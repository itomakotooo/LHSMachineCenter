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


def _build_mixed_md5_fixture(
    src_chunk: Path, dst_dir: Path, mix: list[tuple[str, str, int]],
) -> tuple[str, str, int]:
    """Build a tmp cache dir with chunks at varying md5s by COPYING
    a real on-disk chunk envelope and re-stamping its md5 fields.

    Why copy a real chunk: synthetic envelopes need to satisfy the
    analyzer's full schema validation (StopSymbolsByCol per round +
    sha256 over the response array, etc.) — recreating that from
    scratch is brittle. A real chunk already passes validation;
    we just rewrite the md5 stamps and DROP the sha256 field
    (load_chunk_envelope falls through to legacy-v2 path when
    _payload_sha256 is absent, which still validates structure but
    skips the hash check).

    ``mix`` is a list of (cfg_md5, code_md5, count) tuples. Returns
    the (cfg, code, count) of the SECOND-LARGEST bucket — that's
    a reliable narrowing target (smaller than total but non-zero).
    """
    base = json.loads(src_chunk.read_text(encoding="utf-8"))
    base.pop("_payload_sha256", None)
    base["_envelope_version"] = 2  # accept-as-legacy path
    next_idx = 1
    for cfg, code, count in mix:
        for _ in range(count):
            chunk = {**base, "_config_md5": cfg, "_code_md5": code,
                     "_chunk_index": next_idx}
            (dst_dir / f"chunk_{next_idx:04d}.json").write_text(
                json.dumps(chunk, ensure_ascii=False), encoding="utf-8",
            )
            next_idx += 1
    # Pick the smallest non-empty bucket as the narrowing target.
    smallest = min(mix, key=lambda t: t[2])
    return smallest


@pytest.mark.skipif(
    not M1SIM_RAWDATA.exists() or not any(M1SIM_RAWDATA.glob("chunk_*.json")),
    reason="M1sim rawdata not present in this checkout — need a real "
           "envelope to clone for the mixed-md5 fixture",
)
def test_e2e_pre_filter_narrows_to_matching_md5_real_subprocess(tmp_path):
    """REGRESSION 2026-04-26 (the user's "你做完就不会自己测一下" case):
    spawn the REAL analyzer subprocess on a constructed mixed-md5
    cache and prove the cache_read_start event reports ONLY the
    matching chunk count.

    Builds a mixed-md5 fixture by cloning a real M1sim chunk (so
    schema validation passes) and re-stamping md5s. Independent of
    M1sim's current on-disk state — works whether M1sim has 1 or
    14 md5 buckets at test time.

    Pre-fix would observe ``cache_read_start.total_chunks = 30``
    (full disk). Post-fix observes the matching bucket size.
    """
    # Find a real chunk to use as the schema-valid template.
    real_chunks = sorted(M1SIM_RAWDATA.glob("chunk_*.json"))
    if not real_chunks:
        pytest.skip("M1sim rawdata is empty")
    template_chunk = real_chunks[0]

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    # 5 chunks at md5 NEW_CFG, 25 chunks at md5 OLD_CFG.
    OLD_CFG = "old_cfg_aaaaaaaaaaaaaaaaaaaaaaaaaaaaa1"
    NEW_CFG = "new_cfg_bbbbbbbbbbbbbbbbbbbbbbbbbbbbb2"
    CODE = "code_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx3"
    target_cfg, target_code, expected_match = _build_mixed_md5_fixture(
        template_chunk, cache_dir,
        mix=[(OLD_CFG, CODE, 25), (NEW_CFG, CODE, 5)],
    )
    total_disk = sum(1 for _ in cache_dir.glob("chunk_*.json"))
    assert total_disk == 30
    assert expected_match == 5, "fixture should narrow 30→5"

    output_dir = tmp_path / "out"
    progress_file = tmp_path / "progress.jsonl"
    rc = _run_analyzer(
        cache_dir, target_cfg, target_code, progress_file, output_dir,
    )
    assert rc.returncode == 0, (
        f"analyzer subprocess failed (rc={rc.returncode})\n"
        f"STDERR: {rc.stderr[-2000:]}"
    )

    events = _read_progress_events(progress_file)
    cache_starts = [e for e in events if e.get("event") == "cache_read_start"]
    assert len(cache_starts) == 1, (
        f"expected one cache_read_start event, got {len(cache_starts)}"
    )

    actual_total = cache_starts[0]["total_chunks"]
    # SMOKING GUN: total_chunks reflects matching subset, NOT full disk.
    # Pre-fix would emit 30 (full disk). Post-fix emits 5 (matching).
    assert actual_total == expected_match, (
        f"PRE-FILTER REGRESSION: cache_read_start reported total_chunks="
        f"{actual_total}, expected {expected_match} (matching bucket). "
        f"{total_disk} = pre-filter not firing → user's '已读 X/Y · 0 "
        f"spins' symptom."
    )

    completed = [e for e in events if e.get("event") == "completed"]
    assert len(completed) == 1, "expected analyzer to complete cleanly"
    assert completed[0].get("chunks") == expected_match, (
        f"completed event reports chunks={completed[0].get('chunks')}, "
        f"expected {expected_match}"
    )


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
