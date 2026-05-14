"""M43 feature plugin — post-win Respin + post-spin MiniGame +
pay_id 8 wild_blank_special + pay_id 9 consolation wild doubling.

This plugin is an **outcome-conditional** FeaturePlugin (per
``core/engine/feature_protocol.py``): ``trigger_pay_id`` is ``None``,
so ``SpinEngine.spin_session`` calls ``simulate_session(rng,
outcome=...)`` after every paid spin and we decide internally.

Mechanics (from session_artifacts/M43/01c_field_analysis.md +
01c_supp_pay_id_8.md + 01c_supp_doubling_correction.md):

  - **Off-payline wild — NO additional doubling** — the original 01c §3
    claim that "extra wild on adjacent row doubles the bar pay" was
    disproved empirically at Stage 2.5. Bar/7 pays (pay_ids 2-7) use
    standard evaluator ``wild_product`` only: literal ``wild`` on payline
    gives 2× via wild.multiplier=2; ``blankup``/``blankdown`` on payline
    have multiplier=1 (adjacency markers, not doubling agents). See
    ``01c_supp_doubling_correction.md`` for full derivation.
    No post-eval doubling is applied for bar/7 pays.

  - **Pay_id 8 wild_blank_special** — fires when payline has exactly 2
    wild-family cells (wild/blankup/blankdown) + 1 plain blank
    (predicate B_v2). Overrides any prior pay_id 9 false-positive from
    ``side_wild_alone`` evaluator.
    Multiplier: ``5 × 2^(window_wf_count - 4) × bet`` where
    ``window_wf_count`` is wild-family count across all 9 cells.
    Valid range window_wf_count ∈ {4, 5, 6}.
    Confidence: HIGH (01c_supp §5 — 100% hit coverage, 0 FP on 650k).

  - **Pay_id 9 consolation wild doubling** — when ``side_wild_alone``
    evaluator returns pay_id 9 (2×) AND a literal ``wild`` (not
    blankup/blankdown) is on the payline mid-row, the result is doubled
    to 4×. When only blankup/blankdown appears on the payline, result
    stays 2× (no doubling). Empirical basis: chunk_0001-0003 (~47k
    spins). See ``01c_supp_doubling_correction.md`` §3.

  - **Respin (SpinType=50, ReelSkin=6, CostCredits=0, ReMarks='ReSpin')**
    Triggered after some fraction of base-spin wins (rate ~1.32% of
    paid rounds, ~10% of base wins). LOW confidence on exact predicate.
    Implementation: best-guess "p(respin | base_win) = 10%" applied
    uniformly to ALL paid wins regardless of pay_id. Stage 6 must refit.
    Respin re-samples reels via a separate SpinEngine constructed from
    ``respin_strips.json`` weights (skinId 6 in M43Reel.xlsx). Same
    paytable / evaluator as base.

  - **MiniGame (SpinType=51, reduced 7-key schema, ReMarks='MiniGame[t1,t2,...]')**
    Triggered after ANY paid spin probabilistically (rate ~1.05% per
    paid round). Independent of base win. LOW confidence on exact
    predicate. Implementation: best-guess uniform probability.
    Token sequence length sampled from empirical distribution; tokens
    sampled iid from empirical token distribution. WinCredits =
    sum(token_to_xbet[tk] * bet) for tokens in the sequence.

Production-emitted rounds match the 17-key envelope for SpinType=1/50
(via ``emit_round``) and the 7-key reduced envelope for SpinType=51
(emitted directly here).

Classification (analyzer-side):
  ST=1                                 → "Normal"
  ST=50 (respin)                       → "ReSpin"
  ST=51 (mini-game)                    → "MiniGame"

Stage 6 fit markers (see grep TODO Stage 6):
  - respin trigger predicate (currently 10% of base wins)
  - mini-game trigger predicate (currently 1.05% of all paid rounds)
  - mini-game length distribution (Stage 6 may refit per-length token bias)
"""
from __future__ import annotations

import json
from pathlib import Path
from random import Random
from typing import Any

from slot_designer.core.emitter.round import emit_round
from slot_designer.core.engine.evaluator import PaytableEvaluator
from slot_designer.core.engine.reel_strip import ReelStrip, Stop
from slot_designer.core.engine.rules import RuleSet
from slot_designer.core.engine.spin import SpinEngine
from slot_designer.core.engine.symbol import SymbolRegistry


# SpinType codes for M43 feature sub-rounds. Hardcoded here (not in core/)
# per ARCHITECTURE §7 forbidden-zone rule — production rawdata schema
# verified at ``rawdata/M43/mode_1/chunk_*.json``.
_ST_RESPIN = 50
_ST_MINIGAME = 51

# ReelSkin id for respin rounds (xlsx M43Reel skinId 6).
_RESPIN_REEL_SKIN = 6

# Classification feature names. Kept inside the plugin (forbidden zone
# rule per ARCHITECTURE §7).
_NAME_NORMAL = "Normal"
_NAME_RESPIN = "ReSpin"
_NAME_MINIGAME = "MiniGame"

# ─── M43-specific pay_id and symbol sets ───────────────────────────────
# pay_id 8 — "wild_blank_special" (HIGH confidence per 01c_supp §5)
_PAY_ID_8 = 8

# Wild-family symbols: used for pay_id 8 predicate + window_wf_count.
# blankup/blankdown are adjacency MARKERS (not real wilds) but still
# count as wild-family for the pay_id 8 trigger and multiplier formula.
_WF_SYMBOLS: frozenset[str] = frozenset({"wild", "blankup", "blankdown"})

# Literal "wild" is distinct from blankup/blankdown adjacency markers.
# Used to test whether a payline cell carries a true doubling wild
# (for pay_id 9 Rule C) vs a non-doubling adjacency marker.
# Per 01c_supp_doubling_correction.md: bar pays use standard wild_product
# only; off-payline wilds do NOT trigger additional doubling.
_LITERAL_WILD = "wild"

# Pay_id 8 payout lookup: window_wf_count → base multiplier.
# Formula: 5 * 2^(window_wf_count - 4).  Valid range {4, 5, 6}.
# Source: 01c_supp_pay_id_8.md §5 + §8 (HIGH confidence, 100% match on
# all 829 production hits).
_PAY_ID_8_MULT: dict[int, int] = {4: 5, 5: 10, 6: 20}

# Row indices in the 3-column grid (grid[col][row]).
_ROW_TOP = 0
_ROW_MID = 1
_ROW_BOT = 2

# Payline is mid-row only: all 3 columns, row=1.
_PAYLINE_CELLS: frozenset[tuple[int, int]] = frozenset(
    {(0, _ROW_MID), (1, _ROW_MID), (2, _ROW_MID)}
)


def _count_window_wf(grid: list[list[str]]) -> int:
    """Count wild-family symbols (wild/blankup/blankdown) across ALL 9
    cells of the 3×3 grid.  Used for pay_id 8 multiplier formula.
    """
    return sum(
        1
        for col in grid
        for sym in col
        if sym in _WF_SYMBOLS
    )


def _count_payline_literal_wilds(payline_syms: list[str]) -> int:
    """Count literal ``wild`` symbols (not blankup/blankdown) on the payline.

    Used for pay_id 9 doubling rule: when literal wild is on the payline
    mid-row, the standard side_wild_alone pay (2×) is doubled to 4×.
    """
    return sum(1 for s in payline_syms if s == _LITERAL_WILD)


_PAY_ID_9 = 9  # side_wild_alone pay — doubled when literal wild on payline


def _apply_payline_post_eval(outcome) -> None:
    """M43-specific payline post-evaluator — mutates ``outcome.pay``
    in-place based on the full 3×3 grid.

    Three rules in order of priority (established from production rawdata
    chunk analysis, 650k spins, validated against 01c_supp_pay_id_8.md):

    Rule B (highest priority) — pay_id 8 wild_blank_special:
      When payline has exactly 2 wild-family cells (wild/blankup/blankdown)
      + 1 plain blank (predicate B_v2), assign pay_id 8.
      This OVERRIDES any prior standard pay (specifically: the
      ``side_wild_alone`` evaluator fires pay_id 9 for n_wf>=1 on the
      payline, which incorrectly fires for the n_wf==2 case too — we
      must override it here).
      Multiplier: 5 × 2^(window_wf_count - 4) × bet.
      Valid range window_wf_count ∈ {4, 5, 6}.
      Confidence: HIGH (01c_supp §5 — 100% hit coverage, 0 FP on 650k).

    Rule C — pay_id 9 consolation wild doubling:
      When standard evaluator returned pay_id 9 (side_wild_alone, 2×)
      AND a literal ``wild`` (not blankup/blankdown) is on the payline,
      double the win from 2× to 4×.
      Production evidence (chunk_0001-0003, ~47k spins; blankup and
      blankdown treated as equivalent per 01c §1 strip structure):
        4× pay_id 9: ALWAYS has literal wild on payline
        2× pay_id 9: ALWAYS has blankup or blankdown (no literal wild) on payline
      This is because when wild is at mid-row, blankdown appears at top
      and blankup appears at bottom — these off-payline markers ARE the
      adjacent-wild bonus that doubles the consolation.
      When only blankup/blankdown is at mid-row, the wild they represent
      is already accounted for as the consolation marker; no extra doubling.

    Rule A — bar/7 pay doubling (already handled by standard evaluator):
      When a literal ``wild`` is ON the payline as part of a bar/7 3-match
      pay (pay_ids 2-7), the standard evaluator ALREADY applies 2× via
      wild.multiplier=2 in ``wild_product``.
      ``blankup``/``blankdown`` on the payline have multiplier=1 (correct:
      they are adjacency markers that substitute but don't double).
      Production confirms: pay_id 6 at 10× uses blankup/blankdown;
      pay_id 6 at 20× uses literal wild on payline.
      NO additional post-eval doubling needed for bar/7 pays — standard
      evaluator handles the wild-on-payline case correctly.

    No-op case — when none of the above rules apply:
      outcome.pay is left as returned by the standard evaluator (including
      None if no pay).

    Implementation note on Rule B priority over pay_id 9:
      In spec.json ``blankup``/``blankdown`` have ``kind: "wild"`` (they
      ARE wild symbols for substitution purposes).  The ``side_wild_alone``
      evaluator fires pay_id 9 whenever any wild-family symbol appears on
      the payline — this correctly covers n_wf==1, but ALSO fires when
      n_wf==2 (the pay_id 8 case).  Production rawdata shows n_wf==2 is
      always pay_id 8, never pay_id 9 (0 false positives in 649,171 non-
      pay_id-8 rounds per 01c_supp §6).  So Rule B must take priority.

    ``outcome`` is a ``SpinOutcome`` dataclass (not frozen — mutable).
    """
    from slot_designer.core.engine.rules import PayResult

    grid = outcome.grid
    payline_syms = [grid[c][_ROW_MID] for c in range(len(grid))]

    n_wf = sum(1 for s in payline_syms if s in _WF_SYMBOLS)
    n_blank = sum(1 for s in payline_syms if s == "blank")

    # ── Rule B: pay_id 8 (highest priority) ──────────────────────────
    # Fires when payline = exactly 2 wild-family + 1 plain blank.
    # Overrides standard pay (pay_id 9 false-positive when n_wf==2).
    if n_wf == 2 and n_blank == 1:
        # Predicate B_v2 matched.  The non-wf, non-blank payline cells can
        # only be plain blank (guaranteed: if a bar/7 were present the
        # standard evaluator would have returned a bar/seven pay AND
        # n_wf+n_blank would be < 3 for a 3-cell payline — contradiction).
        window_wf = _count_window_wf(grid)
        mult = _PAY_ID_8_MULT.get(window_wf)
        if mult is None:
            # Defensive: window_wf outside expected {4,5,6}.  Log error
            # and use minimum tier (5×) rather than crashing.
            import logging
            logging.getLogger(__name__).error(
                "M43 pay_id 8: unexpected window_wf_count=%d "
                "(expected 4/5/6); payline=%r grid=%r — "
                "falling back to mult=5 (TODO: report to main session)",
                window_wf, payline_syms, grid,
            )
            mult = 5  # minimum tier fallback
        outcome.pay = PayResult(
            pay_id=_PAY_ID_8,
            multiplier=mult,
            positions=tuple((c, _ROW_MID) for c in range(len(grid))),
        )
        return  # Rule B fired; rules A/C do not apply.

    # ── Rule C: pay_id 9 consolation wild doubling ────────────────────
    # Standard side_wild_alone pays 2× regardless of wild type on payline.
    # When literal wild (not blankup/blankdown) is on the payline, the
    # production result is 4× (the adjacent blankdown/blankup markers in
    # the top/bot rows function as bonus indicators).
    if (outcome.pay is not None
            and outcome.pay.pay_id == _PAY_ID_9
            and _count_payline_literal_wilds(payline_syms) > 0):
        outcome.pay = PayResult(
            pay_id=outcome.pay.pay_id,
            multiplier=outcome.pay.multiplier * 2,
            positions=outcome.pay.positions,
        )
        return  # Rule C fired; Rule A does not apply.


class M43FeaturePlugin:
    """Lucky-Ducky-style post-win Respin + post-spin MiniGame.

    Constructed from spec.json + mode weights + plugin-side respin
    strips + mini_game_params. Carries a private ``_respin_engine``
    for re-sampling reels with skinId-6 weights during ReSpin events.
    """

    # FeaturePlugin Protocol: ``trigger_pay_id is None`` selects the
    # outcome-conditional trigger mode (added 2026-05-14 for M43).
    trigger_pay_id: int | None = None

    def __init__(
        self,
        *,
        respin_engine: SpinEngine,
        respin_trigger_prob_given_base_win: float,
        minigame_trigger_prob: float,
        minigame_token_to_xbet: dict[int, int],
        minigame_length_dist: list[tuple[int, float]],
        minigame_token_dist: list[tuple[int, float]],
    ) -> None:
        self._respin_engine = respin_engine
        # TODO Stage 6 fit — respin trigger predicate (currently 10% of
        # base-spin wins). True predicate from rawdata is opaque per
        # 01c §5 (LOW confidence). Refit at Stage 6 against tuned weights.
        self._respin_p = float(respin_trigger_prob_given_base_win)
        # TODO Stage 6 fit — mini-game trigger predicate (currently
        # 1.05% of all paid rounds). True predicate is opaque per 01c §6
        # (LOW confidence). Refit at Stage 6.
        self._mg_p = float(minigame_trigger_prob)
        self._mg_token_to_xbet = dict(minigame_token_to_xbet)
        # Pre-decompose length / token distributions into parallel lists
        # for ``rng.choices``.
        self._mg_lengths = [int(L) for L, _ in minigame_length_dist]
        self._mg_length_weights = [float(p) for _, p in minigame_length_dist]
        self._mg_tokens = [int(t) for t, _ in minigame_token_dist]
        self._mg_token_weights = [float(p) for _, p in minigame_token_dist]

    # ─── FeaturePlugin Protocol ──────────────────────────────────────

    def simulate_session(self, rng: Random, *, outcome=None) -> list[dict]:
        """Decide whether to fire Respin / MiniGame for this paid spin.

        Returns plugin-private feature-round descriptors as a list of
        dicts. Each descriptor carries a ``kind`` ("respin" or
        "minigame") and the data needed by ``emit_extra_rounds`` to
        produce the rawdata round dict.

        Best-guess trigger logic (Stage 6 must refit):
          - Respin: fires with prob ``_respin_p`` if the paid spin had
            a non-zero ``WinCredits``-equivalent payout (via
            ``outcome.pay`` non-None). Predicate per 01c §5 LOW
            confidence.
          - MiniGame: fires with prob ``_mg_p`` on EVERY paid spin
            (independent of base win) per 01c §6.

        Multiple features may fire in the same paid round (both possible
        but rare).
        """
        if outcome is None:
            return []

        # ── Stage 2.5: apply M43-specific payline post-evaluation ──
        # Mutates outcome.pay in-place before any respin/minigame logic.
        # Must run first so that:
        #   - off-payline wild doubling is reflected in WinCredits
        #   - pay_id 8 fires (and is treated as a "win" for respin trigger)
        _apply_payline_post_eval(outcome)

        sessions: list[dict] = []
        base_won = outcome.pay is not None

        # 1. Respin: post-win.
        if base_won and rng.random() < self._respin_p:
            respin_outcome = self._respin_engine.spin(rng)
            sessions.append({
                "kind": "respin",
                "outcome": respin_outcome,
            })

        # 2. MiniGame: post-spin (independent).
        if rng.random() < self._mg_p:
            length = rng.choices(self._mg_lengths, self._mg_length_weights, k=1)[0]
            tokens = rng.choices(
                self._mg_tokens, self._mg_token_weights, k=length,
            )
            sessions.append({
                "kind": "minigame",
                "tokens": list(tokens),
            })

        return sessions

    def emit_extra_rounds(
        self,
        base_round: dict,
        feature_rounds: list[dict],
        *,
        last_credits: int,
        spin_times: int,
        rtp_id: int,
        bet_amount: int,
    ) -> list[dict]:
        """Convert each feature-round descriptor into a rawdata round dict.

        Respin rounds use the full 17-key envelope (via emit_round) with
        ReelSkin=6, CostCredits=0, ReMarks='ReSpin'.

        MiniGame rounds use the reduced 7-key envelope:
          {IsLackCreditsSpin, LastCredits, RTPId, ReMarks, SpinTimes,
           SpinType, WinCredits}
        """
        out: list[dict] = []
        # Track last_credits across emitted rounds; respin updates it
        # (free spin → credits += win).
        running_credits = int(last_credits)
        for fr in feature_rounds:
            kind = fr["kind"]
            if kind == "respin":
                respin_outcome = fr["outcome"]
                round_dict = emit_round(
                    respin_outcome,
                    last_credits=running_credits,
                    spin_times=spin_times,
                    rtp_id=rtp_id,
                    remarks="ReSpin",
                )
                # Production: respin emits ReelSkin=6 + CostCredits=0
                # (already 0 from spin engine's cost_per_spin=0).
                round_dict["ReelSkin"] = _RESPIN_REEL_SKIN
                round_dict["CostCredits"] = 0
                round_dict["SpinType"] = _ST_RESPIN
                round_dict["BetAmount"] = bet_amount
                running_credits += int(round_dict.get("WinCredits", 0) or 0)
                out.append(round_dict)
            elif kind == "minigame":
                tokens = fr["tokens"]
                win = sum(self._mg_token_to_xbet[t] * bet_amount for t in tokens)
                running_credits += int(win)
                # Reduced 7-key envelope per 01c §6 + §8.
                out.append({
                    "IsLackCreditsSpin": False,
                    "LastCredits": running_credits - int(win),
                    "RTPId": rtp_id,
                    "ReMarks": "MiniGame[" + ",".join(str(t) for t in tokens) + "]",
                    "SpinTimes": spin_times,
                    "SpinType": _ST_MINIGAME,
                    "WinCredits": int(win),
                })
            else:  # pragma: no cover - defensive
                raise ValueError(f"unknown M43 feature-round kind: {kind!r}")
        return out

    def classify_round(
        self,
        round_dict: dict,
        next_round_dict: dict | None,
    ) -> tuple[str, int]:
        """Bucket a single round into a feature_name + effective_win.

        Per ``memory/feedback_session_semantics.md``: respin/mini-game
        wins attribute to the triggering paid round. The analyzer's
        session-centric aggregation handles that; per-row classification
        here just labels the feature name correctly.
        """
        del next_round_dict
        st = int(round_dict.get("SpinType", 1) or 1)
        win = int(round_dict.get("WinCredits", 0) or 0)
        if st == _ST_RESPIN:
            return _NAME_RESPIN, win
        if st == _ST_MINIGAME:
            return _NAME_MINIGAME, win
        return _NAME_NORMAL, win


# ─────────────────────────────────────────────────────────────────────
# Respin engine construction — same paytable as base, different strips.
# ─────────────────────────────────────────────────────────────────────

def _load_respin_strips(strips_path: Path) -> tuple[list[list[str]], list[list[int]]]:
    """Load respin reel layout + weights.

    Strips byte-identical to base reel_strips.json (M43 cross-skin
    invariant per 01c §1); weights from xlsx skinId 6.
    """
    base_strips_path = strips_path.parent.parent / "reel_strips.json"
    strips_doc = json.loads(base_strips_path.read_text(encoding="utf-8"))
    respin_doc = json.loads(strips_path.read_text(encoding="utf-8"))
    return strips_doc["reels"], respin_doc["weights"]


def _build_respin_engine(spec_dict: dict, plugin_dir: Path) -> SpinEngine:
    """Construct a SpinEngine that re-samples base reels with respin
    weights (skinId 6) and re-uses the base paytable.

    Cost per spin = 0 (free spin). Spin type set to 50 by emit override
    in ``emit_extra_rounds`` (engine's spin_type field is the base
    paid spin type; we don't use it here).
    """
    strips_layout, respin_weights = _load_respin_strips(
        plugin_dir / "respin_strips.json"
    )
    assembled: list[list[dict]] = []
    for strip, wts in zip(strips_layout, respin_weights):
        assembled.append([
            {"symbol": s, "weight": float(w)} for s, w in zip(strip, wts)
        ])

    symbols = SymbolRegistry(spec_dict["symbols"])
    rules = RuleSet(spec_dict["pays"], reroll_blocks=spec_dict.get("reroll_blocks"))
    evaluator = PaytableEvaluator(symbols, rules, spec_dict["evaluation_order"])

    reels = [ReelStrip([Stop(symbol=s["symbol"], weight=s["weight"]) for s in row])
             for row in assembled]

    # Single payline (mid row) — same as base.
    paylines = spec_dict["grid"]["paylines"]
    positions = [tuple(p) for p in paylines[0]["positions"]]

    return SpinEngine(
        reels=reels,
        evaluator=evaluator,
        payline_positions=positions,
        cost_per_spin=0,
        bet_amount=int(spec_dict["spin_types"]["1"]["bet_amount"]),
        spin_type=_ST_RESPIN,
        plugin=None,  # respin engine never recurses into another feature.
    )


def build_plugin(spec_dict: dict, weights_doc: dict) -> M43FeaturePlugin | None:
    """Construct an M43 plugin from spec.json + per-mode weights.

    Returns None when spec doesn't declare features (defensive).
    """
    del weights_doc  # M43 plugin parameters live in mini_game_params.json
                    # (alongside the plugin code) rather than per-mode
                    # weights.json. This keeps Stage 6 weight-tuning
                    # decoupled from plugin parameter tuning.
    feats = spec_dict.get("features") or []
    if not feats:
        return None

    plugin_dir = Path(__file__).resolve().parent
    mg_params = json.loads(
        (plugin_dir / "mini_game_params.json").read_text(encoding="utf-8")
    )
    respin_engine = _build_respin_engine(spec_dict, plugin_dir)

    return M43FeaturePlugin(
        respin_engine=respin_engine,
        # TODO Stage 6 fit — respin trigger predicate. Currently
        # "10% of base-spin wins" derived from observed 1.32% paid-round
        # rate / 13.3% base-win rate ≈ 9.9% per 01c §5. Predicate exact
        # rule LOW confidence (could be pay_id-threshold or pattern-
        # specific, not random).
        respin_trigger_prob_given_base_win=0.099,
        minigame_trigger_prob=float(mg_params["trigger_prob"]),
        minigame_token_to_xbet={
            int(k): int(v) for k, v in mg_params["token_to_xbet"].items()
        },
        minigame_length_dist=[
            (int(L), float(p)) for L, p in mg_params["length_distribution"]
        ],
        minigame_token_dist=[
            (int(tk), float(p)) for tk, p in mg_params["token_distribution"].items()
        ],
    )
