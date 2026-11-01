"""Explicit immutable engine profiles. Scientific permission is a separate local policy."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[2]
LEGACY_SHA='5176a82104878268fd4f16616d28a12b7624f292e2db5ac76eac102c13302848'
TEAM_SHA='d95acc315a2ee1f1fa57c0f54b01d72e25692f73236d42a0f2ce005207dfd924'
TEAM44_SHA='ac759e24c01ee5c99beaa3d70a6db601d0848c8d69edef6123d3e0efbeceeeca'


def load_profile(name):
    if name=='legacy8':
        with zipfile.ZipFile(ROOT/'deployment/frozen_execution_v1/chemcritic_frozen_v1.zip') as archive:engine=archive.read('chemcritic_engine.py')
        metadata={'profile':'legacy8','program_sha256':LEGACY_SHA,'record_count':8}
    elif name=='team32':
        folder=ROOT/'deployment/team32_inputfix'
        metadata=json.loads((folder/'profile.json').read_text(encoding='utf-8'))
        engine=(folder/'chemcritic_engine.py').read_bytes()
        if metadata['program_sha256']!=TEAM_SHA:raise ValueError('Engine profile metadata mismatch')
    elif name=='team44':
        folder=ROOT/'deployment/team44_pinned'
        metadata=json.loads((folder/'profile.json').read_text(encoding='utf-8'))
        engine=(folder/'chemcritic_engine.py').read_bytes()
        if metadata['program_sha256']!=TEAM44_SHA:raise ValueError('Engine profile metadata mismatch')
    else:raise ValueError('Unknown engine profile')
    if hashlib.sha256(engine).hexdigest()!=metadata['program_sha256']:raise ValueError('Pinned engine hash mismatch')
    return engine,metadata


def adapt_team_input(subject):
    # Retain observed values and original labels. Only map explicit structural fields.
    import copy
    result=copy.deepcopy(subject)
    conditions=result['conditions']
    if 'base_equivalents' in conditions:conditions['base_eq']=conditions.pop('base_equivalents')
    sources={}
    for parent in ('outcome','conditions','substrate','assay'):
        for key,value in result.get(parent,{}).items():
            if key=='base_status':continue
            path=parent+'.'+key
            if isinstance(value,dict):
                for child,val in value.items():sources[path+'.'+child]='unknown' if val is None else 'user_stated'
            else:sources[path]='unknown' if value is None or (path=='outcome.outcome_type' and value=='unknown') else 'user_stated'
    result['inputs_source']=sources
    return result


def reference_catalog(name):
    """Read literal data from the hash-verified bundle without executing its code."""
    import ast
    if name not in {'team32','team44'}:return []
    engine,metadata=load_profile(name)
    for node in ast.parse(engine.decode('utf-8-sig')).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='RECORDS_JSON' for t in node.targets):
            data=json.loads(ast.literal_eval(node.value))
            records=data['records']
            if len(records)!=metadata['record_count']:raise ValueError('Reference catalog count mismatch')
            return records
    raise ValueError('Pinned reference catalog unavailable')


def program_bundle(name):
    """Program-only attachment for natural input. It does not certify LLM extraction."""
    import io
    engine,metadata=load_profile(name)
    from .extraction_contract import GUIDE
    files={'chemcritic_engine.py':engine,'profile.json':json.dumps(metadata,ensure_ascii=False,indent=2).encode(),
           'INPUT_GUIDE.md':GUIDE.encode('utf-8')}
    files['manifest.json']=json.dumps({n:hashlib.sha256(data).hexdigest() for n,data in files.items()},indent=2).encode()
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        for path,data in sorted(files.items()):
            info=zipfile.ZipInfo(path,(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;archive.writestr(info,data)
    return output.getvalue(),metadata
