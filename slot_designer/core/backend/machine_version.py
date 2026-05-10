"""Single source of truth for virtual-machine MD5 versioning.

Mirrors the real-machine schema from `configs/machines.json`:
  - `configSummaryMd5` — per-machine. Flips when the machine's spec
    (rules) or weights (reel strip / per-mode) change.
  - `codeSummaryMd5`   — **per-machine** (Phase B refactor 2026-05-08).
    Hash covers (a) ``core/engine/**`` + ``core/emitter/**`` shared
    framework + (b) ``machines/<machine_name>/plugins/**`` private
    plugin tree. Flips only for the affected machine when its plugin
    code or the framework code changes.

This module is the ONE place these hashes are computed, so we can't
accidentally hash different byte sequences in different call sites and
have chunks silently mismatch the registry.

Call sites (3):
  1. `core/backend/virtual_app.refresh_machines_virtual()` — on console
     boot AND on every sampling request. Writes current MD5s into
     machines_virtual.json.
  2. `core/backend/virtual_analyzer._compute_md5s()` — stamps emitted
     chunks with CURRENT MD5 of the exact (spec, weights, engine,
     plugin) snapshot that produced them.
  3. `scripts/tune.py` — same contract: stamp tuned-weights emitted
     chunks with current MD5.

Why weights are in config_md5 (not in code_md5):
  - Real machines.json schema: configSummaryMd5 covers the machine-specific
    math config (paytable + reel strip). codeSummaryMd5 covers the
    engine/platform code.
  - For virtual machines the analog is: spec (rules) + weights (reel
    strip) = machine-specific; engine = shared. So weights MUST be in
    config_md5 to get the "machine version" semantics. Without this,
    re-tuning creates chunks that look identical to old-tuning chunks
    → classify_chunks marks them all "kept" → analyzer mixes them →
    blended / wrong RTP.

Phase B per-machine hash boundary (slot_designer/ARCHITECTURE.md §4):
  - Touch core/engine/* or core/emitter/* → every machine's md5 flips
    (correct: framework change is a fleet-wide event).
  - Touch machines/M15/plugins/* → only M15's md5 flips.
  - Touch machines/M279/plugins/* → only M279's md5 flips.
  - Touch tests, docs, scripts, configs → no machine's md5 flips.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable


# slot_designer/ root (this file lives at slot_designer/core/backend/machine_version.py
# after Phase A; walk three parents up).
_SLOT_DESIGNER = Path(__file__).resolve().parent.parent.parent


def _md5_file(path: Path) -> bytes:
    """MD5 digest (raw bytes, for chaining) of a single file."""
    return hashlib.md5(path.read_bytes()).digest()


def _core_source_files() -> list[Path]:
    """All ``core/engine/**`` + ``core/emitter/**`` .py files
    (excluding ``__init__.py`` and ``__pycache__``). Sorted by relative
    path for determinism.

    Note (Phase B): we recurse with ``rglob`` because future framework
    additions may live in subpackages (e.g. ``core/engine/features/``).
    Pre-Phase-B used non-recursive ``glob`` which silently missed
    ``engine/m279/`` subpackage files — that subpackage is now relocated
    under ``machines/M279/plugins/`` so the recursion is safe.
    """
    core_engine = _SLOT_DESIGNER / "core" / "engine"
    core_emitter = _SLOT_DESIGNER / "core" / "emitter"
    files: list[Path] = []
    for d in (core_engine, core_emitter):
        if not d.is_dir():
            continue
        for p in d.rglob("*.py"):
            if p.name == "__init__.py":
                continue
            if "__pycache__" in p.parts:
                continue
            files.append(p)
    files.sort()
    return files


def _plugin_source_files(machine_name: str) -> list[Path]:
    """All ``machines/<machine_name>/plugins/**`` .py files (excluding
    ``__init__.py`` + ``__pycache__``). Sorted for determinism.

    Returns empty list when the machine has no plugins/ dir (base-only
    machines like M1 / M37).
    """
    plugin_dir = _SLOT_DESIGNER / "machines" / machine_name / "plugins"
    if not plugin_dir.is_dir():
        return []
    files: list[Path] = []
    for p in plugin_dir.rglob("*.py"):
        if p.name == "__init__.py":
            continue
        if "__pycache__" in p.parts:
            continue
        files.append(p)
    files.sort()
    return files


def compute_code_md5(machine_name: str) -> str:
    """Per-machine game-engine + plugin version hash.

    Hash inputs (in order):
      1. ``core/engine/**/*.py``  — shared framework engine
      2. ``core/emitter/**/*.py`` — shared framework emitter
      3. ``machines/<machine_name>/plugins/**/*.py`` — per-machine plugins
         (empty for base-only machines)

    Behavior:
      - Touching core/* flips every machine's md5 (framework change).
      - Touching machines/M15/plugins/* flips only M15's md5.
      - Touching machines/M279/plugins/* flips only M279's md5.
      - Touching tests / docs / scripts / configs → no md5 flips.

    Args:
      machine_name: short machine identifier (e.g. "M1", "M15"); the
        directory under ``slot_designer/machines/`` whose plugin tree
        contributes to the hash.

    Backward-incompat (Phase B 2026-05-08): pre-Phase-B signature was
    ``compute_code_md5() -> str`` returning a fleet-wide hash. Callers
    must pass machine_name now. The bare-call signature is gone so the
    interpreter raises TypeError loudly — silent fleet-wide hashing is
    the architectural rot we're fixing.
    """
    h = hashlib.md5()
    for p in _core_source_files():
        h.update(p.read_bytes())
    for p in _plugin_source_files(machine_name):
        h.update(p.read_bytes())
    return h.hexdigest()


def compute_config_md5(
    spec_path: Path,
    weights_paths: Iterable[Path],
    *,
    strips_path: Path | None = None,
) -> str:
    """Per-machine math-config version hash.

    Inputs:
      - spec_path: the machine's rules definition
        (``slot_designer/specs/X.spec.json``).
      - strips_path (2026-04-22): the shared ``reel_strips.json`` that
        defines the symbol-at-position layout all modes of this machine
        share. Omit when hashing an old-schema single-file weights
        (rare; new virtual machines always have strips).
      - weights_paths: all mode-specific weights files for this machine,
        in stable order. Typically resolved by the caller from the
        registry's ``_weights_path_template`` for each mode in ``modes``.

    The hash is order-sensitive — passing weights in a different mode
    order would produce a different md5. Callers (refresh /
    compute_md5s / tune) MUST use the same sorted-by-mode order.

    Missing files contribute a sentinel to the hash so the md5 still
    changes when a weights/strips file first appears or is later
    deleted.
    """
    h = hashlib.md5()
    if spec_path.exists():
        h.update(spec_path.read_bytes())
    else:
        h.update(b"<spec_missing>")
    # Strips come between spec and per-mode weights so the hash has a
    # stable shape: (spec | strips | mode_1 | mode_2 | ...). Callers
    # without strips (e.g. legacy tests hashing only per-mode files)
    # pass strips_path=None and we elide the section — so adding
    # strips_path later creates a new md5 (correct: the machine's
    # identity changed).
    if strips_path is not None:
        h.update(b"\x00")
        if strips_path.exists():
            h.update(strips_path.read_bytes())
        else:
            h.update(b"<strips_missing>")
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

    Shared strips + per-mode weights (2026-04-22 layout):
      ``_weights_path_template`` expands to
      ``slot_designer/weights/<machine>/mode_<N>/weights.json``
      (symbol layout lives in the machine-level ``reel_strips.json``).

    If the file is missing (new machine still being scaffolded), the
    deterministic placeholder path is still returned — the hash picks
    up the "missing" sentinel inside ``compute_config_md5`` so the
    md5 flips correctly once the file gets created.

    Returns the paths in ``modes`` order (sorted ascending by int for
    stability).
    """
    repo_root = _SLOT_DESIGNER.parent
    tpl = entry.get("_weights_path_template")
    if not tpl:
        return []
    return [
        repo_root / tpl.format(mode=mode)
        for mode in sorted({int(m) for m in modes})
    ]


def resolve_strips_path(entry: dict) -> Path | None:
    """Resolve the machine's shared ``reel_strips.json`` path from the
    registry entry. Returns None if the entry lacks ``_strips_path``
    (legacy single-file machines that pre-date the strips-split).
    """
    tpl = entry.get("_strips_path")
    if not tpl:
        return None
    return _SLOT_DESIGNER.parent / tpl


def _machine_name_from_entry(entry: dict) -> str:
    """Extract the machines/<M>/ directory name from a registry entry.

    Prefers ``_source_machine`` (explicit, set by registry authors so
    "M15sim" → "M15"). Falls back to stripping a trailing "sim" from
    the registry's ``machine`` field for back-compat with entries that
    omit ``_source_machine``.
    """
    name = entry.get("_source_machine")
    if name:
        return str(name)
    raw = entry.get("machine", "")
    if raw.endswith("sim"):
        return raw[:-3]
    return raw


def compute_machine_md5(entry: dict) -> tuple[str, str]:
    """Machine-level (aggregate) ``(config_md5, code_md5)``.

    config_md5 covers spec + shared strips + ALL mode weights — flips
    when the spec, strips, or ANY mode's weights change. Used for "did
    anything about this machine change?" questions; NOT used for
    per-mode chunk tag comparison (that's
    ``compute_machine_md5_for_mode`` below).

    code_md5 (Phase B per-machine) covers core engine + core emitter +
    that machine's own plugins/. Touching another machine's plugins
    won't flip this machine's code_md5.

    All callers route through this helper or the per-mode variant so
    hash semantics stay consistent across refresh / classify / stamp
    sites.
    """
    repo_root = _SLOT_DESIGNER.parent
    spec_path = repo_root / entry.get("_spec_path", "")
    strips_path = resolve_strips_path(entry)
    weights_paths = resolve_weights_paths(entry, entry.get("modes", []))
    cfg = compute_config_md5(spec_path, weights_paths, strips_path=strips_path)
    return cfg, compute_code_md5(_machine_name_from_entry(entry))


def compute_machine_md5_for_mode(entry: dict, mode: int) -> tuple[str, str]:
    """Per-mode ``(config_md5, code_md5)`` — hash covers spec + strips
    + THIS mode's weights only.

    Motivation (2026-04-22): on a machine where different modes have
    different per-mode weights files, the old aggregate
    ``compute_machine_md5`` mixed all modes' weights into one hash.
    Result: adding mode 2 flipped the machine's config_md5, and every
    existing mode 1 chunk (stamped with the pre-mode-2 hash) was
    reclassified as "historical" — even though mode 1's reel weights
    never changed.

    Per-mode md5 fixes this: mode 1's hash depends on spec + strips +
    mode 1 weights only. Adding mode 2 doesn't change it. Each mode's
    chunks stamp with their own md5; classifier compares against the
    same per-mode md5 on replay.

    NOTE on strips (2026-04-22 structural): strips are shared across
    all modes of the machine, so they ARE part of every per-mode
    hash — changing the strip layout flips md5 for every mode
    simultaneously (by design: the strip change IS a machine-wide
    event that should invalidate all old chunks).

    code_md5 is mode-agnostic (Phase B: shared core + this machine's
    plugins) — it shares the same value across modes of the same
    machine, but we return it here for call-site convenience.
    """
    repo_root = _SLOT_DESIGNER.parent
    spec_path = repo_root / entry.get("_spec_path", "")
    strips_path = resolve_strips_path(entry)
    # Single mode → single weights path
    weights_paths = resolve_weights_paths(entry, [int(mode)])
    cfg = compute_config_md5(spec_path, weights_paths, strips_path=strips_path)
    return cfg, compute_code_md5(_machine_name_from_entry(entry))
