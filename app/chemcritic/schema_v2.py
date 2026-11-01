"""Reaction-agnostic experiment record (v0.2) and the v0.1 upgrade path.

Two rules govern this module:

* The record describes **roles**, not positions.  A reactant carries an explicit
  ``role`` (aryl halide, amine, alkene, ...) instead of being "slot 0"; an
  additive carries an explicit ``type`` (base, acid, salt, oxidant, ...) instead
  of a dedicated ``base_*`` triple.  Nothing here infers chemistry from names.
* Absence and ignorance stay distinguishable.  ``absent`` means the user said
  the additive was not used; ``unknown`` means the record does not say.  The
  same holds for solvent water content.

The fixed decision engine only understands Suzuki-shaped subjects, so this module
never talks to it directly; :mod:`reaction_profiles` owns that mapping.
"""

from __future__ import annotations

import copy
import math

SCHEMA = "chemcritic.experiment.v0.2"
LEGACY_SCHEMA = "chemcritic.experiment.v0.1"

REACTION_TYPES = {
    "suzuki_miyaura": "Suzuki–Miyaura 偶联",
    "buchwald_hartwig": "Buchwald–Hartwig 胺化",
    "heck": "Heck 反应",
    "sonogashira": "Sonogashira 偶联",
    "hydrogenation": "氢化 / 还原",
    "oxidation": "氧化",
    "condensation": "缩合 / 酯化 / 酰胺化",
    "substitution": "取代 / 加成",
    "other": "其他 / 未归类",
}

# Roles are declared by the user.  A role is never derived from a chemical name.
REACTANT_ROLES = {
    "aryl_halide": "芳基卤化物 / 芳基磺酸酯",
    "boronic_acid_or_ester": "硼酸 / 硼酸酯",
    "amine": "胺（亲核试剂）",
    "alkene": "烯烃",
    "alkyne": "炔烃",
    "electrophile": "亲电试剂",
    "nucleophile": "亲核试剂",
    "reagent": "试剂（氧化剂 / 还原剂 / 其他）",
    "other": "其他 / 未分类",
}

ADDITIVE_TYPES = {
    "base": "碱",
    "acid": "酸",
    "salt": "盐 / 缓冲剂",
    "oxidant": "氧化剂",
    "reductant": "还原剂",
    "ligand": "配体",
    "cocatalyst": "助催化剂",
    "phase_transfer": "相转移催化剂",
    "surfactant": "表面活性剂 / 添加剂",
    "other": "其他",
}

METRICS = {"isolated", "gc", "nmr", "lc", "conversion", "unknown"}
METRIC_LABELS = {
    "isolated": "分离收率",
    "gc": "GC收率",
    "nmr": "NMR定量",
    "lc": "LC收率",
    "conversion": "转化率",
    "unknown": "口径未知",
}
WATER_STATES = {"unknown": "未知 / 未记录", "anhydrous": "明确无水", "aqueous": "明确含水"}
PRESENCE_STATES = {"present", "absent", "unknown"}

# Adducts the local mass check understands.  Only the user selects one; the
# default is applied when a reported m/z carries no adduct label.
MZ_ADDUCTS = {
    "[M+H]+": "正离子 [M+H]+（默认）",
    "[M-H]-": "负离子 [M-H]-",
    "[M+Na]+": "钠加合 [M+Na]+",
    "M+": "分子离子 M+",
}

# Engine tier vocabulary, mirrored verbatim so a user declaration can be passed
# through without translation.  Only the user may fill these; the app never
# derives a form/family from a catalyst name.
CLASSIFICATION_FIELDS = {
    "catalyst_form": {
        "label": "催化剂物理形态",
        "values": {"molecular_complex": "可溶分子配合物", "in_situ_salt": "原位生成盐/配合物",
                   "nanoparticle": "纳米颗粒", "supported": "负载型", "bulk_metal": "块体金属"},
    },
    "ligand_family": {
        "label": "配体族",
        "values": {"phosphine": "膦类配体", "non_phosphine": "非膦配体", "none": "无配体"},
    },
    "support": {
        "label": "载体",
        "values": {"none": "无载体", "solid_support": "固体载体"},
    },
    "medium": {
        "label": "反应介质",
        "values": {"aqueous": "水相", "organic": "有机相", "solventless": "无溶剂"},
    },
    "activation_mode": {
        "label": "活化方式",
        "values": {"thermal": "热", "mechanochemical": "机械化学",
                   "microwave": "微波", "photochemical": "光化学"},
    },
}


class ValidationError(ValueError):
    """Invalid record, with a machine-readable field path."""

    def __init__(self, field, message):
        self.field = field
        super().__init__(f"{field}: {message}")


# --------------------------------------------------------------------------- #
# small validators


def _fail(field, message):
    raise ValidationError(field, message)


def _object(value, path):
    if not isinstance(value, dict):
        _fail(path, "must be an object")
    return value


def _number(value, path, maximum=None, positive=False):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "must be a numeric value or null")
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        _fail(path, "must be finite and non-negative (positive for scale/time/volume)")
    if maximum is not None and value > maximum:
        _fail(path, f"must be <= {maximum}")
    return float(value)


def _text(value, path, required=False):
    if value is None:
        if required:
            _fail(path, "is required")
        return None
    if not isinstance(value, str):
        _fail(path, "must be a string")
    if required and not value.strip():
        _fail(path, "must be a non-empty string")
    return value.strip() or None


def _enum(value, path, allowed, default=None, labels=None):
    if value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        keys = "、".join(sorted(allowed)) if labels is None else "、".join(f"{k}({v})" for k, v in labels.items())
        _fail(path, f"unsupported value; expected one of: {keys}")
    return value


# --------------------------------------------------------------------------- #
# v0.1 -> v0.2


def upgrade(experiment):
    """Return a v0.2 copy of a v0.1 record.

    The v0.1 form had two ordered substrate slots and a dedicated base triple, so
    the upgrade maps slots to the roles those slots were labelled with.  That
    provenance is recorded per reactant (``role_source``) instead of being
    presented as a chemistry judgement.
    """
    source = _object(experiment, "experiment")
    reaction = _object(source.get("reaction") or {}, "reaction")
    conditions = _object(source.get("conditions") or {}, "conditions")
    results = _object(source.get("results") or {}, "results")
    goal = source.get("user_goal")
    substrates = reaction.get("substrates") if isinstance(reaction.get("substrates"), list) else []
    names = [(_text(substrates[i], f"reaction.substrates[{i}]") if i < len(substrates) else None) for i in range(2)]
    partners = _number(conditions.get("partner_equivalents"), "conditions.partner_equivalents")
    reactants = []
    for name, role in zip(names, ("aryl_halide", "boronic_acid_or_ester")):
        reactants.append({
            "name": name,
            "role": role,
            "equivalents": partners if role == "boronic_acid_or_ester" else None,
            "limiting": role == "aryl_halide" if partners is not None else False,
            "role_source": "declared_by_v01_form_slots",
        })
    base_state = conditions.get("base_status", "unknown")
    base_state = base_state if base_state in PRESENCE_STATES else "unknown"
    additives = []
    if base_state == "present":
        additives.append({
            "name": _text(conditions.get("base_name"), "conditions.base_name"),
            "type": "base",
            "equivalents": _number(conditions.get("base_equivalents"), "conditions.base_equivalents"),
            "loading_mol_pct": None,
        })
    upgraded = {
        "schema_version": SCHEMA,
        "experiment_id": source.get("experiment_id"),
        "simulated": source.get("simulated"),
        "reaction": {
            "type": "suzuki_miyaura",
            "type_label": None,
            "reactants": reactants,
            "product": {"name": _text(reaction.get("target_product"), "reaction.target_product"),
                        "characterization": None},
            "equivalents_basis": ({"reactant_index": 0, "label": names[0]} if partners is not None else None),
            "name": _text(reaction.get("name"), "reaction.name"),
        },
        "catalyst": {
            "name": _text(conditions.get("catalyst"), "conditions.catalyst"),
            "loading_mol_pct": _number(conditions.get("catalyst_loading_mol_pct"), "conditions.catalyst_loading_mol_pct"),
            "loading_basis": _text(conditions.get("catalyst_loading_basis"), "conditions.catalyst_loading_basis"),
            "ligand": {"name": _text(conditions.get("ligand"), "conditions.ligand"), "loading_mol_pct": None},
            "classification": {},
        },
        "additives": additives,
        "additives_listed_complete": None,
        "additive_declarations": {"base": base_state},
        "conditions": {
            "solvent_system": {
                "primary": _text(conditions.get("solvent"), "conditions.solvent"),
                "cosolvent": None, "ratio": None,
                "volume_ml": _number(conditions.get("solvent_volume_ml"), "conditions.solvent_volume_ml", positive=True),
                "water_content": "unknown",
            },
            "temperature_C": _number(conditions.get("temperature_C"), "conditions.temperature_C"),
            "time_h": _number(conditions.get("time_h"), "conditions.time_h", positive=True),
            "atmosphere": _text(conditions.get("atmosphere"), "conditions.atmosphere"),
            "scale_mmol": _number(conditions.get("scale_mmol"), "conditions.scale_mmol", positive=True),
            "pressure_bar": None, "irradiation": None, "addition_mode": None,
        },
        "results": {
            "value_pct": _number(results.get("yield_pct"), "results.yield_pct", maximum=100),
            "metric": results.get("yield_type", "unknown"),
            "basis": _text(results.get("yield_basis"), "results.yield_basis"),
            "method": results.get('assay') or results.get('method'),
            "internal_standard": results.get('internal_standard'),
            "characterization": results.get("characterization", []),
            "repeat_attempts": results.get("repeat_attempts"),
            "replicates": [],
        },
        "user_goal": ({"minimum_yield_pct": _number((goal or {}).get("minimum_yield_pct"), "user_goal.minimum_yield_pct", maximum=100),
                       "metric": (goal or {}).get("yield_type", "unknown")} if isinstance(goal, dict) else None),
        "upgraded_from": LEGACY_SCHEMA,
    }
    return upgraded


# --------------------------------------------------------------------------- #
# v0.2 validation / normalisation


def validate(experiment):
    """Validate a v0.2 record and return a normalised copy.  Never imputes values."""
    record = copy.deepcopy(_object(experiment, "experiment"))
    record_id = _text(record.get("experiment_id"), "experiment_id", required=True)
    if record_id.startswith("sp_live_"):
        _fail("experiment_id", "疑似将API密钥填入实验编号；请改为普通编号。")
    record["experiment_id"] = record_id
    if type(record.get("simulated")) is not bool:
        _fail("simulated", "must explicitly be true or false")

    reaction = _object(record.get("reaction") or {}, "reaction")
    reaction["type"] = _enum(reaction.get("type"), "reaction.type", set(REACTION_TYPES), default="other")
    reaction["type_label"] = _text(reaction.get("type_label"), "reaction.type_label")
    reactants = reaction.get("reactants")
    if not isinstance(reactants, list) or not reactants:
        _fail("reaction.reactants", "must be a non-empty list of {name, role}")
    clean = []
    for index, item in enumerate(reactants):
        path = f"reaction.reactants[{index}]"
        item = _object(item, path)
        clean.append({
            "name": _text(item.get("name"), path + ".name", required=True),
            "role": _enum(item.get("role"), path + ".role", set(REACTANT_ROLES), default="other"),
            "equivalents": _number(item.get("equivalents"), path + ".equivalents"),
            "limiting": bool(item.get("limiting")) if isinstance(item.get("limiting"), bool) else False,
            "role_source": _text(item.get("role_source"), path + ".role_source") or "user_stated",
        })
    reaction["reactants"] = clean
    if sum(item['limiting'] for item in clean)>1:
        _fail('reaction.reactants.limiting','只能声明一个限量试剂/当量基准，不能静默选择第一项')
    product = _object(reaction.get("product") or {}, "reaction.product")
    reaction["product"] = {"name": _text(product.get("name"), "reaction.product.name", required=True),
                           "characterization": product.get("characterization")}
    basis = reaction.get("equivalents_basis")
    if basis is not None:
        basis = _object(basis, "reaction.equivalents_basis")
        index = basis.get("reactant_index")
        if index is not None and (isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(clean)):
            _fail("reaction.equivalents_basis.reactant_index", "must index an existing reactant or be null")
        reaction["equivalents_basis"] = {"reactant_index": index,
                                         "label": _text(basis.get("label"), "reaction.equivalents_basis.label")}
    reaction.pop("name", None)  # v0.1 reaction.name is superseded by reaction.type
    record["reaction"] = reaction

    catalyst = _object(record.get("catalyst") or {}, "catalyst")
    ligand = _object(catalyst.get("ligand") or {}, "catalyst.ligand")
    classification = _object(catalyst.get("classification") or {}, "catalyst.classification")
    normalized_classification = {}
    for key, spec in CLASSIFICATION_FIELDS.items():
        value = classification.get(key)
        if value is None:
            normalized_classification[key] = None
            continue
        if not isinstance(value, str) or value not in spec["values"]:
            _fail(f"catalyst.classification.{key}",
                  "unsupported value; expected one of: " + "、".join(f"{k}({v})" for k, v in spec["values"].items()))
        normalized_classification[key] = value
    # An extra key is stray data, not a contradiction: park it and keep going.
    unknown = sorted(set(classification) - set(CLASSIFICATION_FIELDS))
    record["catalyst"] = {
        "name": _text(catalyst.get("name"), "catalyst.name"),
        "loading_mol_pct": _number(catalyst.get("loading_mol_pct"), "catalyst.loading_mol_pct"),
        "loading_basis": _text(catalyst.get("loading_basis"), "catalyst.loading_basis"),
        "ligand": {"name": _text(ligand.get("name"), "catalyst.ligand.name"),
                   "loading_mol_pct": _number(ligand.get("loading_mol_pct"), "catalyst.ligand.loading_mol_pct")},
        # Only the user declares these; they are passed to the engine verbatim.
        "classification": normalized_classification,
    }
    if unknown:
        record["catalyst"]["classification_ignored"] = unknown

    additives = record.get("additives") or []
    if not isinstance(additives, list):
        _fail("additives", "must be a list")
    clean = []
    for index, item in enumerate(additives):
        path = f"additives[{index}]"
        item = _object(item, path)
        clean.append({"name": _text(item.get("name"), path + ".name"),
                      "type": _enum(item.get("type"), path + ".type", set(ADDITIVE_TYPES), default="other"),
                      "equivalents": _number(item.get("equivalents"), path + ".equivalents"),
                      "loading_mol_pct": _number(item.get("loading_mol_pct"), path + ".loading_mol_pct")})
    record["additives"] = clean
    if record.get("additives_listed_complete") is not None and not isinstance(record.get("additives_listed_complete"), bool):
        _fail("additives_listed_complete", "must be true, false or null")
    declarations = record.get("additive_declarations") or {}
    declarations = _object(declarations, "additive_declarations")
    record["additive_declarations"] = {
        _enum(key, "additive_declarations." + key, set(ADDITIVE_TYPES), default="other"):
            _enum(value, "additive_declarations." + key, PRESENCE_STATES, default="unknown")
        for key, value in declarations.items()
    }
    # A contradictory declaration is not a reason to reject the whole experiment:
    # the row wins (it is the concrete observation), the contradicting declaration
    # is dropped, and the conflict is recorded so it stays visible.
    reconciled = []
    for kind, state in list(record["additive_declarations"].items()):
        rows = [item for item in clean if item["type"] == kind]
        if state == "absent" and rows:
            record["additive_declarations"].pop(kind)
            reconciled.append({"type": kind, "declared": state, "kept": "present_from_rows"})
        elif state == "present" and not rows:
            record["additive_declarations"].pop(kind)
            reconciled.append({"type": kind, "declared": state, "kept": "unknown_no_row"})
    if reconciled:
        record["additive_declarations_reconciled"] = reconciled
    for index, item in enumerate(clean):
        if item["name"] is None and record["additive_declarations"].get(item["type"]) != "present":
            _fail(f"additives[{index}].name",
                  "名称缺失时必须在 additive_declarations 中声明该类型为 present（已加入、名称未知）")

    conditions = _object(record.get("conditions") or {}, "conditions")
    solvent = _object(conditions.get("solvent_system") or {}, "conditions.solvent_system")
    conditions["solvent_system"] = {
        "primary": _text(solvent.get("primary"), "conditions.solvent_system.primary"),
        "cosolvent": _text(solvent.get("cosolvent"), "conditions.solvent_system.cosolvent"),
        "ratio": _text(solvent.get("ratio"), "conditions.solvent_system.ratio"),
        "volume_ml": _number(solvent.get("volume_ml"), "conditions.solvent_system.volume_ml", positive=True),
        "water_content": _enum(solvent.get("water_content"), "conditions.solvent_system.water_content",
                               set(WATER_STATES), default="unknown"),
    }
    temperature = conditions.get("temperature_C")
    if temperature is not None and (isinstance(temperature, bool) or not isinstance(temperature, (int, float))
                                    or not math.isfinite(temperature) or temperature < -273.15):
        _fail("conditions.temperature_C", "must be a finite temperature >= -273.15")
    conditions["time_h"] = _number(conditions.get("time_h"), "conditions.time_h", positive=True)
    conditions["atmosphere"] = _text(conditions.get("atmosphere"), "conditions.atmosphere")
    conditions["scale_mmol"] = _number(conditions.get("scale_mmol"), "conditions.scale_mmol", positive=True)
    conditions["pressure_bar"] = _number(conditions.get("pressure_bar"), "conditions.pressure_bar")
    conditions["irradiation"] = _text(conditions.get("irradiation"), "conditions.irradiation")
    conditions["addition_mode"] = _text(conditions.get("addition_mode"), "conditions.addition_mode")
    record["conditions"] = conditions

    results = _object(record.get("results") or {}, "results")
    results["value_pct"] = _number(results.get("value_pct"), "results.value_pct", maximum=100)
    results["metric"] = _enum(results.get("metric", "unknown"), "results.metric", METRICS, default="unknown")
    results["basis"] = _text(results.get("basis"), "results.basis")
    results["method"] = _text(results.get("method"), "results.method")
    results["internal_standard"] = _text(results.get("internal_standard"), "results.internal_standard")
    evidence = results.get("characterization") or []
    if not isinstance(evidence, list):
        _fail("results.characterization", "must be a list")
    normalized = []
    for index, item in enumerate(evidence):
        path = f"results.characterization[{index}]"
        item = _object(item, path)
        provenance = item.get("provenance", "user_report")
        if provenance not in {"user_report", "human_review"}:
            _fail(path + ".provenance", "expected user_report or human_review")
        if type(item.get("supports_target")) is not bool:
            _fail(path + ".supports_target", "must be boolean")
        entry = {"method": _text(item.get("method"), path + ".method", required=True),
                 "supports_target": item["supports_target"], "provenance": provenance,
                 "raw_spectrum_provided": bool(item.get("raw_spectrum_provided"))}
        if provenance == "human_review":
            entry["review_reference"] = _text(item.get("review_reference"), path + ".review_reference", required=True)
        # Observation values are optional: a record may legitimately stop at
        # "method and conclusion".  When they are present they must be usable for
        # the local checks, so they are typed rather than kept as free text.
        reference = _text(item.get("spectrum_reference"), path + ".spectrum_reference")
        if reference:
            entry["spectrum_reference"] = reference
        observed = _text(item.get("observation_text"), path + ".observation_text")
        if observed:
            entry["observation_text"] = observed
        formula = _text(item.get("formula"), path + ".formula")
        if formula:
            if len(formula) > 60:
                _fail(path + ".formula", "must be at most 60 characters")
            entry["formula"] = formula
        integral = item.get("proton_integral")
        if integral is not None:
            integral = _number(integral, path + ".proton_integral")
            if integral > 200:
                _fail(path + ".proton_integral", "must be <= 200")
            entry["proton_integral"] = integral
        mass = item.get("mz")
        if mass is not None:
            mass = _number(mass, path + ".mz", positive=True)
            if mass > 1_000_000:
                _fail(path + ".mz", "must be a plausible m/z")
            entry["mz"] = mass
        adduct = _enum(item.get("mz_adduct"), path + ".mz_adduct", set(MZ_ADDUCTS))
        if adduct:
            entry["mz_adduct"] = adduct
        normalized.append(entry)
    results["characterization"] = normalized
    attempts = results.get("repeat_attempts")
    if attempts is not None and (type(attempts) is not int or attempts < 1):
        _fail("results.repeat_attempts", "must be a positive integer")
    replicates = results.get("replicates") or []
    if not isinstance(replicates, list):
        _fail("results.replicates", "must be a list of numbers")
    results["replicates"] = [_number(value, f"results.replicates[{index}]", maximum=100)
                             for index, value in enumerate(replicates)]
    record["results"] = results

    goal = record.get("user_goal")
    if goal is not None:
        goal = _object(goal, "user_goal")
        record["user_goal"] = {
            "minimum_yield_pct": _number(goal.get("minimum_yield_pct"), "user_goal.minimum_yield_pct", maximum=100),
            "metric": _enum(goal.get("metric", "unknown"), "user_goal.metric", METRICS, default="unknown"),
        }
    record["schema_version"] = SCHEMA
    return record


def normalize(experiment):
    """Accept v0.1 or v0.2 and return a validated v0.2 record."""
    record = _object(experiment, "experiment")
    version = record.get("schema_version")
    if version == SCHEMA:
        return validate(record)
    if version in (LEGACY_SCHEMA, None):
        return validate(upgrade(record))
    _fail("schema_version", f"unsupported version {version!r}")


# --------------------------------------------------------------------------- #
# read-only helpers (no inference, no defaults that look like facts)


def reactants(experiment):
    return list((experiment.get("reaction") or {}).get("reactants") or [])


def reactant_by_role(experiment, role):
    for item in reactants(experiment):
        if item.get("role") == role:
            return item
    return None


def reactant_by_any_role(experiment, roles):
    for role in roles:
        found = reactant_by_role(experiment, role)
        if found:
            return found
    return None


def limiting_reactant(experiment):
    for item in reactants(experiment):
        if item.get("limiting"):
            return item
    return None


def equivalents_basis_label(experiment):
    basis = (experiment.get("reaction") or {}).get("equivalents_basis")
    if basis:
        index = basis.get("reactant_index")
        if isinstance(index, int) and 0 <= index < len(reactants(experiment)):
            return basis.get("label") or reactants(experiment)[index].get("name")
        return basis.get("label")
    # "限量试剂" is the user-declared equivalents basis; it is not an inference
    # when the record says so, and it stays empty when nothing is marked.
    limiting = limiting_reactant(experiment)
    return limiting.get("name") if limiting else None


def additives_of_type(experiment, kind):
    return [item for item in experiment.get("additives") or [] if item.get("type") == kind]


def additive_by_type(experiment, kind):
    found = additives_of_type(experiment, kind)
    return found[0] if found else None


def presence_state(experiment, kind):
    """present / absent / unknown for one additive type; never guesses."""
    if additives_of_type(experiment, kind):
        return "present"
    if experiment.get("additives_listed_complete") is True:
        return "absent"
    declared = (experiment.get("additive_declarations") or {}).get(kind)
    return declared if declared in PRESENCE_STATES else "unknown"


def classification(experiment):
    """User-declared engine tier fields (never inferred from a catalyst name)."""
    return ((experiment.get("catalyst") or {}).get("classification") or {})


def classification_missing(experiment):
    return [spec["label"] for key, spec in CLASSIFICATION_FIELDS.items()
            if not classification(experiment).get(key)]


def classification_complete(experiment):
    return not classification_missing(experiment)


def solvent_label(experiment):
    solvent = (experiment.get("conditions") or {}).get("solvent_system") or {}
    primary = solvent.get("primary")
    if not primary:
        # Preserve an explicitly provided cosolvent even if primary is unknown.
        return solvent.get('cosolvent')
    cosolvent = solvent.get("cosolvent")
    if not cosolvent:
        return primary
    ratio = solvent.get("ratio")
    return f"{primary}/{cosolvent}{(' ' + ratio) if ratio else ''}"


def metric_label(experiment):
    metric = (experiment.get("results") or {}).get("metric") or "unknown"
    return METRIC_LABELS.get(metric, "口径未知")


def describe(experiment):
    """One-line human description of the record (used in audit notes)."""
    parts = []
    for item in reactants(experiment):
        parts.append(f"{item.get('name') or '未记录'}（{REACTANT_ROLES.get(item.get('role'), '其他')}" +
                     (f"，{item.get('equivalents')} eq" if item.get("equivalents") is not None else "") + "）")
    product = ((experiment.get("reaction") or {}).get("product") or {}).get("name")
    return " + ".join(parts) + (" → " + product if product else "")
