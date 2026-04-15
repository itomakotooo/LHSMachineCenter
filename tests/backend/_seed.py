"""DB seed helper for backend tests.

Self-contained: does NOT import from src.web_console.backend.app, so adding
this helper to a test does not pull in any side effects from the production
module (even if app.py later regresses to import-time work).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Mirror StateStore._init_db so every NOT NULL column has a sane default.
_DEFAULTS: dict[str, Any] = {
    "run_id": "stale001",
    "machine": "M14",
    "mode": 1,
    "status": "running",
    "model_id": "gpt-5.4-mini",
    "created_at": None,            # filled with _utc_now() in insert_run_row
    "started_at": None,            # filled with _utc_now() in insert_run_row
    "finished_at": None,
    "target_halfwidth_pp": 0.5,
    "chunk_spin_times": 5000,
    "chunk_robot_count": 20,
    "batch_concurrency": 2,
    "max_chunks": 120,
    "timeout": 300.0,
    "bankruptcy_session_spins": 500,
    "bankruptcy_bankroll_multipliers": "100,200,500",
    "report_version": "rv_old",
    "output_dir": "/tmp/o",
    "progress_file": "/tmp/p",
    "summary_file": None,
    "report_file": None,
    "error_message": None,
    "process_pid": 42424,
}


_SCHEMA = """
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
  error_message TEXT,
  process_pid INTEGER
);
"""


def insert_run_row(db_path, **overrides) -> str:
    """Insert one runs row, filling NOT NULL columns with sensible defaults.

    Returns the run_id of the inserted row. Overrides any default by passing
    the column name as a keyword argument, e.g.
        insert_run_row(db_path, run_id="abc", status="completed").
    """
    row = {**_DEFAULTS, **overrides}
    if row["created_at"] is None:
        row["created_at"] = _utc_now()
    if row["started_at"] is None:
        row["started_at"] = _utc_now()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA)
        cols = ", ".join(row.keys())
        marks = ", ".join(["?"] * len(row))
        conn.execute(
            f"INSERT INTO runs ({cols}) VALUES ({marks})",
            list(row.values()),
        )
        conn.commit()
    finally:
        conn.close()
    return str(row["run_id"])
