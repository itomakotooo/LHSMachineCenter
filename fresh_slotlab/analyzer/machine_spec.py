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
KNOWN_ROLES = frozenset({"paid_spin", "player_choice", "settlement", "state"})

# ── Analysis derivation (replaces the old hand-listed analyzer_features) ──────
# CROSS_CUTTING: whole-session analyses that apply to every machine.
CROSS_CUTTING: tuple[str, ...] = (
    "bankruptcy_simulation",
    "multiplier_profile",
    "machine_mechanics",
    "upstream_feature_breakdown",
    "collect_mechanic",
    "bonus_chain_dynamics",
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
ROLE_ANALYSES: dict[str, tuple[str, ...]] = {
    "player_choice": ("topdollar_choice",),
}


def derive_analyses(manifest: dict[str, Any]) -> list[str]:
    """Derive the analysis set for a machine from its spin_types.

    = CROSS_CUTTING + PER_SPINTYPE + role-specific analyses for each role present.
    Reproduces the confirmed M15 set exactly (see test_machine_spec).
    """
    out: set[str] = set(CROSS_CUTTING) | set(PER_SPINTYPE)
    roles = {
        str(st.get("role", "")) for st in (manifest.get("spin_types") or {}).values()
    }
    for role in roles:
        out.update(ROLE_ANALYSES.get(role, ()))
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
