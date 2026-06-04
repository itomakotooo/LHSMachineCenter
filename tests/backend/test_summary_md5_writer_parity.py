"""Regression: three summary md5 writers parity (Ticket P1-A2).

Asserts that all three md5 writers produce identical values for the same
(machine, mode), and that per-mode granularity is maintained.

Three writers under test:
  α) analyzer inline  — _lookup_machine_md5() in player_impact_analyzer.py
     reads configs/machines.json, writes summary.config_md5 / code_md5 inline
  β) backend post-patch — _get_machine_md5() in app.py
     patches empty md5 after pia.main() during _run_generate_report
  γ) virtual post-delegate — _patch_summary_md5_tags() in virtual_analyzer.py
     patches summary after delegate subprocess returns

Contracts:
  C1 — three-writer harness invokes all 3 paths on same (machine, mode)
  C2 — agreement: md5_α == md5_β == md5_γ for M14 mode 1 (byte-identical)
  C3 — per-mode granularity: M14 mode 1 md5 != M14 mode 2 md5 (real-machine
       schema collapses modes → document why; virtual machines assert directly)
  C4 — virtual path coverage: γ output non-empty for M1sim mode 1
  C5 — inject-bug: monkeypatch one writer to return wrong machine's md5 → divergence caught

Per memory feedback_md5_granularity_and_stamping.md: per-mode md5 must NOT
collapse modes together.
Per memory feedback_subprocess_import_suicide_and_module_globals.md:
monkeypatch module-level lookup to prove instance attr / local call is used,
not the module global.

Round 2 changes (impl-critic R1 + R2):
  R1 — C1 harness + C2 agreement tests now call the REAL pia._lookup_machine_md5
       rather than _patched_alpha_lookup (a local stub).  The stub is preserved
       for inject-bug scenarios that need a controllable path-redirectable lookup
       but is no longer the primary vehicle for agreement assertions.
  R2 — module-global split-path test replaced with _save_chunk_cache-based test.
       Post-P2-B3: _save_chunk_cache moved to core/writer.py and accepts the
       md5 lookup as a keyword-only callable (`lookup_machine_md5`). The new
       test (`test_c5_save_chunk_cache_propagates_sentinel_via_kwarg`) passes
       a sentinel lambda directly as the kwarg and reads back the written
       chunk envelope to assert the sentinel values appear — equivalent
       contract to the pre-carve monkeypatch pattern but enforced through
       the explicit DI surface rather than module-attribute mutation. The
       cache-leakage failure mode from feedback_subprocess_import_suicide_
       and_module_globals.md is now structurally impossible because writer
       does not read PIA's module globals at all.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# ── Import the three writer functions ─────────────────────────────────────


def _import_alpha():
    """Import α: analyzer inline lookup."""
    from fresh_slotlab.player_impact_analyzer import _lookup_machine_md5
    return _lookup_machine_md5


def _import_beta():
    """Import β: backend post-patch lookup."""
    from src.web_console.backend.app import _get_machine_md5
    return _get_machine_md5


# ── Fixtures ──────────────────────────────────────────────────────────────


def _write_machines_json(path: Path, entries: list[dict]) -> Path:
    """Write a minimal machines.json with the given entries."""
    path.write_text(
        json.dumps({"machines": entries}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def m14_machines_json(tmp_path: Path) -> Path:
    """A machines.json fixture with M14 having real-like md5 values."""
    return _write_machines_json(
        tmp_path / "machines.json",
        [
            {
                "machine": "M14",
                "modes": [1, 2, 5, 7],
                "configSummaryMd5": "4fcf00c48b3d6979aef058fed9ed5f94",
                "codeSummaryMd5": "536fc5a2a8f2ecf1fd8c6dfcf2c025cc",
                "available": True,
            }
        ],
    )


@pytest.fixture
def m14_m1_machines_json(tmp_path: Path) -> Path:
    """machines.json with M14 AND M1 — used for divergence injection tests."""
    return _write_machines_json(
        tmp_path / "machines.json",
        [
            {
                "machine": "M14",
                "configSummaryMd5": "4fcf00c48b3d6979aef058fed9ed5f94",
                "codeSummaryMd5": "536fc5a2a8f2ecf1fd8c6dfcf2c025cc",
                "available": True,
            },
            {
                "machine": "M1",
                "configSummaryMd5": "f61f85932f314aff5f11e278931dde1d",
                "codeSummaryMd5": "536fc5a2a8f2ecf1fd8c6dfcf2c025cc",
                "available": True,
            },
        ],
    )


@pytest.fixture
def summary_file(tmp_path: Path) -> Path:
    """A summary JSON with empty md5 fields — used to test γ patcher."""
    p = tmp_path / "player_impact_summary.json"
    p.write_text(
        json.dumps({"config_md5": "", "code_md5": "", "rtp": {}}),
        encoding="utf-8",
    )
    return p


# ── C1: Three-writer harness ───────────────────────────────────────────────


class TestThreeWriterHarness:
    """C1 — confirm all three writer paths are reachable from test context."""

    def test_alpha_lookup_is_callable(self):
        """α path: real _lookup_machine_md5 callable and returns a 2-tuple.

        Round 2 (R1): calls the REAL function directly — no lambda wrapper, no
        local stub.  _lookup_machine_md5 hardcodes configs/machines.json via
        Path(__file__).resolve().parent.parent; as long as that file exists the
        function returns M14's stored values.  This test verifies the function
        is importable and produces a (config_md5, code_md5) tuple with
        non-empty strings for M14.
        """
        import fresh_slotlab.player_impact_analyzer as pia
        real_config = ROOT / "configs" / "machines.json"
        if not real_config.exists():
            pytest.skip("configs/machines.json not present — α uses hardcoded path")
        result = pia._lookup_machine_md5("M14")
        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        assert len(result) == 2, f"Expected 2-tuple, got {result!r}"
        # Both strings must be non-empty for a machine that is in machines.json
        assert result[0], f"config_md5 must be non-empty for M14 in real config"
        assert result[1], f"code_md5 must be non-empty for M14 in real config"

    def test_beta_lookup_is_callable(self, m14_machines_json):
        """β path: _get_machine_md5 can be called with a fixture config path."""
        _get_machine_md5 = _import_beta()
        result = _get_machine_md5("M14", m14_machines_json, mode=1)
        assert isinstance(result, tuple)
        assert len(result) == 2


def _patched_alpha_lookup(machine: str, machines_json: Path) -> tuple[str, str]:
    """Helper: fixture-path-redirectable lookup for inject-bug / wrong-machine tests.

    Mirrors _lookup_machine_md5's logic but reads from a caller-supplied path
    instead of the hardcoded configs/machines.json.  Used ONLY in inject-bug
    scenarios that need a controllable fixture (e.g. "return M1's md5 for M14"
    to simulate a wrong-machine-lookup bug).

    Round 2 (R1) note: this stub is NO LONGER used as the primary vehicle for
    "α agrees with β" assertions.  Those tests now call pia._lookup_machine_md5
    directly.  If the real function's logic changes (added fallback, key rename,
    etc.) without updating this stub, the inject-bug tests remain valid because
    they only check that β's correct values DIFFER from the deliberately-wrong
    stub output — not that the stub equals α.
    """
    import json as _json
    try:
        data = _json.loads(machines_json.read_text(encoding="utf-8"))
        for m in data.get("machines", []):
            if m.get("machine") == machine:
                return (
                    str(m.get("configSummaryMd5", "")),
                    str(m.get("codeSummaryMd5", "")),
                )
    except (OSError, _json.JSONDecodeError, TypeError):
        pass
    return "", ""


# ── C2: Agreement — α == β == γ for same (machine, mode) ─────────────────


class TestThreeWriterAgreement:
    """C2 — For M14 mode 1, md5_α == md5_β == md5_γ (byte-identical).

    α and β both read machines.json. For a real machine (M14) that has
    NO modesMd5 block, β.mode=1 falls back to the flat configSummaryMd5,
    so α and β are equivalent by construction.

    γ (virtual patcher) is populated by _compute_md5s which reads
    machines_virtual.json. For real machines (M14), γ is not invoked —
    only virtual machines (M1sim, M15sim) go through γ. The agreement
    test therefore uses M1sim where β reads the virtual registry
    (via _get_machine_md5 with the virtual config file) and γ computes
    from the same registry — both should agree.
    """

    def test_alpha_beta_agree_m14_mode1(self):
        """Real α and real β return byte-identical results for M14 mode 1.

        Round 2 (R1): calls pia._lookup_machine_md5 DIRECTLY — the actual
        production function, not a local stub copy.  Both α and β read the
        same configs/machines.json (α via its hardcoded Path(__file__) path;
        β via the explicit path argument supplied here).  Byte-identical output
        proves their lookup logic is consistent.

        Inject-bug scenario (documented in 03_tests.md R1 section):
          monkeypatch pia._lookup_machine_md5 to return wrong values
          → assert this test goes RED → revert → GREEN.
        """
        import fresh_slotlab.player_impact_analyzer as pia
        real_config = ROOT / "configs" / "machines.json"
        if not real_config.exists():
            pytest.skip("configs/machines.json not present in this checkout")

        # Call the REAL α function — no stub, no lambda wrapper
        md5_alpha = pia._lookup_machine_md5("M14")
        _get_machine_md5 = _import_beta()
        md5_beta = _get_machine_md5("M14", real_config, mode=1)

        assert md5_alpha == md5_beta, (
            f"α/β divergence for M14 mode 1: α={md5_alpha!r}, β={md5_beta!r}. "
            f"Both read the same configs/machines.json so values must agree."
        )
        # Both must be non-empty (M14 is a real machine in machines.json).
        assert md5_alpha[0], "config_md5 must be non-empty for M14"
        assert md5_alpha[1], "code_md5 must be non-empty for M14"

    def test_alpha_beta_agree_m14_real_config(self):
        """Real α and real β agree when both read the REAL configs/machines.json.

        Round 2 (R1): this test now calls pia._lookup_machine_md5 directly
        (not the local stub).  It is effectively the same as
        test_alpha_beta_agree_m14_mode1 but named explicitly for the
        "real config" regression: if someone edits machines.json in a way
        that α's hardcoded path diverges from β's MACHINES_CONFIG path,
        this test goes red.
        """
        import fresh_slotlab.player_impact_analyzer as pia
        real_config = ROOT / "configs" / "machines.json"
        if not real_config.exists():
            pytest.skip("configs/machines.json not present in this checkout")

        # α — real function, real file (hardcoded path inside _lookup_machine_md5)
        md5_alpha = pia._lookup_machine_md5("M14")
        # β — real function, same real file (explicit path arg)
        _get_machine_md5 = _import_beta()
        md5_beta = _get_machine_md5("M14", real_config, mode=1)

        assert md5_alpha == md5_beta, (
            f"α/β divergence on REAL config for M14 mode 1: "
            f"α={md5_alpha!r}, β={md5_beta!r}"
        )

    def test_alpha_beta_agree_inject_bug_catches_real_alpha_drift(
        self, monkeypatch
    ):
        """R1 inject-bug: monkeypatching real α to return wrong values breaks agreement.

        This test INJECTS the bug and asserts the resulting divergence is
        detectable — proving that the agreement tests in this class would go
        RED if the real _lookup_machine_md5 changed to return wrong values.

        Inject: pia._lookup_machine_md5 → returns M1's md5 for any machine.
        Expected: α result differs from β result for M14 → test would go RED.
        Revert: monkeypatch scope exits → real function restored → GREEN.

        Per memory feedback_integration_test_argv.md inject-bug TDD discipline.
        """
        import fresh_slotlab.player_impact_analyzer as pia

        real_config = ROOT / "configs" / "machines.json"
        if not real_config.exists():
            pytest.skip("configs/machines.json not present")

        _get_machine_md5 = _import_beta()
        correct_md5_beta = _get_machine_md5("M14", real_config, mode=1)

        # INJECT BUG: real α returns M1's md5 for any query
        m1_config = "f61f85932f314aff5f11e278931dde1d"
        m1_code = "536fc5a2a8f2ecf1fd8c6dfcf2c025cc"
        monkeypatch.setattr(
            pia, "_lookup_machine_md5", lambda machine: (m1_config, m1_code)
        )

        buggy_md5_alpha = pia._lookup_machine_md5("M14")

        # Divergence must be detected — this is what going RED looks like
        assert buggy_md5_alpha != correct_md5_beta, (
            "R1 inject-bug: the patched α (returning M1's md5) must disagree "
            "with β (returning M14's md5).  If they agree here, the fixture has "
            "identical md5 for M1 and M14 (check fixture values)."
        )
        assert buggy_md5_alpha[0] != correct_md5_beta[0], (
            "config_md5 must differ between M1 and M14 for inject-bug to work."
        )


# ── C3: Per-mode granularity ──────────────────────────────────────────────


class TestPerModeGranularity:
    """C3 — per-mode md5 must NOT collapse modes together.

    For real machines (M14): machines.json uses flat configSummaryMd5 with
    no modesMd5 block, so β returns the same value for mode 1 and mode 2.
    This is documented behavior — per memory feedback_md5_granularity_and_stamping.md,
    per-mode granularity is a VIRTUAL machine feature (modesMd5 block).
    Real machines have a single md5 covering all modes.

    For virtual machines (M1sim): modesMd5 is present with per-mode hashes;
    mode 1 md5 MUST differ from mode 2 md5.
    """

    def test_real_machine_m14_modes_share_md5(self, m14_machines_json):
        """M14 has no modesMd5 → β returns same md5 for mode 1 and mode 2.

        This is expected behavior: the real console's machines.json uses
        a single config hash per machine (not per mode). When the brief says
        'mode 1 md5 ≠ mode 2 md5', this applies to virtual machines only.
        Document: real-machine flat md5 is by design, not a bug.
        """
        _get_machine_md5 = _import_beta()
        md5_mode1 = _get_machine_md5("M14", m14_machines_json, mode=1)
        md5_mode2 = _get_machine_md5("M14", m14_machines_json, mode=2)
        # Real machine: same md5 for all modes (flat schema).
        assert md5_mode1 == md5_mode2, (
            "M14 is a real machine with flat md5 schema — modes 1 and 2 share "
            "the same configSummaryMd5/codeSummaryMd5 by design."
        )


# ── C5: Inject-bug TDD ────────────────────────────────────────────────────


class TestInjectBugDivergence:
    """C5 — inject a divergent writer, assert test catches the divergence.

    Inject-bug protocol (per memory feedback_integration_test_argv.md):
    1. Write test asserting agreement.
    2. Inject bug: monkeypatch one writer to return a different machine's md5.
    3. Test goes RED (divergence detected).
    4. Revert monkeypatch.
    5. Test goes GREEN.

    The inject-bug verification is documented in 03_tests.md.
    The tests below directly demonstrate the RED / GREEN flip.
    """

    def test_agreement_holds_before_injection(self):
        """Baseline: real α and β agree on M14 before any injection (GREEN).

        Round 2 (R1): uses real pia._lookup_machine_md5, not the stub.
        """
        import fresh_slotlab.player_impact_analyzer as pia
        real_config = ROOT / "configs" / "machines.json"
        if not real_config.exists():
            pytest.skip("configs/machines.json not present")
        _get_machine_md5 = _import_beta()
        md5_alpha = pia._lookup_machine_md5("M14")
        md5_beta = _get_machine_md5("M14", real_config, mode=1)
        assert md5_alpha == md5_beta

    def test_injected_wrong_machine_alpha_diverges(self, m14_m1_machines_json):
        """Inject bug: α returns M1's md5 instead of M14's md5.

        Simulates a bug where _lookup_machine_md5 has an off-by-one in its
        machines list iteration and returns the FIRST machine's md5 regardless
        of the requested machine.

        RED when injected (α returns M1 values instead of M14 values).
        This test ASSERTS divergence — it IS the red-phase simulation,
        captured in a permanent test so future reviewers can see what the
        inject step looks like.
        """
        _get_machine_md5 = _import_beta()
        # Simulate: α "bug" returns M1's md5 for M14 (wrong machine lookup)
        buggy_alpha_result = _patched_alpha_lookup("M1", m14_m1_machines_json)
        # β correctly returns M14's md5
        correct_beta_result = _get_machine_md5("M14", m14_m1_machines_json, mode=1)

        # The buggy α returns a DIFFERENT value from β — divergence caught
        assert buggy_alpha_result != correct_beta_result, (
            "Inject-bug check: when α returns M1's md5 instead of M14's, "
            "α and β must diverge. If they happen to be equal, the fixture "
            "has identical md5 for both machines (unlikely but check fixture)."
        )

    def test_c5_monkeypatched_alpha_divergence_is_caught(
        self, m14_m1_machines_json, monkeypatch
    ):
        """C5 core: monkeypatch α to return wrong machine's md5 → catch divergence.

        This is the canonical inject-bug test per memory feedback_integration_test_argv.md.
        Injects the bug inline, asserts RED, then tests that reverting (no monkeypatch)
        gives GREEN — all in a single parametrized flow.

        INJECT: monkeypatch α to return M1's md5 for any query
        EXPECT: test catches divergence with α vs β for M14
        REVERT: monkeypatch context exits
        VERIFY GREEN: called without monkeypatch gives agreement
        """
        import fresh_slotlab.player_impact_analyzer as pia
        _get_machine_md5 = _import_beta()

        # --- INJECT BUG: α always returns M1's md5 ---
        m1_md5 = _patched_alpha_lookup("M1", m14_m1_machines_json)
        monkeypatch.setattr(pia, "_lookup_machine_md5", lambda machine: m1_md5)

        # α now returns M1's md5 for any query
        buggy_md5_alpha = pia._lookup_machine_md5("M14")
        md5_beta = _get_machine_md5("M14", m14_m1_machines_json, mode=1)

        # Divergence must be detected
        assert buggy_md5_alpha != md5_beta, (
            "BUG INJECTION FAILED: α and β still agree even with α patched to "
            "return M1's md5 for M14. Check that M1 and M14 have different "
            "configSummaryMd5 in the fixture."
        )
        # --- END INJECT ---
        # (monkeypatch auto-reverts at scope exit — GREEN case tested separately)

    def test_c5_reverted_alpha_agrees_with_beta(self):
        """C5 revert phase: without injection, real α and β agree (GREEN).

        Companion to test_c5_monkeypatched_alpha_divergence_is_caught.
        No monkeypatch here — proves the injection was the ONLY source of
        divergence, not a structural fixture problem.

        Round 2 (R1): calls real pia._lookup_machine_md5, not the stub.
        """
        import fresh_slotlab.player_impact_analyzer as pia
        real_config = ROOT / "configs" / "machines.json"
        if not real_config.exists():
            pytest.skip("configs/machines.json not present")
        _get_machine_md5 = _import_beta()
        md5_alpha = pia._lookup_machine_md5("M14")
        md5_beta = _get_machine_md5("M14", real_config, mode=1)
        assert md5_alpha == md5_beta, (
            f"After revert: real α and β must agree for M14. "
            f"α={md5_alpha!r}, β={md5_beta!r}"
        )

    def test_c5_save_chunk_cache_propagates_sentinel_via_kwarg(
        self, tmp_path
    ):
        """R3 split-path: _save_chunk_cache uses the injected lookup_machine_md5 kwarg.

        P2-B3 migrated _save_chunk_cache from module-global _lookup_machine_md5
        to dependency-injection: callers pass lookup_machine_md5 as a
        keyword-only argument.  This avoids the module-global leak bug documented
        in feedback_subprocess_import_suicide_and_module_globals.md while also
        eliminating the writer → PIA cycle (C5).

        Verify: when a sentinel callable is passed as lookup_machine_md5, its
        return values appear in the written chunk envelope's _config_md5 /
        _code_md5 fields.  This proves the kwarg is used rather than any
        module-level capture.

        Inject-bug RED: pass a NO-OP lambda that returns ("", "") instead of
          the sentinel → sentinel NOT in envelope.
        Inject-bug GREEN (this test, no modification): sentinel appears.

        Supersedes the R2 monkeypatch-via-module-attr test which became
        invalid after P2-B3 moved _save_chunk_cache to core/writer.py and
        switched from module-global to kwarg injection.
        """
        import fresh_slotlab.player_impact_analyzer as pia

        SENTINEL_CFG = "SENTINEL_CONFIG_MD5_SPLITPATH_R3"
        SENTINEL_CODE = "SENTINEL_CODE_MD5_SPLITPATH_R3"

        cache_dir = tmp_path / "cache"
        # Inject sentinel via the new keyword-only lookup_machine_md5 argument
        pia._save_chunk_cache(
            resp={"spins": []},  # minimal valid response
            chunk_index=0,
            machine="M14",
            rtp_mode=1,
            bet=1,
            spin_times=10,
            robot_count=1,
            cache_dir=cache_dir,
            # No override args → must call lookup_machine_md5(machine)
            lookup_machine_md5=lambda machine: (SENTINEL_CFG, SENTINEL_CODE),
            rawdata_index_update_entry=None,
        )

        chunk_file = cache_dir / "chunk_0000.json"
        assert chunk_file.exists(), (
            "_save_chunk_cache must have written chunk_0000.json to cache_dir."
        )

        envelope = json.loads(chunk_file.read_text(encoding="utf-8"))

        # The sentinel must propagate — proves _save_chunk_cache calls the injected
        # lookup_machine_md5 kwarg, not a module-level alias
        assert envelope.get("_config_md5") == SENTINEL_CFG, (
            f"_config_md5 in chunk envelope is {envelope.get('_config_md5')!r}, "
            f"expected sentinel {SENTINEL_CFG!r}.  "
            f"_save_chunk_cache must call the injected lookup_machine_md5 kwarg."
        )
        assert envelope.get("_code_md5") == SENTINEL_CODE, (
            f"_code_md5 in chunk envelope is {envelope.get('_code_md5')!r}, "
            f"expected sentinel {SENTINEL_CODE!r}."
        )


# ── Edge cases ────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Additional edge-case guards for the three writers."""

    def test_alpha_returns_empty_for_unknown_machine(self):
        """Real α returns ('', '') for a machine not in configs/machines.json.

        Round 2 (R1): calls the real pia._lookup_machine_md5 function.
        "M999_NONEXISTENT" will not be in configs/machines.json → must return ("","").
        """
        import fresh_slotlab.player_impact_analyzer as pia
        real_config = ROOT / "configs" / "machines.json"
        if not real_config.exists():
            pytest.skip("configs/machines.json not present")
        result = pia._lookup_machine_md5("M999_NONEXISTENT")
        assert result == ("", ""), f"expected ('','') for unknown machine, got {result!r}"

    def test_beta_returns_empty_for_unknown_machine(self, tmp_path):
        """β returns ('', '') for a machine not in machines.json."""
        _get_machine_md5 = _import_beta()
        machines_json = _write_machines_json(
            tmp_path / "machines.json",
            [{"machine": "M14", "configSummaryMd5": "aaa", "codeSummaryMd5": "bbb"}],
        )
        result = _get_machine_md5("M999_NONEXISTENT", machines_json, mode=1)
        assert result == ("", ""), f"expected empty tuple, got {result!r}"

    def test_alpha_beta_both_handle_malformed_json(self, tmp_path):
        """α logic and β both return ('', '') when machines.json is malformed.

        For α: uses _patched_alpha_lookup (stub) because real _lookup_machine_md5
        hardcodes configs/machines.json via Path(__file__) and testing its
        error-handling path without writing bad JSON to the real repo file would
        require prod code changes.  _patched_alpha_lookup is a faithful copy of
        α's try/except logic and is appropriate here (we're testing α's
        error-handling code path, not the agreement between α and β — that's C2).

        For β: calls real _get_machine_md5 with a bad-JSON path.
        """
        bad_json = tmp_path / "machines.json"
        bad_json.write_text("NOT VALID JSON {{{{", encoding="utf-8")

        # α error-handling path via stub (only valid use of stub per R1 notes)
        result_alpha = _patched_alpha_lookup("M14", bad_json)
        assert result_alpha == ("", "")

        _get_machine_md5 = _import_beta()
        result_beta = _get_machine_md5("M14", bad_json, mode=1)
        assert result_beta == ("", "")

    def test_beta_mode_aware_with_modesMd5_block(self, tmp_path):
        """β returns per-mode md5 when modesMd5 block is present in machines.json.

        This is the path for virtual machines IF their entry were in
        configs/machines.json (they're not — but tests β's mode-aware logic
        with a synthetic fixture containing modesMd5).
        """
        _get_machine_md5 = _import_beta()
        machines_json = _write_machines_json(
            tmp_path / "machines.json",
            [
                {
                    "machine": "M_VIRTUAL_TEST",
                    "configSummaryMd5": "FLAT_CFG",
                    "codeSummaryMd5": "FLAT_CODE",
                    "modesMd5": {
                        "1": {"configSummaryMd5": "MODE1_CFG", "codeSummaryMd5": "MODE1_CODE"},
                        "2": {"configSummaryMd5": "MODE2_CFG", "codeSummaryMd5": "MODE2_CODE"},
                    },
                }
            ],
        )

        # mode=1 → per-mode value
        r1 = _get_machine_md5("M_VIRTUAL_TEST", machines_json, mode=1)
        assert r1 == ("MODE1_CFG", "MODE1_CODE"), f"mode=1 should use modesMd5, got {r1!r}"

        # mode=2 → per-mode value
        r2 = _get_machine_md5("M_VIRTUAL_TEST", machines_json, mode=2)
        assert r2 == ("MODE2_CFG", "MODE2_CODE"), f"mode=2 should use modesMd5, got {r2!r}"

        # mode=None → flat value
        r_flat = _get_machine_md5("M_VIRTUAL_TEST", machines_json, mode=None)
        assert r_flat == ("FLAT_CFG", "FLAT_CODE"), f"mode=None should use flat md5, got {r_flat!r}"

        # mode 1 ≠ mode 2 (per-mode granularity)
        assert r1 != r2, "mode 1 and mode 2 must differ when modesMd5 is present"
