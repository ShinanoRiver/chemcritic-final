"""Flag observed overconfident wording; not a chemistry correctness evaluator."""
import re


def causal_findings(answer):
    findings=[];section='';seen=set()
    for line in answer.splitlines():
        heading=re.match(r'^\s*#{1,2}\s+(.+)',line)
        if heading:section=heading[1]
        if re.search('文献检索|证据与来源|参考来源|推断边界',section):continue
        for clause in re.split('[。！？；;]',line):
            stripped=clause.strip()
            # Negation of the strong claim is appropriate, not itself an overclaim.
            if re.search(r'不能(?:据此)?(?:认定|确定|断言|证明)|尚(?:不|未)能(?:确定|认定)|不得(?:断言|认定)|不等于|无法认定',stripped):continue
            pattern=r'最可能的?(?:瓶颈|主因|原因)|是[^。！？；;]{0,35}(?:主因|主要原因)|(?:转金属化|催化循环)[^。！？；;]{0,12}几乎无法进行|若[^。！？；;]{0,30}(?:无变化|不变)[^。！？；;]{0,12}(?:则|就)(?:可)?排除'
            if re.search(pattern,stripped) and 'unsupported_causal_certainty' not in seen:
                findings.append({'code':'unsupported_causal_certainty','excerpt':stripped[:500]})
                seen.add('unsupported_causal_certainty')
    return findings
