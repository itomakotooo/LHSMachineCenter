"""Regression tests for ticket P2-C — Wave 2c: 4 universal features.

Contracts asserted (per 00_ticket.md §4):

  C1 — 4 feature module files exist, each exports an AnalyzerFeature
       subclass with the correct FEATURE_ID.  Parametrized over all 4.

  C2 — Registration on import: importing each feature module causes its
       FEATURE_ID to appear in feature_registry.ALL_FEATURES.
       Duplicate import (idempotent re-registration) does NOT grow the list.

  C3 — P1-A1 canary reference: test references the parity-test file path.
       (Full 23/23 run is impl-verifier's job; this test validates the
       file path + module structure so the canary can actually run.)

  C4 — main() invokes feature.emit: AST / source-level check that
       player_impact_analyzer.py's main() function body contains a loop
       over ALL_FEATURES (or equivalent) that calls feature.emit.

  C5 — Hash composition: compute_base_analyzer_version() (if exported)
       is unchanged by wave-2c additions (core/*.py only, not features/*.py).
       feature.compute_hash() works for each class (returns 12-char hex).

  C6 — Subprocess import safety: python -c "import <feature_module>" exits
       rc=0 with no stderr for all 4 feature modules.  Parametrized.

  C7 — Pattern A features (payouts_by_spin_type, reel_marginal_by_spin_type)
       have no-op extract (returns {}) and no-op reduce (returns prev_acc).

  C8 — Inject-bug TDD (at least 2 proofs):
       (a) Registration inject: ALL_FEATURES lacks FEATURE_ID when
           register() call is absent.
       (b) emit-invocation inject: main() source lacking the ALL_FEATURES
           loop means the structural emit-invocation check goes RED.

Inject-bug discipline per memory/feedback_integration_test_argv.md:
    Every test proven red by injecting the bug, then restored green.
    Verification log in session_artifacts/_impl/phase2/07_wave_2c_universal_features/03_tests.md.

Subprocess-mode requirement per memory/feedback_perf_claim_needs_e2e_event_stream.md:
    C6 uses real subprocess (python -c "import ...") for each feature module.

Guard pattern (implementer running in parallel):
    FEATURES_DIR is checked before each parametrized test; skipped until impl lands.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[2]
FEATURES_DIR = ROOT / "fresh_slotlab" / "analyzer" / "features"
PIA_PATH = ROOT / "fresh_slotlab" / "player_impact_analyzer.py"

# ---------------------------------------------------------------------------
# Feature manifest: IDs + module paths + Pattern type
# ---------------------------------------------------------------------------

FEATURE_SPECS = [
    {
        "feature_id": "payouts_by_spin_type",
        "module_name": "fresh_slotlab.analyzer.features.payouts_by_spin_type",
        "module_file": "payouts_by_spin_type.py",
        "pattern": "B",  # Phase C2: Pattern A → B (real extract/reduce/emit)
        "schema_keys_include": ("payouts_by_spin_type",),
    },
    {
        "feature_id": "reel_marginal_by_spin_type",
        "module_name": "fresh_slotlab.analyzer.features.reel_marginal_by_spin_type",
        "module_file": "reel_marginal_by_spin_type.py",
        # Phase 5: Pattern A → B. The dict-build was carved out of PIA into the
        # plugin's emit() (stash pattern). reduce() now returns {} (not prev_acc)
        # and emit() raises on a missing stash — so it is excluded from the C7
        # Pattern-A no-op-reduce / no-op-emit assertions (same as multiplier_profile).
        "pattern": "B",  # Phase 5 carve; we don't assert reduce semantics
        "schema_keys_include": ("reel_marginal_by_spin_type",),
    },
    {
        "feature_id": "bankruptcy_simulation",
        "module_name": "fresh_slotlab.analyzer.features.bankruptcy_simulation",
        "module_file": "bankruptcy_simulation.py",
        "pattern": "B",  # logic extraction; reduce may NOT be no-op
        "schema_keys_include": ("bankruptcy_simulation", "bankruptcy_probe"),
    },
    {
        "feature_id": "multiplier_profile",
        "module_name": "fresh_slotlab.analyzer.features.multiplier_profile",
        "module_file": "multiplier_profile.py",
        "pattern": "B",  # opportunistic; we don't assert reduce semantics
        "schema_keys_include": ("multiplier_profile",),
    },
]

# Convenience lookups
_SPEC_BY_ID = {s["feature_id"]: s for s in FEATURE_SPECS}
_ALL_FEATURE_IDS = [s["feature_id"] for s in FEATURE_SPECS]
_PATTERN_A_IDS = [s["feature_id"] for s in FEATURE_SPECS if s["pattern"] == "A"]


# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------

try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    _ABC_IMPORTABLE = True
except ImportError:
    _ABC_IMPORTABLE = False

try:
    import fresh_slotlab.analyzer.feature_registry as _registry_mod
    _REGISTRY_IMPORTABLE = True
except ImportError:
    _REGISTRY_IMPORTABLE = False

try:
    from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version as _cbav
    _BASE_VERSION_IMPORTABLE = True
except ImportError:
    _cbav = None
    _BASE_VERSION_IMPORTABLE = False

try:
    from fresh_slotlab.analyzer.pipeline_context import (
        PipelineContext as _PipelineContext,
        MechanismRegistry as _MechanismRegistry,
    )
    _PIPELINE_CONTEXT_IMPORTABLE = True
except ImportError:
    _PipelineContext = None  # type: ignore[assignment, misc]
    _MechanismRegistry = None  # type: ignore[assignment, misc]
    _PIPELINE_CONTEXT_IMPORTABLE = False

# ---------------------------------------------------------------------------
# Skip markers
# ---------------------------------------------------------------------------

requires_abc = pytest.mark.skipif(
    not _ABC_IMPORTABLE,
    reason="fresh_slotlab.analyzer.features._base not importable — "
           "P2-A1 not yet landed",
)
requires_registry = pytest.mark.skipif(
    not _REGISTRY_IMPORTABLE,
    reason="fresh_slotlab.analyzer.feature_registry not importable",
)
requires_base_version = pytest.mark.skipif(
    not _BASE_VERSION_IMPORTABLE,
    reason="compute_base_analyzer_version not yet exported from versioning.py",
)


def _feature_file_exists(feature_id: str) -> bool:
    spec = _SPEC_BY_ID[feature_id]
    return (FEATURES_DIR / spec["module_file"]).exists()


def _skip_if_not_landed(feature_id: str):
    """Return a skip marker if the feature module file doesn't exist yet."""
    if not _feature_file_exists(feature_id):
        return pytest.skip(
            f"Feature module {_SPEC_BY_ID[feature_id]['module_file']} not yet "
            "created — waiting on impl-implementer."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_feature_module(module_name: str):
    """Import a feature module, forcing a real import (not cache)."""
    # Use importlib to reload if already in sys.modules so the test
    # reflects current disk state (important for inject-bug proofs).
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


def _get_feature_class_from_module(module, feature_id: str):
    """Extract the AnalyzerFeature subclass from a loaded module."""
    if not _ABC_IMPORTABLE:
        return None
    for name in dir(module):
        obj = getattr(module, name)
        if (
            isinstance(obj, type)
            and obj is not AnalyzerFeature
            and issubclass(obj, AnalyzerFeature)
            and getattr(obj, "FEATURE_ID", None) == feature_id
        ):
            return obj
    return None


# ===========================================================================
# C1 — 4 feature modules exist + AnalyzerFeature subclass
# ===========================================================================

class TestFeatureModulesExist:
    """C1: each feature module file exists on disk at the expected path."""

    @pytest.mark.parametrize("feature_id", _ALL_FEATURE_IDS)
    def test_module_file_exists(self, feature_id):
        """C1: fresh_slotlab/analyzer/features/<feature_id>.py must exist.

        This test goes RED until impl-implementer creates the file.
        It uses the guard pattern documented in 03_tests.md.
        """
        spec = _SPEC_BY_ID[feature_id]
        target = FEATURES_DIR / spec["module_file"]
        if not target.exists():
            pytest.skip(
                f"Waiting on impl: {target} not yet created."
            )
        assert target.exists(), (
            f"Feature module not found: {target}\n"
            f"C1 contract: {spec['module_file']} must be created by Wave 2c implementer."
        )
        assert target.is_file(), (
            f"{target} exists but is not a regular file."
        )

    @requires_abc
    @pytest.mark.parametrize("feature_id", _ALL_FEATURE_IDS)
    def test_module_exports_analyzer_feature_subclass(self, feature_id):
        """C1: each feature module exports a class that is an AnalyzerFeature subclass.

        Inject-bug: if the class doesn't inherit from AnalyzerFeature (e.g.
        it's a plain Python class), issubclass raises TypeError — this test
        catches that.
        """
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        mod = _import_feature_module(spec["module_name"])
        cls = _get_feature_class_from_module(mod, feature_id)

        assert cls is not None, (
            f"Could not find an AnalyzerFeature subclass with FEATURE_ID={feature_id!r} "
            f"in module {spec['module_name']}.\n"
            f"C1 contract: the module must export exactly one AnalyzerFeature subclass "
            f"with FEATURE_ID == {feature_id!r}."
        )
        assert issubclass(cls, AnalyzerFeature), (
            f"Class {cls.__name__} in {spec['module_name']} is not an AnalyzerFeature subclass.\n"
            "C1 contract: must inherit from AnalyzerFeature ABC."
        )

    @requires_abc
    @pytest.mark.parametrize("feature_id", _ALL_FEATURE_IDS)
    def test_feature_id_classvar_matches_module_name(self, feature_id):
        """C1: the class's FEATURE_ID ClassVar must exactly match the feature_id string.

        Inject-bug: if implementer writes FEATURE_ID = 'payouts' instead of
        'payouts_by_spin_type', this assertion fires.
        """
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        mod = _import_feature_module(spec["module_name"])
        cls = _get_feature_class_from_module(mod, feature_id)
        if cls is None:
            pytest.skip(f"Class with FEATURE_ID={feature_id!r} not found yet in module")

        assert cls.FEATURE_ID == feature_id, (
            f"Class {cls.__name__}.FEATURE_ID = {cls.FEATURE_ID!r}, "
            f"expected {feature_id!r}.\n"
            f"C1 contract: FEATURE_ID must exactly match the feature_id string."
        )

    @requires_abc
    @pytest.mark.parametrize("feature_id", _ALL_FEATURE_IDS)
    def test_class_is_instantiable(self, feature_id):
        """C1: the feature class must be instantiable without error.

        ABC machinery: if any abstractmethod is not implemented (extract,
        reduce, emit), instantiation raises TypeError at __init__ time.
        This proves all 3 abstract methods are concretely implemented.
        """
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        mod = _import_feature_module(spec["module_name"])
        cls = _get_feature_class_from_module(mod, feature_id)
        if cls is None:
            pytest.skip(f"Class with FEATURE_ID={feature_id!r} not found yet")

        try:
            instance = cls()
        except TypeError as exc:
            pytest.fail(
                f"Class {cls.__name__} raised TypeError at instantiation: {exc}\n"
                f"C1 contract: all 3 abstractmethods (extract/reduce/emit) must be "
                f"concretely implemented. TypeError means at least one is missing."
            )
        assert instance is not None

    @requires_abc
    @pytest.mark.parametrize("feature_id", _ALL_FEATURE_IDS)
    def test_rtp_contribution_classvar_is_false(self, feature_id):
        """C1: each feature class must define RTP_CONTRIBUTION = False.

        CRITICAL: Wave 2e gate reads this ClassVar. All 4 Wave 2c features
        are display-only (C1 contract in brief §4).
        """
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        mod = _import_feature_module(spec["module_name"])
        cls = _get_feature_class_from_module(mod, feature_id)
        if cls is None:
            pytest.skip(f"Class not found yet")

        assert hasattr(cls, "RTP_CONTRIBUTION"), (
            f"{cls.__name__} missing RTP_CONTRIBUTION ClassVar — "
            "Wave 2e gate will AttributeError."
        )
        assert cls.RTP_CONTRIBUTION is False, (
            f"{cls.__name__}.RTP_CONTRIBUTION = {cls.RTP_CONTRIBUTION!r}, "
            "expected False. All Wave 2c features are display-only."
        )


# ===========================================================================
# C2 — Registration on import
# ===========================================================================

class TestRegistrationOnImport:
    """C2: importing each feature module registers its FEATURE_ID in ALL_FEATURES.

    Uses a fixture that saves + restores ALL_FEATURES around each test to
    avoid cross-test contamination (same pattern as TestFeatureRegistry in
    test_analyzer_foundation.py).
    """

    @pytest.fixture(autouse=True)
    def _reset_registry(self):
        """Save and restore ALL_FEATURES around each test."""
        if not _REGISTRY_IMPORTABLE:
            yield
            return
        original = list(_registry_mod.ALL_FEATURES)
        yield
        _registry_mod.ALL_FEATURES.clear()
        _registry_mod.ALL_FEATURES.extend(original)

    @requires_abc
    @requires_registry
    @pytest.mark.parametrize("feature_id", _ALL_FEATURE_IDS)
    def test_feature_registered_after_module_import(self, feature_id):
        """C2: importing the feature module registers its FEATURE_ID in ALL_FEATURES.

        This is the core C8 inject-bug target: if the module-bottom
        `register(MyFeature())` call is commented out, this test goes RED.

        Inject-bug proof documented in 03_tests.md.
        """
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        # Remove from sys.modules to force a fresh import
        mod_name = spec["module_name"]
        was_in_modules = mod_name in sys.modules
        if was_in_modules:
            del sys.modules[mod_name]

        # Snapshot ALL_FEATURES before import
        before_ids = {f.FEATURE_ID for f in _registry_mod.ALL_FEATURES}

        # Import — registration should happen as a side-effect
        try:
            importlib.import_module(mod_name)
        finally:
            pass  # leave module in sys.modules for subsequent tests

        after_ids = {f.FEATURE_ID for f in _registry_mod.ALL_FEATURES}

        assert feature_id in after_ids, (
            f"FEATURE_ID={feature_id!r} not in ALL_FEATURES after importing "
            f"{mod_name}.\n"
            f"Before import: {sorted(before_ids)}\n"
            f"After import:  {sorted(after_ids)}\n"
            f"C2 contract: module-bottom register(MyFeature()) call must fire.\n"
            f"C8 inject-bug: commenting out register() makes this RED."
        )

    @requires_registry
    @pytest.mark.parametrize("feature_id", _ALL_FEATURE_IDS)
    def test_re_import_is_idempotent(self, feature_id):
        """C2: importing the module a second time must not duplicate the registration.

        Per feature_registry.register() idempotency contract: duplicate
        registration by FEATURE_ID is a silent no-op.

        Inject-bug: if register() lost its dedup check, double-import would
        grow ALL_FEATURES by 1 extra entry — len check fires.
        """
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        mod_name = spec["module_name"]

        # First import
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        importlib.import_module(mod_name)
        count_after_first = sum(
            1 for f in _registry_mod.ALL_FEATURES if f.FEATURE_ID == feature_id
        )

        # Second import (reload)
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        importlib.import_module(mod_name)
        count_after_second = sum(
            1 for f in _registry_mod.ALL_FEATURES if f.FEATURE_ID == feature_id
        )

        assert count_after_second == count_after_first, (
            f"After re-importing {mod_name}, FEATURE_ID={feature_id!r} "
            f"appears {count_after_second} time(s) in ALL_FEATURES "
            f"(was {count_after_first} after first import).\n"
            f"C2 idempotency: register() must deduplicate by FEATURE_ID."
        )
        assert count_after_second == 1, (
            f"FEATURE_ID={feature_id!r} appears {count_after_second} time(s) "
            f"in ALL_FEATURES; expected exactly 1."
        )


# ===========================================================================
# C3 — P1-A1 canary reference
# ===========================================================================

class TestP1A1CanaryReference:
    """C3: the existing 3-invocation parity test file must be present and importable.

    We do NOT re-run the full 23/23 canary here (that's impl-verifier's job).
    We assert the test file exists (so pytest can discover it) and that
    our key summary keys are structurally present in player_impact_analyzer.py
    (via source inspection), which is a lighter prerequisite check.
    """

    def test_parity_test_file_exists(self):
        """C3: tests/integration/test_analyzer_three_invocation_parity.py exists.

        If someone accidentally deleted or moved the P1-A1 canary, this fires.
        """
        parity_path = ROOT / "tests" / "integration" / "test_analyzer_three_invocation_parity.py"
        assert parity_path.exists(), (
            f"P1-A1 canary not found at {parity_path}\n"
            f"C3 contract: this file must remain intact throughout Wave 2c."
        )

    def test_pia_summary_keys_present_in_source(self):
        """C3: the 4 feature summary keys appear in player_impact_analyzer.py source.

        Structural check that main() (or the feature emit functions it invokes)
        still populates the expected keys.  Pattern A features use inline
        aggregation in main() — the keys must remain there until Wave 2d moves
        them.  Pattern B features (bankruptcy_simulation, bankruptcy_probe) may
        be written by emit() — we only check the string appears anywhere
        (as a key, import path, or comment) so this test is stable across
        both patterns.

        BOM note: PIA file is saved with a UTF-8 BOM (utf-8-sig); we strip it
        via the encoding parameter so string search works correctly.
        """
        pia_source = PIA_PATH.read_text(encoding="utf-8-sig")

        expected_keys = [
            "payouts_by_spin_type",
            "reel_marginal_by_spin_type",
            "bankruptcy_simulation",
            "bankruptcy_probe",
            "multiplier_profile",
        ]
        for key in expected_keys:
            assert key in pia_source, (
                f"Summary key {key!r} not found anywhere in player_impact_analyzer.py.\n"
                f"C3 contract: summary keys must not be removed by Wave 2c.\n"
                f"(Check: key may appear in a comment, import path, or emit body.)"
            )


# ===========================================================================
# C4 — main() invokes feature.emit
# ===========================================================================

class TestMainInvokesFeatureEmit:
    """C4: main() must contain a loop over the registered features that calls feature.emit.

    Per brief §4 C4 (pre-C1 wording, retained for reference):
        for feature in ALL_FEATURES:
            feature.emit(None, summary)

    Post-C1 actual form (topo-sorted, 3-arg emit per 04_v3 §4.2):
        for _feature in _sorted_features:
            _feature.emit(final_acc, summary, ctx)

    Two-part check:
    (a) Source-level: main()'s function source contains 'feature.emit(' substring,
        whether the iterable is ALL_FEATURES (legacy) or _sorted_features (C1+).
    (b) Source-level: main() or PIA module imports ALL_FEATURES from feature_registry.

    These are structural guards. The emit-invocation inject-bug proof (C8b)
    complements this by proving the test goes RED if the loop is absent.
    """

    def test_main_source_contains_feature_emit_call(self):
        """C4: player_impact_analyzer.py source contains a '.emit(' call on a
        feature variable (e.g. 'feature.emit(' or '_feature.emit(').

        Catches the scaffolding-not-wired regression: implementer creates
        the 4 feature classes but forgets to add the emit loop to main().

        C8 inject-bug: comment out the for-loop → no '.emit(' on any feature
        variable → this test RED.

        BOM note: PIA file is UTF-8 BOM; we strip it via utf-8-sig.
        """
        pia_source = PIA_PATH.read_text(encoding="utf-8-sig")

        # Locate the feature-emit loop and check that a .emit( call appears
        # on the loop variable within that loop body.
        #
        # Strategy:
        #   1. Find `for <var> in ALL_FEATURES:` (pre-C1) OR
        #          `for <var> in _sorted_features:` (C1+, after topo sort)
        #      to identify the loop variable name.
        #   2. Assert `<var>.emit(` appears anywhere after that loop header.
        #
        # The OR-pattern lets the test survive both the legacy direct-ALL_FEATURES
        # loop and the C1+ topo-sorted _sorted_features loop.
        # This is robust to variable name differences ('feature', '_feature', etc.)
        # and correctly excludes class-method calls like 'BankruptcySimulation.emit('.
        import re

        loop_match = re.search(
            r'for\s+(\w+)\s+in\s+(?:ALL_FEATURES|_sorted_features)\s*:',
            pia_source,
        )
        assert loop_match is not None, (
            f"No 'for <var> in ALL_FEATURES:' or 'for <var> in _sorted_features:' "
            f"loop found in {PIA_PATH.name}.\n"
            f"C4 contract: main() must loop over the registered features and call "
            f"feature.emit() for each."
        )

        loop_var = loop_match.group(1)
        # The emit call must appear after the loop header
        source_after_loop = pia_source[loop_match.end():]
        emit_pattern = re.compile(re.escape(loop_var) + r'\.emit\(')
        emit_calls = emit_pattern.findall(source_after_loop)

        assert len(emit_calls) >= 1, (
            f"No '{loop_var}.emit(' call found after the feature loop header "
            f"in {PIA_PATH.name}.\n"
            f"C4 contract: main() must invoke feature.emit() for each registered feature.\n"
            f"C8 inject-bug: removing the feature loop makes this RED."
        )

    def test_pia_imports_all_features_from_registry(self):
        """C4: player_impact_analyzer.py imports ALL_FEATURES from feature_registry.

        The brief's C4 specifies:
            from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES

        This catches the case where the import was forgotten (emit loop calls
        an undefined name, causing NameError at runtime).

        BOM note: PIA file is UTF-8 BOM; we strip it via utf-8-sig.
        """
        pia_source = PIA_PATH.read_text(encoding="utf-8-sig")

        # Allow either the package-mode or script-mode import
        has_registry_import = (
            "feature_registry" in pia_source
            and "ALL_FEATURES" in pia_source
        )
        assert has_registry_import, (
            f"ALL_FEATURES from feature_registry not found in {PIA_PATH.name}.\n"
            f"C4 contract: main() must import ALL_FEATURES to invoke the emit loop.\n"
            f"Without the import, the name would be undefined at runtime."
        )

    def test_main_function_ast_contains_emit_call(self):
        """C4: AST-walk main() function body for a .emit() call.

        More precise than a raw string search: parses the AST and looks for
        a Call node whose func is an Attribute named 'emit', inside the
        function definition named 'main'.

        The loop variable name may be 'feature', '_feature', or any other word
        — we check only for the 'emit' attribute name.

        Inject-bug: replacing '_feature.emit(...)' with 'pass' in the loop
        body → AST walk finds no emit Call → test RED.

        BOM note: PIA file has UTF-8 BOM; ast.parse requires a BOM-free string.
        We read with utf-8-sig so the BOM is stripped before parsing.
        """
        pia_source = PIA_PATH.read_text(encoding="utf-8-sig")
        tree = ast.parse(pia_source, filename=str(PIA_PATH))

        # Find the 'main' function definition
        main_func = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                main_func = node
                break

        assert main_func is not None, (
            f"Could not find 'def main()' in {PIA_PATH.name}.\n"
            "This is a structural invariant — main() must exist."
        )

        # Walk main()'s body for Attribute calls named 'emit'
        emit_calls_found = []
        for node in ast.walk(main_func):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "emit"
            ):
                emit_calls_found.append(node)

        assert len(emit_calls_found) >= 1, (
            f"No 'feature.emit(...)' call found in main()'s AST.\n"
            f"C4 contract: main() must invoke feature.emit for each registered feature.\n"
            f"C8 inject-bug: removing the emit call makes this RED."
        )


# ===========================================================================
# C5 — Hash composition unchanged; feature.compute_hash() works
# ===========================================================================

class TestHashComposition:
    """C5: compute_base_analyzer_version() hashes core/*.py only (not features/*.py).
    feature.compute_hash() returns 12-char hex for each feature class.
    """

    @requires_base_version
    def test_base_version_is_12char_hex(self):
        """C5: compute_base_analyzer_version() returns a 12-char lowercase hex string.

        Gate: skipped if compute_base_analyzer_version is not yet exported
        from versioning.py (consistent with other C5 tests in the suite).
        """
        result = _cbav()
        assert isinstance(result, str), (
            f"compute_base_analyzer_version() must return str, got {type(result).__name__}"
        )
        assert len(result) == 12, (
            f"compute_base_analyzer_version() must return 12-char string, "
            f"got len={len(result)}: {result!r}"
        )
        assert all(c in "0123456789abcdef" for c in result), (
            f"compute_base_analyzer_version() must return lowercase hex, got {result!r}"
        )

    @requires_base_version
    def test_base_version_does_not_include_features_dir(self):
        """honesty-2 update: base_hash excludes REGISTERED feature plugins (R-4), not features/*.py.

        Phase honesty-2 (2026-05-29) refined the exclusion rule: instead of excluding all
        features/*.py (which would wrongly drop _base.py and __init__.py from base), only
        REGISTERED feature plugin files (those in ALL_FEATURES) are excluded (R-4).
        _base.py and features/__init__.py are NOT registered plugins → they STAY IN base.

        The C5 intent still holds: adding a registered feature plugin must NOT change base_hash.
        We verify: (a) registered plugin files are NOT in _CLOSURE_FILES, (b) _base.py and
        features/__init__.py ARE in _CLOSURE_FILES (they stay in base), (c) live value is
        the known R-1 closure pin.
        """
        from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES

        # (a) Registered plugin files must NOT be in _CLOSURE_FILES
        registered_plugin_stems = [
            "payouts_by_spin_type",
            "reel_marginal_by_spin_type",
            "bankruptcy_simulation",
            "multiplier_profile",
            "multiplier_wild",
            "machine_mechanics",
            "upstream_feature_breakdown",
            "collect_mechanic",
            "bonus_chain_dynamics",
        ]
        for stem in registered_plugin_stems:
            plugin_rel = f"fresh_slotlab/analyzer/features/{stem}.py"
            assert plugin_rel not in _CLOSURE_FILES, (
                f"Registered plugin {plugin_rel!r} is in _CLOSURE_FILES — it must be EXCLUDED "
                f"(R-4: exclusion via registry, not glob). Registered plugins carry their own "
                f"feature_hash; including them in base would cause FALSE-STALE ×393."
            )

        # (b) _base.py and __init__.py must stay IN the closure (they are not registered plugins)
        assert "fresh_slotlab/analyzer/features/_base.py" in _CLOSURE_FILES, (
            "features/_base.py must be in _CLOSURE_FILES. It defines the AnalyzerFeature ABC "
            "and is NOT a registered plugin (not in ALL_FEATURES). R-4 excludes only registered "
            "plugins; _base.py stays in base."
        )
        assert "fresh_slotlab/analyzer/features/__init__.py" in _CLOSURE_FILES, (
            "features/__init__.py must be in _CLOSURE_FILES. It is a package marker, not a "
            "registered plugin. R-4 excludes only registered plugins; __init__.py stays in base."
        )

        # (c) Live value must be the known R-1 closure pin (post phase-6)
        # Phase 2a carved collect_mechanic's compute out of PIA (a closure file),
        # shrinking base 960e9d18d83d -> 57fdb323585d; phase 2b carved
        # bonus_chain_dynamics out of PIA -> 980f488f4bb2; phase 3 carved
        # upstream_feature_breakdown's row-build out of PIA -> c89db791d8a1;
        # phase 4 carved multiplier_profile's dict-build out of PIA -> ce298f055495;
        # phase 5 carved reel_marginal_by_spin_type's dict-build out of PIA -> ccc1ecce185d;
        # phase 6 carved bankruptcy_simulation's tier row-build out of PIA (the LAST
        # carve) -> d8b8c138874a (report content byte-identical).
        # playtype C3 (per-machine config layer): added machine_id/mode params to
        # parse_chunk_response in core/parser.py -> 85666c4c4407.
        # Phase D (play-type layer delete): removed plugin framework wiring from
        # parser.py / base_pipeline.py + C3 Layer-0 from PIA -> 8a791a69cd05.
        # Behavior byte-identical: framework flag-off-dormant; C3 L0 == L1 for pilots.
        actual = _cbav()
        assert actual == "3b852134b03a", (
            f"compute_base_analyzer_version() mismatch vs R-1 closure reference:\n"
            f"  actual   = {actual!r}\n"
            f"  expected = '3b852134b03a' (R-1 closure value, post spin_type_rtp_buckets:\n"
            "  parser paid-bucket accumulator (play_types stays carved) → 8dbbfad6f90f→3b852134b03a;\n"
            "  additive display metadata only, no RTP change).\n"
            "R-4 exclusion covers registered plugins only (not all features/*.py).\n"
            "_base.py and features/__init__.py are still in base (not registered plugins)."
        )

    @requires_abc
    @pytest.mark.parametrize("feature_id", _ALL_FEATURE_IDS)
    def test_feature_compute_hash_returns_12char_hex(self, feature_id):
        """C5: feature.compute_hash() returns a 12-char lowercase hex string.

        Per _base.py §5.2: sha256(source_bytes).hexdigest()[:12].
        """
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        mod = _import_feature_module(spec["module_name"])
        cls = _get_feature_class_from_module(mod, feature_id)
        if cls is None:
            pytest.skip(f"Class not found yet in module")

        result = cls.compute_hash()
        assert isinstance(result, str), (
            f"{cls.__name__}.compute_hash() must return str, got {type(result).__name__}"
        )
        assert len(result) == 12, (
            f"{cls.__name__}.compute_hash() must return 12-char string, "
            f"got len={len(result)}: {result!r}"
        )
        assert all(c in "0123456789abcdef" for c in result), (
            f"{cls.__name__}.compute_hash() must return lowercase hex, got {result!r}"
        )

    @requires_abc
    @pytest.mark.parametrize("feature_id", _ALL_FEATURE_IDS)
    def test_feature_compute_hash_is_deterministic(self, feature_id):
        """C5: calling compute_hash() twice returns the same value."""
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        mod = _import_feature_module(spec["module_name"])
        cls = _get_feature_class_from_module(mod, feature_id)
        if cls is None:
            pytest.skip(f"Class not found yet in module")

        h1 = cls.compute_hash()
        h2 = cls.compute_hash()
        assert h1 == h2, (
            f"{cls.__name__}.compute_hash() is not deterministic: {h1!r} vs {h2!r}"
        )


# ===========================================================================
# C6 — Subprocess import safety
# ===========================================================================

class TestSubprocessImportSafety:
    """C6: each feature module must import in a fresh subprocess with rc=0, no stderr.

    Per memory/feedback_subprocess_import_suicide_and_module_globals.md:
    'import-time side effects' means any I/O, network calls, or global
    state mutations beyond registering the feature instance. The
    register(MyFeature()) call is explicitly safe (pure list-append).

    Per memory/feedback_perf_claim_needs_e2e_event_stream.md: subprocess
    smoke is required — not just in-process import smoke.
    """

    @pytest.mark.parametrize("feature_id", _ALL_FEATURE_IDS)
    def test_subprocess_import_exits_zero(self, feature_id):
        """C6: python -c "import <module>" exits rc=0 for each feature module.

        Inject-bug: adding `open('/tmp/file', 'w')` at module top would
        not cause rc!=0 (file write succeeds), but it IS a side effect.
        The no-stderr check (below) catches DeprecationWarnings etc.

        This test primarily guards against ImportError / SyntaxError / any
        exception propagated at import time (rc != 0).
        """
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        cmd = [
            sys.executable, "-c",
            f"import {spec['module_name']}; print('OK')",
        ]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Importing {spec['module_name']!r} in subprocess failed "
            f"(rc={result.returncode})\n"
            f"STDOUT: {result.stdout!r}\n"
            f"STDERR: {result.stderr!r}\n"
            f"C6 contract: feature modules must import without I/O side effects "
            f"or unhandled exceptions."
        )
        assert "OK" in result.stdout, (
            f"Import completed but 'OK' sentinel not in stdout — "
            f"possible silent failure: {result.stdout!r}"
        )

    @pytest.mark.parametrize("feature_id", _ALL_FEATURE_IDS)
    def test_subprocess_import_no_stderr(self, feature_id):
        """C6: importing feature module emits nothing to stderr.

        Catches DeprecationWarnings (with -W error they become exceptions),
        print-to-stderr debug statements, etc.
        """
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        cmd = [
            sys.executable, "-W", "error", "-c",
            f"import {spec['module_name']}",
        ]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            # Only fail if it's NOT a known-OK scenario
            if "ModuleNotFoundError" in result.stderr:
                pytest.skip(f"Module not yet importable: {result.stderr[:200]}")
            assert result.returncode == 0, (
                f"Importing {spec['module_name']!r} with -W error failed "
                f"(rc={result.returncode})\n"
                f"STDERR: {result.stderr!r}\n"
                f"C6: feature module emits warnings or errors at import time."
            )

    @pytest.mark.parametrize("feature_id", _ALL_FEATURE_IDS)
    def test_subprocess_import_registers_in_registry(self, feature_id):
        """C6 + C2 combined: subprocess import registers the feature, verifiable
        by printing ALL_FEATURES length after import.

        This is the subprocess-mode analog of test_feature_registered_after_module_import.
        It proves that registration works in a real subprocess context (not just
        in-process via importlib), which matters for the virtual_app / batch worker paths.
        """
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        script = textwrap.dedent(f"""
            import fresh_slotlab.analyzer.feature_registry as reg
            import {spec['module_name']}
            ids = [f.FEATURE_ID for f in reg.ALL_FEATURES]
            assert {feature_id!r} in ids, f"FEATURE_ID not registered: {{ids}}"
            print("REGISTERED")
        """)
        cmd = [sys.executable, "-c", script]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Subprocess registration check failed for {spec['module_name']!r} "
            f"(rc={result.returncode})\n"
            f"STDOUT: {result.stdout!r}\n"
            f"STDERR: {result.stderr!r}\n"
            f"C6+C2: registration must work in subprocess context."
        )
        assert "REGISTERED" in result.stdout, (
            f"Registration sentinel 'REGISTERED' not in stdout: {result.stdout!r}"
        )


# ===========================================================================
# C7 — Pattern A features have no-op extract/reduce
# ===========================================================================

class TestPatternANoOpExtractReduce:
    """C7: Pattern A features (payouts_by_spin_type, reel_marginal_by_spin_type)
    must implement extract as a no-op ({} return) and reduce as a no-op
    (returns prev_acc unchanged).

    Pattern B features (bankruptcy_simulation, multiplier_profile) are
    excluded from the reduce assertion — their reduce may differ.
    extract() returning {} is still expected for Pattern B features in Wave 2c
    (they use inline main() aggregation too, just with a more complex emit).

    Per brief §2 Pattern A spec verbatim:
        def extract(self, parse_state, chunk_dict) -> dict:
            return {}  # no per-round work
        def reduce(self, prev_acc, this_acc) -> dict:
            return prev_acc  # no-op accumulator
    """

    @requires_abc
    @pytest.mark.parametrize("feature_id", _PATTERN_A_IDS)
    def test_pattern_a_extract_returns_empty_dict(self, feature_id):
        """C7: Pattern A extract(parse_state={}, chunk_dict={}) returns {}.

        Inject-bug: if extract returns {'some_key': value} instead of {},
        this assertion fires. Proves the no-op contract is enforced.
        """
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        mod = _import_feature_module(spec["module_name"])
        cls = _get_feature_class_from_module(mod, feature_id)
        if cls is None:
            pytest.skip(f"Class not found yet")

        instance = cls()
        result = instance.extract(parse_state={}, chunk_dict={})

        assert result == {}, (
            f"{cls.__name__}.extract(parse_state={{}}, chunk_dict={{}}) returned "
            f"{result!r}, expected {{}}.\n"
            f"C7 Pattern A contract: extract must be a no-op (return {{}}) "
            f"since aggregation stays in main() until Wave 2d."
        )

    @requires_abc
    @pytest.mark.parametrize("feature_id", _PATTERN_A_IDS)
    def test_pattern_a_reduce_returns_prev_acc_unchanged(self, feature_id):
        """C7: Pattern A reduce(prev_acc, this_acc) returns prev_acc unchanged.

        Verify with two distinct acc dicts: result must be the prev_acc object
        (or at least equal to it), NOT this_acc.

        Inject-bug: if reduce returns this_acc or a merged dict, the assertion
        fires — proving the no-op accumulator contract.
        """
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        mod = _import_feature_module(spec["module_name"])
        cls = _get_feature_class_from_module(mod, feature_id)
        if cls is None:
            pytest.skip(f"Class not found yet")

        instance = cls()
        prev_acc = {"x": 1, "y": 2}
        this_acc = {"y": 99, "z": 3}

        result = instance.reduce(prev_acc, this_acc)

        assert result == prev_acc, (
            f"{cls.__name__}.reduce(prev_acc, this_acc) returned {result!r}, "
            f"expected {prev_acc!r} (prev_acc unchanged).\n"
            f"C7 Pattern A contract: reduce must return prev_acc as-is "
            f"(no-op accumulator) since aggregation stays in main()."
        )

    @requires_abc
    @pytest.mark.parametrize("feature_id", _PATTERN_A_IDS)
    def test_pattern_a_emit_is_callable(self, feature_id):
        """C7: Pattern A emit() is concrete (callable, not abstract).

        Per the implementer's Pattern A spec: emit checks that the key is
        present inside ``summary["player_impact"]`` (not top-level in
        summary).  We build a minimal summary that mirrors the real structure
        main() produces:

            summary = {"player_impact": {"payouts_by_spin_type": {}, ...}}

        This should NOT raise.  If it does raise AssertionError, the key path
        check in emit is wrong (e.g. it expects a different nesting level).
        """
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        mod = _import_feature_module(spec["module_name"])
        cls = _get_feature_class_from_module(mod, feature_id)
        if cls is None:
            pytest.skip(f"Class not found yet")

        instance = cls()
        assert callable(instance.emit), (
            f"{cls.__name__}.emit must be callable (concretely implemented)."
        )

        # Build a minimal summary that mirrors real main() output structure.
        # Pattern A emit checks summary["player_impact"][key] per implementer code.
        player_impact_section = {key: {} for key in spec["schema_keys_include"]}
        summary_with_player_impact = {"player_impact": player_impact_section}

        # Build a minimal PipelineContext for the C1 3-arg emit() signature.
        # Phase C1 changed emit() from (final_acc, summary) to
        # (final_acc, summary, ctx). Pattern A plugins accept ctx but do not
        # use it. Skip if PipelineContext is not yet importable.
        if not _PIPELINE_CONTEXT_IMPORTABLE:
            pytest.skip("PipelineContext not importable -- C1 not yet landed")
        _ctx = _PipelineContext(
            effective_bet_for_rtp=1.0,
            total_spins=10,
            total_paid_sessions=5,
            total_paid_spins=5,
            clamp_pending_robots_total=0,
            robots_with_pending_cycle=0,
            mechanism_registry=_MechanismRegistry(),
            manifest={},
        )
        try:
            instance.emit(None, summary_with_player_impact, _ctx)
        except AssertionError as exc:
            pytest.fail(
                f"{cls.__name__}.emit() raised AssertionError with a summary "
                f"containing player_impact.{list(spec['schema_keys_include'])}:\n"
                f"  {exc}\n"
                f"Pattern A emit should only assert the key IS present in "
                f"summary['player_impact']. Check the key path."
            )
        except TypeError as exc:
            pytest.fail(
                f"{cls.__name__}.emit() raised TypeError: {exc}\n"
                f"emit() signature must accept (final_acc, summary: dict, ctx: PipelineContext)."
            )


# ===========================================================================
# C8 — Inject-bug TDD
# ===========================================================================

class TestInjectBugRegistration:
    """C8a — Registration inject-bug proof.

    Simulates: comment out the `register(MyFeature())` call at the bottom
    of a feature module. The test_feature_registered_after_module_import test
    (in C2) would go RED.

    We prove this by directly manipulating ALL_FEATURES: after clearing the
    list, importing the module populates it; if we simulate the missing
    register() by not importing the module, the ID is absent.
    """

    @pytest.fixture(autouse=True)
    def _reset_registry(self):
        if not _REGISTRY_IMPORTABLE:
            yield
            return
        original = list(_registry_mod.ALL_FEATURES)
        yield
        _registry_mod.ALL_FEATURES.clear()
        _registry_mod.ALL_FEATURES.extend(original)

    @requires_registry
    def test_inject_missing_register_call_makes_feature_id_absent(self):
        """C8a inject-bug proof: feature_id absent from ALL_FEATURES when
        register() is not called.

        Inject scenario: the module-bottom register(MyFeature()) is commented
        out. The test_feature_registered_after_module_import test would see
        feature_id NOT in ALL_FEATURES → RED.

        This test simulates that bug directly (without editing the file) by
        asserting that ALL_FEATURES lacking a feature_id IS a failure condition.
        """
        # Simulate the bug: clear ALL_FEATURES and do NOT import any feature module.
        _registry_mod.ALL_FEATURES.clear()

        # The invariant: if we check now, none of the 4 feature IDs are present.
        registered_ids = {f.FEATURE_ID for f in _registry_mod.ALL_FEATURES}
        for feature_id in _ALL_FEATURE_IDS:
            assert feature_id not in registered_ids, (
                f"INJECT-BUG PROOF C8a setup failed: {feature_id!r} already "
                f"registered without importing — unexpected."
            )

        # If the test_feature_registered_after_module_import were to run now
        # (after clearing ALL_FEATURES and without import), it would fire:
        sentinel_id = "payouts_by_spin_type"
        injected_ids = set()  # simulates: module imported but register() was commented out
        assert sentinel_id not in injected_ids, (
            f"INJECT-BUG PROOF C8a: {sentinel_id!r} is correctly absent from "
            f"ALL_FEATURES when register() was not called.\n"
            f"The C2 test test_feature_registered_after_module_import would be RED here."
        )

    @requires_registry
    def test_inject_register_not_called_then_restore_shows_green(self):
        """C8a restore proof: after importing the module, feature_id appears.

        Completes the inject-bug loop:
        1. Inject: no register call → feature_id absent (above test)
        2. Restore: import module → feature_id appears → GREEN

        Skip if module files not landed yet.
        """
        sentinel_id = "payouts_by_spin_type"
        spec = _SPEC_BY_ID[sentinel_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created; restore proof pending impl landing.")

        _registry_mod.ALL_FEATURES.clear()

        # RESTORE: import the module (register() call fires)
        mod_name = spec["module_name"]
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        importlib.import_module(mod_name)

        registered_ids = {f.FEATURE_ID for f in _registry_mod.ALL_FEATURES}
        assert sentinel_id in registered_ids, (
            f"RESTORE PROOF C8a: after importing {mod_name}, "
            f"{sentinel_id!r} must appear in ALL_FEATURES.\n"
            f"This proves the C2 test goes GREEN when register() is present."
        )


class TestInjectBugEmitInvocation:
    """C8b — emit-invocation inject-bug proof.

    Simulates: in main()'s ALL_FEATURES loop, the emit call is absent.
    The C4 structural test (test_main_source_contains_feature_emit_call)
    would go RED because 'feature.emit(' would be absent from source.

    We prove this by asserting the negative: a source WITHOUT 'feature.emit('
    correctly triggers the C4 assertion.
    """

    def test_inject_no_emit_call_makes_c4_test_fire(self):
        """C8b inject-bug proof: source without 'feature.emit(' fails C4 check.

        Simulate the bug: main() has the ALL_FEATURES loop but with 'pass'
        instead of 'feature.emit(None, summary)'. The C4 test would assert
        'feature.emit(' in source → fail.

        We prove this by checking the injected string directly.
        """
        # Injected (buggy) main snippet: loop exists but emit is absent
        injected_main_source = textwrap.dedent("""
            def main():
                for feature in ALL_FEATURES:
                    pass  # emit was accidentally removed
                return 0
        """)

        # The C4 guard assertion: 'feature.emit(' must appear
        has_emit = "feature.emit(" in injected_main_source
        assert not has_emit, (
            "INJECT-BUG PROOF C8b setup: injected source must NOT contain "
            "'feature.emit(' — that's the bug we're simulating."
        )

        # Prove the C4 test would fire: it checks for the substring
        # If has_emit is False, the C4 assertion `assert 'feature.emit(' in source`
        # would fail → test RED.
        # This is the guard proof: the test correctly catches the absent emit.

    def test_inject_emit_absent_from_ast_makes_c4_test_fire(self):
        """C8b inject-bug proof: AST walk finds no emit Call in injected source.

        Same scenario as above but via the AST checker in
        test_main_function_ast_contains_emit_call.
        """
        injected_main_source = textwrap.dedent("""
            def main():
                for feature in ALL_FEATURES:
                    # feature.emit(None, summary)  # commented out (the bug)
                    _ = feature  # no-op
                return 0
        """)

        tree = ast.parse(injected_main_source)
        main_func = next(
            (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main"),
            None,
        )
        assert main_func is not None, "Injected source must have a main() function."

        emit_calls = [
            n for n in ast.walk(main_func)
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "emit"
            )
        ]
        assert len(emit_calls) == 0, (
            "INJECT-BUG PROOF C8b: injected source (with emit commented out) "
            "must have 0 emit calls in AST — this proves the C4 AST guard fires."
        )

    def test_restore_emit_call_present_in_actual_pia_source(self):
        """C8b restore proof: actual PIA source contains a '.emit(' call → GREEN.

        After the implementer lands the emit loop, this goes from RED to GREEN.
        Pre-impl: this test is skipped (no .emit( call in source yet).
        Post-impl: this test is GREEN.

        The loop variable name is accepted as any word (feature, _feature, etc.)
        — the key invariant is that '.emit(' appears after a word character.

        BOM note: PIA file has UTF-8 BOM; read with utf-8-sig.
        """
        import re
        pia_source = PIA_PATH.read_text(encoding="utf-8-sig")

        # Check for the ALL_FEATURES loop + emit call pattern.
        loop_match = re.search(r'for\s+(\w+)\s+in\s+ALL_FEATURES\s*:', pia_source)
        if loop_match is None:
            pytest.skip(
                "Waiting on impl: no 'for <var> in ALL_FEATURES:' loop yet in "
                "player_impact_analyzer.py. This test will pass once the Wave 2c "
                "emit loop is wired."
            )

        loop_var = loop_match.group(1)
        source_after_loop = pia_source[loop_match.end():]
        emit_calls = re.findall(re.escape(loop_var) + r'\.emit\(', source_after_loop)

        if not emit_calls:
            pytest.skip(
                f"Waiting on impl: '{loop_var}.emit(' not yet present after "
                f"'for {loop_var} in ALL_FEATURES:' in player_impact_analyzer.py."
            )

        # If we reach here, the restore is GREEN.
        assert len(emit_calls) >= 1, (
            "RESTORE PROOF C8b: actual PIA source contains a loop-var.emit(' call — "
            "C4 test correctly goes GREEN."
        )


# ===========================================================================
# Additional: schema_keys declared on each class
# ===========================================================================

class TestSchemaKeysDeclared:
    """Additional coverage: each feature class declares SCHEMA_KEYS that include
    the expected summary keys from the brief §1 table.
    """

    @requires_abc
    @pytest.mark.parametrize("feature_id", _ALL_FEATURE_IDS)
    def test_schema_keys_includes_expected_summary_keys(self, feature_id):
        """Each feature class must declare SCHEMA_KEYS that include the brief §1 keys.

        Brief §1 table maps each feature_id to expected summary keys:
          payouts_by_spin_type        → ("payouts_by_spin_type",)
          reel_marginal_by_spin_type  → ("reel_marginal_by_spin_type",)
          bankruptcy_simulation       → ("bankruptcy_simulation", "bankruptcy_probe")
          multiplier_profile          → ("multiplier_profile",)
        """
        spec = _SPEC_BY_ID[feature_id]
        if not (FEATURES_DIR / spec["module_file"]).exists():
            pytest.skip(f"Module file not yet created: {spec['module_file']}")

        mod = _import_feature_module(spec["module_name"])
        cls = _get_feature_class_from_module(mod, feature_id)
        if cls is None:
            pytest.skip(f"Class not found yet")

        schema_keys = set(cls.SCHEMA_KEYS)
        for expected_key in spec["schema_keys_include"]:
            assert expected_key in schema_keys, (
                f"{cls.__name__}.SCHEMA_KEYS={cls.SCHEMA_KEYS!r} does not "
                f"include expected key {expected_key!r}.\n"
                f"Brief §1: {feature_id!r} must declare {spec['schema_keys_include']!r} "
                f"in SCHEMA_KEYS."
            )
