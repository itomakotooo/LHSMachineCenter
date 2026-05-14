"""M31 code_md5 isolation test.

ARCHITECTURE §5.4 required test: test_<M>_md5_isolation.py
Per ARCHITECTURE §4 and test pattern in tests/core/test_per_machine_code_md5.py:

  compute_code_md5("M31") hashes:
    1. core/engine/**/*.py
    2. core/emitter/**/*.py
    3. machines/M31/plugins/**/*.py  (plugin tree)

  Mutation propagation:
    - Changing machines/M31/plugins/* → only M31 md5 changes
    - Other machines (M15/M37/M279) md5 unchanged
    - M31 md5 != M15 md5 (different plugin trees)

Asserts:
  1. compute_code_md5("M31") != compute_code_md5("M15")
  2. compute_code_md5("M31") != compute_code_md5("M37")  (M37 is base-only)
  3. Mutating machines/M31/plugins/feature.py flips ONLY M31's md5
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SLOT_DESIGNER = _ROOT / "slot_designer"


def _compute(machine_name: str) -> str:
    from slot_designer.core.backend.machine_version import compute_code_md5
    return compute_code_md5(machine_name)


_MACHINES_WITH_PLUGINS = ["M15", "M279", "M31"]
_MACHINES_BASE_ONLY = ["M1", "M37"]
_ALL_MACHINES = _MACHINES_WITH_PLUGINS + _MACHINES_BASE_ONLY


# ─────────────────────────────────────────────────────────────────────
# Basic invariants
# ─────────────────────────────────────────────────────────────────────

def test_compute_code_md5_m31_returns_string():
    """compute_code_md5('M31') returns a 32-char hex string."""
    md5 = _compute("M31")
    assert isinstance(md5, str)
    assert len(md5) == 32, f"Expected 32-char md5, got {len(md5)}: {md5!r}"


def test_compute_code_md5_m31_is_deterministic():
    """compute_code_md5('M31') is deterministic across calls."""
    a = _compute("M31")
    b = _compute("M31")
    assert a == b, "md5 must be deterministic"


def test_m31_md5_differs_from_m15():
    """M31 and M15 have different plugin trees → different code_md5.

    Invariant (ARCHITECTURE §4): per-machine code_md5 isolates plugin changes.
    """
    m31 = _compute("M31")
    m15 = _compute("M15")
    assert m31 != m15, (
        f"M31 and M15 plugin trees differ, must have different code_md5. "
        f"Got M31={m31[:8]}... M15={m15[:8]}..."
    )


def test_m31_md5_differs_from_m37():
    """M31 (has plugins/) and M37 (base-only) must have different code_md5."""
    m31 = _compute("M31")
    m37 = _compute("M37")
    assert m31 != m37, (
        f"M31 (plugin machine) must have different md5 from M37 (base-only). "
        f"Got M31={m31[:8]}... M37={m37[:8]}..."
    )


def test_m31_md5_differs_from_m279():
    """M31 and M279 have different plugin trees → different code_md5."""
    m31 = _compute("M31")
    m279 = _compute("M279")
    assert m31 != m279, (
        f"M31 and M279 must have different code_md5 (different plugin trees). "
        f"Got M31={m31[:8]}... M279={m279[:8]}..."
    )


# ─────────────────────────────────────────────────────────────────────
# Mutation isolation — changing M31 plugin flips only M31
# ─────────────────────────────────────────────────────────────────────

def _baseline_md5s() -> dict[str, str]:
    return {m: _compute(m) for m in _ALL_MACHINES}


def test_mutating_m31_plugin_flips_only_m31_md5():
    """Mutating machines/M31/plugins/feature.py flips M31's code_md5 ONLY.

    Verifies ARCHITECTURE §4 per-machine isolation:
      changing machines/M31/plugins/* → only M31 md5 changes.
    """
    plugin_dir = _SLOT_DESIGNER / "machines" / "M31" / "plugins"
    plugin_files = [
        p for p in plugin_dir.rglob("*.py")
        if p.name != "__init__.py" and "__pycache__" not in str(p)
    ]
    assert plugin_files, (
        "machines/M31/plugins/ has no non-init .py files to mutate"
    )
    target = plugin_files[0]  # feature.py
    original_bytes = target.read_bytes()

    before = _baseline_md5s()
    target.write_bytes(original_bytes + b"\n# M31-md5-isolation-mutation\n")
    try:
        after = _baseline_md5s()
    finally:
        target.write_bytes(original_bytes)  # always restore

    assert after["M31"] != before["M31"], (
        f"Changing {target.name} did NOT flip M31's code_md5 — "
        "machines/M31/plugins/ must be in M31's hash"
    )
    for other_machine in _ALL_MACHINES:
        if other_machine == "M31":
            continue
        assert after[other_machine] == before[other_machine], (
            f"Changing M31's plugin leaked into {other_machine}'s code_md5. "
            f"Plugin trees must be isolated per ARCHITECTURE §4."
        )


# ─────────────────────────────────────────────────────────────────────
# Negative space — other machines' plugins don't affect M31
# ─────────────────────────────────────────────────────────────────────

def test_mutating_m15_plugin_does_not_change_m31_md5():
    """Changing M15 plugin must NOT flip M31's md5."""
    plugin_dir = _SLOT_DESIGNER / "machines" / "M15" / "plugins"
    plugin_files = [
        p for p in plugin_dir.rglob("*.py")
        if p.name != "__init__.py" and "__pycache__" not in str(p)
    ]
    if not plugin_files:
        pytest.skip("M15 plugin files not found")
    target = plugin_files[0]
    original_bytes = target.read_bytes()

    before_m31 = _compute("M31")
    target.write_bytes(original_bytes + b"\n# M15-cross-mutation-test\n")
    try:
        after_m31 = _compute("M31")
    finally:
        target.write_bytes(original_bytes)

    assert after_m31 == before_m31, (
        "Changing M15's plugin leaked into M31's code_md5. "
        "Plugin trees must be isolated per ARCHITECTURE §4."
    )


def test_mutating_core_engine_changes_m31_md5():
    """Changing core/engine/spin.py MUST flip M31's md5 (fleet-wide framework change)."""
    target = _SLOT_DESIGNER / "core" / "engine" / "spin.py"
    assert target.exists()
    original_bytes = target.read_bytes()

    before_m31 = _compute("M31")
    target.write_bytes(original_bytes + b"\n# M31-core-mutation-test\n")
    try:
        after_m31 = _compute("M31")
    finally:
        target.write_bytes(original_bytes)

    assert after_m31 != before_m31, (
        "Changing core/engine/spin.py should flip M31's code_md5 "
        "(core changes are fleet-wide per ARCHITECTURE §4)"
    )
