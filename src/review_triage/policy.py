"""Frozen MVP V1 pilot-calibrated reliability policy.

The observed agreement values are audit metadata from pilot_180. They are not
production-grade reliability estimates and do not directly imply case passage.
"""

from __future__ import annotations

from dataclasses import dataclass

from review_triage.errors import PolicyConfigurationError
from review_triage.schemas import (
    Dimension,
    RELIABILITY_POLICY_ID,
    RiskLevel,
    SeverityCoverage,
    VerificationRoute,
)


@dataclass(frozen=True, slots=True)
class PolicyCell:
    dimension: Dimension
    case_risk: RiskLevel
    verification_route: VerificationRoute
    observed_agreement: float
    sample_count: int
    source_case_count: int
    severity_coverage: SeverityCoverage
    policy_source: str = "pilot_180"

    @property
    def policy_cell(self) -> str:
        return f"{self.dimension.value}×{self.case_risk.value}"


_N = SeverityCoverage.NEUTRAL_ONLY
_M = SeverityCoverage.NON_NEUTRAL_PRESENT

RELIABILITY_POLICY_EN_ZH_V1: dict[tuple[Dimension, RiskLevel], PolicyCell] = {
    (Dimension.TERMINOLOGY, RiskLevel.HIGH): PolicyCell(
        Dimension.TERMINOLOGY, RiskLevel.HIGH, VerificationRoute.HUMAN_VERIFY,
        0.611, 18, 6, _M,
    ),
    (Dimension.TERMINOLOGY, RiskLevel.MEDIUM): PolicyCell(
        Dimension.TERMINOLOGY, RiskLevel.MEDIUM, VerificationRoute.AUTO_TRUST,
        1.000, 18, 6, _M,
    ),
    (Dimension.TERMINOLOGY, RiskLevel.LOW): PolicyCell(
        Dimension.TERMINOLOGY, RiskLevel.LOW, VerificationRoute.AUTO_TRUST,
        1.000, 9, 3, _N,
    ),
    (Dimension.ACCURACY, RiskLevel.HIGH): PolicyCell(
        Dimension.ACCURACY, RiskLevel.HIGH, VerificationRoute.SAMPLE_AUDIT,
        0.944, 18, 6, _M,
    ),
    (Dimension.ACCURACY, RiskLevel.MEDIUM): PolicyCell(
        Dimension.ACCURACY, RiskLevel.MEDIUM, VerificationRoute.AUTO_TRUST,
        1.000, 18, 6, _N,
    ),
    (Dimension.ACCURACY, RiskLevel.LOW): PolicyCell(
        Dimension.ACCURACY, RiskLevel.LOW, VerificationRoute.AUTO_TRUST,
        1.000, 9, 3, _N,
    ),
    (Dimension.LOCALE, RiskLevel.HIGH): PolicyCell(
        Dimension.LOCALE, RiskLevel.HIGH, VerificationRoute.AUTO_TRUST,
        1.000, 18, 6, _M,
    ),
    (Dimension.LOCALE, RiskLevel.MEDIUM): PolicyCell(
        Dimension.LOCALE, RiskLevel.MEDIUM, VerificationRoute.SAMPLE_AUDIT,
        0.944, 18, 6, _M,
    ),
    (Dimension.LOCALE, RiskLevel.LOW): PolicyCell(
        Dimension.LOCALE, RiskLevel.LOW, VerificationRoute.AUTO_TRUST,
        1.000, 9, 3, _M,
    ),
    (Dimension.AUDIENCE, RiskLevel.HIGH): PolicyCell(
        Dimension.AUDIENCE, RiskLevel.HIGH, VerificationRoute.AUTO_TRUST,
        1.000, 18, 6, _M,
    ),
    (Dimension.AUDIENCE, RiskLevel.MEDIUM): PolicyCell(
        Dimension.AUDIENCE, RiskLevel.MEDIUM, VerificationRoute.AUTO_TRUST,
        1.000, 18, 6, _N,
    ),
    (Dimension.AUDIENCE, RiskLevel.LOW): PolicyCell(
        Dimension.AUDIENCE, RiskLevel.LOW, VerificationRoute.AUTO_TRUST,
        1.000, 9, 3, _N,
    ),
}


def validate_policy_complete() -> None:
    expected = {
        (dimension, risk)
        for dimension in Dimension
        for risk in (RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW)
    }
    actual = set(RELIABILITY_POLICY_EN_ZH_V1)
    if actual != expected:
        missing = sorted(f"{d.value}×{r.value}" for d, r in expected - actual)
        extra = sorted(f"{d.value}×{r.value}" for d, r in actual - expected)
        raise PolicyConfigurationError(
            f"{RELIABILITY_POLICY_ID} is incomplete: missing={missing}, extra={extra}"
        )


validate_policy_complete()
