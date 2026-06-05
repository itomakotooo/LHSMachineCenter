"""Tests for the SpinType-native machine manifest (Phase 0 — framework lock).

The load-bearing gate is `test_derive_reproduces_confirmed_m15`: the analysis set
DERIVED from M15's spin_types must EXACTLY equal the hand-listed analyzer_features
of the confirmed M15 — i.e. the derivation reproduces the confirmed machine, so
switching the live analyzer from hand-listed to derived is provably a no-op for M15.
"""
from __future__ import annotations

import json
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
_OLD_ROOT = _REPO / "slot_designer" / "configs" / "machine_manifests"


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

def test_derive_reproduces_confirmed_m15(m15):
    """derive_analyses(M15) must equal the confirmed M15's hand-listed features."""
    old = json.loads((_OLD_ROOT / "M15.json").read_text(encoding="utf-8"))
    assert sorted(old["analyzer_features"]) == derive_analyses(m15)


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
