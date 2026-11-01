"""Grade the product-identity evidence a record actually contains.

What this module is for
-----------------------
Every structural observation in this application was typed by the user: there is
no independent copy of the spectrum, the HRMS report or the isolated sample.  If
"not independently verified" were used to dismiss all of that, every record would
collapse to the same empty state, and a bare "1H NMR matches" would be worth
exactly as much as a full peak list that survives arithmetic.  That is the wrong
boundary.

The right boundary is between *an assertion* and *data that can be checked*:

``missing``              no characterization entry at all.
``contradictory``        the user's own entry says the observation does **not**
                         support the target product.
``user_report_only``     an assertion ("1H NMR matches") with no observation
                         values attached.
``structured_documented``observation values are present but no local check could
                         be completed (missing formula, unparseable formula, …).
``structured_consistent``at least one local mechanical check passed and none
                         failed.
``structured_inconsistent``the user's numbers contradict the user's declared
                         formula or each other; resolve before relying on it.
``human_review_recorded``a person recorded a review with a reference.

Two things never change with the grade: the evidence is still the user's, and the
system still has not verified it.  ``independently_verified_by_system`` stays
``False`` at every grade, and no grade licenses the report to say "structure
confirmed".  The grade answers "how much can the user's own report carry?", not
"is this the right molecule?".

The mechanical checks are deliberately narrow and reproducible:

* monoisotopic mass computed from the declared formula vs the reported m/z;
* the declared proton count vs the reported ¹H integral;
* whether the named method has any data behind it at all.

They are arithmetic, not spectroscopy.  A passing check means the numbers agree,
not that the spectrum was recorded on the right sample.
"""

from __future__ import annotations

import math
import re

# Masses are monoisotopic, in u.  Only common organic/organometallic elements are
# listed; an unknown element makes a check "skipped", never "failed".
MONOISOTOPIC = {
    "H": 1.00782503207, "B": 11.0093054, "C": 12.0, "N": 14.0030740048,
    "O": 15.9949146196, "F": 18.99840322, "Na": 22.9897692809,
    "Mg": 23.985041700, "Si": 27.9769265325, "P": 30.97376163,
    "S": 31.97207100, "Cl": 34.96885268, "K": 38.96370668,
    "Ca": 39.96259098, "Fe": 55.9349375, "Cu": 62.9295975,
    "Zn": 63.9291422, "Br": 78.9183371, "I": 126.904473,
}
PROTON = 1.007276466      # m/z shift of [M+H]+, not the H atom mass
SODIUM_CATION = 22.989218  # 22.9897692809 - electron
ELECTRON = 0.00054858

ADDUCTS = {
    "[M+H]+": ("proton", 1),
    "[M-H]-": ("proton", -1),
    "[M+Na]+": ("sodium", 1),
    "M+": ("electron", 1),
}
DEFAULT_ADDUCT = "[M+H]+"

# ppm windows for the HRMS check.  Wide on purpose: the published value may be
# low-resolution, and a mismatch here is a reason to recheck, not a verdict.
HRMS_PASS_PPM = 10.0
HRMS_WARN_PPM = 50.0

# 1H integral vs formula H count.  Exchangeable protons and residual solvent are
# ordinary causes of a small difference, so only a large gap is a failure.
INTEGRAL_PASS = 0.5
INTEGRAL_WARN = 2.0

STATES = {
    "missing": {"index": 0, "label": "未提供表征证据", "blocks_goal_comparison": True},
    "contradictory": {"index": 0, "label": "表征与目标产物矛盾", "blocks_goal_comparison": True},
    "user_report_only": {"index": 1, "label": "用户报告匹配（未附数据）", "blocks_goal_comparison": False},
    "structured_documented": {"index": 2, "label": "用户提供观测数据（未完成本地核对）", "blocks_goal_comparison": False},
    "structured_consistent": {"index": 3, "label": "用户数据本地核对一致（非独立核验）", "blocks_goal_comparison": False},
    "structured_warning": {"index": 2, "label": "用户数据存在待核查项（非独立核验）", "blocks_goal_comparison": False},
    "human_review_recorded": {"index": 4, "label": "有人工复核记录（非系统核验）", "blocks_goal_comparison": False},
    "structured_inconsistent": {"index": 0, "label": "用户数据与声明不一致", "blocks_goal_comparison": False},
}

BLOCKING_STATES = {"missing", "contradictory"}

DEFAULT_LIMITATION = (
    "结构证据全部来自用户填报，系统未独立读取谱图、原始质谱文件或样品。"
    "等级描述的是“用户所报数据能被本地机械核对到什么程度”，不是分子身份确认。"
)

RAISE_IT = {
    "missing": ["补充支持目标产物的表征记录（方法、观测值、谱图或附件编号）",
                "若确实没有任何表征，请如实保持为空，不要用名称匹配代替证据"],
    "contradictory": ["核对样品编号与目标产物是否对应",
                      "记录与目标不符的具体观察（杂质、峰位不符、m/z 不符）",
                      "确认结论是否应改为“未得到目标产物”"],
    "user_report_only": ["补充该方法的具体观测值（峰位与积分、m/z、熔点等）",
                         "给出目标产物的分子式，便于本地核对积分与质量"],
    "structured_documented": ["补上可核对的参照值（分子式、总积分或加合物形式）",
                              "附上谱图或原始文件的编号，便于人工复核"],
    "structured_consistent": ["由人工复核谱图原件并留存复核记录",
                              "需要独立确证时，另做 HRMS/2D NMR 或与标准品比对"],
    "structured_warning": ["核对原始数据与警告原因，保留有差异的观测值", "由领域人员确认差异，不自动改写数值以消除警告"],
    "structured_inconsistent": ["先核对分子式、加合物与积分是否抄录正确",
                                "保留原始数据，不要为让数值吻合而改写观测值"],
    "human_review_recorded": ["保留复核人、日期与原始文件编号",
                              "复核记录不等于系统核验，报告中仍需注明来源"],
}

_ELEMENT = re.compile(r"([A-Z][a-z]?)(\d{0,6})")


def parse_formula(text):
    """Return ({element: count}, None) or (None, reason).  No parentheses."""
    if not isinstance(text, str) or not text.strip():
        return None, "未填写分子式"
    raw = text.strip().replace(" ", "")
    counts, position = {}, 0
    while position < len(raw):
        match = _ELEMENT.match(raw, position)
        if not match:
            return None, "分子式格式无法解析"
        element, digits = match.group(1), match.group(2)
        if element not in MONOISOTOPIC:
            return None, f"分子式含未收录元素 {element}"
        count = int(digits) if digits else 1
        if count <= 0:
            return None, "分子式含非正原子数"
        counts[element] = counts.get(element, 0) + count
        position = match.end()
    return (counts, None) if counts else (None, "分子式为空")


def monoisotopic_mass(counts):
    return sum(MONOISOTOPIC[element] * count for element, count in counts.items())


def theoretical_mz(counts, adduct=DEFAULT_ADDUCT):
    """Theoretical m/z for one adduct, or None when the adduct is not supported."""
    kind = ADDUCTS.get(adduct)
    if kind is None:
        return None
    mass = monoisotopic_mass(counts)
    if kind == ("proton", 1):
        return mass + PROTON
    if kind == ("proton", -1):
        return mass - PROTON
    if kind == ("sodium", 1):
        return mass + SODIUM_CATION
    if kind == ("electron", 1):
        return mass - ELECTRON
    return None


def ppm_error(observed, theoretical):
    if not theoretical:
        return None
    return (observed - theoretical) / theoretical * 1e6


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def _has_data(entry):
    return any(_number(entry.get(key)) is not None
               for key in ("proton_integral", "mz")) or bool(
        (entry.get("formula") or "").strip()) or bool((entry.get("observation_text") or "").strip())


def _checks(entry):
    """Local, mechanical checks for one characterization entry."""
    checks = []
    formula_text = entry.get("formula")
    counts, formula_error = parse_formula(formula_text) if formula_text else (None, "未填写分子式")
    integral = _number(entry.get("proton_integral"))
    mz = _number(entry.get("mz"))
    adduct = entry.get("mz_adduct") or DEFAULT_ADDUCT
    method = (entry.get("method") or "")

    if counts is not None:
        checks.append({"id": "formula_parse", "state": "pass",
                       "detail": f"分子式 {formula_text} 可解析，单同位素质量 {monoisotopic_mass(counts):.4f}"})
    elif formula_text:
        checks.append({"id": "formula_parse", "state": "warn", "detail": formula_error})

    # ¹H integral vs the proton count the declared formula implies.
    if integral is not None and counts is not None:
        protons = counts.get("H", 0)
        difference = integral - protons
        if abs(difference) <= INTEGRAL_PASS:
            checks.append({"id": "integral_vs_formula", "state": "pass",
                           "detail": f"总积分 {integral:g}H 与分子式氢数 {protons} 一致"})
        elif abs(difference) <= INTEGRAL_WARN:
            checks.append({"id": "integral_vs_formula", "state": "warn",
                           "detail": (f"总积分 {integral:g}H 与分子式氢数 {protons} 相差 {abs(difference):g}H，"
                                      "仅为数值差异，原因尚未确定，需核查原始记录；不得据此推断具体化学原因")})
        else:
            checks.append({"id": "integral_vs_formula", "state": "fail",
                           "detail": f"总积分 {integral:g}H 与分子式氢数 {protons} 相差 {abs(difference):g}H"})
    elif integral is not None:
        checks.append({"id": "integral_vs_formula", "state": "skipped",
                       "detail": ("分子式无法解析，未核对积分总数" if formula_text
                                  else "未填写分子式，无法核对积分总数")})

    # Reported m/z vs the mass computed from the declared formula.
    if mz is not None and counts is not None:
        theory = theoretical_mz(counts, adduct)
        if theory is None:
            checks.append({"id": "hrms_vs_formula", "state": "skipped",
                           "detail": f"未识别的加合物 {adduct}，未核对 m/z"})
        else:
            ppm = ppm_error(mz, theory)
            detail = f"{adduct} 理论 m/z {theory:.4f}，实测 {mz:.4f}，偏差 {ppm:+.1f} ppm"
            state = "pass" if abs(ppm) <= HRMS_PASS_PPM else ("warn" if abs(ppm) <= HRMS_WARN_PPM else "fail")
            checks.append({"id": "hrms_vs_formula", "state": state, "detail": detail})
    elif mz is not None:
        checks.append({"id": "hrms_vs_formula", "state": "skipped",
                       "detail": ("分子式无法解析，未推算理论 m/z" if formula_text
                                  else "未填写分子式，无法推算理论 m/z")})

    # A named method with nothing behind it stays an assertion, not data.
    if "nmr" in method.lower() or "核磁" in method:
        if integral is None and not (entry.get("observation_text") or "").strip():
            checks.append({"id": "method_data", "state": "warn",
                           "detail": "方法声明为 NMR，但未给出积分数值或峰位记录"})
    if re.search(r"ms|质谱", method, re.I):
        if mz is None:
            checks.append({"id": "method_data", "state": "warn",
                           "detail": "方法声明为质谱，但未给出实测 m/z"})
    return checks


def _entry_state(entry, checks):
    states = {check["state"] for check in checks}
    if "fail" in states:
        return "structured_inconsistent"
    if "pass" in states:
        return "structured_consistent"
    if _has_data(entry):
        return "structured_documented"
    return "user_report_only"


def grade(record):
    """Grade the product-identity evidence of one normalized record.

    Returns a dict with the coarse ``state`` (also consumed by the UI and the
    stored snapshots), a numeric ``index``, the reasons behind it, the checks
    that ran, and the invariants that never move.
    """
    results = (record or {}).get("results") or {}
    entries = results.get("characterization") or []
    entries = [item for item in entries if isinstance(item, dict)]
    traceability = ("attachment_recorded" if any(
        (item.get("spectrum_reference") or "").strip() or item.get("raw_spectrum_provided")
        for item in entries) else "no_attachment")

    def done(state, reasons, checks):
        return _result(state, reasons, checks, len(entries), traceability)

    if not entries:
        return done("missing", ["未提供任何结构表征记录"], [])

    if any(item.get("supports_target") is False for item in entries):
        return done("contradictory", ["至少一条表征记录声明不支持目标产物"], [])

    analyses = [(item, _checks(item)) for item in entries]
    states = [_entry_state(item, checks) for item, checks in analyses]
    checks = [check for _, entry_checks in analyses for check in entry_checks]

    if "structured_inconsistent" in states:
        failing = [check["detail"] for check in checks if check["state"] == "fail"]
        return done("structured_inconsistent", failing[:3], checks)
    # Missing observation data retains the existing claim/documented grades.
    # A concrete numeric or formula warning must survive into the summary.
    warnings = [check['detail'] for check in checks if check['state']=='warn' and check['id']!='method_data']
    if warnings:
        return done('structured_warning', warnings[:3], checks)
    if any(item.get("provenance") == "human_review" for item in entries):
        return done("human_review_recorded",
                    ["记录中有人工复核依据；系统未读取该复核的原始材料"], checks)
    if "structured_consistent" in states:
        passing = [check["detail"] for check in checks if check["state"] == "pass"]
        return done("structured_consistent", passing[:3], checks)
    if "structured_documented" in states:
        skipped = [check["detail"] for check in checks if check["state"] in {"skipped", "warn"}]
        return done("structured_documented",
                    skipped[:3] or ["观测值已记录，但本地无法完成核对"], checks)
    return done("user_report_only", ["仅有“与目标一致”的结论，未附可核对的数据"], [])


def _result(state, reasons, checks, entries, traceability):
    spec = STATES[state]
    return {
        "state": state,
        "index": spec["index"],
        "label": spec["label"],
        "entry_count": entries,
        "reasons": [item for item in reasons if item],
        "checks": checks,
        "traceability": traceability,
        "independently_verified_by_system": False,
        "source": "user_report",
        "structure_confirmed": False,
        "limitation": DEFAULT_LIMITATION,
        "what_would_raise_it": list(RAISE_IT.get(state, [])),
        "prompt_summary": prompt_summary(state, reasons),
    }


def state_of(record):
    """Coarse state only; the full detail is :func:`grade`."""
    try:
        return grade(record)["state"]
    except (AttributeError, TypeError, ValueError):
        return "missing"


def blocks_goal_comparison(state):
    return state in BLOCKING_STATES


def prompt_summary(state, reasons=None):
    label = STATES.get(state, {}).get("label", state)
    detail = "；".join(reasons or [])
    return f"{label}" + (f"（{detail}）" if detail else "")


def followup(state):
    """The one question that would move the grade up, or None when it already is."""
    if state == "missing":
        return ("results.characterization", "有哪些支持目标产物结构的表征记录（方法、观测值与原始文件）？")
    if state == "user_report_only":
        return ("results.characterization[0].observation_text",
                "该表征记录的具体观测值是什么（峰位与积分、m/z、熔点等）？是否附有原始文件编号？")
    if state == 'structured_warning':
        return ('results.characterization', '本次观测数据有待核查项，请对照原始记录核对差异或未完成的检查；不要修改数值来迎合一致。')
    if state == "structured_documented":
        return ("results.characterization[0].formula",
                "目标产物的分子式是什么？补上后可以本地核对积分总数与实测 m/z。")
    if state == "structured_inconsistent":
        return ("results.characterization[0]",
                "本次填写的分子式、总积分与实测 m/z 之间不一致，请核对是否有抄录错误或加合物不同。")
    return None


# Injected into every Agent prompt.  It states the boundary the grade encodes, so
# the report cannot convert "user says it matches" into "structure confirmed".
PROMPT_CLAUSE = """
【产物结构证据的表述边界】
本次记录中的结构证据全部由用户填写，系统没有独立读取或核验任何谱图、质谱文件或样品。
- 用户只写“结构匹配 / 已确证”而未给方法与观测值时，只能写“用户报告匹配，未附数据”，不得写成已确认。
- 用户提供了方法、观测值与分子式等可核对数据、且本地机械核对通过时，可写“用户所报数据内部一致”，并同时说明未经独立核验。
- 用户所报数据与声明不一致时，先指出不一致并建议核对，不得沿用“结构已确认”的结论。
- 任何情况下都不得写“已确证产物 / 结构已确认 / 身份已确认”；可写“支持目标产物的结构表征（用户报告，未独立核验）”。
- 用户自述的谱图匹配、单次 m/z 或熔点，都不能替代独立确证。
"""
