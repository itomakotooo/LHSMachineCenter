from __future__ import annotations

import concurrent.futures
import json
import math
import os
import shutil
import signal
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


APP_STARTED_AT = utc_now()


ROOT = Path(__file__).resolve().parents[3]
STATE_DIR = ROOT / "state" / "console"
DB_PATH = STATE_DIR / "console.db"
MODEL_CONFIG_PATH = STATE_DIR / "model_config.json"
PROGRESS_DIR = STATE_DIR / "progress"
REPORTS_ROOT = ROOT / "reports"
CACHE_ROOT = ROOT / "cache" / "chunks"
MACHINES_CONFIG = ROOT / "configs" / "machines.json"
ANALYZER = ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
FRONTEND_DIR = ROOT / "src" / "web_console" / "frontend"
SLOT_SPIN_ENDPOINT = "http://buffalo-debug.citrusjoy.com/MachineTest/MultiRobotTestSpin"


PROVIDER_MODELS: dict[str, list[str]] = {
    "gemini": ["gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-2.5-flash", "gemini-2.5-pro"],
    "gpt": ["gpt-5.4-mini", "gpt-5.4", "gpt-5.2"],
    "claude": ["claude-sonnet-4-20250514", "claude-3-7-sonnet-latest"],
}


class RuntimeModelConfig:
    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path
        provider = os.getenv("MODEL_PROVIDER", "gemini").strip().lower()
        if provider not in PROVIDER_MODELS:
            provider = "gemini"
        self._provider = provider
        self._api_key = os.getenv("MODEL_API_KEY", "").strip()
        self._lock = threading.Lock()
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self._config_path.exists():
            return
        try:
            payload = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        provider = str(payload.get("provider", "")).strip().lower()
        api_key = str(payload.get("api_key", "")).strip()
        if provider in PROVIDER_MODELS:
            self._provider = provider
        if api_key:
            self._api_key = api_key

    def _persist(self) -> None:
        payload = {
            "provider": self._provider,
            "api_key": self._api_key,
            "updated_at": utc_now(),
        }
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return {"provider": self._provider, "api_key": self._api_key}

    def update(self, provider: str, api_key: str) -> dict[str, str]:
        p = provider.strip().lower()
        if p not in PROVIDER_MODELS:
            raise ValueError(f"unsupported provider: {provider}")
        with self._lock:
            self._provider = p
            key = (api_key or "").strip()
            if key:
                self._api_key = key
            self._persist()
            return {"provider": self._provider, "api_key": self._api_key}


def get_model_config_view(
    model_runtime: "RuntimeModelConfig",
    model_config_path: Path,
) -> dict[str, Any]:
    snap = model_runtime.snapshot()
    provider = snap["provider"]
    models = PROVIDER_MODELS[provider]
    warnings: list[str] = []
    if not snap["api_key"]:
        warnings.append(f"{provider.upper()} API key is empty; interpretation will fall back to rule-based.")
    return {
        "provider_options": list(PROVIDER_MODELS.keys()),
        "provider_catalog": PROVIDER_MODELS,
        "active_provider": provider,
        "has_api_key": bool(snap["api_key"]),
        "config_persisted": model_config_path.exists(),
        "config_path": str(model_config_path),
        "default_model": models[0],
        "cleanup_policy": "manual_only",
        "warnings": warnings,
        "models": [{"id": mid, "label": mid} for mid in models],
    }


class RunCreateRequest(BaseModel):
    machine: str
    mode: int
    # target_halfwidth_pp == 0 encodes the "fuzzy" tier (no CI stop;
    # backend resolves max_chunks to target ~1M spins). Any positive
    # value is a normal CI half-width in percentage points.
    target_halfwidth_pp: float = Field(default=0.5, ge=0)
    chunk_spin_times: int = Field(default=5000, gt=0)
    chunk_robot_count: int = Field(default=20, gt=0)
    batch_concurrency: int = Field(default=2, gt=0)
    max_chunks: int = Field(default=120, gt=0)
    timeout: float = Field(default=300.0, gt=0)
    bankruptcy_session_spins: int = Field(default=500, gt=0)
    bankruptcy_bankroll_multipliers: str = Field(default="100,200,500")
    model_id: str = Field(default="gpt-5.4-mini")


class InterpretationRequest(BaseModel):
    run_id: str
    model_id: str


class ModelConfigUpdateRequest(BaseModel):
    provider: str
    api_key: str = Field(default="")


class CacheCleanupRequest(BaseModel):
    max_delete_bytes: int = Field(default=0, ge=0)


class AutoTuneRequest(BaseModel):
    machine: str
    mode: int
    spin_times: int = Field(default=120, gt=0)
    # Compact 3x3 default grid (was 5x4): the user's first dashboard
    # round flagged autotune as too slow. Combined with the per-robot
    # early-exit in run_auto_tune, this typically cuts wall time more
    # than half versus the prior sweep without losing coverage of the
    # interesting (low / mid / high) load points.
    robot_candidates: list[int] = Field(default_factory=lambda: [8, 16, 24])
    concurrency_candidates: list[int] = Field(default_factory=lambda: [1, 2, 4])
    rounds: int = Field(default=2, gt=0, le=8)
    timeout: float = Field(default=30.0, gt=0, le=180.0)
    bet: int = Field(default=1000, gt=0)


class StateStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                  run_id TEXT PRIMARY KEY,
                  machine TEXT NOT NULL,
                  mode INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  model_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  started_at TEXT NOT NULL,
                  finished_at TEXT,
                  target_halfwidth_pp REAL NOT NULL,
                  chunk_spin_times INTEGER NOT NULL,
                  chunk_robot_count INTEGER NOT NULL,
                  batch_concurrency INTEGER NOT NULL,
                  max_chunks INTEGER NOT NULL,
                  timeout REAL NOT NULL,
                  bankruptcy_session_spins INTEGER NOT NULL,
                  bankruptcy_bankroll_multipliers TEXT NOT NULL,
                  report_version TEXT NOT NULL,
                  output_dir TEXT NOT NULL,
                  progress_file TEXT NOT NULL,
                  summary_file TEXT,
                  report_file TEXT,
                  error_message TEXT
                )
                """
            )
            run_columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
            if "process_pid" not in run_columns:
                conn.execute("ALTER TABLE runs ADD COLUMN process_pid INTEGER")
            # Run-history surfaces in the manage tab read these two columns
            # so the operator can eyeball RTP + achieved CI without clicking
            # "Load" on every row. Populated from the summary JSON in
            # _update_report_index(); legacy rows from before this migration
            # stay NULL and render as "\u2014".
            if "achieved_rtp_pct" not in run_columns:
                conn.execute("ALTER TABLE runs ADD COLUMN achieved_rtp_pct REAL")
            if "achieved_halfwidth_pp" not in run_columns:
                conn.execute("ALTER TABLE runs ADD COLUMN achieved_halfwidth_pp REAL")
            # quality_label feeds the merged Run History "Quality" column
            # (report-grade / exploratory / ...). Populated from
            # summary.guideline_assessment.data_quality.quality_label in
            # _update_report_index(); backfilled on startup for legacy rows.
            if "quality_label" not in run_columns:
                conn.execute("ALTER TABLE runs ADD COLUMN quality_label TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS interpretations (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_id TEXT NOT NULL,
                  model_id TEXT NOT NULL,
                  source TEXT,
                  warning TEXT,
                  content TEXT NOT NULL,
                  created_at TEXT NOT NULL
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(interpretations)").fetchall()}
            if "source" not in columns:
                conn.execute("ALTER TABLE interpretations ADD COLUMN source TEXT")
            if "warning" not in columns:
                conn.execute("ALTER TABLE interpretations ADD COLUMN warning TEXT")
            conn.commit()

    def insert_run(self, record: dict[str, Any]) -> None:
        fields = ", ".join(record.keys())
        holders = ", ".join([":" + k for k in record.keys()])
        with self._connect() as conn:
            conn.execute(f"INSERT INTO runs ({fields}) VALUES ({holders})", record)
            conn.commit()

    def update_run(self, run_id: str, patch: dict[str, Any]) -> None:
        if not patch:
            return
        sets = ", ".join([f"{k}=:{k}" for k in patch.keys()])
        payload = {"run_id": run_id, **patch}
        with self._connect() as conn:
            conn.execute(f"UPDATE runs SET {sets} WHERE run_id=:run_id", payload)
            conn.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def list_runs_by_status(self, status: str, limit: int = 2000) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def backfill_rtp_ci_from_summaries(self) -> dict[str, Any]:
        """One-shot migration: for every completed row missing
        achieved_rtp_pct OR achieved_halfwidth_pp, read the on-disk
        summary.json and populate the column. Old rows (from before
        _update_report_index started persisting these two fields)
        would otherwise render as "\u2014" in the manage-tab history
        table forever.

        Safe to run on every startup: rows with values already set are
        skipped; rows whose summary_file is missing or malformed are
        left null (the UI still shows "\u2014" for them).
        """
        scanned = 0
        updated = 0
        skipped_no_file = 0
        with self._connect() as conn:
            # Include 'cancelled' status too: graceful-stop runs produce
            # a valid partial summary that can be backfilled like any
            # completed run.
            rows = conn.execute(
                """
                SELECT run_id, status, summary_file, achieved_rtp_pct,
                       achieved_halfwidth_pp, quality_label
                FROM runs
                WHERE status IN ('completed', 'cancelled')
                  AND (achieved_rtp_pct IS NULL
                       OR achieved_halfwidth_pp IS NULL
                       OR quality_label IS NULL)
                """
            ).fetchall()
            for r in rows:
                scanned += 1
                path_text = r["summary_file"]
                if not path_text:
                    skipped_no_file += 1
                    continue
                summary_path = Path(path_text)
                if not summary_path.exists():
                    skipped_no_file += 1
                    continue
                try:
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                rtp = summary.get("rtp", {}).get("point_pct") if isinstance(summary, dict) else None
                hw = (
                    summary.get("sampling", {}).get("achieved_halfwidth_pp")
                    if isinstance(summary, dict) else None
                )
                ql = (
                    summary.get("guideline_assessment", {})
                    .get("data_quality", {})
                    .get("quality_label")
                    if isinstance(summary, dict) else None
                )
                # Write whichever fields had a null stored + a real
                # value available; leave others alone.
                patch_pairs: list[tuple[str, Any]] = []
                if r["achieved_rtp_pct"] is None and rtp is not None:
                    patch_pairs.append(("achieved_rtp_pct", float(rtp)))
                if r["achieved_halfwidth_pp"] is None and hw is not None:
                    patch_pairs.append(("achieved_halfwidth_pp", float(hw)))
                if r["quality_label"] is None and ql:
                    patch_pairs.append(("quality_label", str(ql)))
                if not patch_pairs:
                    continue
                sets = ", ".join(f"{name}=?" for name, _ in patch_pairs)
                values = [v for _, v in patch_pairs] + [r["run_id"]]
                conn.execute(
                    f"UPDATE runs SET {sets} WHERE run_id=?",
                    values,
                )
                updated += 1
            conn.commit()
        return {
            "scanned": scanned,
            "updated": updated,
            "skipped_no_file": skipped_no_file,
        }

    def delete_run(self, run_id: str) -> bool:
        """Drop the run row and its cascade children (interpretations).

        Returns True if the row was actually removed. Callers are expected
        to have already refused deletes for running rows and cleaned up
        on-disk artefacts (progress/summary/report/report-version-dir).
        """
        with self._connect() as conn:
            conn.execute("DELETE FROM interpretations WHERE run_id=?", (run_id,))
            cur = conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
            conn.commit()
            return cur.rowcount > 0

    def insert_interpretation(
        self,
        run_id: str,
        model_id: str,
        content: str,
        source: str = "",
        warning: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO interpretations (run_id, model_id, source, warning, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, model_id, source, warning, content, utc_now()),
            )
            conn.commit()

    def latest_interpretation(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM interpretations
                WHERE run_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        return dict(row) if row else None


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_progress_events(progress_file: Path) -> list[dict[str, Any]]:
    if not progress_file.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in progress_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def summarize_progress(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {}
    latest = events[-1]
    chunk_events = [e for e in events if e.get("event") == "chunk_progress"]
    return {
        "latest_event": latest,
        "chunks": chunk_events,
        "chunk_count": len(chunk_events),
    }


def load_machines(path: Path | None = None) -> list[dict[str, Any]]:
    target = path if path is not None else MACHINES_CONFIG
    if target.exists():
        payload = read_json(target)
        machines = payload.get("machines", [])
        if isinstance(machines, list):
            return machines
    return [{"machine": "M14", "modes": [1]}]


class OperationCoordinator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._busy = False
        self._name = ""
        self._since = ""

    def acquire(self, name: str) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            self._name = name
            self._since = utc_now()
            return True

    def release(self) -> None:
        with self._lock:
            self._busy = False
            self._name = ""
            self._since = ""

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "busy": self._busy,
                "operation": self._name,
                "since": self._since,
            }


def _coerce_pid(value: Any) -> int | None:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _terminate_pid_if_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            result = subprocess.run(  # noqa: S603
                ["taskkill", "/PID", str(pid), "/T", "/F"],  # noqa: S607
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return result.returncode == 0
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def _sanitize_int_candidates(values: list[int], lower: int, upper: int) -> list[int]:
    cleaned = sorted({int(v) for v in values if isinstance(v, int) and lower <= int(v) <= upper})
    return cleaned


def _build_spin_payload(machine: str, mode: int, spin_times: int, robot_count: int, bet: int) -> dict[str, Any]:
    return {
        "MachineName": machine,
        "InitCreditsStr": str(10**14),
        "BetStrategy": 0,
        "BetOriginStr": str(bet),
        "SpinTimes": int(spin_times),
        "RtpId": int(mode),
        "ShouldTestLuckyGame": False,
        "ContinueAfterBankrupt": True,
        "ResetPlayerStateAfterEachSpin": True,
        "RobotCount": int(robot_count),
        "OutputAllRobotResult": True,
    }


def _parse_round_count(robot: Any) -> int:
    if not isinstance(robot, dict):
        return 0
    rr = robot.get("roundResult")
    if isinstance(rr, list):
        return len(rr)
    if isinstance(rr, str):
        try:
            parsed = json.loads(rr)
        except json.JSONDecodeError:
            return 0
        return len(parsed) if isinstance(parsed, list) else 0
    return 0


def _post_slot_spin(payload: dict[str, Any], timeout: float) -> Any:
    req = urllib.request.Request(
        SLOT_SPIN_ENDPOINT,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def _run_probe_request(payload: dict[str, Any], expected_spins: int, timeout: float) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        resp = _post_slot_spin(payload, timeout)
        elapsed = max(time.perf_counter() - t0, 1e-6)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "elapsed_s": max(time.perf_counter() - t0, 1e-6),
            "spins": 0,
            "error": exc.__class__.__name__,
        }
    if not isinstance(resp, list):
        return {"ok": False, "elapsed_s": elapsed, "spins": 0, "error": "invalid_response_shape"}
    spins = sum(_parse_round_count(robot) for robot in resp)
    if spins <= 0:
        spins = expected_spins
    return {"ok": True, "elapsed_s": elapsed, "spins": spins, "error": ""}


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    p = min(max(pct, 0.0), 1.0)
    ordered = sorted(float(v) for v in values)
    idx = int(round((len(ordered) - 1) * p))
    return ordered[idx]


def _run_parallel_candidate(
    *,
    machine: str,
    mode: int,
    spin_times: int,
    robot_count: int,
    batch_concurrency: int,
    rounds: int,
    timeout: float,
    bet: int,
) -> dict[str, Any]:
    expected_spins = int(spin_times) * int(robot_count)
    request_count = rounds * batch_concurrency
    success_count = 0
    total_spins = 0
    total_request_elapsed = 0.0
    latencies: list[float] = []
    errors: dict[str, int] = {}
    started_wall = time.perf_counter()

    payload = _build_spin_payload(
        machine=machine,
        mode=mode,
        spin_times=spin_times,
        robot_count=robot_count,
        bet=bet,
    )
    for _ in range(rounds):
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_concurrency) as executor:
            futures = [
                executor.submit(_run_probe_request, payload, expected_spins, timeout)
                for _ in range(batch_concurrency)
            ]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                total_request_elapsed += float(result.get("elapsed_s", 0.0))
                latencies.append(float(result.get("elapsed_s", 0.0)))
                if result.get("ok"):
                    success_count += 1
                    total_spins += int(result.get("spins", 0))
                else:
                    err = str(result.get("error", "unknown_error"))
                    errors[err] = errors.get(err, 0) + 1

    wall_elapsed = max(time.perf_counter() - started_wall, 1e-6)
    success_rate = (success_count / request_count) if request_count > 0 else 0.0
    throughput_sps = total_spins / wall_elapsed
    mean_latency = statistics.fmean(latencies) if latencies else 0.0
    p95_latency = _percentile(latencies, 0.95)

    return {
        "robot_count": robot_count,
        "batch_concurrency": batch_concurrency,
        "spin_times": spin_times,
        "rounds": rounds,
        "request_count": request_count,
        "success_count": success_count,
        "success_rate": success_rate,
        "total_spins": total_spins,
        "throughput_spins_per_sec": throughput_sps,
        "wall_elapsed_s": wall_elapsed,
        "cumulative_request_elapsed_s": total_request_elapsed,
        "mean_latency_s": mean_latency,
        "p95_latency_s": p95_latency,
        "errors": errors,
        "score": throughput_sps * success_rate,
    }


def run_auto_tune(
    req: AutoTuneRequest,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    """Run the autotune candidate grid.

    Emits progress via ``progress_callback(phase, payload)`` where phase is
    one of ``"start" | "candidate" | "finish"``:

    - ``start`` payload: ``{"total_candidates": N, "machine": ..., "mode": ...}``
    - ``candidate`` payload: the candidate result dict just produced
    - ``finish`` payload: ``{"status": "completed" | "error"}``
    """
    robots = _sanitize_int_candidates(req.robot_candidates, lower=1, upper=200)
    concs = sorted(_sanitize_int_candidates(req.concurrency_candidates, lower=1, upper=16))
    if not robots:
        robots = [8, 16, 24]
    if not concs:
        concs = [1, 2, 4]

    started = utc_now()
    candidates: list[dict[str, Any]] = []
    total = len(robots) * len(concs)
    if progress_callback is not None:
        progress_callback(
            "start",
            {"total_candidates": total, "machine": req.machine, "mode": req.mode},
        )
    # Early-exit bookkeeping: once a (robot, conc) candidate's success_rate
    # falls below SATURATION_THRESHOLD, every larger conc with the same
    # robot is guaranteed to fail at least as hard (more parallel load on
    # an already-stressed worker pool). Skip them, but still pre-emit a
    # "candidate" progress payload tagged skipped=True so the operator
    # sees why the sweep finished early.
    SATURATION_THRESHOLD = 0.7
    saturated_robots: set[int] = set()
    try:
        for robot in robots:
            for conc in concs:
                if robot in saturated_robots:
                    skip_payload = {
                        "robot_count": robot,
                        "batch_concurrency": conc,
                        "spin_times": req.spin_times,
                        "rounds": req.rounds,
                        "skipped": True,
                        "skip_reason": "saturated_at_lower_concurrency",
                        "success_rate": 0.0,
                        "throughput_spins_per_sec": 0.0,
                    }
                    if progress_callback is not None:
                        progress_callback("candidate", skip_payload)
                    continue
                result = _run_parallel_candidate(
                    machine=req.machine,
                    mode=req.mode,
                    spin_times=req.spin_times,
                    robot_count=robot,
                    batch_concurrency=conc,
                    rounds=req.rounds,
                    timeout=req.timeout,
                    bet=req.bet,
                )
                candidates.append(result)
                if progress_callback is not None:
                    progress_callback("candidate", result)
                if float(result.get("success_rate", 0.0)) < SATURATION_THRESHOLD:
                    saturated_robots.add(robot)
    except BaseException:
        if progress_callback is not None:
            progress_callback("finish", {"status": "error"})
        raise
    if progress_callback is not None:
        progress_callback("finish", {"status": "completed"})

    ranked = sorted(
        candidates,
        key=lambda x: (
            float(x.get("success_rate", 0.0)),
            float(x.get("throughput_spins_per_sec", 0.0)),
            -float(x.get("p95_latency_s", 0.0)),
        ),
        reverse=True,
    )
    best = ranked[0] if ranked else None
    return {
        "started_at": started,
        "finished_at": utc_now(),
        "machine": req.machine,
        "mode": req.mode,
        "spin_times": req.spin_times,
        "rounds": req.rounds,
        "robot_candidates": robots,
        "concurrency_candidates": concs,
        "tested": len(candidates),
        "best": best,
        "recommendation": {
            "chunk_robot_count": int(best.get("robot_count", req.robot_candidates[0] if req.robot_candidates else 20))
            if best
            else 20,
            "batch_concurrency": int(best.get("batch_concurrency", req.concurrency_candidates[0] if req.concurrency_candidates else 2))
            if best
            else 2,
        },
        "results": ranked,
    }


def create_interpretation_content(summary: dict[str, Any], model_id: str) -> str:
    ga = summary.get("guideline_assessment", {})
    cls = ga.get("classification", {})
    d = ga.get("derived_metrics", {})
    bank = ga.get("bankruptcy_checks", {})
    alerts = ga.get("alerts", [])
    actions = ga.get("action_recommendations", [])
    quality = ga.get("data_quality", {}).get("quality_label", "UNKNOWN")
    player = summary.get("player_impact", {})
    hit = player.get("hit_and_payout", {})
    mult = player.get("multiplier_profile", {})
    rtp = summary.get("rtp", {})

    lines = [
        f"Model: {model_id}",
        f"Quality: {quality}",
        f"RTP: {rtp.get('point_pct')} (CI95: {rtp.get('ci95_interval_pct')})",
        (
            "Player feel: "
            f"{cls.get('experience_archetype', 'N/A')} / {cls.get('volatility_class', 'N/A')}"
        ),
        (
            "Core rates: "
            f"zero_win={hit.get('zero_win_rate')}, win_hit={hit.get('win_hit_rate')}, "
            f"profit_spin={hit.get('profit_spin_rate')}, big_win_x10={hit.get('big_win_x10_rate')}"
        ),
        (
            "Tail structure: "
            f"tail_spin_ge10x={mult.get('tail_spin_rate_ge10x')}, "
            f"tail_rtp_pp_ge10x={mult.get('tail_rtp_contribution_pp_ge10x')}, "
            f"tail_dependency={d.get('tail_dependency')}"
        ),
        (
            "Bankruptcy ladder: "
            f"x100={bank.get('x100_bankruptcy_rate')}, "
            f"x200={bank.get('x200_bankruptcy_rate')}, "
            f"x500={bank.get('x500_bankruptcy_rate')}"
        ),
    ]
    if alerts:
        lines.append("Alerts:")
        for a in alerts:
            lines.append(f"- [{a.get('severity')}] {a.get('code')}: {a.get('message')}")
    if actions:
        lines.append("Recommended actions:")
        for idx, action in enumerate(actions, 1):
            lines.append(f"{idx}. {action}")
    return "\n".join(lines)


def build_interpretation_prompt(summary: dict[str, Any]) -> str:
    pi = summary.get("player_impact", {}) or {}
    subset = {
        "machine": summary.get("machine"),
        "mode": summary.get("mode"),
        "sampling": summary.get("sampling"),
        "rtp": summary.get("rtp"),
        "player_impact": {
            "volatility": pi.get("volatility"),
            "multiplier_profile": pi.get("multiplier_profile"),
            "hit_and_payout": pi.get("hit_and_payout"),
            "streaks": pi.get("streaks"),
            "bankruptcy_probe": pi.get("bankruptcy_probe"),
            # Drilldown surfaces -- give the model the same data the
            # console operator stares at so it can comment on payline /
            # payout-id / symbol hotspots instead of stopping at the
            # aggregate volatility numbers.
            "paylines_top20": pi.get("paylines_top20"),
            "payout_groups_top20": pi.get("payout_groups_top20"),
            "payout_ids_top20": pi.get("payout_ids_top20"),
            "spin_type_breakdown": pi.get("spin_type_breakdown"),
            "symbols_top20": pi.get("symbols_top20"),
            "symbols_by_column_top10": pi.get("symbols_by_column_top10"),
        },
        # Cross-cutting context the LLM needs to interpret the metrics:
        # upstream_analysis carries the server-side total_win sanity
        # check; collect_mechanic flags whether the machine has a
        # collect bonus (M272+) so the model can surface it explicitly.
        "upstream_analysis": summary.get("upstream_analysis"),
        "collect_mechanic": summary.get("collect_mechanic"),
        "guideline_assessment": summary.get("guideline_assessment"),
        "guideline_comparison": summary.get("guideline_comparison"),
    }
    payload = json.dumps(subset, ensure_ascii=False, indent=2)
    # Reference thresholds keep the model's "波动性高" / "破产率偏高"
    # assertions grounded in the same numbers analyzer uses internally
    # (see classify_volatility, classify_experience_archetype, and the
    # alert rules in configs/classic_slots_guideline_rules.json).
    reference = (
        "参照阈值（用于判断高/中/低与告警门槛，请在结论中显式引用）：\n"
        "- 波动性 (player_impact.volatility.classification)：\n"
        "  * Very High: zero_win_rate>0.82 OR loss_streak_p95>18 OR tail_dependency>0.50\n"
        "  * High:      zero_win_rate>=0.75 OR loss_streak_p95>=13 OR tail_dependency>=0.35\n"
        "  * Medium:    zero_win_rate>=0.65 OR loss_streak_p95>=9  OR tail_dependency>=0.20\n"
        "  * Low:       以上均不满足\n"
        "- 体验类型 (experience_archetype)：\n"
        "  * Boom-Bust: zero_win_rate>=0.75 且 tail_dependency>=0.35 且 big_win_x10_rate>=0.015\n"
        "  * Grindy:    zero_win_rate>=0.75 且 big_win_x10_rate<0.015，或 zero_win_rate>=0.78\n"
        "  * Balanced:  其余（且 0.08<=profit_spin_rate<=0.16, tail_dependency<0.35 时强匹配）\n"
        "- 数据可信度 (sampling)：CI half-width<=0.5pp 为报告级，total_spins>=2,000,000 为推荐量\n"
        "- 损失连击 (streaks.loss_streak_p95)：>=15 触发告警，>=18 进入风险区\n"
        "- 破产率 (bankruptcy_probe)：x100 bust>0.20 高，x200>0.10 高，x500>0.05 高\n"
        "- 倍率桶尾部 (multiplier_profile.tail_dependency)：>=0.45 表示头重，<0.20 表示扁平\n"
    )
    return (
        "你是老虎机数值分析助手。请使用中文输出，结构固定为：\n"
        "1) 数据可信度\n"
        "2) 玩家体感\n"
        "3) RTP结构与倍率分桶\n"
        "4) 支付线与符号热点（必须基于 paylines_top20 / payout_groups_top20 /\n"
        "   symbols_top20 / symbols_by_column_top10；如果 payout_groups_top20\n"
        "   为空请说明该报告由旧版本 analyzer 生成）\n"
        "5) 关键风险与告警（必须引用上方「参照阈值」中的具体数字）\n"
        "6) 优先调参建议（按优先级，每条注明对应的指标和目标方向）\n"
        "要求：结论可执行，避免空话，每点尽量量化；引用阈值时使用上方提供的数值。\n\n"
        f"{reference}\n"
        f"输入数据:\n{payload}"
    )

def _post_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float = 90.0) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        method="POST",
        headers=headers,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def call_gpt_interpreter(summary: dict[str, Any], model_id: str, api_key: str) -> str:
    prompt = build_interpretation_prompt(summary)
    endpoint = "https://api.openai.com/v1/chat/completions"
    body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "You are a rigorous slot-math analyst."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = _post_json(endpoint, headers, body, timeout=90.0)
    choices = payload.get("choices", [])
    if not choices:
        raise ValueError("model returned empty choices")
    msg = choices[0].get("message", {})
    content = msg.get("content", "")
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
        content = "\n".join([x for x in text_parts if x])
    if not content:
        raise ValueError("model returned empty content")
    return str(content)


def call_gemini_interpreter(summary: dict[str, Any], model_id: str, api_key: str) -> str:
    prompt = build_interpretation_prompt(summary)
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib.parse.quote(model_id, safe='')}:generateContent?key={urllib.parse.quote(api_key, safe='')}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }
    payload = _post_json(endpoint, {"Content-Type": "application/json"}, body, timeout=90.0)
    candidates = payload.get("candidates", [])
    if not candidates:
        raise ValueError("gemini returned empty candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    texts = [str(p.get("text", "")).strip() for p in parts if isinstance(p, dict)]
    content = "\n".join([t for t in texts if t])
    if not content:
        raise ValueError("gemini returned empty content")
    return content


def call_claude_interpreter(summary: dict[str, Any], model_id: str, api_key: str) -> str:
    prompt = build_interpretation_prompt(summary)
    endpoint = "https://api.anthropic.com/v1/messages"
    body = {
        "model": model_id,
        "max_tokens": 1200,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    payload = _post_json(endpoint, headers, body, timeout=90.0)
    content_items = payload.get("content", [])
    texts = [
        str(item.get("text", "")).strip()
        for item in content_items
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    content = "\n".join([t for t in texts if t])
    if not content:
        raise ValueError("claude returned empty content")
    return content


def call_remote_interpreter(summary: dict[str, Any], model_id: str, provider: str, api_key: str) -> str:
    if provider == "gemini":
        return call_gemini_interpreter(summary, model_id, api_key)
    if provider == "gpt":
        return call_gpt_interpreter(summary, model_id, api_key)
    if provider == "claude":
        return call_claude_interpreter(summary, model_id, api_key)
    raise ValueError(f"unsupported provider: {provider}")


def _default_popen_factory(cmd: list[str], cwd: Path) -> subprocess.Popen[str]:
    """Default subprocess factory used by RunManager.

    Tests inject a stub via ``RunManager(popen_factory=...)`` so they don't
    spawn real processes.
    """
    return subprocess.Popen(  # noqa: S603
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


@dataclass
class ManagedRun:
    run_id: str
    process: Any  # actual: subprocess.Popen[str] or test stub with .pid/.communicate/.terminate/.returncode
    output_dir: Path
    progress_file: Path
    summary_file: Path
    report_file: Path
    machine: str
    mode: int
    report_version: str
    # Path the backend touches on cancel_run to request graceful stop.
    # The analyzer polls this file between chunks (cross-platform
    # alternative to SIGTERM: Windows' TerminateProcess doesn't
    # deliver a catchable signal).
    stop_flag_file: Path


class RunManager:
    def __init__(
        self,
        store: StateStore,
        *,
        analyzer: Path | None = None,
        reports_root: Path | None = None,
        progress_dir: Path | None = None,
        cache_root: Path | None = None,
        popen_factory: "Callable[[list[str], Path], Any] | None" = None,
    ) -> None:
        self.store = store
        self._analyzer = analyzer if analyzer is not None else ANALYZER
        self._reports_root = reports_root if reports_root is not None else REPORTS_ROOT
        self._cache_root = cache_root if cache_root is not None else CACHE_ROOT
        self._progress_dir = progress_dir if progress_dir is not None else PROGRESS_DIR
        self._popen_factory = popen_factory if popen_factory is not None else _default_popen_factory
        self._lock = threading.Lock()
        self._running: dict[str, ManagedRun] = {}
        self._startup_recovery = self._recover_orphan_running_runs()

    def _recover_orphan_running_runs(self) -> dict[str, Any]:
        stale = self.store.list_runs_by_status("running", limit=5000)
        if not stale:
            return {
                "recovered_count": 0,
                "run_ids": [],
                "terminated_pids": [],
                "failed_to_terminate_pids": [],
            }
        recovered_ids: list[str] = []
        terminated_pids: list[int] = []
        failed_to_terminate_pids: list[int] = []
        for row in stale:
            run_id = str(row.get("run_id", "")).strip()
            if not run_id:
                continue
            pid = _coerce_pid(row.get("process_pid"))
            message = "run interrupted by console restart; please rerun if needed"
            if pid is not None:
                if _terminate_pid_if_running(pid):
                    terminated_pids.append(pid)
                    message += " (stale worker process terminated)"
                else:
                    failed_to_terminate_pids.append(pid)
                    message += " (stale worker process may still exist)"
            self.store.update_run(
                run_id,
                {
                    "status": "failed",
                    "finished_at": utc_now(),
                    "error_message": message,
                },
            )
            recovered_ids.append(run_id)
        return {
            "recovered_count": len(recovered_ids),
            "run_ids": recovered_ids,
            "terminated_pids": terminated_pids,
            "failed_to_terminate_pids": failed_to_terminate_pids,
        }

    def startup_recovery_snapshot(self) -> dict[str, Any]:
        return dict(self._startup_recovery)

    def running_count(self) -> int:
        with self._lock:
            return len(self._running)

    #: Total spins targeted by the "fuzzy" CI tier. Chosen to keep
    #: per-bucket counts high enough for stable multiplier / streak /
    #: bankruptcy metrics in high-volatility modes, while still bounded.
    FUZZY_TARGET_TOTAL_SPINS = 1_000_000

    def start_run(self, req: RunCreateRequest) -> dict[str, Any]:
        if not self._analyzer.exists():
            raise HTTPException(status_code=500, detail="analyzer script not found")

        run_id = uuid.uuid4().hex[:12]
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report_version = f"rv_{ts}_{run_id[:8]}"

        output_dir = self._reports_root / req.machine / f"mode_{req.mode}" / "versions" / report_version
        progress_file = self._progress_dir / f"{run_id}.jsonl"
        summary_file = output_dir / "player_impact_summary.json"
        report_file = output_dir / "player_impact_report.md"

        output_dir.mkdir(parents=True, exist_ok=True)
        progress_file.parent.mkdir(parents=True, exist_ok=True)

        # Fuzzy tier: target_halfwidth_pp == 0 means "skip CI stop".
        # We don't touch the analyzer; instead we feed it an impossible
        # CI target (999 pp) so the CI-stop branch never fires, and
        # override max_chunks so total spins ~= FUZZY_TARGET_TOTAL_SPINS.
        if req.target_halfwidth_pp == 0:
            per_chunk = req.chunk_spin_times * req.chunk_robot_count
            effective_max_chunks = max(
                1, math.ceil(self.FUZZY_TARGET_TOTAL_SPINS / per_chunk)
            )
            effective_halfwidth_pp = 999.0
        else:
            effective_max_chunks = req.max_chunks
            effective_halfwidth_pp = req.target_halfwidth_pp

        cmd = [
            sys.executable,
            str(self._analyzer),
            "--machine",
            req.machine,
            "--rtp-mode",
            str(req.mode),
            "--target-halfwidth-pp",
            str(effective_halfwidth_pp),
            "--chunk-spin-times",
            str(req.chunk_spin_times),
            "--chunk-robot-count",
            str(req.chunk_robot_count),
            "--batch-concurrency",
            str(req.batch_concurrency),
            "--max-chunks",
            str(effective_max_chunks),
            "--timeout",
            str(req.timeout),
            "--bankruptcy-session-spins",
            str(req.bankruptcy_session_spins),
            "--bankruptcy-bankroll-multipliers",
            req.bankruptcy_bankroll_multipliers,
            "--output-dir",
            str(output_dir),
            "--run-id",
            run_id,
            "--progress-file",
            str(progress_file),
        ]
        # Stop-flag file lives next to the run's progress file so it's
        # part of the run's on-disk footprint and gets cleaned up when
        # delete_run removes the run artefacts.
        stop_flag_file = self._progress_dir / f"{run_id}.stop"
        cmd.extend(["--stop-flag-file", str(stop_flag_file)])
        # Chunk cache: raw API responses are persisted here for offline
        # report rebuild. The cache root is the same cache/ tree that
        # /api/cache/status + cleanup already operate on, so cleanup
        # naturally covers it. Rule #13: cleanup must skip active chunks.
        chunk_cache_dir = self._cache_root / run_id
        cmd.extend(["--chunk-cache-dir", str(chunk_cache_dir)])

        process = self._popen_factory(cmd, ROOT)
        managed = ManagedRun(
            run_id=run_id,
            process=process,
            output_dir=output_dir,
            progress_file=progress_file,
            summary_file=summary_file,
            report_file=report_file,
            machine=req.machine,
            mode=req.mode,
            report_version=report_version,
            stop_flag_file=stop_flag_file,
        )

        self.store.insert_run(
            {
                "run_id": run_id,
                "machine": req.machine,
                "mode": req.mode,
                "status": "running",
                "model_id": req.model_id,
                "created_at": utc_now(),
                "started_at": utc_now(),
                "finished_at": None,
                "target_halfwidth_pp": req.target_halfwidth_pp,
                "chunk_spin_times": req.chunk_spin_times,
                "chunk_robot_count": req.chunk_robot_count,
                "batch_concurrency": req.batch_concurrency,
                "max_chunks": req.max_chunks,
                "timeout": req.timeout,
                "bankruptcy_session_spins": req.bankruptcy_session_spins,
                "bankruptcy_bankroll_multipliers": req.bankruptcy_bankroll_multipliers,
                "report_version": report_version,
                "output_dir": str(output_dir),
                "progress_file": str(progress_file),
                "summary_file": str(summary_file),
                "report_file": str(report_file),
                "error_message": None,
                "process_pid": process.pid,
            }
        )

        with self._lock:
            self._running[run_id] = managed

        thread = threading.Thread(target=self._watch_run, args=(managed,), daemon=True)
        thread.start()
        return {"run_id": run_id, "status": "running"}

    def _watch_run(self, managed: ManagedRun) -> None:
        proc = managed.process
        stdout, stderr = proc.communicate()
        code = proc.returncode

        if code == 0 and managed.summary_file.exists() and managed.report_file.exists():
            # Sanity guard: even with exit_code=0 + both artefacts present,
            # the analyzer can have "successfully" exited after zero spins
            # (the main loop breaks on the first failed chunk and writes
            # an empty summary). The most common cause is the upstream
            # sampling API returning 5xx for the first request -- the
            # operator otherwise sees a "completed" run with empty KPIs
            # and no idea why. Promote that case to failed with the
            # analyzer-recorded stop_reason in error_message.
            summary_payload = read_json(managed.summary_file) or {}
            sampling_meta = summary_payload.get("sampling") or {}
            try:
                total_spins = int(sampling_meta.get("total_spins") or 0)
            except (TypeError, ValueError):
                total_spins = 0
            stop_reason = str(sampling_meta.get("stop_reason") or "unknown")
            if total_spins == 0:
                try:
                    chunks_done = int(sampling_meta.get("chunks") or 0)
                except (TypeError, ValueError):
                    chunks_done = 0
                # Zero-spin + user_stop = user cancelled before any
                # chunk completed. Mark cancelled (not failed) so the
                # operator sees their own intent reflected; no data
                # available to surface, error_message notes the cause.
                if stop_reason == "user_stop":
                    self.store.update_run(
                        managed.run_id,
                        {
                            "status": "cancelled",
                            "finished_at": utc_now(),
                            "error_message": (
                                f"cancelled by user before any chunk completed; "
                                f"{chunks_done} chunk(s) attempted"
                            )[:4000],
                        },
                    )
                else:
                    self.store.update_run(
                        managed.run_id,
                        {
                            "status": "failed",
                            "finished_at": utc_now(),
                            "error_message": (
                                f"sampling produced 0 spins after {chunks_done} chunk(s); "
                                f"stop_reason={stop_reason}"
                            )[:4000],
                        },
                    )
                with self._lock:
                    self._running.pop(managed.run_id, None)
                return
            # Non-zero spins with user_stop = graceful cancel with
            # partial data. Persist the report like a completed run
            # (index + latest), but mark status "cancelled" so the
            # operator can distinguish and see the data.
            self._update_report_index(managed)
            final_status = "cancelled" if stop_reason == "user_stop" else "completed"
            self.store.update_run(
                managed.run_id,
                {
                    "status": final_status,
                    "finished_at": utc_now(),
                    "error_message": None,
                },
            )
        else:
            # Build a structured failure message so even silent analyzer
            # crashes leave a diagnostic trail. Order: captured stderr/stdout
            # first (truncated), then exit_code, then which artefacts are
            # missing. Never persist absolute paths -- only file names.
            parts: list[str] = []
            raw = (stderr or stdout or "").strip()
            if raw:
                parts.append(raw[:3500])
            parts.append(f"analyzer exit_code={code}")
            if not managed.summary_file.exists():
                parts.append(f"summary missing: {managed.summary_file.name}")
            if not managed.report_file.exists():
                parts.append(f"report missing: {managed.report_file.name}")
            message = " | ".join(parts)[:4000]
            self.store.update_run(
                managed.run_id,
                {
                    "status": "failed",
                    "finished_at": utc_now(),
                    "error_message": message,
                },
            )
        with self._lock:
            self._running.pop(managed.run_id, None)

    def _update_report_index(self, managed: ManagedRun) -> None:
        mode_dir = self._reports_root / managed.machine / f"mode_{managed.mode}"
        index_path = mode_dir / "index.json"
        latest_path = mode_dir / "latest.json"
        summary = read_json(managed.summary_file)

        index_payload = []
        if index_path.exists():
            try:
                raw = read_json(index_path)
                if isinstance(raw, list):
                    index_payload = raw
            except Exception:
                index_payload = []
        rtp_point_pct = summary.get("rtp", {}).get("point_pct")
        achieved_hw_pp = summary.get("sampling", {}).get("achieved_halfwidth_pp")
        quality_label = summary.get("guideline_assessment", {}).get("data_quality", {}).get("quality_label")
        item = {
            "report_version": managed.report_version,
            "run_id": managed.run_id,
            "created_at": utc_now(),
            "summary_file": str(managed.summary_file),
            "report_file": str(managed.report_file),
            "rtp_point_pct": rtp_point_pct,
            "quality_label": quality_label,
        }
        index_payload.append(item)
        write_json(index_path, index_payload)
        write_json(latest_path, item)
        # Persist the achieved RTP + CI + quality_label onto the runs
        # row so the merged Run History table can show them without
        # reading every summary.json on list.
        patch: dict[str, Any] = {}
        if rtp_point_pct is not None:
            patch["achieved_rtp_pct"] = float(rtp_point_pct)
        if achieved_hw_pp is not None:
            patch["achieved_halfwidth_pp"] = float(achieved_hw_pp)
        if quality_label:
            patch["quality_label"] = str(quality_label)
        if patch:
            self.store.update_run(managed.run_id, patch)

    def get_run_with_progress(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        progress_events = read_progress_events(Path(run["progress_file"]))
        run["progress"] = summarize_progress(progress_events)
        return run

    def list_runs(self) -> list[dict[str, Any]]:
        rows = self.store.list_runs()
        output: list[dict[str, Any]] = []
        for row in rows:
            row["progress"] = summarize_progress(read_progress_events(Path(row["progress_file"])))
            output.append(row)
        return output

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            managed = self._running.get(run_id)
        if not managed:
            raise HTTPException(status_code=404, detail="run not running")
        # Graceful stop: touch the flag file so the analyzer bails out
        # between chunks with partial data intact, then writes its
        # summary with stop_reason="user_stop". _watch_run detects that
        # and marks the run "cancelled" while keeping the partial
        # summary readable. Do NOT terminate immediately -- that would
        # throw away all completed chunks.
        try:
            managed.stop_flag_file.parent.mkdir(parents=True, exist_ok=True)
            managed.stop_flag_file.write_text(utc_now(), encoding="utf-8")
        except OSError:
            # Fall through to hard-terminate if we can't write the flag
            # (read-only FS, no permission); better a lost-chunk cancel
            # than a stuck run.
            managed.process.terminate()
        return {"run_id": run_id, "status": "cancelling"}

    def delete_run(self, run_id: str) -> dict[str, Any]:
        """Delete a run row plus its on-disk artefacts.

        Refuses to delete a run that is still running -- the operator has
        to cancel it first. Removes the per-run progress / summary /
        report files, the report version directory under
        ``reports/<machine>/mode_<n>/versions/<rv>/``, and rolls back
        ``index.json`` + ``latest.json`` so the manage-tab version panel
        doesn't dangle.
        """
        run = self.store.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        status = str(run.get("status", "")).lower()
        if status == "running":
            raise HTTPException(
                status_code=409,
                detail="run is still running; cancel it before deleting",
            )
        with self._lock:
            if run_id in self._running:
                raise HTTPException(
                    status_code=409,
                    detail="run is still running; cancel it before deleting",
                )

        removed_paths: list[str] = []
        # Per-run artefacts. Best-effort unlink; we don't abort the DB
        # delete on a missing file since partial failures would otherwise
        # create un-deletable ghost rows.
        for key in ("progress_file", "summary_file", "report_file"):
            raw = run.get(key)
            if not raw:
                continue
            p = Path(raw)
            try:
                if p.exists():
                    p.unlink()
                    removed_paths.append(str(p))
            except OSError:
                pass
        # Stop-flag file (graceful-stop marker). Not stored in the row
        # but derivable from the progress file's directory + run_id.
        progress_raw = run.get("progress_file")
        if progress_raw:
            stop_flag = Path(progress_raw).parent / f"{run_id}.stop"
            try:
                if stop_flag.exists():
                    stop_flag.unlink()
                    removed_paths.append(str(stop_flag))
            except OSError:
                pass

        # Report version directory + the two machine-mode manifests.
        report_version = (run.get("report_version") or "").strip()
        if report_version:
            mode_dir = self._reports_root / str(run["machine"]) / f"mode_{run['mode']}"
            version_dir = mode_dir / "versions" / report_version
            if version_dir.exists():
                try:
                    shutil.rmtree(version_dir)
                    removed_paths.append(str(version_dir))
                except OSError:
                    pass
            index_path = mode_dir / "index.json"
            latest_path = mode_dir / "latest.json"
            if index_path.exists():
                try:
                    raw = read_json(index_path)
                    if isinstance(raw, list):
                        filtered = [
                            item for item in raw
                            if isinstance(item, dict)
                            and item.get("report_version") != report_version
                        ]
                        write_json(index_path, filtered)
                        # latest.json rolls back to the newest remaining
                        # item (list is append-ordered); if we just drained
                        # the last version, clear latest too.
                        if filtered:
                            write_json(latest_path, filtered[-1])
                        elif latest_path.exists():
                            latest_path.unlink()
                except Exception:
                    pass

        removed = self.store.delete_run(run_id)
        return {
            "run_id": run_id,
            "deleted": bool(removed),
            "removed_paths": removed_paths,
        }


def current_system_state(
    store: StateStore,
    manager: RunManager,
    ops: OperationCoordinator,
) -> dict[str, Any]:
    snap = ops.snapshot()
    running = store.list_runs_by_status("running", limit=2000)
    return {
        "ts": utc_now(),
        "app_started_at": APP_STARTED_AT,
        "operation_busy": bool(snap["busy"]),
        "operation_name": snap["operation"],
        "operation_since": snap["since"],
        "running_runs_count": len(running),
        "running_run_ids": [str(r.get("run_id", "")) for r in running if r.get("run_id")],
        "in_memory_running_count": manager.running_count(),
        "startup_recovery": manager.startup_recovery_snapshot(),
    }


def folder_bytes(path: Path) -> tuple[int, int]:
    size = 0
    files = 0
    if not path.exists():
        return (0, 0)
    for p in path.rglob("*"):
        if p.is_file():
            files += 1
            size += p.stat().st_size
    return (size, files)


def _parse_threshold(env_key: str, default: int) -> int:
    """Read a positive int from env var; fall back to default on missing/invalid."""
    raw = os.environ.get(env_key, "")
    if not raw:
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


def resolved_risk_thresholds() -> dict[str, int]:
    """Return cache cleanup risk thresholds.

    Defaults are 512 MiB (medium) and 2 GiB (high). Both can be overridden via
    SLOT_RISK_MEDIUM_BYTES and SLOT_RISK_HIGH_BYTES (used by e2e tests to
    trigger the medium/high tier without writing huge files). The function
    enforces ``high >= medium > 0`` so the frontend never sees an inverted
    pair.
    """
    medium = _parse_threshold("SLOT_RISK_MEDIUM_BYTES", 512 * 1024 * 1024)
    high = _parse_threshold("SLOT_RISK_HIGH_BYTES", 2 * 1024 * 1024 * 1024)
    if high < medium:
        high = medium
    return {"medium_bytes": medium, "high_bytes": high}


def create_app(
    state_dir: Path | None = None,
    reports_root: Path | None = None,
    cache_root: Path | None = None,
    machines_config: Path | None = None,
    analyzer_path: Path | None = None,
) -> FastAPI:
    """Build a FastAPI app with all stateful singletons scoped to this instance.

    Each call constructs its own StateStore, RunManager, OperationCoordinator,
    and RuntimeModelConfig, and registers all routes via closures over them.
    Tests pass tmp paths to get a fully isolated app; ``main.py`` calls this
    with no arguments to get the default production app.
    """
    sd = state_dir if state_dir is not None else STATE_DIR
    sd.mkdir(parents=True, exist_ok=True)
    progress_dir = sd / "progress"
    progress_dir.mkdir(parents=True, exist_ok=True)

    db_path = sd / "console.db"
    model_config_path = sd / "model_config.json"
    rr = reports_root if reports_root is not None else REPORTS_ROOT
    cr = cache_root if cache_root is not None else CACHE_ROOT
    mc = machines_config if machines_config is not None else MACHINES_CONFIG
    az = analyzer_path if analyzer_path is not None else ANALYZER

    store = StateStore(db_path)
    # Backfill achieved_rtp_pct / achieved_halfwidth_pp from on-disk
    # summary.json for completed rows predating those columns -- quick
    # scan, safe on every startup (no-op once populated).
    store.backfill_rtp_ci_from_summaries()
    model_runtime = RuntimeModelConfig(model_config_path)
    manager = RunManager(
        store,
        analyzer=az,
        reports_root=rr,
        progress_dir=progress_dir,
        cache_root=cr,
    )
    ops = OperationCoordinator()

    app = FastAPI(title="Slot Console API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/console", StaticFiles(directory=FRONTEND_DIR, html=True), name="console")

    # Expose live singletons on app.state so tests / e2e fixtures can poke them
    # without monkeypatching module globals.
    app.state.store = store
    app.state.manager = manager
    app.state.ops = ops
    app.state.model_runtime = model_runtime
    app.state.cache_root = cr
    app.state.reports_root = rr
    app.state.db_path = db_path
    app.state.machines_config = mc
    app.state.analyzer = az
    # Autotune progress snapshot: an in-memory dict protected by a lock.
    # Mutated by run_auto_tune via the progress_callback injected below,
    # read via GET /api/autotune/progress.
    app.state.autotune_progress_lock = threading.Lock()
    app.state.autotune_progress = {
        "status": "idle",
        "started_at": None,
        "finished_at": None,
        "total_candidates": 0,
        "completed_candidates": 0,
        "last_result": None,
        "machine": None,
        "mode": None,
    }

    def _autotune_progress_sink(phase: str, payload: dict[str, Any] | None) -> None:
        with app.state.autotune_progress_lock:
            p = app.state.autotune_progress
            if phase == "start":
                p.update(
                    {
                        "status": "running",
                        "started_at": utc_now(),
                        "finished_at": None,
                        "total_candidates": int((payload or {}).get("total_candidates", 0)),
                        "completed_candidates": 0,
                        "last_result": None,
                        "machine": (payload or {}).get("machine"),
                        "mode": (payload or {}).get("mode"),
                    }
                )
            elif phase == "candidate" and payload is not None:
                p["completed_candidates"] = int(p.get("completed_candidates", 0)) + 1
                p["last_result"] = {
                    "robot_count": payload.get("robot_count"),
                    "batch_concurrency": payload.get("batch_concurrency"),
                    "success_rate": payload.get("success_rate"),
                    "throughput_spins_per_sec": payload.get("throughput_spins_per_sec"),
                    "p95_latency_s": payload.get("p95_latency_s"),
                }
            elif phase == "finish":
                p["status"] = str((payload or {}).get("status", "completed"))
                p["finished_at"] = utc_now()

    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        s = current_system_state(store, manager, ops)
        return {
            "ok": True,
            "ts": s["ts"],
            "app_started_at": s["app_started_at"],
            "operation_busy": s["operation_busy"],
            "running_runs_count": s["running_runs_count"],
            "startup_recovery_count": s["startup_recovery"].get("recovered_count", 0),
            "startup_terminated_pid_count": len(s["startup_recovery"].get("terminated_pids", [])),
        }

    @app.get("/api/system-state")
    def system_state() -> dict[str, Any]:
        return current_system_state(store, manager, ops)

    @app.get("/api/machines")
    def machines() -> dict[str, Any]:
        return {"machines": load_machines(mc)}

    @app.get("/api/models")
    def models() -> dict[str, Any]:
        return get_model_config_view(model_runtime, model_config_path)

    @app.post("/api/model-config")
    def update_model_config(req: ModelConfigUpdateRequest) -> dict[str, Any]:
        try:
            model_runtime.update(req.provider, req.api_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"persist_failed:{exc.__class__.__name__}") from exc
        return get_model_config_view(model_runtime, model_config_path)

    @app.post("/api/runs")
    def create_run(req: RunCreateRequest) -> dict[str, Any]:
        # Mode 2 and 5 are RTP-exploding / high-volatility paths where a
        # narrow CI never converges; force the fuzzy tier (halfwidth_pp == 0)
        # so the backend targets ~1M spins via max_chunks instead.
        if req.mode in (2, 5) and req.target_halfwidth_pp != 0:
            raise HTTPException(
                status_code=400,
                detail="mode 2 and 5 must use fuzzy target (target_halfwidth_pp=0)",
            )
        existing = store.list_runs_by_status("running", limit=2)
        if existing:
            rid = str(existing[0].get("run_id", ""))
            raise HTTPException(status_code=409, detail=f"run already active: {rid}")
        if not ops.acquire("start_run"):
            snap = ops.snapshot()
            raise HTTPException(status_code=409, detail=f"system busy: {snap.get('operation') or 'unknown'}")
        try:
            return manager.start_run(req)
        finally:
            ops.release()

    @app.post("/api/autotune")
    def auto_tune(req: AutoTuneRequest) -> dict[str, Any]:
        running = store.list_runs_by_status("running", limit=2000)
        if running:
            raise HTTPException(status_code=409, detail="auto tune is blocked while runs are active")
        if not ops.acquire("auto_tune"):
            snap = ops.snapshot()
            raise HTTPException(status_code=409, detail=f"system busy: {snap.get('operation') or 'unknown'}")
        try:
            return run_auto_tune(req, progress_callback=_autotune_progress_sink)
        finally:
            ops.release()

    @app.get("/api/autotune/progress")
    def autotune_progress() -> dict[str, Any]:
        """Snapshot of autotune progress. Safe to poll at 1s cadence from
        the frontend while a compute is in flight; returns {"status":"idle"}
        when nothing has been run yet this process lifetime."""
        with app.state.autotune_progress_lock:
            return dict(app.state.autotune_progress)

    @app.get("/api/runs")
    def runs() -> dict[str, Any]:
        return {"runs": manager.list_runs()}

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, Any]:
        return manager.get_run_with_progress(run_id)

    @app.get("/api/runs/{run_id}/progress")
    def run_progress(run_id: str) -> dict[str, Any]:
        row = store.get_run(run_id)
        if not row:
            raise HTTPException(status_code=404, detail="run not found")
        events = read_progress_events(Path(row["progress_file"]))
        return {"run_id": run_id, "events": events}

    @app.post("/api/runs/{run_id}/cancel")
    def run_cancel(run_id: str) -> dict[str, Any]:
        return manager.cancel_run(run_id)

    @app.get("/api/runs/{run_id}/chunks")
    def run_chunks(run_id: str) -> dict[str, Any]:
        """Chunk cache status for a run. Returns count + size so the
        manage-tab can show whether rebuild is available."""
        chunk_dir = cr / run_id
        if not chunk_dir.is_dir():
            return {
                "run_id": run_id,
                "chunk_count": 0,
                "total_bytes": 0,
                "cache_version": None,
                "available": False,
            }
        files = sorted(chunk_dir.glob("chunk_*.json"))
        total_bytes = sum(f.stat().st_size for f in files)
        # Read version from first file
        cache_version = None
        if files:
            try:
                first = json.loads(files[0].read_text(encoding="utf-8"))
                cache_version = first.get("_cache_version")
            except Exception:
                pass
        return {
            "run_id": run_id,
            "chunk_count": len(files),
            "total_bytes": total_bytes,
            "cache_version": cache_version,
            "available": len(files) > 0,
        }

    @app.post("/api/runs/{run_id}/rebuild")
    def run_rebuild(run_id: str) -> dict[str, Any]:
        """Rebuild a run's report from cached raw chunk data.

        Re-parses every cached chunk through the current analyzer code,
        re-aggregates, and overwrites the summary + report files.
        Requires cached chunks to exist under cache/chunks/{run_id}/.
        """
        row = store.get_run(run_id)
        if not row:
            raise HTTPException(status_code=404, detail="run not found")
        if str(row.get("status", "")).lower() == "running":
            raise HTTPException(status_code=409, detail="run is still in progress")

        chunk_dir = cr / run_id
        if not chunk_dir.is_dir():
            raise HTTPException(
                status_code=404,
                detail="no cached chunks for this run; resample required",
            )
        chunk_files = sorted(chunk_dir.glob("chunk_*.json"))
        if not chunk_files:
            raise HTTPException(
                status_code=404,
                detail="chunk cache directory is empty; resample required",
            )

        if not ops.acquire("rebuild_report"):
            snap = ops.snapshot()
            raise HTTPException(
                status_code=409,
                detail=f"system busy: {snap.get('operation') or 'unknown'}",
            )
        try:
            from fresh_slotlab.player_impact_analyzer import (
                CHUNK_CACHE_VERSION,
                run_sampling_chunk,
            )

            # Load each cached raw response and re-parse through the
            # current analyzer code.
            chunk_records: list[dict[str, Any]] = []
            for cf in chunk_files:
                envelope = json.loads(cf.read_text(encoding="utf-8"))
                raw_resp = envelope.get("response")
                if raw_resp is None:
                    continue
                # Re-parse: monkey-patch is avoided by calling
                # run_sampling_chunk with a patched post_json. Simpler:
                # call the function with the response pre-loaded.
                # We temporarily swap the module-level post_json.
                import fresh_slotlab.player_impact_analyzer as pia
                _saved_post = pia.post_json
                pia.post_json = lambda payload, timeout, _r=raw_resp: _r
                try:
                    rec = run_sampling_chunk(
                        chunk_index=int(envelope.get("_chunk_index", 0)),
                        machine=str(row["machine"]),
                        rtp_mode=int(row["mode"]),
                        bet=1000,
                        spin_times=int(row["chunk_spin_times"]),
                        robot_count=int(row["chunk_robot_count"]),
                        timeout=float(row["timeout"]),
                    )
                finally:
                    pia.post_json = _saved_post
                if rec.get("ok"):
                    chunk_records.append(rec)

            if not chunk_records:
                raise HTTPException(
                    status_code=422,
                    detail="all cached chunks failed to re-parse",
                )

            # Feed the chunk records through main()'s aggregation by
            # running main() with the cached data. Simpler: write a
            # temp script... Actually simplest: re-run main() with
            # post_json patched to return pre-loaded responses.
            # Use the same approach as the regression test:
            import sys as _sys
            import tempfile
            from io import StringIO
            from pathlib import Path as _Path

            import fresh_slotlab.player_impact_analyzer as pia2

            # Prepare a response iterator: each call to post_json gets
            # the next cached response.
            _cached_responses = [
                json.loads(cf.read_text(encoding="utf-8")).get("response")
                for cf in chunk_files
                if json.loads(cf.read_text(encoding="utf-8")).get("response") is not None
            ]
            _resp_iter = iter(_cached_responses)
            _saved2 = pia2.post_json
            pia2.post_json = lambda payload, timeout: next(_resp_iter)
            _saved_exit = os._exit
            os._exit = lambda rc: None

            output_dir = _Path(row["summary_file"]).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            progress_file = _Path(row["progress_file"])

            test_argv = [
                "analyzer",
                "--machine", str(row["machine"]),
                "--rtp-mode", str(row["mode"]),
                "--bet", "1000",
                "--chunk-spin-times", str(row["chunk_spin_times"]),
                "--chunk-robot-count", str(row["chunk_robot_count"]),
                "--batch-concurrency", "1",
                "--max-chunks", str(len(_cached_responses)),
                "--target-halfwidth-pp", "999",
                "--timeout", str(row["timeout"]),
                "--output-dir", str(output_dir),
                "--progress-file", str(progress_file),
                "--run-id", run_id,
                "--bankruptcy-session-spins", str(row["bankruptcy_session_spins"]),
                "--bankruptcy-bankroll-multipliers", row["bankruptcy_bankroll_multipliers"],
            ]

            old_argv = _sys.argv
            _sys.argv = test_argv
            captured = StringIO()
            old_stdout = _sys.stdout
            _sys.stdout = captured
            try:
                from fresh_slotlab.player_impact_analyzer import main
                rc = main()
            finally:
                _sys.stdout = old_stdout
                _sys.argv = old_argv
                pia2.post_json = _saved2
                os._exit = _saved_exit

            if rc != 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"analyzer main() returned {rc} during rebuild",
                )

            # Re-read the rebuilt summary and update the DB row.
            summary_path = _Path(row["summary_file"])
            if summary_path.exists():
                summary = read_json(summary_path)
                rtp = summary.get("rtp", {}).get("point_pct")
                hw = summary.get("sampling", {}).get("achieved_halfwidth_pp")
                ql = (
                    summary.get("guideline_assessment", {})
                    .get("data_quality", {})
                    .get("quality_label")
                )
                patch: dict[str, Any] = {}
                if rtp is not None:
                    patch["achieved_rtp_pct"] = float(rtp)
                if hw is not None:
                    patch["achieved_halfwidth_pp"] = float(hw)
                if ql:
                    patch["quality_label"] = str(ql)
                if patch:
                    store.update_run(run_id, patch)

                # Update report index + latest.json
                mode_dir = rr / str(row["machine"]) / f"mode_{row['mode']}"
                index_path = mode_dir / "index.json"
                latest_path = mode_dir / "latest.json"
                report_version = row.get("report_version", "")
                item = {
                    "report_version": report_version,
                    "run_id": run_id,
                    "created_at": utc_now(),
                    "summary_file": str(summary_path),
                    "report_file": str(row.get("report_file", "")),
                    "rtp_point_pct": rtp,
                    "quality_label": ql,
                }
                # Replace existing entry or append.
                index_payload = []
                if index_path.exists():
                    try:
                        raw = read_json(index_path)
                        if isinstance(raw, list):
                            index_payload = [
                                e for e in raw
                                if isinstance(e, dict) and e.get("report_version") != report_version
                            ]
                    except Exception:
                        pass
                index_payload.append(item)
                write_json(index_path, index_payload)
                write_json(latest_path, item)

            return {
                "run_id": run_id,
                "status": "rebuilt",
                "chunks_reprocessed": len(chunk_records),
                "rtp_point_pct": rtp if summary_path.exists() else None,
            }
        finally:
            ops.release()

    @app.delete("/api/runs/{run_id}")
    def run_delete(run_id: str) -> dict[str, Any]:
        # Mutex under the shared ops coordinator so deletes don't race
        # a run that's just finishing its _watch_run cleanup, and so
        # the cache-cleanup / start-run paths can't interleave either.
        if not ops.acquire("delete_run"):
            snap = ops.snapshot()
            raise HTTPException(
                status_code=409,
                detail=f"system busy: {snap.get('operation') or 'unknown'}",
            )
        try:
            return manager.delete_run(run_id)
        finally:
            ops.release()

    @app.get("/api/runs/{run_id}/report")
    def run_report(run_id: str) -> dict[str, Any]:
        row = store.get_run(run_id)
        if not row:
            raise HTTPException(status_code=404, detail="run not found")
        summary_path = Path(row["summary_file"])
        report_path = Path(row["report_file"])
        if not summary_path.exists():
            raise HTTPException(status_code=404, detail="summary not generated yet")
        summary = read_json(summary_path)
        report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
        return {
            "run_id": run_id,
            "summary": summary,
            "report_markdown": report_text,
            "summary_file": str(summary_path),
            "report_file": str(report_path),
        }

    @app.get("/api/reports/{machine}/{mode}")
    def report_versions(machine: str, mode: int) -> dict[str, Any]:
        mode_dir = rr / machine / f"mode_{mode}"
        index_path = mode_dir / "index.json"
        latest_path = mode_dir / "latest.json"
        index_payload = read_json(index_path) if index_path.exists() else []
        latest_payload = read_json(latest_path) if latest_path.exists() else {}
        return {"machine": machine, "mode": mode, "versions": index_payload, "latest": latest_payload}

    @app.get("/api/library/distributions")
    def library_distributions() -> dict[str, Any]:
        """Across-library metric distributions built from every
        reports/<machine>/mode_<n>/latest.json + its summary JSON.

        Used by the frontend to show "lib-P87 (15/17)" style relative
        ranking on KPI cards so the operator sees where the current
        machine stands within the whole library instead of reading
        absolute numbers in isolation.

        Scales linearly with the number of (machine, mode) pairs --
        each one is a single JSON read. For hundreds of machines
        this runs in well under a second; no caching needed.

        Shape:
            {
              "machines_count": N,
              "metrics": {
                "volatility_score": {"values": [...], "count": N},
                "zero_win_rate": {...},
                "tail_dependency_ge10x": {...},
                "big_win_x10_rate": {...},
                "profit_spin_rate": {...}
              },
              "archetype_counts": {"Boom-Bust": 2, "Balanced": 3, ...},
              "volatility_class_counts": {"Very High": 4, "High": 1, ...}
            }
        """
        from collections import defaultdict as _dd

        metric_values: dict[str, list[float]] = _dd(list)
        archetype_counts: dict[str, int] = _dd(int)
        volatility_class_counts: dict[str, int] = _dd(int)
        machine_count = 0

        if not rr.exists():
            return {
                "machines_count": 0,
                "metrics": {},
                "archetype_counts": {},
                "volatility_class_counts": {},
            }
        for machine_dir in sorted(rr.iterdir()):
            if not machine_dir.is_dir():
                continue
            for mode_dir in sorted(machine_dir.glob("mode_*")):
                latest_path = mode_dir / "latest.json"
                if not latest_path.exists():
                    continue
                try:
                    latest_data = json.loads(latest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                summary_file = latest_data.get("summary_file")
                if not summary_file:
                    continue
                summary_path = Path(summary_file)
                if not summary_path.exists():
                    continue
                try:
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                machine_count += 1
                ga = summary.get("guideline_assessment", {}) or {}
                derived = ga.get("derived_metrics", {}) or {}
                cls = ga.get("classification", {}) or {}
                player = summary.get("player_impact", {}) or {}
                hit = player.get("hit_and_payout", {}) or {}
                streaks = player.get("streaks", {}) or {}
                zero_win = hit.get("zero_win_rate")
                tail_ge10 = derived.get("tail_dependency_ge10x")
                if tail_ge10 is None:
                    tail_ge10 = derived.get("tail_dependency")
                loss_p95 = streaks.get("loss_streak_p95")
                big_win_x10 = hit.get("big_win_x10_rate")
                profit_spin = hit.get("profit_spin_rate")

                # Composite volatility score mirrors classify_volatility
                # -- max(zero_win/0.82, loss_p95/18, tail/0.50). 1.0 is
                # the Very High threshold; values above that fall into
                # Very High territory. Ranking this across the library
                # gives a continuous "how intense" reading that the
                # discrete Very High/High/Medium/Low label can't.
                if zero_win is not None and tail_ge10 is not None and loss_p95 is not None:
                    try:
                        vol_score = max(
                            float(zero_win) / 0.82,
                            float(loss_p95) / 18.0,
                            float(tail_ge10) / 0.50,
                        )
                        metric_values["volatility_score"].append(vol_score)
                    except (TypeError, ValueError):
                        pass
                for name, raw in (
                    ("zero_win_rate", zero_win),
                    ("tail_dependency_ge10x", tail_ge10),
                    ("big_win_x10_rate", big_win_x10),
                    ("profit_spin_rate", profit_spin),
                ):
                    if raw is None:
                        continue
                    try:
                        metric_values[name].append(float(raw))
                    except (TypeError, ValueError):
                        pass
                arch = cls.get("experience_archetype")
                if arch:
                    archetype_counts[str(arch)] += 1
                vol_cls = cls.get("volatility_class")
                if vol_cls:
                    volatility_class_counts[str(vol_cls)] += 1

        return {
            "machines_count": machine_count,
            "metrics": {
                k: {"values": v, "count": len(v)} for k, v in metric_values.items()
            },
            "archetype_counts": dict(archetype_counts),
            "volatility_class_counts": dict(volatility_class_counts),
        }

    @app.get("/api/cache/status")
    def cache_status() -> dict[str, Any]:
        total_bytes, file_count = folder_bytes(cr)
        running = store.list_runs_by_status("running", limit=2000)
        return {
            "cache_root": str(cr),
            "total_bytes": total_bytes,
            "file_count": file_count,
            "running_runs": len(running),
            "reclaimable_bytes_estimate": total_bytes if not running else 0,
            "risk_thresholds": resolved_risk_thresholds(),
        }

    @app.post("/api/cache/cleanup")
    def cache_cleanup(req: CacheCleanupRequest) -> dict[str, Any]:
        running = store.list_runs_by_status("running", limit=2000)
        if running:
            return {
                "deleted_files": 0,
                "deleted_bytes": 0,
                "message": "cleanup blocked while runs are active",
            }
        if not ops.acquire("cache_cleanup"):
            snap = ops.snapshot()
            raise HTTPException(status_code=409, detail=f"system busy: {snap.get('operation') or 'unknown'}")

        try:
            deleted_files = 0
            deleted_bytes = 0
            targets = sorted(
                [p for p in cr.rglob("*") if p.is_file()],
                key=lambda p: p.stat().st_mtime,
            )
            max_delete = req.max_delete_bytes if req.max_delete_bytes > 0 else (10**18)
            for file in targets:
                size = file.stat().st_size
                if deleted_bytes + size > max_delete:
                    break
                file.unlink(missing_ok=True)
                deleted_files += 1
                deleted_bytes += size
            return {"deleted_files": deleted_files, "deleted_bytes": deleted_bytes}
        finally:
            ops.release()

    @app.post("/api/interpretations")
    def create_interpretation(req: InterpretationRequest) -> dict[str, Any]:
        row = store.get_run(req.run_id)
        if not row:
            raise HTTPException(status_code=404, detail="run not found")
        summary_path = Path(row["summary_file"])
        if not summary_path.exists():
            raise HTTPException(status_code=400, detail="run summary not ready")
        summary = read_json(summary_path)
        runtime = model_runtime.snapshot()
        provider = runtime["provider"]
        api_key = runtime["api_key"]
        allowed_models = PROVIDER_MODELS.get(provider, [])
        if req.model_id not in allowed_models:
            raise HTTPException(
                status_code=400,
                detail=f"model_id not allowed for provider={provider}: {req.model_id}",
            )

        content = ""
        source = "rule-based"
        warning = ""
        if not api_key:
            warning = f"{provider.upper()} API key is empty; switched to rule-based interpretation."
            content = create_interpretation_content(summary, req.model_id)
        else:
            try:
                content = call_remote_interpreter(summary, req.model_id, provider, api_key)
                source = f"remote-{provider}"
            except Exception as exc:
                warning = (
                    f"{provider.upper()} remote model failed ({type(exc).__name__}); "
                    "switched to rule-based interpretation."
                )
                content = create_interpretation_content(summary, req.model_id)

        store.insert_interpretation(req.run_id, req.model_id, content, source=source, warning=warning)
        return {
            "run_id": req.run_id,
            "model_id": req.model_id,
            "provider": provider,
            "source": source,
            "warning": warning,
            "content": content,
        }

    @app.get("/api/interpretations/{run_id}")
    def latest_interpretation(run_id: str) -> dict[str, Any]:
        payload = store.latest_interpretation(run_id)
        if not payload:
            return {
                "run_id": run_id,
                "content": "",
                "model_id": "",
                "source": "",
                "warning": "",
                "created_at": "",
            }
        return payload

    return app

