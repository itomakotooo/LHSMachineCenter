"""Regression: adding a mode to a machine MUST NOT invalidate pre-
existing modes' chunks / reports.

2026-04-22 incident: the user tuned M1sim mode 2, which added mode 2
weights to the registry. The old ``compute_machine_md5`` hashed
spec + ALL mode weights into one machine-level ``configSummaryMd5``,
so the machine-level md5 flipped even though mode 1's
``reel_weights.json`` was byte-identical. Every existing mode 1 chunk
(stamped with the old md5) was reclassified as historical.

Fix (2026-04-22): switch to PER-MODE config_md5.
  * ``compute_machine_md5_for_mode(entry, mode)`` hashes spec +
    THAT mode's weights only.
  * Registry entry carries ``modesMd5: {"N": {cfg, code}}``.
  * ``_get_machine_md5(machine, config, mode=N)`` returns the
    per-mode pair when available, else falls back to machine-level.
  * ``check_rawdata_status`` / ``_classify_chunks`` /
    ``validate_machine_reports`` all pass mode and compare per-mode.

Invariants the tests lock:
  1. Adding mode 2 doesn't change mode 1's per-mode md5.
  2. Registry's per-mode map stores distinct cfg for each mode.
  3. ``_get_machine_md5`` returns per-mode md5 when mode is passed
     AND the entry has a modesMd5 map.
  4. ``_get_machine_md5`` falls back to machine-level md5 when mode
     is missing or the entry doesn't have modesMd5 (real-console
     schema path).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.backend.machine_version import (
    compute_machine_md5,
    compute_machine_md5_for_mode,
)


def _entry_for_modes(modes: list[int]) -> dict:
    """Build a machines_virtual.json-shape entry for M1sim with
    arbitrary mode list. Uses the real spec + weights on disk."""
    return {
        "machine": "M1sim",
        "modes": modes,
        "_source_machine": "M1",
        "_spec_path": "slot_designer/specs/M1.spec.json",
        "_weights_path_template": "slot_designer/weights/M1/mode_{mode}/reel_weights.json",
    }


def test_adding_mode_does_not_change_existing_mode_per_mode_md5():
    """The key regression: computing mode 1's md5 should produce the
    same value whether mode 2 is in the registry or not.

    Before the fix: ``compute_machine_md5`` hashed spec + [w1, w2],
    so adding mode 2 flipped the hash for mode 1's chunks too.
    After: ``compute_machine_md5_for_mode(entry, 1)`` hashes spec +
    only w1 — immune to mode 2 being present.
    """
    entry_1_only = _entry_for_modes([1])
    entry_1_and_2 = _entry_for_modes([1, 2])

    cfg_only, code_only = compute_machine_md5_for_mode(entry_1_only, 1)
    cfg_with, code_with = compute_machine_md5_for_mode(entry_1_and_2, 1)

    assert cfg_only == cfg_with, (
        f"mode 1 per-mode cfg changed when mode 2 was added to the "
        f"machine: {cfg_only!r} → {cfg_with!r}. This is the bug — "
        f"mode 1 chunks would be reclassified as historical."
    )
    assert code_only == code_with, "code_md5 also must be mode-independent"


def test_per_mode_md5_distinct_per_mode():
    """Mode 1 and mode 2 weights files DIFFER — so their per-mode
    cfg_md5 MUST also differ. If they collided, chunks from mode 1
    could be silently accepted as mode 2 chunks."""
    entry = _entry_for_modes([1, 2])
    cfg1, _ = compute_machine_md5_for_mode(entry, 1)
    cfg2, _ = compute_machine_md5_for_mode(entry, 2)
    assert cfg1 != cfg2, (
        f"mode 1 and mode 2 per-mode cfg_md5 collided: {cfg1!r}. "
        f"They must differ because M1/mode_1/reel_weights.json != "
        f"M1/mode_2/reel_weights.json."
    )


def test_machine_level_md5_is_still_aggregate():
    """``compute_machine_md5`` (non per-mode) still returns the
    aggregate. Useful for "has ANY mode changed?" UI indicator at
    the machine card header. This verifies that adding mode 2 DOES
    change the aggregate (contrast with the per-mode invariant)."""
    cfg_1_only, _ = compute_machine_md5(_entry_for_modes([1]))
    cfg_1_and_2, _ = compute_machine_md5(_entry_for_modes([1, 2]))
    assert cfg_1_only != cfg_1_and_2, (
        "aggregate machine-level md5 should differ when mode set "
        "changes (it's the 'machine has a new version' signal). "
        "This test locks the aggregate behavior separate from the "
        "per-mode behavior."
    )


def test_registry_stores_modes_md5_map_per_mode():
    """After ``refresh_machines_virtual``, the M1sim entry must have
    a ``modesMd5`` map with one entry per mode, each carrying its
    own cfg / code pair."""
    from slot_designer.backend.virtual_registry import (
        VIRTUAL_MACHINES_CONFIG,
        refresh_machines_virtual,
    )
    r = refresh_machines_virtual(VIRTUAL_MACHINES_CONFIG)
    entry = next(m for m in r["machines"] if m["machine"] == "M1sim")
    modes_md5 = entry.get("modesMd5")
    assert isinstance(modes_md5, dict), (
        f"M1sim entry must carry modesMd5 dict; got {modes_md5!r}"
    )
    # Must cover every mode in the entry's modes list
    for mode in entry.get("modes", []):
        assert str(mode) in modes_md5, (
            f"modesMd5 missing entry for mode {mode}"
        )
        per = modes_md5[str(mode)]
        assert per.get("configSummaryMd5"), (
            f"modesMd5[{mode}] missing configSummaryMd5: {per!r}"
        )
        assert per.get("codeSummaryMd5"), (
            f"modesMd5[{mode}] missing codeSummaryMd5: {per!r}"
        )


def test_backend_lookup_prefers_per_mode_md5():
    """``_get_machine_md5(machine, config, mode=N)`` must return the
    per-mode md5 when the registry has a modesMd5 map — not the
    top-level aggregate."""
    from src.web_console.backend.app import _get_machine_md5
    from slot_designer.backend.virtual_registry import (
        VIRTUAL_MACHINES_CONFIG,
        refresh_machines_virtual,
    )
    r = refresh_machines_virtual(VIRTUAL_MACHINES_CONFIG)
    entry = next(m for m in r["machines"] if m["machine"] == "M1sim")
    per_mode_1 = entry["modesMd5"]["1"]
    per_mode_2 = entry["modesMd5"]["2"]

    # Look up mode 1 via the backend helper — should match per-mode 1
    cfg1, code1 = _get_machine_md5("M1sim", VIRTUAL_MACHINES_CONFIG, mode=1)
    assert cfg1 == per_mode_1["configSummaryMd5"]
    assert code1 == per_mode_1["codeSummaryMd5"]

    cfg2, code2 = _get_machine_md5("M1sim", VIRTUAL_MACHINES_CONFIG, mode=2)
    assert cfg2 == per_mode_2["configSummaryMd5"]
    assert code2 == per_mode_2["codeSummaryMd5"]

    # Mode 1 vs mode 2 cfg MUST differ (otherwise the per-mode
    # distinction is lost and old bug returns)
    assert cfg1 != cfg2, (
        f"per-mode lookup returned identical cfg for modes 1 & 2: "
        f"{cfg1!r}. This means the fallback path fired — the entry "
        f"probably lacks modesMd5, or _get_machine_md5's mode branch "
        f"is broken."
    )


def test_backend_lookup_falls_back_when_mode_unknown():
    """``_get_machine_md5`` without mode (or with a mode not in
    modesMd5) must fall back to the top-level cfg/code — this is
    the real-console path where all modes share one reel strip."""
    from src.web_console.backend.app import _get_machine_md5
    from slot_designer.backend.virtual_registry import (
        VIRTUAL_MACHINES_CONFIG,
        refresh_machines_virtual,
    )
    r = refresh_machines_virtual(VIRTUAL_MACHINES_CONFIG)
    entry = next(m for m in r["machines"] if m["machine"] == "M1sim")

    # No mode arg → aggregate
    cfg_agg, code_agg = _get_machine_md5("M1sim", VIRTUAL_MACHINES_CONFIG)
    assert cfg_agg == entry["configSummaryMd5"]
    assert code_agg == entry["codeSummaryMd5"]

    # Mode not in modesMd5 → fallback to aggregate (graceful)
    cfg_unk, code_unk = _get_machine_md5(
        "M1sim", VIRTUAL_MACHINES_CONFIG, mode=99,
    )
    assert cfg_unk == entry["configSummaryMd5"]
    assert code_unk == entry["codeSummaryMd5"]


if __name__ == "__main__":
    import inspect

    mod = sys.modules[__name__]
    tests = [obj for name, obj in inspect.getmembers(mod)
             if name.startswith("test_") and callable(obj)]
    passed, failures = 0, []
    for t in tests:
        try:
            t()
            print(f"ok  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failures.append((t.__name__, e))
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if not failures else 1)
