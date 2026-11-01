"""Conservative textual conflict checks, not a scientific correctness evaluator."""
import json
import re

REPORT_STYLE = """
【正文表达要求】
保留六个分区标题供界面展示，分区内部使用自然连贯的短段落。效果评估第一句直接给判断，接着用一两句解释依据及最关键的限制，不以文献清单替代评估。不使用“能否判断目标达成：”“文献对照结论：”“候选解释（均待验证，目前无法确定）：”“能说明的/不能说明的”等密集标签，不使用星级或固定证据/假设/变量/指标四栏模板。
下一步方案先明确最优先的一项行动及理由，再说明应观察什么、结果能支持到哪一步；只有存在独立且必要的后续行动时才追加，不默认凑满三套方案。补记录与改变条件仍须区分，但通过具体句子说明，不靠堆叠标签。
明确的是当前判断和行动顺序，不是把未知原因写成确定事实。信息不足时直说“目前无法判断是否达标”并紧接原因与下一步，不用泛泛免责声明代替判断。未知仍保持未知，不保证提升。文献出处、详细实验信息和推断限制放在对应辅助分区，正文不反复重复同一限制，也不删掉影响判断的关键限制。
"""

REPORT_REQUIREMENTS = """
【报告事实与权限合同】
1. 仅写用户明确提供的条件：THF不等于无水/纯THF；未知碱不等于未加碱。假设必须始终用条件式，不能随后写成当前事实。已知的口径和数值不要重复询问。
2. numeric_comparison_allowed=false时，所有文献（含新检索的库外记录）不得用于用户-文献数值差值、排序或区间定位。库外资料不得绕开证书；用户自设目标比较单独使用binding中的目标结果。COMPARABLE标签不覆盖全局权限。
3. 文献口径未决保留未决。DOI未知则明确未取得，不填xxx或编造标识。正文引用的判定应照录证书，条数以实际记录计数，不要求列出全部32条。
4. 数据库有PDF、历史A_confirmed、搜索摘要或网页片段，都不等于本轮已核验全文。明确实际工具、查询词、来源链接、页表位置和读到的证据；工具不可用如实报告。不得声称后端已独立核验来源。
5. 条件差异不证明原因；收率变化不单独证明某个机制。不输出未经证据支持的主因排名。方案的变量、对照、证据和未决前提分开说明；不保证提升。
6. 按本次声明的版本读取字段：legacy8的reference仅含citation/doi/locator/tier；team32可能包含更多元数据。读取一次发现字段不存在就停止寻找；不存在不等于整个证书缺失。可用verdict、gates、soft_flags及binding的目标比较完成报告，不必列文献数值。不得反复执行相同字段查询；工具无新增信息时明确限制并交付现有报告。
7. 交付优先使用非空text直接提供正文，不要求生成报告附件。默认全文控制在1800个中文字符以内，保留六个二级标题；重点展开至多3条文献，完整记录保留在导出文件，不粘贴程序日志和长哈希。默认至多2次检索与2次原文读取，优先核对最相关原文，无法取得则声明限制，不重复请求同一无新增内容的来源。用户明确要求详细检索时按其范围执行。仅当文件确实已写入且检查可读时才可附加；不存在的文件不能作为attachments。交付工具因附件失败时，去掉不可用附件并修正说明，只重试交付一次，不重跑程序或重复规划写文件。
8. 程序报错不得删改已知数值或用户原话来迎合校验。结果41且口径未知，两项必须分别保留；unknown不等于value=null。字段映射错误最多检查一次定位，无法解决则交付失败环节、已知/未知与仍不可判断的完整说明，不伪造成功证书。
9. 随请求附有固定程序时，只运行该附件及其manifest；禁止git clone最新main、bootstrap其他版本或替换记录库。未附程序时不可自称已使用本地固定版本；无法确认已部署程序版本就声明未核对，不动态安装替代版本。
10. 表头Yield与脚注total conversion/GC等措辞并存时，应分别报告原话与证据，保留术语未决；只确认使用GC不等于已经消除了收率/转化率定义歧义。
11. 调用complete时必须把完整六节报告作为该工具的text参数传入；仅提供attachments或在工具外说“已完成”不算交付。若收到DELIVERY_SUMMARY_REQUIRED，下一次交付必须新增非空text，简述本次交付与尚未完成的项目工作；不得原样重复缺text的调用，也不得为修复交付重跑已完成的计算。正文未写入文件时不附报告文件路径。
12. 用户设定目标且实测与目标口径一致时，效果评估必须明确写出按用户所报数据“达到”或“未达到”目标，不能只说“可以比较”。没有目标、数值缺失或口径未知/不同则明确暂不能判断。目标判断不依赖文献比较权限，不代表独立确认产物。下一步方案应先说明要核查的实验记录、依据与观察指标；文献术语核查不能冒充已完成实验方案。
13. 不得把程序soft_flags自动当作已确认事实：若提示“None vs N2/air”但用户气氛为空，应报告气氛未知、无法比较；若提示THF与含水溶剂族不同，但用户没有说明含水性，只报告溶剂名称不同，不能确认用户体系无水或非含水。保留原始证书，正文明确说明该类启发式提示的限制，不为配合提示补写输入。
14. 结构证据全部由用户填报，系统未独立读取或核验谱图与原始文件。只有结论（如“1H NMR 匹配”）而无观测值时，只能写“用户报告匹配，未附数据”；有方法、观测值与分子式且本地核对通过时，可写“用户所报数据内部一致”，并同时说明未经独立核验；数据自相矛盾时先指出不一致并建议核对，不得沿用“结构已确认”。任何情况下不得写“已确证产物 / 结构已确认 / 身份已确认”，除非明确写明这是记录中的人工复核并给出记录编号。用户自述的谱图匹配不能替代独立确证。
"""
REPORT_REQUIREMENTS += REPORT_STYLE

# Internal engine vocabulary that must never reach the user-facing report.  These
# are field names and status enums, not chemistry words: quoted original wording
# (label_raw) may legitimately contain English such as "isolated yield".
INTERNAL_TOKENS = (
    ("placement", r"(?<![A-Za-z0-9_])placement(?![A-Za-z0-9_])"),
    ("verdict", r"(?<![A-Za-z0-9_])verdicts?(?![A-Za-z0-9_])"),
    ("input_audit", r"(?<![A-Za-z0-9_])input_audit(?![A-Za-z0-9_])"),
    ("inputs_source", r"(?<![A-Za-z0-9_])inputs_source(?![A-Za-z0-9_])"),
    ("soft_flags", r"(?<![A-Za-z0-9_])soft_flags(?![A-Za-z0-9_])"),
    ("candidate_count", r"(?<![A-Za-z0-9_])candidate_count(?![A-Za-z0-9_])"),
    ("needs_evidence_count", r"(?<![A-Za-z0-9_])same_pair_needs_evidence_count(?![A-Za-z0-9_])"),
    ("delta", r"(?<![A-Za-z0-9_])delta_vs_(?:min|max)(?![A-Za-z0-9_])"),
    ("reference_values", r"(?<![A-Za-z0-9_])reference_values(?![A-Za-z0-9_])"),
    ("migration_targets", r"(?<![A-Za-z0-9_])migration_targets(?![A-Za-z0-9_])"),
    ("class_summary", r"(?<![A-Za-z0-9_])class_summary(?![A-Za-z0-9_])"),
    ("execution_facts", r"(?<![A-Za-z0-9_])execution_facts(?![A-Za-z0-9_])"),
    ("engine_sha256", r"(?<![A-Za-z0-9_])engine_sha256(?![A-Za-z0-9_])"),
    ("status_NO_COMPARABLE", r"(?<![A-Za-z0-9_])NO_(?:COMPARABLE|CALIBRATED_REFERENCE|SAME_TIER_REFERENCE|OBSERVED_VALUE|REFERENCE_VALUE)(?![A-Za-z0-9_])"),
    ("status_TIER_UNKNOWN", r"(?<![A-Za-z0-9_])(?:TIER_UNKNOWN|UNDEFINED)(?![A-Za-z0-9_])"),
    ("status_PLACED", r"(?<![A-Za-z0-9_])PLACED(?![A-Za-z0-9_])"),
    ("status_verdict", r"(?<![A-Za-z0-9_])(?:COMPARABLE|BLOCKED|NEEDS_EVIDENCE)(?![A-Za-z0-9_])"),
)


def visible_report_body(answer):
    """Match the page's report-only scope without modifying the raw answer."""
    if '</think>' in answer:
        answer=answer.rsplit('</think>',1)[-1]
    elif '<think>' in answer:
        # The page does not show a parsed report for an unclosed draft marker.
        return ''
    match=re.search(r'^\s*#{2,4}\s*(?:效果评估|实验评价|本次用到的条件|能不能与文献值并排比较|实验建议|证据与来源|实验信息|推断边界|缺失与追问)[^\n]*(?:\n|$)',answer,re.M)
    return answer[match.start():] if match else answer


def internal_token_findings(answer):
    """List engine field names / status enums that leaked into the report prose."""
    answer=visible_report_body(answer)
    hits = []
    for label, pattern in INTERNAL_TOKENS:
        for match in re.finditer(pattern, answer):
            hits.append({"token": match.group(0), "label": label, "at": match.start()})
    seen, ordered = set(), []
    for hit in sorted(hits, key=lambda item: item["at"]):
        if hit["token"] in seen:
            continue
        seen.add(hit["token"])
        ordered.append({"token": hit["token"], "label": hit["label"]})
    return ordered[:8]


def empty_class_claim(answer):
    """Detect "同口径下没有任何记录" style claims that mix two denominators.

    The engine's placement pool is (same outcome type AND same substrate pair),
    while the class table is the whole library grouped by outcome type.  Saying
    the class is empty because the pair-scoped pool is empty is a factual error,
    so a sentence that asserts emptiness *without* naming the pair restriction is
    reported.  Sentences that do name it (同底物对 / 均属其他 / 全库 …) pass.
    """
    for clause in re.split(r"[。！？\n；;]", visible_report_body(answer)):
        if not re.search(r"(?:同口径|该口径|同类口径|此口径|口径内)", clause):
            continue
        if not re.search(r"(?:没有任何|没有一条|一条也没有|不存在|均为零|为零|为\s*0\s*条|是零)", clause):
            continue
        if not re.search(r"(?:记录|参照|文献|数据)", clause):
            continue
        if re.search(r"(?:同底物|相同底物|底物对|产物相同|与你相同|均属其他|其他底物|全库|库内共|共\s*\d+\s*条)", clause):
            continue
        return clause.strip()[:500]
    return None


def failure_report(experiment,exit_code):
    results=experiment.get('results',{}) or {}
    value=results.get('value_pct',results.get('yield_pct'))
    metric=results.get('metric',results.get('yield_type','unknown'))
    explanation=(f'确定性程序退出码为{exit_code}，本次程序判定未完成' if exit_code is not None else '程序执行凭证未能核对，不能确认本次判定已完成')
    return ('## 1. 已知事实与待确认信息\n'
        +f"实验编号：{experiment.get('experiment_id')}；实测数值：{value}%；口径字段：{metric}。\n"
        +'未知条件保持未知，原始输入和用户目标完整保留在导出记录中。\n\n'
        +'## 2. 本次文献检索\n本段为本地程序失败说明，没有据此声称已检索或核验文献。\n\n'
        +f'## 3. 效果评估\n{explanation}；不给出文献数值差值、排序或档内定位。\n\n'
        +'## 4. 下一步方案\n核查失败日志及字段映射，保留实测值，不通过改写实验事实让程序通过。此处不提出化学优化参数。\n\n'
        +'## 5. 最必要的补充问题\n若为程序或环境错误，不要求用户重新提供已经明确的数值或口径；无法查到的信息继续保持未知。\n\n'
        +'## 6. 推断边界\n这是失败状态兜底报告，不是科研结论；未确认产物、原因或文献可比性。')


def _user_facts(experiment):
    """Read the user-side facts for the guards from either record version."""
    experiment = experiment if isinstance(experiment, dict) else {}
    conditions = experiment.get("conditions") if isinstance(experiment.get("conditions"), dict) else {}
    solvent = ""
    system = conditions.get("solvent_system") if isinstance(conditions.get("solvent_system"), dict) else {}
    if system.get("primary"):
        solvent = system["primary"] + (("/" + system["cosolvent"]) if system.get("cosolvent") else "")
    elif isinstance(conditions.get("solvent"), str):
        solvent = conditions["solvent"]
    boronic = None
    reactants = (experiment.get("reaction") or {}).get("reactants") if isinstance(experiment.get("reaction"), dict) else None
    for item in reactants or []:
        if isinstance(item, dict) and item.get("role") == "boronic_acid_or_ester":
            boronic = item.get("equivalents")
    if boronic is None:
        boronic = conditions.get("partner_equivalents")
    return solvent, conditions, boronic


GOAL_WORDING = {"below_target": "按用户所报数据，未达到用户设定目标。",
                "met": "按用户所报数据，已达到用户设定目标。"}
GOAL_REASONS = {"goal_not_set": "用户未设目标，不判断是否达标。",
                "assay_unknown": "实测或目标口径未知，暂不能判断是否达标。",
                "assay_mismatch": "实测与目标口径不同，暂不能判断是否达标。",
                "outcome_missing": "实测数值缺失，暂不能判断是否达标。"}
GOAL_FALLBACK = "目标是否可比较以已核对的本地目标规则结果为准。"

# A "达标" claim, not a mention. Conditional or negated phrasing is excluded below.
_GOAL_OBJECT = r"(?:用户)?(?:设定|自设)?(?:的)?(?:最低|收率|结果)?目标"
_CLAIM_MET = re.compile(r"(?:(?:已经?达到|已经?超过|达成(?:了)?|满足(?:了)?|超过(?:了)?)" + _GOAL_OBJECT + r"|已经?达标)")
_CLAIM_NOT_MET = re.compile(r"(?:(?:未|没有|尚未|未能)达(?:到)?" + _GOAL_OBJECT + r"|未达标)")
_CLAIM_SKIP = re.compile(r"无法|不能|暂不|难以|不判断|是否|未设|没有设|假设|如果|若|不能比较")
_REFERENCE_SENTENCE = re.compile(r"参照|文献|DOI|表\s*\d|脚注|证书")


def goal_summary(goal):
    """The verified arithmetic verdict in one sentence, or None when unknown."""
    if not isinstance(goal, dict) or not goal:
        return None
    return GOAL_WORDING.get(goal.get("state"), GOAL_REASONS.get(goal.get("reason"), GOAL_FALLBACK))


def _goal_section(body):
    """The evaluation section carries the user-facing claim; return (text, scoped)."""
    match = re.search(r"^#{2,4}\s*(?:\d+[.、)]?\s*)?(?:效果评估|实验评价)[^\n]*\n(.*?)(?=^#{1,4}\s|\Z)",
                      body, re.M | re.S)
    return (match.group(1), True) if match else (body, False)


def goal_claim(answer):
    """What the report itself claims about the goal: 'met' / 'not_met' / None."""
    section, scoped = _goal_section(visible_report_body(answer or ""))
    for sentence in re.split(r"[。！？\n；;]", section):
        if _CLAIM_SKIP.search(sentence):
            continue
        if not scoped and _REFERENCE_SENTENCE.search(sentence):
            continue
        if _CLAIM_NOT_MET.search(sentence):
            return "not_met"
        if _CLAIM_MET.search(sentence):
            return "met"
    return None


def goal_conflict(goal, claim):
    """A report may not contradict the arithmetic it was given.

    Only the deterministic direction is a hard conflict (met vs below_target).
    Caliber mismatches and "no goal set" are softer: the report reasoned past a
    limitation rather than contradicting a subtraction.
    """
    if not claim:
        return None
    state = (goal or {}).get("state")
    reason = (goal or {}).get("reason")
    if state in {"met", "below_target"}:
        verified = "met" if state == "met" else "not_met"
        if claim != verified:
            return {"code": "goal_claim_conflict",
                    "excerpt": ("报告写已达标，按用户所报数据算出的结果是未达到" if claim == "met"
                                else "报告写未达到，按用户所报数据算出的结果是已达到")}
        return None
    if reason in {"assay_mismatch", "assay_unknown"}:
        return {"code": "goal_claim_without_comparable_caliber",
                "excerpt": "实测与目标口径不同或未知，报告却对是否达标下了结论"}
    if reason == "goal_not_set":
        return {"code": "goal_claim_without_goal",
                "excerpt": "用户未设目标，报告却声称达到目标"}
    return None


def _evidence_of(experiment):
    """Grade the record's product evidence, or None when no record is available."""
    if not isinstance(experiment, dict) or not isinstance(experiment.get("results"), dict):
        return None
    from .product_evidence import grade
    try:
        return grade(experiment)
    except (AttributeError, TypeError, ValueError):
        return None


# A confirmation claim, not a mention.  Negated or conditional wording is
# excluded below, and so is an explicit attribution to a recorded human review.
_PRODUCT_CLAIM = re.compile(
    r"(?:已确证|已经确证|已确认结构|结构已确认|结构确证|身份已确认|确证为目标产物|已证实为目标产物|"
    r"confirmed\s+(?:the\s+)?(?:structure|identity))", re.I)
_PRODUCT_CLAIM_SKIP = re.compile(r"不能|不得|无法|未|并非|不是|不等于|不代表|若|假设|如果|待|尚|不能确认")
_DATA_AGREES = re.compile(r"(?:数据|数值|积分|m/z|质谱|谱图).{0,12}(?:一致|吻合|相符)")
_DATA_CONFLICT_MENTIONED = re.compile(r"不一致|矛盾|不符|需核对|需核查|待核对")


def product_claim_overreach(answer, evidence):
    """Flag a report that turns user-reported evidence into confirmation.

    The record cannot support "structure confirmed" at any grade: nobody in this
    process verified the spectrum.  The only admissible attribution is a recorded
    human review, which the sentence has to name.
    """
    if not isinstance(evidence, dict):
        return None
    for clause in re.split(r"[。！？\n；;]", visible_report_body(answer)):
        match = _PRODUCT_CLAIM.search(clause)
        if not match:
            continue
        if _PRODUCT_CLAIM_SKIP.search(clause[:match.start()]):
            continue
        if "人工复核" in clause and re.search(r"[A-Za-z0-9][A-Za-z0-9_\-/]{2,}", clause):
            continue
        return {"code": "product_claim_overreach", "excerpt": clause.strip()[:500]}
    return None


def product_data_conflict_ignored(answer, evidence):
    """Flag "the data agree" when the user's own numbers contradict each other."""
    if not isinstance(evidence, dict) or evidence.get("state") != "structured_inconsistent":
        return None
    for clause in re.split(r"[。！？\n；;]", visible_report_body(answer)):
        if not _DATA_AGREES.search(clause):
            continue
        if _DATA_CONFLICT_MENTIONED.search(clause):
            continue
        return {"code": "product_data_conflict_ignored", "excerpt": clause.strip()[:500]}
    return None


def review_report(answer, experiment, certificate, *, research_events=None, catalog=None, scope=None):
    from .causal_review import causal_findings
    findings=causal_findings(answer)
    sentences=re.split(r'[。！？\n]',answer)
    def add(code,excerpt):
        if code not in {r['code'] for r in findings}:
            findings.append({'code':code,'excerpt':excerpt[:500]})
    tokens=internal_token_findings(answer)
    claim=empty_class_claim(answer)
    if claim:add('empty_class_claim',claim)
    # Wording-level product-evidence problems are reported, not answered for: the
    # report stays intact and the reader gets the objective excerpt.
    warnings=[]
    evidence=_evidence_of(experiment)
    if evidence is not None:
        overreach=product_claim_overreach(answer,evidence)
        if overreach:warnings.append(overreach)
        conflict=product_data_conflict_ignored(answer,evidence)
        if conflict:warnings.append(conflict)
    if certificate.get('numeric_comparison_allowed') is False:
        for sentence in re.split(r'[。！？\n；;]|但|然而',answer):
            if ('文献' in sentence or '参照' in sentence) and re.search('用户|您的|本次|当前|实测',sentence) and re.search(r'\d+(?:\.\d+)?\s*个?百分点',sentence) and re.search('差距|相差|差\\s*\\d|高出|低于|高于',sentence):
                if not re.search('不能|禁止|不提供|不得|不给出|没有给出|未给出|不进行|未进行|不计算|未计算',sentence):
                    add('unauthorized_literature_delta',sentence)
    solvent,_conditions,_boronic=_user_facts(experiment)
    conditions=_conditions
    if certificate.get('numeric_comparison_allowed') is False:
        for sentence in re.split(r'[。！？\n；;]|但|然而',answer):
            if re.search(r'文献|Miyaura|Weeden',sentence) and re.search(r'收率|用户值|用户结果',sentence) and re.search(r'高于|低于|接近',sentence) and re.search(r'用户|实测',sentence) and not re.search('不能|不得|不输出|不作|不做|不构成',sentence):
                add('unauthorized_literature_ranking',sentence)
    # Inspect only the user's experiment section; never treat literature amounts as user facts.
    for match in re.finditer(r'^#{1,6}[^\n]*(?:实验信息|已知事实)[^\n]*\n(.*?)(?=^#{1,6}\s|\Z)',answer,re.M|re.S):
        for sentence in re.split('[。\n]',match[1]):
            if re.search('若|假设|例如|建议|未提供|未知|不应|不能',sentence):continue
            if conditions.get('scale_mmol') is None and re.search(r'\d+(?:\.\d+)?\s*mmol',sentence,re.I):
                add('invented_scale_or_equivalents',sentence)
            if _boronic is None and re.search(r'苯硼酸.{0,15}\d+(?:\.\d+)?\s*(?:equiv|当量)',sentence,re.I):
                add('invented_scale_or_equivalents',sentence)
    if conditions.get('atmosphere') in (None,'','unknown','未知'):
        for sentence in sentences:
            if '气氛不同' in sentence and re.search(r'未提供|未知|None|null',sentence) and not re.search('不能|不得|不应|不等于',sentence):
                add('unknown_as_difference',sentence)
    if solvent.lower()=='thf':
        for sentence in sentences:
            for clause in re.split('[；;，,、]',sentence):
                if re.search(r'THF\s*[（(]?\s*(?:非含水|无水)',clause,re.I) and not re.search('若|如果|假如|假设|未知|未说明|未提供|不能|不应|不等于|是否',clause):
                    add('invented_water_content',clause)
            if re.search(r'(?:您的|当前|本次)(?:的)?\s*无水\s*THF',sentence) and not re.search('若|如果|假如|假设(?:当前|本次|使用|为)|未知|未说明|未提供|不应|不能|并未',sentence):
                add('invented_water_content',sentence)
    match=re.search(r'10\.\d{4,9}/[^\s，。；（）()]+(?:xxx|XXX)[^\s，。；（）()]*',answer)
    if match:add('placeholder_doi',match.group())
    count=len(certificate.get('verdicts',[]))
    match=re.search(r'全部\s*(\d+)\s*条参照记录',answer)
    if match and int(match[1])!=count:add('reference_count_conflict',match.group())
    if research_events is not None:
        kb_only=any('knowledge_base' in row.get('output_excerpt','') for row in research_events)
        primary_read=any(re.search(r'scrape|browse|fetch|read_file',row.get('tool',''),re.I)
                         and row.get('tool_success') is True and bool(row.get('output_excerpt','').strip())
                         for row in research_events)
        if kb_only and not primary_read:
            for sentence in sentences:
                for clause in re.split('[；;]',sentence):
                    claim=re.search(r'(?:本轮|上一轮|本次).*?已(?:核验|核对|读取).*?(?:原始\s*PDF|原文全文|全文)',clause)
                    if claim and not re.search('不能|不等于|不代表|不应|不得',clause[:claim.end()]):
                        add('unsupported_fulltext_claim',clause)
    for paragraph in answer.split('\n\n'):
        if re.search('分别|不是同|并非同|不同文献|非同一',paragraph):continue
        for record in catalog or []:
            rid=record.get('record_id','');doi=record.get('doi','')
            if not rid or not re.search(r'(?<![A-Za-z0-9_.-])'+re.escape(rid)+r'(?![A-Za-z0-9_.-])',paragraph):continue
            # Bounded, explicit observed misattribution; this is not a generic citation verifier.
            if doi and doi!='10.3390/molecules23102435' and re.search(r'Molecules\s*2018|10\.3390/molecules23102435',paragraph) and re.search('这三条|这几条|即确认|属于|来自|DOI[:：]',paragraph):
                add('reference_identity_conflict',paragraph)
    return {'state':'blocked_known_conflict' if findings else 'no_known_conflict_detected',
        'findings':findings,'format_findings':([{'code':'internal_engine_token','tokens':tokens}] if tokens else []),
        'consistency_warnings':warnings,
        'scientific_approval':False,'source_verified':False,
        'product_evidence':(None if evidence is None else {
            'state':evidence.get('state'),'label':evidence.get('label'),
            'index':evidence.get('index'),'structure_confirmed':False}),
        'engine_scope':(None if scope is None else {'in_scope':bool(scope.get('in_scope')),
                                                     'reaction_type':scope.get('reaction_type'),
                                                     'reaction_label':scope.get('reaction_label')}),
        'limitations':'有限文本检查；未检出不等于报告正确或科学验收通过。'}


def research_event(event,key):
    """Save bounded original tool evidence, never treat names alone as source verification."""
    def obj(value):
        if isinstance(value,str):value=json.loads(value)
        return value if isinstance(value,dict) else {}
    if event.get('type')!='tool':return None
    content=obj(event.get('content',{}));meta=obj(event.get('metadata',{}))
    audit=obj(meta.get('tool_audit',{}));name=content.get('name','')
    if not re.search(r'search|scrape|browse|fetch|read_file',name,re.I):return None
    if not content.get('tool_call_id') or content['tool_call_id']!=audit.get('tool_call_id'):return None
    def clean(value):
        if isinstance(value,dict):
            return {k:('[已隐藏]' if re.search(r'authorization|cookie|api.?key|password|secret|token',k,re.I) else clean(v)) for k,v in value.items()}
        if isinstance(value,list):return [clean(v) for v in value[:100]]
        if isinstance(value,str):
            text=value.replace(key,'[已隐藏]') if key else value
            return re.sub(r'sp_live_[A-Za-z0-9_-]+|Bearer\s+[A-Za-z0-9._-]+','[已隐藏]',text)
        return value
    args=clean(obj(audit.get('arguments',{})))
    arg_text=json.dumps(args,ensure_ascii=False)
    args_truncated=len(arg_text)>6000
    if args_truncated:args={'truncated_excerpt':arg_text[:6000]}
    output=clean(content.get('content',''))
    raw=json.dumps(output,ensure_ascii=False)
    return {'tool':name,'tool_call_id':content['tool_call_id'],'tool_success':meta.get('tool_success'),'arguments':args,'arguments_truncated':args_truncated,
        'output_excerpt':raw[:12000],'output_truncated':len(raw)>12000,
        'source_verified':False,'provenance':'platform_tool_audit_event_not_independent_source_review'}
