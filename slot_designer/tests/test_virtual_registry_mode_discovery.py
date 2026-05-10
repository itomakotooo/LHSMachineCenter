"""Regression: ``refresh_machines_virtual`` auto-discovers on-disk
modes and adds them to the registry entry's ``modes`` list.

Why this matters (2026-04-23 failure):
  Operator ran ``derive_m15_mode_7.py`` + Phase 4 tune for mode 2 + copy
  for mode 5, which created ``weights/M15/mode_{2,5,7}/weights.json``
  on disk. Registry entry still had ``modes: [1]`` from the original
  M15 onboarding. Downstream UIs that iterate ``entry["modes"]``
  (rwtree rendering, batch-run mode filter, per-mode md5 lookup) never
  saw the new modes → sampled mode 7 chunks sat on disk with a proper
  report but the rwtree showed only Mode 1 cards.

  Before the fix, ``refresh_machines_virtual`` faithfully RECOMPUTED
  the md5 for every mode ALREADY in ``modes`` — but it never LEARNED
  about new modes. Adding a new mode required hand-editing
  machines_virtual.json, which no workflow step documented.

Fix: ``_discover_modes_on_disk(entry)`` scans
``slot_designer/weights/<MACHINE>/mode_<N>/weights.json`` and
``refresh_machines_virtual`` unions the discovered set with the
existing ``modes``. Never removes a mode — a missing weights file
shouldn't silently drop it from the registry (could be mid-edit).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.backend.virtual_registry import (
    _discover_modes_on_disk,
    refresh_machines_virtual,
)


def _make_machine_fixture(tmp_path: Path, machine: str, modes_to_create: list[int]) -> dict:
    """Build a minimal virtual-machine fixture on disk.

    Creates a machine dir with spec + strips + per-mode weights, then
    returns a registry entry dict pointing at those paths.
    """
    # Lay out weights/<machine>/ in the temp path mimicking real repo
    # layout so relative path templates work with a patched _SLOT_DESIGNER.
    machine_dir = tmp_path / "weights" / machine
    machine_dir.mkdir(parents=True)
    (machine_dir / "reel_strips.json").write_text(
        json.dumps({
            "machine": machine, "reel_set": "default",
            "reels": [["blank", "cherry", "blank", "3bar"]],
        }),
        encoding="utf-8",
    )
    for mode in modes_to_create:
        (machine_dir / f"mode_{mode}").mkdir()
        (machine_dir / f"mode_{mode}" / "weights.json").write_text(
            json.dumps({
                "machine": machine, "mode": mode, "reel_set": "default",
                "weights": [[1, 1, 1, 1]],
            }),
            encoding="utf-8",
        )
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    (specs_dir / f"{machine}.spec.json").write_text(
        json.dumps({
            "machine": machine, "mode": 1, "schema_version": 2,
            "grid": {"cols": 1, "rows": 3,
                     "paylines": [{"line_id": 1, "positions": [[0, 1]]}]},
            "symbols": {"blank": {"kind": "filler"}, "cherry": {"kind": "cherry_special"},
                        "3bar": {"kind": "regular"}},
            "pays": [],
            "evaluation_order": [],
            "spin_types": {"1": {"kind": "paid", "cost_per_spin": 1000,
                                 "bet_amount": 1000, "reel_set": "default"}},
        }),
        encoding="utf-8",
    )
    return {
        "machine": f"{machine}sim",
        "modes": [1],  # curated to start with only mode 1
        "_spec_path": f"slot_designer/specs/{machine}.spec.json",
        "_strips_path": f"slot_designer/weights/{machine}/reel_strips.json",
        "_weights_path_template": (
            f"slot_designer/weights/{machine}/mode_{{mode}}/weights.json"
        ),
    }


def test_discover_modes_returns_all_mode_dirs_with_weights(tmp_path, monkeypatch):
    """Core discovery: find every mode_<N>/weights.json under the
    machine's weights dir, ignoring non-mode subdirs and mode dirs
    missing weights.json.
    """
    # Patch _SLOT_DESIGNER to the tmp path so relative paths resolve.
    import slot_designer.core.backend.virtual_registry as vr
    monkeypatch.setattr(vr, "_SLOT_DESIGNER", tmp_path / "slot_designer")
    # Also patch machine_version's _SLOT_DESIGNER since resolve_weights_paths
    # uses it for the parent.
    import slot_designer.core.backend.machine_version as mv
    monkeypatch.setattr(mv, "_SLOT_DESIGNER", tmp_path / "slot_designer")

    # Relocate fixture under tmp_path/slot_designer/ so _SLOT_DESIGNER.parent
    # (the "repo root") becomes tmp_path.
    sd = tmp_path / "slot_designer"
    sd.mkdir()
    entry = _make_machine_fixture(sd, "Mfake", modes_to_create=[1, 2, 5, 7])

    # Add a junk subdir that should NOT be treated as a mode
    (sd / "weights" / "Mfake" / "not_a_mode").mkdir()
    # Add a mode dir without weights.json — should also be ignored
    (sd / "weights" / "Mfake" / "mode_99").mkdir()

    discovered = _discover_modes_on_disk(entry)
    assert discovered == [1, 2, 5, 7], (
        f"should find exactly the modes with weights.json; got {discovered}"
    )


def test_discover_modes_empty_when_template_missing(tmp_path, monkeypatch):
    """Entries without ``_weights_path_template`` (legacy real-console
    registrations) must not crash discovery — return empty and let
    ``refresh_machines_virtual`` fall back to the curated modes list.
    """
    assert _discover_modes_on_disk({}) == []
    assert _discover_modes_on_disk({"modes": [1]}) == []  # no template


def test_refresh_unions_discovered_modes_into_registry(tmp_path, monkeypatch):
    """End-to-end: calling ``refresh_machines_virtual`` on a registry
    where the entry says ``modes: [1]`` but disk has ``mode_1, mode_2,
    mode_5, mode_7`` must write back ``modes: [1, 2, 5, 7]`` with the
    per-mode md5 map covering all four.

    Inject-bug check: before this fix, the same invocation would leave
    ``modes: [1]`` alone and ``modesMd5`` would only carry mode 1's
    hashes. Asserting the full set post-call pins the new behavior.
    """
    import slot_designer.core.backend.virtual_registry as vr
    import slot_designer.core.backend.machine_version as mv
    sd = tmp_path / "slot_designer"
    sd.mkdir()
    monkeypatch.setattr(vr, "_SLOT_DESIGNER", sd)
    monkeypatch.setattr(mv, "_SLOT_DESIGNER", sd)

    entry = _make_machine_fixture(sd, "Mfake", modes_to_create=[1, 2, 5, 7])
    registry = {"machines": [entry]}
    config_path = tmp_path / "machines_virtual.json"
    config_path.write_text(json.dumps(registry), encoding="utf-8")

    refreshed = refresh_machines_virtual(config_path)
    updated_entry = refreshed["machines"][0]

    assert updated_entry["modes"] == [1, 2, 5, 7], (
        f"discovered modes should be unioned into entry['modes']; got {updated_entry['modes']}"
    )
    assert set((updated_entry.get("modesMd5") or {}).keys()) == {"1", "2", "5", "7"}, (
        f"every discovered mode needs a modesMd5 entry; got "
        f"{list((updated_entry.get('modesMd5') or {}).keys())}"
    )


def test_refresh_never_removes_existing_modes(tmp_path, monkeypatch):
    """Protection: if a mode is declared in the curated ``modes`` list
    but its weights.json is temporarily missing (mid-edit / partial
    checkout), refresh should LEAVE the mode in the list. Modes are
    additive-only from disk — removal requires an explicit operator
    edit.
    """
    import slot_designer.core.backend.virtual_registry as vr
    import slot_designer.core.backend.machine_version as mv
    sd = tmp_path / "slot_designer"
    sd.mkdir()
    monkeypatch.setattr(vr, "_SLOT_DESIGNER", sd)
    monkeypatch.setattr(mv, "_SLOT_DESIGNER", sd)

    # Disk has only mode_1; entry claims modes [1, 2] (mode 2's file deleted mid-edit)
    entry = _make_machine_fixture(sd, "Mfake", modes_to_create=[1])
    entry["modes"] = [1, 2]
    registry = {"machines": [entry]}
    config_path = tmp_path / "machines_virtual.json"
    config_path.write_text(json.dumps(registry), encoding="utf-8")

    refreshed = refresh_machines_virtual(config_path)
    updated_entry = refreshed["machines"][0]

    # Mode 2 must survive — curator knew about it, disk gap is transient.
    assert 2 in updated_entry["modes"], (
        "refresh must not drop a curated mode when its weights.json is missing"
    )
    assert 1 in updated_entry["modes"]


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        print(f"ad-hoc run in {d} — use pytest for full fixture isolation")
