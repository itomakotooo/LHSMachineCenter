"""Phase D target — custom-engine adapter contract via plugin module.

Some machines have engine architectures that don't fit
``SpinEngine.spin_session`` (e.g. M279: multi-payline + persistent
collect meter + nudge stacks + wheel feature). Those machines route
through a custom-engine adapter exposed by their plugin package.

Adapter contract (when ``machines/<M>/plugins/__init__.py`` is invoked
via the ``_engine`` registry marker):

  load_engine(spec_path, weights_path) -> (engine, spec)
  sample_one_chunk(engine, *, machine, mode, chunk_index,
                   robots, spins_per_robot, rng, schema_fp,
                   config_md5, code_md5) -> (chunk, win, bet)
  compute_schema_fingerprint(engine, *, mode, spins_per_robot) -> str

Generic core never imports the concrete engine class; it discovers the
plugin module via ``importlib.import_module(f"slot_designer.machines.
{machine_name}.plugins")`` keyed by the registry's ``_machine`` /
``_source_machine`` field.

This test exercises the contract via the M279 plugin (the only custom
engine in the repo today).
"""
from __future__ import annotations

import json
from pathlib import Path
from random import Random


_SLOT_DESIGNER = Path(__file__).resolve().parents[2]
_M279_SPEC = _SLOT_DESIGNER / "machines" / "M279" / "spec.json"
_M279_WEIGHTS_M1 = (
    _SLOT_DESIGNER / "machines" / "M279" / "weights" / "mode_1" / "weights.json"
)


# ─────────────────────────────────────────────────────────────────────
# Plugin package exposes the adapter callables
# ─────────────────────────────────────────────────────────────────────

def test_m279_plugin_module_exposes_load_engine():
    import slot_designer.machines.M279.plugins as plugin

    assert hasattr(plugin, "load_engine")
    assert callable(plugin.load_engine)


def test_m279_plugin_module_exposes_sample_one_chunk():
    import slot_designer.machines.M279.plugins as plugin

    assert hasattr(plugin, "sample_one_chunk")
    assert callable(plugin.sample_one_chunk)


def test_m279_plugin_module_exposes_compute_schema_fingerprint():
    import slot_designer.machines.M279.plugins as plugin

    assert hasattr(plugin, "compute_schema_fingerprint")
    assert callable(plugin.compute_schema_fingerprint)


def test_m279_plugin_module_exposes_build_plugin_returning_none():
    """M279 has no FeaturePlugin-shape feature. build_plugin must return
    None so the FeaturePlugin loading path skips it cleanly."""
    import slot_designer.machines.M279.plugins as plugin

    assert hasattr(plugin, "build_plugin")
    spec = json.loads(_M279_SPEC.read_text(encoding="utf-8"))
    weights = json.loads(_M279_WEIGHTS_M1.read_text(encoding="utf-8"))
    assert plugin.build_plugin(spec, weights) is None


# ─────────────────────────────────────────────────────────────────────
# importlib resolution path that virtual_analyzer uses
# ─────────────────────────────────────────────────────────────────────

def test_virtual_analyzer_load_custom_engine_module_resolves_m279():
    """virtual_analyzer._load_custom_engine_module(entry) imports the
    plugin package given a registry entry. Verify it works for the
    M279 entry without crashing."""
    from slot_designer.core.backend.virtual_analyzer import _load_custom_engine_module

    fake_entry = {
        "machine": "M279sim",
        "_source_machine": "M279",
        "_engine": "custom",
    }
    module = _load_custom_engine_module(fake_entry)
    # All three callables present
    assert callable(module.load_engine)
    assert callable(module.sample_one_chunk)
    assert callable(module.compute_schema_fingerprint)


def test_virtual_analyzer_load_custom_engine_module_falls_back_to_machine_field():
    """Entry without ``_source_machine`` falls back to ``machine``
    field. Backwards compat with hand-curated registry entries."""
    from slot_designer.core.backend.virtual_analyzer import _load_custom_engine_module

    fake_entry = {
        "machine": "M279",
        "_engine": "custom",
    }
    module = _load_custom_engine_module(fake_entry)
    assert callable(module.load_engine)


# ─────────────────────────────────────────────────────────────────────
# Adapter signature smoke — load_engine works
# ─────────────────────────────────────────────────────────────────────

def test_m279_load_engine_returns_engine_and_spec():
    import slot_designer.machines.M279.plugins as plugin

    engine, spec = plugin.load_engine(_M279_SPEC, _M279_WEIGHTS_M1)
    assert engine is not None
    assert isinstance(spec, dict)
    assert spec.get("machine") == "M279"


# ─────────────────────────────────────────────────────────────────────
# End-to-end: sample one chunk through the adapter
# ─────────────────────────────────────────────────────────────────────

def test_m279_sample_one_chunk_via_adapter_produces_valid_chunk():
    """Call the adapter end-to-end like virtual_analyzer would: load
    engine, compute schema_fp, sample one chunk. Verify chunk shape
    matches what the analyzer expects (machine + mode tags + non-empty
    robots).
    """
    import slot_designer.machines.M279.plugins as plugin

    engine, spec = plugin.load_engine(_M279_SPEC, _M279_WEIGHTS_M1)
    schema_fp = plugin.compute_schema_fingerprint(
        engine,
        mode=int(spec["mode"]),
        spins_per_robot=10,
    )
    rng = Random(0)
    chunk, c_win, c_bet = plugin.sample_one_chunk(
        engine,
        machine="M279sim",
        mode=int(spec["mode"]),
        chunk_index=1,
        robots=2,
        spins_per_robot=10,
        rng=rng,
        schema_fp=schema_fp,
        config_md5="cfg-stub",
        code_md5="code-stub",
    )
    assert isinstance(chunk, dict)
    assert chunk.get("_machine") == "M279sim"
    assert chunk.get("_mode") == int(spec["mode"])
    assert chunk.get("_config_md5") == "cfg-stub"
    assert chunk.get("_code_md5") == "code-stub"
    assert isinstance(c_win, int)
    assert c_bet > 0  # 2 robots × 10 spins × bet


# ─────────────────────────────────────────────────────────────────────
# Per-machine md5 isolation — M279 plugin churn doesn't bleed to others
# ─────────────────────────────────────────────────────────────────────

def test_m279_plugin_change_isolates_to_m279_md5():
    """Change a file inside machines/M279/plugins/m279/ → only M279's
    code_md5 flips; M1 / M15 / M37 unchanged.

    This duplicates one assertion from
    test_per_machine_code_md5.py but specifically targets the deeper
    M279 subpackage layout (plugins/m279/<file>.py) rather than just
    plugins/<file>.py — confirms the recursive rglob really walks the
    full tree."""
    from slot_designer.core.backend.machine_version import compute_code_md5

    target = _SLOT_DESIGNER / "machines" / "M279" / "plugins" / "m279" / "engine.py"
    assert target.exists()
    machines = ["M1", "M15", "M37", "M279"]
    before = {m: compute_code_md5(m) for m in machines}

    original = target.read_bytes()
    target.write_bytes(original + b"\n# Phase-D mutation\n")
    try:
        after = {m: compute_code_md5(m) for m in machines}
    finally:
        target.write_bytes(original)

    assert after["M279"] != before["M279"]
    for m in ("M1", "M15", "M37"):
        assert after[m] == before[m], (
            f"M279 plugin/m279/engine.py mutation leaked into {m}'s md5"
        )
