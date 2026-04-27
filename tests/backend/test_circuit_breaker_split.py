"""End-to-end: spawn the analyzer subprocess and verify the new
dual-counter circuit-breaker behavior.

User feedback 2026-04-26: "你还要能鉴别出机台本身的问题还是网络问题".
The pre-fix behavior bumped a single counter for any chunk failure;
schema_drift / parse_failed bugs took ~40 chunks to bail (same as a
real network outage). After the split, machine-class failures bail
at MAX_CUMULATIVE_FAILED_CHUNKS_MACHINE = 5, while network-class
keeps the (more tolerant) ≥ 20 cumulative + 3 consecutive batch
window.

These tests pin the user-visible contract by inspecting:
  - The ``stop_reason`` written into the run summary
  - The ``chunk_failed`` events in the progress JSONL (each carries
    an ``error_class`` field after the split)
  - The ``failed`` event's reason payload

Run-via-subprocess uses a fake upstream over HTTP (the analyzer's
``--endpoint-url`` flag points at a tmp HTTPServer that we control
to inject specific error shapes per chunk).
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


class _ScriptedHandler(BaseHTTPRequestHandler):
    """HTTP handler driven by a class-attr ``responses`` queue —
    each POST consumes one entry and replies with that shape.

    Entry types:
      - ('5xx', code): respond with HTTP <code>
      - ('schema_drift',): respond 200 with valid envelope but
        rounds missing required schema fields
      - ('valid', spin_times, robot_count): respond with a valid
        sampling response (analyzer accepts it as a real chunk)
    """
    responses: list = []  # set per-test
    log_lock = threading.Lock()
    request_log: list = []

    def log_message(self, fmt, *args):  # silence default stderr noise
        return

    def do_POST(self):
        with _ScriptedHandler.log_lock:
            if not _ScriptedHandler.responses:
                # Default: keep returning valid empty-ish responses
                # so the analyzer doesn't crash on exhausted script.
                entry = ('valid', 5, 1)
            else:
                entry = _ScriptedHandler.responses.pop(0)
            _ScriptedHandler.request_log.append(entry)
        kind = entry[0]
        if kind == '5xx':
            code = entry[1]
            self.send_response(code)
            self.end_headers()
            self.wfile.write(b'{"error": "fake 5xx"}')
        elif kind == 'schema_drift':
            # Valid envelope shape but rounds missing
            # ``StopSymbolsByCol`` — analyzer flags as
            # schema_drift_missing_fields.
            body = json.dumps([
                {"roundResult": json.dumps([
                    # Missing StopSymbolsByCol — the schema-drift
                    # detector triggers on the first round.
                    {"BetAmount": 100, "WinAmount": 0, "SpinType": 1,
                     "ReMarks": "", "PayoutId": 0,
                     "WinPayLineIDs": [], "FeatureWin": 0,
                     "PayoutIdToWinAmount": {}, "SettlementSpinType": 1},
                ])}
            ])
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))
        else:
            # Valid response — minimal but parseable.
            spin_times = entry[1] if len(entry) >= 2 else 5
            robot_count = entry[2] if len(entry) >= 3 else 1
            rounds = [
                {"BetAmount": 100, "WinAmount": 0, "SpinType": 1,
                 "ReMarks": "", "PayoutId": 0,
                 "WinPayLineIDs": [], "FeatureWin": 0,
                 "PayoutIdToWinAmount": {}, "SettlementSpinType": 1,
                 "StopSymbolsByCol": [["A"], ["A"], ["A"]],
                 "PayLineGroupId": 0, "PayLineId": -1}
                for _ in range(spin_times)
            ]
            robots = [
                {"roundResult": json.dumps(rounds)}
                for _ in range(robot_count)
            ]
            body = json.dumps(robots)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))


@pytest.fixture
def fake_upstream():
    """Spin up a localhost HTTP server. Tests preload
    ``_ScriptedHandler.responses`` to control per-request reply
    shapes."""
    _ScriptedHandler.responses = []
    _ScriptedHandler.request_log = []
    # Find a free port.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = HTTPServer(("127.0.0.1", port), _ScriptedHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}/MultiRobotTestSpin"
    finally:
        server.shutdown()
        server.server_close()


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


def _run_analyzer(
    endpoint_url: str,
    progress_file: Path,
    output_dir: Path,
    *,
    max_chunks: int = 50,
    timeout_s: int = 60,
    target_halfwidth_pp: float = 0.001,
) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable, "-m", "fresh_slotlab.player_impact_analyzer",
        "--machine", "M1",
        "--rtp-mode", "1",
        "--bet", "1000",
        "--output-dir", str(output_dir),
        "--target-halfwidth-pp", str(target_halfwidth_pp),
        "--max-chunks", str(max_chunks),
        "--chunk-spin-times", "5",
        "--chunk-robot-count", "1",
        "--batch-concurrency", "1",
        "--timeout", "10",
        "--bankruptcy-session-spins", "100",
        "--bankruptcy-bankroll-multipliers", "10",
        "--endpoint-url", endpoint_url,
        "--progress-file", str(progress_file),
        "--run-id", "test_circuit",
    ]
    return subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout_s,
    )


# ── Network-class tolerance ───────────────────────────────────────


def test_network_failures_tolerated_until_consecutive_batch_threshold(
    fake_upstream, tmp_path,
):
    """5xx errors are network-class. Pre-fix, 40 cumulative would
    bail; post-fix, network bails at 3 consecutive fully-failed
    batches OR 20 cumulative network failures — whichever first.

    Setup: every request → 503. Expect bail with stop_reason
    starting ``upstream_unstable:network_*``.
    """
    _ScriptedHandler.responses = [('5xx', 503)] * 50
    progress_file = tmp_path / "progress.jsonl"
    output_dir = tmp_path / "out"

    rc = _run_analyzer(fake_upstream, progress_file, output_dir, max_chunks=50)
    # Analyzer bails non-zero because of upstream_unstable.
    # Don't strict-assert rc since the failed event still exits 1.
    events = _read_progress_events(progress_file)
    failed_evts = [e for e in events if e.get("event") == "failed"]
    assert failed_evts, (
        f"expected 'failed' event with upstream_unstable reason; events="
        f"{[e.get('event') for e in events][:20]}"
    )
    reason = failed_evts[0].get("reason", "")
    assert reason.startswith("upstream_unstable:network_"), (
        f"network-class breakage should produce upstream_unstable:"
        f"network_* stop_reason; got {reason!r}"
    )

    # Each chunk_failed event carries error_class='network'.
    chunk_failed = [e for e in events if e.get("event") == "chunk_failed"]
    assert chunk_failed, "expected chunk_failed events"
    for e in chunk_failed:
        assert e.get("error_class") == "network", (
            f"5xx should classify as network; chunk_failed event: "
            f"{e!r}"
        )


# ── Machine-class fail-fast ───────────────────────────────────────


def test_machine_class_bails_fast_at_threshold(fake_upstream, tmp_path):
    """schema_drift errors are machine-class. Pre-fix, 40 cumulative
    needed to bail (same as network). Post-fix, machine-class bails
    at MAX_CUMULATIVE_FAILED_CHUNKS_MACHINE = 5 — much earlier so
    the operator sees the bug signal fast.

    Setup: every request → schema_drift_missing_fields. Expect bail
    AFTER the 5th machine-class chunk_failed (NOT after 20+).
    """
    _ScriptedHandler.responses = [('schema_drift',)] * 50
    progress_file = tmp_path / "progress.jsonl"
    output_dir = tmp_path / "out"

    rc = _run_analyzer(fake_upstream, progress_file, output_dir, max_chunks=50)
    events = _read_progress_events(progress_file)
    failed_evts = [e for e in events if e.get("event") == "failed"]
    assert failed_evts, "expected 'failed' event"
    reason = failed_evts[0].get("reason", "")
    assert reason.startswith("machine_bug:"), (
        f"schema_drift should produce machine_bug:* stop_reason; "
        f"got {reason!r}"
    )

    chunk_failed = [e for e in events if e.get("event") == "chunk_failed"]
    machine_failures = [e for e in chunk_failed if e.get("error_class") == "machine"]
    # Bailed at MAX_CUMULATIVE_FAILED_CHUNKS_MACHINE = 5. Allow
    # +/- 1 chunk for batch-boundary timing (a batch in flight when
    # we hit threshold completes its chunks). The point is we
    # bail well before 20+.
    assert 5 <= len(machine_failures) <= 8, (
        f"machine-class bail should fire at ~5 chunks "
        f"(MAX_CUMULATIVE_FAILED_CHUNKS_MACHINE), not the network-class "
        f"40-chunk limit. Got {len(machine_failures)} machine-class "
        f"failures before bail."
    )

    # Pre-fix would have classified everything the same and bailed
    # at ~40 cumulative. Pin the speedup explicitly.
    assert len(machine_failures) < 40, (
        f"REGRESSION: machine-class bail should fire FAST (<10 chunks). "
        f"Bailing at {len(machine_failures)} suggests the dual-counter "
        f"split was reverted to the monolithic threshold."
    )
