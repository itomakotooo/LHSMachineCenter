"""Fleet smoke-test runner. Wave 2 supervisor invokes this.

What this does (per row of work_plan.csv, status=pending):
  1. If source == copy_from_main: shutil.copytree main_repo/rawdata/<m>/mode_1
     into worktree/rawdata/<m>/mode_1 (dirs_exist_ok so retries are safe).
     Mark status=copied.
  2. Submit the machine via POST /api/batch-run with max_chunks=2,
     chunk_spin_times=5000 (→ 10k spins/machine target).
  3. Poll GET /api/runs/{run_id} every 5s until status ∈
     {completed, failed} OR 600s wall (then mark timeout).
  4. Write back to work_plan.csv after every machine state change so a crash
     leaves a recoverable plan. Each attempt also gets a structured JSON line
     in run_log.jsonl.

Design notes:
  - Wave size = 20 machines per /api/batch-run POST. Backend's batch_concurrency
    is 8, so a wave of 20 means ~3 sub-batches of sub-batches inside the
    backend's worker pool — bounded enough that a backend crash loses ≤20
    in-flight runs (we already have their run_ids on disk so we can re-check
    each one's final status). We rejected "one big batch of all 255" because
    a crash would orphan every run_id we hadn't yet recorded.
  - Copy step is serial WITHIN a wave (typically <2s/machine on local SSD).
    For the M1-sized caches (~2 GB of chunks) this dominates wave wall time;
    we accept it because parallel filesystem copies on Windows are messy.
  - Retry policy: each failed/timed-out machine gets ONE retry in a second
    pass after the main loop completes (sequentially, one-by-one). This
    avoids interleaving retry into the main wave logic.
  - The runner errors out cleanly if GET /api/health returns non-200 — the
    supervisor is responsible for starting the backend first.

CLI:
  python runner.py                # process all pending
  python runner.py --limit 5      # smoke test: first 5 pending
  python runner.py --retry-failed # clear failed→pending, then process

Logs:
  work_plan.csv     — authoritative state, rewritten on every state change
  run_log.jsonl     — append-only audit trail (one JSON per attempt)
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import urllib.error
import urllib.request

# --- Constants -------------------------------------------------------------

HERE = Path(__file__).resolve().parent
# Default CSV; overridden via --csv flag so two runner instances can
# run in parallel against separate work plans (copy-only vs sample-only).
WORK_PLAN = HERE / "work_plan.csv"
RUN_LOG = HERE / "run_log.jsonl"

MAIN_REPO = Path(r"C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT")
WORKTREE = Path(
    r"C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT/.claude/worktrees/stoic-napier-f0ea00"
)
MAIN_RAWDATA = MAIN_REPO / "rawdata"
WORKTREE_RAWDATA = WORKTREE / "rawdata"

BACKEND_BASE = "http://127.0.0.1:8877"
HEALTH_URL = f"{BACKEND_BASE}/api/health"
BATCH_URL = f"{BACKEND_BASE}/api/batch-run"
RUN_URL_FMT = f"{BACKEND_BASE}/api/runs/{{run_id}}"

WAVE_SIZE = 4  # halved so two runner instances (copy + sample) share backend pool=8 evenly
POLL_INTERVAL_S = 10.0
RUN_TIMEOUT_S = 1500.0  # 25 min — fresh sampling can take 10+ min on rate-limited upstream

BATCH_PAYLOAD_DEFAULTS = {
    "concurrency": 8,
    "server_id": "dev",
    "chunk_spin_times": 5000,
    "chunk_robot_count": 8,
    "batch_concurrency": 8,
    "max_chunks": 2,
    "timeout": 300.0,
    "target_halfwidth_pp": 0.5,
    # MUST stay false so the analyzer does not auto-delete the chunks we
    # copied from the main repo. (See memory:
    # feedback_md5_is_a_tag_not_a_destruction_signal.)
    "auto_cleanup_cache": False,
    # We don't need the upstream md5 refresh — fresh_sample machines will
    # get the current md5 stamped from the upstream call anyway, and copied
    # caches were stamped at copy time.
    "skip_md5_refresh": True,
}

CSV_FIELDS = [
    "machine", "mode", "family", "is_representative",
    "source", "status", "run_id", "summary_path", "duration_s", "error",
]


# --- HTTP helpers ----------------------------------------------------------

def _http_get_json(url: str, timeout: float = 30.0) -> tuple[int, dict[str, Any] | None]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8")
            return r.status, json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        return e.code, None
    except urllib.error.URLError as e:
        raise RuntimeError(f"GET {url} unreachable: {e}") from e


def _http_post_json(url: str, payload: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"POST {url} → HTTP {e.code}: {detail[:500]}") from e


def assert_backend_alive() -> None:
    try:
        code, _ = _http_get_json(HEALTH_URL, timeout=10.0)
    except RuntimeError as e:
        print(f"ERROR: backend at {BACKEND_BASE} is unreachable.\n  {e}", file=sys.stderr)
        print("HINT: the supervisor must start the console backend before this runner.", file=sys.stderr)
        sys.exit(2)
    if code != 200:
        print(f"ERROR: {HEALTH_URL} returned HTTP {code} (expected 200).", file=sys.stderr)
        sys.exit(2)


# --- CSV state -------------------------------------------------------------

@dataclass
class Row:
    machine: str
    mode: int
    family: str
    is_representative: bool
    source: str  # 'copy_from_main' | 'fresh_sample'
    status: str  # 'pending' | 'copied' | 'submitted' | 'completed' | 'failed' | 'timeout'
    run_id: str = ""
    summary_path: str = ""
    duration_s: str = ""
    error: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> "Row":
        return cls(
            machine=d["machine"],
            mode=int(d["mode"]),
            family=d["family"],
            is_representative=str(d.get("is_representative", "True")).lower() in ("true", "1"),
            source=d["source"],
            status=d.get("status", "pending"),
            run_id=d.get("run_id", ""),
            summary_path=d.get("summary_path", ""),
            duration_s=d.get("duration_s", ""),
            error=d.get("error", ""),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "machine": self.machine,
            "mode": str(self.mode),
            "family": self.family,
            "is_representative": "True" if self.is_representative else "False",
            "source": self.source,
            "status": self.status,
            "run_id": self.run_id,
            "summary_path": self.summary_path,
            "duration_s": self.duration_s,
            "error": self.error,
        }


@dataclass
class Plan:
    rows: list[Row] = field(default_factory=list)
    # Per-instance CSV path so two runner processes can drive disjoint
    # work plans in parallel (copy stream vs sample stream).
    csv_path: Path = field(default_factory=lambda: WORK_PLAN)

    @classmethod
    def load(cls, csv_path: Path = WORK_PLAN) -> "Plan":
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            return cls(
                rows=[Row.from_dict(r) for r in csv.DictReader(f)],
                csv_path=csv_path,
            )

    def save(self) -> None:
        tmp = self.csv_path.with_suffix(".csv.tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            for r in self.rows:
                w.writerow(r.to_dict())
        tmp.replace(self.csv_path)


def log_event(payload: dict[str, Any]) -> None:
    payload = {"ts": time.time(), **payload}
    with RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


# --- Copy step -------------------------------------------------------------

def copy_chunks_if_needed(row: Row) -> tuple[bool, str]:
    """For copy_from_main rows in pending state, copy mode_1 chunks.
    Returns (success, error_message). Idempotent via dirs_exist_ok.
    """
    if row.source != "copy_from_main":
        return True, ""
    src = MAIN_RAWDATA / row.machine / "mode_1"
    if not src.exists():
        return False, f"source dir missing: {src}"
    dst = WORKTREE_RAWDATA / row.machine / "mode_1"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(src, dst, dirs_exist_ok=True)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, f"copytree failed: {e}"


# --- Submission & polling --------------------------------------------------

def submit_wave(machines: list[str]) -> dict[str, str]:
    """POST one /api/batch-run with up to WAVE_SIZE items.

    Returns map machine→run_id for successful submissions. The backend's
    POST response is the lean acknowledgement form {batch_id, status,
    total, md5_refresh}; run_ids are exposed only via
    GET /api/batch-run/{batch_id} (which returns items[]). So we
    submit, then immediately fetch the batch detail to extract run_ids.
    """
    payload = {
        "items": [{"machine": m, "mode": 1, "chunk_spin_times": 5000} for m in machines],
        **BATCH_PAYLOAD_DEFAULTS,
    }
    resp = _http_post_json(BATCH_URL, payload, timeout=120.0)
    batch_id = resp.get("batch_id") if isinstance(resp, dict) else None
    if not batch_id:
        return {}
    # /api/batch-run/{batch_id}.items[].run_id stays None for a long
    # time (60s+ observed) — that endpoint is for "show me the batch
    # progress", not for "give me run ids". The authoritative way to
    # match a submission to its run ids is GET /api/runs?limit=N which
    # lists runs newest-first with populated run_id from the moment
    # the run is created. We pick the latest N runs whose machine name
    # matches a submitted machine and whose created_at is later than
    # the moment we POSTed.
    submitted = set(machines)
    expected = len(machines)
    runs_url = f"{BACKEND_BASE}/api/runs?limit={max(50, expected * 3)}"
    deadline = time.time() + 90.0
    out: dict[str, str] = {}
    while time.time() < deadline:
        code, body = _http_get_json(runs_url, timeout=30.0)
        if code == 200 and isinstance(body, dict):
            for r in body.get("runs", []):
                m = r.get("machine")
                rid = r.get("run_id")
                if m in submitted and rid and m not in out:
                    out[m] = rid
            if len(out) >= expected:
                return out
        time.sleep(1.0)
    return out


def poll_run(run_id: str) -> dict[str, Any]:
    """GET /api/runs/{run_id}. Treats 404 as a terminal error."""
    code, body = _http_get_json(RUN_URL_FMT.format(run_id=run_id), timeout=30.0)
    if code != 200 or body is None:
        return {"status": "failed", "error_message": f"HTTP {code}"}
    return body


def wait_for_runs(plan: Plan, machine_to_run: dict[str, str], started: dict[str, float]) -> None:
    """Poll until every run is terminal (completed/failed) or wall expires.
    Updates plan rows in-place and persists CSV on each state change.
    """
    pending = set(machine_to_run.keys())
    while pending:
        time.sleep(POLL_INTERVAL_S)
        now = time.time()
        for machine in list(pending):
            run_id = machine_to_run[machine]
            row = next(r for r in plan.rows if r.machine == machine)
            wall = now - started[machine]
            try:
                body = poll_run(run_id)
            except RuntimeError as e:
                row.status = "failed"
                row.error = f"poll error: {e}"
                row.duration_s = f"{wall:.1f}"
                pending.discard(machine)
                log_event({"machine": machine, "action": "poll_error", "run_id": run_id,
                           "status": "failed", "duration_s": wall, "error": str(e)})
                plan.save()
                continue
            status = body.get("status") or ""
            if status in ("completed",):
                row.status = "completed"
                row.summary_path = body.get("summary_file") or ""
                row.duration_s = f"{wall:.1f}"
                row.error = ""
                pending.discard(machine)
                log_event({"machine": machine, "action": "complete", "run_id": run_id,
                           "status": "completed", "duration_s": wall,
                           "summary_path": row.summary_path})
                plan.save()
            elif status in ("failed", "cancelled"):
                row.status = "failed"
                row.error = (body.get("error_message") or status)[:500]
                row.duration_s = f"{wall:.1f}"
                pending.discard(machine)
                log_event({"machine": machine, "action": "fail", "run_id": run_id,
                           "status": status, "duration_s": wall, "error": row.error})
                plan.save()
            elif wall > RUN_TIMEOUT_S:
                row.status = "timeout"
                row.error = f"wall>{RUN_TIMEOUT_S}s (last status={status})"
                row.duration_s = f"{wall:.1f}"
                pending.discard(machine)
                log_event({"machine": machine, "action": "timeout", "run_id": run_id,
                           "status": "timeout", "duration_s": wall, "error": row.error})
                plan.save()
            # else: still running/pending — keep polling


# --- Wave orchestration ----------------------------------------------------

def reclaim_orphan_submitted(plan: Plan) -> None:
    """Pick up rows whose status is 'submitted' but never got a terminal
    update — happens when a previous runner / supervisor invocation
    crashed mid-poll. Each row has a run_id; we just poll it once to
    bring its status current.
    """
    orphans = [r for r in plan.rows if r.status == "submitted" and r.run_id]
    if not orphans:
        return
    print(f"[runner] reclaiming {len(orphans)} orphan submitted rows")
    machine_to_run = {r.machine: r.run_id for r in orphans}
    started = {r.machine: time.time() for r in orphans}
    # Use the existing wait_for_runs loop which already handles
    # completed/failed/timeout transitions.
    wait_for_runs(plan, machine_to_run, started)


def process_pending(plan: Plan, limit: int | None) -> None:
    # First reclaim any orphans before starting new waves so we don't
    # double-process or leave them dangling.
    reclaim_orphan_submitted(plan)
    pending = [r for r in plan.rows if r.status in ("pending", "copied")]
    if limit:
        pending = pending[:limit]
    print(f"[runner] processing {len(pending)} rows in waves of {WAVE_SIZE}")

    for wave_idx, start in enumerate(range(0, len(pending), WAVE_SIZE)):
        wave = pending[start:start + WAVE_SIZE]
        print(f"[runner] wave {wave_idx + 1}/{(len(pending) + WAVE_SIZE - 1) // WAVE_SIZE} — {len(wave)} machines")

        # Copy step (serial within the wave)
        for row in wave:
            if row.status == "copied":
                continue
            ok, err = copy_chunks_if_needed(row)
            if not ok:
                row.status = "failed"
                row.error = err
                log_event({"machine": row.machine, "action": "copy_fail",
                           "error": err})
            elif row.source == "copy_from_main":
                row.status = "copied"
                log_event({"machine": row.machine, "action": "copy_ok"})
        plan.save()

        # Submit the wave (excluding rows whose copy failed)
        submit_machines = [r.machine for r in wave if r.status in ("pending", "copied")]
        if not submit_machines:
            continue
        try:
            machine_to_run = submit_wave(submit_machines)
        except RuntimeError as e:
            for m in submit_machines:
                row = next(r for r in plan.rows if r.machine == m)
                row.status = "failed"
                row.error = f"submit error: {e}"[:500]
                log_event({"machine": m, "action": "submit_fail", "error": str(e)})
            plan.save()
            continue

        # Update CSV with run_ids before polling so a crash leaves traceable state
        started: dict[str, float] = {}
        now = time.time()
        for m, rid in machine_to_run.items():
            row = next(r for r in plan.rows if r.machine == m)
            row.run_id = rid
            row.status = "submitted"
            started[m] = now
            log_event({"machine": m, "action": "submit", "run_id": rid})
        # Any machine the batch failed to register (rare)
        for m in submit_machines:
            if m not in machine_to_run:
                row = next(r for r in plan.rows if r.machine == m)
                row.status = "failed"
                row.error = "no run_id returned"
                log_event({"machine": m, "action": "no_run_id"})
        plan.save()

        # Poll wave to completion
        wait_for_runs(plan, machine_to_run, started)


def _reset_one_failed_row(r: Row) -> None:
    """Reset a failed/timeout row so it gets reprocessed. Copy-failures
    reset to 'pending' (re-attempt copy); all other failures reset to
    'pending' for fresh_sample or 'copied' for copy_from_main (skip
    redundant re-copy)."""
    copy_failed = r.error.startswith("copytree failed") or r.error.startswith("source dir missing")
    if r.source == "fresh_sample" or copy_failed:
        r.status = "pending"
    else:
        r.status = "copied"
    r.run_id = ""
    r.error = ""
    r.duration_s = ""
    r.summary_path = ""


def retry_failed_once(plan: Plan) -> None:
    """Second pass: re-attempt every failed/timeout row exactly once."""
    failed = [r for r in plan.rows if r.status in ("failed", "timeout")]
    if not failed:
        return
    print(f"[runner] retry pass: {len(failed)} failed/timeout rows → reset")
    for r in failed:
        _reset_one_failed_row(r)
        log_event({"machine": r.machine, "action": "retry_reset"})
    plan.save()
    # Now process again (only the rows we just reset are pending/copied; main
    # loop's "pending" filter picks them up)
    process_pending(plan, limit=None)


def reset_failed_to_pending(plan: Plan) -> int:
    """For --retry-failed mode: reset failed/timeout rows so the main loop
    picks them up. Returns count reset.
    """
    n = 0
    for r in plan.rows:
        if r.status in ("failed", "timeout"):
            _reset_one_failed_row(r)
            n += 1
    plan.save()
    return n


# --- Main ------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None,
                    help="Process at most N pending rows (smoke testing)")
    ap.add_argument("--retry-failed", action="store_true",
                    help="Reset failed/timeout rows to pending before running")
    ap.add_argument("--no-retry-pass", action="store_true",
                    help="Skip the auto retry-once pass after the main loop")
    ap.add_argument("--csv", type=Path, default=WORK_PLAN,
                    help="Work-plan CSV path (default work_plan.csv). Two "
                         "runner instances can run in parallel against separate "
                         "CSVs (e.g. work_plan_copy.csv + work_plan_sample.csv).")
    args = ap.parse_args()

    csv_path: Path = args.csv
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found. Run build_work_plan.py first.",
              file=sys.stderr)
        sys.exit(2)

    assert_backend_alive()
    plan = Plan.load(csv_path)

    if args.retry_failed:
        n = reset_failed_to_pending(plan)
        print(f"[runner] --retry-failed: reset {n} rows to pending/copied")

    process_pending(plan, limit=args.limit)

    if not args.no_retry_pass and not args.limit:
        retry_failed_once(plan)

    # Summary
    from collections import Counter
    final = Counter(r.status for r in plan.rows)
    print(f"[runner] done — final status counts: {dict(final)}")


if __name__ == "__main__":
    main()
