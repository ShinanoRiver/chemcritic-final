import unittest
from app.chemcritic.input_context import build_context, report_conflicts
from app.chemcritic.research_request import build_prompt

TEXT = ('模拟测试。\n4-溴苯甲醚为限量试剂，1 mmol，1当量。\n'
        '方法为1H NMR，总积分为13H，目标分子式为C13H12O。\n'
        '保留上述数值，不为使数据一致而修改积分或分子式。')


class RecordFidelityTests(unittest.TestCase):
    def test_scale_is_traced_without_changing_input(self):
        context = build_context(TEXT)
        self.assertEqual(context['known_scale']['value_mmol'], 1)
        self.assertIn(context['known_scale']['source_text'], TEXT)
        self.assertTrue(context['explicit_preservation_requested'])
        self.assertTrue(build_prompt(TEXT).endswith(TEXT))
        self.assertEqual(build_context({'experiment': {'conditions': {'scale_mmol': 2}}})['known_scale']['value_mmol'], 2)

    def test_ambiguous_or_additive_amount_is_not_scale(self):
        self.assertNotIn('known_scale', build_context('添加剂K2CO3 2 mmol。'))
        self.assertNotIn('known_scale', build_context('规模1 mmol\n另一次规模2 mmol'))

    def test_all_three_actual_report_errors_are_detected(self):
        report = ('### 效果评估\n总积分13H与12H相差1H，常见于可交换质子或残留溶剂。\n'
                  '### 实验建议\n若为模拟数据，建议修正模拟录入使其内部一致。\n'
                  '### 缺失与追问\n气氛、规模、溶剂体积、压力均未记录。')
        codes = {x['code'] for x in report_conflicts(report, build_context(TEXT))}
        self.assertTrue({'known_scale_reported_missing', 'original_values_change_advice', 'unsupported_integral_cause'} <= codes)

    def test_safe_report_has_no_false_alarm(self):
        report = ('### 效果评估\n规模为1 mmol，气氛未记录。总积分13H与12H有差异，原因尚未确定。\n'
                  '### 实验建议\n保留原值，不得修改积分或分子式来使其一致。不能归因于残留溶剂。')
        self.assertEqual(report_conflicts(report, build_context(TEXT)), [])

    def test_arithmetic_warning_does_not_supply_chemical_cause(self):
        evidence = build_context(TEXT)['text_evidence_check']['product_evidence']
        self.assertEqual(evidence['state'], 'structured_warning')
        self.assertIn('相差 1H', evidence['prompt_summary'])
        self.assertNotIn('可交换', str(evidence))
        self.assertNotIn('残留溶剂', str(evidence))
