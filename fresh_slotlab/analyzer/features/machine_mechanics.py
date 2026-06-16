"""AnalyzerFeature: machine_mechanics — Pattern B (Mechanism Registry driven).

Phase C4 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §7.2
and session_artifacts/_impl/phase_c4/brief.md.

Closes gaps #1 (jackpot.applicable=false despite jackpot pids present) and
#2 (free_spin.applicable=false despite freespin rounds present) from
session_artifacts/_arch_analyzer_unbundle/00_brief.md §3.

Mechanism
---------
This plugin replaces the PIA inline machine_mechanics block.  Instead of
independent detection per mechanic (the root cause of gaps #1+#2), the plugin
takes jackpot / free_spin applicability from the machine's DECLARED mechanism
(the SpinType-native manifest), the single source of truth.

For jackpot and free_spin, the plugin reads
``machine_spec.derive_mechanism_flags(ctx.machine_spec_manifest)`` for the
authoritative applicable flag and PID set (phase 5C: mechanism_registry deleted;
mechanism is declared in the manifest's spin_types role/play, not detected at
runtime).  For the quantitative fields (trigger_spins, trigger_rate, total_win,
rtp_contribution_pp) the plugin reads from its own extract() accumulator, which
mirrors the existing inline aggregation but is now centralized here.

For lock_lines / lock_symbols / lock_reels / dollar_pick (not yet in the
Mechanism Registry), the plugin continues to use the extract() accumulator
exactly as the inline block did.  These are pass-through with no behavior
change.

Data sources
------------
extract() reads from chunk_dict (parser output):
  lock_lines_spins, lock_lines_total_lines, lock_lines_win
  lock_symbols_spins, lock_symbols_unique (list), lock_symbols_win
  lock_reels_spins, lock_reels_win
  jackpot_spins, jackpot_ids_seen (list), jackpot_win
  freespin_chain_spins, freespin_retriggers, freespin_max_chain, freespin_win
  dollar_pick_spins, dollar_pick_total_dollars, dollar_pick_win

emit() reads:
  derive_mechanism_flags(ctx.machine_spec_manifest) — jackpot_applicable,
                           jackpot_pid_set, freespin_applicable, detection_source
  ctx.effective_bet_for_rtp — RTP denominator
  ctx.total_spins — rate denominator

Output schema (SCHEMA_VERSION = 2 — adds _detection_source per mechanic)
------------------------------------------------------------------------
summary["player_impact"]["machine_mechanics"]:
  lock_lines    — {applicable, lock_spins, lock_rate, total_lines_locked,
                   avg_lines_per_lock, lock_win, lock_rtp_contribution_pp}
  lock_symbols  — {applicable, lock_spins, lock_rate, unique_symbols,
                   unique_symbol_count, lock_win, lock_rtp_contribution_pp}
  lock_reels    — {applicable, lock_spins, lock_rate, lock_win,
                   lock_rtp_contribution_pp}
  jackpot       — {applicable, trigger_spins, trigger_rate, jackpot_ids,
                   jackpot_id_count, total_win, rtp_contribution_pp,
                   _detection_source}   ← NEW in C4
  free_spin     — {applicable, chain_spins, chain_rate, retriggers,
                   max_chain_length, total_win, rtp_contribution_pp,
                   _detection_source}   ← NEW in C4
  dollar_pick   — {applicable, pick_spins, pick_rate, total_dollars_picked,
                   avg_dollars_per_pick, total_win, rtp_contribution_pp}

SCHEMA_VERSION history
----------------------
v1 — pre-C4 inline block (no _detection_source field)
v2 — C4 plugin (adds _detection_source to jackpot and free_spin sections)

REGISTERED_FALLBACK_RULES[1] — old v1 summaries on disk have no
  _detection_source; frontend renders it as None per fallback rule.

Per-machine isolation
---------------------
This plugin file is NOT in fresh_slotlab/analyzer/core/ so its addition does
NOT change compute_base_analyzer_version().  Only machines that declare
"machine_mechanics" in their manifest's analyzer_features list will include
this plugin's hash in their effective_analyzer_version.

REQUIRES = ("bonus_chain_dynamics",) — R2 Phase 2 C-3: machine_mechanics.emit()
reads summary["player_impact"]["bonus_chain_dynamics"] for the M275 freespin
fallback path (fs_chain_spins from bonus_round_count).  After C-1 removes the
F6 inline write, this key is written only by the BonusChainDynamics plugin.
REQUIRES = ("bonus_chain_dynamics",) ensures topo-sort places machine_mechanics
after bonus_chain_dynamics regardless of alphabetical order.

Memory feedback honored
-----------------------
- feedback_invariant_with_fallback_hides_drift.md:
    _detection_source is an explicit required output per §5.2 — NOT a
    silent fallback bucket.  Every jackpot/free_spin decision records the
    tier that fired.  REGISTERED_FALLBACK_RULES[1] surfaces it as None for
    old summaries (explicit "not available for this version" rather than
    silently absent).
- feedback_no_silent_swallow.md:
    extract() errors surface via the PIA merge-loop mechanism.  The per-chunk
    error dict is returned (not swallowed).
- feedback_subprocess_import_suicide_and_module_globals.md:
    register() is a pure list-append — no I/O at import time.
- feedback_no_hardcode.md:
    No machine-specific semantics hardcoded.  Lock/jackpot/freespin fields
    come from parser accumulation, not from machine-id lookups.
- feedback_prefer_complex_better.md:
    Registry-driven approach rather than independent per-mechanic detectors.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    from fresh_slotlab.analyzer.feature_registry import register
except ImportError:  # running as standalone script
    from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
    from analyzer.feature_registry import register  # type: ignore[no-redef]

if TYPE_CHECKING:
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
    except ImportError:
        from analyzer.pipeline_context import PipelineContext  # type: ignore[assignment]


class MachineMechanics(AnalyzerFeature):
    """Pattern B plugin: machine mechanic detection via Mechanism Registry.

    Accumulator structure (6 mechanic sections)
    -------------------------------------------
    lock_lines:
      spins (int), total_lines (int), win (float)
    lock_symbols:
      spins (int), unique (set[str]), win (float)
    lock_reels:
      spins (int), win (float)
    jackpot:
      spins (int), ids_seen (set[str]), win (float)
    freespin:
      chain_spins (int), retriggers (int), max_chain (int), win (float)
    dollar_pick:
      spins (int), total_dollars (int), win (float)

    All counters are additive across chunks.
    lock_symbols.unique and jackpot.ids_seen are unioned across chunks.
    freespin.max_chain takes the max across chunks.
    """

    FEATURE_ID: ClassVar[str] = "machine_mechanics"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("machine_mechanics",)
    SCHEMA_VERSION: ClassVar[int] = 2  # C4: bumped from v1; adds _detection_source
    RTP_CONTRIBUTION: ClassVar[bool] = False  # display only; doesn't add to RTP totals
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    REQUIRES: ClassVar[tuple[str, ...]] = ("bonus_chain_dynamics",)
    # R2 Phase 2 C-3: REQUIRES now declares the bonus_chain_dynamics dependency
    # explicitly.  machine_mechanics.emit() reads
    # summary["player_impact"]["bonus_chain_dynamics"] for the M275 freespin
    # fallback (fs_chain_spins from bonus_round_count when CurFreeSpin is absent).
    # Pre-R2, this dependency was satisfied by alphabetical topo-sort accident
    # (bonus_chain_dynamics < machine_mechanics).  C-3 makes it a declared
    # structural constraint: topo-sort places machine_mechanics after
    # bonus_chain_dynamics regardless of alphabetical order.
    # All 253 manifests that declare machine_mechanics also declare
    # bonus_chain_dynamics — validated by arch-validator R2 W3.

    # v1 → v2: _detection_source field is new; old summaries render it as None.
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {
        1: {
            # v1 summaries (pre-C4 inline block) have no _detection_source.
            # Frontend renders as None when loading a v1 summary.
            "_detection_source": None,
        }
    }

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """Read per-chunk mechanic counters from chunk_dict.

        Reads from chunk_dict (parser output):
          lock_lines_spins, lock_lines_total_lines, lock_lines_win
          lock_symbols_spins, lock_symbols_unique, lock_symbols_win
          lock_reels_spins, lock_reels_win
          jackpot_spins, jackpot_ids_seen, jackpot_win
          freespin_chain_spins, freespin_retriggers, freespin_max_chain, freespin_win
          dollar_pick_spins, dollar_pick_total_dollars, dollar_pick_win

        Returns accumulator dict mirroring the inline PIA block structure.
        Handles:
          - None or non-dict chunk_dict: returns zero accumulator
          - Missing keys: treated as 0/empty (old cached chunks)
        """
        if not chunk_dict or not isinstance(chunk_dict, dict):
            return _empty_acc()

        try:
            return {
                "ll_spins": int(chunk_dict.get("lock_lines_spins", 0) or 0),
                "ll_total_lines": int(chunk_dict.get("lock_lines_total_lines", 0) or 0),
                "ll_win": float(chunk_dict.get("lock_lines_win", 0) or 0),
                "ls_spins": int(chunk_dict.get("lock_symbols_spins", 0) or 0),
                "ls_unique": set(str(s) for s in (chunk_dict.get("lock_symbols_unique") or [])),
                "ls_win": float(chunk_dict.get("lock_symbols_win", 0) or 0),
                "lr_spins": int(chunk_dict.get("lock_reels_spins", 0) or 0),
                "lr_win": float(chunk_dict.get("lock_reels_win", 0) or 0),
                "jp_spins": int(chunk_dict.get("jackpot_spins", 0) or 0),
                "jp_ids": set(str(j) for j in (chunk_dict.get("jackpot_ids_seen") or [])),
                "jp_win": float(chunk_dict.get("jackpot_win", 0) or 0),
                "fs_chain_spins": int(chunk_dict.get("freespin_chain_spins", 0) or 0),
                "fs_retriggers": int(chunk_dict.get("freespin_retriggers", 0) or 0),
                "fs_max_chain": int(chunk_dict.get("freespin_max_chain", 0) or 0),
                "fs_win": float(chunk_dict.get("freespin_win", 0) or 0),
                "dp_spins": int(chunk_dict.get("dollar_pick_spins", 0) or 0),
                "dp_total_dollars": int(chunk_dict.get("dollar_pick_total_dollars", 0) or 0),
                "dp_win": float(chunk_dict.get("dollar_pick_win", 0) or 0),
            }
        except (TypeError, ValueError):
            return _empty_acc()

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Merge two extract() outputs across chunks.

        Additive for numeric fields.
        Union for set fields (ls_unique, jp_ids).
        Max for fs_max_chain.
        Handles empty dicts (first chunk, error chunk).
        """
        if not prev_acc:
            return this_acc if this_acc else _empty_acc()
        if not this_acc:
            return prev_acc

        return {
            "ll_spins": prev_acc.get("ll_spins", 0) + this_acc.get("ll_spins", 0),
            "ll_total_lines": prev_acc.get("ll_total_lines", 0) + this_acc.get("ll_total_lines", 0),
            "ll_win": prev_acc.get("ll_win", 0.0) + this_acc.get("ll_win", 0.0),
            "ls_spins": prev_acc.get("ls_spins", 0) + this_acc.get("ls_spins", 0),
            "ls_unique": (prev_acc.get("ls_unique") or set()) | (this_acc.get("ls_unique") or set()),
            "ls_win": prev_acc.get("ls_win", 0.0) + this_acc.get("ls_win", 0.0),
            "lr_spins": prev_acc.get("lr_spins", 0) + this_acc.get("lr_spins", 0),
            "lr_win": prev_acc.get("lr_win", 0.0) + this_acc.get("lr_win", 0.0),
            "jp_spins": prev_acc.get("jp_spins", 0) + this_acc.get("jp_spins", 0),
            "jp_ids": (prev_acc.get("jp_ids") or set()) | (this_acc.get("jp_ids") or set()),
            "jp_win": prev_acc.get("jp_win", 0.0) + this_acc.get("jp_win", 0.0),
            "fs_chain_spins": prev_acc.get("fs_chain_spins", 0) + this_acc.get("fs_chain_spins", 0),
            "fs_retriggers": prev_acc.get("fs_retriggers", 0) + this_acc.get("fs_retriggers", 0),
            "fs_max_chain": max(
                prev_acc.get("fs_max_chain", 0),
                this_acc.get("fs_max_chain", 0),
            ),
            "fs_win": prev_acc.get("fs_win", 0.0) + this_acc.get("fs_win", 0.0),
            "dp_spins": prev_acc.get("dp_spins", 0) + this_acc.get("dp_spins", 0),
            "dp_total_dollars": prev_acc.get("dp_total_dollars", 0) + this_acc.get("dp_total_dollars", 0),
            "dp_win": prev_acc.get("dp_win", 0.0) + this_acc.get("dp_win", 0.0),
        }

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Build and write summary["player_impact"]["machine_mechanics"].

        Reads:
          derive_mechanism_flags(ctx.machine_spec_manifest) — jackpot_applicable,
                                   jackpot_pid_set, freespin_applicable, detection_source
          ctx.effective_bet_for_rtp — RTP denominator
          ctx.total_spins — rate denominator
          final_acc — accumulated mechanic counters from extract/reduce

        Writes:
          summary["player_impact"]["machine_mechanics"] with the existing
          6-section schema (lock_lines / lock_symbols / lock_reels / jackpot /
          free_spin / dollar_pick) plus _detection_source on jackpot+free_spin.

        Jackpot and free_spin applicable flags come from the DECLARED mechanism
        (manifest spin_types role/play via derive_mechanism_flags), NOT from the
        raw counter > 0 test that the old inline block used.  This closes gaps #1 and #2.

        For lock_lines / lock_symbols / lock_reels / dollar_pick, the
        applicable flag is still counter > 0 (these mechanics are not yet
        in the Mechanism Registry — that is scope for C5).
        """
        player_impact = summary.setdefault("player_impact", {})
        acc = final_acc or {}
        ebet = ctx.effective_bet_for_rtp
        total_spins = ctx.total_spins

        # Phase 5C: mechanism_registry removed. Manifest-only path.
        # For non-registered machines (no machine_spec_manifest), all mechanism flags
        # default to False — non-registered machines don't generate reports anyway.
        if isinstance(ctx.machine_spec_manifest, dict) and ctx.machine_spec_manifest:
            try:
                from fresh_slotlab.analyzer.machine_spec import derive_mechanism_flags
            except ImportError:
                from analyzer.machine_spec import derive_mechanism_flags  # type: ignore[no-redef]
            _mflags = derive_mechanism_flags(ctx.machine_spec_manifest)
            _jp_applicable = _mflags["jackpot_applicable"]
            _jp_pid_set_manifest = _mflags["jackpot_pid_set"]
            _fs_applicable = _mflags["freespin_applicable"]
            _detection_src_jp = _mflags["detection_source"]
            _detection_src_fs = _mflags["detection_source"]
        else:
            _jp_applicable = False
            _jp_pid_set_manifest = frozenset()
            _fs_applicable = False
            _detection_src_jp = "manifest_absent"
            _detection_src_fs = "manifest_absent"

        def _rtp(win: float) -> float:
            return (win / ebet * 100) if ebet > 0 else 0.0

        def _rate(n: int) -> float:
            return (n / total_spins) if total_spins > 0 else 0.0

        # Lock lines
        ll_spins = int(acc.get("ll_spins", 0))
        ll_lines = int(acc.get("ll_total_lines", 0))
        ll_win = float(acc.get("ll_win", 0.0))
        lock_lines_block = {
            "applicable": ll_spins > 0,
            "lock_spins": ll_spins,
            "lock_rate": _rate(ll_spins),
            "total_lines_locked": ll_lines,
            "avg_lines_per_lock": (ll_lines / ll_spins) if ll_spins > 0 else 0,
            "lock_win": ll_win,
            "lock_rtp_contribution_pp": _rtp(ll_win),
        }

        # Lock symbols
        ls_spins = int(acc.get("ls_spins", 0))
        ls_unique = sorted(acc.get("ls_unique") or set())
        ls_win = float(acc.get("ls_win", 0.0))
        lock_symbols_block = {
            "applicable": ls_spins > 0,
            "lock_spins": ls_spins,
            "lock_rate": _rate(ls_spins),
            "unique_symbols": ls_unique,
            "unique_symbol_count": len(ls_unique),
            "lock_win": ls_win,
            "lock_rtp_contribution_pp": _rtp(ls_win),
        }

        # Lock reels
        lr_spins = int(acc.get("lr_spins", 0))
        lr_win = float(acc.get("lr_win", 0.0))
        lock_reels_block = {
            "applicable": lr_spins > 0,
            "lock_spins": lr_spins,
            "lock_rate": _rate(lr_spins),
            "lock_win": lr_win,
            "lock_rtp_contribution_pp": _rtp(lr_win),
        }

        # Jackpot — DRIVEN BY MANIFEST (phase 3) or MECHANISM REGISTRY (legacy).
        # applicable and jackpot_ids come from manifest spin_types (phase 3) or
        # registry (Tier 1/2/3). Quantitative fields (trigger_spins, total_win, rtp)
        # come from the extract() accumulator (raw parser counts, unchanged semantics).
        jp_spins = int(acc.get("jp_spins", 0))
        jp_ids_acc = sorted(acc.get("jp_ids") or set())  # from JackpotIds field only
        jp_win = float(acc.get("jp_win", 0.0))

        # Manifest-driven fields (phase 3) or registry-driven (legacy):
        jp_applicable = _jp_applicable
        jp_pid_set = sorted(_jp_pid_set_manifest)  # from manifest spin_types
        jp_detection_src = _detection_src_jp

        # jackpot_ids: prefer the registry's union result (more complete than
        # jp_ids_acc which only has IDs from the JackpotIds raw field).
        # If registry has IDs (Path A M275-style OR Path B M11-style), use those.
        # Fall back to jp_ids_acc only if registry has no IDs (should not happen
        # when applicable=True, but defensive).
        jackpot_ids_final = jp_pid_set if jp_pid_set else jp_ids_acc

        # For machines like M275 where jackpot wins come through payout_id_win
        # (not JackpotIds raw field), jp_win from extract() is 0.  Reconstruct
        # total_win by summing the jackpot PIDs in payout_ids_top20 (which is
        # guaranteed written by the inline block before the emit loop).
        if jp_win == 0.0 and jp_applicable and jp_pid_set:
            _pids_top20 = (
                summary.get("player_impact", {})
                       .get("payout_ids_top20", [])
            )
            _jp_pid_str_set = set(jp_pid_set)
            for _row in _pids_top20:
                _pid_s = str(_row.get("payout_id", ""))
                if _pid_s in _jp_pid_str_set:
                    jp_win += float(_row.get("total_win", 0) or 0)

        # trigger_spins: for machines using JackpotIds field (M11), jp_spins
        # counts actual jackpot trigger rounds.  For M275-style PIDs, jp_spins=0
        # but hit_count from payout_ids_top20 can fill it.
        if jp_spins == 0 and jp_applicable and jp_pid_set:
            _pids_top20 = (
                summary.get("player_impact", {})
                       .get("payout_ids_top20", [])
            )
            _jp_pid_str_set = set(jp_pid_set)
            for _row in _pids_top20:
                _pid_s = str(_row.get("payout_id", ""))
                if _pid_s in _jp_pid_str_set:
                    jp_spins += int(_row.get("hit_count", 0) or 0)

        jackpot_block = {
            "applicable": jp_applicable,
            "trigger_spins": jp_spins,
            "trigger_rate": _rate(jp_spins),
            "jackpot_ids": jackpot_ids_final,
            "jackpot_id_count": len(jackpot_ids_final),
            "total_win": jp_win,
            "rtp_contribution_pp": _rtp(jp_win),
            "_detection_source": jp_detection_src,  # C4 transparency field
        }

        # Free spin — DRIVEN BY MANIFEST (phase 3) or MECHANISM REGISTRY (legacy).
        # applicable comes from manifest spin_types play=="freespin" (phase 3) or
        # registry (Tier 1/2 bonus_chain_lengths check). Quantitative fields come
        # from extract() accumulator.
        fs_chain_spins = int(acc.get("fs_chain_spins", 0))
        fs_retriggers = int(acc.get("fs_retriggers", 0))
        fs_max_chain = int(acc.get("fs_max_chain", 0))
        fs_win = float(acc.get("fs_win", 0.0))

        fs_applicable = _fs_applicable
        fs_detection_src = _detection_src_fs

        # For machines like M275 where freespin chains are tracked via
        # bonus_chain_dynamics (ReMarks-based) rather than CurFreeSpin
        # (which populates freespin_chain_spins = 0), fall back to
        # bonus_chain_dynamics.bonus_round_count as chain_spins.
        # bonus_chain_dynamics is guaranteed present because
        # REQUIRES = ("bonus_chain_dynamics",) (R2 Phase 2 C-3) makes topo-sort
        # run bonus_chain_dynamics.emit() before this plugin's emit().
        if fs_chain_spins == 0 and fs_applicable:
            _bcd = (
                summary.get("player_impact", {})
                       .get("bonus_chain_dynamics", {})
            )
            _bcd_round_count = int(_bcd.get("bonus_round_count", 0) or 0)
            _bcd_chain_count = int(_bcd.get("chain_count", 0) or 0)
            if _bcd_round_count > 0:
                fs_chain_spins = _bcd_round_count
                # max_chain_length: use avg rounded down if max is 0
                if fs_max_chain == 0:
                    _avg_len = _bcd.get("avg_chain_length", 0) or 0
                    if _avg_len:
                        fs_max_chain = round(_avg_len)

        # Same fallback family for the WIN: on those role/play-declared
        # machines the CurFreeSpin-based ``freespin_win`` accumulator stays 0
        # while the free rounds' settled wins live in spin_type_breakdown
        # (written inline by the engine before the emit loop). Without this,
        # an APPLICABLE card renders rtp_contribution_pp 0.00 while the same
        # report shows the real pp elsewhere (the M275 W5 breaker
        # counterexample). Manifest-driven: sum total_win of the STs whose
        # role/play is "freespin" — no machine-specific code.
        if fs_win == 0.0 and fs_applicable and fs_chain_spins > 0:
            _ms_manifest = getattr(ctx, "machine_spec_manifest", None) or {}
            _fs_sts: set[str] = set()
            for _st_key, _st_spec in (_ms_manifest.get("spin_types") or {}).items():
                if not isinstance(_st_spec, dict):
                    continue
                if (str(_st_spec.get("role") or "").lower() == "freespin"
                        or str(_st_spec.get("play") or "").lower() == "freespin"):
                    _fs_sts.add(str(_st_key))
            if _fs_sts:
                _stb_rows = (
                    summary.get("player_impact", {})
                           .get("spin_type_breakdown") or []
                )
                _fb_win = 0.0
                for _stb_row in _stb_rows:
                    if str(_stb_row.get("spin_type")) in _fs_sts:
                        _fb_win += float(_stb_row.get("total_win") or 0.0)
                if _fb_win > 0:
                    fs_win = _fb_win
                    fs_detection_src = (
                        f"{fs_detection_src}+stb_win_fallback"
                        if fs_detection_src else "stb_win_fallback"
                    )

        free_spin_block = {
            "applicable": fs_applicable,
            "chain_spins": fs_chain_spins,
            "chain_rate": _rate(fs_chain_spins),
            "retriggers": fs_retriggers,
            "max_chain_length": fs_max_chain,
            "total_win": fs_win,
            "rtp_contribution_pp": _rtp(fs_win),
            "_detection_source": fs_detection_src,  # C4 transparency field
        }

        # Dollar pick
        dp_spins = int(acc.get("dp_spins", 0))
        dp_dollars = int(acc.get("dp_total_dollars", 0))
        dp_win = float(acc.get("dp_win", 0.0))
        dollar_pick_block = {
            "applicable": dp_spins > 0,
            "pick_spins": dp_spins,
            "pick_rate": _rate(dp_spins),
            "total_dollars_picked": dp_dollars,
            "avg_dollars_per_pick": (dp_dollars / dp_spins) if dp_spins > 0 else 0,
            "total_win": dp_win,
            "rtp_contribution_pp": _rtp(dp_win),
        }

        player_impact["machine_mechanics"] = {
            "lock_lines": lock_lines_block,
            "lock_symbols": lock_symbols_block,
            "lock_reels": lock_reels_block,
            "jackpot": jackpot_block,
            "free_spin": free_spin_block,
            "dollar_pick": dollar_pick_block,
        }


def _empty_acc() -> dict:
    """Return a zero-valued accumulator dict."""
    return {
        "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
        "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
        "lr_spins": 0, "lr_win": 0.0,
        "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
        "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
        "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
    }


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# ---------------------------------------------------------------------------
register(MachineMechanics())
