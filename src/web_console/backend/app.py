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
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Phase 1 deploy refactor (2026-05-15): atomic JSON writers with per-file
# threading.Lock — replaces ad-hoc write_text() across config writers
# that raced under multi-user concurrency. See
# session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md §4.2.
from src.web_console.backend.config_writer import (
    atomic_json_read_modify_write,
    atomic_json_write,
)

# Phase 2 deploy refactor (2026-05-17): unified cell-level concurrency
# primitives.  CellLockRegistry replaces _IN_USE_MODES + _busy_keys +
# OperationCoordinator.  ConcurrencyLimiter replaces the v1 token bucket.
# See session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md §4.1 + §4.5.
from src.web_console.backend.cell_lock_registry import CellLockRegistry, CellOperation
from src.web_console.backend.rate_limiter import ConcurrencyLimiter


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
# Unified rawdata location (historical name ``dev_rawdata`` was
# misleading — there's no dev-vs-prod split, all sampled chunks land
# here). Prod deploys can point this at a non-repo path via the
# ``SLOT_RAWDATA_ROOT`` env var; unset → repo-relative default.
RAWDATA_ROOT_DEFAULT = ROOT / "rawdata"
# Default minimum chunks retention per (machine, mode): below this
# many spins, chunks are protected from both UI "delete" and auto-
# cleanup. Operator-tunable via /api/settings; persisted in
# state/console/settings.json.
_RAWDATA_MIN_RETENTION_SPINS_DEFAULT = 100_000
# Classifier dumps per-mode verdict JSONs under dev_reports/_classify/
# during the data-layer deep dive. Gitignored; available only after
# operator runs scripts/classify_payline_structure.py on the cache.
CLASSIFY_DIR = ROOT / "dev_reports" / "_classify"
# Per-machine paytable SHAPE inference (wild auto-inference + rich
# shape fields). Produced by scripts/infer_paytable.py from rawdata.
# Gitignored; empty / missing → endpoint returns "not_run" status.
PAYTABLES_DIR = ROOT / "configs" / "paytables"
MACHINES_CONFIG = ROOT / "configs" / "machines.json"
SERVERS_CONFIG = ROOT / "configs" / "servers.json"
# Operator-pref overrides for things that LOOK like server config but
# are per-deploy preferences (currently: default_server). Persisted next
# to console.db; gitignored — flipping the default server via the UI must
# NOT cause a merge conflict on next `git pull`. See `_load_settings`
# defaults + `_resolve_active_server_id` priority. Each create_app() also
# builds its own `settings_path` inside `sd / "settings.json"` for test
# isolation; this module constant is the fallback for module-level
# resolver calls that don't have a closure local in scope.
SETTINGS_PATH = ROOT / "state" / "console" / "settings.json"
# Phase 3 deploy (2026-05-17): uploaded config JSONs live here.
# Directory is gitignored; _registry.json inside tracks all uploads.
CONFIGS_UPLOAD_DIR = ROOT / "configs" / "uploaded_configs"
# Per-underlying MachineConfig override files that designers maintain
# locally (gitignored). Naming is hardcoded as ``<underlying>Cfg.txt``
# by convention — an M273 variant picks up machineconfig/M273Cfg.txt
# via variants_map resolution. Missing file → "no override available"
# → the Use-Local-Cfg checkbox in the UI stays hidden.
MACHINECONFIG_DIR = ROOT / "machineconfig"
ANALYZER = ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
FRONTEND_DIR = ROOT / "src" / "web_console" / "frontend"
SLOT_SPIN_ENDPOINT = "http://192.168.10.21:15060/MachineTest/MultiRobotTestSpinVariant"

# Offline inference scripts that are auto-triggered after every
# successful generate-report so the UI's payline / paytable panels
# stay in sync with the analyzer's data. Both scripts support
# per-(machine, mode) invocation — the classifier script writes a
# per-machine file (`{machine}_mode<N>.json`) to avoid clobbering
# other machines' verdicts under concurrent batch regen.
# INFER_PAYTABLE_SCRIPT / VERIFY_LABELS_SCRIPT constants removed per
# P1-B5 round-2 critic R2: dead code after the dedup refactor. The
# canonical helper `fresh_slotlab.post_inference.run_post_analyzer_
# inference` resolves both script paths from its `scripts_dir`
# parameter (which the wrapper below passes as `ROOT / "scripts"`).


def _run_post_analyzer_inference(
    machine: str,
    mode: int,
    *,
    timeout_sec: float = 300.0,
    rawdata_root: Path | None = None,
    paytables_dir: Path | None = None,
    classify_dir: Path | None = None,
    log_to_dir: Path | None = None,
) -> dict[str, Any]:
    """Fire the two offline inference scripts for one (machine, mode).

    Thin wrapper around ``fresh_slotlab.post_inference.run_post_analyzer_inference``
    (P1-B5 — inference-trigger dedup; ticket §3 C1 + C2).

    Called right after a successful generate-report so the UI's
    payline-classification + paytable-shape panels stay in sync
    with the just-produced analyzer summary. Best-effort — failures
    are captured in the returned dict but do NOT propagate. Generate-
    report has already written its own artifacts by the time this
    runs; losing the inference artifacts is non-fatal (operator can
    re-run the scripts manually if the UI panel shows "not_run").

    ``rawdata_root`` (optional) is forwarded as ``SLOT_RAWDATA_ROOT``
    env to the subprocess so tests that point the app at a tmp
    rawdata dir don't accidentally scan the real 9 GB production
    tree. Production callers typically pass ``None`` and rely on the
    parent process's own env.

    ``paytables_dir`` / ``classify_dir`` (optional) are forwarded as
    ``--output-dir`` CLI args so alternate-universe callers (tests,
    the virtual-machine console under slot_designer/) write their
    inference artefacts into their own directory tree instead of
    clobbering the real ``configs/paytables/`` + ``dev_reports/
    _classify/``. Production callers pass ``None`` → scripts use
    their built-in defaults (same behaviour as before this param
    existed).

    ``log_to_dir`` (optional) writes the full results dict to
    ``<log_to_dir>/_post_hook.json`` before returning, same contract
    as the batch-gen worker. Without this, the in-process path's
    daemon thread drops its return value on the floor and silent
    failures (timeouts / subprocess not found / env issues) are
    invisible. memory/feedback_no_silent_swallow.md: any best-effort
    post-hook must persist its outcome.
    """
    from fresh_slotlab.post_inference import run_post_analyzer_inference as _canonical  # noqa: PLC0415

    # summary_path: the canonical helper uses it to derive the dir for the
    # failure-diagnostic file (C3). When log_to_dir is set it equals the
    # output_dir; otherwise synthesise a plausible path from log_to_dir or
    # fall back to a sentinel that produces no diagnostic (script_missing
    # etc. still log to stderr per C3).
    if log_to_dir is not None:
        _summary_path = Path(log_to_dir) / "player_impact_summary.json"
    else:
        # No output_dir available from this call signature — use a no-op dir.
        # Failure stderr logging still fires (C3); on-disk diagnostic is best-effort.
        _summary_path = Path(".") / "player_impact_summary.json"

    # Do NOT pass log_to_dir to the canonical helper — the canonical helper
    # writes _post_hook.json in the InferenceResult / scripts-array format,
    # but existing tests and callers expect the old flat dict format
    # {machine, mode, paytable_shape: {ok, returncode, stderr_tail}, ...}.
    # We reconstruct that format below and persist it ourselves.
    _canonical_result = _canonical(
        summary_path=_summary_path,
        paytables_dir=paytables_dir,
        classify_dir=classify_dir,
        opts={
            "machine": machine,
            "mode": mode,
            "scripts_dir": ROOT / "scripts",
            "rawdata_root": rawdata_root,
            "timeout_sec": timeout_sec,
            # log_to_dir: NOT forwarded — we handle persistence below.
        },
    )

    # Build backward-compatible result dict (same shape as original inline impl).
    # Tests and the fire-and-forget daemon thread read this dict; keep field
    # names stable (returncode vs rc — matches pre-P1-B5 key name).
    results: dict[str, Any] = {"machine": machine, "mode": mode}
    if _canonical_result.skipped is not None:
        results["skipped"] = _canonical_result.skipped
    for s in _canonical_result.scripts:
        entry: dict[str, Any] = {"ok": s.ok}
        if s.rc is not None:
            entry["returncode"] = s.rc
        if s.error is not None:
            # Normalize timeout error to the short form the original impl used.
            # The canonical helper uses "timeout_after_Xs"; callers (and tests)
            # that predated P1-B5 expect "timeout" so backward compat is preserved.
            _err = s.error
            if _err.startswith("timeout_after_"):
                _err = "timeout"
            entry["error"] = _err
        if s.stderr_tail:
            entry["stderr_tail"] = s.stderr_tail
        results[s.name] = entry

    # Persist outcome to disk (per memory feedback_no_silent_swallow.md):
    # the daemon thread drops its return value on the floor, so this file is
    # the only persistence for in-process path outcomes.
    if log_to_dir is not None:
        import os as _os  # noqa: PLC0415
        try:
            Path(log_to_dir).mkdir(parents=True, exist_ok=True)
            (Path(log_to_dir) / "_post_hook.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            # Don't let a log-write failure alter the hook's effective outcome.
            pass

    return results


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
    server_id: str = Field(default="")
    from_cache_dir: str = Field(default="")  # if set, analyzer uses --from-cache
    resume_from_cache_dir: str = Field(default="")  # if set, analyzer uses --resume-from-cache
    # Upstream md5 pair for the analyzer's resume-read filter. When
    # both set (from machines.json at batch-start time), the analyzer
    # only merges stats from chunks whose envelope md5 matches; other
    # chunks stay on disk but are skipped. Prevents mixed-md5 stat
    # pollution on md5-drift while still persisting new chunks to
    # rawdata/. Empty strings = no filter (back-compat for callers
    # that don't pass these).
    upstream_config_md5: str = Field(default="")
    upstream_code_md5: str = Field(default="")
    # target_halfwidth_pp == 0 encodes the "fuzzy" tier (no CI stop;
    # backend resolves max_chunks to target ~1M spins). Any positive
    # value is a normal CI half-width in percentage points.
    target_halfwidth_pp: float = Field(default=0.5, ge=0)
    # 2026-05-22: floor lifted from 5000 -> 10000 per operator request
    # (cleaner per-chunk RTP variance). Frontend's per-machine
    # heuristic also enforces this floor for batch flows. Tests that
    # want smaller chunks (cheaper fixtures) keep passing explicit
    # values; this only affects callers that omit the field.
    chunk_spin_times: int = Field(default=10000, gt=0)
    # 2026-04-24 internal-server bench (M14 mode 1, chunk=2000) sized
    # the 8×8 / 8×16 / 8×32 / 8×48 progression that justified r=8 c=8
    # as the WAN-prod default. 2026-05-22 loopback measurement showed
    # the direction inverts (small robot + high conc wins on loopback);
    # the loopback-deployed console picks the right shape via
    # _LOOPBACK_HARDCODED_TUNING + per-server tuning storage. These
    # defaults stay tuned for the WAN regime so external operators
    # who omit explicit values still get a sensible request.
    chunk_robot_count: int = Field(default=8, gt=0)
    batch_concurrency: int = Field(default=8, gt=0)
    max_chunks: int = Field(default=120, gt=0)
    # 2026-05-22: lowered 300 -> 60. Previous value was sized for a
    # public-internet endpoint at p99 chunk wall ~30s with 10x retry
    # safety. Internal-deploy / loopback p95 chunk wall is ~10s so
    # 60s keeps 5-6x margin while giving the operator a quick failure
    # signal instead of a 5-minute hang when the simulator stalls.
    # WAN-prod operators who need more time can override per-request.
    timeout: float = Field(default=60.0, gt=0)
    bankruptcy_session_spins: int = Field(default=10000, gt=0)
    bankruptcy_bankroll_multipliers: str = Field(default="10,100,200,500")
    model_id: str = Field(default="gpt-5.4-mini")
    # Optional per-run MachineConfig override (see upstream
    # MachineTestRequest.MachineConfig field). JSON string; non-empty
    # → analyzer writes it to a file under output_dir and passes
    # --machine-config-file so every upstream request carries the
    # override. Intended for focused single-machine A/B testing of
    # draft weights / paytables without a server deploy.
    machine_config: str = Field(default="")


class InterpretationRequest(BaseModel):
    run_id: str
    model_id: str


class ModelConfigUpdateRequest(BaseModel):
    provider: str
    api_key: str = Field(default="")


class CacheCleanupRequest(BaseModel):
    max_delete_bytes: int = Field(default=0, ge=0)


class RawdataVersionDeleteRequest(BaseModel):
    """Target one (config_md5, code_md5) bucket within a (machine, mode)
    for per-version cleanup. Empty md5 pair intentionally disallowed —
    "delete everything with missing envelope md5" is a risky op that
    belongs to force=True in the per-mode endpoint."""
    config_md5: str = Field(min_length=1)
    code_md5: str = Field(min_length=1)


class ServerEntry(BaseModel):
    id: str
    name: str
    endpoint: str = ""
    active: bool = False


class ServerUpdateRequest(BaseModel):
    name: str | None = None
    endpoint: str | None = None
    active: bool | None = None


def load_servers(path: Path | None = None) -> dict[str, Any]:
    target = path if path is not None else SERVERS_CONFIG
    if target.exists():
        return read_json(target) or {"servers": [], "default_server": ""}
    return {"servers": [], "default_server": ""}


def _current_md5_pairs(
    machine: str,
    machines_config: Path | None = None,
    mode: int | None = None,
) -> list[dict[str, str]]:
    """Return the set of (cfg_md5, code_md5) pairs that count as
    "current" for this machine/mode.

    Pre-2026-04-24 there was exactly ONE current pair (server global
    from ``machines.json``). Adding local-cfg override breaks that
    assumption: a chunk sampled with ``machineconfig/<u>Cfg.txt`` is
    ALSO "current" if the file's byte content still matches what the
    chunk was stamped with — just "current w.r.t. a different reference".

    Returns a list of dicts with ``cfg_md5`` / ``code_md5`` / ``label``
    / ``source`` so the UI can show both cells as "当前" while
    distinguishing which is which:

      [
        {"cfg_md5": "<server>", "code_md5": "<server>",
         "label": "服务端", "source": "server"},
        {"cfg_md5": "localcfg_<file-hash>", "code_md5": "<server>",
         "label": "本地 cfg", "source": "local"},  # only if file exists
      ]

    Best-effort — IO failure reading ``machineconfig/`` returns just
    the server pair.
    """
    up_config, up_code = _get_machine_md5(machine, machines_config, mode=mode)
    pairs: list[dict[str, str]] = [{
        "cfg_md5": up_config,
        "code_md5": up_code,
        "label": "服务端",
        "source": "server",
    }]
    try:
        _underlying, local_cfg_path = _resolve_local_cfg_for_machine(machine)
    except Exception:  # noqa: BLE001
        local_cfg_path = None
    if local_cfg_path is not None:
        try:
            content = local_cfg_path.read_text(encoding="utf-8")
            local_cfg_md5 = _derive_local_cfg_md5(content)
            # Only the config half of the pair differs when local cfg
            # is in play — analyzer code is unchanged. So the local
            # pair borrows ``code_md5`` from the server global.
            pairs.append({
                "cfg_md5": local_cfg_md5,
                "code_md5": up_code,
                "label": f"本地 cfg ({local_cfg_path.name})",
                "source": "local",
            })
        except OSError:
            pass
    return pairs


def _derive_local_cfg_md5(cfg_content: str) -> str:
    """Turn a MachineConfig override JSON string into a deterministic
    version tag that slots into the existing md5 filter / bucket
    system. Chunks produced with a local cfg override get stamped
    with this tag instead of upstream's global cfg md5 so they stay
    segregated from global-cfg chunks of the same machine / mode.

    Without this, override chunks get the GLOBAL md5 from upstream's
    /MachineConfigMd5 endpoint (which has no idea the request carried
    a per-call override) and silently mix with non-override chunks
    on subsequent resume-reads — a data pollution bug.

    Format: ``localcfg_<8-hex>`` — the prefix makes the UI's rawdata
    panel visibly distinguish local-cfg versions from server md5s
    (real server md5s are full hex strings; prefix is clear).
    Two operators with byte-identical cfg files hash to the same
    tag → chunks resume-compatibly across their machines, which is
    the desired "share designer draft results" semantics."""
    import hashlib
    digest = hashlib.sha1(cfg_content.encode("utf-8")).hexdigest()[:8]
    return f"localcfg_{digest}"


def _resolve_local_cfg_for_machine(
    machine_display: str,
    machines_config_path: Path | None = None,
    halls_path: Path | None = None,
    cfg_dir: Path | None = None,
) -> tuple[str, Path | None]:
    """Find the ``machineconfig/<underlying>Cfg.txt`` file that
    covers ``machine_display``. Returns ``(underlying, path)`` where
    ``path`` is ``None`` if no such file exists.

    All variants of the same underlying physical machine share a
    single local cfg file (variants_map flattens display name → raw
    machine name); operators maintain one ``M273Cfg.txt`` rather
    than 11 per-variant files.

    Two-step lookup:
      1. variants_map-resolved underlying → ``<u>Cfg.txt``
      2. filesystem fallback: regex-extract ``M<n>`` prefix from the
         display name → ``<base>Cfg.txt``. Triggers when halls.json
         hasn't been refreshed under the variants schema yet (empty
         ``variants_map``) so variant display names resolve to their
         own upstream_key (e.g. ``M15$0$``) instead of the physical
         ``M15``. The filename convention ``<M\\d+>Cfg.txt`` is a
         stable filesystem convention — see
         ``machine_variants.extract_base_machine_name`` for why this
         exception to the no-``$``-parsing rule is sound.

    Best-effort: any IO / parse error falls through to
    ``(machine_display, None)`` — the UI simply hides the checkbox
    rather than surfacing an error."""
    mc = machines_config_path or MACHINES_CONFIG
    hp = halls_path or (ROOT / "configs" / "machine_halls.json")
    dir_ = cfg_dir or MACHINECONFIG_DIR
    # Lazy import — machine_variants is imported elsewhere on the
    # cold path, avoid paying it on every call if this module is
    # imported for non-sampling use (e.g. unit tests of other areas).
    from src.web_console.backend.machine_variants import (
        extract_base_machine_name,
        load_variants_map,
        resolve_underlying_for_display,
    )
    try:
        data = json.loads(Path(mc).read_text(encoding="utf-8"))
        machines_rows = data.get("machines") or []
    except (OSError, json.JSONDecodeError):
        machines_rows = []
    variants_map = load_variants_map(hp)
    underlying = resolve_underlying_for_display(
        machine_display, machines_rows, variants_map,
    )
    candidate = dir_ / f"{underlying}Cfg.txt"
    if candidate.is_file():
        return underlying, candidate
    base = extract_base_machine_name(machine_display)
    if base != underlying:
        base_candidate = dir_ / f"{base}Cfg.txt"
        if base_candidate.is_file():
            return base, base_candidate
    return underlying, None


def save_servers(data: dict[str, Any], path: Path | None = None) -> None:
    target = path if path is not None else SERVERS_CONFIG
    # Phase 1 deploy: atomic + per-file-locked. Concurrent edits via
    # POST/PUT/DELETE /api/servers/* now serialize per-file instead of
    # racing on truncate-then-write (which under load could silently
    # lose the first writer's change).
    atomic_json_write(target, data, trailing_newline=True)


RAWDATA_ROOT = Path(os.getenv("SLOT_RAWDATA_ROOT", str(RAWDATA_ROOT_DEFAULT)))

# Analyzer CLI default for --bet; mirrored here so backend can detect
# cache/current bet mismatches and warn. Update both if the default
# ever changes.
_DEFAULT_ANALYZER_BET = 1000


def _peek_cache_bets(mode_dir: Path) -> set[int]:
    """Return the set of `_bet` values recorded across a cache dir's
    chunks. Opens each chunk's JSON envelope (small — just metadata)
    and plucks `_bet`. Returns empty set if dir missing or no readable
    chunks. Used by start_batch to warn when cache bet differs from
    the current run's bet.
    """
    if not mode_dir.is_dir():
        return set()
    bets: set[int] = set()
    for p in mode_dir.glob("chunk_*.json"):
        try:
            with p.open("r", encoding="utf-8") as f:
                env = json.loads(f.read())
            bet = env.get("_bet")
            if bet is not None:
                bets.add(int(bet))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return bets


def _get_machine_md5(
    machine: str,
    machines_config: Path | None = None,
    mode: int | None = None,
) -> tuple[str, str]:
    """Look up ``(config_md5, code_md5)`` for a machine from
    ``machines.json``.

    When ``mode`` is provided AND the entry has a ``modesMd5`` map
    (virtual registry, per-mode md5 2026-04-22), returns the md5
    specific to that mode. Otherwise falls back to the canonical
    real-machine flat-schema lookup (``configSummaryMd5`` /
    ``codeSummaryMd5``) via ``fresh_slotlab.machine_md5.lookup_machine_md5``
    — the single source of truth for the real-console schema.

    Mode-aware callers (classify_chunks, generate-report, pre-batch
    refresh) should pass ``mode`` so virtual machines with per-mode
    reel strips classify each mode's chunks against the right md5.

    P1-B1 (phase1/07_lookup_machine_md5_dedup §1 citing 04_v5 §6.1):
    flat-schema fallback now delegates to canonical instead of duplicating
    the read logic inline.
    """
    # P1-B1: import canonical real-machine lookup (lazy — mirrors app.py style
    # for fresh_slotlab imports; avoids circular-import risk at module load).
    from fresh_slotlab.machine_md5 import lookup_machine_md5  # noqa: PLC0415

    target = machines_config if machines_config is not None else MACHINES_CONFIG
    if mode is not None:
        # Virtual-machine path: check for per-mode modesMd5 block first.
        # Only real machines + legacy virtual entries lack modesMd5; those
        # fall through to the canonical flat-schema lookup below.
        if not target.exists():
            return "", ""
        try:
            data = read_json(target) or {}
            for m in data.get("machines", []):
                if m.get("machine") != machine:
                    continue
                per_mode = (m.get("modesMd5") or {}).get(str(int(mode)))
                if isinstance(per_mode, dict) and (
                    per_mode.get("configSummaryMd5") or per_mode.get("codeSummaryMd5")
                ):
                    return (
                        str(per_mode.get("configSummaryMd5", "")),
                        str(per_mode.get("codeSummaryMd5", "")),
                    )
                # No modesMd5 for this mode — fall through to flat-schema below.
                break
        except (OSError, json.JSONDecodeError, TypeError):
            # Narrowed per P1-B1 round-2 critic R2 to match canonical
            # `fresh_slotlab.machine_md5.lookup_machine_md5`'s exception
            # spec. Matches what JSON-on-disk reads can plausibly raise;
            # any other exception (KeyError, AttributeError, etc.) is a
            # programming bug worth surfacing rather than swallowing.
            return "", ""
    # Flat-schema path (real machines + virtual machines without modesMd5):
    # delegate to canonical single source of truth.
    return lookup_machine_md5(machine, target)


def _empty_rawdata_status(**extra: Any) -> dict[str, Any]:
    base = {
        "exists": False, "usable_chunks": 0, "mismatch_chunks": 0,
        "total_size_mb": 0.0,
        "upstream_config_md5": "", "upstream_code_md5": "",
        "saved_at": "", "unverifiable": False,
    }
    base.update(extra)
    return base


def _status_from_index_entry(
    entry: dict[str, Any],
    up_config: str,
    up_code: str,
    unverifiable: bool,
) -> dict[str, Any] | None:
    """Return a full status dict if the index entry is usable without a
    filesystem scan; None if caller must fall back to per-chunk scan.

    Conditions for the fast path:
    - entry has consistent md5 across all chunks (not mixed)
    - either upstream is unknown (accept everything) OR all chunks' md5
      matches the current upstream md5 (no mismatches to report)
    When md5 drifted or chunks are heterogeneous, the caller can't shortcut
    — we need the per-chunk md5 to count mismatched chunks correctly.
    """
    if entry.get("mixed_md5"):
        return None
    chunks_n = int(entry.get("chunks", 0))
    if chunks_n == 0:
        return _empty_rawdata_status(
            upstream_config_md5=up_config, upstream_code_md5=up_code,
            unverifiable=unverifiable,
        )
    cfg = str(entry.get("config_md5", ""))
    code = str(entry.get("code_md5", ""))
    if unverifiable:
        pass  # accept whatever's there
    else:
        if not cfg and not code:
            # Envelope has no md5 tags (legacy) — treat all as mismatch.
            # Fall back so size accounting works per-chunk.
            return None
        if cfg != up_config or code != up_code:
            # All chunks carry the same md5 but it's not current. Fall
            # back so the caller gets a correct mismatch_chunks count.
            return None
    return {
        "exists": True,
        "usable_chunks": chunks_n,
        "mismatch_chunks": 0,
        "total_size_mb": round(
            int(entry.get("total_size_bytes", 0)) / (1024 * 1024), 2
        ),
        "upstream_config_md5": up_config,
        "upstream_code_md5": up_code,
        "saved_at": str(entry.get("last_saved_at", "")),
        "unverifiable": unverifiable,
    }


def check_rawdata_status(
    machine: str,
    mode: int,
    rawdata_root: Path | None = None,
    machines_config: Path | None = None,
) -> dict[str, Any]:
    """Per-chunk rawdata availability and MD5 match for a machine-mode.

    Read-only — NEVER mutates disk. Returns counts the UI + analyzer
    use to decide what to do next; actual deletions happen only via
    cache-management paths (``_auto_cleanup_for_space`` under disk
    pressure, ``POST /api/cache/cleanup`` manual button, per-mode
    ``delete_rawdata``, or the per-version ``DELETE
    /api/rawdata/{m}/mode/{mode}/version`` endpoint).

    Before 2026-04-21 this function took ``auto_delete_mismatched=True``
    and unlinked md5-mismatched chunks directly — that was the M1|1
    regression path (``start_batch`` called it per item, wiping locked
    chunks). The current semantics: md5 is a tag, not a destruction
    signal. Historical md5 chunks stay on disk until operator
    intervention.

    Hot path: consults `<rawdata_root>/_index.json` (one open) when the
    cached entry is consistent and all chunks match upstream md5. Cold
    path (stale index, mixed md5, or md5 drift) falls back to a full
    per-chunk envelope scan and rebuilds the entry so the next call
    is fast again.

    Returns:
      {
        "exists": bool,
        "usable_chunks": int,       # chunks with matching MD5 (or unverifiable when upstream unknown)
        "mismatch_chunks": int,     # chunks with non-current MD5 (historical)
        "total_size_mb": float,     # size of remaining usable chunks
        "upstream_config_md5": str,
        "upstream_code_md5": str,
        "saved_at": str,            # earliest saved_at among usable chunks
        "unverifiable": bool,       # upstream MD5 unknown → can't verify
      }
    """
    root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT
    mode_dir = root / machine / f"mode_{mode}"
    if not mode_dir.is_dir():
        return _empty_rawdata_status()

    # Pass ``mode`` so virtual machines with per-mode reel strips
    # classify this mode's chunks against the right md5 (2026-04-22).
    up_config, up_code = _get_machine_md5(machine, machines_config, mode=mode)
    unverifiable = not up_config and not up_code

    # ── Fast path: try the cached index first ──
    # Validated by matching entry.chunks against the actual glob count;
    # any drift (external delete, failed writer, etc.) forces a rescan.
    try:
        from fresh_slotlab.rawdata_index import load_index, entry_key
        idx = load_index(root)
        entry = idx.get("entries", {}).get(entry_key(machine, mode))
        if entry is not None:
            actual_count = sum(1 for _ in mode_dir.glob("chunk_*.json"))
            if actual_count == int(entry.get("chunks", -1)):
                status = _status_from_index_entry(
                    entry, up_config, up_code, unverifiable
                )
                if status is not None:
                    return status
    except Exception:  # noqa: BLE001
        # Index read failures shouldn't block the API call; fall
        # through to the authoritative filesystem scan.
        pass

    # ── Cold path: per-chunk metadata scan + index rebuild ──
    # Use the per-mode chunk sidecar (``_chunks.json``) so we don't
    # ``json.loads`` every chunk file just to read the envelope
    # header. Sidecar auto-rebuilds via 4KB peek per chunk when
    # missing — turns a multi-GB rawdata scan into a few-MB peek
    # sweep. The click-a-machine-with-huge-rawdata slowness reported
    # 2026-04-24 was this loop on every UI refresh.
    chunks = sorted(mode_dir.glob("chunk_*.json"))
    if not chunks:
        return _empty_rawdata_status()

    from fresh_slotlab.chunk_index import get_chunks_index
    try:
        sidecar = get_chunks_index(mode_dir)
        sidecar_entries = sidecar.get("chunks") or {}
    except Exception:  # noqa: BLE001
        sidecar_entries = {}

    # Multi-current md5 set: server global + any local-cfg hash whose
    # machineconfig/<underlying>Cfg.txt is on disk. Chunks matching
    # ANY pair are "usable" (current); the rest are historical.
    current_set = {
        (p["cfg_md5"], p["code_md5"])
        for p in _current_md5_pairs(machine, machines_config, mode=mode)
        if p["cfg_md5"] or p["code_md5"]
    }

    usable = 0
    mismatched: list[Path] = []
    saved_ats: list[str] = []
    usable_size = 0

    for chunk_path in chunks:
        entry = sidecar_entries.get(chunk_path.name)
        if isinstance(entry, dict):
            cfg_md5 = str(entry.get("cfg_md5", "") or "")
            code_md5 = str(entry.get("code_md5", "") or "")
            saved = str(entry.get("saved_at", "") or "")
            size_bytes = int(entry.get("size_bytes", 0) or 0)
        else:
            # Sidecar miss (not yet indexed / peek failed). Fall
            # back to full read for this chunk only — self-heals
            # on next call via sidecar rebuild.
            try:
                data = json.loads(chunk_path.read_text(encoding="utf-8"))
                cfg_md5 = str(data.get("_config_md5", ""))
                code_md5 = str(data.get("_code_md5", ""))
                saved = str(data.get("_saved_at", ""))
                size_bytes = int(chunk_path.stat().st_size)
            except Exception:
                mismatched.append(chunk_path)
                continue

        if unverifiable:
            # No upstream reference → accept as-is.
            usable += 1
            usable_size += size_bytes
            if saved:
                saved_ats.append(saved)
            continue

        # Empty MD5 in envelope = old format, can't verify → treat as mismatch.
        if not cfg_md5 and not code_md5:
            mismatched.append(chunk_path)
            continue
        if (cfg_md5, code_md5) in current_set:
            usable += 1
            usable_size += size_bytes
            if saved:
                saved_ats.append(saved)
        else:
            mismatched.append(chunk_path)

    # Refresh the index entry so the next read hits the fast path again.
    # Runs outside the main return so any failure here doesn't disturb
    # the canonical scan result.
    try:
        from fresh_slotlab.rawdata_index import update_entry
        update_entry(root, machine, mode, mode_dir)
    except Exception:  # noqa: BLE001
        pass

    return {
        "exists": True,
        "usable_chunks": usable,
        "mismatch_chunks": len(mismatched),
        "total_size_mb": round(usable_size / (1024 * 1024), 2),
        "upstream_config_md5": up_config,
        "upstream_code_md5": up_code,
        "saved_at": min(saved_ats) if saved_ats else "",
        "unverifiable": unverifiable,
    }


def _load_settings(settings_path: Path) -> dict[str, Any]:
    """Read operator-tunable settings from disk. Missing / malformed
    file → returns defaults. Callers read through here on each access
    so a settings update via /api/settings takes effect immediately.

    Fields:
      * ``min_retention_spins`` (int ≥ 0) — chunk-retention floor.
      * ``default_server`` (str) — operator override for which server
        sampling uses by default. Empty string means "follow servers.json
        shipped default → first-active fallback" in ``_resolve_active_server_id``.
        Stored here (not in tracked configs/servers.json) so flipping the
        default via the UI does not create a merge conflict on next pull.
      * ``server_tuning`` (dict[server_id, dict]) — per-server-endpoint
        autotune results persisted after /api/autotune completes. Each
        entry: ``{"chunk_robot_count": int, "batch_concurrency": int,
        "tuned_at": iso8601, "endpoint_kind": str, "probe": {...}}``.
        Looked up by BatchRunManager when a batch-run request omits
        the corresponding knob; lets a loopback-deployed server pick a
        different concurrency than the WAN-prod path without per-call
        tuning. Persisted server-side instead of frontend localStorage
        so the tuning survives browser swaps + benefits LAN clients
        that hit the same console backend.
      * ``auto_resume_orphan_runs`` (bool, default True) — A2 task
        2026-05-22. Controls whether RunManager._recover_orphan_running_runs
        re-submits interrupted samples on console startup. True
        (default): the previous run row is marked failed and a fresh
        run is spawned with --resume-from-cache pointed at the rawdata
        dir, so the analyzer picks up where it left off. False: the
        orphan is marked failed and the operator must manually retrigger.
        Flip to False when a runaway run was causing the console to
        crash (auto-resume would otherwise loop).
    """
    # Default per-mode settings for auto_sweep (07_decision §3).
    _AUTO_SWEEP_MODE_DEFAULTS: dict[str, Any] = {
        "chunk_spin_times": 10000,
        "chunk_robot_count": 2,
        "batch_concurrency": 16,
        "target_halfwidth_pp": 0.5,
        "max_chunks": 60,
    }
    defaults: dict[str, Any] = {
        "min_retention_spins": _RAWDATA_MIN_RETENTION_SPINS_DEFAULT,
        "default_server": "",
        "server_tuning": {},
        "auto_resume_orphan_runs": True,
        "auto_sweep": {
            "enabled": False,
            "schedule_mode": "daily",
            "schedule_value": "02:00",
            "skip_fresh_cells": True,
            "sweep_concurrency": 2,
            "binary_group_large_cap": 2,
            "max_consecutive_failures": 3,
            "consecutive_failure_window": 10,
            "structural_skip_machines": ["M250", "M260", "M264", "M268"],
            "cell_busy_timeout_s": 1800,
            "wall_time_per_cell_s": 7200,
            "modes": {
                "1": dict(_AUTO_SWEEP_MODE_DEFAULTS),
                "2": dict(_AUTO_SWEEP_MODE_DEFAULTS),
                "5": dict(_AUTO_SWEEP_MODE_DEFAULTS),
                "7": dict(_AUTO_SWEEP_MODE_DEFAULTS),
            },
        },
    }
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    out = dict(defaults)
    mrs = data.get("min_retention_spins")
    if isinstance(mrs, (int, float)) and mrs >= 0:
        out["min_retention_spins"] = int(mrs)
    ds = data.get("default_server")
    if isinstance(ds, str):
        out["default_server"] = ds
    ar = data.get("auto_resume_orphan_runs")
    if isinstance(ar, bool):
        out["auto_resume_orphan_runs"] = ar
    st = data.get("server_tuning")
    if isinstance(st, dict):
        clean: dict[str, dict[str, Any]] = {}
        for sid, entry in st.items():
            if not isinstance(sid, str) or not isinstance(entry, dict):
                continue
            rc = entry.get("chunk_robot_count")
            bc = entry.get("batch_concurrency")
            if (
                isinstance(rc, (int, float)) and rc > 0
                and isinstance(bc, (int, float)) and bc > 0
            ):
                clean[sid] = {
                    "chunk_robot_count": int(rc),
                    "batch_concurrency": int(bc),
                    "tuned_at": str(entry.get("tuned_at") or ""),
                    "endpoint_kind": str(entry.get("endpoint_kind") or ""),
                    "probe": dict(entry.get("probe") or {}),
                }
        out["server_tuning"] = clean
    # ── auto_sweep block (07_decision §3) ────────────────────────────────
    # If auto_sweep is missing or non-dict, use defaults wholesale.
    # If individual sub-keys are missing, fall back per-key.
    raw_as = data.get("auto_sweep")
    if isinstance(raw_as, dict):
        as_out: dict[str, Any] = dict(defaults["auto_sweep"])
        # Scalar booleans.
        for _bool_key in ("enabled", "skip_fresh_cells"):
            _v = raw_as.get(_bool_key)
            if isinstance(_v, bool):
                as_out[_bool_key] = _v
        # schedule_mode: must be "daily" or "interval".
        _sm = raw_as.get("schedule_mode")
        if isinstance(_sm, str) and _sm in ("daily", "interval"):
            as_out["schedule_mode"] = _sm
        # schedule_value: str (not validated further — upstream UI enforces format).
        _sv = raw_as.get("schedule_value")
        if isinstance(_sv, str):
            as_out["schedule_value"] = _sv
        # Positive-int scalars with inclusive bounds.
        _int_bounds: dict[str, tuple[int, int]] = {
            "sweep_concurrency": (1, 16),
            "binary_group_large_cap": (1, 16),
            "max_consecutive_failures": (1, 100),
            "consecutive_failure_window": (1, 1000),
            "cell_busy_timeout_s": (60, 86400),
            "wall_time_per_cell_s": (60, 86400),
        }
        for _ik, (_lo, _hi) in _int_bounds.items():
            _iv = raw_as.get(_ik)
            if isinstance(_iv, (int, float)) and _lo <= int(_iv) <= _hi:
                as_out[_ik] = int(_iv)
        # structural_skip_machines: list of strings.
        _ssm = raw_as.get("structural_skip_machines")
        if isinstance(_ssm, list) and all(isinstance(x, str) for x in _ssm):
            as_out["structural_skip_machines"] = list(_ssm)
        # modes: dict keyed by str mode number.
        raw_modes = raw_as.get("modes")
        if isinstance(raw_modes, dict):
            clean_modes: dict[str, dict[str, Any]] = dict(as_out["modes"])
            for _mode_key, _mode_def in defaults["auto_sweep"]["modes"].items():
                raw_mode = raw_modes.get(_mode_key)
                if not isinstance(raw_mode, dict):
                    continue
                clean_mode: dict[str, Any] = dict(_mode_def)
                _mode_int_bounds: dict[str, tuple[int, int]] = {
                    "chunk_spin_times": (1000, 100000),
                    "chunk_robot_count": (1, 16),
                    "batch_concurrency": (1, 32),
                    "max_chunks": (1, 1000),
                }
                for _mk, (_mlo, _mhi) in _mode_int_bounds.items():
                    _mv = raw_mode.get(_mk)
                    if isinstance(_mv, (int, float)) and _mlo <= int(_mv) <= _mhi:
                        clean_mode[_mk] = int(_mv)
                _thw = raw_mode.get("target_halfwidth_pp")
                if isinstance(_thw, (int, float)) and 0.0 <= float(_thw) <= 5.0:
                    clean_mode["target_halfwidth_pp"] = float(_thw)
                clean_modes[_mode_key] = clean_mode
            as_out["modes"] = clean_modes
        out["auto_sweep"] = as_out
    return out


# ── Per-server endpoint classification (used by autotune to pick a
# probe candidate grid sized to the endpoint's expected throughput) ──

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

_RFC1918_PREFIXES = (
    "10.",
    "192.168.",
    *(f"172.{n}." for n in range(16, 32)),
)


def _classify_endpoint_kind(endpoint_url: str) -> str:
    """Return ``"loopback"`` / ``"lan"`` / ``"wan"`` from an endpoint URL.

    Used to pick a sane autotune probe grid: loopback can sustain much
    higher concurrency than WAN before saturation, so the default
    candidates differ by an order of magnitude. Heuristic-only — any
    parse failure falls back to ``"wan"`` (the conservative grid).
    """
    if not isinstance(endpoint_url, str) or not endpoint_url:
        return "wan"
    try:
        host = urllib.parse.urlparse(endpoint_url).hostname or ""
    except (ValueError, TypeError):
        return "wan"
    host = host.lower()
    if host in _LOOPBACK_HOSTS:
        return "loopback"
    if any(host.startswith(p) for p in _RFC1918_PREFIXES):
        return "lan"
    return "wan"


# Probe candidate grids per endpoint kind. Used for LAN / WAN only —
# loopback bypasses the probe entirely (see _LOOPBACK_HARDCODED_TUNING
# below).
#
#  - LAN (RFC1918): 1-3ms RTT, gigabit, no rate limit. Moderate grid.
#  - WAN (anything else): public-internet, per-IP throttle exists.
#    Keep the existing conservative grid (matches the 2026-04-25
#    external-server benchmark that lives in AutoTuneRequest's docstring).
#
# Caller passes ``use_auto_grid=True`` (or omits robot/conc candidates)
# to opt in; explicit candidates always win over the preset.
_AUTO_GRIDS: dict[str, dict[str, list[int]]] = {
    "lan": {
        "robot_candidates": [8, 16, 24],
        "concurrency_candidates": [4, 8, 12, 16],
    },
    "wan": {
        "robot_candidates": [8, 16],
        "concurrency_candidates": [4, 8, 12],
    },
}


# Hardcoded tuning for loopback endpoints. Manual probe 2026-05-22 on
# the deployed Windows server (192.168.10.21, slot simulator on
# 127.0.0.1:15060) sampled r ∈ {2, 4, 8, 16, 24, 32} × c ∈ {8, 12, 16}
# over multiple probe rounds; r=2 c=16 won decisively on BOTH metrics
# (throughput 32196 spin/s + p95 0.192s — 5% better throughput AND 24%
# lower latency than the next best, r=4 c=10 at 30631 spin/s / 0.25s).
#
# Counter-intuitive direction (smaller robots not larger) — explained
# by the loopback path's near-zero HTTP overhead: bigger robot count
# only means more serial compute per request, occupying the simulator
# CPU longer; the throughput ceiling is fixed at ~30k spin/s by the
# simulator's worker pool, and small robot count + high concurrency
# best amortizes the wait across the available workers.
#
# Plateau confirmed: all 18 distinct (r, c) pairs in the 2026-05-22
# data hit 25-32k throughput with success_rate=1.0. Adding more probe
# rounds would tighten the variance band but not move the peak. So
# this gets baked in as a constant — autotune button on loopback just
# materializes this without probing.
_LOOPBACK_HARDCODED_TUNING: dict[str, int] = {
    "chunk_robot_count": 2,
    "batch_concurrency": 16,
}


def _auto_grid_for_endpoint(endpoint_url: str) -> dict[str, list[int]]:
    """Convenience wrapper: classify then return the preset grid.

    NOTE: loopback endpoints do not use a probe grid; the autotune
    endpoint short-circuits and persists ``_LOOPBACK_HARDCODED_TUNING``
    directly. This function returns the LAN preset as a defensive
    fallback in case a non-autotune caller asks for the loopback grid
    (none today), so behavior degrades gracefully instead of KeyError.
    """
    kind = _classify_endpoint_kind(endpoint_url)
    if kind == "loopback":
        return _AUTO_GRIDS["lan"]
    return _AUTO_GRIDS[kind]


def _load_server_tuning(server_id: str, settings_path: Path) -> dict[str, Any]:
    """Return the persisted autotune result for ``server_id``, or an
    empty dict if no tuning has been saved (yet). Reads through
    ``_load_settings`` so the on-disk schema validation applies."""
    if not server_id:
        return {}
    settings = _load_settings(settings_path)
    return dict((settings.get("server_tuning") or {}).get(server_id) or {})


def _save_server_tuning(
    settings_path: Path,
    server_id: str,
    chunk_robot_count: int,
    batch_concurrency: int,
    *,
    endpoint_kind: str = "",
    probe: dict[str, Any] | None = None,
) -> None:
    """Persist autotune result against ``server_id``. Merges into the
    existing settings.json without clobbering unrelated fields."""
    if not server_id:
        return
    current = _load_settings(settings_path)
    server_tuning = dict(current.get("server_tuning") or {})
    server_tuning[server_id] = {
        "chunk_robot_count": int(chunk_robot_count),
        "batch_concurrency": int(batch_concurrency),
        "tuned_at": utc_now(),
        "endpoint_kind": endpoint_kind,
        "probe": dict(probe or {}),
    }
    current["server_tuning"] = server_tuning
    _save_settings(settings_path, current)


def _save_settings(settings_path: Path, data: dict[str, Any]) -> None:
    # Phase 1 deploy: unified atomic writer adds per-file lock so
    # concurrent settings POSTs serialize. Previously already atomic
    # (tmp + os.replace) but racing concurrent writers could clobber
    # each other; the per-file lock makes the outcome deterministic.
    atomic_json_write(settings_path, data)


def _peek_envelope_scalars(path: Path) -> dict[str, Any] | None:
    """Extract only the envelope's top-level scalar fields without
    fully parsing the (potentially 70MB+) ``response`` array.

    Chunks are written as ``{..., "response": [...]}`` with the scalar
    fields preceding ``response``. Reading the first ~2 KB of the file
    and regex-matching the fields we care about (_spin_times,
    _config_md5, _code_md5) turns a 5-10 second full-parse into a
    sub-millisecond read. Falls back to full parse only on mismatch.

    Returns None on read / parse failure so caller can treat the chunk
    as unreadable (stale) rather than crashing the whole classification.
    """
    try:
        with path.open("rb") as f:
            head = f.read(4096)
    except OSError:
        return None
    try:
        text = head.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return None
    # Simple regex extraction — envelope JSON is not adversarial and
    # the scalars we want are simple quoted/integer values.
    import re as _re
    def _grab_str(key: str) -> str:
        m = _re.search(r'"' + _re.escape(key) + r'"\s*:\s*"([^"]*)"', text)
        return m.group(1) if m else ""
    def _grab_int(key: str) -> int | None:
        m = _re.search(r'"' + _re.escape(key) + r'"\s*:\s*(-?\d+)', text)
        return int(m.group(1)) if m else None
    spin_times = _grab_int("_spin_times")
    robot_count = _grab_int("_robot_count")
    cfg = _grab_str("_config_md5")
    code = _grab_str("_code_md5")
    if spin_times is None and not cfg and not code:
        # Envelope may not fit in first 4KB (unusual) — caller can
        # fall back to full parse.
        return None
    return {"_spin_times": spin_times or 0,
            "_robot_count": robot_count or 0,
            "_config_md5": cfg, "_code_md5": code}


def _classify_chunks(
    machine: str,
    mode: int,
    rawdata_root: Path,
    machines_config: Path,
    min_retention_spins: int,
) -> dict[str, Any]:
    """Partition chunks of (machine, mode) into kept / deletable /
    historical. Classification is **not** a deletion decision — it's
    a tag for display + analyzer filtering. See ``_auto_cleanup_for_space``
    for the actual eviction policy (mtime-based across deletable +
    historical, locked pairs skipped).

    * **historical** — envelope ``_config_md5`` / ``_code_md5`` differ
      from the current machines.json values (server-side machine
      updated since sampling). Analyzer ignores these when generating
      the "current md5" report, but the chunks themselves stay on
      disk until a cache-management action (disk-pressure cleanup,
      manual 一键清理, per-mode 清理, or the new per-version delete
      button) removes them. md5 drift alone never triggers auto-delete
      — see the 2026-04-20 M1|1 incident memory.
    * **kept** — md5 matches current upstream AND first chunks in
      ``chunk_index`` order whose cumulative ``_spin_times`` reaches
      ``min_retention_spins`` (inclusive of the chunk that crosses
      the threshold). Baseline protection; the retention quota applies
      ONLY to current-md5 chunks (historical md5 chunks are not
      "保底" — user 2026-04-21).
    * **deletable** — md5 matches current upstream AND above the
      retention quota. Eligible for cleanup.

    If total current-md5 spins < min_retention_spins, every current-md5
    chunk is kept (quota not reached). Historical chunks are always
    classified as historical regardless of quota.

    Returns ``{kept, deletable, historical, kept_spins, deletable_spins,
    historical_spins, upstream_config_md5, upstream_code_md5}`` where
    each group is a list of dicts ``{path, spins, mtime, config_md5,
    code_md5}``.

    ── Consumer enumeration (brief §3 C1) ──────────────────────────────

    Every caller's semantics are documented here so reviewers can verify
    that historical chunks are never silently auto-deleted or passed to
    the analyzer without explicit operator intent (per memory
    ``feedback_md5_is_a_tag_not_a_destruction_signal.md``).

    **Display-only consumers** (read all three buckets; NO deletion,
    NO analyzer input):

    * ``_build_rawdata_overview`` (~line 2087) — walks every (machine,
      mode), reads kept/deletable/historical byte counts + chunk counts
      to build the rawdata overview panel. Purely aggregates numbers for
      the UI; does not pass any chunks to the analyzer or delete
      anything.

    * ``get_rawdata_status`` endpoint (~line 5971, ``GET
      /api/rawdata/{machine}``) — reads all three buckets, groups chunks
      by (config_md5, code_md5) into ``versions`` for the per-mode
      rawdata panel. All three buckets contribute to the display
      breakdown (kept_chunks, deletable_chunks, historical_chunks in
      ``status["classified"]``). No deletion; no analyzer input.

    **Deletion consumers** (use deletable + historical for mtime-based
    eviction; NEVER delete kept; historical deletion is always
    explicitly-triggered, not md5-drift-triggered):

    * ``delete_rawdata`` (~line 1133, triggered by manual 一键清理 /
      per-mode 清理 button or ``POST /api/cache/cleanup``) — merges
      ``cls["deletable"] + cls["historical"]`` into the eviction pool,
      unlinks in mtime order until disk target or the list is exhausted.
      Locked (machine, mode) pairs and in-use pairs are skipped entirely.
      ``cls["kept"]`` is never touched. historical chunks are eligible
      because they have no retention protection (user 2026-04-21: "保底
      only applies to current md5").
      **Force-flag bypass note (P1-A4 R4)**: when the caller passes
      ``force=True`` the function takes the ``shutil.rmtree`` path
      (whole mode directory) — `_classify_chunks` is NOT consulted at
      all. The force path is operator-explicit and removes the entire
      (machine, mode) tree including all three buckets.

    * ``_auto_cleanup_for_space`` (~line 2617, disk-pressure auto-evict)
      — same pool logic: ``deletable + historical``, mtime-sorted
      oldest-first, stops at free-space target. Locked + in-use (machine,
      mode) pairs skipped. This function is the ONLY place where
      historical chunks can be deleted automatically (not by md5 drift —
      by disk pressure). See 2026-04-20 M1|1 incident.

    * ``_enumerate_rawdata_deletable`` (~line 8766, candidate collector
      shared by the background auto-cleanup scheduler) — walks rd_root,
      calls this function per (machine, mode), appends every entry in
      ``cls["deletable"] + cls["historical"]`` to the returned candidate
      list, sorted by mtime. Used by the periodic cleanup task that calls
      ``_auto_cleanup_for_space``. Same lock + in-use guards as above.

    **Analyzer-input consumers** (use kept + deletable; historical ONLY
    when explicitly md5-filtered by the operator):

    * ``_run_generate_report`` (~line 6789, in-process analyzer replay;
      inject site for the filter check is at ~line 6845) — default
      path (no md5 filter): uses ``classified["kept"] +
      classified["deletable"]`` only. Historical chunks are NEVER
      passed to the analyzer in this path. md5-filter path (operator
      requests a historical-md5 cell via config_md5 + code_md5 query
      params): merges all three buckets then filters to the exact md5
      pair — effectively turns an explicitly-chosen historical bucket
      into analyzer input. This is intentional and safe because the
      operator explicitly named the version.

    * ``_prepare_batch_gen_item`` (~line 7136, batch-generate parent
      thread) — Python-level filter computes ``usable =
      classified["kept"] + classified["deletable"]`` for **bookkeeping
      / quota math only**. The actual analyzer subprocess input is the
      raw ``chunk_dir`` (mode directory) passed to the batch worker
      (``scripts/_batch_gen_worker.py``) as ``--from-cache <chunk_dir>``.
      The worker does NOT forward ``--upstream-config-md5`` /
      ``--upstream-code-md5`` filter args today, so the analyzer
      subprocess defaults to "no filter" and reads ALL
      ``chunk_*.json`` in the directory — INCLUDING historical chunks.
      **The Python ``usable`` filter does NOT propagate to the
      subprocess.** This is the P1-A4 round-2 critic finding (R1) and
      a known prod issue requiring a separate fix ticket (TODO: open
      ticket to forward md5 filter args from `_prepare_batch_gen_item`
      → `_batch_gen_worker.py` → analyzer CLI). The regression test in
      ``tests/backend/test_classify_chunks_historical_consumers.py``
      includes an xfail-marked test that asserts the future-correct
      behavior; flip to non-xfail when the bug is fixed.

    **Out-of-scope non-consumer** (per-version DELETE endpoint):

    * ``DELETE /api/rawdata/{machine}/mode/{mode}/version`` (~line
      6042-6162) — does NOT call ``_classify_chunks``. It iterates raw
      chunk files directly and matches by (config_md5, code_md5) in the
      request body. Included here for completeness: this is the surgical
      per-version delete path; classification buckets are irrelevant
      because the target version is specified explicitly.

    ── Safety invariant ────────────────────────────────────────────────

    Historical bucket is NEVER auto-deleted by md5 drift alone. Deletion
    always goes through ``_auto_cleanup_for_space`` (disk pressure,
    explicit 一键清理) or the per-version DELETE endpoint (operator
    names the exact version). The md5 mismatch flag is a display tag
    only — it does NOT trigger unlink. This was broken before 2026-04-20
    via ``check_rawdata_status(auto_delete_mismatched=True)``; that
    parameter has been removed. ``check_rawdata_status`` is now
    read-only and does not accept any ``auto_delete_*`` argument.
    """
    mode_dir = rawdata_root / machine / f"mode_{mode}"
    empty = {
        "kept": [], "deletable": [], "historical": [],
        "kept_spins": 0, "deletable_spins": 0, "historical_spins": 0,
        "upstream_config_md5": "", "upstream_code_md5": "",
    }
    if not mode_dir.is_dir():
        return empty
    up_config, up_code = _get_machine_md5(machine, machines_config, mode=mode)
    empty["upstream_config_md5"] = up_config
    empty["upstream_code_md5"] = up_code
    unverifiable = not up_config and not up_code
    # Current md5 set — the server pair PLUS any local-cfg pair whose
    # file still exists on disk with matching content. A chunk that
    # matches ANY pair in this set is "current" (different reference,
    # same semantics: still valid for baseline retention). See
    # ``_current_md5_pairs`` for the shape + labels.
    current_pairs = _current_md5_pairs(machine, machines_config, mode=mode)
    current_set = {
        (p["cfg_md5"], p["code_md5"])
        for p in current_pairs
        if p["cfg_md5"] or p["code_md5"]
    }
    # Sort by chunk_index (filename order) so "kept" walks from oldest
    # baseline forward — deterministic regardless of mtime jitter.
    chunks = sorted(mode_dir.glob("chunk_*.json"))
    if not chunks:
        return empty

    kept: list[dict[str, Any]] = []
    deletable: list[dict[str, Any]] = []
    historical: list[dict[str, Any]] = []
    kept_spins = 0
    deletable_spins = 0
    historical_spins = 0

    # Pre-load the per-mode chunk metadata sidecar once (auto-rebuilds
    # on first access via peek — see ``fresh_slotlab.chunk_index``).
    # Virtual console uses the same helper because virtual_app passes
    # ``rawdata_root=VIRTUAL_RAWDATA_ROOT`` through to this function —
    # one codepath, two rawdata trees. Before 2026-04-24 this loop
    # opened every chunk file via ``_peek_envelope_scalars`` per
    # request (4 KB × N chunks); now 0 file reads when the sidecar
    # covers every chunk.
    try:
        from fresh_slotlab.chunk_index import get_chunks_index
        sidecar_entries = get_chunks_index(mode_dir).get("chunks") or {}
    except Exception:  # noqa: BLE001
        sidecar_entries = {}

    for p in chunks:
        entry_data = sidecar_entries.get(p.name)
        if isinstance(entry_data, dict):
            cfg = str(entry_data.get("cfg_md5", "") or "")
            code = str(entry_data.get("code_md5", "") or "")
            per_robot_spins = int(entry_data.get("spin_times", 0) or 0)
            robots = int(entry_data.get("robot_count", 0) or 0) or 1
        else:
            # Sidecar miss (chunk not yet indexed, rebuild failed).
            # Fall back to the per-file 4 KB peek, then to full
            # ``json.loads`` for truly legacy envelopes.
            data = _peek_envelope_scalars(p)
            if data is None:
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    historical.append({
                        "path": str(p), "spins": 0,
                        "mtime": p.stat().st_mtime if p.exists() else 0,
                        "config_md5": "", "code_md5": "",
                    })
                    continue
            cfg = str(data.get("_config_md5", ""))
            code = str(data.get("_code_md5", ""))
            per_robot_spins = int(data.get("_spin_times") or 0)
            robots = int(data.get("_robot_count") or 0) or 1

        # _spin_times is the PER-ROBOT spin count in this chunk — actual
        # chunk spins = _spin_times × _robot_count. Older UI used the
        # per-robot value and under-reported 27× on M273 (robots=27).
        spins = per_robot_spins * robots
        mtime = p.stat().st_mtime
        md5_ok = unverifiable or ((cfg, code) in current_set and (cfg or code))
        entry = {"path": str(p), "spins": spins, "mtime": mtime,
                 "config_md5": cfg, "code_md5": code}
        if not md5_ok:
            # Historical md5 — not a deletion signal, just a tag.
            # Retention baseline ONLY applies to current md5, so these
            # never contribute to `kept_spins`.
            historical.append(entry)
            historical_spins += spins
            continue
        # md5 valid: fill kept quota first, then deletable
        if kept_spins < min_retention_spins:
            kept.append(entry)
            kept_spins += spins
        else:
            deletable.append(entry)
            deletable_spins += spins

    return {
        "kept": kept, "deletable": deletable, "historical": historical,
        "kept_spins": kept_spins, "deletable_spins": deletable_spins,
        "historical_spins": historical_spins,
        "upstream_config_md5": up_config, "upstream_code_md5": up_code,
        # Multi-current set: the server pair PLUS any local-cfg pair
        # whose file is on disk right now. UI uses this to badge each
        # md5 bucket as "当前(服务端)" / "当前(本地 cfg)" / "历史".
        "current_md5_pairs": current_pairs,
    }


def _tag_reports_stale(
    machine: str,
    mode: int,
    reports_root: Path,
    store: "StateStore",
    state_dir: Path,
) -> None:
    """Phase 3 (D9): tag all reports for (machine, mode) as stale.

    Sets ``underlying_removed=True`` on every entry in the per-mode
    report index.json and ``underlying_removed=1`` in the SQLite
    ``runs`` table.

    Per memory/feedback_md5_is_a_tag_not_a_destruction_signal.md:
    this is purely observability tagging — no reports are deleted.

    Per memory/feedback_no_silent_swallow.md:
    * Persists diagnostic to ``state_dir/stale_tag_error.json`` on failure.
    * Re-raises so callers can detect and handle the failure
      (typically: log, but don't block the delete that already succeeded).

    INV-7 v2 carve-out: ``DELETE /api/machines/{machine}/all-data``
    is EXEMPT from this call because it deletes both rawdata + reports
    entirely; reports don't survive to need stale-tagging.
    """
    index_path = reports_root / machine / f"mode_{mode}" / "index.json"
    try:
        if index_path.exists():
            def _mark_stale(data: Any) -> Any:
                if isinstance(data, list):
                    for entry in data:
                        if isinstance(entry, dict):
                            entry["underlying_removed"] = True
                return data
            atomic_json_read_modify_write(index_path, _mark_stale)
        store.mark_runs_underlying_removed(machine, mode)
    except Exception as exc:
        # Persist diagnostic per memory/feedback_no_silent_swallow.md.
        diag_path = state_dir / "stale_tag_error.json"
        diag = {
            "machine": machine,
            "mode": mode,
            "error": f"{exc.__class__.__name__}: {exc}",
            "ts": utc_now(),
        }
        try:
            atomic_json_write(diag_path, diag)
        except Exception:
            pass  # Last-resort: don't let log-write swallow original exc.
        import traceback as _tb
        _tb.print_exc()
        raise  # Re-raise so caller can surface the failure.


def delete_rawdata(
    machine: str,
    mode: int | None = None,
    rawdata_root: Path | None = None,
    machines_config: Path | None = None,
    min_retention_spins: int = _RAWDATA_MIN_RETENTION_SPINS_DEFAULT,
    force: bool = False,
) -> dict[str, Any]:
    """Delete rawdata for a machine / mode, respecting the retention
    quota by default.

    * ``force=False`` (default, operator-safe) — delete only
      ``deletable`` + ``historical`` chunks; the ``kept`` quota
      survives so baseline samples aren't silently wiped. Retention
      protects ONLY current-md5 chunks (historical md5 has no
      retention — same semantic rule as the classifier).
    * ``force=True`` — nuke everything at the target path (legacy
      behavior; matches the pre-quota ``shutil.rmtree``). UI exposes
      this under a separate "完全删除" button with confirmation.

    ``mode=None`` applies the same semantics to every mode under the
    machine. The rawdata index is updated per affected mode so the UI
    reflects the deletion on the next read.
    """
    root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT
    mc = machines_config if machines_config is not None else MACHINES_CONFIG
    if not (root / machine).is_dir():
        return {"ok": True, "deleted": False, "reason": "not_found",
                "deleted_chunks": 0, "kept_chunks": 0}

    if force:
        # Legacy nuclear path: delete everything under the target dir.
        target = root / machine if mode is None else root / machine / f"mode_{mode}"
        if not target.is_dir():
            return {"ok": True, "deleted": False, "reason": "not_found",
                    "deleted_chunks": 0, "kept_chunks": 0}
        shutil.rmtree(target, ignore_errors=True)
        try:
            from fresh_slotlab.rawdata_index import remove_entry, load_index, _save_index
            if mode is not None:
                remove_entry(root, machine, mode)
            else:
                data = load_index(root)
                data["entries"] = {
                    k: v for k, v in data["entries"].items()
                    if not k.startswith(f"{machine}|")
                }
                _save_index(root, data)
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "deleted": True, "forced": True,
                "path": str(target), "deleted_chunks": -1,
                "kept_chunks": 0}

    # Default path: classifier-driven tiered delete
    if mode is None:
        modes = []
        for md in sorted((root / machine).iterdir()):
            if md.is_dir() and md.name.startswith("mode_"):
                try:
                    modes.append(int(md.name.split("_", 1)[1]))
                except (IndexError, ValueError):
                    continue
    else:
        modes = [mode]

    # Operator-lock carve-out: in non-force mode, locked (machine, mode)
    # pairs are preserved even against a user-initiated "清理" button.
    # Rationale: the lock is the operator's explicit "这个别动" signal;
    # the tiered-delete button is normally the auto-cleanup equivalent
    # the user can trigger manually, so it should honor the same
    # carve-outs. Force mode (the "完全删除" button) skips this
    # entirely — that's the "I know what I'm doing" escape hatch.
    try:
        _locks = _load_rawdata_locks(_rawdata_locks_path(mc))
    except Exception:  # noqa: BLE001
        _locks = set()

    deleted_chunks = 0
    kept_chunks = 0
    skipped_locked_modes: list[int] = []
    total_deletable_bytes = 0
    for m in modes:
        if (machine, int(m)) in _locks:
            # Surface as "kept" + record skipped mode so the UI can
            # explain why nothing happened for these.
            skipped_locked_modes.append(int(m))
            # Count the locked chunks against kept_chunks so the
            # response still reflects the on-disk reality.
            mode_dir = root / machine / f"mode_{m}"
            if mode_dir.is_dir():
                kept_chunks += sum(1 for _ in mode_dir.glob("chunk_*.json"))
            continue
        cls = _classify_chunks(machine, m, root, mc, min_retention_spins)
        kept_chunks += len(cls["kept"])
        # Track the chunk filenames we actually unlinked so we can
        # batch-update the per-mode sidecar (`_chunks.json`) in one
        # write instead of N. Without this the sidecar's mtime stays
        # behind the dir's mtime → every subsequent read triggers a
        # full glob+peek rebuild.
        unlinked_names: list[str] = []
        for entry in cls["deletable"] + cls["historical"]:
            try:
                p = Path(entry["path"])
                if p.exists():
                    total_deletable_bytes += p.stat().st_size
                    p.unlink()
                    deleted_chunks += 1
                    unlinked_names.append(p.name)
            except OSError:
                pass
        # Rescan index entry so the UI status reflects the deletion
        # immediately rather than on next read's cold-path scan.
        try:
            from fresh_slotlab.rawdata_index import update_entry, remove_entry
            from fresh_slotlab.chunk_index import bulk_remove_chunk_entries
            mode_dir = root / machine / f"mode_{m}"
            # Drop the just-deleted chunks from the per-mode sidecar
            # FIRST so the next index read trusts the sidecar instead
            # of falling through to a rebuild (the rebuild itself is
            # cheap but the trust path is cheaper still).
            if unlinked_names:
                bulk_remove_chunk_entries(mode_dir, unlinked_names)
            if mode_dir.is_dir() and any(mode_dir.glob("chunk_*.json")):
                update_entry(root, machine, m, mode_dir)
            else:
                remove_entry(root, machine, m)
        except Exception:  # noqa: BLE001
            pass

    return {
        "ok": True, "deleted": deleted_chunks > 0, "forced": False,
        "deleted_chunks": deleted_chunks,
        "kept_chunks": kept_chunks,
        "deleted_bytes": total_deletable_bytes,
        "skipped_locked_modes": skipped_locked_modes,
    }


def _detect_machine_cycle(machine: str, reports_root: Path) -> dict[str, Any]:
    """Inspect the newest report of a machine and infer cycle_spin_times.

    Returns:
      {"detected": bool, "cycle_length": int | None, "source": str, "recommended_chunk_size": int}
    """
    machine_dir = reports_root / machine
    if not machine_dir.is_dir():
        return {"detected": False, "cycle_length": None, "source": "no_report",
                "recommended_chunk_size": 1000}

    # Find newest report across all modes.
    newest: Path | None = None
    newest_mtime = 0.0
    for mode_dir in machine_dir.iterdir():
        versions = mode_dir / "versions"
        if not versions.is_dir():
            continue
        for v in versions.iterdir():
            sf = v / "player_impact_summary.json"
            if sf.exists():
                mtime = sf.stat().st_mtime
                if mtime > newest_mtime:
                    newest_mtime = mtime
                    newest = sf

    if newest is None:
        return {"detected": False, "cycle_length": None, "source": "no_summary",
                "recommended_chunk_size": 1000}

    try:
        s = json.loads(newest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"detected": False, "cycle_length": None, "source": "parse_failed",
                "recommended_chunk_size": 1000}

    pi = s.get("player_impact", {}) or {}
    collect = pi.get("collect", {}) or {}
    cycle_peaks = collect.get("cycle_peaks") or []
    bcd = pi.get("bonus_chain_dynamics", {}) or {}

    if cycle_peaks:
        cycle = max(int(x) for x in cycle_peaks if x)
        return {"detected": True, "cycle_length": cycle, "source": "cycle_peaks",
                "recommended_chunk_size": max(cycle * 2, 1000)}

    # Collect mechanic applicable but no cycle peaks recorded → sampling was too short.
    if collect.get("applicable") or bcd.get("applicable"):
        return {"detected": False, "cycle_length": None, "source": "collect_detected_no_cycle",
                "recommended_chunk_size": 10000}

    return {"detected": True, "cycle_length": None, "source": "no_cycle_mechanic",
            "recommended_chunk_size": 1000}


def _get_disk_space_info(path: Path) -> dict[str, int]:
    """Return free/total disk space in GB for the given path."""
    try:
        usage = shutil.disk_usage(str(path))
        return {
            "free_gb": round(usage.free / (1024**3), 1),
            "total_gb": round(usage.total / (1024**3), 1),
            "used_gb": round(usage.used / (1024**3), 1),
        }
    except OSError:
        return {"free_gb": 0, "total_gb": 0, "used_gb": 0}


def _fetch_machine_config_md5(endpoint: str, timeout: float = 30.0) -> dict[str, Any] | None:
    """Call MachineConfigMd5 on a server and return the parsed response."""
    url = f"{endpoint.rstrip('/')}/MachineTest/MachineConfigMd5"
    req = urllib.request.Request(url, method="POST",
                                headers={"Content-Type": "application/json"},
                                data=b"{}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body)
    except Exception:
        return None


def _save_server_snapshot(server_id: str, data: dict[str, Any]) -> Path:
    """Save a MachineConfigMd5 snapshot for a server."""
    snap_dir = ROOT / ".probe" / "server_snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    out_path = snap_dir / f"{server_id}.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def _load_server_snapshot(server_id: str) -> dict[str, Any] | None:
    snap_path = ROOT / ".probe" / "server_snapshots" / f"{server_id}.json"
    if snap_path.exists():
        return read_json(snap_path)
    return None


def _compare_snapshots(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare two MachineConfigMd5 snapshots. Returns list of diffs."""
    diffs = []
    all_keys = sorted(set(list(a.keys()) + list(b.keys())),
                      key=lambda k: int(k[1:]) if k[1:].isdigit() else 0)
    for key in all_keys:
        ma = a.get(key)
        mb = b.get(key)
        if ma is None:
            diffs.append({"machine": key, "status": "only_in_b"})
        elif mb is None:
            diffs.append({"machine": key, "status": "only_in_a"})
        else:
            config_a = ma.get("configSummaryMd5", "")
            config_b = mb.get("configSummaryMd5", "")
            code_a = ma.get("codeSummaryMd5", "")
            code_b = mb.get("codeSummaryMd5", "")
            if config_a != config_b or code_a != code_b:
                diffs.append({
                    "machine": key,
                    "status": "changed",
                    "config_changed": config_a != config_b,
                    "code_changed": code_a != code_b,
                    "config_a": config_a, "config_b": config_b,
                    "code_a": code_a, "code_b": code_b,
                })
    return diffs


def _resolve_active_server_id(
    path: Path | None = None,
    settings_path: Path | None = None,
) -> str:
    """Pick which server sampling should hit when the caller didn't
    specify one. Priority:
      1. ``default_server`` from state/console/settings.json (operator
         override via PUT /api/servers/{id}/set-default) — kept here
         instead of in tracked configs/servers.json so flipping does
         not produce git merge conflicts on next pull.
      2. ``default_server`` shipped in configs/servers.json (the
         initial / fallback default — usually only set when the file
         is first authored).
      3. First entry with ``active=true`` AND non-empty endpoint.
      4. "" — sampler falls back to SLOT_SPIN_ENDPOINT hardcoded.

    Each level still requires the picked server to (a) exist in the
    servers list and (b) carry a non-empty endpoint, otherwise it
    falls through. That way a stale operator override pointing at a
    deleted/renamed server silently drops to the next tier instead of
    blowing up.

    Keeps the UI in control: flipping ``active`` via the 服务器管理 UI
    or setting a new default via the resolver endpoint is enough to
    reroute batch-run without a backend restart or a code edit.
    """
    cfg = load_servers(path)
    entries = cfg.get("servers") or []
    by_id = {s.get("id"): s for s in entries if isinstance(s, dict)}

    sp = settings_path if settings_path is not None else SETTINGS_PATH
    operator_pref = _load_settings(sp).get("default_server", "")
    if operator_pref and isinstance(by_id.get(operator_pref), dict):
        ep = (by_id[operator_pref].get("endpoint") or "").strip()
        if ep:
            return operator_pref

    shipped = cfg.get("default_server")
    if shipped and isinstance(by_id.get(shipped), dict):
        ep = (by_id[shipped].get("endpoint") or "").strip()
        if ep:
            return shipped

    for s in entries:
        if s.get("active") and (s.get("endpoint") or "").strip():
            return s.get("id") or ""
    return ""


def get_server_endpoint(server_id: str, path: Path | None = None) -> str:
    """Resolve the sampling API endpoint URL for a server."""
    cfg = load_servers(path)
    for s in cfg.get("servers", []):
        if s.get("id") == server_id:
            ep = s.get("endpoint", "").rstrip("/")
            if ep:
                return f"{ep}/MachineTest/MultiRobotTestSpinVariant"
    return SLOT_SPIN_ENDPOINT


class BatchRunItem(BaseModel):
    machine: str
    mode: int
    chunk_spin_times: int | None = None  # per-item override
    # Per-item MachineConfig JSON string. Only meaningful when the
    # batch has a single item (focused-machine flow). Frontend will
    # never populate this for multi-select batches — but if it ever
    # does, the analyzer subprocess for that item still applies only
    # to that item's sampling, so batch_concurrency doesn't cross-pollute.
    machine_config: str | None = None
    # Server-side shortcut: when True, backend reads
    # ``machineconfig/<underlying>Cfg.txt`` (resolved via variants_map)
    # at batch-submit time and uses its content as machine_config.
    # Lets the UI show a simple "use local cfg" checkbox without
    # uploading the file on every submit. Ignored when machine_config
    # is already explicitly set (explicit beats inferred).
    use_local_machine_config: bool = False


class BatchRunRequest(BaseModel):
    items: list[BatchRunItem]
    concurrency: int = Field(default=3, ge=1, le=10)
    # Optional server selection. Empty string → backend picks from
    # configs/servers.json (default_server → first active with a
    # non-empty endpoint). Lets operators flip endpoints via the
    # 服务器管理 UI without touching the SLOT_SPIN_ENDPOINT constant.
    server_id: str = Field(default="")
    # 2026-05-22: defaults aligned with RunCreateRequest (see that
    # class for the rationale of each value). chunk_spin_times floor
    # lifted to 10000 per operator request; timeout dropped to 60s
    # matching the loopback p95 measurement.
    chunk_spin_times: int = Field(default=10000, gt=0)
    chunk_robot_count: int = Field(default=8, gt=0)
    batch_concurrency: int = Field(default=8, gt=0)
    max_chunks: int = Field(default=120, gt=0)
    timeout: float = Field(default=60.0, gt=0)
    target_halfwidth_pp: float = Field(default=0.5, ge=0)
    auto_cleanup_cache: bool = Field(default=True)
    # Sampling strategy for count-based runs:
    #   "total"       — max_chunks is the TOTAL target; if cache
    #                   already has ≥max_chunks, analyzer's from-cache
    #                   resume skips new sampling (current default
    #                   behavior — safe)
    #   "incremental" — max_chunks is the ADDITIONAL delta beyond
    #                   existing cache; backend reads per-item cache
    #                   size and adjusts effective max_chunks to
    #                   (existing + requested). Useful when operator
    #                   wants to "add another 10k spins on top of
    #                   whatever is there".
    sampling_strategy: str = Field(default="total")
    # Auto-refresh upstream md5 before deciding cache reuse (2026-04-21).
    # Default True — operator expects "开始采样" to grab the freshest
    # upstream md5 so chunks cached against an old config don't get
    # silently reused. Set to False when you know local md5 is already
    # current or want to skip the round-trip.
    skip_md5_refresh: bool = Field(default=False)


class AutoTuneRequest(BaseModel):
    machine: str
    mode: int
    # 200 outer spins per robot per probe — big enough that the
    # per-request signal is not RTT-dominated (single chunk ~0.5-1s
    # against the current external endpoint at r=8) but small enough
    # that the full grid still finishes in 1-2 min. Was 120; bumped
    # 2026-04-25 because at the new sub-100ms RTT floor, 120 spins
    # made probe latency variance dwarf the throughput signal.
    spin_times: int = Field(default=200, gt=0)
    # Default candidate grid 2026-04-25 — derived from external server
    # benchmark (M14 mode 1, 116.232.103.19:10288). Throughput peaks
    # at r=8 c=8 ≈ 9,100 outer/s; r=16 adds ~5% but doubles chunk wall
    # so retry cost rises. conc<4 strictly leaves performance unused;
    # conc>12 plateaus then falls (at conc=32 it's 7,300/s, ~80% of
    # peak). 2x3=6 candidates × 2 rounds × ~5s/wave = ~1 min full
    # autotune wall time, which the operator can stomach.
    #
    # Old grid (8/16/24 × 1/2/4) explored almost entirely the
    # left-of-peak region — the autotune routinely returned
    # ``best=24x4`` purely because it never tried higher conc.
    robot_candidates: list[int] = Field(default_factory=lambda: [8, 16])
    concurrency_candidates: list[int] = Field(default_factory=lambda: [4, 8, 12])
    # When True (or when both ``robot_candidates`` and
    # ``concurrency_candidates`` arrive empty/list-of-zero), the autotune
    # endpoint replaces the request grid with a preset sized for the
    # current server endpoint's expected throughput regime (loopback vs
    # LAN vs WAN). Frontend can either opt in by setting this True, or
    # send explicit candidates and ignore this knob. See
    # ``_auto_grid_for_endpoint`` for the actual presets and the rationale.
    use_auto_grid: bool = Field(default=False)
    rounds: int = Field(default=2, gt=0, le=8)
    # Ceiling 60s = c=12 sustained max wall (~22s) × 2 round-trip
    # safety margin. c=16 hits 30s wall, c=24 hits 49s — operators
    # who venture past the default grid get a clean Timeout signal
    # instead of an indefinite hang.
    timeout: float = Field(default=60.0, gt=0, le=180.0)
    bet: int = Field(default=1000, gt=0)


class StateStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Phase 3 (D6): queue_id to resume after crash recovery.
        # Populated by _recover_fleet_refresh if a running queue is found.
        # Consumed by create_app after FleetRefreshManager is constructed.
        self._pending_resume_queue_id: str | None = None
        self._init_db()
        # Phase 3 (D6): recover in-flight fleet refresh items after crash.
        # Must run AFTER _init_db so the tables exist. Guard with
        # OperationalError for pre-P3 databases that don't have the tables yet.
        # I3 fix: distinguish "no such table" (expected, pre-P3 DB) from
        # genuine corruption (unexpected — write diagnostic per
        # memory/feedback_no_silent_swallow.md).
        try:
            self._recover_fleet_refresh()
        except sqlite3.OperationalError as _exc:
            if "no such table" in str(_exc).lower():
                pass  # Pre-P3 database — tables don't exist yet, expected
            else:
                # Corruption or schema mismatch — persist diagnostic to disk.
                try:
                    import json as _json
                    _diag_path = self.db_path.parent / "fleet_recovery_error.json"
                    _diag_path.write_text(
                        _json.dumps({
                            "error": str(_exc),
                            "ts": utc_now(),
                        }),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
                import traceback as _tb
                _tb.print_exc()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            # Phase 1 deploy: enable WAL mode + busy_timeout so
            # concurrent reads don't block writes (and vice versa).
            # Required for <10 planners hitting the DB in parallel.
            # WAL is idempotent on repeated apply — once set it
            # persists in the .db header.
            #
            # NOTE: WAL creates .db-wal + .db-shm sidecars; the deploy
            # README documents that state/console/ MUST be on local
            # disk (NOT a network share — WAL is unsupported on SMB/CIFS).
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
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
            # Version fingerprints for run-history staleness display.
            # rawdata_config_md5 / rawdata_code_md5 = server machine
            # version at sampling time (summary.config_md5 / code_md5);
            # analyzer_version = local analyzer source hash at report
            # generation (summary.analyzer_version). All three
            # populated on run finalize + backfilled on startup.
            if "rawdata_config_md5" not in run_columns:
                conn.execute("ALTER TABLE runs ADD COLUMN rawdata_config_md5 TEXT")
            if "rawdata_code_md5" not in run_columns:
                conn.execute("ALTER TABLE runs ADD COLUMN rawdata_code_md5 TEXT")
            if "analyzer_version" not in run_columns:
                conn.execute("ALTER TABLE runs ADD COLUMN analyzer_version TEXT")
            # Run-history surfaces total_spins so the operator can see
            # sample size alongside RTP / CI (0.5pp at 10k spins vs at
            # 1M spins is very different confidence). Populated from
            # summary.sampling.total_spins.
            if "total_spins" not in run_columns:
                conn.execute("ALTER TABLE runs ADD COLUMN total_spins INTEGER")
            # Phase 3 item 6: per-(machine, mode) effective_analyzer_version
            # composed of base_hash + sorted(feature_hashes) + mode. Lives
            # alongside the legacy `analyzer_version` column — old run rows
            # carry NULL here and render as historical (per memory
            # feedback_md5_is_a_tag_not_a_destruction_signal.md: version is
            # a tag, not a destruction signal). Populated by PIA's summary
            # writer + backfilled at run finalize.
            if "effective_analyzer_version" not in run_columns:
                conn.execute(
                    "ALTER TABLE runs ADD COLUMN effective_analyzer_version TEXT"
                )
            # Phase 3 deploy (2026-05-17): flag set when the underlying rawdata
            # for a run has been deleted.  Surfaced in list_runs / report endpoints
            # so the frontend can show a "rawdata removed" badge.
            if "underlying_removed" not in run_columns:
                conn.execute(
                    "ALTER TABLE runs ADD COLUMN underlying_removed INTEGER NOT NULL DEFAULT 0"
                )
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
            # 2026-05-22 L2: batches table persists BatchRunManager state
            # across console restarts. Before this, _batches was an
            # in-memory dict — a console restart erased the batch
            # grouping (individual run records survived in the runs
            # table + A2 auto-resumed them, but the batch outer shell
            # was gone, so the A1 resume button could not work after a
            # restart). With this table, restart recovery marks
            # non-terminal batches as cancelled-by-restart and loads
            # them back so the operator can still hit the resume
            # button on yesterday's interrupted batch. params_json /
            # items_json / events_json store the full batch dict
            # contents; the manager rebuilds the in-memory state from
            # these on __init__.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    concurrency INTEGER NOT NULL DEFAULT 3,
                    params_json TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    events_json TEXT NOT NULL,
                    reports_root TEXT,
                    kind TEXT NOT NULL DEFAULT 'sampling'
                )
                """
            )
            # 2026-05-26 L3: add kind column to existing L2 batches table
            # so the unified history covers both BatchRunManager (sampling)
            # and BatchGenerateManager (generate). Existing L2 rows default
            # to 'sampling' which matches their semantics.
            batches_columns = {row[1] for row in conn.execute(
                "PRAGMA table_info(batches)"
            ).fetchall()}
            if "kind" not in batches_columns:
                conn.execute(
                    "ALTER TABLE batches ADD COLUMN kind TEXT NOT NULL DEFAULT 'sampling'"
                )
            # Phase 3 deploy (2026-05-17): fleet refresh queue tables.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fleet_refresh_queue (
                    queue_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_items INTEGER NOT NULL,
                    completed_items INTEGER NOT NULL DEFAULT 0,
                    failed_items INTEGER NOT NULL DEFAULT 0,
                    skipped_items INTEGER NOT NULL DEFAULT 0,
                    config_source TEXT NOT NULL DEFAULT 'server_default',
                    server_id TEXT,
                    cancelled_at TEXT,
                    finished_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fleet_refresh_items (
                    queue_id TEXT NOT NULL REFERENCES fleet_refresh_queue(queue_id),
                    machine TEXT NOT NULL,
                    mode INTEGER NOT NULL,
                    queue_position INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    run_id TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    PRIMARY KEY (queue_id, machine, mode)
                )
                """
            )
            # Phase 3 deploy (2026-05-17): crash-recovery anchor for config_id
            # sidecar annotation. Written before a sampling run starts;
            # cleared after the sidecar is updated. On startup, orphaned rows
            # trigger re-association of chunks with their config_id.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_batch_configs (
                    batch_run_id TEXT NOT NULL,
                    machine TEXT NOT NULL,
                    mode INTEGER NOT NULL,
                    config_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (batch_run_id, machine, mode)
                )
                """
            )
            # Phase 4 (auto-inspect): sweep + item tables.  Idempotent
            # CREATE IF NOT EXISTS — safe on every startup, no ALTER needed.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auto_inspect_sweeps (
                    sweep_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    settings_snapshot_json TEXT NOT NULL,
                    modes_json TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    total_items INTEGER NOT NULL DEFAULT 0,
                    completed_items INTEGER NOT NULL DEFAULT 0,
                    failed_items INTEGER NOT NULL DEFAULT 0,
                    skipped_items INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auto_inspect_items (
                    sweep_id TEXT NOT NULL REFERENCES auto_inspect_sweeps(sweep_id),
                    machine TEXT NOT NULL,
                    mode INTEGER NOT NULL,
                    queue_position INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    cell_class TEXT NOT NULL,
                    sample_run_id TEXT,
                    generate_run_id TEXT,
                    generate_status TEXT,
                    cfg_md5_at_enqueue TEXT NOT NULL DEFAULT '',
                    code_md5_at_enqueue TEXT NOT NULL DEFAULT '',
                    claimed_by TEXT,
                    claimed_at TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    terminal_reason TEXT,
                    events_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY (sweep_id, machine, mode)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_auto_inspect_items_status
                    ON auto_inspect_items (sweep_id, status)
                """
            )
            conn.commit()

    def _recover_fleet_refresh(self) -> None:
        """Phase 3 (D6): re-queue any in-flight items from a crashed queue.

        Called during StateStore.__init__ AFTER _init_db.  If a
        ``fleet_refresh_queue`` row with ``status='running'`` exists,
        any of its items that are also ``status='running'`` crashed mid-run
        (the daemon thread died with the process).  Reset them to
        ``status='pending'`` so the next ``run_queue`` pass picks them up.

        Sets ``self._pending_resume_queue_id`` so ``create_app`` can
        resume the queue via FleetRefreshManager.run_queue() after it
        constructs the manager.

        Raises ``sqlite3.OperationalError`` if the tables don't exist
        yet (pre-P3 database); caller swallows it.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT queue_id FROM fleet_refresh_queue "
                "WHERE status='running' LIMIT 1"
            ).fetchone()
            if row:
                queue_id = str(row["queue_id"])
                # Re-queue in-flight items (they crashed mid-fetch).
                conn.execute(
                    "UPDATE fleet_refresh_items SET status='pending', run_id=NULL "
                    "WHERE queue_id=? AND status='running'",
                    (queue_id,),
                )
                conn.commit()
                # Signal create_app to resume this queue.
                self._pending_resume_queue_id = queue_id

    # ── Phase 3 (D10): underlying_removed ────────────────────────────

    def mark_runs_underlying_removed(self, machine: str, mode: int) -> int:
        """Set ``underlying_removed=1`` on every run row matching
        ``(machine, mode)``.  Called after rawdata deletion so the UI can
        show a "underlying rawdata removed" badge on historical reports.

        Returns the number of rows updated.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE runs SET underlying_removed=1 "
                "WHERE machine=? AND mode=?",
                (str(machine), int(mode)),
            )
            conn.commit()
            return cur.rowcount

    # ── Phase 3 (D2): pending_batch_configs ──────────────────────────

    def insert_pending_batch_config(
        self,
        batch_run_id: str,
        machine: str,
        mode: int,
        config_id: str,
    ) -> None:
        """Write-config-first ordering anchor (R8 / D2).

        Called BEFORE the analyzer subprocess starts sampling so that a
        crash between subprocess start and sidecar update can be detected
        and re-associated on next startup.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO pending_batch_configs "
                "(batch_run_id, machine, mode, config_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (batch_run_id, str(machine), int(mode), str(config_id), utc_now()),
            )
            conn.commit()

    def delete_pending_batch_config(
        self,
        batch_run_id: str,
        machine: str,
        mode: int,
    ) -> None:
        """Remove the anchor after the sidecar is updated (D2)."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM pending_batch_configs "
                "WHERE batch_run_id=? AND machine=? AND mode=?",
                (batch_run_id, str(machine), int(mode)),
            )
            conn.commit()

    def list_pending_batch_configs(self) -> list[dict[str, Any]]:
        """Return all pending_batch_configs rows for startup re-association."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_batch_configs ORDER BY created_at ASC"
            ).fetchall()
        return [dict(r) for r in rows]

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

    # ── 2026-05-22 L2: BatchRunManager state persistence ──

    def upsert_batch(
        self,
        batch_id: str,
        *,
        status: str,
        created_at: str,
        finished_at: str | None,
        concurrency: int,
        params: dict[str, Any],
        items: list[dict[str, Any]],
        events: list[dict[str, Any]],
        reports_root: str | None,
        kind: str = "sampling",
    ) -> None:
        """Upsert a batch's full state. Called by BatchRunManager
        at start_batch, at each item finalize, on cancel, and on
        terminal status transition; also called by BatchGenerateManager
        (2026-05-26 L3) with kind='generate' for the same lifecycle
        events.

        Light-frequency writes — events list is appended at logical
        milestones (typically 5-30 rows per batch), not on each
        chunk_progress emission.
        """
        # Cap events at last 200 to bound the column size; matches
        # the existing -100 read cap on get_batch but leaves a bit
        # of headroom for criticals.
        events_capped = list(events)[-200:]
        payload = {
            "batch_id": batch_id,
            "status": status,
            "kind": str(kind or "sampling"),
            "created_at": created_at,
            "finished_at": finished_at,
            "concurrency": int(concurrency),
            "params_json": json.dumps(params, ensure_ascii=False),
            "items_json": json.dumps(items, ensure_ascii=False),
            "events_json": json.dumps(events_capped, ensure_ascii=False),
            "reports_root": reports_root,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO batches (
                    batch_id, status, kind, created_at, finished_at,
                    concurrency, params_json, items_json, events_json,
                    reports_root
                ) VALUES (
                    :batch_id, :status, :kind, :created_at, :finished_at,
                    :concurrency, :params_json, :items_json, :events_json,
                    :reports_root
                )
                ON CONFLICT(batch_id) DO UPDATE SET
                    status=:status,
                    kind=:kind,
                    finished_at=:finished_at,
                    concurrency=:concurrency,
                    params_json=:params_json,
                    items_json=:items_json,
                    events_json=:events_json,
                    reports_root=:reports_root
                """,
                payload,
            )

    def get_batch_row(self, batch_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM batches WHERE batch_id=?", (batch_id,),
            ).fetchone()
        if row is None:
            return None
        out = dict(row)
        # Decode JSON columns for caller convenience.
        for col in ("params_json", "items_json", "events_json"):
            try:
                out[col.removesuffix("_json")] = json.loads(out.get(col) or "null")
            except (TypeError, json.JSONDecodeError):
                out[col.removesuffix("_json")] = None
        return out

    def list_batches_by_status(
        self,
        statuses: tuple[str, ...],
        limit: int = 5000,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """List batches matching ``statuses``. ``kind`` optional filter
        (e.g. 'sampling' or 'generate'). Returns most-recent first by
        created_at."""
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        params: tuple[Any, ...] = tuple(statuses)
        sql = f"SELECT * FROM batches WHERE status IN ({placeholders})"
        if kind is not None:
            sql += " AND kind=?"
            params = params + (kind,)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params = params + (limit,)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            for col in ("params_json", "items_json", "events_json"):
                try:
                    d[col.removesuffix("_json")] = json.loads(d.get(col) or "null")
                except (TypeError, json.JSONDecodeError):
                    d[col.removesuffix("_json")] = None
            out.append(d)
        return out

    def list_recent_batches(
        self,
        limit: int = 50,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """List recent batches across ALL statuses (running / completed /
        cancelled / partial / failed / pending). Used by the UI
        history panel so the operator can see what happened across
        every console session, not just what's currently in flight.

        Kind filter optional — pass 'sampling' or 'generate' to scope
        to one batch manager's history; omit for unified view."""
        sql = "SELECT * FROM batches"
        params: tuple[Any, ...] = ()
        if kind is not None:
            sql += " WHERE kind=?"
            params = (kind,)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params = params + (int(limit),)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            for col in ("params_json", "items_json", "events_json"):
                try:
                    d[col.removesuffix("_json")] = json.loads(d.get(col) or "null")
                except (TypeError, json.JSONDecodeError):
                    d[col.removesuffix("_json")] = None
            out.append(d)
        return out

    def list_runs_by_report_version(self, version: str) -> list[dict[str, Any]]:
        """Every run row pointing at a given `<rv_...>` version directory.

        Used by the retention pruner: before deleting a version dir on
        disk, find and drop any runs rows that reference it so the UI
        doesn't later show dangling entries with missing file paths.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE report_version=?", (version,)
            ).fetchall()
        return [dict(r) for r in rows]

    def backfill_rtp_ci_from_summaries(self) -> dict[str, Any]:
        """One-shot migration: for every completed row missing
        achieved_rtp_pct, achieved_halfwidth_pp, quality_label,
        rawdata_config_md5, rawdata_code_md5, or analyzer_version,
        read the on-disk summary.json and populate the column. Old
        rows (from before _update_report_index started persisting
        these fields) would otherwise render as "\u2014" forever.

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
                       achieved_halfwidth_pp, quality_label,
                       rawdata_config_md5, rawdata_code_md5, analyzer_version,
                       effective_analyzer_version,
                       total_spins
                FROM runs
                WHERE status IN ('completed', 'cancelled')
                  AND (achieved_rtp_pct IS NULL
                       OR achieved_halfwidth_pp IS NULL
                       OR quality_label IS NULL
                       OR rawdata_config_md5 IS NULL
                       OR rawdata_code_md5 IS NULL
                       OR analyzer_version IS NULL
                       OR total_spins IS NULL)
                  -- effective_analyzer_version intentionally NOT in this
                  -- predicate: old summaries pre-Phase-3 lack the field,
                  -- so its IS NULL would re-scan the same legacy rows on
                  -- every backfill pass with no progress. The column
                  -- still gets populated when the loop body runs for
                  -- other reasons (any other NULL → loop fires → field
                  -- is set on UPDATE if present in summary).
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
                if not isinstance(summary, dict):
                    continue
                rtp = summary.get("rtp", {}).get("point_pct")
                hw = summary.get("sampling", {}).get("achieved_halfwidth_pp")
                ql = (
                    summary.get("guideline_assessment", {})
                    .get("data_quality", {})
                    .get("quality_label")
                )
                rpt_cfg = summary.get("config_md5")
                rpt_code = summary.get("code_md5")
                analyzer_ver = summary.get("analyzer_version")
                eff_analyzer_ver = summary.get("effective_analyzer_version")
                tot_spins = summary.get("sampling", {}).get("total_spins")
                # Write whichever fields had a null stored + a real
                # value available; leave others alone.
                patch_pairs: list[tuple[str, Any]] = []
                if r["achieved_rtp_pct"] is None and rtp is not None:
                    patch_pairs.append(("achieved_rtp_pct", float(rtp)))
                if r["achieved_halfwidth_pp"] is None and hw is not None:
                    patch_pairs.append(("achieved_halfwidth_pp", float(hw)))
                if r["quality_label"] is None and ql:
                    patch_pairs.append(("quality_label", str(ql)))
                if r["rawdata_config_md5"] is None and rpt_cfg:
                    patch_pairs.append(("rawdata_config_md5", str(rpt_cfg)))
                if r["rawdata_code_md5"] is None and rpt_code:
                    patch_pairs.append(("rawdata_code_md5", str(rpt_code)))
                if r["analyzer_version"] is None and analyzer_ver:
                    patch_pairs.append(("analyzer_version", str(analyzer_ver)))
                if r["effective_analyzer_version"] is None and eff_analyzer_ver:
                    patch_pairs.append(
                        ("effective_analyzer_version", str(eff_analyzer_ver))
                    )
                if r["total_spins"] is None and tot_spins is not None:
                    patch_pairs.append(("total_spins", int(tot_spins)))
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
    # 2026-04-22: guard against empty-string Path inputs. ``Path("")``
    # equals ``Path(".")`` — which exists() returns True for (current
    # dir) but is not a file → read_text() raises IsADirectoryError
    # and the /api/runs list endpoint 500s. The placeholder-row path
    # for async generate-report + any other caller that might hand us
    # a missing / empty path benefits from is_file() over exists().
    if not progress_file.is_file():
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


def _classify_machine(logic_classes: list[str]) -> str:
    """Derive a human-readable category from logicClassNames.

    Priority ordered — the first matching pattern wins.  The categories
    are intentionally broad; operators refine via the search bar.
    """
    names = {n for n in logic_classes}
    if not names:
        return "Unknown"
    joined = " ".join(names).lower()
    if any("BuffCollection" in n for n in names):
        return "Collect"
    if any("LockReSpin" in n or "LockSpin" in n for n in names):
        return "Lock"
    if any("Fortunes" in n for n in names):
        return "Fortunes"
    if any("RedHot" in n for n in names):
        return "ReSpin"
    if any("Wheel" in n for n in names):
        return "Wheel"
    if any("FreeSpin" in n or "Rising" in n for n in names):
        return "FreeSpin"
    # Broader ReSpin detection (WildRespin, DiamondRespin, etc.)
    if "respin" in joined:
        return "ReSpin"
    if "selector" in joined:
        return "Selector"
    if "collection" in joined:
        return "Collect"
    if all("Normal" in n or "RTP" in n for n in names):
        return "Normal"
    return "Other"


def load_machines(
    path: Path | None = None,
    reports_root: Path | None = None,
) -> list[dict[str, Any]]:
    target = path if path is not None else MACHINES_CONFIG
    rr = reports_root if reports_root is not None else REPORTS_ROOT
    if target.exists():
        payload = read_json(target)
        machines = payload.get("machines", [])
        if isinstance(machines, list):
            for m in machines:
                logic = m.get("logicClassNames", [])
                m.setdefault("category", _classify_machine(logic))
                m.setdefault("available", bool(logic))
                # Count on-disk report versions for this machine.
                report_count = 0
                machine_dir = rr / m["machine"]
                if machine_dir.is_dir():
                    for mode_dir in machine_dir.iterdir():
                        versions_dir = mode_dir / "versions"
                        if versions_dir.is_dir():
                            report_count += sum(
                                1 for v in versions_dir.iterdir() if v.is_dir()
                            )
                m["report_count"] = report_count
            return machines
    return [{"machine": "M14", "modes": [1], "category": "Normal", "report_count": 0}]


def _load_classifier_verdict(
    machine: str, classify_dir: Path = CLASSIFY_DIR,
) -> dict[str, Any]:
    """Per-mode payline-structure verdict for a machine.

    Reads each ``all_verdicts_mode<N>.json`` under ``classify_dir``,
    picks the entry for ``machine`` (if present), and returns a
    compact per-mode summary for UI display:

    * ``machine_label`` — "classic-payline [strict-ltr]" / "ways-pay" /
      "hybrid (payline+board) [flexible]" / "no-wins"
    * ``paid_spin_type`` — the inferred paid SpinType
    * ``per_st_verdicts`` — per-SpinType channel ("pay_id" /
      "FeatureWin aggregated" / etc) + classification bucket
    * ``feature_delta_from_paid`` — per-bonus-SpinType added/removed
      line_id sets when bonus mode's payline rules differ from paid
      (flag for RTP interpretation)
    * ``feature_tally_keys`` — list of upstream_feature_tally names
      seen on this machine

    Missing classifier output (dev_reports not populated, or
    classifier never run) → empty ``modes`` dict. Endpoint stays 200
    so UI can render "no data" gracefully instead of erroring.
    """
    modes: dict[str, dict[str, Any]] = {}
    updated_at: dict[str, str] = {}
    if not classify_dir.is_dir():
        return {"machine": machine, "modes": modes, "updated_at": updated_at}

    def _record_verdict(mode: int, v: dict, ts: str | None) -> None:
        modes[str(mode)] = {
            "machine_label": v.get("machine_label"),
            "paid_spin_type": v.get("paid_spin_type"),
            "all_resolved": v.get("all_resolved"),
            "per_st_verdicts": v.get("per_st_verdicts") or {},
            "feature_delta_from_paid": v.get("feature_delta_from_paid") or {},
            "feature_tally_keys": v.get("feature_tally_keys") or [],
            "grid": v.get("grid") or {},
        }
        if ts:
            updated_at[str(mode)] = ts

    # Prefer per-machine files (primary artifact from auto-triggered
    # hooks — no race with other machines' writes). Shape:
    # ``{machine}_mode<N>.json`` with ``{mode, machine, verdict,
    # written_at}``.
    for f in sorted(classify_dir.glob(f"{machine}_mode*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mode = d.get("mode")
        v = d.get("verdict")
        if not isinstance(mode, int) or not isinstance(v, dict):
            continue
        if v.get("machine") != machine:
            continue
        _record_verdict(mode, v, d.get("written_at"))

    # Fallback for modes still missing: read the legacy combined
    # ``all_verdicts_mode<N>.json`` (written by full-fleet sweeps /
    # ≥2-machine runs). Per-machine file takes precedence when both
    # exist — it's by construction newer.
    for f in sorted(classify_dir.glob("all_verdicts_mode*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mode = d.get("mode")
        if not isinstance(mode, int) or str(mode) in modes:
            continue
        for v in d.get("verdicts") or []:
            if v.get("machine") != machine:
                continue
            try:
                ts = datetime.fromtimestamp(
                    f.stat().st_mtime, tz=timezone.utc,
                ).isoformat().replace("+00:00", "Z")
            except OSError:
                ts = None
            _record_verdict(mode, v, ts)
            break
    return {"machine": machine, "modes": modes, "updated_at": updated_at}


def _load_paytable_shape(
    machine: str,
    mode: int,
    paytables_dir: Path = PAYTABLES_DIR,
) -> dict[str, Any]:
    """Per-pay_id shape inference + wild auto-detection for one
    (machine, mode). Reads the JSON produced by
    ``scripts/infer_paytable.py`` and returns a trimmed UI-oriented
    view (drops mult-only fields, keeps shape / wild_inference /
    self_verify).

    Missing file → ``status="not_run"`` so the endpoint stays 200 and
    UI renders "not yet inferred — run scripts/infer_paytable.py".
    """
    path = paytables_dir / f"{machine}_mode{mode}.json"
    if not path.is_file():
        return {
            "machine": machine,
            "mode": mode,
            "status": "not_run",
            "rows": [],
            "wild_inference": None,
            "machine_flags": [],
            "grid": None,
        }
    try:
        pt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "machine": machine,
            "mode": mode,
            "status": "error",
            "rows": [],
            "wild_inference": None,
            "machine_flags": [],
            "grid": None,
        }
    wi = pt.get("wild_inference") or {}
    sv = pt.get("self_verify") or {}
    rows_out: list[dict[str, Any]] = []
    for r in pt.get("paytable_rows") or []:
        sh = r.get("shape") or {}
        rows_out.append({
            "pay_id": r.get("pay_id"),
            "match_count": r.get("match_count"),
            "fires": r.get("fires"),
            # avg_win added by the 2026-04-20 round 3 script upgrade —
            # lets the UI cross-check the script's own rawdata scan
            # against analyzer's payout_ids_top20[*].avg_win_when_hit
            # without walking ``shape.wild_composition_breakdown``.
            "avg_win": r.get("avg_win"),
            "line_ids_fired": r.get("line_ids_fired") or [],
            "shape": sh,
        })
    return {
        "machine": machine,
        "mode": mode,
        "status": "ok",
        "grid": pt.get("grid"),
        "wild_inference": {
            "status": wi.get("status"),
            "wilds": wi.get("wilds") or [],
            "evidence": wi.get("evidence") or {},
            "tier_stems": wi.get("tier_stems") or {},
            "review_needed": wi.get("review_needed", False),
            "stem_count": wi.get("stem_count", 0),
        },
        "rows": rows_out,
        "machine_flags": sv.get("machine_flags") or [],
        "chunks_scanned": pt.get("chunks_scanned"),
    }


# ── Per-app-instance cache state (P1-C1 migration) ───────────────────
# Previously these were bare module-level dicts/sets, which leaked
# across multiple app instances created in the same process (tests).
# Now each create_app() call gets its own AppCacheState(); the module-
# level _MODULE_CACHE_STATE is the backward-compat default for any
# standalone caller (scripts / tests that call helper fns directly
# without going through create_app).
# Per memory feedback_subprocess_import_suicide_and_module_globals.md:
#   "module-level dict → self._xxx; tests that monkeypatch the module
#    global no longer catch the bug → split-path regression needed."


class AppCacheState:
    """Per-app-instance cache container for the 5 formerly-module-global
    mutable state structures.  Instantiate once per create_app() call
    and pass via closure to every function that previously referenced a
    module-level global.

    NOT imported at module top — instantiated lazily inside create_app.
    No build_*() side effects; safe to import (§3 C3 invariant).
    """

    __slots__ = (
        "machines_summary_cache",
        "rawdata_overview_cache",
        "static_attrs_cache",
        "lock_cache",
        "in_use_modes",
        "in_use_lock",
    )

    def __init__(self) -> None:
        # Machines-summary: keyed by str(reports_root) → {fingerprint, result}
        self.machines_summary_cache: dict[str, dict[str, Any]] = {}
        # Rawdata-overview: keyed by str(rawdata_root) → {fp, retention, result}
        self.rawdata_overview_cache: dict[str, dict[str, Any]] = {}
        # Static-attrs: mtime-invalidated in-memory view of machines_static.json
        self.static_attrs_cache: dict = {"mtime": 0, "data": None}
        # Rawdata-locks: mtime-invalidated in-memory view of rawdata_locks.json
        self.lock_cache: dict = {"mtime": 0, "data": None}
        # In-use protection: (machine, mode) pairs currently being sampled/analyzed
        self.in_use_modes: set[tuple[str, int]] = set()
        self.in_use_lock: threading.Lock = threading.Lock()


# Module-level singleton — backward-compat default for standalone callers
# (scripts / tests that call helper fns without going through create_app).
# Each create_app() instance gets its own AppCacheState() and passes it
# via closure; the module global is NEVER used by in-process app routes.
_MODULE_CACHE_STATE = AppCacheState()


def _machines_summary_fingerprint(reports_root: Path) -> tuple[int, int]:
    """Lightweight cache key: (sum of version-dir mtime_ns, version-dir count)
    across all (machine, mode) pairs. Stat-only, no file reads. Changes when
    a new version is added (import / generate-report both create a new
    ``versions/<rv_*>`` dir) or an existing version dir is touched. The
    count component catches additions where the new dir's mtime_ns happens
    to sum-cancel (theoretical, but cheap to guard).

    We scan version dirs rather than ``latest.json`` mtimes because
    ``/api/reports/import`` doesn't rewrite latest.json — it only copies
    the version tree — and the cache would otherwise miss imported
    reports until a subsequent run touched latest.json."""
    if not reports_root.is_dir():
        return (0, 0)
    total = 0
    count = 0
    for machine_dir in reports_root.iterdir():
        if not machine_dir.is_dir():
            continue
        for mode_dir in machine_dir.iterdir():
            if not mode_dir.is_dir() or not mode_dir.name.startswith("mode_"):
                continue
            versions_dir = mode_dir / "versions"
            if not versions_dir.is_dir():
                continue
            for ver_dir in versions_dir.iterdir():
                try:
                    total += ver_dir.stat().st_mtime_ns
                    count += 1
                except OSError:
                    continue
    return (total, count)


# ── Rawdata overview cache ────────────────────────────────────────
# Fleet-wide per-machine rawdata breakdown (kept / deletable /
# historical bytes + total). Walking every chunk envelope is O(N_chunks) and
# takes seconds on a large fleet; mtime-fingerprint cache makes it
# effectively free when nothing changed. Invalidated by add/delete
# of chunk files (mode_dir mtime bumps).
# Migrated from _RAWDATA_OVERVIEW_CACHE module global to AppCacheState
# per P1-C1 (feedback_subprocess_import_suicide_and_module_globals.md).


def _rawdata_overview_fingerprint(rawdata_root: Path) -> tuple[int, int]:
    """Aggregate mtime_ns + mode_dir count across all (machine, mode).
    Changes when chunks are added/deleted/replaced."""
    if not rawdata_root.is_dir():
        return (0, 0)
    total = 0
    count = 0
    for machine_dir in rawdata_root.iterdir():
        if not machine_dir.is_dir() or machine_dir.name.startswith("_"):
            continue
        for mode_dir in machine_dir.iterdir():
            if not mode_dir.is_dir() or not mode_dir.name.startswith("mode_"):
                continue
            try:
                total += mode_dir.stat().st_mtime_ns
                count += 1
            except OSError:
                continue
    return (total, count)


def _build_rawdata_overview(
    rawdata_root: Path,
    machines_config: Path,
    retention_spins: int,
    _cs: "AppCacheState | None" = None,
) -> dict[str, Any]:
    """Per-machine rawdata breakdown (baseline / reclaimable / historical
    bytes + last-sample mtime) + fleet aggregates. Cached keyed on
    str(rawdata_root) with the mtime fingerprint above.
    _cs is the per-app-instance AppCacheState (P1-C1)."""
    cs = _cs if _cs is not None else _MODULE_CACHE_STATE
    cache_key = str(rawdata_root)
    fp = _rawdata_overview_fingerprint(rawdata_root)
    entry = cs.rawdata_overview_cache.get(cache_key)
    if entry and entry.get("fp") == fp and entry.get("retention") == retention_spins:
        return entry["result"]

    per_machine: list[dict[str, Any]] = []
    total_kept = 0
    total_del = 0
    total_historical = 0
    if rawdata_root.is_dir():
        for machine_dir in sorted(rawdata_root.iterdir()):
            if not machine_dir.is_dir() or machine_dir.name.startswith("_"):
                continue
            machine = machine_dir.name
            m_kept = m_del = m_historical = 0
            m_kept_chunks = m_del_chunks = m_historical_chunks = 0
            latest_mtime = 0.0
            for mode_dir in machine_dir.iterdir():
                if not mode_dir.is_dir() or not mode_dir.name.startswith("mode_"):
                    continue
                try:
                    mode = int(mode_dir.name.split("_")[1])
                except (IndexError, ValueError):
                    continue
                cls = _classify_chunks(machine, mode, rawdata_root, machines_config, retention_spins)
                for kind, sink_key in (("kept", "m_kept"), ("deletable", "m_del"), ("historical", "m_historical")):
                    for entry_d in cls[kind]:
                        try:
                            sz = Path(entry_d["path"]).stat().st_size
                        except OSError:
                            sz = 0
                        if sink_key == "m_kept":
                            m_kept += sz; m_kept_chunks += 1
                        elif sink_key == "m_del":
                            m_del += sz; m_del_chunks += 1
                        else:
                            m_historical += sz; m_historical_chunks += 1
                        if entry_d["mtime"] > latest_mtime:
                            latest_mtime = entry_d["mtime"]
            if (m_kept + m_del + m_historical) == 0:
                continue
            per_machine.append({
                "machine": machine,
                "kept_bytes": m_kept,
                "deletable_bytes": m_del,
                "historical_bytes": m_historical,
                "kept_chunks": m_kept_chunks,
                "deletable_chunks": m_del_chunks,
                "historical_chunks": m_historical_chunks,
                "last_sample_mtime": latest_mtime,
            })
            total_kept += m_kept
            total_del += m_del
            total_historical += m_historical
    result = {
        "total_bytes": total_kept + total_del + total_historical,
        "baseline_bytes": total_kept,
        "deletable_bytes": total_del,
        "historical_bytes": total_historical,
        "reclaimable_bytes": total_del + total_historical,
        "per_machine": per_machine,
    }
    cs.rawdata_overview_cache[cache_key] = {
        "fp": fp, "retention": retention_spins, "result": result,
    }
    return result


# ── Machine static attrs cache (2026-04-19 round 6) ─────────────────
# Static attributes (category / logicClassNames / features / mechanics /
# config_md5 / code_md5) are cached to a dedicated JSON file so the
# catalog filters (按玩法 chips + 按机制 view) don't break when reports
# get deleted or regenerated. Refresh policy:
#   * Seeded from machines.json on first access (bootstrap).
#   * Updated after every successful generate-report: features +
#     mechanics merged in as UNION across history (short rawdata
#     doesn't evict entries that were seen in earlier reports).
#   * Rebuilt on /api/reports/import success.
# Performance: in-memory cache keyed by file mtime_ns; atomic writes
# via temp + os.replace; O(machines × modes) bootstrap walk runs once.
_STATIC_ATTRS_CACHE: dict = {"mtime": 0, "data": None}
# Phase 1 fix: guard parallel to _LOCK_CACHE_GUARD (added for _LOCK_CACHE in
# Phase 1 commit cec5012; _STATIC_ATTRS_CACHE has the IDENTICAL TOCTOU shape
# and was left unguarded — caught by impl-critic retroactive review).
# Closes the race where concurrent _load + _save leave (mtime, data) in
# an inconsistent state (mtime says fresh, data is stale or mid-build).
_STATIC_ATTRS_CACHE_GUARD = threading.Lock()

# ── In-use protection — DELETED in Phase 2 deploy refactor ──────────
# _IN_USE_MODES / _IN_USE_LOCK / _acquire_in_use / _release_in_use /
# _get_in_use_snapshot were replaced by CellLockRegistry (imported above).
# The registry is injected into create_app() and threaded through all
# callers that previously used these helpers.
# See session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md §4.1 D5.


# ── Rawdata lock registry (2026-04-20 round 6) ──────────────────────
# Per-(machine, mode) lock — locked entries are NEVER auto-deleted by
# the disk-pressure auto-cleanup logic (kept baseline is already safe
# via min_retention_spins; lock is the operator's extra carve-out for
# chunks they want preserved beyond retention).
# Storage: configs/rawdata_locks.json, gitignored + per-fleet.
# Key format: "<machine>|<mode>". Value: bool (true = locked).
_LOCK_CACHE: dict = {"mtime": 0, "data": None}
# Phase 1 deploy: guard cache access so concurrent _load + _save can't
# leave (mtime, data) in inconsistent state (mtime says fresh, data is
# stale or being-built). Minor TOCTOU fix per 04_v2 Phase 1 deliverable #8.
_LOCK_CACHE_GUARD = threading.Lock()


def _rawdata_locks_path(configs_root_machines_config: Path) -> Path:
    return configs_root_machines_config.parent / "rawdata_locks.json"


def _load_rawdata_locks(path: Path) -> set[tuple[str, int]]:
    """Return the set of (machine, mode) tuples currently locked.
    Mtime-invalidated in-memory cache; file IO only on first call
    or when file mtime changes.

    Phase 1 deploy: cache check+update guarded by ``_LOCK_CACHE_GUARD``
    so concurrent _load calls can't race and produce inconsistent
    (mtime, data) state.
    """
    try:
        cur_mtime = path.stat().st_mtime_ns if path.exists() else 0
    except OSError:
        cur_mtime = 0
    with _LOCK_CACHE_GUARD:
        cached = _LOCK_CACHE.get("data")
        if cached is not None and _LOCK_CACHE.get("mtime") == cur_mtime:
            return cached
        locks: set[tuple[str, int]] = set()
        if path.exists():
            try:
                raw = read_json(path) or {}
            except Exception:
                raw = {}
            for key in (raw.get("locked") or []):
                try:
                    machine, mode_str = str(key).split("|", 1)
                    locks.add((machine, int(mode_str)))
                except (ValueError, TypeError):
                    continue
        _LOCK_CACHE["mtime"] = cur_mtime
        _LOCK_CACHE["data"] = locks
        return locks


def _save_rawdata_locks(path: Path, locks: set[tuple[str, int]]) -> None:
    """Phase 1 deploy: atomic + per-file-locked write; cache update
    guarded so concurrent _load can't observe partial update."""
    keys = sorted(f"{m}|{mode}" for (m, mode) in locks)
    payload = {"locked": keys, "updated_at": utc_now()}
    atomic_json_write(path, payload)
    with _LOCK_CACHE_GUARD:
        try:
            _LOCK_CACHE["mtime"] = path.stat().st_mtime_ns
        except OSError:
            pass
        _LOCK_CACHE["data"] = set(locks)


def _set_rawdata_lock(
    path: Path, machine: str, mode: int, locked: bool,
) -> bool:
    """Add or remove (machine, mode) from the lock set. Returns True if
    the state changed (lock applied or removed), False if it was already
    in the desired state."""
    locks = set(_load_rawdata_locks(path))
    key = (str(machine), int(mode))
    was = key in locks
    if locked and not was:
        locks.add(key)
    elif not locked and was:
        locks.discard(key)
    else:
        return False
    _save_rawdata_locks(path, locks)
    return True


# _STATIC_ATTRS_MECH_KEYS is a true constant (immutable tuple of mechanic
# key names), not mutable state.  Left as module-level per brief §4
# "True constants — leave alone".  Justified in 02_implementation.md.
_STATIC_ATTRS_MECH_KEYS = (
    "lock_lines", "lock_symbols", "lock_reels",
    "jackpot", "free_spin", "dollar_pick",
)


def _static_attrs_path(machines_config: Path) -> Path:
    """machines_static.json lives alongside machines.json in configs/."""
    return machines_config.parent / "machines_static.json"


def _load_static_attrs(path: Path) -> dict:
    """Phase 1 fix: cache check+update guarded by ``_STATIC_ATTRS_CACHE_GUARD``
    so concurrent _load calls can't race and produce inconsistent (mtime, data)
    state. Mirrors the ``_LOCK_CACHE_GUARD`` fix in ``_load_rawdata_locks``.
    Mtime stat is outside the lock (cheap + non-blocking; same pattern as
    ``_load_rawdata_locks`` per 04_v2 Phase 1 deliverable #8).
    """
    try:
        cur_mtime = path.stat().st_mtime_ns if path.exists() else 0
    except OSError:
        cur_mtime = 0
    with _STATIC_ATTRS_CACHE_GUARD:
        if (_STATIC_ATTRS_CACHE["data"] is not None
                and _STATIC_ATTRS_CACHE["mtime"] == cur_mtime):
            return _STATIC_ATTRS_CACHE["data"]
        if not path.exists():
            data: dict = {}
        else:
            try:
                data = read_json(path) or {}
            except Exception:
                data = {}
        data.setdefault("machines", {})
        data.setdefault("feature_distribution", {})
        data.setdefault("mechanics_distribution", {})
        _STATIC_ATTRS_CACHE["mtime"] = cur_mtime
        _STATIC_ATTRS_CACHE["data"] = data
        return data


def _save_static_attrs(path: Path, data: dict) -> None:
    """Phase 1 deploy: atomic + per-file-locked write.
    Phase 1 fix: cache update guarded by ``_STATIC_ATTRS_CACHE_GUARD``
    so concurrent _load can't observe a partial update (mtime written,
    data not yet — or vice versa). Mirrors ``_save_rawdata_locks`` pattern.
    """
    atomic_json_write(path, data)
    with _STATIC_ATTRS_CACHE_GUARD:
        try:
            _STATIC_ATTRS_CACHE["mtime"] = path.stat().st_mtime_ns
        except OSError:
            pass
        _STATIC_ATTRS_CACHE["data"] = data


def _rebuild_static_distributions(data: dict) -> None:
    """Recompute feature_distribution + mechanics_distribution from the
    per-machine dict. Called after any merge so the distributions stay
    in sync with the machines map."""
    feat_machines: dict[str, set] = {}
    mech_count: dict[str, int] = {}
    for machine, entry in (data.get("machines") or {}).items():
        for fn in entry.get("features") or []:
            feat_machines.setdefault(fn, set()).add(machine)
        for mk in entry.get("mechanics") or []:
            mech_count[mk] = mech_count.get(mk, 0) + 1
    data["feature_distribution"] = {
        fn: len(ms) for fn, ms in feat_machines.items()
    }
    data["mechanics_distribution"] = mech_count


def _extract_features_from_summary(summary: dict) -> set[str]:
    """Prefer feature_base_name (stripped of trigger-path suffix); fall
    back to feature_name. Skip trigger-only features."""
    out: set[str] = set()
    feats = (
        (summary.get("player_impact") or {})
        .get("upstream_feature_breakdown") or {}
    ).get("features") or []
    for f in feats:
        base = f.get("feature_base_name") or f.get("feature_name") or ""
        if base:
            out.add(str(base))
    return out


def _extract_mechanics_from_summary(summary: dict) -> set[str]:
    mm = (summary.get("player_impact") or {}).get("machine_mechanics") or {}
    return {
        mk for mk in _STATIC_ATTRS_MECH_KEYS
        if (mm.get(mk) or {}).get("applicable")
    }


def _machine_static_from_machines_json(
    machine: str, machines_config: Path,
) -> dict:
    """Pull the pure-static bits (category / logicClassNames / md5s) from
    machines.json. Called both at seed time and whenever a fresh summary
    is merged (so stale md5 in the cache gets refreshed)."""
    try:
        mc_data = read_json(machines_config) or {}
    except Exception:
        return {}
    for m_cfg in (mc_data.get("machines") or []):
        if m_cfg.get("machine") == machine:
            logic = m_cfg.get("logicClassNames") or []
            return {
                "category": (
                    m_cfg.get("category") or _classify_machine(logic)
                ),
                "logicClassNames": logic,
                "config_md5": str(m_cfg.get("configSummaryMd5") or ""),
                "code_md5": str(m_cfg.get("codeSummaryMd5") or ""),
                "modes": m_cfg.get("modes") or [1, 2, 5, 7],
            }
    return {}


def _merge_machine_static(
    machine: str, summary: dict,
    machines_config: Path, static_path: Path,
) -> None:
    """Merge one machine's attrs from a fresh report summary. UNION for
    features + mechanics (history-preserving so short rawdata doesn't
    erase entries)."""
    data = _load_static_attrs(static_path)
    entry = dict(data.get("machines", {}).get(machine, {}))
    features = set(entry.get("features") or [])
    features |= _extract_features_from_summary(summary)
    entry["features"] = sorted(features)
    mechs = set(entry.get("mechanics") or [])
    mechs |= _extract_mechanics_from_summary(summary)
    entry["mechanics"] = sorted(mechs)
    entry.update(_machine_static_from_machines_json(machine, machines_config))
    entry["updated_at"] = utc_now()
    data.setdefault("machines", {})[machine] = entry
    _rebuild_static_distributions(data)
    data["updated_at"] = entry["updated_at"]
    _save_static_attrs(static_path, data)


def _bootstrap_static_attrs(
    reports_root: Path, machines_config: Path, static_path: Path,
) -> dict:
    """First-call populate — walk existing report summaries + seed from
    machines.json. Called lazily from GET /api/machines/static when the
    cache file is missing or empty. O(machines × modes × versions)."""
    try:
        mc_data = read_json(machines_config) or {}
    except Exception:
        mc_data = {}
    machines_data: dict[str, dict] = {}
    for m_cfg in (mc_data.get("machines") or []):
        name = m_cfg.get("machine")
        if not name:
            continue
        logic = m_cfg.get("logicClassNames") or []
        machines_data[name] = {
            "category": (
                m_cfg.get("category") or _classify_machine(logic)
            ),
            "logicClassNames": logic,
            "config_md5": str(m_cfg.get("configSummaryMd5") or ""),
            "code_md5": str(m_cfg.get("codeSummaryMd5") or ""),
            "modes": m_cfg.get("modes") or [1, 2, 5, 7],
            "features": [],
            "mechanics": [],
            "updated_at": "",
        }
    # Overlay features + mechanics from existing report summaries.
    if reports_root.is_dir():
        for machine_dir in reports_root.iterdir():
            if not machine_dir.is_dir():
                continue
            name = machine_dir.name
            entry = machines_data.setdefault(name, {
                "features": [], "mechanics": [], "updated_at": "",
            })
            feats: set[str] = set(entry.get("features") or [])
            mechs: set[str] = set(entry.get("mechanics") or [])
            for mode_dir in machine_dir.iterdir():
                if (
                    not mode_dir.is_dir()
                    or not mode_dir.name.startswith("mode_")
                ):
                    continue
                versions_dir = mode_dir / "versions"
                if not versions_dir.is_dir():
                    continue
                for ver_dir in versions_dir.iterdir():
                    if not ver_dir.is_dir():
                        continue
                    sf = ver_dir / "player_impact_summary.json"
                    if not sf.exists():
                        continue
                    try:
                        s = json.loads(sf.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    feats |= _extract_features_from_summary(s)
                    mechs |= _extract_mechanics_from_summary(s)
            entry["features"] = sorted(feats)
            entry["mechanics"] = sorted(mechs)
            if feats or mechs:
                entry["updated_at"] = utc_now()
    data = {"machines": machines_data, "updated_at": utc_now()}
    _rebuild_static_distributions(data)
    _save_static_attrs(static_path, data)
    return data


def _auto_cleanup_for_space(
    rawdata_root: Path,
    machines_config: Path,
    retention: int,
    target_free_gb: float,
    low_water_gb: float | None = None,
    registry: "CellLockRegistry | None" = None,
) -> dict[str, Any]:
    """Evict deletable chunks oldest-first until free space ≥ target.

    Respected carve-outs:
      * ``kept`` (baseline retention) — protected automatically by
        _classify_chunks's partitioning.
      * ``locked`` (operator-applied via POST /api/rawdata/{m}/mode/{n}/lock)
        — entire (machine, mode) skipped even for deletable chunks.
      * ``in_use`` (analyzer currently sampling / generating for that
        (m, mode)) — skipped to avoid mid-write corruption.

    Returns ``{deleted_files, deleted_bytes, reached_target,
    initial_free_gb, final_free_gb, skipped_locked, skipped_in_use,
    candidates}``. When already above target on entry, returns
    ``reached_target=True`` without doing any IO.
    """
    result: dict[str, Any] = {
        "deleted_files": 0, "deleted_bytes": 0,
        "reached_target": False,
        "initial_free_gb": 0.0, "final_free_gb": 0.0,
        "skipped_locked": [], "skipped_in_use": [],
        "candidates": 0,
    }
    if not rawdata_root.is_dir():
        return result
    try:
        initial_free = shutil.disk_usage(str(rawdata_root)).free
    except OSError:
        return result
    result["initial_free_gb"] = round(initial_free / (1024 ** 3), 3)
    target_bytes = int(target_free_gb * (1024 ** 3))
    if initial_free >= target_bytes:
        result["reached_target"] = True
        result["final_free_gb"] = result["initial_free_gb"]
        return result

    # Respect the low-water trigger — if not below low_water, don't do
    # anything (caller may have called defensively).
    if low_water_gb is not None and initial_free >= int(low_water_gb * (1024 ** 3)):
        result["reached_target"] = True
        result["final_free_gb"] = result["initial_free_gb"]
        return result

    locks = _load_rawdata_locks(_rawdata_locks_path(machines_config))
    # Phase 2: use registry.get_active_cells() when registry is provided;
    # fall back to empty set (no-op protection) when called without one
    # (e.g. from very old test paths that pre-date registry injection).
    in_use: set[tuple[str, int]] = (
        registry.get_active_cells() if registry is not None else set()
    )

    # Collect deletable chunks across all (machine, mode), skipping
    # locked + in_use groups entirely.
    candidates: list[dict[str, Any]] = []
    for machine_dir in rawdata_root.iterdir():
        if not machine_dir.is_dir() or machine_dir.name.startswith("_"):
            continue
        machine = machine_dir.name
        for mode_dir in machine_dir.iterdir():
            if not mode_dir.is_dir() or not mode_dir.name.startswith("mode_"):
                continue
            try:
                mode = int(mode_dir.name.split("_")[1])
            except (IndexError, ValueError):
                continue
            key = (machine, mode)
            if key in locks:
                result["skipped_locked"].append(f"{machine}|{mode}")
                continue
            if key in in_use:
                result["skipped_in_use"].append(f"{machine}|{mode}")
                continue
            cls = _classify_chunks(machine, mode, rawdata_root, machines_config, retention)
            # Cleanable pool = above-retention current chunks + all
            # historical-md5 chunks. Merged + sorted by mtime below,
            # so we evict strictly oldest-first regardless of md5 —
            # md5 is a tag, not a priority signal (2026-04-21).
            pool = list(cls.get("deletable") or []) + list(cls.get("historical") or [])
            for entry in pool:
                candidates.append({
                    "path": Path(entry["path"]),
                    "mtime": entry["mtime"],
                    "machine": machine,
                    "mode": mode,
                })
    candidates.sort(key=lambda c: c["mtime"])  # oldest first
    result["candidates"] = len(candidates)

    deleted_files = 0
    deleted_bytes = 0
    current_free = initial_free
    # Bucket the unlinked filenames per (machine, mode) so we can
    # batch-drop them from the per-mode `_chunks.json` sidecar at
    # the end of the loop — one sidecar rewrite per mode instead of
    # one per chunk. Skipping this would leave dir.mtime > sidecar
    # .mtime on every affected mode → every following read does a
    # full glob+peek rebuild (~5 ms × N chunks).
    unlinked_by_mode: dict[tuple[str, int], list[str]] = {}
    for cand in candidates:
        if current_free >= target_bytes:
            break
        try:
            sz = cand["path"].stat().st_size
            cand["path"].unlink()
            deleted_files += 1
            deleted_bytes += sz
            current_free += sz  # best-effort — real free space may move with concurrent writers
            unlinked_by_mode.setdefault(
                (cand["machine"], int(cand["mode"])), [],
            ).append(cand["path"].name)
        except OSError:
            continue
    if unlinked_by_mode:
        try:
            from fresh_slotlab.chunk_index import bulk_remove_chunk_entries
            for (machine, mode), names in unlinked_by_mode.items():
                md = rawdata_root / machine / f"mode_{mode}"
                bulk_remove_chunk_entries(md, names)
        except Exception:  # noqa: BLE001
            # Sidecar update is an optimization; failures don't
            # invalidate the actual disk-space cleanup. Next reader
            # rebuilds via mtime stale-check.
            pass
    try:
        final_free = shutil.disk_usage(str(rawdata_root)).free
    except OSError:
        final_free = current_free
    result["deleted_files"] = deleted_files
    result["deleted_bytes"] = deleted_bytes
    result["final_free_gb"] = round(final_free / (1024 ** 3), 3)
    result["reached_target"] = final_free >= target_bytes
    return result


def _parse_upstream_map_order(upstream: dict) -> dict:
    """Parse the upstream ``POST /MachineTest/MapMachineOrder`` response
    into the platform's ordering model (2026-04-20 round 3 fix).

    Upstream fields:
      * ``localMapMachineCellsJson`` — JSON string → array of cell
        dicts (name / prefabAssetPath / cellType / isFront). Default
        on-map sequence; contains decorative cells (LinkedJackpotL /
        cellType=4 etc.) which we drop by matching ``name`` against
        ``^M\\d+$``.
      * ``gmMapMachineOrderJson`` — JSON string → array of activity
        overrides {Id / Orders / InfluenceMachines / StartTime /
        EndTime / MachineLuckyBonus / DependentSwitch / ...}.
      * ``machineTestVariantsJson`` — JSON string → dict
        ``{machine_key: upstream_md5_key}``. Authoritative map from a
        machine's variant-aware name (e.g. ``M273$1$1-2-3``) to the
        key under which the upstream ``MachineConfigMd5`` endpoint
        reports its md5 (e.g. ``M273``). Used *only* by the md5-refresh
        path to fan md5 values out across sibling variants; every
        other layer of the system treats each machine row as
        independent and does not consult this map.

    Returns ``{default_order, current_hall_order, active_activities,
    club_machines, variants_map}`` where ``current_hall_order`` =
    default_order with currently-active activities' InfluenceMachines
    promoted to the front (sorted by Orders[0] ascending). Activities
    with ``now ∈ [StartTime, EndTime]`` are "active"; others are
    dropped from the output.
    """
    import re as _re
    import time as _time
    machine_re = _re.compile(r"^M\d+$")

    default_order: list[str] = []
    club_machines: list[str] = []
    cells_json = upstream.get("localMapMachineCellsJson") if isinstance(upstream, dict) else None
    if isinstance(cells_json, str):
        try:
            cells = json.loads(cells_json)
        except json.JSONDecodeError:
            cells = []
        for c in cells if isinstance(cells, list) else []:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name", ""))
            if not machine_re.match(name):
                continue
            default_order.append(name)
            # Club ("Royal" lobby) marker: the cell carries
            # ``selectType: 2`` ONLY on the multi-cabinet bank machines
            # bracketed by the LinkedRoyalJackpot banners (verified on
            # live dev — 17 cells out of 247 machines; all other
            # machines have selectType=None). Preserve upstream order.
            if c.get("selectType") == 2:
                club_machines.append(name)

    now_ts = int(_time.time())
    activities_raw: list[dict] = []
    gm_json = upstream.get("gmMapMachineOrderJson") if isinstance(upstream, dict) else None
    if isinstance(gm_json, str):
        try:
            activities_raw = json.loads(gm_json) or []
        except json.JSONDecodeError:
            activities_raw = []
    active_activities: list[dict] = []
    for a in activities_raw if isinstance(activities_raw, list) else []:
        if not isinstance(a, dict):
            continue
        try:
            st = int(a.get("StartTime") or 0)
            et = int(a.get("EndTime") or 0)
        except (TypeError, ValueError):
            continue
        if st <= now_ts <= et:
            active_activities.append({
                "id": a.get("Id"),
                "orders": a.get("Orders") or [],
                "influence_machines": a.get("InfluenceMachines") or [],
                "except_machines": a.get("ExceptMachines") or [],
                "start_ts": st,
                "end_ts": et,
                "lucky_bonus": bool(a.get("MachineLuckyBonus")),
                "dep_switch": int(a.get("DependentSwitch") or 0),
                "desc": a.get("Desc"),
            })

    if active_activities and default_order:
        promoted_sequence: list[str] = []
        promoted_set: set[str] = set()
        def _act_key(a: dict) -> tuple:
            orders = a.get("orders") or []
            primary = orders[0] if orders else 9999
            return (primary, a.get("id") or 0)
        for a in sorted(active_activities, key=_act_key):
            for m in (a.get("influence_machines") or []):
                if m in promoted_set or m not in default_order:
                    continue
                promoted_sequence.append(m)
                promoted_set.add(m)
        tail = [m for m in default_order if m not in promoted_set]
        current_hall_order = promoted_sequence + tail
    else:
        current_hall_order = list(default_order)

    variants_map: dict[str, str] = {}
    variants_json = upstream.get("machineTestVariantsJson") if isinstance(upstream, dict) else None
    if isinstance(variants_json, str):
        try:
            raw_variants = json.loads(variants_json)
        except json.JSONDecodeError:
            raw_variants = None
        if isinstance(raw_variants, dict):
            for vk, uk in raw_variants.items():
                # Drop malformed rows rather than propagate them
                # silently; upstream schema drift should not poison
                # the map. Same guard as machine_variants._coerce_str_map.
                if isinstance(vk, str) and isinstance(uk, str):
                    variants_map[vk] = uk

    return {
        "default_order": default_order,
        "current_hall_order": current_hall_order,
        "active_activities": active_activities,
        "club_machines": club_machines,
        "variants_map": variants_map,
    }


def _build_machines_summary(
    reports_root: Path, _cs: "AppCacheState | None" = None,
) -> dict[str, Any]:
    """Scan reports dir, pick best-CI report per machine-mode, return summary.
    _cs is the per-app-instance AppCacheState (P1-C1); defaults to the
    module-level sentinel for standalone callers."""
    import math

    cs = _cs if _cs is not None else _MODULE_CACHE_STATE
    cache_key = str(reports_root)
    fingerprint = _machines_summary_fingerprint(reports_root)
    entry = cs.machines_summary_cache.get(cache_key)
    if entry is not None and entry.get("fingerprint") == fingerprint:
        return entry["result"]

    result: dict[str, dict[str, Any]] = {}
    # Collect all volatility values for percentile ranking.
    all_vol_values: list[tuple[str, int, float]] = []  # (machine, mode, zero_win_rate)
    # Mechanics distribution across machines.
    mechanics_dist: dict[str, int] = {}
    # Feature distribution: feature_name → set of machines (then count).
    feature_machines: dict[str, set[str]] = {}

    if not reports_root.is_dir():
        return {"machines": {}, "volatility_ranking": []}

    for machine_dir in reports_root.iterdir():
        if not machine_dir.is_dir():
            continue
        machine = machine_dir.name
        result[machine] = {}

        for mode_dir in machine_dir.iterdir():
            if not mode_dir.is_dir():
                continue
            # Extract mode from "mode_2"
            mode_str = mode_dir.name
            if not mode_str.startswith("mode_"):
                continue
            try:
                mode = int(mode_str.split("_")[1])
            except (IndexError, ValueError):
                continue

            versions_dir = mode_dir / "versions"
            if not versions_dir.is_dir():
                continue

            best: dict[str, Any] | None = None
            best_ci = float("inf")

            for ver_dir in versions_dir.iterdir():
                if not ver_dir.is_dir():
                    continue
                summary_file = ver_dir / "player_impact_summary.json"
                if not summary_file.exists():
                    continue
                try:
                    s = json.loads(summary_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue

                sampling = s.get("sampling", {})
                rtp_data = s.get("rtp", {})
                pi = s.get("player_impact", {})
                vol = pi.get("volatility", {})
                ci_hw = sampling.get("achieved_halfwidth_pp")
                ci_val = float(ci_hw) if ci_hw is not None else float("inf")

                if best is None or ci_val <= best_ci:
                    best_ci = ci_val
                    ga = s.get("guideline_assessment", {})
                    ga_cls = ga.get("classification", {})
                    ga_dm = ga.get("derived_metrics", {})
                    hap = pi.get("hit_and_payout", {})
                    # Extract mechanics from this report version.
                    _mechs = []
                    _mm = pi.get("machine_mechanics", {})
                    for _mk in ("lock_lines", "lock_symbols", "lock_reels", "jackpot", "free_spin", "dollar_pick"):
                        if _mm.get(_mk, {}).get("applicable"):
                            _mechs.append(_mk)
                    # Extract upstream features (raw feature names from the game).
                    _features = []
                    _ufb = pi.get("upstream_feature_breakdown", {})
                    for _f in _ufb.get("features", []) or []:
                        _fn = _f.get("feature_name", "")
                        if _fn:
                            _features.append(_fn)
                    # Report's own MD5 (added in session-MD5-tagging commit).
                    _rpt_cfg = str(s.get("config_md5", ""))
                    _rpt_code = str(s.get("code_md5", ""))
                    best = {
                        "rtp_pct": rtp_data.get("point_pct"),
                        "ci_halfwidth_pp": ci_hw,
                        "total_spins": sampling.get("total_spins", 0),
                        "volatility_class": ga_cls.get("volatility_class", ""),
                        "zero_win_rate": float(hap.get("zero_win_rate", 0) or 0),
                        "tail_ge10x": float(ga_dm.get("tail_dependency", 0) or 0),
                        "report_version": ver_dir.name,
                        "mechanics": _mechs,
                        "features": _features,
                        "config_md5": _rpt_cfg,
                        "code_md5": _rpt_code,
                    }

            if best is not None:
                # Compute MD5 status vs current machines.json (upstream).
                up_cfg, up_code = _get_machine_md5(machine, mode=mode)
                r_cfg = best.get("config_md5", "")
                r_code = best.get("code_md5", "")
                if not r_cfg and not r_code:
                    best["md5_status"] = "untagged"
                elif not up_cfg and not up_code:
                    best["md5_status"] = "unverifiable"
                elif r_cfg == up_cfg and r_code == up_code:
                    best["md5_status"] = "match"
                else:
                    best["md5_status"] = "outdated"

                result[machine][str(mode)] = best
                zwr = best.get("zero_win_rate", 0)
                if isinstance(zwr, (int, float)) and math.isfinite(zwr):
                    all_vol_values.append((machine, mode, zwr))
                for mk in best.get("mechanics", []):
                    mechanics_dist[mk] = mechanics_dist.get(mk, 0) + 1
                # Track features per machine (not per machine-mode, dedupe with set).
                for fn in best.get("features", []):
                    if fn not in feature_machines:
                        feature_machines[fn] = set()
                    feature_machines[fn].add(machine)

    # Compute percentile ranks for zero_win_rate across all machine-modes.
    all_vol_values.sort(key=lambda x: x[2])
    n = len(all_vol_values)
    for rank, (m, mode, zwr) in enumerate(all_vol_values):
        pct = round((rank / n) * 100) if n > 1 else 50
        if m in result and str(mode) in result[m]:
            result[m][str(mode)]["volatility_percentile"] = pct

    feature_distribution = {fn: len(ms) for fn, ms in feature_machines.items()}
    out = {
        "machines": result,
        "mechanics_distribution": dict(mechanics_dist),
        "feature_distribution": feature_distribution,
    }
    cs.machines_summary_cache[cache_key] = {"fingerprint": fingerprint, "result": out}
    return out


class BatchGenerateManager:
    """Background batch driver for ``POST /api/rawdata/batch-generate-
    report``. Each batch is a list of (machine, mode) pairs; analyzer
    runs for each item execute in a ProcessPoolExecutor of N worker
    subprocesses (default 4).

    Why subprocess pool (refactor 2026-04-19 round 7): the old design
    ran items sequentially because analyzer's ``post_json`` is monkey-
    patched at the module level, and concurrent in-process calls would
    race each other. Running analyzer in a subprocess per item gives
    each call its own interpreter state — the in-process generator
    callback (``prepare_fn``) just handles the DB row / output dir /
    chunk discovery; the actual analyzer.main() lives in the worker.

    Phase 2: per-item GENERATING locks via CellLockRegistry replace the old
    coarse ops mutex.
    """

    def __init__(
        self,
        prepare_fn: Callable[[str, int], dict[str, Any]],
        finalize_fn: Callable[[dict, dict], dict[str, Any]],
        concurrency: int = 4,
        root_path: str = "",
        store: "StateStore | None" = None,
    ) -> None:
        # prepare_fn(machine, mode) → dict with:
        #   job: pickle-safe dict for the worker (chunk_dir, output_dir,
        #        run_id, etc.)
        #   plus any extra keys the caller wants (machine/mode/run_id/etc)
        #   which finalize_fn uses to update DB + index.json.
        # Phase 2: runs per-item GENERATING acquire inside the wrapper
        # (D7); no longer needs the coarse ops mutex.
        self._prepare_fn = prepare_fn
        # finalize_fn(prepared_dict, worker_result_dict) → dict with
        #   final metrics (rtp_point_pct, achieved_halfwidth_pp, etc.).
        # Runs in the parent thread after each worker result arrives.
        self._finalize_fn = finalize_fn
        # Phase 2: _ops removed — per-item registry GENERATING replaces it.
        self._batches: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._concurrency = max(1, int(concurrency))
        self._root_path = root_path
        # 2026-05-26 L3: persist state to SQLite so a console restart
        # mid-batch doesn't erase the operator's view. None when caller
        # doesn't supply a store (e.g. tests constructing the manager
        # directly without create_app); persistence becomes a no-op in
        # that case so the rest of the manager still works.
        self._store = store
        if self._store is not None:
            self._restore_persisted()

    def _persist(self, batch_id: str) -> None:
        """Snapshot state to the batches SQLite table with kind='generate'.
        Safe to call from inside or outside the lock; takes the lock
        itself to read a consistent snapshot. Wrapped in try/except so
        a persistence failure never blocks the foreground thread.
        """
        if self._store is None:
            return
        with self._lock:
            state = self._batches.get(batch_id)
            if state is None:
                return
            snapshot = {
                "status": str(state.get("status") or ""),
                "created_at": str(state.get("started_at") or utc_now()),
                "finished_at": state.get("finished_at"),
                "concurrency": self._concurrency,
                # BatchGenerateManager has no equivalent of BatchRunManager's
                # `params` (the analyzer-side knobs are computed per-item
                # by prepare_fn). Persist counter fields here so the
                # history view can show "5/20 completed" without parsing
                # items_json.
                "params": {
                    "total": int(state.get("total") or 0),
                    "completed": int(state.get("completed") or 0),
                    "failed": int(state.get("failed") or 0),
                    "pending": int(state.get("pending") or 0),
                    "error": state.get("error"),
                },
                "items": [dict(it) for it in state.get("items") or []],
                "events": [],  # BatchGenerateManager has no events list
                "reports_root": None,
                "kind": "generate",
            }
        try:
            self._store.upsert_batch(batch_id, **snapshot)
        except Exception:
            pass

    def _restore_persisted(self) -> None:
        """Read non-terminal generate batches from the batches table
        and rehydrate as cancelled-by-restart. Same pattern as
        BatchRunManager._restore_persisted_batches but with
        kind='generate' filter."""
        if self._store is None:
            return
        try:
            persisted = self._store.list_batches_by_status(
                ("pending", "running"),
                limit=5000,
                kind="generate",
            )
        except Exception:
            return
        for row in persisted:
            batch_id = str(row.get("batch_id") or "").strip()
            if not batch_id:
                continue
            items = row.get("items") or []
            counter_params = row.get("params") or {}
            cancelled_during_running = 0
            for it in items:
                if isinstance(it, dict) and it.get("status") in ("pending", "running"):
                    it["status"] = "cancelled"
                    if not it.get("error"):
                        it["error"] = "cancelled by console restart"
                    cancelled_during_running += 1
            state = {
                "batch_id": batch_id,
                "started_at": str(row.get("created_at") or utc_now()),
                "finished_at": utc_now(),
                "status": "cancelled",
                "total": int(counter_params.get("total") or len(items)),
                "completed": int(counter_params.get("completed") or 0),
                "failed": int(counter_params.get("failed") or 0),
                "pending": 0,  # nothing left pending after restart
                "error": "interrupted by console restart",
                "items": items,
                "_cancel_requested": True,
            }
            self._batches[batch_id] = state
            # Persist the cancelled-by-restart state back so subsequent
            # reads of the SQLite row reflect the recovery decision.
            self._persist(batch_id)

    def start(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        batch_id = f"bgen_{uuid.uuid4().hex[:12]}"
        state = {
            "batch_id": batch_id,
            "started_at": utc_now(),
            "finished_at": None,
            "status": "pending",
            "total": len(items),
            "completed": 0,
            "failed": 0,
            "pending": len(items),
            "error": None,
            "items": [
                {
                    "machine": it["machine"],
                    "mode": it["mode"],
                    "status": "pending",
                    "run_id": None,
                    "rtp_point_pct": None,
                    "achieved_halfwidth_pp": None,
                    "chunks_processed": None,
                    "error": None,
                }
                for it in items
            ],
        }
        with self._lock:
            self._batches[batch_id] = state
        # 2026-05-26 L3: persist initial state so a restart mid-batch
        # leaves a trail (cancelled-by-restart on next startup).
        self._persist(batch_id)
        thread = threading.Thread(
            target=self._run, args=(batch_id,), daemon=True,
        )
        thread.start()
        return {"batch_id": batch_id, "total": len(items), "status": "running"}

    def get(self, batch_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._batches.get(batch_id)
            if state is None:
                return None
            # Shallow copy so caller can't mutate the live dict.
            return {**state, "items": [dict(i) for i in state["items"]]}

    def cancel(self, batch_id: str) -> bool:
        """Request graceful cancellation. The in-progress analyzer call
        can't be interrupted mid-item (it's an in-process monkey-patched
        run), so cancel takes effect at the NEXT item boundary. Remaining
        pending items flip to status=cancelled + batch status=cancelled.
        """
        with self._lock:
            state = self._batches.get(batch_id)
            if state is None:
                return False
            if state["status"] in ("completed", "partial", "failed", "cancelled"):
                return False
            state["_cancel_requested"] = True
        # 2026-05-26 L3: persist the cancel-requested intent so a
        # restart while still draining lands as cancelled at recovery.
        self._persist(batch_id)
        return True

    def _set_item(self, batch_id: str, idx: int, patch: dict[str, Any]) -> None:
        with self._lock:
            state = self._batches.get(batch_id)
            if state is None:
                return
            state["items"][idx].update(patch)
        # 2026-05-26 L3: persist after every item-status mutation so the
        # SQLite row stays in sync. Frequency is bounded (1 per item
        # finalize + 1 per "running" transition; not per chunk_progress
        # — those don't pass through _set_item).
        self._persist(batch_id)

    def _run(self, batch_id: str) -> None:
        # Phase 2 (D9 site #1): the coarse ops mutex ("batch_generate_report")
        # is removed.  Per-item GENERATING locks in the registry replace it.
        # The per-item locks are acquired inside _prepare_batch_gen_item_wrapper
        # and released inside _finalize_batch_gen_item_wrapper (D7).

        # Import locally — multiprocessing / concurrent.futures top-level
        # imports would pull all of stdlib into every reload cycle.
        import multiprocessing as _mp
        from concurrent.futures import ProcessPoolExecutor, as_completed

        # Discover the worker module's import path (file next to app.py).
        from ._batch_gen_worker import (  # noqa: PLC0415
            _pool_worker_init, run_analyzer_job,
        )

        with self._lock:
            state = self._batches.get(batch_id)
            if state is None:
                return
            state["status"] = "running"
            items_snapshot = list(state["items"])

        # Phase A — prepare each item in the parent thread (DB row,
        # output dir, chunk discovery). Failures here mark the item
        # without a worker submission.
        prepared: list[tuple[int, dict[str, Any]]] = []
        for idx, item in enumerate(items_snapshot):
            # Cancel check before preparing — avoids a half-created
            # run row when operator hits Stop during prep.
            with self._lock:
                state = self._batches.get(batch_id)
                if state is not None and state.get("_cancel_requested"):
                    break
            try:
                pre = self._prepare_fn(item["machine"], item["mode"])
                prepared.append((idx, pre))
                self._set_item(batch_id, idx, {
                    "status": "running",
                    "run_id": pre.get("run_id"),
                })
            except HTTPException as exc:
                self._set_item(batch_id, idx, {
                    "status": "failed",
                    "error": str(exc.detail),
                })
                with self._lock:
                    st2 = self._batches.get(batch_id)
                    if st2 is not None:
                        st2["failed"] += 1
                        st2["pending"] -= 1
            except Exception as exc:  # noqa: BLE001
                self._set_item(batch_id, idx, {
                    "status": "failed",
                    "error": f"{exc.__class__.__name__}: {exc}",
                })
                with self._lock:
                    st2 = self._batches.get(batch_id)
                    if st2 is not None:
                        st2["failed"] += 1
                        st2["pending"] -= 1

        # Phase B — spin up the pool + submit all prepared jobs.
        # Workers run analyzer.main() in their own process; parent
        # reads each job's summary.json from disk after completion.
        if prepared:
            ctx = _mp.get_context("spawn")  # portable across POSIX/Windows
            with ProcessPoolExecutor(
                max_workers=self._concurrency,
                mp_context=ctx,
                initializer=_pool_worker_init,
                initargs=(self._root_path,),
            ) as pool:
                futures: dict = {}
                for idx, pre in prepared:
                    fut = pool.submit(run_analyzer_job, pre["job"])
                    futures[fut] = (idx, pre)

                cancelled_submitted = False
                for fut in as_completed(list(futures.keys())):
                    idx, pre = futures[fut]

                    # On first cancel after a result lands, cancel any
                    # still-queued futures (in-flight ones finish).
                    with self._lock:
                        state = self._batches.get(batch_id)
                        want_cancel = bool(
                            state and state.get("_cancel_requested")
                        )
                    if want_cancel and not cancelled_submitted:
                        for other in futures:
                            if other is not fut and not other.done():
                                other.cancel()
                        cancelled_submitted = True

                    # Process this future's result.
                    try:
                        result = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        self._set_item(batch_id, idx, {
                            "status": "failed",
                            "error": f"{exc.__class__.__name__}: {exc}",
                        })
                        with self._lock:
                            st3 = self._batches.get(batch_id)
                            if st3 is not None:
                                st3["failed"] += 1
                                st3["pending"] -= 1
                        continue

                    if result.get("ok"):
                        try:
                            final = self._finalize_fn(pre, result)
                            self._set_item(batch_id, idx, {
                                "status": "completed",
                                "rtp_point_pct": final.get("rtp_point_pct"),
                                "achieved_halfwidth_pp": final.get("achieved_halfwidth_pp"),
                                "chunks_processed": final.get("chunks_processed"),
                            })
                            with self._lock:
                                st3 = self._batches.get(batch_id)
                                if st3 is not None:
                                    st3["completed"] += 1
                                    st3["pending"] -= 1
                        except Exception as exc:  # noqa: BLE001
                            self._set_item(batch_id, idx, {
                                "status": "failed",
                                "error": f"finalize: {exc}",
                            })
                            with self._lock:
                                st3 = self._batches.get(batch_id)
                                if st3 is not None:
                                    st3["failed"] += 1
                                    st3["pending"] -= 1
                    else:
                        # Worker reported per-item failure. Call
                        # finalize with a failure marker so DB row
                        # flips to status=failed.
                        try:
                            self._finalize_fn(pre, result)
                        except Exception as exc:  # noqa: BLE001
                            # Per memory/feedback_no_silent_swallow.md —
                            # surface diagnostic; GENERATING lock released
                            # by the wrapper's finally regardless.
                            import traceback
                            print(
                                f"[batch-generate-finalize] failed: {exc}",
                                file=sys.stderr,
                            )
                            traceback.print_exc()
                        self._set_item(batch_id, idx, {
                            "status": "failed",
                            "error": str(result.get("error") or "worker failed"),
                        })
                        with self._lock:
                            st3 = self._batches.get(batch_id)
                            if st3 is not None:
                                st3["failed"] += 1
                                st3["pending"] -= 1

        # Phase C — flip any still-pending items to cancelled (can
        # happen if cancel fired during Phase A).
        with self._lock:
            state = self._batches.get(batch_id)
            if state is not None:
                pending_idxs = [
                    i for i, it in enumerate(state["items"])
                    if it["status"] == "pending"
                ]
                if state.get("_cancel_requested") and pending_idxs:
                    for i in pending_idxs:
                        state["items"][i]["status"] = "cancelled"
                        state["items"][i]["error"] = "cancelled by user"
                    state["pending"] = 0
                    state["status"] = "cancelled"
                else:
                    if state.get("_cancel_requested"):
                        state["status"] = "cancelled"
                    elif state["failed"] == 0:
                        state["status"] = "completed"
                    else:
                        state["status"] = "partial"
                state["finished_at"] = utc_now()
        # 2026-05-26 L3: persist the terminal state outside the lock so
        # the SQLite row reflects the true final status + finished_at.
        # Restart recovery filters batches by status IN (pending, running)
        # so this entry will not be re-restored on next __init__.
        self._persist(batch_id)


class BatchRunManager:
    """Orchestrates parallel analyzer runs for multiple machines."""

    def __init__(
        self,
        store: "StateStore",
        run_manager: "RunManager",
        cache_root: Path,
        *,
        state_dir: Path | None = None,
        machines_config: Path | None = None,
        rawdata_root: Path | None = None,
        registry: "CellLockRegistry | None" = None,
        limiter: "ConcurrencyLimiter | None" = None,
    ) -> None:
        self._store = store
        self._run_manager = run_manager
        self._cache_root = cache_root
        # Injected paths (2026-04-20): disk-pressure loop needs the
        # app-scoped settings + locks + rawdata paths. Falls back to
        # module globals for back-compat with callers that don't pass
        # them, but create_app now always wires them explicitly so
        # tests with tmp paths work.
        self._state_dir = state_dir if state_dir is not None else STATE_DIR
        self._settings_path = self._state_dir / "settings.json"
        self._machines_config = (
            machines_config if machines_config is not None else MACHINES_CONFIG
        )
        self._rawdata_root = (
            rawdata_root if rawdata_root is not None else RAWDATA_ROOT
        )
        self._lock = threading.Lock()
        self._batches: dict[str, dict[str, Any]] = {}
        # Phase 2: _busy_keys / _try_acquire_key / _release_key replaced by
        # CellLockRegistry (SAMPLING acquire/release).  The registry is the
        # single source of truth for all (machine, mode) liveness checks.
        # Falls back to a local registry if not injected (back-compat for
        # tests that construct BatchRunManager directly without create_app).
        self._registry: CellLockRegistry = registry if registry is not None else CellLockRegistry()
        # Phase 2 (D2 Blocker 1): ConcurrencyLimiter caps concurrent analyzer
        # subprocesses.  Falls back to a fresh limiter if not injected so
        # tests that construct BatchRunManager directly still work.
        self._limiter: ConcurrencyLimiter = (
            limiter if limiter is not None else ConcurrencyLimiter(n_slots=5, foreground_reserve=2)
        )
        # 2026-05-22 L2: restore non-terminal batches from the batches
        # table — they were running when the console died, so mark
        # them cancelled-by-restart and load them back into memory so
        # the operator can still hit "↻ 继续未完成项" on yesterday's
        # interrupted batch. _restore_persisted_batches walks the
        # store + builds in-memory state dicts; no threads are started.
        self._restore_persisted_batches()

    def _restore_persisted_batches(self) -> None:
        """Read non-terminal batches from the batches SQLite table and
        rehydrate the in-memory ``_batches`` dict so the resume endpoint
        + sampling_status both surface them after a console restart.

        Each restored batch is force-marked status='cancelled' with a
        synthetic event noting the restart. Per-item status comes from
        whatever the last persist captured; items that were 'running'
        at the moment the console died get re-tagged 'cancelled' so the
        resume endpoint's filter (which picks up cancelled / failed /
        pending) treats them as work-to-do. The matching runs-table row
        will have been marked failed by RunManager._recover_orphan_running_runs
        on its own startup pass (which runs before this method via the
        create_app construction order).
        """
        try:
            persisted = self._store.list_batches_by_status(
                ("pending", "running"),
                limit=5000,
                kind="sampling",
            )
        except Exception:
            # batches table doesn't exist yet on a pre-L2 database;
            # nothing to restore. Caller proceeds with an empty dict.
            return
        if not persisted:
            return
        for row in persisted:
            batch_id = str(row.get("batch_id") or "").strip()
            if not batch_id:
                continue
            params = row.get("params") or {}
            items = row.get("items") or []
            events = list(row.get("events") or [])
            # Force any still-running items into cancelled so the A1
            # resume button sees them in the incomplete set.
            for it in items:
                if isinstance(it, dict) and it.get("status") in ("pending", "running"):
                    it["status"] = "cancelled"
                    if not it.get("error"):
                        it["error"] = "cancelled by console restart"
            # Append a restart-marker event so the operator can see
            # in the timeline why the batch ended where it did.
            events.append({
                "ts": utc_now(),
                "level": "warn",
                "text": (
                    "⚠ console 重启,本批次保存的进度仅供续跑参考;"
                    "已完成项保留,未完成项被标记为 cancelled — "
                    "可点 ↻ 继续未完成项 让它们续跑"
                ),
            })
            self._batches[batch_id] = {
                "batch_id": batch_id,
                "status": "cancelled",
                "items": items,
                "events": events,
                "concurrency": int(row.get("concurrency") or 3),
                "params": params,
                "reports_root": str(row.get("reports_root") or "") or None,
                "created_at": str(row.get("created_at") or utc_now()),
                "finished_at": utc_now(),
                "cancel_requested": True,
            }
            # Persist the cancelled-by-restart state back so subsequent
            # reads of the SQLite row reflect the recovery decision.
            self._persist_batch(batch_id)

    def sampling_status(self) -> dict[str, Any]:
        """Snapshot of active batches + which (machine, mode) keys are
        currently being sampled. Used by the frontend on page load to
        recover state after refresh — activeBatchId lives in
        localStorage so polling can resume without spinning up a second
        batch that'd hit the per-key lock."""
        with self._lock:
            active = []
            for batch_id, b in self._batches.items():
                if b.get("status") != "completed":
                    running_items = [
                        it for it in b.get("items", [])
                        if it.get("status") in ("pending", "running")
                    ]
                    if running_items or b.get("status") == "running":
                        active.append({
                            "batch_id": batch_id,
                            "status": b.get("status"),
                            "total": len(b.get("items", [])),
                            "running": len(running_items),
                            "created_at": b.get("created_at"),
                        })
            # Phase 2: read active SAMPLING cells from the registry
            # instead of the old _busy_keys set.
            sampling_cells = self._registry.get_active_cells(CellOperation.SAMPLING)
            return {
                "active_batches": active,
                "busy_keys": [
                    {"machine": m, "mode": mode}
                    for (m, mode) in sorted(sampling_cells)
                ],
            }

    def start_batch(self, req: BatchRunRequest, reports_root: Path | None = None) -> dict[str, Any]:
        batch_id = uuid.uuid4().hex[:12]
        rr = reports_root or REPORTS_ROOT
        # Compute per-item chunk_spin_times if not set.
        items = []
        events: list[dict[str, Any]] = []
        for it in req.items:
            chunk_size = it.chunk_spin_times
            cycle_info = None
            if chunk_size is None:
                cycle_info = _detect_machine_cycle(it.machine, rr)
                chunk_size = cycle_info["recommended_chunk_size"]

            # Check local rawdata — read-only scan. Historical md5
            # chunks are reported via ``mismatch_chunks`` but never
            # deleted here (2026-04-21 semantics rewrite; this was
            # the M1|1 regression path before).
            #
            # P1-B6 R1 fix: pass rawdata_root + machines_config
            # explicitly so virtual-console BatchRunManager instances
            # scan VIRTUAL_RAWDATA_ROOT instead of falling back to the
            # module-global RAWDATA_ROOT (real console tree). Per
            # memory feedback_subprocess_import_suicide_and_module_
            # globals.md — this was a real prod bug surfaced by P1-A1
            # round-2 critic + caught by P1-B6 tester/verifier.
            raw_status = check_rawdata_status(
                it.machine, it.mode,
                rawdata_root=self._rawdata_root,
                machines_config=self._machines_config,
            )
            # Cache routing (simplified 2026-04-17): cache always acts
            # as a resume starting point for user-initiated batch runs.
            # Fuzzy with cache used to be read-only which made the Fuzzy
            # sample hint lie ("约 1M spins" but a 20k-cache run returned
            # in 1s with 12.9pp CI). Resume handles both cases naturally:
            # - cache already exceeds max_chunks/target → loop exits
            #   immediately, same observable behavior as old reuse
            # - cache is smaller than max_chunks → continues sampling up
            #   to the budget; stops at CI target (precise) or max_chunks
            #   (fuzzy).
            # The read-only `--from-cache` flag is still used by
            # batch_generate_reports.py for offline re-analysis; it's
            # just not reachable from /api/batch-run any more.
            target_pp = float(req.target_halfwidth_pp or 0)
            cache_usable = raw_status["usable_chunks"] > 0
            reuse_cache = False  # kept for wire-format stability; unused
            # 2026-04-21 v2: ALWAYS resume-from-cache into rawdata/.
            # Analyzer gets ``--upstream-config-md5`` / ``--upstream-
            # code-md5`` and filters the resume-read to only merge
            # matching-md5 chunks into stats — historical-md5 chunks
            # stay on disk but don't pollute the sample's running
            # totals. New chunks land in rawdata/ with
            # next_chunk_index = max_existing + 1, so they co-exist
            # with historical chunks without collision.
            #
            # Supersedes the earlier v1 (commit 424e4d7) which routed
            # md5-drift samples to cache/<run_id>/ scratch — that lost
            # data on cancel because auto_cleanup_cache rmtree'd the
            # scratch dir. Now cancel preserves both historical AND
            # newly-sampled chunks (chunks live in rawdata/, scratch
            # stays empty). Aligns with "md5 is a tag, not a
            # destruction signal" (f5d8787).
            resume_cache = True

            # Strategy-aware per-item max_chunks. "total" honors the
            # batch-level req.max_chunks as the target total (analyzer
            # resume-from-cache stops when reached, so if cache ≥
            # max_chunks no new sampling happens). "incremental" adds
            # req.max_chunks on top of the existing cache so the
            # operator gets a guaranteed delta even when cache is
            # already large.
            item_max_chunks = req.max_chunks
            if req.sampling_strategy == "incremental":
                item_max_chunks = req.max_chunks + int(raw_status.get("usable_chunks", 0) or 0)

            # Per-item MachineConfig override: explicit string wins;
            # otherwise ``use_local_machine_config=True`` reads the
            # on-disk ``machineconfig/<underlying>Cfg.txt`` file at
            # submit time. If the flag is set but the file is missing
            # we 400 the whole batch — failing fast beats silently
            # sampling against global cfg while the UI claims the
            # override is active.
            item_machine_config = it.machine_config or ""
            if not item_machine_config and it.use_local_machine_config:
                _underlying, cfg_path = _resolve_local_cfg_for_machine(it.machine)
                if cfg_path is None:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"use_local_machine_config=True for "
                            f"{it.machine} but no "
                            f"machineconfig/{_underlying}Cfg.txt file exists"
                        ),
                    )
                item_machine_config = cfg_path.read_text(encoding="utf-8")

            items.append({
                "machine": it.machine,
                "mode": it.mode,
                "chunk_spin_times": chunk_size,
                "status": "pending",
                "run_id": None,
                "cycle_info": cycle_info,
                "rawdata_status": raw_status,
                "reuse_cache": reuse_cache,
                "resume_cache": resume_cache,
                "max_chunks": item_max_chunks,
                # Per-item MachineConfig override (empty str = none).
                # Populated either by explicit machine_config string
                # (legacy path, unused by current UI) or by the
                # use_local_machine_config flag resolving to disk.
                "machine_config": item_machine_config,
            })
            # (Historical-md5 chunks are called out inline with the
            # "fresh start" log below so the operator sees the reason
            # + the reassurance in one event rather than two. See the
            # else-branch emitting "♻ 无法续采" further down.)

            # Bet-mismatch warning: if cached chunks have mixed _bet
            # values or differ from the run's current bet, the CI is
            # still math-valid on per-session ret_x, but the
            # rtp_point_pct (value-weighted) ends up averaging across
            # differently-priced sessions. Usually sub-1% effect, but
            # worth flagging so the operator knows.
            if resume_cache:
                bets_seen = _peek_cache_bets(self._rawdata_root / it.machine / f"mode_{it.mode}")
                current_bet = _DEFAULT_ANALYZER_BET  # 1000 until backend exposes bet
                if bets_seen:
                    if len(bets_seen) > 1 or (current_bet not in bets_seen and len(bets_seen) == 1):
                        events.append({
                            "ts": utc_now(), "level": "warn",
                            "machine": it.machine,
                            "text": (
                                f"⚠ bet 不一致: 缓存里 {sorted(bets_seen)} vs 当前 {current_bet}. "
                                f"session-level CI 仍有效 (ret_x = win/bet 无量纲)，"
                                f"但 RTP = total_win/total_bet 会跨不同单价加权。"
                            ),
                        })
            target_label = "Fuzzy" if target_pp == 0 else f"±{target_pp}pp"
            if item_machine_config:
                # Local-cfg override creates a separate md5 bucket
                # (see _derive_local_cfg_md5). Historical chunks
                # stamped with global/other md5 stay on disk but
                # won't count toward this run's stats — say so
                # loudly so the operator doesn't expect resume reuse.
                local_md5 = _derive_local_cfg_md5(item_machine_config)
                existing_total = (
                    raw_status["usable_chunks"]
                    + raw_status["mismatch_chunks"]
                )
                events.append({
                    "ts": utc_now(), "level": "info",
                    "machine": it.machine,
                    "text": (
                        f"🔧 启用本地 cfg ({local_md5}) → 独立 md5 分桶；"
                        f"磁盘上 {existing_total} 个历史 chunks 保留但不计入本轮；"
                        f"本轮新 chunks 会接在历史编号之后写入，目标 "
                        f"{target_label} (chunk_spin_times={chunk_size})"
                    ),
                })
            elif resume_cache and cache_usable:
                # Existing current-md5 chunks on disk → reuse + continue.
                events.append({
                    "ts": utc_now(), "level": "info",
                    "machine": it.machine,
                    "text": (
                        f"♻ 续采: 复用 {raw_status['usable_chunks']} chunks / "
                        f"{raw_status['total_size_mb']}MB，从下一个 chunk 继续采到 "
                        f"{target_label} (chunk_spin_times={chunk_size})"
                    ),
                })
            elif resume_cache:
                # Dir is empty (or machine brand new). Analyzer starts
                # at chunk_0001, writes directly to rawdata/ via
                # --resume-from-cache pointed at an empty dir — chunks
                # will persist for the next run's resume.
                events.append({
                    "ts": utc_now(), "level": "info",
                    "machine": it.machine,
                    "text": (
                        f"📥 首次 API 采样，直接写入 rawdata/ 目标 "
                        f"{target_label} (chunk_spin_times={chunk_size})"
                    ),
                })
            else:
                # mismatch_chunks > 0: historical-md5 chunks on disk.
                # Fall back to scratch so analyzer stats don't mix old
                # and new md5 data. Chunks stay on disk (rwtree 历史
                # cell); this run's output goes to cache/<run_id>/.
                events.append({
                    "ts": utc_now(), "level": "warn",
                    "machine": it.machine,
                    "text": (
                        f"⚠ 无法续采：本地 {raw_status['mismatch_chunks']} "
                        f"个 chunks 属于历史 md5（保留在磁盘，rwtree "
                        f"「历史」cell 可见/可删），本次走 scratch "
                        f"路径采到 {target_label} "
                        f"(chunk_spin_times={chunk_size})"
                    ),
                })
            if cycle_info and cycle_info["source"] == "collect_detected_no_cycle":
                events.append({
                    "ts": utc_now(), "level": "warn",
                    "machine": it.machine,
                    "text": f"Collect 机制已识别但未确认 cycle 长度，使用保守值 chunk_spin_times={chunk_size}",
                })
            elif cycle_info and cycle_info["source"] == "cycle_peaks":
                events.append({
                    "ts": utc_now(), "level": "info",
                    "machine": it.machine,
                    "text": f"从历史 report 识别 cycle={cycle_info['cycle_length']}, chunk_spin_times={chunk_size}",
                })

        # Disk space check.
        disk = _get_disk_space_info(rr)
        if disk["free_gb"] < 5:
            events.append({
                "ts": utc_now(), "level": "danger",
                "text": f"磁盘剩余空间仅 {disk['free_gb']}GB，建议先清理缓存",
            })

        batch = {
            "batch_id": batch_id,
            "status": "running",
            "items": items,
            "events": events,
            "concurrency": req.concurrency,
            "params": {
                "chunk_spin_times": req.chunk_spin_times,
                "chunk_robot_count": req.chunk_robot_count,
                "batch_concurrency": req.batch_concurrency,
                "max_chunks": req.max_chunks,
                "timeout": req.timeout,
                "target_halfwidth_pp": req.target_halfwidth_pp,
                "auto_cleanup_cache": req.auto_cleanup_cache,
                # Resolve server selection once at batch submit time so
                # every item spawns against the same endpoint, even if
                # configs/servers.json flips mid-batch. Caller's
                # server_id wins; otherwise resolver checks
                # state/console/settings.json operator override →
                # servers.json default_server → first-active.
                "server_id": (
                    req.server_id
                    or _resolve_active_server_id(settings_path=self._settings_path)
                ),
            },
            "reports_root": rr,
            "created_at": utc_now(),
            "cancel_requested": False,
        }
        with self._lock:
            self._batches[batch_id] = batch
        # 2026-05-22 L2: persist initial batch state so a console
        # restart during the sample can find the batch params + items
        # and offer the resume button. The thread will continue
        # persisting on each item finalize + the terminal status flip.
        self._persist_batch(batch_id)

        thread = threading.Thread(target=self._run_batch, args=(batch_id,), daemon=True)
        thread.start()
        return {"batch_id": batch_id, "status": "running", "total": len(items)}

    def _persist_batch(self, batch_id: str) -> None:
        """Snapshot the in-memory batch dict to the batches SQLite
        table. Safe to call from inside or outside the lock; takes
        the lock itself to read a consistent snapshot.

        Called at:
          * start_batch (initial INSERT)
          * each item finalize in _run_one (so we capture per-item
            run_id + status as the run progresses)
          * cancel_batch (records cancel_requested + may persist
            in-flight items as cancelled by the run thread)
          * _run_batch terminal status flip (final state)
        """
        with self._lock:
            b = self._batches.get(batch_id)
            if b is None:
                return
            snapshot = {
                "status": str(b.get("status") or ""),
                "created_at": str(b.get("created_at") or utc_now()),
                "finished_at": b.get("finished_at"),
                "concurrency": int(b.get("concurrency") or 3),
                "params": dict(b.get("params") or {}),
                "items": [dict(it) for it in b.get("items") or []],
                "events": list(b.get("events") or []),
                "reports_root": str(b.get("reports_root") or ""),
            }
        try:
            self._store.upsert_batch(batch_id, **snapshot)
        except Exception:
            # Persistence is best-effort — never let it block the
            # batch's foreground thread. A failed write means the
            # post-restart restore won't see this batch, but the
            # samples themselves still complete because the run
            # records use the (separate) runs table.
            pass

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self._lock:
            b = self._batches.get(batch_id)
            if b is None:
                return None
            completed = sum(1 for it in b["items"] if it["status"] in ("completed", "failed", "cancelled"))
            items_out = []
            for it in b["items"]:
                entry = {
                    "machine": it["machine"],
                    "mode": it["mode"],
                    "chunk_spin_times": it.get("chunk_spin_times"),
                    "status": it["status"],
                    "run_id": it.get("run_id"),
                    "error": it.get("error"),
                    "reuse_cache": bool(it.get("reuse_cache", False)),
                    "resume_cache": bool(it.get("resume_cache", False)),
                    # stop_reason + ci_target_met are set by _run_one
                    # when a run completes. Absent on pending/running
                    # items (hence the get() with None default — don't
                    # invent values). Frontend uses ci_target_met to
                    # decide between ✓ and ⚠ icons.
                    "stop_reason": it.get("stop_reason"),
                    "ci_target_met": it.get("ci_target_met"),
                    "progress": None,
                }
                # Read progress.jsonl unconditionally once a run_id is
                # assigned. Previously this was gated on
                # status == "running", which meant that the instant the
                # item flipped to completed/failed/cancelled the UI lost
                # every per-chunk event — chunk_failed, resume_from_cache,
                # the whole history. That's exactly the data the operator
                # needs to read *after* the run (to see WHY it bailed on
                # upstream_unstable, for instance). The live `progress`
                # snapshot stays gated on running (it's the latest chunk
                # frame; meaningless once the run is done), but the
                # `chunk_events` history is always surfaced.
                if it.get("run_id"):
                    try:
                        row = self._store.get_run(it["run_id"])
                        if row:
                            pf = Path(row.get("progress_file", ""))
                            if pf.exists():
                                events = read_progress_events(pf)
                                if it["status"] == "running":
                                    chunks = [e for e in events if e.get("event") == "chunk_progress"]
                                    if chunks:
                                        latest = chunks[-1]
                                        # Analyzer event key is
                                        # `current_halfwidth_pp`, not
                                        # `halfwidth_pp` — the old key
                                        # was always None which is why
                                        # the UI never showed live CI.
                                        # Both keys accepted for
                                        # backward-compat with any stale
                                        # progress files.
                                        entry["progress"] = {
                                            "chunks_done": latest.get("chunk_index", 0),
                                            "total_spins": latest.get("total_spins", 0),
                                            "current_rtp_pct": latest.get("current_rtp_pct"),
                                            "halfwidth_pp": (
                                                latest.get("current_halfwidth_pp")
                                                if latest.get("current_halfwidth_pp") is not None
                                                else latest.get("halfwidth_pp")
                                            ),
                                            "session_level_halfwidth_pp": latest.get("session_level_halfwidth_pp"),
                                            "chunk_level_halfwidth_pp": latest.get("chunk_level_halfwidth_pp"),
                                        }
                                # Per-chunk event history. Critical
                                # events (chunk_failed / resume_from_cache
                                # / disk_guard_stop / failed) are NEVER
                                # pruned; chunk_progress rotates (last 8).
                                # The earlier version used `merged[-60:]`
                                # which, given enough failures, would
                                # have sliced criticals too — the first
                                # iteration of this fix quietly broke
                                # its own "never pruned" promise. Now
                                # the cap is progress-only.
                                # cache_read_* events added 2026-04-21 so the
                                # long silent "read N existing chunks" phase
                                # at the start of --resume-from-cache runs
                                # (165 chunks = ~80s on M14) stays visible
                                # in the batch log instead of looking stuck.
                                # Aligned with frontend's mergeTimeline CRITICAL
                                # (2026-04-21): backend filter used to drop
                                # ``fetching_chunk`` and ``analyzer_started``,
                                # so a sample against an empty-cache machine
                                # would show last_chunk_event=resume_from_cache
                                # for 30-60s while the analyzer's first
                                # upstream HTTP roundtrip was pending. User
                                # thought "卡住了". Including them here
                                # surfaces the "⇅ 请求 chunk 1…" line
                                # immediately so the operator sees activity.
                                _CRITICAL = {
                                    "chunk_failed", "resume_from_cache",
                                    "disk_guard_stop", "failed",
                                    "analyzer_started", "fetching_chunk",
                                    "adaptive_tune", "circuit_pause",
                                    "cache_read_start", "cache_read_progress",
                                    "cache_read_done", "cache_read_target_met",
                                    # 2026-04-21: bug / in-dev machine bail
                                    # signal — tier-2 non-convergence abort.
                                    "non_convergence_abort",
                                }
                                critical = [e for e in events if e.get("event") in _CRITICAL]
                                progress_evts = [e for e in events if e.get("event") == "chunk_progress"]
                                merged = critical + progress_evts[-8:]
                                merged.sort(key=lambda e: e.get("ts") or "")
                                entry["chunk_events"] = merged
                    except Exception:
                        pass
                items_out.append(entry)
            # 2026-05-22 task A1: surface batch-level params + concurrency
            # to the UI. The resume endpoint reads through here to rebuild
            # a BatchRunRequest for the new batch, and the UI can display
            # "本批参数: chunk_spin_times=10000 robot=2 conc=16 ..." for
            # transparency. Shallow-copy params so caller can't mutate
            # the live dict.
            return {
                "batch_id": b["batch_id"],
                "status": b["status"],
                "total": len(b["items"]),
                "completed": completed,
                "items": items_out,
                "events": list(b.get("events", []))[-100:],
                "created_at": b["created_at"],
                "concurrency": int(b.get("concurrency") or 3),
                "params": dict(b.get("params") or {}),
            }

    def cancel_batch(self, batch_id: str) -> bool:
        with self._lock:
            b = self._batches.get(batch_id)
            if b is None:
                return False
            b["cancel_requested"] = True
            # Kill any running subprocesses for this batch.
            for item in b["items"]:
                if item["status"] == "running" and item.get("run_id"):
                    run_id = item["run_id"]
                    # Write stop flag so analyzer exits gracefully.
                    row = self._store.get_run(run_id)
                    if row:
                        pf = Path(row.get("progress_file", ""))
                        stop_flag = pf.parent / f"{run_id}.stop" if pf.parent.exists() else None
                        if stop_flag:
                            try:
                                stop_flag.write_text("stop", encoding="utf-8")
                            except OSError:
                                pass
                    # Also kill the subprocess tree via ManagedRun in
                    # RunManager. Tree kill (not bare terminate) so the
                    # analyzer's internal worker threads / mid-flight
                    # urllib requests get cleaned up with the parent.
                    with self._run_manager._lock:
                        mr = self._run_manager._running.get(run_id)
                        if mr and mr.process:
                            try:
                                _terminate_process_tree(mr.process)
                            except (OSError, ProcessLookupError) as exc:
                                # Action-level: tree-kill can still fail
                                # (already exited, permission, handle
                                # closed). Stop-flag file already
                                # triggered graceful exit — log for ops
                                # and move on.
                                print(
                                    f"[cancel_batch] terminate_tree({run_id}) failed: "
                                    f"{type(exc).__name__}: {exc}",
                                    flush=True,
                                )
        # 2026-05-22 L2: snapshot cancel_requested so a restart while
        # the batch is still draining lands it as cancelled-by-restart
        # at recovery time (matching the in-flight intent). The
        # _run_one finalize will overwrite per-item status as the
        # running items wind down through stop-flag.
        self._persist_batch(batch_id)
        return True

    def _run_batch(self, batch_id: str) -> None:
        with self._lock:
            batch = self._batches[batch_id]

        items = batch["items"]
        params = batch["params"]
        concurrency = batch["concurrency"]
        reports_root = batch.get("reports_root") or REPORTS_ROOT
        semaphore = threading.Semaphore(concurrency)
        events = batch["events"]

        def _log(level: str, text: str, machine: str | None = None) -> None:
            events.append({
                "ts": utc_now(),
                "level": level,
                "machine": machine,
                "text": text,
            })

        def _run_one(item: dict[str, Any]) -> None:
            if batch.get("cancel_requested"):
                item["status"] = "cancelled"
                _log("info", "采样被取消（队列中）", item["machine"])
                return
            # Phase 2 (D4 + D12): replace _try_acquire_key with registry
            # SAMPLING acquire.  If acquire fails, check whether the
            # existing SAMPLING has the same (config_id, upstream_md5) —
            # if so, return an "attached" response so the caller can poll
            # the existing run instead of failing outright (R9 / INV-6).
            _item_machine = item["machine"]
            _item_mode = int(item["mode"])
            # Determine the upstream md5 for this item (used for attach).
            _item_up_cfg, _item_up_code = _get_machine_md5(
                _item_machine,
                machines_config=self._machines_config,
                mode=_item_mode,
            )
            _item_upstream_md5 = f"{_item_up_cfg or ''}|{_item_up_code or ''}"
            # P3 known limitation: config_id wiring through the sampling path
            # is deferred — update_chunk_entry currently has no config_id
            # parameter, so all chunks are written to the "null" bucket of
            # _chunks.json:by_config_id. The 4-tuple dedup infrastructure
            # (pending_batch_configs + by_config_id inverted index + lazy
            # migration + recovery) is fully in place and tested with the
            # "null" sentinel; connecting the upload→batch→sidecar route is
            # a follow-up. See session_artifacts/_impl/p3/critique_v3 if
            # written, otherwise critique_v2 §2 RISK-1.
            _item_config_id = "null"
            _sampling_info = {
                "config_id": _item_config_id,
                "upstream_md5": _item_upstream_md5,
                # run_id not yet known; will be set after start_run returns.
                "run_id": "",
            }
            if not self._registry.try_acquire_cell(
                _item_machine, _item_mode, CellOperation.SAMPLING,
                info=_sampling_info,
            ):
                # Acquire failed — check attach vs reject (D12).
                existing_info = self._registry.get_active_sampling_info(
                    _item_machine, _item_mode,
                )
                if (
                    existing_info is not None
                    and existing_info.get("config_id") == _item_config_id
                    and existing_info.get("upstream_md5") == _item_upstream_md5
                ):
                    # Same (config_id, upstream_md5) → attach response.
                    item["status"] = "attached"
                    item["attached_to_run_id"] = existing_info.get("run_id") or ""
                    item["error"] = ""
                    _log(
                        "info",
                        (f"附加到已有采样 run {item['attached_to_run_id']!s} "
                         f"({_item_machine} mode {_item_mode})"),
                        _item_machine,
                    )
                else:
                    # Different config → reject.
                    item["status"] = "failed"
                    item["error"] = "another batch is sampling this machine+mode (different config)"
                    _log(
                        "warn",
                        f"跳过：另一个批次正在采样 {_item_machine} mode {_item_mode}（不同 config）",
                        _item_machine,
                    )
                return
            # Phase 2 (D2 Blocker 1): track whether the ConcurrencyLimiter
            # slot was acquired so the finally block can release it.
            # Initialised before semaphore.acquire() so it is always defined
            # in the finally block even if semaphore.acquire() raises.
            _limiter_acquired: bool = False
            semaphore.acquire()
            try:
                # Disk-pressure handling (2026-04-20 round 6 rewrite).
                # Replaces the old "< 2 GB → cancel whole batch" dead-end
                # with: trigger auto-cleanup (frees deletable chunks,
                # respects locked + baseline + in-use carve-outs),
                # retry a few times if still tight, then fail just
                # THIS item (not the batch).
                # Thresholds from env:
                #   SLOT_DISK_LOW_WATER_GB (default 5) — trigger cleanup
                #   SLOT_DISK_TARGET_FREE_GB (default 10) — cleanup goal
                #   SLOT_DISK_HARD_STOP_GB  (default 2) — bail this item
                low_water = float(os.environ.get("SLOT_DISK_LOW_WATER_GB") or 5.0)
                target_free = float(os.environ.get("SLOT_DISK_TARGET_FREE_GB") or 10.0)
                hard_stop = float(os.environ.get("SLOT_DISK_HARD_STOP_GB") or 2.0)
                retention_cur = _load_settings(self._settings_path).get(
                    "min_retention_spins", 100000,
                )
                _wait_attempts = 0
                _max_wait_attempts = int(
                    os.environ.get("SLOT_DISK_WAIT_RETRIES") or 30,
                )  # 30 × 10s = 5 min default
                while True:
                    if batch.get("cancel_requested"):
                        item["status"] = "cancelled"
                        return
                    disk = _get_disk_space_info(reports_root)
                    if disk["free_gb"] >= low_water:
                        break  # plenty of room, proceed
                    # Below low-water → try cleanup.
                    _log(
                        "warn",
                        f"磁盘余量 {disk['free_gb']}GB < {low_water}GB，自动清理…",
                        item["machine"],
                    )
                    summary = _auto_cleanup_for_space(
                        self._rawdata_root, self._machines_config,
                        retention_cur, target_free_gb=target_free,
                        registry=self._registry,
                    )
                    del_gb = summary["deleted_bytes"] / (1024 ** 3)
                    _log(
                        "info",
                        (f"清理完成：删 {summary['deleted_files']} 文件 "
                         f"({del_gb:.2f} GB)，剩 {summary['final_free_gb']} GB "
                         f"(跳过锁定 {len(summary['skipped_locked'])}、使用中 "
                         f"{len(summary['skipped_in_use'])})"),
                        item["machine"],
                    )
                    if summary["final_free_gb"] >= hard_stop:
                        break
                    _wait_attempts += 1
                    if _wait_attempts >= _max_wait_attempts:
                        # Give up on this item — but keep the batch alive.
                        # Other items may still have deletable chunks we
                        # can reclaim when they finish.
                        item["status"] = "failed"
                        item["error"] = f"disk_exhausted (free {summary['final_free_gb']}GB < {hard_stop}GB after cleanup)"
                        _log(
                            "danger",
                            f"磁盘不足且清理无效，跳过此项（已等待 {_wait_attempts} 次）",
                            item["machine"],
                        )
                        return
                    # Wait for another in-flight item to finish +
                    # release its chunks; then retry.
                    _log(
                        "info",
                        f"等待磁盘空间释放… (第 {_wait_attempts} 次)",
                        item["machine"],
                    )
                    time.sleep(10)
                if batch.get("cancel_requested"):
                    item["status"] = "cancelled"
                    return
                item["status"] = "running"
                # Phase 2: SAMPLING is already acquired in the registry
                # before semaphore.acquire().  The old _acquire_in_use
                # call here was a secondary registration in _IN_USE_MODES;
                # CellLockRegistry unifies both — no second call needed.
                # Single routing path (2026-04-21 v2): always
                # --resume-from-cache into rawdata/, with analyzer
                # filtering stats by current upstream md5. New chunks
                # land in rawdata/ alongside historical ones; analyzer
                # only merges matching-md5 into running stats.
                from_cache_dir = ""
                # Use the BatchRunManager's injected rawdata_root, not the
                # module-level RAWDATA_ROOT global. Virtual console
                # (create_app(rawdata_root=slot_designer/rawdata/)) vs
                # real console (rawdata/ at repo root) have different
                # roots; hardcoding the global here made every virtual
                # batch-run target the REAL console's rawdata/ tree,
                # which the virtual analyzer doesn't look at — delegate
                # then found no chunks and exited rc=1 with
                # "summary missing".
                cache_dir_str = str(
                    self._rawdata_root / item["machine"] / f"mode_{item['mode']}"
                )
                resume_from_cache_dir = cache_dir_str
                usable_now = item.get("rawdata_status", {}).get("usable_chunks", 0)
                mismatch_now = item.get("rawdata_status", {}).get("mismatch_chunks", 0)
                up_cfg, up_code = _get_machine_md5(
                    item["machine"], machines_config=self._machines_config,
                    mode=item["mode"],
                )
                if mismatch_now > 0 and usable_now > 0:
                    _log(
                        "info",
                        f"♻ 续采 from {cache_dir_str} "
                        f"({usable_now} 当前 md5 chunks + {mismatch_now} 历史 md5 "
                        f"仅保留不合并, chunk_spin_times={item['chunk_spin_times']})",
                        item["machine"],
                    )
                elif mismatch_now > 0:
                    _log(
                        "info",
                        f"📥 上游 md5 变更，{mismatch_now} 历史 md5 chunks 保留; "
                        f"从 chunk_{mismatch_now + 1} 起以新 md5 采样到 "
                        f"rawdata/ (chunk_spin_times={item['chunk_spin_times']})",
                        item["machine"],
                    )
                elif usable_now > 0:
                    _log(
                        "info",
                        f"♻ 续采 from {cache_dir_str} "
                        f"({usable_now} chunks, chunk_spin_times={item['chunk_spin_times']})",
                        item["machine"],
                    )
                else:
                    _log(
                        "info",
                        f"📥 首次采样，chunks 直接写入 {cache_dir_str} "
                        f"(chunk_spin_times={item['chunk_spin_times']})",
                        item["machine"],
                    )
                req = RunCreateRequest(
                    machine=item["machine"],
                    mode=item["mode"],
                    chunk_spin_times=item["chunk_spin_times"],
                    chunk_robot_count=params["chunk_robot_count"],
                    batch_concurrency=params["batch_concurrency"],
                    # Per-item max_chunks (strategy-aware) falls back
                    # to the batch-level default for back-compat.
                    max_chunks=item.get("max_chunks") or params["max_chunks"],
                    timeout=params["timeout"],
                    target_halfwidth_pp=params["target_halfwidth_pp"],
                    # Server selection: request's server_id wins, else
                    # resolve from servers.json. Empty string still
                    # lets RunManager fall through to SLOT_SPIN_ENDPOINT.
                    server_id=params.get("server_id") or "",
                    from_cache_dir=from_cache_dir,
                    resume_from_cache_dir=resume_from_cache_dir,
                    # Snapshot the upstream md5 at batch-start time so
                    # analyzer can filter historical-md5 chunks from
                    # the stats merge (they stay on disk, just aren't
                    # counted toward the session's running stats).
                    # RunManager.start_run swaps in a
                    # ``localcfg_<hash>`` synthetic when machine_config
                    # is set, so we don't pre-empt it here.
                    upstream_config_md5=up_cfg or "",
                    upstream_code_md5=up_code or "",
                    # Per-item MachineConfig override (focused-machine
                    # flow uploads a JSON file). Empty string = use
                    # server's global cfg, which is the default.
                    machine_config=item.get("machine_config") or "",
                )
                # Phase 2 (D2 Blocker 1): acquire a ConcurrencyLimiter slot
                # BEFORE spawning the analyzer subprocess.  This caps the
                # total number of concurrent analyzer subprocesses across all
                # batches to n_slots=5 (40 upstream connections max).
                # If all slots are busy, we wait up to 30 s and then fail
                # this item (not the whole batch).
                if not self._limiter.acquire("foreground", timeout=30.0):
                    item["status"] = "rate_limited"
                    item["error"] = "Concurrency limit reached; too many analyzer subprocesses running"
                    _log(
                        "warn",
                        f"并发限制：{_item_machine} mode {_item_mode} 等待 30s 仍无空位",
                        _item_machine,
                    )
                    return
                _limiter_acquired = True
                # Phase 3 (D2): write-config-first ordering — record the
                # (batch_run_id, machine, mode, config_id) tuple BEFORE the
                # analyzer subprocess starts so crash recovery can re-associate
                # orphaned chunks with their config_id on next startup.
                try:
                    self._store.insert_pending_batch_config(
                        batch["batch_id"], _item_machine, _item_mode, _item_config_id,
                    )
                except Exception as _pbc_exc:  # noqa: BLE001
                    # Non-fatal: sidecar re-association falls back to "null"
                    # if this row is missing. Log and continue.
                    print(
                        f"[_run_one] insert_pending_batch_config failed "
                        f"({_item_machine} mode {_item_mode}): "
                        f"{type(_pbc_exc).__name__}: {_pbc_exc}",
                        flush=True,
                    )
                result = self._run_manager.start_run(req)
                run_id = result.get("run_id")
                item["run_id"] = run_id
                # Phase 2 (D12): update the registry SAMPLING info with
                # the real run_id now that start_run allocated it.  The
                # attach-response logic reads this to return the existing
                # run_id to a second requester with the same config.
                # IMPORTANT: try_acquire_cell stored a *copy* of _sampling_info
                # (see cell_lock_registry.py:144), so mutating the local dict
                # here does NOT propagate to the registry.  Must use the explicit
                # update_sampling_run_id method (Blocker 2 fix per impl-critic).
                if run_id:
                    self._registry.update_sampling_run_id(
                        _item_machine, _item_mode, str(run_id)
                    )
                self._wait_for_run(run_id)
                # Phase 3 (D2): sidecar is now updated by the subprocess.
                # Clear the pending_batch_config row — crash recovery
                # no longer needs it for this (batch, machine, mode).
                try:
                    self._store.delete_pending_batch_config(
                        batch["batch_id"], _item_machine, _item_mode,
                    )
                except Exception as _dpbc_exc:  # noqa: BLE001
                    print(
                        f"[_run_one] delete_pending_batch_config failed "
                        f"({_item_machine} mode {_item_mode}): "
                        f"{type(_dpbc_exc).__name__}: {_dpbc_exc}",
                        flush=True,
                    )
                row = self._store.get_run(run_id)
                status = (row or {}).get("status", "failed")
                if status == "completed":
                    item["status"] = "completed"
                    rtp = row.get("achieved_rtp_pct")
                    ci = row.get("achieved_halfwidth_pp")
                    rtp_str = f"{rtp:.2f}%" if rtp is not None else "—"
                    ci_str = f"±{ci:.2f}pp" if ci is not None else "(no CI)"
                    # Pull stop_reason + chunk/spin counts from the
                    # summary so the operator sees WHY sampling ended
                    # (e.g. "upstream_unstable:... vs target_ci_reached
                    # vs max_chunks_reached"). Previously the only
                    # signal was the final CI value, which hid whether
                    # the target was met or the run bailed from errors.
                    stop_tail = ""
                    stop_reason = ""
                    target_hw = 0.0
                    try:
                        summary_path = Path(row.get("summary_file", ""))
                        if summary_path.exists():
                            s = json.loads(summary_path.read_text(encoding="utf-8"))
                            sam = s.get("sampling", {})
                            stop_reason = str(sam.get("stop_reason", "") or "")
                            target_hw = float(sam.get("target_halfwidth_pp") or 0.0)
                            n_chunks = sam.get("chunks", 0)
                            n_spins = sam.get("total_spins", 0)
                            dur = sam.get("duration_seconds", 0)
                            stop_tail = (
                                f" · stop={stop_reason or '?'} · chunks={n_chunks} · "
                                f"spins={n_spins:,} · {dur:.0f}s"
                            )
                    except Exception:  # noqa: BLE001
                        pass
                    # ci_target_met distinguishes "run hit its CI goal"
                    # from "run finished with valid data but goal NOT
                    # met" (upstream_unstable, max_chunks_reached on a
                    # precise target, disk_low, etc.). Fuzzy runs route
                    # target=0 through the CLI as 999 to bypass the CI
                    # gate entirely — their success is reaching the
                    # max_chunks budget, so max_chunks_reached +
                    # from_cache_complete count as met.
                    #
                    # Numeric tie-breaker (2026-04-21): even when
                    # stop_reason isn't "target_ci_reached" verbatim,
                    # achieved CI ≤ target means the goal was met.
                    # This covers virtual_analyzer's sim loop breaking
                    # with "target_ci_reached" but then the delegated
                    # real-analyzer --from-cache step overwriting the
                    # summary's stop_reason to "from_cache_complete".
                    # The numeric reality is ground truth; the string
                    # label is just a hint.
                    #
                    # Source-of-truth for the TARGET (not just stop
                    # reason): the runs-table row stores the original
                    # user-specified target (``req.target_halfwidth_pp``
                    # — 5.0pp in the virtual-console bug report).
                    # Summary's ``sampling.target_halfwidth_pp`` is
                    # whatever the analyzer saw on its CLI, which
                    # virtual_analyzer's delegate rewrites to 0.001 to
                    # force the real analyzer to process all chunks
                    # instead of early-stopping. Trusting summary here
                    # would compare achieved=4.42 vs target=0.001 →
                    # False (the bug). Reading row keeps us on the
                    # user's original intent.
                    row_target_hw = float(row.get("target_halfwidth_pp") or 0.0)
                    is_fuzzy = target_hw >= 999.0 or row_target_hw == 0.0
                    ci_target_met = (
                        stop_reason == "target_ci_reached"
                        or (
                            not is_fuzzy
                            and row_target_hw > 0
                            and ci is not None
                            and float(ci) <= row_target_hw
                        )
                        or (
                            is_fuzzy
                            and stop_reason in (
                                "max_chunks_reached", "from_cache_complete",
                            )
                        )
                    )
                    item["stop_reason"] = stop_reason
                    item["ci_target_met"] = ci_target_met
                    # Log level: ok when CI was reached (or fuzzy
                    # completed its budget), warn otherwise. Non-
                    # convergence aborts get a distinct "⛔ 非收敛早退"
                    # prefix + the parsed reason so the operator sees
                    # WHY it bailed without having to read the
                    # stop_reason string.
                    if stop_reason.startswith("non_convergence_abort:"):
                        reason_short = stop_reason.split(":", 1)[1]
                        reason_zh = {
                            "rtp_out_of_band": "RTP 超出合理区间",
                            "projected_budget_exceeded": "预算不足以收敛",
                        }.get(reason_short, reason_short)
                        log_level = "warn"
                        log_prefix = f"⛔ 非收敛早退 · 原因: {reason_zh}"
                    else:
                        log_level = "ok" if ci_target_met else "warn"
                        log_prefix = "完成" if ci_target_met else "完成但未达 CI 目标"
                    _log(
                        log_level,
                        f"{log_prefix} RTP={rtp_str} {ci_str}{stop_tail}",
                        item["machine"],
                    )
                else:
                    item["status"] = "failed"
                    err = (row or {}).get("error_message", "")[:200]
                    item["error"] = err
                    _log("error", f"失败: {err[:80]}", item["machine"])
                # Auto-cleanup chunk cache.
                if params.get("auto_cleanup_cache") and run_id:
                    cache_dir = self._cache_root / run_id
                    if cache_dir.is_dir():
                        shutil.rmtree(cache_dir, ignore_errors=True)
            except Exception as exc:  # noqa: BLE001
                item["status"] = "failed"
                item["error"] = str(exc)[:200]
                _log("error", f"异常: {str(exc)[:80]}", item["machine"])
            finally:
                # Phase 2: release the registry SAMPLING lock BEFORE
                # releasing the semaphore — so any waiting batch item
                # that's polling disk space sees this (m, mode) as
                # available as soon as the analyzer exits.
                self._registry.release_cell(
                    item["machine"], int(item["mode"]), CellOperation.SAMPLING,
                )
                semaphore.release()
                # Phase 2 (D2 Blocker 1): release the ConcurrencyLimiter slot
                # AFTER the semaphore so it is released last.  Only release if
                # we actually acquired it (rate_limited early-return path did
                # not reach the acquire call, so _limiter_acquired stays False).
                if _limiter_acquired:
                    self._limiter.release()
            # 2026-05-22 L2: persist the item's final state. Catches
            # every terminal-status branch above (attached / failed /
            # cancelled / completed) so the SQLite batches row stays
            # in sync without scattering _persist_batch() calls at each
            # `item["status"] = ...` site.
            self._persist_batch(batch_id)

        threads: list[threading.Thread] = []
        for item in items:
            t = threading.Thread(target=_run_one, args=(item,), daemon=True)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        batch["status"] = "completed"
        batch["finished_at"] = utc_now()
        # 2026-05-22 L2: final terminal-state snapshot. Captures the
        # cancelled / completed transition so a restart-recovery scan
        # finds the batch in its true terminal state, not as "running".
        self._persist_batch(batch_id)

    def _wait_for_run(self, run_id: str) -> None:
        """Poll until the run is no longer 'running'."""
        import time
        for _ in range(7200):  # max ~2 hours
            row = self._store.get_run(run_id)
            if row and row.get("status") not in ("running", None):
                return
            time.sleep(1)


# OperationCoordinator DELETED in Phase 2 deploy refactor (2026-05-17).
# All 13 call sites migrated to CellLockRegistry per-cell or global ops.
# See session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md §4.1 R5.


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


def _terminate_process_tree(proc_or_pid: Any, timeout: float = 5.0) -> bool:
    """Terminate a process AND all its descendants.

    `subprocess.Popen.terminate()` kills only the root pid; the analyzer
    spawns its own internal ThreadPoolExecutor workers and (on real
    sampling runs) can have urllib request threads mid-flight. A bare
    terminate leaves those to get cleaned up by the OS only when the
    parent fully exits — on Windows, "已 stop 但 orphan 还跑" is the
    common complaint this helper prevents.

    Windows: delegates to `taskkill /T /F` (built-in tree kill).
    POSIX with psutil: walks `Process.children(recursive=True)`,
      terminates each, waits up to `timeout`, then `kill()` on stragglers.
    POSIX without psutil: falls back to `os.kill(SIGTERM)` on root only
      (children may leak — logs a warning).

    Accepts either a `Popen` instance (reads `.pid`) or an int pid.
    Returns True if the tree-kill attempt was issued; False if the
    pid was invalid or the initial lookup failed.
    """
    pid = int(getattr(proc_or_pid, "pid", proc_or_pid) or 0)
    if pid <= 0:
        return False
    if os.name == "nt":
        # taskkill already implements the tree-kill we want.
        return _terminate_pid_if_running(pid)
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        print(
            f"[terminate_process_tree] psutil not installed; "
            f"falling back to single-pid SIGTERM for {pid} "
            f"— children may leak",
            flush=True,
        )
        return _terminate_pid_if_running(pid)
    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return False
    try:
        children = root.children(recursive=True)
    except psutil.NoSuchProcess:
        children = []
    for child in children:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    try:
        root.terminate()
    except psutil.NoSuchProcess:
        pass
    _, alive = psutil.wait_procs(children + [root], timeout=timeout)
    for straggler in alive:
        try:
            straggler.kill()
        except psutil.NoSuchProcess:
            pass
    return True


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
    # Resolve endpoint at call time via the same logic batch-run uses
    # (servers.json default_server → first active-with-endpoint →
    # SLOT_SPIN_ENDPOINT fallback). Keeps autotune symmetric with
    # actual sampling — when operator flips ``default_server`` to
    # external/internal in the 服务器管理 UI, both paths reroute.
    # Before this, autotune was hard-pinned to the SLOT_SPIN_ENDPOINT
    # constant: when servers.json said "prod" (external) but the
    # constant still pointed at internal LAN, autotune got connection
    # refused while batch-run worked fine — exactly the user-reported
    # 2026-04-25 调参按钮 bug.
    endpoint = get_server_endpoint(_resolve_active_server_id())
    req = urllib.request.Request(
        endpoint,
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
        machines_config: Path | None = None,
        popen_factory: "Callable[[list[str], Path], Any] | None" = None,
        rawdata_root: Path | None = None,
        auto_resume_orphan_runs: bool = True,
    ) -> None:
        self.store = store
        self._analyzer = analyzer if analyzer is not None else ANALYZER
        self._reports_root = reports_root if reports_root is not None else REPORTS_ROOT
        self._cache_root = cache_root if cache_root is not None else CACHE_ROOT
        self._progress_dir = progress_dir if progress_dir is not None else PROGRESS_DIR
        # machines_config is consulted at spawn time to resolve a
        # row's upstream_key (the value passed as MachineName on the
        # /MultiRobotTestSpinVariant payload). Falls back to the
        # module default so non-test callers don't break.
        self._machines_config = (
            machines_config if machines_config is not None else MACHINES_CONFIG
        )
        self._popen_factory = popen_factory if popen_factory is not None else _default_popen_factory
        # 2026-05-22 A2: auto-resume orphan runs needs the rawdata path
        # to build a --resume-from-cache argument. Falls back to module
        # default so tests that construct RunManager directly without
        # create_app keep working.
        self._rawdata_root = (
            rawdata_root if rawdata_root is not None else RAWDATA_ROOT
        )
        self._auto_resume_orphan_runs = bool(auto_resume_orphan_runs)
        self._lock = threading.Lock()
        self._running: dict[str, ManagedRun] = {}
        self._startup_recovery = self._recover_orphan_running_runs()

    def _resolve_upstream_machine_name(self, machine: str) -> str | None:
        """Look up the machine row's ``upstream_key`` field for use
        as ``MachineName`` on the upstream payload. Returns None
        when the row is absent, the field is missing, or it equals
        the machine name (so we don't redundantly pass a flag that
        duplicates --machine). Best-effort — any IO error falls
        through to None and the sampling just uses --machine."""
        try:
            data = json.loads(Path(self._machines_config).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        for row in (data.get("machines") or []):
            if not isinstance(row, dict):
                continue
            if row.get("machine") == machine:
                uk = row.get("upstream_key")
                if isinstance(uk, str) and uk and uk != machine:
                    return uk
                return None
        return None

    def _recover_orphan_running_runs(self) -> dict[str, Any]:
        """Recover ``status=running`` rows after a console restart.

        Every such row corresponds to either:
          a. A subprocess still alive — its PID is captured, terminated
             cleanly so we don't double-spawn on resume.
          b. A subprocess long dead — PID missing or process gone; the
             chunks it wrote to rawdata/ are still on disk (atomic_json_write).

        2026-05-22 A2 task: when ``self._auto_resume_orphan_runs`` is
        True (default), each orphan is re-submitted via
        ``_spawn_resume_for_orphan`` with --resume-from-cache pointed
        at its rawdata directory. The previous run row is still marked
        failed but the error_message records the new run_id so the UI
        can render the chain. False mode preserves the pre-A2 behavior
        ("mark failed, operator manually retriggers") for cases where
        auto-resume would be dangerous (a runaway run causing the
        console to crash repeatedly).
        """
        stale = self.store.list_runs_by_status("running", limit=5000)
        if not stale:
            return {
                "recovered_count": 0,
                "run_ids": [],
                "terminated_pids": [],
                "failed_to_terminate_pids": [],
                "auto_resumed": {},
            }
        recovered_ids: list[str] = []
        terminated_pids: list[int] = []
        failed_to_terminate_pids: list[int] = []
        auto_resumed: dict[str, str] = {}
        for row in stale:
            run_id = str(row.get("run_id", "")).strip()
            if not run_id:
                continue
            pid = _coerce_pid(row.get("process_pid"))
            message_parts = ["run interrupted by console restart"]
            if pid is not None:
                if _terminate_pid_if_running(pid):
                    terminated_pids.append(pid)
                    message_parts.append("stale worker process terminated")
                else:
                    failed_to_terminate_pids.append(pid)
                    message_parts.append("stale worker process may still exist")

            # Try auto-resume first. If it succeeds, the operator gets a
            # fresh run row that continues from the existing chunks. If
            # it fails for any reason (missing required fields,
            # rawdata path gone, start_run raises), fall through to the
            # mark-failed-with-rerun-hint path.
            #
            # 2026-05-26 R1: skip the spawn if the cell is owned by a
            # non-terminal queue (fleet_refresh / sampling batch /
            # generate batch). The queue's own restart-recovery path
            # will handle the resume in a coordinated way — A2
            # spawning here would race + create duplicate orphan runs
            # for the same cell. Leaves the row marked failed so the
            # queue's resume creates the new run cleanly.
            new_run_id: str | None = None
            queue_owner: str | None = None
            if self._auto_resume_orphan_runs:
                machine = (row.get("machine") or "").strip()
                mode_raw = row.get("mode")
                if machine and mode_raw is not None:
                    try:
                        queue_owner = self._is_cell_owned_by_active_queue(
                            machine, int(mode_raw),
                        )
                    except (TypeError, ValueError):
                        queue_owner = None
                if queue_owner is not None:
                    message_parts.append(
                        f"skip auto-resume: owned by {queue_owner}"
                    )
                else:
                    try:
                        new_run_id = self._spawn_resume_for_orphan(row)
                    except Exception as exc:
                        message_parts.append(
                            f"auto-resume failed: {exc.__class__.__name__}: {exc}"
                        )

            if new_run_id:
                auto_resumed[run_id] = new_run_id
                message_parts.append(f"auto-resumed as {new_run_id}")
            else:
                message_parts.append("please rerun if needed")

            self.store.update_run(
                run_id,
                {
                    "status": "failed",
                    "finished_at": utc_now(),
                    "error_message": "; ".join(message_parts),
                },
            )
            recovered_ids.append(run_id)
        return {
            "recovered_count": len(recovered_ids),
            "run_ids": recovered_ids,
            "terminated_pids": terminated_pids,
            "failed_to_terminate_pids": failed_to_terminate_pids,
            "auto_resumed": auto_resumed,
        }

    def _is_cell_owned_by_active_queue(
        self, machine: str, mode: int,
    ) -> str | None:
        """Return a human-readable owner description if ``(machine, mode)``
        is currently held by a non-terminal queue (fleet refresh queue,
        sampling batch, generate batch, or auto-inspect sweep). Returns
        None when no queue is interested — A2 is free to spawn a resume run.

        Used by ``_recover_orphan_running_runs`` (R1, 2026-05-26) to
        avoid racing the queue's own restart-recovery path. The orphan
        is still marked failed; the queue picks up the cell on its own
        resume cycle (operator clicks ↻ 继续未完成项 / fleet refresh
        resume thread / auto-inspect resume thread).

        Pre-L2 / pre-L3 / pre-Phase-4 databases may not have the batches
        table, fleet_refresh_queue, or auto_inspect_sweeps tables;
        sqlite3.OperationalError is swallowed and the check returns
        "no owner found", which preserves the old A2 behavior (spawn anyway).
        """
        # 1. fleet refresh — table has its own indexes so a SQL join
        #    is cheap.
        try:
            with self.store._connect() as conn:
                row = conn.execute(
                    """
                    SELECT q.queue_id FROM fleet_refresh_items i
                    JOIN fleet_refresh_queue q ON q.queue_id = i.queue_id
                    WHERE i.machine = ? AND i.mode = ?
                      AND q.status IN ('pending', 'running')
                    LIMIT 1
                    """,
                    (str(machine), int(mode)),
                ).fetchone()
                if row:
                    return f"fleet_refresh queue {row['queue_id']}"
        except sqlite3.OperationalError:
            pass
        # 2. sampling + generate batches — items_json is a TEXT column,
        #    no SQL way to index by content; read each non-terminal
        #    batch's items list and check membership. Bounded by the
        #    number of non-terminal batches (typically 0-3 across both
        #    kinds), so the linear scan is fine.
        try:
            for r in self.store.list_batches_by_status(("pending", "running")):
                for it in r.get("items") or []:
                    if not isinstance(it, dict):
                        continue
                    try:
                        it_machine = str(it.get("machine") or "")
                        it_mode = int(it.get("mode", -1))
                    except (TypeError, ValueError):
                        continue
                    if it_machine == str(machine) and it_mode == int(mode):
                        return f"batch {r.get('batch_id')} (kind={r.get('kind') or 'sampling'})"
        except sqlite3.OperationalError:
            pass
        # 3. auto_inspect_items — new table (Phase 4 / auto-inspect).
        #    A sweep in scanning / sampling / finalizing with a non-terminal
        #    item for this (machine, mode) owns the cell.  OperationalError
        #    is swallowed like the other branches (pre-Phase-4 databases
        #    won't have the table yet).
        try:
            with self.store._connect() as conn:
                row_ai = conn.execute(
                    """
                    SELECT s.sweep_id
                    FROM auto_inspect_items i
                    JOIN auto_inspect_sweeps s ON s.sweep_id = i.sweep_id
                    WHERE i.machine = ? AND i.mode = ?
                      AND s.status IN ('scanning', 'sampling', 'finalizing')
                      AND i.status NOT IN ('completed', 'failed', 'structural_skip',
                                           'convergence_timeout',
                                           'manifest_override_partial',
                                           'md5_drift_invalidated')
                    LIMIT 1
                    """,
                    (str(machine), int(mode)),
                ).fetchone()
                if row_ai:
                    return f"auto-inspect sweep {row_ai['sweep_id']}"
        except sqlite3.OperationalError:
            pass
        return None

    def _spawn_resume_for_orphan(self, row: dict[str, Any]) -> str | None:
        """Reconstruct a RunCreateRequest from a DB row and call
        start_run with --resume-from-cache pointed at the rawdata
        directory for that (machine, mode).

        Returns the new run_id on success, None when the row is missing
        a required field (machine, mode) or when start_run rejects the
        request (cell locked by another in-flight SAMPLING — typically
        means a different orphan for the same cell already won the
        race; that's fine, this one just doesn't resume).
        """
        machine = (row.get("machine") or "").strip()
        mode_raw = row.get("mode")
        if not machine or mode_raw is None:
            return None
        try:
            mode = int(mode_raw)
        except (TypeError, ValueError):
            return None

        rawdata_dir = self._rawdata_root / machine / f"mode_{mode}"

        # Use saved md5 fields so the resume's stats merge only includes
        # chunks whose envelope md5 matches what this run was sampling
        # against originally. Empty strings = no filter (legacy rows).
        req = RunCreateRequest(
            machine=machine,
            mode=mode,
            target_halfwidth_pp=float(row.get("target_halfwidth_pp") or 0.5),
            chunk_spin_times=int(row.get("chunk_spin_times") or 10000),
            chunk_robot_count=int(row.get("chunk_robot_count") or 8),
            batch_concurrency=int(row.get("batch_concurrency") or 8),
            max_chunks=int(row.get("max_chunks") or 120),
            timeout=float(row.get("timeout") or 60.0),
            bankruptcy_session_spins=int(row.get("bankruptcy_session_spins") or 10000),
            bankruptcy_bankroll_multipliers=str(
                row.get("bankruptcy_bankroll_multipliers") or "10,100,200,500"
            ),
            model_id=str(row.get("model_id") or "gpt-5.4-mini"),
            resume_from_cache_dir=str(rawdata_dir),
            upstream_config_md5=str(row.get("rawdata_config_md5") or ""),
            upstream_code_md5=str(row.get("rawdata_code_md5") or ""),
            # server_id intentionally empty — the resolver picks the
            # current default at start_run time. If the operator
            # flipped servers between the crash and the restart, we
            # trust the post-restart choice.
            server_id="",
        )
        try:
            result = self.start_run(req)
        except HTTPException:
            # Cell locked (another orphan already winning the race, or
            # an unrelated SAMPLING in flight). Skip this one; the
            # outer caller logs "auto-resume failed" into error_message.
            return None
        return str(result.get("run_id") or "") or None

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
        # Chunk cache CLI arg (legacy). The analyzer's resume-from-cache
        # path overrides this to the RAWDATA_ROOT location at runtime
        # so new chunks land in the canonical rawdata tree, not here.
        # Kept for the fresh-sample path (no resume) which would still
        # write here — but generate-report (Commit 3) reads directly
        # from rawdata, so this tree's only role is transient scratch
        # for the first-ever sample on a machine.
        chunk_cache_dir = self._cache_root / run_id
        cmd.extend(["--chunk-cache-dir", str(chunk_cache_dir)])
        # Server-specific endpoint URL.
        if req.server_id:
            endpoint = get_server_endpoint(req.server_id)
            cmd.extend(["--endpoint-url", endpoint])
        # From-cache mode: reuse existing chunks, skip API sampling.
        if req.from_cache_dir:
            cmd.extend(["--from-cache", req.from_cache_dir])
        # Resume-from-cache mode: seed state from existing chunks, then
        # continue live sampling into the same dir until CI target hits.
        # Mutually exclusive with from_cache_dir (analyzer enforces it).
        if req.resume_from_cache_dir:
            cmd.extend(["--resume-from-cache", req.resume_from_cache_dir])
        # Upstream md5 snapshot — tells analyzer which envelope md5 to
        # count toward session stats during the resume-read. Chunks
        # with other md5 (historical generations) stay on disk but
        # skip the stats merge. Empty strings (back-compat) = no
        # filter, merge everything.
        #
        # Defensive override: if this run carries a MachineConfig
        # per-request override, the upstream /MachineConfigMd5
        # endpoint's global md5 is WRONG for filtering (upstream has
        # no idea the request is overriding cfg). Swap in a content-
        # derived synthetic so chunks land in their own version
        # bucket. BatchRunManager already does this, but do it again
        # here so /api/runs direct callers can't accidentally bypass.
        effective_cfg_md5 = req.upstream_config_md5
        if getattr(req, "machine_config", ""):
            effective_cfg_md5 = _derive_local_cfg_md5(req.machine_config)
        if effective_cfg_md5:
            cmd.extend(["--upstream-config-md5", effective_cfg_md5])
        if req.upstream_code_md5:
            cmd.extend(["--upstream-code-md5", req.upstream_code_md5])
        # Variant routing: for rows whose upstream_key differs from
        # the display machine name (all 166 variant rows), forward
        # the bare upstream key to analyzer so its payload's
        # MachineName field routes correctly through the Variant
        # endpoint. Non-variant rows omit the flag — analyzer
        # defaults MachineName to --machine.
        upstream_machine_name = self._resolve_upstream_machine_name(req.machine)
        if upstream_machine_name:
            cmd.extend(["--upstream-machine-name", upstream_machine_name])

        # Per-run MachineConfig override: persist to a sibling file in
        # output_dir so the analyzer subprocess can read it at startup
        # without inheriting it over the command line (configs can be
        # 10s of KB). File survives alongside the run so later forensic
        # work can see exactly which cfg was tested.
        if getattr(req, "machine_config", ""):
            cfg_path = output_dir / "machine_config.json"
            cfg_path.write_text(req.machine_config, encoding="utf-8")
            cmd.extend(["--machine-config-file", str(cfg_path)])

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
        # Version fingerprints let run-history flag stale reports without
        # re-reading summary.json on every list. Three dimensions:
        #   rawdata_config_md5 / rawdata_code_md5 = server-side machine
        #     version captured at sampling time (fresh iff matches
        #     machines.json current). Stale → resample required.
        #   analyzer_version = local analyzer source hash at report-
        #     generation time (fresh iff matches current Python code).
        #     Stale → regenerate from rawdata via the new Part A path.
        rawdata_config_md5 = summary.get("config_md5")
        rawdata_code_md5 = summary.get("code_md5")
        analyzer_version = summary.get("analyzer_version")
        # Phase 3 item 4: effective_analyzer_version is the per-(machine,
        # mode) hash that invalidates only machines actually using the
        # changed feature(s). Lives alongside the legacy analyzer_version
        # field (which hashes the analyzer source only — not per-machine).
        # When PIA's summary writer ships the new field (deferred to a
        # later commit; see ticket 09_phase3_manifest_bootstrap notes),
        # this code picks it up automatically. Until then the value is
        # None and old run rows render with empty-string in the index.
        effective_analyzer_version = summary.get("effective_analyzer_version")
        total_spins = summary.get("sampling", {}).get("total_spins")
        item = {
            "report_version": managed.report_version,
            "run_id": managed.run_id,
            "created_at": utc_now(),
            "summary_file": str(managed.summary_file),
            "report_file": str(managed.report_file),
            "rtp_point_pct": rtp_point_pct,
            # Keep both legacy (rtp_point_pct) and frontend-expected
            # (achieved_*) keys so the version-history table can
            # render RTP / CI / Spins without re-reading summary.json
            # per row.
            "achieved_rtp_pct": rtp_point_pct,
            "achieved_halfwidth_pp": achieved_hw_pp,
            "total_spins": total_spins,
            "quality_label": quality_label,
            # 2026-04-26: stamp rawdata md5 onto the index row so the
            # /api/reports/{m}/{n} endpoint can filter by rawdata
            # version WITHOUT re-opening every summary file. Reports
            # generated before this commit have no md5 here; the
            # endpoint treats "missing" as "untagged" so old reports
            # neither leak into a current-md5 view nor disappear from
            # an "include_historical=true" view.
            "rawdata_config_md5": rawdata_config_md5 or "",
            "rawdata_code_md5": rawdata_code_md5 or "",
            "analyzer_version": analyzer_version or "",
            "effective_analyzer_version": effective_analyzer_version or "",
        }
        index_payload.append(item)
        # Phase 1 deploy: atomic + per-file-locked
        atomic_json_write(index_path, index_payload)
        atomic_json_write(latest_path, item)
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
        if rawdata_config_md5:
            patch["rawdata_config_md5"] = str(rawdata_config_md5)
        if rawdata_code_md5:
            patch["rawdata_code_md5"] = str(rawdata_code_md5)
        if analyzer_version:
            patch["analyzer_version"] = str(analyzer_version)
        if effective_analyzer_version:
            patch["effective_analyzer_version"] = str(effective_analyzer_version)
        if total_spins is not None:
            patch["total_spins"] = int(total_spins)
        if patch:
            self.store.update_run(managed.run_id, patch)

    def get_run_with_progress(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        progress_events = read_progress_events(Path(run["progress_file"]))
        run["progress"] = summarize_progress(progress_events)
        return run

    def list_runs(self, limit: int = 2000) -> list[dict[str, Any]]:
        rows = self.store.list_runs(limit=limit)
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
            # than a stuck run. Tree-kill so analyzer's worker threads /
            # urllib handles go with the parent.
            _terminate_process_tree(managed.process)
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
                        # Phase 1 deploy: atomic + per-file-locked (parallel to
                        # _update_report_index at app.py:5090). Closes the
                        # delete_run race: concurrent finalize + delete could
                        # otherwise both read the same index baseline and one
                        # would overwrite the other's update (Scenario 16).
                        atomic_json_write(index_path, filtered)
                        # latest.json rolls back to the newest remaining
                        # item (list is append-ordered); if we just drained
                        # the last version, clear latest too.
                        if filtered:
                            atomic_json_write(latest_path, filtered[-1])
                        elif latest_path.exists():
                            latest_path.unlink()
                except (OSError, json.JSONDecodeError, TypeError):
                    # Data-level: index/latest manifest malformed or
                    # unwritable. Run row still gets deleted below;
                    # stale index entry at worst shows a dangling
                    # version in 运行历史 until next write.
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
    registry: CellLockRegistry,
    state_dir: Path | None = None,
) -> dict[str, Any]:
    """Build the GET /api/system-state response.

    Phase 2 (D13): includes registry.snapshot() as ``concurrency`` field,
    replacing the old OperationCoordinator single-flag fields.

    Phase 3 / B3 fix: reads diagnostic JSON files from ``state_dir`` and
    surfaces them as ``md5_refresh_error``, ``stale_tag_error``, and
    ``reassociate_error`` fields.  Each is ``None`` when the corresponding
    file does not exist.  The /api/health endpoint does NOT include these
    fields (health is a thin liveness probe).
    """
    def _read_diag(path: Path) -> Any:
        """Return parsed JSON from path, or None if absent/unreadable."""
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    md5_refresh_error: Any = None
    stale_tag_error: Any = None
    reassociate_error: Any = None
    if state_dir is not None:
        md5_refresh_error = _read_diag(state_dir / "md5_refresh_error.json")
        stale_tag_error = _read_diag(state_dir / "stale_tag_error.json")
        reassociate_error = _read_diag(state_dir / "reassociate_error.json")

    running = store.list_runs_by_status("running", limit=2000)
    return {
        "ts": utc_now(),
        "app_started_at": APP_STARTED_AT,
        # Phase 2: operation_busy / operation_name / operation_since removed;
        # callers should read concurrency.cells + concurrency.global_ops instead.
        # Backward-compat shim: if any global op is active, surface it here
        # so older frontends that read operation_busy still get a signal.
        "operation_busy": bool(registry.snapshot()["global_ops"]),
        "operation_name": (registry.snapshot()["global_ops"] or [""])[0],
        "operation_since": "",
        "running_runs_count": len(running),
        "running_run_ids": [str(r.get("run_id", "")) for r in running if r.get("run_id")],
        "in_memory_running_count": manager.running_count(),
        "startup_recovery": manager.startup_recovery_snapshot(),
        # Phase 2 (D13): full concurrency registry snapshot.
        "concurrency": registry.snapshot(),
        # B3 fix: diagnostic files from state_dir (None when file absent).
        "md5_refresh_error": md5_refresh_error,
        "stale_tag_error": stale_tag_error,
        "reassociate_error": reassociate_error,
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


# ── MD5 refresh thread — testable error-persistence helpers ──────────────────
# Extracted to module level so impl-tester can monkeypatch _do_refresh_machines_md5
# and assert disk state without going through the full FastAPI TestClient.
# Motivation: feedback_no_silent_swallow.md — the closure in start_batch_run
# had an untestable inner OSError swallow; these helpers are each independently
# exercisable. (Phase 1 fix, retroactive impl-critic item Fix 4.)


def _md5_refresh_error_path(state_dir: Path) -> Path:
    """State path for the persistent MD5 refresh error diagnostic."""
    return state_dir / "md5_refresh_error.json"


def _persist_md5_refresh_error(
    state_dir: Path, server_id: str, exc: BaseException
) -> None:
    """Write diagnostic to disk per memory/feedback_no_silent_swallow.md.

    Last-resort fallback: if the disk write fails, write to stderr — never
    silently swallow the diagnostic-write failure (no infinite recursion of
    logging because stderr is always available).

    **Concurrency note (single-user deploy)**: this helper uses raw
    ``write_text`` (not ``atomic_json_write``) because the deploy target
    is single-machine Windows with a small number of planners
    (see ``memory/project_internal_deploy_intent.md``). Under genuinely
    concurrent calls (e.g. 10+ daemon threads firing simultaneously), Windows
    may return ``PermissionError`` on contending writers, which falls through
    to the stderr branch above; file ends up with one writer's content
    (no torn writes since ``write_text`` is fd-buffered + ``close()`` flushes
    atomically on most filesystems). For the documented deploy intent this
    is acceptable; if the deploy ever sees high concurrent failure rates,
    migrate to ``atomic_json_write``. Flagged by impl-critic P1-fix review
    2026-05-17 (``session_artifacts/_impl/p1_fix/critique.md`` §3 item 1).
    """
    err_path = _md5_refresh_error_path(state_dir)
    try:
        err_path.parent.mkdir(parents=True, exist_ok=True)
        err_path.write_text(
            json.dumps({
                "ts": utc_now(),
                "server_id": server_id,
                "error": f"{exc.__class__.__name__}: {exc}",
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as inner_exc:
        # Last-resort: stderr. Don't silently swallow per feedback_no_silent_swallow.md.
        print(
            f"[md5-refresh] FAILED to persist error diagnostic: "
            f"{inner_exc.__class__.__name__}: {inner_exc}",
            file=sys.stderr,
        )


def _clear_md5_refresh_error(state_dir: Path) -> None:
    """Clear the persistent diagnostic on success so UI doesn't show stale failure."""
    err_path = _md5_refresh_error_path(state_dir)
    try:
        if err_path.exists():
            err_path.unlink()
    except OSError:
        pass  # Stale file is cosmetic; not worth a diagnostic about a diagnostic.


def create_app(
    state_dir: Path | None = None,
    reports_root: Path | None = None,
    cache_root: Path | None = None,
    machines_config: Path | None = None,
    analyzer_path: Path | None = None,
    classify_dir: Path | None = None,
    rawdata_root: Path | None = None,
    paytables_dir: Path | None = None,
    md5_refresh_override: "Callable[[str], dict[str, Any]] | None" = None,
    # Phase 3 (D12): virtual console passes False to skip fleet refresh endpoints
    # and the FleetRefreshManager daemon thread.  Production default is True.
    fleet_refresh_enabled: bool = True,
    # I5 fix: injectable configs_upload_dir for test isolation + e2e harness.
    # When None, falls back to the module-level CONFIGS_UPLOAD_DIR constant.
    configs_upload_dir: Path | None = None,
) -> FastAPI:
    """Build a FastAPI app with all stateful singletons scoped to this instance.

    Each call constructs its own StateStore, RunManager, CellLockRegistry,
    ConcurrencyLimiter, and RuntimeModelConfig, and registers all routes via
    closures over them.
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
    sc = SERVERS_CONFIG
    az = analyzer_path if analyzer_path is not None else ANALYZER
    cd = classify_dir if classify_dir is not None else CLASSIFY_DIR
    pd_root = paytables_dir if paytables_dir is not None else PAYTABLES_DIR
    rd_root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT
    # Operator settings live next to console.db so they survive restart
    # and follow the same tmp-dir swap in tests.
    settings_path = sd / "settings.json"

    store = StateStore(db_path)
    # Per-app-instance cache state (P1-C1 migration from module globals).
    # Each create_app() call gets its own AppCacheState so multiple
    # concurrent test app instances don't share cache/in-use state.
    app_cache = AppCacheState()

    # Backfill achieved_rtp_pct / achieved_halfwidth_pp from on-disk
    # summary.json for completed rows predating those columns -- quick
    # scan, safe on every startup (no-op once populated).
    store.backfill_rtp_ci_from_summaries()
    # Phase 3 (D2): startup re-association — scan pending_batch_configs for
    # orphaned rows left by a crashed _run_one. For each row, check the
    # sidecar's by_config_id; if the machine+mode's sidecar exists but the
    # config_id bucket doesn't contain the most-recently-written chunks,
    # re-assign them. This is best-effort; failure is non-fatal (chunks stay
    # tagged "null", which is the safe default). Run in a daemon thread so
    # startup isn't blocked by potentially slow sidecar reads.
    def _reassociate_orphaned_configs() -> None:
        try:
            from fresh_slotlab.chunk_index import load_chunks_index, set_chunk_config_id
            pending = store.list_pending_batch_configs()
            if not pending:
                return
            print(
                f"[startup] re-associating {len(pending)} orphaned pending_batch_config rows",
                flush=True,
            )
            for row in pending:
                machine = row["machine"]
                mode = int(row["mode"])
                config_id = row["config_id"]
                if config_id == "null":
                    continue  # nothing useful to re-associate
                mode_dir = rd_root / machine / f"mode_{mode}"
                if not mode_dir.is_dir():
                    continue
                try:
                    idx = load_chunks_index(mode_dir)
                except Exception as _e:  # noqa: BLE001
                    print(
                        f"[startup] load_chunks_index failed {machine}/mode_{mode}: {_e}",
                        flush=True,
                    )
                    continue
                if idx is None:
                    continue
                by_cid = idx.get("by_config_id", {})
                null_bucket = set(by_cid.get("null", []))
                target_bucket = set(by_cid.get(config_id, []))
                # Re-associate chunks that are still in the "null" bucket.
                # This is conservative: only re-assign if there are no chunks
                # already under this config_id (indicating the crash happened
                # before ANY chunk was written and tagged).
                if target_bucket:
                    # At least one chunk already properly tagged — trust it.
                    # Row is effectively done; delete so it doesn't accumulate.
                    try:
                        store.delete_pending_batch_config(
                            row["batch_run_id"], machine, mode,
                        )
                    except Exception as _del_exc:  # noqa: BLE001
                        print(
                            f"[startup] delete_pending_batch_config (already-tagged) "
                            f"failed {machine}/mode_{mode}: {_del_exc!r}",
                            flush=True,
                        )
                    continue
                _reassoc_failures = 0
                for fname in list(null_bucket):
                    try:
                        set_chunk_config_id(mode_dir, fname, config_id)
                    except Exception as _ce:  # noqa: BLE001
                        _reassoc_failures += 1
                        import traceback as _tb
                        print(
                            f"[startup] set_chunk_config_id failed "
                            f"{machine}/mode_{mode}/{fname}: {_ce!r}",
                            file=sys.stderr,
                            flush=True,
                        )
                        _tb.print_exc()
                        # Persist diagnostic per memory/feedback_no_silent_swallow.md.
                        try:
                            _err_path = sd / "reassociate_error.json"
                            _err_path.parent.mkdir(parents=True, exist_ok=True)
                            atomic_json_write(_err_path, {
                                "ts": utc_now(),
                                "chunk_file": str(fname),
                                "machine": machine,
                                "mode": mode,
                                "config_id": config_id,
                                "error": f"{_ce.__class__.__name__}: {_ce}",
                            })
                        except OSError:
                            pass  # last-resort — can't write diagnostic
                # Only delete the pending row when ALL chunks succeeded.
                # If any failed, preserve it for retry on next startup.
                if _reassoc_failures == 0:
                    try:
                        store.delete_pending_batch_config(
                            row["batch_run_id"], machine, mode,
                        )
                    except Exception as _del_exc:  # noqa: BLE001
                        print(
                            f"[startup] delete_pending_batch_config failed "
                            f"{machine}/mode_{mode}: {_del_exc!r}",
                            flush=True,
                        )
        except Exception as _top:  # noqa: BLE001
            import traceback
            print("[startup] _reassociate_orphaned_configs error:", flush=True)
            traceback.print_exc()

    threading.Thread(
        target=_reassociate_orphaned_configs, daemon=True, name="orphan-config-reassoc",
    ).start()
    # Warm the machines-summary cache in a daemon thread so the first
    # page load doesn't block on a fresh 10k+ summary.json scan
    # (observed 11-14s on a fleet with many version iterations). The
    # cache is mtime-invalidated, so any subsequent fleet change rebuilds.
    def _prewarm_machines_summary() -> None:
        try:
            _build_machines_summary(rr, _cs=app_cache)
        except Exception:  # noqa: BLE001 — non-fatal, logged via print
            import traceback
            traceback.print_exc()

    threading.Thread(target=_prewarm_machines_summary, daemon=True).start()
    model_runtime = RuntimeModelConfig(model_config_path)
    # 2026-05-22 A2: read auto-resume preference from settings.json so
    # the operator can flip it without touching code. Default True;
    # set False via PUT /api/settings when a runaway run is crashing
    # the console and you want manual control on restart.
    _startup_settings = _load_settings(settings_path)
    manager = RunManager(
        store,
        analyzer=az,
        reports_root=rr,
        progress_dir=progress_dir,
        cache_root=cr,
        machines_config=mc,
        rawdata_root=rd_root,
        auto_resume_orphan_runs=bool(
            _startup_settings.get("auto_resume_orphan_runs", True)
        ),
    )
    # Phase 2 (D3): construct shared registry + limiter, inject into all managers.
    registry = CellLockRegistry()
    limiter = ConcurrencyLimiter(n_slots=5, foreground_reserve=2)

    batch_mgr = BatchRunManager(
        store, manager, cr,
        state_dir=sd, machines_config=mc, rawdata_root=rd_root,
        registry=registry,
        limiter=limiter,
    )

    app = FastAPI(title="Slot Console API", version="0.1.0")
    # Expose app_cache on app.state so tests and lifespan hooks can access
    # the per-instance cache without passing it through function args.
    # Per brief §3 C5: multi-worker tests inspect app.state.cache_state to
    # confirm two create_app() calls produce independent AppCacheState objects.
    app.state.cache_state = app_cache
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Compute the asset-hash cache-bust token for embedding into
    # ``index.html`` (both /console/ and / serve the same template).
    # Declared early so the console_root route below can use it.
    def _asset_hash_for_console() -> str:
        latest = 0
        for name in ("pure.js", "app.js", "panel_registry.js", "styles.css"):
            p = FRONTEND_DIR / name
            try:
                ts = int(p.stat().st_mtime)
                if ts > latest:
                    latest = ts
            except OSError:
                continue
        return str(latest) if latest else "dev"

    # /console/ and /console must substitute the ASSET_HASH placeholder
    # in index.html so <script>/<link> URLs carry a cache-bust token.
    # Registered BEFORE the StaticFiles mount so FastAPI's explicit
    # route beats the static handler for the root path. The mount
    # continues to serve app.js / pure.js / styles.css directly.
    @app.get("/console/")
    @app.get("/console")
    def console_root() -> Response:
        text = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        return Response(
            content=text.replace("{{ASSET_HASH}}", _asset_hash_for_console()),
            media_type="text/html; charset=utf-8",
        )

    app.mount("/console", StaticFiles(directory=FRONTEND_DIR, html=True), name="console")

    # Expose live singletons on app.state so tests / e2e fixtures can poke them
    # without monkeypatching module globals.
    app.state.store = store
    app.state.manager = manager
    app.state.batch_manager = batch_mgr
    # Phase 2 (D3): registry + limiter replace ops on app.state.
    app.state.registry = registry
    app.state.limiter = limiter
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

    # Compute a cache-bust token from the newest mtime among the
    # served frontend assets. Embedded into ``index.html`` as the
    # ``{{ASSET_HASH}}`` placeholder so <script>/<link> URLs carry
    # ``?v=<token>`` and the browser reliably picks up edits.
    def _asset_hash() -> str:
        latest = 0
        for name in ("pure.js", "app.js", "panel_registry.js", "styles.css"):
            p = FRONTEND_DIR / name
            try:
                ts = int(p.stat().st_mtime)
                if ts > latest:
                    latest = ts
            except OSError:
                continue
        return str(latest) if latest else "dev"

    @app.get("/")
    def root() -> Response:
        text = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        return Response(
            content=text.replace("{{ASSET_HASH}}", _asset_hash()),
            media_type="text/html; charset=utf-8",
        )


    @app.get("/api/health")
    def health() -> dict[str, Any]:
        s = current_system_state(store, manager, registry)
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
        # Phase 2 (D13): returns registry.snapshot() as concurrency field.
        # B3 fix: passes state_dir so diagnostic files are surfaced.
        return current_system_state(store, manager, registry, state_dir=sd)

    @app.get("/api/machines")
    def machines() -> dict[str, Any]:
        return {"machines": load_machines(mc, rr)}

    @app.get("/api/versions/current")
    def versions_current() -> dict[str, Any]:
        """Current server-side + analyzer versions.

        Returned shape (honesty-3 extended):
          {
            "analyzer_version": "<12-char hex>",    # legacy global; kept for back-compat
            "machines": {"<machine>": {"config_md5": ..., "code_md5": ...}},
            "effective_versions": {                  # per-(machine,mode) effective hash
              "<machine>|<mode>": "<12-hex or UNVERIFIABLE>",
              ...
            }
          }

        ``effective_versions`` is populated for the bounded set of
        (machine, mode) pairs that have completed runs — the exact set
        the frontend needs for Run History staleness badges. Machines with
        no manifest (virtual/unregistered) map to the ``UNVERIFIABLE``
        sentinel; the frontend treats those as "untagged" rather than stale.

        ``analyzer_version`` is kept for backward-compat (older cached
        frontends); it is no longer the comparator for staleness decisions
        (honesty-3 cutover). The frontend comparator (versionBadges) now
        uses ``effective_versions``.
        """
        from fresh_slotlab.analyzer.versioning import compute_analyzer_version
        from src.web_console.backend.effective_version_cache import EffectiveVersionCache
        machines_payload: dict[str, dict[str, str]] = {}
        if mc.exists():
            try:
                data = read_json(mc) or {}
                for m in data.get("machines", []):
                    name = m.get("machine")
                    if not name:
                        continue
                    machines_payload[str(name)] = {
                        "config_md5": str(m.get("configSummaryMd5", "")),
                        "code_md5": str(m.get("codeSummaryMd5", "")),
                    }
            except (OSError, json.JSONDecodeError, TypeError):
                # Malformed machines.json → return empty map; frontend
                # degrades to "untagged" badges rather than blank cells.
                pass
        # Build effective_versions for all (machine, mode) pairs that have
        # completed runs. This is the bounded set the frontend needs — not
        # all 393 machines × all modes, just the ones with existing runs.
        # Per-request cache (R-7): base_hash computed once for this call.
        eff_cache = EffectiveVersionCache()
        effective_versions: dict[str, str] = {}
        try:
            completed = store.list_runs_by_status("completed", limit=10000) or []
            seen_pairs: set[tuple[str, int]] = set()
            for row in completed:
                machine = row.get("machine")
                mode = row.get("mode")
                if not machine or mode is None:
                    continue
                pair = (str(machine), int(mode))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                key = f"{machine}|{mode}"
                eff = eff_cache.get(str(machine), int(mode))
                effective_versions[key] = eff
        except FileNotFoundError:
            raise  # broken install — let the endpoint 500 honestly
        except Exception as _exc:  # noqa: BLE001 — DB/index read failure: return partial map
            # Non-fatal: return partial effective_versions map so the frontend
            # degrades gracefully. Log so the operator can investigate.
            print(
                f"[versions/current] effective_versions build failed at "
                f"{machine}|{mode}: {type(_exc).__name__}: {_exc}",
                file=sys.stderr,
            )
        return {
            "analyzer_version": compute_analyzer_version(),
            "machines": machines_payload,
            "effective_versions": effective_versions,
        }

    @app.get("/api/machines/halls")
    def get_machine_halls() -> dict[str, Any]:
        """Return the cached on-map machine ordering for the 按大厅 view.

        Upstream provides two things:
          * localMapMachineCellsJson — the default on-map cell sequence
          * gmMapMachineOrderJson   — per-activity order overrides

        Server-side confirms there's NO actual hall grouping; the
        previous version's "G6 / G10 / Default" buckets came from
        Unity asset-bundle names (MapMachine/{ZONE}/{M}/...) and were
        misinterpreted as halls (2026-04-20 round 3 fix). Now we
        expose the two orderings operators actually care about:

          * ``default_order``       — ordered list of machine IDs in
                                      their default layout
          * ``current_hall_order``  — default_order with currently-
                                      active activity overrides applied
                                      (``InfluenceMachines`` of each
                                      activity promoted to Orders[0];
                                      stable for remaining machines)
          * ``active_activities``   — summaries of currently-active
                                      activities (start/end/orders/
                                      influence_machines/lucky_bonus)
          * ``halls``               — kept as empty dict for
                                      back-compat with older clients

        Missing file → empty orderings + prompt to refresh.
        """
        halls_path = ROOT / "configs" / "machine_halls.json"
        if not halls_path.exists():
            return {
                "halls": {}, "default_order": [], "current_hall_order": [],
                "active_activities": [],
                "updated_at": None, "source": None,
            }
        try:
            data = json.loads(halls_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "halls": {}, "default_order": [], "current_hall_order": [],
                "active_activities": [],
                "updated_at": None, "source": None,
                "error": "halls file unreadable",
            }
        # Back-fill from raw_upstream when the file was written under
        # an older schema. Triggers on:
        #   - missing default_order (pre-round-3 format)
        #   - missing club_machines (round-4 added the club/normal
        #     split; earlier round-3 files lack this field)
        #   - missing variants_map (variants round added the map; the
        #     existing raw_upstream may predate the field — in that
        #     case the reparse yields an empty map, which is fine)
        needs_backfill = bool(
            isinstance(data.get("raw_upstream"), dict)
            and (not data.get("default_order")
                 or "club_machines" not in data
                 or "variants_map" not in data)
        )
        if needs_backfill:
            parsed = _parse_upstream_map_order(data["raw_upstream"])
            data.update(parsed)
            try:
                # Phase 1 deploy: atomic + per-file-locked write
                atomic_json_write(halls_path, data)
            except OSError:
                pass
        return {
            "halls": data.get("halls") or {},
            "default_order": data.get("default_order") or [],
            "current_hall_order": data.get("current_hall_order") or [],
            "active_activities": data.get("active_activities") or [],
            "club_machines": data.get("club_machines") or [],
            "variants_map": data.get("variants_map") or {},
            "updated_at": data.get("updated_at"),
            "source": data.get("source"),
        }

    @app.post("/api/machines/halls/refresh")
    def refresh_machine_halls(req: dict[str, Any] | None = None) -> dict[str, Any]:
        """Fetch upstream ``POST /MachineTest/MapMachineOrder`` and
        persist the hall grouping. Operator-triggered only (per the
        no-proactive-fetch rule).

        Request body may carry ``{server_id: ...}`` to pick which
        configured server to query; defaults to the active server.
        Response parsing is best-effort: if upstream shape changes
        we store the raw response for later inspection rather than
        dropping it.
        """
        # Phase 2 (D9 site #13): migrated from ops.acquire to registry global.
        if not registry.try_acquire_global("refresh_halls"):
            raise HTTPException(
                status_code=409,
                detail="refresh_machine_halls already in progress",
            )
        try:
            # Resolve server precedence: caller-specified server_id
            # wins, else fall back to servers.json default_server /
            # first-active. Avoids the SLOT_SPIN_ENDPOINT hardcode
            # silently routing halls-refresh to the wrong server
            # when default_server is non-"dev".
            server_id = (
                (req or {}).get("server_id")
                or _resolve_active_server_id(settings_path=settings_path)
            )
            ep = get_server_endpoint(server_id) if server_id else SLOT_SPIN_ENDPOINT
            endpoint_base = ep.rstrip("/").rsplit("/MachineTest", 1)[0]
            url = f"{endpoint_base}/MachineTest/MapMachineOrder"
            try:
                req_payload = json.dumps({}).encode("utf-8")
                http_req = urllib.request.Request(
                    url, data=req_payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(http_req, timeout=20) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"upstream MapMachineOrder failed: {exc.__class__.__name__}: {exc}",
                ) from exc
            try:
                upstream_payload = json.loads(raw)
            except json.JSONDecodeError:
                upstream_payload = {"_raw": raw[:10000]}
            parsed = _parse_upstream_map_order(upstream_payload)
            halls_path = ROOT / "configs" / "machine_halls.json"
            halls_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                # Kept as empty dict for back-compat with pre-fix
                # clients; new UI reads default_order / current_hall_order.
                "halls": {},
                "default_order": parsed["default_order"],
                "current_hall_order": parsed["current_hall_order"],
                "active_activities": parsed["active_activities"],
                "club_machines": parsed["club_machines"],
                "variants_map": parsed["variants_map"],
                "updated_at": utc_now(),
                "source": url,
                "raw_upstream": upstream_payload,
            }
            # Phase 1 deploy: atomic + per-file-locked write
            atomic_json_write(halls_path, payload)
            return {
                "default_order": parsed["default_order"],
                "current_hall_order": parsed["current_hall_order"],
                "active_activities": parsed["active_activities"],
                "club_machines": parsed["club_machines"],
                "variants_map": parsed["variants_map"],
                "machine_count": len(parsed["default_order"]),
                "club_count": len(parsed["club_machines"]),
                "active_count": len(parsed["active_activities"]),
                "variant_count": len(parsed["variants_map"]),
                "updated_at": payload["updated_at"],
                "source": url,
            }
        finally:
            registry.release_global("refresh_halls")

    @app.get("/api/reports/stale-count")
    def stale_report_count() -> dict[str, Any]:
        """Fleet-wide staleness summary for the run-history banner.

        Scans ``runs`` rows (status=completed) and compares each row's
        stored fingerprints against the current snapshot returned by
        ``/api/versions/current``:

        * ``stale_rawdata`` — chunks were sampled against an older
          server version; report can only be refreshed by re-sampling
          (backend can't fix this locally).
        * ``stale_analyzer`` — report was generated with older analyzer
          code; re-runnable from existing rawdata via batch-generate.
        * ``fixable_items`` — (machine, mode) pairs where analyzer is
          stale AND rawdata is fresh — exactly the set a one-click
          "batch regen" should submit.
        * ``needs_rawdata_items`` — (machine, mode) pairs where analyzer
          is stale AND there is NO usable rawdata cache — cannot be
          auto-fixed; operator must resample first. Honest dead-end
          per R-6 (M275/mode_7 = 0 chunks verified empty-index case).

        De-duplicated by (machine, mode): if 3 runs exist for M14
        mode 1 all with stale analyzer, only one fixable item lands
        (the operator regenerates the mode, not each individual run).

        Honesty-3 (2026-05-29): the analyzer-staleness comparison now
        uses per-(machine, mode) ``effective_analyzer_version`` from the
        row, compared against the current effective computed by
        ``EffectiveVersionCache``. This means editing one machine's
        analysis flags ONLY that machine — not all 393 (the M31 bug).
        Machines with no manifest (virtual/unregistered) are "unverifiable"
        and are never counted stale or fixable (honest).
        """
        from src.web_console.backend.effective_version_cache import EffectiveVersionCache
        # Legacy global hash: kept in the response for display/backward-compat;
        # it NO LONGER drives the stale/fixable decision (honesty-3).
        try:
            from fresh_slotlab.analyzer.versioning import compute_analyzer_version
            cur_analyzer = compute_analyzer_version()
        except Exception:  # noqa: BLE001 — best-effort display only
            cur_analyzer = ""

        cur_machines: dict[str, tuple[str, str]] = {}
        if mc.exists():
            try:
                data = read_json(mc) or {}
                for m in data.get("machines", []):
                    name = m.get("machine")
                    if name:
                        cur_machines[str(name)] = (
                            str(m.get("configSummaryMd5", "")),
                            str(m.get("codeSummaryMd5", "")),
                        )
            except (OSError, json.JSONDecodeError, TypeError):
                pass

        completed = store.list_runs_by_status("completed", limit=10000) or []
        total = len(completed)
        stale_rawdata = 0
        stale_analyzer = 0
        untagged = 0
        # Use sets keyed by (machine, mode) to dedupe across multiple runs.
        fixable_keys: set[tuple[str, int]] = set()
        needs_rawdata_keys: set[tuple[str, int]] = set()
        # Per-request memoized effective-version cache (R-7): one instance
        # for this endpoint invocation. Computes base_hash once; memoizes
        # per-(machine, mode). Avoids O(rows × 25-file-read) I/O storm.
        eff_cache = EffectiveVersionCache()
        for row in completed:
            machine = row.get("machine")
            mode = row.get("mode")
            row_cfg = row.get("rawdata_config_md5") or ""
            row_code = row.get("rawdata_code_md5") or ""
            # Honesty-3: use effective_analyzer_version, not legacy analyzer_version.
            # effective is the per-(machine, mode) hash that changes only when
            # that machine's analysis code changed — the M31-isolation fix.
            row_eff = row.get("effective_analyzer_version") or ""
            if not row_cfg and not row_code and not row_eff:
                untagged += 1
                continue
            cur_cfg, cur_code = cur_machines.get(machine or "", ("", ""))
            # Rawdata staleness: row has fingerprint + doesn't match current
            rawdata_is_stale = bool(
                (row_cfg or row_code)
                and (cur_cfg or cur_code)
                and (row_cfg != cur_cfg or row_code != cur_code)
            )
            # Analyzer staleness: compare row's effective against the current
            # per-(machine, mode) effective. UNVERIFIABLE (no manifest) → NOT
            # stale (can't verify, honest). Empty row_eff → untagged for this
            # dimension (also not counted stale — it's legacy/pre-honesty-3).
            analyzer_is_stale = False
            if row_eff and machine and mode is not None:
                try:
                    cur_eff = eff_cache.get(str(machine), int(mode))
                except FileNotFoundError:
                    # A closure file is missing — broken install. Surface it,
                    # don't swallow (feedback_no_silent_swallow.md). Not caught
                    # here so the endpoint 500s and the operator investigates.
                    raise
                if cur_eff != EffectiveVersionCache.UNVERIFIABLE and cur_eff:
                    analyzer_is_stale = row_eff != cur_eff
            if rawdata_is_stale:
                stale_rawdata += 1
            if analyzer_is_stale:
                stale_analyzer += 1
            # Fixable = analyzer stale AND rawdata fresh (or rawdata
            # unverifiable → treat as fresh enough). Resampling-only
            # cases are NOT fixable by the batch regen button.
            # R-6: if stale AND no usable rawdata → needs_rawdata (not fixable).
            if analyzer_is_stale and not rawdata_is_stale and machine and mode is not None:
                m_int = int(mode)
                # Check whether there is usable rawdata to run the analyzer on.
                # Reuses check_rawdata_status (already defined in this file).
                try:
                    rs = check_rawdata_status(
                        str(machine), m_int, rawdata_root=rd_root, machines_config=mc,
                    )
                    has_rawdata = bool(rs.get("usable_chunks", 0) > 0)
                except Exception as _rdc_exc:  # noqa: BLE001 — rawdata check is best-effort
                    # If status check fails, conservatively treat as has rawdata
                    # so the item lands in fixable (operator can retry).
                    # Log so the operator can investigate the index failure.
                    print(
                        f"[stale-count] check_rawdata_status failed for "
                        f"{machine}|{m_int}: {type(_rdc_exc).__name__}: {_rdc_exc}",
                        file=sys.stderr,
                    )
                    has_rawdata = True
                if has_rawdata:
                    fixable_keys.add((str(machine), m_int))
                else:
                    needs_rawdata_keys.add((str(machine), m_int))
        fixable_items = [
            {"machine": m, "mode": mode} for (m, mode) in sorted(fixable_keys)
        ]
        needs_rawdata_items = [
            {"machine": m, "mode": mode} for (m, mode) in sorted(needs_rawdata_keys)
        ]
        return {
            "total_completed_runs": total,
            "stale_rawdata": stale_rawdata,
            "stale_analyzer": stale_analyzer,
            "untagged": untagged,
            "fixable_items": fixable_items,
            "fixable_count": len(fixable_items),
            "needs_rawdata_items": needs_rawdata_items,
            "needs_rawdata_count": len(needs_rawdata_items),
            "current_analyzer_version": cur_analyzer,
        }

    @app.get("/api/machines/summary")
    def machines_summary() -> dict[str, Any]:
        """Per-machine-mode best-report summary for catalog cards.

        Scans reports/{machine}/mode_{n}/versions/*/player_impact_summary.json,
        picks the report with the smallest CI half-width for each machine-mode,
        and returns RTP / CI / volatility metrics.
        """
        return _build_machines_summary(rr, _cs=app_cache)

    @app.post("/api/batch-run")
    def start_batch_run(req: BatchRunRequest) -> dict[str, Any]:
        if not req.items:
            raise HTTPException(status_code=400, detail="items list is empty")
        # Auto-refresh upstream md5 before deciding cache reuse (2026-04-21).
        # If local machines.json is stale, ``check_rawdata_status``
        # would classify old-md5 chunks as "usable" and
        # ``--resume-from-cache`` would silently reuse them. The
        # refresh pulls current upstream md5 so the classifier sees
        # the right baseline. Best-effort: upstream failures don't
        # block the batch; we fall through to the (possibly stale)
        # local md5. Operator can opt out via ``skip_md5_refresh=True``.
        #
        # Iter 2026-04-23: MachineConfigMd5 upstream call takes
        # ~18s server-side — doing it synchronously blocked
        # POST /api/batch-run for 30-40s (UI would timeout and
        # report "cannot sample"). Moved to a daemon thread: the
        # batch starts immediately with whatever md5 is currently
        # in machines.json; the refresh lands in the background and
        # any md5 drift is reflected on the NEXT batch (or the next
        # operator-triggered /api/machines/refresh-md5 click).
        # Stale-md5 risk is bounded — it only affects chunk
        # classification (historical vs current) at the margin, not
        # sampling correctness, and the explicit "刷新 MD5" button
        # remains synchronous for deterministic operator workflows.
        refresh_triggered = False
        if not req.skip_md5_refresh:
            import threading as _threading
            # Resolve which server to refresh from at submit time —
            # whatever ``default_server`` (or first active) is in
            # servers.json now. Hardcoding "dev" here meant flipping
            # default_server to "prod" via the UI didn't actually
            # reroute the pre-batch md5 refresh.
            _refresh_sid = (
                _resolve_active_server_id(settings_path=settings_path) or "dev"
            )
            def _refresh_md5_async() -> None:
                # Phase 1 deploy: per memory/feedback_no_silent_swallow.md,
                # best-effort background-thread failures must persist a
                # diagnostic to disk so operators can see WHY the refresh
                # didn't land. Picked up by GET /api/system-state
                # md5_refresh_error field (Phase 1 deliverable #11).
                # Phase 1 fix: logic extracted to module-level helpers
                # (_persist_md5_refresh_error / _clear_md5_refresh_error)
                # so impl-tester can exercise each path in isolation without
                # going through the full FastAPI TestClient.
                try:
                    _do_refresh_machines_md5(
                        server_id=_refresh_sid, raise_on_error=False,
                    )
                    # Success — clear any prior error so UI doesn't show
                    # stale failure.
                    _clear_md5_refresh_error(sd)
                except Exception as exc:  # noqa: BLE001
                    _persist_md5_refresh_error(sd, _refresh_sid, exc)
            _threading.Thread(
                target=_refresh_md5_async,
                daemon=True,
                name="pre-batch-md5-refresh",
            ).start()
            refresh_triggered = True
        result = batch_mgr.start_batch(req, rr)
        if refresh_triggered:
            # Observability placeholder (async since be953cb — the
            # refresh's ok/error outcome can't land in the sync
            # response because we return before the thread finishes).
            # Operators polling POST /api/batch-run still see that a
            # refresh WAS triggered; the completed outcome is only
            # observable via the next batch's classifier or the
            # explicit /api/machines/refresh-md5 endpoint.
            result["md5_refresh"] = {"ok": None, "pending": True}
        return result

    @app.get("/api/disk-space")
    def disk_space() -> dict[str, Any]:
        return _get_disk_space_info(rr)

    @app.get("/api/manifests/review-state")
    def manifests_review_state() -> dict[str, Any]:
        """Per-machine manifest review state for the operator UI catalog.

        Returns
        -------
        dict[str, dict]
            ``{machine_id: {verified: bool, reviewed: bool, variant: bool}}``
            where:
            verified — manifest.console_diagnostic_complete is true (SC-Vanilla
              today; grows as reviewers confirm per-machine values).
            reviewed — opposite of _generator_notes.config_not_reviewed. False
              for the 182 bootstrap-default manifests today; true once a
              reviewer opens the manifest and confirms the values.
            variant  — manifest.inherits_from is non-null. Variants inherit
              verified / reviewed state from the parent (eager cascade per
              architecture §5.5.5).

        Synthetic templates (the 26 underlying parents that have no fleet
        membership) are excluded from the response — they are not
        operator-facing machines.

        Best-effort: missing manifest directory returns an empty dict; a
        single malformed manifest is skipped and its machine_id is absent
        from the response (the UI falls back to no-badge for missing
        entries).
        """
        # 5B: flat-manifest layer deleted. Iterate SpinType-native manifests only.
        # Only M15.json (confirmed) lives here; the badge map will contain M15 only.
        # The catalog machine list (from machines.json roster) is NOT affected — that
        # is a separate check. The "broken ⚠ 缺 mode" flag is also independent.
        new_manifests_root = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "configs" / "machine_manifests"
        )
        out: dict[str, dict[str, bool]] = {}
        if not new_manifests_root.exists():
            return out
        for path in sorted(new_manifests_root.iterdir()):
            if not path.is_file() or path.suffix != ".json":
                continue
            try:
                m = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(m, dict):
                continue
            mid = m.get("machine_id")
            if not mid:
                continue
            # SpinType-native manifests use validation.status == "confirmed".
            validation = m.get("validation") or {}
            verified = validation.get("status") == "confirmed"
            # New-schema manifests have no _generator_notes; default reviewed=True.
            notes = m.get("_generator_notes") or {}
            reviewed = not bool(notes.get("config_not_reviewed"))
            # New-schema manifests are non-variant (no inherits_from at top level).
            is_variant = False
            out[mid] = {
                "verified": verified,
                "reviewed": reviewed,
                "variant": is_variant,
            }
        return out

    @app.get("/api/machines/static")
    def machines_static_attrs() -> dict[str, Any]:
        """Per-machine static attrs (category / logicClassNames / features /
        mechanics / md5) — decoupled from report lifecycle so the catalog
        filters survive report deletions. See AppCacheState.static_attrs_cache.

        Response adds a `drift` list of machine names whose cached md5
        differs from the current machines.json — the operator should
        refresh MD5 + regenerate reports for those.
        """
        path = _static_attrs_path(mc)
        data = _load_static_attrs(path)
        if not data.get("machines"):
            data = _bootstrap_static_attrs(rr, mc, path)
        # Compute drift on-the-fly (cheap read of machines.json).
        try:
            mc_data = read_json(mc) or {}
        except Exception:
            mc_data = {}
        cur_md5: dict[str, tuple[str, str]] = {}
        for m_cfg in (mc_data.get("machines") or []):
            name = m_cfg.get("machine")
            if not name:
                continue
            cur_md5[str(name)] = (
                str(m_cfg.get("configSummaryMd5") or ""),
                str(m_cfg.get("codeSummaryMd5") or ""),
            )
        drift = []
        for name, entry in (data.get("machines") or {}).items():
            cur = cur_md5.get(name)
            if not cur:
                continue  # machine no longer in machines.json — ignore
            cached_cfg = str(entry.get("config_md5") or "")
            cached_code = str(entry.get("code_md5") or "")
            # Only flag drift when the cached md5 is set AND differs.
            # An empty cached md5 just means "never stamped" — not drift.
            if cached_cfg and cached_cfg != cur[0]:
                drift.append(name)
            elif cached_code and cached_code != cur[1]:
                drift.append(name)
        # Return a shallow copy so we don't mutate the cached dict.
        out = dict(data)
        out["drift"] = sorted(set(drift))
        return out

    @app.get("/api/rawdata/overview")
    def rawdata_overview() -> dict[str, Any]:
        """Fleet-wide rawdata breakdown for the master/detail dashboard
        banner + the drill-down table. Returns kept/deletable/stale
        bytes per machine + totals. Cached with an mtime fingerprint
        across mode dirs so the operator-visible banner stays cheap
        to refresh."""
        retention = _load_settings(settings_path)["min_retention_spins"]
        return _build_rawdata_overview(rd_root, mc, retention, _cs=app_cache)

    @app.get("/api/machines/{machine}/cfg-availability")
    def get_machine_cfg_availability(machine: str) -> dict[str, Any]:
        """Tell the frontend whether ``machineconfig/<underlying>Cfg.txt``
        exists for the focused machine — if so, UI reveals a
        "use local cfg" checkbox that opts the next sampling run
        into passing the file's content as the upstream
        ``MachineConfig`` field.

        ``underlying`` is resolved via variants_map so all variants
        of the same physical machine share one cfg (operators
        maintain ``M273Cfg.txt`` once, not 11 times for every
        M273 variant)."""
        underlying, path = _resolve_local_cfg_for_machine(machine)
        if path is None:
            return {
                "available": False,
                "machine": machine,
                "underlying": underlying,
                "filename": f"{underlying}Cfg.txt",
                "bytes": 0,
                "mtime_iso": None,
            }
        st = path.stat()
        return {
            "available": True,
            "machine": machine,
            "underlying": underlying,
            "filename": path.name,
            "bytes": st.st_size,
            "mtime_iso": datetime.fromtimestamp(
                st.st_mtime, tz=timezone.utc,
            ).isoformat(),
        }

    @app.get("/api/rawdata/{machine}")
    def get_rawdata_status(machine: str) -> dict[str, Any]:
        """Per-mode rawdata status for a machine.

        Each mode entry carries:
          * legacy MD5 verification (``usable_chunks`` / ``mismatch_chunks``)
          * classification groups (``kept`` / ``deletable`` / ``stale``) so the
            UI can show kept-baseline vs deletable-excess separately
          * per-md5-version breakdown (``versions``) so stale vs current chunks
            group visibly in the rawdata panel
        """
        result = {}
        machine_dir = rd_root / machine
        retention = _load_settings(settings_path)["min_retention_spins"]
        if machine_dir.is_dir():
            for mode_dir in machine_dir.iterdir():
                if not mode_dir.is_dir() or not mode_dir.name.startswith("mode_"):
                    continue
                try:
                    mode = int(mode_dir.name.split("_")[1])
                except (IndexError, ValueError):
                    continue
                status = check_rawdata_status(
                    machine, mode, rawdata_root=rd_root, machines_config=mc,
                )
                classified = _classify_chunks(
                    machine, mode, rd_root, mc, retention,
                )
                # Version-grouped view: bucket chunks by (config_md5,
                # code_md5) so the UI can render "current server
                # version: N chunks / old version: M chunks".
                # Multi-current: any chunk matching ANY pair in
                # ``current_md5_pairs`` is current; each pair also
                # carries a label (服务端 / 本地 cfg) so the UI can
                # distinguish the two "当前" buckets visually.
                by_version: dict[tuple[str, str], dict[str, Any]] = {}
                current_pairs = classified.get("current_md5_pairs") or []
                current_lookup = {
                    (p["cfg_md5"], p["code_md5"]): p
                    for p in current_pairs
                    if p.get("cfg_md5") or p.get("code_md5")
                }
                for group in ("kept", "deletable", "historical"):
                    for entry in classified[group]:
                        key = (entry["config_md5"], entry["code_md5"])
                        pair_info = current_lookup.get(key)
                        v = by_version.setdefault(key, {
                            "config_md5": entry["config_md5"],
                            "code_md5": entry["code_md5"],
                            "is_current": pair_info is not None,
                            "current_label": (pair_info or {}).get("label", ""),
                            "current_source": (pair_info or {}).get("source", ""),
                            "kept_chunks": 0, "deletable_chunks": 0, "historical_chunks": 0,
                            "kept_spins": 0, "deletable_spins": 0, "historical_spins": 0,
                        })
                        v[f"{group}_chunks"] += 1
                        v[f"{group}_spins"] += entry["spins"]
                status["classified"] = {
                    "min_retention_spins": retention,
                    "kept_chunks": len(classified["kept"]),
                    "deletable_chunks": len(classified["deletable"]),
                    "historical_chunks": len(classified["historical"]),
                    "kept_spins": classified["kept_spins"],
                    "deletable_spins": classified["deletable_spins"],
                    "historical_spins": classified["historical_spins"],
                }
                status["versions"] = sorted(
                    by_version.values(),
                    key=lambda v: (not v["is_current"], v["config_md5"], v["code_md5"]),
                )
                # Locked flag — locked (machine, mode) pairs won't be
                # auto-deleted during disk-pressure cleanup. Kept
                # baseline is already safe via retention; lock is the
                # operator's extra carve-out for deletable chunks they
                # want preserved.
                locks = _load_rawdata_locks(_rawdata_locks_path(mc))
                status["locked"] = (machine, mode) in locks
                result[str(mode)] = status
        return {"machine": machine, "modes": result}

    @app.post("/api/rawdata/{machine}/mode/{mode}/lock")
    def lock_rawdata_mode(machine: str, mode: int) -> dict[str, Any]:
        """Mark (machine, mode) rawdata as locked — never auto-deleted.
        Operator-triggered; idempotent (relock is a no-op)."""
        changed = _set_rawdata_lock(_rawdata_locks_path(mc), machine, mode, True)
        return {"ok": True, "machine": machine, "mode": mode,
                "locked": True, "changed": changed}

    @app.delete("/api/rawdata/{machine}/mode/{mode}/lock")
    def unlock_rawdata_mode(machine: str, mode: int) -> dict[str, Any]:
        """Remove the auto-delete protection on (machine, mode).
        Idempotent (unlocking an unlocked entry is a no-op)."""
        changed = _set_rawdata_lock(_rawdata_locks_path(mc), machine, mode, False)
        return {"ok": True, "machine": machine, "mode": mode,
                "locked": False, "changed": changed}

    @app.delete("/api/rawdata/{machine}/mode/{mode}/version")
    def delete_rawdata_version(
        machine: str, mode: int, req: RawdataVersionDeleteRequest,
    ) -> dict[str, Any]:
        """Delete every chunk under (machine, mode) whose envelope md5
        matches the (config_md5, code_md5) pair in the body. Reports
        are untouched — they're analyzer output, not rawdata, and
        operator may still want them for historical comparison.

        Semantics (2026-04-21):
        * Respects the lock — locked (machine, mode) returns 409 and
          the operator must unlock first. Per-version delete is an
          operator-initiated "clean up this specific md5 bucket"
          action; the lock still means "leave this pair alone".
        * Skips running runs on (m, mode) via the in-use snapshot —
          deleting chunks an analyzer is mid-write would corrupt its
          output.
        * Reports are not touched; report rows pointing at the removed
          md5 remain readable (operators can still open old reports).
        * Returns the (m, mode) dir removal if the last chunks got
          wiped; empty parent machine dir is NOT removed (other modes
          may still live there).
        """
        mode_dir = rd_root / machine / f"mode_{mode}"
        if not mode_dir.is_dir():
            raise HTTPException(status_code=404, detail="mode dir not found")

        # Lock gate — per-version delete respects the lock (user
        # choice 2026-04-21). Force=true escape hatch lives on the
        # per-mode endpoint; per-version intentionally doesn't expose
        # one since the granular case for overriding a lock is
        # vanishingly rare.
        locks = _load_rawdata_locks(_rawdata_locks_path(mc))
        if (machine, int(mode)) in locks:
            raise HTTPException(
                status_code=409,
                detail="machine+mode is locked; unlock first if you really want to delete",
            )

        # Phase 2 (D8 Blocker 3): acquire DELETING lock atomically instead of
        # snapshot check.  The old snapshot check was a TOCTOU race — a
        # concurrent SAMPLING could start between the snapshot and the delete.
        # try_acquire_cell(DELETING) returns False if SAMPLING or GENERATING is
        # active (INV-1 + INV-2), atomically under the registry lock.
        if not registry.try_acquire_cell(machine, int(mode), CellOperation.DELETING):
            raise HTTPException(
                status_code=409,
                detail="machine+mode is currently sampling or generating; retry after it finishes",
            )
        try:
            deleted_chunks = 0
            deleted_bytes = 0
            matched_spins = 0
            skipped_chunks = 0
            # Track names of chunks unlinked this call so the per-mode
            # `_chunks.json` sidecar can be patched in a single write at
            # the end — keeps sidecar.mtime ≥ dir.mtime so future reads
            # trust the sidecar instead of rebuilding via glob+peek.
            unlinked_names: list[str] = []
            for p in sorted(mode_dir.glob("chunk_*.json")):
                try:
                    data = _peek_envelope_scalars(p)
                    if data is None:
                        # Full parse fallback — peek can miss tiny chunks.
                        try:
                            data = json.loads(p.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            # Unreadable envelope → not our target, leave
                            # it alone. The per-mode force=true path is
                            # the right tool for that case.
                            skipped_chunks += 1
                            continue
                    cfg = str(data.get("_config_md5", ""))
                    code = str(data.get("_code_md5", ""))
                    if cfg != req.config_md5 or code != req.code_md5:
                        skipped_chunks += 1
                        continue
                    per_robot = int(data.get("_spin_times") or 0)
                    robots = int(data.get("_robot_count") or 0) or 1
                    matched_spins += per_robot * robots
                    size = p.stat().st_size
                    p.unlink()
                    deleted_chunks += 1
                    deleted_bytes += size
                    unlinked_names.append(p.name)
                except OSError:
                    skipped_chunks += 1

            # Refresh the rawdata index so subsequent GET /api/rawdata is
            # consistent without a cold-path rescan.
            try:
                from fresh_slotlab.rawdata_index import update_entry, remove_entry
                from fresh_slotlab.chunk_index import bulk_remove_chunk_entries
                if unlinked_names:
                    bulk_remove_chunk_entries(mode_dir, unlinked_names)
                if any(mode_dir.glob("chunk_*.json")):
                    update_entry(rd_root, machine, mode, mode_dir)
                else:
                    remove_entry(rd_root, machine, mode)
            except Exception as exc:  # noqa: BLE001
                # Per feedback_no_silent_swallow.md: surface sidecar/index
                # update failures so operators can see when cache_cleanup
                # left the indices stale. Not fatal — next read self-heals.
                import traceback
                print(
                    f"[cache-cleanup] sidecar/index update failed for "
                    f"{machine}|{mode}: {exc.__class__.__name__}: {exc}",
                    file=sys.stderr,
                )
                traceback.print_exc()

            # Remove the empty mode dir if nothing's left AND (Commit 2)
            # the caller will then re-check the mode-hide rule on the UI
            # side (mode disappears when no rawdata + no reports remain).
            mode_dir_removed = False
            try:
                if mode_dir.is_dir() and not any(mode_dir.iterdir()):
                    mode_dir.rmdir()
                    mode_dir_removed = True
            except OSError:
                pass

            # Phase 3 (D9): tag reports stale only when this delete
            # empties the mode (last-chunk-removed path per brief D9).
            # INV-7 v2: only tag — reports are NOT deleted here.
            if deleted_chunks > 0 and not any(mode_dir.glob("chunk_*.json")):
                try:
                    _tag_reports_stale(machine, int(mode), rr, store, sd)
                except Exception:
                    pass  # Diagnostic persisted by helper; don't block return.
            return {
                "ok": True,
                "machine": machine,
                "mode": mode,
                "config_md5": req.config_md5,
                "code_md5": req.code_md5,
                "deleted_chunks": deleted_chunks,
                "deleted_bytes": deleted_bytes,
                "deleted_spins": matched_spins,
                "skipped_chunks": skipped_chunks,
                "mode_dir_removed": mode_dir_removed,
            }
        finally:
            registry.release_cell(machine, int(mode), CellOperation.DELETING)

    @app.get("/api/events")
    def unified_events(
        since: str = "",
        lookback_minutes: int = 5,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Unified event feed across all active + recently-completed
        runs. Merges per-run ``progress/*.jsonl`` streams so the top
        log panel can render one stream regardless of which operation
        (sampling / generate-report / batch-regen) produced the event.

        Query params:
          * ``since`` — ISO ts; return only events strictly after.
            Empty = include everything from ``lookback_minutes`` back.
          * ``lookback_minutes`` — how far back to scan for recent
            runs (default 5).
          * ``limit`` — cap total events returned (default 500).

        Returns ``{events: [...], max_ts, active_runs}``. ``max_ts``
        is the newest event ts seen; caller uses it as the next
        ``since``.
        """
        cutoff_ts = ""
        if since:
            cutoff_ts = since
        # Collect candidate runs: anything running + finished recently.
        active = store.list_runs_by_status("running", limit=100) or []
        # Finished runs within lookback — tail their events for context.
        recent_cutoff = datetime.now(timezone.utc).timestamp() - (
            max(lookback_minutes, 0) * 60
        )
        completed_recent: list[dict[str, Any]] = []
        for r in (store.list_runs(limit=50) or []):
            if r.get("status") == "running":
                continue
            fin = r.get("finished_at") or r.get("started_at") or ""
            try:
                fin_ts = datetime.fromisoformat(
                    fin.replace("Z", "+00:00")
                ).timestamp() if fin else 0
            except ValueError:
                fin_ts = 0
            if fin_ts >= recent_cutoff:
                completed_recent.append(r)

        collected: list[dict[str, Any]] = []
        for r in (active + completed_recent):
            pf_str = r.get("progress_file")
            if not pf_str:
                continue
            events = read_progress_events(Path(pf_str))
            for ev in events:
                ev_ts = str(ev.get("ts") or "")
                if cutoff_ts and ev_ts <= cutoff_ts:
                    continue
                collected.append({
                    "ts": ev_ts,
                    "run_id": r.get("run_id"),
                    "machine": r.get("machine"),
                    "mode": r.get("mode"),
                    "model_id": r.get("model_id") or "sampling",
                    "run_status": r.get("status"),
                    "event": ev.get("event"),
                    "chunks_completed": ev.get("chunks_completed"),
                    "total_spins": ev.get("total_spins"),
                    "current_halfwidth_pp": ev.get("current_halfwidth_pp"),
                    "stop_reason": ev.get("stop_reason"),
                    "error_message": ev.get("error_message"),
                    "raw": ev,
                })
        collected.sort(key=lambda e: e["ts"])
        if limit > 0 and len(collected) > limit:
            collected = collected[-limit:]
        max_ts = collected[-1]["ts"] if collected else cutoff_ts
        return {
            "events": collected,
            "max_ts": max_ts,
            "active_runs": [
                {
                    "run_id": r.get("run_id"),
                    "machine": r.get("machine"),
                    "mode": r.get("mode"),
                    "model_id": r.get("model_id") or "sampling",
                    "started_at": r.get("started_at"),
                }
                for r in active
            ],
        }

    @app.delete("/api/rawdata/{machine}")
    def delete_machine_rawdata(
        machine: str,
        mode: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Delete rawdata for a machine (all modes or specific mode).

        ``force=false`` (default) — respects the retention quota: only
        deletable + stale chunks are removed, the kept baseline survives.
        ``force=true`` — nuclear: delete everything at the target path.
        UI exposes force under a separate confirmation-gated button.

        Phase 2 (D8 + D9 site #4): acquires per-mode DELETING lock instead
        of the coarse ops mutex, so concurrent deletes on different cells
        can proceed in parallel while blocking conflicting SAMPLING /
        GENERATING on the same cell.

        Per 07_deploy_decision.md §6 OQ-3: if mode is specified, acquires
        DELETING for that mode only; if mode is None (all modes), enumerates
        dirs and acquires per-mode with abort-and-rollback semantics.
        """
        # Collect modes to lock.
        if mode is not None:
            modes_to_lock = [int(mode)]
        else:
            # All modes: enumerate dirs.
            machine_dir = rd_root / machine
            modes_to_lock = []
            if machine_dir.is_dir():
                for md in machine_dir.iterdir():
                    if md.is_dir() and md.name.startswith("mode_"):
                        try:
                            modes_to_lock.append(int(md.name.split("_", 1)[1]))
                        except (IndexError, ValueError):
                            continue

        # Acquire DELETING for all relevant modes — abort-and-rollback if
        # any fails (per 07_deploy_decision.md §6 OQ-3).
        acquired_modes: list[int] = []
        for m in modes_to_lock:
            if not registry.try_acquire_cell(machine, m, CellOperation.DELETING):
                # Roll back already-acquired modes.
                for am in acquired_modes:
                    registry.release_cell(machine, am, CellOperation.DELETING)
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"cell {machine}|{m} is busy (SAMPLING or GENERATING) — "
                        "retry after the active operation completes"
                    ),
                )
            acquired_modes.append(m)

        try:
            retention = _load_settings(settings_path)["min_retention_spins"]
            result = delete_rawdata(
                machine, mode, rawdata_root=rd_root, machines_config=mc,
                min_retention_spins=retention, force=force,
            )
            # Phase 3 (D9): tag reports stale for each deleted mode.
            # INV-7 v2: only tag — reports are NOT deleted here.
            # Best-effort: if tagging fails, log it but still return success
            # (delete already happened; the helper persists the diagnostic
            # to state/console/stale_tag_error.json and prints to stderr +
            # traceback. Operators discover it via filesystem inspection;
            # /api/system-state does NOT surface this file in P3 — adding
            # that is a follow-up).
            for _stale_mode in modes_to_lock:
                try:
                    _tag_reports_stale(machine, _stale_mode, rr, store, sd)
                except Exception:
                    pass  # Diagnostic already persisted + printed by helper.
            return result
        finally:
            for am in acquired_modes:
                registry.release_cell(machine, am, CellOperation.DELETING)

    @app.delete("/api/machines/{machine}/all-data")
    def delete_machine_all_data(machine: str) -> dict[str, Any]:
        """Wipe ALL rawdata + reports + runs rows for a single machine.

        Catastrophic per-machine reset for the focused-detail panel's
        danger-zone button. Steps:
          1. ``delete_rawdata(machine, mode=None, force=True)`` — nuke
             every mode's chunks + index entries.
          2. ``shutil.rmtree(reports/<machine>)`` — drop every mode's
             versions + index.json + latest.json.
          3. Drop every ``runs`` row whose machine column matches.

        Phase 2 (D8 + D9 site #5): acquires per-mode DELETING lock for
        all modes of this machine. Abort-and-rollback if any mode is busy
        (per 07_deploy_decision.md §6 OQ-3).
        Idempotent: returns ``ok=true`` even when nothing exists for the
        machine.
        """
        # Enumerate all modes currently on disk for this machine.
        # Phase 2 (B2 fix): union disk dirs + registry.get_active_cells() so
        # that in-flight SAMPLING cells (rawdata dir not yet created) are also
        # covered — mirrors the R1 fix in delete_machine_rawdata.
        machine_dir = rd_root / machine
        modes_set_all: set[int] = set()
        if machine_dir.is_dir():
            for md in machine_dir.iterdir():
                if md.is_dir() and md.name.startswith("mode_"):
                    try:
                        modes_set_all.add(int(md.name.split("_", 1)[1]))
                    except (IndexError, ValueError):
                        continue
        # Add any registry-active cells for this machine (pre-chunk race window).
        for cell_machine, cell_mode in registry.get_active_cells():
            if cell_machine == machine:
                modes_set_all.add(cell_mode)
        modes_all: list[int] = list(modes_set_all)

        # Acquire DELETING for all modes — abort-and-rollback if any fails.
        acquired_all_data: list[int] = []
        for m in modes_all:
            if not registry.try_acquire_cell(machine, m, CellOperation.DELETING):
                for am in acquired_all_data:
                    registry.release_cell(machine, am, CellOperation.DELETING)
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"cell {machine}|{m} is busy — retry after active operation completes"
                    ),
                )
            acquired_all_data.append(m)

        try:
            # Refuse if any run for this machine is still running —
            # we'd otherwise yank rawdata/reports out from under a
            # live sample / generate-report.  The DELETING lock above
            # blocks NEW ops but the DB may still hold a row from a
            # run that started before this endpoint acquired the lock.
            machine_runs = [
                r for r in store.list_runs(limit=100000)
                if str(r.get("machine") or "") == machine
            ]
            running = [
                r for r in machine_runs
                if str(r.get("status", "")).lower() == "running"
            ]
            if running:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"机台 {machine} 有 {len(running)} 个运行中的 run，"
                        "请先取消后再清空。"
                    ),
                )

            # Step 1: count chunks BEFORE delete (force=True returns
            # the legacy -1 sentinel — useless for the UI's "deleted N
            # chunks" copy), then nuke. Count is best-effort: if the
            # rawdata dir is missing we fall through with 0.
            machine_rawdata_dir = rd_root / machine
            deleted_chunks = 0
            if machine_rawdata_dir.is_dir():
                deleted_chunks = sum(
                    1 for _ in machine_rawdata_dir.rglob("chunk_*.json")
                )
            delete_rawdata(
                machine, mode=None, rawdata_root=rd_root,
                machines_config=mc, force=True,
            )

            # Step 2: reports tree.
            machine_reports_dir = rr / machine
            deleted_versions = 0
            if machine_reports_dir.is_dir():
                for mode_dir in machine_reports_dir.iterdir():
                    if not mode_dir.is_dir():
                        continue
                    versions_dir = mode_dir / "versions"
                    if versions_dir.is_dir():
                        deleted_versions += sum(
                            1 for v in versions_dir.iterdir() if v.is_dir()
                        )
                shutil.rmtree(machine_reports_dir, ignore_errors=True)

            # Step 3: drop every runs row for this machine. Use the
            # store's own delete_run so cascade children
            # (interpretations) follow consistently — disk artifacts
            # are already gone above, so missing-file errors there
            # are best-effort and don't matter.
            runs_deleted = 0
            for r in machine_runs:
                rid = str(r.get("run_id") or "")
                if not rid:
                    continue
                try:
                    if store.delete_run(rid):
                        runs_deleted += 1
                except Exception as exc:  # noqa: BLE001
                    # Per memory/feedback_no_silent_swallow.md — surface
                    # diagnostic; caller still gets the partial summary.
                    import traceback
                    print(
                        f"[delete-machine-all-data] store.delete_run({rid!r}) failed: {exc}",
                        file=sys.stderr,
                    )
                    traceback.print_exc()

            return {
                "ok": True,
                "machine": machine,
                "deleted_chunks": deleted_chunks,
                "deleted_report_versions": deleted_versions,
                "runs_deleted": runs_deleted,
            }
        finally:
            for am in acquired_all_data:
                registry.release_cell(machine, am, CellOperation.DELETING)

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        """Operator-tunable knobs persisted in state/console/settings.json."""
        return _load_settings(settings_path)

    @app.put("/api/settings")
    def put_settings(req: dict[str, Any]) -> dict[str, Any]:
        """Upsert operator settings. Unknown fields ignored; invalid
        values (e.g. negative retention) clamped by _load_settings
        on next read.

        Accepted keys:
          * min_retention_spins (int >= 0)
          * auto_sweep (dict) — P4 addition.  Merged into the persisted
            auto_sweep block; _load_settings validates the sub-fields on
            next read, so this handler only checks type + persists the
            raw dict (validation is centralised there).
        """
        current = _load_settings(settings_path)
        if "min_retention_spins" in req:
            try:
                v = int(req["min_retention_spins"])
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="min_retention_spins must be a non-negative integer",
                )
            if v < 0:
                raise HTTPException(
                    status_code=400,
                    detail="min_retention_spins must be non-negative",
                )
            current["min_retention_spins"] = v
        # P4: accept auto_sweep block.  Merge incoming dict onto disk so
        # partial updates (e.g. just changing enabled) don't wipe other
        # keys.  _load_settings validates sub-fields on next read.
        if "auto_sweep" in req:
            raw_as = req["auto_sweep"]
            if not isinstance(raw_as, dict):
                raise HTTPException(
                    status_code=400,
                    detail="auto_sweep must be an object",
                )
            existing_as = current.get("auto_sweep") or {}
            if not isinstance(existing_as, dict):
                existing_as = {}
            # Deep-merge: modes dict gets merged per-key so a partial
            # POST doesn't wipe modes that weren't included.
            merged = dict(existing_as)
            merged.update(raw_as)
            if "modes" in raw_as and isinstance(raw_as["modes"], dict):
                existing_modes = dict((existing_as.get("modes") or {}))
                existing_modes.update(raw_as["modes"])
                merged["modes"] = existing_modes
            current["auto_sweep"] = merged
        _save_settings(settings_path, current)
        # Return the validated (parsed) version so the caller gets back
        # the clamped/validated values rather than the raw input.
        return _load_settings(settings_path)

    @app.get("/api/classifier/{machine}")
    def get_classifier_verdict(machine: str) -> dict[str, Any]:
        """Per-mode payline-structure classification + feature-vs-pay_id
        channel split + feature-mode rule delta for a machine. Sourced
        from ``dev_reports/_classify/all_verdicts_mode*.json`` (produced
        by ``scripts/classify_payline_structure.py``). Missing output →
        empty ``modes`` dict, UI renders a "classifier not run" notice.
        """
        return _load_classifier_verdict(machine, cd)

    @app.get("/api/paytables/{machine}/mode/{mode}/shape")
    def get_paytable_shape(machine: str, mode: int) -> dict[str, Any]:
        """Per-pay_id shape + auto-inferred wild symbols for one
        (machine, mode). Sourced from
        ``configs/paytables/{machine}_mode{mode}.json`` produced by
        ``scripts/infer_paytable.py``. Response fields:

          * ``status``: "ok" / "not_run" / "error"
          * ``grid``: {n_cols, n_rows}
          * ``wild_inference``: {status, wilds, evidence, tier_stems,
            review_needed, stem_count}
          * ``rows[]``: per (pay_id, match_count) with ``shape``:
            symbol_set, symbol_purity, wild_substitution_rate,
            line_id_sign, position_cols_covered, position_samples,
            confidence, notes
          * ``machine_flags``: list of self-verify flags
        """
        return _load_paytable_shape(machine, mode, pd_root)

    @app.get("/api/batch-run/{batch_id}")
    def get_batch_run(batch_id: str) -> dict[str, Any]:
        result = batch_mgr.get_batch(batch_id)
        if result is not None:
            return result
        # 2026-05-26 B1: fall back to the persisted batches table so
        # the operator can still inspect a batch that finished a while
        # ago and was never re-loaded into the in-memory _batches dict
        # (restart restore only rehydrates non-terminal kinds, and
        # completed batches GC-out across the next restart). Returns
        # the same shape as get_batch — params + items live in the
        # row's json columns, just need to project them into the
        # response.
        try:
            row = store.get_batch_row(batch_id)
        except sqlite3.OperationalError:
            row = None
        if row is None:
            raise HTTPException(status_code=404, detail="batch not found")
        items = row.get("items") or []
        completed = sum(
            1 for it in items
            if isinstance(it, dict)
            and it.get("status") in ("completed", "failed", "cancelled")
        )
        return {
            "batch_id": row.get("batch_id"),
            "status": row.get("status"),
            "total": len(items),
            "completed": completed,
            "items": items,
            "events": row.get("events") or [],
            "created_at": row.get("created_at"),
            "concurrency": row.get("concurrency"),
            "params": row.get("params") or {},
            # Sentinel so UI knows this came from disk (no live
            # in-memory state — chunk_events would be stale, etc.).
            "from_history": True,
            "kind": row.get("kind") or "sampling",
        }

    @app.get("/api/sampling-status")
    def sampling_status_endpoint() -> dict[str, Any]:
        """Server-side truth about in-flight sampling. Frontend calls on
        page load to recover state (activeBatchId) and on machine-select
        to disable 开始采样 when any selected (machine, mode) is busy."""
        return batch_mgr.sampling_status()

    @app.post("/api/batch-run/{batch_id}/cancel")
    def cancel_batch_run(batch_id: str) -> dict[str, Any]:
        if not batch_mgr.cancel_batch(batch_id):
            raise HTTPException(status_code=404, detail="batch not found")
        return {"ok": True}

    @app.get("/api/batches")
    def list_batches(limit: int = 30, kind: str | None = None) -> dict[str, Any]:
        """Unified batch history across both managers (sampling +
        generate). Returns most-recent first by created_at.

        Surfaces completed/failed/cancelled batches that the in-memory
        _batches dicts don't carry (sampling: completed batches are
        filtered out of restore; generate: same). This is the
        "console restart, what happened yesterday?" view.

        Params:
          limit: cap rows (default 30; max 500)
          kind:  optional filter — 'sampling' or 'generate'

        Each item carries enough for the UI history panel to render a
        row + click into details (which goes through the existing GET
        /api/batch-run/{id} for sampling kind or the
        /api/rawdata/batch-generate-report/{id} for generate kind).
        params + items + events are intentionally NOT included in this
        list view (each row could be 50-500KB JSON); UI fetches detail
        on click.

        2026-05-26 B1 task.
        """
        eff_limit = max(1, min(500, int(limit)))
        if kind not in (None, "sampling", "generate"):
            raise HTTPException(
                status_code=400,
                detail=f"kind must be 'sampling' or 'generate' (got {kind!r})",
            )
        try:
            rows = store.list_recent_batches(limit=eff_limit, kind=kind)
        except sqlite3.OperationalError:
            # pre-L2 db: no batches table yet, return empty.
            rows = []
        # Strip the heavy json columns; surface metadata + per-item
        # counts that the UI history row needs.
        out: list[dict[str, Any]] = []
        for r in rows:
            items = r.get("items") or []
            counts: dict[str, int] = {}
            for it in items:
                if isinstance(it, dict):
                    s = str(it.get("status") or "?")
                    counts[s] = counts.get(s, 0) + 1
            out.append({
                "batch_id": r.get("batch_id"),
                "kind": r.get("kind") or "sampling",
                "status": r.get("status"),
                "created_at": r.get("created_at"),
                "finished_at": r.get("finished_at"),
                "concurrency": r.get("concurrency"),
                "total_items": len(items),
                "item_status_counts": counts,
            })
        return {"batches": out, "count": len(out)}

    @app.post("/api/batch-run/{batch_id}/resume")
    def resume_batch_run(batch_id: str) -> dict[str, Any]:
        """Re-submit a cancelled / failed / partial batch with the same
        params, including only items that did NOT reach completed.

        On the wire this is just a new batch_id. The "resume" is implicit:
        ``start_batch`` already does resume_from_cache per-item against
        ``rawdata/{machine}/mode_X/``, so chunks already written persist
        and the analyzer continues from the next chunk index. Cancelled
        or failed items pick up where they left off; pending items run
        from scratch. The interrupted chunk (mid-HTTP at cancel time)
        is always discarded — chunk files are atomic-written so any
        partially-written file gets skipped as malformed.

        2026-05-22 task A1: until this endpoint, the same UX required
        the operator to re-select the same machines + re-click 开始采样
        and trust that resume_from_cache would do the right thing. The
        button just makes that two-step explicit.
        """
        state = batch_mgr.get_batch(batch_id)
        if state is None:
            raise HTTPException(status_code=404, detail="batch not found")

        # Only let TERMINAL-incomplete batches be resumed. A still-running
        # batch doesn't need a resume (it's still going); an already-
        # completed batch has nothing left to do (the new submit would
        # be a no-op at best, a confused double-spend at worst).
        if state["status"] not in ("cancelled", "failed", "partial"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"batch is in status '{state['status']}' — only "
                    "cancelled / failed / partial batches can be resumed"
                ),
            )

        # Items to re-submit. ``completed`` and ``attached`` items have
        # already produced (or are already producing) a usable run for
        # their cell, so we skip them. Everything else (failed /
        # cancelled / pending / running-leftover) gets re-queued.
        incomplete_statuses = {"failed", "cancelled", "pending", "running"}
        items_to_resume = [
            it for it in state["items"]
            if it.get("status") in incomplete_statuses
        ]
        if not items_to_resume:
            raise HTTPException(
                status_code=409,
                detail=(
                    "all items already completed (or attached) — nothing "
                    "to resume"
                ),
            )

        # Rebuild BatchRunRequest from saved batch params. Per-item
        # chunk_spin_times is preserved from the original (per-machine
        # heuristic was already applied at submit time).
        params = state.get("params") or {}
        new_items = [
            BatchRunItem(
                machine=it["machine"],
                mode=int(it["mode"]),
                chunk_spin_times=int(it["chunk_spin_times"])
                if it.get("chunk_spin_times") is not None
                else None,
            )
            for it in items_to_resume
        ]
        new_req = BatchRunRequest(
            items=new_items,
            concurrency=int(state.get("concurrency") or 3),
            server_id=str(params.get("server_id") or ""),
            chunk_spin_times=int(params.get("chunk_spin_times") or 10000),
            chunk_robot_count=int(params.get("chunk_robot_count") or 8),
            batch_concurrency=int(params.get("batch_concurrency") or 8),
            max_chunks=int(params.get("max_chunks") or 120),
            timeout=float(params.get("timeout") or 60.0),
            target_halfwidth_pp=float(params.get("target_halfwidth_pp") or 0.5),
            auto_cleanup_cache=bool(params.get("auto_cleanup_cache", True)),
        )

        result = batch_mgr.start_batch(new_req)
        # Tag the response so the UI can wire the new batch_id back into
        # the same activity log entry / show "continuation of {old}".
        result["resumed_from_batch_id"] = batch_id
        result["resumed_items"] = len(items_to_resume)
        result["skipped_completed_items"] = (
            len(state["items"]) - len(items_to_resume)
        )
        return result

    # ── Server management ──

    @app.get("/api/servers")
    def list_servers() -> dict[str, Any]:
        """Server list with the EFFECTIVE default merged in.

        Reads tracked configs/servers.json for the actual server list,
        then overlays state/console/settings.json's ``default_server``
        if the operator has set one — that way the UI's "默认服务器"
        chip shows what the resolver will actually use, not the stale
        shipped default.

        If the operator override points at a server that no longer
        exists (e.g. operator deleted it), we silently drop the
        override here too so the UI does not display a dangling ref.
        """
        cfg = load_servers(sc)
        op_default = _load_settings(settings_path).get("default_server", "")
        if op_default:
            ids = {s.get("id") for s in (cfg.get("servers") or []) if isinstance(s, dict)}
            if op_default in ids:
                cfg["default_server"] = op_default
        return cfg

    @app.post("/api/servers")
    def add_server(entry: ServerEntry) -> dict[str, Any]:
        cfg = load_servers(sc)
        servers = cfg.get("servers", [])
        if any(s["id"] == entry.id for s in servers):
            raise HTTPException(status_code=409, detail=f"server '{entry.id}' already exists")
        servers.append(entry.model_dump())
        cfg["servers"] = servers
        save_servers(cfg, sc)
        return {"ok": True, "server": entry.model_dump()}

    @app.put("/api/servers/{server_id}")
    def update_server(server_id: str, req: ServerUpdateRequest) -> dict[str, Any]:
        cfg = load_servers(sc)
        servers = cfg.get("servers", [])
        target = next((s for s in servers if s["id"] == server_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="server not found")
        if req.name is not None:
            target["name"] = req.name
        if req.endpoint is not None:
            target["endpoint"] = req.endpoint
        if req.active is not None:
            target["active"] = req.active
        save_servers(cfg, sc)
        return {"ok": True, "server": target}

    @app.put("/api/servers/{server_id}/set-default")
    def set_default_server(server_id: str) -> dict[str, Any]:
        """Mark ``server_id`` as the operator-preferred default for
        sampling. Batch-run resolver (``_resolve_active_server_id``)
        picks this up on every subsequent call, so the flip takes
        effect without a backend restart. 400 if the target has no
        endpoint — a default-server pointing to an unreachable entry
        just masks the bug with a silent fallthrough.

        Persistence: writes to state/console/settings.json (operator
        override layer), NOT tracked configs/servers.json. Reason:
        ``default_server`` is a per-deploy preference; persisting it
        in tracked code causes git merge conflicts every time an
        operator flips the dropdown and then the developer pushes an
        unrelated change. servers.json keeps its shipped default
        field intact as the fallback.

        Reads ``SERVERS_CONFIG`` module attribute directly (not the
        ``sc`` closure captured at app-build time) so tests and
        runtime config swaps take effect immediately."""
        cfg_path = SERVERS_CONFIG
        cfg = load_servers(cfg_path)
        target = next(
            (s for s in cfg.get("servers", []) if s.get("id") == server_id),
            None,
        )
        if target is None:
            raise HTTPException(status_code=404, detail="server not found")
        ep = (target.get("endpoint") or "").strip()
        if not ep:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"cannot set '{server_id}' as default — it has no "
                    f"endpoint configured"
                ),
            )
        current = _load_settings(settings_path)
        current["default_server"] = server_id
        _save_settings(settings_path, current)
        return {"ok": True, "default_server": server_id}

    @app.post("/api/servers/{server_id}/scan")
    def scan_server(server_id: str) -> dict[str, Any]:
        """Fetch MachineConfigMd5 from a server and cache the snapshot."""
        cfg = load_servers(sc)
        target = next((s for s in cfg.get("servers", []) if s["id"] == server_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="server not found")
        ep = target.get("endpoint", "").strip()
        if not ep:
            raise HTTPException(status_code=400, detail="server has no endpoint configured")
        data = _fetch_machine_config_md5(ep)
        if data is None:
            raise HTTPException(status_code=502, detail="failed to fetch MachineConfigMd5 from server")
        _save_server_snapshot(server_id, data)
        return {"ok": True, "machine_count": len(data), "server_id": server_id}

    @app.get("/api/servers/{server_id}/snapshot")
    def get_server_snapshot(server_id: str) -> dict[str, Any]:
        snap = _load_server_snapshot(server_id)
        if snap is None:
            raise HTTPException(status_code=404, detail="no snapshot for this server; run scan first")
        return {"server_id": server_id, "machine_count": len(snap), "snapshot": snap}

    @app.get("/api/servers/compare")
    def compare_servers(a: str, b: str) -> dict[str, Any]:
        """Compare MachineConfigMd5 snapshots between two servers."""
        snap_a = _load_server_snapshot(a)
        snap_b = _load_server_snapshot(b)
        if snap_a is None:
            raise HTTPException(status_code=404, detail=f"no snapshot for server '{a}'")
        if snap_b is None:
            raise HTTPException(status_code=404, detail=f"no snapshot for server '{b}'")
        diffs = _compare_snapshots(snap_a, snap_b)
        return {
            "server_a": a,
            "server_b": b,
            "total_a": len(snap_a),
            "total_b": len(snap_b),
            "diffs": diffs,
            "diff_count": len(diffs),
        }

    @app.post("/api/servers/{server_id}/check-changes")
    def check_version_changes(server_id: str) -> dict[str, Any]:
        """Scan server for MachineConfigMd5 and compare with previous snapshot."""
        cfg = load_servers(sc)
        target = next((s for s in cfg.get("servers", []) if s["id"] == server_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="server not found")
        ep = target.get("endpoint", "").strip()
        if not ep:
            raise HTTPException(status_code=400, detail="server has no endpoint configured")
        # Load previous snapshot.
        old_snap = _load_server_snapshot(server_id)
        # Fetch current state.
        new_data = _fetch_machine_config_md5(ep)
        if new_data is None:
            raise HTTPException(status_code=502, detail="failed to fetch from server")
        # Save as new snapshot.
        _save_server_snapshot(server_id, new_data)
        # Compare.
        if old_snap is None:
            return {
                "server_id": server_id,
                "first_scan": True,
                "machine_count": len(new_data),
                "diffs": [],
            }
        diffs = _compare_snapshots(old_snap, new_data)
        return {
            "server_id": server_id,
            "first_scan": False,
            "machine_count": len(new_data),
            "diffs": diffs,
            "diff_count": len(diffs),
            "changed_machines": [d["machine"] for d in diffs if d.get("status") == "changed"],
            "config_changed": [d["machine"] for d in diffs if d.get("config_changed")],
            "code_changed": [d["machine"] for d in diffs if d.get("code_changed")],
        }

    @app.delete("/api/servers/{server_id}")
    def delete_server(server_id: str) -> dict[str, Any]:
        cfg = load_servers(sc)
        servers = cfg.get("servers", [])
        before = len(servers)
        cfg["servers"] = [s for s in servers if s["id"] != server_id]
        if len(cfg["servers"]) == before:
            raise HTTPException(status_code=404, detail="server not found")
        if cfg.get("default_server") == server_id:
            cfg["default_server"] = cfg["servers"][0]["id"] if cfg["servers"] else ""
        save_servers(cfg, sc)
        # Also clear the operator-override default in settings.json if
        # it points at the just-deleted server. Otherwise list_servers
        # would silently drop the override (it filters dangling refs)
        # but a subsequent set-default to a different id would briefly
        # display the stale string in the response.
        op_settings = _load_settings(settings_path)
        if op_settings.get("default_server") == server_id:
            op_settings["default_server"] = ""
            _save_settings(settings_path, op_settings)
        return {"ok": True}

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
        # Phase 2 (D6 + D9 site #3): acquire GENERATING lock for this cell.
        # start_run is for from-cache / generate-report style runs; the
        # SAMPLING path goes through BatchRunManager._run_one which acquires
        # SAMPLING separately.
        #
        # 2026-05-22 (Scenario D fix): user-facing single-cell generate-report
        # opts into INV-3 gating so a report is not produced while SAMPLING
        # is still writing chunks (which would silently omit data).
        if not registry.try_acquire_cell(
            req.machine, req.mode, CellOperation.GENERATING,
            block_if_sampling_active=True,
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"cell {req.machine}|{req.mode} is busy — "
                    "another generate/delete is in progress, or sampling is "
                    "writing chunks (retry after it completes to get a "
                    "complete report)"
                ),
            )
        try:
            return manager.start_run(req)
        finally:
            registry.release_cell(req.machine, req.mode, CellOperation.GENERATING)

    @app.post("/api/autotune")
    def auto_tune(req: AutoTuneRequest) -> dict[str, Any]:
        running = store.list_runs_by_status("running", limit=2000)
        if running:
            raise HTTPException(status_code=409, detail="auto tune is blocked while runs are active")
        # Phase 2 (D9 site #12): migrated from ops.acquire to registry global.
        if not registry.try_acquire_global("autotune"):
            raise HTTPException(status_code=409, detail="autotune already in progress")
        try:
            # 2026-05-22: per-server autotune.
            # (1) Identify which server endpoint we're probing — this is
            #     who the result will be persisted against. Resolver
            #     reads settings.json operator override / servers.json
            #     shipped default / first-active, same as batch-run.
            target_server_id = _resolve_active_server_id(
                settings_path=settings_path,
            )
            endpoint_url = (
                get_server_endpoint(target_server_id)
                if target_server_id
                else SLOT_SPIN_ENDPOINT
            )
            endpoint_kind = _classify_endpoint_kind(endpoint_url)

            wants_auto = (
                req.use_auto_grid
                or not req.robot_candidates
                or not req.concurrency_candidates
            )

            # (2a) Loopback short-circuit. On the same-machine deployment
            #      pattern (slot simulator + console on one Windows box,
            #      sampling target = 127.0.0.1:15060), the throughput
            #      ceiling is fixed by the simulator's CPU/worker budget;
            #      no probe grid produces a meaningfully different answer
            #      from _LOOPBACK_HARDCODED_TUNING (data: 2026-05-22).
            #      So the UI 调参 button just materializes the constant
            #      instead of burning 2 minutes of probe time. The
            #      explicit-candidate path (operator passing non-empty
            #      robot/conc arrays AND use_auto_grid=false) is still
            #      honored — if you want to verify the constant or probe
            #      a different region, send curl with explicit candidates.
            if endpoint_kind == "loopback" and wants_auto:
                rc = _LOOPBACK_HARDCODED_TUNING["chunk_robot_count"]
                bc = _LOOPBACK_HARDCODED_TUNING["batch_concurrency"]
                if target_server_id:
                    _save_server_tuning(
                        settings_path,
                        target_server_id,
                        rc,
                        bc,
                        endpoint_kind="loopback",
                        probe={"hardcoded": True, "note": (
                            "loopback hardcoded tuning — see _LOOPBACK_"
                            "HARDCODED_TUNING in app.py for source data"
                        )},
                    )
                return {
                    "started_at": utc_now(),
                    "finished_at": utc_now(),
                    "machine": req.machine,
                    "mode": req.mode,
                    "spin_times": req.spin_times,
                    "rounds": req.rounds,
                    "robot_candidates": [rc],
                    "concurrency_candidates": [bc],
                    "tested": 0,
                    "best": None,
                    "recommendation": {
                        "chunk_robot_count": rc,
                        "batch_concurrency": bc,
                    },
                    "results": [],
                    "saved_for_server": target_server_id,
                    "endpoint_kind": "loopback",
                    "hardcoded": True,
                }

            # (2b) LAN / WAN: apply the per-endpoint probe-grid preset
            #      when the caller opts in OR sends empty candidate
            #      arrays. Explicit non-empty candidates still win.
            if wants_auto:
                grid = _auto_grid_for_endpoint(endpoint_url)
                req = req.model_copy(update={
                    "robot_candidates": list(grid["robot_candidates"]),
                    "concurrency_candidates": list(grid["concurrency_candidates"]),
                })

            result = run_auto_tune(req, progress_callback=_autotune_progress_sink)

            # (3) Persist the recommendation against target_server_id so
            #     subsequent batch-runs (this server) can resolve
            #     chunk_robot_count / batch_concurrency without the
            #     caller having to remember the last-tuned values.
            #     Probe metadata (machine + best success_rate + best
            #     throughput) goes in the sidecar for "why this number"
            #     traceability.
            rec = result.get("recommendation") or {}
            rc = rec.get("chunk_robot_count")
            bc = rec.get("batch_concurrency")
            if target_server_id and isinstance(rc, int) and isinstance(bc, int):
                best = result.get("best") or {}
                _save_server_tuning(
                    settings_path,
                    target_server_id,
                    rc,
                    bc,
                    endpoint_kind=endpoint_kind,
                    probe={
                        "machine": req.machine,
                        "mode": req.mode,
                        "success_rate": float(best.get("success_rate") or 0.0),
                        "throughput_spins_per_sec": float(
                            best.get("throughput_spins_per_sec") or 0.0
                        ),
                    },
                )
                result["saved_for_server"] = target_server_id
                result["endpoint_kind"] = endpoint_kind
            return result
        finally:
            registry.release_global("autotune")

    @app.get("/api/autotune/progress")
    def autotune_progress() -> dict[str, Any]:
        """Snapshot of autotune progress. Safe to poll at 1s cadence from
        the frontend while a compute is in flight; returns {"status":"idle"}
        when nothing has been run yet this process lifetime."""
        with app.state.autotune_progress_lock:
            return dict(app.state.autotune_progress)

    @app.get("/api/servers/{server_id}/tuning")
    def get_server_tuning_endpoint(server_id: str) -> dict[str, Any]:
        """Return the persisted autotune recommendation for one server.

        Empty body (``{}``) means no tuning has been saved yet for this
        endpoint — caller (UI or batch-run resolver) falls back to the
        hardcoded BatchRunRequest defaults. Frontend uses this to show
        the "已调参" chip and to populate the sampling form with the
        per-server tuned values instead of the local-storage cache.
        """
        return _load_server_tuning(server_id, settings_path)

    @app.get("/api/runs")
    def runs(limit: int = 2000) -> dict[str, Any]:
        # Old default was 50 via store.list_runs(); at 1013+ DB rows the
        # manage-tab history would only show the newest 50. 2000 is the
        # current population * ~2 headroom; callers can request lower
        # via ?limit= if they want a faster roundtrip.
        return {"runs": manager.list_runs(limit=max(1, limit))}

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

    def _run_generate_report(
        machine: str, mode: int,
        *, config_md5: str = "", code_md5: str = "",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Core generate-report work. Acquires GENERATING lock via
        CellLockRegistry internally; caller does not manage lock lifecycle.

        When ``config_md5`` + ``code_md5`` are both provided, scope the
        analyzer to chunks whose envelope md5 matches those values —
        lets the rwtree generate a report from a historical-md5 cell
        (user-requested 2026-04-21: "report 都是独立的"). Empty
        strings = current-md5 default (kept + deletable classifier
        result).

        ``run_id`` optional (2026-04-22): when the async endpoint
        pre-allocates a run_id + inserts a ``status=queued`` row so
        the response can carry the id back to the UI for activity-log
        polling, this function UPDATEs that row instead of inserting
        a fresh one. ``None`` keeps the original INSERT behavior for
        the sync endpoint + batch-generate workers.

        Raises HTTPException on validation failure so the single-item
        endpoint surfaces standard HTTP errors; the batch manager
        catches them to record per-item failures.
        """
        # 2026-06-06 Phase 2b: wire to report_engine.generate_report_from_chunks.
        # Registered machines (configs/machine_manifests/<M>.json exists) → generate.
        # Non-registered machines → clear HTTPException(422).
        # The live-sampling RunManager subprocess path (ANALYZER constant / spawning)
        # is untouched — only the from-cache path is wired here.

        # -- REGISTERED CHECK (before any disk I/O) --
        from fresh_slotlab.analyzer.report_engine import (  # noqa: PLC0415
            generate_report_from_chunks as _gen_report,
            MachineNotRegistered,
        )
        _manifests_root = ROOT / "configs" / "machine_manifests"
        if not (_manifests_root / f"{machine}.json").exists():
            raise HTTPException(
                status_code=422,
                detail=(
                    f"machine {machine} is not registered for the SpinType-native engine "
                    "(only machines with a confirmed machine_spec manifest generate reports); "
                    "see docs/ANALYZER_ARCHITECTURE.md"
                ),
            )

        mode_dir = rd_root / machine / f"mode_{mode}"
        if not mode_dir.is_dir():
            raise HTTPException(
                status_code=404,
                detail=f"no rawdata for {machine} mode {mode} — resample required",
            )
        retention = _load_settings(settings_path)["min_retention_spins"]
        classified = _classify_chunks(machine, mode, rd_root, mc, retention)
        md5_filter = bool(config_md5 and code_md5)
        if md5_filter:
            all_entries = (
                classified["kept"] + classified["deletable"] + classified["historical"]
            )
            usable_entries = [
                e for e in all_entries
                if e.get("config_md5") == config_md5 and e.get("code_md5") == code_md5
            ]
            if not usable_entries:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"no chunks for {machine} mode {mode} "
                        f"matching md5 cfg={config_md5[:8]}… code={code_md5[:8]}…"
                    ),
                )
        else:
            usable_entries = classified["kept"] + classified["deletable"]
            if not usable_entries:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"no usable chunks for {machine} mode {mode} "
                        f"(kept=0, deletable=0; historical={len(classified['historical'])})"
                    ),
                )

        if not registry.try_acquire_cell(
            machine, mode, CellOperation.GENERATING,
            block_if_sampling_active=True,
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"cell {machine}|{mode} is busy — "
                    "another generate/delete is in progress, or sampling is "
                    "writing chunks (retry after it completes to get a "
                    "complete report)"
                ),
            )
        try:
            chunk_paths = sorted(Path(e["path"]) for e in usable_entries)

            new_run_id = run_id or f"gen_{uuid.uuid4().hex[:12]}"
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            if md5_filter:
                cfg_short = (config_md5 or "")[:6] or "-"
                code_short = (code_md5 or "")[:6] or "-"
                report_version = f"rv_{ts}_rawdata_{cfg_short}_{code_short}"
            else:
                report_version = f"rv_{ts}_rawdata"
            output_dir = rr / machine / f"mode_{mode}" / "versions" / report_version
            output_dir.mkdir(parents=True, exist_ok=True)
            progress_file = sd / "progress" / f"{new_run_id}.jsonl"
            summary_file = output_dir / "player_impact_summary.json"
            report_file = output_dir / "player_impact_report.md"

            # Reuse the first usable chunk's robot_count / spin_times.
            sample_env = json.loads(chunk_paths[0].read_text(encoding="utf-8"))
            chunk_spin_times = int(sample_env.get("_spin_times") or 5000)
            chunk_robot_count = int(sample_env.get("_robot_count") or 24)

            started_now = utc_now()
            row_fields = {
                "machine": machine,
                "mode": mode,
                "status": "running",
                "model_id": "generate-report",
                "started_at": started_now,
                "target_halfwidth_pp": 0.001,
                "chunk_spin_times": chunk_spin_times,
                "chunk_robot_count": chunk_robot_count,
                "batch_concurrency": 1,
                "max_chunks": len(chunk_paths),
                "timeout": 30,
                "bankruptcy_session_spins": 10000,
                "bankruptcy_bankroll_multipliers": "10,100,200,500",
                "report_version": report_version,
                "output_dir": str(output_dir),
                "progress_file": str(progress_file),
                "summary_file": str(summary_file),
                "report_file": str(report_file),
            }
            if run_id and store.get_run(run_id):
                store.update_run(new_run_id, row_fields)
            else:
                store.insert_run({
                    "run_id": new_run_id,
                    "created_at": started_now,
                    **row_fields,
                })

            # -- NEW ENGINE: report_engine.generate_report_from_chunks --
            # Chunk dir: the whole mode dir (engine reads chunk_*.json from it).
            # Note: md5-filtering of mixed-md5 dirs is a follow-up; for M15 all
            # chunks share one md5 so the full mode_dir is safe. The engine raises
            # MachineNotRegistered if the manifest is absent (already caught above).
            try:
                _gen_report(
                    machine, mode,
                    chunk_dir=mode_dir,
                    output_dir=output_dir,
                    run_id=new_run_id,
                )
            except MachineNotRegistered as exc:
                raise HTTPException(
                    status_code=422,
                    detail=str(exc),
                ) from exc

            # Patch empty md5 tags in the written summary (mirrors old path).
            from fresh_slotlab.summary_md5_patch import patch_summary_md5 as _patch_summary_md5  # noqa: PLC0415
            _patch_summary_md5(
                summary_file,
                lambda: _get_machine_md5(machine, mc, mode=mode),
                machine=machine,
                mode=mode,
            )

            summary: dict[str, Any] = {}
            if summary_file.exists():
                summary = read_json(summary_file) or {}
            rtp = (summary.get("rtp") or {}).get("point_pct")
            hw = (summary.get("sampling") or {}).get("achieved_halfwidth_pp")
            ql = (
                (summary.get("guideline_assessment") or {})
                .get("data_quality", {})
                .get("quality_label")
            )
            rawdata_cfg = summary.get("config_md5") or ""
            rawdata_code = summary.get("code_md5") or ""
            analyzer_ver = summary.get("analyzer_version") or ""
            total_spins_val = summary.get("sampling", {}).get("total_spins")

            store.update_run(new_run_id, {
                "status": "completed",
                "finished_at": utc_now(),
                "achieved_rtp_pct": float(rtp) if rtp is not None else None,
                "achieved_halfwidth_pp": float(hw) if hw is not None else None,
                "quality_label": str(ql) if ql else None,
                "rawdata_config_md5": str(rawdata_cfg) if rawdata_cfg else None,
                "rawdata_code_md5": str(rawdata_code) if rawdata_code else None,
                "analyzer_version": str(analyzer_ver) if analyzer_ver else None,
                "total_spins": int(total_spins_val) if total_spins_val is not None else None,
            })

            mode_reports_dir = rr / machine / f"mode_{mode}"
            index_path = mode_reports_dir / "index.json"
            latest_path = mode_reports_dir / "latest.json"
            item = {
                "report_version": report_version,
                "run_id": new_run_id,
                "created_at": utc_now(),
                "summary_file": str(summary_file),
                "report_file": str(report_file),
                "rtp_point_pct": rtp,
                "achieved_rtp_pct": rtp,
                "achieved_halfwidth_pp": hw,
                "total_spins": total_spins_val,
                "quality_label": ql,
            }
            index_payload = []
            if index_path.exists():
                try:
                    raw = read_json(index_path)
                    if isinstance(raw, list):
                        index_payload = raw
                except Exception:
                    pass
            index_payload.append(item)
            atomic_json_write(index_path, index_payload)
            atomic_json_write(latest_path, item)

            try:
                _merge_machine_static(
                    machine, summary, mc, _static_attrs_path(mc),
                )
            except Exception:
                pass

            try:
                import threading as _threading
                _threading.Thread(
                    target=lambda: _run_post_analyzer_inference(
                        machine, mode, rawdata_root=rd_root,
                        paytables_dir=pd_root, classify_dir=cd,
                        timeout_sec=300.0,
                        log_to_dir=output_dir,
                    ),
                    daemon=True,
                    name=f"post-infer-{machine}-{mode}",
                ).start()
            except Exception:
                pass

            return {
                "run_id": new_run_id,
                "machine": machine,
                "mode": mode,
                "report_version": report_version,
                "chunks_processed": len(chunk_paths),
                "rtp_point_pct": rtp,
                "achieved_halfwidth_pp": hw,
                "analyzer_version": analyzer_ver,
            }
        except HTTPException as exc:
            if "new_run_id" in locals() and store.get_run(new_run_id):
                store.update_run(new_run_id, {
                    "status": "failed",
                    "finished_at": utc_now(),
                    "error_message": str(getattr(exc, "detail", exc))[:500],
                })
            raise
        except Exception as exc:
            if "new_run_id" in locals() and store.get_run(new_run_id):
                store.update_run(new_run_id, {
                    "status": "failed",
                    "finished_at": utc_now(),
                    "error_message": f"{exc.__class__.__name__}: {exc}"[:500],
                })
            raise HTTPException(
                status_code=500,
                detail=f"generate-report failed: {exc.__class__.__name__}: {exc}",
            ) from exc
        finally:
            registry.release_cell(machine, mode, CellOperation.GENERATING)

    def _prepare_batch_gen_item(machine: str, mode: int) -> dict[str, Any]:
        """Parent-thread prep: validate chunks, create output dir, insert
        RUNNING run row, build job dict for the worker.

        Returns a dict with ``job`` (worker input), plus ``run_id``,
        ``output_dir``, ``chunk_count`` etc. used by _finalize.
        Raises HTTPException on validation failure — batch manager
        surfaces as a per-item error.
        """
        mode_dir = rd_root / machine / f"mode_{mode}"
        if not mode_dir.is_dir():
            raise HTTPException(
                status_code=404,
                detail=f"no rawdata for {machine} mode {mode}",
            )
        retention = _load_settings(settings_path)["min_retention_spins"]
        classified = _classify_chunks(machine, mode, rd_root, mc, retention)
        usable = classified["kept"] + classified["deletable"]
        if not usable:
            raise HTTPException(
                status_code=404,
                detail=f"no usable chunks for {machine} mode {mode}",
            )
        chunk_paths = sorted(Path(e["path"]) for e in usable)
        sample_env = json.loads(chunk_paths[0].read_text(encoding="utf-8"))
        chunk_spin_times = int(sample_env.get("_spin_times") or 5000)
        chunk_robot_count = int(sample_env.get("_robot_count") or 24)
        new_run_id = f"gen_{uuid.uuid4().hex[:12]}"
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report_version = f"rv_{ts}_rawdata"
        output_dir = rr / machine / f"mode_{mode}" / "versions" / report_version
        output_dir.mkdir(parents=True, exist_ok=True)
        progress_file = sd / "progress" / f"{new_run_id}.jsonl"
        summary_file = output_dir / "player_impact_summary.json"
        report_file = output_dir / "player_impact_report.md"
        started_now = utc_now()
        store.insert_run({
            "run_id": new_run_id,
            "machine": machine,
            "mode": mode,
            "status": "running",
            "model_id": "generate-report",
            "created_at": started_now,
            "started_at": started_now,
            "target_halfwidth_pp": 0.001,
            "chunk_spin_times": chunk_spin_times,
            "chunk_robot_count": chunk_robot_count,
            "batch_concurrency": 1,
            "max_chunks": len(usable),
            "timeout": 30,
            "bankruptcy_session_spins": 10000,
            "bankruptcy_bankroll_multipliers": "10,100,200,500",
            "report_version": report_version,
            "output_dir": str(output_dir),
            "progress_file": str(progress_file),
            "summary_file": str(summary_file),
            "report_file": str(report_file),
        })
        # C1 (P1-D1 §3 C1): look up (config_md5, code_md5) for this
        # (machine, mode) pair so the worker can forward them as
        # --upstream-config-md5 / --upstream-code-md5 CLI flags to the
        # analyzer, filtering historical-md5 chunks out of the batch run.
        # Uses app-level _get_machine_md5 which handles both real machines
        # (flat configSummaryMd5 schema) and virtual machines (per-mode
        # modesMd5 schema). Matches the logic in _run_generate_report
        # (lines 7185-7188 of the in-process path).
        upstream_cfg, upstream_code = _get_machine_md5(machine, mc, mode=mode)
        return {
            "machine": machine,
            "mode": mode,
            "run_id": new_run_id,
            "report_version": report_version,
            "output_dir": output_dir,
            "summary_file": summary_file,
            "report_file": report_file,
            "chunk_count": len(usable),
            "job": {
                "machine": machine,
                "mode": mode,
                "chunk_dir": str(mode_dir),
                "output_dir": str(output_dir),
                "run_id": new_run_id,
                "progress_file": str(progress_file),
                "max_chunks": len(usable),
                "chunk_spin_times": chunk_spin_times,
                "chunk_robot_count": chunk_robot_count,
                "bet": 1000,
                # C1 (P1-D1 §3 C1): md5 filter keys — forwarded by the
                # worker to the analyzer as --upstream-config-md5 /
                # --upstream-code-md5 CLI flags so historical-md5 chunks
                # are excluded from batch-generated reports (same as the
                # in-process _run_generate_report path, lines 7185-7188).
                "upstream_config_md5": upstream_cfg,
                "upstream_code_md5": upstream_code,
                # C3 (P1-D1 §3 C3): machines_config forwarded to the
                # worker so patch_summary_md5 can call lookup_machine_md5
                # with the correct config path (virtual machines need the
                # per-mode modesMd5 schema, not the repo-root default).
                "machines_config": str(mc),
                # Forward the app-level output dirs to the worker's post-
                # analyzer hook so alternate-universe callers (tests, the
                # virtual-machine console) don't clobber real
                # configs/paytables/ + dev_reports/_classify/ with their
                # per-run inference artefacts.
                "paytables_dir": str(pd_root),
                "classify_dir": str(cd),
            },
        }

    def _prepare_batch_gen_item_wrapper(machine: str, mode: int) -> dict[str, Any]:
        """Acquire GENERATING protection before submitting the worker.
        Phase 2 (D7): uses registry instead of _acquire_in_use.
        Released in _finalize_batch_gen_item_wrapper below."""
        prepared = _prepare_batch_gen_item(machine, mode)
        # If registry says cell is already locked (e.g. concurrent DELETING),
        # raise so BatchGenerateManager marks this item as failed.
        if not registry.try_acquire_cell(machine, int(mode), CellOperation.GENERATING):
            raise HTTPException(
                status_code=409,
                detail=f"cell {machine}|{mode} is busy — cannot start batch-generate",
            )
        return prepared

    def _finalize_batch_gen_item_wrapper(
        prepared: dict[str, Any], worker_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Release GENERATING protection after each worker finishes.
        Phase 2 (D7): uses registry instead of _release_in_use."""
        try:
            return _finalize_batch_gen_item(prepared, worker_result)
        finally:
            registry.release_cell(
                prepared.get("machine") or "",
                int(prepared.get("mode") or 0),
                CellOperation.GENERATING,
            )

    def _finalize_batch_gen_item(
        prepared: dict[str, Any], worker_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Parent-thread post-process: read summary, update DB row,
        write index.json / latest.json, merge static attrs. Returns a
        dict with rtp_point_pct / achieved_halfwidth_pp for the batch
        UI to display."""
        machine = prepared["machine"]
        mode = int(prepared["mode"])
        run_id = prepared["run_id"]
        output_dir = Path(prepared["output_dir"])
        summary_file = Path(prepared["summary_file"])
        report_file = Path(prepared["report_file"])
        report_version = prepared["report_version"]
        chunk_count = prepared["chunk_count"]

        # Persist the batch worker's auto-inference post_hook diagnostic
        # (paytable_shape + classifier rc / skip reasons) so we can trace
        # silent hook failures without spinning up a tracing framework.
        # Mode 7 regression (2026-04-20): all 252 items ran but produced
        # zero configs/paytables/*_mode7.json — without persisted hook
        # results we had no way to tell whether the subprocess ran,
        # skipped, or errored. File is tiny (<1KB), best-effort write.
        post_hook = worker_result.get("post_hook")
        if post_hook is not None:
            try:
                write_json(output_dir / "_post_hook.json", post_hook)
            except Exception:
                pass

        if not worker_result.get("ok"):
            err = str(worker_result.get("error") or "worker failed")
            if store.get_run(run_id):
                store.update_run(run_id, {
                    "status": "failed",
                    "finished_at": utc_now(),
                    "error_message": err[:500],
                })
            return {"ok": False, "error": err}

        summary: dict[str, Any] = {}
        if summary_file.exists():
            summary = read_json(summary_file) or {}
        rtp = (summary.get("rtp") or {}).get("point_pct")
        hw = (summary.get("sampling") or {}).get("achieved_halfwidth_pp")
        ql = (
            (summary.get("guideline_assessment") or {})
            .get("data_quality", {})
            .get("quality_label")
        )
        rawdata_cfg = summary.get("config_md5") or ""
        rawdata_code = summary.get("code_md5") or ""
        analyzer_ver = summary.get("analyzer_version") or ""
        total_spins_val = summary.get("sampling", {}).get("total_spins")
        store.update_run(run_id, {
            "status": "completed",
            "finished_at": utc_now(),
            "achieved_rtp_pct": float(rtp) if rtp is not None else None,
            "achieved_halfwidth_pp": float(hw) if hw is not None else None,
            "quality_label": str(ql) if ql else None,
            "rawdata_config_md5": str(rawdata_cfg) if rawdata_cfg else None,
            "rawdata_code_md5": str(rawdata_code) if rawdata_code else None,
            "analyzer_version": str(analyzer_ver) if analyzer_ver else None,
            "total_spins": int(total_spins_val) if total_spins_val is not None else None,
        })
        mode_reports_dir = rr / machine / f"mode_{mode}"
        index_path = mode_reports_dir / "index.json"
        latest_path = mode_reports_dir / "latest.json"
        item = {
            "report_version": report_version,
            "run_id": run_id,
            "created_at": utc_now(),
            "summary_file": str(summary_file),
            "report_file": str(report_file),
            "rtp_point_pct": rtp,
            "achieved_rtp_pct": rtp,
            "achieved_halfwidth_pp": hw,
            "total_spins": total_spins_val,
            "quality_label": ql,
        }
        index_payload = []
        if index_path.exists():
            try:
                raw = read_json(index_path)
                if isinstance(raw, list):
                    index_payload = raw
            except Exception:
                pass
        index_payload.append(item)
        # Phase 1 deploy: atomic + per-file-locked
        atomic_json_write(index_path, index_payload)
        atomic_json_write(latest_path, item)
        try:
            _merge_machine_static(machine, summary, mc, _static_attrs_path(mc))
        except Exception:
            pass
        return {
            "ok": True,
            "rtp_point_pct": rtp,
            "achieved_halfwidth_pp": hw,
            "chunks_processed": chunk_count,
            "analyzer_version": analyzer_ver,
        }

    _batch_gen_concurrency = int(os.environ.get("SLOT_BATCH_GEN_WORKERS", "4"))
    # Phase 2 (D7): the wrappers now acquire/release GENERATING via registry
    # instead of _acquire_in_use / _release_in_use.  ops= removed from ctor.
    batch_gen_mgr = BatchGenerateManager(
        prepare_fn=_prepare_batch_gen_item_wrapper,
        finalize_fn=_finalize_batch_gen_item_wrapper,
        concurrency=_batch_gen_concurrency,
        root_path=str(ROOT),
        # 2026-05-26 L3: pass store so the manager can persist state
        # to the batches table (kind='generate') and restore non-
        # terminal batches as cancelled-by-restart on startup.
        store=store,
    )

    @app.post("/api/rawdata/{machine}/generate-report")
    def generate_report_from_rawdata(
        machine: str, req: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the analyzer against cached chunks for (machine, mode)
        and produce a fresh report + run row. Always creates NEW
        artefacts; old runs preserved.

        Body: ``{"mode": int, "async": bool,
                 "config_md5"?: str, "code_md5"?: str}``.

        ``config_md5`` + ``code_md5`` optional — when both provided,
        the analyzer processes only chunks whose envelope md5 matches
        those values (historical-md5 report generation, 2026-04-21).
        Empty / absent = current-md5 default.

        Default (``async=false``) runs synchronously and returns the
        completed run metadata — backward-compatible with existing
        tests and direct-API users. ``async=true`` queues the work in
        a daemon thread and returns immediately with
        ``{run_id, status: "accepted"}`` so the UI can subscribe to
        the unified events feed and render progress without a hanging
        HTTP request.
        """
        try:
            mode = int(req.get("mode"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="mode must be an integer")
        use_async = bool(req.get("async") or False)
        config_md5 = str(req.get("config_md5") or "")
        code_md5 = str(req.get("code_md5") or "")

        if not use_async:
            # Phase 2 (D9 site #2): ops.acquire("generate_report") removed.
            # _run_generate_report acquires GENERATING per cell via registry.
            return _run_generate_report(
                machine, mode,
                config_md5=config_md5, code_md5=code_md5,
            )

        # Async path: GENERATING lock is acquired inside _run_generate_report.
        # The async thread acquires on entry and releases in the finally block
        # of _run_generate_report.  No outer lock needed here.

        # 2026-04-22: pre-allocate run_id + insert ``status=queued``
        # placeholder row BEFORE spawning the thread, so the response
        # carries a stable run_id the UI can poll immediately. Before
        # this, the endpoint returned only {status: accepted} and the
        # UI had no way to track progress — user-reported symptom:
        # "点击生成以后没有 log, 没法确认状态. 合并入当前的 log 体系".
        # The thread's call to _run_generate_report(run_id=new_run_id)
        # detects the existing row and UPDATEs it instead of inserting.
        new_run_id = f"gen_{uuid.uuid4().hex[:12]}"
        started_now = utc_now()
        # Pre-compute the progress_file path so the placeholder row
        # can carry a real (if not-yet-existing) path — empty strings
        # confuse downstream Path() consumers (``Path("")`` == current
        # dir, read_text() on it raises IsADirectoryError and /api/runs
        # 500s, which is how the 2026-04-22 "生成 Report 失败: /api/runs:
        # 500" regression first surfaced in real browser use).
        _placeholder_progress = sd / "progress" / f"{new_run_id}.jsonl"
        try:
            store.insert_run({
                "run_id": new_run_id,
                "machine": machine,
                "mode": mode,
                "status": "queued",
                "model_id": "generate-report",
                "created_at": started_now,
                "started_at": started_now,
                "target_halfwidth_pp": 0.001,
                "chunk_spin_times": 0,
                "chunk_robot_count": 0,
                "batch_concurrency": 1,
                "max_chunks": 0,
                "timeout": 30,
                "bankruptcy_session_spins": 10000,
                "bankruptcy_bankroll_multipliers": "10,100,200,500",
                "report_version": "",
                "output_dir": "",
                "progress_file": str(_placeholder_progress),
                "summary_file": "",
                "report_file": "",
            })
        except Exception:
            # Placeholder insert failed — fail loudly.  Phase 2: no ops
            # lock to release (GENERATING is acquired inside _run_generate_report,
            # which hasn't started yet at this point).
            raise

        def _work() -> None:
            try:
                _run_generate_report(
                    machine, mode,
                    config_md5=config_md5, code_md5=code_md5,
                    run_id=new_run_id,
                )
            except Exception as _async_exc:
                # Persist the real traceback (memory/feedback_no_silent_swallow.md) —
                # the daemon-thread exception was previously swallowed, hiding the cause.
                import traceback as _tb
                try:
                    (sd / "_async_gen_err.txt").write_text(
                        f"run={new_run_id} machine={machine} mode={mode}\n"
                        f"{_async_exc!r}\n\n{_tb.format_exc()}",
                        encoding="utf-8",
                    )
                except Exception:
                    pass
                # _run_generate_report already marks the runs row as
                # failed on its way out. Swallow here so the daemon
                # thread exits cleanly without tracebacks in the log
                # (the failure is surfaced via the runs table + the err file above).
                # Mark the placeholder row as failed in case the
                # raise happened before the inner status=running flip.
                try:
                    cur = store.get_run(new_run_id) or {}
                    if cur.get("status") in ("queued", "running"):
                        store.update_run(new_run_id, {
                            "status": "failed",
                            "finished_at": utc_now(),
                            "error_message": f"generate-report failed: {_async_exc}",
                        })
                except Exception:
                    pass
            # Phase 2: no ops.release() needed — GENERATING lock is
            # released inside _run_generate_report's own finally block.

        threading.Thread(target=_work, daemon=True).start()
        return {
            "status": "accepted",
            "run_id": new_run_id,
            "machine": machine,
            "mode": mode,
            "message": f"generate-report started — poll /api/runs/{new_run_id}",
        }

    @app.post("/api/rawdata/batch-generate-report")
    def batch_generate_report(req: dict[str, Any]) -> dict[str, Any]:
        """Kick off batch report generation for multiple (machine, mode)
        pairs.

        Body::

          {"items": [{"machine": "M273", "mode": 1}, ...]}   — explicit list
          {"scope": "all_with_rawdata"}                      — auto-collect

        ``scope=all_with_rawdata`` walks RAWDATA_ROOT and builds items
        for every (machine, mode) pair with at least one valid chunk
        file. Used by the "⟳ 全 fleet 重建" button for large-scale
        analyzer upgrades / recoveries.
        """
        scope = str(req.get("scope") or "").strip()
        parsed_items: list[dict[str, Any]] = []

        if scope == "all_with_rawdata":
            if not rd_root.is_dir():
                raise HTTPException(status_code=404, detail="no rawdata root")
            for machine_dir in sorted(rd_root.iterdir()):
                if not machine_dir.is_dir() or machine_dir.name.startswith("_"):
                    continue
                for mode_dir in machine_dir.iterdir():
                    if not mode_dir.is_dir() or not mode_dir.name.startswith("mode_"):
                        continue
                    try:
                        mode = int(mode_dir.name.split("_")[1])
                    except (IndexError, ValueError):
                        continue
                    # Only include (m, mode) pairs with at least one
                    # chunk file (mtime-based, no envelope parse —
                    # keeps scope-build cheap even on a huge fleet).
                    if any(mode_dir.glob("chunk_*.json")):
                        parsed_items.append({"machine": machine_dir.name, "mode": mode})
            if not parsed_items:
                raise HTTPException(
                    status_code=404,
                    detail="no (machine, mode) pairs with rawdata",
                )
            return batch_gen_mgr.start(parsed_items)

        raw_items = req.get("items") or []
        if not isinstance(raw_items, list) or not raw_items:
            raise HTTPException(
                status_code=400,
                detail="items must be a non-empty list, OR set scope=all_with_rawdata",
            )
        for it in raw_items:
            if not isinstance(it, dict):
                raise HTTPException(status_code=400, detail="each item must be an object")
            machine = str(it.get("machine") or "").strip()
            try:
                mode = int(it.get("mode"))
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail=f"mode must be an integer (item: {it})",
                )
            if not machine:
                raise HTTPException(status_code=400, detail="machine required")
            parsed_items.append({"machine": machine, "mode": mode})

        # I6 fix: pre-check registry before queuing (explicit-items scope only).
        # scope=all_with_rawdata returns early above; this block is items-only.
        # Surfaces 409 synchronously at submit time instead of async worker fail.
        busy_cells: list[str] = []
        for item in parsed_items:
            ops = registry.peek_cell_status(item["machine"], item["mode"])
            if ops:
                busy_cells.append(
                    f"{item['machine']}|{item['mode']} ({', '.join(o.value for o in ops)})"
                )
        if busy_cells:
            raise HTTPException(
                status_code=409,
                detail=f"cells busy: {'; '.join(busy_cells)} — retry after active operations complete",
            )

        return batch_gen_mgr.start(parsed_items)

    @app.post("/api/rawdata/batch-generate-report/{batch_id}/cancel")
    def cancel_batch_generate(batch_id: str) -> dict[str, Any]:
        """Graceful cancel — takes effect at the next item boundary.
        Pending items flip to status=cancelled; in-progress analyzer
        call for the current item completes first (can't kill in-process
        monkey-patched run mid-flight)."""
        if not batch_gen_mgr.cancel(batch_id):
            raise HTTPException(
                status_code=404,
                detail="batch not found or already finished",
            )
        return {"ok": True, "batch_id": batch_id}

    @app.get("/api/rawdata/batch-generate-report/{batch_id}")
    def get_batch_generate_report(batch_id: str) -> dict[str, Any]:
        state = batch_gen_mgr.get(batch_id)
        if state is None:
            raise HTTPException(status_code=404, detail="batch_id not found")
        return state

    @app.delete("/api/runs/{run_id}")
    def run_delete(run_id: str) -> dict[str, Any]:
        # Phase 2 (D9 site #6): delete_run acquires GENERATING lock for the
        # run's (machine, mode) so it can't race a concurrent generate-report
        # that's still writing to the same output dir.
        row = store.get_run(run_id)
        if not row:
            raise HTTPException(status_code=404, detail="run not found")
        _machine = str(row.get("machine") or "")
        _mode = int(row.get("mode") or 0)
        if _machine and _mode:
            if not registry.try_acquire_cell(_machine, _mode, CellOperation.GENERATING):
                raise HTTPException(
                    status_code=409,
                    detail=f"cell {_machine}|{_mode} is busy — retry after active operation completes",
                )
            try:
                return manager.delete_run(run_id)
            finally:
                registry.release_cell(_machine, _mode, CellOperation.GENERATING)
        return manager.delete_run(run_id)

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
    def report_versions(
        machine: str,
        mode: int,
        config_md5: str = "",
        code_md5: str = "",
        include_historical: bool = False,
    ) -> dict[str, Any]:
        """List report versions for a (machine, mode).

        Query params (added 2026-04-26):
          - ``config_md5`` / ``code_md5``: when EITHER is non-empty, the
            response includes only reports whose stored rawdata md5
            matches AND reports tagged "untagged" (i.e. legacy reports
            that pre-date md5 stamping). The rawdata-detail panel
            passes the current rawdata md5 here so historical-md5
            reports don't leak into a fresh-pull view.
          - ``include_historical=true``: bypass md5 filtering and
            return everything, regardless of md5. Used by run-history
            views that need the full ledger.

        Behavior when no md5 query is passed: return everything (back-
        compat for callers that still expect the unfiltered list — UI
        surfaces still reading the full version table without bucketing).
        """
        mode_dir = rr / machine / f"mode_{mode}"
        index_path = mode_dir / "index.json"
        latest_path = mode_dir / "latest.json"
        index_payload = read_json(index_path) if index_path.exists() else []
        latest_payload = read_json(latest_path) if latest_path.exists() else {}
        # Legacy entries only carry ``rtp_point_pct`` + ``quality_label``.
        # Version-history UI wants ``achieved_rtp_pct`` / ``achieved_
        # halfwidth_pp`` / ``total_spins`` too. When the stored entry
        # lacks them, fall back to reading that version's summary.json
        # once per request. Cheap — this endpoint only fires when the
        # operator opens the machine-detail panel.
        if isinstance(index_payload, list):
            for entry in index_payload:
                if not isinstance(entry, dict):
                    continue
                # Backfill md5 + analyzer fields the same way other
                # achieved_* fields are backfilled — old index rows
                # don't have them; one summary.json read fills it in
                # so the filter below sees a stable shape for both
                # pre- and post-2026-04-26 entries.
                needs_md5_fill = (
                    "rawdata_config_md5" not in entry
                    or "rawdata_code_md5" not in entry
                )
                needs_perf_fill = (
                    entry.get("achieved_rtp_pct") is None
                    or entry.get("achieved_halfwidth_pp") is None
                    or entry.get("total_spins") is None
                )
                if not needs_md5_fill and not needs_perf_fill:
                    continue
                sf = entry.get("summary_file")
                if not sf or not Path(sf).exists():
                    # No summary on disk → keep entry as-is. Filtering
                    # below treats missing md5 as "untagged".
                    if needs_md5_fill:
                        entry.setdefault("rawdata_config_md5", "")
                        entry.setdefault("rawdata_code_md5", "")
                    continue
                try:
                    s = read_json(Path(sf)) or {}
                except Exception:  # noqa: BLE001
                    if needs_md5_fill:
                        entry.setdefault("rawdata_config_md5", "")
                        entry.setdefault("rawdata_code_md5", "")
                    continue
                samp = s.get("sampling") or {}
                if entry.get("achieved_rtp_pct") is None:
                    entry["achieved_rtp_pct"] = (
                        entry.get("rtp_point_pct")
                        or (s.get("rtp") or {}).get("point_pct")
                    )
                if entry.get("achieved_halfwidth_pp") is None:
                    entry["achieved_halfwidth_pp"] = samp.get("achieved_halfwidth_pp")
                if entry.get("total_spins") is None:
                    entry["total_spins"] = samp.get("total_spins")
                if needs_md5_fill:
                    entry["rawdata_config_md5"] = str(s.get("config_md5") or "")
                    entry["rawdata_code_md5"] = str(s.get("code_md5") or "")
                    entry.setdefault("analyzer_version", str(s.get("analyzer_version") or ""))

        # md5 filtering. When EITHER query md5 is set we treat it as
        # "filter to this rawdata version". Reports with empty stored
        # md5 ("untagged" = legacy) are kept by default — they
        # logically belong to their generating rawdata even if we
        # can't prove a match, and silently dropping them would hide
        # data the operator may want to see. include_historical=true
        # disables the filter entirely.
        filtered = index_payload
        md5_filter_active = bool(config_md5 or code_md5)
        if md5_filter_active and not include_historical and isinstance(index_payload, list):
            def _matches(entry: dict) -> bool:
                cfg = str(entry.get("rawdata_config_md5") or "")
                code = str(entry.get("rawdata_code_md5") or "")
                if not cfg and not code:
                    return True  # untagged — keep
                # Both md5 dimensions must match when both are passed;
                # when only one is passed (operator targeting either
                # cfg drift or code drift in isolation), the other is
                # treated as wildcard.
                if config_md5 and cfg != config_md5:
                    return False
                if code_md5 and code != code_md5:
                    return False
                return True
            filtered = [
                e for e in index_payload
                if isinstance(e, dict) and _matches(e)
            ]
        return {
            "machine": machine,
            "mode": mode,
            "versions": filtered,
            "latest": latest_payload,
            "filter": {
                "config_md5": config_md5,
                "code_md5": code_md5,
                "include_historical": include_historical,
                "total_unfiltered": len(index_payload) if isinstance(index_payload, list) else 0,
                "total_filtered": len(filtered) if isinstance(filtered, list) else 0,
            },
        }

    @app.get("/api/reports/{machine}/{mode}/{version}")
    def report_version_detail(machine: str, mode: int, version: str) -> dict[str, Any]:
        """Load a specific report version's summary for comparison."""
        summary_path = rr / machine / f"mode_{mode}" / "versions" / version / "player_impact_summary.json"
        if not summary_path.exists():
            raise HTTPException(status_code=404, detail="report version not found")
        return read_json(summary_path) or {}

    @app.delete("/api/reports/{machine}/{mode}/{version}")
    def delete_report_version(machine: str, mode: int, version: str) -> dict[str, Any]:
        """Delete one report version directory + its DB row (if any).

        Works even for ORPHAN versions — disk dirs that lost their
        runs-table row (e.g. from the aggressive cleanup that drops
        tagged-stale rows). The in-UI per-report 删除 button routes
        here for this reason; /api/runs/{rid} 404s on those orphans.

        **Idempotent** (2026-04-21 fix): when the disk dir is already
        gone but index.json still lists the entry ("zombie"), we no
        longer 404 — we finish the cleanup (drop the index.json entry +
        DB row). Before this fix, zombies could never be deleted from
        the UI: the frontend caught the 404 and showed "删除失败",
        leaving the entry visible forever. Root cause: a prior partial
        cleanup (manual rm, interrupted rmtree, import rollback that
        didn't rewind index.json, etc.) leaves the two out of sync;
        the user's intent — "make this report gone" — is equally valid
        whether the disk half is present or absent, so we honor it.

        Steps:
          1. Remove the version directory (shutil.rmtree) if it exists.
          2. Delete the matching DB row if one exists (via run_id
             lookup).
          3. Rewrite index.json without the deleted entry.
          4. If latest.json pointed at this version, rewrite it to
             the newest surviving version (or unlink if none).
          5. 404 ONLY when neither disk nor index.json knows about
             this version — i.e. there's nothing to clean up.
        """
        # Phase 2 (D8 + D9 site #7) / I2 fix: acquire DELETING lock (not
        # GENERATING) for this cell so a concurrent SAMPLING can't race the
        # rmtree. DELETING is mutually exclusive with SAMPLING (INV-1) and
        # GENERATING (INV-2), correctly modelling "I am destroying something".
        if not registry.try_acquire_cell(machine, int(mode), CellOperation.DELETING):
            raise HTTPException(
                status_code=409,
                detail=f"cell {machine}|{mode} is busy — retry after active operation completes",
            )
        try:
            mode_dir = rr / machine / f"mode_{mode}"
            version_dir = mode_dir / "versions" / version
            disk_existed = version_dir.exists()

            # Existence probe: if neither disk nor index.json has this
            # version, genuinely nothing to delete — 404. This keeps
            # the "truly not found" signal intact while fixing zombies.
            index_path = mode_dir / "index.json"
            index_has_entry = False
            if index_path.exists():
                try:
                    raw_probe = read_json(index_path)
                    if isinstance(raw_probe, list):
                        index_has_entry = any(
                            isinstance(e, dict)
                            and e.get("report_version") == version
                            for e in raw_probe
                        )
                except Exception:  # noqa: BLE001
                    pass
            if not disk_existed and not index_has_entry:
                raise HTTPException(
                    status_code=404,
                    detail=f"version not found: {machine}/mode_{mode}/{version}",
                )

            # Find + delete matching DB row (if any) BEFORE wiping
            # disk — the store's delete_run uses the row's file paths
            # to clean progress/summary/report artefacts that might
            # live outside the version dir.
            runs_deleted = 0
            matched_run_id: str | None = None
            for row in store.list_runs(limit=100000):
                if (
                    str(row.get("machine") or "") == machine
                    and int(row.get("mode") or 0) == int(mode)
                    and (row.get("report_version") or "").strip() == version
                ):
                    matched_run_id = str(row.get("run_id") or "")
                    break
            if matched_run_id:
                try:
                    if store.delete_run(matched_run_id):
                        runs_deleted = 1
                except Exception:
                    pass

            # Wipe the version directory — only when it still exists.
            # Missing dir → already partially cleaned, continue to
            # index.json rewrite below. Re-check exists() because
            # delete_run above can rmtree the dir as part of its own
            # cleanup (it uses the runs-row's output_dir path).
            if version_dir.exists():
                try:
                    shutil.rmtree(version_dir)
                except OSError as exc:
                    raise HTTPException(
                        status_code=500,
                        detail=f"rmtree failed: {exc}",
                    ) from exc

            # Rewrite index.json (drop the deleted entry).
            remaining: list[dict] = []
            if index_path.exists():
                try:
                    raw = read_json(index_path)
                    if isinstance(raw, list):
                        remaining = [
                            e for e in raw
                            if isinstance(e, dict)
                            and e.get("report_version") != version
                        ]
                        # Phase 1 deploy: atomic + per-file-locked; mirrors
                        # _update_report_index at app.py:5090. Prevents the
                        # Scenario 16 race: concurrent finalize + delete-version
                        # on same (machine, mode) see same index baseline.
                        atomic_json_write(index_path, remaining)
                except Exception:  # noqa: BLE001
                    pass

            # Rewrite latest.json if it pointed at the deleted version.
            latest_path = mode_dir / "latest.json"
            if latest_path.exists():
                try:
                    latest = read_json(latest_path) or {}
                    if latest.get("report_version") == version:
                        if remaining:
                            survivor = sorted(
                                remaining,
                                key=lambda e: str(e.get("report_version") or ""),
                                reverse=True,
                            )[0]
                            # Phase 1 deploy: atomic write, parallel to
                            # index_path write above.
                            atomic_json_write(latest_path, survivor)
                        else:
                            latest_path.unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    pass

            return {
                "ok": True,
                "deleted_version": version,
                "runs_deleted": runs_deleted,
                "remaining_versions": len(remaining),
                # Tell the caller whether we actually removed a disk
                # dir or just finished a partial cleanup — useful for
                # the UI to distinguish "normal delete" vs "zombie
                # finalize" in the activity log.
                "disk_removed": disk_existed,
            }
        finally:
            registry.release_cell(machine, int(mode), CellOperation.DELETING)

    @app.post("/api/reports/import")
    def import_reports(req: dict[str, Any]) -> dict[str, Any]:
        """Transactionally import reports + DB rows from an external folder.

        Each version goes through three steps:
          1. read source summary (validate)
          2. insert DB row with status="importing"
          3. copytree into reports/
          4. flip DB status to "completed"

        Any step failing rolls back the prior steps (remove partial dst,
        delete DB row). Successful imports are `completed` runs visible
        in 运行历史. Failed versions are reported individually in
        `failures[]` with their stage, so the operator can see exactly
        which leg of the transaction broke.

        Fixes the historical "166/1002 silent import fails" incident by
        making partial state impossible — either a version is fully
        imported (DB row + files) or not at all.
        """
        # Phase 2 (D9 site #11): migrated from ops.acquire to registry global.
        if not registry.try_acquire_global("import_reports"):
            raise HTTPException(status_code=409, detail="import_reports already in progress")
        # Phase 2 (Blocker 4 fix per impl-critic): wrap the ENTIRE function body
        # in a single try/finally so the global lock is always released even if
        # OSError fires in src.iterdir() mid-loop.  The previous code had a
        # try/finally covering only the last ~15 lines (the return statement),
        # leaving the 160-line main loop unprotected — any exception in iterdir()
        # would leak the lock permanently.  Early-release calls removed; the
        # finally handles all exit paths.  Per memory/feedback_no_silent_swallow.md.
        try:
            source = req.get("source_path", "").strip()
            mode_arg = req.get("mode", "merge")
            if not source:
                raise HTTPException(status_code=400, detail="source_path required")
            src = Path(source)
            if not src.is_dir():
                raise HTTPException(status_code=400, detail=f"source_path not a directory: {source}")

            imported = 0
            skipped = 0
            machines_affected: set[str] = set()
            failures: list[dict[str, str]] = []
            MAX_FAILURES_REPORTED = 100

            def _derive_run_id(version_name: str, machine_n: str, mode_n: int) -> str:
                # "rv_20260416T073355Z_9d60553e" → "9d60553e" (real run, globally unique)
                # Anything else (devcache / short suffix) → hash(machine+mode+version_name)
                #   so M1 and M2 with same version timestamp don't collide.
                parts = version_name.split("_")
                tail = parts[-1] if parts else version_name
                if tail not in ("devcache",) and len(tail) >= 8 and all(c in "0123456789abcdef" for c in tail):
                    return tail[:12]
                import hashlib
                key = f"{machine_n}|{mode_n}|{version_name}"
                return hashlib.md5(key.encode()).hexdigest()[:12]

            def _record_failure(stage: str, machine_n: str, mode_n: int,
                                version_name: str, run_id_n: str, exc: BaseException) -> None:
                if len(failures) < MAX_FAILURES_REPORTED:
                    failures.append({
                        "stage": stage,
                        "machine": machine_n, "mode": str(mode_n),
                        "version": version_name, "run_id": run_id_n,
                        "error": f"{type(exc).__name__}: {exc}"[:200],
                    })
                if len(failures) <= 3:
                    import traceback
                    traceback.print_exc()

            def _rollback(run_id_n: str, dst_path: Path) -> None:
                """Undo as much as possible; secondary errors are logged but
                non-fatal so the outer loop keeps processing other versions
                (per feedback_no_silent_swallow.md — log, do not abort)."""
                try:
                    store.delete_run(run_id_n)
                except Exception as exc:  # noqa: BLE001
                    import traceback
                    print(
                        f"[import-reports rollback] store.delete_run({run_id_n!r}) failed: "
                        f"{exc.__class__.__name__}: {exc}",
                        file=sys.stderr,
                    )
                    traceback.print_exc()
                try:
                    if dst_path.exists():
                        shutil.rmtree(dst_path)
                except Exception as exc:  # noqa: BLE001
                    import traceback
                    print(
                        f"[import-reports rollback] rmtree({dst_path!s}) failed: "
                        f"{exc.__class__.__name__}: {exc}",
                        file=sys.stderr,
                    )
                    traceback.print_exc()

            def _import_one(source_v: Path, dst: Path,
                            machine_n: str, mode_n: int) -> bool:
                """Transactional import of one version dir. Returns True on
                full success (DB row + files both committed)."""
                run_id = _derive_run_id(source_v.name, machine_n, mode_n)
                if store.get_run(run_id):
                    run_id = run_id + "_i"

                # 1. Read source summary BEFORE touching DB or dst — we want
                #    rtp/ci/quality values in the initial insert so there's
                #    never a moment where a row exists with placeholder data.
                try:
                    s = json.loads(
                        (source_v / "player_impact_summary.json").read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    _record_failure("read_summary", machine_n, mode_n,
                                    source_v.name, run_id, exc)
                    return False

                sam = s.get("sampling", {})
                rtp_pct = (s.get("rtp", {}) or {}).get("point_pct")
                ci_hw = sam.get("achieved_halfwidth_pp")
                qa = (
                    s.get("guideline_assessment", {}).get("quality_label")
                    or s.get("quality_label")
                )
                row = {
                    "run_id": run_id,
                    "machine": machine_n,
                    "mode": mode_n,
                    "status": "importing",
                    "model_id": "",
                    "created_at": sam.get("started_at") or utc_now(),
                    "started_at": sam.get("started_at") or utc_now(),
                    "finished_at": sam.get("finished_at") or utc_now(),
                    "target_halfwidth_pp": sam.get("target_halfwidth_pp") or 0.5,
                    "chunk_spin_times": sam.get("chunk_spin_times") or 0,
                    "chunk_robot_count": sam.get("chunk_robot_count") or 0,
                    "batch_concurrency": sam.get("batch_concurrency") or 1,
                    "max_chunks": sam.get("chunks") or 0,
                    "timeout": 300.0,
                    "bankruptcy_session_spins": 10000,
                    "bankruptcy_bankroll_multipliers": "10,100,200,500",
                    "report_version": source_v.name,
                    "output_dir": str(dst),
                    "progress_file": str(dst / "progress.jsonl"),
                    "summary_file": str(dst / "player_impact_summary.json"),
                    "report_file": str(dst / "player_impact_report.md"),
                    "error_message": None,
                    "process_pid": 0,
                    "achieved_rtp_pct": rtp_pct,
                    "achieved_halfwidth_pp": ci_hw,
                    "quality_label": qa,
                }

                # 2. Insert placeholder row.
                try:
                    store.insert_run(row)
                except Exception as exc:  # noqa: BLE001
                    _record_failure("insert_run", machine_n, mode_n,
                                    source_v.name, run_id, exc)
                    return False

                # 3. Copy files. Rollback row + partial dst on any failure.
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(source_v, dst)
                except Exception as exc:  # noqa: BLE001
                    _rollback(run_id, dst)
                    _record_failure("copytree", machine_n, mode_n,
                                    source_v.name, run_id, exc)
                    return False

                # 4. Flip status → completed. If this tiny final update fails,
                #    we roll back the whole thing rather than leave a row
                #    stuck at "importing" forever (operator re-imports cleanly).
                try:
                    store.update_run(run_id, {"status": "completed"})
                except Exception as exc:  # noqa: BLE001
                    _rollback(run_id, dst)
                    _record_failure("update_status", machine_n, mode_n,
                                    source_v.name, run_id, exc)
                    return False

                return True

            for machine_dir in src.iterdir():
                if not machine_dir.is_dir():
                    continue
                machine_name = machine_dir.name
                dst_machine = rr / machine_name
                if mode_arg == "replace" and dst_machine.is_dir():
                    shutil.rmtree(dst_machine)
                for mode_dir in machine_dir.iterdir():
                    if not mode_dir.is_dir() or not mode_dir.name.startswith("mode_"):
                        continue
                    try:
                        mode_int = int(mode_dir.name.split("_")[1])
                    except (IndexError, ValueError):
                        continue
                    versions_dir = mode_dir / "versions"
                    if not versions_dir.is_dir():
                        continue
                    for v in versions_dir.iterdir():
                        if not v.is_dir():
                            continue
                        if not (v / "player_impact_summary.json").exists():
                            continue
                        dst = rr / machine_name / mode_dir.name / "versions" / v.name
                        if dst.exists():
                            skipped += 1
                            continue
                        if _import_one(v, dst, machine_name, mode_int):
                            imported += 1
                            machines_affected.add(machine_name)

            # Refresh static attrs from imported reports. Re-bootstrap
            # across the fleet (simpler than per-machine merge; import is
            # infrequent).
            if imported > 0:
                try:
                    _bootstrap_static_attrs(rr, mc, _static_attrs_path(mc))
                except Exception:  # noqa: BLE001
                    pass

            return {
                "imported": imported,
                "skipped": skipped,
                "failed": len(failures),
                "failures": failures,
                "machines_affected": sorted(machines_affected),
            }
        finally:
            registry.release_global("import_reports")

    @app.post("/api/maintenance/prune-versions")
    def prune_versions_endpoint(req: dict[str, Any] | None = None) -> dict[str, Any]:
        """Keep the newest N version dirs per (machine, mode); delete rest.

        Body: `{"keep": 5, "dry_run": false}` — both optional; default
        keep=5 matches the CLI. Active runs (status in {"running",
        "importing"}) are always skipped so we don't race a writer.
        """
        # Phase 2 (D9 site #9): migrated from ops.acquire to registry global.
        if not registry.try_acquire_global("prune_versions"):
            raise HTTPException(status_code=409, detail="prune_versions already in progress")
        try:
            from src.web_console.backend.reports_retention import prune_versions
            body = req or {}
            keep = int(body.get("keep", 5))
            dry_run = bool(body.get("dry_run", False))
            if keep < 1:
                raise HTTPException(status_code=400, detail="keep must be >= 1")
            return prune_versions(
                reports_root=rr, store=store, keep_last=keep, dry_run=dry_run,
            )
        finally:
            registry.release_global("prune_versions")

    def _do_refresh_machines_md5(
        server_id: str = "dev", *, raise_on_error: bool = True,
    ) -> dict[str, Any]:
        """Core md5-refresh work shared between the explicit endpoint
        and the pre-batch auto-refresh. Fetches the active server's
        MachineConfigMd5 and updates ``machines.json`` entries with
        the latest md5, **fanning out** each underlying-machine md5
        across all of its registered variants.

        ``raise_on_error=True`` (default, for the explicit endpoint):
        upstream failures surface as HTTPException so the UI shows
        a clear error.
        ``raise_on_error=False`` (for the pre-batch auto-refresh):
        swallow network/config errors and return a dict with
        ``ok: False`` so the batch can continue with stale local
        md5 rather than fail the operator's sampling run on a
        transient upstream hiccup.

        **Variant fanout (stage 3 of variants rollout)**: upstream
        ``MachineConfigMd5`` reports md5 per underlying machine key
        (``M273`` / ``M201`` / ...) — it has no notion of variants.
        Our ``machines.json`` entries are independent-machine rows
        (``M273$0$`` / ``M273$1$1-2-3`` / ...). The
        ``variants_map`` from ``configs/machine_halls.json`` resolves
        each entry to the upstream key whose md5 it inherits. Empty
        map (fresh deployment) → every entry resolves to itself, so
        the refresh degrades to the pre-variants behavior and 227
        non-variant machines keep working.

        **Discovery boundary**: when upstream reports a machine we
        haven't seen locally:
          * if the upstream key is ``variants_map.values()`` (i.e.
            it's an underlying whose variants should own the md5),
            we DO NOT create a bare row for it — that row would
            shadow the variant rows during md5 resolution
          * otherwise (genuinely new non-variant machine), we create
            a row keyed by the upstream name, same as the legacy path

        Returns ``{ok, server_id, machines_fetched, machines_updated,
        updated_machines, skipped_empty_upstream, unresolved_entries,
        error?}``. ``unresolved_entries`` lists machine rows whose
        resolved upstream key wasn't in the response — operators see
        this when a variant row exists locally but its underlying
        has been decommissioned upstream (shouldn't happen on a
        healthy deployment; surfacing it avoids silent drift).

        **Virtual console override**: when create_app was given
        ``md5_refresh_override=<callable>`` (2026-04-21 isolation fix),
        this function delegates to that callable and short-circuits
        the upstream fetch. Virtual consoles use this to recompute
        local md5 from spec + weights + engine source instead of
        pulling from production API — without this, upstream fleet
        (253 real machines) gets merged into the virtual registry
        and breaks data isolation.
        """
        if md5_refresh_override is not None:
            try:
                return md5_refresh_override(server_id)
            except Exception as exc:
                if raise_on_error:
                    raise HTTPException(status_code=500, detail=str(exc))
                return {"ok": False, "error": str(exc), "server_id": server_id,
                        "machines_fetched": 0, "machines_updated": 0}
        cfg = load_servers(sc)
        target = next((s for s in cfg.get("servers", []) if s["id"] == server_id), None)
        if target is None:
            msg = f"server '{server_id}' not found"
            if raise_on_error:
                raise HTTPException(status_code=404, detail=msg)
            return {"ok": False, "error": msg, "server_id": server_id,
                    "machines_fetched": 0, "machines_updated": 0,
                    "updated_machines": []}
        ep = target.get("endpoint", "").strip()
        if not ep:
            msg = "server has no endpoint configured"
            if raise_on_error:
                raise HTTPException(status_code=400, detail=msg)
            return {"ok": False, "error": msg, "server_id": server_id,
                    "machines_fetched": 0, "machines_updated": 0,
                    "updated_machines": []}
        data = _fetch_machine_config_md5(ep)
        if data is None:
            msg = "failed to fetch MachineConfigMd5"
            if raise_on_error:
                raise HTTPException(status_code=502, detail=msg)
            return {"ok": False, "error": msg, "server_id": server_id,
                    "machines_fetched": 0, "machines_updated": 0,
                    "updated_machines": []}

        # Load variants map for fanout. The map is operator-refreshed
        # via /api/machines/halls/refresh; a missing / empty map
        # degrades cleanly to identity resolution (legacy behavior).
        from src.web_console.backend.machine_variants import (
            apply_md5_refresh, load_variants_map,
        )
        halls_path = ROOT / "configs" / "machine_halls.json"
        variants_map = load_variants_map(halls_path)

        # Phase 1 deploy: atomic read-modify-write under per-file lock
        # closes the Critical C1 race (Scenario 16) where two concurrent
        # callers (pre-batch async refresh + explicit
        # /api/machines/refresh-md5) truncate and write machines.json
        # simultaneously, silently wiping all 393 rows from the fleet
        # registry. The per-file lock held across read+apply+write
        # makes the operation serializable.
        # Optional A (Phase 1 fix): single-element dict replaces the list-append
        # pattern. If atomic_json_read_modify_write ever gains internal retry
        # semantics, `[0]` would return stale stats from the first (failed)
        # attempt; the dict-set pattern always reflects the final call's stats.
        _stats_holder: dict[str, dict] = {}

        def _apply(current: Any) -> dict:
            base = current if isinstance(current, dict) else {"machines": []}
            updated, stats_local = apply_md5_refresh(
                base, data, variants_map,
            )
            _stats_holder["stats"] = stats_local
            return updated

        existing = atomic_json_read_modify_write(
            Path(mc), _apply, default={"machines": []},
            trailing_newline=True,
        )
        stats = _stats_holder["stats"]
        _save_server_snapshot(server_id, data)
        return {
            "ok": True,
            "server_id": server_id,
            "machines_fetched": len(data),
            "machines_updated": stats["updated_count"],
            "updated_machines": stats["updated_machines"],
            "skipped_empty_upstream": stats["skipped_empty_upstream"],
            "unresolved_entries": stats["unresolved_entries"],
            "discovered_machines": stats["discovered_machines"],
            "variants_map_size": len(variants_map),
        }

    @app.post("/api/machines/refresh-md5")
    def refresh_machines_md5(req: dict[str, Any] | None = None) -> dict[str, Any]:
        """Fetch current MachineConfigMd5 from the active server and update machines.json.

        After this, report-validate will reflect the latest upstream MD5.
        Optionally takes {"server_id": "..."} to pick a specific server;
        defaults to the resolver's pick (default_server → first active),
        keeping symmetric with batch-run / autotune / halls-refresh.
        """
        payload = req or {}
        server_id = (
            payload.get("server_id")
            or _resolve_active_server_id(settings_path=settings_path)
            or "dev"
        )
        return _do_refresh_machines_md5(server_id, raise_on_error=True)

    @app.get("/api/report-validate/{machine}")
    def validate_machine_reports(machine: str) -> dict[str, Any]:
        """Check each report's stored MD5 + analyzer version against current.

        Per-report status: md5_status (match / outdated / untagged) +
        analyzer_status (match / outdated / untagged). Frontend surfaces
        both as small badges next to each report row.

        Honesty-3 (2026-05-29): analyzer_status is now based on per-mode
        ``effective_analyzer_version`` (from the summary) vs the current
        per-(machine, mode) effective hash. Machines with no manifest are
        "unverifiable" — status "untagged", not "outdated".
        ``report_effective_version`` is added to each result row so
        the frontend badge (versionBadges via rwtree) can compare against
        current.effective_versions[machine|mode] directly.
        ``current_analyzer_version`` is kept for display/back-compat.
        """
        from fresh_slotlab.analyzer.versioning import compute_analyzer_version
        from src.web_console.backend.effective_version_cache import EffectiveVersionCache
        # Machine-level aggregate (used as response-level hint so
        # frontend can show "current cfg md5" at the card header).
        up_config, up_code = _get_machine_md5(machine, mc)
        current_analyzer = compute_analyzer_version()
        if not up_config and not up_code:
            return {
                "machine": machine, "unverifiable": True, "reports": [],
                "current_analyzer_version": current_analyzer,
            }
        results = []
        machine_dir = rr / machine
        if not machine_dir.is_dir():
            return {
                "machine": machine, "unverifiable": False, "reports": [],
                "current_analyzer_version": current_analyzer,
            }
        # Per-request effective-version cache (R-7): one instance for this
        # endpoint call, shared across all mode_dirs. Computes base_hash once.
        eff_cache = EffectiveVersionCache()
        for mode_dir in machine_dir.iterdir():
            if not mode_dir.is_dir() or not mode_dir.name.startswith("mode_"):
                continue
            try:
                mode_val = int(mode_dir.name.split("_")[1])
            except (IndexError, ValueError):
                continue
            # Per-mode md5 for the comparison — virtual machines with
            # different reel strips per mode have distinct md5s, which
            # the machine-level aggregate can't represent (2026-04-22).
            # Real machines (no modesMd5 map) fall through to the
            # aggregate via _get_machine_md5's fallback path.
            mode_cfg, mode_code = _get_machine_md5(machine, mc, mode=mode_val)
            # Current per-(machine, mode) effective for analyzer comparison.
            try:
                cur_eff = eff_cache.get(machine, mode_val)
            except FileNotFoundError:
                # Closure file missing (broken install) — surface it.
                raise
            versions_dir = mode_dir / "versions"
            if not versions_dir.is_dir():
                continue
            for v in versions_dir.iterdir():
                if not v.is_dir():
                    continue
                sf = v / "player_impact_summary.json"
                if not sf.exists():
                    continue
                try:
                    s = json.loads(sf.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                rpt_config = str(s.get("config_md5", ""))
                rpt_code = str(s.get("code_md5", ""))
                # Honesty-3: use effective_analyzer_version for the staleness
                # decision. Legacy analyzer_version kept for display only.
                rpt_effective = str(s.get("effective_analyzer_version", ""))
                rpt_analyzer = str(s.get("analyzer_version", ""))
                if not rpt_config and not rpt_code:
                    md5_status = "untagged"
                elif rpt_config == mode_cfg and rpt_code == mode_code:
                    md5_status = "match"
                else:
                    md5_status = "outdated"
                # analyzer_status based on effective (per-machine/mode):
                #   - no rpt_effective → untagged (pre-honesty-3 legacy)
                #   - no cur_eff (UNVERIFIABLE) → untagged (no manifest)
                #   - match → "match"; mismatch → "outdated"
                if not rpt_effective:
                    analyzer_status = "untagged"
                elif cur_eff == EffectiveVersionCache.UNVERIFIABLE or not cur_eff:
                    analyzer_status = "untagged"
                elif rpt_effective == cur_eff:
                    analyzer_status = "match"
                else:
                    analyzer_status = "outdated"
                results.append({
                    "mode": mode_val, "version": v.name,
                    "md5_status": md5_status,
                    "analyzer_status": analyzer_status,
                    "report_config_md5": rpt_config, "report_code_md5": rpt_code,
                    "report_analyzer_version": rpt_analyzer,
                    # Honesty-3: per-mode effective; the rwtree badge compares
                    # this against current.effective_versions[machine|mode].
                    "report_effective_version": rpt_effective,
                })
        return {
            "machine": machine, "unverifiable": False,
            "upstream_config_md5": up_config, "upstream_code_md5": up_code,
            "current_analyzer_version": current_analyzer,
            "reports": results,
        }

    @app.post("/api/reports/cleanup")
    def cleanup_old_reports() -> dict[str, Any]:
        """Prune redundant DUPLICATE report versions — per-mode, recency
        dedup WITHIN a single analyzer-tag class. An analyzer-version
        mismatch NEVER selects a version for deletion.

        Honesty-1 (2026-05-29, `feedback_md5_is_a_tag_not_a_destruction_signal.md`
        + `feedback_enumerate_safety_paths.md`): a version/staleness tag
        is a classification signal, NOT a destruction trigger. The prior
        policy deleted every analyzer-stale version from disk + DB (and a
        DB second-pass dropped every run row whose analyzer_version !=
        current). At the upcoming honest-signal cutover — which marks
        every machine stale exactly once when the signal's definition
        changes — that coupling would wipe the whole fleet's reports.
        So staleness is decoupled from deletion here: stale-analyzer and
        untagged versions are KEPT regardless of recency.

        What this still does (genuine, non-verdict disk hygiene only):
          for each (machine, mode), within the survivor's analyzer-tag
          class, drop OLDER exact-tag DUPLICATES (operator freeing disk,
          keeping the newest of an equivalent class). Cross-class
          deletion keyed on a tag mismatch is removed entirely. If the
          only reason to delete a version would be its analyzer tag,
          nothing is deleted.

        Interim cosmetic (intended): the "清理过期" banner may now show a
        non-zero analyzer-stale count that clicking no longer zeros by
        deletion. That is resolved when the honest signal + the
        needs_rebaseline lifecycle land (honesty-3). The lock, the
        index.json/latest.json rewrite, and the no_silent_swallow
        diagnostics still apply to whatever duplicates are pruned.
        """
        # Phase 2 (D9 site #10): migrated from ops.acquire to registry global.
        if not registry.try_acquire_global("reports_cleanup"):
            raise HTTPException(status_code=409, detail="reports_cleanup already in progress")
        try:
            # Honesty-1 (2026-05-29): the current analyzer version is
            # deliberately NOT computed or consulted here anymore. This
            # endpoint no longer makes ANY delete decision from an
            # analyzer-version (mis)match — it only dedups exact-tag
            # duplicate versions. compute_analyzer_version() still backs the
            # read-only /api/reports/stale-count + validate endpoints.
            rv_to_run_id: dict[str, str] = {}
            for row in store.list_runs(limit=100000):
                rv = (row.get("report_version") or "").strip()
                if rv:
                    rv_to_run_id[rv] = row.get("run_id", "")

            def _version_analyzer(v_dir: Path) -> str:
                sf = v_dir / "player_impact_summary.json"
                if not sf.exists():
                    return ""
                try:
                    s = json.loads(sf.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return ""
                return str(s.get("analyzer_version", "") or "")

            deleted = 0
            kept = 0
            runs_deleted = 0
            for machine_dir in rr.iterdir():
                if not machine_dir.is_dir():
                    continue
                for mode_dir in machine_dir.iterdir():
                    if not mode_dir.is_dir():
                        continue
                    versions_dir = mode_dir / "versions"
                    if not versions_dir.is_dir():
                        continue
                    versions = sorted(
                        [v for v in versions_dir.iterdir() if v.is_dir()],
                        reverse=True,  # newest first
                    )
                    if not versions:
                        continue

                    # Cleanup policy (honesty-1, 2026-05-29): the survivor
                    # is the newest version overall, so every mode always
                    # keeps a loadable baseline regardless of analyzer tag.
                    # We prune ONLY older versions whose analyzer tag is
                    # BYTE-IDENTICAL to the survivor's — i.e. superseded
                    # exact-duplicates of the SAME version (recency dedup,
                    # operator freeing disk). A version is NEVER deleted
                    # because its tag mismatches the current analyzer (or
                    # the survivor's) — a version tag classifies, it does
                    # not destroy (`feedback_md5_is_a_tag_not_a_destruction_signal`).
                    # The current analyzer version is intentionally NOT
                    # consulted here for any delete decision (it backs only
                    # the read-only banner endpoints). This is what stops the
                    # honest-signal cutover (every machine marked stale
                    # exactly once) from wiping the fleet's reports.
                    survivor = versions[0]
                    survivor_tag = _version_analyzer(survivor)
                    to_delete = [
                        v for v in versions[1:]
                        if _version_analyzer(v) == survivor_tag
                    ]
                    kept += 1

                    for old in to_delete:
                        rv_name = old.name
                        shutil.rmtree(old, ignore_errors=True)
                        deleted += 1
                        run_id = rv_to_run_id.get(rv_name)
                        if run_id:
                            try:
                                if store.delete_run(run_id):
                                    runs_deleted += 1
                            except Exception as exc:
                                # Per feedback_no_silent_swallow.md — this
                                # prune path survives honesty-1, so its
                                # best-effort DB delete must still persist a
                                # diagnostic, not swallow silently.
                                import traceback
                                print(
                                    f"[cleanup-old-reports] store.delete_run({run_id!r}) "
                                    f"failed during duplicate prune: "
                                    f"{exc.__class__.__name__}: {exc}",
                                    file=sys.stderr,
                                )
                                traceback.print_exc()

                    # Rewrite index.json to drop ONLY the entries for the
                    # versions we actually pruned (older exact-tag duplicates),
                    # keeping every surviving version's entry so the
                    # version-history panel still lists them. Mirrors the
                    # explicit per-version DELETE endpoint's "drop the deleted
                    # entry" rewrite (app.py:10385). Under honesty-1 the survivor
                    # is NO LONGER the only kept version (distinct-tag versions
                    # survive), so collapsing the index to the survivor alone
                    # would orphan still-on-disk reports from the UI version list.
                    if to_delete:
                        survivor_name = survivor.name
                        deleted_names = {old.name for old in to_delete}
                        index_path = mode_dir / "index.json"
                        if index_path.exists():
                            try:
                                idx = read_json(index_path)
                                if isinstance(idx, list):
                                    idx = [e for e in idx if isinstance(e, dict)
                                           and e.get("report_version") not in deleted_names]
                                    # Phase 1 deploy: atomic + per-file-locked;
                                    # mirrors _update_report_index. Prune +
                                    # concurrent finalize on same (m, mode) could
                                    # race without this; now serialized.
                                    atomic_json_write(index_path, idx)
                            except Exception as exc:
                                # Per feedback_no_silent_swallow.md
                                import traceback
                                print(
                                    f"[cleanup-old-reports] index.json rewrite failed "
                                    f"for {machine_dir.name}|{mode_dir.name}: {exc.__class__.__name__}: {exc}",
                                    file=sys.stderr,
                                )
                                traceback.print_exc()
                        # latest.json points at the newest version. If it was
                        # left pointing at a pruned duplicate, repoint it at the
                        # survivor (always the newest, so under honesty-1 it
                        # always exists — there is no no-survivor case).
                        latest_path = mode_dir / "latest.json"
                        if latest_path.exists():
                            try:
                                latest = read_json(latest_path) or {}
                                if latest.get("report_version") != survivor_name:
                                    # Point latest at the survivor.
                                    latest["report_version"] = survivor_name
                                    # Phase 1 deploy: atomic write, parallel
                                    # to index_path write above.
                                    atomic_json_write(latest_path, latest)
                            except Exception as exc:
                                # Per feedback_no_silent_swallow.md
                                import traceback
                                print(
                                    f"[cleanup-old-reports] latest.json rewrite failed "
                                    f"for {machine_dir.name}|{mode_dir.name}: {exc.__class__.__name__}: {exc}",
                                    file=sys.stderr,
                                )
                                traceback.print_exc()

            # Honesty-1 (2026-05-29): the DB "second pass" that deleted
            # EVERY run row whose analyzer_version != cur_analyzer (with no
            # disk coupling) has been REMOVED. Dropping a run row purely
            # because its analyzer tag mismatches the current one is the
            # exact tag-as-destruction anti-pattern this phase kills
            # (`feedback_md5_is_a_tag_not_a_destruction_signal`). The
            # /api/reports/stale-count banner may now report a non-zero
            # analyzer-stale count that this endpoint no longer zeros by
            # deletion; that interim cosmetic is intended and resolved by
            # the honest signal + needs_rebaseline lifecycle (honesty-3).
            return {
                "ok": True, "deleted": deleted, "kept": kept,
                "runs_deleted": runs_deleted,
            }
        finally:
            registry.release_global("reports_cleanup")

    @app.get("/api/fleet/export-csv")
    def export_fleet_csv() -> Any:
        """Export fleet summary as CSV for offline analysis."""
        import csv
        import io
        summary = _build_machines_summary(rr, _cs=app_cache)
        machines_data = summary.get("machines", {})
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["machine", "mode", "rtp_pct", "ci_halfwidth_pp", "total_spins",
                          "volatility_class", "volatility_percentile", "zero_win_rate",
                          "tail_ge10x", "mechanics", "report_version"])
        for machine in sorted(machines_data.keys(),
                              key=lambda k: int(k[1:]) if k[1:].isdigit() else 0):
            modes = machines_data[machine]
            for mode in sorted(modes.keys(), key=int):
                d = modes[mode]
                writer.writerow([
                    machine, mode,
                    round(d.get("rtp_pct") or 0, 4),
                    round(d.get("ci_halfwidth_pp") or 0, 4) if d.get("ci_halfwidth_pp") is not None else "",
                    d.get("total_spins", 0),
                    d.get("volatility_class", ""),
                    d.get("volatility_percentile", ""),
                    round(d.get("zero_win_rate", 0), 6),
                    round(d.get("tail_ge10x", 0), 6),
                    "|".join(d.get("mechanics", [])),
                    d.get("report_version", ""),
                ])
        from starlette.responses import Response
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=fleet_summary.csv"},
        )

    @app.get("/api/library/distributions")
    def library_distributions(mode: int | None = None) -> dict[str, Any]:
        """Across-library metric distributions built from every
        reports/<machine>/mode_<n>/latest.json + its summary JSON.

        Used by the frontend to show "lib-P87 (15/17)" style relative
        ranking on KPI cards so the operator sees where the current
        machine stands within the whole library instead of reading
        absolute numbers in isolation.

        When ``mode`` is supplied (e.g. ``?mode=1``) only that mode's
        reports contribute to the distribution — prevents comparing a
        mode 1 baseline machine against a mode 5 bonus-mode machine
        where the RTP / volatility ranges are inherently different.
        Without the filter, the distribution mixes all modes (legacy
        behavior preserved for backward-compat callers).

        Scales linearly with the number of (machine, mode) pairs --
        each one is a single JSON read. For hundreds of machines
        this runs in well under a second; no caching needed.

        Shape:
            {
              "machines_count": N,
              "mode": N or null,
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
        mode_filter: int | None = int(mode) if mode is not None else None

        if not rr.exists():
            return {
                "machines_count": 0,
                "mode": mode_filter,
                "metrics": {},
                "archetype_counts": {},
                "volatility_class_counts": {},
            }
        for machine_dir in sorted(rr.iterdir()):
            if not machine_dir.is_dir():
                continue
            mode_glob = f"mode_{mode_filter}" if mode_filter is not None else "mode_*"
            for mode_dir in sorted(machine_dir.glob(mode_glob)):
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
            "mode": mode_filter,
            "metrics": {
                k: {"values": v, "count": len(v)} for k, v in metric_values.items()
            },
            "archetype_counts": dict(archetype_counts),
            "volatility_class_counts": dict(volatility_class_counts),
        }

    def _enumerate_rawdata_deletable(
        *,
        respect_locks: bool = True,
        respect_in_use: bool = True,
    ) -> list[dict[str, Any]]:
        """Walk rd_root, classify each (machine, mode), return the
        aggregate deletable list — chunks that are safe to reclaim
        (stale MD5 + valid chunks above retention quota). Sorted by
        mtime so oldest-first deletion is a single pass downstream.

        ``respect_locks`` filters out (machine, mode) pairs present in
        ``configs/rawdata_locks.json`` (operator carve-outs). Both
        manual "一键清理" and auto-cleanup should leave locks alone.
        ``respect_in_use`` filters out pairs currently being sampled
        or analyzed — dropping chunks mid-run would corrupt in-flight
        work.
        """
        retention = _load_settings(settings_path)["min_retention_spins"]
        locks = _load_rawdata_locks(_rawdata_locks_path(mc)) if respect_locks else set()
        # Phase 2: use registry.get_active_cells() instead of removed _get_in_use_snapshot.
        in_use = registry.get_active_cells() if respect_in_use else set()
        candidates: list[dict[str, Any]] = []
        if not rd_root.is_dir():
            return candidates
        for machine_dir in rd_root.iterdir():
            if not machine_dir.is_dir() or not machine_dir.name.startswith("M"):
                continue
            for mode_dir in machine_dir.iterdir():
                if not mode_dir.is_dir() or not mode_dir.name.startswith("mode_"):
                    continue
                try:
                    mode = int(mode_dir.name.split("_", 1)[1])
                except (IndexError, ValueError):
                    continue
                key = (machine_dir.name, mode)
                if key in locks or key in in_use:
                    continue
                cls = _classify_chunks(
                    machine_dir.name, mode, rd_root, mc, retention,
                )
                # Cleanable pool = deletable (current md5 above
                # retention) + historical (other md5s, no retention
                # protection). Sorted by mtime below so cleanup runs
                # oldest-first regardless of md5 — md5 is a tag, not
                # a priority signal.
                for entry in cls["deletable"] + cls["historical"]:
                    candidates.append({
                        "machine": machine_dir.name, "mode": mode,
                        "path": entry["path"], "spins": entry["spins"],
                        "mtime": entry["mtime"],
                    })
        candidates.sort(key=lambda e: e["mtime"])
        return candidates

    @app.get("/api/cache/status")
    def cache_status() -> dict[str, Any]:
        """Cache + rawdata usage snapshot.

        The historical ``cache/chunks`` root is kept for legacy
        reporting but the meaningful numbers now come from RAWDATA_ROOT
        (where actual chunks live). ``reclaimable_bytes_estimate`` is
        computed via the tiered classifier so the UI shows the real
        amount that /api/cache/cleanup would free.
        """
        cache_total, cache_files = folder_bytes(cr)
        rawdata_total, rawdata_files = folder_bytes(rd_root)
        running = store.list_runs_by_status("running", limit=2000)
        # Approximation only: using full rawdata size as the reclaimable
        # estimate. The real number (stale + above-retention chunks) is
        # computed inside /api/cache/cleanup — doing it here would force
        # a per-chunk JSON parse over every mode dir on every status
        # poll (~1 min for 1k chunks), which blocks the UI. The risk-tier
        # display only needs rough magnitude, so
        # reclaimable == total_bytes stays on the safe side (cleanup
        # never exceeds this; baseline is always preserved).
        reclaimable = rawdata_total if not running else 0
        return {
            # Legacy cache/chunks root — always empty in the current
            # sampling flow but kept in the response so older clients
            # don't break.
            "cache_root": str(cr),
            "cache_total_bytes": cache_total,
            "cache_file_count": cache_files,
            # Authoritative rawdata numbers (what operators actually
            # care about).
            "rawdata_root": str(rd_root),
            "rawdata_total_bytes": rawdata_total,
            "rawdata_file_count": rawdata_files,
            # Back-compat keys (previously reported CACHE_ROOT totals).
            # Frontends that still read these now see the rawdata
            # numbers since that's the useful signal.
            "total_bytes": rawdata_total,
            "file_count": rawdata_files,
            "running_runs": len(running),
            "reclaimable_bytes_estimate": reclaimable,
            "risk_thresholds": resolved_risk_thresholds(),
        }

    @app.post("/api/cache/cleanup")
    def cache_cleanup(req: CacheCleanupRequest) -> dict[str, Any]:
        """Tier-based cleanup over RAWDATA_ROOT.

        Protected by the retention quota (setting
        ``min_retention_spins``, default 100k) so baseline chunks
        survive even here. Additionally, (machine, mode) pairs locked
        by the operator via ``/api/rawdata/{m}/mode/{mode}/lock`` are
        skipped entirely, and any pair currently being sampled or
        analyzed is skipped to avoid corrupting in-flight work.
        Deletion order is oldest mtime across all remaining pairs —
        caller optionally caps total bytes freed via
        ``max_delete_bytes``.
        """
        running = store.list_runs_by_status("running", limit=2000)
        if running:
            return {
                "deleted_files": 0,
                "deleted_bytes": 0,
                "message": "cleanup blocked while runs are active",
            }
        # Phase 2 (D9 site #8): migrated from ops.acquire to registry global.
        if not registry.try_acquire_global("disk_cleanup"):
            raise HTTPException(status_code=409, detail="disk_cleanup already in progress")

        try:
            deleted_files = 0
            deleted_bytes = 0
            affected_modes: set[tuple[str, int]] = set()
            # Snapshot lock / in-use carve-outs BEFORE enumeration so
            # the response can explain what was preserved. Enumeration
            # itself re-reads these internally (single source of truth
            # via the ``respect_*`` kwargs).
            locked_pairs = _load_rawdata_locks(_rawdata_locks_path(mc))
            # Phase 2: use registry.get_active_cells() instead of removed _get_in_use_snapshot.
            in_use_pairs = registry.get_active_cells()
            targets = _enumerate_rawdata_deletable(
                respect_locks=True, respect_in_use=True,
            )
            max_delete = req.max_delete_bytes if req.max_delete_bytes > 0 else (10**18)
            # Bucket unlinked filenames per (machine, mode) so we can
            # batch-update the per-mode `_chunks.json` sidecar with one
            # write per affected mode at the end. See _auto_cleanup_for_
            # space() for the same pattern.
            unlinked_by_mode: dict[tuple[str, int], list[str]] = {}
            for entry in targets:
                p = Path(entry["path"])
                try:
                    size = p.stat().st_size
                except OSError:
                    continue
                if deleted_bytes + size > max_delete:
                    break
                try:
                    p.unlink()
                except OSError:
                    continue
                deleted_files += 1
                deleted_bytes += size
                affected_modes.add((entry["machine"], entry["mode"]))
                unlinked_by_mode.setdefault(
                    (entry["machine"], int(entry["mode"])), [],
                ).append(p.name)
            # Refresh the rawdata index for each affected (machine, mode)
            # so subsequent GET /api/rawdata sees the reduced chunk count
            # without a cold-path rescan.
            try:
                from fresh_slotlab.rawdata_index import update_entry, remove_entry
                from fresh_slotlab.chunk_index import bulk_remove_chunk_entries
                for (m, mode), names in unlinked_by_mode.items():
                    md = rd_root / m / f"mode_{mode}"
                    bulk_remove_chunk_entries(md, names)
                for m, mode in affected_modes:
                    md = rd_root / m / f"mode_{mode}"
                    if md.is_dir() and any(md.glob("chunk_*.json")):
                        update_entry(rd_root, m, mode, md)
                    else:
                        remove_entry(rd_root, m, mode)
            except Exception:  # noqa: BLE001
                pass
            return {
                "deleted_files": deleted_files,
                "deleted_bytes": deleted_bytes,
                "skipped_locked": [
                    {"machine": m, "mode": mode} for m, mode in sorted(locked_pairs)
                ],
                "skipped_in_use": [
                    {"machine": m, "mode": mode} for m, mode in sorted(in_use_pairs)
                ],
            }
        finally:
            registry.release_global("disk_cleanup")

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

    # Phase 2 (D11): disk monitor daemon thread — periodically triggers
    # _auto_cleanup_for_space if free space drops below the low-water mark.
    # Sequenced AFTER all D10 registry-aware _auto_cleanup_for_space edits
    # are in place (same commit, later in create_app body).
    # Env vars mirror BatchRunManager._run_one disk-pressure loop defaults.
    def _disk_monitor_loop() -> None:
        import time as _time
        low_water = float(os.environ.get("SLOT_DISK_LOW_WATER_GB") or 5.0)
        target_free = float(os.environ.get("SLOT_DISK_TARGET_FREE_GB") or 10.0)
        interval = int(os.environ.get("SLOT_DISK_MONITOR_INTERVAL_S") or 60)
        while True:
            _time.sleep(interval)
            try:
                disk = _get_disk_space_info(rd_root)
                if disk["free_gb"] < low_water:
                    retention = _load_settings(settings_path).get(
                        "min_retention_spins", _RAWDATA_MIN_RETENTION_SPINS_DEFAULT
                    )
                    _auto_cleanup_for_space(
                        rd_root, mc, retention,
                        target_free_gb=target_free,
                        low_water_gb=low_water,
                        registry=registry,
                    )
            except Exception:  # noqa: BLE001 — daemon; must not crash
                import traceback
                traceback.print_exc()

    # ── Phase 3 (D1): Config upload endpoints ──────────────────────────
    import hashlib as _hashlib

    # I5 fix: use injected path when provided (test isolation + e2e harness);
    # fall back to module-level constant for production use.
    configs_upload_dir = configs_upload_dir if configs_upload_dir is not None else CONFIGS_UPLOAD_DIR
    configs_upload_dir.mkdir(parents=True, exist_ok=True)
    _configs_registry_path = configs_upload_dir / "_registry.json"

    @app.post("/api/configs/upload")
    def upload_config(req: dict[str, Any]) -> dict[str, Any]:
        """Upload a config JSON. Computes config_id = sha1(content).
        Idempotent: uploading the same content twice with the same
        display_name is a no-op; with a different display_name adds
        an alias entry to the registry.

        Body: {content: <JSON string or dict>, display_name: str}
        """
        raw_content = req.get("content")
        display_name = str(req.get("display_name") or "").strip() or "unnamed"
        if raw_content is None:
            raise HTTPException(status_code=400, detail="content is required")
        # Normalise to canonical JSON string.
        if isinstance(raw_content, dict):
            try:
                content_str = json.dumps(raw_content, ensure_ascii=False,
                                         sort_keys=True, separators=(",", ":"))
                parsed_content = raw_content
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400,
                                    detail=f"content is not JSON-serialisable: {exc}")
        elif isinstance(raw_content, str):
            try:
                parsed_content = json.loads(raw_content)
                content_str = json.dumps(parsed_content, ensure_ascii=False,
                                         sort_keys=True, separators=(",", ":"))
            except (json.JSONDecodeError, TypeError) as exc:
                raise HTTPException(status_code=400,
                                    detail=f"content is not valid JSON: {exc}")
        else:
            raise HTTPException(status_code=400,
                                detail="content must be a JSON string or object")

        config_id = _hashlib.sha1(
            content_str.encode("utf-8")
        ).hexdigest()  # 40 hex chars

        # Write content file (idempotent — if exists, content is identical).
        content_path = configs_upload_dir / f"{config_id}.json"
        if not content_path.exists():
            atomic_json_write(content_path, parsed_content)

        # Update registry atomically.
        now_ts = utc_now()

        def _register(reg: Any) -> Any:
            if not isinstance(reg, dict):
                reg = {"entries": []}
            entries = reg.get("entries") or []
            # Check for existing entry with this (config_id, display_name).
            for e in entries:
                if (e.get("config_id") == config_id
                        and e.get("display_name") == display_name):
                    return reg  # Idempotent: already registered.
            entries.append({
                "config_id": config_id,
                "display_name": display_name,
                "uploaded_at": now_ts,
            })
            reg["entries"] = entries
            return reg

        atomic_json_read_modify_write(
            _configs_registry_path, _register,
            default={"entries": []},
        )
        return {
            "ok": True,
            "config_id": config_id,
            "display_name": display_name,
            "uploaded_at": now_ts,
        }

    @app.get("/api/configs")
    def list_configs() -> dict[str, Any]:
        """List all uploaded configs from _registry.json."""
        if not _configs_registry_path.exists():
            return {"entries": []}
        try:
            data = json.loads(_configs_registry_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"entries": []}
            return {"entries": data.get("entries") or []}
        except (OSError, json.JSONDecodeError):
            return {"entries": []}

    @app.get("/api/configs/{config_id}")
    def get_config(config_id: str) -> dict[str, Any]:
        """Return metadata + content for a single config."""
        content_path = configs_upload_dir / f"{config_id}.json"
        if not content_path.exists():
            raise HTTPException(status_code=404, detail="config not found")
        try:
            content = json.loads(content_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500,
                                detail=f"config file unreadable: {exc}")
        # Pull display_name from registry.
        display_name = config_id  # fallback
        if _configs_registry_path.exists():
            try:
                reg = json.loads(_configs_registry_path.read_text(encoding="utf-8"))
                for e in (reg.get("entries") or []):
                    if e.get("config_id") == config_id:
                        display_name = str(e.get("display_name") or config_id)
                        break
            except (OSError, json.JSONDecodeError):
                pass
        return {
            "config_id": config_id,
            "display_name": display_name,
            "content": content,
        }

    # ── Phase 3 (D7 + D5 + D8): Fleet refresh endpoints ───────────────

    if fleet_refresh_enabled:
        from src.web_console.backend.fleet_refresh import FleetRefreshManager

        # Build the per-item runner that FleetRefreshManager calls.
        # This function runs a single (machine, mode) batch item and
        # waits for it to complete, returning {run_id, status, error}.
        def _fleet_batch_item_runner(
            machine: str, mode: int, queue_id: str,
        ) -> dict[str, Any]:
            """Run one fleet-refresh item synchronously.

            Reuses the existing BatchRunManager and RunManager infrastructure
            so fleet refresh honors the same disk-pressure / md5-filter /
            resume-from-cache logic as ad-hoc planner batches.

            The item already has a SAMPLING lock (acquired by FleetRefreshManager
            before calling this) and a ConcurrencyLimiter slot.  We skip the
            lock-acquire step inside BatchRunManager by driving it directly via
            RunManager.start_run.
            """
            import time as _time
            try:
                up_cfg, up_code = _get_machine_md5(machine, mc, mode)
                cache_dir_str = str(rd_root / machine / f"mode_{mode}")
                run_req = RunCreateRequest(
                    machine=machine,
                    mode=mode,
                    chunk_spin_times=1000,
                    chunk_robot_count=8,
                    batch_concurrency=8,
                    max_chunks=120,
                    timeout=300.0,
                    target_halfwidth_pp=0.5,
                    server_id="",
                    resume_from_cache_dir=cache_dir_str,
                    upstream_config_md5=up_cfg or "",
                    upstream_code_md5=up_code or "",
                )
                result = manager.start_run(run_req)
                run_id = str(result.get("run_id") or "")
                # Wait for the run to complete.
                # Check cancel flag each iteration so DELETE /api/fleet/refresh
                # can interrupt a long-running wait (up to 5s latency vs the
                # previous 2-hour worst-case).
                max_wait = 7200  # 2 hours
                waited = 0
                while waited < max_wait:
                    # Cancel check before each poll — fleet_mgr is defined in
                    # the enclosing scope immediately after this function and is
                    # guaranteed assigned before the first call.
                    if fleet_mgr._is_cancelled(queue_id):
                        return {
                            "run_id": run_id,
                            "status": "cancelled",
                            "error": "queue cancelled during run",
                        }
                    row = store.get_run(run_id)
                    if row is None:
                        break
                    status = str(row.get("status") or "")
                    if status not in ("running", "pending"):
                        return {
                            "run_id": run_id,
                            "status": "completed" if status == "completed" else "failed",
                            "error": str(row.get("error_message") or ""),
                        }
                    _time.sleep(5)
                    waited += 5
                return {"run_id": run_id, "status": "failed", "error": "timeout"}
            except Exception as exc:  # noqa: BLE001
                import traceback as _tb
                _tb.print_exc()
                return {"run_id": "", "status": "failed",
                        "error": f"{exc.__class__.__name__}: {exc}"}

        fleet_mgr = FleetRefreshManager(
            db_path=db_path,
            registry=registry,
            limiter=limiter,
            start_batch_item_fn=_fleet_batch_item_runner,
        )
        app.state.fleet_refresh_manager = fleet_mgr

        # Resume crashed queue if any (D6).
        if store._pending_resume_queue_id:
            _resume_id = store._pending_resume_queue_id
            threading.Thread(
                target=fleet_mgr.run_queue,
                args=(_resume_id,),
                daemon=True,
                name=f"fleet-refresh-resume-{_resume_id[:8]}",
            ).start()

        @app.post("/api/fleet/refresh")
        def start_fleet_refresh(req: dict[str, Any] | None = None) -> dict[str, Any]:
            """Trigger a new fleet refresh queue.

            Single-instance enforcement: returns 409 if a queue is already
            running.

            Body (optional): {config_source: str, server_id: str,
                              machines: [{machine, modes: [int]}]}
            If machines is omitted, all machines from machines.json are queued.
            """
            # Single-instance check.
            running_id = fleet_mgr.get_running_queue_id()
            if running_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"fleet refresh already running (queue_id={running_id}). "
                        "Cancel it first via DELETE /api/fleet/refresh"
                    ),
                )
            # MF-3 reverse mutex: refuse fleet refresh while auto-inspect
            # sweep is active (07_decision §2 MF-3).
            _ai_mgr = getattr(app.state, "auto_inspect_manager", None)
            if _ai_mgr is not None and _ai_mgr._has_running_sweep():
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "auto-inspect sweep is active -- wait for it to "
                        "complete or cancel it first"
                    ),
                )
            # Build machine list.
            body = req or {}
            config_source = str(body.get("config_source") or "server_default")
            server_id = str(body.get("server_id") or "") or None
            raw_machines = body.get("machines")
            if raw_machines is None:
                # Default: all machines from machines.json with their
                # supported modes (inferred from rawdata dirs or default [1]).
                try:
                    data = json.loads(Path(mc).read_text(encoding="utf-8"))
                    machines_list = []
                    for entry in (data.get("machines") or []):
                        m = str(entry.get("machine") or "")
                        if not m:
                            continue
                        # Default to modes that exist in rawdata, or mode 1.
                        machine_rawdata = rd_root / m
                        modes: list[int] = []
                        if machine_rawdata.is_dir():
                            for md in machine_rawdata.iterdir():
                                if md.is_dir() and md.name.startswith("mode_"):
                                    try:
                                        modes.append(int(md.name.split("_", 1)[1]))
                                    except (IndexError, ValueError):
                                        continue
                        if not modes:
                            modes = [1]
                        machines_list.append({"machine": m, "modes": sorted(modes)})
                except (OSError, json.JSONDecodeError):
                    machines_list = []
            else:
                machines_list = list(raw_machines)

            if not machines_list:
                raise HTTPException(status_code=400,
                                    detail="no machines to refresh")

            queue_id = fleet_mgr.start_queue(
                machines_list,
                config_source=config_source,
                server_id=server_id,
            )
            return {
                "ok": True,
                "queue_id": queue_id,
                "total_machines": len(machines_list),
                "total_items": sum(
                    len(m.get("modes") or []) for m in machines_list
                ),
            }

        @app.get("/api/fleet/refresh")
        def get_fleet_refresh() -> dict[str, Any]:
            """Poll current fleet refresh progress.

            Returns the most recently started queue (running or completed).
            404 if no queue has ever been created.
            """
            queue_id = fleet_mgr.get_running_queue_id()
            if queue_id is None:
                # No running queue — return the most recently completed.
                try:
                    with fleet_mgr._connect() as _conn:
                        row = _conn.execute(
                            "SELECT queue_id FROM fleet_refresh_queue "
                            "ORDER BY started_at DESC LIMIT 1"
                        ).fetchone()
                    queue_id = str(row["queue_id"]) if row else None
                except sqlite3.OperationalError:
                    queue_id = None

            if queue_id is None:
                raise HTTPException(
                    status_code=404, detail="no fleet refresh queue found"
                )

            progress = fleet_mgr.get_queue_progress(queue_id)
            if progress is None:
                raise HTTPException(
                    status_code=404, detail=f"queue {queue_id} not found"
                )
            return progress

        @app.delete("/api/fleet/refresh")
        def cancel_fleet_refresh() -> dict[str, Any]:
            """Cancel the currently running fleet refresh queue."""
            queue_id = fleet_mgr.get_running_queue_id()
            if queue_id is None:
                raise HTTPException(
                    status_code=404, detail="no running fleet refresh queue"
                )
            fleet_mgr.cancel_queue(queue_id)
            return {"ok": True, "queue_id": queue_id, "cancelled": True}

    else:
        # fleet_refresh_enabled=False (virtual console).
        app.state.fleet_refresh_manager = None

    # ── Phase 4 (auto-inspect) — AutoInspectManager construction ──────────
    # Construction is always done (not gated on fleet_refresh_enabled) so
    # the schema tables are always present and _is_cell_owned_by_active_queue
    # branch 3 always works.  No HTTP in __init__ (MF-1).
    from src.web_console.backend.auto_inspect_manager import AutoInspectManager

    auto_inspect_mgr = AutoInspectManager(
        store=store,
        run_manager=manager,
        registry=registry,
        limiter=limiter,
        settings_path=settings_path,
        machines_config=mc,
        rawdata_root=rd_root,
    )
    app.state.auto_inspect_manager = auto_inspect_mgr

    # If a non-terminal sweep was found on startup, resume it via daemon
    # thread after create_app finishes — same pattern as FleetRefreshManager
    # restart-recovery at line ~11762 above (07_decision §2 MF-1 resolution).
    if auto_inspect_mgr._pending_resume_sweep_id:
        _resume_sweep_id = auto_inspect_mgr._pending_resume_sweep_id
        threading.Thread(
            target=auto_inspect_mgr.resume_sweep,
            args=(_resume_sweep_id,),
            daemon=True,
            name=f"auto-inspect-resume-{_resume_sweep_id[:8]}",
        ).start()

    # -- Phase 5 -- Cron scheduler startup --------------------------------
    # Start the cron scheduler as a daemon.  It reads settings every cycle
    # so operator can change cadence without restarting.  If
    # auto_sweep.enabled is False (default), it idles; first fire only
    # happens once the operator enables it.
    from src.web_console.backend.auto_inspect_manager import (  # noqa: PLC0415
        _AutoInspectScheduler,
    )

    _ai_scheduler = _AutoInspectScheduler(
        auto_inspect_mgr,
        settings_path=settings_path,
    )
    app.state.auto_inspect_scheduler = _ai_scheduler
    _ai_scheduler.start()

    # -- Phase 4 P2 -- auto-inspect HTTP endpoints ------------------------
    # Wired unconditionally (not gated on fleet_refresh_enabled) so the
    # endpoints are always present even in virtual-console mode.

    @app.post("/api/auto-inspect/start")
    def auto_inspect_start() -> dict[str, Any]:
        """Trigger a new auto-inspect sweep.

        409 if a sweep is already running or a fleet refresh is active.
        Returns {sweep_id: str}.
        """
        return {"sweep_id": auto_inspect_mgr.start_sweep(trigger="manual")}

    @app.post("/api/auto-inspect/{sweep_id}/cancel")
    def auto_inspect_cancel(sweep_id: str) -> dict[str, Any]:
        """Cancel a running sweep.  404 if sweep_id not found."""
        if not auto_inspect_mgr.cancel_sweep(sweep_id):
            raise HTTPException(status_code=404, detail="sweep not found")
        return {"ok": True}

    @app.get("/api/auto-inspect")
    def auto_inspect_list(limit: int = 30) -> dict[str, Any]:
        """Return list of recent sweeps, newest first."""
        return {"sweeps": auto_inspect_mgr.list_recent_sweeps(limit=limit)}

    @app.get("/api/auto-inspect/preview")
    def auto_inspect_preview() -> dict[str, Any]:
        """Preview what a new sweep would enqueue, without committing.

        P4 deliverable 3.  Calls _scan_cells (read-only) and returns
        aggregate counts + per-cell list so the operator can confirm
        scope before clicking 开始巡检.

        IMPORTANT: this fixed-path route is registered BEFORE the
        parameterised /api/auto-inspect/{sweep_id} route below.
        FastAPI / Starlette resolves routes in registration order;
        placing this first ensures GET /api/auto-inspect/preview is
        never swallowed by the {sweep_id} catch-all.

        Returns:
          * total (int)
          * by_mode ({str: int})
          * by_cell_class ({str: int})
          * structural_skip_count (int)
          * manifest_override_count (int)
          * estimated_wall_time_s (int, rough: total * 300s)
          * cells (list[{machine, mode, cell_class, cfg_md5, code_md5}])
        """
        return auto_inspect_mgr.preview_sweep()

    @app.get("/api/auto-inspect/{sweep_id}")
    def auto_inspect_get(
        sweep_id: str,
        items_limit: int = 200,
    ) -> dict[str, Any]:
        """Return sweep progress dict.  404 if sweep_id not found.

        P5: items_limit caps the items list (default 200).  The UI
        passes ?items_limit=200 to avoid multi-MB payloads on 1688-cell
        sweeps.
        """
        status_data = auto_inspect_mgr.get_sweep_status(
            sweep_id, items_limit=items_limit
        )
        if status_data is None:
            raise HTTPException(status_code=404, detail="sweep not found")
        return status_data

    threading.Thread(target=_disk_monitor_loop, daemon=True, name="disk-monitor").start()

    return app

