"""Tests for overnight-run robustness hardening (2026-04-17 session).

Three fixes:
1. Analyzer's live sampling loop now retries transient upstream failures
   (5xx / URLError / TimeoutError) via `post_json_with_retry`, so one
   blip doesn't abort a 3M-spin run. `run_sampling_chunk` calls the
   retry helper instead of raw `post_json`.
2. Mid-run disk guard inside the analyzer while loop. Free space <
   2 GB on the output dir's filesystem → graceful stop with partial
   summary + stop_reason="disk_low_X.XXGB" (so caller can distinguish
   from regular target_ci_reached / max_chunks).
3. BatchRunManager now holds a per-(machine, mode) busy set. A second
   batch-run that includes a key currently sampling gets the item
   failed with error "another batch is sampling this machine+mode" —
   no chunk-dir race.
"""

from __future__ import annotations

import json
import socket
import urllib.error
from pathlib import Path
from typing import Any

import pytest


class TestAnalyzerChunkRetry:
    """`run_sampling_chunk` now wraps `post_json` in exp-backoff retry.
    First 5xx used to abort the whole machine; now it retries."""

    def test_run_sampling_chunk_retries_on_502_then_succeeds(self, monkeypatch):
        import fresh_slotlab.player_impact_analyzer as analyzer
        attempts = {"n": 0}

        def fake_post(payload, timeout):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise urllib.error.HTTPError(
                    url="x", code=502, msg="transient", hdrs=None, fp=None,
                )
            # Return an empty robots list (valid shape; analyzer will
            # produce an empty-chunk result but marks ok=False because
            # parse_failed_empty_response — that's fine, we're only
            # testing the retry path here).
            return []

        monkeypatch.setattr(analyzer, "post_json", fake_post)
        monkeypatch.setattr(analyzer.time, "sleep", lambda _s: None)

        result = analyzer.run_sampling_chunk(
            chunk_index=1, machine="M1", rtp_mode=1, bet=1000,
            spin_times=10, robot_count=1, timeout=1.0,
        )
        # First 502 was retried; second attempt returned []. Retry
        # succeeded (post_json_with_retry didn't raise), even if
        # parse_chunk_response then flags empty response downstream.
        assert attempts["n"] == 2
        # Result is the analyzer's normal empty-response failure,
        # NOT a request_failed_http_502 — that proves the retry
        # layer swallowed the 502.
        assert result.get("ok") is False
        assert "request_failed_http" not in str(result.get("error", ""))

    def test_non_retryable_404_fails_fast(self, monkeypatch):
        import fresh_slotlab.player_impact_analyzer as analyzer
        attempts = {"n": 0}

        def fake_post(payload, timeout):
            attempts["n"] += 1
            raise urllib.error.HTTPError(
                url="x", code=404, msg="not found", hdrs=None, fp=None,
            )

        monkeypatch.setattr(analyzer, "post_json", fake_post)
        monkeypatch.setattr(analyzer.time, "sleep", lambda _s: None)
        result = analyzer.run_sampling_chunk(
            chunk_index=1, machine="M1", rtp_mode=1, bet=1000,
            spin_times=10, robot_count=1, timeout=1.0,
        )
        assert attempts["n"] == 1  # no retry
        assert result.get("ok") is False
        assert "request_failed_http_404" in str(result.get("error", ""))


class TestBatchRunManagerPerKeyLock:
    """Two concurrent batches with overlapping (machine, mode) keys must
    not both run analyzer in the same chunk_cache_dir."""

    def test_second_batch_same_key_is_rejected(self, client, app_factory, tmp_path):
        import src.web_console.backend.app as app_mod
        c, app = client

        # Reach into the batch manager and manually acquire a key,
        # simulating an in-flight batch. Then trigger a new batch
        # request for the same key — its _run_one must see the key
        # busy and short-circuit the item with "failed" + the
        # specific error message.
        bm = app.state.batch_manager  # type: ignore[attr-defined]
        assert bm._try_acquire_key("M99", 1) is True
        try:
            r = c.post("/api/batch-run", json={
                "items": [{"machine": "M99", "mode": 1, "chunk_spin_times": 1000}],
                "concurrency": 1,
                "chunk_spin_times": 1000,
                "chunk_robot_count": 20,
                "max_chunks": 1,
                "target_halfwidth_pp": 0.0,
                "batch_concurrency": 1,
                "timeout": 300,
                "auto_cleanup_cache": False,
            })
            assert r.status_code == 200
            batch_id = r.json()["batch_id"]
            # The item thread runs asynchronously; poll a few times.
            import time
            deadline = time.time() + 5
            while time.time() < deadline:
                b = c.get(f"/api/batch-run/{batch_id}").json()
                if b["items"][0]["status"] in ("failed", "completed", "cancelled"):
                    break
                time.sleep(0.1)
            b = c.get(f"/api/batch-run/{batch_id}").json()
            it = b["items"][0]
            assert it["status"] == "failed"
            assert "another batch is sampling" in (it.get("error") or "").lower()
        finally:
            bm._release_key("M99", 1)

    def test_lock_releases_on_completion(self, app_factory):
        """After an item finishes (or fails), the per-key lock must be
        released so subsequent batches can take it."""
        import src.web_console.backend.app as app_mod
        # Build a fresh app, grab its batch manager, poke the lock API
        # directly.
        app = app_factory()
        bm = app.state.batch_manager  # type: ignore[attr-defined]
        assert bm._try_acquire_key("MX", 2) is True
        assert bm._try_acquire_key("MX", 2) is False  # already held
        bm._release_key("MX", 2)
        assert bm._try_acquire_key("MX", 2) is True  # free again
        bm._release_key("MX", 2)

    def test_lock_is_per_key_not_global(self, app_factory):
        """Different (machine, mode) keys must not block each other."""
        app = app_factory()
        bm = app.state.batch_manager  # type: ignore[attr-defined]
        assert bm._try_acquire_key("MA", 1) is True
        assert bm._try_acquire_key("MA", 2) is True  # different mode
        assert bm._try_acquire_key("MB", 1) is True  # different machine
        bm._release_key("MA", 1)
        bm._release_key("MA", 2)
        bm._release_key("MB", 1)


class TestSharedRetryHelper:
    """post_json_with_retry is shared between analyzer's live loop and
    batch_dev_sampler. Both modules must expose it at import time."""

    def test_analyzer_exports_post_json_with_retry(self):
        import fresh_slotlab.player_impact_analyzer as analyzer
        assert callable(analyzer.post_json_with_retry)

    def test_sampler_aliases_shared_helper(self):
        import fresh_slotlab.batch_dev_sampler as sampler
        import fresh_slotlab.player_impact_analyzer as analyzer
        # _post_json_with_retry in sampler is literally the analyzer's
        # function — same object, not a wrapper.
        assert sampler._post_json_with_retry is analyzer.post_json_with_retry
