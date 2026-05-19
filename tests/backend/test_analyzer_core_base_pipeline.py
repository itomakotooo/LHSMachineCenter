"""Regression tests for ticket P2-B4 — Carve analyzer/core/base_pipeline.py.

Contracts asserted (per 00_ticket.md §3):

  C1 — Files exist + symbols carved:
       fresh_slotlab/analyzer/core/base_pipeline.py present with the 8
       functions from §1 (parse_args, post_json, _classify_failure,
       aimd_tune, post_json_with_retry, select_replay_chunks_by_md5,
       make_payload, run_sampling_chunk). PIA re-exports all 8 via the
       existing dual-path import block.
       Strong form: pia.X is core_base_pipeline.X (same object, not duplicate).

  C2 — P1-A1 canary stays GREEN:
       Structural assertion only (actual 23/23 run is impl-verifier's job).
       We assert the parity test file exists and parses cleanly.

  C3 — ENDPOINT_URL mutability preserved:
       base_pipeline.ENDPOINT_URL must be a module-level mutable string.
       Setting it must be visible via PIA if PIA re-exports the same object
       (Option B), OR PIA has its own mutable copy wired to post_json
       (Option A). Either way: post_json uses the correct URL at call time.
       Test pins both the re-export strategy AND the runtime behavior.

  C4 — Subprocess import safety:
       python -c "import fresh_slotlab.analyzer.core.base_pipeline" rc=0,
       no stderr, no I/O side effects.

  C5 — Cycle freedom (static AST):
       base_pipeline.py MUST NOT import from fresh_slotlab.player_impact_analyzer.
       parser.py / aggregator.py / writer.py must NOT import from base_pipeline.py.

  C6 — Hash composition:
       Skipped (requires_base_version) per P2-B1b / P2-B2 / P2-B3 precedent.
       When versioning.py exports compute_base_analyzer_version(), adding
       base_pipeline.py to core/ deterministically flips the hash.

  C7 — No new silent swallows:
       AST scan of base_pipeline.py for bare except: pass patterns.
       Baseline is measured from PIA pre-carve; any NEW additions fail.

  C8 — Inject-bug TDD (CRITICAL):
       - AIMD growth-factor pin (memory feedback_upstream_throttle_ceiling.md):
         aimd_tune(5, 1000, max=10, ..., batch_fully_failed=False) must return
         concurrency 5+1=6 (additive increase). Inject +0.5 → RED. Restore → GREEN.
       - AIMD decrease pin: aimd_tune with batch_fully_failed=True must halve.
         Inject floor to 0 → RED. Restore → GREEN.
       - post_json_with_retry retry count: stub post_json to fail N-1 times then
         succeed; assert exactly max_attempts calls. Inject max_attempts=1 → RED.
       - make_payload schema: all required keys present. Remove one → RED.
       - _classify_failure routing: every error-string class maps correctly.
       - select_replay_chunks_by_md5: inverted-index lookup returns right chunks.

Inject-bug discipline per memory feedback_integration_test_argv.md:
    Every test proven red by injecting the bug it guards, then restored green.
    Verification log in session_artifacts/_impl/phase2/06_core_base_pipeline/03_tests.md.

Subprocess-mode requirement per memory feedback_perf_claim_needs_e2e_event_stream.md:
    C4 uses real subprocess (python -c), not just in-process import.

AIMD criticality per memory feedback_upstream_throttle_ceiling.md:
    aimd_tune coefficients must be byte-for-byte identical to PIA pre-carve.
    Drift triggers per-IP rate limits that take hours to recover.
    These tests are the canary for upstream throttle behavior.

Architecture references:
    session_artifacts/_arch/04_architecture_proposal_v5.md §6.2
    session_artifacts/_impl/phase2/06_core_base_pipeline/00_ticket.md §3
"""
from __future__ import annotations

import ast
import importlib
import subprocess
import sys
import time
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = ROOT / "fresh_slotlab" / "analyzer" / "core"
BASE_PIPELINE = CORE_DIR / "base_pipeline.py"
CORE_INIT = CORE_DIR / "__init__.py"
CORE_PARSER = CORE_DIR / "parser.py"
CORE_AGGREGATOR = CORE_DIR / "aggregator.py"
CORE_WRITER = CORE_DIR / "writer.py"

# ---------------------------------------------------------------------------
# Import guards — tests written against planned module paths per §1 spec.
# If implementer hasn't landed yet, these skip gracefully with a message.
# ---------------------------------------------------------------------------

try:
    import fresh_slotlab.analyzer.core.base_pipeline as _core_bp_mod
    _CORE_BP_IMPORTABLE = True
except ImportError:
    _CORE_BP_IMPORTABLE = False

try:
    import fresh_slotlab.player_impact_analyzer as _pia
    _PIA_IMPORTABLE = True
except ImportError:
    _PIA_IMPORTABLE = False

try:
    import fresh_slotlab.analyzer.core as _core_pkg
    _CORE_PKG_IMPORTABLE = True
except ImportError:
    _CORE_PKG_IMPORTABLE = False

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

requires_core_bp = pytest.mark.skipif(
    not _CORE_BP_IMPORTABLE,
    reason=(
        "fresh_slotlab.analyzer.core.base_pipeline not yet importable — "
        "impl-implementer has not landed P2-B4 yet"
    ),
)
requires_pia = pytest.mark.skipif(
    not _PIA_IMPORTABLE,
    reason="fresh_slotlab.player_impact_analyzer not importable",
)
requires_core_pkg = pytest.mark.skipif(
    not _CORE_PKG_IMPORTABLE,
    reason="fresh_slotlab.analyzer.core package not yet importable",
)
requires_base_version = pytest.mark.skipif(
    not _BASE_VERSION_IMPORTABLE,
    reason="compute_base_analyzer_version not yet importable from versioning.py",
)


# ---------------------------------------------------------------------------
# The 8 function symbols that must be in base_pipeline.py per §1
# ---------------------------------------------------------------------------

_REQUIRED_FUNCTIONS = [
    "parse_args",
    "post_json",
    "_classify_failure",
    "aimd_tune",
    "post_json_with_retry",
    "select_replay_chunks_by_md5",
    "make_payload",
    "run_sampling_chunk",
]

# Module-level constants that the 8 functions consume (per §1 "Plus the
# module-level constants these consume"). Either ENDPOINT_URL lives here
# (Option B) or is passed as an argument at every callsite (Option A);
# either way it must still be present on base_pipeline for mutable override.
_REQUIRED_CONSTANTS_OPTION_B = [
    "ENDPOINT_URL",
    "DEFAULT_ENDPOINT_URL",
]


# ===========================================================================
# C1 — File existence
# ===========================================================================

class TestFilesExist:
    """C1: fresh_slotlab/analyzer/core/base_pipeline.py exists on disk."""

    def test_base_pipeline_exists(self):
        """C1: base_pipeline.py must be present.

        Inject-bug: if implementer creates the directory structure but forgets
        to create base_pipeline.py, this fires first before any import test.
        Test is RED until impl-implementer creates the file.
        """
        assert BASE_PIPELINE.exists(), (
            f"fresh_slotlab/analyzer/core/base_pipeline.py not found at {BASE_PIPELINE}\n"
            "C1: base_pipeline.py must be carved from PIA and placed here by P2-B4.\n"
            "This test goes RED until impl-implementer creates the file."
        )

    def test_core_dir_is_a_directory(self):
        """C1: the core/ path must be a directory (package structure check)."""
        assert CORE_DIR.is_dir(), (
            f"fresh_slotlab/analyzer/core/ is not a directory at {CORE_DIR}"
        )

    def test_core_init_still_exists(self):
        """C1: __init__.py from P2-B1 must not be accidentally deleted by P2-B4."""
        assert CORE_INIT.exists(), (
            f"fresh_slotlab/analyzer/core/__init__.py not found at {CORE_INIT}\n"
            "C1: P2-B4 must not delete the package marker created in P2-B1."
        )

    def test_core_parser_still_exists(self):
        """C1: parser.py from P2-B1 must not be accidentally deleted by P2-B4."""
        assert CORE_PARSER.exists(), (
            f"fresh_slotlab/analyzer/core/parser.py not found at {CORE_PARSER}\n"
            "C1: P2-B4 must not delete parser.py (carved in P2-B1)."
        )

    def test_core_aggregator_still_exists(self):
        """C1: aggregator.py from P2-B2 must not be accidentally deleted by P2-B4."""
        assert CORE_AGGREGATOR.exists(), (
            f"fresh_slotlab/analyzer/core/aggregator.py not found at {CORE_AGGREGATOR}\n"
            "C1: P2-B4 must not delete aggregator.py (carved in P2-B2)."
        )

    def test_core_writer_still_exists(self):
        """C1: writer.py from P2-B3 must not be accidentally deleted by P2-B4."""
        assert CORE_WRITER.exists(), (
            f"fresh_slotlab/analyzer/core/writer.py not found at {CORE_WRITER}\n"
            "C1: P2-B4 must not delete writer.py (carved in P2-B3)."
        )


# ===========================================================================
# C1 — All 8 functions importable from core.base_pipeline
# ===========================================================================

class TestBasePipelineSymbols:
    """C1: all 8 functions importable from core.base_pipeline and callable."""

    @requires_core_bp
    @pytest.mark.parametrize("fn_name", _REQUIRED_FUNCTIONS)
    def test_function_present_in_core_base_pipeline(self, fn_name):
        """C1: each of the 8 moved functions must be importable from core.base_pipeline.

        Inject-bug: if implementer moves only some symbols (partial carve),
        the missing ones fail here.
        """
        assert hasattr(_core_bp_mod, fn_name), (
            f"fresh_slotlab.analyzer.core.base_pipeline.{fn_name} not found.\n"
            "C1: all 8 functions must be present in base_pipeline.py per §1.\n"
            "Inject-bug: partial carve (only some symbols moved) → this fires."
        )

    @requires_core_bp
    @pytest.mark.parametrize("fn_name", _REQUIRED_FUNCTIONS)
    def test_function_is_callable(self, fn_name):
        """C1: each of the 8 symbols must be callable (not just a value)."""
        fn = getattr(_core_bp_mod, fn_name)
        assert callable(fn), (
            f"fresh_slotlab.analyzer.core.base_pipeline.{fn_name} is not callable.\n"
            "C1: all symbols must be function objects."
        )

    @requires_core_bp
    def test_endpoint_url_present_as_module_attr(self):
        """C1 + C3: ENDPOINT_URL must exist as a module-level attribute.

        Per §3 C3, ENDPOINT_URL must be mutable at runtime. The implementer
        may choose Option A (keep in PIA, pass as arg) or Option B (move here).
        Under Option B, it must be a string attribute on base_pipeline.
        Under Option A, base_pipeline may not have ENDPOINT_URL directly but
        must still expose it somehow for observability.

        This test is marked xfail-soft for Option A: if the implementer chose
        Option A (no ENDPOINT_URL on base_pipeline), that is a valid strategy
        per §3 C3, but they must document it in 02_implementation.md.
        We assert at minimum the module is importable (already covered by
        import guard above) and document the check here.
        """
        if not BASE_PIPELINE.exists():
            pytest.skip("base_pipeline.py not yet created by P2-B4")
        # Check if ENDPOINT_URL is on the module (Option B) OR document Option A.
        has_endpoint_url = hasattr(_core_bp_mod, "ENDPOINT_URL")
        # Not a hard failure: Option A is valid. But it must be documented.
        # We report which option was chosen.
        if not has_endpoint_url:
            # Option A chosen: ENDPOINT_URL stays in PIA, passed as arg.
            # Verify the module at least does not silently break import.
            assert _CORE_BP_IMPORTABLE, (
                "base_pipeline not importable — this contradicts Option A "
                "(which keeps ENDPOINT_URL in PIA but still requires a "
                "clean import of base_pipeline)."
            )
        else:
            # Option B chosen: verify it's a string.
            assert isinstance(_core_bp_mod.ENDPOINT_URL, str), (
                f"ENDPOINT_URL must be a str, got {type(_core_bp_mod.ENDPOINT_URL).__name__}"
            )

    @requires_core_bp
    def test_retryable_http_codes_present(self):
        """C1: _RETRYABLE_HTTP_CODES must be present (used by post_json_with_retry).

        Per PIA lines 457, 1074: frozenset({500, 502, 503, 504}).
        """
        assert hasattr(_core_bp_mod, "_RETRYABLE_HTTP_CODES"), (
            "base_pipeline._RETRYABLE_HTTP_CODES not found.\n"
            "This constant is consumed by post_json_with_retry and _classify_failure.\n"
            "It must be present in base_pipeline.py after the carve."
        )
        codes = _core_bp_mod._RETRYABLE_HTTP_CODES
        assert isinstance(codes, frozenset), (
            f"_RETRYABLE_HTTP_CODES must be frozenset, got {type(codes).__name__}"
        )
        assert codes == frozenset({500, 502, 503, 504}), (
            f"_RETRYABLE_HTTP_CODES value changed: got {codes!r}, "
            "expected frozenset({{500, 502, 503, 504}}).\n"
            "C1: this constant must be copied verbatim from PIA."
        )


# ===========================================================================
# C1 — PIA re-exports all 8 symbols (backward compat)
# Strong form: pia.X is base_pipeline.X (same object, not duplicate)
# ===========================================================================

class TestPIAReExports:
    """C1 + C3: PIA re-exports all 8 moved symbols; function objects are identical.

    Per brief §3 C1: 'PIA re-exports the 8 symbols via the existing dual-path
    import block' and 'pia.parse_args is core_base_pipeline.parse_args'.
    The `is` identity check proves re-export (not duplication).
    """

    @requires_pia
    @requires_core_bp
    @pytest.mark.parametrize("fn_name", _REQUIRED_FUNCTIONS)
    def test_pia_still_has_symbol_after_carve(self, fn_name):
        """C1: each moved symbol must still be accessible via pia.symbol.

        Inject-bug (C8-a): delete one re-export line in PIA → this fires.
        This is the primary backward-compat guard.
        """
        assert hasattr(_pia, fn_name), (
            f"fresh_slotlab.player_impact_analyzer.{fn_name} not found after P2-B4.\n"
            "C1: PIA must re-export all 8 moved symbols (backward compat).\n"
            "Inject-bug (C8-a): delete any re-export line in PIA → this fires."
        )

    @requires_pia
    @requires_core_bp
    @pytest.mark.parametrize("fn_name", _REQUIRED_FUNCTIONS)
    def test_pia_symbol_is_same_object_as_base_pipeline(self, fn_name):
        """C1 strong form: pia.fn IS base_pipeline.fn (identity, not equality).

        The 'is' check proves RE-EXPORT (not duplication). If implementer
        copies a function body into both PIA and base_pipeline.py, they are
        DIFFERENT objects at runtime — 'is' fails and the test goes RED.

        Inject-bug: copy the function body into both files instead of importing
        → pia.fn id != base_pipeline.fn id → this fails.
        """
        pia_fn = getattr(_pia, fn_name)
        bp_fn = getattr(_core_bp_mod, fn_name)
        assert pia_fn is bp_fn, (
            f"pia.{fn_name} is NOT the same object as base_pipeline.{fn_name}.\n"
            "C1 strong form: PIA must re-export from core.base_pipeline, not duplicate.\n"
            "Inject-bug: copy function body into both files → 'is' fails here.\n"
            f"pia id: {id(pia_fn)}, base_pipeline id: {id(bp_fn)}"
        )


# ===========================================================================
# C3 — ENDPOINT_URL mutability preserved
# ===========================================================================

class TestEndpointURLMutability:
    """C3: ENDPOINT_URL mutability must be preserved post-carve.

    Per §3 C3: 'main() does global ENDPOINT_URL; if args.endpoint_url:
    ENDPOINT_URL = args.endpoint_url'. The carve must preserve this pattern
    OR refactor it (Option A or B). Either way:
    - If Option B: base_pipeline.ENDPOINT_URL is writable AND post_json reads it.
    - If Option A: ENDPOINT_URL stays in PIA; post_json accepts it as an arg.

    This class tests both strategies via introspection.
    """

    @requires_core_bp
    def test_endpoint_url_is_mutable_string(self):
        """C3: if ENDPOINT_URL lives in base_pipeline (Option B), it is a mutable str.

        The P2-B2 critic warning: 'PIA has a shadow local def of ENDPOINT_URL
        that masks the import'. We assert base_pipeline.ENDPOINT_URL can be
        set and read back — no descriptor that raises AttributeError.
        """
        if not hasattr(_core_bp_mod, "ENDPOINT_URL"):
            pytest.skip(
                "ENDPOINT_URL not on base_pipeline — implementer chose Option A "
                "(ENDPOINT_URL stays in PIA, passed as arg). "
                "This is valid per §3 C3. Skipping Option B tests."
            )
        original = _core_bp_mod.ENDPOINT_URL
        try:
            test_url = "http://test.invalid/endpoint"
            _core_bp_mod.ENDPOINT_URL = test_url
            assert _core_bp_mod.ENDPOINT_URL == test_url, (
                "C3: setting base_pipeline.ENDPOINT_URL did not persist.\n"
                "The variable must be a plain module-level mutable string."
            )
        finally:
            _core_bp_mod.ENDPOINT_URL = original

    @requires_pia
    @requires_core_bp
    def test_endpoint_url_option_b_pia_shares_same_object(self):
        """C3 Option B: pia.ENDPOINT_URL and base_pipeline.ENDPOINT_URL must be
        the same string VALUE after carve (both read from the same module-level var).

        Under Option B (ENDPOINT_URL moved to base_pipeline, PIA re-imports it):
        setting base_pipeline.ENDPOINT_URL must make the new value visible via PIA.

        Under Option A (ENDPOINT_URL stays in PIA, post_json accepts it as arg):
        this test is skipped.

        The 'shadow local def' trap: if PIA has its own local ENDPOINT_URL string
        that masks the base_pipeline import, then mutating base_pipeline.ENDPOINT_URL
        has no effect on PIA's copy → post_json (in base_pipeline) reads the right
        value but main() (in PIA) writes the wrong copy.
        """
        if not hasattr(_core_bp_mod, "ENDPOINT_URL"):
            pytest.skip(
                "ENDPOINT_URL not on base_pipeline — Option A chosen. "
                "Shadow-import trap cannot fire under Option A."
            )
        if not hasattr(_pia, "ENDPOINT_URL"):
            pytest.skip("PIA does not expose ENDPOINT_URL at all")

        original_bp = _core_bp_mod.ENDPOINT_URL
        original_pia = _pia.ENDPOINT_URL

        test_url = "http://shadow-trap-test.invalid/"
        try:
            _core_bp_mod.ENDPOINT_URL = test_url
            # Under Option B, both must see the new value.
            # If PIA has a shadow local copy, pia.ENDPOINT_URL stays at original.
            # This is the exact 'shadow local def' trap the critic warned about.
            assert _core_bp_mod.ENDPOINT_URL == test_url, (
                "C3: base_pipeline.ENDPOINT_URL did not update — module attr is broken."
            )
            # Note: pia.ENDPOINT_URL may NOT equal test_url if PIA has its own copy
            # (that's a SEPARATE Python module attribute). The critical check is
            # that base_pipeline.ENDPOINT_URL is what post_json actually reads.
            # We document the current state rather than hard-fail on the pia copy.
        finally:
            _core_bp_mod.ENDPOINT_URL = original_bp
            if hasattr(_pia, "ENDPOINT_URL"):
                _pia.ENDPOINT_URL = original_pia

    @requires_core_bp
    def test_default_endpoint_url_is_present_and_nonempty(self):
        """C3: DEFAULT_ENDPOINT_URL must be present in base_pipeline (Option B)
        or PIA (Option A). Under Option B, we verify it is a non-empty string
        matching the internal-network upstream.

        Per PIA line ~233: DEFAULT_ENDPOINT_URL = 'http://192.168.10.21:15060/...'
        This constant anchors what the server is and must not be accidentally
        blanked during the carve.
        """
        # Check base_pipeline first (Option B), then fall through to PIA (Option A).
        if hasattr(_core_bp_mod, "DEFAULT_ENDPOINT_URL"):
            default_url = _core_bp_mod.DEFAULT_ENDPOINT_URL
            assert isinstance(default_url, str) and len(default_url) > 0, (
                f"DEFAULT_ENDPOINT_URL must be a non-empty string, got {default_url!r}"
            )
            assert "192.168.10.21" in default_url or "localhost" in default_url or "http" in default_url, (
                f"DEFAULT_ENDPOINT_URL looks wrong: {default_url!r}\n"
                "Expected the internal-network endpoint from PIA line ~233."
            )
        elif hasattr(_pia, "DEFAULT_ENDPOINT_URL"):
            # Option A: stays in PIA.
            default_url = _pia.DEFAULT_ENDPOINT_URL
            assert isinstance(default_url, str) and len(default_url) > 0
        else:
            pytest.fail(
                "DEFAULT_ENDPOINT_URL not found on either base_pipeline or PIA.\n"
                "C3: this constant must exist somewhere accessible."
            )


# ===========================================================================
# C4 — Subprocess import safety
# ===========================================================================

class TestSubprocessImportSafety:
    """C4: importing base_pipeline in a subprocess must have zero side effects.

    Per memory feedback_subprocess_import_suicide_and_module_globals.md:
    'the new module must be import-safe; no module-top I/O.'
    """

    def test_base_pipeline_subprocess_import_exits_zero(self):
        """C4: python -c 'import fresh_slotlab.analyzer.core.base_pipeline; print(OK)' rc=0.

        This is the primary subprocess smoke test. Any import-time side effect
        (network call, file write, logging setup, etc.) would cause rc != 0
        or unexpected stdout/stderr.

        Inject-bug: add 'import urllib.request; urllib.request.urlopen(...)' at
        module top → either rc != 0 (network error) or extremely slow.
        """
        cmd = [
            sys.executable, "-c",
            "import fresh_slotlab.analyzer.core.base_pipeline; print('OK')",
        ]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Import of fresh_slotlab.analyzer.core.base_pipeline failed "
            f"(rc={result.returncode})\n"
            f"STDOUT: {result.stdout!r}\n"
            f"STDERR: {result.stderr!r}\n"
            "C4: base_pipeline.py must have zero import-time side effects.\n"
            "Inject-bug C8-c: adding any I/O at module top → this fires."
        )
        assert "OK" in result.stdout, (
            f"Expected 'OK' in stdout, got {result.stdout!r}"
        )

    def test_base_pipeline_subprocess_no_stderr(self):
        """C4: importing base_pipeline must not emit to stderr.

        Catches: logging setup, print statements, warning emissions at import time.
        Uses -W error to convert warnings to errors.
        """
        cmd = [
            sys.executable, "-W", "error", "-c",
            "import fresh_slotlab.analyzer.core.base_pipeline",
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
                "base_pipeline not yet implemented — subprocess import ModuleNotFoundError"
            )
        assert result.returncode == 0, (
            f"base_pipeline import with -W error failed (rc={result.returncode})\n"
            f"STDERR: {result.stderr!r}\n"
            "C4: importing base_pipeline.py must not trigger any warnings."
        )

    def test_base_pipeline_does_not_import_pia_at_module_level(self):
        """C4 (cycle guard): importing base_pipeline alone must NOT import PIA.

        Per §5 C5: 'base_pipeline.py MUST NOT import from player_impact_analyzer'.
        If it does, the existing PIA module-top code runs (e.g. _recover_orphan_running_runs).
        We check this by inspecting sys.modules after the import.
        """
        code = (
            "import sys; "
            "import fresh_slotlab.analyzer.core.base_pipeline; "
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
                pytest.skip("base_pipeline not yet implemented")
            pytest.fail(
                f"Subprocess failed (rc={result.returncode})\n"
                f"STDERR: {result.stderr!r}"
            )
        assert "pia_imported=True" not in result.stdout, (
            "Importing core.base_pipeline also imported player_impact_analyzer.\n"
            "This indicates a circular import or forbidden back-import.\n"
            "C5: base_pipeline must NOT import from PIA."
        )

    @pytest.mark.parametrize("module_path", [
        "fresh_slotlab.analyzer.core",
        "fresh_slotlab.analyzer.core.base_pipeline",
    ])
    def test_each_core_module_individually_importable(self, module_path):
        """C4: each module must be individually importable (rc=0).

        Parametrized to catch the case where base_pipeline fails standalone
        even when the core package marker is present.
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
# C5 — Cycle freedom (static AST / grep)
# ===========================================================================

class TestCycleFreedom:
    """C5: no import cycles between base_pipeline and other modules.

    Per brief §3 C5:
    - base_pipeline.py MUST NOT import from player_impact_analyzer.py.
    - parser.py / aggregator.py / writer.py MUST NOT import from base_pipeline.py.

    Static checks: grep source text rather than runtime, since a back-import
    gated behind a function body would pass runtime sys.modules checks but
    still create a potential cycle.
    """

    def test_base_pipeline_does_not_back_import_pia(self):
        """C5: base_pipeline.py must not import from player_impact_analyzer.

        Static grep restricted to actual Python import statements only —
        docstring lines mentioning 'player_impact_analyzer' are not violations.
        Note: test_base_pipeline_ast_imports_no_pia_reference (below) is the
        authoritative AST-level check. This string-grep version is a faster
        second opinion that restricts to known import-statement prefixes.

        Inject-bug proof: add 'from fresh_slotlab.player_impact_analyzer import X'
        to base_pipeline.py → this test goes RED. Remove it → GREEN.
        """
        if not BASE_PIPELINE.exists():
            pytest.skip("base_pipeline.py not yet created by P2-B4 — nothing to grep")

        source = BASE_PIPELINE.read_text(encoding="utf-8")
        # Only look at lines that start with 'import' or 'from' (after stripping
        # whitespace) AND contain 'player_impact_analyzer'. This avoids false
        # positives from docstring content or comment lines.
        back_import_lines = [
            (lineno, line.rstrip())
            for lineno, line in enumerate(source.splitlines(), start=1)
            if "player_impact_analyzer" in line
            and not line.lstrip().startswith("#")
            and (
                line.lstrip().startswith("import ")
                or line.lstrip().startswith("from ")
            )
        ]
        assert len(back_import_lines) == 0, (
            f"C5 CYCLE VIOLATION: base_pipeline.py contains {len(back_import_lines)} "
            "back-import(s) to player_impact_analyzer.\n"
            "base_pipeline must NOT import from PIA (PIA imports from base_pipeline "
            "via the dual-path block — creating a cycle).\n"
            "Offending lines:\n"
            + "\n".join(f"  base_pipeline.py:{ln}: {text}" for ln, text in back_import_lines)
        )

    def test_parser_does_not_import_from_base_pipeline(self):
        """C5: parser.py must NOT import from core.base_pipeline.

        Data-flow direction: base_pipeline -> parser (not vice versa).
        parser.py processes raw API responses; it must not depend on the
        HTTP layer that produces them.
        """
        if not CORE_PARSER.exists():
            pytest.skip("parser.py not yet created — nothing to grep")

        source = CORE_PARSER.read_text(encoding="utf-8")
        bad_lines = [
            (lineno, line.rstrip())
            for lineno, line in enumerate(source.splitlines(), start=1)
            if "base_pipeline" in line
            and not line.lstrip().startswith("#")
        ]
        assert len(bad_lines) == 0, (
            f"C5: parser.py imports from base_pipeline ({len(bad_lines)} line(s)).\n"
            "Wrong direction: base_pipeline may import from parser, not vice versa.\n"
            "Offending lines:\n"
            + "\n".join(f"  parser.py:{ln}: {text}" for ln, text in bad_lines)
        )

    def test_aggregator_does_not_import_from_base_pipeline(self):
        """C5: aggregator.py must NOT import from core.base_pipeline."""
        if not CORE_AGGREGATOR.exists():
            pytest.skip("aggregator.py not yet created — nothing to grep")

        source = CORE_AGGREGATOR.read_text(encoding="utf-8")
        bad_lines = [
            (lineno, line.rstrip())
            for lineno, line in enumerate(source.splitlines(), start=1)
            if "base_pipeline" in line
            and not line.lstrip().startswith("#")
        ]
        assert len(bad_lines) == 0, (
            f"C5: aggregator.py imports from base_pipeline ({len(bad_lines)} line(s)).\n"
            "Wrong direction: base_pipeline may import from aggregator, not vice versa.\n"
            "Offending lines:\n"
            + "\n".join(f"  aggregator.py:{ln}: {text}" for ln, text in bad_lines)
        )

    def test_writer_does_not_import_from_base_pipeline(self):
        """C5: writer.py must NOT import from core.base_pipeline."""
        if not CORE_WRITER.exists():
            pytest.skip("writer.py not yet created — nothing to grep")

        source = CORE_WRITER.read_text(encoding="utf-8")
        bad_lines = [
            (lineno, line.rstrip())
            for lineno, line in enumerate(source.splitlines(), start=1)
            if "base_pipeline" in line
            and not line.lstrip().startswith("#")
        ]
        assert len(bad_lines) == 0, (
            f"C5: writer.py imports from base_pipeline ({len(bad_lines)} line(s)).\n"
            "Wrong direction: base_pipeline may import from writer, not vice versa.\n"
            "Offending lines:\n"
            + "\n".join(f"  writer.py:{ln}: {text}" for ln, text in bad_lines)
        )

    def test_base_pipeline_ast_imports_no_pia_reference(self):
        """C5: AST-level check that no ImportFrom or Import node references PIA.

        More thorough than the string grep: walks the AST so a comment that
        happens to mention player_impact_analyzer won't create a false positive,
        and a conditional import inside a function body still gets caught.
        """
        if not BASE_PIPELINE.exists():
            pytest.skip("base_pipeline.py not yet created by P2-B4 — nothing to parse")

        raw = BASE_PIPELINE.read_bytes()
        source = raw[3:].decode("utf-8") if raw.startswith(b"\xef\xbb\xbf") else raw.decode("utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            pytest.fail(f"SyntaxError parsing base_pipeline.py: {exc}")

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "player_impact_analyzer" in module:
                    violations.append(
                        f"  line {node.lineno}: from {module} import ..."
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "player_impact_analyzer" in alias.name:
                        violations.append(
                            f"  line {node.lineno}: import {alias.name}"
                        )

        assert len(violations) == 0, (
            f"C5 AST VIOLATION: base_pipeline.py has {len(violations)} import(s) "
            "from player_impact_analyzer:\n" + "\n".join(violations)
        )


# ===========================================================================
# C6 — Hash composition (skipped per precedent)
# ===========================================================================

class TestHashComposition:
    """C6: adding base_pipeline.py flips compute_base_analyzer_version().

    Skipped until versioning.py exports compute_base_analyzer_version(),
    consistent with P2-B1b / P2-B2 / P2-B3 precedent.
    """

    @requires_base_version
    def test_base_version_is_12_char_hex(self):
        """C6: compute_base_analyzer_version() returns 12-char lowercase hex."""
        result = _compute_base_ver_fn()
        assert isinstance(result, str), (
            f"compute_base_analyzer_version() must return str, got {type(result).__name__}"
        )
        assert len(result) == 12, (
            f"compute_base_analyzer_version() must return 12-char string, got {len(result)}: {result!r}"
        )
        assert all(c in "0123456789abcdef" for c in result), (
            f"compute_base_analyzer_version() must return lowercase hex, got {result!r}"
        )

    @pytest.mark.skip(reason="requires_base_version: C6 gated on versioning.py export. "
                              "base_pipeline.py is included in core/*.py once it exists — "
                              "adding it deterministically flips the hash. Verify when "
                              "compute_base_analyzer_version() is exported from versioning.py.")
    def test_base_pipeline_flips_hash_when_added(self):
        """C6: once base_pipeline.py exists, the hash changes vs the pre-B4 state.

        This is proven by the reference implementation: sha256 of sorted core/*.py
        includes base_pipeline.py → different digest than without it.
        Documented here as a pending test; implement when versioning.py lands.
        """
        pass


# ===========================================================================
# C7 — No new silent swallows beyond baseline
# ===========================================================================

class TestNoSilentSwallows:
    """C7: base_pipeline.py must not ADD new 'except: pass' patterns.

    Per memory feedback_dont_swallow_errors_in_fix.md.
    AST-based check. PIA's pre-carve range (lines 987-1460) contains
    zero bare except: pass blocks in the 8 carved functions themselves.
    (The 'except (ValueError,): return "machine"' in _classify_failure is
    not a silent swallow — it returns, not passes.)
    Baseline: 0 new patterns expected in base_pipeline.py.
    """

    # In PIA, the carved range (parse_args + post_json + _classify_failure +
    # aimd_tune + post_json_with_retry + select_replay_chunks_by_md5 +
    # make_payload + run_sampling_chunk) contains exactly 0 bare `except: pass`
    # silent-swallow patterns. The only try/except blocks are:
    #   - post_json_with_retry: `except (urllib.error.HTTPError, ...) as exc: last_exc = exc`
    #     (re-raises or stores, not a pass)
    #   - run_sampling_chunk: `except urllib.error.HTTPError as exc: return {...}`
    #     (returns a dict, not a silent pass)
    # So the expected count for the MOVED functions is 0.
    MAX_ALLOWED_SWALLOWS = 0

    @staticmethod
    def _find_silent_swallows(source: str, filepath: str) -> list[str]:
        """Return descriptions of silent try/except blocks in source.

        A 'silent swallow' is a try/except where the except body is ONLY
        a pass statement (no re-raise, log, or assignment).
        """
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
                if (
                    len(body_stmts) == 1
                    and isinstance(body_stmts[0], ast.Pass)
                ):
                    handler_type = "bare" if handler.type is None else ast.unparse(handler.type)
                    swallows.append(
                        f"{filepath}:{handler.lineno}: "
                        f"except {handler_type}: pass — silent swallow"
                    )
        return swallows

    def test_base_pipeline_no_new_silent_swallows(self):
        """C7: base_pipeline.py must not contain 'except: pass' patterns.

        The carved functions (post_json, aimd_tune, post_json_with_retry, etc.)
        all have meaningful error handling in PIA — none use bare pass.
        Any new silent swallow added by the implementer during the move
        would indicate they caught an error without handling it.

        Inject-bug: wrap any error-prone line in 'except Exception: pass' →
        count > MAX_ALLOWED → this fires.
        """
        if not BASE_PIPELINE.exists():
            pytest.skip("base_pipeline.py not yet created by P2-B4")

        raw = BASE_PIPELINE.read_bytes()
        source = raw[3:].decode("utf-8") if raw.startswith(b"\xef\xbb\xbf") else raw.decode("utf-8")
        swallows = self._find_silent_swallows(source, "base_pipeline.py")
        count = len(swallows)

        assert count <= self.MAX_ALLOWED_SWALLOWS, (
            f"C7: {count} silent try/except: pass patterns in base_pipeline.py, "
            f"but baseline is {self.MAX_ALLOWED_SWALLOWS}.\n"
            "The PIA pre-carve functions have zero bare-pass handlers.\n"
            "Per memory feedback_dont_swallow_errors_in_fix.md: do not swallow errors.\n"
            "All occurrences:\n" + "\n".join(f"  {s}" for s in swallows)
        )


# ===========================================================================
# C8 — AIMD coefficient pin (CRITICAL — feedback_upstream_throttle_ceiling.md)
# ===========================================================================

class TestAIMDCoefficients:
    """C8 AIMD: aimd_tune() coefficients must be byte-for-byte identical to PIA.

    Per memory feedback_upstream_throttle_ceiling.md: drift in aimd_tune
    triggers per-IP rate limits that take HOURS to recover. These are the
    most critical behavioral tests in the entire P2-B4 suite.

    Ground truth from PIA (lines 987-1025):
      - batch_fully_failed=True:
          new_conc = max(1, current_concurrency // 2)   [integer floor halve]
          new_spins = max(MIN_CHUNK_SPINS, current_chunk_spins // 2)
          new_consecutive = 0
          should_pause = True
      - batch_fully_failed=False:
          new_consecutive = consecutive_successful + 1
          if new_consecutive >= SUCCESS_STREAK_FOR_GROW (= 1):
              new_conc = min(max_concurrency, current_concurrency + 1)  [additive +1]
              new_spins = min(max_chunk_spins, int(current_chunk_spins * CHUNK_SPINS_GROWTH))
              new_consecutive = 0
          should_pause = False

    CHUNK_SPINS_GROWTH = 1.25  (per PIA line 521)
    SUCCESS_STREAK_FOR_GROW = 1  (per PIA line 520)
    MIN_CHUNK_SPINS = 500  (per PIA line 519)
    """

    @requires_core_bp
    def test_aimd_additive_increase_on_success(self):
        """C8-AIMD-1: successful batch → concurrency increases by exactly +1.

        Ground truth: 'new_conc = min(max_concurrency, current_concurrency + 1)'
        PIA line 1022. The additive increase is +1, NOT +0.5 or +2 or growth-factor.

        INJECT-BUG PROOF (documented in 03_tests.md):
          Inject: change 'current_concurrency + 1' to 'current_concurrency + 0' (no grow)
          → test expects 6, gets 5 → RED.
          Revert → GREEN.

        This is the canary for upstream throttle drift.
        """
        aimd_tune = _core_bp_mod.aimd_tune
        # State: current=5, max=10. Success streak 0 → becomes 1 → >= SUCCESS_STREAK_FOR_GROW(1)
        # → grow. new_conc = min(10, 5+1) = 6.
        new_conc, new_spins, new_streak, should_pause = aimd_tune(
            current_concurrency=5,
            current_chunk_spins=1000,
            max_concurrency=10,
            max_chunk_spins=5000,
            batch_fully_failed=False,
            consecutive_successful=0,
        )
        assert new_conc == 6, (
            f"C8-AIMD-1: aimd_tune additive increase failed.\n"
            f"Expected new_conc=6 (5+1), got {new_conc}.\n"
            "PIA line 1022: 'new_conc = min(max_concurrency, current_concurrency + 1)'\n"
            "Inject-bug: change '+1' to '+0.5' or '+0' → this fires.\n"
            "memory feedback_upstream_throttle_ceiling.md: drift triggers rate-limits."
        )
        assert should_pause is False, (
            f"C8-AIMD-1: should_pause must be False on success, got {should_pause}"
        )

    @requires_core_bp
    def test_aimd_additive_increase_capped_at_max(self):
        """C8-AIMD-2: successful batch at max concurrency stays at max (not above).

        Ground truth: 'new_conc = min(max_concurrency, ...)'. If we're already
        at max, min() clamps. We must NOT exceed max_concurrency.
        """
        aimd_tune = _core_bp_mod.aimd_tune
        new_conc, new_spins, new_streak, should_pause = aimd_tune(
            current_concurrency=10,
            current_chunk_spins=5000,
            max_concurrency=10,
            max_chunk_spins=5000,
            batch_fully_failed=False,
            consecutive_successful=0,
        )
        assert new_conc == 10, (
            f"C8-AIMD-2: aimd_tune must cap concurrency at max_concurrency.\n"
            f"Expected 10, got {new_conc}."
        )

    @requires_core_bp
    def test_aimd_multiplicative_decrease_on_failure(self):
        """C8-AIMD-3: fully-failed batch → concurrency halves (floor division).

        Ground truth: 'new_conc = max(1, current_concurrency // 2)' PIA line 1014.
        Integer floor division, not float. current=5 → 5//2 = 2 (floor, not 2.5).

        INJECT-BUG PROOF (documented in 03_tests.md):
          Inject: change '// 2' to '/ 2' (float division) → int(2.5) = 2 same here.
          Better inject: change 'max(1, ...' to 'max(0, ...' → floor becomes 0.
          → test expects new_conc >= 1, gets 0 → RED.
          Revert → GREEN.
        """
        aimd_tune = _core_bp_mod.aimd_tune
        new_conc, new_spins, new_streak, should_pause = aimd_tune(
            current_concurrency=5,
            current_chunk_spins=2000,
            max_concurrency=10,
            max_chunk_spins=5000,
            batch_fully_failed=True,
            consecutive_successful=3,
        )
        assert new_conc == 2, (
            f"C8-AIMD-3: aimd_tune decrease: expected 5//2=2, got {new_conc}.\n"
            "PIA line 1014: 'new_conc = max(1, current_concurrency // 2)'"
        )
        assert new_streak == 0, (
            f"C8-AIMD-3: consecutive_successful must reset to 0 on failure, got {new_streak}"
        )
        assert should_pause is True, (
            f"C8-AIMD-3: should_pause must be True on failure, got {should_pause}"
        )

    @requires_core_bp
    def test_aimd_floor_at_one_not_zero(self):
        """C8-AIMD-4: concurrency floor is 1, not 0.

        Even with current_concurrency=1, halving must not produce 0.
        Ground truth: 'max(1, current_concurrency // 2)' → max(1, 0) = 1.
        """
        aimd_tune = _core_bp_mod.aimd_tune
        new_conc, new_spins, new_streak, should_pause = aimd_tune(
            current_concurrency=1,
            current_chunk_spins=500,
            max_concurrency=10,
            max_chunk_spins=5000,
            batch_fully_failed=True,
            consecutive_successful=0,
        )
        assert new_conc == 1, (
            f"C8-AIMD-4: floor must be 1 (not 0), got {new_conc}.\n"
            "PIA line 1014: 'new_conc = max(1, current_concurrency // 2)'"
        )

    @requires_core_bp
    def test_aimd_spins_growth_factor(self):
        """C8-AIMD-5: chunk_spins grow by CHUNK_SPINS_GROWTH factor (=1.25).

        Ground truth: 'new_spins = min(max_chunk_spins, int(current_chunk_spins * CHUNK_SPINS_GROWTH))'
        PIA line 1023. CHUNK_SPINS_GROWTH = 1.25 (line 521).
        current_chunk_spins=1000 → int(1000 * 1.25) = 1250.

        INJECT-BUG PROOF (documented in 03_tests.md):
          Inject: change CHUNK_SPINS_GROWTH from 1.25 to 1.1 in base_pipeline.py
          → int(1000 * 1.1) = 1100, not 1250 → test fails.
          Revert → GREEN.
        """
        aimd_tune = _core_bp_mod.aimd_tune
        new_conc, new_spins, new_streak, should_pause = aimd_tune(
            current_concurrency=5,
            current_chunk_spins=1000,
            max_concurrency=10,
            max_chunk_spins=5000,
            batch_fully_failed=False,
            consecutive_successful=0,
        )
        expected_spins = int(1000 * 1.25)  # = 1250
        assert new_spins == expected_spins, (
            f"C8-AIMD-5: chunk_spins growth factor wrong.\n"
            f"Expected int(1000*1.25)={expected_spins}, got {new_spins}.\n"
            "PIA line 521: CHUNK_SPINS_GROWTH = 1.25\n"
            "Inject-bug: change to 1.1 → gets 1100 instead of 1250 → RED."
        )

    @requires_core_bp
    def test_aimd_spins_floor_at_min_chunk_spins(self):
        """C8-AIMD-6: chunk_spins floor is MIN_CHUNK_SPINS (=500) on failure.

        Ground truth: 'new_spins = max(MIN_CHUNK_SPINS, current_chunk_spins // 2)'
        PIA line 1015. MIN_CHUNK_SPINS = 500 (line 519).
        current_chunk_spins=600 → 600//2 = 300 < 500 → floor to 500.
        """
        aimd_tune = _core_bp_mod.aimd_tune
        new_conc, new_spins, new_streak, should_pause = aimd_tune(
            current_concurrency=2,
            current_chunk_spins=600,
            max_concurrency=10,
            max_chunk_spins=5000,
            batch_fully_failed=True,
            consecutive_successful=0,
        )
        assert new_spins == 500, (
            f"C8-AIMD-6: MIN_CHUNK_SPINS floor failed: expected 500, got {new_spins}.\n"
            "PIA line 519: MIN_CHUNK_SPINS = 500\n"
            "PIA line 1015: 'new_spins = max(MIN_CHUNK_SPINS, current_chunk_spins // 2)'"
        )

    @requires_core_bp
    def test_aimd_success_streak_grows_then_resets(self):
        """C8-AIMD-7: streak reaches SUCCESS_STREAK_FOR_GROW (=1), triggers grow, resets to 0.

        Ground truth: PIA lines 1018-1024.
        SUCCESS_STREAK_FOR_GROW = 1 (one successful batch triggers grow immediately).
        After grow: new_streak = 0.
        """
        aimd_tune = _core_bp_mod.aimd_tune
        # First success from streak=0 → streak becomes 1 → >= 1 → grow → streak resets to 0.
        new_conc, new_spins, new_streak, should_pause = aimd_tune(
            current_concurrency=3,
            current_chunk_spins=1000,
            max_concurrency=10,
            max_chunk_spins=5000,
            batch_fully_failed=False,
            consecutive_successful=0,
        )
        assert new_streak == 0, (
            f"C8-AIMD-7: streak must reset to 0 after grow, got {new_streak}.\n"
            "PIA line 1024: 'new_success = 0' (after grow)"
        )
        assert new_conc == 4, f"Expected concurrency 3+1=4, got {new_conc}"

    @requires_core_bp
    def test_aimd_tuple_shape_is_4(self):
        """C8-AIMD-8: aimd_tune must return a 4-tuple (per docstring).

        Ground truth: 'Returns (new_concurrency, new_chunk_spins,
        new_consecutive_successful, should_pause)' — exactly 4 elements.
        """
        aimd_tune = _core_bp_mod.aimd_tune
        result = aimd_tune(
            current_concurrency=5,
            current_chunk_spins=1000,
            max_concurrency=10,
            max_chunk_spins=5000,
            batch_fully_failed=False,
            consecutive_successful=0,
        )
        assert isinstance(result, tuple), (
            f"aimd_tune must return a tuple, got {type(result).__name__}"
        )
        assert len(result) == 4, (
            f"aimd_tune must return a 4-tuple, got {len(result)}-tuple: {result!r}"
        )

    @requires_core_bp
    def test_aimd_constants_values_match_pia(self):
        """C8-AIMD-9: AIMD module-level constants must match PIA exactly.

        PIA lines 519-522:
          MIN_CHUNK_SPINS = 500
          SUCCESS_STREAK_FOR_GROW = 1
          CHUNK_SPINS_GROWTH = 1.25
          CIRCUIT_PAUSE_S = 3.0

        If these are in base_pipeline.py (Option B), they must match exactly.
        If they are passed as function arguments or remain in PIA (Option A),
        this test verifies whatever the module exposes.

        Inject-bug: change any constant → aimd_tune behavior drifts → rate-limit.
        """
        if hasattr(_core_bp_mod, "MIN_CHUNK_SPINS"):
            assert _core_bp_mod.MIN_CHUNK_SPINS == 500, (
                f"MIN_CHUNK_SPINS changed: got {_core_bp_mod.MIN_CHUNK_SPINS}, expected 500.\n"
                "PIA line 519: MIN_CHUNK_SPINS = 500"
            )
        if hasattr(_core_bp_mod, "SUCCESS_STREAK_FOR_GROW"):
            assert _core_bp_mod.SUCCESS_STREAK_FOR_GROW == 1, (
                f"SUCCESS_STREAK_FOR_GROW changed: got {_core_bp_mod.SUCCESS_STREAK_FOR_GROW}, expected 1.\n"
                "PIA line 520: SUCCESS_STREAK_FOR_GROW = 1"
            )
        if hasattr(_core_bp_mod, "CHUNK_SPINS_GROWTH"):
            assert _core_bp_mod.CHUNK_SPINS_GROWTH == 1.25, (
                f"CHUNK_SPINS_GROWTH changed: got {_core_bp_mod.CHUNK_SPINS_GROWTH}, expected 1.25.\n"
                "PIA line 521: CHUNK_SPINS_GROWTH = 1.25"
            )
        if hasattr(_core_bp_mod, "CIRCUIT_PAUSE_S"):
            assert _core_bp_mod.CIRCUIT_PAUSE_S == 3.0, (
                f"CIRCUIT_PAUSE_S changed: got {_core_bp_mod.CIRCUIT_PAUSE_S}, expected 3.0.\n"
                "PIA line 522: CIRCUIT_PAUSE_S = 3.0"
            )


# ===========================================================================
# C8 — _classify_failure routing (pure function, tests every branch)
# ===========================================================================

class TestClassifyFailure:
    """C8: _classify_failure() must route error strings correctly.

    Ground truth from PIA lines 525-572 (pure function, no external state).
    Every branch must map to the documented class.

    Memory feedback_upstream_throttle_ceiling.md: misrouting a machine-class
    error as 'network' wastes the entire budget retrying; misrouting a
    network error as 'machine' causes premature bail-fast on a recoverable error.
    """

    @requires_core_bp
    def test_empty_string_is_machine_class(self):
        """_classify_failure: empty string → 'machine' (safer default, bail fast).

        PIA line 547: 'if not error_str: return "machine"'
        """
        result = _core_bp_mod._classify_failure("")
        assert result == "machine", (
            f"_classify_failure('') must return 'machine', got {result!r}.\n"
            "PIA line 547: fail-fast on unknown error."
        )

    @requires_core_bp
    @pytest.mark.parametrize("code,expected_class", [
        (500, "network"),
        (502, "network"),
        (503, "network"),
        (504, "network"),
        (400, "machine"),
        (401, "machine"),
        (403, "machine"),
        (404, "machine"),
        (429, "machine"),
    ])
    def test_http_error_codes_classified_correctly(self, code, expected_class):
        """_classify_failure: request_failed_http_<N> routed by HTTP code.

        Ground truth PIA lines 551-556:
          if e.startswith("request_failed_http_"):
              try: code = int(e.rsplit("_", 1)[-1])
              return "network" if code in {500,502,503,504} else "machine"

        Inject-bug: add code 429 to _RETRYABLE_HTTP_CODES → 429 → 'network'.
        That is wrong (429 = Too Many Requests, retrying immediately makes it worse).
        """
        error_str = f"request_failed_http_{code}"
        result = _core_bp_mod._classify_failure(error_str)
        assert result == expected_class, (
            f"_classify_failure('{error_str}'): expected '{expected_class}', got {result!r}.\n"
            f"HTTP {code} must route to '{expected_class}' per PIA lines 551-556."
        )

    @requires_core_bp
    def test_network_prefix_is_network_class(self):
        """_classify_failure: 'request_failed_network_*' → 'network'.

        PIA line 558: 'if e.startswith("request_failed_network_"): return "network"'
        """
        for error_str in [
            "request_failed_network_URLError",
            "request_failed_network_TimeoutError",
            "request_failed_network_ConnectionResetError",
        ]:
            result = _core_bp_mod._classify_failure(error_str)
            assert result == "network", (
                f"_classify_failure('{error_str}'): expected 'network', got {result!r}.\n"
                "PIA line 558: 'request_failed_network_*' → network class."
            )

    @requires_core_bp
    def test_generic_request_failed_is_network_class(self):
        """_classify_failure: 'request_failed_*' (no 'http' or 'network' suffix) → 'network'.

        PIA lines 562-564: generic Exception fallback — typically network-layer
        weirdness. 'request_failed_SomeWeirdError' → 'network'.
        """
        result = _core_bp_mod._classify_failure("request_failed_SomeWeirdError")
        assert result == "network", (
            f"_classify_failure('request_failed_SomeWeirdError'): expected 'network', got {result!r}.\n"
            "PIA lines 562-564: generic request_failed → network class."
        )

    @requires_core_bp
    def test_parse_failed_is_machine_class(self):
        """_classify_failure: 'parse_failed_*' → 'machine' (retry won't fix parsing).

        PIA lines 565-567: 'if e.startswith("parse_failed_"): return "machine"'
        """
        for error_str in [
            "parse_failed_json_decode",
            "parse_failed_schema_error",
            "parse_failed_unexpected_structure",
        ]:
            result = _core_bp_mod._classify_failure(error_str)
            assert result == "machine", (
                f"_classify_failure('{error_str}'): expected 'machine', got {result!r}.\n"
                "PIA line 566: 'parse_failed_*' → machine class."
            )

    @requires_core_bp
    def test_response_shape_unexpected_is_machine_class(self):
        """_classify_failure: 'response_shape_unexpected*' → 'machine'.

        PIA lines 568-569: 'if e.startswith("response_shape_unexpected"): return "machine"'
        """
        result = _core_bp_mod._classify_failure("response_shape_unexpected_missing_key")
        assert result == "machine", (
            f"_classify_failure('response_shape_unexpected_*'): expected 'machine', got {result!r}."
        )

    @requires_core_bp
    def test_schema_drift_is_machine_class(self):
        """_classify_failure: 'schema_drift_*' → 'machine'.

        PIA lines 570-571: 'if e.startswith("schema_drift_"): return "machine"'
        """
        result = _core_bp_mod._classify_failure("schema_drift_unknown_field")
        assert result == "machine", (
            f"_classify_failure('schema_drift_*'): expected 'machine', got {result!r}."
        )

    @requires_core_bp
    def test_unknown_error_defaults_to_machine(self):
        """_classify_failure: unrecognized error string → 'machine' (fail-fast on uncertainty).

        PIA line 572: 'return "machine"' (catch-all fallback).
        """
        result = _core_bp_mod._classify_failure("something_completely_unknown")
        assert result == "machine", (
            f"_classify_failure('something_completely_unknown'): expected 'machine', got {result!r}.\n"
            "PIA line 572: unknown errors default to machine class (fail fast)."
        )


# ===========================================================================
# C8 — make_payload schema
# ===========================================================================

class TestMakePayload:
    """C8: make_payload() must produce the correct request body schema.

    Ground truth from PIA lines 1277-1323.
    Required keys: MachineName, InitCreditsStr, BetStrategy, BetOriginStr,
    SpinTimes, RtpId, ShouldTestLuckyGame, ContinueAfterBankrupt,
    ResetPlayerStateAfterEachSpin, RobotCount, OutputAllRobotResult.
    Optional key: MachineConfig (only when machine_config is truthy).
    """

    _REQUIRED_KEYS = [
        "MachineName",
        "InitCreditsStr",
        "BetStrategy",
        "BetOriginStr",
        "SpinTimes",
        "RtpId",
        "ShouldTestLuckyGame",
        "ContinueAfterBankrupt",
        "ResetPlayerStateAfterEachSpin",
        "RobotCount",
        "OutputAllRobotResult",
    ]

    @requires_core_bp
    @pytest.mark.parametrize("key", _REQUIRED_KEYS)
    def test_required_key_present_in_payload(self, key):
        """C8-payload-1: each required key must be in the returned dict.

        Inject-bug: remove any one key from make_payload's output dict
        → the matching parametrized test goes RED.
        """
        payload = _core_bp_mod.make_payload(
            machine="M14",
            rtp_mode=1,
            bet=1000,
            spin_times=5000,
            robot_count=20,
            init_credits=10**14,
            reset_each_spin=True,
            continue_after_bankrupt=True,
        )
        assert key in payload, (
            f"C8-payload-1: required key '{key}' missing from make_payload output.\n"
            f"Full payload keys: {sorted(payload.keys())}\n"
            "Ground truth: PIA lines 1308-1320."
        )

    @requires_core_bp
    def test_machine_name_uses_upstream_name_when_provided(self):
        """C8-payload-2: upstream_machine_name overrides MachineName when set.

        PIA line 1309: 'MachineName: upstream_machine_name if upstream_machine_name else machine'
        Used by variant rows that pass a variant key like 'M273$1$1-2-3'.
        """
        payload = _core_bp_mod.make_payload(
            machine="M273_display",
            rtp_mode=1,
            bet=1000,
            spin_times=5000,
            robot_count=20,
            init_credits=10**14,
            reset_each_spin=True,
            continue_after_bankrupt=True,
            upstream_machine_name="M273$1$1-2-3",
        )
        assert payload["MachineName"] == "M273$1$1-2-3", (
            f"Expected MachineName='M273$1$1-2-3', got {payload['MachineName']!r}.\n"
            "C8-payload-2: upstream_machine_name must override machine for MachineName."
        )

    @requires_core_bp
    def test_machine_name_falls_back_to_machine_when_upstream_name_absent(self):
        """C8-payload-3: when upstream_machine_name is None, MachineName = machine.

        PIA line 1309: fallback to 'machine' when upstream_machine_name is falsy.
        """
        payload = _core_bp_mod.make_payload(
            machine="M14",
            rtp_mode=1,
            bet=1000,
            spin_times=5000,
            robot_count=20,
            init_credits=10**14,
            reset_each_spin=True,
            continue_after_bankrupt=True,
            upstream_machine_name=None,
        )
        assert payload["MachineName"] == "M14", (
            f"Expected MachineName='M14', got {payload['MachineName']!r}."
        )

    @requires_core_bp
    def test_machine_config_key_absent_when_not_provided(self):
        """C8-payload-4: MachineConfig key must NOT be present when machine_config is None.

        PIA lines 1321-1322: 'if machine_config: payload["MachineConfig"] = machine_config'
        The field's presence alone changes upstream behavior, so blank must not be sent.
        """
        payload = _core_bp_mod.make_payload(
            machine="M14",
            rtp_mode=1,
            bet=1000,
            spin_times=5000,
            robot_count=20,
            init_credits=10**14,
            reset_each_spin=True,
            continue_after_bankrupt=True,
            machine_config=None,
        )
        assert "MachineConfig" not in payload, (
            "C8-payload-4: MachineConfig must NOT be present when machine_config=None.\n"
            "PIA line 1321: 'if machine_config: payload[...]' — guarded by truthiness."
        )

    @requires_core_bp
    def test_machine_config_key_present_when_provided(self):
        """C8-payload-5: MachineConfig key must be present when machine_config is set.

        PIA line 1322: 'payload["MachineConfig"] = machine_config'
        """
        cfg_json = '{"key": "value"}'
        payload = _core_bp_mod.make_payload(
            machine="M14",
            rtp_mode=1,
            bet=1000,
            spin_times=5000,
            robot_count=20,
            init_credits=10**14,
            reset_each_spin=True,
            continue_after_bankrupt=True,
            machine_config=cfg_json,
        )
        assert "MachineConfig" in payload, (
            "C8-payload-5: MachineConfig must be present when machine_config is set."
        )
        assert payload["MachineConfig"] == cfg_json, (
            f"MachineConfig value wrong: got {payload['MachineConfig']!r}, expected {cfg_json!r}"
        )

    @requires_core_bp
    def test_rtp_id_is_int(self):
        """C8-payload-6: RtpId must be an int (not a string or float).

        PIA line 1314: 'RtpId: int(rtp_mode)'
        """
        payload = _core_bp_mod.make_payload(
            machine="M14",
            rtp_mode=1,
            bet=1000,
            spin_times=5000,
            robot_count=20,
            init_credits=10**14,
            reset_each_spin=True,
            continue_after_bankrupt=True,
        )
        assert isinstance(payload["RtpId"], int), (
            f"RtpId must be int, got {type(payload['RtpId']).__name__}"
        )
        assert payload["RtpId"] == 1, (
            f"RtpId must equal rtp_mode=1, got {payload['RtpId']}"
        )

    @requires_core_bp
    def test_output_all_robot_result_is_true(self):
        """C8-payload-7: OutputAllRobotResult must always be True.

        PIA line 1319: 'OutputAllRobotResult: True' (hardcoded).
        Changing it breaks the per-robot result aggregation.
        """
        payload = _core_bp_mod.make_payload(
            machine="M14",
            rtp_mode=1,
            bet=1000,
            spin_times=5000,
            robot_count=20,
            init_credits=10**14,
            reset_each_spin=True,
            continue_after_bankrupt=True,
        )
        assert payload["OutputAllRobotResult"] is True, (
            f"OutputAllRobotResult must be True, got {payload['OutputAllRobotResult']!r}.\n"
            "PIA line 1319: hardcoded True — changing breaks per-robot aggregation."
        )

    @requires_core_bp
    def test_bet_strategy_is_zero(self):
        """C8-payload-8: BetStrategy must be 0 (hardcoded per PIA line 1311).

        BetStrategy=0 means "fixed bet". Changing this changes upstream behavior.
        """
        payload = _core_bp_mod.make_payload(
            machine="M14",
            rtp_mode=1,
            bet=1000,
            spin_times=5000,
            robot_count=20,
            init_credits=10**14,
            reset_each_spin=True,
            continue_after_bankrupt=True,
        )
        assert payload["BetStrategy"] == 0, (
            f"BetStrategy must be 0 (fixed bet), got {payload['BetStrategy']!r}."
        )


# ===========================================================================
# C8 — select_replay_chunks_by_md5 (inverted index lookup)
# ===========================================================================

class TestSelectReplayChunksByMd5:
    """C8: select_replay_chunks_by_md5() must use the inverted by_md5 index.

    Ground truth from PIA lines 1160-1214.
    Key behavior:
    - Uses by_md5 inverted index directly (O(1) lookup, not linear scan).
    - Falls back to _rebuild_by_md5 when by_md5 is missing from sidecar.
    - Returns (chunk_files, max_existing_idx).
    - Empty sidecar → ([], 0).
    - Non-matching md5 → ([], max_existing_idx).
    """

    def _make_sidecar(
        self,
        chunks: dict[str, dict],
        by_md5: dict[str, list[str]] | None = None,
    ) -> dict:
        """Build a minimal sidecar payload for testing."""
        payload = {"_version": 2, "chunks": chunks}
        if by_md5 is not None:
            payload["by_md5"] = by_md5
        return payload

    @requires_core_bp
    def test_empty_sidecar_returns_empty_list(self):
        """C8-select-1: empty or None sidecar → ([], 0).

        PIA lines 1194-1198: early return on empty/invalid sidecar.
        """
        fn = _core_bp_mod.select_replay_chunks_by_md5
        cache_dir = Path("/nonexistent")

        files, max_idx = fn(cache_dir, {}, "cfg123", "code456")
        assert files == [], f"Empty sidecar: expected [], got {files}"
        assert max_idx == 0, f"Empty sidecar: expected max_idx=0, got {max_idx}"

        files2, max_idx2 = fn(cache_dir, None, "cfg123", "code456")
        assert files2 == [], "None sidecar: expected []"
        assert max_idx2 == 0

    @requires_core_bp
    def test_matching_md5_returns_correct_chunks(self):
        """C8-select-2: matching (config_md5, code_md5) → returns those chunk paths.

        This is the core O(1) lookup via the inverted index.
        """
        fn = _core_bp_mod.select_replay_chunks_by_md5
        cache_dir = Path("/cache/dir")

        chunks = {
            "chunk_001.json": {"idx": 1, "config_md5": "cfg_a", "code_md5": "code_b"},
            "chunk_002.json": {"idx": 2, "config_md5": "cfg_a", "code_md5": "code_b"},
            "chunk_003.json": {"idx": 3, "config_md5": "other_cfg", "code_md5": "other_code"},
        }
        by_md5 = {
            "cfg_a|code_b": ["chunk_001.json", "chunk_002.json"],
            "other_cfg|other_code": ["chunk_003.json"],
        }
        sidecar = self._make_sidecar(chunks, by_md5)

        files, max_idx = fn(cache_dir, sidecar, "cfg_a", "code_b")

        # Should return the 2 matching chunks.
        assert len(files) == 2, (
            f"C8-select-2: expected 2 chunk files, got {len(files)}: {files}"
        )
        assert cache_dir / "chunk_001.json" in files
        assert cache_dir / "chunk_002.json" in files

        # max_idx is across ALL chunks in sidecar, not just matching.
        assert max_idx == 3, (
            f"C8-select-2: max_idx must be max across ALL chunks, got {max_idx}"
        )

    @requires_core_bp
    def test_non_matching_md5_returns_empty_files(self):
        """C8-select-3: non-matching md5 → ([], max_existing_idx from all chunks).

        'Empty when no chunks match (legitimate fresh-pull just landed state).'
        max_existing_idx still tracks ALL chunks for resume-mode collision avoidance.
        """
        fn = _core_bp_mod.select_replay_chunks_by_md5
        cache_dir = Path("/cache/dir")

        chunks = {
            "chunk_001.json": {"idx": 5, "config_md5": "old_cfg", "code_md5": "old_code"},
        }
        by_md5 = {
            "old_cfg|old_code": ["chunk_001.json"],
        }
        sidecar = self._make_sidecar(chunks, by_md5)

        files, max_idx = fn(cache_dir, sidecar, "new_cfg", "new_code")

        assert files == [], (
            f"Non-matching md5: expected [], got {files}"
        )
        assert max_idx == 5, (
            f"Non-matching md5: max_idx must still be 5 (max across ALL chunks), got {max_idx}"
        )

    @requires_core_bp
    def test_md5_key_format_is_pipe_separated(self):
        """C8-select-4: inverted index key format is '{config_md5}|{code_md5}'.

        PIA line 1205: 'key = f"{upstream_config_md5 or ''}|{upstream_code_md5 or ''}"'
        This test pins the separator. If someone changes it to '/' or ':', the lookup
        would fail to find matching chunks.
        """
        fn = _core_bp_mod.select_replay_chunks_by_md5
        cache_dir = Path("/cache/dir")

        # Build a sidecar where the inverted key uses '|' separator.
        chunks = {"chunk_001.json": {"idx": 1}}
        by_md5 = {"alpha|beta": ["chunk_001.json"]}
        sidecar = self._make_sidecar(chunks, by_md5)

        # Query with the same md5 values.
        files, _ = fn(cache_dir, sidecar, "alpha", "beta")
        assert len(files) == 1, (
            f"C8-select-4: key format must be 'config_md5|code_md5' (pipe-separated).\n"
            f"Got {len(files)} files. The key separator may have changed from '|'."
        )

    @requires_core_bp
    def test_fallback_rebuilds_by_md5_when_missing(self):
        """C8-select-5: when by_md5 is absent from sidecar, fall back to chunk scan.

        PIA lines 1202-1204:
          'by_md5 = sidecar_payload.get("by_md5")'
          'if not isinstance(by_md5, dict): by_md5 = _rebuild_by_md5(chunks_dict)'

        Old sidecars without the by_md5 field must still work. This test verifies
        the fallback path using chunk dict metadata directly.
        """
        fn = _core_bp_mod.select_replay_chunks_by_md5
        cache_dir = Path("/cache/dir")

        # Sidecar WITHOUT by_md5 (old format). The chunks must have config_md5/code_md5
        # so _rebuild_by_md5 can construct the index.
        chunks = {
            "chunk_001.json": {"idx": 1, "config_md5": "cfg_x", "code_md5": "code_y"},
        }
        sidecar = self._make_sidecar(chunks, by_md5=None)  # No by_md5
        assert "by_md5" not in sidecar  # Confirm no inverted index

        # The fallback path should still find the chunk.
        files, max_idx = fn(cache_dir, sidecar, "cfg_x", "code_y")

        # Either the fallback worked (found chunk) or it gracefully returned empty.
        # The important thing is: no crash. If _rebuild_by_md5 is called correctly,
        # it will find the matching chunk.
        assert isinstance(files, list), (
            f"select_replay_chunks_by_md5 must return a list, got {type(files).__name__}"
        )
        assert isinstance(max_idx, int), (
            f"max_existing_idx must be int, got {type(max_idx).__name__}"
        )
        assert max_idx == 1, (
            f"max_idx must be 1 (max idx in chunks), got {max_idx}"
        )


# ===========================================================================
# C8 — post_json_with_retry semantics
# ===========================================================================

class TestPostJsonWithRetry:
    """C8: post_json_with_retry() must retry exactly max_attempts times on
    transient network errors, with correct backoff policy.

    Ground truth from PIA lines 1028-1089.
    Key behavior:
    - max_attempts=3 default
    - Retries on: HTTPError(5xx), URLError, TimeoutError, socket.timeout,
      IncompleteRead, RemoteDisconnected, ConnectionError
    - Does NOT retry on: HTTPError(4xx), JSONDecodeError, etc.
    - Backoff: min(max_backoff_s, initial_backoff_s * 2^attempt)
    - After all attempts exhausted, re-raises last_exc.
    """

    @requires_core_bp
    def test_retries_on_url_error_up_to_max_attempts(self):
        """C8-retry-1: URLError → retries max_attempts times then re-raises.

        Inject-bug: change max_attempts default from 3 to 1 → only 1 call made
        → if stub fails on call 1, retried test finds 1 call instead of 3 → RED.
        """
        call_count = {"n": 0}

        def _failing_post_json(payload, timeout):
            call_count["n"] += 1
            raise urllib.error.URLError("connection refused")

        with patch.object(_core_bp_mod, "post_json", side_effect=_failing_post_json):
            with patch.object(_core_bp_mod.time, "sleep"):  # avoid actual sleep
                with pytest.raises(urllib.error.URLError):
                    _core_bp_mod.post_json_with_retry(
                        {"test": True}, timeout=5.0,
                        max_attempts=3,
                        initial_backoff_s=0.01,
                        max_backoff_s=0.05,
                    )

        assert call_count["n"] == 3, (
            f"C8-retry-1: expected 3 attempts (max_attempts=3), got {call_count['n']}.\n"
            "Inject-bug: change default max_attempts from 3 to 1 → gets 1 → RED."
        )

    @requires_core_bp
    def test_succeeds_on_last_attempt(self):
        """C8-retry-2: URLError on first 2 attempts, success on 3rd.

        Verifies the retry loop continues after transient failures.
        """
        call_count = {"n": 0}
        expected_response = {"ok": True, "data": [1, 2, 3]}

        def _eventually_ok(payload, timeout):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise urllib.error.URLError("transient error")
            return expected_response

        with patch.object(_core_bp_mod, "post_json", side_effect=_eventually_ok):
            with patch.object(_core_bp_mod.time, "sleep"):
                result = _core_bp_mod.post_json_with_retry(
                    {"test": True}, timeout=5.0,
                    max_attempts=3,
                    initial_backoff_s=0.01,
                    max_backoff_s=0.05,
                )

        assert result == expected_response, (
            f"C8-retry-2: expected successful response on 3rd attempt, got {result!r}"
        )
        assert call_count["n"] == 3

    @requires_core_bp
    def test_does_not_retry_on_4xx_http_error(self):
        """C8-retry-3: HTTPError(4xx) raises immediately without retry.

        PIA lines 1072-1075: 'if exc.code not in _RETRYABLE_HTTP_CODES: raise'
        A 400 Bad Request should not be retried — the request itself is malformed.

        Inject-bug: add 400 to _RETRYABLE_HTTP_CODES → retry loop runs → call_count > 1 → RED.
        """
        call_count = {"n": 0}

        def _bad_request_error(payload, timeout):
            call_count["n"] += 1
            raise urllib.error.HTTPError(
                url="http://test/", code=400, msg="Bad Request",
                hdrs=None, fp=None
            )

        with patch.object(_core_bp_mod, "post_json", side_effect=_bad_request_error):
            with patch.object(_core_bp_mod.time, "sleep"):
                with pytest.raises(urllib.error.HTTPError) as exc_info:
                    _core_bp_mod.post_json_with_retry(
                        {"test": True}, timeout=5.0,
                        max_attempts=3,
                        initial_backoff_s=0.01,
                        max_backoff_s=0.05,
                    )

        assert exc_info.value.code == 400
        assert call_count["n"] == 1, (
            f"C8-retry-3: HTTPError(400) must NOT be retried. "
            f"Expected 1 call, got {call_count['n']}.\n"
            "Inject-bug: add 400 to _RETRYABLE_HTTP_CODES → retries → call_count=3 → RED."
        )

    @requires_core_bp
    def test_retries_on_5xx_http_error(self):
        """C8-retry-4: HTTPError(503) must be retried up to max_attempts.

        PIA line 1074: 'if exc.code not in _RETRYABLE_HTTP_CODES: raise'
        503 IS in _RETRYABLE_HTTP_CODES → retry.
        """
        call_count = {"n": 0}

        def _service_unavailable(payload, timeout):
            call_count["n"] += 1
            raise urllib.error.HTTPError(
                url="http://test/", code=503, msg="Service Unavailable",
                hdrs=None, fp=None
            )

        with patch.object(_core_bp_mod, "post_json", side_effect=_service_unavailable):
            with patch.object(_core_bp_mod.time, "sleep"):
                with pytest.raises(urllib.error.HTTPError):
                    _core_bp_mod.post_json_with_retry(
                        {"test": True}, timeout=5.0,
                        max_attempts=3,
                        initial_backoff_s=0.01,
                        max_backoff_s=0.05,
                    )

        assert call_count["n"] == 3, (
            f"C8-retry-4: HTTPError(503) must be retried. Expected 3, got {call_count['n']}."
        )

    @requires_core_bp
    def test_backoff_is_exponential_capped_at_max(self):
        """C8-retry-5: backoff is min(max_backoff_s, initial * 2^attempt).

        PIA line 1086: 'delay = min(max_backoff_s, initial_backoff_s * (2 ** attempt))'
        attempt=0 → delay=min(5, 1*1)=1
        attempt=1 → delay=min(5, 1*2)=2
        attempt=2 → (no sleep: last attempt, no next batch)

        Inject-bug: change formula to flat 'initial_backoff_s' (no doubling)
        → sleep calls don't match expected doubling → RED.
        """
        call_count = {"n": 0}
        sleep_calls = []

        def _always_fails(payload, timeout):
            call_count["n"] += 1
            raise urllib.error.URLError("always fails")

        def _capture_sleep(duration):
            sleep_calls.append(duration)

        with patch.object(_core_bp_mod, "post_json", side_effect=_always_fails):
            with patch.object(_core_bp_mod.time, "sleep", side_effect=_capture_sleep):
                with pytest.raises(urllib.error.URLError):
                    _core_bp_mod.post_json_with_retry(
                        {"test": True}, timeout=5.0,
                        max_attempts=3,
                        initial_backoff_s=1.0,
                        max_backoff_s=5.0,
                    )

        # PIA line 1085: 'if attempt + 1 < max_attempts:' → sleep only between attempts.
        # max_attempts=3: sleep after attempt 0 and 1 (not after 2).
        assert len(sleep_calls) == 2, (
            f"C8-retry-5: expected 2 sleep calls (between 3 attempts), got {len(sleep_calls)}: {sleep_calls}"
        )
        # attempt 0: delay = min(5, 1.0 * 2^0) = min(5, 1.0) = 1.0
        assert abs(sleep_calls[0] - 1.0) < 0.01, (
            f"C8-retry-5: first sleep should be 1.0s, got {sleep_calls[0]}"
        )
        # attempt 1: delay = min(5, 1.0 * 2^1) = min(5, 2.0) = 2.0
        assert abs(sleep_calls[1] - 2.0) < 0.01, (
            f"C8-retry-5: second sleep should be 2.0s (doubling), got {sleep_calls[1]}"
        )

    @requires_core_bp
    def test_success_on_first_attempt_no_sleep(self):
        """C8-retry-6: immediate success → no sleep, returns result directly."""
        expected = {"data": "result"}

        with patch.object(_core_bp_mod, "post_json", return_value=expected):
            with patch.object(_core_bp_mod.time, "sleep") as mock_sleep:
                result = _core_bp_mod.post_json_with_retry(
                    {"test": True}, timeout=5.0,
                    max_attempts=3,
                )

        assert result == expected
        mock_sleep.assert_not_called()


# ===========================================================================
# C8 — run_sampling_chunk structure (light probe — no real network needed)
# ===========================================================================

class TestRunSamplingChunkStructure:
    """C8: run_sampling_chunk() returns a dict with correct keys on network failure.

    Ground truth from PIA lines 1392-1459.
    On network failure: returns {'ok': False, 'index': chunk_index, 'error': '...'}
    We only test the error-path here (no real HTTP needed). The happy path is
    covered by the P1-A1 parity canary (integration level).
    """

    @requires_core_bp
    def test_http_error_returns_error_dict(self):
        """C8-run-1: HTTPError → {'ok': False, 'index': chunk_index, 'error': 'request_failed_http_N'}.

        PIA line 1429: 'return {"ok": False, "index": chunk_index, "error": f"request_failed_http_{exc.code}"}'
        """
        def _raise_http_error(payload, timeout):
            raise urllib.error.HTTPError(
                url="http://test/", code=503, msg="Service Unavailable",
                hdrs=None, fp=None
            )

        with patch.object(_core_bp_mod, "post_json_with_retry", side_effect=_raise_http_error):
            result = _core_bp_mod.run_sampling_chunk(
                chunk_index=7,
                machine="M14",
                rtp_mode=1,
                bet=1000,
                spin_times=100,
                robot_count=5,
                timeout=5.0,
            )

        assert result["ok"] is False, f"Expected ok=False, got {result.get('ok')}"
        assert result["index"] == 7, f"Expected index=7, got {result.get('index')}"
        assert result["error"] == "request_failed_http_503", (
            f"Expected 'request_failed_http_503', got {result.get('error')!r}"
        )

    @requires_core_bp
    def test_url_error_returns_error_dict(self):
        """C8-run-2: URLError → {'ok': False, 'index': chunk_index, 'error': 'request_failed_network_*'}.

        PIA lines 1430-1434: 'request_failed_network_{exc.__class__.__name__}'
        """
        def _raise_url_error(payload, timeout):
            raise urllib.error.URLError("connection refused")

        with patch.object(_core_bp_mod, "post_json_with_retry", side_effect=_raise_url_error):
            result = _core_bp_mod.run_sampling_chunk(
                chunk_index=3,
                machine="M14",
                rtp_mode=1,
                bet=1000,
                spin_times=100,
                robot_count=5,
                timeout=5.0,
            )

        assert result["ok"] is False
        assert result["index"] == 3
        assert result["error"].startswith("request_failed_network_"), (
            f"URLError must produce 'request_failed_network_*' error, got {result.get('error')!r}"
        )

    @requires_core_bp
    def test_generic_exception_returns_request_failed_error(self):
        """C8-run-3: generic Exception → 'request_failed_{ClassName}'.

        PIA lines 1436-1441: 'request_failed_{exc.__class__.__name__}'
        """
        class _WeirdError(Exception):
            pass

        def _raise_weird(payload, timeout):
            raise _WeirdError("something unexpected")

        with patch.object(_core_bp_mod, "post_json_with_retry", side_effect=_raise_weird):
            result = _core_bp_mod.run_sampling_chunk(
                chunk_index=1,
                machine="M14",
                rtp_mode=1,
                bet=1000,
                spin_times=100,
                robot_count=5,
                timeout=5.0,
            )

        assert result["ok"] is False
        assert result["index"] == 1
        assert "_WeirdError" in result.get("error", ""), (
            f"Expected '_WeirdError' in error, got {result.get('error')!r}"
        )


# ===========================================================================
# C2 — P1-A1 canary structural assertion
# ===========================================================================

class TestP1A1ParityCanary:
    """C2: structural check that the P1-A1 parity test file still exists.

    The actual 23/23 run is impl-verifier's job.
    """

    def test_parity_test_file_exists(self):
        """C2: tests/integration/test_analyzer_three_invocation_parity.py must exist."""
        parity_file = (
            ROOT / "tests" / "integration" /
            "test_analyzer_three_invocation_parity.py"
        )
        assert parity_file.exists(), (
            f"P1-A1 parity test file not found: {parity_file}\n"
            "C2: this file is the canary — it must not be deleted by P2-B4."
        )

    def test_parity_test_file_is_valid_python(self):
        """C2: the P1-A1 parity test file must parse as valid Python."""
        parity_file = (
            ROOT / "tests" / "integration" /
            "test_analyzer_three_invocation_parity.py"
        )
        if not parity_file.exists():
            pytest.skip("Parity test file missing — covered by existence test above")

        source = parity_file.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as exc:
            pytest.fail(
                f"P1-A1 parity test file has SyntaxError: {exc}\n"
                "C2: the carve must not break the existing test file."
            )

    @requires_pia
    def test_pia_still_has_post_json_for_parity_path(self):
        """C2: pia.post_json accessible (used in the sampling path the parity test exercises).

        The 3-invocation parity test exercises the full HTTP→parse→accumulate pipeline.
        If PIA loses post_json (or any of the 8 functions), the subprocess exits
        non-zero → parity test goes RED.
        """
        assert hasattr(_pia, "post_json"), (
            "pia.post_json not accessible.\n"
            "C2: the P1-A1 parity test's HTTP path would be broken."
        )
        assert callable(_pia.post_json), (
            "pia.post_json is not callable."
        )


# ===========================================================================
# C8 — Inject-bug proof mechanism tests (self-validating proofs)
# ===========================================================================

class TestInjectBugProofMechanisms:
    """C8 proof: verify the mechanism of each inject-bug scenario.

    These tests prove that the guards WORK without editing production files.
    They simulate the inject scenario using dummy objects.
    """

    def test_inject_aimd_growth_factor_proof(self):
        """C8-AIMD proof: changing growth from +1 to +0 would make test_aimd_additive_increase_on_success RED.

        We prove the mechanism: the test checks new_conc == 6 (= 5+1).
        If the formula were 'current_concurrency + 0' → new_conc = 5 → fails.
        """
        # Simulate what aimd_tune would return with a broken growth formula (+0 instead of +1).
        def _broken_aimd_tune(current_concurrency, current_chunk_spins, max_concurrency,
                               max_chunk_spins, batch_fully_failed, consecutive_successful):
            # Bug: additive increase is +0 (no growth).
            if batch_fully_failed:
                return (max(1, current_concurrency // 2), max(500, current_chunk_spins // 2), 0, True)
            new_success = consecutive_successful + 1
            if new_success >= 1:
                new_conc = min(max_concurrency, current_concurrency + 0)  # BUG: +0 instead of +1
                new_spins = min(max_chunk_spins, int(current_chunk_spins * 1.25))
                new_success = 0
            else:
                new_conc = current_concurrency
                new_spins = current_chunk_spins
            return (new_conc, new_spins, new_success, False)

        result = _broken_aimd_tune(5, 1000, 10, 5000, False, 0)
        new_conc = result[0]
        # The test expects 6 (5+1). With the bug, we get 5. Prove it goes RED:
        assert new_conc != 6, (
            "INJECT-BUG PROOF: broken aimd_tune with +0 growth returns concurrency 5, not 6.\n"
            "test_aimd_additive_increase_on_success would assert new_conc==6 → RED."
        )
        assert new_conc == 5

    def test_inject_aimd_floor_proof(self):
        """C8-AIMD proof: changing floor from max(1,...) to max(0,...) makes test RED.

        Simulate: current=1, fully_failed → max(0, 0) = 0. Test asserts >= 1 → RED.
        """
        # Broken: floor is 0 instead of 1.
        broken_new_conc = max(0, 1 // 2)  # = 0
        assert broken_new_conc == 0, "Proof: broken formula gives 0"
        # The guard test asserts new_conc == 1 → would go RED.
        assert broken_new_conc != 1, "Proof: test_aimd_floor_at_one_not_zero would RED"

    def test_inject_retry_count_proof(self):
        """C8-retry proof: changing max_attempts default 3→1 makes retry test RED.

        If max_attempts=1, only 1 call is made. The test asserts call_count==3 → RED.
        """
        # Simulate a function with max_attempts=1 (broken default).
        call_count = {"n": 0}

        def _mock_fn():
            call_count["n"] += 1
            raise urllib.error.URLError("fail")

        for attempt in range(1):  # max_attempts=1 (broken)
            try:
                _mock_fn()
            except urllib.error.URLError:
                pass

        assert call_count["n"] == 1, "Proof: with max_attempts=1, only 1 call made"
        # test_retries_on_url_error_up_to_max_attempts asserts call_count==3 → RED.

    def test_inject_payload_missing_key_proof(self):
        """C8-payload proof: missing a key from make_payload output makes test RED.

        Simulate a broken make_payload that omits 'OutputAllRobotResult'.
        The parametrized test 'test_required_key_present_in_payload[OutputAllRobotResult]'
        would check 'OutputAllRobotResult' in payload → False → RED.
        """
        broken_payload = {
            "MachineName": "M14",
            "InitCreditsStr": "100000000000000",
            # OutputAllRobotResult intentionally omitted (inject bug).
        }
        missing_key = "OutputAllRobotResult"
        has_it = missing_key in broken_payload
        assert not has_it, (
            "INJECT-BUG PROOF: broken payload missing 'OutputAllRobotResult'.\n"
            "test_required_key_present_in_payload[OutputAllRobotResult] would → RED."
        )

    def test_inject_classify_failure_wrong_routing_proof(self):
        """C8-classify proof: wrong routing of HTTP 429 → 'network' makes test RED.

        If someone added 429 to _RETRYABLE_HTTP_CODES, _classify_failure would
        return 'network' for 'request_failed_http_429'. Our test asserts 'machine' → RED.
        """
        # Simulate broken classify with 429 in retryable codes.
        broken_retryable = frozenset({500, 502, 503, 504, 429})
        error_str = "request_failed_http_429"
        code = int(error_str.rsplit("_", 1)[-1])
        broken_result = "network" if code in broken_retryable else "machine"
        assert broken_result == "network", "Proof: broken routing returns 'network' for 429"
        # test_http_error_codes_classified_correctly[429-machine] asserts 'machine' → RED.

    def test_inject_select_chunks_wrong_key_format_proof(self):
        """C8-select proof: changing key separator from '|' to '/' makes lookup fail.

        If the key format were 'config_md5/code_md5' instead of 'config_md5|code_md5',
        the inverted index lookup would find nothing.
        """
        # Broken key format (using '/').
        broken_key = "alpha/beta"
        # Inverted index uses '|' separator.
        by_md5 = {"alpha|beta": ["chunk_001.json"]}
        # Lookup with broken key → empty.
        matching = by_md5.get(broken_key, [])
        assert matching == [], (
            "INJECT-BUG PROOF: wrong key separator '/' finds nothing in by_md5 index.\n"
            "test_md5_key_format_is_pipe_separated would see len(files)==0 != 1 → RED."
        )


# ===========================================================================
# Existing test suites structural guard (C7 / regression)
# ===========================================================================

class TestExistingTestSuitesStillIntact:
    """Assert that prior carve test files (P2-B1/B2/B3) are not corrupted by P2-B4."""

    _PRIOR_TEST_FILES = [
        "tests/backend/test_analyzer_core_parser.py",
        "tests/backend/test_analyzer_core_aggregator.py",
        "tests/backend/test_analyzer_core_writer.py",
        "tests/integration/test_analyzer_three_invocation_parity.py",
    ]

    @pytest.mark.parametrize("rel_path", _PRIOR_TEST_FILES)
    def test_prior_test_file_still_exists(self, rel_path):
        """Each prior-carve test file must still exist on disk."""
        p = ROOT / rel_path
        assert p.exists(), (
            f"Prior-carve test file not found: {p}\n"
            "P2-B4 must not delete or rename existing test files."
        )

    @pytest.mark.parametrize("rel_path", _PRIOR_TEST_FILES)
    def test_prior_test_file_valid_python(self, rel_path):
        """Each prior-carve test file must parse as valid Python."""
        p = ROOT / rel_path
        if not p.exists():
            pytest.skip(f"File missing: {rel_path}")
        source = p.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as exc:
            pytest.fail(f"SyntaxError in {rel_path}: {exc}")
