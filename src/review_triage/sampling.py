"""NODE-06 stable deterministic batch sampling."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from review_triage.errors import PolicyConfigurationError
from review_triage.schemas import (
    FinalPolicyRoute,
    RouteDecision,
    SamplingBatchResult,
    SamplingDecision,
)


SAMPLING_POLICY_ID = "sample_audit_v1"
DEFAULT_SAMPLE_RATE = 0.10
DEFAULT_SAMPLING_SEED = "sample_audit_v1_fixed_seed"


def _stable_score(*, eval_run_id: str, case_id: str, sampling_seed: str) -> str:
    identity = f"{SAMPLING_POLICY_ID}|{sampling_seed}|{eval_run_id}|{case_id}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def node_06_sample_batch(
    *,
    eval_run_id: str,
    route_decisions: Sequence[RouteDecision],
    sampling_seed: str = DEFAULT_SAMPLING_SEED,
    sample_rate: float = DEFAULT_SAMPLE_RATE,
) -> SamplingBatchResult:
    """Sample only NODE-05 SAMPLE_POOL cases, independent of input order."""

    if not eval_run_id.strip():
        raise PolicyConfigurationError("NODE-06 requires eval_run_id")
    if not sampling_seed.strip():
        raise PolicyConfigurationError("NODE-06 requires a non-empty sampling seed")
    if not 0 < sample_rate <= 1:
        raise PolicyConfigurationError("NODE-06 sample_rate must be in (0, 1]")
    case_ids = [decision.case_id for decision in route_decisions]
    if len(case_ids) != len(set(case_ids)):
        raise PolicyConfigurationError("NODE-06 route decisions contain duplicate case_id")

    pool_case_ids = sorted(
        decision.case_id
        for decision in route_decisions
        if decision.final_policy_route == FinalPolicyRoute.SAMPLE_POOL
    )
    pool_size = len(pool_case_ids)
    sample_size = 0 if pool_size == 0 else math.ceil(pool_size * sample_rate)
    ranked = sorted(
        pool_case_ids,
        key=lambda case_id: (
            _stable_score(
                eval_run_id=eval_run_id,
                case_id=case_id,
                sampling_seed=sampling_seed,
            ),
            case_id,
        ),
    )
    selected = set(ranked[:sample_size])
    decisions = [
        SamplingDecision(
            case_id=case_id,
            eval_run_id=eval_run_id,
            sample_rate=sample_rate,
            pool_size=pool_size,
            sample_size=sample_size,
            selected_for_audit=case_id in selected,
            sampling_seed=sampling_seed,
            selection_reason=(
                "Selected by stable SHA-256 rank over fixed seed, eval_run_id, "
                "and case_id."
                if case_id in selected
                else "Not within the deterministic top sample_size ranks."
            ),
        )
        for case_id in pool_case_ids
    ]
    return SamplingBatchResult(
        eval_run_id=eval_run_id,
        sample_rate=sample_rate,
        pool_size=pool_size,
        sample_size=sample_size,
        sampling_seed=sampling_seed,
        pool_case_ids=pool_case_ids,
        selected_case_ids=sorted(selected),
        decisions=decisions,
    )
