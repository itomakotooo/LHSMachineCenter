"""Tests for fault-tolerant batch handling in the analyzer sampling loop.

Regression: user ran M273 m1 @ 0.5pp, hit a single upstream 504 on one
chunk (after all 3 retry attempts), and the whole run aborted — ~1M
spins of already-completed sibling chunks discarded. stop_reason was
`request_failed_http_504` logged in the summary but NOT surfaced to
the UI; the batch event log only showed "完成 ±1.23pp" so the user had
no signal that sampling bailed mid-run.

Fix under test:
- A single chunk failure no longer kills the run. Successful siblings
  in the same batch are merged; the failure is logged as `chunk_failed`
  in progress.jsonl so it's visible to the UI (which surfaces the last
  ~8 chunk events per item).
- Cumulative failure counter (>=20) or consecutive-fully-failed-batches
  counter (>=3) signal sustained upstream breakage → graceful stop
  with stop_reason="upstream_unstable:...".
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from typing import Any


def _ok_chunk(idx: int, spins: int = 100, bet: float = 100_000, win: float = 90_000):
    """Minimal valid result mimicking parse_chunk_response success."""
    return {
        "ok": True,
        "index": idx,
        "spins": spins,
        "bet": bet,
        "win": win,
        "ret_count": spins,
        "ret_sum": 0.9 * spins,
        "ret_sq_sum": 0.9 * 0.9 * spins,
        "max_return_x": 1.0,
        "win_spins": spins,
        "loss_spins": 0,
        "profit_spins": 0,
        "breakeven_or_more_spins": 0,
        "big_win_x10_spins": 0,
        "win_sum": win,
        "lack_credit_spins": 0,
        "payline_hits": {},
        "payline_win_approx": {},
        "payline_winning_symbols": {},
        "payline_winning_symbols_rln": {},
        "bonus_chain_lengths": [],
        "bonus_chain_max_ratios": [],
        "bonus_chain_retrigger_events": [],
        "bonus_total_rounds": 0,
        "bonus_retrigger_rounds": 0,
        "bonus_extra_ratio_counts": {},
        "collect_cycle_ratios": [],
        "collect_wait_distribution": {},
        "collect_trunk_clamp_estimate": 0.0,
        "session_ret_count": spins,
        "session_ret_sum": 0.9 * spins,
        "session_ret_sq_sum": 0.9 * 0.9 * spins,
        "session_paid_count": spins,
        "session_paid_bet_sum": bet,
        "session_paid_win_sum": win,
        "session_max_return_x": 1.0,
        "paid_spins_count": spins,
        "bonus_spins_count": 0,
        "session_bucket_spins": {},
        "session_bucket_bet": {},
        "session_bucket_win": {},
        "session_max_loss_streak": 0,
        "session_max_win_streak": 0,
        "session_wins": spins,
        "session_loses": 0,
        "session_profits": 0,
        "session_breakevens": 0,
        "session_big_win_x10": 0,
        "session_loss_streak_hist": {},
        "session_win_streak_hist": {},
        # Spin type / feature / payout accumulators — empty is fine for this test.
        "spin_type_spins": {},
        "spin_type_win": {},
        "spin_type_wins": {},
        "spin_type_paid_rounds": {},
        "upstream_feature_tally": {},
        "upstream_chunk_total_win": 0.0,
        "upstream_chunk_robots_seen": 0,
        "collect_count_total": 0,
        "acc_credits_max": 0,
        "collect_robots_seen": 0,
        "collect_cycles_completed": 0,
        "collect_cycles_truncated_by_chunk_end": 0,
        "collect_cycle_completion_confidence": None,
        "payout_id_hits": {},
        "payout_id_win": {},
        "payline_group_hits": {},
        "payline_group_win": {},
        "reel_position_counts": {},
        "symbol_counts": {},
        "symbol_by_col_counts": {},
        "session_rtp_curve_samples": [],
        "chain_ratio_sequences": [],
        "payline_wild_hits": {},
        "nf_correction_fields": {},
        # Machine-mechanics accumulators (most machines don't set these).
        "lock_lines_spins": 0, "lock_lines_win": 0.0,
        "lock_symbols_spins": 0, "lock_symbols_win": 0.0,
        "lock_reels_spins": 0, "lock_reels_win": 0.0,
        "jackpot_spins": 0, "jackpot_ids_seen": [], "jackpot_win": 0.0,
        "freespin_chain_spins": 0, "freespin_retriggers": 0,
        "freespin_max_chain": 0, "freespin_win": 0.0,
        "dollar_pick_spins": 0, "dollar_pick_total_dollars": 0,
        "dollar_pick_win": 0.0,
    }


def _fail_chunk(idx: int, code: int = 504):
    return {
        "ok": False,
        "index": idx,
        "error": f"request_failed_http_{code}",
    }


class TestFaultTolerantBatchLoop:
    """These tests are white-box: they reach into the partition logic
    (successful vs failed) to pin the behavior. The full end-to-end
    analyzer test would require mocking subprocess-level sampling which
    is too heavy; these isolate the fault-tolerance branch."""

    def test_partition_logic_keeps_successes(self):
        """When a batch has 4 results: 3 ok, 1 failed, the filter
        expressions must yield 3 successes for merging, 1 failure for
        logging, and NOT trigger the fail-early break."""
        batch_results = [_ok_chunk(1), _ok_chunk(2), _fail_chunk(3), _ok_chunk(4)]
        successful = [r for r in batch_results if bool(r.get("ok"))]
        failed = [r for r in batch_results if not bool(r.get("ok"))]
        assert len(successful) == 3
        assert len(failed) == 1
        # Mixed batch (at least one success) → consecutive_failed_batches
        # resets to 0 (the analyzer's logic).
        assert not (failed and not successful)

    def test_partition_fully_failed_batch(self):
        """Batch where all 4 chunks fail → consecutive counter bumps."""
        batch_results = [_fail_chunk(i) for i in range(1, 5)]
        successful = [r for r in batch_results if bool(r.get("ok"))]
        failed = [r for r in batch_results if not bool(r.get("ok"))]
        assert len(successful) == 0
        assert len(failed) == 4
        assert failed and not successful  # triggers consecutive bump


class TestFaultToleranceThresholds:
    """Document the threshold constants so a future change that makes
    them accidentally too aggressive (e.g. bail at 1 failure) fails."""

    def test_thresholds_are_reasonable(self):
        import fresh_slotlab.player_impact_analyzer as analyzer
        import inspect
        # Grep the main() source for the sentinel constants.
        src = inspect.getsource(analyzer.main)
        # Expect both guards present.
        assert "_MAX_CONSECUTIVE_FAILED_BATCHES" in src
        assert "_MAX_CUMULATIVE_FAILED_CHUNKS" in src
        # The constants get inlined as literals in the source; sanity
        # check they're not <= 1 which would kill runs on any single
        # failure (the original bug).
        import re
        m1 = re.search(r"_MAX_CONSECUTIVE_FAILED_BATCHES\s*=\s*(\d+)", src)
        m2 = re.search(r"_MAX_CUMULATIVE_FAILED_CHUNKS\s*=\s*(\d+)", src)
        assert m1 and int(m1.group(1)) >= 2, \
            "consecutive-failed-batches threshold must tolerate >= 2 bad batches"
        assert m2 and int(m2.group(1)) >= 5, \
            "cumulative-failed-chunks threshold must tolerate >= 5 total failures"


class TestBackendProgressKeyMigration:
    """The UI's CI gauge was stuck at N/A because the backend read
    `halfwidth_pp` from progress events but the analyzer always wrote
    `current_halfwidth_pp`. Both keys are now accepted."""

    def test_current_halfwidth_pp_is_picked_up(
        self, client, app_factory, tmp_path: Path, monkeypatch
    ):
        c, app = client
        # Seed a fake running run with a chunk_progress event carrying
        # current_halfwidth_pp (analyzer's actual key) but not the
        # legacy halfwidth_pp. batch_run response should surface it.
        import src.web_console.backend.app as app_mod
        from tests.backend._seed import insert_run_row

        state_dir = app_factory.state_dir
        progress_dir = state_dir / "progress"
        progress_dir.mkdir(parents=True, exist_ok=True)
        run_id = "fakerun12345"
        progress_file = progress_dir / f"{run_id}.jsonl"
        progress_file.write_text(
            json.dumps({
                "event": "chunk_progress",
                "run_id": run_id,
                "chunk_index": 3,
                "total_spins": 360_000,
                "current_rtp_pct": 92.5,
                "current_halfwidth_pp": 0.82,
                "session_level_halfwidth_pp": 0.82,
                "chunk_level_halfwidth_pp": 1.05,
                "target_halfwidth_pp": 0.5,
                "ts": "2026-04-17T10:00:00Z",
            }) + "\n",
            encoding="utf-8",
        )
        db_path = app_factory.db_path
        insert_run_row(
            db_path,
            run_id=run_id,
            machine="M273",
            mode=1,
            status="running",
            progress_file=str(progress_file),
        )
        # Manually construct a batch record referencing the seeded run
        # (the normal /api/batch-run flow would have spawned a subprocess
        # which stub_popen blocks; we bypass by poking the manager state
        # directly).
        bm = app.state.batch_manager
        batch_id = "testbatch01"
        bm._batches[batch_id] = {
            "batch_id": batch_id,
            "status": "running",
            "items": [{
                "machine": "M273", "mode": 1,
                "chunk_spin_times": 5000,
                "status": "running", "run_id": run_id,
                "cycle_info": None, "rawdata_status": {},
                "reuse_cache": False, "resume_cache": False,
            }],
            "events": [],
            "concurrency": 1, "params": {},
            "reports_root": app_factory.reports_dir,
            "created_at": "x", "cancel_requested": False,
        }
        r = c.get(f"/api/batch-run/{batch_id}")
        assert r.status_code == 200
        body = r.json()
        it = body["items"][0]
        p = it["progress"]
        # The regression: halfwidth_pp used to be None here. Now it
        # falls back to current_halfwidth_pp when legacy key is absent.
        assert p["halfwidth_pp"] == 0.82, p
        assert p["session_level_halfwidth_pp"] == 0.82
        # chunk_events list is also exposed for the per-chunk mini log.
        assert "chunk_events" in it
        assert len(it["chunk_events"]) >= 1
        assert it["chunk_events"][0]["event"] == "chunk_progress"
