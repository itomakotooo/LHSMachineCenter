"""Thin run orchestrator — sampling loop + report_engine dispatch.

This module is the entry point that ``src/web_console/backend/app.py``
spawns as a subprocess (the ``ANALYZER`` constant at line 103).  It was
deleted in commit c72b05a as part of the monolith-decomposition; this
file restores the subprocess contract while delegating analysis to the
new framework.

Responsibilities
----------------
1. Parse the CLI built by ``RunManager.start_run`` (app.py ~6414).
2. Run the VERBATIM sampling loop from the original monolith:
   - --from-cache (read-only replay),
   - --resume-from-cache (seed + continue live),
   - fresh live sampling with AIMD + CI-stop + cooperative cancel.
   Progress JSONL events are emitted unchanged so ``_watch_run`` parses
   them identically.
3. After the sampling loop, delegate analysis to
   ``fresh_slotlab.analyzer.report_engine.generate_report_from_chunks``.
   The monolith's entire inline parse→aggregate→build-summary tail is
   replaced by that single call.
4. Patch the returned summary's ``sampling`` section with the actual
   stop_reason / chunks / total_spins / bet from *this* loop, then
   re-write the JSON so ``_watch_run``'s sanity guard
   (``summary["sampling"]["total_spins"]``) works correctly.
5. Emit the ``completed`` progress event and exit 0.

NOT reimplemented here
-----------------------
- parse_args, post_json, run_sampling_chunk, aimd_tune, etc. — all
  delegated to ``fresh_slotlab.analyzer.core.base_pipeline``.
- CI math (t_critical_95, session_halfwidth_pp) — delegated to
  ``fresh_slotlab.sampler``.
- Chunk-file helpers (load_chunk_envelope, parse_chunk_response,
  update_chunk_entry) — delegated to core modules.
- The full per-chunk merge accumulators ARE kept here because they
  drive the CI-stop decision in the live loop (the loop computes
  session-level RTP / CI from chunk records to know when to stop;
  report_engine builds the final full-fidelity summary from the
  same chunks after the loop ends).

Design constraints honored
--------------------------
- feedback_subprocess_import_suicide_and_module_globals.md: no I/O
  at import time; ENDPOINT_URL mutation goes through
  _core_base_pipeline module attribute (not a snapshot binding).
- feedback_no_silent_swallow.md: every except with side effects
  writes a diagnostic to the progress file before continuing.
- feedback_respect_existing_codebase.md: app.py / sampler.py /
  base_pipeline.py / report_engine.py are NOT modified.
"""
from __future__ import annotations

import concurrent.futures
import json
import math
import os
import shutil
import signal
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Repo-root sys.path injection (script mode only)
# When invoked as ``python fresh_slotlab/player_impact_analyzer.py``, Python
# inserts the script's DIRECTORY (fresh_slotlab/) at sys.path[0]. That
# satisfies the bare ``from X import`` fallback imports below but makes the
# repo-root-anchored imports inside report_engine.py (``from fresh_slotlab.X
# import``) invisible. Inject the repo root (two levels up) when it's not
# already on sys.path so report_engine's deferred imports resolve correctly
# in both invocation modes. No-op in package mode (repo root is already on
# sys.path when ``python -m fresh_slotlab.player_impact_analyzer`` or when
# spawned as a subprocess from the repo root).
_REPO_ROOT_FOR_PATH = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT_FOR_PATH) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_PATH))

# ---------------------------------------------------------------------------
# Dual-path imports
# Standard pattern: package-mode path first, standalone-script fallback.
# Script mode: ``python fresh_slotlab/player_impact_analyzer.py`` puts
# fresh_slotlab/ on sys.path so the bare names work.
# Package mode: ``python -m fresh_slotlab.player_impact_analyzer`` or
# subprocess from repo root — qualified names resolve correctly.
# ---------------------------------------------------------------------------

try:
    from fresh_slotlab.sampler import t_critical_95, session_halfwidth_pp
    from fresh_slotlab.chunk_index import (
        get_chunks_index,
        update_chunk_entry,
    )
    from fresh_slotlab.rawdata_index import update_entry as _rawdata_index_update_entry
    from fresh_slotlab.round_win import (
        RoundWinRule,
        load_rules_for_machine,
    )
    import fresh_slotlab.analyzer.core.base_pipeline as _core_base_pipeline
    from fresh_slotlab.analyzer.core.base_pipeline import (
        CHUNK_SPINS_GROWTH,
        CIRCUIT_PAUSE_S,
        DEFAULT_ENDPOINT_URL,
        DEFAULT_GUIDELINE_RULES_PATH,
        ENDPOINT_URL,
        MIN_CHUNK_SPINS,
        SUCCESS_STREAK_FOR_GROW,
        _classify_failure,
        _RETRYABLE_HTTP_CODES,
        aimd_tune,
        parse_args,
        run_sampling_chunk,
        select_replay_chunks_by_md5,
    )
    from fresh_slotlab.analyzer.core._utils import (
        _DEFAULT_BANKROLL_MULTIPLIERS,
        _DEFAULT_BANKRUPTCY_SESSION_SPINS,
        _empty_bankruptcy_tier,
    )
    from fresh_slotlab.analyzer.core.aggregator import (
        _BankruptcyStreamAccumulator,
    )
    from fresh_slotlab.analyzer.core.parser import (
        ChunkIntegrityError,
        load_chunk_envelope,
        parse_chunk_response,
    )
    from fresh_slotlab.analyzer.core.writer import utc_now
    from fresh_slotlab.analyzer.report_engine import (
        generate_report_from_chunks,
        MachineNotRegistered,
    )
except ImportError:  # standalone script mode
    from sampler import t_critical_95, session_halfwidth_pp  # type: ignore[no-redef]
    from chunk_index import (  # type: ignore[no-redef]
        get_chunks_index,
        update_chunk_entry,
    )
    from rawdata_index import update_entry as _rawdata_index_update_entry  # type: ignore[no-redef]
    from round_win import (  # type: ignore[no-redef]
        RoundWinRule,
        load_rules_for_machine,
    )
    import analyzer.core.base_pipeline as _core_base_pipeline  # type: ignore[no-redef]
    from analyzer.core.base_pipeline import (  # type: ignore[no-redef]
        CHUNK_SPINS_GROWTH,
        CIRCUIT_PAUSE_S,
        DEFAULT_ENDPOINT_URL,
        DEFAULT_GUIDELINE_RULES_PATH,
        ENDPOINT_URL,
        MIN_CHUNK_SPINS,
        SUCCESS_STREAK_FOR_GROW,
        _classify_failure,
        _RETRYABLE_HTTP_CODES,
        aimd_tune,
        parse_args,
        run_sampling_chunk,
        select_replay_chunks_by_md5,
    )
    from analyzer.core._utils import (  # type: ignore[no-redef]
        _DEFAULT_BANKROLL_MULTIPLIERS,
        _DEFAULT_BANKRUPTCY_SESSION_SPINS,
        _empty_bankruptcy_tier,
    )
    from analyzer.core.aggregator import (  # type: ignore[no-redef]
        _BankruptcyStreamAccumulator,
    )
    from analyzer.core.parser import (  # type: ignore[no-redef]
        ChunkIntegrityError,
        load_chunk_envelope,
        parse_chunk_response,
    )
    from analyzer.core.writer import utc_now  # type: ignore[no-redef]
    from analyzer.report_engine import (  # type: ignore[no-redef]
        generate_report_from_chunks,
        MachineNotRegistered,
    )

# ---------------------------------------------------------------------------
# Module-level constants (verbatim from deleted monolith)
# ---------------------------------------------------------------------------

MAX_CONSECUTIVE_FAILED_BATCHES_NET = 3
MAX_CUMULATIVE_FAILED_CHUNKS_NET = 20
MAX_CUMULATIVE_FAILED_CHUNKS_MACHINE = 5

NON_CONVERGENCE_ABORT_MIN_CHUNKS = 20
NON_CONVERGENCE_BUDGET_MULTIPLIER = 5.0
NON_CONVERGENCE_RTP_BAND_PAID = (40.0, 200.0)
NON_CONVERGENCE_RTP_OUT_OF_BAND_CONSECUTIVE = 3

# ---------------------------------------------------------------------------
# Helpers (verbatim from deleted monolith)
# ---------------------------------------------------------------------------


def ci_halfwidth_pp(chunk_rtps_pct: list[float]) -> float:
    if len(chunk_rtps_pct) < 2:
        return math.inf
    if len(set(chunk_rtps_pct)) == 1:
        return 0.0
    return (
        t_critical_95(len(chunk_rtps_pct) - 1)
        * statistics.stdev(chunk_rtps_pct)
        / math.sqrt(len(chunk_rtps_pct))
    )


def append_jsonl(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def main() -> int:  # noqa: C901  (complexity kept for 1:1 fidelity with monolith loop)
    args = parse_args()

    if args.endpoint_url:
        _core_base_pipeline.ENDPOINT_URL = args.endpoint_url

    stop_requested = {"value": False}

    def _graceful_stop_handler(signum, _frame):
        stop_requested["value"] = True

    try:
        signal.signal(signal.SIGTERM, _graceful_stop_handler)
    except (ValueError, OSError):
        pass
    try:
        signal.signal(signal.SIGINT, _graceful_stop_handler)
    except (ValueError, OSError):
        pass

    if args.bet <= 0:
        raise SystemExit("--bet must be positive")
    if args.target_halfwidth_pp <= 0:
        raise SystemExit("--target-halfwidth-pp must be positive")
    if args.chunk_spin_times <= 0 or args.chunk_robot_count <= 0:
        raise SystemExit("--chunk-spin-times and --chunk-robot-count must be positive")
    if args.batch_concurrency <= 0 or args.max_chunks <= 0 or args.timeout <= 0:
        raise SystemExit("--batch-concurrency, --max-chunks, --timeout must be positive")
    if args.bankruptcy_session_spins <= 0:
        raise SystemExit("--bankruptcy-session-spins must be positive")

    _bankruptcy_mults_tuple: tuple[int, ...] = tuple(
        int(x.strip())
        for x in args.bankruptcy_bankroll_multipliers.split(",")
        if x.strip()
    ) or _DEFAULT_BANKROLL_MULTIPLIERS

    # Per-machine round-win extraction rules.
    _round_win_rules: list[RoundWinRule] = []
    try:
        _rules_config_path = (
            Path(__file__).resolve().parent.parent / "configs" / "machine_round_win_rules.json"
        )
        if _rules_config_path.exists():
            with open(_rules_config_path, encoding="utf-8") as _rcf:
                _rules_config = json.load(_rcf)
            _round_win_rules = load_rules_for_machine(args.machine, _rules_config)
    except (OSError, json.JSONDecodeError):
        _round_win_rules = []

    args.output_dir.mkdir(parents=True, exist_ok=True)

    run_id = args.run_id or f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    progress_file = args.progress_file

    started_at = utc_now()
    t0 = time.time()
    append_jsonl(
        progress_file,
        {
            "event": "started",
            "run_id": run_id,
            "machine": args.machine,
            "mode": args.rtp_mode,
            "target_halfwidth_pp": args.target_halfwidth_pp,
            "chunk_spin_times": args.chunk_spin_times,
            "chunk_robot_count": args.chunk_robot_count,
            "batch_concurrency": args.batch_concurrency,
            "started_at": started_at,
        },
    )
    append_jsonl(
        progress_file,
        {
            "event": "analyzer_started",
            "run_id": run_id,
            "pid": os.getpid(),
            "machine": args.machine,
            "mode": args.rtp_mode,
            "ts": utc_now(),
        },
    )

    if _round_win_rules:
        append_jsonl(
            progress_file,
            {
                "event": "round_win_rules_active",
                "run_id": run_id,
                "machine": args.machine,
                "rule_count": len(_round_win_rules),
                "rule_types": [type(r).__name__ for r in _round_win_rules],
                "ts": utc_now(),
            },
        )

    # ── Accumulator initialization (verbatim from monolith) ─────────────────
    total_spins = 0
    total_bet = 0.0
    total_win = 0.0
    chunk_rtps_pct: list[float] = []

    ret_count = 0
    ret_sum = 0.0
    ret_sq_sum = 0.0

    total_session_ret_count = 0
    total_session_ret_sum = 0.0
    total_session_ret_sq_sum = 0.0
    total_session_win_sum = 0.0
    session_bucket_spins: dict[str, int] = defaultdict(int)
    session_bucket_bet: dict[str, float] = defaultdict(float)
    session_bucket_win: dict[str, float] = defaultdict(float)

    bankruptcy_stream_acc = _BankruptcyStreamAccumulator(
        bet=args.bet,
        session_spins=args.bankruptcy_session_spins,
        bankroll_mults=_bankruptcy_mults_tuple,
    )

    chunks = 0
    stop_reason = "max_chunks_reached"
    achieved_halfwidth_pp: float | None = None
    next_chunk_index = 1

    cumulative_failed_chunks = 0
    cumulative_failed_chunks_net = 0
    cumulative_failed_chunks_machine = 0
    consecutive_failed_batches_net = 0
    rtp_out_of_band_consecutive = 0

    # ── Cache read phase ─────────────────────────────────────────────────────
    if args.from_cache is not None and args.resume_from_cache is not None:
        raise SystemExit("--from-cache and --resume-from-cache are mutually exclusive")

    cache_read_dir = (
        args.from_cache if args.from_cache is not None else args.resume_from_cache
    )
    resume_mode = args.resume_from_cache is not None
    skip_sampling_loop = args.from_cache is not None

    if cache_read_dir is not None:
        try:
            _chunks_idx_payload = get_chunks_index(cache_read_dir)
            _sidecar_entries = _chunks_idx_payload.get("chunks") or {}
        except Exception:  # noqa: BLE001
            _chunks_idx_payload = {}
            _sidecar_entries = {}

        md5_filter_active_pre = bool(args.upstream_config_md5 or args.upstream_code_md5)
        if md5_filter_active_pre and _sidecar_entries:
            chunk_files, max_existing_idx = select_replay_chunks_by_md5(
                cache_read_dir,
                _chunks_idx_payload,
                args.upstream_config_md5,
                args.upstream_code_md5,
            )
        else:
            chunk_files = sorted(cache_read_dir.glob("chunk_*.json"))
            max_existing_idx = 0

        if not chunk_files and not resume_mode and not md5_filter_active_pre:
            raise SystemExit(
                f"--from-cache: no chunk_*.json files found in {cache_read_dir}"
            )

        if not resume_mode and args.max_chunks > 0:
            chunk_files = chunk_files[: args.max_chunks]
        if not resume_mode:
            stop_reason = "from_cache_complete"

        tag = "--resume-from-cache" if resume_mode else "--from-cache"
        total_to_read = len(chunk_files)
        if total_to_read > 0:
            append_jsonl(
                progress_file,
                {
                    "event": "cache_read_start",
                    "run_id": run_id,
                    "tag": tag,
                    "total_chunks": total_to_read,
                    "ts": utc_now(),
                },
            )

        read_progress_step = max(20, total_to_read // 10) if total_to_read > 0 else 0
        md5_filter_active = bool(args.upstream_config_md5 or args.upstream_code_md5)
        historical_md5_skipped = 0

        for read_idx, cf in enumerate(chunk_files):
            if md5_filter_active:
                sidecar_entry = _sidecar_entries.get(cf.name)
                if isinstance(sidecar_entry, dict):
                    peek_idx = int(sidecar_entry.get("idx", 0) or 0)
                    peek_cfg = str(sidecar_entry.get("cfg_md5", "") or "")
                    peek_code = str(sidecar_entry.get("code_md5", "") or "")
                    max_existing_idx = max(max_existing_idx, peek_idx)
                    if (
                        peek_cfg != args.upstream_config_md5
                        or peek_code != args.upstream_code_md5
                    ):
                        historical_md5_skipped += 1
                        if (
                            read_progress_step > 0
                            and total_to_read > 0
                            and (read_idx + 1) % read_progress_step == 0
                            and (read_idx + 1) < total_to_read
                        ):
                            append_jsonl(
                                progress_file,
                                {
                                    "event": "cache_read_progress",
                                    "run_id": run_id,
                                    "chunks_read": read_idx + 1,
                                    "total_chunks": total_to_read,
                                    "total_spins": total_spins,
                                    "md5_skipped": historical_md5_skipped,
                                    "ts": utc_now(),
                                },
                            )
                        continue

            try:
                raw = load_chunk_envelope(cf)
            except ChunkIntegrityError as exc:
                raise SystemExit(f"{tag}: {exc}")

            chunk_bet_val = int(raw.get("_bet", args.bet) or args.bet)
            idx = int(raw.get("_chunk_index", next_chunk_index))
            max_existing_idx = max(max_existing_idx, idx)

            if md5_filter_active:
                cfg_env = str(raw.get("_config_md5", "") or "")
                code_env = str(raw.get("_code_md5", "") or "")
                if cfg_env != args.upstream_config_md5 or code_env != args.upstream_code_md5:
                    historical_md5_skipped += 1
                    if (
                        read_progress_step > 0
                        and total_to_read > 0
                        and (read_idx + 1) % read_progress_step == 0
                        and (read_idx + 1) < total_to_read
                    ):
                        append_jsonl(
                            progress_file,
                            {
                                "event": "cache_read_progress",
                                "run_id": run_id,
                                "chunks_read": read_idx + 1,
                                "total_chunks": total_to_read,
                                "total_spins": total_spins,
                                "md5_skipped": historical_md5_skipped,
                                "ts": utc_now(),
                            },
                        )
                    continue

            resp = raw.get("response")
            if resp is None:
                raise SystemExit(f"{tag}: {cf.name} missing 'response' key")
            rec = parse_chunk_response(
                resp, idx, chunk_bet_val,
                bankruptcy_session_spins=args.bankruptcy_session_spins,
                bankruptcy_bankroll_mults=_bankruptcy_mults_tuple,
                round_win_rules=_round_win_rules,
            )
            if not rec.get("ok"):
                raise SystemExit(f"{tag}: {cf.name} parse failed: {rec.get('error')}")

            # ── minimal merge for CI tracking ───────────────────────────────
            chunks += 1
            spins = int(rec["spins"])
            bet_amt = float(rec["bet"])
            win_amt = float(rec["win"])
            total_spins += spins
            total_bet += bet_amt
            total_win += win_amt
            chunk_rtp = (win_amt / bet_amt) * 100.0 if bet_amt > 0 else 0.0
            chunk_rtps_pct.append(chunk_rtp)
            ret_count += int(rec["ret_count"])
            ret_sum += float(rec["ret_sum"])
            ret_sq_sum += float(rec["ret_sq_sum"])
            total_session_ret_count += int(rec.get("session_ret_count", 0) or 0)
            total_session_ret_sum += float(rec.get("session_ret_sum", 0.0) or 0.0)
            total_session_ret_sq_sum += float(rec.get("session_ret_sq_sum", 0.0) or 0.0)
            total_session_win_sum += float(rec.get("session_win_sum", 0.0) or 0.0)
            for b, c in (rec.get("session_bucket_spins") or {}).items():
                session_bucket_spins[str(b)] += int(c)
            for b, v in (rec.get("session_bucket_bet") or {}).items():
                session_bucket_bet[str(b)] += float(v)
            for b, v in (rec.get("session_bucket_win") or {}).items():
                session_bucket_win[str(b)] += float(v)
            _bk_reps = rec.get("bankruptcy_reps")
            if isinstance(_bk_reps, list) and _bk_reps:
                bankruptcy_stream_acc.feed_reps(
                    [
                        (int(t[0]), int(t[1]))
                        for t in _bk_reps
                        if isinstance(t, (list, tuple)) and len(t) >= 2
                    ]
                )
            # ── end minimal merge ────────────────────────────────────────────

            # Periodic read-progress heartbeat.
            if (
                read_progress_step > 0
                and total_to_read > 0
                and (read_idx + 1) % read_progress_step == 0
                and (read_idx + 1) < total_to_read
            ):
                append_jsonl(
                    progress_file,
                    {
                        "event": "cache_read_progress",
                        "run_id": run_id,
                        "chunks_read": read_idx + 1,
                        "total_chunks": total_to_read,
                        "total_spins": total_spins,
                        "ts": utc_now(),
                    },
                )

            # Early-stop: CI met while replaying cached chunks.
            if (
                resume_mode
                and args.target_halfwidth_pp > 0
                and args.target_halfwidth_pp < 999.0
                and ret_count > 1
            ):
                ci_now = session_halfwidth_pp(
                    total_session_ret_count,
                    total_session_ret_sum,
                    total_session_ret_sq_sum,
                )
                if ci_now is not None and ci_now <= args.target_halfwidth_pp:
                    append_jsonl(
                        progress_file,
                        {
                            "event": "cache_read_target_met",
                            "run_id": run_id,
                            "chunks_read": read_idx + 1,
                            "total_chunks": total_to_read,
                            "total_spins": total_spins,
                            "current_halfwidth_pp": ci_now,
                            "target_halfwidth_pp": args.target_halfwidth_pp,
                            "ts": utc_now(),
                        },
                    )
                    stop_reason = "target_ci_reached_from_cache"
                    skip_sampling_loop = True
                    break

        if total_to_read > 0:
            append_jsonl(
                progress_file,
                {
                    "event": "cache_read_done",
                    "run_id": run_id,
                    "chunks_read": total_to_read,
                    "chunks_merged": chunks,
                    "md5_skipped": historical_md5_skipped,
                    "total_spins": total_spins,
                    "ts": utc_now(),
                },
            )

        if resume_mode:
            next_chunk_index = max_existing_idx + 1
            args.chunk_cache_dir = cache_read_dir
            if next_chunk_index > args.max_chunks:
                remaining_new = max(1, args.max_chunks - chunks)
                args.max_chunks = max_existing_idx + remaining_new
            append_jsonl(
                progress_file,
                {
                    "event": "resume_from_cache",
                    "run_id": run_id,
                    "existing_chunks": chunks,
                    "existing_spins": total_spins,
                    "historical_md5_skipped": historical_md5_skipped,
                    "next_chunk_index": next_chunk_index,
                    "adjusted_max_chunks": args.max_chunks,
                    "ts": utc_now(),
                },
            )

    # ── Per-machine config override ──────────────────────────────────────────
    _DISK_GUARD_MIN_FREE_GB = 2.0
    _disk_guard_path = (
        args.output_dir if args.output_dir.exists() else args.output_dir.parent
    )

    _machine_config_str: str | None = None
    if args.machine_config_file:
        cfg_path = Path(args.machine_config_file)
        if not cfg_path.is_file():
            raise SystemExit(
                f"--machine-config-file not found or not a file: {cfg_path}"
            )
        _machine_config_str = cfg_path.read_text(encoding="utf-8")
        try:
            json.loads(_machine_config_str)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--machine-config-file is not valid JSON: {exc}")

    first_fetch_emitted = False
    current_concurrency = args.batch_concurrency
    current_chunk_spins = args.chunk_spin_times
    consecutive_successful_batches = 0
    last_batch_pause_until = 0.0

    # ── Online sampling loop (verbatim from monolith) ────────────────────────
    while not skip_sampling_loop and next_chunk_index <= args.max_chunks:
        now_s = time.time()
        if now_s < last_batch_pause_until:
            remaining_pause = last_batch_pause_until - now_s
            append_jsonl(
                progress_file,
                {
                    "event": "circuit_pause",
                    "run_id": run_id,
                    "pause_seconds": round(remaining_pause, 2),
                    "reason": "fully_failed_batch",
                    "ts": utc_now(),
                },
            )
            while time.time() < last_batch_pause_until:
                if stop_requested["value"] or (
                    args.stop_flag_file is not None and args.stop_flag_file.exists()
                ):
                    break
                time.sleep(min(1.0, last_batch_pause_until - time.time()))
            last_batch_pause_until = 0.0

        if stop_requested["value"] or (
            args.stop_flag_file is not None and args.stop_flag_file.exists()
        ):
            stop_reason = "user_stop"
            break

        # Mid-run disk guard.
        try:
            free_gb = shutil.disk_usage(_disk_guard_path).free / (1024 ** 3)
            if free_gb < _DISK_GUARD_MIN_FREE_GB:
                stop_reason = f"disk_low_{free_gb:.2f}GB"
                append_jsonl(
                    progress_file,
                    {
                        "event": "disk_guard_stop",
                        "run_id": run_id,
                        "free_gb": round(free_gb, 3),
                        "threshold_gb": _DISK_GUARD_MIN_FREE_GB,
                        "chunks_completed": chunks,
                        "total_spins": total_spins,
                        "ts": utc_now(),
                    },
                )
                break
        except OSError:
            pass

        remaining = args.max_chunks - chunks
        batch_size = min(current_concurrency, remaining)
        if batch_size <= 0:
            break

        indices = list(range(next_chunk_index, next_chunk_index + batch_size))
        next_chunk_index += batch_size

        if not first_fetch_emitted:
            first_fetch_emitted = True
            append_jsonl(
                progress_file,
                {
                    "event": "fetching_chunk",
                    "run_id": run_id,
                    "chunk_index": indices[0],
                    "batch_size": batch_size,
                    "ts": utc_now(),
                },
            )

        batch_results: list[dict[str, Any]] = []
        chunk_cache = getattr(args, "chunk_cache_dir", None)

        for idx in indices:
            append_jsonl(
                progress_file,
                {
                    "event": "chunk_started",
                    "run_id": run_id,
                    "chunk_index": idx,
                    "ts": utc_now(),
                },
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = [
                executor.submit(
                    run_sampling_chunk,
                    idx,
                    args.machine,
                    args.rtp_mode,
                    args.bet,
                    current_chunk_spins,
                    args.chunk_robot_count,
                    args.timeout,
                    chunk_cache_dir=chunk_cache,
                    bankruptcy_session_spins=args.bankruptcy_session_spins,
                    bankruptcy_bankroll_mults=_bankruptcy_mults_tuple,
                    upstream_machine_name=args.upstream_machine_name,
                    machine_config=_machine_config_str,
                    envelope_config_md5=args.upstream_config_md5 or "",
                    envelope_code_md5=args.upstream_code_md5 or "",
                    round_win_rules=_round_win_rules,
                )
                for idx in indices
            ]
            for future in concurrent.futures.as_completed(futures):
                rec = future.result()
                batch_results.append(rec)
                if not rec.get("ok"):
                    err_class = _classify_failure(rec.get("error", ""))
                    if err_class == "network":
                        cumulative_failed_chunks_net += 1
                    else:
                        cumulative_failed_chunks_machine += 1
                    cumulative_failed_chunks = (
                        cumulative_failed_chunks_net + cumulative_failed_chunks_machine
                    )
                    append_jsonl(
                        progress_file,
                        {
                            "event": "chunk_failed",
                            "run_id": run_id,
                            "chunk_index": rec.get("index"),
                            "error": rec.get("error"),
                            "error_class": err_class,
                            "cumulative_failed": cumulative_failed_chunks,
                            "cumulative_failed_net": cumulative_failed_chunks_net,
                            "cumulative_failed_machine": cumulative_failed_chunks_machine,
                            "chunks_completed_so_far": chunks,
                            "total_spins_so_far": total_spins,
                            "ts": utc_now(),
                        },
                    )
                    continue

                # Success path: minimal merge for CI tracking.
                chunks += 1
                spins = int(rec["spins"])
                bet_amt = float(rec["bet"])
                win_amt = float(rec["win"])
                total_spins += spins
                total_bet += bet_amt
                total_win += win_amt
                chunk_rtp = (win_amt / bet_amt) * 100.0 if bet_amt > 0 else 0.0
                chunk_rtps_pct.append(chunk_rtp)
                ret_count += int(rec["ret_count"])
                ret_sum += float(rec["ret_sum"])
                ret_sq_sum += float(rec["ret_sq_sum"])
                total_session_ret_count += int(rec.get("session_ret_count", 0) or 0)
                total_session_ret_sum += float(rec.get("session_ret_sum", 0.0) or 0.0)
                total_session_ret_sq_sum += float(
                    rec.get("session_ret_sq_sum", 0.0) or 0.0
                )
                total_session_win_sum += float(rec.get("session_win_sum", 0.0) or 0.0)
                for b, c in (rec.get("session_bucket_spins") or {}).items():
                    session_bucket_spins[str(b)] += int(c)
                for b, v in (rec.get("session_bucket_bet") or {}).items():
                    session_bucket_bet[str(b)] += float(v)
                for b, v in (rec.get("session_bucket_win") or {}).items():
                    session_bucket_win[str(b)] += float(v)
                _bk_reps = rec.get("bankruptcy_reps")
                if isinstance(_bk_reps, list) and _bk_reps:
                    bankruptcy_stream_acc.feed_reps(
                        [
                            (int(t[0]), int(t[1]))
                            for t in _bk_reps
                            if isinstance(t, (list, tuple)) and len(t) >= 2
                        ]
                    )

                hw = ci_halfwidth_pp(chunk_rtps_pct)
                if math.isfinite(hw):
                    achieved_halfwidth_pp = hw

                current_rtp_pct = (
                    (total_win / total_bet) * 100.0 if total_bet > 0 else 0.0
                )
                session_bet_sum_live = sum(session_bucket_bet.values())
                session_rtp_pct = (
                    (total_session_win_sum / session_bet_sum_live) * 100.0
                    if session_bet_sum_live > 0
                    else None
                )
                session_ci_now = session_halfwidth_pp(
                    total_session_ret_count,
                    total_session_ret_sum,
                    total_session_ret_sq_sum,
                )
                append_jsonl(
                    progress_file,
                    {
                        "event": "chunk_progress",
                        "run_id": run_id,
                        "chunk_index": int(rec["index"]),
                        "chunks_completed": chunks,
                        "total_spins": total_spins,
                        "current_rtp_pct": current_rtp_pct,
                        "session_rtp_pct": session_rtp_pct,
                        "current_halfwidth_pp": (
                            session_ci_now
                            if session_ci_now is not None
                            else achieved_halfwidth_pp
                        ),
                        "chunk_level_halfwidth_pp": achieved_halfwidth_pp,
                        "session_level_halfwidth_pp": session_ci_now,
                        "target_halfwidth_pp": args.target_halfwidth_pp,
                        "elapsed_seconds": round(time.time() - t0, 3),
                        "ts": utc_now(),
                    },
                )

        successful_results = [r for r in batch_results if bool(r.get("ok"))]
        failed_results = [r for r in batch_results if not bool(r.get("ok"))]
        batch_fully_failed = bool(failed_results) and not successful_results
        batch_failure_classes = [
            _classify_failure(r.get("error", "")) for r in failed_results
        ]
        batch_has_network_failure = any(c == "network" for c in batch_failure_classes)
        batch_fully_network_failed = batch_fully_failed and batch_has_network_failure
        if batch_fully_network_failed:
            consecutive_failed_batches_net += 1
        else:
            consecutive_failed_batches_net = 0

        aimd_should_halve = batch_fully_network_failed
        new_conc, new_spins, new_streak, should_pause = aimd_tune(
            current_concurrency,
            current_chunk_spins,
            args.batch_concurrency,
            args.chunk_spin_times,
            aimd_should_halve,
            consecutive_successful_batches,
        )
        if (new_conc, new_spins) != (current_concurrency, current_chunk_spins):
            append_jsonl(
                progress_file,
                {
                    "event": "adaptive_tune",
                    "run_id": run_id,
                    "from_concurrency": current_concurrency,
                    "to_concurrency": new_conc,
                    "from_chunk_spins": current_chunk_spins,
                    "to_chunk_spins": new_spins,
                    "direction": "down" if aimd_should_halve else "up",
                    "reason": (
                        "fully_failed_batch"
                        if aimd_should_halve
                        else "success_streak"
                    ),
                    "ts": utc_now(),
                },
            )
        current_concurrency = new_conc
        current_chunk_spins = new_spins
        consecutive_successful_batches = new_streak
        if should_pause:
            last_batch_pause_until = time.time() + CIRCUIT_PAUSE_S

        if cumulative_failed_chunks_machine >= MAX_CUMULATIVE_FAILED_CHUNKS_MACHINE:
            machine_errors = [
                r.get("error", "")
                for r in batch_results
                if not r.get("ok")
                and _classify_failure(r.get("error", "")) == "machine"
            ]
            stop_reason = (
                f"machine_bug:"
                f"cumulative_machine_failures={cumulative_failed_chunks_machine},"
                f"last_error={machine_errors[0] if machine_errors else '?'}"
            )
            append_jsonl(
                progress_file,
                {
                    "event": "failed",
                    "run_id": run_id,
                    "reason": stop_reason,
                    "chunks": chunks,
                    "total_spins": total_spins,
                    "elapsed_seconds": round(time.time() - t0, 3),
                    "ts": utc_now(),
                },
            )
            break

        if (
            consecutive_failed_batches_net >= MAX_CONSECUTIVE_FAILED_BATCHES_NET
            or cumulative_failed_chunks_net >= MAX_CUMULATIVE_FAILED_CHUNKS_NET
        ):
            last_err = failed_results[0] if failed_results else {}
            stop_reason = (
                f"upstream_unstable:"
                f"network_consecutive_batches={consecutive_failed_batches_net},"
                f"network_cumulative_chunks={cumulative_failed_chunks_net},"
                f"last_error={last_err.get('error', '?')}"
            )
            append_jsonl(
                progress_file,
                {
                    "event": "failed",
                    "run_id": run_id,
                    "reason": stop_reason,
                    "chunks": chunks,
                    "total_spins": total_spins,
                    "elapsed_seconds": round(time.time() - t0, 3),
                    "ts": utc_now(),
                },
            )
            break

        session_ci_final = session_halfwidth_pp(
            total_session_ret_count,
            total_session_ret_sum,
            total_session_ret_sq_sum,
        )
        if (
            chunks >= 2
            and session_ci_final is not None
            and session_ci_final <= args.target_halfwidth_pp
        ):
            stop_reason = "target_ci_reached"
            break

        # Tier 2 non-convergence early-abort.
        if (
            not args.disable_non_convergence_abort
            and 0.0 < args.target_halfwidth_pp < 999.0
            and chunks >= NON_CONVERGENCE_ABORT_MIN_CHUNKS
        ):
            if args.rtp_mode == 1:
                session_bet_sum_now = sum(session_bucket_bet.values())
                running_rtp_pct = (
                    (total_session_win_sum / session_bet_sum_now) * 100.0
                    if session_bet_sum_now > 0
                    else None
                )
                if running_rtp_pct is not None:
                    lo, hi = NON_CONVERGENCE_RTP_BAND_PAID
                    if running_rtp_pct < lo or running_rtp_pct > hi:
                        rtp_out_of_band_consecutive += 1
                    else:
                        rtp_out_of_band_consecutive = 0
                    if (
                        rtp_out_of_band_consecutive
                        >= NON_CONVERGENCE_RTP_OUT_OF_BAND_CONSECUTIVE
                    ):
                        append_jsonl(
                            progress_file,
                            {
                                "event": "non_convergence_abort",
                                "run_id": run_id,
                                "reason": "rtp_out_of_band",
                                "rtp_pct": round(running_rtp_pct, 3),
                                "band_lo_pct": lo,
                                "band_hi_pct": hi,
                                "consecutive": rtp_out_of_band_consecutive,
                                "chunks": chunks,
                                "total_spins": total_spins,
                                "mode": args.rtp_mode,
                                "ts": utc_now(),
                            },
                        )
                        stop_reason = "non_convergence_abort:rtp_out_of_band"
                        break

            if session_ci_final is not None and session_ci_final > args.target_halfwidth_pp:
                ratio = session_ci_final / args.target_halfwidth_pp
                projected_chunks = chunks * (ratio * ratio)
                budget_ceiling = args.max_chunks * NON_CONVERGENCE_BUDGET_MULTIPLIER
                if projected_chunks > budget_ceiling:
                    append_jsonl(
                        progress_file,
                        {
                            "event": "non_convergence_abort",
                            "run_id": run_id,
                            "reason": "projected_budget_exceeded",
                            "projected_chunks": int(projected_chunks),
                            "budget_ceiling": int(budget_ceiling),
                            "current_ci_pp": round(session_ci_final, 3),
                            "target_ci_pp": args.target_halfwidth_pp,
                            "chunks": chunks,
                            "total_spins": total_spins,
                            "ts": utc_now(),
                        },
                    )
                    stop_reason = "non_convergence_abort:projected_budget_exceeded"
                    break

    duration_seconds = round(time.time() - t0, 3)
    finished_at = utc_now()

    # ── Determine chunk_dir for report_engine ────────────────────────────────
    # The chunk_dir fed to generate_report_from_chunks must contain ONLY the
    # chunks that matched the md5 filter (if active). On mixed-md5 rawdata dirs
    # (resume / from-cache with historical chunks) we hardlink matching chunks
    # into a scoped temp dir — mirroring the generate-report path in app.py.
    if args.from_cache is not None:
        _raw_chunk_dir: Path = args.from_cache
    elif args.resume_from_cache is not None:
        _raw_chunk_dir = args.resume_from_cache
    else:
        # Fresh sampling: chunk_cache_dir receives all live chunks.
        _raw_chunk_dir = getattr(args, "chunk_cache_dir", None) or args.output_dir

    md5_scope_active = bool(args.upstream_config_md5 or args.upstream_code_md5)

    # Build scoped dir when md5 filter is active and the raw dir may have
    # more chunks than we actually processed. Clean up afterwards.
    _scoped_dir: Path | None = None
    if _raw_chunk_dir.is_dir() and md5_scope_active and chunks > 0:
        all_in_dir = list(_raw_chunk_dir.glob("chunk_*.json"))
        if len(all_in_dir) != chunks:
            # At least one chunk in the dir doesn't match our filter.
            # Collect the chunk files we actually processed (matching md5).
            try:
                _idx_payload2 = get_chunks_index(_raw_chunk_dir)
                _sid2 = _idx_payload2.get("chunks") or {}
            except Exception:  # noqa: BLE001
                _idx_payload2 = {}
                _sid2 = {}

            _cfg_md5 = args.upstream_config_md5 or ""
            _code_md5 = args.upstream_code_md5 or ""
            matching_paths: list[Path] = []
            for _cf in sorted(all_in_dir):
                _se = _sid2.get(_cf.name)
                if isinstance(_se, dict):
                    if (
                        str(_se.get("cfg_md5", "") or "") == _cfg_md5
                        and str(_se.get("code_md5", "") or "") == _code_md5
                    ):
                        matching_paths.append(_cf)
                        continue
                # Fall back to envelope read.
                try:
                    _raw2 = load_chunk_envelope(_cf)
                    if (
                        str(_raw2.get("_config_md5", "") or "") == _cfg_md5
                        and str(_raw2.get("_code_md5", "") or "") == _code_md5
                    ):
                        matching_paths.append(_cf)
                except Exception:  # noqa: BLE001
                    pass

            if matching_paths and len(matching_paths) != len(all_in_dir):
                _scoped_dir = args.output_dir / "_scope_tmp"
                _scoped_dir.mkdir(parents=True, exist_ok=True)
                for _cp in matching_paths:
                    _dst = _scoped_dir / _cp.name
                    try:
                        os.link(_cp, _dst)
                    except OSError:
                        shutil.copyfile(_cp, _dst)
                _chunk_dir_for_engine = _scoped_dir
            else:
                _chunk_dir_for_engine = _raw_chunk_dir
        else:
            _chunk_dir_for_engine = _raw_chunk_dir
    else:
        _chunk_dir_for_engine = _raw_chunk_dir

    # ── Read actual bet from first chunk ─────────────────────────────────────
    # Per memory bet-trap: MUST NOT default to 1. The chunk envelope carries the
    # real bet used during sampling.
    actual_bet = args.bet
    if _chunk_dir_for_engine.is_dir():
        _first_chunks = sorted(_chunk_dir_for_engine.glob("chunk_*.json"))
        if _first_chunks:
            try:
                _env = load_chunk_envelope(_first_chunks[0])
                _env_bet = int(_env.get("_bet", 0) or 0)
                if _env_bet > 0:
                    actual_bet = _env_bet
            except Exception:  # noqa: BLE001
                pass

    # ── Variant resolution for manifest lookup ───────────────────────────────
    try:
        from src.web_console.backend.machine_variants import (
            extract_base_machine_name as _extract_base,
        )
        _base_machine = _extract_base(args.machine)
    except Exception:  # noqa: BLE001
        # Fallback: strip $ suffix if any (simple regex strip).
        import re as _re
        _m = _re.match(r"^(M\d+)", args.machine)
        _base_machine = _m.group(1) if _m else args.machine

    # ── Delegate analysis to report_engine ───────────────────────────────────
    _analysis_error: str | None = None
    summary: dict[str, Any] = {}
    out_json = args.output_dir / "player_impact_summary.json"

    try:
        if total_spins == 0:
            # No data collected: write a minimal shell summary so _watch_run can
            # inspect sampling.total_spins and sampling.stop_reason without crashing.
            summary = {
                "machine": args.machine,
                "mode": args.rtp_mode,
                "run_id": run_id,
                "sampling": {
                    "total_spins": 0,
                    "chunks": 0,
                    "stop_reason": stop_reason,
                    "bet": actual_bet,
                    "duration_seconds": duration_seconds,
                    "started_at": started_at,
                    "finished_at": finished_at,
                },
            }
            out_json.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            # Write stub report.md so _watch_run file-existence check passes.
            (args.output_dir / "player_impact_report.md").write_text(
                f"# Player Impact Report — {args.machine} mode {args.rtp_mode}\n\n"
                f"run_id: {run_id}\n"
                f"stop_reason: {stop_reason}\n"
                f"total_spins: 0\n"
                "note: no data collected\n",
                encoding="utf-8",
            )
        else:
            try:
                if not _chunk_dir_for_engine.is_dir() or not any(
                    _chunk_dir_for_engine.glob("chunk_*.json")
                ):
                    raise MachineNotRegistered(
                        f"chunk_dir {_chunk_dir_for_engine} is empty or missing"
                    )
                summary = generate_report_from_chunks(
                    args.machine,
                    args.rtp_mode,
                    chunk_dir=_chunk_dir_for_engine,
                    output_dir=args.output_dir,
                    bet=actual_bet,
                    run_id=run_id,
                    manifest_machine_id=(
                        _base_machine if _base_machine != args.machine else None
                    ),
                )
                # Patch sampling section with actuals from our loop.
                if "sampling" in summary:
                    summary["sampling"]["total_spins"] = total_spins
                    summary["sampling"]["chunks"] = chunks
                    summary["sampling"]["stop_reason"] = stop_reason
                    summary["sampling"]["bet"] = actual_bet
                    summary["sampling"]["duration_seconds"] = duration_seconds
                    summary["sampling"]["started_at"] = started_at
                    summary["sampling"]["finished_at"] = finished_at
                else:
                    summary["sampling"] = {
                        "total_spins": total_spins,
                        "chunks": chunks,
                        "stop_reason": stop_reason,
                        "bet": actual_bet,
                        "duration_seconds": duration_seconds,
                        "started_at": started_at,
                        "finished_at": finished_at,
                    }
                # Re-write the patched summary.
                out_json.write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                # Write the report.md that _watch_run checks for existence.
                # report_engine writes only the JSON summary; the stub .md satisfies
                # the `managed.report_file.exists()` gate in app.py _watch_run (~6564)
                # and marks this as a SpinType-native engine report.
                _out_md = args.output_dir / "player_impact_report.md"
                _rtp_pct = float((summary.get("rtp") or {}).get("point_pct") or 0.0)
                _out_md.write_text(
                    f"# Player Impact Report — {args.machine} mode {args.rtp_mode}\n\n"
                    f"run_id: {run_id}\n"
                    f"stop_reason: {stop_reason}\n"
                    f"total_spins: {total_spins}\n"
                    f"chunks: {chunks}\n"
                    f"rtp_point_pct: {_rtp_pct:.4f}\n"
                    f"generated_by: report_engine (SpinType-native)\n"
                    f"summary: player_impact_summary.json\n",
                    encoding="utf-8",
                )
            except MachineNotRegistered as exc:
                _analysis_error = f"MachineNotRegistered: {exc}"
                append_jsonl(
                    progress_file,
                    {
                        "event": "analysis_error",
                        "run_id": run_id,
                        "error": _analysis_error,
                        "ts": utc_now(),
                    },
                )
                # Write a minimal summary so _watch_run can read stop_reason.
                summary = {
                    "machine": args.machine,
                    "mode": args.rtp_mode,
                    "run_id": run_id,
                    "sampling": {
                        "total_spins": total_spins,
                        "chunks": chunks,
                        "stop_reason": f"analysis_failed:{_analysis_error[:200]}",
                        "bet": actual_bet,
                        "duration_seconds": duration_seconds,
                        "started_at": started_at,
                        "finished_at": finished_at,
                    },
                }
                out_json.write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                # Write stub report.md for the error path.
                (args.output_dir / "player_impact_report.md").write_text(
                    f"# Player Impact Report — {args.machine} mode {args.rtp_mode}\n\n"
                    f"run_id: {run_id}\n"
                    f"error: {_analysis_error}\n",
                    encoding="utf-8",
                )
            except Exception as exc:  # noqa: BLE001
                _analysis_error = f"{type(exc).__name__}: {exc}"
                append_jsonl(
                    progress_file,
                    {
                        "event": "analysis_error",
                        "run_id": run_id,
                        "error": _analysis_error,
                        "ts": utc_now(),
                    },
                )
                summary = {
                    "machine": args.machine,
                    "mode": args.rtp_mode,
                    "run_id": run_id,
                    "sampling": {
                        "total_spins": total_spins,
                        "chunks": chunks,
                        "stop_reason": f"analysis_failed:{_analysis_error[:200]}",
                        "bet": actual_bet,
                        "duration_seconds": duration_seconds,
                        "started_at": started_at,
                        "finished_at": finished_at,
                    },
                }
                out_json.write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                # Write stub report.md for the generic error path.
                (args.output_dir / "player_impact_report.md").write_text(
                    f"# Player Impact Report — {args.machine} mode {args.rtp_mode}\n\n"
                    f"run_id: {run_id}\n"
                    f"error: {_analysis_error}\n",
                    encoding="utf-8",
                )
    finally:
        # Clean up scoped temp dir (hardlinks only; content is in rawdata, not here).
        if _scoped_dir is not None:
            try:
                shutil.rmtree(_scoped_dir, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass

    # ── Completed progress event (shape matches what _watch_run reads) ────────
    rtp_point_pct = (
        float(
            (summary.get("rtp") or {}).get("point_pct")
            or (summary.get("sampling") or {}).get("rtp_point_pct")
            or 0.0
        )
    )
    achieved_hw = float(
        (summary.get("sampling") or {}).get("achieved_halfwidth_pp")
        or achieved_halfwidth_pp
        or 0.0
    )
    ci_interval = None
    if achieved_hw > 0 and rtp_point_pct > 0:
        ci_interval = [rtp_point_pct - achieved_hw, rtp_point_pct + achieved_hw]

    append_jsonl(
        progress_file,
        {
            "event": "completed",
            "run_id": run_id,
            "stop_reason": stop_reason,
            "total_spins": total_spins,
            "chunks": chunks,
            "duration_seconds": duration_seconds,
            "rtp_point_pct": rtp_point_pct,
            "ci95_interval_pct": ci_interval,
            "output_dir": str(args.output_dir),
            "summary_file": str(out_json),
            "ts": utc_now(),
        },
    )

    print(json.dumps(summary, ensure_ascii=False))

    if _analysis_error is not None:
        return 1
    return 0


if __name__ == "__main__":
    _rc = main()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    os._exit(_rc)
