"""M279 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This test asserts STRUCTURE / FLAGS / INVARIANTS, never an RTP value or a count.
M279's numbers (RTP, hit-rates, openers, cell map) change on re-sample / re-tune /
upstream-config drift, so pinning ANY number here would be a brittle false alarm
(charter permanent invariant 1). The ONLY hard numbers asserted are STRUCTURAL
identifiers fixed by the manifest / rawdata protocol (the SpinType ids 140/36/2,
the 12-cell / cells-8&10 jackpot shape that the design records as the FIXED wheel
layout) — never an RTP or an observed frequency.

What M279 added (session_artifacts/_onboard/M279/03_design.md):
  - configs/machine_manifests/M279.json — ST140 paid_spin/NormalCollectionSpin,
    ST36 respin/MoveSpin, ST2 settlement/Wheel.
  - fresh_slotlab/analyzer/features/wheel_dynamics.py — the ST2 Wheel collect-
    settlement mechanic view (attached via the `Wheel` PLAY → machine_spec.
    PLAY_ANALYSES, NOT the shared `settlement` role, so it must NOT leak onto M15's
    TopDollar settlement or M43's WinMiniGame settlement).
  - PLAY_ANALYSES["Wheel"] = ("wheel_dynamics",) in machine_spec.py (the play hook).
  - configs/machine_round_win_rules.json m279_wheel_settlement (synthesize_pay_id,
    spin_types=[2], label_format=spin_type) — attributes the whole ST2 win to a
    single real pid `st2` so the RTP-integrity gate passes (_unattributed_st2 → 0).
  - REUSED (NOT redesigned): respin_dynamics (via the `respin` role on ST36) and
    collect_mechanic (CROSS_CUTTING, self-detecting the 1000-spin metronome).

The whole test runs the REAL engine on the real cached chunks at
rawdata/M279/mode_1 (charter invariant 3: run the real thing; read the real summary).

Tests
-----
1. report generates; rtp_integrity_check.passed == True; _unattributed_st2 share == 0
   (no fallback bucket; the m279_wheel_settlement rule holds) — VALUE-AGNOSTIC.
2. the 3 STs present with the correct role/play (140 paid_spin/NormalCollectionSpin,
   36 respin/MoveSpin, 2 settlement/Wheel) — verified from the manifest AND from how
   the role/play-keyed analyses resolve their SpinTypes in the report.
3. schema / frontend-contract keys present (top-level + player_impact.*).
4. wheel_dynamics present + its fields populated; the cell→prize map + distinct
   prize distribution are now DATA-DERIVED via the wheel_cells extractor (no longer
   parser_blind): every cell observed + deterministic, jackpot == max(observed
   prizes) @ argmax cells — asserted value-agnostically (populated/deterministic/
   data-derived, NOT the literal prize values).
5. respin_dynamics applicable (via the respin role) + grant_rate.openers present.
6. collect_mechanic present (TOP-LEVEL) + detected_cycle_length present.
7. NON-LEAK: M15 / M43 have NO wheel_dynamics (the `Wheel` PLAY scoping held);
   M279 has NO minigame_dynamics (no `WinMiniGame` play → not even in its derived set).

Inject-bug → RED → revert → GREEN (TestInjectBugProof):
  - monkeypatch load_rules_for_machine → [] (the m279_wheel_settlement rule absent):
    the whole ST2 win lands in _unattributed_st2 → Layer-2 fallback bucket →
    rtp_integrity_check.passed is NOT True. Auto-reverts.
  - monkeypatch machine_spec.PLAY_ANALYSES without "Wheel" (the play hook broken):
    wheel_dynamics is absent from the report. Integrity still passes (the synth rule
    still attributes st2) — proving the wiring break is isolated. Auto-reverts.
  Each inject-bug was ALSO run manually during authoring (the RED was observed on the
  real chunks before this file was committed), and the GREEN resumes from the
  un-patched module-scoped fixture (TestCorrectnessGate).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# Repo root for locating rawdata + the manifest.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M279_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M279" / "mode_1"
_M15_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M15" / "mode_1"
_M43_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M43" / "mode_1"
_M279_MANIFEST = _REPO_ROOT / "configs" / "machine_manifests" / "M279.json"

# The bet used during M279 sampling (cost=1000 per paid spin). The report is
# value-agnostic; bet only affects coin totals, which this test never asserts.
_BET = 1000

# Reserved fallback-bucket prefix the attribution rule must zero out (rtp_integrity
# Layer 2). The specific bucket for ST2 with no PayoutIdToWinAmount is _unattributed_st2.
_FALLBACK_ST2 = "_unattributed_st2"

# Structural SpinType ids fixed by the rawdata protocol + manifest (NOT values that
# drift on re-sample): the base grind, the wild-nudge respin, the wheel settlement.
_ST_BASE = 140
_ST_RESPIN = 36
_ST_WHEEL = 2


# Expected top-level keys (frontend contract — same current schema as M15/M43 e2e).
# NOTE: M279 has no `player_choice` role, so it has NO top-level `topdollar_choice`
# key (unlike M15). We assert a SUPERSET (all required keys present), not equality.
# collect_mechanic lives at TOP-LEVEL (not under player_impact).
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

# Expected player_impact sub-keys. The standard set PLUS the M279 mechanic sections
# (respin_dynamics via the respin role; wheel_dynamics via the Wheel play). We assert
# these are all present (superset), never equality.
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
    # M279 mechanic sections (the whole point of this onboarding):
    "respin_dynamics", "wheel_dynamics",
})


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m279_summary():
    if not _has_chunks(_M279_CHUNK_DIR):
        pytest.skip("M279 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks

    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            "M279", 1,
            chunk_dir=_M279_CHUNK_DIR,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists(), (
            "write_summary_json must produce player_impact_summary.json"
        )
        yield summary


@pytest.fixture(scope="module")
def m279_player_impact(m279_summary):
    return m279_summary["player_impact"]


@pytest.fixture(scope="module")
def m279_manifest():
    if not _M279_MANIFEST.exists():
        pytest.skip("M279 manifest not present")
    return json.loads(_M279_MANIFEST.read_text(encoding="utf-8"))


def _payout_ids(summary) -> list[str]:
    return [
        str(r.get("payout_id", ""))
        for r in summary["player_impact"].get("payout_ids_top20", [])
    ]


def _stb_spin_types(player_impact) -> set[int]:
    out: set[int] = set()
    for row in player_impact.get("spin_type_breakdown", []):
        try:
            out.add(int(row.get("spin_type")))
        except (TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------------------
# 1. CORRECTNESS GATE — integrity passes; _unattributed_st2 share == 0.
#    VALUE-AGNOSTIC: structure/flags only, no RTP number.
# ---------------------------------------------------------------------------

class TestCorrectnessGate:
    def test_report_generates_with_machine_and_mode(self, m279_summary):
        assert m279_summary["machine"] == "M279"
        assert m279_summary["mode"] == 1
        assert m279_summary["sampling"]["chunks"] > 0
        assert m279_summary["sampling"]["total_spins"] > 0
        # No emit-loop / extract errors surfaced (feedback_no_silent_swallow.md).
        assert not m279_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m279_summary.get('feature_errors')}"
        )

    def test_rtp_integrity_passes(self, m279_summary):
        """rtp_integrity_check.passed must be True (sum(payid)==total, no fallback)."""
        ric = m279_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M279 mode 1. "
            f"Got passed={ric.get('passed')}, message={ric.get('summary_message', 'N/A')}. "
            f"Likely cause: the m279_wheel_settlement round_win rule is not applied → "
            f"ST2 win lands in {_FALLBACK_ST2}."
        )

    def test_layer1_sum_invariant_holds(self, m279_summary):
        """L1 (value-agnostic): sum(pay_id win) == our_total_win — no orphan/double-count."""
        ric = m279_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant broken: {ric.get('layer1_error')}"
        )

    def test_no_unattributed_st2_fallback_bucket(self, m279_summary):
        """The attribution rule holds: NO _unattributed_st2 (Layer-2 fallback) bucket.
        This is the headline value-agnostic guard — 'share == 0' = the bucket is absent."""
        ric = m279_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}. "
            f"The m279_wheel_settlement rule must zero {_FALLBACK_ST2}."
        )
        buckets = ric.get("layer2_fallback_buckets_found") or []
        assert _FALLBACK_ST2 not in buckets, (
            f"{_FALLBACK_ST2} fallback bucket present: {buckets}"
        )
        # And it must not appear as a payout_id row at all.
        pids = _payout_ids(m279_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )

    def test_st2_attributed_to_real_pid(self, m279_summary):
        """The synthesized real pid 'st2' must be present (the wheel as one honest
        feature row). Existence only — NOT its win value."""
        pids = _payout_ids(m279_summary)
        assert "st2" in pids, (
            f"expected synthesized real pid 'st2' from m279_wheel_settlement; "
            f"got payout ids {pids}"
        )


# ---------------------------------------------------------------------------
# 2. THE THREE SPINTYPES — correct role/play, all present.
#    role/play come from the manifest (the source of truth); the report's
#    role-/play-keyed analyses prove the wiring resolved the right SpinTypes.
# ---------------------------------------------------------------------------

class TestThreeSpinTypes:
    def test_manifest_declares_three_st_roles_and_plays(self, m279_manifest):
        """The manifest is the source of truth for role/play (feedback_no_hardcode.md
        — analyses resolve from here, not literals). 140 paid_spin/NormalCollectionSpin,
        36 respin/MoveSpin, 2 settlement/Wheel."""
        st = m279_manifest["spin_types"]
        assert st[str(_ST_BASE)]["role"] == "paid_spin"
        assert st[str(_ST_BASE)]["play"] == "NormalCollectionSpin"
        assert st[str(_ST_RESPIN)]["role"] == "respin"
        assert st[str(_ST_RESPIN)]["play"] == "MoveSpin"
        assert st[str(_ST_WHEEL)]["role"] == "settlement"
        assert st[str(_ST_WHEEL)]["play"] == "Wheel"

    def test_report_contains_the_three_spin_types(self, m279_player_impact):
        """The real report's per-ST breakdown carries exactly the three onboarded STs
        (a superset check: at minimum 140/36/2 are present)."""
        sts = _stb_spin_types(m279_player_impact)
        for st in (_ST_BASE, _ST_RESPIN, _ST_WHEEL):
            assert st in sts, f"ST{st} missing from spin_type_breakdown; got {sorted(sts)}"

    def test_respin_role_resolved_to_st36_base_st140(self, m279_player_impact):
        """The `respin` ROLE hook resolved respin_st=36 / base_st=140 from the manifest
        (proves the role/play declaration is wired, not just declared)."""
        rd = m279_player_impact.get("respin_dynamics") or {}
        assert rd.get("respin_spin_type") == _ST_RESPIN, (
            f"respin ST must resolve to {_ST_RESPIN} (role=respin); got {rd.get('respin_spin_type')}"
        )
        assert rd.get("base_spin_type") == _ST_BASE, (
            f"base ST must resolve to {_ST_BASE} (role=paid_spin); got {rd.get('base_spin_type')}"
        )

    def test_wheel_play_resolved_to_st2(self, m279_player_impact):
        """The `Wheel` PLAY hook resolved wheel_st=2 from the manifest."""
        wd = m279_player_impact.get("wheel_dynamics") or {}
        assert wd.get("wheel_spin_type") == _ST_WHEEL, (
            f"wheel ST must resolve to {_ST_WHEEL} (play=Wheel); got {wd.get('wheel_spin_type')}"
        )


# ---------------------------------------------------------------------------
# 3. SCHEMA / FRONTEND-CONTRACT keys present.
# ---------------------------------------------------------------------------

class TestSchema:
    def test_top_level_keys_superset(self, m279_summary):
        missing = _EXPECTED_TOP_KEYS - set(m279_summary.keys())
        assert not missing, f"Expected top-level keys absent: {sorted(missing)}"

    def test_player_impact_keys_superset(self, m279_player_impact):
        missing = _EXPECTED_PI_KEYS - set(m279_player_impact.keys())
        assert not missing, f"Expected player_impact keys absent: {sorted(missing)}"

    def test_rtp_integrity_check_has_layer_fields(self, m279_summary):
        ric = m279_summary["rtp_integrity_check"]
        for field in ("passed", "layer1_invariant_ok", "layer2_no_fallback_buckets_ok",
                      "layer3_anchors_ok", "summary_message"):
            assert field in ric, f"rtp_integrity_check missing field: {field}"


# ---------------------------------------------------------------------------
# 4. wheel_dynamics — BASE-DERIVABLE fields populated; parser_blind FLAGGED.
# ---------------------------------------------------------------------------

class TestWheelDynamicsDelivered:
    @pytest.fixture
    def wd(self, m279_player_impact):
        wd = m279_player_impact.get("wheel_dynamics")
        assert isinstance(wd, dict), "wheel_dynamics section missing"
        return wd

    def test_applicable_and_attributed_pid(self, wd):
        """wheel_dynamics fired via the Wheel PLAY (NOT the settlement role) and points
        at its synthesized pid st2 (feedback_no_hardcode.md)."""
        assert wd.get("applicable") is True, (
            f"wheel_dynamics must be applicable for M279; got {wd.get('applicable')} "
            f"reason={wd.get('reason')}"
        )
        assert wd.get("attributed_pay_id") == "st2", (
            "wheel must point at its synthesized pid st2"
        )

    def test_guaranteed_payout_populated(self, wd):
        """W1 guaranteed-payout / cadence: hit_rate + events + one_per_n_paid_spins
        present and computed. The wheel ALWAYS pays (guaranteed flag derivable). Value-
        agnostic — we do NOT pin hit_rate==1.0 or cadence==1000."""
        gp = wd["guaranteed_payout"]
        for k in ("hit_rate", "win_rounds", "events", "guaranteed", "one_per_n_paid_spins"):
            assert k in gp, f"guaranteed_payout missing {k}"
        assert gp["events"] > 0, "M279 has wheel events; events must be > 0"
        assert gp["hit_rate"] is not None, "hit_rate must be computed (events known)"
        assert gp["one_per_n_paid_spins"] is not None, (
            "the metronome cadence is derivable (base_spins / wheel_events); must not be null"
        )
        assert isinstance(gp["guaranteed"], bool), "guaranteed must be a bool flag"

    def test_prize_distribution_distinct_prizes_data_derived(self, wd):
        """W2 ⭐ UPDATED (wheel_cells de-hardcode): the prize distribution is now the
        DATA-DERIVED set of DISTINCT prizes (un-merged from the exact cell→prize map
        via the wheel_cells extractor), NOT the old coarse RETURN_BUCKET banding that
        merged 20×/30×. Each prize carries {prize_multiplier, prob, hit_count,
        win_share}. Value-agnostic — no probability or multiplier VALUE is pinned;
        we assert the SET STRUCTURE + cardinality logic + un-merge consistency."""
        pd = wd["prize_distribution"]
        assert pd.get("available") is True, (
            f"prize_distribution must be available (data-derived); got {pd.get('available')}"
        )
        prizes = pd.get("prizes")
        assert isinstance(prizes, list) and len(prizes) > 0, (
            "prize_distribution.prizes must be a non-empty DISTINCT-prize list"
        )
        for k in ("total_events", "distinct_prize_count", "modal_prize_multiplier",
                  "dominant_prize_share", "jackpot_prize_multiplier", "source"):
            assert k in pd, f"prize_distribution missing {k}"
        assert pd["modal_prize_multiplier"] is not None
        assert pd["dominant_prize_share"] is not None
        for prize in prizes:
            for k in ("prize_multiplier", "prob", "hit_count", "win_share"):
                assert k in prize, f"distribution prize malformed (missing {k}): {prize}"
        # The distribution's prize SET equals the cell-map distinct-prize SET, and
        # its cardinality equals distinct_prize_count (un-merged EXACTLY — no merge,
        # no fabricated split). This is the value-agnostic replacement for the old
        # "merged_band_present" / parser_blind un-merge flag.
        cm = wd["cell_map"]
        cm_distinct = set(cm.get("distinct_prizes") or [])
        pd_distinct = {p.get("prize_multiplier") for p in prizes}
        assert pd_distinct == cm_distinct, (
            f"the prize-distribution prize SET ({sorted(pd_distinct)}) must equal the "
            f"cell-map distinct-prize SET ({sorted(cm_distinct)}) — un-merged exactly"
        )
        assert pd["distinct_prize_count"] == len(cm_distinct)
        # The source must declare it data-derived (no hardcoded ladder, no merge).
        src = str(pd.get("source", "")).lower()
        assert "wheel_cells" in src, (
            f"prize_distribution.source must cite the wheel_cells extractor; got {pd.get('source')!r}"
        )

    def test_cell_map_delivered_data_derived(self, wd):
        """W3 ⭐ CONVERTED (was test_cell_map_flagged_parser_blind): the wheel_cells
        extractor now DELIVERS M279's cell map data-derived — it is NO LONGER
        parser_blind. The OLD reality (available:False + a parser_blind list + the
        hardcoded {8,10} jackpot SHAPE) is replaced by the NEW reality: available
        True, every cell observed + deterministic, jackpot data-derived (==max of
        observed prizes / argmax cells). VALUE-AGNOSTIC: we assert it is POPULATED +
        DETERMINISTIC + data-derived, NOT the literal prize values (100×, 30× etc.
        drift on re-tune; the structure/derivation invariants do not)."""
        cm = wd["cell_map"]
        # NEW: the map is DELIVERED, not parser-blind.
        assert cm.get("available") is True, (
            "cell_map.available must now be True — the wheel_cells extractor DELIVERS "
            f"M279's cell map data-derived. Got available={cm.get('available')} "
            f"reason={cm.get('reason')}. (Old reality was parser_blind/False.)"
        )
        assert "parser_blind" not in cm, (
            "the cell map is no longer parser_blind — the parser_blind list must be GONE"
        )
        # Data-derived source (not a hardcoded ladder).
        src = str(cm.get("source", "")).lower()
        assert "wheel_cells" in src and ("not hardcoded" in src or "derived" in src), (
            f"cell_map.source must declare it data-derived; got {cm.get('source')!r}"
        )
        # The fixed physical wheel size (a manifest structural fact).
        assert cm.get("wheel_cell_count") == 12, "the wheel's fixed cell count (12) is recorded"

        # POPULATED: every observed cell maps to exactly one (non-null) prize.
        observed = cm.get("observed_cells") or []
        assert len(observed) > 0, "M279 has observed wheel cells"
        cells = {int(c["cell"]): c for c in cm["cells"]}
        for cell in observed:
            assert cells[int(cell)]["prize_multiplier"] is not None, (
                f"observed cell {cell} must map to exactly one (non-null) prize"
            )

        # DETERMINISTIC: no cell paid >1 distinct prize (the alarm is silent).
        assert not cm.get("nondeterministic_cells"), (
            f"M279's cells are deterministic; nondeterministic_cells must be empty, "
            f"got {cm.get('nondeterministic_cells')}"
        )

        # JACKPOT data-derived: == max(observed distinct prizes), cells == argmax.
        distinct = cm.get("distinct_prizes") or []
        assert len(distinct) > 0
        jackpot = cm.get("jackpot") or {}
        assert jackpot.get("prize_multiplier") == max(distinct), (
            f"jackpot.prize_multiplier ({jackpot.get('prize_multiplier')}) must equal "
            f"max(observed distinct prizes) ({max(distinct)}) — data-derived, not a literal"
        )
        max_prize = jackpot["prize_multiplier"]
        expected_cells = sorted(
            int(c["cell"]) for c in cm["cells"]
            if c["observed"] and c["prize_multiplier"] == max_prize
        )
        assert sorted(jackpot.get("cells") or []) == expected_cells, (
            f"jackpot.cells must be exactly the cell(s) paying the max prize "
            f"({expected_cells}); got {jackpot.get('cells')}"
        )
        assert len(expected_cells) > 0

    def test_rtp_concentration_populated(self, wd):
        """W4 RTP-concentration: contribution + share + event-rate + hit-rate present
        and computed. Value-agnostic — no 4.34% pin."""
        rc = wd["rtp_concentration"]
        for k in ("wheel_rtp_contribution_pp", "share_of_all_win", "event_rate", "hit_rate"):
            assert k in rc, f"rtp_concentration missing {k}"
        assert rc["share_of_all_win"] is not None
        assert rc["event_rate"] is not None


# ---------------------------------------------------------------------------
# 5. respin_dynamics — DELIVERED via the respin ROLE (structure, not values).
# ---------------------------------------------------------------------------

class TestRespinDynamicsDelivered:
    @pytest.fixture
    def rd(self, m279_player_impact):
        rd = m279_player_impact.get("respin_dynamics")
        assert isinstance(rd, dict), "respin_dynamics section missing"
        return rd

    def test_applicable_via_respin_role(self, rd):
        """respin_dynamics fired for M279 (ST36 has role=respin) — the REUSED generic
        role-level mechanic attaches by role, no fork."""
        assert rd.get("applicable") is True, (
            f"respin_dynamics must be applicable for M279; got {rd.get('applicable')} "
            f"reason={rd.get('reason')}"
        )

    def test_grant_rate_openers_present(self, rd):
        """M1 grant-rate: openers present and > 0 (M279 really has ST140→ST36 openers).
        Value-agnostic — we do NOT pin 145242."""
        gr = rd["grant_rate"]
        for k in ("openers", "per_winning_paid_spin", "per_paid_spin", "one_per_n_paid_spins"):
            assert k in gr, f"grant_rate missing {k}"
        assert gr["openers"] > 0, "M279 has ST140->ST36 openers; openers must be > 0"
        assert gr["per_paid_spin"] is not None, "the move grant rate is computable, not null"


# ---------------------------------------------------------------------------
# 6. collect_mechanic — TOP-LEVEL, with the cycle metronome detected.
# ---------------------------------------------------------------------------

class TestCollectMechanic:
    def test_collect_mechanic_top_level_applicable(self, m279_summary):
        """collect_mechanic lives at TOP-LEVEL summary['collect_mechanic'] (NOT under
        player_impact) and is applicable (M279's CollectCount metronome)."""
        assert "collect_mechanic" in m279_summary, (
            "collect_mechanic must be a TOP-LEVEL summary key"
        )
        assert "collect_mechanic" not in m279_summary["player_impact"], (
            "collect_mechanic must NOT be under player_impact (it is top-level)"
        )
        cm = m279_summary["collect_mechanic"]
        assert cm.get("applicable") is True, (
            f"collect_mechanic must be applicable for M279; got {cm.get('applicable')}"
        )

    def test_detected_cycle_length_present(self, m279_summary):
        """The metronome period is detected (detected_cycle_length present and non-null).
        Value-agnostic — we do NOT pin 1000."""
        bcc = m279_summary["collect_mechanic"].get("bonus_cycle_correction") or {}
        assert "detected_cycle_length" in bcc, (
            "bonus_cycle_correction must carry detected_cycle_length"
        )
        assert bcc["detected_cycle_length"] is not None, (
            "M279's collect cycle IS detectable; detected_cycle_length must not be null"
        )
        assert bcc["detected_cycle_length"] > 0


# ---------------------------------------------------------------------------
# 7. NON-LEAK — the ROLE/PLAY wiring did not cross-fire.
#
#    wheel_dynamics is keyed on the Wheel PLAY, NOT the `settlement` role (which
#    M15's ST15 TopDollar and M43's ST51 WinMiniGame settlements ALSO use) — so it
#    must NOT fire on M15 or M43. minigame_dynamics is keyed on the WinMiniGame PLAY,
#    which M279 does not have — so it must NOT fire on M279 (not even applicable:False;
#    it is not in M279's derived analysis set at all).
# ---------------------------------------------------------------------------

class TestNonLeak:
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

    @pytest.fixture(scope="class")
    def m43_summary(self):
        if not _has_chunks(_M43_CHUNK_DIR):
            pytest.skip("M43 cached chunks not present")
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            return generate_report_from_chunks(
                "M43", 1,
                chunk_dir=_M43_CHUNK_DIR,
                output_dir=Path(tmpdir),
                bet=_BET,
            )

    def test_m15_report_generates_and_integrity_passes(self, m15_summary):
        assert m15_summary["machine"] == "M15"
        assert m15_summary["rtp_integrity_check"].get("passed") is True, (
            "M15 integrity must still pass (onboarding M279 must not regress M15)"
        )

    def test_m15_has_no_wheel_dynamics(self, m15_summary):
        """wheel_dynamics is keyed on the Wheel PLAY, NOT the `settlement` role that
        M15's ST15 TopDollar shares. The PLAY_ANALYSES scoping prevents this leak."""
        assert "wheel_dynamics" not in m15_summary["player_impact"], (
            "wheel_dynamics LEAKED onto M15 — it must be keyed on the Wheel PLAY, NOT "
            "the `settlement` role M15's ST15 shares."
        )

    def test_m43_report_generates_and_integrity_passes(self, m43_summary):
        assert m43_summary["machine"] == "M43"
        assert m43_summary["rtp_integrity_check"].get("passed") is True, (
            "M43 integrity must still pass (onboarding M279 must not regress M43)"
        )

    def test_m43_has_no_wheel_dynamics(self, m43_summary):
        """M43's ST51 (WinMiniGame) settlement shares the `settlement` role with M279's
        ST2 Wheel — but wheel_dynamics keys on the Wheel PLAY, which M43 does not have."""
        assert "wheel_dynamics" not in m43_summary["player_impact"], (
            "wheel_dynamics LEAKED onto M43 — the Wheel PLAY must not match M43's "
            "WinMiniGame settlement."
        )

    def test_m279_has_no_minigame_dynamics(self, m279_player_impact):
        """M279 has no `WinMiniGame` play, so minigame_dynamics is NOT in its derived
        analysis set at all (not even applicable:False). The converse non-leak."""
        assert "minigame_dynamics" not in m279_player_impact, (
            "minigame_dynamics LEAKED onto M279 — it is keyed on the WinMiniGame PLAY, "
            "which M279 does not declare. derive_analyses must not add it."
        )


# ---------------------------------------------------------------------------
# INJECT-BUG PROOF — break each safety claim → RED → (auto-revert) → GREEN.
#
# Claim A: the m279_wheel_settlement rule zeroes _unattributed_st2 (integrity).
# Claim B: the PLAY_ANALYSES["Wheel"] wiring attaches wheel_dynamics.
#
# Both monkeypatches auto-revert, so the module-scoped m279_summary (built without
# any patch) stays GREEN (TestCorrectnessGate + TestWheelDynamicsDelivered above).
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_no_m279_rule_reintroduces_unattributed_st2(self, monkeypatch):
        """INJECT (Claim A): load_rules_for_machine → [] (the m279_wheel_settlement
        rule is gone). Assert the ST2 win lands in _unattributed_st2 (Layer-2 fallback)
        and integrity FAILS — VALUE-AGNOSTIC (the fallback bucket is the signature,
        not an RTP number)."""
        if not _has_chunks(_M279_CHUNK_DIR):
            pytest.skip("M279 cached chunks not present")

        import fresh_slotlab.round_win as rw_mod

        def _no_rules(machine_id, config):
            return []  # BUG: drop ALL round_win rules (M279 rule removed)

        monkeypatch.setattr(rw_mod, "load_rules_for_machine", _no_rules)

        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks

        with tempfile.TemporaryDirectory() as tmpdir:
            summary = generate_report_from_chunks(
                "M279", 1,
                chunk_dir=_M279_CHUNK_DIR,
                output_dir=Path(tmpdir),
                bet=_BET,
            )
            ric = summary.get("rtp_integrity_check", {})
            pids = _payout_ids(summary)

            # RED 1 — the _unattributed_st2 fallback bucket reappears.
            assert _FALLBACK_ST2 in pids, (
                f"inject-bug: without the M279 rule, ST2 win must land in {_FALLBACK_ST2}; "
                f"got payout ids {pids}"
            )
            # RED 2 — Layer 2 flags the fallback bucket.
            assert ric.get("layer2_no_fallback_buckets_ok") is False, (
                f"inject-bug: Layer-2 must flag the fallback bucket; "
                f"got layer2_no_fallback_buckets_ok={ric.get('layer2_no_fallback_buckets_ok')}, "
                f"buckets={ric.get('layer2_fallback_buckets_found')}"
            )
            assert _FALLBACK_ST2 in (ric.get("layer2_fallback_buckets_found") or [])
            # RED 3 — overall integrity is NOT passing.
            assert ric.get("passed") is not True, (
                f"inject-bug: rtp_integrity_check.passed must NOT be True; got {ric.get('passed')}"
            )
            # RED 4 — the synthesized real pid 'st2' is gone (no attribution).
            assert "st2" not in pids, (
                f"inject-bug: real pid 'st2' must be absent without the rule; got {pids}"
            )
        # monkeypatch auto-reverts here — the module-scoped GREEN fixture is unaffected.

    def test_inject_break_wheel_play_wiring_drops_wheel_dynamics(self, monkeypatch):
        """INJECT (Claim B): remove "Wheel" from machine_spec.PLAY_ANALYSES (the play
        hook broken). Assert wheel_dynamics is ABSENT from the report. Integrity STILL
        passes (the synth rule still attributes st2) — proving the wiring break is
        isolated to the analysis, not the attribution."""
        if not _has_chunks(_M279_CHUNK_DIR):
            pytest.skip("M279 cached chunks not present")

        import fresh_slotlab.analyzer.machine_spec as ms

        patched = {k: v for k, v in ms.PLAY_ANALYSES.items() if k != "Wheel"}
        monkeypatch.setattr(ms, "PLAY_ANALYSES", patched)

        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks

        with tempfile.TemporaryDirectory() as tmpdir:
            summary = generate_report_from_chunks(
                "M279", 1,
                chunk_dir=_M279_CHUNK_DIR,
                output_dir=Path(tmpdir),
                bet=_BET,
            )
            pi = summary["player_impact"]
            # RED — wheel_dynamics is absent (the Wheel play no longer attaches it).
            assert "wheel_dynamics" not in pi, (
                "inject-bug: with PLAY_ANALYSES['Wheel'] removed, wheel_dynamics must be "
                f"absent from the report; got keys {sorted(pi.keys())}"
            )
            # The attribution (the synth rule) is independent and still holds.
            assert summary["rtp_integrity_check"].get("passed") is True, (
                "inject-bug: breaking the wheel_dynamics wiring must NOT break integrity "
                "(the m279_wheel_settlement rule still attributes st2)"
            )
        # monkeypatch auto-reverts here.

    def test_green_resumes_after_revert(self, m279_summary):
        """After the inject-bug monkeypatches revert, the real (un-patched) report is
        GREEN again: integrity passes, no fallback bucket, wheel_dynamics present.
        (m279_summary is the module fixture built WITHOUT any patch.)"""
        ric = m279_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert ric.get("layer2_no_fallback_buckets_ok") is True
        assert _FALLBACK_ST2 not in _payout_ids(m279_summary)
        assert "wheel_dynamics" in m279_summary["player_impact"]
