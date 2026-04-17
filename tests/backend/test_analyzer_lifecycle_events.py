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


def test_chunk_progress_emits_session_rtp_pct(progress_events):
    """chunk_progress events must now carry session_rtp_pct alongside
    current_rtp_pct. The final summary's rtp.point_pct uses
    session_bet_sum as the denominator (paid sessions only); the live
    current_rtp_pct used total_bet (includes bonus BetAmount) which
    under-reports RTP on collect-mechanic machines by 30-50%. User
    reported chunk log showed RTP=83% but final report showed 92%+
    on M273 (a collect-mechanic machine). Adding session_rtp_pct to
    the event keeps the live display semantically aligned with the
    final report."""
    progress = [e for e in progress_events if e.get("event") == "chunk_progress"]
    assert progress, "no chunk_progress events found on fixture run"
    for ev in progress:
        assert "session_rtp_pct" in ev, (
            f"chunk_progress must carry session_rtp_pct (paid-session "
            f"denominator RTP); event keys: {sorted(ev.keys())!r}"
        )
    # For M14 (no bonus rounds, all paid sessions), session_rtp and
    # current_rtp should match within rounding. If they diverge on M14
    # something's wrong in the session-accounting.
    ev = progress[-1]
    if ev.get("current_rtp_pct") is not None and ev.get("session_rtp_pct") is not None:
        delta = abs(ev["current_rtp_pct"] - ev["session_rtp_pct"])
        assert delta < 0.5, (
            f"on M14 (no bonus), session_rtp {ev['session_rtp_pct']} and "
            f"current_rtp {ev['current_rtp_pct']} must agree within 0.5pp; "
            f"delta={delta}"
        )


def test_chunk_started_emitted_per_submitted_chunk(progress_events):
    """Every submitted chunk must produce a chunk_started event —
    feeds the UI's in-flight section so the operator sees each chunk
    as it's dispatched. Previously the user saw nothing until the
    whole batch returned (30-90s of silence for a slow chunk)."""
    started = [e for e in progress_events if e.get("event") == "chunk_started"]
    submitted_indices = sorted(e.get("chunk_index") for e in started)
    # On M14 fixture (max_chunks=1, batch_concurrency=1) we submit
    # exactly one chunk.
    assert started, "expected at least one chunk_started event"
    assert submitted_indices == [1], (
        f"expected chunk_started for index 1, got {submitted_indices!r}"
    )
    for ev in started:
        assert ev.get("ts"), "chunk_started must carry a timestamp"
        assert isinstance(ev.get("chunk_index"), int)


def test_chunk_progress_chunk_index_matches_submit_index(progress_events):
    """chunk_progress.chunk_index must use the actual submitted index
    (rec['index']) rather than the running `chunks` counter. The UI's
    in-flight section pairs chunk_started (submit-index) with
    chunk_progress by chunk_index — if they mismatch, an in-flight
    chunk would never be retired from the section."""
    started = {e["chunk_index"] for e in progress_events
               if e.get("event") == "chunk_started"}
    completed = {e["chunk_index"] for e in progress_events
                 if e.get("event") == "chunk_progress"}
    # Every completed chunk (on this fixture: just chunk 1) must
    # match a chunk_started index.
    assert completed.issubset(started), (
        f"chunk_progress indices {completed!r} must be a subset of "
        f"chunk_started indices {started!r} — else the UI's in-flight "
        f"pairing breaks"
    )


def test_chunk_started_ordering_precedes_progress(progress_events):
    """chunk_started for a given chunk_index must appear before any
    chunk_progress/chunk_failed for the same index. Otherwise the UI
    briefly shows an in-flight row for an already-complete chunk."""
    seen_started = set()
    for ev in progress_events:
        kind = ev.get("event")
        idx = ev.get("chunk_index")
        if idx is None:
            continue
        if kind == "chunk_started":
            seen_started.add(idx)
        elif kind in ("chunk_progress", "chunk_failed"):
            assert idx in seen_started, (
                f"chunk {idx} emitted {kind} before chunk_started — "
                f"this breaks the UI's in-flight pairing"
            )
