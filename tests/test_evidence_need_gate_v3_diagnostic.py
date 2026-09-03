from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from devtools import run_evidence_need_gate_v3_diagnostic as diagnostic
from review_triage.prompts import (
    POST_EVAL_CONTROL_V3_PROMPT_VERSION as POST_EVAL_CONTROL_PROMPT_VERSION,
    POST_EVAL_CONTROL_V2_PROMPT_VERSION,
)
from review_triage.schemas import Dimension
from review_triage.workflow import ReviewTriageWorkflow


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
                "reason": "The fixture has no decision-material external fact.",
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


class EvidenceNeedGateV3DiagnosticTests(unittest.TestCase):
    def test_24_case_input_contract_is_gt_blind_and_preserves_null_context(self) -> None:
        specs = diagnostic.load_development_inputs()
        self.assertEqual(len(specs), 24)
        self.assertEqual({item["corpus_id"] for item in specs}, {
            "CS-010", "CS-011", "MKT-006", "MKT-007", "MKT-008", "MKT-009",
            "MKT-012", "MKT-015", "MKT-018", "MKT-020", "MKT-021", "MKT-022",
            "MKT-031", "UI-001", "UI-003", "UI-005", "UI-006", "UI-007",
            "UI-008", "UI-011", "UI-014", "UI-017", "UI-018", "UI-019",
        })
        for spec in specs:
            self.assertEqual(
                set(spec["review_case"]), diagnostic.RUNTIME_REVIEW_CASE_FIELDS
            )
            self.assertIsNone(spec["review_case"]["context_notes"])
            diagnostic.assert_runtime_payload_is_gt_blind(spec["review_case"])
        mkt_007 = next(item for item in specs if item["corpus_id"] == "MKT-007")
        self.assertEqual(
            mkt_007["review_case"]["brand_or_domain"],
            "producthunt.com/products/recordmeeting",
        )

    def test_gt_leakage_guard_rejects_human_fields(self) -> None:
        for forbidden in (
            "human_gt",
            "human_notes",
            "corrected_translation",
            "terminology_evidence_verdict",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaisesRegex(RuntimeError, "forbidden GT field"):
                    diagnostic.assert_runtime_payload_is_gt_blind({forbidden: "x"})

    def test_gate_runner_uses_v2_and_v3_without_downstream_nodes(self) -> None:
        spec = next(
            item
            for item in diagnostic.load_development_inputs()
            if item["evaluations"] is not None
        )
        client = GateFake()
        for variant, prompt_version in (
            ("C0_V2", POST_EVAL_CONTROL_V2_PROMPT_VERSION),
            ("C1_V3", POST_EVAL_CONTROL_PROMPT_VERSION),
        ):
            rows = diagnostic.run_variant_predictions(
                client,
                specs=[spec],
                variant=variant,
                prompt_version=prompt_version,
            )
            self.assertEqual(rows[0]["prediction"], False)
            self.assertIsNone(rows[0]["processing_failure"])
        self.assertEqual(
            [call["prompt_version"] for call in client.calls],
            [POST_EVAL_CONTROL_V2_PROMPT_VERSION, POST_EVAL_CONTROL_PROMPT_VERSION],
        )

    def test_human_gt_is_joined_only_after_both_prediction_passes(self) -> None:
        events = []

        class Provider:
            public_metadata = {"model": "fake"}

            def close(self):
                events.append("provider-closed")

        def predict(*args, **kwargs):
            events.append(f"predict-{kwargs['variant']}")
            return []

        def load_gt():
            events.append("load-gt")
            return {}

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "diagnostic.json"
            with (
                patch.object(diagnostic, "OUTPUT", output),
                patch.object(diagnostic, "verify_frozen_inputs", return_value={}),
                patch.object(diagnostic, "load_development_inputs", return_value=[]),
                patch.object(
                    diagnostic,
                    "create_comparative_deepseek_provider",
                    return_value=Provider(),
                ),
                patch.object(diagnostic, "run_variant_predictions", side_effect=predict),
                patch.object(
                    diagnostic, "load_human_gt_after_predictions", side_effect=load_gt
                ),
                patch.object(
                    diagnostic,
                    "build_artifact",
                    return_value={
                        "metrics": {
                            "C0_V2": {"counts": {}},
                            "C1_V3": {"counts": {}},
                        }
                    },
                ),
                patch.object(diagnostic, "write_new_artifact"),
            ):
                self.assertEqual(diagnostic.main(), 0)
        self.assertEqual(
            events,
            ["predict-C0_V2", "predict-C1_V3", "provider-closed", "load-gt"],
        )

    def test_confusion_metrics_and_positive_audit(self) -> None:
        predictions = [
            {
                "case_id": "TP",
                "prediction": True,
                "terminology": {
                    "term_candidate": "Name",
                    "evidence_need": "Verify official naming.",
                    "reason": "The current identity is insufficient; official docs can resolve it.",
                },
                "processing_failure": None,
            },
            {
                "case_id": "FP",
                "prediction": True,
                "terminology": {
                    "term_candidate": "Word",
                    "evidence_need": "Verify controlled usage.",
                    "reason": "A glossary could resolve the candidate.",
                },
                "processing_failure": None,
            },
            {"case_id": "TN", "prediction": False, "terminology": None, "processing_failure": None},
            {"case_id": "FN", "prediction": False, "terminology": None, "processing_failure": None},
            {"case_id": "FAIL", "prediction": None, "terminology": None, "processing_failure": {"error_code": "X"}},
        ]
        result = diagnostic.compute_confusion(
            predictions,
            {"TP": True, "FP": False, "TN": False, "FN": True, "FAIL": True},
        )
        self.assertEqual(result["counts"], {"TP": 1, "FP": 1, "TN": 1, "FN": 1})
        self.assertEqual(result["evidence_need_recall"]["value"], 0.5)
        self.assertEqual(result["false_trigger_rate"]["value"], 0.5)
        self.assertEqual(result["processing_failure_count"], 1)
        self.assertEqual(result["predicted_positive_audit"][0]["case_id"], "TP")

    def test_router_topology_still_depends_only_on_gate_boolean(self) -> None:
        for requires_evidence, expected in ((True, "evidence"), (False, "continue")):
            state = {
                "dimension_evaluations": [
                    SimpleNamespace(
                        dimension=Dimension.TERMINOLOGY,
                        requires_external_evidence=requires_evidence,
                    )
                ]
            }
            self.assertEqual(ReviewTriageWorkflow._after_node_02(state), expected)


if __name__ == "__main__":
    unittest.main()
