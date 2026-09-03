"""The three controlled NODE-03 retrieval tools for MVP V1."""

from __future__ import annotations

import sqlite3
import json
from collections.abc import Iterable
from typing import Protocol

from review_triage.schemas import (
    EvidenceCandidate,
    EvidenceProvenance,
    EvidenceToolResult,
    ToolResultStatus,
)


def _matches(query: str, candidate: EvidenceCandidate) -> bool:
    tokens = [token.casefold() for token in query.split() if token.strip()]
    haystack = " ".join(
        [
            candidate.term_candidate,
            candidate.content,
            candidate.claim_key,
            candidate.claim_value,
            candidate.brand_or_domain or "",
        ]
    ).casefold()
    return bool(tokens) and any(token in haystack for token in tokens)


class EvidenceTools(Protocol):
    def search_glossary(self, query: str) -> EvidenceToolResult: ...

    def search_official_docs(
        self,
        query: str,
        *,
        term_candidate: str | None = None,
    ) -> EvidenceToolResult: ...

    def search_case_memory(self, query: str) -> EvidenceToolResult: ...


class ControlledEvidenceTools:
    """In-process controlled stores; no open-ended browsing is permitted."""

    def __init__(
        self,
        *,
        glossary: Iterable[EvidenceCandidate] = (),
        official_docs: Iterable[EvidenceCandidate] = (),
        case_memory: Iterable[EvidenceCandidate] = (),
    ) -> None:
        self._glossary = self._validate_store(
            glossary, EvidenceProvenance.GLOSSARY, "glossary"
        )
        self._official_docs = self._validate_store(
            official_docs, EvidenceProvenance.OFFICIAL_DOCS, "official docs"
        )
        self._case_memory = self._validate_store(
            case_memory, EvidenceProvenance.CASE_MEMORY, "case memory"
        )

    @staticmethod
    def _validate_store(
        candidates: Iterable[EvidenceCandidate],
        provenance: EvidenceProvenance,
        label: str,
    ) -> tuple[EvidenceCandidate, ...]:
        values = tuple(candidates)
        invalid = [item.candidate_id for item in values if item.provenance != provenance]
        if invalid:
            raise ValueError(f"{label} contains invalid provenance: {invalid}")
        return values

    @staticmethod
    def _search(
        query: str,
        candidates: tuple[EvidenceCandidate, ...],
        *,
        label: str,
    ) -> EvidenceToolResult:
        matches = [candidate for candidate in candidates if _matches(query, candidate)]
        if not matches:
            return EvidenceToolResult(
                status=ToolResultStatus.MISS,
                summary=f"No controlled {label} result matched the query.",
            )
        return EvidenceToolResult(
            status=ToolResultStatus.HIT,
            candidates=matches,
            summary=f"Controlled {label} returned {len(matches)} candidate(s).",
        )

    def search_glossary(self, query: str) -> EvidenceToolResult:
        return self._search(query, self._glossary, label="glossary")

    def search_official_docs(
        self,
        query: str,
        *,
        term_candidate: str | None = None,
    ) -> EvidenceToolResult:
        # Legacy controlled stores remain query-only.  The optional anchor keeps
        # the shared tool boundary compatible with the Demo strict path.
        del term_candidate
        return self._search(query, self._official_docs, label="official docs")

    def search_case_memory(self, query: str) -> EvidenceToolResult:
        return self._search(query, self._case_memory, label="case memory")


class SQLiteCaseMemorySearch:
    """Search only approved case_memory; human_feedback is never queried here."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def search_case_memory(self, query: str) -> EvidenceToolResult:
        rows = self.connection.execute(
            """
            SELECT memory_id, payload_json
            FROM case_memory
            WHERE validation_status = 'HUMAN_VALIDATED'
              AND payload_json LIKE ?
            ORDER BY created_at, memory_id
            """,
            (f"%{query}%",),
        ).fetchall()
        if not rows:
            return EvidenceToolResult(
                status=ToolResultStatus.MISS,
                summary="No approved case_memory row matched the query.",
            )
        candidates = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            candidates.append(
                EvidenceCandidate(
                    candidate_id=row["memory_id"],
                    term_candidate=query,
                    provenance=EvidenceProvenance.CASE_MEMORY,
                    source_ref=f"case_memory://{row['memory_id']}",
                    content=row["payload_json"],
                    claim_key=(
                        str(payload.get("source_text", query)).strip().casefold()
                    ),
                    claim_value=str(payload.get("validated_translation", "")),
                    brand_or_domain=payload.get("brand_or_domain"),
                    target_locale=payload.get("target_locale", "zh-CN"),
                    validation_status="HUMAN_VALIDATED",
                )
            )
        return EvidenceToolResult(
            status=ToolResultStatus.HIT,
            candidates=candidates,
            summary=f"Approved case_memory returned {len(rows)} candidate(s).",
        )
