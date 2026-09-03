"""Data-only validation for Demo Official Evidence Pack v1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "official_terminology_snapshot_v1.json"

EXPECTED_FACT_IDS = {
    "SIG-01", "SIG-02", "SIG-03", "SIG-04",
    "PP-01", "PP-02", "PP-03", "PP-04",
    "TEN-01", "TEN-02", "TEN-03", "TEN-04",
}
EXPECTED_CONTROL_IDS = {"NC-A", "NC-B"}
REQUIRED_FACT_FIELDS = {
    "fact_id", "source_term", "target_form", "authority_scope", "locale_scope",
    "source_ref", "supporting_excerpt", "excerpt_location", "claim_key",
    "claim_value", "scenario", "is_official_source",
    "supports_normative_claim", "claim_scope",
}
FORBIDDEN_TOKENS = (
    "case_id", "human gt", "human_gt", "final route", "final_route",
    "corrected translation", "corrected_translation", "mkt-020",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def nonempty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def content_hash_without_self(data: dict[str, object]) -> str:
    payload = dict(data)
    payload.pop("snapshot_sha256_excluding_self", None)
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def main() -> None:
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    facts = data["positive_facts"]
    controls = data["negative_controls"]
    sources = data["source_documents"]

    fact_ids = [fact["fact_id"] for fact in facts]
    control_ids = [control["control_id"] for control in controls]
    source_refs = [source["source_ref"] for source in sources]

    require(len(facts) == 12, "positive fact count must be 12")
    require(set(fact_ids) == EXPECTED_FACT_IDS, "positive fact IDs do not match freeze scope")
    require(len(fact_ids) == len(set(fact_ids)), "fact_id values must be unique")
    require(len(controls) == 2, "negative control count must be 2")
    require(set(control_ids) == EXPECTED_CONTROL_IDS, "negative control IDs do not match freeze scope")
    require(len(source_refs) == len(set(source_refs)), "source_ref values must be unique")

    source_ref_set = set(source_refs)
    for fact in facts:
        missing = REQUIRED_FACT_FIELDS - set(fact)
        require(not missing, f"{fact['fact_id']} missing fields: {sorted(missing)}")
        for field in REQUIRED_FACT_FIELDS:
            require(nonempty(fact[field]), f"{fact['fact_id']} has empty required field: {field}")
        require(fact["source_ref"] in source_ref_set, f"{fact['fact_id']} has unresolved source_ref")
        for ref in fact.get("supporting_source_refs", []):
            require(ref in source_ref_set, f"{fact['fact_id']} has unresolved supporting source_ref: {ref}")
        require(fact["is_official_source"] is True, f"{fact['fact_id']} is not verified first-party")
        require(fact["supports_normative_claim"] is True, f"{fact['fact_id']} excerpt does not support its scoped claim")

    facts_by_id = {fact["fact_id"]: fact for fact in facts}
    for fact_id in ("PP-01", "PP-02", "PP-03"):
        require(facts_by_id[fact_id]["locale_scope"]["target"] == "zh_C2", f"{fact_id} locale was rewritten")
    require(facts_by_id["PP-04"]["locale_scope"]["target"] == "zh_US", "PP-04 locale was rewritten")

    signal_commit = "git_commit:879651dc47a7b18b67e7aea52a25197875024680"
    signal_sources = [source for source in sources if source["source_ref"].startswith("SIG-ANDROID-")]
    require(len(signal_sources) == 2, "Signal must have exactly two locale source documents")
    require({source["version_identifier"] for source in signal_sources} == {signal_commit}, "Signal locale files are not pinned to the same commit")
    expected_keys = {
        "SIG-01": "save",
        "SIG-02": "delete",
        "SIG-03": "AttachmentKeyboard_gallery",
        "SIG-04": "AttachmentKeyboard_go_to_settings",
    }
    for fact_id, key in expected_keys.items():
        require(facts_by_id[fact_id]["excerpt_location"]["key"] == key, f"{fact_id} string key mismatch")
        require(facts_by_id[fact_id]["excerpt_location"]["alignment"] == "same_key_same_git_commit", f"{fact_id} alignment is not frozen")

    controls_by_id = {control["control_id"]: control for control in controls}
    nc_a = controls_by_id["NC-A"]
    require(nc_a["is_official_source"] is True, "NC-A official flag must be true")
    require(nc_a["supports_normative_claim"] is False, "NC-A normative support must be false")
    nc_b = controls_by_id["NC-B"]
    require(nc_b["control_type"] == "coverage_negative", "NC-B must be a coverage-negative control")
    require(nc_b["positive_evidence_candidate"] is False, "NC-B must not be a positive candidate")
    require(nc_b["pack_coverage"] is False, "NC-B must remain outside pack coverage")
    require("NC-B" not in fact_ids, "NC-B leaked into positive facts")
    require(nc_b["source_ref"] in source_ref_set, "NC-B source_ref is unresolved")

    serialized = json.dumps(data, ensure_ascii=False).lower()
    for token in FORBIDDEN_TOKENS:
        require(token not in serialized, f"forbidden token present in snapshot: {token}")

    computed_content_hash = content_hash_without_self(data)
    require(data["snapshot_sha256_excluding_self"] == computed_content_hash, "snapshot content hash mismatch")

    result = {
        "status": "PASS",
        "positive_fact_count": len(facts),
        "negative_control_count": len(controls),
        "source_document_count": len(sources),
        "snapshot_content_sha256_excluding_self": computed_content_hash,
        "checks": 20,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
