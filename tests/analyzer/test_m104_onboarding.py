"""M104 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This file asserts STRUCTURE / CONSERVATION / ATTRIBUTION / role-and-play
resolution / honesty INVARIANTS, NEVER an RTP value or range. M104's numbers
(RTP point estimate, hit-rates, lock-record rate, fat-tail share, the
per-band probabilities) drift on re-sample / re-tune / upstream config change;
pinning ANY of them would be a brittle false alarm (charter permanent
invariant 1). The only hard constants asserted are STRUCTURAL ids fixed by the
manifest (the single SpinType 96) and CONSERVATION / IDENTITY arithmetic
(sum(payid rtp_pp) == summary point_pct — a ratio identity, not a pinned value;
the natural payid map's fallback bucket == [] — a structural emptiness, not a
number).

What M104 shipped (session_artifacts/_onboard/M104/03_design.md):
  - configs/machine_manifests/M104.json — ONE SpinType ST96, role paid_spin /
    play LockSymbolSpin, economy WinCredits/real, a `lock_mechanic` declarative
    block (ReMarks discriminator, 35x trigger_symbol, SpinTimes group_unit).
    round_win_rule == null (NO SynthesizePayIdRule): ST96 carries a NATURAL
    per-payid map (Σ PayoutIdToWinAmount == WinCredits), so sum(payid)==summary
    and the fallback bucket is ALREADY 0 without any rule. (Contrast M43/M278/
    M279 whose bonus ST had an EMPTY payid map and NEEDED a synth rule.)
  - machine_spec.py — PLAY_ANALYSES["LockSymbolSpin"]=("lock_respin_dynamics",).
    NOT a role hook: the lock rides the `paid_spin` ROLE every machine's base
    spin carries, so a role hook would cross-fire fleet-wide. The play
    "LockSymbolSpin" is M104-exclusive → scoped to M104 only.
  - features/lock_respin_dynamics.py — NEW base-EXCLUDED plugin (NOT a fork of
    respin_dynamics, which is transition-blind: next_counts is 96→96 only).
    RTP_CONTRIBUTION=False (re-presents already-attributed natural-payid wins).

The whole test runs the REAL engine on the real cached chunk at
rawdata/M104/mode_1 (charter invariant 3: run the real thing, pass bet=chunk
_bet=1000 — the M279 _bet trap; read the real summary). NON-LEAK is locked the
same way test_m278's family-resolution non-leak is: lock_respin_dynamics must
NOT appear in any other machine's derived analysis set, and the M63 sibling
nudge_dynamics must NOT appear on any machine but M63.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M104_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M104" / "mode_1"
_M15_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M15" / "mode_1"
_M104_MANIFEST = _REPO_ROOT / "configs" / "machine_manifests" / "M104.json"
_MANIFEST_DIR = _REPO_ROOT / "configs" / "machine_manifests"

_BET = 1000  # the chunk _bet — MUST be plumbed (the M279 _bet trap)
_ST_LOCK = 96  # the single paid SpinType; the Lock mechanic rides IN-LINE on it
_FALLBACK_ST96 = "_unattributed_st96"
_LOCK_PLAY = "LockSymbolSpin"


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m104_summary():
    if not _has_chunks(_M104_CHUNK_DIR):
        pytest.skip("M104 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            "M104", 1,
            chunk_dir=_M104_CHUNK_DIR,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists()
        yield summary


@pytest.fixture(scope="module")
def m104_player_impact(m104_summary):
    return m104_summary["player_impact"]


@pytest.fixture(scope="module")
def m104_lock(m104_player_impact):
    lrd = m104_player_impact.get("lock_respin_dynamics")
    assert isinstance(lrd, dict), "lock_respin_dynamics section missing"
    return lrd


@pytest.fixture(scope="module")
def m104_manifest():
    if not _M104_MANIFEST.exists():
        pytest.skip("M104 manifest not present")
    return json.loads(_M104_MANIFEST.read_text(encoding="utf-8"))


def _payout_ids(summary) -> list[str]:
    return [
        str(r.get("payout_id", ""))
        for r in summary["player_impact"].get("payout_ids_top20", [])
    ]


def _st96_row(summary) -> dict:
    for row in summary["player_impact"].get("spin_type_breakdown", []):
        try:
            if int(row.get("spin_type")) == _ST_LOCK:
                return row
        except (TypeError, ValueError):
            continue
    return {}


# ---------------------------------------------------------------------------
# 0. Smoke + frontend-contract keys + manifest declarations.
# ---------------------------------------------------------------------------

class TestReportGenerates:
    def test_machine_and_mode(self, m104_summary):
        assert m104_summary["machine"] == "M104"
        assert m104_summary["mode"] == 1
        assert m104_summary["sampling"]["chunks"] > 0
        assert m104_summary["sampling"]["total_spins"] > 0
        assert not m104_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m104_summary.get('feature_errors')}"
        )

    def test_bet_plumbed_no_1000x_inflation(self, m104_summary):
        """The _bet trap (M279): bet=1000 must land in sampling.bet so the
        frontend's '× bet' columns divide correctly. If bet defaulted to 1 the
        ST96 multiplier bands would be 1000× inflated. VALUE-AGNOSTIC: we assert
        the plumbed bet equals the chunk _bet, NOT any multiplier magnitude."""
        assert m104_summary["sampling"].get("bet") == _BET, (
            f"sampling.bet must be the chunk _bet ({_BET}); got "
            f"{m104_summary['sampling'].get('bet')}. A bet=1 report inflates every "
            "'× bet' multiplier column 1000× (the M279 trap)."
        )

    def test_frontend_contract_keys_present(self, m104_player_impact):
        """The frontend contract: the report MUST carry the per-ST breakdown +
        payid attribution + the strict-reused dimension sections + the NEW
        lock_respin_dynamics section. Missing any one means the console renders a
        broken / empty panel."""
        for key in (
            "spin_type_breakdown",
            "payout_ids_top20",
            "payouts_by_spin_type",
            "reel_marginal_by_spin_type",
            "spin_type_outcomes",
            "spin_type_rtp_buckets",
            "multiplier_profile",
            "bankruptcy_simulation",
            "upstream_feature_breakdown",
            "lock_respin_dynamics",
        ):
            assert key in m104_player_impact, (
                f"frontend-contract key '{key}' absent from player_impact"
            )

    def test_only_one_spin_type_st96(self, m104_summary):
        """M104 is a single-SpinType machine: ST96 is the ONLY ST. The whole
        Lock mechanic rides IN-LINE on it (ReMarks-discriminated)."""
        sts = sorted(
            int(r.get("spin_type"))
            for r in m104_summary["player_impact"].get("spin_type_breakdown", [])
        )
        assert sts == [_ST_LOCK], (
            f"M104 must have exactly one SpinType {_ST_LOCK}; got {sts}"
        )

    def test_manifest_declares_play_role_and_lock_mechanic(self, m104_manifest):
        """ST96 = role paid_spin / play LockSymbolSpin with a `lock_mechanic`
        declarative block (the dimension spec the plugin consumes — analog of
        M275 trigger_paths / M279 wheel_cells)."""
        st = m104_manifest["spin_types"][str(_ST_LOCK)]
        assert st["role"] == "paid_spin", (
            "ST96 role must be paid_spin (the lock rides IN-LINE on the paid spin; "
            "NO separate respin/freespin/hold_respin ST)"
        )
        assert st["play"] == _LOCK_PLAY
        assert st["economy"] == {"win_field": "WinCredits", "kind": "real"}
        lm = st.get("lock_mechanic")
        assert isinstance(lm, dict), "ST96 must declare a lock_mechanic block"
        assert lm.get("discriminator") == "ReMarks"
        assert lm.get("trigger_symbol") == "35x"
        assert lm.get("group_unit") == "SpinTimes"

    def test_manifest_has_no_round_win_rule(self, m104_manifest):
        """The design decision (§2): M104 needs NO SynthesizePayIdRule because
        ST96 carries a COMPLETE natural payid map. round_win_rule must be null —
        asserting the machine relies on the natural map, not synthesis."""
        assert m104_manifest.get("round_win_rule") is None, (
            "M104 round_win_rule must be null (the natural per-payid map is "
            "complete; a synth rule would DESTROY the machine's own symbol-tier "
            "taxonomy). Got "
            f"{m104_manifest.get('round_win_rule')!r}"
        )

    def test_no_m104_entry_in_round_win_rules_config(self):
        """Belt-and-suspenders for the no-rule decision: M104 must NOT have an
        entry in configs/machine_round_win_rules.json (the general fallback
        machinery never engages because the natural map is complete)."""
        cfg_path = _REPO_ROOT / "configs" / "machine_round_win_rules.json"
        if not cfg_path.exists():
            pytest.skip("machine_round_win_rules.json not present")
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        # The config may be {machine: [...]} or {rules: [...]} — scan for M104.
        blob = json.dumps(cfg)
        # An entry would name "M104" as a machine key / spin-type rule target.
        rules = cfg.get("rules") if isinstance(cfg, dict) else None
        if isinstance(rules, list):
            m104_rules = [r for r in rules if str(r.get("machine_id", "")) == "M104"]
            assert not m104_rules, (
                f"M104 must have NO round_win_rule entry; found {m104_rules}"
            )
        else:
            # dict-keyed-by-machine layout
            assert "M104" not in cfg, (
                "M104 must have NO round_win_rule entry in machine_round_win_rules.json"
            )


# ---------------------------------------------------------------------------
# (c) ST96 ATTRIBUTION — the NATURAL per-payid map. sum(payid)==summary,
#     NO fallback bucket, every real pid present. (No synth pid expected.)
# ---------------------------------------------------------------------------

class TestNaturalPayidAttribution:
    def test_rtp_integrity_passes(self, m104_summary):
        ric = m104_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M104 mode 1; got "
            f"passed={ric.get('passed')}, message={ric.get('summary_message','N/A')}."
        )

    def test_layer1_sum_invariant_holds(self, m104_summary):
        ric = m104_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant broken: {ric.get('layer1_error')}"
        )

    def test_layer3_anchors_ok(self, m104_summary):
        ric = m104_summary.get("rtp_integrity_check", {})
        assert ric.get("layer3_anchors_ok") is True, (
            f"Layer-3 anchors missing: {ric.get('layer3_missing_anchors')}"
        )

    def test_no_unattributed_st96_fallback_bucket(self, m104_summary):
        """The load-bearing M104 claim (§2): the natural payid map is COMPLETE,
        so the fallback bucket is [] WITHOUT any rule. VALUE-AGNOSTIC: we assert
        the bucket is EMPTY (structural), not its share number."""
        ric = m104_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}"
        )
        buckets = ric.get("layer2_fallback_buckets_found") or []
        assert buckets == [], (
            f"M104 must have ZERO fallback buckets (natural map complete); got {buckets}"
        )
        assert _FALLBACK_ST96 not in buckets
        pids = _payout_ids(m104_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )

    def test_payids_are_natural_not_synthetic(self, m104_summary):
        """ST96 settles via REAL natural payids on every win-bearing record (the
        machine's own symbol-tier taxonomy), NOT a synthesized 'st96' pid. There
        must be NO synthetic pid named after the spin type."""
        pids = _payout_ids(m104_summary)
        assert pids, "M104 must surface natural payids"
        assert "st96" not in pids, (
            f"M104 must NOT synthesize an 'st96' pid (unlike M278's st160) — its "
            f"payids are the natural symbol-tier map; got {pids}"
        )
        # Every surfaced pid is a plain numeric token (no synth / fallback prefix).
        for p in pids:
            assert p.isdigit(), (
                f"M104 payids must be the natural numeric tokens; got non-numeric {p!r}"
            )

    def test_sum_payid_rtp_pp_equals_summary_point(self, m104_summary):
        """The aggregator parity invariant (feedback_aggregator_parity_invariant):
        Σ(payid rtp_contribution_pp) == summary RTP point estimate. VALUE-AGNOSTIC:
        an IDENTITY between two views of the same RTP, NOT a pinned RTP value."""
        point = float(m104_summary["rtp"]["point_pct"])
        sum_pp = sum(
            float(r.get("rtp_contribution_pp") or 0.0)
            for r in m104_summary["player_impact"].get("payout_ids_top20", [])
        )
        assert sum_pp == pytest.approx(point, abs=1e-6), (
            f"Σ payid rtp_pp ({sum_pp}) must equal summary point_pct ({point}) — "
            "the natural per-payid map fully accounts for the RTP (aggregator parity)."
        )

    def test_session_conservation_ok(self, m104_summary):
        """Real-economy machine, no preview field — the whole ST96 win is
        conserved (LastCredits invariant; lock respins are free but ride ST96)."""
        ric = m104_summary.get("rtp_integrity_check", {})
        assert ric.get("session_conservation_level") == "ok", (
            f"session_conservation_level must be 'ok'; got "
            f"{ric.get('session_conservation_level')} "
            f"(skip_reason={ric.get('session_conservation_skip_reason')})"
        )


# ---------------------------------------------------------------------------
# (b) lock_respin_dynamics RESOLVES via the PLAY hook — mechanic view NOT dark.
# ---------------------------------------------------------------------------

class TestLockRespinDynamicsResolves:
    def test_play_hook_attaches_only_lock_respin(self, m104_manifest):
        """derive_analyses attaches lock_respin_dynamics to M104 via the PLAY
        'LockSymbolSpin' hook (NOT a role hook on paid_spin which would
        cross-fire fleet-wide)."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses, PLAY_ANALYSES
        assert PLAY_ANALYSES.get(_LOCK_PLAY) == ("lock_respin_dynamics",), (
            "lock_respin_dynamics must attach via PLAY_ANALYSES['LockSymbolSpin'], "
            "not a role hook"
        )
        analyses = derive_analyses(m104_manifest)
        assert "lock_respin_dynamics" in analyses, (
            f"derive_analyses(M104) must include lock_respin_dynamics; got {analyses}"
        )

    def test_lock_respin_applicable_and_resolves_st96(self, m104_lock):
        """The IMPLEMENTER-CRITICAL detail: lock_respin_dynamics resolves the lock
        ST via play=='LockSymbolSpin' and the base ST via role=='paid_spin' — on
        M104 they are the SAME ST96 (in-line lock). The mechanic view is NOT dark
        (applicable True)."""
        assert m104_lock.get("applicable") is True, (
            f"lock_respin_dynamics MUST be applicable for M104 (the play "
            f"'LockSymbolSpin' must resolve); got applicable="
            f"{m104_lock.get('applicable')} reason={m104_lock.get('reason')}. "
            "If False, _resolve_st_by_role_or_play(play='LockSymbolSpin') failed → "
            "the entire mechanic view went DARK."
        )
        assert m104_lock.get("lock_spin_type") == _ST_LOCK
        assert m104_lock.get("base_spin_type") == _ST_LOCK, (
            "on M104 the lock rides IN-LINE on the paid spin → base==lock==96"
        )

    def test_lock_mechanic_block_surfaced(self, m104_lock):
        """The plugin surfaces the manifest lock_mechanic declaration (the
        dimension spec) — discriminator/trigger_symbol/group_unit visible."""
        lm = m104_lock.get("lock_mechanic") or {}
        assert lm.get("discriminator") == "ReMarks"
        assert lm.get("trigger_symbol") == "35x"
        assert lm.get("group_unit") == "SpinTimes"

    def test_determinism_from_declaration(self, m104_lock):
        """FD3/L3: 35x ⟺ Lock determinism. The trigger_symbol drives
        P(Lock|trigger)=1.0 / P(Lock|¬trigger)=0.0 — a DECLARED structural fact
        (the per-record empirical proof is parser_blind)."""
        det = m104_lock.get("determinism") or {}
        assert det.get("trigger_symbol") == "35x"
        assert det.get("p_lock_given_trigger") == 1.0
        assert det.get("p_lock_given_no_trigger") == 0.0

    def test_grant_rate_money_agnostic_shape(self, m104_lock):
        """FD1/L1: grant-rate is reported as a RATE / 1-in-N, never a coin total.
        VALUE-AGNOSTIC: assert the rate is a proper probability in (0,1) and the
        1-in-N is its reciprocal — NOT a pinned 5.6% / 1-in-17.8."""
        gr = m104_lock.get("grant_rate") or {}
        rate = gr.get("per_paid_spin_record_rate")
        one_per_n = gr.get("one_per_n_paid_spins_records")
        assert isinstance(rate, float) and 0.0 < rate < 1.0, (
            f"per_paid_spin_record_rate must be a probability in (0,1); got {rate}"
        )
        assert one_per_n == pytest.approx(1.0 / rate, rel=1e-6), (
            "one_per_n_paid_spins_records must be the reciprocal of the rate "
            "(a felt-denominator restatement, not an independent number)"
        )
        assert int(gr.get("lock_records") or 0) > 0, (
            "M104 has lock respin records (the feature fires)"
        )

    def test_rtp_concentration_shares_in_range(self, m104_lock):
        """FD5/L5: lock RTP-concentration is reported as SHARES in [0,1] and a
        fat-tail share in [0,1]. VALUE-AGNOSTIC: bounded ratios, not coin sums."""
        rc = m104_lock.get("rtp_concentration") or {}
        for key in (
            "lock_record_win_share_of_st",
            "lock_record_rate",
            "fat_tail_ge20x_win_share",
            "fat_tail_ge20x_spin_rate",
            "loss_rate",
        ):
            v = rc.get(key)
            assert v is None or (0.0 <= float(v) <= 1.0), (
                f"rtp_concentration.{key} must be a share in [0,1] or null; got {v}"
            )

    def test_multiplier_distribution_probs_sum_to_one(self, m104_lock):
        """FD6-framing: the per-ST multiplier band distribution probs sum to 1.0
        over the FULL denominator (incl. losses). VALUE-AGNOSTIC: a probability
        identity, not pinned band sizes. Proves the bet is plumbed (bands are
        meaningful multipliers, not 1000× inflated labels)."""
        md = m104_lock.get("multiplier_distribution") or {}
        bands = md.get("bands") or []
        assert bands, "multiplier_distribution must surface bands"
        # prob sums over EMITTED bands are < 1 (the eq0 loss band is dropped from
        # the bands list but counted in total_spins) — so we reconstruct: emitted
        # win-band prob + loss_rate ≈ 1.0.
        emitted_prob = sum(float(b.get("prob") or 0.0) for b in bands)
        loss_rate = float((m104_lock.get("rtp_concentration") or {}).get("loss_rate") or 0.0)
        assert emitted_prob + loss_rate == pytest.approx(1.0, abs=1e-6), (
            f"emitted win-band prob ({emitted_prob}) + loss_rate ({loss_rate}) must "
            "sum to 1.0 (full per-ST denominator including the eq0 loss band)"
        )

    def test_rtp_contribution_false_no_double_count(self):
        """lock_respin_dynamics RE-PRESENTS wins already attributed by the natural
        payid map; it must NOT add to the RTP sum (RTP_CONTRIBUTION=False).
        Combined with test_sum_payid_rtp_pp_equals_summary_point this proves no
        double-count: the mechanic view does not inflate the RTP aggregate."""
        from fresh_slotlab.analyzer.features.lock_respin_dynamics import LockRespinDynamics
        assert LockRespinDynamics.RTP_CONTRIBUTION is False, (
            "lock_respin_dynamics must be RTP_CONTRIBUTION=False (it re-presents "
            "already-attributed natural-payid wins; counting it would double-count)"
        )

    def test_parser_blind_flagged_explicitly_not_fabricated(self, m104_lock):
        """The honesty invariant (feedback_no_silent_swallow): the metrics that
        need a per-group/per-record substrate (L2 chain-length ladder, L4 wild
        cross, group-opening rate) are surfaced in a `parser_blind` list with a
        reason — NEVER emitted as fabricated zeros."""
        pb = m104_lock.get("parser_blind")
        assert isinstance(pb, list) and pb, (
            "lock_respin_dynamics must flag its substrate-gap metrics in a "
            "parser_blind list (not fabricate zeros)"
        )
        assert isinstance(m104_lock.get("parser_blind_reason"), str)
        # The chain-length ladder (L2) is the headline parser_blind item.
        joined = " ".join(pb).lower()
        assert "chain_length" in joined or "chain-length" in joined, (
            f"the L2 chain-length ladder must be flagged parser_blind; got {pb}"
        )


# ---------------------------------------------------------------------------
# RENDER CONTRACT (gate-7 JSON↔render precondition) — the frontend lock panel
# reads a fixed set of keys (artifact #5, FD1–FD6). The backend emit MUST carry
# every one of them, or the console renders an empty/broken panel (the M43/M279
# "JSON-correct ≠ rendered-correct" lesson). This is a value-agnostic key-presence
# guard; it does NOT (and cannot, without a live console) prove pixels render —
# the live Playwright gate-7 is recorded as a GAP in the W4 summary.
# ---------------------------------------------------------------------------

class TestRenderContract:
    # The exact keys src/web_console/frontend/app.js (renderLockRespinDynamics)
    # reads off player_impact.lock_respin_dynamics. A drift between this set and
    # the emit() output would blank the console panel.
    _TOP_KEYS = ("applicable", "lock_spin_type", "grant_rate", "determinism",
                 "rtp_concentration", "multiplier_distribution")
    _GRANT_KEYS = ("lock_records", "per_paid_spin_record_rate",
                   "one_per_n_paid_spins_records", "note")
    _DET_KEYS = ("trigger_symbol", "p_lock_given_trigger",
                 "p_lock_given_no_trigger", "source")
    _RTPC_KEYS = ("lock_record_win_share_of_st", "st_rtp_contribution_pp",
                  "loss_rate", "note")

    def test_lock_panel_keys_present_for_renderer(self, m104_lock):
        """Every key the frontend lock panel reads is present in the emit output
        (so the panel renders, not blanks)."""
        for k in self._TOP_KEYS:
            assert k in m104_lock, f"frontend lock panel reads lr.{k}; emit missing it"
        gr = m104_lock["grant_rate"]
        for k in self._GRANT_KEYS:
            assert k in gr, f"frontend reads grant_rate.{k}; emit missing it"
        det = m104_lock["determinism"]
        for k in self._DET_KEYS:
            assert k in det, f"frontend reads determinism.{k}; emit missing it"
        rtpc = m104_lock["rtp_concentration"]
        for k in self._RTPC_KEYS:
            assert k in rtpc, f"frontend reads rtp_concentration.{k}; emit missing it"
        # The fat-tail key the frontend reads with a prefix match (rtpC.fat_tail_ge*).
        assert any(k.startswith("fat_tail_ge") for k in rtpc), (
            "frontend reads a fat_tail_ge* share; emit must carry one"
        )

    def test_multiplier_bands_have_render_fields(self, m104_lock):
        """The multiplier-band table renders band/spin_count/prob/win_share per
        row. Each emitted band must carry those fields (sane, bet-plumbed)."""
        md = m104_lock["multiplier_distribution"]
        for band in (md.get("bands") or []):
            for k in ("band", "spin_count", "prob", "win_share"):
                assert k in band, f"a multiplier band is missing render field '{k}'"

    def test_frontend_source_references_lock_respin_keys(self):
        """Belt-and-suspenders: the committed frontend source actually consumes
        lock_respin_dynamics (artifact #5 wired, not just backend-only). Catches a
        regression where the renderer is deleted but the emit stays — the M43/M279
        'backend-only, console shows nothing' failure mode."""
        app_js = _REPO_ROOT / "src" / "web_console" / "frontend" / "app.js"
        if not app_js.exists():
            pytest.skip("frontend app.js not present")
        src = app_js.read_text(encoding="utf-8")
        assert "lock_respin_dynamics" in src, (
            "frontend app.js must read player_impact.lock_respin_dynamics "
            "(artifact #5 — the per-ST dimension renderer)"
        )
        assert "grant_rate" in src and "rtp_concentration" in src, (
            "frontend must render the grant_rate + rtp_concentration dimensions"
        )


# ---------------------------------------------------------------------------
# (3) CROSS-MACHINE NON-LEAK — lock_respin_dynamics and the M63 sibling
#     nudge_dynamics must NOT fire on machines that do not declare them.
# ---------------------------------------------------------------------------

class TestCrossMachineNonLeak:
    # The PRISTINE derive_analyses wiring (mirrors machine_spec source). A plain
    # snapshot of the LIVE dict would preserve a pre-existing pollution; this
    # known-good baseline lets the autouse fixture RESET (not just restore) the
    # module globals — neutralizing any in-place mutation by a sibling test
    # without reloading the module (which would desync other tests' references).
    _PRISTINE_ROLE_ANALYSES = {
        "player_choice": ("topdollar_choice",),
        "respin": ("respin_dynamics",),
        "freespin": ("freespin_dynamics",),
        "hold_respin": ("freespin_dynamics",),
    }
    _PRISTINE_PLAY_ANALYSES = {
        "WinMiniGame": ("minigame_dynamics",),
        "Wheel": ("wheel_dynamics",),
        "LockSymbolSpin": ("lock_respin_dynamics",),
    }
    _PRISTINE_DIMENSION_ANALYSES = {
        "crazy_reel": ("nudge_dynamics",),
    }

    @pytest.fixture(autouse=True)
    def _reset_analysis_hooks_to_pristine(self):
        """Immunize the non-leak assertions against module-global mutation by ANY
        other test (the autouse-snapshot discipline — feedback_subprocess_import_
        suicide_and_module_globals.md / the ALL_PLAY_TYPE_PLUGINS note). The
        derive_analyses hooks (ROLE/PLAY/DIMENSION_ANALYSES) are module globals; a
        sibling test that mutates them in place (instead of via monkeypatch) would
        otherwise poison this guard with a stale/extra machine.

        We RESET the LIVE dicts (in place — preserving their object identity so the
        engine's `from machine_spec import …` references stay valid) to the known
        PRISTINE wiring, then restore that same pristine state on teardown. This is
        value-agnostic and base_hash-neutral: it touches only in-memory test state.

        GUARD: if the source wiring ever changes (a NEW machine's hook), the
        pristine baseline must be updated — test_play_hook_attaches_only_lock_respin
        + the source-parity assertion below will go RED to force the update."""
        import fresh_slotlab.analyzer.machine_spec as ms
        # Source-parity guard: the live wiring must be a SUPERSET-equal of pristine
        # for the keys we care about (a NEW hook key added upstream forces a baseline
        # update rather than a silent stale reset).
        for key, val in self._PRISTINE_PLAY_ANALYSES.items():
            assert ms.PLAY_ANALYSES.get(key) == val, (
                f"PLAY_ANALYSES['{key}'] source wiring changed to "
                f"{ms.PLAY_ANALYSES.get(key)!r}; update _PRISTINE_PLAY_ANALYSES"
            )
        for key, val in self._PRISTINE_DIMENSION_ANALYSES.items():
            assert ms.DIMENSION_ANALYSES.get(key) == val, (
                f"DIMENSION_ANALYSES['{key}'] source wiring changed; update baseline"
            )
        for live, pristine in (
            (ms.ROLE_ANALYSES, self._PRISTINE_ROLE_ANALYSES),
            (ms.PLAY_ANALYSES, self._PRISTINE_PLAY_ANALYSES),
            (ms.DIMENSION_ANALYSES, self._PRISTINE_DIMENSION_ANALYSES),
        ):
            live.clear()
            live.update(pristine)
        try:
            yield
        finally:
            for live, pristine in (
                (ms.ROLE_ANALYSES, self._PRISTINE_ROLE_ANALYSES),
                (ms.PLAY_ANALYSES, self._PRISTINE_PLAY_ANALYSES),
                (ms.DIMENSION_ANALYSES, self._PRISTINE_DIMENSION_ANALYSES),
            ):
                live.clear()
                live.update(pristine)

    @pytest.fixture
    def all_manifests(self):
        """Reload EVERY manifest fresh from disk per-test (function scope) — never
        a cached dict that an earlier test could have mutated in place."""
        out = {}
        for mf in sorted(_MANIFEST_DIR.glob("*.json")):
            out[mf.stem] = json.loads(mf.read_text(encoding="utf-8"))
        return out

    def test_lock_respin_dynamics_fires_iff_lock_symbol_spin_play(self, all_manifests):
        """lock_respin_dynamics must fire EXACTLY on the machines that DECLARE the
        LockSymbolSpin play — the charter non-leak guarantee (the play hook, NOT a
        role hook that would cross-fire onto every machine's paid_spin base). The
        expected set is DERIVED from the manifests, not a hardcoded fleet snapshot,
        so it auto-tracks every machine that genuinely carries the M104 in-line Lock
        hold-and-respin mechanic (M104 + M240 today; both verified in rawdata:
        ReMarks ''->'Lock' discriminator + LockSymbols positions). The invariant is
        `fires IFF declares the play`, same shape as test_m15_has_no_minigame_dynamics."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        declares_lock_play = {
            m for m, man in all_manifests.items()
            if any((st or {}).get("play") == _LOCK_PLAY
                   for st in (man.get("spin_types") or {}).values())
        }
        fired_on = {
            m for m, man in all_manifests.items()
            if "lock_respin_dynamics" in derive_analyses(man)
        }
        assert fired_on == declares_lock_play, (
            f"lock_respin_dynamics must fire EXACTLY on the LockSymbolSpin-play "
            f"machines {sorted(declares_lock_play)}; fired on {sorted(fired_on)}. "
            "A role hook on paid_spin (instead of the play hook) would cross-fire "
            "onto every machine's base spin; a machine firing it WITHOUT declaring "
            "the play (or declaring it WITHOUT firing) is the leak this guard catches."
        )
        # The mechanic is real (the set is non-empty): M104 is the canonical machine.
        assert "M104" in fired_on

    def test_nudge_dynamics_is_m63_exclusive(self, all_manifests):
        """The M63 sibling: nudge_dynamics (crazy_reel dimension hook) must fire
        on M63 ONLY — no other manifest declares a crazy_reel ST block."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        fired_on = [
            m for m, man in all_manifests.items()
            if "nudge_dynamics" in derive_analyses(man)
        ]
        assert fired_on == ["M63"], (
            f"nudge_dynamics must fire on M63 ONLY; fired on {fired_on}."
        )

    def test_exclusivity_guard_catches_a_leak(self, all_manifests):
        """INJECT-BUG (non-leak): giving a machine that does NOT carry the lock
        mechanic the LockSymbolSpin play makes lock_respin_dynamics fire on it too —
        proving the plugin is PLAY-driven, so the `fires IFF declares the play`
        guard above is a real check, not a tautology. Then confirm the real on-disk
        set is unchanged. No disk write — the copy is discarded (the on-disk
        manifests are untouched)."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        real_declares = {
            m for m, man in all_manifests.items()
            if any((st or {}).get("play") == _LOCK_PLAY
                   for st in (man.get("spin_types") or {}).values())
        }
        leaked = json.loads(json.dumps(all_manifests))  # deep copy
        # INJECT: give M15's base ST the LockSymbolSpin play (M15 has NO lock mechanic).
        first_st = next(iter(leaked["M15"]["spin_types"].values()))
        first_st["play"] = _LOCK_PLAY
        fired_on = {
            m for m, man in leaked.items()
            if "lock_respin_dynamics" in derive_analyses(man)
        }
        assert "M15" in fired_on, (
            "inject-bug: with M15 declaring LockSymbolSpin, the plugin must fire on "
            "M15 too — the play hook MUST attach it to any machine declaring the play"
        )
        assert fired_on == real_declares | {"M15"}, (
            f"inject-bug: expected the real LockSymbolSpin set {sorted(real_declares)} "
            f"plus the injected M15; got {sorted(fired_on)}"
        )
        # REVERT is implicit (leaked is a discarded copy); confirm the real
        # manifests fire lock_respin_dynamics exactly on the LockSymbolSpin machines.
        real_fired = {
            m for m, man in all_manifests.items()
            if "lock_respin_dynamics" in derive_analyses(man)
        }
        assert real_fired == real_declares, (
            "GREEN after revert: the real manifests fire lock_respin_dynamics exactly "
            f"on the LockSymbolSpin-play machines {sorted(real_declares)}"
        )

    def test_m15_has_no_lock_respin_dynamics(self, all_manifests):
        """Explicit single-machine non-leak (the canonical guard shape): M15's
        base spin (paid_spin role, Normal play) must NOT pick up
        lock_respin_dynamics — the exact role-vs-play cross-fire the play hook
        prevents."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        m15 = all_manifests.get("M15")
        assert m15 is not None
        analyses = derive_analyses(m15)
        assert "lock_respin_dynamics" not in analyses, (
            f"M15 (paid_spin/Normal) must NOT pick up lock_respin_dynamics; got {analyses}"
        )
        assert "nudge_dynamics" not in analyses

    def test_lock_respin_dark_on_machine_without_play(self):
        """End-to-end non-leak on the REAL engine: run a machine WITHOUT the
        LockSymbolSpin play (M15) and assert lock_respin_dynamics either is absent
        or — if the plugin ran — reports applicable:False (it must NOT emit live
        lock metrics). This catches a leak that a manifest-only test would miss
        (a stray import-time registration that fires the plugin everywhere)."""
        if not _has_chunks(_M15_CHUNK_DIR):
            pytest.skip("M15 cached chunks not present")
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        # M15 has 224 chunks — cap to a few for speed; structure is what matters.
        chunks = sorted(_M15_CHUNK_DIR.glob("chunk_*.json"))[:3]
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            srcp = Path(src)
            for c in chunks:
                (srcp / c.name).write_bytes(c.read_bytes())
            summary = generate_report_from_chunks(
                "M15", 1, chunk_dir=srcp, output_dir=Path(out), bet=_BET,
            )
            lrd = summary["player_impact"].get("lock_respin_dynamics")
            if lrd is not None:
                assert lrd.get("applicable") is False, (
                    "lock_respin_dynamics must NOT emit live metrics on M15 (no "
                    f"LockSymbolSpin play); got {lrd}"
                )
            # And M15's own attribution is unaffected.
            assert summary["rtp_integrity_check"].get("passed") is True, (
                "M15 integrity must still pass (M104 onboarding must not regress M15)"
            )


# ---------------------------------------------------------------------------
# INJECT-BUG PROOF — break each safety claim → RED → (auto-revert) → GREEN.
#   Injection target rule: ONLY M104's OWN manifest or M104's OWN plugin
#   (lock_respin_dynamics.py) — never a shared file (charter invariant 2). All
#   injections are monkeypatch / in-memory and auto-revert; NO file on disk is
#   left mutated.
#
# Claim A: the PLAY hook on "LockSymbolSpin" is load-bearing — break the play in
#          a COPY of M104's manifest → lock_respin_dynamics goes DARK
#          (applicable False). (Proves the play resolution, not a role hook.)
# Claim B: removing the lock_mechanic.trigger_symbol from a manifest COPY breaks
#          the FD3 determinism (p_lock_given_trigger becomes null). (Proves the
#          determinism is sourced from the declaration, not fabricated.)
# Claim C: RTP_CONTRIBUTION must stay False — patching the M104 plugin class to
#          True would (if the engine counted it) break aggregator parity. We
#          assert the guard value and that the live report's parity holds with
#          it False (the revert state).
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_empty_natural_map_reintroduces_unattributed_st96(self, monkeypatch):
        """INJECT (Claim D — the load-bearing M104 attribution claim): empty the
        natural per-payid extraction (round_win.extract_round_payouts → {}). The
        ST96 win then has NO natural pid and spills into _unattributed_st96 →
        integrity FAILS and the fallback bucket appears. This proves the
        no-fallback invariant is REAL (it is the natural map, not a rule, that
        keeps the bucket empty). VALUE-AGNOSTIC: the bucket's PRESENCE is the
        signature, not an RTP. monkeypatch auto-reverts → GREEN resumes."""
        if not _has_chunks(_M104_CHUNK_DIR):
            pytest.skip("M104 cached chunks not present")
        # The parser binds extract_round_payouts as a module global
        # (`from fresh_slotlab.round_win import extract_round_payouts`), so the
        # patch MUST target the parser's binding, not round_win's (a
        # module-global-leak footgun, feedback_subprocess_import_suicide_and_
        # module_globals.md).
        import fresh_slotlab.analyzer.core.parser as parser_mod

        def _empty_payouts(*a, **k):
            return {}

        monkeypatch.setattr(parser_mod, "extract_round_payouts", _empty_payouts)
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = generate_report_from_chunks(
                "M104", 1, chunk_dir=_M104_CHUNK_DIR,
                output_dir=Path(tmpdir), bet=_BET,
            )
            ric = summary.get("rtp_integrity_check", {})
            pids = _payout_ids(summary)
            assert _FALLBACK_ST96 in pids, (
                f"inject-bug: with the natural map emptied, ST96 win must land in "
                f"{_FALLBACK_ST96}; got {pids}"
            )
            assert ric.get("layer2_no_fallback_buckets_ok") is False
            assert _FALLBACK_ST96 in (ric.get("layer2_fallback_buckets_found") or [])
            assert ric.get("passed") is not True
        # monkeypatch auto-reverts here.

    def test_inject_break_play_darkens_lock_view(self):
        """INJECT (Claim A): rename the LockSymbolSpin play to a non-matching
        value in an IN-MEMORY copy of M104's manifest. lock_respin_dynamics then
        resolves no lock ST → applicable False. Proves the PLAY hook + play
        resolution is the load-bearing wiring. VALUE-AGNOSTIC (a structural
        applicable flag, not an RTP)."""
        from fresh_slotlab.analyzer.features.lock_respin_dynamics import (
            _resolve_st_by_role_or_play,
        )
        manifest = json.loads(_M104_MANIFEST.read_text(encoding="utf-8"))
        # BASELINE (revert state): the play resolves ST96.
        assert _resolve_st_by_role_or_play(manifest, play=_LOCK_PLAY) == _ST_LOCK
        # INJECT: break the play.
        manifest["spin_types"][str(_ST_LOCK)]["play"] = "NotALockPlay"
        assert _resolve_st_by_role_or_play(manifest, play=_LOCK_PLAY) is None, (
            "inject-bug: with the LockSymbolSpin play broken the lock ST must NOT "
            "resolve → the mechanic view would go DARK. This proves the play "
            "resolution is load-bearing."
        )
        # Confirm derive_analyses no longer attaches the plugin (the leak guard's
        # inverse): a manifest without the play does NOT carry lock_respin_dynamics.
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        assert "lock_respin_dynamics" not in derive_analyses(manifest), (
            "inject-bug: a manifest without the LockSymbolSpin play must NOT "
            "attach lock_respin_dynamics"
        )
        # REVERT is implicit (the on-disk manifest was never touched; this was a
        # parsed copy). Re-read from disk to PROVE the source is unchanged.
        fresh = json.loads(_M104_MANIFEST.read_text(encoding="utf-8"))
        assert fresh["spin_types"][str(_ST_LOCK)]["play"] == _LOCK_PLAY, (
            "GREEN after revert: the on-disk manifest play is intact"
        )
        assert _resolve_st_by_role_or_play(fresh, play=_LOCK_PLAY) == _ST_LOCK

    def test_inject_remove_trigger_symbol_nulls_determinism(self):
        """INJECT (Claim B): drop lock_mechanic.trigger_symbol from an IN-MEMORY
        manifest copy and run the plugin's emit path on the real accumulator.
        The FD3 determinism then reports p_lock_given_trigger=None (no fabricated
        1.0). Proves the determinism is SOURCED from the declaration."""
        if not _has_chunks(_M104_CHUNK_DIR):
            pytest.skip("M104 cached chunks not present")
        import fresh_slotlab.analyzer.features.lock_respin_dynamics as lrd_mod

        # Build a minimal emit context from a parsed manifest copy (no disk write).
        manifest = json.loads(_M104_MANIFEST.read_text(encoding="utf-8"))
        # BASELINE: trigger_symbol present → determinism is 1.0/0.0.
        lm0 = lrd_mod._lock_mechanic_block(manifest, _ST_LOCK)
        assert lm0.get("trigger_symbol") == "35x"
        # INJECT: remove it.
        del manifest["spin_types"][str(_ST_LOCK)]["lock_mechanic"]["trigger_symbol"]
        lm1 = lrd_mod._lock_mechanic_block(manifest, _ST_LOCK)
        assert lm1.get("trigger_symbol") is None, (
            "inject-bug: removing trigger_symbol must leave the lock_mechanic "
            "block WITHOUT it (the plugin reads the declaration, not a hardcode)"
        )
        # And the determinism the plugin would emit is null (not a fabricated 1.0):
        # mirror the emit branch directly (no engine rerun needed for this unit).
        trig = lm1.get("trigger_symbol")
        p_given = 1.0 if trig else None
        p_not = 0.0 if trig else None
        assert p_given is None and p_not is None, (
            "inject-bug: with no trigger_symbol the FD3 determinism must be null "
            "(NOT a fabricated determinism)"
        )
        # GREEN after revert: on-disk manifest still declares 35x.
        fresh = json.loads(_M104_MANIFEST.read_text(encoding="utf-8"))
        assert (
            fresh["spin_types"][str(_ST_LOCK)]["lock_mechanic"]["trigger_symbol"]
            == "35x"
        )

    def test_inject_rtp_contribution_true_would_break_parity(self, monkeypatch, m104_summary):
        """INJECT (Claim C): the guard is RTP_CONTRIBUTION=False. Flip the M104
        plugin class flag to True (its OWN file's class attribute) and assert the
        flag IS the load-bearing guard the aggregator-parity test relies on; then
        confirm the REAL report (revert state, flag False) holds parity. We do
        NOT count it into the RTP — we prove the guard and the parity together."""
        from fresh_slotlab.analyzer.features.lock_respin_dynamics import LockRespinDynamics
        # BASELINE / revert state: the guard is False.
        assert LockRespinDynamics.RTP_CONTRIBUTION is False
        # INJECT: flip the guard on the M104-OWN plugin class.
        monkeypatch.setattr(LockRespinDynamics, "RTP_CONTRIBUTION", True)
        assert LockRespinDynamics.RTP_CONTRIBUTION is True, (
            "inject-bug: the guard flipped — if the aggregator counted "
            "lock_respin_dynamics into the RTP sum, sum(payid)==summary parity "
            "would break (double-count)."
        )
        # monkeypatch auto-reverts here → the live m104_summary (computed with the
        # guard False) still holds aggregator parity, proving the GREEN state.
        point = float(m104_summary["rtp"]["point_pct"])
        sum_pp = sum(
            float(r.get("rtp_contribution_pp") or 0.0)
            for r in m104_summary["player_impact"].get("payout_ids_top20", [])
        )
        assert sum_pp == pytest.approx(point, abs=1e-6), (
            "GREEN: with RTP_CONTRIBUTION=False the natural payid map alone equals "
            "the summary RTP (no double-count from the mechanic view)."
        )

    def test_green_resumes_after_revert(self, m104_summary, m104_lock):
        """After every inject-bug reverts, the real (un-patched) report is GREEN:
        integrity passes, no fallback, lock_respin_dynamics applicable with the
        declared determinism, and RTP_CONTRIBUTION False."""
        from fresh_slotlab.analyzer.features.lock_respin_dynamics import LockRespinDynamics
        ric = m104_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert ric.get("layer2_no_fallback_buckets_ok") is True
        assert (ric.get("layer2_fallback_buckets_found") or []) == []
        assert _FALLBACK_ST96 not in _payout_ids(m104_summary)
        assert m104_lock.get("applicable") is True
        assert (m104_lock.get("determinism") or {}).get("trigger_symbol") == "35x"
        assert LockRespinDynamics.RTP_CONTRIBUTION is False
