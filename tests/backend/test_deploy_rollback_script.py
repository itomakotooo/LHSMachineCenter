"""Tests for scripts/deploy/rollback.ps1 atomic rollback script (P4-T5).

Windows-only (spawns powershell.exe subprocess).

Memory feedback cited:
- feedback_no_silent_swallow.md — uncommitted changes must produce loud exit 1
  with clear error text, not silent swallow.
- feedback_enumerate_safety_paths.md — every safety carve-out (DryRun / dirty
  repo / confirmation prompt) gets its own test.

Implementer note:
- Stop-ScheduledTask wraps in try/catch and continues if task not registered.
  Test must NOT assert hard-fail when the task is missing.
- Without -Force, the script prompts via Read-Host. In non-interactive
  subprocess mode (stdin closed / empty), the prompt returns empty string
  which is NOT "yes", causing abort with exit 1.

Inject-bug recipe:
  BUG-K (uncommitted-changes guard):
    In rollback.ps1, remove or comment out the block:
        if ($gitStatus) { ... exit 1 }
    Expected: test_rollback_refuses_with_uncommitted_changes goes RED
    (script proceeds past the check instead of exiting 1).

  BUG-L (DryRun skips git reset):
    In rollback.ps1, change the DryRun block for Step 7 to actually call
    git reset --hard instead of printing the dry-run message.
    Expected: test_rollback_dry_run_shows_intended_ops goes RED
    (repo state changes despite DryRun).

  BUG-M (no-Force prompts):
    In rollback.ps1, remove the `if (-not $Force -and -not $DryRun)` block.
    Expected: test_rollback_without_force_prompts_before_reset goes RED
    (script proceeds to reset without confirmation).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

WIN_ONLY = pytest.mark.skipif(os.name != "nt", reason="PowerShell deploy scripts are Windows-only")

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLLBACK_SCRIPT = REPO_ROOT / "scripts" / "deploy" / "rollback.ps1"


def _run_rollback(extra_args: list[str], stdin_text: str = "",
                  timeout: int = 30) -> subprocess.CompletedProcess:
    """Run rollback.ps1 with given args; optionally pipe stdin_text."""
    try:
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(ROLLBACK_SCRIPT)] + extra_args,
            input=stdin_text,
            capture_output=True, text=True, timeout=timeout,
            cwd=str(REPO_ROOT),
        )
    except FileNotFoundError:
        pytest.skip("powershell.exe not on PATH")


# ---------------------------------------------------------------------------
# T5-1: DryRun prints intended ops without modifying repo
# ---------------------------------------------------------------------------

@WIN_ONLY
def test_rollback_dry_run_shows_intended_ops():
    """-DryRun must mention Stop-ScheduledTask and git reset --hard in output,
    exit 0, and NOT actually run git reset."""
    # Record HEAD before.
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    ).stdout.strip()

    result = _run_rollback(["-DryRun"], timeout=30)

    assert result.returncode == 0, (
        f"Expected exit 0 for DryRun.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # DryRun must mention the key operations.
    stdout = result.stdout
    assert "Stop-ScheduledTask" in stdout, (
        f"DryRun output must mention Stop-ScheduledTask.\nstdout: {stdout}"
    )
    assert "git reset --hard" in stdout, (
        f"DryRun output must mention 'git reset --hard'.\nstdout: {stdout}"
    )

    # Repo HEAD must be unchanged.
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    ).stdout.strip()
    assert head_before == head_after, (
        f"DryRun must not modify repo HEAD.\nBefore: {head_before}\nAfter: {head_after}"
    )


# ---------------------------------------------------------------------------
# T5-2: Refuses with uncommitted changes
# ---------------------------------------------------------------------------

@WIN_ONLY
def test_rollback_refuses_with_uncommitted_changes(tmp_path):
    """If git status shows uncommitted changes, rollback must exit 1 with
    a clear error message. We create a dirty file in the repo tree."""
    # Create a temporary dirty file inside the repo.
    dirty_file = REPO_ROOT / "_rollback_test_dirty_sentinel.tmp"
    try:
        dirty_file.write_text("dirty for rollback test\n", encoding="utf-8")

        result = _run_rollback(["-Force"], timeout=30)  # Force skips prompt

        assert result.returncode == 1, (
            f"Expected exit 1 when uncommitted changes exist.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        stdout = result.stdout
        # Must mention the uncommitted changes.
        assert ("Uncommitted" in stdout or "uncommitted" in stdout or
                "ERROR" in stdout), (
            f"Expected error message about uncommitted changes.\nstdout: {stdout}"
        )
    finally:
        if dirty_file.exists():
            dirty_file.unlink()


# ---------------------------------------------------------------------------
# T5-3: Without -Force, prompts before reset (empty stdin = abort)
# ---------------------------------------------------------------------------

@WIN_ONLY
def test_rollback_without_force_prompts_before_reset(tmp_path, monkeypatch):
    """Without -Force, rollback must prompt before git reset --hard.
    In non-interactive mode (empty stdin), the prompt returns '' which is
    NOT 'yes', so the script must abort with exit 1.

    Uses a tmp_path git fixture (2 commits) so the test NEVER skips due to
    real-worktree dirty state. The fixture is clean by construction.

    Inject-bug recipe (BUG-M):
      In rollback.ps1 comment out the block:
          if (-not $Force -and -not $DryRun) { ... Read-Host ... }
      Expected: this test goes RED (HEAD moves to v1 instead of aborting).
      Revert: test goes GREEN again.
    """
    import shutil

    repo = tmp_path / "fixture_repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(repo)] + list(args),
            check=True, capture_output=True, text=True,
        )

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test User")

    # rollback.ps1 derives repo root via:
    #   $repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    # So the script must live at <repo>/scripts/deploy/rollback.ps1.
    # Commit it in v1 so the working tree stays clean for the Step 4 guard.
    scripts_deploy = repo / "scripts" / "deploy"
    scripts_deploy.mkdir(parents=True)
    real_script = REPO_ROOT / "scripts" / "deploy" / "rollback.ps1"
    shutil.copy2(str(real_script), str(scripts_deploy / "rollback.ps1"))

    (repo / "file.txt").write_text("v1")
    git("add", ".")
    git("commit", "-q", "-m", "v1")
    (repo / "file.txt").write_text("v2")
    git("add", ".")
    git("commit", "-q", "-m", "v2")
    # Working tree is now clean: both file.txt and scripts/ are committed.

    fixture_script = scripts_deploy / "rollback.ps1"

    # Empty stdin: operator types nothing → prompt returns "" → NOT "yes" → abort.
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(fixture_script)],
        cwd=str(repo),
        input="",
        capture_output=True, text=True, timeout=30,
    )

    assert result.returncode == 1, (
        f"Expected exit 1 when non-interactive prompt receives empty input.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "aborted" in result.stdout.lower(), (
        f"Expected abort message in stdout.\nstdout: {result.stdout}"
    )

    # Verify HEAD did NOT move (git reset --hard must NOT have run).
    head_after = git("log", "-1", "--format=%s").stdout.strip()
    assert head_after == "v2", (
        f"HEAD moved unexpectedly — git reset --hard ran before operator confirmed.\n"
        f"HEAD message: {head_after}"
    )
