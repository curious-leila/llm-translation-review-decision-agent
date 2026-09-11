"""Frontend contracts: reshape existing workflow facts without new policy."""

from __future__ import annotations

import re
from typing import Any, Literal

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


class ReviewTrajectoryToolCallDTO(StrictModel):
    sequence: int
    action: str
    tool_name: str
    tool_label_zh: str
    query: str
    result_status: str
    result_label_zh: str
    result_summary: str
    candidate_count: int | None
    admitted_count: int


class ReviewTrajectoryEvidenceDTO(StrictModel):
    required: bool
    need_reason: str
    status: str
    status_label_zh: str
    tool_calls: list[ReviewTrajectoryToolCallDTO]
    verified_evidence: list[ReviewEvidenceDTO]


class ReviewTrajectoryStepDTO(StrictModel):
    step_id: str
    kind: str
    status: str
    title_zh: str
    summary_zh: str
    fact_refs: list[str]


class ReviewAgentTrajectoryDTO(StrictModel):
    schema_version: Literal["review-agent-trajectory/v1"] = (
        "review-agent-trajectory/v1"
    )
    case_id: str | None
    processing_status: ProcessingStatus
    case: ReviewCaseDTO | None
    risk: ReviewRiskDTO | None
    dimensions: list[ReviewDimensionDTO]
    evidence: ReviewTrajectoryEvidenceDTO
    reliability_decisions: list[ReviewReliabilityDTO]
    final_route: ReviewRouteDTO | None
    route_reason_codes: list[str]
    steps: list[ReviewTrajectoryStepDTO]


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
    trajectory: ReviewAgentTrajectoryDTO | None = None


TOOL_LABELS_ZH = {
    "official_docs": "官方资料检索",
    "search_official_docs": "官方资料检索",
    "glossary": "术语表检索",
    "search_glossary": "术语表检索",
    "case_memory": "历史案例检索",
    "search_case_memory": "历史案例检索",
}
TRAJECTORY_ROUTE_LABELS_ZH = {
    FinalPolicyRoute.AUTO_PASS: "自动通过",
    FinalPolicyRoute.SAMPLE_POOL: "抽样复核",
    FinalPolicyRoute.HUMAN_REQUIRED: "人工复核",
}


def _candidate_count(tool_call: ReviewToolCallDTO) -> int | None:
    if tool_call.candidate_reviews:
        return len(tool_call.candidate_reviews)
    match = re.search(r"(\d+)\s+candidate", tool_call.result_summary, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _quality_summary(dimensions: list[ReviewDimensionDTO]) -> str:
    if not dimensions:
        return "本轮没有可展示的四维审校结果。"
    issue_dimensions = [
        item.dimension.value for item in dimensions if item.severity != "Neutral"
    ]
    if not issue_dimensions:
        return "已完成术语、准确性、本地化与受众四维审校，四项均无阻断问题。"
    return "已完成四维审校；需要关注：" + "、".join(issue_dimensions) + "。"


def _reliability_summary(items: list[ReviewReliabilityDTO]) -> str:
    counts = {
        route: sum(item.verification_route == route for item in items)
        for route in VerificationRoute
    }
    parts = [
        f"自动信任 {counts[VerificationRoute.AUTO_TRUST]} 项",
        f"抽样复核 {counts[VerificationRoute.SAMPLE_AUDIT]} 项",
        f"人工确认 {counts[VerificationRoute.HUMAN_VERIFY]} 项",
    ]
    return " · ".join(parts) + "。"


def _route_summary(route: ReviewRouteDTO) -> str:
    label = TRAJECTORY_ROUTE_LABELS_ZH[route.code]
    dimensions = route.triggering_dimensions
    if route.code == FinalPolicyRoute.AUTO_PASS:
        return "四个维度均满足非阻断与自动信任条件，本案例自动通过。"
    if dimensions:
        return "、".join(item.value for item in dimensions) + f"触发最严格路径，本案例进入{label}。"
    return f"后端既定路由规则将本案例送入{label}。"


def _evidence_need_reason_zh(reason: str) -> str:
    """Keep the zh display contract readable without translating in the browser."""

    if re.search(r"[\u3400-\u9fff]", reason):
        return reason
    return (
        "术语判断（Terminology）依赖尚未核实的外部命名或规范性事实；"
        "当前材料没有可验证该断言的权威依据，因此需要外部证据。"
    )


def build_review_agent_trajectory(
    result: ReviewResultDTO,
) -> ReviewAgentTrajectoryDTO:
    """Build the versioned display trajectory from existing backend facts only."""

    control = result.post_eval_control
    required = control.terminology_requires_external_evidence if control else False
    evidence_group = result.evidence
    evidence_status = (
        evidence_group.status
        if evidence_group and evidence_group.status
        else "NOT_REQUIRED" if control and not required else "UNAVAILABLE"
    )
    evidence_need_reason = (
        _evidence_need_reason_zh(control.terminology_reason) if control else ""
    )
    status_labels = {
        "SUFFICIENT": "证据充分",
        "INSUFFICIENT": "证据不足 · 安全弃权",
        "NOT_REQUIRED": "无需外部查证",
        "UNAVAILABLE": "暂无证据状态",
    }
    trajectory_calls: list[ReviewTrajectoryToolCallDTO] = []
    for sequence, call in enumerate(
        evidence_group.tool_calls if evidence_group else [], start=1
    ):
        trajectory_calls.append(
            ReviewTrajectoryToolCallDTO(
                sequence=sequence,
                action=call.action,
                tool_name=call.tool_name,
                tool_label_zh=TOOL_LABELS_ZH.get(call.tool_name, "受控证据检索"),
                query=call.query,
                result_status=call.result_status,
                result_label_zh="命中候选" if call.result_status == "HIT" else "未命中",
                result_summary=call.result_summary,
                candidate_count=_candidate_count(call),
                admitted_count=sum(
                    candidate.admitted is True for candidate in call.candidate_reviews
                ),
            )
        )

    steps: list[ReviewTrajectoryStepDTO] = []
    if result.risk or result.dimensions:
        risk_copy = result.risk.label_zh if result.risk else "风险待确认"
        steps.append(
            ReviewTrajectoryStepDTO(
                step_id="risk-and-quality",
                kind="ASSESSMENT",
                status="COMPLETE",
                title_zh="风险扫描与四维审校",
                summary_zh=f"识别为{risk_copy}。{_quality_summary(result.dimensions)}",
                fact_refs=["risk", "dimensions"],
            )
        )
    if control:
        steps.append(
            ReviewTrajectoryStepDTO(
                step_id="evidence-gate",
                kind="EVIDENCE_GATE",
                status="COMPLETE" if required else "SKIPPED",
                title_zh="需要外部证据" if required else "无需外部查证",
                summary_zh=(
                    evidence_need_reason
                    if required
                    else "当前术语判断不依赖未解决的外部事实，跳过证据检索。"
                ),
                fact_refs=["post_eval_control.terminology"],
            )
        )
    for call in trajectory_calls:
        count_copy = (
            f"，返回 {call.candidate_count} 条候选"
            if call.candidate_count is not None
            else ""
        )
        steps.append(
            ReviewTrajectoryStepDTO(
                step_id=f"tool-call-{call.sequence}",
                kind="TOOL_CALL",
                status=call.result_status,
                title_zh=f"{call.tool_label_zh} · {call.result_label_zh}",
                summary_zh=f"查询“{call.query}”{count_copy}。",
                fact_refs=[f"evidence.tool_calls[{call.sequence - 1}]"],
            )
        )
    if required:
        verified_count = len(evidence_group.verified_evidence) if evidence_group else 0
        sufficient = evidence_status == "SUFFICIENT"
        steps.append(
            ReviewTrajectoryStepDTO(
                step_id="evidence-outcome",
                kind="EVIDENCE_OUTCOME",
                status="COMPLETE" if sufficient else "SAFE_ABSTAIN",
                title_zh="证据充分" if sufficient else "证据不足 · 安全弃权",
                summary_zh=(
                    f"接纳 {verified_count} 条可信证据，进入最终术语判断。"
                    if sufficient
                    else "未获得可接纳的充分证据，停止自主判断，不自动放行。"
                ),
                fact_refs=["evidence.verified_evidence", "evidence.status"],
            )
        )
    if result.reliability_decisions:
        steps.append(
            ReviewTrajectoryStepDTO(
                step_id="reliability",
                kind="RELIABILITY",
                status="COMPLETE",
                title_zh="应用可靠性授权",
                summary_zh=_reliability_summary(result.reliability_decisions),
                fact_refs=["reliability_decisions"],
            )
        )
    if result.final_route:
        route_title = TRAJECTORY_ROUTE_LABELS_ZH[result.final_route.code]
        route_summary = _route_summary(result.final_route)
        if (
            evidence_status == "INSUFFICIENT"
            and result.final_route.code == FinalPolicyRoute.HUMAN_REQUIRED
        ):
            route_summary = "证据不足 · 安全弃权 → 人工复核。"
        steps.append(
            ReviewTrajectoryStepDTO(
                step_id="final-route",
                kind="FINAL_ROUTE",
                status="COMPLETE",
                title_zh=route_title,
                summary_zh=route_summary,
                fact_refs=["final_route", "route_reason_codes"],
            )
        )

    return ReviewAgentTrajectoryDTO(
        case_id=result.case_id,
        processing_status=result.processing_status,
        case=result.case,
        risk=result.risk,
        dimensions=result.dimensions,
        evidence=ReviewTrajectoryEvidenceDTO(
            required=required,
            need_reason=evidence_need_reason,
            status=evidence_status,
            status_label_zh=status_labels[evidence_status],
            tool_calls=trajectory_calls,
            verified_evidence=(
                evidence_group.verified_evidence if evidence_group else []
            ),
        ),
        reliability_decisions=result.reliability_decisions,
        final_route=result.final_route,
        route_reason_codes=result.route_reason_codes,
        steps=steps,
    )


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
    result = ReviewResultDTO(
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
    return result.model_copy(update={"trajectory": build_review_agent_trajectory(result)})
