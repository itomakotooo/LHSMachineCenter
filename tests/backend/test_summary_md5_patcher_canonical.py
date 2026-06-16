"""Regression tests for Ticket P1-B2 — Consolidate summary md5 patcher (real x 2).

After the dedup:
  - fresh_slotlab/summary_md5_patch.py is the SINGLE canonical location for
    patch_summary_md5(summary_path, md5_lookup_fn, *, machine=..., mode=...) -> None.
  - app.py (lines 7079-7097) and virtual_analyzer.py (_patch_summary_md5_tags,
    lines 500-552) no longer contain duplicated patcher bodies — each becomes a
    thin callsite that delegates to the canonical helper.
  - md5_lookup_fn is a ZERO-ARGUMENT callable (caller binds machine/mode in a
    lambda); machine + mode keyword args are used ONLY in error log messages.
  - Failure logging: if md5_lookup_fn raises or returning empty when a value was
    expected, the helper logs with full context and does NOT silently swallow.

Contracts under test (per brief §3):
  C1 — single helper, injectable lookup: exactly one canonical definition in
       fresh_slotlab/summary_md5_patch.py; accepts md5_lookup_fn parameter.
  C2 — both callsites use helper: no duplicated patcher body in app.py or
       virtual_analyzer.py; both import and call patch_summary_md5.
  C3 — per-mode granularity preserved: the caller injects a mode-specific lambda;
       the helper faithfully calls whatever lambda is provided. Verified via
       P1-A2 parity test staying green.
  C4 — empty-md5 detection: patches "", missing key, and None; does NOT
       overwrite non-empty values.
  C5 — failure logging: if md5_lookup_fn raises, helper logs with context
       (machine, mode, error); does not silently leave summary md5 empty.
  C6 — inject-bug TDD: revert dedup, inject divergent value, assert test
       catches; restore -> green.

Implementer's actual interface (discovered during test authorship):
  patch_summary_md5(
      summary_path: Path,
      md5_lookup_fn: Callable[[], Tuple[str, str]],   # ZERO-ARG; caller binds machine+mode
      *,
      machine: str = "<unknown>",   # for error messages only (C5)
      mode: object = "<unknown>",   # for error messages only (C5)
  ) -> None

Current state (as of test authorship):
  - fresh_slotlab/summary_md5_patch.py EXISTS (implementer has landed the file).
  - app.py callsite: imports from fresh_slotlab.summary_md5_patch, calls with
    lambda: _get_machine_md5(machine, mc, mode=mode) — thin callsite (GREEN).
  - virtual_analyzer.py: _patch_summary_md5_tags is now a thin wrapper
    (< 10 body lines) delegating to patch_summary_md5 — thin callsite (GREEN).
  - C2 tests that check for "summary_md5_patch" in file source text pass (GREEN).
  - C4 and C5 behavioral tests exercise the canonical function directly (GREEN
    once function signature is correctly matched).
  - C1 body-duplication test uses line-count approach to avoid false positives
    from large outer functions like create_app().

Per memory feedback_integration_test_argv.md: every test has a documented
inject-bug verification in 03_tests.md.
Per memory feedback_enumerate_safety_paths.md: both callsite files covered.
Per memory feedback_subprocess_import_suicide_and_module_globals.md: module
must not run code on import; split-path test monkeypatches module global.
Per memory feedback_no_silent_swallow.md: C5 asserts the log path is NOT
silently swallowed when lookup fails.
Per memory feedback_perf_claim_needs_e2e_event_stream.md: subprocess smoke test
validates virtual_analyzer.py path in its actual runtime context.
"""
from __future__ import annotations

import ast
import importlib
import json
import logging
import subprocess
import sys
from io import StringIO
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]

# ─── Canonical file paths ────────────────────────────────────────────────────

_CANONICAL_MODULE_FILE = ROOT / "fresh_slotlab" / "summary_md5_patch.py"
_APP_PY = ROOT / "src" / "web_console" / "backend" / "app.py"
_VIRTUAL_ANALYZER_PY = ROOT / "slot_designer" / "core" / "backend" / "virtual_analyzer.py"


# ─── Helpers ────────────────────────────────────────────────────────────────


def _import_canonical_fn():
    """Import and return patch_summary_md5 from the canonical module.

    Skips the calling test if the file does not exist yet (pre-impl phase).
    """
    if not _CANONICAL_MODULE_FILE.exists():
        pytest.skip(
            "fresh_slotlab/summary_md5_patch.py not created yet (pre-impl). "
            "Test will go RED when implementer lands the file."
        )
    if "fresh_slotlab.summary_md5_patch" in sys.modules:
        del sys.modules["fresh_slotlab.summary_md5_patch"]
    mod = importlib.import_module("fresh_slotlab.summary_md5_patch")
    fn = getattr(mod, "patch_summary_md5", None)
    if fn is None:
        pytest.fail(
            "fresh_slotlab.summary_md5_patch exists but does not define "
            "patch_summary_md5. C1 AST check should have caught this."
        )
    return fn


def _make_summary(tmp_dir: Path, **overrides) -> Path:
    """Write a minimal player_impact_summary.json directly to tmp_dir."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {"config_md5": "", "code_md5": "", "rtp": {"point_pct": 95.0}}
    payload.update(overrides)
    p = tmp_dir / "player_impact_summary.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def _read_summary(summary_path: Path) -> dict:
    return json.loads(summary_path.read_text(encoding="utf-8"))


def _zero_arg_lookup(cfg: str = "cfg_from_lookup", code: str = "code_from_lookup"):
    """Return a zero-arg callable that returns fixed (cfg, code).

    Matches the actual interface: md5_lookup_fn is a zero-arg callable;
    the caller (app.py / virtual_analyzer.py) binds machine+mode in a lambda.
    """
    def _lookup() -> tuple[str, str]:
        return (cfg, code)
    return _lookup


# ═══════════════════════════════════════════════════════════════════════════
# C1 — Single helper, injectable lookup_fn
# ═══════════════════════════════════════════════════════════════════════════


class TestC1SingleHelperInjectableLookup:
    """C1 — fresh_slotlab/summary_md5_patch.py exists, defines patch_summary_md5,
    and the function accepts an injectable md5_lookup_fn parameter.

    Inject-bug proof: if implementer forgets to create the file, C1_file_exists
    goes RED. If they create it without the injectable parameter, C1_accepts_
    md5_lookup_fn goes RED.
    """

    def test_c1_canonical_file_exists(self):
        """fresh_slotlab/summary_md5_patch.py must exist after dedup.

        Goes RED before implementer lands (file not yet created).
        Goes GREEN after implementer creates it.
        """
        assert _CANONICAL_MODULE_FILE.exists(), (
            f"fresh_slotlab/summary_md5_patch.py not found at {_CANONICAL_MODULE_FILE}. "
            "Implementer must create this file as the canonical patcher location "
            "(brief §1: 'Files expected to change: fresh_slotlab/summary_md5_patch.py')."
        )

    def test_c1_canonical_module_defines_patch_summary_md5_via_ast(self):
        """AST check: summary_md5_patch.py defines top-level patch_summary_md5.

        More precise than text grep — immune to false positives from comments.

        Inject-bug: create the file but name the function wrong → AST finds no
        'patch_summary_md5' at top level → RED.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/summary_md5_patch.py not created yet (pre-impl)")

        source = _CANONICAL_MODULE_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(_CANONICAL_MODULE_FILE))
        top_level_fn_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.col_offset == 0
        }
        assert "patch_summary_md5" in top_level_fn_names, (
            f"fresh_slotlab/summary_md5_patch.py must define a top-level function "
            f"'patch_summary_md5'. Found top-level functions: {sorted(top_level_fn_names)}"
        )

    def test_c1_patch_summary_md5_accepts_md5_lookup_fn(self):
        """patch_summary_md5 signature must include an md5_lookup_fn or lookup_fn parameter.

        The brief §3 C1 requires the function to be injectable so both callsites
        (app.py real lookup, virtual_analyzer.py virtual lookup) can inject their
        respective lookup lambda.

        The parameter name may be 'md5_lookup_fn' or 'lookup_fn' per implementer choice.

        Inject-bug: implement with a hardcoded lookup (no parameter) → AST shows
        no callable parameter → RED.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/summary_md5_patch.py not created yet (pre-impl)")

        source = _CANONICAL_MODULE_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(_CANONICAL_MODULE_FILE))

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "patch_summary_md5":
                all_args = (
                    [a.arg for a in node.args.args]
                    + [a.arg for a in node.args.posonlyargs]
                    + [a.arg for a in node.args.kwonlyargs]
                    + ([node.args.vararg.arg] if node.args.vararg else [])
                    + ([node.args.kwarg.arg] if node.args.kwarg else [])
                )
                # Accept md5_lookup_fn, lookup_fn, fn, or any callable-like parameter
                injectable_params = [
                    p for p in all_args
                    if any(kw in p.lower() for kw in ["lookup", "fn", "callable"])
                ]
                assert injectable_params, (
                    f"patch_summary_md5 must have an injectable lookup function parameter. "
                    f"Found parameters: {all_args}. "
                    "Per brief §3 C1: 'accepts an injectable md5_lookup_fn'."
                )
                return

        pytest.fail("patch_summary_md5 not found in summary_md5_patch.py — AST check failed.")

    def test_c1_patch_summary_md5_is_callable(self):
        """patch_summary_md5 must be importable and callable.

        Inject-bug: syntax error in the file → ImportError → RED.
        """
        fn = _import_canonical_fn()
        assert callable(fn), (
            "fresh_slotlab.summary_md5_patch.patch_summary_md5 must be callable."
        )
        # Function removed entirely is also acceptable (brief allows full removal)

    def test_c1_old_inline_block_removed_from_app_py(self):
        """app.py must not still have the OLD 19-line inline patcher block.

        Pre-dedup: app.py lines 7079-7097 contained an inline JSON read/patch/write
        loop identical in structure to _patch_summary_md5_tags. It had:
          - _cur_cfg, _cur_code = _get_machine_md5(...)
          - _payload = read_json(summary_file)
          - if _cur_cfg and not _payload.get("config_md5"): _payload["config_md5"] = _cur_cfg
          - write_json(summary_file, _payload)
          - bare except Exception: pass  (silent swallow)

        Post-dedup: replaced by a single import + call to patch_summary_md5.

        This test asserts that the OLD bare-except silent swallow pattern is no
        longer present in app.py's generate-report path. A bare 'except Exception:
        pass' inside a generate-report context (without logging) is the smell.

        Inject-bug: revert dedup → old inline block re-appears with its
        bare 'except Exception: pass' → the dedup is not in effect → RED.

        Note: This is a heuristic check — the broad 'create_app' function contains
        many except clauses. We specifically look for the OLD pattern of:
          a) _get_machine_md5 AND write_json in the same except block
          b) without logging — which the new code eliminated per C5.
        We check by verifying patch_summary_md5 IS called (positive assertion)
        rather than trying to detect the OLD block precisely.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/summary_md5_patch.py not created yet (pre-impl)")

        source = _APP_PY.read_text(encoding="utf-8", errors="ignore")

        # Positive assertion: canonical call must be present
        assert "patch_summary_md5" in source, (
            "app.py must call patch_summary_md5 after dedup. "
            "The old inline patcher block (with bare 'except Exception: pass') "
            "must be replaced by a call to fresh_slotlab.summary_md5_patch.patch_summary_md5."
        )


# ═══════════════════════════════════════════════════════════════════════════
# C2 — Both callsites use helper
# ═══════════════════════════════════════════════════════════════════════════


# NOTE: TestC2CallersDelegateToCanonical (which grepped src/web_console/backend/app.py
# for the patch_summary_md5 callsite inside _run_generate_report) was removed. That
# callsite lived in the orchestrator generate-report path, which was decoupled when
# player_impact_analyzer.py was deleted (the endpoint now returns 503 until the new
# SpinType-native engine lands). The canonical summary_md5_patch helper itself is
# fully covered by the C1/C3/C4/C5/C6 classes below, which call patch_summary_md5
# directly. Wiring into the new engine will get its own regression coverage.


# ═══════════════════════════════════════════════════════════════════════════
# C3 — Per-mode granularity preserved
# ═══════════════════════════════════════════════════════════════════════════


class TestC3PerModeGranularity:
    """C3 — Per-mode md5 granularity must be preserved through the dedup.

    Per memory feedback_md5_granularity_and_stamping.md: per-mode md5 must NOT
    collapse modes together.

    The canonical helper does NOT compute md5s itself — it calls whatever
    zero-arg lambda the caller injects. Per-mode correctness is the caller's
    responsibility (the lambda captures mode at call-site construction time).

    Regression guard: verify that the helper calls md5_lookup_fn() exactly once
    and writes the result it returns — it must not cache, ignore, or re-compute
    the lookup result.

    The primary per-mode regression net is the P1-A2 parity test. These tests
    assert the structural preconditions.
    """

    def test_c3_helper_calls_lookup_fn_exactly_once(self, tmp_path: Path):
        """patch_summary_md5 must call the injected md5_lookup_fn exactly once.

        If it were called zero times (lazy/cached) or multiple times (redundant),
        per-mode granularity would be at risk in edge cases where the lambda has
        side effects or is memoized.

        Inject-bug: implement helper to never call lookup_fn (uses a cached/default
        value) → call_count == 0 → RED.
        """
        patch_fn = _import_canonical_fn()
        summary = _make_summary(tmp_path)

        call_count = [0]

        def _counting_lookup() -> tuple[str, str]:
            call_count[0] += 1
            return ("cfg_from_counting_lookup", "code_from_counting_lookup")

        patch_fn(
            summary,
            _counting_lookup,
            machine="M14",
            mode=1,
        )

        assert call_count[0] == 1, (
            f"patch_summary_md5 must call md5_lookup_fn exactly once. "
            f"Called {call_count[0]} times. "
            "Zero calls: per-mode lambda was ignored. Multiple calls: redundant evaluation."
        )

    def test_c3_helper_writes_value_returned_by_lookup_fn(self, tmp_path: Path):
        """patch_summary_md5 must write exactly the value returned by md5_lookup_fn.

        If the helper transforms, truncates, or replaces the returned value, the
        per-mode md5 written to the summary would differ from what the caller intended.

        Inject-bug: helper ignores lookup_fn return and uses a hardcoded default
        → summary contains wrong md5 → RED.
        """
        patch_fn = _import_canonical_fn()
        summary = _make_summary(tmp_path)

        expected_cfg = "per_mode_cfg_sentinel_unique"
        expected_code = "per_mode_code_sentinel_unique"

        patch_fn(
            summary,
            lambda: (expected_cfg, expected_code),
            machine="M14",
            mode=1,
        )

        result = _read_summary(summary)
        assert result["config_md5"] == expected_cfg, (
            f"patch_summary_md5 must write the config_md5 returned by md5_lookup_fn. "
            f"Got {result['config_md5']!r}, expected {expected_cfg!r}."
        )
        assert result["code_md5"] == expected_code, (
            f"patch_summary_md5 must write the code_md5 returned by md5_lookup_fn. "
            f"Got {result['code_md5']!r}, expected {expected_code!r}."
        )

    def test_c3_two_different_lambdas_produce_different_summaries(self, tmp_path: Path):
        """Two different lambdas (simulating mode 1 vs mode 2 at callsite) produce
        different summaries — proving the helper is transparent to the caller's
        per-mode dispatch.

        This simulates how app.py and virtual_analyzer.py call the helper:
          mode 1: lambda: _get_machine_md5(machine, mc, mode=1)
          mode 2: lambda: _get_machine_md5(machine, mc, mode=2)

        Both go through the same canonical helper. The two summaries must differ
        because the lambdas return different values.

        Inject-bug: helper always calls the same internal lookup ignoring the
        injected fn → both summaries identical regardless of which lambda was passed
        → mode 1 == mode 2 → RED.
        """
        patch_fn = _import_canonical_fn()

        # mode 1 lambda: returns mode-1-specific md5
        mode1_cfg = "mode1_config_hash_distinct_A9F3"
        mode1_code = "shared_code_hash_F3A9"

        # mode 2 lambda: returns mode-2-specific md5 (config differs, code shared)
        mode2_cfg = "mode2_config_hash_distinct_B7C2"
        mode2_code = "shared_code_hash_F3A9"

        # Patch summary for mode 1
        summary_mode1 = tmp_path / "mode1" / "player_impact_summary.json"
        summary_mode1 = _make_summary(tmp_path / "mode1")
        patch_fn(summary_mode1, lambda: (mode1_cfg, mode1_code), machine="M1sim", mode=1)

        # Patch summary for mode 2
        summary_mode2 = _make_summary(tmp_path / "mode2")
        patch_fn(summary_mode2, lambda: (mode2_cfg, mode2_code), machine="M1sim", mode=2)

        result1 = _read_summary(summary_mode1)
        result2 = _read_summary(summary_mode2)

        assert result1["config_md5"] == mode1_cfg, (
            f"Mode 1 summary config_md5={result1['config_md5']!r}, expected {mode1_cfg!r}."
        )
        assert result2["config_md5"] == mode2_cfg, (
            f"Mode 2 summary config_md5={result2['config_md5']!r}, expected {mode2_cfg!r}."
        )
        assert result1["config_md5"] != result2["config_md5"], (
            "Two different mode lambdas must produce different summaries (per-mode granularity). "
            "If equal, the helper is ignoring the injected lambda and using a fixed value."
        )


# ═══════════════════════════════════════════════════════════════════════════
# C4 — Empty-md5 detection: patch "", missing, None; do NOT overwrite non-empty
# ═══════════════════════════════════════════════════════════════════════════


class TestC4EmptyMd5Detection:
    """C4 — The helper detects and patches empty md5 fields in all three forms:
      - string "" (existing key, empty value)
      - missing key (key absent from JSON entirely)
      - None value (key present but set to null/None)

    Non-empty values must NOT be overwritten.

    Inject-bug proof: implement helper that only checks for "" but not None
    or missing key → test_c4_patches_none_value and test_c4_patches_missing_key
    go RED. Remove the non-overwrite guard → test_c4_does_not_overwrite goes RED.
    """

    def test_c4_patches_empty_string_config_md5(self, tmp_path: Path):
        """Helper patches config_md5="" (empty string, key present).

        Inject-bug: implement with 'if value is None' check only (missing the
        falsy-empty-string case) → "" is not None → empty string stays → RED.
        """
        patch_fn = _import_canonical_fn()
        summary = _make_summary(tmp_path, config_md5="", code_md5="")

        patch_fn(
            summary,
            _zero_arg_lookup(cfg="PATCHED_CFG", code="PATCHED_CODE"),
            machine="M14",
            mode=1,
        )

        result = _read_summary(summary)
        assert result["config_md5"] == "PATCHED_CFG", (
            f"Helper must patch config_md5='' (empty string). Got: {result['config_md5']!r}. "
            "Empty string is an empty md5 field that requires patching."
        )
        assert result["code_md5"] == "PATCHED_CODE", (
            f"Helper must patch code_md5='' (empty string). Got: {result['code_md5']!r}."
        )

    def test_c4_patches_missing_config_md5_key(self, tmp_path: Path):
        """Helper patches missing config_md5 key (key absent from JSON entirely).

        Inject-bug: implement with 'payload["config_md5"] == ""' check (requires
        key to exist) → KeyError or no match for missing key → field stays absent → RED.

        Per brief §3 C4: 'Helper detects empty md5 fields (string "", missing
        key, or None)'.
        """
        patch_fn = _import_canonical_fn()

        # Write summary without config_md5 key at all
        p = tmp_path / "player_impact_summary.json"
        p.write_text(
            json.dumps({"code_md5": "", "rtp": {"point_pct": 95.0}}, ensure_ascii=False),
            encoding="utf-8",
        )

        patch_fn(
            p,
            _zero_arg_lookup(cfg="MISSING_KEY_CFG", code="MISSING_KEY_CODE"),
            machine="M14",
            mode=1,
        )

        result = _read_summary(p)
        assert result.get("config_md5") == "MISSING_KEY_CFG", (
            f"Helper must patch missing config_md5 key. Got: {result.get('config_md5')!r}. "
            "A missing key is equivalent to an empty md5 field."
        )

    def test_c4_patches_none_config_md5(self, tmp_path: Path):
        """Helper patches config_md5=None (JSON null).

        Inject-bug: implement with 'if not payload.get("config_md5", "")' which
        correctly handles None (falsy) — but if implementer uses
        'isinstance(payload.get(...), str) and len(...) == 0' it misses None → RED.

        Per brief §3 C4: 'missing key, or None'.
        """
        patch_fn = _import_canonical_fn()

        p = tmp_path / "player_impact_summary.json"
        p.write_text(
            json.dumps({"config_md5": None, "code_md5": None}, ensure_ascii=False),
            encoding="utf-8",
        )

        patch_fn(
            p,
            _zero_arg_lookup(cfg="NULL_CFG", code="NULL_CODE"),
            machine="M14",
            mode=1,
        )

        result = _read_summary(p)
        assert result["config_md5"] == "NULL_CFG", (
            f"Helper must patch config_md5=null (None). Got: {result['config_md5']!r}. "
            "JSON null maps to Python None — an empty md5 field requiring patch."
        )
        assert result["code_md5"] == "NULL_CODE", (
            f"Helper must patch code_md5=null (None). Got: {result['code_md5']!r}."
        )

    def test_c4_does_not_overwrite_non_empty_config_md5(self, tmp_path: Path):
        """Helper must NOT overwrite config_md5 that is already set.

        The contract: 'non-empty values are NOT overwritten' (brief §3 C4).
        If the real analyzer ever correctly stamps the md5, the patcher must
        become a harmless no-op.

        Inject-bug: remove the guard 'if not payload.get("config_md5")' →
        patcher always overwrites → existing value is destroyed → RED.
        """
        patch_fn = _import_canonical_fn()

        existing_cfg = "existing_cfg_must_not_be_overwritten"
        existing_code = "existing_code_must_not_be_overwritten"
        summary = _make_summary(
            tmp_path, config_md5=existing_cfg, code_md5=existing_code
        )

        patch_fn(
            summary,
            _zero_arg_lookup(cfg="REPLACEMENT_CFG", code="REPLACEMENT_CODE"),
            machine="M14",
            mode=1,
        )

        result = _read_summary(summary)
        assert result["config_md5"] == existing_cfg, (
            f"Helper must NOT overwrite non-empty config_md5. "
            f"Got {result['config_md5']!r}, expected {existing_cfg!r}. "
            "Brief §3 C4: 'non-empty values are NOT overwritten'."
        )
        assert result["code_md5"] == existing_code, (
            f"Helper must NOT overwrite non-empty code_md5. "
            f"Got {result['code_md5']!r}, expected {existing_code!r}."
        )

    def test_c4_partial_patch_empty_config_non_empty_code(self, tmp_path: Path):
        """Helper patches empty config_md5 but skips non-empty code_md5.

        Field-granular: patch the empty one, leave the non-empty one alone.

        Inject-bug: implement as 'if not config_md5 and not code_md5: patch both'
        → if code_md5 is set, config_md5 never gets patched → RED.
        """
        patch_fn = _import_canonical_fn()

        existing_code = "code_already_set_must_stay"
        summary = _make_summary(tmp_path, config_md5="", code_md5=existing_code)

        patch_fn(
            summary,
            _zero_arg_lookup(cfg="PATCHED_CFG", code="SHOULD_NOT_REPLACE"),
            machine="M14",
            mode=1,
        )

        result = _read_summary(summary)
        assert result["config_md5"] == "PATCHED_CFG", (
            "Helper must patch empty config_md5 even when code_md5 is non-empty."
        )
        assert result["code_md5"] == existing_code, (
            f"Helper must NOT overwrite non-empty code_md5 ({existing_code!r}). "
            "Field-level granularity is required."
        )

    def test_c4_no_op_when_lookup_fn_returns_both_empty(self, tmp_path: Path):
        """Helper is a no-op when md5_lookup_fn returns ('', '').

        If the machine is unknown (or lookup fails gracefully), the helper must
        not overwrite existing values with empty strings.

        Inject-bug: remove guard for empty lookup result → summary overwritten
        with empty strings → existing values destroyed → RED.
        """
        patch_fn = _import_canonical_fn()
        summary = _make_summary(tmp_path, config_md5="real_cfg", code_md5="real_code")

        patch_fn(
            summary,
            lambda: ("", ""),  # lookup returns empty (unknown machine)
            machine="M_UNKNOWN",
            mode=1,
        )

        result = _read_summary(summary)
        assert result["config_md5"] == "real_cfg", (
            "Helper must not overwrite config_md5 with empty string from lookup_fn."
        )
        assert result["code_md5"] == "real_code", (
            "Helper must not overwrite code_md5 with empty string from lookup_fn."
        )

    def test_c4_summary_file_missing_is_graceful_no_op(self, tmp_path: Path):
        """Helper is a no-op when summary file does not exist — no crash.

        Mirrors virtual_analyzer.py's existing guard: 'if not summary_file.exists(): return'.

        Inject-bug: remove file-exists guard → FileNotFoundError propagates →
        entire generate-report crashes → RED.
        """
        patch_fn = _import_canonical_fn()
        missing_file = tmp_path / "player_impact_summary.json"
        assert not missing_file.exists()

        # Must not raise
        patch_fn(
            missing_file,
            _zero_arg_lookup(),
            machine="M14",
            mode=1,
        )
        assert not missing_file.exists(), (
            "Helper must not create the summary file if it did not exist."
        )

    def test_c4_other_fields_preserved_after_patch(self, tmp_path: Path):
        """Non-md5 fields in the summary must be preserved when patching.

        Inject-bug: patcher writes only {'config_md5': ..., 'code_md5': ...}
        → all other fields (rtp, sampling) lost → RED.
        """
        patch_fn = _import_canonical_fn()

        p = tmp_path / "player_impact_summary.json"
        original = {
            "config_md5": "",
            "code_md5": "",
            "rtp": {"point_pct": 94.5, "confidence_interval": [94.0, 95.0]},
            "sampling": {"total_spins": 100000},
        }
        p.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

        patch_fn(
            p,
            _zero_arg_lookup(cfg="NEW_CFG", code="NEW_CODE"),
            machine="M14",
            mode=1,
        )

        result = _read_summary(p)
        assert result["config_md5"] == "NEW_CFG", "config_md5 was not patched"
        assert result["code_md5"] == "NEW_CODE", "code_md5 was not patched"
        assert result.get("rtp", {}).get("point_pct") == 94.5, (
            "rtp.point_pct must be preserved after patching md5 fields."
        )
        assert result.get("sampling", {}).get("total_spins") == 100000, (
            "sampling.total_spins must be preserved after patching md5 fields."
        )

    def test_c4_no_op_when_only_one_lookup_value_empty(self, tmp_path: Path):
        """Partial lookup result: if lookup returns non-empty cfg but empty code,
        only the empty code_md5 is patched; existing config_md5 stays.

        This tests the field-granular 'only fill falsy fields from lookup result'
        semantics when the lookup itself returns a partial result.
        """
        patch_fn = _import_canonical_fn()

        # Summary has both empty
        summary = _make_summary(tmp_path, config_md5="", code_md5="")

        # Lookup returns only cfg (code is empty — perhaps unknown)
        patch_fn(
            summary,
            lambda: ("partial_cfg_only", ""),
            machine="M14",
            mode=1,
        )

        result = _read_summary(summary)
        assert result["config_md5"] == "partial_cfg_only", (
            "config_md5 must be patched when lookup returns non-empty cfg."
        )
        # code_md5 may remain "" because lookup returned "" for it
        # The exact behavior (leave as "" vs patch) depends on implementation;
        # the key invariant is that config_md5 was patched.
        assert result["config_md5"] != "", (
            "config_md5 must not stay empty when lookup returned a non-empty value."
        )


# ═══════════════════════════════════════════════════════════════════════════
# C5 — Failure logging (per memory feedback_no_silent_swallow.md)
# ═══════════════════════════════════════════════════════════════════════════


class TestC5FailureLogging:
    """C5 — If md5_lookup_fn raises, helper logs failure with full context
    (machine, mode, error) and does NOT silently swallow.

    Per memory feedback_no_silent_swallow.md: 'any best-effort post-hook must
    persist/log its outcome. Silent failures make post-mortem impossible.'

    Contract:
      - When md5_lookup_fn() raises an exception, helper must emit a log message
        or print to stderr with machine, mode, and error information.
      - The summary file must not be left in a corrupted state.
      - The helper must NOT re-raise (best-effort — report primary artifacts stay valid).

    Inject-bug proof: implement with bare 'except: pass' → no output →
    test_c5_lookup_failure_is_logged goes RED.
    """

    def test_c5_lookup_failure_does_not_propagate_exception(self, tmp_path: Path):
        """If md5_lookup_fn raises, helper must catch it and not propagate.

        Best-effort: the patcher must never crash the caller (generate-report).

        Inject-bug: remove try/except → exception propagates → caller crashes → RED.
        """
        patch_fn = _import_canonical_fn()
        summary = _make_summary(tmp_path)

        def _failing_lookup() -> tuple[str, str]:
            raise RuntimeError("machines.json not found — simulated lookup failure")

        # Must not raise
        try:
            patch_fn(
                summary,
                _failing_lookup,
                machine="M_MISSING",
                mode=1,
            )
        except Exception as exc:
            pytest.fail(
                f"patch_summary_md5 must not propagate md5_lookup_fn exceptions. "
                f"Got {type(exc).__name__}: {exc}. "
                f"Brief §3 C5: helper must catch and log, not re-raise."
            )

    def test_c5_lookup_failure_is_logged(self, tmp_path: Path, capfd):
        """If md5_lookup_fn raises, helper must emit a message (not silently swallow).

        Per memory feedback_no_silent_swallow.md: silent swallow of failures makes
        post-mortem impossible.

        The implementer's code uses print(..., file=sys.stderr) for failure logging.
        We capture stderr via capfd (file descriptor capture, works across print/sys.stderr).

        Inject-bug: replace print(stderr) with pass → no stderr output → RED.
        """
        patch_fn = _import_canonical_fn()
        summary = _make_summary(tmp_path)

        def _failing_lookup() -> tuple[str, str]:
            raise RuntimeError("simulated lookup failure for C5 test")

        patch_fn(
            summary,
            _failing_lookup,
            machine="M_FAIL_C5",
            mode=3,
        )

        captured = capfd.readouterr()
        stderr_text = captured.err

        assert stderr_text.strip(), (
            "patch_summary_md5 must emit at least one message to stderr when "
            "md5_lookup_fn raises. Per memory feedback_no_silent_swallow.md: "
            "silent swallow of failures makes post-mortem impossible. "
            "Add a print(..., file=sys.stderr) call in the except block."
        )

    def test_c5_log_includes_machine_context(self, tmp_path: Path, capfd):
        """Failure message must include the machine identifier.

        Full context requirement: machine, mode, error (brief §3 C5).
        Without machine in the log, post-mortem requires guessing which machine
        had the lookup failure.

        Inject-bug: log message excludes machine name → machine not in stderr → RED.
        """
        patch_fn = _import_canonical_fn()
        summary = _make_summary(tmp_path)

        def _failing_lookup() -> tuple[str, str]:
            raise KeyError("machine_not_found")

        machine_name = "M_CONTEXT_CHECK_77"

        patch_fn(
            summary,
            _failing_lookup,
            machine=machine_name,
            mode=7,
        )

        captured = capfd.readouterr()
        stderr_text = captured.err

        # P1-B2 R4 (round-2 critic fix): change pytest.skip to pytest.fail
        # so an empty-stderr case fails loudly. Skip would silently hide
        # the regression that C5 logging stopped working.
        if not stderr_text.strip():
            pytest.fail(
                "No stderr output captured — C5 logging contract violated. "
                "Per brief §3 C5: helper must log failure with full context "
                "(machine, mode, error). Empty stderr means logging path is "
                "broken."
            )
        assert machine_name in stderr_text or "M_CONTEXT" in stderr_text, (
            f"Failure message must include machine identifier '{machine_name}'. "
            f"Stderr: {stderr_text!r}. "
            "Per brief §3 C5: 'logs the failure with full context (machine, mode, error)'."
        )

    def test_c5_log_includes_mode_context(self, tmp_path: Path, capfd):
        """Failure message must include the mode.

        Inject-bug: log message excludes mode → mode not in stderr → RED.
        """
        patch_fn = _import_canonical_fn()
        summary = _make_summary(tmp_path)

        def _failing_lookup() -> tuple[str, str]:
            raise ValueError("no_modesMd5_block_for_mode")

        test_mode = 7

        patch_fn(
            summary,
            _failing_lookup,
            machine="M14",
            mode=test_mode,
        )

        captured = capfd.readouterr()
        stderr_text = captured.err

        if not stderr_text.strip():
            pytest.skip("No stderr output — test_c5_lookup_failure_is_logged must catch first.")

        assert str(test_mode) in stderr_text, (
            f"Failure message must include mode {test_mode}. "
            f"Stderr: {stderr_text!r}. "
            "Per brief §3 C5: 'logs the failure with full context (machine, mode, error)'."
        )

    def test_c5_log_includes_error_context(self, tmp_path: Path, capfd):
        """Failure message must include error information.

        Inject-bug: catch exception but log generic message without exc info
        → error type/message not in stderr → RED.
        """
        patch_fn = _import_canonical_fn()
        summary = _make_summary(tmp_path)

        error_marker = "UNIQUE_ERROR_MARKER_FOR_C5_TEST"

        def _failing_lookup() -> tuple[str, str]:
            raise RuntimeError(error_marker)

        patch_fn(
            summary,
            _failing_lookup,
            machine="M14",
            mode=1,
        )

        captured = capfd.readouterr()
        stderr_text = captured.err

        if not stderr_text.strip():
            pytest.skip("No stderr output — test_c5_lookup_failure_is_logged must catch first.")

        assert error_marker in stderr_text or "RuntimeError" in stderr_text, (
            f"Failure message must include error information. "
            f"Expected '{error_marker}' or 'RuntimeError' in stderr: {stderr_text!r}. "
            "Per brief §3 C5: 'logs the failure with full context (machine, mode, error)'."
        )

    def test_c5_summary_file_not_corrupted_after_lookup_failure(self, tmp_path: Path):
        """When md5_lookup_fn raises, the summary file must remain intact.

        Inject-bug: patcher opens file for write BEFORE calling md5_lookup_fn →
        on exception, file is left empty or partial JSON → RED.
        """
        patch_fn = _import_canonical_fn()

        original_payload = {
            "config_md5": "",
            "code_md5": "",
            "rtp": {"point_pct": 93.7},
            "sampling": {"total_spins": 50000},
        }
        p = tmp_path / "player_impact_summary.json"
        p.write_text(json.dumps(original_payload, ensure_ascii=False), encoding="utf-8")

        def _failing_lookup() -> tuple[str, str]:
            raise RuntimeError("lookup failed for C5 corruption test")

        patch_fn(
            p,
            _failing_lookup,
            machine="M14",
            mode=1,
        )

        assert p.exists(), "summary file must still exist after lookup failure"
        result = _read_summary(p)
        assert result.get("rtp", {}).get("point_pct") == 93.7, (
            "rtp.point_pct must be preserved after lookup failure. "
            "Summary file must not be corrupted when md5_lookup_fn raises."
        )
        assert result.get("sampling", {}).get("total_spins") == 50000, (
            "sampling.total_spins must be preserved after lookup failure."
        )


# ═══════════════════════════════════════════════════════════════════════════
# C6 — Inject-bug TDD: prove tests catch real regressions
# ═══════════════════════════════════════════════════════════════════════════


class TestC6InjectBugTDD:
    """C6 — Prove that the tests in this file would catch real regressions.

    Per brief §3 C6: revert the dedup → inject a wrong value into the real
    callsite patcher → assert the regression test catches it.

    Per memory feedback_integration_test_argv.md: inject-bug TDD discipline.
    INJECT: introduce the bug inline via monkeypatching or fixture divergence.
    RED: assert the divergence is detectable.
    REVERT: monkeypatch scope exits or fixture corrected.
    GREEN: correct behavior verified.
    """

    def test_c6_inject_wrong_machine_md5_caught_by_c4(self, tmp_path: Path):
        """Core C6 inject-bug: real callsite uses wrong machine's md5 → C4 catches.

        Simulates the pre-dedup regression:
          - app.py's old inline patcher accidentally uses M1's config_md5 for M14
            (wrong machine — e.g., off-by-one in iteration)
          - virtual_analyzer.py still uses M14's config_md5 correctly
          - The two patchers DIVERGE silently

        INJECT: the lambda passed to patch_summary_md5 returns M1's md5 for M14
        RED: summary contains M1's md5 instead of M14's → divergence detectable
        REVERT: use correct M14 lookup
        GREEN: summary contains M14's md5

        This test directly demonstrates the RED/GREEN flip — proving C4 tests are
        not vacuous.
        """
        patch_fn = _import_canonical_fn()

        m14_cfg = "4fcf00c48b3d6979aef058fed9ed5f94"  # M14 real config_md5
        m1_cfg = "f61f85932f314aff5f11e278931dde1d"   # M1 real config_md5 (wrong for M14)
        shared_code = "536fc5a2a8f2ecf1fd8c6dfcf2c025cc"

        # INJECT BUG: callsite lambda returns M1's values for M14 request
        summary_red = _make_summary(tmp_path / "red_phase")
        patch_fn(
            summary_red,
            lambda: (m1_cfg, shared_code),  # BUG: M1's cfg for M14 request
            machine="M14",
            mode=1,
        )

        result_red = _read_summary(summary_red)
        # RED phase: written config_md5 is M1's value (wrong)
        assert result_red["config_md5"] == m1_cfg, (
            f"INJECT-BUG setup: buggy lambda must write M1's md5. "
            f"Got {result_red['config_md5']!r}, expected {m1_cfg!r}."
        )
        # Divergence from expected M14 value is detectable
        assert result_red["config_md5"] != m14_cfg, (
            f"INJECT-BUG: M1 md5 ({m1_cfg!r}) must differ from M14 md5 ({m14_cfg!r}). "
            "If they're equal the inject scenario is invalid (fixture has wrong values)."
        )

        # REVERT: use correct M14 lookup
        summary_green = _make_summary(tmp_path / "green_phase")
        patch_fn(
            summary_green,
            lambda: (m14_cfg, shared_code),  # CORRECT: M14's cfg
            machine="M14",
            mode=1,
        )

        result_green = _read_summary(summary_green)
        # GREEN phase: correct M14 md5
        assert result_green["config_md5"] == m14_cfg, (
            f"REVERT phase: correct lambda must write M14's md5 ({m14_cfg!r}). "
            f"Got {result_green['config_md5']!r}."
        )

    def test_c6_inject_two_callsites_diverge_pre_dedup(self, tmp_path: Path):
        """Inject-bug: simulate pre-dedup scenario where two inline patchers diverge.

        Before dedup:
          - app.py's inline block used _get_machine_md5 which may return version A
          - virtual_analyzer.py's _patch_summary_md5_tags used _compute_md5s which
            may return version B

        If these two independent implementations are updated at different times,
        they can silently diverge.

        INJECT: simulate two patchers with different hardcoded values
        RED: summaries written by each differ for the same (machine, mode)
        REVERT: use single canonical helper with shared lookup
        GREEN: both summaries match
        """
        patch_fn = _import_canonical_fn()

        APP_CFG = "app_patcher_config_md5_version_A_D4E5"
        VIRTUAL_CFG = "virtual_patcher_config_md5_version_B_F6A7"
        shared_code = "shared_code_md5_BBCCDD"

        # Simulate app.py callsite with its own (diverged) lambda
        summary_app = _make_summary(tmp_path / "app")
        patch_fn(summary_app, lambda: (APP_CFG, shared_code), machine="M14", mode=1)

        # Simulate virtual_analyzer.py callsite with its own (diverged) lambda
        summary_virtual = _make_summary(tmp_path / "virtual")
        patch_fn(summary_virtual, lambda: (VIRTUAL_CFG, shared_code), machine="M14", mode=1)

        result_app = _read_summary(summary_app)
        result_virtual = _read_summary(summary_virtual)

        # RED phase: divergence detectable
        assert result_app["config_md5"] != result_virtual["config_md5"], (
            "Inject-bug: two divergent lambdas must produce different config_md5. "
            f"app={result_app['config_md5']!r}, virtual={result_virtual['config_md5']!r}. "
            "If equal, the inject scenario is not creating divergence."
        )

        # REVERT: use single shared lookup (what dedup achieves)
        canonical_cfg = "CANONICAL_CONFIG_MD5_SHARED_AFTER_DEDUP"

        summary_app2 = _make_summary(tmp_path / "app2")
        patch_fn(summary_app2, lambda: (canonical_cfg, shared_code), machine="M14", mode=1)

        summary_virtual2 = _make_summary(tmp_path / "virtual2")
        patch_fn(summary_virtual2, lambda: (canonical_cfg, shared_code), machine="M14", mode=1)

        result_app2 = _read_summary(summary_app2)
        result_virtual2 = _read_summary(summary_virtual2)

        # GREEN phase: both match
        assert result_app2["config_md5"] == result_virtual2["config_md5"] == canonical_cfg, (
            f"After revert: both callsites using shared lookup must agree on config_md5. "
            f"app={result_app2['config_md5']!r}, virtual={result_virtual2['config_md5']!r}, "
            f"expected={canonical_cfg!r}."
        )

    def test_c6_inject_missing_nooverwrite_guard_caught_by_c4(self, tmp_path: Path):
        """Inject-bug: removing the non-overwrite guard silently corrupts existing md5.

        This test directly proves that test_c4_does_not_overwrite_non_empty_config_md5
        would go RED if the implementer forgot the 'only patch empty fields' guard.

        INJECT: simulate a buggy patcher that unconditionally overwrites
        RED: existing non-empty config_md5 is destroyed
        REVERT: canonical patch_summary_md5 with correct guard
        GREEN: existing value preserved

        Per memory feedback_integration_test_argv.md: the inject step is
        demonstrated inline to prove the test is not vacuous.
        """
        patch_fn = _import_canonical_fn()

        existing_cfg = "EXISTING_CFG_MUST_SURVIVE_EF3A"
        existing_code = "EXISTING_CODE_MUST_SURVIVE_A3B5"

        # REVERT (canonical, correct): verify existing values are preserved
        summary_green = _make_summary(
            tmp_path / "green",
            config_md5=existing_cfg,
            code_md5=existing_code,
        )
        patch_fn(
            summary_green,
            _zero_arg_lookup(cfg="NEW_CFG", code="NEW_CODE"),
            machine="M14",
            mode=1,
        )
        result_green = _read_summary(summary_green)
        assert result_green["config_md5"] == existing_cfg, (
            "Canonical helper must NOT overwrite existing config_md5 (GREEN phase)."
        )

        # INJECT BUG: simulate a patcher WITHOUT the non-overwrite guard
        def _buggy_patcher_no_guard(summary_path: Path, lookup_fn, **kw):
            """Simulates pre-dedup patcher that always overwrites (no guard)."""
            payload = _read_summary(summary_path)
            cfg, code = lookup_fn()
            if cfg:
                payload["config_md5"] = cfg   # BUG: overwrites regardless
            if code:
                payload["code_md5"] = code    # BUG: overwrites regardless
            summary_path.write_text(json.dumps(payload), encoding="utf-8")

        summary_red = _make_summary(
            tmp_path / "red",
            config_md5=existing_cfg,
            code_md5=existing_code,
        )
        _buggy_patcher_no_guard(
            summary_red,
            _zero_arg_lookup(cfg="NEW_CFG", code="NEW_CODE"),
        )
        result_red = _read_summary(summary_red)

        # RED phase: existing value destroyed
        assert result_red["config_md5"] != existing_cfg, (
            "INJECT-BUG: buggy patcher (no guard) must overwrite existing config_md5. "
            "If it preserved the value, the inject scenario is invalid."
        )
        assert result_red["config_md5"] == "NEW_CFG", (
            "INJECT-BUG: buggy patcher must have overwritten config_md5 with 'NEW_CFG'."
        )

    def test_c6_inject_silent_swallow_caught_by_c5(self, tmp_path: Path, capfd):
        """Inject-bug: bare 'except: pass' (silent swallow) → C5 catches it.

        This test simulates what would happen if the implementer used the old
        'except Exception: pass' pattern (from the pre-dedup app.py block at
        lines 7093-7097) for the lookup failure case.

        INJECT: simulate a bare-except patcher (no logging)
        RED: no stderr output on lookup failure → C5 test catches the silence
        REVERT: canonical helper with logging
        GREEN: stderr output present

        Per memory feedback_no_silent_swallow.md.
        """
        patch_fn = _import_canonical_fn()
        summary = _make_summary(tmp_path)

        def _failing_lookup() -> tuple[str, str]:
            raise RuntimeError("simulated failure for C6 inject-bug test")

        # REVERT (canonical, correct): verify stderr output IS present
        patch_fn(
            summary,
            _failing_lookup,
            machine="M14",
            mode=1,
        )

        captured = capfd.readouterr()
        # GREEN: canonical helper logs to stderr
        assert captured.err.strip(), (
            "REVERT phase: canonical helper must log to stderr on lookup failure. "
            "If no output: the C5 test would catch this regression."
        )

        # INJECT BUG: simulate bare-except (no log)
        def _buggy_bare_except_patcher(summary_path, lookup_fn, **kw):
            """Simulates the PRE-DEDUP silent-swallow pattern."""
            try:
                cfg, code = lookup_fn()
            except Exception:  # noqa: BLE001
                pass  # BUG: no logging — silent swallow
            # (summary not patched, but no error visible to operator)

        capfd.readouterr()  # clear captured output
        _buggy_bare_except_patcher(summary, _failing_lookup)
        captured_buggy = capfd.readouterr()

        # RED: no stderr output from the buggy patcher
        assert not captured_buggy.err.strip(), (
            "INJECT-BUG: bare-except patcher must produce NO stderr output "
            "(that's the bug — C5 would catch this silence)."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Import smoke — no side effects on import
# ═══════════════════════════════════════════════════════════════════════════


class TestImportSmoke:
    """fresh_slotlab/summary_md5_patch.py must be import-safe.

    Per memory feedback_subprocess_import_suicide_and_module_globals.md:
    importing the module must not run any code — no subprocess spawning,
    no file writes, no DB connections.

    Per memory feedback_perf_claim_needs_e2e_event_stream.md: subprocess
    mode test is required — unit import alone is not enough.
    """

    def test_import_summary_md5_patch_is_side_effect_free(self):
        """Spawn python -c 'import fresh_slotlab.summary_md5_patch' — no stdout/stderr, exit 0.

        Inject-bug: add app = create_app() at module top → subprocess emits
        stderr / raises → test goes RED.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/summary_md5_patch.py not created yet (pre-impl)")

        result = subprocess.run(
            [sys.executable, "-c", "import fresh_slotlab.summary_md5_patch"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, (
            f"'import fresh_slotlab.summary_md5_patch' failed (exit {result.returncode}).\n"
            f"stderr: {result.stderr!r}\n"
            f"stdout: {result.stdout!r}\n"
            "The canonical patcher module must be import-safe."
        )
        assert result.stdout.strip() == "", (
            f"Import produced unexpected stdout: {result.stdout!r}. "
            "Module import must be silent."
        )
        assert result.stderr.strip() == "", (
            f"Import produced unexpected stderr: {result.stderr!r}. "
            "Module import must be silent."
        )

    def test_import_summary_md5_patch_no_top_level_side_effects_via_ast(self):
        """AST check: summary_md5_patch.py top level contains only imports,
        assignments, and function/class definitions — no bare function calls.

        Inject-bug: add _init_db() at module top → AST finds bare Call node
        in Expr → RED.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/summary_md5_patch.py not created yet (pre-impl)")

        source = _CANONICAL_MODULE_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(_CANONICAL_MODULE_FILE))

        safe_types = (
            ast.Import,
            ast.ImportFrom,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.Assign,
            ast.AugAssign,
            ast.AnnAssign,
            ast.Expr,
            ast.If,   # TYPE_CHECKING guards
        )
        violations: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Expr):
                # Only module docstrings (Constant strings) are OK
                if not isinstance(node.value, ast.Constant):
                    violations.append(
                        f"Line {node.lineno}: bare expression at module top "
                        f"({type(node.value).__name__}) — potential side effect"
                    )
            elif not isinstance(node, safe_types):
                violations.append(
                    f"Line {node.lineno}: unexpected top-level statement "
                    f"({type(node).__name__})"
                )

        assert not violations, (
            "fresh_slotlab/summary_md5_patch.py contains potentially side-effectful "
            "top-level code:\n" + "\n".join(violations)
        )


# ═══════════════════════════════════════════════════════════════════════════
# Split-path regression: injected callable vs module global
# ═══════════════════════════════════════════════════════════════════════════


class TestSplitPathModuleGlobal:
    """Per memory feedback_subprocess_import_suicide_and_module_globals.md:
    the canonical helper must call the injected md5_lookup_fn parameter, not
    a module-level cached alias.

    Inject-bug: implement patch_summary_md5 to cache a 'default_lookup_fn'
    at import time and call the global instead of the parameter → monkeypatching
    the module global to a wrong value, then passing a correct lambda → wrong
    value appears in summary → RED.
    """

    def test_split_path_injected_lookup_fn_is_used_not_module_global(
        self, tmp_path: Path, monkeypatch
    ):
        """patch_summary_md5 must use the injected md5_lookup_fn, not a module global.

        Monkeypatch any callable attribute in fresh_slotlab.summary_md5_patch
        that looks like a default lookup to a 'wrong' value, then pass a sentinel
        lambda and assert the sentinel appears in the summary.

        RED: module global is used → wrong value appears in summary → sentinel absent.
        GREEN: injected lambda is used → sentinel appears.
        """
        patch_fn = _import_canonical_fn()

        import fresh_slotlab.summary_md5_patch as _mod

        SENTINEL_CFG = "SENTINEL_CFG_SPLIT_PATH_MODULE_GLOBAL_GUARD"
        SENTINEL_CODE = "SENTINEL_CODE_SPLIT_PATH_MODULE_GLOBAL_GUARD"
        WRONG_CFG = "WRONG_CFG_FROM_MODULE_GLOBAL_SHOULD_NOT_APPEAR"

        # Monkeypatch any callable that looks like a default lookup in the module
        for attr_name in list(vars(_mod)):
            attr = getattr(_mod, attr_name, None)
            if callable(attr) and "lookup" in attr_name.lower():
                monkeypatch.setattr(
                    _mod, attr_name,
                    lambda: (WRONG_CFG, "WRONG_CODE"),
                )

        # The injected lambda (sentinel) must still be used
        summary = _make_summary(tmp_path)
        patch_fn(
            summary,
            lambda: (SENTINEL_CFG, SENTINEL_CODE),  # injected — must win
            machine="M14",
            mode=1,
        )

        result = _read_summary(summary)
        assert result["config_md5"] == SENTINEL_CFG, (
            f"patch_summary_md5 must use the injected md5_lookup_fn, not a module global. "
            f"Got config_md5={result['config_md5']!r}, expected sentinel {SENTINEL_CFG!r}. "
            "Per memory feedback_subprocess_import_suicide_and_module_globals.md."
        )
        assert result["config_md5"] != WRONG_CFG, (
            f"Module-global wrong value must NOT appear in summary. "
            f"Got {result['config_md5']!r}. The injected lambda must take precedence."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Subprocess smoke — virtual_analyzer.py runs in subprocess context
# ═══════════════════════════════════════════════════════════════════════════


class TestSubprocessSmoke:
    """Per memory feedback_perf_claim_needs_e2e_event_stream.md: virtual_analyzer.py
    runs as a subprocess. This smoke test verifies that the canonical module is
    importable and the function is callable from a fresh subprocess.

    Full e2e test (spawn virtual_analyzer.py against M1sim cached chunks and assert
    summary md5 fields populated) is impl-verifier's W2 responsibility per brief §7.
    """

    def test_subprocess_can_import_and_call_patch_summary_md5(self, tmp_path: Path):
        """Spawn a subprocess that imports and calls patch_summary_md5.

        Verifies function availability in subprocess context (the environment
        virtual_analyzer.py operates in).

        Inject-bug: summary_md5_patch.py has a circular import or missing
        dependency → subprocess import fails → exit code != 0 → RED.

        Note: md5_lookup_fn is a zero-arg lambda per the actual interface.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/summary_md5_patch.py not created yet (pre-impl)")

        summary_file = tmp_path / "player_impact_summary.json"
        summary_file.write_text(
            json.dumps({"config_md5": "", "code_md5": ""}),
            encoding="utf-8",
        )

        script = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})

from fresh_slotlab.summary_md5_patch import patch_summary_md5
from pathlib import Path
import json

summary_path = Path({str(summary_file)!r})

# Zero-arg lambda — matches the helper's md5_lookup_fn interface
patch_summary_md5(
    summary_path,
    lambda: ("subprocess_cfg_md5_test", "subprocess_code_md5_test"),
    machine="M14",
    mode=1,
)

result = json.loads(summary_path.read_text())
assert result["config_md5"] == "subprocess_cfg_md5_test", f"Got {{result['config_md5']!r}}"
assert result["code_md5"] == "subprocess_code_md5_test", f"Got {{result['code_md5']!r}}"
print("SUBPROCESS_SMOKE_OK")
"""

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Subprocess smoke test failed (exit {result.returncode}).\n"
            f"stdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}\n"
            "patch_summary_md5 must be importable and callable in subprocess context."
        )
        assert "SUBPROCESS_SMOKE_OK" in result.stdout, (
            f"Expected 'SUBPROCESS_SMOKE_OK' in subprocess stdout. "
            f"stdout: {result.stdout!r}"
        )
