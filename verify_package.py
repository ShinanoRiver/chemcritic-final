import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parent
manifest=json.loads((root/'MANIFEST.json').read_text(encoding='utf-8'))
bad=[name for name,digest in manifest.items() if not (root/name).is_file() or hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest]
print(json.dumps({'status':'failed' if bad else 'passed','files':len(manifest),'mismatched':bad,'agent_calls':0},ensure_ascii=False))
raise SystemExit(bool(bad))
