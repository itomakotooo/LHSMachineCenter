"""M31 FeaturePlugin — 5-payline multiplier wild + 7-spin FreeSpin chain.

Mechanism (from session_artifacts/M31/01c_field_analysis.md):

  Machine type: 3-reel 3-row 5-payline classic with:
    - 4 wild tiers: Wild2x(x2), Wild3x(x3), Wild5x(x5), Wild10x(x10)
    - Tier B (pure wild, fixed credits): pay_ids 1-6
    - Tier A (regular x wild_mult_product): pay_ids 7-11
    - Scatter anywhere (3 in 3x3 grid): pay_ids 12 + 666 trigger
    - FreeSpin: ST=44, 7 spins per trigger, freespin reel set (R2=100% wild)

Production rawdata schema this plugin manages:

  Base spin (ST=43):
    Full 17-field round dict. Multi-payline (5 lines) + scatter anywhere.
    ReMarks = 'TriggerFreespin' when 3 Scatter triggers FreeSpin.
    ReMarks = '' otherwise.

  FreeSpin (ST=44):
    Full 17-field round dict. CostCredits=0, BetAmount=1000.
    ReMarks = 'FreeSpin' consistently.

Round emission strategy:
  The core SpinEngine evaluates paylines[0] (center row) and returns outcome.pay.
  This plugin carries the full grid in M31Session.base_grid and re-evaluates
  all 5 paylines + scatter via evaluate_all_paylines() in emit_extra_rounds.
  emit_extra_rounds mutates the base_round dict in-place (Python dict mutation
  is visible to the caller's reference in emit_session's session list), then
  appends the 7 FreeSpin round dicts.

  This avoids needing a custom engine: the core driver's emit_session
  handles the 17-field template; the plugin patches the per-machine fields.

Classification rules (analyzer-side):
  ST=43  -> "NormalFreeSpin", win = WinCredits
  ST=44  -> "FreeSpin",       win = WinCredits

TODO Stage 6 fit markers:
  - FreeSpin R1/R3 weights (approximated from observed stop frequencies)
  - FreeSpin R2 strip approximation (13-stop fit, delta < 2pp per symbol)
"""
from __future__ import annotations

import json as _json
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from typing import Any

from slot_designer.core.engine.evaluator import PaytableEvaluator
from slot_designer.core.engine.reel_strip import ReelStrip, Stop
from slot_designer.core.engine.rules import PayResult, RuleSet
from slot_designer.core.engine.spin import SpinEngine, SpinOutcome
from slot_designer.core.engine.symbol import SymbolRegistry

# SpinType constants — M31-specific (ARCHITECTURE §7: machine names stay in plugin)
_ST_PAID = 43       # base paid spin
_ST_FREE = 44       # FreeSpin bonus spin

# Scatter pay_ids — M31-specific
_PAY_ID_SCATTER_WIN = 12       # 5000 credits fixed
_PAY_ID_SCATTER_TRIGGER = 666  # 0 credits, FreeSpin trigger marker

_SCATTER_SYMBOL = "Scatter"
_SCATTER_WIN_CREDITS = 5000
_FREESPIN_COUNT = 7

# ReMarks strings matching production rawdata (01c §5)
_REMARKS_TRIGGER = "TriggerFreespin"
_REMARKS_FREE = "FreeSpin"
_REMARKS_NORMAL = ""

# Feature stream names for classify_round / analysisResult buckets
_FEATURE_NORMAL = "NormalFreeSpin"
_FEATURE_FREE = "FreeSpin"

# 5 paylines: list of (col, row) 0-indexed positions
_PAYLINES: list[list[tuple[int, int]]] = [
    [(0, 1), (1, 1), (2, 1)],  # line 1: center row
    [(0, 0), (1, 0), (2, 0)],  # line 2: top row
    [(0, 2), (1, 2), (2, 2)],  # line 3: bottom row
    [(0, 0), (1, 1), (2, 2)],  # line 4: diagonal down
    [(0, 2), (1, 1), (2, 0)],  # line 5: diagonal up
]

_LINE_IDS = [1, 2, 3, 4, 5]          # production line IDs
_LINE_ID_SCATTER_WIN = -2             # negative line IDs for scatter pays (01c §3)
_LINE_ID_SCATTER_TRIGGER = -1

# Tier B fixed credit amounts (pay_id → credits, NOT multiplied by wild_mult)
_TIER_B_FIXED_CREDITS: dict[int, int] = {
    1: 30000,   # 3x Wild5x
    2: 15000,   # 3x Wild3x
    3: 5000,    # 3x Wild2x
    4: 10000,   # any containing Wild10x
    5: 3000,    # any containing Wild5x (no Wild10x)
    6: 600,     # any {Wild2x, Wild3x} only
}

# Tier A base credits (used only for documentation; evaluator uses multiplier * bet)
_TIER_A_BASE_CREDITS: dict[int, int] = {
    7: 1600, 8: 1200, 9: 600, 10: 200, 11: 100,
}


@dataclass
class M31Session:
    """Opaque per-session object carried through simulate_session -> emit_extra_rounds.

    Carries the base spin grid (for 5-payline re-evaluation in emit_extra_rounds)
    and the 7 FreeSpin outcomes. Generic core code never inspects this object.
    """
    base_grid: list[list[str]]     # grid[col][row] = symbol from base ST=43 spin
    base_has_scatter: bool         # True if 3+ Scatter in base grid
    freespin_outcomes: list[SpinOutcome]  # 7 SpinOutcome objects from freespin engine


class M31FeaturePlugin:
    """M31 FeaturePlugin — 5-payline + FreeSpin 7-spin chain.

    Conforms to core/engine/feature_protocol.py FeaturePlugin Protocol.

    Trigger mode: scatter-pay trigger on pay_id=666.
    SpinEngine.spin_session fires when pay_id 666 is in outcome.scatter_pays.

    However, since M31's scatter is any-position (not reel-specific),
    the core evaluate_scatters() can't detect it directly. We solve this
    by using a dummy scatter_trigger rule that fires when Scatter appears
    on reel 3 center row — but also evaluate the full-grid scatter count
    ourselves in emit_extra_rounds.

    Actually: M31 uses trigger_pay_id=666 with a ScatterTriggerRule that
    detects Scatter on any reel. The plugin then handles the actual
    any-position scatter evaluation.

    Implementation detail:
      simulate_session() is called by SpinEngine.spin_session when it
      detects pay_id=666 in scatter_pays. We also receive the full grid
      via the M31Session approach.

      Since we need the base_grid at emit_extra_rounds time, we:
      1. Store the last evaluated grid in a thread-local instance variable.
         This works because sample_one_chunk serialises all spins in a
         single-threaded loop (no concurrent calls).
      2. simulate_session() captures the pending grid from self._pending_grid
         which was set during spin_session intercept.

      Limitation: trigger_pay_id mechanism triggers plugin ONLY when
      pay_id=666 fires. For non-trigger spins, the plugin returns [] from
      simulate_session and emit_extra_rounds gets an empty list.

      For the base round multi-payline rebuild: the plugin ALWAYS patches
      base_round in emit_extra_rounds, even for non-trigger spins. This
      requires simulate_session to return a non-empty list for EVERY spin
      so that emit_extra_rounds is called. We achieve this by setting
      trigger_pay_id=None (outcome-conditional mode) and having
      simulate_session() always return an M31Session (with freespin_outcomes=[]
      when no trigger).
    """

    # Use outcome-conditional trigger (trigger_pay_id=None) so simulate_session
    # is called on EVERY paid spin. The plugin then decides whether to:
    #   (a) emit FreeSpin rounds (if 3 Scatter in grid)
    #   (b) just rebuild the 5-payline base round (always)
    trigger_pay_id: int | None = None

    def __init__(
        self,
        spec: dict,
        symbols: SymbolRegistry,
        rules: RuleSet,
        evaluator: PaytableEvaluator,
        freespin_engine: SpinEngine,
        bet_amount: int = 1000,
    ) -> None:
        self._spec = spec
        self._symbols = symbols
        self._rules = rules
        self._evaluator = evaluator
        self._freespin_engine = freespin_engine
        self._bet_amount = bet_amount

    # ─── FeaturePlugin protocol ─────────────────────────────────────────

    def simulate_session(self, rng: Random, *, outcome: SpinOutcome | None = None) -> list[M31Session]:
        """Called after every paid spin (outcome-conditional mode).

        Examines the spin's grid for scatter count. If 3+ Scatter found,
        generates 7 FreeSpin outcomes. Always returns one M31Session so
        emit_extra_rounds is always called (to rebuild the 5-payline base round).

        Returns: [M31Session] always (never empty). The session carries:
          - base_grid for 5-payline re-evaluation
          - base_has_scatter flag
          - freespin_outcomes (7 items if triggered, [] otherwise)
        """
        if outcome is None:
            # Defensive: should always receive outcome in outcome-conditional mode
            return [M31Session(base_grid=[], base_has_scatter=False, freespin_outcomes=[])]

        grid = outcome.grid
        scatter_count = sum(1 for col in grid for sym in col if sym == _SCATTER_SYMBOL)
        has_trigger = scatter_count >= 3

        freespin_outcomes: list[SpinOutcome] = []
        if has_trigger:
            for _ in range(_FREESPIN_COUNT):
                fs_out = self._freespin_engine.spin(rng)
                freespin_outcomes.append(fs_out)

        return [M31Session(
            base_grid=grid,
            base_has_scatter=has_trigger,
            freespin_outcomes=freespin_outcomes,
        )]

    def emit_extra_rounds(
        self,
        base_round: dict,
        feature_rounds: list[M31Session],
        *,
        last_credits: int,
        spin_times: int,
        rtp_id: int,
        bet_amount: int,
    ) -> list[dict]:
        """Rebuild base_round with 5-payline data; emit FreeSpin rounds if triggered.

        Mutates base_round in-place (Python dict; caller's reference updates).
        Returns list of FreeSpin round dicts (empty if no trigger).
        """
        if not feature_rounds:
            return []

        session = feature_rounds[0]
        grid = session.base_grid

        if not grid:
            return []

        # Rebuild base round with 5 paylines + scatter
        pid_to_win, payout_by_payline, _ = self._evaluate_grid(grid, bet_amount)
        total_win = sum(pid_to_win.values())
        stops_by_col = ["-".join(col) + "-" for col in grid]
        reward_last_node = [f"{pid}-" for pid in sorted(pid_to_win.keys(), key=lambda x: int(x))]
        remarks = _REMARKS_TRIGGER if session.base_has_scatter else _REMARKS_NORMAL

        # Mutate base_round in-place to include 5-payline + scatter data
        base_round["WinCredits"] = total_win
        base_round["PayoutByPayline"] = payout_by_payline
        base_round["PayoutIdToWinAmount"] = pid_to_win
        base_round["StopSymbolsByCol"] = stops_by_col
        base_round["RewardLastNode"] = reward_last_node
        base_round["ReMarks"] = remarks

        if not session.base_has_scatter:
            return []

        # Emit 7 FreeSpin rounds
        running_credits = last_credits + total_win
        out: list[dict] = []
        for fs_out in session.freespin_outcomes:
            fs_pid_to_win, fs_payout_by_payline, _ = self._evaluate_grid(
                fs_out.grid, bet_amount
            )
            # FreeSpin has no Scatter — remove scatter pay_ids if present
            fs_pid_to_win.pop(str(_PAY_ID_SCATTER_WIN), None)
            fs_pid_to_win.pop(str(_PAY_ID_SCATTER_TRIGGER), None)
            fs_total_win = sum(fs_pid_to_win.values())
            fs_stops_by_col = ["-".join(col) + "-" for col in fs_out.grid]
            fs_reward = [f"{pid}-" for pid in sorted(fs_pid_to_win.keys(), key=lambda x: int(x))]
            rd = {
                "ReMarks": _REMARKS_FREE,
                "LastCredits": running_credits,
                "CostCredits": 0,
                "WinCredits": fs_total_win,
                "BetAmount": bet_amount,
                "ReelSkin": "",
                "StopSymbolsByCol": fs_stops_by_col,
                "RewardLastNode": fs_reward,
                "PayoutByPayline": fs_payout_by_payline,
                "PayoutGroupId": 0,
                "PayLineGroupId": 0,
                "PayoutIdToWinAmount": fs_pid_to_win,
                "CurJackpotStoreWin": 0,
                "SpinType": _ST_FREE,
                "SpinTimes": spin_times,
                "RTPId": rtp_id,
                "IsLackCreditsSpin": False,
            }
            out.append(rd)
            running_credits += fs_total_win
        return out

    def classify_round(
        self,
        round_dict: dict,
        next_round_dict: dict | None,
    ) -> tuple[str, int]:
        """Bucket a round into (feature_name, effective_win).

        ST=43 (paid base spin)  -> "NormalFreeSpin", win = WinCredits
        ST=44 (FreeSpin bonus)  -> "FreeSpin",       win = WinCredits
        """
        st = int(round_dict.get("SpinType", _ST_PAID))
        win = int(round_dict.get("WinCredits", 0) or 0)
        if st == _ST_FREE:
            return _FEATURE_FREE, win
        return _FEATURE_NORMAL, win

    # ─── Grid evaluation ────────────────────────────────────────────────

    def _evaluate_grid(
        self,
        grid: list[list[str]],
        bet_amount: int,
    ) -> tuple[dict[str, int], str, list[PayResult]]:
        """Evaluate all 5 paylines + scatter for a grid.

        Returns: (payout_id_to_win, payout_by_payline_str, all_results)

        Evaluation order per payline:
          1. Tier B (pure_wild / pure_wild_group) — evaluated by core evaluator
          2. Tier A (line_3_same) — evaluated by core evaluator
        Scatter: any-position count (pay_ids 12 + 666).
        """
        payout_id_to_win: dict[str, int] = {}
        payline_parts: list[str] = []
        all_results: list[PayResult] = []

        for line_idx, line_positions in enumerate(_PAYLINES):
            line_id = _LINE_IDS[line_idx]
            line_syms = [grid[c][r] for (c, r) in line_positions]
            result = self._evaluator.evaluate_payline(line_syms)
            if result is None:
                continue

            credits = self._pay_result_to_credits(result, bet_amount)
            pid_str = str(result.pay_id)
            payout_id_to_win[pid_str] = payout_id_to_win.get(pid_str, 0) + credits

            actual_positions = tuple(tuple(p) for p in line_positions)
            all_results.append(PayResult(
                pay_id=result.pay_id,
                multiplier=result.multiplier,
                positions=actual_positions,
            ))
            positions_str = "".join(
                f"{(c + 1) * 100 + (r - 1)}," for (c, r) in actual_positions
            )
            payline_parts.append(
                f"{line_id}:{result.pay_id}-{result.pay_id}({positions_str});  "
            )

        # Scatter: any-position count in 3x3 grid
        scatter_positions = [
            (c, r)
            for c, col in enumerate(grid)
            for r, sym in enumerate(col)
            if sym == _SCATTER_SYMBOL
        ]
        if len(scatter_positions) >= 3:
            sp_str = "".join(
                f"{(c + 1) * 100 + (r - 1)}," for (c, r) in scatter_positions
            )
            win_pid_str = str(_PAY_ID_SCATTER_WIN)
            trig_pid_str = str(_PAY_ID_SCATTER_TRIGGER)
            payout_id_to_win[win_pid_str] = (
                payout_id_to_win.get(win_pid_str, 0) + _SCATTER_WIN_CREDITS
            )
            payout_id_to_win[trig_pid_str] = payout_id_to_win.get(trig_pid_str, 0) + 0
            payline_parts.append(
                f"{_LINE_ID_SCATTER_WIN}:{_PAY_ID_SCATTER_WIN}-"
                f"{_PAY_ID_SCATTER_WIN}({sp_str});  "
            )
            payline_parts.append(
                f"{_LINE_ID_SCATTER_TRIGGER}:{_PAY_ID_SCATTER_TRIGGER}-"
                f"{_PAY_ID_SCATTER_TRIGGER}({sp_str});  "
            )

        payout_by_payline = "".join(payline_parts)
        return payout_id_to_win, payout_by_payline, all_results

    def _pay_result_to_credits(self, result: PayResult, bet_amount: int) -> int:
        """Convert PayResult.multiplier to absolute credits.

        Tier B (pay_ids 1-6): use _TIER_B_FIXED_CREDITS table.
          (These are fixed regardless of wild multipliers — verified in 01c §2.)
        Tier A (pay_ids 7-11): multiplier = (base_xbet * wild_product).
          credits = int(multiplier * bet_amount).
        Scatter: handled separately in _evaluate_grid.
        """
        pid = result.pay_id
        if pid in _TIER_B_FIXED_CREDITS:
            return _TIER_B_FIXED_CREDITS[pid]
        return int(result.multiplier * bet_amount)


def _build_freespin_engine(
    spec: dict,
    strips_doc: dict,
    weights_doc: dict,
) -> SpinEngine:
    """Build a SpinEngine for ST=44 FreeSpin rounds from freespin_reels."""
    freespin_strips = strips_doc.get("freespin_reels")
    if not freespin_strips:
        raise ValueError(
            "M31 reel_strips.json missing 'freespin_reels' key"
        )
    freespin_weights_lists = weights_doc.get("freespin_weights")
    if not freespin_weights_lists:
        raise ValueError(
            "M31 weights.json missing 'freespin_weights' key"
        )
    if len(freespin_strips) != len(freespin_weights_lists):
        raise ValueError(
            f"freespin_reels has {len(freespin_strips)} reels but "
            f"freespin_weights has {len(freespin_weights_lists)}"
        )

    reels: list[ReelStrip] = []
    for reel_idx, (strip, wts) in enumerate(
        zip(freespin_strips, freespin_weights_lists)
    ):
        if len(strip) != len(wts):
            raise ValueError(
                f"freespin reel {reel_idx + 1}: strip {len(strip)} stops "
                f"vs freespin_weights {len(wts)} stops"
            )
        stops = [Stop(symbol=s, weight=float(w)) for s, w in zip(strip, wts)]
        reels.append(ReelStrip(stops))

    symbols = SymbolRegistry(spec["symbols"])
    rules = RuleSet(spec["pays"])
    evaluator = PaytableEvaluator(symbols, rules, spec["evaluation_order"])
    paylines = spec["grid"]["paylines"]
    positions = [tuple(p) for p in paylines[0]["positions"]]

    return SpinEngine(
        reels=reels,
        evaluator=evaluator,
        payline_positions=positions,
        cost_per_spin=0,
        bet_amount=1000,
        spin_type=_ST_FREE,
        plugin=None,
    )


def build_plugin(spec_dict: dict, weights_doc: dict) -> M31FeaturePlugin | None:
    """Construct M31 plugin from spec.json + per-mode weights.json.

    Locates reel_strips.json relative to this plugin file's machine directory.
    Returns None when spec declares no features (defensive guard).
    """
    feats = spec_dict.get("features") or []
    if not feats:
        return None

    plugin_dir = Path(__file__).resolve().parent
    machine_dir = plugin_dir.parent
    strips_path = machine_dir / "reel_strips.json"
    if not strips_path.exists():
        raise FileNotFoundError(
            f"M31 plugin: reel_strips.json not found at {strips_path}"
        )
    strips_doc = _json.loads(strips_path.read_text(encoding="utf-8"))

    symbols = SymbolRegistry(spec_dict["symbols"])
    rules = RuleSet(spec_dict["pays"])
    evaluator = PaytableEvaluator(symbols, rules, spec_dict["evaluation_order"])
    freespin_engine = _build_freespin_engine(spec_dict, strips_doc, weights_doc)

    return M31FeaturePlugin(
        spec=spec_dict,
        symbols=symbols,
        rules=rules,
        evaluator=evaluator,
        freespin_engine=freespin_engine,
        bet_amount=1000,
    )
