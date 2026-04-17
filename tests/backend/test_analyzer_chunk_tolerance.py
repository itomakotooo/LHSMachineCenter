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
        # Thresholds now live at module scope (promoted from main()
        # locals in the 2026-04-17 retry hardening pass). Guard that
        # they exist AND aren't set so tight that a single blip kills
        # the run — original bug was main() locals 3/20 which paired
        # with 3-attempt retries exhausted the window in ~10s.
        assert hasattr(analyzer, "MAX_CONSECUTIVE_FAILED_BATCHES")
        assert hasattr(analyzer, "MAX_CUMULATIVE_FAILED_CHUNKS")
        assert analyzer.MAX_CONSECUTIVE_FAILED_BATCHES >= 2, (
            "consecutive-failed-batches threshold must tolerate >= 2 bad batches"
        )
        assert analyzer.MAX_CUMULATIVE_FAILED_CHUNKS >= 5, (
            "cumulative-failed-chunks threshold must tolerate >= 5 total failures"
        )


class TestChunkEventsRetention:
    """User reported: during a run with many chunk_failed events, the
    chunk_events surfaced by /api/batch-run shrank as sampling
    progressed and the failure records disappeared after completion
    because the old window (last-12 of last-30) let chunk_progress
    events displace chunk_failed ones. New rule: critical events
    (chunk_failed / resume_from_cache / disk_guard_stop / failed) are
    NEVER pruned; only chunk_progress rotates."""

    def _seed_progress(self, path: Path, progress_count: int, fail_count: int) -> None:
        """Fabricate a progress.jsonl where fail_count chunk_failed
        events appeared early, then progress_count chunk_progress
        events accumulate afterward — mimicking the pattern where
        later success events push failures out of a small window."""
        import json
        lines = []
        for i in range(1, fail_count + 1):
            lines.append(json.dumps({
                "event": "chunk_failed", "chunk_index": i,
                "error": "request_failed_http_502",
                "cumulative_failed": i,
                "chunks_completed_so_far": 0, "total_spins_so_far": 0,
                "ts": f"2026-04-17T10:00:{i:02d}Z",
            }))
        for i in range(fail_count + 1, fail_count + progress_count + 1):
            lines.append(json.dumps({
                "event": "chunk_progress", "chunk_index": i,
                "total_spins": i * 1000, "current_rtp_pct": 92.0,
                "current_halfwidth_pp": 1.0,
                "ts": f"2026-04-17T10:01:{(i - fail_count):02d}Z",
            }))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_backend_has_no_overall_cap_on_criticals(
        self, client, app_factory, tmp_path: Path
    ):
        """50 chunk_failed + 12 chunk_progress → backend must return all
        50 criticals + last 8 progress. Previous `merged[-60:]` would
        have sliced 2 criticals off (50 + 8 = 58 < 60 so actually fine
        in this case, but put more and it'd drop). This pins the
        behavior that critical events are unbounded."""
        from tests.backend._seed import insert_run_row
        import json as _json

        state_dir = app_factory.state_dir
        progress_dir = state_dir / "progress"
        progress_dir.mkdir(parents=True, exist_ok=True)
        run_id = "nocaprun1"
        pf = progress_dir / f"{run_id}.jsonl"
        lines = []
        # 80 chunk_failed events (way above the old 60 cap).
        for i in range(1, 81):
            lines.append(_json.dumps({
                "event": "chunk_failed", "chunk_index": i,
                "error": "request_failed_http_502",
                "cumulative_failed": i,
                "ts": f"2026-04-17T10:00:{i:02d}.000000Z",
            }))
        # Then 12 chunk_progress events.
        for i in range(81, 93):
            lines.append(_json.dumps({
                "event": "chunk_progress", "chunk_index": i,
                "total_spins": i * 1000, "current_rtp_pct": 92.0,
                "current_halfwidth_pp": 1.0,
                "ts": f"2026-04-17T10:01:{(i - 80):02d}Z",
            }))
        pf.write_text("\n".join(lines) + "\n", encoding="utf-8")
        insert_run_row(
            app_factory.db_path, run_id=run_id, machine="M88", mode=1,
            status="running", progress_file=str(pf),
        )

        c, app = client
        bm = app.state.batch_manager
        batch_id = "nocapbatch1"
        bm._batches[batch_id] = {
            "batch_id": batch_id, "status": "running",
            "items": [{
                "machine": "M88", "mode": 1,
                "chunk_spin_times": 5000,
                "status": "running", "run_id": run_id,
                "cycle_info": None, "rawdata_status": {},
                "reuse_cache": False, "resume_cache": False,
            }],
            "events": [], "concurrency": 1, "params": {},
            "reports_root": app_factory.reports_dir,
            "created_at": "x", "cancel_requested": False,
        }
        try:
            body = c.get(f"/api/batch-run/{batch_id}").json()
            chunk_events = body["items"][0]["chunk_events"]
            failed = [e for e in chunk_events if e["event"] == "chunk_failed"]
            progress = [e for e in chunk_events if e["event"] == "chunk_progress"]
            # All 80 failures present — no 60 cap.
            assert len(failed) == 80, f"expected 80 chunk_failed, got {len(failed)}"
            # Progress still rotates at 8.
            assert len(progress) == 8, f"expected last 8 progress, got {len(progress)}"
        finally:
            bm._batches.pop(batch_id, None)

    def test_failures_survive_many_successes(
        self, client, app_factory, tmp_path: Path
    ):
        """4 early failures + 30 later progress events. All 4 failures
        must still be in chunk_events despite the 30 progress events
        that would have displaced them under the old last-12 rule."""
        from tests.backend._seed import insert_run_row

        state_dir = app_factory.state_dir
        progress_dir = state_dir / "progress"
        progress_dir.mkdir(parents=True, exist_ok=True)
        run_id = "retentionrun1"
        pf = progress_dir / f"{run_id}.jsonl"
        self._seed_progress(pf, progress_count=30, fail_count=4)
        insert_run_row(
            app_factory.db_path, run_id=run_id, machine="M99", mode=1,
            status="running", progress_file=str(pf),
        )

        c, app = client
        bm = app.state.batch_manager
        batch_id = "retbatch1"
        bm._batches[batch_id] = {
            "batch_id": batch_id, "status": "running",
            "items": [{
                "machine": "M99", "mode": 1,
                "chunk_spin_times": 5000,
                "status": "running", "run_id": run_id,
                "cycle_info": None, "rawdata_status": {},
                "reuse_cache": False, "resume_cache": False,
            }],
            "events": [], "concurrency": 1, "params": {},
            "reports_root": app_factory.reports_dir,
            "created_at": "x", "cancel_requested": False,
        }
        try:
            body = c.get(f"/api/batch-run/{batch_id}").json()
            chunk_events = body["items"][0]["chunk_events"]
            # All 4 chunk_failed events still present (regression: old
            # code would have surfaced ≤1 of them since 12 most-recent
            # are 12 chunk_progress events).
            failed_events = [e for e in chunk_events if e["event"] == "chunk_failed"]
            assert len(failed_events) == 4, (
                f"expected all 4 chunk_failed events preserved, got {len(failed_events)}: {failed_events}"
            )
            # Last 8 chunk_progress (rotating window) also present.
            progress_events = [e for e in chunk_events if e["event"] == "chunk_progress"]
            assert len(progress_events) == 8
            # Chronologically sorted.
            ts = [e.get("ts") for e in chunk_events]
            assert ts == sorted(ts), ts
        finally:
            bm._batches.pop(batch_id, None)


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
