from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from devtools import run_input_semantics_gate_v3_diagnostic as diagnostic
from review_triage.prompts import (
    POST_EVAL_CONTROL_V3_PROMPT_VERSION as POST_EVAL_CONTROL_PROMPT_VERSION,
)


REVIEW_CASE = {
    "source_text": "Record Meeting works differently.",
    "translation_text": "录制会议的工作方式不同。",
    "content_type": "MARKETING",
    "brand_or_domain": "RecordMeeting",
    "context_notes": "Product Hunt 上的 RecordMeeting 产品介绍",
    "source_language": "en",
    "target_locale": "zh-CN",
}


class GateFake:
    model_version = "gate-fake-v1"

    def __init__(self) -> None:
        self.calls = []

    def invoke_structured(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "terminology": {
                "requires_external_evidence": False,
                "term_candidate": None,
                "evidence_need": None,
                "normative_claim": False,
                "reason": "No decision-material external fact is required.",
            },
            "accuracy": {
                "unresolved_external_support": False,
                "reason": "No external support is required.",
            },
            "locale": {
                "unresolved_external_support": False,
                "reason": "No external support is required.",
            },
            "audience": {
                "unresolved_external_support": False,
                "reason": "No external support is required.",
            },
        }


class InputSemanticsGateV3DiagnosticTests(unittest.TestCase):
    def test_non_locator_is_role_labeled_without_rewrite(self) -> None:
        views = diagnostic.build_input_views(REVIEW_CASE)
        labeled = views["role_labeled_gate_input"]
        self.assertIn(diagnostic.IDENTITY_SCOPE_ROLE, labeled["brand_or_domain"])
        self.assertTrue(labeled["brand_or_domain"].endswith("RecordMeeting"))
        self.assertIn(diagnostic.CONTEXT_ROLE, labeled["context_notes"])
        self.assertTrue(
            labeled["context_notes"].endswith(
                "Product Hunt 上的 RecordMeeting 产品介绍"
            )
        )
        self.assertEqual(views["raw_gate_input"], REVIEW_CASE)
        self.assertEqual(labeled["source_text"], REVIEW_CASE["source_text"])
        self.assertEqual(
            labeled["translation_text"], REVIEW_CASE["translation_text"]
        )

    def test_locator_preserves_value_and_does_not_assert_slug_identity(self) -> None:
        case = {
            **REVIEW_CASE,
            "brand_or_domain": "  producthunt.com/products/recordmeeting  ",
            "context_notes": "   ",
        }
        views = diagnostic.build_input_views(case)
        labeled = views["role_labeled_gate_input"]
        audit = views["normalization_audit"]["brand_or_domain"]
        self.assertIn(diagnostic.SOURCE_LOCATOR_ROLE, labeled["brand_or_domain"])
        self.assertIn(diagnostic.LOCATOR_BOUNDARY, labeled["brand_or_domain"])
        self.assertTrue(
            labeled["brand_or_domain"].endswith(
                "producthunt.com/products/recordmeeting"
            )
        )
        self.assertEqual(audit["host"], "producthunt.com")
        self.assertNotIn("entity", audit)
        self.assertIsNone(labeled["context_notes"])

    def test_url_and_domain_detection_is_syntax_only(self) -> None:
        self.assertEqual(
            diagnostic._source_locator_host(
                "https://github.com/signalapp/Signal-Android"
            ),
            "github.com",
        )
        self.assertEqual(
            diagnostic._source_locator_host("framer.com"), "framer.com"
        )
        self.assertIsNone(diagnostic._source_locator_host("RecordMeeting"))
        self.assertIsNone(diagnostic._source_locator_host("email marketing"))

    def test_adapter_rejects_gt_fields_before_rendering(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "contract drift"):
            diagnostic.build_input_views({**REVIEW_CASE, "human_gt": True})

    def test_both_variants_use_same_prompt_v3_and_repeat_three_times(self) -> None:
        client = GateFake()
        spec = {
            "corpus_id": "MKT-007",
            "cohort": "NATURALISTIC",
            "frozen_baseline_source": None,
            "evaluations": [],
            "pre_gate_failure": None,
            "input_views": diagnostic.build_input_views(REVIEW_CASE),
        }
        with patch.object(
            diagnostic,
            "invoke_post_eval_control_classifier",
            side_effect=lambda client, **kwargs: (
                type(
                    "Decision",
                    (),
                    {
                        "terminology": type(
                            "Terminology",
                            (),
                            {
                                "model_dump": lambda self, mode: {
                                    "requires_external_evidence": False,
                                    "term_candidate": None,
                                    "evidence_need": None,
                                    "normative_claim": False,
                                    "reason": "No external fact.",
                                }
                            },
                        )()
                    },
                )(),
                [],
            ),
        ) as invoke:
            predictions = diagnostic.run_all_gate_predictions(
                client, specs=[spec], repeat_count=3
            )
        self.assertEqual(len(predictions["C1_RAW_V3"]), 3)
        self.assertEqual(len(predictions["C2_ROLE_LABELED_V3"]), 3)
        self.assertEqual(invoke.call_count, 6)
        self.assertEqual(
            {call.kwargs["prompt_version"] for call in invoke.call_args_list},
            {POST_EVAL_CONTROL_PROMPT_VERSION},
        )

    def test_stability_marks_prediction_flip(self) -> None:
        rows = [
            {"prediction": True, "terminology": {"term_candidate": "Poll", "reason": "a"}},
            {"prediction": False, "terminology": {"term_candidate": None, "reason": "b"}},
            {"prediction": True, "terminology": {"term_candidate": "Poll", "reason": "c"}},
        ]
        stability = diagnostic._aggregate_runs(rows, 3)
        self.assertTrue(stability["aggregate_prediction"])
        self.assertTrue(stability["prediction_flip_observed"])
        self.assertFalse(stability["prediction_unanimous"])

    def test_candidate_breadth_signal_is_conservative(self) -> None:
        self.assertEqual(
            diagnostic.compare_candidate_breadth("block", "Cannot block yourself"),
            "C2_CLEARLY_BROADER",
        )
        self.assertEqual(
            diagnostic.compare_candidate_breadth("Record Meeting", "Record Meeting"),
            "EQUAL",
        )
        self.assertEqual(
            diagnostic.compare_candidate_breadth("Agents", "design agent"),
            "MANUAL_REVIEW_INCOMPARABLE",
        )

    def test_default_main_is_dry_run_and_never_creates_provider(self) -> None:
        specs = [
            {"pre_gate_failure": None},
            {"pre_gate_failure": {"error_code": "NO_BASELINE"}},
        ]
        output = io.StringIO()
        with (
            patch.object(diagnostic.gate_v3, "verify_frozen_inputs", return_value={}),
            patch.object(diagnostic, "prepare_specs", return_value=specs),
            patch.object(
                diagnostic, "create_comparative_deepseek_provider"
            ) as provider,
            redirect_stdout(output),
        ):
            self.assertEqual(diagnostic.main([]), 0)
        provider.assert_not_called()
        report = __import__("json").loads(output.getvalue())
        self.assertEqual(report["status"], "DRY_RUN_READY_NO_API_CALLED")
        self.assertEqual(report["logical_gate_request_count"], 6)

    def test_full_fake_prediction_then_post_hoc_gt_builds_required_case_audit(self) -> None:
        specs = diagnostic.prepare_specs()
        client = GateFake()
        predictions = diagnostic.run_all_gate_predictions(
            client, specs=specs, repeat_count=3
        )
        self.assertEqual(len(client.calls), 132)

        # Deliberately load labels only after all fake Gate predictions finish.
        labels = diagnostic.gate_v3.load_human_gt_after_predictions()
        artifact = diagnostic.build_artifact(
            specs=specs,
            predictions_by_variant=predictions,
            labels=labels,
            frozen_input_hashes={},
            provider_metadata={"model": "fake"},
            started_at="2026-08-28T00:00:00+00:00",
            repeat_count=3,
        )
        self.assertEqual(len(artifact["cases"]), 24)
        mkt_007 = next(
            case for case in artifact["cases"] if case["case_id"] == "MKT-007"
        )
        self.assertIn("raw_gate_input", mkt_007)
        self.assertIn("role_labeled_gate_input", mkt_007)
        self.assertEqual(len(mkt_007["C1_RAW_V3"]["runs"]), 3)
        self.assertEqual(
            mkt_007["C2_ROLE_LABELED_V3"]["runs"][0]["classification"],
            "FN",
        )
        self.assertEqual(
            artifact["hard_acceptance"]["option_b_automatic_status"], "NO_GO"
        )


if __name__ == "__main__":
    unittest.main()
