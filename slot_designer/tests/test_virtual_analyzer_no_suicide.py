"""Regression: virtual_analyzer subprocess must not self-terminate.

The 2026-04-21 incident in one sentence: ``virtual_analyzer.py``'s
``main()`` imported ``slot_designer.core.backend.virtual_app`` to get
``refresh_machines_virtual``. That import executed virtual_app's
top-level statement ``app = build_virtual_app()``, which calls
``create_app`` → ``RunManager.__init__`` → ``_recover_orphan_running_
runs``. The recovery path lists every run in the state DB with
status="running" and terminates the recorded pid. Backend had written
the current batch's row with status="running" milliseconds before
spawning the subprocess, so the subprocess terminated its OWN pid on
startup and exited rc=1 with no stdout/stderr output.

User-visible symptom:
  ✗ [M1sim] 失败: analyzer exit_code=1 | summary missing:
  player_impact_summary.json | report miss

Fix: extracted registry helpers into ``slot_designer.core.backend.virtual_
registry`` (zero side-effects) and switched virtual_analyzer to import
from there instead of from virtual_app.

These tests guard the fix.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent.parent


def test_virtual_analyzer_source_never_imports_virtual_app():
    """Static check: grep virtual_analyzer.py source. The string
    ``from slot_designer.core.backend.virtual_app`` must NOT appear —
    that's the suicide import. If someone re-adds it, this test
    fails before the bug ships.

    Back-compat re-export from virtual_registry → virtual_app is
    fine; what matters is virtual_analyzer itself never reaches
    into virtual_app.
    """
    src = (_ROOT  / "slot_designer" / "core" / "backend" / "virtual_analyzer.py").read_text(
        encoding="utf-8"
    )
    bad_imports = [
        "from slot_designer.core.backend.virtual_app",
        "import slot_designer.core.backend.virtual_app",
    ]
    for pattern in bad_imports:
        assert pattern not in src, (
            f"virtual_analyzer.py imports {pattern!r} — that pulls in "
            f"virtual_app's module-level `app = build_virtual_app()` "
            f"which triggers RunManager._recover_orphan_running_runs. "
            f"In a subprocess that already has status='running' in the "
            f"DB, this terminates the subprocess's OWN pid and it "
            f"exits rc=1 silently. Import from virtual_registry instead."
        )


def test_virtual_registry_does_not_pull_in_web_console_app():
    """Spawning a fresh Python, importing virtual_registry must NOT
    cause ``src.web_console.backend.app`` to get imported. That module
    contains ``create_app`` whose side-effects are the root cause of
    the suicide. virtual_registry should be entirely standalone.
    """
    code = textwrap.dedent("""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path.cwd()))
        from slot_designer.core.backend.virtual_registry import (  # noqa: F401
            VIRTUAL_MACHINES_CONFIG,
            refresh_machines_virtual,
        )
        bad = "src.web_console.backend.app"
        if bad in sys.modules:
            srcs = [k for k in sys.modules if k.startswith("src.")]
            print(f"LEAK: {bad} imported; src.* keys: {srcs!r}")
            raise SystemExit(1)
        print("OK")
    """)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_ROOT), capture_output=True, text=True, env=env, timeout=30,
    )
    assert out.returncode == 0, (
        f"virtual_registry import leak: rc={out.returncode}\n"
        f"stdout: {out.stdout}\n"
        f"stderr: {out.stderr}"
    )
    assert "OK" in out.stdout


def test_virtual_analyzer_subprocess_does_not_pull_in_web_console_app():
    """End-to-end: spawn virtual_analyzer.py as a subprocess exactly
    like backend does, but force it to exit fast BEFORE any sampling
    by pointing --machine at a name that's not in the registry. The
    subprocess should fail cleanly (RuntimeError from
    _find_machine_entry) without ever triggering virtual_app's
    create_app side-effects.

    We verify by inspecting stderr for a specific marker — and by
    asserting rc != 1 with empty stderr (the old suicide signature).
    """
    # Synthesize the backend-style argv
    argv = [
        sys.executable,
        str(_ROOT  / "slot_designer" / "core" / "backend" / "virtual_analyzer.py"),
        "--machine", "__NonExistentMachine__",
        "--rtp-mode", "1",
        "--chunk-spin-times", "100",
        "--chunk-robot-count", "1",
        "--max-chunks", "1",
        "--output-dir", str(_ROOT / "slot_designer" / "_dev_scratch" / "_test_nonexistent"),
        "--run-id", "suicide_test",
        "--resume-from-cache", str(_ROOT / "slot_designer" / "_dev_scratch" / "_nonexistent_rawdata"),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    out = subprocess.run(
        argv, cwd=str(_ROOT), capture_output=True, text=True, env=env, timeout=30,
    )
    # Expect either:
    #   - Clean RuntimeError from _find_machine_entry (stderr mentions
    #     "virtual machine '__NonExistentMachine__' not in
    #     machines_virtual.json")
    # NOT expected (the bug signature):
    #   - rc=1 with empty stderr+stdout (silent suicide)
    silent_suicide = (out.returncode == 1 and not out.stderr.strip() and not out.stdout.strip())
    assert not silent_suicide, (
        f"virtual_analyzer exited rc=1 with NO stdout/stderr — that's "
        f"the silent-suicide signature from the 2026-04-21 bug. "
        f"Something in the main() path is importing virtual_app and "
        f"triggering _recover_orphan_running_runs on its own pid.\n"
        f"rc={out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}"
    )
    # Stronger positive assertion: stderr should mention the machine
    # name (Python RuntimeError traceback) — confirming the code got
    # far enough to reach _find_machine_entry.
    assert "__NonExistentMachine__" in out.stderr or "__NonExistentMachine__" in out.stdout, (
        f"Expected stderr to mention the bad machine name (from "
        f"_find_machine_entry's RuntimeError). Got:\n"
        f"rc={out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}"
    )


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
