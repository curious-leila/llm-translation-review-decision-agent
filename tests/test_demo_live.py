from __future__ import annotations

import importlib
import sys
import unittest
from unittest.mock import Mock, patch

from review_triage.demo_evidence_retrieval_v2 import DemoEvidenceRetrievalV2
from review_triage.normative_admission import DemoNormativeAdmissionV1
from review_triage.schemas import EvidenceAction, EvidenceProvenance, ToolResultStatus


class LiveCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        sys.modules.pop("review_triage.demo.live", None)

    def tearDown(self) -> None:
        sys.modules.pop("review_triage.demo.live", None)

    def _import_live(self):
        provider = Mock()
        repository = Mock()
        with (
            patch(
                "review_triage.providers.deepseek.DeepSeekProvider.from_env",
                return_value=provider,
            ),
            patch(
                "review_triage.persistence.SQLiteRepository",
                return_value=repository,
            ),
        ):
            module = importlib.import_module("review_triage.demo.live")
        return module

    def test_live_workflow_uses_demo_pack_through_retrieval_v2(self) -> None:
        live = self._import_live()
        workflow = live.service.workflow
        retrieval = workflow.evidence_tools.official_docs

        self.assertIsInstance(retrieval, DemoEvidenceRetrievalV2)
        result = retrieval.search_official_docs("TENCEL")
        self.assertEqual(result.status, ToolResultStatus.HIT)
        self.assertEqual(
            {candidate.provenance for candidate in result.candidates},
            {EvidenceProvenance.OFFICIAL_DOCS},
        )
        self.assertTrue(
            all(candidate.candidate_id.startswith("TEN-") for candidate in result.candidates)
        )

    def test_live_workflow_explicitly_enables_demo_strict_admission(self) -> None:
        live = self._import_live()

        self.assertIsInstance(
            live.service.workflow.normative_admission_policy,
            DemoNormativeAdmissionV1,
        )

    def test_live_workflow_exposes_only_official_search(self) -> None:
        live = self._import_live()
        workflow = live.service.workflow

        self.assertEqual(
            workflow.available_evidence_actions,
            (EvidenceAction.SEARCH_OFFICIAL_DOCS,),
        )
        self.assertEqual(
            workflow.evidence_tools.search_glossary("Signal").status,
            ToolResultStatus.MISS,
        )
        self.assertEqual(
            workflow.evidence_tools.search_case_memory("Signal").status,
            ToolResultStatus.MISS,
        )


if __name__ == "__main__":
    unittest.main()
