"""Typed MVP V1 state and node contracts.

Critical routing decisions are represented by enums and Pydantic models.  No
downstream rule needs to parse natural-language prose.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


RELIABILITY_POLICY_ID = "reliability_policy_en_zh_v1"
AGGREGATION_RULE_VERSION = "route_aggregation_v1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", use_enum_values=False, str_strip_whitespace=True
    )


class ContentType(StrEnum):
    MARKETING = "MARKETING"
    CUSTOMER_SUPPORT = "CUSTOMER_SUPPORT"
    UI = "UI"
    OTHER = "OTHER"


class ProcessingStatus(StrEnum):
    RECEIVED = "RECEIVED"
    VALID = "VALID"
    NEEDS_CONTEXT = "NEEDS_CONTEXT"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    INVALID_INPUT = "INVALID_INPUT"
    PROCESSING_ERROR = "PROCESSING_ERROR"
    ROUTED = "ROUTED"


class RiskLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


class Dimension(StrEnum):
    TERMINOLOGY = "TERMINOLOGY"
    ACCURACY = "ACCURACY"
    LOCALE = "LOCALE"
    AUDIENCE = "AUDIENCE"


class Severity(StrEnum):
    NEUTRAL = "Neutral"
    MINOR = "Minor"
    MAJOR = "Major"
    CRITICAL = "Critical"


class EvidenceStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    CONFLICT = "CONFLICT"


class EvidenceAction(StrEnum):
    SEARCH_GLOSSARY = "SEARCH_GLOSSARY"
    SEARCH_OFFICIAL_DOCS = "SEARCH_OFFICIAL_DOCS"
    SEARCH_MEMORY = "SEARCH_MEMORY"
    STOP_SUFFICIENT = "STOP_SUFFICIENT"
    ABSTAIN = "ABSTAIN"


class ToolResultStatus(StrEnum):
    HIT = "HIT"
    MISS = "MISS"
    ERROR = "ERROR"
    CONFLICT = "CONFLICT"


class EvidenceProvenance(StrEnum):
    GLOSSARY = "GLOSSARY"
    OFFICIAL_DOCS = "OFFICIAL_DOCS"
    CASE_MEMORY = "CASE_MEMORY"


class NormativeAdmissionReasonCode(StrEnum):
    ASSESSOR_REJECTED = "ASSESSOR_REJECTED"
    SOURCE_NOT_ADMISSIBLE = "SOURCE_NOT_ADMISSIBLE"
    NORMATIVE_SUPPORT_UNDECLARED = "NORMATIVE_SUPPORT_UNDECLARED"
    TERM_MISMATCH = "TERM_MISMATCH"
    TERM_PAIR_NOT_ATTESTED = "TERM_PAIR_NOT_ATTESTED"
    LOCALE_SCOPE_MISMATCH = "LOCALE_SCOPE_MISMATCH"
    AUTHORITY_SCOPE_MISMATCH = "AUTHORITY_SCOPE_MISMATCH"
    CLAIM_SCOPE_INVALID = "CLAIM_SCOPE_INVALID"


class SeverityCoverage(StrEnum):
    NEUTRAL_ONLY = "NEUTRAL_ONLY"
    NON_NEUTRAL_PRESENT = "NON_NEUTRAL_PRESENT"


class VerificationRoute(StrEnum):
    AUTO_TRUST = "AUTO_TRUST"
    SAMPLE_AUDIT = "SAMPLE_AUDIT"
    HUMAN_VERIFY = "HUMAN_VERIFY"


class FinalPolicyRoute(StrEnum):
    AUTO_PASS = "AUTO_PASS"
    SAMPLE_POOL = "SAMPLE_POOL"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"


class ReviewMode(StrEnum):
    OPERATIONAL_ASSISTED = "OPERATIONAL_ASSISTED"
    EVAL_BLIND = "EVAL_BLIND"


class HumanDisposition(StrEnum):
    APPROVE_AS_IS = "APPROVE_AS_IS"
    EDIT_REQUIRED = "EDIT_REQUIRED"
    UNRESOLVED = "UNRESOLVED"


class EvidenceVerdict(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INSUFFICIENT = "INSUFFICIENT"


class ExternalSupportRequiredByDimension(StrictModel):
    """Completed Day 2 Human GT evidence-need annotation.

    These fields are deliberately strict Booleans. ``None`` is the unannotated
    packet placeholder only and cannot validate as completed Human GT.
    """

    terminology: StrictBool
    accuracy: StrictBool
    locale: StrictBool
    audience: StrictBool


class Day2HumanGroundTruthAnnotation(StrictModel):
    """Validation contract for a completed Day 2 EVAL_BLIND annotation."""

    human_terminology_severity: Severity
    human_accuracy_severity: Severity
    human_locale_severity: Severity
    human_audience_severity: Severity
    human_final_disposition: HumanDisposition
    human_corrected_translation: str | None = None
    external_support_required_by_dimension: ExternalSupportRequiredByDimension
    terminology_evidence_verdict: EvidenceVerdict | None = None
    human_notes: str = ""

    @model_validator(mode="after")
    def require_correction_for_edit(self) -> "Day2HumanGroundTruthAnnotation":
        if (
            self.human_final_disposition == HumanDisposition.EDIT_REQUIRED
            and not self.human_corrected_translation
        ):
            raise ValueError("EDIT_REQUIRED requires human_corrected_translation")
        return self


class MemoryWriteStatus(StrEnum):
    WRITTEN = "WRITTEN"
    SKIPPED_NOT_ELIGIBLE = "SKIPPED_NOT_ELIGIBLE"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
    BLOCKED_EVAL_FREEZE = "BLOCKED_EVAL_FREEZE"


class ReviewCaseInput(StrictModel):
    source_text: str = Field(min_length=1)
    translation: str = Field(min_length=1)
    content_type: ContentType
    brand_or_domain: str | None = None
    context_notes: str | None = None


class ReviewCase(ReviewCaseInput):
    case_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    source_language: Literal["en"] = "en"
    target_locale: Literal["zh-CN"] = "zh-CN"
    reliability_policy_id: Literal["reliability_policy_en_zh_v1"] = (
        RELIABILITY_POLICY_ID
    )
    processing_status: ProcessingStatus = ProcessingStatus.RECEIVED


class RiskClassificationInput(StrictModel):
    source_text: str
    content_type: ContentType
    brand_or_domain: str | None = None
    context_notes: str | None = None
    source_language: Literal["en"] = "en"
    target_locale: Literal["zh-CN"] = "zh-CN"


class RiskResult(StrictModel):
    case_id: str
    risk_level: RiskLevel
    risk_factors: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    missing_context_fields: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    model_version: str
    prompt_version: str
    prompt_path: str | None = None
    prompt_hash: str | None = None
    llm_run_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_context_fields(self) -> "RiskResult":
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


class QualityEvaluationInput(StrictModel):
    """Frozen baseline evaluator input contract; deliberately excludes risk."""

    source_text: str
    translation_text: str
    content_type: ContentType


class BaselineTerminologyDetails(StrictModel):
    term_type: str | None


class TerminologyDetails(StrictModel):
    term_type: str | None
    term_candidate: str | None = None
    evidence_need: str | None = None
    normative_claim: bool = False


class AccuracyDetails(StrictModel):
    adjacent_correction: str | bool | None
    boundary_risk: str | bool | None


class LocaleDetails(StrictModel):
    locale_element: str | None
    boundary_risk: str | bool | None


class AudienceDetails(StrictModel):
    audience_element: str | None


DimensionSpecificDetails = (
    TerminologyDetails | AccuracyDetails | LocaleDetails | AudienceDetails
)

BaselineDimensionSpecificDetails = (
    BaselineTerminologyDetails | AccuracyDetails | LocaleDetails | AudienceDetails
)


class BaselineDimensionEvaluation(StrictModel):
    """Exact baseline evaluator output plus system metadata, with no control fields."""

    case_id: str
    dimension: Dimension
    severity: Severity
    q1: str
    q2: str
    notes: str
    model_reported_sources: list[str] = Field(default_factory=list)
    dimension_specific: BaselineDimensionSpecificDetails
    model_version: str
    prompt_version: str
    prompt_path: str
    prompt_hash: str
    llm_run_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_dimension_details(self) -> "BaselineDimensionEvaluation":
        expected_type = {
            Dimension.TERMINOLOGY: BaselineTerminologyDetails,
            Dimension.ACCURACY: AccuracyDetails,
            Dimension.LOCALE: LocaleDetails,
            Dimension.AUDIENCE: AudienceDetails,
        }[self.dimension]
        if not isinstance(self.dimension_specific, expected_type):
            raise ValueError(
                f"{self.dimension.value} requires {expected_type.__name__}"
            )
        return self


class PostEvalControlReviewCaseInput(StrictModel):
    source_text: str
    translation_text: str
    content_type: ContentType
    brand_or_domain: str | None = None
    context_notes: str | None = None
    source_language: Literal["en"] = "en"
    target_locale: Literal["zh-CN"] = "zh-CN"


class PostEvalControlDimensionInput(StrictModel):
    dimension: Dimension
    severity: Severity
    q1: str
    q2: str
    notes: str
    model_reported_sources: list[str] = Field(default_factory=list)
    dimension_specific: BaselineDimensionSpecificDetails

    @model_validator(mode="after")
    def validate_dimension_details(self) -> "PostEvalControlDimensionInput":
        expected_type = {
            Dimension.TERMINOLOGY: BaselineTerminologyDetails,
            Dimension.ACCURACY: AccuracyDetails,
            Dimension.LOCALE: LocaleDetails,
            Dimension.AUDIENCE: AudienceDetails,
        }[self.dimension]
        if not isinstance(self.dimension_specific, expected_type):
            raise ValueError(
                f"{self.dimension.value} requires {expected_type.__name__}"
            )
        return self


class PostEvalControlClassifierInput(StrictModel):
    review_case: PostEvalControlReviewCaseInput
    dimension_evaluations: list[PostEvalControlDimensionInput]

    @model_validator(mode="after")
    def validate_four_dimensions(self) -> "PostEvalControlClassifierInput":
        dimensions = [item.dimension for item in self.dimension_evaluations]
        if len(dimensions) != len(Dimension) or set(dimensions) != set(Dimension):
            raise ValueError(
                "Post-Eval Control Classifier requires exactly one result per dimension"
            )
        return self


class TerminologyControlDecision(StrictModel):
    requires_external_evidence: bool
    term_candidate: str | None
    evidence_need: str | None
    normative_claim: bool
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_request(self) -> "TerminologyControlDecision":
        if self.requires_external_evidence:
            if not self.term_candidate or not self.evidence_need:
                raise ValueError(
                    "requires_external_evidence requires term_candidate and evidence_need"
                )
            if not self.normative_claim:
                raise ValueError(
                    "requires_external_evidence requires normative_claim=true"
                )
        elif self.term_candidate is not None or self.evidence_need is not None:
            raise ValueError(
                "term_candidate/evidence_need are only valid when external evidence is required"
            )
        if self.normative_claim and not self.requires_external_evidence:
            raise ValueError(
                "normative_claim requires external evidence under the frozen guardrail"
            )
        return self


class DimensionSupportControl(StrictModel):
    unresolved_external_support: bool
    reason: str = Field(min_length=1)


class PostEvalControlDecision(StrictModel):
    """NODE-02 internal control result; never owns evaluator judgments."""

    case_id: str
    terminology: TerminologyControlDecision
    accuracy: DimensionSupportControl
    locale: DimensionSupportControl
    audience: DimensionSupportControl
    model_version: str
    prompt_version: str
    prompt_path: str
    prompt_hash: str
    llm_run_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)


class DimensionEvaluation(StrictModel):
    case_id: str
    dimension: Dimension
    severity: Severity
    q1: str
    q2: str
    notes: str
    model_reported_sources: list[str] = Field(default_factory=list)
    dimension_specific: DimensionSpecificDetails
    requires_external_evidence: bool
    unresolved_external_support: bool
    model_version: str
    prompt_version: str
    prompt_path: str | None = None
    prompt_hash: str | None = None
    llm_run_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_evidence_scope(self) -> "DimensionEvaluation":
        expected_type = {
            Dimension.TERMINOLOGY: TerminologyDetails,
            Dimension.ACCURACY: AccuracyDetails,
            Dimension.LOCALE: LocaleDetails,
            Dimension.AUDIENCE: AudienceDetails,
        }[self.dimension]
        if not isinstance(self.dimension_specific, expected_type):
            raise ValueError(
                f"{self.dimension.value} requires {expected_type.__name__}"
            )
        if (
            self.dimension != Dimension.TERMINOLOGY
            and self.requires_external_evidence
        ):
            raise ValueError(
                "dynamic external evidence acquisition is terminology-only in MVP V1"
            )
        if self.dimension == Dimension.TERMINOLOGY and self.requires_external_evidence:
            details = self.dimension_specific
            if not isinstance(details, TerminologyDetails):
                raise ValueError("Terminology evidence requires TerminologyDetails")
            if not details.term_candidate or not details.evidence_need:
                raise ValueError(
                    "Terminology evidence requests require term_candidate and evidence_need"
                )
        return self


class EvidenceCandidate(StrictModel):
    candidate_id: str = Field(default_factory=lambda: str(uuid4()))
    term_candidate: str
    provenance: EvidenceProvenance
    source_ref: str
    content: str
    claim_key: str
    claim_value: str
    brand_or_domain: str | None = None
    target_locale: str = "zh-CN"
    scenario: str | None = None
    is_official_source: bool = False
    supports_normative_claim: bool = False
    validation_status: str | None = None


class EvidenceAssessmentItem(StrictModel):
    candidate_id: str
    relevant: bool
    context_match: bool
    reason: str


class EvidenceAssessment(StrictModel):
    assessments: list[EvidenceAssessmentItem]
    model_version: str
    prompt_version: str
    prompt_path: str | None = None
    prompt_hash: str | None = None


class EvidenceToolResult(StrictModel):
    status: ToolResultStatus
    candidates: list[EvidenceCandidate] = Field(default_factory=list)
    summary: str
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "EvidenceToolResult":
        if self.status == ToolResultStatus.HIT and not self.candidates:
            raise ValueError("HIT requires at least one evidence candidate")
        if self.status == ToolResultStatus.MISS and self.candidates:
            raise ValueError("MISS cannot contain candidates")
        if self.status == ToolResultStatus.ERROR and not self.error_message:
            raise ValueError("ERROR requires error_message")
        return self


class EvidenceActionDecision(StrictModel):
    action_decision_id: str = Field(default_factory=lambda: str(uuid4()))
    action: EvidenceAction
    reason: str = Field(min_length=1)
    query: str | None = None
    based_on_tool_call_count: int = Field(ge=0)
    input_state: dict[str, Any]
    model_version: str
    prompt_version: str
    prompt_path: str | None = None
    prompt_hash: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_query(self) -> "EvidenceActionDecision":
        is_search = self.action in {
            EvidenceAction.SEARCH_GLOSSARY,
            EvidenceAction.SEARCH_OFFICIAL_DOCS,
            EvidenceAction.SEARCH_MEMORY,
        }
        if is_search and not self.query:
            raise ValueError("search actions require query")
        if not is_search and self.query is not None:
            raise ValueError("terminal actions must not include query")
        return self


class AdmittedNormativeClaim(StrictModel):
    source_term: str = Field(min_length=1)
    target_form: str = Field(min_length=1)
    claim_key: str = Field(min_length=1)
    authority: str = Field(min_length=1)
    authority_scope: str = Field(min_length=1)
    target_locale: str = Field(min_length=1)
    scenario: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    claim_scope: str = Field(min_length=1)


class NormativeAdmissionDecision(StrictModel):
    candidate_id: str = Field(min_length=1)
    admitted: bool
    primary_reason_code: NormativeAdmissionReasonCode | None = None
    reason_codes: list[NormativeAdmissionReasonCode] = Field(default_factory=list)
    policy_version: str = Field(min_length=1)
    admitted_claim: AdmittedNormativeClaim | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "NormativeAdmissionDecision":
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes must not contain duplicates")
        if self.admitted:
            if self.primary_reason_code is not None or self.reason_codes:
                raise ValueError("admitted evidence cannot contain rejection reasons")
            if self.admitted_claim is None:
                raise ValueError("admitted evidence requires admitted_claim")
        else:
            if self.primary_reason_code is None or not self.reason_codes:
                raise ValueError("rejected evidence requires rejection reasons")
            if self.primary_reason_code not in self.reason_codes:
                raise ValueError("primary_reason_code must be present in reason_codes")
            if self.admitted_claim is not None:
                raise ValueError("rejected evidence cannot contain admitted_claim")
        return self


class VerifiedEvidence(StrictModel):
    evidence_id: str = Field(default_factory=lambda: str(uuid4()))
    case_id: str
    term_candidate: str
    provenance: EvidenceProvenance
    source_ref: str
    content: str
    claim_key: str
    claim_value: str
    relevance_reason: str
    context_match: bool
    is_official_source: bool = False
    supports_normative_claim: bool = False
    declared_supports_normative_claim: bool | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    admitted_normative_evidence: bool = Field(
        default=False, exclude_if=lambda value: not value
    )
    admission_policy_version: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    admitted_claim: AdmittedNormativeClaim | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_normative_admission(self) -> "VerifiedEvidence":
        if self.admitted_normative_evidence:
            if self.declared_supports_normative_claim is not True:
                raise ValueError(
                    "admitted normative evidence requires a positive source declaration"
                )
            if not self.admission_policy_version or self.admitted_claim is None:
                raise ValueError(
                    "admitted normative evidence requires policy and claim metadata"
                )
        elif self.admitted_claim is not None or self.admission_policy_version is not None:
            raise ValueError(
                "non-admitted evidence cannot contain admission policy or claim metadata"
            )
        return self


class EvidenceCandidateReview(StrictModel):
    """Auditable view of one retrieved candidate after semantic review/admission."""

    candidate_id: str = Field(min_length=1)
    term_candidate: str = Field(min_length=1)
    provenance: EvidenceProvenance
    source_ref: str = Field(min_length=1)
    content: str = Field(min_length=1)
    claim_key: str = Field(min_length=1)
    claim_value: str = Field(min_length=1)
    target_locale: str = Field(min_length=1)
    scenario: str | None = None
    is_official_source: bool = False
    supports_normative_claim: bool = False
    relevant: bool | None = None
    context_match: bool | None = None
    assessment_reason: str | None = None
    admitted: bool | None = None
    admission_reason_codes: list[NormativeAdmissionReasonCode] = Field(
        default_factory=list
    )
    admission_policy_version: str | None = None


class ToolCallRecord(StrictModel):
    tool_call_id: str = Field(default_factory=lambda: str(uuid4()))
    case_id: str
    sequence_number: int = Field(ge=1)
    action_decision_id: str
    action: EvidenceAction
    tool_name: Literal[
        "search_glossary", "search_official_docs", "search_case_memory"
    ]
    query: str
    result_status: ToolResultStatus
    result_summary: str
    decision_reason: str
    input_state: dict[str, Any]
    candidate_reviews: list[EvidenceCandidateReview] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class TerminologyEvidenceState(StrictModel):
    case_id: str
    term_candidate: str
    evidence_need: str
    normative_claim: bool = False
    brand_or_domain: str | None = None
    target_locale: str = "zh-CN"
    context_notes: str | None = None
    source_text: str | None = None
    translation_text: str | None = None
    tools_called: list[str] = Field(default_factory=list)
    verified_evidence: list[VerifiedEvidence] = Field(default_factory=list)
    evidence_status: EvidenceStatus | None = None
    tool_call_count: int = Field(default=0, ge=0)
    max_tool_calls: int = Field(default=4, ge=1)
    # Supplied by the frozen shared evidence environment; this is an execution
    # constraint rather than an agent-selected routing signal.
    available_actions: list[EvidenceAction] = Field(
        default_factory=lambda: [
            EvidenceAction.SEARCH_OFFICIAL_DOCS,
            EvidenceAction.SEARCH_GLOSSARY,
            EvidenceAction.SEARCH_MEMORY,
        ]
    )
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    assessments: list[EvidenceAssessment] = Field(default_factory=list)
    normative_admission_decisions: list[NormativeAdmissionDecision] = Field(
        default_factory=list, exclude_if=lambda value: not value
    )
    action_history: list[EvidenceActionDecision] = Field(default_factory=list)
    stop_reason: str | None = None
    stop_action: EvidenceAction | None = None

    @model_validator(mode="after")
    def counts_match(self) -> "TerminologyEvidenceState":
        allowed_tool_actions = {
            EvidenceAction.SEARCH_OFFICIAL_DOCS,
            EvidenceAction.SEARCH_GLOSSARY,
            EvidenceAction.SEARCH_MEMORY,
        }
        if any(action not in allowed_tool_actions for action in self.available_actions):
            raise ValueError("available_actions may contain tool actions only")
        if len(set(self.available_actions)) != len(self.available_actions):
            raise ValueError("available_actions must not contain duplicates")
        if self.tool_call_count != len(self.tool_calls):
            raise ValueError("tool_call_count must equal len(tool_calls)")
        if self.tool_call_count != len(self.tools_called):
            raise ValueError("tool_call_count must equal len(tools_called)")
        if self.evidence_status is not None and not self.stop_reason:
            raise ValueError("completed evidence state requires stop_reason")
        if self.evidence_status is not None and self.stop_action not in {
            EvidenceAction.STOP_SUFFICIENT,
            EvidenceAction.ABSTAIN,
        }:
            raise ValueError("completed evidence state requires a terminal stop_action")
        if (
            self.evidence_status == EvidenceStatus.SUFFICIENT
            and not self.verified_evidence
        ):
            raise ValueError("SUFFICIENT requires at least one verified evidence item")
        return self


class ReliabilityDecision(StrictModel):
    case_id: str
    dimension: Dimension
    case_risk: RiskLevel
    policy_cell: str
    observed_agreement: float = Field(ge=0, le=1)
    sample_count: int = Field(gt=0)
    source_case_count: int = Field(gt=0)
    severity_support: SeverityCoverage
    verification_route: VerificationRoute
    policy_reason: str
    reliability_policy_id: Literal["reliability_policy_en_zh_v1"] = (
        RELIABILITY_POLICY_ID
    )
    policy_source: str = "pilot_180"
    override_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class RouteDecision(StrictModel):
    case_id: str
    final_policy_route: FinalPolicyRoute
    triggering_dimensions: list[Dimension]
    blocking_dimensions: list[Dimension]
    sample_audit_dimensions: list[Dimension]
    route_reason_codes: list[str]
    aggregation_rule_version: Literal["route_aggregation_v1"] = (
        AGGREGATION_RULE_VERSION
    )
    created_at: datetime = Field(default_factory=utc_now)


class SamplingDecision(StrictModel):
    case_id: str
    sampling_policy_id: Literal["sample_audit_v1"] = "sample_audit_v1"
    eval_run_id: str
    sample_rate: float = Field(default=0.10, gt=0, le=1)
    pool_size: int = Field(ge=0)
    sample_size: int = Field(ge=0)
    selected_for_audit: bool
    sampling_seed: str
    selection_reason: str
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_batch_counts(self) -> "SamplingDecision":
        if self.sample_size > self.pool_size:
            raise ValueError("sample_size cannot exceed pool_size")
        if self.selected_for_audit and self.sample_size == 0:
            raise ValueError("selected_for_audit cannot be true when sample_size is zero")
        return self


class SamplingBatchResult(StrictModel):
    sampling_policy_id: Literal["sample_audit_v1"] = "sample_audit_v1"
    eval_run_id: str
    sample_rate: float = Field(default=0.10, gt=0, le=1)
    pool_size: int = Field(ge=0)
    sample_size: int = Field(ge=0)
    sampling_seed: str
    pool_case_ids: list[str]
    selected_case_ids: list[str]
    decisions: list[SamplingDecision]
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_batch(self) -> "SamplingBatchResult":
        if self.pool_size != len(self.pool_case_ids):
            raise ValueError("pool_size must equal len(pool_case_ids)")
        if self.sample_size != len(self.selected_case_ids):
            raise ValueError("sample_size must equal len(selected_case_ids)")
        if len(self.decisions) != self.pool_size:
            raise ValueError("one SamplingDecision is required per SAMPLE_POOL case")
        if len(set(self.pool_case_ids)) != self.pool_size:
            raise ValueError("pool_case_ids must be unique")
        if not set(self.selected_case_ids).issubset(self.pool_case_ids):
            raise ValueError("selected_case_ids must be a subset of pool_case_ids")
        return self


class HumanReviewResult(StrictModel):
    human_review_id: str = Field(default_factory=lambda: str(uuid4()))
    case_id: str
    review_mode: ReviewMode
    human_terminology_severity: Severity
    human_accuracy_severity: Severity
    human_locale_severity: Severity
    human_audience_severity: Severity
    human_final_disposition: HumanDisposition
    human_corrected_translation: str | None = None
    human_notes: str
    evidence_verdict: EvidenceVerdict | None = None
    reviewer_id: str
    reviewed_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def require_correction_for_edit(self) -> "HumanReviewResult":
        if (
            self.human_final_disposition == HumanDisposition.EDIT_REQUIRED
            and not self.human_corrected_translation
        ):
            raise ValueError(
                "EDIT_REQUIRED requires human_corrected_translation"
            )
        return self


class HumanReviewSubmission(StrictModel):
    review_mode: ReviewMode
    human_terminology_severity: Severity
    human_accuracy_severity: Severity
    human_locale_severity: Severity
    human_audience_severity: Severity
    human_final_disposition: HumanDisposition
    human_corrected_translation: str | None = None
    human_notes: str = ""
    evidence_verdict: EvidenceVerdict | None = None
    reviewer_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_correction_for_edit(self) -> "HumanReviewSubmission":
        if (
            self.human_final_disposition == HumanDisposition.EDIT_REQUIRED
            and not self.human_corrected_translation
        ):
            raise ValueError("EDIT_REQUIRED requires human_corrected_translation")
        return self


class HumanReviewView(StrictModel):
    case_id: str
    review_mode: ReviewMode
    case_payload: dict[str, Any]
    ai_findings: list[dict[str, Any]] | None = None
    verified_evidence: list[dict[str, Any]] | None = None
    route_reason: dict[str, Any] | None = None


class MemoryWriteResult(StrictModel):
    case_id: str
    memory_write_status: MemoryWriteStatus
    memory_id: str | None = None
    eligibility_reason: str
    memory_snapshot_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class CaseClosureResult(StrictModel):
    eval_run_id: str
    case_id: str
    final_policy_route: FinalPolicyRoute
    human_review: HumanReviewResult
    memory_write: MemoryWriteResult
    closed_at: datetime = Field(default_factory=utc_now)


class ProcessingErrorResult(StrictModel):
    case_id: str | None = None
    node_name: str
    error_code: str
    error_message: str
    safe_disposition: Literal["STOP_PROCESSING"] = "STOP_PROCESSING"
    created_at: datetime = Field(default_factory=utc_now)


class WorkflowState(StrictModel):
    eval_run_id: str
    input_payload: ReviewCaseInput | None = None
    review_case: ReviewCase | None = None
    risk_result: RiskResult | None = None
    dimension_evaluations: list[DimensionEvaluation] = Field(default_factory=list)
    post_eval_control: PostEvalControlDecision | None = None
    terminology_evidence: TerminologyEvidenceState | None = None
    reliability_decisions: list[ReliabilityDecision] = Field(default_factory=list)
    route_decision: RouteDecision | None = None
    processing_error: ProcessingErrorResult | None = None
