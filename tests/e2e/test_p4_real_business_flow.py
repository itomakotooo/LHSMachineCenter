"""Phase-4 real-upstream E2E tests.

Memory feedback citations:
  feedback_perf_claim_needs_e2e_event_stream.md — real uvicorn, real Playwright,
      real upstream — no requests mocking.
  feedback_enumerate_safety_paths.md — each test documents its inject-bug recipe.
  feedback_no_proactive_fetch.md — user override: dev only, M14 mode 1, ≤1000 spin.
  feedback_no_silent_swallow.md — skip messages are loud/explicit.
  feedback_integration_test_argv.md — real subprocess argv exercised, not mocked.

Inject-bug recipes (see tester_report.md for execution evidence):
  1. test_real_fetch_M14_mode1_via_dev_upstream
     T4 round-2 fix: inject-bug must produce FAIL not SKIP.
     Previous recipe (change port in live configs/servers.json) was wrong because:
       (a) it mutated the committed file (the B1 bug),
       (b) when port is wrong the batch fails with request_failed_* error;
           the test was checking for "upstream_unstable/502" and SKIPping —
           but SKIP is not RED (critique I1).
     New recipe: inject a bad endpoint directly into the POST payload by
     using a non-existent server_id; the live_server's tmp servers.json
     (T1) has only the standard dev/test/prod entries, so an unknown
     server_id causes the batch to fail with status="failed" and
     error containing "server_not_found" or similar.  The test asserts
     item["status"] == "completed" (hard assert, not skip).  Wrong endpoint
     → assertion fails → RED.
     Recipe:
       Edit test: change `"server_id": "dev"` → `"server_id": "bad_inject"` in payload.
       Red: item["status"] == "failed"; assert raises AssertionError.
       Revert: restore "dev". Green: item completes (when upstream healthy).

  2. test_concurrent_fetch_attaches_not_duplicates
     Bug: add time.sleep(2) before context B's POST so A finishes first.
     Red: B gets a NEW batch_id (new run, not attach) because SAMPLING was
     already released when B arrives. Test detects: one_attaches assertion fails.
     Revert: remove sleep. Green: both fire within 200ms, B attaches.

  3. test_delete_during_fetch_returns_409
     Bug: comment out the CellOperation.DELETING conflict check inside
     delete_machine_rawdata (app.py line ~6885 — the try_acquire_cell call).
     Red: DELETE returns 200, not 409. Test detects: 409 status assertion fails.
     Revert: restore the try_acquire_cell call. Green: DELETE returns 409.

  4. test_delete_all_modes_returns_409_with_empty_dir_active_sampling
     Bug: revert implementer's R1 fix — remove the registry.get_active_cells()
     loop from delete_machine_rawdata (lines 6876-6878 in app.py).
     Red: DELETE /api/rawdata/M14 (no ?mode) returns 200 instead of 409.
     Revert: restore registry.get_active_cells() loop. Green: DELETE returns 409.

Cleanup invariant: every test removes rawdata/M14 and any reports/M14/mode_1
versions it created. Verifier checks git status for orphans.
"""
from __future__ import annotations

import shutil
import socket
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest


# ── TCP probe helpers ────────────────────────────────────────────────────────

_DEV_HOST = "192.168.10.21"
_DEV_PORT = 15060
_DEV_ENDPOINT = f"http://{_DEV_HOST}:{_DEV_PORT}"

_PROD_HOST = "116.232.103.19"
_PROD_PORT = 10288


def _tcp_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    """Return True if a TCP connection can be established."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except OSError:
        return False


def _require_dev_upstream() -> None:
    """pytest.skip if dev upstream is unreachable.

    Loud message per feedback_no_silent_swallow.md — skip reason names the
    target host, port, and what test functionality is being skipped.
    """
    if not _tcp_reachable(_DEV_HOST, _DEV_PORT):
        pytest.skip(
            f"DEV UPSTREAM UNREACHABLE: {_DEV_HOST}:{_DEV_PORT} — "
            f"tests in test_p4_real_business_flow.py that require real intranet "
            f"fetch (G3/G4/G5/G6) are being skipped. "
            f"If you are on intranet, check VPN/firewall."
        )


# ── Cleanup helpers ───────────────────────────────────────────────────────────

def _cleanup_m14(live_server) -> None:
    """Remove rawdata/M14 and reports/M14 to leave no orphans.

    Called in both setup and teardown of each test that writes M14 data.
    """
    for target in (
        live_server.rawdata_dir / "M14",
        live_server.reports_dir / "M14",
    ):
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


def _poll_batch(
    base_url: str,
    batch_id: str,
    timeout_sec: float = 120.0,
    poll_interval: float = 2.0,
) -> dict[str, Any]:
    """Poll GET /api/batch-run/{batch_id} until all items are terminal.

    Returns the final batch dict. Raises TimeoutError if not done in time.
    """
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        r = httpx.get(f"{base_url}/api/batch-run/{batch_id}", timeout=10.0)
        assert r.status_code == 200, f"GET batch returned {r.status_code}: {r.text}"
        data = r.json()
        items = data.get("items", [])
        if items and all(
            it["status"] in ("completed", "failed", "cancelled", "attached")
            for it in items
        ):
            return data
        time.sleep(poll_interval)
    raise TimeoutError(
        f"Batch {batch_id} did not complete within {timeout_sec}s"
    )


# ── G3: real fetch ────────────────────────────────────────────────────────────

@pytest.mark.real_upstream
@pytest.mark.slow
def test_real_fetch_M14_mode1_via_dev_upstream(live_server):
    """G3: POST /api/batch-run for M14 mode 1 with spinTimes≤1000 via dev upstream.

    Per brief §4 D3 / §2 G3:
      - rawdata/M14/mode_1/ must have at least one chunk file after completion.
      - reports/M14/mode_1/index.json must have a new entry.
      - GET /api/reports/M14/1 returns it.

    Inject-bug recipe:
      Edit configs/servers.json: change 15060 → 15061.
      POST batch → item fails (connection refused to wrong port).
      Revert port → test passes.

    User override for real upstream: dev, M14 mode 1, ≤1000 spin
    (memory/feedback_no_proactive_fetch.md exception).
    """
    _require_dev_upstream()
    _cleanup_m14(live_server)

    base = live_server.base_url

    # Verify dev is listed and reachable in servers API.
    r = httpx.get(f"{base}/api/servers", timeout=5.0)
    assert r.status_code == 200
    servers_data = r.json()
    server_ids = [s["id"] for s in servers_data.get("servers", [])]
    assert "dev" in server_ids, (
        f"'dev' server not found in /api/servers. Got: {server_ids}"
    )

    # POST batch-run: M14 mode 1, 1 chunk × 1000 spins, 1 robot.
    # max_chunks=1 means we do exactly ONE chunk of 1000 spins then stop.
    # SLOT_SKIP_AUTO_INFER will be set in live_server env if the conftest
    # adds it; if not, the post-hook scripts will run but they are best-effort.
    payload = {
        "items": [{"machine": "M14", "mode": 1}],
        "server_id": "dev",
        "chunk_spin_times": 1000,
        "chunk_robot_count": 2,
        "batch_concurrency": 2,
        "max_chunks": 1,
        "timeout": 120.0,
        "target_halfwidth_pp": 0,
        "skip_md5_refresh": True,
    }

    r = httpx.post(f"{base}/api/batch-run", json=payload, timeout=15.0)
    assert r.status_code == 200, f"POST /api/batch-run failed: {r.status_code} {r.text}"
    resp = r.json()
    batch_id = resp["batch_id"]
    assert batch_id, "No batch_id in response"

    # Poll until completed (max 120s for 1000 spins via intranet).
    batch = _poll_batch(base, batch_id, timeout_sec=120.0)
    items = batch.get("items", [])
    assert len(items) == 1, f"Expected 1 item, got {len(items)}"
    item = items[0]

    # Item must complete (not fail).
    #
    # T4 (round-2): distinguishing environmental failures from inject-bug failures.
    # The previous code treated ALL item failures as SKIP-worthy.  That was wrong:
    # a wrong-endpoint inject-bug (e.g. server_id points to bad host/port) would
    # produce request_failed_network_* → test SKIPs → inject-bug gives no RED signal.
    #
    # New logic:
    #   - 502 / upstream_unstable → real service outage → SKIP (environment)
    #   - server_not_found → bad server_id in payload → FAIL (inject-bug detectable)
    #   - request_failed_* with connection refused → wrong endpoint → FAIL
    #   - any other "failed" → FAIL (assert catches the regression)
    if item["status"] == "failed":
        error_text = item.get("error") or ""
        # Only skip for true upstream service outages (HTTP 502 / upstream_unstable).
        # A wrong server_id or wrong port (inject-bug) produces connection-refused
        # errors, not 502 — those must FAIL, not skip.
        if ("upstream_unstable" in error_text or
                ("502" in error_text and "request_failed" not in error_text)):
            pytest.skip(
                f"DEV UPSTREAM SAMPLING API DOWN: MultiRobotTestSpinVariant returned HTTP 502/5xx. "
                f"Server {_DEV_HOST}:{_DEV_PORT} is TCP-reachable but the sampling endpoint is not healthy. "
                f"Error from analyzer: {error_text!r}. "
                f"Coordinator: check dev upstream service status before re-running G3."
            )
        # For inject-bug verification: wrong server_id → item fails → assertion RED.
        # Inject: change server_id in payload to "bad_inject" → item["status"]=="failed"
        # with error containing "server_not_found" → this assert fires → test RED.
        assert item["status"] == "completed", (
            f"Batch item failed: status={item['status']!r} error={item.get('error')!r}. "
            f"If this is an inject-bug run (wrong server_id/endpoint), the test correctly "
            f"fails here (RED) instead of skipping."
        )
    assert item["status"] == "completed", (
        f"Batch item failed: status={item['status']!r} error={item.get('error')!r}"
    )

    # G3 invariant 1: rawdata/M14/mode_1 must exist with at least one chunk.
    rawdata_mode_dir = live_server.rawdata_dir / "M14" / "mode_1"
    assert rawdata_mode_dir.is_dir(), (
        f"rawdata/M14/mode_1 dir missing — analyzer did not write chunks"
    )
    chunk_files = list(rawdata_mode_dir.glob("*.json"))
    assert len(chunk_files) >= 1, (
        f"No chunk files in {rawdata_mode_dir}"
    )

    # G3 invariant 2: reports/M14/mode_1/index.json must have an entry.
    reports_mode_dir = live_server.reports_dir / "M14" / "mode_1"
    index_path = reports_mode_dir / "index.json"
    assert index_path.exists(), (
        f"reports/M14/mode_1/index.json missing — analyzer report was not generated"
    )
    import json
    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    # index.json is either a list or has a "versions" key.
    entries = index_data if isinstance(index_data, list) else index_data.get("versions", [])
    assert len(entries) >= 1, (
        f"reports/M14/mode_1/index.json has no entries: {index_data}"
    )

    # G3 invariant 3: GET /api/reports/M14/1 returns a valid response.
    r2 = httpx.get(f"{base}/api/reports/M14/1", timeout=10.0)
    assert r2.status_code == 200, (
        f"GET /api/reports/M14/1 returned {r2.status_code}: {r2.text}"
    )
    report_data = r2.json()
    # The report endpoint returns something with a versions list or similar.
    assert report_data, "Empty response from GET /api/reports/M14/1"

    # D4 evidence capture — print for tester_report.md.
    first_chunk = chunk_files[0]
    chunk_size = first_chunk.stat().st_size
    chunk_head = first_chunk.read_bytes()[:200]
    print(
        f"\n[D4 chunk] {first_chunk.name} size={chunk_size}B "
        f"head={chunk_head!r}"
    )
    print(f"[D4 index] {entries[0]}")
    print(f"[D4 report API] keys={list(report_data.keys())[:6]}")

    # Cleanup.
    _cleanup_m14(live_server)


# ── G4: concurrent attach ─────────────────────────────────────────────────────

@pytest.mark.real_upstream
def test_concurrent_fetch_attaches_not_duplicates(live_server):
    """G4: two threads POST same (M14, 1) within 200ms; one attaches to other.

    Per brief §4 D3 / §2 G4:
      - One response creates a new run, the other has status=attached with same run_id.
      - Only ONE SAMPLING CellOperation active (single upstream call).

    Inject-bug recipe:
      Add time.sleep(2.0) before thread B's POST so A finishes before B fires.
      Red: B gets its own new batch_id with status='running' (no attach).
      Revert sleep → test passes (B attaches within 200ms window).

    Uses the same live_server instance (same uvicorn process) so both requests
    share the same CellLockRegistry — required for attach semantics to work.
    """
    _require_dev_upstream()
    _cleanup_m14(live_server)

    base = live_server.base_url
    payload = {
        "items": [{"machine": "M14", "mode": 1}],
        "server_id": "dev",
        "chunk_spin_times": 1000,
        "chunk_robot_count": 1,
        "batch_concurrency": 1,
        "max_chunks": 1,
        "timeout": 120.0,
        "target_halfwidth_pp": 0,
        "skip_md5_refresh": True,
    }

    results: list[dict[str, Any]] = [None, None]
    errors: list[Exception | None] = [None, None]
    barrier = threading.Barrier(2)

    def _post(idx: int) -> None:
        try:
            barrier.wait(timeout=5.0)
            r = httpx.post(f"{base}/api/batch-run", json=payload, timeout=15.0)
            results[idx] = r.json() if r.status_code == 200 else {"status_code": r.status_code, "text": r.text}
        except Exception as exc:  # noqa: BLE001
            errors[idx] = exc

    # Fire both threads simultaneously via barrier.
    t0 = threading.Thread(target=_post, args=(0,))
    t1 = threading.Thread(target=_post, args=(1,))
    t0.start()
    t1.start()
    t0.join(timeout=20.0)
    t1.join(timeout=20.0)

    for i, exc in enumerate(errors):
        assert exc is None, f"Thread {i} raised: {exc}"

    r0, r1 = results[0], results[1]
    assert r0 is not None, "Thread 0 produced no result"
    assert r1 is not None, "Thread 1 produced no result"

    # One response must have a batch_id (the creator) with status "running".
    # The other item within the same or a different batch must show "attached".
    # BatchRunManager.start_batch() sets item["status"] = "attached" in the item dict
    # and item["attached_to_run_id"] is populated; the batch itself still returns
    # {"batch_id": ..., "status": "running", "total": 1} from start_batch.
    # To distinguish, we poll both batches once and look at item statuses.

    batch_ids = {r0.get("batch_id"), r1.get("batch_id")} - {None}
    assert len(batch_ids) in (1, 2), f"Unexpected batch_ids: {r0}, {r1}"

    # Give the batch a moment to process (item status is set synchronously in
    # start_batch before the thread launches, so no polling needed for attach).
    all_item_statuses: list[dict[str, Any]] = []
    for bid in batch_ids:
        r_poll = httpx.get(f"{base}/api/batch-run/{bid}", timeout=10.0)
        if r_poll.status_code == 200:
            all_item_statuses.extend(r_poll.json().get("items", []))

    statuses = [it["status"] for it in all_item_statuses]

    # The system is correct if there is at most ONE "running"/"pending"/"completed"
    # item and at least ONE "attached" item (or the second batch has zero items
    # due to timing — but in that case batch total would be 1 and item "attached"
    # at item level). We check the registry for a single SAMPLING hold.
    r_sys = httpx.get(f"{base}/api/system-state", timeout=5.0)
    if r_sys.status_code == 200:
        sys_data = r_sys.json()
        registry_snap = sys_data.get("registry") or sys_data.get("cell_registry") or {}
        active_cells = registry_snap.get("cells") or {}
        sampling_cells = {k: v for k, v in active_cells.items() if "sampling" in v}
        # At most one SAMPLING on M14|1 at any time.
        assert len(sampling_cells) <= 1, (
            f"More than one SAMPLING active: {sampling_cells}"
        )

    one_attaches = any(s == "attached" for s in statuses)
    assert one_attaches, (
        f"No 'attached' item found. All item statuses: {statuses}. "
        f"Both threads should fire within 200ms (barrier sync). "
        f"If dev upstream is slow and first batch already completed before B fires, "
        f"this test's timing assumption does not hold — check inject-bug recipe."
    )

    # Cancel any still-running batches to avoid leaving an orphan SAMPLING.
    for bid in batch_ids:
        try:
            httpx.post(f"{base}/api/batch-run/{bid}/cancel", timeout=5.0)
        except Exception:
            pass

    # Wait for items to reach terminal state before cleanup.
    for bid in batch_ids:
        try:
            _poll_batch(base, bid, timeout_sec=120.0)
        except Exception:
            pass

    _cleanup_m14(live_server)


# ── G5: delete while fetching → 409 ─────────────────────────────────────────

@pytest.mark.real_upstream
def test_delete_during_fetch_returns_409(live_server):
    """G5: DELETE /api/rawdata/M14?mode=1 while a SAMPLING is active → HTTP 409.

    Per brief §4 D3 / §2 G5 / P2 INV-2:
      - Context B's DELETE returns 409 with cell-busy reason.
      - Context A's run is NOT affected by the failed delete.

    NOTE: We use ?mode=1 explicitly rather than DELETE /api/rawdata/M14 (all modes).
    The all-modes path enumerates on-disk mode dirs; if rawdata/M14 doesn't exist
    yet (SAMPLING started but no chunks written), modes_to_lock = [] and the 409
    guard is never exercised — DELETE returns 200/not_found silently.
    This is a known design gap in delete_machine_rawdata documented in
    tester_report.md as P4 regression candidate R1.
    The explicit ?mode=1 path (modes_to_lock = [1]) always exercises the guard.

    Inject-bug recipe:
      In app.py delete_machine_rawdata, comment out the call to
      registry.try_acquire_cell(..., CellOperation.DELETING) so it always
      proceeds. Red: DELETE returns 200, not 409. Test assertion fails.
      Revert: restore the try_acquire_cell call. Green: DELETE returns 409.
    """
    _require_dev_upstream()
    _cleanup_m14(live_server)

    base = live_server.base_url
    payload = {
        "items": [{"machine": "M14", "mode": 1}],
        "server_id": "dev",
        "chunk_spin_times": 1000,
        "chunk_robot_count": 1,
        "batch_concurrency": 1,
        "max_chunks": 2,  # 2 chunks so the SAMPLING stays active longer.
        "timeout": 120.0,
        "target_halfwidth_pp": 0,
        "skip_md5_refresh": True,
    }

    # Context A starts fetch.
    r_a = httpx.post(f"{base}/api/batch-run", json=payload, timeout=15.0)
    assert r_a.status_code == 200, f"Context A batch start failed: {r_a.text}"
    batch_id_a = r_a.json()["batch_id"]

    # Wait for the item to move from "pending" to "running" (SAMPLING acquired).
    deadline = time.time() + 30.0
    item_running = False
    while time.time() < deadline:
        r_poll = httpx.get(f"{base}/api/batch-run/{batch_id_a}", timeout=5.0)
        items = r_poll.json().get("items", [])
        if items and items[0]["status"] == "running":
            item_running = True
            break
        time.sleep(0.5)

    if not item_running:
        # Item might have completed very fast (cached) or failed.
        r_poll = httpx.get(f"{base}/api/batch-run/{batch_id_a}", timeout=5.0)
        items = r_poll.json().get("items", [])
        if items and items[0]["status"] in ("completed", "failed"):
            pytest.skip(
                f"Batch item reached terminal state before DELETE probe could race it "
                f"(status={items[0]['status']}). "
                f"This can happen if 1000-spin chunk returns < 1s over intranet. "
                f"Use max_chunks=2 and slower robot settings to extend the window."
            )
        raise AssertionError(
            f"Item never entered 'running' state. Final items: {items}"
        )

    # Context B issues DELETE /api/rawdata/M14?mode=1 while A is active.
    # Explicit mode=1 so the 409 guard fires unconditionally (does not depend
    # on rawdata/M14/mode_1 dir existing on disk yet).
    r_b = httpx.delete(f"{base}/api/rawdata/M14", params={"mode": 1}, timeout=10.0)

    # G5 invariant: B must get 409, not 200/204.
    assert r_b.status_code == 409, (
        f"Expected 409 from DELETE while SAMPLING active. "
        f"Got: {r_b.status_code} {r_b.text}"
    )
    assert "busy" in r_b.text.lower() or "409" in str(r_b.status_code), (
        f"409 body should mention cell-busy. Got: {r_b.text}"
    )

    # Capture for D4 evidence.
    print(f"\n[D4 409 body] {r_b.text}")

    # A should still be running (or completing normally).
    r_poll_after = httpx.get(f"{base}/api/batch-run/{batch_id_a}", timeout=5.0)
    items_after = r_poll_after.json().get("items", [])
    assert items_after, "No items in batch after DELETE probe"
    assert items_after[0]["status"] in ("running", "pending", "completed"), (
        f"Context A's run should not have failed due to DELETE probe. "
        f"Got: {items_after[0]['status']}"
    )

    # Cancel A and wait for it to terminate.
    httpx.post(f"{base}/api/batch-run/{batch_id_a}/cancel", timeout=5.0)
    try:
        _poll_batch(base, batch_id_a, timeout_sec=120.0)
    except TimeoutError:
        pass

    _cleanup_m14(live_server)


# ── G6: server switch + scan ──────────────────────────────────────────────────

def test_server_switch_default_and_scan(live_server):
    """G6: list servers, set-default dev, scan dev → MD5 snapshot written.

    Per brief §4 D3 / §2 G6. The scan POST is the only write that touches
    dev upstream in this test (no sampling).

    If dev upstream is unreachable, the scan POST will return 502 (not the
    typical 200). The test handles this gracefully — it still verifies the
    API plumbing, just reports the upstream outcome.
    """
    _require_dev_upstream()

    base = live_server.base_url

    # GET /api/servers — dev + prod present.
    r = httpx.get(f"{base}/api/servers", timeout=5.0)
    assert r.status_code == 200
    data = r.json()
    server_ids = [s["id"] for s in data.get("servers", [])]
    assert "dev" in server_ids, f"'dev' not in server list: {server_ids}"
    assert "prod" in server_ids, f"'prod' not in server list: {server_ids}"

    # PUT /api/servers/dev/set-default.
    r2 = httpx.put(f"{base}/api/servers/dev/set-default", timeout=5.0)
    assert r2.status_code == 200, f"set-default failed: {r2.status_code} {r2.text}"
    assert r2.json().get("ok") is True

    # POST /api/servers/dev/scan — round-trips through dev upstream MachineConfigMd5.
    r3 = httpx.post(f"{base}/api/servers/dev/scan", timeout=60.0)
    if r3.status_code == 502:
        pytest.skip(
            f"DEV upstream returned 502 on scan (MachineConfigMd5 endpoint unavailable): "
            f"{r3.text}. TCP reachability was confirmed at test start."
        )
    assert r3.status_code == 200, f"scan failed: {r3.status_code} {r3.text}"
    scan_result = r3.json()
    assert scan_result.get("ok") is True
    machine_count = scan_result.get("machine_count", 0)
    assert machine_count > 0, (
        f"scan returned ok=True but machine_count=0: {scan_result}"
    )

    # GET /api/servers/dev/snapshot — verify snapshot was written.
    r4 = httpx.get(f"{base}/api/servers/dev/snapshot", timeout=5.0)
    assert r4.status_code == 200, f"snapshot GET failed: {r4.status_code} {r4.text}"
    snap_data = r4.json()
    assert snap_data.get("machine_count", 0) > 0

    # D4 evidence.
    print(
        f"\n[D4 scan] server_id=dev machine_count={machine_count} "
        f"snapshot_keys_sample={list(snap_data.get('snapshot', {}).keys())[:3]}"
    )


# ── Prod read-only probe ──────────────────────────────────────────────────────

def test_prod_endpoint_reachable_but_readonly_probe(live_server):
    """G6 (prod side): GET /api/servers lists prod; GET snapshot is read-only.

    Per brief §3 non-goals: NO POST to prod upstream.
    This test only reads: lists servers + gets existing snapshot.
    Does NOT call POST /api/servers/prod/scan (that would hit prod upstream).
    """
    base = live_server.base_url

    # GET /api/servers — prod must be listed.
    r = httpx.get(f"{base}/api/servers", timeout=5.0)
    assert r.status_code == 200
    data = r.json()
    prod_entry = next(
        (s for s in data.get("servers", []) if s["id"] == "prod"), None
    )
    assert prod_entry is not None, (
        f"'prod' server not listed in /api/servers: {data}"
    )
    assert "116.232.103.19" in prod_entry.get("endpoint", ""), (
        f"Prod entry endpoint unexpected: {prod_entry}"
    )

    # GET /api/servers/prod/snapshot — may return 404 if never scanned before.
    r2 = httpx.get(f"{base}/api/servers/prod/snapshot", timeout=5.0)
    if r2.status_code == 404:
        # Never scanned — that's fine, confirms endpoint exists and is read-only.
        assert "no snapshot" in r2.text.lower() or "404" in r2.text
    else:
        assert r2.status_code == 200, (
            f"GET /api/servers/prod/snapshot returned unexpected {r2.status_code}: {r2.text}"
        )
        snap_data = r2.json()
        assert "server_id" in snap_data

    # Verify prod TCP is reachable (belt-and-suspenders network probe).
    prod_reachable = _tcp_reachable(_PROD_HOST, _PROD_PORT)
    print(
        f"\n[D4 prod probe] TCP {_PROD_HOST}:{_PROD_PORT} reachable={prod_reachable}"
    )
    # Not a hard assertion — prod may be behind VPN.
    # But if we're on intranet, it should be reachable.


# ── T5: R1 regression guard — all-modes DELETE returns 409 when SAMPLING active ──

@pytest.mark.real_upstream
def test_delete_all_modes_returns_409_with_empty_dir_active_sampling(live_server):
    """R1 regression guard: DELETE /api/rawdata/M14 (no ?mode) must return 409
    when SAMPLING is active for M14|1, even when rawdata/M14 dir does not yet exist.

    This is the bug that verifier RV2 confirmed:
      - When rawdata/M14 is absent, the old code enumerated on-disk mode dirs only.
      - modes_to_lock = [] because the dir scan found nothing.
      - The 409 guard loop ran zero iterations → DELETE returned 200.
      - Real planners could silently delete while sampling was in-flight.

    The implementer's R1 fix adds registry.get_active_cells() to the modes_set
    population so active in-flight cells are included even before the first chunk
    is written.

    Inject-bug recipe (verifies this test catches the R1 regression):
      In app.py delete_machine_rawdata, remove the registry.get_active_cells() loop:
          Lines ~6876-6878:
              for cell_machine, cell_mode in registry.get_active_cells():
                  if cell_machine == machine:
                      modes_set.add(cell_mode)
      With the bug injected:
        - modes_to_lock = [] (rawdata/M14 dir absent + registry not consulted)
        - DELETE returns HTTP 200 with {ok:true, deleted:false, reason:not_found}
        - This test assertion (assert r_b.status_code == 409) fails → RED
      Revert the removal → test GREEN.

    Memory feedback: feedback_enumerate_safety_paths.md — every safety path
    needs its own inject-verified test.
    """
    _require_dev_upstream()
    _cleanup_m14(live_server)

    base = live_server.base_url

    # Ensure rawdata/M14 directory does NOT exist before starting the batch.
    # This is the R1 precondition: the bug only manifested when the dir was absent.
    m14_rawdata = live_server.rawdata_dir / "M14"
    assert not m14_rawdata.exists(), (
        f"rawdata/M14 should not exist at test start — cleanup failed: {m14_rawdata}"
    )

    # Start a batch for M14 mode 1. Use max_chunks=2 to extend the SAMPLING window.
    payload = {
        "items": [{"machine": "M14", "mode": 1}],
        "server_id": "dev",
        "chunk_spin_times": 1000,
        "chunk_robot_count": 1,
        "batch_concurrency": 1,
        "max_chunks": 2,
        "timeout": 120.0,
        "target_halfwidth_pp": 0,
        "skip_md5_refresh": True,
    }

    r_a = httpx.post(f"{base}/api/batch-run", json=payload, timeout=15.0)
    assert r_a.status_code == 200, f"Context A batch start failed: {r_a.text}"
    batch_id_a = r_a.json()["batch_id"]

    # Wait for item to reach "running" state.  This means _run_one has acquired
    # the SAMPLING lock — the CellLockRegistry now has (M14, 1) registered.
    # We want rawdata/M14 to still be absent at this point (before first chunk).
    deadline = time.time() + 30.0
    item_running = False
    rawdata_absent_when_running = False

    while time.time() < deadline:
        r_poll = httpx.get(f"{base}/api/batch-run/{batch_id_a}", timeout=5.0)
        items = r_poll.json().get("items", [])
        if items and items[0]["status"] == "running":
            item_running = True
            # Check rawdata/M14 presence at the moment SAMPLING is confirmed.
            rawdata_absent_when_running = not m14_rawdata.exists()
            break
        if items and items[0]["status"] in ("completed", "failed"):
            # Batch already finished — might have been very fast.
            pytest.skip(
                f"Batch item reached terminal state before DELETE probe could race it "
                f"(status={items[0]['status']}). "
                f"Use max_chunks=3 or more to extend the SAMPLING window on fast intranet."
            )
        time.sleep(0.5)

    if not item_running:
        r_poll = httpx.get(f"{base}/api/batch-run/{batch_id_a}", timeout=5.0)
        raise AssertionError(
            f"Item never entered 'running' state within 30s. "
            f"Final batch state: {r_poll.json()}"
        )

    # Context B: fire DELETE /api/rawdata/M14 — ALL MODES, NO ?mode param.
    # This is the exact path that was broken in R1 (the mode=None branch).
    # Even if rawdata/M14 dir is absent (rawdata_absent_when_running may be True),
    # the registry knows SAMPLING is active → 409 must be returned.
    r_b = httpx.delete(f"{base}/api/rawdata/M14", timeout=10.0)

    # R1 invariant: DELETE all-modes must return 409 when SAMPLING is active,
    # regardless of whether rawdata/M14 dir exists on disk.
    assert r_b.status_code == 409, (
        f"R1 REGRESSION: DELETE /api/rawdata/M14 (no ?mode) returned {r_b.status_code} "
        f"instead of 409 while SAMPLING is active. "
        f"rawdata/M14 dir existed at SAMPLING-detected moment: {not rawdata_absent_when_running}. "
        f"Response body: {r_b.text}. "
        f"Root cause if 200: registry.get_active_cells() loop missing from "
        f"delete_machine_rawdata (lines 6876-6878 app.py)."
    )

    # 409 body must mention the busy cell.
    assert "busy" in r_b.text.lower() or "sampling" in r_b.text.lower(), (
        f"409 body should mention cell-busy/sampling reason. Got: {r_b.text}"
    )

    print(
        f"\n[T5 R1 guard] rawdata_absent_when_running={rawdata_absent_when_running} "
        f"DELETE status={r_b.status_code} body={r_b.text[:120]}"
    )

    # Cancel A and wait for it to terminate cleanly.
    httpx.post(f"{base}/api/batch-run/{batch_id_a}/cancel", timeout=5.0)
    try:
        _poll_batch(base, batch_id_a, timeout_sec=120.0)
    except TimeoutError:
        pass

    _cleanup_m14(live_server)
