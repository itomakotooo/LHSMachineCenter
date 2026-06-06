"""Phase 2a e2e gate: report_engine generates correct schema and RTP from M15 cached chunks.

Gates per ANALYZER_ARCHITECTURE.md §6 phase 2:
  - Invariant 1: schema keys (top-level + player_impact.*) match kept-good schema
  - Invariant 3: pytest 0 failed / 0 errors
  - Invariant 4: M15 e2e: rtp_integrity_check.passed == True, RTP in [80,110]
  - Inject-bug (round_win rules): skip rules -> RTP jumps to ~128 -> RED -> revert -> GREEN

Key correctness gate:
  Without the round_win SettlementWinAmountRule, ST=14 phantom WinCredits are
  double-counted and M15 RTP inflates to ~128%. The gate asserts RTP < 115 AND
  rtp_integrity_check.passed == True. A skip of rule loading makes both fail.

Machine-id option (b) chosen: "M15" added to topdollar_selector_settlement.applies_to
in configs/machine_round_win_rules.json so bare "M15" (new framework identity) matches.
The variant keys (M15$TopDollarSelector$*) are preserved for backward compatibility
with the old PIA fleet path.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# Repo root for locating rawdata and kept-good report.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M15" / "mode_1"

# Schema-key reference ONLY (not an RTP reference): rv_20260514 is a localcfg TUNING
# report (config_md5 localcfg_cca3bd1d, RTP 95.78) — NOT the canonical M15. The canonical
# M15 (server config 2d8996..., the current rawdata) is ~92% RTP per the same-config old
# reports (rv_20260604T*_rawdata_2d8996_44297a = 92.04%); this engine produces ~91.3%
# (within CI). The correctness gate is VALUE-AGNOSTIC: RTP < 128 (no ST14 double-count)
# + RTP in [80,110] + rtp_integrity passed — never a pinned RTP value.
_KEPT_GOOD_20260514 = (
    _REPO_ROOT
    / "reports"
    / "M15"
    / "mode_1"
    / "versions"
    / "rv_20260514T020824Z_3c48306e"
    / "player_impact_summary.json"
)

# Expected top-level keys (from kept-good report schema).
_EXPECTED_TOP_KEYS = frozenset({
    "report_id", "run_id", "machine", "mode",
    "config_md5", "code_md5",
    "analyzer_version", "effective_analyzer_version", "effective_analyzer_version_error",
    "output_all_robots_result",
    "sampling", "rtp",
    "player_impact", "upstream_analysis",
    "collect_mechanic", "topdollar_choice",
    "guideline_assessment", "guideline_comparison",
    "rtp_integrity_check",
    "storage",
})

# Expected player_impact sub-keys (from kept-good report schema).
_EXPECTED_PI_KEYS = frozenset({
    "volatility", "hit_and_payout", "streaks",
    "paylines_top20", "payout_groups_top20", "payout_groups_status", "payout_ids_top20",
    "spin_type_breakdown", "spin_type_coverage", "field_discovery",
    "payline_symbol_top20", "session_rtp_curves", "chain_ratio_sequences",
    "reel_position_top20",
    "symbols_top20", "symbols_by_column_top10", "symbols_by_column_top10_payline",
    "payline_rows_per_col",
    "bankruptcy_simulation", "bankruptcy_probe",
    "bonus_chain_dynamics", "machine_mechanics", "multiplier_profile",
    "payouts_by_spin_type", "reel_marginal_by_spin_type",
    "spin_type_outcomes", "spin_type_rtp_buckets",
    "upstream_feature_breakdown",
})

# RTP bounds for correctness (not exact — depends on which chunks are present).
# Without round_win rules: ~128%. With rules: 80-110% (M15 is ~95% RTP machine).
_RTP_LOWER_BOUND = 80.0
_RTP_UPPER_BOUND = 110.0
# The double-count artifact; any value >= this indicates broken rule application.
_RTP_DOUBLE_COUNT_THRESHOLD = 115.0


def _requires_chunks() -> bool:
    return _CHUNK_DIR.exists() and len(list(_CHUNK_DIR.glob("chunk_*.json"))) > 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m15_summary():
    """Run generate_report_from_chunks on real M15 cached chunks once per module."""
    if not _requires_chunks():
        pytest.skip("M15 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks

    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            "M15", 1,
            chunk_dir=_CHUNK_DIR,
            output_dir=Path(tmpdir),
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists(), (
            "write_summary_json must produce player_impact_summary.json"
        )
        yield summary


@pytest.fixture(scope="module")
def kept_good_summary():
    """Load the authoritative M15 reference report (rv_20260514, round_win rules active)."""
    if not _KEPT_GOOD_20260514.exists():
        pytest.skip("Kept-good M15 report (rv_20260514) not present")
    return json.loads(_KEPT_GOOD_20260514.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# CORRECTNESS GATE: RTP must NOT be double-counting ST14 phantom wins
# This is the primary Phase 2a gate. Without round_win rules, RTP = ~128%.
# With rules, RTP is in [80, 110] and rtp_integrity_check.passed = True.
# ---------------------------------------------------------------------------

class TestCorrectnessGate:
    def test_rtp_not_double_counting(self, m15_summary):
        """Primary gate: RTP must be below double-count threshold (~128%)."""
        rtp = m15_summary["rtp"]["point_pct"]
        assert rtp < _RTP_DOUBLE_COUNT_THRESHOLD, (
            f"RTP {rtp:.2f}% exceeds double-count threshold {_RTP_DOUBLE_COUNT_THRESHOLD}%: "
            f"round_win rules (SettlementWinAmountRule) are not being applied — "
            f"ST=14 phantom WinCredits are being double-counted."
        )

    def test_rtp_in_reasonable_range(self, m15_summary):
        """RTP must be in the expected range for an M15-class machine."""
        rtp = m15_summary["rtp"]["point_pct"]
        assert _RTP_LOWER_BOUND <= rtp <= _RTP_UPPER_BOUND, (
            f"RTP {rtp:.2f}% is outside expected range [{_RTP_LOWER_BOUND}, {_RTP_UPPER_BOUND}]. "
            f"This suggests a round_win rule was applied incorrectly or new double-counting exists."
        )

    def test_rtp_integrity_passes(self, m15_summary):
        """rtp_integrity_check.passed must be True: sum(payid RTP) == summary RTP."""
        ric = m15_summary.get("rtp_integrity_check", {})
        passed = ric.get("passed")
        assert passed is True, (
            f"rtp_integrity_check.passed must be True for M15 mode 1. "
            f"Got: passed={passed}, message={ric.get('summary_message', 'N/A')}. "
            f"Likely cause: round_win rules not applied — pay_id attribution does not sum to total RTP."
        )


# ---------------------------------------------------------------------------
# Schema invariant tests (gate invariant 1)
# ---------------------------------------------------------------------------

class TestSchemaInvariant:
    def test_top_level_keys_superset_of_expected(self, m15_summary):
        """Generated report must contain ALL expected top-level keys.

        Uses _EXPECTED_TOP_KEYS (current schema) not a versioned kept-good report —
        the rv_20260514 report predates effective_analyzer_version / rtp_integrity_check
        / topdollar_choice, so direct key-equality against it would be wrong.
        """
        gen_keys = set(m15_summary.keys())
        missing = _EXPECTED_TOP_KEYS - gen_keys
        assert not missing, f"Expected top-level keys absent: {sorted(missing)}"

    def test_top_level_no_spurious_keys(self, m15_summary):
        """Generated report must not have keys outside the known current schema."""
        gen_keys = set(m15_summary.keys())
        extra = gen_keys - _EXPECTED_TOP_KEYS
        assert not extra, (
            f"Unexpected extra top-level keys in generated report: {sorted(extra)}. "
            f"If this is a new intended key, add it to _EXPECTED_TOP_KEYS in this test."
        )

    def test_player_impact_keys_superset_of_expected(self, m15_summary):
        gen_pi = set(m15_summary["player_impact"].keys())
        missing = _EXPECTED_PI_KEYS - gen_pi
        assert not missing, f"Expected player_impact keys absent: {sorted(missing)}"

    def test_player_impact_no_spurious_keys(self, m15_summary):
        gen_pi = set(m15_summary["player_impact"].keys())
        extra = gen_pi - _EXPECTED_PI_KEYS
        assert not extra, (
            f"Unexpected extra player_impact keys: {sorted(extra)}. "
            f"If intentional, add to _EXPECTED_PI_KEYS."
        )

    def test_machine_and_mode(self, m15_summary):
        assert m15_summary["machine"] == "M15"
        assert m15_summary["mode"] == 1

    def test_sampling_metadata_present(self, m15_summary):
        s = m15_summary["sampling"]
        assert s["chunks"] > 0
        assert s["total_spins"] > 0
        assert s["stop_reason"] == "from_cache_complete"


# ---------------------------------------------------------------------------
# rtp_integrity structure (gate invariant 4)
# ---------------------------------------------------------------------------

class TestRTPIntegrity:
    def test_rtp_integrity_check_key_present(self, m15_summary):
        assert "rtp_integrity_check" in m15_summary

    def test_rtp_integrity_check_has_passed_field(self, m15_summary):
        assert "passed" in m15_summary["rtp_integrity_check"]

    def test_rtp_integrity_check_has_layer_fields(self, m15_summary):
        ric = m15_summary["rtp_integrity_check"]
        for field in ("layer1_invariant_ok", "layer2_no_fallback_buckets_ok",
                      "layer3_anchors_ok", "summary_message"):
            assert field in ric, f"rtp_integrity_check missing field: {field}"

    def test_rtp_integrity_summary_message_is_string(self, m15_summary):
        assert isinstance(m15_summary["rtp_integrity_check"].get("summary_message"), str)


# ---------------------------------------------------------------------------
# MachineNotRegistered test
# ---------------------------------------------------------------------------

class TestMachineNotRegistered:
    def test_unregistered_machine_raises(self):
        from fresh_slotlab.analyzer.report_engine import (
            generate_report_from_chunks,
            MachineNotRegistered,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(MachineNotRegistered, match="not registered"):
                generate_report_from_chunks(
                    "M999_nonexistent", 1,
                    chunk_dir=_CHUNK_DIR if _CHUNK_DIR.exists() else Path(tmpdir),
                    output_dir=Path(tmpdir),
                )


# ---------------------------------------------------------------------------
# Inject-bug proof: round_win rule skip → RED → revert → GREEN
#
# This is the critical regression guard: it proves that if the round_win rules
# are NOT applied, the correctness test turns RED (RTP ~128, integrity fails).
# When reverted, tests are GREEN again.
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_no_round_win_rules_rtp_doubles(self, monkeypatch):
        """Inject: monkey-patch load_rules_for_machine to return [].
        Assert: RTP exceeds double-count threshold AND integrity fails.
        This is the RED state that proves the guard is real.
        After monkeypatch auto-reverts, the GREEN state resumes.
        """
        if not _requires_chunks():
            pytest.skip("M15 cached chunks not present")

        import fresh_slotlab.round_win as rw_mod

        def _no_rules(machine_id, config):
            return []  # BUG: always return empty regardless of machine

        monkeypatch.setattr(rw_mod, "load_rules_for_machine", _no_rules)

        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks

        with tempfile.TemporaryDirectory() as tmpdir:
            summary = generate_report_from_chunks(
                "M15", 1,
                chunk_dir=_CHUNK_DIR,
                output_dir=Path(tmpdir),
            )
            rtp = summary["rtp"]["point_pct"]
            ric = summary.get("rtp_integrity_check", {})
            passed = ric.get("passed")

            # Inject-bug RED assertions: double-count artifact must be observable
            assert rtp >= _RTP_DOUBLE_COUNT_THRESHOLD, (
                f"inject-bug: with no round_win rules, M15 RTP should be >= {_RTP_DOUBLE_COUNT_THRESHOLD}% "
                f"(ST14 phantom double-count), got {rtp:.2f}%"
            )
            assert passed is not True, (
                f"inject-bug: with no round_win rules, rtp_integrity_check.passed must NOT be True, "
                f"got passed={passed} (sum(payid) incorrectly matches because ST14 phantom inflates both)"
            )
        # monkeypatch auto-reverts after this test — the next run (without inject) is GREEN

    def test_inject_rtp_integrity_gate_failure_surfaced(self, monkeypatch):
        """Inject: make check_rtp_integrity raise.
        Assert: engine captures the error in rtp_integrity_check (not silent swallow).
        This proves feedback_no_silent_swallow.md is honored.
        """
        if not _requires_chunks():
            pytest.skip("M15 cached chunks not present")

        import fresh_slotlab.analyzer.rtp_integrity as ri_mod

        def _buggy_check(*args, **kwargs):
            raise RuntimeError("injected_gate_failure")

        monkeypatch.setattr(ri_mod, "check_rtp_integrity", _buggy_check)

        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks

        with tempfile.TemporaryDirectory() as tmpdir:
            summary = generate_report_from_chunks(
                "M15", 1,
                chunk_dir=_CHUNK_DIR,
                output_dir=Path(tmpdir),
            )
            ric = summary.get("rtp_integrity_check", {})
            assert "error" in ric, (
                f"inject-bug: rtp_integrity gate failure must appear as 'error' key, got: {ric}"
            )
            assert "injected_gate_failure" in str(ric["error"])
            assert ric.get("passed") is None
