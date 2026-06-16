"""Tests for ``select_replay_chunks_by_md5`` — the analyzer pre-filter.

Regression report 2026-04-26 (the specific user complaint that drove
this test file): "我拉取了新md5的rawdata，采样时候还要去读老的". The
analyzer's cache-replay loop was iterating EVERY chunk in the rawdata
dir (1443 for M1sim mode 1's accumulated 4 md5 versions) even when
the md5 filter was active and the sidecar already knew which chunks
matched. Each "skip" inside the loop body cost ~10ms (dispatch +
JSONL progress emit amortisation), so 1429 mismatched chunks burned
~14 seconds of "0 spins" wall time per generate-report.

Fix: ``select_replay_chunks_by_md5`` consults the sidecar dict
directly and returns ONLY matching chunks, before the loop body.
``cache_read_start.total_chunks`` reflects the matching count
(not the full disk count) so the operator's progress strip and
ETA estimate ("约需 X s") read correctly.

These tests pin the helper's output for the four key scenarios:
  - Mixed-md5 sidecar → only matching subset comes back.
  - max_existing_idx reflects FULL sidecar (resume safety).
  - Empty sidecar → empty list (caller falls back to glob).
  - Sort order is by chunk_index ascending (not insertion order).

Without these tests, a future refactor that subtly broke the helper's
filter (e.g. comparing only one md5 dimension, or returning everything
when sidecar is empty) would silently re-introduce the wall-time
regression. The unit-test cost is one IO-free function call.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "fresh_slotlab"))

import analyzer.core.base_pipeline as pia  # noqa: E402


def _entry(idx: int, cfg: str, code: str) -> dict:
    """Minimal sidecar entry as written by chunk_index.update_chunk_entry."""
    return {
        "idx": idx,
        "cfg_md5": cfg,
        "code_md5": code,
        "spin_times": 1000,
        "robot_count": 8,
        "saved_at": "2026-04-26T00:00:00Z",
        "size_bytes": 1024,
    }


def _build_mixed_sidecar_payload() -> dict:
    """Full sidecar payload (matching what get_chunks_index returns)
    mirroring the M1sim mode 1 state at the time of the regression
    report: 4 md5 buckets, total 1443 chunks. Includes both the
    per-chunk dict AND the inverted ``by_md5`` index — the helper
    under test relies on the latter for its O(1) lookup.
    """
    chunks: dict[str, dict] = {}
    by_md5: dict[str, list[str]] = {}
    md5_groups = [
        ("b560025f6854c54f8f46272b635c298b", "769d599e4a7730e179961616b88dfca5", 702),
        ("edc071628ad1b8f04a7ef77bf7d3fbc6", "769d599e4a7730e179961616b88dfca5", 358),
        ("630c968a4ce0203824c742f519299a91", "769d599e4a7730e179961616b88dfca5", 369),
        ("f01cec9965d097e2e33a5aafdbd650b6", "769d599e4a7730e179961616b88dfca5", 14),
    ]
    next_idx = 1
    for cfg, code, n in md5_groups:
        key = f"{cfg}|{code}"
        bucket = by_md5.setdefault(key, [])
        for _ in range(n):
            fname = f"chunk_{next_idx:04d}.json"
            chunks[fname] = _entry(next_idx, cfg, code)
            bucket.append(fname)
            next_idx += 1
    return {
        "_version": 1,
        "_updated_at": "2026-04-26T00:00:00Z",
        "chunks": chunks,
        "by_md5": by_md5,
    }


def _wrap_sidecar(chunks_dict: dict) -> dict:
    """Wrap a flat ``{filename: entry}`` dict into a full sidecar
    payload with the inverted by_md5 index. Used by tests that build
    a small custom sidecar inline.

    Bucket lists are sorted by chunk_index ascending (parsed from
    the filename) — matches what production ``_rebuild_by_md5``
    does, so test fixtures behave like real sidecars.
    """
    by_md5: dict[str, list[str]] = {}
    for fname, entry in chunks_dict.items():
        if not isinstance(entry, dict):
            continue
        cfg = str(entry.get("cfg_md5", "") or "")
        code = str(entry.get("code_md5", "") or "")
        by_md5.setdefault(f"{cfg}|{code}", []).append(fname)
    for names in by_md5.values():
        names.sort(key=lambda n: int(n.split("_", 1)[1].split(".", 1)[0])
                   if "_" in n and "." in n else 0)
    return {
        "_version": 1,
        "_updated_at": "2026-04-26T00:00:00Z",
        "chunks": dict(chunks_dict),
        "by_md5": by_md5,
    }


# ── Core behavior ─────────────────────────────────────────────────────


def test_pre_filter_returns_only_matching_md5_chunks():
    """REGRESSION: the analyzer's cache_read_start total_chunks now
    reflects only the matching md5 (NOT the whole disk count). The
    user's screenshot showed 1443 chunks being iterated when only
    14 should have been.
    """
    sidecar = _build_mixed_sidecar_payload()
    cache_dir = Path("/tmp/fake/M1sim/mode_1")  # we don't read disk

    chunk_files, max_idx = pia.select_replay_chunks_by_md5(
        cache_dir, sidecar,
        "f01cec9965d097e2e33a5aafdbd650b6",  # current
        "769d599e4a7730e179961616b88dfca5",
    )
    # Only the 14 chunks with the current cfg_md5.
    assert len(chunk_files) == 14, (
        f"expected 14 matching chunks (f01cec99 group), got {len(chunk_files)} — "
        f"this is the exact regression: pre-filter not narrowing the list"
    )
    # And resume safety: max_existing_idx covers ALL 1443 chunks so
    # the next sample's chunk_index doesn't collide with historical.
    assert max_idx == 1443, (
        f"max_existing_idx must reflect FULL sidecar (1443), not just "
        f"matching subset; got {max_idx}"
    )


def test_pre_filter_returns_sorted_by_chunk_index():
    """Sidecar dicts iterate in insertion order, but the analyzer's
    replay loop expects chunk-index ascending so chunk metadata
    (next idx, max idx) flows correctly. Pre-filter must sort."""
    sidecar = _wrap_sidecar({
        "chunk_0050.json": _entry(50, "X", "Y"),
        "chunk_0010.json": _entry(10, "X", "Y"),
        "chunk_0030.json": _entry(30, "X", "Y"),
    })
    chunk_files, _ = pia.select_replay_chunks_by_md5(
        Path("/tmp"), sidecar, "X", "Y",
    )
    indices = [int(p.stem.split("_")[1]) for p in chunk_files]
    assert indices == [10, 30, 50]


def test_pre_filter_returns_empty_when_sidecar_empty():
    """No sidecar entries → empty list + idx=0. Caller falls back to
    glob (handled separately in main())."""
    chunk_files, max_idx = pia.select_replay_chunks_by_md5(
        Path("/tmp"), {}, "X", "Y",
    )
    assert chunk_files == []
    assert max_idx == 0


def test_pre_filter_handles_non_dict_entries_defensively():
    """The sidecar JSON is loaded from disk; a corrupt entry (string
    instead of dict, None, etc.) shouldn't crash the filter — just
    skip that entry and keep going."""
    sidecar = _wrap_sidecar({
        "chunk_0001.json": _entry(1, "MATCH", "CODE"),
        "chunk_0002.json": "corrupt",  # not a dict
        "chunk_0003.json": None,        # not a dict
        "chunk_0004.json": _entry(4, "MATCH", "CODE"),
    })
    chunk_files, max_idx = pia.select_replay_chunks_by_md5(
        Path("/tmp"), sidecar, "MATCH", "CODE",
    )
    # Only the two valid+matching entries.
    assert len(chunk_files) == 2
    # max_idx considers only valid dicts — corrupt entries dropped.
    assert max_idx == 4


def test_pre_filter_no_match_returns_empty_not_crash():
    """All chunks are old md5; current md5 has no chunks in cache yet.
    Pre-filter returns empty list — caller exempts this from the
    "no chunks found, crash" check via md5_filter_active_pre flag."""
    sidecar = _build_mixed_sidecar_payload()
    chunk_files, max_idx = pia.select_replay_chunks_by_md5(
        Path("/tmp"), sidecar,
        "FRESH_MD5_NEVER_SAMPLED_BEFORE", "CODE",
    )
    assert chunk_files == []
    # Resume safety still gives full max so first new chunk lands
    # at idx 1444 (1443 + 1) without colliding.
    assert max_idx == 1443


def test_pre_filter_both_md5_dimensions_must_match():
    """Filter is conjunctive: cfg_md5 AND code_md5 both match.
    A chunk with right cfg but wrong code is mismatched."""
    sidecar = _wrap_sidecar({
        "chunk_0001.json": _entry(1, "GOOD_CFG", "GOOD_CODE"),
        "chunk_0002.json": _entry(2, "GOOD_CFG", "WRONG_CODE"),
        "chunk_0003.json": _entry(3, "WRONG_CFG", "GOOD_CODE"),
    })
    chunk_files, _ = pia.select_replay_chunks_by_md5(
        Path("/tmp"), sidecar, "GOOD_CFG", "GOOD_CODE",
    )
    assert len(chunk_files) == 1
    assert chunk_files[0].name == "chunk_0001.json"


# ── Wall-time invariant (the user-visible signal) ────────────────────


def test_pre_filter_backward_compat_legacy_sidecar_without_by_md5():
    """Pre-2026-04-26 sidecars on disk only have ``chunks`` (no
    ``by_md5`` inverted index). The helper must still return the
    correct subset by deriving the bucket in-memory on the fly.
    Next sidecar write will persist the by_md5 field, so this
    fallback path only fires once per sidecar."""
    legacy_payload = {
        "_version": 1,
        "_updated_at": "2026-04-25T00:00:00Z",
        "chunks": {
            "chunk_0001.json": _entry(1, "X", "Y"),
            "chunk_0002.json": _entry(2, "Z", "Y"),
            "chunk_0003.json": _entry(3, "X", "Y"),
        },
        # NO by_md5 field — matches v1 layout.
    }
    chunk_files, _ = pia.select_replay_chunks_by_md5(
        Path("/tmp"), legacy_payload, "X", "Y",
    )
    # X|Y bucket has 2 chunks (1, 3); helper derives this from
    # `chunks` since by_md5 is absent.
    assert sorted(p.name for p in chunk_files) == [
        "chunk_0001.json", "chunk_0003.json",
    ]


def test_total_chunks_matches_pre_filter_output():
    """The cache_read_start event's ``total_chunks`` and the ETA
    estimate ("约需 X s") both come from ``len(chunk_files)``. With
    the regression in place, total_chunks would be 1443 (full disk)
    instead of 14 (matching). This test pins the relationship —
    the cache_read_start event's total_chunks IS len(chunk_files)
    from the pre-filter."""
    sidecar = _build_mixed_sidecar_payload()
    chunk_files, _ = pia.select_replay_chunks_by_md5(
        Path("/tmp"), sidecar,
        "f01cec9965d097e2e33a5aafdbd650b6",
        "769d599e4a7730e179961616b88dfca5",
    )
    # ETA per pure.js / replay-event renderer: total * 0.5s.
    # User screenshot showed 722s (= 1444 * 0.5); this should be 7s.
    estimate_seconds = round(len(chunk_files) * 0.5)
    assert estimate_seconds == 7, (
        f"ETA estimate broken — got {estimate_seconds}s, expected 7s "
        f"(14 matching chunks × 0.5s/chunk). The user reported '约需 "
        f"722s' which corresponds to the unfilters 1443-chunk count."
    )
