from __future__ import annotations

import unittest

from review_triage.demo_evidence_pack_v1 import load_demo_evidence_pack_v1
from review_triage.evidence import TerminologyEvidenceLoop, action_input_state
from review_triage.normative_admission import (
    DEMO_NORMATIVE_ADMISSION_V1,
    DemoNormativeAdmissionV1,
    normalize_demo_term_v1,
)
from review_triage.schemas import (
    EvidenceAction,
    EvidenceActionDecision,
    EvidenceAssessment,
    EvidenceAssessmentItem,
    EvidenceCandidate,
    EvidenceProvenance,
    EvidenceStatus,
    EvidenceToolResult,
    NormativeAdmissionReasonCode,
    TerminologyEvidenceState,
    ToolResultStatus,
)


class _FixedAssessor:
    def __init__(self, *, relevant: bool = True, context_match: bool = True) -> None:
        self.relevant = relevant
        self.context_match = context_match

    def assess(self, *, state, candidates):
        return EvidenceAssessment(
            assessments=[
                EvidenceAssessmentItem(
                    candidate_id=candidate.candidate_id,
                    relevant=self.relevant,
                    context_match=self.context_match,
                    reason="Fixed semantic assessment for deterministic admission tests.",
                )
                for candidate in candidates
            ],
            model_version="fixed-test-assessor",
            prompt_version="fixed-test-assessor-v1",
        )


class _SearchOfficialThenAbstain:
    model_version = "fixed-test-selector"
    prompt_version = "fixed-test-selector-v1"

    def select_action(self, state):
        snapshot = action_input_state(state)
        if state.tool_call_count == 0:
            return EvidenceActionDecision(
                action=EvidenceAction.SEARCH_OFFICIAL_DOCS,
                reason="Inspect the supplied official candidate once.",
                query=state.term_candidate,
                based_on_tool_call_count=state.tool_call_count,
                input_state=snapshot,
                model_version=self.model_version,
                prompt_version=self.prompt_version,
            )
        return EvidenceActionDecision(
            action=EvidenceAction.ABSTAIN,
            reason="No admitted evidence after the deterministic check.",
            query=None,
            based_on_tool_call_count=state.tool_call_count,
            input_state=snapshot,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
        )


class _FixedResultTools:
    def __init__(self, candidate: EvidenceCandidate) -> None:
        self.result = EvidenceToolResult(
            status=ToolResultStatus.HIT,
            candidates=[candidate],
            summary="One supplied candidate.",
        )

    def search_official_docs(
        self,
        query: str,
        *,
        term_candidate: str | None = None,
    ) -> EvidenceToolResult:
        del term_candidate
        return self.result

    def search_glossary(self, query: str) -> EvidenceToolResult:
        return EvidenceToolResult(status=ToolResultStatus.MISS, summary="Not used.")

    def search_case_memory(self, query: str) -> EvidenceToolResult:
        return EvidenceToolResult(status=ToolResultStatus.MISS, summary="Not used.")


class DemoNormativeAdmissionV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pack = load_demo_evidence_pack_v1()
        cls.policy = DemoNormativeAdmissionV1(cls.pack)
        cls.candidates = {
            candidate.candidate_id: candidate
            for candidate in cls.pack.positive_evidence_candidates
        }

    @staticmethod
    def state(
        term_candidate: str,
        *,
        brand_or_domain: str | None,
        target_locale: str = "zh-CN",
    ) -> TerminologyEvidenceState:
        return TerminologyEvidenceState(
            case_id="admission-test-case",
            term_candidate=term_candidate,
            evidence_need="Confirm the narrow official terminology fact.",
            normative_claim=True,
            brand_or_domain=brand_or_domain,
            target_locale=target_locale,
            max_tool_calls=1,
        )

    @staticmethod
    def semantic(
        candidate: EvidenceCandidate,
        *,
        relevant: bool = True,
        context_match: bool = True,
    ) -> EvidenceAssessmentItem:
        return EvidenceAssessmentItem(
            candidate_id=candidate.candidate_id,
            relevant=relevant,
            context_match=context_match,
            reason="Forced semantic result; reason text is not parsed.",
        )

    @staticmethod
    def copy_candidate(candidate: EvidenceCandidate, **updates) -> EvidenceCandidate:
        return EvidenceCandidate.model_validate(
            {**candidate.model_dump(mode="python"), **updates}
        )

    def decide(
        self,
        candidate: EvidenceCandidate,
        state: TerminologyEvidenceState,
        *,
        relevant: bool = True,
        context_match: bool = True,
    ):
        return self.policy.admit(
            state=state,
            candidate=candidate,
            assessment=self.semantic(
                candidate,
                relevant=relevant,
                context_match=context_match,
            ),
        )

    def brooklinen_candidate(self, *, declared: bool = False) -> EvidenceCandidate:
        return EvidenceCandidate(
            candidate_id="NC-A",
            term_candidate="TENCEL™",
            provenance=EvidenceProvenance.OFFICIAL_DOCS,
            source_ref="BROOKLINEN-OFFICIAL-HOME",
            content="Brooklinen official homepage without an aligned Chinese term pair.",
            claim_key="official_chinese_brand_form",
            claim_value="TENCEL™ → 天丝™",
            target_locale="zh-CN",
            scenario="MARKETING_BRAND",
            is_official_source=True,
            supports_normative_claim=declared,
        )

    def test_term_normalization_is_narrow_and_does_not_split_compounds(self) -> None:
        normalized = normalize_demo_term_v1("“TENCEL™ (brand name)”")
        self.assertEqual(normalized, normalize_demo_term_v1("TENCEL"))
        self.assertEqual(normalized, normalize_demo_term_v1(" tencel® "))
        self.assertNotEqual(normalized, normalize_demo_term_v1("TENCEL COOL"))

    def test_tencel_term_owner_fact_is_admitted_for_brooklinen_case(self) -> None:
        candidate = self.candidates["TEN-01"]
        decision = self.decide(
            candidate,
            self.state(
                "“TENCEL™ (brand name)”",
                brand_or_domain="brooklinen.com",
            ),
        )
        self.assertTrue(decision.admitted)
        self.assertEqual(decision.policy_version, DEMO_NORMATIVE_ADMISSION_V1)
        self.assertEqual(decision.reason_codes, [])
        self.assertEqual(decision.admitted_claim.target_form, "天丝™")
        self.assertEqual(decision.admitted_claim.target_locale, "zh-CN")
        self.assertIn("Lenzing", decision.admitted_claim.authority)

    def test_signal_same_key_commit_fact_is_admitted_and_keeps_zh_rcn(self) -> None:
        candidate = self.candidates["SIG-01"]
        decision = self.decide(
            candidate,
            self.state("SAVE", brand_or_domain="signal.org"),
        )
        self.assertTrue(decision.admitted)
        self.assertEqual(decision.admitted_claim.target_form, "保存")
        self.assertEqual(decision.admitted_claim.target_locale, "zh-rCN")

    def test_paypal_approved_help_scope_is_admitted_and_keeps_zh_c2(self) -> None:
        candidate = self.candidates["PP-01"]
        decision = self.decide(
            candidate,
            self.state("pending", brand_or_domain="paypal.com"),
        )
        self.assertTrue(decision.admitted)
        self.assertEqual(decision.admitted_claim.target_form, "待处理")
        self.assertEqual(decision.admitted_claim.target_locale, "zh_C2")

    def test_brooklinen_forced_positive_assessment_is_still_rejected(self) -> None:
        candidate = self.brooklinen_candidate()
        decision = self.decide(
            candidate,
            self.state("TENCEL™", brand_or_domain="brooklinen.com"),
            relevant=True,
            context_match=True,
        )
        self.assertFalse(decision.admitted)
        self.assertEqual(
            decision.primary_reason_code,
            NormativeAdmissionReasonCode.NORMATIVE_SUPPORT_UNDECLARED,
        )
        self.assertIn(
            NormativeAdmissionReasonCode.NORMATIVE_SUPPORT_UNDECLARED,
            decision.reason_codes,
        )
        self.assertIn(
            NormativeAdmissionReasonCode.TERM_PAIR_NOT_ATTESTED,
            decision.reason_codes,
        )

    def test_positive_fact_with_normative_declaration_false_is_rejected(self) -> None:
        candidate = self.copy_candidate(
            self.candidates["TEN-01"], supports_normative_claim=False
        )
        decision = self.decide(
            candidate,
            self.state("TENCEL", brand_or_domain="tencel.com"),
        )
        self.assertFalse(decision.admitted)
        self.assertIn(
            NormativeAdmissionReasonCode.NORMATIVE_SUPPORT_UNDECLARED,
            decision.reason_codes,
        )

    def test_non_demo_provenance_is_rejected(self) -> None:
        candidate = self.copy_candidate(
            self.candidates["TEN-01"],
            provenance=EvidenceProvenance.GLOSSARY,
        )
        decision = self.decide(
            candidate,
            self.state("TENCEL", brand_or_domain="tencel.com"),
        )
        self.assertFalse(decision.admitted)
        self.assertIn(
            NormativeAdmissionReasonCode.SOURCE_NOT_ADMISSIBLE,
            decision.reason_codes,
        )

    def test_compound_term_does_not_inherit_tencel_fact(self) -> None:
        decision = self.decide(
            self.candidates["TEN-01"],
            self.state("TENCEL COOL", brand_or_domain="tencel.com"),
        )
        self.assertFalse(decision.admitted)
        self.assertIn(
            NormativeAdmissionReasonCode.TERM_MISMATCH,
            decision.reason_codes,
        )

    def test_exact_source_compound_still_does_not_inherit_tencel_fact(self) -> None:
        source_text = "COOL TENCEL™. Refreshing..."
        term_candidate = "COOL TENCEL™"
        self.assertIn(term_candidate, source_text)

        decision = self.decide(
            self.candidates["TEN-01"],
            self.state(term_candidate, brand_or_domain="brooklinen.com"),
        )

        self.assertFalse(decision.admitted)
        self.assertIn(
            NormativeAdmissionReasonCode.TERM_MISMATCH,
            decision.reason_codes,
        )

    def test_missing_target_form_in_candidate_excerpt_is_rejected(self) -> None:
        original = self.candidates["TEN-01"]
        candidate = self.copy_candidate(
            original,
            content=original.content.replace("天丝™", "错误形式", 1),
        )
        decision = self.decide(
            candidate,
            self.state("TENCEL", brand_or_domain="tencel.com"),
        )
        self.assertFalse(decision.admitted)
        self.assertIn(
            NormativeAdmissionReasonCode.TERM_PAIR_NOT_ATTESTED,
            decision.reason_codes,
        )

    def test_unapproved_locale_is_rejected(self) -> None:
        decision = self.decide(
            self.candidates["TEN-01"],
            self.state(
                "TENCEL",
                brand_or_domain="tencel.com",
                target_locale="zh-TW",
            ),
        )
        self.assertFalse(decision.admitted)
        self.assertIn(
            NormativeAdmissionReasonCode.LOCALE_SCOPE_MISMATCH,
            decision.reason_codes,
        )

    def test_authority_mismatch_is_rejected_for_generic_signal_term(self) -> None:
        decision = self.decide(
            self.candidates["SIG-01"],
            self.state("Save", brand_or_domain="paypal.com"),
        )
        self.assertFalse(decision.admitted)
        self.assertIn(
            NormativeAdmissionReasonCode.AUTHORITY_SCOPE_MISMATCH,
            decision.reason_codes,
        )

    def test_each_assessor_boolean_is_a_required_gate(self) -> None:
        candidate = self.candidates["TEN-01"]
        state = self.state("TENCEL", brand_or_domain="tencel.com")
        for relevant, context_match in ((False, True), (True, False)):
            with self.subTest(relevant=relevant, context_match=context_match):
                decision = self.decide(
                    candidate,
                    state,
                    relevant=relevant,
                    context_match=context_match,
                )
                self.assertFalse(decision.admitted)
                self.assertIn(
                    NormativeAdmissionReasonCode.ASSESSOR_REJECTED,
                    decision.reason_codes,
                )

    def test_unregistered_claim_type_is_rejected(self) -> None:
        candidate = self.copy_candidate(
            self.candidates["TEN-01"], claim_key="official_homepage"
        )
        decision = self.decide(
            candidate,
            self.state("TENCEL", brand_or_domain="tencel.com"),
        )
        self.assertFalse(decision.admitted)
        self.assertIn(
            NormativeAdmissionReasonCode.CLAIM_SCOPE_INVALID,
            decision.reason_codes,
        )

    def test_strict_loop_sufficiency_consumes_only_admitted_evidence(self) -> None:
        candidate = self.candidates["TEN-01"]
        result = TerminologyEvidenceLoop(
            selector=_SearchOfficialThenAbstain(),
            assessor=_FixedAssessor(),
            tools=_FixedResultTools(candidate),
            normative_admission_policy=self.policy,
        ).run(self.state("TENCEL", brand_or_domain="brooklinen.com"))
        self.assertEqual(result.evidence_status, EvidenceStatus.SUFFICIENT)
        self.assertEqual(len(result.verified_evidence), 1)
        admitted = result.verified_evidence[0]
        self.assertTrue(admitted.admitted_normative_evidence)
        self.assertTrue(admitted.declared_supports_normative_claim)
        self.assertEqual(
            admitted.admission_policy_version, DEMO_NORMATIVE_ADMISSION_V1
        )
        self.assertTrue(result.normative_admission_decisions[0].admitted)

    def test_forged_brooklinen_declaration_cannot_make_strict_loop_sufficient(self) -> None:
        candidate = self.brooklinen_candidate(declared=True)
        result = TerminologyEvidenceLoop(
            selector=_SearchOfficialThenAbstain(),
            assessor=_FixedAssessor(relevant=True, context_match=True),
            tools=_FixedResultTools(candidate),
            normative_admission_policy=self.policy,
        ).run(self.state("TENCEL", brand_or_domain="brooklinen.com"))
        self.assertEqual(result.evidence_status, EvidenceStatus.INSUFFICIENT)
        self.assertEqual(result.verified_evidence, [])
        self.assertFalse(result.normative_admission_decisions[0].admitted)
        self.assertIn(
            NormativeAdmissionReasonCode.TERM_PAIR_NOT_ATTESTED,
            result.normative_admission_decisions[0].reason_codes,
        )

    def test_default_loop_preserves_day2_legacy_declaration_behavior(self) -> None:
        candidate = self.brooklinen_candidate(declared=True)
        result = TerminologyEvidenceLoop(
            selector=_SearchOfficialThenAbstain(),
            assessor=_FixedAssessor(relevant=True, context_match=True),
            tools=_FixedResultTools(candidate),
        ).run(self.state("TENCEL", brand_or_domain="brooklinen.com"))
        self.assertEqual(result.evidence_status, EvidenceStatus.SUFFICIENT)
        self.assertEqual(len(result.verified_evidence), 1)
        self.assertTrue(result.verified_evidence[0].supports_normative_claim)
        self.assertFalse(
            result.verified_evidence[0].admitted_normative_evidence
        )
        self.assertEqual(result.normative_admission_decisions, [])
        legacy_evidence_json = result.verified_evidence[0].model_dump(mode="json")
        self.assertNotIn(
            "declared_supports_normative_claim", legacy_evidence_json
        )
        self.assertNotIn("admitted_normative_evidence", legacy_evidence_json)
        self.assertNotIn("admission_policy_version", legacy_evidence_json)
        self.assertNotIn("admitted_claim", legacy_evidence_json)
        self.assertNotIn(
            "normative_admission_decisions", result.model_dump(mode="json")
        )


if __name__ == "__main__":
    unittest.main()
