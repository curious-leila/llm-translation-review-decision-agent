"""NODE-08 deterministic Human-validated case-memory gate."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from review_triage.persistence import SQLiteRepository
from review_triage.schemas import (
    EvidenceProvenance,
    HumanDisposition,
    HumanReviewResult,
    MemoryWriteResult,
    MemoryWriteStatus,
    ReviewCase,
    TerminologyEvidenceState,
)


MEMORY_VERSION = "case_memory_v1"
VALIDATION_STATUS = "HUMAN_VALIDATED"
EVIDENCE_BASIS = "HUMAN_VALIDATED_CASE"


def _stable_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _conflict_identity(review_case: ReviewCase) -> dict[str, Any]:
    return {
        "source_text": review_case.source_text,
        "original_translation": review_case.translation,
        "content_type": review_case.content_type.value,
        "brand_or_domain": review_case.brand_or_domain,
        "source_language": review_case.source_language,
        "target_locale": review_case.target_locale,
    }


def _validated_translation(
    review_case: ReviewCase, human_result: HumanReviewResult
) -> str | None:
    if human_result.human_final_disposition == HumanDisposition.APPROVE_AS_IS:
        return review_case.translation
    if human_result.human_final_disposition == HumanDisposition.EDIT_REQUIRED:
        return human_result.human_corrected_translation
    return None


def _result(
    *,
    case_id: str,
    status: MemoryWriteStatus,
    reason: str,
    memory_id: str | None = None,
    memory_snapshot_id: str | None = None,
) -> MemoryWriteResult:
    return MemoryWriteResult(
        case_id=case_id,
        memory_write_status=status,
        memory_id=memory_id,
        eligibility_reason=reason,
        memory_snapshot_id=memory_snapshot_id,
    )


def node_08_write_memory(
    *,
    eval_run_id: str,
    review_case: ReviewCase,
    human_result: HumanReviewResult,
    repository: SQLiteRepository,
    memory_write_allowed: bool,
    is_frozen_holdout: bool,
    memory_snapshot_id: str | None = None,
    terminology_evidence: TerminologyEvidenceState | None = None,
) -> MemoryWriteResult:
    """Write only eligible Human-validated case-level memory."""

    if is_frozen_holdout:
        result = _result(
            case_id=review_case.case_id,
            status=MemoryWriteStatus.BLOCKED_EVAL_FREEZE,
            reason="Frozen Holdout forbids current Human results from searchable Memory.",
            memory_snapshot_id=memory_snapshot_id,
        )
        _log_result(
            eval_run_id,
            result,
            repository,
            input_state={
                "is_frozen_holdout": is_frozen_holdout,
                "memory_write_allowed": memory_write_allowed,
                "human_review_id": human_result.human_review_id,
                "human_final_disposition": human_result.human_final_disposition,
            },
        )
        return result
    if not memory_write_allowed:
        result = _result(
            case_id=review_case.case_id,
            status=MemoryWriteStatus.SKIPPED_NOT_ELIGIBLE,
            reason="memory_write_allowed is false.",
            memory_snapshot_id=memory_snapshot_id,
        )
        _log_result(
            eval_run_id,
            result,
            repository,
            input_state={
                "is_frozen_holdout": is_frozen_holdout,
                "memory_write_allowed": memory_write_allowed,
                "human_review_id": human_result.human_review_id,
                "human_final_disposition": human_result.human_final_disposition,
            },
        )
        return result
    if human_result.case_id != review_case.case_id:
        result = _result(
            case_id=review_case.case_id,
            status=MemoryWriteStatus.SKIPPED_NOT_ELIGIBLE,
            reason="Human result and ReviewCase identity do not match.",
            memory_snapshot_id=memory_snapshot_id,
        )
        _log_result(
            eval_run_id,
            result,
            repository,
            input_state={
                "case_identity_matches": False,
                "human_review_id": human_result.human_review_id,
            },
        )
        return result
    if not repository.has_human_feedback(
        human_result.human_review_id, review_case.case_id
    ):
        result = _result(
            case_id=review_case.case_id,
            status=MemoryWriteStatus.SKIPPED_NOT_ELIGIBLE,
            reason="Human Review has not been persisted to human_feedback.",
            memory_snapshot_id=memory_snapshot_id,
        )
        _log_result(
            eval_run_id,
            result,
            repository,
            input_state={
                "human_feedback_persisted": False,
                "human_review_id": human_result.human_review_id,
            },
        )
        return result
    validated_translation = _validated_translation(review_case, human_result)
    if validated_translation is None:
        reason = (
            "UNRESOLVED Human result cannot become searchable Memory."
            if human_result.human_final_disposition == HumanDisposition.UNRESOLVED
            else "EDIT_REQUIRED is missing human_corrected_translation."
        )
        result = _result(
            case_id=review_case.case_id,
            status=MemoryWriteStatus.SKIPPED_NOT_ELIGIBLE,
            reason=reason,
            memory_snapshot_id=memory_snapshot_id,
        )
        _log_result(
            eval_run_id,
            result,
            repository,
            input_state={
                "human_feedback_persisted": True,
                "human_final_disposition": human_result.human_final_disposition,
                "has_corrected_translation": bool(
                    human_result.human_corrected_translation
                ),
            },
        )
        return result

    official_refs = []
    if terminology_evidence is not None:
        official_refs = [
            item.source_ref
            for item in terminology_evidence.verified_evidence
            if item.is_official_source
            and item.provenance != EvidenceProvenance.CASE_MEMORY
        ]
    conflict_identity = _conflict_identity(review_case)
    conflict_key = _stable_digest(conflict_identity)
    fingerprint_payload = {
        **conflict_identity,
        "validated_translation": validated_translation,
        "human_terminology_severity": human_result.human_terminology_severity.value,
        "human_accuracy_severity": human_result.human_accuracy_severity.value,
        "human_locale_severity": human_result.human_locale_severity.value,
        "human_audience_severity": human_result.human_audience_severity.value,
        "human_final_disposition": human_result.human_final_disposition.value,
    }
    case_fingerprint = _stable_digest(fingerprint_payload)
    existing_duplicate = repository.find_memory_by_fingerprint(case_fingerprint)
    if existing_duplicate is not None:
        result = _result(
            case_id=review_case.case_id,
            status=MemoryWriteStatus.SKIPPED_DUPLICATE,
            reason="Exact Human-validated case memory already exists.",
            memory_id=existing_duplicate["memory_id"],
            memory_snapshot_id=existing_duplicate["memory_snapshot_id"],
        )
        _log_result(
            eval_run_id,
            result,
            repository,
            input_state={
                "case_fingerprint": case_fingerprint,
                "duplicate_found": True,
            },
        )
        return result

    memory_id = str(uuid4())
    conflicts = []
    for row in repository.find_memories_by_conflict_key(conflict_key):
        existing_payload = json.loads(row["payload_json"])
        if existing_payload.get("validated_translation") != validated_translation:
            conflicts.append((str(uuid4()), row["memory_id"]))
    payload = {
        "memory_id": memory_id,
        "source_case_id": review_case.case_id,
        "origin_human_review_id": human_result.human_review_id,
        "case_fingerprint": case_fingerprint,
        "source_text": review_case.source_text,
        "original_translation": review_case.translation,
        "validated_translation": validated_translation,
        "content_type": review_case.content_type.value,
        "brand_or_domain": review_case.brand_or_domain,
        "source_language": review_case.source_language,
        "target_locale": review_case.target_locale,
        "human_terminology_severity": human_result.human_terminology_severity.value,
        "human_accuracy_severity": human_result.human_accuracy_severity.value,
        "human_locale_severity": human_result.human_locale_severity.value,
        "human_audience_severity": human_result.human_audience_severity.value,
        "human_final_disposition": human_result.human_final_disposition.value,
        "validated_terms": [],
        "evidence_basis": EVIDENCE_BASIS,
        "verified_evidence_refs": official_refs,
        "validation_status": VALIDATION_STATUS,
        "memory_version": MEMORY_VERSION,
        "memory_snapshot_id": memory_snapshot_id,
        "conflict_detected": bool(conflicts),
    }
    repository.write_case_memory(
        memory_id=memory_id,
        source_case_id=review_case.case_id,
        origin_human_review_id=human_result.human_review_id,
        case_fingerprint=case_fingerprint,
        conflict_key=conflict_key,
        payload=payload,
        memory_snapshot_id=memory_snapshot_id,
        conflicts=conflicts,
    )
    result = _result(
        case_id=review_case.case_id,
        status=MemoryWriteStatus.WRITTEN,
        reason=(
            "Eligible Human-validated case written; conflicting historical solution "
            "preserved and linked."
            if conflicts
            else "Eligible Human-validated case written."
        ),
        memory_id=memory_id,
        memory_snapshot_id=memory_snapshot_id,
    )
    _log_result(
        eval_run_id,
        result,
        repository,
        input_state={
            "case_fingerprint": case_fingerprint,
            "conflict_key": conflict_key,
            "conflict_count": len(conflicts),
            "human_feedback_persisted": True,
            "memory_write_allowed": memory_write_allowed,
            "is_frozen_holdout": is_frozen_holdout,
        },
    )
    return result


def _log_result(
    eval_run_id: str,
    result: MemoryWriteResult,
    repository: SQLiteRepository,
    *,
    input_state: dict[str, Any],
) -> None:
    repository.log_node(
        eval_run_id=eval_run_id,
        case_id=result.case_id,
        node_name="NODE-08",
        input_state={"memory_write_gate_evaluated": True, **input_state},
        output_state=result,
        decision_reason=result.eligibility_reason,
        reason_code=result.memory_write_status.value,
        policy_version="case_memory_v1",
    )
