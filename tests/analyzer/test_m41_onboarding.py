"""M41 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This file asserts STRUCTURE / CONSERVATION / ATTRIBUTION / role-resolution /
honesty / NON-LEAK INVARIANTS, NEVER an RTP value or range. M41's numbers (RTP,
hit-rate, per-pid shares, tail share) drift on re-sample / re-tune / upstream
re-config; pinning ANY of them would be a brittle false alarm (charter permanent
invariant 1). The only hard constants asserted are STRUCTURAL ids fixed by the
manifest (SpinType 1) and ARITHMETIC identities (the three RTP views must be
EQUAL to each other — a parity identity, not a pinned value).

What M41 is (session_artifacts/_onboard/M41/03_design.md + the manifest):
  - configs/machine_manifests/M41.json — a PURE-REUSE, single-SpinType base
    machine. ST1 role=paid_spin / play=Normal. `trigger` empty (constant
    GameplayTriggerType 0, empty ReMarks). `round_win_rule` null (native
    PayoutIdToWinAmount payId on 100% of wins → nothing to synthesize). modes [1].
  - ZERO new plugins, ZERO config rules, ZERO ROLE/PLAY/DIMENSION hooks. M41 rides
    the M15-class generic base set: derive_analyses(M41) == CROSS_CUTTING ∪
    PER_SPINTYPE exactly. It is the NON-LEAK BASELINE the role-vs-play discipline
    protects — a machine that shares ST *number* 1 with M15's base ST yet must NOT
    pick up any of M15/M43/M104/M63/M275/M278/M279's feature-keyed analyses.

The whole test runs the REAL engine on the real cached chunk at rawdata/M41/mode_1
(charter invariant 3: run the real thing, pass bet=chunk _bet=1000, read the real
summary — NEVER an echo'd exit code, NEVER "looks green").
"""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M41_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M41" / "mode_1"
_M15_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M15" / "mode_1"
_MANIFESTS_ROOT = _REPO_ROOT / "configs" / "machine_manifests"
_M41_MANIFEST = _MANIFESTS_ROOT / "M41.json"

_BET = 1000  # the chunk _bet (rawdata/M41/mode_1/chunk_0002.json["_bet"] == 1000).
_ST_BASE = 1  # the single base paid spin (the only ST M41 emits).
_FALLBACK_ST1 = "_unattributed_st1"

# The feature-keyed analyses that must NEVER attach to M41 (it declares neither a
# keyed role nor a keyed play nor a dimension block). Each is owned by a different
# machine's feature; M41 leaking ANY of them would be a cross-machine fire.
_LEAKY_ANALYSES = frozenset({
    "topdollar_choice",    # M15 ST14 player_choice role
    "respin_dynamics",     # M43 ST50 respin role
    "freespin_dynamics",   # M275 freespin / M278 hold_respin role
    "wheel_dynamics",      # M279 Wheel play
    "minigame_dynamics",   # M43 WinMiniGame play
    "lock_respin_dynamics",  # M104 LockSymbolSpin play
    "nudge_dynamics",      # M63 crazy_reel dimension block
})


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


def _payout_ids(summary) -> list[str]:
    return [
        str(r.get("payout_id", ""))
        for r in summary["player_impact"].get("payout_ids_top20", [])
    ]


def _st_row(summary, st: int):
    for row in summary["player_impact"].get("spin_type_breakdown", []):
        try:
            if int(row.get("spin_type")) == st:
                return row
        except (TypeError, ValueError):
            continue
    return None


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m41_summary():
    if not _has_chunks(_M41_CHUNK_DIR):
        pytest.skip("M41 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            "M41", 1,
            chunk_dir=_M41_CHUNK_DIR,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        # The summary must actually be written (not just returned) — gate against
        # an engine that returns a dict but never persisted player_impact_summary.json.
        assert (Path(tmpdir) / "player_impact_summary.json").exists()
        yield summary


@pytest.fixture(scope="module")
def m41_player_impact(m41_summary):
    return m41_summary["player_impact"]


@pytest.fixture(scope="module")
def m41_manifest():
    if not _M41_MANIFEST.exists():
        pytest.skip("M41 manifest not present")
    return json.loads(_M41_MANIFEST.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 0. Smoke + manifest declaration (the STRUCTURE the report is built from).
# ---------------------------------------------------------------------------

class TestReportGenerates:
    def test_machine_and_mode(self, m41_summary):
        assert m41_summary["machine"] == "M41"
        assert m41_summary["mode"] == 1
        assert m41_summary["sampling"]["chunks"] > 0
        assert m41_summary["sampling"]["total_spins"] > 0
        assert not m41_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m41_summary.get('feature_errors')}"
        )

    def test_bet_not_inflated(self, m41_summary):
        """The M279 ×bet trap: bet=chunk _bet must land in sampling.bet so the
        frontend ×bet columns are NOT 1000× inflated. VALUE-AGNOSTIC: asserts the
        bet wiring (==_BET), not any multiplier value."""
        assert m41_summary["sampling"].get("bet") == _BET, (
            f"sampling.bet must equal the chunk _bet ({_BET}) so the frontend "
            f"×bet columns render sane; got {m41_summary['sampling'].get('bet')}. "
            "A bet=1 summary renders 1000× inflated multipliers (the M279 trap)."
        )

    def test_manifest_single_st_paid_spin_normal(self, m41_manifest):
        """M41 is the single-SpinType base game: ST1 role=paid_spin / play=Normal,
        and NOTHING else. No second ST (no choice/settlement/state/collect/freespin/
        respin/wheel/minigame event)."""
        st = m41_manifest["spin_types"]
        assert list(st.keys()) == [str(_ST_BASE)], (
            f"M41 must declare EXACTLY one SpinType ({_ST_BASE}); got {list(st.keys())}. "
            "A second ST would change the whole shape (no longer the base-only baseline)."
        )
        assert st[str(_ST_BASE)]["role"] == "paid_spin"
        assert st[str(_ST_BASE)]["play"] == "Normal"

    def test_manifest_no_synthesize_rule_and_no_trigger(self, m41_manifest):
        """Native PayoutIdToWinAmount payId is the attribution dimension → NO
        synthesize rule (round_win_rule null), and constant GameplayTriggerType 0 /
        empty ReMarks → empty trigger block. Both are load-bearing: a stray rule or
        trigger would invent attribution M41's data does not have."""
        assert m41_manifest.get("round_win_rule") is None, (
            "M41 must have round_win_rule null (native payId on 100% of wins; "
            f"nothing to synthesize); got {m41_manifest.get('round_win_rule')!r}"
        )
        assert not m41_manifest.get("trigger"), (
            "M41 trigger must be empty (GameplayTriggerType constant 0, ReMarks "
            f"empty); got {m41_manifest.get('trigger')!r}"
        )

    def test_manifest_declares_only_mode_1(self, m41_manifest):
        """modes [1] only — modes 2/5/7 dirs exist but are EMPTY (not fetched, dev
        cache discipline). Extend on data, never by assumption."""
        assert m41_manifest.get("modes") == [1], (
            f"M41 must declare modes [1] only; got {m41_manifest.get('modes')}"
        )


# ---------------------------------------------------------------------------
# 1. SHAPE — exactly one ST, at 100% share, role=paid.
# ---------------------------------------------------------------------------

class TestSingleSpinTypeShape:
    def test_exactly_one_st_in_breakdown(self, m41_player_impact):
        """spin_type_breakdown carries exactly one row — ST1 — at 100% share. The
        EVENT taxonomy is single-ST; any extra row would mean an undeclared event."""
        stb = m41_player_impact.get("spin_type_breakdown")
        assert isinstance(stb, list) and len(stb) == 1, (
            f"M41 must emit exactly one ST row; got {stb!r}"
        )
        row = stb[0]
        assert int(row.get("spin_type")) == _ST_BASE
        assert row.get("share_pct") == 100.0, (
            f"the only ST must hold 100% of the EVENT share; got {row.get('share_pct')}"
        )
        assert row.get("behavior_name") == "paid", (
            f"ST1 behavior must be 'paid'; got {row.get('behavior_name')}"
        )
        assert row.get("feature_name") == "Normal"

    def test_payouts_keyed_only_on_st1_paid(self, m41_player_impact):
        """payouts_by_spin_type carries exactly the one ST1_paid bucket — no
        phantom second-ST or preview bucket."""
        pbst = m41_player_impact.get("payouts_by_spin_type")
        assert isinstance(pbst, dict)
        assert list(pbst.keys()) == ["ST1_paid"], (
            f"payouts must be keyed only on ST1_paid; got {list(pbst.keys())}"
        )

    def test_reel_marginal_keyed_only_on_st1_paid(self, m41_player_impact):
        rm = m41_player_impact.get("reel_marginal_by_spin_type")
        assert isinstance(rm, dict)
        assert list(rm.keys()) == ["ST1_paid"], (
            f"reel marginals must be keyed only on ST1_paid; got {list(rm.keys())}"
        )


# ---------------------------------------------------------------------------
# 2. RTP INTEGRITY — passed, L1/L2/L3, fallback==0, our==server (conditional),
#    session conservation ok. The anti-false-green core.
# ---------------------------------------------------------------------------

class TestRtpIntegrity:
    def test_integrity_passed(self, m41_summary):
        ric = m41_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M41 mode 1; got "
            f"passed={ric.get('passed')}, message={ric.get('summary_message','N/A')}."
        )

    def test_layer1_sum_invariant_holds(self, m41_summary):
        ric = m41_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 sum invariant (Σpid_win == our_total) broken: "
            f"{ric.get('layer1_error')}"
        )

    def test_no_fallback_bucket(self, m41_summary):
        """L2: NO _unattributed_* fallback bucket. M41's native payId space (pids
        3-10 from PayoutIdToWinAmount) attributes 100% of wins — the fallback is
        already 0 with no synthesize rule (feedback_invariant_with_fallback_hides_drift:
        a non-zero fallback is a structural drift signal, not an accounting close)."""
        ric = m41_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}"
        )
        assert (ric.get("layer2_fallback_buckets_found") or []) == [], (
            "fallback bucket list must be empty for M41"
        )
        pids = _payout_ids(m41_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )

    def test_layer3_anchors_ok(self, m41_summary):
        ric = m41_summary.get("rtp_integrity_check", {})
        assert ric.get("layer3_anchors_ok") is True, (
            f"Layer-3 anchors broken; missing: {ric.get('layer3_missing_anchors')}"
        )

    def test_our_equals_server_when_present(self, m41_summary):
        """L1 our==server ONLY when the server aggregate is present. M41's chunk
        carries no server_total_win, so this is conditionally skipped — but if a
        future re-sample populates it, the two must agree. VALUE-AGNOSTIC: equality,
        not a pinned win total."""
        rtp = m41_summary.get("rtp", {})
        server = rtp.get("server_total_win")
        if server is None:
            pytest.skip("M41 chunk has no server aggregate (server_total_win None)")
        assert rtp.get("our_total_win") == server, (
            f"our_total_win {rtp.get('our_total_win')} != server_total_win {server}"
        )

    def test_session_conservation_ok(self, m41_summary):
        ric = m41_summary.get("rtp_integrity_check", {})
        assert ric.get("session_conservation_level") == "ok", (
            f"session_conservation_level must be 'ok'; got "
            f"{ric.get('session_conservation_level')} "
            f"(skip_reason={ric.get('session_conservation_skip_reason')})"
        )


# ---------------------------------------------------------------------------
# 3. ATTRIBUTION PARITY — the three RTP views are EQUAL (no double-count, no
#    under-count). This is the M41 "preview/no-payid does not double-count"
#    invariant in its degenerate (single-ST, native-payId) form.
# ---------------------------------------------------------------------------

class TestAttributionParity:
    def test_three_rtp_views_are_equal(self, m41_summary, m41_player_impact):
        """summary.rtp.point_pct == ST1 rtp_contribution_pp == Σ(per-pid rtp_pp)
        == Σ(payout_ids_top20 rtp_pp). A parity IDENTITY (feedback_aggregator_parity_
        invariant): every aggregator must see the SAME RTP from its own angle. If
        the native payId path double-counted (e.g. read the payline-string mid-segment
        X as a second pid) or under-counted, these would DIVERGE. VALUE-AGNOSTIC:
        we assert the four are EQUAL to each other, never that they equal 93.795."""
        summary_rtp = m41_summary["rtp"]["point_pct"]
        st1_rtp = _st_row(m41_summary, _ST_BASE)["rtp_contribution_pp"]
        sum_pid_st1 = sum(
            e["rtp_contribution_pp"]
            for e in m41_player_impact["payouts_by_spin_type"]["ST1_paid"]
        )
        sum_pid_top = sum(
            e.get("rtp_contribution_pp", 0.0)
            for e in m41_player_impact.get("payout_ids_top20", [])
        )
        assert summary_rtp == pytest.approx(st1_rtp, abs=1e-6), (
            f"summary.rtp {summary_rtp} != ST1 rtp_contribution_pp {st1_rtp}"
        )
        assert summary_rtp == pytest.approx(sum_pid_st1, abs=1e-6), (
            f"summary.rtp {summary_rtp} != Σ(ST1 per-pid rtp_pp) {sum_pid_st1} "
            "(native payId attribution dropped or double-counted a pid)"
        )
        assert summary_rtp == pytest.approx(sum_pid_top, abs=1e-6), (
            f"summary.rtp {summary_rtp} != Σ(payout_ids_top20 rtp_pp) {sum_pid_top}"
        )

    def test_native_payid_space_present(self, m41_player_impact):
        """The native PayoutIdToWinAmount payId space (the design's pids 3-10)
        materialises as the per-pid attribution — no _unattributed pid, at least
        the bread-and-butter pids present. VALUE-AGNOSTIC: asserts the pid SET is
        real native ids (all int-valued, none synthetic), not their hit counts."""
        entries = m41_player_impact["payouts_by_spin_type"]["ST1_paid"]
        pids = [str(e.get("payout_id")) for e in entries]
        assert len(pids) >= 2, f"expected several native pids; got {pids}"
        assert all(p.isdigit() for p in pids), (
            f"every M41 pid must be a native integer id (no synthetic _unattributed/"
            f"st<N> labels — attribution is the authoritative PayoutIdToWinAmount key); "
            f"got {pids}"
        )


# ---------------------------------------------------------------------------
# 4. STRUCTURE DRIFT — clean: no undeclared ST, no declared-absent ST.
# ---------------------------------------------------------------------------

class TestStructureDrift:
    def test_structure_drift_clean(self, m41_summary):
        sd = m41_summary.get("structure_drift", {})
        assert sd.get("status") == "ok", (
            f"structure_drift.status must be 'ok'; got {sd.get('status')}"
        )
        assert (sd.get("undeclared_sts") or []) == [], (
            f"M41 emits an UNDECLARED SpinType: {sd.get('undeclared_sts')} "
            "(the manifest does not match the data)"
        )
        assert (sd.get("declared_sts_absent") or []) == [], (
            f"M41 declares a SpinType absent from the data: {sd.get('declared_sts_absent')}"
        )


# ---------------------------------------------------------------------------
# 5. FRONTEND CONTRACT KEYS + per-ST dimension fields present (artifact-#5 gate
#    at the JSON layer — gate-7 RENDER is a separate Playwright gate, see Gaps).
# ---------------------------------------------------------------------------

class TestFrontendContract:
    def test_top_level_schema_keys(self, m41_summary):
        for k in ("rtp", "sampling", "player_impact", "rtp_integrity_check"):
            assert k in m41_summary, f"top-level schema key '{k}' absent"

    def test_per_st_breakdown_fields_present(self, m41_player_impact):
        """The per-ST breakdown row carries the frontend-contract fields the
        sibling _stDim* renderers consume (spins / hit-rate / rtp-pp / behavior /
        feature). A missing key would make the console ST1 section render blank."""
        row = m41_player_impact["spin_type_breakdown"][0]
        for k in ("spin_type", "spins", "share_pct", "hit_rate",
                  "rtp_contribution_pp", "behavior_name", "feature_name"):
            assert k in row, f"per-ST contract field '{k}' absent from ST breakdown row"

    def test_per_pid_payout_fields_present(self, m41_player_impact):
        """The per-pid payout table fields (the M4 data-derived paytable + M5 wild
        mechanic surfaced via symbol_combo) the console renders under ST1."""
        entries = m41_player_impact["payouts_by_spin_type"]["ST1_paid"]
        assert entries, "ST1_paid payout list is empty"
        for k in ("payout_id", "hit_count", "hit_rate", "rtp_contribution_pp",
                  "symbol_combo"):
            assert k in entries[0], f"per-pid contract field '{k}' absent"

    def test_multiplier_profile_tail_fields_present(self, m41_player_impact):
        """The volatility/kick panel (M3): the tail metrics the frontend reads.
        VALUE-AGNOSTIC: asserts the KEYS exist, not the tail share value."""
        mp = m41_player_impact.get("multiplier_profile")
        assert isinstance(mp, dict)
        for k in ("buckets", "tail_spin_rate_ge10x", "tail_win_share_ge10x",
                  "tail_rtp_contribution_pp_ge10x"):
            assert k in mp, f"multiplier_profile tail field '{k}' absent"


# ---------------------------------------------------------------------------
# 6. MECHANIC HONESTY — the mechanics M41 does NOT have report applicable=false
#    (the honest "no such mechanic" signal, not a silent gap).
# ---------------------------------------------------------------------------

class TestMechanicHonesty:
    def test_cross_cutting_mechanics_applicable_false(self, m41_player_impact, m41_summary):
        for name in ("collect_mechanic", "bonus_chain_dynamics", "upstream_feature_breakdown"):
            obj = m41_player_impact.get(name) or m41_summary.get(name)
            assert isinstance(obj, dict), f"{name} section missing"
            assert obj.get("applicable") is False, (
                f"{name}.applicable must be False for M41 (no such mechanic); "
                f"got {obj.get('applicable')}"
            )

    def test_machine_mechanics_subflags_false(self, m41_player_impact):
        """No freespin / jackpot / lock / dollar-pick mechanic on M41 — every
        machine_mechanics sub-flag reads applicable=False (the report must not
        claim a feature M41 lacks)."""
        mm = m41_player_impact.get("machine_mechanics") or {}
        for sub in ("free_spin", "jackpot", "lock_lines", "lock_symbols",
                    "lock_reels", "dollar_pick"):
            v = mm.get(sub)
            if isinstance(v, dict):
                assert v.get("applicable") is False, (
                    f"machine_mechanics.{sub}.applicable must be False for M41; got {v}"
                )


# ---------------------------------------------------------------------------
# 7. CROSS-MACHINE NON-LEAK — M41 declares neither a keyed role nor a keyed play
#    nor a dimension block, so derive_analyses(M41) == the M15-class base set and
#    NONE of the feature-keyed analyses (owned by M15/M43/M104/M63/M275/M278/M279)
#    attach. The HOOKS are proven REAL by the converse: the owning machines DO get
#    their analysis (otherwise "M41 lacks it" would be vacuous).
# ---------------------------------------------------------------------------

class TestCrossMachineNonLeak:
    def _derive(self, machine: str):
        from fresh_slotlab.analyzer.machine_spec import derive_analyses, load_manifest
        man = load_manifest(machine, _MANIFESTS_ROOT)
        return set(derive_analyses(man))

    def test_m41_analysis_set_is_exactly_the_base_set(self):
        from fresh_slotlab.analyzer.machine_spec import CROSS_CUTTING, PER_SPINTYPE
        base = set(CROSS_CUTTING) | set(PER_SPINTYPE)
        m41 = self._derive("M41")
        assert m41 == base, (
            f"derive_analyses(M41) must equal the M15-class base set exactly "
            f"(CROSS_CUTTING ∪ PER_SPINTYPE). Extra: {m41 - base}; Missing: {base - m41}"
        )

    def test_m41_attaches_no_feature_keyed_analysis(self):
        m41 = self._derive("M41")
        leaked = _LEAKY_ANALYSES & m41
        assert not leaked, (
            f"M41 leaked a feature-keyed analysis it must NOT have: {sorted(leaked)}. "
            "M41 declares no keyed role/play/dimension; it is the non-leak baseline."
        )

    def test_owning_machines_DO_get_their_analysis(self):
        """The converse — proves the hooks are LIVE, not dead (so 'M41 lacks it' is
        a real non-leak, not a vacuous pass). Skips any owner whose manifest is
        absent in this checkout."""
        owners = {
            "M15": "topdollar_choice",
            "M104": "lock_respin_dynamics",
            "M63": "nudge_dynamics",
        }
        checked = 0
        for machine, analysis in owners.items():
            if not (_MANIFESTS_ROOT / f"{machine}.json").exists():
                continue
            checked += 1
            owner_set = self._derive(machine)
            assert analysis in owner_set, (
                f"{machine} must attach {analysis} (the hook is dead otherwise — "
                f"then 'M41 lacks it' would be vacuous). {machine} set: {sorted(owner_set)}"
            )
        assert checked > 0, "no owning machine manifest present to anchor the hooks"

    def test_m41_report_has_no_firing_feature_section(self, m41_player_impact):
        """End-to-end: the REAL M41 report carries NO feature-keyed analysis
        section that is firing (applicable True). topdollar_choice / respin_dynamics
        / freespin_dynamics / wheel_dynamics / minigame_dynamics / lock_respin_dynamics
        / nudge_dynamics are either absent or applicable=False on M41's live run."""
        for name in _LEAKY_ANALYSES:
            obj = m41_player_impact.get(name)
            if obj is None:
                continue  # not in the analysis set at all — the correct outcome
            if isinstance(obj, dict):
                assert obj.get("applicable") is not True, (
                    f"feature section '{name}' is FIRING (applicable True) on M41's "
                    f"live report — a cross-machine leak. Got {obj}"
                )

    def test_m41_does_not_leak_onto_m15(self):
        """Symmetric guard: M41's pure-base declaration must not perturb M15's
        analysis set (M15 keeps topdollar_choice and gains none of M41's — M41 has
        none to give). Cheap structural cross-check that the two share the base set
        but diverge only on M15's player_choice hook."""
        if not (_MANIFESTS_ROOT / "M15.json").exists():
            pytest.skip("M15 manifest not present")
        m15 = self._derive("M15")
        m41 = self._derive("M41")
        assert "topdollar_choice" in m15
        assert "topdollar_choice" not in m41
        # The ONLY difference is M15's player_choice hook(s); everything else equal.
        assert m41 <= m15, (
            f"M41's base set must be a SUBSET of M15's (M15 = base + topdollar_choice). "
            f"M41-only analyses (a leak): {m41 - m15}"
        )


# ---------------------------------------------------------------------------
# 8. INJECT-BUG PROOF — break each safety claim → RED → (auto-revert) → GREEN.
#
# Every inject touches ONLY M41's OWN manifest (an in-memory / tmp-dir COPY,
# never the real file) or M41's OWN chunk DATA (a tmp-dir copy) — NEVER a shared
# plugin and NEVER a file another machine uses. Each reverts immediately
# (TemporaryDirectory / no mutation of the real tree).
#
# Claim A: native PayoutIdToWinAmount payId attributes 100% → fallback==0. Strip
#          PayoutIdToWinAmount from M41's OWN chunk → ST1 win lands in
#          _unattributed_st1, the L2 gate FAILS, integrity FAILS.
# Claim B: M41 declares no keyed play → no feature analysis attaches. Inject a
#          keyed play (LockSymbolSpin) into M41's OWN ST1 manifest block →
#          lock_respin_dynamics LEAKS into derive_analyses (the non-leak guard
#          would go RED).
# Claim C: M41 declares no dimension block → nudge_dynamics does not attach.
#          Inject a crazy_reel block into M41's OWN ST1 manifest block →
#          nudge_dynamics LEAKS.
# Claim D: the manifest matches the data (structure_drift clean). Declare a phantom
#          ST in M41's OWN manifest → structure_drift.declared_sts_absent populates.
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    @staticmethod
    def _strip_payid_chunk_dir(src_dir: Path, dst_dir: Path) -> None:
        """Copy each M41 chunk into dst_dir with PayoutIdToWinAmount blanked in
        every round (and the _payload_sha256 envelope dropped so the modified
        payload is accepted). M41's OWN data only."""
        for src in src_dir.glob("chunk_*.json"):
            ch = json.loads(src.read_text(encoding="utf-8"))
            for rec in ch.get("response", []):
                rr = rec.get("roundResult")
                if isinstance(rr, str):
                    rounds = json.loads(rr)
                    for rd in rounds:
                        if isinstance(rd, dict) and "PayoutIdToWinAmount" in rd:
                            rd["PayoutIdToWinAmount"] = {}
                    rec["roundResult"] = json.dumps(rounds)
            ch.pop("_payload_sha256", None)
            (dst_dir / src.name).write_text(json.dumps(ch), encoding="utf-8")

    def test_inject_strip_payid_reintroduces_fallback(self):
        """INJECT (Claim A): blank PayoutIdToWinAmount in M41's OWN chunk data →
        ST1 win has no per-pid attribution → it lands in _unattributed_st1; the L2
        gate FAILS; integrity FAILS. Proves the native-payId attribution is
        load-bearing AND the fallback gate is LIVE (not a vacuous pass on the clean
        run). VALUE-AGNOSTIC: the bucket NAME is the signature, never an RTP."""
        if not _has_chunks(_M41_CHUNK_DIR):
            pytest.skip("M41 cached chunks not present")
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as cdir, tempfile.TemporaryDirectory() as odir:
            self._strip_payid_chunk_dir(_M41_CHUNK_DIR, Path(cdir))
            summary = generate_report_from_chunks(
                "M41", 1, chunk_dir=Path(cdir), output_dir=Path(odir), bet=_BET,
            )
            ric = summary.get("rtp_integrity_check", {})
            pids = _payout_ids(summary)
            assert _FALLBACK_ST1 in pids, (
                f"inject-bug: stripping PayoutIdToWinAmount must push ST1 win into "
                f"{_FALLBACK_ST1}; got {pids}"
            )
            assert ric.get("layer2_no_fallback_buckets_ok") is False, (
                "inject-bug: the L2 fallback gate must FAIL when a fallback appears"
            )
            assert _FALLBACK_ST1 in (ric.get("layer2_fallback_buckets_found") or [])
            assert ric.get("passed") is not True, (
                "inject-bug: integrity must FAIL with a live fallback bucket"
            )
        # tmp dirs (chunk copy + output) auto-revert here — the real chunk is untouched.

    def test_inject_keyed_play_leaks_lock_respin(self):
        """INJECT (Claim B): set M41's ST1 play to 'LockSymbolSpin' (a keyed play)
        in an IN-MEMORY copy → lock_respin_dynamics LEAKS into derive_analyses. The
        clean M41 (play=Normal) does NOT — proving the non-leak guard would go RED
        on this exact corruption. M41's OWN manifest only; the in-memory copy is
        discarded, the real file is never touched."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses, load_manifest
        clean = load_manifest("M41", _MANIFESTS_ROOT)
        assert "lock_respin_dynamics" not in set(derive_analyses(clean)), (
            "baseline sanity: clean M41 must NOT attach lock_respin_dynamics"
        )
        injected = copy.deepcopy(clean)
        injected["spin_types"]["1"]["play"] = "LockSymbolSpin"
        leaked = set(derive_analyses(injected))
        assert "lock_respin_dynamics" in leaked, (
            "inject-bug: a keyed play (LockSymbolSpin) on M41's ST1 MUST leak "
            "lock_respin_dynamics into derive_analyses — proving the non-leak "
            "guard (test_m41_attaches_no_feature_keyed_analysis) is not vacuous."
        )
        # `injected` is a throwaway dict; nothing on disk changed — GREEN resumes.

    def test_inject_dimension_block_leaks_nudge(self):
        """INJECT (Claim C): add a 'crazy_reel' dimension block to M41's ST1 in an
        IN-MEMORY copy → nudge_dynamics LEAKS via the DIMENSION_ANALYSES hook. Clean
        M41 has no such block and does NOT attach it. M41's OWN manifest only."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses, load_manifest
        clean = load_manifest("M41", _MANIFESTS_ROOT)
        assert "nudge_dynamics" not in set(derive_analyses(clean))
        injected = copy.deepcopy(clean)
        injected["spin_types"]["1"]["crazy_reel"] = {"dummy": True}
        leaked = set(derive_analyses(injected))
        assert "nudge_dynamics" in leaked, (
            "inject-bug: a crazy_reel dimension block on M41's ST1 MUST leak "
            "nudge_dynamics (DIMENSION_ANALYSES hook) — proving the dimension "
            "non-leak is real."
        )

    def test_inject_phantom_st_trips_structure_drift(self):
        """INJECT (Claim D): declare a phantom ST99 in M41's OWN manifest (tmp-dir
        copy, real file untouched) → structure_drift.declared_sts_absent reports
        ['99']. Proves the structure-drift honesty signal is live on M41."""
        if not _has_chunks(_M41_CHUNK_DIR):
            pytest.skip("M41 cached chunks not present")
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        clean = json.loads(_M41_MANIFEST.read_text(encoding="utf-8"))
        injected = copy.deepcopy(clean)
        injected["spin_types"]["99"] = copy.deepcopy(injected["spin_types"]["1"])
        injected["spin_types"]["99"]["play"] = "PhantomFeature"
        with tempfile.TemporaryDirectory() as mroot_s, tempfile.TemporaryDirectory() as odir:
            mroot = Path(mroot_s)
            (mroot / "M41.json").write_text(json.dumps(injected), encoding="utf-8")
            summary = generate_report_from_chunks(
                "M41", 1, chunk_dir=_M41_CHUNK_DIR, output_dir=Path(odir),
                bet=_BET, manifests_root=mroot,
            )
            sd = summary.get("structure_drift", {})
            assert "99" in (sd.get("declared_sts_absent") or []), (
                f"inject-bug: a phantom declared ST99 must show up in "
                f"declared_sts_absent; got {sd.get('declared_sts_absent')}"
            )
        # tmp manifests root auto-reverts — the real configs/machine_manifests/M41.json
        # is never touched.

    def test_green_resumes_after_revert(self, m41_summary):
        """After every inject-bug reverts (TemporaryDirectory teardown / throwaway
        dicts), the REAL un-patched report is GREEN: integrity passes, no fallback,
        structure clean, no feature leak."""
        ric = m41_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert ric.get("layer2_no_fallback_buckets_ok") is True
        assert _FALLBACK_ST1 not in _payout_ids(m41_summary)
        assert m41_summary["structure_drift"].get("status") == "ok"
        assert (m41_summary["structure_drift"].get("declared_sts_absent") or []) == []
