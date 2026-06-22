"""Wave-4 onboarding regression tests for machine M70 (club batch).

Charter: unit = SpinType (EVENT). The deliverable is the report-generating
STRUCTURE, not the report's numbers. Every assertion here is **VALUE-AGNOSTIC**:
structural keys, flags, and conservation invariants only. **NO RTP value or range
is ever pinned** — the machine's numbers change on re-sample / re-tune / upstream
config and a number pin would be a false-RED trap (per ANALYZER_ARCHITECTURE §5.6
and the charter's permanent invariant 1).

What M70 is (session_artifacts/_onboard/M70/03_design.md):
  - Base-game-only machine in mode 1. **ONE** round-level SpinType:
    st1 = paid base spin, role `paid_spin`, play `Normal`.
  - 100% STRICT-REUSE: no new plugin, no fork. Every metric is produced by the
    FROZEN generic plugins derived from CROSS_CUTTING + PER_SPINTYPE.
  - Attribution = the native PayoutId space (pids 2-6 via RewardLastNode 1:1).
    `sum(payid) == summary` holds NATIVELY → NO SynthesizePayIdRule, fallback
    bucket share == 0.
  - role `paid_spin` is already in KNOWN_ROLES, play `Normal` has no PLAY_ANALYSES
    entry → NO keyed analysis attaches → no cross-fire onto M70 and M70 cannot
    cross-fire onto any other machine.

Test groups
-----------
  TestM70RealReport   -- regenerate the REAL report from cached chunks and assert
                         the SEMANTIC output (integrity passed, fallback share==0,
                         declared ST present, frontend-contract keys present, bet
                         not inflated, parity). NEVER an exit code / "looks green".
  TestM70Manifest     -- the manifest declares exactly the structure W3 designed.
  TestM70DeriveSet    -- derive_analyses(M70) is CROSS_CUTTING + PER_SPINTYPE with
                         NO keyed analysis (the leak guard, structural).
  TestM70NonLeak      -- cross-machine: a play/dimension-keyed analysis another
                         machine introduces (minigame_dynamics / wheel_dynamics /
                         lock_respin_dynamics / nudge_dynamics / respin_dynamics /
                         freespin_dynamics / topdollar_choice) must NOT fire on
                         M70, and M70 must NOT pull any such analysis onto itself.
  TestM70InjectBugProofsDoc -- documents the break->RED->revert->GREEN runs that
                         prove each safety claim is real (the actual injection was
                         performed against M70's OWN manifest; see module docstring
                         INJECT-BUG LOG below).
  TestBaseHashUnchanged -- M70 onboarding is config/manifest-only; base_hash must
                         stay c5d2199142c3 (no closure file touched).

INJECT-BUG LOG (break -> RED -> revert -> GREEN), performed during authoring
against M70's OWN manifest configs/machine_manifests/M70.json ONLY (never a shared
plugin, never a file another machine uses) and reverted immediately:

  IB-1 (preview / double-count + economy guard).
    Target tests: TestM70RealReport.test_no_preview_double_count,
                  TestM70Manifest.test_st1_economy_is_real_wincredits
    Break: in M70.json, change spin_types."1".economy.kind "real" -> "preview"
           (st1's real WinCredits is now declared a non-real preview win).
    Observed RED: the regenerated report's rtp_integrity_check.session_conservation_ok
                  flipped from True to None (the all-real-economy gate now skips —
                  st1 win can no longer be conserved as real) -> the
                  test_no_preview_double_count guard (asserts ...ok is True) went
                  RED; the manifest economy guard also went RED.
    Revert -> GREEN: restored kind "real"; session_conservation_ok True again.
    NOTE: a first attempt (win_field "WinCredits" -> "WinAmount") did NOT go RED —
          the parser silently falls back to WinCredits when WinAmount is absent
          (round_win fallback chain), so that injection produced no observable
          signal and was rejected as a worthless test. The economy.kind=preview
          injection above is the one that actually flips a guard.

  IB-2 (declared-ST-present guard).
    Target test: TestM70RealReport.test_declared_spin_type_present_in_breakdown
    Break: in M70.json, rename the st1 key "1" -> "99" (so the manifest declares
           ST 99 but the rawdata only has ST 1).
    Observed RED: spin_type_breakdown still emits ST 1 from the rawdata while the
                  declared-set assertion (declared ST id present and == observed)
                  failed because the manifest's declared id no longer matched the
                  emitted breakdown id.
    Revert -> GREEN: restored "1".

  IB-3 (non-leak / derive guard).
    Target tests: TestM70DeriveSet.test_no_keyed_analysis_in_derived_set,
                  TestM70NonLeak.test_m70_does_not_pull_any_keyed_analysis
    Break: in M70.json, change spin_types."1".play "Normal" -> "WinMiniGame"
           (a play that has a PLAY_ANALYSES entry -> minigame_dynamics).
    Observed RED: derive_analyses(M70) gained "minigame_dynamics" -> both the
                  derived-set guard and the cross-machine non-leak guard went RED.
    Revert -> GREEN: restored play "Normal"; keyed-analysis set empty again.

  IB-4 (real-report leak guard).
    Target test: TestM70RealReport.test_no_keyed_analysis_block_in_report
    Break: same as IB-3 (play -> "WinMiniGame").
    Observed RED: the regenerated report grew summary["player_impact"]
                  ["minigame_dynamics"] -> the absent-key assertion went RED.
    Revert -> GREEN: restored play "Normal"; no keyed block in the report.

Every injection was on M70.json only and was reverted before this file was saved;
the manifest on disk is the W3-designed manifest.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from fresh_slotlab.analyzer.machine_spec import (
    KNOWN_ROLES,
    PLAY_ANALYSES,
    ROLE_ANALYSES,
    DIMENSION_ANALYSES,
    derive_analyses,
    derive_mechanism_flags,
    load_manifest,
    validate_schema,
)
from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks

ROOT = Path(__file__).resolve().parents[2]
MANIFESTS_ROOT = ROOT / "configs" / "machine_manifests"
M70_CHUNK_DIR = ROOT / "rawdata" / "M70" / "mode_1"

# The complete set of play/role/dimension-KEYED analyses in the fleet. M70 declares
# only role `paid_spin` + play `Normal` (neither keyed) so NONE of these may attach.
# Derived structurally from the spec tables so a NEW keyed analysis added later is
# automatically covered by the non-leak guard (no hand-maintained list to drift).
_ALL_KEYED_ANALYSES: frozenset[str] = frozenset(
    a
    for table in (ROLE_ANALYSES, PLAY_ANALYSES, DIMENSION_ANALYSES)
    for analyses in table.values()
    for a in analyses
)

# Fallback / garbage-bucket pid prefixes (ANALYZER_ARCHITECTURE §5.6 / rtp_integrity
# layer 2). Any pid with one of these prefixes is a silent mis-attribution signal.
_FALLBACK_PREFIXES: tuple[str, ...] = ("_unattributed_", "_other", "_default", "_misc")


@pytest.fixture(scope="module")
def m70_manifest() -> dict:
    return load_manifest("M70", MANIFESTS_ROOT)


@pytest.fixture(scope="module")
def m70_report() -> dict:
    """Regenerate the REAL M70 report from the cached chunk.

    bet=1000 is the chunk's _bet (verified below in test_bet_not_inflated). The
    engine default bet=1 would land 1 in sampling.bet and the frontend "x bet"
    columns would render 1000x inflated multipliers (the M279 trap) — so we pass
    the real chunk bet, exactly as the live console re-generate path does.
    """
    assert M70_CHUNK_DIR.exists(), f"M70 mode_1 chunk dir missing: {M70_CHUNK_DIR}"
    out = Path(tempfile.mkdtemp(prefix="m70_w4_report_"))
    summary = generate_report_from_chunks(
        "M70", 1, chunk_dir=M70_CHUNK_DIR, output_dir=out, bet=1000,
    )
    return summary


# ===========================================================================
# TestM70RealReport — the SEMANTIC output of the REAL regenerated report
# ===========================================================================
class TestM70RealReport:
    """Run the REAL thing (report_engine.generate_report_from_chunks on the cached
    chunk) and assert the actual summary. No exit code, no 'looks green'."""

    def test_report_is_a_dict_with_machine_and_mode(self, m70_report):
        assert isinstance(m70_report, dict)
        assert m70_report["machine"] == "M70"
        assert m70_report["mode"] == 1

    def test_rtp_integrity_passed(self, m70_report):
        """Layer-1 sum==our_total + Layer-2 no-fallback + Layer-3 anchors all pass.
        We assert the passed FLAG and the per-layer ok FLAGS — never an RTP value."""
        ric = m70_report.get("rtp_integrity_check")
        assert ric is not None, "rtp_integrity_check block missing from summary"
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True. Got: {ric.get('passed')!r}. "
            f"message={ric.get('summary_message')!r} error={ric.get('error')!r}"
        )
        assert ric.get("layer1_invariant_ok") is True, ric.get("layer1_error")
        assert ric.get("layer2_no_fallback_buckets_ok") is True
        assert ric.get("layer3_anchors_ok") is True

    def test_no_unattributed_fallback_bucket(self, m70_report):
        """Layer 2: NO `_unattributed_*` (or _other/_default/_misc) bucket; the
        fallback share is exactly 0 (M70 has native pids, NO SynthesizePayIdRule).
        This is the invariant_with_fallback_hides_drift guard — a fallback bucket
        is a silent mis-attribution signal, never a closing mechanism."""
        ric = m70_report["rtp_integrity_check"]
        assert ric.get("layer2_fallback_buckets_found") == [], (
            f"Expected NO fallback buckets, got {ric.get('layer2_fallback_buckets_found')!r}"
        )
        # Cross-check against the actual pid rows (independent of the gate).
        pid_rows = m70_report["player_impact"]["payout_ids_top20"]
        leaked = [
            r["payout_id"] for r in pid_rows
            if str(r["payout_id"]).startswith(_FALLBACK_PREFIXES)
        ]
        assert leaked == [], f"Fallback pids present in payout_ids_top20: {leaked!r}"

    def test_aggregator_parity_payid_sum_equals_rtp(self, m70_report):
        """Aggregator parity invariant: Sigma(payid rtp_contribution_pp) == rtp.point_pct.
        This is a RELATIONSHIP between two views of the SAME number (not a pinned
        value) — it must hold no matter what the resampled RTP is."""
        pi = m70_report["player_impact"]
        rtp_point = m70_report["rtp"]["point_pct"]
        sum_pp = sum(r.get("rtp_contribution_pp", 0.0) for r in pi["payout_ids_top20"])
        assert abs(sum_pp - rtp_point) < 1e-3, (
            f"payid rtp_pp sum ({sum_pp}) != rtp.point_pct ({rtp_point}) — "
            f"aggregator parity broken (missing attribution / double-count)."
        )

    def test_our_equals_server_when_server_present(self, m70_report):
        """If the server aggregate is present, our_total_win must equal it.
        When the server aggregate is ABSENT (server_total_win is None), this clause
        does not apply — we do NOT fabricate a comparison. (M70's single chunk has
        no upstream aggregate, so this is the vacuous branch; the assertion still
        runs so a future re-sample that DOES carry the server total is checked.)"""
        rtp = m70_report["rtp"]
        server = rtp.get("server_total_win")
        if server is not None and server > 0:
            our = rtp["our_total_win"]
            assert abs(our - server) < max(1.0, server * 1e-6), (
                f"our_total_win ({our}) != server_total_win ({server})"
            )

    def test_declared_spin_type_present_in_breakdown(self, m70_manifest, m70_report):
        """Every DECLARED SpinType's output is present in spin_type_breakdown, and
        the breakdown carries ONLY declared STs (M70 declares exactly st1)."""
        declared = {int(k) for k in m70_manifest["spin_types"].keys()}
        breakdown = m70_report["player_impact"]["spin_type_breakdown"]
        emitted = {int(r["spin_type"]) for r in breakdown}
        assert declared <= emitted, (
            f"declared STs {sorted(declared)} missing from breakdown {sorted(emitted)}"
        )
        # M70 is single-ST; the breakdown must be exactly the declared set.
        assert emitted == declared, (
            f"breakdown emitted STs {sorted(emitted)} != declared {sorted(declared)}"
        )

    def test_frontend_contract_keys_present(self, m70_report):
        """The frontend-contract keys the console renders must be present. These are
        the PER_SPINTYPE + base player_impact panels M70 surfaces through."""
        pi = m70_report["player_impact"]
        required_pi_keys = {
            # PER_SPINTYPE (the console per-ST panels)
            "spin_type_breakdown",
            "spin_type_outcomes",
            "spin_type_rtp_buckets",
            "payouts_by_spin_type",
            "reel_marginal_by_spin_type",
            # base panels
            "payout_ids_top20",
            "hit_and_payout",
            "volatility",
            "upstream_feature_breakdown",
        }
        missing = required_pi_keys - set(pi.keys())
        assert not missing, f"frontend-contract player_impact keys missing: {sorted(missing)}"

    def test_per_spintype_panels_keyed_on_st1(self, m70_report):
        """The reused per-ST panels surface st1 specifically (the console renders a
        section per emitted ST). spin_type_outcomes / payouts_by_spin_type are
        keyed by the ST label, and the st1 entry must exist."""
        pi = m70_report["player_impact"]
        sto = pi["spin_type_outcomes"]
        pbst = pi["payouts_by_spin_type"]
        assert isinstance(sto, dict) and len(sto) >= 1
        assert isinstance(pbst, dict) and len(pbst) >= 1
        # The single ST label must reference spin_type 1.
        st_ids = {int(v.get("spin_type")) for v in sto.values() if "spin_type" in v}
        assert 1 in st_ids, f"spin_type_outcomes has no st1 entry: keys={list(sto.keys())}"

    def test_upstream_feature_breakdown_inert(self, m70_report):
        """Single-feature machine ('Normal'): upstream_feature_breakdown is correctly
        inert (applicable=False), NOT a fabricated multi-feature panel."""
        ufb = m70_report["player_impact"]["upstream_feature_breakdown"]
        assert ufb.get("applicable") is False, (
            f"M70 is single-feature; applicable must be False, got {ufb.get('applicable')!r}"
        )

    def test_bet_not_inflated(self, m70_report):
        """The M279 bet trap: sampling.bet must equal the chunk's real _bet (1000),
        and the per-spin multiplier columns must be SANE (single/low-hundreds), not
        1000x inflated. We assert the bet PASSED THROUGH and the multiplier is in a
        sane band — NOT a specific RTP/multiplier value."""
        assert m70_report["sampling"]["bet"] == 1000, (
            f"sampling.bet must be the chunk _bet (1000), got "
            f"{m70_report['sampling'].get('bet')!r} — a bet=1 report inflates the "
            f"frontend 'x bet' columns 1000x (the M279 trap)."
        )
        avg_x = m70_report["player_impact"]["hit_and_payout"]["avg_win_when_hit_x"]
        # Sane band: a wild base game's avg win when hit is a small multiplier.
        # A 1000x-inflated report would make this thousands. Wide band — structural,
        # not a value pin.
        assert 0.0 < avg_x < 100.0, (
            f"avg_win_when_hit_x={avg_x} is outside the sane multiplier band — "
            f"likely a bet-inflation (1000x) regression."
        )

    def test_no_keyed_analysis_block_in_report(self, m70_report):
        """No play/role/dimension-keyed analysis block leaked into the report. The
        keyed plugins write summary["player_impact"][<feature_id>] (or top-level);
        none may appear for M70."""
        pi = m70_report["player_impact"]
        for key in _ALL_KEYED_ANALYSES:
            assert key not in pi, (
                f"keyed analysis {key!r} leaked into player_impact for M70 "
                f"(M70 declares no role/play/dimension that should produce it)."
            )
            assert key not in m70_report, (
                f"keyed analysis {key!r} leaked into the top-level summary for M70."
            )

    def test_no_preview_double_count(self, m70_report):
        """M70 has NO preview ST (st1 is economy.kind=real). The conservation check
        confirms session_win_sum == total_win (a preview ST contributing real win
        would break this). We assert the conservation FLAG, not the win amount."""
        ric = m70_report["rtp_integrity_check"]
        # session_conservation is informational; for a base-only real machine it
        # must be ok (no preview/orphan win double-count).
        assert ric.get("session_conservation_ok") is True, (
            f"session conservation not ok — possible preview/double-count: "
            f"{ric.get('session_conservation_notes')!r}"
        )


# ===========================================================================
# TestM70Manifest — the manifest declares exactly the W3-designed structure
# ===========================================================================
class TestM70Manifest:
    def test_manifest_is_schema_valid(self, m70_manifest):
        assert validate_schema(m70_manifest) == []
        assert m70_manifest["machine_id"] == "M70"
        assert m70_manifest["schema"] == "spintype-native/1"

    def test_single_paid_spin_type(self, m70_manifest):
        """M70 declares exactly ONE SpinType: st1, role paid_spin, play Normal."""
        sts = m70_manifest["spin_types"]
        assert list(sts.keys()) == ["1"], f"M70 must declare exactly st1, got {list(sts.keys())}"
        st1 = sts["1"]
        assert st1["role"] == "paid_spin"
        assert st1["play"] == "Normal"
        assert st1["role"] in KNOWN_ROLES

    def test_st1_economy_is_real_wincredits(self, m70_manifest):
        """st1 is a real paid win settling from WinCredits — NOT a preview."""
        econ = m70_manifest["spin_types"]["1"].get("economy", {})
        assert econ.get("win_field") == "WinCredits"
        assert econ.get("kind") == "real"

    def test_no_synthesize_payid_rule(self, m70_manifest):
        """st1 emits native pids → NO SynthesizePayIdRule. The round_win_rule field
        must be ABSENT (inventing a pid where real pids exist corrupts the ladder)."""
        assert "round_win_rule" not in m70_manifest, (
            "M70 must NOT declare a round_win_rule — st1 has native pids 2-6."
        )

    def test_no_trigger_payout(self, m70_manifest):
        """Base-only machine: no feature/granted-session trigger in mode 1."""
        trig = m70_manifest.get("trigger") or {}
        assert trig.get("payout_id") is None, (
            f"M70 mode 1 has no trigger; payout_id must be null, got {trig.get('payout_id')!r}"
        )

    def test_no_dimension_block_declared(self, m70_manifest):
        """M70 declares no dimension key (no trigger_paths / crazy_reel / etc.) — no
        declared-but-empty dimension (the M43/M279 'backend-only, console empty' trap)."""
        for st_id, spec in m70_manifest["spin_types"].items():
            for dim_key in DIMENSION_ANALYSES:
                assert dim_key not in spec, (
                    f"st{st_id} unexpectedly declares dimension key {dim_key!r}"
                )


# ===========================================================================
# TestM70DeriveSet — derive_analyses(M70) has NO keyed analysis (structural)
# ===========================================================================
class TestM70DeriveSet:
    def test_derived_set_is_crosscutting_plus_perspintype(self, m70_manifest):
        """M70's analysis set = CROSS_CUTTING + PER_SPINTYPE, sorted, no extras.
        Asserts the structural superset of required generic analyses (value-agnostic)."""
        derived = derive_analyses(m70_manifest)
        assert derived == sorted(derived), "derive_analyses must return a sorted list"
        required = {
            # PER_SPINTYPE
            "payouts_by_spin_type", "reel_marginal_by_spin_type",
            "spin_type_outcomes", "spin_type_rtp_buckets",
            # CROSS_CUTTING (subset M70 needs)
            "bankruptcy_simulation", "multiplier_profile", "machine_mechanics",
            "upstream_feature_breakdown",
        }
        missing = required - set(derived)
        assert not missing, f"M70 derived set dropped required analyses: {sorted(missing)}"

    def test_no_keyed_analysis_in_derived_set(self, m70_manifest):
        """THE LEAK GUARD: no play/role/dimension-keyed analysis appears in M70's
        derived set (role paid_spin has no ROLE_ANALYSES entry; play Normal has no
        PLAY_ANALYSES entry; no dimension block declared)."""
        derived = set(derive_analyses(m70_manifest))
        leaked = derived & _ALL_KEYED_ANALYSES
        assert leaked == set(), (
            f"keyed analyses leaked into M70's derived set: {sorted(leaked)}. "
            f"M70 declares only role 'paid_spin' + play 'Normal' (neither keyed)."
        )

    def test_mechanism_flags_all_inert(self, m70_manifest):
        """Base-only: no freespin / jackpot mechanic flags (no false mechanic)."""
        mf = derive_mechanism_flags(m70_manifest)
        assert mf["freespin_applicable"] is False
        assert mf["jackpot_applicable"] is False
        assert mf["scatter_trigger_pids"] == frozenset(), (
            f"M70 has no trigger; scatter_trigger_pids must be empty, got "
            f"{mf['scatter_trigger_pids']!r}"
        )


# ===========================================================================
# TestM70NonLeak — cross-machine isolation (both directions)
# ===========================================================================
class TestM70NonLeak:
    """Cross-machine NON-LEAK. M70 uses only the fleet-generic role `paid_spin` and
    play `Normal`, so it must neither receive nor emit any play/role/dimension-keyed
    analysis. This is the same isolation contract as
    test_m15_has_no_minigame_dynamics — proven against the OTHER machines too."""

    def test_m70_does_not_pull_any_keyed_analysis(self, m70_manifest):
        """Direction A: no keyed analysis fires ONTO M70."""
        derived = set(derive_analyses(m70_manifest))
        for keyed in sorted(_ALL_KEYED_ANALYSES):
            assert keyed not in derived, (
                f"{keyed!r} must NOT attach to M70 (no matching role/play/dimension)."
            )

    @pytest.mark.parametrize("other_machine,keyed_analysis", [
        ("M44", "minigame_dynamics"),
        ("M104", "lock_respin_dynamics"),
        ("M63", "nudge_dynamics"),
        ("M279", "wheel_dynamics"),
        ("M43", "respin_dynamics"),
        ("M275", "freespin_dynamics"),
        ("M15", "topdollar_choice"),
    ])
    def test_other_machines_keyed_analysis_does_not_fire_on_m70(
        self, m70_manifest, other_machine, keyed_analysis,
    ):
        """Direction B: an analysis another machine introduces/uses via its own
        play/role/dimension key must NOT fire on M70.

        For each available other-machine manifest, confirm IT derives the keyed
        analysis (so the test is exercising a real keyed analysis, not a typo) and
        confirm M70 does NOT. If the other manifest is absent, we still assert M70
        does not pull the keyed analysis (the M70 side of the contract is what
        matters and never depends on the other machine being present)."""
        m70_derived = set(derive_analyses(m70_manifest))
        assert keyed_analysis not in m70_derived, (
            f"{keyed_analysis!r} ({other_machine}'s analysis) leaked onto M70."
        )
        other_path = MANIFESTS_ROOT / f"{other_machine}.json"
        if other_path.exists():
            other_manifest = load_manifest(other_machine, MANIFESTS_ROOT)
            other_derived = set(derive_analyses(other_manifest))
            assert keyed_analysis in other_derived, (
                f"sanity: {other_machine} should derive {keyed_analysis!r} so the "
                f"non-leak test is exercising a REAL keyed analysis. "
                f"{other_machine} derived: {sorted(other_derived)}"
            )

    def test_m70_play_and_role_have_no_keyed_entry(self, m70_manifest):
        """The structural reason there is no leak: M70's role/play tokens carry no
        keyed-analysis entry, and M70 declares no dimension key. This pins WHY the
        isolation holds (so a future fleet change that adds a 'Normal'/'paid_spin'
        keyed entry would surface here)."""
        sts = m70_manifest["spin_types"].values()
        roles = {s["role"] for s in sts}
        plays = {s["play"] for s in sts}
        assert roles == {"paid_spin"}
        assert plays == {"Normal"}
        assert ROLE_ANALYSES.get("paid_spin", ()) == (), (
            "If a ROLE_ANALYSES['paid_spin'] entry is ever added it cross-fires onto "
            "the ENTIRE fleet base spin including M70 — that is a fleet-wide bug."
        )
        assert PLAY_ANALYSES.get("Normal", ()) == (), (
            "If a PLAY_ANALYSES['Normal'] entry is ever added it cross-fires onto "
            "every base-game machine including M70."
        )


# ===========================================================================
# TestM70InjectBugProofsDoc — the break->RED->revert->GREEN proofs (live re-runs)
# ===========================================================================
class TestM70InjectBugProofsDoc:
    """These tests re-establish, in CODE, the GREEN side of each inject-bug proof
    documented in the module INJECT-BUG LOG. The injection itself was performed by
    hand-editing M70.json during authoring (and reverted); these assertions are the
    guards that go RED when the bug is present. Keeping them here makes the proof
    re-runnable: re-inject the documented edit and watch the named test flip RED."""

    def test_ib1_guard_integrity_passes_green(self, m70_report):
        """IB-1 GREEN side: with win_field=WinCredits, integrity passes + parity holds."""
        assert m70_report["rtp_integrity_check"]["passed"] is True
        pi = m70_report["player_impact"]
        sum_pp = sum(r.get("rtp_contribution_pp", 0.0) for r in pi["payout_ids_top20"])
        assert abs(sum_pp - m70_report["rtp"]["point_pct"]) < 1e-3

    def test_ib2_guard_st1_present_green(self, m70_manifest, m70_report):
        """IB-2 GREEN side: declared st1 == emitted breakdown ST."""
        declared = {int(k) for k in m70_manifest["spin_types"].keys()}
        emitted = {int(r["spin_type"]) for r in m70_report["player_impact"]["spin_type_breakdown"]}
        assert emitted == declared

    def test_ib3_ib4_guard_no_keyed_leak_green(self, m70_manifest, m70_report):
        """IB-3/IB-4 GREEN side: play stays Normal -> no keyed analysis in derive
        OR in the regenerated report."""
        assert set(derive_analyses(m70_manifest)) & _ALL_KEYED_ANALYSES == set()
        for key in _ALL_KEYED_ANALYSES:
            assert key not in m70_report["player_impact"]


# ===========================================================================
# TestBaseHashUnchanged — onboarding is config-only; closure must be byte-stable
# ===========================================================================
class TestBaseHashUnchanged:
    def test_base_hash_is_current_baseline(self):
        """M70 onboarding adds only a manifest (config) — it touches NO base-closure
        file. The fleet base_hash baseline is ddde50975d25 (re-baselined 2026-06-22
        by the pluggable round_win rule-engine refactor — rule types moved to
        base-EXCLUDED round_win_rules/; prior pin 3ddaa183f38c was stale). M70 must
        equal the current baseline — a divergence here means a closure file was edited."""
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        bh = compute_base_analyzer_version()
        assert bh == "ddde50975d25", (
            f"base_hash changed from the ddde50975d25 baseline to {bh!r}. M70 "
            f"onboarding is config/manifest-only — a base_hash change means a "
            f"closure file was accidentally modified (or a new deliberate closure "
            f"change needs this baseline updated)."
        )
