"""Deterministic offline research attachment; no source download at runtime."""
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[2]
ENGINE_SHA='ac759e24c01ee5c99beaa3d70a6db601d0848c8d69edef6123d3e0efbeceeeca'
NAME='chemcritic_offline.zip'

PREFLIGHT='''import hashlib,json,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parent
try:
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    for name,expected in manifest.items():
        if Path(name).name!=name or hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('package_hash_mismatch')
    result=subprocess.run([sys.executable,'-X','utf8','-I',str(root/'chemcritic_engine.py'),'--selftest'],capture_output=True,timeout=30)
    (root/'preflight.stdout.log').write_bytes(result.stdout)
    (root/'preflight.stderr.log').write_bytes(result.stderr)
    if result.returncode:raise RuntimeError('selftest_exit_'+str(result.returncode))
    report={'state':'ready','selftest_exit_code':0,'engine_sha256':manifest['chemcritic_engine.py']}
    (root/'preflight.json').write_text(json.dumps(report),encoding='utf-8')
    print(json.dumps(report))
except Exception as exc:
    report={'state':'preparation_failed','error_type':type(exc).__name__}
    (root/'preflight.json').write_text(json.dumps(report),encoding='utf-8')
    print(json.dumps(report));raise SystemExit(1)
'''


def build_bundle():
    engine=(ROOT/'deployment/team44_pinned/chemcritic_engine.py').read_bytes()
    if hashlib.sha256(engine).hexdigest()!=ENGINE_SHA:
        raise ValueError('Pinned research engine hash mismatch')
    bridge=(ROOT/'tools/agent_result_bridge.py').read_bytes()
    files={'chemcritic_engine.py':engine,'agent_result_bridge.py':bridge,
           'run_preflight.py':PREFLIGHT.encode('utf-8')}
    manifest={name:hashlib.sha256(blob).hexdigest() for name,blob in files.items()}
    files['manifest.json']=json.dumps(manifest,sort_keys=True).encode('utf-8')
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        for name,blob in sorted(files.items()):
            info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,blob)
    blob=output.getvalue()
    return blob,{'bundle_sha256':hashlib.sha256(blob).hexdigest(),'engine_sha256':ENGINE_SHA,
                 'bridge_sha256':manifest['agent_result_bridge.py']}
