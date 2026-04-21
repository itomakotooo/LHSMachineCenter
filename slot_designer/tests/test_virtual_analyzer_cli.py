"""Regression: virtual_analyzer accepts + forwards flags added to the
real analyzer's CLI without requiring parallel edits.

Locks two invariants from the 2026-04-21 virtual-sampling regression:

  1. argparse uses ``parse_known_args`` — new backend-side flags
     (like ``--upstream-config-md5`` / ``--upstream-code-md5`` from
     8f74213) don't error out here before sampling can start.

  2. md5-filter flags flow through to the delegated real-analyzer
     ``--from-cache`` call so historical-md5 virtual chunks are
     excluded from stats during replay, matching the real-analyzer
     behavior.

  3. Unknown flags captured by ``parse_known_args`` are NOT forwarded
     to the delegated real-analyzer call — the real analyzer uses
     strict ``parse_args`` and would rc=2 on anything it doesn't know.
     (Virtual sampling logs which flags got dropped so operators can
     see it.)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.backend.virtual_analyzer import (
    _build_delegate_cmd,
    _parse_args,
)


def _parse(argv: list[str]):
    """Invoke virtual_analyzer's argparse in-process with a spoofed argv."""
    import argparse
    # _parse_args reads sys.argv via argparse; monkey-patch for the call.
    old = sys.argv[:]
    sys.argv = ["virtual_analyzer.py", *argv]
    try:
        return _parse_args()
    finally:
        sys.argv = old


def test_parse_known_args_tolerates_unknown_flags():
    """Backend may add new analyzer flags between releases. Virtual
    analyzer must accept them (and capture them for forwarding) rather
    than argparse-erroring out.
    """
    argv = [
        "--machine", "M1sim", "--rtp-mode", "1",
        "--output-dir", "/tmp/x",
        "--upstream-config-md5", "cfg123",
        "--upstream-code-md5", "code456",
        "--future-unknown-flag", "value",
        "--another-future-bool",
    ]
    args, extras = _parse(argv)
    assert args.machine == "M1sim"
    assert args.upstream_config_md5 == "cfg123"
    assert args.upstream_code_md5 == "code456"
    # Unknown flags land in the extras list (to be forwarded).
    assert "--future-unknown-flag" in extras
    assert "value" in extras
    assert "--another-future-bool" in extras


def test_delegate_cmd_forwards_md5_filter_flags():
    """When operator / backend passes ``--upstream-*-md5``, the delegated
    real-analyzer call must carry them — otherwise historical-md5
    chunks get merged into stats during replay and pollute the RTP.
    """
    argv = [
        "--machine", "M1sim", "--rtp-mode", "1",
        "--output-dir", "/tmp/out",
        "--upstream-config-md5", "CFG_HASH",
        "--upstream-code-md5", "CODE_HASH",
    ]
    args, _extras = _parse(argv)
    cmd = _build_delegate_cmd(args, Path("/tmp/cache"))

    # md5 flags are present and paired with the right values
    assert "--upstream-config-md5" in cmd
    assert cmd[cmd.index("--upstream-config-md5") + 1] == "CFG_HASH"
    assert "--upstream-code-md5" in cmd
    assert cmd[cmd.index("--upstream-code-md5") + 1] == "CODE_HASH"


def test_delegate_cmd_does_not_forward_unknown_extras():
    """Unknown flags caught by parse_known_args must NOT end up in the
    real-analyzer command — that analyzer uses strict parse_args and
    would rc=2 on anything unrecognized. Honoring a new backend flag
    on the virtual side requires an explicit declaration in both
    _parse_args and _build_delegate_cmd.
    """
    argv = [
        "--machine", "M1sim", "--rtp-mode", "1",
        "--output-dir", "/tmp/out",
        "--some-hypothetical-flag", "42",
        "--another-future-bool",
    ]
    args, extras = _parse(argv)
    # Extras captured correctly (parse_known_args doesn't error)
    assert "--some-hypothetical-flag" in extras
    assert "--another-future-bool" in extras
    # But NOT forwarded to real analyzer
    cmd = _build_delegate_cmd(args, Path("/tmp/cache"))
    assert "--some-hypothetical-flag" not in cmd
    assert "--another-future-bool" not in cmd
    assert "42" not in cmd


def test_delegate_cmd_skips_md5_filter_when_empty():
    """Empty md5 = no filter (backend's default when machine has no
    registered md5 yet). Don't emit empty-string CLI args — they're
    valid to the real analyzer but noisy in logs.
    """
    argv = [
        "--machine", "M1sim", "--rtp-mode", "1",
        "--output-dir", "/tmp/out",
        # no --upstream-*-md5 → default ""
    ]
    args, _extras = _parse(argv)
    cmd = _build_delegate_cmd(args, Path("/tmp/cache"))
    assert "--upstream-config-md5" not in cmd
    assert "--upstream-code-md5" not in cmd


def test_subprocess_does_not_argparse_error_on_new_flags():
    """End-to-end guard: run virtual_analyzer.py as a subprocess with
    the same argv backend sends (incl. the new md5 flags). Pre-fix this
    exited rc=2 with ``usage: ...`` from argparse. After fix, it must
    get past arg parsing.

    We intentionally pass --machine that doesn't exist so the process
    exits fast (RuntimeError from _find_machine_entry) rather than
    actually sampling — the assertion is just "didn't fail at
    argparse".
    """
    cmd = [
        sys.executable, "slot_designer/backend/virtual_analyzer.py",
        "--machine", "M1sim",
        "--rtp-mode", "1",
        "--chunk-spin-times", "10",
        "--chunk-robot-count", "1",
        "--max-chunks", "0",  # 0 chunks → loop body never runs
        "--output-dir", str(_ROOT / "slot_designer" / "_dev_scratch" / "_test_virt"),
        "--upstream-config-md5", "cfg_test",
        "--upstream-code-md5", "code_test",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run(
        cmd, cwd=str(_ROOT), capture_output=True, text=True,
        env=env, timeout=60,
    )
    # argparse exits rc=2 with 'usage:' when unknown flag is rejected.
    # After the fix that path is gone — we either succeed through or
    # fail further in (RuntimeError, delegation failure, etc.).
    assert r.returncode != 2 or "unrecognized arguments" not in r.stderr, (
        f"virtual_analyzer argparse rejected a flag it should forward.\n"
        f"rc={r.returncode}\nstderr={r.stderr[:500]}"
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
