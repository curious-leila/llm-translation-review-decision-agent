"""Read-only loader for the human-approved Demo Evidence Pack v1.

This module validates and projects frozen data only. It deliberately does not
perform retrieval, matching, evidence admission, sufficiency, or routing.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Mapping, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
)

from review_triage.schemas import EvidenceCandidate, EvidenceProvenance


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_EVIDENCE_PACK_V1_DIR = PROJECT_ROOT / "artifacts/demo_evidence_v1"
MANIFEST_V1_FILENAME = "manifest_v1.json"
SNAPSHOT_V1_FILENAME = "official_terminology_snapshot_v1.json"

EXPECTED_ARTIFACT_ID = "demo-official-evidence-pack-v1"
EXPECTED_ARTIFACT_TYPE = "OFFICIAL_TERMINOLOGY_SNAPSHOT"
EXPECTED_VERSION = "1.0.0"
EXPECTED_STATUS = "HUMAN_APPROVED_DATA_FREEZE"
EXPECTED_SIGNAL_VERSION = "879651dc47a7b18b67e7aea52a25197875024680"
EXPECTED_SIGNAL_STRING_KEYS = {
    "SIG-01": "save",
    "SIG-02": "delete",
    "SIG-03": "AttachmentKeyboard_gallery",
    "SIG-04": "AttachmentKeyboard_go_to_settings",
}
EXPECTED_FACT_IDS = frozenset(
    {
        "SIG-01", "SIG-02", "SIG-03", "SIG-04",
        "PP-01", "PP-02", "PP-03", "PP-04",
        "TEN-01", "TEN-02", "TEN-03", "TEN-04",
    }
)
EXPECTED_CONTROL_IDS = frozenset({"NC-A", "NC-B"})
EXPECTED_FAMILY_COUNTS = MappingProxyType(
    {
        "Signal Android UI": 4,
        "PayPal customer support": 4,
        "Lenzing / TENCEL marketing": 4,
    }
)

NonEmptyStr = Annotated[StrictStr, Field(min_length=1)]
_ModelT = TypeVar("_ModelT", bound=BaseModel)


class DemoEvidencePackV1Error(ValueError):
    """A fail-fast, diagnosable Demo Evidence Pack v1 loading error."""

    def __init__(self, code: str, message: str, *, path: Path | None = None) -> None:
        self.code = code
        self.path = path
        location = f" ({path})" if path is not None else ""
        super().__init__(f"{code}: {message}{location}")


class DemoEvidenceCandidateV1(EvidenceCandidate):
    """Immutable ``EvidenceCandidate`` projection of one approved positive fact."""

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=False,
        str_strip_whitespace=True,
        frozen=True,
    )


class _FrozenPackModel(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


class DemoLocaleScopeV1(_FrozenPackModel):
    source: NonEmptyStr
    target: NonEmptyStr


class DemoSourceDocumentV1(_FrozenPackModel):
    source_ref: NonEmptyStr
    authority: NonEmptyStr
    resource_title: NonEmptyStr
    canonical_url: NonEmptyStr
    exact_locale: NonEmptyStr
    source_type: NonEmptyStr
    retrieved_at: NonEmptyStr
    frozen_at: NonEmptyStr
    version_identifier: NonEmptyStr
    source_provenance: NonEmptyStr
    retrieval_url: NonEmptyStr | None = None
    article_id: NonEmptyStr | None = None


class DemoPositiveTerminologyFactV1(_FrozenPackModel):
    fact_id: NonEmptyStr
    evidence_family: NonEmptyStr
    source_term: NonEmptyStr
    target_form: NonEmptyStr
    authority_scope: NonEmptyStr
    locale_scope: DemoLocaleScopeV1
    source_ref: NonEmptyStr
    supporting_source_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    supporting_excerpt: Mapping[NonEmptyStr, NonEmptyStr] = Field(min_length=1)
    excerpt_location: Mapping[NonEmptyStr, NonEmptyStr] = Field(min_length=1)
    claim_key: NonEmptyStr
    claim_value: NonEmptyStr
    scenario: NonEmptyStr
    is_official_source: StrictBool
    supports_normative_claim: StrictBool
    claim_scope: NonEmptyStr
    provenance_notes: NonEmptyStr | None = None

    @field_validator("supporting_excerpt", "excerpt_location", mode="after")
    @classmethod
    def freeze_mapping(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        return MappingProxyType(dict(value))


class DemoNegativeControlV1(_FrozenPackModel):
    control_id: NonEmptyStr
    control_type: NonEmptyStr
    source_ref: NonEmptyStr
    source_term: NonEmptyStr
    control_scope: NonEmptyStr
    expected_evidence_state: NonEmptyStr
    target_form_under_test: NonEmptyStr | None = None
    is_official_source: StrictBool | None = None
    supports_normative_claim: StrictBool | None = None
    positive_evidence_candidate: StrictBool | None = None
    pack_coverage: StrictBool | None = None


class _DemoEvidenceScopeV1(_FrozenPackModel):
    purpose: NonEmptyStr
    families: tuple[NonEmptyStr, ...] = Field(min_length=1)
    positive_fact_count: StrictInt
    negative_control_count: StrictInt


class _DemoEvidenceManifestV1(_FrozenPackModel):
    artifact_id: NonEmptyStr
    version: NonEmptyStr
    freeze_type: NonEmptyStr
    frozen_at: NonEmptyStr
    snapshot_file: NonEmptyStr
    snapshot_sha256: NonEmptyStr
    snapshot_content_sha256_excluding_self: NonEmptyStr
    positive_fact_count: StrictInt
    negative_control_count: StrictInt
    source_document_count: StrictInt
    family_fact_counts: dict[NonEmptyStr, StrictInt]
    signal_version: NonEmptyStr
    paypal_target_locales: tuple[NonEmptyStr, ...]
    blocked_fact_ids: tuple[NonEmptyStr, ...]
    runtime_wiring: NonEmptyStr
    admission_basis: NonEmptyStr


class _DemoEvidenceSnapshotV1(_FrozenPackModel):
    artifact_id: NonEmptyStr
    artifact_type: NonEmptyStr
    version: NonEmptyStr
    status: NonEmptyStr
    frozen_at: NonEmptyStr
    runtime_wiring: NonEmptyStr
    scope: _DemoEvidenceScopeV1
    source_documents: tuple[DemoSourceDocumentV1, ...]
    positive_facts: tuple[DemoPositiveTerminologyFactV1, ...]
    negative_controls: tuple[DemoNegativeControlV1, ...]
    snapshot_sha256_excluding_self: NonEmptyStr


@dataclass(frozen=True)
class DemoEvidencePackV1:
    artifact_id: str
    artifact_type: str
    version: str
    status: str
    frozen_at: str
    snapshot_path: Path
    snapshot_sha256: str
    snapshot_content_sha256_excluding_self: str
    signal_version: str
    source_documents: tuple[DemoSourceDocumentV1, ...]
    positive_facts: tuple[DemoPositiveTerminologyFactV1, ...]
    negative_controls: tuple[DemoNegativeControlV1, ...]
    positive_evidence_candidates: tuple[DemoEvidenceCandidateV1, ...]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _content_hash_without_self(data: Mapping[str, Any]) -> str:
    payload = dict(data)
    payload.pop("snapshot_sha256_excluding_self", None)
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _read_json_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as error:
        raise DemoEvidencePackV1Error(
            "FILE_NOT_FOUND", f"required {label} file is missing", path=path
        ) from error
    except OSError as error:
        raise DemoEvidencePackV1Error(
            "FILE_READ_ERROR", f"cannot read {label}: {error}", path=path
        ) from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        detail = str(error)
        if isinstance(error, json.JSONDecodeError):
            detail = f"{error.msg} at line {error.lineno}, column {error.colno}"
        raise DemoEvidencePackV1Error(
            "JSON_PARSE_ERROR", f"cannot parse {label}: {detail}", path=path
        ) from error
    if not isinstance(value, dict):
        raise DemoEvidencePackV1Error(
            "SCHEMA_ERROR", f"{label} root must be a JSON object", path=path
        )
    return value, raw


def _parse_model(
    model: type[_ModelT], data: dict[str, Any], *, label: str
) -> _ModelT:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_url=False)
        )
        code = (
            "REQUIRED_FIELD_MISSING"
            if any(item["type"] == "missing" for item in error.errors())
            else "SCHEMA_ERROR"
        )
        raise DemoEvidencePackV1Error(
            code, f"{label} basic schema validation failed: {details}"
        ) from error


def _validate_v1_contract(
    *,
    manifest: _DemoEvidenceManifestV1,
    snapshot: _DemoEvidenceSnapshotV1,
) -> None:
    sources = snapshot.source_documents
    facts = snapshot.positive_facts
    controls = snapshot.negative_controls
    source_refs = [source.source_ref for source in sources]
    if len(source_refs) != len(set(source_refs)):
        raise DemoEvidencePackV1Error("DUPLICATE_SOURCE_REF", "source_ref values must be unique")

    fact_ids: set[str] = set()
    forbidden_control_fields = {
        "control_id", "control_type", "positive_evidence_candidate", "pack_coverage"
    }
    for fact in facts:
        mixed = forbidden_control_fields & set(fact.model_extra or {})
        if mixed:
            raise DemoEvidencePackV1Error(
                "CLASSIFICATION_ERROR",
                f"positive fact {fact.fact_id} contains negative-control fields: {sorted(mixed)}",
            )
        if fact.fact_id in fact_ids:
            raise DemoEvidencePackV1Error("DUPLICATE_FACT_ID", f"duplicate fact_id: {fact.fact_id}")
        fact_ids.add(fact.fact_id)
        unresolved = {fact.source_ref, *fact.supporting_source_refs} - set(source_refs)
        if unresolved:
            raise DemoEvidencePackV1Error(
                "UNRESOLVED_SOURCE_REF",
                f"{fact.fact_id} has unknown source_ref(s): {sorted(unresolved)}",
            )
        if not fact.is_official_source or not fact.supports_normative_claim:
            raise DemoEvidencePackV1Error(
                "CLASSIFICATION_ERROR",
                f"positive fact {fact.fact_id} must remain official and positive",
            )

    control_ids: set[str] = set()
    forbidden_positive_fields = {"fact_id", "target_form", "claim_key", "claim_value"}
    for control in controls:
        mixed = forbidden_positive_fields & set(control.model_extra or {})
        if mixed or control.control_id in fact_ids or control.control_id in control_ids:
            raise DemoEvidencePackV1Error(
                "CLASSIFICATION_ERROR",
                f"duplicate or mixed negative control {control.control_id}",
            )
        control_ids.add(control.control_id)
        if control.source_ref not in source_refs:
            raise DemoEvidencePackV1Error(
                "UNRESOLVED_SOURCE_REF",
                f"{control.control_id} references unknown source_ref: {control.source_ref}",
            )
        if control.positive_evidence_candidate is True:
            raise DemoEvidencePackV1Error(
                "CLASSIFICATION_ERROR",
                f"negative control {control.control_id} cannot be a positive evidence candidate",
            )

    if fact_ids != EXPECTED_FACT_IDS:
        raise DemoEvidencePackV1Error(
            "CLASSIFICATION_ERROR", "positive fact IDs do not match the approved v1 scope"
        )
    if control_ids != EXPECTED_CONTROL_IDS:
        raise DemoEvidencePackV1Error(
            "CLASSIFICATION_ERROR", "negative control IDs do not match the approved v1 scope"
        )
    family_counts = Counter(fact.evidence_family for fact in facts)
    if dict(family_counts) != dict(EXPECTED_FAMILY_COUNTS):
        raise DemoEvidencePackV1Error(
            "MANIFEST_MISMATCH", f"family fact counts are invalid: {dict(family_counts)}"
        )
    if manifest.family_fact_counts != dict(family_counts):
        raise DemoEvidencePackV1Error(
            "MANIFEST_MISMATCH", "manifest family_fact_counts do not match snapshot facts"
        )
    if manifest.blocked_fact_ids:
        raise DemoEvidencePackV1Error(
            "MANIFEST_MISMATCH", "Demo Evidence Pack v1 must not contain blocked fact IDs"
        )
    for field, actual in {
        "positive_fact_count": len(facts),
        "negative_control_count": len(controls),
        "source_document_count": len(sources),
    }.items():
        if getattr(manifest, field) != actual:
            raise DemoEvidencePackV1Error(
                "MANIFEST_MISMATCH", f"manifest {field} does not match snapshot"
            )
    if (
        snapshot.scope.positive_fact_count != len(facts)
        or snapshot.scope.negative_control_count != len(controls)
    ):
        raise DemoEvidencePackV1Error(
            "MANIFEST_MISMATCH", "snapshot scope counts do not match loaded records"
        )

    facts_by_id = {fact.fact_id: fact for fact in facts}
    for fact_id in ("PP-01", "PP-02", "PP-03"):
        if facts_by_id[fact_id].locale_scope.target != "zh_C2":
            raise DemoEvidencePackV1Error("LOCALE_MISMATCH", f"{fact_id} target locale must remain zh_C2")
    if facts_by_id["PP-04"].locale_scope.target != "zh_US":
        raise DemoEvidencePackV1Error("LOCALE_MISMATCH", "PP-04 target locale must remain zh_US")
    if manifest.paypal_target_locales != ("zh_C2", "zh_US"):
        raise DemoEvidencePackV1Error(
            "MANIFEST_MISMATCH", "manifest PayPal target locales do not match frozen v1 values"
        )

    signal_identifier = f"git_commit:{EXPECTED_SIGNAL_VERSION}"
    signal_sources = [source for source in sources if source.source_ref.startswith("SIG-ANDROID-")]
    if len(signal_sources) != 2 or any(
        source.version_identifier != signal_identifier for source in signal_sources
    ):
        raise DemoEvidencePackV1Error(
            "SIGNAL_VERSION_MISMATCH",
            "Signal source metadata must contain both locale files at the frozen commit",
        )
    if manifest.signal_version != EXPECTED_SIGNAL_VERSION:
        raise DemoEvidencePackV1Error(
            "SIGNAL_VERSION_MISMATCH", "manifest Signal version is missing or not the frozen commit"
        )
    for fact_id, expected_key in EXPECTED_SIGNAL_STRING_KEYS.items():
        fact = facts_by_id[fact_id]
        if (
            fact.excerpt_location.get("key") != expected_key
            or fact.excerpt_location.get("alignment") != "same_key_same_git_commit"
        ):
            raise DemoEvidencePackV1Error(
                "SIGNAL_VERSION_MISMATCH",
                f"{fact_id} must retain its frozen Signal string key and commit alignment",
            )

    controls_by_id = {control.control_id: control for control in controls}
    nc_a = controls_by_id["NC-A"]
    if (
        nc_a.control_type != "official_but_nonnormative"
        or nc_a.is_official_source is not True
        or nc_a.supports_normative_claim is not False
    ):
        raise DemoEvidencePackV1Error(
            "CLASSIFICATION_ERROR", "NC-A must remain official-but-nonnormative"
        )
    nc_b = controls_by_id["NC-B"]
    if (
        nc_b.control_type != "coverage_negative"
        or nc_b.positive_evidence_candidate is not False
        or nc_b.pack_coverage is not False
        or nc_b.target_form_under_test is not None
    ):
        raise DemoEvidencePackV1Error(
            "CLASSIFICATION_ERROR", "NC-B must remain a coverage-negative control without a target answer"
        )


def _to_candidate(
    fact: DemoPositiveTerminologyFactV1, *, validation_status: str
) -> DemoEvidenceCandidateV1:
    content = _canonical_json(
        {
            "authority_scope": fact.authority_scope,
            "supporting_excerpt": dict(fact.supporting_excerpt),
            "claim_scope": fact.claim_scope,
        }
    )
    return DemoEvidenceCandidateV1(
        candidate_id=fact.fact_id,
        term_candidate=fact.source_term,
        provenance=EvidenceProvenance.OFFICIAL_DOCS,
        source_ref=fact.source_ref,
        content=content,
        claim_key=fact.claim_key,
        claim_value=fact.claim_value,
        target_locale=fact.locale_scope.target,
        scenario=fact.scenario,
        is_official_source=fact.is_official_source,
        supports_normative_claim=fact.supports_normative_claim,
        validation_status=validation_status,
    )


def load_demo_evidence_pack_v1(
    pack_dir: str | Path = DEMO_EVIDENCE_PACK_V1_DIR,
) -> DemoEvidencePackV1:
    """Load and validate the explicitly selected Demo Evidence Pack v1.

    ``version`` is the artifact/schema contract for this frozen v1 format.
    There is no fallback to Day2 evidence or to a mutable upstream source.
    """

    directory = Path(pack_dir)
    manifest_data, _ = _read_json_object(
        directory / MANIFEST_V1_FILENAME, label="Demo Evidence Pack v1 manifest"
    )
    manifest = _parse_model(
        _DemoEvidenceManifestV1, manifest_data, label="Demo Evidence Pack v1 manifest"
    )
    if (
        manifest.artifact_id != EXPECTED_ARTIFACT_ID
        or manifest.version != EXPECTED_VERSION
        or manifest.snapshot_file != SNAPSHOT_V1_FILENAME
    ):
        raise DemoEvidencePackV1Error("VERSION_MISMATCH", "manifest is not the expected v1 pack")
    if manifest.freeze_type != "DATA_EVIDENCE_ONLY" or manifest.runtime_wiring != "NONE":
        raise DemoEvidencePackV1Error(
            "SCHEMA_ERROR", "manifest must remain a data-only freeze with no runtime wiring"
        )

    snapshot_path = directory / SNAPSHOT_V1_FILENAME
    snapshot_data, snapshot_raw = _read_json_object(
        snapshot_path, label="Demo Evidence Pack v1 snapshot"
    )
    snapshot = _parse_model(
        _DemoEvidenceSnapshotV1, snapshot_data, label="Demo Evidence Pack v1 snapshot"
    )
    if (
        (snapshot.artifact_id, snapshot.artifact_type, snapshot.version)
        != (EXPECTED_ARTIFACT_ID, EXPECTED_ARTIFACT_TYPE, EXPECTED_VERSION)
    ):
        raise DemoEvidencePackV1Error("VERSION_MISMATCH", "snapshot is not the expected v1 pack")
    if snapshot.status != EXPECTED_STATUS or snapshot.runtime_wiring != "NONE":
        raise DemoEvidencePackV1Error(
            "SCHEMA_ERROR", "snapshot must remain a human-approved freeze with no runtime wiring"
        )

    actual_file_hash = hashlib.sha256(snapshot_raw).hexdigest()
    if manifest.snapshot_sha256 != actual_file_hash:
        raise DemoEvidencePackV1Error(
            "INTEGRITY_MISMATCH",
            f"snapshot file SHA-256 mismatch: declared={manifest.snapshot_sha256}, actual={actual_file_hash}",
            path=snapshot_path,
        )
    actual_content_hash = _content_hash_without_self(snapshot_data)
    if snapshot.snapshot_sha256_excluding_self != actual_content_hash:
        raise DemoEvidencePackV1Error(
            "INTEGRITY_MISMATCH",
            "snapshot content SHA-256 does not match its embedded declaration",
            path=snapshot_path,
        )
    if manifest.snapshot_content_sha256_excluding_self != actual_content_hash:
        raise DemoEvidencePackV1Error(
            "INTEGRITY_MISMATCH", "manifest does not bind the snapshot canonical content hash"
        )

    _validate_v1_contract(manifest=manifest, snapshot=snapshot)
    candidates = tuple(
        _to_candidate(fact, validation_status=EXPECTED_STATUS)
        for fact in snapshot.positive_facts
    )
    return DemoEvidencePackV1(
        artifact_id=snapshot.artifact_id,
        artifact_type=snapshot.artifact_type,
        version=snapshot.version,
        status=snapshot.status,
        frozen_at=snapshot.frozen_at,
        snapshot_path=snapshot_path,
        snapshot_sha256=actual_file_hash,
        snapshot_content_sha256_excluding_self=actual_content_hash,
        signal_version=manifest.signal_version,
        source_documents=snapshot.source_documents,
        positive_facts=snapshot.positive_facts,
        negative_controls=snapshot.negative_controls,
        positive_evidence_candidates=candidates,
    )
