from __future__ import annotations

import unittest

from review_triage.demo_evidence_pack_v1 import load_demo_evidence_pack_v1
from review_triage.demo_evidence_retrieval_v2 import (
    AUTHORITY_IDENTITY_ALIASES_V1,
    DemoEvidenceRetrievalV2,
    RETRIEVAL_INTENT_MODIFIER_TOKENS,
    canonicalize_demo_identity_tokens_v1,
    normalize_demo_retrieval_text,
)
from review_triage.schemas import ToolResultStatus


REAL_MKT_020_LIVE_QUERIES = (
    (
        "TENCEL™ 兰精 官方中文品牌名",
        frozenset({"tencel", "lenzing"}),
    ),
    (
        "兰精 TENCEL 中文名称 商标 天丝",
        frozenset({"lenzing", "tencel", "天丝"}),
    ),
    (
        "TENCEL 天丝 兰精 官方 中国 商标",
        frozenset({"tencel", "天丝", "lenzing"}),
    ),
    (
        "TENCEL 天丝 兰精 商标 中国",
        frozenset({"tencel", "天丝", "lenzing"}),
    ),
)


class DemoEvidenceRetrievalV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.retrieval = DemoEvidenceRetrievalV2(load_demo_evidence_pack_v1())

    def search(self, query: str, *, term_candidate: str | None = None):
        return self.retrieval.search_official_docs(
            query,
            term_candidate=term_candidate,
        )

    def test_tencel_and_trademark_variant_reach_same_ten_family(self) -> None:
        plain = self.search("TENCEL")
        trademarked = self.search("TENCEL™")
        self.assertEqual(plain.status, ToolResultStatus.HIT)
        self.assertEqual(trademarked.status, ToolResultStatus.HIT)
        self.assertEqual(
            [candidate.candidate_id for candidate in plain.candidates],
            [candidate.candidate_id for candidate in trademarked.candidates],
        )
        self.assertEqual(plain.candidates[0].candidate_id, "TEN-01")
        self.assertTrue(all(candidate.candidate_id.startswith("TEN-") for candidate in plain.candidates))

    def test_trademark_qualifiers_become_token_boundaries_before_nfkc(self) -> None:
        self.assertEqual(
            normalize_demo_retrieval_text("TENCEL™ 天丝™莱赛尔纤维 ACME®Widget"),
            "tencel 天丝 莱赛尔纤维 acme widget",
        )

    def test_real_mkt_020_live_query_reaches_ten_01(self) -> None:
        result = self.search(
            "TENCEL 天丝 官方 中文名称 Lenzing",
            term_candidate="TENCEL™",
        )

        self.assertEqual(result.status, ToolResultStatus.HIT)
        self.assertEqual(result.candidates[0].candidate_id, "TEN-01")
        self.assertIn("TEN-01", [candidate.candidate_id for candidate in result.candidates])

    def test_live_query_variant_reaches_ten_01_without_exact_query_memorization(self) -> None:
        result = self.search(
            "Lenzing TENCEL™ 天丝™ 官方中文译名",
            term_candidate="TENCEL™",
        )

        self.assertEqual(result.status, ToolResultStatus.HIT)
        self.assertEqual(result.candidates[0].candidate_id, "TEN-01")
        self.assertTrue(
            all(candidate.candidate_id.startswith("TEN-") for candidate in result.candidates)
        )

    def test_real_mkt_020_live_queries_preserve_canonical_guidance_tokens(self) -> None:
        for query, expected_identity_tokens in REAL_MKT_020_LIVE_QUERIES:
            with self.subTest(query=query):
                self.assertEqual(
                    canonicalize_demo_identity_tokens_v1(query),
                    expected_identity_tokens,
                )
                result = self.search(query, term_candidate="TENCEL™")
                candidate_ids = [candidate.candidate_id for candidate in result.candidates]

                self.assertEqual(result.status, ToolResultStatus.HIT)
                self.assertIn("TEN-01", candidate_ids)
                self.assertTrue(
                    all(candidate_id.startswith("TEN-") for candidate_id in candidate_ids)
                )

    def test_lenzing_chinese_alias_is_canonicalized_not_discarded(self) -> None:
        self.assertEqual(AUTHORITY_IDENTITY_ALIASES_V1["兰精"], "lenzing")
        self.assertNotIn("兰精", RETRIEVAL_INTENT_MODIFIER_TOKENS)
        self.assertEqual(
            canonicalize_demo_identity_tokens_v1("兰精"),
            frozenset({"lenzing"}),
        )

    def test_chinese_intent_modifier_generalizes_to_signal(self) -> None:
        result = self.search(
            "Signal Save 保存 官方中文名称",
            term_candidate="Save",
        )

        self.assertEqual(result.status, ToolResultStatus.HIT)
        self.assertEqual([candidate.candidate_id for candidate in result.candidates], ["SIG-01"])

    def test_tencel_studio_variants_prefer_the_exact_ten_04_term(self) -> None:
        for query in ("TENCEL Studio", "TENCEL™ Studio"):
            with self.subTest(query=query):
                result = self.search(query)
                self.assertEqual(result.status, ToolResultStatus.HIT)
                self.assertEqual(
                    [candidate.candidate_id for candidate in result.candidates],
                    ["TEN-04"],
                )

    def test_save_reaches_signal_mapping(self) -> None:
        result = self.search("Save")
        self.assertEqual(result.status, ToolResultStatus.HIT)
        self.assertEqual(result.candidates[0].candidate_id, "SIG-01")
        self.assertEqual(result.candidates[0].claim_value, "Save → 保存")

    def test_pending_reaches_paypal_mapping(self) -> None:
        result = self.search("pending")
        self.assertEqual(result.status, ToolResultStatus.HIT)
        self.assertEqual(result.candidates[0].candidate_id, "PP-01")
        self.assertEqual(result.candidates[0].claim_value, "pending → 待处理")

    def test_explicit_cross_family_queries_remain_isolated(self) -> None:
        expectations = {
            ("Save", "Signal Save"): ["SIG-01"],
            ("pending", "PayPal pending"): ["PP-01"],
        }
        for (term_candidate, query), expected_candidate_ids in expectations.items():
            with self.subTest(term_candidate=term_candidate, query=query):
                result = self.search(query, term_candidate=term_candidate)
                self.assertEqual(result.status, ToolResultStatus.HIT)
                self.assertEqual(
                    [candidate.candidate_id for candidate in result.candidates],
                    expected_candidate_ids,
                )

    def test_coverage_and_unrelated_queries_miss(self) -> None:
        for query in (
            "Flodesk Studio",
            "Acme Quasar",
            "TENCEL COOL",
            "TENCEL Flodesk",
        ):
            with self.subTest(query=query):
                result = self.search(query)
                self.assertEqual(result.status, ToolResultStatus.MISS)
                self.assertEqual(result.candidates, [])

    def test_low_information_queries_do_not_fall_back_to_an_official_page(self) -> None:
        for query in (
            "official Chinese name",
            "官方中文名称",
            "官方 中文名称",
            "中文译名",
            "官方译名",
            "官方 中文 商标 中国",
            "the or a an",
            "official product translation",
        ):
            with self.subTest(query=query):
                result = self.search(query)
                self.assertEqual(result.status, ToolResultStatus.MISS)
                self.assertEqual(result.candidates, [])

    def test_retrieval_hit_remains_candidate_reachability_only(self) -> None:
        result = self.search(
            REAL_MKT_020_LIVE_QUERIES[0][0],
            term_candidate="TENCEL™",
        )
        serialized = result.model_dump(mode="json")

        self.assertEqual(result.status, ToolResultStatus.HIT)
        self.assertIn("TEN-01", [candidate.candidate_id for candidate in result.candidates])
        self.assertNotIn("verified_evidence", serialized)
        self.assertNotIn("normative_admission_decisions", serialized)
        self.assertNotIn("evidence_status", serialized)

    def test_tencel_does_not_rank_other_families_ahead_of_ten(self) -> None:
        result = self.search("TENCEL")
        self.assertEqual(result.status, ToolResultStatus.HIT)
        self.assertTrue(all(candidate.candidate_id.startswith("TEN-") for candidate in result.candidates))

    def test_shared_non_core_token_does_not_cross_family_match(self) -> None:
        result = self.search("Flodesk Studio")
        self.assertEqual(result.status, ToolResultStatus.MISS)
        self.assertEqual(result.candidates, [])

    def test_exact_anchor_and_one_way_descendant_scope(self) -> None:
        expectations = {
            "TENCEL™": (
                ToolResultStatus.HIT,
                ["TEN-01", "TEN-02", "TEN-03", "TEN-04"],
            ),
            "TENCEL™ Studio": (ToolResultStatus.HIT, ["TEN-04"]),
            "COOL TENCEL™": (ToolResultStatus.MISS, []),
            "Save": (ToolResultStatus.HIT, ["SIG-01"]),
            "pending": (ToolResultStatus.HIT, ["PP-01"]),
            "Flodesk Studio": (ToolResultStatus.MISS, []),
        }
        for term_candidate, (expected_status, expected_ids) in expectations.items():
            with self.subTest(term_candidate=term_candidate):
                result = self.search(
                    "unknown retrieval wording",
                    term_candidate=term_candidate,
                )
                self.assertEqual(result.status, expected_status)
                self.assertEqual(
                    [candidate.candidate_id for candidate in result.candidates],
                    expected_ids,
                )

    def test_query_guides_descendant_ranking_without_displacing_anchor(self) -> None:
        studio = self.search(
            "TENCEL official Studio terminology",
            term_candidate="TENCEL™",
        )
        lyocell = self.search(
            "TENCEL official Lyocell terminology",
            term_candidate="TENCEL™",
        )
        studio_ids = [candidate.candidate_id for candidate in studio.candidates]
        lyocell_ids = [candidate.candidate_id for candidate in lyocell.candidates]

        self.assertEqual(studio_ids[0], "TEN-01")
        self.assertEqual(lyocell_ids[0], "TEN-01")
        self.assertEqual(studio_ids[1], "TEN-04")
        self.assertEqual(lyocell_ids[1], "TEN-02")
        self.assertNotEqual(studio_ids, lyocell_ids)

    def test_query_cannot_filter_or_expand_a_valid_anchor_scope(self) -> None:
        result = self.search(
            "Flodesk quasar wording never seen before",
            term_candidate="TENCEL™",
        )

        self.assertEqual(result.status, ToolResultStatus.HIT)
        self.assertEqual(result.candidates[0].candidate_id, "TEN-01")
        self.assertEqual(
            {candidate.candidate_id for candidate in result.candidates},
            {"TEN-01", "TEN-02", "TEN-03", "TEN-04"},
        )


if __name__ == "__main__":
    unittest.main()
