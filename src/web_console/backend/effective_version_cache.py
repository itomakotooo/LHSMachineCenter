"""Per-request memoized effective-analyzer-version helper (honesty-3, R-7).

Extracted OUT of fresh_slotlab/analyzer/versioning.py so that loading this
module does NOT modify any file in _CLOSURE_FILES (versioning.py is in the
closure; adding code there changes base_hash fleet-wide, which was the exact
honesty-3 cutover hazard).

This module is backend-only (web console / app.py). It MUST NOT be imported
from fresh_slotlab or any analyzer module because those are closure files.

Rationale (R-7):
    compute_effective_version_for_machine() does file I/O on every call: it
    reads the manifest AND hashes 25 closure files via
    compute_base_analyzer_version. Comparator loops in app.py iterate up to
    10 000 rows / all fleet modes. Calling it raw = O(rows × 25-file-read)
    I/O storm on every /api/reports/stale-count request.

    Fix: one EffectiveVersionCache instance per endpoint invocation. It
    (a) computes base_hash once, (b) memoizes per-(machine, mode), and
    (c) correctly distinguishes "no manifest" (unverifiable, not stale) from
    "closure file missing" (broken install — surfaces loudly).

Sentinel:
    When the machine has NO manifest the result is the string
    _UNVERIFIABLE_SENTINEL (not empty — empty would be indistinguishable from
    "computation failed"; this string is intentionally non-hex so it can never
    collide with a real hash).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Import the two primitives from versioning. Use the same path that app.py
# already uses to reach fresh_slotlab.
# ---------------------------------------------------------------------------
from fresh_slotlab.analyzer.versioning import (
    compute_base_analyzer_version,
    compute_effective_version_for_machine,
)

# ---------------------------------------------------------------------------
# Sentinel value
# ---------------------------------------------------------------------------
_UNVERIFIABLE_SENTINEL = "UNVERIFIABLE"

# ---------------------------------------------------------------------------
# Repo root (used for default manifests_root resolution)
# ---------------------------------------------------------------------------
# This file lives at src/web_console/backend/effective_version_cache.py.
# Repo root is 3 levels up: backend → web_console → src → repo root.
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parent.parent.parent.parent


class EffectiveVersionCache:
    """Per-request, lazily-populated cache of effective_analyzer_version.

    Usage::

        cache = EffectiveVersionCache()
        eff = cache.get("M14", 1)
        if eff == EffectiveVersionCache.UNVERIFIABLE:
            # machine has no manifest — treat as "cannot verify", not stale
            ...

    One instance should be created per endpoint invocation and discarded
    afterwards (not a module-level singleton — that would accumulate stale
    entries as machine manifests change between requests).

    base_hash is computed once on first use and cached on the instance. It is
    the SAME base hash for all machines in a given request, so we only pay the
    25-file hash cost once, not N(machines) times.

    ``compute_base_analyzer_version`` raises ``FileNotFoundError`` when a
    closure file is missing (broken install). That error is NOT caught here —
    it propagates to the caller so it can surface loudly
    (per memory/feedback_no_silent_swallow.md). Only the
    manifest-missing case is silently downgraded to UNVERIFIABLE.
    """

    UNVERIFIABLE: str = _UNVERIFIABLE_SENTINEL

    def __init__(
        self,
        *,
        manifests_root: Optional[Path] = None,
        closure_files: Optional[tuple[str, ...]] = None,
        repo_root: Optional[Path] = None,
    ) -> None:
        # 5B: flat-manifest layer deleted.  Default to the SpinType-native dir
        # so M15.json is found and returns a real hash instead of UNVERIFIABLE.
        self._manifests_root = (
            manifests_root
            if manifests_root is not None
            else _REPO_ROOT / "configs" / "machine_manifests"
        )
        self._closure_files = closure_files  # None → use _CLOSURE_FILES default
        self._repo_root = repo_root          # None → use _REPO_ROOT default
        self._base_hash: Optional[str] = None          # computed on first get()
        self._cache: dict[tuple[str, Optional[int]], str] = {}

    def _ensure_base(self) -> str:
        """Compute and cache base_hash on first call.

        Raises FileNotFoundError if a closure file is missing (broken install).
        Does NOT catch — callers see the error.
        """
        if self._base_hash is None:
            self._base_hash = compute_base_analyzer_version(
                closure_files=self._closure_files,
                repo_root=self._repo_root,
            )
        return self._base_hash

    def get(self, machine_id: str, mode: Optional[int]) -> str:
        """Return the effective_analyzer_version for (machine_id, mode).

        Returns ``UNVERIFIABLE`` (the class constant) when the machine has no
        manifest file — the caller should treat this as "cannot verify",
        neither fresh nor stale.

        Raises ``FileNotFoundError`` when a CLOSURE file is missing (broken
        install — not a missing manifest). This is NOT caught; the error
        surfaces to the endpoint handler so the operator can investigate.
        Never uses a blanket ``except Exception`` (per
        memory/feedback_no_silent_swallow.md).

        Caches the result by (machine_id, mode) for the lifetime of this
        instance.
        """
        key = (machine_id, mode)
        if key in self._cache:
            return self._cache[key]

        # Check manifest existence FIRST (cheap path check — just Path.exists(),
        # no JSON parse). A missing manifest = "unregistered / virtual machine"
        # — not a broken install. Unverifiable is honest.
        # A missing CLOSURE file (different FileNotFoundError) = broken install
        # and must NOT be swallowed. We distinguish by checking the manifest
        # path before attempting compute_effective_version_for_machine.
        # Manifest resolution per manifest_loader.load_manifest:
        # {manifests_dir}/{machine_id}.json
        manifest_file = self._manifests_root / f"{machine_id}.json"
        if not manifest_file.exists():
            # Expected case: virtual/unregistered machine has no manifest.
            # Honest "cannot verify" — not stale, not fresh.
            self._cache[key] = _UNVERIFIABLE_SENTINEL
            return _UNVERIFIABLE_SENTINEL

        # Manifest exists: compute. compute_base_analyzer_version inside may
        # raise FileNotFoundError for a missing closure file — do NOT catch
        # that; let it surface.
        self._ensure_base()  # raises FileNotFoundError on broken closure
        result = compute_effective_version_for_machine(
            machine_id,
            mode,
            manifests_root=self._manifests_root,
            closure_files=self._closure_files,
            repo_root=self._repo_root,
        )
        self._cache[key] = result
        return result
