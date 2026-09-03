"""Explicitly offline demo fixture; never constructs a paid/network provider."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from review_triage.demo.app import create_app
from review_triage.llm import POST_EVAL_CONTROL_PROMPT_VERSION
from review_triage.persistence import SQLiteRepository
from review_triage.prompts import (
    PROMPT_VERSION_BY_DIMENSION,
    RenderedEvaluatorPrompt,
    RenderedStructuredPrompt,
)
from review_triage.schemas import Dimension, ReviewCaseInput, WorkflowState
from review_triage.service import ReviewTriageService
from review_triage.workflow import ReviewTriageWorkflow


class OfflineStructuredLLM:
    """Deterministic integration fixture isolated from the production adapter."""

    model_version = "offline-integration-fixture-v1"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke_structured(
        self,
        *,
        prompt_version: str,
        payload: Mapping[str, Any],
        output_schema: type[BaseModel],
        prompt: RenderedEvaluatorPrompt | RenderedStructuredPrompt | None = None,
    ) -> Mapping[str, Any]:
        del payload, output_schema, prompt
        self.calls.append(prompt_version)
        if prompt_version in {
            "node01_risk_classifier_v1",
            "node01_risk_classifier_v2",
            "node01_risk_classifier_v3",
        }:
            return {
                "risk_level": "HIGH",
                "risk_factors": ["offline integration fixture"],
                "reason": "离线集成夹具返回固定的结构化风险结果。",
                "missing_context_fields": [],
                "clarification_question": None,
            }
        if prompt_version == POST_EVAL_CONTROL_PROMPT_VERSION:
            return {
                "terminology": {
                    "requires_external_evidence": False,
                    "term_candidate": None,
                    "evidence_need": None,
                    "normative_claim": False,
                    "reason": "Offline fixture requires no external evidence.",
                },
                "accuracy": {
                    "unresolved_external_support": False,
                    "reason": "Offline fixture has no unresolved support.",
                },
                "locale": {
                    "unresolved_external_support": False,
                    "reason": "Offline fixture has no unresolved support.",
                },
                "audience": {
                    "unresolved_external_support": False,
                    "reason": "Offline fixture has no unresolved support.",
                },
            }

        dimension_by_prompt = {
            version: dimension
            for dimension, version in PROMPT_VERSION_BY_DIMENSION.items()
        }
        dimension = dimension_by_prompt[prompt_version]
        common: dict[str, Any] = {
            "severity": "Major" if dimension == Dimension.ACCURACY else "Neutral",
            "q1": "offline fixture finding",
            "q2": "offline fixture impact",
            "notes": f"Offline {dimension.value} integration result.",
            "sources": [],
        }
        details: dict[Dimension, dict[str, Any]] = {
            Dimension.TERMINOLOGY: {"term_type": None},
            Dimension.ACCURACY: {
                "adjacent_correction": None,
                "boundary_risk": False,
            },
            Dimension.LOCALE: {"locale_element": None, "boundary_risk": False},
            Dimension.AUDIENCE: {"audience_element": None},
        }
        return {**common, **details[dimension]}


class OfflineReviewProcessor:
    """Runs the real workflow with a request-local in-memory audit store."""

    def __init__(self, llm: OfflineStructuredLLM) -> None:
        self.llm = llm

    def process_case(
        self,
        *,
        eval_run_id: str,
        raw_input: ReviewCaseInput,
        run_mode: str = "DEVELOPMENT",
    ) -> WorkflowState:
        with SQLiteRepository(":memory:") as repository:
            service = ReviewTriageService(
                workflow=ReviewTriageWorkflow(repository=repository, llm=self.llm),
                repository=repository,
            )
            return service.process_case(
                eval_run_id=eval_run_id,
                raw_input=raw_input,
                run_mode=run_mode,
            )


def create_offline_app():
    """Build an isolated in-memory app for tests and local integration checks."""

    offline_llm = OfflineStructuredLLM()
    service = OfflineReviewProcessor(offline_llm)
    offline_app = create_app(service_provider=lambda: service)
    offline_app.state.offline_llm = offline_llm
    return offline_app


app = create_offline_app()
