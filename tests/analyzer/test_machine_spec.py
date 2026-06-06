"""Tests for the SpinType-native machine manifest (Phase 0 — framework lock).

The load-bearing gate is `test_derive_m15_is_nonempty_and_sorted`: the analysis
set DERIVED from M15's spin_types must be a non-empty sorted list of known feature
IDs.  Phase 5B removed the flat manifest layer so the equivalence comparison
against the old flat M15.json is no longer possible; structural shape is gated
instead.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from fresh_slotlab.analyzer.machine_spec import (
    SCHEMA_VERSION,
    derive_analyses,
    has_hidden_mechanics,
    is_confirmed,
    load_manifest,
    validate_schema,
)

_REPO = Path(__file__).resolve().parents[2]
_NEW_ROOT = _REPO / "configs" / "machine_manifests"


@pytest.fixture()
def m15() -> dict:
    return load_manifest("M15", _NEW_ROOT)


# ── schema / loader ──────────────────────────────────────────────────────

def test_m15_loads_and_is_schema_valid(m15):
    assert m15["machine_id"] == "M15"
    assert m15["schema"] == SCHEMA_VERSION
    assert validate_schema(m15) == []


def test_validate_schema_catches_problems():
    base = {"machine_id": "X", "schema": SCHEMA_VERSION,
            "spin_types": {"1": {"role": "paid_spin"}}, "validation": {}}
    assert validate_schema(base) == []
    # wrong schema version
    bad = copy.deepcopy(base); bad["schema"] = "legacy/0"
    assert any("schema" in e for e in validate_schema(bad))
    # missing role
    bad = copy.deepcopy(base); bad["spin_types"]["1"] = {"play": "Normal"}
    assert any("role" in e for e in validate_schema(bad))
    # unknown role
    bad = copy.deepcopy(base); bad["spin_types"]["1"]["role"] = "wat"
    assert any("unknown role" in e for e in validate_schema(bad))
    # empty spin_types
    bad = copy.deepcopy(base); bad["spin_types"] = {}
    assert any("spin_types" in e for e in validate_schema(bad))
    # missing validation block
    bad = copy.deepcopy(base); del bad["validation"]
    assert any("validation" in e for e in validate_schema(bad))


# ── derivation: the load-bearing gate ────────────────────────────────────

def test_derive_m15_is_nonempty_and_sorted(m15):
    """derive_analyses(M15) returns a non-empty sorted list of known feature IDs.

    5B: flat manifest layer deleted; equivalence against old flat M15.json is no
    longer possible.  We gate structural shape instead: non-empty, sorted, contains
    the core cross-cutting features that M15 declares via its spin_types.
    """
    result = derive_analyses(m15)
    assert isinstance(result, list), "derive_analyses must return a list"
    assert len(result) > 0, "M15 must derive at least one analysis"
    assert result == sorted(result), f"derive_analyses must return sorted list; got {result}"
    # Structural superset gate (value-agnostic): every analysis M15's spin_types
    # REQUIRE must be derived. M15 = paid_spin (ST1) + player_choice (ST14) +
    # settlement (ST15). A regression that silently drops any of these from
    # derive_analyses (e.g. CROSS_CUTTING / PER_SPINTYPE / role-gating bug) is
    # caught here. Uses analysis NAMES (structural), never an RTP value. Asserts
    # ⊇ (additions allowed), not == (so adding a new cross-cutting analysis later
    # does not falsely break this). Replaces the deleted flat-equivalence gate.
    required = {
        # cross-cutting (any machine with paid_spin)
        "payouts_by_spin_type", "reel_marginal_by_spin_type",
        "bankruptcy_simulation", "multiplier_profile",
        "machine_mechanics", "bonus_chain_dynamics",
        # per-SpinType (any machine with spin_types)
        "spin_type_outcomes", "spin_type_rtp_buckets",
        # role-specific: M15 has player_choice (ST14 TopDollar)
        "topdollar_choice",
    }
    missing = required - set(result)
    assert not missing, (
        f"M15 derived analyses dropped required structural analyses: {sorted(missing)}. "
        f"Full derived set: {result}"
    )


def test_derive_gates_role_specific_analyses():
    """A machine with no player_choice ST must NOT get topdollar_choice;
    one with player_choice must (role-gated, the M14-vs-M15 distinction)."""
    no_choice = {"spin_types": {"1": {"role": "paid_spin"}}}
    with_choice = {"spin_types": {"1": {"role": "paid_spin"},
                                  "14": {"role": "player_choice"}}}
    assert "topdollar_choice" not in derive_analyses(no_choice)
    assert "topdollar_choice" in derive_analyses(with_choice)
    # the role-gated one is a strict superset by exactly the role analyses
    assert set(derive_analyses(no_choice)) < set(derive_analyses(with_choice))


# ── validation state + hidden-mechanics flag (the M90 lesson) ─────────────

def test_m15_is_confirmed(m15):
    assert is_confirmed(m15) is True


def test_auto_until_user_signs_off():
    m = {"validation": {"status": "confirmed", "user_signed_off": False}}
    assert is_confirmed(m) is False
    m = {"validation": {"status": "auto", "user_signed_off": True}}
    assert is_confirmed(m) is False


def test_m15_has_no_hidden_mechanics(m15):
    assert has_hidden_mechanics(m15) is False


def test_hidden_mechanics_flag_for_m90_shape():
    """The M90 case: a domain-declared mechanic testspin can't show."""
    m90_like = {"out_of_engine_mechanics": [
        {"name": "trigger_10_gift", "rtp_impact": True, "source": "domain"}]}
    assert has_hidden_mechanics(m90_like) is True
