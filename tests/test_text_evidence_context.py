import json
import threading
import unittest
from app.chemcritic.input_context import build_context,text_evidence,report_conflicts
from app.chemcritic.research_request import build_prompt
from app.chemcritic.shared_agent import SharedAgent

TEXT='模拟测试。方法为1H NMR，总积分数值为13，填写的目标分子式为C13H12O。未提供原始谱图。'

class TextEvidenceContextTests(unittest.TestCase):
    def test_explicit_arithmetic_and_source_spans(self):
        c=text_evidence(TEXT)
        self.assertEqual(c['product_evidence']['state'],'structured_warning')
        self.assertIn('相差 1H',c['product_evidence']['prompt_summary'])
        self.assertEqual(c['checked_fields']['proton_integral'],'13')
        for matches in c['source_spans'].values():
            for m in matches:self.assertEqual(TEXT[m['start']:m['end']],m['text'])
        self.assertFalse(c['product_evidence']['structure_confirmed'])

    def test_consistent_and_large_conflict_and_missing(self):
        self.assertEqual(text_evidence(TEXT.replace('为13','为12'))['product_evidence']['state'],'structured_consistent')
        self.assertEqual(text_evidence(TEXT.replace('为13','为16'))['product_evidence']['state'],'structured_inconsistent')
        self.assertEqual(text_evidence('1H NMR匹配，无其他记录')['state'],'not_extracted')
        self.assertEqual(text_evidence(TEXT+'另一次总积分为12H。')['state'],'not_extracted')
        self.assertEqual(text_evidence(TEXT+'另一分子式C12H10。')['state'],'not_extracted')

    def test_full_original_input_is_unchanged_and_ends_prompt(self):
        data=json.dumps({'user_description':TEXT,'experiment':None},ensure_ascii=False)
        prompt=build_prompt(data)
        self.assertTrue(prompt.endswith(data))
        self.assertIn('structured_warning',prompt)
        self.assertIn('相差 1H',prompt)
        self.assertIsInstance(build_context('普通未结构化说明'),dict)

    def test_contradiction_guard_keeps_raw(self):
        ctx=build_context({'user_description':TEXT})
        bad='### 效果评估\n总积分13H与分子式氢数一致，用户数据内部一致。'
        self.assertTrue(report_conflicts(bad,ctx))
        self.assertTrue(report_conflicts('### 效果评估\n总积分13H与分子式氢数一致，用户数据内部一致；但未提供真实谱图，不得写已确证产物。',ctx))
        self.assertFalse(report_conflicts('### 效果评估\n有待核查差异，不能称数据内部一致。',ctx))

    def test_live_review_path_without_remote_call(self):
        done=threading.Event()
        class Offline(SharedAgent):
            def _run(self,job_id,data):
                self._update(job_id,working=False,state='completed');done.set()
        agent=Offline('test-placeholder',client_factory=lambda:None,execution_mode='research')
        job=agent.start('11111111-2222-4333-8444-555555555555',request_text=TEXT)
        self.assertTrue(done.wait(5))
        answer='### 效果评估\n总积分13H与分子式氢数一致。'
        agent._update(job['id'],answer=answer,prompt_source={'policy':'team_role_document'})
        agent._review_answer(job['id']);result=agent.snapshot(job['id'])
        self.assertEqual(result['answer'],answer)
        self.assertIn('product_evidence_check_conflict',[r['code'] for r in result['report_review']['consistency_warnings']])
        self.assertEqual(result['report_review']['input_context']['text_evidence_check']['product_evidence']['state'],'structured_warning')
