"""AnalyzerFeature: minigame_dynamics — the WinMiniGame (st51) MECHANIC view.

M43 onboarding (Wave 4). st51 has no reels/cost and no round-level PayoutId; its
whole win is attributed to a single real pid `st51` by the config-only
SynthesizePayIdRule (configs/machine_round_win_rules.json: m43_minigame_settlement)
so the RTP-integrity gate passes (_unattributed_st51 -> 0). This feature quantifies
the MINIGAME MECHANIC's felt experience as rates / multipliers / probabilities /
shares (money-agnostic; NO coin totals).

What the player feels (design 03_design.md §2): out of nowhere (usually right
after a losing spin) the game drops into a bonus board and pays a chunky prize —
a rescue / pleasant-surprise moment. The minigame is the machine's big-win engine:
~1% of spins deliver ~31% of payback.

Mechanic metrics (design G1–G6)
-------------------------------
- G1 multiplier distribution: "what does the minigame typically pay?" The design
    prefers the server's own SummaryWin taxonomy. The parser does NOT capture
    SummaryWin (only TotalWin/FeatureWin, and FeatureWin collapses the minigame
    into the meaningless feature-flag tier 500). BUT Wave-1 PROVED (econ §4) that
    re-banding every minigame round by WinCredits/bet reproduces SummaryWin's
    WinMiniGame tiers 100% exactly. We therefore build the multiplier distribution
    from the per-ST return-bucket histogram (our own win/bet banding) — the same
    numbers, money-agnostic. (st51 has no BetAmount, so the parser's bet defaults
    to the run bet (1000); win/bet is meaningful.)
- G2 trigger frequency: rarity / anticipation. Signal: st51 spins / base spins.
- G3 surprise-on-loss ⭐: the signature feel — the minigame mostly fires after a
    LOSING paid spin (a rescue). The TRIGGER-CONTEXT transition COUNTS (base->st51
    vs respin->st51) are derivable; the win/loss STATUS of the specific preceding
    base spin is NOT (transition counts don't carry the predecessor's outcome) —
    see `parser_blind`.
- G4 node-count × multiplier: longer path pays more (board progression). NEEDS the
    per-round ReMarks="MiniGame[...]" node list — see `parser_blind`.
- G5 node-code distribution + terminal-node: the path vocabulary. Same — NEEDS the
    per-round node list — see `parser_blind`.
- G6 RTP-concentration ⭐: the big-win engine — a rare event carrying a huge share
    of payback. Signal: st51 rtp_contribution_pp / total + trigger rate.

Data path (all base-EXCLUDED — no parser/closure dependency)
------------------------------------------------------------
extract() reads two PER-CHUNK accumulators the parser already emits in the chunk
dict (rec) — accumulated OURSELVES (no stash-ordering dependency):

  chunk_dict["spin_type_next_counts"]
      {str(from_st): {str(to_st): count}} — ST transitions. Gives base->st51 and
      respin->st51 opener contexts (G3 counts) and the st51 fire rate (G2).
  chunk_dict["spin_type_bucket_spins" | "spin_type_bucket_win"]
      {str(st): {return_bucket_label: value}} — per-ST win/bet multiplier-band
      histogram over ALL rounds. For st51 the bet defaults to the run bet, so the
      bands are meaningful multipliers (G1). "eq0" is the zero-win band (st51 wins
      on 100% of rounds, so it is empty here).

emit() additionally reads the byte-stable summary["player_impact"]["spin_type_breakdown"]
(per-ST round-level stats) for G2/G6 (spins, total_win, rtp_contribution_pp).

RTP_CONTRIBUTION = False
  The minigame win is already attributed (to pid `st51`) by the synth rule +
  PER_SPINTYPE plugins. This feature re-presents it; it adds NOTHING to the RTP
  sum (feedback_aggregator_parity_invariant.md).

Per-machine isolation
---------------------
NOT in fresh_slotlab/analyzer/core/ and NOT in versioning._CLOSURE_FILES — base-
EXCLUDED (R-4). Auto-discovered via feature_registry.discover_features(). Editing
it re-flags ONLY machines declaring "minigame_dynamics" (via play "WinMiniGame" in
machine_spec.PLAY_ANALYSES — NOT the shared `settlement` role, so it does NOT fire
on M15's TopDollar settlement).

Memory feedback honored
-----------------------
- feedback_no_hardcode.md: the minigame ST is resolved from the manifest's
  spin_types (play "WinMiniGame"), NOT hardcoded "51".
- feedback_no_silent_swallow.md: a missing spin_type_breakdown section RAISES.
  The SummaryWin-source / node-list / surprise-on-loss sub-metrics that the frozen
  framework cannot expose are surfaced EXPLICITLY in `parser_blind` — never
  fabricated as zeros.
- feedback_invariant_with_fallback_hides_drift.md: no catch-all bucket; rates with
  a zero denominator are null, not a "0.0 with 0 denominator" lie.
- feedback_no_parallel_panel_impl.md: mirrors spin_type_rtp_buckets /
  spin_type_outcomes / respin_dynamics pattern; reuses RETURN_BUCKET_ORDER.
- feedback_subprocess_import_suicide_and_module_globals.md: register() is a pure
  list-append; no I/O at import time.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    from fresh_slotlab.analyzer.feature_registry import register
    from fresh_slotlab.analyzer.core.aggregator import RETURN_BUCKET_ORDER
except ImportError:  # running as standalone script
    from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
    from analyzer.feature_registry import register  # type: ignore[no-redef]
    from analyzer.core.aggregator import RETURN_BUCKET_ORDER  # type: ignore[no-redef]

if TYPE_CHECKING:
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
    except ImportError:
        from analyzer.pipeline_context import PipelineContext  # type: ignore[assignment]


def _merge_nested_counts(
    prev: dict[str, dict[str, float]],
    this: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Additively merge two {outer: {inner: number}} dicts."""
    out: dict[str, dict[str, float]] = {}
    for okey, imap in prev.items():
        out[okey] = dict(imap)
    for okey, imap in this.items():
        dest = out.setdefault(okey, {})
        for ikey, val in imap.items():
            dest[ikey] = dest.get(ikey, 0) + val
    return out


def _resolve_st_by_play(manifest: dict[str, Any] | None, play: str) -> int | None:
    """Return the first SpinType int whose spec.play == play. None if no match.

    No hardcoded ids (feedback_no_hardcode.md): the minigame ST is identified by
    its rawdata feature name (play), read from ctx.machine_spec_manifest.
    """
    if not isinstance(manifest, dict):
        return None
    for st_key, spec in (manifest.get("spin_types") or {}).items():
        if isinstance(spec, dict) and str(spec.get("play", "")) == play:
            try:
                return int(st_key)
            except (TypeError, ValueError):
                continue
    return None


def _resolve_st_by_role(manifest: dict[str, Any] | None, role: str) -> int | None:
    """Return the first SpinType int whose spec.role == role. None if no match."""
    if not isinstance(manifest, dict):
        return None
    for st_key, spec in (manifest.get("spin_types") or {}).items():
        if isinstance(spec, dict) and str(spec.get("role", "")) == role:
            try:
                return int(st_key)
            except (TypeError, ValueError):
                continue
    return None


class MiniGameDynamics(AnalyzerFeature):
    """Pattern-B plugin: accumulate transition + per-ST bucket data per chunk;
    compute the minigame-mechanic metrics in emit().

    Accumulator structure
    ---------------------
      next_counts: dict[str, dict[str, int]]   — ST transition tally.
      bucket_spins / bucket_win: dict[str, dict[str, number]] — per-ST bands.
    """

    FEATURE_ID: ClassVar[str] = "minigame_dynamics"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("minigame_dynamics",)
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False  # win already attributed via synth rule
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    # We read spin_type_breakdown in emit(); payouts_by_spin_type guarantees it is
    # present (it requires spin_type_breakdown, written by the inline F1 block).
    REQUIRES: ClassVar[tuple[str, ...]] = ("payouts_by_spin_type",)
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """Lift the per-chunk transition tally + per-ST bucket histograms."""
        if not chunk_dict or not isinstance(chunk_dict, dict):
            return {"next_counts": {}, "bucket_spins": {}, "bucket_win": {}}

        def _coerce_nested(raw: Any, *, as_int: bool) -> dict[str, dict[str, float]]:
            out: dict[str, dict[str, float]] = {}
            if not isinstance(raw, dict):
                return out
            for okey, imap in raw.items():
                if not isinstance(imap, dict):
                    continue
                inner: dict[str, float] = {}
                for ikey, val in imap.items():
                    try:
                        inner[str(ikey)] = int(val or 0) if as_int else float(val or 0.0)
                    except (TypeError, ValueError):
                        continue
                if inner:
                    out[str(okey)] = inner
            return out

        return {
            "next_counts": _coerce_nested(
                chunk_dict.get("spin_type_next_counts"), as_int=True
            ),
            "bucket_spins": _coerce_nested(
                chunk_dict.get("spin_type_bucket_spins"), as_int=True
            ),
            "bucket_win": _coerce_nested(
                chunk_dict.get("spin_type_bucket_win"), as_int=False
            ),
        }

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Additively merge transition + bucket tallies across chunks."""
        if not prev_acc:
            return this_acc if this_acc else {
                "next_counts": {}, "bucket_spins": {}, "bucket_win": {}
            }
        if not this_acc:
            return prev_acc
        return {
            "next_counts": _merge_nested_counts(
                prev_acc.get("next_counts") or {}, this_acc.get("next_counts") or {}
            ),
            "bucket_spins": _merge_nested_counts(
                prev_acc.get("bucket_spins") or {}, this_acc.get("bucket_spins") or {}
            ),
            "bucket_win": _merge_nested_counts(
                prev_acc.get("bucket_win") or {}, this_acc.get("bucket_win") or {}
            ),
        }

    @staticmethod
    def _multiplier_distribution(
        bucket_spins: dict[str, int],
        bucket_win: dict[str, float],
    ) -> dict[str, Any]:
        """Money-agnostic multiplier-band distribution for the minigame.

        Returns {bands:[{band, spin_count, prob, win_share}], total_events,
        modal_band, dominant_band_share}. prob/win_share over ALL minigame events.
        """
        total_spins = sum(int(v) for v in bucket_spins.values())
        total_win = sum(float(v) for v in bucket_win.values())
        bands: list[dict[str, Any]] = []
        modal_band: str | None = None
        modal_count = -1
        for band in RETURN_BUCKET_ORDER:
            sc = int(bucket_spins.get(band, 0))
            bw = float(bucket_win.get(band, 0.0))
            if sc == 0 and bw == 0.0:
                continue
            bands.append({
                "band": band,
                "spin_count": sc,
                "prob": (sc / total_spins) if total_spins > 0 else None,
                "win_share": (bw / total_win) if total_win > 0 else None,
            })
            if sc > modal_count:
                modal_count = sc
                modal_band = band
        return {
            "total_events": total_spins,
            "bands": bands,
            "modal_band": modal_band,
            "dominant_band_share": (
                (modal_count / total_spins)
                if (total_spins > 0 and modal_count > 0) else None
            ),
            "source": (
                "our win/bet banding (RETURN_BUCKET_ORDER). Wave-1 econ §4 proved "
                "this reproduces the server SummaryWin WinMiniGame tiers 100% "
                "exactly; the parser does not capture SummaryWin directly."
            ),
        }

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Compute and write summary["player_impact"]["minigame_dynamics"]."""
        player_impact = summary.setdefault("player_impact", {})

        # Hard dependency check (feedback_no_silent_swallow.md).
        if "spin_type_breakdown" not in player_impact:
            raise RuntimeError(
                "minigame_dynamics requires player_impact['spin_type_breakdown'] "
                "but it is absent at emit time — the inline F1 block / "
                "PayoutsBySpinType did not run or failed upstream."
            )

        manifest = getattr(ctx, "machine_spec_manifest", None)
        mg_st = _resolve_st_by_play(manifest, "WinMiniGame")
        base_st = _resolve_st_by_role(manifest, "paid_spin")
        respin_st = _resolve_st_by_role(manifest, "respin")

        if mg_st is None:
            player_impact["minigame_dynamics"] = {
                "applicable": False,
                "reason": "no SpinType with play 'WinMiniGame' in manifest",
            }
            return

        next_counts: dict[str, dict[str, int]] = (final_acc or {}).get("next_counts") or {}
        bucket_spins: dict[str, dict[str, int]] = (final_acc or {}).get("bucket_spins") or {}
        bucket_win: dict[str, dict[str, float]] = (final_acc or {}).get("bucket_win") or {}

        stb_rows: list[dict[str, Any]] = player_impact.get("spin_type_breakdown") or []
        stb_by_st: dict[int, dict[str, Any]] = {}
        for row in stb_rows:
            try:
                stb_by_st[int(row.get("spin_type"))] = row
            except (TypeError, ValueError):
                continue
        mg_row = stb_by_st.get(mg_st) or {}
        base_row = stb_by_st.get(base_st) if base_st is not None else {}
        base_row = base_row or {}

        mg_st_s = str(mg_st)
        base_st_s = str(base_st) if base_st is not None else None
        respin_st_s = str(respin_st) if respin_st is not None else None

        # ── G1 — multiplier distribution (our banding == SummaryWin tiers) ──
        multiplier_distribution = self._multiplier_distribution(
            bucket_spins.get(mg_st_s) or {}, bucket_win.get(mg_st_s) or {}
        )

        # ── G2 — trigger frequency ──
        mg_spins = int(mg_row.get("spins") or 0)
        base_spins = int(base_row.get("spins") or 0)
        trigger_frequency = {
            "minigame_events": mg_spins,
            "per_paid_spin": (mg_spins / base_spins) if base_spins > 0 else None,
            "one_per_n_paid_spins": (base_spins / mg_spins) if mg_spins > 0 else None,
        }

        # ── G3 — trigger-context (surprise-on-loss is parser-blind) ──
        # Openers INTO the minigame, by source ST (transition counts).
        opener_from_base = (
            int((next_counts.get(base_st_s) or {}).get(mg_st_s, 0))
            if base_st_s is not None else 0
        )
        opener_from_respin = (
            int((next_counts.get(respin_st_s) or {}).get(mg_st_s, 0))
            if respin_st_s is not None else 0
        )
        opener_total = opener_from_base + opener_from_respin
        trigger_context = {
            "opener_from_base_spin": opener_from_base,
            "opener_from_respin_burst": opener_from_respin,
            "share_from_base_spin": (
                opener_from_base / opener_total if opener_total > 0 else None
            ),
            "share_from_respin_burst": (
                opener_from_respin / opener_total if opener_total > 0 else None
            ),
            "parser_blind": [
                "surprise_on_loss_rate (share of minigames that follow a "
                "ZERO-WIN base spin vs a winning one)",
            ],
            "parser_blind_reason": (
                "the win/loss STATUS of the specific base spin that precedes each "
                "minigame is not carried by the aggregate transition counts; "
                "computing it needs per-round predecessor-outcome tracking in "
                "parser.py (a base-closure file). The transition COUNTS by source "
                "ST above ARE derivable base-excluded. Escalated to framework team."
            ),
        }

        # ── G4 / G5 — node path analysis (parser-blind) ──
        node_path_analysis = {
            "available": False,
            "parser_blind": [
                "node_count_x_multiplier (G4: path length 1-8 -> avg multiplier)",
                "node_code_distribution (G5: code frequency over the 101-110 pool)",
                "terminal_node_x_multiplier (G5: last code in path -> multiplier)",
                "solo_terminal_value_ladder (G5: 106->10x .. 110->30x)",
            ],
            "parser_blind_reason": (
                "the per-round ReMarks='MiniGame[n1,n2,...]' node list is NOT "
                "accumulated by parser.py (it keeps only 3 sample ReMarks strings "
                "per SpinType, not a node-list distribution). Computing node-count "
                "/ node-code / terminal-node tables needs a new per-round ReMarks "
                "accumulator in parser.py (a base-closure file). Escalated to the "
                "framework team. (Wave-1 struct §7.7 / econ §6e mapped these from "
                "a one-off raw re-parse; they are real but not framework-derivable "
                "without the parser accumulator.)"
            ),
        }

        # ── G6 — RTP-concentration (the big-win engine) ──
        all_win = sum(float(r.get("total_win") or 0.0) for r in stb_rows)
        mg_win = float(mg_row.get("total_win") or 0.0)
        total_spins_all = sum(int(r.get("spins") or 0) for r in stb_rows)
        rtp_concentration = {
            "minigame_rtp_contribution_pp": mg_row.get("rtp_contribution_pp"),
            "share_of_all_win": (mg_win / all_win) if all_win > 0 else None,
            "event_rate": (
                mg_spins / total_spins_all if total_spins_all > 0 else None
            ),
            "hit_rate": mg_row.get("hit_rate"),
            "note": (
                "the rarest ~1% of outcomes (the minigame) carries a large share "
                "of all payback — the opposite of the base game's grind. Compare "
                "event_rate to share_of_all_win for the concentration ratio."
            ),
        }

        player_impact["minigame_dynamics"] = {
            "applicable": True,
            "minigame_spin_type": mg_st,
            "attributed_pay_id": f"st{mg_st}",
            "multiplier_distribution": multiplier_distribution,
            "trigger_frequency": trigger_frequency,
            "trigger_context": trigger_context,
            "node_path_analysis": node_path_analysis,
            "rtp_concentration": rtp_concentration,
        }


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# Auto-discovered by feature_registry.discover_features() (globs features/*.py).
# ---------------------------------------------------------------------------
register(MiniGameDynamics())
