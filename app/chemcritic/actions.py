"""Prioritize evidence collection, not reaction optimization or diagnosis.

Actions are written against the generic record (roles and additive types), not
against Suzuki field names.  The list stays short and ordered by how much it
unblocks the current judgement.
"""


def next_checks(record, evidence, goal_comparison, unknowns, sources, scope=None):
    checks = []
    gaps = set(unknowns)
    results = record.get("results") or {}
    scope = scope or {"in_scope": True, "reasons": []}
    evidence = evidence if isinstance(evidence, dict) else {"state": evidence}
    evidence_state = evidence.get("state")

    def add(rule_id, title, fields, why, materials, resolution, limits, related_label=None):
        related = []
        for source in sources:
            if related_label and any(item["label"] == related_label and item["state"] == "unknown" and item["precedent"] is not None
                                     for item in source.get("field_comparisons", [])):
                related.append({"record_id": source["record_id"], "source_id": source["source_id"],
                                "url": source["url"], "locator": source["locator"]})
        checks.append({"priority": len(checks) + 1, "rule_id": rule_id, "title": title,
                       "triggered_fields": fields, "why": why, "requested_materials": materials,
                       "expected_resolution": resolution, "limits": limits,
                       "basis_type": "input_evidence_gap", "related_sources": related[:2]})

    if not scope.get("in_scope", True):
        add("A00_ENGINE_SCOPE", "先把反应类型与反应物角色核对清楚", ["reaction.type", "reaction.reactants"],
            "固定判定引擎按 Suzuki–Miyaura（芳基卤化物 + 硼酸/硼酸酯）成对判定；本次记录不在该范围内，"
            "因此不做可比性判定。角色由你在表单中声明，系统不会从化学名称推断。",
            ["核对反应类型是否选对（选“其他”时写上具体类型）",
             "核对每个反应物的角色；确实属于 Suzuki 时把角色改为芳基卤化物 / 硼酸（酯）"],
            "角色声明与反应类型一致后，本次即可进入固定引擎的可比性判定；"
            "若反应本身不是 Suzuki，则不进入判定，只保留事实复盘与证据核查。",
            "这一步只解决“能否判定”，不代表反应数据或文献证据已经核验。")

    if evidence_state in {"missing", "contradictory"}:
        add("A01_PRODUCT_EVIDENCE", "先核查目标产物的结构证据", ["results.characterization"],
            "当前结构证据缺失或与目标矛盾，尚不能确认所报结果对应目标产物。",
            ["核对原始表征记录、样品编号与目标产物", "记录支持与不支持目标结构的观察，由领域人员审核"],
            "补充后可重新判断结构证据状态，再决定是否恢复目标比较。",
            "系统未自动解析谱图；有表征记录不等于产物纯度或收率已确认。")

    if evidence_state == "structured_inconsistent":
        add("A05B_EVIDENCE_CONFLICT", "先解决用户所报结构数据内部的不一致", ["results.characterization"],
            "本次填写的结构证据互相矛盾：" + "；".join((evidence.get("reasons") or [])[:2]) +
            "。数据自相矛盾时，任何“结构已确认”的说法都不成立。",
            ["核对分子式、加合物与积分是否抄录正确", "核对原始谱图/质谱文件中的对应数值",
             "保留原始数据，不要为了匹配而改写观测值"],
            "改到数值互相一致后，本地核对才能通过；仍不等于独立确证。",
            "系统只做算术核对，不判断谱图真伪，也不替代原始文件复核。")

    if "results.value_pct" in gaps:
        add("A02_OUTCOME_VALUE", "明确本次实际报告的结果", ["results.value_pct"],
            "尚未提供可描述的结果数值。", ["从原始记录核对结果数值及计算过程"],
            "记录数值后才能检查目标差距。", "不替用户估计或补造收率。")
    if "results.metric" in gaps:
        add("A03_OUTCOME_METRIC", "先确认百分比的测量口径", ["results.metric"],
            "现有百分比的含义未明确，无法与用户目标或先例对齐。",
            ["核对是分离收率、GC/LC 定量、NMR 定量还是转化率", "记录计算基准、实际使用的定量方法及内标/校准说明（如适用）"],
            "明确口径后重新评估目标比较；文献数值比较仍保持关闭。",
            "不能凭使用了GC或NMR就推定测到的是收率，也不要求所有方法都使用内标。")
    elif goal_comparison["reason"] == "assay_mismatch":
        add("A04_GOAL_METRIC", "核对用户目标与结果是否同口径", ["results.metric", "user_goal.metric"],
            "用户目标与实测结果属于不同的测量口径。", ["确认原先设定目标的口径及当前结果定义"],
            "目标与结果对齐后再判断达标；不换算不同口径的百分比。", "不能为了得出达标结论而改写原始目标。")

    if evidence_state == "user_report_only":
        add("A05_REPORTED_EVIDENCE", "把“结构匹配”的自述换成可核对的数据", ["results.characterization"],
            "当前只有用户报告结构匹配，没有方法、观测值或原始文件，本地无法做任何核对。",
            ["记录方法（如 1H NMR / HRMS）与具体观测值（峰位与积分、m/z）",
             "给出目标产物分子式，便于本地核对积分与质量",
             "保留审核人或原始文件编号；未审核时继续标为用户报告"],
            "有了数据后，本地能判断所报数值内部是否一致；仍不构成独立确证。",
            "本地程序不解析谱图，数据一致也不等于样品就是目标产物。")
    elif evidence_state == "structured_documented" and any(
            not item.get("raw_spectrum_provided", False) for item in results.get("characterization", [])):
        add("A05D_EVIDENCE_DOCUMENT", "补上可核对的参照值与原始文件编号", ["results.characterization"],
            "观测值已记录，但缺少可核对的参照（分子式、加合物）或原始文件，本地核对无法完成。",
            ["填写目标产物分子式与加合物形式", "记录谱图/质谱文件的编号或存放位置"],
            "补齐后本地可核对积分总数与实测 m/z 是否一致。",
            "本地只做算术核对，不判断谱图真伪或样品身份。")

    if not sources:
        add("A06_FIND_PRECEDENT", "补充可追溯的文献先例", [],
            "本次评估没有可用先例，无法提供文献参照。" if scope.get("in_scope", True)
            else "本次评估没有可用先例；即使补充，也需先解决判定范围问题才能做数值比较。",
            ["通过SciencePal或人工检索完整底物对", "保留原文/SI链接、表格条目及结果定义，再导入复盘"],
            "获取先例后可展示条件差异；没有先例不等于不存在相关文献。",
            "不能补造来源或把库内未命中解释为反应没有先例。")

    additive_gaps = [item for item in record.get("additives") or []
                     if item.get("equivalents") is None and item.get("loading_mol_pct") is None]
    if "additives" in gaps or additive_gaps:
        fields = ([item.get("name") for item in additive_gaps] or ["additives"])
        add("A07_ADDITIVE_RECORD", "查清添加剂的原始使用记录", fields,
            "除催化剂外的试剂（碱/酸/盐/氧化剂/还原剂/配体等）使用信息不完整，相关条件无法对齐。",
            ["核查称量、配液或操作记录", "记录加入的试剂类型、名称与当量；确实没加也请注明“明确未加入”"],
            "补齐后可把相关条件从未知改为相同或不同。",
            "文献中加了某种试剂不能证明本次未加，也不能证明该试剂导致结果差异。",
            ("碱名称" if scope.get("in_scope", True) else None))

    loading_fields = [key for key in ("catalyst.loading_mol_pct", "catalyst.loading_basis") if key in gaps]
    if loading_fields:
        add("A08_LOADING_BASIS", "核对催化剂载量与计算基准", loading_fields,
            "载量或其计算基准未明确，尚不能完整解释这个mol%。",
            ["核对实际投料记录", "记录载量相对哪个组分计算；已知数值不必重新填写"],
            "补齐载量定义后才能完整描述本次反应条件。", "载量差异不自动意味着催化剂不足或过量。",
            ("载量（mol%）" if scope.get("in_scope", True) else None))

    condition_fields = [key for key in ("conditions.scale_mmol", "conditions.solvent_system.volume_ml",
                                        "reaction.reactants.equivalents", "conditions.atmosphere") if key in gaps]
    if condition_fields:
        add("A09_CONTEXT_RECORD", "补全规模、用量与气氛记录", condition_fields,
            "仍有条件字段缺失，后续复盘与复现缺少上下文。",
            ["从原操作记录核对规模、溶剂体积、投料当量与基准、气氛"],
            "能够更完整地记录条件并显示与文献的差异。", "补齐记录不会自动确定失败原因。")

    if goal_comparison["reason"] == "goal_not_set":
        add("A10_OPTIONAL_GOAL", "如需判断达标，再设定自己的目标", ["user_goal.minimum_yield_pct"],
            "未设用户目标时只报告结果与证据。", ["可选择填写目标值及结果口径，也可以继续不设目标"],
            "用户明确目标后才判断是否达到预期。", "不使用文献收率替用户设定目标。")
    # The complete followup list is retained separately; this panel stays small.
    return checks[:3]
