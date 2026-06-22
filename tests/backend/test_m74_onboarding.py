"""M74 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This file asserts STRUCTURE / ATTRIBUTION / role-resolution / honesty INVARIANTS,
NEVER an RTP value or range. M74's numbers (RTP, hit-rates, per-payid shares,
multiplier-tier frequencies) drift on re-sample / re-tune / upstream config; pinning
ANY of them would be a brittle false alarm (charter permanent invariant 1). The only
hard constants asserted are STRUCTURAL ids fixed by the manifest (SpinType id 1, the
declared analysis set), the EXISTENCE of native payids (not their win values), and
the SHAPE of the frontend contract.

What M74 shipped (session_artifacts/_onboard/M74/03_design.md — the SIMPLEST archetype
in the fleet):
  - configs/machine_manifests/M74.json — ST1 paid_spin/Normal, STRICT-REUSE of the
    confirmed M15 paid_spin/Normal pipeline. NO new plugin. NO new role/play token.
    NO SynthesizePayIdRule. NO round_win_rule entry. The deliverable is a manifest +
    a verbatim reuse declaration.
  - Attribution is NATIVE: ST1 carries a real PayoutIdToWinAmount (exactly one pid per
    win); Σ payid == WinCredits with 0 violations → the fallback bucket is already []
    WITHOUT any synthesis (M74 is the INVERSE of M283/M278/M43/M279's no-payid
    settlement pattern).

Because M74 adds NOTHING to the shared role/play/dimension tables, its
derive_analyses set must equal CROSS_CUTTING ∪ PER_SPINTYPE EXACTLY — i.e. NONE of
the play/role/dimension-keyed analyses owned by OTHER machines (minigame_dynamics,
wheel_dynamics, lock_respin_dynamics, nudge_dynamics, respin_dynamics,
freespin_dynamics, topdollar_choice) may fire on M74's generic paid_spin/Normal ST1.
That inverse non-leak is the cross-machine guard for this archetype.

The whole test runs the REAL engine on the real cached chunk at rawdata/M74/mode_1
(charter invariant 3: run the real thing, pass bet=chunk _bet, read the real summary).

INJECT-BUG PROOFS (all M74-MANIFEST-ONLY — written into a temp manifests_root, the
real configs/machine_manifests/M74.json is NEVER edited; charter Wave-4 rule: inject
only into M74's OWN manifest, never a shared file):
  - flip ST1 play Normal→WinMiniGame  ⇒ minigame_dynamics LEAKS in (non-leak guard).
  - add a crazy_reel block to ST1       ⇒ nudge_dynamics LEAKS in (dimension non-leak).
  - flip ST1 role paid_spin→respin      ⇒ respin_dynamics LEAKS in (role non-leak).
  - declare a phantom never-observed ST2 ⇒ structure_drift.declared_sts_absent populates.
  - declare ST2 instead of ST1          ⇒ structure_drift.status=='fail', ST1 undeclared.
  - flip ST1 role paid_spin→freespin    ⇒ free_spin.applicable flips True (no-fabricated-bonus).
"""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M74_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M74" / "mode_1"
_M15_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M15" / "mode_1"
_M74_MANIFEST = _REPO_ROOT / "configs" / "machine_manifests" / "M74.json"

# The bet used during M74 sampling (cost=1000 per paid spin; chunk _bet=1000). The
# report is value-agnostic; bet only affects coin totals, which this test never
# asserts. (Charter M279 trap: bet must land in sampling.bet so the frontend "× bet"
# multiplier columns are SANE — but we never assert a multiplier VALUE.)
_BET = 1000

# The only SpinType M74/mode_1 emits — a manifest STRUCTURAL fact, not a frequency.
_ST_BASE = 1

# The exact analysis set a generic paid_spin/Normal single-ST machine derives.
# (CROSS_CUTTING ∪ PER_SPINTYPE; verified against machine_spec at runtime below.)
# The play/role/dimension-keyed analyses OWNED BY OTHER MACHINES that must NOT leak:
_FOREIGN_ANALYSES = frozenset({
    "minigame_dynamics",    # M43  play WinMiniGame
    "wheel_dynamics",       # M279 play Wheel
    "lock_respin_dynamics", # M104 play LockSymbolSpin
    "nudge_dynamics",       # M63  dimension crazy_reel
    "respin_dynamics",      # M43  role respin
    "freespin_dynamics",    # M275/M278 role freespin/hold_respin
    "topdollar_choice",     # M15  role player_choice (M74 has none)
})


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


def _payout_ids(summary) -> list[str]:
    return [
        str(r.get("payout_id", ""))
        for r in summary["player_impact"].get("payout_ids_top20", [])
    ]


def _gen(machine_id, chunk_dir, manifests_root=None):
    """Run the REAL engine; return the summary dict."""
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        kwargs = dict(chunk_dir=chunk_dir, output_dir=Path(tmpdir), bet=_BET)
        if manifests_root is not None:
            kwargs["manifests_root"] = manifests_root
        summary = generate_report_from_chunks(machine_id, 1, **kwargs)
        if manifests_root is None:
            assert (Path(tmpdir) / "player_impact_summary.json").exists(), (
                "write_summary_json must produce player_impact_summary.json"
            )
        return summary


def _gen_with_manifest(manifest_dict):
    """Run the REAL engine against an INJECTED M74 manifest in a temp manifests_root
    (the real configs/machine_manifests/M74.json is never touched)."""
    with tempfile.TemporaryDirectory() as mroot:
        (Path(mroot) / "M74.json").write_text(json.dumps(manifest_dict), encoding="utf-8")
        return _gen("M74", _M74_CHUNK_DIR, manifests_root=Path(mroot))


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m74_summary():
    if not _has_chunks(_M74_CHUNK_DIR):
        pytest.skip("M74 cached chunks not present")
    return _gen("M74", _M74_CHUNK_DIR)


@pytest.fixture(scope="module")
def m74_player_impact(m74_summary):
    return m74_summary["player_impact"]


@pytest.fixture(scope="module")
def m74_manifest():
    if not _M74_MANIFEST.exists():
        pytest.skip("M74 manifest not present")
    return json.loads(_M74_MANIFEST.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 0. Smoke — the report generates with no feature errors.
# ---------------------------------------------------------------------------

class TestReportGenerates:
    def test_machine_and_mode(self, m74_summary):
        assert m74_summary["machine"] == "M74"
        assert m74_summary["mode"] == 1
        assert m74_summary["sampling"]["chunks"] > 0
        assert m74_summary["sampling"]["total_spins"] > 0
        assert not m74_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m74_summary.get('feature_errors')}"
        )

    def test_bet_lands_in_sampling(self, m74_summary):
        """The M279 trap guard: bet must land in sampling.bet so the frontend's
        '× bet' multiplier columns are not 1000×-inflated. We assert the bet was
        threaded (a structural plumbing fact), NOT any multiplier VALUE."""
        assert m74_summary["sampling"].get("bet") == _BET, (
            f"bet must be threaded into sampling.bet; got {m74_summary['sampling'].get('bet')}"
        )

    def test_manifest_is_single_st_strict_reuse(self, m74_manifest):
        """M74 declares EXACTLY one ST (id 1) as paid_spin/Normal — the strict-reuse
        archetype. No second event ST, no new role/play token."""
        st = m74_manifest["spin_types"]
        assert list(st.keys()) == [str(_ST_BASE)], (
            f"M74 must declare exactly ST{_ST_BASE}; got {list(st.keys())}"
        )
        assert st[str(_ST_BASE)]["role"] == "paid_spin"
        assert st[str(_ST_BASE)]["play"] == "Normal"
        # No SynthesizePayIdRule / round_win_rule entry (native-payid attribution).
        assert str(m74_manifest.get("round_win_rule", "")).lower().startswith("none"), (
            "M74 must declare NO round_win_rule (native payid attribution)"
        )


# ---------------------------------------------------------------------------
# 1. FRONTEND CONTRACT — the panels the console renders must all be present.
# ---------------------------------------------------------------------------

class TestFrontendContract:
    # The panels the M15 paid_spin/Normal pipeline ships and the console renders.
    _REQUIRED_PI_KEYS = (
        "spin_type_breakdown",
        "spin_type_coverage",
        "spin_type_outcomes",
        "spin_type_rtp_buckets",
        "payouts_by_spin_type",
        "reel_marginal_by_spin_type",
        "multiplier_profile",
        "machine_mechanics",
        "upstream_feature_breakdown",
        "bonus_chain_dynamics",
        "bankruptcy_simulation",
        "payout_ids_top20",
    )

    @pytest.mark.parametrize("key", _REQUIRED_PI_KEYS)
    def test_frontend_contract_key_present(self, m74_player_impact, key):
        assert key in m74_player_impact, (
            f"frontend-contract key {key!r} missing from player_impact"
        )

    def test_spin_type_breakdown_declares_only_st1(self, m74_player_impact):
        """The single declared ST's output is present and is the only ST.
        VALUE-AGNOSTIC: assert the ST id + role/feature LABELS, never the counts."""
        stb = m74_player_impact["spin_type_breakdown"]
        assert isinstance(stb, list) and len(stb) == 1, (
            f"M74 emits exactly one ST; got {len(stb)} rows"
        )
        row = stb[0]
        assert row["spin_type"] == _ST_BASE
        assert row["behavior_name"] == "paid"
        assert row["feature_name"] == "Normal"
        assert row["share_pct"] == 100.0, (
            "ST1 is 100% of rounds (a structural single-ST fact, not a tuned rate)"
        )

    def test_spin_type_outcomes_present_for_st1(self, m74_player_impact):
        """The declared ST's per-ST outcomes panel is present (win-bands etc.)."""
        outcomes = m74_player_impact["spin_type_outcomes"]
        assert "ST1_paid" in outcomes, (
            f"spin_type_outcomes must carry the declared ST1; got {list(outcomes.keys())}"
        )
        assert isinstance(outcomes["ST1_paid"].get("win_bands"), list)

    def test_payouts_by_spin_type_keyed_on_st1(self, m74_player_impact):
        """payouts_by_spin_type is keyed by the single ST1; its rows carry the
        native payids + decoded symbol_combo (the 'which symbol/line paid' surface)."""
        pbs = m74_player_impact["payouts_by_spin_type"]
        assert list(pbs.keys()) == ["ST1_paid"], (
            f"payouts_by_spin_type must be keyed on the single ST1; got {list(pbs.keys())}"
        )
        rows = pbs["ST1_paid"]
        assert isinstance(rows, list) and len(rows) > 0
        for r in rows:
            assert "payout_id" in r and "hit_count" in r and "rtp_contribution_pp" in r
            sc = r.get("symbol_combo") or {}
            assert "dominant" in sc, "each payid row must decode its dominant symbol combo"


# ---------------------------------------------------------------------------
# 2. NATIVE-PAYID ATTRIBUTION — sum(payid)==summary, ZERO fallback, NO synthesis.
# ---------------------------------------------------------------------------

class TestNativePayidAttribution:
    def test_rtp_integrity_passes(self, m74_summary):
        ric = m74_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M74 mode 1; got "
            f"passed={ric.get('passed')}, message={ric.get('summary_message','N/A')}"
        )

    def test_layer1_sum_invariant_holds(self, m74_summary):
        ric = m74_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant broken (Σ payid != our_total): {ric.get('layer1_error')}"
        )

    def test_no_unattributed_fallback_bucket(self, m74_summary):
        """The headline value-agnostic guard: NO _unattributed_* bucket (Layer-2),
        WITHOUT any SynthesizePayIdRule — ST1 attributes natively."""
        ric = m74_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}"
        )
        assert (ric.get("layer2_fallback_buckets_found") or []) == [], (
            "M74's native-payid attribution must leave ZERO fallback buckets"
        )
        pids = _payout_ids(m74_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )
        assert not any(p.startswith("_other") for p in pids), (
            f"an _other* garbage-bucket pid leaked into payout_ids_top20: {pids}"
        )

    def test_native_payids_present(self, m74_summary):
        """Real native payids are present (existence, NOT win values). A single-line
        machine attributes every win to a native winning-symbol/line code."""
        pids = _payout_ids(m74_summary)
        assert len(pids) > 0, "M74 must surface native payids"
        # Every surfaced payid is a real (numeric-string) native code, not a synthesized
        # st-label and not a fallback bucket.
        for p in pids:
            assert p.isdigit(), (
                f"M74 attributes via NATIVE numeric payids (no synthesized st-labels); "
                f"got non-native pid {p!r}"
            )

    def test_layer3_anchors_ok(self, m74_summary):
        ric = m74_summary.get("rtp_integrity_check", {})
        assert ric.get("layer3_anchors_ok") is True, (
            f"Layer-3 anchors broken: missing {ric.get('layer3_missing_anchors')}"
        )

    def test_session_conservation_ok(self, m74_summary):
        """No win lost to attribution (real-economy machine)."""
        ric = m74_summary.get("rtp_integrity_check", {})
        assert ric.get("session_conservation_level") == "ok", (
            f"session_conservation_level must be 'ok'; got "
            f"{ric.get('session_conservation_level')} "
            f"(skip_reason={ric.get('session_conservation_skip_reason')})"
        )


# ---------------------------------------------------------------------------
# 3. STRUCTURE HONESTY — single ST, declared==observed, NO fabricated bonus.
# ---------------------------------------------------------------------------

class TestStructureHonesty:
    def test_structure_drift_clean(self, m74_summary):
        sd = m74_summary.get("structure_drift", {})
        assert sd.get("status") == "ok", (
            f"structure_drift must be ok; got {sd.get('status')} "
            f"undeclared={sd.get('undeclared_sts')} absent={sd.get('declared_sts_absent')}"
        )
        assert (sd.get("undeclared_sts") or []) == [], (
            f"every observed ST must be declared; undeclared={sd.get('undeclared_sts')}"
        )
        assert (sd.get("declared_sts_absent") or []) == [], (
            f"no phantom declared-but-absent ST; absent={sd.get('declared_sts_absent')}"
        )
        assert sd.get("audited_rounds", 0) > 0

    def test_no_fabricated_bonus_mechanics(self, m74_player_impact):
        """M74 has NO bonus/freespin/jackpot/collect — the mechanics panels must
        correctly read inert (NOT invent a feature). Charter design metric #7."""
        mm = m74_player_impact["machine_mechanics"]
        assert mm["free_spin"]["applicable"] is False, "M74 must NOT invent a free_spin"
        assert mm["jackpot"]["applicable"] is False, "M74 must NOT invent a jackpot"
        assert mm["lock_lines"]["applicable"] is False
        assert mm["lock_symbols"]["applicable"] is False
        assert mm["lock_reels"]["applicable"] is False
        assert mm["dollar_pick"]["applicable"] is False

    def test_collect_metronome_inert(self, m74_summary):
        cm = m74_summary.get("collect_mechanic", {})
        assert cm.get("applicable") is False, (
            "M74 has no collect metronome; collect_mechanic must be inert"
        )

    def test_bonus_chain_inert(self, m74_player_impact):
        bcd = m74_player_impact["bonus_chain_dynamics"]
        assert bcd.get("applicable") is False, (
            "M74 has no bonus chain; bonus_chain_dynamics must be inert"
        )

    def test_upstream_single_feature_normal(self, m74_player_impact):
        ufb = m74_player_impact["upstream_feature_breakdown"]
        feats = [f.get("feature_name") for f in (ufb.get("features") or [])]
        assert feats == ["Normal"], (
            f"M74's only upstream feature is 'Normal'; got {feats}"
        )


# ---------------------------------------------------------------------------
# 4. CROSS-MACHINE NON-LEAK — M74's generic paid_spin/Normal must derive EXACTLY
#    CROSS_CUTTING ∪ PER_SPINTYPE — none of the play/role/dimension-keyed analyses
#    OWNED BY OTHER MACHINES may attach. (The inverse non-leak for the strict-reuse
#    archetype: M74 adds nothing to the shared tables, so it must pick up nothing.)
# ---------------------------------------------------------------------------

class TestCrossMachineNonLeak:
    def test_m74_derives_exactly_cross_cutting_plus_per_spintype(self, m74_manifest):
        from fresh_slotlab.analyzer.machine_spec import (
            derive_analyses, CROSS_CUTTING, PER_SPINTYPE,
        )
        expected = sorted(set(CROSS_CUTTING) | set(PER_SPINTYPE))
        got = derive_analyses(m74_manifest)
        assert got == expected, (
            f"M74's derive_analyses must equal CROSS_CUTTING ∪ PER_SPINTYPE exactly "
            f"(generic paid_spin/Normal, no role/play/dimension extras); got {got}"
        )

    def test_no_foreign_analysis_attaches_to_m74(self, m74_manifest):
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        got = set(derive_analyses(m74_manifest))
        leaked = got & _FOREIGN_ANALYSES
        assert not leaked, (
            f"foreign play/role/dimension-keyed analyses leaked onto M74: {sorted(leaked)}"
        )

    def test_foreign_analysis_sections_inert_in_real_report(self, m74_player_impact):
        """A foreign analysis must not even render an applicable section. wheel_dynamics
        / minigame_dynamics / topdollar_choice / respin_dynamics / freespin_dynamics /
        nudge_dynamics / lock_respin_dynamics — if present at all (some are not even
        keys) they must be inert (a preview/foreign ST contributes 0)."""
        for name in _FOREIGN_ANALYSES:
            sect = m74_player_impact.get(name)
            if sect is None:
                continue  # not even emitted — strongest non-leak
            assert sect.get("applicable") is False, (
                f"foreign analysis {name!r} must be inert (applicable False) on M74; "
                f"got {sect.get('applicable')}"
            )

    def test_m15_unaffected_by_m74_strict_reuse(self):
        """ADDITIVITY: M74 adds NOTHING to the shared role/play/dimension tables, so
        M15 (whose ST1 M74 byte-matches) must derive its own set unchanged — incl. its
        OWN topdollar_choice, which M74 must NOT have. Proves M74 did not perturb the
        shared resolution that M15 depends on."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        m15_manifest_path = _REPO_ROOT / "configs" / "machine_manifests" / "M15.json"
        if not m15_manifest_path.exists():
            pytest.skip("M15 manifest not present")
        m15 = json.loads(m15_manifest_path.read_text(encoding="utf-8"))
        da15 = set(derive_analyses(m15))
        assert "topdollar_choice" in da15, (
            "M15's player_choice role must STILL resolve topdollar_choice (unaffected)"
        )


# ---------------------------------------------------------------------------
# 5. FROZEN-FRAMEWORK GUARD — M74 onboarding must not move the base hash.
# ---------------------------------------------------------------------------

class TestBaseHashUnchanged:
    def test_base_hash_is_current_baseline(self):
        """M74 is a manifest-only strict-reuse onboard (no plugin / no closure edit).
        The fleet base_hash baseline is d17c69c251ed (re-baselined 2026-06-22 by the
        pluggable round_win rule-engine refactor — rule types moved to base-EXCLUDED
        round_win_rules/; prior pin 3ddaa183f38c was stale, missed across the
        intervening WinResidualRule / settlement_label_format flips). M74 must equal
        the current baseline — a move means a closure/shared file was edited (which
        M74 must never do)."""
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        bh = compute_base_analyzer_version()
        assert bh == "d17c69c251ed", (
            f"base_hash changed from the d17c69c251ed baseline to {bh!r}. M74 "
            f"onboarding is manifest-only — a base_hash change means a closure/shared "
            f"file was edited (or a deliberate closure change needs this updated)."
        )


# ---------------------------------------------------------------------------
# INJECT-BUG PROOFS — break each safety claim → RED → (auto-revert) → GREEN.
#
# ALL injections write a MUTATED COPY of the M74 manifest into a temp manifests_root
# (charter Wave-4 rule: inject ONLY into M74's own manifest; the real
# configs/machine_manifests/M74.json is NEVER edited). Each helper builds + discards
# its own temp tree, so the module-scoped fixtures (built from the REAL manifest) stay
# GREEN (every class above).
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_play_winminigame_leaks_minigame_dynamics(self):
        """INJECT (non-leak / PLAY): flip ST1 play Normal→WinMiniGame. minigame_dynamics
        now derives onto M74 — proving test_no_foreign_analysis_attaches_to_m74 is a
        real guard, not vacuously green. VALUE-AGNOSTIC (a derived-set membership, not
        a number)."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        m74 = json.loads(_M74_MANIFEST.read_text(encoding="utf-8"))
        inj = copy.deepcopy(m74)
        inj["spin_types"]["1"]["play"] = "WinMiniGame"
        assert "minigame_dynamics" in derive_analyses(inj), (
            "inject-bug: play=WinMiniGame must leak minigame_dynamics onto M74"
        )
        # REVERT (re-read real manifest) → GREEN:
        assert "minigame_dynamics" not in derive_analyses(m74)

    def test_inject_crazy_reel_block_leaks_nudge_dynamics(self):
        """INJECT (non-leak / DIMENSION): add a crazy_reel block to ST1. nudge_dynamics
        now derives onto M74 — proving the dimension non-leak guard catches a regression."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        m74 = json.loads(_M74_MANIFEST.read_text(encoding="utf-8"))
        inj = copy.deepcopy(m74)
        inj["spin_types"]["1"]["crazy_reel"] = {"discriminator": "ReMarks"}
        assert "nudge_dynamics" in derive_analyses(inj), (
            "inject-bug: a crazy_reel ST block must leak nudge_dynamics onto M74"
        )
        assert "nudge_dynamics" not in derive_analyses(m74)

    def test_inject_role_respin_leaks_respin_dynamics(self):
        """INJECT (non-leak / ROLE): flip ST1 role paid_spin→respin. respin_dynamics
        now derives onto M74 — proving the role non-leak guard catches a regression."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        m74 = json.loads(_M74_MANIFEST.read_text(encoding="utf-8"))
        inj = copy.deepcopy(m74)
        inj["spin_types"]["1"]["role"] = "respin"
        assert "respin_dynamics" in derive_analyses(inj), (
            "inject-bug: role=respin must leak respin_dynamics onto M74"
        )
        assert "respin_dynamics" not in derive_analyses(m74)

    def test_inject_phantom_st_populates_declared_absent(self):
        """INJECT (structure honesty): declare a phantom ST2 that is never observed.
        structure_drift.declared_sts_absent must populate with '2' — proving the
        test_structure_drift_clean guard is a real catch. Runs the REAL engine on an
        injected manifest in a temp manifests_root."""
        if not _has_chunks(_M74_CHUNK_DIR):
            pytest.skip("M74 cached chunks not present")
        m74 = json.loads(_M74_MANIFEST.read_text(encoding="utf-8"))
        inj = copy.deepcopy(m74)
        inj["spin_types"]["2"] = {
            "role": "settlement", "play": "Wheel", "signature": ["WinCredits"],
        }
        summary = _gen_with_manifest(inj)
        sd = summary.get("structure_drift", {})
        assert "2" in (sd.get("declared_sts_absent") or []), (
            f"inject-bug: phantom ST2 must populate declared_sts_absent; got {sd}"
        )
        # REVERT (real manifest) → GREEN:
        real = _gen("M74", _M74_CHUNK_DIR)
        assert (real["structure_drift"].get("declared_sts_absent") or []) == []

    def test_inject_undeclared_st_flips_structure_drift_fail(self):
        """INJECT (structure honesty): declare ST2 INSTEAD of ST1, so the real ST1 is
        UNDECLARED. structure_drift.status must flip to 'fail' and ST1 must appear in
        undeclared_sts — proving the every-observed-ST-is-declared guard."""
        if not _has_chunks(_M74_CHUNK_DIR):
            pytest.skip("M74 cached chunks not present")
        m74 = json.loads(_M74_MANIFEST.read_text(encoding="utf-8"))
        inj = copy.deepcopy(m74)
        inj["spin_types"] = {"2": copy.deepcopy(m74["spin_types"]["1"])}
        summary = _gen_with_manifest(inj)
        sd = summary.get("structure_drift", {})
        assert sd.get("status") == "fail", (
            f"inject-bug: an undeclared observed ST1 must flip structure_drift to fail; got {sd}"
        )
        undeclared = {str(u.get("st")) for u in (sd.get("undeclared_sts") or [])}
        assert "1" in undeclared, (
            f"inject-bug: ST1 must appear in undeclared_sts; got {sd.get('undeclared_sts')}"
        )
        real = _gen("M74", _M74_CHUNK_DIR)
        assert real["structure_drift"].get("status") == "ok"

    def test_inject_role_freespin_fabricates_bonus(self):
        """INJECT (no-fabricated-bonus): flip ST1 role paid_spin→freespin. machine_mechanics
        free_spin.applicable must flip True — proving test_no_fabricated_bonus_mechanics
        is a real catch (the baseline correctly reads inert)."""
        if not _has_chunks(_M74_CHUNK_DIR):
            pytest.skip("M74 cached chunks not present")
        m74 = json.loads(_M74_MANIFEST.read_text(encoding="utf-8"))
        inj = copy.deepcopy(m74)
        inj["spin_types"]["1"]["role"] = "freespin"
        summary = _gen_with_manifest(inj)
        fs = summary["player_impact"]["machine_mechanics"]["free_spin"]
        assert fs.get("applicable") is True, (
            f"inject-bug: role=freespin must flip free_spin.applicable True; got {fs.get('applicable')}"
        )
        real = _gen("M74", _M74_CHUNK_DIR)
        assert real["player_impact"]["machine_mechanics"]["free_spin"]["applicable"] is False

    def test_green_resumes_after_all_injects(self, m74_summary, m74_manifest):
        """After every inject helper above builds + discards its own temp tree, the
        real (un-injected) report is GREEN: integrity passes, zero fallback, structure
        clean, no foreign analysis, base_hash intact."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        ric = m74_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert (ric.get("layer2_fallback_buckets_found") or []) == []
        assert m74_summary["structure_drift"].get("status") == "ok"
        assert not (set(derive_analyses(m74_manifest)) & _FOREIGN_ANALYSES)
        assert compute_base_analyzer_version() == "d17c69c251ed"  # re-baselined by pluggable round_win refactor (2026-06-22)
