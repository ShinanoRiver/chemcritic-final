"""Small, conservative subset of the agreed ChemCritic rules.

S1/S2/S3, literature scoring and causal diagnosis deliberately remain unset.

Input handling is reaction-agnostic (see :mod:`schema_v2`).  Only records whose
reaction profile matches the shipped engine get literature comparability work;
everything else still receives facts, evidence gaps, the user's own goal
comparison and next checks, with an explicit "out of engine scope" statement.
"""

from decimal import Decimal
import math
from urllib.parse import urlparse

from . import reaction_profiles, schema_v2
from .comparison import compare_fields, publication_key
from .actions import next_checks
from .gate_diagnostics import diagnose
from . import product_evidence

YIELD_TYPES = schema_v2.METRICS
BASE_STATES = schema_v2.PRESENCE_STATES

# One exception type for the whole input path; the field path stays machine readable.
ValidationError = schema_v2.ValidationError


def _text(value, path):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(path, "must be a non-empty string")


def validate(experiment, precedents):
    record = schema_v2.normalize(experiment)
    if not isinstance(precedents, list):
        raise ValidationError("precedents", "must be a list")
    ids = set()
    for index, source in enumerate(precedents):
        prefix = f"precedents[{index}]"
        if not isinstance(source, dict):
            raise ValidationError(prefix, "must be an object")
        for key in ("record_id", "source_id", "locator", "url", "provenance"):
            _text(source.get(key), f"{prefix}.{key}")
        if source["record_id"] in ids:
            raise ValidationError(f"{prefix}.record_id", "duplicate record ID")
        ids.add(source["record_id"])
        url = urlparse(source["url"])
        if url.scheme not in {"http", "https"} or not url.netloc:
            raise ValidationError(f"{prefix}.url", "must be an HTTP(S) source URL")
        outcome = source.get("outcome")
        if not isinstance(outcome, dict):
            raise ValidationError(f"{prefix}.outcome", "must be an object")
        value = outcome.get("value_pct")
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValidationError(f"{prefix}.outcome.value_pct", "must be a number between 0 and 100 or null")
        metric = outcome.get("yield_type", "unknown")
        if not isinstance(metric, str) or metric not in YIELD_TYPES:
            raise ValidationError(f"{prefix}.outcome.yield_type", "unsupported outcome type")
        for key in ("conditions", "reaction", "import_metadata"):
            if key in source and not isinstance(source[key], dict):
                raise ValidationError(f"{prefix}.{key}", "must be an object")
        if "source_links" in source:
            if not isinstance(source["source_links"], list):
                raise ValidationError(f"{prefix}.source_links", "must be a list")
            for link in source["source_links"]:
                _text(link, f"{prefix}.source_links")
                parsed_link = urlparse(link)
                if parsed_link.scheme not in {"http", "https"} or not parsed_link.netloc:
                    raise ValidationError(f"{prefix}.source_links", "must contain HTTP(S) URLs")
    return record


def _goal_comparison(record):
    results = record.get("results") or {}
    goal = record.get("user_goal") or {}
    value, target = results.get("value_pct"), goal.get("minimum_yield_pct")
    actual, wanted = results.get("metric", "unknown"), goal.get("metric", "unknown")
    comparison = {"state": "unavailable", "reason": None, "gap_pp": None}
    if target is None:
        comparison["reason"] = "goal_not_set"
    elif value is None:
        comparison["reason"] = "outcome_missing"
    elif "unknown" in (actual, wanted):
        comparison["reason"] = "assay_unknown"
    elif actual != wanted:
        comparison["reason"] = "assay_mismatch"
    else:
        gap = Decimal(str(target)) - Decimal(str(value))
        comparison.update(state="below_target" if gap > 0 else "met",
                          reason="goal_below" if gap > 0 else "goal_met", gap_pp=float(gap))
    return comparison


def _evidence_state(record):
    """Coarse product-evidence state; the grading itself lives in product_evidence.

    "User-reported" is not the same as "worthless": the grade separates a bare
    conclusion from observation values that survive local arithmetic.  Neither is
    independent verification, so ``independently_verified_by_system`` stays false
    in every branch.
    """
    return product_evidence.state_of(record)


def _collect_unknowns(record, evidence_state, scope=None):
    """Field-level unknowns and the question that would resolve each one."""
    conditions = record.get("conditions") or {}
    results = record.get("results") or {}
    catalyst = record.get("catalyst") or {}
    solvent = conditions.get("solvent_system") or {}
    reactants = schema_v2.reactants(record)
    goal = record.get("user_goal") or {}
    unknowns, followups = [], []

    def missing(field, question):
        unknowns.append(field)
        followups.append({"field": field, "question": question})

    if results.get("value_pct") is None:
        missing("results.value_pct", "本次测得的结果百分比是多少？")
    if results.get("metric") == "unknown":
        missing("results.metric", "这个百分比是分离收率、GC/LC 定量、NMR 定量还是转化率？")
    if goal.get("minimum_yield_pct") is None:
        missing("user_goal.minimum_yield_pct", "是否有明确用户目标？可以不设定；未设定时不判断达标。")
    elif goal.get("metric", "unknown") == "unknown":
        missing("user_goal.metric", "目标百分比对应哪种收率或转化率口径？")
    if results.get("value_pct") is not None and not results.get("basis"):
        missing("results.basis", "该结果百分比以哪一种投料为计算基准？")
    if evidence_state == "missing":
        missing("results.characterization", "有哪些支持目标产物结构的表征记录？")
    elif evidence_state != "human_review_recorded":
        # A more precise question than "did you characterize it": the grade says
        # which part of the evidence is still only an assertion.
        question = product_evidence.followup(evidence_state)
        if question and question[0] not in unknowns:
            missing(*question)

    if not catalyst.get("name"):
        missing("catalyst.name", "使用了哪种催化剂？")
    if catalyst.get("loading_mol_pct") is None:
        missing("catalyst.loading_mol_pct", "催化剂载量是多少 mol%，相对哪个组分？")
    elif not catalyst.get("loading_basis"):
        missing("catalyst.loading_basis", "已知催化剂载量；这个 mol% 相对哪一种投料计算？")
    ligand = catalyst.get("ligand") or {}
    if not ligand.get("name") and ligand.get("loading_mol_pct") is None:
        missing("catalyst.ligand", "是否另加了配体？加了哪一种、多少 mol%（未加请填“明确未加”）。")
    elif ligand.get("name") and ligand.get("loading_mol_pct") is None:
        missing("catalyst.ligand.loading_mol_pct", f"配体 {ligand.get('name')} 的用量是多少 mol%？")

    if not (record.get("additives") or []) and record.get("additives_listed_complete") is not True:
        unresolved = [schema_v2.ADDITIVE_TYPES[kind] for kind in
                      ("base", "acid", "salt", "oxidant", "reductant", "cocatalyst", "phase_transfer")
                      if schema_v2.presence_state(record, kind) == "unknown"]
        if unresolved:
            missing("additives", "除催化剂外还加入了哪些试剂（" + "、".join(unresolved[:4]) +
                    "）？各自用量多少；确实没加也请注明“明确未加入”。")
    else:
        for item in record.get("additives") or []:
            if item.get("equivalents") is None and item.get("loading_mol_pct") is None:
                label = item.get("name") or ("未记录名称的" + schema_v2.ADDITIVE_TYPES.get(item.get("type"), "添加剂"))
                missing(f"additives[{item.get('type')}].amount",
                        f"{label}，用量是多少（当量或 mol%）？")
                break

    if not solvent.get("primary"):
        missing("conditions.solvent_system.primary", "溶剂（或混合溶剂体系）是什么？")
    if solvent.get("primary") and solvent.get("water_content", "unknown") == "unknown" and _water_matters(record):
        missing("conditions.solvent_system.water_content",
                "该溶剂体系的水分状态是否有记录（明确无水 / 明确含水 / 未知）？")
    if conditions.get("temperature_C") is None:
        missing("conditions.temperature_C", "反应温度是多少摄氏度？")
    if conditions.get("time_h") is None:
        missing("conditions.time_h", "反应时间是多少小时？")
    if conditions.get("atmosphere") is None:
        missing("conditions.atmosphere", "使用什么反应气氛（空气 / N2 / Ar 等）？")
    if conditions.get("scale_mmol") is None:
        missing("conditions.scale_mmol", "反应规模是多少 mmol？")
    if solvent.get("volume_ml") is None:
        missing("conditions.solvent_system.volume_ml", "溶剂总体积是多少 mL？")

    if all(item.get("equivalents") is None for item in reactants):
        basis = schema_v2.equivalents_basis_label(record)
        missing("reaction.reactants.equivalents",
                "各反应物的投料当量是多少" + (f"（以 {basis} 为基准）" if basis else "，以哪一个投料为基准") + "？")
    if (results.get("repeat_attempts") is None) and not results.get("replicates"):
        missing("results.repeat_attempts", "同条件重复了几次，每次结果分别是多少？")
    if scope and scope.get("in_scope"):
        absent = schema_v2.classification_missing(record)
        if absent:
            missing("catalyst.classification",
                    "可选补充：催化体系分类（还缺" + "、".join(absent) +
                    "）。它只影响“档内定位”这一层，本轮其它判定照常进行；系统不会根据催化剂名称替你推断。")
    return unknowns, followups


def _water_matters(record):
    """Only ask about water content when an additive could care (salt/base/aqueous)."""
    kinds = {item.get("type") for item in record.get("additives") or []}
    return bool(kinds & {"base", "acid", "salt"})


def review(experiment, precedents=None):
    """Return facts and restrictions without modifying the supplied records."""
    precedents = [] if precedents is None else precedents
    record = validate(experiment, precedents)
    scope = reaction_profiles.scope(record)
    view = reaction_profiles.legacy_view(record)

    comparison = _goal_comparison(record)
    evidence = product_evidence.grade(record)
    evidence_state = evidence["state"]
    unknowns, followups = _collect_unknowns(record, evidence_state, scope)
    blocked = {"causal_attribution", "repeatability", "precedent_numeric"}
    if comparison["state"] == "unavailable":
        blocked.add("target_comparison")
    if not scope["in_scope"]:
        blocked.add("engine_scope")

    # Only implement the unambiguous negative evidence branches from B v0.2.
    # "Reported by the user" is not itself a reason to block: the grade already
    # separates a bare claim from checkable data.  Self-contradicting data is not
    # blocked here either — the yield arithmetic is a separate question — but it
    # is carried into the warnings and the next-check list.
    status, reason_code, triggered_fields = None, None, []
    pending = ["用户报告的结构证据是否足以进入S1，仍待A/B明确。"]
    results = record.get("results") or {}
    if evidence_state in {"missing", "contradictory"}:
        status, reason_code = "S3", "evidence_gap"
        triggered_fields = ["results.characterization"]
        comparison = {"state": "unavailable", "reason": "evidence_gap", "gap_pp": None}
        blocked.add("target_comparison")
        pending = []
    elif results.get("value_pct") is None and results.get("metric") == "unknown":
        status, reason_code = "S3", "input_gap"
        triggered_fields = ["results.value_pct", "results.metric"]
        pending = []
    if status is None and comparison["state"] == "unavailable" and comparison["reason"] != "goal_not_set":
        pending.append("有目标但结果数值或口径不全时的S1/S2/S3映射仍待确认。")

    source_comparisons = []
    for source in precedents:
        source_type = source["outcome"].get("yield_type", "unknown")
        actual_type = results.get("metric", "unknown")
        if "unknown" in (actual_type, source_type):
            reason = "assay_unknown"
        elif actual_type != source_type:
            reason = "assay_mismatch"
        else:
            reason = "mvp_numeric_disabled"
        entry = {
            "source_id": source["source_id"], "record_id": source["record_id"],
            "locator": source["locator"], "url": source["url"],
            "provenance": source["provenance"],
            "numeric_comparison_allowed": False, "reason": reason,
            "outcome_type": source_type,
            "verification": source.get("verification"),
            "import_metadata": source.get("import_metadata"),
            "paper_id": publication_key(source),
            "reported_outcome": source["outcome"],
            "field_comparisons": [],
            "evidence_level_claimed": source.get("evidence_level_claimed"),
            "field_evidence": source.get("field_evidence", {}),
            "limitations": source.get("limitations", []),
            "source_links": source.get("source_links", []),
            "gate_diagnostics": None,
        }
        if view is not None:
            entry["field_comparisons"] = compare_fields(view, source)
            entry["gate_diagnostics"] = diagnose(view, source, [
                other["record_id"] for other in precedents
                if other["record_id"] != source["record_id"]
                and publication_key(source) is not None
                and publication_key(other) == publication_key(source)
            ])
        else:
            entry["limitations"] = list(entry["limitations"]) + [
                "当前反应不在固定判定引擎范围内，未做逐字段文献对照或八维门槛诊断。"]
        source_comparisons.append(entry)

    imported = any(source.get("import_metadata", {}).get("mode") == "sciencepal_file_import" for source in precedents)
    papers = {publication_key(source) for source in precedents if publication_key(source)}
    base = schema_v2.additive_by_type(record, "base")
    warnings = (["模拟案例，非团队真实实验。"] if record.get("simulated") else []) \
        + (["没有提供先例；未判断是否存在相关文献。"] if not precedents else []) \
        + ["不推断失败真因；未启用SciencePal实时连接、排序评分或LLM解释。"]
    if not scope["in_scope"]:
        warnings.insert(0, "本次反应不在固定判定引擎范围内：" + "".join(scope["reasons"]))
    if evidence_state == 'structured_warning':
        warnings.append('本次结构证据有待核查项：'+'；'.join(evidence['reasons'][:3])+'。保留原始数据，不能概括为全部核对一致。')
    if evidence_state == "structured_inconsistent":
        warnings.append("本次填写的结构证据内部不一致：" + "；".join(evidence["reasons"][:2]) +
                        "。先核对原始记录，不要据此认定产物已确认。")
    return {
        "schema_version": "chemcritic.review.v0.3", "rule_version": "core-0.3.0-partial",
        "experiment_id": record["experiment_id"], "simulated": record["simulated"],
        "status": status, "reason_code": reason_code, "triggered_fields": triggered_fields,
        "status_policy": "role_B_v0.2_partial_pending_A_confirmation", "pending_decisions": pending,
        "numeric_comparison_policy": {"enabled_in_mvp": False, "reason": "role_B_v0.2_explicit_disable"},
        "goal_comparison": comparison,
        "engine_scope": scope,
        "product_evidence": evidence,
        "base": {"state": schema_v2.presence_state(record, "base"), "name": (base or {}).get("name")},
        "additives": [{"name": item.get("name"), "type": item.get("type"),
                       "equivalents": item.get("equivalents"),
                       "loading_mol_pct": item.get("loading_mol_pct")}
                      for item in record.get("additives") or []],
        "additives_listed_complete": record.get("additives_listed_complete"),
        "reaction": {"type": (record.get("reaction") or {}).get("type"),
                      "label": scope["reaction_label"],
                      "reactants": [{"name": item.get("name"), "role": item.get("role"),
                                     "equivalents": item.get("equivalents"),
                                     "limiting": item.get("limiting")} for item in schema_v2.reactants(record)],
                      "product": ((record.get("reaction") or {}).get("product") or {}).get("name"),
                      "equivalents_basis": schema_v2.equivalents_basis_label(record)},
        "conditions": {"solvent": schema_v2.solvent_label(record),
                        "water_content": ((record.get("conditions") or {}).get("solvent_system") or {}).get("water_content"),
                        "temperature_C": (record.get("conditions") or {}).get("temperature_C"),
                        "time_h": (record.get("conditions") or {}).get("time_h"),
                        "atmosphere": (record.get("conditions") or {}).get("atmosphere"),
                        "scale_mmol": (record.get("conditions") or {}).get("scale_mmol"),
                        "catalyst": (record.get("catalyst") or {}).get("name"),
                        "catalyst_loading_mol_pct": (record.get("catalyst") or {}).get("loading_mol_pct"),
                        "ligand": ((record.get("catalyst") or {}).get("ligand") or {}).get("name")},
        "results": {"value_pct": results.get("value_pct"), "metric": results.get("metric"),
                     "metric_label": schema_v2.metric_label(record), "basis": results.get("basis")},
        "unknowns": unknowns, "blocked_dimensions": sorted(blocked),
        "followups": followups, "precedent_comparisons": source_comparisons,
        "next_checks": next_checks(record, evidence, comparison, unknowns, source_comparisons, scope),
        "retrieval": {"mode": "sciencepal_file_import" if imported else "provided_records",
                       "record_count": len(precedents), "independent_publication_count": len(papers),
                       "live_retrieval_performed": False},
        "warnings": warnings,
    }
