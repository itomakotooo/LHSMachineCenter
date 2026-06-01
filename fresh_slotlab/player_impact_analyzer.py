from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import re
import shutil
import signal
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from pathlib import Path
from typing import Any

# Phase 3 / Phase 5: default manifest root resolved relative to repo. Pure
# path arithmetic, no I/O at import.
_DEFAULT_MANIFEST_ROOT = (
    Path(__file__).resolve().parent.parent
    / "slot_designer" / "configs" / "machine_manifests"
)

# Dual-path import for the trigger-session helper: dir-level script
# invocation (``python fresh_slotlab/player_impact_analyzer.py``) puts
# fresh_slotlab/ on sys.path so the top-level name works; package-style
# invocation from backend (cwd = repo root) needs the qualified path.
# Keeping this at module top rather than inside the hot loop ensures a
# single import attempt per process.
try:
    from fresh_slotlab.trigger_sessions import (
        _round_has_credited_win,
        compute_trigger_sessions,
    )  # noqa: E402
    from fresh_slotlab.round_win import (
        RoundWinRule,
        extract_round_payouts,
        extract_round_win,
        load_rules_for_machine,
    )
    from fresh_slotlab.round_classification import (
        detect_cycle_peak,
        is_wild_nudge_round,
    )
    # chunk_index / rawdata_index are also script-mode-fragile: they
    # used to be lazy-imported inside best-effort try/except blocks,
    # which silently swallowed the ImportError in script mode and
    # defeated the inverted-md5 / chunk-sidecar optimizations. Hoist
    # to the top so the same dual-path fallback covers them — the
    # call-site try/except guards still catch real I/O / JSON errors
    # at runtime, but module-not-found is no longer one of them.
    from fresh_slotlab.chunk_index import (
        _rebuild_by_md5,
        get_chunks_index,
        update_chunk_entry,
    )
    from fresh_slotlab.rawdata_index import update_entry as _rawdata_index_update_entry
    # P1-B4: t_critical_95 consolidated to sampler.py (canonical source).
    # Ticket: phase1/01_t_critical_table_dedup §1.
    from fresh_slotlab.sampler import t_critical_95
    # P1-B3: session_halfwidth_pp consolidated to sampler.py (canonical source).
    # Ticket: phase1/09_session_ci_halfwidth_dedup §1.
    from fresh_slotlab.sampler import session_halfwidth_pp
    # P1-B1: _lookup_machine_md5 consolidated to machine_md5.py (canonical source).
    # Ticket: phase1/07_lookup_machine_md5_dedup §1.
    from fresh_slotlab.machine_md5 import lookup_machine_md5 as _lookup_machine_md5
except ImportError:  # running as a standalone script, not a package member
    from trigger_sessions import (  # type: ignore[no-redef]
        _round_has_credited_win,
        compute_trigger_sessions,
    )
    from round_win import (  # type: ignore[no-redef]
        RoundWinRule,
        extract_round_payouts,
        extract_round_win,
        load_rules_for_machine,
    )
    from round_classification import (  # type: ignore[no-redef]
        detect_cycle_peak,
        is_wild_nudge_round,
    )
    from chunk_index import (  # type: ignore[no-redef]
        _rebuild_by_md5,
        get_chunks_index,
        update_chunk_entry,
    )
    from rawdata_index import update_entry as _rawdata_index_update_entry  # type: ignore[no-redef]
    from sampler import t_critical_95  # type: ignore[no-redef]  # P1-B4
    from sampler import session_halfwidth_pp  # type: ignore[no-redef]  # P1-B3
    from machine_md5 import lookup_machine_md5 as _lookup_machine_md5  # type: ignore[no-redef]  # P1-B1

# P2-B1a: 14 chunk-parsing helpers + 1 exception + 8 constants moved to
# fresh_slotlab/analyzer/core/parser.py per 04_v5 §6.2 deliverable 1.
# P2-B1b: parse_chunk_response (the 1857-line orchestrator) also moved.
# Re-exported here so all existing callers continue to work via
# ``from fresh_slotlab.player_impact_analyzer import parse_rounds`` etc.
try:
    from fresh_slotlab.analyzer.core.parser import (
        ChunkIntegrityError,
        PAYLINE_RE,
        _BASELINE_ROUND_FIELDS,
        _ENVELOPE_PEEK_BYTES,
        _ENVELOPE_PEEK_RE,
        _REMARKS_ADDFREESPINS_COUNT_RE,
        _REMARKS_EXTRARATIO_RE,
        _REMARKS_FREESPIN_RE,
        _REQUIRED_BET_FIELDS_ANY,
        _REQUIRED_ROUND_FIELDS,
        _canonical_payload_bytes,
        _check_round_schema,
        _compute_bonus_correction,
        _compute_nf_correction,
        _compute_upstream_schema_fingerprint,
        _payload_sha256,
        load_chunk_envelope,
        parse_chunk_response,
        parse_freespin_remarks,
        parse_paylines,
        parse_rln_codes,
        parse_rounds,
        peek_chunk_envelope,
        split_symbols,
    )
except ImportError:  # running as standalone script
    from analyzer.core.parser import (  # type: ignore[no-redef]
        ChunkIntegrityError,
        PAYLINE_RE,
        _BASELINE_ROUND_FIELDS,
        _ENVELOPE_PEEK_BYTES,
        _ENVELOPE_PEEK_RE,
        _REMARKS_ADDFREESPINS_COUNT_RE,
        _REMARKS_EXTRARATIO_RE,
        _REMARKS_FREESPIN_RE,
        _REQUIRED_BET_FIELDS_ANY,
        _REQUIRED_ROUND_FIELDS,
        _canonical_payload_bytes,
        _check_round_schema,
        _compute_bonus_correction,
        _compute_nf_correction,
        _compute_upstream_schema_fingerprint,
        _payload_sha256,
        load_chunk_envelope,
        parse_chunk_response,
        parse_freespin_remarks,
        parse_paylines,
        parse_rln_codes,
        parse_rounds,
        peek_chunk_envelope,
        split_symbols,
    )

# P2-B2: 9 shared utility helpers consolidated into core/_utils.py.
# Re-exported here so ``from fresh_slotlab.player_impact_analyzer import
# to_float`` etc. keeps working for all existing callers.
try:
    from fresh_slotlab.analyzer.core._utils import (
        to_float,
        blank_like_symbol,
        bonus_chain_depth_bucket,
        return_bucket,
        _empty_bankruptcy_tier,
        _extract_bankruptcy_reps,
        simulate_bankruptcy_from_response,
        _DEFAULT_BANKROLL_MULTIPLIERS,
        _DEFAULT_BANKRUPTCY_SESSION_SPINS,
    )
except ImportError:  # running as standalone script
    from analyzer.core._utils import (  # type: ignore[no-redef]
        to_float,
        blank_like_symbol,
        bonus_chain_depth_bucket,
        return_bucket,
        _empty_bankruptcy_tier,
        _extract_bankruptcy_reps,
        simulate_bankruptcy_from_response,
        _DEFAULT_BANKROLL_MULTIPLIERS,
        _DEFAULT_BANKRUPTCY_SESSION_SPINS,
    )

# P2-B2: 13 aggregation-only symbols + RETURN_BUCKET_ORDER moved to
# core/aggregator.py. Re-exported here so all existing callers continue
# to resolve via ``from fresh_slotlab.player_impact_analyzer import ...``.
try:
    from fresh_slotlab.analyzer.core.aggregator import (
        RETURN_BUCKET_ORDER,
        _BankruptcyStreamAccumulator,
        compute_bankruptcy_percentiles,
        fastest_bankruptcy_spins_from_list,
        median_spins_from_list,
        build_multiplier_bucket_rows,
        quantile_from_hist,
        classify_volatility,
        classify_experience_archetype,
        _metric_path_get,
        _eval_operator,
        _deviation,
        evaluate_guideline_comparison,
    )
except ImportError:  # running as standalone script
    from analyzer.core.aggregator import (  # type: ignore[no-redef]
        RETURN_BUCKET_ORDER,
        _BankruptcyStreamAccumulator,
        compute_bankruptcy_percentiles,
        fastest_bankruptcy_spins_from_list,
        median_spins_from_list,
        build_multiplier_bucket_rows,
        quantile_from_hist,
        classify_volatility,
        classify_experience_archetype,
        _metric_path_get,
        _eval_operator,
        _deviation,
        evaluate_guideline_comparison,
    )

# P2-B3: _save_chunk_cache + write_summary_json moved to core/writer.py.
# CHUNK_CACHE_VERSION and utc_now() are also canonical in writer.py now.
# Re-exported here so all existing callers continue to resolve via
# ``from fresh_slotlab.player_impact_analyzer import _save_chunk_cache`` etc.
try:
    from fresh_slotlab.analyzer.core.writer import (
        CHUNK_CACHE_VERSION,
        _save_chunk_cache,
        utc_now,
        write_summary_json,
    )
except ImportError:  # running as standalone script
    from analyzer.core.writer import (  # type: ignore[no-redef]
        CHUNK_CACHE_VERSION,
        _save_chunk_cache,
        utc_now,
        write_summary_json,
    )

# P2-B4: 8 HTTP/sampling helpers + ENDPOINT_URL constants + AIMD constants +
# DEFAULT_GUIDELINE_RULES_PATH moved to core/base_pipeline.py.
# Re-exported here so all existing callers continue to resolve via
# ``from fresh_slotlab.player_impact_analyzer import parse_args`` etc.
#
# CAUTION (ENDPOINT_URL snapshot binding): the ``ENDPOINT_URL`` re-export
# below is a string-VALUE snapshot taken at this module's import time.
# Python's ``from X import Y`` for an immutable string copies the value;
# it does NOT keep a live reference to ``X.Y``. Therefore reading
# ``pia.ENDPOINT_URL`` after main() runs returns the DEFAULT value,
# not the operator-supplied --endpoint-url. The only correct mutation
# path is ``_core_base_pipeline.ENDPOINT_URL = ...`` (which main() does
# at line ~1035 below) — the live read site inside base_pipeline.py's
# post_json picks up the new value because post_json resolves the
# name from its own module namespace at call time. Code that needs
# the runtime endpoint MUST read ``_core_base_pipeline.ENDPOINT_URL``,
# not ``pia.ENDPOINT_URL``.
# main() mutates base_pipeline.ENDPOINT_URL directly (Option B per §3 C3):
#   import fresh_slotlab.analyzer.core.base_pipeline as _core_bp
#   _core_bp.ENDPOINT_URL = args.endpoint_url
try:
    import fresh_slotlab.analyzer.core.base_pipeline as _core_base_pipeline
    from fresh_slotlab.analyzer.core.base_pipeline import (
        CHUNK_SPINS_GROWTH,
        CIRCUIT_PAUSE_S,
        DEFAULT_ENDPOINT_URL,
        DEFAULT_GUIDELINE_RULES_PATH,
        ENDPOINT_URL,
        MIN_CHUNK_SPINS,
        SUCCESS_STREAK_FOR_GROW,
        _classify_failure,
        _RETRYABLE_HTTP_CODES,
        aimd_tune,
        make_payload,
        parse_args,
        post_json,
        post_json_with_retry,
        run_sampling_chunk,
        select_replay_chunks_by_md5,
    )
except ImportError:  # running as standalone script
    import analyzer.core.base_pipeline as _core_base_pipeline  # type: ignore[no-redef]
    from analyzer.core.base_pipeline import (  # type: ignore[no-redef]
        CHUNK_SPINS_GROWTH,
        CIRCUIT_PAUSE_S,
        DEFAULT_ENDPOINT_URL,
        DEFAULT_GUIDELINE_RULES_PATH,
        ENDPOINT_URL,
        MIN_CHUNK_SPINS,
        SUCCESS_STREAK_FOR_GROW,
        _classify_failure,
        _RETRYABLE_HTTP_CODES,
        aimd_tune,
        make_payload,
        parse_args,
        post_json,
        post_json_with_retry,
        run_sampling_chunk,
        select_replay_chunks_by_md5,
    )

# PAYLINE_RE moved to fresh_slotlab.analyzer.core.parser (P2-B1a).
# RETURN_BUCKET_ORDER moved to fresh_slotlab.analyzer.core.aggregator (P2-B2);
# re-exported via the import block above. 11 win-bearing buckets;
# `return_bucket()` returns "" for zero-win sessions and the accumulators
# skip them. Tail dependency uses every bucket >= 10x.
# Tail dependency uses every bucket >= 10x. The previous schema lumped
# everything >=100 into one bucket; the refined schema splits it into
# 100-200 / 200-500 / 500-1000 / 1000-5000 / 5000+ so the tail is more
# than just a pile.
TAIL_GEX10_BUCKETS = {
    "ge10_lt20",
    "ge20_lt50",
    "ge50_lt100",
    "ge100_lt200",
    "ge200_lt500",
    "ge500_lt1000",
    "ge1000_lt5000",
    "ge5000",
}
# Multi-threshold tail slices for tail_dependency_ge{N}x breakdown.
# Each set is a strict superset filter on RETURN_BUCKET_ORDER; the
# analyzer computes win_share + rtp_contribution_pp for each threshold
# so the operator sees how the tail fattens as x increases.
TAIL_GEX20_BUCKETS = {
    "ge20_lt50",
    "ge50_lt100",
    "ge100_lt200",
    "ge200_lt500",
    "ge500_lt1000",
    "ge1000_lt5000",
    "ge5000",
}
TAIL_GEX50_BUCKETS = {
    "ge50_lt100",
    "ge100_lt200",
    "ge200_lt500",
    "ge500_lt1000",
    "ge1000_lt5000",
    "ge5000",
}
TAIL_GEX100_BUCKETS = {
    "ge100_lt200",
    "ge200_lt500",
    "ge500_lt1000",
    "ge1000_lt5000",
    "ge5000",
}
# DEFAULT_GUIDELINE_RULES_PATH moved to fresh_slotlab.analyzer.core.base_pipeline (P2-B4).
# Re-exported via the dual-path import block above.


# parse_args moved to fresh_slotlab.analyzer.core.base_pipeline (P2-B4).
# Re-exported via the dual-path import block above.

# utc_now() moved to fresh_slotlab.analyzer.core.writer (P2-B3).
# Re-exported via the dual-path import block above.

# to_float moved to fresh_slotlab.analyzer.core._utils (P2-B2)

# post_json moved to fresh_slotlab.analyzer.core.base_pipeline (P2-B4).
# Re-exported via the dual-path import block above.


# _RETRYABLE_HTTP_CODES moved to fresh_slotlab.analyzer.core.base_pipeline (P2-B4).
# Re-exported via the dual-path import block above.

# Fault-tolerance thresholds for the sampling loop's bailout check.
# Promoted from locals inside main() to module-level constants so:
#   (a) tests can lock them without invoking main()
#   (b) future per-run overrides (CLI flag) have a natural place to land
#
# 2026-04-17 (M273 incident): originally tuned for the EXTERNAL
# upstream `buffalo-debug.citrusjoy.com` which had per-IP throttling
# (see `feedback_upstream_throttle_ceiling.md`). 30s hiccup tolerance
# was needed there.
#
# 2026-04-26 (internal-network move, user directive): default endpoint
# moved to `192.168.10.21:15060` internal server (commit 527618d).
# Internal upstream has no per-IP rate limit — hiccups are sub-second
# TCP blips, not 30s rate-limit cooldowns. Plus user wanted the
# circuit-breaker to DISCRIMINATE between two failure classes:
#
#   - Network class (5xx, TimeoutError, ConnectionReset, etc.): retry
#     might help. Tolerate up to N failures across M batches before
#     bailing as `upstream_unstable`.
#
#   - Machine class (4xx, schema_drift, parse_failed_*, response_shape_
#     unexpected): retry won't help — the machine is emitting
#     garbage / wrong shape. Bail fast as `machine_bug` so operator
#     sees the signal early and can fix the machine code.
#
# See ``_classify_failure`` for the routing. Old monolithic
# ``MAX_CONSECUTIVE_FAILED_BATCHES`` and ``MAX_CUMULATIVE_FAILED_CHUNKS``
# constants are split into _NET / _MACHINE pairs below.
MAX_CONSECUTIVE_FAILED_BATCHES_NET = 3      # network-only fully-failed batches in a row → bail
MAX_CUMULATIVE_FAILED_CHUNKS_NET = 20       # network failures total → bail (~20s of bad-network)
MAX_CUMULATIVE_FAILED_CHUNKS_MACHINE = 5    # machine-class failures → fail-fast (5 ≈ batch size)

# Non-convergence early-abort (2026-04-21). When a machine's data is
# too pathological to converge on the caller's CI target (bug machines
# / in-development machines that emit nonsense), bail rather than
# burn the full max_chunks budget. Tier 1 (parse_failure / consecutive
# chunk_failed) is already handled by MAX_* constants above. These
# drive Tier 2: RTP out of sane band (paid-mode only, user decision
# 2026-04-21 — bonus mode legitimately hits high RTP) + projected
# budget overrun.
NON_CONVERGENCE_ABORT_MIN_CHUNKS = 20      # need ≥ N chunks before deciding
NON_CONVERGENCE_BUDGET_MULTIPLIER = 5.0    # predicted total > max_chunks × this → abort
NON_CONVERGENCE_RTP_BAND_PAID = (40.0, 200.0)  # paid mode (mode 1) sane range %
NON_CONVERGENCE_RTP_OUT_OF_BAND_CONSECUTIVE = 3  # chunks out-of-band in a row

# MIN_CHUNK_SPINS, SUCCESS_STREAK_FOR_GROW, CHUNK_SPINS_GROWTH, CIRCUIT_PAUSE_S
# moved to fresh_slotlab.analyzer.core.base_pipeline (P2-B4).
# Re-exported via the dual-path import block above.

# _classify_failure moved to fresh_slotlab.analyzer.core.base_pipeline (P2-B4).
# Re-exported via the dual-path import block above.


# Features that are NEVER the BCM cycle-bonus pair: paid-normal
# channels (the "regular spin" accumulator). Mirrored in
# scripts/infer_bcm_pairing.py — keep in sync. Add new paid-normal
# feature names here as machines with different naming conventions
# come online.
PAID_NORMAL_FEATURES = frozenset({
    "NormalCollectionSpin",
    "BingoCollectionNormalSpin",
    "ReelCollectionNormal",
    "HalloweenReelCollectionNormal",
})

# Path to per-machine BCM pairing config. Loaded lazily; absent file
# is treated as empty dict (no crash). Module-level constant so tests
# can monkeypatch it.
_BCM_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "configs" / "bcm_pairings.json"
)


def _load_bcm_pairings() -> dict[str, dict[int, str]]:
    """Load per-machine BCM bonus-feature pairings from
    ``configs/bcm_pairings.json``. Returns ``{machine_name: {mode_int:
    bonus_feature_name}}``.

    Supports two on-disk schemas:

    * **v2 (current)** — per-mode nested:
      ``{"machines": {"M273": {"modes": {"1": {"bonus_feature": ...}}}}}``.
      Some BCM machines pair with different features in different
      modes (e.g. M247: PreWheel in modes 1/2/5, LockReSpin in mode 7).
      Writing mode 1 data as "all modes" would silently under-correct
      RTP on variant modes.
    * **v1 (legacy)** — flat:
      ``{"_mode": 1, "machines": {"M273": {"bonus_feature": ...}}}``.
      Treated as mode-1-only (matches what the file was actually
      generated from). Remaining modes fall through to heuristic.

    Missing file or parse error → empty dict (resolver falls back to
    heuristic).
    """
    try:
        raw = json.loads(_BCM_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    machines = raw.get("machines") or {}
    out: dict[str, dict[int, str]] = {}
    # v1 fallback: the top-level ``_mode`` field tells us which single
    # mode the flat entries belong to. Default to 1 if absent (matches
    # the original inference tool's behavior).
    legacy_mode = int(raw.get("_mode", 1) or 1)
    for m, entry in machines.items():
        if not isinstance(entry, dict):
            continue
        modes = entry.get("modes")
        if isinstance(modes, dict):
            per_mode: dict[int, str] = {}
            for mode_key, mode_entry in modes.items():
                if not isinstance(mode_entry, dict):
                    continue
                feat = mode_entry.get("bonus_feature")
                try:
                    mode_int = int(mode_key)
                except (TypeError, ValueError):
                    continue
                if feat:
                    per_mode[mode_int] = feat
            if per_mode:
                out[m] = per_mode
            continue
        # v1 flat schema: {machine: {bonus_feature, confidence, ...}}
        feat = entry.get("bonus_feature")
        if feat:
            out[m] = {legacy_mode: feat}
    return out


def _infer_feature_spin_type_mapping(
    feature_times_total: dict[str, int],
    spin_type_spins: dict[int, int] | dict[str, int],
    spin_type_remarks_sample: dict[int, list[str]] | dict[str, list[str]],
    feature_win_total: dict[str, float] | None = None,
    spin_type_win: dict[int, float] | dict[str, float] | None = None,
) -> tuple[dict[str, int], dict[int, str], set[str]]:
    """Map upstream FeatureWin feature_name → round-level SpinType int.

    The upstream API groups feature payouts by a string ``feature_name``
    while round records carry an integer ``SpinType``. No explicit
    mapping is exposed, so we infer it from three signals (ordered
    strongest → weakest):

      1. **Unique fire-count match**: feature.times and spin_type.spins
         each uniquely match one another. Hard algebraic signal, no
         ambiguity. The clean happy path.
      2. **ReMarks substring** (tie-breaker): for features still
         unbound, match by feature_name appearing literally in the
         ReMarks of a candidate SpinType. Only binds if the
         SpinType's spin count is within ±50% of the feature's times
         (prevents M102-style misfires where paid-spin ReMarks mention
         a tiny bonus feature's name and we'd otherwise bind the big
         paid SpinType to the small feature).
      3. **Tied-count ordinal**: N features and N SpinTypes share the
         same count (e.g. M273's 3 ceremony features each fire 106×).
         Assign by sorted-ordinal and flag ambiguous so UI can warn.
      4. **±2% tolerance**: last-resort fuzzy for edge-round drift.

    Returns ``(feature_to_spin_type, spin_type_to_feature,
    ambiguous_mapped)``. Features with no plausible SpinType binding
    (e.g. session-level meta features with times = robot count) are
    left unmapped — chain-parent inference skips them.
    """
    st_spins = {int(k): int(v) for k, v in spin_type_spins.items()}
    st_remarks = {
        int(k): list(v) if isinstance(v, list) else []
        for k, v in (spin_type_remarks_sample or {}).items()
    }
    spin_type_to_feature: dict[int, str] = {}
    feature_to_spin_type: dict[str, int] = {}
    ambiguous_mapped: set[str] = set()

    # Group features + SpinTypes by count for the first + third passes.
    times_to_features: dict[int, list[str]] = defaultdict(list)
    for feat_name, feat_times in feature_times_total.items():
        if feat_times > 0:
            times_to_features[int(feat_times)].append(str(feat_name))
    times_to_spin_types: dict[int, list[int]] = defaultdict(list)
    for st, cnt in st_spins.items():
        times_to_spin_types[cnt].append(st)

    # Pass 1 — unique fire-count match. If exactly one feature and
    # exactly one SpinType share a count, they bind unambiguously.
    for feat_times, feats in times_to_features.items():
        sts = times_to_spin_types.get(feat_times) or []
        if len(feats) == 1 and len(sts) == 1:
            spin_type_to_feature[sts[0]] = feats[0]
            feature_to_spin_type[feats[0]] = sts[0]

    # Pass 2 — ReMarks substring, count-compatibility gated. Only
    # considers still-unbound (feature, SpinType) pairs.
    feats_lower = {str(f).lower(): str(f) for f in feature_times_total}
    for st, remarks_list in st_remarks.items():
        if st in spin_type_to_feature:
            continue
        st_count = st_spins.get(st, 0)
        for rm in remarks_list:
            rm_lower = rm.lower()
            matched = [
                feat for fl, feat in feats_lower.items() if fl in rm_lower
            ]
            fresh = [
                f for f in matched if f not in feature_to_spin_type
            ]
            if len(fresh) != 1:
                continue
            feat_name = fresh[0]
            feat_times = int(feature_times_total.get(feat_name, 0) or 0)
            # Reject count-incompatible ReMarks bindings (e.g. paid
            # SpinType with 10000 spins wouldn't host a feature that
            # fires 72 times even if its name appears in ReMarks).
            if feat_times <= 0 or st_count <= 0:
                continue
            drift = abs(st_count - feat_times) / max(feat_times, st_count, 1)
            if drift > 0.5:
                continue
            spin_type_to_feature[st] = feat_name
            feature_to_spin_type[feat_name] = st
            break

    # Pass 3 — tied-count ordinal assignment for residual groups.
    for feat_times, feats in times_to_features.items():
        fresh_feats = sorted(
            f for f in feats if f not in feature_to_spin_type
        )
        fresh_sts = sorted(
            st for st in (times_to_spin_types.get(feat_times) or [])
            if st not in spin_type_to_feature
        )
        if len(fresh_feats) == len(fresh_sts) and fresh_feats:
            for feat_name, st in zip(fresh_feats, fresh_sts):
                spin_type_to_feature[st] = feat_name
                feature_to_spin_type[feat_name] = st
                if len(fresh_feats) > 1:
                    ambiguous_mapped.add(feat_name)

    # Pass 4 — ±2% tolerance for single-candidate approximate matches.
    for feat_name, feat_times in feature_times_total.items():
        if feat_times <= 0 or feat_name in feature_to_spin_type:
            continue
        candidates = [
            (st, cnt) for st, cnt in st_spins.items()
            if abs(cnt - feat_times) / max(feat_times, 1) <= 0.02
            and st not in spin_type_to_feature
        ]
        if len(candidates) == 1:
            st = candidates[0][0]
            spin_type_to_feature[st] = feat_name
            feature_to_spin_type[feat_name] = st

    # Sanity gate — if a feature has direct_win_credits > 0 but its
    # mapped SpinType has total_win == 0, the count match pointed at
    # a "selector / resolution" SpinType that doesn't carry the wins
    # (M102 Wheel: pay_id attribution lands on a different SpinType
    # than where fires were counted). Drop the mapping; pass 5 below
    # will re-bind if the zero-win ST is a legitimate settlement
    # SpinType (unique match only).
    if feature_win_total and spin_type_win:
        st_win = {int(k): float(v) for k, v in spin_type_win.items()}
        dropped: list[str] = []
        for feat_name, st in list(feature_to_spin_type.items()):
            feat_win = float(feature_win_total.get(feat_name, 0) or 0)
            mapped_st_win = st_win.get(st, 0.0)
            if feat_win > 0 and mapped_st_win <= 0:
                dropped.append(feat_name)
        for feat_name in dropped:
            st = feature_to_spin_type.pop(feat_name)
            spin_type_to_feature.pop(st, None)
            ambiguous_mapped.discard(feat_name)

    # Pass 5 — settlement-SpinType binding (iter 5 M15 fix, 2026-04-23).
    # Some selector-style features (M15 TopDollar, M12 TopDollar,
    # QuickDollar family) have a "settlement SpinType" that fires
    # once per trigger session with WinCredits=None on every round.
    # The aggregator sees zero win on that SpinType, so pass 1's
    # count match binds feature → settlement ST, then the sanity
    # gate immediately drops it (feat_win > 0 but mapped_st_win = 0).
    # Without re-binding, the feature's resolved_spin_type stays
    # None → UI shows "无倍率分桶数据" on its card AND the chain
    # inference can't resolve the selector feature's successor
    # (which should point at this settlement feature).
    #
    # Runs AFTER the sanity gate so it picks up features the gate
    # just dropped. Rule: for each unbound paying feature, find the
    # unique unbound zero-win SpinType with count within 15% of
    # feat.times. The zero-win filter is the whole point — we
    # ONLY re-bind to zero-win STs, so this never clashes with the
    # sanity gate's intended behaviour (dropping misfires onto
    # zero-win STs when a nonzero-win ST is the real match).
    if feature_win_total and spin_type_win:
        st_win_p5 = {int(k): float(v) for k, v in spin_type_win.items()}
        for feat_name, feat_times in feature_times_total.items():
            if feat_times <= 0 or feat_name in feature_to_spin_type:
                continue
            feat_win = float(feature_win_total.get(feat_name, 0) or 0)
            if feat_win <= 0:
                # Zero-win feature → let pass 1/3 handle via counts;
                # pass 5 targets paying features only.
                continue
            zero_win_candidates = [
                (st, cnt) for st, cnt in st_spins.items()
                if st not in spin_type_to_feature
                and st_win_p5.get(st, 0.0) == 0.0
                and abs(cnt - feat_times) / max(feat_times, 1) <= 0.15
            ]
            if len(zero_win_candidates) == 1:
                st = zero_win_candidates[0][0]
                spin_type_to_feature[st] = feat_name
                feature_to_spin_type[feat_name] = st
    return feature_to_spin_type, spin_type_to_feature, ambiguous_mapped


def _resolve_bonus_feature(
    machine: str,
    mode: int,
    upstream_feature_tally: dict | None,
    config: dict[str, dict[int, str]],
    feature_to_spin_type: dict[str, int] | None = None,
    wild_nudge_spin_types: set[int] | None = None,
) -> tuple[str | None, str]:
    """Decide which FeatureWin key pairs with BuffCollectionMap for a
    given (machine, mode).

    Three-layer strategy (config → heuristic → none):
      1. If ``config[machine][mode]`` exists → return that feature,
         source="config". Respect operator override even when the
         feature's current win is zero (small cache, rare feature;
         operator knows best). The config is regenerated by
         ``scripts/infer_bcm_pairing.py`` which uses observed-at-
         cycle-peak SpinType as Signal C (highest priority).
      2. Otherwise pick the feature in the tally with highest total win
         that is neither in PAID_NORMAL_FEATURES nor BuffCollectionMap
         itself, AND whose resolved SpinType is NOT in
         ``wild_nudge_spin_types``. Source="heuristic". Excluding
         wild-nudge SpinTypes prevents the M279 misfire where MoveSpin
         (wild-nudge total 170M) was picked over Wheel (real BCM
         target, total 11M). When config is up-to-date the heuristic
         rarely fires, but it's the safety net for new machines.
      3. If no such feature exists (all-zero wins, empty tally, only
         paid-normal / BCM / wild-nudge in tally) → (None, "none").
         Caller should skip RTP correction + surface a warning.

    Returns ``(feature_name_or_None, source_string)``.
    """
    cfg = config or {}
    per_mode = cfg.get(machine)
    if isinstance(per_mode, dict) and mode in per_mode:
        return per_mode[mode], "config"
    tally = upstream_feature_tally or {}
    nudge_sts = wild_nudge_spin_types or set()
    f2st = feature_to_spin_type or {}
    best_feat = None
    best_win = -1.0
    for feat, payouts in tally.items():
        if feat in PAID_NORMAL_FEATURES or feat == "BuffCollectionMap":
            continue
        if not isinstance(payouts, dict):
            continue
        # Skip wild-nudge features (Bug 3 fix; defensive — Signal C
        # in bcm_pairings.json regen handles the primary path).
        feat_st = f2st.get(feat)
        if feat_st is not None and feat_st in nudge_sts:
            continue
        total_win = 0.0
        for entry in payouts.values():
            if isinstance(entry, dict):
                total_win += float(entry.get("win", 0) or 0)
        if total_win > best_win:
            best_win = total_win
            best_feat = feat
    if best_feat is None or best_win <= 0:
        return None, "none"
    return best_feat, "heuristic"


# collect_feature_match_warning + build_cycle_observation moved to
# fresh_slotlab.analyzer.features.collect_mechanic (Phase 2a carve). They are
# PRIVATE to the collect_mechanic feature (only that plugin's compute calls
# them on the report-production path), so they now live with the feature whose
# hash they belong to. External callers (tests/backend/test_bcm_resolver.py,
# scripts/scan_collect_feature_match.py) import them from the plugin module.


# aimd_tune moved to fresh_slotlab.analyzer.core.base_pipeline (P2-B4).
# Re-exported via the dual-path import block above.

# post_json_with_retry moved to fresh_slotlab.analyzer.core.base_pipeline (P2-B4).
# Re-exported via the dual-path import block above.


# t_critical_95 — imported from fresh_slotlab.sampler (canonical source).
# P1-B4: dropped local duplicate (sparse table, linear-interp missing df 11-19,
# 21-29, 31+). See ticket phase1/01_t_critical_table_dedup §1 +
# session_artifacts/_arch/03_coupling_audit.md §4.5.


def ci_halfwidth_pp(chunk_rtps_pct: list[float]) -> float:
    if len(chunk_rtps_pct) < 2:
        return math.inf
    if len(set(chunk_rtps_pct)) == 1:
        return 0.0
    return (
        t_critical_95(len(chunk_rtps_pct) - 1)
        * statistics.stdev(chunk_rtps_pct)
        / math.sqrt(len(chunk_rtps_pct))
    )


# session_halfwidth_pp — imported from fresh_slotlab.sampler (canonical source).
# P1-B3: dropped local duplicate; both this module and virtual_analyzer.py
# now delegate to the single definition in sampler.py.
# Ticket: phase1/09_session_ci_halfwidth_dedup §1 citing
# session_artifacts/_arch/03_coupling_audit.md §4.5.
# Note: caller signature uses (ret_count, ret_sum, ret_sq_sum) — the canonical
# sampler signature uses (n, ret_sum, ret_sq_sum); positionally identical.


# parse_rounds moved to fresh_slotlab.analyzer.core.parser (P2-B1a).


# Rawdata-replay bankruptcy simulation. Each robot's round sequence is
# an independent IID sample (the upstream uses ContinueAfterBankrupt +
# reset_each_spin so RNG is stateless w.r.t. wallet) — so we pool
# rounds across all robots in a chunk and chop the resulting stream
# into non-overlapping `session_spins`-length windows. Each window is
# one simulated "paid-round session": we start with a fresh bankroll
# (multiplier × bet), debit paid rounds (CostCredits > 0), credit wins
# on every round, and mark survival when the window is consumed or
# bankruptcy when the balance can't afford the next paid round. Bonus
# rounds (CostCredits = 0) don't drain balance but still contribute
# wins, matching real-play pickup behavior.
#
# Precision: each chunk records the EXACT spins-done at bankruptcy for
# every bankrupt window (not a histogram). At finalize, per-tier
# percentiles / median / fastest are computed from the sorted combined
# list with spin-level precision — a tier with 3,840 simulated
# sessions fits in <40 KB and percentile look-ups are O(1) after the
# sort. Survivors (spins_done == session_spins) are tallied separately
# and only materialized into the sorted view when a percentile past
# the bankrupt share is requested.
#
# Pooling across robots is what lets session_spins = 10,000 (the
# default) work even when each robot carries only ~chunk_spin_times
# rounds (typically 5,000). IID guarantee means a 10k window
# synthesized from two robots is statistically equivalent to one
# robot playing 10k spins. The only hard case is
# `total_rounds_in_chunk < session_spins` — that chunk contributes
# zero sessions; the operator sees fewer total samples but nothing
# crashes.
# _DEFAULT_BANKROLL_MULTIPLIERS moved to fresh_slotlab.analyzer.core._utils (P2-B2)
# _DEFAULT_BANKRUPTCY_SESSION_SPINS moved to fresh_slotlab.analyzer.core._utils (P2-B2)
# _empty_bankruptcy_tier moved to fresh_slotlab.analyzer.core._utils (P2-B2)


# _extract_bankruptcy_reps moved to fresh_slotlab.analyzer.core._utils (P2-B2)
# simulate_bankruptcy_from_response moved to fresh_slotlab.analyzer.core._utils (P2-B2)


# select_replay_chunks_by_md5 moved to fresh_slotlab.analyzer.core.base_pipeline (P2-B4).
# Re-exported via the dual-path import block above.


# _BankruptcyStreamAccumulator moved to fresh_slotlab.analyzer.core.aggregator (P2-B2)

# _BankruptcyStreamAccumulator moved to fresh_slotlab.analyzer.core.aggregator (P2-B2)
# compute_bankruptcy_percentiles moved to fresh_slotlab.analyzer.core.aggregator (P2-B2)
# fastest_bankruptcy_spins_from_list moved to fresh_slotlab.analyzer.core.aggregator (P2-B2)
# median_spins_from_list moved to fresh_slotlab.analyzer.core.aggregator (P2-B2)
# quantile_from_hist moved to fresh_slotlab.analyzer.core.aggregator (P2-B2)
# _BANKRUPTCY_PERCENTILES: PIA body uses this at lines 5044, 5451, 5454.
# The constant is not in the 16 P2-B2 symbols; keep a PIA-local copy.
# aggregator.py also defines it for its own use (compute_bankruptcy_percentiles
# uses it as a default parameter).
_BANKRUPTCY_PERCENTILES: tuple[int, ...] = (10, 20, 30, 40, 50, 60, 70, 80, 90)

# _BASELINE_ROUND_FIELDS, _REQUIRED_ROUND_FIELDS, _REQUIRED_BET_FIELDS_ANY,
# _check_round_schema, parse_paylines, split_symbols moved to
# fresh_slotlab.analyzer.core.parser (P2-B1a).


def safe_div(numerator: float, denominator: float) -> float:
    return (numerator / denominator) if denominator > 0 else 0.0


def append_jsonl(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


# _metric_path_get moved to fresh_slotlab.analyzer.core.aggregator (P2-B2)


# _eval_operator moved to fresh_slotlab.analyzer.core.aggregator (P2-B2)
# _deviation moved to fresh_slotlab.analyzer.core.aggregator (P2-B2)


# evaluate_guideline_comparison moved to fresh_slotlab.analyzer.core.aggregator (P2-B2)
# classify_volatility moved to fresh_slotlab.analyzer.core.aggregator (P2-B2)
# classify_experience_archetype moved to fresh_slotlab.analyzer.core.aggregator (P2-B2)
# blank_like_symbol moved to fresh_slotlab.analyzer.core._utils (P2-B2)


# ReMarks annotation parsers. M272 bonus rounds carry strings like:
#   "Freespin 18; CollectCount:64; AddCollectCount:6; ExtraRatio:200; "
#   "Freespin 19; CollectCount:68; AddCollectCount:4; ExtraRatio:200; AddFreespins; 1"
# which tell us (a) that this round is inside a bonus chain, (b) what
# multiplier the chain is currently at, and (c) whether it self-
# retriggered. All three drive the bonus_chain_dynamics surface.
# Machines without this field (M14) silently skip -- parse returns None.
# _REMARKS_*_RE constants and parse_freespin_remarks moved to
# fresh_slotlab.analyzer.core.parser (P2-B1a).


# bonus_chain_depth_bucket moved to fresh_slotlab.analyzer.core._utils (P2-B2)

# _compute_bonus_correction, _compute_nf_correction, parse_rln_codes
# moved to fresh_slotlab.analyzer.core.parser (P2-B1a).


# make_payload moved to fresh_slotlab.analyzer.core.base_pipeline (P2-B4).
# Re-exported via the dual-path import block above.


# return_bucket moved to fresh_slotlab.analyzer.core._utils (P2-B2)
# build_multiplier_bucket_rows moved to fresh_slotlab.analyzer.core.aggregator (P2-B2)


# CHUNK_CACHE_VERSION moved to fresh_slotlab.analyzer.core.writer (P2-B3).
# Re-exported via the dual-path import block above.

# ChunkIntegrityError, _canonical_payload_bytes, _payload_sha256,
# load_chunk_envelope moved to fresh_slotlab.analyzer.core.parser (P2-B1a).


# Envelope header peek — extracts ``_chunk_index`` + ``_config_md5`` +
# ``_code_md5`` from the first ~4KB of a chunk file WITHOUT parsing the
# potentially-megabytes-sized ``response`` array that follows. The fields
# land at the top of the envelope (see the dict in ``_persist_chunk``
# which writes ``_chunk_index`` / ``_config_md5`` / ``_code_md5`` well
# before ``response``), so regex over the first 4KB is safe in practice.
#
# Fallback: when the regex doesn't match (very old envelopes without
# these keys, reordered writes, etc.), caller drops back to full
# ``load_chunk_envelope`` which preserves the pre-optimization path.
#
# Wins: on a 100MB historical-md5 replay (29 × ~3.5MB chunks for M15
# mode 5), peek cuts read+parse from ~15s to <200ms total. That's the
# observable "replay stalls even though nothing matches my new md5"
# pain when an operator swaps ``machineconfig/<u>Cfg.txt``.
# _ENVELOPE_PEEK_BYTES, _ENVELOPE_PEEK_RE, peek_chunk_envelope,
# _compute_upstream_schema_fingerprint moved to
# fresh_slotlab.analyzer.core.parser (P2-B1a).


def compute_analyzer_version() -> str:
    """Return a 12-char hex digest of this analyzer module's source.

    Stamped in summary.json so run-history can flag reports as stale
    when the analyzer code has changed after a report was built.
    Intentionally broad: any edit to ``player_impact_analyzer.py`` —
    including comments — changes the hash. That's fine because the
    recovery action is a single click (⟳ generate report from
    rawdata), and a false-stale is cheap to resolve while a false-
    fresh would hide a real bug.

    Returns "" if the source file can't be read (shouldn't happen in
    normal execution — this module is always loaded from a file). An
    empty string signals "untagged" downstream rather than crashing.
    """
    try:
        data = Path(__file__).resolve().read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(data).hexdigest()[:12]


# _lookup_machine_md5 is imported from fresh_slotlab.machine_md5 at module top
# (P1-B1: phase1/07_lookup_machine_md5_dedup §1 citing 04_v5 §6.1).
# The name is kept as a module-level attribute so callers (including
# _save_chunk_cache below) can be monkeypatched in tests via
# `monkeypatch.setattr(pia, "_lookup_machine_md5", ...)`.


# _save_chunk_cache moved to fresh_slotlab.analyzer.core.writer (P2-B3).
# Re-exported via the dual-path import block above.

# run_sampling_chunk moved to fresh_slotlab.analyzer.core.base_pipeline (P2-B4).
# Re-exported via the dual-path import block above.


# parse_chunk_response moved to fresh_slotlab.analyzer.core.parser (P2-B1b)


def main() -> int:
    args = parse_args()

    if args.endpoint_url:
        # Option B (P2-B4 §3 C3): ENDPOINT_URL is now canonical in
        # base_pipeline.py; post_json reads it from that module's namespace.
        # Mutate the base_pipeline module attribute so post_json picks up
        # the new value. PIA's re-exported ENDPOINT_URL binding is a
        # snapshot from import time; only _core_base_pipeline.ENDPOINT_URL
        # is the live source of truth.
        _core_base_pipeline.ENDPOINT_URL = args.endpoint_url

    # Graceful stop flag: SIGTERM / SIGINT sets this so the main chunk
    # loop breaks between chunks and falls through to the normal
    # summary-build path with whatever data we have. The backend sends
    # SIGTERM when the operator clicks Stop; we want partial data to
    # be usable (a cancelled run shouldn't throw away 10 completed
    # chunks just because chunk 11 was mid-flight).
    stop_requested = {"value": False}

    def _graceful_stop_handler(signum, _frame):
        stop_requested["value"] = True

    try:
        signal.signal(signal.SIGTERM, _graceful_stop_handler)
    except (ValueError, OSError):
        # Non-main-thread invocation or platform that doesn't allow it.
        # On Windows the signal module's SIGTERM handling is limited;
        # the signal is still delivered but catchable only on the main
        # thread, which is where main() runs.
        pass
    try:
        signal.signal(signal.SIGINT, _graceful_stop_handler)
    except (ValueError, OSError):
        pass

    if args.bet <= 0:
        raise SystemExit("--bet must be positive")
    if args.target_halfwidth_pp <= 0:
        raise SystemExit("--target-halfwidth-pp must be positive")
    if args.chunk_spin_times <= 0 or args.chunk_robot_count <= 0:
        raise SystemExit("--chunk-spin-times and --chunk-robot-count must be positive")
    if args.batch_concurrency <= 0 or args.max_chunks <= 0 or args.timeout <= 0:
        raise SystemExit("--batch-concurrency, --max-chunks, --timeout must be positive")
    if args.bankruptcy_session_spins <= 0:
        raise SystemExit("--bankruptcy-session-spins must be positive")

    # Bankroll multiplier tiers for the rawdata-replay bankruptcy
    # simulation. Parsed once here and threaded through to every
    # chunk-parse call site so the sim computes the correct tier set
    # (and every chunk agrees on the same tier list, making the
    # per-tier histogram merge well-defined).
    _bankruptcy_mults_tuple: tuple[int, ...] = tuple(
        int(x.strip())
        for x in args.bankruptcy_bankroll_multipliers.split(",")
        if x.strip()
    ) or _DEFAULT_BANKROLL_MULTIPLIERS

    # Per-machine round-win extraction rules (2026-04-27).
    # Default: empty rule list -> chunk parsing falls back to legacy
    # ``r.get("WinCredits", 0)`` lookup, byte-identical to pre-2026-04-27.
    # When the machine appears in configs/machine_round_win_rules.json,
    # the extracted rules are threaded through every WinCredits site
    # in parse_chunk_response + the trigger-session helper + the
    # bankruptcy simulator so phantom-offer rounds (M12 ST=14) and
    # WinAmount-only settlement rounds (M12 ST=15) are accounted
    # correctly. Config absence / parse failure / unknown rule type
    # all fall through to default (no rules); the operator sees
    # legacy behaviour unchanged.
    _round_win_rules: list[RoundWinRule] = []
    try:
        _rules_config_path = Path(__file__).resolve().parent.parent / "configs" / "machine_round_win_rules.json"
        if _rules_config_path.exists():
            with open(_rules_config_path, encoding="utf-8") as _rcf:
                _rules_config = json.load(_rcf)
            _round_win_rules = load_rules_for_machine(args.machine, _rules_config)
    except (OSError, json.JSONDecodeError):
        _round_win_rules = []

    args.output_dir.mkdir(parents=True, exist_ok=True)

    run_id = args.run_id or f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    progress_file = args.progress_file

    started_at = utc_now()
    t0 = time.time()
    append_jsonl(
        progress_file,
        {
            "event": "started",
            "run_id": run_id,
            "machine": args.machine,
            "mode": args.rtp_mode,
            "target_halfwidth_pp": args.target_halfwidth_pp,
            "chunk_spin_times": args.chunk_spin_times,
            "chunk_robot_count": args.chunk_robot_count,
            "batch_concurrency": args.batch_concurrency,
            "started_at": started_at,
        },
    )
    # UI-facing lifecycle event. The `started` event above is consumed
    # by PURE.summarizeRunEvent (single-run live status strip) and was
    # never meant to surface in the batch-log timeline. Emit a separate
    # `analyzer_started` so the batch-log renderer can show "⚙ analyzer
    # 就绪 · pid=X" right as the subprocess finishes its bootstrap —
    # closes the observability gap between the backend's "spawn" log
    # and the first chunk_progress event (which otherwise is 30-60s of
    # apparent silence while the analyzer fetches its first chunk).
    append_jsonl(
        progress_file,
        {
            "event": "analyzer_started",
            "run_id": run_id,
            "pid": os.getpid(),
            "machine": args.machine,
            "mode": args.rtp_mode,
            "ts": utc_now(),
        },
    )

    # Operator-visible signal that this run is using per-machine round-win
    # overrides (vs the default legacy WinCredits lookup). Only emitted
    # when at least one rule is active so vanilla machines keep the
    # JSONL stream short.
    if _round_win_rules:
        append_jsonl(
            progress_file,
            {
                "event": "round_win_rules_active",
                "run_id": run_id,
                "machine": args.machine,
                "rule_count": len(_round_win_rules),
                "rule_types": [type(r).__name__ for r in _round_win_rules],
                "ts": utc_now(),
            },
        )

    total_spins = 0
    total_bet = 0.0
    total_win = 0.0
    chunk_rtps_pct: list[float] = []

    ret_count = 0
    ret_sum = 0.0
    ret_sq_sum = 0.0
    max_observed_return_x = 0.0

    win_spins = 0
    loss_spins = 0
    profit_spins = 0
    breakeven_or_more_spins = 0
    big_win_x10_spins = 0
    win_sum = 0.0

    # Session-level totals (per-chunk records accumulate into these).
    total_paid_sessions = 0
    total_bonus_spins = 0
    total_session_wins = 0
    total_session_loses = 0
    total_session_profits = 0
    total_session_breakevens = 0
    total_session_big_win_x10 = 0
    total_session_big_win_x20 = 0
    total_session_big_win_x50 = 0
    total_session_big_win_x100 = 0
    # Rawdata-replay bankruptcy histogram totals. Initialized lazily on
    # first chunk that carries data; keyed by int bankroll multiplier.
    # Two paths: (a) cross-chunk streaming accumulator (preferred —
    # consumes raw reps from each chunk record); (b) per-chunk merge
    # (fallback for cached chunks pre-dating the 2026-04-25 fix).
    # Finalize prefers the streaming result when ``has_data``.
    bankruptcy_sim_totals: dict[int, dict[str, Any]] = {}
    bankruptcy_stream_acc = _BankruptcyStreamAccumulator(
        bet=args.bet,
        session_spins=args.bankruptcy_session_spins,
        bankroll_mults=_bankruptcy_mults_tuple,
    )
    total_session_ret_count = 0
    total_session_ret_sum = 0.0
    total_session_ret_sq_sum = 0.0
    total_session_max_return_x = 0.0
    total_session_win_sum = 0.0
    session_bucket_spins: dict[str, int] = defaultdict(int)
    session_bucket_bet: dict[str, float] = defaultdict(float)
    session_bucket_win: dict[str, float] = defaultdict(float)
    session_loss_streak_hist: dict[int, int] = defaultdict(int)
    session_win_streak_hist: dict[int, int] = defaultdict(int)
    total_session_max_loss_streak = 0
    total_session_max_win_streak = 0

    payline_hits: dict[str, int] = defaultdict(int)
    payline_win_approx: dict[str, float] = defaultdict(float)
    payline_winning_symbols: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    payline_winning_symbols_rln: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    # Bonus-chain dynamics aggregators (M272 MapCollection / future
    # machines). All stay empty when no ReMarks freespin lines were
    # seen across the sample; applicable=false in that case.
    bonus_chain_lengths: list[int] = []
    bonus_chain_max_ratios: list[int] = []
    bonus_chain_retrigger_events: list[int] = []
    bonus_total_rounds_global = 0
    bonus_retrigger_rounds_global = 0
    bonus_extra_ratio_counts: dict[int, int] = defaultdict(int)
    bonus_depth_ratio_sum: dict[str, float] = defaultdict(float)
    bonus_depth_ratio_count: dict[str, int] = defaultdict(int)

    symbol_counts: dict[str, int] = defaultdict(int)
    symbol_counts_by_col: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    symbol_counts_by_col_by_row: dict[int, dict[int, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    # 2026-05-14: per-ST symbol counts per column for ST-split reel marginal.
    symbol_counts_by_col_by_spin_type_total: dict[int, dict[int, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    payline_rows_per_col: dict[int, set[int]] = defaultdict(set)
    total_symbol_slots = 0

    loss_streak_hist: dict[int, int] = defaultdict(int)
    win_streak_hist: dict[int, int] = defaultdict(int)
    max_loss_streak = 0
    max_win_streak = 0

    multiplier_bucket_spins: dict[str, int] = defaultdict(int)
    multiplier_bucket_bet: dict[str, float] = defaultdict(float)
    multiplier_bucket_win: dict[str, float] = defaultdict(float)

    payout_group_hits: dict[int, int] = defaultdict(int)
    payout_group_win: dict[int, float] = defaultdict(float)
    payout_id_hits: dict[str, int] = defaultdict(int)
    payout_id_win: dict[str, float] = defaultdict(float)
    payout_id_by_spin_type_total: dict[str, dict[int, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    # Note: payout_id_win_by_spin_type_total removed in Phase C2.
    # It was only consumed by Block F3 (payouts_by_spin_type), which is
    # now owned by the PayoutsBySpinType plugin's extract/reduce/emit.
    # payout_id_by_spin_type_total is kept: F2 (payout_ids_top20) still
    # uses it for dominant-SpinType attribution at finalization.
    spin_type_spins: dict[int, int] = defaultdict(int)
    spin_type_next_counts: dict[int, Counter] = defaultdict(Counter)
    spin_type_remarks_sample: dict[int, list[str]] = defaultdict(list)
    spin_type_nudge_round_count: dict[int, int] = defaultdict(int)
    spin_type_bucket_spins: dict[int, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    spin_type_bucket_bet: dict[int, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    spin_type_bucket_win: dict[int, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    # Iter 6 finalize-level accumulators — merged across chunks from
    # each chunk's session_bucket_*_by_settlement_st payload. Feature
    # rows bound via Pass 5 (paying feature → zero-win settlement ST)
    # read from here instead of spin_type_bucket_* to populate their
    # bucket_distribution cards with per-session win histograms.
    session_bucket_spins_by_settlement_st: dict[int, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    session_bucket_bet_by_settlement_st: dict[int, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    session_bucket_win_by_settlement_st: dict[int, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    # Per-chain-path bucket histograms (session-level reduce target).
    chain_bucket_spins: dict[tuple, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    chain_bucket_bet: dict[tuple, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    chain_bucket_win: dict[tuple, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    # Session-level bonus-chain summary merged from per-chunk records.
    # Key = (first_st, entry_cc_reset, sp_type) → rolled-up counts.
    chain_chunk_summaries: dict[tuple, dict[str, float]] = defaultdict(
        lambda: {"count": 0, "win": 0.0, "bet": 0.0}
    )
    spin_type_bet: dict[int, float] = defaultdict(float)
    spin_type_paid_bet: dict[int, float] = defaultdict(float)
    spin_type_win: dict[int, float] = defaultdict(float)
    spin_type_wins: dict[int, int] = defaultdict(int)
    spin_type_paid_rounds: dict[int, int] = defaultdict(int)
    # Upstream FeatureWin aggregation across chunks. feature_name (str)
    # -> payout_id (str) -> {"win": float, "times": int}.
    upstream_feature_tally: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"win": 0.0, "times": 0})
    )
    upstream_total_win = 0.0
    upstream_robots_seen = 0
    collect_count_total = 0
    acc_credits_max_global = 0
    collect_robots_seen_total = 0
    clamp_pending_paid_spins_total = 0
    clamp_pending_robots_total = 0
    # BuffCollectionMap cycle aggregation for NewFreespin correction.
    all_cycle_peaks: list[int] = []
    all_final_cc_values: list[int] = []
    total_completed_cycles = 0
    # Raw-data analysis aggregation across chunks.
    all_payline_symbol_joint: dict[str, dict[str, float]] = defaultdict(
        lambda: {"hits": 0, "win": 0.0}
    )
    all_session_rtp_curves: list[list[dict[str, float]]] = []
    all_chain_ratio_sequences: list[list[int]] = []
    all_reel_position_hits: dict[str, int] = defaultdict(int)
    # Per-feature chain aggregation.
    all_chains_by_feature: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "lengths": [], "max_ratios": [], "retrigger_events": [],
            "total_rounds": 0, "retrigger_rounds": 0,
        }
    )

    lack_credit_spins = 0
    # Extra-field discovery aggregation across chunks.
    total_extra_fields_seen: dict[str, int] = defaultdict(int)
    # Per-machine mechanic totals.
    total_lock_lines_spins = 0
    total_lock_lines_total_lines = 0
    total_lock_lines_win = 0.0
    total_lock_symbols_spins = 0
    total_lock_symbols_unique: set[str] = set()
    total_lock_symbols_win = 0.0
    total_lock_reels_spins = 0
    total_lock_reels_win = 0.0
    total_jackpot_spins = 0
    total_jackpot_ids_seen: set[str] = set()
    total_jackpot_win = 0.0
    total_freespin_chain_spins = 0
    total_freespin_retriggers = 0
    total_freespin_max_chain = 0
    total_freespin_win = 0.0
    total_dollar_pick_spins = 0
    total_dollar_pick_total_dollars = 0
    total_dollar_pick_win = 0.0
    chunks = 0
    stop_reason = "max_chunks_reached"
    achieved_halfwidth_pp: float | None = None
    next_chunk_index = 1
    # Fault-tolerance counters. A single chunk failure no longer kills
    # the run (merge successful siblings, log the failure, continue).
    # Thresholds live at module scope (MAX_CONSECUTIVE_FAILED_BATCHES /
    # MAX_CUMULATIVE_FAILED_CHUNKS) so tests can lock them and a
    # future per-run override has a natural seam.
    cumulative_failed_chunks = 0           # legacy total; kept for event payload back-compat
    cumulative_failed_chunks_net = 0       # network-class (5xx, timeout, conn-reset, etc.)
    cumulative_failed_chunks_machine = 0   # machine-class (schema_drift, parse_failed, 4xx)
    consecutive_failed_batches_net = 0     # only counts batches whose failures are mostly network
    # Non-convergence Tier-2 RTP band tracker — consecutive chunks
    # where paid-mode RTP sits outside the sane band. Initialized
    # outside the main loop so it persists across batches.
    rtp_out_of_band_consecutive = 0

    # Phase C1: per-feature accumulator dict — keyed by FEATURE_ID.
    # extract() and reduce() calls in the merge loop fold per-chunk data here.
    # Initialized to empty dict per feature; the final value is passed to
    # emit() as ``final_acc`` in the Phase D emit loop.
    # Feature list is not yet known here (plugins register via import in the
    # Wave 2c block below); we use a defaultdict so any FEATURE_ID is safe.
    _feature_accs: dict[str, dict] = {}

    # EC-4 consumer (critique_commitC1 finding #2): collect
    # _plugin_partial_attribution_errors from every chunk across the whole run.
    # Per memory/feedback_no_silent_swallow.md: the key is written per chunk by
    # parse_chunk_response when an accumulator faults; we surface the aggregate
    # into summary["play_type_plugin_warnings"] + a stderr log so operators see
    # the signal rather than having it sit silently in the chunk dict.
    _play_type_plugin_errors_total: list = []

    # ── Cache read phase ─────────────────────────────────────────────
    # Two modes share the reader, differ only in what happens after:
    # - `--from-cache <dir>`: read-only. Run the pipeline offline on
    #   the cached chunks; skip the live sampling loop entirely.
    # - `--resume-from-cache <dir>`: read cached chunks as a starting
    #   state, then CONTINUE live sampling into the same dir from the
    #   next chunk index until the CI target or max_chunks hits.
    # Mutually exclusive.
    if args.from_cache is not None and args.resume_from_cache is not None:
        raise SystemExit(
            "--from-cache and --resume-from-cache are mutually exclusive"
        )
    cache_read_dir = args.from_cache if args.from_cache is not None else args.resume_from_cache
    resume_mode = args.resume_from_cache is not None
    # Set to True after the reader finishes so the `while` live-loop
    # knows to skip (read-only mode).
    skip_sampling_loop = args.from_cache is not None

    if cache_read_dir is not None:
        # Pre-load the per-mode chunk metadata sidecar once so the
        # replay loop can check md5 match WITHOUT opening any chunk
        # file. Auto-rebuilds on first use via 4KB peek per chunk —
        # O(N peek) instead of O(N full-load). See
        # ``fresh_slotlab.chunk_index`` for the design.
        try:
            _chunks_idx_payload = get_chunks_index(cache_read_dir)
            _sidecar_entries = _chunks_idx_payload.get("chunks") or {}
        except Exception:  # noqa: BLE001
            _sidecar_entries = {}

        # 2026-04-26: when an md5 filter IS active and the sidecar IS
        # populated, pre-filter chunk_files to ONLY the matching md5.
        # The previous loop iterated every chunk on disk (e.g. 1429
        # for M1sim mode 1 with three accumulated md5 versions) and
        # quickly skipped mismatches via the sidecar fast-path — but
        # "quickly" was still ~10ms/chunk for the dispatch + JSONL
        # progress event amortisation, so iterating 1060 mismatched
        # chunks burned ~15 seconds of "0 spins" wall time per
        # generate-report. Pre-filtering drops that to a single dict
        # walk + sort. The fall-back glob path is preserved for old
        # cache that pre-dates the sidecar (no `_sidecar_entries`)
        # and for the no-md5-filter case.
        md5_filter_active_pre = bool(args.upstream_config_md5 or args.upstream_code_md5)
        if md5_filter_active_pre and _sidecar_entries:
            chunk_files, max_existing_idx = select_replay_chunks_by_md5(
                cache_read_dir,
                _chunks_idx_payload,
                args.upstream_config_md5,
                args.upstream_code_md5,
            )
        else:
            chunk_files = sorted(cache_read_dir.glob("chunk_*.json"))
            max_existing_idx = 0

        # Read-only mode demands a non-empty cache; resume mode is
        # happy to start fresh (cache dir just happens to be empty
        # on the first resume call). With md5 pre-filter active,
        # "empty" can also mean "no chunks match the current md5",
        # which is a legitimate fresh-pull state — fall through to
        # the "no chunks" report-only path instead of crashing.
        if not chunk_files and not resume_mode and not md5_filter_active_pre:
            raise SystemExit(f"--from-cache: no chunk_*.json files found in {cache_read_dir}")
        # Respect --max-chunks for --from-cache just like for online
        # sampling. Without this, a dev-time batch pass over cached
        # machines with 50+ chunks (M273 generate-report baseline)
        # would always process the full cache even when the caller
        # only needs a single-chunk smoke-quality report. Default
        # max-chunks is high (999) so prod/baseline paths are
        # unaffected; batch_generate_reports.py now passes a small
        # cap (default 1) for dev sweeps.
        if not resume_mode and args.max_chunks > 0:
            chunk_files = chunk_files[: args.max_chunks]
        if not resume_mode:
            stop_reason = "from_cache_complete"
        tag = "--resume-from-cache" if resume_mode else "--from-cache"

        # Heads-up: reading a large existing cache is synchronous and
        # silent (no chunk_progress events fire during the replay —
        # those are emitted only from the live sampling loop below).
        # On M14's 165-chunk cache this read takes ~80s, during which
        # the batch log shows nothing and operators assume it's stuck
        # (2026-04-21 report: "启动拉取以后 log 没变化 估计卡住了").
        # Emit a single read-start event + a periodic progress event
        # every ~10% or 20 chunks (whichever is larger) so the strip
        # keeps ticking.
        total_to_read = len(chunk_files)
        if total_to_read > 0:
            append_jsonl(
                progress_file,
                {
                    "event": "cache_read_start",
                    "run_id": run_id,
                    "tag": tag,
                    "total_chunks": total_to_read,
                    "ts": utc_now(),
                },
            )
        read_progress_step = max(20, total_to_read // 10) if total_to_read > 0 else 0
        # Track md5-filtered skip count so the cache_read_done event
        # can tell the operator "N chunks read, K skipped due to md5
        # drift" — important feedback when the (machine, mode) has a
        # mix of current + historical md5 chunks.
        md5_filter_active = bool(args.upstream_config_md5 or args.upstream_code_md5)
        historical_md5_skipped = 0

        # Phase C2: pre-register feature plugins BEFORE the merge loop so
        # that ALL_FEATURES is populated when extract() is called per chunk.
        # Without this block, ALL_FEATURES is empty during the merge loop
        # (plugins are lazy-imported at emit time) → extract() is never called
        # → payouts_by_spin_type accumulator stays empty → emit() writes
        # empty lists (C1 latent bug class; C2 is first phase with real
        # extract() work). Imports are idempotent (Python module cache +
        # register() duplicate guard).
        try:
            import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
            import fresh_slotlab.analyzer.features.reel_marginal_by_spin_type  # noqa: F401
            import fresh_slotlab.analyzer.features.bankruptcy_simulation  # noqa: F401
            import fresh_slotlab.analyzer.features.multiplier_profile  # noqa: F401
            import fresh_slotlab.analyzer.features.multiplier_wild  # noqa: F401  # C3.5
            import fresh_slotlab.analyzer.features.machine_mechanics  # noqa: F401  # C4
            import fresh_slotlab.analyzer.features.upstream_feature_breakdown  # noqa: F401  # C5
            import fresh_slotlab.analyzer.features.collect_mechanic  # noqa: F401  # C5
        except ImportError:  # running as standalone script
            import analyzer.features.payouts_by_spin_type  # type: ignore[no-redef]  # noqa: F401
            import analyzer.features.reel_marginal_by_spin_type  # type: ignore[no-redef]  # noqa: F401
            import analyzer.features.bankruptcy_simulation  # type: ignore[no-redef]  # noqa: F401
            import analyzer.features.multiplier_profile  # type: ignore[no-redef]  # noqa: F401
            import analyzer.features.multiplier_wild  # type: ignore[no-redef]  # noqa: F401  # C3.5
            import analyzer.features.machine_mechanics  # type: ignore[no-redef]  # noqa: F401  # C4
            import analyzer.features.upstream_feature_breakdown  # type: ignore[no-redef]  # noqa: F401  # C5
            import analyzer.features.collect_mechanic  # type: ignore[no-redef]  # noqa: F401  # C5

        for read_idx, cf in enumerate(chunk_files):
            # Fast path: when a md5 filter is active, consult the
            # per-mode sidecar (``_chunks.json``) first. Sidecar
            # entry hit + non-match → skip the full chunk-file read
            # + JSON parse + sha256 integrity check entirely. Cuts
            # ~100MB / ~15s off a historical-md5 replay where the
            # operator swapped cfg and nothing will match the new
            # filter.
            #
            # Sidecar miss (new chunk not yet indexed, legacy
            # envelope, mid-migration) → fall through to the full
            # load path below, which still works correctly.
            if md5_filter_active:
                sidecar_entry = _sidecar_entries.get(cf.name)
                if isinstance(sidecar_entry, dict):
                    peek_idx = int(sidecar_entry.get("idx", 0) or 0)
                    peek_cfg = str(sidecar_entry.get("cfg_md5", "") or "")
                    peek_code = str(sidecar_entry.get("code_md5", "") or "")
                    max_existing_idx = max(max_existing_idx, peek_idx)
                    if (
                        peek_cfg != args.upstream_config_md5
                        or peek_code != args.upstream_code_md5
                    ):
                        historical_md5_skipped += 1
                        if (
                            read_progress_step > 0
                            and total_to_read > 0
                            and (read_idx + 1) % read_progress_step == 0
                            and (read_idx + 1) < total_to_read
                        ):
                            append_jsonl(
                                progress_file,
                                {
                                    "event": "cache_read_progress",
                                    "run_id": run_id,
                                    "chunks_read": read_idx + 1,
                                    "total_chunks": total_to_read,
                                    "total_spins": total_spins,
                                    "md5_skipped": historical_md5_skipped,
                                    "ts": utc_now(),
                                },
                            )
                        continue

            try:
                raw = load_chunk_envelope(cf)
            except ChunkIntegrityError as exc:
                raise SystemExit(f"{tag}: {exc}")
            # Honour envelope metadata for bet + chunk index even on
            # md5-skip chunks (so next_chunk_index never collides with
            # an existing file on disk, regardless of md5 match).
            chunk_bet_val = int(raw.get("_bet", args.bet) or args.bet)
            idx = int(raw.get("_chunk_index", next_chunk_index))
            max_existing_idx = max(max_existing_idx, idx)

            # md5 filter — fall-through case (peek failed earlier so
            # we've already paid the full-load cost; just confirm
            # match here using the parsed envelope).
            if md5_filter_active:
                cfg_env = str(raw.get("_config_md5", "") or "")
                code_env = str(raw.get("_code_md5", "") or "")
                if cfg_env != args.upstream_config_md5 or code_env != args.upstream_code_md5:
                    historical_md5_skipped += 1
                    if (
                        read_progress_step > 0
                        and total_to_read > 0
                        and (read_idx + 1) % read_progress_step == 0
                        and (read_idx + 1) < total_to_read
                    ):
                        append_jsonl(
                            progress_file,
                            {
                                "event": "cache_read_progress",
                                "run_id": run_id,
                                "chunks_read": read_idx + 1,
                                "total_chunks": total_to_read,
                                "total_spins": total_spins,
                                "md5_skipped": historical_md5_skipped,
                                "ts": utc_now(),
                            },
                        )
                    continue

            resp = raw.get("response")
            if resp is None:
                raise SystemExit(f"{tag}: {cf.name} missing 'response' key")
            rec = parse_chunk_response(
                resp, idx, chunk_bet_val,
                bankruptcy_session_spins=args.bankruptcy_session_spins,
                bankruptcy_bankroll_mults=_bankruptcy_mults_tuple,
                round_win_rules=_round_win_rules,
                use_play_type_plugins=getattr(args, "use_play_type_plugins", False),
            )
            if not rec.get("ok"):
                raise SystemExit(f"{tag}: {cf.name} parse failed: {rec.get('error')}")
            # ── identical merge block as online path (below) ──
            # We must replicate the merge here because the online loop is
            # inside a while-block we skip. A helper would be cleaner but
            # duplicating keeps the diff small and avoids touching 200+
            # lines of battle-tested merge logic. The "for rec in ..."
            # block below is the canonical merge; we jump directly there
            # by repackaging as a single-element batch_results list.
            batch_results_fc = [rec]
            for rec in batch_results_fc:  # noqa: PLW2901 — intentional rebind
                chunks += 1
                spins = int(rec["spins"])
                bet_amt = float(rec["bet"])
                win_amt = float(rec["win"])
                total_spins += spins
                total_bet += bet_amt
                total_win += win_amt
                chunk_rtp = (win_amt / bet_amt) * 100.0 if bet_amt > 0 else 0.0
                chunk_rtps_pct.append(chunk_rtp)
                ret_count += int(rec["ret_count"])
                ret_sum += float(rec["ret_sum"])
                ret_sq_sum += float(rec["ret_sq_sum"])
                max_observed_return_x = max(max_observed_return_x, float(rec["max_return_x"]))
                win_spins += int(rec["win_spins"])
                loss_spins += int(rec["loss_spins"])
                profit_spins += int(rec["profit_spins"])
                breakeven_or_more_spins += int(rec["breakeven_or_more_spins"])
                big_win_x10_spins += int(rec["big_win_x10_spins"])
                win_sum += float(rec["win_sum"])
                lack_credit_spins += int(rec["lack_credit_spins"])
                for lid, c in rec["payline_hits"].items():
                    payline_hits[str(lid)] += int(c)
                for lid, w in rec["payline_win_approx"].items():
                    payline_win_approx[str(lid)] += float(w)
                for lid, smap in (rec.get("payline_winning_symbols") or {}).items():
                    if isinstance(smap, dict):
                        for sym, c in smap.items():
                            payline_winning_symbols[str(lid)][str(sym)] += int(c)
                for lid, smap in (rec.get("payline_winning_symbols_rln") or {}).items():
                    if isinstance(smap, dict):
                        for code, c in smap.items():
                            payline_winning_symbols_rln[str(lid)][str(code)] += int(c)
                for L in rec.get("bonus_chain_lengths") or []:
                    bonus_chain_lengths.append(int(L))
                for L in rec.get("bonus_chain_max_ratios") or []:
                    bonus_chain_max_ratios.append(int(L))
                for L in rec.get("bonus_chain_retrigger_events") or []:
                    bonus_chain_retrigger_events.append(int(L))
                bonus_total_rounds_global += int(rec.get("bonus_total_rounds", 0) or 0)
                bonus_retrigger_rounds_global += int(rec.get("bonus_retrigger_rounds", 0) or 0)
                for ratio_str, c in (rec.get("bonus_extra_ratio_counts") or {}).items():
                    try:
                        bonus_extra_ratio_counts[int(ratio_str)] += int(c)
                    except (TypeError, ValueError):
                        pass
                for depth, s in (rec.get("bonus_depth_ratio_sum") or {}).items():
                    bonus_depth_ratio_sum[str(depth)] += float(s)
                for depth, c in (rec.get("bonus_depth_ratio_count") or {}).items():
                    bonus_depth_ratio_count[str(depth)] += int(c)
                for sym, c in rec["symbol_counts"].items():
                    symbol_counts[str(sym)] += int(c)
                for ci_text, cmap in rec["symbol_counts_by_col"].items():
                    ci = int(ci_text)
                    if isinstance(cmap, dict):
                        for sym, c in cmap.items():
                            symbol_counts_by_col[ci][str(sym)] += int(c)
                # 2026-04-24: merge per-row counts + payline row set.
                # Tolerate missing keys so analyzing pre-2026-04-24 cached
                # chunks doesn't crash (old chunks just skip this merge;
                # payline density then defaults to mid-row fallback).
                for ci_text, row_map in (rec.get("symbol_counts_by_col_by_row") or {}).items():
                    ci = int(ci_text)
                    if isinstance(row_map, dict):
                        for ri_text, sym_map in row_map.items():
                            try:
                                ri = int(ri_text)
                            except (TypeError, ValueError):
                                continue
                            if isinstance(sym_map, dict):
                                for sym, c in sym_map.items():
                                    symbol_counts_by_col_by_row[ci][ri][str(sym)] += int(c)
                # 2026-05-14: merge per-ST symbol counts per column.
                for st_text, col_map in (rec.get("symbol_counts_by_col_by_spin_type") or {}).items():
                    try:
                        _merge_st = int(st_text)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(col_map, dict):
                        for ci_text2, sym_map in col_map.items():
                            try:
                                _merge_ci = int(ci_text2)
                            except (TypeError, ValueError):
                                continue
                            if isinstance(sym_map, dict):
                                for sym, c in sym_map.items():
                                    symbol_counts_by_col_by_spin_type_total[_merge_st][_merge_ci][str(sym)] += int(c)
                for ci_text, rows_list in (rec.get("payline_rows_per_col") or {}).items():
                    try:
                        ci = int(ci_text)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(rows_list, list):
                        payline_rows_per_col[ci].update(int(r) for r in rows_list)
                total_symbol_slots += int(rec["total_symbol_slots"])
                for k, c in rec["loss_streak_hist"].items():
                    loss_streak_hist[int(k)] += int(c)
                for k, c in rec["win_streak_hist"].items():
                    win_streak_hist[int(k)] += int(c)
                max_loss_streak = max(max_loss_streak, int(rec["max_loss_streak"]))
                max_win_streak = max(max_win_streak, int(rec["max_win_streak"]))
                for k, c in rec["multiplier_bucket_spins"].items():
                    multiplier_bucket_spins[str(k)] += int(c)
                for k, v in rec["multiplier_bucket_bet"].items():
                    multiplier_bucket_bet[str(k)] += float(v)
                for k, v in rec["multiplier_bucket_win"].items():
                    multiplier_bucket_win[str(k)] += float(v)
                for k, c in (rec.get("payout_group_hits") or {}).items():
                    payout_group_hits[int(k)] += int(c)
                for k, w in (rec.get("payout_group_win") or {}).items():
                    payout_group_win[int(k)] += float(w)
                for pid, c in (rec.get("payout_id_hits") or {}).items():
                    payout_id_hits[str(pid)] += int(c)
                for pid, w in (rec.get("payout_id_win") or {}).items():
                    payout_id_win[str(pid)] += float(w)
                for pid, st_map in (rec.get("payout_id_by_spin_type") or {}).items():
                    if not isinstance(st_map, dict):
                        continue
                    for st_key, cnt in st_map.items():
                        try:
                            _st_int = int(st_key)
                        except (TypeError, ValueError):
                            _st_int = -1
                        payout_id_by_spin_type_total[str(pid)][_st_int] += int(cnt or 0)
                # Phase C2: payout_id_win_by_spin_type_total removed — now owned
                # by PayoutsBySpinType plugin's extract()/reduce() accumulator.
                for st, c in (rec.get("spin_type_spins") or {}).items():
                    spin_type_spins[int(st)] += int(c)
                for st, b in (rec.get("spin_type_bet") or {}).items():
                    spin_type_bet[int(st)] += float(b)
                for st, b in (rec.get("spin_type_paid_bet") or {}).items():
                    spin_type_paid_bet[int(st)] += float(b)
                for st, w in (rec.get("spin_type_win") or {}).items():
                    spin_type_win[int(st)] += float(w)
                for st, c in (rec.get("spin_type_wins") or {}).items():
                    spin_type_wins[int(st)] += int(c)
                for st, c in (rec.get("spin_type_paid_rounds") or {}).items():
                    spin_type_paid_rounds[int(st)] += int(c)
                for st_from, transitions in (rec.get("spin_type_next_counts") or {}).items():
                    if not isinstance(transitions, dict):
                        continue
                    for st_to, c in transitions.items():
                        spin_type_next_counts[int(st_from)][int(st_to)] += int(c)
                for st, rms in (rec.get("spin_type_remarks_sample") or {}).items():
                    if not isinstance(rms, list):
                        continue
                    bucket = spin_type_remarks_sample[int(st)]
                    for s in rms:
                        if isinstance(s, str) and s and len(bucket) < 6 and s not in bucket:
                            bucket.append(s)
                for st, n in (rec.get("spin_type_nudge_round_count") or {}).items():
                    spin_type_nudge_round_count[int(st)] += int(n or 0)
                for st, buckets in (rec.get("spin_type_bucket_spins") or {}).items():
                    if isinstance(buckets, dict):
                        for bname, c in buckets.items():
                            spin_type_bucket_spins[int(st)][str(bname)] += int(c or 0)
                for st, buckets in (rec.get("spin_type_bucket_bet") or {}).items():
                    if isinstance(buckets, dict):
                        for bname, v in buckets.items():
                            spin_type_bucket_bet[int(st)][str(bname)] += float(v or 0.0)
                for st, buckets in (rec.get("spin_type_bucket_win") or {}).items():
                    if isinstance(buckets, dict):
                        for bname, v in buckets.items():
                            spin_type_bucket_win[int(st)][str(bname)] += float(v or 0.0)
                # Iter 6: merge per-chunk session-bucket-by-settlement-ST.
                for st, buckets in (rec.get("session_bucket_spins_by_settlement_st") or {}).items():
                    if isinstance(buckets, dict):
                        for bname, c in buckets.items():
                            session_bucket_spins_by_settlement_st[int(st)][str(bname)] += int(c or 0)
                for st, buckets in (rec.get("session_bucket_bet_by_settlement_st") or {}).items():
                    if isinstance(buckets, dict):
                        for bname, v in buckets.items():
                            session_bucket_bet_by_settlement_st[int(st)][str(bname)] += float(v or 0.0)
                for st, buckets in (rec.get("session_bucket_win_by_settlement_st") or {}).items():
                    if isinstance(buckets, dict):
                        for bname, v in buckets.items():
                            session_bucket_win_by_settlement_st[int(st)][str(bname)] += float(v or 0.0)
                for ent in (rec.get("chain_chunk_summaries") or []):
                    if not isinstance(ent, dict):
                        continue
                    key = (
                        int(ent.get("first_st", 0) or 0),
                        bool(ent.get("entry_cc_reset", False)),
                        int(ent.get("sp_type", 0) or 0),
                    )
                    chain_chunk_summaries[key]["count"] += int(ent.get("count", 0) or 0)
                    chain_chunk_summaries[key]["win"] += float(ent.get("win", 0) or 0)
                    chain_chunk_summaries[key]["bet"] += float(ent.get("bet", 0) or 0)
                # Per-chain-path bucket merges.
                for _bkey, _src in (
                    ("chain_bucket_spins", chain_bucket_spins),
                    ("chain_bucket_bet", chain_bucket_bet),
                    ("chain_bucket_win", chain_bucket_win),
                ):
                    for ent in (rec.get(_bkey) or []):
                        if not isinstance(ent, dict):
                            continue
                        key = (
                            int(ent.get("first_st", 0) or 0),
                            bool(ent.get("entry_cc_reset", False)),
                            int(ent.get("sp_type", 0) or 0),
                        )
                        buckets = ent.get("buckets") or {}
                        if not isinstance(buckets, dict):
                            continue
                        for bname, val in buckets.items():
                            if _bkey == "chain_bucket_spins":
                                _src[key][str(bname)] += int(val or 0)
                            else:
                                _src[key][str(bname)] += float(val or 0.0)
                for feat, payouts in (rec.get("upstream_feature_tally") or {}).items():
                    if not isinstance(payouts, dict):
                        continue
                    for pid, entry in payouts.items():
                        if not isinstance(entry, dict):
                            continue
                        upstream_feature_tally[str(feat)][str(pid)]["win"] += float(entry.get("win", 0.0) or 0.0)
                        upstream_feature_tally[str(feat)][str(pid)]["times"] += int(entry.get("times", 0) or 0)
                upstream_total_win += float(rec.get("upstream_chunk_total_win", 0.0) or 0.0)
                upstream_robots_seen += int(rec.get("upstream_chunk_robots_seen", 0) or 0)
                collect_count_total += int(rec.get("collect_count_total", 0) or 0)
                chunk_acc_max = int(rec.get("acc_credits_max", 0) or 0)
                if chunk_acc_max > acc_credits_max_global:
                    acc_credits_max_global = chunk_acc_max
                collect_robots_seen_total += int(rec.get("collect_robots_seen", 0) or 0)
                clamp_pending_paid_spins_total += int(rec.get("clamp_pending_paid_spins", 0) or 0)
                clamp_pending_robots_total += int(rec.get("clamp_pending_robots", 0) or 0)
                for pk in rec.get("cycle_peaks") or []:
                    all_cycle_peaks.append(int(pk))
                for fcc in rec.get("final_cc_values") or []:
                    all_final_cc_values.append(int(fcc))
                total_completed_cycles += int(rec.get("completed_cycles", 0) or 0)
                for key, entry in (rec.get("payline_symbol_joint") or {}).items():
                    if isinstance(entry, dict):
                        all_payline_symbol_joint[key]["hits"] += int(entry.get("hits", 0))
                        all_payline_symbol_joint[key]["win"] += float(entry.get("win", 0.0))
                for curve in rec.get("session_rtp_curves") or []:
                    if isinstance(curve, list):
                        all_session_rtp_curves.append(curve)
                for seq in rec.get("chain_ratio_sequences") or []:
                    if isinstance(seq, list):
                        all_chain_ratio_sequences.append(seq)
                for pos, cnt in (rec.get("reel_position_hits") or {}).items():
                    all_reel_position_hits[str(pos)] += int(cnt)
                for feat, fb in (rec.get("chains_by_feature") or {}).items():
                    if not isinstance(fb, dict):
                        continue
                    afb = all_chains_by_feature[str(feat)]
                    for L in fb.get("lengths") or []:
                        afb["lengths"].append(int(L))
                    for L in fb.get("max_ratios") or []:
                        afb["max_ratios"].append(int(L))
                    for L in fb.get("retrigger_events") or []:
                        afb["retrigger_events"].append(int(L))
                    afb["total_rounds"] += int(fb.get("total_rounds", 0) or 0)
                    afb["retrigger_rounds"] += int(fb.get("retrigger_rounds", 0) or 0)
                total_paid_sessions += int(rec.get("paid_session_count", 0) or 0)
                total_bonus_spins += int(rec.get("bonus_spin_count", 0) or 0)
                total_session_wins += int(rec.get("session_win_count", 0) or 0)
                total_session_loses += int(rec.get("session_lose_count", 0) or 0)
                total_session_profits += int(rec.get("session_profit_count", 0) or 0)
                total_session_breakevens += int(rec.get("session_breakeven_count", 0) or 0)
                total_session_big_win_x10 += int(rec.get("session_big_win_x10_count", 0) or 0)
                total_session_big_win_x20 += int(rec.get("session_big_win_x20_count", 0) or 0)
                total_session_big_win_x50 += int(rec.get("session_big_win_x50_count", 0) or 0)
                total_session_big_win_x100 += int(rec.get("session_big_win_x100_count", 0) or 0)
                # Bankruptcy sim histogram merge (elementwise sum of bins +
                # scalar totals per tier). Kept for backward compat with
                # cached chunks pre-dating the cross-chunk fix; finalize
                # prefers the streaming accumulator below when it has data.
                for _mk, _entry in (rec.get("bankruptcy_sim") or {}).items():
                    if not isinstance(_entry, dict):
                        continue
                    _m = int(_mk)
                    if _m not in bankruptcy_sim_totals:
                        bankruptcy_sim_totals[_m] = _empty_bankruptcy_tier()
                    _dst = bankruptcy_sim_totals[_m]
                    _dst["bankrupt"] += int(_entry.get("bankrupt", 0) or 0)
                    _dst["survived"] += int(_entry.get("survived", 0) or 0)
                    _sd = _entry.get("spins_done")
                    if isinstance(_sd, list) and _sd:
                        # Extend the unsorted combined list; finalize
                        # sorts once. O(N) append across chunks.
                        _dst["spins_done"].extend(int(v) for v in _sd)
                # Cross-chunk streaming accumulator: feed raw reps so
                # chunks below session_spins (virtual sampling 8k vs
                # session=10k) still contribute. Old chunk records lack
                # the field — feed_reps no-ops on missing data.
                _bk_reps = rec.get("bankruptcy_reps")
                if isinstance(_bk_reps, list) and _bk_reps:
                    bankruptcy_stream_acc.feed_reps(
                        [(int(t[0]), int(t[1])) for t in _bk_reps if isinstance(t, (list, tuple)) and len(t) >= 2]
                    )
                total_session_ret_count += int(rec.get("session_ret_count", 0) or 0)
                total_session_ret_sum += float(rec.get("session_ret_sum", 0.0) or 0.0)
                total_session_ret_sq_sum += float(rec.get("session_ret_sq_sum", 0.0) or 0.0)
                chunk_sess_max_ret = float(rec.get("session_max_return_x", 0.0) or 0.0)
                if chunk_sess_max_ret > total_session_max_return_x:
                    total_session_max_return_x = chunk_sess_max_ret
                total_session_win_sum += float(rec.get("session_win_sum", 0.0) or 0.0)
                for b, c in (rec.get("session_bucket_spins") or {}).items():
                    session_bucket_spins[str(b)] += int(c)
                for b, v in (rec.get("session_bucket_bet") or {}).items():
                    session_bucket_bet[str(b)] += float(v)
                for b, v in (rec.get("session_bucket_win") or {}).items():
                    session_bucket_win[str(b)] += float(v)
                for k, c in (rec.get("session_loss_streak_hist") or {}).items():
                    session_loss_streak_hist[int(k)] += int(c)
                for k, c in (rec.get("session_win_streak_hist") or {}).items():
                    session_win_streak_hist[int(k)] += int(c)
                chunk_sess_max_loss = int(rec.get("session_max_loss_streak", 0) or 0)
                if chunk_sess_max_loss > total_session_max_loss_streak:
                    total_session_max_loss_streak = chunk_sess_max_loss
                chunk_sess_max_win = int(rec.get("session_max_win_streak", 0) or 0)
                if chunk_sess_max_win > total_session_max_win_streak:
                    total_session_max_win_streak = chunk_sess_max_win
                for fld, cnt in (rec.get("extra_fields_seen") or {}).items():
                    total_extra_fields_seen[str(fld)] += int(cnt)
                # Per-machine mechanic merge.
                total_lock_lines_spins += int(rec.get("lock_lines_spins", 0) or 0)
                total_lock_lines_total_lines += int(rec.get("lock_lines_total_lines", 0) or 0)
                total_lock_lines_win += float(rec.get("lock_lines_win", 0) or 0)
                total_lock_symbols_spins += int(rec.get("lock_symbols_spins", 0) or 0)
                for s in rec.get("lock_symbols_unique") or []:
                    total_lock_symbols_unique.add(str(s))
                total_lock_symbols_win += float(rec.get("lock_symbols_win", 0) or 0)
                total_lock_reels_spins += int(rec.get("lock_reels_spins", 0) or 0)
                total_lock_reels_win += float(rec.get("lock_reels_win", 0) or 0)
                total_jackpot_spins += int(rec.get("jackpot_spins", 0) or 0)
                for j in rec.get("jackpot_ids_seen") or []:
                    total_jackpot_ids_seen.add(str(j))
                total_jackpot_win += float(rec.get("jackpot_win", 0) or 0)
                total_freespin_chain_spins += int(rec.get("freespin_chain_spins", 0) or 0)
                total_freespin_retriggers += int(rec.get("freespin_retriggers", 0) or 0)
                fsmc = int(rec.get("freespin_max_chain", 0) or 0)
                if fsmc > total_freespin_max_chain:
                    total_freespin_max_chain = fsmc
                total_freespin_win += float(rec.get("freespin_win", 0) or 0)
                total_dollar_pick_spins += int(rec.get("dollar_pick_spins", 0) or 0)
                total_dollar_pick_total_dollars += int(rec.get("dollar_pick_total_dollars", 0) or 0)
                total_dollar_pick_win += float(rec.get("dollar_pick_win", 0) or 0)
                # EC-4 consumer (critique_commitC1 finding #2): collect
                # _plugin_partial_attribution_errors from each chunk dict.
                # parse_chunk_response writes this key only when non-empty;
                # tolerate absence (old cached chunks or no-fault chunks).
                _chunk_plugin_errs = rec.get("_plugin_partial_attribution_errors")
                if isinstance(_chunk_plugin_errs, list) and _chunk_plugin_errs:
                    for _cpe in _chunk_plugin_errs:
                        _play_type_plugin_errors_total.append(
                            dict(_cpe, chunk_index=rec.get("index", "?"))
                        )
                # Phase C1: wire extract() per chunk (from-cache path).
                # ALL_FEATURES is not imported yet at this point; we defer
                # to a lazy import pattern so we can call extract() here without
                # pulling the full feature set into the module top. The import
                # is idempotent (Python module cache). Pattern-A plugins return {}
                # so no behavior change in C1. We use a try/except so a missing
                # feature module doesn't abort the cache replay.
                try:
                    try:
                        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES as _fc_features
                        from fresh_slotlab.analyzer.parse_state import ParseState as _fc_ParseState
                    except ImportError:
                        from analyzer.feature_registry import ALL_FEATURES as _fc_features  # type: ignore[no-redef]
                        from analyzer.parse_state import ParseState as _fc_ParseState  # type: ignore[no-redef]
                    _fc_parse_state = _fc_ParseState(
                        chunk_dict=rec,
                        machine_id=args.machine,
                        mode=args.rtp_mode,
                        manifest={},  # manifest not yet loaded; plugins don't use it in extract()
                    )
                    for _fc_feat in _fc_features:
                        try:
                            _fc_this = _fc_feat.extract(_fc_parse_state, rec)
                            _feature_accs[_fc_feat.FEATURE_ID] = _fc_feat.reduce(
                                _feature_accs.get(_fc_feat.FEATURE_ID, {}),
                                _fc_this,
                            )
                        except Exception as _fc_exc:  # noqa: BLE001
                            # Phase C2: extract()/reduce() error — persist diagnostic
                            # per feedback_no_silent_swallow.md; do NOT silently pass.
                            # Use prev_acc unchanged; capture error for feature_errors.
                            import sys as _fc_sys
                            print(
                                f"WARNING: feature '{_fc_feat.FEATURE_ID}' "
                                f"extract()/reduce() failed on chunk "
                                f"{rec.get('index', '?')}: {_fc_exc}",
                                file=_fc_sys.stderr,
                            )
                            _feature_accs.setdefault(
                                f"_extract_error_{_fc_feat.FEATURE_ID}", []
                            ).append(str(_fc_exc))
                except Exception:  # noqa: BLE001
                    # Outer guard: import failure or ParseState construction
                    # failure. These are infrastructure errors; keep pass here
                    # to avoid aborting the cache replay on transient issues.
                    pass

            # Emit heartbeat every read_progress_step chunks so the
            # batch log keeps ticking during the long silent replay.
            # Guarded by read_progress_step > 0 (empty-cache case).
            if (
                read_progress_step > 0
                and total_to_read > 0
                and (read_idx + 1) % read_progress_step == 0
                and (read_idx + 1) < total_to_read
            ):
                append_jsonl(
                    progress_file,
                    {
                        "event": "cache_read_progress",
                        "run_id": run_id,
                        "chunks_read": read_idx + 1,
                        "total_chunks": total_to_read,
                        "total_spins": total_spins,
                        "ts": utc_now(),
                    },
                )

            # Early-stop: if the cumulative CI already meets the
            # caller's target, there's no need to read (or sample) any
            # further. Skips the remaining replay + the live sampling
            # loop entirely — a ~80s read on a 165-chunk cache can
            # finish in ~20s when the first 40-60 chunks already
            # achieve target. User 2026-04-21: "我刚刚就采样一个机台，
            # 也会读这么多?". For target=0 (fuzzy / no CI gate) the
            # check is disabled and we read everything to give the
            # final report max precision.
            if (
                resume_mode
                and args.target_halfwidth_pp > 0
                and args.target_halfwidth_pp < 999.0
                and ret_count > 1
            ):
                ci_now = session_halfwidth_pp(ret_count, ret_sum, ret_sq_sum)
                if ci_now is not None and ci_now <= args.target_halfwidth_pp:
                    append_jsonl(
                        progress_file,
                        {
                            "event": "cache_read_target_met",
                            "run_id": run_id,
                            "chunks_read": read_idx + 1,
                            "total_chunks": total_to_read,
                            "total_spins": total_spins,
                            "current_halfwidth_pp": ci_now,
                            "target_halfwidth_pp": args.target_halfwidth_pp,
                            "ts": utc_now(),
                        },
                    )
                    stop_reason = "target_ci_reached_from_cache"
                    skip_sampling_loop = True
                    break

        if total_to_read > 0:
            append_jsonl(
                progress_file,
                {
                    "event": "cache_read_done",
                    "run_id": run_id,
                    "chunks_read": total_to_read,
                    "chunks_merged": chunks,
                    "md5_skipped": historical_md5_skipped,
                    "total_spins": total_spins,
                    "ts": utc_now(),
                },
            )

        if resume_mode:
            # Prime state so the live sampling loop picks up right after
            # the last cached chunk. New chunks go into the same dir so
            # a subsequent resume sees all of them.
            next_chunk_index = max_existing_idx + 1
            args.chunk_cache_dir = cache_read_dir
            # Budget repair: ``args.max_chunks`` is an *absolute chunk
            # index ceiling*, but the caller usually sets it relative
            # to a clean ``chunk_1`` start (count-mode 总量 strategy
            # especially). When existing-on-disk chunks push
            # ``next_chunk_index`` past that ceiling, the live
            # sampling loop would exit immediately with 0 spins — the
            # user's budget silently evaporates. Triggers most often
            # after a ``machineconfig/<u>Cfg.txt`` swap: the new
            # ``localcfg_<hash>`` filters out every historical chunk,
            # ``chunks == 0`` after replay, but indices 1..29 still
            # occupy the name space so ``next_chunk_index == 30`` for
            # a budget of 1. Symptom: "sampling produced 0 spins
            # after 0 chunk(s); stop_reason=max_chunks_reached".
            #
            # Fix: interpret the shortfall as "remaining NEW chunks
            # the user still wants" and extend ``max_chunks`` past
            # the existing ceiling. ``remaining_new`` keeps honoring
            # already-counted replay chunks so partial-match resumes
            # (some v1 + some v2, still v1-sampling) behave correctly.
            if next_chunk_index > args.max_chunks:
                remaining_new = max(1, args.max_chunks - chunks)
                args.max_chunks = max_existing_idx + remaining_new
            append_jsonl(
                progress_file,
                {
                    "event": "resume_from_cache",
                    "run_id": run_id,
                    "existing_chunks": chunks,
                    "existing_spins": total_spins,
                    "historical_md5_skipped": historical_md5_skipped,
                    "next_chunk_index": next_chunk_index,
                    "adjusted_max_chunks": args.max_chunks,
                    "ts": utc_now(),
                },
            )

    # Mid-run disk guard: pre-run check (in backend start_batch) only
    # sees the state at kickoff; an overnight 3M-spin run can fill the
    # disk mid-sample. We check here every iteration and stop gracefully
    # (summary still builds with partial data) when free space drops
    # below 2 GB on the output dir's filesystem. Cheap os.statvfs /
    # shutil.disk_usage — ~microseconds. Skips when output_dir's parent
    # doesn't exist (shouldn't happen post-argparse).
    _DISK_GUARD_MIN_FREE_GB = 2.0
    _disk_guard_path = args.output_dir if args.output_dir.exists() else args.output_dir.parent

    # Per-request MachineConfig override — read once at startup so we
    # don't re-read the file per chunk. An empty / missing file path
    # means "use global cfg.json on the server", same as not passing
    # the flag at all. File read errors hard-fail so operators don't
    # accidentally sample against server cfg thinking they sampled
    # against their draft.
    _machine_config_str: str | None = None
    if args.machine_config_file:
        cfg_path = Path(args.machine_config_file)
        if not cfg_path.is_file():
            raise SystemExit(
                f"--machine-config-file not found or not a file: {cfg_path}"
            )
        _machine_config_str = cfg_path.read_text(encoding="utf-8")
        # Sanity-check JSON parseability so we don't discover upstream
        # rejected our payload after 100 chunks.
        try:
            json.loads(_machine_config_str)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"--machine-config-file is not valid JSON: {exc}"
            )

    # One-shot "first live fetch" signal for the UI log. The first
    # analyzer chunk typically takes 30-60s (Python startup + first
    # HTTP call + robot fan-out). Emitting this event right before the
    # first batch submit gives the operator a concrete "⇅ 请求 chunk 1…"
    # line to look at during that window, instead of an apparently-
    # frozen panel between `analyzer_started` and the first chunk_progress.
    first_fetch_emitted = False

    # AIMD adaptive tuning state. Starts at user's setting, halved on
    # fully-failed batch, grown back toward the ceiling over
    # SUCCESS_STREAK_FOR_GROW consecutive clean batches. Gives upstream
    # breathing room during sustained slowdowns without the whole run
    # bailing at MAX_CONSECUTIVE_FAILED_BATCHES. See aimd_tune().
    current_concurrency = args.batch_concurrency
    current_chunk_spins = args.chunk_spin_times
    consecutive_successful_batches = 0
    last_batch_pause_until = 0.0  # time.time() to resume after circuit pause

    # Phase C2: pre-register feature plugins BEFORE the online merge loop so
    # that ALL_FEATURES is populated when extract() is called per chunk.
    # Mirrors the from-cache pre-registration block above (lines ~1521-1538).
    # Without this block, ALL_FEATURES is empty during the online loop
    # (plugins are lazy-imported at emit time only) → extract() is never called
    # → payouts_by_spin_type accumulator stays empty in pure-online mode.
    # Imports are idempotent (Python module cache + register() duplicate guard).
    try:
        import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
        import fresh_slotlab.analyzer.features.reel_marginal_by_spin_type  # noqa: F401
        import fresh_slotlab.analyzer.features.bankruptcy_simulation  # noqa: F401
        import fresh_slotlab.analyzer.features.multiplier_profile  # noqa: F401
        import fresh_slotlab.analyzer.features.multiplier_wild  # noqa: F401  # C3.5
        import fresh_slotlab.analyzer.features.machine_mechanics  # noqa: F401  # C4
        import fresh_slotlab.analyzer.features.upstream_feature_breakdown  # noqa: F401  # C5
        import fresh_slotlab.analyzer.features.collect_mechanic  # noqa: F401  # C5
    except ImportError:  # running as standalone script
        import analyzer.features.payouts_by_spin_type  # type: ignore[no-redef]  # noqa: F401
        import analyzer.features.reel_marginal_by_spin_type  # type: ignore[no-redef]  # noqa: F401
        import analyzer.features.bankruptcy_simulation  # type: ignore[no-redef]  # noqa: F401
        import analyzer.features.multiplier_profile  # type: ignore[no-redef]  # noqa: F401
        import analyzer.features.multiplier_wild  # type: ignore[no-redef]  # noqa: F401  # C3.5
        import analyzer.features.machine_mechanics  # type: ignore[no-redef]  # noqa: F401  # C4
        import analyzer.features.upstream_feature_breakdown  # type: ignore[no-redef]  # noqa: F401  # C5
        import analyzer.features.collect_mechanic  # type: ignore[no-redef]  # noqa: F401  # C5

    # ── online sampling path (skipped in read-only --from-cache mode) ──
    while not skip_sampling_loop and next_chunk_index <= args.max_chunks:
        # Circuit-breaker pause: after a fully-failed batch aimd_tune
        # sets this deadline; sleep in small increments so stop flag
        # can still interrupt us mid-pause.
        now_s = time.time()
        if now_s < last_batch_pause_until:
            remaining_pause = last_batch_pause_until - now_s
            append_jsonl(
                progress_file,
                {
                    "event": "circuit_pause",
                    "run_id": run_id,
                    "pause_seconds": round(remaining_pause, 2),
                    "reason": "fully_failed_batch",
                    "ts": utc_now(),
                },
            )
            # Sleep in 1s steps so stop_requested / stop_flag_file can
            # still bail us out inside the pause window.
            while time.time() < last_batch_pause_until:
                if stop_requested["value"] or (
                    args.stop_flag_file is not None and args.stop_flag_file.exists()
                ):
                    break
                time.sleep(min(1.0, last_batch_pause_until - time.time()))
            last_batch_pause_until = 0.0
        # Graceful-stop checkpoint: if the operator clicked Stop, bail
        # out here so any completed chunks (aggregated up to the
        # previous batch end) still reach the summary-build path. The
        # summary will carry stop_reason="user_stop" so the watcher
        # can flag the run as cancelled-with-data rather than failed.
        if stop_requested["value"] or (
            args.stop_flag_file is not None and args.stop_flag_file.exists()
        ):
            stop_reason = "user_stop"
            break

        # Mid-run disk guard.
        try:
            free_gb = shutil.disk_usage(_disk_guard_path).free / (1024 ** 3)
            if free_gb < _DISK_GUARD_MIN_FREE_GB:
                stop_reason = f"disk_low_{free_gb:.2f}GB"
                append_jsonl(
                    progress_file,
                    {
                        "event": "disk_guard_stop",
                        "run_id": run_id,
                        "free_gb": round(free_gb, 3),
                        "threshold_gb": _DISK_GUARD_MIN_FREE_GB,
                        "chunks_completed": chunks,
                        "total_spins": total_spins,
                        "ts": utc_now(),
                    },
                )
                break
        except OSError:
            # Disk check failure (weird FS, permission, etc.) shouldn't
            # abort sampling — log quietly and keep going.
            pass

        remaining = args.max_chunks - chunks
        # AIMD-adapted concurrency (shrinks on upstream stress, grows
        # back to args.batch_concurrency over consecutive clean batches).
        batch_size = min(current_concurrency, remaining)
        if batch_size <= 0:
            break

        indices = list(range(next_chunk_index, next_chunk_index + batch_size))
        next_chunk_index += batch_size

        if not first_fetch_emitted:
            first_fetch_emitted = True
            append_jsonl(
                progress_file,
                {
                    "event": "fetching_chunk",
                    "run_id": run_id,
                    "chunk_index": indices[0],
                    "batch_size": batch_size,
                    "ts": utc_now(),
                },
            )

        batch_results: list[dict[str, Any]] = []
        chunk_cache = getattr(args, "chunk_cache_dir", None)

        # Emit chunk_started per submitted index BEFORE the HTTP calls
        # block. The frontend derives its "in-flight chunks" section by
        # pairing chunk_started events (by chunk_index) with their
        # eventual chunk_progress / chunk_failed counterparts — ones
        # without a pair are still in flight and get a live elapsed
        # ticker. Without this, a 4-way concurrent batch where one
        # request takes 90s would show nothing to the operator for 90s.
        for idx in indices:
            append_jsonl(
                progress_file,
                {
                    "event": "chunk_started",
                    "run_id": run_id,
                    "chunk_index": idx,
                    "ts": utc_now(),
                },
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = [
                executor.submit(
                    run_sampling_chunk,
                    idx,
                    args.machine,
                    args.rtp_mode,
                    args.bet,
                    # AIMD-adapted chunk size (shrinks on upstream
                    # stress to give each HTTP request less work;
                    # grows back to args.chunk_spin_times over
                    # consecutive clean batches). Each chunk's envelope
                    # records the effective chunk_spin_times so offline
                    # aggregation + collect-cycle correction (which
                    # walks per-chunk CC resets) stays correct across
                    # variable chunk sizes.
                    current_chunk_spins,
                    args.chunk_robot_count,
                    args.timeout,
                    chunk_cache_dir=chunk_cache,
                    bankruptcy_session_spins=args.bankruptcy_session_spins,
                    bankruptcy_bankroll_mults=_bankruptcy_mults_tuple,
                    upstream_machine_name=args.upstream_machine_name,
                    machine_config=_machine_config_str,
                    # Stamp new chunks with whatever md5 the analyzer
                    # is filtering against — not ``machines.json``'s
                    # global md5. Without this, chunks produced with
                    # a ``localcfg_<hash>`` filter still land in the
                    # global md5 bucket and silently merge on next
                    # resume (user-reported 2026-04-24: "通过本地
                    # 配置拉取下来的 rawdata md5 管理还是有问题").
                    envelope_config_md5=args.upstream_config_md5 or "",
                    envelope_code_md5=args.upstream_code_md5 or "",
                    round_win_rules=_round_win_rules,
                    use_play_type_plugins=getattr(args, "use_play_type_plugins", False),
                )
                for idx in indices
            ]
            # Process each future AS its chunk returns, not after the
            # whole batch. Previously the aggregate+emit block ran once
            # at batch-end — if chunk 38 returned in 30s but chunk 41
            # took 90s, the user saw nothing for 90s and then 4 events
            # landed together. Now each chunk's chunk_progress (success)
            # or chunk_failed (failure) fires the moment its future
            # resolves, giving the operator real-time per-chunk feedback.
            # Aggregation order becomes network-completion order rather
            # than sorted-by-submit-index, but every aggregation op is
            # associative+commutative (sums, maxes, list appends used
            # only for order-invariant stats), so totals are identical
            # either way. The `chunk_rtps_pct` list ordering changes but
            # is only consumed by `ci_halfwidth_pp` (stdev) which is
            # order-invariant.
            for future in concurrent.futures.as_completed(futures):
                rec = future.result()
                batch_results.append(rec)
                if not rec.get("ok"):
                    err_class = _classify_failure(rec.get("error", ""))
                    if err_class == "network":
                        cumulative_failed_chunks_net += 1
                    else:
                        cumulative_failed_chunks_machine += 1
                    cumulative_failed_chunks = (
                        cumulative_failed_chunks_net + cumulative_failed_chunks_machine
                    )
                    append_jsonl(
                        progress_file,
                        {
                            "event": "chunk_failed",
                            "run_id": run_id,
                            "chunk_index": rec.get("index"),
                            "error": rec.get("error"),
                            "error_class": err_class,
                            "cumulative_failed": cumulative_failed_chunks,
                            "cumulative_failed_net": cumulative_failed_chunks_net,
                            "cumulative_failed_machine": cumulative_failed_chunks_machine,
                            "chunks_completed_so_far": chunks,
                            "total_spins_so_far": total_spins,
                            "ts": utc_now(),
                        },
                    )
                    continue
                # Success path: aggregate into globals + emit
                # chunk_progress.
                chunks += 1
                spins = int(rec["spins"])
                bet_amt = float(rec["bet"])
                win_amt = float(rec["win"])

                total_spins += spins
                total_bet += bet_amt
                total_win += win_amt

                chunk_rtp = (win_amt / bet_amt) * 100.0 if bet_amt > 0 else 0.0
                chunk_rtps_pct.append(chunk_rtp)

                ret_count += int(rec["ret_count"])
                ret_sum += float(rec["ret_sum"])
                ret_sq_sum += float(rec["ret_sq_sum"])
                max_observed_return_x = max(max_observed_return_x, float(rec["max_return_x"]))

                win_spins += int(rec["win_spins"])
                loss_spins += int(rec["loss_spins"])
                profit_spins += int(rec["profit_spins"])
                breakeven_or_more_spins += int(rec["breakeven_or_more_spins"])
                big_win_x10_spins += int(rec["big_win_x10_spins"])
                win_sum += float(rec["win_sum"])
                lack_credit_spins += int(rec["lack_credit_spins"])

                for lid, c in rec["payline_hits"].items():
                    payline_hits[str(lid)] += int(c)
                for lid, w in rec["payline_win_approx"].items():
                    payline_win_approx[str(lid)] += float(w)
                # payline_winning_symbols was added in the symbol-inference
                # commit; old chunk records (pre-feature) won't have it.
                for lid, smap in (rec.get("payline_winning_symbols") or {}).items():
                    if isinstance(smap, dict):
                        for sym, c in smap.items():
                            payline_winning_symbols[str(lid)][str(sym)] += int(c)
                # payline_winning_symbols_rln added in the RLN-auth commit.
                for lid, smap in (rec.get("payline_winning_symbols_rln") or {}).items():
                    if isinstance(smap, dict):
                        for code, c in smap.items():
                            payline_winning_symbols_rln[str(lid)][str(code)] += int(c)
                # bonus_chain_* added in the MapCollection dynamics commit.
                for L in rec.get("bonus_chain_lengths") or []:
                    bonus_chain_lengths.append(int(L))
                for L in rec.get("bonus_chain_max_ratios") or []:
                    bonus_chain_max_ratios.append(int(L))
                for L in rec.get("bonus_chain_retrigger_events") or []:
                    bonus_chain_retrigger_events.append(int(L))
                bonus_total_rounds_global += int(rec.get("bonus_total_rounds", 0) or 0)
                bonus_retrigger_rounds_global += int(rec.get("bonus_retrigger_rounds", 0) or 0)
                for ratio_str, c in (rec.get("bonus_extra_ratio_counts") or {}).items():
                    try:
                        bonus_extra_ratio_counts[int(ratio_str)] += int(c)
                    except (TypeError, ValueError):
                        pass
                for depth, s in (rec.get("bonus_depth_ratio_sum") or {}).items():
                    bonus_depth_ratio_sum[str(depth)] += float(s)
                for depth, c in (rec.get("bonus_depth_ratio_count") or {}).items():
                    bonus_depth_ratio_count[str(depth)] += int(c)

                for sym, c in rec["symbol_counts"].items():
                    symbol_counts[str(sym)] += int(c)
                for ci_text, cmap in rec["symbol_counts_by_col"].items():
                    ci = int(ci_text)
                    if isinstance(cmap, dict):
                        for sym, c in cmap.items():
                            symbol_counts_by_col[ci][str(sym)] += int(c)
                # 2026-04-24: merge per-row counts + payline row set
                # (tolerates pre-2026-04-24 chunks that lack these fields).
                for ci_text, row_map in (rec.get("symbol_counts_by_col_by_row") or {}).items():
                    ci = int(ci_text)
                    if isinstance(row_map, dict):
                        for ri_text, sym_map in row_map.items():
                            try:
                                ri = int(ri_text)
                            except (TypeError, ValueError):
                                continue
                            if isinstance(sym_map, dict):
                                for sym, c in sym_map.items():
                                    symbol_counts_by_col_by_row[ci][ri][str(sym)] += int(c)
                # 2026-05-14: merge per-ST symbol counts per column.
                for st_text, col_map in (rec.get("symbol_counts_by_col_by_spin_type") or {}).items():
                    try:
                        _merge_st = int(st_text)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(col_map, dict):
                        for ci_text2, sym_map in col_map.items():
                            try:
                                _merge_ci = int(ci_text2)
                            except (TypeError, ValueError):
                                continue
                            if isinstance(sym_map, dict):
                                for sym, c in sym_map.items():
                                    symbol_counts_by_col_by_spin_type_total[_merge_st][_merge_ci][str(sym)] += int(c)
                for ci_text, rows_list in (rec.get("payline_rows_per_col") or {}).items():
                    try:
                        ci = int(ci_text)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(rows_list, list):
                        payline_rows_per_col[ci].update(int(r) for r in rows_list)

                total_symbol_slots += int(rec["total_symbol_slots"])

                for k, c in rec["loss_streak_hist"].items():
                    loss_streak_hist[int(k)] += int(c)
                for k, c in rec["win_streak_hist"].items():
                    win_streak_hist[int(k)] += int(c)
                max_loss_streak = max(max_loss_streak, int(rec["max_loss_streak"]))
                max_win_streak = max(max_win_streak, int(rec["max_win_streak"]))

                for k, c in rec["multiplier_bucket_spins"].items():
                    multiplier_bucket_spins[str(k)] += int(c)
                for k, v in rec["multiplier_bucket_bet"].items():
                    multiplier_bucket_bet[str(k)] += float(v)
                for k, v in rec["multiplier_bucket_win"].items():
                    multiplier_bucket_win[str(k)] += float(v)

                for k, c in (rec.get("payout_group_hits") or {}).items():
                    payout_group_hits[int(k)] += int(c)
                for k, w in (rec.get("payout_group_win") or {}).items():
                    payout_group_win[int(k)] += float(w)
                # payout_id_* added in the PayoutIdToWinAmount commit; old
                # chunk records (pre-feature) tolerate missing via .get().
                for pid, c in (rec.get("payout_id_hits") or {}).items():
                    payout_id_hits[str(pid)] += int(c)
                for pid, w in (rec.get("payout_id_win") or {}).items():
                    payout_id_win[str(pid)] += float(w)
                for pid, st_map in (rec.get("payout_id_by_spin_type") or {}).items():
                    if not isinstance(st_map, dict):
                        continue
                    for st_key, cnt in st_map.items():
                        try:
                            _st_int = int(st_key)
                        except (TypeError, ValueError):
                            _st_int = -1
                        payout_id_by_spin_type_total[str(pid)][_st_int] += int(cnt or 0)
                # Phase C2: payout_id_win_by_spin_type_total removed — now owned
                # by PayoutsBySpinType plugin's extract()/reduce() accumulator.
                # spin_type_* added in the SpinType-breakdown commit; old
                # chunk records tolerate missing via .get().
                for st, c in (rec.get("spin_type_spins") or {}).items():
                    spin_type_spins[int(st)] += int(c)
                for st, b in (rec.get("spin_type_bet") or {}).items():
                    spin_type_bet[int(st)] += float(b)
                for st, b in (rec.get("spin_type_paid_bet") or {}).items():
                    spin_type_paid_bet[int(st)] += float(b)
                for st, w in (rec.get("spin_type_win") or {}).items():
                    spin_type_win[int(st)] += float(w)
                for st, c in (rec.get("spin_type_wins") or {}).items():
                    spin_type_wins[int(st)] += int(c)
                for st, c in (rec.get("spin_type_paid_rounds") or {}).items():
                    spin_type_paid_rounds[int(st)] += int(c)
                for st_from, transitions in (rec.get("spin_type_next_counts") or {}).items():
                    if not isinstance(transitions, dict):
                        continue
                    for st_to, c in transitions.items():
                        spin_type_next_counts[int(st_from)][int(st_to)] += int(c)
                for st, rms in (rec.get("spin_type_remarks_sample") or {}).items():
                    if not isinstance(rms, list):
                        continue
                    bucket = spin_type_remarks_sample[int(st)]
                    for s in rms:
                        if isinstance(s, str) and s and len(bucket) < 6 and s not in bucket:
                            bucket.append(s)
                for st, n in (rec.get("spin_type_nudge_round_count") or {}).items():
                    spin_type_nudge_round_count[int(st)] += int(n or 0)
                for st, buckets in (rec.get("spin_type_bucket_spins") or {}).items():
                    if isinstance(buckets, dict):
                        for bname, c in buckets.items():
                            spin_type_bucket_spins[int(st)][str(bname)] += int(c or 0)
                for st, buckets in (rec.get("spin_type_bucket_bet") or {}).items():
                    if isinstance(buckets, dict):
                        for bname, v in buckets.items():
                            spin_type_bucket_bet[int(st)][str(bname)] += float(v or 0.0)
                for st, buckets in (rec.get("spin_type_bucket_win") or {}).items():
                    if isinstance(buckets, dict):
                        for bname, v in buckets.items():
                            spin_type_bucket_win[int(st)][str(bname)] += float(v or 0.0)
                # Iter 6: merge per-chunk session-bucket-by-settlement-ST.
                for st, buckets in (rec.get("session_bucket_spins_by_settlement_st") or {}).items():
                    if isinstance(buckets, dict):
                        for bname, c in buckets.items():
                            session_bucket_spins_by_settlement_st[int(st)][str(bname)] += int(c or 0)
                for st, buckets in (rec.get("session_bucket_bet_by_settlement_st") or {}).items():
                    if isinstance(buckets, dict):
                        for bname, v in buckets.items():
                            session_bucket_bet_by_settlement_st[int(st)][str(bname)] += float(v or 0.0)
                for st, buckets in (rec.get("session_bucket_win_by_settlement_st") or {}).items():
                    if isinstance(buckets, dict):
                        for bname, v in buckets.items():
                            session_bucket_win_by_settlement_st[int(st)][str(bname)] += float(v or 0.0)
                for ent in (rec.get("chain_chunk_summaries") or []):
                    if not isinstance(ent, dict):
                        continue
                    key = (
                        int(ent.get("first_st", 0) or 0),
                        bool(ent.get("entry_cc_reset", False)),
                        int(ent.get("sp_type", 0) or 0),
                    )
                    chain_chunk_summaries[key]["count"] += int(ent.get("count", 0) or 0)
                    chain_chunk_summaries[key]["win"] += float(ent.get("win", 0) or 0)
                    chain_chunk_summaries[key]["bet"] += float(ent.get("bet", 0) or 0)
                # Per-chain-path bucket merges (resume_from_cache path).
                for _bkey, _src in (
                    ("chain_bucket_spins", chain_bucket_spins),
                    ("chain_bucket_bet", chain_bucket_bet),
                    ("chain_bucket_win", chain_bucket_win),
                ):
                    for ent in (rec.get(_bkey) or []):
                        if not isinstance(ent, dict):
                            continue
                        key = (
                            int(ent.get("first_st", 0) or 0),
                            bool(ent.get("entry_cc_reset", False)),
                            int(ent.get("sp_type", 0) or 0),
                        )
                        buckets = ent.get("buckets") or {}
                        if not isinstance(buckets, dict):
                            continue
                        for bname, val in buckets.items():
                            if _bkey == "chain_bucket_spins":
                                _src[key][str(bname)] += int(val or 0)
                            else:
                                _src[key][str(bname)] += float(val or 0.0)
                # upstream feature tally merge: additive per (feature, payid).
                # Older chunk records (pre-feature) lack the key -- safe via
                # .get() default.
                for feat, payouts in (rec.get("upstream_feature_tally") or {}).items():
                    if not isinstance(payouts, dict):
                        continue
                    for pid, entry in payouts.items():
                        if not isinstance(entry, dict):
                            continue
                        upstream_feature_tally[str(feat)][str(pid)]["win"] += float(
                            entry.get("win", 0.0) or 0.0
                        )
                        upstream_feature_tally[str(feat)][str(pid)]["times"] += int(
                            entry.get("times", 0) or 0
                        )
                # upstream analysis cross-check (older chunk records lack
                # these fields; .get() default keeps the comparison neutral).
                upstream_total_win += float(rec.get("upstream_chunk_total_win", 0.0) or 0.0)
                upstream_robots_seen += int(rec.get("upstream_chunk_robots_seen", 0) or 0)
                # collect-mechanic accumulators (M272+; absent on M14).
                collect_count_total += int(rec.get("collect_count_total", 0) or 0)
                chunk_acc_max = int(rec.get("acc_credits_max", 0) or 0)
                if chunk_acc_max > acc_credits_max_global:
                    acc_credits_max_global = chunk_acc_max
                collect_robots_seen_total += int(rec.get("collect_robots_seen", 0) or 0)
                # Trunk-clamp totals.
                clamp_pending_paid_spins_total += int(rec.get("clamp_pending_paid_spins", 0) or 0)
                clamp_pending_robots_total += int(rec.get("clamp_pending_robots", 0) or 0)
                for pk in rec.get("cycle_peaks") or []:
                    all_cycle_peaks.append(int(pk))
                for fcc in rec.get("final_cc_values") or []:
                    all_final_cc_values.append(int(fcc))
                total_completed_cycles += int(rec.get("completed_cycles", 0) or 0)
                # Raw-data analysis merge.
                for key, entry in (rec.get("payline_symbol_joint") or {}).items():
                    if isinstance(entry, dict):
                        all_payline_symbol_joint[key]["hits"] += int(entry.get("hits", 0))
                        all_payline_symbol_joint[key]["win"] += float(entry.get("win", 0.0))
                for curve in rec.get("session_rtp_curves") or []:
                    if isinstance(curve, list):
                        all_session_rtp_curves.append(curve)
                for seq in rec.get("chain_ratio_sequences") or []:
                    if isinstance(seq, list):
                        all_chain_ratio_sequences.append(seq)
                for pos, cnt in (rec.get("reel_position_hits") or {}).items():
                    all_reel_position_hits[str(pos)] += int(cnt)
                for feat, fb in (rec.get("chains_by_feature") or {}).items():
                    if not isinstance(fb, dict):
                        continue
                    afb = all_chains_by_feature[str(feat)]
                    for L in fb.get("lengths") or []:
                        afb["lengths"].append(int(L))
                    for L in fb.get("max_ratios") or []:
                        afb["max_ratios"].append(int(L))
                    for L in fb.get("retrigger_events") or []:
                        afb["retrigger_events"].append(int(L))
                    afb["total_rounds"] += int(fb.get("total_rounds", 0) or 0)
                    afb["retrigger_rounds"] += int(fb.get("retrigger_rounds", 0) or 0)

                # Session-level totals (session refactor commit). Older chunk
                # records (pre-feature) silently add 0 via .get() fallback.
                total_paid_sessions += int(rec.get("paid_session_count", 0) or 0)
                total_bonus_spins += int(rec.get("bonus_spin_count", 0) or 0)
                total_session_wins += int(rec.get("session_win_count", 0) or 0)
                total_session_loses += int(rec.get("session_lose_count", 0) or 0)
                total_session_profits += int(rec.get("session_profit_count", 0) or 0)
                total_session_breakevens += int(rec.get("session_breakeven_count", 0) or 0)
                total_session_big_win_x10 += int(rec.get("session_big_win_x10_count", 0) or 0)
                total_session_big_win_x20 += int(rec.get("session_big_win_x20_count", 0) or 0)
                total_session_big_win_x50 += int(rec.get("session_big_win_x50_count", 0) or 0)
                total_session_big_win_x100 += int(rec.get("session_big_win_x100_count", 0) or 0)
                # Bankruptcy sim histogram merge (elementwise sum of bins +
                # scalar totals per tier). Kept for backward compat with
                # cached chunks pre-dating the cross-chunk fix; finalize
                # prefers the streaming accumulator below when it has data.
                for _mk, _entry in (rec.get("bankruptcy_sim") or {}).items():
                    if not isinstance(_entry, dict):
                        continue
                    _m = int(_mk)
                    if _m not in bankruptcy_sim_totals:
                        bankruptcy_sim_totals[_m] = _empty_bankruptcy_tier()
                    _dst = bankruptcy_sim_totals[_m]
                    _dst["bankrupt"] += int(_entry.get("bankrupt", 0) or 0)
                    _dst["survived"] += int(_entry.get("survived", 0) or 0)
                    _sd = _entry.get("spins_done")
                    if isinstance(_sd, list) and _sd:
                        # Extend the unsorted combined list; finalize
                        # sorts once. O(N) append across chunks.
                        _dst["spins_done"].extend(int(v) for v in _sd)
                # Cross-chunk streaming accumulator: feed raw reps so
                # chunks below session_spins (virtual sampling 8k vs
                # session=10k) still contribute. Old chunk records lack
                # the field — feed_reps no-ops on missing data.
                _bk_reps = rec.get("bankruptcy_reps")
                if isinstance(_bk_reps, list) and _bk_reps:
                    bankruptcy_stream_acc.feed_reps(
                        [(int(t[0]), int(t[1])) for t in _bk_reps if isinstance(t, (list, tuple)) and len(t) >= 2]
                    )
                total_session_ret_count += int(rec.get("session_ret_count", 0) or 0)
                total_session_ret_sum += float(rec.get("session_ret_sum", 0.0) or 0.0)
                total_session_ret_sq_sum += float(rec.get("session_ret_sq_sum", 0.0) or 0.0)
                chunk_sess_max_ret = float(rec.get("session_max_return_x", 0.0) or 0.0)
                if chunk_sess_max_ret > total_session_max_return_x:
                    total_session_max_return_x = chunk_sess_max_ret
                total_session_win_sum += float(rec.get("session_win_sum", 0.0) or 0.0)
                for b, c in (rec.get("session_bucket_spins") or {}).items():
                    session_bucket_spins[str(b)] += int(c)
                for b, v in (rec.get("session_bucket_bet") or {}).items():
                    session_bucket_bet[str(b)] += float(v)
                for b, v in (rec.get("session_bucket_win") or {}).items():
                    session_bucket_win[str(b)] += float(v)
                for k, c in (rec.get("session_loss_streak_hist") or {}).items():
                    session_loss_streak_hist[int(k)] += int(c)
                for k, c in (rec.get("session_win_streak_hist") or {}).items():
                    session_win_streak_hist[int(k)] += int(c)
                chunk_sess_max_loss = int(rec.get("session_max_loss_streak", 0) or 0)
                if chunk_sess_max_loss > total_session_max_loss_streak:
                    total_session_max_loss_streak = chunk_sess_max_loss
                chunk_sess_max_win = int(rec.get("session_max_win_streak", 0) or 0)
                if chunk_sess_max_win > total_session_max_win_streak:
                    total_session_max_win_streak = chunk_sess_max_win
                # Extra-field discovery merge.
                for fld, cnt in (rec.get("extra_fields_seen") or {}).items():
                    total_extra_fields_seen[str(fld)] += int(cnt)
                # Per-machine mechanic merge.
                total_lock_lines_spins += int(rec.get("lock_lines_spins", 0) or 0)
                total_lock_lines_total_lines += int(rec.get("lock_lines_total_lines", 0) or 0)
                total_lock_lines_win += float(rec.get("lock_lines_win", 0) or 0)
                total_lock_symbols_spins += int(rec.get("lock_symbols_spins", 0) or 0)
                for s in rec.get("lock_symbols_unique") or []:
                    total_lock_symbols_unique.add(str(s))
                total_lock_symbols_win += float(rec.get("lock_symbols_win", 0) or 0)
                total_lock_reels_spins += int(rec.get("lock_reels_spins", 0) or 0)
                total_lock_reels_win += float(rec.get("lock_reels_win", 0) or 0)
                total_jackpot_spins += int(rec.get("jackpot_spins", 0) or 0)
                for j in rec.get("jackpot_ids_seen") or []:
                    total_jackpot_ids_seen.add(str(j))
                total_jackpot_win += float(rec.get("jackpot_win", 0) or 0)
                total_freespin_chain_spins += int(rec.get("freespin_chain_spins", 0) or 0)
                total_freespin_retriggers += int(rec.get("freespin_retriggers", 0) or 0)
                fsmc = int(rec.get("freespin_max_chain", 0) or 0)
                if fsmc > total_freespin_max_chain:
                    total_freespin_max_chain = fsmc
                total_freespin_win += float(rec.get("freespin_win", 0) or 0)
                total_dollar_pick_spins += int(rec.get("dollar_pick_spins", 0) or 0)
                total_dollar_pick_total_dollars += int(rec.get("dollar_pick_total_dollars", 0) or 0)
                total_dollar_pick_win += float(rec.get("dollar_pick_win", 0) or 0)
                # EC-4 consumer (critique_commitC1 finding #2): collect
                # _plugin_partial_attribution_errors from each chunk dict.
                # Mirrors the from-cache path consumer above.
                _ol_chunk_plugin_errs = rec.get("_plugin_partial_attribution_errors")
                if isinstance(_ol_chunk_plugin_errs, list) and _ol_chunk_plugin_errs:
                    for _ol_cpe in _ol_chunk_plugin_errs:
                        _play_type_plugin_errors_total.append(
                            dict(_ol_cpe, chunk_index=rec.get("index", "?"))
                        )
                # Phase C1: wire extract() per chunk (online/live-sampling path).
                # Mirrors the from-cache path wiring above. Same lazy-import pattern.
                try:
                    try:
                        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES as _ol_features
                        from fresh_slotlab.analyzer.parse_state import ParseState as _ol_ParseState
                    except ImportError:
                        from analyzer.feature_registry import ALL_FEATURES as _ol_features  # type: ignore[no-redef]
                        from analyzer.parse_state import ParseState as _ol_ParseState  # type: ignore[no-redef]
                    _ol_parse_state = _ol_ParseState(
                        chunk_dict=rec,
                        machine_id=args.machine,
                        mode=args.rtp_mode,
                        manifest={},  # manifest not yet loaded; plugins don't use it in extract()
                    )
                    for _ol_feat in _ol_features:
                        try:
                            _ol_this = _ol_feat.extract(_ol_parse_state, rec)
                            _feature_accs[_ol_feat.FEATURE_ID] = _ol_feat.reduce(
                                _feature_accs.get(_ol_feat.FEATURE_ID, {}),
                                _ol_this,
                            )
                        except Exception as _ol_exc:  # noqa: BLE001
                            # Phase C2: persist diagnostic per feedback_no_silent_swallow.md.
                            import sys as _ol_sys
                            print(
                                f"WARNING: feature '{_ol_feat.FEATURE_ID}' "
                                f"extract()/reduce() failed on chunk "
                                f"{rec.get('index', '?')}: {_ol_exc}",
                                file=_ol_sys.stderr,
                            )
                            _feature_accs.setdefault(
                                f"_extract_error_{_ol_feat.FEATURE_ID}", []
                            ).append(str(_ol_exc))
                except Exception:  # noqa: BLE001
                    pass

                hw = ci_halfwidth_pp(chunk_rtps_pct)
                if math.isfinite(hw):
                    achieved_halfwidth_pp = hw

                current_rtp_pct = (total_win / total_bet) * 100.0 if total_bet > 0 else 0.0
                # Session-level RTP mirrors the final summary's rtp.point_pct
                # (total_win / session_bet_sum). On collect-mechanic machines
                # diverges from spin-level current_rtp_pct by 30-50%; UI
                # prefers this value (see pure.js formatChunkEventText).
                session_bet_sum_live = sum(session_bucket_bet.values())
                session_rtp_pct = (
                    (total_session_win_sum / session_bet_sum_live) * 100.0
                    if session_bet_sum_live > 0 else None
                )
                # Session-level CI: authoritative, matches the final-report
                # computation. Progress events now expose this so the UI's
                # CI gauge reflects the value the stop condition compares.
                session_ci_now = session_halfwidth_pp(
                    total_session_ret_count,
                    total_session_ret_sum,
                    total_session_ret_sq_sum,
                )
                append_jsonl(
                    progress_file,
                    {
                        "event": "chunk_progress",
                        "run_id": run_id,
                        # Actual submitted index (pairs with chunk_started
                        # for the UI's in-flight section). Previously this
                        # carried the running `chunks` counter which could
                        # be lower than the true index on resume runs.
                        "chunk_index": int(rec["index"]),
                        "chunks_completed": chunks,
                        "total_spins": total_spins,
                        "current_rtp_pct": current_rtp_pct,
                        "session_rtp_pct": session_rtp_pct,
                        "current_halfwidth_pp": (
                            session_ci_now if session_ci_now is not None else achieved_halfwidth_pp
                        ),
                        "chunk_level_halfwidth_pp": achieved_halfwidth_pp,
                        "session_level_halfwidth_pp": session_ci_now,
                        "target_halfwidth_pp": args.target_halfwidth_pp,
                        "elapsed_seconds": round(time.time() - t0, 3),
                        "ts": utc_now(),
                    },
                )

        # Batch-end bail check. Emissions already fired inline above —
        # this block only counts for the sustained-failure threshold.
        successful_results = [r for r in batch_results if bool(r.get("ok"))]
        failed_results = [r for r in batch_results if not bool(r.get("ok"))]
        batch_fully_failed = bool(failed_results) and not successful_results
        # Classify the batch's failure profile so AIMD only kicks in for
        # network-class trouble. Machine-class failures (schema_drift,
        # parse_failed_*, 4xx) won't be helped by halving conc + sleeping
        # — bail-fast via the _MACHINE counter is the right response.
        batch_failure_classes = [
            _classify_failure(r.get("error", "")) for r in failed_results
        ]
        batch_has_network_failure = any(c == "network" for c in batch_failure_classes)
        batch_fully_network_failed = (
            batch_fully_failed and batch_has_network_failure
        )
        if batch_fully_network_failed:
            # Entire batch failed AND at least one was network-class →
            # treat as a network-stress event. N consecutive ones in a
            # row signals sustained upstream breakage and we bail.
            consecutive_failed_batches_net += 1
        else:
            consecutive_failed_batches_net = 0

        # AIMD: halve concurrency + chunk_spins on a NETWORK-fully-failed
        # batch, grow back on success. Doesn't fire on machine-class-only
        # fully-failed batches (halving wouldn't help). Runs BEFORE the
        # bail threshold check so `adaptive_tune` always emits even on
        # the batch that trips bail (useful for post-mortem).
        aimd_should_halve = batch_fully_network_failed
        new_conc, new_spins, new_streak, should_pause = aimd_tune(
            current_concurrency,
            current_chunk_spins,
            args.batch_concurrency,
            args.chunk_spin_times,
            aimd_should_halve,
            consecutive_successful_batches,
        )
        if (new_conc, new_spins) != (current_concurrency, current_chunk_spins):
            append_jsonl(
                progress_file,
                {
                    "event": "adaptive_tune",
                    "run_id": run_id,
                    "from_concurrency": current_concurrency,
                    "to_concurrency": new_conc,
                    "from_chunk_spins": current_chunk_spins,
                    "to_chunk_spins": new_spins,
                    "direction": "down" if aimd_should_halve else "up",
                    "reason": (
                        "fully_failed_batch" if aimd_should_halve
                        else "success_streak"
                    ),
                    "ts": utc_now(),
                },
            )
        current_concurrency = new_conc
        current_chunk_spins = new_spins
        consecutive_successful_batches = new_streak
        if should_pause:
            last_batch_pause_until = time.time() + CIRCUIT_PAUSE_S

        # Bail check — three independent triggers, each with its own
        # stop_reason prefix so the operator + post-mortem tools can
        # see WHICH side of the network/machine split caused the
        # bailout:
        #   - upstream_unstable:network_consecutive_batches
        #   - upstream_unstable:network_cumulative_chunks
        #   - machine_bug:cumulative_machine_failures
        if cumulative_failed_chunks_machine >= MAX_CUMULATIVE_FAILED_CHUNKS_MACHINE:
            machine_errors = [
                r.get("error", "") for r in batch_results
                if not r.get("ok")
                and _classify_failure(r.get("error", "")) == "machine"
            ]
            stop_reason = (
                f"machine_bug:"
                f"cumulative_machine_failures={cumulative_failed_chunks_machine},"
                f"last_error={machine_errors[0] if machine_errors else '?'}"
            )
            append_jsonl(
                progress_file,
                {
                    "event": "failed",
                    "run_id": run_id,
                    "reason": stop_reason,
                    "chunks": chunks,
                    "total_spins": total_spins,
                    "elapsed_seconds": round(time.time() - t0, 3),
                    "ts": utc_now(),
                },
            )
            break
        if (
            consecutive_failed_batches_net >= MAX_CONSECUTIVE_FAILED_BATCHES_NET
            or cumulative_failed_chunks_net >= MAX_CUMULATIVE_FAILED_CHUNKS_NET
        ):
            last_err = failed_results[0] if failed_results else {}
            stop_reason = (
                f"upstream_unstable:"
                f"network_consecutive_batches={consecutive_failed_batches_net},"
                f"network_cumulative_chunks={cumulative_failed_chunks_net},"
                f"last_error={last_err.get('error', '?')}"
            )
            append_jsonl(
                progress_file,
                {
                    "event": "failed",
                    "run_id": run_id,
                    "reason": stop_reason,
                    "chunks": chunks,
                    "total_spins": total_spins,
                    "elapsed_seconds": round(time.time() - t0, 3),
                    "ts": utc_now(),
                },
            )
            break

        # Stop when session-level CI meets the target. Previously this
        # check used chunk-level CI which collapses to ~0 after 2-3
        # chunks that happen to share similar RTPs, causing premature
        # "target_ci_reached" on high-variance machines (e.g. M273 m1
        # completed at 12.9pp session-CI after reporting 0.3pp chunk-CI).
        # We require session-level CI ≤ target AND a minimum-chunk
        # guard so a pathological single-chunk variance doesn't exit.
        session_ci_final = session_halfwidth_pp(
            total_session_ret_count,
            total_session_ret_sum,
            total_session_ret_sq_sum,
        )
        if (
            chunks >= 2
            and session_ci_final is not None
            and session_ci_final <= args.target_halfwidth_pp
        ):
            stop_reason = "target_ci_reached"
            break

        # ── Non-convergence early-abort (2026-04-21, user request) ──
        # Bail bug / in-dev machines whose data can't converge to
        # target rather than burning the full max_chunks budget. Tier
        # 1 (parse failure rate / consecutive chunk_failed) is covered
        # by the upstream_unstable branch above; this block is Tier 2
        # (RTP out-of-band + projection overrun). Skipped for fuzzy
        # (target == 0) and sentinel (target ≥ 999 — backend rewrites
        # fuzzy to 999 to bypass the CI gate).
        if (
            not args.disable_non_convergence_abort
            and 0.0 < args.target_halfwidth_pp < 999.0
            and chunks >= NON_CONVERGENCE_ABORT_MIN_CHUNKS
        ):
            # Tier 2a: paid-mode RTP out of sane band (mode 1 only).
            # Bonus modes legitimately hit 500%+ so we skip them.
            if args.rtp_mode == 1:
                session_bet_sum_now = sum(session_bucket_bet.values())
                running_rtp_pct = (
                    (total_session_win_sum / session_bet_sum_now) * 100.0
                    if session_bet_sum_now > 0 else None
                )
                if running_rtp_pct is not None:
                    lo, hi = NON_CONVERGENCE_RTP_BAND_PAID
                    if running_rtp_pct < lo or running_rtp_pct > hi:
                        rtp_out_of_band_consecutive += 1
                    else:
                        rtp_out_of_band_consecutive = 0
                    if rtp_out_of_band_consecutive >= NON_CONVERGENCE_RTP_OUT_OF_BAND_CONSECUTIVE:
                        append_jsonl(
                            progress_file,
                            {
                                "event": "non_convergence_abort",
                                "run_id": run_id,
                                "reason": "rtp_out_of_band",
                                "rtp_pct": round(running_rtp_pct, 3),
                                "band_lo_pct": lo,
                                "band_hi_pct": hi,
                                "consecutive": rtp_out_of_band_consecutive,
                                "chunks": chunks,
                                "total_spins": total_spins,
                                "mode": args.rtp_mode,
                                "ts": utc_now(),
                            },
                        )
                        stop_reason = "non_convergence_abort:rtp_out_of_band"
                        break

            # Tier 2b: projected budget exceeded. CI shrinks as
            # 1/√N, so predicted_total = N × (ci_now / target_ci)²
            # chunks. If that's more than (max_chunks × multiplier),
            # this machine won't converge in any reasonable budget.
            if session_ci_final is not None and session_ci_final > args.target_halfwidth_pp:
                ratio = session_ci_final / args.target_halfwidth_pp
                projected_chunks = chunks * (ratio * ratio)
                budget_ceiling = args.max_chunks * NON_CONVERGENCE_BUDGET_MULTIPLIER
                if projected_chunks > budget_ceiling:
                    append_jsonl(
                        progress_file,
                        {
                            "event": "non_convergence_abort",
                            "run_id": run_id,
                            "reason": "projected_budget_exceeded",
                            "projected_chunks": int(projected_chunks),
                            "budget_ceiling": int(budget_ceiling),
                            "current_ci_pp": round(session_ci_final, 3),
                            "target_ci_pp": args.target_halfwidth_pp,
                            "chunks": chunks,
                            "total_spins": total_spins,
                            "ts": utc_now(),
                        },
                    )
                    stop_reason = "non_convergence_abort:projected_budget_exceeded"
                    break

    duration_seconds = round(time.time() - t0, 3)
    finished_at = utc_now()

    # Session-level aggregates that downstream RTP/bucket/volatility
    # math depends on; computed up-front so later blocks can reference
    # them without re-summing.
    session_bet_sum = sum(float(v) for v in session_bucket_bet.values()) or total_bet
    session_win_sum_agg = sum(float(v) for v in session_bucket_win.values()) or total_win

    # RTP denominator is paid-session bet only (the old total_bet also
    # added BetAmount for bonus / free spins, which the player doesn't
    # actually pay -- the combined figure under-reports true RTP on
    # bonus-heavy machines like M272 mode 2). Falls back to total_bet
    # if the run had no paid sessions (shouldn't happen post-refactor,
    # but stays safe for legacy chunk records).
    effective_bet_for_rtp = session_bet_sum if total_paid_sessions > 0 else total_bet
    # RTP numerator: prefer analysisResult.TotalWin (server-side canonical
    # per-chunk total) when it disagrees with our round-walk sum by more
    # than 1%. Per-round WinCredits can double-count on machines that
    # emit BOTH a summary round AND its detail sub-rounds for the same
    # payout (M112: ST 98 FinalMinigame = summary of 5× ST 97 WheelSpin,
    # both carrying the same 4.9M win → analyzer sums both → 2× the
    # true FinalMinigame contribution). server_total_win has no such
    # duplication; pick it as the authoritative numerator and log the
    # override for operator visibility.
    rtp_numerator_source = "our_total_win"
    rtp_numerator = total_win
    if upstream_robots_seen > 0 and upstream_total_win > 0:
        _delta = abs(upstream_total_win - total_win)
        _tol = max(1.0, total_win * 0.01)
        if _delta > _tol:
            rtp_numerator = upstream_total_win
            rtp_numerator_source = "server_total_win_override"
    rtp_point_pct = (
        (rtp_numerator / effective_bet_for_rtp) * 100.0
        if effective_bet_for_rtp > 0 else 0.0
    )

    # Session-level CI on RTP: t × SE of per-session ret_x mean, in pp.
    # Works on single-chunk runs (dev `--from-cache`) where chunk-level
    # CI is undefined (needs N ≥ 2 chunks). N here is session count —
    # typically 10k+, so CI is both valid and tighter than chunk-level.
    # Keeps chunk-level value as diagnostic fallback.
    chunk_level_halfwidth_pp = achieved_halfwidth_pp
    # Delegates to the shared session_halfwidth_pp helper so the final
    # report and the in-loop stop check use identical math. See helper
    # docstring for the N≤1 / zero-variance edge cases.
    session_level_halfwidth_pp = session_halfwidth_pp(
        total_session_ret_count,
        total_session_ret_sum,
        total_session_ret_sq_sum,
    )
    if session_level_halfwidth_pp is not None:
        achieved_halfwidth_pp = session_level_halfwidth_pp

    ci_interval = None
    if achieved_halfwidth_pp is not None:
        ci_interval = [rtp_point_pct - achieved_halfwidth_pp, rtp_point_pct + achieved_halfwidth_pp]

    # --- Session-level derived metrics (player-perspective view). A
    #     "paid session" is a paid spin + any bonus spins it triggered;
    #     hit_rate / RTP bucket / streaks are all based on these so
    #     bonus chains don't dilute the player experience signal. ---
    effective_session_count = total_paid_sessions if total_paid_sessions > 0 else total_spins
    avg_return_x = (
        (total_session_ret_sum / total_session_ret_count)
        if total_session_ret_count > 0
        else 0.0
    )
    if total_session_ret_count > 1:
        variance = (
            total_session_ret_sq_sum
            - (total_session_ret_sum * total_session_ret_sum / total_session_ret_count)
        ) / (total_session_ret_count - 1)
        std_return_x = math.sqrt(max(variance, 0.0))
    else:
        std_return_x = 0.0
    # Prefer session-level peak when we have paid sessions; otherwise
    # keep the spin-level max_observed_return_x already aggregated above
    # (variable carries the sum from rec["max_return_x"] across chunks).
    if total_paid_sessions > 0:
        max_observed_return_x = total_session_max_return_x

    hit_rate = (
        (total_session_wins / effective_session_count) if effective_session_count > 0 else 0.0
    )
    zero_win_rate = (
        (total_session_loses / effective_session_count) if effective_session_count > 0 else 0.0
    )
    profit_spin_rate = (
        (total_session_profits / effective_session_count) if effective_session_count > 0 else 0.0
    )
    breakeven_or_more_rate = (
        (total_session_breakevens / effective_session_count) if effective_session_count > 0 else 0.0
    )
    big_win_x10_rate = (
        (total_session_big_win_x10 / effective_session_count) if effective_session_count > 0 else 0.0
    )
    # Higher-tail paid-round rates. Share the same denominator as x10
    # (paid-round count) so all four numbers align on the same scale —
    # the UI renders them as a 2×2 tile grid mirroring the tail-dep
    # breakdown. Each threshold is strictly nested (x100 ⊂ x50 ⊂ x20
    # ⊂ x10) so rates monotonically decrease across the grid.
    big_win_x20_rate = (
        (total_session_big_win_x20 / effective_session_count) if effective_session_count > 0 else 0.0
    )
    big_win_x50_rate = (
        (total_session_big_win_x50 / effective_session_count) if effective_session_count > 0 else 0.0
    )
    big_win_x100_rate = (
        (total_session_big_win_x100 / effective_session_count) if effective_session_count > 0 else 0.0
    )
    avg_win_when_hit_x = (
        (total_session_win_sum / total_session_wins) / args.bet
        if total_session_wins > 0 and args.bet > 0
        else 0.0
    )

    # Multiplier bucket rows: session-level. Falls back to spin-level
    # aggregates if session data is unavailable (e.g. empty chunk that
    # somehow passed the zero-spin guard), so the summary never looks
    # broken.
    if total_paid_sessions > 0:
        mb_bucket_spins = session_bucket_spins
        mb_bucket_bet = session_bucket_bet
        mb_bucket_win = session_bucket_win
        mb_total_spins = total_paid_sessions
        mb_total_bet = session_bet_sum
        mb_total_win = session_win_sum_agg
    else:
        mb_bucket_spins = multiplier_bucket_spins
        mb_bucket_bet = multiplier_bucket_bet
        mb_bucket_win = multiplier_bucket_win
        mb_total_spins = total_spins
        mb_total_bet = total_bet
        mb_total_win = total_win
    multiplier_bucket_rows = build_multiplier_bucket_rows(
        bucket_spins=mb_bucket_spins,
        bucket_bet=mb_bucket_bet,
        bucket_win=mb_bucket_win,
        total_spins=mb_total_spins,
        total_bet=mb_total_bet,
        total_win=mb_total_win,
    )
    tail_spins_ge10 = sum(mb_bucket_spins.get(k, 0) for k in TAIL_GEX10_BUCKETS)
    tail_win_ge10 = sum(mb_bucket_win.get(k, 0.0) for k in TAIL_GEX10_BUCKETS)
    tail_win_ge20 = sum(mb_bucket_win.get(k, 0.0) for k in TAIL_GEX20_BUCKETS)
    tail_win_ge50 = sum(mb_bucket_win.get(k, 0.0) for k in TAIL_GEX50_BUCKETS)
    tail_win_ge100 = sum(mb_bucket_win.get(k, 0.0) for k in TAIL_GEX100_BUCKETS)

    payline_rows = []
    for lid, hits in sorted(payline_hits.items(), key=lambda kv: kv[1], reverse=True):
        # Top winning symbols for this payline. RLN (RewardLastNode)
        # is upstream-authoritative -- when we captured codes for this
        # payline, use them; otherwise fall back to the left-3-col
        # intersection heuristic. top_symbols_source tells the UI which
        # path fired so the display can optionally badge it.
        rln_counts = payline_winning_symbols_rln.get(lid, {})
        if rln_counts:
            top_syms = sorted(rln_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
            top_symbols_source = "rln"
        else:
            sym_counts = payline_winning_symbols.get(lid, {})
            top_syms = sorted(sym_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
            top_symbols_source = "heuristic"
        payline_rows.append(
            {
                "payline_id": lid,
                "hit_count": hits,
                "hit_rate": hits / total_spins if total_spins > 0 else 0.0,
                "approx_win_credits": payline_win_approx[lid],
                "approx_rtp_contribution_pp": (
                    (payline_win_approx[lid] / total_bet) * 100.0 if total_bet > 0 else 0.0
                ),
                "top_symbols": [{"symbol": s, "count": c} for s, c in top_syms],
                "top_symbols_source": top_symbols_source,
            }
        )

    # Gap #5 (C5): detect "all PayoutGroupId == 0" condition.
    # When every round has PayoutGroupId=0, it means the machine doesn't use
    # PayoutGroupId for real grouping — it's just the default value.  Showing
    # a single "{group_id: 0, hit_count: 89090, rtp_pp: 80.13}" row is noise,
    # not signal.  If the only key in payout_group_hits is 0, filter the list
    # to empty and set payout_groups_status to "all_zeros_filtered".
    # Per feedback_invariant_with_fallback_hides_drift.md: the status flag is
    # an explicit operator-readable signal, not a silent bucket.
    _payout_group_keys_nonzero = set(k for k in payout_group_hits if int(k) != 0)
    payout_groups_status: str
    if not payout_group_hits:
        payout_groups_status = "absent_field"
    elif not _payout_group_keys_nonzero:
        # All rounds have PayoutGroupId == 0 — noise, not signal.
        payout_groups_status = "all_zeros_filtered"
    else:
        payout_groups_status = "populated"

    payout_group_rows: list[dict[str, Any]] = []
    if payout_groups_status == "populated":
        for gid, hits in sorted(payout_group_hits.items(), key=lambda kv: kv[1], reverse=True):
            wins = float(payout_group_win.get(gid, 0.0))
            win_spins_in_group = hits if gid != 0 else 0
            payout_group_rows.append(
                {
                    "group_id": int(gid),
                    "hit_count": int(hits),
                    "hit_rate": (hits / total_spins) if total_spins > 0 else 0.0,
                    "total_win": wins,
                    "avg_win_when_hit_x": (
                        (wins / win_spins_in_group) / args.bet
                        if win_spins_in_group > 0 and args.bet > 0
                        else 0.0
                    ),
                    "rtp_contribution_pp": (
                        (wins / total_bet) * 100.0 if total_bet > 0 else 0.0
                    ),
                }
            )
    # payout_groups_status is written into summary["player_impact"] below
    # alongside payout_groups_top20.

    # SpinType breakdown: per-type spins / bet / win + share of total.
    # Order by spins desc so the dominant type lands first; for collect
    # mechanics this immediately surfaces "X% of rounds are bonus".
    #
    # RTP denominator note: older versions summed BetAmount blindly,
    # which makes free-spin types look like rtp_pct=243% (M272 SpinType
    # 126 carries BetAmount=1000 but CostCredits=0 because the player
    # doesn't pay for bonus rounds). We now compute per-type RTP from
    # total_paid_bet (CostCredits>0 only); free-spin types get
    # rtp_pct=None so the UI can render "N/A" instead of a nonsense
    # percentage. Their wins are still attributed to total RTP via
    # rtp_contribution_pp, which uses the overall total_bet denominator.
    #
    # behavior_name is derived from the per-type paid-round count --
    # "paid" when every round cost the player, "free" when none did,
    # "mixed" otherwise -- so machine-specific SpinType semantics stay
    # out of the analyzer (a new machine's types auto-classify).
    spin_type_rows: list[dict[str, Any]] = []
    for st, spins in sorted(spin_type_spins.items(), key=lambda kv: -kv[1]):
        bet_face = float(spin_type_bet.get(st, 0.0))
        bet_paid = float(spin_type_paid_bet.get(st, 0.0))
        win = float(spin_type_win.get(st, 0.0))
        win_rounds = int(spin_type_wins.get(st, 0))
        paid_rounds = int(spin_type_paid_rounds.get(st, 0))
        spins_int = int(spins)
        if paid_rounds == 0:
            behavior = "free"
        elif paid_rounds == spins_int:
            behavior = "paid"
        else:
            behavior = "mixed"
        rtp_pct: float | None = (
            (win / bet_paid) * 100.0 if bet_paid > 0 else None
        )
        spin_type_rows.append(
            {
                "spin_type": int(st),
                "spins": spins_int,
                "share_pct": (spins / total_spins) * 100.0 if total_spins > 0 else 0.0,
                "win_rounds": win_rounds,
                "paid_rounds": paid_rounds,
                "hit_rate": (win_rounds / spins) if spins > 0 else 0.0,
                "total_bet": bet_face,
                "total_paid_bet": bet_paid,
                "total_win": win,
                # rtp_pct is win / paid_bet -- nonsense for all-free
                # types so we emit null (JSON) for those rows.
                "rtp_pct": rtp_pct,
                "rtp_contribution_pp": (win / total_bet) * 100.0 if total_bet > 0 else 0.0,
                "behavior_name": behavior,
                # Flag extremely rare SpinTypes that may not be
                # representative in a small sample (< 5 occurrences).
                "rare": spins_int < 5,
            }
        )
    spin_type_coverage = len(spin_type_spins)

    # PayoutIdToWinAmount-derived drilldown. Sort by total_win desc so the
    # operator immediately sees which payout ids carry the RTP. Unlike
    # payout_groups_top20 (which is informationally empty for M14/M272 mode
    # 1/2 because the field is always 0), this surface actually
    # discriminates between payout sources.
    # Per-SpinType category lookup for the pay_id tag below. Uses the
    # same "paid" / "free" / "mixed" buckets computed above in
    # spin_type_rows so the category column on each pay_id row is
    # directly traceable to the SpinType panel.
    _st_behavior: dict[int, str] = {
        int(row["spin_type"]): row["behavior_name"]
        for row in spin_type_rows
    }

    payout_id_rows: list[dict[str, Any]] = []
    for pid, wins in sorted(payout_id_win.items(), key=lambda kv: kv[1], reverse=True):
        hits = int(payout_id_hits.get(pid, 0))
        wins_f = float(wins)
        # Tag each pay_id with the dominant SpinType that fired it +
        # the spin_type_category ("paid" / "bonus" / "mixed") so the
        # UI can render "this pay_id is fired 92% from paid rounds,
        # 8% from bonus" without a second JOIN across tables.
        st_hits = payout_id_by_spin_type_total.get(str(pid)) or {}
        total_st_hits = sum(int(c) for c in st_hits.values()) if st_hits else 0
        dominant_st: int | None = None
        dominant_share = 0.0
        if total_st_hits > 0:
            # Pick the SpinType with the most pay_id firings for this
            # specific pay_id; ties broken by smallest SpinType.
            dominant_st = max(
                st_hits.items(),
                key=lambda kv: (int(kv[1]), -int(kv[0])),
            )[0]
            dominant_share = float(st_hits[dominant_st]) / total_st_hits
        # Category resolution: if the dominant SpinType is "paid",
        # label "paid"; if "free", label "bonus"; otherwise "mixed".
        # When a pay_id spans multiple SpinTypes with no single
        # category owning ≥80% of firings, force "mixed" so the
        # operator investigates the breakdown.
        category: str | None = None
        if dominant_st is not None:
            st_behavior = _st_behavior.get(int(dominant_st), "mixed")
            if st_behavior == "paid":
                category = "paid" if dominant_share >= 0.8 else "mixed"
            elif st_behavior == "free":
                category = "bonus" if dominant_share >= 0.8 else "mixed"
            else:
                category = "mixed"
        payout_id_rows.append(
            {
                "payout_id": str(pid),
                "hit_count": hits,
                "hit_rate": (hits / total_spins) if total_spins > 0 else 0.0,
                "total_win": wins_f,
                "avg_win_when_hit": (wins_f / hits) if hits > 0 else 0.0,
                # 2026-04-23 (iter 3 denominator unification): use the
                # same paid-only denominator that summary.rtp uses
                # (effective_bet_for_rtp = session_bet_sum). Before
                # this, payout rows used total_bet which included
                # BetAmount on bonus rounds where the player doesn't
                # actually pay, so sum(payout_ids_top20.rtp_pp)
                # lagged summary.rtp by the ratio (paid / total)
                # (e.g. M15: 200M / 208.84M = 95.77%). Now the sum
                # converges on summary.rtp at fleet level.
                "rtp_contribution_pp": (
                    (wins_f / effective_bet_for_rtp) * 100.0
                    if effective_bet_for_rtp > 0 else 0.0
                ),
                # New (2026-04-20 round 2): attribution to SpinType.
                # ``spin_type_category`` ∈ {"paid", "bonus", "mixed"};
                # ``dominant_spin_type`` is the int that dominated
                # this pay_id's firings; ``spin_type_breakdown``
                # lists (spin_type, count) pairs for UI tooltips.
                "spin_type_category": category,
                "dominant_spin_type": int(dominant_st) if dominant_st is not None else None,
                "spin_type_breakdown": [
                    {"spin_type": int(k), "count": int(v)}
                    for k, v in sorted(st_hits.items(), key=lambda kv: -int(kv[1]))
                ],
            }
        )

    # ── SpinType label map (_st_label) was here until Phase 5 ───────────────
    # Phase C2 carved payouts_by_spin_type's construction into its plugin's
    # emit() (PayoutsBySpinType.emit(), which RE-DERIVES _st_label from
    # summary["player_impact"]["spin_type_breakdown"]).  Phase 5 then carved
    # reel_marginal_by_spin_type's build into ITS plugin's emit() — the last
    # remaining consumer of this PIA-local _st_label.  Both plugins now derive
    # the {spin_type → "ST{N}_{behavior_name}"} map locally from the
    # spin_type_breakdown rows F1 wrote into the summary, so the inline map is
    # gone (no consumer left in PIA).  See ReelMarginalBySpinType.emit() and
    # PayoutsBySpinType.emit().

    symbol_rows = []
    for sym, cnt in sorted(symbol_counts.items(), key=lambda kv: kv[1], reverse=True):
        symbol_rows.append(
            {
                "symbol": sym,
                "count": cnt,
                "rate": cnt / total_symbol_slots if total_symbol_slots > 0 else 0.0,
            }
        )

    symbol_by_col_rows = {}
    for ci, cmap in symbol_counts_by_col.items():
        total_col = sum(cmap.values())
        rows = []
        for sym, cnt in sorted(cmap.items(), key=lambda kv: kv[1], reverse=True):
            rows.append(
                {
                    "symbol": sym,
                    "count": cnt,
                    "rate": cnt / total_col if total_col > 0 else 0.0,
                }
            )
        symbol_by_col_rows[str(ci)] = rows

    # Payline-row density (2026-04-24). For each reel, restrict the
    # symbol count to ONLY the rows that paylines actually visit
    # (inferred from observed PayoutByPayline positions — no spec
    # dependency). Single-payline classic slots (M1, M37) will yield
    # row=1 only → payline density reflects what hits the payout line.
    # Multi-payline machines whose paylines cover all 3 rows will
    # yield identical numbers to window density (that's correct: every
    # row is paylineable). V-shape paylines surface per-reel specific
    # row subsets. Fallback: if no wins ever seen (no positions to
    # decode), default to row=1 (mid-row) to keep output populated.
    payline_row_mask_per_col = {
        str(ci): sorted(rows) for ci, rows in payline_rows_per_col.items()
    }
    symbol_by_col_rows_payline = {}
    for ci, _row_map in symbol_counts_by_col_by_row.items():
        _payline_mask = payline_rows_per_col.get(ci) or {1}  # default mid row
        _merged_payline: dict[str, int] = defaultdict(int)
        for _row_idx, _sym_counts in _row_map.items():
            if _row_idx in _payline_mask:
                for _sym, _c in _sym_counts.items():
                    _merged_payline[_sym] += _c
        _total_col_payline = sum(_merged_payline.values())
        _rows_payline = []
        for _sym, _cnt in sorted(_merged_payline.items(), key=lambda kv: kv[1], reverse=True):
            _rows_payline.append(
                {
                    "symbol": _sym,
                    "count": _cnt,
                    "rate": _cnt / _total_col_payline if _total_col_payline > 0 else 0.0,
                }
            )
        symbol_by_col_rows_payline[str(ci)] = _rows_payline

    # ── SpinType-split reel marginal (2026-05-14) ─────────────────────
    # Phase 5 (analyzer honesty/isolation): the reel_marginal_by_spin_type
    # dict-BUILD was carved OUT of this file and INTO the
    # ReelMarginalBySpinType plugin's emit() (Pattern B stash pattern,
    # analogous to upstream_feature_breakdown C5 / multiplier_profile Phase 4).
    # The plugin reads summary["_reel_marginal_by_spin_type_data"] (the RAW
    # per-ST symbol-count accumulator stashed below, after this summary dict is
    # closed), RE-DERIVES the {spin_type → label} map from the
    # spin_type_breakdown rows (exactly as PayoutsBySpinType.emit() already
    # does — F1 wrote spin_type_breakdown above), builds the dict VERBATIM
    # (byte-identical: same sort order / int(count) / prob_pct = (cnt/total)*100),
    # and writes it into summary["player_impact"]["reel_marginal_by_spin_type"]
    # in the Phase D emit loop.  Editing this panel's logic now flips only
    # reel_marginal_by_spin_type's feature_hash, not base_hash.
    # (Aggregate symbols_by_column_top10 stays untouched.)

    # Upstream FeatureWin breakdown. The upstream API groups payouts by
    # a semantic feature name (string: e.g. "Normal", "NormalCollectionSpin",
    # "NewFreespin") -- richer than the round-level SpinType int. For
    # single-feature machines (M14: just "Normal") this block is redundant
    # with payout_ids_top20 so we flag it as non-actionable. For multi-
    # feature machines (M272 mode 1/2) it's the authoritative per-bonus
    # attribution the operator needs to understand where the RTP actually
    # comes from.
    feature_times_total: dict[str, int] = {
        str(feat): sum(int(p.get("times", 0)) for p in payouts.values())
        for feat, payouts in upstream_feature_tally.items()
    }
    feature_win_total: dict[str, float] = {
        str(feat): sum(float(p.get("win", 0) or 0) for p in payouts.values())
        for feat, payouts in upstream_feature_tally.items()
    }
    feature_to_spin_type, spin_type_to_feature, ambiguous_mapped = (
        _infer_feature_spin_type_mapping(
            feature_times_total,
            spin_type_spins,
            spin_type_remarks_sample,
            feature_win_total=feature_win_total,
            spin_type_win=spin_type_win,
        )
    )

    # Compute wild-nudge SpinType set once for the whole chunk-stream.
    # A SpinType counts as wild-nudge when >=90% of its rounds were
    # tagged by ``is_wild_nudge_round`` during chunk parsing (cost=0
    # + ReMarks contains "move"/"nudge"). Used by the BCM heuristic
    # below to exclude high-volume nudge features from candidate
    # selection (Bug 3 fix; defensive backup to bcm_pairings.json
    # regen which uses observed-at-cycle-peak as the primary signal).
    _wild_nudge_st_set: set[int] = set()
    for _st_key, _nudge_n in (spin_type_nudge_round_count or {}).items():
        try:
            _st_int = int(_st_key)
        except (TypeError, ValueError):
            continue
        _st_total = int(spin_type_spins.get(_st_int, 0) or 0)
        if _st_total > 0 and (_nudge_n / _st_total) >= 0.9:
            _wild_nudge_st_set.add(_st_int)

    # Preload BCM pairing (config → heuristic) once. Falls back the
    # "BuffCollectionMap" feature to its cycle-pair when SpinType
    # inference can't bind it (BCM is per-spin background state, not
    # a round-level type — never has its own SpinType count).
    _bcm_bonus_feature, _bcm_bonus_source = _resolve_bonus_feature(
        args.machine, args.rtp_mode,
        upstream_feature_tally, _load_bcm_pairings(),
        feature_to_spin_type=feature_to_spin_type,
        wild_nudge_spin_types=_wild_nudge_st_set,
    )

    # Upstream FeatureWin breakdown -- row-build carved out (Phase 3).
    #
    # Phase 3 carve (07_decision.md section 5 Phase 3-6 + R-11): the ~400-line
    # row-BUILD that used to live here (the sub_streams_by_feature post-processing,
    # the reverse spin_type_prev_counts table, the per-feature upstream_feature_rows
    # assembly loop with its successor/predecessor inference + per-feature
    # multiplier-bucket histograms + per-path splitting, the sort, and the
    # upstream_feature_applicable flag) was moved VERBATIM into the
    # UpstreamFeatureBreakdown plugin's emit().  The plugin re-sources the raw
    # inputs from the _upstream_feature_breakdown_data stash (built below) and
    # produces the byte-identical {applicable, source, features} dict.  This shed
    # PIA bytes -> base_hash shrinks one-time; editing this feature's compute now
    # flips only its feature_hash, not the fleet-wide base.
    #
    # The SHARED helpers _infer_feature_spin_type_mapping / _resolve_bonus_feature
    # / _load_bcm_pairings STAY in PIA (used elsewhere + unit-tested against this
    # module directly; the plugin must not import PIA -- circular law).  PIA
    # pre-computes their RESULTS above (feature_to_spin_type / spin_type_to_feature
    # / ambiguous_mapped at ~3467; _bcm_bonus_feature / _bcm_bonus_source at ~3498)
    # and stashes those results as raw inputs.

    # Bonus-chain dynamics aggregation from ReMarks. On machines
    # without freespin annotations (M14), all the collected lists are
    # empty and the block flags applicable=False. On MapCollection
    # machines (M272) this gives quantiles of chain length, peak ratio,
    # and the energy-ramp curve -- the real window into the "map
    # collection bonus" experience the aggregate RTP can't describe.
    #
    # Phase 2b carve (07_decision.md §5 Phase 2 + R-11): the dict-BUILD that
    # used to live here (the `_quantiles` closure + the `depth_curve` loop + the
    # `bonus_chain_dynamics` dict literal incl. the `by_feature` comprehension)
    # was moved VERBATIM into the BonusChainDynamics plugin's emit().  The plugin
    # re-sources the raw accumulators from the `_bonus_chain_dynamics_data` stash
    # (built below) and produces the byte-identical dict.  This shed PIA bytes →
    # base_hash shrinks one-time; editing the feature's compute now flips only its
    # feature_hash, not the fleet-wide base.

    # Session-level streak quantiles (player perspective: runs of
    # losing / winning paid sessions). Falls back to spin-level if no
    # session data is available so legacy back-compat code paths stay
    # meaningful.
    if total_paid_sessions > 0:
        loss_hist_src = session_loss_streak_hist
        win_hist_src = session_win_streak_hist
        max_loss_final = total_session_max_loss_streak
        max_win_final = total_session_max_win_streak
    else:
        loss_hist_src = loss_streak_hist
        win_hist_src = win_streak_hist
        max_loss_final = max_loss_streak
        max_win_final = max_win_streak
    loss_streak_p50 = quantile_from_hist(loss_hist_src, 0.50)
    loss_streak_p90 = quantile_from_hist(loss_hist_src, 0.90)
    loss_streak_p95 = quantile_from_hist(loss_hist_src, 0.95)
    win_streak_p50 = quantile_from_hist(win_hist_src, 0.50)
    win_streak_p90 = quantile_from_hist(win_hist_src, 0.90)
    win_streak_p95 = quantile_from_hist(win_hist_src, 0.95)

    # Bankruptcy analysis: rawdata-replay simulation. Every chunk
    # contributes to ``bankruptcy_sim_totals`` during the merge loop
    # above (keyed by bankroll multiplier, fine-resolution histogram).
    # Here we derive per-tier decile percentiles + the fastest
    # bankruptcy spin count. Percentiles are evaluated over the FULL
    # session population (bankrupt + survived, denominator = all
    # simulated sessions in the tier); once cumulative mass passes all
    # bankrupt sessions the remaining percentiles pin to session_spins,
    # which matches the "survived" share — so the table transition
    # directly shows when bankruptcy runs out.
    #
    # Rationale for percentile table over bin histograms: at RTP ~90%
    # with session_spins=10000, bankruptcy mass concentrates heavily
    # in the first ~10% of the horizon and any equal-width or
    # equal-mass histogram compresses or stretches the rest poorly.
    # Showing "at each decile, what's the spin count?" gives each row
    # a cleanly interpretable reading: P10 = 10% of simulated users
    # were out by this spin, P50 = median user, P90 = 90% of users
    # died by this spin (the rest are still in).
    bankruptcy_sim_session_spins = args.bankruptcy_session_spins
    # 2026-04-25: prefer the cross-chunk streaming accumulator's result
    # when it received any reps. The per-chunk-merged dict is kept only
    # so cached chunks pre-dating the streaming fix still produce
    # something rather than crashing — but their results are wrong (zero
    # windows for any chunk smaller than session_spins). New chunk
    # records always carry ``bankruptcy_reps`` so this branch will be
    # taken on every fresh sampling / report rebuild.
    if bankruptcy_stream_acc.has_data:
        bankruptcy_sim_totals = bankruptcy_stream_acc.finalize()
    # Phase 6 carve (analyzer unbundle — the LAST carve; see
    # session_artifacts/_impl/phase_extract_6_bankruptcy/brief.md):
    # the tier ROW-BUILD loop moved VERBATIM into the bankruptcy_simulation
    # plugin as build_bankruptcy_rows(). PIA imports it (dual-path) and calls
    # it HERE — the pre-summary row-build site — because bankruptcy_rows feeds
    # the pre-summary x100_br/x200_br/x500_br derivation (split-ownership: the
    # late-running emit() cannot own a build the pre-summary path consumes).
    # The returned rows are byte-identical to the pre-carve inline loop;
    # x100_br etc. and the stash + markdown read-back below are UNCHANGED.
    # Importing the plugin here is safe for the R-1 drift-guard: PIA already
    # imports this registered plugin (for register()), so no new content module
    # enters the closure — the guard still excludes it (R-4). The row-build
    # bytes now live in the plugin → editing them flips ITS feature_hash, not
    # base. Dual-path per memory
    # feedback_subprocess_import_suicide_and_module_globals.md; NEVER the
    # reverse import (the plugin must not import PIA — cycle risk).
    try:
        from fresh_slotlab.analyzer.features.bankruptcy_simulation import (
            build_bankruptcy_rows,
        )
    except ImportError:  # running as standalone script
        from analyzer.features.bankruptcy_simulation import (  # type: ignore[no-redef]
            build_bankruptcy_rows,
        )
    bankruptcy_rows: list[dict[str, Any]] = build_bankruptcy_rows(
        bankruptcy_sim_totals,
        _bankruptcy_mults_tuple,
        args.bet,
        bankruptcy_sim_session_spins,
    )

    ci_met = achieved_halfwidth_pp is not None and achieved_halfwidth_pp <= args.target_halfwidth_pp
    sample_size_met = total_spins >= 2_000_000
    buckets_complete = len(multiplier_bucket_rows) == len(RETURN_BUCKET_ORDER)
    # Rawdata-replay sim always produces rows for every requested tier
    # (the per-chunk loop emits zero-count tiers for degenerate inputs,
    # which still satisfy the "ladder present" signal). Keep the check
    # so the quality_label gate stays structurally identical; it only
    # trips when someone invokes the analyzer with an empty multi list.
    bankruptcy_ladder_met = sum(1 for row in bankruptcy_rows if "error" not in row) >= 3
    quality_label = (
        "REPORT_GRADE"
        if (ci_met and sample_size_met and buckets_complete and bankruptcy_ladder_met)
        else "EXPLORATORY"
    )

    recovery_gap = hit_rate - profit_spin_rate
    # Tail metrics share RTP's paid-bet denominator so the percentage is
    # comparable to rtp_point_pct (same units; the ratio is stable).
    tail_rtp_contribution_pp_ge10x = (
        (tail_win_ge10 / effective_bet_for_rtp) * 100.0 if effective_bet_for_rtp > 0 else 0.0
    )
    tail_rtp_contribution_pp_ge20x = (
        (tail_win_ge20 / effective_bet_for_rtp) * 100.0 if effective_bet_for_rtp > 0 else 0.0
    )
    tail_rtp_contribution_pp_ge50x = (
        (tail_win_ge50 / effective_bet_for_rtp) * 100.0 if effective_bet_for_rtp > 0 else 0.0
    )
    tail_rtp_contribution_pp_ge100x = (
        (tail_win_ge100 / effective_bet_for_rtp) * 100.0 if effective_bet_for_rtp > 0 else 0.0
    )
    tail_win_share_ge10x = tail_win_ge10 / total_win if total_win > 0 else 0.0
    # Multi-threshold tail_dependency: what share of total RTP comes
    # from >=Nx wins. ge10x remains the canonical input to
    # classify_volatility / classify_experience_archetype; ge20x / ge50x
    # / ge100x surface the tail shape (how fast the mass decays as x
    # grows). Boom-Bust machines show a slow decay; grindy machines
    # decay sharply.
    tail_dependency_ge10x = safe_div(tail_rtp_contribution_pp_ge10x, rtp_point_pct)
    tail_dependency_ge20x = safe_div(tail_rtp_contribution_pp_ge20x, rtp_point_pct)
    tail_dependency_ge50x = safe_div(tail_rtp_contribution_pp_ge50x, rtp_point_pct)
    tail_dependency_ge100x = safe_div(tail_rtp_contribution_pp_ge100x, rtp_point_pct)
    # Legacy alias. All call sites that matter (classify_volatility,
    # classify_experience_archetype, alert thresholds) use this name;
    # keep it pointing at the ge10x figure.
    tail_dependency = tail_dependency_ge10x

    volatility_class = classify_volatility(
        zero_win_rate=zero_win_rate,
        loss_streak_p95=loss_streak_p95,
        tail_dependency=tail_dependency,
    )
    experience_archetype = classify_experience_archetype(
        zero_win_rate=zero_win_rate,
        big_win_x10_rate=big_win_x10_rate,
        tail_dependency=tail_dependency,
        profit_spin_rate=profit_spin_rate,
    )

    payline_total_pp = sum(float(row["approx_rtp_contribution_pp"]) for row in payline_rows)
    payline_top1_share = (
        safe_div(float(payline_rows[0]["approx_rtp_contribution_pp"]), payline_total_pp)
        if payline_rows
        else 0.0
    )
    payline_top3_share = (
        safe_div(sum(float(row["approx_rtp_contribution_pp"]) for row in payline_rows[:3]), payline_total_pp)
        if payline_rows
        else 0.0
    )
    payline_top1_concentrated = payline_top1_share > 0.20
    payline_top3_concentrated = payline_top3_share > 0.55

    blank_like_total = sum(cnt for sym, cnt in symbol_counts.items() if blank_like_symbol(sym))
    blank_like_rate = safe_div(float(blank_like_total), float(total_symbol_slots))
    blank_like_rate_by_col: dict[str, float] = {}
    for ci, cmap in symbol_counts_by_col.items():
        total_col = sum(cmap.values())
        blank_col = sum(c for sym, c in cmap.items() if blank_like_symbol(sym))
        blank_like_rate_by_col[str(ci)] = safe_div(float(blank_col), float(total_col))
    if blank_like_rate_by_col:
        blank_like_col_spread = max(blank_like_rate_by_col.values()) - min(blank_like_rate_by_col.values())
    else:
        blank_like_col_spread = 0.0
    symbol_distribution_skew = blank_like_col_spread > 0.05

    bankruptcy_by_mult = {
        int(row["bankroll_multiplier"]): row
        for row in bankruptcy_rows
        if "error" not in row
    }
    x100_br = float(bankruptcy_by_mult.get(100, {}).get("bankruptcy_rate", 0.0))
    x200_br = float(bankruptcy_by_mult.get(200, {}).get("bankruptcy_rate", 0.0))
    x500_br = float(bankruptcy_by_mult.get(500, {}).get("bankruptcy_rate", 0.0))

    alerts: list[dict[str, str]] = []
    if not ci_met:
        alerts.append(
            {
                "code": "A1_CI_NOT_REACHED",
                "severity": "high",
                "message": "CI half-width target not reached.",
            }
        )
    if zero_win_rate > 0.80 and profit_spin_rate < 0.10:
        alerts.append(
            {
                "code": "A2_DRY_AND_LOW_PROFIT",
                "severity": "high",
                "message": "High dead-spin rate with low profit-spin rate.",
            }
        )
    if loss_streak_p95 >= 15:
        alerts.append(
            {
                "code": "A3_LONG_LOSS_STREAK",
                "severity": "medium",
                "message": "Loss streak p95 is high.",
            }
        )
    if tail_dependency >= 0.45:
        alerts.append(
            {
                "code": "A4_HIGH_TAIL_DEPENDENCY",
                "severity": "medium",
                "message": "RTP depends heavily on >=10x tail outcomes.",
            }
        )
    if x200_br >= 0.10:
        alerts.append(
            {
                "code": "A5_X200_BANKRUPTCY_HIGH",
                "severity": "high",
                "message": "x200 bankroll bankruptcy rate is above 10%.",
            }
        )
    if payline_top1_concentrated or payline_top3_concentrated:
        alerts.append(
            {
                "code": "A6_PAYLINE_CONCENTRATION",
                "severity": "medium",
                "message": "Payline RTP contribution is concentrated.",
            }
        )
    if symbol_distribution_skew:
        alerts.append(
            {
                "code": "A7_SYMBOL_SKEW",
                "severity": "medium",
                "message": "Blank-like symbol distribution spread across columns exceeds 5pp.",
            }
        )

    action_recommendations: list[str] = []
    if zero_win_rate > 0.80 or loss_streak_p95 >= 15:
        action_recommendations.append(
            "Increase low return bucket (gt0_lt1) to reduce dry feel."
        )
    if tail_dependency >= 0.45:
        action_recommendations.append(
            "Reduce >=10x tail RTP share slightly and reallocate to ge1_lt5."
        )
    if x200_br >= 0.10:
        action_recommendations.append(
            "Improve session survivability at x200 bankroll by raising mid-tier payout continuity."
        )
    if not action_recommendations:
        action_recommendations.append(
            "Profile is within baseline guardrails; run targeted A/B tests on mid buckets for finer tuning."
        )

    conclusion_data_confidence = (
        f"CI half-width={achieved_halfwidth_pp}, target<={args.target_halfwidth_pp}, spins={total_spins}, quality={quality_label}."
    )
    conclusion_player_feel = (
        f"{experience_archetype} feel with {volatility_class} volatility: zero_win_rate={zero_win_rate:.4f}, loss_streak_p95={loss_streak_p95}."
    )
    conclusion_rtp_structure = (
        f">=10x tail contributes {tail_rtp_contribution_pp_ge10x:.4f}pp RTP (dependency={tail_dependency:.4f})."
    )
    conclusion_session_risk = (
        f"Bankruptcy ladder: x100={x100_br:.4f}, x200={x200_br:.4f}, x500={x500_br:.4f}."
    )
    conclusion_design_action = action_recommendations[0]

    # Capture machine MD5 at report build time for later validity checks.
    # Primary source: whatever the analyzer actually used to FILTER this
    # run's chunks (args.upstream_config_md5 passed by backend). If the
    # backend's ``--upstream-config-md5`` arg was an explicit value —
    # including synthetic ``localcfg_<hash>`` for MachineConfig
    # overrides — the report must be stamped with THAT so the rwtree
    # routes it to its own md5 bucket. Otherwise a local-cfg run's
    # report would inherit machines.json's global md5 (via
    # _lookup_machine_md5) and silently mix with global-cfg reports
    # under the "current" cell.
    if args.upstream_config_md5 or args.upstream_code_md5:
        _summary_config_md5 = args.upstream_config_md5 or ""
        _summary_code_md5 = args.upstream_code_md5 or ""
    else:
        _summary_config_md5, _summary_code_md5 = _lookup_machine_md5(args.machine)
    _summary_analyzer_version = compute_analyzer_version()
    # Phase 3 item 4: per-(machine, mode) effective_analyzer_version
    # composed of base_hash + sorted(feature_hashes_machine_uses) + mode.
    # Lives alongside the legacy analyzer_version. Best-effort: if the
    # manifest is missing or feature registry is empty, falls back to
    # empty string and old run rows show as historical (per memory
    # feedback_md5_is_a_tag_not_a_destruction_signal.md). The legacy
    # analyzer_version field is unchanged; old summaries keep working.
    _summary_effective_analyzer_version = ""
    _effective_version_error: str | None = None
    try:
        # Dual-path import — backend cwd=repo-root resolves the
        # fresh_slotlab.* path; script-mode (cwd=fresh_slotlab/) needs
        # the bare module path. Matches the pattern PIA uses for its
        # trigger_sessions / round_classification / round_win imports
        # at the top of this file.
        try:
            from fresh_slotlab.analyzer.versioning import (
                compute_effective_version_for_machine as _ceavfm,
            )
        except ImportError:
            from analyzer.versioning import (  # type: ignore[no-redef]
                compute_effective_version_for_machine as _ceavfm,
            )
        _summary_effective_analyzer_version = _ceavfm(
            args.machine, mode=args.rtp_mode,
        )
    except Exception as _exc:  # noqa: BLE001 — capture-and-record
        # Per memory feedback_no_silent_swallow.md: empty value in
        # summary signals "not computed"; the diagnostic field below
        # names the exception so an operator can grep. Initially we
        # caught only (FileNotFoundError, KeyError, ImportError,
        # ValueError); broadened to catch all because debugging
        # 2026-05-20 showed the production path was hitting an
        # AttributeError class that escaped the narrow catch. The
        # legacy analyzer_version is still computed above so the
        # report write succeeds for backward compat.
        _effective_version_error = f"{type(_exc).__name__}: {_exc}"
        print(
            f"[pia] effective_analyzer_version not computed for "
            f"{args.machine} mode {args.rtp_mode}: {_effective_version_error}",
            file=sys.stderr,
        )
    summary = {
        "report_id": f"impact_{args.machine}_mode{args.rtp_mode}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "run_id": run_id,
        "machine": args.machine,
        "mode": args.rtp_mode,
        # Server-side machine fingerprint at sampling time (paytable /
        # paylines / code on the server). Staleness means rawdata is
        # from an older server version → must resample.
        "config_md5": _summary_config_md5,
        "code_md5": _summary_code_md5,
        # Local analyzer source fingerprint at report-generation time.
        # Staleness means the report was built with older Python code
        # → safe to regenerate from rawdata (same chunks, new code).
        "analyzer_version": _summary_analyzer_version,
        # Per-(machine, mode) effective hash. Empty when manifest /
        # registry not available; populated 12-hex when both are.
        "effective_analyzer_version": _summary_effective_analyzer_version,
        # Diagnostic — populated only when the orchestrator above hit
        # an exception. None when computation succeeded. Lets operators
        # see WHY the field is empty without grepping stderr.
        "effective_analyzer_version_error": _effective_version_error,
        "output_all_robots_result": True,
        "sampling": {
            "target_halfwidth_pp": args.target_halfwidth_pp,
            "achieved_halfwidth_pp": achieved_halfwidth_pp,
            "chunk_level_halfwidth_pp": chunk_level_halfwidth_pp,
            "session_level_halfwidth_pp": session_level_halfwidth_pp,
            "chunk_spin_times": args.chunk_spin_times,
            "chunk_robot_count": args.chunk_robot_count,
            "batch_concurrency": args.batch_concurrency,
            # Per-spin bet size used during sampling — needed by the UI
            # to render "avg_win / bet = multiplier" in the PayID overview
            # (adding it here saves a /api/runs poke + fallback math).
            "bet": int(args.bet),
            "chunks": chunks,
            "total_spins": total_spins,
            # Paid vs bonus split (session refactor). total_spins is
            # paid_spins + bonus_spins. All derived metrics use
            # paid_spins as the denominator; total_spins is kept for
            # the quality gate ("did we sample enough rounds overall").
            "paid_spins": total_paid_sessions,
            "bonus_spins": total_bonus_spins,
            "stop_reason": stop_reason,
            "duration_seconds": duration_seconds,
            "started_at": started_at,
            "finished_at": finished_at,
        },
        "rtp": {
            "point_pct": rtp_point_pct,
            "ci95_interval_pct": ci_interval,
            # ``numerator_source`` surfaces whether the RTP point_pct
            # was computed from our per-round WinCredits sum
            # ("our_total_win") or was overridden with the server's
            # analysisResult.TotalWin ("server_total_win_override")
            # because the two diverged > 1%. The override kicks in on
            # machines like M112 where the server emits both a
            # FinalMinigame summary round AND its WheelSpin sub-rounds
            # for the same payout — our naive sum would double-count.
            #
            # Caveat: per-SpinType and per-payline contribution fields
            # below still reflect the RAW win aggregation (may sum to
            # more than point_pct on double-counting machines). Use
            # ``upstream_feature_breakdown`` for an authoritative
            # per-feature RTP slice when numerator_source !=
            # "our_total_win".
            "numerator_source": rtp_numerator_source,
            "our_total_win": total_win,
            "server_total_win": upstream_total_win if upstream_robots_seen > 0 else None,
        },
        "storage": {
            "raw_round_data_persisted": False,
            "reason": "Only aggregated metrics are persisted to keep local storage bounded.",
        },
        "player_impact": {
            "volatility": {
                "avg_return_x": avg_return_x,
                "std_return_x": std_return_x,
                "max_observed_return_x": max_observed_return_x,
                "return_bucket_rate": {
                    row["bucket"]: row["spin_rate"]
                    for row in multiplier_bucket_rows
                },
            },
            # Phase 4 (analyzer honesty/isolation): multiplier_profile is now
            # written by the MultiplierProfile plugin's emit() (Pattern B stash
            # pattern, analogous to upstream_feature_breakdown C5 / bonus_chain_dynamics
            # 2b). The inline dict-build was carved OUT of this file into the plugin
            # so editing it flips only multiplier_profile's feature_hash, not
            # base_hash. The plugin reads summary["_multiplier_profile_data"] (the
            # RAW inputs stashed below, after this summary dict is closed), builds
            # the dict VERBATIM (byte-identical), and writes it into
            # summary["player_impact"]["multiplier_profile"] in the Phase D emit loop.
            "hit_and_payout": {
                "win_hit_rate": hit_rate,
                "zero_win_rate": zero_win_rate,
                "profit_spin_rate": profit_spin_rate,
                "breakeven_or_more_rate": breakeven_or_more_rate,
                "big_win_x10_rate": big_win_x10_rate,
                "big_win_x20_rate": big_win_x20_rate,
                "big_win_x50_rate": big_win_x50_rate,
                "big_win_x100_rate": big_win_x100_rate,
                "avg_win_when_hit_x": avg_win_when_hit_x,
                "lack_credit_spin_rate": (lack_credit_spins / total_spins) if total_spins > 0 else 0.0,
            },
            "streaks": {
                # Session-level streaks (consecutive losing/winning paid
                # sessions). Matches hit_rate / zero_win_rate semantics.
                "loss_streak_p50": loss_streak_p50,
                "loss_streak_p90": loss_streak_p90,
                "loss_streak_p95": loss_streak_p95,
                "loss_streak_max": max_loss_final,
                "win_streak_p50": win_streak_p50,
                "win_streak_p90": win_streak_p90,
                "win_streak_p95": win_streak_p95,
                "win_streak_max": max_win_final,
            },
            # 2026-05-12: top-N truncations lifted across the *_top20
            # family. 字段名保留 "_top20" 后向兼容老 report + LLM prompt
            # (它们已经把字段名写死),但实际不再截断。原因同
            # symbols_by_column_top10:对比模式下截断会让排名 >N 的条目
            # 在 A/B 一侧凭空消失,Δ chip + "A only"/"B only" 标签据此
            # 推断出错误的 presence diff。机台 payline / pay_id / symbol
            # 总数一般 ≤ 30,全部下发的开销可忽略。
            "paylines_top20": list(payline_rows),
            "payout_groups_top20": list(payout_group_rows),
            # Gap #5 (C5): explicit status for payout_groups_top20.
            # "populated" — real group IDs; "all_zeros_filtered" — all rounds
            # had PayoutGroupId=0 (noise, list is empty); "absent_field" — no
            # PayoutGroupId field observed at all.
            # Per feedback_invariant_with_fallback_hides_drift.md: explicit
            # named status, not a silent catch-all bucket.
            "payout_groups_status": payout_groups_status,
            "payout_ids_top20": list(payout_id_rows),
            # Phase C2: payouts_by_spin_type is now written by the
            # PayoutsBySpinType plugin's emit() (Pattern B). The key is
            # populated in Phase D (plugin emit loop) after this summary
            # dict is constructed. The plugin writes directly into
            # summary["player_impact"]["payouts_by_spin_type"].
            # Phase 5: reel_marginal_by_spin_type is likewise now written by
            # the ReelMarginalBySpinType plugin's emit() (Pattern B). It is
            # populated in Phase D (plugin emit loop) from the raw stash
            # summary["_reel_marginal_by_spin_type_data"]. Shape unchanged:
            # {spin_type_label → {reel_col → [{symbol, count, prob_pct}]}}
            # where prob_pct sums to 100 per (label, reel). The plugin writes
            # directly into summary["player_impact"]["reel_marginal_by_spin_type"].
            # Existing symbols_by_column_top10 untouched.
            "spin_type_breakdown": spin_type_rows,
            "spin_type_coverage": spin_type_coverage,
            # Extra fields discovered beyond _BASELINE_ROUND_FIELDS.
            "field_discovery": {
                "extra_fields": [
                    {"field": f, "occurrences": c}
                    for f, c in sorted(
                        total_extra_fields_seen.items(),
                        key=lambda kv: -kv[1],
                    )
                ],
                "extra_field_count": len(total_extra_fields_seen),
                "baseline_field_count": len(_BASELINE_ROUND_FIELDS),
            },
            # Per-machine mechanic analysis (machine_mechanics).
            # Phase C4: this key is now written by the MachineMechanics plugin
            # emit() in the Phase D plugin emit loop (after this summary dict
            # is constructed). The plugin uses ctx.mechanism_registry for
            # jackpot + freespin detection (Tier 1/2/3) and the extract()
            # accumulator for quantitative fields.
            # All 253 base manifests declare "machine_mechanics" in
            # analyzer_features so the plugin runs for every machine that
            # previously had the inline block.  The inline block is removed
            # per 04_v3 §7.2 C4 acceptance criterion #10 (grep verifies absence).
            #
            # Phase C5: upstream_feature_breakdown is now written by the
            # UpstreamFeatureBreakdown plugin's emit() (Pattern B stash pattern).
            # The stash key below carries the computed data into the plugin;
            # the plugin writes the final summary["player_impact"][
            # "upstream_feature_breakdown"] key in Phase D.
            # All 253 base manifests declare "upstream_feature_breakdown".
            # The inline block is removed per 04_v3 §7.2 C5 acceptance criterion.
            # R2 Phase 2 C-1: "bonus_chain_dynamics" key REMOVED from this inline
            # dict literal.  The BonusChainDynamics plugin now writes it during
            # the Phase D emit loop (after REQUIRES ordering via C-3 ensures
            # bonus_chain_dynamics runs before machine_mechanics).
            # --- Raw-data analysis surfaces ---
            # Payline × Symbol joint: top 20 (payline, symbol) pairs
            # by win contribution. Answers "which symbol on which line
            # carries the most RTP?"
            "payline_symbol_top20": sorted(
                [
                    {
                        "payline_symbol": k,
                        "payline_id": k.split(":")[0] if ":" in k else k,
                        "symbol": k.split(":")[1] if ":" in k else "?",
                        "hits": int(v["hits"]),
                        "total_win": float(v["win"]),
                        "rtp_contribution_pp": (
                            (float(v["win"]) / effective_bet_for_rtp) * 100.0
                            if effective_bet_for_rtp > 0 else 0.0
                        ),
                    }
                    for k, v in all_payline_symbol_joint.items()
                    if v["hits"] > 0
                ],
                key=lambda x: -x["rtp_contribution_pp"],
            ),  # 2026-05-12: 不再截断,见 paylines_top20 之上的注释
            # Session RTP curve: cumulative RTP per robot at sampled
            # paid-spin indices. Frontend can plot these as spaghetti
            # lines or compute p10/p50/p90 envelope.
            "session_rtp_curves": all_session_rtp_curves[:50],
            # Chain ExtraRatio sequences: per-chain ordered ratio list.
            # Shows how the multiplier escalates within each individual
            # bonus chain (not just the depth-bucket average).
            "chain_ratio_sequences": all_chain_ratio_sequences[:50],
            # Reel position distribution: which PayoutByPayline positions
            # hit most often. Answers "is the win distribution across
            # reel positions uniform?"
            "reel_position_top20": sorted(
                [
                    {"position": pos, "hits": cnt}
                    for pos, cnt in all_reel_position_hits.items()
                ],
                key=lambda x: -x["hits"],
            ),  # 2026-05-12: 不再截断,见 paylines_top20 之上的注释
            "symbols_top20": list(symbol_rows),  # 2026-05-12: 不再截断
            # 2026-05-12: name kept as "top10" for back-compat with old
            # reports + LLM prompt, but truncation removed. Reason: in
            # report-compare mode, when a symbol existed in A's top 10
            # but ranked >10 in B's column, B side rendered "—" and was
            # tagged "A only", even though B's overall data had the
            # symbol (just at lower per-column rank). 单机一共也就十几个
            # 符号,全部下发开销可忽略,但能让按列对比的 presence diff
            # 真实可信。下游 (pure.js / interpret prompt) 只 iterate,
            # 不假设长度。
            "symbols_by_column_top10": {k: list(v) for k, v in symbol_by_col_rows.items()},
            # 2026-04-24: payline-density variant of symbols_by_column_top10.
            # "symbols_by_column_top10" counts all visible window rows (top+mid+bot
            # — what player sees). "_payline" restricts to rows that paylines
            # actually visit per reel (inferred from PayoutByPayline positions,
            # falls back to mid-row if no wins sampled). Multi-payline aware.
            # Frontend shows both columns for comparison: symbols with
            # window% >> payline% are "near-miss amplifiers" (clustered with
            # blanks to tease).
            "symbols_by_column_top10_payline": {k: list(v) for k, v in symbol_by_col_rows_payline.items()},
            "payline_rows_per_col": payline_row_mask_per_col,
            # Wave 2c (P2-C): bankruptcy_simulation + bankruptcy_probe are
            # no longer inlined here. BankruptcySimulation.emit() writes
            # them into summary["player_impact"] after the feature loop
            # (see below). Temp keys _bankruptcy_rows /
            # _bankruptcy_sim_session_spins carry the pre-built data.
        },
        "upstream_analysis": {
            # Server-side analysisResult.TotalWin sum (across all chunk
            # responses that included it). Used as a sanity check
            # against our parsed total_win; persistent drift suggests
            # our aggregator misses a field or mis-counts a SpinType.
            "server_total_win": upstream_total_win,
            "our_total_win": total_win,
            "delta": total_win - upstream_total_win,
            "delta_pct": (
                ((total_win - upstream_total_win) / upstream_total_win) * 100.0
                if upstream_total_win > 0
                else None
            ),
            # Tolerate rounding to 0.5 credit per robot per chunk; below
            # that, treat it as a match. server_robots_seen tells whether
            # ANY response actually carried analysisResult (older
            # machines may not).
            "matches": (
                abs(total_win - upstream_total_win) < max(1.0, upstream_total_win * 1e-6)
                if upstream_robots_seen > 0
                else None
            ),
            "server_robots_seen": upstream_robots_seen,
        },
        # Phase C5: collect_mechanic is now written by the CollectMechanic plugin
        # emit() in the Phase D plugin emit loop (stash pattern, analogous to
        # BankruptcySimulation C1).  The stash key _collect_mechanic_data is
        # written after the summary dict is closed (see post-summary block below).
        # All 253 base manifests declare "collect_mechanic" in analyzer_features.
        # The inline block is removed per 04_v3 §7.2 C5 acceptance criterion.
        "guideline_assessment": {
            "guideline": "classic_slots_report_guideline_v1",
            "data_quality": {
                "quality_label": quality_label,
                "ci_met": ci_met,
                "sample_size_met": sample_size_met,
                "buckets_complete": buckets_complete,
                "bankruptcy_ladder_met": bankruptcy_ladder_met,
            },
            "derived_metrics": {
                "recovery_gap": recovery_gap,
                # Canonical tail_dependency (ge10x) preserved so
                # classify_volatility / classify_experience_archetype
                # and alert thresholds keep reading the same name.
                "tail_dependency": tail_dependency,
                # Four-point breakdown: how RTP dependency on the
                # >=Nx tail evolves as the threshold rises. Small
                # drop from ge10x to ge20x means most tail value
                # lives in modest 10-20x wins; large drop means
                # the tail concentrates in deep 50x+ hits.
                "tail_dependency_ge10x": tail_dependency_ge10x,
                "tail_dependency_ge20x": tail_dependency_ge20x,
                "tail_dependency_ge50x": tail_dependency_ge50x,
                "tail_dependency_ge100x": tail_dependency_ge100x,
                "tail_rtp_contribution_pp_ge10x": tail_rtp_contribution_pp_ge10x,
                "tail_rtp_contribution_pp_ge20x": tail_rtp_contribution_pp_ge20x,
                "tail_rtp_contribution_pp_ge50x": tail_rtp_contribution_pp_ge50x,
                "tail_rtp_contribution_pp_ge100x": tail_rtp_contribution_pp_ge100x,
            },
            "classification": {
                "volatility_class": volatility_class,
                "experience_archetype": experience_archetype,
            },
            "concentration_checks": {
                "payline_top1_share": payline_top1_share,
                "payline_top3_share": payline_top3_share,
                "payline_top1_concentrated": payline_top1_concentrated,
                "payline_top3_concentrated": payline_top3_concentrated,
            },
            "symbol_checks": {
                "blank_like_rate": blank_like_rate,
                "blank_like_rate_by_column": blank_like_rate_by_col,
                "blank_like_col_spread": blank_like_col_spread,
                "symbol_distribution_skew": symbol_distribution_skew,
            },
            "bankruptcy_checks": {
                "x100_bankruptcy_rate": x100_br,
                "x200_bankruptcy_rate": x200_br,
                "x500_bankruptcy_rate": x500_br,
            },
            "alerts": alerts,
            "action_recommendations": action_recommendations,
            "conclusion_template": {
                "data_confidence": conclusion_data_confidence,
                "player_feel": conclusion_player_feel,
                "rtp_structure": conclusion_rtp_structure,
                "session_risk": conclusion_session_risk,
                "design_action": conclusion_design_action,
            },
        },
    }

    guideline_comparison = evaluate_guideline_comparison(summary, args.guideline_rules)
    summary["guideline_comparison"] = guideline_comparison

    # ── Phase C5 — stash keys for UpstreamFeatureBreakdown + CollectMechanic ──
    # Analogous to _bankruptcy_rows / _bankruptcy_sim_session_spins (C1).
    # Each stash key carries pre-computed data into the plugin's emit() method,
    # which reads it, augments it (collect_mechanic adds gap #6 recommendation),
    # removes the stash key, and writes the final summary location.

    # Stash for UpstreamFeatureBreakdown plugin (Pattern B stash — Phase 3 carve).
    #
    # Phase 3 (analyzer honesty/isolation; 07_decision.md §5 Phase 3-6 + R-11):
    # the ~400-line upstream_feature_breakdown row-BUILD was carved OUT of this
    # file and INTO the UpstreamFeatureBreakdown plugin's emit() (mirrors the 2a
    # collect_mechanic / 2b bonus_chain_dynamics carves).  The stash now carries
    # the RAW inputs the row-build reads — NOT the pre-built {applicable, source,
    # features} dict.  The plugin re-sources each raw input from this stash and
    # builds the dict VERBATIM (key/sort order / float forms / None-vs-0.0
    # preserved → report output byte-identical).  PIA shed the row-builder, so
    # base_hash shrinks one-time and editing this feature's compute flips only
    # its feature_hash, not base.
    #
    # The SHARED helpers _infer_feature_spin_type_mapping / _resolve_bonus_feature
    # / _load_bcm_pairings stay in PIA (used elsewhere + unit-tested against this
    # module directly; the plugin must not import PIA — circular law).  PIA
    # pre-computes their RESULTS above (feature_to_spin_type / spin_type_to_feature
    # / ambiguous_mapped at ~3467; _bcm_bonus_feature / _bcm_bonus_source at ~3498)
    # and passes them as raw inputs here.  build_multiplier_bucket_rows lives in
    # analyzer.core.aggregator (a base-closure module) and is imported directly by
    # the plugin (no circular dependency).
    #
    # Per feedback_no_silent_swallow.md the plugin reads each raw key by explicit
    # indexing and raises if any is absent (no silent default that would corrupt
    # report numbers).
    summary["_upstream_feature_breakdown_data"] = {
        # Resolved helper RESULTS (helpers stay in PIA — circular law).
        "feature_to_spin_type": feature_to_spin_type,
        "spin_type_to_feature": spin_type_to_feature,
        "ambiguous_mapped": ambiguous_mapped,
        "bcm_bonus_feature": _bcm_bonus_feature,
        "bcm_bonus_source": _bcm_bonus_source,
        # The per-feature per-pid {win, times} tally the row headers read.
        "upstream_feature_tally": upstream_feature_tally,
        # SpinType transition table (drives successor/predecessor inference).
        "spin_type_next_counts": spin_type_next_counts,
        # Chain post-processing accumulators (drive the per-path sub_streams).
        "chain_chunk_summaries": chain_chunk_summaries,
        "chain_bucket_spins": chain_bucket_spins,
        "chain_bucket_bet": chain_bucket_bet,
        "chain_bucket_win": chain_bucket_win,
        # Round-level multiplier-bucket accumulators + settlement-ST fallbacks.
        "spin_type_bucket_spins": spin_type_bucket_spins,
        "spin_type_bucket_bet": spin_type_bucket_bet,
        "spin_type_bucket_win": spin_type_bucket_win,
        "session_bucket_spins_by_settlement_st": session_bucket_spins_by_settlement_st,
        "session_bucket_bet_by_settlement_st": session_bucket_bet_by_settlement_st,
        "session_bucket_win_by_settlement_st": session_bucket_win_by_settlement_st,
        # Wild-nudge tagging inputs.
        "spin_type_spins": spin_type_spins,
        "spin_type_nudge_round_count": spin_type_nudge_round_count,
        # Scalars.
        "total_spins": total_spins,
        "effective_bet_for_rtp": effective_bet_for_rtp,
        "upstream_total_win": upstream_total_win,
    }

    # Stash for CollectMechanic plugin (Pattern B stash — Phase 2a carve).
    # The plugin now OWNS the collect_mechanic dict-building compute; this stash
    # carries only the RAW accumulator inputs (no compute here).  All variables
    # below are local PIA accumulators from the merge loop.
    #
    # _resolve_bonus_feature stays in PIA (it is SHARED with the bonus-chain
    # accumulation path at ~3579; the plugin must not import it — circular law).
    # PIA pre-resolves the (feature, source) strings and passes them as raw data;
    # the plugin re-sources them from this stash and runs the dict-build + the
    # _compute_bonus_correction / collect_feature_match_warning /
    # build_cycle_observation calls (all moved into / imported by the plugin).
    _cm_bonus_feat, _cm_bonus_src = _resolve_bonus_feature(
        args.machine, args.rtp_mode, upstream_feature_tally, _load_bcm_pairings()
    )
    summary["_collect_mechanic_data"] = {
        "collect_robots_seen_total": collect_robots_seen_total,
        "collect_count_total": collect_count_total,
        "acc_credits_max_global": acc_credits_max_global,
        "total_spins": total_spins,
        "clamp_pending_robots_total": clamp_pending_robots_total,
        "clamp_pending_paid_spins_total": clamp_pending_paid_spins_total,
        "total_paid_sessions": total_paid_sessions,
        "all_cycle_peaks": all_cycle_peaks,
        "all_final_cc_values": all_final_cc_values,
        "total_completed_cycles": total_completed_cycles,
        "upstream_feature_tally": upstream_feature_tally,
        "effective_bet_for_rtp": effective_bet_for_rtp,
        "bonus_feature": _cm_bonus_feat,
        "bonus_feature_source": _cm_bonus_src,
    }

    # ── Phase C6 / Phase 2b — stash key for BonusChainDynamics plugin ─────
    # Analogous to _collect_mechanic_data / _upstream_feature_breakdown_data (C5).
    #
    # Phase 2b (analyzer honesty/isolation; 07_decision.md §5 Phase 2 + R-11):
    # the bonus_chain_dynamics dict-BUILD was carved OUT of this file and INTO the
    # BonusChainDynamics plugin's emit() (mirrors the 2a collect_mechanic carve).
    # The stash now carries the RAW accumulator inputs the build reads — NOT the
    # pre-built dict.  The plugin re-sources each raw input from this stash and
    # builds the dict VERBATIM (key order / float / 0.0-default forms preserved →
    # report output byte-identical).  PIA shed the `_quantiles` closure + the
    # `depth_curve` loop + the dict literal, so base_hash shrinks one-time and
    # editing this feature's compute flips only its feature_hash, not base.
    #
    # machine_mechanics.emit() reads summary["player_impact"]["bonus_chain_dynamics"]
    # for the M275 freespin fallback path.  That key is now written ONLY by the
    # BonusChainDynamics plugin emit() — which runs before machine_mechanics.emit()
    # because machine_mechanics.REQUIRES = ("bonus_chain_dynamics",) (C-3).
    #
    # The stash carries (Phase 2b — raw inputs, no compute):
    #   - the 9 raw accumulators the dict-build reads (see plugin emit() for the
    #     verbatim build): bonus_chain_lengths, bonus_chain_max_ratios,
    #     bonus_total_rounds_global, bonus_retrigger_rounds_global,
    #     bonus_chain_retrigger_events, bonus_extra_ratio_counts,
    #     bonus_depth_ratio_count, bonus_depth_ratio_sum, all_chains_by_feature.
    #   - scatter_feature_names: sorted list of feature names from
    #     all_chains_by_feature keys that have non-empty lengths (the same
    #     filter as by_feature in the build). Used by the plugin to
    #     infer trigger_target for scatter-marker pids (gap #3). KEPT in PIA
    #     (cheap; the plugin's trigger-inference consumes it) — Phase 2b moves
    #     ONLY the bcd dict-build, not this derivation.
    summary["_bonus_chain_dynamics_data"] = {
        # Phase 2b RAW inputs (the dict-build moved into the plugin re-sources
        # each of these). Per feedback_no_silent_swallow.md the plugin reads each
        # by explicit indexing and raises if any is absent (no silent default).
        "bonus_chain_lengths": bonus_chain_lengths,
        "bonus_chain_max_ratios": bonus_chain_max_ratios,
        "bonus_total_rounds_global": bonus_total_rounds_global,
        "bonus_retrigger_rounds_global": bonus_retrigger_rounds_global,
        "bonus_chain_retrigger_events": bonus_chain_retrigger_events,
        "bonus_extra_ratio_counts": bonus_extra_ratio_counts,
        "bonus_depth_ratio_count": bonus_depth_ratio_count,
        "bonus_depth_ratio_sum": bonus_depth_ratio_sum,
        "all_chains_by_feature": all_chains_by_feature,
        "scatter_feature_names": sorted(
            feat for feat, afb in all_chains_by_feature.items()
            if afb.get("lengths")
        ),
        # R1 Phase 2 d2: chain counts per feature for trigger_target majority-vote
        # heuristic.  Picks the feature with the most observed chains as the scatter
        # trigger target (e.g. M275: NCS=841 >> NewFreespin=67 → NCS correct).
        # The bonus_chain_dynamics plugin uses this to disambiguate when 2+ scatter
        # features are present.  Must be in this same commit as the plugin change
        # (the plugin raises RuntimeError if the key is absent and len >= 2).
        "scatter_feature_chain_counts": {
            feat: len(afb["lengths"])
            for feat, afb in all_chains_by_feature.items()
            if afb.get("lengths")
        },
    }

    # ── Phase 4 — stash key for MultiplierProfile plugin ──────────────────
    # Analogous to _bonus_chain_dynamics_data / _upstream_feature_breakdown_data /
    # _collect_mechanic_data (the 2a/2b/3 carves).
    #
    # Phase 4 (analyzer honesty/isolation; 07_decision.md §5 Phase 3-6 + R-11):
    # the multiplier_profile dict-BUILD was carved OUT of this file (was the inline
    # player_impact.multiplier_profile literal — pre-carve PIA:~3964) and INTO the
    # MultiplierProfile plugin's emit().  The stash now carries the RAW inputs the
    # build reads — NOT the pre-built {metric, buckets, ...} dict.  The plugin
    # re-sources each raw input from this stash and builds the dict VERBATIM (key
    # order / float / None-vs-0.0 forms preserved → report output byte-identical).
    # PIA shed the dict literal, so base_hash shrinks one-time and editing this
    # feature's compute flips only its feature_hash, not base.
    #
    # All 5 inputs are PIA-local values that remain SHARED with other consumers
    # (multiplier_bucket_rows → volatility.return_bucket_rate at ~3961 + the
    # buckets_complete quality gate at ~3641 + the markdown bucket section at ~4878;
    # tail_rtp_contribution_pp_ge10x → guideline derived_metrics at ~4180;
    # tail_spins_ge10 / mb_total_spins / tail_win_share_ge10x → the markdown section).
    # Phase 4 moves ONLY the dict-build, not those derivations — so the values are
    # computed once above and merely passed here as raw inputs.
    #
    # Per feedback_no_silent_swallow.md the plugin reads each raw key by explicit
    # indexing and raises if any is absent (no silent default that would corrupt
    # report numbers).
    summary["_multiplier_profile_data"] = {
        "multiplier_bucket_rows": multiplier_bucket_rows,
        "tail_spins_ge10": tail_spins_ge10,
        "mb_total_spins": mb_total_spins,
        "tail_rtp_contribution_pp_ge10x": tail_rtp_contribution_pp_ge10x,
        "tail_win_share_ge10x": tail_win_share_ge10x,
    }

    # ── Phase 5 — stash key for ReelMarginalBySpinType plugin ─────────────
    # Analogous to _multiplier_profile_data (Phase 4) / _upstream_feature_breakdown_data
    # (C5) / _bonus_chain_dynamics_data (2b) / _collect_mechanic_data (2a).
    #
    # Phase 5 (analyzer honesty/isolation; 07_decision.md §5 Phase 3-6 + R-11):
    # the reel_marginal_by_spin_type dict-BUILD was carved OUT of this file (was the
    # inline build at pre-carve PIA:~3432, the
    # `for st_int, label in sorted(_st_label.items())` loop) and INTO the
    # ReelMarginalBySpinType plugin's emit().  The stash carries the single RAW
    # accumulator the build reads — the per-ST per-column symbol-count map — NOT
    # the pre-built {label → {col → [...]}} dict.  PIA shed the dict literal, so
    # base_hash shrinks one-time and editing this feature's compute flips only its
    # feature_hash, not base.
    #
    # Only ONE raw input is stashed: symbol_counts_by_col_by_spin_type_total
    # (built at ~1182, populated at ~1655/~2425).  After this carve it has NO
    # other consumer in PIA — it fed only this build.  The OTHER build input,
    # the {spin_type → "ST{N}_{behavior_name}"} label map (was the PIA-local
    # _st_label), is NOT stashed: the plugin RE-DERIVES it from
    # summary["player_impact"]["spin_type_breakdown"] (the rows F1 wrote above),
    # exactly as PayoutsBySpinType.emit() already does.  spin_type_breakdown is
    # itself SHARED (the spin_type_breakdown panel + the pay_id category column),
    # so it stays in PIA and the plugin reads its already-emitted value — no
    # circular import, no duplicated source of truth.
    #
    # Per feedback_no_silent_swallow.md the plugin reads the stash key by explicit
    # indexing and raises if absent (no silent default that would corrupt the
    # report numbers).
    summary["_reel_marginal_by_spin_type_data"] = {
        "symbol_counts_by_col_by_spin_type_total": symbol_counts_by_col_by_spin_type_total,
    }

    # ── Wave 2c / Phase C1: registered feature emit hooks ─────────────────
    # Phase C1 of analyzer unbundle (04_v3 §7.2) — plumbing only.
    # No visible output change; M14 + M275 cached rebuilds byte-identical.
    #
    # Execution order per 04_v3 §4.2:
    #   Phase B (F1 inline, already complete above) → Phase C (registry
    #   build, placeholder in C1) → Phase D (topo-sorted emit loop).
    #
    # Stash temp keys for BankruptcySimulation.emit() (Pattern B).
    # bankruptcy_rows was built earlier (pre-summary) by the plugin's
    # build_bankruptcy_rows() — Phase 6 carve; it's still needed by the
    # markdown section below (local variable, not deleted here).
    # The temp keys carry it into the feature's emit and are removed there.
    summary["_bankruptcy_rows"] = bankruptcy_rows
    summary["_bankruptcy_sim_session_spins"] = bankruptcy_sim_session_spins

    # Trigger feature module imports so their register() calls fire.
    # Dual-path (package-mode / standalone-script) mirrors the pattern at
    # the module top (lines 182-231). Each register() is idempotent.
    try:
        import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
        import fresh_slotlab.analyzer.features.reel_marginal_by_spin_type  # noqa: F401
        import fresh_slotlab.analyzer.features.bankruptcy_simulation  # noqa: F401
        import fresh_slotlab.analyzer.features.multiplier_profile  # noqa: F401
        import fresh_slotlab.analyzer.features.multiplier_wild  # noqa: F401  # C3.5
        import fresh_slotlab.analyzer.features.machine_mechanics  # noqa: F401  # C4
        import fresh_slotlab.analyzer.features.upstream_feature_breakdown  # noqa: F401  # C5
        import fresh_slotlab.analyzer.features.collect_mechanic  # noqa: F401  # C5
        import fresh_slotlab.analyzer.features.bonus_chain_dynamics  # noqa: F401  # C6
        from fresh_slotlab.analyzer.feature_registry import (
            ALL_FEATURES as _ALL_FEATURES,
            get_features_for_machine as _get_features_for_machine,
        )
        from fresh_slotlab.analyzer.pipeline_context import (
            PipelineContext as _PipelineContext,
            MechanismRegistry as _MechanismRegistry,
        )
        from fresh_slotlab.analyzer.parse_state import ParseState as _ParseState
        from fresh_slotlab.analyzer.topo_sort import (
            topological_sort as _topological_sort,
            PluginCyclicDependencyError as _PluginCyclicDependencyError,
            PluginMissingDependencyError as _PluginMissingDependencyError,
            PluginDeclaredDepMissingError as _PluginDeclaredDepMissingError,
        )
        from fresh_slotlab.analyzer.manifest_loader import (
            load_manifest as _c1_load_manifest,
            resolve_inheritance as _c1_resolve_inheritance,
            resolve_per_mode as _c1_resolve_per_mode,
        )
    except ImportError:  # running as standalone script
        import analyzer.features.payouts_by_spin_type  # type: ignore[no-redef]  # noqa: F401
        import analyzer.features.reel_marginal_by_spin_type  # type: ignore[no-redef]  # noqa: F401
        import analyzer.features.bankruptcy_simulation  # type: ignore[no-redef]  # noqa: F401
        import analyzer.features.multiplier_profile  # type: ignore[no-redef]  # noqa: F401
        import analyzer.features.multiplier_wild  # type: ignore[no-redef]  # noqa: F401  # C3.5
        import analyzer.features.machine_mechanics  # type: ignore[no-redef]  # noqa: F401  # C4
        import analyzer.features.upstream_feature_breakdown  # type: ignore[no-redef]  # noqa: F401  # C5
        import analyzer.features.collect_mechanic  # type: ignore[no-redef]  # noqa: F401  # C5
        import analyzer.features.bonus_chain_dynamics  # type: ignore[no-redef]  # noqa: F401  # C6
        from analyzer.feature_registry import (  # type: ignore[no-redef]
            ALL_FEATURES as _ALL_FEATURES,
            get_features_for_machine as _get_features_for_machine,
        )
        from analyzer.pipeline_context import (  # type: ignore[no-redef]
            PipelineContext as _PipelineContext,
            MechanismRegistry as _MechanismRegistry,
        )
        from analyzer.parse_state import ParseState as _ParseState  # type: ignore[no-redef]
        from analyzer.topo_sort import (  # type: ignore[no-redef]
            topological_sort as _topological_sort,
            PluginCyclicDependencyError as _PluginCyclicDependencyError,
            PluginMissingDependencyError as _PluginMissingDependencyError,
            PluginDeclaredDepMissingError as _PluginDeclaredDepMissingError,
        )
        from analyzer.manifest_loader import (  # type: ignore[no-redef]
            load_manifest as _c1_load_manifest,
            resolve_inheritance as _c1_resolve_inheritance,
            resolve_per_mode as _c1_resolve_per_mode,
        )

    # ── Phase C1 — Step 1: resolve manifest for PipelineContext ──────────
    # Load the per-mode manifest so PipelineContext.manifest is populated.
    # Best-effort: failure falls back to empty dict (same graceful degradation
    # as the RTP integrity gate below at line ~4875).
    _c1_manifest: dict[str, Any] = {}
    try:
        _c1_manifest = _c1_load_manifest(args.machine, _DEFAULT_MANIFEST_ROOT)
        if _c1_manifest.get("inherits_from"):
            _c1_manifest = _c1_resolve_inheritance(_c1_manifest, _DEFAULT_MANIFEST_ROOT)
        _c1_manifest = _c1_resolve_per_mode(_c1_manifest, args.rtp_mode)
    except (FileNotFoundError, KeyError, Exception):  # noqa: BLE001
        _c1_manifest = {}

    # ── Phase C4 — Step 2: build MechanismRegistry (Tier 1/2/3 detection) ──
    # Phase C4 replaces the C1 placeholder with real detection logic.
    # INVARIANT: F1 inline MUST have written spin_type_breakdown before this
    # call (see 04_v3 §4.2 ordering contract).
    #
    # NOTE (R1 Cluster A scope boundary — post-commit critic Q8): the three
    # asserts below are DEV-TIME ordering invariants, NOT operator-facing runtime
    # errors. They can only fire if a developer reorders the inline F-blocks
    # (caught immediately by these asserts in that developer's own test/CI run);
    # they CANNOT fire on any shipped machine config or runtime/data condition.
    # They are therefore deliberately OUTSIDE Cluster A's structured-error disk-
    # surfacing (Region 1 topo-sort / Region 2 DECLARED_DEPS), which targets
    # errors reachable from real machine configs. An AssertionError here fails
    # fast and loud (descriptive message + traceback to stderr) — the correct
    # behavior for an internal code invariant, and NOT a silent swallow (the
    # traceback IS surfaced; it is simply not the structured analyzer_init_error
    # JSON). If a future invariant in this region becomes runtime/data-reachable,
    # convert it to a checked raise routed through _safe_write_summary_json.
    assert "spin_type_breakdown" in summary.get("player_impact", {}), (
        "PHASE C1 INVARIANT: F1 inline must write player_impact.spin_type_breakdown "
        "before MechanismRegistry build. Ordering contract violated."
    )
    # C4 FIX-1 (per impl-critic): machine_mechanics.emit() also reads
    # payout_ids_top20 + bonus_chain_dynamics via defensive .get(..., []).
    # If Phase B ordering is violated by a future edit, those defensive paths
    # silently produce jp_win=0 + fs_chain_spins=0 — wrong numbers with NO
    # error. Assert all three sentinels for the inline-F-blocks-complete
    # invariant.
    assert "payout_ids_top20" in summary.get("player_impact", {}), (
        "PHASE C4 INVARIANT: F2 inline must write player_impact.payout_ids_top20 "
        "before MechanismRegistry build. machine_mechanics.jackpot Tier 3 reads "
        "this; silent fallback would produce jackpot.applicable=false for "
        "M275-class machines. Ordering contract violated."
    )
    assert "_bonus_chain_dynamics_data" in summary, (
        "PHASE R2-C2 INVARIANT: F6 stash builder must write _bonus_chain_dynamics_data "
        "before MechanismRegistry build. BonusChainDynamics plugin (and transitively "
        "machine_mechanics via REQUIRES) depends on this stash being present. "
        "If absent, BCD plugin raises PluginDeclaredDepMissingError (Region 2). "
        "Ordering contract violated."
    )
    # Extract pid_has_regular_line from payouts_by_spin_type plugin accumulator.
    # This is built by PayoutsBySpinType.extract() across all chunks and tells
    # us which PIDs have at least one regular payline record (line_id != -1).
    # PIDs absent from this dict (or with False value) are scatter-trigger-only.
    _c4_pbs_acc = _feature_accs.get("payouts_by_spin_type") or {}
    _c4_pid_has_regular_line: dict[str, bool] = _c4_pbs_acc.get("pid_has_regular_line") or {}
    _mechanism_registry = _MechanismRegistry.build(
        manifest=_c1_manifest,
        payout_id_win=dict(payout_id_win),
        payout_id_hits=dict(payout_id_hits),
        jackpot_ids_seen=total_jackpot_ids_seen,
        bonus_chain_lengths=bonus_chain_lengths,
        total_freespin_chain_spins=total_freespin_chain_spins,
        payout_group_win=dict(payout_group_win),
        pid_has_regular_line=_c4_pid_has_regular_line,
    )
    summary["_mechanism_registry"] = _mechanism_registry

    # ── B-4 (CR-2): surface unrecognized mechanism_overrides keys to disk ──
    # Per feedback_invariant_with_fallback_hides_drift.md + feedback_no_silent_swallow.md:
    # an unknown override key (e.g. a typo in the manifest) must appear in
    # summary["feature_errors"] on disk, not just as a log line.
    # Today 0 manifests use mechanism_overrides, so this block is dormant —
    # it fires only if an operator adds a manifest override with an unknown key.
    for _b4_key in _mechanism_registry.unknown_override_keys:
        if "feature_errors" not in summary:
            summary["feature_errors"] = {}
        summary["feature_errors"][f"mechanism_registry_unknown_override_{_b4_key}"] = {
            "type": "UnrecognizedMechanismOverrideKey",
            "key": _b4_key,
            "machine_id": summary.get("machine_id", "unknown"),
            "detail": (
                f"Manifest mechanism_overrides contains unrecognized key '{_b4_key}'. "
                f"Recognized keys: scatter_marker_pids, jackpot_applicable, "
                f"jackpot_pid_set, freespin_applicable, payout_groups_applicable. "
                f"This override was silently ignored; fix the manifest to suppress."
            ),
        }

    # ── Phase C1 — Step 3: compute robots_with_pending_cycle ─────────────
    # Mirrors the robots_with_pending_cycle computation that the
    # collect_mechanic plugin runs (bonus_cycle_correction) on the same
    # accumulators.  Computed here so PipelineContext.robots_with_pending_cycle
    # is correct without duplicating logic or reading from the summary dict.
    _c1_cycle_median: int | None = (
        int(sorted(all_cycle_peaks)[len(all_cycle_peaks) // 2])
        if all_cycle_peaks else None
    )
    _c1_robots_with_pending_cycle: int = (
        sum(
            1 for fcc in all_final_cc_values
            if _c1_cycle_median is not None and fcc < _c1_cycle_median
        )
    )

    # ── Phase C1 — Step 4: construct PipelineContext ──────────────────────
    # All fields from local accumulator variables per 04_v3 §4.1 + §4.3.
    # total_paid_spins = sum of paid rounds across all SpinTypes (rounds
    # where CostCredits > 0, accumulated into spin_type_paid_rounds).
    _c1_ctx = _PipelineContext(
        effective_bet_for_rtp=effective_bet_for_rtp,
        total_spins=total_spins,
        total_paid_sessions=total_paid_sessions,
        total_paid_spins=int(sum(spin_type_paid_rounds.values())),
        clamp_pending_robots_total=clamp_pending_robots_total,
        robots_with_pending_cycle=_c1_robots_with_pending_cycle,
        mechanism_registry=_mechanism_registry,
        manifest=_c1_manifest,
    )

    # ── Phase C1 — Step 5: topo-sort + emit loop ─────────────────────────
    # Use manifest-filtered feature set (get_features_for_machine).
    # Falls back to ALL_FEATURES if manifest is empty (Phase 2 stub behavior).

    # R1 Cluster A: helper defined here so it is in scope for BOTH error
    # regions below (Region 1 = topo-sort block; Region 2 = DECLARED_DEPS
    # check inside the emit loop).  Per feedback_no_silent_swallow.md: any
    # best-effort post-hook must persist diagnostic to disk.
    #
    # CRITICAL: stderr_ref is passed at CALL TIME (sys.stderr), NOT captured
    # via closure from main() top, per arch-v2 §4.3 critique BF-2.
    def _strip_internal_stash_keys(summary):
        """Remove all _-prefixed top-level temp/stash keys (live, non-serializable).

        Mirrors the success-path cleanup later in main(). Stash keys hold live
        Python objects — _mechanism_registry (a MechanismRegistry), _bankruptcy_rows,
        the C5 temp dicts — that are NOT JSON-serializable. They MUST be stripped
        before ANY write_summary_json, including the Region 1/2 error-path writes,
        or the write raises "Object of type X is not JSON serializable" and the
        diagnostic never reaches disk (defeating Cluster A). Partial player_impact
        plugin output (non _-prefixed) is preserved as the diagnostic per arch-v2
        §4.3 "keep partial + annotate".
        """
        for _tmp_key in list(summary.keys()):
            if _tmp_key.startswith("_"):
                summary.pop(_tmp_key, None)

    def _safe_write_summary_json(summary, output_dir, *, stderr_ref):
        """Write summary JSON without letting write failure suppress caller's exception.

        If write_summary_json raises (e.g. OSError, disk full, permission denied),
        log the write failure to stderr_ref and RETURN — do NOT re-raise.
        The caller's SystemExit(1) propagates unmolested.
        Per feedback_no_silent_swallow.md: diagnostic is persisted on best-effort;
        if the write itself fails, the stderr log is the fallback record.
        """
        # Region 1/2 fire BEFORE the success-path stash cleanup, so non-serializable
        # internal stash objects (_mechanism_registry et al.) are still in summary
        # and would make the write fail. Strip them first; keep partial player_impact.
        _strip_internal_stash_keys(summary)
        try:
            write_summary_json(summary, output_dir)
        except Exception as _write_exc:
            print(
                f"ERROR: failed to write summary JSON on error path: {_write_exc}",
                file=stderr_ref,
            )
            # Return — do not re-raise. Caller's SystemExit(1) propagates.

    _machine_features = _get_features_for_machine(
        args.machine,
        manifest=_c1_manifest if _c1_manifest else None,
    )

    try:
        _sorted_features = _topological_sort(_machine_features)
    except (_PluginCyclicDependencyError, _PluginMissingDependencyError) as _topo_exc:
        # R1 Cluster A — Region 1: topo-sort hard error.
        # Programming error: cycle or missing dep in REQUIRES declarations.
        # Per 04_v3 §4.2 topo-sort failure surfacing + feedback_no_silent_swallow.md.
        # Per arch-v2 §4.3: affected_plugin=None (multiple plugins may be involved
        # in a cycle; PluginMissingDependencyError.plugin is set on the exc itself
        # but for schema uniformity both use None here); region=1 signals pre-emit.
        summary["analyzer_init_error"] = {
            "error_type": type(_topo_exc).__name__,
            "message": str(_topo_exc),
            "plugin_dep_graph": {
                f.FEATURE_ID: list(f.REQUIRES)
                for f in _machine_features
            },
            "affected_plugin": None,
            "region": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print(
            f"ERROR: analyzer plugin topo-sort failed: "
            f"{type(_topo_exc).__name__} — {_topo_exc}",
            file=sys.stderr,
        )
        # Write structured diagnostic to disk BEFORE exit so backend/operator
        # can inspect the error. _safe_write_summary_json guards against write
        # failure replacing the original SystemExit(1) (per arch-v2 §4.3).
        _safe_write_summary_json(summary, args.output_dir, stderr_ref=sys.stderr)
        # Non-zero exit so backend marks run as failed.
        raise SystemExit(1) from _topo_exc

    # Invoke each feature's emit in topological order.
    # Pattern A features verify key presence (no-op).
    # Pattern B features (BankruptcySimulation) write their final schema keys.
    # Per 04_v3 §4.2 error handling: emit() errors log + set
    # summary["feature_errors"][fid]; do NOT crash the run.
    for _feature in _sorted_features:
        # R1 Cluster A — Region 2: DECLARED_DEPS check.
        # Validate DECLARED_DEPS summary-dict keys are present in summary before
        # calling emit. A missing dep key is a programming error (ordering bug or
        # typo in DECLARED_DEPS). Per arch-v2 §4.3: write structured diagnostic to
        # disk + raise SystemExit(1) so backend marks run as failed.
        # Partial plugin output preceding analyzer_init_error is intentional and
        # diagnostic (region=2): plugins that emitted before the failing one are
        # preserved in summary; affected_plugin identifies the break point.
        for _dep_key in _feature.DECLARED_DEPS:
            if _dep_key not in summary:
                _dep_exc = _PluginDeclaredDepMissingError(
                    plugin=_feature.FEATURE_ID,
                    missing_dep_key=_dep_key,
                )
                summary["analyzer_init_error"] = {
                    "error_type": type(_dep_exc).__name__,
                    "message": str(_dep_exc),
                    "plugin_dep_graph": {
                        f.FEATURE_ID: list(f.REQUIRES)
                        for f in _machine_features
                    },
                    "affected_plugin": _feature.FEATURE_ID,
                    "region": 2,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                print(
                    f"ERROR: analyzer DECLARED_DEPS check failed for "
                    f"'{_feature.FEATURE_ID}': key '{_dep_key}' absent from summary",
                    file=sys.stderr,
                )
                # Write structured diagnostic to disk BEFORE exit so backend/operator
                # can inspect the error (per feedback_no_silent_swallow.md).
                # Partial plugin output preceding analyzer_init_error is intentional
                # and diagnostic (region=2).
                _safe_write_summary_json(summary, args.output_dir, stderr_ref=sys.stderr)
                raise SystemExit(1) from _dep_exc
        try:
            _feature.emit(_feature_accs.get(_feature.FEATURE_ID, {}), summary, _c1_ctx)
        except Exception as _emit_exc:  # noqa: BLE001
            import sys as _sys
            print(
                f"ERROR: feature '{_feature.FEATURE_ID}' emit() failed: {_emit_exc}",
                file=_sys.stderr,
            )
            if "feature_errors" not in summary:
                summary["feature_errors"] = {}
            summary["feature_errors"][_feature.FEATURE_ID] = str(_emit_exc)

    # Phase C2: surface _extract_error_* entries from _feature_accs into
    # summary["feature_errors"] so they persist to disk.
    # Per feedback_no_silent_swallow.md: extract() errors must not be silently
    # swallowed — they are captured per-feature during the merge loop and
    # surfaced here after the emit loop completes.
    for _feat_key, _feat_errs in list(_feature_accs.items()):
        if _feat_key.startswith("_extract_error_") and _feat_errs:
            _fid = _feat_key[len("_extract_error_"):]
            if "feature_errors" not in summary:
                summary["feature_errors"] = {}
            # Join all per-chunk errors for this feature into one entry.
            summary["feature_errors"][f"extract_{_fid}"] = "; ".join(
                str(e) for e in _feat_errs
            )

    # Cleanup: remove all _-prefixed temp keys (DECLARED_DEPS + registry).
    # This includes _bankruptcy_rows, _bankruptcy_sim_session_spins,
    # _mechanism_registry, _upstream_feature_breakdown_data (C5),
    # _collect_mechanic_data (C5), and any future plugin temp keys.
    # Use pop() with default to guard against keys already deleted by emit()
    # (BankruptcySimulation.emit() and C5 plugins delete their own temp keys
    # in-situ via summary.pop(_STASH_KEY)). Shared with the error-path writes
    # (Region 1/2) via _strip_internal_stash_keys — single definition of
    # "what is an internal stash key".
    _strip_internal_stash_keys(summary)
    # ── End Wave 2c / Phase C1 + C2 ───────────────────────────────────────────

    # ── Phase 5 (P5-1 partial): RTP integrity gate, warn-only ──────────────
    # Run the 4-layer integrity gate against the just-built summary and
    # stash the result into summary["rtp_integrity_check"] per architecture
    # proposal section 9 + ticket P2-E1 §3 C1. Default warn_only=True so
    # the gate NEVER raises here — operator-facing layer-failure surfacing
    # happens in the console UI. Phase 5 proper flips warn_only per
    # manifest.console_diagnostic_complete (deferred).
    #
    # Best-effort: any exception inside the gate (e.g. missing manifest
    # for this machine, or layer-internal data corruption that the gate
    # itself cannot soft-catch) is recorded onto summary with a
    # diagnostic string. Per memory feedback_no_silent_swallow.md the
    # outcome is preserved on disk; per
    # feedback_dont_swallow_errors_in_fix.md the catch is scoped to
    # documented expected failure modes only.
    try:
        try:
            from fresh_slotlab.analyzer.rtp_integrity import (
                check_rtp_integrity as _check_rtp_integrity,
                Layer4Error as _Layer4Error,
            )
            from fresh_slotlab.analyzer.manifest_loader import (
                load_manifest as _load_manifest,
                resolve_inheritance as _resolve_inheritance,
                resolve_per_mode as _resolve_per_mode,
            )
        except ImportError:  # script-mode (no fresh_slotlab namespace)
            from analyzer.rtp_integrity import (  # type: ignore[no-redef]
                check_rtp_integrity as _check_rtp_integrity,
                Layer4Error as _Layer4Error,
            )
            from analyzer.manifest_loader import (  # type: ignore[no-redef]
                load_manifest as _load_manifest,
                resolve_inheritance as _resolve_inheritance,
                resolve_per_mode as _resolve_per_mode,
            )
        # Resolve manifest (best-effort; if missing the gate runs against
        # an empty manifest stub which means Layer 3 anchor check is
        # vacuous, Layer 4 is skipped if rawdata_dir is None).
        _manifest: dict[str, Any] = {}
        try:
            _manifest = _load_manifest(args.machine, _DEFAULT_MANIFEST_ROOT)
            if _manifest.get("inherits_from"):
                _manifest = _resolve_inheritance(_manifest, _DEFAULT_MANIFEST_ROOT)
            _manifest = _resolve_per_mode(_manifest, args.rtp_mode)
        except (FileNotFoundError, KeyError):
            _manifest = {}
        _gate_result = _check_rtp_integrity(
            summary, manifest=_manifest or None, rawdata_dir=None, warn_only=True,
        )
        summary["rtp_integrity_check"] = {
            "passed": _gate_result.passed,
            "layer1_invariant_ok": _gate_result.layer1_invariant_ok,
            "layer1_error": _gate_result.layer1_error,
            "layer2_no_fallback_buckets_ok": _gate_result.layer2_no_fallback_buckets_ok,
            "layer2_fallback_buckets_found": list(_gate_result.layer2_fallback_buckets_found),
            "layer3_anchors_ok": _gate_result.layer3_anchors_ok,
            "layer3_missing_anchors": list(_gate_result.layer3_missing_anchors),
            "layer4_applicable": _gate_result.layer4_applicable,
            "layer4_per_st_consistency_ok": _gate_result.layer4_per_st_consistency_ok,
            "layer4_inconsistencies": list(_gate_result.layer4_inconsistencies),
            "summary_message": _gate_result.summary_message,
            "suggested_actions": list(_gate_result.suggested_actions),
            "completeness_declared": _gate_result.completeness_declared,
        }
    except _Layer4Error as _exc:  # noqa: F841 — recorded for operator
        # Data corruption in rawdata (SpinType missing / invalid). Record
        # but do NOT crash report generation — the operator needs the
        # rest of the summary to investigate.
        summary["rtp_integrity_check"] = {
            "passed": False,
            "error": f"Layer4Error: {_exc}",
        }
        print(
            f"[pia] rtp_integrity gate Layer4Error for {args.machine} "
            f"mode {args.rtp_mode}: {_exc}",
            file=sys.stderr,
        )
    except Exception as _exc:  # noqa: BLE001 — best-effort
        summary["rtp_integrity_check"] = {
            "passed": None,
            "error": f"{type(_exc).__name__}: {_exc}",
        }
        print(
            f"[pia] rtp_integrity gate did not run for {args.machine} "
            f"mode {args.rtp_mode}: {type(_exc).__name__}: {_exc}",
            file=sys.stderr,
        )
    # ── End Phase 5 partial ─────────────────────────────────────────────────

    # EC-4 surface (critique_commitC1 finding #2): if any play-type plugin
    # accumulator faulted across any chunk during this run, write the
    # aggregated diagnostics into the summary and emit a stderr warning so
    # the operator sees the signal.  The summary key is only written when
    # non-empty (empty-registry / no-fault runs add zero keys — byte-identical
    # invariant preserved for the 9-pilot golden baseline).
    # Per memory/feedback_no_silent_swallow.md: both a durable (summary JSON)
    # and an immediate (stderr) signal are required.
    if _play_type_plugin_errors_total:
        summary["play_type_plugin_warnings"] = {
            "total_faults": len(_play_type_plugin_errors_total),
            "records": _play_type_plugin_errors_total,
        }
        print(
            f"[play_type_plugins] WARNING: {len(_play_type_plugin_errors_total)} "
            f"accumulator fault(s) across {chunks} chunk(s) for "
            f"{args.machine} mode {args.rtp_mode}. "
            f"See summary['play_type_plugin_warnings'] for details.",
            file=sys.stderr,
        )

    out_json = write_summary_json(summary, args.output_dir)  # P2-B3

    md_lines = [
        f"# {args.machine} Mode={args.rtp_mode} Player Impact Report",
        "",
        "## Sampling",
        f"- total_spins: {total_spins}",
        f"- chunks: {chunks}",
        f"- target_halfwidth_pp: {args.target_halfwidth_pp}",
        f"- achieved_halfwidth_pp: {achieved_halfwidth_pp}",
        f"- chunk_level_halfwidth_pp: {chunk_level_halfwidth_pp}",
        f"- session_level_halfwidth_pp: {session_level_halfwidth_pp}",
        f"- stop_reason: {stop_reason}",
        f"- duration_seconds: {duration_seconds}",
        "",
        "## RTP",
        f"- point_pct: {rtp_point_pct:.6f}%",
        f"- ci95_interval_pct: {ci_interval}",
        "",
        "## Player Impact",
        f"- volatility.avg_return_x: {avg_return_x:.6f}",
        f"- volatility.std_return_x: {std_return_x:.6f}",
        f"- volatility.max_observed_return_x: {max_observed_return_x:.6f}",
        f"- win_hit_rate: {hit_rate:.6f}",
        f"- zero_win_rate: {zero_win_rate:.6f}",
        f"- profit_spin_rate: {profit_spin_rate:.6f}",
        f"- breakeven_or_more_rate: {breakeven_or_more_rate:.6f}",
        f"- big_win_x10_rate: {big_win_x10_rate:.6f}",
        f"- big_win_x20_rate: {big_win_x20_rate:.6f}",
        f"- big_win_x50_rate: {big_win_x50_rate:.6f}",
        f"- big_win_x100_rate: {big_win_x100_rate:.6f}",
        f"- avg_win_when_hit_x: {avg_win_when_hit_x:.6f}",
        f"- loss_streak p50/p90/p95/max: {loss_streak_p50}/{loss_streak_p90}/{loss_streak_p95}/{max_loss_streak}",
        f"- win_streak p50/p90/p95/max: {win_streak_p50}/{win_streak_p90}/{win_streak_p95}/{max_win_streak}",
        "",
        "## Multiplier Buckets (ret_x = win/bet)",
        f"- tail_spin_rate_ge10x: {(tail_spins_ge10 / total_spins) if total_spins > 0 else 0.0:.6f}",
        f"- tail_rtp_contribution_pp_ge10x: {((tail_win_ge10 / total_bet) * 100.0) if total_bet > 0 else 0.0:.6f}",
        f"- tail_rtp_contribution_pp_ge20x: {((tail_win_ge20 / total_bet) * 100.0) if total_bet > 0 else 0.0:.6f}",
        f"- tail_rtp_contribution_pp_ge50x: {((tail_win_ge50 / total_bet) * 100.0) if total_bet > 0 else 0.0:.6f}",
        f"- tail_rtp_contribution_pp_ge100x: {((tail_win_ge100 / total_bet) * 100.0) if total_bet > 0 else 0.0:.6f}",
        f"- tail_win_share_ge10x: {(tail_win_ge10 / total_win) if total_win > 0 else 0.0:.6f}",
    ]
    for row in multiplier_bucket_rows:
        md_lines.append(
            "- {bucket}: spin_rate={spin_rate:.6f}, avg_x={avg_return_x_in_bucket:.6f}, "
            "rtp_pp={rtp_contribution_pp:.6f}, win_share={win_share:.6f}".format(**row)
        )

    md_lines.extend(
        [
            "",
            "## Guideline Assessment",
            f"- quality_label: {quality_label}",
            f"- volatility_class: {volatility_class}",
            f"- experience_archetype: {experience_archetype}",
            f"- recovery_gap: {recovery_gap:.6f}",
            f"- tail_dependency: {tail_dependency:.6f}",
            f"- payline_top1_share: {payline_top1_share:.6f}",
            f"- payline_top3_share: {payline_top3_share:.6f}",
            f"- blank_like_rate: {blank_like_rate:.6f}",
            f"- blank_like_col_spread: {blank_like_col_spread:.6f}",
            f"- x100_bankruptcy_rate: {x100_br:.6f}",
            f"- x200_bankruptcy_rate: {x200_br:.6f}",
            f"- x500_bankruptcy_rate: {x500_br:.6f}",
        ]
    )

    md_lines.extend(
        [
            "",
            "## Guideline Rule Comparison (External Rules)",
            f"- guideline_id: {guideline_comparison.get('guideline_id', 'unknown')}",
            f"- overall_status: {guideline_comparison.get('overall_status', 'UNKNOWN')}",
            (
                "- checks: total={check_count} pass={pass_count} fail={fail_count} "
                "missing={missing_count} not_applicable={not_applicable_count}".format(
                    check_count=guideline_comparison.get("check_count", 0),
                    pass_count=guideline_comparison.get("pass_count", 0),
                    fail_count=guideline_comparison.get("fail_count", 0),
                    missing_count=guideline_comparison.get("missing_count", 0),
                    not_applicable_count=guideline_comparison.get("not_applicable_count", 0),
                )
            ),
        ]
    )
    for row in guideline_comparison.get("checks", []):
        status = row.get("status", "unknown")
        if status == "pass":
            continue
        md_lines.append(
            f"- [{status}] {row.get('id', 'UNKNOWN')} ({row.get('severity', 'medium')}): "
            f"{row.get('description', '')} observed={row.get('observed', 'N/A')} target={row.get('target', 'N/A')}"
        )

    if alerts:
        md_lines.append("- alerts:")
        for alert in alerts:
            md_lines.append(f"- [{alert['severity']}] {alert['code']}: {alert['message']}")
    else:
        md_lines.append("- alerts: none")

    for idx, action in enumerate(action_recommendations, 1):
        md_lines.append(f"- action_{idx}: {action}")

    md_lines.extend(
        [
            "",
            "## Conclusion Template (Filled)",
            f"1. Data confidence: {conclusion_data_confidence}",
            f"2. Player feel: {conclusion_player_feel}",
            f"3. RTP structure: {conclusion_rtp_structure}",
            f"4. Session risk: {conclusion_session_risk}",
            f"5. Design action: {conclusion_design_action}",
        ]
    )

    md_lines.extend(
        [
            "",
            "## Top Paylines (approx by split win)",
        ]
    )
    for row in payline_rows[:20]:
        md_lines.append(
            f"- line {row['payline_id']}: hit_rate={row['hit_rate']:.6f}, approx_rtp_pp={row['approx_rtp_contribution_pp']:.6f}"
        )

    md_lines.append("")
    md_lines.append("## Top Symbols")
    for row in symbol_rows[:20]:
        md_lines.append(f"- {row['symbol']}: rate={row['rate']:.6f}")

    # ── SpinType-split sections (2026-05-14) ──────────────────────────
    md_lines.append("")
    md_lines.append("## Per-pay_id by SpinType")
    md_lines.append(
        "Columns: payout_id | hit_count | rtp_contribution_pp | total_win. "
        "Each sub-section is one SpinType (base vs freespin etc.)."
    )
    # Phase C2: payouts_by_spin_type local var removed; read from summary.
    _md_pbst = (summary.get("player_impact") or {}).get("payouts_by_spin_type") or {}
    for label, pid_rows in sorted(_md_pbst.items()):
        if not pid_rows:
            continue
        md_lines.append(f"")
        md_lines.append(f"### {label}")
        # Header
        md_lines.append("| pay_id | hits | rtp_contribution_pp | total_win |")
        md_lines.append("|--------|------|---------------------|-----------|")
        for pr in pid_rows[:30]:
            md_lines.append(
                f"| {pr['payout_id']} | {pr['hit_count']} "
                f"| {pr['rtp_contribution_pp']:.4f} | {pr['total_win']:.0f} |"
            )

    md_lines.append("")
    md_lines.append("## Per-reel Marginal by SpinType")
    md_lines.append(
        "Symbol probability per reel (col), split by SpinType. "
        "prob_pct sums to 100 per (SpinType, reel)."
    )
    # Phase 5: reel_marginal_by_spin_type is built by the ReelMarginalBySpinType
    # plugin emit() (no longer an inline PIA local). The emit loop above
    # populated summary["player_impact"]["reel_marginal_by_spin_type"] BEFORE this
    # markdown section runs, so read it from there. The dict is byte-identical to
    # the pre-carve local var (same labels — including empty col_rows ones, which
    # the loop below still skips — same sort order), so the markdown is unchanged.
    _reel_marginal_by_spin_type_md = (
        (summary.get("player_impact") or {}).get("reel_marginal_by_spin_type") or {}
    )
    for label, col_rows in sorted(_reel_marginal_by_spin_type_md.items()):
        if not col_rows:
            continue
        md_lines.append(f"")
        md_lines.append(f"### {label}")
        for col_key, sym_list in sorted(col_rows.items(), key=lambda kv: int(kv[0])):
            md_lines.append(f"#### Reel {col_key}")
            md_lines.append("| symbol | prob_pct |")
            md_lines.append("|--------|----------|")
            for entry in sym_list[:15]:
                md_lines.append(
                    f"| {entry['symbol']} | {entry['prob_pct']:.3f}% |"
                )

    md_lines.append("")
    md_lines.append("## Bankruptcy Simulation (rawdata replay)")
    md_lines.append(f"- session_spins: {bankruptcy_sim_session_spins}")
    md_lines.append(f"- percentile_keys: {list(_BANKRUPTCY_PERCENTILES)}")
    for row in bankruptcy_rows:
        pct = row.get("percentiles") or {}
        pct_str = " ".join(f"P{k}={pct.get(str(k), pct.get(k, 0))}" for k in _BANKRUPTCY_PERCENTILES)
        fastest = row.get("fastest_bankruptcy_spins")
        fastest_s = str(fastest) if fastest is not None else "-"
        md_lines.append(
            f"- bankroll x{row['bankroll_multiplier']}: "
            f"bankruptcy_rate={row['bankruptcy_rate']:.6f}, "
            f"median={row['median_spins_completed']}, "
            f"fastest={fastest_s}, "
            f"sessions={row['robots']}, "
            f"survived={row['completed_robots']}, "
            f"{pct_str}"
        )

    md_lines.append("")
    md_lines.append("## Storage")
    md_lines.append("- raw_round_data_persisted: false")
    md_lines.append("- persisted: player_impact_summary.json + player_impact_report.md")
    md_lines.append("")
    md_lines.append(
        "Note: payline contribution is approximate because one spin may hit multiple paylines and win is split evenly across parsed line ids."
    )

    out_md = args.output_dir / "player_impact_report.md"
    out_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    append_jsonl(
        progress_file,
        {
            "event": "completed",
            "run_id": run_id,
            "stop_reason": stop_reason,
            "total_spins": total_spins,
            "chunks": chunks,
            "duration_seconds": duration_seconds,
            "rtp_point_pct": rtp_point_pct,
            "ci95_interval_pct": ci_interval,
            "output_dir": str(args.output_dir),
            "summary_file": str(out_json),
            "report_file": str(out_md),
            "quality_label": quality_label,
            "ts": utc_now(),
        },
    )

    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    # Force-exit so any worker thread that ended up stuck in a slow
    # urllib socket read (e.g. an upstream that trickles bytes under the
    # socket-level timeout) cannot prevent the process from terminating.
    # We've already printed + flushed the summary JSON by the time
    # main() returns, so skipping atexit finalizers is safe here. If you
    # ever register a real cleanup hook (temp files, locks, ...) do it
    # before this point.
    _rc = main()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    os._exit(_rc)
