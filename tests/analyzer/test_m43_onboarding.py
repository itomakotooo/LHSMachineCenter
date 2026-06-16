"""M43 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This test asserts STRUCTURE / FLAGS / INVARIANTS, never an RTP value or a count.
The machine's numbers (RTP, hit-rates, openers) change on re-sample / re-tune /
upstream-config drift, so pinning ANY number here would be a brittle false alarm
(charter permanent invariant 1).

What M43 added (session_artifacts/_onboard/M43/03_design.md):
  - configs/machine_manifests/M43.json — ST1 paid_spin/Normal, ST50 respin/WinRespin,
    ST51 settlement/WinMiniGame.
  - fresh_slotlab/analyzer/features/respin_dynamics.py — the ST50 respin mechanic view
    (attached via the `respin` ROLE → machine_spec.ROLE_ANALYSES).
  - fresh_slotlab/analyzer/features/minigame_dynamics.py — the ST51 minigame view
    (attached via the `WinMiniGame` PLAY → machine_spec.PLAY_ANALYSES, NOT the shared
    `settlement` role, so it must NOT leak onto M15's TopDollar settlement).
  - configs/machine_round_win_rules.json m43_minigame_settlement (synthesize_pay_id,
    spin_types=[51], label_format=spin_type) — attributes the whole ST51 win to a single
    real pid `st51` so the RTP-integrity gate passes (_unattributed_st51 → 0).

The whole test runs the REAL engine on the clean 41 real v3 chunks at
rawdata/M43/mode_1 (charter invariant 3: run the real thing; read the real summary).

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
   minigame_dynamics (the ROLE/PLAY wiring did not leak).

Inject-bug → RED → revert → GREEN (TestInjectBugProof):
  monkeypatch load_rules_for_machine → [] (simulates the M43 rule being absent /
  removed from machine_round_win_rules.json). The whole ST51 win then lands in
  _unattributed_st51 → Layer-2 fallback bucket → rtp_integrity_check.passed is NOT True.
  The monkeypatch auto-reverts, so the GREEN state (TestCorrectnessGate) resumes.
  (Both the monkeypatch path AND a literal on-disk removal of the config entry were
  proven manually during authoring; the monkeypatch is used in the committed test
  because it auto-reverts and never mutates a shared config file.)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

# Repo root for locating rawdata.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M43_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M43" / "mode_1"
_M15_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M15" / "mode_1"

# The bet used during M43 sampling (cost=1000 per paid spin). The report is
# value-agnostic; bet only affects coin totals, which this test never asserts.
_BET = 1000

# Reserved fallback-bucket prefix the attribution rule must zero out (rtp_integrity
# Layer 2). The specific bucket for ST51 with no PayoutIdToWinAmount is _unattributed_st51.
_FALLBACK_ST51 = "_unattributed_st51"


# Expected top-level keys (frontend contract — same current schema as M15 e2e).
# NOTE: M43 has no `player_choice` role, so it has NO top-level `topdollar_choice`
# key (unlike M15). We assert a SUPERSET (all required keys present), not equality,
# so machine-specific top-level keys do not make this brittle.
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

# Expected player_impact sub-keys. The standard set PLUS the two M43 mechanic
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
    # M43 NEW mechanic sections (the whole point of this onboarding):
    "respin_dynamics", "minigame_dynamics",
})


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m43_summary():
    if not _has_chunks(_M43_CHUNK_DIR):
        pytest.skip("M43 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks

    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            "M43", 1,
            chunk_dir=_M43_CHUNK_DIR,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists(), (
            "write_summary_json must produce player_impact_summary.json"
        )
        yield summary


@pytest.fixture(scope="module")
def m43_player_impact(m43_summary):
    return m43_summary["player_impact"]


def _payout_ids(summary) -> list[str]:
    return [
        str(r.get("payout_id", ""))
        for r in summary["player_impact"].get("payout_ids_top20", [])
    ]


# ---------------------------------------------------------------------------
# 1. CORRECTNESS GATE — integrity passes; _unattributed_st51 share == 0.
#    VALUE-AGNOSTIC: structure/flags only, no RTP number.
# ---------------------------------------------------------------------------

class TestCorrectnessGate:
    def test_report_generates_with_machine_and_mode(self, m43_summary):
        assert m43_summary["machine"] == "M43"
        assert m43_summary["mode"] == 1
        assert m43_summary["sampling"]["chunks"] > 0
        assert m43_summary["sampling"]["total_spins"] > 0
        # No emit-loop / extract errors surfaced (feedback_no_silent_swallow.md).
        assert not m43_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m43_summary.get('feature_errors')}"
        )

    def test_rtp_integrity_passes(self, m43_summary):
        """rtp_integrity_check.passed must be True (sum(payid)==total, no fallback)."""
        ric = m43_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M43 mode 1. "
            f"Got passed={ric.get('passed')}, message={ric.get('summary_message', 'N/A')}. "
            f"Likely cause: the m43_minigame_settlement round_win rule is not applied → "
            f"ST51 win lands in {_FALLBACK_ST51}."
        )

    def test_layer1_sum_invariant_holds(self, m43_summary):
        """L1 (value-agnostic): sum(pay_id win) == our_total_win — no orphan/double-count."""
        ric = m43_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant broken: {ric.get('layer1_error')}"
        )

    def test_no_unattributed_st51_fallback_bucket(self, m43_summary):
        """The attribution rule holds: NO _unattributed_st51 (Layer-2 fallback) bucket.
        This is the headline value-agnostic guard — 'share == 0' = the bucket is absent."""
        ric = m43_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}. "
            f"The m43_minigame_settlement rule must zero {_FALLBACK_ST51}."
        )
        buckets = ric.get("layer2_fallback_buckets_found") or []
        assert _FALLBACK_ST51 not in buckets, (
            f"{_FALLBACK_ST51} fallback bucket present: {buckets}"
        )
        # And it must not appear as a payout_id row at all.
        pids = _payout_ids(m43_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )

    def test_st51_attributed_to_real_pid(self, m43_summary):
        """The synthesized real pid 'st51' must be present (the minigame as one honest
        feature row). Existence only — NOT its win value."""
        pids = _payout_ids(m43_summary)
        assert "st51" in pids, (
            f"expected synthesized real pid 'st51' from m43_minigame_settlement; "
            f"got payout ids {pids}"
        )


# ---------------------------------------------------------------------------
# 2. SCHEMA / FRONTEND-CONTRACT keys present.
# ---------------------------------------------------------------------------

class TestSchema:
    def test_top_level_keys_superset(self, m43_summary):
        missing = _EXPECTED_TOP_KEYS - set(m43_summary.keys())
        assert not missing, f"Expected top-level keys absent: {sorted(missing)}"

    def test_player_impact_keys_superset(self, m43_player_impact):
        missing = _EXPECTED_PI_KEYS - set(m43_player_impact.keys())
        assert not missing, f"Expected player_impact keys absent: {sorted(missing)}"

    def test_rtp_integrity_check_has_layer_fields(self, m43_summary):
        ric = m43_summary["rtp_integrity_check"]
        for field in ("passed", "layer1_invariant_ok", "layer2_no_fallback_buckets_ok",
                      "layer3_anchors_ok", "summary_message"):
            assert field in ric, f"rtp_integrity_check missing field: {field}"


# ---------------------------------------------------------------------------
# 3. respin_dynamics — DELIVERED metrics populated (structure, not values).
# ---------------------------------------------------------------------------

class TestRespinDynamicsDelivered:
    @pytest.fixture
    def rd(self, m43_player_impact):
        rd = m43_player_impact.get("respin_dynamics")
        assert isinstance(rd, dict), "respin_dynamics section missing"
        return rd

    def test_applicable_and_resolved_spin_types(self, rd):
        """respin_dynamics fired for M43 (ST50 has role=respin) and resolved the STs
        from the manifest (NOT hardcoded ids — feedback_no_hardcode.md)."""
        assert rd.get("applicable") is True, (
            f"respin_dynamics must be applicable for M43; got {rd.get('applicable')} "
            f"reason={rd.get('reason')}"
        )
        assert rd.get("respin_spin_type") == 50, "respin ST must resolve to 50 (role=respin)"
        assert rd.get("base_spin_type") == 1, "base ST must resolve to 1 (role=paid_spin)"

    def test_grant_rate_populated(self, rd):
        """M1 grant-rate: openers + both felt denominators present and non-null
        (M43 really has ST1→ST50 openers, so the rates are computable, not null)."""
        gr = rd["grant_rate"]
        for k in ("openers", "per_winning_paid_spin", "per_paid_spin", "one_per_n_paid_spins"):
            assert k in gr, f"grant_rate missing {k}"
        assert gr["openers"] > 0, "M43 has ST1->ST50 openers; openers must be > 0"
        # Rates are computed (not the null/zero-denominator lie); value-agnostic: just non-null.
        assert gr["per_winning_paid_spin"] is not None
        assert gr["per_paid_spin"] is not None

    def test_hit_rate_uplift_populated(self, rd):
        """M2 hit-rate uplift: respin/base hit-rates + the uplift ratio present and
        computed (a real ratio, not null). Value-agnostic — we don't pin 2.07x."""
        hu = rd["hit_rate_uplift"]
        for k in ("respin_hit_rate", "base_hit_rate", "uplift_ratio"):
            assert k in hu, f"hit_rate_uplift missing {k}"
        assert hu["respin_hit_rate"] is not None
        assert hu["base_hit_rate"] is not None
        assert hu["uplift_ratio"] is not None, "uplift_ratio must be computed (both hit-rates known)"

    def test_multiplier_distributions_populated(self, rd):
        """M2 overlaid distributions: respin + base multiplier-band distributions
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
        """M3 skin-premium symbol/payid mix: respin + base payid shares present.
        M43 ST50 carries real symbol pids 2-9, so respin_payid_share is non-empty."""
        pm = rd["payid_mix"]
        assert "respin_payid_share" in pm and "base_payid_share" in pm
        assert len(pm["respin_payid_share"]) > 0, (
            "respin_payid_share must be populated (ST50 has real symbol pids)"
        )

    def test_rtp_concentration_populated(self, rd):
        """M5 RTP-concentration: contribution + share + fat-tail + loss-rate present."""
        rc = rd["rtp_concentration"]
        for k in ("respin_rtp_contribution_pp", "share_of_all_win",
                  "fat_tail_ge20x_win_share", "loss_rate"):
            assert k in rc, f"rtp_concentration missing {k}"
        assert rc["share_of_all_win"] is not None

    def test_continuity_continuation_prob_populated(self, rd):
        """M4 continuity: the continuation_prob P(respin->respin) IS derivable
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
    def mg(self, m43_player_impact):
        mg = m43_player_impact.get("minigame_dynamics")
        assert isinstance(mg, dict), "minigame_dynamics section missing"
        return mg

    def test_applicable_and_resolved_spin_type(self, mg):
        """minigame_dynamics fired via the WinMiniGame PLAY (NOT the settlement role)
        and resolved ST51 from the manifest (feedback_no_hardcode.md)."""
        assert mg.get("applicable") is True, (
            f"minigame_dynamics must be applicable for M43; got {mg.get('applicable')} "
            f"reason={mg.get('reason')}"
        )
        assert mg.get("minigame_spin_type") == 51, "minigame ST must resolve to 51 (play=WinMiniGame)"
        assert mg.get("attributed_pay_id") == "st51", (
            "minigame must point at its synthesized pid st51"
        )

    def test_multiplier_distribution_populated(self, mg):
        """G1 multiplier distribution (machine's own win/bet banding): non-empty bands
        + a modal band + dominant-band share present. Value-agnostic — no 88.5% pin."""
        md = mg["multiplier_distribution"]
        assert isinstance(md.get("bands"), list) and len(md["bands"]) > 0, (
            "multiplier_distribution.bands must be a non-empty histogram"
        )
        for k in ("total_events", "modal_band", "dominant_band_share", "source"):
            assert k in md, f"multiplier_distribution missing {k}"
        assert md["modal_band"] is not None
        assert md["dominant_band_share"] is not None

    def test_trigger_frequency_populated(self, mg):
        """G2 trigger frequency: events + per-paid-spin rate present and computed."""
        tf = mg["trigger_frequency"]
        for k in ("minigame_events", "per_paid_spin", "one_per_n_paid_spins"):
            assert k in tf, f"trigger_frequency missing {k}"
        assert tf["minigame_events"] > 0, "M43 has minigame events; count must be > 0"
        assert tf["per_paid_spin"] is not None

    def test_trigger_context_counts_populated(self, mg):
        """G3 (the derivable part): trigger-context transition COUNTS by source ST
        (base vs respin burst) are present — the surprise-on-loss RATE itself is
        parser-blind (asserted separately in TestDeferredMetricsFlagged)."""
        tc = mg["trigger_context"]
        for k in ("opener_from_base_spin", "opener_from_respin_burst",
                  "share_from_base_spin", "share_from_respin_burst"):
            assert k in tc, f"trigger_context missing {k}"

    def test_rtp_concentration_populated(self, mg):
        """G6 RTP-concentration (the big-win engine): contribution + share + event-rate
        + hit-rate present and computed. Value-agnostic — no 30.7% pin."""
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
    def test_minigame_node_path_analysis_flagged_unavailable(self, m43_player_impact):
        """G4/G5 node path is parser-blind: available==False with parser_blind reasons.
        (If a future change fakes the node-count/node-code tables, available would flip
        True / the parser_blind list would shrink — this goes RED.)"""
        npa = m43_player_impact["minigame_dynamics"]["node_path_analysis"]
        assert npa.get("available") is False, (
            "node_path_analysis.available must be False (G4/G5 are parser-blind, NOT "
            "fabricated). If True, someone faked the node path tables."
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

    def test_minigame_surprise_on_loss_flagged_parser_blind(self, m43_player_impact):
        """G3 ⭐ surprise-on-loss RATE is parser-blind (the win/loss status of the
        specific preceding base spin is not in the transition counts). The marker must
        EXIST under trigger_context.parser_blind — NOT emitted as a fabricated number."""
        tc = m43_player_impact["minigame_dynamics"]["trigger_context"]
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

    def test_respin_continuity_parser_blind_present(self, m43_player_impact):
        """M4 burst-length histogram + win-gating proof are parser-blind. The marker
        must EXIST under continuity.parser_blind (the continuation_prob IS delivered;
        only the burst-length SHAPE is blind)."""
        cont = m43_player_impact["respin_dynamics"]["continuity"]
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
# 6. M15 UNTOUCHED — the ROLE/PLAY wiring did not leak onto M15.
#    minigame_dynamics is keyed on the WinMiniGame PLAY, NOT the `settlement` role
#    (which M15's ST15 TopDollar settlement ALSO uses) — so it must NOT fire on M15.
#    respin_dynamics is keyed on the `respin` role, which M15 does not have.
# ---------------------------------------------------------------------------

class TestM15NotLeaked:
    @pytest.fixture(scope="class")
    def m15_summary(self):
        if not _has_chunks(_M15_CHUNK_DIR):
            pytest.skip("M15 cached chunks not present")
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            return generate_report_from_chunks(
                "M15", 1,
                chunk_dir=_M15_CHUNK_DIR,
                output_dir=Path(tmpdir),
                bet=_BET,
            )

    def test_m15_report_generates_and_integrity_passes(self, m15_summary):
        assert m15_summary["machine"] == "M15"
        assert m15_summary["rtp_integrity_check"].get("passed") is True, (
            "M15 integrity must still pass (onboarding M43 must not regress M15)"
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


# ---------------------------------------------------------------------------
# INJECT-BUG PROOF — remove the M43 round_win rule → RED → (auto-revert) → GREEN.
#
# The key safety claim of this onboarding is: the m43_minigame_settlement rule
# zeroes _unattributed_st51. This proves the guard above (TestCorrectnessGate)
# actually goes RED when the rule is absent. The monkeypatch auto-reverts, so the
# module-scoped m43_summary (built without the patch) stays GREEN.
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_no_m43_rule_reintroduces_unattributed_st51(self, monkeypatch):
        """INJECT: load_rules_for_machine → [] (the M43 rule is gone). Assert the
        ST51 win lands in _unattributed_st51 (Layer-2 fallback) and integrity FAILS —
        VALUE-AGNOSTIC (the fallback bucket is the signature, not an RTP number)."""
        if not _has_chunks(_M43_CHUNK_DIR):
            pytest.skip("M43 cached chunks not present")

        import fresh_slotlab.round_win as rw_mod

        def _no_rules(machine_id, config):
            return []  # BUG: drop ALL round_win rules (M43 rule removed)

        monkeypatch.setattr(rw_mod, "load_rules_for_machine", _no_rules)

        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks

        with tempfile.TemporaryDirectory() as tmpdir:
            summary = generate_report_from_chunks(
                "M43", 1,
                chunk_dir=_M43_CHUNK_DIR,
                output_dir=Path(tmpdir),
                bet=_BET,
            )
            ric = summary.get("rtp_integrity_check", {})
            pids = _payout_ids(summary)

            # RED 1 — the _unattributed_st51 fallback bucket reappears.
            assert _FALLBACK_ST51 in pids, (
                f"inject-bug: without the M43 rule, ST51 win must land in {_FALLBACK_ST51}; "
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

    def test_green_resumes_after_revert(self, m43_summary):
        """After the inject-bug test's monkeypatch reverts, the real (un-patched)
        report is GREEN again: integrity passes and no fallback bucket. (m43_summary is
        the module fixture built WITHOUT the patch — proves revert restores GREEN.)"""
        ric = m43_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert ric.get("layer2_no_fallback_buckets_ok") is True
        assert _FALLBACK_ST51 not in _payout_ids(m43_summary)
