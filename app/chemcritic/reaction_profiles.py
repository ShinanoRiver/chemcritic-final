"""Reaction profiles: the only place that knows how a generic record maps to a
fixed decision engine.

The shipped engine is Suzuki-shaped (``substrate.aryl_halide`` +
``substrate.boronic_acid`` + ``conditions.base``).  Rather than bending every
reaction into that shape, a profile declares which record roles it needs and how
they map.  Records outside every profile are still valid experiments: they get
fact review, evidence gaps and the user's own goal comparison, but no
comparability verdict.

Adding a family later means adding one profile entry (plus engine support); the
record format and the form do not change.
"""

from __future__ import annotations

from . import schema_v2

SUZUKI = "suzuki_miyaura"

PROFILES = {
    SUZUKI: {
        "label": "Suzuki–Miyaura 偶联",
        "engine": "chemcritic-engine (team40/team44 pinned)",
        "required_roles": {
            "aryl_halide": "芳基卤化物 / 芳基磺酸酯",
            "boronic_acid_or_ester": "硼酸 / 硼酸酯",
        },
        "notes": "固定引擎按芳基卤化物 + 硼酸（酯）成对判定；其他 Suzuki 变体（如自偶联、硼酸酯原位生成）需人工作者确认角色。",
    },
}


def reaction_label(experiment):
    reaction = experiment.get("reaction") or {}
    kind = reaction.get("type") or "other"
    if kind == "other" and reaction.get("type_label"):
        return reaction["type_label"]
    return schema_v2.REACTION_TYPES.get(kind, "其他 / 未归类")


def resolve(experiment):
    return PROFILES.get((experiment.get("reaction") or {}).get("type"))


def missing_roles(experiment, profile):
    missing = []
    for role, label in profile["required_roles"].items():
        if schema_v2.reactant_by_role(experiment, role) is None:
            missing.append({"role": role, "label": label})
    product = ((experiment.get("reaction") or {}).get("product") or {}).get("name")
    if not product:
        missing.append({"role": "product", "label": "目标产物名称"})
    return missing


def scope(experiment):
    """Return whether the fixed engine may judge this record, and why not.

    ``in_scope`` requires a matching reaction profile *and* every required role
    being explicitly declared.  Nothing is inferred from chemical names.
    """
    profile = resolve(experiment)
    kind = (experiment.get("reaction") or {}).get("type") or "other"
    label = reaction_label(experiment)
    base = {"reaction_type": kind, "reaction_label": label,
            "profile": (kind if profile else None),
            "record_description": schema_v2.describe(experiment),
            "engine_capability": "Suzuki–Miyaura（芳基卤化物 + 硼酸/硼酸酯）"}
    if profile is None:
        return {**base, "in_scope": False, "missing_roles": [],
                "reasons": [f"固定判定引擎只覆盖 Suzuki–Miyaura；本次记为「{label}」，"
                            "不做可比性判定、档内定位或文献数值比较。",
                            "仍会保留实验事实、结果口径、证据缺口与用户自设目标的判断。"]}
    missing = missing_roles(experiment, profile)
    if missing:
        return {**base, "in_scope": False, "missing_roles": missing,
                "reasons": ["本次记为 Suzuki–Miyaura，但以下角色未声明：" +
                            "、".join(item["label"] for item in missing) +
                            "；角色由用户声明，不由系统从化学名称推断，因此暂不做判定。"]}
    ambiguous=[]
    for role in profile['required_roles']:
        if sum(item.get('role')==role for item in schema_v2.reactants(experiment))>1:
            ambiguous.append('同一引擎角色声明多条原料，不能静默只取第一条：'+role)
    for kind in ('base','ligand'):
        if len(schema_v2.additives_of_type(experiment,kind))>1:
            ambiguous.append('同类型添加剂多条，引擎单字段无法无损表达：'+kind)
    ligand=((experiment.get('catalyst') or {}).get('ligand') or {}).get('name')
    extra=schema_v2.additive_by_type(experiment,'ligand')
    if ligand and extra and ligand!=extra.get('name'):
        ambiguous.append('另加配体和添加剂配体不一致，不能静默选择其中一项')
    basis=(experiment.get('reaction') or {}).get('equivalents_basis') or {}
    index=basis.get('reactant_index')
    if index is not None and schema_v2.reactants(experiment)[index].get('role')!='aryl_halide':
        ambiguous.append('当前当量基准不是芳基卤化物，固定引擎不自动换算当量')
    if (experiment.get('results') or {}).get('metric')=='lc':
        ambiguous.append('固定引擎未支持LC口径，保留原始值但不改为GC或分离收率')
    if ambiguous:
        return {**base,'in_scope':False,'missing_roles':[],'reasons':ambiguous}
    return {**base, "in_scope": True, "missing_roles": [], "reasons": []}


def legacy_view(experiment):
    """Project a generic record onto the v0.1 shape the fixed engine understands.

    Returns ``None`` when the record is out of the profile's scope, so callers
    cannot accidentally run the engine on a mismatched reaction.
    """
    if not scope(experiment)["in_scope"]:
        return None
    halide = schema_v2.reactant_by_role(experiment, "aryl_halide")
    boronic = schema_v2.reactant_by_role(experiment, "boronic_acid_or_ester")
    product = (experiment.get("reaction") or {}).get("product") or {}
    catalyst = experiment.get("catalyst") or {}
    ligand = catalyst.get("ligand") or {}
    extra_ligand=schema_v2.additive_by_type(experiment,'ligand') or {}
    base = schema_v2.additive_by_type(experiment, "base")
    solvent = (experiment.get("conditions") or {}).get("solvent_system") or {}
    results = experiment.get("results") or {}
    goal = experiment.get("user_goal")
    return {
        "schema_version": schema_v2.LEGACY_SCHEMA,
        "experiment_id": experiment.get("experiment_id"),
        "simulated": experiment.get("simulated"),
        "reaction": {
            "name": "Suzuki-Miyaura",
            "substrates": [halide.get("name"), boronic.get("name")],
            "target_product": product.get("name"),
        },
        "conditions": {
            "catalyst": catalyst.get("name"),
            "catalyst_loading_mol_pct": catalyst.get("loading_mol_pct"),
            "catalyst_loading_basis": catalyst.get("loading_basis"),
            "ligand": ligand.get("name") or extra_ligand.get('name'),
            "base_status": schema_v2.presence_state(experiment, "base"),
            "base_name": (base or {}).get("name"),
            "base_equivalents": (base or {}).get("equivalents"),
            "aryl_halide_equivalents": halide.get("equivalents"),
            "partner_equivalents": boronic.get("equivalents"),
            "solvent": schema_v2.solvent_label(experiment),
            "solvent_volume_ml": solvent.get("volume_ml"),
            "temperature_C": (experiment.get("conditions") or {}).get("temperature_C"),
            "time_h": (experiment.get("conditions") or {}).get("time_h"),
            "atmosphere": (experiment.get("conditions") or {}).get("atmosphere"),
            "scale_mmol": (experiment.get("conditions") or {}).get("scale_mmol"),
            "purification": None,
        },
        "results": {
            "yield_pct": results.get("value_pct"),
            "yield_type": results.get("metric", "unknown"),
            "yield_basis": results.get("basis"),
            "assay": results.get("method"),
            "internal_standard": results.get("internal_standard"),
            "characterization": results.get("characterization") or [],
            "repeat_attempts": results.get("repeat_attempts"),
        },
        "user_goal": ({"minimum_yield_pct": goal.get("minimum_yield_pct"),
                       "yield_type": goal.get("metric", "unknown")} if isinstance(goal, dict) else None),
        "_mapping": {
            "profile": SUZUKI,
            "equivalents_basis": schema_v2.equivalents_basis_label(experiment),
            "role_source": [item.get("role_source") for item in schema_v2.reactants(experiment)],
            "additives_outside_engine_scope": sorted(
                {item.get("type") for item in experiment.get("additives") or []
                 if item.get("type") not in {"base", "ligand"}}
            ),
        },
    }
