"""Slim report engine: analysis-from-cache -> player_impact_summary.json.

Phase 2a of the analyzer rebuild (ANALYZER_ARCHITECTURE.md §6 phase 2).

Public API
----------
    generate_report_from_chunks(
        machine_id, mode, *,
        chunk_dir,            # Path to rawdata/M15/mode_1/
        output_dir,           # where to write player_impact_summary.json
        manifests_root=None,  # defaults to configs/machine_manifests/
        bet=1,
        run_id=None,
    ) -> dict

Registered machines only.  If no SpinType-native manifest exists for
``machine_id`` under ``manifests_root``, raises ``MachineNotRegistered``
(caller handles UX in phase 2b).

PORTED from the deleted ``fresh_slotlab/player_impact_analyzer.py``
(git c72b05a^).  The specific sections ported are:
  - The --from-cache chunk-read loop (adapted to accept a chunk_dir path
    directly, stripping all the CLI/argparse/progress-event scaffolding).
  - The per-chunk extract() / reduce() wiring for feature plugins.
  - The full finalization block: session aggregates, RTP/CI, quality
    gates, spin_type_rows, payout_id_rows, payline_rows, symbol rows,
    all stash keys for plugins (_bankruptcy_rows, _collect_mechanic_data,
    _bonus_chain_dynamics_data, _multiplier_profile_data,
    _reel_marginal_by_spin_type_data, _upstream_feature_breakdown_data).
  - The Phase D topo-sort emit loop with DECLARED_DEPS validation and
    error surfacing.
  - The rtp_integrity gate (warn_only=True).
  - The write_summary_json call.

NOT ported (out of scope for phase 2a):
  - Online sampling, SIGTERM/SIGINT, progress JSONL, AIMD tuning.
  - app.py / _batch_gen_worker wiring (phase 2b).

The shared helpers that stay in the engine (they were inline in PIA's
top-level and are used by the stash/finalization blocks):
  _infer_feature_spin_type_mapping, _resolve_bonus_feature,
  _load_bcm_pairings, safe_div — ported verbatim.

Design invariants honored
--------------------------
- feedback_subprocess_import_suicide_and_module_globals.md: no I/O at
  import time; no module-global state.
- feedback_no_silent_swallow.md: every except with side effects persists
  the diagnostic to the summary dict before raising/returning.
- feedback_no_parallel_panel_impl.md: re-uses parser / aggregator / writer
  / feature_registry / topo_sort / pipeline_context from the existing L1/L2
  layers verbatim; no duplicate implementations.
- ANALYZER_ARCHITECTURE.md §5 gate 5 (no silent drift): _unattributed_*
  share surfaced via rtp_integrity, not swallowed.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class MachineNotRegistered(ValueError):
    """Raised when machine_id has no SpinType-native manifest under manifests_root."""


# ---------------------------------------------------------------------------
# Repo-relative default paths (pure path arithmetic, no I/O at import time)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_DEFAULT_MANIFESTS_ROOT = _REPO_ROOT / "configs" / "machine_manifests"

_BCM_CONFIG_PATH = _REPO_ROOT / "configs" / "bcm_pairings.json"

_DEFAULT_GUIDELINE_RULES_PATH = _REPO_ROOT / "configs" / "classic_slots_guideline_rules.json"

# ---------------------------------------------------------------------------
# Tail-bucket sets (ported verbatim from deleted PIA module-level constants)
# ---------------------------------------------------------------------------

TAIL_GEX10_BUCKETS = {
    "ge10_lt20", "ge20_lt50", "ge50_lt100", "ge100_lt200",
    "ge200_lt500", "ge500_lt1000", "ge1000_lt5000", "ge5000",
}
TAIL_GEX20_BUCKETS = {
    "ge20_lt50", "ge50_lt100", "ge100_lt200", "ge200_lt500",
    "ge500_lt1000", "ge1000_lt5000", "ge5000",
}
TAIL_GEX50_BUCKETS = {
    "ge50_lt100", "ge100_lt200", "ge200_lt500",
    "ge500_lt1000", "ge1000_lt5000", "ge5000",
}
TAIL_GEX100_BUCKETS = {
    "ge100_lt200", "ge200_lt500", "ge500_lt1000", "ge1000_lt5000", "ge5000",
}

# Feature names that are NOT the BCM bonus feature (used by _resolve_bonus_feature).
PAID_NORMAL_FEATURES = frozenset({
    "NormalCollectionSpin",
    "BingoCollectionNormalSpin",
    "ReelCollectionNormal",
    "HalloweenReelCollectionNormal",
})

# ---------------------------------------------------------------------------
# Inlined helpers (ported verbatim from deleted PIA — no circular import risk)
# ---------------------------------------------------------------------------

def safe_div(numerator: float, denominator: float) -> float:
    return (numerator / denominator) if denominator > 0 else 0.0


def _load_bcm_pairings() -> dict[str, dict[int, str]]:
    """Load per-machine BCM bonus-feature pairings from configs/bcm_pairings.json.

    Ported verbatim from deleted player_impact_analyzer.py.
    """
    try:
        raw = json.loads(_BCM_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    machines = raw.get("machines") or {}
    out: dict[str, dict[int, str]] = {}
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
    """Map upstream FeatureWin feature_name -> round-level SpinType int.

    Ported verbatim from deleted player_impact_analyzer.py (five-pass algorithm).
    """
    st_spins = {int(k): int(v) for k, v in spin_type_spins.items()}
    st_remarks = {
        int(k): list(v) if isinstance(v, list) else []
        for k, v in (spin_type_remarks_sample or {}).items()
    }
    spin_type_to_feature: dict[int, str] = {}
    feature_to_spin_type: dict[str, int] = {}
    ambiguous_mapped: set[str] = set()

    times_to_features: dict[int, list[str]] = defaultdict(list)
    for feat_name, feat_times in feature_times_total.items():
        if feat_times > 0:
            times_to_features[int(feat_times)].append(str(feat_name))
    times_to_spin_types: dict[int, list[int]] = defaultdict(list)
    for st, cnt in st_spins.items():
        times_to_spin_types[cnt].append(st)

    # Pass 1 — unique fire-count match.
    for feat_times, feats in times_to_features.items():
        sts = times_to_spin_types.get(feat_times) or []
        if len(feats) == 1 and len(sts) == 1:
            spin_type_to_feature[sts[0]] = feats[0]
            feature_to_spin_type[feats[0]] = sts[0]

    # Pass 2 — ReMarks substring, count-compatibility gated.
    feats_lower = {str(f).lower(): str(f) for f in feature_times_total}
    for st, remarks_list in st_remarks.items():
        if st in spin_type_to_feature:
            continue
        st_count = st_spins.get(st, 0)
        for rm in remarks_list:
            rm_lower = rm.lower()
            matched = [feat for fl, feat in feats_lower.items() if fl in rm_lower]
            fresh = [f for f in matched if f not in feature_to_spin_type]
            if len(fresh) != 1:
                continue
            feat_name = fresh[0]
            feat_times = int(feature_times_total.get(feat_name, 0) or 0)
            if feat_times <= 0 or st_count <= 0:
                continue
            drift = abs(st_count - feat_times) / max(feat_times, st_count, 1)
            if drift > 0.5:
                continue
            spin_type_to_feature[st] = feat_name
            feature_to_spin_type[feat_name] = st
            break

    # Pass 3 — tied-count ordinal assignment.
    for feat_times, feats in times_to_features.items():
        fresh_feats = sorted(f for f in feats if f not in feature_to_spin_type)
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

    # Pass 4 — ±2% tolerance.
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

    # Sanity gate — drop misfires onto zero-win STs when nonzero-win ST would match.
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

    # Pass 5 — settlement-SpinType re-binding (iter 5 M15 fix).
    if feature_win_total and spin_type_win:
        st_win_p5 = {int(k): float(v) for k, v in spin_type_win.items()}
        for feat_name, feat_times in feature_times_total.items():
            if feat_times <= 0 or feat_name in feature_to_spin_type:
                continue
            feat_win = float(feature_win_total.get(feat_name, 0) or 0)
            if feat_win <= 0:
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
    """Decide which FeatureWin key pairs with BuffCollectionMap.

    Ported verbatim from deleted player_impact_analyzer.py.
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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_report_from_chunks(
    machine_id: str,
    mode: int,
    *,
    chunk_dir: Path | str,
    output_dir: Path | str,
    manifests_root: Optional[Path | str] = None,
    bet: int = 1,
    run_id: Optional[str] = None,
) -> dict:
    """Generate a player_impact_summary.json from cached rawdata chunks.

    Parameters
    ----------
    machine_id:
        Machine identifier (e.g. "M15").  Must have a SpinType-native
        manifest under ``manifests_root`` or raises MachineNotRegistered.
    mode:
        RTP mode integer (e.g. 1).
    chunk_dir:
        Directory containing chunk_*.json files (rawdata/M15/mode_1/).
    output_dir:
        Directory to write player_impact_summary.json (and report.md).
        Created if absent.
    manifests_root:
        Root for configs/machine_manifests/.  Defaults to
        <repo_root>/configs/machine_manifests/.
    bet:
        Bet size in credits used during sampling (default 1).
    run_id:
        Run identifier stamped in the summary.  Auto-generated if None.

    Returns
    -------
    dict
        The summary dict (also written to output_dir/player_impact_summary.json).

    Raises
    ------
    MachineNotRegistered
        If no SpinType-native manifest is found for machine_id.
    SystemExit(1)
        For hard errors during the plugin emit loop (topo-sort failure,
        DECLARED_DEPS missing) — identical to the old PIA behavior.
    """
    # -- L1: deferred imports (no module-level side effects) --
    from fresh_slotlab.analyzer.machine_spec import (
        load_manifest as _ms_load_manifest,
        derive_analyses,
        is_confirmed,
    )
    from fresh_slotlab.analyzer.core.parser import (
        load_chunk_envelope,
        parse_chunk_response,
        ChunkIntegrityError,
    )
    from fresh_slotlab.analyzer.core.aggregator import (
        RETURN_BUCKET_ORDER,
        build_multiplier_bucket_rows,
        quantile_from_hist,
        classify_volatility,
        classify_experience_archetype,
        evaluate_guideline_comparison,
        _BankruptcyStreamAccumulator,
    )
    from fresh_slotlab.analyzer.core._utils import (
        _DEFAULT_BANKROLL_MULTIPLIERS,
        _DEFAULT_BANKRUPTCY_SESSION_SPINS,
        blank_like_symbol,
    )
    from fresh_slotlab.analyzer.core.writer import write_summary_json
    from fresh_slotlab.analyzer.versioning import (
        compute_analyzer_version,
        compute_effective_version_for_machine,
    )
    from fresh_slotlab.analyzer.feature_registry import (
        ALL_FEATURES,
        get_features_for_machine,
    )
    from fresh_slotlab.analyzer.parse_state import ParseState
    from fresh_slotlab.analyzer.pipeline_context import PipelineContext, MechanismRegistry
    from fresh_slotlab.analyzer.topo_sort import (
        topological_sort,
        PluginCyclicDependencyError,
        PluginMissingDependencyError,
        PluginDeclaredDepMissingError,
    )
    from fresh_slotlab.analyzer.manifest_loader import (
        load_manifest as _legacy_load_manifest,
        resolve_inheritance as _legacy_resolve_inheritance,
        resolve_per_mode as _legacy_resolve_per_mode,
    )
    from fresh_slotlab.analyzer.rtp_integrity import (
        check_rtp_integrity,
        Layer4Error,
    )
    from fresh_slotlab.machine_md5 import lookup_machine_md5
    from fresh_slotlab.analyzer.core.base_pipeline import DEFAULT_GUIDELINE_RULES_PATH
    from fresh_slotlab.analyzer.features.bankruptcy_simulation import build_bankruptcy_rows
    from fresh_slotlab.sampler import session_halfwidth_pp
    from fresh_slotlab.round_win import RoundWinRule, load_rules_for_machine

    # -- feature plugins: trigger register() calls --
    # Phase 4: replaced hardcoded import list with auto-discovery.
    # discover_features() globs features/*.py (excluding _base, __init__),
    # imports each in sorted order, idempotent (duplicate FEATURE_ID no-op).
    from fresh_slotlab.analyzer.feature_registry import discover_features
    discover_features()

    # -- resolve paths --
    chunk_dir = Path(chunk_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _manifests_root = Path(manifests_root) if manifests_root else _DEFAULT_MANIFESTS_ROOT

    # -- L3: load SpinType-native manifest (registered machines only) --
    manifest_path = _manifests_root / f"{machine_id}.json"
    if not manifest_path.exists():
        raise MachineNotRegistered(
            f"Machine '{machine_id}' is not registered: no manifest at {manifest_path}. "
            f"Add a SpinType-native manifest per docs/MACHINE_ONBOARDING.md to register it."
        )
    try:
        new_manifest = _ms_load_manifest(machine_id, _manifests_root)
    except ValueError as exc:
        raise MachineNotRegistered(
            f"Machine '{machine_id}' manifest is invalid: {exc}"
        ) from exc

    # Derive the analysis set from spin_types (SpinType-native model).
    analysis_set = derive_analyses(new_manifest)

    # Also load the legacy flat manifest for PipelineContext.manifest
    # (plugins that read ctx.manifest still expect the flat schema, which
    # carries mechanism_overrides / per-mode grid / etc.).  Best-effort:
    # falls back to empty dict if the flat manifest doesn't exist for
    # this machine (non-M15 registered machines don't need it).
    _legacy_manifest: dict[str, Any] = {}
    _flat_manifests_root = _REPO_ROOT / "slot_designer" / "configs" / "machine_manifests"
    try:
        _legacy_manifest = _legacy_load_manifest(machine_id, _flat_manifests_root)
        if _legacy_manifest.get("inherits_from"):
            _legacy_manifest = _legacy_resolve_inheritance(_legacy_manifest, _flat_manifests_root)
        _legacy_manifest = _legacy_resolve_per_mode(_legacy_manifest, mode)
    except (FileNotFoundError, KeyError, Exception):  # noqa: BLE001
        _legacy_manifest = {}

    # -- Round-win rules (ported from deleted PIA lines ~1031-1039) --
    # Per-machine extraction rules that correct phantom WinCredits
    # (e.g. M15 ST=14 selector-offer rounds) and WinAmount-only
    # settlement rounds (ST=15). Default: empty list → legacy
    # WinCredits lookup, byte-identical to pre-2026-04-27 behaviour.
    # Machine-id option chosen: (b) add "M15" to applies_to in config,
    # so bare machine_id "M15" (the new framework's identity) matches.
    # See coordinator review note in Phase 2a fix commit for rationale.
    _rules_config_path = _REPO_ROOT / "configs" / "machine_round_win_rules.json"
    _round_win_rules: list[RoundWinRule] = []
    try:
        if _rules_config_path.exists():
            _rules_config = json.loads(_rules_config_path.read_text(encoding="utf-8"))
            _round_win_rules = load_rules_for_machine(machine_id, _rules_config)
    except (OSError, json.JSONDecodeError):
        _round_win_rules = []

    # -- IDs & defaults --
    if run_id is None:
        run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    _bankruptcy_mults_tuple: tuple[int, ...] = _DEFAULT_BANKROLL_MULTIPLIERS
    _bankruptcy_session_spins: int = _DEFAULT_BANKRUPTCY_SESSION_SPINS
    target_halfwidth_pp = 0.5  # canonical default (matches old PIA default)

    # -- accumulator initialization (ported from old PIA main()) --
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
    bankruptcy_sim_totals: dict[int, dict[str, Any]] = {}
    bankruptcy_stream_acc = _BankruptcyStreamAccumulator(
        bet=bet,
        session_spins=_bankruptcy_session_spins,
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
    payline_winning_symbols: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    payline_winning_symbols_rln: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

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
    payout_id_by_spin_type_total: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    payout_id_col_set_total: dict[str, set[int]] = defaultdict(set)
    payout_id_symbol_combos_total: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    spin_type_spins: dict[int, int] = defaultdict(int)
    spin_type_next_counts: dict[int, Counter] = defaultdict(Counter)
    spin_type_remarks_sample: dict[int, list[str]] = defaultdict(list)
    spin_type_nudge_round_count: dict[int, int] = defaultdict(int)
    spin_type_bucket_spins: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    spin_type_bucket_bet: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    spin_type_bucket_win: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    session_bucket_spins_by_settlement_st: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    session_bucket_bet_by_settlement_st: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    session_bucket_win_by_settlement_st: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    chain_bucket_spins: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    chain_bucket_bet: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    chain_bucket_win: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    chain_chunk_summaries: dict[tuple, dict[str, float]] = defaultdict(
        lambda: {"count": 0, "win": 0.0, "bet": 0.0}
    )
    spin_type_bet: dict[int, float] = defaultdict(float)
    spin_type_paid_bet: dict[int, float] = defaultdict(float)
    spin_type_win: dict[int, float] = defaultdict(float)
    spin_type_wins: dict[int, int] = defaultdict(int)
    spin_type_paid_rounds: dict[int, int] = defaultdict(int)
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
    all_cycle_peaks: list[int] = []
    all_final_cc_values: list[int] = []
    total_completed_cycles = 0
    all_payline_symbol_joint: dict[str, dict[str, float]] = defaultdict(lambda: {"hits": 0, "win": 0.0})
    all_session_rtp_curves: list[list[dict[str, float]]] = []
    all_chain_ratio_sequences: list[list[int]] = []
    all_reel_position_hits: dict[str, int] = defaultdict(int)
    all_chains_by_feature: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"lengths": [], "max_ratios": [], "retrigger_events": [], "total_rounds": 0, "retrigger_rounds": 0}
    )
    lack_credit_spins = 0
    total_extra_fields_seen: dict[str, int] = defaultdict(int)
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

    _feature_accs: dict[str, dict] = {}
    chunks = 0
    achieved_halfwidth_pp: float | None = None

    # -- cache read phase (ported from PIA --from-cache path) --
    chunk_files = sorted(chunk_dir.glob("chunk_*.json"))
    if not chunk_files:
        raise ValueError(f"No chunk_*.json files found in {chunk_dir}")

    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    for cf in chunk_files:
        try:
            raw = load_chunk_envelope(cf)
        except ChunkIntegrityError as exc:
            raise ValueError(f"Chunk integrity error: {exc}") from exc

        chunk_bet_val = int(raw.get("_bet", bet) or bet)
        idx = int(raw.get("_chunk_index", chunks + 1))
        resp = raw.get("response")
        if resp is None:
            raise ValueError(f"{cf.name} missing 'response' key")

        rec = parse_chunk_response(
            resp, idx, chunk_bet_val,
            bankruptcy_session_spins=_bankruptcy_session_spins,
            bankruptcy_bankroll_mults=_bankruptcy_mults_tuple,
            round_win_rules=_round_win_rules if _round_win_rules else None,
        )
        if not rec.get("ok"):
            raise ValueError(f"{cf.name} parse failed: {rec.get('error')}")

        # -- merge block (ported verbatim from PIA for-cache merge) --
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
        for depth_key, s in (rec.get("bonus_depth_ratio_sum") or {}).items():
            bonus_depth_ratio_sum[str(depth_key)] += float(s)
        for depth_key, c in (rec.get("bonus_depth_ratio_count") or {}).items():
            bonus_depth_ratio_count[str(depth_key)] += int(c)
        for feat_key, feat_data in (rec.get("chains_by_feature") or {}).items():
            if not isinstance(feat_data, dict):
                continue
            tgt = all_chains_by_feature[str(feat_key)]
            for L in feat_data.get("lengths") or []:
                tgt["lengths"].append(int(L))
            for L in feat_data.get("max_ratios") or []:
                tgt["max_ratios"].append(int(L))
            for L in feat_data.get("retrigger_events") or []:
                tgt["retrigger_events"].append(int(L))
            tgt["total_rounds"] += int(feat_data.get("total_rounds", 0) or 0)
            tgt["retrigger_rounds"] += int(feat_data.get("retrigger_rounds", 0) or 0)

        for sym, cnt in (rec.get("symbol_counts") or {}).items():
            symbol_counts[str(sym)] += int(cnt)
        for ci_s, cmap in (rec.get("symbol_counts_by_col") or {}).items():
            ci = int(ci_s)
            if isinstance(cmap, dict):
                for sym, c in cmap.items():
                    symbol_counts_by_col[ci][str(sym)] += int(c)
        for ci_s, row_map in (rec.get("symbol_counts_by_col_by_row") or {}).items():
            ci = int(ci_s)
            if isinstance(row_map, dict):
                for row_s, sym_map in row_map.items():
                    ri = int(row_s)
                    if isinstance(sym_map, dict):
                        for sym, c in sym_map.items():
                            symbol_counts_by_col_by_row[ci][ri][str(sym)] += int(c)
        for ci_s, row_map in (rec.get("symbol_counts_by_col_by_spin_type") or {}).items():
            ci = int(ci_s)
            if isinstance(row_map, dict):
                for row_s, sym_map in row_map.items():
                    ri = int(row_s)
                    if isinstance(sym_map, dict):
                        for sym, c in sym_map.items():
                            symbol_counts_by_col_by_spin_type_total[ci][ri][str(sym)] += int(c)
        for ci_s, rows_set in (rec.get("payline_rows_per_col") or {}).items():
            ci = int(ci_s)
            for r in (rows_set if isinstance(rows_set, (list, set)) else []):
                payline_rows_per_col[ci].add(int(r))
        total_symbol_slots += int(rec.get("symbol_slots", 0) or 0)

        for ls, cnt in (rec.get("loss_streak_hist") or {}).items():
            loss_streak_hist[int(ls)] += int(cnt)
        for ws, cnt in (rec.get("win_streak_hist") or {}).items():
            win_streak_hist[int(ws)] += int(cnt)
        chunk_max_loss = int(rec.get("max_loss_streak", 0) or 0)
        if chunk_max_loss > max_loss_streak:
            max_loss_streak = chunk_max_loss
        chunk_max_win = int(rec.get("max_win_streak", 0) or 0)
        if chunk_max_win > max_win_streak:
            max_win_streak = chunk_max_win

        for bk, spins_b in (rec.get("multiplier_bucket_spins") or {}).items():
            multiplier_bucket_spins[str(bk)] += int(spins_b)
        for bk, bet_b in (rec.get("multiplier_bucket_bet") or {}).items():
            multiplier_bucket_bet[str(bk)] += float(bet_b)
        for bk, win_b in (rec.get("multiplier_bucket_win") or {}).items():
            multiplier_bucket_win[str(bk)] += float(win_b)

        for gid, c in (rec.get("payout_group_hits") or {}).items():
            payout_group_hits[int(gid)] += int(c)
        for gid, w in (rec.get("payout_group_win") or {}).items():
            payout_group_win[int(gid)] += float(w)
        for pid, c in (rec.get("payout_id_hits") or {}).items():
            payout_id_hits[str(pid)] += int(c)
        for pid, w in (rec.get("payout_id_win") or {}).items():
            payout_id_win[str(pid)] += float(w)
        for pid, st_map in (rec.get("payout_id_by_spin_type") or {}).items():
            if isinstance(st_map, dict):
                for st_s, c in st_map.items():
                    payout_id_by_spin_type_total[str(pid)][int(st_s)] += int(c)
        for pid, col_set in (rec.get("payout_id_col_set") or {}).items():
            for col in (col_set if isinstance(col_set, (list, set)) else []):
                payout_id_col_set_total[str(pid)].add(int(col))
        for pid, sc_map in (rec.get("payout_id_symbol_combos") or {}).items():
            if isinstance(sc_map, dict):
                for combo, c in sc_map.items():
                    payout_id_symbol_combos_total[str(pid)][str(combo)] += int(c)

        for st_s, c in (rec.get("spin_type_spins") or {}).items():
            spin_type_spins[int(st_s)] += int(c)
        for st_s, cntr in (rec.get("spin_type_next_counts") or {}).items():
            if isinstance(cntr, dict):
                for next_st, cnt in cntr.items():
                    spin_type_next_counts[int(st_s)][int(next_st)] += int(cnt)
        for st_s, remarks in (rec.get("spin_type_remarks_sample") or {}).items():
            if isinstance(remarks, list):
                spin_type_remarks_sample[int(st_s)].extend(remarks)
        for st_s, c in (rec.get("spin_type_nudge_round_count") or {}).items():
            spin_type_nudge_round_count[int(st_s)] += int(c)
        for st_s, bk_map in (rec.get("spin_type_bucket_spins") or {}).items():
            if isinstance(bk_map, dict):
                for bk, c in bk_map.items():
                    spin_type_bucket_spins[int(st_s)][str(bk)] += int(c)
        for st_s, bk_map in (rec.get("spin_type_bucket_bet") or {}).items():
            if isinstance(bk_map, dict):
                for bk, v in bk_map.items():
                    spin_type_bucket_bet[int(st_s)][str(bk)] += float(v)
        for st_s, bk_map in (rec.get("spin_type_bucket_win") or {}).items():
            if isinstance(bk_map, dict):
                for bk, v in bk_map.items():
                    spin_type_bucket_win[int(st_s)][str(bk)] += float(v)
        for st_s, bk_map in (rec.get("session_bucket_spins_by_settlement_st") or {}).items():
            if isinstance(bk_map, dict):
                for bk, c in bk_map.items():
                    session_bucket_spins_by_settlement_st[int(st_s)][str(bk)] += int(c)
        for st_s, bk_map in (rec.get("session_bucket_bet_by_settlement_st") or {}).items():
            if isinstance(bk_map, dict):
                for bk, v in bk_map.items():
                    session_bucket_bet_by_settlement_st[int(st_s)][str(bk)] += float(v)
        for st_s, bk_map in (rec.get("session_bucket_win_by_settlement_st") or {}).items():
            if isinstance(bk_map, dict):
                for bk, v in bk_map.items():
                    session_bucket_win_by_settlement_st[int(st_s)][str(bk)] += float(v)
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
        for _bkey, _bsrc, _bcast in (
            ("chain_bucket_spins", chain_bucket_spins, int),
            ("chain_bucket_bet", chain_bucket_bet, float),
            ("chain_bucket_win", chain_bucket_win, float),
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
                    _bsrc[key][str(bname)] += _bcast(val or 0)
        for st_s, v in (rec.get("spin_type_bet") or {}).items():
            spin_type_bet[int(st_s)] += float(v)
        for st_s, v in (rec.get("spin_type_paid_bet") or {}).items():
            spin_type_paid_bet[int(st_s)] += float(v)
        for st_s, v in (rec.get("spin_type_win") or {}).items():
            spin_type_win[int(st_s)] += float(v)
        for st_s, v in (rec.get("spin_type_wins") or {}).items():
            spin_type_wins[int(st_s)] += int(v)
        for st_s, v in (rec.get("spin_type_paid_rounds") or {}).items():
            spin_type_paid_rounds[int(st_s)] += int(v)
        for feat, pid_map in (rec.get("upstream_feature_tally") or {}).items():
            if isinstance(pid_map, dict):
                for pid, entry in pid_map.items():
                    if isinstance(entry, dict):
                        upstream_feature_tally[str(feat)][str(pid)]["win"] += float(entry.get("win", 0) or 0)
                        upstream_feature_tally[str(feat)][str(pid)]["times"] += int(entry.get("times", 0) or 0)
        upstream_total_win += float(rec.get("upstream_total_win", 0) or 0)
        upstream_robots_seen += int(rec.get("upstream_robots_seen", 0) or 0)
        collect_count_total += int(rec.get("collect_count_total", 0) or 0)
        acc_g = int(rec.get("acc_credits_max", 0) or 0)
        if acc_g > acc_credits_max_global:
            acc_credits_max_global = acc_g
        collect_robots_seen_total += int(rec.get("collect_robots_seen", 0) or 0)
        clamp_pending_paid_spins_total += int(rec.get("clamp_pending_paid_spins", 0) or 0)
        clamp_pending_robots_total += int(rec.get("clamp_pending_robots", 0) or 0)
        for peak in rec.get("cycle_peaks") or []:
            all_cycle_peaks.append(int(peak))
        for fcc in rec.get("final_cc_values") or []:
            all_final_cc_values.append(int(fcc))
        total_completed_cycles += int(rec.get("completed_cycles", 0) or 0)
        for k, v in (rec.get("payline_symbol_joint") or {}).items():
            if isinstance(v, dict):
                all_payline_symbol_joint[str(k)]["hits"] += float(v.get("hits", 0) or 0)
                all_payline_symbol_joint[str(k)]["win"] += float(v.get("win", 0) or 0)
        for curve in rec.get("session_rtp_curves") or []:
            if isinstance(curve, list):
                all_session_rtp_curves.append(curve)
        for seq in rec.get("chain_ratio_sequences") or []:
            if isinstance(seq, list):
                all_chain_ratio_sequences.append(seq)
        for pos, c in (rec.get("reel_position_hits") or {}).items():
            all_reel_position_hits[str(pos)] += int(c)

        total_paid_sessions += int(rec.get("paid_sessions", 0) or 0)
        total_bonus_spins += int(rec.get("bonus_spins", 0) or 0)
        total_session_wins += int(rec.get("session_wins", 0) or 0)
        total_session_loses += int(rec.get("session_loses", 0) or 0)
        total_session_profits += int(rec.get("session_profits", 0) or 0)
        total_session_breakevens += int(rec.get("session_breakevens", 0) or 0)
        total_session_big_win_x10 += int(rec.get("session_big_win_x10", 0) or 0)
        total_session_big_win_x20 += int(rec.get("session_big_win_x20", 0) or 0)
        total_session_big_win_x50 += int(rec.get("session_big_win_x50", 0) or 0)
        total_session_big_win_x100 += int(rec.get("session_big_win_x100", 0) or 0)
        total_session_ret_count += int(rec.get("session_ret_count", 0) or 0)
        total_session_ret_sum += float(rec.get("session_ret_sum", 0.0) or 0.0)
        total_session_ret_sq_sum += float(rec.get("session_ret_sq_sum", 0.0) or 0.0)
        total_session_max_return_x = max(
            total_session_max_return_x,
            float(rec.get("session_max_return_x", 0.0) or 0.0),
        )
        total_session_win_sum += float(rec.get("session_win_sum", 0.0) or 0.0)
        for bk, c in (rec.get("session_bucket_spins") or {}).items():
            session_bucket_spins[str(bk)] += int(c)
        for bk, v in (rec.get("session_bucket_bet") or {}).items():
            session_bucket_bet[str(bk)] += float(v)
        for bk, v in (rec.get("session_bucket_win") or {}).items():
            session_bucket_win[str(bk)] += float(v)
        for ls, cnt in (rec.get("session_loss_streak_hist") or {}).items():
            session_loss_streak_hist[int(ls)] += int(cnt)
        for ws, cnt in (rec.get("session_win_streak_hist") or {}).items():
            session_win_streak_hist[int(ws)] += int(cnt)
        chunk_sess_max_loss = int(rec.get("session_max_loss_streak", 0) or 0)
        if chunk_sess_max_loss > total_session_max_loss_streak:
            total_session_max_loss_streak = chunk_sess_max_loss
        chunk_sess_max_win = int(rec.get("session_max_win_streak", 0) or 0)
        if chunk_sess_max_win > total_session_max_win_streak:
            total_session_max_win_streak = chunk_sess_max_win

        for fld, cnt in (rec.get("extra_fields_seen") or {}).items():
            total_extra_fields_seen[str(fld)] += int(cnt)
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

        # Per-chunk extract() / reduce() for feature plugins
        parse_state = ParseState(
            chunk_dict=rec,
            machine_id=machine_id,
            mode=mode,
            manifest={},
        )
        for _feat in ALL_FEATURES:
            try:
                _this_acc = _feat.extract(parse_state, rec)
                _feature_accs[_feat.FEATURE_ID] = _feat.reduce(
                    _feature_accs.get(_feat.FEATURE_ID, {}),
                    _this_acc,
                )
            except Exception as _exc:  # noqa: BLE001
                import sys as _sys
                print(
                    f"WARNING: feature '{_feat.FEATURE_ID}' extract()/reduce() "
                    f"failed on chunk {rec.get('index', '?')}: {_exc}",
                    file=_sys.stderr,
                )
                _feature_accs.setdefault(f"_extract_error_{_feat.FEATURE_ID}", []).append(str(_exc))

        # Bankruptcy streaming accumulator
        try:
            _breps = rec.get("bankruptcy_reps")
            if _breps:
                bankruptcy_stream_acc.feed_reps(_breps)
        except Exception:  # noqa: BLE001
            pass
        # Also merge old-style per-tier dict
        for bk_tier, tier_data in (rec.get("bankruptcy_sim") or {}).items():
            try:
                t = int(bk_tier)
                if t not in bankruptcy_sim_totals:
                    bankruptcy_sim_totals[t] = {"spin_counts": [], "win_totals": [], "reps": 0}
                for k, v in (tier_data or {}).items():
                    if k in ("spin_counts", "win_totals") and isinstance(v, list):
                        bankruptcy_sim_totals[t].setdefault(k, []).extend(v)
                    elif k == "reps":
                        bankruptcy_sim_totals[t]["reps"] = bankruptcy_sim_totals[t].get("reps", 0) + int(v or 0)
            except (TypeError, ValueError):
                pass

        # Update chunk-level CI
        if len(chunk_rtps_pct) >= 2:
            try:
                _ci = (
                    statistics.stdev(chunk_rtps_pct)
                    / math.sqrt(len(chunk_rtps_pct))
                )
                if math.isfinite(_ci):
                    achieved_halfwidth_pp = _ci
            except statistics.StatisticsError:
                pass

    # End of chunk loop

    finished_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # -- Finalization block (ported from PIA post-loop) --

    session_bet_sum = sum(float(v) for v in session_bucket_bet.values()) or total_bet
    session_win_sum_agg = sum(float(v) for v in session_bucket_win.values()) or total_win
    effective_bet_for_rtp = session_bet_sum if total_paid_sessions > 0 else total_bet

    # RTP numerator: prefer server TotalWin when divergence > 1%.
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

    # Session-level CI override
    session_level_halfwidth_pp = session_halfwidth_pp(
        total_session_ret_count,
        total_session_ret_sum,
        total_session_ret_sq_sum,
    )
    chunk_level_halfwidth_pp = achieved_halfwidth_pp
    if session_level_halfwidth_pp is not None:
        achieved_halfwidth_pp = session_level_halfwidth_pp

    ci_interval = None
    if achieved_halfwidth_pp is not None:
        ci_interval = [rtp_point_pct - achieved_halfwidth_pp, rtp_point_pct + achieved_halfwidth_pp]

    # Session-level derived metrics
    effective_session_count = total_paid_sessions if total_paid_sessions > 0 else total_spins
    avg_return_x = (
        (total_session_ret_sum / total_session_ret_count)
        if total_session_ret_count > 0 else 0.0
    )
    if total_session_ret_count > 1:
        variance = (
            total_session_ret_sq_sum
            - (total_session_ret_sum * total_session_ret_sum / total_session_ret_count)
        ) / (total_session_ret_count - 1)
        std_return_x = math.sqrt(max(variance, 0.0))
    else:
        std_return_x = 0.0
    if total_paid_sessions > 0:
        max_observed_return_x = total_session_max_return_x

    hit_rate = (total_session_wins / effective_session_count) if effective_session_count > 0 else 0.0
    zero_win_rate = (total_session_loses / effective_session_count) if effective_session_count > 0 else 0.0
    profit_spin_rate = (total_session_profits / effective_session_count) if effective_session_count > 0 else 0.0
    breakeven_or_more_rate = (total_session_breakevens / effective_session_count) if effective_session_count > 0 else 0.0
    big_win_x10_rate = (total_session_big_win_x10 / effective_session_count) if effective_session_count > 0 else 0.0
    big_win_x20_rate = (total_session_big_win_x20 / effective_session_count) if effective_session_count > 0 else 0.0
    big_win_x50_rate = (total_session_big_win_x50 / effective_session_count) if effective_session_count > 0 else 0.0
    big_win_x100_rate = (total_session_big_win_x100 / effective_session_count) if effective_session_count > 0 else 0.0
    avg_win_when_hit_x = (
        (total_session_win_sum / total_session_wins) / bet
        if total_session_wins > 0 and bet > 0 else 0.0
    )

    # Multiplier bucket rows
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

    # Payline rows
    from fresh_slotlab.analyzer.core.parser import _BASELINE_ROUND_FIELDS
    payline_rows: list[dict[str, Any]] = []
    for lid, hits_pl in sorted(payline_hits.items(), key=lambda kv: kv[1], reverse=True):
        wins_pl = float(payline_win_approx.get(lid, 0.0))
        rln_syms = payline_winning_symbols_rln.get(lid) or {}
        heur_syms = payline_winning_symbols.get(lid) or {}
        if rln_syms:
            top_syms = sorted(rln_syms.items(), key=lambda kv: -kv[1])[:5]
            top_symbols_source = "rln"
        elif heur_syms:
            top_syms = sorted(heur_syms.items(), key=lambda kv: -kv[1])[:5]
            top_symbols_source = "heuristic"
        else:
            top_syms = []
            top_symbols_source = "none"
        payline_rows.append({
            "payline_id": str(lid),
            "hit_count": int(hits_pl),
            "hit_rate": (hits_pl / total_spins) if total_spins > 0 else 0.0,
            "approx_win_credits": wins_pl,
            "approx_rtp_contribution_pp": (
                (wins_pl / total_bet) * 100.0 if total_bet > 0 else 0.0
            ),
            "top_symbols": [{"symbol": s, "count": c} for s, c in top_syms],
            "top_symbols_source": top_symbols_source,
        })

    # Payout group rows
    _payout_group_keys_nonzero = {k for k in payout_group_hits if int(k) != 0}
    if not payout_group_hits:
        payout_groups_status = "absent_field"
    elif not _payout_group_keys_nonzero:
        payout_groups_status = "all_zeros_filtered"
    else:
        payout_groups_status = "populated"
    payout_group_rows: list[dict[str, Any]] = []
    if payout_groups_status == "populated":
        for gid, hits_g in sorted(payout_group_hits.items(), key=lambda kv: kv[1], reverse=True):
            wins_g = float(payout_group_win.get(gid, 0.0))
            win_spins_in_group = hits_g if gid != 0 else 0
            payout_group_rows.append({
                "group_id": int(gid),
                "hit_count": int(hits_g),
                "hit_rate": (hits_g / total_spins) if total_spins > 0 else 0.0,
                "total_win": wins_g,
                "avg_win_when_hit_x": (
                    (wins_g / win_spins_in_group) / bet
                    if win_spins_in_group > 0 and bet > 0 else 0.0
                ),
                "rtp_contribution_pp": (
                    (wins_g / total_bet) * 100.0 if total_bet > 0 else 0.0
                ),
            })

    # SpinType breakdown
    spin_type_rows: list[dict[str, Any]] = []
    for st, spins_st in sorted(spin_type_spins.items(), key=lambda kv: -kv[1]):
        bet_face = float(spin_type_bet.get(st, 0.0))
        bet_paid = float(spin_type_paid_bet.get(st, 0.0))
        win_st = float(spin_type_win.get(st, 0.0))
        win_rounds_st = int(spin_type_wins.get(st, 0))
        paid_rounds_st = int(spin_type_paid_rounds.get(st, 0))
        spins_int = int(spins_st)
        if paid_rounds_st == 0:
            behavior = "free"
        elif paid_rounds_st == spins_int:
            behavior = "paid"
        else:
            behavior = "mixed"
        rtp_pct_st: float | None = (
            (win_st / bet_paid) * 100.0 if bet_paid > 0 else None
        )
        spin_type_rows.append({
            "spin_type": int(st),
            "spins": spins_int,
            "share_pct": (spins_st / total_spins) * 100.0 if total_spins > 0 else 0.0,
            "win_rounds": win_rounds_st,
            "paid_rounds": paid_rounds_st,
            "hit_rate": (win_rounds_st / spins_st) if spins_st > 0 else 0.0,
            "total_bet": bet_face,
            "total_paid_bet": bet_paid,
            "total_win": win_st,
            "rtp_pct": rtp_pct_st,
            "rtp_contribution_pp": (win_st / total_bet) * 100.0 if total_bet > 0 else 0.0,
            "behavior_name": behavior,
            "rare": spins_int < 5,
        })
    spin_type_coverage = len(spin_type_spins)

    # Payout ID rows
    _st_behavior: dict[int, str] = {int(row["spin_type"]): row["behavior_name"] for row in spin_type_rows}
    payout_id_rows: list[dict[str, Any]] = []
    for pid, wins_pid in sorted(payout_id_win.items(), key=lambda kv: kv[1], reverse=True):
        hits_pid = int(payout_id_hits.get(pid, 0))
        wins_f = float(wins_pid)
        st_hits = payout_id_by_spin_type_total.get(str(pid)) or {}
        total_st_hits = sum(int(c) for c in st_hits.values()) if st_hits else 0
        dominant_st: int | None = None
        dominant_share = 0.0
        if total_st_hits > 0:
            dominant_st = max(st_hits.items(), key=lambda kv: (int(kv[1]), -int(kv[0])))[0]
            dominant_share = float(st_hits[dominant_st]) / total_st_hits
        category: str | None = None
        if dominant_st is not None:
            st_behavior_val = _st_behavior.get(int(dominant_st), "mixed")
            if st_behavior_val == "paid":
                category = "paid" if dominant_share >= 0.8 else "mixed"
            elif st_behavior_val == "free":
                category = "bonus" if dominant_share >= 0.8 else "mixed"
            else:
                category = "mixed"
        _c4_pid_s = str(pid)
        _c4_col_set = payout_id_col_set_total.get(_c4_pid_s)
        _c4_covered_columns: list[int] = sorted(_c4_col_set) if _c4_col_set else []
        _c4_sc_map = payout_id_symbol_combos_total.get(_c4_pid_s) or {}
        if _c4_sc_map:
            _c4_dominant = max(_c4_sc_map.items(), key=lambda kv: kv[1])[0]
            _c4_all_syms: set[str] = set()
            for _c4_combo_str in _c4_sc_map:
                for _c4_sym in _c4_combo_str.split("|"):
                    if _c4_sym:
                        _c4_all_syms.add(_c4_sym)
            _c4_symbol_combo: dict[str, Any] = {"dominant": _c4_dominant, "distinct_symbols": sorted(_c4_all_syms)}
        else:
            _c4_symbol_combo = {"dominant": None, "distinct_symbols": []}
        payout_id_rows.append({
            "payout_id": str(pid),
            "hit_count": hits_pid,
            "hit_rate": (hits_pid / total_spins) if total_spins > 0 else 0.0,
            "total_win": wins_f,
            "avg_win_when_hit": (wins_f / hits_pid) if hits_pid > 0 else 0.0,
            "rtp_contribution_pp": (
                (wins_f / effective_bet_for_rtp) * 100.0 if effective_bet_for_rtp > 0 else 0.0
            ),
            "spin_type_category": category,
            "dominant_spin_type": int(dominant_st) if dominant_st is not None else None,
            "spin_type_breakdown": [
                {"spin_type": int(k), "count": int(v)}
                for k, v in sorted(st_hits.items(), key=lambda kv: -int(kv[1]))
            ],
            "covered_columns": _c4_covered_columns,
            "symbol_combo": _c4_symbol_combo,
        })

    # Feature cross-reference enrichment on spin_type_rows
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
    if spin_type_to_feature:
        _feat_rtp_pp_lookup: dict[str, float | None] = {}
        _feat_fire_rate_lookup: dict[str, float | None] = {}
        _feat_trigger_only_lookup: dict[str, bool | None] = {}
        for _fname, _ftimes in feature_times_total.items():
            _fwin = feature_win_total.get(_fname, 0.0)
            _feat_rtp_pp_lookup[_fname] = (
                (_fwin / effective_bet_for_rtp) * 100.0
                if effective_bet_for_rtp > 0 and _ftimes > 0 else None
            )
            _feat_fire_rate_lookup[_fname] = (
                _ftimes / total_spins if total_spins > 0 and _ftimes > 0 else None
            )
            _feat_trigger_only_lookup[_fname] = (
                bool(_ftimes > 0 and _fwin == 0.0) if _ftimes > 0 else None
            )
        for _stb_row in spin_type_rows:
            _st_int_val = int(_stb_row["spin_type"])
            _mapped_feat = spin_type_to_feature.get(_st_int_val)
            _stb_row["feature_name"] = _mapped_feat
            _stb_row["feature_rtp_pp"] = _feat_rtp_pp_lookup.get(_mapped_feat) if _mapped_feat else None
            _stb_row["feature_fire_rate"] = _feat_fire_rate_lookup.get(_mapped_feat) if _mapped_feat else None
            _stb_row["feature_trigger_only"] = _feat_trigger_only_lookup.get(_mapped_feat) if _mapped_feat else None
    else:
        for _stb_row in spin_type_rows:
            _stb_row["feature_name"] = None
            _stb_row["feature_rtp_pp"] = None
            _stb_row["feature_fire_rate"] = None
            _stb_row["feature_trigger_only"] = None

    # Wild-nudge ST set
    _wild_nudge_st_set: set[int] = set()
    for _st_key, _nudge_n in (spin_type_nudge_round_count or {}).items():
        try:
            _st_int = int(_st_key)
        except (TypeError, ValueError):
            continue
        _st_total = int(spin_type_spins.get(_st_int, 0) or 0)
        if _st_total > 0 and (_nudge_n / _st_total) >= 0.9:
            _wild_nudge_st_set.add(_st_int)

    # BCM bonus feature resolution
    _bcm_bonus_feature, _bcm_bonus_source = _resolve_bonus_feature(
        machine_id, mode,
        upstream_feature_tally, _load_bcm_pairings(),
        feature_to_spin_type=feature_to_spin_type,
        wild_nudge_spin_types=_wild_nudge_st_set,
    )

    # Symbol rows
    symbol_rows = [
        {"symbol": sym, "count": cnt, "rate": cnt / total_symbol_slots if total_symbol_slots > 0 else 0.0}
        for sym, cnt in sorted(symbol_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]
    symbol_by_col_rows: dict[str, list] = {}
    for ci_k, cmap in symbol_counts_by_col.items():
        total_col = sum(cmap.values())
        symbol_by_col_rows[str(ci_k)] = [
            {"symbol": sym, "count": cnt, "rate": cnt / total_col if total_col > 0 else 0.0}
            for sym, cnt in sorted(cmap.items(), key=lambda kv: kv[1], reverse=True)
        ]
    payline_row_mask_per_col = {str(ci_k): sorted(rows) for ci_k, rows in payline_rows_per_col.items()}
    symbol_by_col_rows_payline: dict[str, list] = {}
    for ci_k, _row_map in symbol_counts_by_col_by_row.items():
        _payline_mask = payline_rows_per_col.get(ci_k) or {1}
        _merged_payline: dict[str, int] = defaultdict(int)
        for _row_idx, _sym_counts in _row_map.items():
            if _row_idx in _payline_mask:
                for _sym, _c in _sym_counts.items():
                    _merged_payline[_sym] += _c
        _total_col_payline = sum(_merged_payline.values())
        symbol_by_col_rows_payline[str(ci_k)] = [
            {"symbol": s, "count": c, "rate": c / _total_col_payline if _total_col_payline > 0 else 0.0}
            for s, c in sorted(_merged_payline.items(), key=lambda kv: kv[1], reverse=True)
        ]

    # Quality metrics
    # Use the stream accumulator if it has data (correctly pools across chunks),
    # fall back to the per-chunk dict accumulator (legacy path) otherwise.
    _bsim_final = (
        bankruptcy_stream_acc.finalize()
        if bankruptcy_stream_acc.has_data
        else bankruptcy_sim_totals
    )
    bankruptcy_rows_list: list[dict[str, Any]] = build_bankruptcy_rows(
        _bsim_final,
        _bankruptcy_mults_tuple,
        bet,
        _bankruptcy_session_spins,
    )
    ci_met = achieved_halfwidth_pp is not None and achieved_halfwidth_pp <= target_halfwidth_pp
    sample_size_met = total_spins >= 2_000_000
    buckets_complete = len(multiplier_bucket_rows) == len(RETURN_BUCKET_ORDER)
    bankruptcy_ladder_met = sum(1 for row in bankruptcy_rows_list if "error" not in row) >= 3
    quality_label = (
        "REPORT_GRADE"
        if (ci_met and sample_size_met and buckets_complete and bankruptcy_ladder_met)
        else "EXPLORATORY"
    )

    recovery_gap = hit_rate - profit_spin_rate
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
    tail_dependency_ge10x = safe_div(tail_rtp_contribution_pp_ge10x, rtp_point_pct)
    tail_dependency_ge20x = safe_div(tail_rtp_contribution_pp_ge20x, rtp_point_pct)
    tail_dependency_ge50x = safe_div(tail_rtp_contribution_pp_ge50x, rtp_point_pct)
    tail_dependency_ge100x = safe_div(tail_rtp_contribution_pp_ge100x, rtp_point_pct)
    tail_dependency = tail_dependency_ge10x

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
        if payline_rows else 0.0
    )
    payline_top3_share = (
        safe_div(sum(float(row["approx_rtp_contribution_pp"]) for row in payline_rows[:3]), payline_total_pp)
        if payline_rows else 0.0
    )
    blank_like_total = sum(cnt for sym, cnt in symbol_counts.items() if blank_like_symbol(sym))
    blank_like_rate = safe_div(float(blank_like_total), float(total_symbol_slots))
    blank_like_rate_by_col: dict[str, float] = {}
    for ci_k, cmap in symbol_counts_by_col.items():
        total_col = sum(cmap.values())
        blank_col = sum(c for sym, c in cmap.items() if blank_like_symbol(sym))
        blank_like_rate_by_col[str(ci_k)] = safe_div(float(blank_col), float(total_col))
    blank_like_col_spread = (
        max(blank_like_rate_by_col.values()) - min(blank_like_rate_by_col.values())
        if blank_like_rate_by_col else 0.0
    )
    symbol_distribution_skew = blank_like_col_spread > 0.05

    bankruptcy_by_mult = {
        int(row["bankroll_multiplier"]): row
        for row in bankruptcy_rows_list if "error" not in row
    }
    x100_br = float(bankruptcy_by_mult.get(100, {}).get("bankruptcy_rate", 0.0))
    x200_br = float(bankruptcy_by_mult.get(200, {}).get("bankruptcy_rate", 0.0))
    x500_br = float(bankruptcy_by_mult.get(500, {}).get("bankruptcy_rate", 0.0))

    # Alerts
    alerts: list[dict[str, str]] = []
    if not ci_met:
        alerts.append({"code": "A1_CI_NOT_REACHED", "severity": "high", "message": "CI half-width target not reached."})
    if zero_win_rate > 0.80 and profit_spin_rate < 0.10:
        alerts.append({"code": "A2_DRY_AND_LOW_PROFIT", "severity": "high", "message": "High dead-spin rate with low profit-spin rate."})
    if loss_streak_p95 >= 15:
        alerts.append({"code": "A3_LONG_LOSS_STREAK", "severity": "medium", "message": "Loss streak p95 is high."})
    if tail_dependency >= 0.45:
        alerts.append({"code": "A4_HIGH_TAIL_DEPENDENCY", "severity": "medium", "message": "RTP depends heavily on >=10x tail outcomes."})
    if x200_br >= 0.10:
        alerts.append({"code": "A5_X200_BANKRUPTCY_HIGH", "severity": "high", "message": "x200 bankroll bankruptcy rate is above 10%."})
    if payline_top1_share > 0.20 or payline_top3_share > 0.55:
        alerts.append({"code": "A6_PAYLINE_CONCENTRATION", "severity": "medium", "message": "Payline RTP contribution is concentrated."})
    if symbol_distribution_skew:
        alerts.append({"code": "A7_SYMBOL_SKEW", "severity": "medium", "message": "Blank-like symbol distribution spread across columns exceeds 5pp."})

    action_recommendations: list[str] = []
    if zero_win_rate > 0.80 or loss_streak_p95 >= 15:
        action_recommendations.append("Increase low return bucket (gt0_lt1) to reduce dry feel.")
    if tail_dependency >= 0.45:
        action_recommendations.append("Reduce >=10x tail RTP share slightly and reallocate to ge1_lt5.")
    if x200_br >= 0.10:
        action_recommendations.append("Improve session survivability at x200 bankroll by raising mid-tier payout continuity.")
    if not action_recommendations:
        action_recommendations.append("Profile is within baseline guardrails; run targeted A/B tests on mid buckets for finer tuning.")

    # Effective analyzer version (best-effort)
    _summary_analyzer_version = compute_analyzer_version()
    _summary_effective_analyzer_version = ""
    _effective_version_error: str | None = None
    try:
        _summary_effective_analyzer_version = compute_effective_version_for_machine(machine_id, mode=mode)
    except Exception as _exc:  # noqa: BLE001
        _effective_version_error = f"{type(_exc).__name__}: {_exc}"

    # MD5 fingerprints
    _summary_config_md5, _summary_code_md5 = lookup_machine_md5(machine_id)

    # -- Build summary dict --
    summary: dict[str, Any] = {
        "report_id": f"impact_{machine_id}_mode{mode}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "run_id": run_id,
        "machine": machine_id,
        "mode": mode,
        "config_md5": _summary_config_md5,
        "code_md5": _summary_code_md5,
        "analyzer_version": _summary_analyzer_version,
        "effective_analyzer_version": _summary_effective_analyzer_version,
        "effective_analyzer_version_error": _effective_version_error,
        "output_all_robots_result": True,
        "sampling": {
            "target_halfwidth_pp": target_halfwidth_pp,
            "achieved_halfwidth_pp": achieved_halfwidth_pp,
            "chunk_level_halfwidth_pp": chunk_level_halfwidth_pp,
            "session_level_halfwidth_pp": session_level_halfwidth_pp,
            "chunk_spin_times": int(rec.get("spins", 0)) if chunks > 0 else 0,
            "chunk_robot_count": 0,
            "batch_concurrency": 1,
            "bet": int(bet),
            "chunks": chunks,
            "total_spins": total_spins,
            "paid_spins": total_paid_sessions,
            "bonus_spins": total_bonus_spins,
            "stop_reason": "from_cache_complete",
            "duration_seconds": 0.0,
            "started_at": started_at,
            "finished_at": finished_at,
        },
        "rtp": {
            "point_pct": rtp_point_pct,
            "ci95_interval_pct": ci_interval,
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
                "loss_streak_p50": loss_streak_p50,
                "loss_streak_p90": loss_streak_p90,
                "loss_streak_p95": loss_streak_p95,
                "loss_streak_max": max_loss_final,
                "win_streak_p50": win_streak_p50,
                "win_streak_p90": win_streak_p90,
                "win_streak_p95": win_streak_p95,
                "win_streak_max": max_win_final,
            },
            "paylines_top20": list(payline_rows),
            "payout_groups_top20": list(payout_group_rows),
            "payout_groups_status": payout_groups_status,
            "payout_ids_top20": list(payout_id_rows),
            "spin_type_breakdown": spin_type_rows,
            "spin_type_coverage": spin_type_coverage,
            "field_discovery": {
                "extra_fields": [
                    {"field": f, "occurrences": c}
                    for f, c in sorted(total_extra_fields_seen.items(), key=lambda kv: -kv[1])
                ],
                "extra_field_count": len(total_extra_fields_seen),
                "baseline_field_count": len(_BASELINE_ROUND_FIELDS),
            },
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
            ),
            "session_rtp_curves": all_session_rtp_curves[:50],
            "chain_ratio_sequences": all_chain_ratio_sequences[:50],
            "reel_position_top20": sorted(
                [{"position": pos, "hits": cnt} for pos, cnt in all_reel_position_hits.items()],
                key=lambda x: -x["hits"],
            ),
            "symbols_top20": list(symbol_rows),
            "symbols_by_column_top10": {k: list(v) for k, v in symbol_by_col_rows.items()},
            "symbols_by_column_top10_payline": {k: list(v) for k, v in symbol_by_col_rows_payline.items()},
            "payline_rows_per_col": payline_row_mask_per_col,
        },
        "upstream_analysis": {
            "server_total_win": upstream_total_win,
            "our_total_win": total_win,
            "delta": total_win - upstream_total_win,
            "delta_pct": (
                ((total_win - upstream_total_win) / upstream_total_win) * 100.0
                if upstream_total_win > 0 else None
            ),
            "matches": (
                abs(total_win - upstream_total_win) < max(1.0, upstream_total_win * 1e-6)
                if upstream_robots_seen > 0 else None
            ),
            "server_robots_seen": upstream_robots_seen,
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
                "tail_dependency": tail_dependency,
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
                "payline_top1_concentrated": payline_top1_share > 0.20,
                "payline_top3_concentrated": payline_top3_share > 0.55,
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
                "data_confidence": f"CI half-width={achieved_halfwidth_pp}, target<={target_halfwidth_pp}, spins={total_spins}, quality={quality_label}.",
                "player_feel": f"{experience_archetype} feel with {volatility_class} volatility: zero_win_rate={zero_win_rate:.4f}, loss_streak_p95={loss_streak_p95}.",
                "rtp_structure": f">=10x tail contributes {tail_rtp_contribution_pp_ge10x:.4f}pp RTP (dependency={tail_dependency:.4f}).",
                "session_risk": f"Bankruptcy ladder: x100={x100_br:.4f}, x200={x200_br:.4f}, x500={x500_br:.4f}.",
                "design_action": action_recommendations[0],
            },
        },
    }

    # guideline_comparison
    summary["guideline_comparison"] = evaluate_guideline_comparison(summary, DEFAULT_GUIDELINE_RULES_PATH)

    # -- Stash keys for Pattern B plugins --
    summary["_upstream_feature_breakdown_data"] = {
        "feature_to_spin_type": feature_to_spin_type,
        "spin_type_to_feature": spin_type_to_feature,
        "ambiguous_mapped": ambiguous_mapped,
        "bcm_bonus_feature": _bcm_bonus_feature,
        "bcm_bonus_source": _bcm_bonus_source,
        "upstream_feature_tally": upstream_feature_tally,
        "spin_type_next_counts": spin_type_next_counts,
        "chain_chunk_summaries": chain_chunk_summaries,
        "chain_bucket_spins": chain_bucket_spins,
        "chain_bucket_bet": chain_bucket_bet,
        "chain_bucket_win": chain_bucket_win,
        "spin_type_bucket_spins": spin_type_bucket_spins,
        "spin_type_bucket_bet": spin_type_bucket_bet,
        "spin_type_bucket_win": spin_type_bucket_win,
        "session_bucket_spins_by_settlement_st": session_bucket_spins_by_settlement_st,
        "session_bucket_bet_by_settlement_st": session_bucket_bet_by_settlement_st,
        "session_bucket_win_by_settlement_st": session_bucket_win_by_settlement_st,
        "spin_type_spins": spin_type_spins,
        "spin_type_nudge_round_count": spin_type_nudge_round_count,
        "total_spins": total_spins,
        "effective_bet_for_rtp": effective_bet_for_rtp,
        "upstream_total_win": upstream_total_win,
    }

    _cm_bonus_feat, _cm_bonus_src = _resolve_bonus_feature(
        machine_id, mode, upstream_feature_tally, _load_bcm_pairings(),
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

    summary["_bonus_chain_dynamics_data"] = {
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
            feat for feat, afb in all_chains_by_feature.items() if afb.get("lengths")
        ),
        "scatter_feature_chain_counts": {
            feat: len(afb["lengths"])
            for feat, afb in all_chains_by_feature.items()
            if afb.get("lengths")
        },
    }

    summary["_multiplier_profile_data"] = {
        "multiplier_bucket_rows": multiplier_bucket_rows,
        "tail_spins_ge10": tail_spins_ge10,
        "mb_total_spins": mb_total_spins,
        "tail_rtp_contribution_pp_ge10x": tail_rtp_contribution_pp_ge10x,
        "tail_win_share_ge10x": tail_win_share_ge10x,
    }

    summary["_reel_marginal_by_spin_type_data"] = {
        "symbol_counts_by_col_by_spin_type_total": symbol_counts_by_col_by_spin_type_total,
    }

    summary["_bankruptcy_rows"] = bankruptcy_rows_list
    summary["_bankruptcy_sim_session_spins"] = _bankruptcy_session_spins

    # -- Phase D: topo-sort + emit loop --

    # Helper to strip internal stash keys before writing
    def _strip_internal_stash_keys(s: dict) -> None:
        for _k in list(s.keys()):
            if _k.startswith("_"):
                s.pop(_k, None)

    def _safe_write_summary_json(s: dict, out_dir: Path) -> None:
        _strip_internal_stash_keys(s)
        try:
            write_summary_json(s, out_dir)
        except Exception as _write_exc:
            import sys as _sys
            print(f"ERROR: failed to write summary JSON on error path: {_write_exc}", file=_sys.stderr)

    # Build MechanismRegistry
    _c1_cycle_median: int | None = (
        int(sorted(all_cycle_peaks)[len(all_cycle_peaks) // 2])
        if all_cycle_peaks else None
    )
    _c1_robots_with_pending_cycle: int = (
        sum(1 for fcc in all_final_cc_values if _c1_cycle_median is not None and fcc < _c1_cycle_median)
    )
    _c4_pbs_acc = _feature_accs.get("payouts_by_spin_type") or {}
    _c4_pid_has_regular_line: dict[str, bool] = _c4_pbs_acc.get("pid_has_regular_line") or {}
    _mechanism_registry = MechanismRegistry.build(
        manifest=_legacy_manifest,
        payout_id_win=dict(payout_id_win),
        payout_id_hits=dict(payout_id_hits),
        jackpot_ids_seen=total_jackpot_ids_seen,
        bonus_chain_lengths=bonus_chain_lengths,
        total_freespin_chain_spins=total_freespin_chain_spins,
        payout_group_win=dict(payout_group_win),
        pid_has_regular_line=_c4_pid_has_regular_line,
    )
    summary["_mechanism_registry"] = _mechanism_registry

    # Surface unknown mechanism_overrides keys
    for _b4_key in _mechanism_registry.unknown_override_keys:
        if "feature_errors" not in summary:
            summary["feature_errors"] = {}
        summary["feature_errors"][f"mechanism_registry_unknown_override_{_b4_key}"] = {
            "type": "UnrecognizedMechanismOverrideKey",
            "key": _b4_key,
            "machine_id": machine_id,
            "detail": (
                f"Manifest mechanism_overrides contains unrecognized key '{_b4_key}'. "
                f"This override was silently ignored."
            ),
        }

    # Build PipelineContext
    _c1_ctx = PipelineContext(
        effective_bet_for_rtp=effective_bet_for_rtp,
        total_spins=total_spins,
        total_paid_sessions=total_paid_sessions,
        total_paid_spins=int(sum(spin_type_paid_rounds.values())),
        clamp_pending_robots_total=clamp_pending_robots_total,
        robots_with_pending_cycle=_c1_robots_with_pending_cycle,
        mechanism_registry=_mechanism_registry,
        manifest=_legacy_manifest,
        machine_spec_manifest=new_manifest,  # Phase 3: SpinType-native manifest
    )

    # Select features based on derived analysis_set (the SpinType-native model)
    # Build a synthetic manifest that get_features_for_machine can read
    _synthetic_manifest = {"analyzer_features": analysis_set}
    _machine_features = get_features_for_machine(machine_id, manifest=_synthetic_manifest)

    # Topo-sort
    try:
        _sorted_features = topological_sort(_machine_features)
    except (PluginCyclicDependencyError, PluginMissingDependencyError) as _topo_exc:
        summary["analyzer_init_error"] = {
            "error_type": type(_topo_exc).__name__,
            "message": str(_topo_exc),
            "plugin_dep_graph": {f.FEATURE_ID: list(f.REQUIRES) for f in _machine_features},
            "affected_plugin": None,
            "region": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        import sys as _sys
        print(f"ERROR: analyzer plugin topo-sort failed: {type(_topo_exc).__name__} — {_topo_exc}", file=_sys.stderr)
        _safe_write_summary_json(summary, output_dir)
        raise SystemExit(1) from _topo_exc

    # Emit loop
    for _feature in _sorted_features:
        # DECLARED_DEPS check
        for _dep_key in _feature.DECLARED_DEPS:
            if _dep_key not in summary:
                _dep_exc = PluginDeclaredDepMissingError(
                    plugin=_feature.FEATURE_ID,
                    missing_dep_key=_dep_key,
                )
                summary["analyzer_init_error"] = {
                    "error_type": type(_dep_exc).__name__,
                    "message": str(_dep_exc),
                    "plugin_dep_graph": {f.FEATURE_ID: list(f.REQUIRES) for f in _machine_features},
                    "affected_plugin": _feature.FEATURE_ID,
                    "region": 2,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                import sys as _sys
                print(f"ERROR: analyzer DECLARED_DEPS check failed for '{_feature.FEATURE_ID}': key '{_dep_key}' absent", file=_sys.stderr)
                _safe_write_summary_json(summary, output_dir)
                raise SystemExit(1) from _dep_exc
        try:
            _feature.emit(_feature_accs.get(_feature.FEATURE_ID, {}), summary, _c1_ctx)
        except Exception as _emit_exc:  # noqa: BLE001
            import sys as _sys
            print(f"ERROR: feature '{_feature.FEATURE_ID}' emit() failed: {_emit_exc}", file=_sys.stderr)
            if "feature_errors" not in summary:
                summary["feature_errors"] = {}
            summary["feature_errors"][_feature.FEATURE_ID] = str(_emit_exc)

    # Surface extract() errors
    for _feat_key, _feat_errs in list(_feature_accs.items()):
        if _feat_key.startswith("_extract_error_") and _feat_errs:
            _fid = _feat_key[len("_extract_error_"):]
            if "feature_errors" not in summary:
                summary["feature_errors"] = {}
            summary["feature_errors"][f"extract_{_fid}"] = "; ".join(str(e) for e in _feat_errs)

    # Cleanup internal stash keys
    _strip_internal_stash_keys(summary)

    # -- RTP integrity gate (warn_only) --
    try:
        _gate_result = check_rtp_integrity(
            summary,
            manifest=_legacy_manifest or None,
            rawdata_dir=None,
            warn_only=True,
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
    except Layer4Error as _exc:
        summary["rtp_integrity_check"] = {"passed": False, "error": f"Layer4Error: {_exc}"}
        import sys as _sys
        print(f"[report_engine] rtp_integrity Layer4Error for {machine_id} mode {mode}: {_exc}", file=_sys.stderr)
    except Exception as _exc:  # noqa: BLE001
        summary["rtp_integrity_check"] = {"passed": None, "error": f"{type(_exc).__name__}: {_exc}"}
        import sys as _sys
        print(f"[report_engine] rtp_integrity gate did not run for {machine_id} mode {mode}: {_exc}", file=_sys.stderr)

    # -- Write --
    write_summary_json(summary, output_dir)

    return summary
