"""Lossless input context and bounded checks of explicitly labelled text fields.

This is not a general natural-language or chemical-structure parser. Ambiguous
or unlabelled evidence stays unverified; original user data is always retained.
"""
import json
import re
from . import product_evidence
from .report_contract import visible_report_body


def text_evidence(text):
    patterns={
        'formula':r'(?:目标)?分子式\s*(?:为|是|[:：=])?\s*([A-Z][A-Za-z0-9]{0,100})',
        'proton_integral':r'总积分(?:数值)?\s*(?:为|是|[:：=])?\s*(\d+(?:\.\d+)?)\s*(?:H|个氢)?',
    }
    extracted={};sources={}
    if not re.search(r'1H\s*NMR|¹H\s*NMR|氢谱',text,re.I):
        return {'state':'not_extracted','reason':'no_explicit_proton_nmr_method','independently_verified':False}
    for key,pattern in patterns.items():
        matches=list(re.finditer(pattern,text))
        values={m[1] for m in matches}
        if len(values)!=1 or any(re.search(r'不是|并非|假如|例如|不是说',text[max(0,m.start()-8):m.start()]) for m in matches):
            return {'state':'not_extracted','reason':'missing_or_ambiguous_labelled_'+key,'independently_verified':False}
        extracted[key]=next(iter(values))
        sources[key]=[{'text':m[0],'start':m.start(),'end':m.end()} for m in matches]
    entry={'method':'1H NMR','provenance':'user_report',
           'raw_spectrum_provided':False,'formula':extracted['formula'],
           'proton_integral':float(extracted['proton_integral'])}
    # Deliberately omit supports_target: arithmetic is not an identity declaration.
    evidence=product_evidence.grade({'results':{'characterization':[entry]}})
    return {'state':'labelled_arithmetic_checked','source_spans':sources,
            'checked_fields':extracted,'product_evidence':evidence,
            'support_flag_is_user_declaration':False,'independently_verified':False,
            'limitation':'仅核对明确标注的分子式与总积分；未恢复完整表征、未确认结构或用户匹配声明。'}


def build_context(data):
    if isinstance(data,str):
        try:value=json.loads(data)
        except json.JSONDecodeError:value={'user_description':data}
    else:value=data
    if not isinstance(value,dict):value={}
    experiment=value.get('experiment')
    text=value.get('user_description') or value.get('request_text')
    context={'raw_user_data_preserved':True,'scientific_approval':False,
             'authority':'user_supplied_data_not_independent_verification',
             'record_policy':{'preserve_original_values':True,
                              'do_not_change_values_to_pass_checks':True,
                              'discrepancy_cause':'not_determined_by_arithmetic'}}
    if isinstance(experiment,dict):
        context['product_evidence']=product_evidence.grade(experiment)
        context['full_record_available']=True
        scale=(experiment.get('conditions') or {}).get('scale_mmol')
        if scale is not None:
            context['known_scale']={'value_mmol':scale,'source_path':'experiment.conditions.scale_mmol'}
    if isinstance(text,str) and text:
        context['text_evidence_check']=text_evidence(text)
        # Only explicit scale / limiting-reagent statements qualify. Do not
        # interpret catalyst or additive mmol as the reaction scale.
        matches=[]
        for line in text.splitlines():
            if not re.search(r'规模|限量试剂|限量反应物',line):continue
            for m in re.finditer(r'(?<![\d.])(\d+(?:\.\d+)?)\s*mmol\b',line,re.I):
                matches.append({'value_mmol':float(m[1]),'source_text':line})
        if len({m['value_mmol'] for m in matches})==1 and 'known_scale' not in context:
            context['known_scale']=matches[0]
        if re.search(r'不为.*修改|保留.*数值|不要.*修改.*(?:积分|分子式)',text):
            context['explicit_preservation_requested']=True
    return context


def report_conflicts(text,context):
    evidence=context.get('product_evidence') or (context.get('text_evidence_check') or {}).get('product_evidence') or {}
    findings=[]
    body=visible_report_body(text)
    if context.get('known_scale'):
        for sentence in re.split(r'[。\n；;]',body):
            if re.search(r'规模',sentence) and re.search(r'未记录|未提供|缺失|未知|需补[录记]',sentence):
                # A grouped missing-fields list must not erase an explicit scale.
                if re.search(r'规模[^\d。\n；;]{0,65}(?:未记录|未提供|缺失|未知)|(?:未记录|未提供|缺失|未知|需补[录记])[^\d。\n；;]{0,65}规模',sentence):
                    findings.append({'code':'known_scale_reported_missing','excerpt':sentence.strip()[:250],
                                     'expected':context['known_scale']})
    if evidence.get('state') not in {'structured_warning','structured_inconsistent'}:return findings
    for sentence in re.split(r'[。\n；;，,]',body):
        if re.search(r'总积分.*(?:氢数|分子式).*一致|数据内部一致|全部(?:核对)?一致',sentence) and not re.search(r'不能|不得|不应|不一致|未能|不能称',sentence):
            findings.append({'code':'product_evidence_check_conflict','excerpt':sentence[:250],
                             'expected_summary':evidence.get('prompt_summary')})
    for sentence in re.split(r'[。\n；;]',body):
        if (re.search(r'(?:修改|修正|调整|改写).*(?:模拟录入|积分|分子式|使其.*一致)|(?:积分|分子式).*(?:改为|调整为)',sentence)
                and not re.search(r'不得|不要|不能|不应|不为|不建议',sentence)):
            findings.append({'code':'original_values_change_advice','excerpt':sentence.strip()[:250],
                             'expected':'保留原值，核查并注明差异，不改写数据来通过检查'})
        if (re.search(r'积分|相差\s*\d.*H',sentence)
                and re.search(r'(?:常见于|来自|归因于|导致|引起).*(?:可交换|残留溶剂|OH|NH)|(?:可交换质子|残留溶剂).*(?:导致|引起)',sentence)
                and not re.search(r'不能|不得|不应|无法|尚不能|不推断',sentence)):
            findings.append({'code':'unsupported_integral_cause','excerpt':sentence.strip()[:250],
                             'expected':'仅报告算术差异，具体原因尚未确定'})
    return findings
