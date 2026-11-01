"""Execute one hash-bound structured request. Standard library only."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from collections import Counter


def report_context(certificate,request):
    verdicts=certificate.get('verdicts',[])
    selected=[]
    # Preserve certificate order; this is a display sample, never a yield ranking.
    for verdict in verdicts[:3]:
        ref=verdict.get('reference') or {}
        selected.append({'record_id':verdict.get('reference_id'),'verdict':verdict.get('verdict'),
                         'blocking_dimension':verdict.get('blocking_dimension'),
                         'reference':{k:ref.get(k) for k in ['citation','doi','locator','locator_zh']}})
    return {'original_experiment':request.get('original_experiment'),
            'goal_comparison':request.get('goal_comparison_from_local_rules'),
            'verdict_count':len(verdicts),'verdict_counts':dict(Counter(v.get('verdict') for v in verdicts)),
            'display_sample_first_three_not_ranked':selected,'numeric_comparison_allowed':False,'placement_allowed':False,
            'source_verified_by_this_run':False,'scientific_approval':False,
            'limitations':['原始完整证书另行保留，摘要不取代证书核对。','不包含全部记录，未列出不代表不存在。','气氛等未知不能解释为不同，THF不代表非含水。']}


def certificate_for(raw,payload,raw_sha):
    if payload.get('engine_profile','legacy8')=='legacy8':return raw
    return {'schema_version':'chemcritic.bound_team_certificate.v0.1','subject':raw.get('subject'),
        'subject_input':payload['engine_input']['subject'],'engine_profile':payload['engine_metadata'],
        'raw_engine_output_sha256':raw_sha,'input_audit':raw.get('input_audit'),
        'verdicts':raw.get('verdicts',[]),'numeric_comparison_allowed':False,'placement_allowed':False,
        'placement':{'status':'POLICY_DISABLED','reason':'scientific_acceptance_pending'},
        'source_verified_by_this_run':False,'scientific_approval':False}


def main():
    root=Path(__file__).resolve().parent
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    for name,digest in manifest["files"].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:raise ValueError("Input or program hash mismatch")
    request=json.loads((root/"request.json").read_text(encoding="utf-8"))
    output=root/"execution";output.mkdir(exist_ok=False)
    path=output/"input.json";path.write_bytes(json.dumps(request["engine_input"],ensure_ascii=False).encode())
    command=[sys.executable,"-X","utf8","-I",str(root/"chemcritic_engine.py"),"--input",str(path)]
    if request.get('engine_profile') in ('team32','team44'):command.append('--json')
    result=subprocess.run(command,capture_output=True,encoding="utf-8",timeout=60)
    raw_bytes=result.stdout.encode()
    (output/'engine_output.json').write_bytes(raw_bytes)
    if result.returncode==0:
        certificate=certificate_for(json.loads(result.stdout),request,hashlib.sha256(raw_bytes).hexdigest())
        cert_bytes=(raw_bytes if request.get('engine_profile','legacy8')=='legacy8' else json.dumps(certificate,ensure_ascii=False,indent=2).encode())
    else:
        cert_bytes=json.dumps({'state':'engine_failed','exit_code':result.returncode,'original_input_preserved':True,'numeric_comparison_allowed':False,'placement_allowed':False},indent=2).encode()
    (output/"certificate.json").write_bytes(cert_bytes)
    if result.returncode==0:
        context_bytes=json.dumps(report_context(certificate,request),ensure_ascii=False,indent=2).encode()
        (output/'report_context.json').write_bytes(context_bytes)
    (output/"stderr.txt").write_bytes(result.stderr.encode())
    binding={"program_sha256":manifest["files"]["chemcritic_engine.py"],"request_sha256":manifest["files"]["request.json"],
             "exit_code":result.returncode,"certificate_sha256":hashlib.sha256(cert_bytes).hexdigest(),
             "goal_comparison_from_local_rules":request["goal_comparison_from_local_rules"],"command":command}
    if result.returncode==0:binding['report_context_sha256']=hashlib.sha256(context_bytes).hexdigest()
    (output/"binding.json").write_bytes(json.dumps(binding,ensure_ascii=False,indent=2).encode())
    print(json.dumps(binding,ensure_ascii=False))
    return result.returncode


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
