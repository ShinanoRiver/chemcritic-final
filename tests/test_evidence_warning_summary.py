import unittest
from test_product_evidence import record,BARE
from app.chemcritic import product_evidence,rules

class WarningSummaryTests(unittest.TestCase):
    def test_small_gap_propagates_without_changing_thresholds_or_goal(self):
        self.assertEqual((product_evidence.INTEGRAL_PASS,product_evidence.INTEGRAL_WARN),(0.5,2.0))
        for n,expected in [(12,'structured_consistent'),(13,'structured_warning'),(16,'structured_inconsistent')]:
            r=record([{**BARE,'formula':'C13H12O','proton_integral':n}])
            r['results']['value_pct']=64
            result=rules.review(r,[]);e=result['product_evidence']
            self.assertEqual(e['state'],expected)
            self.assertFalse(e['structure_confirmed'])
            self.assertEqual(result['goal_comparison']['gap_pp'],-4)
            if n==13:
                self.assertIn('相差 1H',e['prompt_summary'])
                self.assertTrue(any('待核查项' in w for w in result['warnings']))

    def test_warning_in_other_entry_not_hidden_by_one_passing_entry(self):
        entries=[{**BARE,'formula':'C13H12O','proton_integral':12},{**BARE,'formula':'C13H12O','proton_integral':13}]
        e=product_evidence.grade(record(entries))
        self.assertEqual(e['state'],'structured_warning')
        self.assertIn('相差 1H',e['prompt_summary'])

    def test_human_review_does_not_hide_numeric_warning(self):
        e=product_evidence.grade(record([{**BARE,'formula':'C13H12O','proton_integral':13,'provenance':'human_review','review_reference':'TEST-REVIEW'}]))
        self.assertEqual(e['state'],'structured_warning')
        self.assertTrue(product_evidence.followup(e['state']))
