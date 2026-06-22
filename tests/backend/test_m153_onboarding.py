"""M153 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter (binds every onboard-* agent): Unit = SpinType (EVENT); quantify the
*felt* experience as distributions / rates / probabilities / shares — money
amounts do NOT matter. This file asserts STRUCTURE / DETERMINISM / ATTRIBUTION /
HONESTY / NON-LEAK invariants, NEVER an RTP value or range. M153's numbers (RTP,
hit-rate, band frequencies, the collect-window CC ladder) all change on
re-sample / re-tune / upstream drift; pinning ANY of them would be a brittle
false alarm (permanent invariant 1). The ONLY hard constants asserted are
STRUCTURAL identifiers fixed by the manifest / protocol (the single SpinType id
140, the declared paid_spin role / NormalCollectionSpin play, the canonical
RETURN_BUCKET_ORDER taxonomy, and the BCM-inertness *flags*).

What M153 shipped (session_artifacts/_onboard/M153/03_design.md + the manifest
configs/machine_manifests/M153.json):
  - The structurally SIMPLEST onboard in the fleet so far: a PURE STRICT-REUSE
    of the 4 PER_SPINTYPE plugins. EXACTLY ONE ST=140 {role paid_spin, play
    NormalCollectionSpin}, the shared `paid_spin` path. NO new backend plugin,
    NO round_win rule (round_win_rule:null), NO SynthesizePayIdRule — st140
    self-settles with real PayoutIdToWinAmount payIds (all 9 natural payids
    present, pid 9 = the collect/bonus trigger correctly pays 0; sum(payid) ==
    summary, fallback 0, proven 40000/40000 in W1).
  - derive_analyses(M153) == CROSS_CUTTING + PER_SPINTYPE ONLY (role paid_spin
    and play NormalCollectionSpin add nothing; no role/play/dimension analysis
    keys on them).
  - The CROSS_CUTTING `collect_mechanic` (BCM) AUTO-fires and MIS-DESCRIBES the
    machine (it models an INCREMENT-to-threshold accumulator; M153's CollectCount
    is a DECREMENT 3->2->1->0 collect-window). It is a known false-positive routed
    to the framework team — but it is RTP-INERT (bonus_cycle_correction.applicable
    == False, estimated_correction_pp == None) and corrupts NO invariant. A
    dedicated guard (TestCollectMechanicInert) locks this: the BCM noise must NOT
    bleed into rtp_integrity / fallback / sum(payid)==summary.
  - The collect-window CC-state ladder is PARSER-BLIND at the base-excluded layer
    (framework-team item) and is NOT a labeled split here — so NO collect-window /
    minigame / wheel / freespin panel may appear (non-leak).

The structural-report classes run the REAL engine on the real cached chunk at
rawdata/M153/mode_1 (permanent invariant 3: run the real thing; pass bet == the
chunk _bet so per-multiplier columns are sane — the M279 1000× trap — but never
assert a multiplier VALUE).

The inject-bug proofs (permanent invariant 2) mutate ONLY a COPY of M153's OWN
manifest written into a throwaway manifests_root (never the real file, never a
shared plugin, never another machine's file), prove the guard goes RED, then let
the tempdir auto-revert — leaving the real (un-patched) module-scoped report GREEN.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M153_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M153" / "mode_1"
_M153_MANIFEST = _REPO_ROOT / "configs" / "machine_manifests" / "M153.json"
_MANIFESTS_ROOT = _REPO_ROOT / "configs" / "machine_manifests"

# The bet used during M153 sampling (CostCredits=1000 per paid spin; chunk
# _bet=1000). The report is value-agnostic; bet only affects coin totals (never
# asserted) and must land in sampling.bet so the frontend "× bet" columns are not
# 1000× inflated (the M279 trap).
_BET = 1000

# Structural SpinType id fixed by the manifest / rawdata protocol (NOT a value).
_ST = 140
_ST_KEY = "ST140_paid"

# The single declared role/play (manifest structural facts).
_ROLE = "paid_spin"
_PLAY = "NormalCollectionSpin"

# Frontend-contract per-ST keys the console depends on (permanent invariant 1/3).
_FRONTEND_PER_ST_KEYS = (
    "spin_type_breakdown",
    "spin_type_rtp_buckets",
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "spin_type_outcomes",
    "upstream_feature_breakdown",
)

# Role/play/dimension-keyed analyses that must NOT fire on a plain
# paid_spin/NormalCollectionSpin machine. Each is scoped (machine_spec.py) to a
# role/play/dimension M153 lacks. The collect-window is INTRA-ST state, NOT a
# trigger into a new ST — so NONE of these (incl. the would-be collect-window
# plugin's would-be relatives) may appear.
_KEYED_ANALYSES_MUST_NOT_FIRE = (
    "topdollar_choice",     # role player_choice (M15 ST14)
    "respin_dynamics",      # role respin (M43 ST50)
    "minigame_dynamics",    # play WinMiniGame (M43 ST51)
    "wheel_dynamics",       # play Wheel (M279/M283 ST2)
    "freespin_dynamics",    # role freespin / hold_respin (M275/M278)
    "lock_respin_dynamics", # play LockSymbolSpin (M104)
    "nudge_dynamics",       # dimension crazy_reel (M63)
)


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


def _load_manifest_copy() -> dict:
    """A deep-mutable copy of M153's REAL manifest (utf-8: the file has non-ASCII
    text in the caveats). The original file is NEVER written."""
    return json.loads(_M153_MANIFEST.read_text(encoding="utf-8"))


def _run_with_manifest(manifest: dict, *, chunk_dir: Path = _M153_CHUNK_DIR) -> dict:
    """Run the REAL engine against a one-off manifests_root holding the given
    (possibly mutated) M153 manifest. The real configs/ tree is untouched."""
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as mroot, tempfile.TemporaryDirectory() as out:
        (Path(mroot) / "M153.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return generate_report_from_chunks(
            "M153", 1,
            chunk_dir=chunk_dir,
            output_dir=Path(out),
            manifests_root=Path(mroot),
            bet=_BET,
        )


def _payout_ids(summary) -> list[str]:
    return [
        str(r.get("payout_id", ""))
        for r in summary["player_impact"].get("payout_ids_top20", [])
    ]


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine ONCE per module against the REAL manifest
# (permanent invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m153_summary():
    if not _has_chunks(_M153_CHUNK_DIR):
        pytest.skip("M153 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            "M153", 1,
            chunk_dir=_M153_CHUNK_DIR,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists(), (
            "write_summary_json must produce player_impact_summary.json"
        )
        yield summary


@pytest.fixture(scope="module")
def m153_player_impact(m153_summary):
    return m153_summary["player_impact"]


@pytest.fixture(scope="module")
def m153_manifest():
    if not _M153_MANIFEST.exists():
        pytest.skip("M153 manifest not present")
    return _load_manifest_copy()


# ---------------------------------------------------------------------------
# 0. Smoke — report generates, declared ST present, bet lands, no feature errors.
# ---------------------------------------------------------------------------

class TestReportGenerates:
    def test_machine_and_mode(self, m153_summary):
        assert m153_summary["machine"] == "M153"
        assert m153_summary["mode"] == 1
        assert m153_summary["sampling"]["chunks"] > 0
        assert m153_summary["sampling"]["total_spins"] > 0

    def test_no_feature_errors(self, m153_summary):
        assert not m153_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m153_summary.get('feature_errors')}"
        )

    def test_bet_lands_in_sampling(self, m153_summary):
        """The M279 trap: bet must land in sampling.bet so the frontend "× bet"
        columns are not 1000× inflated. (We assert the WIRING, not any multiplier.)"""
        assert m153_summary["sampling"]["bet"] == _BET, (
            f"bet must land in sampling.bet (== chunk _bet {_BET}); got "
            f"{m153_summary['sampling'].get('bet')} — frontend would inflate × bet"
        )

    def test_manifest_declares_single_paid_spin(self, m153_manifest):
        """STRUCTURAL: the manifest declares EXACTLY one ST=140 {paid_spin,
        NormalCollectionSpin}, round_win_rule null (no synth rule — st140
        self-settles with real PayoutIdToWinAmount payIds)."""
        st = m153_manifest["spin_types"]
        assert list(st.keys()) == [str(_ST)], (
            f"M153 declares exactly one ST=140; got {list(st.keys())}"
        )
        assert st[str(_ST)]["role"] == _ROLE
        assert st[str(_ST)]["play"] == _PLAY
        assert m153_manifest.get("round_win_rule") is None, (
            "M153 must have round_win_rule null (no SynthesizePayIdRule — st140 "
            "self-settles with real PayoutIdToWinAmount payIds)"
        )


# ---------------------------------------------------------------------------
# 1. FRONTEND CONTRACT — every key the console renders is present + the single
#    declared ST is present in each per-ST section.
# ---------------------------------------------------------------------------

class TestFrontendContract:
    def test_frontend_per_st_keys_present(self, m153_player_impact):
        for key in _FRONTEND_PER_ST_KEYS:
            assert key in m153_player_impact, (
                f"frontend-contract key '{key}' missing from player_impact"
            )

    def test_spin_type_breakdown_has_declared_st(self, m153_player_impact):
        """The declared ST=140 output is PRESENT and labelled paid_spin /
        NormalCollectionSpin."""
        stb = m153_player_impact["spin_type_breakdown"]
        sts = [r.get("spin_type") for r in stb]
        assert sts == [_ST], (
            f"spin_type_breakdown must contain exactly the declared ST={_ST}; got {sts}"
        )
        row = stb[0]
        assert row["share_pct"] == pytest.approx(100.0), (
            "ST=140 is the only ST → 100% share"
        )
        assert str(row.get("feature_name")) == _PLAY
        # hit_rate is a RATE (0..1) — structural bound, not a pinned value.
        assert 0.0 < row["hit_rate"] < 1.0, (
            f"hit_rate must be a probability in (0,1); got {row['hit_rate']}"
        )

    def test_per_st_sections_key_on_declared_st(self, m153_player_impact):
        """The per-ST band + payId + reel + outcome sections all key on the single
        declared ST (ST140_paid). No stray/extra ST keys (no phantom event — the
        collect-window is INTRA-ST, not a second SpinType)."""
        for key in ("spin_type_rtp_buckets", "payouts_by_spin_type",
                    "reel_marginal_by_spin_type", "spin_type_outcomes"):
            section = m153_player_impact[key]
            assert isinstance(section, dict)
            assert list(section.keys()) == [_ST_KEY], (
                f"{key} must key on exactly the declared ST ('{_ST_KEY}'); "
                f"got {list(section.keys())}"
            )

    def test_band_taxonomy_is_the_machine_own_summarywin_order(self, m153_player_impact):
        """The RTP-band card uses the canonical RETURN_BUCKET_ORDER (the machine's
        OWN SummaryWin band taxonomy), NOT hand-rolled banding. Assert the band ID
        SET / ORDER matches the shared canonical order — value-agnostic (no
        frequencies)."""
        from fresh_slotlab.analyzer.core.aggregator import RETURN_BUCKET_ORDER
        buckets = [b["bucket"] for b in m153_player_impact["spin_type_rtp_buckets"][_ST_KEY]]
        canonical = list(RETURN_BUCKET_ORDER)
        # the emitted bands must be a prefix-consistent subset in canonical order
        assert buckets == [b for b in canonical if b in set(buckets)], (
            f"band order must follow the canonical RETURN_BUCKET_ORDER; got {buckets}"
        )
        assert set(buckets).issubset(set(canonical)), (
            f"every band must be a canonical SummaryWin band; stray={set(buckets)-set(canonical)}"
        )


# ---------------------------------------------------------------------------
# 2. ATTRIBUTION / RTP-INTEGRITY — passed, ZERO fallback, parity, conservation.
#    (The headline value-agnostic guards. NO RTP value asserted.)
# ---------------------------------------------------------------------------

class TestRtpIntegrity:
    def test_rtp_integrity_passes(self, m153_summary):
        ric = m153_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M153 mode 1; got "
            f"passed={ric.get('passed')}, message={ric.get('summary_message','N/A')}"
        )

    def test_layer1_sum_invariant_holds(self, m153_summary):
        ric = m153_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant (sum == our_total) broken: {ric.get('layer1_error')}"
        )

    def test_layer2_no_unattributed_fallback_bucket(self, m153_summary):
        """The headline value-agnostic guard: NO _unattributed_* fallback bucket
        (Layer-2). M153 has round_win_rule null — st140 self-settles, so a
        fallback bucket would be a genuine attribution regression."""
        ric = m153_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}"
        )
        assert (ric.get("layer2_fallback_buckets_found") or []) == [], (
            f"fallback bucket share must be 0; got {ric.get('layer2_fallback_buckets_found')}"
        )
        pids = _payout_ids(m153_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )

    def test_no_unattributed_token_in_per_st_payids(self, m153_player_impact):
        """No `_unattributed_*` token anywhere in st140's own payId breakdown
        (the W2/W3 layer-2 audit claim: layer2_fallback_buckets_found []).
        st140 carries all 9 natural payids — pid 9 (collect/bonus trigger) is a
        REAL row that correctly pays 0, NOT a synthetic fallback bucket."""
        rows = m153_player_impact["payouts_by_spin_type"][_ST_KEY]
        pids = [str(r.get("payout_id", "")) for r in rows]
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* bucket leaked into st140's payId breakdown: {pids}"
        )

    def test_layer3_anchors_ok(self, m153_summary):
        ric = m153_summary.get("rtp_integrity_check", {})
        assert ric.get("layer3_anchors_ok") is True, (
            f"Layer-3 anchors broken; missing={ric.get('layer3_missing_anchors')}"
        )
        assert (ric.get("layer3_missing_anchors") or []) == []

    def test_session_conservation_ok(self, m153_summary):
        """No win lost to attribution (real-economy machine, kind:real)."""
        ric = m153_summary.get("rtp_integrity_check", {})
        assert ric.get("session_conservation_level") == "ok", (
            f"session_conservation_level must be 'ok'; got "
            f"{ric.get('session_conservation_level')} "
            f"(skip_reason={ric.get('session_conservation_skip_reason')})"
        )

    def test_our_equals_server_when_present(self, m153_summary):
        """When a server aggregate is present, our_total_win == server_total_win.
        M153's cached chunk carries NO server aggregate (server_total_win:null), so
        this clause is N/A — assert the contract honestly: numerator_source is our
        total and the (absent) server value is not silently substituted."""
        rtp = m153_summary.get("rtp", {})
        server = rtp.get("server_total_win")
        if server is not None:
            assert rtp.get("our_total_win") == pytest.approx(server), (
                f"our_total_win ({rtp.get('our_total_win')}) must equal "
                f"server_total_win ({server}) when the server aggregate is present"
            )
        else:
            assert rtp.get("numerator_source") == "our_total_win", (
                "with no server aggregate, the numerator source must be our_total_win"
            )


class TestAttributionParity:
    def test_sum_payid_rtp_equals_st_rtp(self, m153_player_impact):
        """Aggregator parity: Σ payId rtp_pp == ST rtp_pp (sum(payid) == summary,
        cross-aggregator alignment). VALUE-AGNOSTIC: the EQUALITY is the invariant,
        not the magnitude. All 9 natural payids reconcile to st140's total."""
        st_rtp = m153_player_impact["spin_type_breakdown"][0]["rtp_pct"]
        sum_payid = sum(
            r["rtp_contribution_pp"]
            for r in m153_player_impact["payouts_by_spin_type"][_ST_KEY]
        )
        assert sum_payid == pytest.approx(st_rtp, abs=1e-3), (
            f"Σ payId rtp_pp ({sum_payid}) must equal ST rtp_pp ({st_rtp}) — "
            f"sum(payid) == summary"
        )

    def test_collect_trigger_payid_present_and_pays_zero(self, m153_player_impact):
        """STRUCTURAL (not a value pin): the collect/bonus trigger pid 9 is a REAL
        payId row that contributes ZERO RTP (it arms the collect window, it does
        not pay). Its presence-as-a-zero-row (rather than absence / fallback) is
        the structural fact that keeps attribution honest. The equality 'pid9
        rtp_pp == 0' is exact by construction (a 0-paying combo), not a sampled
        magnitude — so asserting == 0 is value-agnostic."""
        rows = m153_player_impact["payouts_by_spin_type"][_ST_KEY]
        by_pid = {str(r.get("payout_id", "")): r for r in rows}
        assert "9" in by_pid, (
            f"the collect/bonus trigger pid 9 must be a real payId row in st140's "
            f"breakdown; got payids {sorted(by_pid)}"
        )
        assert by_pid["9"]["rtp_contribution_pp"] == 0.0, (
            "pid 9 (collect/bonus trigger) must contribute 0 RTP — it arms the "
            f"collect window, it does not pay; got {by_pid['9']['rtp_contribution_pp']}"
        )

    def test_sum_band_rtp_equals_st_rtp(self, m153_player_impact):
        """Band parity: Σ band rtp_pp == ST rtp_pp (the SummaryWin band taxonomy
        reconciles to the ST total). VALUE-AGNOSTIC: equality, not magnitude."""
        st_rtp = m153_player_impact["spin_type_breakdown"][0]["rtp_pct"]
        sum_band = sum(
            b["rtp_contribution_pp"]
            for b in m153_player_impact["spin_type_rtp_buckets"][_ST_KEY]
        )
        assert sum_band == pytest.approx(st_rtp, abs=1e-3), (
            f"Σ band rtp_pp ({sum_band}) must equal ST rtp_pp ({st_rtp})"
        )

    def test_no_preview_or_no_payid_double_count(self, m153_player_impact):
        """No-payId / preview rounds must not double-count. M153 is a single-ST
        line-pay machine; every win round lands in exactly one band. Assert: the
        per-band spin_count sum == win_rounds (each win round in one band, none
        counted twice / dropped), and win_rounds <= paid_rounds. There is NO
        preview/trigger-only ST inflating the denominator (the collect window is
        intra-ST, not a separate event)."""
        row = m153_player_impact["spin_type_breakdown"][0]
        paid_rounds = row["paid_rounds"]
        band_spins = sum(
            b["spin_count"]
            for b in m153_player_impact["spin_type_rtp_buckets"][_ST_KEY]
        )
        win_rounds = row["win_rounds"]
        assert band_spins == win_rounds, (
            f"each win round must land in exactly ONE band (no double-count / drop): "
            f"Σ band spin_count ({band_spins}) must equal win_rounds ({win_rounds})"
        )
        assert win_rounds <= paid_rounds, (
            f"win_rounds ({win_rounds}) cannot exceed paid_rounds ({paid_rounds})"
        )


# ---------------------------------------------------------------------------
# 3. STRICT-REUSE SHAPE — the REUSE-ONLY onboard.
#    M153 ships ZERO new plugins. No role/play/dimension-keyed analysis may leak
#    in. The collect-window is a parser-blind framework-team item, NOT a labeled
#    split here — so no collect-window / minigame / wheel / freespin panel.
# ---------------------------------------------------------------------------

class TestStrictReuseShape:
    def test_no_keyed_analysis_leaks_into_m153(self, m153_player_impact):
        """A plain paid_spin / NormalCollectionSpin machine gets CROSS_CUTTING +
        PER_SPINTYPE only. No role/play/dimension-keyed analysis may appear in its
        player_impact."""
        for analysis in _KEYED_ANALYSES_MUST_NOT_FIRE:
            assert analysis not in m153_player_impact, (
                f"{analysis} LEAKED onto M153 (a plain paid_spin/NormalCollectionSpin "
                f"machine). M153 declares neither the role/play/dimension that scopes it."
            )

    def test_derive_analyses_is_cross_cutting_plus_per_spintype(self, m153_manifest):
        """The analysis SET derived from M153's manifest equals CROSS_CUTTING +
        PER_SPINTYPE exactly — the canonical single-paid_spin reuse set. (The BCM
        `collect_mechanic` IS part of CROSS_CUTTING, so it is in the set; that is
        correct — it is the inert auto-attach, locked separately for inertness.)"""
        from fresh_slotlab.analyzer.machine_spec import (
            derive_analyses, CROSS_CUTTING, PER_SPINTYPE,
        )
        derived = derive_analyses(m153_manifest)
        expected = sorted(set(CROSS_CUTTING) | set(PER_SPINTYPE))
        assert derived == expected, (
            f"M153's analysis set must be exactly CROSS_CUTTING+PER_SPINTYPE; "
            f"got {derived}, expected {expected}"
        )
        for analysis in _KEYED_ANALYSES_MUST_NOT_FIRE:
            assert analysis not in derived, (
                f"{analysis} must not be in M153's derived analysis set"
            )


# ---------------------------------------------------------------------------
# 3b. COLLECT_MECHANIC (BCM) FALSE-POSITIVE IS RTP-INERT — the M153 distinguishing
#     guard. The CROSS_CUTTING collect_mechanic auto-fires and MIS-DESCRIBES the
#     DECREMENT collect-window as an INCREMENT-to-threshold cycle (framework-team
#     heuristic-hardening item). This is ACCEPTABLE only because it is RTP-INERT:
#     it must NOT contribute any correction and must NOT corrupt the integrity /
#     fallback / parity invariants. If a future change makes the BCM heuristic
#     start *applying* a correction on M153, these guards go RED — exactly the
#     signal the design wants (per feedback_invariant_with_fallback_hides_drift:
#     a fallback/correction is a WARNING signal, not a silent close-out).
# ---------------------------------------------------------------------------

class TestCollectMechanicInert:
    def test_collect_mechanic_correction_not_applicable(self, m153_summary):
        cm = m153_summary.get("collect_mechanic", {})
        assert cm, "collect_mechanic block must be present (CROSS_CUTTING auto-fires)"
        bcc = cm.get("bonus_cycle_correction", {})
        assert bcc.get("applicable") is False, (
            "collect_mechanic BCM correction must be NON-applicable on M153 (its "
            "INCREMENT-to-threshold model mis-describes the DECREMENT collect-window; "
            f"it must stay RTP-inert). got applicable={bcc.get('applicable')}"
        )
        assert bcc.get("estimated_correction_pp") is None, (
            "BCM estimated_correction_pp must be None (RTP-inert); got "
            f"{bcc.get('estimated_correction_pp')}"
        )

    def test_bcm_does_not_corrupt_integrity_or_parity(self, m153_summary):
        """The whole point: despite the BCM false-positive, rtp_integrity passes,
        fallback is empty, and Σ payId rtp_pp == ST rtp_pp. The BCM noise is
        display-only and touches NO invariant."""
        ric = m153_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert (ric.get("layer2_fallback_buckets_found") or []) == []
        pi = m153_summary["player_impact"]
        st_rtp = pi["spin_type_breakdown"][0]["rtp_pct"]
        sum_payid = sum(
            r["rtp_contribution_pp"] for r in pi["payouts_by_spin_type"][_ST_KEY]
        )
        assert sum_payid == pytest.approx(st_rtp, abs=1e-3), (
            "BCM false-positive must not break sum(payid)==summary parity"
        )


# ---------------------------------------------------------------------------
# 4. CROSS-MACHINE NON-LEAK — M153 ships NO new keyed plugin, so the canonical
#    cross-machine non-leak this onboard must guarantee is: M153 (plain paid_spin /
#    NormalCollectionSpin) does not pick up ANY of the fleet's keyed analyses, and
#    conversely the fleet's keyed analyses stay scoped to their declaring machines.
#    The `NormalCollectionSpin` play token is SHARED with M279/M278's st140 but
#    keys NO play-analysis (absent from PLAY_ANALYSES) — proven below so the shared
#    token cannot accidentally start cross-firing. We assert on machine_spec, the
#    single source of truth for the wiring (base-excluded, pure function).
# ---------------------------------------------------------------------------

class TestCrossMachineNonLeak:
    def test_keyed_analyses_scoped_away_from_m153(self, m153_manifest):
        """A plain {paid_spin, NormalCollectionSpin} manifest (M153) attaches NONE
        of the keyed analyses (the role/play/dimension hooks each require a key
        M153 lacks)."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        derived = set(derive_analyses(m153_manifest))
        leaked = derived & set(_KEYED_ANALYSES_MUST_NOT_FIRE)
        assert not leaked, (
            f"keyed analyses leaked onto plain M153: {sorted(leaked)}"
        )

    def test_normalcollectionspin_play_keys_no_play_analysis(self):
        """The NormalCollectionSpin play token (SHARED with M279/M278 st140) must
        NOT be a key in PLAY_ANALYSES — so it can never cross-fire a play-keyed
        analysis. (Locks the design claim that the shared token keys nothing.)"""
        from fresh_slotlab.analyzer.machine_spec import PLAY_ANALYSES
        assert _PLAY not in PLAY_ANALYSES, (
            f"'{_PLAY}' must NOT key any PLAY_ANALYSES entry (it is a shared base "
            f"play token; keying it would cross-fire onto M279/M278). "
            f"PLAY_ANALYSES keys = {sorted(PLAY_ANALYSES)}"
        )

    def test_lock_respin_and_nudge_are_other_machine_exclusive(self):
        """M104's lock_respin_dynamics (play LockSymbolSpin) and M63's nudge_dynamics
        (dimension crazy_reel) are keyed so they fire ONLY on their declaring
        machine. A plain {paid_spin, NormalCollectionSpin} manifest must get
        NEITHER — proving these would-leak-via-the-shared-role plugins are scoped by
        play/dimension."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        plain = {
            "spin_types": {"140": {"role": "paid_spin", "play": "NormalCollectionSpin"}},
        }
        derived = set(derive_analyses(plain))
        assert "lock_respin_dynamics" not in derived, (
            "lock_respin_dynamics must be scoped to the LockSymbolSpin PLAY (M104), "
            "NOT the paid_spin role every base spin shares"
        )
        assert "nudge_dynamics" not in derived, (
            "nudge_dynamics must be scoped to the crazy_reel DIMENSION key (M63), "
            "NOT the paid_spin role / NormalCollectionSpin play"
        )

    def test_real_other_machines_do_not_pick_up_phantom_analyses(self):
        """Spot-check the live wiring is symmetric: load REAL fleet manifests that
        share the paid_spin role / NormalCollectionSpin play with M153 (M279/M278)
        and confirm they do not pick up lock_respin_dynamics / nudge_dynamics. The
        SHARED NormalCollectionSpin token must not have started keying a play
        analysis. (Skips any manifest absent.)"""
        from fresh_slotlab.analyzer.machine_spec import load_manifest, derive_analyses
        for other in ("M279", "M278", "M15"):
            mf = _MANIFESTS_ROOT / f"{other}.json"
            if not mf.exists():
                continue
            derived = set(derive_analyses(load_manifest(other, _MANIFESTS_ROOT)))
            assert "lock_respin_dynamics" not in derived, (
                f"lock_respin_dynamics leaked onto {other}"
            )
            assert "nudge_dynamics" not in derived, (
                f"nudge_dynamics leaked onto {other}"
            )


# ---------------------------------------------------------------------------
# 5. BASE_HASH STABILITY — M153 is a manifest-only / config-only onboard (ZERO new
#    plugins, NO base-closure change). The REAL invariant the M153 onboard must
#    guarantee is: adding M153 does NOT flip the base analyzer version (its manifest
#    is base-EXCLUDED). A flip would mean an M153 onboard touched a base-closure
#    file (Cardinal-rule 8) and connected the whole fleet's byte gates to it.
#
#    NOTE on the constant: the Wave-4 brief asked to confirm base_hash ==
#    c5d2199142c3. The LIVE/committed value on this branch (collab/dev, HEAD) is
#    `3ddaa183f38c` — c5d2199142c3 was superseded by the ALREADY-COMMITTED framework
#    change 58a28fd ("paid-unit framework fix + onboard M63/M104"), which touched the
#    base-closure files core/parser.py + machine_spec.py. That drift is UNRELATED to
#    M153 (M153.json is untracked and base-excluded; ZERO closure files are dirty in
#    the working tree — verified). Per permanent-invariant 1 (never pin a stale
#    value), this guard pins the value to a module constant and the load-bearing
#    invariant is `test_m153_does_not_flip_base_hash`: M153 must not change whatever
#    the committed base value is. The stale-constant discrepancy is reported up.
# ---------------------------------------------------------------------------

# The base_hash the COMMITTED HEAD code actually produces (drifted from the brief's
# c5d2199142c3 by the already-committed 58a28fd, NOT by M153). Asserting the live
# value keeps this test honest (it goes RED iff a *closure* file changes), while
# test_m153_does_not_flip_base_hash locks the actual M153-onboard invariant.
_LIVE_BASE_HASH = "ddde50975d25"  # re-baselined 2026-06-22: pluggable round_win rule-engine refactor (4 rule classes + RULE_REGISTRY → base-EXCLUDED round_win_rules/; __init__.py added to closure) — LAST rule-type flip; prior bba689d50f03 = settlement_label_format param
_BRIEF_BASE_HASH = "c5d2199142c3"  # superseded by 58a28fd (M63/M104), pre-M153


class TestBaseHashStable:
    def test_base_hash_matches_committed_head(self):
        """The base analyzer version equals what the COMMITTED HEAD closure produces.
        On this branch that is 3ddaa183f38c (the brief's c5d2199142c3 was superseded
        by the already-committed 58a28fd M63/M104 paid-unit fix — a base-closure
        change UNRELATED to M153). A change here means a *closure* file moved."""
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        bh = compute_base_analyzer_version()
        assert bh == _LIVE_BASE_HASH, (
            f"base_hash changed to {bh!r} (expected the committed-HEAD value "
            f"{_LIVE_BASE_HASH!r}). A closure file moved — if intentional, update the "
            f"constant; if not, a base-closure file was accidentally touched."
        )
        assert bh != _BRIEF_BASE_HASH, (
            "sanity: the live base_hash is the post-58a28fd value, not the stale "
            f"brief constant {_BRIEF_BASE_HASH}"
        )

    def test_m153_does_not_flip_base_hash(self):
        """THE LOAD-BEARING M153 INVARIANT (value-agnostic re: the actual digest):
        the M153 onboard introduces ZERO new plugins and ZERO base-closure changes,
        so the base_hash with M153 present must equal the base_hash WITHOUT any
        machine context — i.e. M153's manifest is base-EXCLUDED. We compute the base
        digest directly from the closure (no machine context) and assert M153's
        presence on disk did not perturb it. (The manifest is untracked + not in
        the closure file set — proven structurally.)"""
        from fresh_slotlab.analyzer.versioning import (
            compute_base_analyzer_version, _CLOSURE_FILES,
        )
        # The closure file set must NOT contain any per-machine manifest path.
        closure_strs = [str(p) for p in _CLOSURE_FILES]
        assert not any("machine_manifests" in s for s in closure_strs), (
            "a machine manifest leaked into the base-closure file set — onboarding "
            "a machine would then flip base_hash for the whole fleet (Cardinal-rule 8)"
        )
        assert not any("M153" in s for s in closure_strs), (
            "M153 must not appear in the base-closure file set"
        )
        # Base digest is computed from the closure alone → identical regardless of
        # whether M153 has been onboarded.
        assert compute_base_analyzer_version() == _LIVE_BASE_HASH


# ---------------------------------------------------------------------------
# 6. INJECT-BUG PROOF — break each safety claim → RED → (auto-revert) → GREEN.
#
#   Claim A (non-leak is REAL, play scoping): if M153's ST=140 play were the
#     Wheel PLAY, wheel_dynamics WOULD fire (and a wheel panel would leak). Proves
#     M153's clean absence is enforced by the PLAY scoping, not luck. (Inject ONLY
#     into M153's OWN manifest copy.)
#   Claim B (non-leak is REAL, dimension scoping): if M153's ST=140 declared a
#     crazy_reel DIMENSION block, nudge_dynamics WOULD fire. Proves the dimension
#     scoping is load-bearing.
#   Claim C (the REUSE set is determined by the declared ROLE): if M153's ST=140
#     role were `freespin`, freespin_dynamics WOULD attach. Proves the derived set
#     tracks the declared role (and thus that the plain paid_spin role is what keeps
#     M153 clean).
#
# Every inject writes a COPY of M153's manifest into a throwaway manifests_root and
# is auto-reverted (tempdir teardown). The real configs/ tree and the module-scoped
# m153_summary (built from the REAL manifest) stay GREEN — see test_green_after_revert.
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_play_wheel_leaks_wheel_dynamics(self):
        """INJECT (Claim A): set ST=140 play -> "Wheel". wheel_dynamics MUST appear
        (RED for the non-leak guard). Then the tempdir reverts."""
        if not _has_chunks(_M153_CHUNK_DIR):
            pytest.skip("M153 cached chunks not present")
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        m = _load_manifest_copy()
        assert "wheel_dynamics" not in set(derive_analyses(m))  # clean before inject
        m["spin_types"]["140"]["play"] = "Wheel"
        summary = _run_with_manifest(m)
        assert "wheel_dynamics" in summary["player_impact"], (
            "inject-bug: with play=Wheel, wheel_dynamics MUST fire — proving M153's "
            "clean absence is enforced by the PLAY scoping, not luck"
        )

    def test_inject_crazy_reel_dimension_leaks_nudge_dynamics(self):
        """INJECT (Claim B): add a crazy_reel dimension block to ST=140.
        nudge_dynamics MUST appear (RED for the non-leak guard). Then the tempdir
        reverts."""
        if not _has_chunks(_M153_CHUNK_DIR):
            pytest.skip("M153 cached chunks not present")
        m = _load_manifest_copy()
        m["spin_types"]["140"]["crazy_reel"] = {
            "symbols": ["crazy_up", "crazy", "crazy_down"]
        }
        summary = _run_with_manifest(m)
        assert "nudge_dynamics" in summary["player_impact"], (
            "inject-bug: with a crazy_reel dimension block, nudge_dynamics MUST fire "
            "— proving the dimension scoping (DIMENSION_ANALYSES) is load-bearing"
        )

    def test_inject_role_freespin_attaches_freespin_dynamics(self):
        """INJECT (Claim C): set ST=140 role -> "freespin". freespin_dynamics MUST
        attach in the derived analysis set (RED for the reuse-only guard).
        machine_spec is a pure function — assert via derive_analyses on the mutated
        manifest copy."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        m = _load_manifest_copy()
        assert "freespin_dynamics" not in set(derive_analyses(m))  # clean before
        m["spin_types"]["140"]["role"] = "freespin"
        derived = set(derive_analyses(m))
        assert "freespin_dynamics" in derived, (
            "inject-bug: with role=freespin, freespin_dynamics MUST attach — proving "
            "the REUSE-only set tracks the declared role (plain paid_spin keeps M153 clean)"
        )

    def test_green_after_revert(self, m153_summary, m153_player_impact, m153_manifest):
        """After every inject-bug tempdir reverts, the REAL (un-patched) report is
        GREEN: integrity passes, zero fallback, REUSE-only shape, no keyed leak,
        BCM inert, derived set == CROSS_CUTTING+PER_SPINTYPE, base_hash unchanged."""
        from fresh_slotlab.analyzer.machine_spec import (
            derive_analyses, CROSS_CUTTING, PER_SPINTYPE,
        )
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        ric = m153_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert ric.get("layer2_no_fallback_buckets_ok") is True
        assert (ric.get("layer2_fallback_buckets_found") or []) == []
        for analysis in _KEYED_ANALYSES_MUST_NOT_FIRE:
            assert analysis not in m153_player_impact
        cm = m153_summary.get("collect_mechanic", {})
        assert cm.get("bonus_cycle_correction", {}).get("applicable") is False
        derived = derive_analyses(m153_manifest)
        assert derived == sorted(set(CROSS_CUTTING) | set(PER_SPINTYPE))
        # base_hash equals the committed-HEAD value (see TestBaseHashStable for the
        # c5d2199142c3 -> 3ddaa183f38c drift, caused by 58a28fd, UNRELATED to M153).
        assert compute_base_analyzer_version() == _LIVE_BASE_HASH
