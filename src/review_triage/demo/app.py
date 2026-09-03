"""FastAPI application factory for the standalone Review Triage demo."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from review_triage.demo.contracts import ReviewResultDTO, to_review_result
from review_triage.demo.rate_limit import RateLimiter
from review_triage.schemas import ReviewCaseInput, WorkflowState


STATIC_DIRECTORY = Path(__file__).with_name("static")
MAX_FIELD_LENGTH = 2000


class ReviewProcessor(Protocol):
    def process_case(
        self,
        *,
        eval_run_id: str,
        raw_input: ReviewCaseInput,
        run_mode: str = "DEVELOPMENT",
    ) -> WorkflowState: ...


def create_app(
    *,
    service_provider: Callable[[], ReviewProcessor],
    eval_run_id_factory: Callable[[], str] | None = None,
    shutdown_callback: Callable[[], None] | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    """Create one-origin static + API app around an injected existing service."""

    app = FastAPI(title="Review Triage Demo", version="0.1.0")
    limiter = rate_limiter or RateLimiter()

    @app.middleware("http")
    async def enforce_demo_rate_limit(request: Request, call_next):
        if request.method == "POST" and request.url.path == "/api/review":
            if not limiter.allow(limiter.client_key(request)):
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "提交过于频繁，请稍后重试",
                        }
                    },
                )
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "location": [str(part) for part in item["loc"]],
                "type": item["type"],
                "message": item["msg"],
            }
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "请求字段无效",
                    "details": details,
                }
            },
        )

    create_eval_run_id = eval_run_id_factory or (lambda: str(uuid4()))

    @app.post("/api/review", response_model=ReviewResultDTO)
    async def review(request: ReviewCaseInput) -> ReviewResultDTO:
        if (
            len(request.source_text) > MAX_FIELD_LENGTH
            or len(request.translation) > MAX_FIELD_LENGTH
        ):
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "TEXT_TOO_LONG",
                        "message": "原文与译文长度需在 2000 字符以内",
                    }
                },
            )
        service = service_provider()
        state = service.process_case(
            eval_run_id=create_eval_run_id(),
            raw_input=request,
            run_mode="DEVELOPMENT",
        )
        return to_review_result(state)

    if shutdown_callback is not None:
        app.router.on_shutdown.append(shutdown_callback)

    app.mount("/assets", StaticFiles(directory=STATIC_DIRECTORY), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIRECTORY / "index.html")

    return app
