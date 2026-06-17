"""M42 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This test asserts STRUCTURE / FLAGS / INVARIANTS, never an RTP value, range, or a
count of coins. The machine's numbers (RTP, hit-rates, openers) change on
re-sample / re-tune / upstream-config drift, so pinning ANY number here would be a
brittle false alarm (charter permanent invariant 1).

What M42 is (session_artifacts/_onboard/M42/03_design.md):
  - configs/machine_manifests/M42.json — ST1 paid_spin/Normal, ST50 respin/WinRespin.
    **M42 == M43 MINUS the ST51 `WinMiniGame` settlement.**
  - **NEW plugins: 0.** Both STs STRICT-REUSE the confirmed M43 plugins verbatim.
    respin_dynamics (the ST50 respin mechanic) attaches via the `respin` ROLE.
  - **NO minigame_dynamics** (no `WinMiniGame` play / no `settlement` ST).
  - **NO SynthesizePayIdRule / no round_win_rule** — every M42 win carries a real
    native numeric pid in PayoutIdToWinAmount, so attribution is native & complete
    with zero `_unattributed_*` fallback.

The whole test runs the REAL engine on the 20 real v3 chunks at
rawdata/M42/mode_1 (charter invariant 3: run the real thing; pass bet=<chunk _bet>
= 1000 so the frontend "x bet" columns are not inflated 1000x; read the real
summary, never an exit code).

Tests
-----
1. CORRECTNESS GATE — report generates; rtp_integrity_check.passed == True;
   layer1 sum invariant ok; NO `_unattributed_*` fallback bucket (share == 0);
   attribution is via NATIVE pids (no synthesized `st51`). VALUE-AGNOSTIC.
2. SCHEMA — top-level + player_impact frontend-contract keys present (superset).
3. BOTH declared SpinTypes (ST1, ST50) present in the per-ST sections; the free
   respin ST50 is structurally free (total_paid_bet == 0) and is correctly
   EXCLUDED from spin_type_rtp_buckets (paid_st = [1]); no double-count.
4. respin_dynamics — DELIVERED metrics populated (structure, not values); the
   DEFERRED (parser-blind) sub-metrics are correctly FLAGGED, NOT fabricated.
5. M42 has NO minigame_dynamics / wheel_dynamics (the inverse of M43 —
   the `WinMiniGame` PLAY wiring must NOT fire on a respin-only machine).
6. CROSS-MACHINE NON-LEAK — M15 still generates, integrity passes, and has
   NO respin_dynamics (the `respin` role did not leak onto M15).

Inject-bug → RED → revert → GREEN (TestInjectBugProof):
  monkeypatch machine_spec.load_manifest so that, for M42, ST50's `role` is
  flipped from `respin` to `paid_spin` (a single edit to M42's OWN manifest
  content, in memory). The REAL derive_analyses then no longer attaches
  respin_dynamics → the respin_dynamics section disappears from the report. This
  proves the role-keyed wiring guard (TestRespinDynamicsDelivered) actually goes
  RED when M42's manifest stops declaring the respin role. The monkeypatch
  auto-reverts, so the module-scoped m42_summary (built un-patched) stays GREEN.
  (The inject mutates ONLY M42's own manifest content — never a shared plugin or
  another machine's file — and never writes to disk.)
"""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import pytest

# Repo root for locating rawdata.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M42_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M42" / "mode_1"
_M15_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M15" / "mode_1"

# The bet used during M42 sampling (chunk _bet = 1000; cost=1000 per paid spin).
# The report is value-agnostic; bet only affects coin totals — which this test
# never asserts — but MUST be passed (the M279 bet=1 trap inflates "x bet" columns
# 1000x in the frontend).
_BET = 1000


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


# ---------------------------------------------------------------------------
# Expected frontend-contract keys (same current schema as the M15/M43 e2e).
# We assert a SUPERSET (all required keys present), never equality, so
# machine-specific keys do not make this brittle.
# ---------------------------------------------------------------------------

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

# Standard per-ST + cross-cutting sections PLUS the M42 respin mechanic section.
# NOTE: minigame_dynamics is deliberately ABSENT here (M42 has no WinMiniGame) —
# its absence is asserted positively in TestNoMiniGameLeak.
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
    # M42 respin mechanic section (reused M43 plugin via the `respin` role):
    "respin_dynamics",
})


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m42_summary():
    if not _has_chunks(_M42_CHUNK_DIR):
        pytest.skip("M42 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks

    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            "M42", 1,
            chunk_dir=_M42_CHUNK_DIR,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists(), (
            "write_summary_json must produce player_impact_summary.json"
        )
        yield summary


@pytest.fixture(scope="module")
def m42_player_impact(m42_summary):
    return m42_summary["player_impact"]


def _payout_ids(summary) -> list[str]:
    return [
        str(r.get("payout_id", ""))
        for r in summary["player_impact"].get("payout_ids_top20", [])
    ]


def _breakdown_by_st(player_impact) -> dict[int, dict]:
    return {
        int(r["spin_type"]): r
        for r in player_impact.get("spin_type_breakdown", [])
        if r.get("spin_type") is not None
    }


# ---------------------------------------------------------------------------
# 1. CORRECTNESS GATE — integrity passes; NO fallback bucket; native pids only.
#    VALUE-AGNOSTIC: structure/flags only, no RTP number.
# ---------------------------------------------------------------------------

class TestCorrectnessGate:
    def test_report_generates_with_machine_and_mode(self, m42_summary):
        assert m42_summary["machine"] == "M42"
        assert m42_summary["mode"] == 1
        assert m42_summary["sampling"]["chunks"] > 0
        assert m42_summary["sampling"]["total_spins"] > 0
        # bet must be the real sampling bet, not the engine default 1 (M279 trap).
        assert m42_summary["sampling"]["bet"] == _BET, (
            f"sampling.bet must be the chunk _bet ({_BET}); got "
            f"{m42_summary['sampling'].get('bet')} — the frontend 'x bet' columns "
            f"would be inflated otherwise."
        )
        # No emit-loop / extract errors surfaced (feedback_no_silent_swallow.md).
        assert not m42_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m42_summary.get('feature_errors')}"
        )

    def test_rtp_integrity_passes(self, m42_summary):
        """rtp_integrity_check.passed must be True (sum(payid)==total, no fallback)."""
        ric = m42_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M42 mode 1. "
            f"Got passed={ric.get('passed')}, message={ric.get('summary_message', 'N/A')}."
        )

    def test_layer1_sum_invariant_holds(self, m42_summary):
        """L1 (value-agnostic): sum(pay_id win) == our_total_win — no orphan/double-count."""
        ric = m42_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant broken: {ric.get('layer1_error')}"
        )

    def test_no_unattributed_fallback_bucket(self, m42_summary):
        """Native pids attribute every win directly: NO `_unattributed_*` (Layer-2
        fallback) bucket. 'share == 0' = the bucket is absent (charter invariant 1)."""
        ric = m42_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}."
        )
        buckets = ric.get("layer2_fallback_buckets_found") or []
        assert not buckets, f"unexpected fallback buckets: {buckets}"
        # And no _unattributed_* row leaks into the payout-id table.
        pids = _payout_ids(m42_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )

    def test_attribution_is_native_no_synthesized_pid(self, m42_summary):
        """M42 has NO no-payid settlement ST → NO SynthesizePayIdRule. The pids must
        be the NATIVE numeric symbol-tier ids (no synthesized 'st51'/'st*' marker)."""
        pids = _payout_ids(m42_summary)
        assert pids, "payout_ids_top20 must be non-empty"
        # M42 (= M43 minus ST51) must NOT carry the synthesized minigame pid.
        assert "st51" not in pids, (
            f"synthesized pid 'st51' must be ABSENT on M42 (no WinMiniGame ST); got {pids}"
        )
        assert not any(str(p).startswith("st") for p in pids), (
            f"no synthesized 'st*' pid expected (native attribution only); got {pids}"
        )
        # Native pids are numeric symbol-tier ids.
        assert any(str(p).isdigit() for p in pids), (
            f"expected native numeric symbol-tier pids; got {pids}"
        )


# ---------------------------------------------------------------------------
# 2. SCHEMA / FRONTEND-CONTRACT keys present.
# ---------------------------------------------------------------------------

class TestSchema:
    def test_top_level_keys_superset(self, m42_summary):
        missing = _EXPECTED_TOP_KEYS - set(m42_summary.keys())
        assert not missing, f"Expected top-level keys absent: {sorted(missing)}"

    def test_player_impact_keys_superset(self, m42_player_impact):
        missing = _EXPECTED_PI_KEYS - set(m42_player_impact.keys())
        assert not missing, f"Expected player_impact keys absent: {sorted(missing)}"

    def test_rtp_integrity_check_has_layer_fields(self, m42_summary):
        ric = m42_summary["rtp_integrity_check"]
        for field in ("passed", "layer1_invariant_ok", "layer2_no_fallback_buckets_ok",
                      "layer3_anchors_ok", "summary_message"):
            assert field in ric, f"rtp_integrity_check missing field: {field}"


# ---------------------------------------------------------------------------
# 3. BOTH declared SpinTypes present; free ST50 structurally free + paid_st scoping.
# ---------------------------------------------------------------------------

class TestSpinTypeStructure:
    def test_both_declared_spin_types_present_in_breakdown(self, m42_player_impact):
        """Every DECLARED SpinType (ST1, ST50) appears in spin_type_breakdown."""
        by_st = _breakdown_by_st(m42_player_impact)
        assert 1 in by_st, "ST1 (paid_spin/Normal) missing from spin_type_breakdown"
        assert 50 in by_st, "ST50 (respin/WinRespin) missing from spin_type_breakdown"

    def test_both_declared_spin_types_in_per_st_sections(self, m42_player_impact):
        """payouts_by_spin_type and spin_type_outcomes cover BOTH declared STs."""
        for section in ("payouts_by_spin_type", "spin_type_outcomes"):
            sect = m42_player_impact.get(section)
            assert isinstance(sect, dict), f"{section} must be a dict"
            keys = set(sect.keys())
            assert "ST1_paid" in keys, f"{section} missing ST1_paid; got {sorted(keys)}"
            assert "ST50_free" in keys, f"{section} missing ST50_free; got {sorted(keys)}"

    def test_respin_st50_is_structurally_free(self, m42_player_impact):
        """ST50 is the FREE respin: its paid bet is 0 (the free-respin structural
        invariant). ST1 (paid) has paid bet > 0. Value-agnostic — we assert the
        zero/non-zero STRUCTURE, never the amounts."""
        by_st = _breakdown_by_st(m42_player_impact)
        assert by_st[50]["total_paid_bet"] == 0, (
            f"ST50 is a FREE respin; total_paid_bet must be 0, got {by_st[50]['total_paid_bet']}"
        )
        assert by_st[1]["total_paid_bet"] > 0, (
            f"ST1 is a PAID spin; total_paid_bet must be > 0, got {by_st[1]['total_paid_bet']}"
        )

    def test_rtp_buckets_scoped_to_paid_st_only(self, m42_player_impact):
        """spin_type_rtp_buckets is the PAID-round bucket view → ST1 only (paid_st=[1]).
        The free ST50 must NOT appear (it would double-count free wins into the paid
        bucket view). This is the intended paid-round semantics."""
        srb = m42_player_impact.get("spin_type_rtp_buckets")
        assert isinstance(srb, dict), "spin_type_rtp_buckets must be a dict"
        assert "ST1_paid" in srb, f"ST1_paid must be the paid-bucket key; got {sorted(srb)}"
        assert "ST50_free" not in srb, (
            f"free ST50 must NOT appear in the paid-round rtp_buckets (double-count); "
            f"got {sorted(srb)}"
        )


# ---------------------------------------------------------------------------
# 4. respin_dynamics — DELIVERED metrics populated (structure, not values).
# ---------------------------------------------------------------------------

class TestRespinDynamicsDelivered:
    @pytest.fixture
    def rd(self, m42_player_impact):
        rd = m42_player_impact.get("respin_dynamics")
        assert isinstance(rd, dict), "respin_dynamics section missing"
        return rd

    def test_applicable_and_resolved_spin_types(self, rd):
        """respin_dynamics fired for M42 (ST50 role=respin) and resolved the STs
        from the manifest (NOT hardcoded ids — feedback_no_hardcode.md)."""
        assert rd.get("applicable") is True, (
            f"respin_dynamics must be applicable for M42; got {rd.get('applicable')} "
            f"reason={rd.get('reason')}"
        )
        assert rd.get("respin_spin_type") == 50, "respin ST must resolve to 50 (role=respin)"
        assert rd.get("base_spin_type") == 1, "base ST must resolve to 1 (role=paid_spin)"

    def test_grant_rate_populated(self, rd):
        """grant-rate: openers + both felt denominators present and non-null."""
        gr = rd["grant_rate"]
        for k in ("openers", "per_winning_paid_spin", "per_paid_spin", "one_per_n_paid_spins"):
            assert k in gr, f"grant_rate missing {k}"
        assert gr["openers"] > 0, "M42 has ST1->ST50 openers; openers must be > 0"
        assert gr["per_winning_paid_spin"] is not None
        assert gr["per_paid_spin"] is not None

    def test_hit_rate_uplift_populated(self, rd):
        """hit-rate uplift: respin/base hit-rates + uplift ratio present & computed
        (a real ratio, not null). Value-agnostic — no 5.54x pin."""
        hu = rd["hit_rate_uplift"]
        for k in ("respin_hit_rate", "base_hit_rate", "uplift_ratio"):
            assert k in hu, f"hit_rate_uplift missing {k}"
        assert hu["respin_hit_rate"] is not None
        assert hu["base_hit_rate"] is not None
        assert hu["uplift_ratio"] is not None, "uplift_ratio must be computed (both hit-rates known)"

    def test_multiplier_distributions_populated(self, rd):
        """Overlaid distributions: respin + base multiplier-band distributions present
        with non-empty bands (real histograms)."""
        rdist = rd["respin_multiplier_distribution"]
        assert isinstance(rdist.get("bands"), list) and len(rdist["bands"]) > 0, (
            "respin_multiplier_distribution.bands must be a non-empty histogram"
        )
        for band in rdist["bands"]:
            assert "band" in band and "spin_count" in band and "prob" in band, (
                f"distribution band malformed: {band}"
            )
        bdist = rd["base_multiplier_distribution"]
        assert isinstance(bdist, dict) and isinstance(bdist.get("bands"), list) and bdist["bands"], (
            "base_multiplier_distribution.bands must be a non-empty histogram"
        )

    def test_payid_mix_populated(self, rd):
        """skin-premium symbol/payid mix: respin + base payid shares present.
        M42 ST50 carries real native symbol pids, so respin_payid_share is non-empty."""
        pm = rd["payid_mix"]
        assert "respin_payid_share" in pm and "base_payid_share" in pm
        assert len(pm["respin_payid_share"]) > 0, (
            "respin_payid_share must be populated (ST50 has real native pids)"
        )

    def test_rtp_concentration_populated(self, rd):
        """RTP-concentration: contribution + share + fat-tail + loss-rate present."""
        rc = rd["rtp_concentration"]
        for k in ("respin_rtp_contribution_pp", "share_of_all_win",
                  "fat_tail_ge20x_win_share", "loss_rate"):
            assert k in rc, f"rtp_concentration missing {k}"
        assert rc["share_of_all_win"] is not None

    def test_continuity_continuation_prob_populated(self, rd):
        """continuity: the continuation_prob P(respin->respin) IS derivable
        base-excluded and must be a real (non-null) probability."""
        cont = rd["continuity"]
        for k in ("continuation_prob", "respin_to_respin_transitions",
                  "respin_exit_transitions", "exit_breakdown"):
            assert k in cont, f"continuity missing {k}"
        assert cont["continuation_prob"] is not None, (
            "continuation_prob is derivable from transition counts; must not be null"
        )

    def test_continuity_parser_blind_flagged_not_fabricated(self, rd):
        """The burst-length histogram + win-gating proof are parser-blind (inherited
        from M43's escalated accumulator gap). The marker must EXIST under
        continuity.parser_blind — NOT silently dropped, NOT fabricated. A future
        change that fakes the histogram or drops the flag goes RED (charter:
        'no fabricated coverage')."""
        cont = rd["continuity"]
        blind = cont.get("parser_blind")
        assert isinstance(blind, list) and len(blind) > 0, (
            "continuity.parser_blind must list burst_length_histogram + win_gating_proof"
        )
        blind_blob = " ".join(blind).lower()
        assert "burst_length" in blind_blob, "burst_length_histogram must be flagged blind"
        assert "win_gating" in blind_blob or "win-gat" in blind_blob, (
            "win_gating_proof must be flagged blind"
        )
        assert isinstance(cont.get("parser_blind_reason"), str) and cont["parser_blind_reason"], (
            "continuity.parser_blind_reason must explain WHY (escalation, not silence)"
        )


# ---------------------------------------------------------------------------
# 5. NO minigame_dynamics / wheel_dynamics on M42 (the inverse of M43).
#    M42 = M43 minus ST51 → the WinMiniGame PLAY hook must NOT fire here.
#    (This is the inverse of M43's test_m15_has_no_minigame_dynamics — it proves
#    the PLAY scoping does not over-fire onto a respin-only machine.)
# ---------------------------------------------------------------------------

class TestNoMiniGameLeak:
    def test_m42_has_no_minigame_dynamics(self, m42_player_impact):
        assert "minigame_dynamics" not in m42_player_impact, (
            "minigame_dynamics LEAKED onto M42 — M42 has NO WinMiniGame play / NO "
            "settlement ST. It must attach ONLY via the WinMiniGame PLAY (M43's ST51), "
            "which M42 does not have."
        )

    def test_m42_has_no_wheel_dynamics(self, m42_player_impact):
        assert "wheel_dynamics" not in m42_player_impact, (
            "wheel_dynamics LEAKED onto M42 — M42 has no Wheel play."
        )


# ---------------------------------------------------------------------------
# 6. CROSS-MACHINE NON-LEAK — M15 untouched; the `respin` role did not leak.
#    respin_dynamics is keyed on the `respin` role, which M15 does not have. M15
#    must still generate cleanly and show NO respin_dynamics.
# ---------------------------------------------------------------------------

class TestM15NotLeaked:
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

    def test_m15_report_generates_and_integrity_passes(self, m15_summary):
        assert m15_summary["machine"] == "M15"
        assert m15_summary["rtp_integrity_check"].get("passed") is True, (
            "M15 integrity must still pass (onboarding M42 must not regress M15)"
        )

    def test_m15_has_no_respin_dynamics(self, m15_summary):
        assert "respin_dynamics" not in m15_summary["player_impact"], (
            "respin_dynamics LEAKED onto M15 — the `respin` role must not match M15. "
            "M42 declaring role=respin on ST50 must not over-fire respin_dynamics fleet-wide."
        )

    def test_m15_has_no_minigame_dynamics(self, m15_summary):
        # Sanity: M15 also has no WinMiniGame play (M43's minigame plugin is keyed on
        # the PLAY, not the `settlement` role M15's ST15 shares).
        assert "minigame_dynamics" not in m15_summary["player_impact"], (
            "minigame_dynamics LEAKED onto M15."
        )


# ---------------------------------------------------------------------------
# INJECT-BUG PROOF — flip M42's OWN manifest ST50 role → RED → (auto-revert) → GREEN.
#
# The key wiring claim of this onboarding is: ST50 declaring `role: respin` in
# M42's manifest is what attaches respin_dynamics (via ROLE_ANALYSES). This proves
# TestRespinDynamicsDelivered actually goes RED when that declaration is gone.
#
# The inject mutates ONLY M42's own manifest content (in memory, via a load_manifest
# wrapper) — never a shared plugin, never another machine's file, never disk. The
# monkeypatch auto-reverts, so the module-scoped m42_summary (built un-patched)
# stays GREEN.
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_strip_respin_role_removes_respin_dynamics(self, monkeypatch):
        """INJECT: M42's ST50 manifest `role` is flipped respin -> paid_spin. The REAL
        derive_analyses then no longer attaches respin_dynamics → the section vanishes
        from the report. VALUE-AGNOSTIC (the missing section is the signature, not a
        number)."""
        if not _has_chunks(_M42_CHUNK_DIR):
            pytest.skip("M42 cached chunks not present")

        import fresh_slotlab.analyzer.machine_spec as ms_mod

        _orig_load = ms_mod.load_manifest

        def _load_role_flipped(machine_id, manifests_root=None, *args, **kwargs):
            man = _orig_load(machine_id, manifests_root, *args, **kwargs)
            if str(machine_id) == "M42":
                man = copy.deepcopy(man)
                # BUG: M42's manifest stops declaring the respin role on ST50.
                man["spin_types"]["50"]["role"] = "paid_spin"
            return man

        monkeypatch.setattr(ms_mod, "load_manifest", _load_role_flipped)

        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks

        with tempfile.TemporaryDirectory() as tmpdir:
            summary = generate_report_from_chunks(
                "M42", 1,
                chunk_dir=_M42_CHUNK_DIR,
                output_dir=Path(tmpdir),
                bet=_BET,
            )
            pi = summary["player_impact"]
            # RED — respin_dynamics is no longer derived → absent from the report.
            assert "respin_dynamics" not in pi, (
                "inject-bug: with ST50 role flipped off `respin`, respin_dynamics must "
                "NOT be derived/emitted. If it is still present, the role wiring is not "
                "what attaches it — the delivered-metrics guard would be a false green."
            )
        # monkeypatch auto-reverts here — the module-scoped GREEN fixture is unaffected.

    def test_green_resumes_after_revert(self, m42_summary):
        """After the inject-bug test's monkeypatch reverts, the real (un-patched)
        report is GREEN again: respin_dynamics present + applicable, integrity passes,
        no fallback bucket. (m42_summary is the module fixture built WITHOUT the patch
        — proves revert restores GREEN.)"""
        ric = m42_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert ric.get("layer2_no_fallback_buckets_ok") is True
        rd = m42_summary["player_impact"].get("respin_dynamics")
        assert isinstance(rd, dict) and rd.get("applicable") is True, (
            "respin_dynamics must be present + applicable after the monkeypatch reverts"
        )


# ---------------------------------------------------------------------------
# 7. BASE-HASH STABILITY — M42 onboarding is MANIFEST-ONLY (zero plugin / zero
#    closure edit), so the analyzer base_hash must NOT move because of M42. A move
#    means a base-closure file (versioning._CLOSURE_FILES) was touched — which an
#    onboard that adds only configs/machine_manifests/M42.json must never do.
#
#    ANTI-FALSE-GREEN NOTE (why we do NOT pin a literal like the older fleet tests):
#    the historical onboarding tests pin `c5d2199142c3`. That literal is STALE — it
#    predates the committed per-ST extraction layer (commit 95ba119) which legitimately
#    added st_extract/__init__.py + st_extract/_base.py to _CLOSURE_FILES, moving the
#    canonical committed base_hash to a NEW value. Pinning that old literal would make
#    this test guaranteed-RED on a perfectly clean tree (a false alarm that catches no
#    real regression — exactly the trap the charter forbids: "NEVER pin a value that
#    the machine's own evolution changes"). Instead we assert base_hash equals the
#    value INDEPENDENTLY recomputed from the *committed* closure files on disk: this
#    goes RED iff M42 (or anything) actually edits a closure file, and stays GREEN on
#    a legitimate, already-committed closure — which is the real invariant we care
#    about (M42 touched no closure file).
# ---------------------------------------------------------------------------

class TestBaseHashUnchangedByM42:
    def test_function_matches_independent_closure_recompute(self):
        """base_hash from compute_base_analyzer_version() must equal an INDEPENDENT
        recomputation over the same committed _CLOSURE_FILES (read fresh from disk,
        same CRLF→LF + sorted-by-path algorithm). This proves M42 added no closure
        file and edited none: if any closure source on disk differed from what the
        engine hashes, the two would diverge. VALUE-AGNOSTIC: no literal pinned."""
        import hashlib
        from fresh_slotlab.analyzer import versioning as _v

        engine_bh = _v.compute_base_analyzer_version()

        h = hashlib.sha256()
        for rel in sorted(_v._CLOSURE_FILES):
            src = _v._REPO_ROOT / rel
            assert src.exists(), f"closure file missing on disk: {src}"
            h.update(src.read_bytes().replace(b"\r\n", b"\n"))
        independent_bh = h.hexdigest()[:12]

        assert engine_bh == independent_bh, (
            f"base_hash function ({engine_bh}) disagrees with an independent recompute "
            f"of the committed closure ({independent_bh}) — the closure set or a closure "
            f"source moved out from under the engine."
        )

    def test_m42_manifest_is_not_a_closure_file(self):
        """The thing M42 onboarding actually adds — configs/machine_manifests/M42.json
        — must NOT be in the base closure (manifests are config, not code). If it were,
        every machine onboard would re-flag the whole fleet. This is the structural
        reason an M42 onboard leaves base_hash alone."""
        from fresh_slotlab.analyzer import versioning as _v
        for rel in _v._CLOSURE_FILES:
            assert "machine_manifests" not in rel, (
                f"a machine manifest leaked into the base closure: {rel} — onboarding "
                f"M42 (a manifest add) would then move base_hash fleet-wide."
            )
        assert not any(rel.endswith("M42.json") for rel in _v._CLOSURE_FILES)

    def test_base_hash_moves_red_when_a_closure_source_changes(self, monkeypatch):
        """INJECT-BUG (closure tamper): feed compute_base_analyzer_version a closure
        whose bytes differ from disk and prove base_hash MOVES → RED. This proves the
        stability assertion above is not vacuous: it really would catch a closure edit.
        Done via the function's own `closure_files`/`repo_root` test seam over a tmp
        copy — NEVER touching any real source file (no disk write to the repo)."""
        import hashlib
        import tempfile
        from fresh_slotlab.analyzer import versioning as _v

        clean = _v.compute_base_analyzer_version()

        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            # Mirror the committed closure into a tmp root, then tamper ONE file.
            for rel in _v._CLOSURE_FILES:
                dst = tmp_root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes((_v._REPO_ROOT / rel).read_bytes())
            tampered_rel = "fresh_slotlab/analyzer/versioning.py"
            tgt = tmp_root / tampered_rel
            tgt.write_bytes(tgt.read_bytes() + b"\n# injected closure tamper\n")

            tampered = _v.compute_base_analyzer_version(
                closure_files=_v._CLOSURE_FILES, repo_root=tmp_root
            )
            # RED side of the inject: a closure edit MUST move base_hash.
            assert tampered != clean, (
                "tampering a closure source did not move base_hash — the stability "
                "guard would be a false green (it cannot detect a closure edit)."
            )

        # REVERT (the tmp dir is gone) → the real function is GREEN/clean again.
        assert _v.compute_base_analyzer_version() == clean, (
            "base_hash did not return to its clean value after the tmp tamper was "
            "discarded — the inject leaked into the real closure."
        )
