"""HTTP layer + chunk-sampler helpers, carved from
``player_impact_analyzer.py``.

P2-B4 (Phase 2 / Wave 2b): moves 8 helper functions out of PIA into this
canonical module. PIA re-exports all 8 via its dual-path import block so
all existing callers keep resolving via ``fresh_slotlab.player_impact_analyzer``.

Functions (canonical source here, re-exported from PIA):
  parse_args                  — argparse setup for the analyzer CLI.
  post_json                   — HTTP POST (urllib + json); reads ENDPOINT_URL.
  _classify_failure           — error string → 'network' | 'machine' enum.
  aimd_tune                   — AIMD concurrency / chunk-spins governor.
  post_json_with_retry        — exp-backoff retry wrapper around post_json.
  select_replay_chunks_by_md5 — resume-from-cache picker (inverted-md5 index).
  make_payload                — /MultiRobotTestSpinVariant request body builder.
  run_sampling_chunk          — one-chunk fetch-loop wrapper.

Module-level constants (canonical source here, re-exported from PIA):
  DEFAULT_ENDPOINT_URL        — fallback endpoint (hard-wired internal server).
  ENDPOINT_URL                — mutable; overridden by main() via
                                ``import fresh_slotlab.analyzer.core.base_pipeline
                                as _bp; _bp.ENDPOINT_URL = args.endpoint_url``.
  _RETRYABLE_HTTP_CODES       — 5xx codes that trigger retry in post_json_with_retry.
  MIN_CHUNK_SPINS             — AIMD floor for chunk_spins.
  SUCCESS_STREAK_FOR_GROW     — AIMD consecutive-success threshold before grow.
  CHUNK_SPINS_GROWTH          — AIMD multiplicative growth factor.
  CIRCUIT_PAUSE_S             — pause duration after a fully-failed batch.
  DEFAULT_GUIDELINE_RULES_PATH — default path to guideline rules JSON.

Architecture reference:
  session_artifacts/_arch/04_architecture_proposal_v5.md §6.2 deliverable 1.

Cycle-freedom contract (ticket P2-B4 §3 C5):
  MUST NOT import from ``fresh_slotlab.player_impact_analyzer``.
  MAY import from ``core/parser.py``, ``core/_utils.py``, ``core/writer.py``.
  core/parser.py, core/aggregator.py, core/writer.py MUST NOT import from
  this module (wrong direction).

Per memory feedback_subprocess_import_suicide_and_module_globals.md:
  No I/O at import time. Constants + function defs only.

Per memory feedback_upstream_throttle_ceiling.md:
  aimd_tune growth/decrement formula is preserved byte-for-byte.
  Do NOT modify AIMD coefficients.

Per memory feedback_perf_claim_needs_e2e_event_stream.md:
  P1-A1 canary (test_analyzer_three_invocation_parity.py) is the e2e proof.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Dual-path import of utils needed by the 8 carved functions.
# Package-mode path in the try arm; standalone-script fallback
# (fresh_slotlab/ on sys.path) in the except arm.
# Mirrors the pattern established by writer.py (P2-B3).
try:
    from fresh_slotlab.analyzer.core._utils import (
        _DEFAULT_BANKROLL_MULTIPLIERS,
        _DEFAULT_BANKRUPTCY_SESSION_SPINS,
    )
    from fresh_slotlab.analyzer.core.parser import parse_chunk_response
    from fresh_slotlab.analyzer.core.writer import _save_chunk_cache
    from fresh_slotlab.chunk_index import _rebuild_by_md5
    from fresh_slotlab.machine_md5 import lookup_machine_md5 as _lookup_machine_md5
    from fresh_slotlab.rawdata_index import update_entry as _rawdata_index_update_entry
    from fresh_slotlab.round_win import RoundWinRule
except ImportError:  # running as a standalone script
    from analyzer.core._utils import (  # type: ignore[no-redef]
        _DEFAULT_BANKROLL_MULTIPLIERS,
        _DEFAULT_BANKRUPTCY_SESSION_SPINS,
    )
    from analyzer.core.parser import parse_chunk_response  # type: ignore[no-redef]
    from analyzer.core.writer import _save_chunk_cache  # type: ignore[no-redef]
    from chunk_index import _rebuild_by_md5  # type: ignore[no-redef]
    from machine_md5 import lookup_machine_md5 as _lookup_machine_md5  # type: ignore[no-redef]
    from rawdata_index import update_entry as _rawdata_index_update_entry  # type: ignore[no-redef]
    from round_win import RoundWinRule  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Module-level constants (canonical source — PIA re-imports these)
# ---------------------------------------------------------------------------

DEFAULT_ENDPOINT_URL = "http://192.168.10.21:15060/MachineTest/MultiRobotTestSpinVariant"
ENDPOINT_URL = DEFAULT_ENDPOINT_URL  # mutable; overridden by --endpoint-url
# We always hit the Variant endpoint. ``MachineName`` on the payload is
# passed through verbatim from machines.json — a variant key like
# "M273$1$1-2-3" or a plain machine name like "M14" both work: the
# Variant endpoint looks the key up in its MachineTestVariants map and
# either rewrites to (underlying + selector params) or falls through
# to a plain test-spin when the key isn't a variant. See
# docs/upstream/MachineTest-TestSpin.md.

# Default path to guideline rules JSON. Computed relative to THIS file
# so the path resolves correctly regardless of where the repo is cloned.
# base_pipeline.py lives at fresh_slotlab/analyzer/core/base_pipeline.py;
# parents[3] is the project root; configs/ sits directly under that.
DEFAULT_GUIDELINE_RULES_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "classic_slots_guideline_rules.json"
)

# 5xx / transient-network retry policy shared by the live sampling loop
# (run_sampling_chunk) and the dev batch sampler. One 5xx or timeout on
# a long overnight run used to abort the whole machine; this wrapper
# rides through them. Non-retryable errors (4xx / JSONDecodeError /
# anything else) propagate on the first occurrence — retrying won't
# help and would just delay the real cause.
_RETRYABLE_HTTP_CODES = frozenset({500, 502, 503, 504})

# AIMD (additive-increase / multiplicative-decrease) adaptive tuning
# for batch_concurrency + chunk_spin_times. Halves on a network-class
# fully-failed batch (gives upstream breathing room). Does NOT halve
# on machine-class failures — retrying a smaller batch won't help if
# the machine is emitting garbage; bail-fast via the _MACHINE counter
# is the right response there.
#
# Tuned 2026-04-26 for internal-network default:
#   - SUCCESS_STREAK_FOR_GROW dropped from 3 → 1: a single fluke
#     shouldn't cost 3 batches of staying at half-conc. Internal
#     network's hiccups are short, recovery should be fast.
#   - CIRCUIT_PAUSE_S dropped from 20.0s → 3.0s: 20s was for external
#     per-IP throttle cooldown; internal upstream needs nothing
#     beyond a brief TCP-stack-clear pause.
MIN_CHUNK_SPINS = 500
SUCCESS_STREAK_FOR_GROW = 1
CHUNK_SPINS_GROWTH = 1.25
CIRCUIT_PAUSE_S = 3.0

# ---------------------------------------------------------------------------
# 8 carved functions (bodies verbatim from PIA per P2-B4 §4 out-of-scope)
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Player-impact analyzer for slot test endpoint with true batch concurrency."
    )
    parser.add_argument("--machine", default="M14")
    parser.add_argument("--rtp-mode", type=int, default=1)
    parser.add_argument("--bet", type=int, default=1000)
    # Graceful-stop flag file. When set and the file exists, the main
    # chunk loop bails out between chunks and the summary records
    # stop_reason="user_stop". Cross-platform alternative to SIGTERM
    # (the Windows subprocess.terminate() calls TerminateProcess which
    # doesn't deliver a catchable signal). Backend writes this file
    # when the operator clicks Stop.
    parser.add_argument("--stop-flag-file", type=Path, default=None)
    parser.add_argument("--target-halfwidth-pp", type=float, default=0.5)
    parser.add_argument("--chunk-spin-times", type=int, default=5000)
    parser.add_argument("--chunk-robot-count", type=int, default=20)
    parser.add_argument("--batch-concurrency", type=int, default=2)
    parser.add_argument("--max-chunks", type=int, default=120)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", default=None, help="optional external run id for orchestration")
    # When set, the resume-from-cache replay skips stats merge for
    # any chunk whose envelope (_config_md5 / _code_md5) differs from
    # these upstream values. Max-chunk-index tracking still happens so
    # new chunks pick the next free index. Default: empty strings =
    # no filter (backward-compat — merges every chunk, same as pre-
    # 2026-04-21 behaviour). Backend passes the current machines.json
    # md5 here so md5-drift resumes don't pollute stats with historical
    # chunks but DO co-exist with them on disk.
    parser.add_argument("--upstream-config-md5", default="",
                        help="filter cache-read stats by chunk envelope config_md5")
    parser.add_argument("--upstream-code-md5", default="",
                        help="filter cache-read stats by chunk envelope code_md5")
    # Non-convergence early-abort. Default ON — bad machines (bug,
    # in-dev, wild variance) bail rather than burn the full budget.
    # Tests / dev can disable via --disable-non-convergence-abort.
    parser.add_argument("--disable-non-convergence-abort", action="store_true",
                        help="disable Tier-2 early-abort (RTP band + projection)")
    parser.add_argument(
        "--progress-file",
        type=Path,
        default=None,
        help="optional jsonl file path for chunk-level progress events",
    )
    parser.add_argument(
        "--bankruptcy-session-spins",
        type=int,
        default=_DEFAULT_BANKRUPTCY_SESSION_SPINS,
        help=(
            "session length (in spins) for each simulated bankroll trial. "
            "Higher values give the histogram longer horizons; requires "
            "enough pooled chunk rounds to build at least one window "
            "(chunk_spin_times × chunk_robot_count >= session_spins)."
        ),
    )
    parser.add_argument(
        "--bankruptcy-bankroll-multipliers",
        default="10,100,200,500",
        help=(
            "comma-separated bet multipliers for the bankruptcy "
            "simulation (rawdata-replay). Each tier yields a per-tier "
            "survival histogram. Default includes 10x as a short-play "
            "'tourist' baseline so the histogram grid shows how quickly "
            "minimal bankrolls bust; 100/200/500 remain the standard "
            "session-length tiers."
        ),
    )
    parser.add_argument(
        "--guideline-rules",
        type=Path,
        default=DEFAULT_GUIDELINE_RULES_PATH,
        help="path to external deterministic guideline check rules JSON",
    )
    parser.add_argument(
        "--chunk-cache-dir",
        type=Path,
        default=None,
        help="optional dir for raw API response caching (full per-chunk data for offline rebuild)",
    )
    parser.add_argument(
        "--from-cache",
        type=Path,
        default=None,
        help=(
            "skip API sampling; read chunk_*.json files from this directory "
            "and run the full parse → accumulate → report pipeline offline. "
            "Each file must have the chunk-cache envelope with a 'response' key."
        ),
    )
    parser.add_argument(
        "--resume-from-cache",
        type=Path,
        default=None,
        help=(
            "Resume mode: load any existing chunk_*.json from this dir (same "
            "shape as --from-cache), seed the accumulators with their state, "
            "then continue LIVE API sampling into the same dir from the next "
            "chunk index until the CI target or max_chunks is reached. "
            "Mutually exclusive with --from-cache. Skips chunks that fail sha256 "
            "integrity or whose config_md5 no longer matches upstream."
        ),
    )
    parser.add_argument(
        "--endpoint-url",
        type=str,
        default=None,
        help=f"override the sampling API endpoint (default: {DEFAULT_ENDPOINT_URL})",
    )
    parser.add_argument(
        "--upstream-machine-name",
        type=str,
        default=None,
        help=(
            "Override the ``MachineName`` value sent on each "
            "/MultiRobotTestSpinVariant POST. Defaults to --machine. "
            "Variant-aware callers pass the variant's upstream key "
            "(e.g. M273$1$1-2-3) here while --machine stays the "
            "display name (e.g. M273$WheelSelector$1$1-2-3) used for "
            "rawdata directory + summary identity. Non-variant "
            "callers can leave this unset."
        ),
    )
    parser.add_argument(
        "--machine-config-file",
        type=str,
        default=None,
        help=(
            "Path to a JSON file whose content is passed verbatim as "
            "the ``MachineConfig`` field on every upstream sampling "
            "request. Used to A/B test a designer's draft weights / "
            "paytable without shipping to the game server's cfg.json. "
            "Only makes sense for focused single-machine sampling; "
            "batch runs generally should NOT share an override."
        ),
    )
    # Commit B: play-type plugin framework flag (§9-rev Phase 1 #18).
    # Default OFF — flag-off path is byte-identical to the pre-Commit-B
    # baseline.  Flag-ON with an empty registry is also byte-identical
    # (all plugin loops short-circuit on `if active_plugins`).
    # Removal of inline mechanic code happens in later commits (C+).
    parser.add_argument(
        "--use-play-type-plugins",
        action="store_true",
        default=False,
        help=(
            "Enable the play-type plugin framework wiring in parse_chunk_response. "
            "With an empty plugin registry (Commit B) this flag is a no-op: "
            "no accumulators fire, output is byte-identical to flag-off. "
            "Concrete plugins are registered in later commits (C+). "
            "Per 04_v2.md §9-rev Phase 1 deliverable #18."
        ),
    )
    return parser.parse_args()


def post_json(payload: dict[str, Any], timeout: float) -> Any:
    req = urllib.request.Request(
        ENDPOINT_URL,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def _classify_failure(error_str: str) -> str:
    """Classify a chunk-failure error string into 'network' or 'machine'.

    The ``rec.error`` strings produced by ``run_sampling_chunk`` and
    ``parse_chunk_response`` already encode the failure type — this
    helper is the single place that interprets them so the bail logic
    can apply different thresholds.

    Returns:
      - 'network' for transient errors that retry might help with:
        5xx HTTP, TimeoutError, URLError, IncompleteRead, TCP resets,
        and the generic "request_failed_<TypeName>" fallback.
      - 'machine' for permanent errors that retry won't help:
        4xx HTTP (bad request / config mismatch), parse_failed_*,
        response_shape_unexpected_*, schema_drift_*. Empty / unknown
        error strings default to 'machine' (fail-fast on uncertainty
        is safer than burning the budget on something we don't
        understand).

    Pure function so tests can pin every error-string→class mapping
    without spawning a subprocess.
    """
    if not error_str:
        return "machine"  # safer default: bail fast on unknown
    e = str(error_str)
    # HTTP errors carry the code in the suffix.
    if e.startswith("request_failed_http_"):
        try:
            code = int(e.rsplit("_", 1)[-1])
        except ValueError:
            return "machine"
        return "network" if code in _RETRYABLE_HTTP_CODES else "machine"
    # Explicit network-class prefixes from run_sampling_chunk.
    if e.startswith("request_failed_network_"):
        return "network"
    # Generic Exception fallback — these are typically network-layer
    # weirdness (ConnectionResetError etc.) that the more-specific
    # except-clauses didn't catch. Retry is reasonable.
    if e.startswith("request_failed_"):
        return "network"
    # Everything else: machine-side issue.
    if e.startswith("parse_failed_"):
        return "machine"
    if e.startswith("response_shape_unexpected"):
        return "machine"
    if e.startswith("schema_drift_"):
        return "machine"
    return "machine"


def aimd_tune(
    current_concurrency: int,
    current_chunk_spins: int,
    max_concurrency: int,
    max_chunk_spins: int,
    batch_fully_failed: bool,
    consecutive_successful: int,
) -> tuple[int, int, int, bool]:
    """Adjust concurrency + chunk_spins based on the latest batch
    outcome.

    Returns ``(new_concurrency, new_chunk_spins, new_consecutive_successful,
    should_pause)``.

    * Fully-failed batch → halve both (floor 1 / MIN_CHUNK_SPINS),
      reset success streak, signal to caller that it should pause
      CIRCUIT_PAUSE_S before the next submit (gives upstream breathing
      room).
    * Any success in the batch → increment success streak. After
      ``SUCCESS_STREAK_FOR_GROW`` consecutive clean batches, grow
      concurrency by 1 and chunk_spins by ``CHUNK_SPINS_GROWTH``
      (capped at the user's original values).

    Pure function so tests can walk through state transitions without
    having to run the analyzer loop.
    """
    if batch_fully_failed:
        new_conc = max(1, current_concurrency // 2)
        new_spins = max(MIN_CHUNK_SPINS, current_chunk_spins // 2)
        return (new_conc, new_spins, 0, True)
    # Any success: bump streak.
    new_success = consecutive_successful + 1
    new_conc = current_concurrency
    new_spins = current_chunk_spins
    if new_success >= SUCCESS_STREAK_FOR_GROW:
        new_conc = min(max_concurrency, current_concurrency + 1)
        new_spins = min(max_chunk_spins, int(current_chunk_spins * CHUNK_SPINS_GROWTH))
        new_success = 0
    return (new_conc, new_spins, new_success, False)


def post_json_with_retry(
    payload: dict[str, Any],
    timeout: float,
    max_attempts: int = 3,
    initial_backoff_s: float = 1.0,
    max_backoff_s: float = 5.0,
) -> Any:
    """Call post_json with exp-backoff on transient network errors.

    Retryable classes:
      * HTTPError with code in {500, 502, 503, 504}
      * URLError (DNS / connection refused / etc.)
      * TimeoutError / socket.timeout
      * http.client.IncompleteRead (truncated body mid-stream —
        typical of flaky proxies returning EOF prematurely)
      * http.client.RemoteDisconnected (connection closed before a
        response — typical of upstream load-balancer draining)
      * ConnectionError and its subclasses (ConnectionResetError,
        ConnectionAbortedError, BrokenPipeError, etc. — TCP-level
        resets from any intermediate hop)

    Previously IncompleteRead + ConnectionReset fell through to the
    caller's bare ``except Exception`` → zero retries → the chunk
    failed on first try regardless of transience.

    Backoff doubles each attempt (1s → 2s → 4s) but is capped at
    ``max_backoff_s`` so unbounded ``max_attempts`` can't produce
    multi-minute sleeps.

    Defaults tuned 2026-04-26 for internal-network upstream
    (192.168.10.21:15060 since commit 527618d). External upstream's
    per-IP throttling cooldowns made 5 attempts × 30s cap ≈ ~30s
    retry window necessary; internal hiccups are sub-second so 3
    attempts × 5s cap ≈ ~6s window is plenty without burning time
    on errors that won't transiently clear. Bail-fast goes via the
    machine-class counter at the loop level (see ``_classify_failure``
    + ``MAX_CUMULATIVE_FAILED_CHUNKS_MACHINE``).
    """
    import socket
    from http.client import IncompleteRead, RemoteDisconnected
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return post_json(payload, timeout)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code not in _RETRYABLE_HTTP_CODES:
                raise
        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            IncompleteRead,
            RemoteDisconnected,
            ConnectionError,
        ) as exc:
            last_exc = exc
        if attempt + 1 < max_attempts:
            delay = min(max_backoff_s, initial_backoff_s * (2 ** attempt))
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def select_replay_chunks_by_md5(
    cache_read_dir: Path,
    sidecar_payload: dict[str, Any],
    upstream_config_md5: str,
    upstream_code_md5: str,
) -> tuple[list[Path], int]:
    """Pre-filter chunk_files for the cache-replay loop based on md5
    sidecar's INVERTED INDEX.

    2026-04-26 architectural fix (user feedback: "你应该有个管理 rawdata
    的机制，比如索引啥的，而不是要去读每个 rawdata 才知道 md5"):
    instead of walking every sidecar entry to filter, we look up the
    inverted index ``sidecar.by_md5[(cfg|code)]`` directly. The
    sidecar maintains both indexes (per-chunk dict + by_md5 inverted
    map) on every write, so the read path never iterates.

    Pure function so the regression test in
    ``tests/backend/test_analyzer_chunk_prefilter.py`` can pin the
    behavior without spawning a subprocess.

    ``sidecar_payload`` is the full ``get_chunks_index(mode_dir)``
    return value — i.e. ``{"_version", "chunks", "by_md5"}``. The
    helper looks up the matching bucket via ``by_md5``; falls back
    to deriving it in-memory if an older sidecar is loaded without
    the inverted index field.

    Returns ``(chunk_files, max_existing_idx)``:
      - ``chunk_files``: paths of chunks stamped with the given md5
        pair, sorted by chunk_index. Empty when no chunks match
        (legitimate "fresh-pull just landed; nothing cached" state).
      - ``max_existing_idx``: max chunk_index across the FULL
        sidecar so resume-mode picks an idx that doesn't collide
        with historical-md5 chunks.
    """
    if not sidecar_payload or not isinstance(sidecar_payload, dict):
        return [], 0
    chunks_dict = sidecar_payload.get("chunks") or {}
    if not isinstance(chunks_dict, dict) or not chunks_dict:
        return [], 0
    # Direct O(1) lookup via the inverted index. Falls back to
    # deriving the bucket from chunks_dict in-memory only when an
    # older sidecar is loaded without the by_md5 field.
    by_md5 = sidecar_payload.get("by_md5")
    if not isinstance(by_md5, dict):
        by_md5 = _rebuild_by_md5(chunks_dict)
    key = f"{upstream_config_md5 or ''}|{upstream_code_md5 or ''}"
    matching_names = by_md5.get(key, [])
    chunk_files = [cache_read_dir / name for name in matching_names]
    max_existing_idx = max(
        (int(e.get("idx", 0) or 0)
         for e in chunks_dict.values()
         if isinstance(e, dict)),
        default=0,
    )
    return chunk_files, max_existing_idx


def make_payload(
    machine: str,
    rtp_mode: int,
    bet: int,
    spin_times: int,
    robot_count: int,
    init_credits: int,
    reset_each_spin: bool,
    continue_after_bankrupt: bool,
    upstream_machine_name: str | None = None,
    machine_config: str | None = None,
) -> dict[str, Any]:
    """Build a /MultiRobotTestSpinVariant request payload.

    ``machine`` identifies the row locally (display name for variant
    rows, raw name for non-variants). ``upstream_machine_name`` —
    when provided — becomes the ``MachineName`` field on the
    payload; otherwise ``MachineName`` falls back to ``machine``.

    Variant rows pass the variant's upstream key (e.g. ``M273$1$1-2-3``)
    as ``upstream_machine_name`` so the upstream Variant endpoint can
    rewrite it to (underlying + selector params) server-side. Non-
    variant rows leave it None and both fields hold the plain name.

    ``machine_config`` — optional JSON string (see upstream docs:
    MachineConfig on MachineTestRequest). When non-empty it's sent
    on every request so upstream uses it in place of cfg.json for
    this machine, letting us A/B test designer weights without a
    server deploy. Only attach the field when actually provided —
    blank string is the server's "use global cfg" signal and the
    field's presence alone should not change behavior."""
    payload: dict[str, Any] = {
        "MachineName": upstream_machine_name if upstream_machine_name else machine,
        "InitCreditsStr": str(init_credits),
        "BetStrategy": 0,
        "BetOriginStr": str(bet),
        "SpinTimes": int(spin_times),
        "RtpId": int(rtp_mode),
        "ShouldTestLuckyGame": False,
        "ContinueAfterBankrupt": bool(continue_after_bankrupt),
        "ResetPlayerStateAfterEachSpin": bool(reset_each_spin),
        "RobotCount": int(robot_count),
        "OutputAllRobotResult": True,
    }
    if machine_config:
        payload["MachineConfig"] = machine_config
    return payload


def run_sampling_chunk(
    chunk_index: int,
    machine: str,
    rtp_mode: int,
    bet: int,
    spin_times: int,
    robot_count: int,
    timeout: float,
    chunk_cache_dir: Path | None = None,
    bankruptcy_session_spins: int = _DEFAULT_BANKRUPTCY_SESSION_SPINS,
    bankruptcy_bankroll_mults: tuple[int, ...] = _DEFAULT_BANKROLL_MULTIPLIERS,
    upstream_machine_name: str | None = None,
    machine_config: str | None = None,
    envelope_config_md5: str = "",
    envelope_code_md5: str = "",
    round_win_rules: list[RoundWinRule] | None = None,
    use_play_type_plugins: bool = False,
) -> dict[str, Any]:
    payload = make_payload(
        machine=machine,
        rtp_mode=rtp_mode,
        bet=bet,
        spin_times=spin_times,
        robot_count=robot_count,
        init_credits=10**14,
        reset_each_spin=True,
        continue_after_bankrupt=True,
        upstream_machine_name=upstream_machine_name,
        machine_config=machine_config,
    )

    started = time.time()
    try:
        # Wrapped with retry so one 5xx / transient timeout doesn't
        # kill an overnight long-sample run. Non-retryable errors
        # (4xx, etc.) still propagate on first occurrence.
        resp = post_json_with_retry(payload, timeout)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "index": chunk_index, "error": f"request_failed_http_{exc.code}"}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {
            "ok": False,
            "index": chunk_index,
            "error": f"request_failed_network_{exc.__class__.__name__}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "index": chunk_index,
            "error": f"request_failed_{exc.__class__.__name__}",
        }

    # Persist the raw API response before ANY parsing so offline rebuild
    # always has untouched upstream data. Best-effort: disk failure is
    # silent (the run proceeds; the operator just can't rebuild later).
    _save_chunk_cache(
        resp, chunk_index, machine, rtp_mode, bet, spin_times, robot_count, chunk_cache_dir,
        override_config_md5=envelope_config_md5,
        override_code_md5=envelope_code_md5,
        lookup_machine_md5=_lookup_machine_md5,
        rawdata_index_update_entry=_rawdata_index_update_entry,
    )

    return parse_chunk_response(
        resp, chunk_index, bet, started,
        bankruptcy_session_spins=bankruptcy_session_spins,
        bankruptcy_bankroll_mults=bankruptcy_bankroll_mults,
        round_win_rules=round_win_rules,
        use_play_type_plugins=use_play_type_plugins,
    )
