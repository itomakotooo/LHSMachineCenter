"""M137 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This file asserts STRUCTURE / DETERMINISM / ATTRIBUTION / NON-LEAK / HONESTY
invariants, NEVER an RTP value or range. M137's numbers (RTP 87.792, hit-rate
15.228%, per-band shares, max_mult 499.95) drift on re-sample / re-tune /
upstream config change; pinning ANY of them would be a brittle false alarm
(charter permanent invariant 1). The only hard constants asserted are STRUCTURAL
ids fixed by the manifest / protocol (the single SpinType id 1, role=paid_spin,
play=Normal) and arithmetic IDENTITIES (Σ bucket rtp_pp == ST rtp_pp;
Σ payid rtp_pp == machine rtp) — ratio identities, not pinned magnitudes.

ARCHETYPE: single-ST self-settling base reel slot (session_artifacts/_onboard/
M137/03_design.md). The whole machine is ONE paid reel spin (st1 `Normal`,
role=paid_spin, play=Normal). It adds:
  - NO new plugin (derive_analyses == CROSS_CUTTING + PER_SPINTYPE, identical to
    the confirmed M15-mode-1 base case — §3 of the design doc).
  - NO round_win rule (native PayoutIdToWinAmount attribution; pay-id == winning
    symbol id; sum(payid)==summary holds NATIVELY → fallback bucket structurally 0).
  - configs/machine_manifests/M137.json declares two `out_of_engine_mechanics`
    (jackpot_symbol_progressive + CurJackpotStoreWin progressive) per the Gate-8
    user declaration — both rtp_impact_current == 0 (parse-as-is, RTP shown is the
    BASE RTP). These are DOMAIN declarations, NOT engine-visible mechanics; they
    must NOT change the attribution / integrity (the report still attributes 100%
    of the in-engine RTP with zero fallback).

NON-LEAK (the M43 lesson, inverted): because M137 declares neither respin/
freespin/hold_respin/player_choice roles nor WinMiniGame/Wheel plays, none of the
role/play-keyed plugins (respin_dynamics / freespin_dynamics / topdollar_choice /
minigame_dynamics / wheel_dynamics) can cross-fire onto it. The inject-bug proof
flips ONE token in a TEMP COPY of M137's OWN manifest (role=respin →
respin_dynamics appears; play=WinMiniGame → minigame_dynamics appears) to prove
the wiring is load-bearing, then the unpatched manifest is GREEN (absent).

The whole test runs the REAL engine on the real cached chunk at rawdata/M137/mode_1
(charter invariant 3: run the real thing, pass bet=chunk _bet=1000, read the real
summary). It NEVER reads an echo'd exit code.
"""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M137_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M137" / "mode_1"
_M15_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M15" / "mode_1"
_M137_MANIFEST = _REPO_ROOT / "configs" / "machine_manifests" / "M137.json"
_MANIFESTS_ROOT = _REPO_ROOT / "configs" / "machine_manifests"

# The bet used during M137 sampling (chunk _bet == 1000). The report is
# value-agnostic; bet only affects coin totals (never asserted) — but it MUST land
# in sampling.bet so the frontend "× bet" columns are not 1000× inflated (the M279
# trap). We assert sampling.bet == _BET and that max_mult is SANE, never a value.
_BET = 1000

# Structural SpinType identity fixed by the manifest / rawdata protocol (NOT a value).
_ST_ONLY = 1

# The role/play-keyed plugins that MUST NOT fire on a single flat base-game ST.
_ROLE_PLAY_PLUGINS = (
    "respin_dynamics",
    "freespin_dynamics",
    "topdollar_choice",
    "minigame_dynamics",
    "wheel_dynamics",
    "lock_respin_dynamics",  # M104's plugin
    "nudge_dynamics",        # M63's plugin
    "crazy_reel_dim",        # M63's plugin
)

# Any leaked attribution fallback bucket starts with this prefix (rtp_integrity L2).
_FALLBACK_PREFIX = "_unattributed"


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


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


def _write_manifest_copy(mf: dict) -> Path:
    """Write a TEMP copy of the M137 manifest to a temp manifests_root, return it.

    Inject-bug edits go ONLY into this temp copy (never the real manifest file),
    so the on-disk M137.json is untouched and base_hash is unaffected.
    """
    tmproot = Path(tempfile.mkdtemp(prefix="m137_mf_"))
    (tmproot / "M137.json").write_text(json.dumps(mf), encoding="utf-8")
    return tmproot


# Standard top-level summary keys the frontend contract depends on (superset check).
_EXPECTED_TOP_KEYS = frozenset({
    "machine", "mode", "rtp", "rtp_integrity_check", "sampling",
    "player_impact", "guideline_assessment", "guideline_comparison",
    "collect_mechanic", "storage", "structure_drift", "upstream_analysis",
})

# Standard player_impact sub-keys (the generic per-ST layer). M137 adds NO new
# dimension, so the set is exactly the generic base set — superset check.
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
})


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m137_summary():
    if not _has_chunks(_M137_CHUNK_DIR):
        pytest.skip("M137 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            "M137", 1,
            chunk_dir=_M137_CHUNK_DIR,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists(), (
            "write_summary_json must produce player_impact_summary.json"
        )
        yield summary


@pytest.fixture(scope="module")
def m137_player_impact(m137_summary):
    return m137_summary["player_impact"]


@pytest.fixture(scope="module")
def m137_manifest():
    if not _M137_MANIFEST.exists():
        pytest.skip("M137 manifest not present")
    return json.loads(_M137_MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def m137_derived():
    """derive_analyses(M137) from the REAL on-disk manifest."""
    if not _M137_MANIFEST.exists():
        pytest.skip("M137 manifest not present")
    from fresh_slotlab.analyzer.machine_spec import load_manifest, derive_analyses
    return set(derive_analyses(load_manifest("M137", _MANIFESTS_ROOT)))


# ---------------------------------------------------------------------------
# 0. SMOKE — report generates, frontend contract keys present, no feature errors.
# ---------------------------------------------------------------------------

class TestReportGenerates:
    def test_machine_and_mode(self, m137_summary):
        assert m137_summary["machine"] == "M137"
        assert m137_summary["mode"] == 1
        assert m137_summary["sampling"]["chunks"] > 0
        assert m137_summary["sampling"]["total_spins"] > 0
        # No emit/extract errors swallowed (feedback_no_silent_swallow.md).
        assert not m137_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m137_summary.get('feature_errors')}"
        )

    def test_frontend_contract_top_keys_present(self, m137_summary):
        """The frontend-contract top-level keys are all present (superset)."""
        missing = _EXPECTED_TOP_KEYS - set(m137_summary.keys())
        assert not missing, f"frontend-contract top keys missing from summary: {missing}"

    def test_frontend_contract_player_impact_keys_present(self, m137_player_impact):
        """The generic per-ST panel keys (spin_type_breakdown etc.) are present."""
        missing = _EXPECTED_PI_KEYS - set(m137_player_impact.keys())
        assert not missing, f"frontend-contract player_impact keys missing: {missing}"

    def test_bet_lands_in_sampling_avoids_m279_trap(self, m137_summary):
        """bet=chunk _bet=1000 must land in sampling.bet so the frontend '× bet'
        columns are not 1000× inflated (the M279 trap). VALUE-AGNOSTIC: we assert
        the bet PLUMBING, never a multiplier magnitude."""
        assert m137_summary["sampling"]["bet"] == _BET, (
            f"sampling.bet must be {_BET} (the chunk _bet) so multipliers render "
            f"sane; got {m137_summary['sampling'].get('bet')}"
        )


# ---------------------------------------------------------------------------
# 1. SINGLE-ST STRUCTURE — exactly one ST (st1 paid_spin/Normal); no second ST.
# ---------------------------------------------------------------------------

class TestSingleSpinTypeStructure:
    def test_manifest_declares_exactly_one_st(self, m137_manifest):
        st = m137_manifest["spin_types"]
        assert set(st.keys()) == {str(_ST_ONLY)}, (
            f"M137 is a single-ST machine; expected only ST{_ST_ONLY}, got {list(st.keys())}"
        )
        assert st[str(_ST_ONLY)]["role"] == "paid_spin"
        assert st[str(_ST_ONLY)]["play"] == "Normal"

    def test_report_surfaces_exactly_one_st(self, m137_player_impact):
        sts = _stb_spin_types(m137_player_impact)
        assert sts == {_ST_ONLY}, (
            f"spin_type_breakdown must surface exactly ST{_ST_ONLY}; got {sts}"
        )

    def test_st1_is_the_only_charged_event_full_share(self, m137_player_impact):
        """st1 carries 100% of the rounds — it is the only paid event. VALUE-AGNOSTIC:
        the 100% SHARE is a structural identity (single ST), not a tuned number."""
        rows = m137_player_impact["spin_type_breakdown"]
        assert len(rows) == 1
        row = rows[0]
        assert int(row["spin_type"]) == _ST_ONLY
        assert row["share_pct"] == pytest.approx(100.0), (
            f"a single-ST machine's only ST must carry 100% share; got {row['share_pct']}"
        )

    def test_no_trigger_declared(self, m137_manifest):
        """The trigger block is an explicit all-null no-trigger block (the machine
        has no feature trigger). Keeps derive_mechanism_flags honest."""
        trig = m137_manifest["trigger"]
        assert trig.get("payout_id") is None
        assert trig.get("remarks") is None
        assert trig.get("opens") is None


# ---------------------------------------------------------------------------
# 2. NATIVE ATTRIBUTION — rtp_integrity passes, ZERO fallback, native payids,
#    Σ payid rtp_pp == machine rtp. NO SynthesizePayIdRule (native map).
#    VALUE-AGNOSTIC: structure/flags + arithmetic identity, no RTP magnitude.
# ---------------------------------------------------------------------------

class TestNativeAttribution:
    def test_rtp_integrity_passes(self, m137_summary):
        ric = m137_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M137 mode 1; got "
            f"passed={ric.get('passed')}, message={ric.get('summary_message','N/A')}."
        )

    def test_layer1_sum_invariant_holds(self, m137_summary):
        """L1 (value-agnostic): sum(pay_id win) == our_total — no orphan/double-count."""
        ric = m137_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant broken: {ric.get('layer1_error')}"
        )

    def test_no_unattributed_fallback_bucket(self, m137_summary):
        """The headline value-agnostic guard: NO _unattributed_* (Layer-2) bucket.
        M137 attributes natively → fallback share == 0 (the bucket is absent)."""
        ric = m137_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}"
        )
        buckets = ric.get("layer2_fallback_buckets_found") or []
        assert buckets == [], f"unexpected fallback buckets: {buckets}"
        pids = _payout_ids(m137_summary)
        assert not any(p.startswith(_FALLBACK_PREFIX) for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )

    def test_payids_are_native_real_symbol_ids_not_synthetic(self, m137_player_impact):
        """Every ST1 payid is a REAL winning-symbol id (the native PayoutIdToWinAmount
        map). ZERO synthetic '_'-prefixed or 'st'-prefixed pids (no SynthesizePayIdRule).
        VALUE-AGNOSTIC: we assert the pids are real ids, not their win values, and we
        do NOT pin the count to 18 (a re-sample could surface a never-seen symbol)."""
        rows = m137_player_impact["payouts_by_spin_type"].get("ST1_paid")
        assert isinstance(rows, list) and len(rows) > 0, (
            "payouts_by_spin_type[ST1_paid] must carry the per-symbol payid rows"
        )
        pids = [str(r["payout_id"]) for r in rows]
        synth = [p for p in pids if p.startswith("_") or not p.lstrip("-").isdigit()]
        assert not synth, (
            f"M137 attributes natively — NO synthetic pid is allowed; found {synth}"
        )
        # All real ids are distinct (a true per-symbol map, no double-counted row).
        assert len(pids) == len(set(pids)), f"duplicate payid rows: {pids}"

    def test_payid_rtp_pp_sums_to_machine_rtp(self, m137_summary, m137_player_impact):
        """ARITHMETIC IDENTITY (value-agnostic): Σ(per-pid rtp_pp) == machine rtp.
        We assert the IDENTITY (the two sides match), never the magnitude itself —
        the magnitude moves on re-sample/re-tune, the identity is a hard invariant."""
        rows = m137_player_impact["payouts_by_spin_type"]["ST1_paid"]
        sum_pp = sum(r["rtp_contribution_pp"] for r in rows)
        machine_rtp = m137_summary["rtp"]["point_pct"]
        assert sum_pp == pytest.approx(machine_rtp, rel=1e-9, abs=1e-6), (
            f"Σ payid rtp_pp ({sum_pp}) must equal machine rtp ({machine_rtp}) — "
            f"the aggregator-parity invariant"
        )

    def test_session_conservation_not_lossy(self, m137_summary):
        """No win is silently lost to attribution. session_conservation must be
        'ok' or honestly skipped with a reason (never a silent partial-attribution)."""
        ric = m137_summary.get("rtp_integrity_check", {})
        level = ric.get("session_conservation_level")
        assert level in ("ok", "skip", None), (
            f"session_conservation_level must be ok / skip (with reason) / None; got {level}"
        )
        if level == "skip":
            assert ric.get("session_conservation_skip_reason"), (
                "a skipped conservation check must carry a reason (honest, not silent)"
            )


# ---------------------------------------------------------------------------
# 3. BUCKET / FEATURE PARITY — the win-tier distribution sums back to the ST rtp;
#    the single `Normal` feature confirms the flat base game. VALUE-AGNOSTIC.
# ---------------------------------------------------------------------------

class TestBucketAndFeatureParity:
    def test_single_normal_feature(self, m137_player_impact):
        """upstream_feature_breakdown shows EXACTLY one `Normal` feature firing on
        100% of spins (Q8 single-feature confirmation). VALUE-AGNOSTIC: fire_rate
        1.0 is a structural identity for a single-feature flat machine."""
        ufb = m137_player_impact["upstream_feature_breakdown"]
        feats = ufb["features"]
        assert len(feats) == 1, f"M137 is one flat feature; got {len(feats)} features"
        f = feats[0]
        assert f["feature_name"] == "Normal"
        assert f["fire_rate"] == pytest.approx(1.0), (
            f"the single Normal feature must fire on 100% of spins; got {f['fire_rate']}"
        )

    def test_win_tier_buckets_sum_to_feature_rtp(self, m137_player_impact):
        """ARITHMETIC IDENTITY: Σ(win-tier bucket rtp_pp) == machine rtp (the win-size
        distribution IS the multiplier distribution, charter invariant 4). The shape
        moves on re-tune; the SUM identity is hard."""
        f = m137_player_impact["upstream_feature_breakdown"]["features"][0]
        buckets = f["bucket_distribution"]
        assert len(buckets) > 0
        sum_pp = sum(b["rtp_contribution_pp"] for b in buckets)
        # parity against the per-ST contribution (single ST → == machine rtp).
        row = m137_player_impact["spin_type_breakdown"][0]
        assert sum_pp == pytest.approx(row["rtp_contribution_pp"], rel=1e-9, abs=1e-6), (
            f"Σ win-tier bucket rtp_pp ({sum_pp}) must equal the ST1 rtp_contribution_pp "
            f"({row['rtp_contribution_pp']})"
        )

    def test_multiplier_profile_is_sane_not_inflated(self, m137_player_impact):
        """The realized max multiplier must be SANE (a few hundred ×), not 1000×
        inflated — a smoke check that bet=1000 plumbed correctly (M279 trap).
        VALUE-AGNOSTIC: we assert max_mult is < bet (no inflation), NOT its value."""
        sto = m137_player_impact["spin_type_outcomes"]["ST1_paid"]
        max_mult = sto.get("max_mult")
        assert max_mult is not None, "spin_type_outcomes must carry max_mult"
        # If bet were dropped to 1, every multiplier would be ~1000× larger.
        assert max_mult < _BET, (
            f"max_mult ({max_mult}) is suspiciously >= bet ({_BET}) — likely a bet=1 "
            f"1000× inflation (the M279 trap). It must be a sane realized multiplier."
        )
        assert max_mult > 0, "a paying machine must have a positive max multiplier"


# ---------------------------------------------------------------------------
# 4. NO-PLUGIN / DEGENERATE-HOOK STRUCTURE — derive_analyses == generic base set;
#    no role/play plugin attaches; mechanism flags honest (no trigger).
# ---------------------------------------------------------------------------

class TestNoPluginStructure:
    def test_derive_analyses_has_no_role_or_play_plugin(self, m137_derived):
        """derive_analyses(M137) contains NONE of the role/play-keyed plugins —
        M137 declares neither a respin/freespin/choice role nor a WinMiniGame/Wheel
        play. This is the symmetric counterpart of M15's non-leak lock (design §3/§7)."""
        leaked = [p for p in _ROLE_PLAY_PLUGINS if p in m137_derived]
        assert not leaked, (
            f"role/play plugins LEAKED into M137's derived analyses: {leaked}. "
            f"M137 attaches CROSS_CUTTING + PER_SPINTYPE only."
        )

    def test_role_play_sections_absent_from_report(self, m137_player_impact):
        """The corresponding player_impact sections are ABSENT (not even
        applicable:False) — derive_analyses must not add them at all."""
        leaked = [p for p in _ROLE_PLAY_PLUGINS if p in m137_player_impact]
        assert not leaked, (
            f"role/play sections LEAKED into M137's report: {leaked}"
        )

    def test_mechanism_flags_honest_no_feature(self, m137_player_impact):
        """No trigger declared → freespin/jackpot mechanics report applicable:False
        (derive_mechanism_flags honest). VALUE-AGNOSTIC: structural flags only."""
        mm = m137_player_impact["machine_mechanics"]
        assert mm["jackpot"]["applicable"] is False, (
            "M137 declares no trigger — jackpot mechanic must be applicable:False"
        )
        assert mm["free_spin"]["applicable"] is False, (
            "M137 declares no trigger — free_spin mechanic must be applicable:False"
        )

    def test_collect_mechanic_not_applicable(self, m137_summary):
        """collect_mechanic self-detects no collect metronome on this flat base game."""
        cm = m137_summary.get("collect_mechanic") or {}
        assert cm.get("applicable") is False, (
            f"collect_mechanic must be applicable:False on a flat base game; got "
            f"{cm.get('applicable')}"
        )


# ---------------------------------------------------------------------------
# 5. OUT-OF-ENGINE DECLARATIONS are inert in mode_1 — they MUST NOT change
#    attribution / integrity (rtp_impact_current == 0; parse-as-is base RTP).
# ---------------------------------------------------------------------------

class TestOutOfEngineDeclarations:
    def test_manifest_declares_zero_impact_out_of_engine(self, m137_manifest):
        """The two Gate-8 declared out_of_engine_mechanics both carry
        rtp_impact_current == 0 (the test interface zeroes them). They are DOMAIN
        facts, not engine-visible mechanics."""
        ooe = m137_manifest.get("out_of_engine_mechanics") or []
        assert len(ooe) >= 1, (
            "M137 manifest must declare its out_of_engine_mechanics (Gate-8 declaration)"
        )
        names = {m.get("name") for m in ooe}
        assert any("jackpot" in str(n).lower() for n in names), (
            f"the jackpot_symbol_progressive declaration must be present; got {names}"
        )
        for m in ooe:
            assert m.get("rtp_impact_current") == 0, (
                f"out-of-engine mechanic {m.get('name')!r} must contribute 0 in the "
                f"current test interface (parse-as-is base RTP); got {m.get('rtp_impact_current')}"
            )

    def test_declared_mechanics_do_not_create_attribution(self, m137_summary):
        """The declared out-of-engine progressives must NOT inject any synthetic
        jackpot/progressive payid or fallback — the report shows ONLY the base RTP,
        fully attributed natively, zero fallback (rtp_impact_current == 0 in data)."""
        pids = _payout_ids(m137_summary)
        assert not any(
            "jackpot" in p.lower() or "progressive" in p.lower() for p in pids
        ), (
            f"a declared out-of-engine progressive must NOT create a payid row in "
            f"mode_1 (it is test-interface-zeroed); got pids {pids}"
        )
        ric = m137_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert (ric.get("layer2_fallback_buckets_found") or []) == []


# ---------------------------------------------------------------------------
# 6. CROSS-MACHINE NON-LEAK — onboarding M137 must NOT leak onto another machine,
#    and another machine's role/play-keyed analysis must NOT fire on M137.
#    (M104 lock_respin_dynamics / M63 nudge_dynamics must NOT fire on others;
#    M44 minigame_dynamics must NOT fire on M15 — the symmetric guard for M137.)
# ---------------------------------------------------------------------------

class TestCrossMachineNonLeak:
    @pytest.fixture(scope="class")
    def m15_summary(self):
        if not _has_chunks(_M15_CHUNK_DIR):
            pytest.skip("M15 cached chunks not present")
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            return generate_report_from_chunks(
                "M15", 1, chunk_dir=_M15_CHUNK_DIR,
                output_dir=Path(tmpdir), bet=_BET,
            )

    def test_m15_still_generates_and_integrity_passes(self, m15_summary):
        """Onboarding M137 must NOT regress the confirmed M15 base case."""
        assert m15_summary["machine"] == "M15"
        assert m15_summary["rtp_integrity_check"].get("passed") is True, (
            "M15 integrity must still pass (onboarding M137 must not regress M15)"
        )

    def test_m137_role_play_plugins_absent_on_m15_too(self, m15_summary):
        """M104's lock_respin_dynamics / M63's nudge_dynamics / minigame_dynamics
        are keyed on roles/plays that NEITHER M137 NOR M15 declares — so they must
        not fire on M15 (the symmetric non-leak: a play-keyed analysis stays scoped
        to its declaring machine)."""
        pi15 = m15_summary["player_impact"]
        for plugin in ("lock_respin_dynamics", "nudge_dynamics", "crazy_reel_dim", "minigame_dynamics"):
            assert plugin not in pi15, (
                f"{plugin} LEAKED onto M15 — it is keyed on a role/play M15 does not declare"
            )

    def test_m137_does_not_consume_minigame_or_respin(self, m137_player_impact):
        """The converse: minigame_dynamics / respin_dynamics (keyed on plays/roles
        M137 does not declare) are NOT in M137's report at all (not even
        applicable:False). derive_analyses must not add them."""
        for plugin in ("minigame_dynamics", "respin_dynamics", "wheel_dynamics",
                       "lock_respin_dynamics", "nudge_dynamics"):
            assert plugin not in m137_player_impact, (
                f"{plugin} LEAKED onto M137 — derive_analyses must not add a plugin "
                f"for a role/play M137 does not declare"
            )


# ---------------------------------------------------------------------------
# 7. INJECT-BUG PROOF — break each safety claim → RED → (auto-revert) → GREEN.
#
# All injections go into a TEMP COPY of M137's OWN manifest (never the real file)
# or a monkeypatch on a loader — NEVER a shared plugin / another machine's file.
# They all auto-revert (temp dirs discarded; monkeypatch undone) so the module
# fixtures (built from the real manifest) stay GREEN.
#
# Claim A (non-leak role): role=respin → respin_dynamics ATTACHES (proves the
#   ROLE_ANALYSES wiring is load-bearing; the real manifest has no such role).
# Claim B (non-leak play): play=WinMiniGame → minigame_dynamics ATTACHES (proves
#   the PLAY_ANALYSES wiring; the real manifest has play=Normal).
# Claim C (native payid): a SynthesizePayIdRule on ST1 COLLAPSES the per-symbol
#   native payids into a single synthetic 'st1' row (proves the native
#   PayoutIdToWinAmount per-symbol attribution is genuinely sourced, not faked).
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_respin_role_attaches_respin_dynamics(self):
        """INJECT (Claim A): flip ST1 role → 'respin' in a TEMP manifest copy.
        derive_analyses must then CONTAIN respin_dynamics — proving the absence on
        the real manifest is a real wiring fact, not a vacuous assertion."""
        from fresh_slotlab.analyzer.machine_spec import load_manifest, derive_analyses
        base = json.loads(_M137_MANIFEST.read_text(encoding="utf-8"))

        # baseline (real manifest copy, no edit): respin_dynamics ABSENT.
        tmproot0 = _write_manifest_copy(base)
        da0 = set(derive_analyses(load_manifest("M137", tmproot0)))
        assert "respin_dynamics" not in da0, "baseline must NOT have respin_dynamics"

        # INJECT: role=respin → respin_dynamics ATTACHES (RED for the non-leak claim).
        mf = copy.deepcopy(base)
        mf["spin_types"]["1"]["role"] = "respin"
        tmproot1 = _write_manifest_copy(mf)
        da1 = set(derive_analyses(load_manifest("M137", tmproot1)))
        assert "respin_dynamics" in da1, (
            "inject-bug: with role=respin, respin_dynamics MUST attach (wiring "
            "load-bearing). If it does not, the non-leak test is vacuous."
        )
        # REVERT is automatic — temp dirs discarded; the real manifest is untouched.

    def test_inject_winminigame_play_attaches_minigame_dynamics(self):
        """INJECT (Claim B): flip ST1 play → 'WinMiniGame' in a TEMP manifest copy.
        derive_analyses must then CONTAIN minigame_dynamics — proving the PLAY_ANALYSES
        wiring is load-bearing."""
        from fresh_slotlab.analyzer.machine_spec import load_manifest, derive_analyses
        base = json.loads(_M137_MANIFEST.read_text(encoding="utf-8"))

        tmproot0 = _write_manifest_copy(base)
        da0 = set(derive_analyses(load_manifest("M137", tmproot0)))
        assert "minigame_dynamics" not in da0, "baseline must NOT have minigame_dynamics"

        mf = copy.deepcopy(base)
        mf["spin_types"]["1"]["play"] = "WinMiniGame"
        tmproot1 = _write_manifest_copy(mf)
        da1 = set(derive_analyses(load_manifest("M137", tmproot1)))
        assert "minigame_dynamics" in da1, (
            "inject-bug: with play=WinMiniGame, minigame_dynamics MUST attach. "
            "If it does not, the non-leak test is vacuous."
        )
        # REVERT automatic.

    def test_inject_synth_rule_collapses_native_payids(self, monkeypatch):
        """INJECT (Claim C): monkeypatch load_rules_for_machine to return a
        SynthesizePayIdRule on ST1 (apply_when_pid_present=True) — suppressing the
        native per-symbol payids. Assert the 18 real symbol pids COLLAPSE into a
        single synthetic 'st1' row (a real native pid like '18' disappears). Proves
        the per-symbol 'which symbol carries the thrill' view (Q3/Q4) is genuinely
        sourced from PayoutIdToWinAmount, not fabricated. VALUE-AGNOSTIC: we assert
        the STRUCTURE (per-symbol vs collapsed), never a win value."""
        if not _has_chunks(_M137_CHUNK_DIR):
            pytest.skip("M137 cached chunks not present")
        import fresh_slotlab.round_win as rw_mod
        from fresh_slotlab.round_win import SynthesizePayIdRule

        def _synth_st1(machine_id, config):
            if machine_id == "M137":
                return [SynthesizePayIdRule(
                    spin_types=[_ST_ONLY], label_format="spin_type",
                    apply_when_pid_present=True,
                )]
            return []

        monkeypatch.setattr(rw_mod, "load_rules_for_machine", _synth_st1)

        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = generate_report_from_chunks(
                "M137", 1, chunk_dir=_M137_CHUNK_DIR,
                output_dir=Path(tmpdir), bet=_BET,
            )
            rows = summary["player_impact"]["payouts_by_spin_type"].get("ST1_paid") or []
            pids = [str(r["payout_id"]) for r in rows]
            assert "st1" in pids, (
                f"inject-bug: the synth rule must produce the synthetic 'st1' pid; got {pids}"
            )
            # The native per-symbol pids are gone — the per-symbol dimension collapsed.
            assert len(rows) == 1, (
                f"inject-bug: the synth rule must collapse the per-symbol native payids "
                f"into ONE synthetic row; got {len(rows)} rows {pids}"
            )
            assert not any(p.lstrip("-").isdigit() for p in pids), (
                f"inject-bug: native numeric symbol pids must be suppressed; got {pids}"
            )
        # monkeypatch auto-reverts here.

    def test_green_resumes_after_revert(self, m137_summary, m137_player_impact, m137_derived):
        """After every inject-bug reverts, the real (unpatched) report is GREEN:
        integrity passes, zero fallback, native per-symbol payids restored, no
        role/play plugin attaches."""
        ric = m137_summary["rtp_integrity_check"]
        assert ric.get("passed") is True
        assert (ric.get("layer2_fallback_buckets_found") or []) == []
        rows = m137_player_impact["payouts_by_spin_type"]["ST1_paid"]
        pids = [str(r["payout_id"]) for r in rows]
        assert len(rows) > 1, "native per-symbol payids must be restored (>1 row)"
        assert all(p.lstrip("-").isdigit() for p in pids), (
            f"all payids must be native numeric symbol ids after revert; got {pids}"
        )
        assert "st1" not in pids, "no synthetic 'st1' pid after revert"
        leaked = [p for p in _ROLE_PLAY_PLUGINS if p in m137_derived]
        assert not leaked, f"no role/play plugin attaches after revert; leaked {leaked}"
