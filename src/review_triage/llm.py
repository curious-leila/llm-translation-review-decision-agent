"""Strict, provider-neutral single-call LLM interfaces for NODE-01/02."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from review_triage.errors import LLMProcessingError
from review_triage.prompts import (
    POST_EVAL_CONTROL_PROMPT_VERSION,
    EvaluatorPrompt,
    PostEvalControlPromptLoader,
    ReviewPromptRegistry,
    RenderedEvaluatorPrompt,
    RenderedStructuredPrompt,
)
from review_triage.schemas import (
    AccuracyDetails,
    AudienceDetails,
    BaselineDimensionEvaluation,
    BaselineTerminologyDetails,
    Dimension,
    DimensionEvaluation,
    LocaleDetails,
    PostEvalControlClassifierInput,
    PostEvalControlDimensionInput,
    PostEvalControlDecision,
    PostEvalControlReviewCaseInput,
    QualityEvaluationInput,
    RiskClassificationInput,
    RiskLevel,
    RiskResult,
    Severity,
    TerminologyDetails,
    TerminologyControlDecision,
    DimensionSupportControl,
    VerifiedEvidence,
)


class _LLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RiskLLMOutput(_LLMOutput):
    risk_level: RiskLevel
    risk_factors: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    missing_context_fields: list[str] = Field(default_factory=list)
    clarification_question: str | None = None

    @model_validator(mode="after")
    def validate_context_fields(self) -> "RiskLLMOutput":
        insufficient = self.risk_level == RiskLevel.INSUFFICIENT_CONTEXT
        if insufficient and (
            not self.missing_context_fields or not self.clarification_question
        ):
            raise ValueError(
                "INSUFFICIENT_CONTEXT requires missing_context_fields and "
                "clarification_question"
            )
        if not insufficient and (
            self.missing_context_fields or self.clarification_question is not None
        ):
            raise ValueError(
                "context recovery fields are only valid for INSUFFICIENT_CONTEXT"
            )
        return self


class DimensionLLMOutputBase(_LLMOutput):
    severity: Severity
    q1: str
    q2: str
    notes: str
    sources: list[str] = Field(default_factory=list)


class BaselineTerminologyLLMOutput(DimensionLLMOutputBase):
    term_type: str | None


class AccuracyLLMOutput(DimensionLLMOutputBase):
    adjacent_correction: str | bool | None
    boundary_risk: str | bool | None


class LocaleLLMOutput(DimensionLLMOutputBase):
    locale_element: str | None
    boundary_risk: str | bool | None


class AudienceLLMOutput(DimensionLLMOutputBase):
    audience_element: str | None


class TerminologyControlLLMOutput(_LLMOutput):
    requires_external_evidence: bool
    term_candidate: str | None
    evidence_need: str | None
    normative_claim: bool
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_request(self) -> "TerminologyControlLLMOutput":
        TerminologyControlDecision.model_validate(self.model_dump())
        return self


class DimensionSupportControlLLMOutput(_LLMOutput):
    unresolved_external_support: bool
    reason: str = Field(min_length=1)


class PostEvalControlLLMOutput(_LLMOutput):
    terminology: TerminologyControlLLMOutput
    accuracy: DimensionSupportControlLLMOutput
    locale: DimensionSupportControlLLMOutput
    audience: DimensionSupportControlLLMOutput


class FinalTerminologyLLMOutput(_LLMOutput):
    severity: Severity
    q1: str
    q2: str
    notes: str
    model_reported_sources: list[str] = Field(default_factory=list)
    term_type: str | None


DIMENSION_OUTPUT_SCHEMAS: dict[Dimension, type[DimensionLLMOutputBase]] = {
    Dimension.TERMINOLOGY: BaselineTerminologyLLMOutput,
    Dimension.ACCURACY: AccuracyLLMOutput,
    Dimension.LOCALE: LocaleLLMOutput,
    Dimension.AUDIENCE: AudienceLLMOutput,
}


class StructuredLLM(Protocol):
    """One model call returning JSON text or an already decoded JSON object."""

    @property
    def model_version(self) -> str: ...

    def invoke_structured(
        self,
        *,
        prompt_version: str,
        payload: Mapping[str, Any],
        output_schema: type[BaseModel],
        prompt: RenderedEvaluatorPrompt | RenderedStructuredPrompt | None = None,
    ) -> str | Mapping[str, Any]: ...


ModelT = TypeVar("ModelT", bound=BaseModel)


def _provider_failure_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and code.startswith("PROVIDER_") else "LLM_API_FAILURE"


def parse_strict_output(
    raw: str | Mapping[str, Any],
    schema: type[ModelT],
    *,
    node_name: str,
) -> ModelT:
    try:
        decoded: Any = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise LLMProcessingError(
            "LLM_INVALID_JSON",
            f"{node_name} returned invalid JSON: {error}",
            node_name=node_name,
        ) from error
    try:
        return schema.model_validate(decoded)
    except ValidationError as error:
        raise LLMProcessingError(
            "LLM_SCHEMA_MISMATCH",
            f"{node_name} output failed schema validation: {error}",
            node_name=node_name,
        ) from error


def invoke_risk_classifier(
    client: StructuredLLM,
    *,
    case_id: str,
    payload: RiskClassificationInput,
    prompt_version: str = "node01_risk_classifier_v3",
    prompt_registry: ReviewPromptRegistry | None = None,
) -> RiskResult:
    node_name = "NODE-01"
    request = payload.model_dump(mode="json")
    rendered_prompt = (prompt_registry or ReviewPromptRegistry()).render(
        prompt_version, request
    )
    try:
        raw = client.invoke_structured(
            prompt_version=prompt_version,
            payload=request,
            output_schema=RiskLLMOutput,
            prompt=rendered_prompt,
        )
    except LLMProcessingError:
        raise
    except Exception as error:
        raise LLMProcessingError(
            _provider_failure_code(error),
            f"{node_name} model call failed: {error}",
            node_name=node_name,
        ) from error
    parsed = parse_strict_output(raw, RiskLLMOutput, node_name=node_name)
    return RiskResult(
        case_id=case_id,
        **parsed.model_dump(),
        model_version=client.model_version,
        prompt_version=prompt_version,
        prompt_path=rendered_prompt.prompt_path,
        prompt_hash=rendered_prompt.prompt_hash,
    )


def invoke_dimension_evaluator(
    client: StructuredLLM,
    *,
    case_id: str,
    dimension: Dimension,
    payload: QualityEvaluationInput,
    prompt: EvaluatorPrompt,
) -> BaselineDimensionEvaluation:
    """Invoke one independent evaluator without any NODE-01 risk input."""

    node_name = f"NODE-02-{dimension.value}"
    request = payload.model_dump(mode="json")
    if prompt.dimension != dimension:
        raise AssertionError(
            f"{dimension.value} evaluator received {prompt.dimension.value} prompt"
        )
    if "risk_level" in request or "case_risk" in request:
        raise AssertionError("NODE-02 evaluator contract must not contain risk")
    rendered_prompt = prompt.render(payload)
    try:
        raw = client.invoke_structured(
            prompt_version=prompt.prompt_version,
            payload=request,
            output_schema=DIMENSION_OUTPUT_SCHEMAS[dimension],
            prompt=rendered_prompt,
        )
    except LLMProcessingError:
        raise
    except Exception as error:
        raise LLMProcessingError(
            _provider_failure_code(error),
            f"{node_name} model call failed: {error}",
            node_name=node_name,
        ) from error
    parsed = parse_strict_output(
        raw, DIMENSION_OUTPUT_SCHEMAS[dimension], node_name=node_name
    )
    details = {
        Dimension.TERMINOLOGY: lambda value: BaselineTerminologyDetails(
            term_type=value.term_type,
        ),
        Dimension.ACCURACY: lambda value: AccuracyDetails(
            adjacent_correction=value.adjacent_correction,
            boundary_risk=value.boundary_risk,
        ),
        Dimension.LOCALE: lambda value: LocaleDetails(
            locale_element=value.locale_element,
            boundary_risk=value.boundary_risk,
        ),
        Dimension.AUDIENCE: lambda value: AudienceDetails(
            audience_element=value.audience_element
        ),
    }[dimension](parsed)
    return BaselineDimensionEvaluation(
        case_id=case_id,
        dimension=dimension,
        severity=parsed.severity,
        q1=parsed.q1,
        q2=parsed.q2,
        notes=parsed.notes,
        model_reported_sources=parsed.sources,
        dimension_specific=details,
        model_version=client.model_version,
        prompt_version=prompt.prompt_version,
        prompt_path=prompt.prompt_path,
        prompt_hash=prompt.prompt_hash,
    )


def invoke_post_eval_control_classifier(
    client: StructuredLLM,
    *,
    case_id: str,
    review_case_fields: Mapping[str, Any],
    evaluations: list[BaselineDimensionEvaluation],
    prompt_version: str = POST_EVAL_CONTROL_PROMPT_VERSION,
    prompt_loader: PostEvalControlPromptLoader | None = None,
) -> tuple[PostEvalControlDecision, list[DimensionEvaluation]]:
    """Classify evidence controls once, without changing baseline judgments."""

    node_name = "NODE-02-POST-EVAL-CONTROL"
    if len(evaluations) != len(Dimension) or {
        item.dimension for item in evaluations
    } != set(Dimension):
        raise LLMProcessingError(
            "LLM_SCHEMA_MISMATCH",
            "Post-Eval Control Classifier requires exactly four dimension evaluations",
            node_name=node_name,
        )

    baseline_payload = [
        PostEvalControlDimensionInput(
            dimension=item.dimension,
            severity=item.severity,
            q1=item.q1,
            q2=item.q2,
            notes=item.notes,
            model_reported_sources=list(item.model_reported_sources),
            dimension_specific=item.dimension_specific,
        )
        for item in evaluations
    ]
    try:
        typed_request = PostEvalControlClassifierInput(
            review_case=PostEvalControlReviewCaseInput.model_validate(
                dict(review_case_fields)
            ),
            dimension_evaluations=baseline_payload,
        )
    except ValidationError as error:
        raise LLMProcessingError(
            "LLM_SCHEMA_MISMATCH",
            f"{node_name} input failed schema validation: {error}",
            node_name=node_name,
        ) from error
    request = typed_request.model_dump(mode="json")
    rendered_prompt = (prompt_loader or PostEvalControlPromptLoader()).render(request)
    if prompt_version != rendered_prompt.prompt_version:
        raise LLMProcessingError(
            "LLM_SCHEMA_MISMATCH",
            "Post-Eval Control prompt version does not match the frozen artifact",
            node_name=node_name,
        )
    try:
        raw = client.invoke_structured(
            prompt_version=prompt_version,
            payload=request,
            output_schema=PostEvalControlLLMOutput,
            prompt=rendered_prompt,
        )
    except LLMProcessingError:
        raise
    except Exception as error:
        raise LLMProcessingError(
            _provider_failure_code(error),
            f"{node_name} model call failed: {error}",
            node_name=node_name,
        ) from error
    parsed = parse_strict_output(raw, PostEvalControlLLMOutput, node_name=node_name)
    decision = PostEvalControlDecision(
        case_id=case_id,
        terminology=TerminologyControlDecision.model_validate(
            parsed.terminology.model_dump()
        ),
        accuracy=DimensionSupportControl.model_validate(parsed.accuracy.model_dump()),
        locale=DimensionSupportControl.model_validate(parsed.locale.model_dump()),
        audience=DimensionSupportControl.model_validate(parsed.audience.model_dump()),
        model_version=client.model_version,
        prompt_version=prompt_version,
        prompt_path=rendered_prompt.prompt_path,
        prompt_hash=rendered_prompt.prompt_hash,
    )

    before = [
        (item.severity, item.q1, item.q2, item.notes) for item in evaluations
    ]
    controls = {
        Dimension.ACCURACY: decision.accuracy,
        Dimension.LOCALE: decision.locale,
        Dimension.AUDIENCE: decision.audience,
    }
    enriched: list[DimensionEvaluation] = []
    for item in evaluations:
        update: dict[str, Any]
        if item.dimension == Dimension.TERMINOLOGY:
            details = item.dimension_specific
            if not isinstance(details, BaselineTerminologyDetails):
                raise LLMProcessingError(
                    "LLM_SCHEMA_MISMATCH",
                    "Terminology baseline result has incompatible typed details",
                    node_name=node_name,
                )
            update = {
                "requires_external_evidence": (
                    decision.terminology.requires_external_evidence
                ),
                "unresolved_external_support": False,
                "dimension_specific": TerminologyDetails(
                    term_type=details.term_type,
                    term_candidate=decision.terminology.term_candidate,
                    evidence_need=decision.terminology.evidence_need,
                    normative_claim=decision.terminology.normative_claim,
                ),
            }
        else:
            update = {
                "unresolved_external_support": controls[
                    item.dimension
                ].unresolved_external_support,
                "requires_external_evidence": False,
            }
        enriched.append(
            DimensionEvaluation.model_validate(
                {**item.model_dump(mode="python"), **update}
            )
        )

    after = [(item.severity, item.q1, item.q2, item.notes) for item in enriched]
    if before != after:
        raise AssertionError("Post-Eval Control Classifier altered baseline judgments")
    return decision, enriched


def invoke_final_terminology_evaluator(
    client: StructuredLLM,
    *,
    case_id: str,
    payload: QualityEvaluationInput,
    verified_evidence: list[VerifiedEvidence],
    prompt_version: str = "node02a_terminology_final_v1",
    prompt_registry: ReviewPromptRegistry | None = None,
) -> DimensionEvaluation:
    """Run the frozen post-evidence Final Terminology Judgment."""

    if not verified_evidence:
        raise LLMProcessingError(
            "LLM_SCHEMA_MISMATCH",
            "Final Terminology Judgment requires verified evidence",
            node_name="NODE-02-TERMINOLOGY-FINAL",
        )
    node_name = "NODE-02-TERMINOLOGY-FINAL"
    request = payload.model_dump(mode="json")
    request["verified_evidence"] = [
        item.model_dump(mode="json") for item in verified_evidence
    ]
    if "risk_level" in request or "case_risk" in request:
        raise AssertionError("Final Terminology evaluator must not contain risk")
    rendered_prompt = (prompt_registry or ReviewPromptRegistry()).render(
        prompt_version, request
    )
    try:
        raw = client.invoke_structured(
            prompt_version=prompt_version,
            payload=request,
            output_schema=FinalTerminologyLLMOutput,
            prompt=rendered_prompt,
        )
    except LLMProcessingError:
        raise
    except Exception as error:
        raise LLMProcessingError(
            _provider_failure_code(error),
            f"{node_name} model call failed: {error}",
            node_name=node_name,
        ) from error
    parsed = parse_strict_output(raw, FinalTerminologyLLMOutput, node_name=node_name)
    return DimensionEvaluation(
        case_id=case_id,
        dimension=Dimension.TERMINOLOGY,
        severity=parsed.severity,
        q1=parsed.q1,
        q2=parsed.q2,
        notes=parsed.notes,
        model_reported_sources=parsed.model_reported_sources,
        dimension_specific=TerminologyDetails(
            term_type=parsed.term_type,
            term_candidate=None,
            evidence_need=None,
            normative_claim=False,
        ),
        requires_external_evidence=False,
        unresolved_external_support=False,
        model_version=client.model_version,
        prompt_version=prompt_version,
        prompt_path=rendered_prompt.prompt_path,
        prompt_hash=rendered_prompt.prompt_hash,
    )
