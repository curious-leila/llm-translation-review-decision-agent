"""SQLite persistence and structured audit logging for MVP V1."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel

from review_triage.schemas import (
    DimensionEvaluation,
    HumanReviewResult,
    ProcessingErrorResult,
    ReliabilityDecision,
    ReviewCase,
    RiskResult,
    RouteDecision,
    SamplingBatchResult,
    SamplingDecision,
    TerminologyEvidenceState,
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    def encode(item: Any) -> Any:
        if isinstance(item, BaseModel):
            return encode(item.model_dump(mode="json"))
        if isinstance(item, dict):
            return {str(key): encode(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [encode(child) for child in item]
        return item

    return json.dumps(encode(value), ensure_ascii=False, default=str, sort_keys=True)


class SQLiteRepository:
    """Small explicit repository; SQLite rows remain inspectable without an ORM."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLiteRepository":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _initialize_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS eval_runs (
                eval_run_id TEXT PRIMARY KEY,
                run_mode TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                error_json TEXT
            );

            CREATE TABLE IF NOT EXISTS review_cases (
                case_id TEXT PRIMARY KEY,
                eval_run_id TEXT NOT NULL,
                source_text TEXT NOT NULL,
                translation TEXT NOT NULL,
                content_type TEXT NOT NULL,
                brand_or_domain TEXT,
                context_notes TEXT,
                source_language TEXT NOT NULL,
                target_locale TEXT NOT NULL,
                reliability_policy_id TEXT NOT NULL,
                processing_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (eval_run_id) REFERENCES eval_runs(eval_run_id)
            );

            CREATE TABLE IF NOT EXISTS risk_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                risk_factors_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                missing_context_fields_json TEXT NOT NULL,
                clarification_question TEXT,
                model_version TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                prompt_path TEXT,
                prompt_hash TEXT,
                llm_run_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES review_cases(case_id)
            );

            CREATE TABLE IF NOT EXISTS dimension_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                dimension TEXT NOT NULL,
                severity TEXT NOT NULL,
                q1 TEXT NOT NULL,
                q2 TEXT NOT NULL,
                notes TEXT NOT NULL,
                model_reported_sources_json TEXT NOT NULL,
                dimension_specific_json TEXT NOT NULL,
                requires_external_evidence INTEGER NOT NULL,
                unresolved_external_support INTEGER NOT NULL,
                model_version TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                prompt_path TEXT,
                prompt_hash TEXT,
                llm_run_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES review_cases(case_id),
                UNIQUE(case_id, dimension, llm_run_id)
            );

            CREATE TABLE IF NOT EXISTS tool_calls (
                tool_call_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                sequence_number INTEGER NOT NULL,
                action_decision_id TEXT NOT NULL,
                action TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                query TEXT NOT NULL,
                result_status TEXT NOT NULL,
                result_summary TEXT NOT NULL,
                decision_reason TEXT NOT NULL,
                input_state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES review_cases(case_id)
            );

            CREATE TABLE IF NOT EXISTS evidence_action_decisions (
                action_decision_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                sequence_number INTEGER NOT NULL,
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                query TEXT,
                based_on_tool_call_count INTEGER NOT NULL,
                input_state_json TEXT NOT NULL,
                model_version TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                prompt_path TEXT,
                prompt_hash TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES review_cases(case_id)
            );

            CREATE TABLE IF NOT EXISTS evidence_assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                sequence_number INTEGER NOT NULL,
                assessments_json TEXT NOT NULL,
                model_version TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                prompt_path TEXT,
                prompt_hash TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES review_cases(case_id)
            );

            CREATE TABLE IF NOT EXISTS verified_evidence (
                evidence_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                term_candidate TEXT NOT NULL,
                provenance TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                content TEXT NOT NULL,
                claim_key TEXT NOT NULL,
                claim_value TEXT NOT NULL,
                relevance_reason TEXT NOT NULL,
                context_match INTEGER NOT NULL,
                is_official_source INTEGER NOT NULL,
                supports_normative_claim INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES review_cases(case_id)
            );

            CREATE TABLE IF NOT EXISTS terminology_evidence_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL UNIQUE,
                term_candidate TEXT NOT NULL,
                evidence_need TEXT NOT NULL,
                normative_claim INTEGER NOT NULL,
                evidence_status TEXT NOT NULL,
                tool_call_count INTEGER NOT NULL,
                max_tool_calls INTEGER NOT NULL,
                tools_called_json TEXT NOT NULL,
                stop_action TEXT NOT NULL,
                stop_reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES review_cases(case_id)
            );

            CREATE TABLE IF NOT EXISTS reliability_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                dimension TEXT NOT NULL,
                case_risk TEXT NOT NULL,
                policy_cell TEXT NOT NULL,
                observed_agreement REAL NOT NULL,
                sample_count INTEGER NOT NULL,
                source_case_count INTEGER NOT NULL,
                severity_support TEXT NOT NULL,
                verification_route TEXT NOT NULL,
                policy_reason TEXT NOT NULL,
                reliability_policy_id TEXT NOT NULL,
                policy_source TEXT NOT NULL,
                override_reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES review_cases(case_id),
                UNIQUE(case_id, dimension)
            );

            CREATE TABLE IF NOT EXISTS routing_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL UNIQUE,
                final_policy_route TEXT NOT NULL,
                triggering_dimensions_json TEXT NOT NULL,
                blocking_dimensions_json TEXT NOT NULL,
                sample_audit_dimensions_json TEXT NOT NULL,
                route_reason_codes_json TEXT NOT NULL,
                aggregation_rule_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES review_cases(case_id)
            );

            CREATE TABLE IF NOT EXISTS sampling_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                sampling_policy_id TEXT NOT NULL,
                eval_run_id TEXT NOT NULL,
                sample_rate REAL NOT NULL,
                pool_size INTEGER NOT NULL,
                sample_size INTEGER NOT NULL,
                selected_for_audit INTEGER NOT NULL,
                sampling_seed TEXT NOT NULL,
                selection_reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(eval_run_id, case_id, sampling_policy_id)
            );

            CREATE TABLE IF NOT EXISTS human_feedback (
                human_review_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                reviewed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS case_memory (
                memory_id TEXT PRIMARY KEY,
                source_case_id TEXT NOT NULL,
                origin_human_review_id TEXT NOT NULL,
                case_fingerprint TEXT NOT NULL,
                conflict_key TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                validation_status TEXT NOT NULL,
                memory_snapshot_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(case_fingerprint)
            );

            CREATE TABLE IF NOT EXISTS memory_conflicts (
                conflict_id TEXT PRIMARY KEY,
                conflict_key TEXT NOT NULL,
                existing_memory_id TEXT NOT NULL,
                new_memory_id TEXT NOT NULL,
                conflict_reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (existing_memory_id) REFERENCES case_memory(memory_id),
                FOREIGN KEY (new_memory_id) REFERENCES case_memory(memory_id)
            );

            CREATE TABLE IF NOT EXISTS node_audit_logs (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                eval_run_id TEXT NOT NULL,
                case_id TEXT,
                node_name TEXT NOT NULL,
                input_state_json TEXT NOT NULL,
                output_state_json TEXT NOT NULL,
                decision_reason TEXT NOT NULL,
                reason_code TEXT,
                policy_version TEXT,
                model_version TEXT,
                prompt_version TEXT,
                prompt_path TEXT,
                prompt_hash TEXT,
                tool_name TEXT,
                tool_result_status TEXT,
                tool_call_count INTEGER,
                evidence_status TEXT,
                stop_reason TEXT,
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS day2_run_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                eval_run_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                baseline_id TEXT NOT NULL,
                final_route TEXT NOT NULL,
                actual_human_review INTEGER,
                logical_tool_call_count INTEGER NOT NULL,
                evidence_acquisition_triggered INTEGER NOT NULL,
                system_terminology_evidence_verdict TEXT,
                first_resolution_tool_call_index INTEGER,
                budget_exhausted INTEGER NOT NULL,
                memory_search_executed INTEGER NOT NULL,
                validated_memory_admitted_used INTEGER NOT NULL,
                trajectory_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(eval_run_id, case_id),
                FOREIGN KEY (eval_run_id) REFERENCES eval_runs(eval_run_id),
                FOREIGN KEY (case_id) REFERENCES review_cases(case_id)
            );
            """
        )
        self._ensure_column("dimension_evaluations", "prompt_path", "TEXT")
        self._ensure_column("dimension_evaluations", "prompt_hash", "TEXT")
        self._ensure_column("risk_results", "prompt_path", "TEXT")
        self._ensure_column("risk_results", "prompt_hash", "TEXT")
        self._ensure_column("evidence_action_decisions", "prompt_path", "TEXT")
        self._ensure_column("evidence_action_decisions", "prompt_hash", "TEXT")
        self._ensure_column("node_audit_logs", "prompt_path", "TEXT")
        self._ensure_column("node_audit_logs", "prompt_hash", "TEXT")
        self.connection.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        """Apply the small additive metadata migration to existing local DBs."""

        existing = {
            row["name"]
            for row in self.connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in existing:
            self.connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    def start_eval_run(self, eval_run_id: str, run_mode: str = "DEVELOPMENT") -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO eval_runs VALUES (?, ?, ?, ?, NULL, NULL)",
                (eval_run_id, run_mode, "RUNNING", _utc_iso()),
            )

    def finish_eval_run(
        self,
        eval_run_id: str,
        *,
        status: str,
        error: ProcessingErrorResult | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE eval_runs SET status=?, completed_at=?, error_json=? "
                "WHERE eval_run_id=?",
                (status, _utc_iso(), _json(error) if error else None, eval_run_id),
            )

    def save_review_case(self, eval_run_id: str, case: ReviewCase) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO review_cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    eval_run_id,
                    case.source_text,
                    case.translation,
                    case.content_type.value,
                    case.brand_or_domain,
                    case.context_notes,
                    case.source_language,
                    case.target_locale,
                    case.reliability_policy_id,
                    case.processing_status.value,
                    case.created_at.isoformat(),
                ),
            )

    def update_case_status(self, case_id: str, status: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE review_cases SET processing_status=? WHERE case_id=?",
                (status, case_id),
            )

    def save_risk_result(self, result: RiskResult) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO risk_results (
                    case_id, risk_level, risk_factors_json, reason,
                    missing_context_fields_json, clarification_question,
                    model_version, prompt_version, prompt_path, prompt_hash,
                    llm_run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.case_id,
                    result.risk_level.value,
                    _json(result.risk_factors),
                    result.reason,
                    _json(result.missing_context_fields),
                    result.clarification_question,
                    result.model_version,
                    result.prompt_version,
                    result.prompt_path,
                    result.prompt_hash,
                    result.llm_run_id,
                    result.created_at.isoformat(),
                ),
            )

    def save_dimension_evaluations(
        self, evaluations: Iterable[DimensionEvaluation]
    ) -> None:
        rows = [
            (
                item.case_id,
                item.dimension.value,
                item.severity.value,
                item.q1,
                item.q2,
                item.notes,
                _json(item.model_reported_sources),
                _json(item.dimension_specific),
                int(item.requires_external_evidence),
                int(item.unresolved_external_support),
                item.model_version,
                item.prompt_version,
                item.prompt_path,
                item.prompt_hash,
                item.llm_run_id,
                item.created_at.isoformat(),
            )
            for item in evaluations
        ]
        with self.connection:
            self.connection.executemany(
                """
                INSERT INTO dimension_evaluations (
                    case_id, dimension, severity, q1, q2, notes,
                    model_reported_sources_json, dimension_specific_json,
                    requires_external_evidence, unresolved_external_support,
                    model_version, prompt_version, prompt_path, prompt_hash,
                    llm_run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def save_terminology_evidence(
        self, state: TerminologyEvidenceState
    ) -> None:
        if state.evidence_status is None or state.stop_action is None or not state.stop_reason:
            raise ValueError("only completed terminology evidence state can be persisted")
        with self.connection:
            for sequence_number, decision in enumerate(state.action_history, start=1):
                self.connection.execute(
                    """
                    INSERT INTO evidence_action_decisions (
                        action_decision_id, case_id, sequence_number, action,
                        reason, query, based_on_tool_call_count, input_state_json,
                        model_version, prompt_version, prompt_path, prompt_hash,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision.action_decision_id,
                        state.case_id,
                        sequence_number,
                        decision.action.value,
                        decision.reason,
                        decision.query,
                        decision.based_on_tool_call_count,
                        _json(decision.input_state),
                        decision.model_version,
                        decision.prompt_version,
                        decision.prompt_path,
                        decision.prompt_hash,
                        decision.created_at.isoformat(),
                    ),
                )
            for call in state.tool_calls:
                self.connection.execute(
                    """
                    INSERT INTO tool_calls (
                        tool_call_id, case_id, sequence_number, action_decision_id,
                        action, tool_name, query, result_status, result_summary,
                        decision_reason, input_state_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        call.tool_call_id,
                        call.case_id,
                        call.sequence_number,
                        call.action_decision_id,
                        call.action.value,
                        call.tool_name,
                        call.query,
                        call.result_status.value,
                        call.result_summary,
                        call.decision_reason,
                        _json(call.input_state),
                        call.created_at.isoformat(),
                    ),
                )
            for sequence_number, assessment in enumerate(
                state.assessments, start=1
            ):
                self.connection.execute(
                    """
                    INSERT INTO evidence_assessments (
                        case_id, sequence_number, assessments_json,
                        model_version, prompt_version, prompt_path, prompt_hash,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.case_id,
                        sequence_number,
                        _json(assessment.assessments),
                        assessment.model_version,
                        assessment.prompt_version,
                        assessment.prompt_path,
                        assessment.prompt_hash,
                        _utc_iso(),
                    ),
                )
            for evidence in state.verified_evidence:
                self.connection.execute(
                    """
                    INSERT INTO verified_evidence (
                        evidence_id, case_id, term_candidate, provenance,
                        source_ref, content, claim_key, claim_value,
                        relevance_reason, context_match, is_official_source,
                        supports_normative_claim, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evidence.evidence_id,
                        evidence.case_id,
                        evidence.term_candidate,
                        evidence.provenance.value,
                        evidence.source_ref,
                        evidence.content,
                        evidence.claim_key,
                        evidence.claim_value,
                        evidence.relevance_reason,
                        int(evidence.context_match),
                        int(evidence.is_official_source),
                        int(evidence.supports_normative_claim),
                        evidence.created_at.isoformat(),
                    ),
                )
            self.connection.execute(
                """
                INSERT INTO terminology_evidence_runs (
                    case_id, term_candidate, evidence_need, normative_claim,
                    evidence_status, tool_call_count, max_tool_calls,
                    tools_called_json, stop_action, stop_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.case_id,
                    state.term_candidate,
                    state.evidence_need,
                    int(state.normative_claim),
                    state.evidence_status.value,
                    state.tool_call_count,
                    state.max_tool_calls,
                    _json(state.tools_called),
                    state.stop_action.value,
                    state.stop_reason,
                    _utc_iso(),
                ),
            )

    def save_reliability_decisions(
        self, decisions: Iterable[ReliabilityDecision]
    ) -> None:
        rows = [
            (
                item.case_id,
                item.dimension.value,
                item.case_risk.value,
                item.policy_cell,
                item.observed_agreement,
                item.sample_count,
                item.source_case_count,
                item.severity_support.value,
                item.verification_route.value,
                item.policy_reason,
                item.reliability_policy_id,
                item.policy_source,
                item.override_reason,
                item.created_at.isoformat(),
            )
            for item in decisions
        ]
        with self.connection:
            self.connection.executemany(
                """
                INSERT INTO reliability_decisions (
                    case_id, dimension, case_risk, policy_cell,
                    observed_agreement, sample_count, source_case_count,
                    severity_support, verification_route, policy_reason,
                    reliability_policy_id, policy_source, override_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def save_route_decision(self, decision: RouteDecision) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO routing_decisions (
                    case_id, final_policy_route, triggering_dimensions_json,
                    blocking_dimensions_json, sample_audit_dimensions_json,
                    route_reason_codes_json, aggregation_rule_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.case_id,
                    decision.final_policy_route.value,
                    _json([d.value for d in decision.triggering_dimensions]),
                    _json([d.value for d in decision.blocking_dimensions]),
                    _json([d.value for d in decision.sample_audit_dimensions]),
                    _json(decision.route_reason_codes),
                    decision.aggregation_rule_version,
                    decision.created_at.isoformat(),
                ),
            )

    def save_day2_run_metrics(self, metrics: dict[str, Any]) -> None:
        """Persist the minimum frozen Day 2 measurement fields, append-only."""

        actual_human_review = metrics["actual_human_review"]
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO day2_run_metrics (
                    eval_run_id, case_id, baseline_id, final_route,
                    actual_human_review, logical_tool_call_count,
                    evidence_acquisition_triggered,
                    system_terminology_evidence_verdict,
                    first_resolution_tool_call_index, budget_exhausted,
                    memory_search_executed, validated_memory_admitted_used,
                    trajectory_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metrics["eval_run_id"],
                    metrics["case_id"],
                    metrics["baseline_id"],
                    metrics["final_route"],
                    None if actual_human_review is None else int(actual_human_review),
                    metrics["logical_tool_call_count"],
                    int(metrics["evidence_acquisition_triggered"]),
                    metrics["system_terminology_evidence_verdict"],
                    metrics["first_resolution_tool_call_index"],
                    int(metrics["budget_exhausted"]),
                    int(metrics["memory_search_executed"]),
                    int(metrics["validated_memory_admitted_used"]),
                    _json(metrics["trajectory"]),
                    _utc_iso(),
                ),
            )

    def save_sampling_batch(self, result: SamplingBatchResult) -> None:
        rows = [
            (
                item.case_id,
                item.sampling_policy_id,
                item.eval_run_id,
                item.sample_rate,
                item.pool_size,
                item.sample_size,
                int(item.selected_for_audit),
                item.sampling_seed,
                item.selection_reason,
                item.created_at.isoformat(),
            )
            for item in result.decisions
        ]
        with self.connection:
            self.connection.executemany(
                """
                INSERT INTO sampling_decisions (
                    case_id, sampling_policy_id, eval_run_id, sample_rate,
                    pool_size, sample_size, selected_for_audit, sampling_seed,
                    selection_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def realize_day2_sampling(
        self, *, eval_run_id: str, selected_case_ids: set[str]
    ) -> None:
        """Fill the existing actual-human-review field after NODE-06 realization."""

        with self.connection:
            self.connection.execute(
                """
                UPDATE day2_run_metrics
                SET actual_human_review=CASE
                    WHEN final_route='HUMAN_REQUIRED' THEN 1
                    WHEN final_route='AUTO_PASS' THEN 0
                    WHEN final_route='SAMPLE_POOL' AND case_id IN ({}) THEN 1
                    WHEN final_route='SAMPLE_POOL' THEN 0
                    ELSE actual_human_review
                END
                WHERE eval_run_id LIKE ?
                """.format(",".join("?" for _ in selected_case_ids) or "''"),
                (*sorted(selected_case_ids), f"{eval_run_id}%"),
            )

    def save_human_feedback(
        self,
        *,
        result: HumanReviewResult,
        evaluations: Iterable[DimensionEvaluation],
        route: RouteDecision,
        sampling: SamplingDecision | None,
        terminology_evidence: TerminologyEvidenceState | None,
    ) -> None:
        payload = {
            "human_result": result,
            "ai_evaluations": list(evaluations),
            "route_decision": route,
            "sampling_decision": sampling,
            "terminology_evidence": terminology_evidence,
        }
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO human_feedback (
                    human_review_id, case_id, payload_json, reviewed_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    result.human_review_id,
                    result.case_id,
                    _json(payload),
                    result.reviewed_at.isoformat(),
                ),
            )

    def has_human_feedback(self, human_review_id: str, case_id: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM human_feedback WHERE human_review_id=? AND case_id=?",
            (human_review_id, case_id),
        ).fetchone()
        return row is not None

    def find_memory_by_fingerprint(self, case_fingerprint: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM case_memory WHERE case_fingerprint=?",
            (case_fingerprint,),
        ).fetchone()

    def find_memories_by_conflict_key(self, conflict_key: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM case_memory WHERE conflict_key=? ORDER BY created_at, memory_id",
                (conflict_key,),
            ).fetchall()
        )

    def write_case_memory(
        self,
        *,
        memory_id: str,
        source_case_id: str,
        origin_human_review_id: str,
        case_fingerprint: str,
        conflict_key: str,
        payload: dict[str, Any],
        memory_snapshot_id: str | None,
        conflicts: list[tuple[str, str]],
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO case_memory (
                    memory_id, source_case_id, origin_human_review_id,
                    case_fingerprint, conflict_key, payload_json,
                    validation_status, memory_snapshot_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'HUMAN_VALIDATED', ?, ?)
                """,
                (
                    memory_id,
                    source_case_id,
                    origin_human_review_id,
                    case_fingerprint,
                    conflict_key,
                    _json(payload),
                    memory_snapshot_id,
                    _utc_iso(),
                ),
            )
            for conflict_id, existing_memory_id in conflicts:
                self.connection.execute(
                    """
                    INSERT INTO memory_conflicts (
                        conflict_id, conflict_key, existing_memory_id,
                        new_memory_id, conflict_reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        conflict_id,
                        conflict_key,
                        existing_memory_id,
                        memory_id,
                        "Same case/context has a different Human-validated solution.",
                        _utc_iso(),
                    ),
                )

    def log_sampling_batch(self, result: SamplingBatchResult) -> None:
        self.log_node(
            eval_run_id=result.eval_run_id,
            case_id=None,
            node_name="NODE-06",
            input_state={
                "pool_case_ids": result.pool_case_ids,
                "sample_rate": result.sample_rate,
                "sampling_seed": result.sampling_seed,
            },
            output_state=result,
            decision_reason=(
                "Batch-level ceil(pool_size × sample_rate) with stable SHA-256 "
                "ranking; input order is not used."
            ),
            reason_code="STABLE_DETERMINISTIC_SAMPLE",
            policy_version=result.sampling_policy_id,
        )

    def log_node(
        self,
        *,
        eval_run_id: str,
        case_id: str | None,
        node_name: str,
        input_state: Any,
        output_state: Any,
        decision_reason: str,
        reason_code: str | list[str] | None = None,
        policy_version: str | None = None,
        model_version: str | None = None,
        prompt_version: str | None = None,
        prompt_path: str | None = None,
        prompt_hash: str | None = None,
        tool_name: str | None = None,
        tool_result_status: str | None = None,
        tool_call_count: int | None = None,
        evidence_status: str | None = None,
        stop_reason: str | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO node_audit_logs (
                    eval_run_id, case_id, node_name, input_state_json,
                    output_state_json, decision_reason, reason_code,
                    policy_version, model_version, prompt_version, prompt_path,
                    prompt_hash, tool_name, tool_result_status, tool_call_count,
                    evidence_status, stop_reason, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eval_run_id,
                    case_id,
                    node_name,
                    _json(input_state),
                    _json(output_state),
                    decision_reason,
                    _json(reason_code) if isinstance(reason_code, list) else reason_code,
                    policy_version,
                    model_version,
                    prompt_version,
                    prompt_path,
                    prompt_hash,
                    tool_name,
                    tool_result_status,
                    tool_call_count,
                    evidence_status,
                    stop_reason,
                    _utc_iso(),
                ),
            )

    def fetch_all(self, query: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return list(self.connection.execute(query, parameters).fetchall())

    def fetch_evidence_trace(self, case_id: str) -> list[sqlite3.Row]:
        """Return Action(t), its tool result, and the next-action input snapshot."""

        return self.fetch_all(
            """
            SELECT
                decision.sequence_number AS action_sequence,
                decision.action,
                decision.reason AS action_reason,
                decision.based_on_tool_call_count,
                decision.input_state_json AS action_input_state_json,
                call.tool_name,
                call.result_status AS tool_result_status,
                call.result_summary AS tool_result_summary
            FROM evidence_action_decisions AS decision
            LEFT JOIN tool_calls AS call
                ON call.action_decision_id = decision.action_decision_id
            WHERE decision.case_id = ?
            ORDER BY decision.sequence_number
            """,
            (case_id,),
        )
