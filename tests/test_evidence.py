from __future__ import annotations

import unittest

from review_triage.evidence import TerminologyEvidenceLoop, action_input_state
from review_triage.evidence_tools import ControlledEvidenceTools
from review_triage.errors import LLMProcessingError
from review_triage.schemas import (
    EvidenceAction,
    EvidenceCandidate,
    EvidenceProvenance,
    EvidenceStatus,
    TerminologyEvidenceState,
)
from tests.helpers import AcceptRelevantAssessor, FeedbackDrivenSelector


def candidate(
    provenance: EvidenceProvenance,
    *,
    claim_value: str = "继续",
    official: bool = False,
    validation_status: str | None = None,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        term_candidate="Continue",
        provenance=provenance,
        source_ref=f"{provenance.value.casefold()}://continue",
        content=f"Continue → {claim_value}",
        claim_key="continue",
        claim_value=claim_value,
        brand_or_domain="Acme",
        is_official_source=official,
        supports_normative_claim=official,
        validation_status=validation_status,
    )


class EvidenceLoopTests(unittest.TestCase):
    def run_loop(
        self,
        *,
        tools: ControlledEvidenceTools,
        normative_claim: bool = False,
        brand: str | None = "Acme",
        max_tool_calls: int = 4,
    ):
        selector = FeedbackDrivenSelector()
        state = TerminologyEvidenceState(
            case_id="case-1",
            term_candidate="Continue",
            evidence_need=(
                "official designated UI term" if normative_claim else "brand UI term"
            ),
            normative_claim=normative_claim,
            brand_or_domain=brand,
            max_tool_calls=max_tool_calls,
        )
        result = TerminologyEvidenceLoop(
            selector=selector,
            assessor=AcceptRelevantAssessor(),
            tools=tools,
        ).run(state)
        return result, selector

    def test_first_sufficient_admission_stops_without_second_selector_call(self) -> None:
        result, selector = self.run_loop(
            tools=ControlledEvidenceTools(
                glossary=[candidate(EvidenceProvenance.GLOSSARY, official=True)]
            )
        )
        self.assertEqual(result.evidence_status, EvidenceStatus.SUFFICIENT)
        self.assertEqual(result.tool_call_count, 1)
        self.assertEqual(
            [item.action for item in result.action_history],
            [EvidenceAction.SEARCH_GLOSSARY],
        )
        self.assertEqual(result.stop_action, EvidenceAction.STOP_SUFFICIENT)
        self.assertEqual(result.stop_reason, "EVIDENCE_SUFFICIENT")
        self.assertEqual(len(selector.seen_states), 1)

    def test_miss_changes_next_action(self) -> None:
        result, selector = self.run_loop(
            tools=ControlledEvidenceTools(
                official_docs=[
                    candidate(EvidenceProvenance.OFFICIAL_DOCS, official=True)
                ]
            )
        )
        self.assertEqual(result.tools_called, ["search_glossary", "search_official_docs"])
        self.assertEqual(result.tool_calls[0].result_status.value, "MISS")
        second = result.action_history[1]
        self.assertEqual(second.action, EvidenceAction.SEARCH_OFFICIAL_DOCS)
        self.assertEqual(second.based_on_tool_call_count, 1)
        self.assertEqual(
            second.input_state["previous_tool_results"][-1]["result_status"],
            "MISS",
        )
        self.assertIn("Glossary MISS", second.reason)
        self.assertEqual(len(selector.seen_states), 2)

    def test_initial_action_is_context_dependent_not_fixed(self) -> None:
        official_result, _ = self.run_loop(
            normative_claim=True,
            tools=ControlledEvidenceTools(
                official_docs=[
                    candidate(EvidenceProvenance.OFFICIAL_DOCS, official=True)
                ]
            ),
        )
        memory_result, _ = self.run_loop(
            brand=None,
            tools=ControlledEvidenceTools(
                case_memory=[
                    candidate(
                        EvidenceProvenance.CASE_MEMORY,
                        validation_status="HUMAN_VALIDATED",
                    )
                ]
            ),
        )
        self.assertEqual(official_result.action_history[0].action, EvidenceAction.SEARCH_OFFICIAL_DOCS)
        self.assertEqual(memory_result.action_history[0].action, EvidenceAction.SEARCH_MEMORY)

    def test_conflicting_verified_evidence_abstains(self) -> None:
        class TwoSourceSelector(FeedbackDrivenSelector):
            def select_action(self, state):
                snapshot = action_input_state(state)
                if state.tool_call_count == 0:
                    return self._decision(
                        state,
                        snapshot,
                        EvidenceAction.SEARCH_MEMORY,
                        "Check approved historical cases.",
                        state.term_candidate,
                    )
                return self._decision(
                    state,
                    snapshot,
                    EvidenceAction.SEARCH_OFFICIAL_DOCS,
                    "Cross-check the glossary claim against official docs.",
                    state.term_candidate,
                )

        state = TerminologyEvidenceState(
            case_id="case-1",
            term_candidate="Continue",
            evidence_need="cross-source designated term",
            normative_claim=True,
            brand_or_domain="Acme",
        )
        result = TerminologyEvidenceLoop(
            selector=TwoSourceSelector(),
            assessor=AcceptRelevantAssessor(),
            tools=ControlledEvidenceTools(
                case_memory=[
                    candidate(
                        EvidenceProvenance.CASE_MEMORY,
                        validation_status="HUMAN_VALIDATED",
                    )
                ],
                official_docs=[
                    candidate(
                        EvidenceProvenance.OFFICIAL_DOCS,
                        claim_value="持续",
                        official=True,
                    )
                ],
            ),
        ).run(state)
        self.assertEqual(result.evidence_status, EvidenceStatus.CONFLICT)
        self.assertEqual(result.stop_action, EvidenceAction.ABSTAIN)
        self.assertEqual(result.stop_reason, "VERIFIED_EVIDENCE_CONFLICT")
        self.assertEqual(result.tool_call_count, 2)
        self.assertEqual(
            [item.action for item in result.action_history],
            [EvidenceAction.SEARCH_MEMORY, EvidenceAction.SEARCH_OFFICIAL_DOCS],
        )

    def test_tool_budget_prevents_extra_call(self) -> None:
        result, _ = self.run_loop(
            tools=ControlledEvidenceTools(), max_tool_calls=1
        )
        self.assertEqual(result.evidence_status, EvidenceStatus.INSUFFICIENT)
        self.assertEqual(result.stop_reason, "TOOL_BUDGET_REACHED")
        self.assertEqual(result.tool_call_count, 1)

    def test_all_reasonable_tools_miss_then_agent_abstains(self) -> None:
        result, _ = self.run_loop(tools=ControlledEvidenceTools(), max_tool_calls=4)
        self.assertEqual(result.evidence_status, EvidenceStatus.INSUFFICIENT)
        self.assertEqual(result.stop_action, EvidenceAction.ABSTAIN)
        self.assertEqual(result.tool_call_count, 3)
        self.assertEqual(
            result.tools_called,
            ["search_glossary", "search_official_docs", "search_case_memory"],
        )
        self.assertIn("controlled sources returned MISS", result.stop_reason)

    def test_unvalidated_memory_is_never_verified(self) -> None:
        result, _ = self.run_loop(
            brand=None,
            tools=ControlledEvidenceTools(
                case_memory=[candidate(EvidenceProvenance.CASE_MEMORY)]
            ),
        )
        self.assertEqual(result.evidence_status, EvidenceStatus.INSUFFICIENT)
        self.assertEqual(result.verified_evidence, [])

    def test_assessment_failure_is_explicit_safe_escalation(self) -> None:
        class BrokenAssessor:
            def assess(self, **kwargs):
                raise LLMProcessingError(
                    "LLM_API_FAILURE",
                    "assessment provider unavailable",
                    node_name="NODE-03",
                )

        selector = FeedbackDrivenSelector()
        state = TerminologyEvidenceState(
            case_id="case-1",
            term_candidate="Continue",
            evidence_need="brand UI term",
            brand_or_domain="Acme",
        )
        result = TerminologyEvidenceLoop(
            selector=selector,
            assessor=BrokenAssessor(),
            tools=ControlledEvidenceTools(
                glossary=[candidate(EvidenceProvenance.GLOSSARY, official=True)]
            ),
        ).run(state)
        self.assertEqual(result.evidence_status, EvidenceStatus.INSUFFICIENT)
        self.assertEqual(result.stop_action, EvidenceAction.ABSTAIN)
        self.assertEqual(
            result.stop_reason, "EVIDENCE_ASSESSMENT_ERROR:LLM_API_FAILURE"
        )
        self.assertEqual(result.tool_call_count, 1)

    def test_normative_claim_rejects_memory_only_sufficiency(self) -> None:
        class MemoryFirstSelector(FeedbackDrivenSelector):
            def select_action(self, state):
                decision = super().select_action(state)
                if state.tool_call_count == 0:
                    snapshot = decision.input_state
                    return self._decision(
                        state,
                        snapshot,
                        EvidenceAction.SEARCH_MEMORY,
                        "Check approved historical cases.",
                        state.term_candidate,
                    )
                return decision

        state = TerminologyEvidenceState(
            case_id="case-1",
            term_candidate="Continue",
            evidence_need="official designated term",
            normative_claim=True,
            brand_or_domain="Acme",
        )
        selector = MemoryFirstSelector()
        result = TerminologyEvidenceLoop(
            selector=selector,
            assessor=AcceptRelevantAssessor(),
            tools=ControlledEvidenceTools(
                case_memory=[
                    candidate(
                        EvidenceProvenance.CASE_MEMORY,
                        validation_status="HUMAN_VALIDATED",
                    )
                ]
            ),
        ).run(state)
        self.assertEqual(result.evidence_status, EvidenceStatus.INSUFFICIENT)
        self.assertEqual(result.stop_reason, "STOP_SUFFICIENT_REJECTED_BY_GUARDRAIL")
        self.assertEqual(result.tool_call_count, 1)
        self.assertEqual(len(selector.seen_states), 2)


if __name__ == "__main__":
    unittest.main()
