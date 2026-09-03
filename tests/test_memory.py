from __future__ import annotations

import json
import unittest

from review_triage.human_review import node_07_submit_human_review
from review_triage.memory import node_08_write_memory
from review_triage.nodes import node_00_normalize
from review_triage.persistence import SQLiteRepository
from review_triage.schemas import (
    FinalPolicyRoute,
    HumanDisposition,
    HumanReviewResult,
    HumanReviewSubmission,
    MemoryWriteStatus,
    ReviewMode,
    RouteDecision,
    Severity,
)
from tests.helpers import evaluations


class MemoryGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SQLiteRepository(":memory:")
        self.repository.start_eval_run("run-memory")
        self.case = node_00_normalize(
            {
                "source_text": "Continue",
                "translation": "继续",
                "content_type": "UI",
                "brand_or_domain": "Acme",
            }
        )
        self.repository.save_review_case("run-memory", self.case)
        self.evaluations = evaluations(case_id=self.case.case_id)
        self.route = RouteDecision(
            case_id=self.case.case_id,
            final_policy_route=FinalPolicyRoute.HUMAN_REQUIRED,
            triggering_dimensions=[],
            blocking_dimensions=[],
            sample_audit_dimensions=[],
            route_reason_codes=["fixture"],
        )

    def tearDown(self) -> None:
        self.repository.close()

    def review(
        self,
        *,
        disposition: HumanDisposition = HumanDisposition.APPROVE_AS_IS,
        corrected: str | None = None,
    ) -> HumanReviewResult:
        return node_07_submit_human_review(
            eval_run_id="run-memory",
            review_case=self.case,
            evaluations=self.evaluations,
            route=self.route,
            submission=HumanReviewSubmission(
                review_mode=ReviewMode.OPERATIONAL_ASSISTED,
                human_terminology_severity=Severity.NEUTRAL,
                human_accuracy_severity=Severity.NEUTRAL,
                human_locale_severity=Severity.NEUTRAL,
                human_audience_severity=Severity.NEUTRAL,
                human_final_disposition=disposition,
                human_corrected_translation=corrected,
                human_notes="Human-validated fixture.",
                reviewer_id="reviewer-1",
            ),
            repository=self.repository,
        )

    def write(self, human: HumanReviewResult, **overrides):
        values = {
            "eval_run_id": "run-memory",
            "review_case": self.case,
            "human_result": human,
            "repository": self.repository,
            "memory_write_allowed": True,
            "is_frozen_holdout": False,
            "memory_snapshot_id": "memory_snapshot_v1",
        }
        values.update(overrides)
        return node_08_write_memory(**values)

    def test_approve_as_is_writes_human_validated_case_memory(self) -> None:
        result = self.write(self.review())
        self.assertEqual(result.memory_write_status, MemoryWriteStatus.WRITTEN)
        row = self.repository.fetch_all("SELECT * FROM case_memory")[0]
        payload = json.loads(row["payload_json"])
        self.assertEqual(row["validation_status"], "HUMAN_VALIDATED")
        self.assertEqual(payload["validated_translation"], self.case.translation)
        self.assertEqual(payload["evidence_basis"], "HUMAN_VALIDATED_CASE")
        self.assertEqual(payload["validated_terms"], [])

    def test_edit_required_writes_corrected_solution(self) -> None:
        result = self.write(
            self.review(
                disposition=HumanDisposition.EDIT_REQUIRED,
                corrected="请继续",
            )
        )
        self.assertEqual(result.memory_write_status, MemoryWriteStatus.WRITTEN)
        payload = json.loads(
            self.repository.fetch_all("SELECT payload_json FROM case_memory")[0][
                "payload_json"
            ]
        )
        self.assertEqual(payload["validated_translation"], "请继续")

    def test_unresolved_feedback_remains_but_memory_is_rejected(self) -> None:
        human = self.review(disposition=HumanDisposition.UNRESOLVED)
        result = self.write(human)
        self.assertEqual(
            result.memory_write_status, MemoryWriteStatus.SKIPPED_NOT_ELIGIBLE
        )
        self.assertEqual(
            self.repository.fetch_all("SELECT COUNT(*) count FROM human_feedback")[0][
                "count"
            ],
            1,
        )
        self.assertEqual(
            self.repository.fetch_all("SELECT COUNT(*) count FROM case_memory")[0][
                "count"
            ],
            0,
        )

    def test_frozen_holdout_blocks_write(self) -> None:
        result = self.write(self.review(), is_frozen_holdout=True)
        self.assertEqual(
            result.memory_write_status, MemoryWriteStatus.BLOCKED_EVAL_FREEZE
        )
        self.assertEqual(
            self.repository.fetch_all("SELECT COUNT(*) count FROM case_memory")[0][
                "count"
            ],
            0,
        )

    def test_memory_write_allowed_false_skips(self) -> None:
        result = self.write(self.review(), memory_write_allowed=False)
        self.assertEqual(
            result.memory_write_status, MemoryWriteStatus.SKIPPED_NOT_ELIGIBLE
        )

    def test_unpersisted_human_result_is_not_eligible(self) -> None:
        human = HumanReviewResult(
            case_id=self.case.case_id,
            review_mode=ReviewMode.OPERATIONAL_ASSISTED,
            human_terminology_severity=Severity.NEUTRAL,
            human_accuracy_severity=Severity.NEUTRAL,
            human_locale_severity=Severity.NEUTRAL,
            human_audience_severity=Severity.NEUTRAL,
            human_final_disposition=HumanDisposition.APPROVE_AS_IS,
            human_notes="Not persisted.",
            reviewer_id="reviewer-1",
        )
        result = self.write(human)
        self.assertEqual(
            result.memory_write_status, MemoryWriteStatus.SKIPPED_NOT_ELIGIBLE
        )
        self.assertIn("human_feedback", result.eligibility_reason)

    def test_exact_duplicate_is_skipped(self) -> None:
        human = self.review()
        first = self.write(human)
        second = self.write(human)
        self.assertEqual(first.memory_write_status, MemoryWriteStatus.WRITTEN)
        self.assertEqual(second.memory_write_status, MemoryWriteStatus.SKIPPED_DUPLICATE)
        self.assertEqual(first.memory_id, second.memory_id)
        self.assertEqual(
            self.repository.fetch_all("SELECT COUNT(*) count FROM case_memory")[0][
                "count"
            ],
            1,
        )

    def test_conflicting_validated_solution_is_preserved_and_linked(self) -> None:
        first = self.write(self.review())
        second = self.write(
            self.review(
                disposition=HumanDisposition.EDIT_REQUIRED,
                corrected="请继续",
            )
        )
        self.assertEqual(first.memory_write_status, MemoryWriteStatus.WRITTEN)
        self.assertEqual(second.memory_write_status, MemoryWriteStatus.WRITTEN)
        self.assertIn("conflicting", second.eligibility_reason)
        memories = self.repository.fetch_all("SELECT memory_id FROM case_memory")
        conflicts = self.repository.fetch_all("SELECT * FROM memory_conflicts")
        self.assertEqual(len(memories), 2)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["existing_memory_id"], first.memory_id)
        self.assertEqual(conflicts[0]["new_memory_id"], second.memory_id)

    def test_every_gate_result_is_audited(self) -> None:
        self.write(self.review(), memory_write_allowed=False)
        audit = self.repository.fetch_all(
            "SELECT reason_code FROM node_audit_logs WHERE node_name='NODE-08'"
        )[0]
        self.assertEqual(audit["reason_code"], "SKIPPED_NOT_ELIGIBLE")


if __name__ == "__main__":
    unittest.main()
