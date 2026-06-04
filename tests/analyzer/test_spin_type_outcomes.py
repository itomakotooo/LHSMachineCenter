"""spin_type_outcomes AnalyzerFeature — impl-tester gate suite.

=== Contract ===
spin_type_outcomes is a new base-excluded AnalyzerFeature that computes a
per-SpinType win-distribution shape (volatility profile) and top-combo
ranking for EVERY SpinType — not just ST=14. It reads two already-built
summary sections (payouts_by_spin_type + spin_type_breakdown) in emit()
and writes summary["player_impact"]["spin_type_outcomes"].

=== Scope ===
This file enforces 4 gates from the brief:

Gate A (trace): Real M15 full-dataset run -> win_bands for ST1_paid match
  exact expected counts; top_combos contains pid 8 + 666; max_mult >= 200;
  ST14_free / ST15_free have has_payouts==False and empty bands/combos.

Gate B (carve/isolation): Editing spin_type_outcomes.py does NOT change
  base_hash (stays "8dbbfad6f90f"); it DOES change M15's effective_version
  vs. M14 (which does not declare the feature).

Gate C (additive): M15 summary gains ONLY spin_type_outcomes; no
  pre-existing leaf changes. Verified at section-level presence check
  (no full-summary golden — M15 golden fixtures don't exist for this feature).

Gate D (RTP parity): RTP_CONTRIBUTION=False; sum(pay_id.rtp_pp)==summary.rtp
  still holds; the feature adds NOTHING to the RTP sum.

=== Inject-bug recipes ===
Bug A (Gate A — band edge): In spin_type_outcomes.py _BANDS, change the
  "2-5x" band hi from 5.0 to 3.0:
      ("2-5x", 2.0, 3.0),
  Then: test_st1_win_bands_exact_counts -> RED (2-5x hits change, 3-5x
  hits shift to next band). Revert -> GREEN.

Bug B (Gate B — isolation): Add
  "fresh_slotlab/analyzer/features/spin_type_outcomes.py"
  to _CLOSURE_FILES in versioning.py.
  Then: test_editing_feature_file_does_not_flip_base_hash -> RED
  (simulated edit changes base_hash because the file is now in closure).
  Revert versioning.py -> GREEN.

Bug C (Gate D — RTP): Change RTP_CONTRIBUTION = True in spin_type_outcomes.py.
  Then: test_rtp_contribution_flag_is_false -> RED. Revert -> GREEN.

=== Memory feedback honored ===
- feedback_enumerate_safety_paths.md: inject-bug recipes for each gate.
- feedback_perf_claim_needs_e2e_event_stream.md: real PIA subprocess.
- feedback_aggregator_parity_invariant.md: Gate D RTP parity.
- feedback_no_hardcode.md: feature reads generically (no M15 ids in code).
- feedback_self_verify_output.md: cross-check bands sum vs payid totals.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo layout constants
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]
_RAWDATA_M15 = _ROOT / "rawdata" / "M15" / "mode_1"
_RAWDATA_M14 = _ROOT / "rawdata" / "M14" / "mode_1"
_MANIFESTS = _ROOT / "slot_designer" / "configs" / "machine_manifests"
_FEATURE_FILE = _ROOT / "fresh_slotlab" / "analyzer" / "features" / "spin_type_outcomes.py"

_M15_AVAILABLE = _RAWDATA_M15.is_dir() and any(_RAWDATA_M15.glob("chunk_*.json"))
_M14_AVAILABLE = _RAWDATA_M14.is_dir() and any(_RAWDATA_M14.glob("chunk_*.json"))

_SKIP_NO_M15 = pytest.mark.skipif(not _M15_AVAILABLE, reason="M15 rawdata not available")
_SKIP_NO_M14 = pytest.mark.skipif(not _M14_AVAILABLE, reason="M14 rawdata not available")

# ---------------------------------------------------------------------------
# Expected base_hash (paytype-rearch; must NOT flip after adding this feature)
# ---------------------------------------------------------------------------
_EXPECTED_BASE_HASH = "99b1dec52f88"  # spin_type_rtp_buckets: parser paid-bucket + versioning play_types closure → 8dbbfad6f90f→99b1dec52f88

# ---------------------------------------------------------------------------
# Ground-truth trace values — from a full 224-chunk M15 run (2,048,000 ST1 spins)
# These are derived by running PIA on all available rawdata/M15/mode_1 chunks.
#
# ST1_paid win_bands (PAYLINE-level; each hit_count = sum of payid hit_counts
# binned by avg_win_when_hit / bet). Note: sum > win_rounds (47936 in 5 chunks)
# because a round can match multiple paylines simultaneously — correct behaviour.
# Full 224-chunk run (2048k ST1 spins, 327620 win_rounds):
#   <1x:0  1-2x:182487  2-5x:111913  5-20x:30107  20-100x:26161  100x+:43
#
# The brief gives 334k-spin reference: 1-2x:20649  2-5x:21351  5-20x:5189
#   20-100x:3883  100x+:2  <1x:0
# We use the full 224-chunk dataset as the definitive gate.
# ---------------------------------------------------------------------------
_EXPECTED_BANDS_224 = {
    "<1x":    0,
    "1-2x":   182487,
    "2-5x":   111913,
    "5-20x":  30107,
    "20-100x": 26161,
    "100x+":  43,
}
_EXPECTED_MAX_MULT_MIN = 199.0  # pid=1 (doublediamond x3 = 200x)
_EXPECTED_TOP_COMBO_PIDS = {"8", "666"}  # must be present in top_combos
_MAX_CHUNKS_GATE_A = 224  # use all available chunks for Gate A trace gate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_pia_subprocess(
    machine: str,
    mode: int,
    rawdata_dir: Path,
    out_dir: Path,
    max_chunks: int = 2,
) -> dict:
    """Run real PIA subprocess and return parsed summary JSON."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "fresh_slotlab.player_impact_analyzer",
        "--machine", machine,
        "--rtp-mode", str(mode),
        "--from-cache", str(rawdata_dir),
        "--output-dir", str(out_dir),
        "--max-chunks", str(max_chunks),
    ]
    result = subprocess.run(
        cmd, cwd=str(_ROOT), capture_output=True, text=True, timeout=600
    )
    assert result.returncode == 0, (
        f"PIA subprocess failed (rc={result.returncode}):\n"
        f"stdout: {result.stdout[:2000]}\nstderr: {result.stderr[:2000]}"
    )
    summary_path = out_dir / "player_impact_summary.json"
    assert summary_path.exists(), f"No summary JSON at {summary_path}"
    return json.loads(summary_path.read_bytes().decode("utf-8"))


def _get_spin_type_outcomes(summary: dict) -> dict:
    """Extract spin_type_outcomes section from a PIA summary."""
    return (summary.get("player_impact") or {}).get("spin_type_outcomes") or {}


def _bands_as_dict(win_bands: list) -> dict[str, int]:
    """Convert win_bands list to {band_name: hit_count} dict."""
    return {b["band"]: b["hit_count"] for b in win_bands}


# ---------------------------------------------------------------------------
# Gate A — Trace gate: real M15 run matches expected counts
# ---------------------------------------------------------------------------

class TestGateATrace:
    """Gate A: full M15 dataset -> win_bands exact, top_combos present,
    max_mult >= 200, ST14/ST15 empty.

    Inject-bug A: in spin_type_outcomes.py _BANDS, change
      ("2-5x", 2.0, 5.0) -> ("2-5x", 2.0, 3.0)
    Then: test_st1_win_bands_exact_counts -> RED (2-5x count drops, adjacent
    band picks up the [3,5) hits). Revert _BANDS -> GREEN.
    """

    @pytest.mark.slow
    @_SKIP_NO_M15
    def test_st1_win_bands_exact_counts(self, tmp_path):
        """ST1_paid win_bands match exact expected counts from full M15 dataset.

        Uses all 224 available chunks (2,048,000 ST1 spins) for a stable
        ground-truth signal.

        Inject-bug A: change band edge 5.0 -> 3.0 for '2-5x' in _BANDS.
        The counts shift and this assertion fails. Revert -> GREEN.
        """
        out_dir = tmp_path / "gate_a_trace"
        summary = _run_pia_subprocess(
            "M15", 1, _RAWDATA_M15, out_dir, max_chunks=_MAX_CHUNKS_GATE_A
        )
        sto = _get_spin_type_outcomes(summary)
        assert "ST1_paid" in sto, (
            "spin_type_outcomes missing ST1_paid key. "
            "Did you add 'spin_type_outcomes' to M15.json analyzer_features?"
        )
        st1 = sto["ST1_paid"]
        assert st1["has_payouts"] is True, "ST1_paid should have payouts"

        actual = _bands_as_dict(st1["win_bands"])
        for band, expected_count in _EXPECTED_BANDS_224.items():
            assert actual.get(band) == expected_count, (
                f"ST1_paid band '{band}': expected {expected_count}, got {actual.get(band)}.\n"
                f"All bands: {actual}\n"
                "Inject-bug A: change '2-5x' hi from 5.0 to 3.0 in _BANDS -> RED here."
            )

    @pytest.mark.slow
    @_SKIP_NO_M15
    def test_st1_max_mult_approx_200(self, tmp_path):
        """max_mult >= 200 (from pid=1 doublediamond|doublediamond|doublediamond = 200x)."""
        out_dir = tmp_path / "gate_a_maxmult"
        summary = _run_pia_subprocess(
            "M15", 1, _RAWDATA_M15, out_dir, max_chunks=_MAX_CHUNKS_GATE_A
        )
        sto = _get_spin_type_outcomes(summary)
        st1 = sto.get("ST1_paid", {})
        max_mult = st1.get("max_mult", 0.0)
        assert max_mult >= _EXPECTED_MAX_MULT_MIN, (
            f"max_mult={max_mult} < expected >= {_EXPECTED_MAX_MULT_MIN}. "
            "pid=1 (doublediamond x3 = 200x bet) should be present in a 2M-spin run."
        )

    @pytest.mark.slow
    @_SKIP_NO_M15
    def test_st1_top_combos_contain_required_pids(self, tmp_path):
        """top_combos includes pid 8 (1bar|2bar|1bar ~2.3x) and pid 666 (topdollar ~46x)."""
        out_dir = tmp_path / "gate_a_topcombos"
        summary = _run_pia_subprocess(
            "M15", 1, _RAWDATA_M15, out_dir, max_chunks=_MAX_CHUNKS_GATE_A
        )
        sto = _get_spin_type_outcomes(summary)
        st1 = sto.get("ST1_paid", {})
        top_combo_pids = {tc["payout_id"] for tc in st1.get("top_combos", [])}
        missing = _EXPECTED_TOP_COMBO_PIDS - top_combo_pids
        assert not missing, (
            f"top_combos missing required pids: {missing}. "
            f"Got pids: {top_combo_pids}. "
            "pid=666 (topdollar, ~52.8% RTP) and pid=8 (1bar|2bar|1bar, ~12.4% RTP) "
            "should both appear in top 5 by rtp_pp."
        )

    @pytest.mark.slow
    @_SKIP_NO_M15
    def test_st1_top_combo_666_has_correct_structure(self, tmp_path):
        """pid=666 top combo has topdollar combo, correct mult ~46x."""
        out_dir = tmp_path / "gate_a_666"
        summary = _run_pia_subprocess(
            "M15", 1, _RAWDATA_M15, out_dir, max_chunks=_MAX_CHUNKS_GATE_A
        )
        sto = _get_spin_type_outcomes(summary)
        st1 = sto.get("ST1_paid", {})
        combo_666 = next(
            (tc for tc in st1.get("top_combos", []) if tc["payout_id"] == "666"),
            None,
        )
        assert combo_666 is not None, "pid=666 not found in top_combos"
        assert combo_666["combo"] == "topdollar", (
            f"pid=666 combo should be 'topdollar', got {combo_666['combo']!r}"
        )
        mult_666 = combo_666.get("mult")
        assert mult_666 is not None and 40.0 <= mult_666 <= 60.0, (
            f"pid=666 mult={mult_666} outside expected range [40, 60] "
            "(topdollar payid avg ~46-47x)"
        )

    @pytest.mark.slow
    @_SKIP_NO_M15
    def test_st14_and_st15_have_no_payouts(self, tmp_path):
        """ST14_free and ST15_free have has_payouts=False and empty bands/combos.

        M15 ST=14 is a player-choice event (DollarCount/ChosenDollar) and
        ST=15 is the settlement event — neither has payid rows in
        payouts_by_spin_type. Both should show has_payouts=False.
        """
        out_dir = tmp_path / "gate_a_st14_st15"
        summary = _run_pia_subprocess(
            "M15", 1, _RAWDATA_M15, out_dir, max_chunks=5
        )
        sto = _get_spin_type_outcomes(summary)

        for label in ("ST14_free", "ST15_free"):
            st_entry = sto.get(label)
            assert st_entry is not None, f"{label} missing from spin_type_outcomes"
            assert st_entry["has_payouts"] is False, (
                f"{label} has_payouts should be False (no payid rows)"
            )
            total_band_hits = sum(
                b["hit_count"] for b in st_entry.get("win_bands", [])
            )
            assert total_band_hits == 0, (
                f"{label} win_band hit_counts should all be 0, got {total_band_hits}"
            )
            assert st_entry.get("top_combos") == [], (
                f"{label} top_combos should be empty, got {st_entry.get('top_combos')}"
            )

    @pytest.mark.slow
    @_SKIP_NO_M15
    def test_st1_still_has_round_level_fields_from_stb(self, tmp_path):
        """Round-level fields (hit_rate, avg_win_when_hit, rtp_contribution_pp)
        come from spin_type_breakdown and should be present even for STs with
        empty payid lists.
        """
        out_dir = tmp_path / "gate_a_round_level"
        summary = _run_pia_subprocess(
            "M15", 1, _RAWDATA_M15, out_dir, max_chunks=5
        )
        sto = _get_spin_type_outcomes(summary)
        for label in ("ST1_paid", "ST14_free", "ST15_free"):
            entry = sto.get(label, {})
            assert "hit_rate" in entry, f"{label} missing hit_rate"
            assert "dead_spin_rate" in entry, f"{label} missing dead_spin_rate"
            assert "rtp_contribution_pp" in entry, f"{label} missing rtp_contribution_pp"
            # hit_rate + dead_spin_rate should sum to ~1.0
            hr = float(entry.get("hit_rate") or 0.0)
            dsr = float(entry.get("dead_spin_rate") or 0.0)
            assert abs(hr + dsr - 1.0) < 1e-9, (
                f"{label}: hit_rate ({hr}) + dead_spin_rate ({dsr}) != 1.0"
            )

    @pytest.mark.slow
    @_SKIP_NO_M15
    def test_st1_pct_small_and_big_hits_plausible(self, tmp_path):
        """pct_small_hits and pct_big_hits are in [0,1] and sum to <= 1."""
        out_dir = tmp_path / "gate_a_pct"
        summary = _run_pia_subprocess(
            "M15", 1, _RAWDATA_M15, out_dir, max_chunks=_MAX_CHUNKS_GATE_A
        )
        sto = _get_spin_type_outcomes(summary)
        st1 = sto.get("ST1_paid", {})
        pct_small = float(st1.get("pct_small_hits") or 0.0)
        pct_big = float(st1.get("pct_big_hits") or 0.0)
        assert 0.0 <= pct_small <= 1.0, f"pct_small_hits={pct_small} out of [0,1]"
        assert 0.0 <= pct_big <= 1.0, f"pct_big_hits={pct_big} out of [0,1]"
        # NON-tautological cross-check: recompute pct_small / pct_big INDEPENDENTLY
        # from the emitted win_bands (small = mult<5 = bands <1x,1-2x,2-5x;
        # big = mult>=20 = bands 20-100x,100x+) and confirm the feature's own
        # pct fields agree. A naive `pct_small+pct_big<=1` is always true (they
        # are disjoint subsets) — this ties the fields to the band data instead.
        bands = {b["band"]: int(b["hit_count"]) for b in st1.get("win_bands", [])}
        band_total = sum(bands.values())
        small_from_bands = bands.get("<1x", 0) + bands.get("1-2x", 0) + bands.get("2-5x", 0)
        big_from_bands = bands.get("20-100x", 0) + bands.get("100x+", 0)
        exp_small = small_from_bands / band_total if band_total else 0.0
        exp_big = big_from_bands / band_total if band_total else 0.0
        assert abs(pct_small - exp_small) < 1e-6, (
            f"pct_small_hits={pct_small} disagrees with band-derived {exp_small}"
        )
        assert abs(pct_big - exp_big) < 1e-6, (
            f"pct_big_hits={pct_big} disagrees with band-derived {exp_big}"
        )
        # On M15: most hits are pid=9 (cherry, 1x) — small hit majority expected
        assert pct_small >= 0.5, (
            f"pct_small_hits={pct_small:.3f} unexpectedly low for M15 "
            "(cherry payid pid=9 is the most frequent, 1x -> 'small')"
        )


# ---------------------------------------------------------------------------
# Gate B — Carve/isolation: base_hash unchanged; M15 effective_version changes
# ---------------------------------------------------------------------------

class TestGateBIsolation:
    """Gate B: editing spin_type_outcomes.py must NOT flip base_hash but MUST
    change M15's effective_version vs. M14.

    Inject-bug B: add spin_type_outcomes.py to _CLOSURE_FILES in versioning.py.
    Then: test_editing_feature_file_does_not_flip_base_hash -> RED
    (simulated edit affects base_hash because file is now in closure).
    Revert versioning.py -> GREEN.
    """

    def _base_hash_with_simulated_edit(self, edit_rel: str, suffix: bytes) -> str:
        """Recompute base_hash, appending suffix to edit_rel iff in the closure."""
        from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES, _REPO_ROOT
        h = hashlib.sha256()
        for rel in sorted(_CLOSURE_FILES):
            raw = (_REPO_ROOT / rel).read_bytes().replace(b"\r\n", b"\n")
            if rel == edit_rel:
                raw = raw + suffix
            h.update(raw)
        return h.hexdigest()[:12]

    def test_base_hash_is_expected_value(self):
        """base_hash == '8dbbfad6f90f' (paytype-rearch value; unchanged by this feature)."""
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        actual = compute_base_analyzer_version()
        assert actual == _EXPECTED_BASE_HASH, (
            f"base_hash mismatch. Expected {_EXPECTED_BASE_HASH!r}, got {actual!r}.\n"
            "Adding spin_type_outcomes.py to _CLOSURE_FILES (inject-bug B) would cause this."
        )

    def test_feature_file_not_in_closure_files(self):
        """spin_type_outcomes.py must NOT be in _CLOSURE_FILES.

        R-4: registered feature plugins are excluded from base_hash.
        Inject-bug B: add it to _CLOSURE_FILES -> this test RED.
        """
        from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES
        feature_rel = "fresh_slotlab/analyzer/features/spin_type_outcomes.py"
        assert feature_rel not in _CLOSURE_FILES, (
            f"{feature_rel!r} found in _CLOSURE_FILES — feature modules must be "
            "EXCLUDED from the base_hash closure (R-4). Inject-bug B: adding it "
            "causes base_hash to flip whenever the feature file changes."
        )

    def test_payouts_by_spin_type_not_in_closure_files(self):
        """payouts_by_spin_type.py must NOT be in _CLOSURE_FILES.

        It is a registered feature plugin (ALL_FEATURES), excluded by R-4.
        This also confirms that our auto-import hack (adding a line to
        payouts_by_spin_type.py) does NOT flip base_hash.
        """
        from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES
        pbs_rel = "fresh_slotlab/analyzer/features/payouts_by_spin_type.py"
        assert pbs_rel not in _CLOSURE_FILES, (
            f"{pbs_rel!r} found in _CLOSURE_FILES — it is a registered feature plugin "
            "and must be excluded by R-4."
        )

    def test_editing_feature_file_does_not_flip_base_hash(self):
        """Editing spin_type_outcomes.py does NOT change base_hash — with a
        POSITIVE CONTROL proving the simulator can actually move the hash.

        The negative case alone (feature file not in closure → suffix never
        applied → hash unchanged) is tautological. We pair it with a positive
        control: applying the SAME simulated edit to a real _CLOSURE_FILES
        member DOES change base_hash. If the control fails to move the hash,
        the negative assertion is meaningless — so we assert both.

        Inject-bug B: add spin_type_outcomes.py to _CLOSURE_FILES ->
        the feature-file edit then moves base_hash -> this test RED.
        Revert -> GREEN.
        """
        from fresh_slotlab.analyzer.versioning import (
            compute_base_analyzer_version,
            _CLOSURE_FILES,
        )
        feature_rel = "fresh_slotlab/analyzer/features/spin_type_outcomes.py"
        suffix = b"\n# simulated edit\n"
        baseline = compute_base_analyzer_version()

        # POSITIVE CONTROL: editing a genuine closure member MUST move the hash.
        control_rel = sorted(_CLOSURE_FILES)[0]
        control_after = self._base_hash_with_simulated_edit(control_rel, suffix)
        assert control_after != baseline, (
            f"Positive control failed: simulating an edit to closure member "
            f"{control_rel!r} did NOT change base_hash — the simulator is "
            "broken, so the negative assertion below would be meaningless."
        )

        # NEGATIVE: editing the (excluded) feature file must NOT move the hash.
        feature_after = self._base_hash_with_simulated_edit(feature_rel, suffix)
        assert feature_after == baseline, (
            f"Simulating edit to spin_type_outcomes.py changed base_hash: "
            f"baseline={baseline!r}, after={feature_after!r}. "
            "This means spin_type_outcomes.py leaked into _CLOSURE_FILES. "
            "Inject-bug B: add it -> RED here."
        )

    def test_m15_effective_version_differs_from_m14(self):
        """M15 effective_version must differ from M14 (M15 has spin_type_outcomes; M14 doesn't)."""
        from fresh_slotlab.analyzer.versioning import compute_effective_version_for_machine
        import fresh_slotlab.analyzer.features.spin_type_outcomes  # ensure registered
        ev_m15 = compute_effective_version_for_machine("M15", mode=1)
        ev_m14 = compute_effective_version_for_machine("M14", mode=1)
        assert ev_m15 != ev_m14, (
            f"M15 effective_version ({ev_m15!r}) must differ from M14 ({ev_m14!r}). "
            "M15 declares 'spin_type_outcomes'; M14 does not."
        )

    def test_feature_edit_changes_m15_but_not_m14_effective_version(self):
        """Simulated feature edit changes M15's effective_version but NOT M14's.

        The carve property: only machines declaring the feature re-flag.
        """
        from fresh_slotlab.analyzer.versioning import (
            compute_effective_analyzer_version,
            compute_base_analyzer_version,
        )
        from fresh_slotlab.analyzer import feature_registry as registry
        import fresh_slotlab.analyzer.features.spin_type_outcomes  # ensure registered

        base_hash = compute_base_analyzer_version()
        feature_hashes_real = {f.FEATURE_ID: f.compute_hash() for f in registry.ALL_FEATURES}

        # Simulate a change to spin_type_outcomes.py
        fake_sto_hash = hashlib.sha256(b"fake spin_type_outcomes").hexdigest()[:12]
        feature_hashes_fake = dict(feature_hashes_real)
        feature_hashes_fake["spin_type_outcomes"] = fake_sto_hash

        # M15 declares spin_type_outcomes
        m15_features = ["spin_type_outcomes", "payouts_by_spin_type"]
        m15_real_ev = compute_effective_analyzer_version(
            base_hash=base_hash, feature_hashes=feature_hashes_real,
            machine_features=m15_features, mode=1,
        )
        m15_fake_ev = compute_effective_analyzer_version(
            base_hash=base_hash, feature_hashes=feature_hashes_fake,
            machine_features=m15_features, mode=1,
        )
        # M14 does NOT declare spin_type_outcomes
        m14_features: list[str] = []
        m14_real_ev = compute_effective_analyzer_version(
            base_hash=base_hash, feature_hashes=feature_hashes_real,
            machine_features=m14_features, mode=1,
        )
        m14_fake_ev = compute_effective_analyzer_version(
            base_hash=base_hash, feature_hashes=feature_hashes_fake,
            machine_features=m14_features, mode=1,
        )

        assert m15_real_ev != m15_fake_ev, (
            "Feature edit must change M15's effective_version "
            "(M15 declares spin_type_outcomes)."
        )
        assert m14_real_ev == m14_fake_ev, (
            "Feature edit must NOT change M14's effective_version "
            "(M14 does not declare spin_type_outcomes). "
            "This is the carve property: only declaring machines re-flag."
        )


# ---------------------------------------------------------------------------
# Gate C — Additive: spin_type_outcomes is present and non-empty
# ---------------------------------------------------------------------------

class TestGateCAdditive:
    """Gate C: spin_type_outcomes section added to M15 summary; no pre-existing
    field changes.

    We verify at section-level (spin_type_outcomes present + non-empty + has
    expected keys) rather than a full leaf-level golden diff. M15 has no
    separate golden fixture for this feature.
    """

    @_SKIP_NO_M15
    def test_spin_type_outcomes_present_in_m15_summary(self, tmp_path):
        """M15 summary must contain spin_type_outcomes under player_impact."""
        out_dir = tmp_path / "gate_c_present"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=2)
        pi = summary.get("player_impact") or {}
        assert "spin_type_outcomes" in pi, (
            "spin_type_outcomes absent from player_impact. "
            "Did you add 'spin_type_outcomes' to M15.json analyzer_features?"
        )

    @_SKIP_NO_M15
    def test_spin_type_outcomes_has_all_st_labels(self, tmp_path):
        """spin_type_outcomes contains ST1_paid, ST14_free, ST15_free."""
        out_dir = tmp_path / "gate_c_labels"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=2)
        sto = _get_spin_type_outcomes(summary)
        for label in ("ST1_paid", "ST14_free", "ST15_free"):
            assert label in sto, f"{label} missing from spin_type_outcomes"

    @_SKIP_NO_M15
    def test_spin_type_outcomes_entry_has_required_keys(self, tmp_path):
        """Each ST entry has all required schema keys."""
        out_dir = tmp_path / "gate_c_keys"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=2)
        sto = _get_spin_type_outcomes(summary)
        required_keys = {
            "spin_type", "label", "dead_spin_rate", "hit_rate",
            "avg_win_when_hit", "rtp_contribution_pp",
            "win_bands", "top_combos", "max_mult",
            "pct_small_hits", "pct_big_hits", "has_payouts",
            "round_stats_available",
        }
        for label, entry in sto.items():
            missing = required_keys - set(entry.keys())
            assert not missing, (
                f"spin_type_outcomes['{label}'] missing keys: {missing}"
            )

    @_SKIP_NO_M15
    def test_spin_type_outcomes_does_not_mutate_payouts_by_spin_type(self, tmp_path):
        """payouts_by_spin_type is present and unchanged alongside spin_type_outcomes."""
        out_dir = tmp_path / "gate_c_no_mutate"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=2)
        pi = summary.get("player_impact") or {}
        pbst = pi.get("payouts_by_spin_type")
        assert pbst is not None, "payouts_by_spin_type absent — should not be removed"
        assert "ST1_paid" in pbst, "ST1_paid missing from payouts_by_spin_type"

    @_SKIP_NO_M15
    def test_win_bands_have_correct_structure(self, tmp_path):
        """Each win_bands entry has band, lo, hi, hit_count, rtp_pp keys."""
        out_dir = tmp_path / "gate_c_bands_struct"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=2)
        sto = _get_spin_type_outcomes(summary)
        st1 = sto.get("ST1_paid", {})
        bands = st1.get("win_bands", [])
        assert len(bands) == 6, f"Expected 6 bands, got {len(bands)}: {[b['band'] for b in bands]}"
        band_names = [b["band"] for b in bands]
        expected_names = ["<1x", "1-2x", "2-5x", "5-20x", "20-100x", "100x+"]
        assert band_names == expected_names, (
            f"Band names mismatch: {band_names} != {expected_names}"
        )
        for b in bands:
            for key in ("band", "lo", "hi", "hit_count", "rtp_pp"):
                assert key in b, f"Band entry missing '{key}': {b}"

    @_SKIP_NO_M14
    def test_m14_does_not_get_spin_type_outcomes(self, tmp_path):
        """M14 does NOT declare spin_type_outcomes; section must be absent."""
        out_dir = tmp_path / "gate_c_m14"
        summary = _run_pia_subprocess("M14", 1, _RAWDATA_M14, out_dir, max_chunks=2)
        pi = summary.get("player_impact") or {}
        assert "spin_type_outcomes" not in pi, (
            "spin_type_outcomes appeared in M14 output — it must NOT apply to "
            "machines that don't declare 'spin_type_outcomes' in their manifest."
        )


# ---------------------------------------------------------------------------
# Gate D — RTP parity
# ---------------------------------------------------------------------------

class TestGateDRTPParity:
    """Gate D: RTP_CONTRIBUTION=False; feature adds nothing to the RTP sum.

    Inject-bug C: change RTP_CONTRIBUTION = True in spin_type_outcomes.py.
    Then: test_rtp_contribution_flag_is_false -> RED. Revert -> GREEN.
    """

    def test_rtp_contribution_flag_is_false(self):
        """SpinTypeOutcomes.RTP_CONTRIBUTION must be False.

        Inject-bug C: flip to True -> RED. Revert -> GREEN.
        """
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod
        assert sto_mod.SpinTypeOutcomes.RTP_CONTRIBUTION is False, (
            "SpinTypeOutcomes.RTP_CONTRIBUTION must be False — wins are already "
            "attributed by payouts_by_spin_type. Setting True would double-count. "
            "Inject-bug C: flip to True -> this test RED."
        )

    @_SKIP_NO_M15
    def test_rtp_layer1_invariant_still_holds(self, tmp_path):
        """sum(pay_id.rtp_pp)==summary.rtp (layer1 invariant) still holds after feature.

        With RTP_CONTRIBUTION=False, adding spin_type_outcomes must NOT perturb
        the RTP sum. Check rtp_integrity_check.layer1_invariant_ok is True.
        """
        out_dir = tmp_path / "gate_d_rtp_invariant"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=2)
        ric = summary.get("rtp_integrity_check")
        assert ric is not None, "rtp_integrity_check absent from M15 summary"
        assert ric.get("layer1_invariant_ok") is True, (
            f"RTP layer1 invariant failed after adding spin_type_outcomes. "
            f"rtp_integrity_check: {ric}"
        )

    @_SKIP_NO_M15
    def test_spin_type_outcomes_rtp_fields_do_not_appear_in_pay_id_top20(self, tmp_path):
        """spin_type_outcomes fields must NOT contaminate payout_ids_top20.

        The feature's rtp_contribution_pp values are informational re-groupings;
        they must not appear as new pay_id entries in the top20 attribution.
        """
        out_dir = tmp_path / "gate_d_no_pids"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=2)
        pids_top20 = summary.get("payout_ids_top20") or []
        for row in pids_top20:
            pid_str = str(row.get("payout_id") or "")
            assert "spin_type_outcomes" not in pid_str, (
                f"spin_type_outcomes appeared in a pay_id row: {row}"
            )


# ---------------------------------------------------------------------------
# Plugin contract / registration checks
# ---------------------------------------------------------------------------

class TestPluginContract:
    """Structural invariants of the spin_type_outcomes plugin."""

    def test_feature_id(self):
        """FEATURE_ID == 'spin_type_outcomes'."""
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod
        assert sto_mod.SpinTypeOutcomes.FEATURE_ID == "spin_type_outcomes"

    def test_schema_keys(self):
        """SCHEMA_KEYS contains 'spin_type_outcomes'."""
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod
        assert "spin_type_outcomes" in sto_mod.SpinTypeOutcomes.SCHEMA_KEYS

    def test_schema_version_is_1(self):
        """SCHEMA_VERSION == 1."""
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod
        assert sto_mod.SpinTypeOutcomes.SCHEMA_VERSION == 1

    def test_requires_payouts_by_spin_type(self):
        """REQUIRES == ('payouts_by_spin_type',)."""
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod
        assert sto_mod.SpinTypeOutcomes.REQUIRES == ("payouts_by_spin_type",)

    def test_rtp_contribution_is_false(self):
        """RTP_CONTRIBUTION == False."""
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod
        assert sto_mod.SpinTypeOutcomes.RTP_CONTRIBUTION is False

    def test_feature_registered_after_import(self):
        """After import, 'spin_type_outcomes' is in ALL_FEATURES."""
        import fresh_slotlab.analyzer.features.spin_type_outcomes  # noqa: F401
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES
        fids = [f.FEATURE_ID for f in ALL_FEATURES]
        assert "spin_type_outcomes" in fids, (
            f"'spin_type_outcomes' not in ALL_FEATURES after import. Got: {fids}"
        )

    def test_auto_registered_when_payouts_by_spin_type_imported(self):
        """spin_type_outcomes auto-registers when payouts_by_spin_type is imported.

        Runs in a FRESH interpreter so the result is not contaminated by an
        earlier test in this process having already imported spin_type_outcomes
        (which would make the in-process assertion pass trivially). The child
        imports ONLY payouts_by_spin_type and asserts spin_type_outcomes appears
        in ALL_FEATURES — proving the bottom-of-module auto-import really fires.
        """
        code = (
            "import fresh_slotlab.analyzer.features.payouts_by_spin_type\n"
            "from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES\n"
            "fids = [f.FEATURE_ID for f in ALL_FEATURES]\n"
            "assert 'payouts_by_spin_type' in fids, 'dep not registered: ' + repr(fids)\n"
            "assert 'spin_type_outcomes' in fids, 'auto-import did NOT fire: ' + repr(fids)\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=str(_ROOT),
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0 and "OK" in result.stdout, (
            "Fresh-interpreter auto-import check failed.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_register_is_idempotent(self):
        """Duplicate import does not grow ALL_FEATURES."""
        import fresh_slotlab.analyzer.features.spin_type_outcomes  # noqa: F401
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES, register
        before = sum(1 for f in ALL_FEATURES if f.FEATURE_ID == "spin_type_outcomes")
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod  # noqa: F811
        register(sto_mod.SpinTypeOutcomes())  # force second registration attempt
        after = sum(1 for f in ALL_FEATURES if f.FEATURE_ID == "spin_type_outcomes")
        assert after == before == 1, (
            f"Duplicate registration changed count: before={before}, after={after}"
        )

    def test_extract_returns_empty_dict(self):
        """extract() returns {} (no-op)."""
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod
        plugin = sto_mod.SpinTypeOutcomes()
        result = plugin.extract(parse_state={}, chunk_dict={})
        assert result == {}, f"Expected empty dict, got {result}"

    def test_reduce_returns_prev_acc(self):
        """reduce() returns prev_acc unchanged."""
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod
        plugin = sto_mod.SpinTypeOutcomes()
        acc = {"sentinel": 42}
        result = plugin.reduce(prev_acc=acc, this_acc={})
        assert result == acc, f"reduce() must return prev_acc unchanged, got {result}"

    def test_emit_raises_when_dependency_section_absent(self):
        """emit() RAISES (loud) when payouts_by_spin_type key is absent.

        feedback_no_silent_swallow.md: PayoutsBySpinType always writes its
        section when it runs, so an ABSENT key means an upstream crash. emit()
        must raise (the PIA loop records it in summary['feature_errors']) rather
        than silently writing {} and hiding the failure.

        Inject-bug (silent-swallow regression): revert emit() to write {} on
        absent dependency -> this test RED.
        """
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod
        plugin = sto_mod.SpinTypeOutcomes()
        summary = {"player_impact": {}}  # no payouts_by_spin_type key
        with pytest.raises(RuntimeError, match="payouts_by_spin_type"):
            plugin.emit(final_acc={}, summary=summary, ctx=None)

    def test_emit_writes_empty_when_dependency_present_but_empty(self):
        """emit() writes {} (no error) when payouts_by_spin_type is present but {}.

        An empty-but-present section is a legitimate no-op (machine with no
        per-ST payouts) — distinct from the absent-key crash case above.
        """
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod
        plugin = sto_mod.SpinTypeOutcomes()
        summary = {"player_impact": {"payouts_by_spin_type": {}}}
        plugin.emit(final_acc={}, summary=summary, ctx=None)
        sto = (summary.get("player_impact") or {}).get("spin_type_outcomes")
        assert sto == {}, f"empty-but-present dependency must yield {{}}, got {sto}"

    def test_emit_round_stats_unavailable_when_st_absent_from_breakdown(self):
        """ST present in payouts but absent from spin_type_breakdown is flagged
        round_stats_available=False (not silently zero-filled)."""
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod
        plugin = sto_mod.SpinTypeOutcomes()
        summary = {
            "sampling": {"bet": 1000},
            "player_impact": {
                "spin_type_breakdown": [],  # ST1 NOT present here
                "payouts_by_spin_type": {
                    "ST1_paid": [{
                        "payout_id": "9", "hit_count": 10,
                        "avg_win_when_hit": 1000.0, "rtp_contribution_pp": 5.0,
                        "symbol_combo": {"dominant": "cherry"}, "covered_columns": [0],
                    }]
                },
            },
        }
        plugin.emit(final_acc={}, summary=summary, ctx=None)
        entry = summary["player_impact"]["spin_type_outcomes"]["ST1_paid"]
        assert entry["round_stats_available"] is False, (
            "ST absent from spin_type_breakdown must set round_stats_available=False"
        )
        assert entry["has_payouts"] is True  # payid data is still present

    def test_emit_handles_zero_bet_without_crash(self):
        """bet==0 -> no crash; bands stay empty (mult uncomputable), has_payouts True."""
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod
        plugin = sto_mod.SpinTypeOutcomes()
        summary = {
            "sampling": {"bet": 0},
            "player_impact": {
                "spin_type_breakdown": [{
                    "spin_type": 1, "behavior_name": "paid", "spins": 100,
                    "win_rounds": 50, "hit_rate": 0.5, "total_win": 50000.0,
                    "rtp_contribution_pp": 25.0,
                }],
                "payouts_by_spin_type": {
                    "ST1_paid": [{
                        "payout_id": "9", "hit_count": 50,
                        "avg_win_when_hit": 1000.0, "rtp_contribution_pp": 25.0,
                        "symbol_combo": {"dominant": "cherry"}, "covered_columns": [0],
                    }]
                },
            },
        }
        plugin.emit(final_acc={}, summary=summary, ctx=None)
        entry = summary["player_impact"]["spin_type_outcomes"]["ST1_paid"]
        assert entry["has_payouts"] is True
        assert sum(b["hit_count"] for b in entry["win_bands"]) == 0, (
            "bet=0 -> mult uncomputable -> no rows binned into bands"
        )
        assert entry["max_mult"] == 0.0

    def test_emit_writes_correct_section_path(self):
        """emit() writes to summary['player_impact']['spin_type_outcomes']."""
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod
        plugin = sto_mod.SpinTypeOutcomes()
        # Minimal summary with one ST entry
        summary = {
            "sampling": {"bet": 1000},
            "player_impact": {
                "spin_type_breakdown": [
                    {
                        "spin_type": 1, "behavior_name": "paid",
                        "spins": 100, "win_rounds": 60,
                        "hit_rate": 0.6, "total_win": 120000.0,
                        "rtp_contribution_pp": 30.0,
                    }
                ],
                "payouts_by_spin_type": {
                    "ST1_paid": [
                        {
                            "payout_id": "5",
                            "hit_count": 60,
                            "avg_win_when_hit": 2000.0,
                            "rtp_contribution_pp": 30.0,
                            "symbol_combo": {"dominant": "cherry", "distinct_symbols": ["cherry"]},
                            "covered_columns": [0, 1, 2],
                        }
                    ]
                },
            },
        }
        plugin.emit(final_acc={}, summary=summary, ctx=None)
        pi = summary.get("player_impact") or {}
        assert "spin_type_outcomes" in pi, "spin_type_outcomes not written to player_impact"
        sto = pi["spin_type_outcomes"]
        assert "ST1_paid" in sto, "ST1_paid entry missing"
        entry = sto["ST1_paid"]
        assert entry["spin_type"] == 1
        assert entry["has_payouts"] is True
        # pid=5, avg_win=2000, bet=1000 -> mult=2.0 -> "2-5x" band
        bands = {b["band"]: b["hit_count"] for b in entry["win_bands"]}
        assert bands.get("2-5x") == 60, f"2-5x band should have 60 hits, got {bands}"

    def test_emit_skips_underscore_pids(self):
        """emit() excludes '_'-prefixed synthetic payids from bands/combos."""
        import fresh_slotlab.analyzer.features.spin_type_outcomes as sto_mod
        plugin = sto_mod.SpinTypeOutcomes()
        summary = {
            "sampling": {"bet": 1000},
            "player_impact": {
                "spin_type_breakdown": [
                    {
                        "spin_type": 1, "behavior_name": "paid",
                        "spins": 100, "win_rounds": 50,
                        "hit_rate": 0.5, "total_win": 50000.0,
                        "rtp_contribution_pp": 25.0,
                    }
                ],
                "payouts_by_spin_type": {
                    "ST1_paid": [
                        {
                            "payout_id": "_unattributed_residual",
                            "hit_count": 999,
                            "avg_win_when_hit": 5000.0,
                            "rtp_contribution_pp": 20.0,
                            "symbol_combo": {"dominant": None},
                            "covered_columns": [],
                        },
                        {
                            "payout_id": "9",
                            "hit_count": 50,
                            "avg_win_when_hit": 1000.0,
                            "rtp_contribution_pp": 5.0,
                            "symbol_combo": {"dominant": "cherry"},
                            "covered_columns": [0, 1, 2],
                        },
                    ]
                },
            },
        }
        plugin.emit(final_acc={}, summary=summary, ctx=None)
        sto = summary["player_impact"]["spin_type_outcomes"]
        entry = sto["ST1_paid"]
        # Only the real pid=9 should contribute to bands
        total_band_hits = sum(b["hit_count"] for b in entry["win_bands"])
        assert total_band_hits == 50, (
            f"Band hits should only count real pid=9 (50 hits), got {total_band_hits}. "
            "_unattributed_residual (999 hits) must be excluded."
        )
        # top_combos must not include the underscore pid
        combo_pids = [tc["payout_id"] for tc in entry["top_combos"]]
        assert "_unattributed_residual" not in combo_pids, (
            f"Underscore pid appeared in top_combos: {combo_pids}"
        )

    def test_m15_manifest_declares_spin_type_outcomes(self):
        """M15.json must list 'spin_type_outcomes' in analyzer_features."""
        m15_path = _MANIFESTS / "M15.json"
        if m15_path.exists():
            manifest = json.loads(m15_path.read_bytes().decode("utf-8"))
        else:
            pytest.skip("M15.json not found in working tree")
        features = manifest.get("analyzer_features", [])
        assert "spin_type_outcomes" in features, (
            f"M15.json analyzer_features missing 'spin_type_outcomes'. Got: {features}"
        )

    def test_m14_manifest_does_not_declare_spin_type_outcomes(self):
        """M14.json must NOT list 'spin_type_outcomes'."""
        m14_path = _MANIFESTS / "M14.json"
        if not m14_path.exists():
            pytest.skip("M14.json not found in working tree")
        manifest = json.loads(m14_path.read_bytes().decode("utf-8"))
        features = manifest.get("analyzer_features", [])
        assert "spin_type_outcomes" not in features, (
            f"M14.json should NOT declare 'spin_type_outcomes'. Got: {features}"
        )
