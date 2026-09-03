"""NODE-07 minimal structured Human Review interface."""

from __future__ import annotations

from collections.abc import Sequence

from review_triage.errors import PolicyConfigurationError
from review_triage.persistence import SQLiteRepository
from review_triage.schemas import (
    Dimension,
    DimensionEvaluation,
    FinalPolicyRoute,
    HumanReviewResult,
    HumanReviewSubmission,
    HumanReviewView,
    ReviewCase,
    ReviewMode,
    RouteDecision,
    SamplingDecision,
    TerminologyEvidenceState,
)


def _eligible_for_human_review(
    *, route: RouteDecision, sampling: SamplingDecision | None
) -> bool:
    if route.final_policy_route == FinalPolicyRoute.HUMAN_REQUIRED:
        return True
    if route.final_policy_route == FinalPolicyRoute.SAMPLE_POOL:
        return bool(sampling and sampling.selected_for_audit)
    return False


def build_human_review_view(
    *,
    review_case: ReviewCase,
    review_mode: ReviewMode,
    evaluations: Sequence[DimensionEvaluation],
    route: RouteDecision,
    terminology_evidence: TerminologyEvidenceState | None = None,
) -> HumanReviewView:
    case_payload = {
        "source_text": review_case.source_text,
        "translation_text": review_case.translation,
        "content_type": review_case.content_type.value,
        "brand_or_domain": review_case.brand_or_domain,
        "context_notes": review_case.context_notes,
        "source_language": review_case.source_language,
        "target_locale": review_case.target_locale,
    }
    if review_mode == ReviewMode.EVAL_BLIND:
        return HumanReviewView(
            case_id=review_case.case_id,
            review_mode=review_mode,
            case_payload=case_payload,
        )
    return HumanReviewView(
        case_id=review_case.case_id,
        review_mode=review_mode,
        case_payload=case_payload,
        ai_findings=[item.model_dump(mode="json") for item in evaluations],
        verified_evidence=(
            [
                item.model_dump(mode="json")
                for item in terminology_evidence.verified_evidence
            ]
            if terminology_evidence
            else []
        ),
        route_reason=route.model_dump(mode="json"),
    )


def node_07_submit_human_review(
    *,
    eval_run_id: str,
    review_case: ReviewCase,
    evaluations: Sequence[DimensionEvaluation],
    route: RouteDecision,
    submission: HumanReviewSubmission,
    repository: SQLiteRepository,
    sampling: SamplingDecision | None = None,
    terminology_evidence: TerminologyEvidenceState | None = None,
) -> HumanReviewResult:
    if route.case_id != review_case.case_id:
        raise PolicyConfigurationError("NODE-07 route/case identity mismatch")
    if sampling is not None and sampling.case_id != review_case.case_id:
        raise PolicyConfigurationError("NODE-07 sampling/case identity mismatch")
    if not _eligible_for_human_review(route=route, sampling=sampling):
        raise PolicyConfigurationError(
            "NODE-07 entry requires HUMAN_REQUIRED or selected SAMPLE_POOL"
        )
    by_dimension = {item.dimension: item for item in evaluations}
    if set(by_dimension) != set(Dimension) or len(evaluations) != 4:
        raise PolicyConfigurationError(
            "NODE-07 requires exactly one AI evaluation for each dimension"
        )
    human_severities = {
        Dimension.TERMINOLOGY: submission.human_terminology_severity,
        Dimension.ACCURACY: submission.human_accuracy_severity,
        Dimension.LOCALE: submission.human_locale_severity,
        Dimension.AUDIENCE: submission.human_audience_severity,
    }
    disagreements = [
        dimension
        for dimension in Dimension
        if by_dimension[dimension].severity != human_severities[dimension]
    ]
    if disagreements and not submission.human_notes.strip():
        raise PolicyConfigurationError(
            "NODE-07 human_notes is required for Human/AI severity disagreement"
        )

    result = HumanReviewResult(
        case_id=review_case.case_id,
        **submission.model_dump(),
    )
    repository.save_human_feedback(
        result=result,
        evaluations=evaluations,
        route=route,
        sampling=sampling,
        terminology_evidence=terminology_evidence,
    )
    repository.log_node(
        eval_run_id=eval_run_id,
        case_id=review_case.case_id,
        node_name="NODE-07",
        input_state={
            "entry_route": route,
            "sampling": sampling,
            "review_mode": submission.review_mode,
        },
        output_state=result,
        decision_reason="Human adjudication submitted under NODE-07 entry and schema rules",
        reason_code=result.human_final_disposition.value,
        policy_version="human_review_v1",
        evidence_status=(
            terminology_evidence.evidence_status.value
            if terminology_evidence and terminology_evidence.evidence_status
            else None
        ),
    )
    return result
