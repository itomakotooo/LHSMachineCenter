"""Phase A target layout — directory invariants.

Asserts the post-Phase-A layout exists. Per ARCHITECTURE.md §2:

  slot_designer/
  ├── core/
  │   ├── engine/      (moved from slot_designer/engine/)
  │   ├── emitter/     (moved from slot_designer/emitter/)
  │   ├── tuner/       (moved from slot_designer/tuner/)
  │   ├── devtools/    (moved from slot_designer/devtools/)
  │   └── backend/     (moved from slot_designer/backend/)
  │
  └── machines/
      ├── M1/          (moved from specs/M1.spec.json + weights/M1/)
      │   ├── spec.json
      │   ├── reel_strips.json
      │   └── weights/mode_<N>/weights.json
      ├── M15/         (+ plugins/feature.py from engine/feature_m15.py)
      ├── M37/
      └── M279/        (+ plugins/ from engine/m279/ + emitter/m279_*.py)

This test asserts the LAYOUT exists. It does NOT test absence of legacy
imports inside core/ — that's the §7 forbidden-zone enforcement which
lands in Phase C with the FeaturePlugin protocol decoupling.

TDD note: this test is RED before Phase A moves and turns GREEN once
git mv + import fixes complete. Run via:

    python -m pytest slot_designer/tests/core/test_layout.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest


_SLOT_DESIGNER = Path(__file__).resolve().parents[2]


# ─────────────────────────────────────────────────────────────────────
# core/ subtree
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "subdir",
    ["engine", "emitter", "tuner", "devtools", "backend"],
)
def test_core_subdir_exists(subdir: str) -> None:
    """core/<subdir>/ must exist as a Python package (with __init__.py)."""
    p = _SLOT_DESIGNER / "core" / subdir
    assert p.is_dir(), f"missing core/{subdir}/ directory"
    init = p / "__init__.py"
    assert init.exists(), f"missing core/{subdir}/__init__.py"


@pytest.mark.parametrize(
    "filename",
    ["spin.py", "loader.py", "evaluator.py", "reel_strip.py", "rules.py", "symbol.py"],
)
def test_core_engine_has_framework_files(filename: str) -> None:
    """Generic engine framework files moved into core/engine/."""
    p = _SLOT_DESIGNER / "core" / "engine" / filename
    assert p.is_file(), f"missing core/engine/{filename}"


@pytest.mark.parametrize(
    "filename",
    ["chunk.py", "round.py", "robot.py", "driver.py"],
)
def test_core_emitter_has_framework_files(filename: str) -> None:
    """Generic emitter framework files moved into core/emitter/."""
    p = _SLOT_DESIGNER / "core" / "emitter" / filename
    assert p.is_file(), f"missing core/emitter/{filename}"


def test_core_does_not_contain_machine_specific_files() -> None:
    """core/engine/ + core/emitter/ must not contain machine-name modules.

    Phase A moves them out:
      - engine/feature_m15.py    -> machines/M15/plugins/feature.py
      - engine/m279/             -> machines/M279/plugins/
      - emitter/m279_round.py    -> machines/M279/plugins/
      - emitter/m279_driver.py   -> machines/M279/plugins/
    """
    forbidden = []
    for sub in ("engine", "emitter"):
        d = _SLOT_DESIGNER / "core" / sub
        if not d.exists():
            continue
        for f in d.rglob("*.py"):
            # Skip pycache residue (cleaned via pytest config + ignored at git)
            if "__pycache__" in f.parts:
                continue
            name = f.name.lower()
            # M\d+ in a filename or in a directory name = machine-specific
            if any(token in name for token in ("m15", "m279", "m1_", "m37_")):
                forbidden.append(str(f.relative_to(_SLOT_DESIGNER)))
    assert not forbidden, (
        f"core/ contains machine-specific files (must move to "
        f"machines/<M>/plugins/): {forbidden}"
    )


# ─────────────────────────────────────────────────────────────────────
# machines/ subtree
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("machine", ["M1", "M15", "M37", "M279"])
def test_machine_dir_has_required_files(machine: str) -> None:
    """machines/<M>/ must contain spec.json + reel_strips.json."""
    md = _SLOT_DESIGNER / "machines" / machine
    assert md.is_dir(), f"missing machines/{machine}/ directory"
    assert (md / "spec.json").is_file(), f"missing machines/{machine}/spec.json"
    assert (md / "reel_strips.json").is_file(), (
        f"missing machines/{machine}/reel_strips.json"
    )


@pytest.mark.parametrize("machine", ["M1", "M15", "M37", "M279"])
def test_machine_has_at_least_mode_1_weights(machine: str) -> None:
    """Every machine ships at least mode_1/weights.json."""
    p = (
        _SLOT_DESIGNER
        / "machines"
        / machine
        / "weights"
        / "mode_1"
        / "weights.json"
    )
    assert p.is_file(), f"missing machines/{machine}/weights/mode_1/weights.json"


def test_m279_has_plugins_dir() -> None:
    """M279 has machine-specific engine + emitter — must live under plugins/."""
    p = _SLOT_DESIGNER / "machines" / "M279" / "plugins"
    assert p.is_dir(), "missing machines/M279/plugins/ directory"
    assert (p / "__init__.py").exists(), "missing machines/M279/plugins/__init__.py"


def test_m15_has_plugins_dir() -> None:
    """M15 has feature engine — must live under plugins/."""
    p = _SLOT_DESIGNER / "machines" / "M15" / "plugins"
    assert p.is_dir(), "missing machines/M15/plugins/ directory"
    assert (p / "__init__.py").exists(), "missing machines/M15/plugins/__init__.py"


# ─────────────────────────────────────────────────────────────────────
# legacy-tree absence (post-restructure)
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "legacy_path",
    [
        "engine",       # moved to core/engine + machines/<M>/plugins
        "emitter",      # moved to core/emitter + machines/<M>/plugins
        "tuner",        # moved to core/tuner
        "devtools",     # moved to core/devtools
        "backend",      # moved to core/backend
        "specs",        # moved to machines/<M>/spec.json
        "weights",      # moved to machines/<M>/weights
    ],
)
def test_legacy_dir_removed(legacy_path: str) -> None:
    """The pre-Phase-A directories must NOT remain after restructure.

    Catches half-done restructure where files moved but the old empty
    directory (or worse: stale duplicates) remains.
    """
    p = _SLOT_DESIGNER / legacy_path
    assert not p.exists(), (
        f"legacy slot_designer/{legacy_path}/ still exists after Phase A"
    )
