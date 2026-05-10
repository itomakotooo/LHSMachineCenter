"""Phase E target — end-to-end verification across all virtual machines.

Closes the Phase A→D refactor with integration tests that exercise the
full cross-machine flow:

  load_engine (or custom adapter)
    → spin_session / sample_one_chunk
      → emit_session / emit_robot
        → chunk envelope + analysisResult JSON

For all four virtual machines (M1, M15, M37, M279), confirms:
  - Plugin loading routes to the right path (FeaturePlugin vs custom
    engine adapter vs neither)
  - Sampling produces a valid chunk dict
  - Per-machine code_md5 isolation holds across the fleet
  - Registry refresh writes distinct md5s for machines whose plugin
    trees differ

These tests are slow (1-3s each because they actually run sampling).
Architecturally they cover what the static-check tests in
test_layout.py / test_per_machine_code_md5.py / test_no_machine_leakage.py /
test_feature_plugin_protocol.py / test_custom_engine_adapter.py cannot:
that the **runtime contract holds** — concrete code paths actually work.
"""
from __future__ import annotations

import json
from pathlib import Path
from random import Random

import pytest


_SLOT_DESIGNER = Path(__file__).resolve().parents[2]
_REPO_ROOT = _SLOT_DESIGNER.parent
_REGISTRY = _SLOT_DESIGNER / "configs" / "machines_virtual.json"


# ─────────────────────────────────────────────────────────────────────
# Fleet matrix
# ─────────────────────────────────────────────────────────────────────

_FLEET = ["M1", "M15", "M37", "M279"]


def _spec_path(machine: str) -> Path:
    return _SLOT_DESIGNER / "machines" / machine / "spec.json"


def _weights_path(machine: str, mode: int) -> Path:
    return (
        _SLOT_DESIGNER / "machines" / machine / "weights" /
        f"mode_{mode}" / "weights.json"
    )


# ─────────────────────────────────────────────────────────────────────
# Fleet-wide engine loading
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("machine", _FLEET)
def test_every_machine_loads_an_engine_for_mode_1(machine: str) -> None:
    """Every machine in the fleet must load an engine without error.

    Routing path:
      - Machines without ``_engine`` marker → core load_engine, plugin
        from machines/<M>/plugins/__init__.py::build_plugin (or None
        for base-only).
      - Machines with ``_engine`` marker → custom adapter from
        machines/<M>/plugins/__init__.py::load_engine.
    """
    spec_path = _spec_path(machine)
    weights_path = _weights_path(machine, 1)

    # Decide which loader by reading the registry's _engine field.
    registry = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    entry = next(
        (e for e in registry["machines"] if e.get("_source_machine") == machine),
        None,
    )
    assert entry is not None, f"machine {machine} not in machines_virtual.json"

    if entry.get("_engine"):
        # Custom adapter path
        from slot_designer.core.backend.virtual_analyzer import _load_custom_engine_module

        adapter = _load_custom_engine_module(entry)
        engine, spec = adapter.load_engine(spec_path, weights_path)
    else:
        from slot_designer.core.engine.loader import load_engine

        engine, spec = load_engine(spec_path, weights_path)

    assert engine is not None
    assert spec.get("machine") == machine


# ─────────────────────────────────────────────────────────────────────
# Plugin classification per machine
# ─────────────────────────────────────────────────────────────────────

def test_m1_engine_has_no_plugin():
    from slot_designer.core.engine.loader import load_engine

    engine, _ = load_engine(_spec_path("M1"), _weights_path("M1", 1))
    assert engine.plugin is None


def test_m37_engine_has_no_plugin():
    from slot_designer.core.engine.loader import load_engine

    engine, _ = load_engine(_spec_path("M37"), _weights_path("M37", 1))
    assert engine.plugin is None


def test_m15_engine_has_feature_plugin():
    from slot_designer.core.engine.feature_protocol import FeaturePlugin
    from slot_designer.core.engine.loader import load_engine

    engine, _ = load_engine(_spec_path("M15"), _weights_path("M15", 1))
    assert engine.plugin is not None
    assert isinstance(engine.plugin, FeaturePlugin)


# ─────────────────────────────────────────────────────────────────────
# End-to-end sampling — base + feature + custom engine
# ─────────────────────────────────────────────────────────────────────

def test_e2e_sample_chunk_for_m1_produces_valid_chunk():
    """Base-only machine sampling end-to-end."""
    from slot_designer.core.emitter.driver import (
        compute_schema_fingerprint_for,
        sample_one_chunk,
    )
    from slot_designer.core.engine.loader import load_engine

    engine, spec = load_engine(_spec_path("M1"), _weights_path("M1", 1))
    schema_fp = compute_schema_fingerprint_for(
        engine, mode=int(spec["mode"]), spins_per_robot=20,
    )
    rng = Random(42)
    chunk, c_win, c_bet = sample_one_chunk(
        engine,
        machine="M1sim",
        mode=int(spec["mode"]),
        chunk_index=1,
        robots=2,
        spins_per_robot=20,
        rng=rng,
        schema_fp=schema_fp,
        config_md5="cfg-stub",
        code_md5="code-stub",
    )
    assert chunk["_machine"] == "M1sim"
    assert chunk["_mode"] == int(spec["mode"])
    assert c_bet > 0
    assert c_win >= 0  # base game can be 0-win across small batch


def test_e2e_sample_chunk_for_m15_includes_feature_rounds():
    """Feature machine sampling end-to-end. Feature trigger rate is
    ~1.14% on M15 mode 1; with 200 spins we have ~98%+ probability of
    seeing at least one trigger, so the chunk's roundResult should
    contain ST=14 (feature reveal) rounds when a trigger fires.
    """
    from slot_designer.core.emitter.driver import (
        compute_schema_fingerprint_for,
        sample_one_chunk,
    )
    from slot_designer.core.engine.loader import load_engine

    engine, spec = load_engine(_spec_path("M15"), _weights_path("M15", 1))
    schema_fp = compute_schema_fingerprint_for(
        engine, mode=int(spec["mode"]), spins_per_robot=200,
    )
    rng = Random(42)
    chunk, c_win, c_bet = sample_one_chunk(
        engine,
        machine="M15sim",
        mode=int(spec["mode"]),
        chunk_index=1,
        robots=2,
        spins_per_robot=200,
        rng=rng,
        schema_fp=schema_fp,
        config_md5="cfg-stub",
        code_md5="code-stub",
    )
    assert chunk["_machine"] == "M15sim"
    # Inspect rounds across robots — at least one feature reveal
    # (ST=14 in M15's plugin output) expected.
    saw_feature_round = False
    for robot in chunk.get("response", []):
        rounds_str = robot.get("roundResult", "[]")
        rounds = json.loads(rounds_str)
        if any(r.get("SpinType") == 14 for r in rounds):
            saw_feature_round = True
            break
    assert saw_feature_round, (
        "M15 mode 1 with 400 spins must produce at least one feature trigger; "
        "if this fails, plugin wiring is broken (no ST=14 reveals emitted)"
    )


def test_e2e_sample_chunk_for_m279_via_custom_adapter():
    """Custom-engine machine sampling end-to-end."""
    from slot_designer.core.backend.virtual_analyzer import _load_custom_engine_module

    fake_entry = {
        "machine": "M279sim",
        "_source_machine": "M279",
        "_engine": "custom",
    }
    adapter = _load_custom_engine_module(fake_entry)
    engine, spec = adapter.load_engine(_spec_path("M279"), _weights_path("M279", 1))
    schema_fp = adapter.compute_schema_fingerprint(
        engine, mode=int(spec["mode"]), spins_per_robot=20,
    )
    rng = Random(42)
    chunk, c_win, c_bet = adapter.sample_one_chunk(
        engine,
        machine="M279sim",
        mode=int(spec["mode"]),
        chunk_index=1,
        robots=2,
        spins_per_robot=20,
        rng=rng,
        schema_fp=schema_fp,
        config_md5="cfg-stub",
        code_md5="code-stub",
    )
    assert chunk["_machine"] == "M279sim"
    assert c_bet > 0


# ─────────────────────────────────────────────────────────────────────
# Registry refresh writes distinct per-machine md5s
# ─────────────────────────────────────────────────────────────────────

def test_registry_refresh_assigns_distinct_md5s_per_machine():
    """After refresh_machines_virtual, the four virtual machines have
    DISTINCT codeSummaryMd5 values (M15sim has plugin tree, M279sim has
    plugin tree, M1sim/M37sim have none → so M15sim ≠ M1sim).

    Pre-Phase-B, all four shared one fleet-wide hash. This test pins
    the post-refactor invariant.
    """
    from slot_designer.core.backend.virtual_app import refresh_machines_virtual

    original = _REGISTRY.read_text(encoding="utf-8")
    try:
        refresh_machines_virtual(_REGISTRY)
        raw = json.loads(_REGISTRY.read_text(encoding="utf-8"))
        m_by_name = {e["machine"]: e for e in raw["machines"]}
        m1_md5 = m_by_name["M1sim"]["codeSummaryMd5"]
        m15_md5 = m_by_name["M15sim"]["codeSummaryMd5"]
        m37_md5 = m_by_name["M37sim"]["codeSummaryMd5"]
        m279_md5 = m_by_name["M279sim"]["codeSummaryMd5"]

        # M15 has plugins, M1/M37 don't → must differ.
        assert m1_md5 != m15_md5
        assert m37_md5 != m15_md5
        # M279 has plugins, M15 has plugins → must differ (different
        # plugin tree contents).
        assert m15_md5 != m279_md5
        # M1 and M37 are both base-only → same md5 (only core/ contributes).
        assert m1_md5 == m37_md5
    finally:
        # Restore original registry to keep tests independent.
        _REGISTRY.write_text(original, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
# Refactor invariants summary — pulls together the boundary contracts
# from all phases A-D for a final readout
# ─────────────────────────────────────────────────────────────────────

def test_refactor_summary_invariants_hold_post_phase_e():
    """One-shot smoke that the headline invariants from each refactor
    phase still hold:

      A — core/ + machines/<M>/ exist; legacy slot_designer/{engine,
          emitter,...} removed.
      B — compute_code_md5 takes a machine_name arg.
      C — core/engine/feature_protocol exposes FeaturePlugin Protocol;
          load_engine sets engine.plugin (None or instance).
      D — machines/M279/plugins exposes the custom-engine adapter
          callables.
    """
    # A
    assert (_SLOT_DESIGNER / "core" / "engine").is_dir()
    assert (_SLOT_DESIGNER / "machines" / "M1").is_dir()
    assert not (_SLOT_DESIGNER / "engine").exists()

    # B
    from slot_designer.core.backend.machine_version import compute_code_md5

    md5_a = compute_code_md5("M15")
    md5_b = compute_code_md5("M1")
    assert md5_a != md5_b
    with pytest.raises(TypeError):
        compute_code_md5()  # type: ignore[call-arg]

    # C
    from slot_designer.core.engine.feature_protocol import FeaturePlugin
    from slot_designer.core.engine.loader import load_engine

    e_m15, _ = load_engine(_spec_path("M15"), _weights_path("M15", 1))
    e_m1, _ = load_engine(_spec_path("M1"), _weights_path("M1", 1))
    assert isinstance(e_m15.plugin, FeaturePlugin)
    assert e_m1.plugin is None

    # D
    import slot_designer.machines.M279.plugins as m279_plugin

    assert callable(m279_plugin.load_engine)
    assert callable(m279_plugin.sample_one_chunk)
    assert callable(m279_plugin.compute_schema_fingerprint)
