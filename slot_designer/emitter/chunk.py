"""Emit chunk envelope + write to disk. Matches existing v2 schema.

v2 (no payload sha256) is accepted by existing ``load_chunk_envelope``.
v3 would require computing the canonical payload hash identically to
fresh_slotlab; we stick to v2 to stay decoupled.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def compute_schema_fingerprint(first_round: dict) -> str:
    """sha256[:16] of sorted-key set of the first round — matches analyzer's
    ``_compute_upstream_schema_fingerprint``.
    """
    keys = sorted(first_round.keys())
    return hashlib.sha256("|".join(keys).encode()).hexdigest()[:16]


def emit_chunk(
    robots: list[dict],
    *,
    machine: str,
    mode: int,
    bet: int,
    spin_times: int,
    robot_count: int,
    chunk_index: int,
    upstream_schema_fingerprint: str,
    config_md5: str = "",
    code_md5: str = "",
    cache_version: int = 2,
    dev_sample: bool = True,
) -> dict:
    """Wrap robots in the envelope produced by existing sampling pipeline."""
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return {
        "_cache_version": cache_version,
        "_machine": machine,
        "_mode": mode,
        "_bet": bet,
        "_spin_times": spin_times,
        "_robot_count": robot_count,
        "_chunk_index": chunk_index,
        "_saved_at": now,
        "_config_md5": config_md5,
        "_code_md5": code_md5,
        "_upstream_schema_fingerprint": upstream_schema_fingerprint,
        "_dev_sample": dev_sample,
        "response": robots,
    }


def write_chunk(chunk: dict, out_dir: Path, chunk_index: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"chunk_{chunk_index:04d}.json"
    path.write_text(json.dumps(chunk, ensure_ascii=False), encoding="utf-8")
    # Per-mode chunk metadata sidecar (shared module — same format
    # as real analyzer's ``_persist_chunk``). Lets virtual-side
    # readers (pre-sample scan, virtual rawdata status) skip full
    # chunk-file parse when only envelope md5s are needed. Best-
    # effort: sidecar failure never blocks a successful chunk write.
    try:
        from fresh_slotlab.chunk_index import update_chunk_entry
        update_chunk_entry(
            out_dir, path,
            chunk_index=int(chunk.get("_chunk_index", chunk_index)),
            config_md5=str(chunk.get("_config_md5", "") or ""),
            code_md5=str(chunk.get("_code_md5", "") or ""),
            spin_times=int(chunk.get("_spin_times", 0) or 0),
            robot_count=int(chunk.get("_robot_count", 0) or 0),
            saved_at=str(chunk.get("_saved_at", "") or "") or None,
        )
    except Exception:  # noqa: BLE001
        pass
    return path
