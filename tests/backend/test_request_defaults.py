"""Default values on the sampling request models (2026-05-22 tune).

Two operator-facing defaults were adjusted after the deployed-server
loopback measurement:

  * ``chunk_spin_times``: 5000 → 10000 (floor lift per operator request
    for cleaner per-chunk RTP variance).
  * ``timeout``: 300.0 → 60.0 (loopback p95 chunk wall ~10s, so 60s
    is 6× safety; was sized for public-internet retries).

This file pins those values so a casual refactor cannot silently
revert. Each test has an explicit inject-bug recipe so future devs
can verify the protection.

Other defaults (chunk_robot_count=8, batch_concurrency=8, max_chunks
=120, target_halfwidth_pp=0.5) stay tuned for the WAN-prod regime —
callers can override per-request and the loopback-deployed console
already uses _LOOPBACK_HARDCODED_TUNING for the robot/conc pair.
"""
from __future__ import annotations

import pytest

from src.web_console.backend.app import BatchRunItem, BatchRunRequest, RunCreateRequest


class TestRunCreateRequestDefaults:
    def test_chunk_spin_times_default_is_10000(self):
        """Inject-bug: revert to 5000 → test fails. Catches the easy
        accidental rollback during a merge that didn't see the
        2026-05-22 docstring justification."""
        req = RunCreateRequest(machine="M14", mode=1)
        assert req.chunk_spin_times == 10000, (
            "operator requested 2026-05-22: chunk_spin_times floor "
            ">= 10000 for cleaner per-chunk RTP variance. If you "
            "lower this, also update the frontend per-machine "
            "category branch in app.js startBatchRun()."
        )

    def test_timeout_default_is_60s(self):
        """Inject-bug: revert to 300 → test fails. Catches the
        accidental rollback to the public-internet default."""
        req = RunCreateRequest(machine="M14", mode=1)
        assert req.timeout == 60.0, (
            "2026-05-22 loopback measurement: chunk p95 wall ~10s, "
            "60s gives 6× safety. Reverting to 300s buries operator "
            "failure signals under a 5-minute hang."
        )

    def test_explicit_override_still_honored(self):
        """Defaults only fill when the caller omits; explicit smaller
        values for tests / fixtures continue to work.

        Inject-bug: change Field(gt=0) to Field(ge=10000) → the
        chunk_spin_times=1000 override raises a ValidationError →
        existing integration tests that intentionally pass small
        values break."""
        req = RunCreateRequest(
            machine="M14", mode=1,
            chunk_spin_times=1000, timeout=10.0,
        )
        assert req.chunk_spin_times == 1000
        assert req.timeout == 10.0


class TestBatchRunRequestDefaults:
    def test_chunk_spin_times_default_aligned_with_run_create(self):
        """BatchRunRequest must agree with RunCreateRequest — they
        flow to the same analyzer subprocess; divergent defaults
        cause batch vs single-run drift."""
        breq = BatchRunRequest(items=[BatchRunItem(machine="M14", mode=1)])
        rreq = RunCreateRequest(machine="M14", mode=1)
        assert breq.chunk_spin_times == rreq.chunk_spin_times
        assert breq.chunk_spin_times == 10000

    def test_timeout_default_aligned_with_run_create(self):
        breq = BatchRunRequest(items=[BatchRunItem(machine="M14", mode=1)])
        rreq = RunCreateRequest(machine="M14", mode=1)
        assert breq.timeout == rreq.timeout
        assert breq.timeout == 60.0

    def test_explicit_override_still_honored(self):
        breq = BatchRunRequest(
            items=[BatchRunItem(machine="M14", mode=1)],
            chunk_spin_times=2000, timeout=15.0,
        )
        assert breq.chunk_spin_times == 2000
        assert breq.timeout == 15.0
