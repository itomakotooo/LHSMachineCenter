"""Regression: virtual_analyzer sim loop stops when CI target met.

2026-04-21 bug: the sim loop only honored ``stop_flag_file`` and
``max_chunks`` — the ``--target-halfwidth-pp`` from the UI's "目标 CI"
input was collected at argparse but never checked. A 5pp target would
still sample a full ``max_chunks=120`` worth of chunks before
delegating (or not stop at all on ``max_chunks=999``), forcing the
operator to cancel manually.

Fix: session-level CI accumulated across existing + newly-simulated
chunks (Welford-equivalent via running ret_sum / ret_sq_sum), checked
after every chunk, mirrors the real analyzer's ``session_halfwidth_pp``
formula. Three stop paths now:

  * ``target_ci_reached_from_cache`` — existing rawdata already meets
    target; sim loop is skipped entirely.
  * ``target_ci_reached`` — N new chunks sim'd, running CI crossed
    target, sim loop breaks.
  * ``max_chunks_reached`` / ``user_stop`` — unchanged; sim ran to
    the budget or was cancelled.

Tests:
  1. Small-N t-critical table matches the real analyzer's values.
  2. ``_ci_halfwidth_pp`` returns None for n ≤ 1.
  3. ``_session_returns_from_chunk_dict`` extracts one ret_x per
     robot from a chunk-shaped dict.
  4. ``_load_existing_session_stats`` accumulates across chunks and
     respects the md5 filter (historical chunks skipped).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.backend.virtual_analyzer import (
    _ci_halfwidth_pp,
    _load_existing_session_stats,
    _session_returns_from_chunk_dict,
    _t_critical_95,
)


def _make_robot(rounds: list[dict]) -> dict:
    """Build a robot dict in the real chunk's shape (roundResult is a
    JSON string containing a list of rounds with WinCredits / BetAmount)."""
    return {"roundResult": json.dumps(rounds, ensure_ascii=False)}


def _make_chunk(robots_win_bet: list[tuple[int, int]], *, config_md5: str = "", code_md5: str = "") -> dict:
    """Build a minimal chunk dict. Each ``(win_total, bet_total)`` tuple
    represents one robot whose rounds collectively sum to those totals
    (a single synthetic round suffices for session-ret_x math)."""
    return {
        "_config_md5": config_md5,
        "_code_md5": code_md5,
        "response": [
            _make_robot([{"WinCredits": win, "BetAmount": bet}])
            for win, bet in robots_win_bet
        ],
    }


def test_t_critical_matches_small_n_table():
    """Small-N t values should match the real analyzer's table. Large
    N falls back to 1.96 (same cutoff real analyzer uses)."""
    assert _t_critical_95(1) == 12.706
    assert _t_critical_95(10) == 2.228
    assert _t_critical_95(29) == 2.045
    assert _t_critical_95(30) == 2.042
    # Above table = normal approximation
    assert _t_critical_95(100) == 1.96
    assert _t_critical_95(500) == 1.96
    # Edge: df <= 0 returns the n=1 sentinel (guarded by n<=1 check
    # in _ci_halfwidth_pp, shouldn't be hit in practice).
    assert _t_critical_95(0) == 12.706


def test_ci_halfwidth_pp_undefined_for_n_le_1():
    assert _ci_halfwidth_pp(0, 0.0, 0.0) is None
    assert _ci_halfwidth_pp(1, 0.93, 0.86) is None


def test_ci_halfwidth_pp_zero_variance():
    """All sessions identical ret_x → variance 0 → CI half-width 0."""
    # 10 sessions all at ret_x = 0.95
    n = 10
    ret_sum = 0.95 * n
    ret_sq_sum = (0.95 ** 2) * n
    assert _ci_halfwidth_pp(n, ret_sum, ret_sq_sum) == 0.0


def test_ci_halfwidth_pp_matches_hand_computation():
    """Verify formula against a hand-worked example.

    5 sessions with ret_x values [0.90, 1.05, 0.85, 1.10, 0.95].
    Mean = 0.97, variance = (sum of sq deviations) / (n-1)
    = ((0.07²+0.08²+0.12²+0.13²+0.02²)) / 4
    = (0.0049+0.0064+0.0144+0.0169+0.0004)/4 = 0.043/4 = 0.01075
    se = sqrt(0.01075/5) = 0.04637
    t(df=4) = 2.776
    CI half-width = 2.776 * 0.04637 * 100 = 12.871
    """
    rx = [0.90, 1.05, 0.85, 1.10, 0.95]
    n = len(rx)
    ret_sum = sum(rx)
    ret_sq_sum = sum(x * x for x in rx)
    ci = _ci_halfwidth_pp(n, ret_sum, ret_sq_sum)
    assert ci is not None
    assert abs(ci - 12.871) < 0.01, f"expected ~12.87pp, got {ci}"


def test_session_returns_from_chunk_dict_extracts_per_robot():
    """One ret_x per robot: (1100, 1000), (900, 1000) → [1.10, 0.90]."""
    chunk = _make_chunk([(1100, 1000), (900, 1000)])
    rets = _session_returns_from_chunk_dict(chunk)
    assert rets == [1.10, 0.90]


def test_session_returns_skips_robots_with_zero_bet():
    """Bet == 0 = undefined ret_x, skipped to avoid div-by-zero."""
    chunk = _make_chunk([(500, 1000), (0, 0), (1200, 1000)])
    rets = _session_returns_from_chunk_dict(chunk)
    assert rets == [0.5, 1.2]


def test_session_returns_handles_list_roundResult():
    """When roundResult is a plain list (not JSON string) the extractor
    should still work — some test fixtures use list form directly."""
    chunk = {
        "response": [
            {"roundResult": [{"WinCredits": 2000, "BetAmount": 1000}]},
        ],
    }
    rets = _session_returns_from_chunk_dict(chunk)
    assert rets == [2.0]


def test_load_existing_session_stats_accumulates_across_chunks(tmp_path: Path):
    """Two on-disk chunks with 2 robots each → 4 sessions total."""
    for idx, robots in enumerate([
        [(1100, 1000), (900, 1000)],
        [(950, 1000), (1050, 1000)],
    ], start=1):
        chunk = _make_chunk(robots, config_md5="cfg1", code_md5="code1")
        (tmp_path / f"chunk_{idx:04d}.json").write_text(
            json.dumps(chunk), encoding="utf-8",
        )
    n, ret_sum, ret_sq, chunks_read, total = _load_existing_session_stats(
        tmp_path, md5_filter=None,
    )
    assert n == 4
    assert abs(ret_sum - (1.10 + 0.90 + 0.95 + 1.05)) < 1e-9
    # No filter → chunks_read == total_on_disk == 2.
    assert chunks_read == 2
    assert total == 2


def test_load_existing_session_stats_respects_md5_filter(tmp_path: Path):
    """With md5_filter set, chunks tagged with a different md5 pair
    are skipped — prevents historical-md5 chunks from polluting the
    CI estimate (matches real analyzer's filter semantics)."""
    # Two chunks with md5 "A", one chunk with md5 "B" (historical)
    (tmp_path / "chunk_0001.json").write_text(json.dumps(
        _make_chunk([(1100, 1000), (900, 1000)], config_md5="A", code_md5="A")
    ), encoding="utf-8")
    (tmp_path / "chunk_0002.json").write_text(json.dumps(
        _make_chunk([(950, 1000), (1050, 1000)], config_md5="A", code_md5="A")
    ), encoding="utf-8")
    (tmp_path / "chunk_0003.json").write_text(json.dumps(
        _make_chunk([(9999, 1000), (0, 1000)], config_md5="B", code_md5="B")
    ), encoding="utf-8")
    n_filtered, _, _, chunks_read_f, total_f = _load_existing_session_stats(
        tmp_path, md5_filter=("A", "A"),
    )
    n_unfiltered, _, _, chunks_read_u, total_u = _load_existing_session_stats(
        tmp_path, md5_filter=None,
    )
    assert n_filtered == 4, "only md5=A chunks counted (4 robots total)"
    assert n_unfiltered == 6, "no filter = all 6 robots counted"
    # NEW (2026-04-26): chunks_read reflects the matching subset
    # (2 of 3) when filter is active; total_on_disk reports full
    # disk count so events can show "skipped 1 of 3 historical-md5".
    assert chunks_read_f == 2, "filter active: only 2 matching md5=A chunks opened"
    assert total_f == 3, "total_on_disk always reports full glob count"
    assert chunks_read_u == 3, "no filter: all 3 chunks opened"
    assert total_u == 3


def test_load_existing_session_stats_empty_dir(tmp_path: Path):
    """Non-existent / empty dir returns (0, 0.0, 0.0, 0, 0) — the sim
    loop uses this as the 'no priors' starting state before adding
    freshly simulated chunks."""
    empty = tmp_path / "does_not_exist"
    n, s, sq, chunks_read, total = _load_existing_session_stats(
        empty, md5_filter=None,
    )
    assert (n, s, sq, chunks_read, total) == (0, 0.0, 0.0, 0, 0)


def test_load_existing_session_stats_pre_filter_no_match(tmp_path: Path):
    """REGRESSION 2026-04-26: user pulled fresh md5 → 0 cached chunks
    matching it → CI pre-check loop should iterate zero, not 422.
    Pre-fix the loop iterated all 422 disk chunks via inline skip,
    and the cache_read_done event reported chunks_read=422 +
    md5_skipped=0 (lying). New shape: chunks_read=0,
    total_on_disk=422 — caller can compute md5_skipped=422-0."""
    for idx in (1, 2, 3):
        (tmp_path / f"chunk_{idx:04d}.json").write_text(json.dumps(
            _make_chunk([(1100, 1000)], config_md5="OLD", code_md5="OLD")
        ), encoding="utf-8")
    n, _, _, chunks_read, total = _load_existing_session_stats(
        tmp_path, md5_filter=("FRESH_MD5", "FRESH_CODE"),
    )
    assert n == 0
    # The whole point: zero chunks opened, even though disk has 3.
    assert chunks_read == 0
    assert total == 3


if __name__ == "__main__":
    import inspect

    mod = sys.modules[__name__]
    tests = [obj for name, obj in inspect.getmembers(mod)
             if name.startswith("test_") and callable(obj)]
    import tempfile
    passed, failures = 0, []
    for t in tests:
        try:
            sig = inspect.signature(t)
            if "tmp_path" in sig.parameters:
                with tempfile.TemporaryDirectory() as d:
                    t(tmp_path=Path(d))
            else:
                t()
            print(f"ok  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failures.append((t.__name__, e))
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if not failures else 1)
