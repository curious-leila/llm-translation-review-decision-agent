from __future__ import annotations

import unittest

from review_triage.demo_evidence_pack_v1 import load_demo_evidence_pack_v1
from review_triage.term_anchor import (
    DEMO_TERM_ANCHOR_RESOLVER_V1,
    DemoTermAnchorResolverV1,
)


class DemoTermAnchorResolverV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resolver = DemoTermAnchorResolverV1.from_pack(
            load_demo_evidence_pack_v1()
        )

    def test_historical_mkt_020_candidate_resolves_to_registered_tencel_anchor(self) -> None:
        result = self.resolver.resolve(
            source_text=(
                "COOL TENCEL™. Refreshing, smooth, with barely-there feel,\n"
                "introducing our coolest fabric yet."
            ),
            term_candidate=(
                "COOL TENCEL™ (specifically the TENCEL™ brand component)"
            ),
        )

        self.assertEqual(result.raw_term_candidate, "COOL TENCEL™ (specifically the TENCEL™ brand component)")
        self.assertEqual(result.resolved_term_anchor, "TENCEL™")
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual(result.policy_version, DEMO_TERM_ANCHOR_RESOLVER_V1)

    def test_exact_registered_term_is_preserved(self) -> None:
        result = self.resolver.resolve(
            source_text="TENCEL™ fibers",
            term_candidate="TENCEL™",
        )

        self.assertEqual(result.resolved_term_anchor, "TENCEL™")
        self.assertEqual(result.status, "EXACT")

    def test_exact_more_specific_registered_term_wins_over_parent(self) -> None:
        result = self.resolver.resolve(
            source_text="Explore TENCEL™ Studio today.",
            term_candidate="TENCEL™ Studio",
        )

        self.assertEqual(result.resolved_term_anchor, "TENCEL™ Studio")
        self.assertEqual(result.status, "EXACT")

    def test_unique_registered_subterm_resolves_from_literal_compound(self) -> None:
        result = self.resolver.resolve(
            source_text="COOL TENCEL™ is smooth.",
            term_candidate="COOL TENCEL™",
        )

        self.assertEqual(result.resolved_term_anchor, "TENCEL™")
        self.assertEqual(result.status, "RESOLVED")

    def test_unregistered_term_fails_closed(self) -> None:
        result = self.resolver.resolve(
            source_text="Flodesk Studio designs an email.",
            term_candidate="Flodesk Studio",
        )

        self.assertIsNone(result.resolved_term_anchor)
        self.assertEqual(result.status, "UNRESOLVED")

    def test_equal_length_ambiguity_fails_closed(self) -> None:
        resolver = DemoTermAnchorResolverV1(("天丝", "兰精"))
        result = resolver.resolve(
            source_text="天丝兰精",
            term_candidate="天丝兰精",
        )

        self.assertIsNone(result.resolved_term_anchor)
        self.assertEqual(result.status, "AMBIGUOUS")

    def test_ascii_substrings_do_not_cross_word_boundaries(self) -> None:
        resolver = DemoTermAnchorResolverV1(("Save",))
        result = resolver.resolve(
            source_text="Saved successfully",
            term_candidate="Saved",
        )

        self.assertIsNone(result.resolved_term_anchor)
        self.assertEqual(result.status, "UNRESOLVED")


if __name__ == "__main__":
    unittest.main()
