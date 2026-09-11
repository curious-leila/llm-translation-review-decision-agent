from __future__ import annotations

import unittest

from review_triage.demo_evidence_pack_v1 import load_demo_evidence_pack_v1
from review_triage.demo_evidence_retrieval_v2 import DemoEvidenceRetrievalV2
from review_triage.demo.contracts import to_review_result
from review_triage.evidence import action_input_state
from review_triage.evidence_tools import ControlledEvidenceTools
from review_triage.normative_admission import DemoNormativeAdmissionV1
from review_triage.persistence import SQLiteRepository
from review_triage.schemas import (
    EvidenceAction,
    EvidenceActionDecision,
    EvidenceAssessment,
    EvidenceAssessmentItem,
    EvidenceStatus,
    EvidenceToolResult,
    TerminologyEvidenceState,
    ToolResultStatus,
)
from review_triage.term_anchor import (
    DEMO_TERM_ANCHOR_RESOLVER_V1,
    DemoTermAnchorResolverV1,
)
from review_triage.workflow import ReviewTriageWorkflow
from review_triage.workflow import TERM_ANCHOR_AMBIGUOUS
from tests.helpers import FakeStructuredLLM


class _SearchOfficialOnce:
    model_version = "term-anchor-workflow-selector"
    prompt_version = "term-anchor-workflow-selector-v1"

    def __init__(self) -> None:
        self.call_count = 0

    def select_action(
        self, state: TerminologyEvidenceState
    ) -> EvidenceActionDecision:
        self.call_count += 1
        if state.tool_call_count == 0:
            return EvidenceActionDecision(
                action=EvidenceAction.SEARCH_OFFICIAL_DOCS,
                reason="Exercise the registered Demo anchor once.",
                query="Query wording does not own term identity.",
                based_on_tool_call_count=state.tool_call_count,
                input_state=action_input_state(state),
                model_version=self.model_version,
                prompt_version=self.prompt_version,
            )
        return EvidenceActionDecision(
            action=EvidenceAction.ABSTAIN,
            reason="No further action is required by this fixture.",
            query=None,
            based_on_tool_call_count=state.tool_call_count,
            input_state=action_input_state(state),
            model_version=self.model_version,
            prompt_version=self.prompt_version,
        )


class _AlwaysRelevantAssessor:
    def assess(self, *, state, candidates):
        return EvidenceAssessment(
            assessments=[
                EvidenceAssessmentItem(
                    candidate_id=candidate.candidate_id,
                    relevant=True,
                    context_match=True,
                    reason="Candidate matches the resolved registered term.",
                )
                for candidate in candidates
            ],
            model_version="term-anchor-workflow-assessor",
            prompt_version="term-anchor-workflow-assessor-v1",
        )


class _DemoOfficialTools(ControlledEvidenceTools):
    def __init__(self, retrieval: DemoEvidenceRetrievalV2) -> None:
        super().__init__()
        self.retrieval = retrieval
        self.received_term_candidates: list[str | None] = []

    def search_official_docs(
        self,
        query: str,
        *,
        term_candidate: str | None = None,
    ) -> EvidenceToolResult:
        self.received_term_candidates.append(term_candidate)
        return self.retrieval.search_official_docs(
            query,
            term_candidate=term_candidate,
        )


class DemoTermAnchorWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SQLiteRepository(":memory:")
        self.pack = load_demo_evidence_pack_v1()

    def tearDown(self) -> None:
        self.repository.close()

    def build_workflow(
        self,
        term_candidate: str,
        *,
        term_anchor_resolver=None,
    ):
        selector = _SearchOfficialOnce()
        tools = _DemoOfficialTools(DemoEvidenceRetrievalV2(self.pack))
        workflow = ReviewTriageWorkflow(
            repository=self.repository,
            llm=FakeStructuredLLM(
                terminology_requires_evidence=True,
                terminology_term_candidate=term_candidate,
            ),
            evidence_selector=selector,
            evidence_assessor=_AlwaysRelevantAssessor(),
            evidence_tools=tools,
            normative_admission_policy=DemoNormativeAdmissionV1(self.pack),
            term_anchor_resolver=(
                term_anchor_resolver
                if term_anchor_resolver is not None
                else DemoTermAnchorResolverV1.from_pack(self.pack)
            ),
            available_evidence_actions=(EvidenceAction.SEARCH_OFFICIAL_DOCS,),
        )
        return workflow, selector, tools

    def test_historical_mkt_020_candidate_reaches_ten_01_and_becomes_sufficient(self) -> None:
        raw_candidate = (
            "COOL TENCEL™ (specifically the TENCEL™ brand component)"
        )
        workflow, selector, tools = self.build_workflow(raw_candidate)

        result = workflow.run(
            eval_run_id="term-anchor-mkt-020-regression",
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

        evidence = result.terminology_evidence
        self.assertEqual(evidence.raw_term_candidate, raw_candidate)
        self.assertEqual(evidence.term_candidate, "TENCEL™")
        self.assertEqual(evidence.term_anchor_resolution_status, "RESOLVED")
        self.assertEqual(
            evidence.term_anchor_policy_version,
            DEMO_TERM_ANCHOR_RESOLVER_V1,
        )
        self.assertEqual(tools.received_term_candidates, ["TENCEL™"])
        self.assertEqual(evidence.tool_call_count, 1)
        self.assertEqual(evidence.tool_calls[0].result_status, ToolResultStatus.HIT)
        self.assertEqual(evidence.evidence_status, EvidenceStatus.SUFFICIENT)
        self.assertEqual(
            [
                item.candidate_id
                for item in evidence.normative_admission_decisions
                if item.admitted
            ],
            ["TEN-01"],
        )
        self.assertEqual(len(evidence.verified_evidence), 1)
        self.assertEqual(selector.call_count, 1)
        public_result = to_review_result(result)
        self.assertEqual(public_result.evidence.raw_term_candidate, raw_candidate)
        self.assertEqual(public_result.evidence.resolved_term_anchor, "TENCEL™")
        self.assertEqual(
            public_result.trajectory.evidence.term_anchor_policy_version,
            DEMO_TERM_ANCHOR_RESOLVER_V1,
        )
        anchor_step = next(
            step
            for step in public_result.trajectory.steps
            if step.step_id == "term-anchor-resolution"
        )
        self.assertIn("TENCEL™", anchor_step.summary_zh)

    def test_unregistered_flodesk_anchor_preserves_real_retrieval_miss(self) -> None:
        workflow, selector, tools = self.build_workflow("Flodesk Studio")

        result = workflow.run(
            eval_run_id="term-anchor-flodesk-regression",
            raw_input={
                "source_text": "Flodesk Studio designs an email.",
                "translation": "Flodesk Studio 可以设计邮件。",
                "content_type": "MARKETING",
                "brand_or_domain": "flodesk.com",
            },
        )

        evidence = result.terminology_evidence
        self.assertEqual(evidence.evidence_status, EvidenceStatus.INSUFFICIENT)
        self.assertEqual(evidence.term_anchor_resolution_status, "UNRESOLVED")
        self.assertIsNone(evidence.resolved_term_anchor)
        self.assertEqual(evidence.tool_call_count, 1)
        self.assertEqual(tools.received_term_candidates, ["Flodesk Studio"])
        self.assertEqual(selector.call_count, 2)
        anchor_step = next(
            step
            for step in to_review_result(result).trajectory.steps
            if step.step_id == "term-anchor-resolution"
        )
        self.assertEqual(anchor_step.status, "UNRESOLVED")
        self.assertIn("按原候选执行受控检索", anchor_step.summary_zh)

    def test_ambiguous_registered_anchor_stops_before_retrieval(self) -> None:
        workflow, selector, tools = self.build_workflow(
            "天丝兰精",
            term_anchor_resolver=DemoTermAnchorResolverV1(("天丝", "兰精")),
        )

        result = workflow.run(
            eval_run_id="term-anchor-ambiguous-regression",
            raw_input={
                "source_text": "天丝兰精",
                "translation": "天丝兰精",
                "content_type": "MARKETING",
                "brand_or_domain": "example.com",
            },
        )

        evidence = result.terminology_evidence
        self.assertEqual(evidence.term_anchor_resolution_status, "AMBIGUOUS")
        self.assertEqual(evidence.stop_reason, TERM_ANCHOR_AMBIGUOUS)
        self.assertEqual(evidence.evidence_status, EvidenceStatus.INSUFFICIENT)
        self.assertEqual(evidence.tool_call_count, 0)
        self.assertEqual(tools.received_term_candidates, [])
        self.assertEqual(selector.call_count, 0)
        public_result = to_review_result(result)
        self.assertEqual(
            public_result.trajectory.evidence.term_anchor_resolution_status,
            "AMBIGUOUS",
        )
        anchor_step = next(
            step
            for step in public_result.trajectory.steps
            if step.step_id == "term-anchor-resolution"
        )
        self.assertEqual(anchor_step.status, "SAFE_ABSTAIN")
        self.assertIn("停止检索", anchor_step.summary_zh)


if __name__ == "__main__":
    unittest.main()
