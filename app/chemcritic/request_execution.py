"""Bind original form fields, package the pinned engine and independently check its certificate."""
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from .gate_diagnostics import adapt_record
from .rules import review

ROOT=Path(__file__).resolve().parents[2]
ENGINE_SHA="5176a82104878268fd4f16616d28a12b7624f292e2db5ac76eac102c13302848"


def prepare(experiment,profile='legacy8'):
    from . import reaction_profiles, schema_v2
    record_v2=schema_v2.normalize(experiment)
    view=reaction_profiles.legacy_view(record_v2)
    if view is None:
        raise ValueError('本次反应不在固定判定引擎范围内，未创建任务。')
    local_result=review(record_v2,[])
    record,notes=adapt_record(view,subject=True)
    subject=asdict(record)
    for key in ("outcome_value","outcome_type","label_raw"):subject.pop(key,None)
    result=view["results"]
    subject["outcome"]={"value":result.get("yield_pct"),"outcome_type":result.get("yield_type","unknown"),
        "label_raw":f"用户表单字段：yield_type={result.get('yield_type','unknown')};yield_pct={result.get('yield_pct')}"}
    subject["_extraction"]={"label_raw_provenance":"structured_form_fields"}
    subject["conditions"]["base_status"]=view["conditions"].get("base_status","unknown")
    subject["conditions"]["catalyst_loading_basis"]=view["conditions"].get("catalyst_loading_basis")
    if profile in ('team32','team44'):
        from .engine_profiles import adapt_team_input
        subject=adapt_team_input(subject)
    # The only route to tier-scoped placement: the user's own declaration.
    # A partial declaration is passed through as absent, never completed by us.
    declared=schema_v2.classification_complete(record_v2)
    if declared:
        subject["catalytic_profile"]={key:record_v2["catalyst"]["classification"][key]
                                      for key in schema_v2.CLASSIFICATION_FIELDS}
    payload={"original_experiment":record_v2,"engine_input":{"simulated":record_v2["simulated"],"subject":subject},
             "mapping_provenance":"trusted_structured_form_fields_not_LLM_transcription",
             "classification_declared":declared,
             "classification_missing":schema_v2.classification_missing(record_v2),
             "goal_comparison_from_local_rules":local_result["goal_comparison"],
             "engine_scope":reaction_profiles.scope(record_v2),
             "record_profile":"chemcritic.experiment.v0.2"}
    try:
        if profile=='legacy8':
            with zipfile.ZipFile(ROOT/"deployment/frozen_execution_v1/chemcritic_frozen_v1.zip") as archive:
                engine=archive.read("chemcritic_engine.py")
            metadata={'profile':'legacy8','program_sha256':ENGINE_SHA,'record_count':8}
        else:
            from .engine_profiles import load_profile
            engine,metadata=load_profile(profile)
    except (OSError,zipfile.BadZipFile,KeyError):
        raise ValueError("固定部署包不可用，尚未创建远端任务。") from None
    if hashlib.sha256(engine).hexdigest()!=metadata['program_sha256']:raise ValueError("Frozen engine version mismatch")
    if profile in ('team32','team44'):payload.update(engine_profile=profile,engine_metadata=metadata)
    with tempfile.TemporaryDirectory() as temp:
        folder=Path(temp);(folder/"engine.py").write_bytes(engine)
        (folder/"input.json").write_bytes(json.dumps(payload["engine_input"],ensure_ascii=False).encode())
        command=[sys.executable,"-X","utf8","-I",str(folder/"engine.py"),"--input",str(folder/"input.json")]
        if profile in ('team32','team44'):command.append('--json')
        observed=subprocess.run(command,capture_output=True,encoding="utf-8",timeout=60)
    if observed.returncode!=0:
        # The pinned engine is hash-locked, so an interpreter it cannot parse is a
        # setup problem, not an input problem.  Name it instead of blaming the form.
        stderr=observed.stderr or ''
        if 'badly formed help string' in stderr or 'unsupported format character' in stderr:
            raise ValueError(
                '固定判定引擎与当前 Python '+sys.version.split()[0]+
                ' 不兼容（3.14 起 argparse 会校验帮助字符串里的 %），请改用 Python 3.11 运行本服务')
        raise ValueError("Local frozen-engine input validation failed")
    expected=json.loads(observed.stdout)
    from .request_execution_driver import certificate_for
    expected=certificate_for(expected,payload,hashlib.sha256(observed.stdout.encode()).hexdigest())
    files={"chemcritic_engine.py":engine,"request.json":json.dumps(payload,ensure_ascii=False,indent=2).encode(),
           "run_request.py":(Path(__file__).parent/"request_execution_driver.py").read_bytes()}
    manifest={"files":{n:hashlib.sha256(b).hexdigest() for n,b in files.items()}}
    files["manifest.json"]=json.dumps(manifest,indent=2).encode()
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w") as archive:
        for name,data in sorted(files.items()):
            info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,data)
    blob=buffer.getvalue()
    return {"bundle":blob,"zip_sha256":hashlib.sha256(blob).hexdigest(),"request_sha256":manifest["files"]["request.json"],
            "expected":expected,"payload":payload,"mapping_notes":notes,'program_sha256':metadata['program_sha256'],'engine_profile':profile}


def verify(contract,certificate_bytes,binding):
    expected_sha=contract.get('program_sha256',ENGINE_SHA)
    if type(binding.get('exit_code')) is not int or binding.get("exit_code")!=0 or binding.get("program_sha256")!=expected_sha or binding.get("request_sha256")!=contract["request_sha256"]:
        raise ValueError("Execution binding differs from original request")
    if binding.get("certificate_sha256")!=hashlib.sha256(certificate_bytes).hexdigest():raise ValueError("Certificate byte hash differs")
    certificate=json.loads(certificate_bytes)
    canonical=lambda value:json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    if canonical(certificate)!=canonical(contract["expected"]):raise ValueError("Certificate differs from local frozen engine")
    if canonical(binding.get("goal_comparison_from_local_rules"))!=canonical(contract["payload"]["goal_comparison_from_local_rules"]):raise ValueError("Goal comparison differs")
    return {"state":"artifact_matches_local_frozen_engine","program_sha256":expected_sha,
            "request_sha256":contract["request_sha256"],"certificate":certificate,
            "goal_comparison":contract["payload"]["goal_comparison_from_local_rules"],
            "raw_tool_execution_verified":False,"source_verified_by_this_run":False}


def execution_event_proven(events,binding):
    runs=[e for e in events if e["tool"]=="execute_command"]
    if len(runs)!=1:return False
    run=runs[0]
    finished=run if run.get("completed") else next((e for e in events if e["tool"]=="watch_task" and e.get("session_name")==run.get("session_name") and e.get("completed")),None)
    if not finished or finished.get("exit_code")!=0 or finished.get("output_truncated"):return False
    text=finished.get("output","").replace("\\n","").replace("\\r","")
    text="".join(text.split())
    return all(binding[k] in text for k in ("program_sha256","request_sha256","certificate_sha256"))
