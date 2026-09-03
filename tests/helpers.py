from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from review_triage.schemas import Dimension, DimensionEvaluation, Severity
from review_triage.prompts import (
    PROMPT_VERSION_BY_DIMENSION,
    RenderedEvaluatorPrompt,
    RenderedStructuredPrompt,
)
from review_triage.llm import POST_EVAL_CONTROL_PROMPT_VERSION
from review_triage.evidence import action_input_state
from review_triage.schemas import (
    EvidenceAction,
    EvidenceActionDecision,
    EvidenceAssessment,
    EvidenceAssessmentItem,
    EvidenceCandidate,
    TerminologyEvidenceState,
)


class FakeStructuredLLM:
    model_version = "fake-model-v1"

    def __init__(
        self,
        *,
        risk_level: str = "LOW",
        severities: dict[Dimension, Severity] | None = None,
        invalid_prompt: str | None = None,
        insufficient_context: bool = False,
        unresolved_dimensions: set[Dimension] | None = None,
        terminology_requires_evidence: bool = False,
        terminology_term_candidate: str = "Continue",
    ) -> None:
        self.risk_level = risk_level
        self.severities = severities or {}
        self.invalid_prompt = invalid_prompt
        self.insufficient_context = insufficient_context
        self.unresolved_dimensions = unresolved_dimensions or set()
        self.terminology_requires_evidence = terminology_requires_evidence
        self.terminology_term_candidate = terminology_term_candidate
        self.calls: list[dict[str, Any]] = []

    def invoke_structured(
        self,
        *,
        prompt_version: str,
        payload: Mapping[str, Any],
        output_schema: type[BaseModel],
        prompt: RenderedEvaluatorPrompt | RenderedStructuredPrompt | None = None,
    ) -> str | Mapping[str, Any]:
        copied = dict(payload)
        self.calls.append(
            {
                "prompt_version": prompt_version,
                "payload": copied,
                "prompt": prompt,
            }
        )
        if prompt_version == self.invalid_prompt:
            return "{definitely-not-json"
        if prompt_version in {
            "node01_risk_classifier_v1",
            "node01_risk_classifier_v2",
            "node01_risk_classifier_v3",
        }:
            if self.insufficient_context:
                return {
                    "risk_level": "INSUFFICIENT_CONTEXT",
                    "risk_factors": ["missing deployment context"],
                    "reason": "Potential consequence depends on where the copy appears.",
                    "missing_context_fields": ["deployment_surface"],
                    "clarification_question": "Where will this copy be shown?",
                }
            return {
                "risk_level": self.risk_level,
                "risk_factors": ["test fixture"],
                "reason": "Structured test risk decision.",
            }
        if prompt_version == POST_EVAL_CONTROL_PROMPT_VERSION:
            return {
                "terminology": {
                    "requires_external_evidence": self.terminology_requires_evidence,
                    "term_candidate": (
                        self.terminology_term_candidate if self.terminology_requires_evidence else None
                    ),
                    "evidence_need": (
                        "official UI term"
                        if self.terminology_requires_evidence
                        else None
                    ),
                    "normative_claim": self.terminology_requires_evidence,
                    "reason": "Test-only structured terminology control judgment.",
                },
                "accuracy": {
                    "unresolved_external_support": (
                        Dimension.ACCURACY in self.unresolved_dimensions
                    ),
                    "reason": "Test-only structured accuracy control judgment.",
                },
                "locale": {
                    "unresolved_external_support": (
                        Dimension.LOCALE in self.unresolved_dimensions
                    ),
                    "reason": "Test-only structured locale control judgment.",
                },
                "audience": {
                    "unresolved_external_support": (
                        Dimension.AUDIENCE in self.unresolved_dimensions
                    ),
                    "reason": "Test-only structured audience control judgment.",
                },
            }

        if prompt_version == "node03_evidence_action_selector_v1":
            if copied["verified_evidence"]:
                return {
                    "action": "STOP_SUFFICIENT",
                    "reason": "The synthetic state now contains context-matched verified evidence.",
                    "query": None,
                }
            return {
                "action": "SEARCH_OFFICIAL_DOCS",
                "reason": "The synthetic normative evidence need requires an official source.",
                "query": copied["term_candidate"],
            }

        if prompt_version == "node03_evidence_assessor_v1":
            return {
                "assessments": [
                    {
                        "candidate_id": item["candidate_id"],
                        "relevant": True,
                        "context_match": True,
                        "reason": "Synthetic candidate matches the requested term and context.",
                    }
                    for item in copied["candidates"]
                ]
            }

        prompt_to_dimension = {
            version: dimension
            for dimension, version in PROMPT_VERSION_BY_DIMENSION.items()
        }
        dimension = prompt_to_dimension.get(
            prompt_version,
            Dimension.TERMINOLOGY
            if prompt_version == "node02a_terminology_final_v1"
            else None,
        )
        if dimension is None:
            raise KeyError(prompt_version)
        is_final_terminology = prompt_version == "node02a_terminology_final_v1"
        dimension_fields: dict[Dimension, dict[str, Any]] = {
            Dimension.TERMINOLOGY: {
                "term_type": None,
            },
            Dimension.ACCURACY: {
                "adjacent_correction": None,
                "boundary_risk": False,
            },
            Dimension.LOCALE: {"locale_element": None, "boundary_risk": False},
            Dimension.AUDIENCE: {"audience_element": None},
        }
        response = {
            "severity": self.severities.get(dimension, Severity.NEUTRAL).value,
            "q1": "fixture finding",
            "q2": "fixture impact",
            "notes": f"Structured {dimension.value} evaluation.",
            **(
                {"model_reported_sources": []}
                if is_final_terminology
                else {"sources": []}
            ),
            **(
                {
                    "term_type": None,
                }
                if is_final_terminology
                else dimension_fields[dimension]
            ),
        }
        return response


def evaluations(
    case_id: str = "case-1",
    *,
    severities: dict[Dimension, Severity] | None = None,
    unresolved: set[Dimension] | None = None,
) -> list[DimensionEvaluation]:
    severities = severities or {}
    unresolved = unresolved or set()
    dimension_fields: dict[Dimension, dict[str, Any]] = {
        Dimension.TERMINOLOGY: {
            "term_type": None,
            "term_candidate": None,
            "evidence_need": None,
            "normative_claim": False,
        },
        Dimension.ACCURACY: {
            "adjacent_correction": None,
            "boundary_risk": False,
        },
        Dimension.LOCALE: {"locale_element": None, "boundary_risk": False},
        Dimension.AUDIENCE: {"audience_element": None},
    }
    return [
        DimensionEvaluation(
            case_id=case_id,
            dimension=dimension,
            severity=severities.get(dimension, Severity.NEUTRAL),
            q1="finding",
            q2="impact",
            notes="fixture",
            dimension_specific=dimension_fields[dimension],
            requires_external_evidence=False,
            unresolved_external_support=dimension in unresolved,
            model_version="fake-model-v1",
            prompt_version=f"{dimension.value.lower()}_v1",
        )
        for dimension in Dimension
    ]


class FeedbackDrivenSelector:
    """Test double that chooses from current state, not a scripted fixed sequence."""

    model_version = "feedback-selector-test-v1"
    prompt_version = "terminology_evidence_action_test_v1"

    def __init__(self) -> None:
        self.seen_states: list[dict[str, Any]] = []

    def select_action(
        self, state: TerminologyEvidenceState
    ) -> EvidenceActionDecision:
        snapshot = action_input_state(state)
        self.seen_states.append(snapshot)
        previous = snapshot["previous_tool_results"]
        verified = snapshot["verified_evidence"]
        if verified:
            action = EvidenceAction.STOP_SUFFICIENT
            reason = "A relevant context-matched evidence item is now available."
            query = None
        elif not previous:
            if state.normative_claim or "official" in state.evidence_need.casefold():
                action = EvidenceAction.SEARCH_OFFICIAL_DOCS
                reason = "Normative claim needs an official controlled source first."
            elif state.brand_or_domain:
                action = EvidenceAction.SEARCH_GLOSSARY
                reason = "Brand context makes the controlled glossary the best first source."
            else:
                action = EvidenceAction.SEARCH_MEMORY
                reason = "Historical human-validated cases best match this non-normative need."
            query = state.term_candidate
        else:
            last = previous[-1]
            if last["tool_name"] == "search_glossary" and last["result_status"] == "MISS":
                action = EvidenceAction.SEARCH_OFFICIAL_DOCS
                reason = "Glossary MISS requires a different controlled source."
            elif last["tool_name"] == "search_official_docs" and last["result_status"] == "MISS":
                action = EvidenceAction.SEARCH_MEMORY
                reason = "Official docs MISS; try human-validated case memory."
            elif last["tool_name"] == "search_case_memory" and last["result_status"] == "MISS":
                action = EvidenceAction.ABSTAIN
                reason = "All context-relevant controlled sources returned MISS."
                query = None
                return self._decision(state, snapshot, action, reason, query)
            else:
                action = EvidenceAction.ABSTAIN
                reason = "No additional safe evidence action remains."
            query = None if action == EvidenceAction.ABSTAIN else state.term_candidate
        return self._decision(state, snapshot, action, reason, query)

    def _decision(
        self,
        state: TerminologyEvidenceState,
        snapshot: dict[str, Any],
        action: EvidenceAction,
        reason: str,
        query: str | None,
    ) -> EvidenceActionDecision:
        return EvidenceActionDecision(
            action=action,
            reason=reason,
            query=query,
            based_on_tool_call_count=state.tool_call_count,
            input_state=snapshot,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
        )


class AcceptRelevantAssessor:
    def assess(
        self,
        *,
        state: TerminologyEvidenceState,
        candidates: list[EvidenceCandidate],
    ) -> EvidenceAssessment:
        return EvidenceAssessment(
            assessments=[
                EvidenceAssessmentItem(
                    candidate_id=item.candidate_id,
                    relevant=True,
                    context_match=(
                        item.target_locale == state.target_locale
                        and (
                            item.brand_or_domain is None
                            or state.brand_or_domain is None
                            or item.brand_or_domain == state.brand_or_domain
                        )
                    ),
                    reason="Candidate matches the requested term and test context.",
                )
                for item in candidates
            ],
            model_version="assessment-test-v1",
            prompt_version="terminology_evidence_assessment_test_v1",
        )
