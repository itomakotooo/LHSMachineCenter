"""End-to-end regression tests for the run orchestrator
``fresh_slotlab/player_impact_analyzer.py``.

WHY THIS FILE EXISTS
--------------------
The OLD monolith was deleted in commit c72b05a. The console's live-sampling
path (``POST /api/batch-run``, ``POST /api/runs``) was broken with
"analyzer script not found" until the orchestrator was rebuilt as a thin
bridge: the VERBATIM sampling loop from the monolith + analysis delegated to
``report_engine.generate_report_from_chunks``. The console's RunManager
spawns this module as a subprocess (app.py ~6414) and ``_watch_run`` (app.py
~6564) reads:
  - exit code 0,
  - ``output_dir/player_impact_summary.json`` (parses ``sampling.total_spins``),
  - ``output_dir/player_impact_report.md`` (existence gate),
  - the progress JSONL stream (``completed`` event etc.).

These tests spawn the REAL orchestrator subprocess and assert on the produced
FILES — never exit-code-only (per memory/feedback_perf_claim_needs_e2e_event_stream:
"unit test + AST + import smoke green is not enough — spawn a real subprocess
against real fixtures and assert a user-visible signal"). An ``echo``-style
exit-code check would FALSELY pass even when report_engine delegation is
broken (see the inject-bug note below — the summary still writes + exits 0, but
``player_impact`` / ``rtp_integrity_check`` keys vanish).

VALUE-AGNOSTIC (ANALYZER_ARCHITECTURE §5.6): we assert structural / contract
keys (sampling.total_spins>0, sampling.bet>0 NOT 1, player_impact present,
rtp_integrity_check.passed, layer2 no _unattributed_* fallback buckets, schema
keys present, completed progress event). We NEVER pin an RTP value or range —
the machine's numbers change on re-sample / re-tune / upstream config drift.

RAWDATA ISOLATION (memory/feedback_enumerate_safety_paths +
tests/conftest.py session guard): no test writes into or deletes from the real
``rawdata/`` tree. from-cache reads are READ-ONLY; live sampling / unregistered
fixtures write only into ``tmp_path``. The session-autouse guard in
tests/conftest.py hard-fails any real-rawdata chunk delete.

INJECT-BUG PROOF (ran during authoring, recipe documented per claim):
  Test 2 (report delegation migrated): in player_impact_analyzer.py replace the
  ``summary = generate_report_from_chunks(...)`` call with ``summary = {}``.
  Re-run the from-cache subprocess → the summary still WRITES and the process
  still EXITS 0 (this is the false-green trap), but ``player_impact`` and
  ``rtp_integrity_check`` are ABSENT → ``test_from_cache_*`` go RED on the
  ``assert "player_impact" in summary`` / ``...["rtp_integrity_check"]...``
  assertions. Revert → GREEN. Verified 2026-06-17.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ANALYZER_SCRIPT = ROOT / "fresh_slotlab" / "player_impact_analyzer.py"

# Machine with a registered SpinType-native manifest + cached chunks. M283 has
# exactly 1 cached chunk in mode_1 (small + fast to replay). If it's ever
# evicted the from-cache / live tests skip rather than fail spuriously.
CACHE_MACHINE = "M283"
CACHE_MODE = 1
CACHE_DIR = ROOT / "rawdata" / CACHE_MACHINE / f"mode_{CACHE_MODE}"


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _has_cached_chunks(d: Path) -> bool:
    return d.is_dir() and bool(list(d.glob("chunk_*.json")))


def _read_events(progress_file: Path) -> list[dict]:
    if not progress_file.exists():
        return []
    out: list[dict] = []
    for line in progress_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _event_names(events: list[dict]) -> list[str]:
    return [e.get("event") for e in events]


def _run_orchestrator(args: list[str], timeout: float = 180) -> subprocess.CompletedProcess:
    """Spawn the REAL orchestrator subprocess (script mode, cwd=ROOT) — exactly
    how the console's RunManager invokes it (sys.executable + script path)."""
    cmd = [sys.executable, str(ANALYZER_SCRIPT), *args]
    return subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout
    )


def _build_canned_payload(n_robots: int = 2, n_rounds: int = 40) -> list[dict]:
    """Build a small canned /MultiRobotTestSpinVariant ``response`` payload by
    slicing a REAL cached chunk envelope. The cached ``response`` IS exactly
    what ``post_json`` returns (a list of robot dicts, each with double-encoded
    ``analysisResult`` / ``roundResult`` JSON strings), so this is byte-shape
    identical to a live upstream response — just smaller for speed.

    Re-encoding the sliced roundResult keeps the double-encoding the parser
    expects. Value-agnostic: we don't care what RTP the slice implies, only
    that parse_chunk_response + report_engine accept the shape and the live
    loop writes a chunk."""
    src = sorted(CACHE_DIR.glob("chunk_*.json"))
    if not src:
        raise RuntimeError(f"no cached chunk to clone in {CACHE_DIR}")
    raw = json.loads(src[0].read_text(encoding="utf-8"))
    resp = raw["response"]
    out: list[dict] = []
    for robot in resp[:n_robots]:
        rounds = json.loads(robot["roundResult"])[:n_rounds]
        analysis = json.loads(robot["analysisResult"])
        out.append(
            {
                "analysisResult": json.dumps(analysis),
                "roundResult": json.dumps(rounds),
            }
        )
    return out


class _StubUpstream:
    """A localhost HTTP server that returns a canned MultiRobotTestSpinVariant
    payload for any POST — so the live-sampling loop hits NO real network.

    monkeypatch can't cross a subprocess boundary, so we stand up a real
    socket and pass ``--endpoint-url http://127.0.0.1:<port>/...`` to the
    orchestrator (which routes through base_pipeline.ENDPOINT_URL)."""

    def __init__(self, payload: list[dict]):
        self._payload_bytes = json.dumps(payload).encode("utf-8")
        srv_payload = self._payload_bytes

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length:
                    self.rfile.read(length)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(srv_payload)))
                self.end_headers()
                self.wfile.write(srv_payload)

            def log_message(self, *args):  # noqa: D401 - silence stderr noise
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "_StubUpstream":
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()

    @property
    def endpoint_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/MachineTest/MultiRobotTestSpinVariant"


# ─────────────────────────────────────────────────────────────────────────
# Test 1 — --help works in BOTH invocation modes (script + package)
# ─────────────────────────────────────────────────────────────────────────


def test_help_script_mode_exit_zero():
    """``python fresh_slotlab/player_impact_analyzer.py --help`` → exit 0.

    This is the exact spawn shape the console uses (sys.executable + script
    path). If the dual-path imports at module top are broken, --help fails
    before argparse even runs — so a green --help proves the import block
    resolves in script mode (the mode that was failing as 'analyzer script
    not found')."""
    proc = _run_orchestrator(["--help"], timeout=60)
    assert proc.returncode == 0, (
        f"--help (script mode) exited {proc.returncode}\n"
        f"STDERR:\n{proc.stderr[-2000:]}"
    )
    assert "--machine" in proc.stdout
    assert "--from-cache" in proc.stdout
    assert "--output-dir" in proc.stdout


def test_help_package_mode_exit_zero():
    """``python -m fresh_slotlab.player_impact_analyzer --help`` → exit 0.

    Package mode resolves the qualified ``from fresh_slotlab.X import``
    imports; this proves the module also loads when run as a package
    (the mode some orchestration paths / tests use)."""
    cmd = [sys.executable, "-m", "fresh_slotlab.player_impact_analyzer", "--help"]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, (
        f"--help (package mode) exited {proc.returncode}\n"
        f"STDERR:\n{proc.stderr[-2000:]}"
    )
    assert "--machine" in proc.stdout


# ─────────────────────────────────────────────────────────────────────────
# Test 2 — from-cache mode: the "analysis migrated to report_engine" proof
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.skipif(
    not _has_cached_chunks(CACHE_DIR),
    reason=f"no cached chunks in {CACHE_DIR} (registered machine + rawdata required)",
)
def test_from_cache_produces_full_report(tmp_path):
    """from-cache replay → exit 0 + full report_engine summary.

    Reads the REAL cached chunks READ-ONLY (never writes/deletes rawdata).
    Asserts the report delegation actually ran by checking for the analysis
    keys report_engine produces. INJECT-BUG: replace the
    ``generate_report_from_chunks(...)`` call with ``summary = {}`` → these
    keys vanish (process still exits 0) → this test goes RED."""
    out_dir = tmp_path / "out"
    progress = tmp_path / "p.jsonl"
    proc = _run_orchestrator(
        [
            "--machine", CACHE_MACHINE,
            "--rtp-mode", str(CACHE_MODE),
            "--from-cache", str(CACHE_DIR),
            "--output-dir", str(out_dir),
            "--progress-file", str(progress),
            "--run-id", "t1",
            "--max-chunks", "1",
            "--bankruptcy-session-spins", "100",
            "--bankruptcy-bankroll-multipliers", "10",
        ]
    )
    assert proc.returncode == 0, (
        f"from-cache exited {proc.returncode}\nSTDERR:\n{proc.stderr[-3000:]}"
    )

    # ── _watch_run's two file-existence gates ──────────────────────────────
    summary_file = out_dir / "player_impact_summary.json"
    report_md = out_dir / "player_impact_report.md"
    assert summary_file.exists(), "player_impact_summary.json missing (watch_run gate)"
    assert report_md.exists(), "player_impact_report.md missing (watch_run gate)"

    summary = json.loads(summary_file.read_text(encoding="utf-8"))

    # ── sampling section (the section _watch_run inspects) ─────────────────
    sampling = summary.get("sampling") or {}
    assert int(sampling.get("total_spins") or 0) > 0, "sampling.total_spins must be > 0"
    # bet-trap (M279): the engine default bet=1 would land in sampling.bet and
    # the frontend would render every '× bet' column 1000× inflated. The
    # orchestrator MUST read the real bet from the chunk envelope's _bet.
    bet = sampling.get("bet")
    assert bet is not None and float(bet) > 0, "sampling.bet must be present + positive"
    assert float(bet) != 1, (
        "sampling.bet == 1 → the bet-trap: chunk _bet was not propagated, "
        "frontend multiplier columns would render 1000x inflated"
    )

    # ── report_engine actually ran (the migration proof) ──────────────────
    assert "rtp_integrity_check" in summary, "report_engine did not run (no rtp_integrity_check)"
    assert "player_impact" in summary, "report_engine did not run (no player_impact)"

    # ── rtp_integrity (VALUE-AGNOSTIC: structural, no number pinned) ───────
    integrity = summary["rtp_integrity_check"]
    assert integrity.get("passed") is True, (
        f"rtp_integrity_check.passed != True: {integrity.get('summary_message')}"
    )
    assert integrity.get("layer1_invariant_ok") is True, "L1 sum==our_total invariant failed"
    # L2: NO _unattributed_* fallback buckets (silent mis-attribution sink).
    assert integrity.get("layer2_no_fallback_buckets_ok") is True, (
        f"L2 fallback buckets found: {integrity.get('layer2_fallback_buckets_found')}"
    )
    assert not integrity.get("layer2_fallback_buckets_found"), (
        "fallback (_unattributed_*) share must be 0"
    )

    # ── completed progress event (what _watch_run / the UI reads) ──────────
    events = _read_events(progress)
    names = _event_names(events)
    assert "completed" in names, f"no 'completed' progress event; saw {names}"

    # ── identity stamped correctly ─────────────────────────────────────────
    assert summary.get("machine") == CACHE_MACHINE
    assert int(summary.get("mode")) == CACHE_MODE


# ─────────────────────────────────────────────────────────────────────────
# Test 3 — LIVE sampling against a MOCKED upstream (the path that was broken)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.skipif(
    not _has_cached_chunks(CACHE_DIR),
    reason=f"need a real chunk to clone a canned payload from ({CACHE_DIR})",
)
def test_live_sampling_against_stub_writes_chunk_and_report(tmp_path):
    """The MOST IMPORTANT test: the live-sampling loop that was broken with
    'analyzer script not found'. We stand up a local stub HTTP server that
    returns a canned MultiRobotTestSpinVariant payload (cloned from a real
    chunk) and point the orchestrator at it via --endpoint-url. NO real
    network is hit.

    KEY assertions (prove the live loop is ALIVE end-to-end):
      - the loop reaches real sampling: a ``chunk_started`` event fires
        (this is the proof it gets PAST the old 'analyzer script not found'
        500 and INTO the sampling path),
      - at least one chunk_*.json is written to the tmp cache dir,
      - report_engine produces a summary with the correct bet (bet-trap),
      - the process exits 0 (clean — no crash/hang).

    All writes go to tmp_path — NOTHING touches the real rawdata/ tree."""
    payload = _build_canned_payload(n_robots=2, n_rounds=40)
    out_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"

    with _StubUpstream(payload) as stub:
        proc = _run_orchestrator(
            [
                "--machine", CACHE_MACHINE,
                "--rtp-mode", str(CACHE_MODE),
                "--target-halfwidth-pp", "999",   # never CI-stop; max_chunks bounds it
                "--max-chunks", "1",
                "--chunk-spin-times", "100",
                "--chunk-robot-count", "2",
                "--batch-concurrency", "1",
                "--timeout", "10",
                "--output-dir", str(out_dir),
                "--chunk-cache-dir", str(cache_dir),  # first-ever sample lands here (tmp)
                "--progress-file", str(out_dir / "p.jsonl"),
                "--run-id", "t2",
                "--endpoint-url", stub.endpoint_url,
                "--bankruptcy-session-spins", "100",
                "--bankruptcy-bankroll-multipliers", "10",
                "--disable-non-convergence-abort",
            ],
            timeout=180,
        )

    # ── process exits cleanly ──────────────────────────────────────────────
    assert proc.returncode == 0, (
        f"live sampling exited {proc.returncode}\nSTDERR:\n{proc.stderr[-3000:]}"
    )

    # ── the live loop RAN: it got past 'analyzer script not found' and into
    #    real sampling (chunk_started is emitted right before the HTTP fetch) ─
    events = _read_events(out_dir / "p.jsonl")
    names = _event_names(events)
    assert "chunk_started" in names, (
        f"live loop never reached the sampling phase; events seen: {names}"
    )

    # ── a chunk was actually written to the (tmp) cache dir ────────────────
    chunk_files = sorted(cache_dir.glob("chunk_*.json"))
    assert chunk_files, (
        f"live sampling wrote no chunk_*.json to {cache_dir}; events: {names}"
    )

    # ── report_engine produced a summary (canned payload is rich enough) ───
    summary_file = out_dir / "player_impact_summary.json"
    assert summary_file.exists(), "no summary produced after live sampling"
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    sampling = summary.get("sampling") or {}
    assert int(sampling.get("total_spins") or 0) > 0, "live sampling produced 0 spins"
    # bet-trap on the live path too.
    bet = sampling.get("bet")
    assert bet is not None and float(bet) > 0 and float(bet) != 1, (
        f"sampling.bet bet-trap on live path: bet={bet!r}"
    )
    assert "completed" in names, f"no 'completed' event; saw {names}"

    # ── the real rawdata tree was NOT touched (paranoia: cache dir is tmp) ──
    assert str(cache_dir).startswith(str(tmp_path)), "cache dir must be under tmp_path"


# ─────────────────────────────────────────────────────────────────────────
# Test 4 — unregistered machine → graceful (no crash / no hang)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.skipif(
    not _has_cached_chunks(CACHE_DIR),
    reason=f"need a real chunk to copy into the fake-machine fixture ({CACHE_DIR})",
)
def test_unregistered_machine_fails_gracefully(tmp_path):
    """from-cache on a machine with NO manifest → non-zero exit + an
    ``analysis_error`` (MachineNotRegistered) progress event — NOT an
    uncaught traceback and NOT a hang.

    We copy ONE real chunk into a tmp dir (the real rawdata tree is never
    written) and run the orchestrator under a fake machine name 'MNOPE'
    that has no manifest in configs/machine_manifests/."""
    fake_cache = tmp_path / "cache"
    fake_cache.mkdir(parents=True)
    src = sorted(CACHE_DIR.glob("chunk_*.json"))[0]
    shutil.copyfile(src, fake_cache / "chunk_0001.json")

    out_dir = tmp_path / "out"
    progress = tmp_path / "p.jsonl"
    proc = _run_orchestrator(
        [
            "--machine", "MNOPE",
            "--rtp-mode", "1",
            "--from-cache", str(fake_cache),
            "--output-dir", str(out_dir),
            "--progress-file", str(progress),
            "--run-id", "t4",
            "--max-chunks", "1",
            "--bankruptcy-session-spins", "100",
            "--bankruptcy-bankroll-multipliers", "10",
        ],
        timeout=120,
    )

    # ── non-zero exit (the orchestrator returns 1 when analysis errors) ────
    assert proc.returncode != 0, (
        "unregistered machine should exit non-zero; "
        f"exited {proc.returncode}\nSTDERR:\n{proc.stderr[-2000:]}"
    )

    # ── a clean analysis_error event, not a raw traceback ──────────────────
    events = _read_events(progress)
    names = _event_names(events)
    assert "analysis_error" in names, (
        f"expected an 'analysis_error' event for an unregistered machine; saw {names}"
    )
    err_events = [e for e in events if e.get("event") == "analysis_error"]
    assert err_events, "no analysis_error event payload"
    assert "MachineNotRegistered" in str(err_events[0].get("error", "")), (
        f"analysis_error should name MachineNotRegistered: {err_events[0].get('error')!r}"
    )

    # ── stderr is NOT an uncaught traceback that crashed the process ───────
    assert "Traceback (most recent call last)" not in (proc.stderr or ""), (
        "unregistered machine produced an uncaught traceback (should be handled "
        f"gracefully):\n{proc.stderr[-2000:]}"
    )

    # ── still wrote a minimal summary so _watch_run can read stop_reason ───
    summary_file = out_dir / "player_impact_summary.json"
    assert summary_file.exists(), "even on analysis error a minimal summary must be written"
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    assert "analysis_failed" in str(
        (summary.get("sampling") or {}).get("stop_reason", "")
    ), "stop_reason should record the analysis failure"
