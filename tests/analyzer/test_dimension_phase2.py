"""Phase 2 dimension framework tests — plugins consume dimensions substrate + emit by_dim.

Design source:
    session_artifacts/_arch_playtype/dimension/04_dimension_framework.md §3.3/§3.4
Breaker source:
    session_artifacts/_arch_playtype/dimension/05_breaker.md (BREAK-1, GAP-B basis)
Implementations tested:
    fresh_slotlab/analyzer/features/payouts_by_spin_type.py (Phase 2 __by_dim__ sibling key)
    fresh_slotlab/analyzer/features/spin_type_outcomes.py   (Phase 2 by_dim sub-key)
    fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py (Phase 2 __by_dim__ sibling key)
    fresh_slotlab/analyzer/features/freespin_dynamics.py   (Phase 2 rtp_concentration.by_dim)
    src/web_console/frontend/app.js (_stDimGenericDimension function)
    src/web_console/frontend/pure.js (dim* i18n keys)

Contract Phase 2 establishes (value-agnostic — relations only, no pinned literals)
-----------------------------------------------------------------------------------
ADDITIVE:
  A ST with <2 real dimension-values emits NO by_dim/__by_dim__ keys.
  M15/M43/M279 produce byte-identical output to before (no declared dimensions).
  Only M275 ST126 gains by_dim, because it has exactly 2 real values:
  scatter and collect_peak.

GUARD (BREAK-1 from 05_breaker.md):
  Every plugin guards on the precise "dimensions" sub-key inside
  st_extract["trigger_path"], NOT on st_extract presence. st_extract is
  always non-empty fleet-wide (signature_audit extractor fires for all 4 machines).
  The guard must be:
    st_extract.get("trigger_path", {}).get("dimensions", {})  # OK
  NOT:
    if "st_extract" in chunk_dict:                            # WRONG — BREAK-1

PER-PANEL RTP BASIS SELF-CONSISTENCY (GAP-B from 05_breaker.md):
  spin_type_outcomes ST126 by_dim:
    Sigma(per-dim rtp_contribution_pp) == ST126 aggregate rtp_contribution_pp
    using the OUTCOME basis (global-bet denominator, same as rtp_pp_stb).

  payouts_by_spin_type "__by_dim__<dim>" sibling key:
    Sigma over real values of Sigma(payid rtp_pp) == ST126 aggregate Sigma(payid rtp_pp)
    using the PAYID basis (effective_bet_for_rtp denominator).

  freespin_dynamics.rtp_concentration.by_dim:
    BOTH rtp_contribution_pp_payid_basis AND rtp_contribution_pp_outcome_basis
    are present and each sum to their respective aggregate.

SCHEMA SHAPES:
  dict-valued keys (spin_type_outcomes):
    nested "by_dim":{dim_name:{_dim_label, _dim_values, <value>:{...}, _unknown, _multi}}
  list-valued (payouts_by_spin_type):
    sibling "<label>__by_dim__<dim_name>":{value:[rows]}

INJECT-BUG RECIPES (documented per feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------------
IB-1 (break per-panel basis — wrong rtp for spin_type_outcomes by_dim):
  In spin_type_outcomes.py emit(), in the by_dim section, change the per-dim rtp_pp
  formula from outcome-basis to payid-basis:
    OLD: _dv_rtp_pp = (_dv_total_win / total_win_stb) * rtp_pp_stb
    NEW: _dv_rtp_pp = (_dv_total_win / effective_bet_for_rtp) * 100.0  # wrong basis
  where effective_bet_for_rtp = ctx.effective_bet_for_rtp
  => test_spin_type_outcomes_by_dim_sum_equals_aggregate_outcome_basis RED
     because Sigma(per-dim outcome-pp) != rtp_pp_stb
  Revert => GREEN.

IB-2 (weaken guard to st_extract presence instead of "dimensions" sub-key):
  In payouts_by_spin_type.py extract(), change the guard from:
    _dims_raw = _tp_raw.get("dimensions")
    if isinstance(_dims_raw, dict):
  to:
    if isinstance(_tp_raw, dict):  # WRONG — fires for all 4 machines
  => TestBreak1Guard.test_payouts_extract_no_dim_data_when_no_dimensions_sub_key RED
  Revert => GREEN.

Memory feedback honored:
  memory/feedback_enumerate_safety_paths.md — inject-bug per invariant above
  memory/feedback_perf_claim_needs_e2e_event_stream.md — Test 6 uses real engine
    on real M275 chunks (not just unit-testing extract() in isolation)
  memory/feedback_integration_test_argv.md — Test 6 asserts actual computed
    relations (Sigma == aggregate), not just "the key is present"
  memory/feedback_no_silent_swallow.md — unknown/multi buckets asserted present
    as alarm signals; tests would fail if they were silently merged
  memory/feedback_aggregator_parity_invariant.md — GAP-B Sigma==aggregate
    is the cross-aggregator parity invariant for the dimension dimension
"""
from __future__ import annotations

import json
import tempfile
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

# The ST that gets by_dim in M275.
_FS_ST = 126
_FS_LABEL = "ST126_free"
_DIM_NAME = "trigger_path"
_REAL_VALUES = frozenset({"scatter", "collect_peak"})


# ---------------------------------------------------------------------------
# Synthetic manifest builder  (valid for generate_report_from_chunks)
# ---------------------------------------------------------------------------

def _synth_manifest_2val(
    machine_id: str = "M_synth_2val",
    fs_st: int = 126,
    paid_st: int = 1,
    field: str = "FieldX",
) -> dict:
    """Full spintype-native/1 manifest with 2-value trigger_paths on ST=fs_st.

    Includes all required fields so machine_spec.validate_schema() passes.
    """
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
                "observed_fields": ["SpinType", "CostCredits", "WinCredits",
                                    "StopSymbolsByCol", "PayoutIdToWinAmount"],
            },
            str(fs_st): {
                "role": "freespin",
                "play": "SynthFreespin",
                "economy": {"win_field": "WinCredits", "kind": "real"},
                "signature": ["SpinType", "WinCredits"],
                "observed_fields": ["SpinType", "WinCredits",
                                    "StopSymbolsByCol", "PayoutIdToWinAmount",
                                    field],
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
            "sign_off": "synthetic test fixture",
            "confirmed_against": {"mode": 1, "rawdata": "synthetic"},
        },
        "rtp_integrity": {"paid_st": [paid_st], "fallback_warn": 1.0, "fallback_fail": 10.0},
        "out_of_engine_mechanics": [],
        "round_win_rule": None,
    }


def _synth_manifest_nodim(
    machine_id: str = "M_synth_nodim",
    fs_st: int = 126,
    paid_st: int = 1,
) -> dict:
    """Manifest with NO trigger_paths at all (BREAK-1 scenario)."""
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
                "observed_fields": ["SpinType", "CostCredits", "WinCredits",
                                    "StopSymbolsByCol", "PayoutIdToWinAmount"],
            },
            str(fs_st): {
                "role": "freespin",
                "play": "SynthFreespin",
                "economy": {"win_field": "WinCredits", "kind": "real"},
                "signature": ["SpinType", "WinCredits"],
                "observed_fields": ["SpinType", "WinCredits",
                                    "StopSymbolsByCol", "PayoutIdToWinAmount"],
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
            "sign_off": "synthetic test fixture",
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
    """Build a robot entry in the format expected by the chunk cache format.

    The chunk file has response: [{roundResult: json_str, analysisResult: json_str}].
    The analysisResult is the upstream analysis JSON — empty dict is fine for synthetic.
    """
    return {
        "roundResult": json.dumps(rounds),
        "analysisResult": "{}",
    }


def _paid(
    *,
    st: int = 1,
    bet: int = 1000,
    win: int = 0,
    payout: dict | None = None,
) -> dict:
    return {
        "SpinType": st,
        "CostCredits": bet,
        "BetAmount": bet,
        "WinCredits": win,
        "StopSymbolsByCol": {"0": "cherry", "1": "bar", "2": "seven"},
        "PayoutIdToWinAmount": payout if payout is not None else {},
        "ReMarks": "",
    }


def _bonus(
    *,
    st: int = 126,
    win: int = 0,
    payout: dict | None = None,
    field_x: int | None = None,
) -> dict:
    r: dict[str, Any] = {
        "SpinType": st,
        "CostCredits": None,
        "WinCredits": win,
        "StopSymbolsByCol": {"0": "cherry", "1": "bar", "2": "seven"},
        "PayoutIdToWinAmount": payout if payout is not None else ({"10": win} if win > 0 else {}),
        "ReMarks": "",
    }
    if field_x is not None:
        r["FieldX"] = field_x
    return r


# ---------------------------------------------------------------------------
# Report runner using temp manifests_root
# ---------------------------------------------------------------------------

def _run_report(
    rounds: list[dict],
    manifest: dict,
    bet: int = 1000,
) -> dict:
    """Generate a full report summary via report_engine using synthetic data."""
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
        # Chunk file format: response = [{roundResult: json_str, analysisResult: json_str}].
        # _payload_sha256 omitted (v2 legacy compat — loader accepts without it).
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

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        summary = generate_report_from_chunks(
            machine_id, 1,
            chunk_dir=chunk_dir,
            output_dir=output_dir,
            manifests_root=manifests_root,
            bet=bet,
        )
    return summary


# ---------------------------------------------------------------------------
# Accessor helpers
# ---------------------------------------------------------------------------

def _pbst(summary: dict) -> dict:
    return summary.get("player_impact", {}).get("payouts_by_spin_type", {})


def _sto(summary: dict) -> dict:
    return summary.get("player_impact", {}).get("spin_type_outcomes", {})


def _rmbst(summary: dict) -> dict:
    return summary.get("player_impact", {}).get("reel_marginal_by_spin_type", {})


def _fsd(summary: dict) -> dict:
    return summary.get("player_impact", {}).get("freespin_dynamics", {})


def _has_by_dim_key(d: dict, prefix: str) -> bool:
    return any(k.startswith(f"{prefix}__by_dim__") for k in d)


def _has_nested_by_dim(sto_entry: dict) -> bool:
    return "by_dim" in sto_entry


# ===========================================================================
# Test 1 — Synthetic 2-value ST: each plugin emits by_dim + Sigma==aggregate
# ===========================================================================

class TestTwoValueSt:
    """2-value ST fixture: alpha (FieldX=0, 5 rounds, 500 win each = 500 total)
    + beta (FieldX=1, 3 rounds, 500 win each).

    Sigma per-dim == aggregate tested per-plugin per its own RTP basis:
    - spin_type_outcomes: outcome basis (round-level rtp_pp_stb from stb)
    - payouts_by_spin_type: payid basis (effective_bet_for_rtp denominator)
    """

    @pytest.fixture(scope="class")
    def summary(self) -> dict:
        """Build a synthetic 2-value report once per class."""
        rounds = []
        for _ in range(5):
            rounds.append(_paid(st=1, bet=1000, win=0))
        # 5 alpha bonus rounds (FieldX=0), each winning 500 credits
        for _ in range(5):
            rounds.append(_bonus(st=126, win=500, field_x=0))
        # 3 beta bonus rounds (FieldX=1), each winning 500 credits
        for _ in range(3):
            rounds.append(_bonus(st=126, win=500, field_x=1))
        return _run_report(rounds, _synth_manifest_2val())

    def test_payouts_by_spin_type_has_by_dim_sibling(self, summary):
        """payouts_by_spin_type must have a 'ST126_free__by_dim__trigger_path' sibling key."""
        pbst = _pbst(summary)
        sibling = "ST126_free__by_dim__trigger_path"
        assert sibling in pbst, (
            f"Expected '{sibling}' in payouts_by_spin_type. "
            f"Got dim-related keys: {[k for k in pbst if 'by_dim' in k or '126' in k]}"
        )

    def test_payouts_by_spin_type_sibling_has_real_values(self, summary):
        """The __by_dim__ sibling must have 'alpha' and 'beta' keys."""
        pbst = _pbst(summary)
        sibling = pbst.get("ST126_free__by_dim__trigger_path", {})
        for val in ("alpha", "beta"):
            assert val in sibling, (
                f"Missing dim value '{val}' in by_dim sibling. Got: {list(sibling)}"
            )

    def test_payouts_by_spin_type_sum_equals_aggregate_payid_basis(self, summary):
        """GAP-B payid basis: Sigma over dim values of Sigma(payid rtp_pp) == aggregate Sigma(payid rtp_pp).

        This is the test that inject-bug IB-1 is designed to catch.
        The proportional-split property guarantees exact equality when shares sum to 1.
        """
        pbst = _pbst(summary)
        agg_rows = pbst.get("ST126_free", [])
        agg_total_rtp = sum(
            float(r.get("rtp_contribution_pp", 0.0)) for r in agg_rows
        )
        sibling = pbst.get("ST126_free__by_dim__trigger_path", {})
        dim_total_rtp = 0.0
        for dv in ("alpha", "beta"):
            dv_rows = sibling.get(dv, [])
            for r in dv_rows:
                dim_total_rtp += float(r.get("rtp_contribution_pp", 0.0))
        assert abs(dim_total_rtp - agg_total_rtp) < 0.001, (
            f"GAP-B payid basis violated: "
            f"Sigma(per-dim rtp_pp)={dim_total_rtp:.6f} != "
            f"aggregate={agg_total_rtp:.6f}"
        )

    def test_spin_type_outcomes_has_by_dim_sub_key(self, summary):
        """spin_type_outcomes ST126_free must have a 'by_dim' sub-key."""
        sto = _sto(summary)
        st126 = sto.get("ST126_free", {})
        assert _has_nested_by_dim(st126), (
            f"Expected 'by_dim' in spin_type_outcomes['ST126_free']. "
            f"Got keys: {list(st126.keys())}"
        )

    def test_spin_type_outcomes_by_dim_sum_equals_aggregate_outcome_basis(self, summary):
        """GAP-B outcome basis: Sigma(per-dim rtp_contribution_pp) == ST126 aggregate rtp_pp.

        Inject-bug IB-1 targets this test: if the by_dim uses the payid basis instead
        of the outcome basis, Sigma(per-dim) != aggregate (bases differ in general).
        """
        sto = _sto(summary)
        st126 = sto.get("ST126_free", {})
        agg_rtp_pp = float(st126.get("rtp_contribution_pp", 0.0))
        by_dim = st126.get("by_dim", {})
        dim_block = by_dim.get("trigger_path", {})
        dim_sum = 0.0
        for dv in ("alpha", "beta"):
            dv_entry = dim_block.get(dv, {})
            dim_sum += float(dv_entry.get("rtp_contribution_pp", 0.0))
        # Formula (dim_win/total_win)*rtp_pp_stb guarantees exact sum==aggregate.
        assert abs(dim_sum - agg_rtp_pp) < 0.001, (
            f"GAP-B outcome basis violated: "
            f"Sigma(per-dim rtp_pp)={dim_sum:.6f} != "
            f"aggregate rtp_pp_stb={agg_rtp_pp:.6f}"
        )

    def test_spin_type_outcomes_by_dim_has_meta_keys(self, summary):
        """by_dim block must have _dim_label and _dim_values meta keys."""
        sto = _sto(summary)
        st126 = sto.get("ST126_free", {})
        by_dim = st126.get("by_dim", {})
        dim_block = by_dim.get("trigger_path", {})
        assert "_dim_label" in dim_block, (
            f"Missing _dim_label in by_dim block. Keys: {list(dim_block)}"
        )
        assert "_dim_values" in dim_block, (
            f"Missing _dim_values in by_dim block. Keys: {list(dim_block)}"
        )
        dim_values = dim_block.get("_dim_values", [])
        assert set(dim_values) == {"alpha", "beta"}, (
            f"Expected _dim_values == {{'alpha','beta'}} (order-agnostic). Got: {dim_values}"
        )

    def test_spin_type_outcomes_by_dim_has_unknown_and_multi_alarm_keys(self, summary):
        """by_dim block must always surface _unknown and _multi as alarm keys."""
        sto = _sto(summary)
        st126 = sto.get("ST126_free", {})
        by_dim = st126.get("by_dim", {})
        dim_block = by_dim.get("trigger_path", {})
        assert "_unknown" in dim_block, "Missing _unknown alarm key in by_dim block"
        assert "_multi" in dim_block, "Missing _multi alarm key in by_dim block"

    def test_reel_marginal_by_spin_type_has_by_dim_sibling(self, summary):
        """reel_marginal_by_spin_type must have 'ST126_free__by_dim__trigger_path' sibling."""
        rmbst = _rmbst(summary)
        sibling_key = "ST126_free__by_dim__trigger_path"
        if "ST126_free" in rmbst:
            assert sibling_key in rmbst, (
                f"Expected '{sibling_key}' in reel_marginal_by_spin_type. "
                f"Got dim-related keys: {[k for k in rmbst if 'by_dim' in k]}"
            )

    def test_aggregate_st_label_unchanged(self, summary):
        """The aggregate ST126_free key in payouts_by_spin_type is a LIST (unchanged shape)."""
        pbst = _pbst(summary)
        agg = pbst.get("ST126_free")
        assert isinstance(agg, list), (
            f"payouts_by_spin_type['ST126_free'] must still be a list. Got: {type(agg)}"
        )

    def test_aggregate_sto_entry_unchanged_fields(self, summary):
        """spin_type_outcomes ST126_free must still have all original top-level fields."""
        sto = _sto(summary)
        st126 = sto.get("ST126_free", {})
        for field in ("spin_type", "label", "hit_rate", "rtp_contribution_pp",
                      "win_bands", "top_combos", "has_payouts"):
            assert field in st126, (
                f"Original field '{field}' missing from spin_type_outcomes['ST126_free']. "
                f"by_dim must be ADDITIVE only."
            )

    # NOTE: freespin_dynamics intentionally emits NO by_dim (Phase 2 critic fix —
    # per-dimension breakdown is the GENERIC per-ST layer's job, not a mechanic
    # plugin's). The removed tests that asserted freespin_dynamics.rtp_concentration.by_dim
    # are replaced by the architecture lock TestRealDataM275.test_freespin_dynamics_emits_no_by_dim.


# ===========================================================================
# Test 2 — Single-value (or no-dimension) ST: NO by_dim key emitted
# ===========================================================================

class TestSingleValueStNoDim:
    """Single-value or no-dimension ST: by_dim/__by_dim__ must be absent.

    This test catches BREAK-1 regression: if the guard checks 'st_extract present'
    instead of 'dimensions sub-key present', a no-dimension machine would still
    emit spurious by_dim keys.
    """

    @pytest.fixture(scope="class")
    def summary_nodim(self) -> dict:
        """Manifest with NO trigger_paths at all."""
        rounds = []
        for _ in range(5):
            rounds.append(_paid(st=1, bet=1000, win=0))
        for _ in range(8):
            rounds.append(_bonus(st=126, win=100))
        return _run_report(rounds, _synth_manifest_nodim())

    def test_nodim_manifest_no_by_dim_key_in_payouts(self, summary_nodim):
        """payouts_by_spin_type must have NO __by_dim__ key for no-dimension manifests."""
        pbst = _pbst(summary_nodim)
        by_dim_keys = [k for k in pbst if "__by_dim__" in k]
        assert not by_dim_keys, (
            f"Spurious __by_dim__ keys emitted for no-dimension manifest: {by_dim_keys}"
        )

    def test_nodim_manifest_no_by_dim_in_outcomes(self, summary_nodim):
        """spin_type_outcomes must have NO by_dim for no-dimension manifests."""
        sto = _sto(summary_nodim)
        for label, entry in sto.items():
            if isinstance(entry, dict) and _has_nested_by_dim(entry):
                pytest.fail(
                    f"Spurious by_dim found in spin_type_outcomes['{label}']. "
                    f"No trigger_paths declared in manifest."
                )

    def test_nodim_reel_marginal_no_by_dim(self, summary_nodim):
        """reel_marginal_by_spin_type must have NO __by_dim__ key for no-dimension manifests."""
        rmbst = _rmbst(summary_nodim)
        by_dim_keys = [k for k in rmbst if "__by_dim__" in k]
        assert not by_dim_keys, (
            f"Spurious __by_dim__ keys in reel_marginal for no-dimension manifest: {by_dim_keys}"
        )


# ===========================================================================
# Test 3 — BREAK-1 guard: signature_audit present, no "dimensions" sub-key
# ===========================================================================

class TestBreak1Guard:
    """BREAK-1 regression: st_extract has signature_audit but NO dimensions sub-key.

    st_extract is always non-empty fleet-wide (signature_audit fires for all 4 machines).
    Every plugin must guard on the precise "dimensions" sub-key inside trigger_path,
    NOT on st_extract presence.

    This test directly injects a chunk_dict with st_extract containing ONLY
    signature_audit (no trigger_path.dimensions) and verifies no by_dim is emitted.
    """

    def _make_chunk_dict_with_signature_audit_only(self) -> dict:
        """Build a minimal chunk_dict simulating M15/M43/M279 state:
        st_extract present (signature_audit) but no trigger_path.dimensions."""
        return {
            "payout_id_by_spin_type": {"10": {"1": 5}},
            "payout_id_win_by_spin_type": {"10": {"1": 5000.0}},
            "payout_id_payline_hits": {},
            "payout_id_match_count_dist": {},
            "payout_id_col_set": {},
            "payout_id_has_regular_line": {"10": True},
            "payout_id_symbol_combos": {},
            "st_extract": {
                # signature_audit is present (fleet-wide — BREAK-1 scenario)
                "signature_audit": {"1": {"fields_observed": ["SpinType", "WinCredits"]}},
                # trigger_path present but NO "dimensions" sub-key
                # (this is the exact state for M15/M43/M279 after Phase 1)
                "trigger_path": {
                    "1": {}  # numeric ST key — no "dimensions" key here
                },
            },
        }

    def test_payouts_extract_no_dim_data_when_no_dimensions_sub_key(self):
        """PayoutsBySpinType.extract() must return empty dim_by_st when no dimensions sub-key.

        INJECT-BUG IB-2: change guard from `_tp_raw.get("dimensions")` to
        `if isinstance(_tp_raw, dict)` → dim_by_st_hits becomes non-empty → RED.
        Revert → GREEN.
        """
        from fresh_slotlab.analyzer.features.payouts_by_spin_type import PayoutsBySpinType

        plugin = PayoutsBySpinType()
        chunk_dict = self._make_chunk_dict_with_signature_audit_only()
        acc = plugin.extract(None, chunk_dict)
        dim_hits = acc.get("dim_by_st_hits", {})
        dim_wins = acc.get("dim_by_st_win", {})
        assert not dim_hits, (
            f"BREAK-1 violation: dim_by_st_hits non-empty when no 'dimensions' sub-key. "
            f"Got: {dim_hits}"
        )
        assert not dim_wins, (
            f"BREAK-1 violation: dim_by_st_win non-empty when no 'dimensions' sub-key. "
            f"Got: {dim_wins}"
        )

    def test_spin_type_outcomes_extract_no_dim_data_when_no_dimensions_sub_key(self):
        """SpinTypeOutcomes.extract() must return empty dim dicts when no dimensions sub-key."""
        from fresh_slotlab.analyzer.features.spin_type_outcomes import SpinTypeOutcomes

        plugin = SpinTypeOutcomes()
        chunk_dict = self._make_chunk_dict_with_signature_audit_only()
        acc = plugin.extract(None, chunk_dict)
        rc = acc.get("dim_round_count", {})
        wrc = acc.get("dim_win_round_count", {})
        assert not rc, (
            f"BREAK-1 violation: dim_round_count non-empty when no 'dimensions' sub-key. Got: {rc}"
        )
        assert not wrc, (
            f"BREAK-1 violation: dim_win_round_count non-empty when no 'dimensions' sub-key. Got: {wrc}"
        )

    def test_reel_marginal_extract_no_dim_data_when_no_dimensions_sub_key(self):
        """ReelMarginalBySpinType.extract() must return empty dim_symbol_counts when no dimensions sub-key."""
        from fresh_slotlab.analyzer.features.reel_marginal_by_spin_type import ReelMarginalBySpinType

        plugin = ReelMarginalBySpinType()
        chunk_dict = self._make_chunk_dict_with_signature_audit_only()
        acc = plugin.extract(None, chunk_dict)
        dsc = acc.get("dim_symbol_counts", {})
        assert not dsc, (
            f"BREAK-1 violation: dim_symbol_counts non-empty when no 'dimensions' sub-key. Got: {dsc}"
        )

    def test_no_crash_with_signature_audit_only(self):
        """All extract() calls must not crash when st_extract has only signature_audit."""
        from fresh_slotlab.analyzer.features.payouts_by_spin_type import PayoutsBySpinType
        from fresh_slotlab.analyzer.features.spin_type_outcomes import SpinTypeOutcomes
        from fresh_slotlab.analyzer.features.reel_marginal_by_spin_type import ReelMarginalBySpinType
        from fresh_slotlab.analyzer.features.freespin_dynamics import FreespinDynamics

        chunk_dict = self._make_chunk_dict_with_signature_audit_only()
        for plugin_cls in (PayoutsBySpinType, SpinTypeOutcomes, ReelMarginalBySpinType, FreespinDynamics):
            plugin = plugin_cls()
            plugin.extract(None, chunk_dict)  # must not raise


# ===========================================================================
# Test 4 — ">=2 real values" guard: degenerate single-value (at runtime)
# ===========================================================================

class TestDegenerateSingleValue:
    """Manifest declares 2 values, but all observed rounds map to ONLY 1 value.

    Guard: if only 1 real (non-unknown, non-multi) value is observed,
    NO by_dim/__by_dim__ key must be emitted.
    """

    @pytest.fixture(scope="class")
    def summary(self) -> dict:
        """2-value manifest but all rounds have FieldX=0 (only alpha observed)."""
        rounds = []
        for _ in range(5):
            rounds.append(_paid(st=1, bet=1000, win=0))
        # All 8 bonus rounds use FieldX=0 (alpha) — beta is declared but not observed.
        for _ in range(8):
            rounds.append(_bonus(st=126, win=100, field_x=0))
        return _run_report(rounds, _synth_manifest_2val(machine_id="M_synth_1obs"))

    def test_degenerate_single_value_no_by_dim_in_payouts(self, summary):
        """When only 1 real value observed, __by_dim__ must NOT be emitted."""
        pbst = _pbst(summary)
        by_dim_keys = [k for k in pbst if "__by_dim__" in k]
        assert not by_dim_keys, (
            f"Spurious __by_dim__ keys emitted for degenerate single-value: {by_dim_keys}. "
            f"'>=2 real values' guard not enforced."
        )

    def test_degenerate_single_value_no_by_dim_in_outcomes(self, summary):
        """When only 1 real value observed, by_dim must NOT be in spin_type_outcomes."""
        sto = _sto(summary)
        for label, entry in sto.items():
            if isinstance(entry, dict) and _has_nested_by_dim(entry):
                pytest.fail(
                    f"Spurious by_dim in spin_type_outcomes['{label}'] for single-value data. "
                    f"'>=2 real values' guard not enforced."
                )


# ===========================================================================
# Test 5 — unknown/multi excluded from real-values count but surfaced
# ===========================================================================

class TestUnknownMultiHandling:
    """Unknown/multi values are excluded from the >=2-real-values count
    but SURFACED as _unknown/_multi alarm buckets in the by_dim block.

    Specifically: 5 alpha, 3 beta, 2 rounds with FieldX=99 (unmapped -> unknown:99).
    -> >=2 real values (alpha, beta) -> by_dim IS emitted.
    -> _unknown must be in the by_dim block as an alarm key.
    """

    @pytest.fixture(scope="class")
    def summary(self) -> dict:
        rounds = []
        for _ in range(5):
            rounds.append(_paid(st=1, bet=1000, win=0))
        for _ in range(5):
            rounds.append(_bonus(st=126, win=100, field_x=0))   # alpha
        for _ in range(3):
            rounds.append(_bonus(st=126, win=100, field_x=1))   # beta
        for _ in range(2):
            rounds.append(_bonus(st=126, win=100, field_x=99))  # -> unknown:99
        return _run_report(rounds, _synth_manifest_2val(machine_id="M_synth_unk"))

    def test_by_dim_emitted_despite_unknowns(self, summary):
        """by_dim IS emitted because >=2 real values (alpha, beta) present."""
        pbst = _pbst(summary)
        sibling = "ST126_free__by_dim__trigger_path"
        assert sibling in pbst, (
            f"Expected by_dim emitted for 2 real values despite unknowns. "
            f"Keys: {[k for k in pbst if 'by_dim' in k]}"
        )

    def test_unknown_not_in_real_dim_values(self, summary):
        """_dim_values in the by_dim block must contain ONLY real values (not unknown:*)."""
        sto = _sto(summary)
        st126 = sto.get("ST126_free", {})
        by_dim = st126.get("by_dim", {})
        dim_block = by_dim.get("trigger_path", {})
        dim_values = dim_block.get("_dim_values", [])
        unknowns_in_values = [v for v in dim_values if str(v).startswith("unknown:")]
        assert not unknowns_in_values, (
            f"unknown:* values appear in _dim_values: {unknowns_in_values}. "
            f"They must be excluded from the real-values list."
        )
        assert set(dim_values) == {"alpha", "beta"}, (
            f"Expected _dim_values == {{'alpha','beta'}}. Got: {dim_values}"
        )

    def test_unknown_surfaced_as_alarm_key(self, summary):
        """_unknown alarm key must be in the by_dim block when unknowns are present."""
        sto = _sto(summary)
        st126 = sto.get("ST126_free", {})
        by_dim = st126.get("by_dim", {})
        dim_block = by_dim.get("trigger_path", {})
        assert "_unknown" in dim_block, (
            f"'_unknown' alarm key absent from by_dim block despite unknown:99 rounds. "
            f"Keys: {list(dim_block)}"
        )

    def test_reel_marginal_surfaces_unknown_excluded_alarm(self, summary):
        """SHIP-BLOCKER fix (Phase 2 critic): reel_marginal excludes unknown:* rounds
        from per-dim symbol_counts (they carry mixed-path data) but MUST surface the
        excluded count as an explicit alarm key — never a silent drop
        (feedback_invariant_with_fallback_hides_drift)."""
        rm = _rmbst(summary)
        sibling = "ST126_free__by_dim__trigger_path"
        assert sibling in rm, (
            f"reel_marginal __by_dim__ sibling absent. Keys: {[k for k in rm if 'by_dim' in k]}"
        )
        block = rm[sibling]
        assert "_unknown_excluded_count" in block, (
            f"reel_marginal must surface '_unknown_excluded_count' for the 2 unknown:99 "
            f"rounds (no silent drop). Keys: {list(block)}"
        )
        assert int(block["_unknown_excluded_count"]) == 2, (
            f"expected 2 excluded unknown rounds, got {block.get('_unknown_excluded_count')}"
        )


# ===========================================================================
# Test 6 — Real-data M275 (skipif rawdata absent)
# ===========================================================================

class TestRealDataM275:
    """Real M275 report regression: GAP-B Sigma==aggregate on real data.

    Verifies (value-agnostically):
    (a) spin_type_outcomes ST126 Sigma per-dim rtp_pp == aggregate (outcome basis)
    (b) payouts __by_dim__ Sigma == aggregate (payid basis)
    (c) freespin rtp_concentration.by_dim both bases each sum to their aggregate
    (d) trigger_paths table still present + unchanged shape (additive proof)
    (e) integrity passed + session_conservation ok

    The exact Sigma values observed are reported at the end for human review,
    but are NOT pinned as literals (values drift on re-sample).
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
    def test_session_conservation_ok(self, summary):
        ric = summary.get("rtp_integrity_check", {})
        sc = ric.get("session_conservation_level")
        assert sc == "ok", (
            f"session_conservation_level is not 'ok': {sc}"
        )

    @SKIP_NO_M275
    def test_spin_type_outcomes_by_dim_sum_equals_aggregate_outcome_basis(self, summary):
        """GAP-B outcome basis: Sigma(per-dim rtp_pp) == ST126 aggregate rtp_pp."""
        sto = _sto(summary)
        st126 = sto.get(_FS_LABEL, {})
        assert st126, f"spin_type_outcomes has no entry for '{_FS_LABEL}'"
        agg_rtp_pp = float(st126.get("rtp_contribution_pp", 0.0))
        by_dim = st126.get("by_dim", {})
        assert by_dim, (
            f"spin_type_outcomes['{_FS_LABEL}'] has no 'by_dim' sub-key. "
            f"Phase 2 by_dim emission failed for M275."
        )
        dim_block = by_dim.get(_DIM_NAME, {})
        dim_sum = 0.0
        for dv in ("scatter", "collect_peak"):
            dv_entry = dim_block.get(dv, {})
            dim_sum += float(dv_entry.get("rtp_contribution_pp", 0.0))
        print(f"\n[M275 GAP-B outcome] Sigma per-dim={dim_sum:.6f} | aggregate={agg_rtp_pp:.6f}")
        assert abs(dim_sum - agg_rtp_pp) < 0.01, (
            f"GAP-B outcome basis violated on real M275 data: "
            f"Sigma(per-dim rtp_pp)={dim_sum:.6f} != aggregate={agg_rtp_pp:.6f}"
        )

    @SKIP_NO_M275
    def test_payouts_by_dim_sum_equals_aggregate_payid_basis(self, summary):
        """GAP-B payid basis: Sigma __by_dim__ Sigma(rtp_pp) == aggregate Sigma(rtp_pp)."""
        pbst = _pbst(summary)
        sibling_key = f"{_FS_LABEL}__by_dim__{_DIM_NAME}"
        assert sibling_key in pbst, (
            f"payouts_by_spin_type has no '{sibling_key}' sibling key. "
            f"Phase 2 by_dim emission failed for M275."
        )
        agg_rows = pbst.get(_FS_LABEL, [])
        agg_total = sum(float(r.get("rtp_contribution_pp", 0.0)) for r in agg_rows)
        sibling = pbst[sibling_key]
        dim_total = 0.0
        for dv in ("scatter", "collect_peak"):
            dv_rows = sibling.get(dv, [])
            for r in dv_rows:
                dim_total += float(r.get("rtp_contribution_pp", 0.0))
        print(f"\n[M275 GAP-B payid] Sigma per-dim={dim_total:.6f} | aggregate={agg_total:.6f}")
        assert abs(dim_total - agg_total) < 0.01, (
            f"GAP-B payid basis violated on real M275 data: "
            f"Sigma(per-dim payid rtp_pp)={dim_total:.6f} != aggregate={agg_total:.6f}"
        )

    @SKIP_NO_M275
    def test_freespin_dynamics_by_dim_only_on_own_metrics(self, summary):
        """ARCHITECTURE LOCK (Phase 2 critic fix, REFINED in Phase 3): the
        per-dimension split of GENERIC per-ST metrics (hit-rate / RTP / payid /
        reel) is the generic layer's job — freespin_dynamics must NOT re-derive
        it on the generic-overlap sections. But freespin_dynamics MAY own the
        by_dim of its OWN freespin-specific metrics that no generic plugin can
        compute (ER ladder / FS-index arc / session tiers, added in Phase 3).
        This locks the boundary: by_dim ALLOWED only on those 3 sections."""
        fsd = _fsd(summary)
        _ALLOWED = {"er_ladder", "fs_index_arc", "session_tier_distribution"}
        offenders = [sec for sec, block in fsd.items()
                     if isinstance(block, dict) and "by_dim" in block
                     and sec not in _ALLOWED]
        assert not offenders, (
            f"freespin_dynamics emitted by_dim on a GENERIC-overlap section "
            f"(that is the generic layer's job): {offenders}. by_dim is allowed "
            f"only on freespin-specific sections {sorted(_ALLOWED)}."
        )

    @SKIP_NO_M275
    def test_trigger_paths_table_still_present_unchanged_shape(self, summary):
        """Additive proof: trigger_paths section in freespin_dynamics still present and valid."""
        fsd = _fsd(summary)
        tp = fsd.get("trigger_paths", {})
        assert tp.get("available") is True, (
            f"freespin_dynamics.trigger_paths.available is not True: {tp.get('available')}. "
            f"Phase 2 must be ADDITIVE — existing F6 block must remain."
        )
        paths = tp.get("paths", [])
        path_labels = {p.get("path") for p in paths}
        assert "scatter" in path_labels, (
            f"'scatter' path missing from trigger_paths.paths: {path_labels}"
        )
        assert "collect_peak" in path_labels, (
            f"'collect_peak' path missing from trigger_paths.paths: {path_labels}"
        )

    @SKIP_NO_M275
    def test_additive_no_by_dim_on_non_freespin_sts(self, summary):
        """Non-freespin STs (ST140) must not gain by_dim keys (ADDITIVE only)."""
        sto = _sto(summary)
        for label, entry in sto.items():
            if "140" in label and isinstance(entry, dict):
                assert not _has_nested_by_dim(entry), (
                    f"by_dim unexpectedly present in non-freespin ST '{label}'. "
                    f"Phase 2 must be ADDITIVE to declared STs only."
                )

    @SKIP_NO_M275
    def test_payouts_no_by_dim_for_st140(self, summary):
        """payouts_by_spin_type must not have __by_dim__ for ST140."""
        pbst = _pbst(summary)
        bad = [k for k in pbst if "__by_dim__" in k and "140" in k]
        assert not bad, (
            f"Spurious __by_dim__ keys for ST140: {bad}. Phase 2 is ADDITIVE only."
        )


# ===========================================================================
# Test 7 — Frontend contract: app.js keys + pure.js i18n
# ===========================================================================

class TestFrontendContract:
    """Contract: the keys _stDimGenericDimension reads in app.js must match what
    the plugins emit; the i18n keys it uses must exist in pure.js both locales.

    Per feedback_no_parallel_panel_impl.md: frontend renderers must reuse existing
    helpers and i18n keys — no parallel implementation.
    """

    _APP_JS = ROOT / "src" / "web_console" / "frontend" / "app.js"
    _PURE_JS = ROOT / "src" / "web_console" / "frontend" / "pure.js"

    @pytest.fixture(scope="class")
    def app_js_text(self) -> str:
        return self._APP_JS.read_bytes().decode("utf-8", errors="replace")

    @pytest.fixture(scope="class")
    def pure_js_text(self) -> str:
        return self._PURE_JS.read_bytes().decode("utf-8", errors="replace")

    def test_app_js_reads_outcome_by_dim(self, app_js_text):
        """app.js must read outcome.by_dim (spin_type_outcomes[label].by_dim)."""
        assert "outcome.by_dim" in app_js_text, (
            "app.js does not read 'outcome.by_dim' — "
            "the frontend contract for spin_type_outcomes Phase 2 is missing."
        )

    def test_app_js_reads_sibling_key_pattern(self, app_js_text):
        """app.js must build the '<label>__by_dim__<dimName>' sibling key."""
        assert "__by_dim__" in app_js_text, (
            "app.js does not contain '__by_dim__' — "
            "the payouts_by_spin_type sibling key pattern is missing."
        )

    def test_app_js_stDimGenericDimension_registered(self, app_js_text):
        """_stDimGenericDimension must be registered in SPINTYPE_DIMENSIONS."""
        assert "_stDimGenericDimension" in app_js_text, (
            "_stDimGenericDimension function not found in app.js"
        )
        spintype_dims_idx = app_js_text.find("SPINTYPE_DIMENSIONS")
        assert spintype_dims_idx >= 0, "SPINTYPE_DIMENSIONS not found in app.js"
        after_idx = app_js_text.find("_stDimGenericDimension", spintype_dims_idx)
        assert after_idx >= 0, (
            "_stDimGenericDimension not found after SPINTYPE_DIMENSIONS in app.js"
        )

    def test_i18n_dim_keys_present_in_both_locales(self, pure_js_text):
        """All dim* i18n keys used by _stDimGenericDimension must exist in both zh and en.

        pure.js uses unquoted JS object key syntax: 'dimColMetric:' not '"dimColMetric"'.
        The keys must appear at least twice (once per locale: zh + en).
        """
        required_keys = [
            "dimColMetric",
            "dimRowHitRate",
            "dimRowDeadSpinRate",
            "dimRowRtpPp",
            "dimRowRounds",
            "stoPayidTitle",
        ]
        for key in required_keys:
            # Keys in pure.js appear as bare JS object keys: "dimColMetric:"
            count = pure_js_text.count(f"{key}:")
            assert count >= 2, (
                f"i18n key '{key}' appears {count} time(s) in pure.js (as '{key}:') — "
                f"expected >=2 (once per locale: zh + en). "
                f"The key is used by _stDimGenericDimension in app.js."
            )

    def test_app_js_reads_dim_values_list(self, app_js_text):
        """app.js must read _dim_values from the by_dim block."""
        assert "_dim_values" in app_js_text, (
            "app.js does not read '_dim_values' from the by_dim block. "
            "This list drives the side-by-side column rendering."
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
# Test — base_hash unchanged (Phase 2 must NOT touch closure files)
# ===========================================================================

class TestBaseHashUnchanged:
    """Phase 2 must not change base_hash. All plugin edits are base-excluded.

    Expected base_hash: c5d2199142c3 (confirmed correct import path via test suite).
    """

    def test_base_hash_is_current_baseline(self):
        """compute_base_analyzer_version() must return the current baseline
        5900f0deb2ad (re-baselined 2026-06-22 by the DELIBERATE pluggable
        round_win rule-engine refactor: the 4 rule TYPE classes + RULE_REGISTRY
        moved out of fresh_slotlab/round_win.py into the base-EXCLUDED
        fresh_slotlab/round_win_rules/ package, and round_win_rules/__init__.py
        was added to _CLOSURE_FILES. This is the LAST base_hash flip for rule
        types — adding/editing a rule type is now base-excluded. Prior:
        bba689d50f03 (SettlementWinAmountRule.settlement_label_format param);
        was d9fa4625b956 derive-from-data routing).

        If this fails, a closure file (_CLOSURE_FILES in versioning.py) was
        accidentally modified (or a new deliberate closure change needs this
        baseline updated). Plugin/rule-type edits themselves are base-EXCLUDED.
        """
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        bh = compute_base_analyzer_version()
        assert bh == "5900f0deb2ad", (
            f"base_hash changed from the 5900f0deb2ad baseline to {bh!r}. "
            f"A base_hash change means a closure file (_CLOSURE_FILES) was "
            f"accidentally modified (or a deliberate closure change needs this updated)."
        )


# ===========================================================================
# Additive gate — M15/M43/M279 emit NO by_dim keys (ADDITIVE proof)
# ===========================================================================

class TestAdditiveGate:
    """The additive gate: M15, M43, M279 produce NO by_dim/__by_dim__ keys.

    These machines declare no dimensions, so Phase 2 is a no-op for them.
    This is the core additive-only proof without relying on stale byte-identical
    golden files.
    """

    _RAWDATA = ROOT / "rawdata"

    _CASES = [
        ("M15", 1, 1000),
        ("M43", 1, 1000),
        ("M43", 7, 1000),
        ("M279", 1, 1000),
    ]

    @pytest.mark.parametrize("machine,mode,bet", _CASES)
    def test_no_by_dim_keys_for_nodim_machine(self, machine, mode, bet):
        """Run a real report on M15/M43/M279 and verify NO by_dim/__by_dim__ keys appear.

        Phase 2 is ADDITIVE: machines without declared dimensions must produce
        zero dimension-split output.
        """
        chunk_dir = self._RAWDATA / machine / f"mode_{mode}"
        if not list(chunk_dir.glob("chunk_*.json")):
            # dir may exist but be empty (e.g. mode_7 chunks not cached on this checkout) —
            # the report engine raises on no chunks, so skip rather than spuriously fail.
            pytest.skip(f"rawdata/{machine}/mode_{mode} has no cached chunks")

        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmp:
            summary = generate_report_from_chunks(
                machine, mode,
                chunk_dir=chunk_dir,
                output_dir=Path(tmp),
                bet=bet,
            )

        # payouts_by_spin_type: NO __by_dim__ keys.
        pbst = _pbst(summary)
        pbst_dim_keys = [k for k in pbst if "__by_dim__" in k]
        assert not pbst_dim_keys, (
            f"{machine}/mode_{mode}: Spurious __by_dim__ keys in payouts_by_spin_type: "
            f"{pbst_dim_keys}. Phase 2 additive-only contract broken."
        )

        # spin_type_outcomes: NO by_dim sub-keys.
        sto = _sto(summary)
        for label, entry in sto.items():
            if isinstance(entry, dict) and _has_nested_by_dim(entry):
                pytest.fail(
                    f"{machine}/mode_{mode}: Spurious by_dim in spin_type_outcomes['{label}']. "
                    f"Phase 2 additive-only contract broken."
                )

        # reel_marginal_by_spin_type: NO __by_dim__ keys.
        rmbst = _rmbst(summary)
        rmbst_dim_keys = [k for k in rmbst if "__by_dim__" in k]
        assert not rmbst_dim_keys, (
            f"{machine}/mode_{mode}: Spurious __by_dim__ keys in reel_marginal_by_spin_type: "
            f"{rmbst_dim_keys}. Phase 2 additive-only contract broken."
        )
