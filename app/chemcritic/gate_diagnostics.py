"""Conservative bridge to the shared gate prototype; never authorizes comparison.

Inputs are the existing application's normalized records, not shared demo data.
No source ID, claimed grade or verification boolean grants A confirmation here.
"""

import math

from .gate_engine.gates import RULE_REVISION, judge
from .gate_engine.schemas import Record


ADAPTER_VERSION = "shared-gates-shadow-0.3"


def _text(value):
    if not isinstance(value, str) or value.strip().lower() in {"", "unknown", "未知", "null", "none", "n/a", "待核验"}:
        return None
    return value


def _number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or (positive and value <= 0):
        return None
    return value


def adapt_record(raw, *, subject=False):
    """Return a fresh Record and mapping notes; never impute chemical roles.

    ``raw`` is the engine-facing projection produced by
    :func:`reaction_profiles.legacy_view`, so the substrate slots are already
    derived from user-declared reactant roles rather than from input order.
    """
    reaction, conditions = raw.get("reaction", {}), raw.get("conditions", {})
    outcome = raw.get("results", {}) if subject else raw.get("outcome", {})
    substrates = reaction.get("substrates")
    substrates = substrates if isinstance(substrates, list) and len(substrates) == 2 else [None, None]
    base_state = conditions.get("base_status", "unknown")
    base = "explicitly absent" if base_state == "absent" else _text(conditions.get("base_name")) if base_state == "present" else None
    mapped = {
        "catalyst": _text(conditions.get("catalyst")),
        "catalyst_mol_pct": _number(conditions.get("catalyst_loading_mol_pct")),
        "ligand": _text(conditions.get("ligand")),
        "base": base,
        "base_equivalents": _number(conditions.get("base_equivalents")),
        "solvent": _text(conditions.get("solvent")),
        "temp_c": _number(conditions.get("temperature_C")),
        "time_h": _number(conditions.get("time_h"), positive=True),
        "atmosphere": _text(conditions.get("atmosphere")),
        "scale_mmol": _number(conditions.get("scale_mmol"), positive=True),
        # Never assume 1 equivalent, concentration, ligand or loading basis.
        "equivalents": {"aryl_halide": _number(conditions.get("aryl_halide_equivalents")),
                        "boronic_acid": _number(conditions.get("partner_equivalents"))},
        "concentration_m": _number(conditions.get("concentration_m"), positive=True),
    }
    assay = {
        "method": _text(outcome.get("assay")),
        "internal_standard": _text(outcome.get("internal_standard")),
        "quantification_basis": _text(outcome.get("yield_basis") if subject else outcome.get("basis")),
    }
    record = Record(
        record_id=raw["experiment_id"] if subject else raw["record_id"],
        outcome_type=outcome.get("yield_type", "unknown"),
        outcome_value=outcome.get("yield_pct") if subject else outcome.get("value_pct"),
        assay=assay, conditions=mapped,
        substrate={"aryl_halide": _text(substrates[0]), "boronic_acid": _text(substrates[1]),
                   "product": _text(reaction.get("target_product"))},
        source_id=raw.get("source_id"), locator=raw.get("locator"),
        purification=_text(conditions.get("purification")),
        # This phase implements no approved record-level promotion workflow.
        evidence_grade="imported_unchecked", verification="unverified",
        label_raw=None if subject else _text(outcome.get("original_metric")),
        label_raw_provenance="unknown",
    )
    missing = ["conditions." + key for key, value in mapped.items() if value is None]
    missing.extend("conditions.equivalents." + key for key, value in mapped["equivalents"].items() if value is None)
    missing.extend("substrate." + key for key, value in record.substrate.items() if value is None)
    missing.extend("assay." + key for key, value in assay.items() if value is None)
    notes = {
        "missing_mapped_fields": missing,
        "evidence_grade_used": record.evidence_grade,
        "evidence_level_claimed": raw.get("evidence_level_claimed"),
        "source_verification_claimed": raw.get("verification"),
        "base_status": base_state,
        "substrate_mapping": "declared_reactant_roles_mapped_to_engine_slots",
        "role_source": (raw.get("_mapping") or {}).get("role_source"),
    }
    return record, notes


def diagnose(experiment, source, same_publication_record_ids=None):
    """Run all eight gates on separate copies, retaining the production lock.

    PASS in a prototype soft gate can coexist with missing fields. Consumers must
    retain mapping gaps and the shadow-only label, never use verdict as permission.
    """
    user, user_notes = adapt_record(experiment, subject=True)
    reference, source_notes = adapt_record(source)
    verdict = judge(user, reference).to_dict()
    return {
        "adapter_version": ADAPTER_VERSION,
        "engine_revision": RULE_REVISION,
        "mode": "shadow_only",
        "numeric_comparison_allowed": False,
        "policy_reason": "production_numeric_policy_unchanged",
        "placement_allowed": False,
        "calibration_interpretation": "reported_method_fields_only_not_independent_verification",
        "shared_engine": verdict,
        # Upstream non_independent compares subject/reference; this separate
        # field describes dependencies among the retrieved references.
        "reference_set": {
            "non_independent": bool(same_publication_record_ids),
            "same_publication_record_ids": list(same_publication_record_ids or []),
            "basis": "matching_nonempty_doi",
        },
        "mapping": {"subject": user_notes, "reference": source_notes},
        "limitations": [
            "原型名称匹配不验证化学结构或用户产物身份。",
            "软门槛PASS不表示字段齐全；应结合missing_mapped_fields查看。",
            "原型溶剂族启发式及L1/L2阈值未在本适配中完成科学验收。",
            "未启用固定编号确认名单、体系分层、区间定位或数值比较。",
        ],
    }
