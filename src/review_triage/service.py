"""Minimal application service closing the MVP V1 ReviewCase lifecycle."""

from __future__ import annotations

from typing import Any

from review_triage.human_review import node_07_submit_human_review
from review_triage.memory import node_08_write_memory
from review_triage.persistence import SQLiteRepository
from review_triage.schemas import (
    CaseClosureResult,
    HumanReviewSubmission,
    ReviewCaseInput,
    SamplingDecision,
    WorkflowState,
)
from review_triage.workflow import ReviewTriageWorkflow


class ReviewTriageService:
    """Compose frozen nodes without adding or overriding product policy."""

    def __init__(
        self,
        *,
        workflow: ReviewTriageWorkflow,
        repository: SQLiteRepository,
    ) -> None:
        self.workflow = workflow
        self.repository = repository

    def process_case(
        self,
        *,
        eval_run_id: str,
        raw_input: ReviewCaseInput | dict[str, Any],
        run_mode: str = "DEVELOPMENT",
    ) -> WorkflowState:
        return self.workflow.run(
            eval_run_id=eval_run_id,
            raw_input=raw_input,
            run_mode=run_mode,
        )

    def complete_human_case(
        self,
        *,
        automated: WorkflowState,
        submission: HumanReviewSubmission,
        memory_write_allowed: bool,
        is_frozen_holdout: bool,
        memory_snapshot_id: str | None = None,
        sampling: SamplingDecision | None = None,
    ) -> CaseClosureResult:
        if automated.processing_error is not None:
            raise ValueError("cannot Human-close a workflow with processing_error")
        if automated.review_case is None or automated.route_decision is None:
            raise ValueError("cannot Human-close a workflow without a final route")
        human = node_07_submit_human_review(
            eval_run_id=automated.eval_run_id,
            review_case=automated.review_case,
            evaluations=automated.dimension_evaluations,
            route=automated.route_decision,
            submission=submission,
            repository=self.repository,
            sampling=sampling,
            terminology_evidence=automated.terminology_evidence,
        )
        memory = node_08_write_memory(
            eval_run_id=automated.eval_run_id,
            review_case=automated.review_case,
            human_result=human,
            repository=self.repository,
            memory_write_allowed=memory_write_allowed,
            is_frozen_holdout=is_frozen_holdout,
            memory_snapshot_id=memory_snapshot_id,
            terminology_evidence=automated.terminology_evidence,
        )
        self.repository.finish_eval_run(
            automated.eval_run_id, status="HUMAN_REVIEW_COMPLETED"
        )
        return CaseClosureResult(
            eval_run_id=automated.eval_run_id,
            case_id=automated.review_case.case_id,
            final_policy_route=automated.route_decision.final_policy_route,
            human_review=human,
            memory_write=memory,
        )
