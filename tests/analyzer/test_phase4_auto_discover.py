"""Phase 4 root-fix gate: auto-discover plugins; new plugin does NOT flip base_hash.

Gate per ANALYZER_ARCHITECTURE.md §6 Phase 4 / §5 invariant 2:
  (a) discover_features() finds a newly-added plugin file without any hardcoded
      import list edit — the auto-discovery route works.
  (b) compute_base_analyzer_version() is UNCHANGED after adding a new plugin file
      — adding a plugin no longer re-flags the whole fleet.

The "inject" here is: write a throwaway dummy plugin file, call discover_features(),
assert it is in ALL_FEATURES (auto-found), assert base_hash is the same as before
the dummy existed, then delete the dummy.

Inject-bug recipe (to prove the test is meaningful):
  - Remove the `discover_features()` call from versioning.py and use an old
    hardcoded list that omits `_probe_phase4` → (a) fires RED (not in registry).
  - Add `_probe_phase4.py` to _CLOSURE_FILES → (b) fires RED (base_hash changed).
  Both prove the test is actually gating the root fix, not just passing vacuously.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_FEATURES_DIR = _REPO / "fresh_slotlab" / "analyzer" / "features"
_PROBE_FILE = _FEATURES_DIR / "_probe_phase4.py"

# Minimal no-op AnalyzerFeature plugin: valid module, unique FEATURE_ID.
_PROBE_SOURCE = textwrap.dedent("""\
    \"\"\"Throwaway probe plugin for Phase 4 root-fix inject test.

    This file is created and deleted by test_phase4_auto_discover.py.
    It must never be committed to the repository.
    \"\"\"
    from __future__ import annotations
    from typing import ClassVar, Any

    try:
        from fresh_slotlab.analyzer.features._base import AnalyzerFeature
        from fresh_slotlab.analyzer.feature_registry import register
    except ImportError:
        from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
        from analyzer.feature_registry import register  # type: ignore[no-redef]


    class _ProbePhase4Feature(AnalyzerFeature):
        FEATURE_ID: ClassVar[str] = "_probe_phase4"
        SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ()
        SCHEMA_VERSION: ClassVar[int] = 1
        REQUIRES: ClassVar[tuple[str, ...]] = ()
        DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
        RTP_CONTRIBUTION: ClassVar[bool] = False

        # Correct extract() signature: (self, parse_state, chunk_dict) per _base.py.
        def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
            return {}

        def reduce(self, prev_acc: Any, this_acc: Any) -> dict:
            return {}

        def emit(self, final_acc: Any, summary: dict, ctx: Any) -> None:
            pass


    register(_ProbePhase4Feature())
""")

_PROBE_FEATURE_ID = "_probe_phase4"


class TestPhase4AutoDiscover:
    """Root-fix inject tests: adding a plugin file does NOT flip base_hash."""

    def setup_method(self, method):
        """Ensure probe file is absent before each test (clean slate)."""
        if _PROBE_FILE.exists():
            _PROBE_FILE.unlink()

    def teardown_method(self, method):
        """Delete probe file, un-import probe module, remove from ALL_FEATURES."""
        if _PROBE_FILE.exists():
            _PROBE_FILE.unlink()
        # Remove the probe module from sys.modules so later tests don't see it.
        import sys
        for key in list(sys.modules.keys()):
            if "_probe_phase4" in key:
                del sys.modules[key]
        # Remove probe from ALL_FEATURES so later tests (including module-scope
        # fixtures in other test files) don't see the probe feature.
        # This is CRITICAL for test isolation: the probe feature registered here
        # must not contaminate the global registry for downstream tests.
        try:
            from fresh_slotlab.analyzer import feature_registry
        except ImportError:
            return
        feature_registry.ALL_FEATURES[:] = [
            f for f in feature_registry.ALL_FEATURES
            if f.FEATURE_ID != _PROBE_FEATURE_ID
        ]

    def test_a_probe_auto_discovered(self):
        """(a) After adding a plugin file, discover_features() finds it automatically.

        Root-fix inject: the probe FEATURE_ID must appear in ALL_FEATURES after
        discover_features() — no edit to any hardcoded list required.

        Inject-bug: replace discover_features() with the old hardcoded list
        (omitting _probe_phase4) → this assertion fires RED.
        """
        try:
            import sys
            # Remove any stale cached state for feature_registry so ALL_FEATURES
            # starts fresh for this test (other tests in the suite may already
            # have populated it; we need a clean view that includes the probe).
            # We do NOT reset ALL_FEATURES itself — we assert the probe IS added.
            from fresh_slotlab.analyzer import feature_registry
            from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        except ImportError:
            pytest.skip("fresh_slotlab not importable")

        # Capture base_hash BEFORE the probe file exists.
        base_before = compute_base_analyzer_version()

        # Write the probe file.
        _PROBE_FILE.write_text(_PROBE_SOURCE, encoding="utf-8")

        # Remove any cached import of the probe (it didn't exist yet, but be safe).
        for key in list(sys.modules.keys()):
            if "_probe_phase4" in key:
                del sys.modules[key]

        # Run discovery (idempotent for already-registered features; adds probe).
        feature_registry.discover_features()

        # Assert (a): probe is in ALL_FEATURES.
        registered_ids = {f.FEATURE_ID for f in feature_registry.ALL_FEATURES}
        assert _PROBE_FEATURE_ID in registered_ids, (
            f"_probe_phase4 was NOT found in ALL_FEATURES after discover_features().\n"
            f"Registered IDs: {sorted(registered_ids)}\n"
            f"This means discover_features() did not auto-find the new plugin file.\n"
            f"Inject-bug: if the old hardcoded list (no probe) is used instead of "
            f"discover_features(), this assertion fires RED."
        )

        # Assert (b): base_hash is unchanged by adding the probe file.
        # Plugin files live in features/ which is base-excluded (R-4), so editing
        # features/ never touches _CLOSURE_FILES → base_hash must be stable.
        base_after = compute_base_analyzer_version()
        assert base_after == base_before, (
            f"base_hash CHANGED after adding a plugin file — the root fix is broken.\n"
            f"  before: {base_before!r}\n"
            f"  after:  {base_after!r}\n"
            f"Plugin files in features/ must be base-excluded (R-4). "
            f"Inject-bug: if _probe_phase4.py were added to _CLOSURE_FILES, this fires RED."
        )

    def test_b_base_hash_stable_with_probe_present(self):
        """(b) base_hash is identical whether or not the probe file exists.

        This is the standalone form of the fleet-impact invariant: a new plugin
        file must not flip base_hash.  Complements test_a by testing from the
        other direction (probe file already present, base_hash computed fresh).
        """
        try:
            from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        except ImportError:
            pytest.skip("fresh_slotlab not importable")

        # Without probe.
        base_without = compute_base_analyzer_version()

        # With probe written to disk.
        _PROBE_FILE.write_text(_PROBE_SOURCE, encoding="utf-8")
        base_with = compute_base_analyzer_version()

        assert base_with == base_without, (
            f"base_hash differs when probe file is present vs absent.\n"
            f"  without probe: {base_without!r}\n"
            f"  with probe:    {base_with!r}\n"
            f"features/ files are base-excluded (R-4): _probe_phase4.py must NOT "
            f"affect base_hash. Check _CLOSURE_FILES — it must not glob features/."
        )

    def test_c_discover_is_idempotent(self):
        """discover_features() called twice leaves ALL_FEATURES unchanged (no duplicates).

        Verifies the idempotency contract: register() deduplicates by FEATURE_ID.
        """
        try:
            from fresh_slotlab.analyzer import feature_registry
        except ImportError:
            pytest.skip("fresh_slotlab not importable")

        # Write probe so both calls see it.
        _PROBE_FILE.write_text(_PROBE_SOURCE, encoding="utf-8")

        import sys
        for key in list(sys.modules.keys()):
            if "_probe_phase4" in key:
                del sys.modules[key]

        feature_registry.discover_features()
        count_after_first = len(feature_registry.ALL_FEATURES)
        ids_after_first = [f.FEATURE_ID for f in feature_registry.ALL_FEATURES]

        feature_registry.discover_features()
        count_after_second = len(feature_registry.ALL_FEATURES)
        ids_after_second = [f.FEATURE_ID for f in feature_registry.ALL_FEATURES]

        assert count_after_first == count_after_second, (
            f"discover_features() is not idempotent: "
            f"first call registered {count_after_first} features, "
            f"second call registered {count_after_second}. "
            f"Duplicate FEATURE_IDs: "
            f"{sorted(set(ids_after_second) - set(ids_after_first))}"
        )


class TestPhase4ExclusionSet:
    """_base.py and __init__.py must never be imported as plugins."""

    def test_base_and_init_excluded(self):
        """discover_features() does NOT attempt to import _base.py or __init__.py.

        These are ABC definitions / package markers that live in features/ but
        are NOT plugins.  They must remain in _CLOSURE_FILES (contributing to
        base_hash), not in ALL_FEATURES.
        """
        try:
            from fresh_slotlab.analyzer import feature_registry
        except ImportError:
            pytest.skip("fresh_slotlab not importable")

        feature_registry.discover_features()
        registered_ids = {f.FEATURE_ID for f in feature_registry.ALL_FEATURES}

        # AnalyzerFeature ABC itself has FEATURE_ID = "" — if _base.py were
        # accidentally imported as a plugin, an instance with FEATURE_ID=""
        # would be registered.
        assert "" not in registered_ids, (
            "_base.py was accidentally imported as a plugin (FEATURE_ID='' found). "
            "_DISCOVERY_EXCLUDE must contain '_base.py'."
        )

        # Confirm the exclusion set constant is correct.
        from fresh_slotlab.analyzer.feature_registry import _DISCOVERY_EXCLUDE
        assert "_base.py" in _DISCOVERY_EXCLUDE
        assert "__init__.py" in _DISCOVERY_EXCLUDE
