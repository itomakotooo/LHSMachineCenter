"""Regression: ``fresh_slotlab.*`` modules imported via the bare-
import fallback must themselves be re-importable in the same context.

Backend launches analyzer subprocess as a SCRIPT (``sys.executable
<path>/player_impact_analyzer.py``), not as a module
(``python -m fresh_slotlab.player_impact_analyzer``). Python puts
the script's directory on sys.path[0], so the package-prefix
``from fresh_slotlab.X import ...`` raises ModuleNotFoundError and
the analyzer falls back to a bare ``from X import ...``. That works
— BUT each sibling module loaded via the bare path must also tolerate
the same script-mode environment. If a sibling does an unguarded
``from fresh_slotlab.Y import ...`` (no fallback), the import phase
crashes the subprocess with a misleading "No module named
'fresh_slotlab'" trace.

User-reported regression 2026-04-27: ``trigger_sessions.py`` line 50
had ``from fresh_slotlab.round_win import ...`` with no fallback;
M279 mode 1 sampling crashed the subprocess at import. Fixed by
adding the dual-import pattern. This test pins the contract for
EVERY sibling module so a future "wire in module Z" commit can't
re-introduce the bug.

The test runs the actual subprocess in script-mode and asserts the
import phase completes (--help is enough; we don't sample).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ANALYZER = ROOT / "fresh_slotlab" / "player_impact_analyzer.py"


@pytest.mark.skipif(
    not ANALYZER.exists(),
    reason="player_impact_analyzer.py not present in this checkout",
)
def test_script_mode_invocation_imports_cleanly():
    """Spawn the analyzer as a script (matching ``app.py`` self._
    analyzer launch shape) and assert the import phase completes
    without crashing.

    Pre-fix this test failed with::

        ModuleNotFoundError: No module named 'fresh_slotlab'

    raised from inside ``trigger_sessions.py`` line 50 (which had
    a hardcoded package-prefix import to ``fresh_slotlab.round_win``
    with no fallback for the script-mode case).
    """
    rc = subprocess.run(
        [sys.executable, str(ANALYZER), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert rc.returncode == 0, (
        f"script-mode analyzer crashed at import (rc={rc.returncode}); "
        f"this is the 2026-04-27 trigger_sessions → round_win fallback "
        f"regression class.\nSTDERR:\n{rc.stderr[-2000:]}"
    )
    # Stderr should be empty — argparse --help writes to stdout.
    assert not rc.stderr, (
        f"unexpected stderr from --help: {rc.stderr[-500:]}"
    )
    # Stdout must contain the argparse usage line — proves we got
    # past every import and into argparse.
    assert "usage:" in rc.stdout, (
        f"--help output missing usage line; stdout: {rc.stdout[:500]}"
    )
