"""M43 per-machine code_md5 isolation (ARCHITECTURE §4 + §5.4 invariant).

Touching ``slot_designer/machines/M43/plugins/*.py`` must:
  - flip ``compute_code_md5('M43')``
  - leave every OTHER machine's ``compute_code_md5`` unchanged

This prevents the fleet-wide-cache-invalidation regression — per
``memory/feedback_md5_granularity_and_stamping.md``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SLOT_DESIGNER = _REPO_ROOT / "slot_designer"
_OTHER_MACHINES = ["M1", "M15", "M37", "M279"]


def _compute():
    from slot_designer.core.backend.machine_version import compute_code_md5
    return compute_code_md5


def test_m43_code_md5_differs_from_other_machines():
    """M43 plugin tree is distinct from M1/M15/M37/M279, so md5 differs."""
    compute = _compute()
    m43 = compute("M43")
    for other in _OTHER_MACHINES:
        other_md5 = compute(other)
        assert m43 != other_md5, (
            f"M43 code_md5 ({m43[:8]}...) == {other} code_md5 "
            f"({other_md5[:8]}...). M43 must have a distinct plugin tree."
        )


def test_changing_m43_plugin_changes_only_m43_md5(tmp_path):
    """Mutate machines/M43/plugins/feature.py → only M43's md5 flips."""
    compute = _compute()

    before_m43 = compute("M43")
    before_others = {m: compute(m) for m in _OTHER_MACHINES}

    target = _SLOT_DESIGNER / "machines" / "M43" / "plugins" / "feature.py"
    assert target.exists()
    original_bytes = target.read_bytes()
    target.write_bytes(original_bytes + b"\n# TDD-isolation-mutation\n")
    try:
        after_m43 = compute("M43")
        after_others = {m: compute(m) for m in _OTHER_MACHINES}
    finally:
        target.write_bytes(original_bytes)

    assert after_m43 != before_m43, (
        f"mutation of {target.relative_to(_SLOT_DESIGNER)} did NOT flip "
        f"M43's code_md5 — plugin dir not in M43's hash"
    )
    for other, before in before_others.items():
        after = after_others[other]
        assert after == before, (
            f"M43 plugin mutation leaked into {other}'s code_md5 "
            f"(before={before[:8]}, after={after[:8]}). Plugin trees "
            f"must be isolated per machine."
        )


def test_changing_other_machine_plugin_does_not_change_m43_md5():
    """Inverse: mutate M15's plugin → M43's md5 stays the same."""
    compute = _compute()

    before_m43 = compute("M43")

    target = _SLOT_DESIGNER / "machines" / "M15" / "plugins" / "feature.py"
    assert target.exists()
    original_bytes = target.read_bytes()
    target.write_bytes(original_bytes + b"\n# TDD-cross-machine-mutation\n")
    try:
        after_m43 = compute("M43")
    finally:
        target.write_bytes(original_bytes)

    assert after_m43 == before_m43, (
        f"mutating M15 plugin flipped M43's code_md5 "
        f"(before={before_m43[:8]}, after={after_m43[:8]}). "
        f"Cross-machine isolation violation."
    )


def test_changing_m43_spec_or_strips_does_not_change_code_md5():
    """spec.json / reel_strips.json / weights.json are config_md5
    territory, NOT code_md5. Editing them must not flip code_md5."""
    compute = _compute()
    before = compute("M43")

    spec = _SLOT_DESIGNER / "machines" / "M43" / "spec.json"
    original_bytes = spec.read_bytes()
    spec.write_bytes(original_bytes + b"\n")  # trailing whitespace
    try:
        after = compute("M43")
    finally:
        spec.write_bytes(original_bytes)

    assert after == before, (
        f"editing spec.json flipped M43's code_md5 — spec is "
        f"config_md5 territory, not code_md5"
    )
