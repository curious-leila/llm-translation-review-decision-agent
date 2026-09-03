from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from review_triage.errors import PolicyConfigurationError
from review_triage.human_review import (
    build_human_review_view,
    node_07_submit_human_review,
)
from review_triage.nodes import node_00_normalize
from review_triage.persistence import SQLiteRepository
from review_triage.schemas import (
    Dimension,
    FinalPolicyRoute,
    HumanDisposition,
    HumanReviewSubmission,
    ReviewMode,
    RouteDecision,
    SamplingDecision,
    Severity,
)
from tests.helpers import evaluations


def route(case_id: str, value: FinalPolicyRoute) -> RouteDecision:
    return RouteDecision(
        case_id=case_id,
        final_policy_route=value,
        triggering_dimensions=[],
        blocking_dimensions=[],
        sample_audit_dimensions=[],
        route_reason_codes=["fixture"],
    )


def submission(**overrides) -> HumanReviewSubmission:
    values = {
        "review_mode": ReviewMode.OPERATIONAL_ASSISTED,
        "human_terminology_severity": Severity.NEUTRAL,
        "human_accuracy_severity": Severity.NEUTRAL,
        "human_locale_severity": Severity.NEUTRAL,
        "human_audience_severity": Severity.NEUTRAL,
        "human_final_disposition": HumanDisposition.APPROVE_AS_IS,
        "human_notes": "Reviewed all four dimensions.",
        "reviewer_id": "reviewer-1",
    }
    values.update(overrides)
    return HumanReviewSubmission(**values)


class HumanReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SQLiteRepository(":memory:")
        self.repository.start_eval_run("run-human")
        self.case = node_00_normalize(
            {
                "source_text": "Continue",
                "translation": "继续",
                "content_type": "UI",
            }
        )
        self.repository.save_review_case("run-human", self.case)
        self.evaluations = evaluations(case_id=self.case.case_id)

    def tearDown(self) -> None:
        self.repository.close()

    def test_eval_blind_view_excludes_all_ai_and_agent_conclusions(self) -> None:
        view = build_human_review_view(
            review_case=self.case,
            review_mode=ReviewMode.EVAL_BLIND,
            evaluations=self.evaluations,
            route=route(self.case.case_id, FinalPolicyRoute.HUMAN_REQUIRED),
        )
        payload = view.model_dump(mode="json")
        self.assertIsNone(payload["ai_findings"])
        self.assertIsNone(payload["verified_evidence"])
        self.assertIsNone(payload["route_reason"])
        serialized = json.dumps(payload)
        self.assertNotIn("severity", serialized)
        self.assertNotIn("model route", serialized)

    def test_operational_view_includes_assistance(self) -> None:
        view = build_human_review_view(
            review_case=self.case,
            review_mode=ReviewMode.OPERATIONAL_ASSISTED,
            evaluations=self.evaluations,
            route=route(self.case.case_id, FinalPolicyRoute.HUMAN_REQUIRED),
        )
        self.assertEqual(len(view.ai_findings), 4)
        self.assertIsNotNone(view.route_reason)
        self.assertEqual(view.verified_evidence, [])

    def test_human_required_submission_persists_feedback_and_audit(self) -> None:
        upstream_route = route(self.case.case_id, FinalPolicyRoute.HUMAN_REQUIRED)
        result = node_07_submit_human_review(
            eval_run_id="run-human",
            review_case=self.case,
            evaluations=self.evaluations,
            route=upstream_route,
            submission=submission(),
            repository=self.repository,
        )
        self.assertEqual(result.case_id, self.case.case_id)
        self.assertEqual(
            upstream_route.final_policy_route, FinalPolicyRoute.HUMAN_REQUIRED
        )
        feedback = self.repository.fetch_all("SELECT * FROM human_feedback")
        self.assertEqual(len(feedback), 1)
        self.assertIn("APPROVE_AS_IS", feedback[0]["payload_json"])
        structured = json.loads(feedback[0]["payload_json"])
        self.assertIsInstance(structured["human_result"], dict)
        self.assertEqual(len(structured["ai_evaluations"]), 4)
        self.assertIsInstance(structured["route_decision"], dict)
        audit = self.repository.fetch_all(
            "SELECT reason_code FROM node_audit_logs WHERE node_name='NODE-07'"
        )[0]
        self.assertEqual(audit["reason_code"], "APPROVE_AS_IS")

    def test_selected_sample_pool_may_enter(self) -> None:
        upstream_route = route(self.case.case_id, FinalPolicyRoute.SAMPLE_POOL)
        sample = SamplingDecision(
            case_id=self.case.case_id,
            eval_run_id="run-human",
            pool_size=1,
            sample_size=1,
            selected_for_audit=True,
            sampling_seed="fixed",
            selection_reason="selected fixture",
        )
        result = node_07_submit_human_review(
            eval_run_id="run-human",
            review_case=self.case,
            evaluations=self.evaluations,
            route=upstream_route,
            sampling=sample,
            submission=submission(review_mode=ReviewMode.EVAL_BLIND),
            repository=self.repository,
        )
        self.assertEqual(result.review_mode, ReviewMode.EVAL_BLIND)

    def test_auto_pass_and_unselected_sample_pool_cannot_enter(self) -> None:
        with self.assertRaises(PolicyConfigurationError):
            node_07_submit_human_review(
                eval_run_id="run-human",
                review_case=self.case,
                evaluations=self.evaluations,
                route=route(self.case.case_id, FinalPolicyRoute.AUTO_PASS),
                submission=submission(),
                repository=self.repository,
            )
        not_selected = SamplingDecision(
            case_id=self.case.case_id,
            eval_run_id="run-human",
            pool_size=1,
            sample_size=1,
            selected_for_audit=False,
            sampling_seed="fixed",
            selection_reason="not selected fixture",
        )
        with self.assertRaises(PolicyConfigurationError):
            node_07_submit_human_review(
                eval_run_id="run-human",
                review_case=self.case,
                evaluations=self.evaluations,
                route=route(self.case.case_id, FinalPolicyRoute.SAMPLE_POOL),
                sampling=not_selected,
                submission=submission(),
                repository=self.repository,
            )

    def test_disagreement_requires_notes(self) -> None:
        with self.assertRaises(PolicyConfigurationError):
            node_07_submit_human_review(
                eval_run_id="run-human",
                review_case=self.case,
                evaluations=self.evaluations,
                route=route(self.case.case_id, FinalPolicyRoute.HUMAN_REQUIRED),
                submission=submission(
                    human_accuracy_severity=Severity.MAJOR, human_notes=""
                ),
                repository=self.repository,
            )

    def test_edit_required_needs_correction_and_unresolved_is_allowed(self) -> None:
        with self.assertRaises(ValidationError):
            submission(human_final_disposition=HumanDisposition.EDIT_REQUIRED)
        unresolved = submission(
            human_final_disposition=HumanDisposition.UNRESOLVED,
            human_notes="Insufficient context even after review.",
        )
        result = node_07_submit_human_review(
            eval_run_id="run-human",
            review_case=self.case,
            evaluations=self.evaluations,
            route=route(self.case.case_id, FinalPolicyRoute.HUMAN_REQUIRED),
            submission=unresolved,
            repository=self.repository,
        )
        self.assertEqual(result.human_final_disposition, HumanDisposition.UNRESOLVED)


if __name__ == "__main__":
    unittest.main()
