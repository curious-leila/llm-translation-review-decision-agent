"""Terminology-only NODE-03 agentic evidence loop."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from review_triage.errors import LLMProcessingError, PolicyConfigurationError
from review_triage.evidence_tools import EvidenceTools
from review_triage.llm import StructuredLLM, _provider_failure_code, parse_strict_output
from review_triage.prompts import ReviewPromptRegistry
from review_triage.schemas import (
    EvidenceAction,
    EvidenceActionDecision,
    EvidenceAssessment,
    EvidenceAssessmentItem,
    EvidenceCandidate,
    EvidenceCandidateReview,
    EvidenceProvenance,
    EvidenceStatus,
    EvidenceToolResult,
    NormativeAdmissionDecision,
    TerminologyEvidenceState,
    ToolCallRecord,
    ToolResultStatus,
    VerifiedEvidence,
)


ACTION_PROMPT_VERSION = "node03_evidence_action_selector_v1"
ASSESSMENT_PROMPT_VERSION = "node03_evidence_assessor_v1"


class _StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ActionLLMOutput(_StrictOutput):
    action: EvidenceAction
    reason: str = Field(min_length=1)
    query: str | None = None


class AssessmentItemLLMOutput(_StrictOutput):
    candidate_id: str
    relevant: bool
    context_match: bool
    reason: str


class AssessmentLLMOutput(_StrictOutput):
    assessments: list[AssessmentItemLLMOutput]


class EvidenceActionSelector(Protocol):
    @property
    def model_version(self) -> str: ...

    @property
    def prompt_version(self) -> str: ...

    def select_action(
        self, state: TerminologyEvidenceState
    ) -> EvidenceActionDecision: ...


class EvidenceCandidateAssessor(Protocol):
    def assess(
        self,
        *,
        state: TerminologyEvidenceState,
        candidates: list[EvidenceCandidate],
    ) -> EvidenceAssessment: ...


class NormativeEvidenceAdmissionPolicy(Protocol):
    @property
    def policy_version(self) -> str: ...

    def admit(
        self,
        *,
        state: TerminologyEvidenceState,
        candidate: EvidenceCandidate,
        assessment: EvidenceAssessmentItem,
    ) -> NormativeAdmissionDecision: ...


def action_input_state(state: TerminologyEvidenceState) -> dict[str, Any]:
    """Snapshot exactly what the action selector sees before choosing."""

    return {
        "term_candidate": state.term_candidate,
        "evidence_need": state.evidence_need,
        "normative_claim": state.normative_claim,
        "brand_or_domain": state.brand_or_domain,
        "target_locale": state.target_locale,
        "context_notes": state.context_notes,
        "evidence_status": (
            state.evidence_status.value if state.evidence_status is not None else None
        ),
        "tool_call_count": state.tool_call_count,
        "max_tool_calls": state.max_tool_calls,
        "available_actions": [action.value for action in state.available_actions],
        "tools_called": list(state.tools_called),
        "previous_tool_results": [
            {
                "sequence_number": call.sequence_number,
                "tool_name": call.tool_name,
                "result_status": call.result_status.value,
                "result_summary": call.result_summary,
            }
            for call in state.tool_calls
        ],
        "verified_evidence": [
            {
                "evidence_id": evidence.evidence_id,
                "provenance": evidence.provenance.value,
                "source_ref": evidence.source_ref,
                "claim_key": evidence.claim_key,
                "claim_value": evidence.claim_value,
                "supports_normative_claim": evidence.supports_normative_claim,
            }
            for evidence in state.verified_evidence
        ],
    }


class LLMEvidenceActionSelector:
    """Single action-selection call; all terminal permissions remain rule-guarded."""

    def __init__(
        self,
        client: StructuredLLM,
        *,
        prompt_version: str = ACTION_PROMPT_VERSION,
        prompt_registry: ReviewPromptRegistry | None = None,
    ) -> None:
        self.client = client
        self._prompt_version = prompt_version
        self.prompt_registry = prompt_registry or ReviewPromptRegistry()

    @property
    def model_version(self) -> str:
        return self.client.model_version

    @property
    def prompt_version(self) -> str:
        return self._prompt_version

    def select_action(self, state: TerminologyEvidenceState) -> EvidenceActionDecision:
        snapshot = action_input_state(state)
        rendered_prompt = self.prompt_registry.render(self.prompt_version, snapshot)
        try:
            raw = self.client.invoke_structured(
                prompt_version=self.prompt_version,
                payload=snapshot,
                output_schema=ActionLLMOutput,
                prompt=rendered_prompt,
            )
        except Exception as error:
            if isinstance(error, LLMProcessingError):
                raise
            raise LLMProcessingError(
                _provider_failure_code(error),
                f"NODE-03 action selection failed: {error}",
                node_name="NODE-03",
            ) from error
        parsed = parse_strict_output(raw, ActionLLMOutput, node_name="NODE-03")
        return EvidenceActionDecision(
            action=parsed.action,
            reason=parsed.reason,
            query=parsed.query,
            based_on_tool_call_count=state.tool_call_count,
            input_state=snapshot,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            prompt_path=rendered_prompt.prompt_path,
            prompt_hash=rendered_prompt.prompt_hash,
        )


class LLMEvidenceCandidateAssessor:
    def __init__(
        self,
        client: StructuredLLM,
        *,
        prompt_version: str = ASSESSMENT_PROMPT_VERSION,
        prompt_registry: ReviewPromptRegistry | None = None,
    ) -> None:
        self.client = client
        self.prompt_version = prompt_version
        self.prompt_registry = prompt_registry or ReviewPromptRegistry()

    def assess(
        self,
        *,
        state: TerminologyEvidenceState,
        candidates: list[EvidenceCandidate],
    ) -> EvidenceAssessment:
        payload = {
            "term_candidate": state.term_candidate,
            "evidence_need": state.evidence_need,
            "brand_or_domain": state.brand_or_domain,
            "target_locale": state.target_locale,
            "context_notes": state.context_notes,
            "source_text": state.source_text,
            "translation_text": state.translation_text,
            "candidates": [item.model_dump(mode="json") for item in candidates],
        }
        rendered_prompt = self.prompt_registry.render(self.prompt_version, payload)
        try:
            raw = self.client.invoke_structured(
                prompt_version=self.prompt_version,
                payload=payload,
                output_schema=AssessmentLLMOutput,
                prompt=rendered_prompt,
            )
        except Exception as error:
            if isinstance(error, LLMProcessingError):
                raise
            raise LLMProcessingError(
                _provider_failure_code(error),
                f"NODE-03 evidence assessment failed: {error}",
                node_name="NODE-03",
            ) from error
        parsed = parse_strict_output(raw, AssessmentLLMOutput, node_name="NODE-03")
        expected = {item.candidate_id for item in candidates}
        actual = {item.candidate_id for item in parsed.assessments}
        if actual != expected or len(parsed.assessments) != len(candidates):
            raise LLMProcessingError(
                "LLM_SCHEMA_MISMATCH",
                "NODE-03 assessment must cover each retrieved candidate exactly once",
                node_name="NODE-03",
            )
        return EvidenceAssessment(
            assessments=[
                EvidenceAssessmentItem.model_validate(item.model_dump())
                for item in parsed.assessments
            ],
            model_version=self.client.model_version,
            prompt_version=self.prompt_version,
            prompt_path=rendered_prompt.prompt_path,
            prompt_hash=rendered_prompt.prompt_hash,
        )


def _tool_for_action(action: EvidenceAction) -> tuple[str, str]:
    mapping = {
        EvidenceAction.SEARCH_GLOSSARY: ("search_glossary", "search_glossary"),
        EvidenceAction.SEARCH_OFFICIAL_DOCS: (
            "search_official_docs",
            "search_official_docs",
        ),
        EvidenceAction.SEARCH_MEMORY: ("search_case_memory", "search_case_memory"),
    }
    try:
        return mapping[action]
    except KeyError as error:
        raise PolicyConfigurationError(f"action is not a tool action: {action}") from error


def _hard_candidate_guard(candidate: EvidenceCandidate) -> bool:
    if candidate.provenance == EvidenceProvenance.CASE_MEMORY:
        return candidate.validation_status == "HUMAN_VALIDATED"
    return candidate.provenance in {
        EvidenceProvenance.GLOSSARY,
        EvidenceProvenance.OFFICIAL_DOCS,
    }


def _verified_from_result(
    *,
    state: TerminologyEvidenceState,
    result: EvidenceToolResult,
    assessment: EvidenceAssessment | None,
) -> list[VerifiedEvidence]:
    if result.status not in {ToolResultStatus.HIT, ToolResultStatus.CONFLICT} or assessment is None:
        return []
    by_id = {item.candidate_id: item for item in assessment.assessments}
    verified: list[VerifiedEvidence] = []
    for candidate in result.candidates:
        semantic = by_id[candidate.candidate_id]
        if not _hard_candidate_guard(candidate):
            continue
        if not semantic.relevant or not semantic.context_match:
            continue
        verified.append(
            VerifiedEvidence(
                case_id=state.case_id,
                term_candidate=state.term_candidate,
                provenance=candidate.provenance,
                source_ref=candidate.source_ref,
                content=candidate.content,
                claim_key=candidate.claim_key,
                claim_value=candidate.claim_value,
                relevance_reason=semantic.reason,
                context_match=True,
                is_official_source=candidate.is_official_source,
                supports_normative_claim=candidate.supports_normative_claim,
            )
        )
    return verified


def _admitted_from_result(
    *,
    state: TerminologyEvidenceState,
    result: EvidenceToolResult,
    assessment: EvidenceAssessment | None,
    policy: NormativeEvidenceAdmissionPolicy,
) -> tuple[list[VerifiedEvidence], list[NormativeAdmissionDecision]]:
    if result.status not in {ToolResultStatus.HIT, ToolResultStatus.CONFLICT} or assessment is None:
        return [], []
    by_id = {item.candidate_id: item for item in assessment.assessments}
    admitted: list[VerifiedEvidence] = []
    decisions: list[NormativeAdmissionDecision] = []
    for candidate in result.candidates:
        semantic = by_id[candidate.candidate_id]
        decision = policy.admit(
            state=state,
            candidate=candidate,
            assessment=semantic,
        )
        if (
            decision.candidate_id != candidate.candidate_id
            or decision.policy_version != policy.policy_version
        ):
            raise PolicyConfigurationError(
                "normative admission decision does not match its candidate or policy"
            )
        decisions.append(decision)
        if not decision.admitted:
            continue
        if decision.admitted_claim is None:
            raise PolicyConfigurationError(
                "admitted normative evidence requires scoped claim metadata"
            )
        admitted.append(
            VerifiedEvidence(
                case_id=state.case_id,
                term_candidate=state.term_candidate,
                provenance=candidate.provenance,
                source_ref=candidate.source_ref,
                content=candidate.content,
                claim_key=candidate.claim_key,
                claim_value=candidate.claim_value,
                relevance_reason=semantic.reason,
                context_match=True,
                is_official_source=candidate.is_official_source,
                # Retained only as the legacy/source declaration. Demo strict
                # sufficiency consumes admitted_normative_evidence below.
                supports_normative_claim=candidate.supports_normative_claim,
                declared_supports_normative_claim=(
                    candidate.supports_normative_claim
                ),
                admitted_normative_evidence=True,
                admission_policy_version=decision.policy_version,
                admitted_claim=decision.admitted_claim,
            )
        )
    return admitted, decisions


def _candidate_reviews(
    candidates: list[EvidenceCandidate],
    assessment: EvidenceAssessment | None,
    admission_decisions: list[NormativeAdmissionDecision],
) -> list[EvidenceCandidateReview]:
    assessments_by_id = (
        {item.candidate_id: item for item in assessment.assessments}
        if assessment is not None
        else {}
    )
    decisions_by_id = {item.candidate_id: item for item in admission_decisions}
    reviews: list[EvidenceCandidateReview] = []
    for candidate in candidates:
        semantic = assessments_by_id.get(candidate.candidate_id)
        admission = decisions_by_id.get(candidate.candidate_id)
        reviews.append(
            EvidenceCandidateReview(
                candidate_id=candidate.candidate_id,
                term_candidate=candidate.term_candidate,
                provenance=candidate.provenance,
                source_ref=candidate.source_ref,
                content=candidate.content,
                claim_key=candidate.claim_key,
                claim_value=candidate.claim_value,
                target_locale=candidate.target_locale,
                scenario=candidate.scenario,
                is_official_source=candidate.is_official_source,
                supports_normative_claim=candidate.supports_normative_claim,
                relevant=semantic.relevant if semantic is not None else None,
                context_match=semantic.context_match if semantic is not None else None,
                assessment_reason=semantic.reason if semantic is not None else None,
                admitted=admission.admitted if admission is not None else None,
                admission_reason_codes=(
                    list(admission.reason_codes) if admission is not None else []
                ),
                admission_policy_version=(
                    admission.policy_version if admission is not None else None
                ),
            )
        )
    return reviews


def _has_conflict(evidence: list[VerifiedEvidence]) -> bool:
    claims: dict[str, set[str]] = {}
    for item in evidence:
        claims.setdefault(item.claim_key.casefold(), set()).add(
            item.claim_value.strip().casefold()
        )
    return any(len(values) > 1 for values in claims.values())


def _is_sufficient(state: TerminologyEvidenceState) -> bool:
    if not state.verified_evidence or _has_conflict(state.verified_evidence):
        return False
    if state.normative_claim:
        return any(
            item.provenance != EvidenceProvenance.CASE_MEMORY
            and item.is_official_source
            and item.supports_normative_claim
            for item in state.verified_evidence
        )
    return True


def _is_strict_sufficient(
    state: TerminologyEvidenceState,
    policy: NormativeEvidenceAdmissionPolicy,
) -> bool:
    if not state.verified_evidence or _has_conflict(state.verified_evidence):
        return False
    return any(
        item.admitted_normative_evidence
        and item.admission_policy_version == policy.policy_version
        for item in state.verified_evidence
    )


class TerminologyEvidenceLoop:
    def __init__(
        self,
        *,
        selector: EvidenceActionSelector,
        assessor: EvidenceCandidateAssessor,
        tools: EvidenceTools,
        normative_admission_policy: NormativeEvidenceAdmissionPolicy | None = None,
    ) -> None:
        self.selector = selector
        self.assessor = assessor
        self.tools = tools
        self.normative_admission_policy = normative_admission_policy

    def _is_sufficient(self, state: TerminologyEvidenceState) -> bool:
        if self.normative_admission_policy is None:
            return _is_sufficient(state)
        return _is_strict_sufficient(state, self.normative_admission_policy)

    def run(self, initial_state: TerminologyEvidenceState) -> TerminologyEvidenceState:
        state = initial_state.model_copy(deep=True)
        if state.evidence_status is not None:
            raise PolicyConfigurationError("NODE-03 initial state must be unfinished")

        while state.evidence_status is None:
            if _has_conflict(state.verified_evidence):
                state.evidence_status = EvidenceStatus.CONFLICT
                state.stop_action = EvidenceAction.ABSTAIN
                state.stop_reason = "VERIFIED_EVIDENCE_CONFLICT"
                break

            decision = self.selector.select_action(state)
            if decision.based_on_tool_call_count != state.tool_call_count:
                raise PolicyConfigurationError(
                    "action decision does not reference the current tool_call_count"
                )
            state.action_history.append(decision)

            if decision.action == EvidenceAction.STOP_SUFFICIENT:
                if not self._is_sufficient(state):
                    state.evidence_status = EvidenceStatus.INSUFFICIENT
                    state.stop_action = EvidenceAction.ABSTAIN
                    state.stop_reason = "STOP_SUFFICIENT_REJECTED_BY_GUARDRAIL"
                else:
                    state.evidence_status = EvidenceStatus.SUFFICIENT
                    state.stop_action = EvidenceAction.STOP_SUFFICIENT
                    state.stop_reason = "EVIDENCE_SUFFICIENT"
                break
            if decision.action == EvidenceAction.ABSTAIN:
                state.evidence_status = (
                    EvidenceStatus.CONFLICT
                    if _has_conflict(state.verified_evidence)
                    else EvidenceStatus.INSUFFICIENT
                )
                state.stop_action = EvidenceAction.ABSTAIN
                state.stop_reason = decision.reason
                break

            if state.tool_call_count >= state.max_tool_calls:
                state.evidence_status = EvidenceStatus.INSUFFICIENT
                state.stop_action = EvidenceAction.ABSTAIN
                state.stop_reason = "TOOL_BUDGET_REACHED"
                break

            if decision.action not in state.available_actions:
                state.evidence_status = EvidenceStatus.INSUFFICIENT
                state.stop_action = EvidenceAction.ABSTAIN
                state.stop_reason = "FROZEN_EVIDENCE_TOOL_UNAVAILABLE"
                break

            tool_name, method_name = _tool_for_action(decision.action)
            tool = getattr(self.tools, method_name)
            try:
                if decision.action == EvidenceAction.SEARCH_OFFICIAL_DOCS:
                    result: EvidenceToolResult = tool(
                        decision.query or "",
                        term_candidate=state.term_candidate,
                    )
                else:
                    result = tool(decision.query or "")
            except Exception as error:
                result = EvidenceToolResult(
                    status=ToolResultStatus.ERROR,
                    summary=f"{tool_name} failed.",
                    error_message=str(error),
                )

            assessment = None
            if result.status in {ToolResultStatus.HIT, ToolResultStatus.CONFLICT}:
                try:
                    assessment = self.assessor.assess(
                        state=state, candidates=result.candidates
                    )
                except LLMProcessingError as error:
                    state.tool_call_count += 1
                    state.tools_called.append(tool_name)
                    state.tool_calls.append(
                        ToolCallRecord(
                            case_id=state.case_id,
                            sequence_number=state.tool_call_count,
                            action_decision_id=decision.action_decision_id,
                            action=decision.action,
                            tool_name=tool_name,
                            query=decision.query or "",
                            result_status=result.status,
                            result_summary=result.summary,
                            decision_reason=decision.reason,
                            input_state=decision.input_state,
                            candidate_reviews=_candidate_reviews(
                                result.candidates, None, []
                            ),
                        )
                    )
                    state.evidence_status = EvidenceStatus.INSUFFICIENT
                    state.stop_action = EvidenceAction.ABSTAIN
                    state.stop_reason = f"EVIDENCE_ASSESSMENT_ERROR:{error.code}"
                    break
                state.assessments.append(assessment)
            if self.normative_admission_policy is None:
                verified = _verified_from_result(
                    state=state, result=result, assessment=assessment
                )
                admission_decisions: list[NormativeAdmissionDecision] = []
            else:
                verified, admission_decisions = _admitted_from_result(
                    state=state,
                    result=result,
                    assessment=assessment,
                    policy=self.normative_admission_policy,
                )
            state.verified_evidence.extend(verified)
            state.normative_admission_decisions.extend(admission_decisions)
            state.tool_call_count += 1
            state.tools_called.append(tool_name)
            state.tool_calls.append(
                ToolCallRecord(
                    case_id=state.case_id,
                    sequence_number=state.tool_call_count,
                    action_decision_id=decision.action_decision_id,
                    action=decision.action,
                    tool_name=tool_name,
                    query=decision.query or "",
                    result_status=result.status,
                    result_summary=result.summary,
                    decision_reason=decision.reason,
                    input_state=decision.input_state,
                    candidate_reviews=_candidate_reviews(
                        result.candidates, assessment, admission_decisions
                    ),
                )
            )

            if _has_conflict(state.verified_evidence):
                state.evidence_status = EvidenceStatus.CONFLICT
                state.stop_action = EvidenceAction.ABSTAIN
                state.stop_reason = "VERIFIED_EVIDENCE_CONFLICT"
                break
            if self._is_sufficient(state):
                state.evidence_status = EvidenceStatus.SUFFICIENT
                state.stop_action = EvidenceAction.STOP_SUFFICIENT
                state.stop_reason = "EVIDENCE_SUFFICIENT"
                break

        return TerminologyEvidenceState.model_validate(state.model_dump())
