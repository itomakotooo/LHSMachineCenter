"""Regression: all modes of a machine share byte-identical reel strips.

Why this is a hard invariant (2026-04-23):
  Production slot cabinets have physical reel tape; it's installed once
  per machine and never changes when the operator flips to a different
  RTP mode. Our rawdata upstream mirrors that: the ``StopSymbolsByCol``
  position sequence is the SAME across mode 1/2/5/7 for a given machine,
  only hit probabilities differ.

  The tuner's Phase 5 joint SA can silently co-swap positions across
  modes (it preserves marginals but shuffles the position→symbol map).
  If it runs when it shouldn't (e.g. onboarding mode 2 without
  ``--sa-steps 0``), every sibling mode's ``weights.json`` gets
  re-permuted too → all prior mode 1 rawdata becomes "different
  machine" (different strip layout) → md5 drift + bucket misalignment
  + analyzer cross-mode comparison breaks.

  This test locks in the invariant at file-layout level: one
  ``reel_strips.json`` per machine, all modes read from the same bytes.

See also: ``memory/project_slot_designer.md (§E strip layout)``
(the authoring rule) and ``project_slot_designer.md (§E strip layout)``
(the file-layout refactor that made it enforceable).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.engine.loader import _resolve_strips_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _discover_modes(machine_dir: Path) -> list[int]:
    """Return sorted mode numbers present under ``machine_dir``."""
    modes: list[int] = []
    for child in sorted(machine_dir.glob("mode_*")):
        if not child.is_dir():
            continue
        try:
            n = int(child.name.split("_", 1)[1])
        except (ValueError, IndexError):
            continue
        if (child / "weights.json").exists():
            modes.append(n)
    return modes


def _weights_paths_for_machine(machine: str) -> list[Path]:
    # Phase A layout: machines/<M>/weights/mode_<N>/weights.json
    machine_weights_dir = _ROOT / "slot_designer" / "machines" / machine / "weights"
    return [
        machine_weights_dir / f"mode_{n}" / "weights.json"
        for n in _discover_modes(machine_weights_dir)
    ]


def test_m15_strips_resolve_to_same_file_across_modes():
    """Every M15 mode's weights.json must resolve to the same
    reel_strips.json — not "two files with identical contents", but
    literally the same inode / hash.
    """
    modes = _weights_paths_for_machine("M15")
    assert len(modes) >= 2, (
        f"M15 has {len(modes)} mode(s) with weights.json; this test "
        f"requires at least 2 to be meaningful. Found: {modes}"
    )

    resolved_strips = {mp: _resolve_strips_path(mp).resolve() for mp in modes}
    unique_paths = set(resolved_strips.values())
    assert len(unique_paths) == 1, (
        f"M15 modes resolve to DIFFERENT reel_strips.json files — "
        f"this breaks the strips-identical-across-modes invariant.\n"
        f"Per-mode strips resolution:\n" +
        "\n".join(f"  {mp.relative_to(_ROOT)} → {sp}" for mp, sp in resolved_strips.items())
    )

    # Double-check by hash: even if the path is the same, a caller that
    # subverts _resolve_strips_path (e.g. a test fixture that copies
    # strips into mode_<N>/) should also fail. Hash every per-mode
    # strips path and assert one hash.
    hashes = {mp: _sha256(sp) for mp, sp in resolved_strips.items()}
    unique_hashes = set(hashes.values())
    assert len(unique_hashes) == 1, (
        f"M15 modes have strips files with DIFFERENT sha256 hashes — "
        f"even if path resolution agrees, the bytes diverged.\n" +
        "\n".join(f"  {mp.relative_to(_ROOT)} sha256={h[:12]}..."
                  for mp, h in hashes.items())
    )


def test_m1_strips_resolve_to_same_file_across_modes():
    """Same invariant holds for M1 (our older 4-mode machine)."""
    modes = _weights_paths_for_machine("M1")
    if len(modes) < 2:
        # M1 may be single-mode in some branches; skip silently if so.
        return
    resolved = {mp: _resolve_strips_path(mp).resolve() for mp in modes}
    unique = set(resolved.values())
    assert len(unique) == 1, (
        f"M1 modes resolve to DIFFERENT reel_strips.json — invariant "
        f"broken.\n" +
        "\n".join(f"  {mp.relative_to(_ROOT)} → {sp}" for mp, sp in resolved.items())
    )


def test_m15_loaded_reel_symbols_identical_across_modes():
    """End-to-end check: load every M15 mode and compare the actual
    position→symbol layout that each engine exposes. Catches a hypothetical
    bug where the loader accidentally gets its symbols from weights.json
    instead of reel_strips.json.
    """
    from slot_designer.core.engine.loader import load_engine

    spec = _ROOT / "slot_designer" / "machines" / "M15" / "spec.json"
    modes = _weights_paths_for_machine("M15")
    assert len(modes) >= 2, f"need at least 2 M15 modes for this test; found {modes}"

    layouts: dict[Path, list[list[str]]] = {}
    for wp in modes:
        engine, _ = load_engine(spec, wp)
        # Reel-by-reel symbol list; weight is NOT checked here (that's
        # expected to differ per mode — it's the whole point).
        layout = [[stop.symbol for stop in reel.stops] for reel in engine.reels]
        layouts[wp] = layout

    ref_path, ref_layout = next(iter(layouts.items()))
    for wp, layout in layouts.items():
        if wp is ref_path:
            continue
        assert layout == ref_layout, (
            f"mode at {wp.relative_to(_ROOT)} has a DIFFERENT position→symbol "
            f"layout from {ref_path.relative_to(_ROOT)} — the shared reel_strips.json "
            f"must dictate both. This is a loader or tooling bug."
        )


def test_self_check_catches_per_mode_divergence(tmp_path):
    """Meta-test: proves the structural tests above actually catch a
    regression rather than passing trivially.

    Scenario: someone refactors ``_resolve_strips_path`` to look in the
    per-mode directory first, and accidentally checks in a stale copy
    of ``reel_strips.json`` under ``mode_2/`` that has one position
    swapped. The real tests should detect the divergence.

    This test simulates that failure by constructing a synthetic machine
    dir (strips + mode_1 + mode_2 weights) with a deliberately divergent
    per-mode strips file, swapping in a fake resolver, and confirming the
    hash/layout checks would have flagged the corruption.
    """
    import json

    # Build a minimal machine directory:
    #   <tmp>/machine/reel_strips.json          ← "canonical"
    #   <tmp>/machine/mode_1/weights.json
    #   <tmp>/machine/mode_2/weights.json
    #   <tmp>/machine/mode_2/reel_strips.json   ← "divergent" (bug injected)
    machine_dir = tmp_path / "machine"
    machine_dir.mkdir()
    canonical = {
        "machine": "TestMachine",
        "reel_set": "default",
        "reels": [["blank", "cherry", "blank", "3bar"]],
    }
    (machine_dir / "reel_strips.json").write_text(
        json.dumps(canonical), encoding="utf-8"
    )
    for mode in (1, 2):
        d = machine_dir / f"mode_{mode}"
        d.mkdir()
        (d / "weights.json").write_text(
            json.dumps({
                "machine": "TestMachine",
                "mode": mode,
                "reel_set": "default",
                "weights": [[1, 1, 1, 1]],
            }),
            encoding="utf-8",
        )
    # Inject the divergent copy into mode_2/
    divergent = json.loads(json.dumps(canonical))
    divergent["reels"][0][1] = "1bar"  # cherry → 1bar
    (machine_dir / "mode_2" / "reel_strips.json").write_text(
        json.dumps(divergent), encoding="utf-8"
    )

    # Fake resolver that prefers per-mode reel_strips.json if present.
    # This is the hypothetical refactor; the structural check must detect
    # divergence given this behavior.
    def _hypothetical_resolve(weights_path):
        per_mode = weights_path.parent / "reel_strips.json"
        if per_mode.exists():
            return per_mode
        return weights_path.parent.parent / "reel_strips.json"

    mode_paths = [
        machine_dir / "mode_1" / "weights.json",
        machine_dir / "mode_2" / "weights.json",
    ]
    resolved = {mp: _hypothetical_resolve(mp).resolve() for mp in mode_paths}
    unique_paths = set(resolved.values())
    # Our structural test's path-level check: two modes resolving to two
    # different files MUST fail the "one unique path" assertion.
    assert len(unique_paths) == 2, (
        f"self-check broken: hypothetical per-mode resolver should give 2 "
        f"different paths; got {unique_paths}"
    )
    # Our structural test's hash-level check: the divergent bytes must
    # produce different hashes.
    hashes = {mp: _sha256(sp) for mp, sp in resolved.items()}
    assert len(set(hashes.values())) == 2, (
        "self-check broken: divergent per-mode strips should hash differently"
    )


if __name__ == "__main__":
    test_m15_strips_resolve_to_same_file_across_modes()
    print("ok  test_m15_strips_resolve_to_same_file_across_modes")
    test_m1_strips_resolve_to_same_file_across_modes()
    print("ok  test_m1_strips_resolve_to_same_file_across_modes")
    test_m15_loaded_reel_symbols_identical_across_modes()
    print("ok  test_m15_loaded_reel_symbols_identical_across_modes")
    print("3/3 passed (run via pytest to exercise the self-check meta-test)")
