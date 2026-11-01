"""Bounded post-extraction checks. These do not certify chemical identity."""
import json
import re

GUIDE='''# 输入与执行约定
先按用户原话抽取完整Record，再检查字段，最后只运行一次程序。不要通过反复执行来学习输入结构。
最小结构：{"record_id":"编号","substrate":{"aryl_halide":null,"boronic_acid":null,"product":null},"outcome":{"value":null,"outcome_type":"unknown","label_raw":"用户原话"},"conditions":{"catalyst":null,"catalyst_mol_pct":null,"base":null,"base_eq":null,"solvent":null,"temp_c":null,"time_h":null,"atmosphere":null,"scale_mmol":null},"assay":{"method":null,"internal_standard":null,"quantification_basis":null},"inputs_source":{}}
inputs_source用user_stated记录用户明确值，unknown记录未知。已知数值与未知口径分开，不删除数值。
用户明确“以芳基溴为基准”时：assay.quantification_basis="芳基溴"，并标记对应inputs_source为user_stated。不只把它留在label_raw。
相对芳基溴的mol%是载量基准，与收率计算基准分开，不能相互推导。
用户目标在原始描述/补答记录中单独保留，不放进文献记录或替换实验结果。
名称规范化只允许明确的词汇别名，例如4-溴苯甲醚/4-bromoanisole、苯硼酸/phenylboronic acid、4-甲氧基联苯/4-methoxybiphenyl；保留原名和映射说明。不能据此声称已验证分子结构。
不要猜催化体系受控分类。字段未知就保持未知，不为获得PLACED而填空。
每篇文献独立核对record_id、DOI、页表行；P12与SM-004不是同一文献，不可套用脚注。
检索返回source=knowledge_base时只能称知识库片段；不能称本轮打开了原始PDF。
交付需要调用complete(text="完整六节报告及限制")，text不能省略。出现缺text报错时只修交付，不重跑程序。
'''


def audit_mapping(source,record):
    """Detect this observed omission only; absence of findings is not full fidelity."""
    findings=[]
    # This exact basis wording does not match catalyst-loading wording '相对芳基溴'.
    stated=bool(re.search(r'(?:以|按)\s*芳基(?:溴|卤化物)\s*(?:为基准|计)',source))
    if stated and not (record.get('assay') or {}).get('quantification_basis'):
        findings.append({'code':'missing_explicit_yield_basis','field':'assay.quantification_basis'})
    # Only unambiguous direct result phrases, not arbitrary percentages from literature/targets.
    observed=set()
    for clause in re.split('[，。；;\n]',source):
        if re.search('文献|摘要|目标|希望|至少|期望',clause):continue
        observed.update(re.findall(r'(?:结果|分离收率)\s*(?:为|是|[:：])?\s*(\d+(?:\.\d+)?)\s*%',clause))
    if len(observed)==1 and 'outcome' in record:
        expected=float(next(iter(observed)));value=(record.get('outcome') or {}).get('value')
        if type(value) not in (int,float) or value!=expected:
            findings.append({'code':'observed_value_changed_or_missing','field':'outcome.value'})
    # A controlled classification is the user's declaration, not a model inference.
    # The engine turns catalytic_profile into a tier, so a guessed profile opens
    # tier-scoped placement on chemistry the user never stated.
    profile = record.get('catalytic_profile')
    if isinstance(profile, dict) and profile:
        findings.append({'code': 'invented_derived_classification', 'field': 'catalytic_profile'})
    elif any(str(path).startswith('catalytic_profile') for path in (record.get('inputs_source') or {})):
        findings.append({'code': 'invented_derived_classification', 'field': 'catalytic_profile'})
    return {'state':'needs_review' if findings else 'no_known_omission_detected','findings':findings,
            'semantic_mapping_verified':False,'limitations':'只检查明确基准、单一直接结果措辞与受控分类字段，不验证化学身份或全部自然语言语义。'}


def mapping_event(event,source):
    def obj(v):
        if isinstance(v,str):
            try:v=json.loads(v)
            except ValueError:return {}
        return v if isinstance(v,dict) else {}
    if event.get('type')!='tool':return None
    c=obj(event.get('content'));m=obj(event.get('metadata'));a=obj(m.get('tool_audit'))
    if c.get('name')!='create_file' or not c.get('tool_call_id') or c['tool_call_id']!=a.get('tool_call_id'):return None
    args=obj(a.get('arguments'));raw=args.get('file_contents');path=args.get('file_path','')
    if not isinstance(raw,str) or len(raw)>64000 or not path.endswith('.json'):return None
    record=obj(raw)
    if not isinstance(record.get('outcome'),dict) or 'substrate' not in record:return None
    return {'path':path,'tool_call_id':c['tool_call_id'],'file_write_tool_success':m.get('tool_success'),
            'record':record,'audit':audit_mapping(source,record),'provenance':'captured_create_file_arguments_not_downloaded_file'}
