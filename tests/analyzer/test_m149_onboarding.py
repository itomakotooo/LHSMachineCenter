"""M149 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This test asserts STRUCTURE / FLAGS / INVARIANTS, never an RTP value or a count
(charter permanent invariant 1). The machine's numbers change on re-sample /
re-tune / upstream-config drift, so pinning ANY number here would be brittle.

What M149 added (session_artifacts/_onboard/M149/03_design.md):
  - configs/machine_manifests/M149.json — the ONLY artifact. ST35 paid_spin/Normal,
    ST36 respin/MoveSpin. ZERO new plugins, ZERO config rules.
  - ST36 (role `respin`) routes to the FROZEN fleet-shared respin_dynamics plugin
    via machine_spec.ROLE_ANALYSES["respin"] — the SAME plugin M43 ST50 uses.
  - NO round_win_rule (contrast M43 ST51): every credit attributes natively via
    PayoutIdToWinAmount, so sum(payid)==WinCredits holds and the _unattributed_*
    fallback bucket is structurally 0 WITHOUT any synthesis (design §0/§2).

The whole test runs the REAL engine on the real ~40k chunk at rawdata/M149/mode_1
(charter invariant 3: run the real thing; read the real summary).

Tests
-----
1. report generates; rtp_integrity_check.passed == True; NO _unattributed_*
   fallback bucket (share == 0, no synthesis needed); L1 sum invariant holds;
   payid aggregator parity (sum payid rtp_pp == rtp.point_pct) — VALUE-AGNOSTIC.
2. schema / frontend-contract keys present (top-level + player_impact.*) +
   spin_type_breakdown has BOTH declared STs, neither double-counts.
3. respin_dynamics present + applicable with the DELIVERED metrics populated, STs
   resolved from the manifest (NOT hardcoded), play-label is M149's own MoveSpin.
4. the DEFERRED (parser-blind) burst-length / win-gating metrics are correctly
   FLAGGED parser_blind, NOT fabricated.
5. NON-LEAK both directions: M149 has NONE of the other play/role/dimension-keyed
   analyses (minigame/wheel/lock_respin/nudge/freespin/topdollar); and the
   respin_dynamics it DOES use must NOT fire on M15 (the role wiring did not leak).

Inject-bug → RED → revert → GREEN (TestInjectBugProof):
  Edits M149's OWN manifest on disk (never a shared plugin, never another machine's
  file), recomputes the REAL report, asserts the structure guard goes RED, then
  restores the exact original bytes (auto-revert) so the module GREEN fixture holds.
  Two independent injections, one per safety claim:
    A. role respin -> paid_spin on ST36  → respin_dynamics no longer derived/fires
       (delivered-metric guard goes RED). Proves test #3 catches a wiring regression.
    B. play Normal -> WinMiniGame on ST35 → minigame_dynamics LEAKS onto M149
       (non-leak guard goes RED). Proves test #5 catches a cross-fire regression.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# Repo root for locating rawdata + manifests.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M149_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M149" / "mode_1"
_M15_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M15" / "mode_1"
_M149_MANIFEST = _REPO_ROOT / "configs" / "machine_manifests" / "M149.json"

# The bet used during M149 sampling (chunk _bet=1000; design §0/§5 — the M279 trap:
# bet=1 would inflate every "x bet" column 1000x). The report is value-agnostic;
# bet only affects coin totals, which this test never asserts.
_BET = 1000


# Expected top-level keys (frontend contract — current schema). We assert a SUPERSET
# (all required present), never equality, so machine-specific keys do not make it brittle.
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

# Expected player_impact sub-keys — the standard set PLUS the respin_dynamics section
# M149 RIDES via the `respin` role. Superset, never equality.
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
    # M149 RIDES this shared section (the whole point of the `respin` role wiring):
    "respin_dynamics",
})

# The analyses M149 must NOT carry (its plays Normal+MoveSpin and roles paid_spin+respin
# match none of these hooks). Each is a play/role/dimension-keyed analysis owned by
# another machine: leaking it here would be a cross-fire bug (design §3).
_MUST_NOT_LEAK_PI_KEYS = (
    "minigame_dynamics",      # PLAY WinMiniGame (M43 ST51)
    "wheel_dynamics",         # PLAY Wheel (M279)
    "lock_respin_dynamics",   # PLAY LockSymbolSpin (M104)
    "nudge_dynamics",         # DIMENSION crazy_reel (M63)
    "freespin_dynamics",      # ROLE freespin / hold_respin
    "topdollar_choice",       # ROLE player_choice (M15 ST14)
)

# The two declared SpinTypes (design §6 manifest).
_DECLARED_STS = {35, 36}


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


def _payout_ids(summary) -> list[str]:
    return [
        str(r.get("payout_id", ""))
        for r in summary["player_impact"].get("payout_ids_top20", [])
    ]


def _generate(machine_id: str, chunk_dir: Path) -> dict:
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            machine_id, 1,
            chunk_dir=chunk_dir,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists(), (
            "write_summary_json must produce player_impact_summary.json"
        )
        return summary


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m149_summary():
    if not _has_chunks(_M149_CHUNK_DIR):
        pytest.skip("M149 cached chunks not present")
    return _generate("M149", _M149_CHUNK_DIR)


@pytest.fixture(scope="module")
def m149_player_impact(m149_summary):
    return m149_summary["player_impact"]


# ---------------------------------------------------------------------------
# 1. CORRECTNESS GATE — integrity passes; fallback share == 0 (NO synthesis).
#    VALUE-AGNOSTIC: structure/flags only, no RTP number.
# ---------------------------------------------------------------------------

class TestCorrectnessGate:
    def test_report_generates_with_machine_and_mode(self, m149_summary):
        assert m149_summary["machine"] == "M149"
        assert m149_summary["mode"] == 1
        assert m149_summary["sampling"]["chunks"] > 0
        assert m149_summary["sampling"]["total_spins"] > 0
        # The bet survived into sampling.bet (M279 trap: bet=1 would inflate the
        # frontend "x bet" columns 1000x). We assert the value we passed landed,
        # never an RTP/multiplier number.
        assert m149_summary["sampling"]["bet"] == _BET, (
            f"bet must round-trip into sampling.bet; got {m149_summary['sampling']['bet']}"
        )
        # No emit-loop / extract errors surfaced (feedback_no_silent_swallow.md).
        assert not m149_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m149_summary.get('feature_errors')}"
        )

    def test_rtp_integrity_passes(self, m149_summary):
        """rtp_integrity_check.passed must be True (sum(payid)==total, no fallback)."""
        ric = m149_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M149 mode 1. "
            f"Got passed={ric.get('passed')}, message={ric.get('summary_message', 'N/A')}."
        )

    def test_layer1_sum_invariant_holds(self, m149_summary):
        """L1 (value-agnostic): sum(pay_id win) == our_total_win — no orphan/double-count."""
        ric = m149_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant broken: {ric.get('layer1_error')}"
        )

    def test_no_unattributed_fallback_bucket(self, m149_summary):
        """Headline value-agnostic guard: the _unattributed_* fallback bucket is
        STRUCTURALLY 0 for M149 — every credit attributes natively via
        PayoutIdToWinAmount, NO SynthesizePayIdRule needed (design §0/§2). 'share == 0'
        = no fallback bucket exists, neither as a Layer-2 finding nor a payout_id row."""
        ric = m149_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}. "
            f"M149 must have ZERO fallback (native pay-id attribution on both STs)."
        )
        buckets = ric.get("layer2_fallback_buckets_found") or []
        assert buckets == [], f"unexpected fallback buckets: {buckets}"
        pids = _payout_ids(m149_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )

    def test_layer3_anchors_ok(self, m149_summary):
        """L3 anchors satisfied (no missing declared anchors)."""
        ric = m149_summary.get("rtp_integrity_check", {})
        assert ric.get("layer3_anchors_ok") is True, (
            f"Layer-3 anchors missing: {ric.get('layer3_missing_anchors')}"
        )

    def test_payid_aggregator_parity(self, m149_summary):
        """Fleet-wide hard invariant (feedback_aggregator_parity_invariant.md):
        sum(payout_ids.rtp_contribution_pp) == rtp.point_pct — two aggregator views of
        the SAME RTP must align. RELATIVE equality (we never pin point_pct's value)."""
        pi = m149_summary["player_impact"]
        point_pct = m149_summary["rtp"]["point_pct"]
        sum_payid_pp = sum(
            float(r.get("rtp_contribution_pp") or 0.0)
            for r in pi.get("payout_ids_top20", [])
        )
        assert point_pct is not None and point_pct > 0, "point_pct must be computed"
        assert abs(sum_payid_pp - point_pct) < 1e-3, (
            f"aggregator parity broken: sum(payid rtp_pp)={sum_payid_pp} != "
            f"rtp.point_pct={point_pct} (double-count or lost attribution)"
        )


# ---------------------------------------------------------------------------
# 2. SCHEMA / FRONTEND-CONTRACT keys present + per-ST breakdown shape.
# ---------------------------------------------------------------------------

class TestSchema:
    def test_top_level_keys_superset(self, m149_summary):
        missing = _EXPECTED_TOP_KEYS - set(m149_summary.keys())
        assert not missing, f"Expected top-level keys absent: {sorted(missing)}"

    def test_player_impact_keys_superset(self, m149_player_impact):
        missing = _EXPECTED_PI_KEYS - set(m149_player_impact.keys())
        assert not missing, f"Expected player_impact keys absent: {sorted(missing)}"

    def test_rtp_integrity_check_has_layer_fields(self, m149_summary):
        ric = m149_summary["rtp_integrity_check"]
        for field in ("passed", "layer1_invariant_ok", "layer2_no_fallback_buckets_ok",
                      "layer3_anchors_ok", "summary_message"):
            assert field in ric, f"rtp_integrity_check missing field: {field}"

    def test_both_declared_spin_types_present(self, m149_player_impact):
        """spin_type_breakdown must carry BOTH declared STs (35, 36) — the frontend per-ST
        panel deliverable rides this. Neither is dropped, neither is invented."""
        stb = m149_player_impact.get("spin_type_breakdown")
        assert isinstance(stb, list) and stb, "spin_type_breakdown must be a non-empty list"
        sts = {int(r["spin_type"]) for r in stb}
        assert _DECLARED_STS.issubset(sts), (
            f"declared STs {_DECLARED_STS} not all present in spin_type_breakdown: {sts}"
        )

    def test_no_preview_double_count(self, m149_player_impact):
        """Neither declared ST is a preview/trigger-only contributor: both ST35 and ST36
        carry real spins. A preview ST (feature_trigger_only=True) would contribute 0 to
        the paid loop; M149 has none, so a future change that mis-flags one as preview
        (and would otherwise drop its win from the totals) is caught here."""
        stb = {int(r["spin_type"]): r for r in m149_player_impact["spin_type_breakdown"]}
        for st in _DECLARED_STS:
            row = stb[st]
            assert row.get("feature_trigger_only") is False, (
                f"ST{st} unexpectedly flagged feature_trigger_only — would drop its win"
            )
            assert row.get("spins", 0) > 0, f"ST{st} has no spins (double-count/drop risk)"

    def test_payouts_by_spin_type_has_both_sts(self, m149_player_impact):
        """payouts_by_spin_type must key BOTH STs (the symbol-tier pay-id mix the
        money-agnostic bar wants — design §1). Existence/keys only, no win value."""
        pbst = m149_player_impact.get("payouts_by_spin_type")
        assert isinstance(pbst, dict) and pbst, "payouts_by_spin_type must be a non-empty dict"
        keys_blob = " ".join(pbst.keys())
        assert "35" in keys_blob and "36" in keys_blob, (
            f"payouts_by_spin_type must cover ST35 and ST36; got {sorted(pbst.keys())}"
        )


# ---------------------------------------------------------------------------
# 3. respin_dynamics — DELIVERED metrics populated (structure, not values).
#    M149 RIDES the same frozen plugin as M43 ST50, via the `respin` role.
# ---------------------------------------------------------------------------

class TestRespinDynamicsDelivered:
    @pytest.fixture
    def rd(self, m149_player_impact):
        rd = m149_player_impact.get("respin_dynamics")
        assert isinstance(rd, dict), "respin_dynamics section missing"
        return rd

    def test_applicable_and_resolved_spin_types(self, rd):
        """respin_dynamics fired for M149 (ST36 role=respin) and resolved the STs from
        the manifest (NOT hardcoded — feedback_no_hardcode.md). M149's respin ST is 36
        (NOT M43's 50), proving manifest-driven resolution."""
        assert rd.get("applicable") is True, (
            f"respin_dynamics must be applicable for M149; got {rd.get('applicable')} "
            f"reason={rd.get('reason')}"
        )
        assert rd.get("respin_spin_type") == 36, "respin ST must resolve to 36 (role=respin)"
        assert rd.get("base_spin_type") == 35, "base ST must resolve to 35 (role=paid_spin)"

    def test_grant_rate_populated(self, rd):
        """M1 grant-rate: openers + both felt denominators present, non-null and computed
        (M149 really has ST35->ST36 openers). Value-agnostic — no 1-in-39 pin."""
        gr = rd["grant_rate"]
        for k in ("openers", "per_winning_paid_spin", "per_paid_spin", "one_per_n_paid_spins"):
            assert k in gr, f"grant_rate missing {k}"
        assert gr["openers"] > 0, "M149 has ST35->ST36 openers; openers must be > 0"
        assert gr["per_winning_paid_spin"] is not None
        assert gr["per_paid_spin"] is not None

    def test_hit_rate_uplift_populated(self, rd):
        """M2 hit-rate uplift: respin/base hit-rates + the uplift ratio present and
        computed (a real ratio, not null). Value-agnostic — no 4.43x pin."""
        hu = rd["hit_rate_uplift"]
        for k in ("respin_hit_rate", "base_hit_rate", "uplift_ratio"):
            assert k in hu, f"hit_rate_uplift missing {k}"
        assert hu["respin_hit_rate"] is not None
        assert hu["base_hit_rate"] is not None
        assert hu["uplift_ratio"] is not None, "uplift_ratio must be computed (both rates known)"

    def test_multiplier_distributions_populated(self, rd):
        """M2 overlaid distributions: respin + base multiplier-band distributions present
        with non-empty bands (real histograms, the machine's own tier feel)."""
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
        """M3 skin-premium symbol/payid mix: respin + base payid shares present.
        M149 ST36 carries real symbol pids (1-7 + 10001), so respin_payid_share is non-empty."""
        pm = rd["payid_mix"]
        assert "respin_payid_share" in pm and "base_payid_share" in pm
        assert len(pm["respin_payid_share"]) > 0, (
            "respin_payid_share must be populated (ST36 has real symbol pids)"
        )

    def test_rtp_concentration_populated(self, rd):
        """M5 RTP-concentration: contribution + share + fat-tail + loss-rate present."""
        rc = rd["rtp_concentration"]
        for k in ("respin_rtp_contribution_pp", "share_of_all_win",
                  "fat_tail_ge20x_win_share", "loss_rate"):
            assert k in rc, f"rtp_concentration missing {k}"
        assert rc["share_of_all_win"] is not None

    def test_continuity_continuation_prob_populated(self, rd):
        """M4 continuity: continuation_prob P(respin->respin) is derivable base-excluded
        and must be a real (non-null) probability — the 'lock keeps going' feel."""
        cont = rd["continuity"]
        for k in ("continuation_prob", "respin_to_respin_transitions",
                  "respin_exit_transitions", "exit_breakdown"):
            assert k in cont, f"continuity missing {k}"
        assert cont["continuation_prob"] is not None, (
            "continuation_prob is derivable from transition counts; must not be null"
        )


# ---------------------------------------------------------------------------
# 4. DEFERRED metrics correctly FLAGGED parser_blind (NOT fabricated).
#    Same ANALYZER DATA BOUNDARY caveat as M43 (design §4). A future change that
#    fabricates the burst-length histogram / win-gating proof goes RED here.
# ---------------------------------------------------------------------------

class TestDeferredMetricsFlagged:
    def test_respin_continuity_parser_blind_present(self, m149_player_impact):
        """M4 burst-length histogram + win-gating proof are parser-blind. The marker must
        EXIST under continuity.parser_blind (continuation_prob IS delivered; only the
        burst-length SHAPE is blind). Protects the 'no fabricated coverage' invariant."""
        cont = m149_player_impact["respin_dynamics"]["continuity"]
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
# 5a. NON-LEAK (direction 1) — M149 has NONE of the other play/role/dimension
#     analyses. M149 declares plays Normal+MoveSpin / roles paid_spin+respin, which
#     match none of those hooks (design §3). A leak = cross-fire bug.
# ---------------------------------------------------------------------------

class TestM149NoForeignAnalyses:
    @pytest.mark.parametrize("key", _MUST_NOT_LEAK_PI_KEYS)
    def test_foreign_analysis_absent(self, m149_player_impact, key):
        assert key not in m149_player_impact, (
            f"{key} LEAKED onto M149 — M149's plays (Normal/MoveSpin) and roles "
            f"(paid_spin/respin) match none of the other-machine hooks. A foreign "
            f"play/role/dimension-keyed analysis fired here = cross-fire regression."
        )


# ---------------------------------------------------------------------------
# 5b. NON-LEAK (direction 2) — the respin_dynamics M149 USES must NOT fire on M15.
#     respin_dynamics is keyed on the `respin` role, which M15 does not have.
#     This is the cross-machine non-leak the charter (#3) requires.
# ---------------------------------------------------------------------------

class TestRespinDynamicsDoesNotLeakToM15:
    @pytest.fixture(scope="class")
    def m15_summary(self):
        if not _has_chunks(_M15_CHUNK_DIR):
            pytest.skip("M15 cached chunks not present")
        return _generate("M15", _M15_CHUNK_DIR)

    def test_m15_report_generates_and_integrity_passes(self, m15_summary):
        assert m15_summary["machine"] == "M15"
        assert m15_summary["rtp_integrity_check"].get("passed") is True, (
            "M15 integrity must still pass (onboarding M149 must not regress M15)"
        )

    def test_m15_has_no_respin_dynamics(self, m15_summary):
        assert "respin_dynamics" not in m15_summary["player_impact"], (
            "respin_dynamics LEAKED onto M15 — the `respin` role (M149 ST36) must not "
            "match M15 (which has no respin-role ST). ROLE_ANALYSES scoping prevents this."
        )


# ---------------------------------------------------------------------------
# INJECT-BUG PROOF — edit M149's OWN manifest → RED → (restore bytes) → GREEN.
#
# We mutate ONLY configs/machine_manifests/M149.json (M149's own artifact — never a
# shared plugin, never another machine's file), recompute the REAL report, assert the
# guard goes RED, then restore the exact original bytes. Two injections, one per claim.
# ---------------------------------------------------------------------------

class _ManifestPatch:
    """Context manager: apply a mutation fn to M149.json on disk, restore exact bytes."""
    def __init__(self, mutate):
        self._mutate = mutate
        self._orig_bytes = None

    def __enter__(self):
        self._orig_bytes = _M149_MANIFEST.read_bytes()
        d = json.loads(self._orig_bytes.decode("utf-8"))
        self._mutate(d)
        _M149_MANIFEST.write_text(json.dumps(d, indent=2), encoding="utf-8")
        return self

    def __exit__(self, *exc):
        # Restore the EXACT original bytes (not a re-serialization) — guarantees the
        # working tree is byte-identical, so base_hash / git diff are clean.
        _M149_MANIFEST.write_bytes(self._orig_bytes)
        return False


class TestInjectBugProof:
    def test_inject_respin_role_flip_kills_respin_dynamics(self):
        """INJECT A: flip ST36 role respin -> paid_spin in M149's OWN manifest. The
        `respin` role disappears, so derive_analyses no longer attaches respin_dynamics
        and it does NOT fire — TestRespinDynamicsDelivered would go RED. Proves the
        delivered-metric / wiring guard actually catches a regression. VALUE-AGNOSTIC."""
        if not _has_chunks(_M149_CHUNK_DIR):
            pytest.skip("M149 cached chunks not present")

        def _flip_role(d):
            d["spin_types"]["36"]["role"] = "paid_spin"

        with _ManifestPatch(_flip_role):
            summary = _generate("M149", _M149_CHUNK_DIR)
            pi = summary["player_impact"]
            rd = pi.get("respin_dynamics")
            # RED: respin_dynamics is no longer derived (no `respin` role) — either
            # absent entirely, or present-but-not-applicable. Both are the failure
            # mode the GREEN guard (applicable is True) catches.
            applicable = isinstance(rd, dict) and rd.get("applicable") is True
            assert not applicable, (
                "inject-bug: with ST36 role flipped to paid_spin, respin_dynamics must "
                f"NOT be applicable; got respin_dynamics={rd}"
            )
        # bytes restored on __exit__ — module GREEN fixture unaffected.

    def test_inject_play_change_leaks_minigame_dynamics(self):
        """INJECT B: change ST35 play Normal -> WinMiniGame in M149's OWN manifest. The
        WinMiniGame PLAY now matches PLAY_ANALYSES, so minigame_dynamics LEAKS into
        player_impact — TestM149NoForeignAnalyses would go RED. Proves the non-leak guard
        actually catches a cross-fire regression. VALUE-AGNOSTIC."""
        if not _has_chunks(_M149_CHUNK_DIR):
            pytest.skip("M149 cached chunks not present")

        def _leak_play(d):
            d["spin_types"]["35"]["play"] = "WinMiniGame"

        with _ManifestPatch(_leak_play):
            summary = _generate("M149", _M149_CHUNK_DIR)
            pi = summary["player_impact"]
            # RED: minigame_dynamics now leaks onto M149 (the WinMiniGame play fired it).
            assert "minigame_dynamics" in pi, (
                "inject-bug: with ST35 play=WinMiniGame, minigame_dynamics must LEAK "
                "into M149's player_impact (the non-leak guard must catch this)."
            )
        # bytes restored on __exit__.

    def test_green_resumes_after_revert(self, m149_summary):
        """After the inject-bug tests restore the manifest bytes, the real (un-patched)
        report is GREEN again: respin_dynamics applicable, no foreign-analysis leak.
        (m149_summary is the module fixture built from the pristine manifest.)"""
        pi = m149_summary["player_impact"]
        rd = pi.get("respin_dynamics")
        assert isinstance(rd, dict) and rd.get("applicable") is True
        assert "minigame_dynamics" not in pi
        assert m149_summary["rtp_integrity_check"].get("passed") is True
