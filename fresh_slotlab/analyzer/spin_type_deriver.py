"""Data-driven SpinType mechanism classifier (refactor core).

Replaces the hand-declared `role` with a classification DERIVED per (machine, ST)
from observable rawdata. Three orthogonal axes:

  mechanism  -- WHAT the SpinType is (selects which feature-dimension plugin runs).
                Derived from field signature + ReMarks pattern + win channel.
  economy    -- paid vs free. Derived from CostCredits/BetAmount (recognises the
                legacy cost-echo-unreliable lock-respin case + WinAmount settlements).
  position   -- base (main/paid loop) vs feature (triggered by another ST).

Precise signals validated 2026-06-18 against the fleet + adversarial cross-check
(see the disagreement audit). Notable traps the rules encode:
  * A "TriggerFreespin"/"TriggerRespin" ReMarks on a COST-BEARING spin is a TRIGGER
    MARKER for what it spawns, NOT that spin's own mechanism -> classify by signature,
    require an actual free-session COUNTER ("Freespin <N>") for `freespin`.
  * hold_respin requires PERSISTENT per-position held state (coin-position JSON that
    accumulates across rounds), NOT merely the word "respin".
  * A settlement paying via the WinAmount field has WinCredits==0 -> it is NOT a
    zero-win `state`. Win presence checks BOTH WinCredits and WinAmount.
  * "MoveSpin"/"move", empty-ReMarks RedHotRespin, and run-until-blank are all real
    `respin` (cost=0 + new reel outcome + subordinate to a paid base in the SpinTimes).

This module is import-side-effect-free and base-EXCLUDED (no closure file imports it).
"""
from __future__ import annotations
import copy
import re
from collections import Counter
from typing import Any

_COIN_JSON = re.compile(r'\{\s*"?\d+"?\s*:\s*\[')        # {"500":[2804] ...  held-coin state
_FREESPIN_WORD = re.compile(r'free\s*spin', re.I)         # "FreeSpin" / "Freespin 3" (free session)
_TRIGGER_PREFIX = re.compile(r'^\s*trigger', re.I)        # "Trigger Minigame" -- a marker, not the mechanism
_SELECTOR_FIELDS = {"DollarCount", "ChosenDollar", "OfferValue"}
_LOCK_FIELDS = ("LockLines", "LockReels", "LockReel", "HoldReels", "LockPositions")

VALID_MECHANISMS = (
    "selector", "hold_respin", "freespin", "respin",
    "wheel", "minigame", "state", "normal",
)


def _num(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def new_signals() -> dict:
    """An empty signal accumulator for streaming (memory-light over huge STs)."""
    return {
        "n": 0, "cost_pos": 0, "bet_pos": 0,
        "win_wc": 0, "win_wa": 0, "zero_win": 0,
        "coin_json": 0, "new_reel": 0, "lock_pop": 0,
        "lock_grows": 0,     # rounds where the held set GROWS vs the prev round of the same burst
        "echo_cost": 0,      # cost-bearing rounds whose wallet delta == win (cost is a per-record echo)
        "fields": set(), "remarks": Counter(),
        "_last_spt": None, "_last_lockn": 0,   # sequence state for accumulation
    }


def _lock_count(r: dict) -> int:
    for lf in _LOCK_FIELDS:
        v = r.get(lf)
        if v not in (None, "", [], {}, "[]", "{}"):
            return len(re.findall(r"\d+", str(v)))
    return 0


def fold_round(sig: dict, r: dict, prev_last_credits: float | None = None) -> None:
    """Fold ONE round into a signal accumulator (mutates ``sig``). ``prev_last_credits``
    is the wallet (LastCredits) AFTER the immediately preceding round in sequence; pass it
    to detect echo-cost (a free spin whose CostCredits is a per-record echo, M104/M96 class)."""
    sig["n"] += 1
    cost = _num(r.get("CostCredits"))
    bet = _num(r.get("BetAmount"))
    if cost > 0:
        sig["cost_pos"] += 1
    if bet > 0:
        sig["bet_pos"] += 1
    wc = _num(r.get("WinCredits"))
    wa = _num(r.get("WinAmount"))
    if wc > 0:
        sig["win_wc"] += 1
    if wa > 0:
        sig["win_wa"] += 1
    if wc <= 0 and wa <= 0:
        sig["zero_win"] += 1
    # echo-cost: a charged spin moves the wallet by (win - cost); an echo (free) spin moves it
    # by (win) only. delta == win  =>  cost was not actually charged.
    if cost > 0 and prev_last_credits is not None:
        delta = _num(r.get("LastCredits")) - prev_last_credits
        if abs(delta - wc) < 0.5:
            sig["echo_cost"] += 1
    rm = str(r.get("ReMarks") or "")
    if rm and len(sig["remarks"]) < 64:        # cap remarks vocabulary (memory bound)
        sig["remarks"][rm[:40]] += 1
    elif rm and rm[:40] in sig["remarks"]:
        sig["remarks"][rm[:40]] += 1
    if _COIN_JSON.search(rm):
        sig["coin_json"] += 1
    if r.get("StopSymbolsByCol") not in (None, "", [], {}):
        sig["new_reel"] += 1
    lockn = _lock_count(r)
    if lockn > 0:
        sig["lock_pop"] += 1       # a held reel/line/coin position is populated this round
        # accumulation: within the SAME respin burst (same SpinTimes), does the held set grow?
        spt = r.get("SpinTimes")
        if spt is not None and spt == sig["_last_spt"] and lockn > sig["_last_lockn"]:
            sig["lock_grows"] += 1
        sig["_last_spt"] = spt
        sig["_last_lockn"] = lockn
    for k, v in r.items():
        if v not in (None, "", [], {}, "[]", "{}"):
            sig["fields"].add(k)


def aggregate_st_signals(rounds: list[dict]) -> dict:
    """Reduce all rounds of ONE (machine, ST) to the signals the rules need. Rounds must be
    in original order so the lock-accumulation + echo-cost (wallet-delta) signals work."""
    sig = new_signals()
    prev_lc = None
    for r in rounds:
        fold_round(sig, r, prev_last_credits=prev_lc)
        prev_lc = _num(r.get("LastCredits"))
    return sig


def _remarks_has(sig: dict, *needles: str) -> bool:
    blob = " ".join(sig["remarks"].keys()).lower()
    return any(nd.lower() in blob for nd in needles)


def _remarks_re(sig: dict, rx: re.Pattern) -> bool:
    return any(rx.search(k) for k in sig["remarks"])


def derive_mechanism(sig: dict) -> tuple[str, float, str]:
    """Return (mechanism, confidence, evidence). Ordered, first-match; precise signals
    validated against the fleet 2026-06-18. A confidence < MIN_CONFIDENCE means the data
    is genuinely ambiguous -> the gate routes it to domain sign-off, never a silent guess."""
    f = sig["fields"]
    n = max(sig["n"], 1)
    # free = the ST is never cost-bearing. (A per-record CostCredits ECHO on a truly-free spin
    # -- the M104/M96 class -- is NOT detectable here via the wallet delta: large LastCredits
    # values lose the cost in float precision. That economy call is left to the parser's is_paid
    # / cost_credits_unreliable logic; the deriver does not reimplement it.)
    cost0 = sig["cost_pos"] == 0
    win = sig["win_wc"] + sig["win_wa"]
    reel = sig["new_reel"] / n
    coin = sig["coin_json"] / n
    lock = sig["lock_pop"] / n
    lock_grows = sig["lock_grows"] / n
    has_remarks = bool(sig["remarks"])
    # respin marker = the spin's OWN mechanism ("respin"/"move"/"nudge"), NOT a trigger marker
    # ("TriggerRespin" on a paid base spawns a respin elsewhere -- the base is not itself a respin).
    respin_word = any(
        (("respin" in k.lower() or "move" in k.lower()
          or "redhot" in k.lower() or "nudge" in k.lower())
         and not _TRIGGER_PREFIX.search(k))
        for k in sig["remarks"]
    )

    # 1. selector (TopDollar pick offer)
    if _SELECTOR_FIELDS & f:
        return "selector", 0.95, "DollarCount/ChosenDollar/OfferValue present"
    # 2. freespin granted session: any "FreeSpin"/"Freespin N" word on a FREE spin.
    #    (counter precedence over held-state: a freespin that also holds symbols is a freespin.)
    if cost0 and _remarks_re(sig, _FREESPIN_WORD):
        return "freespin", 0.9, "ReMarks 'FreeSpin' on a free (cost=0) spin"
    # 3. hold_respin (high conf): PERSISTENT per-position held-COIN state.
    if cost0 and coin >= 0.5:
        return "hold_respin", 0.92, f"persistent coin-position JSON ({sig['coin_json']}/{n})"
    # 4. wheel settlement
    if _remarks_has(sig, "wheelspin"):
        return "wheel", 0.9, "ReMarks 'WheelSpin'"
    # 5. minigame settlement: 'MiniGame' on a FREE win-bearing spin (cost=0 excludes a paid
    #    base whose ReMarks merely say 'Trigger Minigame').
    if cost0 and win > 0 and _remarks_has(sig, "minigame", "cellindex") and not _remarks_re(sig, _TRIGGER_PREFIX):
        return "minigame", 0.85, "ReMarks 'MiniGame/CellIndex' + free + win-bearing"
    # 6. bare / WinAmount settlement: free, win-bearing, NO fresh reel of its own, no held state.
    if cost0 and win > 0 and reel < 0.5 and coin == 0 and lock == 0:
        return "settlement", 0.75, "free + win-bearing + no fresh reel (bare/WinAmount settlement)"
    # 7. hold_respin (CONFIDENT): held set ACCUMULATES across the burst (reels progressively
    #    lock, e.g. M252 ST125 1,5,6,7 -> ... -> 1,2,4,5,6,7,8). A genuine hold-and-respin.
    if cost0 and lock >= 0.5 and lock_grows > 0 and reel >= 0.5 and coin == 0:
        return "hold_respin", 0.85, f"held set ACCUMULATES across the burst ({sig['lock_grows']} grow-steps)"
    # 8. respin: a re-spin whose held set does NOT accumulate. MODEL DECISION (owner 2026-06-18):
    #    hold_respin REQUIRES an accumulating held set; a constant (non-growing) lock is a plain
    #    respin -- so M20 ST22/23 + the constant-lock LockReSpin ST13 family are `respin`.
    #    A respin is marked (respin/move/nudge, paid OR free) OR is a free reel re-spin that holds
    #    a constant lock / wins. The guard excludes a never-wins no-lock milestone (-> state).
    if (reel >= 0.5 and coin == 0 and lock_grows == 0
            and (respin_word or (cost0 and (lock >= 0.5 or win > 0)))):
        return "respin", 0.82, "reel re-spin, held set does NOT accumulate (constant/no lock) -> respin"
    # 9. respin (implicit): FREE reel re-spin with EMPTY ReMarks subordinate to a paid base
    #    (RedHotRespin ST5). 'null' ReMarks is NOT empty -> excluded (falls to state below).
    if cost0 and not has_remarks and reel >= 0.5 and coin == 0 and lock == 0:
        return "respin", 0.78, "cost=0 + fresh reel + empty ReMarks (RedHotRespin)"
    # 10. state / transition / milestone: never wins (WinCredits==0 AND WinAmount==0), no
    #     held state. (M257 ST13 every-1000-spin milestone with 'null' ReMarks.)
    if win == 0 and coin == 0 and lock == 0:
        return "state", 0.85, "never wins (WC==0 & WA==0), no held state -> transition/milestone"
    # 11. default: cost-bearing base reel
    return "normal", 0.7 if sig["cost_pos"] > 0 else 0.5, "default base reel"


def derive_economy(sig: dict, machine_has_paid_base: bool) -> str:
    if sig["cost_pos"] > 0:
        return "paid"
    # legacy lock-respin: cost echo unreliable -> bet>0 on the sole/main loop = paid
    if sig["bet_pos"] == sig["n"] and not machine_has_paid_base:
        return "paid"
    return "free"


def derive_position(sig: dict, st: str, prev_st_counts: Counter, machine_has_paid_base: bool) -> str:
    if sig["cost_pos"] > 0:
        return "base"
    nonself = sum(c for p, c in (prev_st_counts or Counter()).items() if str(p) != str(st))
    if machine_has_paid_base and nonself > 0:
        return "feature"
    if not machine_has_paid_base:
        return "base"          # sole / main loop (legacy lock-respin)
    return "feature"


# Map a derived top-level mechanism back to the manifest (role, play) the existing routing
# (ROLE_ANALYSES / PLAY_ANALYSES) + plugin target-resolution understand. Identity for a machine
# whose declared role already matches its data -> the effective manifest is byte-identical, so
# only historically-mislabeled STs change. wheel/minigame canonicalize the PLAY (PLAY_ANALYSES
# keys on "Wheel"/"WinMiniGame"); the rest keep their original play so the intra-ST hooks
# (LockSymbolSpin -> lock_respin_dynamics, crazy_reel dimension) are preserved.
MECHANISM_TO_ROLE: dict[str, str] = {
    "normal": "paid_spin", "respin": "respin", "hold_respin": "hold_respin",
    "freespin": "freespin", "selector": "player_choice",
    "wheel": "settlement", "minigame": "settlement", "settlement": "settlement",
    "state": "state",
}
MECHANISM_TO_PLAY: dict[str, str] = {"wheel": "Wheel", "minigame": "WinMiniGame"}


def apply_derived_to_manifest(manifest: dict, derived_mechanisms: dict[str, str]) -> dict:
    """Return a COPY of the manifest with each ST's (role, play) replaced by the data-derived
    mechanism's. The SpinType-native effective manifest used to route the whole report so role
    and plugin target-resolution agree. Byte-identical where derived == the declared role."""
    eff = copy.deepcopy(manifest)
    for st, blk in (eff.get("spin_types") or {}).items():
        if not isinstance(blk, dict):
            continue
        mech = derived_mechanisms.get(str(st))
        role = MECHANISM_TO_ROLE.get(str(mech)) if mech else None
        if not role:
            continue
        # GUARD: never DOWNGRADE a declared free-feature role to a paid base. That is the
        # echo-cost failure mode -- a truly-free spin whose CostCredits is a per-record echo
        # (M96 ST86) looks cost-bearing to the deriver, which the deriver cannot see (the
        # wallet-delta test is precision-fragile). The hand label knows better there, so keep it.
        if role == "paid_spin" and blk.get("role") not in (None, "", "paid_spin"):
            continue
        # GUARD: never DOWNGRADE a declared hold_respin to a plain respin. The
        # hold_respin-vs-respin distinction (does the held set ACCUMULATE?) is a DOMAIN
        # call the user confirms at gate-8 -- a GRANTED respin chain triggered by a
        # pity/grant mechanic (M277 LockReSpin: random + collect-peak pity) is a
        # hold_respin BONUS SESSION even when its locked LINES stay constant across the
        # burst. derive_mechanism rule 8 reads "constant/no lock GROWTH" as respin, which
        # is too coarse for the granted-respin-with-pity archetype (user ruling 2026-06-20,
        # M277 + the M227/M228/M231/M246/M247 LockReSpin family). The hand label -- a
        # gate-8-confirmed family refinement, NOT drift -- knows better; keep it so the
        # freespin-family trigger-path / grant analysis is preserved. (respin is the only
        # mechanism honored here; any OTHER derived role on a hold_respin ST -- e.g.
        # state/minigame -- still overrides, surfacing genuine drift.)
        if role == "respin" and blk.get("role") == "hold_respin":
            continue
        blk["role"] = role
        if str(mech) in MECHANISM_TO_PLAY:
            blk["play"] = MECHANISM_TO_PLAY[str(mech)]
    return eff


def derive_profile_from_signals(sig: dict, *, st: str,
                                machine_has_paid_base: bool,
                                prev_st_counts: Counter | None = None) -> dict:
    """Full 3-axis profile from a pre-accumulated signal dict (streaming path)."""
    mech, conf, ev = derive_mechanism(sig)
    return {
        "spin_type": str(st),
        "mechanism": mech,
        "economy": derive_economy(sig, machine_has_paid_base),
        "position": derive_position(sig, st, prev_st_counts or Counter(), machine_has_paid_base),
        "confidence": conf,
        "evidence": ev,
    }


def derive_spin_type_profile(rounds: list[dict], *, st: str,
                             machine_has_paid_base: bool,
                             prev_st_counts: Counter | None = None) -> dict:
    """Full 3-axis profile for one (machine, ST) from its rounds."""
    sig = aggregate_st_signals(rounds)
    mech, conf, ev = derive_mechanism(sig)
    return {
        "spin_type": str(st),
        "mechanism": mech,
        "economy": derive_economy(sig, machine_has_paid_base),
        "position": derive_position(sig, st, prev_st_counts or Counter(), machine_has_paid_base),
        "confidence": conf,
        "evidence": ev,
    }
