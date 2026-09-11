from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from review_triage.day2_baselines import (
    build_comparative_c_workflow,
    load_frozen_available_evidence_actions,
    load_shared_evidence_tools,
)
from review_triage.demo.contracts import (
    ReviewResultDTO,
    build_review_agent_trajectory,
    to_review_result,
)
from review_triage.demo_evidence_retrieval_v2 import DemoEvidenceRetrievalV2
from review_triage.evidence import TerminologyEvidenceLoop, action_input_state
from review_triage.evidence_tools import ControlledEvidenceTools
from review_triage.normative_admission import DEMO_NORMATIVE_ADMISSION_V1
from review_triage.persistence import SQLiteRepository
from review_triage.schemas import (
    EvidenceAction,
    EvidenceActionDecision,
    EvidenceAssessment,
    EvidenceAssessmentItem,
    EvidenceCandidate,
    EvidenceProvenance,
    EvidenceStatus,
    EvidenceToolResult,
    NormativeAdmissionReasonCode,
    TerminologyEvidenceState,
    ToolResultStatus,
)
from tests.helpers import FakeStructuredLLM


class _SearchOfficialOnce:
    model_version = "demo-runtime-fixed-selector"
    prompt_version = "demo-runtime-fixed-selector-v1"

    def __init__(self, *, query: str | None = None) -> None:
        self.call_count = 0
        self.query = query

    def select_action(self, state: TerminologyEvidenceState) -> EvidenceActionDecision:
        self.call_count += 1
        snapshot = action_input_state(state)
        if state.tool_call_count == 0:
            return EvidenceActionDecision(
                action=EvidenceAction.SEARCH_OFFICIAL_DOCS,
                reason="Deterministically exercise the Demo official-doc action once.",
                query=self.query or state.term_candidate,
                based_on_tool_call_count=state.tool_call_count,
                input_state=snapshot,
                model_version=self.model_version,
                prompt_version=self.prompt_version,
            )
        return EvidenceActionDecision(
            action=EvidenceAction.ABSTAIN,
            reason="The deterministic integration fixture has no further action.",
            query=None,
            based_on_tool_call_count=state.tool_call_count,
            input_state=snapshot,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
        )


class _AlwaysRelevantAssessor:
    def __init__(self) -> None:
        self.call_count = 0

    def assess(self, *, state, candidates):
        self.call_count += 1
        return EvidenceAssessment(
            assessments=[
                EvidenceAssessmentItem(
                    candidate_id=candidate.candidate_id,
                    relevant=True,
                    context_match=True,
                    reason="Fixed relevant/context-match result for runtime integration.",
                )
                for candidate in candidates
            ],
            model_version="demo-runtime-fixed-assessor",
            prompt_version="demo-runtime-fixed-assessor-v1",
        )


class _FixedOfficialResultTools(ControlledEvidenceTools):
    def __init__(self, candidate: EvidenceCandidate) -> None:
        super().__init__()
        self.candidate = candidate
        self.received_calls: list[tuple[str, str | None]] = []

    def search_official_docs(
        self,
        query: str,
        *,
        term_candidate: str | None = None,
    ) -> EvidenceToolResult:
        self.received_calls.append((query, term_candidate))
        return EvidenceToolResult(
            status=ToolResultStatus.HIT,
            candidates=[self.candidate],
            summary="One direct negative-control integration candidate.",
        )


def _import_demo_live():
    sys.modules.pop("review_triage.demo.live", None)
    with (
        patch(
            "review_triage.providers.deepseek.DeepSeekProvider.from_env",
            return_value=Mock(),
        ),
        patch("review_triage.persistence.SQLiteRepository", return_value=Mock()),
    ):
        return importlib.import_module("review_triage.demo.live")


class DemoEvidenceRuntimeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.live = _import_demo_live()

    @classmethod
    def tearDownClass(cls) -> None:
        sys.modules.pop("review_triage.demo.live", None)

    def setUp(self) -> None:
        self.repository = SQLiteRepository(":memory:")

    def tearDown(self) -> None:
        self.repository.close()

    def build_workflow(self, term: str, *, selector_query: str | None = None):
        selector = _SearchOfficialOnce(query=selector_query)
        assessor = _AlwaysRelevantAssessor()
        workflow = self.live.build_demo_v1_workflow(
            repository=self.repository,
            llm=FakeStructuredLLM(
                terminology_requires_evidence=True,
                terminology_term_candidate=term,
            ),
            evidence_selector=selector,
            evidence_assessor=assessor,
        )
        return workflow, selector, assessor

    def test_tencel_runs_pack_retrieval_admission_and_strict_sufficiency(self) -> None:
        workflow, selector, assessor = self.build_workflow(
            "TENCEL™",
            selector_query="TENCEL™ 兰精 官方中文品牌名",
        )

        result = workflow.run(
            eval_run_id="demo-runtime-tencel",
            raw_input={
                "source_text": "TENCEL™",
                "translation": "天丝™",
                "content_type": "MARKETING",
                "brand_or_domain": "brooklinen.com",
            },
        )

        self.assertIsNone(result.processing_error)
        self.assertIsInstance(workflow.evidence_tools.official_docs, DemoEvidenceRetrievalV2)
        self.assertEqual(
            workflow.normative_admission_policy.policy_version,
            DEMO_NORMATIVE_ADMISSION_V1,
        )
        self.assertEqual(len(workflow.normative_admission_policy.pack.snapshot_sha256), 64)
        evidence = result.terminology_evidence
        self.assertEqual(evidence.tool_calls[0].result_status, ToolResultStatus.HIT)
        self.assertEqual(
            {decision.candidate_id for decision in evidence.normative_admission_decisions},
            {"TEN-01", "TEN-02", "TEN-03", "TEN-04"},
        )
        admitted = [
            decision
            for decision in evidence.normative_admission_decisions
            if decision.admitted
        ]
        self.assertEqual([decision.candidate_id for decision in admitted], ["TEN-01"])
        self.assertEqual(len(evidence.verified_evidence), 1)
        self.assertTrue(evidence.verified_evidence[0].admitted_normative_evidence)
        self.assertEqual(len(evidence.tool_calls[0].candidate_reviews), 4)
        candidate_reviews = {
            review.candidate_id: review for review in evidence.tool_calls[0].candidate_reviews
        }
        self.assertTrue(candidate_reviews["TEN-01"].admitted)
        self.assertFalse(candidate_reviews["TEN-02"].admitted)
        self.assertIn(
            NormativeAdmissionReasonCode.TERM_MISMATCH,
            candidate_reviews["TEN-02"].admission_reason_codes,
        )
        self.assertEqual(
            evidence.verified_evidence[0].admission_policy_version,
            DEMO_NORMATIVE_ADMISSION_V1,
        )
        public_result = to_review_result(result).model_dump(mode="json")
        self.assertEqual(
            len(public_result["evidence"]["tool_calls"][0]["candidate_reviews"]),
            4,
        )
        self.assertEqual(
            public_result["evidence"]["tool_calls"][0]["candidate_reviews"][1]["admitted"],
            False,
        )
        self.assertEqual(evidence.evidence_status, EvidenceStatus.SUFFICIENT)
        self.assertEqual(evidence.stop_action, EvidenceAction.STOP_SUFFICIENT)
        self.assertEqual(evidence.stop_reason, "EVIDENCE_SUFFICIENT")
        self.assertEqual(selector.call_count, 1)
        self.assertEqual(assessor.call_count, 1)

    def test_real_mkt_020_query_runs_retrieval_admission_and_deterministic_stop(self) -> None:
        live_query = "TENCEL 天丝 官方 中文名称 Lenzing"
        workflow, selector, assessor = self.build_workflow(
            "TENCEL™",
            selector_query=live_query,
        )

        result = workflow.run(
            eval_run_id="demo-runtime-mkt-020-live-query",
            raw_input={
                "source_text": (
                    "COOL TENCEL™. Refreshing, smooth, with barely-there feel,\n"
                    "introducing our coolest fabric yet."
                ),
                "translation": "酷爽天丝™。清爽顺滑，几乎无感，隆重推出我们迄今最酷爽的面料。",
                "content_type": "MARKETING",
                "brand_or_domain": "brooklinen.com",
            },
        )

        self.assertIsNone(result.processing_error)
        evidence = result.terminology_evidence
        self.assertEqual(evidence.tool_call_count, 1)
        self.assertEqual(evidence.tool_calls[0].query, live_query)
        self.assertEqual(evidence.tool_calls[0].result_status, ToolResultStatus.HIT)
        self.assertIn(
            "TEN-01",
            {
                assessment.candidate_id
                for group in evidence.assessments
                for assessment in group.assessments
            },
        )
        admitted = [
            decision
            for decision in evidence.normative_admission_decisions
            if decision.admitted
        ]
        self.assertEqual([decision.candidate_id for decision in admitted], ["TEN-01"])
        self.assertEqual(len(evidence.verified_evidence), 1)
        self.assertTrue(evidence.verified_evidence[0].admitted_normative_evidence)
        self.assertEqual(evidence.evidence_status, EvidenceStatus.SUFFICIENT)
        self.assertEqual(evidence.stop_action, EvidenceAction.STOP_SUFFICIENT)
        self.assertEqual(evidence.stop_reason, "EVIDENCE_SUFFICIENT")
        self.assertEqual(selector.call_count, 1)
        self.assertEqual(assessor.call_count, 1)

    def test_flodesk_studio_is_a_real_retrieval_miss_and_never_sufficient(self) -> None:
        workflow, selector, assessor = self.build_workflow("Flodesk Studio")

        result = workflow.run(
            eval_run_id="demo-runtime-flodesk-miss",
            raw_input={
                "source_text": "Flodesk Studio",
                "translation": "Flodesk 工作室",
                "content_type": "MARKETING",
                "brand_or_domain": "flodesk.com",
            },
        )

        evidence = result.terminology_evidence
        self.assertEqual(evidence.tool_call_count, 1)
        self.assertEqual(evidence.tool_calls[0].result_status, ToolResultStatus.MISS)
        self.assertEqual(evidence.verified_evidence, [])
        self.assertEqual(evidence.normative_admission_decisions, [])
        self.assertEqual(evidence.evidence_status, EvidenceStatus.INSUFFICIENT)
        self.assertEqual(evidence.stop_action, EvidenceAction.ABSTAIN)
        self.assertEqual(selector.call_count, 2)
        self.assertEqual(assessor.call_count, 0)

    def test_brooklinen_official_negative_control_cannot_be_admitted(self) -> None:
        workflow, selector, assessor = self.build_workflow("TENCEL")
        candidate = EvidenceCandidate(
            candidate_id="NC-A",
            term_candidate="TENCEL™",
            provenance=EvidenceProvenance.OFFICIAL_DOCS,
            source_ref="BROOKLINEN-OFFICIAL-HOME",
            content="Brooklinen official homepage without an aligned Chinese term pair.",
            claim_key="official_chinese_brand_form",
            claim_value="TENCEL™ → 天丝™",
            target_locale="zh-CN",
            scenario="MARKETING_BRAND",
            is_official_source=True,
            supports_normative_claim=True,
        )
        state = TerminologyEvidenceState(
            case_id="demo-runtime-brooklinen-negative",
            term_candidate="TENCEL™",
            evidence_need="Confirm the official Chinese brand form.",
            normative_claim=True,
            brand_or_domain="brooklinen.com",
            target_locale="zh-CN",
            max_tool_calls=1,
            available_actions=[EvidenceAction.SEARCH_OFFICIAL_DOCS],
        )

        tools = _FixedOfficialResultTools(candidate)
        evidence = TerminologyEvidenceLoop(
            selector=selector,
            assessor=assessor,
            tools=tools,
            normative_admission_policy=workflow.normative_admission_policy,
        ).run(state)

        self.assertEqual(tools.received_calls, [("TENCEL™", "TENCEL™")])
        self.assertEqual(evidence.verified_evidence, [])
        self.assertEqual(evidence.evidence_status, EvidenceStatus.INSUFFICIENT)
        self.assertFalse(evidence.normative_admission_decisions[0].admitted)
        self.assertIn(
            NormativeAdmissionReasonCode.TERM_PAIR_NOT_ATTESTED,
            evidence.normative_admission_decisions[0].reason_codes,
        )
        self.assertEqual(assessor.call_count, 1)

    def test_day2_factories_and_historical_retrieval_shape_remain_legacy(self) -> None:
        day2_tools = load_shared_evidence_tools()
        day2_workflow = build_comparative_c_workflow(
            repository=self.repository,
            llm=FakeStructuredLLM(),
        )

        self.assertIsInstance(day2_tools, ControlledEvidenceTools)
        self.assertIsNone(day2_workflow.normative_admission_policy)
        self.assertEqual(
            load_frozen_available_evidence_actions(),
            (EvidenceAction.SEARCH_OFFICIAL_DOCS,),
        )
        result = day2_tools.search_official_docs("paypal.com payment")
        self.assertEqual(result.status, ToolResultStatus.HIT)
        self.assertEqual(
            [candidate.candidate_id for candidate in result.candidates],
            [
                "official-doc-paypal-help111-v2",
                "official-doc-paypal-help518-v2",
            ],
        )
        self.assertEqual(
            set(result.model_dump(mode="json")),
            {"status", "candidates", "summary", "error_message"},
        )

class DemoStaticPresentationTests(unittest.TestCase):
    project_root = Path(__file__).resolve().parents[1]
    static_root = project_root / "src" / "review_triage" / "demo" / "static"

    def test_landing_is_an_hr_first_replay_workbench(self) -> None:
        index = (self.static_root / "index.html").read_text(encoding="utf-8")
        app = (self.static_root / "app.js").read_text(encoding="utf-8")
        styles = (self.static_root / "styles.css").read_text(encoding="utf-8")

        self.assertIn("<title>面向大模型译文的审校决策Agent</title>", index)
        self.assertIn("Noto+Serif+SC", index)
        self.assertIn('--font-serif:"Noto Serif SC"', styles)
        self.assertNotRegex(styles, r"font-weight:(650|730|750|800|850)")
        self.assertIn("让每条译文，走到合适的审校路径。", index)
        self.assertNotIn("让每条 AI 译文，都有证据地通过。", index)
        self.assertNotIn("让专业的 AI，做专业的判断。", index)
        self.assertNotIn("RECORDED RUN · 默认展示冻结案例", index)
        self.assertIn("真实运行回放 · 后端结果快照", index)
        self.assertIn("按需取证", index)
        self.assertIn("轨迹可回放", index)
        self.assertIn("安全弃权", index)
        self.assertIn("待审译文", index)
        self.assertIn("Agent 行动轨迹", index)
        self.assertIn("审校结论与可信证据", index)
        self.assertIn('<p class="eyebrow hero-eyebrow">面向大模型译文的审校决策Agent</p>', index)
        self.assertNotIn("TRANSLATION REVIEW DECISION AGENT", index)
        self.assertNotIn("只在判断依赖外部事实时查证", index)
        self.assertNotIn("输入、行动、证据与路由同源", index)
        self.assertNotIn("证据不足时停止自主判断", index)
        self.assertIn("<span>无需查证</span>", index)
        self.assertIn("<span>证据验证</span>", index)
        self.assertIn("<span>证据不足</span>", index)
        self.assertIn("<span>自动通过</span>", index)
        self.assertNotIn("进入抽样复核</small>", index)
        self.assertNotIn("命中不等于接纳</small>", index)
        self.assertNotIn("转人工复核</small>", index)
        self.assertNotIn("默认案例</small>", index)
        self.assertIn('class="live-entry-icon"', index)
        self.assertIn('aria-hidden="true"', index)
        self.assertIn("前置评测用于形成冻结路由策略，不是当前 Agent 上线后的效果指标。", index)
        self.assertIn('role="tablist"', index)
        self.assertIn('role="status"', index)
        self.assertIn("data-default-replay", index)
        self.assertIn("data-open-live", index)
        self.assertNotIn('id="result-view"', index)
        self.assertNotIn('class="decision-mechanism"', index)
        self.assertNotIn('class="architecture"', index)
        self.assertIn('data-display-case-id="CS-020"', index)
        self.assertIn('data-display-case-id="MKT-020"', index)
        self.assertIn('data-display-case-id="MKT-005"', index)
        self.assertIn('data-display-case-id="UI-003"', index)
        self.assertIn('{ cache: "no-store" }', app)
        self.assertNotIn('href="/assets/', index)
        self.assertNotIn('src="/assets/', index)
        self.assertNotIn('data-replay-url="/assets/', index)
        self.assertIn(
            'const API_BASE_URL = "https://llm-translation-review-decision-agent.onrender.com";',
            app,
        )
        self.assertIn('fetch(`${API_BASE_URL}/api/review`', app)
        self.assertNotIn('fetch("/api/review"', app)
        self.assertIn("snapshot?.result?.trajectory", app)
        self.assertIn("data?.trajectory", app)
        self.assertIn("证据不足 · 安全弃权 → 人工复核", app)
        self.assertIn("ArrowRight", app)
        self.assertIn("aria-selected", app)

    def test_verified_replays_expose_business_ids_without_mutating_case_ids(self) -> None:
        expected = {
            "refund-no-evidence.json": "CS-020",
            "mkt-020-evidence-validation.json": "MKT-020",
            "mkt-005-safe-failure.json": "MKT-005",
            "ui-003-agent-success.json": "UI-003",
        }
        for filename, display_case_id in expected.items():
            snapshot = json.loads((self.static_root / "replays" / filename).read_text(encoding="utf-8"))
            self.assertEqual(snapshot["replay_metadata"]["display_case_id"], display_case_id)
            self.assertEqual(snapshot["result"]["display_case_id"], display_case_id)
            self.assertEqual(snapshot["replay_metadata"]["source_case_id"], snapshot["result"]["case_id"])

    def test_all_verified_replays_share_the_deterministic_trajectory_contract(self) -> None:
        expected_outcomes = {
            "refund-no-evidence.json": ("NOT_REQUIRED", "SAMPLE_POOL"),
            "mkt-020-evidence-validation.json": ("INSUFFICIENT", "HUMAN_REQUIRED"),
            "mkt-005-safe-failure.json": ("INSUFFICIENT", "HUMAN_REQUIRED"),
            "ui-003-agent-success.json": ("SUFFICIENT", "AUTO_PASS"),
        }
        for filename, (evidence_status, route_code) in expected_outcomes.items():
            with self.subTest(filename=filename):
                snapshot = json.loads(
                    (self.static_root / "replays" / filename).read_text(encoding="utf-8")
                )
                raw_result = snapshot["result"]
                trajectory = raw_result["trajectory"]
                contract_payload = {
                    key: value
                    for key, value in raw_result.items()
                    if key in ReviewResultDTO.model_fields and key != "trajectory"
                }
                rebuilt = build_review_agent_trajectory(
                    ReviewResultDTO.model_validate(contract_payload)
                ).model_dump(mode="json")

                self.assertEqual(trajectory, rebuilt)
                self.assertEqual(
                    trajectory["schema_version"], "review-agent-trajectory/v1"
                )
                self.assertEqual(trajectory["case"], raw_result["case"])
                self.assertEqual(trajectory["risk"], raw_result["risk"])
                self.assertEqual(trajectory["dimensions"], raw_result["dimensions"])
                self.assertEqual(
                    trajectory["reliability_decisions"],
                    raw_result["reliability_decisions"],
                )
                self.assertEqual(trajectory["evidence"]["status"], evidence_status)
                self.assertEqual(trajectory["final_route"]["code"], route_code)
                self.assertTrue(trajectory["steps"])
                self.assertTrue(
                    all(step["fact_refs"] for step in trajectory["steps"])
                )
                evidence_gate = next(
                    (step for step in trajectory["steps"] if step["step_id"] == "evidence-gate"),
                    None,
                )
                if trajectory["evidence"]["required"]:
                    self.assertIsNotNone(evidence_gate)
                    self.assertRegex(evidence_gate["summary_zh"], r"[\u3400-\u9fff]")
                    self.assertNotRegex(
                        evidence_gate["summary_zh"],
                        r"^The Terminology",
                    )
                if evidence_status == "INSUFFICIENT":
                    self.assertIn(
                        "证据不足 · 安全弃权 → 人工复核。",
                        [step["summary_zh"] for step in trajectory["steps"]],
                    )

    def test_trajectory_localizes_an_english_evidence_need_reason(self) -> None:
        snapshot = json.loads(
            (self.static_root / "replays" / "mkt-020-evidence-validation.json").read_text(
                encoding="utf-8"
            )
        )
        raw_result = snapshot["result"]
        contract_payload = {
            key: value
            for key, value in raw_result.items()
            if key in ReviewResultDTO.model_fields and key != "trajectory"
        }
        contract_payload["post_eval_control"]["terminology_reason"] = (
            "The Terminology judgment depends on an unverified official naming fact."
        )

        trajectory = build_review_agent_trajectory(
            ReviewResultDTO.model_validate(contract_payload)
        )
        evidence_gate = next(
            step for step in trajectory.steps if step.step_id == "evidence-gate"
        )

        self.assertRegex(trajectory.evidence.need_reason, r"[\u3400-\u9fff]")
        self.assertEqual(evidence_gate.summary_zh, trajectory.evidence.need_reason)
        self.assertNotIn("The Terminology", evidence_gate.summary_zh)


if __name__ == "__main__":
    unittest.main()
