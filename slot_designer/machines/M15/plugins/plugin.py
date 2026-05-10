"""M15 FeaturePlugin implementation — Top Dollar Feature Play.

Wraps the analytic / simulation primitives in ``feature.py`` (FeatureSpec
+ simulate_feature_session) into a FeaturePlugin-conforming class.

Contract: see core/engine/feature_protocol.py.

Production rawdata schema this plugin emits:
  - ST=14 per feature reveal round
       Fields: ReMarks="", LastCredits, CostCredits=0, WinCredits =
       reveal r_value × bet, BetAmount=0, StopSymbolsByCol=null,
       RewardLastNode=[], PayoutByPayline="", PayoutIdToWinAmount={},
       SpinTimes, RTPId.
  - ST=15 end marker (one per session)
       Fields: WinAmount = accepted r_value × bet, SpinTimes, RTPId,
       IsLackCreditsSpin=False. NOTE: WinAmount NOT WinCredits — the
       analyzer's Type-1 trigger session rule reads ``last_non_none
       WinCredits`` across the bonus sequence, so emitting WinCredits=0
       here would override the accepted ST=14 row's WinCredits and
       blank the feature's bucket distribution in the report.

Classification rules (Top Dollar production-verified):
  ST=1 (any ReMarks)            → "Normal", win = WinCredits
  ST=14 followed by another ST=14 → "TopDollarSelector", win = 0  (rejected reveal)
  ST=14 NOT followed by ST=14     → "TopDollar", win = WinCredits  (accepted final)
  ST=15                           → "TopDollarSelector", win = 0  (end marker)
"""
from __future__ import annotations

from random import Random
from typing import Any

from .feature import (
    FeatureRound,
    FeatureSpec,
    _X_POOL,
    _Y_POOL,
    simulate_feature_session,
)


class M15FeaturePlugin:
    """Top Dollar Feature Play plugin.

    Constructed from ``machines/M15/spec.json`` features[0] block plus
    a per-mode ``feature_params`` block in
    ``machines/M15/weights/mode_<N>/weights.json``. The per-mode block
    overrides spec-level defaults for x_count_weights / y_count_weights /
    x_value_weights / y_value_weights / accept_threshold / max_rounds.
    """

    # Feature name strings used in classify_round. Kept here (NOT in
    # core/) so the brand-name hardcode lives in the M15 plugin where
    # it belongs — the production schema emits these literal strings.
    _NAME_NORMAL = "Normal"
    _NAME_ACCEPTED = "TopDollar"
    _NAME_REJECTED_OR_END = "TopDollarSelector"

    # SpinType codes used for M15 feature sub-rounds + end marker.
    # These are hardcoded in the M15 production rawdata schema (verified
    # against M15$TopDollarSelector$0$ rawdata).
    _ST_FEATURE_ROUND = 14
    _ST_END_MARKER = 15

    def __init__(
        self,
        spec: FeatureSpec,
        *,
        trigger_pay_id: int | None,
    ) -> None:
        self._spec = spec
        self.trigger_pay_id: int | None = trigger_pay_id

    # ─── FeaturePlugin protocol ─────────────────────────────────────

    def simulate_session(self, rng: Random) -> list[FeatureRound]:
        return simulate_feature_session(self._spec, rng)

    def emit_extra_rounds(
        self,
        base_round: dict,
        feature_rounds: list[FeatureRound],
        *,
        last_credits: int,
        spin_times: int,
        rtp_id: int,
        bet_amount: int,
    ) -> list[dict]:
        if not feature_rounds:
            return []
        out: list[dict] = []
        for fr in feature_rounds:
            out.append(
                self._emit_feature_round(
                    fr,
                    bet_amount=bet_amount,
                    last_credits=last_credits,
                    spin_times=spin_times,
                    rtp_id=rtp_id,
                )
            )
        # WinAmount on end marker = accepted session's payout (last
        # round's r_value × bet).
        accepted_win = int(feature_rounds[-1].r_value * bet_amount)
        out.append(
            self._emit_feature_end(
                spin_times=spin_times,
                rtp_id=rtp_id,
                win_amount=accepted_win,
            )
        )
        return out

    def classify_round(
        self,
        round_dict: dict,
        next_round_dict: dict | None,
    ) -> tuple[str, int]:
        st = round_dict.get("SpinType", 1)
        win = int(round_dict.get("WinCredits", 0) or 0)
        if st == self._ST_FEATURE_ROUND:
            next_st = (
                next_round_dict.get("SpinType")
                if next_round_dict is not None
                else None
            )
            if next_st == self._ST_FEATURE_ROUND:
                # Followed by another reveal → rejected
                return self._NAME_REJECTED_OR_END, 0
            # Last reveal in the run → accepted
            return self._NAME_ACCEPTED, win
        if st == self._ST_END_MARKER:
            return self._NAME_REJECTED_OR_END, 0
        # Anything else (ST=1 paid spin, or unknown) → Normal
        return self._NAME_NORMAL, win

    # ─── internals ──────────────────────────────────────────────────

    def _emit_feature_round(
        self,
        fr: FeatureRound,
        *,
        bet_amount: int,
        last_credits: int,
        spin_times: int,
        rtp_id: int,
    ) -> dict:
        """Emit one ST=14 reveal sub-round dict."""
        return {
            "ReMarks": "",
            "LastCredits": last_credits,
            "CostCredits": 0,
            "WinCredits": int(fr.r_value * bet_amount),
            "BetAmount": 0,
            "StopSymbolsByCol": None,
            "RewardLastNode": [],
            "PayoutByPayline": "",
            "PayoutIdToWinAmount": {},
            "SpinType": self._ST_FEATURE_ROUND,
            "SpinTimes": spin_times,
            "RTPId": rtp_id,
        }

    def _emit_feature_end(
        self,
        *,
        spin_times: int,
        rtp_id: int,
        win_amount: int = 0,
    ) -> dict:
        """Emit the ST=15 end marker dict."""
        return {
            "WinAmount": int(win_amount),
            "SpinType": self._ST_END_MARKER,
            "SpinTimes": spin_times,
            "RTPId": rtp_id,
            "IsLackCreditsSpin": False,
        }


# ─────────────────────────────────────────────────────────────────────
# build_plugin factory
# ─────────────────────────────────────────────────────────────────────

def build_plugin(spec_dict: dict, weights_doc: dict) -> M15FeaturePlugin | None:
    """Construct an M15 plugin from spec.json + per-mode weights.json.

    Returns None when the spec doesn't declare features (defensive —
    M15 always declares features but the contract for the FeaturePlugin
    interface is "return None for base-only").
    """
    feats = spec_dict.get("features") or []
    if not feats:
        return None
    feat = feats[0]
    fp = weights_doc.get("feature_params") or {}
    x_count = fp.get("x_count_weights") or feat.get("x_count_weights")
    y_count = fp.get("y_count_weights") or feat.get("y_count_weights")
    x_val = fp.get("x_value_weights") or feat.get("x_value_weights")
    y_val = fp.get("y_value_weights") or feat.get("y_value_weights")
    thresh = fp.get("accept_threshold") or feat.get("accept_threshold", 40)
    max_r = fp.get("max_rounds") or feat.get("max_rounds", 4)
    if not (x_count and y_count):
        return None

    spec = FeatureSpec(
        x_count_weights=tuple(x_count),
        y_count_weights=tuple(y_count),
        x_value_weights=tuple(x_val) if x_val else (1.0,) * len(_X_POOL),
        y_value_weights=tuple(y_val) if y_val else (1.0,) * len(_Y_POOL),
        accept_threshold=float(thresh),
        max_rounds=int(max_r),
    )
    return M15FeaturePlugin(spec, trigger_pay_id=feat.get("trigger_pay_id"))
