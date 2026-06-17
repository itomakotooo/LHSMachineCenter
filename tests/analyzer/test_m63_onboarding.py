"""M63 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares / count-histograms — money
amounts do NOT matter. This file asserts STRUCTURE / DETERMINISM / ATTRIBUTION /
ISOLATION / HONESTY invariants, NEVER an RTP value or range. M63's numbers (RTP,
nudge hit-rate, win-rate uplift, slide-offset counts, per-column counts) change
on re-sample / re-tune / upstream drift; pinning ANY of them would be a brittle
false alarm (charter permanent invariant 1).

The ONLY hard constants asserted are STRUCTURAL identifiers fixed by the manifest
/ rawdata protocol (the SpinType id 1, the declared crazy-symbol family, the
5-offset slide signature, the 3-reel grid) — and even those are read from the
manifest where possible (the nudge ST is the ST that DECLARES crazy_reel, never a
hardcoded "1"). Every numeric relation asserted is INTERNAL CONSISTENCY (a count
equals the sum of its parts; a rate equals num/den; ordering is determined) — not
a pinned value.

What M63 shipped (session_artifacts/_onboard/M63/03_design.md + the manifest):
  - configs/machine_manifests/M63.json — single ST1 paid_spin/Normal, with a
    `crazy_reel` dimension-declaration block on ST1 (the nudge data source).
  - fresh_slotlab/analyzer/st_extract/crazy_reel_dim.py (NEW base-excluded
    extractor) — parser-blind reel-nudge geometry scan of StopSymbolsByCol.
  - fresh_slotlab/analyzer/features/nudge_dynamics.py (NEW base-excluded consumer
    plugin, RTP_CONTRIBUTION=False) — the N1-N6 felt-experience metric set.
  - machine_spec.DIMENSION_ANALYSES = {"crazy_reel": ("nudge_dynamics",)} + a
    dimension-declaration branch in derive_analyses (the non-leaking hook: M63's
    fleet-generic paid_spin role / Normal play cannot scope the analysis).
  - round_win_rule: null (payids attribute 100%, fallback 0; no synthesize rule).

The whole test runs the REAL engine on the real cached chunk at rawdata/M63/mode_1
(charter invariant 3: run the real thing, pass bet=chunk _bet, read the real
summary). It NEVER trusts an exit code / GREEN.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M63_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M63" / "mode_1"
_M63_MANIFEST = _REPO_ROOT / "configs" / "machine_manifests" / "M63.json"
_MANIFESTS_ROOT = _REPO_ROOT / "configs" / "machine_manifests"

# The bet used during M63 sampling (chunk _bet=1000). The report is
# value-agnostic; bet only affects coin totals, which this test never asserts.
# (Charter M279 trap: bet must land in sampling.bet so per-ST multipliers are
# sane — but we never assert a multiplier VALUE.)
_BET = 1000

# The dimension-declaration key that is the WHOLE isolation mechanism (extractor
# DECLARED_IN_KEY + machine_spec.DIMENSION_ANALYSES hook). M63 is the only
# machine that declares it.
_CRAZY_REEL_KEY = "crazy_reel"
_NUDGE_FEATURE = "nudge_dynamics"
_CRAZY_EXTRACTOR_ID = "crazy_reel_dim"

# The 12-plugin reused set + nudge_dynamics (design §8). Asserted as a SET so a
# leak (extra plugin) or a drop (missing plugin) is caught, never a value.
_EXPECTED_M63_ANALYSES = frozenset({
    "bankruptcy_simulation",
    "bonus_chain_dynamics",
    "collect_mechanic",
    "machine_mechanics",
    "multiplier_profile",
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "spin_type_outcomes",
    "spin_type_rtp_buckets",
    "structure_drift",
    "upstream_feature_breakdown",
    "nudge_dynamics",
})

# Frontend-contract player_impact keys the console paint path reads (the schema
# contract — presence, not values).
_FRONTEND_CONTRACT_KEYS = (
    "spin_type_breakdown",
    "spin_type_outcomes",
    "payouts_by_spin_type",
    "payout_ids_top20",
    "multiplier_profile",
    "nudge_dynamics",
)

# Machines that must NOT gain nudge_dynamics (non-leak peers — at least one base
# game / Normal-play machine to prove the role/play hooks are NOT used).
_NON_DECLARING_PEERS = ("M15", "M43", "M104", "M275", "M279", "M283")


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m63_summary():
    if not _has_chunks(_M63_CHUNK_DIR):
        pytest.skip("M63 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            "M63", 1,
            chunk_dir=_M63_CHUNK_DIR,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists(), (
            "write_summary_json must produce player_impact_summary.json"
        )
        yield summary


@pytest.fixture(scope="module")
def m63_player_impact(m63_summary):
    return m63_summary["player_impact"]


@pytest.fixture(scope="module")
def m63_nudge(m63_player_impact):
    nd = m63_player_impact.get(_NUDGE_FEATURE)
    assert isinstance(nd, dict), "nudge_dynamics section missing"
    return nd


@pytest.fixture(scope="module")
def m63_manifest():
    if not _M63_MANIFEST.exists():
        pytest.skip("M63 manifest not present")
    return json.loads(_M63_MANIFEST.read_text(encoding="utf-8"))


def _payout_ids(summary) -> list[str]:
    return [
        str(r.get("payout_id", ""))
        for r in summary["player_impact"].get("payout_ids_top20", [])
    ]


def _nudge_st(manifest) -> int:
    """The nudge ST = the ST that DECLARES crazy_reel (never hardcoded)."""
    for st_key, spec in (manifest.get("spin_types") or {}).items():
        if isinstance(spec, dict) and isinstance(spec.get(_CRAZY_REEL_KEY), dict):
            blk = spec[_CRAZY_REEL_KEY].get("spin_type")
            return int(blk) if blk is not None else int(st_key)
    raise AssertionError("no ST declares crazy_reel in the M63 manifest")


# ---------------------------------------------------------------------------
# 0. Smoke — report generates, no feature errors, frontend-contract keys present.
# ---------------------------------------------------------------------------

class TestReportGenerates:
    def test_machine_and_mode(self, m63_summary):
        assert m63_summary["machine"] == "M63"
        assert m63_summary["mode"] == 1
        assert m63_summary["sampling"]["chunks"] > 0
        assert m63_summary["sampling"]["total_spins"] > 0
        assert not m63_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m63_summary.get('feature_errors')}"
        )

    def test_bet_landed_in_sampling(self, m63_summary):
        """The M279 bet trap: bet must land in sampling.bet so the frontend's
        '× bet' columns divide by the right denominator (no 1000× inflation).
        VALUE-AGNOSTIC: we assert bet round-tripped == what we passed, not a
        multiplier value."""
        assert m63_summary["sampling"]["bet"] == _BET, (
            f"bet must round-trip into sampling.bet (={_BET}); got "
            f"{m63_summary['sampling'].get('bet')} — the '× bet' columns would "
            f"render inflated"
        )

    def test_frontend_contract_keys_present(self, m63_player_impact):
        """Every frontend-contract player_impact key the console paint path reads
        is present (schema contract — presence, not values)."""
        for key in _FRONTEND_CONTRACT_KEYS:
            assert key in m63_player_impact, (
                f"frontend-contract key '{key}' missing from player_impact; the "
                f"console paint path would render a blank section"
            )

    def test_single_paid_spin_type(self, m63_player_impact, m63_manifest):
        """M63 mode_1 is a SINGLE paid base-game SpinType (the design headline).
        The breakdown carries exactly one ST row, the declared nudge ST."""
        stb = m63_player_impact["spin_type_breakdown"]
        assert isinstance(stb, list) and len(stb) == 1, (
            f"M63 mode_1 is single-ST; spin_type_breakdown must have 1 row, got "
            f"{[r.get('spin_type') for r in stb]}"
        )
        assert int(stb[0]["spin_type"]) == _nudge_st(m63_manifest)


# ---------------------------------------------------------------------------
# 1. MANIFEST DECLARATION — the crazy_reel dimension block is the data source.
# ---------------------------------------------------------------------------

class TestManifestDeclaration:
    def test_single_st_role_play_fleet_generic(self, m63_manifest):
        """The load-bearing design fact: M63's only ST is the FLEET-GENERIC
        role paid_spin + play Normal — so neither a role nor a play hook can
        scope the nudge analysis (it would cross-fire). This is WHY the
        dimension-declaration hook exists."""
        sts = m63_manifest["spin_types"]
        assert len(sts) == 1, "M63 mode_1 declares a single SpinType"
        st1 = sts[str(_nudge_st(m63_manifest))]
        assert st1["role"] == "paid_spin", (
            "M63 ST role must be the fleet-generic paid_spin (the reason the hook "
            "is dimension-keyed, not role-keyed)"
        )
        assert st1["play"] == "Normal", (
            "M63 ST play must be the fleet-generic Normal (the reason the hook "
            "is dimension-keyed, not play-keyed)"
        )

    def test_crazy_reel_block_present_and_well_formed(self, m63_manifest):
        st1 = m63_manifest["spin_types"][str(_nudge_st(m63_manifest))]
        cr = st1.get(_CRAZY_REEL_KEY)
        assert isinstance(cr, dict), "ST1 must declare a crazy_reel block"
        # The symbol family is DECLARED (no hardcode in the extractor).
        syms = cr.get("symbols")
        assert isinstance(syms, list) and len(syms) >= 1, (
            "crazy_reel.symbols must be a non-empty declared list (the nudge "
            "family — declared so the extractor hardcodes nothing)"
        )
        # The reel field is declared as the LIST-of-column-strings form (the M63
        # reality the trigger_path extractor's dict-assumption would miss).
        assert cr.get("reel_field_kind") == "list_of_col_strings"
        assert isinstance(cr.get("reel_field"), str) and cr["reel_field"]
        assert isinstance(cr.get("win_field"), str) and cr["win_field"]

    def test_round_win_rule_null_no_synthesize(self, m63_manifest):
        """No SynthesizePayIdRule (design §6): the single ST carries its own
        payids; the nudge symbols never carry a pid, so attribution is 100% real
        — a synthesize rule would invent a phantom pid."""
        assert m63_manifest.get("round_win_rule") is None, (
            "M63 must have round_win_rule: null — payids attribute 100%, no "
            "synthesize rule (the L2 fallback bucket is empty)"
        )

    def test_modes_restricted_to_cached(self, m63_manifest):
        """Modes restricted to [1] (the only cached mode) — extend on data,
        never by assumption (gate-8 discipline)."""
        assert m63_manifest["modes"] == [1]


# ---------------------------------------------------------------------------
# 2. DERIVE_ANALYSES — exactly the 11 reused + nudge_dynamics (12), no leak.
# ---------------------------------------------------------------------------

class TestDeriveAnalyses:
    @staticmethod
    def _derived(machine: str) -> set[str]:
        from fresh_slotlab.analyzer.machine_spec import load_manifest, derive_analyses
        return set(derive_analyses(load_manifest(machine, _MANIFESTS_ROOT)))

    def test_m63_analysis_set_is_reused_plus_nudge(self):
        """derive_analyses(M63) == the 11-plugin reused set + nudge_dynamics.
        Asserting the exact SET catches both a leak (extra) and a drop (missing
        reused plugin)."""
        derived = self._derived("M63")
        assert derived == set(_EXPECTED_M63_ANALYSES), (
            f"M63 derived set != expected; diff "
            f"extra={derived - set(_EXPECTED_M63_ANALYSES)} "
            f"missing={set(_EXPECTED_M63_ANALYSES) - derived}"
        )

    def test_nudge_attached_via_dimension_key_not_role_or_play(self):
        """nudge_dynamics attaches because ST1 declares crazy_reel — provable by
        removing the dimension key in a manifest copy (the analysis vanishes)
        while role/play are unchanged. This is the inject-bug for the HOOK."""
        from fresh_slotlab.analyzer.machine_spec import load_manifest, derive_analyses
        manifest = load_manifest("M63", _MANIFESTS_ROOT)
        assert _NUDGE_FEATURE in set(derive_analyses(manifest))
        # Strip the dimension key (role/play untouched) — nudge must vanish.
        import copy
        stripped = copy.deepcopy(manifest)
        for spec in stripped["spin_types"].values():
            spec.pop(_CRAZY_REEL_KEY, None)
        stripped_derived = set(derive_analyses(stripped))
        assert _NUDGE_FEATURE not in stripped_derived, (
            "nudge_dynamics must attach ONLY via the crazy_reel dimension key; "
            "with the key stripped (role paid_spin / play Normal unchanged) it "
            "must NOT attach — proving it is NOT role/play-hooked"
        )


# ---------------------------------------------------------------------------
# 3. EXTRACTOR WIRING — crazy_reel_dim configured for the nudge ST only.
# ---------------------------------------------------------------------------

class TestExtractorWiring:
    def test_crazy_reel_extractor_configured_for_nudge_st(self, m63_manifest):
        from fresh_slotlab.analyzer.st_extract import (
            discover_extractors, get_extractors_for_manifest,
        )
        discover_extractors()
        exts = get_extractors_for_manifest(m63_manifest)
        ext_ids = [e.EXTRACTOR_ID for e in exts]
        assert _CRAZY_EXTRACTOR_ID in ext_ids, (
            f"M63 must configure the crazy_reel_dim extractor; got {ext_ids}"
        )
        cre = next(e for e in exts if e.EXTRACTOR_ID == _CRAZY_EXTRACTOR_ID)
        assert set(cre._st_declarations.keys()) == {_nudge_st(m63_manifest)}, (
            f"crazy_reel_dim must be configured for the nudge ST only; got "
            f"{sorted(cre._st_declarations.keys())}"
        )


# ---------------------------------------------------------------------------
# 4. ATTRIBUTION / INTEGRITY — sum(payid)==summary, ZERO fallback bucket.
# ---------------------------------------------------------------------------

class TestAttributionIntegrity:
    def test_rtp_integrity_passes(self, m63_summary):
        ric = m63_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M63 mode 1; got "
            f"passed={ric.get('passed')}, message={ric.get('summary_message','N/A')}"
        )

    def test_layer1_sum_invariant_holds(self, m63_summary):
        ric = m63_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant (sum==our_total) broken: {ric.get('layer1_error')}"
        )

    def test_no_unattributed_fallback_bucket(self, m63_summary):
        """Headline value-agnostic guard: NO _unattributed_* fallback bucket
        (Layer-2). The fallback SHARE is 0 — the bucket label is the alarm
        signal, not an account-closing mechanism
        (feedback_invariant_with_fallback_hides_drift.md)."""
        ric = m63_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}"
        )
        assert not (ric.get("layer2_fallback_buckets_found") or []), (
            "M63 must have ZERO fallback buckets (single ST carries its own payids)"
        )
        pids = _payout_ids(m63_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )

    def test_payid_rtp_sum_equals_summary_rtp(self, m63_summary):
        """Aggregator parity: sum(payid.rtp_contribution_pp) == summary RTP
        (feedback_aggregator_parity_invariant.md). Asserting EQUALITY of two
        views of the SAME RTP is value-agnostic — it holds whatever the RTP is."""
        pi = m63_summary["player_impact"]
        pids = pi.get("payout_ids_top20", [])
        assert pids, "M63 must surface payout ids"
        pid_sum = sum(float(p.get("rtp_contribution_pp", 0.0)) for p in pids)
        summary_rtp = float(m63_summary["rtp"]["point_pct"])
        assert pid_sum == pytest.approx(summary_rtp, abs=1e-6), (
            f"sum(payid.rtp_pp) ({pid_sum}) must equal summary RTP ({summary_rtp}) "
            f"— the aggregator-parity invariant, independent of the value"
        )

    def test_nudge_rtp_contribution_is_subshare_not_whole_st(self, m63_player_impact):
        """nudge_dynamics is RTP_CONTRIBUTION=False — it re-presents a PORTION of
        ST1's win as a data-derived SHARE, it does NOT add a separate RTP addend.
        The nudge's rtp_contribution_pp must be a sub-share of the ST's own pp
        (0 < nudge_pp < st_pp, and == share_of_st_win * st_pp) — NOT the pre-W5
        whole-ST placeholder that rendered the full 90.99pp / 100%."""
        stb = m63_player_impact["spin_type_breakdown"]
        nd = m63_player_impact[_NUDGE_FEATURE]
        nudge_st = int(nd["nudge_spin_type"])
        st_row = next(r for r in stb if int(r["spin_type"]) == nudge_st)
        rtp_c = nd.get("rtp_concentration") or {}
        st_pp = st_row.get("rtp_contribution_pp")
        nudge_pp = rtp_c.get("nudge_rtp_contribution_pp")
        share = rtp_c.get("share_of_st_win")
        assert nudge_pp is not None and st_pp, "nudge rtp pp + ST pp must be present"
        assert 0.0 < nudge_pp < st_pp, (
            f"nudge rtp pp ({nudge_pp}) must be a SUB-share of the ST pp ({st_pp}), "
            "not the whole-ST placeholder"
        )
        assert share is not None and 0.0 < share < 1.0
        assert nudge_pp == pytest.approx(share * st_pp, rel=1e-6), (
            "nudge rtp pp must equal share_of_st_win * ST rtp_pp (data-derived share)"
        )

    def test_session_conservation_ok(self, m63_summary):
        ric = m63_summary.get("rtp_integrity_check", {})
        assert ric.get("session_conservation_level") == "ok", (
            f"session_conservation_level must be 'ok'; got "
            f"{ric.get('session_conservation_level')}"
        )


# ---------------------------------------------------------------------------
# 5. NUDGE STRUCTURE — N1-N6 present, internally consistent, money-agnostic.
#    NO pinned values — only count==sum-of-parts and rate==num/den relations.
# ---------------------------------------------------------------------------

class TestNudgeStructure:
    def test_applicable_and_points_at_declared_st(self, m63_nudge, m63_manifest):
        assert m63_nudge.get("applicable") is True, (
            f"nudge_dynamics must be applicable on M63; got "
            f"applicable={m63_nudge.get('applicable')} reason={m63_nudge.get('reason')}"
        )
        assert int(m63_nudge.get("nudge_spin_type")) == _nudge_st(m63_manifest), (
            "nudge_spin_type must be the ST declaring crazy_reel (resolved from "
            "the manifest, not hardcoded)"
        )

    def test_cadence_counts_partition(self, m63_nudge):
        """N1: nudge_rounds = single + multi; nudge + baseline = total; hit_rate
        = nudge/total. Internal-consistency (count==sum-of-parts), value-agnostic."""
        cad = m63_nudge["cadence"]
        nudge = cad["nudge_rounds"]
        total = cad["total_rounds"]
        single = cad["single_col_rounds"]
        multi = cad["multi_col_rounds"]
        assert nudge > 0 and total > 0
        assert single + multi == nudge, (
            f"single_col ({single}) + multi_col ({multi}) must == nudge_rounds "
            f"({nudge})"
        )
        assert single <= nudge and multi <= nudge and nudge <= total
        # hit_rate == nudge/total (a derived rate, not a pinned number).
        assert m63_nudge["hit_rate"] == pytest.approx(nudge / total, abs=1e-9)
        assert cad["single_col_share"] == pytest.approx(single / nudge, abs=1e-9)

    def test_win_rate_uplift_is_ratio_of_two_rates(self, m63_nudge):
        """N2: nudge/baseline win-rates and their ratio are derived purely from
        counts (rate==num/den, ratio==rate/rate). Value-agnostic."""
        u = m63_nudge["win_rate_uplift"]
        for k in ("nudge", "baseline", "ratio"):
            assert u.get(k) is not None, f"win_rate_uplift.{k} must be present"
        assert u["ratio"] == pytest.approx(u["nudge"] / u["baseline"], abs=1e-9), (
            "uplift ratio must equal nudge_win_rate / baseline_win_rate"
        )

    def test_win_through_share_bounded_by_nudge_wins(self, m63_nudge):
        """N3: win_through_nudge_rounds <= nudge_win_rounds, and the share is
        their quotient. A probability is in [0,1]. Value-agnostic bounds."""
        through = m63_nudge["win_through_nudge_rounds"]
        nudge_win = m63_nudge["nudge_win_rounds"]
        share = m63_nudge["win_through_nudge_share"]
        assert 0 <= through <= nudge_win, (
            f"win_through_nudge_rounds ({through}) must be <= nudge_win_rounds "
            f"({nudge_win})"
        )
        assert share == pytest.approx(through / nudge_win, abs=1e-9)
        assert 0.0 <= share <= 1.0

    def test_slide_distribution_probs_sum_to_one(self, m63_nudge):
        """N4: the slide-offset histogram counts sum to nudge_rounds and the
        probs sum to ~1; rows are sorted by descending count (determinism). The
        OFFSET LABELS are a structural signature (the 5 slide positions), counts
        are NOT pinned."""
        slides = m63_nudge["slide_distribution"]
        assert isinstance(slides, list) and len(slides) >= 1
        cad = m63_nudge["cadence"]
        # counts sum to nudge_rounds (every nudge round contributes one offset).
        total_offset = sum(s["count"] for s in slides)
        assert total_offset == cad["nudge_rounds"], (
            f"slide-offset counts ({total_offset}) must sum to nudge_rounds "
            f"({cad['nudge_rounds']})"
        )
        prob_sum = sum(s["prob"] for s in slides)
        assert prob_sum == pytest.approx(1.0, abs=1e-6)
        # Deterministic ordering: descending count, label tiebreak.
        keyed = [(-s["count"], s["offset_label"]) for s in slides]
        assert keyed == sorted(keyed), (
            "slide_distribution must be sorted by descending count (deterministic)"
        )
        for s in slides:
            assert s["prob"] == pytest.approx(s["count"] / cad["nudge_rounds"], abs=1e-9)

    def test_per_column_distribution_partitions_nudge_rounds(self, m63_nudge):
        """N5: the per-column (first-nudged-column) counts sum to nudge_rounds;
        each share == count/nudge_rounds; columns are 0-based and sorted
        (column-generic — the nudge can fire on any reel). Value-agnostic."""
        cols = m63_nudge["by_column"]
        cad = m63_nudge["cadence"]
        assert isinstance(cols, list) and len(cols) >= 1
        total_col = sum(c["count"] for c in cols)
        assert total_col == cad["nudge_rounds"], (
            f"per-column counts ({total_col}) must sum to nudge_rounds "
            f"({cad['nudge_rounds']}) — one first-nudged-column per nudge round"
        )
        col_ids = [c["col"] for c in cols]
        assert col_ids == sorted(col_ids), "by_column must be sorted by column index"
        assert all(isinstance(c["col"], int) and c["col"] >= 0 for c in cols), (
            "columns must be 0-based non-negative integers (column-generic)"
        )
        for c in cols:
            assert c["share"] == pytest.approx(c["count"] / cad["nudge_rounds"], abs=1e-9)

    def test_rtp_concentration_is_data_derived_share_not_coin(self, m63_nudge):
        """N6: rtp_concentration carries DATA-DERIVED shares / rates / a
        contribution-pp — NO raw coin total surfaced. The W5 fix replaced the
        whole-ST 100% placeholder: share_of_all_win is now the REAL nudge-round
        win share (in (0,1)); event_rate == hit_rate."""
        rtp_c = m63_nudge["rtp_concentration"]
        # No raw-coin key surfaced (the felt experience is shares, not totals).
        assert "nudge_win_sum" not in rtp_c and "total_win_sum" not in rtp_c, (
            "rtp_concentration must surface SHARES, not raw coin totals"
        )
        # event_rate is a probability in [0,1] and mirrors the hit_rate.
        er = rtp_c.get("event_rate")
        assert er is not None and 0.0 <= er <= 1.0
        assert er == pytest.approx(m63_nudge["hit_rate"], abs=1e-9)
        # share_of_all_win is a DATA-DERIVED share in (0,1) — NOT the pre-W5 1.0
        # whole-ST placeholder, NOT a parser_blind flag.
        saw = rtp_c.get("share_of_all_win")
        assert saw is not None and 0.0 < saw < 1.0, (
            f"share_of_all_win ({saw}) must be a data-derived nudge-round win share "
            "in (0,1), not the whole-ST 100% placeholder"
        )
        assert "nudge_round_win_amount_split" not in rtp_c, (
            "the win-amount split is now DATA-DERIVED (from nudge_win_sum/"
            "total_win_sum) — the parser_blind placeholder must be gone"
        )

    def test_no_extraction_errors_surfaced(self, m63_nudge):
        """Honesty: extractor errors are surfaced, never swallowed
        (feedback_no_silent_swallow.md). On clean data the key is absent."""
        assert "extraction_errors" not in m63_nudge, (
            f"unexpected extraction_errors on clean M63 data: "
            f"{m63_nudge.get('extraction_errors')}"
        )


# ---------------------------------------------------------------------------
# 6. NON-LEAK — nudge_dynamics fires ONLY on M63; peers' sets are unchanged;
#    the crazy_reel_dim extractor / crazy_reel key do not appear on peers.
# ---------------------------------------------------------------------------

class TestNonLeak:
    @staticmethod
    def _derived(machine: str) -> set[str]:
        from fresh_slotlab.analyzer.machine_spec import load_manifest, derive_analyses
        return set(derive_analyses(load_manifest(machine, _MANIFESTS_ROOT)))

    def test_nudge_dynamics_does_not_leak_onto_peers(self):
        """The headline non-leak: nudge_dynamics must NOT appear in any peer's
        derived set (it is dimension-keyed on crazy_reel, which only M63
        declares). Mirrors test_m15_has_no_minigame_dynamics."""
        for machine in _NON_DECLARING_PEERS:
            from fresh_slotlab.analyzer.machine_spec import load_manifest
            try:
                load_manifest(machine, _MANIFESTS_ROOT)
            except Exception:
                pytest.skip(f"{machine} manifest not present")
            derived = self._derived(machine)
            assert _NUDGE_FEATURE not in derived, (
                f"nudge_dynamics LEAKED onto {machine} — the crazy_reel dimension "
                f"key must scope it to M63 alone (not the paid_spin role / Normal "
                f"play that {machine} may share)"
            )

    def test_only_m63_declares_crazy_reel_fleet_wide(self):
        """Fleet scan: NO manifest other than M63 declares the crazy_reel
        dimension block. The isolation guarantee at its source."""
        declaring = []
        for path in sorted(_MANIFESTS_ROOT.glob("*.json")):
            try:
                man = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for spec in (man.get("spin_types") or {}).values():
                if isinstance(spec, dict) and _CRAZY_REEL_KEY in spec:
                    declaring.append(path.stem)
                    break
        assert declaring == ["M63"], (
            f"exactly one manifest (M63) may declare crazy_reel; got {declaring}"
        )

    def test_extractor_not_configured_on_peers(self):
        """The crazy_reel_dim extractor must NOT be configured for any peer
        (no crazy_reel block ⇒ byte-identical parse, key absent in their
        records). Mirrors test_sibling_manifests_configure_no_trigger_path."""
        from fresh_slotlab.analyzer.machine_spec import load_manifest
        from fresh_slotlab.analyzer.st_extract import (
            discover_extractors, get_extractors_for_manifest,
        )
        discover_extractors()
        for machine in _NON_DECLARING_PEERS:
            try:
                manifest = load_manifest(machine, _MANIFESTS_ROOT)
            except Exception:
                pytest.skip(f"{machine} manifest not present")
            ext_ids = [e.EXTRACTOR_ID for e in get_extractors_for_manifest(manifest)]
            assert _CRAZY_EXTRACTOR_ID not in ext_ids, (
                f"{machine} must NOT configure the crazy_reel_dim extractor "
                f"(no crazy_reel block); got {ext_ids}"
            )

    def test_lock_respin_does_not_leak_onto_m63(self):
        """Reciprocal non-leak (the club-batch sibling): M104's
        lock_respin_dynamics (play-keyed LockSymbolSpin) must NOT fire on M63,
        and nudge_dynamics must NOT fire on M104 — the two onboarded mechanics
        are mutually isolated."""
        m63 = self._derived("M63")
        assert "lock_respin_dynamics" not in m63, (
            "lock_respin_dynamics LEAKED onto M63 — M104's LockSymbolSpin play "
            "must not match M63's Normal play"
        )
        try:
            from fresh_slotlab.analyzer.machine_spec import load_manifest
            load_manifest("M104", _MANIFESTS_ROOT)
        except Exception:
            pytest.skip("M104 manifest not present")
        m104 = self._derived("M104")
        assert _NUDGE_FEATURE not in m104, (
            "nudge_dynamics LEAKED onto M104 — crazy_reel must scope it to M63"
        )
        assert "lock_respin_dynamics" in m104, (
            "sanity: M104 must carry its own lock_respin_dynamics"
        )


# ---------------------------------------------------------------------------
# 7. INJECT-BUG PROOF — break each safety claim → RED → (auto-revert) → GREEN.
#
# Claim A: the crazy_reel_dim extractor delivers the data-derived nudge metrics;
#          without the extractor's chunk output nudge_dynamics degrades HONESTLY
#          to applicable:false (proves the data path is load-bearing, not
#          fabricated), while INTEGRITY still passes (attribution is independent).
# Claim B: nudge_dynamics is dimension-keyed (proven in
#          test_nudge_attached_via_dimension_key_not_role_or_play — re-confirmed
#          here at the report level: same machine_spec hook drives derive_analyses).
#
# The extractor-drop monkeypatch auto-reverts, so the module-scoped m63_summary
# fixture (built without any patch) stays GREEN (all classes above).
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_drop_extractor_collapses_nudge(self, monkeypatch):
        """INJECT (Claim A): make get_extractors_for_manifest return [] (the
        crazy_reel_dim extractor never runs). Assert nudge_dynamics degrades
        HONESTLY to applicable:false with a reason (NOT a fabricated panel) and
        that integrity STILL passes (the nudge re-presents ST1's already-real
        attribution — it is not load-bearing for the RTP sum)."""
        if not _has_chunks(_M63_CHUNK_DIR):
            pytest.skip("M63 cached chunks not present")
        import fresh_slotlab.analyzer.st_extract as st_mod
        import fresh_slotlab.analyzer.report_engine as re_mod

        def _no_extractors(manifest):
            return []

        monkeypatch.setattr(st_mod, "get_extractors_for_manifest", _no_extractors)
        if hasattr(re_mod, "get_extractors_for_manifest"):
            monkeypatch.setattr(re_mod, "get_extractors_for_manifest", _no_extractors)

        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = generate_report_from_chunks(
                "M63", 1, chunk_dir=_M63_CHUNK_DIR,
                output_dir=Path(tmpdir), bet=_BET,
            )
            nd = summary["player_impact"].get(_NUDGE_FEATURE) or {}
            assert nd.get("applicable") is False, (
                "inject-bug: with no crazy_reel_dim extractor the nudge section "
                f"must degrade to applicable:false (not fabricate); got "
                f"{nd.get('applicable')}"
            )
            assert isinstance(nd.get("reason"), str) and nd["reason"], (
                "the degraded nudge section must carry a reason (honest, not silent)"
            )
            # Attribution is INDEPENDENT of the extractor — integrity still passes.
            assert summary["rtp_integrity_check"].get("passed") is True, (
                "inject-bug: dropping the extractor must NOT break attribution "
                "(the nudge re-presents ST1's already-real payids)"
            )
        # monkeypatch auto-reverts here.

    def test_green_resumes_after_revert(self, m63_summary, m63_nudge):
        """After the inject-bug monkeypatch reverts, the real (un-patched) report
        is GREEN: integrity passes, no fallback, the nudge is applicable and
        data-derived, the cadence partitions cleanly."""
        ric = m63_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert ric.get("layer2_no_fallback_buckets_ok") is True
        assert not _payout_ids(m63_summary) or not any(
            p.startswith("_unattributed") for p in _payout_ids(m63_summary)
        )
        assert m63_nudge.get("applicable") is True
        cad = m63_nudge["cadence"]
        assert cad["single_col_rounds"] + cad["multi_col_rounds"] == cad["nudge_rounds"]
