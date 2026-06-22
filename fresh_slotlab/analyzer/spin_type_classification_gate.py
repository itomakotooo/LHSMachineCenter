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

from fresh_slotlab.analyzer.spin_type_deriver import (
    derive_cost_credits_unreliable,
    derive_spin_type_profile,
)

# A declared role is consistent if the data-derived mechanism falls in its allowed set.
# paid_spin is economy-conflated (it asserts "paid base"), so its mechanism may be a
# normal reel OR a paid lock/respin loop (legacy LockReSpin machines like M10).
ROLE_TO_MECH: dict[str, set[str]] = {
    "paid_spin": {"normal", "hold_respin", "respin"},
    "respin": {"respin"},
    # freespin + hold_respin share the granted-free-session plugin family (FREESPIN_FAMILY_ROLES),
    # so either role accepts either derived mechanism. hold_respin ALSO accepts a derived `respin`:
    # the hold_respin-vs-respin distinction (does the held set ACCUMULATE?) is a DOMAIN call the
    # user confirms at gate-8 — a GRANTED constant-lock respin chain with a pity/grant trigger
    # (M277 + the M227/M228/M231/M246/M247 LockReSpin family) is a hold_respin BONUS even though
    # derive_mechanism's lock-GROWTH heuristic reads it as respin (too coarse for granted respin
    # chains; user ruling 2026-06-20). apply_derived_to_manifest HONORS the declared hold_respin
    # (its own guard), so the gate must accept the derived `respin` here rather than flag drift.
    "hold_respin": {"hold_respin", "freespin", "respin"},
    "freespin": {"freespin", "hold_respin"},
    "settlement": {"settlement", "wheel", "minigame", "selector"},
    "player_choice": {"selector"},
    "state": {"state"},
}

# Confidence floor: below this the deriver is guessing -> require explicit sign-off.
MIN_CONFIDENCE = 0.7

# ── Migration delta (2026-06-18, deriver v3; AMENDED 2026-06-20) ────────────────
# MODEL DECISION (owner 2026-06-18): hold_respin REQUIRES an accumulating held set; a constant
# lock is, BY DEFAULT, a plain respin (derive_mechanism rule 8). AMENDMENT (owner 2026-06-20):
# that lock-GROWTH heuristic is too coarse for a GRANTED constant-lock respin chain triggered by
# a pity/grant mechanic (M277 LockReSpin: random + collect-peak pity). Such a chain is a
# hold_respin BONUS SESSION (freespin-family: trigger-path / grant analysis) even with a constant
# locked LINE set — a DOMAIN call the user confirms at gate-8 that the deriver cannot reliably
# derive (M277 vs M149's plain in-line respin look identical to the lock-growth signal). So a
# DECLARED hold_respin is now HONORED over a derived `respin`: apply_derived_to_manifest keeps the
# declared role (its guard) and ROLE_TO_MECH[hold_respin] accepts `respin` (above). The constant-
# lock LockReSpin family (M227/M228/M231/M246/M247/M277 ST13) therefore STAYS hold_respin — they
# are NO LONGER in this fix list. (derive_mechanism still RETURNS respin for a constant lock —
# that default + test_deriver_constant_lock_is_respin_per_model_decision are unchanged; only the
# apply/gate layer honors the manifest's gate-8-confirmed family refinement.)
#
# These remain genuine data-derived role corrections (derived role OVERRIDES the manifest; NOT a
# hold_respin↔respin family question):
PENDING_ROLE_FIXES: dict[tuple[str, str], str] = {
    ("M257", "13"): "state",         # never-wins 'null' milestone, no held state
    ("M268", "125"): "hold_respin",   # persistent coin-position JSON -> accumulating hold
    ("M252", "125"): "hold_respin",   # LockReels ACCUMULATES 1,5 -> ... -> 1,2,4,5,6,7,8
    ("M274", "139"): "minigame",      # win-bearing minigame settlement
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
    # Machine-level cost-echo signal (mirrors core/parser.py). When CostCredits is
    # echoed onto a feature (M93 ST82) or never populated (M10/M23/M131/M133), the
    # per-ST economy/position + the cost0-gated mechanism rules must NOT trust
    # CostCredits — otherwise a freespin feature derives as a paid 'normal' base and
    # the role↔mechanism gate wrongly fails. Computed once over all rounds.
    cost_unreliable = derive_cost_credits_unreliable(rounds_by_st)
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
            cost_unreliable=cost_unreliable,
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
