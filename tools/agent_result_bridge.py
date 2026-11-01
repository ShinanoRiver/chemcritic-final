"""Single engine execution and compact factual context. Standard library only."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normalize_unknown_sources(source):
    """Expand an unknown container declaration only if all its existing leaves are null.

    Preserve known values. The explicit unknown outcome-type sentinel is encoded
    as null for the source-audit contract, with the adaptation recorded.
    A populated or ambiguous container is rejected, never erased.
    """
    value=copy.deepcopy(source);declarations=value.get('inputs_source') or {};changes=[]
    # Repair only an exact, unambiguous provenance-path alias. Never invent a
    # value or move a top-level value into conditions; retain the original file.
    for leaf in ('aryl_halide','boronic_acid'):
        old='equivalents.'+leaf;new='conditions.equivalents.'+leaf
        if old not in declarations:continue
        actual=((value.get('conditions') or {}).get('equivalents') or {})
        if 'equivalents' in value or leaf not in actual:
            raise ValueError('Ambiguous equivalents provenance path')
        label=declarations[old]
        if new in declarations and declarations[new]!=label:
            raise ValueError('Conflicting equivalents provenance declarations')
        if (label=='unknown' and actual[leaf] is not None) or label not in {'user_stated','unknown'}:
            raise ValueError('Unsafe equivalents provenance alias')
        declarations[new]=declarations.pop(old)
        changes.append({'source_path':old,'normalized_source_path':new,
                        'reason':'exact_nested_equivalents_provenance_alias'})
    for path,label in list(declarations.items()):
        if label!='unknown':continue
        field=value;missing=False
        for component in path.split('.'):
            if not isinstance(field,dict) or component not in field:
                missing=True;break
            field=field[component]
        if missing:
            # This declaration contains no input value. Preserve the original
            # document and log the removed dangling unknown-only declaration.
            declarations.pop(path)
            changes.append({'source_path':path,'reason':'absent_unknown_declaration_removed'})
            continue
        if path=='outcome.outcome_type' and field=='unknown':
            value['outcome']['outcome_type']=None
            changes.append({'source_path':path,'original_value':'unknown','normalized_value':None,
                            'reason':'explicit_unknown_sentinel_to_null'})
            continue
        if not isinstance(field,dict):continue
        def leaves(node,prefix):
            if isinstance(node,dict) and node:
                for key,child in node.items():yield from leaves(child,prefix+'.'+key)
            else:yield prefix,node
        expanded=list(leaves(field,path))
        if not expanded or any(leaf is not None for _,leaf in expanded):
            raise ValueError('Unknown container contains known or ambiguous values')
        declarations.pop(path)
        declarations.update({leaf_path:'unknown' for leaf_path,_ in expanded})
        changes.append({'source_path':path,'expanded_unknown_leaf_paths':[leaf for leaf,_ in expanded]})
    outcome=value.get('outcome') or {}
    assay=value.get('assay')
    # An explicitly user-stated GC/NMR yield already names the measurement
    # method. Map only that name; never infer calibration or internal standard.
    label=str(outcome.get('label_raw') or '')
    hints={'gc':('GC收率','GC 收率','GC yield','气相收率'),
           'nmr':('NMR收率','NMR 收率','NMR yield','核磁收率')}
    kind=outcome.get('outcome_type')
    if (declarations.get('outcome.outcome_type')=='user_stated' and
        kind in hints and any(h.lower() in label.lower() for h in hints[kind]) and
        (assay is None or isinstance(assay,dict)) and not (assay or {}).get('method') and
        declarations.get('assay') not in {'unknown','memory'} and
        declarations.get('assay.method')!='memory'):
        if assay is None:value['assay']={}
        value['assay']['method']=kind.upper()
        declarations['assay.method']='user_stated'
        changes.append({'source_path':'assay.method','normalized_value':kind.upper(),
                        'reason':'method_named_by_explicit_user_outcome_label'})
    if declarations:value['inputs_source']=declarations
    return value,changes


def compact_context(result):
    placement=result.get('placement') or {}
    verdicts=result.get('verdicts') or []
    candidates=[v for v in verdicts if v.get('verdict')=='COMPARABLE']
    pending=[v for v in verdicts if v.get('verdict')=='NEEDS_EVIDENCE' and
             all((v.get('gates') or {}).get(str(i),{}).get('status')=='PASS' for i in (1,2))]
    # Classification and calibration remain distinct; no new scientific rule is inferred.
    paired=[]
    bindings=placement.get('comparables') or []
    bound_ids={r if isinstance(r,str) else r.get('reference_id') or r.get('record_id')
               for r in bindings if isinstance(r,(str,dict))}
    for v in candidates:
        if (v.get('reference_id') in bound_ids and v.get('calibration')=='calibrated'
                and v.get('subject_calibration')=='calibrated' and v.get('ref_calibration')=='calibrated'):
            paired.append(v.get('reference_id'))
    flags_allowed=all(k not in result or result[k] is True for k in ['numeric_comparison_allowed','placement_allowed'])
    # A single explicitly bound reference is unambiguous. Multiple-reference delta
    # attribution requires an engine-specific contract, so this bridge leaves it closed.
    unambiguous=len(bound_ids)==1 and bound_ids.issubset(set(paired))
    audit=result.get('input_audit') or {}
    authorized=(audit.get('status')=='pass' and unambiguous and placement.get('status')=='PLACED'
                and placement.get('delta_vs_min') is not None and flags_allowed)
    facts=[]
    for row in candidates[:4]:
        facts.append({k:row.get(k) for k in ['reference_id','verdict','calibration','subject_calibration','ref_calibration','non_independent','reference','soft_flags']})
    # Library-wide statistics and the user's placement pool share one records list
    # but not one filter. Both denominators travel together so the report cannot
    # turn "library has 19 isolated records" into "19 comparable records".
    classes=[row for row in result.get('classes') or [] if isinstance(row,dict)]
    class_counts={row.get('outcome_type'):row.get('count') for row in classes if row.get('outcome_type')}
    class_labels={row.get('outcome_type'):row.get('outcome_type_label') for row in classes if row.get('outcome_type')}
    library_record_count=sum(value for value in class_counts.values() if isinstance(value,int)) or (result.get('coverage') or {}).get('total_values')
    scope_keys=('scope','scope_basis','outcome_type','outcome_type_label','pair',
                'library_total_count','library_same_class_count','same_pair_count')
    placement_scope={key:placement.get(key) for key in scope_keys if key in placement}
    if not placement_scope:
        placement_scope={'scope':'unavailable_in_this_engine_version',
                         'note':'引擎未提供分母字段；不要自行推断全库分布'}
    return {'input_audit':result.get('input_audit'),'placement':placement,
            'candidate_count':len(candidates),'candidate_facts':facts,
            'candidate_facts_count':len(facts),'candidate_facts_truncated':len(facts)<len(candidates),
            'same_pair_needs_evidence_count':len(pending),
            'same_pair_needs_evidence_facts':[{k:v.get(k) for k in ['reference_id','reference','blocking_dimension','unlock_condition']} for v in pending[:3]],
            'numeric_comparison_authorized_by_observed_fields':authorized,
            'delta_from_engine':placement.get('delta_vs_min') if authorized else None,
            'library':{'record_count':library_record_count,'class_counts':class_counts,
                       'class_labels':class_labels,'scope':'library_wide',
                       'basis':'whole pinned library grouped by outcome type; not filtered by your substrate pair'},
            'placement_scope':placement_scope,
            'population_rule':('library.class_counts 与 placement_scope.same_pair_count 分母不同：'
                               '本次同口径同底物对为 0 条，不代表库内没有该口径的记录；'
                               '库内该口径有 N 条，也不代表本次有 N 条可参照。两句话必须分别给数，不得互相否定。'),
            'classification_is_not_numeric_authorization':True,
            'warning':'This context summarizes saved engine output; it does not verify chemistry, primary sources, calibration or product identity.'}


def execute(engine,input_path,out,timeout=60):
    engine=Path(engine).resolve();input_path=Path(input_path).resolve();out=Path(out).resolve()
    engine_bytes=engine.read_bytes();input_bytes=input_path.read_bytes()
    source=json.loads(input_bytes.decode('utf-8-sig'))
    normalized,mapping_changes=normalize_unknown_sources(source)
    fingerprint={'engine_sha256':sha(engine_bytes),'input_sha256':sha(input_bytes),
                 'bridge_sha256':sha(Path(__file__).read_bytes())}
    out.mkdir(parents=True,exist_ok=True)
    marker=out/'execution.json';context_path=out/'report_context.json'
    if marker.exists():
        previous=json.loads(marker.read_text(encoding='utf-8'))
        if any(previous.get(k)!=v for k,v in fingerprint.items()):
            raise ValueError('Existing execution belongs to different input or engine; not rerun')
        if previous.get('state')!='context_ready':
            raise ValueError('Existing execution unfinished or failed; not rerun')
        raw=context_path.read_bytes()
        if sha(raw)!=previous.get('context_sha256'):
            raise ValueError('Saved context changed; not reused or rerun')
        return {**json.loads(raw),'reused_saved_context':True}
    # Exclusive creation prevents two helpers from launching the engine twice.
    with marker.open('x',encoding='utf-8') as file:
        json.dump({**fingerprint,'state':'execution_started'},file)
    # Retain the raw input and record a lossless declaration-shape adaptation separately.
    (out/'original_input.json').write_bytes(input_bytes)
    normalized_path=out/'normalized_input.json'
    normalized_path.write_text(json.dumps(normalized,ensure_ascii=False,indent=2),encoding='utf-8')
    command=[sys.executable,'-X','utf8','-I',str(engine),'--json','--input',str(normalized_path)]
    try:
        with (out/'engine_output.json').open('wb') as stdout,(out/'engine_stderr.log').open('wb') as stderr:
            run=subprocess.run(command,stdout=stdout,stderr=stderr,timeout=timeout,check=False)
        if run.returncode:
            raise RuntimeError('Engine exited '+str(run.returncode))
        result=json.loads((out/'engine_output.json').read_text(encoding='utf-8-sig'))
        if not isinstance(result,dict) or not isinstance(result.get('verdicts'),list):
            raise ValueError('Engine output schema unavailable')
        if isinstance(source,dict) and source.get('record_id') and result.get('subject')!=source['record_id']:
            raise ValueError('Engine result does not match current input identity')
        context={**compact_context(result),'input_mapping_changes':mapping_changes,'execution_facts':{**fingerprint,'engine_exit_code':run.returncode,
            'normalized_input_sha256':sha(normalized_path.read_bytes()),
            'engine_output_sha256':sha((out/'engine_output.json').read_bytes()),
            'engine_output_path':str(out/'engine_output.json'),'source_verified_by_this_run':False}}
        raw=json.dumps(context,ensure_ascii=False,indent=2).encode('utf-8')
        context_path.write_bytes(raw)
        marker.write_text(json.dumps({**fingerprint,'state':'context_ready','context_sha256':sha(raw)}),encoding='utf-8')
        return context
    except Exception as exc:
        marker.write_text(json.dumps({**fingerprint,'state':'failed','error_type':type(exc).__name__}),encoding='utf-8')
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',required=True,type=Path)
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    args=parser.parse_args()
    try:
        print(json.dumps(execute(args.engine,args.input,args.output_dir),ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({'state':'context_unavailable','error_type':type(exc).__name__,
                          'message':'No report facts verified; inspect the original execution, do not rerun blindly.'}))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
