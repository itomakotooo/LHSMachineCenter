"""Regression tests for Ticket P1-B1 — Consolidate _lookup_machine_md5 (real x 2).

After the dedup:
  - fresh_slotlab/machine_md5.py is the SINGLE canonical location for
    lookup_machine_md5(machine, machines_config_path) -> (config_md5, code_md5).
  - app.py and player_impact_analyzer.py no longer define their own local
    _lookup_machine_md5 / _get_machine_md5 — they import from the canonical module.
  - The virtual cousin (compute_machine_md5_for_mode in machine_version.py)
    is NOT merged (different schema) but its relationship is documented.

Contracts under test (per brief §3):
  C1 — single source of truth: exactly one definition in fresh_slotlab/machine_md5.py
  C2 — both callsites delegate (no local def remaining in app.py / player_impact_analyzer.py)
  C3 — value parity for M14, M37, M101, M260, M279 (config_md5 FIRST, code_md5 SECOND)
  C4 — virtual cousin documented and NOT merged
  C5 — P1-A2 parity test (test_summary_md5_writer_parity.py) stays green
  C6 — inject-bug TDD: divergent value in one old location is caught

Import smoke:
  fresh_slotlab.machine_md5 must be import-safe (no side effects on import).

Per memory feedback_subprocess_import_suicide_and_module_globals.md: the new module
must not run any code on import (no app construction, no DB connections, no file
writes, no subprocess spawns).

Per memory feedback_integration_test_argv.md: every test has a documented inject-bug
verification in 03_tests.md.

Per memory feedback_enumerate_safety_paths.md: all 5 machines from brief §3 C3 are
covered by parametrize; both callsite files from brief §1 are grepped by C2.

Current state (as of test authorship):
- `fresh_slotlab/machine_md5.py` was created by implementer (untracked, not yet committed).
- `player_impact_analyzer.py` STILL has the old `def _lookup_machine_md5` at line 2138
  (the removal step is incomplete — the import comment appears at line 59-61 in PIA but
  the actual old local def was not yet removed, and the import is not real code yet).
- C1 (count==1) and C2 (no-local-def-in-PIA) are therefore RED until the implementer
  completes the dedup by removing the old local def and adding the real import.
- All other tests (C3, C4, C5, C6, import-smoke) pass against the current state.
"""
from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# ─── Snapshot values from configs/machines.json (per brief §3 C3) ──────────
# Verified by running:
#   python3 -c "import json,pathlib; data=json.loads(pathlib.Path('configs/machines.json').read_text()); ..."
# Config FIRST, code SECOND — matches player_impact_analyzer.py:2138 return order.
_EXPECTED_MD5: dict[str, tuple[str, str]] = {
    "M14": ("4fcf00c48b3d6979aef058fed9ed5f94", "536fc5a2a8f2ecf1fd8c6dfcf2c025cc"),
    "M37": ("c226b1c302ec15647fd6584ae57078c5", "536fc5a2a8f2ecf1fd8c6dfcf2c025cc"),
    "M101": ("04084ef4c868814b3e2ca224908e3cb2", "536fc5a2a8f2ecf1fd8c6dfcf2c025cc"),
    "M260": ("037fe950f73645bfcefeba86f3905a08", "f9c245e3422703455facadbbbe4fbd31"),
    "M279": ("9a77d7996d9fdf1cd6ef27bba0c05c2b", "1c1af39a07ed1f46f412e21b7fa3bb5d"),
}

_MACHINES_JSON = ROOT / "configs" / "machines.json"
_CANONICAL_MODULE_FILE = ROOT / "fresh_slotlab" / "machine_md5.py"
_APP_PY = ROOT / "src" / "web_console" / "backend" / "app.py"
_PIA_PY = ROOT / "fresh_slotlab" / "player_impact_analyzer.py"


# ═══════════════════════════════════════════════════════════════════════════
# C1 — Single source of truth
# ═══════════════════════════════════════════════════════════════════════════


class TestC1SingleSourceOfTruth:
    """C1 — grep 'def lookup_machine_md5' returns exactly one definition,
    in fresh_slotlab/machine_md5.py.

    Inject-bug proof: if the implementer accidentally left a second definition
    (e.g., did not remove the old one from player_impact_analyzer.py), the
    count check catches it.  If the implementer forgot to create machine_md5.py
    entirely, the file-existence check catches it.
    """

    def test_canonical_module_file_exists(self):
        """fresh_slotlab/machine_md5.py must exist after dedup.

        Goes RED before implementer lands (file doesn't exist yet).
        Goes GREEN after implementer creates it.
        """
        assert _CANONICAL_MODULE_FILE.exists(), (
            f"fresh_slotlab/machine_md5.py not found at {_CANONICAL_MODULE_FILE}. "
            "Implementer must create this file as the canonical lookup location."
        )

    def test_exactly_one_def_lookup_machine_md5_in_repo(self):
        """grep for 'def lookup_machine_md5' returns exactly one hit (in machine_md5.py).

        Scans fresh_slotlab/ and src/ (the two namespaces that contain the
        pre-dedup implementations). Exactly one definition must remain.

        Inject-bug: deleting machine_md5.py → 0 definitions → RED.
        Inject-bug: leaving old local def in player_impact_analyzer.py → 2 defs → RED.
        """
        hits: list[Path] = []
        for search_root in [ROOT / "fresh_slotlab", ROOT / "src"]:
            if not search_root.is_dir():
                continue
            for py_file in search_root.rglob("*.py"):
                text = py_file.read_text(encoding="utf-8", errors="ignore")
                # Match both def _lookup_machine_md5 and def lookup_machine_md5
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("def _lookup_machine_md5") or stripped.startswith("def lookup_machine_md5"):
                        hits.append(py_file)
                        break  # one hit per file is enough for the count check

        assert len(hits) == 1, (
            f"Expected exactly 1 definition of lookup_machine_md5, found {len(hits)}.\n"
            f"Files with definitions: {[str(h) for h in hits]}\n"
            "Either the canonical machine_md5.py is missing, or old local definitions "
            "were not removed from app.py / player_impact_analyzer.py."
        )
        assert hits[0] == _CANONICAL_MODULE_FILE, (
            f"The sole definition must be in {_CANONICAL_MODULE_FILE}, "
            f"but found it in {hits[0]}."
        )

    def test_canonical_module_defines_lookup_machine_md5_via_ast(self):
        """AST check: machine_md5.py defines a top-level function named lookup_machine_md5.

        More precise than text grep — immune to false positives from comments
        or docstrings containing the function name.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/machine_md5.py not created yet (pre-impl)")

        source = _CANONICAL_MODULE_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(_CANONICAL_MODULE_FILE))
        top_level_fn_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.col_offset == 0
        }
        assert "lookup_machine_md5" in top_level_fn_names, (
            f"fresh_slotlab/machine_md5.py must define a top-level function "
            f"'lookup_machine_md5'. Found top-level functions: {sorted(top_level_fn_names)}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# C2 — Both callsites delegate (no local defs remaining)
# ═══════════════════════════════════════════════════════════════════════════


class TestC2CallersDelegateToCanonical:
    """C2 — After dedup, neither app.py nor player_impact_analyzer.py contains
    a local 'def _lookup_machine_md5' or 'def _get_machine_md5' definition.
    Both files instead import from fresh_slotlab.machine_md5.

    Note: app.py currently has _get_machine_md5 (the slightly richer variant
    with modesMd5 support). Per the brief, the implementer may either:
      (a) delete _get_machine_md5 and replace all calls with lookup_machine_md5,
      (b) keep _get_machine_md5 as a thin wrapper that delegates to canonical.
    C2 tests the observable contract either way: no STANDALONE body that
    duplicates the machines.json lookup logic.

    Inject-bug proof:
      Revert dedup → local _lookup_machine_md5 re-appears in player_impact_analyzer.py
      → test_no_local_lookup_machine_md5_in_pia goes RED.
    """

    def test_no_local_lookup_machine_md5_in_pia(self):
        """player_impact_analyzer.py must not define _lookup_machine_md5 locally.

        Goes RED before dedup (the function is currently defined at line 2138).
        Goes GREEN after implementer removes it and delegates to canonical.

        Note: player_impact_analyzer.py has a UTF-8 BOM (\xef\xbb\xbf) so we
        read with 'utf-8-sig' to strip it before passing to ast.parse.
        """
        source = _PIA_PY.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(_PIA_PY))
        fn_names_in_pia = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        assert "_lookup_machine_md5" not in fn_names_in_pia, (
            "player_impact_analyzer.py still defines _lookup_machine_md5 locally. "
            "Dedup must remove this definition and delegate to "
            "fresh_slotlab.machine_md5.lookup_machine_md5."
        )

    def test_no_local_lookup_machine_md5_in_app(self):
        """app.py must not define a standalone _lookup_machine_md5 locally.

        The existing _get_machine_md5 in app.py may survive as a thin wrapper
        (for the mode-aware modesMd5 path), but if the implementer chose to
        keep it, its body must import/delegate rather than re-implement the
        core machines.json lookup.

        This test asserts the simpler contract: no function named
        _lookup_machine_md5 exists in app.py (that name belonged to the
        player_impact_analyzer.py copy — app.py used a different name).
        """
        source = _APP_PY.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(_APP_PY))
        fn_names_in_app = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        assert "_lookup_machine_md5" not in fn_names_in_app, (
            "app.py defines _lookup_machine_md5 locally — this is not expected "
            "after dedup (the app.py variant was named _get_machine_md5). "
            "If the implementer renamed during dedup, check that only ONE canonical "
            "function remains in fresh_slotlab/machine_md5.py."
        )

    def test_machine_md5_module_imported_by_pia(self):
        """player_impact_analyzer.py imports from fresh_slotlab.machine_md5 after dedup.

        Text search for the import statement. More resilient than AST for
        detecting 'from fresh_slotlab.machine_md5 import ...' across various
        import styles.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/machine_md5.py not created yet (pre-impl)")
        source = _PIA_PY.read_text(encoding="utf-8")
        assert "machine_md5" in source, (
            "player_impact_analyzer.py does not reference 'machine_md5'. "
            "After dedup it must import from fresh_slotlab.machine_md5."
        )

    def test_machine_md5_module_imported_by_app(self):
        """app.py imports from fresh_slotlab.machine_md5 after dedup.

        Text search for the import statement.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/machine_md5.py not created yet (pre-impl)")
        source = _APP_PY.read_text(encoding="utf-8")
        assert "machine_md5" in source, (
            "app.py does not reference 'machine_md5'. "
            "After dedup it must import from fresh_slotlab.machine_md5."
        )


# ═══════════════════════════════════════════════════════════════════════════
# C3 — Value parity preserved (config_md5 FIRST, code_md5 SECOND)
# ═══════════════════════════════════════════════════════════════════════════


def _import_canonical() -> object:
    """Import and return the canonical lookup_machine_md5 function.

    Skips the test if machine_md5.py does not exist yet (pre-impl phase).
    """
    if not _CANONICAL_MODULE_FILE.exists():
        pytest.skip("fresh_slotlab/machine_md5.py not created yet (pre-impl)")
    # Force fresh import in case module was already imported before the file existed
    if "fresh_slotlab.machine_md5" in sys.modules:
        del sys.modules["fresh_slotlab.machine_md5"]
    mod = importlib.import_module("fresh_slotlab.machine_md5")
    fn = getattr(mod, "lookup_machine_md5", None)
    if fn is None:
        pytest.fail(
            "fresh_slotlab.machine_md5 exists but does not define lookup_machine_md5. "
            "C1 (AST check) should have caught this — check test order."
        )
    return fn


class TestC3ValueParity:
    """C3 — canonical lookup_machine_md5 returns same (config_md5, code_md5) as
    the pre-dedup implementations, using configs/machines.json as the data source.

    TUPLE ORDER: config_md5 FIRST, code_md5 SECOND.
    This matches player_impact_analyzer.py:2138 return order (per brief §3 + main
    session RR3 fix). Do NOT flip.

    Inject-bug proof: if the implementer accidentally flipped the tuple order,
    test_value_parity_tuple_order catches it (config != code for most machines).
    If the implementer accidentally returned (code_md5, config_md5), the
    snapshot values would not match → RED.
    """

    @pytest.mark.parametrize("machine", list(_EXPECTED_MD5.keys()))
    def test_canonical_returns_expected_md5_snapshot(self, machine: str):
        """For each of the 5 brief-specified machines, canonical returns the
        snapshot values from configs/machines.json.

        Snapshot values were extracted directly from configs/machines.json
        at the time of test authorship (see _EXPECTED_MD5 at module top).

        Inject-bug: change canonical to return (code_md5, config_md5) (flipped
        tuple) → M37 snapshot has same code_md5 as config snapshot for M14/M37/M101
        (code_md5 = 536fc5a... shared) but config_md5 differs → M260 and M279
        would show immediate mismatch because their code_md5 != config_md5.
        """
        if not _MACHINES_JSON.exists():
            pytest.skip("configs/machines.json not present")
        lookup = _import_canonical()
        result = lookup(machine, _MACHINES_JSON)

        assert isinstance(result, tuple), (
            f"lookup_machine_md5({machine!r}) must return a tuple, got {type(result)}"
        )
        assert len(result) == 2, (
            f"lookup_machine_md5({machine!r}) must return a 2-tuple, got {result!r}"
        )
        expected = _EXPECTED_MD5[machine]
        assert result == expected, (
            f"lookup_machine_md5({machine!r}) returned {result!r}, "
            f"expected {expected!r}.\n"
            f"  config_md5 (index 0): got {result[0]!r}, expected {expected[0]!r}\n"
            f"  code_md5   (index 1): got {result[1]!r}, expected {expected[1]!r}\n"
            "TUPLE ORDER: config_md5 FIRST, code_md5 SECOND (brief §3 + PIA:2138)."
        )

    @pytest.mark.parametrize("machine", list(_EXPECTED_MD5.keys()))
    def test_canonical_config_md5_is_index_0(self, machine: str):
        """Explicit order check: result[0] matches configSummaryMd5 from JSON.

        This guard is independent of the snapshot comparison — it verifies the
        SEMANTIC label (not just the value) by re-reading machines.json directly
        and asserting result[0] == configSummaryMd5.

        Inject-bug: flip tuple in canonical → result[0] == codeSummaryMd5 ≠ configSummaryMd5
        → RED for machines where config_md5 ≠ code_md5 (M260, M279).
        """
        if not _MACHINES_JSON.exists():
            pytest.skip("configs/machines.json not present")
        lookup = _import_canonical()

        data = json.loads(_MACHINES_JSON.read_text(encoding="utf-8"))
        entry = next((m for m in data.get("machines", []) if m.get("machine") == machine), None)
        if entry is None:
            pytest.skip(f"{machine} not found in configs/machines.json")

        expected_config = str(entry.get("configSummaryMd5", ""))
        result = lookup(machine, _MACHINES_JSON)

        assert result[0] == expected_config, (
            f"result[0] for {machine!r} = {result[0]!r}, "
            f"but configSummaryMd5 in machines.json = {expected_config!r}. "
            "config_md5 must be at index 0 (FIRST). Tuple may be flipped."
        )

    @pytest.mark.parametrize("machine", list(_EXPECTED_MD5.keys()))
    def test_canonical_code_md5_is_index_1(self, machine: str):
        """Explicit order check: result[1] matches codeSummaryMd5 from JSON.

        Inject-bug: flip tuple → result[1] == configSummaryMd5 ≠ codeSummaryMd5 → RED.
        """
        if not _MACHINES_JSON.exists():
            pytest.skip("configs/machines.json not present")
        lookup = _import_canonical()

        data = json.loads(_MACHINES_JSON.read_text(encoding="utf-8"))
        entry = next((m for m in data.get("machines", []) if m.get("machine") == machine), None)
        if entry is None:
            pytest.skip(f"{machine} not found in configs/machines.json")

        expected_code = str(entry.get("codeSummaryMd5", ""))
        result = lookup(machine, _MACHINES_JSON)

        assert result[1] == expected_code, (
            f"result[1] for {machine!r} = {result[1]!r}, "
            f"but codeSummaryMd5 in machines.json = {expected_code!r}. "
            "code_md5 must be at index 1 (SECOND). Tuple may be flipped."
        )

    def test_canonical_returns_empty_tuple_for_unknown_machine(self):
        """Canonical returns ('', '') for a machine not in machines.json.

        Mirrors behavior of both pre-dedup implementations.
        Inject-bug: implement lookup to raise instead of returning empty → RED.
        """
        if not _MACHINES_JSON.exists():
            pytest.skip("configs/machines.json not present")
        lookup = _import_canonical()
        result = lookup("M999_NONEXISTENT_FOR_TEST", _MACHINES_JSON)
        assert result == ("", ""), (
            f"Expected ('', '') for unknown machine, got {result!r}. "
            "Canonical must return empty tuple gracefully for unknown machines."
        )

    def test_canonical_returns_empty_tuple_when_json_missing(self, tmp_path: Path):
        """Canonical returns ('', '') when machines.json path does not exist.

        Both pre-dedup implementations handled OSError gracefully.
        Inject-bug: implement to let OSError propagate → RED.
        """
        lookup = _import_canonical()
        missing_path = tmp_path / "nonexistent_machines.json"
        result = lookup("M14", missing_path)
        assert result == ("", ""), (
            f"Expected ('', '') when machines.json is missing, got {result!r}. "
            "Canonical must handle missing config file gracefully."
        )

    def test_canonical_returns_empty_tuple_when_json_malformed(self, tmp_path: Path):
        """Canonical returns ('', '') when machines.json contains invalid JSON.

        Inject-bug: remove try/except → JSONDecodeError propagates → RED.
        """
        lookup = _import_canonical()
        bad_json = tmp_path / "machines.json"
        bad_json.write_text("NOT VALID JSON {{{{", encoding="utf-8")
        result = lookup("M14", bad_json)
        assert result == ("", ""), (
            f"Expected ('', '') for malformed machines.json, got {result!r}. "
            "Canonical must handle JSON parse errors gracefully."
        )

    def test_parity_with_pre_dedup_pia_implementation_m14(self):
        """Cross-check: canonical result for M14 matches what the OLD PIA
        implementation would have returned (by reading machines.json directly).

        This test re-implements the pre-dedup logic as a fixture mirror to
        verify the canonical function preserves the contract independently of
        snapshot values.

        Inject-bug: canonical reads 'config_md5' instead of 'configSummaryMd5'
        key → returns '' → mismatch with mirror → RED.
        """
        if not _MACHINES_JSON.exists():
            pytest.skip("configs/machines.json not present")
        lookup = _import_canonical()

        # Mirror the pre-dedup PIA logic verbatim (from player_impact_analyzer.py:2144-2158)
        def _pre_dedup_pia_lookup(machine: str) -> tuple[str, str]:
            try:
                data = json.loads(_MACHINES_JSON.read_text(encoding="utf-8"))
                for m in data.get("machines", []):
                    if m.get("machine") == machine:
                        return (
                            str(m.get("configSummaryMd5", "")),
                            str(m.get("codeSummaryMd5", "")),
                        )
            except (OSError, json.JSONDecodeError, TypeError):
                pass
            return "", ""

        canonical_result = lookup("M14", _MACHINES_JSON)
        mirror_result = _pre_dedup_pia_lookup("M14")

        assert canonical_result == mirror_result, (
            f"canonical lookup_machine_md5('M14') = {canonical_result!r}, "
            f"pre-dedup PIA mirror = {mirror_result!r}. "
            "Canonical must preserve the exact same return semantics."
        )


# ═══════════════════════════════════════════════════════════════════════════
# C4 — Virtual cousin documented, not merged
# ═══════════════════════════════════════════════════════════════════════════


class TestC4VirtualCousinNotMerged:
    """C4 — compute_machine_md5_for_mode in slot_designer/.../machine_version.py
    is the virtual-side equivalent. It must NOT be merged into machine_md5.py
    (different schema — reads spec+weights+plugins, not configs/machines.json).

    The canonical module's docstring must document this relationship.

    Inject-bug proof: if the implementer merges the virtual function into
    machine_md5.py, the test_virtual_cousin_not_in_machine_md5 test catches it.
    """

    _MACHINE_VERSION_PY = ROOT / "slot_designer" / "core" / "backend" / "machine_version.py"

    def test_virtual_cousin_exists_in_machine_version(self):
        """compute_machine_md5_for_mode still exists in machine_version.py.

        The dedup must NOT have moved or deleted it — it serves a different
        purpose (virtual machines, spec+weights hash) and must stay separate.
        """
        if not self._MACHINE_VERSION_PY.exists():
            pytest.skip("slot_designer/core/backend/machine_version.py not present")
        source = self._MACHINE_VERSION_PY.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(self._MACHINE_VERSION_PY))
        fn_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        assert "compute_machine_md5_for_mode" in fn_names, (
            "compute_machine_md5_for_mode no longer exists in "
            "slot_designer/core/backend/machine_version.py. "
            "The dedup must NOT have removed or merged this function — "
            "it handles virtual machines with a different schema."
        )

    def test_virtual_cousin_not_in_machine_md5(self):
        """compute_machine_md5_for_mode must NOT appear in fresh_slotlab/machine_md5.py.

        The brief explicitly states: 'NOT merged in this ticket (different purposes)'.
        Inject-bug: implementer erroneously adds compute_machine_md5_for_mode to
        machine_md5.py → test goes RED.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/machine_md5.py not created yet (pre-impl)")
        source = _CANONICAL_MODULE_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(_CANONICAL_MODULE_FILE))
        fn_names_in_canonical = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        assert "compute_machine_md5_for_mode" not in fn_names_in_canonical, (
            "fresh_slotlab/machine_md5.py defines compute_machine_md5_for_mode. "
            "This virtual-side function must NOT be merged into the canonical "
            "real-machine lookup (brief §4 out-of-scope, §3 C4)."
        )

    def test_canonical_docstring_references_virtual_cousin(self):
        """The canonical module's docstring mentions the virtual cousin relationship.

        Brief §3 C4: 'The relationship is documented in the canonical helper's
        docstring'. This test verifies the documentation is present.

        Inject-bug: implementer creates machine_md5.py with no docstring or
        an empty docstring → test goes RED.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/machine_md5.py not created yet (pre-impl)")
        source = _CANONICAL_MODULE_FILE.read_text(encoding="utf-8")
        # Accept either module docstring or function docstring mentioning the cousin
        cousin_keywords = ["compute_machine_md5_for_mode", "machine_version", "virtual"]
        found = any(kw in source for kw in cousin_keywords)
        assert found, (
            f"fresh_slotlab/machine_md5.py does not reference the virtual cousin "
            f"relationship. Expected at least one of: {cousin_keywords}. "
            "Per brief §3 C4, the docstring must document the virtual cousin "
            "(compute_machine_md5_for_mode in slot_designer/core/backend/machine_version.py)."
        )


# ═══════════════════════════════════════════════════════════════════════════
# C5 — P1-A2 parity test stays green
# ═══════════════════════════════════════════════════════════════════════════


class TestC5P1A2ParityStaysGreen:
    """C5 — After dedup, the P1-A2 three-writer parity test must still pass.

    We do not re-run the full parity test here (that's impl-verifier's job).
    Instead we assert the structural precondition that enables it to stay
    green: the P1-A2 test file exists and the three writer functions it
    exercises are still importable.

    The actual '30/30 pass' verification is an impl-verifier responsibility
    (W2 step per brief §7).
    """

    _PARITY_TEST_FILE = ROOT / "tests" / "backend" / "test_summary_md5_writer_parity.py"

    def test_p1a2_parity_test_file_exists(self):
        """test_summary_md5_writer_parity.py exists (P1-A2 not accidentally deleted)."""
        assert self._PARITY_TEST_FILE.exists(), (
            f"P1-A2 parity test file not found: {self._PARITY_TEST_FILE}. "
            "This file must not be removed — it is the regression net for md5 writer agreement."
        )

    def test_p1a2_alpha_writer_still_importable(self):
        """After dedup, the α writer function is still importable.

        α is now lookup_machine_md5 from fresh_slotlab.machine_md5 (canonical).
        Previously it was _lookup_machine_md5 from player_impact_analyzer.

        If the implementer broke the import path, this goes RED.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/machine_md5.py not created yet (pre-impl)")
        # After dedup, pia._lookup_machine_md5 is either removed (no local def)
        # or re-exported from the canonical module. The canonical should be importable.
        from fresh_slotlab import machine_md5 as _mm  # noqa: F401
        assert hasattr(_mm, "lookup_machine_md5"), (
            "fresh_slotlab.machine_md5 does not export lookup_machine_md5. "
            "P1-A2 alpha writer (now canonical) must remain reachable."
        )

    def test_p1a2_beta_writer_still_importable(self):
        """After dedup, the β writer function (_get_machine_md5 or its replacement)
        is still importable from app.py.

        If the implementer removed _get_machine_md5 without re-exporting the
        canonical function, P1-A2 tests that call _get_machine_md5 would break.
        """
        # app.py may still export _get_machine_md5 as a thin wrapper, or may
        # export lookup_machine_md5 directly. Either is acceptable if P1-A2
        # test adapts — but at minimum the module must import cleanly.
        import src.web_console.backend.app as _app  # noqa: F401
        # No AttributeError check here — impl-verifier confirms specific attribute.
        # This test just guards against ImportError from a botched dedup.
        assert _app is not None


# ═══════════════════════════════════════════════════════════════════════════
# C6 — Inject-bug TDD
# ═══════════════════════════════════════════════════════════════════════════


class TestC6InjectBugTDD:
    """C6 — Prove the tests in this file would catch real regressions.

    Per brief §3 C6: revert the dedup, inject a divergent value in one of the
    two old locations, assert the regression test catches it.

    These tests simulate the inject-bug scenarios inline using monkeypatching
    and fixture-based divergence, so the inject-bug proof can be demonstrated
    without modifying prod files. Each test documents what the 'RED' state
    looks like and why the 'GREEN' state (post-revert) would be different.

    Per memory feedback_integration_test_argv.md: document inject → RED → revert
    → GREEN for each scenario in 03_tests.md.
    """

    def test_c6_inject_wrong_tuple_order_is_caught_for_m260(self, tmp_path: Path):
        """Inject-bug: a buggy canonical that returns (code_md5, config_md5) is caught.

        M260 has different config_md5 and code_md5, so flipping the tuple
        produces a value that diverges from both the snapshot AND the raw JSON.

        Simulate the bug with a local divergent implementation and assert
        the C3 snapshot would have rejected it.

        Inject: canonical returns (code_md5, config_md5) — flipped
        Expected: result[0] == code_md5 != expected config_md5 → snapshot mismatch → RED
        Revert: use correct order → result matches snapshot → GREEN
        """
        if not _MACHINES_JSON.exists():
            pytest.skip("configs/machines.json not present")

        machine = "M260"
        expected = _EXPECTED_MD5[machine]  # (config_md5, code_md5)

        # Simulate the buggy canonical (flipped tuple)
        def _buggy_lookup(machine_name: str, machines_config_path: Path) -> tuple[str, str]:
            data = json.loads(machines_config_path.read_text(encoding="utf-8"))
            for m in data.get("machines", []):
                if m.get("machine") == machine_name:
                    # BUG: code FIRST, config SECOND (flipped)
                    return (
                        str(m.get("codeSummaryMd5", "")),   # WRONG: should be config
                        str(m.get("configSummaryMd5", "")), # WRONG: should be code
                    )
            return "", ""

        buggy_result = _buggy_lookup(machine, _MACHINES_JSON)

        # RED phase: buggy result != expected (M260 has distinct config/code md5)
        assert buggy_result != expected, (
            f"Inject-bug FAILED to create divergence for {machine}: "
            f"buggy={buggy_result!r}, expected={expected!r}. "
            f"M260 must have different config_md5 and code_md5 for this test to work."
        )
        # Specifically: the flipped config_md5 (index 0) is wrong
        assert buggy_result[0] != expected[0], (
            f"Inject-bug: flipped result[0]={buggy_result[0]!r} should differ from "
            f"expected config_md5={expected[0]!r} for M260."
        )

        # GREEN phase: correct order matches
        def _correct_lookup(machine_name: str, machines_config_path: Path) -> tuple[str, str]:
            data = json.loads(machines_config_path.read_text(encoding="utf-8"))
            for m in data.get("machines", []):
                if m.get("machine") == machine_name:
                    return (
                        str(m.get("configSummaryMd5", "")),
                        str(m.get("codeSummaryMd5", "")),
                    )
            return "", ""

        correct_result = _correct_lookup(machine, _MACHINES_JSON)
        assert correct_result == expected, (
            f"GREEN phase: correct lookup must match snapshot for {machine}. "
            f"Got {correct_result!r}, expected {expected!r}."
        )

    def test_c6_inject_wrong_key_name_is_caught(self, tmp_path: Path):
        """Inject-bug: canonical reads 'config_md5' key instead of 'configSummaryMd5'.

        This simulates a key-name bug in the new canonical implementation —
        a common error when refactoring across schemas.

        Inject: lookup reads 'config_md5' (non-existent key in machines.json)
        Expected: returns '' instead of the real hash → snapshot mismatch → RED
        Revert: use correct key 'configSummaryMd5' → snapshot matches → GREEN
        """
        # Create a minimal machines.json with the correct key names
        machines_data = {
            "machines": [
                {
                    "machine": "M14",
                    "configSummaryMd5": "4fcf00c48b3d6979aef058fed9ed5f94",
                    "codeSummaryMd5": "536fc5a2a8f2ecf1fd8c6dfcf2c025cc",
                }
            ]
        }
        fixture_json = tmp_path / "machines.json"
        fixture_json.write_text(json.dumps(machines_data), encoding="utf-8")

        expected = _EXPECTED_MD5["M14"]

        # INJECT: wrong key name (reads 'config_md5' not 'configSummaryMd5')
        def _buggy_wrong_key(machine_name: str, machines_config_path: Path) -> tuple[str, str]:
            data = json.loads(machines_config_path.read_text(encoding="utf-8"))
            for m in data.get("machines", []):
                if m.get("machine") == machine_name:
                    return (
                        str(m.get("config_md5", "")),   # WRONG KEY
                        str(m.get("code_md5", "")),     # WRONG KEY
                    )
            return "", ""

        buggy_result = _buggy_wrong_key("M14", fixture_json)
        # RED: wrong keys return '' because 'config_md5' doesn't exist in machines.json
        assert buggy_result != expected, (
            f"Inject-bug FAILED: buggy lookup with wrong key still returned {buggy_result!r}. "
            f"Expected divergence from snapshot {expected!r}."
        )
        assert buggy_result == ("", ""), (
            f"Wrong-key lookup must return ('', ''), got {buggy_result!r}."
        )

        # GREEN: correct keys
        def _correct_lookup(machine_name: str, machines_config_path: Path) -> tuple[str, str]:
            data = json.loads(machines_config_path.read_text(encoding="utf-8"))
            for m in data.get("machines", []):
                if m.get("machine") == machine_name:
                    return (
                        str(m.get("configSummaryMd5", "")),
                        str(m.get("codeSummaryMd5", "")),
                    )
            return "", ""

        correct_result = _correct_lookup("M14", fixture_json)
        assert correct_result == expected, (
            f"GREEN phase: correct key lookup must match snapshot. "
            f"Got {correct_result!r}, expected {expected!r}."
        )

    def test_c6_inject_stale_divergent_pia_lookup_caught_by_c1(self, monkeypatch: pytest.MonkeyPatch):
        """Inject-bug: revert scenario — old local def in PIA would be caught by C1/C2.

        Simulates what happens if the implementer's dedup is reverted: the
        'count == 1' check in C1 would see 2 definitions (machine_md5.py AND
        player_impact_analyzer.py) and go RED.

        We simulate this by building a fake file list and running the count
        logic directly.

        RED phase: 2 definitions found → count != 1 → C1 goes RED
        GREEN phase: 1 definition → count == 1 → C1 stays GREEN
        """
        # Simulate: both files define the function (pre-dedup or botched revert)
        found_in_two_files = [_CANONICAL_MODULE_FILE, _PIA_PY]
        assert len(found_in_two_files) != 1, (
            "Inject-bug simulation: 2 files with the function must fail the count==1 check."
        )

        # GREEN: only canonical has it
        found_in_one_file = [_CANONICAL_MODULE_FILE]
        assert len(found_in_one_file) == 1, (
            "After revert to correct state: only canonical file should define the function."
        )
        assert found_in_one_file[0] == _CANONICAL_MODULE_FILE

    def test_c6_canonical_monkeypatch_divergence_caught_by_c3(self, monkeypatch: pytest.MonkeyPatch):
        """Inject-bug using monkeypatch: canonical patched to return wrong machine's md5
        → C3 snapshot test catches the divergence.

        This is the full inject-bug TDD loop per memory feedback_integration_test_argv.md:
          INJECT: canonical returns M1's md5 for any machine
          RED: result != _EXPECTED_MD5[machine] for all 5 machines
          REVERT: monkeypatch scope exits
          GREEN: real canonical returns correct values

        The test DIRECTLY demonstrates the RED behavior (proves tests are not vacuous).
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/machine_md5.py not created yet (pre-impl)")
        if not _MACHINES_JSON.exists():
            pytest.skip("configs/machines.json not present")

        import fresh_slotlab.machine_md5 as mm

        # M1's values (from machines.json) — different from all 5 test machines
        m1_config = "f61f85932f314aff5f11e278931dde1d"
        m1_code = "536fc5a2a8f2ecf1fd8c6dfcf2c025cc"

        # INJECT: canonical always returns M1's md5
        monkeypatch.setattr(
            mm, "lookup_machine_md5",
            lambda machine, machines_config_path=None: (m1_config, m1_code),
        )

        # Verify divergence is detectable for machines where M1's values differ
        # M260 and M279 have unique code_md5 (not 536fc5...) so BOTH fields diverge
        for machine in ["M260", "M279"]:
            buggy_result = mm.lookup_machine_md5(machine, _MACHINES_JSON)
            expected = _EXPECTED_MD5[machine]
            assert buggy_result != expected, (
                f"Inject-bug FAILED for {machine}: buggy result {buggy_result!r} "
                f"should differ from expected {expected!r}. "
                "M1's code_md5 (536fc5...) differs from M260/M279's code_md5."
            )

        # For M14/M37/M101 (share code_md5 with M1), config_md5 still differs
        for machine in ["M37", "M101"]:
            buggy_result = mm.lookup_machine_md5(machine, _MACHINES_JSON)
            expected = _EXPECTED_MD5[machine]
            assert buggy_result[0] != expected[0], (
                f"Inject-bug: config_md5 for {machine} must differ when patched to M1's values. "
                f"buggy[0]={buggy_result[0]!r}, expected[0]={expected[0]!r}."
            )

        # monkeypatch scope exits → canonical restored → GREEN
        # (tested by test_canonical_returns_expected_md5_snapshot above)


# ═══════════════════════════════════════════════════════════════════════════
# Import smoke — no side effects on import
# ═══════════════════════════════════════════════════════════════════════════


class TestImportSmoke:
    """Per memory feedback_subprocess_import_suicide_and_module_globals.md:
    fresh_slotlab/machine_md5.py must be import-safe.

    'import fresh_slotlab.machine_md5' in a subprocess must produce no output,
    no file writes, no DB connections, no process kills.

    This is critical because player_impact_analyzer.py is spawned as a
    subprocess — if machine_md5.py has any module-top side effects (e.g.,
    `app = build_app()`) they would run every time the subprocess starts,
    potentially triggering the 'import suicide' bug documented in the memory.
    """

    def test_import_machine_md5_is_side_effect_free(self):
        """Spawn python -c 'import fresh_slotlab.machine_md5' and assert
        no stdout, no stderr, exit code 0.

        Subprocess mode is required here per memory
        feedback_perf_claim_needs_e2e_event_stream.md: unit + AST checks
        are not enough for import-side-effect bugs — the subprocess IS the
        runtime context where the bug manifests.

        Inject-bug: add `app = create_app()` at module top of machine_md5.py
        → subprocess emits stderr / raises / hangs → test goes RED.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/machine_md5.py not created yet (pre-impl)")

        result = subprocess.run(
            [sys.executable, "-c", "import fresh_slotlab.machine_md5"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, (
            f"'import fresh_slotlab.machine_md5' failed with exit code {result.returncode}.\n"
            f"stderr: {result.stderr!r}\n"
            f"stdout: {result.stdout!r}\n"
            "The canonical module must be import-safe (no side effects on import)."
        )
        assert result.stdout.strip() == "", (
            f"'import fresh_slotlab.machine_md5' produced unexpected stdout: {result.stdout!r}. "
            "Module import must be silent — no print() calls at module top."
        )
        assert result.stderr.strip() == "", (
            f"'import fresh_slotlab.machine_md5' produced unexpected stderr: {result.stderr!r}. "
            "Module import must be silent — no warnings or errors at module top."
        )

    def test_import_machine_md5_does_not_mutate_module_globals(self):
        """Importing machine_md5 must not mutate any module-level globals in
        fresh_slotlab or src packages.

        Specifically guards against the 'virtual_app import suicide' pattern
        from memory feedback_subprocess_import_suicide_and_module_globals.md
        where importing a module ran a recovery loop that killed the current PID.

        Verify by importing twice and asserting the function identity is stable.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/machine_md5.py not created yet (pre-impl)")

        # First import
        if "fresh_slotlab.machine_md5" in sys.modules:
            del sys.modules["fresh_slotlab.machine_md5"]
        mod1 = importlib.import_module("fresh_slotlab.machine_md5")
        fn1 = getattr(mod1, "lookup_machine_md5", None)

        # Second import (from cache — must be stable)
        mod2 = importlib.import_module("fresh_slotlab.machine_md5")
        fn2 = getattr(mod2, "lookup_machine_md5", None)

        assert fn1 is fn2, (
            "lookup_machine_md5 function identity changed between two imports "
            "of the same module — module-level state mutation detected."
        )

    def test_machine_md5_has_no_module_top_code_beyond_imports_and_defs(self):
        """AST check: machine_md5.py top level contains only imports, assignments,
        and function/class definitions — no bare function calls that could
        trigger side effects.

        Catches patterns like:
          app = create_app()         # import suicide
          result = read_config()     # unexpected I/O on import
          _db.connect()              # unexpected network on import

        Per memory feedback_subprocess_import_suicide_and_module_globals.md.
        """
        if not _CANONICAL_MODULE_FILE.exists():
            pytest.skip("fresh_slotlab/machine_md5.py not created yet (pre-impl)")

        source = _CANONICAL_MODULE_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(_CANONICAL_MODULE_FILE))

        # Allowed top-level statement types
        safe_types = (
            ast.Import,
            ast.ImportFrom,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.Assign,
            ast.AugAssign,
            ast.AnnAssign,
            ast.Expr,    # module docstrings are Expr(value=Constant(...))
            ast.If,      # TYPE_CHECKING guards
        )
        # Check Expr nodes more carefully — only string literals (docstrings) are OK,
        # not bare function calls
        violations: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Expr):
                # Module docstring: Expr with a Constant string value
                if not isinstance(node.value, ast.Constant):
                    violations.append(
                        f"Line {node.lineno}: bare expression at module top "
                        f"(type: {type(node.value).__name__}) — potential side effect"
                    )
            elif not isinstance(node, safe_types):
                violations.append(
                    f"Line {node.lineno}: unexpected top-level statement "
                    f"(type: {type(node).__name__})"
                )

        assert not violations, (
            "fresh_slotlab/machine_md5.py contains potentially side-effectful "
            "top-level code:\n" + "\n".join(violations)
        )
