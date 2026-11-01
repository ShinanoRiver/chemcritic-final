"""Regression tests for the generic record (v0.2) and the placement scope fix.

Run from the package root:

    python -m unittest discover -s tests -v
"""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chemcritic import (engine_profiles, reaction_profiles, request_execution,
                            research_bundle, rules, schema_v2)
from app.chemcritic.report_contract import empty_class_claim, internal_token_findings, review_report
from tools import agent_result_bridge

ENGINE = ROOT / "deployment/team44_pinned/chemcritic_engine.py"
CASE = json.loads((ROOT / "cases/C2_simulated_42_goal60.json").read_text(encoding="utf-8"))


def run_engine(subject):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "input.json"
        path.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
        finished = subprocess.run(
            [sys.executable, "-X", "utf8", "-I", str(ENGINE), "--json", "--input", str(path)],
            capture_output=True, text=True, encoding="utf-8", timeout=60)
    if finished.returncode != 0:
        raise AssertionError(finished.stderr[-2000:])
    return json.loads(finished.stdout)


def engine_subject(experiment):
    """Build the pinned engine's subject through the same adapter the app uses."""
    view = reaction_profiles.legacy_view(schema_v2.normalize(experiment))
    from app.chemcritic.gate_diagnostics import adapt_record
    from dataclasses import asdict
    record, _notes = adapt_record(view, subject=True)
    subject = asdict(record)
    for key in ("outcome_value", "outcome_type", "label_raw"):
        subject.pop(key, None)
    results = view["results"]
    subject["outcome"] = {"value": results["yield_pct"], "outcome_type": results["yield_type"],
                          "label_raw": f"用户表单字段：yield_type={results['yield_type']};yield_pct={results['yield_pct']}"}
    subject["_extraction"] = {"label_raw_provenance": "structured_form_fields"}
    subject["conditions"]["base_status"] = view["conditions"]["base_status"]
    subject["conditions"]["catalyst_loading_basis"] = view["conditions"]["catalyst_loading_basis"]
    return engine_profiles.adapt_team_input(subject)


def v02(**overrides):
    record = schema_v2.upgrade(CASE)
    for path, value in overrides.items():
        node = record
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return record


class UpgradeTests(unittest.TestCase):
    def test_upgrade_maps_slots_to_roles_and_flags_provenance(self):
        record = schema_v2.normalize(CASE)
        self.assertEqual(record["schema_version"], schema_v2.SCHEMA)
        self.assertEqual(record["upgraded_from"], schema_v2.LEGACY_SCHEMA)
        roles = [item["role"] for item in record["reaction"]["reactants"]]
        self.assertEqual(roles, ["aryl_halide", "boronic_acid_or_ester"])
        self.assertTrue(all(item["role_source"] == "declared_by_v01_form_slots"
                            for item in record["reaction"]["reactants"]))
        self.assertEqual(record["results"]["value_pct"], 42)
        self.assertEqual(record["results"]["metric"], "isolated")
        self.assertEqual(record["conditions"]["solvent_system"]["primary"], "THF")
        # v0.1 base_status=unknown must not become "absent".
        self.assertEqual(schema_v2.presence_state(record, "base"), "unknown")
        self.assertEqual(record["user_goal"], {"minimum_yield_pct": 60, "metric": "isolated"})

    def test_upgrade_maps_base_triple_to_additive_row(self):
        case = json.loads(json.dumps(CASE))
        case["conditions"].update(base_status="present", base_name="K2CO3", base_equivalents=2)
        record = schema_v2.normalize(case)
        positive = schema_v2.additive_by_type(record, "base")
        self.assertEqual(positive, {"name": "K2CO3", "type": "base", "equivalents": 2, "loading_mol_pct": None})
        self.assertEqual(schema_v2.presence_state(record, "base"), "present")
        case["conditions"].update(base_status="absent", base_name=None, base_equivalents=None)
        self.assertEqual(schema_v2.presence_state(schema_v2.normalize(case), "base"), "absent")

    def test_upgrade_keeps_present_base_with_unknown_name(self):
        """v0.1 let the user say "碱加了，但不知道是哪种"; that must not become an error."""
        case = json.loads(json.dumps(CASE))
        case["conditions"].update(base_status="present", base_name=None, base_equivalents=None)
        record = schema_v2.normalize(case)
        self.assertEqual(schema_v2.presence_state(record, "base"), "present")
        self.assertIsNone(schema_v2.additive_by_type(record, "base")["name"])

    def test_presence_declaration_is_reconciled_not_rejected(self):
        """说"没加碱"却又填了 K2CO3：以行（具体记录）为准，冲突留痕，不拦整单。"""
        contradictory = schema_v2.validate({
            "schema_version": schema_v2.SCHEMA, "experiment_id": "X", "simulated": False,
            "reaction": {"type": "other", "reactants": [{"name": "A", "role": "other"}],
                         "product": {"name": "P"}},
            "additives": [{"name": "K2CO3", "type": "base"}],
            "additive_declarations": {"base": "absent"},
            "conditions": {}, "results": {}})
        self.assertEqual(schema_v2.presence_state(contradictory, "base"), "present")
        self.assertEqual(contradictory["additive_declarations_reconciled"],
                         [{"type": "base", "declared": "absent", "kept": "present_from_rows"}])

        empty = schema_v2.validate({
            "schema_version": schema_v2.SCHEMA, "experiment_id": "X", "simulated": False,
            "reaction": {"type": "other", "reactants": [{"name": "A", "role": "other"}],
                         "product": {"name": "P"}},
            "additives": [],
            "additive_declarations": {"base": "present"},
            "conditions": {}, "results": {}})
        self.assertEqual(schema_v2.presence_state(empty, "base"), "unknown")
        self.assertEqual(empty["additive_declarations_reconciled"],
                         [{"type": "base", "declared": "present", "kept": "unknown_no_row"}])

    def test_unnamed_additive_needs_a_present_declaration(self):
        base = {"schema_version": schema_v2.SCHEMA, "experiment_id": "X", "simulated": False,
                "reaction": {"type": "other", "reactants": [{"name": "A", "role": "other"}],
                             "product": {"name": "P"}},
                "additives": [{"name": None, "type": "base"}],
                "conditions": {}, "results": {}}
        with self.assertRaises(schema_v2.ValidationError):
            schema_v2.validate(json.loads(json.dumps(base)))
        declared = json.loads(json.dumps(base))
        declared["additive_declarations"] = {"base": "present"}
        self.assertEqual(schema_v2.normalize(declared)["additives"][0]["name"], None)

    def test_upgrade_keeps_mixed_solvent_as_written(self):
        case = json.loads(json.dumps(CASE))
        case["conditions"]["solvent"] = "THF/水 4:1"
        record = schema_v2.normalize(case)
        self.assertEqual(schema_v2.solvent_label(record), "THF/水 4:1")
        self.assertEqual(record["conditions"]["solvent_system"]["water_content"], "unknown")

    def test_validation_rejects_missing_reactants_and_bad_role(self):
        with self.assertRaises(schema_v2.ValidationError):
            schema_v2.validate({"schema_version": schema_v2.SCHEMA, "experiment_id": "X",
                                "simulated": False, "reaction": {"type": "other", "reactants": []},
                                "results": {}, "conditions": {}})
        record = v02()
        record["reaction"]["reactants"][0]["role"] = "not_a_role"
        with self.assertRaises(schema_v2.ValidationError):
            schema_v2.validate(record)


class ScopeTests(unittest.TestCase):
    def test_suzuki_with_declared_roles_is_in_scope(self):
        scope = reaction_profiles.scope(schema_v2.normalize(CASE))
        self.assertTrue(scope["in_scope"])
        self.assertEqual(scope["profile"], "suzuki_miyaura")
        self.assertIsNotNone(reaction_profiles.legacy_view(schema_v2.normalize(CASE)))

    def test_other_reaction_is_out_of_scope_and_has_no_engine_view(self):
        record = schema_v2.normalize({
            "schema_version": schema_v2.SCHEMA, "experiment_id": "BH-1", "simulated": False,
            "reaction": {"type": "buchwald_hartwig",
                         "reactants": [{"name": "4-bromoanisole", "role": "aryl_halide"},
                                       {"name": "morpholine", "role": "amine"}],
                         "product": {"name": "4-morpholinoanisole"}},
            "conditions": {},
            "results": {"value_pct": 78, "metric": "isolated",
                        "characterization": [{"method": "1H NMR", "supports_target": True,
                                              "provenance": "user_report"}]},
            "user_goal": None})
        scope = reaction_profiles.scope(record)
        self.assertFalse(scope["in_scope"])
        self.assertIn("Suzuki", "".join(scope["reasons"]))
        self.assertIsNone(reaction_profiles.legacy_view(record))
        result = rules.review(record, [])
        self.assertIn("engine_scope", result["blocked_dimensions"])
        self.assertEqual(result["goal_comparison"]["reason"], "goal_not_set")
        self.assertEqual(result["next_checks"][0]["rule_id"], "A00_ENGINE_SCOPE")

    def test_suzuki_without_boronic_role_stays_out_of_scope(self):
        record = v02()
        record["reaction"]["reactants"][1]["role"] = "other"
        scope = reaction_profiles.scope(schema_v2.validate(record))
        self.assertFalse(scope["in_scope"])
        self.assertEqual([item["role"] for item in scope["missing_roles"]], ["boronic_acid_or_ester"])

    def test_out_of_scope_goal_comparison_still_works(self):
        record = v02(**{"reaction.type": "heck"})
        record["user_goal"] = {"minimum_yield_pct": 50, "metric": "isolated"}
        result = rules.review(schema_v2.validate(record), [])
        self.assertFalse(result["engine_scope"]["in_scope"])
        self.assertEqual(result["goal_comparison"]["state"], "below_target")
        self.assertAlmostEqual(result["goal_comparison"]["gap_pp"], 8.0)


class ClassificationTests(unittest.TestCase):
    """Only the user may declare the tier fields; they unlock tier-scoped placement."""

    FULL = {"catalyst_form": "molecular_complex", "ligand_family": "phosphine",
            "support": "none", "medium": "organic", "activation_mode": "thermal"}

    def test_extra_classification_key_is_parked(self):
        """分类块里多塞一个 solvent_system：不拦整单，只放进 classification_ignored。"""
        record = v02()
        record["catalyst"]["classification"] = {**self.FULL, "solvent_system": "organic"}
        normalized = schema_v2.validate(record)
        self.assertEqual(normalized["catalyst"]["classification_ignored"], ["solvent_system"])
        self.assertNotIn("solvent_system", normalized["catalyst"]["classification"])
        self.assertEqual(normalized["catalyst"]["classification"]["catalyst_form"], "molecular_complex")

    def test_declared_classification_reaches_the_engine(self):
        record = v02()
        record["catalyst"]["classification"] = dict(self.FULL)
        contract = request_execution.prepare(schema_v2.validate(record), profile="team44")
        subject = contract["payload"]["engine_input"]["subject"]
        self.assertEqual(subject["catalytic_profile"], self.FULL)
        self.assertTrue(contract["payload"]["classification_declared"])
        payload = run_engine(subject)
        self.assertEqual(payload["placement"]["status"], "PLACED")
        self.assertEqual(payload["placement"]["tier"], "A")
        self.assertIsNotNone(payload["placement"]["delta_vs_min"])

    def test_partial_classification_is_not_sent(self):
        record = v02()
        record["catalyst"]["classification"] = {"catalyst_form": "molecular_complex"}
        contract = request_execution.prepare(schema_v2.validate(record), profile="team44")
        subject = contract["payload"]["engine_input"]["subject"]
        self.assertFalse(subject.get("catalytic_profile"))
        self.assertFalse(contract["payload"]["classification_declared"])
        self.assertEqual(contract["payload"]["classification_missing"],
                         ["配体族", "载体", "反应介质", "活化方式"])
        self.assertEqual(run_engine(subject)["placement"]["status"], "TIER_UNKNOWN")

    def test_unknown_value_is_rejected(self):
        record = v02()
        record["catalyst"]["classification"] = dict(self.FULL, ligand_family="phenanthroline")
        with self.assertRaises(schema_v2.ValidationError):
            schema_v2.validate(record)

    def test_followup_mentions_only_missing_labels(self):
        result = rules.review(schema_v2.normalize(CASE), [])
        followup = next(item for item in result["followups"] if item["field"] == "catalyst.classification")
        self.assertIn("配体族", followup["question"])
        complete = v02()
        complete["catalyst"]["classification"] = dict(self.FULL)
        cleared = rules.review(schema_v2.validate(complete), [])
        self.assertNotIn("catalyst.classification", [item["field"] for item in cleared["followups"]])

    def test_frontend_vocabulary_matches_the_schema(self):
        js = (ROOT / "app/chemcritic/static/app.js").read_text(encoding="utf-8")
        html = (ROOT / "app/chemcritic/static/index.html").read_text(encoding="utf-8")
        self.assertIn('id="classification-fields"', html)
        for spec in schema_v2.CLASSIFICATION_FIELDS.values():
            for value in spec["values"]:
                self.assertIn(value, js)


class PlacementScopeTests(unittest.TestCase):
    def test_placement_reason_carries_both_denominators(self):
        subject = engine_subject(CASE)
        payload = run_engine(subject)
        classes = {row["outcome_type"]: row for row in payload["classes"]}
        placement = payload["placement"]
        self.assertEqual(classes["isolated"]["count"], 19)
        self.assertEqual(payload["coverage"]["scope"], "library_wide")
        self.assertEqual(placement["library_total_count"], 44)
        self.assertEqual(placement["library_same_class_count"], 19)
        self.assertEqual(placement["same_pair_count"], placement["same_pair_count"])
        self.assertEqual(placement["observed"], 42)
        self.assertEqual(placement["outcome_type_label"], "分离收率")
        self.assertEqual(placement["scope"], "same_outcome_type_and_substrate_pair")
        self.assertEqual(placement["scope"], payload["scopes"]["placement"]["scope"])

    def test_no_comparable_names_pair_scope_and_library_count(self):
        outside = v02()
        outside["reaction"]["reactants"] = [
            {"name": "3-bromothiophene", "role": "aryl_halide", "equivalents": None, "limiting": True,
             "role_source": "user_stated"},
            {"name": "phenylboronic acid", "role": "boronic_acid_or_ester", "equivalents": None,
             "limiting": False, "role_source": "user_stated"},
        ]
        outside["reaction"]["product"] = {"name": "3-phenylthiophene", "characterization": None}
        payload = run_engine(engine_subject(schema_v2.validate(outside)))
        placement = payload["placement"]
        self.assertEqual(placement["status"], "NO_COMPARABLE")
        self.assertEqual(placement["same_pair_count"], 0)
        self.assertEqual(placement["library_same_class_count"], 19)
        self.assertIn("同底物对", placement["reason"])
        self.assertIn("19", placement["reason"])
        self.assertNotIn("没有任何已核验记录", placement["reason"])
        self.assertEqual(placement["observed"], 42)

    def test_class_rows_are_library_wide_and_never_claim_comparability(self):
        payload = run_engine(engine_subject(CASE))
        for row in payload["classes"]:
            self.assertEqual(row["scope"], "library_wide")
            self.assertFalse(row["comparison_authorized"])
            self.assertNotIn("comparable", row)
            self.assertIn("outcome_type_label", row)

    def test_bridge_exposes_library_and_placement_scopes(self):
        subject = engine_subject(CASE)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            engine_copy = root / "chemcritic_engine.py"
            engine_copy.write_bytes(ENGINE.read_bytes())
            (root / "user.json").write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
            context = agent_result_bridge.execute(engine_copy, root / "user.json", root / "out")
        self.assertEqual(context["library"]["record_count"], 44)
        self.assertEqual(context["library"]["class_counts"]["isolated"], 19)
        self.assertEqual(context["library"]["scope"], "library_wide")
        self.assertEqual(context["placement_scope"]["scope"], "same_outcome_type_and_substrate_pair")
        self.assertIn("same_pair_count", context["placement_scope"])
        self.assertIn("分母不同", context["population_rule"])


class ReportGuardTests(unittest.TestCase):
    def test_internal_tokens_are_reported_without_blocking(self):
        answer = "### 效果评估\n\nplacement: NO_COMPARABLE，因此不做档内定位。"
        tokens = internal_token_findings(answer)
        self.assertTrue({item["token"] for item in tokens} >= {"NO_COMPARABLE"})
        audit = review_report(answer, {}, {"numeric_comparison_allowed": False})
        self.assertEqual(audit["state"], "no_known_conflict_detected")
        self.assertTrue(audit["format_findings"])

    def test_empty_class_claim_is_blocked(self):
        answer = "### 效果评估\n\n库内分离收率记录共有 19 条，但同口径下没有任何已核验记录。"
        self.assertIsNotNone(empty_class_claim(answer))
        audit = review_report(answer, {}, {"numeric_comparison_allowed": False})
        self.assertEqual(audit["state"], "blocked_known_conflict")
        self.assertIn("empty_class_claim", {item["code"] for item in audit["findings"]})

    def test_pair_scoped_statement_is_not_flagged(self):
        answer = ("### 效果评估\n\n固定库共 44 条记录，其中分离收率 19 条；"
                  "与本次底物对、产物相同的分离收率记录没有一条，因此不做档内定位。")
        self.assertIsNone(empty_class_claim(answer))
        audit = review_report(answer, {}, {"numeric_comparison_allowed": False})
        self.assertEqual(audit["state"], "no_known_conflict_detected")
        self.assertEqual(audit["format_findings"], [])

    def test_chinese_caliber_words_are_not_internal_tokens(self):
        self.assertEqual(internal_token_findings("分离收率 19 条，与本次同底物对相同的有 0 条。"), [])

    def test_scope_is_echoed_in_report_review(self):
        scope = reaction_profiles.scope(schema_v2.normalize(CASE))
        audit = review_report("### 效果评估\n\n本次不做数值比较。", {}, {"numeric_comparison_allowed": False}, scope=scope)
        self.assertEqual(audit["engine_scope"]["in_scope"], True)
        self.assertEqual(audit["engine_scope"]["reaction_type"], "suzuki_miyaura")


class ResearchReviewTests(unittest.TestCase):
    """The research flow keeps the team answer but must surface known text defects."""

    def _agent(self):
        from app.chemcritic.shared_agent import SharedAgent

        class Offline(SharedAgent):
            def _run(self, job_id, data):
                self._update(job_id, working=False, state="completed")

        return Offline("key", client_factory=lambda: None, execution_mode="research")

    def test_research_review_warns_without_replacing_the_answer(self):
        agent = self._agent()
        snapshot = agent.start("33333333-3333-3333-3333-333333333333", CASE, None)
        answer = ("### 效果评估\n\n库内分离收率记录共有 19 条，但同口径下没有任何已核验记录。\n\n"
                  "### 推断边界\n本次不做数值比较。")
        agent._update(snapshot["id"], answer=answer, state="completed",
                      prompt_source={"policy": "team_role_document"})
        agent._review_answer(snapshot["id"])
        job = agent.snapshot(snapshot["id"])
        self.assertEqual(job["answer"], answer)  # never silently replaced
        review = job["report_review"]
        self.assertEqual(review["state"], "team_policy_not_independently_verified")
        self.assertTrue(review["consistency_warnings"])
        self.assertEqual(review["consistency_warnings"][0]["code"], "empty_class_claim")

    def test_research_job_uses_one_library_for_local_and_remote(self):
        agent = self._agent()
        snapshot = agent.start("44444444-4444-4444-4444-444444444444", CASE, None)
        self.assertEqual(snapshot["engine_profile"], "team44")
        self.assertEqual(snapshot["execution"]["library_record_count"], 44)
        self.assertTrue(snapshot["record_scope"]["in_scope"])
        self.assertEqual(snapshot["input_goal_preview"]["goal_comparison"]["state"], "below_target")

    def test_out_of_scope_job_has_no_certificate(self):
        agent = self._agent()
        record = schema_v2.normalize({
            "schema_version": schema_v2.SCHEMA, "experiment_id": "BH-9", "simulated": False,
            "reaction": {"type": "buchwald_hartwig",
                         "reactants": [{"name": "4-bromoanisole", "role": "aryl_halide"},
                                       {"name": "morpholine", "role": "amine"}],
                         "product": {"name": "4-morpholinoanisole"}},
            "conditions": {}, "results": {"value_pct": 78, "metric": "isolated",
                                          "characterization": [{"method": "1H NMR", "supports_target": True,
                                                               "provenance": "user_report"}]},
            "user_goal": None})
        snapshot = agent.start("55555555-5555-5555-5555-555555555555", record, None)
        self.assertFalse(snapshot["record_scope"]["in_scope"])
        self.assertEqual(snapshot["execution"]["state"], "out_of_engine_scope")
        self.assertIsNone(snapshot["execution"]["certificate"])


class PackageTests(unittest.TestCase):
    def test_pinned_engine_hash_matches_profile_and_bundle(self):
        _, metadata = engine_profiles.load_profile("team44")
        blob, bundle_metadata = research_bundle.build_bundle()
        self.assertEqual(bundle_metadata["engine_sha256"], metadata["program_sha256"])
        self.assertEqual(hashlib.sha256(engine(ENGINE)).hexdigest(), metadata["program_sha256"])
        self.assertTrue(blob)

    def test_manifest_covers_every_file(self):
        manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
        mismatched = [name for name, digest in manifest.items()
                      if not (ROOT / name).is_file()
                      or hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
        self.assertEqual(mismatched, [])


def engine(path):
    return Path(path).read_bytes()


if __name__ == "__main__":
    unittest.main()
