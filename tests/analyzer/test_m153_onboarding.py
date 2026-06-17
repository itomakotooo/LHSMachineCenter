"""M153 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This file asserts STRUCTURE / CONSERVATION / ATTRIBUTION / role-resolution /
honesty INVARIANTS, NEVER an RTP value or range. M153's numbers (RTP, hit-rates,
per-payid rtp_pp, the collect-window ladder) drift on re-sample / re-tune; pinning
ANY of them would be a brittle false alarm (charter permanent invariant 1). The
only hard constants asserted are STRUCTURAL ids fixed by the manifest (the single
SpinType 140) and ratio / SUM identities (share_pct == 100.0 for the sole ST;
Σ payid rtp_pp == summary.rtp; coverage == 1.0).

What M153 shipped (session_artifacts/_onboard/M153/03_design.md + the manifest):
  - configs/machine_manifests/M153.json — EXACTLY ONE SpinType st140,
    role=paid_spin / play=NormalCollectionSpin. ZERO new plugins. NO
    SynthesizePayIdRule (round_win_rule null). st140 self-settles via its OWN
    PayoutIdToWinAmount (9 natural pids, pid 9 = collect-trigger pays 0).
  - NO role/play/dimension analysis attaches: roles={paid_spin},
    plays={NormalCollectionSpin}, no dimension key → derive_analyses returns
    EXACTLY the CROSS_CUTTING + PER_SPINTYPE baseline. The simplest onboard in
    the fleet.
  - collect_mechanic (CROSS_CUTTING BCM) auto-fires but is RTP-INERT (it
    mis-describes the DECREMENT collect-window as a failed increment cycle) — a
    framework-team heuristic-hardening item, corrupts NO invariant.

The whole test runs the REAL engine on the real cached chunk at rawdata/M153/mode_1
(charter invariant 3: run the real thing, pass bet=chunk _bet=1000, read the real
summary). The inject-bug proofs mutate ONLY M153's OWN manifest (in-process, via a
monkeypatched load_manifest that returns a mutated copy — never an on-disk write,
never a shared plugin, auto-reverts) per the W4 brief.
"""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MANIFESTS_ROOT = _REPO_ROOT / "configs" / "machine_manifests"
_M153_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M153" / "mode_1"
_M153_MANIFEST = _MANIFESTS_ROOT / "M153.json"

_BET = 1000  # chunk _bet — the M279 bet trap (default 1 inflates the × bet columns)

_ST_BASE = 140  # the SOLE SpinType — paid_spin / NormalCollectionSpin
_ST_KEY = "ST140_paid"  # the per-ST plugin key
_TRIGGER_PID = "9"  # the collect-window bonus trigger; pays 0 (a real zero row)

# The role/play/dimension analyses that DO NOT attach to M153 (it has none of the
# keying roles/plays/dims). If any appears in player_impact, a foreign mechanic
# view leaked onto a plain paid-spin machine.
_LEAK_ANALYSES = (
    "topdollar_choice",       # ROLE player_choice (M15)
    "respin_dynamics",        # ROLE respin (M43/M279)
    "freespin_dynamics",      # ROLE freespin/hold_respin (M275/M278)
    "minigame_dynamics",      # PLAY WinMiniGame (M44)
    "wheel_dynamics",         # PLAY Wheel (M279)
    "lock_respin_dynamics",   # PLAY LockSymbolSpin (M104)
    "nudge_dynamics",         # DIMENSION crazy_reel (M63)
)


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


def _gen(machine_id: str, chunk_dir: Path):
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            machine_id, 1,
            chunk_dir=chunk_dir,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists()
        return summary


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m153_summary():
    if not _has_chunks(_M153_CHUNK_DIR):
        pytest.skip("M153 cached chunks not present")
    return _gen("M153", _M153_CHUNK_DIR)


@pytest.fixture(scope="module")
def m153_pi(m153_summary):
    return m153_summary["player_impact"]


@pytest.fixture(scope="module")
def m153_manifest():
    if not _M153_MANIFEST.exists():
        pytest.skip("M153 manifest not present")
    return json.loads(_M153_MANIFEST.read_text(encoding="utf-8"))


def _payout_id_rows(pi) -> list[dict]:
    return list(pi.get("payouts_by_spin_type", {}).get(_ST_KEY, []) or [])


def _payout_ids_top20(pi) -> list[str]:
    return [str(r.get("payout_id", "")) for r in pi.get("payout_ids_top20", [])]


def _st_breakdown_rows(pi) -> list[dict]:
    return list(pi.get("spin_type_breakdown", []) or [])


# ---------------------------------------------------------------------------
# 0. Smoke + manifest declaration.
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

    def test_bet_passed_through(self, m153_summary):
        """The bet trap (M279): bet must land in sampling.bet so the frontend
        '× bet' columns divide by 1000, not 1 (else 1000× inflated multipliers).
        VALUE-AGNOSTIC: we assert the bet plumbing, not any multiplier value."""
        assert m153_summary["sampling"]["bet"] == _BET, (
            f"sampling.bet must be {_BET} (chunk _bet); got "
            f"{m153_summary['sampling'].get('bet')} → frontend would inflate "
            "every '× bet' multiplier column 1000×."
        )

    def test_manifest_single_paid_spin_st(self, m153_manifest):
        """The manifest declares EXACTLY ONE SpinType — st140, role paid_spin,
        play NormalCollectionSpin. Structural id fixed by the manifest."""
        sts = m153_manifest["spin_types"]
        assert list(sts.keys()) == [str(_ST_BASE)], (
            f"M153 declares EXACTLY ONE SpinType (st{_ST_BASE}); got {list(sts.keys())}"
        )
        st = sts[str(_ST_BASE)]
        assert st["role"] == "paid_spin"
        assert st["play"] == "NormalCollectionSpin"

    def test_manifest_no_synth_rule(self, m153_manifest):
        """NO SynthesizePayIdRule: st140 self-settles via its OWN
        PayoutIdToWinAmount (W3 §2). round_win_rule is null and no trigger pid."""
        assert m153_manifest.get("round_win_rule") is None, (
            "M153 must NOT declare a round_win_rule (st140 self-settles; adding "
            "a synth rule would double-attribute already-attributed wins)"
        )
        trig = m153_manifest.get("trigger") or {}
        assert trig.get("payout_id") is None, (
            "M153 has no separate-event trigger pid (the collect-window is an "
            "intra-ST state dimension, NOT a trigger into a new SpinType)"
        )
        assert trig.get("opens") is None


# ---------------------------------------------------------------------------
# 1. SINGLE-SPINTYPE STRUCTURE — exactly one ST, all reused plugins keyed to it.
# ---------------------------------------------------------------------------

class TestSingleSpinTypeStructure:
    def test_breakdown_has_exactly_one_st(self, m153_pi):
        rows = _st_breakdown_rows(m153_pi)
        sts = [int(r.get("spin_type")) for r in rows]
        assert sts == [_ST_BASE], (
            f"M153 is a single-ST machine; spin_type_breakdown must have exactly "
            f"[{_ST_BASE}]; got {sts}"
        )

    def test_sole_st_share_is_one_hundred_pct(self, m153_pi):
        """The sole ST carries 100% of the rounds — a SHARE IDENTITY, not a
        pinned count (the round count drifts; the share of the only ST is 1.0)."""
        rows = _st_breakdown_rows(m153_pi)
        assert len(rows) == 1
        assert rows[0]["share_pct"] == pytest.approx(100.0, abs=1e-6), (
            f"the sole ST must hold 100% share; got {rows[0]['share_pct']}"
        )

    def test_spin_type_coverage_is_full(self, m153_pi):
        """All emitted rounds are covered by a declared ST (coverage 1.0) — no
        un-classified events. Ratio identity, value-agnostic."""
        cov = m153_pi.get("spin_type_coverage")
        assert cov == pytest.approx(1.0, abs=1e-9), (
            f"spin_type_coverage must be 1.0 (every round is the declared st{_ST_BASE}); "
            f"got {cov}"
        )

    def test_all_reused_plugins_keyed_to_sole_st(self, m153_pi):
        """The 4 strict-reused PER_SPINTYPE plugins each key EXACTLY the one ST
        (ST140_paid) — no stray second ST, no missing ST."""
        for plug in (
            "payouts_by_spin_type",
            "reel_marginal_by_spin_type",
            "spin_type_outcomes",
            "spin_type_rtp_buckets",
        ):
            d = m153_pi.get(plug)
            assert isinstance(d, dict), f"{plug} missing or not a dict"
            assert sorted(d.keys()) == [_ST_KEY], (
                f"{plug} must key EXACTLY [{_ST_KEY!r}]; got {sorted(d.keys())}"
            )

    def test_no_preview_or_zero_contribution_phantom_st(self, m153_pi):
        """A 'preview' ST contributes 0 to RTP (charter invariant 1). M153 has
        NO preview ST — its sole ST is a real paid spin (feature_trigger_only
        False) that DOES contribute. So no ST is both counted AND zero-paying as
        a preview. (pid 9 zero-pays, but it is a payid ROW, not a separate ST.)"""
        rows = _st_breakdown_rows(m153_pi)
        for r in rows:
            assert r.get("feature_trigger_only") in (False, None), (
                f"M153 declares no preview/trigger-only ST; got "
                f"feature_trigger_only={r.get('feature_trigger_only')} on st{r.get('spin_type')}"
            )
        # The sole real ST DOES carry the machine's payback (not a zero phantom).
        assert rows[0]["rtp_contribution_pp"] > 0.0, (
            "the sole real paid ST must contribute the machine's payback "
            "(a preview ST would contribute 0; M153 has no preview ST)"
        )


# ---------------------------------------------------------------------------
# 2. ATTRIBUTION — st140 self-settles; sum(payid)==summary; no fallback; no
#    double-count; pid 9 (collect trigger) pays 0.
# ---------------------------------------------------------------------------

class TestAttributionSelfSettles:
    def test_rtp_integrity_passes(self, m153_summary):
        ric = m153_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M153 mode 1; got "
            f"passed={ric.get('passed')}, message={ric.get('summary_message','N/A')}."
        )

    def test_layer1_sum_invariant_holds(self, m153_summary):
        ric = m153_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant broken: {ric.get('layer1_error')}"
        )

    def test_no_unattributed_fallback_bucket(self, m153_summary, m153_pi):
        """L2: NO _unattributed_* fallback bucket — share == 0 (the W2-proven
        layer2_fallback_buckets_found []). A fallback bucket is the silent-drift
        signal (feedback_invariant_with_fallback_hides_drift)."""
        ric = m153_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}"
        )
        assert (ric.get("layer2_fallback_buckets_found") or []) == [], (
            f"M153 must have ZERO fallback buckets; got "
            f"{ric.get('layer2_fallback_buckets_found')}"
        )
        # No _unattributed_* pid leaked into the payid views.
        for pid in _payout_ids_top20(m153_pi):
            assert not pid.startswith("_unattributed"), (
                f"an _unattributed_* pid leaked into payout_ids_top20: {pid}"
            )
        for row in _payout_id_rows(m153_pi):
            assert not str(row.get("payout_id", "")).startswith("_unattributed"), (
                f"an _unattributed_* pid leaked into payouts_by_spin_type: {row}"
            )

    def test_payid_sum_equals_summary_rtp_no_double_count(self, m153_summary, m153_pi):
        """Σ payid rtp_contribution_pp == summary.rtp point_pct == the sole ST's
        rtp_contribution_pp. A SUM IDENTITY across three views (per-pid, summary,
        per-ST) — if any view double-counted (e.g. a phantom synth pid on top of
        the natural pids), these would diverge. VALUE-AGNOSTIC: we assert the
        three views AGREE, not what the number is."""
        sum_pid = sum(float(r.get("rtp_contribution_pp", 0.0)) for r in _payout_id_rows(m153_pi))
        summary_rtp = float(m153_summary["rtp"]["point_pct"])
        st_rtp = float(_st_breakdown_rows(m153_pi)[0]["rtp_contribution_pp"])
        assert sum_pid == pytest.approx(summary_rtp, abs=1e-3), (
            f"Σ payid rtp_pp ({sum_pid}) must equal summary.rtp ({summary_rtp}) — "
            "a divergence means an attribution view double-counts or drops."
        )
        assert st_rtp == pytest.approx(summary_rtp, abs=1e-3), (
            f"the sole ST's rtp_pp ({st_rtp}) must equal summary.rtp ({summary_rtp})"
        )

    def test_all_nine_natural_pids_present_trigger_pays_zero(self, m153_pi):
        """st140 attributes by its OWN PayoutIdToWinAmount — 9 natural pids, with
        the collect-window trigger pid 9 correctly a ZERO-paying row (it arms the
        window; it does not pay). A structural fact (the pid SET + the trigger's
        zero), not an RTP value."""
        rows = _payout_id_rows(m153_pi)
        pids = {str(r.get("payout_id")) for r in rows}
        assert pids == {"1", "2", "3", "4", "5", "7", "8", "9", "101"}, (
            f"M153 st140 has 9 natural payids; got {sorted(pids)}"
        )
        trig = next((r for r in rows if str(r.get("payout_id")) == _TRIGGER_PID), None)
        assert trig is not None, "pid 9 (collect trigger) must be a row"
        assert float(trig.get("total_win", -1)) == 0.0, (
            f"pid {_TRIGGER_PID} (collect trigger) must pay 0; got total_win="
            f"{trig.get('total_win')}"
        )
        assert float(trig.get("rtp_contribution_pp", -1)) == 0.0, (
            f"pid {_TRIGGER_PID} must contribute 0 rtp_pp; got "
            f"{trig.get('rtp_contribution_pp')}"
        )
        assert int(trig.get("hit_count", 0)) > 0, (
            "the trigger pid must still be HIT (it arms the window) even though "
            "it pays 0 — a counted, zero-paying event, not a dropped one"
        )

    def test_session_conservation_ok(self, m153_summary):
        ric = m153_summary.get("rtp_integrity_check", {})
        assert ric.get("session_conservation_level") == "ok", (
            f"session_conservation_level must be 'ok'; got "
            f"{ric.get('session_conservation_level')} "
            f"(skip_reason={ric.get('session_conservation_skip_reason')})"
        )


# ---------------------------------------------------------------------------
# 3. NO ROLE/PLAY/DIMENSION ANALYSIS ATTACHES — derive_analyses is the baseline.
# ---------------------------------------------------------------------------

class TestNoRolePlayAnalysisAttaches:
    def test_derive_analyses_is_exactly_baseline(self, m153_manifest):
        """roles={paid_spin}, plays={NormalCollectionSpin}, no dimension key →
        derive_analyses returns EXACTLY CROSS_CUTTING + PER_SPINTYPE. No
        role/play/dimension analysis attaches (the simplest onboard)."""
        from fresh_slotlab.analyzer.machine_spec import (
            derive_analyses, CROSS_CUTTING, PER_SPINTYPE,
        )
        baseline = sorted(set(CROSS_CUTTING) | set(PER_SPINTYPE))
        got = derive_analyses(m153_manifest)
        assert got == baseline, (
            f"M153 derive_analyses must equal the CROSS_CUTTING+PER_SPINTYPE "
            f"baseline; got {got}\nbaseline {baseline}"
        )
        for leak in _LEAK_ANALYSES:
            assert leak not in got, (
                f"{leak} must NOT be derived for M153 (no keying role/play/dim)"
            )

    def test_no_role_play_plugin_in_player_impact(self, m153_pi):
        """The real report contains NONE of the role/play/dimension plugin
        sections — no foreign mechanic view rendered onto a plain paid-spin
        machine (the gate-7 'no leaked panel' invariant, JSON side)."""
        for leak in _LEAK_ANALYSES:
            assert leak not in m153_pi, (
                f"player_impact must NOT contain {leak!r} for M153; a foreign "
                f"mechanic view leaked. present sections: {sorted(m153_pi.keys())}"
            )


# ---------------------------------------------------------------------------
# 4. collect_mechanic auto-fires but is RTP-INERT (framework-team heuristic FP).
# ---------------------------------------------------------------------------

class TestCollectMechanicInert:
    def test_collect_mechanic_present_but_rtp_inert(self, m153_summary):
        """The CROSS_CUTTING BCM collect_mechanic auto-fires (opt-out-free) and
        mis-describes M153's DECREMENT collect-window as a failed increment
        cycle — but it is RTP-INERT: it does NOT claim an RTP correction and so
        corrupts NO invariant. VALUE-AGNOSTIC: we assert the inertness flags, not
        any BCM-frame number (total_collects etc. are meaningless here)."""
        cm = m153_summary.get("collect_mechanic")
        assert isinstance(cm, dict), "collect_mechanic auto-attaches (CROSS_CUTTING)"
        bcc = cm.get("bonus_cycle_correction") or {}
        assert bcc.get("applicable") is False, (
            f"collect_mechanic must be RTP-INERT (bonus_cycle_correction.applicable "
            f"False) for M153's decrement window; got {bcc.get('applicable')}"
        )
        assert bcc.get("estimated_correction_pp") is None, (
            f"collect_mechanic must claim NO RTP correction; got "
            f"estimated_correction_pp={bcc.get('estimated_correction_pp')}"
        )
        # Being inert, it must NOT have moved integrity: the report still passes
        # (the BCM frame is display-only).
        assert m153_summary["rtp_integrity_check"].get("passed") is True


# ---------------------------------------------------------------------------
# 5. CROSS-MACHINE NON-LEAK — M153's keys fire on NO sibling and siblings' keys
#    are real (so M153 lacking them is a genuine structural fact, not a missing
#    registration). M44 minigame_dynamics / M104 lock_respin_dynamics / M63
#    nudge_dynamics / M278 freespin_dynamics / M279 wheel_dynamics must each fire
#    ONLY on their own machine — and NONE on M153.
# ---------------------------------------------------------------------------

class TestCrossMachineNonLeak:
    def test_sibling_analyses_are_real_and_machine_scoped(self):
        """The role/play/dimension analyses are REAL (a sibling that declares the
        key DOES derive it) AND scoped (M153, lacking the key, does NOT). This is
        the value of the non-leak: the keys exist, M153 simply has none of them.
        Pure manifest-level derivation — no report needed."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses, load_manifest

        expectations = {
            "M44": "minigame_dynamics",     # PLAY WinMiniGame
            "M104": "lock_respin_dynamics",  # PLAY LockSymbolSpin
            "M63": "nudge_dynamics",        # DIMENSION crazy_reel
            "M278": "freespin_dynamics",     # ROLE hold_respin
            "M279": "wheel_dynamics",       # PLAY Wheel
        }
        m153 = load_manifest("M153", _MANIFESTS_ROOT)
        m153_set = set(derive_analyses(m153))
        for mid, analysis in expectations.items():
            path = _MANIFESTS_ROOT / f"{mid}.json"
            if not path.exists():
                pytest.skip(f"{mid} manifest not present")
            sib = load_manifest(mid, _MANIFESTS_ROOT)
            sib_set = set(derive_analyses(sib))
            assert analysis in sib_set, (
                f"{analysis} must be REAL — derived for {mid} (its declaring "
                f"machine); got {sorted(sib_set)}"
            )
            assert analysis not in m153_set, (
                f"{analysis} ({mid}'s mechanic) must NOT leak onto M153"
            )

    def test_m153_keys_do_not_fire_on_a_sibling(self):
        """The converse leak direction: M153 declares NO role/play/dimension key
        that would pull a plugin — so there is nothing of M153's to leak ONTO a
        sibling. We assert M153 introduces no NEW analysis vs the baseline (so it
        cannot contaminate another machine's report)."""
        from fresh_slotlab.analyzer.machine_spec import (
            derive_analyses, load_manifest, CROSS_CUTTING, PER_SPINTYPE,
        )
        m153 = load_manifest("M153", _MANIFESTS_ROOT)
        introduced = set(derive_analyses(m153)) - (set(CROSS_CUTTING) | set(PER_SPINTYPE))
        assert introduced == set(), (
            f"M153 introduces ZERO machine-specific analyses (nothing to leak "
            f"onto a sibling); got {introduced}"
        )

    def test_minigame_dynamics_absent_on_m153_report(self, m153_pi):
        """Concrete instance of the M44 non-leak the charter names: M44's
        minigame_dynamics must NOT fire on M153 (it has no WinMiniGame play)."""
        assert "minigame_dynamics" not in m153_pi


# ---------------------------------------------------------------------------
# 6. INJECT-BUG PROOF — break each safety claim → RED → (auto-revert) → GREEN.
#
#    All injects mutate ONLY M153's OWN manifest, IN-PROCESS, via a monkeypatched
#    machine_spec.load_manifest that returns a mutated COPY (never an on-disk
#    write, never a shared plugin or another machine's file). monkeypatch
#    auto-reverts at test exit.
#
#    Claim A: M153 has NO leaked role/play/dimension plugin. Inject a foreign key
#             onto st140 → the plugin section APPEARS in player_impact (RED).
#    Claim B: the sole-ST structure / coverage holds because st140 is the only
#             declared ST. (proven via the baseline-derivation inject in Claim A's
#             derive_analyses path — a second ST or foreign key changes the set.)
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    @staticmethod
    def _patch_manifest(monkeypatch, mutate):
        """Make report_engine load a MUTATED copy of M153's OWN manifest."""
        import fresh_slotlab.analyzer.machine_spec as ms
        base = json.loads(_M153_MANIFEST.read_text(encoding="utf-8"))

        def _patched(machine_id, manifests_root):
            if machine_id == "M153":
                m = copy.deepcopy(base)
                mutate(m)
                return m
            return ms.validate_schema  # unreachable in this test (only M153 loads)

        monkeypatch.setattr(ms, "load_manifest", _patched)

    def test_inject_minigame_play_leaks_panel_then_reverts(self, monkeypatch):
        """INJECT (Claim A — M44 leak): set st140 play = WinMiniGame on M153's OWN
        manifest. minigame_dynamics now DERIVES and its section APPEARS in
        player_impact → the non-leak guard would have caught a real leak. RED."""
        if not _has_chunks(_M153_CHUNK_DIR):
            pytest.skip("M153 cached chunks not present")

        def _mut(m):
            m["spin_types"][str(_ST_BASE)]["play"] = "WinMiniGame"

        self._patch_manifest(monkeypatch, _mut)
        summary = _gen("M153", _M153_CHUNK_DIR)
        pi = summary["player_impact"]
        assert "minigame_dynamics" in pi, (
            "inject-bug: with play=WinMiniGame, minigame_dynamics MUST appear in "
            "player_impact (the foreign-panel leak). If it does not, the non-leak "
            "test_no_role_play_plugin_in_player_impact is worthless."
        )
        # monkeypatch auto-reverts here.

    def test_inject_crazy_reel_dimension_leaks_nudge_then_reverts(self, monkeypatch):
        """INJECT (Claim A — M63 leak): add a `crazy_reel` dimension block to
        st140. nudge_dynamics now DERIVES → the dimension-hook non-leak is
        proven load-bearing. RED at the derive_analyses level (no full report
        needed; the derive set is what gates the plugin)."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        base = json.loads(_M153_MANIFEST.read_text(encoding="utf-8"))
        mutated = copy.deepcopy(base)
        mutated["spin_types"][str(_ST_BASE)]["crazy_reel"] = {}
        got = derive_analyses(mutated)
        assert "nudge_dynamics" in got, (
            "inject-bug: with a crazy_reel dimension block, nudge_dynamics MUST be "
            "derived (the M63 dimension hook). If not, the dimension non-leak guard "
            "is worthless."
        )
        # No report state was touched — the unmutated on-disk manifest is intact.
        assert "nudge_dynamics" not in derive_analyses(base), (
            "revert check: the real (unmutated) M153 manifest derives NO nudge_dynamics"
        )

    def test_inject_respin_role_leaks_respin_then_reverts(self, monkeypatch):
        """INJECT (Claim A — M43/M279 leak): change st140 role to `respin`.
        respin_dynamics now DERIVES → the role-hook non-leak is proven. RED."""
        if not _has_chunks(_M153_CHUNK_DIR):
            pytest.skip("M153 cached chunks not present")

        def _mut(m):
            m["spin_types"][str(_ST_BASE)]["role"] = "respin"

        self._patch_manifest(monkeypatch, _mut)
        summary = _gen("M153", _M153_CHUNK_DIR)
        pi = summary["player_impact"]
        assert "respin_dynamics" in pi, (
            "inject-bug: with role=respin, respin_dynamics MUST appear in "
            "player_impact. If not, the role-hook non-leak guard is worthless."
        )
        # monkeypatch auto-reverts here.

    def test_inject_synth_rule_corrupts_payid_breakdown_then_reverts(self, monkeypatch):
        """INJECT (Claim — no synth rule needed): force a SynthesizePayIdRule onto
        M153's st140 (which already self-settles via its 9 natural pids). With
        apply_when_pid_present=True it ABSORBS the st140 win into a synthetic
        'st140' pid even though the natural pids already cover it — DESTROYING the
        9-natural-pid breakdown (it collapses to {'9','st140'}). This is the exact
        double-attribution the design's 'NO SynthesizePayIdRule' decision avoids.
        RED via the OBSERVABLE: a phantom 'st140' pid appears and the natural
        breakdown is corrupted. Proves the decision is load-bearing."""
        if not _has_chunks(_M153_CHUNK_DIR):
            pytest.skip("M153 cached chunks not present")
        import fresh_slotlab.round_win as rw_mod

        real_rules = rw_mod.load_rules_for_machine

        def _with_synth(machine_id, config):
            rules = list(real_rules(machine_id, config) or [])
            if machine_id == "M153":
                # apply_when_pid_present=True FORCES it to fire even though st140
                # already has natural pids (the default no-ops — exactly why the
                # design correctly adds NO such rule).
                rules.append(
                    rw_mod.SynthesizePayIdRule(
                        spin_types=[_ST_BASE],
                        label_format="spin_type",
                        apply_when_pid_present=True,
                    )
                )
            return rules

        monkeypatch.setattr(rw_mod, "load_rules_for_machine", _with_synth)
        summary = _gen("M153", _M153_CHUNK_DIR)
        pi = summary["player_impact"]
        pbs_pids = {str(r.get("payout_id")) for r in _payout_id_rows(pi)}
        # The phantom synth pid appears...
        assert "st140" in pbs_pids, (
            f"inject-bug: a forced SynthesizePayIdRule MUST surface a phantom "
            f"'st140' pid in payouts_by_spin_type; got {sorted(pbs_pids)}. If not, "
            "the 'NO synth rule' decision is untested."
        )
        # ...and the genuine 9-natural-pid breakdown is corrupted (the real report
        # has {1,2,3,4,5,7,8,9,101}; the synth absorbs them).
        natural = {"1", "2", "3", "4", "5", "7", "8", "9", "101"}
        assert pbs_pids != natural, (
            "inject-bug: the synth rule must CORRUPT the natural 9-pid breakdown "
            f"(the design's whole point); got {sorted(pbs_pids)}"
        )
        # monkeypatch auto-reverts here.

    def test_green_resumes_after_revert(self, m153_summary, m153_pi):
        """After every inject-bug monkeypatch reverts, the real (un-patched) report
        is GREEN: integrity passes, no fallback, single ST, NO leaked panel."""
        ric = m153_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert ric.get("layer2_no_fallback_buckets_ok") is True
        assert (ric.get("layer2_fallback_buckets_found") or []) == []
        rows = _st_breakdown_rows(m153_pi)
        assert [int(r["spin_type"]) for r in rows] == [_ST_BASE]
        for leak in _LEAK_ANALYSES:
            assert leak not in m153_pi
