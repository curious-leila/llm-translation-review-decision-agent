"""Explicit local LIVE startup surface for one engineering-only integration run.

Start this module intentionally with Uvicorn.  The browser never selects live
mode; this module is the sole opt-in and writes only to an ignored runtime DB.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException

from review_triage.demo.app import create_app
from review_triage.demo_evidence_pack_v1 import load_demo_evidence_pack_v1
from review_triage.demo_evidence_retrieval_v2 import DemoEvidenceRetrievalV2
from review_triage.evidence import EvidenceActionSelector, EvidenceCandidateAssessor
from review_triage.evidence_tools import ControlledEvidenceTools
from review_triage.llm import StructuredLLM
from review_triage.normative_admission import DemoNormativeAdmissionV1
from review_triage.persistence import SQLiteRepository
from review_triage.providers.deepseek import DeepSeekProvider
from review_triage.schemas import (
    EvidenceAction,
    EvidenceToolResult,
    ReviewCaseInput,
    WorkflowState,
)
from review_triage.service import ReviewTriageService
from review_triage.workflow import ReviewTriageWorkflow


RUNTIME_DATABASE = Path("runtime/demo_live_integration.sqlite3")
RUN_PREFIX = "demo-live-engineering-only"


class DemoV1EvidenceTools(ControlledEvidenceTools):
    """Expose the frozen Demo retrieval behind the existing official-doc action."""

    def __init__(self, official_docs: DemoEvidenceRetrievalV2) -> None:
        super().__init__()
        self.official_docs = official_docs

    def search_official_docs(
        self,
        query: str,
        *,
        term_candidate: str | None = None,
    ) -> EvidenceToolResult:
        return self.official_docs.search_official_docs(
            query,
            term_candidate=term_candidate,
        )


def build_demo_v1_workflow(
    *,
    repository: SQLiteRepository,
    llm: StructuredLLM,
    evidence_selector: EvidenceActionSelector | None = None,
    evidence_assessor: EvidenceCandidateAssessor | None = None,
) -> ReviewTriageWorkflow:
    """Compose Demo-only evidence runtime dependencies from one validated pack."""

    pack = load_demo_evidence_pack_v1()
    return ReviewTriageWorkflow(
        repository=repository,
        llm=llm,
        evidence_selector=evidence_selector,
        evidence_assessor=evidence_assessor,
        evidence_tools=DemoV1EvidenceTools(DemoEvidenceRetrievalV2(pack)),
        normative_admission_policy=DemoNormativeAdmissionV1(pack),
        available_evidence_actions=(EvidenceAction.SEARCH_OFFICIAL_DOCS,),
    )


class SingleUseLiveProcessor:
    """Server-side usage cap for live-case executions per process.

    ``max_uses=None`` disables the cap; the public demo deployment relies on
    the per-IP rate limiter instead of a process-wide one-shot guard.
    """

    def __init__(
        self, service: ReviewTriageService, max_uses: int | None = 1
    ) -> None:
        self.service = service
        self._lock = Lock()
        self._uses = 0
        self._max_uses = max_uses

    def process_case(
        self,
        *,
        eval_run_id: str,
        raw_input: ReviewCaseInput,
        run_mode: str = "DEVELOPMENT",
    ) -> WorkflowState:
        with self._lock:
            if self._max_uses is not None and self._uses >= self._max_uses:
                raise HTTPException(
                    status_code=409,
                    detail="This live server has reached its case cap.",
                )
            self._uses += 1
        return self.service.process_case(
            eval_run_id=eval_run_id,
            raw_input=raw_input,
            run_mode=run_mode,
        )


RUNTIME_DATABASE.parent.mkdir(parents=True, exist_ok=True)
repository = SQLiteRepository(RUNTIME_DATABASE)
provider = DeepSeekProvider.from_env()
service = ReviewTriageService(
    workflow=build_demo_v1_workflow(
        repository=repository,
        llm=provider,
    ),
    repository=repository,
)
processor = SingleUseLiveProcessor(service, max_uses=None)
app = create_app(
    service_provider=lambda: processor,
    eval_run_id_factory=lambda: f"{RUN_PREFIX}-{uuid4()}",
    shutdown_callback=lambda: (provider.close(), repository.close()),
)
app.state.live_provider = provider
app.state.runtime_database = RUNTIME_DATABASE
