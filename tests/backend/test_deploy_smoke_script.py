"""Tests for scripts/deploy/run_smoke.ps1 smoke probe script (P4-T4).

Windows-only (spawns powershell.exe subprocess).

Memory feedback cited:
- feedback_perf_claim_needs_e2e_event_stream.md — tests spawn the REAL
  powershell.exe; the DryRun test verifies URL enumeration without
  making network calls.
- feedback_no_silent_swallow.md — unroutable target must produce exit 1
  with a clear failure summary (not silent exit 0).

Inject-bug recipe (not separately listed in P4-T6 but documented here):
  BUG-I (dry-run URL count):
    Remove one of the 5 probe entries from the $probes array in run_smoke.ps1.
    Expected: test_smoke_dry_run_lists_5_endpoints goes RED (only 4 URLs).

  BUG-J (exit code on failure):
    Change "exit 1" to "exit 0" in the anyFail branch of run_smoke.ps1.
    Expected: test_smoke_against_unroutable_fails_loudly_exit_1 goes RED.

Note: test_smoke_passes_against_live_create_app (e2e live server) is
intentionally NOT implemented here — it requires binding port 8877, which
may conflict with a running developer instance. It is marked with a manual
note for the impl-verifier's operator verification checklist.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

WIN_ONLY = pytest.mark.skipif(os.name != "nt", reason="PowerShell deploy scripts are Windows-only")

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "deploy" / "run_smoke.ps1"


def _run_smoke(extra_args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(SMOKE_SCRIPT)] + extra_args,
            # encoding pinned: text=True alone decodes with the locale codepage
            # (GBK on zh-CN Windows) and a single non-GBK byte kills the reader
            # thread -> stdout=None -> TypeError in assertions. The asserted
            # substrings are ASCII, so utf-8 + replace is locale-independent.
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
            cwd=str(REPO_ROOT),
        )
    except FileNotFoundError:
        pytest.skip("powershell.exe not on PATH")


# ---------------------------------------------------------------------------
# T4-1: DryRun lists all 5 endpoint URLs
# ---------------------------------------------------------------------------

@WIN_ONLY
def test_smoke_dry_run_lists_5_endpoints():
    """-DryRun must list 5 URLs in stdout and exit 0."""
    result = _run_smoke(["-DryRun", "-BaseUrl", "http://localhost:8877"])
    assert result.returncode == 0, (
        f"Expected exit 0 for DryRun.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    stdout = result.stdout

    expected_paths = [
        "/console/",
        "/api/machines",
        "/api/system-state",
        "/api/fleet/refresh",
        "/api/configs",
    ]
    for path in expected_paths:
        assert path in stdout, (
            f"Expected endpoint path '{path}' in DryRun output.\nstdout: {stdout}"
        )


# ---------------------------------------------------------------------------
# T4-2: Unroutable target exits 1 with failure summary
# ---------------------------------------------------------------------------

@WIN_ONLY
def test_smoke_against_unroutable_fails_loudly_exit_1():
    """Running against http://192.0.2.1:1 (TEST-NET, RFC 5737 — guaranteed
    unroutable) with -Timeout 2 must exit 1 and mention FAIL in the output."""
    result = _run_smoke(
        ["-BaseUrl", "http://192.0.2.1:1", "-Timeout", "2"],
        timeout=60,  # generous outer timeout; inner PS timeout is 2s × 5 probes = 10s
    )
    assert result.returncode == 1, (
        f"Expected exit 1 for unroutable target.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # The summary table must say FAIL.
    assert "FAIL" in result.stdout, (
        f"Expected 'FAIL' in smoke output.\nstdout: {result.stdout}"
    )


# ---------------------------------------------------------------------------
# T4-3: E2E live server test (manual operator verification)
# ---------------------------------------------------------------------------

@pytest.mark.skip(
    reason=(
        "E2E test requires binding port 8877 locally. "
        "Run manually: start start_console.ps1 in background, then "
        "powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\deploy\\run_smoke.ps1 and verify exit 0. "
        "Automated version risks port conflicts with developer instance."
    )
)
@WIN_ONLY
def test_smoke_passes_against_live_create_app():
    """Placeholder — impl-verifier must perform this manually."""
    pass
