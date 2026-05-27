"""Phase C3.5 — subprocess e2e test for M275 mode 1 with multiplier_wild plugin.

Spawns the real player_impact_analyzer subprocess against M275 mode 1 cached
chunks. Verifies that multiplier_wild output is correctly populated, including:
  - 3 variants (wild2x, wild5x, wild10x)
  - Hit counts within ±10% of implementer-verified values
  - All 3 variants show col 1 dominance
  - by_spin_type split present (ST=140 paid + ST=126 free)
  - estimated_rtp_contribution_pp == null
  - estimated_rtp_method == "deferred_v2"

This is a real subprocess test per:
  memory/feedback_perf_claim_needs_e2e_event_stream.md
  memory/feedback_integration_test_argv.md

A unit test of extract()/reduce()/emit() alone cannot catch:
  - Registration failures at the 5 PIA import sites
  - Manifest-gating (plugin only runs when M275 declares it)
  - chunk_dict key names from real parser output

Implementer-verified baseline counts (M275 mode 1, 10k spins, 2026-05-27):
  wild2x: 3289 total hits (col 1 dominant)
  wild5x: 5120 total hits (col 1 dominant)
  wild10x: 2682 total hits (col 1 dominant)
  (Note: brief §4 AC#5 shows different per-ST breakdown for raw probe values;
   the chunk-rebuilt total is what we verify here.)

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug A — remove the from-cache pre-registration site (site 1):
    In fresh_slotlab/player_impact_analyzer.py, find the from-cache
    pre-registration block (~line 1534):
        import fresh_slotlab.analyzer.features.multiplier_wild  # noqa: F401  # C3.5
    Comment it out (# import ...).
    RED: multiplier_wild plugin NOT registered when from-cache path runs →
         multiplier_wild key absent from M275 summary →
         test_multiplier_wild_key_present fails.
    Revert (uncomment) → GREEN.
    This guards the 5-site registration trap from coupling_audit.md §2.2.

Bug B — remove multiplier_wild from M275.json analyzer_features:
    Change M275.json analyzer_features to remove "multiplier_wild".
    RED: plugin registered but manifest-gated → M275 doesn't invoke plugin →
         multiplier_wild key absent (or applicable=False) →
         test_multiplier_wild_applicable_true fails.
    Revert M275.json → GREEN.

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess test required — unit tests alone don't catch PIA registration bugs)
- memory/feedback_integration_test_argv.md
  (real subprocess invocation, not mocked)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_no_silent_swallow.md (analyzer_init_error surfaced via rc)
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_CACHE_DIR = _REPO_ROOT / "rawdata" / "M275" / "mode_1"

# Implementer-verified baseline counts for M275 mode 1 (2026-05-27 smoke run).
# Coordinator brief says: wild2x=3289, wild5x=5120, wild10x=2682.
# We allow ±10% since exact counts may vary if chunk files differ.
_BASELINE_COUNTS = {
    "wild2x": 3289,
    "wild5x": 5120,
    "wild10x": 2682,
}
_COUNT_TOLERANCE = 0.10  # ±10%


@pytest.fixture(scope="module")
def m275_c3_5_summary() -> dict:
    """Run M275 mode 1 analyzer with C3.5 plugin; return parsed summary."""
    if not _CACHE_DIR.exists() or not list(_CACHE_DIR.glob("chunk_*.json")):
        pytest.skip(f"M275 mode 1 cached chunks not found at {_CACHE_DIR}")

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable,
            str(_PIA),
            "--machine", "M275",
            "--rtp-mode", "1",
            "--from-cache", str(_CACHE_DIR),
            "--output-dir", tmpdir,
            "--bet", "1000",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            timeout=180,
        )
        assert result.returncode == 0, (
            f"M275 analyzer exited non-zero ({result.returncode}).\n"
            f"STDOUT: {result.stdout[:3000]}\n"
            f"STDERR: {result.stderr[:3000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists(), (
            f"summary.json not written. STDOUT: {result.stdout[:500]}"
        )
        data = json.loads(summary_path.read_bytes())
    return data


# ---------------------------------------------------------------------------
# T1: Analyzer health checks
# ---------------------------------------------------------------------------

class TestM275C3_5Health:
    """Basic health: no errors, rtp_integrity passes."""

    def test_no_analyzer_init_error(self, m275_c3_5_summary):
        """analyzer_init_error must be absent on success path."""
        assert "analyzer_init_error" not in m275_c3_5_summary, (
            f"analyzer_init_error present: {m275_c3_5_summary.get('analyzer_init_error')}"
        )

    def test_no_feature_errors(self, m275_c3_5_summary):
        """feature_errors must be absent or empty on success path."""
        fe = m275_c3_5_summary.get("feature_errors", {})
        assert not fe, (
            f"feature_errors unexpectedly populated (multiplier_wild may have thrown): {fe}"
        )

    def test_rtp_integrity_check_passed(self, m275_c3_5_summary):
        """rtp_integrity_check.passed must be True."""
        ric = m275_c3_5_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed is not True. Full value: {ric}"
        )


# ---------------------------------------------------------------------------
# T2: multiplier_wild key present + schema
# ---------------------------------------------------------------------------

class TestM275MultiplierWildKeyPresent:
    """multiplier_wild must be in summary["player_impact"]."""

    def test_multiplier_wild_key_present(self, m275_c3_5_summary):
        """summary["player_impact"]["multiplier_wild"] must exist.

        INJECT-BUG (Bug A): remove the from-cache pre-registration import line.
        RED: plugin not registered → key absent → this assertion fails.
        Revert → GREEN.

        This guards the 5-site registration trap described in §2.5.
        """
        pi = m275_c3_5_summary.get("player_impact", {})
        assert "multiplier_wild" in pi, (
            f"'multiplier_wild' must be present in player_impact. "
            f"Got keys: {sorted(pi.keys())}. "
            f"Check all 5 plugin registration sites in PIA."
        )

    def test_multiplier_wild_top_level_schema(self, m275_c3_5_summary):
        """multiplier_wild dict must have all 5 required top-level keys."""
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        required = {
            "applicable", "variants", "total_multiplier_wild_hits",
            "estimated_rtp_contribution_pp", "estimated_rtp_method",
        }
        missing = required - set(mw.keys())
        assert not missing, (
            f"multiplier_wild missing required keys: {missing}. Got: {sorted(mw.keys())}"
        )

    def test_multiplier_wild_applicable_true(self, m275_c3_5_summary):
        """applicable must be True for M275 (it has wildNx symbols in data).

        INJECT-BUG (Bug B): remove "multiplier_wild" from M275.json analyzer_features.
        RED: plugin manifest-gated out → M275 doesn't run plugin →
             key absent or applicable=False → this assertion fails.
        Revert M275.json → GREEN.
        """
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        assert mw["applicable"] is True, (
            f"applicable must be True for M275. Got: {mw['applicable']!r}. "
            f"M275 has wildNx symbols in its cached data — applicable=False "
            f"means the plugin ran but found no data (check chunk_dict key names)."
        )

    def test_estimated_rtp_contribution_pp_is_null(self, m275_c3_5_summary):
        """estimated_rtp_contribution_pp must be null (deferred to v2)."""
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        assert mw["estimated_rtp_contribution_pp"] is None, (
            f"estimated_rtp_contribution_pp must be None (null), "
            f"got {mw['estimated_rtp_contribution_pp']!r}"
        )

    def test_estimated_rtp_method_is_deferred_v2(self, m275_c3_5_summary):
        """estimated_rtp_method must be 'deferred_v2'."""
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        assert mw["estimated_rtp_method"] == "deferred_v2", (
            f"estimated_rtp_method must be 'deferred_v2', "
            f"got {mw['estimated_rtp_method']!r}"
        )


# ---------------------------------------------------------------------------
# T3: 3 variants present
# ---------------------------------------------------------------------------

class TestM275ThreeVariants:
    """Exactly 3 variants (wild2x, wild5x, wild10x) must be present."""

    def test_three_variants_present(self, m275_c3_5_summary):
        """M275 has wild2x, wild5x, wild10x in its data — all 3 must appear.

        INJECT-BUG (Bug A): remove pre-registration import → plugin not called →
        key absent → fixture assertion fails before this test.
        This test guards that variant list is not empty.
        """
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        variants = mw["variants"]
        assert len(variants) == 3, (
            f"Expected 3 variants (wild2x, wild5x, wild10x), got {len(variants)}. "
            f"Variants: {[v['symbol'] for v in variants]}"
        )

    def test_variant_symbols_are_wild2x_wild5x_wild10x(self, m275_c3_5_summary):
        """Variant symbols must be exactly: wild2x, wild5x, wild10x."""
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        symbols = {v["symbol"] for v in mw["variants"]}
        expected = {"wild2x", "wild5x", "wild10x"}
        assert symbols == expected, (
            f"Expected variant symbols {expected}, got {symbols}"
        )

    def test_variants_sorted_by_multiplier_value_ascending(self, m275_c3_5_summary):
        """Variants must be sorted by multiplier_value ascending (wild2x first)."""
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        mult_values = [v["multiplier_value"] for v in mw["variants"]]
        assert mult_values == sorted(mult_values), (
            f"Variants must be sorted by multiplier_value ascending. "
            f"Got: {mult_values}"
        )
        assert mult_values[0] == 2, f"First variant must be wild2x (value=2), got {mult_values[0]}"


# ---------------------------------------------------------------------------
# T4: Hit count ballpark checks (±10% of implementer values)
# ---------------------------------------------------------------------------

class TestM275HitCountBallpark:
    """Hit counts must be within ±10% of implementer-verified baseline values."""

    def _get_variant(self, m275_c3_5_summary, symbol: str) -> dict:
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        for v in mw["variants"]:
            if v["symbol"] == symbol:
                return v
        pytest.fail(f"Variant '{symbol}' not found in multiplier_wild output")

    def test_wild2x_total_hits_ballpark(self, m275_c3_5_summary):
        """wild2x total_hits must be within ±10% of baseline (3289)."""
        v = self._get_variant(m275_c3_5_summary, "wild2x")
        baseline = _BASELINE_COUNTS["wild2x"]
        lo = baseline * (1 - _COUNT_TOLERANCE)
        hi = baseline * (1 + _COUNT_TOLERANCE)
        assert lo <= v["total_hits"] <= hi, (
            f"wild2x total_hits={v['total_hits']} outside ±10% of baseline {baseline}. "
            f"Expected [{lo:.0f}, {hi:.0f}]."
        )

    def test_wild5x_total_hits_ballpark(self, m275_c3_5_summary):
        """wild5x total_hits must be within ±10% of baseline (5120)."""
        v = self._get_variant(m275_c3_5_summary, "wild5x")
        baseline = _BASELINE_COUNTS["wild5x"]
        lo = baseline * (1 - _COUNT_TOLERANCE)
        hi = baseline * (1 + _COUNT_TOLERANCE)
        assert lo <= v["total_hits"] <= hi, (
            f"wild5x total_hits={v['total_hits']} outside ±10% of baseline {baseline}. "
            f"Expected [{lo:.0f}, {hi:.0f}]."
        )

    def test_wild10x_total_hits_ballpark(self, m275_c3_5_summary):
        """wild10x total_hits must be within ±10% of baseline (2682)."""
        v = self._get_variant(m275_c3_5_summary, "wild10x")
        baseline = _BASELINE_COUNTS["wild10x"]
        lo = baseline * (1 - _COUNT_TOLERANCE)
        hi = baseline * (1 + _COUNT_TOLERANCE)
        assert lo <= v["total_hits"] <= hi, (
            f"wild10x total_hits={v['total_hits']} outside ±10% of baseline {baseline}. "
            f"Expected [{lo:.0f}, {hi:.0f}]."
        )

    def test_total_hits_is_positive(self, m275_c3_5_summary):
        """Total multiplier_wild_hits must be positive."""
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        assert mw["total_multiplier_wild_hits"] > 0, (
            f"total_multiplier_wild_hits must be positive, got {mw['total_multiplier_wild_hits']}"
        )


# ---------------------------------------------------------------------------
# T5: Column 1 dominance
# ---------------------------------------------------------------------------

class TestM275ColOneDominance:
    """All 3 variants should show col 1 dominance (implementer probe: all col 1)."""

    def _get_variant(self, m275_c3_5_summary, symbol: str) -> dict:
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        for v in mw["variants"]:
            if v["symbol"] == symbol:
                return v
        pytest.fail(f"Variant '{symbol}' not found")

    def _dominant_col(self, variant: dict) -> int:
        """Return the col with the highest hit count."""
        by_col = variant["by_column"]
        assert by_col, f"by_column is empty for {variant['symbol']}"
        return max(by_col, key=lambda e: e["hits"])["col"]

    def test_wild2x_col_1_has_hits(self, m275_c3_5_summary):
        """wild2x must have hits in col 1 (implementer probe shows all col 1)."""
        v = self._get_variant(m275_c3_5_summary, "wild2x")
        col1_entries = [e for e in v["by_column"] if e["col"] == 1]
        assert col1_entries, (
            f"wild2x by_column has no col 1 entry. "
            f"Got cols: {[e['col'] for e in v['by_column']]}"
        )
        assert col1_entries[0]["hits"] > 0, (
            f"wild2x col 1 hits must be > 0"
        )

    def test_wild5x_col_1_has_hits(self, m275_c3_5_summary):
        """wild5x must have hits in col 1."""
        v = self._get_variant(m275_c3_5_summary, "wild5x")
        col1_entries = [e for e in v["by_column"] if e["col"] == 1]
        assert col1_entries and col1_entries[0]["hits"] > 0, (
            f"wild5x must have hits in col 1. Got: {v['by_column']}"
        )

    def test_wild10x_col_1_has_hits(self, m275_c3_5_summary):
        """wild10x must have hits in col 1."""
        v = self._get_variant(m275_c3_5_summary, "wild10x")
        col1_entries = [e for e in v["by_column"] if e["col"] == 1]
        assert col1_entries and col1_entries[0]["hits"] > 0, (
            f"wild10x must have hits in col 1. Got: {v['by_column']}"
        )

    def test_by_column_has_hit_rate_field(self, m275_c3_5_summary):
        """Each by_column entry must have a hit_rate field."""
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        for variant in mw["variants"]:
            for entry in variant["by_column"]:
                assert "hit_rate" in entry, (
                    f"by_column entry missing hit_rate: {entry} "
                    f"in {variant['symbol']}"
                )
                assert isinstance(entry["hit_rate"], float), (
                    f"hit_rate must be float, got {type(entry['hit_rate'])}"
                )


# ---------------------------------------------------------------------------
# T6: by_spin_type split present
# ---------------------------------------------------------------------------

class TestM275SpinTypeSplit:
    """by_spin_type must contain paid + free entries (M275 has both ST=140 and ST=126)."""

    def _get_variant(self, m275_c3_5_summary, symbol: str) -> dict:
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        for v in mw["variants"]:
            if v["symbol"] == symbol:
                return v
        pytest.fail(f"Variant '{symbol}' not found")

    def test_by_spin_type_present_and_nonempty(self, m275_c3_5_summary):
        """All variants must have non-empty by_spin_type."""
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        for variant in mw["variants"]:
            assert variant["by_spin_type"], (
                f"by_spin_type is empty for {variant['symbol']}. "
                f"M275 has both paid (ST=140) and free (ST=126) spins."
            )

    def test_paid_spin_type_present(self, m275_c3_5_summary):
        """At least one 'paid' behavior entry in by_spin_type for each variant."""
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        for variant in mw["variants"]:
            paid_entries = [
                e for e in variant["by_spin_type"]
                if e.get("behavior") == "paid"
            ]
            assert paid_entries, (
                f"No 'paid' behavior entry in by_spin_type for {variant['symbol']}. "
                f"Got: {variant['by_spin_type']}"
            )
            assert paid_entries[0]["hits"] > 0, (
                f"Paid spin hits must be > 0 for {variant['symbol']}"
            )

    def test_free_spin_type_present(self, m275_c3_5_summary):
        """At least one 'free' behavior entry in by_spin_type for each variant."""
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        for variant in mw["variants"]:
            free_entries = [
                e for e in variant["by_spin_type"]
                if e.get("behavior") == "free"
            ]
            assert free_entries, (
                f"No 'free' behavior entry in by_spin_type for {variant['symbol']}. "
                f"Got: {variant['by_spin_type']}. "
                f"M275 has freespins (ST=126) — they must appear in the split."
            )

    def test_by_spin_type_entry_schema(self, m275_c3_5_summary):
        """Each by_spin_type entry must have spin_type (int), behavior (str), hits (int)."""
        mw = m275_c3_5_summary["player_impact"]["multiplier_wild"]
        for variant in mw["variants"]:
            for entry in variant["by_spin_type"]:
                assert "spin_type" in entry and isinstance(entry["spin_type"], int), (
                    f"spin_type must be int: {entry}"
                )
                assert "behavior" in entry and isinstance(entry["behavior"], str), (
                    f"behavior must be str: {entry}"
                )
                assert "hits" in entry and isinstance(entry["hits"], int), (
                    f"hits must be int: {entry}"
                )


# ---------------------------------------------------------------------------
# T7: effective_analyzer_version in summary matches versioning module
# ---------------------------------------------------------------------------

class TestM275EffectiveVersionInSummary:
    """effective_analyzer_version in M275 summary must be the C3.5 value."""

    def test_effective_version_matches_c3_5(self, m275_c3_5_summary):
        """effective_analyzer_version in summary must be 2ef11cd69c8d (C3.5 value)."""
        try:
            from fresh_slotlab.analyzer.versioning import compute_effective_version_for_machine
        except ImportError:
            from analyzer.versioning import compute_effective_version_for_machine  # type: ignore[no-redef]

        expected = compute_effective_version_for_machine("M275", 1)
        actual = m275_c3_5_summary.get("effective_analyzer_version", "")
        assert actual == expected, (
            f"effective_analyzer_version in M275 summary must match versioning module. "
            f"Summary has {actual!r}, module returns {expected!r}."
        )
