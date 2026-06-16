"""Retention policy for per-mode report version dirs.

Every `batch_generate_reports --force` run (and every `/api/reports/import`
of fresh dev output) appends a new `rv_<ts>_<sha>` directory under
`reports/<machine>/mode_<N>/versions/`. Nothing trims them — so after
three regens the 1006-report fleet has 3× the disk footprint even though
only the newest version is ever shown.

This module provides a retention pass that keeps the newest N versions
per (machine, mode) and removes older ones cleanly:

1. Discover version dirs under `<reports_root>/<machine>/mode_<N>/versions/`.
   Sort by directory name (ISO timestamp prefix = chronological).
2. For each version past the keep window:
   - Skip if any DB run row still has status="running" or "importing"
     (don't race an active writer).
   - Otherwise `rmtree` the dir and `delete_run` the matching DB rows.
3. Rebuild `index.json` + `latest.json` for that mode from the remaining
   version dirs so the UI's version picker stays in sync.

`dry_run=True` reports the deletions that *would* happen without
touching disk or DB — useful for the CLI's default safety net.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Protocol

from src.web_console.backend.report_index import (
    build_index_entry,
    _atomic_write_json,
    _report_index_lock,
)


# Version-dir names sort chronologically by their ISO timestamp prefix
# (`rv_YYYYMMDDTHHMMSSZ_...`), so string-sort is effectively time-sort.
VERSION_PREFIX = "rv_"
MODE_PREFIX = "mode_"


class _Store(Protocol):
    """Minimal interface the retention pass needs from the run store.

    Kept as a protocol so tests can fake it without instantiating
    ReportsStore + sqlite.
    """
    def list_runs_by_report_version(self, version: str) -> list[dict[str, Any]]: ...
    def delete_run(self, run_id: str) -> bool: ...


def prune_versions(
    reports_root: Path,
    store: _Store,
    keep_last: int = 5,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Keep newest `keep_last` version dirs per (machine, mode); prune rest.

    Returns a structured report so CLI / API callers can show exactly
    what happened (or what would happen in dry-run).
    """
    if keep_last < 1:
        raise ValueError(f"keep_last must be >= 1, got {keep_last}")

    result: dict[str, Any] = {
        "keep_last": keep_last,
        "dry_run": dry_run,
        "versions_kept": 0,
        "versions_deleted": 0,
        "db_rows_deleted": 0,
        "skipped_active_runs": 0,
        "machines_touched": [],
        "deleted_paths": [],
        "errors": [],
    }
    if not reports_root.is_dir():
        return result
    touched: set[str] = set()

    for machine_dir in sorted(reports_root.iterdir()):
        if not machine_dir.is_dir() or machine_dir.name.startswith("_"):
            continue
        for mode_dir in sorted(machine_dir.iterdir()):
            if not mode_dir.is_dir() or not mode_dir.name.startswith(MODE_PREFIX):
                continue
            versions_dir = mode_dir / "versions"
            if not versions_dir.is_dir():
                continue

            version_dirs = sorted(
                [d for d in versions_dir.iterdir()
                 if d.is_dir() and d.name.startswith(VERSION_PREFIX)],
                key=lambda p: p.name,
                reverse=True,  # newest first
            )
            if len(version_dirs) <= keep_last:
                result["versions_kept"] += len(version_dirs)
                continue

            keep = version_dirs[:keep_last]
            drop = version_dirs[keep_last:]
            result["versions_kept"] += len(keep)

            any_deleted_in_this_mode = False
            for vdir in drop:
                matching = store.list_runs_by_report_version(vdir.name)
                active = [r for r in matching
                          if r.get("status") in ("running", "importing")]
                if active:
                    result["skipped_active_runs"] += 1
                    # Keep the version — active run is still writing to it.
                    continue

                result["deleted_paths"].append(str(vdir))
                result["versions_deleted"] += 1
                if dry_run:
                    continue
                try:
                    shutil.rmtree(vdir)
                    any_deleted_in_this_mode = True
                except OSError as exc:
                    result["errors"].append({
                        "path": str(vdir),
                        "error": f"rmtree: {type(exc).__name__}: {exc}",
                    })
                    continue
                for r in matching:
                    try:
                        if store.delete_run(r["run_id"]):
                            result["db_rows_deleted"] += 1
                    except Exception as exc:  # noqa: BLE001
                        result["errors"].append({
                            "run_id": r.get("run_id"),
                            "error": f"delete_run: {type(exc).__name__}: {exc}",
                        })
                touched.add(machine_dir.name)

            if any_deleted_in_this_mode and not dry_run:
                try:
                    _refresh_mode_manifests(mode_dir)
                except OSError as exc:
                    result["errors"].append({
                        "path": str(mode_dir),
                        "error": f"refresh_manifest: {type(exc).__name__}: {exc}",
                    })

    result["machines_touched"] = sorted(touched)
    return result


def _refresh_mode_manifests(mode_dir: Path, reports_root: Path | None = None) -> None:
    """Rebuild ``index.json`` + ``latest.json`` from the surviving version dirs.

    Both files are derived state — the version dirs are authoritative.
    Routes through ``build_index_entry`` so the rebuilt index always
    carries the full shape (rawdata md5 / analyzer version / etc.), not
    the minimal rtp_point_pct + quality_label subset the old in-place
    implementation wrote.

    ``reports_root`` is used by ``build_index_entry`` to form canonical
    absolute paths.  When omitted the mode_dir is used as the fallback
    anchor (correct when mode_dir is already under the canonical tree).
    """
    versions_dir = mode_dir / "versions"
    index_path = mode_dir / "index.json"
    latest_path = mode_dir / "latest.json"

    # Derive machine / mode from the mode_dir path convention
    # (<reports_root>/<machine>/mode_<N>/versions/).
    mode_dir_parent = mode_dir.parent   # <reports_root>/<machine>/
    machine_name = mode_dir_parent.name
    try:
        mode_int = int(mode_dir.name.split("_", 1)[1])
    except (IndexError, ValueError):
        mode_int = 0
    rr = reports_root if reports_root is not None else mode_dir_parent.parent

    entries: list[dict[str, Any]] = []
    if versions_dir.is_dir():
        for vdir in sorted(
            [d for d in versions_dir.iterdir()
             if d.is_dir() and d.name.startswith(VERSION_PREFIX)],
            key=lambda p: p.name,
        ):
            summary_path = vdir / "player_impact_summary.json"
            if not summary_path.exists():
                continue
            try:
                s = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            run_id = str(s.get("run_id") or "")
            entry = build_index_entry(
                rr,
                machine_name,
                mode_int,
                vdir.name,
                run_id,
                summary=s,
                summary_path=summary_path,
            )
            entries.append(entry)

    with _report_index_lock(mode_dir):
        _atomic_write_json(index_path, entries)
        if entries:
            latest = max(
                enumerate(entries),
                key=lambda ie: (
                    str(ie[1].get("created_at") or ""),
                    str(ie[1].get("report_version") or ""),
                    ie[0],
                ),
            )[1]
            _atomic_write_json(latest_path, latest)
        elif latest_path.exists():
            try:
                latest_path.unlink()
            except OSError:
                pass


