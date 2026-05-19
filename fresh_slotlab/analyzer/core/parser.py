"""Chunk-parsing primitives carved from ``player_impact_analyzer.py``.

P2-B1a (Phase 2 / Wave 2b sub-ticket): moves 14 helper functions, 1
exception class, and 8 module-level constants out of PIA into this
canonical module. PIA re-exports the same symbols (`from
fresh_slotlab.analyzer.core.parser import ...`) so all external
callers — `_batch_gen_worker.py`, `batch_dev_sampler.py`, scripts/,
tests — keep working unchanged.

**Not** moved here (separate ticket P2-B1b):
  parse_chunk_response — the 1857-line orchestrator that consumes
  every helper in this module. Its sheer size made it too risky to
  carve in one shot; sub-divided per ticket §5 sub-division pattern.

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
from pathlib import Path
from typing import Any


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
