"""honesty-2: R-1 closure drift-guard + R-4 registration-completeness tests.

This test file implements two CI safety guards introduced by the honesty-2
phase (2026-05-29):

R-1 drift-guard (§3.3 of phase_honesty_2/brief.md)
------------------------------------------------------
Introspects the monolith's ACTUAL runtime import closure (via sys.modules
after importing player_impact_analyzer + support modules) and FAILS loudly
if any repo-local content module is imported on the production path but
ABSENT from ``_CLOSURE_FILES`` in versioning.py.

This prevents anyone from silently adding an unhashed content module —
e.g. a new helper imported by round_classification.py that is not yet in
the closure tuple would pass the hash test but cause false-fresh reports.

Scope of introspection:
- ``fresh_slotlab/`` modules that are NOT tests and NOT registered plugins.
- Excludes: stdlib, third-party, tests, registered-plugin files.
- Lazy imports exercised: the guard explicitly triggers the lazy-import
  chain used in the production path (rtp_integrity, parse_state,
  pipeline_context, topo_sort, mechanism_registry) in addition to what
  PIA loads at module top.

Known residual (per 07_decision.md §7):
  Conditional imports inside function bodies (e.g. imports guarded by
  ``if some_condition``) that are never exercised in this test will NOT
  appear in sys.modules. The guard covers module-top + the major lazy
  imports; deep conditional-only imports may slip through. This is
  documented and accepted — any such new import must also be added to
  _CLOSURE_FILES and to this test's manually-exercised set.

R-4 registration-completeness (§3.4 of phase_honesty_2/brief.md)
------------------------------------------------------------------
Asserts every ``fresh_slotlab/analyzer/features/*.py`` EXCEPT ``_base.py``
and ``__init__.py`` is present in ``ALL_FEATURES`` (catches "forgot to add
the new plugin to the registry import block" footgun in CI).

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug A — Add a fake content import to the production path:
    Add ``import fresh_slotlab.analyzer._stub_features`` at module-top of
    player_impact_analyzer.py (a repo-local file NOT in _CLOSURE_FILES).
    RED: test_no_content_module_missing_from_closure fires because
    _stub_features.py is in sys.modules but not in _CLOSURE_FILES.
    Revert PIA → GREEN.

Bug B — Add an unregistered plugin file:
    Create ``fresh_slotlab/analyzer/features/zzz_unregistered.py`` with a
    dummy AnalyzerFeature class but NO ``register()`` call.
    RED: test_all_feature_files_registered fires (zzz_unregistered.py
    discovered by glob but absent from ALL_FEATURES FEATURE_ID set).
    Revert (delete the file) → GREEN.

Memory feedback honored
-----------------------
- memory/feedback_subprocess_import_suicide_and_module_globals.md — drift
  guard does NOT import the monolith at module level; it imports inside
  the test function to avoid import-time side effects.
- memory/feedback_invariant_with_fallback_hides_drift.md — guard FAILS
  loudly (raises AssertionError), never warns-and-passes.
- memory/feedback_no_silent_swallow.md — any unexpected import error is
  re-raised, never swallowed.
- memory/feedback_enumerate_safety_paths.md — inject-bug documented above.
- memory/feedback_self_verify_output.md — failure message includes the
  exact set of missing files for easy debugging.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FRESH_SLOTLAB = _REPO_ROOT / "fresh_slotlab"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_repo_local_content(module_name: str, fpath: Path) -> bool:
    """Return True if fpath is a fresh_slotlab production-path module.

    Filters out:
    - __pycache__ directories
    - non-.py files
    - test files (under tests/)
    """
    if not fpath.suffix == ".py":
        return False
    if "__pycache__" in fpath.parts:
        return False
    # Must be under fresh_slotlab/
    try:
        fpath.relative_to(_FRESH_SLOTLAB)
    except ValueError:
        return False
    return True


def _get_registered_plugin_files() -> set[Path]:
    """Return the set of __file__ paths for all registered feature plugins.

    Imports all 11 known plugins to ensure they are registered, then reads
    ALL_FEATURES to get the registered set. This is the R-4 exclusion set.

    Does NOT use a glob — per brief §3.2, exclusion is via the registry,
    not a directory glob. _base.py and __init__.py are NOT in ALL_FEATURES
    and therefore NOT in this exclusion set.

    Phase E update: added topdollar_choice import (10th plugin).
    playtype-rearch: added spin_type_outcomes (11th plugin; auto-registers
      via payouts_by_spin_type.py auto-import to avoid closure-file edits).
    """
    # Ensure plugins are registered
    try:
        import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
        # spin_type_outcomes is auto-imported by payouts_by_spin_type above.
        import fresh_slotlab.analyzer.features.reel_marginal_by_spin_type  # noqa: F401
        import fresh_slotlab.analyzer.features.bankruptcy_simulation  # noqa: F401
        import fresh_slotlab.analyzer.features.multiplier_profile  # noqa: F401
        import fresh_slotlab.analyzer.features.multiplier_wild  # noqa: F401
        import fresh_slotlab.analyzer.features.machine_mechanics  # noqa: F401
        import fresh_slotlab.analyzer.features.upstream_feature_breakdown  # noqa: F401
        import fresh_slotlab.analyzer.features.collect_mechanic  # noqa: F401
        import fresh_slotlab.analyzer.features.bonus_chain_dynamics  # noqa: F401
        import fresh_slotlab.analyzer.features.topdollar_choice  # noqa: F401  # Phase E
        import fresh_slotlab.analyzer.features.spin_type_outcomes  # noqa: F401  # playtype-rearch
    except ImportError as exc:
        raise ImportError(
            f"Failed to import a registered plugin — cannot build exclusion set: {exc}"
        ) from exc

    from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES

    excluded: set[Path] = set()
    for feature in ALL_FEATURES:
        mod = sys.modules.get(feature.__class__.__module__)
        if mod is not None and getattr(mod, "__file__", None):
            excluded.add(Path(mod.__file__).resolve())
    return excluded


def _get_closure_set() -> set[Path]:
    """Return the set of absolute Paths that _CLOSURE_FILES maps to."""
    # Import versioning without triggering any heavy side-effects;
    # versioning.py is a pure-path-arithmetic module.
    try:
        from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES, _REPO_ROOT as _VER_REPO_ROOT
    except ImportError:
        from analyzer.versioning import _CLOSURE_FILES, _REPO_ROOT as _VER_REPO_ROOT  # type: ignore[no-redef]

    return {(_VER_REPO_ROOT / rel).resolve() for rel in _CLOSURE_FILES}


# ---------------------------------------------------------------------------
# R-1 drift-guard tests
# ---------------------------------------------------------------------------

class TestR1ClosureDriftGuard:
    """Drift guard: every repo-local content module imported on the production
    path must be present in _CLOSURE_FILES.

    Per memory/feedback_invariant_with_fallback_hides_drift.md: FAIL loudly,
    never warn-and-pass.
    """

    def test_no_content_module_missing_from_closure(self):
        """FAIL if any repo-local content module is imported but not in _CLOSURE_FILES.

        Steps:
        1. Snapshot sys.modules before.
        2. Import the monolith (player_impact_analyzer) and trigger the major
           lazy-import branches used on the production path.
        3. Collect all fresh_slotlab modules that appeared.
        4. Exclude registered-plugin files (R-4) — they are intentionally out.
        5. FAIL if any remaining module is not in _CLOSURE_FILES.

        INJECT-BUG: add ``import fresh_slotlab.analyzer._stub_features`` at
        module-top of player_impact_analyzer.py.
        RED: _stub_features.py appears in sys.modules but is absent from
        _CLOSURE_FILES → this test fails.
        Revert → GREEN.
        """
        # --- Step 1: snapshot ---
        before = set(sys.modules.keys())

        # --- Step 2: import production path ---
        # Import PIA (module-top content imports)
        try:
            import fresh_slotlab.player_impact_analyzer  # noqa: F401
        except Exception as exc:
            # PIA may raise SystemExit on --help or import errors from missing
            # config. For CI purposes, a clean import should succeed.
            raise RuntimeError(
                f"Failed to import player_impact_analyzer (needed for drift guard): {exc}"
            ) from exc

        # Trigger the lazy imports used in the production path (parse_chunk_response
        # + main() call sites in PIA). We import them explicitly to ensure they are
        # exercised — they would NOT appear in sys.modules from PIA's module-top import
        # alone (they are imported inside function bodies).
        _lazy_modules = [
            "fresh_slotlab.analyzer.rtp_integrity",
            "fresh_slotlab.analyzer.parse_state",
            "fresh_slotlab.analyzer.pipeline_context",
            "fresh_slotlab.analyzer.topo_sort",
            "fresh_slotlab.analyzer.mechanism_registry",
            "fresh_slotlab.analyzer.versioning",
            "fresh_slotlab.analyzer.manifest_loader",
            "fresh_slotlab.analyzer.feature_registry",
        ]
        for mod_name in _lazy_modules:
            try:
                importlib.import_module(mod_name)
            except ImportError as exc:
                raise ImportError(
                    f"Drift guard could not import production-path module {mod_name!r}: {exc}. "
                    f"If this module was removed from the codebase, remove it from this list too."
                ) from exc

        # Also trigger the versioning effective-version path (loads manifest_loader
        # and registers features)
        try:
            from fresh_slotlab.analyzer.versioning import compute_effective_version_for_machine
            compute_effective_version_for_machine("M14", 1)
        except Exception:
            pass  # Failure here is OK — we only need sys.modules to be populated

        # --- Step 3: collect new fresh_slotlab modules ---
        after = set(sys.modules.keys())
        new_module_names = after - before

        imported_content_files: set[Path] = set()
        for name in new_module_names:
            mod = sys.modules.get(name)
            if mod is None:
                continue
            fpath_str = getattr(mod, "__file__", None)
            if fpath_str is None:
                continue
            fpath = Path(fpath_str).resolve()
            if _is_repo_local_content(name, fpath):
                imported_content_files.add(fpath)

        # --- Step 4: exclude registered plugins (R-4) ---
        try:
            excluded_plugins = _get_registered_plugin_files()
        except Exception as exc:
            raise RuntimeError(
                f"Drift guard could not determine registered plugin files: {exc}"
            ) from exc

        content_minus_plugins = imported_content_files - excluded_plugins

        # --- Step 5: compare against _CLOSURE_FILES ---
        closure = _get_closure_set()

        missing_from_closure = content_minus_plugins - closure
        if missing_from_closure:
            missing_rel = sorted(
                p.relative_to(_REPO_ROOT).as_posix()
                for p in missing_from_closure
            )
            raise AssertionError(
                f"R-1 DRIFT DETECTED: {len(missing_from_closure)} repo-local content "
                f"module(s) are imported on the production path but ABSENT from "
                f"_CLOSURE_FILES in versioning.py.\n\n"
                f"Missing files:\n"
                + "\n".join(f"  {f}" for f in missing_rel)
                + "\n\n"
                f"Fix: add each missing file to _CLOSURE_FILES tuple in "
                f"fresh_slotlab/analyzer/versioning.py, then recompute base_hash "
                f"and update the pin constants.\n\n"
                f"Per memory/feedback_invariant_with_fallback_hides_drift.md: "
                f"this guard FAILS loudly. Do NOT warn-and-pass."
            )

    def test_no_stale_file_in_closure(self):
        """FAIL if _CLOSURE_FILES references a file that does not exist on disk.

        Catches the case where a file was renamed/deleted but its old path
        remains in _CLOSURE_FILES (which would mean compute_base_analyzer_version
        raises FileNotFoundError at runtime, which is correct — but this test
        catches it earlier with a clearer message).
        """
        try:
            from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES, _REPO_ROOT as _VER_ROOT
        except ImportError:
            from analyzer.versioning import _CLOSURE_FILES, _REPO_ROOT as _VER_ROOT  # type: ignore[no-redef]

        missing_from_disk: list[str] = []
        for rel in _CLOSURE_FILES:
            p = _VER_ROOT / rel
            if not p.exists():
                missing_from_disk.append(rel)

        assert not missing_from_disk, (
            f"_CLOSURE_FILES in versioning.py references {len(missing_from_disk)} "
            f"file(s) that do not exist on disk:\n"
            + "\n".join(f"  {f}" for f in missing_from_disk)
            + "\n\nFix: remove deleted/renamed files from _CLOSURE_FILES and "
            f"recompute base_hash."
        )

    def test_closure_files_all_in_fresh_slotlab(self):
        """_CLOSURE_FILES must only reference files under fresh_slotlab/."""
        try:
            from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES
        except ImportError:
            from analyzer.versioning import _CLOSURE_FILES  # type: ignore[no-redef]

        bad_paths = [
            rel for rel in _CLOSURE_FILES
            if not rel.startswith("fresh_slotlab/")
        ]
        assert not bad_paths, (
            f"_CLOSURE_FILES contains paths not under fresh_slotlab/: {bad_paths}. "
            f"Only fresh_slotlab/ repo-local content files belong in the closure."
        )

    def test_closure_sorted_order(self):
        """_CLOSURE_FILES must be in sorted order (determinism guarantee)."""
        try:
            from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES
        except ImportError:
            from analyzer.versioning import _CLOSURE_FILES  # type: ignore[no-redef]

        assert list(_CLOSURE_FILES) == sorted(_CLOSURE_FILES), (
            f"_CLOSURE_FILES is not in sorted order. "
            f"Reorder the tuple alphabetically to guarantee deterministic hashing."
        )


# ---------------------------------------------------------------------------
# R-4 registration-completeness tests
# ---------------------------------------------------------------------------

class TestR4RegistrationCompleteness:
    """Every features/*.py (except _base.py and __init__.py) must be registered.

    Catches "forgot to add the new plugin to the registry import block" footgun.
    A plugin not in ALL_FEATURES would silently fall into base_hash instead of
    carrying its own feature_hash — causing FALSE-STALE ×393.

    INJECT-BUG: Create fresh_slotlab/analyzer/features/zzz_unregistered.py with
    a dummy AnalyzerFeature subclass but NO register() call.
    RED: test_all_feature_files_registered fires (zzz_unregistered.py found by
    glob but absent from ALL_FEATURES).
    Revert (delete the file) → GREEN.
    """

    def test_all_feature_files_registered(self):
        """Every features/*.py except _base.py and __init__.py must be in ALL_FEATURES.

        Compares the set of FEATURE_IDs from ALL_FEATURES against the set of
        plugin files discovered by glob. A file not registered would fall into
        base_hash (FALSE-STALE ×393 on any plugin change).

        INJECT-BUG: create an unregistered features/zzz_unregistered.py.
        RED: zzz_unregistered.py appears in glob but not in ALL_FEATURES → fails.
        Revert (delete file) → GREEN.
        """
        # Discover all features/*.py files except _base.py and __init__.py
        features_dir = _FRESH_SLOTLAB / "analyzer" / "features"
        assert features_dir.exists(), f"features/ dir not found: {features_dir}"

        all_plugin_files = {
            p.stem: p
            for p in sorted(features_dir.glob("*.py"))
            if p.stem not in ("_base", "__init__")
        }

        # Ensure plugins are registered (importing them triggers register())
        _get_registered_plugin_files()  # side effect: all 10 plugins imported (Phase E: +topdollar_choice)

        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES

        registered_module_stems = set()
        for feature in ALL_FEATURES:
            mod = sys.modules.get(feature.__class__.__module__)
            if mod is not None and getattr(mod, "__file__", None):
                registered_module_stems.add(Path(mod.__file__).stem)

        unregistered = {
            stem: path
            for stem, path in all_plugin_files.items()
            if stem not in registered_module_stems
        }

        assert not unregistered, (
            f"R-4 VIOLATION: {len(unregistered)} features/*.py file(s) exist but "
            f"are NOT in ALL_FEATURES:\n"
            + "\n".join(
                f"  {path.relative_to(_REPO_ROOT).as_posix()}"
                for path in sorted(unregistered.values())
            )
            + "\n\nFix: import the plugin in the feature-loading block in "
            f"versioning.py (compute_effective_version_for_machine) so it calls "
            f"register() and appears in ALL_FEATURES. A plugin not in ALL_FEATURES "
            f"falls into base_hash → FALSE-STALE ×393 on every plugin change.\n\n"
            f"Per memory/feedback_invariant_with_fallback_hides_drift.md: "
            f"this guard FAILS loudly. Do NOT warn-and-pass."
        )

    def test_base_py_and_init_excluded_from_check(self):
        """_base.py and __init__.py must NOT be in ALL_FEATURES (they stay in base).

        These two files ARE in the closure (_CLOSURE_FILES) but are NOT registered
        feature plugins — they form the ABC and package marker. If they appeared
        in ALL_FEATURES that would be a mis-registration.
        """
        _get_registered_plugin_files()  # ensure plugins are imported
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES

        all_feature_ids = {f.FEATURE_ID for f in ALL_FEATURES}

        # _base.py defines AnalyzerFeature ABC — it is abstract and cannot register
        # __init__.py is just a package marker with no AnalyzerFeature subclass

        registered_module_files = set()
        for feature in ALL_FEATURES:
            mod = sys.modules.get(feature.__class__.__module__)
            if mod is not None and getattr(mod, "__file__", None):
                registered_module_files.add(Path(mod.__file__).name)

        # Neither _base.py nor __init__.py should appear as a registered plugin module
        assert "_base.py" not in registered_module_files, (
            "_base.py appeared as a registered plugin module in ALL_FEATURES. "
            "It must stay in base (it is the ABC, not a plugin)."
        )
        assert "__init__.py" not in registered_module_files, (
            "features/__init__.py appeared as a registered plugin module. "
            "It must stay in base (it is the package marker, not a plugin)."
        )

    def test_registered_plugins_count(self):
        """Exactly 11 plugins must be registered after importing all known plugins.

        This is a count-guard: if a new plugin is added without being registered,
        the file-set check above catches it; if a plugin is registered twice
        (idempotency), the count here reveals the dedup worked correctly.

        Phase E update: count bumped 9→10 to include topdollar_choice.
        playtype-rearch: count bumped 10→11 to include spin_type_outcomes.
          spin_type_outcomes auto-registers via payouts_by_spin_type.py import
          (avoiding closure-file edits that would flip base_hash).
        """
        _get_registered_plugin_files()  # imports all 11 (including auto-registered)
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES

        assert len(ALL_FEATURES) == 11, (
            f"Expected exactly 11 registered plugins, got {len(ALL_FEATURES)}. "
            f"Registered FEATURE_IDs: {[f.FEATURE_ID for f in ALL_FEATURES]}. "
            f"If a new plugin was added, update this count AND ensure the plugin "
            f"is registered (either via direct import or via the auto-import "
            f"mechanism in an existing plugin file like payouts_by_spin_type.py)."
        )

    def test_no_plugin_path_in_closure(self):
        """Reverse R-4 guard: no feature-plugin file may appear in _CLOSURE_FILES.

        test_all_feature_files_registered is the FORWARD guard (a plugin that is
        not registered → falls into base). This is the REVERSE: a plugin file
        whose path leaked INTO _CLOSURE_FILES. If that happens, editing that ONE
        plugin flips the shared base_hash → marks ALL reports stale
        (false-stale ×393) — the exact failure mode this whole phase exists to
        prevent.

        Uses the features/*.py glob (NOT the registry) so it catches a future
        10th plugin that is correctly registered but mistakenly added to the
        closure, as well as any unregistered plugin file. _base.py and
        __init__.py are EXCLUDED from the glob because they ARE legitimately in
        the closure (shared infra, not plugins).

        INJECT-BUG: add e.g.
        "fresh_slotlab/analyzer/features/payouts_by_spin_type.py" to
        _CLOSURE_FILES in versioning.py.
        RED: the intersection is non-empty → this test fails.
        Revert → GREEN.
        """
        features_dir = _FRESH_SLOTLAB / "analyzer" / "features"
        assert features_dir.exists(), f"features/ dir not found: {features_dir}"

        plugin_files = {
            p.resolve()
            for p in features_dir.glob("*.py")
            if p.stem not in ("_base", "__init__")
        }

        closure = _get_closure_set()
        leaked = plugin_files & closure

        assert not leaked, (
            f"R-4 REVERSE VIOLATION: {len(leaked)} feature-plugin file(s) appear "
            f"in _CLOSURE_FILES (the shared base_hash closure):\n"
            + "\n".join(
                f"  {p.relative_to(_REPO_ROOT).as_posix()}"
                for p in sorted(leaked)
            )
            + "\n\nA plugin file in the closure means editing that ONE plugin "
            f"flips the shared base_hash → marks ALL reports stale "
            f"(false-stale ×393), the exact failure this phase exists to prevent. "
            f"Registered plugins carry their own feature_hash and MUST be EXCLUDED "
            f"from _CLOSURE_FILES (R-4).\n\n"
            f"Fix: remove the plugin path(s) from _CLOSURE_FILES in "
            f"fresh_slotlab/analyzer/versioning.py. Under features/, only _base.py "
            f"and __init__.py (shared infra) belong in the closure.\n\n"
            f"Per memory/feedback_invariant_with_fallback_hides_drift.md: "
            f"this guard FAILS loudly. Do NOT warn-and-pass."
        )


# ---------------------------------------------------------------------------
# Content-coverage flip test (acceptance check per brief §5.1/5.2)
# ---------------------------------------------------------------------------

class TestContentCoverageFlip:
    """Verify the closure covers production-path modules: a synthetic edit to
    one flips base_hash; editing a registered plugin does NOT.

    This test uses the ``closure_files=`` seam to inject a modified synthetic
    closure, avoiding any actual disk modification.
    """

    def _compute_with_one_file_zeroed(self, rel_path: str) -> str:
        """Compute base_hash with one closure file replaced by b'MODIFIED' (simulates a change).

        We can't actually edit the file in a unit test, so instead we hash a
        modified set where the target file's bytes are replaced with b'MODIFIED'
        — this produces a different hash, simulating what happens when that file
        is edited.

        Uses the same CRLF normalization as compute_base_analyzer_version() (FIX-2)
        so that the simulated hash is directly comparable to the live function output.
        """
        try:
            from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES, _REPO_ROOT as _VER_ROOT
        except ImportError:
            from analyzer.versioning import _CLOSURE_FILES, _REPO_ROOT as _VER_ROOT  # type: ignore[no-redef]

        h = hashlib.sha256()
        for rel in sorted(_CLOSURE_FILES):
            p = _VER_ROOT / rel
            if rel == rel_path:
                h.update(b"MODIFIED")  # simulate an edit; b'MODIFIED' has no \r\n so normalization is a no-op
            else:
                # Apply the same CRLF→LF normalization as the live function (FIX-2).
                # Without this, on Windows the local hash would differ from actual_hash
                # even when the same file set is used, because the live function normalizes
                # but this local loop would not.
                h.update(p.read_bytes().replace(b"\r\n", b"\n"))
        return h.hexdigest()[:12]

    def test_editing_round_classification_flips_base(self):
        """Simulating an edit to round_classification.py must flip base_hash.

        round_classification.py is a key content module (the documented single
        source of truth for round semantics, with 5 past fleet-wide bug families).
        Under the old core/*.py glob it was NOT hashed → FALSE-FRESH. Under R-1
        it IS hashed → a fix to round_classification.py correctly flips base.
        """
        try:
            from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        except ImportError:
            from analyzer.versioning import compute_base_analyzer_version  # type: ignore[no-redef]

        actual_hash = compute_base_analyzer_version()
        modified_hash = self._compute_with_one_file_zeroed(
            "fresh_slotlab/round_classification.py"
        )
        assert actual_hash != modified_hash, (
            "Simulating an edit to round_classification.py must flip base_hash. "
            "If they are equal, round_classification.py is NOT in the closure — "
            "the R-1 fix failed to include it."
        )

    def test_editing_round_win_flips_base(self):
        """Simulating an edit to round_win.py must flip base_hash."""
        try:
            from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        except ImportError:
            from analyzer.versioning import compute_base_analyzer_version  # type: ignore[no-redef]

        actual_hash = compute_base_analyzer_version()
        modified_hash = self._compute_with_one_file_zeroed(
            "fresh_slotlab/round_win.py"
        )
        assert actual_hash != modified_hash, (
            "Simulating an edit to round_win.py must flip base_hash. "
            "round_win.py is a content module and must be in the closure."
        )

    def test_editing_trigger_sessions_flips_base(self):
        """Simulating an edit to trigger_sessions.py must flip base_hash."""
        try:
            from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        except ImportError:
            from analyzer.versioning import compute_base_analyzer_version  # type: ignore[no-redef]

        actual_hash = compute_base_analyzer_version()
        modified_hash = self._compute_with_one_file_zeroed(
            "fresh_slotlab/trigger_sessions.py"
        )
        assert actual_hash != modified_hash, (
            "Simulating an edit to trigger_sessions.py must flip base_hash."
        )

    def test_editing_sampler_flips_base(self):
        """Simulating an edit to sampler.py must flip base_hash."""
        try:
            from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        except ImportError:
            from analyzer.versioning import compute_base_analyzer_version  # type: ignore[no-redef]

        actual_hash = compute_base_analyzer_version()
        modified_hash = self._compute_with_one_file_zeroed(
            "fresh_slotlab/sampler.py"
        )
        assert actual_hash != modified_hash, (
            "Simulating an edit to sampler.py must flip base_hash."
        )

    def test_editing_machine_md5_flips_base(self):
        """Simulating an edit to machine_md5.py must flip base_hash."""
        try:
            from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        except ImportError:
            from analyzer.versioning import compute_base_analyzer_version  # type: ignore[no-redef]

        actual_hash = compute_base_analyzer_version()
        modified_hash = self._compute_with_one_file_zeroed(
            "fresh_slotlab/machine_md5.py"
        )
        assert actual_hash != modified_hash, (
            "Simulating an edit to machine_md5.py must flip base_hash."
        )

    def test_editing_a_core_file_flips_base(self):
        """Simulating an edit to a core/*.py file must flip base_hash.

        core/*.py files were already in the old glob; they remain in the
        R-1 closure. This confirms backward compat with the original intent.
        """
        try:
            from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        except ImportError:
            from analyzer.versioning import compute_base_analyzer_version  # type: ignore[no-redef]

        actual_hash = compute_base_analyzer_version()
        modified_hash = self._compute_with_one_file_zeroed(
            "fresh_slotlab/analyzer/core/parser.py"
        )
        assert actual_hash != modified_hash, (
            "Simulating an edit to core/parser.py must flip base_hash. "
            "core/*.py files are still in the closure under R-1."
        )

    def test_editing_versioning_py_flips_base(self):
        """Simulating an edit to versioning.py itself must flip base_hash.

        versioning.py is in its own closure (self-referential). Editing the
        closure set or any function in versioning.py changes its bytes →
        base_hash changes. This is correct: the hash algorithm changed.
        """
        try:
            from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        except ImportError:
            from analyzer.versioning import compute_base_analyzer_version  # type: ignore[no-redef]

        actual_hash = compute_base_analyzer_version()
        modified_hash = self._compute_with_one_file_zeroed(
            "fresh_slotlab/analyzer/versioning.py"
        )
        assert actual_hash != modified_hash, (
            "Simulating an edit to versioning.py must flip base_hash. "
            "versioning.py is in its own closure (self-referential inclusion)."
        )

    def test_registered_plugin_edit_does_not_flip_base(self):
        """Simulating an edit to a registered plugin must NOT flip base_hash.

        Registered feature plugins are excluded from base_hash by R-4. Their
        hash is carried by the feature's own compute_hash() and only affects
        machines that declare that plugin in their manifest.

        INJECT-BUG: add a registered plugin path to this list.
        RED: that plugin IS in _CLOSURE_FILES → modified hash == real hash only
        if it was already excluded. If it's in the closure, modified hash differs
        → the exclusion failed.
        Revert → GREEN.
        """
        import hashlib
        try:
            from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES, _REPO_ROOT as _VER_ROOT, compute_base_analyzer_version
        except ImportError:
            from analyzer.versioning import _CLOSURE_FILES, _REPO_ROOT as _VER_ROOT, compute_base_analyzer_version  # type: ignore[no-redef]

        actual_hash = compute_base_analyzer_version()

        # These are all 11 registered plugin files. Simulating edits to them
        # must NOT change base_hash (they are excluded by R-4).
        plugin_paths = [
            "fresh_slotlab/analyzer/features/payouts_by_spin_type.py",
            "fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py",
            "fresh_slotlab/analyzer/features/bankruptcy_simulation.py",
            "fresh_slotlab/analyzer/features/multiplier_profile.py",
            "fresh_slotlab/analyzer/features/multiplier_wild.py",
            "fresh_slotlab/analyzer/features/machine_mechanics.py",
            "fresh_slotlab/analyzer/features/upstream_feature_breakdown.py",
            "fresh_slotlab/analyzer/features/collect_mechanic.py",
            "fresh_slotlab/analyzer/features/bonus_chain_dynamics.py",
            "fresh_slotlab/analyzer/features/topdollar_choice.py",
            "fresh_slotlab/analyzer/features/spin_type_outcomes.py",  # playtype-rearch
        ]

        for plugin_path in plugin_paths:
            # Simulating an edit: hash the closure with this plugin's bytes
            # replaced by b'MODIFIED'. Since the plugin is NOT in _CLOSURE_FILES,
            # the loop below should produce the same hash as the real hash.
            # Apply the same CRLF→LF normalization as the live function (FIX-2)
            # so that `simulated` is directly comparable to `actual_hash`.
            h = hashlib.sha256()
            for rel in sorted(_CLOSURE_FILES):
                p = _VER_ROOT / rel
                # None of these plugin paths appear in _CLOSURE_FILES, so this
                # branch is never hit — but we guard anyway to be explicit.
                if rel == plugin_path:
                    h.update(b"MODIFIED")
                else:
                    h.update(p.read_bytes().replace(b"\r\n", b"\n"))
            simulated = h.hexdigest()[:12]

            assert simulated == actual_hash, (
                f"Simulating an edit to registered plugin {plugin_path!r} changed "
                f"base_hash from {actual_hash!r} to {simulated!r}. "
                f"This plugin is registered in ALL_FEATURES and should be EXCLUDED "
                f"from _CLOSURE_FILES (R-4). Check that this plugin path is NOT in "
                f"_CLOSURE_FILES in versioning.py."
            )


# ---------------------------------------------------------------------------
# FIX-2: CRLF normalization regression test
# ---------------------------------------------------------------------------

class TestCRLFNormalization:
    """FIX-2 regression guard: base_hash must be identical regardless of whether
    closure files contain CRLF or LF line endings.

    Without ``raw.replace(b"\\r\\n", b"\\n")`` in the hash loop, the hash would
    flip when switching between Windows (CRLF) and Linux (LF) checkouts, or when
    adding a .gitattributes that changes core.autocrlf. That would mark all 393+
    reports stale without any code change — a false-stale lie that is as wrong as
    a false-fresh lie.

    Test strategy: create a synthetic 2-file closure in a temp directory, writing
    the same content once with ``\\r\\n`` and once with ``\\n``. Use the
    ``closure_files=``/``repo_root=`` seam to inject it into
    ``compute_base_analyzer_version``. Assert both return the same hash.

    INJECT-BUG (FIX-2):
        In fresh_slotlab/analyzer/versioning.py, change:
            h.update(raw.replace(b"\\r\\n", b"\\n"))
        to:
            h.update(raw)
        RED: test_crlf_and_lf_produce_same_hash fails (the two variants produce
        different hashes because CRLF bytes != LF bytes).
        Revert (restore .replace(...)) → GREEN.

    Memory feedback honored:
    - memory/feedback_md5_is_a_tag_not_a_destruction_signal.md — false-stale
      is a honesty violation, not just an inconvenience.
    - memory/feedback_no_silent_swallow.md — normalization failures must be
      visible, not silently tolerated.
    """

    def test_crlf_and_lf_produce_same_hash(self, tmp_path):
        """CRLF and LF variants of the same content must yield identical base_hash.

        Creates two synthetic closure files (a.py, b.py) in two temp directories:
        - lf_dir/: content with LF (\\n) line endings
        - crlf_dir/: same content with CRLF (\\r\\n) line endings

        Passes each as a synthetic closure (closure_files=, repo_root=) to
        compute_base_analyzer_version. Asserts both return the same 12-char hex.

        INJECT-BUG PROOF: see class docstring. Remove .replace(b"\\r\\n", b"\\n")
        in versioning.py → this test goes RED → restore → GREEN.
        """
        try:
            from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        except ImportError:
            from analyzer.versioning import compute_base_analyzer_version  # type: ignore[no-redef]

        # Synthetic content (same logical content, different line endings)
        content_lf = b"# synthetic test file\ndef foo():\n    return 1\n"
        content_b_lf = b"# second synthetic file\nX = 42\n# end\n"

        content_crlf = content_lf.replace(b"\n", b"\r\n")
        content_b_crlf = content_b_lf.replace(b"\n", b"\r\n")

        # Verify we actually have different bytes (guard against replace being a no-op)
        assert content_lf != content_crlf, "Test setup error: LF and CRLF variants are identical"
        assert content_b_lf != content_b_crlf, "Test setup error: LF and CRLF variants are identical"

        # Build LF closure directory
        lf_dir = tmp_path / "lf_root"
        (lf_dir / "fresh_slotlab").mkdir(parents=True)
        (lf_dir / "fresh_slotlab" / "a.py").write_bytes(content_lf)
        (lf_dir / "fresh_slotlab" / "b.py").write_bytes(content_b_lf)

        # Build CRLF closure directory (same logical content, CRLF bytes)
        crlf_dir = tmp_path / "crlf_root"
        (crlf_dir / "fresh_slotlab").mkdir(parents=True)
        (crlf_dir / "fresh_slotlab" / "a.py").write_bytes(content_crlf)
        (crlf_dir / "fresh_slotlab" / "b.py").write_bytes(content_b_crlf)

        # Synthetic closure: two repo-relative paths
        synthetic_closure: tuple[str, ...] = (
            "fresh_slotlab/a.py",
            "fresh_slotlab/b.py",
        )

        # Compute hash for LF variant
        hash_lf = compute_base_analyzer_version(
            closure_files=synthetic_closure,
            repo_root=lf_dir,
        )

        # Compute hash for CRLF variant
        hash_crlf = compute_base_analyzer_version(
            closure_files=synthetic_closure,
            repo_root=crlf_dir,
        )

        assert hash_lf == hash_crlf, (
            f"FIX-2 REGRESSION: CRLF and LF variants of the same content produced "
            f"different base_hash values:\n"
            f"  hash_lf   = {hash_lf!r}\n"
            f"  hash_crlf = {hash_crlf!r}\n"
            f"This means raw.replace(b'\\r\\n', b'\\n') is missing from the hash loop "
            f"in compute_base_analyzer_version() in fresh_slotlab/analyzer/versioning.py.\n"
            f"Without this normalization, checking out on Linux or adding .gitattributes "
            f"would flip base_hash and mark all 393+ reports stale — a false-stale lie.\n"
            f"Fix: restore h.update(raw.replace(b'\\r\\n', b'\\n')) in the hash loop."
        )

    def test_crlf_normalization_is_symmetric(self, tmp_path):
        """LF-only files and CRLF files normalize to the same intermediate bytes.

        Extra sanity: verifies that the normalization operation on LF-only content
        is a no-op (``b'\\n'`` unchanged by ``.replace(b'\\r\\n', b'\\n')``).
        This is a property test, not a hash test.
        """
        lf_bytes = b"# test\nfoo = 1\n"
        crlf_bytes = lf_bytes.replace(b"\n", b"\r\n")

        # Normalize both
        lf_normalized = lf_bytes.replace(b"\r\n", b"\n")
        crlf_normalized = crlf_bytes.replace(b"\r\n", b"\n")

        assert lf_normalized == lf_bytes, (
            "LF-only bytes changed after CRLF normalization — the normalize op is not a no-op on LF content"
        )
        assert crlf_normalized == lf_bytes, (
            "CRLF→LF normalization did not produce LF-only bytes"
        )
        assert lf_normalized == crlf_normalized, (
            "LF-only and CRLF normalized forms differ — normalization is not idempotent"
        )


# ---------------------------------------------------------------------------
# P5: FileNotFoundError regression test (per memory/feedback_no_silent_swallow.md)
# ---------------------------------------------------------------------------

class TestFileNotFoundError:
    """P5: compute_base_analyzer_version() must raise FileNotFoundError (not
    silently return a wrong/partial hash) when a closure file is missing.

    This directly exercises the production error path in versioning.py — if the
    `FileNotFoundError` raise is removed or replaced with a silent `except: pass`,
    the function would return a shorter (wrong) hash derived from only the
    files that exist. That is the "false-fresh" hole: the hash would still look
    like a valid 12-char hex, but it would not cover all closure files.

    Per memory/feedback_no_silent_swallow.md: a missing closure file is a hard
    error — it indicates a broken install or an out-of-date _CLOSURE_FILES.
    Never silently swallow it.

    INJECT-BUG recipe
    -----------------
    In fresh_slotlab/analyzer/versioning.py, replace:
        if not source_file.exists():
            raise FileNotFoundError(...)
    with:
        if not source_file.exists():
            continue  # INJECT-BUG: silently skip missing file
    RED: test_missing_closure_file_raises_file_not_found_error passes a nonexistent
    closure path → the function no longer raises → pytest.raises block fails
    (the function returned a (wrong) hash instead of raising).
    Revert → GREEN.

    Memory feedback honored
    -----------------------
    - memory/feedback_no_silent_swallow.md — missing closure file is NOT swallowed.
    - memory/feedback_enumerate_safety_paths.md — inject-bug documented above.
    - memory/feedback_invariant_with_fallback_hides_drift.md — partial/wrong
      hash returned silently is equivalent to a silent fallback hiding drift.
    """

    def test_missing_closure_file_raises_file_not_found_error(self, tmp_path):
        """FAIL if compute_base_analyzer_version() does NOT raise FileNotFoundError
        when a closure file path does not exist on disk.

        Uses the closure_files= / repo_root= seam to pass a synthetic closure
        with one nonexistent file. Asserts FileNotFoundError is raised — not
        swallowed, not returned as a partial hash.

        INJECT-BUG: change `raise FileNotFoundError(...)` to `continue` in
        versioning.py line ~207 (inside the hash loop).
        RED: FileNotFoundError is not raised → pytest.raises block fails with
             "DID NOT RAISE <class 'FileNotFoundError'>".
        Revert → GREEN.
        """
        try:
            from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        except ImportError:
            from analyzer.versioning import compute_base_analyzer_version  # type: ignore[no-redef]

        # Create one real file so the hash loop starts; the second entry is nonexistent
        real_dir = tmp_path / "root"
        (real_dir / "fresh_slotlab").mkdir(parents=True)
        (real_dir / "fresh_slotlab" / "real_file.py").write_bytes(b"# real content\n")

        synthetic_closure: tuple[str, ...] = (
            "fresh_slotlab/real_file.py",
            "fresh_slotlab/this_file_does_not_exist_p5_test.py",  # nonexistent
        )

        with pytest.raises(FileNotFoundError) as exc_info:
            compute_base_analyzer_version(
                closure_files=synthetic_closure,
                repo_root=real_dir,
            )

        # Verify the error message is informative (not an accidental re-raise from elsewhere)
        error_msg = str(exc_info.value)
        assert "this_file_does_not_exist_p5_test.py" in error_msg, (
            f"FileNotFoundError was raised but message does not name the missing file. "
            f"Got: {error_msg!r}. "
            f"The error message should identify which file is missing so operators can debug."
        )
        assert "Closure file does not exist" in error_msg or "does not exist" in error_msg, (
            f"FileNotFoundError message is unhelpful — should say 'Closure file does not exist'. "
            f"Got: {error_msg!r}. "
            f"Per memory/feedback_no_silent_swallow.md: error messages must be diagnostic."
        )

    def test_missing_closure_file_does_not_return_partial_hash(self, tmp_path):
        """Complementary: confirm no partial hash is returned when a file is missing.

        If a future change added `except FileNotFoundError: continue` to the hash
        loop (silently skipping missing files), the function would return a wrong
        hash that appears valid. This test confirms the function raises rather than
        returning any value.

        This is a belt-and-suspenders test alongside
        test_missing_closure_file_raises_file_not_found_error.
        """
        try:
            from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        except ImportError:
            from analyzer.versioning import compute_base_analyzer_version  # type: ignore[no-redef]

        real_dir = tmp_path / "root2"
        (real_dir / "fresh_slotlab").mkdir(parents=True)
        (real_dir / "fresh_slotlab" / "exists.py").write_bytes(b"# exists\n")

        synthetic_closure: tuple[str, ...] = (
            "fresh_slotlab/exists.py",
            "fresh_slotlab/does_not_exist_at_all.py",
        )

        raised = False
        try:
            result = compute_base_analyzer_version(
                closure_files=synthetic_closure,
                repo_root=real_dir,
            )
        except FileNotFoundError:
            raised = True
        except Exception as exc:
            raise AssertionError(
                f"Expected FileNotFoundError but got {type(exc).__name__}: {exc}. "
                f"Missing closure file must raise FileNotFoundError, not any other exception."
            ) from exc

        assert raised, (
            "compute_base_analyzer_version() DID NOT raise FileNotFoundError when a "
            "closure file was missing. It may have returned a partial hash — this is a "
            "silent-swallow bug. Per memory/feedback_no_silent_swallow.md: missing "
            "closure files must never be silently skipped.\n"
            "INJECT-BUG: Change `raise FileNotFoundError(...)` to `continue` in the "
            "hash loop in versioning.py and observe this test goes RED."
        )
