"""End-to-end integration test: spawn the real analyzer subprocess
against a tmp rawdata dir with mixed-md5 chunks, parse its progress
events, assert the cache_read_start emits ``total_chunks = matching
count`` (not the full disk count).

User feedback 2026-04-26: "你做完就不会自己测一下". Right — every prior
commit on this code path had unit tests but NEVER spawned the actual
analyzer subprocess to verify the wall-time invariant. This test
closes that gap by running the full subprocess end-to-end and
inspecting the JSONL progress stream the user sees in the UI.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _run_analyzer(
    cache_dir: Path,
    upstream_cfg: str,
    upstream_code: str,
    progress_file: Path,
    output_dir: Path,
) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable, "-m", "fresh_slotlab.player_impact_analyzer",
        "--machine", "M1",
        "--rtp-mode", "1",
        "--bet", "1000",
        "--output-dir", str(output_dir),
        "--target-halfwidth-pp", "0.001",
        "--max-chunks", "99999",
        "--chunk-spin-times", "100",
        "--chunk-robot-count", "2",
        "--batch-concurrency", "1",
        "--timeout", "10",
        "--bankruptcy-session-spins", "100",
        "--bankruptcy-bankroll-multipliers", "10",
        "--from-cache", str(cache_dir),
        "--upstream-config-md5", upstream_cfg,
        "--upstream-code-md5", upstream_code,
        "--progress-file", str(progress_file),
        "--run-id", "test_e2e",
    ]
    return subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=60,
    )


def _read_progress_events(progress_file: Path) -> list[dict]:
    if not progress_file.exists():
        return []
    out = []
    for line in progress_file.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ── Tests ─────────────────────────────────────────────────────────────


M1SIM_RAWDATA = ROOT / "slot_designer" / "rawdata" / "M1sim" / "mode_1"


@pytest.mark.skipif(
    not M1SIM_RAWDATA.exists() or not any(M1SIM_RAWDATA.glob("chunk_*.json")),
    reason="M1sim mixed-md5 rawdata not present in this checkout",
)
def test_e2e_pre_filter_narrows_to_matching_md5_real_subprocess(tmp_path):
    """REGRESSION 2026-04-26 (the user's exact "你做完就不会自己测一下"
    case): spawn the REAL analyzer subprocess on M1sim's actual mixed-
    md5 rawdata and prove the cache_read_start event reports ONLY the
    matching chunk count.

    Uses the existing M1sim/mode_1 rawdata (1443 chunks, 4 md5
    versions) as the fixture — building synthetic envelopes that
    pass schema validation is a rabbit hole, and using the live
    fixture means the test reflects the user's actual scenario.

    Without the pre-filter fix (cb2355d), this test observes
    ``cache_read_start.total_chunks = 1443`` (full disk). With it,
    we expect a small matching count (1-369 depending on which md5
    bucket we filter for). The exact md5 fields are read from the
    sidecar at test time so this stays robust against future M1sim
    re-tunes that change md5s.
    """
    from fresh_slotlab.chunk_index import get_chunks_index

    sidecar = get_chunks_index(M1SIM_RAWDATA)
    chunks = sidecar.get("chunks") or {}
    if not chunks:
        pytest.skip("M1sim sidecar has no chunks indexed")

    # Pick the md5 bucket with the smallest count — best demonstrates
    # narrowing. Bucket-size doesn't matter for the assertion, just
    # needs to be MUCH less than total.
    by_md5 = sidecar.get("by_md5") or {}
    if not by_md5:
        pytest.skip("M1sim sidecar missing by_md5 — fix not deployed?")
    smallest_key = min(by_md5.keys(), key=lambda k: len(by_md5[k]))
    cfg_part, _, code_part = smallest_key.partition("|")
    expected_match = len(by_md5[smallest_key])
    total_disk = len(chunks)
    assert total_disk > expected_match, (
        f"need a narrowing scenario; bucket {smallest_key[:16]}... has "
        f"{expected_match} chunks but disk total is {total_disk} — pick a "
        f"different fixture if M1sim ever drops to a single md5"
    )

    output_dir = tmp_path / "out"
    progress_file = tmp_path / "progress.jsonl"
    rc = _run_analyzer(M1SIM_RAWDATA, cfg_part, code_part, progress_file, output_dir)
    assert rc.returncode == 0, (
        f"analyzer subprocess failed (rc={rc.returncode})\n"
        f"STDERR: {rc.stderr[-1500:]}"
    )

    events = _read_progress_events(progress_file)
    cache_starts = [e for e in events if e.get("event") == "cache_read_start"]
    assert len(cache_starts) == 1, (
        f"expected one cache_read_start event, got {len(cache_starts)}"
    )

    actual_total = cache_starts[0]["total_chunks"]
    # SMOKING GUN: total_chunks reflects matching subset, NOT full disk.
    # Pre-fix would emit total_disk (e.g. 1443). Post-fix emits
    # expected_match (the bucket count from sidecar).
    assert actual_total == expected_match, (
        f"PRE-FILTER REGRESSION: cache_read_start reported total_chunks="
        f"{actual_total}, expected {expected_match} (size of md5 bucket "
        f"{cfg_part[:8]}...). {total_disk} would mean pre-filter not "
        f"firing (= the user's '已读 X/436 · 0 spins' symptom)."
    )

    completed = [e for e in events if e.get("event") == "completed"]
    if completed:
        # If completed event fired, it should report the same count.
        assert completed[0].get("chunks") == expected_match


@pytest.mark.skipif(
    not M1SIM_RAWDATA.exists() or not any(M1SIM_RAWDATA.glob("chunk_*.json")),
    reason="M1sim mixed-md5 rawdata not present in this checkout",
)
def test_e2e_pre_filter_no_match_completes_cleanly(tmp_path):
    """When zero chunks match the filter (e.g. operator just pulled a
    brand-new md5 and the historical cache has nothing matching),
    the analyzer should complete cleanly — NOT crash with
    "no chunk_*.json files found" (the pre-fix behavior in
    main()'s 'if not chunk_files and not resume_mode' guard).

    Uses M1sim's real rawdata as the fixture; passes a sentinel
    md5 that's guaranteed not to match.
    """
    output_dir = tmp_path / "out"
    progress_file = tmp_path / "progress.jsonl"
    # Sentinel md5 — never produced by any real machine config.
    rc = _run_analyzer(
        M1SIM_RAWDATA,
        "ffffffffffffffffffffffffffffffff_sentinel_no_match",
        "ffffffffffffffffffffffffffffffff_sentinel_no_match",
        progress_file, output_dir,
    )
    assert rc.returncode == 0, (
        f"analyzer should not crash on no-match-after-filter; "
        f"rc={rc.returncode}\n"
        f"STDERR: {rc.stderr[-1500:]}"
    )
    # No cache_read_start because chunk_files is empty (event only
    # fires when total_to_read > 0).
    events = _read_progress_events(progress_file)
    starts = [e for e in events if e.get("event") == "cache_read_start"]
    assert len(starts) == 0
