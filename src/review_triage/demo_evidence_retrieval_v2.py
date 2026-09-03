"""Narrow, deterministic retrieval for the frozen Demo Evidence Pack v1.

This module intentionally has no workflow wiring and makes no admission or
evidence-sufficiency decision.  Day2 continues to use ``evidence_tools``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType

from review_triage.demo_evidence_pack_v1 import (
    DemoEvidenceCandidateV1,
    DemoEvidencePackV1,
)
from review_triage.schemas import EvidenceToolResult, ToolResultStatus


# This deliberately small set removes retrieval-intent and scope scaffolding,
# not entity, authority, or terminology identity tokens.  Multi-character
# Chinese phrases remain whole tokens under the intentionally minimal tokenizer,
# so their common joined forms are listed explicitly instead of introducing a
# language segmenter.
RETRIEVAL_INTENT_MODIFIER_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "chinese",
        "for",
        "name",
        "official",
        "or",
        "product",
        "the",
        "to",
        "translation",
        "中文",
        "中文名称",
        "中文译名",
        "中国",
        "品牌名",
        "商标",
        "官方",
        "官方中文名称",
        "官方中文品牌名",
        "官方中文译名",
        "官方译名",
    }
)

# Versioned, auditable authority aliases for query guidance.  Aliases are
# canonicalized, never discarded, and can affect ordering only inside an
# already-established anchor scope.  Keep this intentionally small for the
# frozen Demo retrieval surface.
AUTHORITY_IDENTITY_ALIASES_V1 = MappingProxyType(
    {
        "兰精": "lenzing",
    }
)

_DISPLAY_QUALIFIER_BOUNDARIES = str.maketrans({"™": " ", "®": " "})
_PUNCTUATION = str.maketrans(
    {
        "'": " ",
        "\u2018": " ",
        "\u2019": " ",
        "\u201c": " ",
        "\u201d": " ",
        "-": " ",
        "\u2010": " ",
        "\u2011": " ",
        "\u2012": " ",
        "\u2013": " ",
        "\u2014": " ",
        "\u2015": " ",
        "/": " ",
        "\\": " ",
        ",": " ",
        ".": " ",
        ":": " ",
        ";": " ",
        "(": " ",
        ")": " ",
        "[": " ",
        "]": " ",
        "{": " ",
        "}": " ",
    }
)
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def normalize_demo_retrieval_text(value: str) -> str:
    """Normalize only presentation differences relevant to Demo v2 matching."""

    # Handle display-only trademark qualifiers before NFKC can expand them to
    # the searchable-looking strings ``TM`` and ``R``.  A boundary, rather than
    # deletion, also preserves a structured CJK target-form boundary without
    # adding a language segmenter.
    without_display_qualifiers = value.translate(_DISPLAY_QUALIFIER_BOUNDARIES)
    normalized = (
        unicodedata.normalize("NFKC", without_display_qualifiers)
        .casefold()
        .strip()
    )
    normalized = normalized.translate(_PUNCTUATION)
    return " ".join(normalized.split())


def _tokens(value: str) -> frozenset[str]:
    return frozenset(_token_sequence(value))


def _token_sequence(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(normalize_demo_retrieval_text(value)))


def canonicalize_demo_identity_tokens_v1(query: str) -> frozenset[str]:
    """Return canonical ranking guidance from a natural-language query."""

    return frozenset(
        AUTHORITY_IDENTITY_ALIASES_V1.get(token, token)
        for token in _tokens(query)
        if token not in RETRIEVAL_INTENT_MODIFIER_TOKENS
    )


@dataclass(frozen=True)
class _RetrievalRecord:
    candidate: DemoEvidenceCandidateV1
    source_term: str
    target_form: str
    authority_scope: str
    evidence_family: str
    claim_key: str
    claim_value: str

    @property
    def source_tokens(self) -> frozenset[str]:
        return _tokens(self.source_term)

    @property
    def target_tokens(self) -> frozenset[str]:
        return _tokens(self.target_form)

    @property
    def authority_family_tokens(self) -> frozenset[str]:
        return _tokens(f"{self.authority_scope} {self.evidence_family}")

    @property
    def claim_tokens(self) -> frozenset[str]:
        return _tokens(f"{self.claim_key} {self.claim_value}")

    @property
    def searchable_tokens(self) -> frozenset[str]:
        return self.source_tokens | self.target_tokens | self.authority_family_tokens | self.claim_tokens

    @property
    def source_token_sequence(self) -> tuple[str, ...]:
        return _token_sequence(self.source_term)


class DemoEvidenceRetrievalV2:
    """Explicit retrieval path over only the frozen Demo v1 positive facts."""

    def __init__(self, pack: DemoEvidencePackV1) -> None:
        candidates_by_id = {
            candidate.candidate_id: candidate
            for candidate in pack.positive_evidence_candidates
        }
        self._records = tuple(
            _RetrievalRecord(
                candidate=candidates_by_id[fact.fact_id],
                source_term=fact.source_term,
                target_form=fact.target_form,
                authority_scope=fact.authority_scope,
                evidence_family=fact.evidence_family,
                claim_key=fact.claim_key,
                claim_value=fact.claim_value,
            )
            for fact in pack.positive_facts
        )

    def search_official_docs(
        self,
        query: str,
        *,
        term_candidate: str | None = None,
    ) -> EvidenceToolResult:
        """Return reachable frozen candidates, without judging their admissibility."""

        query_normalized = normalize_demo_retrieval_text(query)
        query_guidance_tokens = canonicalize_demo_identity_tokens_v1(query)
        anchor_text = query if term_candidate is None else term_candidate
        anchor_normalized = normalize_demo_retrieval_text(anchor_text)
        anchors = tuple(
            record
            for record in self._records
            if normalize_demo_retrieval_text(record.source_term) == anchor_normalized
        )
        if not anchors:
            return EvidenceToolResult(
                status=ToolResultStatus.MISS,
                summary="Demo Evidence Pack v1 has no exact registered source-term anchor.",
            )

        matches = [
            record
            for record in self._records
            if any(self._is_in_anchor_scope(record, anchor) for anchor in anchors)
        ]
        anchor_ids = {anchor.candidate.candidate_id for anchor in anchors}
        ordered = sorted(
            matches,
            key=lambda record: self._sort_key(
                record,
                query_normalized,
                query_guidance_tokens,
                record.candidate.candidate_id in anchor_ids,
            ),
        )
        return EvidenceToolResult(
            status=ToolResultStatus.HIT,
            candidates=[record.candidate for record in ordered],
            summary=f"Demo Evidence Pack v1 returned {len(ordered)} candidate(s); retrieval is not admission.",
        )

    @staticmethod
    def _is_in_anchor_scope(
        record: _RetrievalRecord,
        anchor: _RetrievalRecord,
    ) -> bool:
        anchor_tokens = anchor.source_token_sequence
        return (
            record.evidence_family == anchor.evidence_family
            and record.source_token_sequence[: len(anchor_tokens)] == anchor_tokens
        )

    @staticmethod
    def _sort_key(
        record: _RetrievalRecord,
        query_normalized: str,
        query_guidance_tokens: frozenset[str],
        is_exact_anchor: bool,
    ) -> tuple[int, int, int, int, int, str]:
        exact_source = query_normalized == normalize_demo_retrieval_text(record.source_term)
        exact_target = query_normalized == normalize_demo_retrieval_text(record.target_form)
        authority_or_family = bool(
            query_guidance_tokens & record.authority_family_tokens
        )
        coverage = len(query_guidance_tokens & record.searchable_tokens)
        return (
            -int(is_exact_anchor),
            -int(exact_source),
            -int(exact_target),
            -int(authority_or_family),
            -coverage,
            record.candidate.candidate_id,
        )
