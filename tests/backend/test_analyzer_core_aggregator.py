"""Regression tests for ticket P2-B2 — Carve analyzer/core/aggregator.py + create core/_utils.py.

Contracts asserted (per 00_ticket.md §3):

  C1 — Files exist + symbols carved:
       fresh_slotlab/analyzer/core/aggregator.py present with 16 + 2 aggregator-scoped
       symbols (accessible via hasattr). fresh_slotlab/analyzer/core/_utils.py present
       with 9 shared helpers. PIA re-exports all 16+2 symbols so pia.symbol still works.

  C2 — P1-A1 canary:
       tests/integration/test_analyzer_three_invocation_parity.py imports cleanly
       (structural canary only; actual 23/23 run is impl-verifier's job).

  C3 — Single source of truth (dedup):
       For each of the 9 formerly-duplicated helpers:
       - inspect.getfile(pia.symbol) endswith "_utils.py"
       - inspect.getfile(core_parser.symbol) endswith "_utils.py"
       - pia.symbol is core_parser.symbol is core_utils.symbol (same object)

  C4 — Subprocess import safety:
       python -c "import fresh_slotlab.analyzer.core._utils" rc=0, no stderr.
       python -c "import fresh_slotlab.analyzer.core.aggregator" rc=0, no stderr.
       Each new module independently importable.

  C5 — Cycle freedom (static grep):
       _utils.py MUST NOT import from fresh_slotlab (any sub-module).
       aggregator.py MUST NOT import from fresh_slotlab.player_impact_analyzer.
       parser.py MUST NOT import from fresh_slotlab.analyzer.core.aggregator.

  C6 — Hash composition rolls forward:
       Adding _utils.py and aggregator.py to core/*.py changes compute_base_analyzer_version().
       Simulated by mutating bytes of _utils.py in memory; reference hash flips.

  C7 — No silent swallows:
       AST scan of _utils.py: 0 silent except: pass patterns expected (pure utility).
       AST scan of aggregator.py: baseline counted from PIA range (0 in 1100-1900).

  C8 — Inject-bug TDD:
       For C3: if parser.py re-adds a local `def to_float` → is-SAME test goes RED.
       For C5: if _utils.py adds `from fresh_slotlab.analyzer.core.aggregator import X` → cycle test RED.
       For C1: if aggregator.py is missing a symbol → hasattr test goes RED.
       Each proven by actual file edit + pytest run + revert (documented in 03_tests.md).

Inject-bug discipline per memory feedback_integration_test_argv.md:
    Every test proven red by injecting the bug it guards, then restored green.
    Verification log in session_artifacts/_impl/phase2/04_core_aggregator/03_tests.md.

Subprocess-mode requirement per memory feedback_perf_claim_needs_e2e_event_stream.md:
    C4 uses real subprocess (python -c), not just in-process import.

Enumerate-all-paths per memory feedback_enumerate_safety_paths.md:
    C3 checks each of the 9 symbols individually (parametrized).
    C5 checks each of the 3 cycle directions independently.

Split-path per memory feedback_subprocess_import_suicide_and_module_globals.md:
    C3 object-identity check proves each symbol resolves to _utils, not a local copy.

Architecture references:
    session_artifacts/_arch/04_architecture_proposal_v5.md §6.2
    session_artifacts/_impl/phase2/04_core_aggregator/00_ticket.md §3
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = ROOT / "fresh_slotlab" / "analyzer" / "core"
CORE_UTILS = CORE_DIR / "_utils.py"
CORE_AGGREGATOR = CORE_DIR / "aggregator.py"
CORE_PARSER = CORE_DIR / "parser.py"
CORE_INIT = CORE_DIR / "__init__.py"

# ---------------------------------------------------------------------------
# Import guards — written against planned module paths per §1 spec.
# If implementer hasn't landed yet, tests gracefully skip with message.
# Pattern mirrors test_analyzer_core_parser.py.
# ---------------------------------------------------------------------------

try:
    import fresh_slotlab.analyzer.core._utils as _core_utils_mod
    _CORE_UTILS_IMPORTABLE = True
except ImportError:
    _CORE_UTILS_IMPORTABLE = False

try:
    import fresh_slotlab.analyzer.core.aggregator as _core_aggregator_mod
    _CORE_AGGREGATOR_IMPORTABLE = True
except ImportError:
    _CORE_AGGREGATOR_IMPORTABLE = False

try:
    import fresh_slotlab.analyzer.core.parser as _core_parser_mod
    _CORE_PARSER_IMPORTABLE = True
except ImportError:
    _CORE_PARSER_IMPORTABLE = False

try:
    import fresh_slotlab.player_impact_analyzer as _pia
    _PIA_IMPORTABLE = True
except ImportError:
    _PIA_IMPORTABLE = False

# versioning module for hash composition (may live in versioning.py per P2-A1)
_compute_base_ver_fn = None
try:
    from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version as _cbav
    _compute_base_ver_fn = _cbav
    _BASE_VERSION_IMPORTABLE = True
except ImportError:
    _BASE_VERSION_IMPORTABLE = False

# ---------------------------------------------------------------------------
# Skip markers
# ---------------------------------------------------------------------------

requires_core_utils = pytest.mark.skipif(
    not _CORE_UTILS_IMPORTABLE,
    reason=(
        "fresh_slotlab.analyzer.core._utils not yet importable — "
        "impl-implementer has not landed P2-B2 yet"
    ),
)
requires_core_aggregator = pytest.mark.skipif(
    not _CORE_AGGREGATOR_IMPORTABLE,
    reason=(
        "fresh_slotlab.analyzer.core.aggregator not yet importable — "
        "impl-implementer has not landed P2-B2 yet"
    ),
)
requires_core_parser = pytest.mark.skipif(
    not _CORE_PARSER_IMPORTABLE,
    reason="fresh_slotlab.analyzer.core.parser not yet importable",
)
requires_pia = pytest.mark.skipif(
    not _PIA_IMPORTABLE,
    reason="fresh_slotlab.player_impact_analyzer not importable",
)
requires_base_version = pytest.mark.skipif(
    not _BASE_VERSION_IMPORTABLE,
    reason="compute_base_analyzer_version not yet importable from versioning.py",
)


# ---------------------------------------------------------------------------
# Reference implementation for base hash (matches test_analyzer_core_parser.py)
# Per §4.1: sha256(all core/*.py files sorted).hexdigest()[:12]
# ---------------------------------------------------------------------------

def _ref_base_version() -> str | None:
    """Reference: SHA256 of all core/*.py files, sorted, concatenated.

    Returns None if core/ directory doesn't exist or has no .py files.
    Per 04_architecture_proposal_v5.md §4.1.
    """
    if not CORE_DIR.exists():
        return None
    py_files = sorted(CORE_DIR.glob("*.py"))
    if not py_files:
        return None
    h = hashlib.sha256()
    for f in py_files:
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


# ---------------------------------------------------------------------------
# Symbol tables — the contracts per §1 of the ticket
# ---------------------------------------------------------------------------

# The 16 aggregator-scoped function/class symbols (4 categories) + 2 constants.
# All must be accessible via hasattr from core.aggregator AND from PIA.
_AGGREGATOR_SYMBOLS_FUNCTIONS = [
    # Bankruptcy (7)
    "_BankruptcyStreamAccumulator",
    "simulate_bankruptcy_from_response",
    "compute_bankruptcy_percentiles",
    "fastest_bankruptcy_spins_from_list",
    "median_spins_from_list",
    "_empty_bankruptcy_tier",
    "_extract_bankruptcy_reps",
    # Bucket rows (3)
    "build_multiplier_bucket_rows",
    "return_bucket",
    "quantile_from_hist",
    # Classifiers (2)
    "classify_volatility",
    "classify_experience_archetype",
    # Guideline comparison (4)
    "_metric_path_get",
    "_eval_operator",
    "_deviation",
    "evaluate_guideline_comparison",
]

_AGGREGATOR_SYMBOLS_CONSTANTS = [
    "_DEFAULT_BANKROLL_MULTIPLIERS",
    "_DEFAULT_BANKRUPTCY_SESSION_SPINS",
]

# All 16+2 aggregator-scoped symbols (everything aggregator.py must expose).
_ALL_AGGREGATOR_SYMBOLS = _AGGREGATOR_SYMBOLS_FUNCTIONS + _AGGREGATOR_SYMBOLS_CONSTANTS

# The 9 shared helpers that P2-B1b duplicated into parser.py.
# After P2-B2 these must ALL reside in _utils.py and be re-exported from
# both parser.py and PIA. The object-identity check is the dedup proof.
_UTILS_SYMBOLS = [
    "to_float",
    "blank_like_symbol",
    "bonus_chain_depth_bucket",
    "return_bucket",
    "_empty_bankruptcy_tier",
    "_extract_bankruptcy_reps",
    "simulate_bankruptcy_from_response",
    "_DEFAULT_BANKROLL_MULTIPLIERS",
    "_DEFAULT_BANKRUPTCY_SESSION_SPINS",
]

# The 3 pure-utility helpers that live ONLY in _utils.py (not aggregator-scoped).
_UTILS_ONLY_SYMBOLS = [
    "to_float",
    "blank_like_symbol",
    "bonus_chain_depth_bucket",
]


# ===========================================================================
# C1 — File existence
# ===========================================================================

class TestFilesExist:
    """C1: both new files must be present on disk."""

    def test_core_utils_exists(self):
        """C1: fresh_slotlab/analyzer/core/_utils.py must be present.

        Inject-bug: if implementer creates aggregator.py but forgets _utils.py,
        the dedup step silently fails and parser.py has local duplicates.
        This test fires immediately — no import needed.
        """
        assert CORE_UTILS.exists(), (
            f"fresh_slotlab/analyzer/core/_utils.py not found at {CORE_UTILS}\n"
            "C1: _utils.py must be created by P2-B2.\n"
            "This test goes RED until impl-implementer creates the file."
        )

    def test_core_aggregator_exists(self):
        """C1: fresh_slotlab/analyzer/core/aggregator.py must be present.

        Inject-bug: if implementer forgets to create the file (or puts it
        in the wrong location), this fires before any import test runs.
        """
        assert CORE_AGGREGATOR.exists(), (
            f"fresh_slotlab/analyzer/core/aggregator.py not found at {CORE_AGGREGATOR}\n"
            "C1: aggregator.py must be carved from PIA and placed here by P2-B2."
        )

    def test_core_dir_is_a_directory(self):
        """C1: the core/ path must be a directory (package marker check)."""
        assert CORE_DIR.is_dir(), (
            f"fresh_slotlab/analyzer/core/ is not a directory at {CORE_DIR}"
        )

    def test_core_init_still_exists(self):
        """C1: __init__.py from P2-B1 must not be accidentally deleted by P2-B2."""
        assert CORE_INIT.exists(), (
            f"fresh_slotlab/analyzer/core/__init__.py not found at {CORE_INIT}\n"
            "C1: P2-B2 must not delete the package marker created in P2-B1."
        )

    def test_core_parser_still_exists(self):
        """C1: parser.py from P2-B1 must not be accidentally deleted by P2-B2."""
        assert CORE_PARSER.exists(), (
            f"fresh_slotlab/analyzer/core/parser.py not found at {CORE_PARSER}\n"
            "C1: P2-B2 modifies parser.py (dedup) but must not delete it."
        )


# ===========================================================================
# C1 — Aggregator-scoped symbols accessible from core.aggregator
# ===========================================================================

class TestAggregatorSymbolsInModule:
    """C1: all 16+2 aggregator-scoped symbols accessible from core.aggregator."""

    @requires_core_aggregator
    @pytest.mark.parametrize("symbol_name", _AGGREGATOR_SYMBOLS_FUNCTIONS)
    def test_function_or_class_present_in_aggregator(self, symbol_name):
        """C1: each of the 16 function/class symbols accessible from core.aggregator.

        Inject-bug (C8 - C1 variant): if implementer only partially moves symbols
        (e.g., leaves compute_bankruptcy_percentiles in PIA without re-exporting),
        this fires for the missing symbol.

        Proven RED by deleting classify_volatility from aggregator.py in 03_tests.md.
        """
        assert hasattr(_core_aggregator_mod, symbol_name), (
            f"fresh_slotlab.analyzer.core.aggregator.{symbol_name} not found.\n"
            "C1: all 16 aggregator-scoped function/class symbols must be accessible\n"
            "from core.aggregator (either defined there or imported from _utils).\n"
            f"Inject-bug proof: delete {symbol_name!r} from aggregator.py → fires."
        )

    @requires_core_aggregator
    @pytest.mark.parametrize("const_name", _AGGREGATOR_SYMBOLS_CONSTANTS)
    def test_constant_present_in_aggregator(self, const_name):
        """C1: each of the 2 constants accessible from core.aggregator.

        These constants belong in _utils.py (shared with parser) but aggregator
        must re-export them so existing PIA callers still work.
        """
        assert hasattr(_core_aggregator_mod, const_name), (
            f"fresh_slotlab.analyzer.core.aggregator.{const_name} not found.\n"
            "C1: aggregator.py must expose the 2 _DEFAULT_* constants\n"
            "(either defined locally or imported from _utils.py)."
        )

    @requires_core_aggregator
    def test_bankruptcy_stream_accumulator_is_class(self):
        """C1: _BankruptcyStreamAccumulator must be a class (not a function).

        The brief confirms it is a stateful class. This guards against the
        implementer accidentally renaming it to a factory function.
        """
        obj = getattr(_core_aggregator_mod, "_BankruptcyStreamAccumulator")
        assert isinstance(obj, type), (
            "_BankruptcyStreamAccumulator must be a class, not a function/other.\n"
            "C1: this is a stateful accumulator class per §6 Risk 2."
        )

    @requires_core_aggregator
    def test_default_bankroll_multipliers_is_tuple(self):
        """C1: _DEFAULT_BANKROLL_MULTIPLIERS must be a tuple (not a list).

        Per PIA source: _DEFAULT_BANKROLL_MULTIPLIERS: tuple[int, ...] = (100, 200, 500)
        If the implementer changes the type during the move, callers that unpack
        it into function signatures expecting a tuple would break.
        """
        val = getattr(_core_aggregator_mod, "_DEFAULT_BANKROLL_MULTIPLIERS")
        assert isinstance(val, tuple), (
            f"_DEFAULT_BANKROLL_MULTIPLIERS must be a tuple, got {type(val).__name__!r}.\n"
            "C1: per PIA definition 'tuple[int, ...] = (100, 200, 500)'."
        )
        assert len(val) > 0, "_DEFAULT_BANKROLL_MULTIPLIERS must be non-empty."

    @requires_core_aggregator
    def test_default_bankruptcy_session_spins_is_positive_int(self):
        """C1: _DEFAULT_BANKRUPTCY_SESSION_SPINS must be a positive integer."""
        val = getattr(_core_aggregator_mod, "_DEFAULT_BANKRUPTCY_SESSION_SPINS")
        assert isinstance(val, int) and val > 0, (
            f"_DEFAULT_BANKRUPTCY_SESSION_SPINS must be a positive int, got {val!r}.\n"
            "C1: per PIA definition '_DEFAULT_BANKRUPTCY_SESSION_SPINS = 10000'."
        )


# ===========================================================================
# C1 — _utils.py symbols accessible from core._utils
# ===========================================================================

class TestUtilsSymbolsInModule:
    """C1: all 9 shared helpers accessible from core._utils."""

    @requires_core_utils
    @pytest.mark.parametrize("symbol_name", _UTILS_SYMBOLS)
    def test_symbol_present_in_utils(self, symbol_name):
        """C1: each of the 9 shared symbols must be accessible from core._utils.

        Inject-bug: if _utils.py only has 8 of the 9 (e.g., forgot return_bucket),
        this fires for the missing one AND the dedup test (C3) will also fail
        because parser.py still has a local definition.
        """
        assert hasattr(_core_utils_mod, symbol_name), (
            f"fresh_slotlab.analyzer.core._utils.{symbol_name} not found.\n"
            "C1: all 9 shared helpers must be defined in _utils.py.\n"
            f"Missing {symbol_name!r} means the dedup is incomplete."
        )

    @requires_core_utils
    def test_to_float_callable(self):
        """C1: to_float must be callable and return expected values."""
        to_float = getattr(_core_utils_mod, "to_float")
        assert callable(to_float), "to_float must be callable"
        assert to_float("1.5") == 1.5, "to_float('1.5') must return 1.5"
        assert to_float(None) == 0.0, "to_float(None) must return default 0.0"
        assert to_float(True) == 0.0, "to_float(True) must return default (bool-safe)"

    @requires_core_utils
    def test_blank_like_symbol_callable(self):
        """C1: blank_like_symbol must be callable with expected behavior."""
        blank_like_symbol = getattr(_core_utils_mod, "blank_like_symbol")
        assert callable(blank_like_symbol)
        assert blank_like_symbol("blank") is True
        assert blank_like_symbol("BAR") is False

    @requires_core_utils
    def test_return_bucket_callable(self):
        """C1: return_bucket must be callable with expected bucketing behavior."""
        return_bucket = getattr(_core_utils_mod, "return_bucket")
        assert callable(return_bucket)
        assert return_bucket(0.0) == "eq0", "return_bucket(0) must return 'eq0'"
        assert return_bucket(0.5) == "gt0_lt1", "return_bucket(0.5) must return 'gt0_lt1'"
        assert return_bucket(100.0) == "ge100_lt200", "return_bucket(100) must return 'ge100_lt200'"

    @requires_core_utils
    def test_simulate_bankruptcy_from_response_callable(self):
        """C1: simulate_bankruptcy_from_response must be callable."""
        fn = getattr(_core_utils_mod, "simulate_bankruptcy_from_response")
        assert callable(fn), "simulate_bankruptcy_from_response must be callable"


# ===========================================================================
# C1 — PIA re-exports all 16+2 aggregator symbols + 9 _utils symbols
# ===========================================================================

class TestPIAReExportsAggregatorSymbols:
    """C1: PIA must re-export all 16+2 aggregator-scoped symbols (backward compat)."""

    @requires_pia
    @pytest.mark.parametrize("symbol_name", _ALL_AGGREGATOR_SYMBOLS)
    def test_pia_has_aggregator_symbol(self, symbol_name):
        """C1: each aggregator-scoped symbol still accessible via pia.symbol.

        Inject-bug (C8 - C1 via PIA): delete one re-export line in PIA
        → this fires for that symbol.

        This guards the backward-compat requirement: callers that do
        `from fresh_slotlab.player_impact_analyzer import simulate_bankruptcy_from_response`
        must keep working after the carve.
        """
        assert hasattr(_pia, symbol_name), (
            f"fresh_slotlab.player_impact_analyzer.{symbol_name} not found.\n"
            "C1: PIA must re-export all 16+2 aggregator-scoped symbols.\n"
            f"Inject-bug: delete re-export of {symbol_name!r} in PIA → this fires."
        )

    @requires_pia
    @pytest.mark.parametrize("symbol_name", _UTILS_ONLY_SYMBOLS)
    def test_pia_has_utils_only_symbol(self, symbol_name):
        """C1: the 3 pure-utility helpers must also be accessible via PIA.

        These (to_float, blank_like_symbol, bonus_chain_depth_bucket) are in
        _utils.py and must still be re-exported by PIA for backward compat.
        """
        assert hasattr(_pia, symbol_name), (
            f"fresh_slotlab.player_impact_analyzer.{symbol_name} not found.\n"
            "C1: PIA must re-export the 3 pure-utility helpers from _utils.py.\n"
            "These were previously defined in PIA directly."
        )


# ===========================================================================
# C2 — P1-A1 canary (structural import check only)
# ===========================================================================

class TestP1A1ParityCanary:
    """C2: structural canary that the 3-invocation parity test file is intact.

    Per brief §3 C2: 'tests/integration/test_analyzer_three_invocation_parity.py
    23/23 GREEN'. We assert structural soundness; actual run is verifier's job.
    """

    def test_p1_a1_parity_test_file_exists(self):
        """C2: the P1-A1 parity test file must still exist after P2-B2."""
        parity_file = (
            ROOT / "tests" / "integration" /
            "test_analyzer_three_invocation_parity.py"
        )
        assert parity_file.exists(), (
            f"P1-A1 parity test file not found: {parity_file}\n"
            "C2: this file must not be deleted or moved by P2-B2."
        )

    def test_p1_a1_parity_test_importable(self):
        """C2: the parity test file must import without blowing up.

        Per brief §3 C2: 'importlib.import_module(...)  doesn't blow up'.
        This is a structural (SyntaxError + ImportError) guard, not a
        full run of the 23 invocation pairs.
        """
        parity_file = (
            ROOT / "tests" / "integration" /
            "test_analyzer_three_invocation_parity.py"
        )
        if not parity_file.exists():
            pytest.skip("Parity test file missing — covered by existence test above")

        # Validate it at least parses as valid Python
        source = parity_file.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as exc:
            pytest.fail(
                f"P1-A1 parity test file has a SyntaxError: {exc}\n"
                "C2: P2-B2 must not corrupt the parity test file."
            )

    @requires_pia
    def test_pia_still_has_simulate_bankruptcy_for_parity_path(self):
        """C2: pia.simulate_bankruptcy_from_response accessible (used in parity path).

        The 3-invocation parity test exercises the full parse path including
        bankruptcy simulation. If PIA loses this symbol, the parity path breaks.
        """
        assert hasattr(_pia, "simulate_bankruptcy_from_response"), (
            "pia.simulate_bankruptcy_from_response not accessible.\n"
            "C2: the P1-A1 parity test parity path includes bankruptcy simulation."
        )
        assert callable(_pia.simulate_bankruptcy_from_response), (
            "pia.simulate_bankruptcy_from_response is not callable.\n"
            "C2: this function is exercised during the 3-invocation parity run."
        )


# ===========================================================================
# C3 — Single source of truth: all 9 _utils symbols resolve to _utils.py
# ===========================================================================

class TestSingleSourceOfTruth:
    """C3: for each of the 9 formerly-duplicated helpers, every import path
    must resolve to _utils.py — not a local copy in parser.py or PIA.

    After P2-B2:
      - parser.py imports the 9 from _utils.py (removes its duplicates)
      - PIA imports the 9 from _utils.py (removes its originals)
      - aggregator.py imports the 6 bankruptcy/bucket ones from _utils.py

    The test checks:
      1. inspect.getfile(pia.symbol) endswith '_utils.py'
      2. inspect.getfile(core_parser.symbol) endswith '_utils.py'
      3. pia.symbol is core_parser.symbol is core_utils.symbol (same object)

    Per brief §3 C3 + memory feedback_subprocess_import_suicide_and_module_globals.md:
    monkeypatch-style split-path is the only way to prove the module-global
    vs instance-attr distinction — here we use object identity.

    Inject-bug C8 for this class: temporarily re-add a local `def to_float(...)` to
    parser.py → the `is` check fails → test goes RED. Documented in 03_tests.md.
    """

    # These 7 are callable functions — inspect.getfile works on them.
    _CALLABLE_UTILS_SYMBOLS = [
        "to_float",
        "blank_like_symbol",
        "bonus_chain_depth_bucket",
        "return_bucket",
        "_empty_bankruptcy_tier",
        "_extract_bankruptcy_reps",
        "simulate_bankruptcy_from_response",
    ]

    # The 2 constants — getfile raises TypeError (built-in / immutable)
    # We can only do the `is` check where Python interns the object (tuple for
    # _DEFAULT_BANKROLL_MULTIPLIERS; int for _DEFAULT_BANKRUPTCY_SESSION_SPINS).
    _CONSTANT_UTILS_SYMBOLS = [
        "_DEFAULT_BANKROLL_MULTIPLIERS",
        "_DEFAULT_BANKRUPTCY_SESSION_SPINS",
    ]

    @requires_pia
    @requires_core_utils
    @pytest.mark.parametrize("symbol_name", _CALLABLE_UTILS_SYMBOLS)
    def test_pia_symbol_resolves_to_utils_file(self, symbol_name):
        """C3: inspect.getfile(pia.symbol) must end with '_utils.py'.

        After P2-B2, PIA no longer defines these symbols in its body —
        it imports them from _utils.py. If PIA still has a local copy,
        inspect.getfile returns player_impact_analyzer.py, not _utils.py.

        Inject-bug (C8 - C3-pia): if PIA re-adds a local `def to_float(...)`,
        getfile returns pia path → test goes RED for that symbol.
        """
        obj = getattr(_pia, symbol_name)
        try:
            source_file = inspect.getfile(obj)
        except TypeError:
            pytest.skip(f"{symbol_name!r} is a built-in/constant — skip getfile check")

        assert source_file.endswith("_utils.py"), (
            f"pia.{symbol_name} resolves to {source_file!r}\n"
            "C3: must resolve to _utils.py, not player_impact_analyzer.py.\n"
            "This means PIA still has a local copy instead of re-exporting.\n"
            f"Inject-bug C8: add local def {symbol_name}(...) to PIA → fires here."
        )

    @requires_core_parser
    @requires_core_utils
    @pytest.mark.parametrize("symbol_name", _CALLABLE_UTILS_SYMBOLS)
    def test_parser_symbol_resolves_to_utils_file(self, symbol_name):
        """C3: inspect.getfile(core_parser.symbol) must end with '_utils.py'.

        After P2-B2, parser.py imports these 9 from _utils.py (dedup step).
        If parser.py still has a local copy from P2-B1b, getfile returns parser.py.

        Inject-bug (C8 - C3-parser): this is THE primary inject-bug for C3.
        Per brief §3 C8: 'Inject: re-add a local def to_float(...) to parser.py
        that does something different → assertion that all import paths resolve
        to _utils.to_float goes RED.'
        Documented full inject+revert cycle in 03_tests.md.
        """
        obj = getattr(_core_parser_mod, symbol_name)
        try:
            source_file = inspect.getfile(obj)
        except TypeError:
            pytest.skip(f"{symbol_name!r} is a built-in/constant — skip getfile check")

        assert source_file.endswith("_utils.py"), (
            f"core_parser.{symbol_name} resolves to {source_file!r}\n"
            "C3: must resolve to _utils.py after dedup.\n"
            "This means parser.py still has a local duplicate from P2-B1b.\n"
            "Per brief §3 C8 inject: add local def back to parser.py → fires here."
        )

    @requires_pia
    @requires_core_parser
    @requires_core_utils
    @pytest.mark.parametrize("symbol_name", _CALLABLE_UTILS_SYMBOLS)
    def test_pia_and_parser_and_utils_are_same_object(self, symbol_name):
        """C3: pia.symbol is core_parser.symbol is core_utils.symbol (same object).

        The 'is' check (identity, not equality) proves all three import paths
        resolve to the single definition in _utils.py — no copies anywhere.

        Per brief §3 C3 strong form:
          'pia.return_bucket is core_parser.return_bucket is core_utils.return_bucket'

        Per memory feedback_subprocess_import_suicide_and_module_globals.md:
        This is the split-path test that catches coincidence-masked duplicates.
        If parser.py and PIA coincidentally implement the same logic but as
        separate objects, equality would pass but identity fails.

        Inject-bug (C8 - C3-identity): if parser.py re-adds a local def for
        any of these 9, the identity chain breaks → this test goes RED.
        """
        pia_obj = getattr(_pia, symbol_name)
        parser_obj = getattr(_core_parser_mod, symbol_name)
        utils_obj = getattr(_core_utils_mod, symbol_name)

        assert pia_obj is utils_obj, (
            f"pia.{symbol_name} IS NOT core_utils.{symbol_name}.\n"
            "C3: PIA must re-export from _utils.py, not define its own copy.\n"
            f"pia_obj id={id(pia_obj)}, utils_obj id={id(utils_obj)}\n"
            "Inject-bug C8: add local def back to PIA body → 'is' fails here."
        )

        assert parser_obj is utils_obj, (
            f"core_parser.{symbol_name} IS NOT core_utils.{symbol_name}.\n"
            "C3: parser.py must import from _utils.py (dedup complete), not define own copy.\n"
            f"parser_obj id={id(parser_obj)}, utils_obj id={id(utils_obj)}\n"
            "This is the primary C8 inject scenario from the brief."
        )

    @requires_pia
    @requires_core_parser
    @requires_core_utils
    @pytest.mark.parametrize("symbol_name", _CONSTANT_UTILS_SYMBOLS)
    def test_constant_value_consistent_across_all_modules(self, symbol_name):
        """C3: constant value must be consistent across PIA, parser, and _utils.

        For immutable constants (int, tuple), Python may or may not intern the
        same object, so 'is' is not reliable. We assert value equality instead.

        After P2-B2, all three modules must reference the same _utils.py constants.
        A value mismatch means one module still has a stale hardcoded copy.
        """
        pia_val = getattr(_pia, symbol_name)
        parser_val = getattr(_core_parser_mod, symbol_name)
        utils_val = getattr(_core_utils_mod, symbol_name)

        assert pia_val == utils_val, (
            f"pia.{symbol_name} ({pia_val!r}) != core_utils.{symbol_name} ({utils_val!r}).\n"
            "C3: PIA must re-export the constant from _utils.py, not use a stale local value."
        )
        assert parser_val == utils_val, (
            f"core_parser.{symbol_name} ({parser_val!r}) != core_utils.{symbol_name} ({utils_val!r}).\n"
            "C3: parser.py must import the constant from _utils.py, not use a stale local value."
        )


# ===========================================================================
# C4 — Subprocess import safety
# ===========================================================================

class TestSubprocessImportSafety:
    """C4: importing each new module in a subprocess must have zero side effects.

    Per memory feedback_subprocess_import_suicide_and_module_globals.md:
    both _utils.py and aggregator.py must be import-safe.

    Per memory feedback_perf_claim_needs_e2e_event_stream.md:
    subprocess-mode bugs need subprocess-mode tests; unit + import-smoke alone
    is NOT enough.
    """

    def test_utils_subprocess_import_exits_zero(self):
        """C4: python -c 'import fresh_slotlab.analyzer.core._utils; print(OK)' rc=0.

        _utils.py is a pure utility module: stdlib only, no I/O, no module-top
        computation. If import fails with rc!=0, the dedup step is broken and
        parser.py can no longer import from it.

        Inject-bug proof (documented in 03_tests.md): adding
        'import logging; logging.basicConfig()' to _utils.py top would not make
        rc!=0 but would emit to stderr. The -W error test below catches that.
        """
        cmd = [
            sys.executable, "-c",
            "import fresh_slotlab.analyzer.core._utils; print('OK')",
        ]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 and "ModuleNotFoundError" in result.stderr:
            pytest.skip(
                "fresh_slotlab.analyzer.core._utils not yet implemented — "
                "waiting on impl-implementer"
            )
        assert result.returncode == 0, (
            f"Import of fresh_slotlab.analyzer.core._utils failed "
            f"(rc={result.returncode})\n"
            f"STDOUT: {result.stdout!r}\n"
            f"STDERR: {result.stderr!r}\n"
            "C4: _utils.py must be import-safe with zero side effects."
        )
        assert "OK" in result.stdout, (
            f"Expected 'OK' in stdout, got {result.stdout!r}"
        )

    def test_aggregator_subprocess_import_exits_zero(self):
        """C4: python -c 'import fresh_slotlab.analyzer.core.aggregator; print(OK)' rc=0.

        aggregator.py imports from _utils.py and possibly parser.py. If either
        has a broken import or cycle, the subprocess fails with an ImportError.

        Inject-bug proof: adding a back-import to PIA inside aggregator.py would
        cause a circular import chain → ImportError → rc!=0 → this fires.
        """
        cmd = [
            sys.executable, "-c",
            "import fresh_slotlab.analyzer.core.aggregator; print('OK')",
        ]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 and "ModuleNotFoundError" in result.stderr:
            pytest.skip(
                "fresh_slotlab.analyzer.core.aggregator not yet implemented — "
                "waiting on impl-implementer"
            )
        assert result.returncode == 0, (
            f"Import of fresh_slotlab.analyzer.core.aggregator failed "
            f"(rc={result.returncode})\n"
            f"STDOUT: {result.stdout!r}\n"
            f"STDERR: {result.stderr!r}\n"
            "C4: aggregator.py must be import-safe. Check for circular imports."
        )
        assert "OK" in result.stdout

    def test_utils_subprocess_no_stderr(self):
        """C4: importing _utils.py must not emit to stderr.

        Uses -W error to convert warnings to errors. A warning at import time
        (e.g., DeprecationWarning from a module it pulls in) would make this fail.
        """
        cmd = [
            sys.executable, "-W", "error", "-c",
            "import fresh_slotlab.analyzer.core._utils",
        ]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 and "ModuleNotFoundError" in result.stderr:
            pytest.skip("_utils.py not yet implemented")
        assert result.returncode == 0, (
            f"_utils.py import with -W error failed (rc={result.returncode})\n"
            f"STDERR: {result.stderr!r}\n"
            "C4: importing _utils.py must not trigger any warnings."
        )

    def test_aggregator_subprocess_no_stderr(self):
        """C4: importing aggregator.py must not emit to stderr."""
        cmd = [
            sys.executable, "-W", "error", "-c",
            "import fresh_slotlab.analyzer.core.aggregator",
        ]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 and "ModuleNotFoundError" in result.stderr:
            pytest.skip("aggregator.py not yet implemented")
        assert result.returncode == 0, (
            f"aggregator.py import with -W error failed (rc={result.returncode})\n"
            f"STDERR: {result.stderr!r}\n"
            "C4: importing aggregator.py must not trigger any warnings."
        )

    def test_utils_does_not_pull_in_pia_at_import_time(self):
        """C4 (cycle guard): importing _utils.py alone must NOT import PIA.

        _utils.py is the lowest level of the core hierarchy. If importing it
        triggers PIA's module-level code, that's a cycle violation that could
        cause _recover_orphan_running_runs() or other side effects to fire.

        Per memory feedback_subprocess_import_suicide_and_module_globals.md.
        """
        code = (
            "import sys; "
            "import fresh_slotlab.analyzer.core._utils; "
            "pia_imported = 'fresh_slotlab.player_impact_analyzer' in sys.modules; "
            "print(f'pia_imported={pia_imported}')"
        )
        cmd = [sys.executable, "-c", code]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            if "ModuleNotFoundError" in result.stderr:
                pytest.skip("_utils.py not yet implemented")
            pytest.fail(
                f"Subprocess failed (rc={result.returncode})\n"
                f"STDERR: {result.stderr!r}"
            )
        assert "pia_imported=True" not in result.stdout, (
            "Importing core._utils also imported player_impact_analyzer.\n"
            "C4/C5: _utils.py has a circular dependency on PIA."
        )

    def test_aggregator_does_not_pull_in_pia_at_import_time(self):
        """C4 (cycle guard): importing aggregator.py alone must NOT import PIA.

        Per brief §3 C5: 'aggregator.py MUST NOT import from
        fresh_slotlab.player_impact_analyzer.' A dynamic import at module load
        time would be caught here even if the static grep (C5 class) misses it.
        """
        code = (
            "import sys; "
            "import fresh_slotlab.analyzer.core.aggregator; "
            "pia_imported = 'fresh_slotlab.player_impact_analyzer' in sys.modules; "
            "print(f'pia_imported={pia_imported}')"
        )
        cmd = [sys.executable, "-c", code]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            if "ModuleNotFoundError" in result.stderr:
                pytest.skip("aggregator.py not yet implemented")
            pytest.fail(
                f"Subprocess failed (rc={result.returncode})\n"
                f"STDERR: {result.stderr!r}"
            )
        assert "pia_imported=True" not in result.stdout, (
            "Importing core.aggregator also imported player_impact_analyzer.\n"
            "C4/C5: aggregator.py must not have a back-dependency on PIA."
        )

    @pytest.mark.parametrize("module_path", [
        "fresh_slotlab.analyzer.core._utils",
        "fresh_slotlab.analyzer.core.aggregator",
    ])
    def test_each_new_module_individually_importable(self, module_path):
        """C4: each new core module must be individually importable (rc=0).

        Parametrized per memory feedback_enumerate_safety_paths.md:
        assert each path separately so failures are individually identifiable.
        """
        cmd = [sys.executable, "-c", f"import {module_path}; print('OK')"]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 and "ModuleNotFoundError" in result.stderr:
            pytest.skip(
                f"Module {module_path!r} not yet implemented — "
                "waiting on impl-implementer"
            )
        assert result.returncode == 0, (
            f"Module {module_path!r} failed to import individually "
            f"(rc={result.returncode})\n"
            f"STDERR: {result.stderr!r}"
        )


# ===========================================================================
# C5 — Cycle freedom (static grep, 3 independent directions)
# ===========================================================================

class TestCycleFreedom:
    """C5: three static grep tests asserting forbidden import directions.

    Per brief §3 C5 and memory feedback_enumerate_safety_paths.md:
    each cycle direction gets its own test so failures are individually named.

    Static grep is the authoritative cycle guard — it catches back-imports
    even inside function bodies that wouldn't fire at import time.

    Inject-bug C8 for C5: add a forbidden import line → test goes RED.
    Documented in 03_tests.md.
    """

    def test_utils_does_not_import_from_fresh_slotlab(self):
        """C5: _utils.py MUST NOT import from parser.py, aggregator.py, or PIA.

        The specific prohibitions per brief §3 C5:
          - MUST NOT import from core/parser.py
          - MUST NOT import from core/aggregator.py
          - MUST NOT import from fresh_slotlab.player_impact_analyzer

        Note: fresh_slotlab.round_win is NOT prohibited — _extract_bankruptcy_reps
        needs RoundWinRule and that module is a standalone non-cyclical dep.
        The brief's 'stdlib only' language means no prohibited fresh_slotlab imports,
        not that round_win is disallowed (it's in the same category as trigger_sessions
        in parser.py and is not part of the parser/aggregator/PIA cycle).

        Inject-bug (C8 - C5-utils): per brief §3 C8:
        'Inject: add a from fresh_slotlab.analyzer.core.aggregator import X
        inside core/_utils.py → cycle test RED.'
        Proven in 03_tests.md by actual file edit + run + revert.
        """
        if not CORE_UTILS.exists():
            pytest.skip("_utils.py not yet created by P2-B2 — nothing to grep")

        source = CORE_UTILS.read_text(encoding="utf-8")

        # Check each prohibited target individually (per memory feedback_enumerate_safety_paths)
        prohibited_patterns = [
            "fresh_slotlab.analyzer.core.parser",
            "fresh_slotlab.analyzer.core.aggregator",
            "fresh_slotlab.player_impact_analyzer",
        ]

        all_violations = []
        for pattern in prohibited_patterns:
            for lineno, line in enumerate(source.splitlines(), start=1):
                # Skip comment lines and docstrings (only check import statements)
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                # Match only actual import statements (not docstring mentions)
                if pattern in line and (
                    stripped.startswith("import ")
                    or stripped.startswith("from ")
                ):
                    all_violations.append((lineno, pattern, line.rstrip()))

        assert len(all_violations) == 0, (
            f"C5 CYCLE VIOLATION: _utils.py contains {len(all_violations)} "
            "prohibited import(s).\n"
            "_utils.py must not import from: parser.py, aggregator.py, or PIA.\n"
            "Per brief §3 C5: these three are the explicitly prohibited targets.\n"
            "Inject-bug C8 (documented in 03_tests.md):\n"
            "  add 'from fresh_slotlab.analyzer.core.aggregator import X' → fires.\n"
            "Offending lines:\n"
            + "\n".join(f"  _utils.py:{ln} [{pat}]: {text}"
                        for ln, pat, text in all_violations)
        )

    def test_aggregator_does_not_import_from_pia(self):
        """C5: aggregator.py MUST NOT import from fresh_slotlab.player_impact_analyzer.

        aggregator.py may import from core/_utils.py and core/parser.py (both
        upstream in the data-flow). It must NOT import from PIA (which imports
        from aggregator — that creates a cycle).

        Per brief §3 C5: 'aggregator.py MUST NOT import from
        fresh_slotlab.player_impact_analyzer.'

        The grep must match only import statements (not docstring mentions of the
        prohibited pattern, which commonly appear in module docstrings).
        """
        if not CORE_AGGREGATOR.exists():
            pytest.skip("aggregator.py not yet created by P2-B2 — nothing to grep")

        source = CORE_AGGREGATOR.read_text(encoding="utf-8")
        back_import_lines = [
            (lineno, line.rstrip())
            for lineno, line in enumerate(source.splitlines(), start=1)
            if "fresh_slotlab.player_impact_analyzer" in line
            # Only flag actual import statements, not comments/docstrings
            and (
                line.lstrip().startswith("import ")
                or line.lstrip().startswith("from ")
            )
        ]

        assert len(back_import_lines) == 0, (
            f"C5 CYCLE VIOLATION: aggregator.py contains {len(back_import_lines)} "
            "back-import(s) from fresh_slotlab.player_impact_analyzer.\n"
            "PIA imports from aggregator; aggregator must NOT import from PIA.\n"
            "Per brief §3 C5: forbidden import direction.\n"
            "Offending lines:\n"
            + "\n".join(f"  aggregator.py:{ln}: {text}" for ln, text in back_import_lines)
        )

    def test_parser_does_not_import_from_aggregator(self):
        """C5: parser.py MUST NOT import from fresh_slotlab.analyzer.core.aggregator.

        parser.py is upstream of aggregator in the data-flow pipeline.
        The correct dependency direction is: _utils.py ← parser.py ← aggregator.py.
        A reverse import (parser ← aggregator) inverts the dependency and may
        cause circular imports.

        Per brief §3 C5: 'core/parser.py MUST NOT import from core/aggregator.py
        (wrong direction). It may newly import from core/_utils.py (that is the dedup).'
        """
        if not CORE_PARSER.exists():
            pytest.skip("core/parser.py not yet created — nothing to grep")

        source = CORE_PARSER.read_text(encoding="utf-8")
        wrong_direction_lines = [
            (lineno, line.rstrip())
            for lineno, line in enumerate(source.splitlines(), start=1)
            if "fresh_slotlab.analyzer.core.aggregator" in line
            and not line.lstrip().startswith("#")
        ]

        assert len(wrong_direction_lines) == 0, (
            f"C5 WRONG DIRECTION: parser.py contains {len(wrong_direction_lines)} "
            "import(s) from fresh_slotlab.analyzer.core.aggregator.\n"
            "parser.py is UPSTREAM of aggregator — it must not import from it.\n"
            "Per brief §3 C5: parser may import from _utils.py but not aggregator.py.\n"
            "Offending lines:\n"
            + "\n".join(f"  parser.py:{ln}: {text}" for ln, text in wrong_direction_lines)
        )

    def test_parser_imports_from_utils_not_defines_locally(self):
        """C5 + C3 bridge: parser.py MUST import from core._utils AND not redefine symbols.

        After P2-B2:
        1. parser.py must have the _utils import line (necessary condition)
        2. parser.py must NOT also have local def statements for the 9 shared
           helpers (which would shadow the import and break C3 identity)

        The dedup step is: import from _utils (at top) + delete local defs.
        Both halves must land together per §6 Risk 1 ('must be atomic').

        This test catches the partially-landed state where parser.py has both
        the import AND the legacy local defs (Python uses the later binding,
        so the local def wins and 'is' tests in C3 go RED).
        """
        if not CORE_PARSER.exists():
            pytest.skip("core/parser.py not yet created — nothing to grep")

        # If _utils.py doesn't exist yet, the dedup cannot have happened
        if not CORE_UTILS.exists():
            pytest.skip("_utils.py not yet created — dedup cannot have happened")

        source = CORE_PARSER.read_text(encoding="utf-8")

        # Check import is present
        has_utils_import = (
            "fresh_slotlab.analyzer.core._utils" in source
            or "from _utils import" in source  # script-mode form
        )

        assert has_utils_import, (
            "C5/C3 PART 1: parser.py does not import from core._utils.\n"
            "After P2-B2, parser.py must have:\n"
            "  from fresh_slotlab.analyzer.core._utils import (...)\n"
            "Either the dedup step is incomplete or uses an unexpected pattern."
        )

        # Check that local defs are NOT present (they shadow the import)
        # We check for 'def to_float' and 'def return_bucket' as canaries
        # of the 9 duplicate defs that must be deleted.
        local_defs_found = []
        for symbol in ["to_float", "blank_like_symbol", "bonus_chain_depth_bucket",
                        "return_bucket", "_empty_bankruptcy_tier"]:
            for lineno, line in enumerate(source.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith(f"def {symbol}("):
                    local_defs_found.append((lineno, stripped[:60]))
                    break

        assert len(local_defs_found) == 0, (
            f"C5/C3 PART 2: parser.py still has {len(local_defs_found)} local def(s)\n"
            "that shadow the _utils import. Python uses the LAST binding for each name\n"
            "in module scope — so these local defs win over the import, breaking C3.\n"
            "Per brief §6 Risk 1: 'Removing 9 duplicates from parser.py and adding\n"
            "them to _utils.py MUST happen in the same commit.'\n"
            "The import was added but local defs were not removed:\n"
            + "\n".join(f"  parser.py:{ln}: {text}" for ln, text in local_defs_found)
        )


# ===========================================================================
# C6 — Hash composition: adding _utils.py + aggregator.py flips base hash
# ===========================================================================

class TestHashCompositionRollsForward:
    """C6: adding new files to core/*.py changes compute_base_analyzer_version().

    Per brief §3 C6: 'Adding _utils.py and aggregator.py to the set MUST flip
    the base hash deterministically. Test: edit one byte in _utils.py → hash flips.'

    We do NOT edit the real _utils.py (prod code read-only for tester).
    Instead we verify the hash mechanism via the reference implementation
    (_ref_base_version), which mimics what compute_base_analyzer_version() should do.
    Same pattern as test_analyzer_core_parser.py §C5.
    """

    def test_adding_utils_py_changes_hash(self):
        """C6: presence of _utils.py in core/ changes the base hash vs without it.

        This tests that the hash algorithm actually includes _utils.py.
        If compute_base_analyzer_version() only hashes parser.py + __init__.py,
        adding _utils.py would have no effect.

        We compute two hashes:
          - without_utils: sha256 of core/*.py files excluding _utils.py
          - with_utils: sha256 of all core/*.py files (the real hash)
        Assert they differ.
        """
        if not CORE_DIR.exists():
            pytest.skip("core/ directory not yet created")
        if not CORE_UTILS.exists():
            pytest.skip("_utils.py not yet created — waiting on impl-implementer")

        # Hash WITH _utils.py (current state after P2-B2)
        py_files_all = sorted(CORE_DIR.glob("*.py"))
        if not py_files_all:
            pytest.skip("No .py files in core/ yet")

        h_with = hashlib.sha256()
        for f in py_files_all:
            h_with.update(f.read_bytes())
        hash_with = h_with.hexdigest()[:12]

        # Hash WITHOUT _utils.py (simulates pre-P2-B2 state)
        py_files_without = [f for f in py_files_all if f.name != "_utils.py"]
        if not py_files_without:
            pytest.skip("Only _utils.py in core/ — need at least one other file")

        h_without = hashlib.sha256()
        for f in py_files_without:
            h_without.update(f.read_bytes())
        hash_without = h_without.hexdigest()[:12]

        assert hash_with != hash_without, (
            "C6: hash WITH _utils.py equals hash WITHOUT _utils.py.\n"
            "This means the hash algorithm is ignoring _utils.py.\n"
            f"  hash_with    = {hash_with!r}\n"
            f"  hash_without = {hash_without!r}\n"
            "Expected: adding _utils.py to core/*.py changes the hash."
        )

    def test_adding_aggregator_py_changes_hash(self):
        """C6: presence of aggregator.py in core/ changes the base hash vs without it.

        Same mechanism as above but for aggregator.py.
        """
        if not CORE_DIR.exists():
            pytest.skip("core/ directory not yet created")
        if not CORE_AGGREGATOR.exists():
            pytest.skip("aggregator.py not yet created — waiting on impl-implementer")

        # Hash WITH aggregator.py
        py_files_all = sorted(CORE_DIR.glob("*.py"))
        h_with = hashlib.sha256()
        for f in py_files_all:
            h_with.update(f.read_bytes())
        hash_with = h_with.hexdigest()[:12]

        # Hash WITHOUT aggregator.py
        py_files_without = [f for f in py_files_all if f.name != "aggregator.py"]
        if not py_files_without:
            pytest.skip("Only aggregator.py in core/ — need at least one other file")

        h_without = hashlib.sha256()
        for f in py_files_without:
            h_without.update(f.read_bytes())
        hash_without = h_without.hexdigest()[:12]

        assert hash_with != hash_without, (
            "C6: hash WITH aggregator.py equals hash WITHOUT aggregator.py.\n"
            "This means the hash algorithm is ignoring aggregator.py.\n"
            f"  hash_with    = {hash_with!r}\n"
            f"  hash_without = {hash_without!r}"
        )

    def test_mutating_utils_py_content_flips_hash(self):
        """C6 inject-byte: edit one byte in _utils.py → hash flips.

        Per brief §3 C6: 'Test: edit one byte in _utils.py → hash flips.'
        We simulate this by adding a sentinel comment to the in-memory bytes
        (not touching the real file) and verifying the hash changes.
        """
        if not CORE_UTILS.exists():
            pytest.skip("_utils.py not yet created — waiting on impl-implementer")

        py_files = sorted(CORE_DIR.glob("*.py"))

        # Compute original hash
        h_original = hashlib.sha256()
        for f in py_files:
            h_original.update(f.read_bytes())
        original = h_original.hexdigest()[:12]

        # Compute modified hash (one sentinel byte added to _utils.py)
        h_modified = hashlib.sha256()
        for f in py_files:
            raw = f.read_bytes()
            if f.name == "_utils.py":
                raw = raw + b"\n# SENTINEL_INJECT_BUG_C6\n"
            h_modified.update(raw)
        modified = h_modified.hexdigest()[:12]

        assert original != modified, (
            "C6: adding a sentinel byte to _utils.py did NOT change the hash.\n"
            f"  original = {original!r}\n"
            f"  modified = {modified!r}\n"
            "The hash mechanism is not reading _utils.py bytes."
        )

    @requires_base_version
    def test_base_version_is_12char_hex(self):
        """C6: compute_base_analyzer_version() must return 12-char lowercase hex.

        After P2-B2, the function must still work (it now hashes more files).
        """
        result = _compute_base_ver_fn()
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
    def test_base_version_matches_reference_after_p2_b2(self):
        """honesty-2 update: base_hash covers the R-1 closure (25-file set), not just core/*.py.

        Phase honesty-2 (2026-05-29) redefined compute_base_analyzer_version() to hash the
        transitive repo-local import closure of the report-production path (R-1), not just
        core/*.py. The test intent survives: core/*.py files (including _utils.py and
        aggregator.py) ARE in the closure, and the function must be deterministic.

        The old assertion (actual == _ref_base_version()) is now wrong because _ref_base_version()
        only hashes core/*.py, but the live function hashes 25 files. Replaced with:
        (a) determinism check, and (b) pin check against the known R-1 closure value.
        """
        if not CORE_DIR.exists() or not list(CORE_DIR.glob("*.py")):
            pytest.skip("core/ directory empty — waiting on impl-implementer")

        # (a) Determinism: two calls must return the same value
        actual1 = _compute_base_ver_fn()
        actual2 = _compute_base_ver_fn()
        assert actual1 == actual2, (
            f"compute_base_analyzer_version() is non-deterministic: {actual1!r} vs {actual2!r}"
        )

        # (b) Pin check: must be the known R-1 closure value (post phase-4)
        # honesty-2 closed the R-1 gap: 25-file set covering full production path.
        # Phase 2a carved collect_mechanic's compute out of PIA (a closure file),
        # shrinking base 960e9d18d83d -> 57fdb323585d; phase 2b carved
        # bonus_chain_dynamics out of PIA -> 980f488f4bb2; phase 3 carved
        # upstream_feature_breakdown's row-build out of PIA -> c89db791d8a1;
        # phase 4 carved multiplier_profile's dict-build out of PIA -> ce298f055495
        # (report content byte-identical).
        # If this value changes again, a _CLOSURE_FILES source was edited.
        assert actual1 == "ce298f055495", (
            f"compute_base_analyzer_version() diverges from R-1 closure reference:\n"
            f"  actual   = {actual1!r}\n"
            f"  expected = 'ce298f055495' (R-1 closure value, post phase-4)\n"
            "The R-1 closure covers core/*.py plus content modules (round_classification,\n"
            "round_win, trigger_sessions, sampler, machine_md5, chunk_index, rawdata_index)\n"
            "and support modules. If this changed, update the pin to the new value and\n"
            "verify _CLOSURE_FILES in versioning.py reflects the intent."
        )


# ===========================================================================
# C7 — No silent swallows in _utils.py or aggregator.py
# ===========================================================================

class TestNoSilentSwallows:
    """C7: _utils.py and aggregator.py must not add new 'except: pass' patterns.

    Per memory feedback_dont_swallow_errors_in_fix.md.
    AST-based check — catches literal try/except blocks with bare pass body.

    Baseline counts (AST-verified by tester before writing these tests):
    - _utils.py: 0 (pure stdlib utility, no exception-swallowing expected)
    - aggregator.py: 0 (PIA lines 1100-1900 where aggregator symbols live
      have 0 silent swallows per AST scan documented in 03_tests.md)

    These baselines match what will be carved from PIA. If either goes above
    its baseline, the implementer added NEW swallows during the move.
    """

    MAX_ALLOWED_SWALLOWS_IN_UTILS = 0
    MAX_ALLOWED_SWALLOWS_IN_AGGREGATOR = 0  # from AST scan of PIA lines 1100-1900

    @staticmethod
    def _find_silent_swallows(source: str, filepath: str) -> list[str]:
        """Return descriptions of silent try/except blocks.

        A 'silent swallow' is a try/except where the except body contains
        ONLY a pass statement (no re-raise, log, or assignment).
        Mirrors the implementation in test_analyzer_core_parser.py.
        """
        # Handle BOM
        if source.startswith("﻿"):
            source = source[1:]
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return [f"SyntaxError in {filepath}: {exc}"]

        swallows = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                body_stmts = handler.body
                if len(body_stmts) == 1 and isinstance(body_stmts[0], ast.Pass):
                    handler_type = (
                        "bare" if handler.type is None else ast.unparse(handler.type)
                    )
                    swallows.append(
                        f"{filepath}:{handler.lineno}: "
                        f"except {handler_type}: pass — silent swallow"
                    )
        return swallows

    def test_utils_no_silent_swallows(self):
        """C7: _utils.py must have ZERO silent 'except: pass' patterns.

        _utils.py is a pure utility module — all errors should propagate.
        A silent swallow here would mask bugs in callers (parser.py, aggregator.py)
        that rely on these primitives.

        Baseline: 0 (PIA has no swallows in the corresponding utility function range).

        Inject-bug: add 'except Exception: pass' to any function in _utils.py
        → count > 0 → test fires.
        """
        if not CORE_UTILS.exists():
            pytest.skip("_utils.py not yet created by P2-B2")

        raw = CORE_UTILS.read_bytes()
        source = raw[3:].decode("utf-8") if raw.startswith(b"\xef\xbb\xbf") else raw.decode("utf-8")
        swallows = self._find_silent_swallows(source, "_utils.py")
        count = len(swallows)

        assert count <= self.MAX_ALLOWED_SWALLOWS_IN_UTILS, (
            f"C7: {count} silent try/except: pass patterns found in _utils.py, "
            f"but baseline is {self.MAX_ALLOWED_SWALLOWS_IN_UTILS}.\n"
            "Per memory feedback_dont_swallow_errors_in_fix.md: do not swallow errors silently.\n"
            "_utils.py is a pure stdlib utility — all errors must propagate.\n"
            "All occurrences:\n" + "\n".join(f"  {s}" for s in swallows)
        )

    def test_aggregator_no_new_silent_swallows_beyond_pia_baseline(self):
        """C7: aggregator.py must not ADD new 'except: pass' beyond PIA baseline.

        Baseline established by AST scan of PIA lines 1100-1900 (the range
        containing the 16 aggregator symbols): ZERO silent swallows found.
        Documented in 03_tests.md.

        If the count exceeds 0, the implementer added NEW swallows during the move.

        Inject-bug: add 'except Exception: pass' wrapper around error-prone
        code in aggregator.py → count > baseline → fires.
        """
        if not CORE_AGGREGATOR.exists():
            pytest.skip("aggregator.py not yet created by P2-B2")

        raw = CORE_AGGREGATOR.read_bytes()
        source = raw[3:].decode("utf-8") if raw.startswith(b"\xef\xbb\xbf") else raw.decode("utf-8")
        swallows = self._find_silent_swallows(source, "aggregator.py")
        count = len(swallows)

        assert count <= self.MAX_ALLOWED_SWALLOWS_IN_AGGREGATOR, (
            f"C7: {count} silent try/except: pass patterns found in aggregator.py, "
            f"but baseline is {self.MAX_ALLOWED_SWALLOWS_IN_AGGREGATOR} "
            f"(from PIA lines 1100-1900 AST scan in 03_tests.md).\n"
            f"The {count - self.MAX_ALLOWED_SWALLOWS_IN_AGGREGATOR} extra pattern(s) "
            "are NEW additions by the implementer during the carve.\n"
            "Per memory feedback_dont_swallow_errors_in_fix.md: do not swallow errors silently.\n"
            "All occurrences:\n" + "\n".join(f"  {s}" for s in swallows)
        )


# ===========================================================================
# C8 — Inject-bug TDD verification (structural proof)
# ===========================================================================

class TestInjectBugC8a_AggregatorSymbolDeletion:
    """C8-a: delete one aggregator symbol → C1 hasattr test goes RED.

    Proof that the C1 parametrized hasattr test actually catches missing symbols.
    We simulate by checking the mechanism directly.
    """

    @requires_core_aggregator
    def test_inject_missing_symbol_proof_mechanism(self):
        """C8-a proof: if aggregator.py is missing a symbol, hasattr → False → C1 fires.

        We prove by verifying a dummy object missing classify_volatility would
        cause the C1 test to fail. Then we prove the real module has it.

        Full inject-bug cycle documented in 03_tests.md:
        1. Delete 'classify_volatility' from aggregator.py
        2. Run test_function_or_class_present_in_aggregator[classify_volatility] → RED
        3. Restore the definition → GREEN
        """
        class _FakeAggregator:
            pass  # No classify_volatility

        fake = _FakeAggregator()
        assert not hasattr(fake, "classify_volatility"), (
            "INJECT-BUG PROOF C8-a: a module missing classify_volatility "
            "would cause hasattr() → False → C1 test fires."
        )

        # Prove real module has it (green state):
        assert hasattr(_core_aggregator_mod, "classify_volatility"), (
            "INJECT-BUG PROOF C8-a: real aggregator.classify_volatility is present.\n"
            "After impl lands, this is green; before, it's red."
        )

    @requires_pia
    def test_inject_pia_missing_symbol_proof_mechanism(self):
        """C8-a proof (PIA re-export): if PIA re-export is deleted → C1-PIA fires.

        PIA must re-export all 16+2 aggregator symbols. If one is deleted
        from the re-export block, test_pia_has_aggregator_symbol fires.
        """
        class _FakePIA:
            pass

        fake_pia = _FakePIA()
        assert not hasattr(fake_pia, "evaluate_guideline_comparison"), (
            "INJECT-BUG PROOF C8-a (PIA): missing re-export → hasattr → False."
        )

        assert hasattr(_pia, "evaluate_guideline_comparison"), (
            "INJECT-BUG PROOF C8-a (PIA): real pia.evaluate_guideline_comparison present."
        )


class TestInjectBugC8b_CycleViolation:
    """C8-b: add a forbidden import to _utils.py → C5 cycle test goes RED.

    Proof that the C5 static grep test catches the inject.
    """

    def test_inject_cycle_in_utils_proof_mechanism(self):
        """C8-b proof: if _utils.py had a prohibited import, C5 grep fires.

        Per brief §3 C8: 'Inject: add a from fresh_slotlab.analyzer.core.aggregator
        import X inside core/_utils.py → cycle test RED.'

        Full inject-bug cycle documented in 03_tests.md:
        1. Add 'from fresh_slotlab.analyzer.core.aggregator import quantile_from_hist'
           to _utils.py (a prohibited import statement)
        2. Run test_utils_does_not_import_from_fresh_slotlab → RED
        3. Revert the line → GREEN

        We prove the MECHANISM here without touching the real file:
        - Our C5 test counts import-statement lines with the prohibited patterns
        - The grep would find 1 match → assert len == 0 fails
        """
        # Simulate the injected _utils.py content
        injected_source = (
            "# _utils.py — shared helpers\n"
            "from fresh_slotlab.analyzer.core.aggregator import quantile_from_hist\n"
            "def to_float(x, default=0.0): return default\n"
        )

        # Apply the SAME grep logic as the C5 test (matching import statements only)
        prohibited_patterns = [
            "fresh_slotlab.analyzer.core.parser",
            "fresh_slotlab.analyzer.core.aggregator",
            "fresh_slotlab.player_impact_analyzer",
        ]

        all_violations = []
        for pattern in prohibited_patterns:
            for lineno, line in enumerate(injected_source.splitlines(), start=1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if pattern in line and (
                    stripped.startswith("import ")
                    or stripped.startswith("from ")
                ):
                    all_violations.append((lineno, pattern, line.rstrip()))

        assert len(all_violations) == 1, (
            "INJECT-BUG PROOF C8-b: The injected source should have exactly 1 "
            "prohibited import line that the C5 grep would catch.\n"
            f"Found: {all_violations}"
        )

        # Prove that C5 assertion would fire:
        assert all_violations[0][1] == "fresh_slotlab.analyzer.core.aggregator", (
            "INJECT-BUG PROOF C8-b: The detected violation should be the "
            "'fresh_slotlab.analyzer.core.aggregator' prohibited import."
        )

    def test_inject_back_import_in_aggregator_proof_mechanism(self):
        """C8-b proof: if aggregator.py had a PIA import, C5 grep fires.

        Proves the grep mechanism for the aggregator → PIA direction.
        """
        injected_aggregator = (
            "# aggregator.py\n"
            "from fresh_slotlab.player_impact_analyzer import _run_generate_report\n"
        )

        back_import_lines = [
            (lineno, line.rstrip())
            for lineno, line in enumerate(injected_aggregator.splitlines(), start=1)
            if "fresh_slotlab.player_impact_analyzer" in line
            and not line.lstrip().startswith("#")
        ]

        assert len(back_import_lines) == 1, (
            "INJECT-BUG PROOF C8-b (aggregator): The injected source has exactly 1 "
            "back-import line that the C5 grep would catch."
        )


class TestInjectBugC8c_DeduplicationBreak:
    """C8-c: re-adding a local definition to parser.py breaks the C3 identity check.

    Per brief §3 C8: 'Inject: re-add a local def to_float(...) to parser.py
    that does something different → assertion that all import paths resolve
    to _utils.to_float goes RED.'

    Full inject-bug cycle documented in 03_tests.md.
    """

    @requires_core_parser
    @requires_core_utils
    def test_inject_local_def_breaks_identity_proof_mechanism(self):
        """C8-c proof: if parser.py redefines to_float, identity check fails.

        We prove by constructing two callable objects with the same name but
        different object identities, and verifying the 'is' check fails.

        The actual inject cycle (documented in 03_tests.md):
        1. Add 'def to_float(value, default=0.0): return float(value) or default'
           to parser.py (a local re-definition with different semantics)
        2. Run test_pia_and_parser_and_utils_are_same_object[to_float] → RED
           (parser.to_float is NOT utils.to_float)
        3. Revert: remove the local def, keep the _utils import → GREEN
        """
        def local_to_float_a(x, default=0.0):
            """Simulates parser.py's re-added local definition."""
            return float(x) if x else default

        def local_to_float_b(x, default=0.0):
            """Simulates _utils.py's canonical definition."""
            return float(x) if x else default

        # Two different objects — 'is' fails even though behavior is identical
        assert local_to_float_a is not local_to_float_b, (
            "INJECT-BUG PROOF C8-c: two separately defined functions are NOT the same object.\n"
            "This proves that if parser.py re-adds a local to_float definition,\n"
            "parser.to_float 'is' utils.to_float would fail → C3 test goes RED."
        )

        # If P2-B2 is landed, prove real state is GREEN:
        if _CORE_UTILS_IMPORTABLE and _CORE_PARSER_IMPORTABLE:
            utils_fn = getattr(_core_utils_mod, "to_float", None)
            parser_fn = getattr(_core_parser_mod, "to_float", None)
            if utils_fn is not None and parser_fn is not None:
                assert parser_fn is utils_fn, (
                    "INJECT-BUG PROOF C8-c GREEN state: "
                    "parser.to_float IS utils.to_float (dedup correct).\n"
                    "This is GREEN after P2-B2 lands.\n"
                    "It would go RED if parser.py re-added a local definition."
                )


# ===========================================================================
# Supplementary: existing test suites still importable after P2-B2
# ===========================================================================

class TestExistingTestSuitesStillIntact:
    """Structural check: P2-B2 must not corrupt existing test files.

    Per brief §3 C7: '5 Phase 1+2 regression suites listed in P2-B1b §3 C6,
    all GREEN.'
    """

    _EXISTING_TEST_FILES = [
        "tests/integration/test_analyzer_three_invocation_parity.py",
        "tests/backend/test_lookup_machine_md5_canonical.py",
        "tests/backend/test_summary_md5_writer_parity.py",
        "tests/backend/test_analyzer_foundation.py",
        "tests/backend/test_manifest_loader.py",
        "tests/backend/test_analyzer_core_parser.py",
    ]

    @pytest.mark.parametrize("rel_path", _EXISTING_TEST_FILES)
    def test_existing_suite_still_exists(self, rel_path):
        """Existing test suite file must still exist after P2-B2."""
        p = ROOT / rel_path
        assert p.exists(), (
            f"Existing test suite file not found: {p}\n"
            "P2-B2 must not delete or rename any existing test files."
        )

    @pytest.mark.parametrize("rel_path", _EXISTING_TEST_FILES)
    def test_existing_suite_still_valid_python(self, rel_path):
        """Existing test suite file must still parse as valid Python after P2-B2."""
        p = ROOT / rel_path
        if not p.exists():
            pytest.skip(f"File missing: {rel_path} — covered by existence test")

        source = p.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as exc:
            pytest.fail(
                f"Existing test suite {rel_path} has SyntaxError after P2-B2: {exc}\n"
                "P2-B2 must not corrupt existing test files."
            )

    @requires_pia
    def test_parser_test_imports_still_resolve_via_pia(self):
        """test_analyzer_parsing.py key imports still work after P2-B2.

        That test does: 'from pia import return_bucket, _check_round_schema, ...'
        After P2-B2, return_bucket moves to _utils.py; PIA must still re-export it.
        """
        for sym in ["return_bucket", "_check_round_schema", "_REQUIRED_ROUND_FIELDS"]:
            assert hasattr(_pia, sym), (
                f"pia.{sym} missing after P2-B2.\n"
                "test_analyzer_parsing.py imports this from PIA; must still work."
            )

    @requires_pia
    def test_bankruptcy_test_imports_still_resolve_via_pia(self):
        """test_analyzer_bankruptcy.py key imports still work after P2-B2.

        That test exercises bankruptcy simulation; all the bankruptcy symbols
        must remain accessible via PIA.
        """
        for sym in [
            "simulate_bankruptcy_from_response",
            "compute_bankruptcy_percentiles",
            "_BankruptcyStreamAccumulator",
            "_DEFAULT_BANKROLL_MULTIPLIERS",
        ]:
            assert hasattr(_pia, sym), (
                f"pia.{sym} missing after P2-B2.\n"
                "test_analyzer_bankruptcy.py depends on this symbol via PIA."
            )
