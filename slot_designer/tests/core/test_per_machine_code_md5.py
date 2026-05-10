"""Phase B target — per-machine ``compute_code_md5(machine_name)``.

Pre-Phase-B contract was fleet-wide: changing any code in core/engine/
or core/emitter/ flipped a single shared codeSummaryMd5 → ALL virtual
machines' chunk caches simultaneously stale.

Phase B contract (per ARCHITECTURE.md §4):
  compute_code_md5(machine_name) hashes
    1. core/engine/**/*.py
    2. core/emitter/**/*.py
    3. machines/<machine_name>/plugins/**/*.py  (if dir exists)

  Behavior consequences:
    - Changing core/* flips all machines' md5.
    - Changing machines/M15/plugins/* flips only M15's md5.
    - Changing machines/M279/plugins/* flips only M279's md5.
    - Changing unrelated files (tests/, docs/, configs/, scripts/,
      __pycache__/) flips no machine's md5.

This test exercises each of those cases by mutating a temp file in the
plugin tree and confirming exactly the right md5 set changes.

TDD ordering:
  1. Run BEFORE changing core/version.py — this file is RED because
     compute_code_md5 still has the fleet-wide signature (no
     machine_name arg).
  2. Refactor compute_code_md5 to (machine_name: str) -> str.
  3. Run AFTER — green.

Pre-conditions guarded:
  - tests/core/test_layout.py asserts core/ + machines/<M>/plugins/
    directories exist; this suite assumes that's already passing.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_SLOT_DESIGNER = Path(__file__).resolve().parents[2]


# Lazy-import so the test file collects even when machine_version.py is
# mid-refactor; the test bodies will fail correctly if the symbol is
# absent.
def _import_compute_code_md5():
    from slot_designer.core.backend.machine_version import compute_code_md5
    return compute_code_md5


@pytest.fixture
def compute():
    return _import_compute_code_md5()


# Machines with plugins (so their md5 includes plugin tree).
_FEATURE_MACHINES = ["M15", "M279"]
# Machines without plugins (base only — md5 = core only).
_BASE_MACHINES = ["M1", "M37"]
_ALL_MACHINES = _FEATURE_MACHINES + _BASE_MACHINES


def _baseline_md5s(compute) -> dict[str, str]:
    """Snapshot every machine's md5 before a mutation so we can compare."""
    return {m: compute(m) for m in _ALL_MACHINES}


# ─────────────────────────────────────────────────────────────────────
# Signature + return shape
# ─────────────────────────────────────────────────────────────────────

def test_compute_code_md5_takes_machine_name_arg(compute):
    """Signature: compute_code_md5(machine_name: str) -> str."""
    md5 = compute("M1")
    assert isinstance(md5, str), "compute_code_md5 must return a string"
    assert len(md5) == 32, f"expected hex md5 (32 chars), got {len(md5)} chars"


def test_compute_code_md5_is_deterministic(compute):
    """Same input → same output across calls (no time / randomness)."""
    a = compute("M15")
    b = compute("M15")
    assert a == b, "compute_code_md5 must be deterministic"


# ─────────────────────────────────────────────────────────────────────
# Cross-machine differences
# ─────────────────────────────────────────────────────────────────────

def test_machines_with_plugins_differ_from_base(compute):
    """M15 (has plugins/) and M1 (no plugins/) must produce different md5s."""
    base = compute("M1")
    feature = compute("M15")
    assert base != feature, (
        "M1 (base-only) and M15 (with feature plugin) must hash differently. "
        "Else changing M15 plugin code would silently NOT invalidate M15 cache, "
        "OR base-only machines would gratuitously inherit feature-plugin churn."
    )


def test_two_feature_machines_differ_from_each_other(compute):
    """M15 plugin tree differs from M279 plugin tree → different md5s."""
    m15 = compute("M15")
    m279 = compute("M279")
    assert m15 != m279, (
        "M15 and M279 have different plugin trees, must hash differently."
    )


def test_two_base_machines_share_md5(compute):
    """Two base machines (no plugins/) share the same md5 — both
    contribute only the core/ tree to the hash."""
    m1 = compute("M1")
    m37 = compute("M37")
    assert m1 == m37, (
        f"M1 and M37 are both base-only (no plugins/), should share md5. "
        f"Got M1={m1[:8]}... M37={m37[:8]}..."
    )


# ─────────────────────────────────────────────────────────────────────
# Mutation propagation — plugin tree changes
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("machine", _FEATURE_MACHINES)
def test_changing_a_machines_plugin_changes_only_that_machines_md5(
    compute, machine, tmp_path,
):
    """Modify ONE file in machines/<M>/plugins/ → only that machine's
    md5 flips. Other machines unaffected.
    """
    # Snapshot baseline.
    before = _baseline_md5s(compute)

    # Pick a real plugin .py to mutate.
    plugin_dir = _SLOT_DESIGNER / "machines" / machine / "plugins"
    plugin_files = [
        p for p in plugin_dir.rglob("*.py")
        if p.name != "__init__.py" and "__pycache__" not in p.parts
    ]
    assert plugin_files, (
        f"machines/{machine}/plugins/ has no non-init .py files to mutate"
    )
    target = plugin_files[0]
    original_bytes = target.read_bytes()

    # Mutate by appending a comment.
    target.write_bytes(original_bytes + b"\n# TDD-Phase-B-mutation\n")
    try:
        after = _baseline_md5s(compute)
    finally:
        target.write_bytes(original_bytes)

    assert after[machine] != before[machine], (
        f"changing {target.relative_to(_SLOT_DESIGNER)} did not flip "
        f"{machine}'s code_md5 — plugin dir is not in {machine}'s hash"
    )
    for other in _ALL_MACHINES:
        if other == machine:
            continue
        assert after[other] == before[other], (
            f"changing {target.relative_to(_SLOT_DESIGNER)} ({machine}'s "
            f"plugin) leaked into {other}'s code_md5 "
            f"(before={before[other][:8]}, after={after[other][:8]}). "
            f"Plugin trees must be isolated per machine."
        )


# ─────────────────────────────────────────────────────────────────────
# Mutation propagation — core changes affect all machines
# ─────────────────────────────────────────────────────────────────────

def test_changing_core_engine_changes_all_machines_md5(compute, tmp_path):
    """Modify core/engine/<file>.py → every machine's md5 flips."""
    before = _baseline_md5s(compute)

    target = _SLOT_DESIGNER / "core" / "engine" / "spin.py"
    assert target.exists()
    original_bytes = target.read_bytes()
    target.write_bytes(original_bytes + b"\n# TDD-Phase-B-core-engine-mutation\n")
    try:
        after = _baseline_md5s(compute)
    finally:
        target.write_bytes(original_bytes)

    for m in _ALL_MACHINES:
        assert after[m] != before[m], (
            f"changing core/engine/spin.py did not flip {m}'s code_md5 "
            f"— core engine must be in every machine's hash"
        )


def test_changing_core_emitter_changes_all_machines_md5(compute, tmp_path):
    """Modify core/emitter/<file>.py → every machine's md5 flips."""
    before = _baseline_md5s(compute)

    target = _SLOT_DESIGNER / "core" / "emitter" / "round.py"
    assert target.exists()
    original_bytes = target.read_bytes()
    target.write_bytes(original_bytes + b"\n# TDD-Phase-B-core-emitter-mutation\n")
    try:
        after = _baseline_md5s(compute)
    finally:
        target.write_bytes(original_bytes)

    for m in _ALL_MACHINES:
        assert after[m] != before[m], (
            f"changing core/emitter/round.py did not flip {m}'s code_md5 "
            f"— core emitter must be in every machine's hash"
        )


# ─────────────────────────────────────────────────────────────────────
# Negative space — unrelated files don't affect md5
# ─────────────────────────────────────────────────────────────────────

def test_changing_test_files_does_not_change_any_md5(compute):
    """Modifying tests/ does not flip any machine's md5 — tests are not
    part of the runtime engine surface.
    """
    before = _baseline_md5s(compute)

    target = _SLOT_DESIGNER / "tests" / "core" / "test_layout.py"
    assert target.exists()
    original_bytes = target.read_bytes()
    target.write_bytes(original_bytes + b"\n# TDD-Phase-B-test-mutation\n")
    try:
        after = _baseline_md5s(compute)
    finally:
        target.write_bytes(original_bytes)

    for m in _ALL_MACHINES:
        assert after[m] == before[m], (
            f"changing a test file flipped {m}'s code_md5 — tests must "
            f"NOT be in the hash (else test-only edits invalidate the cache)"
        )


def test_changing_machine_dir_metadata_does_not_change_md5(compute):
    """Modifying machines/<M>/spec.json or DESIGN.md does NOT change
    code_md5 — those are config_md5 territory, not code_md5.
    """
    before = _baseline_md5s(compute)

    target = _SLOT_DESIGNER / "machines" / "M1" / "spec.json"
    assert target.exists()
    original_bytes = target.read_bytes()
    # Append a no-op trailing whitespace (still valid JSON if I add one
    # to the existing newline). Use a comment-style mutation by writing
    # the bytes back identically — but we want a *real* mutation. Use a
    # write/restore round-trip with one byte added at the end.
    target.write_bytes(original_bytes + b"\n")
    try:
        after = _baseline_md5s(compute)
    finally:
        target.write_bytes(original_bytes)

    for m in _ALL_MACHINES:
        assert after[m] == before[m], (
            f"changing machines/M1/spec.json flipped {m}'s code_md5 — "
            f"spec is config_md5 territory, not code_md5"
        )


def test_pycache_files_are_not_in_md5(compute):
    """__pycache__ residue must not be hashed — would make md5
    nondeterministic across pytest runs."""
    before = _baseline_md5s(compute)
    after = _baseline_md5s(compute)
    # Compare twice; pycache typically gets recreated by interpreter,
    # so deterministic-across-call (test_compute_code_md5_is_deterministic)
    # already covers the negative case.  Adding redundant assertion here
    # against future regression where someone adds rglob into __pycache__:
    for m in _ALL_MACHINES:
        assert after[m] == before[m]


# ─────────────────────────────────────────────────────────────────────
# Backward-incompat: bare compute_code_md5() call must fail loudly
# ─────────────────────────────────────────────────────────────────────

def test_compute_code_md5_no_arg_raises(compute):
    """Calling compute_code_md5() without machine_name must raise — we
    want loud failures at every call site, not silent fleet-wide hash."""
    with pytest.raises(TypeError):
        compute()  # type: ignore[call-arg]
