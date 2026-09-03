from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from collections import Counter
from dataclasses import FrozenInstanceError
from pathlib import Path

from pydantic import ValidationError

from review_triage.day2_baselines import (
    EVIDENCE_SNAPSHOT_PATH,
    load_frozen_available_evidence_actions,
    load_shared_evidence_tools,
)
from review_triage.demo_evidence_pack_v1 import (
    DEMO_EVIDENCE_PACK_V1_DIR,
    EXPECTED_SIGNAL_VERSION,
    DemoEvidencePackV1Error,
    load_demo_evidence_pack_v1,
)
from review_triage.evidence_tools import ControlledEvidenceTools
from review_triage.schemas import EvidenceAction


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_NAME = "official_terminology_snapshot_v1.json"


class DemoEvidencePackV1LoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.pack_dir = Path(self.temporary_directory.name) / "demo_evidence_v1"
        shutil.copytree(DEMO_EVIDENCE_PACK_V1_DIR, self.pack_dir)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _snapshot(self) -> dict:
        return json.loads((self.pack_dir / SNAPSHOT_NAME).read_text(encoding="utf-8"))

    def _write_snapshot_and_refresh_hashes(self, data: dict) -> None:
        content_payload = dict(data)
        content_payload.pop("snapshot_sha256_excluding_self", None)
        canonical = json.dumps(
            content_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        data["snapshot_sha256_excluding_self"] = hashlib.sha256(canonical).hexdigest()
        snapshot_path = self.pack_dir / SNAPSHOT_NAME
        snapshot_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        manifest_path = self.pack_dir / "manifest_v1.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["snapshot_sha256"] = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        manifest["snapshot_content_sha256_excluding_self"] = data[
            "snapshot_sha256_excluding_self"
        ]
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _restore_pack(self) -> None:
        shutil.rmtree(self.pack_dir)
        shutil.copytree(DEMO_EVIDENCE_PACK_V1_DIR, self.pack_dir)

    def assert_error_code(self, expected: str, callable_) -> None:
        with self.assertRaises(DemoEvidencePackV1Error) as raised:
            callable_()
        self.assertEqual(raised.exception.code, expected)

    def test_loads_12_positive_facts_and_preserves_family_counts(self) -> None:
        pack = load_demo_evidence_pack_v1()
        self.assertEqual(len(pack.positive_facts), 12)
        self.assertEqual(len(pack.positive_evidence_candidates), 12)
        self.assertEqual(
            Counter(fact.evidence_family for fact in pack.positive_facts),
            {
                "Signal Android UI": 4,
                "PayPal customer support": 4,
                "Lenzing / TENCEL marketing": 4,
            },
        )
        self.assertEqual(
            {candidate.candidate_id for candidate in pack.positive_evidence_candidates},
            {fact.fact_id for fact in pack.positive_facts},
        )

    def test_preserves_required_positive_fact_fields_without_semantic_rewrite(self) -> None:
        raw_facts = {
            fact["fact_id"]: fact
            for fact in json.loads(
                (DEMO_EVIDENCE_PACK_V1_DIR / SNAPSHOT_NAME).read_text(encoding="utf-8")
            )["positive_facts"]
        }
        for fact in load_demo_evidence_pack_v1().positive_facts:
            raw = raw_facts[fact.fact_id]
            self.assertEqual(fact.source_term, raw["source_term"])
            self.assertEqual(fact.target_form, raw["target_form"])
            self.assertEqual(fact.authority_scope, raw["authority_scope"])
            self.assertEqual(
                {"source": fact.locale_scope.source, "target": fact.locale_scope.target},
                raw["locale_scope"],
            )
            self.assertEqual(fact.source_ref, raw["source_ref"])
            self.assertEqual(dict(fact.supporting_excerpt), raw["supporting_excerpt"])
            self.assertEqual(fact.claim_key, raw["claim_key"])
            self.assertEqual(fact.claim_value, raw["claim_value"])
            self.assertEqual(fact.scenario, raw["scenario"])
            self.assertEqual(fact.is_official_source, raw["is_official_source"])
            self.assertEqual(
                fact.supports_normative_claim, raw["supports_normative_claim"]
            )
            self.assertEqual(fact.claim_scope, raw["claim_scope"])

    def test_preserves_paypal_locales_exactly(self) -> None:
        facts = {fact.fact_id: fact for fact in load_demo_evidence_pack_v1().positive_facts}
        self.assertEqual(facts["PP-01"].locale_scope.target, "zh_C2")
        self.assertEqual(facts["PP-02"].locale_scope.target, "zh_C2")
        self.assertEqual(facts["PP-03"].locale_scope.target, "zh_C2")
        self.assertEqual(facts["PP-04"].locale_scope.target, "zh_US")

    def test_reads_pinned_signal_version_without_network_access(self) -> None:
        pack = load_demo_evidence_pack_v1()
        self.assertEqual(pack.signal_version, EXPECTED_SIGNAL_VERSION)
        signal_sources = [
            source for source in pack.source_documents
            if source.source_ref.startswith("SIG-ANDROID-")
        ]
        self.assertEqual(
            {source.version_identifier for source in signal_sources},
            {f"git_commit:{EXPECTED_SIGNAL_VERSION}"},
        )

    def test_negative_controls_are_not_positive_candidates_and_result_is_read_only(self) -> None:
        pack = load_demo_evidence_pack_v1()
        self.assertEqual({control.control_id for control in pack.negative_controls}, {"NC-A", "NC-B"})
        candidate_ids = {candidate.candidate_id for candidate in pack.positive_evidence_candidates}
        self.assertTrue(candidate_ids.isdisjoint({"NC-A", "NC-B"}))
        nc_b = next(control for control in pack.negative_controls if control.control_id == "NC-B")
        self.assertIsNone(nc_b.target_form_under_test)
        with self.assertRaises(FrozenInstanceError):
            pack.version = "changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            pack.positive_facts[0].supporting_excerpt["source"] = "changed"  # type: ignore[index]
        with self.assertRaises(ValidationError):
            pack.positive_evidence_candidates[0].target_locale = "zh-CN"  # type: ignore[misc]

    def test_tampered_snapshot_fails_file_integrity_validation(self) -> None:
        path = self.pack_dir / SNAPSHOT_NAME
        path.write_bytes(path.read_bytes().replace("Save".encode(), "SAVE".encode(), 1))
        self.assert_error_code(
            "INTEGRITY_MISMATCH", lambda: load_demo_evidence_pack_v1(self.pack_dir)
        )

    def test_version_mismatch_fails_before_integrity_fallback(self) -> None:
        data = self._snapshot()
        data["version"] = "2.0.0"
        (self.pack_dir / SNAPSHOT_NAME).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        self.assert_error_code(
            "VERSION_MISMATCH", lambda: load_demo_evidence_pack_v1(self.pack_dir)
        )

    def test_missing_file_and_invalid_json_are_diagnostic(self) -> None:
        (self.pack_dir / SNAPSHOT_NAME).unlink()
        self.assert_error_code(
            "FILE_NOT_FOUND", lambda: load_demo_evidence_pack_v1(self.pack_dir)
        )
        (self.pack_dir / SNAPSHOT_NAME).write_text("{not-json", encoding="utf-8")
        self.assert_error_code(
            "JSON_PARSE_ERROR", lambda: load_demo_evidence_pack_v1(self.pack_dir)
        )

    def test_required_field_duplicate_id_and_unresolved_ref_fail_fast(self) -> None:
        data = self._snapshot()
        del data["positive_facts"][0]["claim_scope"]
        self._write_snapshot_and_refresh_hashes(data)
        self.assert_error_code(
            "REQUIRED_FIELD_MISSING", lambda: load_demo_evidence_pack_v1(self.pack_dir)
        )

        self._restore_pack()
        data = self._snapshot()
        data["positive_facts"][1]["fact_id"] = data["positive_facts"][0]["fact_id"]
        self._write_snapshot_and_refresh_hashes(data)
        self.assert_error_code(
            "DUPLICATE_FACT_ID", lambda: load_demo_evidence_pack_v1(self.pack_dir)
        )

        self._restore_pack()
        data = self._snapshot()
        data["positive_facts"][0]["source_ref"] = "UNKNOWN-SOURCE"
        self._write_snapshot_and_refresh_hashes(data)
        self.assert_error_code(
            "UNRESOLVED_SOURCE_REF", lambda: load_demo_evidence_pack_v1(self.pack_dir)
        )

    def test_paypal_locale_mutation_fails_even_with_refreshed_hashes(self) -> None:
        data = self._snapshot()
        pp_01 = next(fact for fact in data["positive_facts"] if fact["fact_id"] == "PP-01")
        pp_01["locale_scope"]["target"] = "zh-CN"
        self._write_snapshot_and_refresh_hashes(data)
        self.assert_error_code(
            "LOCALE_MISMATCH", lambda: load_demo_evidence_pack_v1(self.pack_dir)
        )

    def test_illegal_positive_negative_control_mixing_fails(self) -> None:
        data = self._snapshot()
        data["positive_facts"][0]["control_type"] = "coverage_negative"
        self._write_snapshot_and_refresh_hashes(data)
        self.assert_error_code(
            "CLASSIFICATION_ERROR", lambda: load_demo_evidence_pack_v1(self.pack_dir)
        )

    def test_day2_loader_paths_and_behavior_remain_unchanged(self) -> None:
        self.assertEqual(
            EVIDENCE_SNAPSHOT_PATH,
            ROOT / "artifacts/day2_gate_b/shared_evidence_environment_v2.json",
        )
        self.assertIsInstance(load_shared_evidence_tools(), ControlledEvidenceTools)
        self.assertEqual(
            load_frozen_available_evidence_actions(),
            (EvidenceAction.SEARCH_OFFICIAL_DOCS,),
        )


if __name__ == "__main__":
    unittest.main()
