"""M155 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter (binds every onboard-* agent): Unit = SpinType (EVENT); quantify the
*felt* experience as distributions / rates / probabilities / shares — money
amounts do NOT matter. This file asserts STRUCTURE / DETERMINISM / ATTRIBUTION /
HONESTY / NON-LEAK invariants, NEVER an RTP value or range. M155's numbers (RTP,
hit-rate, band frequencies) change on re-sample / re-tune / upstream drift; pinning
ANY of them would be a brittle false alarm (permanent invariant 1). The ONLY hard
constants asserted are STRUCTURAL identifiers fixed by the manifest / protocol (the
single SpinType id 1, the declared paid_spin role / Normal play, the canonical
RETURN_BUCKET_ORDER taxonomy).

What M155 shipped (session_artifacts/_onboard/M155/03_design.md + the manifest
configs/machine_manifests/M155.json):
  - A PURE STRICT-REUSE onboard: ONE ST=1 {role paid_spin, play Normal}, the shared
    `paid_spin` path. NO new backend plugin, NO round_win rule (round_win_rule:null),
    NO SynthesizePayIdRule — the win self-settles with a real PayoutIdToWinAmount
    payId (sum(payid) == summary, fallback 0, proven 40000/40000 in W1).
  - derive_analyses(M155) == CROSS_CUTTING + PER_SPINTYPE ONLY (role paid_spin and
    play Normal add nothing; no DIMENSION_ANALYSES key declared).
  - M10 (multiplier_wild ×5-wild dimension) is DEFERRED this batch (manifest caveat:
    "machine_spec.py and frontend untouched") — so multiplier_wild must NOT appear in
    M155's player_impact (it is not wired into CROSS_CUTTING).

The structural-report classes run the REAL engine on the real cached chunk at
rawdata/M155/mode_1 (permanent invariant 3: run the real thing; pass bet == the
chunk _bet so per-multiplier columns are sane — the M279 1000× trap — but never
assert a multiplier VALUE).

The inject-bug proofs (permanent invariant 2) mutate ONLY a COPY of M155's OWN
manifest written into a throwaway manifests_root (never the real file, never a
shared plugin, never another machine's file), prove the guard goes RED, then let
the tempdir auto-revert — leaving the real (un-patched) module-scoped report GREEN.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M155_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M155" / "mode_1"
_M155_MANIFEST = _REPO_ROOT / "configs" / "machine_manifests" / "M155.json"
_MANIFESTS_ROOT = _REPO_ROOT / "configs" / "machine_manifests"

# The bet used during M155 sampling (cost=1000 per paid spin; chunk _bet=1000).
# The report is value-agnostic; bet only affects coin totals (never asserted) and
# must land in sampling.bet so the frontend "× bet" columns are not 1000× inflated.
_BET = 1000

# Structural SpinType id fixed by the manifest / rawdata protocol (NOT a value).
_ST = 1
_ST_KEY = "ST1_paid"

# The single declared role/play (manifest structural facts).
_ROLE = "paid_spin"
_PLAY = "Normal"

# Frontend-contract per-ST keys the console depends on (permanent invariant 1/3).
_FRONTEND_PER_ST_KEYS = (
    "spin_type_breakdown",
    "spin_type_rtp_buckets",
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "spin_type_outcomes",
    "upstream_feature_breakdown",
)

# Role/play/dimension-keyed analyses that must NOT fire on a plain paid_spin/Normal
# machine. Each is scoped (machine_spec.py) to a role/play/dimension M155 lacks.
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
    """A deep-mutable copy of M155's REAL manifest (utf-8: the file has non-ASCII
    text in the caveats). The original file is NEVER written."""
    return json.loads(_M155_MANIFEST.read_text(encoding="utf-8"))


def _run_with_manifest(manifest: dict, *, chunk_dir: Path = _M155_CHUNK_DIR) -> dict:
    """Run the REAL engine against a one-off manifests_root holding the given
    (possibly mutated) M155 manifest. The real configs/ tree is untouched."""
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as mroot, tempfile.TemporaryDirectory() as out:
        (Path(mroot) / "M155.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return generate_report_from_chunks(
            "M155", 1,
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
def m155_summary():
    if not _has_chunks(_M155_CHUNK_DIR):
        pytest.skip("M155 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            "M155", 1,
            chunk_dir=_M155_CHUNK_DIR,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists(), (
            "write_summary_json must produce player_impact_summary.json"
        )
        yield summary


@pytest.fixture(scope="module")
def m155_player_impact(m155_summary):
    return m155_summary["player_impact"]


@pytest.fixture(scope="module")
def m155_manifest():
    if not _M155_MANIFEST.exists():
        pytest.skip("M155 manifest not present")
    return _load_manifest_copy()


# ---------------------------------------------------------------------------
# 0. Smoke — report generates, declared ST present, bet lands, no feature errors.
# ---------------------------------------------------------------------------

class TestReportGenerates:
    def test_machine_and_mode(self, m155_summary):
        assert m155_summary["machine"] == "M155"
        assert m155_summary["mode"] == 1
        assert m155_summary["sampling"]["chunks"] > 0
        assert m155_summary["sampling"]["total_spins"] > 0

    def test_no_feature_errors(self, m155_summary):
        assert not m155_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m155_summary.get('feature_errors')}"
        )

    def test_bet_lands_in_sampling(self, m155_summary):
        """The M279 trap: bet must land in sampling.bet so the frontend "× bet"
        columns are not 1000× inflated. (We assert the WIRING, not any multiplier.)"""
        assert m155_summary["sampling"]["bet"] == _BET, (
            f"bet must land in sampling.bet (== chunk _bet {_BET}); got "
            f"{m155_summary['sampling'].get('bet')} — frontend would inflate × bet"
        )

    def test_manifest_declares_single_paid_spin(self, m155_manifest):
        """STRUCTURAL: the manifest declares EXACTLY one ST=1 {paid_spin, Normal},
        round_win_rule null (no synth rule — the win self-settles with a real payId)."""
        st = m155_manifest["spin_types"]
        assert list(st.keys()) == [str(_ST)], (
            f"M155 declares exactly one ST=1; got {list(st.keys())}"
        )
        assert st[str(_ST)]["role"] == _ROLE
        assert st[str(_ST)]["play"] == _PLAY
        assert m155_manifest.get("round_win_rule") is None, (
            "M155 must have round_win_rule null (no SynthesizePayIdRule — the win "
            "self-settles with a real PayoutIdToWinAmount payId)"
        )


# ---------------------------------------------------------------------------
# 1. FRONTEND CONTRACT — every key the console renders is present + the single
#    declared ST is present in each per-ST section.
# ---------------------------------------------------------------------------

class TestFrontendContract:
    def test_frontend_per_st_keys_present(self, m155_player_impact):
        for key in _FRONTEND_PER_ST_KEYS:
            assert key in m155_player_impact, (
                f"frontend-contract key '{key}' missing from player_impact"
            )

    def test_spin_type_breakdown_has_declared_st(self, m155_player_impact):
        """The declared ST=1 output is PRESENT and labelled paid_spin/Normal."""
        stb = m155_player_impact["spin_type_breakdown"]
        sts = [r.get("spin_type") for r in stb]
        assert sts == [_ST], (
            f"spin_type_breakdown must contain exactly the declared ST={_ST}; got {sts}"
        )
        row = stb[0]
        assert row["share_pct"] == pytest.approx(100.0), (
            "ST=1 is the only ST → 100% share"
        )
        assert str(row.get("feature_name")) == _PLAY
        # hit_rate is a RATE (0..1) — structural bound, not a pinned value.
        assert 0.0 < row["hit_rate"] < 1.0, (
            f"hit_rate must be a probability in (0,1); got {row['hit_rate']}"
        )

    def test_per_st_sections_key_on_declared_st(self, m155_player_impact):
        """The per-ST band + payId + reel sections all key on the single declared
        ST (ST1_paid). No stray/extra ST keys (no phantom event)."""
        for key in ("spin_type_rtp_buckets", "payouts_by_spin_type",
                    "reel_marginal_by_spin_type"):
            section = m155_player_impact[key]
            assert isinstance(section, dict)
            assert list(section.keys()) == [_ST_KEY], (
                f"{key} must key on exactly the declared ST ('{_ST_KEY}'); "
                f"got {list(section.keys())}"
            )

    def test_band_taxonomy_is_the_machine_own_summarywin_order(self, m155_player_impact):
        """M2/M3 use the canonical RETURN_BUCKET_ORDER (the machine's OWN SummaryWin
        band taxonomy), NOT hand-rolled banding. Assert the band ID SET / ORDER
        matches the shared canonical order — value-agnostic (no frequencies)."""
        from fresh_slotlab.analyzer.core.aggregator import RETURN_BUCKET_ORDER
        buckets = [b["bucket"] for b in m155_player_impact["spin_type_rtp_buckets"][_ST_KEY]]
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
    def test_rtp_integrity_passes(self, m155_summary):
        ric = m155_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M155 mode 1; got "
            f"passed={ric.get('passed')}, message={ric.get('summary_message','N/A')}"
        )

    def test_layer1_sum_invariant_holds(self, m155_summary):
        ric = m155_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant (sum == our_total) broken: {ric.get('layer1_error')}"
        )

    def test_layer2_no_unattributed_fallback_bucket(self, m155_summary):
        """The headline value-agnostic guard: NO _unattributed_* fallback bucket
        (Layer-2). M155 has round_win_rule null — the win self-settles, so a
        fallback bucket would be a genuine attribution regression."""
        ric = m155_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}"
        )
        assert (ric.get("layer2_fallback_buckets_found") or []) == [], (
            f"fallback bucket share must be 0; got {ric.get('layer2_fallback_buckets_found')}"
        )
        pids = _payout_ids(m155_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )

    def test_layer3_anchors_ok(self, m155_summary):
        ric = m155_summary.get("rtp_integrity_check", {})
        assert ric.get("layer3_anchors_ok") is True, (
            f"Layer-3 anchors broken; missing={ric.get('layer3_missing_anchors')}"
        )
        assert (ric.get("layer3_missing_anchors") or []) == []

    def test_session_conservation_ok(self, m155_summary):
        """No win lost to attribution (real-economy machine, kind:real)."""
        ric = m155_summary.get("rtp_integrity_check", {})
        assert ric.get("session_conservation_level") == "ok", (
            f"session_conservation_level must be 'ok'; got "
            f"{ric.get('session_conservation_level')} "
            f"(skip_reason={ric.get('session_conservation_skip_reason')})"
        )

    def test_our_equals_server_when_present(self, m155_summary):
        """When a server aggregate is present, our_total_win == server_total_win.
        M155's cached chunk carries NO server aggregate (server_total_win:null), so
        this clause is N/A — assert the contract honestly: numerator_source is our
        total and the (absent) server value is not silently substituted."""
        rtp = m155_summary.get("rtp", {})
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
    def test_sum_payid_rtp_equals_st_rtp(self, m155_player_impact):
        """Aggregator parity: Σ payId rtp_pp == ST rtp_pp (sum(payid) == summary,
        cross-aggregator alignment). VALUE-AGNOSTIC: the EQUALITY is the invariant,
        not the magnitude."""
        st_rtp = m155_player_impact["spin_type_breakdown"][0]["rtp_pct"]
        sum_payid = sum(
            r["rtp_contribution_pp"]
            for r in m155_player_impact["payouts_by_spin_type"][_ST_KEY]
        )
        assert sum_payid == pytest.approx(st_rtp, abs=1e-3), (
            f"Σ payId rtp_pp ({sum_payid}) must equal ST rtp_pp ({st_rtp}) — "
            f"sum(payid) == summary"
        )

    def test_sum_band_rtp_equals_st_rtp(self, m155_player_impact):
        """Band parity: Σ band rtp_pp == ST rtp_pp (the M2 SummaryWin band taxonomy
        reconciles to the ST total). VALUE-AGNOSTIC: equality, not magnitude."""
        st_rtp = m155_player_impact["spin_type_breakdown"][0]["rtp_pct"]
        sum_band = sum(
            b["rtp_contribution_pp"]
            for b in m155_player_impact["spin_type_rtp_buckets"][_ST_KEY]
        )
        assert sum_band == pytest.approx(st_rtp, abs=1e-3), (
            f"Σ band rtp_pp ({sum_band}) must equal ST rtp_pp ({st_rtp})"
        )

    def test_no_preview_or_no_payid_double_count(self, m155_player_impact):
        """No-payId / preview rounds must not double-count. M155 is single-ST line
        pays with a real payId on every win → win-rounds == sum of payId hit_counts
        across paylines is NOT required, but the per-band spin_counts must reconcile
        to the round count, and there is NO preview/trigger-only ST inflating the
        denominator. Assert: the band spin_count sum == paid_rounds (every paid spin
        lands in exactly one band — no round counted twice, none dropped)."""
        row = m155_player_impact["spin_type_breakdown"][0]
        paid_rounds = row["paid_rounds"]
        band_spins = sum(
            b["spin_count"]
            for b in m155_player_impact["spin_type_rtp_buckets"][_ST_KEY]
        )
        win_rounds = row["win_rounds"]
        # Win bands cover the WIN rounds (>0× return); the 0× (loss) rounds are not
        # banded. So band spin_count sum == win_rounds (each win round in one band).
        assert band_spins == win_rounds, (
            f"each win round must land in exactly ONE band (no double-count / drop): "
            f"Σ band spin_count ({band_spins}) must equal win_rounds ({win_rounds})"
        )
        assert win_rounds <= paid_rounds, (
            f"win_rounds ({win_rounds}) cannot exceed paid_rounds ({paid_rounds})"
        )


# ---------------------------------------------------------------------------
# 3. STRICT-REUSE / DEFERRED M10 — the REUSE-ONLY onboard shape.
#    multiplier_wild (M10 ×5-wild dimension) is DEFERRED this batch → must NOT be
#    in player_impact; no role/play/dimension-keyed analysis may leak in.
# ---------------------------------------------------------------------------

class TestStrictReuseShape:
    def test_multiplier_wild_deferred(self, m155_player_impact):
        """M10 deferred (manifest caveat: machine_spec.py untouched) → multiplier_wild
        is NOT wired into CROSS_CUTTING → it must NOT appear in M155's player_impact."""
        assert "multiplier_wild" not in m155_player_impact, (
            "multiplier_wild appeared in M155 player_impact, but M10 is DEFERRED this "
            "batch (REUSE-ONLY onboard; not wired into CROSS_CUTTING). If M10 was "
            "intentionally shipped, update this test AND the manifest caveat."
        )

    def test_no_keyed_analysis_leaks_into_m155(self, m155_player_impact):
        """A plain paid_spin/Normal machine gets CROSS_CUTTING + PER_SPINTYPE only.
        No role/play/dimension-keyed analysis may appear in its player_impact."""
        for analysis in _KEYED_ANALYSES_MUST_NOT_FIRE:
            assert analysis not in m155_player_impact, (
                f"{analysis} LEAKED onto M155 (a plain paid_spin/Normal machine). "
                f"M155 declares neither the role/play/dimension that scopes it."
            )

    def test_derive_analyses_is_cross_cutting_plus_per_spintype(self, m155_manifest):
        """The analysis SET derived from M155's manifest equals CROSS_CUTTING +
        PER_SPINTYPE exactly — the canonical single-Normal/paid_spin reuse set."""
        from fresh_slotlab.analyzer.machine_spec import (
            derive_analyses, CROSS_CUTTING, PER_SPINTYPE,
        )
        derived = derive_analyses(m155_manifest)
        expected = sorted(set(CROSS_CUTTING) | set(PER_SPINTYPE))
        assert derived == expected, (
            f"M155's analysis set must be exactly CROSS_CUTTING+PER_SPINTYPE; "
            f"got {derived}, expected {expected}"
        )
        for analysis in _KEYED_ANALYSES_MUST_NOT_FIRE:
            assert analysis not in derived, (
                f"{analysis} must not be in M155's derived analysis set"
            )


# ---------------------------------------------------------------------------
# 4. CROSS-MACHINE NON-LEAK — the keyed analyses M155 introduces NO new wiring
#    for must not fire on OTHER machines either, and (the inverse) the scoping is
#    real: declaring the key on M155's OWN manifest copy DOES make the analysis
#    fire (proving the absence is enforced by scoping, not coincidence).
#
#    M155 ships NO new keyed plugin, so the canonical cross-machine non-leak this
#    onboard must guarantee is: M155 (plain paid_spin) does not pick up ANY of the
#    fleet's keyed analyses, and conversely the fleet's keyed analyses stay scoped
#    to their declaring machines. We assert BOTH directions on machine_spec, which
#    is the single source of truth for the wiring (base-excluded, pure function).
# ---------------------------------------------------------------------------

class TestCrossMachineNonLeak:
    def test_keyed_analyses_scoped_away_from_plain_machine(self, m155_manifest):
        """A plain {paid_spin, Normal} manifest (M155) attaches NONE of the keyed
        analyses (the role/play/dimension hooks each require a key M155 lacks)."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        derived = set(derive_analyses(m155_manifest))
        leaked = derived & set(_KEYED_ANALYSES_MUST_NOT_FIRE)
        assert not leaked, (
            f"keyed analyses leaked onto plain M155: {sorted(leaked)}"
        )

    def test_lock_respin_and_nudge_are_other_machine_exclusive(self):
        """M104's lock_respin_dynamics (play LockSymbolSpin) and M63's nudge_dynamics
        (dimension crazy_reel) are keyed so they fire ONLY on their declaring
        machine. A plain {paid_spin, Normal} manifest must get NEITHER — proving
        these would-leak-via-the-shared-role plugins are scoped by play/dimension."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        plain = {
            "spin_types": {"1": {"role": "paid_spin", "play": "Normal"}},
        }
        derived = set(derive_analyses(plain))
        assert "lock_respin_dynamics" not in derived, (
            "lock_respin_dynamics must be scoped to the LockSymbolSpin PLAY (M104), "
            "NOT the paid_spin role every base spin shares"
        )
        assert "nudge_dynamics" not in derived, (
            "nudge_dynamics must be scoped to the crazy_reel DIMENSION key (M63), "
            "NOT the paid_spin role / Normal play that 13 base machines share"
        )

    def test_real_other_machines_do_not_pick_up_phantom_analyses(self):
        """Spot-check the live wiring is symmetric: load a couple of REAL fleet
        manifests that are NOT M104/M63 and confirm they do not pick up
        lock_respin_dynamics / nudge_dynamics. (Skips any manifest absent.)"""
        from fresh_slotlab.analyzer.machine_spec import load_manifest, derive_analyses
        for other in ("M15", "M43"):
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
# 5. INJECT-BUG PROOF — break each safety claim → RED → (auto-revert) → GREEN.
#
#   Claim A (non-leak is REAL, play scoping): if M155's ST=1 play were the
#     WinMiniGame PLAY, minigame_dynamics WOULD fire. Proves M155's clean absence
#     is enforced by the PLAY scoping, not luck. (Inject ONLY into M155's OWN
#     manifest copy.)
#   Claim B (non-leak is REAL, dimension scoping): if M155's ST=1 declared a
#     crazy_reel DIMENSION block, nudge_dynamics WOULD fire. Proves the dimension
#     scoping is load-bearing.
#   Claim C (the REUSE set is determined by the declared ROLE): if M155's ST=1 role
#     were `respin`, respin_dynamics WOULD attach. Proves the derived set tracks the
#     declared role (and thus that the plain paid_spin role is what keeps M155 clean).
#
# Every inject writes a COPY of M155's manifest into a throwaway manifests_root and
# is auto-reverted (tempdir teardown). The real configs/ tree and the module-scoped
# m155_summary (built from the REAL manifest) stay GREEN — see test_green_after_revert.
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_play_winminigame_leaks_minigame_dynamics(self):
        """INJECT (Claim A): set ST=1 play -> "WinMiniGame". minigame_dynamics MUST
        appear (RED for the non-leak guard). Then the tempdir reverts."""
        if not _has_chunks(_M155_CHUNK_DIR):
            pytest.skip("M155 cached chunks not present")
        m = _load_manifest_copy()
        assert "minigame_dynamics" not in set(  # sanity: clean before inject
            __import__("fresh_slotlab.analyzer.machine_spec", fromlist=["derive_analyses"])
            .derive_analyses(m)
        )
        m["spin_types"]["1"]["play"] = "WinMiniGame"
        summary = _run_with_manifest(m)
        assert "minigame_dynamics" in summary["player_impact"], (
            "inject-bug: with play=WinMiniGame, minigame_dynamics MUST fire — "
            "proving M155's clean absence is enforced by the PLAY scoping, not luck"
        )

    def test_inject_crazy_reel_dimension_leaks_nudge_dynamics(self):
        """INJECT (Claim B): add a crazy_reel dimension block to ST=1. nudge_dynamics
        MUST appear (RED for the non-leak guard). Then the tempdir reverts."""
        if not _has_chunks(_M155_CHUNK_DIR):
            pytest.skip("M155 cached chunks not present")
        m = _load_manifest_copy()
        m["spin_types"]["1"]["crazy_reel"] = {
            "symbols": ["crazy_up", "crazy", "crazy_down"]
        }
        summary = _run_with_manifest(m)
        assert "nudge_dynamics" in summary["player_impact"], (
            "inject-bug: with a crazy_reel dimension block, nudge_dynamics MUST fire — "
            "proving the dimension scoping (DIMENSION_ANALYSES) is load-bearing"
        )

    def test_inject_role_respin_attaches_respin_dynamics(self):
        """INJECT (Claim C): set ST=1 role -> "respin". respin_dynamics MUST attach
        in the derived analysis set (RED for the reuse-only guard). machine_spec is
        a pure function — assert via derive_analyses on the mutated manifest copy."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        m = _load_manifest_copy()
        assert "respin_dynamics" not in set(derive_analyses(m))  # clean before
        m["spin_types"]["1"]["role"] = "respin"
        derived = set(derive_analyses(m))
        assert "respin_dynamics" in derived, (
            "inject-bug: with role=respin, respin_dynamics MUST attach — proving the "
            "REUSE-only set tracks the declared role (plain paid_spin keeps M155 clean)"
        )

    def test_green_after_revert(self, m155_summary, m155_player_impact, m155_manifest):
        """After every inject-bug tempdir reverts, the REAL (un-patched) report is
        GREEN: integrity passes, zero fallback, REUSE-only shape, no keyed leak,
        derived set == CROSS_CUTTING+PER_SPINTYPE, M10 deferred."""
        from fresh_slotlab.analyzer.machine_spec import (
            derive_analyses, CROSS_CUTTING, PER_SPINTYPE,
        )
        ric = m155_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert ric.get("layer2_no_fallback_buckets_ok") is True
        assert (ric.get("layer2_fallback_buckets_found") or []) == []
        assert "multiplier_wild" not in m155_player_impact
        for analysis in _KEYED_ANALYSES_MUST_NOT_FIRE:
            assert analysis not in m155_player_impact
        derived = derive_analyses(m155_manifest)
        assert derived == sorted(set(CROSS_CUTTING) | set(PER_SPINTYPE))


# ---------------------------------------------------------------------------
# 6. BASE-HASH / CONFIG-ONLY GUARD — onboarding M155 is a pure config/manifest
#    add. It must touch NO base-closure file (else it would re-flag the whole
#    fleet's reports stale, the playtype-rearch anti-goal). This is the
#    value-agnostic structural invariant; we do NOT pin a tuned number.
#
#    HONESTY NOTE: the LIVE base_hash at HEAD is a moving framework snapshot, NOT a
#    value M155 owns. M155 onboarding touches NO closure file (it adds only
#    configs/machine_manifests/M155.json + this test). The value-agnostic invariant
#    M155 OWNS is: "config-only onboard => NO closure file delta vs HEAD => base_hash
#    unchanged by M155" — guarded by test_m155_modifies_no_closure_file. The snapshot
#    pin below just tracks the CURRENT framework reality so a real closure regression
#    elsewhere still trips this suite.
# ---------------------------------------------------------------------------

# The base_hash at HEAD as of this onboard. A framework SNAPSHOT (not an M155 value):
# re-baselined 2026-06-22 by the pluggable round_win rule-engine refactor (rule types
# moved to base-EXCLUDED round_win_rules/). Prior framework baselines: 3ddaa183f38c →
# bba689d50f03 → 5900f0deb2ad.
_BASE_HASH_AT_HEAD = "5900f0deb2ad"


class TestBaseHashConfigOnly:
    def test_m155_modifies_no_closure_file(self):
        """The load-bearing config-only invariant: onboarding M155 must NOT have
        modified ANY base-closure file in the working tree. If it did, base_hash
        would flip and re-flag the whole fleet stale (the playtype-rearch
        anti-goal). VALUE-AGNOSTIC: a structural delta check, no number pinned."""
        from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES
        try:
            out = subprocess.check_output(
                ["git", "status", "--porcelain", "--", *_CLOSURE_FILES],
                cwd=str(_REPO_ROOT), stderr=subprocess.DEVNULL,
            ).decode("utf-8", "replace")
        except (OSError, subprocess.CalledProcessError):
            pytest.skip("git not available to verify closure-file delta")
        dirty = [ln for ln in out.splitlines() if ln.strip()]
        assert not dirty, (
            "M155 onboarding is config/manifest-only, but base-closure file(s) are "
            f"modified in the working tree:\n{out}\nA closure-file delta flips "
            "base_hash and re-flags the whole fleet stale. Move the change OUT of the "
            "M155 onboard or it is no longer a config-only onboard."
        )

    def test_base_hash_matches_head_snapshot(self):
        """base_hash equals the CURRENT HEAD snapshot. This is NOT c5d2199142c3 —
        that drifted to 5900f0deb2ad at framework commit 58a28fd (parser.py edit),
        which predates and is independent of M155. With M155 adding no closure
        file (test above), the base_hash is whatever HEAD already produces.

        If this fails with a NEW value, a closure file changed since this onboard
        — investigate the diff (and if it is intentional, update the snapshot AND
        the fleet base_hash pin tests together, never silently)."""
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        bh = compute_base_analyzer_version()
        assert bh == _BASE_HASH_AT_HEAD, (
            f"base_hash is {bh!r}, expected the HEAD snapshot {_BASE_HASH_AT_HEAD!r}. "
            f"M155 adds no closure file, so a change here means a closure file moved "
            f"after this onboard. (Brief-requested c5d2199142c3 was already superseded "
            f"by 5900f0deb2ad at framework commit 58a28fd — a parser.py change, not M155.)"
        )
