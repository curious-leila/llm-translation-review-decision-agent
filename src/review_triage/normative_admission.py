"""Deterministic normative-evidence admission for Demo Evidence Pack v1."""

from __future__ import annotations

import json
import re
import unicodedata
from urllib.parse import urlsplit

from review_triage.demo_evidence_pack_v1 import (
    DemoEvidencePackV1,
    DemoNegativeControlV1,
    DemoPositiveTerminologyFactV1,
    DemoSourceDocumentV1,
)
from review_triage.schemas import (
    AdmittedNormativeClaim,
    EvidenceAssessmentItem,
    EvidenceCandidate,
    EvidenceProvenance,
    NormativeAdmissionDecision,
    NormativeAdmissionReasonCode,
    TerminologyEvidenceState,
)


DEMO_NORMATIVE_ADMISSION_V1 = "demo_normative_admission_v1"

_REASON_ORDER = (
    NormativeAdmissionReasonCode.ASSESSOR_REJECTED,
    NormativeAdmissionReasonCode.SOURCE_NOT_ADMISSIBLE,
    NormativeAdmissionReasonCode.NORMATIVE_SUPPORT_UNDECLARED,
    NormativeAdmissionReasonCode.TERM_MISMATCH,
    NormativeAdmissionReasonCode.TERM_PAIR_NOT_ATTESTED,
    NormativeAdmissionReasonCode.LOCALE_SCOPE_MISMATCH,
    NormativeAdmissionReasonCode.AUTHORITY_SCOPE_MISMATCH,
    NormativeAdmissionReasonCode.CLAIM_SCOPE_INVALID,
)

_ALLOWED_CLAIM_KEYS = frozenset(
    {
        "official_chinese_brand_form",
        "official_payment_status_term",
        "official_product_category_name",
        "official_product_feature_name",
        "official_product_navigation_name",
        "official_project_navigation_name",
        "official_ui_action_mapping",
        "official_ui_term_mapping",
    }
)

_ALLOWED_ALIGNMENTS = frozenset(
    {
        "locale_equivalent_navigation_item",
        "locale_equivalent_official_homepage",
        "locale_equivalent_product_page_section",
        "same_article_id_locale_equivalent_page",
        "same_article_id_locale_equivalent_step",
        "same_key_same_git_commit",
    }
)

_AUTHORITY_CONTEXT_ALIASES = {
    "Signal Android UI": frozenset(
        {
            "signal",
            "signal.org",
            "signalapp.org",
            "signalapp",
            "github.com/signalapp/signal-android",
        }
    ),
    "PayPal customer support": frozenset(
        {"paypal", "paypal.com"}
    ),
    "Lenzing / TENCEL marketing": frozenset(
        {"lenzing", "lenzing.com", "tencel", "tencel.com"}
    ),
}

# This is the entire Demo v1 term-owner exception. It is deliberately not a
# general publisher/owner graph: these four frozen TENCEL facts may use the
# registered Lenzing/TENCEL authority even when the case publisher differs.
_TERM_OWNER_FACT_IDS = frozenset({"TEN-01", "TEN-02", "TEN-03", "TEN-04"})
_TENCEL_AUTHORITIES = frozenset(
    {"Lenzing AG / TENCEL™", "Lenzing Aktiengesellschaft"}
)

_DISPLAY_QUALIFIER = re.compile(
    r"\s*\(\s*(?:brand\s+name|brand|品牌名|品牌词)\s*\)\s*$",
    flags=re.IGNORECASE,
)
_OUTER_QUOTES = "\"'“”‘’«»「」『』"
_TRADEMARK_MARKS = str.maketrans("", "", "™®")


def normalize_demo_term_v1(value: str) -> str:
    """Apply only the display-level normalization approved for Demo v1."""

    text = value.translate(_TRADEMARK_MARKS)
    text = unicodedata.normalize("NFKC", text).strip().strip(_OUTER_QUOTES).strip()
    text = _DISPLAY_QUALIFIER.sub("", text).strip()
    text = " ".join(text.split())
    return text.casefold()


def _canonical_candidate_content(fact: DemoPositiveTerminologyFactV1) -> str:
    return json.dumps(
        {
            "authority_scope": fact.authority_scope,
            "supporting_excerpt": dict(fact.supporting_excerpt),
            "claim_scope": fact.claim_scope,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _attestation_text(value: str) -> str:
    text = value.translate(_TRADEMARK_MARKS)
    text = unicodedata.normalize("NFKC", text)
    return " ".join(text.split()).casefold()


def _contains_attested_form(excerpt: str, form: str) -> bool:
    haystack = _attestation_text(excerpt)
    needle = _attestation_text(form)
    if not needle:
        return False
    if needle[0].isascii() and needle[0].isalnum() and needle[-1].isalnum():
        return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None
    return needle in haystack


def _context_authority_tokens(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    text = unicodedata.normalize("NFKC", value).strip().casefold().rstrip("/")
    if not text:
        return frozenset()
    parsed = urlsplit(text if "://" in text else f"//{text}")
    host = (parsed.hostname or "").removeprefix("www.")
    raw = text.split("?", 1)[0].split("#", 1)[0]
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    raw = raw.removeprefix("www.").rstrip("/")
    return frozenset(item for item in {raw, host} if item)


class DemoNormativeAdmissionV1:
    """Admit only frozen Demo v1 facts that pass every deterministic gate."""

    policy_version = DEMO_NORMATIVE_ADMISSION_V1

    def __init__(self, pack: DemoEvidencePackV1) -> None:
        self.pack = pack
        self._facts = {fact.fact_id: fact for fact in pack.positive_facts}
        self._controls = {
            control.control_id: control for control in pack.negative_controls
        }
        self._sources = {
            source.source_ref: source for source in pack.source_documents
        }

    def admit(
        self,
        *,
        state: TerminologyEvidenceState,
        candidate: EvidenceCandidate,
        assessment: EvidenceAssessmentItem,
    ) -> NormativeAdmissionDecision:
        failures: set[NormativeAdmissionReasonCode] = set()
        fact = self._facts.get(candidate.candidate_id)
        control = self._controls.get(candidate.candidate_id)
        source = self._sources.get(candidate.source_ref)

        if (
            assessment.candidate_id != candidate.candidate_id
            or not assessment.relevant
            or not assessment.context_match
        ):
            failures.add(NormativeAdmissionReasonCode.ASSESSOR_REJECTED)

        if not self._source_is_admissible(candidate, fact, control, source):
            failures.add(NormativeAdmissionReasonCode.SOURCE_NOT_ADMISSIBLE)

        if not candidate.supports_normative_claim:
            failures.add(
                NormativeAdmissionReasonCode.NORMATIVE_SUPPORT_UNDECLARED
            )

        registered_source_term = (
            fact.source_term if fact is not None else control.source_term if control else None
        )
        if registered_source_term is not None and (
            normalize_demo_term_v1(state.term_candidate)
            != normalize_demo_term_v1(registered_source_term)
        ):
            failures.add(NormativeAdmissionReasonCode.TERM_MISMATCH)

        if fact is None or not self._term_pair_is_attested(candidate, fact):
            failures.add(NormativeAdmissionReasonCode.TERM_PAIR_NOT_ATTESTED)

        if fact is not None and not self._locale_is_allowed(state, candidate, fact):
            failures.add(NormativeAdmissionReasonCode.LOCALE_SCOPE_MISMATCH)

        if (
            fact is not None
            and source is not None
            and not self._authority_is_allowed(state, fact, source)
        ):
            failures.add(NormativeAdmissionReasonCode.AUTHORITY_SCOPE_MISMATCH)

        if fact is None or not self._claim_scope_is_valid(candidate, fact):
            failures.add(NormativeAdmissionReasonCode.CLAIM_SCOPE_INVALID)

        ordered = [code for code in _REASON_ORDER if code in failures]
        if ordered:
            return NormativeAdmissionDecision(
                candidate_id=candidate.candidate_id,
                admitted=False,
                primary_reason_code=ordered[0],
                reason_codes=ordered,
                policy_version=self.policy_version,
            )

        assert fact is not None and source is not None
        return NormativeAdmissionDecision(
            candidate_id=candidate.candidate_id,
            admitted=True,
            primary_reason_code=None,
            reason_codes=[],
            policy_version=self.policy_version,
            admitted_claim=AdmittedNormativeClaim(
                source_term=fact.source_term,
                target_form=fact.target_form,
                claim_key=fact.claim_key,
                authority=source.authority,
                authority_scope=fact.authority_scope,
                target_locale=fact.locale_scope.target,
                scenario=fact.scenario,
                source_ref=fact.source_ref,
                claim_scope=fact.claim_scope,
            ),
        )

    def _source_is_admissible(
        self,
        candidate: EvidenceCandidate,
        fact: DemoPositiveTerminologyFactV1 | None,
        control: DemoNegativeControlV1 | None,
        source: DemoSourceDocumentV1 | None,
    ) -> bool:
        expected_ref = (
            fact.source_ref if fact is not None else control.source_ref if control else None
        )
        return (
            candidate.provenance == EvidenceProvenance.OFFICIAL_DOCS
            and candidate.is_official_source
            and source is not None
            and (expected_ref is None or candidate.source_ref == expected_ref)
        )

    def _term_pair_is_attested(
        self,
        candidate: EvidenceCandidate,
        fact: DemoPositiveTerminologyFactV1,
    ) -> bool:
        source_excerpt = fact.supporting_excerpt.get("source")
        target_excerpt = fact.supporting_excerpt.get("target")
        alignment = fact.excerpt_location.get("alignment")
        refs_resolve = all(
            source_ref in self._sources for source_ref in fact.supporting_source_refs
        )
        return bool(
            normalize_demo_term_v1(candidate.term_candidate)
            == normalize_demo_term_v1(fact.source_term)
            and candidate.claim_value == fact.claim_value
            and candidate.content == _canonical_candidate_content(fact)
            and source_excerpt
            and target_excerpt
            and _contains_attested_form(source_excerpt, fact.source_term)
            and _contains_attested_form(target_excerpt, fact.target_form)
            and alignment in _ALLOWED_ALIGNMENTS
            and refs_resolve
        )

    @staticmethod
    def _locale_is_allowed(
        state: TerminologyEvidenceState,
        candidate: EvidenceCandidate,
        fact: DemoPositiveTerminologyFactV1,
    ) -> bool:
        case_locale = state.target_locale.casefold()
        evidence_locale = fact.locale_scope.target.casefold()
        if candidate.target_locale != fact.locale_scope.target:
            return False
        if case_locale == evidence_locale:
            return True
        return (
            case_locale == "zh-cn"
            and (
                (
                    fact.evidence_family == "Signal Android UI"
                    and fact.scenario == "UI"
                    and evidence_locale == "zh-rcn"
                )
                or (
                    fact.evidence_family == "PayPal customer support"
                    and fact.scenario == "CUSTOMER_SUPPORT"
                    and evidence_locale in {"zh_c2", "zh_us"}
                )
            )
        )

    @staticmethod
    def _authority_is_allowed(
        state: TerminologyEvidenceState,
        fact: DemoPositiveTerminologyFactV1,
        source: DemoSourceDocumentV1,
    ) -> bool:
        aliases = _AUTHORITY_CONTEXT_ALIASES.get(fact.evidence_family, frozenset())
        if _context_authority_tokens(state.brand_or_domain) & aliases:
            return True
        return (
            fact.fact_id in _TERM_OWNER_FACT_IDS
            and source.authority in _TENCEL_AUTHORITIES
        )

    @staticmethod
    def _claim_scope_is_valid(
        candidate: EvidenceCandidate,
        fact: DemoPositiveTerminologyFactV1,
    ) -> bool:
        return bool(
            fact.claim_key in _ALLOWED_CLAIM_KEYS
            and candidate.claim_key == fact.claim_key
            and candidate.claim_value == fact.claim_value
            and candidate.scenario == fact.scenario
            and fact.authority_scope
            and fact.claim_scope
            and fact.target_form
        )
