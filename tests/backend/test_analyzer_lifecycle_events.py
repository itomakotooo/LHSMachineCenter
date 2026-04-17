"""Analyzer lifecycle events (Layer 3 of the sampling-log refactor).

Background: before 2026-04-17, the batch-sampling UI had a ~30-60s
black hole between the backend's "开始 API 采样" log line and the
first chunk_progress event. During that window the analyzer was
booting Python, parsing args, opening the output dir, and making its
first HTTP call — but the UI showed nothing. Users perceived the app
as stuck.

Fix: analyzer now emits two new progress events that the UI renders
as concrete timeline rows:

  * ``analyzer_started`` — once, right after argparse validation.
    Carries ``pid`` so the operator can correlate with system
    monitors. Rendered as ``⚙ analyzer 就绪 · pid=N``.
  * ``fetching_chunk`` — once, right before the first live batch
    submit. Rendered as ``⇅ 请求 chunk N…``. Only the first batch
    gets this (subsequent batches' chunk_progress events already
    provide a steady heartbeat).

These tests drive the real analyzer main() against a fixture response
and assert on the progress.jsonl event order. Catches any future
regression where someone moves argparse around, restructures the
sampling loop, or accidentally drops the first_fetch_emitted flag.
"""
from __future__ import annotations

import json
import sys
import tempfile
from io import StringIO
from pathlib import Path

import pytest


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "m14_mode1_r8_s50.json"
)


@pytest.fixture
def progress_events(monkeypatch):
    """Run analyzer.main() against M14 fixture; return the parsed
    progress.jsonl events so tests can inspect lifecycle ordering."""
    fixture_data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        "fresh_slotlab.player_impact_analyzer.post_json",
        lambda payload, timeout: fixture_data,
    )
    # main() calls os._exit(rc) at the end to kill stuck worker
    # threads; the fixture stub keeps tests alive.
    monkeypatch.setattr("os._exit", lambda rc: None)

    with tempfile.TemporaryDirectory() as tmpdir:
        outdir = Path(tmpdir) / "output"
        outdir.mkdir()
        progress_path = Path(tmpdir) / "p.jsonl"
        test_argv = [
            "analyzer",
            "--machine", "M14",
            "--rtp-mode", "1",
            "--bet", "1000",
            "--chunk-spin-times", "50",
            "--chunk-robot-count", "8",
            "--batch-concurrency", "1",
            "--max-chunks", "1",
            "--target-halfwidth-pp", "999",
            "--timeout", "30",
            "--output-dir", str(outdir),
            "--progress-file", str(progress_path),
            "--run-id", "m14_lifecycle",
            "--bankruptcy-session-spins", "100",
            "--bankruptcy-bankroll-multipliers", "100,200,500",
        ]
        monkeypatch.setattr(sys, "argv", test_argv)
        monkeypatch.setattr(sys, "stdout", StringIO())
        from fresh_slotlab.player_impact_analyzer import main
        rc = main()
        assert rc == 0, "analyzer main() must succeed on fixture data"
        # Parse events BEFORE the TemporaryDirectory goes out of scope.
        events: list[dict] = []
        for line in progress_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events


def test_analyzer_started_event_emitted(progress_events):
    """Exactly one analyzer_started event must fire after argparse."""
    starts = [e for e in progress_events if e.get("event") == "analyzer_started"]
    assert len(starts) == 1, (
        f"expected exactly 1 analyzer_started event; saw {len(starts)}: {starts!r}"
    )


def test_analyzer_started_carries_pid_and_machine(progress_events):
    """Event payload must expose pid (for system correlation) +
    machine/mode (for multi-machine batches)."""
    ev = next(e for e in progress_events if e.get("event") == "analyzer_started")
    assert isinstance(ev.get("pid"), int) and ev["pid"] > 0, (
        f"analyzer_started.pid must be a positive int; got {ev.get('pid')!r}"
    )
    assert ev.get("machine") == "M14"
    assert ev.get("mode") == 1
    assert ev.get("ts"), "analyzer_started must carry a timestamp"


def test_fetching_chunk_event_emitted_once(progress_events):
    """fetching_chunk fires exactly once — for the FIRST live batch.
    Subsequent batches rely on chunk_progress for their heartbeat; if
    fetching_chunk spammed per batch the log would drown out criticals
    on a 100-chunk run."""
    fetches = [e for e in progress_events if e.get("event") == "fetching_chunk"]
    assert len(fetches) == 1, (
        f"expected exactly 1 fetching_chunk event; saw {len(fetches)}: {fetches!r}"
    )


def test_lifecycle_ordering(progress_events):
    """Event order must be: started → analyzer_started →
    fetching_chunk → chunk_progress. Anything else suggests a
    restructure of main() has broken the observability narrative."""
    kinds = [e.get("event") for e in progress_events]
    idx_started = kinds.index("started")
    idx_analyzer = kinds.index("analyzer_started")
    idx_fetching = kinds.index("fetching_chunk")
    idx_progress = kinds.index("chunk_progress")
    assert idx_started < idx_analyzer < idx_fetching < idx_progress, (
        f"lifecycle events out of order: {kinds!r}"
    )


def test_fetching_chunk_carries_indices(progress_events):
    """Event must carry chunk_index + batch_size so the UI can show
    '⇅ 请求 chunk 10…' rather than a bare '⇅ 请求 chunk ?…'."""
    ev = next(e for e in progress_events if e.get("event") == "fetching_chunk")
    assert isinstance(ev.get("chunk_index"), int) and ev["chunk_index"] >= 1
    assert isinstance(ev.get("batch_size"), int) and ev["batch_size"] >= 1
