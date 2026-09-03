from __future__ import annotations

import unittest

from review_triage.errors import InvalidInputError
from review_triage.nodes import (
    node_00_normalize,
    node_04_reliability,
    node_05_aggregate,
)
from review_triage.policy import RELIABILITY_POLICY_EN_ZH_V1
from review_triage.schemas import (
    ContentType,
    Dimension,
    EvidenceStatus,
    EvidenceAction,
    FinalPolicyRoute,
    ProcessingStatus,
    RELIABILITY_POLICY_ID,
    RiskLevel,
    Severity,
    TerminologyEvidenceState,
    VerificationRoute,
)
from tests.helpers import evaluations


class Node00Tests(unittest.TestCase):
    def test_valid_input_is_normalized(self) -> None:
        case = node_00_normalize(
            {
                "source_text": "  Continue  ",
                "translation": "继续",
                "content_type": "UI",
            }
        )
        self.assertEqual(case.source_text, "Continue")
        self.assertEqual(case.processing_status, ProcessingStatus.VALID)
        self.assertEqual(case.source_language, "en")
        self.assertEqual(case.target_locale, "zh-CN")

    def test_other_is_out_of_scope_not_invalid(self) -> None:
        case = node_00_normalize(
            {
                "source_text": "Clause",
                "translation": "条款",
                "content_type": ContentType.OTHER,
            }
        )
        self.assertEqual(case.processing_status, ProcessingStatus.OUT_OF_SCOPE)

    def test_missing_translation_is_invalid(self) -> None:
        with self.assertRaises(InvalidInputError):
            node_00_normalize({"source_text": "x", "content_type": "UI"})


class PolicyTests(unittest.TestCase):
    def test_policy_has_exactly_twelve_cells(self) -> None:
        expected = {
            (Dimension.TERMINOLOGY, RiskLevel.HIGH): ("HUMAN_VERIFY", 0.611, 18, 6),
            (Dimension.TERMINOLOGY, RiskLevel.MEDIUM): ("AUTO_TRUST", 1.000, 18, 6),
            (Dimension.TERMINOLOGY, RiskLevel.LOW): ("AUTO_TRUST", 1.000, 9, 3),
            (Dimension.ACCURACY, RiskLevel.HIGH): ("SAMPLE_AUDIT", 0.944, 18, 6),
            (Dimension.ACCURACY, RiskLevel.MEDIUM): ("AUTO_TRUST", 1.000, 18, 6),
            (Dimension.ACCURACY, RiskLevel.LOW): ("AUTO_TRUST", 1.000, 9, 3),
            (Dimension.LOCALE, RiskLevel.HIGH): ("AUTO_TRUST", 1.000, 18, 6),
            (Dimension.LOCALE, RiskLevel.MEDIUM): ("SAMPLE_AUDIT", 0.944, 18, 6),
            (Dimension.LOCALE, RiskLevel.LOW): ("AUTO_TRUST", 1.000, 9, 3),
            (Dimension.AUDIENCE, RiskLevel.HIGH): ("AUTO_TRUST", 1.000, 18, 6),
            (Dimension.AUDIENCE, RiskLevel.MEDIUM): ("AUTO_TRUST", 1.000, 18, 6),
            (Dimension.AUDIENCE, RiskLevel.LOW): ("AUTO_TRUST", 1.000, 9, 3),
        }
        actual = {
            key: (
                cell.verification_route.value,
                cell.observed_agreement,
                cell.sample_count,
                cell.source_case_count,
            )
            for key, cell in RELIABILITY_POLICY_EN_ZH_V1.items()
        }
        self.assertEqual(actual, expected)
        term_high = RELIABILITY_POLICY_EN_ZH_V1[
            (Dimension.TERMINOLOGY, RiskLevel.HIGH)
        ]
        self.assertEqual(term_high.verification_route, VerificationRoute.HUMAN_VERIFY)
        self.assertEqual(term_high.observed_agreement, 0.611)

    def test_node_04_lookup_and_unresolved_override(self) -> None:
        result = node_04_reliability(
            case_id="case-1",
            case_risk=RiskLevel.LOW,
            evaluations=evaluations(unresolved={Dimension.LOCALE}),
            reliability_policy_id=RELIABILITY_POLICY_ID,
        )
        by_dimension = {item.dimension: item for item in result}
        self.assertEqual(
            by_dimension[Dimension.LOCALE].verification_route,
            VerificationRoute.HUMAN_VERIFY,
        )
        self.assertEqual(
            by_dimension[Dimension.LOCALE].override_reason,
            "LOCALE_UNRESOLVED_EXTERNAL_SUPPORT",
        )

    def test_node_04_evidence_conflict_override(self) -> None:
        evidence = TerminologyEvidenceState(
            case_id="case-1",
            term_candidate="claim",
            evidence_need="official terminology",
            evidence_status=EvidenceStatus.CONFLICT,
            stop_action=EvidenceAction.ABSTAIN,
            stop_reason="verified sources conflict",
        )
        result = node_04_reliability(
            case_id="case-1",
            case_risk=RiskLevel.MEDIUM,
            evaluations=evaluations(),
            reliability_policy_id=RELIABILITY_POLICY_ID,
            terminology_evidence=evidence,
        )
        terminology = next(
            item for item in result if item.dimension == Dimension.TERMINOLOGY
        )
        self.assertEqual(terminology.verification_route, VerificationRoute.HUMAN_VERIFY)


class AggregationTests(unittest.TestCase):
    def _decisions(self, risk: RiskLevel, evals=None):
        return node_04_reliability(
            case_id="case-1",
            case_risk=risk,
            evaluations=evals or evaluations(),
            reliability_policy_id=RELIABILITY_POLICY_ID,
        )

    def test_auto_pass(self) -> None:
        evals = evaluations()
        route = node_05_aggregate(
            case_id="case-1",
            evaluations=evals,
            reliability_decisions=self._decisions(RiskLevel.LOW, evals),
        )
        self.assertEqual(route.final_policy_route, FinalPolicyRoute.AUTO_PASS)

    def test_sample_pool(self) -> None:
        evals = evaluations()
        route = node_05_aggregate(
            case_id="case-1",
            evaluations=evals,
            reliability_decisions=self._decisions(RiskLevel.MEDIUM, evals),
        )
        self.assertEqual(route.final_policy_route, FinalPolicyRoute.SAMPLE_POOL)
        self.assertIn(Dimension.LOCALE, route.sample_audit_dimensions)

    def test_human_verify_wins_over_sample(self) -> None:
        evals = evaluations()
        route = node_05_aggregate(
            case_id="case-1",
            evaluations=evals,
            reliability_decisions=self._decisions(RiskLevel.HIGH, evals),
        )
        self.assertEqual(route.final_policy_route, FinalPolicyRoute.HUMAN_REQUIRED)
        self.assertIn("TERMINOLOGY_HUMAN_VERIFY", route.route_reason_codes)

    def test_major_wins_over_auto_trust(self) -> None:
        evals = evaluations(severities={Dimension.ACCURACY: Severity.MAJOR})
        route = node_05_aggregate(
            case_id="case-1",
            evaluations=evals,
            reliability_decisions=self._decisions(RiskLevel.LOW, evals),
        )
        self.assertEqual(route.final_policy_route, FinalPolicyRoute.HUMAN_REQUIRED)
        self.assertIn("ACCURACY_BLOCKING_SEVERITY", route.route_reason_codes)


if __name__ == "__main__":
    unittest.main()
