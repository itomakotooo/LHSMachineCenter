"""M43 feature plugin — post-win Respin + post-spin MiniGame.

This plugin is an **outcome-conditional** FeaturePlugin (per
``core/engine/feature_protocol.py``): ``trigger_pay_id`` is ``None``,
so ``SpinEngine.spin_session`` calls ``simulate_session(rng,
outcome=...)`` after every paid spin and we decide internally.

Mechanics (from session_artifacts/M43/01c_field_analysis.md):
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
