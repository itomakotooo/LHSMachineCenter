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

# ── Current fleet residual (2026-06-18, deriver v3) ─────────────────────────────
# CONFIDENT role mislabels resolved by raw-rawdata inspection -- the declared role is WRONG;
# the refactor (mechanism = derived) corrects them by construction:
PENDING_ROLE_FIXES: dict[tuple[str, str], str] = {
    ("M257", "13"): "state",         # every-1000-spin zero-win 'null' milestone, not hold_respin
    ("M268", "125"): "hold_respin",   # persistent coin-position JSON -> a real hold, not respin
    ("M274", "139"): "minigame",      # win-bearing minigame settlement, not hold_respin
    ("M252", "125"): "hold_respin",   # LockReels ACCUMULATES 1,5 -> ... -> 1,2,4,5,6,7,8 = real hold
}
# OPEN DOMAIN-MODEL QUESTION (the deriver returns confidence ~0.55 -> the gate routes these to
# sign-off; it REFUSES to guess). The respin vs hold_respin boundary is genuinely undecidable
# from data for CONSTANT-lock machines: the fleet labels identical data inconsistently --
# M227 ST13 'LockLines=2-' (constant) is hold_respin* but M20 ST22/23 'LockLines=3-2-' (constant)
# is respin. Until the owner decides the MODEL (are hold_respin + respin one mechanism, or split
# by a precise rule e.g. lock-accumulation?), every constant-lock (machine, ST) is auto-flagged
# low-confidence -- there is NO hardcoded list; the gate detects them by confidence < MIN_CONFIDENCE.
# Examples awaiting the model decision: M20 ST21/22/23 (labeled respin), the LockReSpin ST13
# family M201/M227/M228/M231/M233/M241/M246/M247/M277 (labeled hold_respin), M245/M282 ST125.
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
