"""Product-identity evidence: grading, schema round-trip and report guards.

Run from the package root:

    python -m unittest discover -s tests -v
"""

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chemcritic import product_evidence, rules, schema_v2
from app.chemcritic.report_contract import (REPORT_REQUIREMENTS, product_claim_overreach,
                                            product_data_conflict_ignored, review_report)
from app.chemcritic.research_request import build_prompt, prompt_metadata

CASE = json.loads((ROOT / "cases/C2_simulated_42_goal60.json").read_text(encoding="utf-8"))


def record(entries, **results):
    return schema_v2.validate({
        "schema_version": schema_v2.SCHEMA, "experiment_id": "PE-1", "simulated": False,
        "reaction": {"type": "suzuki_miyaura",
                     "reactants": [{"name": "4-bromoanisole", "role": "aryl_halide",
                                    "equivalents": 1, "limiting": True},
                                   {"name": "phenylboronic acid", "role": "boronic_acid_or_ester",
                                    "equivalents": 1.2}],
                     "product": {"name": "4-methoxybiphenyl"}},
        "conditions": {"temperature_C": 60, "time_h": 12},
        "results": {"value_pct": 42, "metric": "isolated", "characterization": entries, **results},
        "user_goal": {"minimum_yield_pct": 60, "metric": "isolated"},
    })


BARE = {"method": "1H NMR", "supports_target": True, "provenance": "user_report"}


class FormulaTests(unittest.TestCase):
    def test_common_formula_is_parsed_and_massed(self):
        counts, error = product_evidence.parse_formula("C13H12O")
        self.assertIsNone(error)
        self.assertEqual(counts, {"C": 13, "H": 12, "O": 1})
        self.assertAlmostEqual(product_evidence.monoisotopic_mass(counts), 184.0888, places=4)
        self.assertAlmostEqual(product_evidence.theoretical_mz(counts), 185.0961, places=4)

    def test_unknown_element_and_garbage_are_reported_not_guessed(self):
        self.assertEqual(product_evidence.parse_formula("C13H12X")[0], None)
        self.assertIn("X", product_evidence.parse_formula("C13H12X")[1])
        self.assertIsNone(product_evidence.parse_formula("13C")[0])
        self.assertIsNone(product_evidence.parse_formula("")[0])

    def test_adduct_shifts(self):
        counts, _ = product_evidence.parse_formula("C13H12O")
        hydrogen = product_evidence.theoretical_mz(counts, "[M+H]+")
        sodium = product_evidence.theoretical_mz(counts, "[M+Na]+")
        self.assertGreater(sodium - hydrogen, 21.9)
        self.assertLess(sodium - hydrogen, 22.1)
        self.assertIsNone(product_evidence.theoretical_mz(counts, "[M+Cl]-"))


class GradeTests(unittest.TestCase):
    """The grade must separate a claim from data, without pretending to verify either."""

    def grade(self, entries, **results):
        return product_evidence.grade(record(entries, **results))

    def test_no_entries_is_missing(self):
        self.assertEqual(self.grade([])["state"], "missing")

    def test_declared_contradiction_wins(self):
        result = self.grade([BARE, {"method": "1H NMR", "supports_target": False,
                                    "provenance": "user_report"}])
        self.assertEqual(result["state"], "contradictory")
        self.assertTrue(product_evidence.blocks_goal_comparison("contradictory"))

    def test_bare_claim_stays_a_claim(self):
        result = self.grade([BARE])
        self.assertEqual(result["state"], "user_report_only")
        self.assertEqual(result["checks"], [])

    def test_formula_and_integral_agree(self):
        result = self.grade([{**BARE, "formula": "C13H12O", "proton_integral": 12}])
        self.assertEqual(result["state"], "structured_consistent")
        self.assertEqual({check["id"] for check in result["checks"]} & {"integral_vs_formula"}, {"integral_vs_formula"})

    def test_formula_and_hrms_agree(self):
        result = self.grade([{**BARE, "method": "HRMS", "formula": "C13H12O", "mz": 185.0961}])
        self.assertEqual(result["state"], "structured_consistent")
        self.assertEqual([check["state"] for check in result["checks"] if check["id"] == "hrms_vs_formula"], ["pass"])

    def test_small_integral_gap_is_a_warning_not_a_conflict(self):
        result = self.grade([{**BARE, "formula": "C13H12O", "proton_integral": 11}])
        self.assertEqual(result["state"], "structured_warning")
        self.assertIn('相差',result['prompt_summary'])
        self.assertEqual([check["state"] for check in result["checks"]
                          if check["id"] == "integral_vs_formula"], ["warn"])

    def test_gross_integral_gap_is_a_conflict(self):
        result = self.grade([{**BARE, "formula": "C13H12O", "proton_integral": 25}])
        self.assertEqual(result["state"], "structured_inconsistent")
        self.assertEqual(result["index"], 0)

    def test_wrong_mass_is_a_conflict(self):
        result = self.grade([{**BARE, "method": "HRMS", "formula": "C13H12O", "mz": 310.5}])
        self.assertEqual(result["state"], "structured_inconsistent")

    def test_values_without_a_formula_stay_documented(self):
        self.assertEqual(self.grade([{**BARE, "mz": 185.0961}])["state"], "structured_documented")
        self.assertEqual(self.grade([{**BARE, "formula": "C13H12X", "proton_integral": 12}])["state"],
                         "structured_warning")

    def test_human_review_outranks_consistency(self):
        result = self.grade([{**BARE, "provenance": "human_review", "review_reference": "QC-2026-001",
                              "formula": "C13H12O", "proton_integral": 12}])
        self.assertEqual(result["state"], "human_review_recorded")

    def test_attachment_is_recorded_as_traceability_only(self):
        result = self.grade([{**BARE, "spectrum_reference": "NMR-2026-101"}])
        self.assertEqual(result["traceability"], "attachment_recorded")
        self.assertEqual(result["state"], "user_report_only")

    def test_no_grade_ever_claims_confirmation(self):
        samples = [
            [],
            [BARE],
            [{**BARE, "supports_target": False}],
            [{**BARE, "formula": "C13H12O", "proton_integral": 12}],
            [{**BARE, "formula": "C13H12O", "proton_integral": 25}],
            [{**BARE, "provenance": "human_review", "review_reference": "QC-1"}],
        ]
        for entries in samples:
            with self.subTest(entries=entries):
                result = product_evidence.grade(record(entries))
                self.assertFalse(result["independently_verified_by_system"])
                self.assertFalse(result["structure_confirmed"])
                self.assertEqual(result["source"], "user_report")
                self.assertTrue(result["limitation"])
                self.assertTrue(result["label"])

    def test_malformed_record_degrades_to_missing(self):
        self.assertEqual(product_evidence.state_of(None), "missing")
        self.assertEqual(product_evidence.state_of({"results": {"characterization": "nope"}}), "missing")


class SchemaTests(unittest.TestCase):
    def test_observation_values_round_trip(self):
        entries = [{**BARE, "formula": "C13H12O", "proton_integral": 12, "mz": 185.0961,
                    "mz_adduct": "[M+H]+", "observation_text": "δ 7.58 (d, 2H)",
                    "spectrum_reference": "NMR-1"}]
        normalized = record(entries)["results"]["characterization"][0]
        for key, value in entries[0].items():
            self.assertEqual(normalized[key], value)

    def test_legacy_entries_without_values_still_normalize(self):
        normalized = record([BARE])["results"]["characterization"][0]
        self.assertEqual(normalized["method"], "1H NMR")
        self.assertFalse(normalized["raw_spectrum_provided"])
        self.assertNotIn("proton_integral", normalized)

    def test_bad_types_are_rejected(self):
        for broken in ({**BARE, "proton_integral": "12"}, {**BARE, "mz": -1},
                       {**BARE, "mz_adduct": "[M+Cl]-"}, {**BARE, "formula": "C" * 61},
                       {**BARE, "supports_target": "yes"}):
            with self.subTest(broken=broken), self.assertRaises(schema_v2.ValidationError):
                record([broken])

    def test_upgrade_path_keeps_characterization(self):
        legacy = json.loads(json.dumps(CASE))
        legacy["results"]["characterization"] = [BARE]
        upgraded = schema_v2.normalize(legacy)
        self.assertEqual(upgraded["results"]["characterization"][0]["method"], "1H NMR")


class ReviewTests(unittest.TestCase):
    def test_review_carries_the_grade_and_its_reasons(self):
        result = rules.review(record([BARE]), [])
        evidence = result["product_evidence"]
        self.assertEqual(evidence["state"], "user_report_only")
        self.assertEqual(evidence["label"], product_evidence.STATES["user_report_only"]["label"])
        self.assertTrue(evidence["reasons"])
        self.assertFalse(evidence["independently_verified_by_system"])

    def test_missing_evidence_blocks_goal_comparison(self):
        result = rules.review(record([]), [])
        self.assertEqual(result["status"], "S3")
        self.assertEqual(result["reason_code"], "evidence_gap")
        self.assertEqual(result["goal_comparison"]["state"], "unavailable")

    def test_checkable_data_keeps_goal_comparison(self):
        result = rules.review(record([{**BARE, "formula": "C13H12O", "proton_integral": 12}]), [])
        self.assertEqual(result["goal_comparison"]["state"], "below_target")

    def test_inconsistent_data_warns_without_hiding_the_arithmetic(self):
        result = rules.review(record([{**BARE, "formula": "C13H12O", "proton_integral": 25}]), [])
        self.assertEqual(result["product_evidence"]["state"], "structured_inconsistent")
        self.assertEqual(result["goal_comparison"]["state"], "below_target")
        self.assertTrue(any("不一致" in warning for warning in result["warnings"]))
        self.assertIn("A05B_EVIDENCE_CONFLICT", [check["rule_id"] for check in result["next_checks"]])

    def test_followup_asks_for_data_not_for_a_verdict(self):
        result = rules.review(record([BARE]), [])
        fields = [item["field"] for item in result["followups"]]
        self.assertIn("results.characterization[0].observation_text", fields)

    def test_reviewed_evidence_does_not_trigger_another_followup(self):
        result = rules.review(record([{**BARE, "provenance": "human_review",
                                       "review_reference": "QC-1"}]), [])
        self.assertEqual(result["product_evidence"]["state"], "human_review_recorded")
        self.assertNotIn("results.characterization", [item["field"] for item in result["followups"]])


class ReportGuardTests(unittest.TestCase):
    """A report may not turn user-reported evidence into confirmation."""

    def setUp(self):
        self.evidence = product_evidence.grade(record([BARE]))

    def test_confirmation_wording_is_flagged(self):
        answer = "### 效果评估\n\n本次已确证产物结构，收率 42%。"
        finding = product_claim_overreach(answer, self.evidence)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["code"], "product_claim_overreach")

    def test_negated_and_conditional_wording_passes(self):
        for answer in ("### 推断边界\n\n用户自述匹配，不能确证结构。",
                       "### 效果评估\n\n若无标准品比对，结构尚未确证。",
                       "### 效果评估\n\n目前无法确认结构。"):
            with self.subTest(answer=answer):
                self.assertIsNone(product_claim_overreach(answer, self.evidence))

    def test_attributed_human_review_passes(self):
        answer = "### 效果评估\n\n结构经人工复核确认（记录 QC-2026-001），未由系统独立核验。"
        self.assertIsNone(product_claim_overreach(answer, self.evidence))

    def test_review_report_reports_it_as_a_warning_not_a_block(self):
        audit = review_report("### 效果评估\n\n本次已确证目标产物结构，收率 42%。",
                              record([BARE]), {"numeric_comparison_allowed": False})
        self.assertEqual(audit["state"], "no_known_conflict_detected")
        self.assertEqual([item["code"] for item in audit["consistency_warnings"]],
                         ["product_claim_overreach"])
        self.assertEqual(audit["product_evidence"]["state"], "user_report_only")

    def test_conflict_ignored_is_flagged_only_when_data_disagree(self):
        inconsistent = product_evidence.grade(record([{**BARE, "formula": "C13H12O", "proton_integral": 25}]))
        answer = "### 效果评估\n\n积分与分子式一致，结构可靠。"
        self.assertEqual(product_data_conflict_ignored(answer, inconsistent)["code"],
                         "product_data_conflict_ignored")
        self.assertIsNone(product_data_conflict_ignored(answer, self.evidence))
        self.assertIsNone(product_data_conflict_ignored(
            "### 效果评估\n\n积分与分子式不一致，需核对。", inconsistent))

    def test_missing_record_does_not_crash_the_guard(self):
        audit = review_report("### 效果评估\n\n已确证结构。", {}, {"numeric_comparison_allowed": False})
        self.assertIsNone(audit["product_evidence"])


class EngineCompatibilityTests(unittest.TestCase):
    """The pinned engine is hash-locked, so an unparseable interpreter is named."""

    def _prepare_with(self, stderr):
        import subprocess as subprocess_module
        from unittest.mock import patch
        from app.chemcritic import request_execution
        finished = subprocess_module.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)
        with patch("app.chemcritic.request_execution.subprocess.run", return_value=finished):
            with self.assertRaises(ValueError) as caught:
                request_execution.prepare(CASE, profile="team44")
        return str(caught.exception)

    def test_argparse_incompatibility_points_at_python_311(self):
        message = self._prepare_with("ValueError: badly formed help string")
        self.assertIn("3.11", message)
        self.assertIn("argparse", message)

    def test_other_engine_failures_keep_the_generic_message(self):
        self.assertEqual(self._prepare_with("boom"), "Local frozen-engine input validation failed")


class FrontendWiringTests(unittest.TestCase):
    """The page and the script must agree on ids and on evidence-row controls."""

    def setUp(self):
        self.js = (ROOT / "app/chemcritic/static/app.js").read_text(encoding="utf-8")
        self.html = (ROOT / "app/chemcritic/static/index.html").read_text(encoding="utf-8")

    def test_every_element_id_used_by_the_script_exists(self):
        ids = set(re.findall(r'\$\("([^"]+)"\)', self.js))
        missing = sorted(item for item in ids if f'id="{item}"' not in self.html)
        self.assertEqual(missing, [])

    def test_evidence_row_writer_and_reader_use_the_same_controls(self):
        writer = self.js[self.js.index("function addEvidenceRow("):self.js.index("function readEvidenceRows(")]
        reader = self.js[self.js.index("function readEvidenceRows("):self.js.index("function readRows(")]
        names = sorted(set(re.findall(r"\.evidence-([a-z]+)", reader)))
        self.assertTrue(names)
        for name in names:
            self.assertIn(f"evidence-{name}", writer)
        self.assertIn('id="evidence-rows"', self.html)
        self.assertNotIn('name="evidence"', self.html)


class PromptTests(unittest.TestCase):
    def test_prompt_states_the_evidence_boundary_before_the_data(self):
        text = json.dumps({"experiment": schema_v2.normalize(CASE)}, ensure_ascii=False)
        prompt = build_prompt(text)
        self.assertIn("产物结构证据的表述边界", prompt)
        self.assertIn("不得写“已确证产物", prompt)
        self.assertTrue(prompt.endswith(text))

    def test_prompt_metadata_records_the_policy(self):
        metadata = prompt_metadata()
        self.assertEqual(metadata["product_evidence_policy"], "user_supplied_evidence_graded_never_confirmed")

    def test_report_requirements_carry_the_clause(self):
        self.assertIn("结构证据全部由用户填报", REPORT_REQUIREMENTS)
        self.assertIn("不得写“已确证产物", REPORT_REQUIREMENTS)


if __name__ == "__main__":
    unittest.main()
