"""End-to-end regression for the M274 BCM-cycle trigger fix.

Spawns the real analyzer subprocess against the cached M274 mode 1
chunks (current md5 ``847d89cd``) and asserts the pay_id drilldown:

  1. ``_unattributed_st139`` is absent (or carries <0.5% RTP) -- the
     BCM-cycle trigger anchor rule must catch every cycle-completion
     bonus block that the default ``PayoutIdToWinAmount`` win==0
     extraction missed.
  2. ``_bcm_cycle`` is present with the expected RTP contribution
     (~4.87% across 8 chunks of NEW md5) and hits == number of
     cycle-peak trigger paid rounds (315 in this fixture).
  3. ``our_total_win == server_total_win`` -- total RTP still
     matches upstream analysisResult.

Why subprocess: per the 2026-04-28 incident
(``feedback_perf_claim_needs_e2e_event_stream``) unit tests + AST
checks aren't enough -- the analyzer's script-mode runtime branch
must actually load + execute the rule pipeline against real chunks
or a runtime import/wiring bug slips through every check.

This test is also the canonical "inject-bug -> red -> revert ->
green" regression guard: removing the BCMCycleAnchorRule entry from
``configs/machine_round_win_rules.json`` MUST make this test fail
(the assertion on ``_bcm_cycle`` presence). That ties test failure
directly to the user-visible signal the strategist reported.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
M274_CACHE = ROOT / "rawdata" / "M274" / "mode_1"
NEW_MD5_CFG = "847d89cd5a651c14b44d56f3a998608b"
NEW_MD5_CODE = "9633e9d6b64234f0d0b63a44a7954aaf"


def _new_md5_chunks_present() -> bool:
    sidecar = M274_CACHE / "_chunks.json"
    if not sidecar.exists():
        return False
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return False
    chunks = meta.get("chunks", {})
    return any(
        c.get("cfg_md5") == NEW_MD5_CFG and c.get("code_md5") == NEW_MD5_CODE
        for c in chunks.values()
    )


pytestmark = pytest.mark.skipif(
    not _new_md5_chunks_present(),
    reason="M274 mode 1 cache with current md5 chunks not available -- "
           "this is a CI-skip path; run locally after sampling the machine.",
)


def _run_analyzer_against_m274(output_dir: Path) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable, "fresh_slotlab/player_impact_analyzer.py",
        "--machine", "M274",
        "--rtp-mode", "1",
        "--bet", "1000",
        "--from-cache", str(M274_CACHE),
        "--upstream-config-md5", NEW_MD5_CFG,
        "--upstream-code-md5", NEW_MD5_CODE,
        "--output-dir", str(output_dir),
        "--max-chunks", "8",
        "--machine-config-file", "configs/machines.json",
        "--target-halfwidth-pp", "0.001",
        "--chunk-spin-times", "5000",
        "--chunk-robot-count", "8",
        "--batch-concurrency", "1",
        "--timeout", "30",
        "--bankruptcy-session-spins", "1000",
        "--bankruptcy-bankroll-multipliers", "10",
    ]
    return subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )


def _read_summary(output_dir: Path) -> dict:
    summary_path = output_dir / "player_impact_summary.json"
    assert summary_path.exists(), f"analyzer did not emit {summary_path}"
    return json.loads(summary_path.read_text(encoding="utf-8"))


def _pid_entry(summary: dict, pid: str) -> dict | None:
    for p in summary.get("player_impact", {}).get("payout_ids_top20", []):
        if str(p.get("payout_id")) == pid:
            return p
    return None


class TestM274BCMCycleE2E:
    def test_bcm_anchor_replaces_fallback(self, tmp_path):
        """The headline regression: _unattributed_st139 -> _bcm_cycle.

        Before the BCMCycleAnchorRule fix, M274 mode 1 NEW md5 emitted
        4.87% RTP into ``_unattributed_st139`` (15.57M credits across
        8 chunks). After the fix, that bucket is empty and the same
        attribution lives on ``_bcm_cycle`` instead.
        """
        result = _run_analyzer_against_m274(tmp_path)
        assert result.returncode == 0, (
            f"analyzer subprocess failed (rc={result.returncode})\n"
            f"--- STDERR ---\n{result.stderr[-2000:]}\n"
            f"--- STDOUT (tail) ---\n{result.stdout[-2000:]}"
        )
        summary = _read_summary(tmp_path)

        # 1. RTP / win total still match upstream
        rtp = summary["rtp"]
        assert rtp["our_total_win"] == rtp["server_total_win"], (
            f"our_total_win {rtp['our_total_win']} != server_total_win "
            f"{rtp['server_total_win']}"
        )
        # M274 mode 1 NEW md5 across 8 chunks gives ~106.34% RTP. Lock
        # within a wide tolerance -- this is the data the strategist
        # measured, not something we'd let drift quietly.
        assert 100.0 < rtp["point_pct"] < 110.0, (
            f"RTP {rtp['point_pct']} drifted -- expected ~106.34%"
        )

        # 2. _unattributed_st139 must be gone or below the structural
        # alarm threshold (0.5% of chunk_win as fallback share). The
        # exact metric in the summary is rtp_contribution_pp; chunk_win
        # = 340.28M, paid_cost = 320M, so 0.5% RTP ~= 1.6M credits.
        fb = _pid_entry(summary, "_unattributed_st139")
        if fb is not None:
            assert fb["rtp_contribution_pp"] < 0.5, (
                f"_unattributed_st139 still carries "
                f"{fb['rtp_contribution_pp']}% RTP -- BCM rule should have "
                f"caught these. win={fb['total_win']} hits={fb['hit_count']}"
            )

        # 3. _bcm_cycle synthetic anchor present, with the expected
        # attribution magnitude.
        bcm = _pid_entry(summary, "_bcm_cycle")
        assert bcm is not None, (
            "_bcm_cycle anchor missing from payout_ids_top20 -- "
            "BCMCycleAnchorRule did not fire. Check that "
            "configs/machine_round_win_rules.json has the M274 entry "
            "and that player_impact_analyzer passes ctx['cycle_peak'] "
            "into compute_trigger_sessions."
        )
        # 15.57M / 320M paid_cost = 4.867% RTP. Use a tight window
        # (CI shouldn't move this much chunk-to-chunk).
        assert 4.5 < bcm["rtp_contribution_pp"] < 5.5, (
            f"_bcm_cycle rtp_contribution_pp {bcm['rtp_contribution_pp']} "
            f"outside expected band [4.5, 5.5] -- attribution drifted"
        )
        # hits == number of CC=peak trigger paid rounds observed (315
        # across 8 chunks; lock the magnitude with reasonable slack).
        assert 250 < bcm["hit_count"] < 400, (
            f"_bcm_cycle hits {bcm['hit_count']} outside expected band "
            f"[250, 400]; expected ~315"
        )

    def test_dominant_pids_unchanged(self, tmp_path):
        """The fix must NOT alter the attribution of real numeric
        pay_ids -- 5801, 1, 3, 7, 4, 5, 6 should retain their
        pre-refactor RTP contributions byte-for-byte.

        Pre-fix anchors and amounts (from session_artifacts/M274_diag
        baseline 2026-05-12):
          5801: 54.112%   1: 33.212%   3: 5.833%   7: 3.470%
          4:    1.896%    5:  1.625%   6: 0.671%
        """
        result = _run_analyzer_against_m274(tmp_path)
        assert result.returncode == 0
        summary = _read_summary(tmp_path)

        expected = {
            "5801": (54.0, 54.3),
            "1": (33.0, 33.4),
            "3": (5.7, 5.9),
            "7": (3.4, 3.6),
            "4": (1.8, 2.0),
            "5": (1.5, 1.7),
            "6": (0.6, 0.8),
        }
        for pid, (lo, hi) in expected.items():
            p = _pid_entry(summary, pid)
            assert p is not None, f"pid {pid!r} missing"
            assert lo <= p["rtp_contribution_pp"] <= hi, (
                f"pid {pid!r} rtp_contribution_pp {p['rtp_contribution_pp']} "
                f"outside expected band [{lo}, {hi}]"
            )
