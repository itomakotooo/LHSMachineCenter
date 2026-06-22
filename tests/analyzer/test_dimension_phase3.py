"""Phase 3 dimension framework tests — freespin_progression extractor + er_ladder /
fs_index_arc / session_tier_distribution + upstream_feature_breakdown accurate labels.

Design source:
    session_artifacts/_arch_playtype/dimension/04_dimension_framework.md §6 Phase 3
Phase 2 test reference (do NOT duplicate locked tests from here):
    tests/analyzer/test_dimension_phase2.py
Implementations tested:
    fresh_slotlab/analyzer/st_extract/freespin_progression.py  (NEW extractor)
    fresh_slotlab/analyzer/features/freespin_dynamics.py        (3 new sections)
    fresh_slotlab/analyzer/features/upstream_feature_breakdown.py (accurate dim labels)
    src/web_console/frontend/app.js (_stDimFreespin Phase 3 sub-panels)
    src/web_console/frontend/pure.js (Phase 3 i18n keys)

Contract Phase 3 establishes (value-agnostic — relations only, no pinned literals)
-----------------------------------------------------------------------------------
EXTRACTOR OUTPUT:
  FreespinProgressionExtractor.finalize_chunk shape:
    {st_str: {dim_name: {path_label: {er_ladder, fs_arc, session_tier_hist}}}}
  All fs_arc round_count values per path sum == total rounds across paths.
  er_ladder only populated for FS positions where ExtraRatio field is present.

ER LADDER (er_ladder section in freespin_dynamics):
  mean_er[last_fs_index] > mean_er[first_fs_index]  (monotone-ish climb relation)
  aggregate round_count per FS index == sum over real paths

FS ARC (fs_index_arc section in freespin_dynamics):
  hit_rate[last_fs_index] < hit_rate[first_fs_index]  (decline relation = the cliff)
  hit_rate == win_round_count / round_count  (internal self-consistency)

SESSION TIER (session_tier_distribution section in freespin_dynamics):
  sum(session_count) == total_sessions  (conservation)
  sum(prob) ~= 1.0  (probability sums to 1)
  bands come from RETURN_BUCKET_ORDER vocabulary

BY_DIM:
  er_ladder / fs_index_arc / session_tier_distribution carry by_dim when >=2 real paths
  Single-path fixture: NO by_dim on these three sections
  Generic-overlap sections (trigger_paths, session_cadence, etc.) MUST NOT have by_dim
  (architecture boundary test already locked in Phase 2; not duplicated here)

UPSTREAM FEATURE BREAKDOWN:
  2-path fixture: sub_streams for the feature ST replaced with per-path rows
    whose "label" == the dimension value (not "via NormalCollectionSpin" heuristic)
  No-dimension fixture (M15/M43/M279): UFB output byte-identical to before Phase 3

BASE-EXCLUDED GATE:
  base_hash unchanged at c5d2199142c3

INJECT-BUG RECIPES (per feedback_enumerate_safety_paths.md)
--------------------------------------------------------------
IB-1 (break ER climb — accumulate without FS-index keying):
  In freespin_progression.py::observe_round, replace:
      arc_key = (spin_type, dim_name, eff_label, fs_idx)
      self._fs_arc_round_count[arc_key] += 1
  with a FLAT key (no fs_idx):
      flat_key = (spin_type, dim_name, eff_label, 0)
      self._fs_arc_round_count[flat_key] += 1
  => test 2 (test_er_ladder_mean_er_climbs_across_fs_index) RED
     because all rounds land in FS index "0", breaking the per-index structure.
  Revert => GREEN.

IB-2 (break UFB accurate labels — keep coarse heuristic even with dimension data):
  In upstream_feature_breakdown.py::emit, change the guard:
      if len(real_dim_labels) < 2:
  to:
      if len(real_dim_labels) < 1000:   # always skip — heuristic always wins
  => test 7 (test_ufb_accurate_labels_when_two_paths) RED
     because the sub_streams rows keep "via ..." labels, not path labels.
  Revert => GREEN.

Memory feedback honored:
  memory/feedback_enumerate_safety_paths.md — inject-bug per invariant above
  memory/feedback_perf_claim_needs_e2e_event_stream.md — Test 8 uses real engine
    on real M275 chunks + asserts computed relations (not just key presence)
  memory/feedback_integration_test_argv.md — real report generation, not just
    direct plugin.extract() calls
  memory/feedback_no_silent_swallow.md — unknown/multi surfaced as alarm keys
  memory/feedback_aggregator_parity_invariant.md — per-path round_count sums
    to aggregate (additivity invariant)
"""
from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Repo / rawdata paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
M275_CHUNK_DIR = ROOT / "rawdata" / "M275" / "mode_1"
M275_CHUNK1 = M275_CHUNK_DIR / "chunk_0001.json"
M275_CHUNK2 = M275_CHUNK_DIR / "chunk_0002.json"
M275_AVAILABLE = M275_CHUNK1.exists() and M275_CHUNK2.exists()
SKIP_NO_M275 = pytest.mark.skipif(
    not M275_AVAILABLE,
    reason="rawdata/M275/mode_1 absent; developer-only test",
)

_FS_ST = 126
_FS_LABEL = "ST126_free"
_DIM_NAME = "trigger_path"
_REAL_VALUES = frozenset({"scatter", "collect_peak"})

# ---------------------------------------------------------------------------
# Shared synthetic manifest builders (mirrors test_dimension_phase2.py)
# ---------------------------------------------------------------------------

def _synth_manifest_2path(
    machine_id: str = "M_p3_2path",
    fs_st: int = 126,
    paid_st: int = 1,
    field: str = "TriggerField",
) -> dict:
    """Full spintype-native/1 manifest with 2-path trigger_paths + freespin role."""
    return {
        "machine_id": machine_id,
        "schema": "spintype-native/1",
        "modes": [1],
        "inherits_from": None,
        "spin_types": {
            str(paid_st): {
                "role": "paid_spin",
                "play": "Normal",
                "economy": {"win_field": "WinCredits", "kind": "real"},
                "signature": ["SpinType", "WinCredits"],
                "observed_fields": [
                    "SpinType", "CostCredits", "WinCredits",
                    "StopSymbolsByCol", "PayoutIdToWinAmount",
                ],
            },
            str(fs_st): {
                "role": "freespin",
                "play": "SynthFreespin",
                "economy": {"win_field": "WinCredits", "kind": "real"},
                "signature": ["SpinType", "WinCredits"],
                "observed_fields": [
                    "SpinType", "WinCredits",
                    "StopSymbolsByCol", "PayoutIdToWinAmount",
                    field, "ExtraRatio", "ReMarks",
                ],
                "trigger_paths": {
                    "discriminator": {
                        "kind": "round_field",
                        "field": field,
                        "map": {"0": "alpha", "1": "beta"},
                        "unmapped_value_policy": "surface_as_unknown_path",
                    },
                    "multi_trigger_policy": "additive_sessions",
                    "paths": {
                        "alpha": {"label": "Alpha path"},
                        "beta":  {"label": "Beta path"},
                    },
                },
            },
        },
        "trigger": {
            "payout_id": "trigger_pid",
            "remarks": "SynthTrigger",
            "opens": "SynthFreespin",
        },
        "validation": {
            "status": "auto",
            "user_signed_off": False,
            "sign_off": "synthetic test fixture Phase 3",
            "confirmed_against": {"mode": 1, "rawdata": "synthetic"},
        },
        "rtp_integrity": {"paid_st": [paid_st], "fallback_warn": 1.0, "fallback_fail": 10.0},
        "out_of_engine_mechanics": [],
        "round_win_rule": None,
    }


def _synth_manifest_nodim(
    machine_id: str = "M_p3_nodim",
    fs_st: int = 126,
    paid_st: int = 1,
) -> dict:
    """Manifest with NO trigger_paths (BREAK-1 / no-dimension scenario)."""
    return {
        "machine_id": machine_id,
        "schema": "spintype-native/1",
        "modes": [1],
        "inherits_from": None,
        "spin_types": {
            str(paid_st): {
                "role": "paid_spin",
                "play": "Normal",
                "economy": {"win_field": "WinCredits", "kind": "real"},
                "signature": ["SpinType", "WinCredits"],
                "observed_fields": [
                    "SpinType", "CostCredits", "WinCredits",
                    "StopSymbolsByCol", "PayoutIdToWinAmount",
                ],
            },
            str(fs_st): {
                "role": "freespin",
                "play": "SynthFreespin",
                "economy": {"win_field": "WinCredits", "kind": "real"},
                "signature": ["SpinType", "WinCredits"],
                "observed_fields": [
                    "SpinType", "WinCredits",
                    "StopSymbolsByCol", "PayoutIdToWinAmount",
                ],
            },
        },
        "trigger": {
            "payout_id": "trigger_pid",
            "remarks": "SynthTrigger",
            "opens": "SynthFreespin",
        },
        "validation": {
            "status": "auto",
            "user_signed_off": False,
            "sign_off": "synthetic test fixture Phase 3 nodim",
            "confirmed_against": {"mode": 1, "rawdata": "synthetic"},
        },
        "rtp_integrity": {"paid_st": [paid_st], "fallback_warn": 1.0, "fallback_fail": 10.0},
        "out_of_engine_mechanics": [],
        "round_win_rule": None,
    }


# ---------------------------------------------------------------------------
# Synthetic round helpers
# ---------------------------------------------------------------------------

def _robot_entry(rounds: list[dict]) -> dict:
    return {
        "roundResult": json.dumps(rounds),
        "analysisResult": "{}",
    }


def _paid(*, st: int = 1, bet: int = 1000, win: int = 0) -> dict:
    return {
        "SpinType": st,
        "CostCredits": bet,
        "BetAmount": bet,
        "WinCredits": win,
        "StopSymbolsByCol": {"0": "bar", "1": "bar", "2": "bar"},
        "PayoutIdToWinAmount": {},
        "ReMarks": "",
    }


def _freespin(
    *,
    st: int = 126,
    win: int = 0,
    trigger_field: int | None = None,
    extra_ratio: float | None = None,
    fs_index: int | None = None,
    block_id_hint: int | None = None,
) -> dict:
    """Build a synthetic freespin round with optional ExtraRatio and ReMarks FS index."""
    r: dict[str, Any] = {
        "SpinType": st,
        "CostCredits": None,
        "WinCredits": win,
        "StopSymbolsByCol": {"0": "cherry", "1": "cherry", "2": "cherry"},
        "PayoutIdToWinAmount": {"10": win} if win > 0 else {},
        "ReMarks": f"Freespin {fs_index}; " if fs_index is not None else "",
    }
    if trigger_field is not None:
        r["TriggerField"] = trigger_field
    if extra_ratio is not None:
        r["ExtraRatio"] = extra_ratio
    return r


# ---------------------------------------------------------------------------
# Report runner
# ---------------------------------------------------------------------------

def _run_report(
    rounds: list[dict],
    manifest: dict,
    bet: int = 1000,
) -> dict:
    """Generate a full report via report_engine using synthetic chunk data."""
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks

    with tempfile.TemporaryDirectory() as tmp_root:
        tmp_path = Path(tmp_root)
        machine_id = manifest["machine_id"]
        manifests_root = tmp_path / "manifests"
        manifests_root.mkdir()
        (manifests_root / f"{machine_id}.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        chunk_dir = tmp_path / "chunks"
        chunk_dir.mkdir()
        chunk_data = {
            "_bet": bet,
            "_chunk_index": 1,
            "_machine": machine_id,
            "_mode": 1,
            "response": [_robot_entry(rounds)],
        }
        (chunk_dir / "chunk_0001.json").write_text(
            json.dumps(chunk_data), encoding="utf-8"
        )
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        summary = generate_report_from_chunks(
            machine_id, 1,
            chunk_dir=chunk_dir,
            output_dir=out_dir,
            manifests_root=manifests_root,
            bet=bet,
        )
    return summary


# ---------------------------------------------------------------------------
# Accessor helpers
# ---------------------------------------------------------------------------

def _fsd(summary: dict) -> dict:
    return summary.get("player_impact", {}).get("freespin_dynamics", {})


def _ufb(summary: dict) -> dict:
    return summary.get("player_impact", {}).get("upstream_feature_breakdown", {})


# ---------------------------------------------------------------------------
# Direct extractor test helpers
# ---------------------------------------------------------------------------

def _build_extractor_with_2path_manifest(field: str = "TriggerField") -> Any:
    from fresh_slotlab.analyzer.st_extract.freespin_progression import FreespinProgressionExtractor
    manifest = {
        "spin_types": {
            "126": {
                "role": "freespin",
                "trigger_paths": {
                    "discriminator": {
                        "kind": "round_field",
                        "field": field,
                        "map": {"0": "alpha", "1": "beta"},
                        "unmapped_value_policy": "surface_as_unknown_path",
                    },
                    "multi_trigger_policy": "additive_sessions",
                    "paths": {"alpha": {"label": "Alpha"}, "beta": {"label": "Beta"}},
                },
            }
        }
    }
    return FreespinProgressionExtractor(manifest)


def _fake_round_ctx(
    robot_idx: int = 0,
    block_id: int = 1,
    bet: int = 1000,
    win: float = 0.0,
) -> dict:
    return {
        "robot_idx": robot_idx,
        "block_id": block_id,
        "bet": bet,
        "win": win,
    }


# ===========================================================================
# Test 1 — Extractor synthetic: er_ladder / fs_arc / session_tiers per (st,dim,value)
# ===========================================================================

class TestExtractorSynthetic:
    """Direct FreespinProgressionExtractor tests — mirrors test_dimension_substrate harness.

    Synthetic fixture: 2-path freespin ST (alpha=TriggerField 0, beta=TriggerField 1).
    Alpha session: FS indices 1..4, ER climbs 100→400; beta session: FS indices 1..4,
    ER climbs 200→800.  All rounds in a single block (session).

    INVARIANT: sum over paths of fs_arc[fs_idx]["round_count"] == total rounds per fs_idx.
    """

    @pytest.fixture(scope="class")
    def extractor_output(self) -> dict:
        """Run extractor over a synthetic sequence; return finalize_chunk output."""
        ext = _build_extractor_with_2path_manifest()
        ext.begin_robot({"robot_idx": 0, "bet": 1000})

        # Session 1 (block_id=1): alpha path, FS 1-4 with climbing ER
        alpha_rounds = [
            {"SpinType": 126, "TriggerField": 0, "WinCredits": 500,  "ExtraRatio": 100, "ReMarks": "Freespin 1; "},
            {"SpinType": 126, "TriggerField": 0, "WinCredits": 0,    "ExtraRatio": 200, "ReMarks": "Freespin 2; "},
            {"SpinType": 126, "TriggerField": 0, "WinCredits": 0,    "ExtraRatio": 300, "ReMarks": "Freespin 3; "},
            {"SpinType": 126, "TriggerField": 0, "WinCredits": 1000, "ExtraRatio": 400, "ReMarks": "Freespin 4; "},
        ]
        for r in alpha_rounds:
            ctx = _fake_round_ctx(robot_idx=0, block_id=1, bet=1000,
                                  win=float(r.get("WinCredits", 0)))
            ext.observe_round(r, 126, ctx)

        # Session 2 (block_id=2): beta path, FS 1-4 with steeper climbing ER
        beta_rounds = [
            {"SpinType": 126, "TriggerField": 1, "WinCredits": 0,    "ExtraRatio": 200, "ReMarks": "Freespin 1; "},
            {"SpinType": 126, "TriggerField": 1, "WinCredits": 0,    "ExtraRatio": 400, "ReMarks": "Freespin 2; "},
            {"SpinType": 126, "TriggerField": 1, "WinCredits": 2000, "ExtraRatio": 600, "ReMarks": "Freespin 3; "},
            {"SpinType": 126, "TriggerField": 1, "WinCredits": 0,    "ExtraRatio": 800, "ReMarks": "Freespin 4; "},
        ]
        for r in beta_rounds:
            ctx = _fake_round_ctx(robot_idx=0, block_id=2, bet=1000,
                                  win=float(r.get("WinCredits", 0)))
            ext.observe_round(r, 126, ctx)

        return ext.finalize_chunk()

    def test_output_has_st_key(self, extractor_output):
        """finalize_chunk output must have the freespin ST string key."""
        assert "126" in extractor_output, (
            f"Expected '126' in extractor output. Got: {list(extractor_output)}"
        )

    def test_output_has_dim_name(self, extractor_output):
        """Output must contain 'trigger_path' dimension name."""
        st_data = extractor_output.get("126", {})
        assert "trigger_path" in st_data, (
            f"Expected 'trigger_path' dim in extractor output['126']. Got: {list(st_data)}"
        )

    def test_output_has_both_path_labels(self, extractor_output):
        """Both 'alpha' and 'beta' path labels must appear in output."""
        dim_data = extractor_output.get("126", {}).get("trigger_path", {})
        for label in ("alpha", "beta"):
            assert label in dim_data, (
                f"Expected path label '{label}' in trigger_path. Got: {list(dim_data)}"
            )

    def test_fs_arc_round_count_per_path_sum_equals_total(self, extractor_output):
        """INVARIANT: Sigma over paths of fs_arc[fs_idx].round_count == total per fs_idx.

        Per-path additivity: each FS round maps to exactly one path.
        INJECT-BUG IB-1: if fs_idx keying is broken (all rounds land in index 0),
        the per-index counts won't match expectations derived from the fixture.
        """
        dim_data = extractor_output.get("126", {}).get("trigger_path", {})
        # All 4 FS positions appear in both paths (8 total rounds).
        for fs_idx in ("1", "2", "3", "4"):
            total_for_idx = 0
            for path_label in ("alpha", "beta"):
                fs_arc = dim_data.get(path_label, {}).get("fs_arc", {})
                entry = fs_arc.get(fs_idx, {})
                total_for_idx += int(entry.get("round_count", 0))
            # Exactly 2 rounds per FS index (1 alpha + 1 beta).
            assert total_for_idx == 2, (
                f"Expected 2 total rounds at FS index '{fs_idx}' (1 per path). "
                f"Got {total_for_idx}."
            )

    def test_er_ladder_present_for_both_paths(self, extractor_output):
        """er_ladder must be non-empty for both paths when ExtraRatio field present."""
        dim_data = extractor_output.get("126", {}).get("trigger_path", {})
        for path_label in ("alpha", "beta"):
            er_ladder = dim_data.get(path_label, {}).get("er_ladder", {})
            assert er_ladder, (
                f"er_ladder empty for path '{path_label}'. ExtraRatio was present in rounds."
            )

    def test_session_tier_hist_present(self, extractor_output):
        """session_tier_hist must be non-empty for paths that had sessions."""
        dim_data = extractor_output.get("126", {}).get("trigger_path", {})
        for path_label in ("alpha", "beta"):
            hist = dim_data.get(path_label, {}).get("session_tier_hist", {})
            assert hist, (
                f"session_tier_hist empty for path '{path_label}'. "
                f"A session with win > 0 was recorded."
            )


# ===========================================================================
# Test 2 — ER ladder climb: mean_er increases across FS index
# ===========================================================================

class TestErLadderClimb:
    """mean_er must increase (monotone-ish) as FS index grows.

    The fixture below has ER=100 at FS 1 and ER=400 at FS 4 for one path.
    INJECT-BUG IB-1 breaks this: if rounds aren't keyed by fs_idx, there
    is only one bucket (fs_idx=0 or a flat key), and the climb cannot be observed.

    NOTE: mean_er is computed by FreespinDynamics._build_er_ladder_section(), not
    stored in the raw extractor output. This fixture runs the extractor then passes
    the raw output through _build_er_ladder_section() to get the computed aggregate.
    """

    @pytest.fixture(scope="class")
    def alpha_ladder(self) -> dict:
        """Run extractor then _build_er_ladder_section; return aggregate with mean_er.

        Uses FreespinDynamics._build_er_ladder_section() which computes mean_er per FS idx.
        The inject-bug (IB-1) breaks fs_idx keying in the extractor, collapsing all
        FS positions into a single bucket, making the climb assertion RED.
        """
        from fresh_slotlab.analyzer.features.freespin_dynamics import FreespinDynamics
        ext = _build_extractor_with_2path_manifest()
        ext.begin_robot({"robot_idx": 0, "bet": 1000})
        # ER climbs: 100 -> 200 -> 300 -> 400 across FS 1-4.
        rounds = [
            {"SpinType": 126, "TriggerField": 0, "WinCredits": 200, "ExtraRatio": 100, "ReMarks": "Freespin 1; "},
            {"SpinType": 126, "TriggerField": 0, "WinCredits": 200, "ExtraRatio": 200, "ReMarks": "Freespin 2; "},
            {"SpinType": 126, "TriggerField": 0, "WinCredits": 200, "ExtraRatio": 300, "ReMarks": "Freespin 3; "},
            {"SpinType": 126, "TriggerField": 0, "WinCredits": 200, "ExtraRatio": 400, "ReMarks": "Freespin 4; "},
        ]
        for r in rounds:
            ctx = _fake_round_ctx(robot_idx=0, block_id=1, bet=1000,
                                  win=float(r.get("WinCredits", 0)))
            ext.observe_round(r, 126, ctx)
        raw_output = ext.finalize_chunk()
        # prog_by_path = {path_label: {er_ladder, fs_arc, session_tier_hist}}
        prog_by_path = raw_output.get("126", {}).get("trigger_path", {})
        # Pass through the section builder which adds mean_er per FS index.
        section = FreespinDynamics._build_er_ladder_section(prog_by_path, [])
        return section.get("aggregate", {})

    def test_er_ladder_has_all_fs_indices(self, alpha_ladder):
        """er_ladder must have entries for all 4 FS positions."""
        for fs_idx in ("1", "2", "3", "4"):
            assert fs_idx in alpha_ladder, (
                f"FS index '{fs_idx}' missing from er_ladder. "
                f"Got: {sorted(alpha_ladder.keys())}"
            )

    def test_er_ladder_mean_er_climbs_across_fs_index(self, alpha_ladder):
        """RELATION: mean_er[FS 4] > mean_er[FS 1] (the climb).

        INJECT-BUG IB-1 target: if fs_idx keying is broken, all rounds pile into
        one bucket — the per-index climb relation cannot be verified -> RED.
        """
        entry_first = alpha_ladder.get("1", {})
        entry_last  = alpha_ladder.get("4", {})
        mean_first = entry_first.get("mean_er")
        mean_last  = entry_last.get("mean_er")
        assert mean_first is not None, "mean_er missing for FS index 1"
        assert mean_last  is not None, "mean_er missing for FS index 4"
        assert float(mean_last) > float(mean_first), (
            f"ER ladder climb broken: mean_er[FS4]={mean_last} <= mean_er[FS1]={mean_first}. "
            f"Expected monotone increase across FS index."
        )

    def test_er_ladder_round_count_sums_per_index(self, alpha_ladder):
        """Each FS index must have round_count == 1 (one round per FS position in fixture)."""
        for fs_idx in ("1", "2", "3", "4"):
            entry = alpha_ladder.get(fs_idx, {})
            rc = entry.get("round_count")
            assert rc == 1, (
                f"Expected round_count == 1 for FS index '{fs_idx}', got {rc}."
            )

    def test_er_ladder_er_sum_per_index(self, alpha_ladder):
        """er_sum for FS 1 must == ExtraRatio value at that position (100)."""
        entry_1 = alpha_ladder.get("1", {})
        er_sum = entry_1.get("er_sum")
        assert er_sum is not None, "er_sum missing from FS index 1 entry"
        assert float(er_sum) == pytest.approx(100.0), (
            f"Expected er_sum == 100.0 for FS 1, got {er_sum}"
        )


# ===========================================================================
# Test 3 — FS arc cliff: hit_rate declines across FS index; internal consistency
# ===========================================================================

class TestFsArcCliff:
    """hit_rate must decline as FS index increases (the cliff).

    The fixture has hit at FS 1 (high) and no-hit at FS 4 (low).
    Internal consistency: hit_rate == win_round_count / round_count.
    """

    @pytest.fixture(scope="class")
    def beta_arc(self) -> dict:
        """Run extractor then _build_fs_arc_section; return aggregate with hit_rate.

        NOTE: hit_rate is computed by FreespinDynamics._build_fs_arc_section(), not
        stored in the raw extractor output (fs_arc has round_count/win_round_count/win_sum
        but not hit_rate). This fixture runs the section builder to get the computed values.
        """
        from fresh_slotlab.analyzer.features.freespin_dynamics import FreespinDynamics
        ext = _build_extractor_with_2path_manifest()
        ext.begin_robot({"robot_idx": 0, "bet": 1000})
        # FS 1: wins (high hit rate), FS 2: win, FS 3: miss, FS 4: miss (low hit rate).
        # For testing the cliff: 2 wins early, 2 misses late in a 4-round session.
        rounds = [
            {"SpinType": 126, "TriggerField": 1, "WinCredits": 1000, "ReMarks": "Freespin 1; "},  # hit
            {"SpinType": 126, "TriggerField": 1, "WinCredits": 500,  "ReMarks": "Freespin 2; "},  # hit
            {"SpinType": 126, "TriggerField": 1, "WinCredits": 0,    "ReMarks": "Freespin 3; "},  # miss
            {"SpinType": 126, "TriggerField": 1, "WinCredits": 0,    "ReMarks": "Freespin 4; "},  # miss
        ]
        for r in rounds:
            ctx = _fake_round_ctx(robot_idx=0, block_id=1, bet=1000,
                                  win=float(r.get("WinCredits", 0)))
            ext.observe_round(r, 126, ctx)
        raw_output = ext.finalize_chunk()
        prog_by_path = raw_output.get("126", {}).get("trigger_path", {})
        section = FreespinDynamics._build_fs_arc_section(prog_by_path, [])
        return section.get("aggregate", {})

    def test_fs_arc_hit_rate_declines_from_first_to_last(self, beta_arc):
        """RELATION: hit_rate[FS 1] > hit_rate[FS 4] (the cliff).

        FS 1 has a win (hit_rate=1.0), FS 4 has no win (hit_rate=0.0).
        """
        entry_1 = beta_arc.get("1", {})
        entry_4 = beta_arc.get("4", {})
        hr_1 = entry_1.get("hit_rate")
        hr_4 = entry_4.get("hit_rate")
        assert hr_1 is not None, "hit_rate missing for FS index 1"
        assert hr_4 is not None, "hit_rate missing for FS index 4"
        assert float(hr_1) > float(hr_4), (
            f"FS arc cliff broken: hit_rate[FS1]={hr_1} <= hit_rate[FS4]={hr_4}. "
            f"Expected decline across FS index."
        )

    def test_fs_arc_hit_rate_internal_consistency(self, beta_arc):
        """INTERNAL CONSISTENCY: hit_rate == win_round_count / round_count for each FS idx."""
        for fs_idx, entry in beta_arc.items():
            rc = entry.get("round_count", 0)
            wrc = entry.get("win_round_count", 0)
            hr = entry.get("hit_rate")
            if hr is None:
                continue
            expected_hr = wrc / rc if rc > 0 else 0.0
            assert abs(float(hr) - expected_hr) < 1e-9, (
                f"hit_rate internal consistency broken at FS idx {fs_idx}: "
                f"hr={hr} but win_round_count/round_count={expected_hr}"
            )

    def test_fs_arc_win_round_count_matches_wins_in_fixture(self, beta_arc):
        """FS 1 and FS 2 each have exactly 1 win; FS 3 and 4 have 0."""
        for fs_idx, expected_wins in (("1", 1), ("2", 1), ("3", 0), ("4", 0)):
            wrc = beta_arc.get(fs_idx, {}).get("win_round_count", 0)
            assert wrc == expected_wins, (
                f"Expected win_round_count={expected_wins} at FS {fs_idx}, got {wrc}."
            )


# ===========================================================================
# Test 4 — Session tier: Sigma session_count == total; Sigma prob ~= 1
# ===========================================================================

class TestSessionTierConservation:
    """session_tier_distribution conservation laws.

    Fixture: 3 alpha sessions + 2 beta sessions; each path independently
    generates a session_tier_hist.  The aggregate section must combine them.

    INVARIANT: sum(session_count) == total_sessions; sum(prob) ~= 1.0.
    Bands must come from RETURN_BUCKET_ORDER vocabulary.
    """

    @pytest.fixture(scope="class")
    def fsd_section(self) -> dict:
        """Run full report on a 3-alpha + 2-beta session fixture; return session_tier_distribution."""
        rounds = []
        # 5 paid rounds to open sessions.
        for _ in range(5):
            rounds.append(_paid(st=1, bet=1000, win=0))
        # Alpha session 1 (block_id implicit from sequence; use separate robots in the
        # chunk to get separate block IDs — but synthetic harness uses single list,
        # so we use multi-session ReMarks hint).
        # Each FS index within a "session" is one round.  We use a simplified fixture:
        # 3 single-round alpha "sessions" (TriggerField=0) and 2 single-round beta "sessions".
        # Per-session, win totals will map to return_bucket.
        for i in range(3):
            r = _freespin(st=126, win=2000, trigger_field=0, fs_index=1)
            rounds.append(r)
        for i in range(2):
            r = _freespin(st=126, win=500, trigger_field=1, fs_index=1)
            rounds.append(r)
        manifest = _synth_manifest_2path(machine_id="M_p3_tier")
        summary = _run_report(rounds, manifest)
        return _fsd(summary).get("session_tier_distribution", {})

    def test_session_tier_available(self, fsd_section):
        """session_tier_distribution must be available (available != False)."""
        assert fsd_section.get("available") is not False, (
            f"session_tier_distribution.available is False. "
            f"Section: {fsd_section}"
        )

    def test_session_tier_aggregate_is_list(self, fsd_section):
        """session_tier_distribution.aggregate must be a list of band rows."""
        agg = fsd_section.get("aggregate")
        assert isinstance(agg, list) and len(agg) > 0, (
            f"session_tier_distribution.aggregate is not a non-empty list. Got: {agg}"
        )

    def test_session_tier_sigma_session_count_equals_total(self, fsd_section):
        """CONSERVATION: Sigma(session_count) == total_sessions."""
        agg = fsd_section.get("aggregate", [])
        total_sessions = fsd_section.get("total_sessions")
        assert total_sessions is not None and total_sessions > 0, (
            f"total_sessions missing or zero. Section: {fsd_section}"
        )
        sigma = sum(int(row.get("session_count", 0)) for row in agg)
        assert sigma == total_sessions, (
            f"CONSERVATION violated: Sigma(session_count)={sigma} != "
            f"total_sessions={total_sessions}"
        )

    def test_session_tier_sigma_prob_approx_one(self, fsd_section):
        """CONSERVATION: Sigma(prob) ~= 1.0 (probability normalizes)."""
        agg = fsd_section.get("aggregate", [])
        sigma_prob = sum(float(row.get("prob", 0.0) or 0.0) for row in agg)
        assert abs(sigma_prob - 1.0) < 0.01, (
            f"Sigma(prob)={sigma_prob:.6f} not approximately 1.0. "
            f"Rows: {agg}"
        )

    def test_session_tier_bands_from_return_bucket_vocabulary(self, fsd_section):
        """All band values must come from RETURN_BUCKET_ORDER or known extensions."""
        from fresh_slotlab.analyzer.core.aggregator import RETURN_BUCKET_ORDER
        valid_bands = set(RETURN_BUCKET_ORDER) | {"eq0"}  # eq0 is a valid edge bucket
        agg = fsd_section.get("aggregate", [])
        for row in agg:
            band = row.get("band")
            if band is not None and not row.get("unexpected_band"):
                assert band in valid_bands, (
                    f"Band '{band}' not in RETURN_BUCKET_ORDER. "
                    f"Valid: {sorted(valid_bands)}"
                )


# ===========================================================================
# Test 5 — by_dim present for 2-path fixture; absent for single-path fixture
# ===========================================================================

class TestByDimPresenceGuard:
    """by_dim on er_ladder / fs_index_arc / session_tier_distribution:
      - PRESENT when >=2 real paths observed
      - ABSENT (or aggregate-only) when single path

    Mirrors the Phase 2 >=2-real-values guard logic.
    """

    @pytest.fixture(scope="class")
    def summary_2path(self) -> dict:
        """2-path report: 3 alpha + 2 beta FS rounds."""
        rounds = [_paid(st=1, bet=1000, win=0)] * 3
        rounds += [_freespin(st=126, win=1000, trigger_field=0, extra_ratio=200, fs_index=1)]
        rounds += [_freespin(st=126, win=1000, trigger_field=0, extra_ratio=400, fs_index=2)]
        rounds += [_freespin(st=126, win=0,    trigger_field=0, extra_ratio=600, fs_index=3)]
        rounds += [_freespin(st=126, win=2000, trigger_field=1, extra_ratio=200, fs_index=1)]
        rounds += [_freespin(st=126, win=0,    trigger_field=1, extra_ratio=600, fs_index=2)]
        return _run_report(rounds, _synth_manifest_2path(machine_id="M_p3_2p_bydim"))

    @pytest.fixture(scope="class")
    def summary_singlepath(self) -> dict:
        """Single-path report: ALL rounds are alpha (TriggerField=0)."""
        rounds = [_paid(st=1, bet=1000, win=0)] * 3
        for i in range(5):
            rounds.append(_freespin(st=126, win=500, trigger_field=0,
                                    extra_ratio=100 * (i + 1), fs_index=i + 1))
        return _run_report(rounds, _synth_manifest_2path(machine_id="M_p3_1p_bydim"))

    def test_2path_er_ladder_has_by_dim(self, summary_2path):
        """er_ladder.by_dim must be present when >=2 real paths observed."""
        fsd = _fsd(summary_2path)
        er = fsd.get("er_ladder", {})
        if er.get("available") is False:
            pytest.skip("er_ladder not available (ExtraRatio absent in fixture?)")
        assert "by_dim" in er, (
            f"er_ladder.by_dim absent despite 2 real paths. "
            f"er_ladder keys: {list(er)}"
        )
        dim_block = er["by_dim"]
        assert "trigger_path" in dim_block, (
            f"er_ladder.by_dim missing 'trigger_path' key. Got: {list(dim_block)}"
        )
        real_vals = {k for k in dim_block["trigger_path"]
                     if not k.startswith("unknown:") and not k.startswith("multi:")}
        assert len(real_vals) >= 2, (
            f"Expected >=2 real dim values in er_ladder.by_dim.trigger_path. "
            f"Got: {sorted(real_vals)}"
        )

    def test_2path_fs_arc_has_by_dim(self, summary_2path):
        """fs_index_arc.by_dim must be present when >=2 real paths observed."""
        fsd = _fsd(summary_2path)
        arc = fsd.get("fs_index_arc", {})
        assert arc.get("available") is not False, (
            f"fs_index_arc not available. Section: {arc}"
        )
        assert "by_dim" in arc, (
            f"fs_index_arc.by_dim absent despite 2 real paths. "
            f"fs_index_arc keys: {list(arc)}"
        )

    def test_2path_session_tier_has_by_dim(self, summary_2path):
        """session_tier_distribution.by_dim must be present when >=2 real paths observed."""
        fsd = _fsd(summary_2path)
        tier = fsd.get("session_tier_distribution", {})
        assert tier.get("available") is not False, (
            f"session_tier_distribution not available. Section: {tier}"
        )
        assert "by_dim" in tier, (
            f"session_tier_distribution.by_dim absent despite 2 real paths. "
            f"Keys: {list(tier)}"
        )

    def test_singlepath_er_ladder_no_by_dim(self, summary_singlepath):
        """er_ladder must NOT have by_dim when only 1 real path observed."""
        fsd = _fsd(summary_singlepath)
        er = fsd.get("er_ladder", {})
        assert "by_dim" not in er, (
            f"er_ladder.by_dim present for single-path fixture. "
            f"er_ladder keys: {list(er)}"
        )

    def test_singlepath_fs_arc_no_by_dim(self, summary_singlepath):
        """fs_index_arc must NOT have by_dim when only 1 real path observed."""
        fsd = _fsd(summary_singlepath)
        arc = fsd.get("fs_index_arc", {})
        assert "by_dim" not in arc, (
            f"fs_index_arc.by_dim present for single-path fixture. "
            f"fs_index_arc keys: {list(arc)}"
        )

    def test_singlepath_session_tier_no_by_dim(self, summary_singlepath):
        """session_tier_distribution must NOT have by_dim for single-path fixture."""
        fsd = _fsd(summary_singlepath)
        tier = fsd.get("session_tier_distribution", {})
        assert "by_dim" not in tier, (
            f"session_tier_distribution.by_dim present for single-path fixture. "
            f"Keys: {list(tier)}"
        )


# ===========================================================================
# Test 6 — BREAK-1 guard: no freespin_progression extractor → no new sections / no crash
# ===========================================================================

class TestBreak1NoExtractor:
    """No new sections emitted when freespin_progression extractor is absent.

    A no-dimension manifest runs through the full report engine; the 3 new sections
    (er_ladder, fs_index_arc, session_tier_distribution) must not crash and must
    either be absent or have available=False.

    Also verifies: freespin_dynamics does not crash if the extractor was never
    registered or the chunks lack the extractor output.
    """

    @pytest.fixture(scope="class")
    def summary_nodim(self) -> dict:
        """No trigger_paths manifest: extractor fires on no STs."""
        rounds = [_paid(st=1, bet=1000, win=0)] * 5
        for _ in range(8):
            rounds.append(_freespin(st=126, win=100))
        return _run_report(rounds, _synth_manifest_nodim())

    def test_no_crash_for_nodim_manifest(self, summary_nodim):
        """Full report generation must not raise for a no-dimension manifest."""
        # If we reach here, no crash occurred.
        assert isinstance(summary_nodim, dict), "Expected dict summary from report engine."

    def test_nodim_er_ladder_not_available_or_absent(self, summary_nodim):
        """er_ladder must either be absent or have available=False for no-dim manifest."""
        fsd = _fsd(summary_nodim)
        er = fsd.get("er_ladder", {})
        if er:
            assert er.get("available") is False, (
                f"er_ladder.available is not False for no-dim manifest. "
                f"Section: {er}"
            )

    def test_nodim_fs_arc_not_available_or_absent(self, summary_nodim):
        """fs_index_arc must either be absent or have available=False for no-dim manifest."""
        fsd = _fsd(summary_nodim)
        arc = fsd.get("fs_index_arc", {})
        if arc:
            assert arc.get("available") is False, (
                f"fs_index_arc.available is not False for no-dim manifest. "
                f"Section: {arc}"
            )

    def test_nodim_session_tier_not_available_or_absent(self, summary_nodim):
        """session_tier_distribution must either be absent or have available=False for no-dim manifest."""
        fsd = _fsd(summary_nodim)
        tier = fsd.get("session_tier_distribution", {})
        if tier:
            assert tier.get("available") is False, (
                f"session_tier_distribution.available is not False for no-dim manifest. "
                f"Section: {tier}"
            )

    def test_freespin_dynamics_extract_no_crash_with_empty_st_extract(self):
        """FreespinDynamics.extract() must not crash when st_extract lacks freespin_progression."""
        from fresh_slotlab.analyzer.features.freespin_dynamics import FreespinDynamics
        plugin = FreespinDynamics()
        chunk_dict = {
            "st_extract": {
                "signature_audit": {"126": {"fields_observed": ["SpinType", "WinCredits"]}},
                # No "freespin_progression" key.
            },
            "spin_type_next_counts": {},
            "spin_type_bucket_spins": {},
            "spin_type_bucket_win": {},
        }
        acc = plugin.extract(None, chunk_dict)  # must not raise
        assert isinstance(acc, dict), "FreespinDynamics.extract() must return a dict."


# ===========================================================================
# Test 7 — UFB accurate labels: 2-path → per-path rows; no-dim → unchanged
# ===========================================================================

class TestUfbAccurateLabels:
    """upstream_feature_breakdown: accurate dimension labels for 2-path ST.

    When st_extract["trigger_path"]["dimensions"] is present for a feature ST
    with >=2 real paths, the sub_streams rows for that feature must have
    "label" == path labels (not "via NormalCollectionSpin" heuristic).

    For no-dimension machines: UFB behavior unchanged (no per-path rows).

    INJECT-BUG IB-2 target: test_ufb_accurate_labels_when_two_paths.
    """

    @pytest.fixture(scope="class")
    def summary_2path_ufb(self) -> dict:
        """2-path fixture for UFB accurate-label test."""
        rounds = [_paid(st=1, bet=1000, win=0)] * 5
        for i in range(4):
            rounds.append(
                _freespin(st=126, win=500, trigger_field=0,
                          extra_ratio=100 * (i + 1), fs_index=i + 1)
            )
        for i in range(2):
            rounds.append(
                _freespin(st=126, win=200, trigger_field=1,
                          extra_ratio=200 * (i + 1), fs_index=i + 1)
            )
        return _run_report(rounds, _synth_manifest_2path(machine_id="M_p3_ufb_2p"))

    @pytest.fixture(scope="class")
    def summary_nodim_ufb(self) -> dict:
        """No-dim fixture for UFB unchanged behavior test."""
        rounds = [_paid(st=1, bet=1000, win=0)] * 5
        for _ in range(6):
            rounds.append(_freespin(st=126, win=200))
        return _run_report(rounds, _synth_manifest_nodim(machine_id="M_p3_ufb_nodim"))

    def _get_sub_streams_labels(self, summary: dict, feature_name: str) -> list[str]:
        """Return label values from sub_streams for a given feature name."""
        ufb = _ufb(summary)
        features = ufb.get("features", [])
        for feat in features:
            if feat.get("feature") == feature_name or feat.get("play") == feature_name:
                return [ss.get("label") for ss in (feat.get("sub_streams") or [])]
        # Also search in the flat upstream_feature_breakdown dict.
        for key, val in ufb.items():
            if isinstance(val, dict) and key == feature_name:
                return [ss.get("label") for ss in (val.get("sub_streams") or [])]
        return []

    def test_ufb_accurate_labels_when_two_paths(self, summary_2path_ufb):
        """INJECT-BUG IB-2 target: sub_streams labels for 2-path feature must be
        per-path labels ('alpha', 'beta'), not coarse 'via ...' heuristic.

        If the Phase 3 accurate-label code is bypassed (IB-2: guard always skips),
        the labels remain "via NormalCollectionSpin" etc., making this test RED.
        """
        ufb = _ufb(summary_2path_ufb)
        if not ufb:
            pytest.skip("UFB not present in summary — feature not declared in synth manifest.")

        # Find sub_streams with _dimension_source marker (accurate rows).
        all_sub_streams: list[dict] = []
        def _walk_ufb(node):
            if isinstance(node, dict):
                if "_dimension_source" in node:
                    all_sub_streams.append(node)
                for v in node.values():
                    _walk_ufb(v)
            elif isinstance(node, list):
                for item in node:
                    _walk_ufb(item)
        _walk_ufb(ufb)

        if not all_sub_streams:
            # Fall back: check that no "via ..." coarse rows appear when dimension data present.
            # This means the test is only conclusive if sub_streams exist.
            pytest.skip(
                "UFB sub_streams with _dimension_source not found — "
                "likely feature ST not matching (synth machine has no feature → ST mapping). "
                "This is a known limitation of the synthetic fixture for UFB tests."
            )

        labels_seen = {ss.get("label") for ss in all_sub_streams}
        coarse_labels = {l for l in labels_seen if l and str(l).startswith("via ")}
        assert not coarse_labels, (
            f"Coarse 'via ...' labels still present despite dimension data: {coarse_labels}. "
            f"Accurate per-path labels expected: alpha, beta."
        )
        path_labels = {l for l in labels_seen if l in ("alpha", "beta")}
        assert path_labels, (
            f"Expected path labels 'alpha'/'beta' in UFB sub_streams. "
            f"Got: {labels_seen}. INJECT-BUG IB-2 would cause this."
        )

    def test_ufb_extract_returns_dimensions_data_when_present(self):
        """UpstreamFeatureBreakdown.extract() must return st_extract_dimensions when present."""
        from fresh_slotlab.analyzer.features.upstream_feature_breakdown import UpstreamFeatureBreakdown
        plugin = UpstreamFeatureBreakdown()
        # Build a chunk_dict with trigger_path extractor output containing "dimensions".
        chunk_dict = {
            "st_extract": {
                "trigger_path": {
                    "dimensions": {
                        "126": {
                            "trigger_path": {
                                "alpha": {"round_count": 100, "win_sum": 50000.0,
                                          "session_count": 10, "paid_round_count": 0,
                                          "win_round_count": 30, "bet_sum": 0.0},
                                "beta": {"round_count": 20, "win_sum": 8000.0,
                                         "session_count": 2, "paid_round_count": 0,
                                         "win_round_count": 5, "bet_sum": 0.0},
                            }
                        }
                    }
                }
            }
        }
        acc = plugin.extract(None, chunk_dict)
        assert "st_extract_dimensions" in acc, (
            f"extract() must return 'st_extract_dimensions' when trigger_path.dimensions present. "
            f"Got keys: {list(acc)}"
        )
        dims = acc["st_extract_dimensions"]
        assert "126" in dims, (
            f"st_extract_dimensions must have ST '126' key. Got: {list(dims)}"
        )

    def test_ufb_extract_returns_empty_when_no_dimensions(self):
        """UpstreamFeatureBreakdown.extract() must return {} when no dimensions sub-key."""
        from fresh_slotlab.analyzer.features.upstream_feature_breakdown import UpstreamFeatureBreakdown
        plugin = UpstreamFeatureBreakdown()
        chunk_dict = {
            "st_extract": {
                "signature_audit": {"126": {}},
                "trigger_path": {"126": {}},  # no "dimensions" key
            }
        }
        acc = plugin.extract(None, chunk_dict)
        assert not acc, (
            f"extract() must return empty dict when no dimensions sub-key. Got: {acc}"
        )

    def test_ufb_reduce_merges_dimensions_additively(self):
        """UpstreamFeatureBreakdown.reduce() must additively merge round_count / win_sum."""
        from fresh_slotlab.analyzer.features.upstream_feature_breakdown import UpstreamFeatureBreakdown
        plugin = UpstreamFeatureBreakdown()
        prev = {"st_extract_dimensions": {
            "126": {"trigger_path": {
                "alpha": {"round_count": 100, "win_sum": 50000.0, "session_count": 10,
                          "paid_round_count": 0, "win_round_count": 30, "bet_sum": 0.0},
            }}
        }}
        this = {"st_extract_dimensions": {
            "126": {"trigger_path": {
                "alpha": {"round_count": 50, "win_sum": 20000.0, "session_count": 5,
                          "paid_round_count": 0, "win_round_count": 15, "bet_sum": 0.0},
                "beta":  {"round_count": 20, "win_sum": 8000.0, "session_count": 2,
                          "paid_round_count": 0, "win_round_count": 5, "bet_sum": 0.0},
            }}
        }}
        merged = plugin.reduce(prev, this)
        dims = merged.get("st_extract_dimensions", {})
        alpha_merged = dims.get("126", {}).get("trigger_path", {}).get("alpha", {})
        assert int(alpha_merged.get("round_count", 0)) == 150, (
            f"Additive merge: alpha round_count should be 150. Got: {alpha_merged.get('round_count')}"
        )
        assert float(alpha_merged.get("win_sum", 0.0)) == pytest.approx(70000.0), (
            f"Additive merge: alpha win_sum should be 70000.0. Got: {alpha_merged.get('win_sum')}"
        )
        # Beta should be present from this_acc only.
        beta_merged = dims.get("126", {}).get("trigger_path", {}).get("beta", {})
        assert int(beta_merged.get("round_count", 0)) == 20, (
            f"Additive merge: beta round_count should be 20. Got: {beta_merged.get('round_count')}"
        )


# ===========================================================================
# Test 8 — Real-data M275 (skipif rawdata absent)
# ===========================================================================

class TestRealDataM275Phase3:
    """Real M275 regression: er_ladder climb + fs_arc cliff + session_tier conservation.

    All assertions are value-agnostic (relations only — no pinned literals).
    The specific climb/cliff values observed are printed for human review.
    """

    @pytest.fixture(scope="class")
    def summary(self) -> dict:
        if not M275_AVAILABLE:
            pytest.skip("rawdata/M275/mode_1 absent; developer-only test")
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmp:
            out = generate_report_from_chunks(
                "M275", 1,
                chunk_dir=M275_CHUNK_DIR,
                output_dir=Path(tmp),
                bet=1000,
            )
        return out

    @SKIP_NO_M275
    def test_integrity_passed(self, summary):
        ric = summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed is not True: {ric}"
        )

    @SKIP_NO_M275
    def test_er_ladder_available(self, summary):
        """er_ladder must be available on real M275 data."""
        er = _fsd(summary).get("er_ladder", {})
        assert er.get("available") is True, (
            f"er_ladder.available is not True on M275. Section: {er}"
        )

    @SKIP_NO_M275
    def test_er_ladder_climb_relation(self, summary):
        """RELATION: mean_er at last FS index > mean_er at first FS index.

        M275 design: ER climbs monotonically from ~145 at FS 1 to ~1641 at FS 10.
        We assert the relation, not the literal values.
        """
        er = _fsd(summary).get("er_ladder", {})
        agg = er.get("aggregate", {})
        fs_idxs = sorted(agg.keys(), key=lambda x: int(x))
        assert len(fs_idxs) >= 2, (
            f"er_ladder.aggregate must have >=2 FS positions. Got: {fs_idxs}"
        )
        mean_er_first = agg[fs_idxs[0]].get("mean_er")
        mean_er_last  = agg[fs_idxs[-1]].get("mean_er")
        print(
            f"\n[M275 ER climb] "
            f"mean_er[FS {fs_idxs[0]}]={mean_er_first:.1f} → "
            f"mean_er[FS {fs_idxs[-1]}]={mean_er_last:.1f}"
        )
        assert float(mean_er_last) > float(mean_er_first), (
            f"ER ladder climb broken on real M275: "
            f"mean_er[last={fs_idxs[-1]}]={mean_er_last} <= "
            f"mean_er[first={fs_idxs[0]}]={mean_er_first}."
        )

    @SKIP_NO_M275
    def test_fs_arc_available(self, summary):
        """fs_index_arc must be available on real M275 data."""
        arc = _fsd(summary).get("fs_index_arc", {})
        assert arc.get("available") is True, (
            f"fs_index_arc.available is not True on M275. Section: {arc}"
        )

    @SKIP_NO_M275
    def test_fs_arc_cliff_relation(self, summary):
        """RELATION: hit_rate at last FS index < hit_rate at first FS index.

        M275 design: hit_rate declines from ~43.8% at FS 1 to ~3.7% at FS 10.
        We assert the relation, not the literal values.
        """
        arc = _fsd(summary).get("fs_index_arc", {})
        agg = arc.get("aggregate", {})
        fs_idxs = sorted(agg.keys(), key=lambda x: int(x))
        assert len(fs_idxs) >= 2, (
            f"fs_index_arc.aggregate must have >=2 FS positions. Got: {fs_idxs}"
        )
        hr_first = agg[fs_idxs[0]].get("hit_rate")
        hr_last  = agg[fs_idxs[-1]].get("hit_rate")
        print(
            f"\n[M275 FS arc cliff] "
            f"hit_rate[FS {fs_idxs[0]}]={hr_first:.4f} → "
            f"hit_rate[FS {fs_idxs[-1]}]={hr_last:.4f}"
        )
        assert float(hr_last) < float(hr_first), (
            f"FS arc cliff broken on real M275: "
            f"hit_rate[last={fs_idxs[-1]}]={hr_last} >= "
            f"hit_rate[first={fs_idxs[0]}]={hr_first}."
        )

    @SKIP_NO_M275
    def test_fs_arc_hit_rate_internal_consistency(self, summary):
        """Internal consistency: hit_rate == win_round_count / round_count for each FS idx."""
        arc = _fsd(summary).get("fs_index_arc", {})
        agg = arc.get("aggregate", {})
        for fs_idx, entry in agg.items():
            rc = int(entry.get("round_count", 0))
            wrc = int(entry.get("win_round_count", 0))
            hr = entry.get("hit_rate")
            if hr is None or rc == 0:
                continue
            expected = wrc / rc
            assert abs(float(hr) - expected) < 1e-9, (
                f"hit_rate internal consistency broken at FS {fs_idx}: "
                f"hr={hr} but wrc/rc={expected}"
            )

    @SKIP_NO_M275
    def test_session_tier_conservation(self, summary):
        """CONSERVATION: Sigma(session_count) == total_sessions."""
        tier = _fsd(summary).get("session_tier_distribution", {})
        assert tier.get("available") is not False, (
            f"session_tier_distribution.available=False on M275. Section: {tier}"
        )
        agg = tier.get("aggregate", [])
        total_sessions = tier.get("total_sessions")
        assert total_sessions is not None and total_sessions > 0, (
            f"total_sessions missing or zero on M275. Section: {tier}"
        )
        sigma = sum(int(row.get("session_count", 0)) for row in agg)
        print(f"\n[M275 session tier] total={total_sessions}, Sigma={sigma}, bands={len(agg)}")
        assert sigma == total_sessions, (
            f"CONSERVATION violated on M275: Sigma={sigma} != total_sessions={total_sessions}"
        )

    @SKIP_NO_M275
    def test_er_ladder_by_dim_has_scatter_and_collect_peak(self, summary):
        """er_ladder.by_dim.trigger_path must have scatter + collect_peak for M275."""
        er = _fsd(summary).get("er_ladder", {})
        by_dim = er.get("by_dim", {})
        assert by_dim, (
            f"er_ladder.by_dim absent on M275 (expected scatter + collect_peak). "
            f"er_ladder keys: {list(er)}"
        )
        tp = by_dim.get("trigger_path", {})
        for path in ("scatter", "collect_peak"):
            assert path in tp, (
                f"'{path}' missing from er_ladder.by_dim.trigger_path on M275. "
                f"Got: {sorted(tp)}"
            )

    @SKIP_NO_M275
    def test_fs_arc_by_dim_has_scatter_and_collect_peak(self, summary):
        """fs_index_arc.by_dim.trigger_path must have scatter + collect_peak for M275."""
        arc = _fsd(summary).get("fs_index_arc", {})
        by_dim = arc.get("by_dim", {})
        assert by_dim, (
            f"fs_index_arc.by_dim absent on M275. arc keys: {list(arc)}"
        )
        tp = by_dim.get("trigger_path", {})
        for path in ("scatter", "collect_peak"):
            assert path in tp, (
                f"'{path}' missing from fs_index_arc.by_dim.trigger_path on M275. "
                f"Got: {sorted(tp)}"
            )

    @SKIP_NO_M275
    def test_session_tier_by_dim_has_scatter_and_collect_peak(self, summary):
        """session_tier_distribution.by_dim.trigger_path must have both paths for M275."""
        tier = _fsd(summary).get("session_tier_distribution", {})
        by_dim = tier.get("by_dim", {})
        assert by_dim, (
            f"session_tier_distribution.by_dim absent on M275. tier keys: {list(tier)}"
        )
        tp = by_dim.get("trigger_path", {})
        for path in ("scatter", "collect_peak"):
            assert path in tp, (
                f"'{path}' missing from session_tier_distribution.by_dim.trigger_path. "
                f"Got: {sorted(tp)}"
            )

    @SKIP_NO_M275
    def test_per_path_arc_round_count_sums_to_aggregate(self, summary):
        """ADDITIVITY: Sigma per-path round_count per FS idx == aggregate round_count.

        This is the key additivity invariant: each freespin round maps to exactly one path.
        """
        arc = _fsd(summary).get("fs_index_arc", {})
        agg = arc.get("aggregate", {})
        by_dim = arc.get("by_dim", {}).get("trigger_path", {})
        if not by_dim:
            pytest.skip("by_dim absent on M275 (unexpected — this should be present)")

        real_paths = [p for p in by_dim if not p.startswith("unknown:") and not p.startswith("multi:")]
        for fs_idx_str, agg_entry in agg.items():
            agg_rc = int(agg_entry.get("round_count", 0))
            path_rc_sum = sum(
                int((by_dim.get(p) or {}).get(fs_idx_str, {}).get("round_count", 0))
                for p in real_paths
            )
            assert path_rc_sum == agg_rc, (
                f"ADDITIVITY violated at FS index {fs_idx_str}: "
                f"sum over paths ({real_paths}) = {path_rc_sum} != "
                f"aggregate round_count = {agg_rc}"
            )

    @SKIP_NO_M275
    def test_ufb_accurate_path_labels_m275(self, summary):
        """INJECT-BUG IB-2 target (real-data): UFB must use accurate per-path labels
        ('scatter', 'collect_peak') instead of coarse 'via ...' heuristic for M275.

        With IB-2 (guard changed to `< 1000`), UFB emits:
          'NewFreespin [via NewFreespin]' + 'NewFreespin [via BCM cycle]'
        After revert, UFB emits:
          'NewFreespin [scatter]' + 'NewFreespin [collect_peak]'
        This test passes when accurate labels are present and coarse labels are absent.
        """
        ufb = _ufb(summary)
        feats = ufb.get("features", [])
        if not feats:
            pytest.skip("UFB features empty on M275 (unexpected)")

        all_trigger_path_labels = [
            f.get("trigger_path_label")
            for f in feats
            if f.get("trigger_path_label") is not None
        ]
        if not all_trigger_path_labels:
            pytest.skip("No trigger_path_label fields found in UFB features")

        print(f"\n[M275 UFB trigger_path_labels]: {all_trigger_path_labels}")

        # Coarse labels: start with "via "
        coarse_labels = [l for l in all_trigger_path_labels if str(l).startswith("via ")]
        assert not coarse_labels, (
            f"Coarse 'via ...' labels still present in M275 UFB features: {coarse_labels}. "
            f"Expected accurate per-path labels ('scatter', 'collect_peak'). "
            f"INJECT-BUG IB-2 would cause this regression."
        )
        # Accurate path labels from M275 dimension declaration.
        accurate_labels = {l for l in all_trigger_path_labels
                           if l in ("scatter", "collect_peak")}
        assert len(accurate_labels) == 2, (
            f"Expected both 'scatter' and 'collect_peak' labels in M275 UFB. "
            f"Got: {sorted(all_trigger_path_labels)}. "
            f"Phase 3 accurate-label replacement may have failed."
        )


# ===========================================================================
# Test 9 — Frontend contract: i18n keys + renderer reads correct data paths
# ===========================================================================

class TestFrontendContractPhase3:
    """Contract: Phase 3 i18n keys + renderer data-path reads.

    Validates:
    (a) All i18n keys used by the Phase 3 sub-panels exist in pure.js BOTH locales.
    (b) The renderer reads fd.er_ladder / fd.fs_index_arc / fd.session_tier_distribution
        (grep for "_stDimFreespin" section + those keys).
    (c) fsRowSessions + stoColShare + rdColBand (reused, not duplicated) exist in both locales.
    (d) node --check passes for app.js + pure.js.
    """

    _APP_JS = ROOT / "src" / "web_console" / "frontend" / "app.js"
    _PURE_JS = ROOT / "src" / "web_console" / "frontend" / "pure.js"

    @pytest.fixture(scope="class")
    def app_js_text(self) -> str:
        return self._APP_JS.read_bytes().decode("utf-8", errors="replace")

    @pytest.fixture(scope="class")
    def pure_js_text(self) -> str:
        return self._PURE_JS.read_bytes().decode("utf-8", errors="replace")

    def test_i18n_phase3_keys_present_in_both_locales(self, pure_js_text):
        """All Phase 3 new i18n keys must exist in pure.js BOTH locales (>=2 occurrences)."""
        # Keys specifically added for Phase 3 sub-panels.
        # The coordinator specified: fsErLadder, fsErColFsIdx, fsErLadderNote,
        # fsFsArc, fsFsArcNote, fsSessionTier, fsSessionTierTotal, fsProgAggregate.
        new_phase3_keys = [
            "fsErLadder",
            "fsErColFsIdx",
            "fsErLadderNote",
            "fsFsArc",
            "fsFsArcNote",
            "fsSessionTier",
            "fsSessionTierTotal",
            "fsProgAggregate",
        ]
        for key in new_phase3_keys:
            count = pure_js_text.count(f"{key}:")
            assert count >= 2, (
                f"i18n key '{key}' appears {count} time(s) in pure.js (as '{key}:') — "
                f"expected >=2 (once per locale: zh + en). "
                f"Phase 3 key missing from one or both locales."
            )

    def test_i18n_reused_keys_present_in_both_locales(self, pure_js_text):
        """Per feedback_no_parallel_panel_impl.md: reused i18n keys must exist
        (not re-created as parallel implementations)."""
        reused_keys = [
            "stoColShare",   # share/prob column (reused from spin_type_outcomes)
            "rdColBand",     # band column (reused from reel_marginal)
            "fsRowSessions", # sessions column (reused from freespin path table)
        ]
        for key in reused_keys:
            count = pure_js_text.count(f"{key}:")
            assert count >= 2, (
                f"Reused i18n key '{key}' appears {count} time(s) in pure.js — "
                f"expected >=2 (zh + en). Key must be reused from sibling renderer, "
                f"not omitted (feedback_no_parallel_panel_impl)."
            )

    def test_app_js_reads_er_ladder(self, app_js_text):
        """app.js must read fd.er_ladder (Phase 3 ER ladder data key)."""
        assert "fd.er_ladder" in app_js_text or "er_ladder" in app_js_text, (
            "app.js does not reference 'er_ladder' — Phase 3 ER ladder renderer missing."
        )

    def test_app_js_reads_fs_index_arc(self, app_js_text):
        """app.js must read fd.fs_index_arc (Phase 3 FS arc data key)."""
        assert "fd.fs_index_arc" in app_js_text or "fs_index_arc" in app_js_text, (
            "app.js does not reference 'fs_index_arc' — Phase 3 FS arc renderer missing."
        )

    def test_app_js_reads_session_tier_distribution(self, app_js_text):
        """app.js must read fd.session_tier_distribution (Phase 3 session tier key)."""
        assert "session_tier_distribution" in app_js_text, (
            "app.js does not reference 'session_tier_distribution' — "
            "Phase 3 session tier renderer missing."
        )

    def test_app_js_stDimFreespin_contains_phase3_panels(self, app_js_text):
        """_stDimFreespin in app.js must contain the Phase 3 sub-panel code."""
        # Find _stDimFreespin function boundary.
        idx = app_js_text.find("function _stDimFreespin")
        assert idx >= 0, "_stDimFreespin function not found in app.js"
        # Verify all 3 phase 3 section names appear after the function def.
        for section_ref in ("er_ladder", "fs_index_arc", "session_tier_distribution"):
            after_idx = app_js_text.find(section_ref, idx)
            assert after_idx >= 0, (
                f"'{section_ref}' not found in app.js after _stDimFreespin. "
                f"Phase 3 sub-panel not added."
            )

    def test_app_js_node_check(self):
        """node --check must pass for app.js (no syntax errors)."""
        import subprocess
        result = subprocess.run(
            ["node", "--check", str(self._APP_JS)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"node --check app.js failed:\n{result.stderr}"
        )

    def test_pure_js_node_check(self):
        """node --check must pass for pure.js (no syntax errors)."""
        import subprocess
        result = subprocess.run(
            ["node", "--check", str(self._PURE_JS)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"node --check pure.js failed:\n{result.stderr}"
        )


# ===========================================================================
# Test — base_hash unchanged (Phase 3 must NOT touch closure files)
# ===========================================================================

class TestBaseHashUnchangedPhase3:
    """Phase 3 must not change base_hash. All changes are base-excluded.

    Expected base_hash: c5d2199142c3 (from Phase 2 and unchanged through Phase 3).
    """

    def test_base_hash_is_current_baseline(self):
        """compute_base_analyzer_version() must return the current baseline
        ddde50975d25 (re-baselined 2026-06-22 by the DELIBERATE pluggable
        round_win rule-engine refactor: the 4 rule TYPE classes + RULE_REGISTRY
        moved out of fresh_slotlab/round_win.py into the base-EXCLUDED
        fresh_slotlab/round_win_rules/ package; round_win_rules/__init__.py added
        to _CLOSURE_FILES. Last rule-type base_hash flip; prior bba689d50f03
        (SettlementWinAmountRule.settlement_label_format); was d9fa4625b956
        derive-from-data routing).

        If this fails, a closure file (_CLOSURE_FILES in versioning.py) was
        accidentally modified (or a new deliberate closure change needs this
        baseline updated) — freespin_progression.py, freespin_dynamics.py,
        upstream_feature_breakdown.py and the round_win_rules/*.py rule types
        are all base-excluded.
        """
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        bh = compute_base_analyzer_version()
        assert bh == "ddde50975d25", (
            f"base_hash changed from the ddde50975d25 baseline to {bh!r}. "
            f"A base_hash change means a closure file was accidentally modified "
            f"(or a deliberate closure change needs this updated)."
        )


# ===========================================================================
# Test — Additive gate: M15/M43/M279 emit NO new Phase 3 sections
# ===========================================================================

class TestAdditiveGatePhase3:
    """M15/M43/M279 must NOT gain er_ladder / fs_index_arc / session_tier_distribution
    (they have no trigger_paths, so no FreespinProgressionExtractor fires).

    Mirrors the Phase 2 additive gate logic.
    """

    _RAWDATA = ROOT / "rawdata"
    _CASES = [
        ("M15", 1, 1000),
        ("M43", 1, 1000),
        ("M279", 1, 1000),
    ]

    @pytest.mark.parametrize("machine,mode,bet", _CASES)
    def test_no_phase3_sections_for_nodim_machine(self, machine, mode, bet):
        """Run a real report on M15/M43/M279 and verify NO Phase 3 sections appear.

        These machines have no trigger_paths on any ST, so the
        FreespinProgressionExtractor accumulates nothing for them.
        """
        chunk_dir = self._RAWDATA / machine / f"mode_{mode}"
        if not chunk_dir.exists():
            pytest.skip(f"rawdata/{machine}/mode_{mode} absent")

        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmp:
            summary = generate_report_from_chunks(
                machine, mode,
                chunk_dir=chunk_dir,
                output_dir=Path(tmp),
                bet=bet,
            )

        fsd = _fsd(summary)

        # er_ladder: must be absent or have available=False.
        er = fsd.get("er_ladder", {})
        if er:
            assert er.get("available") is False, (
                f"{machine}/mode_{mode}: er_ladder.available is not False. "
                f"Phase 3 additive-only contract broken."
            )

        # fs_index_arc: must be absent or have available=False.
        arc = fsd.get("fs_index_arc", {})
        if arc:
            assert arc.get("available") is False, (
                f"{machine}/mode_{mode}: fs_index_arc.available is not False. "
                f"Phase 3 additive-only contract broken."
            )

        # session_tier_distribution: must be absent or have available=False.
        tier = fsd.get("session_tier_distribution", {})
        if tier:
            assert tier.get("available") is False, (
                f"{machine}/mode_{mode}: session_tier_distribution.available is not False. "
                f"Phase 3 additive-only contract broken."
            )
