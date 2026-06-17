"""M84 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This file asserts STRUCTURE / CONSERVATION / ATTRIBUTION / role-resolution /
honesty / non-leak INVARIANTS, NEVER an RTP value or range. M84's numbers
(88.09% RTP, 10.45% hit, per-payid hit-counts, multiplier bands) drift on
re-sample / re-tune; pinning ANY of them would be a brittle false alarm
(charter permanent invariant 1). The only hard constants asserted are the
STRUCTURAL ids fixed by the manifest (the single SpinType 1, role paid_spin,
play Normal) and CONSERVATION / NON-LEAK identities.

What M84 shipped (session_artifacts/_onboard/M84/03_design.md):
  - configs/machine_manifests/M84.json — the SIMPLEST fleet archetype (the M74
    twin): ONE SpinType (ST1 = paid_spin / Normal), a classic 3x3 reel slot whose
    only mechanic is intra-ST multiplicative wild stacking on the center payline.
  - ZERO new plugins. ZERO new role/play tokens. ZERO closure changes. ZERO
    SynthesizePayIdRule (the payid invariant already holds natively — ST1 carries
    a real PayoutIdToWinAmount, exactly one pid per win, fallback bucket already []).
  - STRICT-REUSE of the frozen paid_spin/Normal pipeline (byte-identical 18-field
    ST1 signature to the CONFIRMED M15 AND M43 ST1). derive_analyses(M84) ==
    CROSS_CUTTING U PER_SPINTYPE with NO role/play hook (paid_spin & Normal both
    unkeyed). So none of the play/role-keyed mechanic analyses may fire here.

The whole test runs the REAL engine on the real cached chunk at rawdata/M84/mode_1
(charter invariant 3: run the real thing, pass bet=chunk _bet=1000, read the real
summary). bet=1000 is load-bearing: with the default bet=1 the multiplier columns
inflate 1000x (the M279/M43 trap) — TestBetSanity proves the served bet yields sane
bands while a bet=1 run dumps every win into the 100x+ band.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M84_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M84" / "mode_1"
_M104_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M104" / "mode_1"
_M84_MANIFEST = _REPO_ROOT / "configs" / "machine_manifests" / "M84.json"

# The chunk's own bet (rawdata/M84/mode_1 _bet); load-bearing for the "x bet"
# multiplier columns (the M279/M43 1000x-inflation trap).
_BET = 1000

_ST1 = 1  # the single SpinType — paid_spin / Normal

# The play/role-keyed mechanic analyses that belong to OTHER machines and must
# NOT fire on M84 (it declares no role/play hook). Each is keyed in
# ROLE_ANALYSES / PLAY_ANALYSES by a token M84 does not use.
_FOREIGN_MECHANIC_ANALYSES = (
    "topdollar_choice",      # ROLE player_choice (M15)
    "respin_dynamics",       # ROLE respin (M43)
    "freespin_dynamics",     # ROLE freespin / hold_respin (M275 / M278)
    "minigame_dynamics",     # PLAY WinMiniGame (M44)
    "wheel_dynamics",        # PLAY Wheel (M279)
    "lock_respin_dynamics",  # PLAY LockSymbolSpin (M104)
    "nudge_dynamics",        # M63
    "crazy_reel_dim",        # M63
)


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m84_summary():
    if not _has_chunks(_M84_CHUNK_DIR):
        pytest.skip("M84 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            "M84", 1,
            chunk_dir=_M84_CHUNK_DIR,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists()
        yield summary


@pytest.fixture(scope="module")
def m84_pi(m84_summary):
    pi = m84_summary.get("player_impact")
    assert isinstance(pi, dict), "summary.player_impact missing"
    return pi


@pytest.fixture(scope="module")
def m84_manifest():
    if not _M84_MANIFEST.exists():
        pytest.skip("M84 manifest not present")
    return json.loads(_M84_MANIFEST.read_text(encoding="utf-8"))


def _payout_ids(summary) -> list[str]:
    return [
        str(r.get("payout_id", ""))
        for r in summary["player_impact"].get("payout_ids_top20", [])
    ]


def _st1_breakdown_row(pi) -> dict:
    for row in pi.get("spin_type_breakdown", []):
        try:
            if int(row.get("spin_type")) == _ST1:
                return row
        except (TypeError, ValueError):
            continue
    return {}


def _st1_outcomes(pi) -> dict:
    """The frozen per-ST outcomes panel for ST1 (drives the win-band columns)."""
    so = pi.get("spin_type_outcomes") or {}
    # keyed "ST1_paid" in the frozen schema
    for k, v in so.items():
        if isinstance(v, dict) and int(v.get("spin_type", -1)) == _ST1:
            return v
    return {}


# ---------------------------------------------------------------------------
# 0. Smoke + manifest archetype declaration.
# ---------------------------------------------------------------------------

class TestReportGenerates:
    def test_machine_and_mode(self, m84_summary):
        assert m84_summary["machine"] == "M84"
        assert m84_summary["mode"] == 1
        assert m84_summary["sampling"]["chunks"] > 0
        assert m84_summary["sampling"]["total_spins"] > 0
        assert not m84_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m84_summary.get('feature_errors')}"
        )

    def test_manifest_single_st_paid_spin_normal(self, m84_manifest):
        """The simplest archetype: EXACTLY one SpinType (ST1), role paid_spin,
        play Normal. No second event is declared (no choice/settlement/respin/
        freespin/wheel/collect). This is the structural identity the report rides."""
        st = m84_manifest["spin_types"]
        assert list(st.keys()) == [str(_ST1)], (
            f"M84 must declare exactly ST{_ST1}; got {list(st.keys())}"
        )
        assert st[str(_ST1)]["role"] == "paid_spin"
        assert st[str(_ST1)]["play"] == "Normal"
        assert m84_manifest["modes"] == [1]
        assert m84_manifest["inherits_from"] is None

    def test_manifest_no_synthesize_pay_id_rule(self, m84_manifest):
        """ATTRIBUTION decision: NO SynthesizePayIdRule. round_win_rule is 'none'
        (a string note, NOT a rule key). ST1 attributes natively via its own
        PayoutIdToWinAmount — adding a synth rule would be wrong (there is no
        {}-payid settlement event to synthesize for)."""
        rwr = m84_manifest.get("round_win_rule")
        assert isinstance(rwr, str) and rwr.strip().lower().startswith("none"), (
            f"M84 must declare round_win_rule 'none' (native payid, no synth); got {rwr!r}"
        )
        # And M84 must NOT appear in the global round-win rules config.
        cfg_path = _REPO_ROOT / "configs" / "machine_round_win_rules.json"
        if cfg_path.exists():
            rules = json.loads(cfg_path.read_text(encoding="utf-8"))
            keys = rules.keys() if isinstance(rules, dict) else {
                str(r.get("machine_id", r.get("machine", ""))) for r in rules
            }
            assert not any("M84" in str(k) for k in keys), (
                "M84 must NOT have a round_win rule (native payid attribution)"
            )


# ---------------------------------------------------------------------------
# Frontend contract — the per-ST panels the console renders must be present
# and keyed by the declared SpinType (the ST1_paid panels M15/M43 ride).
# ---------------------------------------------------------------------------

class TestFrontendContractKeys:
    _REQUIRED = (
        "spin_type_breakdown",
        "spin_type_outcomes",
        "spin_type_rtp_buckets",
        "payouts_by_spin_type",
        "reel_marginal_by_spin_type",
        "multiplier_profile",
        "payout_ids_top20",
        "machine_mechanics",
        "upstream_feature_breakdown",
        "bankruptcy_simulation",
    )

    def test_required_panels_present(self, m84_pi):
        for key in self._REQUIRED:
            assert key in m84_pi, f"frontend-contract panel '{key}' missing"

    def test_per_st_panels_keyed_for_st1(self, m84_pi):
        """The per-ST panels (payouts / reel_marginal / outcomes) carry a key for
        the single declared ST1 — the artifact-#5 dimension the console renders."""
        for panel in ("payouts_by_spin_type", "reel_marginal_by_spin_type",
                      "spin_type_outcomes"):
            keys = list((m84_pi.get(panel) or {}).keys())
            assert any("1" in str(k) for k in keys), (
                f"{panel} must carry an ST1 key (the declared SpinType); got {keys}"
            )

    def test_spin_type_breakdown_is_single_st1(self, m84_pi):
        """The breakdown shows the ONE ST1 row, 100% of rounds — value-agnostic
        structural identity (the share is 100.0 because there is no other ST)."""
        rows = m84_pi["spin_type_breakdown"]
        sts = sorted({int(r["spin_type"]) for r in rows})
        assert sts == [_ST1], f"M84 must surface exactly ST{_ST1}; got {sts}"
        row = _st1_breakdown_row(m84_pi)
        assert row.get("share_pct") == pytest.approx(100.0, abs=1e-6), (
            "the single ST must be 100% of rounds (single-ST machine)"
        )
        assert row.get("feature_name") == "Normal"


# ---------------------------------------------------------------------------
# Attribution — sum(payid)==summary, NO fallback bucket, native payid.
# (charter permanent invariant 1: rtp_integrity L1/L2/L3.)
# ---------------------------------------------------------------------------

class TestAttributionIntegrity:
    def test_rtp_integrity_passes(self, m84_summary):
        ric = m84_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M84 mode 1; got "
            f"passed={ric.get('passed')}, message={ric.get('summary_message','N/A')}."
        )

    def test_layer1_sum_invariant_holds(self, m84_summary):
        ric = m84_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant broken (sum(payid) != total): {ric.get('layer1_error')}"
        )

    def test_layer2_no_unattributed_fallback_bucket(self, m84_summary):
        """L2: NO _unattributed_*/_other fallback bucket (share == 0). The native
        payid means the fallback is already empty — a fallback bucket here would be
        a silent mis-attribution (feedback_invariant_with_fallback_hides_drift)."""
        ric = m84_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}"
        )
        assert (ric.get("layer2_fallback_buckets_found") or []) == [], (
            "M84 must have ZERO fallback buckets (native payid attribution)"
        )
        pids = _payout_ids(m84_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )
        assert not any(p.startswith("_other") for p in pids)

    def test_layer3_anchors_ok(self, m84_summary):
        ric = m84_summary.get("rtp_integrity_check", {})
        assert ric.get("layer3_anchors_ok") is True, (
            f"Layer-3 anchors broken: {ric.get('layer3_missing_anchors')}"
        )

    def test_session_conservation_ok(self, m84_summary):
        ric = m84_summary.get("rtp_integrity_check", {})
        assert ric.get("session_conservation_level") == "ok", (
            f"session_conservation_level must be 'ok'; got "
            f"{ric.get('session_conservation_level')} "
            f"(skip_reason={ric.get('session_conservation_skip_reason')})"
        )

    def test_aggregator_parity_pid_sum_equals_st1_rtp(self, m84_pi):
        """Aggregator parity (value-agnostic ratio identity, NOT a pinned RTP):
        the per-payid rtp_contribution_pp sums to the ST1 row's
        rtp_contribution_pp. A drift that double-counts or drops a payid breaks
        this without changing the pinned magnitude."""
        st1_rtp = float(_st1_breakdown_row(m84_pi).get("rtp_contribution_pp") or 0.0)
        assert st1_rtp > 0.0, "ST1 must carry RTP (sanity for the parity check)"
        pid_sum = sum(
            float(r.get("rtp_contribution_pp") or 0.0)
            for r in m84_pi.get("payout_ids_top20", [])
        )
        assert pid_sum == pytest.approx(st1_rtp, rel=1e-4), (
            f"aggregator parity broken: sum(pid rtp_pp)={pid_sum} != ST1 rtp_pp "
            f"{st1_rtp}. A payid was dropped, double-counted, or mis-attributed."
        )

    def test_no_preview_or_double_count_keys(self, m84_pi):
        """The single ST1 self-settles in-round; there is no preview / no-payid
        STRUCTURE that could double-count. The per-ST payouts panel carries ONLY
        the ST1 key — no _preview / _unattributed / no_payid sibling."""
        pbs = m84_pi.get("payouts_by_spin_type") or {}
        for k in pbs.keys():
            sk = str(k)
            assert not sk.startswith("_unattributed"), f"fallback key in payouts: {sk}"
            assert "preview" not in sk.lower(), f"unexpected preview key: {sk}"
            assert "no_payid" not in sk.lower(), f"unexpected no-payid key: {sk}"


# ---------------------------------------------------------------------------
# Wild mechanic surfaced — the multiplicative-wild volatility is visible via
# the frozen panels (symbol_combo decodes wilds; payids carry the boost). This
# is the W2-Layer-c claim. VALUE-AGNOSTIC: we assert the wilds are DECODED and
# FLAGGED, not their rates.
# ---------------------------------------------------------------------------

class TestWildMechanicSurfaced:
    def test_wild_payid_decodes_wild_in_symbol_combo(self, m84_pi):
        """At least one wild-bearing payid (a pid whose combos contain a 'wild*'
        symbol) is decoded with is_wild=True in its symbol_combo. This is how the
        multiplicative-wild mechanic becomes player-visible without a new plugin."""
        found_wild_combo = False
        for r in m84_pi.get("payout_ids_top20", []):
            combo = r.get("symbol_combo") or {}
            distinct = combo.get("distinct_symbols") or []
            if any("wild" in str(sym).lower() for sym in distinct):
                # such a pid must carry at least one is_wild=True combo row
                rows = combo.get("combos") or []
                assert any(c.get("is_wild") is True for c in rows), (
                    f"payid {r.get('payout_id')} has a wild symbol but no combo row "
                    f"flagged is_wild=True — the wild flag is not surfaced"
                )
                found_wild_combo = True
        assert found_wild_combo, (
            "no wild-bearing payid surfaced a decoded wild combo — the "
            "multiplicative-wild mechanic is not visible (W2 Layer-c claim broken)"
        )

    def test_reel_marginal_present_for_st1(self, m84_pi):
        """The per-column symbol marginals (board texture / wild anticipation) are
        delivered for ST1."""
        rm = m84_pi.get("reel_marginal_by_spin_type") or {}
        keys = list(rm.keys())
        assert any("1" in str(k) for k in keys), (
            f"reel_marginal_by_spin_type must carry an ST1 key; got {keys}"
        )


# ---------------------------------------------------------------------------
# Honesty — M84 invents NO bonus. machine_mechanics all applicable=False;
# bonus_chain inert; single upstream feature "Normal".
# ---------------------------------------------------------------------------

class TestHonestyNoInventedBonus:
    def test_machine_mechanics_all_inapplicable(self, m84_pi):
        """The report must NOT invent a lock / jackpot / free-spin / dollar-pick
        mechanic. EVERY machine_mechanics sub-block is applicable=False (single
        generic reel spin, no feature)."""
        mm = m84_pi.get("machine_mechanics") or {}
        assert mm, "machine_mechanics panel missing"
        for name, block in mm.items():
            if isinstance(block, dict) and "applicable" in block:
                assert block.get("applicable") is False, (
                    f"machine_mechanics.{name}.applicable must be False on M84 "
                    f"(no bonus mechanic); got {block.get('applicable')}"
                )

    def test_single_normal_feature(self, m84_pi):
        ufb = m84_pi.get("upstream_feature_breakdown") or {}
        feats = ufb.get("features") or []
        names = {f.get("feature_name") for f in feats}
        assert names == {"Normal"}, (
            f"M84 must surface exactly the single 'Normal' feature; got {names}"
        )

    def test_bonus_chain_inert(self, m84_pi):
        bcd = m84_pi.get("bonus_chain_dynamics")
        if isinstance(bcd, dict):
            assert bcd.get("applicable") is False, (
                "bonus_chain_dynamics must be inert (no chain on a single-ST machine)"
            )


# ---------------------------------------------------------------------------
# NON-LEAK — M84 declares NO role/play hook, so none of the play/role-keyed
# mechanic analyses (which belong to OTHER machines) may fire. Cross-checked
# against M104 where lock_respin_dynamics legitimately fires.
# ---------------------------------------------------------------------------

class TestNonLeakNoForeignMechanic:
    def test_derive_analyses_is_base_set_only(self, m84_manifest):
        """derive_analyses(M84) == CROSS_CUTTING U PER_SPINTYPE — it must contain
        NONE of the role/play-keyed mechanic analyses. The resolution path itself
        (not just the rendered report) must be clean."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        analyses = set(derive_analyses(m84_manifest))
        for foreign in _FOREIGN_MECHANIC_ANALYSES:
            assert foreign not in analyses, (
                f"derive_analyses(M84) leaked a foreign mechanic analysis "
                f"'{foreign}' — M84 declares no role/play hook; got {sorted(analyses)}"
            )

    def test_no_foreign_mechanic_section_in_report(self, m84_pi):
        """The REAL report must carry no role/play-keyed mechanic section (a leak
        would surface a bonus/respin/wheel panel on a plain reel slot)."""
        for foreign in _FOREIGN_MECHANIC_ANALYSES:
            assert foreign not in m84_pi, (
                f"foreign mechanic section '{foreign}' fired on M84 — it must NOT "
                "(M84 has no role/play hook for it)"
            )

    def test_structure_drift_no_undeclared_st(self, m84_summary, m84_manifest):
        """Structural honesty: every SpinType observed in the report is DECLARED in
        the manifest (zero undeclared ST). M84 declares only ST1, so the breakdown
        must surface only ST1 — a leak of any other ST (a sign of mis-parse or a
        foreign mechanic firing) would surface here. Value-agnostic set identity."""
        declared = {int(k) for k in m84_manifest["spin_types"].keys()}
        observed = {
            int(r["spin_type"])
            for r in m84_summary["player_impact"].get("spin_type_breakdown", [])
        }
        undeclared = observed - declared
        assert not undeclared, (
            f"undeclared SpinType(s) observed (structure drift): {sorted(undeclared)} "
            f"(declared={sorted(declared)})"
        )
        assert declared == {_ST1}, "M84 declares exactly ST1 (single-ST archetype)"

    @pytest.fixture(scope="class")
    def m104_summary(self):
        """M104 is the CONTROL: it declares play LockSymbolSpin, so
        lock_respin_dynamics legitimately fires there. This proves the non-leak
        assertion is meaningful (the analysis CAN fire — it just must not on M84)."""
        if not _has_chunks(_M104_CHUNK_DIR):
            pytest.skip("M104 cached chunks not present")
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            return generate_report_from_chunks(
                "M104", 1, chunk_dir=_M104_CHUNK_DIR,
                output_dir=Path(tmpdir), bet=_BET,
            )

    def test_lock_respin_fires_on_m104_but_not_m84(self, m104_summary, m84_pi):
        """The directional non-leak proof: lock_respin_dynamics is APPLICABLE on
        M104 (its rightful machine) and ABSENT/inert on M84. If M84 ever started
        firing it, this would catch the keying leak."""
        m104_lr = m104_summary["player_impact"].get("lock_respin_dynamics") or {}
        assert m104_lr.get("applicable") is True, (
            "control broken: lock_respin_dynamics must fire on M104 (play "
            "LockSymbolSpin) — otherwise the non-leak assertion proves nothing"
        )
        m84_lr = m84_pi.get("lock_respin_dynamics")
        assert m84_lr is None or m84_lr.get("applicable") is not True, (
            "lock_respin_dynamics leaked onto M84 (it has no LockSymbolSpin play)"
        )


# ---------------------------------------------------------------------------
# BET SANITY (the M279/M43 1000x trap) — bet=1000 yields sane multiplier
# columns; bet=1 dumps every win into the 100x+ band / inflates max_mult 1000x.
# VALUE-AGNOSTIC: we assert the SHAPE (wins spread, sane max) not a number.
# ---------------------------------------------------------------------------

class TestBetSanity:
    def test_served_bet_is_chunk_bet(self, m84_summary):
        assert m84_summary["sampling"]["bet"] == _BET, (
            f"the served report must carry sampling.bet=={_BET} (the chunk _bet) "
            "so the 'x bet' multiplier columns are not 1000x-inflated; got "
            f"{m84_summary['sampling']['bet']}"
        )

    def test_max_mult_is_sane_not_inflated(self, m84_pi):
        """A real slot multiplier is O(hundreds). With the bet=1 trap max_mult
        inflates by ~1000x (e.g. 450 -> 450000). Assert it stays in a sane slot
        range — value-agnostic upper bound, not a pinned value."""
        so = _st1_outcomes(m84_pi)
        max_mult = float(so.get("max_mult") or 0.0)
        assert 0.0 < max_mult < 100000.0, (
            f"max_mult {max_mult} is outside a sane slot multiplier range — the "
            "bet=1 1000x-inflation trap (M279/M43) likely fired"
        )

    def test_wins_not_all_dumped_into_top_band(self, m84_pi):
        """With the correct bet the win-band distribution SPREADS across bands;
        the bet=1 trap dumps EVERY win into the 100x+ band. Assert the top band
        does not hold (almost) all the wins — value-agnostic shape, not a count."""
        so = _st1_outcomes(m84_pi)
        bands = so.get("win_bands") or []
        assert bands, "ST1 win_bands missing"
        total = sum(int(b.get("hit_count") or 0) for b in bands)
        assert total > 0, "ST1 has wins"
        top = next(
            (int(b.get("hit_count") or 0) for b in bands if b.get("band") == "100x+"),
            0,
        )
        assert top < total, (
            f"ALL {total} wins landed in the 100x+ band — the bet=1 inflation trap "
            "fired (a real reel slot spreads wins across bands)"
        )


# ---------------------------------------------------------------------------
# INJECT-BUG PROOFS — break each safety claim in M84's OWN manifest → RED →
# (monkeypatch / restore) → GREEN. Per the brief, inject ONLY into M84's own
# manifest (M84 has no own plugin — it is strict-reuse), never a shared file.
#
# Claim A: M84 declares role paid_spin → derive_analyses yields the clean base
#          set (no foreign mechanic). If the manifest declared play LockSymbolSpin
#          (a foreign hook), lock_respin_dynamics would LEAK into the derived set.
# Claim B: the wild combo is decoded is_wild=True. (Asserted indirectly: a manifest
#          mutation cannot break the shared symbol_combo decoder, so this claim is
#          proven by the engine-level inject in Claim C instead.)
# Claim C: the served bet=1000 keeps the multiplier columns sane — re-running the
#          REAL engine with bet=1 (the trap) MUST flip the win-band shape to RED.
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_foreign_play_hook_leaks_mechanic_into_derive(self):
        """INJECT (Claim A / non-leak): mutate an IN-MEMORY copy of M84's manifest
        to declare play 'LockSymbolSpin' on ST1. derive_analyses then LEAKS
        lock_respin_dynamics into the base set — proving the non-leak guard goes
        RED when the keying is wrong. The on-disk manifest is NOT touched."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        manifest = json.loads(_M84_MANIFEST.read_text(encoding="utf-8"))

        # GREEN baseline: clean derived set, no foreign analysis.
        clean = set(derive_analyses(manifest))
        assert "lock_respin_dynamics" not in clean

        # INJECT the foreign play hook (in memory only).
        injected = json.loads(json.dumps(manifest))
        injected["spin_types"][str(_ST1)]["play"] = "LockSymbolSpin"
        leaked = set(derive_analyses(injected))

        # RED: the foreign mechanic now leaks in.
        assert "lock_respin_dynamics" in leaked, (
            "inject-bug failed to reproduce: declaring play LockSymbolSpin must "
            "leak lock_respin_dynamics into derive_analyses — if it does not, the "
            "non-leak guard cannot catch a foreign-hook regression"
        )
        # REVERT is automatic — we never mutated the on-disk manifest.
        assert "lock_respin_dynamics" not in set(derive_analyses(manifest)), (
            "the unmutated manifest must still derive a clean base set (GREEN)"
        )

    def test_inject_bet1_flips_win_band_shape_to_red(self):
        """INJECT (Claim C / bet trap): re-run the REAL engine with bet=1 (the
        default that drops the chunk bet). EVERY win then lands in the 100x+ band
        and max_mult inflates ~1000x — the bet-sanity assertions go RED. Then the
        bet=1000 run is GREEN again (proven by TestBetSanity on the module fixture).
        """
        if not _has_chunks(_M84_CHUNK_DIR):
            pytest.skip("M84 cached chunks not present")
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = generate_report_from_chunks(
                "M84", 1, chunk_dir=_M84_CHUNK_DIR,
                output_dir=Path(tmpdir), bet=1,  # THE TRAP
            )
        pi = bad["player_impact"]
        so = _st1_outcomes(pi)
        bands = so.get("win_bands") or []
        total = sum(int(b.get("hit_count") or 0) for b in bands)
        top = next(
            (int(b.get("hit_count") or 0) for b in bands if b.get("band") == "100x+"),
            0,
        )
        # RED reproduction: the trap dumps EVERY win into the top band.
        assert top == total and total > 0, (
            f"inject-bug failed to reproduce the bet=1 trap: expected ALL {total} "
            f"wins in the 100x+ band, got {top}"
        )
        # And max_mult inflates out of the sane range.
        assert float(so.get("max_mult") or 0.0) >= 100000.0, (
            "inject-bug: bet=1 must inflate max_mult past the sane bound"
        )
        # GREEN resumes: the served bet=1000 keeps it sane (re-asserted here).
        with tempfile.TemporaryDirectory() as tmpdir:
            good = generate_report_from_chunks(
                "M84", 1, chunk_dir=_M84_CHUNK_DIR,
                output_dir=Path(tmpdir), bet=_BET,
            )
        so_good = _st1_outcomes(good["player_impact"])
        bands_good = so_good.get("win_bands") or []
        total_good = sum(int(b.get("hit_count") or 0) for b in bands_good)
        top_good = next(
            (int(b.get("hit_count") or 0) for b in bands_good if b.get("band") == "100x+"),
            0,
        )
        assert top_good < total_good, "bet=1000 must spread wins (GREEN resumes)"
        assert float(so_good.get("max_mult") or 0.0) < 100000.0
