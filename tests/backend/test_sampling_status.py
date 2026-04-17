"""Tests for sampling-status recovery + bet-mismatch warning.

Context: user refreshed the page while a batch was running, then
clicked 开始采样 again. Because `state.activeBatchId` is in-memory, the
second click POSTed a new batch which hit the per-(machine, mode) lock
and failed with "another batch is sampling". UX fix:
 - backend exposes `/api/sampling-status` returning active_batches +
   busy_keys (from BatchRunManager._busy_keys)
 - frontend `_recoverActiveSampling` on boot adopts the batch_id so
   polling resumes and the start button stays hidden.
Also: if the cache's envelope `_bet` differs from the current run's
analyzer default, surface a warn event so the user knows RTP is
value-weighted across differently-priced sessions (CI math is still
valid on ret_x since it's dimensionless).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _seed_chunk_with_bet(root: Path, machine: str, mode: int, idx: int, bet: int):
    from fresh_slotlab.player_impact_analyzer import _save_chunk_cache
    mode_dir = root / machine / f"mode_{mode}"
    mode_dir.mkdir(parents=True, exist_ok=True)
    resp = [
        {"roundResult": json.dumps([
            {"BetAmount": bet, "WinCredits": bet * 0.9,
             "StopSymbolsByCol": "A|B|C|D|E", "SpinType": "Normal"}
        ])}
    ]
    _save_chunk_cache(resp, idx, machine, mode, bet, 1000, 10, mode_dir)


class TestSamplingStatusEndpoint:
    def test_empty_when_no_batch(self, client):
        c, _ = client
        r = c.get("/api/sampling-status")
        assert r.status_code == 200
        body = r.json()
        assert body["active_batches"] == []
        assert body["busy_keys"] == []

    def test_reports_busy_keys_from_manager(self, client, app_factory):
        c, app = client
        bm = app.state.batch_manager
        # Simulate a batch in flight by marking a key busy.
        assert bm._try_acquire_key("M50", 2) is True
        try:
            body = c.get("/api/sampling-status").json()
            assert {"machine": "M50", "mode": 2} in body["busy_keys"]
        finally:
            bm._release_key("M50", 2)

    def test_reports_active_batch_snapshot(self, client, app_factory):
        c, app = client
        bm = app.state.batch_manager
        # Fabricate a batch record in "running" status with one
        # running item — the endpoint should surface batch_id + totals.
        bm._batches["testbatch9"] = {
            "batch_id": "testbatch9",
            "status": "running",
            "items": [
                {"machine": "M1", "mode": 1, "status": "running"},
                {"machine": "M2", "mode": 1, "status": "pending"},
                {"machine": "M3", "mode": 1, "status": "completed"},
            ],
            "events": [],
            "concurrency": 1,
            "params": {},
            "reports_root": app_factory.reports_dir,
            "created_at": "2026-04-17T10:00:00Z",
            "cancel_requested": False,
        }
        try:
            body = c.get("/api/sampling-status").json()
            ab = [b for b in body["active_batches"] if b["batch_id"] == "testbatch9"]
            assert len(ab) == 1
            assert ab[0]["total"] == 3
            # Only running + pending count toward "running" in the
            # snapshot; completed is excluded.
            assert ab[0]["running"] == 2
        finally:
            bm._batches.pop("testbatch9", None)


class TestBetMismatchWarning:
    def test_cache_with_different_bet_warns(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """Cache was sampled at bet=2000, current default is 1000."""
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "dev_rawdata"
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))
        _seed_chunk_with_bet(raw_root, "M77", 1, 1, bet=2000)

        payload = {
            "items": [{"machine": "M77", "mode": 1, "chunk_spin_times": 1000}],
            "concurrency": 1, "chunk_spin_times": 1000,
            "chunk_robot_count": 20, "max_chunks": 5,
            "target_halfwidth_pp": 0.5, "batch_concurrency": 2,
            "timeout": 300, "auto_cleanup_cache": False,
        }
        r = c.post("/api/batch-run", json=payload)
        assert r.status_code == 200
        batch_id = r.json()["batch_id"]
        body = c.get(f"/api/batch-run/{batch_id}").json()
        events_text = " ".join(e["text"] for e in body["events"])
        assert "bet 不一致" in events_text, events_text
        assert "2000" in events_text  # cached bet value shown

    def test_cache_with_same_bet_no_warning(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """Cache at bet=1000 matches analyzer default — no warning."""
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "dev_rawdata"
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))
        _seed_chunk_with_bet(raw_root, "M78", 1, 1, bet=1000)

        payload = {
            "items": [{"machine": "M78", "mode": 1, "chunk_spin_times": 1000}],
            "concurrency": 1, "chunk_spin_times": 1000,
            "chunk_robot_count": 20, "max_chunks": 5,
            "target_halfwidth_pp": 0.5, "batch_concurrency": 2,
            "timeout": 300, "auto_cleanup_cache": False,
        }
        r = c.post("/api/batch-run", json=payload)
        assert r.status_code == 200
        batch_id = r.json()["batch_id"]
        body = c.get(f"/api/batch-run/{batch_id}").json()
        events_text = " ".join(e["text"] for e in body["events"])
        assert "bet 不一致" not in events_text

    def test_mixed_bets_across_chunks_warns(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """Cache with mixed bet values across chunks → warn regardless
        of current bet (sessions at different prices confuse RTP)."""
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "dev_rawdata"
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))
        _seed_chunk_with_bet(raw_root, "M79", 1, 1, bet=1000)
        _seed_chunk_with_bet(raw_root, "M79", 1, 2, bet=2000)

        payload = {
            "items": [{"machine": "M79", "mode": 1, "chunk_spin_times": 1000}],
            "concurrency": 1, "chunk_spin_times": 1000,
            "chunk_robot_count": 20, "max_chunks": 5,
            "target_halfwidth_pp": 0.5, "batch_concurrency": 2,
            "timeout": 300, "auto_cleanup_cache": False,
        }
        r = c.post("/api/batch-run", json=payload)
        body = c.get(f"/api/batch-run/{r.json()['batch_id']}").json()
        events_text = " ".join(e["text"] for e in body["events"])
        assert "bet 不一致" in events_text, events_text
