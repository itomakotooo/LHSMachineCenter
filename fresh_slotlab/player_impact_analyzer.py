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
from typing import Any

DEFAULT_ENDPOINT_URL = "http://buffalo-debug.citrusjoy.com/MachineTest/MultiRobotTestSpin"
ENDPOINT_URL = DEFAULT_ENDPOINT_URL  # mutable; overridden by --endpoint-url
PAYLINE_RE = re.compile(r"(\d+):")
# 11 win-bearing buckets. The old `eq0` bucket carried zero-win sessions
# which already live in summary.hit_and_payout.zero_win_rate; a bucket
# where avg_x / rtp_pp / win_share are all structurally zero is noise
# on the multiplier chart, so we exclude it from the ordered schema.
# `return_bucket()` returns "" for those sessions and the accumulators
# skip them.
RETURN_BUCKET_ORDER = [
    "gt0_lt1",
    "ge1_lt5",
    "ge5_lt10",
    "ge10_lt20",
    "ge20_lt50",
    "ge50_lt100",
    "ge100_lt200",
    "ge200_lt500",
    "ge500_lt1000",
    "ge1000_lt5000",
    "ge5000",
]
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
DEFAULT_GUIDELINE_RULES_PATH = (
    Path(__file__).resolve().parents[1] / "configs" / "classic_slots_guideline_rules.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Player-impact analyzer for slot test endpoint with true batch concurrency."
    )
    parser.add_argument("--machine", default="M14")
    parser.add_argument("--rtp-mode", type=int, default=1)
    parser.add_argument("--bet", type=int, default=1000)
    # Graceful-stop flag file. When set and the file exists, the main
    # chunk loop bails out between chunks and the summary records
    # stop_reason="user_stop". Cross-platform alternative to SIGTERM
    # (the Windows subprocess.terminate() calls TerminateProcess which
    # doesn't deliver a catchable signal). Backend writes this file
    # when the operator clicks Stop.
    parser.add_argument("--stop-flag-file", type=Path, default=None)
    parser.add_argument("--target-halfwidth-pp", type=float, default=0.5)
    parser.add_argument("--chunk-spin-times", type=int, default=5000)
    parser.add_argument("--chunk-robot-count", type=int, default=20)
    parser.add_argument("--batch-concurrency", type=int, default=2)
    parser.add_argument("--max-chunks", type=int, default=120)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", default=None, help="optional external run id for orchestration")
    parser.add_argument(
        "--progress-file",
        type=Path,
        default=None,
        help="optional jsonl file path for chunk-level progress events",
    )
    parser.add_argument("--bankruptcy-session-spins", type=int, default=500)
    parser.add_argument(
        "--bankruptcy-bankroll-multipliers",
        default="100,200,500",
        help="comma-separated bet multipliers for bankruptcy probe",
    )
    parser.add_argument(
        "--bankruptcy-robot-count",
        type=int,
        default=None,
        help="optional override for bankruptcy probe robot count; defaults to chunk-robot-count",
    )
    parser.add_argument(
        "--guideline-rules",
        type=Path,
        default=DEFAULT_GUIDELINE_RULES_PATH,
        help="path to external deterministic guideline check rules JSON",
    )
    parser.add_argument(
        "--chunk-cache-dir",
        type=Path,
        default=None,
        help="optional dir for raw API response caching (full per-chunk data for offline rebuild)",
    )
    parser.add_argument(
        "--from-cache",
        type=Path,
        default=None,
        help=(
            "skip API sampling; read chunk_*.json files from this directory "
            "and run the full parse → accumulate → report pipeline offline. "
            "Each file must have the chunk-cache envelope with a 'response' key."
        ),
    )
    parser.add_argument(
        "--resume-from-cache",
        type=Path,
        default=None,
        help=(
            "Resume mode: load any existing chunk_*.json from this dir (same "
            "shape as --from-cache), seed the accumulators with their state, "
            "then continue LIVE API sampling into the same dir from the next "
            "chunk index until the CI target or max_chunks is reached. "
            "Mutually exclusive with --from-cache. Skips chunks that fail sha256 "
            "integrity or whose config_md5 no longer matches upstream."
        ),
    )
    parser.add_argument(
        "--endpoint-url",
        type=str,
        default=None,
        help=f"override the sampling API endpoint (default: {DEFAULT_ENDPOINT_URL})",
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def to_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return float(text)
            except ValueError:
                return default
    return default


def post_json(payload: dict[str, Any], timeout: float) -> Any:
    req = urllib.request.Request(
        ENDPOINT_URL,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


# 5xx / transient-network retry policy shared by the live sampling loop
# (run_sampling_chunk) and the dev batch sampler. One 5xx or timeout on
# a long overnight run used to abort the whole machine; this wrapper
# rides through them. Non-retryable errors (4xx / JSONDecodeError /
# anything else) propagate on the first occurrence — retrying won't
# help and would just delay the real cause.
_RETRYABLE_HTTP_CODES = frozenset({500, 502, 503, 504})


# Fault-tolerance thresholds for the sampling loop's bailout check.
# Promoted from locals inside main() to module-level constants so:
#   (a) tests can lock them without invoking main()
#   (b) future per-run overrides (CLI flag) have a natural place to land
#
# Tuned 2026-04-17 after a user-reported M273 run bailed at
# cumulative_failed_chunks=12 inside a 10-second upstream hiccup. The
# original 3/20 thresholds paired with max_attempts=3 (3s total sleep)
# produced a retry window of ~10s which matches real-world hiccup
# duration — so we'd bail inside the hiccup instead of riding it out.
# Bumped to 5/40; combined with the retry-window extension in
# post_json_with_retry, a ~30s hiccup is now required to bail.
MAX_CONSECUTIVE_FAILED_BATCHES = 5
MAX_CUMULATIVE_FAILED_CHUNKS = 40

# AIMD (additive-increase / multiplicative-decrease) adaptive tuning
# for batch_concurrency + chunk_spin_times. Per-request retry already
# rides out brief (<30s) hiccups; AIMD handles sustained slowdowns by
# shrinking load so the upstream gets breathing room, then slowly
# re-opens once the upstream recovers. Combined with CIRCUIT_PAUSE_S
# (hard sleep after a fully-failed batch) this lets an analyzer keep
# running through a bad 5-minute upstream window rather than bailing
# at MAX_CONSECUTIVE_FAILED_BATCHES.
MIN_CHUNK_SPINS = 500
SUCCESS_STREAK_FOR_GROW = 3
CHUNK_SPINS_GROWTH = 1.25
CIRCUIT_PAUSE_S = 20.0


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
    # (M12/M15/M132 TopDollar: pay attributed to the selector spin's
    # round, pick-em round has 0 WinCredits). Drop the mapping rather
    # than emit bucket_distribution with pp sum=0 that's semantically
    # wrong. UI falls through to "no bucket data" honestly.
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
    return feature_to_spin_type, spin_type_to_feature, ambiguous_mapped


def _resolve_bonus_feature(
    machine: str,
    mode: int,
    upstream_feature_tally: dict | None,
    config: dict[str, dict[int, str]],
) -> tuple[str | None, str]:
    """Decide which FeatureWin key pairs with BuffCollectionMap for a
    given (machine, mode).

    Two-layer strategy (config → heuristic → none):
      1. If ``config[machine][mode]`` exists → return that feature,
         source="config". Respect operator override even when the
         feature's current win is zero (small cache, rare feature;
         operator knows best).
      2. Otherwise pick the feature in the tally with highest total win
         that is neither in PAID_NORMAL_FEATURES nor BuffCollectionMap
         itself. Source="heuristic".
      3. If no such feature exists (all-zero wins, empty tally, only
         paid-normal / BCM in tally) → (None, "none"). Caller should
         skip RTP correction + surface a warning.

    A machine entry that exists but lacks the specific ``mode`` key
    (e.g. v1 legacy covers only mode 1 but we're running mode 2) falls
    through to heuristic rather than silently using another mode's
    pair — different modes can legitimately pair with different
    features (M247: PreWheel mode 1/2/5, LockReSpin mode 7).

    Returns ``(feature_name_or_None, source_string)``.
    """
    cfg = config or {}
    per_mode = cfg.get(machine)
    if isinstance(per_mode, dict) and mode in per_mode:
        return per_mode[mode], "config"
    tally = upstream_feature_tally or {}
    best_feat = None
    best_win = -1.0
    for feat, payouts in tally.items():
        if feat in PAID_NORMAL_FEATURES or feat == "BuffCollectionMap":
            continue
        if not isinstance(payouts, dict):
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


def collect_feature_match_warning(
    cycle_peaks: list[int],
    upstream_feature_tally: dict,
    resolved_feature: str | None,
    resolved_source: str,
) -> dict:
    """Summary block reporting the BCM-bonus-feature resolution.

    ``warning`` is non-None only when a cycle was observed AND neither
    the config nor the heuristic could identify a bonus feature. In
    that case RTP correction falls through to 0pp and the operator
    needs to either add a config entry or investigate the machine.

    Happy paths (warning is None):
      * cycle_peaks empty → no cycle observed in sample (separate
        ``cycle_observation`` block surfaces the "need more data"
        case; this block stays silent).
      * cycle_peaks non-empty AND resolved_feature is not None →
        pairing known, correction computable.
    """
    has_cycles = len(cycle_peaks) > 0
    features = sorted((upstream_feature_tally or {}).keys())
    warn = None
    if has_cycles and resolved_feature is None:
        warn = (
            "collect cycle detected (from BuffCollectionMap CC resets) "
            "but no bonus feature could be resolved for this machine. "
            "RTP correction will report 0pp which likely under-reports "
            "true RTP. Fix by either: (a) adding this machine to "
            "configs/bcm_pairings.json with the correct bonus_feature, "
            "or (b) resampling so the heuristic has non-zero win data "
            f"for the bonus channel. Features seen: {features!r}"
        )
    return {
        "applicable": has_cycles,
        "known_features": features,
        "bonus_feature": resolved_feature,
        "bonus_feature_source": resolved_source,
        "warning": warn,
    }


def build_cycle_observation(
    collect_robots_seen: int,
    cycle_peaks: list[int],
    final_cc_values: list[int],
) -> dict:
    """Surface the "collect mechanic present but cache too short to
    capture a cycle reset" case (M272-style: one chunk, all 10 robots
    ended exactly at CC=1000 without resetting).

    Without this block, the analyzer silently conflates "mechanic not
    present" with "mechanic present but under-sampled" — both come out
    as `cycle_peaks == []` and RTP correction gives 0pp. The warning
    here distinguishes the two so the operator knows to resume-sample
    rather than treat the current RTP as final.

    Fields:
      * mechanic_detected — ``collect_robots_seen > 0`` (robot's
        rounds carried CollectCount)
      * reset_observed — ``len(cycle_peaks) > 0`` (at least one CC
        reset event observed)
      * cycle_len_lower_bound — ``max(final_cc_values)`` when no reset;
        the cycle length is AT LEAST this (robots can't exceed it if
        they never reset, so the max-final-CC is a lower bound)
      * warning — non-None iff mechanic_detected AND NOT reset_observed
    """
    mechanic = collect_robots_seen > 0
    reset = len(cycle_peaks) > 0
    lower_bound = max(final_cc_values) if final_cc_values else None
    warn = None
    if mechanic and not reset:
        target = lower_bound * 2 if lower_bound else None
        warn = (
            f"collect mechanic detected (CollectCount field present on "
            f"{collect_robots_seen} robots) but no cycle reset observed "
            f"in this sample. Cycle length is at least {lower_bound} "
            f"(max final CC). RTP correction unavailable until resample "
            f"/ resume with ≥ {target} SpinTimes so at least one full "
            f"cycle completes + resets."
        )
    return {
        "mechanic_detected": mechanic,
        "reset_observed": reset,
        "cycle_len_lower_bound": lower_bound,
        "warning": warn,
    }


def aimd_tune(
    current_concurrency: int,
    current_chunk_spins: int,
    max_concurrency: int,
    max_chunk_spins: int,
    batch_fully_failed: bool,
    consecutive_successful: int,
) -> tuple[int, int, int, bool]:
    """Adjust concurrency + chunk_spins based on the latest batch
    outcome.

    Returns ``(new_concurrency, new_chunk_spins, new_consecutive_successful,
    should_pause)``.

    * Fully-failed batch → halve both (floor 1 / MIN_CHUNK_SPINS),
      reset success streak, signal to caller that it should pause
      CIRCUIT_PAUSE_S before the next submit (gives upstream breathing
      room).
    * Any success in the batch → increment success streak. After
      ``SUCCESS_STREAK_FOR_GROW`` consecutive clean batches, grow
      concurrency by 1 and chunk_spins by ``CHUNK_SPINS_GROWTH``
      (capped at the user's original values).

    Pure function so tests can walk through state transitions without
    having to run the analyzer loop.
    """
    if batch_fully_failed:
        new_conc = max(1, current_concurrency // 2)
        new_spins = max(MIN_CHUNK_SPINS, current_chunk_spins // 2)
        return (new_conc, new_spins, 0, True)
    # Any success: bump streak.
    new_success = consecutive_successful + 1
    new_conc = current_concurrency
    new_spins = current_chunk_spins
    if new_success >= SUCCESS_STREAK_FOR_GROW:
        new_conc = min(max_concurrency, current_concurrency + 1)
        new_spins = min(max_chunk_spins, int(current_chunk_spins * CHUNK_SPINS_GROWTH))
        new_success = 0
    return (new_conc, new_spins, new_success, False)


def post_json_with_retry(
    payload: dict[str, Any],
    timeout: float,
    max_attempts: int = 5,
    initial_backoff_s: float = 1.0,
    max_backoff_s: float = 30.0,
) -> Any:
    """Call post_json with exp-backoff on transient network errors.

    Retryable classes:
      * HTTPError with code in {500, 502, 503, 504}
      * URLError (DNS / connection refused / etc.)
      * TimeoutError / socket.timeout
      * http.client.IncompleteRead (truncated body mid-stream —
        typical of flaky proxies returning EOF prematurely)
      * http.client.RemoteDisconnected (connection closed before a
        response — typical of upstream load-balancer draining)
      * ConnectionError and its subclasses (ConnectionResetError,
        ConnectionAbortedError, BrokenPipeError, etc. — TCP-level
        resets from any intermediate hop)

    Previously IncompleteRead + ConnectionReset fell through to the
    caller's bare ``except Exception`` → zero retries → the chunk
    failed on first try regardless of transience. Combined with a
    3-attempt cap (1s+2s sleep only), a 15s upstream hiccup would
    kill an entire run.

    Backoff doubles each attempt (1s → 2s → 4s → 8s → 16s) but is
    capped at ``max_backoff_s`` so unbounded ``max_attempts`` can't
    produce multi-minute sleeps. Default 5 attempts with cap 30s =
    retry window of ~15s sleeps + HTTP time ≈ 20-30s wall clock.
    """
    import socket
    from http.client import IncompleteRead, RemoteDisconnected
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return post_json(payload, timeout)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code not in _RETRYABLE_HTTP_CODES:
                raise
        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            IncompleteRead,
            RemoteDisconnected,
            ConnectionError,
        ) as exc:
            last_exc = exc
        if attempt + 1 < max_attempts:
            delay = min(max_backoff_s, initial_backoff_s * (2 ** attempt))
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def t_critical_95(df: int) -> float:
    if df <= 0:
        return math.inf
    table = {
        1: 12.706,
        2: 4.303,
        3: 3.182,
        4: 2.776,
        5: 2.571,
        6: 2.447,
        7: 2.365,
        8: 2.306,
        9: 2.262,
        10: 2.228,
        20: 2.086,
        30: 2.042,
        40: 2.021,
        60: 2.000,
        120: 1.980,
        1000: 1.962,
    }
    if df in table:
        return table[df]
    points = sorted(table.items())
    if df < points[0][0]:
        return points[0][1]
    if df > points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= df <= x1:
            ratio = (df - x0) / (x1 - x0)
            return y0 + (y1 - y0) * ratio
    return 1.962


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


def session_halfwidth_pp(ret_count: int, ret_sum: float, ret_sq_sum: float) -> float | None:
    """Session-level CI half-width in pp. Uses per-session return
    multiplier (ret_x = session_win / session_bet) variance across
    N = ret_count sessions. Returns None when N ≤ 1 (undefined).

    Single authoritative CI across the codebase: the final summary and
    the in-loop stop check both call this. Chunk-level CI (above) is
    kept as a secondary diagnostic because it collapses to ~0 when
    early chunks coincidentally have similar RTPs — triggering false
    "target reached" breaks on high-variance machines whose TRUE CI
    is still wide.
    """
    if ret_count <= 1:
        return None
    var = max(
        0.0,
        (ret_sq_sum - (ret_sum * ret_sum / ret_count)) / (ret_count - 1),
    )
    if var == 0.0:
        return 0.0
    se = math.sqrt(var / ret_count)
    t = t_critical_95(ret_count - 1)
    return t * se * 100.0


def parse_rounds(robot: dict[str, Any]) -> list[dict[str, Any]]:
    rr = robot.get("roundResult")
    if not rr:
        return []
    if isinstance(rr, str):
        try:
            parsed = json.loads(rr)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return rr if isinstance(rr, list) else []


# Baseline round fields: the set of keys the analyzer knows how to
# interpret. Any field NOT in this set is tracked in extra_fields_seen
# so the report surfaces unknown / machine-specific data for future
# analyzer extensions. This list is intentionally stable — add a key
# here only AFTER writing the code that consumes it.
_BASELINE_ROUND_FIELDS = frozenset({
    "BetAmount", "CostCredits", "WinCredits", "SpinType", "SpinTimes",
    "RTPId", "IsLackCreditsSpin", "LastCredits", "CurJackpotStoreWin",
    "PayLineGroupId", "PayoutGroupId", "PayoutByPayline",
    "PayoutIdToWinAmount", "ReMarks", "ReelSkin",
    "StopSymbolsByCol", "RewardLastNode",
    # Collect-mechanic fields (consumed by cycle/trunk-clamp logic)
    "CollectCount", "AccCredits", "CreditsSymbols", "SymbolIndexToRewards",
})

# Round-level fields that MUST appear on every spin regardless of
# win / lose state. Missing one is almost certainly an upstream API
# field rename and the analyzer should fail loudly instead of silently
# producing all-zero metrics.
#
# Intentionally NOT in this set:
#   - PayoutByPayline: legitimately absent on lose spins (no payline).
#   - PayoutGroupId:   legitimately absent on no-payout spins.
#   The first round of a chunk is statistically very likely to be a
#   lose spin (RTP ~95% with hit_rate ~30% means ~70% lose), so
#   strict-checking these caused false-positive run aborts.
_REQUIRED_ROUND_FIELDS = (
    "WinCredits",
    "StopSymbolsByCol",
)
# Bet amount has a documented fallback chain (BetAmount -> CostCredits
# -> the chunk-level `bet` arg). The schema check still wants AT LEAST
# one of the first two to exist on a real round.
_REQUIRED_BET_FIELDS_ANY = ("BetAmount", "CostCredits")


def _check_round_schema(resp: list[Any]) -> list[str]:
    """Inspect the first parsed round of a chunk response and return the
    names of required fields that are missing. Returns [] when the
    schema is intact, or when there are no parsed rounds at all (the
    existing parse_failed_zero_chunk path handles the empty case).
    """
    if not isinstance(resp, list):
        return []
    for robot in resp:
        if not isinstance(robot, dict):
            continue
        rounds = parse_rounds(robot)
        for round_obj in rounds:
            if not isinstance(round_obj, dict):
                continue
            missing = [f for f in _REQUIRED_ROUND_FIELDS if f not in round_obj]
            if not any(f in round_obj for f in _REQUIRED_BET_FIELDS_ANY):
                missing.append("BetAmount|CostCredits")
            return missing
    return []


def parse_paylines(text: str) -> list[str]:
    if not text:
        return []
    return PAYLINE_RE.findall(text)


def split_symbols(col_text: str) -> list[str]:
    if not col_text:
        return []
    return [x for x in col_text.split("-") if x]


def quantile_from_hist(hist: dict[int, int], q: float) -> int:
    total = sum(hist.values())
    if total <= 0:
        return 0
    target = math.ceil(total * q)
    acc = 0
    for k in sorted(hist.keys()):
        acc += hist[k]
        if acc >= target:
            return k
    return max(hist.keys())


def safe_div(numerator: float, denominator: float) -> float:
    return (numerator / denominator) if denominator > 0 else 0.0


def append_jsonl(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _metric_path_get(payload: dict[str, Any], path: str) -> tuple[Any, bool]:
    cur: Any = payload
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return (None, False)
    return (cur, True)


def _eval_operator(observed: Any, operator: str, target: Any) -> bool:
    if observed is None and operator in ("<", "<=", ">", ">=", "between"):
        return False
    try:
        if operator == "<":
            return observed < target
        if operator == "<=":
            return observed <= target
        if operator == ">":
            return observed > target
        if operator == ">=":
            return observed >= target
        if operator == "==":
            return observed == target
        if operator == "!=":
            return observed != target
        if operator == "between":
            if not isinstance(target, dict):
                return False
            low = target.get("min")
            high = target.get("max")
            if low is None or high is None:
                return False
            return low <= observed <= high
    except TypeError:
        return False
    raise ValueError(f"unsupported operator: {operator}")


def _deviation(observed: Any, operator: str, target: Any) -> float | None:
    if not isinstance(observed, (int, float)):
        return None
    if operator in ("<", "<=") and isinstance(target, (int, float)):
        return float(observed - target)
    if operator in (">", ">=") and isinstance(target, (int, float)):
        return float(target - observed)
    if operator == "between" and isinstance(target, dict):
        low = target.get("min")
        high = target.get("max")
        if isinstance(low, (int, float)) and observed < low:
            return float(low - observed)
        if isinstance(high, (int, float)) and observed > high:
            return float(observed - high)
        return 0.0
    return 0.0


def evaluate_guideline_comparison(summary: dict[str, Any], rules_path: Path) -> dict[str, Any]:
    if not rules_path.exists():
        return {
            "guideline_id": "unknown",
            "rules_path": str(rules_path),
            "overall_status": "ERROR",
            "error": "rules_file_not_found",
            "checks": [],
        }
    try:
        rules_payload = json.loads(rules_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "guideline_id": "unknown",
            "rules_path": str(rules_path),
            "overall_status": "ERROR",
            "error": "rules_json_parse_failed",
            "checks": [],
        }

    checks = rules_payload.get("checks", [])
    if not isinstance(checks, list):
        return {
            "guideline_id": rules_payload.get("guideline_id", "unknown"),
            "rules_path": str(rules_path),
            "overall_status": "ERROR",
            "error": "rules_checks_not_list",
            "checks": [],
        }

    results: list[dict[str, Any]] = []
    pass_count = 0
    fail_count = 0
    na_count = 0
    missing_count = 0
    for check in checks:
        if not isinstance(check, dict):
            continue
        row = {
            "id": check.get("id", "UNKNOWN"),
            "section": check.get("section", "General"),
            "severity": check.get("severity", "medium"),
            "description": check.get("description", ""),
            "path": check.get("path", ""),
            "operator": check.get("operator", ""),
            "target": check.get("target"),
            "status": "missing",
        }
        when = check.get("when")
        if isinstance(when, dict):
            when_path = str(when.get("path", ""))
            when_op = str(when.get("operator", "=="))
            when_target = when.get("target")
            when_observed, when_ok = _metric_path_get(summary, when_path)
            row["when"] = {
                "path": when_path,
                "operator": when_op,
                "target": when_target,
                "observed": when_observed if when_ok else None,
            }
            if not when_ok:
                row["status"] = "missing"
                row["error"] = f"missing_when_path:{when_path}"
                missing_count += 1
                results.append(row)
                continue
            try:
                when_passed = _eval_operator(when_observed, when_op, when_target)
            except Exception as exc:  # noqa: BLE001
                row["status"] = "missing"
                row["error"] = f"when_eval_error:{exc.__class__.__name__}"
                missing_count += 1
                results.append(row)
                continue
            if not when_passed:
                row["status"] = "not_applicable"
                na_count += 1
                results.append(row)
                continue

        path = str(check.get("path", ""))
        operator = str(check.get("operator", "=="))
        target = check.get("target")
        observed, found = _metric_path_get(summary, path)
        if not found:
            row["status"] = "missing"
            row["error"] = f"missing_path:{path}"
            missing_count += 1
            results.append(row)
            continue
        row["observed"] = observed
        try:
            passed = _eval_operator(observed, operator, target)
        except Exception as exc:  # noqa: BLE001
            row["status"] = "missing"
            row["error"] = f"eval_error:{exc.__class__.__name__}"
            missing_count += 1
            results.append(row)
            continue
        row["deviation"] = _deviation(observed, operator, target)
        if passed:
            row["status"] = "pass"
            pass_count += 1
        else:
            row["status"] = "fail"
            fail_count += 1
        results.append(row)

    hard_fail_count = sum(1 for r in results if r.get("status") == "fail" and r.get("severity") == "high")
    overall_status = "FAIL" if (fail_count > 0 or missing_count > 0) else "PASS"
    return {
        "guideline_id": rules_payload.get("guideline_id", "unknown"),
        "rules_path": str(rules_path),
        "evaluated_at": utc_now(),
        "overall_status": overall_status,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "not_applicable_count": na_count,
        "missing_count": missing_count,
        "hard_fail_count": hard_fail_count,
        "check_count": len(results),
        "failed_check_ids": [r.get("id") for r in results if r.get("status") == "fail"],
        "checks": results,
    }


def classify_volatility(zero_win_rate: float, loss_streak_p95: int, tail_dependency: float) -> str:
    if zero_win_rate > 0.82 or loss_streak_p95 > 18 or tail_dependency > 0.50:
        return "Very High"
    if zero_win_rate >= 0.75 or loss_streak_p95 >= 13 or tail_dependency >= 0.35:
        return "High"
    if zero_win_rate >= 0.65 or loss_streak_p95 >= 9 or tail_dependency >= 0.20:
        return "Medium"
    return "Low"


def classify_experience_archetype(
    zero_win_rate: float,
    big_win_x10_rate: float,
    tail_dependency: float,
    profit_spin_rate: float,
) -> str:
    if zero_win_rate >= 0.75 and tail_dependency >= 0.35 and big_win_x10_rate >= 0.015:
        return "Boom-Bust"
    if zero_win_rate >= 0.75 and big_win_x10_rate < 0.015:
        return "Grindy"
    if zero_win_rate < 0.75 and 0.08 <= profit_spin_rate <= 0.16 and tail_dependency < 0.35:
        return "Balanced"
    if zero_win_rate >= 0.78:
        return "Grindy"
    return "Balanced"


def blank_like_symbol(symbol: str) -> bool:
    s = symbol.lower()
    return ("blank" in s) or ("empty" in s) or (s == "none")


# ReMarks annotation parsers. M272 bonus rounds carry strings like:
#   "Freespin 18; CollectCount:64; AddCollectCount:6; ExtraRatio:200; "
#   "Freespin 19; CollectCount:68; AddCollectCount:4; ExtraRatio:200; AddFreespins; 1"
# which tell us (a) that this round is inside a bonus chain, (b) what
# multiplier the chain is currently at, and (c) whether it self-
# retriggered. All three drive the bonus_chain_dynamics surface.
# Machines without this field (M14) silently skip -- parse returns None.
_REMARKS_FREESPIN_RE = re.compile(r"Freespin\s+(\d+)")
_REMARKS_EXTRARATIO_RE = re.compile(r"ExtraRatio:(\d+)")
_REMARKS_ADDFREESPINS_COUNT_RE = re.compile(r"AddFreespins;\s*(\d+)")


def parse_freespin_remarks(remarks: Any) -> dict[str, Any] | None:
    """Return freespin annotation metadata, or None if the string is
    not a freespin line. Tolerant of missing fields -- extra_ratio
    defaults to 100 (the baseline ratio observed in M272 early chain).
    """
    if not isinstance(remarks, str) or "Freespin" not in remarks:
        return None
    m_fs = _REMARKS_FREESPIN_RE.search(remarks)
    if not m_fs:
        return None
    try:
        fs_idx = int(m_fs.group(1))
    except ValueError:
        return None
    m_er = _REMARKS_EXTRARATIO_RE.search(remarks)
    extra_ratio = 100
    if m_er:
        try:
            extra_ratio = int(m_er.group(1))
        except ValueError:
            pass
    m_af = _REMARKS_ADDFREESPINS_COUNT_RE.search(remarks)
    retrigger_count = 0
    if m_af:
        try:
            retrigger_count = int(m_af.group(1))
        except ValueError:
            pass
    return {
        "freespin_index": fs_idx,
        "extra_ratio": extra_ratio,
        "has_retrigger": "AddFreespins" in remarks,
        "retrigger_count": retrigger_count,
    }


def bonus_chain_depth_bucket(fs_idx: int) -> str:
    """Bucket a freespin index into a small depth class so the
    bonus_chain_dynamics extra_ratio_by_depth curve stays compact."""
    if fs_idx <= 1:
        return "1"
    if fs_idx <= 5:
        return "2-5"
    if fs_idx <= 10:
        return "6-10"
    if fs_idx <= 20:
        return "11-20"
    return "21+"


def _compute_bonus_correction(
    bonus_feature: str | None,
    cycle_peaks: list[int],
    final_cc_values: list[int],
    feature_tally: dict[str, dict[str, dict[str, Any]]],
    completed_cycles: int,
    total_paid_bet: float,
) -> float | None:
    """Estimate the RTP correction (in pp) from truncated collect-cycle
    bonus rounds.

    Each robot that ends mid-cycle (final_cc < cycle_length) has lost
    a fraction of the expected bonus payout that would fire at cycle
    completion. The correction is:
        sum across robots of (progress_fraction × avg_bonus_payout)
        / total_paid_bet × 100

    ``bonus_feature`` is the resolved FeatureWin key for this machine
    (from _resolve_bonus_feature — config override or heuristic).
    Returns None when:
      - bonus_feature could not be resolved (None)
      - no cycles observed
      - no completed cycles (resets yes, but sample too small)
      - resolved feature has zero observed win

    Previously hardcoded to "NewFreespin"; that worked for ~13 of 33
    BCM machines and silently under-reported RTP on the other 20.
    """
    if bonus_feature is None:
        return None
    if not cycle_peaks or total_paid_bet <= 0:
        return None
    cycle_len = int(sorted(cycle_peaks)[len(cycle_peaks) // 2])
    if cycle_len <= 0:
        return None
    bonus_total_win = sum(
        float(e.get("win", 0.0))
        for e in (feature_tally.get(bonus_feature) or {}).values()
    )
    if completed_cycles <= 0 or bonus_total_win <= 0:
        return None
    avg_bonus_payout = bonus_total_win / completed_cycles
    total_lost = 0.0
    for fcc in final_cc_values:
        progress = min(fcc / cycle_len, 1.0)
        if progress < 1.0:
            total_lost += progress * avg_bonus_payout
    return (total_lost / total_paid_bet) * 100.0


# Backwards-compat alias for any external caller still using the old
# name. New code should use `_compute_bonus_correction` and pass the
# resolved feature explicitly.
def _compute_nf_correction(
    cycle_peaks: list[int],
    final_cc_values: list[int],
    feature_tally: dict[str, dict[str, dict[str, Any]]],
    completed_cycles: int,
    total_paid_bet: float,
) -> float | None:
    return _compute_bonus_correction(
        "NewFreespin", cycle_peaks, final_cc_values,
        feature_tally, completed_cycles, total_paid_bet,
    )


def parse_rln_codes(rln: Any) -> list[str]:
    """RewardLastNode values look like ['3-', '7-', '668-'] -- numeric
    symbol codes with a trailing '-' separator. Upstream populates this
    on most winning spins (M14 + M272 both use it). Returning the
    stripped codes lets the paylines drilldown credit winning symbols
    directly instead of relying on the left-3-col intersection heuristic.
    """
    if not isinstance(rln, list):
        return []
    out: list[str] = []
    for item in rln:
        s = str(item).strip()
        if s.endswith("-"):
            s = s[:-1]
        s = s.strip()
        if s:
            out.append(s)
    return out


def make_payload(
    machine: str,
    rtp_mode: int,
    bet: int,
    spin_times: int,
    robot_count: int,
    init_credits: int,
    reset_each_spin: bool,
    continue_after_bankrupt: bool,
) -> dict[str, Any]:
    return {
        "MachineName": machine,
        "InitCreditsStr": str(init_credits),
        "BetStrategy": 0,
        "BetOriginStr": str(bet),
        "SpinTimes": int(spin_times),
        "RtpId": int(rtp_mode),
        "ShouldTestLuckyGame": False,
        "ContinueAfterBankrupt": bool(continue_after_bankrupt),
        "ResetPlayerStateAfterEachSpin": bool(reset_each_spin),
        "RobotCount": int(robot_count),
        "OutputAllRobotResult": True,
    }


def return_bucket(ret_x: float) -> str:
    # Zero-win sessions return "eq0" so the internal bet/win/spin
    # accumulators keep correct totals (session_bet_sum, mb_total_bet,
    # tail calculations all derive from bucket sums). The eq0 key is
    # NOT in RETURN_BUCKET_ORDER, so build_multiplier_bucket_rows()
    # skips it when building the output rows -- the user never sees a
    # zero-info bucket in the chart.
    if ret_x <= 0.0:
        return "eq0"
    if ret_x < 1.0:
        return "gt0_lt1"
    if ret_x < 5.0:
        return "ge1_lt5"
    if ret_x < 10.0:
        return "ge5_lt10"
    if ret_x < 20.0:
        return "ge10_lt20"
    if ret_x < 50.0:
        return "ge20_lt50"
    if ret_x < 100.0:
        return "ge50_lt100"
    if ret_x < 200.0:
        return "ge100_lt200"
    if ret_x < 500.0:
        return "ge200_lt500"
    if ret_x < 1000.0:
        return "ge500_lt1000"
    if ret_x < 5000.0:
        return "ge1000_lt5000"
    return "ge5000"


def build_multiplier_bucket_rows(
    bucket_spins: dict[str, int],
    bucket_bet: dict[str, float],
    bucket_win: dict[str, float],
    total_spins: int,
    total_bet: float,
    total_win: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label in RETURN_BUCKET_ORDER:
        spin_count = int(bucket_spins.get(label, 0))
        bet_sum = float(bucket_bet.get(label, 0.0))
        win_sum = float(bucket_win.get(label, 0.0))
        rows.append(
            {
                "bucket": label,
                "spin_count": spin_count,
                "spin_rate": (spin_count / total_spins) if total_spins > 0 else 0.0,
                "avg_return_x_in_bucket": (win_sum / bet_sum) if bet_sum > 0 else 0.0,
                "rtp_contribution_pp": (win_sum / total_bet) * 100.0 if total_bet > 0 else 0.0,
                "win_share": (win_sum / total_win) if total_win > 0 else 0.0,
            }
        )
    return rows


# Cache envelope version. Bumped when the wrapping envelope changes
# (not when analyzer code changes -- raw API data is analyzer-agnostic).
CHUNK_CACHE_VERSION = 3  # v3: added _payload_sha256 + atomic (.tmp+os.replace) write


class ChunkIntegrityError(ValueError):
    """Envelope's stored _payload_sha256 didn't match the recomputed hash.

    Indicates the chunk file is corrupt (partial write from an aborted
    sampler, disk error, filesystem glitch) or was modified after write.
    Distinct from json.JSONDecodeError, which means the envelope itself
    is malformed — this one means the envelope parses cleanly but the
    payload bytes have drifted from what was written.
    """


def _canonical_payload_bytes(resp: Any) -> bytes:
    """Deterministic byte encoding of the cached response for hashing.

    `sort_keys=True` + no whitespace + `ensure_ascii=False` makes the
    writer and reader compute identical bytes regardless of dict key
    order, indent, or non-ASCII handling.
    """
    return json.dumps(
        resp, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _payload_sha256(resp: Any) -> str:
    import hashlib
    return hashlib.sha256(_canonical_payload_bytes(resp)).hexdigest()


def load_chunk_envelope(path: Path) -> dict:
    """Load a chunk cache file and validate `_payload_sha256` if present.

    v3+ envelopes carry a payload sha256; mismatch raises
    ChunkIntegrityError with a readable message so the caller can
    surface "this chunk is corrupt" instead of a generic decode error.
    Legacy v2 envelopes without `_payload_sha256` are accepted as-is
    (backwards compatible — existing 4000 cached chunks keep working).
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    stored_sha = raw.get("_payload_sha256")
    if stored_sha:
        actual_sha = _payload_sha256(raw.get("response"))
        if actual_sha != stored_sha:
            raise ChunkIntegrityError(
                f"chunk {path.name}: payload sha256 mismatch "
                f"(envelope={stored_sha[:16]}..., actual={actual_sha[:16]}...) — "
                f"file is corrupt or was modified after write"
            )
    return raw


def _compute_upstream_schema_fingerprint(resp: Any) -> str | None:
    """Compute a deterministic fingerprint of the upstream round schema.

    Takes the sorted key set from the first robot's first round and
    hashes it. If the upstream renames / adds / removes a field, the
    hash changes → cached data is flagged as incompatible.

    Returns None when the response doesn't contain parseable rounds
    (broken data — shouldn't normally happen).
    """
    import hashlib
    try:
        for robot in resp if isinstance(resp, list) else []:
            if not isinstance(robot, dict):
                continue
            rr = robot.get("roundResult")
            if not isinstance(rr, str):
                continue
            rounds = json.loads(rr)
            if not isinstance(rounds, list) or not rounds:
                continue
            first_round = rounds[0]
            if not isinstance(first_round, dict):
                continue
            keys = sorted(first_round.keys())
            return hashlib.sha256("|".join(keys).encode()).hexdigest()[:16]
    except (json.JSONDecodeError, TypeError, AttributeError, ValueError):
        # Data-level: malformed upstream response shape. Fingerprint is
        # best-effort diagnostic, not correctness-critical; fall through.
        pass
    return None


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


def _lookup_machine_md5(machine: str) -> tuple[str, str]:
    """Look up (config_md5, code_md5) for a machine from configs/machines.json.

    Returns ("", "") if not found — the envelope stores empty strings so
    the file is still valid but MD5 verification is effectively disabled.
    """
    try:
        cfg_path = Path(__file__).resolve().parent.parent / "configs" / "machines.json"
        if not cfg_path.exists():
            return "", ""
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        for m in data.get("machines", []):
            if m.get("machine") == machine:
                return (
                    str(m.get("configSummaryMd5", "")),
                    str(m.get("codeSummaryMd5", "")),
                )
    except (OSError, json.JSONDecodeError, TypeError):
        # Data-level: missing / malformed machines.json. MD5 tagging is
        # best-effort; reports stay valid without it.
        pass
    return "", ""


def _save_chunk_cache(
    resp: Any,
    chunk_index: int,
    machine: str,
    rtp_mode: int,
    bet: int,
    spin_times: int,
    robot_count: int,
    cache_dir: Path | None,
) -> None:
    """Best-effort atomic write of the raw API response to a cache file.

    Writes to `chunk_NNNN.json.tmp` first, then `os.replace` to the
    final path. This guarantees the reader never sees a half-written
    file — either the full new chunk is present or the previous (or
    nothing) is. Payload sha256 is stamped in the envelope so later
    reads can detect silent corruption from e.g. disk block errors.

    Silent on failure so a disk-full or permissions error doesn't abort
    the sampling run. Leftover `.tmp` files (from a failed replace) are
    cleaned up on the way out to avoid accumulating garbage.
    """
    if cache_dir is None:
        return
    out_path = cache_dir / f"chunk_{chunk_index:04d}.json"
    tmp_path = cache_dir / f"chunk_{chunk_index:04d}.json.tmp"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        config_md5, code_md5 = _lookup_machine_md5(machine)
        envelope = {
            "_cache_version": CHUNK_CACHE_VERSION,
            "_machine": machine,
            "_mode": rtp_mode,
            "_bet": bet,
            "_spin_times": spin_times,
            "_robot_count": robot_count,
            "_chunk_index": chunk_index,
            "_saved_at": utc_now(),
            "_config_md5": config_md5,
            "_code_md5": code_md5,
            "_upstream_schema_fingerprint": _compute_upstream_schema_fingerprint(resp),
            "_payload_sha256": _payload_sha256(resp),
            "response": resp,
        }
        tmp_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, out_path)
        # Update the rawdata index so UI reads stay O(1). Best-effort:
        # failure here only means the next UI status refresh falls back
        # to a filesystem scan (which self-heals the index).
        try:
            from fresh_slotlab.rawdata_index import update_entry
            # cache_dir is `<rawdata_root>/<machine>/mode_<N>`; the index
            # lives at `<rawdata_root>/_index.json`.
            rawdata_root = cache_dir.parent.parent
            update_entry(rawdata_root, machine, rtp_mode, cache_dir)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        # Clean up a stale .tmp so we don't accumulate partials from
        # repeated failures. The final chunk file (if any) is left
        # untouched — a successful prior write stays valid.
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def run_sampling_chunk(
    chunk_index: int,
    machine: str,
    rtp_mode: int,
    bet: int,
    spin_times: int,
    robot_count: int,
    timeout: float,
    chunk_cache_dir: Path | None = None,
) -> dict[str, Any]:
    payload = make_payload(
        machine=machine,
        rtp_mode=rtp_mode,
        bet=bet,
        spin_times=spin_times,
        robot_count=robot_count,
        init_credits=10**14,
        reset_each_spin=True,
        continue_after_bankrupt=True,
    )

    started = time.time()
    try:
        # Wrapped with retry so one 5xx / transient timeout doesn't
        # kill an overnight long-sample run. Non-retryable errors
        # (4xx, etc.) still propagate on first occurrence.
        resp = post_json_with_retry(payload, timeout)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "index": chunk_index, "error": f"request_failed_http_{exc.code}"}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {
            "ok": False,
            "index": chunk_index,
            "error": f"request_failed_network_{exc.__class__.__name__}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "index": chunk_index,
            "error": f"request_failed_{exc.__class__.__name__}",
        }

    # Persist the raw API response before ANY parsing so offline rebuild
    # always has untouched upstream data. Best-effort: disk failure is
    # silent (the run proceeds; the operator just can't rebuild later).
    _save_chunk_cache(
        resp, chunk_index, machine, rtp_mode, bet, spin_times, robot_count, chunk_cache_dir,
    )

    return parse_chunk_response(resp, chunk_index, bet, started)


def parse_chunk_response(
    resp: Any,
    chunk_index: int,
    bet: int,
    started: float | None = None,
) -> dict[str, Any]:
    """Parse a raw API response (list of robot dicts) into chunk metrics.

    This is the pure-computation core of the analyzer: no network, no
    disk I/O. ``run_sampling_chunk`` calls it after fetching + caching;
    the ``--from-cache`` path calls it directly with data loaded from
    chunk-cache JSON files.

    ``started`` is an optional ``time.time()`` value used only for
    elapsed_seconds in the result dict.
    """
    if started is None:
        started = time.time()

    # Top-level shape sanity. Different machines can return slightly
    # different envelopes (M14 returns list-of-robots, exploratory probes
    # of new machines have surfaced single-dict variants). Catch and
    # report explicitly so the operator can ask us to add support for the
    # new shape rather than seeing silent all-zero data. The downstream
    # code path assumes resp is a non-empty list of robot dicts.
    if not isinstance(resp, list):
        sample_keys = list(resp.keys())[:6] if isinstance(resp, dict) else None
        detail = (
            f"got_dict_keys={sample_keys}"
            if sample_keys is not None
            else f"got_type={type(resp).__name__}"
        )
        return {
            "ok": False,
            "index": chunk_index,
            "error": f"response_shape_unexpected:expected_list:{detail}",
        }
    if not resp:
        return {"ok": False, "index": chunk_index, "error": "parse_failed_empty_response"}
    if not any(isinstance(robot, dict) for robot in resp):
        item_types = sorted({type(item).__name__ for item in resp[:5]})
        return {
            "ok": False,
            "index": chunk_index,
            "error": f"response_shape_unexpected:expected_robot_dicts:item_types={item_types}",
        }

    # Capture the server-side analysisResult for cross-check. Each robot's
    # analysisResult is a string-encoded JSON {"TotalWin", "FeatureWin",
    # "SummaryWin"} where TotalWin maps payout_id -> {WinCredits, ...,
    # Times}. Summing WinCredits across all keys yields the server's view
    # of total credits won this chunk; compared against our parsed
    # chunk_win it surfaces any drift between our aggregator and the
    # upstream's. Best-effort: any malformed analysisResult is skipped
    # (no crash; the sanity check just won't include that robot).
    #
    # FeatureWin is also parsed here: it's a dict keyed by the upstream
    # feature name (a *string* like "Normal" / "NormalCollectionSpin" /
    # "NewFreespin") -- different from the round-level SpinType int --
    # with each entry a dict of {payout_id: {WinCredits, Times, ...}}.
    # This is authoritative upstream bonus-mechanic attribution: for
    # M272 it separates the MapCollection feature (NormalCollectionSpin,
    # triggered by PayId 666 among others) from the NewFreespin feature.
    # We aggregate per (feature, payout_id) so the summary can surface
    # "which bonus chains contribute how much RTP".
    upstream_chunk_total_win = 0.0
    upstream_chunk_robots_seen = 0
    # feature_name -> {payout_id (str) -> {"win": float, "times": int}}
    feature_chunk_tally: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"win": 0.0, "times": 0})
    )
    for robot in resp:
        if not isinstance(robot, dict):
            continue
        ar = robot.get("analysisResult")
        if not isinstance(ar, str):
            continue
        try:
            parsed = json.loads(ar)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        tw = parsed.get("TotalWin")
        if isinstance(tw, str):
            try:
                tw = json.loads(tw)
            except (json.JSONDecodeError, TypeError, ValueError):
                tw = None
        if isinstance(tw, dict):
            upstream_chunk_robots_seen += 1
            for v in tw.values():
                if isinstance(v, dict):
                    upstream_chunk_total_win += to_float(v.get("WinCredits"), default=0.0)
        fw = parsed.get("FeatureWin")
        if isinstance(fw, str):
            try:
                fw = json.loads(fw)
            except (json.JSONDecodeError, TypeError, ValueError):
                fw = None
        if isinstance(fw, dict):
            for feat_name, feat_payouts in fw.items():
                if not isinstance(feat_payouts, dict):
                    continue
                for pid, entry in feat_payouts.items():
                    if not isinstance(entry, dict):
                        continue
                    pid_str = str(pid)
                    feature_chunk_tally[str(feat_name)][pid_str]["win"] += to_float(
                        entry.get("WinCredits"), default=0.0
                    )
                    try:
                        feature_chunk_tally[str(feat_name)][pid_str]["times"] += int(
                            entry.get("Times", 0) or 0
                        )
                    except (TypeError, ValueError):
                        pass

    # Schema sanity check on the first non-empty round. Without this, an
    # upstream field rename (e.g. WinCredits -> winCredits) would slip
    # through every .get(default=0) fallback in the parsing loop and
    # silently produce all-zero metrics. _watch_run will surface the
    # "schema_drift_missing_fields:..." reason in error_message so the
    # operator sees exactly which field went missing.
    schema_missing = _check_round_schema(resp)
    if schema_missing:
        return {
            "ok": False,
            "index": chunk_index,
            "error": "schema_drift_missing_fields:" + ",".join(schema_missing),
        }

    # --- Pre-scan: detect if CostCredits is unreliable for this chunk.
    # Some machines (M10, M23, M131, M133 — LockReSpin SpinType 13) report
    # CostCredits=0 on ALL spins even though BetAmount>0. For these, the
    # CostCredits-based paid/bonus classification fails. Detect by sampling
    # the first robot: if every round has CostCredits==0 but BetAmount>0,
    # treat ALL spins as paid (the machine has no meaningful free-spin
    # distinction).
    cost_credits_unreliable = False
    _sample_robot = next((r for r in resp if isinstance(r, dict)), None)
    if _sample_robot is not None:
        _sample_rounds = parse_rounds(_sample_robot)
        if _sample_rounds:
            _all_zero_cost = all(
                to_float(rd.get("CostCredits"), default=-1.0) == 0.0
                for rd in _sample_rounds[:200]
                if isinstance(rd, dict)
            )
            _any_positive_bet = any(
                to_float(rd.get("BetAmount"), default=0.0) > 0.0
                for rd in _sample_rounds[:200]
                if isinstance(rd, dict)
            )
            cost_credits_unreliable = _all_zero_cost and _any_positive_bet

    # --- Extra-field discovery: track fields beyond _BASELINE_ROUND_FIELDS.
    extra_fields_seen: dict[str, int] = defaultdict(int)

    # --- Per-machine mechanic accumulators (only populated when the
    #     corresponding fields are present in the spin data). ---
    # LockLines: count of spins with lock, total lock lines triggered.
    lock_lines_spins = 0
    lock_lines_total_lines = 0
    lock_lines_win = 0.0
    # LockSymbols: count of spins with lock symbols, unique symbols seen.
    lock_symbols_spins = 0
    lock_symbols_unique: set[str] = set()
    lock_symbols_win = 0.0
    # JackpotIds: count of spins with jackpot trigger, jackpot win total.
    jackpot_spins = 0
    jackpot_ids_seen: set[str] = set()
    jackpot_win = 0.0
    # LockReels: reel-level locking.
    lock_reels_spins = 0
    lock_reels_win = 0.0
    # FreeSpin tracking: AddFreeSpin retriggers, chain length via CurFreeSpin.
    freespin_chain_spins = 0
    freespin_retriggers = 0
    freespin_max_chain = 0
    freespin_win = 0.0
    # Dollar Pick mechanic.
    dollar_pick_spins = 0
    dollar_pick_total_dollars = 0
    dollar_pick_win = 0.0

    chunk_spins = 0
    chunk_bet = 0.0
    chunk_win = 0.0

    ret_count = 0
    ret_sum = 0.0
    ret_sq_sum = 0.0
    max_return_x = 0.0

    # --- Spin-level counters (kept for back-compat + for surfaces that
    #     are legitimately spin-level, like symbols / spin_type breakdown).
    win_spins = 0
    loss_spins = 0
    profit_spins = 0
    breakeven_or_more_spins = 0
    big_win_x10_spins = 0
    win_sum = 0.0
    lack_credit_spins = 0
    multiplier_bucket_spins: dict[str, int] = defaultdict(int)
    multiplier_bucket_bet: dict[str, float] = defaultdict(float)
    multiplier_bucket_win: dict[str, float] = defaultdict(float)
    loss_streak_hist: dict[int, int] = defaultdict(int)
    win_streak_hist: dict[int, int] = defaultdict(int)
    max_loss_streak = 0
    max_win_streak = 0

    # --- Session-level counters (one "session" = a paid spin + every
    #     bonus / free-spin that follows it, until the next paid spin or
    #     the end of this robot's rounds). These drive the summary's
    #     hit_and_payout / multiplier_profile / streaks / volatility so
    #     the operator sees a player-perspective RTP profile (bonus wins
    #     attributed back to the paid spin that triggered them) instead
    #     of a per-spin tally that dilutes hit_rate with bonus chains.
    #     Paid vs bonus is detected by CostCredits > 0 (robust: a paid
    #     spin costs the player, a bonus free-spin doesn't).
    paid_session_count = 0
    session_win_count = 0
    session_lose_count = 0
    session_profit_count = 0
    session_breakeven_count = 0
    session_big_win_x10_count = 0
    session_ret_count = 0
    session_ret_sum = 0.0
    session_ret_sq_sum = 0.0
    session_max_return_x = 0.0
    session_win_sum = 0.0
    session_bucket_spins: dict[str, int] = defaultdict(int)
    session_bucket_bet: dict[str, float] = defaultdict(float)
    session_bucket_win: dict[str, float] = defaultdict(float)
    session_loss_streak_hist: dict[int, int] = defaultdict(int)
    session_win_streak_hist: dict[int, int] = defaultdict(int)
    session_max_loss_streak = 0
    session_max_win_streak = 0
    # Stats about bonus-spin chain length (operator curiosity; not used
    # in any derived metric here, but cheap to carry).
    bonus_spin_count = 0

    payline_hits: dict[str, int] = defaultdict(int)
    payline_win_approx: dict[str, float] = defaultdict(float)
    symbol_counts: dict[str, int] = defaultdict(int)
    symbol_counts_by_col: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total_symbol_slots = 0

    # Per-PayoutGroupId tally. Both M14 and M272 mode 1/2 always return
    # PayoutGroupId=0 in practice (the field doesn't differentiate), so
    # the drilldown built from this is informationally empty; kept for
    # backward compat in case other modes / machines actually fill it.
    payout_group_hits: dict[int, int] = defaultdict(int)
    payout_group_win: dict[int, float] = defaultdict(float)

    # Per-PayoutId tally from PayoutIdToWinAmount. This is the actual
    # payout-source breakdown the operator wants ("PayoutId 1 contributes
    # 73% of RTP via 333,300 win"). Both M14 and M272 winning rounds
    # populate it (unlike PayoutGroupId which is always 0). hit_count
    # increments per (round, payout_id) appearance, win sums the amount.
    payout_id_hits: dict[str, int] = defaultdict(int)
    payout_id_win: dict[str, float] = defaultdict(float)

    # Per-SpinType tally. M14 mode 1 only emits SpinType=1 (Normal).
    # M272 mode 1 emits 140 (main) + 126 (collect/bonus re-spin); mode
    # 2 has ~36% bonus rounds. Tallying per type lets the drilldown show
    # how much of total RTP comes from main vs bonus, and what fraction
    # of round volume is bonus -- a key insight for collect-mechanic
    # machines that the aggregate RTP / hit_rate alone can't reveal.
    #
    # Two separate bet tallies so the UI can draw an honest per-type
    # RTP: spin_type_bet sums the face BetAmount (mostly for reference)
    # while spin_type_paid_bet sums only CostCredits>0 amounts (the
    # actual player-paid cost). For free-spin types, paid_bet is 0 and
    # a real per-type RTP is undefined -- their wins belong to the
    # triggering session anyway. spin_type_paid_rounds counts
    # is_paid=True rounds so the UI can derive a behavioral label
    # (paid / free / mixed) without hardcoding machine-specific
    # SpinType semantics.
    spin_type_spins: dict[int, int] = defaultdict(int)
    spin_type_bet: dict[int, float] = defaultdict(float)
    spin_type_paid_bet: dict[int, float] = defaultdict(float)
    spin_type_win: dict[int, float] = defaultdict(float)
    spin_type_wins: dict[int, int] = defaultdict(int)  # count of winning rounds per type
    spin_type_paid_rounds: dict[int, int] = defaultdict(int)  # CostCredits>0 rounds per type
    # SpinType chain transitions: spin_type_next_counts[from][to] is
    # the count of rounds where SpinType=from was immediately followed
    # (same robot, next round) by SpinType=to. Used in _finalize to
    # infer trigger-only feature → paying-feature chain parents:
    # when feature F fires at SpinType st_F, what SpinType typically
    # comes next? That next SpinType's feature is F's chain parent.
    spin_type_next_counts: dict[int, Counter] = defaultdict(Counter)
    # Sample ReMarks strings per SpinType (up to 3 per type). Many
    # machines encode the feature name verbatim in ReMarks (e.g.
    # M273 SpinType=136 → "WheelSelector", SpinType=137 → "PreWheel").
    # This gives us a substring signal in _finalize to disambiguate
    # SpinType↔feature_name mapping when multiple features share the
    # same fire count. Rounds with empty ReMarks are skipped.
    spin_type_remarks_sample: dict[int, list[str]] = defaultdict(list)
    # Bonus-chain trigger-path summary. Keyed by
    # (first_st, entry_cc_reset, sp_type_within_chain). Each value is
    # {"count": int, "win": float, "bet": float}. Used in _finalize
    # to derive per-feature sub_streams — same feature may fire in
    # chains entered through different paths (e.g. M273
    # LockSymbolFreespin entered via the wheel ceremony vs via a BCM
    # CollectCount cycle reset). Operators want those stats split
    # because initial state (ReelSkin / paytable / etc.) may differ.
    chain_chunk_summaries: dict[tuple, dict[str, float]] = defaultdict(
        lambda: {"count": 0, "win": 0.0, "bet": 0.0}
    )
    # Per-SpinType × return-bucket histograms. Mirror the global
    # ``multiplier_bucket_{spins,bet,win}`` but keyed by SpinType so
    # the upstream feature breakdown can surface a per-feature bucket
    # distribution (the pay_id-level share bar is too granular for
    # operators to read — bucket histogram is the useful grain).
    spin_type_bucket_spins: dict[int, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    spin_type_bucket_bet: dict[int, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    spin_type_bucket_win: dict[int, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    # Per-chain-path × return-bucket histograms. Keyed by
    # (first_st, cc_reset, sp_type) — same key as chain_chunk_summaries
    # — so the upstream feature breakdown can render bucket
    # distributions PER trigger path (user feedback 2026-04-19: the
    # global per-SpinType bucket was shared across paths, masking the
    # fact that via-wheel and via-BCM paths have different distributions).
    chain_bucket_spins: dict[tuple, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    chain_bucket_bet: dict[tuple, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    chain_bucket_win: dict[tuple, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )

    # Collect-mechanic accumulation. M272's mode 1/2 carries CollectCount
    # (per-robot monotonic counter of triggered collects) and AccCredits
    # (cumulative collected credits). M14 has neither; chunk_collect_seen
    # stays at 0 and the summary marks the surface as not applicable.
    chunk_collect_count_total = 0  # sum of max CollectCount across robots
    chunk_acc_credits_max = 0      # peak AccCredits seen this chunk
    chunk_collect_seen = 0         # robots whose rounds carried the fields
    # Trunk-clamp tracking: how many paid spins had elapsed in each robot
    # since its last collect-trigger when the chunk's SpinTimes ran out.
    # If chunks routinely end with substantial pending paid spins past
    # the average collect interval, the upstream collect bonus that those
    # spins would have eventually triggered never fires inside the
    # sample, and observed RTP under-reports the true RTP. We surface
    # these raw signals (no fabricated lost_pp number) so the operator
    # can decide whether to widen chunk_spin_times.
    chunk_clamp_pending_paid_spins = 0  # sum across robots
    chunk_clamp_pending_robots = 0      # robots with pending > 0
    # BuffCollectionMap cycle detection accumulators.
    chunk_cycle_peaks: list[int] = []   # CC values at each detected reset
    chunk_final_cc_values: list[int] = []  # final CC per robot at chunk end
    chunk_completed_cycles = 0          # total complete cycles across robots

    # Per-payline winning-symbol inference. The API returns
    # PayoutByPayline (which line ids paid) and StopSymbolsByCol (the
    # 5 columns of stopped symbols), but no direct payline->position
    # mapping. Heuristic: classic slots pay 3+ same symbols left-to-
    # right, so the symbol that appears in the leftmost three columns'
    # stopped sets is almost certainly the winner for any line that
    # hit on this spin. We tally per-(payline_id, symbol) frequency so
    # the drilldown can show which symbols carry each payline's RTP.
    payline_winning_symbols: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    # RLN-based (authoritative) winning symbols per payline.
    payline_winning_symbols_rln: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    # --- Raw-data analyses (need per-spin sequential context) ---
    # Payline × Symbol joint: (payline_id, symbol_code) → {hits, win}
    payline_symbol_joint: dict[str, dict[str, float]] = defaultdict(
        lambda: {"hits": 0, "win": 0.0}
    )
    # Session RTP curve: per-robot cumulative win/bet at sample points.
    session_rtp_curves: list[list[dict[str, float]]] = []
    # Chain ExtraRatio sequences: per-chain ordered ratio list.
    chain_ratio_sequences: list[list[int]] = []
    # Reel position distribution: from PayoutByPayline "(pos1,pos2,...)" groups.
    reel_position_hits: dict[str, int] = defaultdict(int)
    _POSITION_RE = re.compile(r"\(([0-9,]+)\)")

    # Bonus-chain dynamics (from ReMarks). A "chain" is a contiguous run
    # of Freespin-annotated rounds within one robot. We track per chain:
    # final length, peak ExtraRatio, self-retrigger hits; plus per-round
    # depth-bucketed ExtraRatio so the summary can draw the
    # energy-ramp curve. M14 and other non-MapCollection machines emit
    # no Freespin ReMarks -- the accumulators stay empty and the summary
    # flags the surface as applicable=False.
    chunk_bonus_chain_lengths: list[int] = []
    chunk_bonus_chain_max_ratios: list[int] = []
    chunk_bonus_chain_retrigger_events: list[int] = []  # per-chain retrigger count
    chunk_bonus_total_rounds = 0
    chunk_bonus_retrigger_rounds = 0
    chunk_bonus_extra_ratio_counts: dict[int, int] = defaultdict(int)
    # Depth-bucket -> sum of extra_ratio / count of rounds (for mean).
    chunk_bonus_depth_ratio_sum: dict[str, float] = defaultdict(float)
    chunk_bonus_depth_ratio_count: dict[str, int] = defaultdict(int)

    # Per-robot bonus-chain state. Flushed on chain end or robot end.
    # trigger_feature: "NormalCollectionSpin" when the trigger spin
    # carried PayId 666, "NewFreespin" when trigger spin had no PayIds
    # (forced at cycle boundary), "unknown" otherwise.
    active_chain = {
        "length": 0, "max_ratio": 0, "retriggers": 0,
        "open": False, "ratios": [], "trigger_feature": "unknown",
    }

    # Per-feature chain accumulators. Keyed by trigger_feature string.
    chunk_chains_by_feature: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "lengths": [], "max_ratios": [], "retrigger_events": [],
            "total_rounds": 0, "retrigger_rounds": 0,
            "extra_ratio_counts": defaultdict(int),
            "depth_ratio_sum": defaultdict(float),
            "depth_ratio_count": defaultdict(int),
            "ratio_sequences": [],
        }
    )

    def _flush_bonus_chain() -> None:
        if not active_chain["open"]:
            return
        feat = active_chain["trigger_feature"]
        fb = chunk_chains_by_feature[feat]
        fb["lengths"].append(int(active_chain["length"]))
        fb["max_ratios"].append(int(active_chain["max_ratio"]))
        fb["retrigger_events"].append(int(active_chain["retriggers"]))
        if active_chain["ratios"]:
            fb["ratio_sequences"].append(list(active_chain["ratios"]))
        # Also maintain the global (aggregate) accumulators for
        # back-compat with the existing summary shape.
        chunk_bonus_chain_lengths.append(int(active_chain["length"]))
        chunk_bonus_chain_max_ratios.append(int(active_chain["max_ratio"]))
        chunk_bonus_chain_retrigger_events.append(int(active_chain["retriggers"]))
        if active_chain["ratios"]:
            chain_ratio_sequences.append(list(active_chain["ratios"]))
        active_chain["length"] = 0
        active_chain["max_ratio"] = 0
        active_chain["retriggers"] = 0
        active_chain["ratios"] = []
        active_chain["trigger_feature"] = "unknown"
        active_chain["open"] = False

    # Session state shared across the inner spin loop and its post-loop
    # flush. Kept as a mutable holder so the inline close() helper can
    # mutate without a long nonlocal declaration.
    sess_state = {
        "open": False,
        "bet": 0.0,
        "win": 0.0,
        "cur_loss_streak": 0,
        "cur_win_streak": 0,
    }

    def _close_session() -> None:
        # Finalize whatever session is currently open. Idempotent if no
        # session is open (guarded at call site). Mutates all session-
        # level chunk counters via `nonlocal`. Keeps the paid/bonus
        # accounting honest: session's bet is the paid bet only; win is
        # paid + all subsequent bonus wins that were attributed to it.
        nonlocal paid_session_count
        nonlocal session_win_count, session_lose_count
        nonlocal session_profit_count, session_breakeven_count, session_big_win_x10_count
        nonlocal session_ret_count, session_ret_sum, session_ret_sq_sum, session_max_return_x
        nonlocal session_win_sum
        nonlocal session_max_loss_streak, session_max_win_streak

        if not sess_state["open"]:
            return
        s_bet = float(sess_state["bet"])
        s_win = float(sess_state["win"])
        ret_x_sess = (s_win / s_bet) if s_bet > 0 else 0.0

        paid_session_count += 1
        session_ret_count += 1
        session_ret_sum += ret_x_sess
        session_ret_sq_sum += ret_x_sess * ret_x_sess
        if ret_x_sess > session_max_return_x:
            session_max_return_x = ret_x_sess
        b = return_bucket(ret_x_sess)
        session_bucket_spins[b] += 1
        session_bucket_bet[b] += s_bet
        session_bucket_win[b] += s_win
        session_win_sum += s_win

        if s_win > 0:
            session_win_count += 1
            if s_win > s_bet:
                session_profit_count += 1
            if s_win >= s_bet:
                session_breakeven_count += 1
            if s_bet > 0 and s_win >= 10.0 * s_bet:
                session_big_win_x10_count += 1
            # Flip streak: if we were on a lose streak, close it.
            if sess_state["cur_loss_streak"] > 0:
                session_loss_streak_hist[sess_state["cur_loss_streak"]] += 1
                if sess_state["cur_loss_streak"] > session_max_loss_streak:
                    session_max_loss_streak = sess_state["cur_loss_streak"]
                sess_state["cur_loss_streak"] = 0
            sess_state["cur_win_streak"] += 1
        else:
            session_lose_count += 1
            if sess_state["cur_win_streak"] > 0:
                session_win_streak_hist[sess_state["cur_win_streak"]] += 1
                if sess_state["cur_win_streak"] > session_max_win_streak:
                    session_max_win_streak = sess_state["cur_win_streak"]
                sess_state["cur_win_streak"] = 0
            sess_state["cur_loss_streak"] += 1

        sess_state["open"] = False
        sess_state["bet"] = 0.0
        sess_state["win"] = 0.0

    for robot in resp:
        if not isinstance(robot, dict):
            continue
        rounds = parse_rounds(robot)
        cur_loss = 0
        cur_win = 0
        # Per-robot collect tracking: max CollectCount + max AccCredits
        # observed within this robot's rounds.
        robot_max_collect_count = 0
        robot_max_acc_credits = 0
        robot_collect_observed = False
        # Trunk-clamp tracking per robot: walk the CollectCount sequence
        # in order; remember the paid-spin index of the last collect
        # transition. After the loop, the difference between the final
        # paid-spin index and that pointer is "paid spins waiting on the
        # next collect trigger" -- the size of the cycle that didn't
        # close before SpinTimes ran out.
        robot_paid_spin_idx = 0
        robot_last_collect_paid_idx = 0
        robot_prev_collect_count = 0
        # BuffCollectionMap cycle detection: track CC resets to find the
        # cycle length (e.g., M272 mode 1 = 1000 paid spins). The cycle
        # length varies per machine/mode and is NOT hardcoded. We detect
        # it by observing when CC drops from a high value back to a low
        # value (reset). The peak CC before each reset = cycle length.
        robot_cycle_peaks: list[int] = []  # CC value just before each reset
        robot_prev_cc_for_cycle = 0  # previous CC (for reset detection)
        robot_final_cc = 0  # CC at chunk end (for pending calculation)
        prev_round_pids: dict[str, Any] = {}  # previous round's PayoutIdToWinAmount (for chain trigger classification)
        # Previous round's SpinType within this robot (reset per-robot
        # so transition counts don't cross robot boundaries — each
        # robot is an independent session trajectory).
        prev_sp_type_in_robot: int | None = None
        # Bonus-chain trigger-path tracker. Each time the robot
        # transitions from paid → non-paid, a chain opens tagged with:
        #   * first_st: the SpinType of the entry round
        #   * entry_cc_reset: whether the immediately-preceding paid
        #     round observed a CollectCount reset (BCM cycle signal)
        # Chain closes on the next paid round; stats roll up into
        # ``chunk_chain_summaries`` keyed by (first_st, entry_cc_reset,
        # sp_type_within_chain). Post-process in _finalize maps the
        # (first_st, cc_reset) key to a human label and attributes
        # per-sp_type wins to the matching paying feature.
        _bonus_chain_active: dict[str, Any] | None = None
        _bonus_chain_last_cc_reset = False  # cc reset seen in the last paid round
        # Reset session-level streak state at robot boundary (streaks
        # don't cross robots -- each is an independent player trajectory).
        sess_state["cur_loss_streak"] = 0
        sess_state["cur_win_streak"] = 0

        for r in rounds:
            if not isinstance(r, dict):
                continue

            # Extra-field discovery (lightweight: just set-diff the keys).
            for k in r:
                if k not in _BASELINE_ROUND_FIELDS:
                    extra_fields_seen[k] += 1

            # --- Per-machine mechanic fields ---
            _lock_lines = r.get("LockLines")
            if _lock_lines and isinstance(_lock_lines, str) and _lock_lines.strip("-").strip():
                lock_lines_spins += 1
                lock_lines_total_lines += len([x for x in _lock_lines.split("-") if x.strip()])
                lock_lines_win += to_float(r.get("WinCredits"), default=0.0)

            _lock_syms = r.get("LockSymbols")
            if _lock_syms and isinstance(_lock_syms, str) and _lock_syms.strip("| "):
                lock_symbols_spins += 1
                lock_symbols_win += to_float(r.get("WinCredits"), default=0.0)
                for part in _lock_syms.split("|"):
                    part = part.strip()
                    if ":" in part:
                        lock_symbols_unique.add(part.split(":")[0].strip())

            _lock_reels = r.get("LockReels")
            if _lock_reels and isinstance(_lock_reels, str) and _lock_reels.strip():
                lock_reels_spins += 1
                lock_reels_win += to_float(r.get("WinCredits"), default=0.0)

            _jackpot_ids = r.get("JackpotIds") or r.get("JackpotID")
            if _jackpot_ids is not None:
                _jid_str = str(_jackpot_ids).strip("-").strip()
                if _jid_str:
                    jackpot_spins += 1
                    jackpot_win += to_float(r.get("WinCredits"), default=0.0)
                    for jid in str(_jackpot_ids).split("-"):
                        jid = jid.strip()
                        if jid:
                            jackpot_ids_seen.add(jid)

            _cur_fs = r.get("CurFreeSpin")
            if _cur_fs is not None:
                try:
                    cur_idx = int(_cur_fs)
                except (TypeError, ValueError):
                    cur_idx = 0
                if cur_idx > 0:
                    freespin_chain_spins += 1
                    freespin_win += to_float(r.get("WinCredits"), default=0.0)
                    if cur_idx > freespin_max_chain:
                        freespin_max_chain = cur_idx
                    add_fs = r.get("AddFreeSpin")
                    if add_fs is not None:
                        try:
                            add_val = int(add_fs)
                        except (TypeError, ValueError):
                            add_val = 0
                        if add_val > 0:
                            freespin_retriggers += add_val

            _chosen_dollar = r.get("ChosenDollar")
            if _chosen_dollar and isinstance(_chosen_dollar, str) and _chosen_dollar.strip("-").strip():
                dollar_pick_spins += 1
                dollar_pick_total_dollars += len([x for x in _chosen_dollar.split("-") if x.strip()])
                dollar_pick_win += to_float(r.get("WinCredits"), default=0.0)

            bet_amt = to_float(r.get("BetAmount"), default=0.0)
            if bet_amt <= 0.0:
                bet_amt = to_float(r.get("CostCredits"), default=float(bet))
            if bet_amt <= 0.0:
                bet_amt = float(bet)

            # Paid vs bonus: CostCredits>0 means the player paid for this
            # spin; CostCredits==0 means it's a free / bonus / re-spin.
            # When CostCredits is unreliable (always 0 despite BetAmount>0),
            # fall back to treating every spin as paid so session metrics
            # are meaningful.
            if cost_credits_unreliable:
                is_paid = True
            else:
                cost_credits_raw = r.get("CostCredits")
                if cost_credits_raw is None:
                    is_paid = True
                else:
                    is_paid = to_float(cost_credits_raw, default=0.0) > 0.0

            win_amt = to_float(r.get("WinCredits"), default=0.0)
            chunk_spins += 1
            chunk_bet += bet_amt
            chunk_win += win_amt

            # Session accounting: close previous session on every new
            # paid spin; bonus wins accrue into the currently-open session.
            if is_paid:
                _close_session()
                sess_state["open"] = True
                sess_state["bet"] = bet_amt
                sess_state["win"] = win_amt
            else:
                if sess_state["open"]:
                    sess_state["win"] += win_amt
                    bonus_spin_count += 1
                # else: orphan bonus (no prior paid spin seen) -- rare /
                # anomalous; not counted toward any session. The spin is
                # still counted in chunk_spins + spin_type_breakdown.

            ret_x = (win_amt / bet_amt) if bet_amt > 0 else 0.0
            max_return_x = max(max_return_x, ret_x)
            ret_count += 1
            ret_sum += ret_x
            ret_sq_sum += ret_x * ret_x
            bucket = return_bucket(ret_x)
            multiplier_bucket_spins[bucket] += 1
            multiplier_bucket_bet[bucket] += bet_amt
            multiplier_bucket_win[bucket] += win_amt
            # Per-SpinType bucket tally deferred until after sp_type is
            # assigned below (see "SpinType per-spin tally" block).

            if win_amt > 0:
                win_spins += 1
                win_sum += win_amt
                if win_amt > bet_amt:
                    profit_spins += 1
                if win_amt >= bet_amt:
                    breakeven_or_more_spins += 1
                if win_amt >= 10.0 * bet_amt:
                    big_win_x10_spins += 1

                if cur_loss > 0:
                    loss_streak_hist[cur_loss] += 1
                    max_loss_streak = max(max_loss_streak, cur_loss)
                    cur_loss = 0
                cur_win += 1
            else:
                loss_spins += 1
                if cur_win > 0:
                    win_streak_hist[cur_win] += 1
                    max_win_streak = max(max_win_streak, cur_win)
                    cur_win = 0
                cur_loss += 1

            if bool(r.get("IsLackCreditsSpin", False)):
                lack_credit_spins += 1

            # PayoutGroupId aggregation: each spin reports one group id.
            # Group 0 means "no payout"; non-zero ids carry the win.
            try:
                pg_id = int(r.get("PayoutGroupId", 0) or 0)
            except (TypeError, ValueError):
                pg_id = 0
            payout_group_hits[pg_id] += 1
            payout_group_win[pg_id] += win_amt

            # SpinType per-spin tally. Type semantics are machine-specific
            # (M14: 1; M272: 140 main + 126 bonus; future machines may
            # introduce new types). Aggregating spins/bet/win per type
            # lets the drilldown show per-mechanic RTP and bonus-share
            # without us hardcoding any meaning.
            try:
                sp_type = int(r.get("SpinType", 0) or 0)
            except (TypeError, ValueError):
                sp_type = 0
            spin_type_spins[sp_type] += 1
            spin_type_bet[sp_type] += bet_amt
            if is_paid:
                spin_type_paid_bet[sp_type] += bet_amt
                spin_type_paid_rounds[sp_type] += 1
            spin_type_win[sp_type] += win_amt
            if win_amt > 0:
                spin_type_wins[sp_type] += 1
            # Per-SpinType return bucket (mirrors the global
            # multiplier_bucket_* but keyed by SpinType so upstream
            # feature breakdown can render a per-feature histogram).
            spin_type_bucket_spins[sp_type][bucket] += 1
            spin_type_bucket_bet[sp_type][bucket] += bet_amt
            spin_type_bucket_win[sp_type][bucket] += win_amt
            # Bonus-chain trigger-path bookkeeping. A chain opens on
            # the first non-paid round after a paid run; it accrues
            # all subsequent non-paid rounds keyed to a stable
            # (first_st, entry_cc_reset) bucket. A paid round closes
            # the chain. entry_cc_reset reflects whether the
            # immediately-preceding paid round observed a CollectCount
            # reset — the M272/M273 BCM-cycle signal.
            # Chain-detection has a stricter "is this a paid round"
            # test than the RTP-side is_paid. RTP defensively treats
            # CostCredits=None as paid (unknown → assume paid so
            # denominators stay conservative). But ceremony rounds on
            # M273-style machines (WheelSelector / PreWheel / etc.)
            # legitimately omit CostCredits entirely — None there
            # means "background sub-round in a chain", not "paid with
            # unreported cost". Treat None as non-paid for chain
            # purposes so 139→136→137→117 stays ONE chain.
            if cost_credits_unreliable:
                _is_paid_for_chain = True
            else:
                _cc_raw_chain = r.get("CostCredits")
                _is_paid_for_chain = _cc_raw_chain is not None and to_float(
                    _cc_raw_chain, default=0.0
                ) > 0.0
            if _is_paid_for_chain:
                # Close any open chain.
                _bonus_chain_active = None
            else:
                if _bonus_chain_active is None:
                    _bonus_chain_active = {
                        "first_st": sp_type,
                        "entry_cc_reset": _bonus_chain_last_cc_reset,
                    }
                    # Consume the reset flag — it applies to this
                    # entry only, not to the next chain.
                    _bonus_chain_last_cc_reset = False
                key = (
                    _bonus_chain_active["first_st"],
                    _bonus_chain_active["entry_cc_reset"],
                    sp_type,
                )
                entry = chain_chunk_summaries[key]
                entry["count"] += 1
                entry["win"] += win_amt
                entry["bet"] += bet_amt
                # Per-chain-path bucket tracking — lets the UI show a
                # distinct bucket histogram per trigger path for the
                # same paying SpinType (e.g. M273 LockSymbolFreespin
                # via PreWheel vs via BCM cycle).
                chain_bucket_spins[key][bucket] += 1
                chain_bucket_bet[key][bucket] += bet_amt
                chain_bucket_win[key][bucket] += win_amt
            # Per-robot SpinType transition for chain-parent inference.
            # Boundary (first round of a robot) contributes no edge.
            if prev_sp_type_in_robot is not None:
                spin_type_next_counts[prev_sp_type_in_robot][sp_type] += 1
            prev_sp_type_in_robot = sp_type
            # Sample ReMarks for this SpinType (up to 3 strings). Used
            # downstream to match feature_name ↔ SpinType by substring
            # when fire-count ties are ambiguous. Truncate to 120 chars
            # to keep chunk metrics compact.
            if len(spin_type_remarks_sample[sp_type]) < 3:
                _rem = r.get("ReMarks")
                if isinstance(_rem, list):
                    _rem = ";".join(str(x) for x in _rem)
                if isinstance(_rem, str):
                    _rem = _rem.strip()
                    if _rem:
                        spin_type_remarks_sample[sp_type].append(_rem[:120])

            # Bonus-chain ReMarks parsing. Freespin-annotated rounds
            # accumulate into the active chain; non-annotated rounds
            # close it (so mid-chain paid spins -- which don't happen
            # on M272 -- would still produce clean chain boundaries
            # if some future machine interleaves). End-of-robot is
            # handled after this inner loop.
            fs_meta = parse_freespin_remarks(r.get("ReMarks"))
            if fs_meta is not None:
                if not active_chain["open"]:
                    active_chain["open"] = True
                    # Classify trigger: look at the PREVIOUS main spin.
                    # If it carried PayId 666 → NormalCollectionSpin
                    # (random trigger). If it had empty PID →
                    # NewFreespin (forced at cycle boundary). Generic:
                    # any non-empty PID = random, empty = forced.
                    prev_pids = prev_round_pids if prev_round_pids else {}
                    if prev_pids:
                        active_chain["trigger_feature"] = "NormalCollectionSpin"
                    else:
                        active_chain["trigger_feature"] = "NewFreespin"
                # length tracks the highest Freespin index seen (they
                # come in order but we max-of to be defensive).
                if fs_meta["freespin_index"] > active_chain["length"]:
                    active_chain["length"] = fs_meta["freespin_index"]
                if fs_meta["extra_ratio"] > active_chain["max_ratio"]:
                    active_chain["max_ratio"] = fs_meta["extra_ratio"]
                if fs_meta["has_retrigger"]:
                    active_chain["retriggers"] += 1
                    chunk_bonus_retrigger_rounds += 1
                chunk_bonus_total_rounds += 1
                active_chain["ratios"].append(fs_meta["extra_ratio"])
                chunk_bonus_extra_ratio_counts[fs_meta["extra_ratio"]] += 1
                depth = bonus_chain_depth_bucket(fs_meta["freespin_index"])
                chunk_bonus_depth_ratio_sum[depth] += fs_meta["extra_ratio"]
                chunk_bonus_depth_ratio_count[depth] += 1
                # Per-feature running stats (in addition to global).
                feat = active_chain["trigger_feature"]
                fb = chunk_chains_by_feature[feat]
                fb["total_rounds"] += 1
                if fs_meta["has_retrigger"]:
                    fb["retrigger_rounds"] += 1
                fb["extra_ratio_counts"][fs_meta["extra_ratio"]] += 1
                fb["depth_ratio_sum"][depth] += fs_meta["extra_ratio"]
                fb["depth_ratio_count"][depth] += 1
            elif active_chain["open"]:
                _flush_bonus_chain()

            # Collect mechanic (M272+): track max CollectCount (per-robot
            # monotonic counter of triggered collect bonuses) and max
            # AccCredits (peak accumulated credit balance). Fields are
            # absent on M14 / non-collect machines -- we only mark this
            # robot as "observed" when at least one of the two appears.
            cc_raw = r.get("CollectCount")
            ac_raw = r.get("AccCredits")
            if cc_raw is not None or ac_raw is not None:
                robot_collect_observed = True
            try:
                cc_int = int(cc_raw or 0)
            except (TypeError, ValueError):
                cc_int = 0
            try:
                ac_int = int(ac_raw or 0)
            except (TypeError, ValueError):
                ac_int = 0
            if cc_int > robot_max_collect_count:
                robot_max_collect_count = cc_int
            # Cycle detection: CC drops from a high value to a low value
            # = one complete BuffCollectionMap cycle. Record the peak.
            # Only track on paid spins (bonus spins have CC=None/0).
            if is_paid and cc_int > 0:
                if cc_int < robot_prev_cc_for_cycle and robot_prev_cc_for_cycle > 10:
                    robot_cycle_peaks.append(robot_prev_cc_for_cycle)
                    # Flag the NEXT chain entry (if any immediately
                    # follows) as BCM-cycle-triggered. Cleared either
                    # when consumed by a chain open or by the next
                    # paid round without a chain between.
                    _bonus_chain_last_cc_reset = True
                robot_prev_cc_for_cycle = cc_int
                robot_final_cc = cc_int
            # On a paid round without a reset, clear any stale BCM
            # flag — only consecutive (paid-with-reset → chain-entry)
            # transitions count as BCM-triggered.
            if is_paid and cc_int == 0 and robot_prev_cc_for_cycle == 0:
                _bonus_chain_last_cc_reset = False
            # Trunk-clamp pointer: every time CollectCount ticks up, mark
            # the paid-spin index where it happened. Only paid spins
            # advance the cycle counter (bonus spins ride on the
            # currently-open paid session).
            if is_paid:
                robot_paid_spin_idx += 1
            if cc_int > robot_prev_collect_count:
                robot_last_collect_paid_idx = robot_paid_spin_idx
                robot_prev_collect_count = cc_int
            if ac_int > robot_max_acc_credits:
                robot_max_acc_credits = ac_int

            # PayoutIdToWinAmount aggregation: dict of {payout_id: win}
            # populated on winning rounds. Sum win and count occurrences
            # per id so the drilldown can rank by total contribution.
            pid_to_win = r.get("PayoutIdToWinAmount") or {}
            if isinstance(pid_to_win, dict):
                for pid_raw, amount_raw in pid_to_win.items():
                    pid = str(pid_raw)
                    payout_id_hits[pid] += 1
                    payout_id_win[pid] += to_float(amount_raw, default=0.0)

            line_ids = parse_paylines(str(r.get("PayoutByPayline") or ""))
            if line_ids:
                share = win_amt / len(line_ids)
                for lid in line_ids:
                    payline_hits[lid] += 1
                    payline_win_approx[lid] += share

            stop_cols = r.get("StopSymbolsByCol") or []
            col_symbol_sets: list[set[str]] = []
            if isinstance(stop_cols, list):
                for ci, col_text in enumerate(stop_cols):
                    col_syms = split_symbols(str(col_text))
                    col_symbol_sets.append({s for s in col_syms if s})
                    for sym in col_syms:
                        symbol_counts[sym] += 1
                        symbol_counts_by_col[ci][sym] += 1
                        total_symbol_slots += 1

            # Infer the winning symbol(s) for each line that paid this
            # spin. Two streams run in parallel:
            #   - RLN (authoritative): RewardLastNode lists the numeric
            #     symbol codes that actually paid. When present, it's
            #     what we credit -- upstream-true.
            #   - Heuristic fallback: intersect the stopped-symbol sets
            #     across the leftmost three columns (classic slot pays
            #     3+ matching left-to-right) after filtering blank-like
            #     symbols; fall back to any non-blank leftmost symbol
            #     if intersection is empty (atypical bonus payout).
            # Emitting both streams lets the summary prefer RLN per
            # payline-id while falling back to heuristic for any ID
            # whose RLN stream happens to be empty (typically when the
            # winning rounds used a non-RLN code path).
            rln_codes = parse_rln_codes(r.get("RewardLastNode"))
            if line_ids and rln_codes:
                # de-dupe within the spin so a code that appeared twice
                # in RLN on multi-line wins doesn't overweight.
                unique_codes = set(rln_codes)
                for lid in line_ids:
                    for code in unique_codes:
                        payline_winning_symbols_rln[lid][code] += 1
            if line_ids and len(col_symbol_sets) >= 3:
                c0 = {s for s in col_symbol_sets[0] if not blank_like_symbol(s)}
                c1 = {s for s in col_symbol_sets[1] if not blank_like_symbol(s)}
                c2 = {s for s in col_symbol_sets[2] if not blank_like_symbol(s)}
                first3 = c0 & c1 & c2
                if not first3 and c0:
                    first3 = {next(iter(c0))}
                for lid in line_ids:
                    for sym in first3:
                        payline_winning_symbols[lid][sym] += 1

            # --- Raw-data per-spin analysis accumulation ---
            # Payline × Symbol joint: credit each (payline, symbol) pair
            # with this spin's per-line win share. Uses RLN codes when
            # present; falls back to heuristic symbols.
            if line_ids and win_amt > 0:
                sym_for_joint = set(rln_codes) if rln_codes else (
                    first3 if (len(col_symbol_sets) >= 3) else set()
                )
                per_line_win = win_amt / max(len(line_ids), 1)
                for lid in line_ids:
                    for sym in sym_for_joint:
                        key = f"{lid}:{sym}"
                        payline_symbol_joint[key]["hits"] += 1
                        payline_symbol_joint[key]["win"] += per_line_win

            # Reel position distribution: extract position groups from
            # PayoutByPayline's "(pos1,pos2,...)" notation.
            if line_ids and win_amt > 0:
                pl_text = str(r.get("PayoutByPayline", ""))
                for match in _POSITION_RE.finditer(pl_text):
                    for pos in match.group(1).split(","):
                        pos = pos.strip()
                        if pos:
                            reel_position_hits[pos] += 1

            # Track previous round's PayIds for chain trigger
            # classification. MUST be the last thing inside the round
            # loop so every paid spin updates it before the next
            # iteration's chain-start check.
            if is_paid:
                prev_round_pids = r.get("PayoutIdToWinAmount") or {}

        # --- End of per-round loop ---

        if cur_loss > 0:
            loss_streak_hist[cur_loss] += 1
            max_loss_streak = max(max_loss_streak, cur_loss)
        if cur_win > 0:
            win_streak_hist[cur_win] += 1
            max_win_streak = max(max_win_streak, cur_win)

        # Session RTP curve: walk this robot's rounds to build cumulative
        # RTP at sampled points. We sample ~50 points per robot for the
        # summary curve (keeps output size bounded).
        cum_bet_r = 0.0
        cum_win_r = 0.0
        paid_count_r = 0
        sample_interval = max(1, robot_paid_spin_idx // 50) if robot_paid_spin_idx > 0 else 1
        curve_points: list[dict[str, float]] = []
        paid_i = 0
        for rr in rounds:
            if not isinstance(rr, dict):
                continue
            cost_r = to_float(rr.get("CostCredits"), default=0.0)
            if cost_r > 0:
                paid_i += 1
                cum_bet_r += to_float(rr.get("BetAmount"), default=cost_r)
                cum_win_r += to_float(rr.get("WinCredits"), default=0.0)
                if paid_i % sample_interval == 0 or paid_i == robot_paid_spin_idx:
                    curve_points.append({
                        "spin": paid_i,
                        "cum_rtp": (cum_win_r / cum_bet_r * 100.0) if cum_bet_r > 0 else 0.0,
                    })
            else:
                # Bonus spin wins attribute to session but we track
                # cumulative win for the curve.
                cum_win_r += to_float(rr.get("WinCredits"), default=0.0)
        if curve_points:
            session_rtp_curves.append(curve_points)

        # Flush any in-progress bonus chain so the chain doesn't span
        # robot boundaries silently.
        _flush_bonus_chain()

        # Finalize the last open session (if any) at the robot boundary,
        # then flush the session-level streak histograms so open streaks
        # don't silently roll into the next robot's counts.
        _close_session()
        if sess_state["cur_loss_streak"] > 0:
            session_loss_streak_hist[sess_state["cur_loss_streak"]] += 1
            if sess_state["cur_loss_streak"] > session_max_loss_streak:
                session_max_loss_streak = sess_state["cur_loss_streak"]
            sess_state["cur_loss_streak"] = 0
        if sess_state["cur_win_streak"] > 0:
            session_win_streak_hist[sess_state["cur_win_streak"]] += 1
            if sess_state["cur_win_streak"] > session_max_win_streak:
                session_max_win_streak = sess_state["cur_win_streak"]
            sess_state["cur_win_streak"] = 0

        # Roll the per-robot collect totals into the chunk-level tally.
        chunk_collect_count_total += robot_max_collect_count
        if robot_max_acc_credits > chunk_acc_credits_max:
            chunk_acc_credits_max = robot_max_acc_credits
        if robot_collect_observed:
            chunk_collect_seen += 1
            pending = robot_paid_spin_idx - robot_last_collect_paid_idx
            if pending > 0:
                chunk_clamp_pending_paid_spins += pending
                chunk_clamp_pending_robots += 1
        # BuffCollectionMap cycle peaks + final CC for NewFreespin
        # correction. Cycle peaks let us detect the cycle length
        # dynamically (not hardcoded); final_cc tells us how far into
        # the current incomplete cycle this robot was when the chunk
        # ended.
        if robot_cycle_peaks:
            chunk_cycle_peaks.extend(robot_cycle_peaks)
        if robot_final_cc > 0:
            chunk_final_cc_values.append(robot_final_cc)
        # Detect NewFreespin chains: chains that started at exactly
        # the cycle boundary (trigger spin has NO PayId 666 but CC was
        # at cycle peak). We already tracked these as bonus chains —
        # their wins contribute to the NewFreespin expected payout.
        # For correction, we just need the cycle peaks + final CCs.
        chunk_completed_cycles += len(robot_cycle_peaks)

    if chunk_spins <= 0 or chunk_bet <= 0:
        return {"ok": False, "index": chunk_index, "error": "parse_failed_zero_chunk"}

    return {
        "ok": True,
        "index": chunk_index,
        "elapsed_seconds": round(time.time() - started, 3),
        "spins": chunk_spins,
        "bet": chunk_bet,
        "win": chunk_win,
        "ret_count": ret_count,
        "ret_sum": ret_sum,
        "ret_sq_sum": ret_sq_sum,
        "max_return_x": max_return_x,
        "win_spins": win_spins,
        "loss_spins": loss_spins,
        "profit_spins": profit_spins,
        "breakeven_or_more_spins": breakeven_or_more_spins,
        "big_win_x10_spins": big_win_x10_spins,
        "win_sum": win_sum,
        "lack_credit_spins": lack_credit_spins,
        "payline_hits": dict(payline_hits),
        "payline_win_approx": dict(payline_win_approx),
        "payline_winning_symbols": {
            str(lid): dict(syms) for lid, syms in payline_winning_symbols.items()
        },
        "payline_winning_symbols_rln": {
            str(lid): dict(codes) for lid, codes in payline_winning_symbols_rln.items()
        },
        "bonus_chain_lengths": list(chunk_bonus_chain_lengths),
        "bonus_chain_max_ratios": list(chunk_bonus_chain_max_ratios),
        "bonus_chain_retrigger_events": list(chunk_bonus_chain_retrigger_events),
        "bonus_total_rounds": chunk_bonus_total_rounds,
        "bonus_retrigger_rounds": chunk_bonus_retrigger_rounds,
        "bonus_extra_ratio_counts": {str(k): v for k, v in chunk_bonus_extra_ratio_counts.items()},
        "bonus_depth_ratio_sum": dict(chunk_bonus_depth_ratio_sum),
        "bonus_depth_ratio_count": dict(chunk_bonus_depth_ratio_count),
        "symbol_counts": dict(symbol_counts),
        "symbol_counts_by_col": {str(k): dict(v) for k, v in symbol_counts_by_col.items()},
        "total_symbol_slots": total_symbol_slots,
        "loss_streak_hist": dict(loss_streak_hist),
        "win_streak_hist": dict(win_streak_hist),
        "max_loss_streak": max_loss_streak,
        "max_win_streak": max_win_streak,
        "multiplier_bucket_spins": dict(multiplier_bucket_spins),
        "multiplier_bucket_bet": dict(multiplier_bucket_bet),
        "multiplier_bucket_win": dict(multiplier_bucket_win),
        "payout_group_hits": {str(k): v for k, v in payout_group_hits.items()},
        "payout_group_win": {str(k): v for k, v in payout_group_win.items()},
        "payout_id_hits": dict(payout_id_hits),
        "payout_id_win": dict(payout_id_win),
        "spin_type_spins": {str(k): v for k, v in spin_type_spins.items()},
        "spin_type_bet": {str(k): v for k, v in spin_type_bet.items()},
        "spin_type_paid_bet": {str(k): v for k, v in spin_type_paid_bet.items()},
        "spin_type_win": {str(k): v for k, v in spin_type_win.items()},
        "spin_type_wins": {str(k): v for k, v in spin_type_wins.items()},
        "spin_type_paid_rounds": {str(k): v for k, v in spin_type_paid_rounds.items()},
        "spin_type_next_counts": {
            str(k): {str(t): c for t, c in v.items()}
            for k, v in spin_type_next_counts.items()
        },
        "spin_type_remarks_sample": {
            str(k): list(v) for k, v in spin_type_remarks_sample.items()
        },
        "spin_type_bucket_spins": {
            str(k): dict(v) for k, v in spin_type_bucket_spins.items()
        },
        "spin_type_bucket_bet": {
            str(k): dict(v) for k, v in spin_type_bucket_bet.items()
        },
        "spin_type_bucket_win": {
            str(k): dict(v) for k, v in spin_type_bucket_win.items()
        },
        "chain_chunk_summaries": [
            {
                "first_st": k[0],
                "entry_cc_reset": bool(k[1]),
                "sp_type": k[2],
                "count": v["count"],
                "win": v["win"],
                "bet": v["bet"],
            }
            for k, v in chain_chunk_summaries.items()
        ],
        # Per-chain-path bucket histograms. Serialized as list (keyed
        # by tuple) so the reduce step in main / resume_from_cache can
        # merge by identical (first_st, cc_reset, sp_type) + bucket.
        "chain_bucket_spins": [
            {"first_st": k[0], "entry_cc_reset": bool(k[1]), "sp_type": k[2],
             "buckets": dict(v)}
            for k, v in chain_bucket_spins.items()
        ],
        "chain_bucket_bet": [
            {"first_st": k[0], "entry_cc_reset": bool(k[1]), "sp_type": k[2],
             "buckets": dict(v)}
            for k, v in chain_bucket_bet.items()
        ],
        "chain_bucket_win": [
            {"first_st": k[0], "entry_cc_reset": bool(k[1]), "sp_type": k[2],
             "buckets": dict(v)}
            for k, v in chain_bucket_win.items()
        ],
        "upstream_feature_tally": {
            feat: {pid: dict(v) for pid, v in payouts.items()}
            for feat, payouts in feature_chunk_tally.items()
        },
        "upstream_chunk_total_win": upstream_chunk_total_win,
        "upstream_chunk_robots_seen": upstream_chunk_robots_seen,
        "collect_count_total": chunk_collect_count_total,
        "acc_credits_max": chunk_acc_credits_max,
        "collect_robots_seen": chunk_collect_seen,
        # Trunk-clamp signals (only meaningful when collect mechanic is
        # active for the machine). pending_paid_spins = sum across robots
        # of paid spins waiting on the next collect at chunk-end.
        "clamp_pending_paid_spins": chunk_clamp_pending_paid_spins,
        "clamp_pending_robots": chunk_clamp_pending_robots,
        "cycle_peaks": list(chunk_cycle_peaks),
        "final_cc_values": list(chunk_final_cc_values),
        "completed_cycles": chunk_completed_cycles,
        # Raw-data analyses.
        "payline_symbol_joint": {k: dict(v) for k, v in payline_symbol_joint.items()},
        "session_rtp_curves": session_rtp_curves,
        "chain_ratio_sequences": chain_ratio_sequences,
        "reel_position_hits": dict(reel_position_hits),
        "chains_by_feature": {
            feat: {
                "lengths": fb["lengths"],
                "max_ratios": fb["max_ratios"],
                "retrigger_events": fb["retrigger_events"],
                "total_rounds": fb["total_rounds"],
                "retrigger_rounds": fb["retrigger_rounds"],
                "extra_ratio_counts": {str(k): v for k, v in fb["extra_ratio_counts"].items()},
                "ratio_sequences": fb["ratio_sequences"],
            }
            for feat, fb in chunk_chains_by_feature.items()
        },
        # --- Session-level counters (see session refactor commit). Summary
        #     derives hit_and_payout / multiplier_profile / streaks /
        #     volatility from these so bonus wins attribute back to the
        #     paid spin that triggered them, not to their own round.
        "paid_session_count": paid_session_count,
        "bonus_spin_count": bonus_spin_count,
        "session_win_count": session_win_count,
        "session_lose_count": session_lose_count,
        "session_profit_count": session_profit_count,
        "session_breakeven_count": session_breakeven_count,
        "session_big_win_x10_count": session_big_win_x10_count,
        "session_ret_count": session_ret_count,
        "session_ret_sum": session_ret_sum,
        "session_ret_sq_sum": session_ret_sq_sum,
        "session_max_return_x": session_max_return_x,
        "session_win_sum": session_win_sum,
        "session_bucket_spins": dict(session_bucket_spins),
        "session_bucket_bet": dict(session_bucket_bet),
        "session_bucket_win": dict(session_bucket_win),
        "session_loss_streak_hist": dict(session_loss_streak_hist),
        "session_win_streak_hist": dict(session_win_streak_hist),
        "session_max_loss_streak": session_max_loss_streak,
        "session_max_win_streak": session_max_win_streak,
        # Extra fields not in _BASELINE_ROUND_FIELDS — surfaced in the
        # report's field_discovery section so operators know which
        # machine-specific data is available for future analysis.
        "extra_fields_seen": dict(extra_fields_seen),
        # Per-machine mechanic accumulators.
        "lock_lines_spins": lock_lines_spins,
        "lock_lines_total_lines": lock_lines_total_lines,
        "lock_lines_win": lock_lines_win,
        "lock_symbols_spins": lock_symbols_spins,
        "lock_symbols_unique": sorted(lock_symbols_unique),
        "lock_symbols_win": lock_symbols_win,
        "lock_reels_spins": lock_reels_spins,
        "lock_reels_win": lock_reels_win,
        "jackpot_spins": jackpot_spins,
        "jackpot_ids_seen": sorted(jackpot_ids_seen),
        "jackpot_win": jackpot_win,
        "freespin_chain_spins": freespin_chain_spins,
        "freespin_retriggers": freespin_retriggers,
        "freespin_max_chain": freespin_max_chain,
        "freespin_win": freespin_win,
        "dollar_pick_spins": dollar_pick_spins,
        "dollar_pick_total_dollars": dollar_pick_total_dollars,
        "dollar_pick_win": dollar_pick_win,
    }


def run_bankruptcy_probe(
    machine: str,
    rtp_mode: int,
    bet: int,
    session_spins: int,
    robot_count: int,
    bankroll_mult: int,
    timeout: float,
) -> dict[str, Any]:
    init_credits = bankroll_mult * bet
    payload = make_payload(
        machine=machine,
        rtp_mode=rtp_mode,
        bet=bet,
        spin_times=session_spins,
        robot_count=robot_count,
        init_credits=init_credits,
        reset_each_spin=False,
        continue_after_bankrupt=False,
    )
    resp = post_json(payload, timeout)
    if not isinstance(resp, list):
        raise ValueError("bankruptcy probe response is not list")

    bankrupt = 0
    completed = 0
    spins_done_sum = 0
    for robot in resp:
        if not isinstance(robot, dict):
            continue
        rounds = parse_rounds(robot)
        spins_done = len(rounds)
        spins_done_sum += spins_done
        if spins_done < session_spins:
            bankrupt += 1
        else:
            completed += 1

    total = len(resp)
    return {
        "bankroll_multiplier": bankroll_mult,
        "init_credits": init_credits,
        "session_spins": session_spins,
        "robots": total,
        "bankrupt_robots": bankrupt,
        "completed_robots": completed,
        "bankruptcy_rate": (bankrupt / total) if total > 0 else 0.0,
        "avg_spins_completed": (spins_done_sum / total) if total > 0 else 0.0,
    }


def main() -> int:
    global ENDPOINT_URL
    args = parse_args()

    if args.endpoint_url:
        ENDPOINT_URL = args.endpoint_url

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
    spin_type_spins: dict[int, int] = defaultdict(int)
    spin_type_next_counts: dict[int, Counter] = defaultdict(Counter)
    spin_type_remarks_sample: dict[int, list[str]] = defaultdict(list)
    spin_type_bucket_spins: dict[int, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    spin_type_bucket_bet: dict[int, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    spin_type_bucket_win: dict[int, dict[str, float]] = defaultdict(
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
    cumulative_failed_chunks = 0
    consecutive_failed_batches = 0

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
        chunk_files = sorted(cache_read_dir.glob("chunk_*.json"))
        # Read-only mode demands a non-empty cache; resume mode is
        # happy to start fresh (cache dir just happens to be empty
        # on the first resume call).
        if not chunk_files and not resume_mode:
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
        max_existing_idx = 0
        tag = "--resume-from-cache" if resume_mode else "--from-cache"

        for cf in chunk_files:
            try:
                raw = load_chunk_envelope(cf)
            except ChunkIntegrityError as exc:
                raise SystemExit(f"{tag}: {exc}")
            resp = raw.get("response")
            if resp is None:
                raise SystemExit(f"{tag}: {cf.name} missing 'response' key")
            # Honour envelope metadata for bet if present.
            chunk_bet_val = int(raw.get("_bet", args.bet) or args.bet)
            idx = int(raw.get("_chunk_index", next_chunk_index))
            max_existing_idx = max(max_existing_idx, idx)
            rec = parse_chunk_response(resp, idx, chunk_bet_val)
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

        if resume_mode:
            # Prime state so the live sampling loop picks up right after
            # the last cached chunk. New chunks go into the same dir so
            # a subsequent resume sees all of them.
            next_chunk_index = max_existing_idx + 1
            args.chunk_cache_dir = cache_read_dir
            append_jsonl(
                progress_file,
                {
                    "event": "resume_from_cache",
                    "run_id": run_id,
                    "existing_chunks": chunks,
                    "existing_spins": total_spins,
                    "next_chunk_index": next_chunk_index,
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
                    cumulative_failed_chunks = cumulative_failed_chunks + 1
                    append_jsonl(
                        progress_file,
                        {
                            "event": "chunk_failed",
                            "run_id": run_id,
                            "chunk_index": rec.get("index"),
                            "error": rec.get("error"),
                            "cumulative_failed": cumulative_failed_chunks,
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
        if batch_fully_failed:
            # Entire batch failed → consecutive failure counter bumps.
            # N consecutive fully-failed batches = sustained upstream
            # breakage; bail out rather than burn the retry helper
            # indefinitely.
            consecutive_failed_batches += 1
        else:
            consecutive_failed_batches = 0

        # AIMD: halve concurrency + chunk_spins on fully-failed batch,
        # grow back toward user settings on consecutive clean batches.
        # Runs BEFORE the bail threshold check so the `adaptive_tune`
        # event fires even on the batch that trips bail (useful for
        # post-mortem).
        new_conc, new_spins, new_streak, should_pause = aimd_tune(
            current_concurrency,
            current_chunk_spins,
            args.batch_concurrency,
            args.chunk_spin_times,
            batch_fully_failed,
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
                    "direction": "down" if batch_fully_failed else "up",
                    "reason": (
                        "fully_failed_batch" if batch_fully_failed
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

        if (
            consecutive_failed_batches >= MAX_CONSECUTIVE_FAILED_BATCHES
            or cumulative_failed_chunks >= MAX_CUMULATIVE_FAILED_CHUNKS
        ):
            last_err = failed_results[0] if failed_results else {}
            stop_reason = (
                f"upstream_unstable:"
                f"consecutive_failed_batches={consecutive_failed_batches},"
                f"cumulative_failed_chunks={cumulative_failed_chunks},"
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
    rtp_point_pct = (
        (total_win / effective_bet_for_rtp) * 100.0 if effective_bet_for_rtp > 0 else 0.0
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

    payout_group_rows: list[dict[str, Any]] = []
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
    payout_id_rows: list[dict[str, Any]] = []
    for pid, wins in sorted(payout_id_win.items(), key=lambda kv: kv[1], reverse=True):
        hits = int(payout_id_hits.get(pid, 0))
        wins_f = float(wins)
        payout_id_rows.append(
            {
                "payout_id": str(pid),
                "hit_count": hits,
                "hit_rate": (hits / total_spins) if total_spins > 0 else 0.0,
                "total_win": wins_f,
                "avg_win_when_hit": (wins_f / hits) if hits > 0 else 0.0,
                "rtp_contribution_pp": (
                    (wins_f / total_bet) * 100.0 if total_bet > 0 else 0.0
                ),
            }
        )

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

    # Preload BCM pairing (config → heuristic) once. Falls back the
    # "BuffCollectionMap" feature to its cycle-pair when SpinType
    # inference can't bind it (BCM is per-spin background state, not
    # a round-level type — never has its own SpinType count).
    _bcm_bonus_feature, _bcm_bonus_source = _resolve_bonus_feature(
        args.machine, args.rtp_mode,
        upstream_feature_tally, _load_bcm_pairings(),
    )

    # Post-process bonus-chain summaries into per-path accumulators
    # (keyed by (feature, label)). User feedback 2026-04-19: the
    # previous sub_streams structure nested all paths under one feature
    # row but kept the bucket distribution SHARED — so operators
    # couldn't tell the via-wheel vs via-BCM paths apart at the bucket
    # level. Now each (feature, label) path carries its own bucket
    # histograms aggregated from chain_bucket_{spins,bet,win}, and the
    # feature assembly emits a SEPARATE row per path when N paths ≥ 2.
    _sub_stream_acc: dict[tuple, dict[str, Any]] = defaultdict(
        lambda: {
            "fires": 0, "win": 0.0, "bet": 0.0,
            "bucket_spins": defaultdict(int),
            "bucket_bet": defaultdict(float),
            "bucket_win": defaultdict(float),
        }
    )
    for (first_st, cc_reset, sp_type), stats in chain_chunk_summaries.items():
        feat_in_chain = spin_type_to_feature.get(int(sp_type))
        if not feat_in_chain:
            continue
        if cc_reset:
            label = "via BCM cycle"
        else:
            entry_feat = spin_type_to_feature.get(int(first_st))
            label = f"via {entry_feat}" if entry_feat else f"via ST{first_st}"
        key = (feat_in_chain, label)
        acc = _sub_stream_acc[key]
        acc["fires"] += int(stats["count"] or 0)
        acc["win"] += float(stats["win"] or 0)
        acc["bet"] += float(stats["bet"] or 0)
        # Aggregate per-path bucket histograms keyed by the same tuple.
        bkey = (first_st, cc_reset, sp_type)
        for bname, c in (chain_bucket_spins.get(bkey) or {}).items():
            acc["bucket_spins"][bname] += int(c or 0)
        for bname, v in (chain_bucket_bet.get(bkey) or {}).items():
            acc["bucket_bet"][bname] += float(v or 0.0)
        for bname, v in (chain_bucket_win.get(bkey) or {}).items():
            acc["bucket_win"][bname] += float(v or 0.0)
    sub_streams_by_feature: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (feat_name, label), stats in _sub_stream_acc.items():
        fires = int(stats["fires"])
        win = float(stats["win"])
        rtp_pp = (win / effective_bet_for_rtp * 100.0) if effective_bet_for_rtp > 0 else 0.0
        sub_streams_by_feature[feat_name].append({
            "label": label,
            "fires": fires,
            "win_credits": win,
            "rtp_contribution_pp": rtp_pp,
            "bucket_spins": dict(stats["bucket_spins"]),
            "bucket_bet": dict(stats["bucket_bet"]),
            "bucket_win": dict(stats["bucket_win"]),
        })
    for rows in sub_streams_by_feature.values():
        rows.sort(key=lambda r: -r["win_credits"])

    upstream_feature_rows: list[dict[str, Any]] = []
    for feat_name, payouts in upstream_feature_tally.items():
        feat_total_win = sum(p.get("win", 0.0) for p in payouts.values())
        feat_total_times = sum(int(p.get("times", 0)) for p in payouts.values())
        # Keep full payout breakdown — UI filters what it shows but
        # the raw tally (including the -1 "no-pay" bucket for trigger
        # features) is useful for LLM interpretation and drill-down.
        payout_rows = []
        for pid, entry in sorted(
            payouts.items(),
            key=lambda kv: (-float(kv[1].get("win", 0.0)), kv[0]),
        ):
            payout_rows.append(
                {
                    "payout_id": str(pid),
                    "win_credits": float(entry.get("win", 0.0)),
                    "times": int(entry.get("times", 0)),
                    "share_of_feature_win": (
                        float(entry.get("win", 0.0)) / feat_total_win
                        if feat_total_win > 0 else 0.0
                    ),
                }
            )
        # Trigger-only detection: feature fires (times > 0) but
        # direct win credits are zero. These are ceremony/gate/
        # selection features that route to a paying parent. We
        # infer the parent via SpinType transition counts.
        trigger_only = feat_total_times > 0 and feat_total_win == 0.0
        # Chain-parent inference. Requires a resolved SpinType
        # mapping for this feature AND observed transitions.
        chain_parent_feature: str | None = None
        chain_parent_share: float = 0.0
        chain_parent_confidence: str = "none"
        chain_parent_next_fires: int = 0
        resolved_spin_type = feature_to_spin_type.get(feat_name)
        if resolved_spin_type is not None:
            transitions = spin_type_next_counts.get(resolved_spin_type) or Counter()
            total_edges = sum(transitions.values())
            if total_edges > 0:
                # Most common next SpinType — that's the likely chain
                # target (what comes after this feature in the round
                # sequence). Skip self-loops (bonus retriggers) since
                # they don't reveal the parent relationship.
                ranked = sorted(
                    (
                        (int(st_to), int(cnt))
                        for st_to, cnt in transitions.items()
                        if int(st_to) != resolved_spin_type
                    ),
                    key=lambda kv: -kv[1],
                )
                if ranked:
                    best_st, best_cnt = ranked[0]
                    parent_feat = spin_type_to_feature.get(best_st)
                    if parent_feat:
                        chain_parent_feature = parent_feat
                        chain_parent_next_fires = best_cnt
                        chain_parent_share = best_cnt / total_edges
                        if chain_parent_share >= 0.80:
                            chain_parent_confidence = "high"
                        elif chain_parent_share >= 0.50:
                            chain_parent_confidence = "medium"
                        else:
                            chain_parent_confidence = "low"
        # BCM fallback: "BuffCollectionMap" has no round-level
        # SpinType (it's a per-spin CollectCount cycle, not its own
        # round type). When SpinType inference can't bind it, use
        # the BCM pairing resolved from configs/bcm_pairings.json
        # (or the heuristic "biggest-win non-normal feature" fallback).
        if (
            str(feat_name) == "BuffCollectionMap"
            and chain_parent_feature is None
            and _bcm_bonus_feature
        ):
            chain_parent_feature = _bcm_bonus_feature
            chain_parent_confidence = (
                "high" if _bcm_bonus_source == "config" else "medium"
            )
            # BCM cycles feed the bonus feature — treat every cycle
            # reset as 100% chaining into the paired feature.
            chain_parent_share = 1.0
            chain_parent_next_fires = feat_total_times
        fire_rate = feat_total_times / total_spins if total_spins > 0 else 0.0
        # Per-feature multiplier bucket histogram. Same shape as the
        # global multiplier_profile.buckets so the UI can reuse the
        # bucket-bar renderer. Requires resolved SpinType (binds the
        # feature to round-level win data); session-level meta
        # features (no SpinType binding) get an empty list.
        #
        # ``total_bet`` passed below is the GLOBAL paid-bet
        # denominator (same as feat_total_win in the header). This
        # makes each bucket's ``rtp_contribution_pp`` a slice of the
        # global RTP — the per-feature bucket pp values sum to the
        # feature header's ``rtp_contribution_pp``. Using the
        # per-feature bet as the denominator (the other option) would
        # inflate bucket pp for bonus features (freespin rounds run
        # 3-4× RTP on their own bet denominator, which is confusing
        # vs the 41pp header).
        feat_bucket_rows: list[dict[str, Any]] = []
        feat_bucket_total_win = 0.0
        feat_bucket_total_spins = 0
        if resolved_spin_type is not None:
            st_b_spins = spin_type_bucket_spins.get(resolved_spin_type) or {}
            st_b_bet = spin_type_bucket_bet.get(resolved_spin_type) or {}
            st_b_win = spin_type_bucket_win.get(resolved_spin_type) or {}
            feat_bucket_total_spins = sum(st_b_spins.values())
            feat_bucket_total_win = sum(st_b_win.values())
            feat_bucket_rows = build_multiplier_bucket_rows(
                st_b_spins,
                st_b_bet,
                st_b_win,
                feat_bucket_total_spins,
                effective_bet_for_rtp,  # global denominator — see note above
                feat_bucket_total_win,
            )
        # Fix 2 (2026-04-19 round 5): if ≥2 trigger paths exist for
        # this feature, emit one row PER PATH with a path-specific
        # bucket distribution. Naming convention: "{feat_name} [{label}]".
        # The frontend's feature-breakdown renders these as separate
        # cards automatically — no UI code change needed.
        feat_subs = sub_streams_by_feature.get(feat_name, [])
        common = {
            "trigger_only": trigger_only,
            "resolved_spin_type": resolved_spin_type,
            "spin_type_binding_ambiguous": feat_name in ambiguous_mapped,
            "chain_parent_feature": chain_parent_feature,
            "chain_parent_confidence": chain_parent_confidence,
            "chain_parent_share": chain_parent_share,
            "chain_parent_next_fires": chain_parent_next_fires,
        }
        # Only split PAYING features into per-path rows. Trigger-only
        # features (WheelSelector / PreWheel / etc.) have direct_win=0
        # on every path — splitting them produces N identical RTP=0
        # rows that clutter the breakdown without adding signal.
        if len(feat_subs) >= 2 and not trigger_only:
            # Aggregate bet from chain sub_streams (per-path) — use for
            # fire_rate calc when splitting.
            for sub in feat_subs:
                p_win = float(sub.get("win_credits", 0.0))
                p_fires = int(sub.get("fires", 0))
                p_bucket_spins = sub.get("bucket_spins") or {}
                p_bucket_bet = sub.get("bucket_bet") or {}
                p_bucket_win = sub.get("bucket_win") or {}
                p_total_spins = sum(p_bucket_spins.values())
                p_total_win = sum(p_bucket_win.values())
                p_bucket_rows = (
                    build_multiplier_bucket_rows(
                        p_bucket_spins, p_bucket_bet, p_bucket_win,
                        p_total_spins, effective_bet_for_rtp, p_total_win,
                    )
                    if p_total_spins > 0 else []
                )
                p_fire_rate = (p_fires / total_spins) if total_spins > 0 else 0.0
                label = sub.get("label", "")
                display_name = f"{feat_name} [{label}]"
                upstream_feature_rows.append({
                    "feature_name": display_name,
                    "feature_base_name": str(feat_name),
                    "trigger_path_label": label,
                    "total_win": p_win,
                    "total_times": p_fires,
                    "fires_spins": p_fires,
                    "fire_rate": p_fire_rate,
                    "direct_win_credits": p_win,
                    "bucket_distribution": p_bucket_rows,
                    "bucket_total_spins": p_total_spins,
                    "sub_streams": [],  # split into separate rows, no nesting
                    "rtp_contribution_pp": (
                        (p_win / effective_bet_for_rtp) * 100.0
                        if effective_bet_for_rtp > 0 else 0.0
                    ),
                    "share_of_total_win": (
                        p_win / upstream_total_win
                        if upstream_total_win > 0 else 0.0
                    ),
                    # payout_rows is feature-aggregate (not path-specific);
                    # attach to first path for accessibility, keep empty
                    # for the rest.
                    "payouts": payout_rows if sub is feat_subs[0] else [],
                    **common,
                })
            # Skip the aggregate row append below — continue outer loop.
            continue

        # Single-path (or no-path) case: emit the aggregate row as before.
        upstream_feature_rows.append(
            {
                "feature_name": str(feat_name),
                "total_win": feat_total_win,
                "total_times": feat_total_times,
                "fires_spins": feat_total_times,
                "fire_rate": fire_rate,
                "direct_win_credits": feat_total_win,
                "bucket_distribution": feat_bucket_rows,
                "bucket_total_spins": feat_bucket_total_spins,
                "sub_streams": feat_subs,
                "rtp_contribution_pp": (
                    (feat_total_win / effective_bet_for_rtp) * 100.0
                    if effective_bet_for_rtp > 0 else 0.0
                ),
                "share_of_total_win": (
                    feat_total_win / upstream_total_win
                    if upstream_total_win > 0 else 0.0
                ),
                "payouts": payout_rows,
                **common,
            }
        )
    # Sort: payers first (by total_win desc), then trigger-only
    # features (by fires desc). Keeps the pay hierarchy readable
    # while still surfacing ceremony features after.
    upstream_feature_rows.sort(
        key=lambda row: (
            1 if row["trigger_only"] else 0,
            -float(row["total_win"]),
            -int(row["fires_spins"]),
        )
    )
    # Machines with a single "Normal" feature carry no bonus-mechanic
    # info in this block (it's a duplicate of payout_ids_top20 through a
    # different field). Flagging applicable=False lets the UI / LLM
    # suppress the section for those machines.
    has_multiple_features = len(upstream_feature_tally) > 1
    has_bonus_named_feature = any(
        name != "Normal" for name in upstream_feature_tally.keys()
    )
    upstream_feature_applicable = bool(
        upstream_feature_tally and (has_multiple_features or has_bonus_named_feature)
    )

    # Bonus-chain dynamics aggregation from ReMarks. On machines
    # without freespin annotations (M14), all the collected lists are
    # empty and the block flags applicable=False. On MapCollection
    # machines (M272) this gives quantiles of chain length, peak ratio,
    # and the energy-ramp curve -- the real window into the "map
    # collection bonus" experience the aggregate RTP can't describe.
    def _quantiles(xs: list[int]) -> dict[str, int | float]:
        if not xs:
            return {"p50": 0, "p90": 0, "p95": 0, "max": 0, "avg": 0.0}
        xs_sorted = sorted(xs)
        n = len(xs_sorted)
        def q(p: float) -> int:
            if n == 0:
                return 0
            idx = min(n - 1, max(0, int(round(p * (n - 1)))))
            return int(xs_sorted[idx])
        return {
            "p50": q(0.50),
            "p90": q(0.90),
            "p95": q(0.95),
            "max": int(xs_sorted[-1]),
            "avg": sum(xs_sorted) / n,
        }

    depth_curve: list[dict[str, Any]] = []
    for bucket in ("1", "2-5", "6-10", "11-20", "21+"):
        cnt = bonus_depth_ratio_count.get(bucket, 0)
        tot = bonus_depth_ratio_sum.get(bucket, 0.0)
        depth_curve.append(
            {
                "depth_bucket": bucket,
                "rounds": int(cnt),
                "avg_extra_ratio": (tot / cnt) if cnt > 0 else 0.0,
            }
        )
    bonus_chain_count = len(bonus_chain_lengths)
    bonus_chain_dynamics = {
        "applicable": bonus_chain_count > 0,
        "source": "ReMarks (Freespin annotation)",
        "chain_count": bonus_chain_count,
        "bonus_round_count": bonus_total_rounds_global,
        "avg_chain_length": (
            sum(bonus_chain_lengths) / bonus_chain_count
            if bonus_chain_count > 0 else 0.0
        ),
        "chain_length_quantiles": _quantiles(bonus_chain_lengths),
        "chain_max_ratio_quantiles": _quantiles(bonus_chain_max_ratios),
        "self_retrigger_round_rate": (
            bonus_retrigger_rounds_global / bonus_total_rounds_global
            if bonus_total_rounds_global > 0 else 0.0
        ),
        "avg_retriggers_per_chain": (
            sum(bonus_chain_retrigger_events) / bonus_chain_count
            if bonus_chain_count > 0 else 0.0
        ),
        # Sorted by ratio ascending so the histogram reads naturally
        # left-to-right; counts are per-round (same round may not
        # double-count because each round emits exactly one ratio).
        "extra_ratio_histogram": [
            {"ratio": r, "rounds": bonus_extra_ratio_counts[r]}
            for r in sorted(bonus_extra_ratio_counts.keys())
        ],
        # Energy ramp: average ExtraRatio at each chain depth bucket.
        # Shows how the MapCollection multiplier escalates as the
        # chain extends.
        "extra_ratio_by_chain_depth": depth_curve,
        # Per-feature breakdown: same structure as aggregate but split
        # by trigger type. NormalCollectionSpin = random (PayId 666),
        # NewFreespin = forced at cycle boundary (no PayId). Empty
        # features are omitted.
        "by_feature": {
            feat: {
                "chain_count": len(afb["lengths"]),
                "bonus_round_count": afb["total_rounds"],
                "avg_chain_length": (
                    sum(afb["lengths"]) / len(afb["lengths"])
                    if afb["lengths"] else 0.0
                ),
                "chain_length_quantiles": _quantiles(afb["lengths"]),
                "chain_max_ratio_quantiles": _quantiles(afb["max_ratios"]),
                "self_retrigger_round_rate": (
                    afb["retrigger_rounds"] / afb["total_rounds"]
                    if afb["total_rounds"] > 0 else 0.0
                ),
            }
            for feat, afb in all_chains_by_feature.items()
            if afb["lengths"]
        },
    }

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

    bankruptcy_rows = []
    mults = [
        int(x.strip())
        for x in args.bankruptcy_bankroll_multipliers.split(",")
        if x.strip()
    ]
    probe_robots = (
        args.bankruptcy_robot_count
        if args.bankruptcy_robot_count is not None
        else args.chunk_robot_count
    )

    # `--from-cache` means "reproduce report from cached sampling data,
    # no live network calls". The bankruptcy probe makes fresh HTTP calls
    # to the upstream API, which (a) defeats cache reproducibility and
    # (b) under batch concurrency of 16+ triggers upstream throttling
    # that inflates per-job wall time 10× (6s → 60s). Skip it here; the
    # quality label already degrades to EXPLORATORY when the ladder
    # is missing, which correctly signals the report's reduced grade.
    skip_bankruptcy = args.from_cache is not None
    if skip_bankruptcy:
        mults = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(mults) or 1)) as executor:
        future_map = {
            executor.submit(
                run_bankruptcy_probe,
                args.machine,
                args.rtp_mode,
                args.bet,
                args.bankruptcy_session_spins,
                probe_robots,
                m,
                args.timeout,
            ): m
            for m in mults
        }
        for future in concurrent.futures.as_completed(future_map):
            m = future_map[future]
            try:
                bankruptcy_rows.append(future.result())
            except Exception as exc:  # noqa: BLE001
                bankruptcy_rows.append(
                    {
                        "bankroll_multiplier": m,
                        "error": exc.__class__.__name__,
                    }
                )
    bankruptcy_rows.sort(key=lambda row: int(row.get("bankroll_multiplier", 0)))

    ci_met = achieved_halfwidth_pp is not None and achieved_halfwidth_pp <= args.target_halfwidth_pp
    sample_size_met = total_spins >= 2_000_000
    buckets_complete = len(multiplier_bucket_rows) == len(RETURN_BUCKET_ORDER)
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
    # Primary source: machines.json (the ground truth at analyzer invocation).
    _summary_config_md5, _summary_code_md5 = _lookup_machine_md5(args.machine)
    _summary_analyzer_version = compute_analyzer_version()
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
        "output_all_robots_result": True,
        "sampling": {
            "target_halfwidth_pp": args.target_halfwidth_pp,
            "achieved_halfwidth_pp": achieved_halfwidth_pp,
            "chunk_level_halfwidth_pp": chunk_level_halfwidth_pp,
            "session_level_halfwidth_pp": session_level_halfwidth_pp,
            "chunk_spin_times": args.chunk_spin_times,
            "chunk_robot_count": args.chunk_robot_count,
            "batch_concurrency": args.batch_concurrency,
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
            "multiplier_profile": {
                "metric": "ret_x = session_win / session_bet (paid bet only)",
                "buckets": multiplier_bucket_rows,
                "tail_spin_rate_ge10x": (
                    tail_spins_ge10 / mb_total_spins if mb_total_spins > 0 else 0.0
                ),
                "tail_rtp_contribution_pp_ge10x": tail_rtp_contribution_pp_ge10x,
                "tail_win_share_ge10x": tail_win_share_ge10x,
            },
            "hit_and_payout": {
                "win_hit_rate": hit_rate,
                "zero_win_rate": zero_win_rate,
                "profit_spin_rate": profit_spin_rate,
                "breakeven_or_more_rate": breakeven_or_more_rate,
                "big_win_x10_rate": big_win_x10_rate,
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
            "paylines_top20": payline_rows[:20],
            "payout_groups_top20": payout_group_rows[:20],
            "payout_ids_top20": payout_id_rows[:20],
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
            # Per-machine mechanic analysis. Sections are only present
            # when the mechanic's fields were observed (applicable=true).
            "machine_mechanics": {
                "lock_lines": {
                    "applicable": total_lock_lines_spins > 0,
                    "lock_spins": total_lock_lines_spins,
                    "lock_rate": (total_lock_lines_spins / total_spins) if total_spins > 0 else 0,
                    "total_lines_locked": total_lock_lines_total_lines,
                    "avg_lines_per_lock": (total_lock_lines_total_lines / total_lock_lines_spins) if total_lock_lines_spins > 0 else 0,
                    "lock_win": total_lock_lines_win,
                    "lock_rtp_contribution_pp": (total_lock_lines_win / effective_bet_for_rtp * 100) if effective_bet_for_rtp > 0 else 0,
                },
                "lock_symbols": {
                    "applicable": total_lock_symbols_spins > 0,
                    "lock_spins": total_lock_symbols_spins,
                    "lock_rate": (total_lock_symbols_spins / total_spins) if total_spins > 0 else 0,
                    "unique_symbols": sorted(total_lock_symbols_unique),
                    "unique_symbol_count": len(total_lock_symbols_unique),
                    "lock_win": total_lock_symbols_win,
                    "lock_rtp_contribution_pp": (total_lock_symbols_win / effective_bet_for_rtp * 100) if effective_bet_for_rtp > 0 else 0,
                },
                "lock_reels": {
                    "applicable": total_lock_reels_spins > 0,
                    "lock_spins": total_lock_reels_spins,
                    "lock_rate": (total_lock_reels_spins / total_spins) if total_spins > 0 else 0,
                    "lock_win": total_lock_reels_win,
                    "lock_rtp_contribution_pp": (total_lock_reels_win / effective_bet_for_rtp * 100) if effective_bet_for_rtp > 0 else 0,
                },
                "jackpot": {
                    "applicable": total_jackpot_spins > 0,
                    "trigger_spins": total_jackpot_spins,
                    "trigger_rate": (total_jackpot_spins / total_spins) if total_spins > 0 else 0,
                    "jackpot_ids": sorted(total_jackpot_ids_seen),
                    "jackpot_id_count": len(total_jackpot_ids_seen),
                    "total_win": total_jackpot_win,
                    "rtp_contribution_pp": (total_jackpot_win / effective_bet_for_rtp * 100) if effective_bet_for_rtp > 0 else 0,
                },
                "free_spin": {
                    "applicable": total_freespin_chain_spins > 0,
                    "chain_spins": total_freespin_chain_spins,
                    "chain_rate": (total_freespin_chain_spins / total_spins) if total_spins > 0 else 0,
                    "retriggers": total_freespin_retriggers,
                    "max_chain_length": total_freespin_max_chain,
                    "total_win": total_freespin_win,
                    "rtp_contribution_pp": (total_freespin_win / effective_bet_for_rtp * 100) if effective_bet_for_rtp > 0 else 0,
                },
                "dollar_pick": {
                    "applicable": total_dollar_pick_spins > 0,
                    "pick_spins": total_dollar_pick_spins,
                    "pick_rate": (total_dollar_pick_spins / total_spins) if total_spins > 0 else 0,
                    "total_dollars_picked": total_dollar_pick_total_dollars,
                    "avg_dollars_per_pick": (total_dollar_pick_total_dollars / total_dollar_pick_spins) if total_dollar_pick_spins > 0 else 0,
                    "total_win": total_dollar_pick_win,
                    "rtp_contribution_pp": (total_dollar_pick_win / effective_bet_for_rtp * 100) if effective_bet_for_rtp > 0 else 0,
                },
            },
            "upstream_feature_breakdown": {
                "applicable": upstream_feature_applicable,
                "source": "analysisResult.FeatureWin",
                "features": upstream_feature_rows,
            },
            "bonus_chain_dynamics": bonus_chain_dynamics,
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
            )[:20],
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
            )[:20],
            "symbols_top20": symbol_rows[:20],
            "symbols_by_column_top10": {k: v[:10] for k, v in symbol_by_col_rows.items()},
            "bankruptcy_probe": bankruptcy_rows,
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
        "collect_mechanic": {
            # M272+ collect mechanic: total CollectCount triggers across
            # all robots, plus peak AccCredits seen. M14 (and any other
            # non-collect machine) reports applicable=false so the
            # frontend / interpretation can suppress the section
            # entirely. avg_spins_between_collects is null when no
            # triggers were observed (avoids div-by-zero).
            "applicable": collect_robots_seen_total > 0,
            "robots_with_data": collect_robots_seen_total,
            "total_collects": collect_count_total,
            "max_acc_credits_observed": acc_credits_max_global,
            "avg_spins_between_collects": (
                (total_spins / collect_count_total)
                if collect_count_total > 0
                else None
            ),
            # Trunk-clamp warning. When chunk_spin_times truncates the
            # robot's run mid-cycle (paid spins accumulated past the
            # last collect-trigger but the next one never fires before
            # SpinTimes runs out), the bonus that those pending paid
            # spins would have eventually triggered is missing from the
            # sample -- observed RTP under-reports the true RTP. We
            # surface the raw signals (pending counts + avg paid spins
            # per collect) instead of fabricating a lost_pp number,
            # because the bonus payout per collect varies a lot per
            # machine and a heuristic estimate gives false confidence.
            # Operator interpretation: if pending_robots is large and
            # pending_paid_spins / paid_spins is non-trivial, widen
            # chunk_spin_times and rerun.
            "clamp_warning": {
                "applicable": (
                    collect_robots_seen_total > 0
                    and clamp_pending_robots_total > 0
                ),
                "pending_robots": clamp_pending_robots_total,
                "total_pending_paid_spins": clamp_pending_paid_spins_total,
                "pending_share_of_paid_spins": (
                    (clamp_pending_paid_spins_total / total_paid_sessions)
                    if total_paid_sessions > 0
                    else None
                ),
                "avg_paid_spins_per_collect": (
                    (total_paid_sessions / collect_count_total)
                    if collect_count_total > 0
                    else None
                ),
                "note": (
                    "Pending paid spins were accumulating toward the next collect "
                    "trigger when chunk_spin_times ran out; the bonus those spins "
                    "would have triggered isn't in the sample. If this is a large "
                    "fraction of total paid spins, widen chunk_spin_times and "
                    "rerun to get a tighter RTP estimate."
                ) if (
                    collect_robots_seen_total > 0 and clamp_pending_robots_total > 0
                ) else None,
            },
            # BCM cycle-bonus RTP correction. When the
            # BuffCollectionMap cycle doesn't complete (chunk ends
            # mid-cycle), the bonus that fires at cycle completion is
            # missing from the sample. This block estimates the lost
            # RTP based on:
            #   - detected cycle length (median of observed CC peaks)
            #   - average payout of the machine's bonus feature (resolved
            #     per-machine via configs/bcm_pairings.json → heuristic
            #     fallback; see _resolve_bonus_feature)
            #   - each robot's final CC as fraction of cycle length
            #
            # Previously hardcoded to "NewFreespin" — worked for ~13/33
            # BCM machines, silently under-reported the rest. Now
            # self-resolving with operator-override.
            "bonus_cycle_correction": (lambda: (lambda bonus_feat, bonus_src: {
                "applicable": len(all_cycle_peaks) > 0,
                "bonus_feature": bonus_feat,
                "bonus_feature_source": bonus_src,
                "detected_cycle_length": (
                    int(sorted(all_cycle_peaks)[len(all_cycle_peaks)//2])
                    if all_cycle_peaks else None
                ),
                "completed_cycles_total": total_completed_cycles,
                "robots_with_pending_cycle": sum(
                    1 for fcc in all_final_cc_values
                    if all_cycle_peaks and fcc < sorted(all_cycle_peaks)[len(all_cycle_peaks)//2]
                ),
                "avg_bonus_payout": (
                    (lambda bonus_total, cyc: bonus_total / cyc if cyc > 0 else None)(
                        sum(
                            float(e.get("win", 0.0))
                            for e in (upstream_feature_tally.get(bonus_feat) or {}).values()
                        ) if bonus_feat else 0.0,
                        total_completed_cycles,
                    )
                ),
                "estimated_correction_pp": _compute_bonus_correction(
                    bonus_feat,
                    all_cycle_peaks, all_final_cc_values,
                    upstream_feature_tally, total_completed_cycles,
                    effective_bet_for_rtp,
                ),
            })(*_resolve_bonus_feature(
                args.machine, args.rtp_mode, upstream_feature_tally, _load_bcm_pairings()
            )))(),
            # Feature-match block — now driven by the resolved feature
            # instead of a hardcoded check. Warning only fires when a
            # cycle was observed AND neither config nor heuristic
            # could identify a bonus feature (the worst case where RTP
            # correction falls through to 0pp).
            "feature_match": collect_feature_match_warning(
                all_cycle_peaks,
                upstream_feature_tally,
                *_resolve_bonus_feature(
                    args.machine, args.rtp_mode, upstream_feature_tally, _load_bcm_pairings()
                ),
            ),
            # Cycle-observation block: distinguishes "no collect mechanic"
            # from "collect mechanic but cache too short to capture a
            # reset" (M272-style: all robots stopped at CC=1000
            # boundary). Without this, both cases look identical in the
            # summary and operator can't tell if RTP correction is
            # missing or genuinely inapplicable.
            "cycle_observation": build_cycle_observation(
                collect_robots_seen_total,
                all_cycle_peaks,
                all_final_cc_values,
            ),
        },
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

    # Backward-compat alias: keep `newfreespin_correction` pointing at
    # the same dict as `bonus_cycle_correction` so any report-reader
    # still expecting the legacy key keeps working. New code should
    # read `bonus_cycle_correction` directly.
    cm = summary.get("collect_mechanic") or {}
    if "bonus_cycle_correction" in cm and "newfreespin_correction" not in cm:
        cm["newfreespin_correction"] = cm["bonus_cycle_correction"]

    out_json = args.output_dir / "player_impact_summary.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

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

    md_lines.append("")
    md_lines.append("## Bankruptcy Probe")
    for row in bankruptcy_rows:
        if "error" in row:
            md_lines.append(f"- bankroll x{row['bankroll_multiplier']}: error={row['error']}")
        else:
            md_lines.append(
                f"- bankroll x{row['bankroll_multiplier']}: bankruptcy_rate={row['bankruptcy_rate']:.6f}, avg_spins_completed={row['avg_spins_completed']:.2f}"
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
