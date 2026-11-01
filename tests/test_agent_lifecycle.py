"""End-to-end lifecycle test with a scripted SciencePal stand-in (no network).

Locks the behaviour that produced "本次分析未完成" in the UI after a single
failed preparation attempt: the status must follow the **latest** observed
attempt, and an agent-reported failure in the final report must still win.
"""

import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chemcritic.shared_agent import AGENT_ID, SharedAgent

RUN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
THREAD_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

REPORT = """### 效果评估

按用户所报数据，本次分离收率 42% 与自设目标 60% 还有 18 个百分点；该值来自用户表单口径，未独立核验。
固定库共 44 条记录，其中分离收率 19 条；与本次同底物对、产物相同的分离收率记录为 1 条，因此只能说明存在同口径参照，不做档内定位。

### 实验建议

1. 先核对本次的碱与载量记录：没有碱就无法判断体系档位。
2. 补一次同条件的分离称重记录：这是获得与目标同口径数据的唯一途径。

### 缺失与追问

- 碱的种类与当量未提供。
- 气氛与规模未记录。

### 证据与来源

本轮未取得任何文献来源；固定库内容来自本地证书，未经原文核验。

### 实验信息

模拟案例，非真实湿实验；4-溴苯甲醚与苯硼酸，Pd(PPh3)4，THF，60 °C，12 h，分离收率 42%。

### 推断边界

用户报告不等于独立确认；条件差异不证明原因；不同口径不换算。
"""


def tool_event(name, tool_call_id, arguments, result, success=True):
    return {"type": "tool",
            "content": {"name": name, "tool_call_id": tool_call_id, "content": result},
            "metadata": {"tool_success": success,
                         "tool_audit": {"tool_call_id": tool_call_id, "arguments": arguments}}}


def final_event(text):
    return {"type": "assistant", "content": {"content": text, "tool_calls": []},
            "metadata": {"stream_status": "complete"}}


class FakeResponse:
    def __init__(self, status_code=200, payload=None, lines=None, chunks=None):
        self.status_code = status_code
        self._payload = payload or {}
        self._lines = lines or []
        self._chunks = chunks or []

    def json(self):
        return self._payload

    def iter_lines(self):
        for line in self._lines:
            yield line

    def iter_bytes(self):
        for chunk in self._chunks:
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeClient:
    """Scripted stand-in for the SciencePal HTTP client."""

    def __init__(self, events, final_status="completed"):
        self.events = events
        self.final_status = final_status
        self.initiated = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, headers=None, params=None):
        if url.endswith("/agents"):
            return FakeResponse(200, {"agents": [{"agent_id": AGENT_ID}]})
        if "/agent-run/" in url:
            return FakeResponse(200, {"id": RUN_ID, "threadId": THREAD_ID, "status": self.final_status})
        if url.endswith("/sandbox"):
            return FakeResponse(200, {"sandbox_id": "sandbox-1"})
        return FakeResponse(404, {})

    def post(self, url, headers=None, data=None, files=None):
        self.initiated = {"data": data, "files": files}
        return FakeResponse(200, {"agent_run_id": RUN_ID, "thread_id": THREAD_ID})

    def stream(self, method, url, headers=None, params=None):
        if url.endswith("/stream"):
            lines = []
            for event in self.events:
                lines.append("data: " + json.dumps(event, ensure_ascii=False))
                lines.append("")
            lines.append("data: [DONE]")
            lines.append("")
            return FakeResponse(200, lines=lines)
        return FakeResponse(200, chunks=[REPORT.encode("utf-8")])


def failed_attempt(identifier="call-1", session="sess-1"):
    return tool_event("execute_command", identifier,
                      {"command": "python /workspace/chemcritic_uploaded/run_preflight.py", "blocking": True},
                      {"exit_code": 1, "completed": True, "session_name": session,
                       "output": "preparation_failed", "timed_out": False})


def succeeded_attempt(identifier="call-2", session="sess-2"):
    return tool_event("execute_command", identifier,
                      {"command": "python /workspace/chemcritic_uploaded/run_preflight.py", "blocking": True},
                      {"exit_code": 0, "completed": True, "session_name": session,
                       "output": '{"state": "ready"}', "timed_out": False})


class LifecycleTests(unittest.TestCase):
    def run_agent(self, events, final_status="completed"):
        client = FakeClient(events, final_status=final_status)
        agent = SharedAgent("test-key", client_factory=lambda: client, execution_mode="research")
        job = agent.start("11111111-2222-3333-4444-555555555555",
                          request_text="模拟案例：4-溴苯甲醚与苯硼酸，分离收率 42%，目标 60%。")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and agent.snapshot(job["id"])["working"]:
            time.sleep(0.05)
        return agent.snapshot(job["id"]), client

    def test_late_success_clears_the_failure_status(self):
        job, client = self.run_agent([failed_attempt(), succeeded_attempt(), final_event(REPORT)])
        self.assertFalse(job["working"])
        self.assertEqual(job["state"], "completed")
        self.assertTrue(job["answer"].startswith("### 效果评估"))
        self.assertNotEqual((job.get("analysis_status") or {}).get("state"), "incomplete")
        self.assertTrue(client.initiated["files"], "offline bundle must stay attached for text input")

    def test_failure_is_kept_when_no_later_success_is_observed(self):
        job, _ = self.run_agent([failed_attempt(), final_event(REPORT)])
        status = job.get("analysis_status") or {}
        self.assertEqual(status.get("state"), "incomplete")
        self.assertEqual(status.get("reason"), "preparation_or_execution_failed")
        self.assertEqual(status.get("exit_code"), 1)
        self.assertIn("run_preflight.py", status.get("command", ""))
        # The report itself is still delivered; the failed step is reported separately.
        self.assertTrue(job["answer"].startswith("### 效果评估"))

    def test_agent_reported_failure_wins_over_tool_history(self):
        report = REPORT.replace("### 推断边界",
                                "本次判定未能完成：固定程序自检未通过，未取得任何判定结果。\n\n### 推断边界")
        job, _ = self.run_agent([succeeded_attempt(), final_event(report)])
        status = job.get("analysis_status") or {}
        self.assertEqual(status.get("state"), "incomplete")
        self.assertEqual(status.get("reason"), "agent_reported_failure")


class ClassificationFabricationTests(unittest.TestCase):
    """The engine turns catalytic_profile into a tier, so it must stay user-declared."""

    def test_audit_flags_invented_profile(self):
        from app.chemcritic.extraction_contract import audit_mapping
        record = {"outcome": {"value": 88, "outcome_type": "conversion"},
                  "substrate": {},
                  "catalytic_profile": {"catalyst_form": "molecular_complex", "ligand_family": "phosphine"}}
        audit = audit_mapping("结果 88%", record)
        self.assertIn("invented_derived_classification", [item["code"] for item in audit["findings"]])

    def test_audit_flags_profile_declared_but_user_never_stated_it(self):
        from app.chemcritic.extraction_contract import audit_mapping
        record = {"outcome": {"value": 88, "outcome_type": "conversion"}, "substrate": {},
                  "inputs_source": {"catalytic_profile.catalyst_form": "user_stated"}}
        audit = audit_mapping("结果 88%", record)
        self.assertIn("invented_derived_classification", [item["code"] for item in audit["findings"]])

    def test_clean_record_has_no_classification_finding(self):
        from app.chemcritic.extraction_contract import audit_mapping
        record = {"outcome": {"value": 88, "outcome_type": "conversion"}, "substrate": {}}
        audit = audit_mapping("结果 88%", record)
        self.assertEqual([item["code"] for item in audit["findings"]], [])

    def test_prompt_keeps_the_prohibition(self):
        prompt = (ROOT / "app/chemcritic/prompts/team_v8_direct.txt").read_text(encoding="utf-8")
        self.assertIn("catalytic_profile", prompt)
        self.assertIn("不要写", prompt)
        self.assertIn("molecular_complex", prompt)

    def test_research_review_surfaces_the_mapping_warning(self):
        agent = SharedAgent("key", client_factory=lambda: None, execution_mode="research")
        job = agent.start("33333333-1111-1111-1111-333333333333", request_text="模拟案例")
        agent._update(job["id"], answer="### 效果评估\n\n正文。", state="completed",
                      prompt_source={"policy": "team_role_document"},
                      mapping_events=[{"record": {"catalytic_profile": {"catalyst_form": "molecular_complex"}},
                                       "audit": {"findings": [{"code": "invented_derived_classification"}]}}])
        agent._review_answer(job["id"])
        review = agent.snapshot(job["id"])["report_review"]
        self.assertIn("invented_derived_classification",
                      [item["code"] for item in review["consistency_warnings"]])


class ExecutionStatusTests(unittest.TestCase):
    def status(self, event, sessions=None):
        from app.chemcritic.analysis_status import execution_status
        return execution_status(event, sessions if sessions is not None else {})

    def test_failed_command_reports_command_and_exit_code(self):
        status = self.status(failed_attempt())
        self.assertEqual(status["state"], "incomplete")
        self.assertEqual(status["exit_code"], 1)
        self.assertIn("run_preflight.py", status["command"])
        self.assertEqual(status["script"], "run_preflight.py")

    def test_success_is_its_own_state(self):
        status = self.status(succeeded_attempt())
        self.assertEqual(status["state"], "tool_attempt_succeeded")
        self.assertEqual(status["exit_code"], 0)

    def test_watched_session_is_attributed_to_the_script(self):
        sessions = {}
        self.status(failed_attempt(session="sess-9"), sessions)
        watched = tool_event("check_command_output", "call-3", {"session_name": "sess-9"},
                             {"exit_code": 0, "completed": True, "session_name": "sess-9"})
        status = self.status(watched, sessions)
        self.assertEqual(status["state"], "tool_attempt_succeeded")

    def test_dispatched_without_exit_code_does_not_change_status(self):
        dispatched = tool_event("execute_command", "call-4",
                                {"command": "python run_preflight.py"},
                                {"exit_code": None, "completed": None, "session_name": "s"})
        self.assertIsNone(self.status(dispatched))

    def test_unrelated_command_is_ignored(self):
        other = tool_event("execute_command", "call-5", {"command": "ls /workspace"},
                           {"exit_code": 2, "completed": True})
        self.assertIsNone(self.status(other))


class ReportedFailureTests(unittest.TestCase):
    def test_common_phrasings_are_detected(self):
        from app.chemcritic.analysis_status import reported_failure
        for text in ("本次分析未完成。", "本次判定未能完成：固定程序自检未通过。",
                     "本轮无法完成判定。", "本次无法完成分析，原因是输入被拒绝。",
                     "本次程序执行未完成：退出码 2。"):
            self.assertTrue(reported_failure(text), text)

    def test_limited_judgements_are_not_failures(self):
        from app.chemcritic.analysis_status import reported_failure
        for text in ("本次不做可比性判定，只做事实复盘。",
                     "同口径下没有可比记录，因此不做档内定位。",
                     "本次未取得全文，只依据摘要说明限制。",
                     "本次分析给出结论：分离收率 42%，未达目标。"):
            self.assertFalse(reported_failure(text), text)


class GoalVerdictTests(unittest.TestCase):
    """The arithmetic verdict is shown, and prose cannot contradict it silently."""

    def agent(self):
        class Offline(SharedAgent):
            def _run(self, job_id, data):
                self._update(job_id, working=False, state="completed")
        return Offline("key", client_factory=lambda: None, execution_mode="research")

    def review(self, agent, job_id, answer, goal=None):
        update = {"answer": answer, "state": "completed", "prompt_source": {"policy": "team_role_document"}}
        if goal is not None:
            update["execution"] = {"state": "local_engine_only", "goal_comparison": goal}
        agent._update(job_id, **update)
        agent._review_answer(job_id)
        return agent.snapshot(job_id)["report_review"]

    def test_claim_detector(self):
        from app.chemcritic.report_contract import goal_claim
        self.assertEqual(goal_claim("### 效果评估\n本次已达到用户设定目标 60%。"), "met")
        self.assertEqual(goal_claim("### 效果评估\n本次未达到用户设定目标，差 18 个百分点。"), "not_met")
        self.assertEqual(goal_claim("### 效果评估\n尚未达到目标，需要补测。"), "not_met")
        self.assertIsNone(goal_claim("### 效果评估\n实测与目标口径不同，不能判断目标是否达到。"))
        self.assertIsNone(goal_claim("### 效果评估\n如果补测后达到目标，则说明……"))
        # Literature rows must not be mistaken for the user's own verdict.
        self.assertIsNone(goal_claim("### 证据与来源\n该参照未达标。"))

    def test_summary_wording(self):
        from app.chemcritic.report_contract import goal_summary
        self.assertIn("未达到", goal_summary({"state": "below_target"}))
        self.assertIn("已达到", goal_summary({"state": "met"}))
        self.assertIn("口径不同", goal_summary({"state": "unavailable", "reason": "assay_mismatch"}))
        self.assertIsNone(goal_summary({}))

    def test_summary_survives_research_mode(self):
        agent = self.agent()
        job = agent.start("12121212-1111-4111-8111-111111111111", request_text="模拟案例")
        review = self.review(agent, job["id"], "### 效果评估\n本次未达到用户设定目标，差 18 个百分点。",
                             goal={"state": "below_target", "reason": "goal_below", "gap_pp": 18.0})
        self.assertIn("未达到", review["goal_summary"])
        self.assertEqual(review["goal_claim"], "not_met")
        self.assertEqual([w["code"] for w in review["consistency_warnings"]], [])

    def test_contradiction_is_reported(self):
        agent = self.agent()
        job = agent.start("13131313-1111-4111-8111-111111111111", request_text="模拟案例")
        review = self.review(agent, job["id"], "### 效果评估\n本次已达到用户设定目标 60%。",
                             goal={"state": "below_target", "reason": "goal_below", "gap_pp": 18.0})
        self.assertIn("goal_claim_conflict", [w["code"] for w in review["consistency_warnings"]])
        self.assertEqual(review["state"], "team_policy_not_independently_verified")

    def test_claim_past_a_caliber_mismatch_is_reported(self):
        agent = self.agent()
        job = agent.start("14141414-1111-4111-8111-111111111111", request_text="模拟案例")
        review = self.review(agent, job["id"], "### 效果评估\n本次已达到用户设定目标 80%。",
                             goal={"state": "unavailable", "reason": "assay_mismatch", "gap_pp": None})
        self.assertIn("goal_claim_without_comparable_caliber",
                      [w["code"] for w in review["consistency_warnings"]])
        self.assertIn("口径不同", review["goal_summary"])

    def test_ui_surfaces_the_verdict(self):
        html = (ROOT / "app/chemcritic/static/index.html").read_text(encoding="utf-8")
        js = (ROOT / "app/chemcritic/static/app.js").read_text(encoding="utf-8")
        self.assertIn('id="agent-goal"', html)
        self.assertIn("goal_summary", js)
        self.assertIn("按你所报数据", js)


if __name__ == "__main__":
    unittest.main()
