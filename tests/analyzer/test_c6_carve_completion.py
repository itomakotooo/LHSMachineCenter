"""Phase C6 — carve completion meta test (all 8 gaps closed on M275).

This is the "completion certificate" for the analyzer unbundle C-phases.
All 8 gaps from brief 00_brief.md must be closed as of C6.

Gap closure assertions
----------------------
#1  jackpot.applicable=True (C4 — machine_mechanics plugin).
#2  free_spin.applicable=True (C4 — machine_mechanics plugin).
#3  pid 666 trigger_marker in payout_ids_top20 (C6 — bonus_chain_dynamics plugin).
#4  multiplier_wild plugin output present (C3.5).
#5  payout_groups_top20=[] all-zeros filtered (C5 — PIA F2 fix).
#6  chunk_spin_times_recommendation present (C5 — collect_mechanic plugin).
#7  payouts_by_spin_type rows have shape/cols/paylines/notes (C3 enrichment).
#8  payout_ids_top20 rows have notes block (C6 — bonus_chain_dynamics plugin).

Cross-phase invariants
----------------------
- base_hash is the R-1 closure value (57fdb323585d as of phase-2a; registered plugins excluded by R-4).
- 9 plugins registered in ALL_FEATURES.
- feature_errors absent or empty for M275.
- No _ prefix stash keys at top level of final summary.

Inject-bug recipe C (CRITICAL — meta guard against gap regression)
------------------------------------------------------------------
Bug C: remove "bonus_chain_dynamics" from M275 manifest analyzer_features list.
    In slot_designer/configs/machine_manifests/M275.json, remove "bonus_chain_dynamics"
    from the analyzer_features array.
    RED: test_gap_3_pid_666_trigger_marker fails because the plugin no longer runs
         for M275 — payout_ids_top20 rows lack the 'notes' block.
         test_gap_8_payout_ids_top20_rows_have_notes also fails.
    Revert (restore "bonus_chain_dynamics" in M275.json) -> GREEN.

This test guards against future regressions that would re-open any of the 8 gaps.
The carve_completion test is the "single pane of glass" for the user/verifier.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (#3 trigger_marker is explicit alert signal, not catch-all)
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess required — gap assertions must run against real cached data)
- memory/feedback_aggregator_parity_invariant.md
  (all C6 plugins have RTP_CONTRIBUTION=False; must not alter rtp)
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
_M275_CACHE = _REPO_ROOT / "rawdata" / "M275" / "mode_1"


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m275_complete_summary() -> dict:
    """Run M275 mode 1 from cache; return parsed summary for all-gap assertion."""
    if not _M275_CACHE.exists() or not list(_M275_CACHE.glob("chunk_*.json")):
        pytest.skip(f"M275 mode 1 cached chunks not found at {_M275_CACHE}")

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable, str(_PIA),
            "--machine", "M275",
            "--rtp-mode", "1",
            "--from-cache", str(_M275_CACHE),
            "--output-dir", tmpdir,
            "--bet", "1000",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=300)
        assert result.returncode == 0, (
            f"M275 analyzer exited {result.returncode}.\n"
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )
        return json.loads((Path(tmpdir) / "player_impact_summary.json").read_bytes())


# ---------------------------------------------------------------------------
# T0: Preconditions (feature_errors + base_hash + plugin count)
# ---------------------------------------------------------------------------

class TestCarveCompletionPreconditions:
    """Preconditions that must hold before gap closure assertions are meaningful."""

    def test_no_feature_errors_m275(self, m275_complete_summary):
        """feature_errors must be absent or empty for M275.

        If any plugin throws, its gap closure assertion may be vacuously true
        (the key is absent, not wrong). Must confirm no errors first.
        """
        fe = m275_complete_summary.get("feature_errors", {})
        assert not fe, (
            f"feature_errors populated — some plugins failed for M275. "
            f"Gap assertions below may be vacuously true. "
            f"feature_errors: {json.dumps(fe, indent=2)[:500]}"
        )

    def test_base_hash_unchanged(self):
        """base_hash must be 57fdb323585d (R-1 closure value, post phase-2a).

        Phase honesty-2 (2026-05-29) redefined base_hash to the 25-file report-
        production import closure → 960e9d18d83d. All C-phase plugins are
        registered features excluded by R-4. Phase 2a carved collect_mechanic's
        compute (dict-builder + 2 private helpers) OUT of player_impact_analyzer.py
        (a closure file) → base re-baselined to 57fdb323585d (report content
        byte-identical; only where the code lives changed). The value is stable
        until another production-path file in _CLOSURE_FILES is modified.
        """
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        actual = compute_base_analyzer_version()
        assert actual == "57fdb323585d", (
            f"base_hash must be '57fdb323585d' (R-1 closure value, post phase-2a). "
            f"Got: {actual!r}. "
            f"Registered plugin modifications must NOT change base_hash (R-4 exclusion). "
            f"Check _CLOSURE_FILES in versioning.py for unintended production-path changes."
        )

    def test_nine_plugins_registered(self):
        """Exactly 9 plugins must be in ALL_FEATURES after all phase imports."""
        # Import all 9 to trigger registration
        import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
        import fresh_slotlab.analyzer.features.reel_marginal_by_spin_type  # noqa: F401
        import fresh_slotlab.analyzer.features.bankruptcy_simulation  # noqa: F401
        import fresh_slotlab.analyzer.features.multiplier_profile  # noqa: F401
        import fresh_slotlab.analyzer.features.multiplier_wild  # noqa: F401
        import fresh_slotlab.analyzer.features.machine_mechanics  # noqa: F401
        import fresh_slotlab.analyzer.features.upstream_feature_breakdown  # noqa: F401
        import fresh_slotlab.analyzer.features.collect_mechanic  # noqa: F401
        import fresh_slotlab.analyzer.features.bonus_chain_dynamics  # noqa: F401
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES
        count = len(ALL_FEATURES)
        assert count == 9, (
            f"Expected exactly 9 plugins in ALL_FEATURES. Got {count}: "
            f"{[f.FEATURE_ID for f in ALL_FEATURES]}"
        )

    def test_no_stash_keys_at_top_level(self, m275_complete_summary):
        """No _ prefix stash keys at top level of final summary."""
        stash_keys = [k for k in m275_complete_summary if k.startswith("_")]
        assert not stash_keys, (
            f"_-prefixed stash keys leaked into M275 final summary: {stash_keys}"
        )


# ---------------------------------------------------------------------------
# T1: Gap #1 — jackpot.applicable=True (C4)
# ---------------------------------------------------------------------------

class TestGap1JackpotApplicable:
    """Gap #1: machine_mechanics.jackpot.applicable must be True for M275 (C4)."""

    def test_gap_1_jackpot_applicable(self, m275_complete_summary):
        """machine_mechanics.jackpot.applicable must be True.

        M275 has high-numeric jackpot pids (pids >= 10000 seen in data).
        C4 machine_mechanics plugin detects this via Tier 3.

        Inject-bug C guard: if machine_mechanics is removed from M275 manifest,
        jackpot block will be absent → this test fires.
        """
        pi = m275_complete_summary.get("player_impact", {})
        mm = pi.get("machine_mechanics", {})
        assert mm, (
            "player_impact.machine_mechanics must be present for M275 (C4 plugin)."
        )
        jackpot = mm.get("jackpot", {})
        assert jackpot.get("applicable") is True, (
            f"Gap #1 not closed: machine_mechanics.jackpot.applicable must be True for M275. "
            f"Got: {jackpot.get('applicable')!r}"
        )


# ---------------------------------------------------------------------------
# T2: Gap #2 — free_spin.applicable=True (C4)
# ---------------------------------------------------------------------------

class TestGap2FreeSpinApplicable:
    """Gap #2: machine_mechanics.free_spin.applicable must be True for M275 (C4)."""

    def test_gap_2_free_spin_applicable(self, m275_complete_summary):
        """machine_mechanics.free_spin.applicable must be True.

        M275 has bonus chain data (NormalCollectionSpin + NewFreespin).
        C4 machine_mechanics plugin detects free_spin via Tier 2 (bonus_chain_lengths).
        """
        pi = m275_complete_summary.get("player_impact", {})
        mm = pi.get("machine_mechanics", {})
        free_spin = mm.get("free_spin", {})
        assert free_spin.get("applicable") is True, (
            f"Gap #2 not closed: machine_mechanics.free_spin.applicable must be True for M275. "
            f"Got: {free_spin.get('applicable')!r}"
        )


# ---------------------------------------------------------------------------
# T3: Gap #3 — pid 666 trigger_marker in payout_ids_top20 (C6 CRITICAL)
# ---------------------------------------------------------------------------

class TestGap3TriggerMarker:
    """Gap #3 (CRITICAL): pid 666 must have is_trigger_marker=True in payout_ids_top20.

    Inject-bug C: remove bonus_chain_dynamics from M275 manifest → plugin doesn't
    run → notes absent from payout_ids_top20 rows → this test fires.
    """

    def test_gap_3_pid_666_trigger_marker(self, m275_complete_summary):
        """pid 666 notes.is_trigger_marker must be True.

        INJECT-BUG (Bug C): remove 'bonus_chain_dynamics' from M275 manifest.
        RED: payout_ids_top20 rows lack 'notes' key (plugin never ran) → KeyError/assertion.
        Revert M275.json → GREEN.

        This is the primary guard for gap #3 regression.
        """
        pi = m275_complete_summary.get("player_impact", {})
        rows = pi.get("payout_ids_top20") or []
        assert rows, "payout_ids_top20 must be non-empty for M275."

        row_666 = next(
            (r for r in rows if str(r.get("payout_id", "")) == "666"),
            None
        )
        assert row_666 is not None, (
            f"pid 666 must be in payout_ids_top20 for M275. "
            f"Available pids: {[str(r.get('payout_id')) for r in rows]}"
        )
        notes = row_666.get("notes", {})
        assert notes.get("is_trigger_marker") is True, (
            f"Gap #3 not closed: pid 666 must have is_trigger_marker=True. "
            f"notes: {notes}"
        )

    def test_gap_3_trigger_target_present(self, m275_complete_summary):
        """pid 666 trigger_target must be non-None (gap #3 full closure)."""
        pi = m275_complete_summary.get("player_impact", {})
        rows = pi.get("payout_ids_top20") or []
        row_666 = next(
            (r for r in rows if str(r.get("payout_id", "")) == "666"), None
        )
        if row_666 is None:
            pytest.skip("pid 666 not in payout_ids_top20")
        notes = row_666.get("notes", {})
        assert notes.get("trigger_target") is not None, (
            f"Gap #3 not fully closed: trigger_target must be non-None for pid 666. "
            f"notes: {notes}"
        )


# ---------------------------------------------------------------------------
# T4: Gap #4 — multiplier_wild plugin output present (C3.5)
# ---------------------------------------------------------------------------

class TestGap4MultiplierWild:
    """Gap #4: player_impact.multiplier_wild must be present for M275 (C3.5)."""

    def test_gap_4_multiplier_wild_present(self, m275_complete_summary):
        """player_impact.multiplier_wild must be present."""
        pi = m275_complete_summary.get("player_impact", {})
        assert "multiplier_wild" in pi, (
            f"Gap #4 not closed: player_impact.multiplier_wild missing for M275. "
            f"C3.5 multiplier_wild plugin must declare M275."
        )


# ---------------------------------------------------------------------------
# T5: Gap #5 — payout_groups_top20=[] all-zeros filtered (C5)
# ---------------------------------------------------------------------------

class TestGap5PayoutGroupsFilter:
    """Gap #5: payout_groups_top20 must be [] for M275 (all-zeros filtered by C5)."""

    def test_gap_5_payout_groups_empty(self, m275_complete_summary):
        """payout_groups_top20 must be [] (not the noise row)."""
        pi = m275_complete_summary.get("player_impact", {})
        assert pi.get("payout_groups_top20") == [], (
            f"Gap #5 not closed: payout_groups_top20 is not []. "
            f"Got: {pi.get('payout_groups_top20')!r}"
        )

    def test_gap_5_status_all_zeros_filtered(self, m275_complete_summary):
        """payout_groups_status must be 'all_zeros_filtered'."""
        pi = m275_complete_summary.get("player_impact", {})
        assert pi.get("payout_groups_status") == "all_zeros_filtered", (
            f"Gap #5 not closed: payout_groups_status must be 'all_zeros_filtered'. "
            f"Got: {pi.get('payout_groups_status')!r}"
        )


# ---------------------------------------------------------------------------
# T6: Gap #6 — chunk_spin_times_recommendation present (C5)
# ---------------------------------------------------------------------------

class TestGap6ChunkSpinTimesRecommendation:
    """Gap #6: chunk_spin_times_recommendation must be present in M275 clamp_warning."""

    def test_gap_6_recommendation_present(self, m275_complete_summary):
        """collect_mechanic.clamp_warning.chunk_spin_times_recommendation must be present."""
        cm = m275_complete_summary.get("collect_mechanic", {})
        rec = cm.get("clamp_warning", {}).get("chunk_spin_times_recommendation")
        assert rec is not None, (
            "Gap #6 not closed: chunk_spin_times_recommendation absent in M275 clamp_warning. "
            "C5 collect_mechanic plugin must add this recommendation."
        )


# ---------------------------------------------------------------------------
# T7: Gap #7 — payouts_by_spin_type rows have shape/cols/paylines/notes (C3)
# ---------------------------------------------------------------------------

class TestGap7PayoutsBySpinTypeEnrich:
    """Gap #7: payouts_by_spin_type rows must have shape/cols/paylines/notes (C3 enrichment)."""

    def test_gap_7_payouts_by_spin_type_dict(self, m275_complete_summary):
        """payouts_by_spin_type must be a dict keyed by spin-type string."""
        pi = m275_complete_summary.get("player_impact", {})
        pbs = pi.get("payouts_by_spin_type", {})
        assert isinstance(pbs, dict), (
            f"payouts_by_spin_type must be a dict (per-ST mapping). Got {type(pbs).__name__}"
        )
        assert len(pbs) >= 1, (
            f"payouts_by_spin_type must have at least 1 spin-type. Got keys: {list(pbs.keys())}"
        )

    def test_gap_7_rows_have_required_fields(self, m275_complete_summary):
        """Sample payouts_by_spin_type rows must have shape/covered_columns/paylines/notes.

        C3 enrichment adds these to each per-(ST, pid) row. Check the first row of the
        first ST. If any field is missing, gap #7 is not closed for that row.
        """
        pi = m275_complete_summary.get("player_impact", {})
        pbs = pi.get("payouts_by_spin_type", {})
        if not pbs:
            pytest.skip("payouts_by_spin_type empty — cannot check row fields.")

        # Pick the first ST (alphabetically consistent with sorted dict output).
        first_st = sorted(pbs.keys())[0]
        rows = pbs[first_st]
        if not rows:
            pytest.skip(f"payouts_by_spin_type[{first_st!r}] is empty.")

        sample_row = rows[0]
        for field in ("shape", "covered_columns", "paylines", "notes"):
            assert field in sample_row, (
                f"Gap #7 not closed: payouts_by_spin_type[{first_st!r}][0] missing '{field}'. "
                f"C3 enrichment must add shape/covered_columns/paylines/notes to all rows. "
                f"Row keys: {sorted(sample_row.keys())}"
            )


# ---------------------------------------------------------------------------
# T8: Gap #8 — payout_ids_top20 rows have notes block (C6)
# ---------------------------------------------------------------------------

class TestGap8PayoutIdsTop20Notes:
    """Gap #8: payout_ids_top20 rows must have 'notes' block (C6 — bonus_chain_dynamics)."""

    def test_gap_8_payout_ids_top20_rows_have_notes(self, m275_complete_summary):
        """All payout_ids_top20 rows must have 'notes' block after C6.

        INJECT-BUG (Bug C): remove 'bonus_chain_dynamics' from M275 manifest.
        RED: plugin never runs → rows lack 'notes' → this test fires.
        Revert M275.json → GREEN.
        """
        pi = m275_complete_summary.get("player_impact", {})
        rows = pi.get("payout_ids_top20") or []
        assert rows, "payout_ids_top20 must be non-empty for M275."

        missing = [str(r.get("payout_id")) for r in rows if "notes" not in r]
        assert not missing, (
            f"Gap #8 not closed: payout_ids_top20 rows missing 'notes': pids {missing}. "
            f"C6 bonus_chain_dynamics plugin must add notes to all rows."
        )

    def test_gap_8_notes_have_is_trigger_marker(self, m275_complete_summary):
        """All payout_ids_top20 notes blocks must have 'is_trigger_marker' key."""
        pi = m275_complete_summary.get("player_impact", {})
        rows = pi.get("payout_ids_top20") or []

        missing = [
            str(r.get("payout_id"))
            for r in rows
            if "is_trigger_marker" not in r.get("notes", {})
        ]
        assert not missing, (
            f"Gap #8 not fully closed: notes missing 'is_trigger_marker' for pids: {missing}."
        )
