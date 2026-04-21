"""Virtual-machine analyzer — CLI-compatible drop-in for player_impact_analyzer.py.

The real console's backend spawns the analyzer as a subprocess with a
specific CLI (--machine, --rtp-mode, --chunk-spin-times, --chunk-robot-count,
--max-chunks, --output-dir, --progress-file, --stop-flag-file, --from-cache,
--resume-from-cache, --chunk-cache-dir, ...).

For virtual machines, we REPLACE the HTTP sampling step with our simulator,
then DELEGATE to the real analyzer's --from-cache path for all the heavy
analysis work (RTP / bucket / streaks / bankruptcy simulation / etc.).

Flow:

  --from-cache ONLY     → straight delegate to real analyzer (no sim needed)
  --resume-from-cache   → load existing chunks, resume sim from next index
  otherwise             → fresh sim → emit chunks → delegate --from-cache

This keeps the real analyzer 100% untouched and inherits every feature /
bugfix / metric it gains over time.

Known-unsupported CLI args (gracefully no-op'd):
  --endpoint-url           (no upstream in virtual mode)
  --batch-concurrency      (sim is sequential; accepted but ignored)
  --timeout                (simulator doesn't hang on IO; accepted)

Forwarded to delegate analysis (but not consumed in virtual sampling):
  --upstream-config-md5    (2026-04-21, 8f74213 on real analyzer —
  --upstream-code-md5       chunks tagged with a different md5 get
                            filtered out of stats during replay)

Unknown flags (future backend additions): accepted via
``parse_known_args`` so virtual sampling doesn't error out, but NOT
forwarded to the delegated real-analyzer call — the real analyzer
uses strict ``parse_args`` and would reject unrecognized flags. When
a new analyzer flag ships and virtual mode needs to honor it,
declare it explicitly here and extend ``_build_delegate_cmd``.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.backend.machine_version import compute_machine_md5
# virtual_registry is DELIBERATELY the only registry import here.
# Importing virtual_app instead would trigger its top-level
# ``app = build_virtual_app()`` → RunManager.__init__ →
# _recover_orphan_running_runs, which would terminate the pid of the
# currently-"running" run in the DB — i.e. this very subprocess. See
# virtual_registry.py docstring for the full incident notes.
from slot_designer.backend.virtual_registry import (
    VIRTUAL_MACHINES_CONFIG,
    refresh_machines_virtual,
)
from slot_designer.emitter.chunk import compute_schema_fingerprint, emit_chunk, write_chunk
from slot_designer.emitter.robot import emit_robot
from slot_designer.emitter.round import emit_round
from slot_designer.engine.loader import load_engine


REAL_ANALYZER = _ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
# Legacy alias kept so external callers importing VIRTUAL_REGISTRY from
# this module keep working. New code should import
# VIRTUAL_MACHINES_CONFIG from virtual_registry directly.
VIRTUAL_REGISTRY = VIRTUAL_MACHINES_CONFIG


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _append_jsonl(path: Path | None, payload: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _check_stop_flag(stop_flag: Path | None) -> bool:
    return stop_flag is not None and stop_flag.exists()


def _parse_args() -> tuple[argparse.Namespace, list[str]]:
    """Mirror the real analyzer's argparse — declare args we consume or
    need to forward verbatim; everything else goes through
    ``parse_known_args`` so unknown flags pass through to the delegated
    real-analyzer call instead of erroring out here.

    History: pre-2026-04-21 this used strict ``parse_args`` despite the
    docstring claiming otherwise, which meant commit 8f74213 (which
    added ``--upstream-config-md5`` / ``--upstream-code-md5`` to the
    analyzer CLI) broke every virtual-machine batch-run until this fix.
    """
    p = argparse.ArgumentParser(description="Virtual-machine analyzer (sim + delegate)")
    p.add_argument("--machine", required=True)
    p.add_argument("--rtp-mode", type=int, default=1)
    p.add_argument("--bet", type=int, default=1000)
    p.add_argument("--stop-flag-file", type=Path, default=None)
    p.add_argument("--target-halfwidth-pp", type=float, default=0.5)
    p.add_argument("--chunk-spin-times", type=int, default=5000)
    p.add_argument("--chunk-robot-count", type=int, default=20)
    p.add_argument("--batch-concurrency", type=int, default=2)
    p.add_argument("--max-chunks", type=int, default=120)
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--run-id", default=None)
    p.add_argument("--progress-file", type=Path, default=None)
    p.add_argument("--bankruptcy-session-spins", type=int, default=10000)
    p.add_argument("--bankruptcy-bankroll-multipliers", default="100,200,500")
    p.add_argument("--guideline-rules", type=Path, default=None)
    p.add_argument("--chunk-cache-dir", type=Path, default=None)
    p.add_argument("--from-cache", type=Path, default=None)
    p.add_argument("--resume-from-cache", type=Path, default=None)
    p.add_argument("--endpoint-url", type=str, default=None)
    # Forwarded to delegate analysis for historical-md5 filtering
    # (8f74213). Default "" = no filter on delegate side either.
    p.add_argument("--upstream-config-md5", default="")
    p.add_argument("--upstream-code-md5", default="")
    return p.parse_known_args()


def _load_virtual_registry() -> dict:
    path = _ROOT / "slot_designer" / "configs" / "machines_virtual.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _find_machine_entry(registry: dict, machine: str) -> dict:
    for m in registry.get("machines", []):
        if m.get("machine") == machine:
            return m
    raise RuntimeError(f"virtual machine {machine!r} not in machines_virtual.json")


def _resolve_weights_path(entry: dict, mode: int) -> Path:
    """Pick tuned weights if present, else fall back to current. Virtual
    machines expected to always have at least `.current.json` available.
    """
    templates = [
        entry.get("_weights_path_template"),
        entry.get("_weights_fallback_template"),
    ]
    for tmpl in templates:
        if not tmpl:
            continue
        p = _ROOT / tmpl.format(mode=mode)
        if p.exists():
            return p
    raise RuntimeError(
        f"no weights file found for {entry.get('machine')} mode {mode}; "
        f"looked at {templates}"
    )


def _spec_path(entry: dict) -> Path:
    rel = entry.get("_spec_path")
    if not rel:
        raise RuntimeError(f"{entry.get('machine')}: missing _spec_path in registry")
    return _ROOT / rel


def _run_simulator_chunk(
    engine, spec: dict, chunk_index: int, robots: int, spins_per_robot: int,
    rng: Random, schema_fp: str, md5s: tuple[str, str],
    initial_credits: int = 1_000_000_000,
) -> tuple[dict, int, int]:
    """Produce ONE chunk dict (plus running win/bet totals)."""
    config_md5, code_md5 = md5s
    robot_list = []
    chunk_win = 0
    chunk_bet = 0
    for _ in range(robots):
        last_credits = initial_credits
        rounds: list[dict] = []
        for _i in range(spins_per_robot):
            out = engine.spin(rng)
            rd = emit_round(
                out,
                last_credits=last_credits,
                spin_times=spins_per_robot,
                rtp_id=int(spec["mode"]),
            )
            rounds.append(rd)
            last_credits = last_credits - out.cost_credits + rd["WinCredits"]
            chunk_win += rd["WinCredits"]
            chunk_bet += out.bet_amount
        robot_list.append(emit_robot(rounds, bet=engine.bet_amount))

    chunk = emit_chunk(
        robot_list,
        machine=spec["machine"],
        mode=int(spec["mode"]),
        bet=engine.bet_amount,
        spin_times=spins_per_robot,
        robot_count=robots,
        chunk_index=chunk_index,
        upstream_schema_fingerprint=schema_fp,
        config_md5=config_md5,
        code_md5=code_md5,
    )
    return chunk, chunk_win, chunk_bet


# ── Session-level CI check (2026-04-21) ─────────────────────────────
# Mirrors real analyzer's session_halfwidth_pp so virtual sampling can
# stop once the user's CI target is met. Prior behavior: sim loop only
# honored max_chunks + stop_flag, so a 5pp target would still run to
# 120 chunks even when 3 chunks' worth of data already satisfied the
# target. Users had to manually stop.

# Two-sided 95% t-critical table for small N; above N=30 we fall back
# to 1.96 (same cutoff the real analyzer uses). Keeps small-session
# CIs honest without dragging scipy in.
_T_CRITICAL_95_TABLE = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def _t_critical_95(df: int) -> float:
    if df <= 0:
        return 12.706  # N=1 sentinel — should never be reached (guarded by n<=1 check)
    return _T_CRITICAL_95_TABLE.get(df, 1.96)


def _ci_halfwidth_pp(n: int, ret_sum: float, ret_sq_sum: float) -> float | None:
    """Session-level 95% CI half-width in percentage points. ``None``
    when n ≤ 1 (variance undefined). Matches the formula used by the
    real analyzer so virtual sampling's stop decision and the delegated
    report's reported CI agree.
    """
    if n <= 1:
        return None
    var = max(0.0, (ret_sq_sum - (ret_sum * ret_sum) / n) / (n - 1))
    if var == 0.0:
        return 0.0
    se = math.sqrt(var / n)
    t = _t_critical_95(n - 1)
    return t * se * 100.0


def _session_returns_from_chunk_dict(chunk: dict) -> list[float]:
    """Extract per-robot session return multiplier (``ret_x =
    total_win / total_bet``) for each robot in a chunk dict.

    Each robot is treated as one session — matches the real analyzer's
    ``session_bucket_bet`` / ``session_bucket_win`` accumulation granularity
    (one bucket per robot, one CI sample per robot).
    """
    out: list[float] = []
    for robot in chunk.get("response") or []:
        rr = robot.get("roundResult")
        if isinstance(rr, str):
            try:
                rounds = json.loads(rr)
            except (json.JSONDecodeError, ValueError):
                continue
        elif isinstance(rr, list):
            rounds = rr
        else:
            continue
        total_win = 0
        total_bet = 0
        for rd in rounds:
            if not isinstance(rd, dict):
                continue
            total_win += int(rd.get("WinCredits", 0) or 0)
            total_bet += int(rd.get("BetAmount", 0) or 0)
        if total_bet > 0:
            out.append(total_win / total_bet)
    return out


def _load_existing_session_stats(
    rawdata_dir: Path,
    md5_filter: tuple[str, str] | None,
) -> tuple[int, float, float]:
    """Walk existing ``chunk_*.json`` in ``rawdata_dir`` and accumulate
    session-level ``(n, ret_sum, ret_sq_sum)`` for CI computation.

    When ``md5_filter`` is set, skips chunks whose envelope md5 pair
    differs from the caller's expected pair — keeps historical-md5
    chunks from polluting the CI estimate (same principle as the real
    analyzer's ``--upstream-*-md5`` filter during --from-cache replay).

    Returns (0, 0.0, 0.0) on empty / missing dir.
    """
    if not rawdata_dir.is_dir():
        return 0, 0.0, 0.0
    n = 0
    ret_sum = 0.0
    ret_sq_sum = 0.0
    for cf in sorted(rawdata_dir.glob("chunk_*.json")):
        try:
            data = json.loads(cf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if md5_filter:
            cfg = str(data.get("_config_md5", "") or "")
            code = str(data.get("_code_md5", "") or "")
            if cfg != md5_filter[0] or code != md5_filter[1]:
                continue
        for rx in _session_returns_from_chunk_dict(data):
            n += 1
            ret_sum += rx
            ret_sq_sum += rx * rx
    return n, ret_sum, ret_sq_sum


def _compute_md5s(entry: dict) -> tuple[str, str]:
    """Compute FRESH (config_md5, code_md5) for this machine at sample
    time, not just read the registry cache. This way a chunk stamp always
    matches the current (spec, weights, engine) snapshot, even if the
    registry JSON is mid-refresh or stale.

    The refresh_machines_virtual() write that matches this comes from the
    virtual_app layer (on console boot) or can be invoked explicitly via
    the same helper — both use the same `compute_machine_md5`.
    """
    return compute_machine_md5(entry)


def _build_delegate_cmd(
    original_args: argparse.Namespace,
    from_cache_dir: Path,
) -> list[str]:
    """Construct the argv for the delegated real-analyzer call.

    Split out as a pure function so tests can assert flag passthrough
    without having to spawn a real subprocess.

    NOTE: we only forward flags the real analyzer explicitly knows
    about. Unknown ``extras`` captured by virtual_analyzer's
    ``parse_known_args`` are INTENTIONALLY dropped here — the real
    analyzer uses strict ``parse_args`` and would rc=2 on anything
    unrecognized. New flags that virtual sampling should honor require
    a parallel add here + in ``_parse_args``.
    """
    cmd = [
        sys.executable, str(REAL_ANALYZER),
        "--machine", original_args.machine,
        "--rtp-mode", str(original_args.rtp_mode),
        "--bet", str(original_args.bet),
        "--output-dir", str(original_args.output_dir),
        "--target-halfwidth-pp", "0.001",   # don't CI-stop; process all chunks we produced
        "--max-chunks", "99999",
        "--from-cache", str(from_cache_dir),
        "--chunk-spin-times", str(original_args.chunk_spin_times),
        "--chunk-robot-count", str(original_args.chunk_robot_count),
        "--batch-concurrency", str(original_args.batch_concurrency),
        "--timeout", str(original_args.timeout),
        "--bankruptcy-session-spins", str(original_args.bankruptcy_session_spins),
        "--bankruptcy-bankroll-multipliers", original_args.bankruptcy_bankroll_multipliers,
    ]
    if original_args.run_id:
        cmd.extend(["--run-id", original_args.run_id])
    if original_args.progress_file:
        cmd.extend(["--progress-file", str(original_args.progress_file)])
    if original_args.stop_flag_file:
        cmd.extend(["--stop-flag-file", str(original_args.stop_flag_file)])
    if original_args.guideline_rules:
        cmd.extend(["--guideline-rules", str(original_args.guideline_rules)])
    # 2026-04-21: forward upstream md5 filter so historical-md5 virtual
    # chunks are excluded from stats during replay (matches real-analyzer
    # behavior since 8f74213). Only forward when non-empty — empty means
    # "no filter" on both sides.
    if original_args.upstream_config_md5:
        cmd.extend(["--upstream-config-md5", original_args.upstream_config_md5])
    if original_args.upstream_code_md5:
        cmd.extend(["--upstream-code-md5", original_args.upstream_code_md5])
    return cmd


def _delegate_to_real_analyzer(
    original_args: argparse.Namespace,
    from_cache_dir: Path,
) -> int:
    """Run the real analyzer with --from-cache, reusing the original args
    that make sense in analysis context. Returns the subprocess's exit code.
    """
    cmd = _build_delegate_cmd(original_args, from_cache_dir)
    return subprocess.call(cmd, cwd=_ROOT)


def main() -> int:
    args, extras = _parse_args()
    if extras:
        # Visible in worker logs so future "why isn't my new flag
        # honored on virtual machines?" diagnostics point at this line.
        print(
            f"virtual_analyzer: ignoring unknown flags {extras!r} "
            f"(declare them in _parse_args + _build_delegate_cmd to honor)"
        )

    # 1. Pure --from-cache: no sim needed, delegate directly
    if args.from_cache and not args.resume_from_cache:
        return _delegate_to_real_analyzer(args, args.from_cache)

    # 2. Resume-from-cache or fresh sample: run simulator to produce chunks,
    #    then delegate with --from-cache.
    # First: refresh registry md5s from current spec/weights/engine so the
    # chunks we're about to write get tagged with the RIGHT md5 even if
    # spec or weights changed since console boot. Writes back to the
    # tracked machines_virtual.json so console's /api/machines etc. read
    # consistent values for the rest of this session.
    # Uses ``virtual_registry`` (no side-effects) rather than
    # ``virtual_app`` (which would import-execute
    # ``app = build_virtual_app()`` and trigger
    # ``_recover_orphan_running_runs`` — that recovery path would then
    # terminate the pid of the currently-"running" run in the DB, which
    # is THIS subprocess. Importing virtual_app here was the 2026-04-21
    # silent-rc=1 suicide bug.
    try:
        refresh_machines_virtual(VIRTUAL_MACHINES_CONFIG)
    except Exception:
        # Non-fatal — if refresh fails we fall back to the cached values.
        # Worst case: chunks tagged with slightly stale md5 → classify_chunks
        # may flag them; operator sees the discrepancy.
        pass

    registry = _load_virtual_registry()
    entry = _find_machine_entry(registry, args.machine)
    spec_path = _spec_path(entry)
    weights_path = _resolve_weights_path(entry, args.rtp_mode)
    engine, spec = load_engine(spec_path, weights_path)

    # For virtual machines, rawdata is the single source of truth — every
    # sampling run APPENDS to the rawdata pool (not a scratch cache). This
    # matches the real analyzer's --resume-from-cache behavior and makes
    # the user's mental model simple: "sampling adds spins to this machine's
    # rawdata", no separate scratch → import step.
    #
    # Backend's --chunk-cache-dir (scratch) is intentionally IGNORED in
    # virtual mode. Explicit --resume-from-cache still wins (operator
    # override).
    rawdata_dir = _ROOT / "slot_designer" / "rawdata" / args.machine / f"mode_{args.rtp_mode}"
    sampling_out_dir = args.resume_from_cache or rawdata_dir
    sampling_out_dir.mkdir(parents=True, exist_ok=True)

    md5s = _compute_md5s(entry)

    # Always resume: pick max existing chunk index + 1 so concurrent /
    # repeated samplings never overwrite each other.
    existing = sorted(sampling_out_dir.glob("chunk_*.json"))
    start_idx = 1
    if existing:
        try:
            last = max(int(p.stem.split("_")[1]) for p in existing)
            start_idx = last + 1
        except (IndexError, ValueError):
            start_idx = 1

    run_id = args.run_id or f"virt_{os.getpid()}"

    # Progress events — same format the real analyzer uses, so the
    # existing frontend status-strip / batch-log renderers treat virtual
    # runs identically to real ones.
    pf = args.progress_file
    _append_jsonl(pf, {
        "event": "started",
        "run_id": run_id,
        "machine": args.machine,
        "mode": args.rtp_mode,
        "target_halfwidth_pp": args.target_halfwidth_pp,
        "chunk_spin_times": args.chunk_spin_times,
        "chunk_robot_count": args.chunk_robot_count,
        "batch_concurrency": args.batch_concurrency,
        "started_at": _utc_now(),
    })
    _append_jsonl(pf, {
        "event": "analyzer_started",
        "run_id": run_id,
        "pid": os.getpid(),
        "machine": args.machine,
        "mode": args.rtp_mode,
        "ts": _utc_now(),
        "virtual": True,
    })

    # Schema fingerprint probe (deterministic seed — doesn't move main RNG)
    probe = emit_round(
        engine.spin(Random(0)),
        last_credits=1_000_000_000,
        spin_times=args.chunk_spin_times,
        rtp_id=int(spec["mode"]),
    )
    schema_fp = compute_schema_fingerprint(probe)

    rng = Random(int(time.time()) ^ (start_idx * 997))
    total_win = 0
    total_bet = 0
    stop_reason = "max_chunks_reached"
    last_produced_idx = start_idx - 1

    # Session-level CI accumulator across existing + newly-simulated
    # chunks so the sim loop can bail once target_halfwidth_pp is
    # satisfied. Target 0 / ≥ 999 = CI gate bypassed (fuzzy / sentinel).
    ci_target = float(args.target_halfwidth_pp)
    ci_gate_active = 0.0 < ci_target < 999.0
    sess_n = 0
    sess_ret_sum = 0.0
    sess_ret_sq_sum = 0.0
    if ci_gate_active:
        sess_n, sess_ret_sum, sess_ret_sq_sum = _load_existing_session_stats(
            sampling_out_dir, md5_filter=md5s,
        )
        existing_ci = _ci_halfwidth_pp(sess_n, sess_ret_sum, sess_ret_sq_sum)
        _append_jsonl(pf, {
            "event": "cache_read_start",
            "run_id": run_id,
            "tag": "--resume-from-cache (virtual pre-check)",
            "total_chunks": len(existing),
            "ts": _utc_now(),
        })
        _append_jsonl(pf, {
            "event": "cache_read_done",
            "run_id": run_id,
            "chunks_read": len(existing),
            "chunks_merged": len(existing),
            "md5_skipped": 0,
            "total_spins": sess_n * args.chunk_spin_times,
            "sessions": sess_n,
            "current_halfwidth_pp": existing_ci,
            "target_halfwidth_pp": ci_target,
            "ts": _utc_now(),
        })
        if existing_ci is not None and existing_ci <= ci_target:
            stop_reason = "target_ci_reached_from_cache"
            # Skip the sim loop entirely — existing cache already meets
            # target. Emit an explicit event so the UI can render a
            # "跳过采样 · CI 已达标" line instead of spinning without
            # any chunk events.
            _append_jsonl(pf, {
                "event": "cache_read_target_met",
                "run_id": run_id,
                "chunks_read": len(existing),
                "total_chunks": len(existing),
                "current_halfwidth_pp": existing_ci,
                "target_halfwidth_pp": ci_target,
                "ts": _utc_now(),
            })
            _append_jsonl(pf, {
                "event": "sampling_done",
                "run_id": run_id,
                "chunks_produced": 0,
                "stop_reason": stop_reason,
                "sampling_rtp_pct": 0.0,
                "sessions": sess_n,
                "current_halfwidth_pp": existing_ci,
                "ts": _utc_now(),
            })
            return _delegate_to_real_analyzer(args, sampling_out_dir)

    for ci in range(start_idx, start_idx + args.max_chunks):
        if _check_stop_flag(args.stop_flag_file):
            stop_reason = "user_stop"
            _append_jsonl(pf, {
                "event": "stop_flag_detected",
                "run_id": run_id,
                "chunk_index": ci,
                "ts": _utc_now(),
            })
            break

        _append_jsonl(pf, {
            "event": "chunk_started",
            "run_id": run_id,
            "chunk_index": ci,
            "ts": _utc_now(),
        })

        t0 = time.time()
        chunk, c_win, c_bet = _run_simulator_chunk(
            engine, spec, ci,
            robots=args.chunk_robot_count,
            spins_per_robot=args.chunk_spin_times,
            rng=rng,
            schema_fp=schema_fp,
            md5s=md5s,
        )
        write_chunk(chunk, sampling_out_dir, ci)
        total_win += c_win
        total_bet += c_bet
        last_produced_idx = ci
        elapsed = time.time() - t0

        # Accumulate THIS chunk's session returns into the running CI
        # estimator. `_run_simulator_chunk` already wrote the chunk; we
        # walk its robot list here without a second read from disk.
        current_ci: float | None = None
        if ci_gate_active:
            for rx in _session_returns_from_chunk_dict(chunk):
                sess_n += 1
                sess_ret_sum += rx
                sess_ret_sq_sum += rx * rx
            current_ci = _ci_halfwidth_pp(sess_n, sess_ret_sum, sess_ret_sq_sum)

        _append_jsonl(pf, {
            "event": "chunk_progress",
            "run_id": run_id,
            "chunk_index": ci,
            "chunks_done": ci - start_idx + 1,
            "total_spins": (ci - start_idx + 1) * args.chunk_robot_count * args.chunk_spin_times,
            "current_rtp_pct": (total_win / total_bet * 100) if total_bet else 0.0,
            "current_halfwidth_pp": current_ci,
            "target_halfwidth_pp": ci_target if ci_gate_active else None,
            "sessions": sess_n if ci_gate_active else None,
            "duration_s": round(elapsed, 3),
            "ts": _utc_now(),
        })

        if ci_gate_active and current_ci is not None and current_ci <= ci_target:
            stop_reason = "target_ci_reached"
            _append_jsonl(pf, {
                "event": "target_ci_reached",
                "run_id": run_id,
                "chunk_index": ci,
                "sessions": sess_n,
                "current_halfwidth_pp": current_ci,
                "target_halfwidth_pp": ci_target,
                "ts": _utc_now(),
            })
            break

    _append_jsonl(pf, {
        "event": "sampling_done",
        "run_id": run_id,
        "chunks_produced": last_produced_idx - start_idx + 1,
        "stop_reason": stop_reason,
        "sampling_rtp_pct": (total_win / total_bet * 100) if total_bet else 0.0,
        "sessions": sess_n if ci_gate_active else None,
        "current_halfwidth_pp": (
            _ci_halfwidth_pp(sess_n, sess_ret_sum, sess_ret_sq_sum)
            if ci_gate_active else None
        ),
        "ts": _utc_now(),
    })

    # 3. Delegate to real analyzer for full analysis
    return _delegate_to_real_analyzer(args, sampling_out_dir)


if __name__ == "__main__":
    sys.exit(main())
