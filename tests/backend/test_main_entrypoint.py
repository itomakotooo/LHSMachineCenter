"""Tests for src/web_console/backend/main.py __main__ env-var support (P4-T2).

Memory feedback cited:
- feedback_perf_claim_needs_e2e_event_stream.md — the __main__ branch is
  tested by running the ACTUAL __main__ block from main.py via runpy, not by
  duplicating the env-read logic inside the test. This ensures the test catches
  real regressions in the source file.
- feedback_subprocess_import_suicide_and_module_globals.md — importing the
  module at module level must have NO side effects; only the __main__ block
  reads env vars.

Inject-bug recipe:
  BUG-E (env read in main.py):
    In src/web_console/backend/main.py __main__ block, change:
        _host = os.environ.get("SLOT_BIND_HOST", "0.0.0.0")
    to:
        _host = "127.0.0.1"  # hardcoded, ignores env
    Expected: test_main_main_uses_env_bind_host_when_set goes RED
              (captured host is "127.0.0.1" not "10.0.0.1").

  BUG-F (default port):
    Change:
        _port = int(os.environ.get("SLOT_BIND_PORT", "8877"))
    to:
        _port = 8765
    Expected: test_main_main_defaults_to_0_0_0_0_8877 goes RED
              (captured port is 8765 not 8877).
"""
from __future__ import annotations

import ast
import os
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = REPO_ROOT / "src" / "web_console" / "backend" / "main.py"


def _extract_and_run_main_block(extra_env: dict[str, str]) -> dict:
    """Parse main.py, extract the __main__ block body, and run it in a
    controlled namespace with a stubbed uvicorn.run. Returns captured kwargs.

    This exercises the REAL source code in main.py rather than duplicating
    the logic in the test, so inject-bug regressions are caught.
    """
    source = MAIN_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Find the `if __name__ == "__main__":` block.
    main_block_nodes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            if (isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name)
                    and test.left.id == "__name__"
                    and len(test.comparators) == 1
                    and isinstance(test.comparators[0], ast.Constant)
                    and test.comparators[0].value == "__main__"):
                main_block_nodes = node.body
                break

    assert main_block_nodes, "Could not find if __name__ == '__main__' block in main.py"

    # Re-assemble as a module-level block we can exec.
    # Wrap in a dummy module so line numbers don't confuse exec.
    block_source = ast.unparse(ast.Module(body=main_block_nodes, type_ignores=[]))

    captured: dict = {}

    def fake_uvicorn_run(app, *, host, port, reload):
        captured["host"] = host
        captured["port"] = port

    import uvicorn

    ns = {"__name__": "__main__"}
    with patch.object(uvicorn, "run", side_effect=fake_uvicorn_run):
        with patch.dict(os.environ, extra_env, clear=False):
            # Remove keys the caller didn't set so we don't leak caller env.
            for key in ("SLOT_BIND_HOST", "SLOT_BIND_PORT"):
                if key not in extra_env:
                    os.environ.pop(key, None)
            exec(compile(block_source, str(MAIN_PY), "exec"), ns)  # noqa: S102

    return captured


# ---------------------------------------------------------------------------
# T2-1: import has no env reads (create_app semantics unchanged)
# ---------------------------------------------------------------------------

def test_main_import_no_env_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing src.web_console.backend.main must not read SLOT_BIND_HOST
    or SLOT_BIND_PORT. Only the __main__ block does env reads.

    Strategy: monkeypatch os.environ to detect any reads of those keys, then
    import the module (or reload it) and assert no read occurred.
    """
    read_keys: list[str] = []

    class _TrackedEnv(dict):
        def get(self, key, default=None):  # type: ignore[override]
            read_keys.append(key)
            return super().get(key, default)

        def __getitem__(self, key):
            read_keys.append(key)
            return super().__getitem__(key)

    real_environ = os.environ.copy()
    tracked = _TrackedEnv(real_environ)

    with patch("os.environ", tracked):
        if "src.web_console.backend.main" in sys.modules:
            del sys.modules["src.web_console.backend.main"]
        import src.web_console.backend.main as main_mod  # noqa: F401

    deploy_keys = {k for k in read_keys
                   if k in ("SLOT_BIND_HOST", "SLOT_BIND_PORT")}
    assert not deploy_keys, (
        f"Module import should NOT read deploy env vars. Got: {deploy_keys}"
    )

    assert hasattr(main_mod, "app"), "main.py must expose 'app' at module level"


# ---------------------------------------------------------------------------
# T2-2: __main__ block uses SLOT_BIND_HOST when set
# ---------------------------------------------------------------------------

def test_main_main_uses_env_bind_host_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """When SLOT_BIND_HOST=10.0.0.1, uvicorn.run must receive host='10.0.0.1'.

    Exercises the REAL __main__ block extracted from main.py so that
    hardcoding _host in the source will make this test RED.
    """
    monkeypatch.delenv("SLOT_BIND_PORT", raising=False)

    captured = _extract_and_run_main_block({"SLOT_BIND_HOST": "10.0.0.1"})

    assert captured.get("host") == "10.0.0.1", (
        f"Expected host='10.0.0.1', got {captured.get('host')!r}"
    )
    assert captured.get("port") == 8877


# ---------------------------------------------------------------------------
# T2-3: __main__ block defaults to 0.0.0.0:8877 with no env
# ---------------------------------------------------------------------------

def test_main_main_defaults_to_0_0_0_0_8877(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no env vars set, __main__ block must use host=0.0.0.0, port=8877.

    Exercises the REAL __main__ block extracted from main.py so that
    hardcoding _port=8765 in the source will make this test RED.
    """
    monkeypatch.delenv("SLOT_BIND_HOST", raising=False)
    monkeypatch.delenv("SLOT_BIND_PORT", raising=False)

    captured = _extract_and_run_main_block({})

    assert captured.get("host") == "0.0.0.0", (
        f"Expected default host='0.0.0.0', got {captured.get('host')!r}"
    )
    assert captured.get("port") == 8877, (
        f"Expected default port=8877, got {captured.get('port')!r}"
    )
