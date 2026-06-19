"""CODE-ENFORCED correctness constraint for SpinType classification.

The guarantee (per user directive: enforce in CODE, not docs): a machine's declared
per-SpinType `role` must be CONSISTENT with the mechanism DERIVED from that machine's
own rawdata. A future onboarding that mislabels a SpinType (the ST13/ST125/ST137 class
of drift) FAILS this gate — it cannot silently land.

Usage:
  * onboarding: call ``check_machine`` on the new manifest + its cached rawdata; a
    non-empty violation list blocks the onboard until the role is fixed or the ST is
    explicitly waived (NEEDS_SIGNOFF) by the domain owner.
  * regression: ``tests/analyzer/test_spin_type_classification_gate.py`` runs this over
    the whole registered fleet; violations must be ⊆ KNOWN_MISLABELS (the documented,
    not-yet-applied fix-list). When the fixes land, KNOWN_MISLABELS shrinks to {}.
"""
from __future__ import annotations
from collections import Counter
from typing import Any

from fresh_slotlab.analyzer.spin_type_deriver import derive_spin_type_profile

# A declared role is consistent if the data-derived mechanism falls in its allowed set.
# paid_spin is economy-conflated (it asserts "paid base"), so its mechanism may be a
# normal reel OR a paid lock/respin loop (legacy LockReSpin machines like M10).
ROLE_TO_MECH: dict[str, set[str]] = {
    "paid_spin": {"normal", "hold_respin", "respin"},
    "respin": {"respin"},
    # freespin + hold_respin share the granted-free-session plugin family (FREESPIN_FAMILY_ROLES),
    # so either role accepts either derived mechanism.
    "hold_respin": {"hold_respin", "freespin"},
    "freespin": {"freespin", "hold_respin"},
    "settlement": {"settlement", "wheel", "minigame", "selector"},
    "player_choice": {"selector"},
    "state": {"state"},
}

# Confidence floor: below this the deriver is guessing -> require explicit sign-off.
MIN_CONFIDENCE = 0.7

# ── Migration delta (2026-06-18, deriver v3, MODEL DECIDED) ─────────────────────
# MODEL DECISION (owner): hold_respin REQUIRES an accumulating held set; a constant lock is a
# plain respin. With that rule the deriver is FULLY confident fleet-wide (no sign-off pending).
# These are the (machine, ST) where the hand-declared role differs from the data-derived
# mechanism -- the refactor (mechanism = derived) corrects each by construction; the manifest
# `role` is being REPLACED, so there is no manual edit. Validated against raw rawdata:
PENDING_ROLE_FIXES: dict[tuple[str, str], str] = {
    ("M257", "13"): "state",         # never-wins 'null' milestone, no held state
    ("M268", "125"): "hold_respin",   # persistent coin-position JSON -> accumulating hold
    ("M252", "125"): "hold_respin",   # LockReels ACCUMULATES 1,5 -> ... -> 1,2,4,5,6,7,8
    ("M274", "139"): "minigame",      # win-bearing minigame settlement
    # constant-lock LockReSpin ST13 -> respin per the model (these locks do NOT accumulate;
    # the accumulating ST13 machines M201/M233/M241 correctly stay hold_respin):
    ("M227", "13"): "respin", ("M228", "13"): "respin", ("M231", "13"): "respin",
    ("M246", "13"): "respin", ("M247", "13"): "respin", ("M277", "13"): "respin",
}
# Empty: the model decision removed the last ambiguity -- nothing awaits sign-off.
PENDING_SIGNOFF: set[tuple[str, str]] = set()


def check_machine(
    manifest: dict[str, Any],
    rounds_by_st: dict[str, list[dict]],
    *,
    machine_has_paid_base: bool,
    prev_st_counts: dict[str, Counter] | None = None,
    needs_signoff: set[tuple[str, str]] | None = None,
) -> list[dict]:
    """Return a list of classification violations for one machine ([] == clean).

    A violation = a declared SpinType whose role's allowed mechanism set does NOT
    contain the data-derived mechanism, or whose derivation is below MIN_CONFIDENCE
    and is not explicitly waived in ``needs_signoff``.
    """
    machine_id = str(manifest.get("machine_id"))
    prev_st_counts = prev_st_counts or {}
    needs_signoff = needs_signoff or set()
    violations: list[dict] = []
    for st, blk in (manifest.get("spin_types") or {}).items():
        if not isinstance(blk, dict):
            continue
        rounds = rounds_by_st.get(str(st))
        if not rounds:
            continue
        prof = derive_spin_type_profile(
            rounds, st=str(st), machine_has_paid_base=machine_has_paid_base,
            prev_st_counts=prev_st_counts.get(str(st), Counter()),
        )
        role = blk.get("role")
        allowed = ROLE_TO_MECH.get(role, set())
        key = (machine_id, str(st))
        if prof["mechanism"] not in allowed and key not in needs_signoff:
            violations.append({
                "machine": machine_id, "spin_type": str(st),
                "declared_role": role, "derived_mechanism": prof["mechanism"],
                "economy": prof["economy"], "position": prof["position"],
                "confidence": prof["confidence"], "evidence": prof["evidence"],
                "kind": "role_mechanism_mismatch",
            })
        elif prof["confidence"] < MIN_CONFIDENCE and key not in needs_signoff:
            violations.append({
                "machine": machine_id, "spin_type": str(st),
                "declared_role": role, "derived_mechanism": prof["mechanism"],
                "confidence": prof["confidence"], "evidence": prof["evidence"],
                "kind": "low_confidence_needs_signoff",
            })
    return violations
