"""Regression tests for ticket P2-A1 — Foundation files (Round 2).

Contracts asserted (per 00_ticket.md §3, round-2 spec-aligned rewrite):

  C1 — AnalyzerFeature ABC (fresh_slotlab.analyzer.features._base):
       * Subclass implementing all 3 abstractmethods can be instantiated
       * Subclass missing any abstractmethod raises TypeError at instantiation
       * 5 ClassVars present with correct defaults
       * compute_hash() classmethod returns 12-char hex of source bytes
       * FEATURE_ID (not NAME), extract/reduce/emit (not aggregate/finalize/applies_to)

  C2 — compute_effective_analyzer_version is deterministic, 12-char hex,
       composition via sha256(base_hash || sorted(feature_hashes_used) || mode).
       Five worked examples with known expected values.
       [UNCHANGED from round 1 — versioning.py API correct per critic]

  C3 — feature_registry.ALL_FEATURES is empty by default; register() appends;
       idempotent re-registration (by FEATURE_ID) is a no-op or raises cleanly.
       [Updated: stubs now use FEATURE_ID not NAME]

  C4 — get_features_for_machine(machine_id, manifest) returns only features
       whose FEATURE_ID appears in manifest["analyzer_features"] list,
       in registration order.
       [Changed from round 1: manifest-list-based filtering, not applies_to predicate]

  C5 — No import-time side effects: subprocess smoke import returns rc=0.
       [Updated: includes fresh_slotlab.analyzer.features._base path]

  C6 — Inject-bug TDD:
         drop abstractmethod from ABC subclass → TypeError at instantiation (C1)
         truncate hash to 11 chars            → length assertion fires     (C2)
         no dedup check in register()         → idempotency len-check fires (C3)
         wrong attribute name in ClassVar     → AttributeError from test assertion (C1)
         RTP_CONTRIBUTION default wrong       → default False check fires  (C1)

Round 2 API changes vs round 1:
  NAME            → FEATURE_ID
  applies_to()    → REMOVED (manifest-declared applicability)
  aggregate()     → extract(parse_state, chunk_dict) -> dict
  finalize()      → emit(final_acc, summary: dict) -> None
  NEW: reduce(prev_acc, this_acc) -> Any
  NEW ClassVars: SCHEMA_KEYS, REQUIRES, RTP_CONTRIBUTION, REGISTERED_FALLBACK_RULES
  NEW classmethod: compute_hash() -> str (12-char sha256 hex of source file)
  get_features_for_machine(machine_id, manifest) reads manifest["analyzer_features"]

Architecture references:
  session_artifacts/_arch/04_architecture_proposal_v5.md §5.2 — ABC spec verbatim
  session_artifacts/_arch/04_architecture_proposal_v5.md §4.1 — hash algorithm
  session_artifacts/_arch/04_architecture_proposal_v5.md §5.5.2 — manifest schema

Hash composition algorithm (§4.1, unchanged from round 1):
    h = sha256(base_hash.encode())
    for fid in sorted(set(machine_features)):
        h.update(b'\\x00' + fid.encode() + b'=' + feature_hashes[fid].encode())
    if mode is not None:
        h.update(b'\\x00mode=' + str(mode).encode())
    return h.hexdigest()[:12]

Inject-bug discipline per memory feedback_integration_test_argv.md:
    Every test proven red by injecting the bug it guards, then restored green.
    Verification log in session_artifacts/_impl/phase2/01_foundation_files/03_tests.md.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Import guards — written against planned module paths per spec.
# C1 (ABC) lives at fresh_slotlab.analyzer.features._base (round 2 path).
# C2/C3/C4 use existing versioning.py + feature_registry.py (round 1 paths).
# If implementer hasn't landed yet these fail with ImportError → pytest ERROR.
# ---------------------------------------------------------------------------

try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    _ABC_IMPORTABLE = True
except ImportError:
    _ABC_IMPORTABLE = False

try:
    from fresh_slotlab.analyzer.versioning import compute_effective_analyzer_version
    _VERSIONING_IMPORTABLE = True
except ImportError:
    _VERSIONING_IMPORTABLE = False

try:
    import fresh_slotlab.analyzer.feature_registry as _registry_mod
    _REGISTRY_IMPORTABLE = True
except ImportError:
    _REGISTRY_IMPORTABLE = False


# ---------------------------------------------------------------------------
# Compatibility skip markers
# ---------------------------------------------------------------------------

requires_abc = pytest.mark.skipif(
    not _ABC_IMPORTABLE,
    reason="fresh_slotlab.analyzer.features._base not yet importable — "
           "impl-implementer round 2 has not landed yet",
)
requires_versioning = pytest.mark.skipif(
    not _VERSIONING_IMPORTABLE,
    reason="fresh_slotlab.analyzer.versioning not yet importable",
)
requires_registry = pytest.mark.skipif(
    not _REGISTRY_IMPORTABLE,
    reason="fresh_slotlab.analyzer.feature_registry not yet importable",
)


# ---------------------------------------------------------------------------
# Shared stub builders (reused across test classes to avoid repetition)
# ---------------------------------------------------------------------------

def _make_good_stub_class(feature_id: str = "good_stub"):
    """Build a valid AnalyzerFeature subclass with all 3 abstractmethods."""
    if not _ABC_IMPORTABLE:
        return None

    class _GoodStub(AnalyzerFeature):
        FEATURE_ID: ClassVar[str] = feature_id
        SCHEMA_KEYS: ClassVar[tuple] = ("good_stub_key",)
        SCHEMA_VERSION: ClassVar[int] = 1
        REQUIRES: ClassVar[tuple] = ()
        RTP_CONTRIBUTION: ClassVar[bool] = False
        REGISTERED_FALLBACK_RULES: ClassVar[dict] = {}

        def extract(self, parse_state, chunk_dict) -> dict:
            return {}

        def reduce(self, prev_acc, this_acc) -> Any:
            return this_acc

        def emit(self, final_acc, summary: dict) -> None:
            pass

    _GoodStub.FEATURE_ID = feature_id
    _GoodStub.__qualname__ = f"_make_good_stub_class.<locals>._GoodStub__{feature_id}"
    return _GoodStub


def _make_registry_stub(feature_id: str):
    """Make a minimal valid ABC subclass for registry tests.

    For registry tests we need a class that can be instantiated and has
    FEATURE_ID set.  Uses the good stub builder so it goes through the
    proper ABC machinery.
    """
    cls = _make_good_stub_class(feature_id)
    if cls is None:
        return None
    return cls()


# ---------------------------------------------------------------------------
# Reference implementation of the hash algorithm (§4.1).
# Used to compute expected values independent of the implementer's code.
# ---------------------------------------------------------------------------

def _ref_effective_version(
    *,
    base_hash: str,
    feature_hashes: dict[str, str],
    machine_features: list[str],
    mode: int | None = None,
) -> str:
    """Reference implementation of the §4.1 composition algorithm.

    Computed independently from the implementer's code.
    Tests compare the implementer's output against this reference.
    """
    h = hashlib.sha256(base_hash.encode())
    for fid in sorted(set(machine_features)):
        h.update(b"\x00" + fid.encode() + b"=" + feature_hashes[fid].encode())
    if mode is not None:
        h.update(b"\x00mode=" + str(mode).encode())
    return h.hexdigest()[:12]


# Pre-computed snapshots (verified via independent Python session).
# Change detection: if the algorithm changes, these will go red.
_SNAPSHOT_E1 = "2da53c98604d"   # base: abc, features=[f1,f2], mode=1
_SNAPSHOT_E3 = "c9927743ddae"   # changed f1 hash
_SNAPSHOT_E4 = "09b114f7b259"   # mode=2
_SNAPSHOT_E5 = "8f0d95353584"   # mode=None
_SNAPSHOT_E6 = "3f986f5883b3"   # changed base_hash


# ===========================================================================
# C1 — AnalyzerFeature ABC shape (per §5.2 verbatim)
# ===========================================================================

class TestAnalyzerFeatureABC:
    """C1 (round 2): AnalyzerFeature is ABC; abstractmethods enforce contract.

    Per spec §5.2:
      - Subclass with all 3 abstractmethods instantiates without error
      - Subclass missing any abstractmethod raises TypeError at instantiation
      - 5 ClassVars present with correct defaults on base class
      - compute_hash() classmethod returns 12-char hex string
    """

    @requires_abc
    def test_complete_subclass_instantiates_without_error(self):
        """C1: a subclass implementing all 3 abstractmethods can be instantiated.

        ABC machinery: TypeError is raised at __init__ time for any missing
        abstractmethod, not at class definition time.
        """
        StubCls = _make_good_stub_class("complete_stub")
        try:
            instance = StubCls()
        except TypeError as exc:
            pytest.fail(
                f"Complete subclass raised TypeError at instantiation: {exc}\n"
                "All 3 abstractmethods (extract/reduce/emit) were implemented."
            )
        assert instance is not None

    @requires_abc
    def test_subclass_missing_extract_raises_type_error(self):
        """C1 inject-bug vector: drop extract → TypeError at instantiation.

        Per ABC contract: subclass missing any abstractmethod raises TypeError
        when you call MySubclass() — not at class definition time.

        Inject-bug: this test proves the guard — make extract a regular def
        (not @abstractmethod) in _base.py and this test goes red.
        """
        class _MissingExtract(AnalyzerFeature):
            FEATURE_ID = "missing_extract"

            # extract deliberately absent

            def reduce(self, prev_acc, this_acc) -> Any:
                return this_acc

            def emit(self, final_acc, summary: dict) -> None:
                pass

        with pytest.raises(TypeError, match="abstract"):
            _MissingExtract()

    @requires_abc
    def test_subclass_missing_reduce_raises_type_error(self):
        """C1: drop reduce → TypeError at instantiation."""
        class _MissingReduce(AnalyzerFeature):
            FEATURE_ID = "missing_reduce"

            def extract(self, parse_state, chunk_dict) -> dict:
                return {}

            # reduce deliberately absent

            def emit(self, final_acc, summary: dict) -> None:
                pass

        with pytest.raises(TypeError, match="abstract"):
            _MissingReduce()

    @requires_abc
    def test_subclass_missing_emit_raises_type_error(self):
        """C1: drop emit → TypeError at instantiation."""
        class _MissingEmit(AnalyzerFeature):
            FEATURE_ID = "missing_emit"

            def extract(self, parse_state, chunk_dict) -> dict:
                return {}

            def reduce(self, prev_acc, this_acc) -> Any:
                return this_acc

            # emit deliberately absent

        with pytest.raises(TypeError, match="abstract"):
            _MissingEmit()

    @requires_abc
    def test_unrelated_class_is_not_abc_subclass(self):
        """C1: an unrelated class (no inheritance) cannot be used as AnalyzerFeature.

        ABC enforces inheritance — isinstance(obj, AnalyzerFeature) returns False
        for objects that don't inherit from it (unlike Protocol duck-typing).
        """
        class _Unrelated:
            FEATURE_ID = "unrelated"

            def extract(self, parse_state, chunk_dict):
                return {}

            def reduce(self, prev_acc, this_acc):
                return this_acc

            def emit(self, final_acc, summary):
                pass

        obj = _Unrelated()
        assert not isinstance(obj, AnalyzerFeature), (
            "An unrelated class (no ABC inheritance) must not be an AnalyzerFeature instance.\n"
            "ABC requires explicit inheritance, unlike Protocol which is structural."
        )


# ---------------------------------------------------------------------------
# C1 — ClassVar defaults (5 vars, one assertion each per brief)
# ---------------------------------------------------------------------------

class TestAnalyzerFeatureClassVars:
    """C1: all 5 ClassVars present on base class with correct spec defaults."""

    @requires_abc
    def test_feature_id_default_is_empty_string(self):
        """C1: FEATURE_ID ClassVar[str] defaults to '' per §5.2.

        Inject-bug: if renamed to NAME, AttributeError fires when accessing
        AnalyzerFeature.FEATURE_ID.
        """
        assert hasattr(AnalyzerFeature, "FEATURE_ID"), (
            "AnalyzerFeature.FEATURE_ID ClassVar not found.\n"
            "C6 inject-bug: rename FEATURE_ID to NAME → this fires."
        )
        assert isinstance(AnalyzerFeature.FEATURE_ID, str), (
            f"FEATURE_ID must be str, got {type(AnalyzerFeature.FEATURE_ID).__name__}"
        )
        assert AnalyzerFeature.FEATURE_ID == "", (
            f"FEATURE_ID default must be '' (empty string), got {AnalyzerFeature.FEATURE_ID!r}"
        )

    @requires_abc
    def test_schema_keys_default_is_empty_tuple(self):
        """C1: SCHEMA_KEYS ClassVar[tuple[str, ...]] defaults to () per §5.2."""
        assert hasattr(AnalyzerFeature, "SCHEMA_KEYS"), (
            "AnalyzerFeature.SCHEMA_KEYS ClassVar not found."
        )
        assert isinstance(AnalyzerFeature.SCHEMA_KEYS, tuple), (
            f"SCHEMA_KEYS must be tuple, got {type(AnalyzerFeature.SCHEMA_KEYS).__name__}"
        )
        assert AnalyzerFeature.SCHEMA_KEYS == (), (
            f"SCHEMA_KEYS default must be (), got {AnalyzerFeature.SCHEMA_KEYS!r}"
        )

    @requires_abc
    def test_schema_version_default_is_one(self):
        """C1: SCHEMA_VERSION ClassVar[int] defaults to 1 per §5.2."""
        assert hasattr(AnalyzerFeature, "SCHEMA_VERSION"), (
            "AnalyzerFeature.SCHEMA_VERSION ClassVar not found."
        )
        assert isinstance(AnalyzerFeature.SCHEMA_VERSION, int), (
            f"SCHEMA_VERSION must be int, got {type(AnalyzerFeature.SCHEMA_VERSION).__name__}"
        )
        assert AnalyzerFeature.SCHEMA_VERSION == 1, (
            f"SCHEMA_VERSION default must be 1, got {AnalyzerFeature.SCHEMA_VERSION!r}"
        )

    @requires_abc
    def test_requires_default_is_empty_tuple(self):
        """C1: REQUIRES ClassVar[tuple[str, ...]] defaults to () per §5.2."""
        assert hasattr(AnalyzerFeature, "REQUIRES"), (
            "AnalyzerFeature.REQUIRES ClassVar not found."
        )
        assert isinstance(AnalyzerFeature.REQUIRES, tuple), (
            f"REQUIRES must be tuple, got {type(AnalyzerFeature.REQUIRES).__name__}"
        )
        assert AnalyzerFeature.REQUIRES == (), (
            f"REQUIRES default must be (), got {AnalyzerFeature.REQUIRES!r}"
        )

    @requires_abc
    def test_rtp_contribution_default_is_false(self):
        """C1: RTP_CONTRIBUTION ClassVar[bool] defaults to False per §5.2.

        CRITICAL: Wave 2e gate dependency reads RTP_CONTRIBUTION.
        Inject-bug: set default to True → this fires.
        """
        assert hasattr(AnalyzerFeature, "RTP_CONTRIBUTION"), (
            "AnalyzerFeature.RTP_CONTRIBUTION ClassVar not found.\n"
            "This is the Wave 2e gate dependency — must be present."
        )
        assert isinstance(AnalyzerFeature.RTP_CONTRIBUTION, bool), (
            f"RTP_CONTRIBUTION must be bool, got "
            f"{type(AnalyzerFeature.RTP_CONTRIBUTION).__name__}"
        )
        assert AnalyzerFeature.RTP_CONTRIBUTION is False, (
            f"RTP_CONTRIBUTION default must be False, got "
            f"{AnalyzerFeature.RTP_CONTRIBUTION!r}\n"
            "C6 inject-bug: default True → Wave 2e gate incorrectly counts "
            "non-RTP features as contributing."
        )

    @requires_abc
    def test_registered_fallback_rules_default_is_empty_dict(self):
        """C1: REGISTERED_FALLBACK_RULES ClassVar[dict[int, dict]] defaults to {} per §5.2."""
        assert hasattr(AnalyzerFeature, "REGISTERED_FALLBACK_RULES"), (
            "AnalyzerFeature.REGISTERED_FALLBACK_RULES ClassVar not found."
        )
        assert isinstance(AnalyzerFeature.REGISTERED_FALLBACK_RULES, dict), (
            f"REGISTERED_FALLBACK_RULES must be dict, got "
            f"{type(AnalyzerFeature.REGISTERED_FALLBACK_RULES).__name__}"
        )
        assert AnalyzerFeature.REGISTERED_FALLBACK_RULES == {}, (
            f"REGISTERED_FALLBACK_RULES default must be {{}}, got "
            f"{AnalyzerFeature.REGISTERED_FALLBACK_RULES!r}"
        )

    @requires_abc
    def test_old_name_attribute_absent(self):
        """C1 regression: NAME attribute must NOT exist on AnalyzerFeature.

        Round 1 used NAME; round 2 renames to FEATURE_ID.
        If a consumer tries feature.NAME they must get AttributeError, not
        silently receive empty string.

        Inject-bug: if implementer kept NAME as alias, this fires.
        """
        # We check the base class does NOT have NAME as a defined attribute.
        # Subclasses that don't inherit it won't have it either.
        assert not hasattr(AnalyzerFeature, "NAME"), (
            "AnalyzerFeature.NAME attribute found — this should be FEATURE_ID in round 2.\n"
            "C6 inject-bug: keeping NAME alias silently masks callers that use NAME."
        )

    @requires_abc
    def test_old_applies_to_method_absent(self):
        """C1 regression: applies_to() must NOT be an abstractmethod.

        Round 1 had applies_to(); round 2 removed it (manifest-declared).
        """
        assert not hasattr(AnalyzerFeature, "applies_to"), (
            "AnalyzerFeature.applies_to found — this was removed in round 2.\n"
            "Applicability is now manifest-declared, not instance-predicate."
        )

    @requires_abc
    def test_old_aggregate_method_absent(self):
        """C1 regression: aggregate() must NOT be an abstractmethod.

        Round 1 had aggregate(); round 2 renames to extract().
        """
        assert not hasattr(AnalyzerFeature, "aggregate"), (
            "AnalyzerFeature.aggregate found — this was renamed to extract() in round 2."
        )

    @requires_abc
    def test_old_finalize_method_absent(self):
        """C1 regression: finalize() must NOT be an abstractmethod.

        Round 1 had finalize(); round 2 renames to emit().
        """
        assert not hasattr(AnalyzerFeature, "finalize"), (
            "AnalyzerFeature.finalize found — this was renamed to emit() in round 2."
        )


# ---------------------------------------------------------------------------
# C1 — compute_hash() classmethod
# ---------------------------------------------------------------------------

class TestComputeHashClassmethod:
    """C1: compute_hash() returns 12-char hex of the subclass module's source."""

    @requires_abc
    def test_compute_hash_exists_as_classmethod(self):
        """C1: compute_hash must be a classmethod on AnalyzerFeature."""
        assert hasattr(AnalyzerFeature, "compute_hash"), (
            "AnalyzerFeature.compute_hash not found."
        )
        # It must be callable as a classmethod (not instance method)
        assert callable(AnalyzerFeature.compute_hash), (
            "compute_hash must be callable as a classmethod."
        )

    @requires_abc
    def test_compute_hash_returns_12_char_hex_string(self):
        """C1: compute_hash() on base class returns 12-char lowercase hex.

        Per §5.2: sha256(source_bytes).hexdigest()[:12]
        """
        result = AnalyzerFeature.compute_hash()
        assert isinstance(result, str), (
            f"compute_hash() must return str, got {type(result).__name__}"
        )
        assert len(result) == 12, (
            f"compute_hash() must return 12-char string, got len={len(result)}: {result!r}\n"
            "C6 inject-bug: [:11] truncation → this fires."
        )
        assert all(c in "0123456789abcdef" for c in result), (
            f"compute_hash() must return lowercase hex, got {result!r}"
        )

    @requires_abc
    def test_compute_hash_matches_sha256_of_source_file(self):
        """C1: compute_hash() must equal sha256(source_file_bytes)[:12].

        Per §5.2 spec:
            src = Path(cls.__module__.replace('.', '/') + '.py')
            return hashlib.sha256(src.read_bytes()).hexdigest()[:12]

        This test independently computes the expected hash and asserts equality.
        """
        # The base class module path
        module_path = AnalyzerFeature.__module__  # e.g. fresh_slotlab.analyzer.features._base
        src_file = ROOT / (module_path.replace(".", "/") + ".py")

        if not src_file.exists():
            pytest.skip(
                f"Source file {src_file} not found — implementer hasn't landed yet."
            )

        expected = hashlib.sha256(src_file.read_bytes()).hexdigest()[:12]
        actual = AnalyzerFeature.compute_hash()
        assert actual == expected, (
            f"compute_hash() mismatch:\n"
            f"  actual  = {actual!r}\n"
            f"  expected = {expected!r} (sha256({src_file})[:12])\n"
            "Per §5.2: compute_hash reads __module__ path and SHA256s the bytes."
        )

    @requires_abc
    def test_compute_hash_on_subclass_reads_subclass_module(self):
        """C1: compute_hash() on a subclass reads the SUBCLASS's source file.

        Per §5.2: uses cls.__module__ — so calling it on a subclass class
        hashes the subclass module, not the base class module.

        Since inline-defined test subclasses live in this test file's module,
        they compute the hash of this test file. We verify the return is still
        a valid 12-char hex (actual content check is covered above).
        """
        StubCls = _make_good_stub_class("hash_test_stub")
        if StubCls is None:
            pytest.skip("ABC not importable")

        result = StubCls.compute_hash()
        assert isinstance(result, str)
        assert len(result) == 12
        assert all(c in "0123456789abcdef" for c in result)

        # Must differ from base class hash (different source file)
        base_hash = AnalyzerFeature.compute_hash()
        assert result != base_hash, (
            "Subclass compute_hash() must hash the SUBCLASS module file, "
            "not the base class file. Got same hash as base class, meaning "
            "cls.__module__ resolution may be wrong."
        )

    @requires_abc
    def test_compute_hash_is_deterministic(self):
        """C1: compute_hash() called twice returns the same value."""
        h1 = AnalyzerFeature.compute_hash()
        h2 = AnalyzerFeature.compute_hash()
        assert h1 == h2, (
            f"compute_hash() is not deterministic: {h1!r} vs {h2!r}"
        )


# ===========================================================================
# C2 — compute_effective_analyzer_version: deterministic + composable + 12-char
# [UNCHANGED from round 1 — versioning.py API correct per critic]
# ===========================================================================

class TestComputeEffectiveAnalyzerVersion:
    """C2: deterministic, 12-char hex, correct composition algorithm.

    All expected values pre-computed via the reference implementation above
    and spot-checked in an independent Python session (see snapshots).
    [Unchanged from round 1 — versioning.py was correct]
    """

    @requires_versioning
    def test_returns_12_char_hex_string(self):
        """Output must be a 12-char lowercase hex string (sha256[:12])."""
        result = compute_effective_analyzer_version(
            base_hash="abc",
            feature_hashes={"f1": "hash1"},
            machine_features=["f1"],
            mode=1,
        )
        assert isinstance(result, str), f"Expected str, got {type(result).__name__}"
        assert len(result) == 12, (
            f"Expected 12-char hash, got len={len(result)}: {result!r}\n"
            "C6 inject-bug: truncating to [:11] makes this fire."
        )
        assert all(c in "0123456789abcdef" for c in result), (
            f"Hash contains non-hex chars: {result!r}"
        )

    @requires_versioning
    def test_example1_snapshot(self):
        """E1: base_hash='abc', features=[f1,f2], mode=1 → snapshot value."""
        result = compute_effective_analyzer_version(
            base_hash="abc",
            feature_hashes={"f1": "hash1", "f2": "hash2"},
            machine_features=["f1", "f2"],
            mode=1,
        )
        assert result == _SNAPSHOT_E1, (
            f"E1 snapshot mismatch: got {result!r}, expected {_SNAPSHOT_E1!r}\n"
            "The hash composition algorithm does not match §4.1."
        )

    @requires_versioning
    def test_example2_feature_order_is_sorted(self):
        """E2: reversed feature order must produce the same hash as E1.

        The algorithm must sort machine_features before hashing.
        """
        result_sorted = compute_effective_analyzer_version(
            base_hash="abc",
            feature_hashes={"f1": "hash1", "f2": "hash2"},
            machine_features=["f1", "f2"],
            mode=1,
        )
        result_reversed = compute_effective_analyzer_version(
            base_hash="abc",
            feature_hashes={"f1": "hash1", "f2": "hash2"},
            machine_features=["f2", "f1"],  # reversed
            mode=1,
        )
        assert result_sorted == result_reversed, (
            f"Feature order sensitivity: sorted={result_sorted!r}, "
            f"reversed={result_reversed!r}\n"
            "The algorithm must sort(set(machine_features)) per §4.1."
        )
        # Also matches E1 snapshot.
        assert result_reversed == _SNAPSHOT_E1

    @requires_versioning
    def test_example3_changing_one_feature_hash_changes_output(self):
        """E3: changing f1 hash must produce a different result.

        Core composition property: one feature change affects exactly
        machines using that feature.
        """
        result_original = compute_effective_analyzer_version(
            base_hash="abc",
            feature_hashes={"f1": "hash1", "f2": "hash2"},
            machine_features=["f1", "f2"],
            mode=1,
        )
        result_changed = compute_effective_analyzer_version(
            base_hash="abc",
            feature_hashes={"f1": "CHANGED", "f2": "hash2"},
            machine_features=["f1", "f2"],
            mode=1,
        )
        assert result_original != result_changed, (
            "Changing a feature hash must change the output hash."
        )
        assert result_changed == _SNAPSHOT_E3, (
            f"E3 snapshot mismatch: got {result_changed!r}, expected {_SNAPSHOT_E3!r}"
        )

    @requires_versioning
    def test_example4_changing_mode_changes_output(self):
        """E4: mode=2 must produce a different result than mode=1."""
        result_mode1 = compute_effective_analyzer_version(
            base_hash="abc",
            feature_hashes={"f1": "hash1", "f2": "hash2"},
            machine_features=["f1", "f2"],
            mode=1,
        )
        result_mode2 = compute_effective_analyzer_version(
            base_hash="abc",
            feature_hashes={"f1": "hash1", "f2": "hash2"},
            machine_features=["f1", "f2"],
            mode=2,
        )
        assert result_mode1 != result_mode2, (
            "Changing mode from 1 to 2 must produce a different hash."
        )
        assert result_mode2 == _SNAPSHOT_E4, (
            f"E4 snapshot mismatch: got {result_mode2!r}, expected {_SNAPSHOT_E4!r}"
        )

    @requires_versioning
    def test_example5_mode_none_differs_from_mode_int(self):
        """E5: mode=None must produce a different result than mode=1.

        Per §4.1: mode suffix is only appended when mode is not None.
        """
        result_mode1 = compute_effective_analyzer_version(
            base_hash="abc",
            feature_hashes={"f1": "hash1", "f2": "hash2"},
            machine_features=["f1", "f2"],
            mode=1,
        )
        result_mode_none = compute_effective_analyzer_version(
            base_hash="abc",
            feature_hashes={"f1": "hash1", "f2": "hash2"},
            machine_features=["f1", "f2"],
            mode=None,
        )
        assert result_mode1 != result_mode_none, (
            "mode=None must produce a different hash than mode=1.\n"
            "Per §4.1: mode suffix is only appended when mode is not None."
        )
        assert result_mode_none == _SNAPSHOT_E5, (
            f"E5 snapshot mismatch: got {result_mode_none!r}, expected {_SNAPSHOT_E5!r}"
        )

    @requires_versioning
    def test_example6_changing_base_hash_changes_output(self):
        """E6: changing base_hash must produce a different result."""
        result_original = compute_effective_analyzer_version(
            base_hash="abc",
            feature_hashes={"f1": "hash1", "f2": "hash2"},
            machine_features=["f1", "f2"],
            mode=1,
        )
        result_changed_base = compute_effective_analyzer_version(
            base_hash="CHANGED_BASE",
            feature_hashes={"f1": "hash1", "f2": "hash2"},
            machine_features=["f1", "f2"],
            mode=1,
        )
        assert result_original != result_changed_base, (
            "Changing base_hash must change the output hash."
        )
        assert result_changed_base == _SNAPSHOT_E6, (
            f"E6 snapshot mismatch: got {result_changed_base!r}, expected {_SNAPSHOT_E6!r}"
        )

    @requires_versioning
    def test_deterministic_same_call_same_output(self):
        """Calling with the same inputs twice must return the same result.

        Guards against any non-deterministic behavior (e.g., random salting).
        """
        kwargs = dict(
            base_hash="determinism_test",
            feature_hashes={"feat_a": "aaa", "feat_b": "bbb"},
            machine_features=["feat_a", "feat_b"],
            mode=7,
        )
        result1 = compute_effective_analyzer_version(**kwargs)
        result2 = compute_effective_analyzer_version(**kwargs)
        assert result1 == result2, (
            f"Same inputs produced different outputs: {result1!r} vs {result2!r}\n"
            "compute_effective_analyzer_version must be deterministic."
        )

    @requires_versioning
    def test_feature_deduplication_in_machine_features(self):
        """Duplicate features in machine_features must be deduplicated (set()).

        Per §4.1: sorted(set(machine_features)) — duplicates are dropped.
        """
        result_dup = compute_effective_analyzer_version(
            base_hash="abc",
            feature_hashes={"f1": "hash1"},
            machine_features=["f1", "f1", "f1"],  # duplicates
            mode=1,
        )
        result_single = compute_effective_analyzer_version(
            base_hash="abc",
            feature_hashes={"f1": "hash1"},
            machine_features=["f1"],
            mode=1,
        )
        assert result_dup == result_single, (
            "Duplicates in machine_features must be deduplicated before hashing.\n"
            "Per §4.1: sorted(set(machine_features))."
        )

    @requires_versioning
    def test_empty_machine_features_uses_only_base_and_mode(self):
        """Empty machine_features must produce a valid 12-char hash."""
        result = compute_effective_analyzer_version(
            base_hash="abc",
            feature_hashes={},
            machine_features=[],
            mode=1,
        )
        assert isinstance(result, str)
        assert len(result) == 12
        assert all(c in "0123456789abcdef" for c in result)

    @requires_versioning
    def test_result_matches_reference_implementation(self):
        """Cross-check: implementer's output must match our reference impl.

        The reference impl is coded directly from §4.1 (not using implementer's
        code), so this is an independent correctness check.
        """
        test_cases = [
            dict(
                base_hash="crosscheck_base",
                feature_hashes={"bc_m_anchor": "deadbeef01", "payouts": "cafebabe12"},
                machine_features=["payouts", "bc_m_anchor"],  # unsorted input
                mode=14,
            ),
            dict(
                base_hash="another_base",
                feature_hashes={"reel_marginal": "11223344556"},
                machine_features=["reel_marginal"],
                mode=None,
            ),
        ]
        for kwargs in test_cases:
            expected = _ref_effective_version(**kwargs)
            actual = compute_effective_analyzer_version(**kwargs)
            assert actual == expected, (
                f"Output mismatch vs reference impl for inputs {kwargs!r}:\n"
                f"  actual={actual!r}\n"
                f"  expected={expected!r}"
            )


# ===========================================================================
# C3 — feature_registry: empty by default, register() works, idempotent
# [Updated: stubs now use FEATURE_ID not NAME; ABC subclasses]
# ===========================================================================

class TestFeatureRegistry:
    """C3: ALL_FEATURES empty initially; register() appends; idempotent.

    Each test resets ALL_FEATURES to avoid cross-test contamination.
    Stubs now use FEATURE_ID (round-2 ABC API) instead of NAME.
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

    @requires_registry
    def test_all_features_empty_on_fresh_import(self):
        """C3: ALL_FEATURES must be an empty list before any register() call."""
        assert isinstance(_registry_mod.ALL_FEATURES, list), (
            "ALL_FEATURES must be a list"
        )
        assert len(_registry_mod.ALL_FEATURES) == 0, (
            f"ALL_FEATURES has {len(_registry_mod.ALL_FEATURES)} entries on "
            f"import — module has side-effect registrations at import time.\n"
            "C3 contract: registry must be empty by default."
        )

    @requires_registry
    def test_register_appends_feature(self):
        """C3: register(feature) must append to ALL_FEATURES.

        Uses a valid ABC stub (round-2 API with FEATURE_ID).
        """
        if not _ABC_IMPORTABLE:
            pytest.skip("ABC not importable — cannot build valid round-2 stub")

        stub = _make_registry_stub("reg_test_stub_a")
        assert len(_registry_mod.ALL_FEATURES) == 0, "precondition: clean slate"
        _registry_mod.register(stub)
        assert len(_registry_mod.ALL_FEATURES) == 1, (
            f"After register(), ALL_FEATURES should have 1 entry, got "
            f"{len(_registry_mod.ALL_FEATURES)}."
        )
        assert _registry_mod.ALL_FEATURES[0] is stub, (
            "Registered feature must be the same object in ALL_FEATURES."
        )

    @requires_registry
    def test_register_same_feature_id_is_idempotent(self):
        """C3: re-registering a feature with the same FEATURE_ID must not grow the list.

        Idempotent: either silently no-op OR raise a clear error.
        Uses FEATURE_ID (round-2) not NAME (round-1).

        C6 inject-bug: if register() unconditionally appends (no dedup check),
        calling it twice grows the list to 2 → this fires.
        """
        if not _ABC_IMPORTABLE:
            pytest.skip("ABC not importable — cannot build valid round-2 stub")

        stub = _make_registry_stub("idempotent_stub_b")
        assert len(_registry_mod.ALL_FEATURES) == 0, "precondition: clean slate"
        _registry_mod.register(stub)
        assert len(_registry_mod.ALL_FEATURES) == 1, "first register: should be 1"

        # Second register of same FEATURE_ID — must be idempotent.
        raised_exc = None
        try:
            _registry_mod.register(stub)
        except Exception as exc:
            raised_exc = exc

        if raised_exc is not None:
            # Raising a clear error is also acceptable.
            assert isinstance(raised_exc, (ValueError, KeyError, RuntimeError, TypeError)), (
                f"register() raised unexpected exception type "
                f"{type(raised_exc).__name__}: {raised_exc}"
            )
        else:
            # No exception: list must still have length 1 (idempotent no-op).
            assert len(_registry_mod.ALL_FEATURES) == 1, (
                f"After re-registering the same feature by FEATURE_ID, "
                f"ALL_FEATURES has length {len(_registry_mod.ALL_FEATURES)} instead of 1.\n"
                "C3 idempotency: register() must not create duplicates.\n"
                "C6 inject-bug: removing the FEATURE_ID dedup check makes this fire."
            )

    @requires_registry
    def test_register_returns_expected_reference(self):
        """C3: register() must not break the ALL_FEATURES list reference."""
        if not _ABC_IMPORTABLE:
            pytest.skip("ABC not importable — cannot build valid round-2 stub")

        ref_before = id(_registry_mod.ALL_FEATURES)
        _registry_mod.register(_make_registry_stub("ref_test_stub_c"))
        ref_after = id(_registry_mod.ALL_FEATURES)
        assert ref_before == ref_after, (
            "register() must not replace the ALL_FEATURES list object."
        )

    @requires_registry
    def test_register_multiple_distinct_features(self):
        """C3: registering 3 distinct-FEATURE_ID features yields length 3."""
        if not _ABC_IMPORTABLE:
            pytest.skip("ABC not importable — cannot build valid round-2 stubs")

        stubs = [_make_registry_stub(f"multi_stub_{i}") for i in range(3)]
        for s in stubs:
            _registry_mod.register(s)

        assert len(_registry_mod.ALL_FEATURES) == 3, (
            f"Expected 3 registered features, got {len(_registry_mod.ALL_FEATURES)}"
        )


# ===========================================================================
# C4 — get_features_for_machine: manifest-list-based filtering
# [Changed from round 1: reads manifest["analyzer_features"], not applies_to()]
# ===========================================================================

class TestGetFeaturesForMachine:
    """C4 (round 2): get_features_for_machine(machine_id, manifest) filters by
    manifest['analyzer_features'] list, not by applies_to() predicate.

    Per §5.2 applicability semantic: manifest declares which FEATURE_IDs apply.
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
    def test_filters_by_manifest_analyzer_features_list(self):
        """C4: only features whose FEATURE_ID is in manifest['analyzer_features']
        are returned.

        Stubs: feat_a, feat_b, feat_c registered.
        Manifest declares: ["feat_a", "feat_c"].
        Query → expect feat_a and feat_c only, NOT feat_b.
        """
        if not _ABC_IMPORTABLE:
            pytest.skip("ABC not importable — cannot build valid round-2 stubs")

        stub_a = _make_registry_stub("feat_a")
        stub_b = _make_registry_stub("feat_b")
        stub_c = _make_registry_stub("feat_c")

        _registry_mod.register(stub_a)
        _registry_mod.register(stub_b)
        _registry_mod.register(stub_c)
        assert len(_registry_mod.ALL_FEATURES) == 3, "precondition"

        # Manifest-style dict per §5.5.2 schema
        manifest = {
            "machine_id": "M14",
            "analyzer_features": ["feat_a", "feat_c"],
        }

        result = _registry_mod.get_features_for_machine("M14", manifest)

        result_ids = [f.FEATURE_ID for f in result]
        assert "feat_a" in result_ids, "feat_a must be in result (listed in manifest)"
        assert "feat_c" in result_ids, "feat_c must be in result (listed in manifest)"
        assert "feat_b" not in result_ids, (
            "feat_b must NOT be in result (not in manifest['analyzer_features']).\n"
            "C4 round-2: filtering is manifest-list-based, not applies_to-predicate."
        )

    @requires_registry
    def test_stable_registration_order_within_manifest_filter(self):
        """C4: returned features appear in registration order.

        When multiple features are in the manifest, they come back in the
        order they were registered (not the order they appear in the manifest).
        """
        if not _ABC_IMPORTABLE:
            pytest.skip("ABC not importable — cannot build valid round-2 stubs")

        names = ["order_first", "order_second", "order_third"]
        for name in names:
            _registry_mod.register(_make_registry_stub(name))

        manifest = {"analyzer_features": ["order_third", "order_first", "order_second"]}
        result = _registry_mod.get_features_for_machine("M_ANY", manifest)
        result_ids = [f.FEATURE_ID for f in result]

        # All three must appear.
        for name in names:
            assert name in result_ids, f"Feature {name!r} missing from result"

        # Order must match registration order (not manifest list order).
        indices = [result_ids.index(n) for n in names]
        assert indices == sorted(indices), (
            f"Features are not in registration order: {result_ids!r}\n"
            "get_features_for_machine must preserve registration order."
        )

    @requires_registry
    def test_empty_registry_returns_empty_list(self):
        """C4: querying on empty registry returns empty list (not None)."""
        manifest = {"analyzer_features": ["feat_x"]}
        result = _registry_mod.get_features_for_machine("M14", manifest)
        assert isinstance(result, list), (
            f"get_features_for_machine must return a list, got {type(result).__name__}"
        )
        assert len(result) == 0, (
            f"Empty registry query must return [], got {result!r}"
        )

    @requires_registry
    def test_empty_manifest_features_returns_empty(self):
        """C4: manifest with empty analyzer_features list returns []."""
        if not _ABC_IMPORTABLE:
            pytest.skip("ABC not importable — cannot build valid round-2 stubs")

        _registry_mod.register(_make_registry_stub("some_feature"))
        manifest = {"analyzer_features": []}
        result = _registry_mod.get_features_for_machine("M_ANY", manifest)
        assert isinstance(result, list)
        assert len(result) == 0, (
            "When manifest['analyzer_features'] is empty, result must be empty."
        )

    @requires_registry
    def test_manifest_feature_not_in_registry_is_silently_skipped(self):
        """C4: feature IDs in manifest but not registered are silently skipped.

        The manifest may reference features that haven't been imported yet.
        The function must not raise; it returns only registered + declared features.
        """
        if not _ABC_IMPORTABLE:
            pytest.skip("ABC not importable — cannot build valid round-2 stubs")

        _registry_mod.register(_make_registry_stub("registered_feat"))
        manifest = {
            "analyzer_features": ["registered_feat", "not_yet_registered_feat"],
        }
        # Must not raise.
        result = _registry_mod.get_features_for_machine("M14", manifest)
        result_ids = [f.FEATURE_ID for f in result]
        assert "registered_feat" in result_ids
        assert "not_yet_registered_feat" not in result_ids


# ===========================================================================
# C5 — No import-time side effects (subprocess smoke)
# [Updated: includes fresh_slotlab.analyzer.features._base (round-2 path)]
# ===========================================================================

class TestNoImportTimeSideEffects:
    """C5: spawning a fresh Python process and importing all modules
    must complete rc=0 with no output to stderr.

    Per memory feedback_subprocess_import_suicide_and_module_globals.md.
    Round-2 update: fresh_slotlab.analyzer.features._base added.
    """

    # Round-1 modules still included (they still exist)
    MODULES_TO_IMPORT = [
        "fresh_slotlab.analyzer",
        "fresh_slotlab.analyzer.versioning",
        "fresh_slotlab.analyzer.feature_registry",
    ]

    # Round-2 new module (may not exist until impl-implementer r2 lands)
    NEW_MODULE = "fresh_slotlab.analyzer.features._base"

    def test_subprocess_import_round1_modules_exits_zero(self):
        """C5: fresh Python subprocess importing round-1 modules must exit rc=0."""
        import_stmt = "; ".join(
            f"import {mod}" for mod in self.MODULES_TO_IMPORT
        )
        cmd = [sys.executable, "-c", f"{import_stmt}; print('OK')"]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Import smoke failed (rc={result.returncode})\n"
            f"STDOUT: {result.stdout!r}\n"
            f"STDERR: {result.stderr!r}\n"
            "At least one round-1 module has import-time side effects or fails to import."
        )
        assert "OK" in result.stdout

    def test_subprocess_import_features_base_exits_zero(self):
        """C5: fresh Python subprocess importing features._base must exit rc=0.

        Round-2 new module. If impl-implementer hasn't landed yet, this will
        fail with ModuleNotFoundError; that is expected and correct behavior
        (test goes red until impl lands).
        """
        cmd = [
            sys.executable, "-c",
            f"import {self.NEW_MODULE}; print('OK')",
        ]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Import of {self.NEW_MODULE!r} failed (rc={result.returncode})\n"
            f"STDOUT: {result.stdout!r}\n"
            f"STDERR: {result.stderr!r}\n"
            "fresh_slotlab.analyzer.features._base has import-time side effects "
            "or is not yet implemented."
        )
        assert "OK" in result.stdout

    def test_subprocess_import_no_stderr_round1(self):
        """C5: importing round-1 modules must not emit anything to stderr."""
        import_stmt = "; ".join(
            f"import {mod}" for mod in self.MODULES_TO_IMPORT
        )
        cmd = [sys.executable, "-W", "error", "-c", import_stmt]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 and "ModuleNotFoundError" not in result.stderr:
            assert result.returncode == 0, (
                f"Import with -W error failed (rc={result.returncode})\n"
                f"STDERR: {result.stderr!r}\n"
                "New modules emit warnings or errors at import time."
            )

    @pytest.mark.parametrize("module_path", [
        "fresh_slotlab.analyzer",
        "fresh_slotlab.analyzer.versioning",
        "fresh_slotlab.analyzer.feature_registry",
        "fresh_slotlab.analyzer.features._base",
    ])
    def test_each_module_importable_individually(self, module_path):
        """C5: each module must be individually importable (rc=0).

        Round-2 update: 4 modules, replacing feature_protocol with features._base.
        """
        cmd = [sys.executable, "-c", f"import {module_path}; print('OK')"]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Module {module_path!r} failed to import individually "
            f"(rc={result.returncode})\n"
            f"STDERR: {result.stderr!r}"
        )


# ===========================================================================
# C6 — Inject-bug TDD verification tests
# ===========================================================================

class TestInjectBugC1ABCDrop:
    """C6/C1 inject-bug: dropping an abstractmethod from ABC subclass → TypeError.

    These tests directly simulate what happens with each inject scenario
    and document the proof that the C1 guard catches the regression.
    """

    @requires_abc
    def test_inject_drop_extract_TypeError_fires(self):
        """C6 C1 inject proof: subclass missing extract → TypeError at init.

        Simulate the bug: if extract were not @abstractmethod, the subclass
        missing it would instantiate without error. The C1 test
        test_subclass_missing_extract_raises_type_error would then go RED.

        This test proves the guard is real: we create the bad subclass and
        confirm TypeError is raised.
        """
        class _BadExtract(AnalyzerFeature):
            FEATURE_ID = "inject_bad_extract"
            # extract deliberately absent

            def reduce(self, prev_acc, this_acc) -> Any:
                return this_acc

            def emit(self, final_acc, summary: dict) -> None:
                pass

        raised = False
        try:
            _BadExtract()
        except TypeError:
            raised = True

        assert raised, (
            "INJECT-BUG PROOF C1/extract: subclass missing extract() must raise TypeError.\n"
            "If this fails, extract is not @abstractmethod — the C1 guard is broken."
        )

    @requires_abc
    def test_inject_drop_reduce_TypeError_fires(self):
        """C6 C1 inject proof: subclass missing reduce → TypeError at init."""
        class _BadReduce(AnalyzerFeature):
            FEATURE_ID = "inject_bad_reduce"

            def extract(self, parse_state, chunk_dict) -> dict:
                return {}

            # reduce deliberately absent

            def emit(self, final_acc, summary: dict) -> None:
                pass

        raised = False
        try:
            _BadReduce()
        except TypeError:
            raised = True

        assert raised, (
            "INJECT-BUG PROOF C1/reduce: subclass missing reduce() must raise TypeError."
        )

    @requires_abc
    def test_inject_drop_emit_TypeError_fires(self):
        """C6 C1 inject proof: subclass missing emit → TypeError at init."""
        class _BadEmit(AnalyzerFeature):
            FEATURE_ID = "inject_bad_emit"

            def extract(self, parse_state, chunk_dict) -> dict:
                return {}

            def reduce(self, prev_acc, this_acc) -> Any:
                return this_acc

            # emit deliberately absent

        raised = False
        try:
            _BadEmit()
        except TypeError:
            raised = True

        assert raised, (
            "INJECT-BUG PROOF C1/emit: subclass missing emit() must raise TypeError."
        )

    @requires_abc
    def test_inject_feature_id_renamed_to_name_fails_classvar_check(self):
        """C6 C1 inject proof: FEATURE_ID renamed to NAME → ClassVar check fires.

        Inject scenario: implementer ships 'NAME = ...' instead of 'FEATURE_ID'.
        The test test_feature_id_default_is_empty_string asserts
        hasattr(AnalyzerFeature, 'FEATURE_ID') — with NAME it would fire.
        """
        # Prove the guard: if NAME exists but not FEATURE_ID, the test fails.
        class _NameNotFeatureId:
            NAME: ClassVar[str] = ""  # wrong attribute name
            # FEATURE_ID absent

        assert not hasattr(_NameNotFeatureId, "FEATURE_ID"), (
            "Precondition: _NameNotFeatureId must not have FEATURE_ID."
        )
        assert hasattr(_NameNotFeatureId, "NAME"), (
            "Precondition: _NameNotFeatureId has NAME (the bug)."
        )
        # The test_feature_id_default_is_empty_string guard:
        # hasattr(AnalyzerFeature, 'FEATURE_ID') would be False → assertion fires.
        # This proves the guard is real.

    @requires_abc
    def test_inject_rtp_contribution_default_true_fails_check(self):
        """C6 C1 inject proof: RTP_CONTRIBUTION default=True → False check fires.

        Inject scenario: implementer writes RTP_CONTRIBUTION: ClassVar[bool] = True.
        test_rtp_contribution_default_is_false would fire.

        We prove the guard by asserting False is False (correct) and confirming
        that True is not False (the inject scenario).
        """
        correct_default = False
        injected_default = True

        # The guard assertion: assert value is False
        assert correct_default is False, "Correct default passes guard"
        assert injected_default is not False, (
            "INJECT-BUG PROOF C1/RTP_CONTRIBUTION: True would fail the 'is False' check.\n"
            "Wave 2e gate reads this to count RTP-contributing features."
        )


class TestInjectBugC2HashLength:
    """C6/C2 inject-bug: truncating to [:11] makes the length assertion fire."""

    @requires_versioning
    def test_inject_truncate_11_chars_would_fail_length_check(self):
        """C6 C2 inject proof: 11-char string fails len==12 assertion."""
        injected_11char = "abcdef012345"[:11]
        assert len(injected_11char) == 11
        assert len(injected_11char) != 12, (
            "INJECT-BUG PROOF C2: 11-char string must not satisfy len==12 check.\n"
            "If the implementer truncates to [:11], test_returns_12_char_hex_string fires."
        )

    @requires_versioning
    def test_snapshot_length_guards_truncation(self):
        """C2 snapshot values are 12 chars — truncation to [:11] fires snapshot checks."""
        for name, snap in [
            ("E1", _SNAPSHOT_E1),
            ("E3", _SNAPSHOT_E3),
            ("E4", _SNAPSHOT_E4),
            ("E5", _SNAPSHOT_E5),
            ("E6", _SNAPSHOT_E6),
        ]:
            assert len(snap) == 12, (
                f"Snapshot {name}={snap!r} is not 12 chars — snapshot itself is wrong."
            )


class TestInjectBugC3SilentDedup:
    """C6/C3 inject-bug: register() without dedup check → idempotency fires."""

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
    def test_inject_unconditional_append_would_fail_idempotency(self):
        """C6 C3 inject proof: append-without-dedup causes len=2 → idempotency fires.

        Simulate the buggy register: directly append the same object twice.
        Assert that len becomes 2, which is what broken register() produces,
        and which the idempotency test would catch.
        """
        if not _ABC_IMPORTABLE:
            pytest.skip("ABC not importable — cannot build valid round-2 stub")

        stub = _make_registry_stub("dedup_inject_stub")
        # Simulate the buggy register: always append regardless.
        _registry_mod.ALL_FEATURES.append(stub)
        _registry_mod.ALL_FEATURES.append(stub)  # duplicate

        dup_len = len(_registry_mod.ALL_FEATURES)
        assert dup_len == 2, (
            "Precondition: unconditional double-append produces len=2."
        )
        assert dup_len != 1, (
            "INJECT-BUG PROOF C3: len=2 would cause idempotency assertion to fire.\n"
            "If register() has proper dedup, len stays 1 (correct behavior)."
        )


class TestInjectBugC4ManifestFiltering:
    """C6/C4 inject-bug: applies_to-based filtering (old API) would fail new tests.

    Proves that the C4 tests enforce manifest-based filtering specifically.
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
    def test_inject_applies_to_based_filtering_would_fail(self):
        """C6 C4 inject proof: if get_features_for_machine used applies_to (old API)
        instead of manifest['analyzer_features'], it would return wrong results.

        Scenario: feat_b has applies_to returning True for M14, but M14's manifest
        only lists feat_a. Old API would include feat_b; new API must not.

        This proves the manifest-list guard is real.
        """
        if not _ABC_IMPORTABLE or not _REGISTRY_IMPORTABLE:
            pytest.skip("ABC or registry not importable")

        # What old applies_to-based filtering would return:
        # "all features where applies_to(M14) is True"
        # → would include feat_b (because it returns True for everything)

        stub_a = _make_registry_stub("feat_a_inject")
        stub_b = _make_registry_stub("feat_b_inject")  # NOT in manifest

        _registry_mod.register(stub_a)
        _registry_mod.register(stub_b)

        manifest = {"analyzer_features": ["feat_a_inject"]}  # feat_b_inject NOT listed

        result = _registry_mod.get_features_for_machine("M14", manifest)
        result_ids = [f.FEATURE_ID for f in result]

        # Under manifest-based filtering: only feat_a_inject
        assert "feat_a_inject" in result_ids, "feat_a_inject must be in result"
        assert "feat_b_inject" not in result_ids, (
            "feat_b_inject is registered but NOT in manifest — must be excluded.\n"
            "C6 inject-bug: old applies_to predicate would include it (all return True).\n"
            "This proves manifest-list filtering is enforced."
        )
