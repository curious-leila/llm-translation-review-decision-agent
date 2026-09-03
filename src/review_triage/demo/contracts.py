"""Frontend contracts: reshape existing workflow facts without new policy."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from review_triage.schemas import (
    Dimension,
    FinalPolicyRoute,
    ProcessingStatus,
    RiskLevel,
    StrictModel,
    VerificationRoute,
    WorkflowState,
)


ROUTE_LABELS_ZH: dict[FinalPolicyRoute, str] = {
    FinalPolicyRoute.AUTO_PASS: "自动放行",
    FinalPolicyRoute.SAMPLE_POOL: "进入抽检",
    FinalPolicyRoute.HUMAN_REQUIRED: "必须人工复核",
}
RISK_LABELS_ZH: dict[RiskLevel, str] = {
    RiskLevel.HIGH: "高风险",
    RiskLevel.MEDIUM: "中风险",
    RiskLevel.LOW: "低风险",
    RiskLevel.INSUFFICIENT_CONTEXT: "上下文不足",
}
VERIFICATION_LABELS_ZH: dict[VerificationRoute, str] = {
    VerificationRoute.AUTO_TRUST: "自动信任",
    VerificationRoute.SAMPLE_AUDIT: "抽检审计",
    VerificationRoute.HUMAN_VERIFY: "人工验证",
}


class ReviewCaseDTO(StrictModel):
    source_text: str
    translation: str
    content_type: str
    brand_or_domain: str | None
    context_notes: str | None


class ReviewRiskDTO(StrictModel):
    level: RiskLevel
    label_zh: str
    reason: str
    clarification_question: str | None


class ReviewRouteDTO(StrictModel):
    code: FinalPolicyRoute
    label_zh: str
    triggering_dimensions: list[Dimension]
    blocking_dimensions: list[Dimension]
    sample_audit_dimensions: list[Dimension]


class ReviewDimensionDTO(StrictModel):
    dimension: Dimension
    severity: str
    q1: str
    q2: str
    notes: str
    requires_external_evidence: bool
    unresolved_external_support: bool
    details: dict[str, Any]


class ReviewReliabilityDTO(StrictModel):
    dimension: Dimension
    verification_route: VerificationRoute
    label_zh: str
    policy_reason: str
    override_reason: str | None
    policy_cell: str


class ReviewEvidenceDTO(StrictModel):
    provenance: str
    source_ref: str
    content: str
    relevance_reason: str
    context_match: bool
    supports_normative_claim: bool


class ReviewEvidenceActionDTO(StrictModel):
    action: str
    reason: str
    query: str | None


class ReviewToolCallDTO(StrictModel):
    action: str
    tool_name: str
    query: str
    result_status: str
    result_summary: str
    decision_reason: str
    candidate_reviews: list["ReviewEvidenceCandidateDTO"] = Field(default_factory=list)


class ReviewEvidenceCandidateDTO(StrictModel):
    candidate_id: str
    term_candidate: str
    provenance: str
    source_ref: str
    content: str
    claim_key: str
    claim_value: str
    target_locale: str
    scenario: str | None
    is_official_source: bool
    supports_normative_claim: bool
    relevant: bool | None
    context_match: bool | None
    assessment_reason: str | None
    admitted: bool | None
    admission_reason_codes: list[str]
    admission_policy_version: str | None


class ReviewEvidenceDTOGroup(StrictModel):
    status: str | None
    stop_reason: str | None
    verified_evidence: list[ReviewEvidenceDTO]
    actions: list[ReviewEvidenceActionDTO]
    tool_calls: list[ReviewToolCallDTO]


class ReviewPostEvalDTO(StrictModel):
    terminology_requires_external_evidence: bool
    terminology_reason: str
    unresolved_support: dict[str, bool]


class ReviewProcessingErrorDTO(StrictModel):
    code: str
    node_name: str
    message: str
    safe_disposition: str


class ReviewResultDTO(StrictModel):
    case_id: str | None
    processing_status: ProcessingStatus
    case: ReviewCaseDTO | None
    risk: ReviewRiskDTO | None
    final_route: ReviewRouteDTO | None
    route_reason_codes: list[str]
    dimensions: list[ReviewDimensionDTO]
    reliability_decisions: list[ReviewReliabilityDTO]
    post_eval_control: ReviewPostEvalDTO | None
    evidence: ReviewEvidenceDTOGroup | None
    processing_error: ReviewProcessingErrorDTO | None


def to_review_result(state: WorkflowState) -> ReviewResultDTO:
    """Serialize backend facts only; routes and policy remain backend-owned."""

    review_case = state.review_case
    case_id = review_case.case_id if review_case else (
        state.processing_error.case_id if state.processing_error else None
    )
    processing_status = (
        review_case.processing_status if review_case else
        ProcessingStatus.PROCESSING_ERROR if state.processing_error else ProcessingStatus.RECEIVED
    )
    evidence_state = state.terminology_evidence
    control = state.post_eval_control
    return ReviewResultDTO(
        case_id=case_id,
        processing_status=processing_status,
        case=(ReviewCaseDTO(
            source_text=review_case.source_text, translation=review_case.translation,
            content_type=review_case.content_type.value,
            brand_or_domain=review_case.brand_or_domain, context_notes=review_case.context_notes,
        ) if review_case else None),
        risk=(ReviewRiskDTO(
            level=state.risk_result.risk_level,
            label_zh=RISK_LABELS_ZH[state.risk_result.risk_level],
            reason=state.risk_result.reason,
            clarification_question=state.risk_result.clarification_question,
        ) if state.risk_result else None),
        final_route=(ReviewRouteDTO(
            code=state.route_decision.final_policy_route,
            label_zh=ROUTE_LABELS_ZH[state.route_decision.final_policy_route],
            triggering_dimensions=list(state.route_decision.triggering_dimensions),
            blocking_dimensions=list(state.route_decision.blocking_dimensions),
            sample_audit_dimensions=list(state.route_decision.sample_audit_dimensions),
        ) if state.route_decision else None),
        route_reason_codes=(list(state.route_decision.route_reason_codes) if state.route_decision else []),
        dimensions=[ReviewDimensionDTO(
            dimension=item.dimension, severity=item.severity.value, q1=item.q1, q2=item.q2,
            notes=item.notes, requires_external_evidence=item.requires_external_evidence,
            unresolved_external_support=item.unresolved_external_support,
            details=item.dimension_specific.model_dump(mode="json"),
        ) for item in state.dimension_evaluations],
        reliability_decisions=[ReviewReliabilityDTO(
            dimension=item.dimension, verification_route=item.verification_route,
            label_zh=VERIFICATION_LABELS_ZH[item.verification_route],
            policy_reason=item.policy_reason, override_reason=item.override_reason,
            policy_cell=item.policy_cell,
        ) for item in state.reliability_decisions],
        post_eval_control=(ReviewPostEvalDTO(
            terminology_requires_external_evidence=control.terminology.requires_external_evidence,
            terminology_reason=control.terminology.reason,
            unresolved_support={
                "ACCURACY": control.accuracy.unresolved_external_support,
                "LOCALE": control.locale.unresolved_external_support,
                "AUDIENCE": control.audience.unresolved_external_support,
            },
        ) if control else None),
        evidence=(ReviewEvidenceDTOGroup(
            status=evidence_state.evidence_status.value if evidence_state.evidence_status else None,
            stop_reason=evidence_state.stop_reason,
            verified_evidence=[ReviewEvidenceDTO(
                provenance=item.provenance.value, source_ref=item.source_ref, content=item.content,
                relevance_reason=item.relevance_reason, context_match=item.context_match,
                supports_normative_claim=item.supports_normative_claim,
            ) for item in evidence_state.verified_evidence],
            actions=[ReviewEvidenceActionDTO(action=item.action.value, reason=item.reason, query=item.query)
                     for item in evidence_state.action_history],
            tool_calls=[ReviewToolCallDTO(
                action=item.action.value, tool_name=item.tool_name, query=item.query,
                result_status=item.result_status.value, result_summary=item.result_summary,
                decision_reason=item.decision_reason,
                candidate_reviews=[ReviewEvidenceCandidateDTO(
                    candidate_id=candidate.candidate_id,
                    term_candidate=candidate.term_candidate,
                    provenance=candidate.provenance.value,
                    source_ref=candidate.source_ref,
                    content=candidate.content,
                    claim_key=candidate.claim_key,
                    claim_value=candidate.claim_value,
                    target_locale=candidate.target_locale,
                    scenario=candidate.scenario,
                    is_official_source=candidate.is_official_source,
                    supports_normative_claim=candidate.supports_normative_claim,
                    relevant=candidate.relevant,
                    context_match=candidate.context_match,
                    assessment_reason=candidate.assessment_reason,
                    admitted=candidate.admitted,
                    admission_reason_codes=[code.value for code in candidate.admission_reason_codes],
                    admission_policy_version=candidate.admission_policy_version,
                ) for candidate in item.candidate_reviews],
            ) for item in evidence_state.tool_calls],
        ) if evidence_state else None),
        processing_error=(ReviewProcessingErrorDTO(
            code=state.processing_error.error_code, node_name=state.processing_error.node_name,
            message=state.processing_error.error_message,
            safe_disposition=state.processing_error.safe_disposition,
        ) if state.processing_error else None),
    )
