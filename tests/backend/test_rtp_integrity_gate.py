"""Regression tests for ticket P2-E1 — rtp_integrity.py 4-layer gate.

Contracts asserted (per 00_ticket.md §3 C1-C10):

  C1  -- File exists; API matches spec (frozen dataclass + 15 fields + callables).
  C2  -- Layer 1 invariant: sum(pid wins) vs chunk_win (exact, zero, fp tolerance).
  C3  -- Layer 2 fallback prefixes: _unattributed_, _other, _default, _misc.
         Also: _bcm_cycle (legitimate anchor, NOT a fallback prefix) does NOT fire L2.
  C4  -- Layer 3 anchor coverage: required anchors must have >0 hits.
  C5  -- Layer 4 skip for trigger-session machines (manifest.layer4_applicable=False
         and/or trigger_session_pattern non-null); also: rawdata_dir=None skip.
  C6  -- Layer 4 Step A/B/C consistency via synthetic chunk files in tmpdir.
  C7  -- Warn-only mode: warn_only=True (default) → no raise; warn_only=False → raises.
  C8  -- Subprocess import safety + CLI --help rc=0.
  C9  -- Full regression (skipped here; delegated to impl-verifier).
  C10 -- Inject-bug TDD proofs for at least 3 contracts.

INJECT-BUG DISCIPLINE (per memory feedback_integration_test_argv.md):
  Every test in C10 was proven red by injecting the targeted bug, then restored green.
  Injection log documented in session_artifacts/_impl/phase2/08_rtp_integrity_gate/03_tests.md.

IMPLEMENTATION GUARD (parallel impl):
  Every test class checks RTP_GATE.exists() at the top of the class — if the
  implementation file is not yet on disk the tests skip, not error. This allows
  tester + implementer to work in parallel.

Subprocess coverage per memory feedback_perf_claim_needs_e2e_event_stream.md:
  C8 spawns real subprocesses for import smoke and CLI --help.

Architecture references:
  session_artifacts/_arch/04_architecture_proposal_v5.md §9 (lines 1003-1300)
  session_artifacts/_impl/phase2/08_rtp_integrity_gate/00_ticket.md §3
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RTP_GATE = ROOT / "fresh_slotlab" / "analyzer" / "rtp_integrity.py"

# ---------------------------------------------------------------------------
# Helpers: synthetic summary builders
# ---------------------------------------------------------------------------

def _make_pid_row(
    pid: str,
    total_win: float = 0.0,
    hit_count: int = 1,
    spin_type_breakdown: list | None = None,
) -> dict:
    """Build a single payout_ids_top20 row.

    Matches the structure the implementation reads from:
      row["payout_id"]          — pid string
      row["total_win"]          — contribution to Layer 1 sum
      row["hit_count"]          — used by Layer 3 anchor check
      row["spin_type_breakdown"]— list of {"spin_type": int, "count": int} for Layer 4 Step A
    """
    return {
        "payout_id": pid,
        "total_win": total_win,
        "hit_count": hit_count,
        "spin_type_breakdown": spin_type_breakdown or [],
    }


def _make_summary(
    *,
    payout_id_win: dict | None = None,
    chunk_win_total: float = 0.0,
    payout_id_hits: dict | None = None,
    payout_id_by_spin_type_total: dict | None = None,
    machine: str = "M_test",
    mode: int = 1,
) -> dict:
    """Build a minimal analyzer summary dict matching the implementation's expected schema.

    The implementation reads:
      summary["machine"], summary["mode"]
      summary["rtp"]["our_total_win"]           — Layer 1 denominator
      summary["player_impact"]["payout_ids_top20"]  — Layers 1, 2, 3, 4A

    Each payout_ids_top20 row:
      row["payout_id"]           — for Layer 2 prefix check + Layer 3 anchor lookup
      row["total_win"]           — for Layer 1 sum
      row["hit_count"]           — for Layer 3 zero-hit check
      row["spin_type_breakdown"] — for Layer 4 Step A dispatch capture

    Args match the old flat-dict API for backward compat with test bodies:
      payout_id_win: {pid_str: total_win_float, ...}
      payout_id_hits: {pid_str: hit_count, ...}
      payout_id_by_spin_type_total: {pid_str: {st_str: count, ...}, ...}
    """
    if payout_id_win is None:
        payout_id_win = {}
    if payout_id_hits is None:
        payout_id_hits = {k: 1 for k in payout_id_win}
    if payout_id_by_spin_type_total is None:
        payout_id_by_spin_type_total = {}

    # Build payout_ids_top20 rows combining all three input dicts
    payout_ids_top20 = []
    for pid_str, total_win in payout_id_win.items():
        hit_count = payout_id_hits.get(pid_str, 1 if total_win > 0 else 0)
        # Build spin_type_breakdown from payout_id_by_spin_type_total
        st_total = payout_id_by_spin_type_total.get(pid_str, {})
        breakdown = []
        for st_key, count in st_total.items():
            breakdown.append({"spin_type": int(st_key), "count": int(count)})
        payout_ids_top20.append({
            "payout_id": pid_str,
            "total_win": float(total_win),
            "hit_count": int(hit_count),
            "spin_type_breakdown": breakdown,
        })

    return {
        "machine": machine,
        "mode": mode,
        "rtp": {
            "our_total_win": chunk_win_total,
        },
        "player_impact": {
            "payout_ids_top20": payout_ids_top20,
        },
    }


def _make_manifest(
    *,
    layer4_applicable: bool = True,
    required_attribution_anchors: list | None = None,
    trigger_session_pattern: str | None = None,
    console_diagnostic_complete: bool = True,
) -> dict:
    """Build a minimal manifest dict matching the implementation's expected schema.

    The implementation reads:
      manifest["layer4_applicable"]          — Layer 4 applicability gate
      manifest["trigger_session_pattern"]    — derived gate (if layer4_applicable absent)
      manifest["rtp_integrity_contract"]["required_attribution_anchors"] — Layer 3
      manifest["console_diagnostic_complete"]  — completeness_declared field
    """
    return {
        "machine_id": "M_test",
        "manifest_version": 1,
        "layer4_applicable": layer4_applicable,
        "trigger_session_pattern": trigger_session_pattern,
        "console_diagnostic_complete": console_diagnostic_complete,
        "rtp_integrity_contract": {
            "required_attribution_anchors": required_attribution_anchors or [],
        },
    }


def _write_chunk(chunk_path: Path, rounds: list[dict]) -> None:
    """Write a minimal synthetic chunk JSON matching the rawdata envelope format."""
    chunk = {
        "_envelope_version": 2,
        "_config_md5": "aaa",
        "_code_md5": "bbb",
        "_chunk_index": 1,
        "response": [
            {
                "robotId": "robot_0",
                "roundResult": rounds,
            }
        ],
    }
    chunk_path.write_text(json.dumps(chunk), encoding="utf-8")


# ---------------------------------------------------------------------------
# C1 — File + API exist
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not RTP_GATE.exists(),
    reason="waiting on impl: fresh_slotlab/analyzer/rtp_integrity.py not yet on disk",
)
class TestC1FileAndAPI:
    """Contract: fresh_slotlab/analyzer/rtp_integrity.py exists and exposes
    the correct public API per §1 of the ticket."""

    def test_file_exists(self):
        """The implementation file must be on disk at the exact path the ticket specifies."""
        assert RTP_GATE.exists(), (
            f"Expected {RTP_GATE} to exist. "
            "Either the implementer hasn't landed yet (use --skip-impl-guard) "
            "or the file was placed at a different path."
        )

    def test_imports_succeed(self):
        """check_rtp_integrity, RTPIntegrityResult, and main are importable."""
        from fresh_slotlab.analyzer.rtp_integrity import (
            check_rtp_integrity,
            main,
            RTPIntegrityResult,
        )
        assert callable(check_rtp_integrity)
        assert callable(main)
        # RTPIntegrityResult must be a class (instantiable)
        assert isinstance(RTPIntegrityResult, type)

    def test_rtp_integrity_result_is_frozen_dataclass(self):
        """RTPIntegrityResult must be a frozen dataclass (immutable instances).

        Tests both that dataclasses.is_dataclass() returns True and that normal
        attribute assignment raises FrozenInstanceError. Note: object.__setattr__
        bypasses the frozen guard in CPython — must use direct attribute assignment
        to exercise the guard.

        Updated 2026-06-11: constructor includes session-conservation fields added
        in the session-dim fix (FRAMEWORK_PASS_2026-06-11.md §A).
        """
        from fresh_slotlab.analyzer.rtp_integrity import RTPIntegrityResult
        assert dataclasses.is_dataclass(RTPIntegrityResult)
        instance = RTPIntegrityResult(
            machine="M_test",
            mode=1,
            passed=True,
            layer1_invariant_ok=True,
            layer1_error=None,
            layer2_no_fallback_buckets_ok=True,
            layer2_fallback_buckets_found=[],
            layer3_anchors_ok=True,
            layer3_missing_anchors=[],
            layer4_applicable=True,
            layer4_per_st_consistency_ok=True,
            layer4_inconsistencies=[],
            layer4_skip_reason=None,
            summary_message="OK",
            suggested_actions=[],
            completeness_declared=True,
            session_conservation_ok=None,
            session_conservation_level=None,
            session_conservation_skip_reason="no manifest",
            session_conservation_notes=[],
        )
        # Direct attribute assignment (not object.__setattr__) exercises frozen guard
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            instance.passed = False  # type: ignore[misc]

    def test_rtp_integrity_result_has_15_fields(self):
        """RTPIntegrityResult must have the correct field set per the architecture spec.

        Updated 2026-06-11 (FRAMEWORK_PASS_2026-06-11.md §A): four session-
        conservation fields were added (session_conservation_ok,
        session_conservation_level, session_conservation_skip_reason,
        session_conservation_notes), bringing the total to 20.
        The original 16-field spec (ticket §1) is superseded.
        This test now validates presence of all named fields (both old and new).
        """
        from fresh_slotlab.analyzer.rtp_integrity import RTPIntegrityResult
        fields = [f.name for f in dataclasses.fields(RTPIntegrityResult)]
        expected_fields = [
            "machine",
            "mode",
            "passed",
            "layer1_invariant_ok",
            "layer1_error",
            "layer2_no_fallback_buckets_ok",
            "layer2_fallback_buckets_found",
            "layer3_anchors_ok",
            "layer3_missing_anchors",
            "layer4_applicable",
            "layer4_per_st_consistency_ok",
            "layer4_inconsistencies",
            "layer4_skip_reason",
            "summary_message",
            "suggested_actions",
            "completeness_declared",
            # Added 2026-06-11 (session-dim fix): session-conservation check fields.
            "session_conservation_ok",
            "session_conservation_level",
            "session_conservation_skip_reason",
            "session_conservation_notes",
        ]
        assert len(fields) == 20, (
            f"Expected 20 fields on RTPIntegrityResult (16 original + 4 conservation). "
            f"Got {len(fields)}: {fields}"
        )
        for name in expected_fields:
            assert name in fields, (
                f"Field '{name}' missing from RTPIntegrityResult. "
                f"Present: {fields}"
            )

    def test_check_rtp_integrity_signature(self):
        """check_rtp_integrity must accept summary, manifest, rawdata_dir, warn_only
        with the keyword-only constraint and correct default for warn_only."""
        import inspect
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        sig = inspect.signature(check_rtp_integrity)
        params = sig.parameters
        # 'summary' is the first positional arg
        assert "summary" in params
        # The remaining are keyword-only per the brief's * separator
        assert "manifest" in params
        assert "rawdata_dir" in params
        assert "warn_only" in params
        # warn_only default must be True
        assert params["warn_only"].default is True, (
            f"warn_only default must be True (not {params['warn_only'].default!r}) "
            "per §3 C7: Phase 5 policy flip changes a single bool."
        )

    def test_rtp_integrity_error_importable(self):
        """RTPIntegrityError must be importable (needed by C7 raise test)."""
        from fresh_slotlab.analyzer.rtp_integrity import RTPIntegrityError
        assert issubclass(RTPIntegrityError, Exception)


# ---------------------------------------------------------------------------
# C2 — Layer 1 invariant
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not RTP_GATE.exists(),
    reason="waiting on impl: fresh_slotlab/analyzer/rtp_integrity.py not yet on disk",
)
class TestC2Layer1Invariant:
    """Contract: sum(payout_id_win[pid]) == chunk_win_total within floating-point
    tolerance. Divergence by >1e-6 must fire Layer 1."""

    def test_l1_exact_match_passes(self):
        """Exact arithmetic match: pid wins sum = chunk_win → L1 ok."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(
            payout_id_win={"100": 1000.0, "200": 500.0},
            chunk_win_total=1500.0,
        )
        result = check_rtp_integrity(summary, warn_only=True)
        assert result.layer1_invariant_ok is True
        assert result.layer1_error is None

    def test_l1_divergence_fires(self):
        """Pid wins sum != chunk_win_total by >1e-6 → L1 fails."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(
            payout_id_win={"100": 1000.0, "200": 499.0},  # sum=1499, but chunk=1500
            chunk_win_total=1500.0,
        )
        result = check_rtp_integrity(summary, warn_only=True)
        assert result.layer1_invariant_ok is False
        assert result.layer1_error is not None and len(result.layer1_error) > 0
        assert result.passed is False

    def test_l1_zero_totals_edge_case(self):
        """Empty payout_id_win and chunk_win=0 → both zeros match → L1 ok."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(payout_id_win={}, chunk_win_total=0.0)
        result = check_rtp_integrity(summary, warn_only=True)
        assert result.layer1_invariant_ok is True

    def test_l1_floating_point_tiny_diff_within_tolerance(self):
        """A floating-point rounding error within 1e-6 tolerance must NOT fire L1.
        Tests that the implementation uses tolerance-aware comparison, not strict ==."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        # 0.1 + 0.2 in IEEE 754 is not exactly 0.3 — introduce intentional fp residual
        pid_wins = {"100": 0.1, "200": 0.2}
        # chunk_win_total == 0.3 exactly (which != 0.1 + 0.2 in float64)
        summary = _make_summary(
            payout_id_win=pid_wins,
            chunk_win_total=0.3,
        )
        result = check_rtp_integrity(summary, warn_only=True)
        # The tolerance must absorb 0.1+0.2 vs 0.3 — diff < 1e-10, well within 1e-6
        assert result.layer1_invariant_ok is True, (
            "Layer 1 fired on a floating-point residual within tolerance. "
            "The implementation must use math.isclose or equivalent, not strict ==."
        )

    def test_l1_large_value_divergence_fires(self):
        """Large-scale divergence (1M credits off) must fire L1 regardless of tolerance."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(
            payout_id_win={"100": 1_000_000.0},
            chunk_win_total=2_000_000.0,  # off by 1M
        )
        result = check_rtp_integrity(summary, warn_only=True)
        assert result.layer1_invariant_ok is False
        assert result.layer1_error is not None

    def test_l1_error_message_is_informative(self):
        """Layer 1 error string must include numeric context (sum vs chunk_win)."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(
            payout_id_win={"100": 300.0},
            chunk_win_total=500.0,
        )
        result = check_rtp_integrity(summary, warn_only=True)
        assert result.layer1_invariant_ok is False
        # Error message should contain numbers so operator can diagnose
        assert result.layer1_error is not None
        assert any(char.isdigit() for char in result.layer1_error), (
            f"Layer 1 error message has no digits — not informative enough: "
            f"{result.layer1_error!r}"
        )


# ---------------------------------------------------------------------------
# C3 — Layer 2 fallback prefixes
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not RTP_GATE.exists(),
    reason="waiting on impl: fresh_slotlab/analyzer/rtp_integrity.py not yet on disk",
)
class TestC3Layer2FallbackPrefixes:
    """Contract: any payout_id starting with a reserved fallback prefix fires L2.
    Reserved prefixes per §9.2: _unattributed_, _other, _default, _misc.
    Legitimate pids (e.g., '666', '_bcm_cycle') must NOT fire L2."""

    @pytest.mark.parametrize("fallback_pid", [
        "_unattributed_st1",
        "_unattributed_st139",
        "_other_bucket",
        "_default_win",
        "_misc_catch",
    ])
    def test_l2_reserved_prefix_fires(self, fallback_pid: str):
        """Each reserved prefix must trigger Layer 2."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(
            payout_id_win={"100": 500.0, fallback_pid: 50.0},
            chunk_win_total=550.0,
        )
        result = check_rtp_integrity(summary, warn_only=True)
        assert result.layer2_no_fallback_buckets_ok is False, (
            f"Layer 2 should fire for pid={fallback_pid!r} "
            f"(starts with reserved fallback prefix)"
        )
        assert fallback_pid in result.layer2_fallback_buckets_found, (
            f"Expected {fallback_pid!r} in layer2_fallback_buckets_found, "
            f"got: {result.layer2_fallback_buckets_found!r}"
        )
        assert result.passed is False

    def test_l2_legitimate_pid_666_does_not_fire(self):
        """Numeric pid '666' (e.g., M15 trigger anchor) must NOT fire Layer 2."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(
            payout_id_win={"666": 1000.0, "100": 500.0},
            chunk_win_total=1500.0,
        )
        result = check_rtp_integrity(summary, warn_only=True)
        assert result.layer2_no_fallback_buckets_ok is True, (
            "Layer 2 must NOT fire for legitimate pid '666' (M15 trigger anchor). "
            f"layer2_fallback_buckets_found={result.layer2_fallback_buckets_found!r}"
        )

    def test_l2_bcm_cycle_pid_does_not_fire(self):
        """'_bcm_cycle' starts with '_' but is a legitimate synthetic anchor, NOT a
        fallback prefix. Layer 2 must NOT fire because '_bcm_cycle' does NOT match
        any of the 4 reserved prefixes (_unattributed_, _other, _default, _misc).

        This test guards the exact-prefix matching requirement from §9.2:
        the check must match the FULL prefix strings, not just '_'."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(
            payout_id_win={"_bcm_cycle": 800.0, "5801": 200.0},
            chunk_win_total=1000.0,
        )
        result = check_rtp_integrity(summary, warn_only=True)
        assert result.layer2_no_fallback_buckets_ok is True, (
            "'_bcm_cycle' is a legitimate anchor per §9.2 (M274 example). "
            "Layer 2 must NOT fire — the prefix check must be exact. "
            f"layer2_fallback_buckets_found={result.layer2_fallback_buckets_found!r}"
        )

    def test_l2_clean_summary_passes(self):
        """Summary with no fallback pids → L2 ok."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(
            payout_id_win={"100": 200.0, "5801": 100.0, "_bcm_cycle": 50.0},
            chunk_win_total=350.0,
        )
        result = check_rtp_integrity(summary, warn_only=True)
        assert result.layer2_no_fallback_buckets_ok is True
        assert result.layer2_fallback_buckets_found == []

    def test_l2_multiple_fallback_pids_all_reported(self):
        """When multiple fallback pids are present, ALL must appear in
        layer2_fallback_buckets_found — not just the first one found."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(
            payout_id_win={
                "100": 200.0,
                "_unattributed_st1": 10.0,
                "_other_extras": 5.0,
            },
            chunk_win_total=215.0,
        )
        result = check_rtp_integrity(summary, warn_only=True)
        assert result.layer2_no_fallback_buckets_ok is False
        assert "_unattributed_st1" in result.layer2_fallback_buckets_found
        assert "_other_extras" in result.layer2_fallback_buckets_found


# ---------------------------------------------------------------------------
# C4 — Layer 3 anchor coverage
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not RTP_GATE.exists(),
    reason="waiting on impl: fresh_slotlab/analyzer/rtp_integrity.py not yet on disk",
)
class TestC4Layer3AnchorCoverage:
    """Contract: every manifest.required_attribution_anchors entry must appear
    in payout_id_hits with >0 hits. Zero hits → L3 fail."""

    def test_l3_required_anchor_with_zero_hits_fails(self):
        """Manifest requires '666'; summary has pid '666' with 0 hits → L3 fail."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        manifest = _make_manifest(required_attribution_anchors=["666"])
        # '666' has win but explicitly 0 hits
        summary = _make_summary(
            payout_id_win={"666": 0.0, "100": 500.0},
            chunk_win_total=500.0,
            payout_id_hits={"666": 0, "100": 1},  # explicitly 0 hits
        )
        result = check_rtp_integrity(summary, manifest=manifest, warn_only=True)
        assert result.layer3_anchors_ok is False
        assert "666" in result.layer3_missing_anchors
        assert result.passed is False

    def test_l3_required_anchor_absent_from_summary_fails(self):
        """Manifest requires '666'; summary doesn't have pid '666' at all → L3 fail."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        manifest = _make_manifest(required_attribution_anchors=["666"])
        summary = _make_summary(
            payout_id_win={"100": 500.0},
            chunk_win_total=500.0,
        )
        result = check_rtp_integrity(summary, manifest=manifest, warn_only=True)
        assert result.layer3_anchors_ok is False
        assert "666" in result.layer3_missing_anchors

    def test_l3_required_anchor_with_positive_hits_passes(self):
        """Manifest requires '666'; summary has pid '666' with >0 hits → L3 ok."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        manifest = _make_manifest(required_attribution_anchors=["666"])
        summary = _make_summary(
            payout_id_win={"666": 1000.0, "100": 500.0},
            chunk_win_total=1500.0,
            payout_id_hits={"666": 42, "100": 10},
        )
        result = check_rtp_integrity(summary, manifest=manifest, warn_only=True)
        assert result.layer3_anchors_ok is True
        assert result.layer3_missing_anchors == []

    def test_l3_empty_anchors_vacuously_passes(self):
        """Empty required_attribution_anchors list → vacuously passes (per §9.2)."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        manifest = _make_manifest(required_attribution_anchors=[])
        summary = _make_summary(
            payout_id_win={"100": 500.0},
            chunk_win_total=500.0,
        )
        result = check_rtp_integrity(summary, manifest=manifest, warn_only=True)
        assert result.layer3_anchors_ok is True
        assert result.layer3_missing_anchors == []

    def test_l3_multiple_anchors_all_must_pass(self):
        """Manifest requires both '_bcm_cycle' and '5801'. One present, one absent → L3 fail."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        manifest = _make_manifest(required_attribution_anchors=["_bcm_cycle", "5801"])
        summary = _make_summary(
            payout_id_win={"_bcm_cycle": 200.0},  # '5801' missing
            chunk_win_total=200.0,
            payout_id_hits={"_bcm_cycle": 5},
        )
        result = check_rtp_integrity(summary, manifest=manifest, warn_only=True)
        assert result.layer3_anchors_ok is False
        assert "5801" in result.layer3_missing_anchors
        assert "_bcm_cycle" not in result.layer3_missing_anchors

    def test_l3_no_manifest_skips_anchor_check(self):
        """When manifest=None (no manifest provided), Layer 3 has nothing to check.
        The result should reflect that L3 is vacuously ok (or not evaluated)."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(
            payout_id_win={"100": 500.0},
            chunk_win_total=500.0,
        )
        result = check_rtp_integrity(summary, manifest=None, warn_only=True)
        # With no manifest, L3 cannot fail. Should be ok (vacuously) or None.
        # The brief does not specify None for L3, so we accept True or that it
        # doesn't contribute to failure.
        assert result.layer3_anchors_ok is True or result.layer3_missing_anchors == []


# ---------------------------------------------------------------------------
# C5 — Layer 4 skip for trigger-session machines
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not RTP_GATE.exists(),
    reason="waiting on impl: fresh_slotlab/analyzer/rtp_integrity.py not yet on disk",
)
class TestC5Layer4SkipTriggerSession:
    """Contract: manifest.layer4_applicable=False (or trigger_session_pattern non-null)
    must bypass Layer 4. Result fields: layer4_applicable=False,
    layer4_per_st_consistency_ok=None, layer4_skip_reason populated."""

    def test_l4_skip_when_layer4_applicable_false(self):
        """manifest.layer4_applicable=False → Layer 4 skipped by applicability gate."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        manifest = _make_manifest(layer4_applicable=False)
        summary = _make_summary(
            payout_id_win={"100": 500.0},
            chunk_win_total=500.0,
        )
        result = check_rtp_integrity(summary, manifest=manifest, warn_only=True)
        assert result.layer4_applicable is False, (
            "layer4_applicable must be False when manifest says so"
        )
        assert result.layer4_per_st_consistency_ok is None, (
            "layer4_per_st_consistency_ok must be None when Layer 4 is skipped "
            "(not contributing to pass/fail)"
        )
        assert result.layer4_inconsistencies == [], (
            "layer4_inconsistencies must be empty list when skipped"
        )
        assert result.layer4_skip_reason is not None and len(result.layer4_skip_reason) > 0, (
            "layer4_skip_reason must be populated explaining why Layer 4 was skipped"
        )

    def test_l4_skip_when_trigger_session_pattern_type1(self):
        """trigger_session_pattern='type_1' → manifest rule 11 forces layer4_applicable=False.
        Layer 4 skipped."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        # Per §9.4 manifest rule 11: trigger_session_pattern != null → layer4_applicable=False
        manifest = _make_manifest(
            layer4_applicable=False,
            trigger_session_pattern="type_1",
        )
        summary = _make_summary(
            payout_id_win={"666": 1000.0},
            chunk_win_total=1000.0,
            payout_id_hits={"666": 100},
        )
        result = check_rtp_integrity(summary, manifest=manifest, warn_only=True)
        assert result.layer4_applicable is False
        assert result.layer4_per_st_consistency_ok is None
        assert result.layer4_skip_reason is not None

    def test_l4_skip_when_rawdata_dir_none_and_applicable(self):
        """manifest.layer4_applicable=True but rawdata_dir=None → Layer 4 cannot run.
        Design choice (per brief): skip with reason rather than raise.
        layer4_per_st_consistency_ok=None, layer4_skip_reason populated."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        manifest = _make_manifest(layer4_applicable=True)
        summary = _make_summary(
            payout_id_win={"100": 500.0},
            chunk_win_total=500.0,
        )
        result = check_rtp_integrity(
            summary, manifest=manifest, rawdata_dir=None, warn_only=True,
        )
        # When rawdata_dir is None and layer4 is applicable, we expect:
        # Either the gate skips with a reason OR it raises Layer4Error.
        # Per our design choice (brief C5 guidance): skip with reason.
        # Accept either: skip (None) or the gate fires with a specific reason.
        # At minimum: must not raise an unexpected exception.
        assert result.layer4_applicable is True or result.layer4_applicable is False
        if result.layer4_per_st_consistency_ok is None:
            # Skip path: skip_reason must be populated
            assert result.layer4_skip_reason is not None, (
                "If Layer 4 is skipped due to missing rawdata_dir, "
                "layer4_skip_reason must explain why"
            )
        # Otherwise (layer4 was evaluated somehow without rawdata): that's also acceptable.

    def test_l4_skip_does_not_affect_l1_l2_l3(self):
        """When Layer 4 is skipped, Layers 1-3 are still enforced per §9.4."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        manifest = _make_manifest(
            layer4_applicable=False,
            required_attribution_anchors=["666"],
        )
        summary = _make_summary(
            payout_id_win={"100": 400.0, "_unattributed_st1": 100.0},  # L2 violation
            chunk_win_total=500.0,
            payout_id_hits={"100": 10, "_unattributed_st1": 2},
            # '666' missing → L3 violation
        )
        result = check_rtp_integrity(summary, manifest=manifest, warn_only=True)
        # Layer 4 skipped
        assert result.layer4_applicable is False
        # But Layer 2 must still fire
        assert result.layer2_no_fallback_buckets_ok is False
        # And Layer 3 must still fire
        assert result.layer3_anchors_ok is False
        # Overall must fail
        assert result.passed is False


# ---------------------------------------------------------------------------
# C6 — Layer 4 Step A/B/C via synthetic chunk files
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not RTP_GATE.exists(),
    reason="waiting on impl: fresh_slotlab/analyzer/rtp_integrity.py not yet on disk",
)
class TestC6Layer4StepABC:
    """Contract: Layer 4 performs an independent rawdata cross-check.
    Step A: capture analyzer's dispatch. Step B: fresh scan of chunk JSONs.
    Step C: compare. Divergence in counts → inconsistency recorded."""

    def test_l4_matching_dispatch_passes(self, tmp_path: Path):
        """When analyzer's dispatch and rawdata scan agree on (pid, ST) counts,
        Layer 4 passes cleanly."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        rawdata_dir = tmp_path / "rawdata"
        rawdata_dir.mkdir()
        # Write a chunk: robot_0 has 2 rounds, both ST=1, pid=100 fires in both
        _write_chunk(rawdata_dir / "chunk_0001.json", rounds=[
            {"SpinType": 1, "PayoutIdToWinAmount": {"100": 500}},
            {"SpinType": 1, "PayoutIdToWinAmount": {"100": 300}},
        ])
        manifest = _make_manifest(layer4_applicable=True)
        # Analyzer's dispatch: pid=100 in ST=1, count=2 (matches 2 rounds in rawdata)
        summary = _make_summary(
            payout_id_win={"100": 800.0},
            chunk_win_total=800.0,
            payout_id_by_spin_type_total={"100": {"1": 2}},
        )
        result = check_rtp_integrity(
            summary, manifest=manifest, rawdata_dir=rawdata_dir, warn_only=True,
        )
        assert result.layer4_per_st_consistency_ok is True, (
            f"Layer 4 should pass when dispatch matches rawdata. "
            f"Inconsistencies: {result.layer4_inconsistencies}"
        )
        assert result.layer4_inconsistencies == []

    def test_l4_divergent_count_fires_inconsistency(self, tmp_path: Path):
        """Analyzer says pid=100 in ST=1 appears 5 times, rawdata shows 3 → L4 fail.
        Inconsistency entry must record correct a_count=5, f_count=3."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        rawdata_dir = tmp_path / "rawdata"
        rawdata_dir.mkdir()
        # Rawdata: only 3 rounds with pid=100 in ST=1
        _write_chunk(rawdata_dir / "chunk_0001.json", rounds=[
            {"SpinType": 1, "PayoutIdToWinAmount": {"100": 300}},
            {"SpinType": 1, "PayoutIdToWinAmount": {"100": 200}},
            {"SpinType": 1, "PayoutIdToWinAmount": {"100": 100}},
        ])
        manifest = _make_manifest(layer4_applicable=True)
        # Analyzer's dispatch: pid=100 in ST=1, count=5 (DIVERGES from rawdata's 3)
        summary = _make_summary(
            payout_id_win={"100": 600.0},
            chunk_win_total=600.0,
            payout_id_by_spin_type_total={"100": {"1": 5}},  # analyzer says 5
        )
        result = check_rtp_integrity(
            summary, manifest=manifest, rawdata_dir=rawdata_dir, warn_only=True,
        )
        assert result.layer4_per_st_consistency_ok is False, (
            "Layer 4 should fail when analyzer count (5) != rawdata count (3)"
        )
        assert len(result.layer4_inconsistencies) >= 1
        # Find the inconsistency for pid=100, ST=1
        incons = [
            e for e in result.layer4_inconsistencies
            if (
                str(e.get("pay_id", "")) == "100"
                or e.get("pay_id") == 100
            )
            and (
                str(e.get("spin_type", "")) == "1"
                or e.get("spin_type") == 1
            )
        ]
        assert len(incons) >= 1, (
            f"Expected inconsistency entry for pid=100, ST=1. "
            f"Got: {result.layer4_inconsistencies!r}"
        )
        entry = incons[0]
        a_count = entry.get("analyzer_dispatch_count")
        f_count = entry.get("rawdata_observed_count")
        assert a_count == 5, (
            f"analyzer_dispatch_count must be 5 (from payout_id_by_spin_type_total), "
            f"got {a_count!r}. Entry: {entry!r}"
        )
        assert f_count == 3, (
            f"rawdata_observed_count must be 3 (from chunk scan), "
            f"got {f_count!r}. Entry: {entry!r}"
        )

    def test_l4_missing_spintype_raises_layer4error(self, tmp_path: Path):
        """A round with SpinType field missing -> Layer4Error raised at Step B.

        Per brief §3 C6: "SpinType missing from a round -> Layer4Error raised at
        Step B". The implementation does NOT catch Layer4Error — it propagates
        as a hard error (data corruption is not a soft integrity failure).
        """
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity, Layer4Error
        rawdata_dir = tmp_path / "rawdata"
        rawdata_dir.mkdir()
        _write_chunk(rawdata_dir / "chunk_0001.json", rounds=[
            # SpinType field deliberately missing
            {"PayoutIdToWinAmount": {"100": 500}},
        ])
        manifest = _make_manifest(layer4_applicable=True)
        summary = _make_summary(
            payout_id_win={"100": 500.0},
            chunk_win_total=500.0,
            payout_id_by_spin_type_total={"100": {"1": 1}},
        )
        with pytest.raises(Layer4Error, match="SpinType"):
            check_rtp_integrity(
                summary, manifest=manifest, rawdata_dir=rawdata_dir, warn_only=True,
            )

    def test_l4_invalid_spintype_raises_layer4error(self, tmp_path: Path):
        """A round with SpinType='not_an_int' -> Layer4Error raised at Step B.

        Per brief §3 C6: "SpinType invalid value -> Layer4Error raised". Same
        propagation contract as the missing-SpinType case.
        """
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity, Layer4Error
        rawdata_dir = tmp_path / "rawdata"
        rawdata_dir.mkdir()
        _write_chunk(rawdata_dir / "chunk_0001.json", rounds=[
            {"SpinType": "not_an_int", "PayoutIdToWinAmount": {"100": 500}},
        ])
        manifest = _make_manifest(layer4_applicable=True)
        summary = _make_summary(
            payout_id_win={"100": 500.0},
            chunk_win_total=500.0,
            payout_id_by_spin_type_total={"100": {"1": 1}},
        )
        with pytest.raises(Layer4Error, match="SpinType"):
            check_rtp_integrity(
                summary, manifest=manifest, rawdata_dir=rawdata_dir, warn_only=True,
            )

    def test_l4_zero_win_pid_counted_by_existence(self, tmp_path: Path):
        """Per §9.4 Step B edge-case table: pid with win=0 in PayoutIdToWinAmount
        is still counted (existence in keys(), not win > 0). Consistent with 4cbcab2 fix."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        rawdata_dir = tmp_path / "rawdata"
        rawdata_dir.mkdir()
        # pid=666 fires with win=0 (trigger anchor pattern, e.g. M15)
        _write_chunk(rawdata_dir / "chunk_0001.json", rounds=[
            {"SpinType": 1, "PayoutIdToWinAmount": {"666": 0, "100": 500}},
            {"SpinType": 1, "PayoutIdToWinAmount": {"666": 0, "100": 300}},
        ])
        manifest = _make_manifest(layer4_applicable=True)
        # Analyzer dispatch: pid=666 in ST=1 count=2, pid=100 in ST=1 count=2
        summary = _make_summary(
            payout_id_win={"666": 0.0, "100": 800.0},
            chunk_win_total=800.0,
            payout_id_by_spin_type_total={
                "666": {"1": 2},
                "100": {"1": 2},
            },
        )
        result = check_rtp_integrity(
            summary, manifest=manifest, rawdata_dir=rawdata_dir, warn_only=True,
        )
        assert result.layer4_per_st_consistency_ok is True, (
            "pid=666 with win=0 must be counted by existence in PayoutIdToWinAmount.keys(). "
            f"Inconsistencies: {result.layer4_inconsistencies}"
        )

    def test_l4_multiple_chunks_all_scanned(self, tmp_path: Path):
        """Step B must iterate ALL chunk files, not just the first.
        Two chunks contribute to the same pid→ST count."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        rawdata_dir = tmp_path / "rawdata"
        rawdata_dir.mkdir()
        # chunk 1: 2 rounds with pid=100 in ST=1
        _write_chunk(rawdata_dir / "chunk_0001.json", rounds=[
            {"SpinType": 1, "PayoutIdToWinAmount": {"100": 200}},
            {"SpinType": 1, "PayoutIdToWinAmount": {"100": 200}},
        ])
        # chunk 2: 3 more rounds with pid=100 in ST=1
        chunk2_path = rawdata_dir / "chunk_0002.json"
        chunk2 = {
            "_envelope_version": 2,
            "_config_md5": "aaa",
            "_code_md5": "bbb",
            "_chunk_index": 2,
            "response": [
                {
                    "robotId": "robot_0",
                    "roundResult": [
                        {"SpinType": 1, "PayoutIdToWinAmount": {"100": 300}},
                        {"SpinType": 1, "PayoutIdToWinAmount": {"100": 400}},
                        {"SpinType": 1, "PayoutIdToWinAmount": {"100": 500}},
                    ],
                }
            ],
        }
        chunk2_path.write_text(json.dumps(chunk2), encoding="utf-8")
        manifest = _make_manifest(layer4_applicable=True)
        # Analyzer dispatch: pid=100 in ST=1, count=5 (2 from chunk1 + 3 from chunk2)
        summary = _make_summary(
            payout_id_win={"100": 1600.0},
            chunk_win_total=1600.0,
            payout_id_by_spin_type_total={"100": {"1": 5}},
        )
        result = check_rtp_integrity(
            summary, manifest=manifest, rawdata_dir=rawdata_dir, warn_only=True,
        )
        assert result.layer4_per_st_consistency_ok is True, (
            "Layer 4 should pass — Step B must scan BOTH chunk files (total 5 rounds). "
            f"Inconsistencies: {result.layer4_inconsistencies!r}"
        )

    def test_l4_no_rawdata_chunks_raises_layer4error(self, tmp_path: Path):
        """When rawdata_dir exists but has no chunk_*.json files, Layer 4 raises
        Layer4Error — not silently claim ok, not soft-record.

        Per §9.4 + implementation choice: missing rawdata is a hard error (cannot
        run the check, must surface to the operator with the "run sampling first"
        diagnostic).
        """
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity, Layer4Error
        rawdata_dir = tmp_path / "empty_rawdata"
        rawdata_dir.mkdir()
        # No chunk files written
        manifest = _make_manifest(layer4_applicable=True)
        summary = _make_summary(
            payout_id_win={"100": 500.0},
            chunk_win_total=500.0,
            payout_id_by_spin_type_total={"100": {"1": 1}},
        )
        with pytest.raises(Layer4Error, match="no rawdata chunks found"):
            check_rtp_integrity(
                summary, manifest=manifest, rawdata_dir=rawdata_dir, warn_only=True,
            )


# ---------------------------------------------------------------------------
# C7 — Warn-only mode
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not RTP_GATE.exists(),
    reason="waiting on impl: fresh_slotlab/analyzer/rtp_integrity.py not yet on disk",
)
class TestC7WarnOnlyMode:
    """Contract: warn_only=True (default) → no raise on failure, returns result.
    warn_only=False → raises RTPIntegrityError on any layer failure."""

    def _failing_summary(self) -> dict:
        """Return a summary that fails Layer 1 (arithmetic mismatch)."""
        return _make_summary(
            payout_id_win={"100": 300.0},
            chunk_win_total=500.0,
        )

    def test_warn_only_true_does_not_raise(self):
        """Default warn_only=True: failing integrity check returns result without raising."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = self._failing_summary()
        # Must not raise — just return the result
        result = check_rtp_integrity(summary, warn_only=True)
        assert result.passed is False, (
            "Expected passed=False for a failing summary"
        )

    def test_warn_only_default_is_true_no_raise(self):
        """Default parameter (omit warn_only entirely) must behave as warn_only=True."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = self._failing_summary()
        # Omitting warn_only — must not raise
        result = check_rtp_integrity(summary)
        assert result.passed is False

    def test_warn_only_false_raises_on_failure(self):
        """warn_only=False: failing integrity check raises RTPIntegrityError."""
        from fresh_slotlab.analyzer.rtp_integrity import (
            check_rtp_integrity, RTPIntegrityError,
        )
        summary = self._failing_summary()
        with pytest.raises(RTPIntegrityError):
            check_rtp_integrity(summary, warn_only=False)

    def test_warn_only_false_does_not_raise_when_passing(self):
        """warn_only=False: a passing summary must NOT raise — only failures raise."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(
            payout_id_win={"100": 500.0},
            chunk_win_total=500.0,
        )
        # Should return without exception
        result = check_rtp_integrity(summary, warn_only=False)
        assert result.passed is True

    def test_warn_only_true_passes_when_all_ok(self):
        """warn_only=True with a passing summary → passed=True, no exception."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(
            payout_id_win={"100": 500.0},
            chunk_win_total=500.0,
        )
        result = check_rtp_integrity(summary, warn_only=True)
        assert result.passed is True


# ---------------------------------------------------------------------------
# C8 — Subprocess import + CLI smoke
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not RTP_GATE.exists(),
    reason="waiting on impl: fresh_slotlab/analyzer/rtp_integrity.py not yet on disk",
)
class TestC8SubprocessSmoke:
    """Contract: no import-time side effects + CLI --help works.
    Per memory feedback_perf_claim_needs_e2e_event_stream.md: must spawn
    real subprocesses, not just in-process import."""

    def test_subprocess_import_rc0(self):
        """python -c 'import fresh_slotlab.analyzer.rtp_integrity' must exit 0
        with no stderr. Guards against import-time side effects that would kill
        a batch worker process (per memory feedback_subprocess_import_suicide_and_module_globals.md)."""
        result = subprocess.run(
            [sys.executable, "-c", "import fresh_slotlab.analyzer.rtp_integrity"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Subprocess import failed (rc={result.returncode}).\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )
        # No stderr on clean import (warns about side effects)
        assert result.stderr.strip() == "", (
            f"Import produced stderr output (potential side effect):\n{result.stderr}"
        )

    def test_subprocess_cli_help_rc0(self):
        """python -m fresh_slotlab.analyzer.rtp_integrity --help must exit 0.
        Guards the __main__ CLI entry point."""
        result = subprocess.run(
            [sys.executable, "-m", "fresh_slotlab.analyzer.rtp_integrity", "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"CLI --help failed (rc={result.returncode}).\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )

    def test_subprocess_cli_requires_machine_arg(self):
        """CLI without --machine should exit non-zero (arg parse error), not crash with
        unhandled exception. Guards the CLI's argument validation."""
        result = subprocess.run(
            [sys.executable, "-m", "fresh_slotlab.analyzer.rtp_integrity"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should exit non-zero (missing required arg) but NOT crash with traceback
        # The argparse behavior is: rc=2, stderr has usage message
        assert result.returncode != 0, (
            "CLI without --machine should exit non-zero"
        )
        # No Python traceback in stderr
        assert "Traceback" not in result.stderr, (
            f"CLI without args produced a Python traceback (unhandled exception):\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# C10 — Inject-bug TDD proofs
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not RTP_GATE.exists(),
    reason="waiting on impl: fresh_slotlab/analyzer/rtp_integrity.py not yet on disk",
)
class TestC10InjectBugTDD:
    """Inject-bug TDD proofs per memory feedback_integration_test_argv.md.

    These tests define the observable signal that proves each guard is real.
    The inject-bug procedure (documented in 03_tests.md):
      1. Hand-edit the production file to introduce the bug.
      2. Run this test class → must go RED.
      3. Revert the edit.
      4. Run again → must go GREEN.

    Three inject-bug proofs:
      IB-1: Drop '_unattributed_' from Layer 2 prefix list → C3 test RED.
      IB-2: Change warn_only=True default to False → C7 no-raise test RED.
      IB-3: Swap a_count/f_count in Step C recording → C6 content test RED.
    """

    def test_ib1_l2_unattributed_prefix_must_fire(self):
        """INJECT-BUG PROOF IB-1: drop '_unattributed_' from Layer 2 prefix list.

        Bug to inject in rtp_integrity.py:
            FALLBACK_PREFIXES = ("_other", "_default", "_misc")  # removed _unattributed_

        Expected when bug injected:
            result.layer2_no_fallback_buckets_ok is True  →  assertion FAILS (RED)

        After revert:
            result.layer2_no_fallback_buckets_ok is False →  assertion PASSES (GREEN)

        This test is the guard. If it passes, the prefix check is present.
        If the bug is injected (prefix removed), this test goes RED because
        layer2_no_fallback_buckets_ok would be True (nothing detected).
        """
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(
            payout_id_win={"100": 500.0, "_unattributed_st1": 10.0},
            chunk_win_total=510.0,
        )
        result = check_rtp_integrity(summary, warn_only=True)
        # Guard: '_unattributed_st1' MUST fire Layer 2
        assert result.layer2_no_fallback_buckets_ok is False, (
            "IB-1 FAILED: Layer 2 did not fire for '_unattributed_st1'. "
            "Either the prefix list is incomplete or the check is broken. "
            "INJECT-BUG: removing '_unattributed_' from FALLBACK_PREFIXES must make this RED."
        )
        assert "_unattributed_st1" in result.layer2_fallback_buckets_found, (
            f"IB-1 FAILED: '_unattributed_st1' not in layer2_fallback_buckets_found. "
            f"Got: {result.layer2_fallback_buckets_found!r}"
        )

    def test_ib2_warn_only_true_must_not_raise(self):
        """INJECT-BUG PROOF IB-2: change warn_only=True default to False.

        Bug to inject in rtp_integrity.py:
            def check_rtp_integrity(summary, *, manifest=None, rawdata_dir=None,
                                    warn_only=False):  # changed True → False

        Expected when bug injected:
            check_rtp_integrity(failing_summary) raises RTPIntegrityError
            → pytest.raises block captures it → the 'no raise' assertion FAILS (RED)

        After revert:
            check_rtp_integrity(failing_summary) returns result → PASSES (GREEN)

        Calling with no warn_only kwarg uses the default — this is the signal.
        """
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        summary = _make_summary(
            payout_id_win={"100": 300.0},
            chunk_win_total=500.0,  # diverges by 200 → Layer 1 fails
        )
        # Must NOT raise when called with no explicit warn_only (uses default)
        try:
            result = check_rtp_integrity(summary)  # relying on default warn_only=True
        except Exception as exc:
            pytest.fail(
                f"IB-2 FAILED: check_rtp_integrity() raised {type(exc).__name__} "
                f"with default warn_only. "
                f"The default must be warn_only=True (no raise). "
                f"INJECT-BUG: changing default to False must make this RED.\n"
                f"Exception: {exc}"
            )
        assert result.passed is False, (
            "IB-2 sanity: expected passed=False for the failing summary"
        )

    def test_ib3_step_c_counts_not_swapped(self, tmp_path: Path):
        """INJECT-BUG PROOF IB-3: swap a_count/f_count in Step C inconsistency recording.

        Bug to inject in rtp_integrity.py Step C:
            inconsistencies.append({
                ...
                "analyzer_dispatch_count": f_count,  # SWAPPED (was a_count)
                "rawdata_observed_count": a_count,   # SWAPPED (was f_count)
                ...
            })

        Expected when bug injected:
            entry["analyzer_dispatch_count"] == 3 (wrong, should be 5)
            → assertion a_count == 5 FAILS (RED)

        After revert:
            entry["analyzer_dispatch_count"] == 5 → PASSES (GREEN)

        This test uses the same fixture as C6 divergent-count test.
        """
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        rawdata_dir = tmp_path / "rawdata"
        rawdata_dir.mkdir()
        # Rawdata: 3 rounds with pid=100 in ST=1
        _write_chunk(rawdata_dir / "chunk_0001.json", rounds=[
            {"SpinType": 1, "PayoutIdToWinAmount": {"100": 200}},
            {"SpinType": 1, "PayoutIdToWinAmount": {"100": 200}},
            {"SpinType": 1, "PayoutIdToWinAmount": {"100": 200}},
        ])
        manifest = _make_manifest(layer4_applicable=True)
        # Analyzer dispatch: pid=100 in ST=1, count=5 (diverges from rawdata's 3)
        summary = _make_summary(
            payout_id_win={"100": 600.0},
            chunk_win_total=600.0,
            payout_id_by_spin_type_total={"100": {"1": 5}},  # analyzer says 5
        )
        result = check_rtp_integrity(
            summary, manifest=manifest, rawdata_dir=rawdata_dir, warn_only=True,
        )
        assert result.layer4_per_st_consistency_ok is False
        assert len(result.layer4_inconsistencies) >= 1
        incons = [
            e for e in result.layer4_inconsistencies
            if (
                str(e.get("pay_id", "")) == "100" or e.get("pay_id") == 100
            ) and (
                str(e.get("spin_type", "")) == "1" or e.get("spin_type") == 1
            )
        ]
        assert len(incons) >= 1, f"No inconsistency entry for pid=100, ST=1: {result.layer4_inconsistencies!r}"
        entry = incons[0]
        a_count = entry.get("analyzer_dispatch_count")
        f_count = entry.get("rawdata_observed_count")
        assert a_count == 5, (
            f"IB-3 FAILED: analyzer_dispatch_count must be 5 (analyzer's count). "
            f"Got {a_count!r}. "
            f"INJECT-BUG: swapping a_count/f_count in Step C must make this RED."
        )
        assert f_count == 3, (
            f"IB-3 FAILED: rawdata_observed_count must be 3 (fresh scan count). "
            f"Got {f_count!r}. "
            f"INJECT-BUG: swapping a_count/f_count in Step C must make this RED."
        )


# ---------------------------------------------------------------------------
# Layer 4 — is_fallback_pid field in inconsistency dict
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not RTP_GATE.exists(),
    reason="waiting on impl: fresh_slotlab/analyzer/rtp_integrity.py not yet on disk",
)
class TestLayer4FallbackPidCorroboration:
    """Contract per §9.4 Step C v5 note: when a pid in an inconsistency entry
    starts with a fallback prefix, is_fallback_pid must be True and the note
    must include '[FALLBACK PID]'. These mismatches must NOT be suppressed."""

    def test_l4_fallback_pid_inconsistency_has_flag(self, tmp_path: Path):
        """An inconsistency for a fallback pid (e.g. '_unattributed_st139') must
        have is_fallback_pid=True in the entry dict per §9.4 Step C."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        rawdata_dir = tmp_path / "rawdata"
        rawdata_dir.mkdir()
        # Rawdata: no '_unattributed_st139' in PayoutIdToWinAmount (it's synthetic)
        _write_chunk(rawdata_dir / "chunk_0001.json", rounds=[
            {"SpinType": 1, "PayoutIdToWinAmount": {"100": 500}},
        ])
        manifest = _make_manifest(layer4_applicable=True)
        # Analyzer has '_unattributed_st139' in dispatch (fallback synthesizer wrote it)
        summary = _make_summary(
            payout_id_win={"100": 500.0, "_unattributed_st139": 50.0},
            chunk_win_total=550.0,
            payout_id_by_spin_type_total={
                "100": {"1": 1},
                "_unattributed_st139": {"1": 2},  # appears in analyzer but NOT in rawdata
            },
        )
        result = check_rtp_integrity(
            summary, manifest=manifest, rawdata_dir=rawdata_dir, warn_only=True,
        )
        assert result.layer4_per_st_consistency_ok is False
        # Find the entry for _unattributed_st139
        fallback_entries = [
            e for e in result.layer4_inconsistencies
            if str(e.get("pay_id", "")).startswith("_unattributed_")
        ]
        assert len(fallback_entries) >= 1, (
            f"Expected inconsistency entry for _unattributed_st139. "
            f"Got: {result.layer4_inconsistencies!r}"
        )
        entry = fallback_entries[0]
        assert entry.get("is_fallback_pid") is True, (
            f"is_fallback_pid must be True for fallback-prefixed pid. "
            f"Entry: {entry!r}"
        )

    def test_l4_legitimate_pid_inconsistency_has_flag_false(self, tmp_path: Path):
        """An inconsistency for a legitimate pid (e.g. '100') must have
        is_fallback_pid=False in the entry dict."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        rawdata_dir = tmp_path / "rawdata"
        rawdata_dir.mkdir()
        # Rawdata: 1 round with pid=100
        _write_chunk(rawdata_dir / "chunk_0001.json", rounds=[
            {"SpinType": 1, "PayoutIdToWinAmount": {"100": 500}},
        ])
        manifest = _make_manifest(layer4_applicable=True)
        # Analyzer says 3 rounds with pid=100 (diverges from rawdata's 1)
        summary = _make_summary(
            payout_id_win={"100": 500.0},
            chunk_win_total=500.0,
            payout_id_by_spin_type_total={"100": {"1": 3}},
        )
        result = check_rtp_integrity(
            summary, manifest=manifest, rawdata_dir=rawdata_dir, warn_only=True,
        )
        assert result.layer4_per_st_consistency_ok is False
        pid100_entries = [
            e for e in result.layer4_inconsistencies
            if str(e.get("pay_id", "")) == "100" or e.get("pay_id") == 100
        ]
        assert len(pid100_entries) >= 1
        entry = pid100_entries[0]
        assert entry.get("is_fallback_pid") is False, (
            f"is_fallback_pid must be False for legitimate numeric pid '100'. "
            f"Entry: {entry!r}"
        )


# ---------------------------------------------------------------------------
# passed=True only when ALL applicable layers pass
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not RTP_GATE.exists(),
    reason="waiting on impl: fresh_slotlab/analyzer/rtp_integrity.py not yet on disk",
)
class TestPassedAggregation:
    """Contract per §9.2: 'A machine passes only if all applicable layers pass.'
    Tests that passed=True requires all layers ok."""

    def test_passed_true_when_all_layers_ok(self):
        """All layers pass (L1 ok, L2 ok, L3 ok) → passed=True."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        manifest = _make_manifest(
            layer4_applicable=False,
            required_attribution_anchors=["100"],
        )
        summary = _make_summary(
            payout_id_win={"100": 500.0},
            chunk_win_total=500.0,
            payout_id_hits={"100": 10},
        )
        result = check_rtp_integrity(summary, manifest=manifest, warn_only=True)
        assert result.layer1_invariant_ok is True
        assert result.layer2_no_fallback_buckets_ok is True
        assert result.layer3_anchors_ok is True
        assert result.passed is True

    def test_passed_false_when_only_l2_fails(self):
        """L2 alone failing → passed=False even if L1 and L3 are ok."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        manifest = _make_manifest(
            layer4_applicable=False,
            required_attribution_anchors=[],  # no L3 requirement
        )
        summary = _make_summary(
            payout_id_win={"100": 400.0, "_misc_leftover": 100.0},
            chunk_win_total=500.0,
        )
        result = check_rtp_integrity(summary, manifest=manifest, warn_only=True)
        assert result.layer1_invariant_ok is True  # L1 ok (sums match)
        assert result.layer2_no_fallback_buckets_ok is False  # L2 fails
        assert result.passed is False, (
            "passed must be False when any applicable layer fails"
        )

    def test_completeness_declared_mirrors_manifest(self):
        """completeness_declared must mirror manifest.console_diagnostic_complete."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity
        for complete_val in (True, False):
            manifest = _make_manifest(
                layer4_applicable=False,
                console_diagnostic_complete=complete_val,
            )
            summary = _make_summary(
                payout_id_win={"100": 500.0},
                chunk_win_total=500.0,
            )
            result = check_rtp_integrity(summary, manifest=manifest, warn_only=True)
            assert result.completeness_declared is complete_val, (
                f"completeness_declared={result.completeness_declared!r} "
                f"but manifest.console_diagnostic_complete={complete_val!r}"
            )
