"""Phase C target — core/ tree must not leak machine names.

ARCHITECTURE.md §7 (forbidden zone):

  core/ source files (engine + emitter + tuner + devtools + backend +
  version + feature_protocol) must NOT contain:
    - imports from slot_designer.machines.* (any machine subpackage)
    - machine identifiers (M1, M15, M37, M279) as bare tokens
    - brand strings ("TopDollar", "TopDollarSelector", "TripleDouble"...)
    - hardcoded machine-specific spin types (ST=14, ST=15) in code

Phase C delivery:
  - feature plugin contract via core/engine/feature_protocol.py
  - M15-specific bits move to machines/M15/plugins/
  - generic engine/emitter call plugin via Protocol; no machine name
    appears in core/ source

This test exercises the static invariant. Pre-Phase-C it is RED
(spin.py + loader.py + round.py + robot.py + driver.py still reference
M15 / TopDollar). Post-Phase-C all references gone.

See also:
  - tests/core/test_layout.py — directory invariants (Phase A)
  - tests/core/test_per_machine_code_md5.py — md5 isolation (Phase B)
  - tests/core/test_feature_plugin_protocol.py — plugin contract (Phase C)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_SLOT_DESIGNER = Path(__file__).resolve().parents[2]
_CORE = _SLOT_DESIGNER / "core"


def _core_py_files() -> list[Path]:
    """All .py files under core/, excluding __init__.py + __pycache__."""
    out = []
    for p in _CORE.rglob("*.py"):
        if p.name == "__init__.py":
            continue
        if "__pycache__" in p.parts:
            continue
        out.append(p)
    return sorted(out)


# ─────────────────────────────────────────────────────────────────────
# Imports
# ─────────────────────────────────────────────────────────────────────

def test_no_imports_from_machines_subpackage_in_core():
    """core/**/*.py must not ``from slot_designer.machines.*`` or
    ``import slot_designer.machines.*``.

    If core/ imports a machine module statically, that machine becomes
    a hard dependency of the framework — defeating the per-machine
    isolation we want. Plugin loading must go through importlib, not
    static import.
    """
    pat_from = re.compile(r"\bfrom\s+slot_designer\.machines\.")
    pat_import = re.compile(r"\bimport\s+slot_designer\.machines\.")
    offenders = []
    for p in _core_py_files():
        text = p.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            if pat_from.search(line) or pat_import.search(line):
                offenders.append(f"{p.relative_to(_SLOT_DESIGNER)}:{line_no}: {line.strip()}")
    assert not offenders, (
        "core/ imports from slot_designer.machines.* — must use importlib "
        "via FeaturePlugin protocol (ARCHITECTURE.md §3, §7):\n  "
        + "\n  ".join(offenders)
    )


# ─────────────────────────────────────────────────────────────────────
# String literals — machine names + brand names
# ─────────────────────────────────────────────────────────────────────

# Tokens which, if found in core/ source code (anywhere — comments,
# docstrings, strings, identifiers), indicate machine-name leak.
# NOT counted: docstring/comment references that are deliberately
# preserved as architectural notes (whitelisted via _ALLOWED_DOCSTRING_NOTES).

_FORBIDDEN_TOKENS_IDENTIFIER = [
    # Bare machine identifiers — must use generic "machine_name" var instead
    r"\bM1\b", r"\bM15\b", r"\bM37\b", r"\bM279\b",
    # Brand-specific feature names — must come through plugin.classify_round
    r"\bTopDollar\b", r"\bTopDollarSelector\b",
]


def test_no_machine_name_tokens_in_core_source():
    """core/**/*.py must not contain bare machine identifiers like M1,
    M15, M37, M279, or brand names like TopDollar / TopDollarSelector.

    Comments + docstrings allowed only when discussing architecture
    constraints (e.g. an example explaining "what plugin/<M>/ contributes
    to per-machine md5"). Such notes need to phrase the discussion
    abstractly. If you must mention a specific machine in core/, push
    that comment to ARCHITECTURE.md or the machine's own DESIGN.md.
    """
    offenders = []
    for p in _core_py_files():
        text = p.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            for pat_str in _FORBIDDEN_TOKENS_IDENTIFIER:
                if re.search(pat_str, line):
                    offenders.append(
                        f"{p.relative_to(_SLOT_DESIGNER)}:{line_no}: "
                        f"{pat_str!r} in: {line.strip()}"
                    )
    assert not offenders, (
        "core/ source contains forbidden machine-name tokens — push them "
        "into machines/<M>/ or generalize via plugin protocol "
        "(ARCHITECTURE.md §7):\n  " + "\n  ".join(offenders)
    )


# ─────────────────────────────────────────────────────────────────────
# Spin type literals — ST=14, ST=15 are M15 plumbing, not core schema
# ─────────────────────────────────────────────────────────────────────

def test_no_hardcoded_spin_types_14_15_in_core():
    """core/**/*.py must not have hardcoded ``SpinType: 14`` / ``SpinType: 15``
    or ``st == 14`` / ``st == 15`` checks. Those are M15-specific feature
    sub-round + end-marker codes; they belong in the M15 plugin.

    Any ST checks in core code should be against the spec's spin_types
    config or via plugin callbacks, not numeric literals.
    """
    pat_14 = re.compile(r"\b(?:SpinType|st|spin_type)\s*[=:]+\s*14\b|==\s*14\b")
    pat_15 = re.compile(r"\b(?:SpinType|st|spin_type)\s*[=:]+\s*15\b|==\s*15\b")
    offenders = []
    for p in _core_py_files():
        text = p.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            if pat_14.search(line) or pat_15.search(line):
                offenders.append(
                    f"{p.relative_to(_SLOT_DESIGNER)}:{line_no}: {line.strip()}"
                )
    assert not offenders, (
        "core/ source contains hardcoded SpinType 14/15 — those are "
        "M15-specific schema, must move to machines/M15/plugins/ "
        "(ARCHITECTURE.md §7):\n  " + "\n  ".join(offenders)
    )
