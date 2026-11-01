import unittest
from app.chemcritic.report_contract import internal_token_findings,visible_report_body,empty_class_claim

class VisibleReportGuardTests(unittest.TestCase):
    def test_english_preamble_not_scanned_as_report(self):
        raw='The engine placement is TIER_UNKNOWN and candidate_count is 3.\n\n### 效果评估\n当前不能给出数值差。'
        self.assertEqual(internal_token_findings(raw),[])
        self.assertTrue(visible_report_body(raw).lstrip().startswith('### 效果评估'))

    def test_visible_token_still_warns(self):
        hits=internal_token_findings('Draft placement TIER_UNKNOWN\n### 效果评估\n本次状态为 TIER_UNKNOWN。')
        self.assertEqual([h['token'] for h in hits],['TIER_UNKNOWN'])

    def test_last_think_boundary_and_raw_unchanged(self):
        raw='### 效果评估\nplacement TIER_UNKNOWN\n</think>### 效果评估\n正文完整。'
        before=raw
        self.assertEqual(internal_token_findings(raw),[])
        self.assertEqual(raw,before)
        self.assertIsNone(empty_class_claim('草稿说同口径下没有任何记录\n### 效果评估\n尚待核查。'))

    def test_no_heading_remains_conservative(self):
        self.assertTrue(internal_token_findings('本次 placement 未提供。'))
        self.assertEqual(internal_token_findings('<think>placement TIER_UNKNOWN'),[])
