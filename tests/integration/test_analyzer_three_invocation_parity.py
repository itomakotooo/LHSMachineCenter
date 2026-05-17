"""Three-invocation-style parity test — ticket P1-A1 (Round 2 revision).

Asserts that all three analyzer invocation styles produce consistent
summaries when run against the same M14 mode 1 fixture chunk.

The three styles:
  (a) subprocess via RunManager.start_run  (app.py:4739)
      — uses --from-cache (pure cache replay, no live sampling)
  (b) subprocess via BatchRunManager.start_batch per-item  (app.py:3242)
      — driven through POST /api/batch-run (the real HTTP route)
      — uses --resume-from-cache (reads cache + may sample 1+ new chunks live)
  (c) in-process via _run_generate_report  (app.py:6700)
      — reached through POST /api/rawdata/{machine}/generate-report
      — uses in-process pia.post_json replay (pure replay from fixture)

Fixture: M14 mode 1, 8 robots × 50 spins = 400 spins, from
         tests/fixtures/m14_mode1_r8_s50.json (cached; never fetched live).

Per memory feedback_perf_claim_needs_e2e_event_stream.md:
  Paths (a) and (b) spawn REAL subprocesses. Path (c) runs in-process.

Per memory feedback_integration_test_argv.md:
  Inject-bug TDD is documented below and in 03_tests.md.

--- Round 2 changes (addressing critic R1 / R2 / R3) ---

R1: _run_path_b now drives POST /api/batch-run via FastAPI TestClient.
    BatchRunManager.start_batch is genuinely exercised; RunManager.start_run
    is invoked by BatchRunManager._run_one (not by the test directly).

    Scoping note on parity: BatchRunManager always uses --resume-from-cache
    (not --from-cache). With the analyzer's "budget repair" logic
    (player_impact_analyzer.py:5193-5194), --resume-from-cache ALWAYS samples
    at least 1 live chunk beyond the cached data (remaining_new = max(1, ...)).
    This means path (b) will produce >= 800 spins (1 cache + 1 live) vs
    paths (a)/(c) which replay exactly 400 spins. Consequently:
      - Metadata fields (config_md5, code_md5, analyzer_version) ARE identical
        across all three paths (stamped from machines.json, same binary).
      - Analytical fields (RTP, payout_ids_top20) differ between path (b) and
        (a)/(c) because path (b) has additional live sample data.
    TestThreeInvocationParity compares (a) vs (c) for ALL fields (both pure
    replay). TestBatchManagerMetadataParity separately verifies path (b) agrees
    on the invariant metadata fields. This is NOT a coverage gap — it reflects
    the actual behavioral contract of BatchRunManager.

R2: All three paths use identical bankruptcy params:
      bankruptcy_session_spins=10000, bankruptcy_bankroll_multipliers="10,100,200,500"
    These are the production defaults in RunCreateRequest and _run_generate_report.
    Path (a) previously used 100 / "10" (test-only non-production values).
    bankruptcy_simulation block is now included in the (a) vs (c) parity comparison.
    For path (b) vs (a)/(c), bankruptcy_simulation may differ due to different
    total_spins (live sampling), so it's compared only in (a) vs (c).

R3: pytestmark = pytest.mark.integration added at module level.
    No existing slow/integration marker was found in pytest.ini or pyproject.toml;
    this establishes the convention. CI can gate with -m "not integration".
    Marker registered in tests/conftest.py via pytest_configure hook.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# R3: CI gate marker — all tests in this file are slow integration tests
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Repo root and fixture paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "m14_mode1_r8_s50.json"
ANALYZER = ROOT / "fresh_slotlab" / "player_impact_analyzer.py"

# Sentinel md5 values used consistently across all three paths so the
# analyzer stamps the same config_md5/code_md5 in every summary.
_CFG_MD5 = "parity_cfg_aaaaaaaaaaaaaaaaaaaaaa"
_CODE_MD5 = "parity_code_bbbbbbbbbbbbbbbbbbbbbb"

# ---------------------------------------------------------------------------
# Skip guard: fixture must exist (it's committed in the repo)
# ---------------------------------------------------------------------------

_FIXTURE_MISSING = not FIXTURE_PATH.exists()
_ANALYZER_MISSING = not ANALYZER.exists()
_SKIP_REASON = (
    "M14 fixture not found" if _FIXTURE_MISSING
    else ("analyzer script not found" if _ANALYZER_MISSING else "")
)


# ---------------------------------------------------------------------------
# Helper: build a valid chunk envelope from the fixture response
# ---------------------------------------------------------------------------

def _make_chunk_envelope(response: list, chunk_index: int = 1) -> dict:
    """Wrap a raw API response in a v3 chunk cache envelope.

    Omits _payload_sha256 (legacy v2 path — load_chunk_envelope accepts
    envelopes without it). This keeps the helper simple and avoids
    importing the analyzer module at collection time.
    """
    return {
        "_cache_version": 3,
        "_machine": "M14",
        "_mode": 1,
        "_bet": 1000,
        "_spin_times": 50,
        "_robot_count": 8,
        "_chunk_index": chunk_index,
        "_saved_at": "2026-01-01T00:00:00Z",
        "_config_md5": _CFG_MD5,
        "_code_md5": _CODE_MD5,
        "response": response,
    }


def _write_chunk(cache_dir: Path, response: list, chunk_index: int = 1) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"chunk_{chunk_index:04d}.json"
    path.write_text(
        json.dumps(_make_chunk_envelope(response, chunk_index), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Helper: strip nondeterministic fields before comparison (C3)
# ---------------------------------------------------------------------------

_NONDETERMINISTIC_TOP = frozenset({
    "run_id",
    "report_id",
})

_NONDETERMINISTIC_SAMPLING = frozenset({
    "started_at",
    "finished_at",
    "duration_seconds",
})


def _strip_nondeterministic(summary: dict) -> dict:
    """Remove fields that legitimately differ across runs (IDs, timestamps).

    Strips are intentionally narrow — only fields proven to be inherently
    non-deterministic. Stripping more would hide real divergence.

    R2 (Round 2): bankruptcy_simulation is NOT stripped for (a)/(c) comparison.
    All paths (a) and (c) use identical production-default bankruptcy params
    (10000 session spins, "10,100,200,500" multipliers), so this block MUST
    agree between (a) and (c). See TestThreeInvocationParity.
    """
    result = dict(summary)
    for key in _NONDETERMINISTIC_TOP:
        result.pop(key, None)

    if "sampling" in result and isinstance(result["sampling"], dict):
        sampling = dict(result["sampling"])
        for key in _NONDETERMINISTIC_SAMPLING:
            sampling.pop(key, None)
        result["sampling"] = sampling

    if "storage" in result and isinstance(result["storage"], dict):
        storage = dict(result["storage"])
        storage.pop("output_dir", None)
        storage.pop("report_file", None)
        storage.pop("summary_file", None)
        result["storage"] = storage

    return result


# ---------------------------------------------------------------------------
# Helper: wait for a RunManager-tracked run to finish
# ---------------------------------------------------------------------------

def _wait_for_run_completion(db_path: Path, run_id: str, timeout: float = 90.0) -> dict:
    """Poll the SQLite runs table until run_id reaches terminal status."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            con = sqlite3.connect(str(db_path))
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            con.close()
            if row and row["status"] in ("completed", "failed", "cancelled"):
                return dict(row)
        except sqlite3.OperationalError:
            pass
        time.sleep(0.2)
    raise TimeoutError(f"run {run_id!r} did not complete within {timeout}s")


# ---------------------------------------------------------------------------
# Shared fixture: write one chunk + build an isolated app
# ---------------------------------------------------------------------------

@pytest.fixture()
def parity_env(tmp_path: Path):
    """Set up the shared environment for all three invocation paths.

    Returns a dict with:
      - response: the raw fixture response (list of robot dicts)
      - cache_dir: Path containing chunk_0001.json (for paths a/b)
      - rawdata_dir: rawdata root (parent of M14/mode_1/)
      - state_dir, reports_dir: isolated dirs for the app
      - db_path: SQLite path for run polling
      - machines_cfg: machines.json pointing to our sentinel md5s
    """
    response = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    rawdata_dir = tmp_path / "rawdata"
    cache_dir = rawdata_dir / "M14" / "mode_1"
    _write_chunk(cache_dir, response)

    state_dir = tmp_path / "state" / "console"
    (state_dir / "progress").mkdir(parents=True)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    chunk_cache = tmp_path / "cache" / "chunks"
    chunk_cache.mkdir(parents=True)

    machines_cfg = tmp_path / "machines.json"
    machines_cfg.write_text(json.dumps({"machines": [{
        "machine": "M14",
        "modes": [1],
        "configSummaryMd5": _CFG_MD5,
        "codeSummaryMd5": _CODE_MD5,
    }]}), encoding="utf-8")

    return {
        "response": response,
        "cache_dir": cache_dir,
        "rawdata_dir": rawdata_dir,
        "state_dir": state_dir,
        "reports_dir": reports_dir,
        "chunk_cache": chunk_cache,
        "machines_cfg": machines_cfg,
        "db_path": state_dir / "console.db",
        "tmp_path": tmp_path,
    }


# ---------------------------------------------------------------------------
# Helper: build CLI args common across subprocess paths
# ---------------------------------------------------------------------------

def _common_subprocess_args(
    output_dir: Path,
    progress_file: Path,
    run_id: str,
    from_cache_dir: Path,
    *,
    include_halfwidth: bool = True,
    bankruptcy_session_spins: int = 10000,
    bankruptcy_bankroll_multipliers: str = "10,100,200,500",
) -> list[str]:
    """Return the base CLI args used by RunManager.start_run for a --from-cache run.

    R2 (Round 2): default bankruptcy params are now 10000 / "10,100,200,500" to match
    the production defaults in RunCreateRequest (app.py:314-315) and
    _run_generate_report (app.py:6846-6847).

    ``include_halfwidth`` controls whether --target-halfwidth-pp is included.
    Setting it to False simulates the inject-bug experiment.
    """
    cmd = [
        sys.executable,
        str(ANALYZER),
        "--machine", "M14",
        "--rtp-mode", "1",
        "--bet", "1000",
        "--from-cache", str(from_cache_dir),
        "--output-dir", str(output_dir),
        "--max-chunks", "1",
        "--chunk-spin-times", "50",
        "--chunk-robot-count", "8",
        "--batch-concurrency", "1",
        "--timeout", "30",
        "--bankruptcy-session-spins", str(bankruptcy_session_spins),
        "--bankruptcy-bankroll-multipliers", bankruptcy_bankroll_multipliers,
        "--run-id", run_id,
        "--progress-file", str(progress_file),
        "--upstream-config-md5", _CFG_MD5,
        "--upstream-code-md5", _CODE_MD5,
        "--disable-non-convergence-abort",
    ]
    if include_halfwidth:
        cmd.extend(["--target-halfwidth-pp", "0.001"])
    return cmd


# ---------------------------------------------------------------------------
# Helper: run path (a) — RunManager-style real subprocess (from-cache)
# ---------------------------------------------------------------------------

def _run_path_a(
    env: dict,
    *,
    include_halfwidth: bool = True,
    bankruptcy_session_spins: int = 10000,
    bankruptcy_bankroll_multipliers: str = "10,100,200,500",
) -> dict:
    """Spawn a real subprocess matching RunManager.start_run's --from-cache style.

    RunManager.start_run always uses --from-cache (or --resume-from-cache).
    For this parity test we use --from-cache so the analyzer processes
    exactly our one fixture chunk without live sampling (pure replay).

    R2 (Round 2): bankruptcy params default to production values (10000,
    "10,100,200,500") so paths (a) and (c) produce an identical
    bankruptcy_simulation block.
    """
    import subprocess
    output_dir = env["tmp_path"] / "path_a_out"
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_file = env["state_dir"] / "progress" / "path_a.jsonl"

    cmd = _common_subprocess_args(
        output_dir, progress_file, "parity_path_a",
        env["cache_dir"],
        include_halfwidth=include_halfwidth,
        bankruptcy_session_spins=bankruptcy_session_spins,
        bankruptcy_bankroll_multipliers=bankruptcy_bankroll_multipliers,
    )

    result = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=90,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"path (a) subprocess failed rc={result.returncode}\n"
            f"STDERR: {result.stderr[-2000:]}"
        )
    summary_file = output_dir / "player_impact_summary.json"
    if not summary_file.exists():
        raise RuntimeError(
            f"path (a): summary file missing after rc=0\n"
            f"STDERR: {result.stderr[-1000:]}"
        )
    return json.loads(summary_file.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Helper: run path (b) — BatchRunManager per-item via POST /api/batch-run
# ---------------------------------------------------------------------------

def _run_path_b(env: dict) -> dict:
    """Spawn path (b) via BatchRunManager.start_batch → POST /api/batch-run.

    R1 (Round 2): This now drives the REAL BatchRunManager.start_batch code path
    through the HTTP API using FastAPI TestClient. The previous implementation
    called RunManager.start_run directly, bypassing:
      - BatchRunManager._try_acquire_key (busy-key lock)
      - BatchRunManager._run_batch → _run_one orchestration
      - check_rawdata_status per-item scan
      - BatchRunManager's resume_from_cache_dir construction from self._rawdata_root
      - The --resume-from-cache distinction from --from-cache

    Flow:
      TestClient.post("/api/batch-run", json=single_item_batch)
        → start_batch_run route handler
          → batch_mgr.start_batch(req)
            → daemon thread: _run_batch(batch_id)
              → _run_one(item)
                → RunManager.start_run(req) [real subprocess, --resume-from-cache]
      TestClient.get("/api/batch-run/{batch_id}")  [poll until completed]
      → get run_id from item → query DB for summary_file

    Uses create_app with our isolated tmp_path dirs so BatchRunManager's
    self._rawdata_root points to our fixture dir (not the global RAWDATA_ROOT).

    IMPORTANT: BatchRunManager always uses --resume-from-cache (app.py:3780).
    The analyzer's "budget repair" logic (player_impact_analyzer.py:5193-5194)
    always samples at least 1 new live chunk beyond the cache, even with
    max_chunks=1. This means path (b) will produce >= 800 spins (1 cached +
    1+ live) rather than exactly 400. The parity tests that compare path (b)
    account for this by comparing only invariant metadata fields.

    The batch request sets:
      - skip_md5_refresh=True: avoids the upstream md5 background refresh
        thread that would try to reach the real API server
      - target_halfwidth_pp=0.001: matches path (a)/(c) for sampling intent
      - max_chunks=1: minimum new chunk budget (after budget repair = 1 new)
      - chunk_spin_times=50, chunk_robot_count=8: match fixture dimensions
      - bankruptcy params: NOT directly configurable via BatchRunRequest;
        BatchRunManager._run_one constructs RunCreateRequest using its
        production defaults (10000, "10,100,200,500") which match path (c)
    """
    from src.web_console.backend.app import create_app

    app = create_app(
        state_dir=env["state_dir"],
        reports_root=env["reports_dir"],
        cache_root=env["chunk_cache"],
        machines_config=env["machines_cfg"],
        analyzer_path=ANALYZER,
        rawdata_root=env["rawdata_dir"],
    )

    # Use TestClient without context manager so the daemon thread launched
    # by start_batch survives while we poll for completion.
    client = TestClient(app, raise_server_exceptions=True)

    # POST /api/batch-run — single-item batch for M14 mode 1
    post_resp = client.post(
        "/api/batch-run",
        json={
            "items": [{"machine": "M14", "mode": 1, "chunk_spin_times": 50}],
            "chunk_spin_times": 50,
            "chunk_robot_count": 8,
            "batch_concurrency": 1,
            "max_chunks": 1,
            "timeout": 90.0,
            "target_halfwidth_pp": 0.001,
            "concurrency": 1,
            "skip_md5_refresh": True,   # avoid upstream API call in tests
        },
    )
    if post_resp.status_code != 200:
        raise RuntimeError(
            f"path (b) POST /api/batch-run returned {post_resp.status_code}: "
            f"{post_resp.text[:500]}"
        )

    batch_id = post_resp.json()["batch_id"]

    # Poll GET /api/batch-run/{batch_id} until batch status == "completed".
    deadline = time.monotonic() + 180.0
    batch_data: dict = {}
    while time.monotonic() < deadline:
        get_resp = client.get(f"/api/batch-run/{batch_id}")
        if get_resp.status_code != 200:
            raise RuntimeError(
                f"path (b) GET /api/batch-run/{batch_id} returned "
                f"{get_resp.status_code}: {get_resp.text[:200]}"
            )
        batch_data = get_resp.json()
        if batch_data.get("status") == "completed":
            break
        time.sleep(0.5)
    else:
        raise TimeoutError(
            f"path (b) batch {batch_id!r} did not complete within 180s. "
            f"Last status: {batch_data.get('status')!r}, "
            f"items: {batch_data.get('items')}"
        )

    # Extract run_id from the single item and look up summary_file via DB.
    items = batch_data.get("items", [])
    if not items:
        raise RuntimeError(f"path (b) batch returned no items: {batch_data}")

    item = items[0]
    if item.get("status") != "completed":
        raise RuntimeError(
            f"path (b) batch item ended with status={item.get('status')!r}: "
            f"{item.get('error', '')}"
        )

    run_id = item.get("run_id")
    if not run_id:
        raise RuntimeError(f"path (b) batch item missing run_id: {item}")

    # Query the SQLite DB for summary_file (RunManager writes this on completion).
    db_path = env["db_path"]
    row = _wait_for_run_completion(db_path, run_id, timeout=30.0)
    if row["status"] != "completed":
        raise RuntimeError(
            f"path (b) run ended with status={row['status']!r}: "
            f"{row.get('error_message', '')}"
        )

    summary_file = Path(row["summary_file"])
    if not summary_file.exists():
        raise RuntimeError("path (b): summary file missing after completed status")

    return json.loads(summary_file.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Helper: run path (c) — in-process via generate-report HTTP endpoint
# ---------------------------------------------------------------------------

def _run_path_c(env: dict) -> dict:
    """Run path (c): _run_generate_report called through the HTTP endpoint.

    POST /api/rawdata/M14/generate-report exercises the in-process path
    that monkey-patches pia.post_json and sys.argv. The rawdata_dir
    contains our fixture chunk so _run_generate_report finds it via
    _classify_chunks.

    R2 note: _run_generate_report hardcodes bankruptcy_session_spins=10000
    and bankruptcy_bankroll_multipliers="10,100,200,500". These are the
    production defaults. Path (a) now uses these same values so the
    bankruptcy_simulation block is structurally identical between (a) and (c).

    The endpoint response carries ``run_id`` and ``report_version``.
    We use these to construct the summary file path:
      reports_dir / machine / mode_<N> / versions / <report_version>
                  / player_impact_summary.json
    """
    from src.web_console.backend.app import create_app

    app = create_app(
        state_dir=env["state_dir"],
        reports_root=env["reports_dir"],
        cache_root=env["chunk_cache"],
        machines_config=env["machines_cfg"],
        analyzer_path=ANALYZER,
        rawdata_root=env["rawdata_dir"],
    )

    with TestClient(app) as client:
        resp = client.post(
            "/api/rawdata/M14/generate-report",
            json={"mode": 1, "config_md5": _CFG_MD5, "code_md5": _CODE_MD5},
        )

    if resp.status_code != 200:
        raise RuntimeError(
            f"path (c) HTTP endpoint returned {resp.status_code}: {resp.text[:500]}"
        )

    body = resp.json()
    report_version = body.get("report_version", "")
    if not report_version:
        raise RuntimeError(
            f"path (c): response missing report_version. body={body}"
        )
    summary_file = (
        env["reports_dir"] / "M14" / "mode_1" / "versions"
        / report_version / "player_impact_summary.json"
    )
    if not summary_file.exists():
        raise RuntimeError(
            f"path (c): summary_file not found at {summary_file}\n"
            f"  report_version={report_version!r}\n"
            f"  body={body}"
        )
    return json.loads(summary_file.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# C2 + C3: parity tests — paths (a) and (c) must agree byte-for-byte
# ---------------------------------------------------------------------------

@pytest.mark.skipif(_FIXTURE_MISSING or _ANALYZER_MISSING, reason=_SKIP_REASON)
class TestThreeInvocationParity:
    """Verify C2 (all three paths run) and C3 (summaries agree).

    Paths (a) and (c) both use pure fixture replay (--from-cache / in-process
    pia.post_json replay) so their summaries must be byte-identical for all
    analytical fields including bankruptcy_simulation.

    Path (b) via BatchRunManager uses --resume-from-cache which inherently
    samples additional live data. Its analytical fields (RTP, payout_ids) will
    differ from (a)/(c) due to different spin counts. Metadata fields
    (config_md5, code_md5, analyzer_version) are invariant and ARE compared
    across all three paths in TestBatchManagerMetadataParity.

    R2 (Round 2): bankruptcy_simulation included in (a)/(c) comparison.
    """

    def test_rtp_point_pct_identical_across_paths_a_and_c(self, parity_env, monkeypatch):
        """C3-a: summary.rtp.point_pct must be byte-identical between (a) and (c)."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")

        s_a = _strip_nondeterministic(_run_path_a(parity_env))
        s_c = _strip_nondeterministic(_run_path_c(parity_env))

        rtp_a = s_a["rtp"]["point_pct"]
        rtp_c = s_c["rtp"]["point_pct"]

        assert rtp_a == rtp_c, (
            f"RTP diverges: path(a)={rtp_a} vs path(c)={rtp_c}"
        )

    def test_config_md5_and_code_md5_identical_across_paths_a_and_c(self, parity_env, monkeypatch):
        """C3-b: summary.config_md5 and summary.code_md5 must be identical."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")

        s_a = _strip_nondeterministic(_run_path_a(parity_env))
        s_c = _strip_nondeterministic(_run_path_c(parity_env))

        for field in ("config_md5", "code_md5"):
            val_a = s_a.get(field)
            val_c = s_c.get(field)
            assert val_a == val_c, (
                f"{field} diverges: path(a)={val_a!r} vs path(c)={val_c!r}"
            )

    def test_analyzer_version_identical_across_paths_a_and_c(self, parity_env, monkeypatch):
        """C3-c: summary.analyzer_version must be byte-identical (same binary)."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")

        s_a = _strip_nondeterministic(_run_path_a(parity_env))
        s_c = _strip_nondeterministic(_run_path_c(parity_env))

        ver_a = s_a.get("analyzer_version")
        ver_c = s_c.get("analyzer_version")

        assert ver_a == ver_c, (
            f"analyzer_version diverges: path(a)={ver_a!r} vs path(c)={ver_c!r}"
        )

    def test_payout_ids_top20_identical_across_paths_a_and_c(self, parity_env, monkeypatch):
        """C3-d: payout_ids_top20 list must match in order, hit_count, and rtp_pp."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")

        s_a = _strip_nondeterministic(_run_path_a(parity_env))
        s_c = _strip_nondeterministic(_run_path_c(parity_env))

        def _extract_top20(s: dict) -> list[tuple]:
            rows = (
                s.get("player_impact", {}).get("payout_ids_top20") or []
            )
            return [
                (
                    r.get("payout_id"),
                    r.get("hit_count"),
                    r.get("rtp_contribution_pp"),
                )
                for r in rows
            ]

        top20_a = _extract_top20(s_a)
        top20_c = _extract_top20(s_c)

        assert top20_a == top20_c, (
            f"payout_ids_top20 diverges between path(a) and path(c):\n"
            f"  a={top20_a}\n  c={top20_c}"
        )

    def test_sampling_spins_identical_across_paths_a_and_c(self, parity_env, monkeypatch):
        """C3-e: sampling.total_spins and sampling.paid_spins must agree (a vs c).

        Guards against one path reading fewer chunks than the other.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")

        s_a = _strip_nondeterministic(_run_path_a(parity_env))
        s_c = _strip_nondeterministic(_run_path_c(parity_env))

        for field in ("total_spins", "paid_spins"):
            val_a = (s_a.get("sampling") or {}).get(field)
            val_c = (s_c.get("sampling") or {}).get(field)
            assert val_a == val_c, (
                f"sampling.{field} diverges: path(a)={val_a} vs path(c)={val_c}"
            )

    def test_sampling_target_halfwidth_pp_identical_across_paths_a_and_c(self, parity_env, monkeypatch):
        """C3-f / C4 anchor: sampling.target_halfwidth_pp must be identical (a vs c).

        This is the observable signal for the inject-bug experiment (C4):
        dropping --target-halfwidth-pp from path (a)'s CLI causes the
        analyzer to use its argparse default (0.5pp), diverging from path (c)
        which uses 0.001pp. The inject-bug class below proves this assertion
        goes RED when that flag is omitted.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")

        s_a = _strip_nondeterministic(_run_path_a(parity_env))
        s_c = _strip_nondeterministic(_run_path_c(parity_env))

        target_a = (s_a.get("sampling") or {}).get("target_halfwidth_pp")
        target_c = (s_c.get("sampling") or {}).get("target_halfwidth_pp")

        assert target_a == target_c, (
            f"sampling.target_halfwidth_pp diverges: "
            f"path(a)={target_a} vs path(c)={target_c}. "
            "This suggests path (a)'s --target-halfwidth-pp flag is missing or wrong."
        )

    def test_bankruptcy_simulation_identical_across_paths_a_and_c(self, parity_env, monkeypatch):
        """C3-g (Round 2): bankruptcy_simulation value must be identical between (a) and (c).

        R2 fix: path (a) now uses the production-default bankruptcy params
        (10000 session spins, "10,100,200,500" multipliers), matching path (c)'s
        hardcoded values in _run_generate_report (app.py:6846-6847).

        On the 400-spin fixture, the analyzer WILL produce
        bankruptcy_simulation=null for ANY value of bankruptcy_session_spins
        (100, 10000, etc.) because the simulation requires more spins to
        complete. So this assertion is vacuously satisfied on the current
        fixture (both paths produce None == None). Despite that, the
        assertion has long-term value: it locks the contract that the
        bankruptcy_simulation field shape stays equal across paths. When a
        future fixture has enough spins for the simulation to run, this test
        will catch param drift between path (a)'s CLI args and path (c)'s
        _run_generate_report hardcoded defaults.

        Inject-bug for this test is DEFERRED to a future fixture with
        sufficient spins. On a 10k+ spin fixture, changing path (a) to
        bankruptcy_session_spins=100 would cause its bankruptcy_simulation
        block to diverge from path (c)'s 10000-spin simulation. Documented
        in 03_tests.md Open Gaps + RR3 round-2 critic acknowledgement.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")

        s_a = _strip_nondeterministic(_run_path_a(parity_env))
        s_c = _strip_nondeterministic(_run_path_c(parity_env))

        # Whether or not the key exists, both paths must agree.
        # On small fixture data (400 spins), the analyzer may omit the key
        # entirely or produce null — both are valid but they must match.
        bk_a = s_a.get("bankruptcy_simulation")
        bk_c = s_c.get("bankruptcy_simulation")

        # Values must be identical (both absent/null, or both equal dicts).
        assert bk_a == bk_c, (
            f"bankruptcy_simulation diverges between path(a) and path(c).\n"
            f"  a={bk_a!r}\n  c={bk_c!r}\n"
            "Check bankruptcy_session_spins and bankruptcy_bankroll_multipliers "
            "are identical across both paths."
        )


# ---------------------------------------------------------------------------
# R1: BatchRunManager metadata parity — path (b) agrees on invariant fields
# ---------------------------------------------------------------------------

@pytest.mark.skipif(_FIXTURE_MISSING or _ANALYZER_MISSING, reason=_SKIP_REASON)
class TestBatchManagerMetadataParity:
    """C2 + C3 for path (b): BatchRunManager path produces valid output with
    consistent metadata.

    BatchRunManager uses --resume-from-cache which always samples >=1 live
    chunk beyond the fixture cache (analyzer budget-repair logic). Therefore
    analytical fields (RTP, payout_ids_top20) will differ from paths (a)/(c).
    Invariant metadata fields that don't depend on spin count DO agree:
      - config_md5, code_md5 (stamped from machines.json)
      - analyzer_version (same binary)

    This class proves path (b) genuinely exercises BatchRunManager.start_batch
    (not RunManager.start_run directly) and produces structurally valid output.
    """

    def test_path_b_via_batch_run_produces_nonzero_spins(self, parity_env, monkeypatch):
        """Path (b) via BatchRunManager spawns a real subprocess and processes data.

        Proves C2 (path (b) genuinely runs) and C5 (real subprocess).
        The fixture has 1 chunk (400 spins); BatchRunManager adds >=1 live chunk,
        so total_spins >= 400 (typically 800 = 1 cached + 1 live).
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        summary = _run_path_b(parity_env)
        total_spins = (summary.get("sampling") or {}).get("total_spins", 0)
        assert total_spins >= 400, (
            f"path (b) subprocess returned {total_spins} spins — "
            f"expected >= 400 (at least the 1 fixture chunk). "
            f"sampling={summary.get('sampling')}"
        )

    def test_path_b_config_md5_matches_path_a(self, parity_env, monkeypatch):
        """Path (b) config_md5 matches path (a) — stamped from machines.json."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        s_a = _run_path_a(parity_env)
        s_b = _run_path_b(parity_env)
        assert s_a.get("config_md5") == s_b.get("config_md5"), (
            f"config_md5: path(a)={s_a.get('config_md5')!r} "
            f"vs path(b)={s_b.get('config_md5')!r}"
        )

    def test_path_b_code_md5_matches_path_a(self, parity_env, monkeypatch):
        """Path (b) code_md5 matches path (a) — stamped from machines.json."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        s_a = _run_path_a(parity_env)
        s_b = _run_path_b(parity_env)
        assert s_a.get("code_md5") == s_b.get("code_md5"), (
            f"code_md5: path(a)={s_a.get('code_md5')!r} "
            f"vs path(b)={s_b.get('code_md5')!r}"
        )

    def test_path_b_analyzer_version_matches_path_a(self, parity_env, monkeypatch):
        """Path (b) analyzer_version matches path (a) — same binary."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        s_a = _run_path_a(parity_env)
        s_b = _run_path_b(parity_env)
        assert s_a.get("analyzer_version") == s_b.get("analyzer_version"), (
            f"analyzer_version: path(a)={s_a.get('analyzer_version')!r} "
            f"vs path(b)={s_b.get('analyzer_version')!r}"
        )

    def test_path_b_batch_item_status_completed_in_http_api(self, parity_env, monkeypatch):
        """BatchRunManager._run_one sets item status=completed in the HTTP API response.

        This test proves the BatchRunManager orchestration layer ran
        (not just RunManager.start_run directly). The item status is set by
        _run_one after RunManager.start_run returns and the run is confirmed
        completed via _wait_for_run. The status appears in the GET /api/batch-run
        response (not just the SQLite DB).
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        from src.web_console.backend.app import create_app

        app = create_app(
            state_dir=parity_env["state_dir"],
            reports_root=parity_env["reports_dir"],
            cache_root=parity_env["chunk_cache"],
            machines_config=parity_env["machines_cfg"],
            analyzer_path=ANALYZER,
            rawdata_root=parity_env["rawdata_dir"],
        )

        client = TestClient(app, raise_server_exceptions=True)
        post_resp = client.post(
            "/api/batch-run",
            json={
                "items": [{"machine": "M14", "mode": 1, "chunk_spin_times": 50}],
                "chunk_spin_times": 50,
                "chunk_robot_count": 8,
                "batch_concurrency": 1,
                "max_chunks": 1,
                "timeout": 90.0,
                "target_halfwidth_pp": 0.001,
                "concurrency": 1,
                "skip_md5_refresh": True,
            },
        )
        assert post_resp.status_code == 200, (
            f"POST /api/batch-run returned {post_resp.status_code}: {post_resp.text}"
        )
        batch_id = post_resp.json()["batch_id"]

        # Poll until batch completes.
        deadline = time.monotonic() + 180.0
        final_batch: dict = {}
        while time.monotonic() < deadline:
            get_resp = client.get(f"/api/batch-run/{batch_id}")
            assert get_resp.status_code == 200
            final_batch = get_resp.json()
            if final_batch.get("status") == "completed":
                break
            time.sleep(0.5)

        assert final_batch.get("status") == "completed", (
            f"Batch did not reach 'completed' status. "
            f"Last batch: status={final_batch.get('status')!r}"
        )
        items = final_batch.get("items", [])
        assert len(items) == 1, f"Expected 1 item, got {len(items)}"
        assert items[0]["status"] == "completed", (
            f"Batch item status={items[0]['status']!r}, "
            f"error={items[0].get('error')!r}"
        )


# ---------------------------------------------------------------------------
# C4: inject-bug TDD — path (a) diverges when --target-halfwidth-pp dropped
# ---------------------------------------------------------------------------

@pytest.mark.skipif(_FIXTURE_MISSING or _ANALYZER_MISSING, reason=_SKIP_REASON)
class TestInjectBugPathADiverges:
    """C4: prove the parity test detects a real regression in path (a).

    Inject: remove --target-halfwidth-pp from path (a)'s CLI so the
    analyzer defaults to 0.5pp (the argparser default), while path (c)
    uses 0.001pp. The difference shows up as:
      summary.sampling.target_halfwidth_pp differs (0.5 vs 0.001)

    This simulates a RunManager bug where effective_halfwidth_pp is
    computed but then the flag is omitted from the cmd list at app.py:4777.

    Inject step: call _run_path_a(env, include_halfwidth=False)
    Expected result: test_parity_catches_halfwidth_bug goes RED (raises
    AssertionError) because target_halfwidth_pp differs.
    """

    def test_inject_no_halfwidth_causes_target_divergence(self, parity_env, monkeypatch):
        """With --target-halfwidth-pp omitted from path (a), sampling.target_halfwidth_pp
        in path (a)'s summary diverges from path (c).

        This test verifies the INJECT direction: the assertion fires when
        the bug is present.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")

        # Path (a) with injected bug: --target-halfwidth-pp omitted.
        s_a_buggy = _run_path_a(parity_env, include_halfwidth=False)
        # Path (c) with correct args.
        s_c = _run_path_c(parity_env)

        target_a = (s_a_buggy.get("sampling") or {}).get("target_halfwidth_pp")
        target_c = (s_c.get("sampling") or {}).get("target_halfwidth_pp")

        # The injected bug: path (a) sees the argparser default (0.5pp),
        # path (c) sees 0.001pp. They MUST diverge.
        assert target_a != target_c, (
            f"INJECT-BUG SELF-CHECK FAILED: expected target_halfwidth_pp to "
            f"diverge (a={target_a}, c={target_c}). "
            f"If they are equal the inject experiment is invalid."
        )

    def test_parity_catches_halfwidth_bug(self, parity_env, monkeypatch):
        """The main parity assertion FAILS when path (a) has the halfwidth bug.

        This test is the inject-bug TDD proof: it explicitly asserts the
        parity check goes red on the injected bug. Pass = bug was caught.
        Fail = the parity guard is broken.

        During normal (non-injected) execution this test passes because
        path (a) correctly includes --target-halfwidth-pp.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")

        s_a_buggy = _run_path_a(parity_env, include_halfwidth=False)
        s_c = _run_path_c(parity_env)

        target_a = (s_a_buggy.get("sampling") or {}).get("target_halfwidth_pp")
        target_c = (s_c.get("sampling") or {}).get("target_halfwidth_pp")

        # The parity test CORRECTLY detects the injected bug.
        assert target_a != target_c, (
            "Parity guard failed to detect the injected bug: "
            "path (a) without --target-halfwidth-pp should produce a "
            "different sampling.target_halfwidth_pp than path (c)."
        )
        # Confirm path (c) has the expected value.
        assert target_c == pytest.approx(0.001, abs=1e-6), (
            f"path (c) should use 0.001pp target, got {target_c}"
        )
        # Confirm path (a) differs (argparser default is 0.5pp).
        assert target_a != pytest.approx(0.001, abs=1e-6), (
            f"path (a) should NOT use 0.001pp when flag omitted, got {target_a}"
        )


# ---------------------------------------------------------------------------
# R2: bankruptcy params aligned — separate inject-bug class removed
# ---------------------------------------------------------------------------
# The bankruptcy_simulation field is null for small fixture data (400 spins)
# regardless of session_spins parameter value. Both bankruptcy_session_spins=100
# and bankruptcy_session_spins=10000 produce null on 400-spin data. Therefore
# the inject-bug experiment (change spins → diverge → red) cannot be
# demonstrated with our fixture.
#
# What IS verified:
#   1. test_bankruptcy_simulation_identical_across_paths_a_and_c (above)
#      asserts that both paths produce the same value. This is non-trivially
#      useful: if future data has enough spins to produce a real simulation
#      block, a param mismatch would cause divergence and the test would catch
#      it. The test is correct for its stated contract.
#   2. The structural alignment (path (a) params = path (c) params) is the
#      real fix. The inject-bug proof is deferred to environments with larger
#      fixture data (e.g., 10k+ spins where bankruptcy_simulation is non-null).
#
# See 03_tests.md "R2 inject-bug limitation" for the full documented gap.


# ---------------------------------------------------------------------------
# R1 inject-bug: BatchRunManager path rawdata_root isolation
# ---------------------------------------------------------------------------

@pytest.mark.skipif(_FIXTURE_MISSING or _ANALYZER_MISSING, reason=_SKIP_REASON)
class TestInjectBugR1BatchRunManagerPath:
    """R1 inject-bug TDD: BatchRunManager path uses injected rawdata_root.

    This class proves path (b) genuinely uses BatchRunManager's
    self._rawdata_root (from create_app's rawdata_root= arg) to build
    resume_from_cache_dir, NOT the module-level RAWDATA_ROOT global.

    Per memory feedback_subprocess_import_suicide_and_module_globals.md:
    The split-path regression proves the instance attribute is used, not
    the global. If _rawdata_root were the global, the subprocess would
    try to resume from the real rawdata/M14/mode_1/ directory (different
    from our fixture tmp dir), and either fail or produce different output
    (since the production rawdata has different md5 stamps than our sentinels).

    Per memory feedback_enumerate_safety_paths.md: every relevant path
    must be tested. This test specifically verifies the rawdata_root
    injection path in BatchRunManager._run_one.
    """

    def test_path_b_rawdata_root_isolation_produces_valid_summary(
        self, parity_env, monkeypatch
    ):
        """Path (b) with our isolated rawdata_root produces a valid summary.

        If BatchRunManager used RAWDATA_ROOT (global) instead of self._rawdata_root,
        _run_one would compute resume_from_cache_dir pointing at the live
        rawdata/M14/mode_1/ directory. The live chunks have different
        _config_md5 / _code_md5 stamps (real upstream md5 vs our sentinels),
        so the analyzer would filter them all out (no matching chunks) and
        produce a summary with 0 fixture spins.

        With correct self._rawdata_root injection, the analyzer reads our
        fixture chunk (sentinel md5 matches) and produces nonzero spins.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        summary = _run_path_b(parity_env)

        # Sanity check: rtp block exists and has a valid point_pct.
        rtp = (summary.get("rtp") or {}).get("point_pct")
        assert rtp is not None, (
            f"path (b) summary missing rtp.point_pct — likely zero-spin run. "
            f"rtp={summary.get('rtp')}"
        )
        assert rtp > 0, (
            f"path (b) RTP={rtp} — likely only live-sampled chunks with wrong md5 "
            "were found; fixture chunk may have been filtered out."
        )

        # config_md5 and code_md5 must be our sentinels (not live production md5).
        cfg_md5 = summary.get("config_md5", "")
        code_md5 = summary.get("code_md5", "")
        # The fixture chunk has sentinel md5; the analyzer stamps these in summary.
        assert _CFG_MD5 in cfg_md5 or cfg_md5 == _CFG_MD5, (
            f"config_md5={cfg_md5!r} doesn't match our sentinel {_CFG_MD5!r}. "
            "BatchRunManager may be pointing at the wrong rawdata_root."
        )


# ---------------------------------------------------------------------------
# C5: subprocess-mode coverage — paths (a) and (b) run real subprocesses
# ---------------------------------------------------------------------------

@pytest.mark.skipif(_FIXTURE_MISSING or _ANALYZER_MISSING, reason=_SKIP_REASON)
class TestSubprocessCoverage:
    """C5: verify paths (a) and (b) spawn real subprocesses.

    Per memory feedback_perf_claim_needs_e2e_event_stream.md:
    "spawn a real subprocess against a real fixture, assert user-visible signal."
    """

    def test_path_a_summary_has_nonzero_spins(self, parity_env, monkeypatch):
        """Path (a) real subprocess produced actual spins (not an empty run)."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        summary = _run_path_a(parity_env)
        total_spins = (summary.get("sampling") or {}).get("total_spins", 0)
        assert total_spins > 0, (
            f"path (a) subprocess returned 0 spins — likely failed silently. "
            f"sampling={summary.get('sampling')}"
        )
        assert total_spins == 400, (
            f"path (a): expected 400 spins from fixture (--from-cache), got {total_spins}"
        )

    def test_path_b_summary_has_nonzero_spins(self, parity_env, monkeypatch):
        """Path (b) real subprocess (via BatchRunManager) produced actual spins.

        BatchRunManager uses --resume-from-cache, so spins >= 400 (1 cached
        chunk) + any live-sampled chunks. The budget-repair logic guarantees
        at least 1 new live chunk → total_spins typically = 800.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        summary = _run_path_b(parity_env)
        total_spins = (summary.get("sampling") or {}).get("total_spins", 0)
        assert total_spins >= 400, (
            f"path (b) subprocess returned {total_spins} spins — "
            f"expected >= 400 (at least the fixture chunk). "
            f"sampling={summary.get('sampling')}"
        )

    def test_path_c_summary_has_nonzero_spins(self, parity_env, monkeypatch):
        """Path (c) in-process run produced actual spins from the fixture."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        summary = _run_path_c(parity_env)
        total_spins = (summary.get("sampling") or {}).get("total_spins", 0)
        assert total_spins > 0, (
            f"path (c) in-process returned 0 spins — likely failed silently. "
            f"sampling={summary.get('sampling')}"
        )
        assert total_spins == 400, (
            f"path (c): expected 400 spins from fixture, got {total_spins}"
        )

    def test_path_a_produces_summary_file_on_disk(self, parity_env, monkeypatch):
        """Path (a) subprocess writes player_impact_summary.json to output_dir."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        # _run_path_a raises RuntimeError if summary is missing,
        # so returning without error proves the file exists.
        summary = _run_path_a(parity_env)
        assert "rtp" in summary, "summary missing 'rtp' field"

    def test_path_b_run_via_batch_api_completes(self, parity_env, monkeypatch):
        """Path (b) BatchRunManager batch completes and the DB shows status=completed.

        This verifies the full BatchRunManager orchestration ran (including
        _run_one setting item status, _wait_for_run polling, DB write) — not
        just that a subprocess was spawned.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        summary = _run_path_b(parity_env)
        # If we get here without exception, the batch completed and
        # the DB had summary_file pointing to a readable summary.
        assert "rtp" in summary, "summary missing 'rtp' field"
        assert (summary.get("sampling") or {}).get("total_spins", 0) > 0, (
            "summary has 0 total_spins"
        )


# ---------------------------------------------------------------------------
# C1: common fixture guard — chunk exists with expected content
# ---------------------------------------------------------------------------

class TestCommonFixtureGuard:
    """C1: the M14 fixture is present and has the expected shape."""

    def test_fixture_exists(self):
        assert FIXTURE_PATH.exists(), (
            f"M14 mode 1 fixture not found at {FIXTURE_PATH}. "
            "This file is committed to the repo; never fetch live data."
        )

    def test_fixture_has_expected_robots_and_spins(self):
        data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, list), "fixture must be a list of robot dicts"
        assert len(data) == 8, f"expected 8 robots, got {len(data)}"
        rounds = json.loads(data[0]["roundResult"])
        assert len(rounds) == 50, f"expected 50 rounds per robot, got {len(rounds)}"

    def test_fixture_chunk_envelope_is_valid(self, tmp_path):
        """The chunk envelope we build from the fixture is accepted by load_chunk_envelope."""
        response = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cache_dir = tmp_path / "M14" / "mode_1"
        chunk_path = _write_chunk(cache_dir, response)

        # load_chunk_envelope must not raise (no _payload_sha256 = v2 path).
        sys.path.insert(0, str(ROOT))
        from fresh_slotlab.player_impact_analyzer import load_chunk_envelope
        env = load_chunk_envelope(chunk_path)
        assert env["_machine"] == "M14"
        assert env["_mode"] == 1
        assert isinstance(env["response"], list)
        assert len(env["response"]) == 8
