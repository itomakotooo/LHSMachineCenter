"""Chunk-parsing primitives carved from ``player_impact_analyzer.py``.

P2-B1a (Phase 2 / Wave 2b sub-ticket): moves 14 helper functions, 1
exception class, and 8 module-level constants out of PIA into this
canonical module. PIA re-exports the same symbols (`from
fresh_slotlab.analyzer.core.parser import ...`) so all external
callers — `_batch_gen_worker.py`, `batch_dev_sampler.py`, scripts/,
tests — keep working unchanged.

P2-B1b: parse_chunk_response (the 1857-line orchestrator) moved here.
PIA re-exports it via the dual-path import block (same pattern as
the P2-B1a helpers).

Per memory feedback_subprocess_import_suicide_and_module_globals.md:
  this module is import-safe — constants + function/class defs only;
  no module-top I/O; no implicit network or filesystem reads at
  import time.

Per memory feedback_md5_is_a_tag_not_a_destruction_signal.md:
  load_chunk_envelope raises ChunkIntegrityError on
  _payload_sha256 mismatch; caller decides whether to skip the
  chunk or surface as integrity error. No silent fallback to a
  corrupt response payload.
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# P2-B2: dual-path import of shared utility helpers that were duplicated
# here by P2-B1b to break the cycle.  Now that _utils.py is the canonical
# source, the duplicates below are deleted and replaced with this import.
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
except ImportError:  # running as a standalone script (fresh_slotlab/ on sys.path)
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

# Dual-path import for round-classification / round-win / trigger-session
# helpers consumed by parse_chunk_response.  Mirrors the pattern used in
# player_impact_analyzer.py: package-style import in the try block,
# standalone-script fallback in the except block.
# P2-B1b: these were implicitly available to parse_chunk_response when the
# function lived inside PIA (which already performed the dual-path import).
# Now that the function lives here we must make the same imports explicit.
try:
    from fresh_slotlab.trigger_sessions import compute_trigger_sessions
    from fresh_slotlab.round_classification import attribute_lines_to_pay_ids
    from fresh_slotlab.analyzer.play_types.bcm_cycle import (
        compute_robot_cycle_peaks,
        detect_cycle_peak,
    )
    from fresh_slotlab.analyzer.play_types.wild_nudge import is_wild_nudge_round
    from fresh_slotlab.round_win import (
        RoundWinRule,
        extract_round_payouts,
        extract_round_win,
    )
except ImportError:  # running as a standalone script
    from trigger_sessions import compute_trigger_sessions  # type: ignore[no-redef]
    from round_classification import attribute_lines_to_pay_ids  # type: ignore[no-redef]
    from analyzer.play_types.bcm_cycle import (  # type: ignore[no-redef]
        compute_robot_cycle_peaks,
        detect_cycle_peak,
    )
    from analyzer.play_types.wild_nudge import is_wild_nudge_round  # type: ignore[no-redef]
    from round_win import (  # type: ignore[no-redef]
        RoundWinRule,
        extract_round_payouts,
        extract_round_win,
    )

# Payline format ``"1:..2:.."`` — number followed by colon. Used by
# parse_paylines to enumerate the payline indices a winning spin lit.
PAYLINE_RE = re.compile(r"(\d+):")


# ----------------------------------------------------------------------
# Round-schema invariants (used by _check_round_schema)
# ----------------------------------------------------------------------

# Round-level fields the analyzer expects on baseline production data.
# Anything outside this set triggers extra-field discovery (the
# field_discovery panel in the report). Intentionally broad: the set
# enumerates every field name the analyzer's existing code reads.
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


# ----------------------------------------------------------------------
# ReMarks regexes (used by parse_freespin_remarks)
# ----------------------------------------------------------------------

_REMARKS_FREESPIN_RE = re.compile(r"Freespin\s+(\d+)")
_REMARKS_EXTRARATIO_RE = re.compile(r"ExtraRatio:(\d+)")
_REMARKS_ADDFREESPINS_COUNT_RE = re.compile(r"AddFreespins;\s*(\d+)")


# ----------------------------------------------------------------------
# Envelope header peek (used by peek_chunk_envelope)
# ----------------------------------------------------------------------

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
_ENVELOPE_PEEK_BYTES = 4096
_ENVELOPE_PEEK_RE = re.compile(
    r'"_chunk_index"\s*:\s*(\d+).*?'
    r'"_config_md5"\s*:\s*"([^"]*)".*?'
    r'"_code_md5"\s*:\s*"([^"]*)"',
    re.DOTALL,
)


# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------

class ChunkIntegrityError(ValueError):
    """Envelope's stored _payload_sha256 didn't match the recomputed hash.

    Indicates the chunk file is corrupt (partial write from an aborted
    sampler, disk error, filesystem glitch) or was modified after write.
    Distinct from json.JSONDecodeError, which means the envelope itself
    is malformed — this one means the envelope parses cleanly but the
    payload bytes have drifted from what was written.
    """


# ----------------------------------------------------------------------
# Round parsing primitives
# ----------------------------------------------------------------------

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


# ----------------------------------------------------------------------
# Freespin / bonus remark parsers
# ----------------------------------------------------------------------

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


# ----------------------------------------------------------------------
# Chunk envelope I/O + integrity
# ----------------------------------------------------------------------

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


def peek_chunk_envelope(path: Path) -> tuple[int, str, str] | None:
    """Return ``(chunk_index, config_md5, code_md5)`` from the
    envelope header without parsing the whole file.

    Returns ``None`` if any of the three fields isn't found in the
    first ~4KB — caller must fall back to ``load_chunk_envelope``.
    """
    try:
        with path.open("rb") as f:
            head = f.read(_ENVELOPE_PEEK_BYTES)
    except OSError:
        return None
    try:
        text = head.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return None
    m = _ENVELOPE_PEEK_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1)), m.group(2), m.group(3)
    except (ValueError, IndexError):
        return None


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


# ----------------------------------------------------------------------
# to_float, blank_like_symbol, bonus_chain_depth_bucket, return_bucket,
# _DEFAULT_BANKROLL_MULTIPLIERS, _DEFAULT_BANKRUPTCY_SESSION_SPINS,
# _empty_bankruptcy_tier, _extract_bankruptcy_reps,
# simulate_bankruptcy_from_response:
# consolidated into fresh_slotlab.analyzer.core._utils (P2-B2).
# Imported at top of this file via dual-path block; single source of truth.
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# parse_chunk_response — moved from player_impact_analyzer.py (P2-B1b).
# Pure-computation core of the analyzer: no network, no disk I/O.
# PIA re-exports this symbol via its dual-path import block so all
# existing callers keep working unchanged.
# ----------------------------------------------------------------------

def parse_chunk_response(
    resp: Any,
    chunk_index: int,
    bet: int,
    started: float | None = None,
    bankruptcy_session_spins: int = _DEFAULT_BANKRUPTCY_SESSION_SPINS,
    bankruptcy_bankroll_mults: tuple[int, ...] = _DEFAULT_BANKROLL_MULTIPLIERS,
    round_win_rules: list[RoundWinRule] | None = None,
) -> dict[str, Any]:
    """Parse a raw API response (list of robot dicts) into chunk metrics.

    This is the pure-computation core of the analyzer: no network, no
    disk I/O. ``run_sampling_chunk`` calls it after fetching + caching;
    the ``--from-cache`` path calls it directly with data loaded from
    chunk-cache JSON files.

    ``started`` is an optional ``time.time()`` value used only for
    elapsed_seconds in the result dict.

    ``bankruptcy_session_spins`` and ``bankruptcy_bankroll_mults`` drive
    the rawdata-replay bankruptcy simulation (per-chunk histogram
    contribution merged at finalize). Defaults produce the standard
    (100/200/500) × 500-spin ladder even when callers forget to plumb
    through the CLI value.

    Phase D (2026-06-03): the play-type plugin framework (use_play_type_plugins /
    machine_id / mode params) has been deleted.  The inline carve path
    (bcm_cycle, wild_nudge) runs unconditionally — it was already the
    flag-off golden path, so behavior is byte-identical.
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

    # TopDollar session accumulator (Phase E, topdollar_choice feature).
    # Populated per-robot from _trig_sessions_for_robot when ST=14 picks are
    # present.  Only non-empty for M15-family machines; transparent to others.
    # Shape: list[dict] where each dict = one TopDollar session (see feature).
    chunk_topdollar_sessions: list[dict] = []

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
    # Higher tail thresholds — share the paid-round denominator with x10
    # so the four rates align on the same scan of the session outcome.
    session_big_win_x20_count = 0
    session_big_win_x50_count = 0
    session_big_win_x100_count = 0
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
    # 2026-04-24: per-(col, row) symbol counts for payline-density
    # drilldown. "symbol_counts_by_col" counts ALL visible rows (window
    # density — what player's eyeball sees). For "payline density" (what
    # matters for payouts) we need per-row granularity so a
    # machine-specific mask over rows can be applied.
    symbol_counts_by_col_by_row: dict[int, dict[int, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    # Union of row indices observed in PayoutByPayline win positions,
    # grouped by column. Inferred from rawdata (no spec needed):
    # classic single-payline machines will only ever record row=1 (mid),
    # multi-payline machines accumulate {0, 1, 2} or whatever rows their
    # paylines actually visit. Per-col set is preserved so V-shape
    # paylines (row-per-reel varies) are handled without flattening.
    payline_rows_per_col: dict[int, set[int]] = defaultdict(set)
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
    # Per (pay_id, spin_type) hit counts. Finalize uses this to tag
    # each pay_id row with the dominant SpinType + a "paid/bonus/mixed"
    # category, so the UI doesn't need to JOIN the PayID + SpinType
    # panels manually to answer "is this pay_id's RTP coming from
    # paid rounds or bonus?".
    payout_id_by_spin_type: dict[str, dict[int, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    # Per (pay_id, spin_type) WIN amounts. Parallel to payout_id_by_spin_type
    # (which tracks hit counts); this accumulates the credited win per ST so
    # the ST-split payout breakdown can compute per-ST RTP contributions.
    # Added 2026-05-14 for SpinType-split breakdowns (payouts_by_spin_type).
    payout_id_win_by_spin_type: dict[str, dict[int, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    # Per-SpinType symbol counts per column. Mirrors symbol_counts_by_col
    # but keyed by SpinType first so reel_marginal_by_spin_type can show
    # base-game vs freespin symbol distributions separately.
    # Added 2026-05-14 for SpinType-split reel marginal.
    symbol_counts_by_col_by_spin_type: dict[int, dict[int, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )

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
    # 2026-04-27 (Bug 3 fix): track which SpinTypes are wild-nudge
    # continuations of paid spins. is_wild_nudge_round detects via
    # ReMarks containing "move"/"nudge" + CostCredits=0. M279/M226/
    # M149 etc emit ST=36 for the auto-nudge mechanic. The feature
    # is NOT an independent BCM/freespin trigger -- it's the same
    # paid spin extended. Used by finalize to tag the feature row
    # so UI/operator recognizes it as a nudge, and exclude these
    # features from the BCM heuristic candidate list (defensive).
    wild_nudge_spin_types: set[int] = set()
    spin_type_nudge_round_count: dict[int, int] = defaultdict(int)
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
    # Per-SpinType PAID-round-level return-bucket histograms.
    # Mirrors spin_type_bucket_{spins,bet,win} but accumulates ONLY rounds
    # where is_paid==True and bet_amt>0 (free/bonus rounds are excluded so
    # win/bet ratios are well-defined and directly comparable to the global
    # multiplier_profile buckets).  Used by the spin_type_rtp_buckets plugin
    # to emit a per-SpinType round-level RTP distribution.
    # Keys: sp_type (int) → bucket_label (str) → count/sum.
    spin_type_paid_bucket_spins: dict[int, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    spin_type_paid_bucket_bet: dict[int, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    spin_type_paid_bucket_win: dict[int, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    # Iter 6 (2026-04-23): settlement-SpinType bucket histogram built
    # from TRIGGER SESSION wins rather than round-level WinCredits.
    # Settlement SpinTypes (M15 TopDollar's ST=15, QuickDollar family's
    # ST=55, etc.) carry WinCredits=None on every round — so
    # spin_type_bucket_win[settlement_st] sums to 0 and the
    # per-feature bucket card renders "无倍率分桶数据". Here we key
    # bucket accumulation on the session's settlement SpinType (last
    # bonus SpinType in each trigger session) and its helper-
    # computed session_win / trigger-round bet. Feature rows bound to
    # a zero-win SpinType via Pass 5 read from this map in finalize.
    session_bucket_spins_by_settlement_st: dict[int, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    session_bucket_bet_by_settlement_st: dict[int, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    session_bucket_win_by_settlement_st: dict[int, dict[str, float]] = defaultdict(
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

    # C3 enrichment: per-pid payline attribution data.
    # Used by payouts_by_spin_type plugin to emit shape / covered_columns /
    # paylines / notes enrichment per (pid, spin_type).
    #
    # payout_id_payline_hits[pid_str][payline_id_str] = hit_count
    #   Every PayoutByPayline record attributed to pid increments this.
    #   line_id==-1 (scatter trigger) records use "-1" as the payline key.
    # payout_id_match_count_dist[pid_str][match_count_int] = occurrences
    #   Records match_count (n-of-a-kind) only for line_id != -1 records.
    # payout_id_col_set[pid_str] = {col_int, ...}
    #   Decoded column indices from PayoutByPayline positions, all records.
    #   col = (pos + 1) // 100 - 1  (per parser position-encoding doc).
    # payout_id_has_regular_line[pid_str] = True if ANY record had line_id != -1
    #   False (default) means all observed records are scatter-trigger lines.
    payout_id_payline_hits: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    payout_id_match_count_dist: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    payout_id_col_set: dict[str, set[int]] = defaultdict(set)
    # Sparse True-only: only set when a non-trigger line_id is seen.
    # Absent key means "no regular line observed" (default False at consumer).
    # Used by plugin to distinguish pure-scatter pids (e.g. M275 pid 666)
    # from regular-line pids.
    payout_id_has_regular_line: dict[str, bool] = {}
    # C4 symbol enrichment: per-pid symbol combination histogram.
    # Key: pid_str → combo_str → count.
    # combo_str = "|"-joined column-ordered symbol names (e.g. "cherry|cherry|35x_wild").
    # Only populated when StopSymbolsByCol is present AND positions decode cleanly.
    # Empty positions (scatter/feature pay, line_id==-1000/-1) → no combo entry.
    # Missing StopSymbolsByCol on the round → no combo entry.
    payout_id_symbol_combos: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

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
        nonlocal session_big_win_x20_count, session_big_win_x50_count, session_big_win_x100_count
        nonlocal session_ret_count, session_ret_sum, session_ret_sq_sum, session_max_return_x
        nonlocal session_win_sum
        nonlocal session_max_loss_streak, session_max_win_streak

        if not sess_state["open"]:
            return
        s_bet = float(sess_state["bet"])
        # Iter 5 (2026-04-23): session_win = paid round win + deferred
        # helper-computed bonus win. The naive per-round accumulator
        # (sess_state["win"] += win_amt on bonus rounds) over-counts
        # selector-offer rounds on M15 / Type-1 machines (sums ALL
        # offers when only the last accepted offer is real win). The
        # helper's ``session_win`` applies last_non_none (Type 1) or
        # sum_all-with-Payout-filter (Type 2) to produce the correct
        # player-received amount. bonus_win_from_helper is set on
        # session open (paid trigger round) from the pre-computed map.
        s_win = float(sess_state["win"]) + float(
            sess_state.get("bonus_win_from_helper", 0.0) or 0.0
        )
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
                if s_win >= 20.0 * s_bet:
                    session_big_win_x20_count += 1
                    if s_win >= 50.0 * s_bet:
                        session_big_win_x50_count += 1
                        if s_win >= 100.0 * s_bet:
                            session_big_win_x100_count += 1
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
        # Iter 5: clear deferred helper-win + trigger-session flag so
        # the next session's paid round gets a clean slate (set by
        # the paid-round branch when opened).
        sess_state["bonus_win_from_helper"] = 0.0
        sess_state["is_trigger_session"] = False

    for robot in resp:
        if not isinstance(robot, dict):
            continue
        rounds = parse_rounds(robot)

        # Trigger session win attribution (iteration 1 — Type 1 families
        # with ReMarks.startswith("Trigger"): TopDollar / QuickDollar /
        # Fortunes / DancingDrum / HoppyHunting / ChristmasSimple /
        # ValentineSimple). The round-level aggregator below credits
        # zero win to the trigger pay_id (its PayoutIdToWinAmount value
        # is 0 by design — it's a signal token), so the feature's real
        # payout lives only on analysisResult.FeatureWin and can't be
        # traced back to a pay_id. Pre-computing trigger sessions here
        # lets us fold each session's actual win (verified equal to
        # FeatureWin aggregate on M15 full-chunk scan) back onto its
        # trigger pay_id's payout_id_win, so payout_ids_top20's RTP pp
        # sum matches summary.rtp.
        #
        # Runs BEFORE the main per-round loop so the hits are still
        # counted by the base aggregator (trigger round's PayoutIdToWinAmount
        # key increments payout_id_hits) while this pass only adds the
        # session win — no double-counting of either hits or the co-
        # occurring regular payline wins (which have nonzero PayoutId
        # amounts and so are excluded from trigger_pay_ids by design).
        # Map trigger_round_idx → session_win for deferred session-
        # level bonus attribution (iter 5 session-win fix, 2026-04-23).
        # M15-style selector sessions carry uncredited "offer value"
        # WinCredits on bonus rounds (Payout=None); the naive per-
        # round session accumulator sums all of them (15000+20000+
        # 25000+40000 = 100000) while the player actually received
        # only the accepted offer (40000). That inflated session_win
        # cascades into session_bucket_win → tail_win_geN →
        # tail_dependency > 100%. Fix: for TRIGGER SESSIONS specifically,
        # replace the main loop's naive bonus-win accumulation with
        # the helper's session_win (Type 1 last_non_none / Type 2
        # sum_with_Payout_filter). Non-trigger sessions (bonus flow
        # without a detectable trigger signal — M272 simple paid→bonus
        # round sequences, etc.) keep their naive accumulation
        # intact so pre-existing behavior is preserved.
        #
        # 2026-05-12: forward ``ctx`` so rules see the per-robot
        # ``cycle_peak`` (used by BCMCycleAnchorRule to detect
        # CollectCount-milestone trigger paid rounds whose
        # PayoutIdToWinAmount is empty -- M274 mode 1 saw 8.25% of
        # bonus rounds escape attribution before this fix; fleet sweep
        # across cached BCM machines found 55 of 117 (machine, mode)
        # pairs leaking similarly into _unattributed_st<N>) and the
        # ``bet`` amount for SynthesizePayIdRule's multiplier labels.
        _cycle_peak_for_ctx = detect_cycle_peak(rounds)
        _trigger_ctx = {"cycle_peak": _cycle_peak_for_ctx, "bet": bet}
        _trig_sessions_for_robot = compute_trigger_sessions(
            rounds, round_win_rules=round_win_rules, ctx=_trigger_ctx,
        )
        session_win_by_trigger_idx: dict[int, float] = {
            int(s["trigger_idx"]): float(s.get("session_win", 0.0) or 0.0)
            for s in _trig_sessions_for_robot
        }
        # 2026-06-11 (session-dim fix): parallel map for the player-experience
        # dimension.  session_dim_win carries the full bonus win without the
        # credited-win exclusion.  On Type-1 shapes (M15/M12/M132) the
        # exclusion never fires, so session_dim_win == session_win and this
        # map is byte-identical to session_win_by_trigger_idx.  On Type-2
        # self-crediting shapes (M273/M275) session_dim_win > session_win
        # (often session_win==0 while session_dim_win==total bonus win).
        # Only _close_session's bonus_win_from_helper uses this map; every
        # OTHER consumer (pid attribution fold, session_handled_bonus_indices,
        # Pass-5 binding) stays on session_win_by_trigger_idx so pid parity
        # is preserved.
        session_dim_win_by_trigger_idx: dict[int, float] = {
            int(s["trigger_idx"]): float(s.get("session_dim_win", 0.0) or 0.0)
            for s in _trig_sessions_for_robot
        }
        trigger_session_paid_indices: set[int] = set(session_win_by_trigger_idx.keys())
        # 2026-04-27: bonus-round indices that are part of a trigger
        # session (i.e. their win is attributed via session_win on the
        # trigger pay_id). Used by the unattributed-fallback synthesizer
        # below to avoid double-counting when a rule deliberately
        # returned {} on these rounds (see SettlementWinAmountRule).
        session_handled_bonus_indices: set[int] = set()
        for _s in _trig_sessions_for_robot:
            _trig_i = int(_s.get("trigger_idx", -1))
            _end_i = int(_s.get("session_end_idx", _trig_i + 1))
            if _trig_i < 0:
                continue
            for _bi in range(_trig_i + 1, _end_i):
                session_handled_bonus_indices.add(_bi)
        # Iter 6: feed each trigger session into the
        # settlement-SpinType bucket histogram so Pass-5-bound
        # features (whose resolved_spin_type has zero round-level
        # win) can render a bucket card. Settlement ST = last bonus
        # round's SpinType in the session. Bet is pulled from the
        # trigger paid round's CostCredits / BetAmount (1 paid spin
        # per trigger session).
        #
        # 2026-06-11 (session-dim fix): use session_dim_win (the
        # player-experience total) rather than session_win (the
        # pid-attribution total which excludes credited rounds).
        # This is a DISPLAY dimension — the correct seed for any
        # future consumer of the settlement-ST bucket histogram.
        # Practical effect of this switch:
        #   Type-1 shapes (M15, TopDollar): session_dim_win ==
        #     session_win (credited-win exclusion never fires on
        #     phantom offer rounds) → byte-identical bucket data.
        #   Type-2 shapes (M275-style, bonus rounds self-credit):
        #     upstream_feature_breakdown's fallback guard
        #     (feat_bucket_total_win==0 → keep existing bucket data)
        #     means the bucket card is driven by the per-ST plugin,
        #     NOT by this iter-6 feed — so the dim-switch does NOT
        #     affect M275's session-level multiplier display.  That
        #     display arrives via the per-ST extraction layer (sub-
        #     pass B / W4 scope, not this pass).
        #   M43/M279: no detected trigger sessions → loop no-op.
        for _s in _trig_sessions_for_robot:
            _sess_win = float(_s.get("session_dim_win", 0.0) or 0.0)
            _bonus_sts = _s.get("bonus_spin_types") or []
            if not _bonus_sts:
                continue
            # Last non-None spin type in the bonus sequence serves
            # as the settlement anchor. If the sequence is all None
            # (shouldn't happen but defensive), skip — can't key.
            _settlement_st: int | None = None
            for _st_candidate in reversed(_bonus_sts):
                if isinstance(_st_candidate, int):
                    _settlement_st = _st_candidate
                    break
            if _settlement_st is None:
                continue
            _trig_idx = int(_s.get("trigger_idx", 0))
            if 0 <= _trig_idx < len(rounds) and isinstance(rounds[_trig_idx], dict):
                _trig_round = rounds[_trig_idx]
                _sess_bet = to_float(
                    _trig_round.get("CostCredits"),
                    default=to_float(_trig_round.get("BetAmount"), default=0.0),
                )
            else:
                _sess_bet = 0.0
            if _sess_bet <= 0:
                continue
            _ret_x = _sess_win / _sess_bet
            _bucket = return_bucket(_ret_x)
            if not _bucket:
                # zero-win session (no accepted bonus) — skip to
                # keep bucket rows aligned with non-empty buckets.
                continue
            session_bucket_spins_by_settlement_st[_settlement_st][_bucket] += 1
            session_bucket_bet_by_settlement_st[_settlement_st][_bucket] += _sess_bet
            session_bucket_win_by_settlement_st[_settlement_st][_bucket] += _sess_win
        # Trigger-session win attribution: each session's session_win
        # belongs to a SINGLE trigger pay_id (the bonus signal token).
        # extract_trigger_pay_ids returns ALL pay_ids whose value is 0
        # on the trigger round, which can include multiple anchors
        # (e.g. M214 mode 5: pid={'1': 0, '666': 0} -- pay_id 1 is the
        # base-game line that happened to pay 0 on this spin, pay_id
        # 666 is the actual TriggerWheel signal). Crediting session_win
        # to BOTH inflates the drilldown by 2x for those sessions.
        # Heuristic: pick the largest integer pid (convention is large
        # ids like 666 / 5801 are pure trigger tokens; small ids 1-100
        # are payline pay_ids that occasionally have 0 win). Falls
        # back to lex-max when none parse as int. Single-anchor
        # sessions (M12/M15/M132 TopDollar with only ['666']) are
        # unaffected -- max of a single-element list is that element.
        def _pid_anchor_sort_key(s: Any) -> tuple:
            try:
                return (1, int(s))
            except (TypeError, ValueError):
                return (0, str(s))

        for _trig_session in _trig_sessions_for_robot:
            _anchor_pids = _trig_session.get("trigger_pay_ids") or ()
            if not _anchor_pids:
                continue
            _chosen = str(max(_anchor_pids, key=_pid_anchor_sort_key))
            _sess_win = float(_trig_session.get("session_win", 0.0) or 0.0)
            # Bump hits for rule-synthesized anchors (e.g. ``_bcm_cycle``
            # from BCMCycleAnchorRule). The default round-level loop
            # bumps ``payout_id_hits[pid]`` only for pids appearing in
            # the round's ``PayoutIdToWinAmount`` dict -- a rule-only
            # anchor never appears there and would silently report
            # ``hits=0`` in the drilldown despite carrying nonzero win.
            # The hit semantic for these anchors is "this trigger
            # session is one occurrence of the synthetic feature": one
            # bump per session regardless of session_win (a 0-win
            # cycle-peak round is still a feature occurrence). Real
            # numeric anchors are detected here as "_chosen is NOT a
            # key in the trigger round's PayoutIdToWinAmount" -- those
            # were credited a hit by the round-level loop already and
            # bumping again would double-count.
            _trig_idx = _trig_session.get("trigger_idx", -1)
            try:
                _trig_idx_int = int(_trig_idx)
            except (TypeError, ValueError):
                _trig_idx_int = -1
            if 0 <= _trig_idx_int < len(rounds):
                _trig_pid_dict = rounds[_trig_idx_int].get("PayoutIdToWinAmount") if isinstance(rounds[_trig_idx_int], dict) else None
                _present_in_round = (
                    isinstance(_trig_pid_dict, dict)
                    and _chosen in {str(k) for k in _trig_pid_dict.keys()}
                )
                if not _present_in_round:
                    payout_id_hits[_chosen] += 1
            if _sess_win == 0.0:
                continue
            payout_id_win[_chosen] += _sess_win
            # 2026-05-14: attribute trigger-session win to ST of the trigger round
            # for the ST-split payout breakdown. Trigger round's SpinType is the
            # paid round that opened the session.
            if 0 <= _trig_idx_int < len(rounds):
                _trig_r = rounds[_trig_idx_int]
                if isinstance(_trig_r, dict):
                    try:
                        _trig_st = int(_trig_r.get("SpinType", -1) or -1)
                    except (TypeError, ValueError):
                        _trig_st = -1
                    payout_id_win_by_spin_type[_chosen][_trig_st] += _sess_win

        # Phase E: TopDollar session behavioral accumulation.
        # For each trigger session that contains ST=14 picks, extract the
        # per-session behavioral data (picks, offers, chosen dollar strings,
        # settled win).  The session dict structure matches what
        # topdollar_choice.extract() expects from chunk_dict["topdollar_sessions"].
        #
        # Runs AFTER the trigger-session attribution loop so _trig_sessions_for_robot
        # is already fully populated.  Operates on the raw `rounds` list using
        # trigger_idx / session_end_idx as slice boundaries — no re-parsing.
        #
        # Non-TopDollar machines produce zero ST=14 rounds → this loop is a
        # cheap no-op (each session's inner loop finds nothing and appends nothing).
        for _td_s in _trig_sessions_for_robot:
            _td_trig_i = int(_td_s.get("trigger_idx", -1))
            _td_end_i = int(_td_s.get("session_end_idx", _td_trig_i + 1))
            if _td_trig_i < 0 or _td_end_i <= _td_trig_i + 1:
                continue
            # Walk the bonus rounds in this session; collect ST=14 pick data.
            _td_picks: list[dict] = []
            _td_settled_win: int | None = None
            for _td_ri in range(_td_trig_i + 1, _td_end_i):
                if _td_ri >= len(rounds):
                    break
                _td_r = rounds[_td_ri]
                if not isinstance(_td_r, dict):
                    continue
                _td_st = _td_r.get("SpinType")
                try:
                    _td_st_int = int(_td_st) if _td_st is not None else -1
                except (TypeError, ValueError):
                    _td_st_int = -1
                if _td_st_int == 14:  # player-choice round
                    _td_offer = _td_r.get("OfferValue")
                    _td_dollar_count = _td_r.get("DollarCount")
                    _td_chosen = _td_r.get("ChosenDollar")
                    try:
                        _td_offer_int = int(_td_offer) if _td_offer is not None else 0
                    except (TypeError, ValueError):
                        _td_offer_int = 0
                    try:
                        _td_dc_int = int(_td_dollar_count) if _td_dollar_count is not None else 0
                    except (TypeError, ValueError):
                        _td_dc_int = 0
                    _td_picks.append({
                        "offer": _td_offer_int,
                        "dollar_count": _td_dc_int,
                        "chosen": str(_td_chosen) if _td_chosen is not None else "",
                    })
                elif _td_st_int == 15:  # settlement round
                    _td_wa = _td_r.get("WinAmount")
                    try:
                        _td_settled_win = int(_td_wa) if _td_wa is not None else None
                    except (TypeError, ValueError):
                        _td_settled_win = None
            if _td_picks:
                # Only record sessions with at least one ST=14 pick (i.e. actual
                # TopDollar sessions; skip non-TD trigger sessions silently).
                chunk_topdollar_sessions.append({
                    "n_picks": len(_td_picks),
                    "offers": [p["offer"] for p in _td_picks],
                    "dollar_counts": [p["dollar_count"] for p in _td_picks],
                    "chosen": [p["chosen"] for p in _td_picks],
                    "settled_win": _td_settled_win,
                })

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
        # BuffCollectionMap cycle detection: computed in ONE place via
        # compute_robot_cycle_peaks(rounds) called after the per-round loop.
        # robot_cycle_peaks is assigned there; declared here so later
        # references (chunk_completed_cycles, chunk_cycle_peaks) are in scope
        # even if the robot has zero rounds.
        robot_cycle_peaks: list[int] = []  # assigned post-loop via helper
        # robot_prev_cc_for_cycle is kept ONLY for the chain-flag clear
        # predicate below (``if is_paid and cc_int == 0 and ...``).
        # It is NOT used for cycle-peak detection any more; that logic
        # lives in compute_robot_cycle_peaks (round_classification.py).
        robot_prev_cc_for_cycle = 0  # only used for chain-flag clear check
        # 2026-04-28 chain-timing fix (Bug 4): pre-compute cycle peak
        # from this robot's full round list using observed-reset
        # detection. The OLD logic set _bonus_chain_last_cc_reset on
        # cc-DROP (the round AFTER cycle complete -- e.g. M279 cc=1000
        # paid -> wheel ST=2 -> cc=1 paid; flag fires at the cc=1 round
        # which is too LATE -- the wheel chain already closed). Result:
        # Wheel chain got "entry_cc_reset=False" (no BCM tag), and the
        # next unrelated MoveSpin nudge a few rounds later got the
        # stale flag and was labeled "via BCM cycle". User saw
        # "MoveSpin [via BCM cycle]" + "Wheel [via Wheel]" instead of
        # the correct "Wheel [via BCM cycle]" + "MoveSpin" plain.
        # New: detect peak ONCE per robot, then in the per-round walk
        # set the flag when cc == peak (the round AT cycle complete,
        # BEFORE the wheel/bonus chain opens).
        # 2026-05-12: reuse the peak value that was already computed for
        # the trigger-session ctx above (single O(n) walk per robot).
        robot_cycle_peak: int | None = _cycle_peak_for_ctx
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

        for _round_idx_in_robot, r in enumerate(rounds):
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
                lock_lines_win += extract_round_win(r, rules=round_win_rules)

            _lock_syms = r.get("LockSymbols")
            if _lock_syms and isinstance(_lock_syms, str) and _lock_syms.strip("| "):
                lock_symbols_spins += 1
                lock_symbols_win += extract_round_win(r, rules=round_win_rules)
                for part in _lock_syms.split("|"):
                    part = part.strip()
                    if ":" in part:
                        lock_symbols_unique.add(part.split(":")[0].strip())

            _lock_reels = r.get("LockReels")
            if _lock_reels and isinstance(_lock_reels, str) and _lock_reels.strip():
                lock_reels_spins += 1
                lock_reels_win += extract_round_win(r, rules=round_win_rules)

            _jackpot_ids = r.get("JackpotIds") or r.get("JackpotID")
            if _jackpot_ids is not None:
                _jid_str = str(_jackpot_ids).strip("-").strip()
                if _jid_str:
                    jackpot_spins += 1
                    jackpot_win += extract_round_win(r, rules=round_win_rules)
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
                    freespin_win += extract_round_win(r, rules=round_win_rules)
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
                dollar_pick_win += extract_round_win(r, rules=round_win_rules)

            bet_amt = to_float(r.get("BetAmount"), default=0.0)
            if bet_amt <= 0.0:
                bet_amt = to_float(r.get("CostCredits"), default=float(bet))
            if bet_amt <= 0.0:
                bet_amt = float(bet)

            # Paid vs bonus classification. Priority signals:
            #   CostCredits>0             → paid (player paid for this spin)
            #   CostCredits==0            → bonus / free / re-spin
            #   CostCredits==None         → ambiguous, fall back to BetAmount
            #     BetAmount>0             → paid (machines that use BetAmount
            #                                as the player-cost signal)
            #     BetAmount==None or ≤0   → bonus summary round (M112 ST97
            #                                WheelSpin / ST98 FinalMinigame
            #                                both emit null cost + null bet;
            #                                previously misclassified as paid,
            #                                inflating RTP denominator and
            #                                double-counting bonus wins)
            # cost_credits_unreliable short-circuits everything to "paid"
            # for machines where the server never populates CostCredits
            # (legacy LockReSpin machines M10/M23/M131/M133 etc).
            if cost_credits_unreliable:
                is_paid = True
            else:
                cost_credits_raw = r.get("CostCredits")
                if cost_credits_raw is None:
                    bet_raw = r.get("BetAmount")
                    bet_val = to_float(bet_raw, default=0.0) if bet_raw is not None else 0.0
                    is_paid = bet_val > 0.0
                else:
                    is_paid = to_float(cost_credits_raw, default=0.0) > 0.0

            win_amt = extract_round_win(r, rules=round_win_rules)
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
                # Iter 5: if this paid round opens a trigger session,
                # mark the session as helper-tracked and record the
                # helper-computed session_win. Bonus rounds belonging
                # to a helper-tracked session skip the naive
                # accumulator (their WinCredits are phantom offers on
                # Type 1 or already at pay_id level on Type 2);
                # _close_session adds bonus_win_from_helper instead.
                # Non-trigger sessions keep naive accumulation —
                # matches pre-iter-5 behavior for machines whose
                # bonus flows aren't caught by the trigger detector.
                #
                # 2026-06-11 (session-dim fix): bonus_win_from_helper
                # now uses session_dim_win_by_trigger_idx (player-
                # experience dimension), NOT session_win_by_trigger_idx
                # (pid-attribution dimension).  _close_session computes
                # the session KPI value (avg_return_x, win hit-rate,
                # ≥10x rate) from this, so it must reflect what the
                # player actually received — not the pid-scoped subset.
                # pid attribution (session_win_by_trigger_idx) is
                # unchanged and still used in the payout_id_win fold
                # below and in session_handled_bonus_indices.
                if _round_idx_in_robot in trigger_session_paid_indices:
                    sess_state["is_trigger_session"] = True
                    sess_state["bonus_win_from_helper"] = (
                        session_dim_win_by_trigger_idx.get(_round_idx_in_robot, 0.0)
                    )
                else:
                    sess_state["is_trigger_session"] = False
                    sess_state["bonus_win_from_helper"] = 0.0
            else:
                if sess_state["open"]:
                    if not sess_state.get("is_trigger_session"):
                        # Non-trigger session — naive accumulation
                        # (pre-iter-5 behavior). Covers M272 paid+
                        # bonus flows without a Trigger ReMarks / win=0
                        # pay_id anchor that the helper would catch.
                        sess_state["win"] += win_amt
                    # else: trigger session — bonus round wins are
                    # handled by bonus_win_from_helper at close. Skip
                    # naive add to avoid double-counting or phantom-
                    # offer inflation.
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
            # 2026-04-27 (Bug 3): tally wild-nudge round count per ST
            # so finalize can decide which features are nudge-dominated
            # (>= 90% of their rounds are wild_nudge). One-off matches
            # don't qualify.
            if is_wild_nudge_round(r):
                spin_type_nudge_round_count[sp_type] += 1
            # Per-SpinType return bucket (mirrors the global
            # multiplier_bucket_* but keyed by SpinType so upstream
            # feature breakdown can render a per-feature histogram).
            spin_type_bucket_spins[sp_type][bucket] += 1
            spin_type_bucket_bet[sp_type][bucket] += bet_amt
            spin_type_bucket_win[sp_type][bucket] += win_amt
            # Per-SpinType PAID-round bucket: only when is_paid and bet>0
            # so the win/bet ratio is meaningful (free rounds have bet==0).
            # Uses the same `bucket` label already computed above via
            # return_bucket(win_amt / bet_amt).  spin_type_rtp_buckets plugin
            # reads spin_type_rtp_buckets from the chunk dict (see return dict
            # below) to emit the per-ST round-level RTP distribution.
            if is_paid and bet_amt > 0:
                spin_type_paid_bucket_spins[sp_type][bucket] += 1
                spin_type_paid_bucket_bet[sp_type][bucket] += bet_amt
                spin_type_paid_bucket_win[sp_type][bucket] += win_amt
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
            # 2026-04-28 (Bug 5): wild-nudge rounds are continuations of
            # the preceding paid spin (no extra cost; ReMarks "move"/
            # "nudge"). They must NOT open / accumulate into / close a
            # bonus chain. Otherwise a nudge that fires AT cycle-peak
            # opens the chain with first_st=36 instead of the actual
            # BCM target (Wheel ST=2 firing right after the nudge).
            # User saw "MoveSpin [via BCM cycle]" + "Wheel [via MoveSpin]"
            # because nudge took the chain-opener slot. Treat nudge
            # rounds as transparent to chain bookkeeping -- chunk_win
            # and per-SpinType totals still include their wins, but the
            # chain inference looks past them to find the real bonus.
            _is_wild_nudge_for_chain = is_wild_nudge_round(r)
            if _is_paid_for_chain:
                # Close any open chain.
                _bonus_chain_active = None
            elif _is_wild_nudge_for_chain:
                # Skip chain bookkeeping for nudge rounds entirely.
                # Don't open, don't close, don't accrue.
                pass
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
                # 2026-04-28: flag BCM-cycle-trigger AT the cycle peak
                # paid round (not on cc-drop). Pre-computed
                # robot_cycle_peak comes from detect_cycle_peak which
                # walks the full round list and only commits a peak
                # when a real cc-reset is observed -- no false-positive
                # on machines whose chunk doesn't span a full cycle.
                # When this paid round's cc == peak, the immediately
                # following non-paid round (Wheel on M279, NewFreespin
                # on others) is the BCM-cycle bonus. Setting the flag
                # here means the chain opener picks it up cleanly.
                if (
                    robot_cycle_peak is not None
                    and cc_int == robot_cycle_peak
                ):
                    _bonus_chain_last_cc_reset = True
                # robot_cycle_peaks is built post-loop via
                # compute_robot_cycle_peaks(rounds) — see below.
                # robot_prev_cc_for_cycle is still updated here so the
                # chain-flag clear predicate at line ~1940 has its value.
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
            #
            # Win-vs-Payout normalization (iter 4 M209 fix, 2026-04-23):
            # some machines' bonus-round Payout represents potential/
            # alternative rewards rather than earned credits, so
            # ``sum(Payout values) > WinCredits`` can happen (M209
            # "move" rounds commonly show Win=10000 Payout={'2':20000}
            # or Win=10000 Payout={'2':10000,'3':5000}). Attributing
            # the raw Payout values inflates pay_id RTP beyond the
            # actual WinCredits earned; ``sum(payout_ids_top20.rtp_pp)``
            # exceeded summary.rtp by ~8pp on M209 before this fix.
            #
            # Fix: when ``sum(Payout) > WinCredits > 0``, scale each
            # pay_id's credit to its proportional share of Win. When
            # they match (almost all machines / all paid rounds),
            # behavior is identical to pre-fix. When upstream reports
            # Win without a corresponding Payout entry (Win > Payout
            # sum, rare), we keep Payout values as-is — the unaccounted
            # delta stays under "no pay_id" at the session level.
            #
            # 2026-04-27: per-machine rules can override / synthesize
            # the pid mapping. extract_round_payouts returns either a
            # rule-supplied dict (e.g. SynthesizePayIdRule emits
            # {'20': 20000} for a wheel ST=2 round; SettlementWinAmountRule
            # emits {} to suppress round-level credit and delegate to
            # trigger_sessions) or the legacy r.PayoutIdToWinAmount
            # bytes-equivalent dict when no rule applies.
            pid_to_win = extract_round_payouts(
                r, rules=round_win_rules, ctx={"bet": bet},
            )
            _win_this_round = extract_round_win(r, rules=round_win_rules)
            _credited_sum = 0.0  # tracks how much of _win_this_round
                                 # ended up attributed to some pay_id
            if pid_to_win:  # non-empty dict only -- empty dict is
                            # explicit "do nothing" from rule or legacy
                _pay_sum = sum(
                    to_float(v, default=0.0) for v in pid_to_win.values()
                )
                _scale = 1.0
                if _pay_sum > 0 and 0 < _win_this_round < _pay_sum:
                    _scale = _win_this_round / _pay_sum
                for pid_raw, amount_raw in pid_to_win.items():
                    pid = str(pid_raw)
                    payout_id_hits[pid] += 1
                    _credited = to_float(amount_raw, default=0.0) * _scale
                    payout_id_win[pid] += _credited
                    _credited_sum += _credited
                    # Capture the SpinType that fired this pay_id (from
                    # the round's sp_type, determined below but already
                    # assigned via the per-round parse pass — the int
                    # sits in ``sp_type`` by this point in the iteration).
                    try:
                        _st_key = int(sp_type) if sp_type is not None else -1
                    except (TypeError, ValueError):
                        _st_key = -1
                    payout_id_by_spin_type[pid][_st_key] += 1
                    # 2026-05-14: also track win per (pid, ST) for ST-split breakdown.
                    payout_id_win_by_spin_type[pid][_st_key] += _credited

            # C3: per-pid payline attribution enrichment.
            # Runs whenever PayoutByPayline is present on this round.
            # attribute_lines_to_pay_ids handles symbol→pid matching
            # (direct / suffix / single-remaining) via existing helpers.
            # This is the only call site; adds no duplicate logic.
            _pbp_c3 = r.get("PayoutByPayline")
            if _pbp_c3:
                # C4 symbol decode: read StopSymbolsByCol once per round.
                # Format: list of "s0-s1-s2-" strings (one per column).
                # Absent or non-list → no symbol decode for this round.
                _c4_ssbc = r.get("StopSymbolsByCol")
                _c4_ssbc_cols: list[list[str]] | None = None
                if isinstance(_c4_ssbc, list) and _c4_ssbc:
                    try:
                        # Split each column string by "-"; keep empty strings
                        # so that index arithmetic (row = pos - col*100 + 1)
                        # maps cleanly. Trailing dash produces a trailing empty
                        # string — that's expected and harmless since we index
                        # by the decoded row value, not by iteration.
                        _c4_ssbc_cols = [str(col_txt).split("-") for col_txt in _c4_ssbc]
                    except Exception:
                        _c4_ssbc_cols = None

                for _c3rec in attribute_lines_to_pay_ids(r):
                    _c3pid = _c3rec.get("pay_id")
                    if _c3pid is None:
                        continue
                    _c3pid_s = str(_c3pid)
                    _c3lid = _c3rec.get("line_id", 0)
                    _c3lid_s = str(_c3lid)
                    payout_id_payline_hits[_c3pid_s][_c3lid_s] += 1
                    # Decode col indices from positions (all records incl line_id=-1)
                    _c3positions = _c3rec.get("positions", [])
                    for _c3pos in _c3positions:
                        _c3col = (_c3pos + 1) // 100 - 1
                        if _c3col >= 0:
                            payout_id_col_set[_c3pid_s].add(_c3col)
                    # C4 symbol combo decode: per-position symbol lookup.
                    # Only when StopSymbolsByCol is available and positions non-empty.
                    # Decode formula (verified M14/M1/M275/M279/M268/M274):
                    #   col_1indexed = (pos + 1) // 100
                    #   col0idx = col_1indexed - 1
                    #   row = pos - col_1indexed * 100 + 1
                    #   symbol = StopSymbolsByCol[col0idx].split("-")[row]
                    # Offset: row=0→top, row=1→middle(center), row=2→bottom.
                    if _c4_ssbc_cols is not None and _c3positions:
                        _c4_symbols: list[str] = []
                        _c4_decode_ok = True
                        for _c4pos in _c3positions:
                            _c4col_1idx = (_c4pos + 1) // 100
                            _c4col0 = _c4col_1idx - 1
                            _c4row = _c4pos - _c4col_1idx * 100 + 1
                            if _c4col0 < 0 or _c4col0 >= len(_c4_ssbc_cols):
                                # Column index out of range for this machine's grid.
                                # FAIL LOUD: record nothing for this round's combo
                                # rather than mis-mapping. Per brief §decode.
                                _c4_decode_ok = False
                                break
                            _c4col_syms = _c4_ssbc_cols[_c4col0]
                            if _c4row < 0 or _c4row >= len(_c4col_syms):
                                # Row index out of range.
                                _c4_decode_ok = False
                                break
                            _c4sym = _c4col_syms[_c4row]
                            if not _c4sym:
                                # Empty string at this index (trailing dash artifact
                                # or malformed data) — skip this combo.
                                _c4_decode_ok = False
                                break
                            _c4_symbols.append(_c4sym)
                        if _c4_decode_ok and _c4_symbols:
                            _c4_combo = "|".join(_c4_symbols)
                            payout_id_symbol_combos[_c3pid_s][_c4_combo] += 1
                    # match_count distribution only for non-trigger lines
                    if _c3lid != -1:
                        payout_id_has_regular_line[_c3pid_s] = True
                        _c3mc = _c3rec.get("match_count", 0)
                        if _c3mc > 0:
                            payout_id_match_count_dist[_c3pid_s][_c3mc] += 1

            # 2026-04-27: fallback synthesizer for the unattributed
            # delta. Closes the ``sum(payid_win) ~= chunk_win``
            # invariant fleet-wide. Skipped when:
            #   * delta <= 0.5 credit (round-level attribution covers it)
            #   * round is part of a trigger session whose session_win
            #     is attributed to the trigger pay_id by the existing
            #     session-attribution loop -- adding here would double-
            #     count (M12/M15/M132 TopDollar settlement rounds).
            #
            # When fired, synthesizes ``_unattributed_st<SpinType>``
            # so the drilldown surfaces "this much win came from
            # SpinType N rounds the upstream didn't itemize per pay_id."
            # The leading underscore signals "synthetic / catch-all"
            # to operators reading the drilldown.
            if (
                _win_this_round - _credited_sum > 0.5
                and _round_idx_in_robot not in session_handled_bonus_indices
            ):
                try:
                    _fallback_st_key = int(sp_type) if sp_type is not None else -1
                except (TypeError, ValueError):
                    _fallback_st_key = -1
                _fallback_pid = f"_unattributed_st{_fallback_st_key}"
                payout_id_hits[_fallback_pid] += 1
                _fallback_win_delta = _win_this_round - _credited_sum
                payout_id_win[_fallback_pid] += _fallback_win_delta
                payout_id_by_spin_type[_fallback_pid][_fallback_st_key] += 1
                # 2026-05-14: also track win for ST-split breakdown.
                payout_id_win_by_spin_type[_fallback_pid][_fallback_st_key] += _fallback_win_delta

            line_ids = parse_paylines(str(r.get("PayoutByPayline") or ""))
            if line_ids:
                share = win_amt / len(line_ids)
                for lid in line_ids:
                    payline_hits[lid] += 1
                    payline_win_approx[lid] += share

            stop_cols = r.get("StopSymbolsByCol") or []
            col_symbol_sets: list[set[str]] = []
            if isinstance(stop_cols, list):
                # Determine SpinType for per-ST reel marginal accumulation.
                # sp_type was already assigned earlier in this round iteration.
                try:
                    _sym_st_key = int(sp_type) if sp_type is not None else -1
                except (TypeError, ValueError):
                    _sym_st_key = -1
                for ci, col_text in enumerate(stop_cols):
                    col_syms = split_symbols(str(col_text))
                    col_symbol_sets.append({s for s in col_syms if s})
                    for row_idx, sym in enumerate(col_syms):
                        symbol_counts[sym] += 1
                        symbol_counts_by_col[ci][sym] += 1
                        symbol_counts_by_col_by_row[ci][row_idx][sym] += 1
                        total_symbol_slots += 1
                        # 2026-05-14: per-ST reel marginal accumulation.
                        symbol_counts_by_col_by_spin_type[_sym_st_key][ci][sym] += 1

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
            # Position encoding (slot_designer/emitter/round.py):
            #   pos = (col+1) * 100 + (row-1)
            # where col/row are 0-indexed and row=1 is middle row.
            # Decoding:
            #   col = (pos // 100) - 1
            #   row = (pos % 100) + 1  (but note: pos 99 → row=100 which is
            #   wrong; pos 99 is actually col=0 row=0 (top)). So we decode:
            #     col = (pos + 1) // 100 - 1   (handles top-row pos=99 etc.)
            #     row = (pos + 1) % 100        (0=top, 1=mid, 2=bot)
            # Use the decoded (col, row) to populate payline_rows_per_col
            # — the inferred set of row indices that paylines visit for
            # each reel. No spec dependency; works for any machine as
            # long as we see at least one win touching each payline row.
            if line_ids and win_amt > 0:
                pl_text = str(r.get("PayoutByPayline", ""))
                for match in _POSITION_RE.finditer(pl_text):
                    for pos_text in match.group(1).split(","):
                        pos_text = pos_text.strip()
                        if not pos_text:
                            continue
                        reel_position_hits[pos_text] += 1
                        try:
                            pos_int = int(pos_text)
                        except ValueError:
                            continue
                        # Decode col/row from position encoding
                        col_decoded = (pos_int + 1) // 100 - 1
                        row_decoded = (pos_int + 1) % 100
                        if col_decoded >= 0 and 0 <= row_decoded <= 2:
                            payline_rows_per_col[col_decoded].add(row_decoded)

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
                cum_win_r += extract_round_win(rr, rules=round_win_rules)
                if paid_i % sample_interval == 0 or paid_i == robot_paid_spin_idx:
                    curve_points.append({
                        "spin": paid_i,
                        "cum_rtp": (cum_win_r / cum_bet_r * 100.0) if cum_bet_r > 0 else 0.0,
                    })
            else:
                # Bonus spin wins attribute to session but we track
                # cumulative win for the curve.
                cum_win_r += extract_round_win(rr, rules=round_win_rules)
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
        #
        # Compute cycle peaks via the shared helper (single source of truth).
        robot_cycle_peaks = compute_robot_cycle_peaks(rounds)
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

    # 2026-04-27 chunk-level residual closer: ensure
    # ``sum(payout_id_win.values()) == chunk_win`` within tolerance.
    # The per-round fallback above catches non-session-handled rounds
    # whose pid attribution is short. This residual catches the
    # remaining causes:
    #   * Trigger sessions where session_win attribution under-counts
    #     (e.g. M24 'TriggerFreespin' rule incorrectly classified as
    #     last_non_none -- only the last bonus round's win goes to
    #     trigger pay_id 666; earlier freespin wins are dropped).
    #   * Per-round M209 scaling boundary cases (WinCredits=0 paired
    #     with non-zero PayoutIdToWinAmount values, where the scale-
    #     down condition `0 < win < pay_sum` doesn't fire).
    #   * Any future leak path we haven't yet identified.
    #
    # Synthesizes a single ``_unattributed_residual`` bucket so the
    # invariant always holds, regardless of upstream emission shape
    # or per-mechanic classification quirks. The label is intentionally
    # distinct from ``_unattributed_st<N>`` so operators can tell
    # "this delta couldn't be tied to any single SpinType" from
    # "this SpinType's rounds didn't have per-pid info".
    _pid_sum = sum(payout_id_win.values())
    _residual = chunk_win - _pid_sum
    if _residual > 0.5:
        payout_id_hits["_unattributed_residual"] += 1
        payout_id_win["_unattributed_residual"] += _residual
        # Don't add to payout_id_by_spin_type -- this delta isn't
        # tied to any single SpinType by definition.

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
        # 2026-04-24: per-(col, row) granular counts for payline-density
        # drilldown. Keys nested as str(col) → str(row) → symbol → count
        # so JSON round-trips through chunk cache cleanly.
        "symbol_counts_by_col_by_row": {
            str(ci): {str(ri): dict(sm) for ri, sm in row_map.items()}
            for ci, row_map in symbol_counts_by_col_by_row.items()
        },
        # 2026-05-14: per-SpinType symbol counts per column for ST-split
        # reel marginal. Keys: str(ST) → str(col) → symbol → count.
        "symbol_counts_by_col_by_spin_type": {
            str(st): {str(ci): dict(cmap) for ci, cmap in col_map.items()}
            for st, col_map in symbol_counts_by_col_by_spin_type.items()
        },
        "payline_rows_per_col": {
            str(ci): sorted(rows) for ci, rows in payline_rows_per_col.items()
        },
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
        "payout_id_by_spin_type": {
            pid: dict(st_map)
            for pid, st_map in payout_id_by_spin_type.items()
        },
        # 2026-05-14: per (pay_id, spin_type) WIN amounts for ST-split breakdown.
        "payout_id_win_by_spin_type": {
            pid: dict(st_map)
            for pid, st_map in payout_id_win_by_spin_type.items()
        },
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
        # 2026-04-27 (Bug 3): per-SpinType nudge-round counts. Finalize
        # uses these (combined with spin_type_spins) to identify
        # nudge-dominated SpinTypes and tag their feature rows.
        "spin_type_nudge_round_count": {
            str(k): v for k, v in spin_type_nudge_round_count.items()
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
        # Per-SpinType PAID-round-level bucket histogram.
        # Consumed by spin_type_rtp_buckets plugin (extract/reduce/emit).
        # Keys: str(sp_type) → {bucket_label: {"spins": int, "bet": float, "win": float}}
        # Aggregated at emit() time (not here) to keep chunk dict compact.
        "spin_type_rtp_buckets": {
            str(st): {
                b: {
                    "spins": spin_type_paid_bucket_spins[st].get(b, 0),
                    "bet": spin_type_paid_bucket_bet[st].get(b, 0.0),
                    "win": spin_type_paid_bucket_win[st].get(b, 0.0),
                }
                for b in spin_type_paid_bucket_spins[st]
            }
            for st in spin_type_paid_bucket_spins
        },
        # Iter 6: session-level bucket histogram keyed by trigger
        # session's settlement SpinType. Finalize merges these across
        # chunks; feature rows bound to zero-win settlement STs
        # (Pass 5) render their bucket_distribution from this map.
        "session_bucket_spins_by_settlement_st": {
            str(k): dict(v) for k, v in session_bucket_spins_by_settlement_st.items()
        },
        "session_bucket_bet_by_settlement_st": {
            str(k): dict(v) for k, v in session_bucket_bet_by_settlement_st.items()
        },
        "session_bucket_win_by_settlement_st": {
            str(k): dict(v) for k, v in session_bucket_win_by_settlement_st.items()
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
        "session_big_win_x20_count": session_big_win_x20_count,
        "session_big_win_x50_count": session_big_win_x50_count,
        "session_big_win_x100_count": session_big_win_x100_count,
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
        # Phase E: TopDollar session behavioral data.
        # Consumed by topdollar_choice.extract().  Empty list for non-TD machines
        # (no ST=14 rounds → inner loop in the per-robot TD block appends nothing).
        "topdollar_sessions": chunk_topdollar_sessions,
        # Rawdata-replay bankruptcy histogram: per-tier survival breakdown
        # derived from the robot round sequences. Merged at finalize;
        # replaces the old live HTTP `run_bankruptcy_probe` loop so
        # `--from-cache` / generate-report get bankruptcy data too.
        # int keys (100/200/500) survive as-is since `rec` flows through
        # the merge loop without JSON round-trip.
        "bankruptcy_sim": simulate_bankruptcy_from_response(
            resp, bet, bankruptcy_session_spins, bankruptcy_bankroll_mults,
            round_win_rules=round_win_rules,
        ),
        # 2026-04-25: raw (cost_bet, cost_win) reps for cross-chunk
        # pooling at merge time. Without this, chunks that fall below
        # session_spins individually (virtual sampling at 1000×8=8000
        # vs session=10000) produce empty per-chunk windows and the
        # bankruptcy panel reports robots=0 across all tiers despite
        # having millions of paid spins. ``_BankruptcyStreamAccumulator``
        # in the merge loop consumes these reps to produce proper
        # cross-chunk pooled results. Old cached chunks (no reps field)
        # fall back to per-chunk merge — produces zeros but doesn't
        # crash, and operators can rebuild reports to refresh.
        "bankruptcy_reps": _extract_bankruptcy_reps(resp, round_win_rules=round_win_rules),
        # C3 enrichment: per-pid payline attribution data.
        # payouts_by_spin_type plugin reads these in extract() to compute
        # shape / covered_columns / paylines / notes per (pid, spin_type).
        "payout_id_payline_hits": {
            pid_s: dict(pl_map)
            for pid_s, pl_map in payout_id_payline_hits.items()
        },
        "payout_id_match_count_dist": {
            pid_s: dict(mc_map)
            for pid_s, mc_map in payout_id_match_count_dist.items()
        },
        "payout_id_col_set": {
            pid_s: sorted(col_set)
            for pid_s, col_set in payout_id_col_set.items()
        },
        "payout_id_has_regular_line": dict(payout_id_has_regular_line),
        # C4 symbol enrichment: per-pid symbol combination histogram.
        # combo_str = "|"-joined column-ordered symbol names per winning line.
        # payouts_by_spin_type plugin reads this in extract() to emit
        # the dominant symbol_combo per (pid, spin_type).
        # payout_ids_top20 aggregates across all STs for the overview table.
        "payout_id_symbol_combos": {
            pid_s: dict(combo_map)
            for pid_s, combo_map in payout_id_symbol_combos.items()
        },
    }
