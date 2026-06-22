"""Versioning primitives for the analyzer plugin model.

Per ticket honesty-2 (phase_honesty_2/brief.md) and
session_artifacts/_arch_honesty_isolation/07_decision.md R-1/R-3/R-4/R-5.

Public surface
--------------
- :func:`compute_base_analyzer_version` — 12-hex hash of the transitive
  repo-local import closure of the report-production path, excluding
  registered feature-plugin files. This is the "universal code" identity:
  any change to a content or support module on the production path flips
  this hash; changes confined to a registered feature plugin do not.
- :func:`compute_effective_analyzer_version` — per-(machine, mode)
  hash composition. The result invalidates only machines that actually
  use the changed feature(s).
- :func:`compute_effective_version_for_machine` — convenience orchestrator
  that reads the machine's manifest, resolves features via the
  registry, hashes the closure + feature bodies, and returns the 12-hex string.

Algorithm (verbatim from §4.1)
-------------------------------
  h = sha256(base_hash)
  for fid in sorted(set(machine_features)):
      h.update(b"\\x00" + fid.encode() + b"=" + feature_hashes[fid].encode())
  if mode is not None:
      h.update(b"\\x00mode=" + str(mode).encode())
  return h.hexdigest()[:12]

Where:
  base_hash      — 12-hex hash of the transitive report-production closure
                   (content + support modules, MINUS registered feature plugins)
  feature_hashes — {feature_id: 12-hex hash} from feature_registry
  machine_features — list[str] of feature IDs the machine declares
  mode           — int | None; if provided, the per-mode dimension is included

R-1 closure definition (honesty-2)
------------------------------------
base_hash covers all repo-local Python modules reachable from the
report-production path, MINUS registered feature-plugin files (R-4).

The closure is encoded as an explicit, version-controlled tuple of
repo-relative paths (``_CLOSURE_FILES`` below) hashed in sorted order.
This is deterministic across the dual import paths (script-mode vs
package-mode) per memory/feedback_subprocess_import_suicide_and_module_globals.md.

Line-ending normalization (FIX-2): bytes are CRLF-normalized before hashing
(``read_bytes().replace(b"\\r\\n", b"\\n")``) so base_hash is a function of
SOURCE CONTENT, not of checkout config (autocrlf) or platform. Without this,
adding a ``.gitattributes`` or checking out on Linux would flip the hash and
mark all 393 reports stale without any code change.

A CI drift-guard test (tests/analyzer/test_honesty2_drift_guard.py) introspects
the actual runtime import closure and FAILS if a new repo-local content module
is imported on the production path but absent from _CLOSURE_FILES.

R-4 exclusion
--------------
The base-exclusion set = exactly the ``__file__``s of the registered features
(``feature_registry.ALL_FEATURES``). ``_base.py`` and ``features/__init__.py``
are NOT in ALL_FEATURES and therefore STAY in base. A glob over
``features/*.py`` would be wrong (it would drop _base.py and __init__.py).

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# R-1: Explicit, version-controlled closure file set (honesty-2)
# ---------------------------------------------------------------------------
# This tuple is the authoritative set of repo-local Python files that
# contribute to base_hash. Resolved from the live import graph (introspection
# of sys.modules after importing player_impact_analyzer and its support chain).
#
# Files in this list: content modules + support modules on the report-
# production path, EXCLUDING registered feature-plugin files (R-4).
#
# NOTE: versioning.py is itself in this list. Editing the closure set (or any
# source in it) flips base_hash — which is correct, because the hash algorithm
# changed. The self-referential inclusion is intentional and correct.
#
# Lazy imports inside main() (rtp_integrity, parse_state, pipeline_context,
# topo_sort) ARE included because they execute on every real
# report-production run.
#
# Modules intentionally NOT in the closure:
#   - fresh_slotlab/analyzer/_stub_features.py   (deleted in 5B — was test-only)
#   - fresh_slotlab/reporter.py                  (standalone script, not imported by PIA)
#   - fresh_slotlab/analyzer/features/*.py       (registered plugins, excluded by R-4)
#     EXCEPT _base.py and __init__.py which ARE in the closure (not registered plugins)
#
# Backend-orchestrated post-hooks (run after pia.main() by app.py / virtual_analyzer.py,
# NOT by PIA's own import graph — they are intentionally outside the closure):
#   - fresh_slotlab/post_inference.py    — run_post_analyzer_inference: launches
#                                          inference scripts as subprocesses after pia.main()
#   - fresh_slotlab/summary_md5_patch.py — patch_summary_md5: stamps md5 fields in the
#                                          written summary after pia.main() returns
#   - fresh_slotlab/batch_dev_sampler.py — dev-only sampling helper, not on report path
# Changes to these post-hooks do NOT flip base_hash. This is a known, accepted scope
# boundary: R-1 defines the report-production path as PIA's import closure, not the
# full backend pipeline. If their honesty ever matters independently, that is a separate
# follow-on (they carry their own md5/patch semantics separate from analyzer_version).
#
# Drift guard: tests/analyzer/test_honesty2_drift_guard.py walks sys.modules
# after importing PIA + support modules and fails if any repo-local content
# module is imported but absent from this list. Update this list if the
# guard fires after a legitimate new content module is added.
_CLOSURE_FILES: tuple[str, ...] = (
    "fresh_slotlab/analyzer/__init__.py",
    "fresh_slotlab/analyzer/core/__init__.py",
    "fresh_slotlab/analyzer/core/_utils.py",
    "fresh_slotlab/analyzer/core/aggregator.py",
    "fresh_slotlab/analyzer/core/base_pipeline.py",
    "fresh_slotlab/analyzer/core/parser.py",
    "fresh_slotlab/analyzer/core/writer.py",
    "fresh_slotlab/analyzer/feature_registry.py",
    "fresh_slotlab/analyzer/features/__init__.py",
    "fresh_slotlab/analyzer/features/_base.py",
    # Sub-pass B: st_extract framework files (discovery + ABC) are in the
    # closure.  Extractor modules (trigger_path.py etc.) are base-EXCLUDED —
    # editing them changes only machines that declare the extractor, not fleet.
    # Analogy: features/__init__.py + _base.py are in closure; plugin modules
    # are excluded.
    "fresh_slotlab/analyzer/st_extract/__init__.py",
    "fresh_slotlab/analyzer/st_extract/_base.py",
    # manifest_loader.py removed (5B): flat-manifest layer deleted.
    # mechanism_registry.py removed (5C): MechanismRegistry deleted.
    "fresh_slotlab/analyzer/parse_state.py",
    "fresh_slotlab/analyzer/pipeline_context.py",
    "fresh_slotlab/analyzer/report_engine.py",
    # NOTE: play_types/{__init__,bcm_cycle,wild_nudge}.py are INTENTIONAL CARVES —
    # base-EXCLUDED so editing a machine's mechanic logic does NOT re-flag the whole
    # fleet (the core playtype-rearch goal). They must NOT be added here, even though
    # parser.py imports them on the production path (the R-1 drift guard allowlists
    # them; per-machine hashing is the tracked follow-up). Adding them broke
    # test_{wild_nudge,bcm_cycle}_carve — see the carve-isolation tests.
    #
    # NOTE: st_extract/trigger_path.py (and future extractor modules) are
    # INTENTIONAL CARVES — base-EXCLUDED so editing an extractor re-flags only
    # machines that declare it, not the fleet.  Only st_extract/__init__.py and
    # st_extract/_base.py (framework files) are in the closure above.
    # parser.py imports st_extract extractor modules at parse time via the
    # st_extractors parameter; the R-1 drift guard must allowlist
    # "fresh_slotlab/analyzer/st_extract/trigger_path.py" the same way it
    # allowlists play_types/ modules (if the guard is ever restored).
    "fresh_slotlab/analyzer/rtp_integrity.py",
    "fresh_slotlab/analyzer/topo_sort.py",
    "fresh_slotlab/analyzer/versioning.py",
    "fresh_slotlab/chunk_index.py",
    "fresh_slotlab/machine_md5.py",
    "fresh_slotlab/rawdata_index.py",
    "fresh_slotlab/round_classification.py",
    "fresh_slotlab/round_win.py",
    # round_win_rules/ framework file (discovery + registry + per-type hashing)
    # is in the closure, mirroring features/__init__.py and st_extract/__init__.py.
    # The rule-TYPE modules (settlement_winamount.py etc.) are base-EXCLUDED —
    # editing or adding a rule type re-flags only machines that declare it (via
    # the rw:<type_str> effective_version component), never the whole fleet.
    "fresh_slotlab/round_win_rules/__init__.py",
    "fresh_slotlab/sampler.py",
    "fresh_slotlab/trigger_sessions.py",
)

# Repo root: two parents up from fresh_slotlab/analyzer/versioning.py
# (i.e., fresh_slotlab/analyzer/ -> fresh_slotlab/ -> repo_root/).
# Pure path arithmetic, no I/O at import time.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# round_win rule-type membership (for "rw:<type_str>" effective_version folding)
# ---------------------------------------------------------------------------
# Module-level cache for configs/machine_round_win_rules.json. The effective-
# version path is called per (machine, mode) across the whole fleet, so the
# config is read once and reused. Tests that mutate the file on disk should
# reset this to None (or pass round_win_rules_config explicitly to bypass it).
_RW_RULES_CONFIG_CACHE: Optional[dict[str, Any]] = None


def _reset_rw_cache() -> None:
    """Clear the round_win rules-config cache.

    Test-only helper. The cache (loaded once, process-lifetime) is correct for
    production where the config file is immutable during a run; a test that
    MUTATES configs/machine_round_win_rules.json on disk between calls must call
    this (or pass ``round_win_rules_config=`` to bypass the cache entirely),
    otherwise the stale parse short-circuits subsequent reads. The ``{}``
    sentinel (file absent) is a valid cached value, so a plain ``is not None``
    guard would not re-read after the file appears — hence this explicit reset.
    """
    global _RW_RULES_CONFIG_CACHE
    _RW_RULES_CONFIG_CACHE = None


def _load_round_win_rules_config(repo_root: Optional[Path] = None) -> dict[str, Any]:
    """Load + cache configs/machine_round_win_rules.json (or {} if absent).

    Cached for the process lifetime (the EV path is called per (machine, mode)
    across the fleet). Tests that mutate the file on disk must call
    :func:`_reset_rw_cache` or pass ``round_win_rules_config=`` to bypass it.
    """
    global _RW_RULES_CONFIG_CACHE
    if _RW_RULES_CONFIG_CACHE is not None:
        return _RW_RULES_CONFIG_CACHE
    import json
    root = repo_root if repo_root is not None else _REPO_ROOT
    path = root / "configs" / "machine_round_win_rules.json"
    if not path.exists():
        _RW_RULES_CONFIG_CACHE = {}
        return _RW_RULES_CONFIG_CACHE
    with open(path, encoding="utf-8") as fh:
        _RW_RULES_CONFIG_CACHE = json.load(fh)
    return _RW_RULES_CONFIG_CACHE


def _used_round_win_types(
    machine_id: str,
    *,
    repo_root: Optional[Path] = None,
    config: Optional[dict[str, Any]] = None,
) -> set[str]:
    """Return the set of round_win rule TYPE strings this machine uses.

    A machine "uses" a rule type if any entry in machine_round_win_rules.json
    has the machine_id — OR its base id (for variants like
    ``"M15$TopDollarSelector$1$"`` → ``"M15"``) — in its ``applies_to`` list.

    The base-id fallback mirrors report_engine's variant rule-loading fallback
    (a variant with no own entry inherits the base machine's rules). Folding the
    rule hash for such variants keeps their effective_version honest — without
    it a variant whose rules come via the base fallback would carry a stale EV
    that never re-flags when the rule changes (critic EC-1).
    """
    cfg = config if config is not None else _load_round_win_rules_config(repo_root)
    rules = (cfg or {}).get("rules") or {}
    base_id = str(machine_id).split("$")[0]
    used: set[str] = set()
    for spec in rules.values():
        if not isinstance(spec, dict):
            continue
        applies_to = spec.get("applies_to") or []
        if machine_id in applies_to or base_id in applies_to:
            t = spec.get("type")
            if t:
                used.add(str(t))
    return used


def compute_base_analyzer_version(
    *,
    closure_files: Optional[tuple[str, ...]] = None,
    repo_root: Optional[Path] = None,
) -> str:
    """Return the 12-char hex hash of the report-production import closure.

    Hashes every file in the explicit closure set ``_CLOSURE_FILES`` in
    deterministic sorted-by-path order, with CRLF→LF normalization so that
    the hash is a function of SOURCE CONTENT rather than checkout-config
    (autocrlf) or platform.

    Per R-1 (honesty-2) the base_hash covers the full transitive repo-local
    import closure of the report-production path (not just ``core/*.py``):
    any change to a content or support module on the production path flips
    this hash; changes confined to a registered feature plugin do not (R-4
    exclusion via the registry — not a glob).

    Parameters
    ----------
    closure_files:
        Override the closure file set (used by tests to inject a synthetic
        closure). When ``None`` (default), uses ``_CLOSURE_FILES``. Each
        entry is a repo-relative path string.
    repo_root:
        Override the repo root (used by tests). When ``None`` (default),
        uses the repo root derived from this module's location.

    Returns
    -------
    str
        12-character lowercase hex string.

    Raises
    ------
    FileNotFoundError
        If any file in the closure set does not exist. The closure is a
        hard dependency; absence indicates a broken install, wrong path,
        or an out-of-date ``_CLOSURE_FILES`` tuple. Never silently swallowed
        (per memory/feedback_no_silent_swallow.md).
    """
    files = closure_files if closure_files is not None else _CLOSURE_FILES
    root = repo_root if repo_root is not None else _REPO_ROOT

    h = hashlib.sha256()
    # Hash in sorted-by-path order for determinism. The sort is on the
    # repo-relative string (posix path form) so it is identical across
    # platforms that use different path separators.
    #
    # CRLF normalization (FIX-2): normalize line endings before hashing so
    # that the hash depends only on source content, not on git checkout
    # config (core.autocrlf) or OS. Without this, adding .gitattributes or
    # checking out on Linux would flip base_hash and mark 393 reports stale
    # without any code change — a false-stale lie. Per
    # memory/feedback_invariant_with_fallback_hides_drift.md: the hash must
    # be honest; a platform-induced false-stale is as wrong as a false-fresh.
    for rel in sorted(files):
        source_file = root / rel
        if not source_file.exists():
            raise FileNotFoundError(
                f"Closure file does not exist: {source_file}. "
                f"The _CLOSURE_FILES tuple in versioning.py may be out of date, "
                f"or the repo root is wrong (repo_root={root!r}). "
                f"Per memory/feedback_no_silent_swallow.md: do not swallow this error."
            )
        raw = source_file.read_bytes()
        h.update(raw.replace(b"\r\n", b"\n"))

    return h.hexdigest()[:12]


def compute_analyzer_version() -> str:
    """Analyzer "version" tag stamped in summary.json for report freshness.

    Historically this hashed ``player_impact_analyzer.py``'s own source. That
    monolith has been removed (orchestrator rebuild); freshness now tracks the
    report-production closure — the same hash that drives per-machine
    ``effective_version`` — which is a strictly more honest signal (it flips
    when any core/support module on the production path changes).

    Returns "" (untagged) rather than crashing the console if the closure
    can't be read, preserving the old never-crash contract.
    """
    try:
        return compute_base_analyzer_version()
    except OSError:
        return ""


def compute_effective_version_for_machine(
    machine_id: str,
    mode: Optional[int] = None,
    *,
    manifests_root: Optional[Path] = None,
    new_manifests_root: Optional[Path] = None,
    registry: Optional[Any] = None,
    closure_files: Optional[tuple[str, ...]] = None,
    repo_root: Optional[Path] = None,
    round_win_rules_config: Optional[dict[str, Any]] = None,
) -> str:
    """Convenience orchestrator — full pipeline for one (machine, mode).

    Reads the machine's manifest, resolves variant inheritance, resolves
    per-mode overrides, looks up feature hashes from the registry, hashes
    the report-production closure (R-1), and returns the 12-hex effective
    version.

    Phase 1 (L5 rewire, 5B: flat-manifest layer deleted): when a SpinType-native
    manifest exists at ``configs/machine_manifests/<M>.json``, the analysis set
    is resolved via ``machine_spec.derive_analyses`` (the new path).  Otherwise
    (non-registered machine, no manifest) returns base_hash with empty
    machine_features — no flat manifest fallback (flat layer deleted in 5B).

    Parameters
    ----------
    machine_id:
        Machine identifier (e.g. ``"M14"`` or ``"M273$WheelSelector$0$"``).
    mode:
        Integer mode. ``None`` to compute the mode-agnostic version (rare).
    manifests_root:
        Unused after 5B (flat-manifest layer deleted).  Kept so existing
        test helpers that pass ``tmp_path`` manifests do not break; the
        parameter is accepted but not read on any live code path.
    new_manifests_root:
        SpinType-native manifests directory (Phase 1 addition). Defaults to
        ``configs/machine_manifests`` resolved relative to this module's repo
        root. Override in tests to point at a synthetic directory.
    registry:
        Object exposing ``ALL_FEATURES``. Defaults to the package
        ``feature_registry`` module.
    closure_files:
        Override the closure file set for tests. Production passes None.
    repo_root:
        Override the repo root for tests. Production passes None.

    Returns
    -------
    str
        12-character lowercase hex string.

    Raises
    ------
    FileNotFoundError
        A closure file is missing (broken install).
    KeyError
        Manifest references a feature ID not registered.
    """
    # Lazy imports to avoid circular import: feature_registry imports the
    # AnalyzerFeature ABC, which lives in features/_base.py, which lives
    # alongside this module's siblings. Direct top-level imports would
    # work today but lazy-import keeps versioning.py drop-in for callers
    # who only need compute_base_analyzer_version. Dual-path covers
    # script-mode (cwd=fresh_slotlab/) per memory
    # feedback_subprocess_import_suicide_and_module_globals.md.
    if registry is None:
        try:
            from fresh_slotlab.analyzer import feature_registry as registry
        except ImportError:
            from analyzer import feature_registry as registry  # type: ignore[no-redef]
        # Phase 4: auto-discover all plugin modules under features/ so each
        # self-registers.  Replaces the old hardcoded import list — adding a
        # new plugin no longer requires editing this closure file.
        # discover_features() is idempotent (duplicate FEATURE_ID is a no-op).
        registry.discover_features()

    # Sub-pass B: discover extractor modules so their hashes can be folded
    # into the effective_version for machines that declare extraction.
    try:
        from fresh_slotlab.analyzer.st_extract import (
            discover_extractors as _discover_extractors,
            get_extractors_for_manifest as _get_extractors_for_manifest,
            extractor_hashes as _extractor_hashes,
        )
    except ImportError:
        from analyzer.st_extract import (  # type: ignore[no-redef]
            discover_extractors as _discover_extractors,
            get_extractors_for_manifest as _get_extractors_for_manifest,
            extractor_hashes as _extractor_hashes,
        )
    _discover_extractors()

    # manifests_root kept as a parameter for callers that pass tmp manifests in
    # tests, but the flat-manifest layer is deleted (5B) so real machines will
    # not have files there.  new_manifests_root defaults to configs/machine_manifests.
    if new_manifests_root is None:
        new_manifests_root = _REPO_ROOT / "configs" / "machine_manifests"

    base_hash = compute_base_analyzer_version(
        closure_files=closure_files,
        repo_root=repo_root,
    )

    # 5B: flat-manifest layer deleted.  Only the SpinType-native path is active.
    # Non-registered machines (no new-schema manifest) resolve to base_hash with
    # empty machine_features — graceful, no crash.
    _new_manifest_path = Path(new_manifests_root) / f"{machine_id}.json"
    _loaded_manifest: Optional[Any] = None
    if _new_manifest_path.exists():
        # New path: load SpinType-native manifest, derive analyses from spin_types.
        try:
            from fresh_slotlab.analyzer.machine_spec import (  # type: ignore[attr-defined]
                load_manifest as ms_load_manifest,
                derive_analyses,
            )
        except ImportError:
            from analyzer.machine_spec import (  # type: ignore[no-redef]
                load_manifest as ms_load_manifest,
                derive_analyses,
            )
        _loaded_manifest = ms_load_manifest(machine_id, new_manifests_root)
        machine_features = derive_analyses(_loaded_manifest)
    else:
        # Non-registered machine: no flat manifest (deleted in 5B), no new-schema
        # manifest.  Return base_hash with empty feature set — not "unregistered
        # error", just the version for a machine with no declared analyses.
        machine_features = []

    feature_hashes = {f.FEATURE_ID: f.compute_hash() for f in registry.ALL_FEATURES}

    # Sub-pass B: fold extractor pseudo-entries ("xt:<EXTRACTOR_ID>" -> hash)
    # into machine_features + feature_hashes for machines whose manifest
    # declares extraction.  No signature change to compute_effective_analyzer_version.
    # Machines without extraction declarations: no pseudo-entries → unchanged.
    if _loaded_manifest is not None:
        _active_extractors = _get_extractors_for_manifest(_loaded_manifest)
        _ext_hashes = _extractor_hashes()
        for _ext in _active_extractors:
            _pseudo_id = f"xt:{_ext.EXTRACTOR_ID}"
            if _pseudo_id not in feature_hashes:
                feature_hashes[_pseudo_id] = _ext_hashes.get(_ext.EXTRACTOR_ID, "")
            if _pseudo_id not in machine_features:
                machine_features = list(machine_features) + [_pseudo_id]

    # Fold round_win rule-type pseudo-entries ("rw:<type_str>" -> hash) for
    # machines whose machine_round_win_rules.json applies_to includes this
    # machine (or its base id, for variants). Mirrors the xt: extractor folding
    # above and the features/ plugin model: editing OR adding a rule type
    # re-flags only its declaring machines, never the fleet. Machines with no
    # rule entry get no pseudo-entries → unchanged effective_version.
    try:
        from fresh_slotlab.round_win_rules import (
            RULE_REGISTRY as _RULE_REGISTRY,
            discover_rules as _discover_rules,
            rule_type_hash as _rule_type_hash,
        )
    except ImportError:
        from round_win_rules import (  # type: ignore[no-redef]
            RULE_REGISTRY as _RULE_REGISTRY,
            discover_rules as _discover_rules,
            rule_type_hash as _rule_type_hash,
        )
    _discover_rules()
    _used_rw_types = _used_round_win_types(
        machine_id, repo_root=repo_root, config=round_win_rules_config
    )
    for _rw_type in sorted(_used_rw_types):
        if _rw_type not in _RULE_REGISTRY:
            # Config references a rule type with no registering module. This is a
            # deploy/config bug (e.g. the JSON entry was added before the
            # round_win_rules/<type>.py file). Fail LOUD with an actionable message
            # rather than a bare KeyError or a silent skip (the machine would then
            # be analyzed with the wrong rule list) — feedback_no_silent_swallow.md.
            raise KeyError(
                f"machine {machine_id!r} declares round_win rule type {_rw_type!r} "
                f"(configs/machine_round_win_rules.json) but no round_win_rules/*.py "
                f"module registers it after discover_rules(). Add "
                f"fresh_slotlab/round_win_rules/{_rw_type}.py (calling register_rule), "
                f"or remove the config entry."
            )
        _pseudo_id = f"rw:{_rw_type}"
        if _pseudo_id not in feature_hashes:
            feature_hashes[_pseudo_id] = _rule_type_hash(_rw_type)
        if _pseudo_id not in machine_features:
            machine_features = list(machine_features) + [_pseudo_id]

    return compute_effective_analyzer_version(
        base_hash=base_hash,
        feature_hashes=feature_hashes,
        machine_features=machine_features,
        mode=mode,
    )


def compute_effective_analyzer_version(
    *,
    base_hash: str,
    feature_hashes: dict[str, str],
    machine_features: list[str],
    mode: Optional[int] = None,
) -> str:
    """Return the 12-char hex effective_analyzer_version for one (machine, mode).

    This is the per-machine hash that invalidates only machines using a
    changed feature.  Composition algorithm per 04_v5 §4.1:

        h = sha256(base_hash)
        for fid in sorted(set(machine_features)):
            h.update(b"\\x00" + fid.encode() + b"=" + feature_hashes[fid].encode())
        if mode is not None:
            h.update(b"\\x00mode=" + str(mode).encode())
        return h.hexdigest()[:12]

    Parameters
    ----------
    base_hash:
        12-hex hash of the universal report-production closure (R-1).
    feature_hashes:
        Mapping of feature_id → 12-hex hash for every registered feature.
        Only features in *machine_features* are included in the digest.
    machine_features:
        Feature IDs declared by this machine.  Duplicates are deduplicated;
        order does not matter (sorted before hashing → deterministic).
    mode:
        Integer mode.  When provided, the mode dimension is included so that
        per-mode effective versions differ when applicable per 07_decision_v5 P1.

    Returns
    -------
    str
        12-character lowercase hex string.

    Raises
    ------
    KeyError
        If a feature in *machine_features* is not present in *feature_hashes*.
        This is a programming error — register features before calling.
    ValueError
        If *base_hash* is empty.
    """
    if not base_hash:
        raise ValueError("base_hash must not be empty")

    h = hashlib.sha256(base_hash.encode())

    for fid in sorted(set(machine_features)):
        fhash = feature_hashes[fid]  # KeyError is intentional — see docstring
        h.update(b"\x00" + fid.encode() + b"=" + fhash.encode())

    if mode is not None:
        h.update(b"\x00mode=" + str(mode).encode())

    return h.hexdigest()[:12]
