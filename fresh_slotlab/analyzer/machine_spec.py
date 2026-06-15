"""SpinType-native machine manifest — schema, loader, and analysis derivation.

LOCKED 2026-06-05 from the confirmed M15 reference + the M90 lesson.

A machine is described in terms of the **SpinTypes it emits** (the unit). Each
SpinType has a `role` and a `play`. The set of analyzer analyses a machine runs
is **DERIVED** from its spin_types (NOT hand-listed) — see `derive_analyses`.

This module is standalone (NOT imported by the report-production closure), so it
does not flip `base_hash`. Wiring versioning/PIA to consume it is the next step.

Schema (configs/machine_manifests/<M>.json)::

    {
      "machine_id": "M15",
      "schema": "spintype-native/1",
      "modes": [1, 2, 5, 7],
      "inherits_from": null,
      "spin_types": {
        "1":  {"role": "paid_spin",     "play": "Normal"},
        "14": {"role": "player_choice", "play": "TopDollar",
               "economy": {"win_field": "WinCredits", "kind": "preview"}},
        "15": {"role": "settlement",    "play": "TopDollar",
               "economy": {"win_field": "WinAmount", "kind": "real"}}
      },
      "trigger": {"payout_id": "666", "remarks": "Trigger"},
      "validation": {"status": "confirmed"|"auto", "user_signed_off": bool, ...},
      "out_of_engine_mechanics": [   # the M90 lesson: mechanics testspin CAN'T show
        {"name": "...", "desc": "...", "rtp_impact": bool, "source": "domain"}
      ],
      "rtp_integrity": {"paid_st": [1], "fallback_warn": 0.5, "fallback_fail": 5.0}
    }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "spintype-native/1"

# Roles a SpinType can play in the gameplay (open set; extend as machines confirm).
# "respin" added 2026-06-07 (M43 onboarding): a free reel-spin extension of a paid
# spin (cost=0, premium-skin board, full reels, can win, shares the triggering
# spin's SpinTimes, win-gated continuation). Data-grounded on M43's WinRespin /
# ReMarks="ReSpin" feature — it does not fit paid_spin/player_choice/settlement/state.
# "freespin" added 2026-06-12 (M275 onboarding): a GRANTED multi-spin FREE session
# (cost=0 reel spins) opened by a trigger event (scatter pid and/or counter peak)
# with a structurally fixed/granted length — NOT a win-driven extension of the
# same paid spin (that is "respin": nothing here is win-gated; the trigger round
# typically wins 0). Data-grounded on M275's NewFreespin / ReMarks="Freespin N"
# (token derived from the machine's own naming, branding prefix belongs to play).
KNOWN_ROLES = frozenset({
    "paid_spin", "player_choice", "settlement", "state", "respin", "freespin",
})

# ── Analysis derivation (replaces the old hand-listed analyzer_features) ──────
# CROSS_CUTTING: whole-session analyses that apply to every machine.
CROSS_CUTTING: tuple[str, ...] = (
    "bankruptcy_simulation",
    "multiplier_profile",
    "machine_mechanics",
    "upstream_feature_breakdown",
    "collect_mechanic",
    "bonus_chain_dynamics",
    "structure_drift",
)
# PER_SPINTYPE: analyses that run per-SpinType (a machine gets them because it
# emits SpinTypes at all).
PER_SPINTYPE: tuple[str, ...] = (
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "spin_type_outcomes",
    "spin_type_rtp_buckets",
)
# ROLE_ANALYSES: analyses attached to a specific SpinType ROLE.
# A role-keyed analysis applies whenever ANY SpinType declares that role.
#   player_choice -> topdollar_choice  (M15 ST14)
#   respin        -> respin_dynamics   (M43 ST50: grant-rate / hit-rate uplift /
#                    continuity / skin-premium symbol mix / RTP-share)
#   freespin      -> freespin_dynamics (M275 ST126: session cadence / hot-board
#                    uplift / trigger-path dimension). ROLE hook (not play):
#                    the analysis applies to ANY freespin-role ST generically
#                    across the freespin family; there is no role collision to
#                    scope away (unlike WinMiniGame/Wheel on the shared
#                    `settlement` role).
ROLE_ANALYSES: dict[str, tuple[str, ...]] = {
    "player_choice": ("topdollar_choice",),
    "respin": ("respin_dynamics",),
    "freespin": ("freespin_dynamics",),
}

# PLAY_ANALYSES: analyses attached to a specific SpinType PLAY (the rawdata
# feature name), NOT its role. This is the correct hook when an analysis is
# specific to one feature whose role is SHARED with an unrelated feature on
# another machine. M43's minigame settles via the `settlement` role — the SAME
# role M15's ST15 (TopDollar) settlement uses — so attaching minigame_dynamics by
# role would wrongly fire it on M15. Keying on play "WinMiniGame" scopes it to the
# minigame feature only. (Play match is case-sensitive: it is the exact FeatureWin
# key from the rawdata per the user's naming directive.)
#   Wheel -> wheel_dynamics (M279 ST2): the guaranteed-payout collect wheel. Its
#   role is `settlement` — the SAME role M15's ST15 (TopDollar) and M43's ST51
#   (WinMiniGame) settlement use — so attaching wheel_dynamics by role would
#   wrongly fire it on those machines. Keying on play "Wheel" scopes it to M279's
#   wheel only (same role-vs-play discipline as WinMiniGame above).
PLAY_ANALYSES: dict[str, tuple[str, ...]] = {
    "WinMiniGame": ("minigame_dynamics",),
    "Wheel": ("wheel_dynamics",),
}


def derive_analyses(manifest: dict[str, Any]) -> list[str]:
    """Derive the analysis set for a machine from its spin_types.

    = CROSS_CUTTING + PER_SPINTYPE
      + role-specific analyses for each ROLE present (ROLE_ANALYSES)
      + play-specific analyses for each PLAY present (PLAY_ANALYSES).

    Reproduces the confirmed M15 set exactly (M15 has no `respin` role and no
    `WinMiniGame` play, so neither M43 analysis attaches to it — see
    test_machine_spec). For M43: ST50 role=`respin` adds respin_dynamics; ST51
    play=`WinMiniGame` adds minigame_dynamics (NOT via its `settlement` role).
    """
    out: set[str] = set(CROSS_CUTTING) | set(PER_SPINTYPE)
    spin_types = (manifest.get("spin_types") or {}).values()
    roles = {str(st.get("role", "")) for st in spin_types}
    plays = {str(st.get("play", "")) for st in spin_types}
    for role in roles:
        out.update(ROLE_ANALYSES.get(role, ()))
    for play in plays:
        out.update(PLAY_ANALYSES.get(play, ()))
    return sorted(out)


def is_confirmed(manifest: dict[str, Any]) -> bool:
    """A machine is confirmed only when validation.status == 'confirmed' AND the
    user signed off. Otherwise it is 'auto' (data-derived, possibly incomplete)."""
    v = manifest.get("validation") or {}
    return v.get("status") == "confirmed" and bool(v.get("user_signed_off"))


def has_hidden_mechanics(manifest: dict[str, Any]) -> bool:
    """True if the machine has domain-declared mechanics that testspin rawdata
    can't show (the M90 case) — a flag that the data-derived view is incomplete."""
    return bool(manifest.get("out_of_engine_mechanics"))


def derive_mechanism_flags(manifest: dict[str, Any]) -> dict[str, Any]:
    """Derive mechanism flags from a SpinType-native manifest.

    Returns a dict with the mechanism fields that `bonus_chain_dynamics` and
    `machine_mechanics` need, derived purely from manifest declarations instead
    of runtime detection (phase 3 de-couple).

    Fields returned:
      freespin_applicable : bool
          True if any SpinType has play == "freespin" (case-insensitive) OR
          role == "freespin" (the structural-kind token; M275's play is the
          literal FeatureWin key "NewFreespin", so the play check alone would
          self-contradict the report — bonus_chain_dynamics showing freespin
          chains while free_spin reads "not applicable". Additive: only
          manifests declaring the freespin role change output).
      jackpot_applicable : bool
          True if any SpinType has play == "jackpot" (case-insensitive).
      jackpot_pid_set : frozenset[str]
          The payout_ids listed in spin_types with play == "jackpot".
          Typically empty; operators declare pids in the spin_type spec.
      scatter_trigger_pids : frozenset[str]
          The payout_id from the top-level "trigger" block, if present.
          These are scatter-trigger marker pids that open a bonus feature.
      detection_source : str
          Always "manifest_spin_types" — identifies phase 3 manifest-driven path.

    For M15 (ST1=Normal/paid_spin, ST14=TopDollar/player_choice,
    ST15=TopDollar/settlement): no freespin/jackpot plays declared → both
    applicable flags are False. scatter_trigger_pids carries the trigger pid
    (payout_id "666" from the trigger block).

    No I/O: pure computation on the already-loaded manifest dict.
    """
    spin_types: dict[str, Any] = manifest.get("spin_types") or {}
    plays_lower = {str(spec.get("play", "")).lower() for spec in spin_types.values()}
    roles_lower = {
        str(spec.get("role", "")).lower()
        for spec in spin_types.values()
        if isinstance(spec, dict)
    }

    # Role-aware freespin derivation (M275, 2026-06-12): a machine whose
    # freespin feature carries a branded play name (e.g. "NewFreespin")
    # declares the structural kind via role == "freespin".
    freespin_applicable: bool = (
        "freespin" in plays_lower or "freespin" in roles_lower
    )
    jackpot_applicable: bool = "jackpot" in plays_lower

    # Jackpot pid set: collect pids from spin_types that declare a jackpot play.
    jackpot_pid_set: frozenset[str] = frozenset(
        str(st_id)
        for st_id, spec in spin_types.items()
        if isinstance(spec, dict) and str(spec.get("play", "")).lower() == "jackpot"
    )

    # Scatter trigger pids: from the top-level "trigger" block.
    # The trigger block carries {payout_id, remarks, opens} — the payout_id
    # is the scatter marker that starts a bonus feature (e.g. "666" on M15).
    _trigger: dict[str, Any] = manifest.get("trigger") or {}
    _trigger_pid = _trigger.get("payout_id")
    scatter_trigger_pids: frozenset[str] = (
        frozenset({str(_trigger_pid)}) if _trigger_pid is not None else frozenset()
    )

    return {
        "freespin_applicable": freespin_applicable,
        "jackpot_applicable": jackpot_applicable,
        "jackpot_pid_set": jackpot_pid_set,
        "scatter_trigger_pids": scatter_trigger_pids,
        "detection_source": "manifest_spin_types",
    }


def validate_schema(manifest: dict[str, Any]) -> list[str]:
    """Return a list of schema problems ([] = valid)."""
    errs: list[str] = []
    if manifest.get("schema") != SCHEMA_VERSION:
        errs.append(f"schema must be {SCHEMA_VERSION!r}, got {manifest.get('schema')!r}")
    if not manifest.get("machine_id"):
        errs.append("machine_id missing")
    sts = manifest.get("spin_types")
    if not isinstance(sts, dict) or not sts:
        errs.append("spin_types must be a non-empty object")
    else:
        for st, spec in sts.items():
            if not isinstance(spec, dict) or "role" not in spec:
                errs.append(f"spin_type {st} missing 'role'")
            elif spec["role"] not in KNOWN_ROLES:
                errs.append(f"spin_type {st} has unknown role {spec['role']!r}")
    if "validation" not in manifest:
        errs.append("validation block missing")
    return errs


def load_manifest(machine_id: str, manifests_root: str | Path) -> dict[str, Any]:
    """Load + schema-validate a SpinType-native manifest. Raises on schema errors."""
    path = Path(manifests_root) / f"{machine_id}.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    errs = validate_schema(manifest)
    if errs:
        raise ValueError(f"{path}: invalid manifest: {errs}")
    return manifest
