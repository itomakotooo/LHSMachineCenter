"""Single source of truth for virtual-machine MD5 versioning.

Mirrors the real-machine schema from `configs/machines.json`:
  - `configSummaryMd5` — per-machine. Flips when the machine's spec
    (rules) or weights (reel strip / per-mode) change.
  - `codeSummaryMd5`   — fleet-wide. Flips when engine/emitter source
    changes (= a new "game engine version" applies to every machine).

This module is the ONE place these hashes are computed, so we can't
accidentally hash different byte sequences in different call sites and
have chunks silently mismatch the registry.

Call sites (3):
  1. `backend/virtual_app.refresh_machines_virtual()` — on console boot
     AND on every sampling request (see `POST /api/virtual/refresh-md5`-
     equivalent trigger). Writes current MD5s into machines_virtual.json
     so the frontend's per-machine badge + classify_chunks both see
     consistent values.
  2. `backend/virtual_analyzer._compute_md5s()` — when emitting sampled
     chunks, stamps them with CURRENT MD5 (not the registry cache),
     so a chunk is always tagged with the md5 of the exact (spec,
     weights, engine) snapshot that produced it.
  3. `scripts/tune.py` — same contract: stamp tuned-weights emitted
     chunks with current MD5.

Why weights are in config_md5 (not in code_md5):
  - Real machines.json schema: configSummaryMd5 covers the machine-specific
    math config (paytable + reel strip). codeSummaryMd5 covers the
    engine/platform code shared across machines.
  - For virtual machines the analog is: spec (rules) + weights (reel
    strip) = machine-specific; engine = shared. So weights MUST be in
    config_md5 to get the "machine version" semantics. Without this,
    re-tuning creates chunks that look identical to old-tuning chunks
    → classify_chunks marks them all "kept" → analyzer mixes them →
    blended / wrong RTP.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable


_SLOT_DESIGNER = Path(__file__).resolve().parent.parent


def _md5_file(path: Path) -> bytes:
    """MD5 digest (raw bytes, for chaining) of a single file."""
    return hashlib.md5(path.read_bytes()).digest()


def _engine_source_files() -> list[Path]:
    """All engine + emitter .py files (excluding __init__.py) that
    contribute to the game logic. Sorted for determinism.
    """
    engine_dir = _SLOT_DESIGNER / "engine"
    emitter_dir = _SLOT_DESIGNER / "emitter"
    files: list[Path] = []
    for d in (engine_dir, emitter_dir):
        files.extend(p for p in sorted(d.glob("*.py")) if p.name != "__init__.py")
    return files


def compute_code_md5() -> str:
    """Fleet-wide game-engine version hash.

    Any change to engine/*.py or emitter/*.py (excluding __init__.py)
    flips this → every virtual machine's chunks become "stale" next
    time classify_chunks compares.
    """
    h = hashlib.md5()
    for f in _engine_source_files():
        h.update(f.read_bytes())
    return h.hexdigest()


def compute_config_md5(
    spec_path: Path,
    weights_paths: Iterable[Path],
) -> str:
    """Per-machine math-config version hash.

    Inputs:
      - spec_path: the machine's rules definition (slot_designer/specs/X.spec.json)
      - weights_paths: all mode-specific weights files for this machine,
        in stable order. Typically resolved by the caller from the
        registry's `_weights_path_template` for each mode in `modes`.

    The hash is order-sensitive — passing weights in a different mode
    order would produce a different md5. Callers (refresh /
    compute_md5s / tune) MUST use the same sorted-by-mode order.

    Missing weights files are allowed: they contribute a zero-byte
    sentinel to the hash so the md5 still changes when a weights file
    first appears or is later deleted.
    """
    h = hashlib.md5()
    if spec_path.exists():
        h.update(spec_path.read_bytes())
    else:
        h.update(b"<spec_missing>")
    for wp in weights_paths:
        if wp.exists():
            h.update(b"\x00")        # separator — prevents ambiguity across
            h.update(wp.read_bytes()) # weights files with adjacent bytes
        else:
            h.update(b"\x00<missing>")
    return h.hexdigest()


def resolve_weights_paths(entry: dict, modes: Iterable[int]) -> list[Path]:
    """Resolve a machines_virtual.json entry's mode list into the actual
    weights file paths that contribute to its config_md5.

    Tries `_weights_path_template` first, then `_weights_fallback_template`
    (for machines that don't have a tuned version yet). Returns the
    chosen paths in `modes` order (sorted ascending by int for stability).
    """
    repo_root = _SLOT_DESIGNER.parent
    out: list[Path] = []
    for mode in sorted({int(m) for m in modes}):
        tpl = entry.get("_weights_path_template")
        fallback = entry.get("_weights_fallback_template")
        chosen: Path | None = None
        if tpl:
            p = repo_root / tpl.format(mode=mode)
            if p.exists():
                chosen = p
        if chosen is None and fallback:
            p = repo_root / fallback.format(mode=mode)
            if p.exists():
                chosen = p
        # If neither exists, still produce a deterministic placeholder
        # path (won't be read, just recorded in the hash via the
        # sentinel branch in compute_config_md5).
        if chosen is None and tpl:
            chosen = repo_root / tpl.format(mode=mode)
        elif chosen is None and fallback:
            chosen = repo_root / fallback.format(mode=mode)
        if chosen is not None:
            out.append(chosen)
    return out


def compute_machine_md5(entry: dict) -> tuple[str, str]:
    """Machine-level (aggregate) ``(config_md5, code_md5)``.

    config_md5 covers spec + ALL mode weights — flips when ANY mode's
    weights (or the spec) change. Used for "did anything about this
    machine change?" questions; NOT used for per-mode chunk tag
    comparison (that's ``compute_machine_md5_for_mode`` below).

    All callers route through this helper or the per-mode variant so
    hash semantics stay consistent across refresh / classify / stamp
    sites.
    """
    repo_root = _SLOT_DESIGNER.parent
    spec_path = repo_root / entry.get("_spec_path", "")
    weights_paths = resolve_weights_paths(entry, entry.get("modes", []))
    return compute_config_md5(spec_path, weights_paths), compute_code_md5()


def compute_machine_md5_for_mode(entry: dict, mode: int) -> tuple[str, str]:
    """Per-mode ``(config_md5, code_md5)`` — hash covers spec + THIS
    mode's weights only.

    Motivation (2026-04-22): on a machine where different modes have
    different reel strips (virtual M1sim mode 1 vs mode 2), the old
    machine-level ``compute_machine_md5`` mixed all modes' weights
    into one hash. Result: adding mode 2 flipped the machine's
    config_md5, and every existing mode 1 chunk (stamped with the
    pre-mode-2 hash) was reclassified as "historical" — even though
    mode 1's reel strip never changed.

    Per-mode md5 fixes this: mode 1's hash depends only on spec +
    mode 1 weights. Adding mode 2 doesn't change it. Each mode's
    chunks stamp with their own md5; classifier compares against the
    same per-mode md5 on replay.

    code_md5 is mode-agnostic (engine + emitter source hashes) — it
    shares the same value across modes, but we return it here for
    call-site convenience.
    """
    repo_root = _SLOT_DESIGNER.parent
    spec_path = repo_root / entry.get("_spec_path", "")
    # Single mode → single weights path
    weights_paths = resolve_weights_paths(entry, [int(mode)])
    return compute_config_md5(spec_path, weights_paths), compute_code_md5()
