"""Deterministic source-term anchor resolution for the frozen Demo evidence pack."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from review_triage.demo_evidence_pack_v1 import DemoEvidencePackV1


DEMO_TERM_ANCHOR_RESOLVER_V1 = "demo_term_anchor_resolver_v1"


@dataclass(frozen=True)
class TermAnchorResolution:
    raw_term_candidate: str
    resolved_term_anchor: str | None
    status: Literal["EXACT", "RESOLVED", "AMBIGUOUS", "UNRESOLVED"]
    reason_code: str
    policy_version: str


class TermAnchorResolver(Protocol):
    policy_version: str

    def resolve(
        self,
        *,
        source_text: str,
        term_candidate: str,
    ) -> TermAnchorResolution: ...


def _contains_literal_term(container: str, term: str) -> bool:
    """Match a registered literal span without crossing ASCII word boundaries."""

    if not term:
        return False
    left = r"(?<!\w)" if term[0].isascii() and term[0].isalnum() else ""
    right = r"(?!\w)" if term[-1].isascii() and term[-1].isalnum() else ""
    return re.search(f"{left}{re.escape(term)}{right}", container) is not None


class DemoTermAnchorResolverV1:
    """Resolve a model phrase only to a uniquely registered literal source term.

    Query wording never participates in identity resolution.  A broader model
    phrase may narrow to a registered term only when that exact registered term
    appears in both the model phrase and the case source.  Equal-specificity
    matches fail closed.
    """

    policy_version = DEMO_TERM_ANCHOR_RESOLVER_V1

    def __init__(self, source_terms: Iterable[str]) -> None:
        self._source_terms = tuple(
            sorted(set(source_terms), key=lambda value: (-len(value), value))
        )

    @classmethod
    def from_pack(cls, pack: "DemoEvidencePackV1") -> "DemoTermAnchorResolverV1":
        return cls(fact.source_term for fact in pack.positive_facts)

    def resolve(
        self,
        *,
        source_text: str,
        term_candidate: str,
    ) -> TermAnchorResolution:
        raw = term_candidate.strip()
        exact = [
            term
            for term in self._source_terms
            if raw == term and _contains_literal_term(source_text, term)
        ]
        if len(exact) == 1:
            return TermAnchorResolution(
                raw_term_candidate=raw,
                resolved_term_anchor=exact[0],
                status="EXACT",
                reason_code="REGISTERED_TERM_EXACT_MATCH",
                policy_version=self.policy_version,
            )

        matches = [
            term
            for term in self._source_terms
            if _contains_literal_term(raw, term)
            and _contains_literal_term(source_text, term)
        ]
        if not matches:
            return TermAnchorResolution(
                raw_term_candidate=raw,
                resolved_term_anchor=None,
                status="UNRESOLVED",
                reason_code="NO_REGISTERED_LITERAL_SOURCE_TERM",
                policy_version=self.policy_version,
            )

        longest_length = max(len(term) for term in matches)
        longest = [term for term in matches if len(term) == longest_length]
        if len(longest) != 1:
            return TermAnchorResolution(
                raw_term_candidate=raw,
                resolved_term_anchor=None,
                status="AMBIGUOUS",
                reason_code="MULTIPLE_EQUAL_SPECIFICITY_REGISTERED_TERMS",
                policy_version=self.policy_version,
            )

        return TermAnchorResolution(
            raw_term_candidate=raw,
            resolved_term_anchor=longest[0],
            status="RESOLVED",
            reason_code="UNIQUE_LONGEST_REGISTERED_LITERAL_SUBTERM",
            policy_version=self.policy_version,
        )
