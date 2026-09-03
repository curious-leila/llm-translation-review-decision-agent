"""MVP V1 NODE-00 through NODE-05 implementations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from review_triage.errors import InvalidInputError, PolicyConfigurationError
from review_triage.policy import RELIABILITY_POLICY_EN_ZH_V1
from review_triage.schemas import (
    Dimension,
    DimensionEvaluation,
    EvidenceStatus,
    FinalPolicyRoute,
    ProcessingStatus,
    RELIABILITY_POLICY_ID,
    ReliabilityDecision,
    ReviewCase,
    ReviewCaseInput,
    RiskLevel,
    RouteDecision,
    TerminologyEvidenceState,
    VerificationRoute,
)


def node_00_normalize(raw_input: ReviewCaseInput | Mapping[str, Any]) -> ReviewCase:
    """Validate fields and combine user, fixed, and generated case metadata."""

    try:
        payload = (
            raw_input
            if isinstance(raw_input, ReviewCaseInput)
            else ReviewCaseInput.model_validate(raw_input)
        )
    except ValidationError as error:
        raise InvalidInputError(f"INVALID_INPUT: {error}") from error

    values = payload.model_dump()
    values["processing_status"] = (
        ProcessingStatus.OUT_OF_SCOPE
        if payload.content_type.value == "OTHER"
        else ProcessingStatus.VALID
    )
    return ReviewCase.model_validate(values)


def node_04_reliability(
    *,
    case_id: str,
    case_risk: RiskLevel,
    evaluations: Sequence[DimensionEvaluation],
    reliability_policy_id: str,
    terminology_evidence: TerminologyEvidenceState | None = None,
) -> list[ReliabilityDecision]:
    """Perform the 12-cell lookup, then apply only frozen safety overrides."""

    if reliability_policy_id != RELIABILITY_POLICY_ID:
        raise PolicyConfigurationError(
            f"unsupported reliability policy: {reliability_policy_id}"
        )
    if case_risk == RiskLevel.INSUFFICIENT_CONTEXT:
        raise PolicyConfigurationError(
            "INSUFFICIENT_CONTEXT must route to NEEDS_CONTEXT before NODE-04"
        )

    by_dimension = {item.dimension: item for item in evaluations}
    if set(by_dimension) != set(Dimension) or len(evaluations) != len(Dimension):
        raise PolicyConfigurationError(
            "NODE-04 requires exactly one evaluation for each of the four dimensions"
        )
    if (
        by_dimension[Dimension.TERMINOLOGY].requires_external_evidence
        and terminology_evidence is None
    ):
        raise PolicyConfigurationError(
            "NODE-03 evidence state is required when Terminology requests external evidence"
        )

    decisions: list[ReliabilityDecision] = []
    for dimension in Dimension:
        evaluation = by_dimension[dimension]
        cell = RELIABILITY_POLICY_EN_ZH_V1[(dimension, case_risk)]
        route = cell.verification_route
        override_reason: str | None = None

        if dimension == Dimension.TERMINOLOGY and terminology_evidence is not None:
            if terminology_evidence.evidence_status in {
                EvidenceStatus.INSUFFICIENT,
                EvidenceStatus.CONFLICT,
            }:
                route = VerificationRoute.HUMAN_VERIFY
                override_reason = (
                    f"TERMINOLOGY_EVIDENCE_{terminology_evidence.evidence_status.value}"
                )
        elif (
            dimension in {Dimension.ACCURACY, Dimension.LOCALE, Dimension.AUDIENCE}
            and evaluation.unresolved_external_support
        ):
            route = VerificationRoute.HUMAN_VERIFY
            override_reason = f"{dimension.value}_UNRESOLVED_EXTERNAL_SUPPORT"

        decisions.append(
            ReliabilityDecision(
                case_id=case_id,
                dimension=dimension,
                case_risk=case_risk,
                policy_cell=cell.policy_cell,
                observed_agreement=cell.observed_agreement,
                sample_count=cell.sample_count,
                source_case_count=cell.source_case_count,
                severity_support=cell.severity_coverage,
                verification_route=route,
                policy_reason=(
                    "Frozen MVP V1 pilot-calibrated dimension×case-risk lookup; "
                    "observed agreement is audit metadata, not production reliability."
                ),
                policy_source=cell.policy_source,
                override_reason=override_reason,
            )
        )
    return decisions


def node_05_aggregate(
    *,
    case_id: str,
    evaluations: Sequence[DimensionEvaluation],
    reliability_decisions: Sequence[ReliabilityDecision],
) -> RouteDecision:
    """Maximum intervention wins; no averaging, voting, or risk double count."""

    evaluation_by_dimension = {item.dimension: item for item in evaluations}
    reliability_by_dimension = {
        item.dimension: item for item in reliability_decisions
    }
    if set(evaluation_by_dimension) != set(Dimension) or set(
        reliability_by_dimension
    ) != set(Dimension) or len(evaluations) != 4 or len(reliability_decisions) != 4:
        raise PolicyConfigurationError(
            "NODE-05 requires one evaluation and one reliability decision per dimension"
        )

    human_verify_dimensions: list[Dimension] = []
    blocking_dimensions: list[Dimension] = []
    sample_dimensions: list[Dimension] = []
    reason_codes: list[str] = []

    for dimension in Dimension:
        evaluation = evaluation_by_dimension[dimension]
        reliability = reliability_by_dimension[dimension]
        if reliability.verification_route == VerificationRoute.HUMAN_VERIFY:
            human_verify_dimensions.append(dimension)
            reason_codes.append(f"{dimension.value}_HUMAN_VERIFY")
        if evaluation.severity.value in {"Major", "Critical"}:
            blocking_dimensions.append(dimension)
            reason_codes.append(f"{dimension.value}_BLOCKING_SEVERITY")
        if reliability.verification_route == VerificationRoute.SAMPLE_AUDIT:
            sample_dimensions.append(dimension)
            reason_codes.append(f"{dimension.value}_SAMPLE_AUDIT")

    if human_verify_dimensions or blocking_dimensions:
        final_route = FinalPolicyRoute.HUMAN_REQUIRED
        triggering = list(dict.fromkeys(human_verify_dimensions + blocking_dimensions))
    elif sample_dimensions:
        final_route = FinalPolicyRoute.SAMPLE_POOL
        triggering = sample_dimensions
    else:
        final_route = FinalPolicyRoute.AUTO_PASS
        triggering = []
        reason_codes.append("ALL_DIMENSIONS_NON_BLOCKING_AUTO_TRUST")

    return RouteDecision(
        case_id=case_id,
        final_policy_route=final_route,
        triggering_dimensions=triggering,
        blocking_dimensions=blocking_dimensions,
        sample_audit_dimensions=sample_dimensions,
        route_reason_codes=reason_codes,
    )
