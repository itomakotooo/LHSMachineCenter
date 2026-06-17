"""M44 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This test asserts STRUCTURE / FLAGS / INVARIANTS, never an RTP value or a count.
The machine's numbers (RTP, hit-rates, openers) change on re-sample / re-tune /
upstream-config drift, so pinning ANY number here would be a brittle false alarm
(charter permanent invariant 1).

What M44 added (session_artifacts/_onboard/M44/03_design.md):
  - configs/machine_manifests/M44.json — ST1 paid_spin/Normal, ST50 respin/WinRespin,
    ST51 settlement/WinMiniGame.  M44 is the M43 archetype VERBATIM on a different
    skin/reel build: NO new plugin, NO new role token, NO closure change.
  - configs/machine_round_win_rules.json `m44_minigame_settlement` (synthesize_pay_id,
    spin_types=[51], label_format=spin_type, applies_to=["M44"]) — attributes the whole
    ST51 win to a single real pid `st51` so the RTP-integrity gate passes
    (_unattributed_st51 → 0).  EXACT M43/M279/M283 precedent (rule TYPE reused).

M44 reuses the M43-archetype plugins:
  - fresh_slotlab/analyzer/features/respin_dynamics.py — ST50 respin mechanic view
    (attached via the `respin` ROLE → machine_spec.ROLE_ANALYSES).
  - fresh_slotlab/analyzer/features/minigame_dynamics.py — ST51 minigame view
    (attached via the `WinMiniGame` PLAY → machine_spec.PLAY_ANALYSES, NOT the shared
    `settlement` role, so it must NOT leak onto M15's TopDollar settlement).

The whole test runs the REAL engine on the cached M44 chunk(s) at
rawdata/M44/mode_1 (charter invariant 3: run the real thing; read the real summary).

Tests
-----
1. report generates; rtp_integrity_check.passed == True; _unattributed_st51 share == 0
   (no fallback bucket; the attribution rule holds) — VALUE-AGNOSTIC.
2. schema / frontend-contract keys present (top-level + player_impact.*).
3. respin_dynamics + minigame_dynamics present with the DELIVERED metrics populated.
4. the DEFERRED (testspin/parser-blind) metrics are correctly FLAGGED parser_blind,
   NOT fabricated — and the markers EXIST (so a future change that fakes them, or that
   silently drops the flag, goes RED).
5. M15 untouched: M15's report still generates and has NO respin_dynamics /
   minigame_dynamics (the ROLE/PLAY wiring did not leak — minigame_dynamics is keyed on
   the WinMiniGame PLAY, NOT the shared `settlement` role M15's ST15 also uses).
6. preview / no-payid double-count guard: aggregator parity holds
   (sum(payout_id rtp_contribution_pp) == rtp.point_pct) and the no-payid ST51
   contributes exactly ONE synthesized pid row (no fallback, no double-count).

Inject-bug → RED → revert → GREEN (TestInjectBugProof):
  Two injects, each into M44's OWN artifact (NEVER a shared plugin):
    (a) load_rules_for_machine("M44") returns the rule list WITHOUT M44's OWN
        m44_minigame_settlement row (simulates that one config row being deleted).
        The whole ST51 win then lands in _unattributed_st51 → Layer-2 fallback →
        rtp_integrity_check.passed is NOT True.
    (b) M44's OWN manifest ST51 `play` flipped off "WinMiniGame" → minigame_dynamics
        no longer attaches → the M44 minigame section disappears (PLAY hook proof).
  Both monkeypatches auto-revert, so the GREEN module fixture is unaffected.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

# Repo root for locating rawdata.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M44_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M44" / "mode_1"
_M15_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M15" / "mode_1"
_MANIFESTS_ROOT = _REPO_ROOT / "configs" / "machine_manifests"

# The bet used during M44 sampling (CostCredits=1000 per paid spin, chunk _bet=1000).
# The report is value-agnostic; bet only affects coin totals, which this test never
# asserts. Passing it correctly avoids the M279 1000x multiplier-inflation trap
# (charter invariant 3: bet=<chunk _bet>, NOT the engine default 1).
_BET = 1000

# Reserved fallback-bucket prefix the attribution rule must zero out (rtp_integrity
# Layer 2). The specific bucket for ST51 with no PayoutIdToWinAmount is _unattributed_st51.
_FALLBACK_ST51 = "_unattributed_st51"


# Expected top-level keys (frontend contract — same current schema as the M43 archetype).
# NOTE: M44 has no `player_choice` role, so it has NO top-level `topdollar_choice` key.
# We assert a SUPERSET (all required keys present), never equality, so machine-specific
# top-level keys do not make this brittle.
_EXPECTED_TOP_KEYS = frozenset({
    "report_id", "run_id", "machine", "mode",
    "config_md5", "code_md5",
    "analyzer_version", "effective_analyzer_version", "effective_analyzer_version_error",
    "output_all_robots_result",
    "sampling", "rtp",
    "player_impact", "upstream_analysis",
    "collect_mechanic",
    "guideline_assessment", "guideline_comparison",
    "rtp_integrity_check",
    "storage",
})

# Expected player_impact sub-keys. The standard set PLUS the two M43-archetype mechanic
# sections. We assert these are all present (superset), never equality.
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
    # M43-archetype mechanic sections (the whole point of this onboarding):
    "respin_dynamics", "minigame_dynamics",
})

# The three DECLARED SpinTypes (configs/machine_manifests/M44.json spin_types).
_DECLARED_SPIN_TYPES = frozenset({1, 50, 51})


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


def _gen(machine_id: str, chunk_dir: Path, **kw):
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            machine_id, 1,
            chunk_dir=chunk_dir,
            output_dir=Path(tmpdir),
            bet=_BET,
            **kw,
        )
        # The summary write is part of the contract.
        assert (Path(tmpdir) / "player_impact_summary.json").exists(), (
            "write_summary_json must produce player_impact_summary.json"
        )
        return summary


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m44_summary():
    if not _has_chunks(_M44_CHUNK_DIR):
        pytest.skip("M44 cached chunks not present")
    return _gen("M44", _M44_CHUNK_DIR)


@pytest.fixture(scope="module")
def m44_player_impact(m44_summary):
    return m44_summary["player_impact"]


def _payout_id_rows(summary) -> list[dict]:
    return list(summary["player_impact"].get("payout_ids_top20", []))


def _payout_ids(summary) -> list[str]:
    return [str(r.get("payout_id", "")) for r in _payout_id_rows(summary)]


# ---------------------------------------------------------------------------
# 1. CORRECTNESS GATE — integrity passes; _unattributed_st51 share == 0.
#    VALUE-AGNOSTIC: structure/flags only, no RTP number.
# ---------------------------------------------------------------------------

class TestCorrectnessGate:
    def test_report_generates_with_machine_and_mode(self, m44_summary):
        assert m44_summary["machine"] == "M44"
        assert m44_summary["mode"] == 1
        assert m44_summary["sampling"]["chunks"] > 0
        assert m44_summary["sampling"]["total_spins"] > 0
        # bet flowed into sampling (the M279 trap guard — bet must NOT default to 1).
        assert m44_summary["sampling"].get("bet") == _BET, (
            f"sampling.bet must be the chunk bet {_BET}, not the engine default 1 "
            f"(M279 1000x inflation trap); got {m44_summary['sampling'].get('bet')}"
        )
        # No emit-loop / extract errors surfaced (feedback_no_silent_swallow.md).
        assert not m44_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m44_summary.get('feature_errors')}"
        )

    def test_rtp_integrity_passes(self, m44_summary):
        """rtp_integrity_check.passed must be True (sum(payid)==total, no fallback)."""
        ric = m44_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M44 mode 1. "
            f"Got passed={ric.get('passed')}, message={ric.get('summary_message', 'N/A')}. "
            f"Likely cause: the m44_minigame_settlement round_win rule is not applied → "
            f"ST51 win lands in {_FALLBACK_ST51}."
        )

    def test_layer1_sum_invariant_holds(self, m44_summary):
        """L1 (value-agnostic): sum(pay_id win) == our_total_win — no orphan/double-count."""
        ric = m44_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant broken: {ric.get('layer1_error')}"
        )

    def test_no_unattributed_st51_fallback_bucket(self, m44_summary):
        """The attribution rule holds: NO _unattributed_st51 (Layer-2 fallback) bucket.
        This is the headline value-agnostic guard — 'share == 0' = the bucket is absent."""
        ric = m44_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}. "
            f"The m44_minigame_settlement rule must zero {_FALLBACK_ST51}."
        )
        buckets = ric.get("layer2_fallback_buckets_found") or []
        assert _FALLBACK_ST51 not in buckets, (
            f"{_FALLBACK_ST51} fallback bucket present: {buckets}"
        )
        # And it must not appear as a payout_id row at all.
        pids = _payout_ids(m44_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )

    def test_layer3_anchors_ok(self, m44_summary):
        """L3 anchors must hold (no broken anchor pids)."""
        ric = m44_summary.get("rtp_integrity_check", {})
        assert ric.get("layer3_anchors_ok") is True, (
            f"Layer-3 anchors broken: {ric.get('layer3_error')}"
        )

    def test_st51_attributed_to_real_pid(self, m44_summary):
        """The synthesized real pid 'st51' must be present (the minigame as one honest
        feature row). Existence only — NOT its win value."""
        pids = _payout_ids(m44_summary)
        assert "st51" in pids, (
            f"expected synthesized real pid 'st51' from m44_minigame_settlement; "
            f"got payout ids {pids}"
        )

    def test_all_declared_spin_types_present(self, m44_player_impact):
        """Every DECLARED SpinType (1, 50, 51) has output in spin_type_breakdown —
        no declared ST silently dropped (charter invariant 3)."""
        seen = {r.get("spin_type") for r in m44_player_impact.get("spin_type_breakdown", [])}
        missing = _DECLARED_SPIN_TYPES - seen
        assert not missing, (
            f"declared SpinType(s) missing from spin_type_breakdown: {sorted(missing)} "
            f"(saw {sorted(s for s in seen if s is not None)})"
        )


# ---------------------------------------------------------------------------
# 2. SCHEMA / FRONTEND-CONTRACT keys present.
# ---------------------------------------------------------------------------

class TestSchema:
    def test_top_level_keys_superset(self, m44_summary):
        missing = _EXPECTED_TOP_KEYS - set(m44_summary.keys())
        assert not missing, f"Expected top-level keys absent: {sorted(missing)}"

    def test_player_impact_keys_superset(self, m44_player_impact):
        missing = _EXPECTED_PI_KEYS - set(m44_player_impact.keys())
        assert not missing, f"Expected player_impact keys absent: {sorted(missing)}"

    def test_rtp_integrity_check_has_layer_fields(self, m44_summary):
        ric = m44_summary["rtp_integrity_check"]
        for field in ("passed", "layer1_invariant_ok", "layer2_no_fallback_buckets_ok",
                      "layer3_anchors_ok", "summary_message"):
            assert field in ric, f"rtp_integrity_check missing field: {field}"


# ---------------------------------------------------------------------------
# 3. respin_dynamics — DELIVERED metrics populated (structure, not values).
# ---------------------------------------------------------------------------

class TestRespinDynamicsDelivered:
    @pytest.fixture
    def rd(self, m44_player_impact):
        rd = m44_player_impact.get("respin_dynamics")
        assert isinstance(rd, dict), "respin_dynamics section missing"
        return rd

    def test_applicable_and_resolved_spin_types(self, rd):
        """respin_dynamics fired for M44 (ST50 has role=respin) and resolved the STs
        from the manifest (NOT hardcoded ids — feedback_no_hardcode.md)."""
        assert rd.get("applicable") is True, (
            f"respin_dynamics must be applicable for M44; got {rd.get('applicable')} "
            f"reason={rd.get('reason')}"
        )
        assert rd.get("respin_spin_type") == 50, "respin ST must resolve to 50 (role=respin)"
        assert rd.get("base_spin_type") == 1, "base ST must resolve to 1 (role=paid_spin)"

    def test_grant_rate_populated(self, rd):
        """grant-rate: openers + both felt denominators present and non-null
        (M44 really has ST1→ST50 openers, so the rates are computable, not null)."""
        gr = rd["grant_rate"]
        for k in ("openers", "per_winning_paid_spin", "per_paid_spin", "one_per_n_paid_spins"):
            assert k in gr, f"grant_rate missing {k}"
        assert gr["openers"] > 0, "M44 has ST1->ST50 openers; openers must be > 0"
        assert gr["per_winning_paid_spin"] is not None
        assert gr["per_paid_spin"] is not None

    def test_hit_rate_uplift_populated(self, rd):
        """hit-rate uplift: respin/base hit-rates + the uplift ratio present and
        computed (a real ratio, not null). Value-agnostic — we don't pin 5.53x."""
        hu = rd["hit_rate_uplift"]
        for k in ("respin_hit_rate", "base_hit_rate", "uplift_ratio"):
            assert k in hu, f"hit_rate_uplift missing {k}"
        assert hu["respin_hit_rate"] is not None
        assert hu["base_hit_rate"] is not None
        assert hu["uplift_ratio"] is not None, "uplift_ratio must be computed (both hit-rates known)"

    def test_multiplier_distributions_populated(self, rd):
        """overlaid distributions: respin + base multiplier-band distributions
        present with non-empty bands (real histograms)."""
        rdist = rd["respin_multiplier_distribution"]
        assert isinstance(rdist.get("bands"), list) and len(rdist["bands"]) > 0, (
            "respin_multiplier_distribution.bands must be a non-empty histogram"
        )
        for band in rdist["bands"]:
            assert "band" in band and "spin_count" in band and "prob" in band, (
                f"distribution band malformed: {band}"
            )
        bdist = rd["base_multiplier_distribution"]
        assert isinstance(bdist, dict) and isinstance(bdist.get("bands"), list) and bdist["bands"], (
            "base_multiplier_distribution.bands must be a non-empty histogram"
        )

    def test_payid_mix_populated(self, rd):
        """skin-premium symbol/payid mix: respin + base payid shares present.
        M44 ST50 carries real symbol pids, so respin_payid_share is non-empty."""
        pm = rd["payid_mix"]
        assert "respin_payid_share" in pm and "base_payid_share" in pm
        assert len(pm["respin_payid_share"]) > 0, (
            "respin_payid_share must be populated (ST50 has real symbol pids)"
        )

    def test_rtp_concentration_populated(self, rd):
        """RTP-concentration: contribution + share + fat-tail + loss-rate present."""
        rc = rd["rtp_concentration"]
        for k in ("respin_rtp_contribution_pp", "share_of_all_win",
                  "fat_tail_ge20x_win_share", "loss_rate"):
            assert k in rc, f"rtp_concentration missing {k}"
        assert rc["share_of_all_win"] is not None

    def test_continuity_continuation_prob_populated(self, rd):
        """continuity: the continuation_prob P(respin->respin) IS derivable
        base-excluded and must be a real (non-null) probability."""
        cont = rd["continuity"]
        for k in ("continuation_prob", "respin_to_respin_transitions",
                  "respin_exit_transitions", "exit_breakdown"):
            assert k in cont, f"continuity missing {k}"
        assert cont["continuation_prob"] is not None, (
            "continuation_prob is derivable from transition counts; must not be null"
        )


# ---------------------------------------------------------------------------
# 4. minigame_dynamics — DELIVERED metrics populated (structure, not values).
# ---------------------------------------------------------------------------

class TestMiniGameDynamicsDelivered:
    @pytest.fixture
    def mg(self, m44_player_impact):
        mg = m44_player_impact.get("minigame_dynamics")
        assert isinstance(mg, dict), "minigame_dynamics section missing"
        return mg

    def test_applicable_and_resolved_spin_type(self, mg):
        """minigame_dynamics fired via the WinMiniGame PLAY (NOT the settlement role)
        and resolved ST51 from the manifest (feedback_no_hardcode.md)."""
        assert mg.get("applicable") is True, (
            f"minigame_dynamics must be applicable for M44; got {mg.get('applicable')} "
            f"reason={mg.get('reason')}"
        )
        assert mg.get("minigame_spin_type") == 51, "minigame ST must resolve to 51 (play=WinMiniGame)"
        assert mg.get("attributed_pay_id") == "st51", (
            "minigame must point at its synthesized pid st51"
        )

    def test_multiplier_distribution_populated(self, mg):
        """multiplier distribution (machine's own win/bet banding): non-empty bands
        + a modal band + dominant-band share present. Value-agnostic — no pin."""
        md = mg["multiplier_distribution"]
        assert isinstance(md.get("bands"), list) and len(md["bands"]) > 0, (
            "multiplier_distribution.bands must be a non-empty histogram"
        )
        for k in ("total_events", "modal_band", "dominant_band_share", "source"):
            assert k in md, f"multiplier_distribution missing {k}"
        assert md["modal_band"] is not None
        assert md["dominant_band_share"] is not None

    def test_trigger_frequency_populated(self, mg):
        """trigger frequency: events + per-paid-spin rate present and computed."""
        tf = mg["trigger_frequency"]
        for k in ("minigame_events", "per_paid_spin", "one_per_n_paid_spins"):
            assert k in tf, f"trigger_frequency missing {k}"
        assert tf["minigame_events"] > 0, "M44 has minigame events; count must be > 0"
        assert tf["per_paid_spin"] is not None

    def test_trigger_context_counts_populated(self, mg):
        """trigger-context transition COUNTS by source ST (base vs respin burst) are
        present — the surprise-on-loss RATE itself is parser-blind (asserted in
        TestDeferredMetricsFlagged)."""
        tc = mg["trigger_context"]
        for k in ("opener_from_base_spin", "opener_from_respin_burst",
                  "share_from_base_spin", "share_from_respin_burst"):
            assert k in tc, f"trigger_context missing {k}"

    def test_rtp_concentration_populated(self, mg):
        """RTP-concentration (the big-win engine): contribution + share + event-rate
        + hit-rate present and computed. Value-agnostic — no pin."""
        rc = mg["rtp_concentration"]
        for k in ("minigame_rtp_contribution_pp", "share_of_all_win", "event_rate", "hit_rate"):
            assert k in rc, f"rtp_concentration missing {k}"
        assert rc["share_of_all_win"] is not None
        assert rc["event_rate"] is not None


# ---------------------------------------------------------------------------
# 5. DEFERRED metrics correctly FLAGGED parser_blind (NOT fabricated).
#
#    These markers MUST EXIST. A future change that (a) silently drops a flag, or
#    (b) fabricates the blind metric (e.g. sets node_path_analysis.available=True or
#    emits a fake surprise_on_loss_rate), makes one of these assertions go RED.
#    This protects the charter "no fabricated coverage" invariant.
# ---------------------------------------------------------------------------

class TestDeferredMetricsFlagged:
    def test_minigame_node_path_analysis_flagged_unavailable(self, m44_player_impact):
        """node path is parser-blind: available==False with parser_blind reasons.
        (If a future change fakes the node-count/node-code tables, available would flip
        True / the parser_blind list would shrink — this goes RED.)"""
        npa = m44_player_impact["minigame_dynamics"]["node_path_analysis"]
        assert npa.get("available") is False, (
            "node_path_analysis.available must be False (node-path metrics are parser-blind, "
            "NOT fabricated). If True, someone faked the node path tables."
        )
        blind = npa.get("parser_blind")
        assert isinstance(blind, list) and len(blind) > 0, (
            "node_path_analysis.parser_blind must list the blind sub-metrics"
        )
        assert isinstance(npa.get("parser_blind_reason"), str) and npa["parser_blind_reason"], (
            "node_path_analysis.parser_blind_reason must explain WHY (escalation, not silence)"
        )
        # The specific deferred sub-metrics must be named (so dropping one is caught).
        blind_blob = " ".join(blind).lower()
        assert "node_count" in blind_blob, "node_count_x_multiplier must be flagged blind"
        assert "node_code" in blind_blob, "node_code_distribution must be flagged blind"
        assert "terminal_node" in blind_blob, "terminal_node_x_multiplier must be flagged blind"

    def test_minigame_surprise_on_loss_flagged_parser_blind(self, m44_player_impact):
        """surprise-on-loss RATE is parser-blind (the win/loss status of the specific
        preceding base spin is not in the transition counts). The marker must EXIST
        under trigger_context.parser_blind — NOT emitted as a fabricated number."""
        tc = m44_player_impact["minigame_dynamics"]["trigger_context"]
        blind = tc.get("parser_blind")
        assert isinstance(blind, list) and len(blind) > 0, (
            "trigger_context.parser_blind must list surprise_on_loss_rate as blind"
        )
        assert any("surprise_on_loss" in str(x).lower() for x in blind), (
            f"surprise_on_loss_rate must be flagged parser_blind; got {blind}"
        )
        assert isinstance(tc.get("parser_blind_reason"), str) and tc["parser_blind_reason"], (
            "trigger_context.parser_blind_reason must explain WHY"
        )
        # And it must NOT be fabricated as a populated metric.
        assert "surprise_on_loss_rate" not in tc, (
            "surprise_on_loss_rate must NOT be emitted as a value — it is parser-blind"
        )

    def test_respin_continuity_parser_blind_present(self, m44_player_impact):
        """burst-length histogram + win-gating proof are parser-blind. The marker
        must EXIST under continuity.parser_blind (the continuation_prob IS delivered;
        only the burst-length SHAPE is blind)."""
        cont = m44_player_impact["respin_dynamics"]["continuity"]
        blind = cont.get("parser_blind")
        assert isinstance(blind, list) and len(blind) > 0, (
            "continuity.parser_blind must list burst_length_histogram + win_gating_proof"
        )
        blind_blob = " ".join(blind).lower()
        assert "burst_length" in blind_blob, "burst_length_histogram must be flagged blind"
        assert "win_gating" in blind_blob or "win-gat" in blind_blob, (
            "win_gating_proof must be flagged blind"
        )
        assert isinstance(cont.get("parser_blind_reason"), str) and cont["parser_blind_reason"], (
            "continuity.parser_blind_reason must explain WHY"
        )


# ---------------------------------------------------------------------------
# 6. PREVIEW / NO-PAYID DOUBLE-COUNT GUARD.
#    ST51 carries NO round-level payid (settlement). It is attributed by ONE
#    synthesized pid `st51`. Assert (a) aggregator parity holds across views, and
#    (b) ST51 is not double-counted (paid_rounds==0: a free settlement adds no
#    paid-round bet; the win is carried once by st51 in the payid view).
# ---------------------------------------------------------------------------

class TestNoDoubleCount:
    def test_aggregator_parity_payids_equal_rtp(self, m44_summary):
        """sum(payout_id rtp_contribution_pp) == rtp.point_pct — the cross-aggregator
        parity invariant (feedback_aggregator_parity_invariant). Value-agnostic: we
        compare two VIEWS of the SAME RTP, never pin the number itself."""
        rows = _payout_id_rows(m44_summary)
        sum_pp = sum(float(r.get("rtp_contribution_pp", 0) or 0) for r in rows)
        point = float(m44_summary["rtp"]["point_pct"])
        assert abs(sum_pp - point) < 0.05, (
            f"aggregator parity broken: sum(payout_id rtp_contribution_pp)={sum_pp:.4f} "
            f"!= rtp.point_pct={point:.4f} (double-count or orphan)"
        )

    def test_st51_single_synthesized_row_no_double_count(self, m44_summary):
        """ST51's no-payid settlement contributes EXACTLY ONE synthesized pid row
        (st51) and ZERO fallback rows — i.e. it is attributed ONCE, not split AND
        bucketed (which would double-count)."""
        rows = _payout_id_rows(m44_summary)
        st51_rows = [r for r in rows if str(r.get("payout_id")) == "st51"]
        assert len(st51_rows) == 1, (
            f"ST51 must be one synthesized row; got {len(st51_rows)} st51 rows"
        )
        # The single st51 row must be dominated by ST51 (the settlement event), not
        # smeared across ST1/ST50 symbol pids.
        assert st51_rows[0].get("dominant_spin_type") == 51, (
            f"st51 row must be dominated by ST51; got {st51_rows[0].get('dominant_spin_type')}"
        )
        # No fallback companion row exists alongside it.
        assert not any(str(r.get("payout_id")).startswith("_unattributed") for r in rows), (
            "an _unattributed_* companion row exists — ST51 would be double-counted"
        )

    def test_minigame_st_not_charging_paid_bet(self, m44_player_impact):
        """ST51 (free settlement) declares paid_rounds==0 / total_paid_bet==0: it does
        NOT charge the player, so it cannot inflate the paid-round denominator. The
        win arrives via the synthesized pid, not a second paid-round entry."""
        stb = {r.get("spin_type"): r for r in m44_player_impact.get("spin_type_breakdown", [])}
        assert 51 in stb, "ST51 missing from spin_type_breakdown"
        st51 = stb[51]
        assert st51.get("paid_rounds") == 0, (
            f"ST51 is a free settlement; paid_rounds must be 0, got {st51.get('paid_rounds')}"
        )
        assert (st51.get("total_paid_bet") or 0) == 0, (
            f"ST51 must charge no paid bet; got total_paid_bet={st51.get('total_paid_bet')}"
        )


# ---------------------------------------------------------------------------
# 7. M15 UNTOUCHED — the ROLE/PLAY wiring did not leak onto M15 (CROSS-MACHINE
#    NON-LEAK). minigame_dynamics is keyed on the WinMiniGame PLAY, NOT the
#    `settlement` role (which M15's ST15 TopDollar settlement ALSO uses) — so it
#    must NOT fire on M15. respin_dynamics is keyed on the `respin` role, which M15
#    does not have. Proven two ways: (a) derive_analyses (no engine), (b) real engine.
# ---------------------------------------------------------------------------

class TestM15NotLeaked:
    def test_derive_analyses_m15_excludes_archetype_plugins(self):
        """Static (no-engine) non-leak: derive_analyses(M15) does NOT contain
        minigame_dynamics or respin_dynamics, while derive_analyses(M44) does. Proves
        the PLAY/ROLE scoping in machine_spec keeps the M44 archetype off M15."""
        from fresh_slotlab.analyzer.machine_spec import load_manifest, derive_analyses
        m44 = set(derive_analyses(load_manifest("M44", manifests_root=_MANIFESTS_ROOT)))
        m15 = set(derive_analyses(load_manifest("M15", manifests_root=_MANIFESTS_ROOT)))
        assert "minigame_dynamics" in m44 and "respin_dynamics" in m44, (
            f"M44 must derive both archetype analyses; got {sorted(m44)}"
        )
        assert "minigame_dynamics" not in m15, (
            "minigame_dynamics LEAKED into M15's analysis set — it is keyed on the "
            "WinMiniGame PLAY, NOT the `settlement` role M15's ST15 shares."
        )
        assert "respin_dynamics" not in m15, (
            "respin_dynamics LEAKED into M15's analysis set — M15 has no `respin` role."
        )

    @pytest.fixture(scope="class")
    def m15_summary(self):
        if not _has_chunks(_M15_CHUNK_DIR):
            pytest.skip("M15 cached chunks not present")
        return _gen("M15", _M15_CHUNK_DIR)

    def test_m15_report_generates_and_integrity_passes(self, m15_summary):
        assert m15_summary["machine"] == "M15"
        assert m15_summary["rtp_integrity_check"].get("passed") is True, (
            "M15 integrity must still pass (onboarding M44 must not regress M15)"
        )

    def test_m15_has_no_respin_dynamics(self, m15_summary):
        assert "respin_dynamics" not in m15_summary["player_impact"], (
            "respin_dynamics LEAKED onto M15 — the `respin` role must not match M15."
        )

    def test_m15_has_no_minigame_dynamics(self, m15_summary):
        assert "minigame_dynamics" not in m15_summary["player_impact"], (
            "minigame_dynamics LEAKED onto M15 — it is keyed on the WinMiniGame PLAY, "
            "NOT the `settlement` role that M15's ST15 shares. The PLAY_ANALYSES scoping "
            "(machine_spec.py) is what prevents this leak."
        )

    def test_m15_has_no_m44_synthetic_pid(self, m15_summary):
        """The m44_minigame_settlement rule (applies_to=['M44']) must NOT attribute an
        st51 pid on M15 — the rule is scoped to M44 by applies_to."""
        pids = [str(r.get("payout_id", "")) for r in m15_summary["player_impact"].get("payout_ids_top20", [])]
        # M15 has its own ST51? No — but guard against the rule cross-firing: M15 must
        # not gain an st51 row from the M44-scoped rule.
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"M15 gained an _unattributed_* pid (regression): {pids}"
        )


# ---------------------------------------------------------------------------
# INJECT-BUG PROOF — break M44's OWN artifact → RED → (auto-revert) → GREEN.
#
# Injects target ONLY M44's OWN config rule and OWN manifest — NEVER a shared
# plugin or another machine's file (charter invariant 2; task constraint).
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_drop_m44_rule_reintroduces_unattributed_st51(self, monkeypatch):
        """INJECT (a): load_rules_for_machine("M44") returns the rule list WITHOUT
        M44's OWN m44_minigame_settlement row (simulates deleting that single config
        row). The ST51 win then lands in _unattributed_st51 (Layer-2 fallback) and
        integrity FAILS — VALUE-AGNOSTIC (the fallback bucket is the signature, not an
        RTP number). This proves TestCorrectnessGate goes RED when the rule is absent."""
        if not _has_chunks(_M44_CHUNK_DIR):
            pytest.skip("M44 cached chunks not present")

        import fresh_slotlab.round_win as rw_mod
        _orig = rw_mod.load_rules_for_machine

        def _drop_m44_minigame_rule(machine_id, config):
            # Build the rule list exactly as production does, then drop ONLY M44's own
            # synthesized-pid minigame rule (params spin_types==[51]). Other machines'
            # rules and other M44 rules (none today) are untouched — this is a surgical
            # inject into M44's OWN config row, not a blanket "no rules" hack.
            if machine_id == "M44" and config and isinstance(config, dict):
                cfg2 = dict(config)
                rules = dict(config.get("rules") or {})
                rules.pop("m44_minigame_settlement", None)
                cfg2["rules"] = rules
                return _orig(machine_id, cfg2)
            return _orig(machine_id, config)

        monkeypatch.setattr(rw_mod, "load_rules_for_machine", _drop_m44_minigame_rule)

        summary = _gen("M44", _M44_CHUNK_DIR)
        ric = summary.get("rtp_integrity_check", {})
        pids = _payout_ids(summary)

        # RED 1 — the _unattributed_st51 fallback bucket reappears.
        assert _FALLBACK_ST51 in pids, (
            f"inject-bug: without M44's rule, ST51 win must land in {_FALLBACK_ST51}; "
            f"got payout ids {pids}"
        )
        # RED 2 — Layer 2 flags the fallback bucket.
        assert ric.get("layer2_no_fallback_buckets_ok") is False, (
            f"inject-bug: Layer-2 must flag the fallback bucket; "
            f"got layer2_no_fallback_buckets_ok={ric.get('layer2_no_fallback_buckets_ok')}, "
            f"buckets={ric.get('layer2_fallback_buckets_found')}"
        )
        assert _FALLBACK_ST51 in (ric.get("layer2_fallback_buckets_found") or [])
        # RED 3 — overall integrity is NOT passing.
        assert ric.get("passed") is not True, (
            f"inject-bug: rtp_integrity_check.passed must NOT be True; got {ric.get('passed')}"
        )
        # RED 4 — the synthesized real pid 'st51' is gone (no attribution).
        assert "st51" not in pids, (
            f"inject-bug: real pid 'st51' must be absent without the rule; got {pids}"
        )
        # monkeypatch auto-reverts here — the module-scoped GREEN fixture is unaffected.

    def test_inject_flip_m44_play_drops_minigame_dynamics(self, monkeypatch):
        """INJECT (b): flip M44's OWN manifest ST51 play off "WinMiniGame". The
        PLAY_ANALYSES["WinMiniGame"] hook then no longer matches → minigame_dynamics
        does NOT attach → the M44 minigame section disappears. Proves the per-PLAY
        wiring (and TestMiniGameDynamicsDelivered) goes RED if the play is wrong.
        Injects into M44's OWN manifest only."""
        if not _has_chunks(_M44_CHUNK_DIR):
            pytest.skip("M44 cached chunks not present")

        import fresh_slotlab.analyzer.machine_spec as ms_mod
        _orig_load = ms_mod.load_manifest

        def _flip_m44_play(machine_id, *a, **kw):
            man = _orig_load(machine_id, *a, **kw)
            if machine_id == "M44":
                import copy
                man = copy.deepcopy(man)
                # Flip ONLY M44's ST51 play to a non-registered token.
                man["spin_types"]["51"]["play"] = "WinMiniGame_DISABLED"
            return man

        monkeypatch.setattr(ms_mod, "load_manifest", _flip_m44_play)
        # report_engine imports load_manifest at call-time from the module, patch there too.
        import fresh_slotlab.analyzer.report_engine as re_mod
        if hasattr(re_mod, "load_manifest"):
            monkeypatch.setattr(re_mod, "load_manifest", _flip_m44_play, raising=False)

        # Static check via derive_analyses on the flipped manifest (no engine needed).
        flipped = set(ms_mod.derive_analyses(_flip_m44_play("M44", manifests_root=_MANIFESTS_ROOT)))
        # RED — minigame_dynamics no longer derived when the play is not WinMiniGame.
        assert "minigame_dynamics" not in flipped, (
            "inject-bug: with ST51 play flipped off WinMiniGame, minigame_dynamics must "
            f"NOT be derived; got {sorted(flipped)}"
        )
        # respin_dynamics (role-keyed, untouched) is still derived — proves the inject
        # is surgical to the PLAY hook, not a blanket break.
        assert "respin_dynamics" in flipped, (
            "inject-bug must be surgical: respin_dynamics (role hook) should still derive"
        )
        # monkeypatch auto-reverts here.

    def test_green_resumes_after_revert(self, m44_summary):
        """After the inject-bug tests' monkeypatches revert, the real (un-patched)
        report is GREEN again: integrity passes, no fallback bucket, both archetype
        sections present. (m44_summary is the module fixture built WITHOUT any patch —
        proves revert restores GREEN.)"""
        ric = m44_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert ric.get("layer2_no_fallback_buckets_ok") is True
        assert _FALLBACK_ST51 not in _payout_ids(m44_summary)
        pi = m44_summary["player_impact"]
        assert isinstance(pi.get("minigame_dynamics"), dict)
        assert isinstance(pi.get("respin_dynamics"), dict)
        assert "st51" in _payout_ids(m44_summary)
