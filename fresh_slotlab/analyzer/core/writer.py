"""Atomic chunk-cache writer + summary JSON writer, carved from
``player_impact_analyzer.py``.

P2-B3 (Phase 2 / Wave 2b): moves two functions out of PIA into this
canonical module. PIA re-exports both via its dual-path import block so
all existing callers keep resolving via ``fresh_slotlab.player_impact_analyzer``.

Functions:
  _save_chunk_cache   — atomic write of raw API response to a cache file.
  write_summary_json  — thin helper: serialises the analysis summary dict
                        to ``<output_dir>/player_impact_summary.json``.

Module-level constants exported (canonical source):
  CHUNK_CACHE_VERSION — bumped when the envelope schema changes (not when
                        analyser logic changes; raw data is analyser-agnostic).
  utc_now             — ISO-8601 UTC timestamp helper.

Architecture reference:
  session_artifacts/_arch/04_architecture_proposal_v5.md §6.2 deliverable 1.

Cycle-freedom contract (ticket §3 C5):
  MUST NOT import from ``fresh_slotlab.player_impact_analyzer``.
  MAY import from ``core/parser.py`` (_payload_sha256,
  _compute_upstream_schema_fingerprint).
  MAY import from ``fresh_slotlab.chunk_index`` (update_chunk_entry).

Per memory feedback_subprocess_import_suicide_and_module_globals.md:
  No I/O at import time. Constants + function defs only.

Per memory feedback_no_silent_swallow.md:
  The bare ``except`` clauses inside ``_save_chunk_cache`` for cleanup
  are PRESERVED VERBATIM from PIA. No new silent swallows added.

Per memory feedback_md5_granularity_and_stamping.md:
  The ``override_config_md5`` / ``override_code_md5`` path is the
  virtual-machine localcfg stamp that segregates chunks into
  ``localcfg_<hash>`` buckets. Must be preserved exactly.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Dual-path import of _payload_sha256 and _compute_upstream_schema_fingerprint
# from core/parser.py (already carved in P2-B1a).
# Package-mode path in the try arm; standalone-script fallback (fresh_slotlab/
# on sys.path) in the except arm.  Mirrors the pattern in aggregator.py.
try:
    from fresh_slotlab.analyzer.core.parser import (
        _compute_upstream_schema_fingerprint,
        _payload_sha256,
    )
except ImportError:  # running as a standalone script
    from analyzer.core.parser import (  # type: ignore[no-redef]
        _compute_upstream_schema_fingerprint,
        _payload_sha256,
    )

# Dual-path import of update_chunk_entry from fresh_slotlab.chunk_index.
# chunk_index has no dependency on PIA so this does NOT create a cycle.
try:
    from fresh_slotlab.chunk_index import update_chunk_entry
except ImportError:  # running as a standalone script
    from chunk_index import update_chunk_entry  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Module-level constants (canonical source — PIA re-imports these)
# ---------------------------------------------------------------------------

# Cache envelope version.  Bumped when the wrapping envelope schema changes
# (not when analyzer code changes — raw API data is analyzer-agnostic).
# v3: added _payload_sha256 + atomic (.tmp + os.replace) write.
CHUNK_CACHE_VERSION = 3


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Chunk-cache writer
# ---------------------------------------------------------------------------

def _save_chunk_cache(
    resp: Any,
    chunk_index: int,
    machine: str,
    rtp_mode: int,
    bet: int,
    spin_times: int,
    robot_count: int,
    cache_dir: Path | None,
    override_config_md5: str = "",
    override_code_md5: str = "",
    *,
    lookup_machine_md5: Callable[[str], tuple[str, str]],
    rawdata_index_update_entry: Callable[..., None] | None = None,
) -> None:
    """Best-effort atomic write of the raw API response to a cache file.

    Writes to ``chunk_NNNN.json.tmp`` first, then ``os.replace`` to the
    final path. This guarantees the reader never sees a half-written
    file — either the full new chunk is present or the previous (or
    nothing) is. Payload sha256 is stamped in the envelope so later
    reads can detect silent corruption from e.g. disk block errors.

    Silent on failure so a disk-full or permissions error doesn't abort
    the sampling run. Leftover ``.tmp`` files (from a failed replace) are
    cleaned up on the way out to avoid accumulating garbage.

    ``override_config_md5`` / ``override_code_md5`` — when non-empty,
    stamp the envelope with these values INSTEAD of
    ``lookup_machine_md5(machine)``'s machines.json global lookup.
    This is what segregates chunks produced with a per-request
    MachineConfig override into their own ``localcfg_<hash>`` md5
    bucket (otherwise all chunks inherit the server's global md5 and
    mix with non-override samples on resume). Mirrors the fix applied
    to the report summary stamp (commit 334d6a9) — same root cause,
    adjacent writer.

    ``lookup_machine_md5`` — injected callable (no direct import of PIA
    to avoid the writer → PIA cycle). Signature:
        ``(machine: str) -> tuple[str, str]``  (config_md5, code_md5)

    ``rawdata_index_update_entry`` — optional injected callable for the
    rawdata index side-effect. When None the side-effect is skipped
    (matches the old behaviour when the import was best-effort).
    """
    if cache_dir is None:
        return
    out_path = cache_dir / f"chunk_{chunk_index:04d}.json"
    tmp_path = cache_dir / f"chunk_{chunk_index:04d}.json.tmp"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        if override_config_md5 or override_code_md5:
            config_md5 = override_config_md5 or ""
            code_md5 = override_code_md5 or ""
        else:
            config_md5, code_md5 = lookup_machine_md5(machine)
        envelope = {
            "_cache_version": CHUNK_CACHE_VERSION,
            "_machine": machine,
            "_mode": rtp_mode,
            "_bet": bet,
            "_spin_times": spin_times,
            "_robot_count": robot_count,
            "_chunk_index": chunk_index,
            "_saved_at": utc_now(),
            "_config_md5": config_md5,
            "_code_md5": code_md5,
            "_upstream_schema_fingerprint": _compute_upstream_schema_fingerprint(resp),
            "_payload_sha256": _payload_sha256(resp),
            "response": resp,
        }
        tmp_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, out_path)
        # Update the rawdata index so UI reads stay O(1). Best-effort:
        # failure here only means the next UI status refresh falls back
        # to a filesystem scan (which self-heals the index).
        try:
            if rawdata_index_update_entry is not None:
                # cache_dir is `<rawdata_root>/<machine>/mode_<N>`; the index
                # lives at `<rawdata_root>/_index.json`.
                rawdata_root = cache_dir.parent.parent
                rawdata_index_update_entry(rawdata_root, machine, rtp_mode, cache_dir)
        except Exception:  # noqa: BLE001
            pass
        # Per-mode chunk metadata sidecar — lets resume-replay +
        # rawdata-status skip full ``json.loads`` on historical
        # chunks. Writes ``mode_<N>/_chunks.json`` atomically.
        # Swallows failures itself; chunk file is already durable.
        try:
            update_chunk_entry(
                cache_dir, out_path,
                chunk_index=chunk_index,
                config_md5=config_md5,
                code_md5=code_md5,
                spin_times=spin_times,
                robot_count=robot_count,
                saved_at=envelope["_saved_at"],
            )
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        # Clean up a stale .tmp so we don't accumulate partials from
        # repeated failures. The final chunk file (if any) is left
        # untouched — a successful prior write stays valid.
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Summary JSON writer
# ---------------------------------------------------------------------------

def write_summary_json(summary: dict, output_dir: Path) -> Path:
    """Serialise *summary* to ``<output_dir>/player_impact_summary.json``.

    Returns the Path of the written file so callers can chain or log it.

    Extracted from ``main()`` lines 5262-5263 (P2-B3 §1). Keeping it as
    a named helper makes future feature writers (per §6.2 deliverable
    "feature_<name>.py emit to writer") easy to hook in.
    """
    out = output_dir / "player_impact_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
