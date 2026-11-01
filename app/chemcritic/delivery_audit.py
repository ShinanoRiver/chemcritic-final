"""Delivery tool diagnostics; never promote a remote run to completed."""
import json


def obj(value):
    if isinstance(value,dict):return value
    try:value=json.loads(value)
    except (ValueError,TypeError):return {}
    return value if isinstance(value,dict) else {}


def delivery_attempt(event):
    if event.get('type')!='tool':return None
    c=obj(event.get('content'));m=obj(event.get('metadata'));a=obj(m.get('tool_audit'))
    if c.get('name')!='complete' or not c.get('tool_call_id') or c['tool_call_id']!=a.get('tool_call_id'):return None
    args=obj(a.get('arguments'));result=obj(c.get('content'))
    text=result.get('text')
    accepted=(m.get('tool_success') is True and result.get('status')=='complete'
              and isinstance(text,str) and bool(text.strip()) and text==args.get('text'))
    return {'tool_call_id':c['tool_call_id'],'accepted':accepted,
            'missing_text':not isinstance(args.get('text'),str) or not args['text'].strip(),
            'error_code':'DELIVERY_SUMMARY_REQUIRED' if result.get('code')=='DELIVERY_SUMMARY_REQUIRED' else None}


def summarize(attempts):
    accepted=any(a['accepted'] for a in attempts)
    return {'state':'accepted_text_observed' if accepted else 'delivery_rejected' if attempts else 'not_observed',
            'attempts':len(attempts),'missing_text_attempts':sum(bool(a['missing_text']) for a in attempts),
            'scientific_approval':False}
