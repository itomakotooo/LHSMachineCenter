"""rtp_integrity — 4-layer RTP integrity gate for the operator's diagnostic surface.

Per session_artifacts/_arch/04_architecture_proposal_v5.md §9 and ticket P2-E1.

This module is the standalone validator that operators run against cached summaries
and rawdata chunks. It does NOT wire into pia.main() (deferred to Phase 5).

No I/O at import time per memory/feedback_subprocess_import_suicide_and_module_globals.md.
All filesystem access occurs inside function bodies, never at module level.

Summary dict schema (input to check_rtp_integrity)
---------------------------------------------------
The ``summary`` parameter is the raw accumulator dict that PIA builds across
chunks. It supports two layouts:

**Flat layout** (analyzer internal / test format):
    summary["payout_id_win"]              — dict[str, float]  pid → total win
    summary["chunk_win_total"]            — float             total win across all chunks
    summary["payout_id_hits"]             — dict[str, int]    pid → hit count
    summary["payout_id_by_spin_type_total"] — dict[str, dict[str,int]]  pid → {st_str → count}
    summary["machine"]                    — str
    summary["mode"]                       — int

**Nested layout** (player_impact_summary.json on disk):
    summary["rtp"]["our_total_win"]                        — float
    summary["player_impact"]["payout_ids_top20"]           — list of row dicts
        row["payout_id"]       — str
        row["total_win"]       — float
        row["hit_count"]       — int
        row["spin_type_breakdown"] — list[{"spin_type": int, "count": int}]
    summary["machine"]                                     — str
    summary["mode"]                                        — int

Both layouts are supported. Flat layout takes precedence if ``payout_id_win`` is
present at the top level. Otherwise the nested layout is used.

Manifest dict schema
--------------------
The ``manifest`` parameter supports two layouts:

**Flat layout** (test format):
    manifest["layer4_applicable"]              — bool
    manifest["required_attribution_anchors"]   — list[str]
    manifest["trigger_session_pattern"]        — str | None
    manifest["console_diagnostic_complete"]    — bool

**Nested layout** (fully resolved manifest JSON):
    manifest["layer4_applicable"]                              — bool
    manifest["rtp_integrity_contract"]["required_attribution_anchors"] — list[str]
    manifest["trigger_session_pattern"]                        — str | None
    manifest["console_diagnostic_complete"]                    — bool

Both layouts are supported. Flat layout (top-level ``required_attribution_anchors``)
takes precedence over the nested ``rtp_integrity_contract`` sub-dict.

Public API
----------
- RTPIntegrityResult   — frozen dataclass, 20 fields (16 original §9.2 + 4 conservation fields 2026-06-11)
- RTPIntegrityError    — raised in strict (warn_only=False) mode on failure
- Layer4Error          — raised inside Step B on SpinType / JSON corruption
- check_rtp_integrity  — main entry point; 4-layer check on a summary dict
- main                 — CLI: ``python -m fresh_slotlab.analyzer.rtp_integrity --machine M ...``

Layers (per §9.2 / §9.4)
--------------------------
Layer 1 — Hard arithmetic invariant: sum(payout_id win) == chunk_win total.
Layer 2 — Fallback-bucket non-existence: no payout_id starts with a reserved prefix.
           Reserved prefixes: _unattributed_, _other, _default, _misc
           (per §9.2 verbatim; memory/feedback_invariant_with_fallback_hides_drift.md).
Layer 3 — Attribution-anchor coverage: manifest's required_attribution_anchors all have >0 hits.
Layer 4 — Dispatch routing self-consistency via rawdata cross-check (Step A/B/C per §9.4).
           Skipped for trigger-session machines (manifest.layer4_applicable=False).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RTPIntegrityError(Exception):
    """Raised in strict (warn_only=False) mode when any applicable layer fails.

    Contains the result's summary_message as the exception message.
    Callers that need structured data can access ``.result`` attribute for the
    full RTPIntegrityResult.

    Per ticket §1 contract C7: warn-only mode default; strict mode raises.
    Per memory/feedback_no_silent_swallow.md: never silently swallow result.
    """

    def __init__(self, message: str, result: "RTPIntegrityResult | None" = None) -> None:
        super().__init__(message)
        self.result = result


class Layer4Error(Exception):
    """Raised inside Layer 4 Step B on data corruption or schema drift.

    Per §9.4 Step B edge case table: SpinType missing or invalid → raise.
    Propagates out of check_rtp_integrity when Layer 4 encounters corrupt data.

    NOT the same as RTPIntegrityError — this is a hard error indicating
    data corruption, not a soft integrity failure.
    """


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Reserved fallback-bucket prefixes per §9.2 Layer 2 verbatim.
# Memory: feedback_invariant_with_fallback_hides_drift.md — these are ALARM
# signals, not accounting residuals. The entire point of Layer 2 is to make
# them explicit rather than hiding behind a GREEN_OK invariant result.
_FALLBACK_PREFIXES: tuple[str, ...] = (
    "_unattributed_",
    "_other",
    "_default",
    "_misc",
)

# Absolute tolerance for Layer 1 floating-point comparison (per ticket §2.b).
# Matches the 1e-6 absolute tolerance in the brief rather than a relative
# tolerance, so that machines with very small total_win still trigger correctly.
_LAYER1_ABS_TOLERANCE: float = 1e-6


# ---------------------------------------------------------------------------
# RTPIntegrityResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RTPIntegrityResult:
    """Structured result of a 4-layer RTP integrity check.

    Per ticket §1 / 04_architecture_proposal_v5.md §9.2 Combined check structure.

    Original ticket §1 listed 15 named fields + ``completeness_declared`` = 16 fields.
    2026-06-11 (FRAMEWORK_PASS_2026-06-11.md §A): four session-conservation fields
    added (session_conservation_ok, session_conservation_level,
    session_conservation_skip_reason, session_conservation_notes) bringing the total to 20.

    Fields
    ------
    machine:
        Machine identifier string (e.g. "M14").
    mode:
        Integer mode number (e.g. 1).
    passed:
        True iff ALL applicable layers pass.
        Layer 4 contributes only when layer4_applicable=True and rawdata_dir was provided.
    layer1_invariant_ok:
        True if sum(payout_id win) == chunk_win within _LAYER1_ABS_TOLERANCE.
    layer1_error:
        Human-readable error string when layer1_invariant_ok=False; else None.
    layer2_no_fallback_buckets_ok:
        True if no payout_id starts with a reserved fallback prefix.
    layer2_fallback_buckets_found:
        List of payout_ids that start with a reserved prefix (empty on pass).
    layer3_anchors_ok:
        True if all required_attribution_anchors from manifest have >0 hits.
    layer3_missing_anchors:
        List of anchor ids missing or zero-hit in summary (empty on pass).
    layer4_applicable:
        False for trigger-session machines (manifest.layer4_applicable=False or
        manifest.trigger_session_pattern != null).
    layer4_per_st_consistency_ok:
        True/False when layer4_applicable=True and rawdata_dir provided; None when skipped.
    layer4_inconsistencies:
        List of inconsistency dicts when layer4 fails; empty otherwise.
        Each dict: {"pay_id", "spin_type", "analyzer_dispatch_count",
        "rawdata_observed_count", "difference", "is_fallback_pid", "note"}.
    layer4_skip_reason:
        Human-readable reason string when layer4_per_st_consistency_ok=None; else None.
    summary_message:
        One-line human-readable verdict suitable for CLI output and log files.
    suggested_actions:
        List of operator-facing action strings derived from which layers failed.
    completeness_declared:
        Mirrors manifest.console_diagnostic_complete (default False if no manifest).
    session_conservation_ok:
        Convenience bool: True iff session_conservation_level == "ok".
        False when level is "warn" or "fail". None when the check is skipped.
        Does NOT flip ``passed`` — the check is informational only.
    session_conservation_level:
        "ok" | "warn" | "fail" when evaluated; None when skipped.
        Level classification:
          "ok"   — |session_win_sum / total_win - 1| < 1%  (conservation holds)
          "warn" — difference 1%–5%  (plausible orphan bonus or rounding)
          "fail" — difference >= 5%  (investigate session_dim_win computation)
        None when session_conservation_ok is None (check was skipped).
    session_conservation_skip_reason:
        Human-readable reason string when session_conservation_ok=None; else None.
    session_conservation_notes:
        List of human-readable strings explaining the check result (ratio,
        orphan-bonus caveat, tolerance class). Empty when skipped or when no notes.
    """

    machine: str
    mode: int
    passed: bool
    layer1_invariant_ok: bool
    layer1_error: str | None
    layer2_no_fallback_buckets_ok: bool
    layer2_fallback_buckets_found: list[str]
    layer3_anchors_ok: bool
    layer3_missing_anchors: list[str]
    layer4_applicable: bool
    layer4_per_st_consistency_ok: bool | None
    layer4_inconsistencies: list[dict]
    layer4_skip_reason: str | None
    summary_message: str
    suggested_actions: list[str]
    completeness_declared: bool
    # Session-conservation check (2026-06-11, session-dim fix).
    # Populated only when machine_spec_manifest is passed to check_rtp_integrity
    # and all ST economy.kind == "real"; None otherwise.
    session_conservation_ok: bool | None
    session_conservation_level: str | None  # "ok" | "warn" | "fail" | None
    session_conservation_skip_reason: str | None
    session_conservation_notes: list[str]


# ---------------------------------------------------------------------------
# Internal helpers — summary schema access (dual-layout support)
# ---------------------------------------------------------------------------

def _is_flat_layout(summary: dict[str, Any]) -> bool:
    """Return True if summary uses the flat accumulator layout.

    Flat layout has ``payout_id_win`` directly at the top level.
    Nested layout uses ``player_impact.payout_ids_top20``.
    """
    return "payout_id_win" in summary


def _get_payout_id_win(summary: dict[str, Any]) -> dict[str, float]:
    """Return {pid_str: float} total win per payout_id from either layout."""
    if _is_flat_layout(summary):
        raw = summary.get("payout_id_win") or {}
        return {str(k): float(v) for k, v in raw.items()}
    # Nested layout: reconstruct from payout_ids_top20
    pi = summary.get("player_impact") or {}
    rows = pi.get("payout_ids_top20") or []
    return {
        str(row.get("payout_id", "")): float(row.get("total_win", 0))
        for row in rows
    }


def _get_chunk_win_total(summary: dict[str, Any]) -> float | None:
    """Return the canonical total win from either layout.

    Flat layout: summary["chunk_win_total"].
    Nested layout: summary["rtp"]["our_total_win"].

    Returns None when the field is absent (old format or truncated JSON).
    """
    if _is_flat_layout(summary):
        val = summary.get("chunk_win_total")
    else:
        rtp = summary.get("rtp") or {}
        val = rtp.get("our_total_win")
    if val is None:
        return None
    return float(val)


def _get_payout_id_hits(summary: dict[str, Any]) -> dict[str, int]:
    """Return {pid_str: int} hit count per payout_id from either layout."""
    if _is_flat_layout(summary):
        raw = summary.get("payout_id_hits") or {}
        return {str(k): int(v) for k, v in raw.items()}
    # Nested layout: reconstruct from payout_ids_top20
    pi = summary.get("player_impact") or {}
    rows = pi.get("payout_ids_top20") or []
    return {
        str(row.get("payout_id", "")): int(row.get("hit_count", 0))
        for row in rows
    }


def _get_payout_id_by_spin_type_total(
    summary: dict[str, Any],
) -> dict[str, dict[int, int]]:
    """Return {pid_str: {st_int: count}} dispatch data from either layout.

    Flat layout: summary["payout_id_by_spin_type_total"] — values are {str: int}.
    Nested layout: reconstructed from payout_ids_top20[*].spin_type_breakdown.

    Returns empty dict when the field is absent or empty.
    """
    if _is_flat_layout(summary):
        raw = summary.get("payout_id_by_spin_type_total") or {}
        result: dict[str, dict[int, int]] = {}
        for pid_str, st_map in raw.items():
            if isinstance(st_map, dict):
                result[str(pid_str)] = {int(st): int(cnt) for st, cnt in st_map.items()}
        return result
    # Nested layout: reconstruct from payout_ids_top20 spin_type_breakdown
    pi = summary.get("player_impact") or {}
    rows = pi.get("payout_ids_top20") or []
    result = {}
    for row in rows:
        pid_str = str(row.get("payout_id", ""))
        breakdown = row.get("spin_type_breakdown") or []
        st_counts: dict[int, int] = {}
        for entry in breakdown:
            if isinstance(entry, dict):
                st = int(entry.get("spin_type", 0))
                count = int(entry.get("count", 0))
                st_counts[st] = st_counts.get(st, 0) + count
        if st_counts:
            result[pid_str] = st_counts
    return result


# ---------------------------------------------------------------------------
# Internal helpers — manifest schema access (dual-layout support)
# ---------------------------------------------------------------------------

def _get_required_attribution_anchors(manifest: dict[str, Any]) -> list[str]:
    """Return required_attribution_anchors from either manifest layout.

    Flat layout: manifest["required_attribution_anchors"]
    Nested layout: manifest["rtp_integrity_contract"]["required_attribution_anchors"]
    """
    # Flat layout takes precedence (test format).
    if "required_attribution_anchors" in manifest:
        return [str(a) for a in (manifest["required_attribution_anchors"] or [])]
    # Nested layout.
    ric = manifest.get("rtp_integrity_contract") or {}
    return [str(a) for a in (ric.get("required_attribution_anchors") or [])]


# ---------------------------------------------------------------------------
# Internal helpers — pure functions, no I/O
# ---------------------------------------------------------------------------

def _is_fallback_pid(pid_str: str) -> bool:
    """Return True if *pid_str* starts with any reserved fallback prefix per §9.2 Layer 2."""
    return any(pid_str.startswith(prefix) for prefix in _FALLBACK_PREFIXES)


def _build_analyzer_dispatch(
    pid_by_spin_type_total: dict[str, dict[int, int]],
) -> dict[Any, dict[int, int]]:
    """Build analyzer_dispatch from payout_id_by_spin_type_total.

    Per §9.4 Step A:
      for pid_str, st_counts in payout_id_by_spin_type_total.items():
          pid = int(pid_str) if pid_str.isdigit() else pid_str
          analyzer_dispatch[pid] = dict(st_counts)

    Keys are int when the pid is purely numeric, else str (same rule as §9.4).
    """
    dispatch: dict[Any, dict[int, int]] = {}
    for pid_str, st_counts in pid_by_spin_type_total.items():
        pid: Any = int(pid_str) if pid_str.isdigit() else pid_str
        dispatch[pid] = dict(st_counts)
    return dispatch


def _run_layer4_step_b(rawdata_dir: Path) -> dict[Any, dict[int, int]]:
    """Step B — independent fresh scan of rawdata chunk files.

    Per §9.4 Step B: iterate ALL chunk_*.json files in rawdata_dir.
    For each robot_response in chunk["response"], iterate roundResult rounds.
    For each round, read SpinType (int) and PayoutIdToWinAmount.keys().
    Increment fresh_dispatch[pid][st] for each pid key present.

    Per §9.4 edge case table:
    - SpinType missing → raise Layer4Error (data corruption).
    - SpinType invalid (not int-castable) → raise Layer4Error.
    - PayoutIdToWinAmount missing/null → skip round (zero-win spin).
    - pid key non-numeric → kept as str.
    - 0-win pid (fired but zero payout) → counted by key existence.
    - Malformed JSON chunk → raises json.JSONDecodeError (caller catches).
    - No chunks found → raises Layer4Error with explicit diagnostic.

    Does NOT call compute_trigger_sessions (applicability gate ensures this
    runs only when trigger_session_pattern=null per §9.4 constraint).

    roundResult handling: may be a JSON-encoded string (upstream API format)
    or a list (in-memory / pre-decoded). Matches parse_rounds() in core/parser.py.
    """
    chunk_paths = sorted(rawdata_dir.glob("chunk_*.json"))
    if not chunk_paths:
        raise Layer4Error(
            f"Layer 4 cannot run: no rawdata chunks found at {rawdata_dir!s}. "
            f"Possible cause: rawdata not yet sampled or deleted. "
            f"Run sampling for this (machine, mode) first."
        )

    fresh_dispatch: dict[Any, dict[int, int]] = {}

    for chunk_path in chunk_paths:
        try:
            chunk = json.loads(chunk_path.read_bytes())
        except json.JSONDecodeError as exc:
            raise json.JSONDecodeError(
                f"Layer 4 Step B: malformed JSON in chunk {chunk_path!s}: {exc.msg}",
                exc.doc,
                exc.pos,
            ) from exc

        robot_responses = chunk.get("response") or []
        for robot_response in robot_responses:
            if not isinstance(robot_response, dict):
                continue
            robot_id = robot_response.get("robotId", "<unknown>")

            # roundResult may be a JSON-encoded string (upstream API format)
            # or a list (in-memory or pre-decoded). Mirrors parse_rounds() semantics.
            rr_raw = robot_response.get("roundResult")
            if not rr_raw:
                continue
            if isinstance(rr_raw, str):
                try:
                    round_results = json.loads(rr_raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(round_results, list):
                    continue
            elif isinstance(rr_raw, list):
                round_results = rr_raw
            else:
                continue

            for round_result in round_results:
                if not isinstance(round_result, dict):
                    continue

                # SpinType field validation per §9.4 Step B edge case table.
                raw_st = round_result.get("SpinType")
                if raw_st is None:
                    raise Layer4Error(
                        f"SpinType field missing in round at "
                        f"{chunk_path!s}:{robot_id}. "
                        f"Possible cause: data corruption or rawdata envelope version drift."
                    )
                try:
                    st = int(raw_st)
                except (TypeError, ValueError):
                    raise Layer4Error(
                        f"SpinType field invalid (value={raw_st!r}) at "
                        f"{chunk_path!s}:{robot_id}."
                    )

                # Count pid existence in PayoutIdToWinAmount (0-win included per §9.4).
                payout_id_to_win = round_result.get("PayoutIdToWinAmount")
                if not isinstance(payout_id_to_win, dict):
                    # Missing or null → zero-win round, skip.
                    continue

                for pid_str in payout_id_to_win.keys():
                    try:
                        pid: Any = int(pid_str)
                    except (TypeError, ValueError):
                        pid = pid_str  # keep as string for non-numeric pids

                    if pid not in fresh_dispatch:
                        fresh_dispatch[pid] = {}
                    fresh_dispatch[pid][st] = fresh_dispatch[pid].get(st, 0) + 1

    return fresh_dispatch


def _build_suggested_actions(
    l1_ok: bool,
    l2_buckets: list[str],
    l3_missing: list[str],
    l4_applicable: bool,
    l4_ok: bool | None,
    l4_inconsistencies: list[dict],
) -> list[str]:
    """Build operator-facing action list based on which layers failed.

    Per §9.6 (interaction with manifest validation):
    - Layer 2 fail → "add/fix features or keep console_diagnostic_complete: false"
    - Layer 3 fail → "investigate round_win_rule that synthesizes anchor X"
    - Layer 4 fail → "investigate round_classification rules for mismatched ST"
    """
    actions: list[str] = []
    if not l1_ok:
        actions.append(
            "Layer 1 FAIL: sum(payout_id_win) != chunk_win_total. "
            "Investigate accumulator logic in parse_chunk_response or chunk aggregation. "
            "Check for double-counting or missed pids in payout_id_win accumulator."
        )
    if l2_buckets:
        prefix_list = ", ".join(repr(p) for p in _FALLBACK_PREFIXES)
        actions.append(
            f"Layer 2 FAIL: fallback buckets found: {l2_buckets!r}. "
            f"Add per-machine RoundWinRule(s) to attribute these wins to real pay_ids. "
            f"Reserved prefixes ({prefix_list}) are alarm signals, not residuals. "
            f"Keep console_diagnostic_complete: false until all buckets are attributed."
        )
    if l3_missing:
        actions.append(
            f"Layer 3 FAIL: required attribution anchors missing or zero-hit: {l3_missing!r}. "
            f"The round_win_rule(s) that synthesize these pay_ids may not be firing. "
            f"Verify the rule is in manifest.round_win_rules and applies_to includes this machine."
        )
    if l4_applicable and l4_ok is False:
        # Extract a compact summary of the worst inconsistencies.
        worst = sorted(
            l4_inconsistencies,
            key=lambda x: abs(x.get("difference") or 0),
            reverse=True,
        )[:3]
        short = [
            f"pid={e['pay_id']}, ST={e['spin_type']}, "
            f"analyzer={e['analyzer_dispatch_count']}, rawdata={e['rawdata_observed_count']}"
            for e in worst
            if e.get("pay_id") is not None
        ]
        actions.append(
            f"Layer 4 FAIL: {len(l4_inconsistencies)} dispatch routing mismatch(es). "
            f"Worst offenders: {short}. "
            f"Investigate round_classification rules for the mismatched SpinType(s). "
            f"The 'note' field in each inconsistency entry provides the starting hypothesis."
        )
    if not actions:
        actions.append("All applicable layers pass. No action required.")
    return actions


# ---------------------------------------------------------------------------
# Session-conservation check helpers (2026-06-11, session-dim fix)
# ---------------------------------------------------------------------------

def _all_sts_real_economy(machine_spec_manifest: dict[str, Any]) -> bool:
    """Return True iff every ST in the manifest declares economy.kind == 'real'.

    Machines with any preview ST (e.g. M15 ST14 economy.kind='preview') return
    False — the session-dim total is rule-view (not raw), so conservation does not
    hold by design.  Machines with no spin_types declared also return False.
    """
    spin_types = machine_spec_manifest.get("spin_types") or {}
    if not spin_types:
        return False
    for _st_key, _st_info in spin_types.items():
        if not isinstance(_st_info, dict):
            return False
        econ = _st_info.get("economy") or {}
        if econ.get("kind") != "real":
            return False
    return True


def _check_session_conservation(
    machine_spec_manifest: dict[str, Any],
    *,
    session_win_total: float | None,
    total_win: float | None,
) -> tuple[bool | None, str | None, str | None, list[str]]:
    """Run the session-conservation check.

    Returns (ok, level, skip_reason, notes).
      ok           — True iff level=="ok"; False for "warn"/"fail"; None for skip.
      level        — "ok" | "warn" | "fail" when evaluated; None when skipped.
      skip_reason  — human-readable string when ok=None, else None.
      notes        — list of human-readable detail strings.

    Conservation invariant (when applicable):
      sum(session_dim_win for all sessions) ≈ total_win

    Caveat: orphan bonus rounds (bonus rounds before the first paid round, or
    after the last paid round closes) contribute to total_win but are NOT
    attributed to any session.  The standard summary JSON does not currently
    surface orphan bonus win separately, so the check uses a WARN threshold
    rather than demanding exact equality.

    Level classification:
      "ok"   — |session_win_sum / total_win - 1| < 0.01 (1% tolerance)
      "warn" — difference between 1% and 5% (plausible orphan bonus or rounding)
      "fail" — |session_win_sum / total_win - 1| >= 0.05 (5%) AND both > 0

    Machines with preview STs (session_dim_win is rule-view, conservation does
    NOT hold) → SKIP with explicit reason.
    """
    notes: list[str] = []

    # Gate 1: machine_spec_manifest must declare all-real economy.
    if not _all_sts_real_economy(machine_spec_manifest):
        # Build a precise skip reason by categorising which STs failed.
        spin_types = machine_spec_manifest.get("spin_types") or {}
        malformed_sts = [
            str(st_k)
            for st_k, st_info in spin_types.items()
            if not isinstance(st_info, dict)
        ]
        non_real_sts = [
            str(st_k)
            for st_k, st_info in spin_types.items()
            if isinstance(st_info, dict)
            and (st_info.get("economy") or {}).get("kind") != "real"
        ]
        if malformed_sts:
            skip_reason = (
                f"malformed spin_types entr{'y' if len(malformed_sts) == 1 else 'ies'} "
                f"(not a dict): {malformed_sts}. "
                f"Cannot determine economy.kind. "
                f"Conservation check skipped."
            )
        elif non_real_sts:
            skip_reason = (
                f"preview or non-real economy STs present: {non_real_sts}. "
                f"session_dim_win is rule-view (phantom rounds contribute 0), "
                f"so sum(session_dim_win) < total_win by design. "
                f"Conservation check skipped for this machine."
            )
        elif not spin_types:
            skip_reason = (
                "machine_spec_manifest has no spin_types block. "
                "Cannot determine economy.kind for all STs. "
                "Conservation check skipped."
            )
        else:
            skip_reason = (
                "Not all STs declare economy.kind == 'real'. "
                "Conservation check skipped."
            )
        return None, None, skip_reason, notes

    # Gate 2: session_win_total must have been passed explicitly.
    # report_engine passes total_session_win_sum (Σ chunk-record session_win_sum),
    # which post-dim-fix IS the session-dim total (bonus_win_from_helper now holds
    # session_dim_win, not session_win).  Direct callers and tests pass it too.
    # There is no fallback to summary key lookup — that path was dead on arrival
    # (session_dim_win_sum was never written to the summary JSON).
    session_win_sum = session_win_total
    if session_win_sum is None:
        skip_reason = (
            "session_win_total not provided to check_rtp_integrity. "
            "Pass session_win_total=total_session_win_sum from report_engine "
            "to enable the conservation check."
        )
        return None, None, skip_reason, notes

    # Gate 3: total_win must be known.
    if total_win is None or total_win <= 0.0:
        skip_reason = (
            f"total_win={total_win!r} is absent or zero; "
            "cannot compute conservation ratio. Check skipped."
        )
        return None, None, skip_reason, notes

    # Conservation ratio and classification.
    ratio = session_win_sum / total_win
    diff_pct = abs(ratio - 1.0) * 100.0

    notes.append(
        f"session_win_sum={session_win_sum:.1f}, total_win={total_win:.1f}, "
        f"ratio={ratio:.6f} (diff={diff_pct:.2f}%)."
    )
    notes.append(
        "Caveat: orphan bonus rounds (bonus before first paid round) contribute "
        "to total_win but not to session_win_sum, so a small negative gap is "
        "expected and normal.  The standard summary JSON does not surface orphan "
        "bonus win separately; diff < 5% is classified WARN (not FAIL) for this reason."
    )

    # Classify into three levels: "ok" / "warn" / "fail".
    level: str
    if diff_pct < 1.0:
        # Tight match — conservation holds.
        level = "ok"
        notes.append("Conservation OK: diff < 1%.")
    elif diff_pct < 5.0:
        # Plausible orphan-bonus gap or minor rounding.
        level = "warn"
        notes.append(
            f"Conservation WARN: diff {diff_pct:.2f}% is in the 1%-5% range. "
            "Likely orphan bonus rounds or rounding across chunks. "
            "Investigate if unexpected."
        )
    else:
        # Substantial gap — likely a session-dim bug or attribution issue.
        level = "fail"
        notes.append(
            f"Conservation FAIL: diff {diff_pct:.2f}% >= 5%. "
            "Investigate session_dim_win computation in trigger_sessions.py "
            "and _close_session in parser.py."
        )

    ok: bool | None = (level == "ok")
    return ok, level, None, notes


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------

def check_rtp_integrity(
    summary: dict[str, Any],
    *,
    manifest: dict[str, Any] | None = None,
    machine_spec_manifest: dict[str, Any] | None = None,
    session_win_total: float | None = None,
    rawdata_dir: Path | None = None,
    warn_only: bool = True,
) -> "RTPIntegrityResult":
    """Run the 4-layer RTP integrity check against *summary*.

    Parameters
    ----------
    summary:
        Analyzer summary dict. Supports two layouts — see module docstring.
        Must contain at minimum:
        - machine / mode identifiers
        - payout_id win amounts (for Layer 1 + Layer 2)
        - payout_id hit counts (for Layer 3)
        - payout_id_by_spin_type dispatch data (for Layer 4 Step A)
    manifest:
        Parsed manifest dict (flat or nested layout — see module docstring).
        If None: Layer 3 vacuously passes (no required anchors); Layer 4 defaults
        to applicable=True; completeness_declared=False.
    machine_spec_manifest:
        SpinType-native manifest dict (configs/machine_manifests/<M>.json format).
        When provided and all ST economy.kind == "real", runs the session-
        conservation check (``session_conservation_ok``).  When None or when any
        ST has economy.kind != "real" (e.g. M15 preview STs), the conservation
        check is skipped with an explicit reason.  The check does NOT flip
        ``passed`` — it is informational and surfaced via ``session_conservation_ok``.
    session_win_total:
        Explicit session-dimension win total (Σ chunk-record session_win_sum).
        After the 2026-06-11 session-dim fix, report_engine's total_session_win_sum
        accumulates session_win_sum per chunk, and _close_session's bonus_win_from_helper
        now holds session_dim_win (player-experienced total, no credited-win exclusion).
        So total_session_win_sum IS the session-dim total.  Pass it explicitly here
        rather than relying on summary key lookup (which was dead — session_dim_win_sum
        was never written to the summary JSON).  When None, the conservation check
        records a skip with an explicit reason.
    rawdata_dir:
        Path to directory containing chunk_*.json files for Layer 4 Step B.
        If None: Layer 4 Step B is skipped with a descriptive skip_reason.
        Layer 4 not evaluated ≠ Layer 4 failed: when skipped, layer4_per_st_consistency_ok=None
        and this does NOT contribute to pass/fail.
    warn_only:
        True (default): return result even if layers fail; never raise.
        False (strict): raise RTPIntegrityError when any applicable layer fails.
        Per ticket §1 C7: supports Phase 5 policy flip via single bool change.

    Returns
    -------
    RTPIntegrityResult
        Frozen dataclass with all layer results + summary_message + actions.

    Raises
    ------
    RTPIntegrityError
        Only when warn_only=False AND any applicable layer fails.
    Layer4Error
        Propagated from Step B when SpinType is missing or invalid (data corruption).
        This is a hard error, not a soft integrity failure — propagates regardless
        of warn_only setting.
    json.JSONDecodeError
        Propagated from Step B when a chunk file has malformed JSON.

    Per memory/feedback_no_silent_swallow.md: result is always returned or raised;
    never silently swallowed.

    Ticket references: §1 contracts C1-C9, 04_v5 §9.2, §9.4.
    """
    machine: str = str(summary.get("machine", "<unknown>"))
    mode: int = int(summary.get("mode", 0))

    # Extract payout_id data (dual-layout support).
    payout_id_win = _get_payout_id_win(summary)
    chunk_win_total = _get_chunk_win_total(summary)
    payout_id_hits = _get_payout_id_hits(summary)
    pid_by_spin_type = _get_payout_id_by_spin_type_total(summary)

    # ------------------------------------------------------------------
    # Layer 1 — Hard arithmetic invariant
    # sum(payout_id win) == chunk_win_total within _LAYER1_ABS_TOLERANCE.
    # Per §9.2 Layer 1 + ticket §1 C2.
    # ------------------------------------------------------------------
    pid_win_sum = sum(payout_id_win.values())

    if chunk_win_total is None:
        layer1_invariant_ok = False
        layer1_error = (
            "chunk_win_total / rtp.our_total_win is absent from summary. "
            "Cannot evaluate Layer 1 invariant. "
            "Old summary format or truncated JSON? Regenerate the report."
        )
    else:
        diff = abs(pid_win_sum - chunk_win_total)
        if diff > _LAYER1_ABS_TOLERANCE:
            layer1_invariant_ok = False
            layer1_error = (
                f"sum(payout_id_win)={pid_win_sum:.6f} != chunk_win_total={chunk_win_total:.6f} "
                f"(diff={diff:.6f} > tolerance={_LAYER1_ABS_TOLERANCE}). "
                f"Arithmetic drift detected in accumulator. "
                f"Investigate double-counting or missed pids in payout_id_win."
            )
        else:
            layer1_invariant_ok = True
            layer1_error = None

    # ------------------------------------------------------------------
    # Layer 2 — Fallback-bucket non-existence
    # No payout_id starts with a reserved prefix per §9.2 Layer 2.
    # Reserved prefixes: _unattributed_, _other, _default, _misc (verbatim §9.2).
    # Per memory/feedback_invariant_with_fallback_hides_drift.md: any fallback
    # bucket is an alarm signal. No statistical threshold.
    # Ticket §1 C3.
    # ------------------------------------------------------------------
    layer2_fallback_buckets_found: list[str] = [
        pid_str
        for pid_str in payout_id_win.keys()
        if _is_fallback_pid(pid_str)
    ]
    layer2_no_fallback_buckets_ok = len(layer2_fallback_buckets_found) == 0

    # ------------------------------------------------------------------
    # Layer 3 — Attribution-anchor coverage
    # Per §9.2 Layer 3 + ticket §1 C4.
    # required_attribution_anchors from manifest (flat or nested layout).
    # Default [] (no manifest → vacuously passes).
    # ------------------------------------------------------------------
    required_anchors: list[str] = []
    completeness_declared: bool = False
    if manifest is not None:
        required_anchors = _get_required_attribution_anchors(manifest)
        completeness_declared = bool(manifest.get("console_diagnostic_complete", False))

    layer3_missing_anchors: list[str] = [
        anchor_str
        for anchor_str in required_anchors
        if payout_id_hits.get(str(anchor_str), 0) == 0
    ]
    layer3_anchors_ok = len(layer3_missing_anchors) == 0

    # ------------------------------------------------------------------
    # Layer 4 — Dispatch routing self-consistency via rawdata cross-check
    # Per §9.4 (v5 applicability gate + Step A/B/C).
    # Ticket §1 C5 (skip gate) + C6 (Step A/B/C consistency).
    # ------------------------------------------------------------------
    layer4_applicable: bool = True
    layer4_per_st_consistency_ok: bool | None = None
    layer4_inconsistencies: list[dict] = []
    layer4_skip_reason: str | None = None

    # Applicability gate: per §9.4 manifest.layer4_applicable check.
    # If no manifest, default layer4_applicable=True (no trigger_session_pattern known).
    if manifest is not None:
        # Read layer4_applicable directly if present; else derive from trigger_session_pattern.
        raw_l4a = manifest.get("layer4_applicable")
        if raw_l4a is False:
            layer4_applicable = False
        elif raw_l4a is True:
            layer4_applicable = True
        else:
            # Field absent: derive from trigger_session_pattern (Patch P1 semantics).
            tsp = manifest.get("trigger_session_pattern")
            layer4_applicable = (tsp is None)

        if not layer4_applicable:
            tsp = manifest.get("trigger_session_pattern")
            layer4_skip_reason = (
                f"trigger_session_pattern={tsp!r}; "
                f"compute_trigger_sessions re-attributes free-spin round pids to paid-spin bucket, "
                f"making naive rawdata SpinType counts incomparable to analyzer_dispatch counts. "
                f"Layer 4 skipped. Layers 1-3 are enforced."
            )

    if layer4_applicable:
        if rawdata_dir is None:
            # rawdata_dir not provided → Layer 4 not evaluable, not failed.
            # Per §9.5: when rawdata_dir is absent the caller is running a summary-only check.
            layer4_per_st_consistency_ok = None
            layer4_skip_reason = (
                "rawdata_dir not provided; Layer 4 Step B (rawdata cross-check) skipped. "
                "Pass rawdata_dir to enable full Layer 4 validation."
            )
        else:
            rawdata_dir = Path(rawdata_dir)
            # Step A — Capture analyzer dispatch from payout_id_by_spin_type_total.
            # Per §9.4: "This dict drives both payouts_by_spin_type AND spin_type_breakdown."
            analyzer_dispatch = _build_analyzer_dispatch(pid_by_spin_type)

            # Step B — Independent fresh scan of rawdata chunk files.
            # Layer4Error (SpinType missing/invalid) and Layer4Error (no chunks found)
            # propagate to the caller — they are hard errors (data corruption / missing data),
            # not soft integrity failures. The caller is responsible for logging them.
            # json.JSONDecodeError (malformed chunk JSON) also propagates.
            fresh_dispatch = _run_layer4_step_b(rawdata_dir)

            # Step C — Compare analyzer_dispatch vs fresh_dispatch.
            # Per §9.4 Step C: for each (pid, st) where counts differ, append entry.
            # NOTE: §9.4 says do NOT suppress _unattributed_* mismatches.
            # They corroborate Layer 2's fallback detection (additive evidence).
            inconsistencies: list[dict] = []
            all_pids = set(analyzer_dispatch.keys()) | set(fresh_dispatch.keys())
            for pid in all_pids:
                a_sts = analyzer_dispatch.get(pid, {})
                f_sts = fresh_dispatch.get(pid, {})
                all_sts = set(a_sts.keys()) | set(f_sts.keys())
                for st in all_sts:
                    a_count = a_sts.get(st, 0)
                    f_count = f_sts.get(st, 0)
                    if a_count != f_count:
                        pid_str_for_check = str(pid)
                        is_fallback = _is_fallback_pid(pid_str_for_check)
                        inconsistencies.append({
                            "pay_id": pid,
                            "spin_type": st,
                            "analyzer_dispatch_count": a_count,
                            "rawdata_observed_count": f_count,
                            "difference": a_count - f_count,
                            "is_fallback_pid": is_fallback,
                            "note": (
                                f"Analyzer dispatched {a_count} round(s) with "
                                f"pid={pid} to ST={st}; rawdata shows {f_count}. "
                                + (
                                    f"[FALLBACK PID] This mismatch corroborates "
                                    f"Layer 2's fallback-bucket detection. "
                                    f"The fallback synthesizer created this synthetic pid "
                                    f"but rawdata has no such pid in PayoutIdToWinAmount. "
                                    f"Do not suppress this mismatch — it is additive "
                                    f"evidence of Layer 2 failure, not a false positive."
                                    if is_fallback else
                                    f"Possible causes: (a) dispatch rule routes these rounds "
                                    f"to wrong ST bucket / (b) round_classification primitive "
                                    f"mismatch for ST={st}. Investigate."
                                )
                            ),
                        })
            layer4_inconsistencies = inconsistencies
            layer4_per_st_consistency_ok = len(inconsistencies) == 0

    # ------------------------------------------------------------------
    # Session-conservation check (2026-06-11, session-dim fix).
    # Informational only — does NOT flip ``passed``.
    # Runs only when machine_spec_manifest is provided and all STs
    # declare economy.kind == "real".  Machines with preview STs (M15)
    # or without a machine_spec_manifest SKIP with an explicit reason.
    # ------------------------------------------------------------------
    session_conservation_ok: bool | None = None
    session_conservation_level: str | None = None
    session_conservation_skip_reason: str | None = None
    session_conservation_notes: list[str] = []

    if machine_spec_manifest is not None:
        (
            session_conservation_ok,
            session_conservation_level,
            session_conservation_skip_reason,
            session_conservation_notes,
        ) = _check_session_conservation(
            machine_spec_manifest,
            session_win_total=session_win_total,
            total_win=chunk_win_total,
        )
    else:
        session_conservation_skip_reason = (
            "machine_spec_manifest not provided; "
            "session-conservation check skipped. "
            "Pass machine_spec_manifest=<manifest_dict> to enable."
        )

    # ------------------------------------------------------------------
    # Final verdict: passed iff ALL applicable layers pass.
    # Layer 4 contributes only when layer4_applicable=True AND
    # layer4_per_st_consistency_ok is not None (i.e., was evaluated).
    # Session-conservation check is informational — does NOT affect passed.
    # Per §9.2: "A machine passes only if all applicable layers pass."
    # Ticket §1 C7.
    # ------------------------------------------------------------------
    l4_contributes = layer4_applicable and (layer4_per_st_consistency_ok is not None)
    passed = (
        layer1_invariant_ok
        and layer2_no_fallback_buckets_ok
        and layer3_anchors_ok
        and (not l4_contributes or layer4_per_st_consistency_ok is True)
    )

    # ------------------------------------------------------------------
    # Summary message + suggested actions
    # ------------------------------------------------------------------
    failed_layers: list[str] = []
    if not layer1_invariant_ok:
        failed_layers.append("L1(arithmetic)")
    if not layer2_no_fallback_buckets_ok:
        failed_layers.append(f"L2(fallback×{len(layer2_fallback_buckets_found)})")
    if not layer3_anchors_ok:
        failed_layers.append(f"L3(anchors×{len(layer3_missing_anchors)})")
    if l4_contributes and not layer4_per_st_consistency_ok:
        failed_layers.append(f"L4(dispatch×{len(layer4_inconsistencies)})")

    if passed:
        l4_status = (
            "L4=SKIP(trigger-session)"
            if not layer4_applicable
            else (
                "L4=SKIP(no-rawdata-dir)"
                if layer4_per_st_consistency_ok is None
                else "L4=PASS"
            )
        )
        summary_message = (
            f"RTP integrity PASS — {machine} mode={mode}. "
            f"L1=PASS, L2=PASS, L3=PASS, {l4_status}."
        )
    else:
        summary_message = (
            f"RTP integrity FAIL — {machine} mode={mode}. "
            f"Failed: {', '.join(failed_layers)}."
        )

    suggested_actions = _build_suggested_actions(
        layer1_invariant_ok,
        layer2_fallback_buckets_found,
        layer3_missing_anchors,
        layer4_applicable,
        layer4_per_st_consistency_ok,
        layer4_inconsistencies,
    )

    result = RTPIntegrityResult(
        machine=machine,
        mode=mode,
        passed=passed,
        layer1_invariant_ok=layer1_invariant_ok,
        layer1_error=layer1_error,
        layer2_no_fallback_buckets_ok=layer2_no_fallback_buckets_ok,
        layer2_fallback_buckets_found=layer2_fallback_buckets_found,
        layer3_anchors_ok=layer3_anchors_ok,
        layer3_missing_anchors=layer3_missing_anchors,
        layer4_applicable=layer4_applicable,
        layer4_per_st_consistency_ok=layer4_per_st_consistency_ok,
        layer4_inconsistencies=layer4_inconsistencies,
        layer4_skip_reason=layer4_skip_reason,
        summary_message=summary_message,
        suggested_actions=suggested_actions,
        completeness_declared=completeness_declared,
        session_conservation_ok=session_conservation_ok,
        session_conservation_level=session_conservation_level,
        session_conservation_skip_reason=session_conservation_skip_reason,
        session_conservation_notes=session_conservation_notes,
    )

    # Per memory/feedback_no_silent_swallow.md: never silently swallow.
    # In warn_only=True mode (default): return result regardless of pass/fail.
    # In warn_only=False mode (strict): raise if any applicable layer failed.
    if not warn_only and not passed:
        raise RTPIntegrityError(summary_message, result=result)

    return result


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _print_result(result: "RTPIntegrityResult") -> None:
    """Print result as JSON to stdout.

    Per ticket §1 C8: JSON output to stdout; error details to stderr.
    Caller decides the exit code.
    """
    import dataclasses

    d = dataclasses.asdict(result)
    print(json.dumps(d, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    """CLI entrypoint: ``python -m fresh_slotlab.analyzer.rtp_integrity [options]``.

    Options
    -------
    --machine M         Machine ID (e.g. M14). Required.
    --mode N            Mode number (e.g. 1). Required.
    --rawdata-dir D     Path to rawdata directory for Layer 4. Optional.
                        When absent, Layer 4 Step B is skipped.
    --manifest-path P   Path to resolved manifest JSON. Optional.
                        When absent, Layers 3+4 use defaults (no anchors, applicable=True).
    --summary-path S    Path to player_impact_summary.json. Optional.
                        When absent, attempts auto-discovery from reports/M/mode_N/versions/
                        latest version.
    --strict            Enable strict (warn_only=False) mode; exits 2 on failure.

    Exit codes
    ----------
    0   All applicable layers pass (or non-strict mode regardless of result).
    1   Usage error (bad arguments or file not found).
    2   One or more applicable layers failed in --strict mode.

    Outputs JSON result to stdout. Error details to stderr.

    Ticket reference: §1 C8 / §3 contract C8.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "RTP integrity gate — 4-layer check on player_impact_summary.json.\n"
            "Per fresh_slotlab/analyzer/rtp_integrity.py §9 architecture spec.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--machine", metavar="M", required=True, help="Machine ID (e.g. M14).")
    parser.add_argument("--mode", metavar="N", type=int, required=True, help="Mode number (e.g. 1).")
    parser.add_argument(
        "--rawdata-dir",
        metavar="D",
        default=None,
        help="Path to rawdata directory for Layer 4 Step B. "
             "When absent, Layer 4 Step B is skipped.",
    )
    parser.add_argument(
        "--manifest-path",
        metavar="P",
        default=None,
        help="Path to a resolved manifest JSON file. Optional.",
    )
    parser.add_argument(
        "--summary-path",
        metavar="S",
        default=None,
        help=(
            "Path to player_impact_summary.json. "
            "When absent, auto-discovers from reports/<M>/mode_<N>/versions/ "
            "(picks the latest version directory)."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Strict mode: exit 2 when any applicable layer fails.",
    )

    args = parser.parse_args()

    # Resolve summary path.
    if args.summary_path:
        summary_path = Path(args.summary_path)
    else:
        # Auto-discover: look for reports/<machine>/mode_<mode>/versions/*/player_impact_summary.json
        repo_root = Path(__file__).resolve().parent.parent.parent
        versions_dir = repo_root / "reports" / args.machine / f"mode_{args.mode}" / "versions"
        if not versions_dir.is_dir():
            print(
                f"ERROR: no reports directory found at {versions_dir!s}. "
                f"Pass --summary-path to specify the summary JSON explicitly.",
                file=sys.stderr,
            )
            return 1
        candidates = [
            vdir / "player_impact_summary.json"
            for vdir in versions_dir.iterdir()
            if vdir.is_dir() and (vdir / "player_impact_summary.json").exists()
        ]
        if not candidates:
            print(
                f"ERROR: no player_impact_summary.json found under {versions_dir!s}.",
                file=sys.stderr,
            )
            return 1
        # Latest by mtime.
        summary_path = max(candidates, key=lambda p: p.stat().st_mtime)

    try:
        summary = json.loads(summary_path.read_bytes())
    except FileNotFoundError:
        print(f"ERROR: summary file not found: {summary_path!s}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: malformed JSON in {summary_path!s}: {exc}", file=sys.stderr)
        return 1

    # Resolve manifest.
    manifest: dict[str, Any] | None = None
    if args.manifest_path:
        mpath = Path(args.manifest_path)
        try:
            manifest = json.loads(mpath.read_bytes())
        except FileNotFoundError:
            print(f"ERROR: manifest file not found: {mpath!s}", file=sys.stderr)
            return 1
        except json.JSONDecodeError as exc:
            print(f"ERROR: malformed JSON in {mpath!s}: {exc}", file=sys.stderr)
            return 1

    # Resolve rawdata_dir.
    rawdata_dir: Path | None = None
    if args.rawdata_dir:
        rawdata_dir = Path(args.rawdata_dir)
        if not rawdata_dir.is_dir():
            print(
                f"ERROR: rawdata_dir not found or not a directory: {rawdata_dir!s}",
                file=sys.stderr,
            )
            return 1

    # Run integrity check.
    # Layer4Error and json.JSONDecodeError from Step B propagate as hard errors.
    try:
        result = check_rtp_integrity(
            summary,
            manifest=manifest,
            rawdata_dir=rawdata_dir,
            warn_only=not args.strict,
        )
    except RTPIntegrityError as exc:
        if exc.result is not None:
            _print_result(exc.result)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Layer4Error as exc:
        print(f"ERROR (Layer 4 data corruption): {exc}", file=sys.stderr)
        return 3
    except json.JSONDecodeError as exc:
        print(f"ERROR: malformed chunk JSON in rawdata: {exc}", file=sys.stderr)
        return 3

    _print_result(result)

    if args.strict and not result.passed:
        return 2
    return 0


# ---------------------------------------------------------------------------
# Module guard — NO module-level I/O.
# Per memory/feedback_subprocess_import_suicide_and_module_globals.md.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(main())
