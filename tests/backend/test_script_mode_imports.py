"""Regression: every script-shaped module in ``fresh_slotlab/`` must
import cleanly when launched in script mode (``python <path>``), not
only in package mode (``python -m fresh_slotlab.X``).

Backend launches subprocesses as scripts (``sys.executable <path>``):
Python puts the script's directory on sys.path[0], so a bare
``from fresh_slotlab.X import ...`` raises ModuleNotFoundError at
import time and crashes the subprocess with a misleading "No module
named 'fresh_slotlab'" trace. Every analyzer-tier sibling that wants
to be launchable as a script needs the dual-import pattern::

    try:
        from fresh_slotlab.X import foo
    except ImportError:
        from X import foo  # type: ignore[no-redef]

User-reported regressions tracked by this test:
  - 2026-04-27: ``trigger_sessions.py`` line 50 had unguarded
    ``from fresh_slotlab.round_win`` → M279 mode 1 sampling crashed
    at subprocess import.
  - 2026-04-27 (preemptive): ``batch_dev_sampler.py`` line 28 had
    unguarded ``from fresh_slotlab.player_impact_analyzer`` → would
    crash if invoked as a script (currently only used as ``-m``).

Strategy: parametrize over every ``.py`` in ``fresh_slotlab/`` that
has an ``if __name__ == "__main__"`` block (i.e. is launchable as a
script), spawn each with ``--help`` in script mode, and assert the
import phase completes (returncode 0 + ``usage:`` in stdout). Plus a
static-source check that no script-shaped module has an unguarded
``from fresh_slotlab.X`` at module top. Together they catch new
sibling modules that introduce the bug class as soon as they're added
— no need to remember to extend this test.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PKG_DIR = ROOT / "fresh_slotlab"


def _discover_script_modules() -> list[Path]:
    """Find every ``.py`` in ``fresh_slotlab/`` that has an
    ``if __name__ == "__main__":`` block — those are the files that
    can be launched as scripts and therefore need the dual-import
    fallback for any package-prefix imports.

    A simple substring match is enough: false positives (string
    literals containing the same text) would still need to handle
    --help cleanly, which is the harder of the two cases.
    """
    if not PKG_DIR.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(PKG_DIR.glob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if '__name__ == "__main__"' in text or "__name__ == '__main__'" in text:
            out.append(path)
    return out


SCRIPT_MODULES = _discover_script_modules()


@pytest.mark.skipif(
    not SCRIPT_MODULES,
    reason="no script-shaped modules in fresh_slotlab/ in this checkout",
)
@pytest.mark.parametrize(
    "script_path",
    SCRIPT_MODULES,
    ids=[p.name for p in SCRIPT_MODULES],
)
def test_script_mode_invocation_imports_cleanly(script_path: Path):
    """Spawn the module as a script (``python <abspath> --help``) and
    assert the import phase completes without crashing.

    Pre-fix this would fail with::

        ModuleNotFoundError: No module named 'fresh_slotlab'

    raised from inside any sibling that has an unguarded
    ``from fresh_slotlab.X import ...`` (no try/except fallback to the
    bare ``from X import ...`` form).
    """
    rc = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert rc.returncode == 0, (
        f"script-mode import crashed for {script_path.name} "
        f"(rc={rc.returncode}); this is the script-mode "
        f"package-prefix regression class — add a dual-import "
        f"fallback to whichever ``from fresh_slotlab.X import ...`` "
        f"line crashed.\nSTDERR:\n{rc.stderr[-2000:]}"
    )
    assert "ModuleNotFoundError" not in rc.stderr, (
        f"unexpected ModuleNotFoundError in stderr for "
        f"{script_path.name}: {rc.stderr[-500:]}"
    )
    assert "usage:" in rc.stdout, (
        f"--help output missing usage line for {script_path.name}; "
        f"stdout: {rc.stdout[:500]}"
    )


def test_no_unguarded_package_prefix_imports_in_script_modules():
    """Static check: any module with an ``if __name__ == '__main__'``
    block must NOT have an unguarded ``from fresh_slotlab.X import``
    statement — those crash in script mode.

    The dual-import pattern wraps the package-prefix import in
    ``try: ... except ImportError: from X import ...``. So an
    unguarded import is one whose AST parent is the module body (or
    a function/class body), NOT a ``Try`` body.

    Uses AST so the check is robust to multi-line import statements
    and large try-blocks (a substring/lookback check is brittle).

    This is a belt-and-suspenders check on top of the subprocess test
    above. The subprocess test catches the runtime crash; this catches
    the source-level bug class even if --help happens to bypass the
    crashing import path (e.g. the import only fires deep into a
    --no-help run).
    """
    import ast

    offenders: list[str] = []
    for script_path in SCRIPT_MODULES:
        # utf-8-sig: ast.parse rejects U+FEFF BOM; read_text("utf-8")
        # leaves the BOM in. utf-8-sig strips it on read.
        tree = ast.parse(
            script_path.read_text(encoding="utf-8-sig"),
            filename=str(script_path),
        )

        # Walk and tag every node with whether it's inside a Try body.
        # Visiting via NodeVisitor lets us track ancestor context.
        class _V(ast.NodeVisitor):
            def __init__(self):
                self.in_try_depth = 0

            def visit_Try(self, node):  # noqa: N802
                self.in_try_depth += 1
                for sub in node.body:
                    self.visit(sub)
                self.in_try_depth -= 1
                # Don't descend into handlers/orelse/finalbody —
                # imports there are the FALLBACK path, not the
                # guarded path. They're allowed to be unguarded
                # (that's literally what an except branch is for).
                # We DO need to mark imports in handlers as "covered"
                # so they don't get flagged, but they're typically
                # bare imports, not package-prefix. Skip handlers:
                # if a handler has a `from fresh_slotlab.X` that
                # would itself crash in script mode, but that's the
                # fallback which only runs WHEN package mode failed
                # so it's a separate degenerate case.
                pass

            def visit_ImportFrom(self, node):  # noqa: N802
                if node.module and node.module.startswith("fresh_slotlab."):
                    if self.in_try_depth == 0:
                        offenders.append(
                            f"{script_path.name}:{node.lineno}: "
                            f"from {node.module} import "
                            f"{', '.join(a.name for a in node.names)}"
                        )

        _V().visit(tree)

    assert not offenders, (
        "Unguarded ``from fresh_slotlab.X import ...`` in script-shaped "
        "modules — wrap each in a try/except ImportError fallback to "
        "the bare ``from X import ...``. See trigger_sessions.py and "
        "batch_dev_sampler.py for the canonical pattern. Offenders:\n"
        + "\n".join(offenders)
    )


def _discover_dual_import_modules() -> list[Path]:
    """Find every ``.py`` in ``fresh_slotlab/`` that uses the
    dual-import pattern (substring screen for ``fresh_slotlab.`` AND
    ``ImportError`` — cheap and safe). Includes non-``__main__``
    siblings like ``trigger_sessions.py`` because they're imported
    BY script-shaped modules and a broken fallback there crashes the
    parent's subprocess."""
    if not PKG_DIR.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(PKG_DIR.glob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "fresh_slotlab." in text and "ImportError" in text:
            out.append(path)
    return out


def test_dual_import_branches_have_matching_symbol_lists():
    """Both branches of the dual-import pattern must import the SAME
    set of symbols. If the package-mode branch lists ``A, B, C`` but
    the script-mode fallback only lists ``A, B``, package-mode tests
    pass while script-mode subprocess execution hits a NameError when
    ``C`` is referenced.

    User-reported regression 2026-04-28: trigger_sessions.py:65 had
    ``from fresh_slotlab.round_win import RoundWinRule, extract_round_payouts, extract_round_win``
    but the fallback line 67 only listed ``RoundWinRule, extract_round_win``
    — missing ``extract_round_payouts``. M15 sampling crashed at
    runtime with ``NameError: name 'extract_round_payouts' is not
    defined`` when ``compute_trigger_sessions`` reached its rules-driven
    branch (only fires when ``round_win_rules`` is non-empty + a
    non-paid round is being scanned, which --help-time imports don't
    exercise).

    Coverage: ALL ``.py`` files in ``fresh_slotlab/`` that use the
    dual-import pattern, NOT just script-shaped (``__main__``) modules.
    A sibling like ``trigger_sessions.py`` doesn't have a main block
    but is IMPORTED by the script-shaped analyzer — its broken
    fallback still crashes the analyzer subprocess.

    AST-level: walk every dual-import module, find each
    ``try: ... ImportError: ...`` block whose try-body has
    ``from fresh_slotlab.X import a, b, c`` and whose except-body has
    ``from X import ...``. Assert the two ``import`` lines have the
    SAME ``names`` list."""
    import ast

    mismatches: list[str] = []
    for script_path in _discover_dual_import_modules():
        tree = ast.parse(
            script_path.read_text(encoding="utf-8-sig"),
            filename=str(script_path),
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            pkg_imports: dict[str, set[str]] = {}
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.ImportFrom)
                    and stmt.module
                    and stmt.module.startswith("fresh_slotlab.")
                ):
                    sibling = stmt.module.split(".", 1)[1]
                    pkg_imports.setdefault(sibling, set()).update(
                        a.name for a in stmt.names
                    )
            bare_imports: dict[str, set[str]] = {}
            for handler in node.handlers:
                for stmt in handler.body:
                    if (
                        isinstance(stmt, ast.ImportFrom)
                        and stmt.module
                        and "." not in stmt.module
                    ):
                        bare_imports.setdefault(stmt.module, set()).update(
                            a.name for a in stmt.names
                        )
            for sibling, pkg_syms in pkg_imports.items():
                bare_syms = bare_imports.get(sibling)
                if bare_syms is None:
                    continue  # no matching fallback at all (different bug class)
                if pkg_syms != bare_syms:
                    only_in_pkg = sorted(pkg_syms - bare_syms)
                    only_in_bare = sorted(bare_syms - pkg_syms)
                    mismatches.append(
                        f"{script_path.name}:{node.lineno}: "
                        f"sibling '{sibling}' — package branch imports "
                        f"{sorted(pkg_syms)}, script branch imports "
                        f"{sorted(bare_syms)}; "
                        f"only-in-pkg={only_in_pkg}, "
                        f"only-in-script={only_in_bare}"
                    )

    assert not mismatches, (
        "Dual-import pattern symbol drift — script-mode fallback "
        "doesn't re-import every symbol the package-mode branch "
        "imports. Will crash with NameError at runtime in subprocess "
        "execution. Mismatches:\n" + "\n".join(mismatches)
    )
