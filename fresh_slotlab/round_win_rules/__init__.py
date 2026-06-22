"""fresh_slotlab.round_win_rules — pluggable round-win RULE-TYPE layer.

Framework package for round-win rule TYPES (``RoundWinRule`` subclasses).
Mirrors the ``features/`` and ``st_extract/`` layers exactly.

Closed / framework files (in ``_CLOSURE_FILES``):
  ``__init__.py`` (this file) — discovery / registry / per-type hashing.

Base-EXCLUDED rule-type modules (``settlement_winamount.py``,
``synthesize_pay_id.py``, ``win_residual.py``, ``bcm_cycle_anchor.py``, and
any future type) are auto-discovered and NOT in the closure, so editing OR
adding a rule type re-flags only the machines that declare it (via
``configs/machine_round_win_rules.json`` ``applies_to`` → the
``rw:<type_str>`` component of their ``effective_version``), never the whole
fleet. This is the last closure-bound extension point converted to the
plugin model.

The ``RoundWinRule`` ABC and the dispatch core (``extract_round_win`` /
``extract_round_payouts`` / ``extract_round_trigger_anchor`` /
``round_has_credited_win`` / ``load_rules_for_machine``) stay in
``fresh_slotlab/round_win.py`` (also in the closure) — they are the truly
shared math; changing them is a legitimate fleet-wide flip.

Public API
----------
  ``register_rule(type_str, rule_cls)`` — self-registration, called at the
      bottom of each rule module. Idempotent.
  ``discover_rules()`` — import every rule module so each self-registers.
      Idempotent.
  ``RULE_REGISTRY`` — ``{type_str: RoundWinRule subclass}``; populated by
      ``discover_rules()``; consumed by ``load_rules_for_machine``.
  ``rule_type_hash(type_str)`` — 12-hex sha256 (CRLF-normalized) of the rule
      module source; folded into per-machine ``effective_version`` as
      ``"rw:<type_str>"`` by ``versioning.py``.

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md. Registry
state is a module global here; rule-class methods must NOT read it.
"""
from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

# RoundWinRule lives in round_win.py, which does NOT import this package at
# module load (all of its references to us are lazy), so this top-level import
# is one-way and cycle-free.
try:
    from fresh_slotlab.round_win import RoundWinRule
except ImportError:
    from round_win import RoundWinRule  # type: ignore[no-redef]


# Files under round_win_rules/ that are NOT rule-type modules. __init__.py is
# the package marker / framework file (stays in _CLOSURE_FILES). Everything
# else is a discoverable, base-excluded rule type.
_DISCOVERY_EXCLUDE: frozenset[str] = frozenset({"__init__.py"})


# ---------------------------------------------------------------------------
# Registry state
# ---------------------------------------------------------------------------

RULE_REGISTRY: dict[str, type[RoundWinRule]] = {}
"""type-string → RoundWinRule subclass.

Empty on import. Rule modules register themselves by calling
``register_rule(type_str, cls)`` at module import time (fired by
``discover_rules()``).
"""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_rule(type_str: str, rule_cls: type[RoundWinRule]) -> None:
    """Register *rule_cls* under *type_str* in ``RULE_REGISTRY``.

    Called at the bottom of each rule module. Idempotent: re-registering the
    same ``type_str`` is a silent no-op so double-import does not raise.

    Raises
    ------
    TypeError
        If *rule_cls* is not a ``RoundWinRule`` subclass.
    ValueError
        If the class declares a ``TYPE_STR`` that disagrees with *type_str*.
        The type string is the contract between the JSON config and the code;
        a mismatch is caught here at registration instead of silently
        producing an empty rule list at ``load_rules_for_machine`` time
        (per memory/feedback_no_silent_swallow.md).
    """
    if not (isinstance(rule_cls, type) and issubclass(rule_cls, RoundWinRule)):
        raise TypeError(
            f"register_rule() requires a RoundWinRule subclass, got {rule_cls!r}. "
            f"Ensure the class subclasses RoundWinRule."
        )
    declared = getattr(rule_cls, "TYPE_STR", "")
    if declared and declared != type_str:
        raise ValueError(
            f"register_rule type_str mismatch: registered as {type_str!r} but "
            f"{rule_cls.__name__}.TYPE_STR={declared!r}. Keep them in sync."
        )
    if type_str in RULE_REGISTRY:
        return  # silent no-op (double import)
    RULE_REGISTRY[type_str] = rule_cls


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_rules(*, _rules_dir: Path | None = None) -> None:
    """Import every rule module under ``round_win_rules/`` so each self-registers.

    Algorithm mirrors ``st_extract.discover_extractors`` /
    ``feature_registry.discover_features`` exactly:
      1. Glob ``*.py``, exclude ``__init__.py``.
      2. Sort for determinism.
      3. Dual-path import (package mode first, standalone fallback).
      4. Each module's bottom-of-file ``register_rule()`` call fires (idempotent).

    Per memory/feedback_no_silent_swallow.md: ``ImportError`` is NOT swallowed.
    """
    if _rules_dir is None:
        _rules_dir = Path(__file__).resolve().parent

    stems: list[str] = sorted(
        p.name
        for p in _rules_dir.glob("*.py")
        if p.name not in _DISCOVERY_EXCLUDE
    )

    for stem_py in stems:
        stem = stem_py[:-3]
        try:
            importlib.import_module(f"fresh_slotlab.round_win_rules.{stem}")
        except ImportError:
            try:
                importlib.import_module(f"round_win_rules.{stem}")
            except ImportError:
                raise ImportError(
                    f"discover_rules: could not import rule module '{stem}' via "
                    f"either 'fresh_slotlab.round_win_rules.{stem}' or "
                    f"'round_win_rules.{stem}'. Check the module for syntax errors "
                    f"or missing dependencies."
                ) from None


# ---------------------------------------------------------------------------
# Per-type hashing
# ---------------------------------------------------------------------------

def rule_type_hash(type_str: str) -> str:
    """Return the 12-hex sha256 of the rule module's source (CRLF-normalized).

    CRLF normalization (``replace(b"\\r\\n", b"\\n")``) matches
    ``versioning.compute_base_analyzer_version`` so the per-type hash is a
    function of SOURCE CONTENT, not git checkout config (core.autocrlf) or
    platform — the round_win_rules layer's analog of base_hash's FIX-2.
    Folded into per-machine ``effective_version`` as ``"rw:<type_str>"``.

    Raises
    ------
    KeyError
        If *type_str* is not in ``RULE_REGISTRY``. Call ``discover_rules()``
        first.
    """
    rule_cls = RULE_REGISTRY[type_str]  # KeyError is intentional — see docstring
    mod = sys.modules.get(rule_cls.__module__)
    path = getattr(mod, "__file__", None) if mod is not None else None
    if path is None:
        path = str(Path(rule_cls.__module__.replace(".", "/") + ".py"))
    raw = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()[:12]
