"""M78 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This test asserts STRUCTURE / FLAGS / INVARIANTS, never an RTP value or a count.
M78's numbers (RTP 91.45%, hit-rate 20.8%, per-pay-id shares, bucket counts)
change on re-sample / re-tune / upstream-config drift, so pinning ANY number here
would be a brittle false alarm (charter permanent invariant 1). The ONLY hard
numbers asserted are STRUCTURAL identifiers fixed by the manifest / rawdata
protocol (the SpinType id 1, the bet=1000 the chunk was sampled at) — never an RTP
or an observed frequency.

What M78 onboarded (session_artifacts/_onboard/M78/03_design.md):
  - configs/machine_manifests/M78.json — a SINGLE SpinType machine: ST1
    role=paid_spin / play=Normal, a self-settling paid base reel spin (the
    canonical M15-reference shape). Carries `economy` (WinCredits/real), a
    `signature` (turns on the signature_audit extractor → structure_drift AUDITS),
    `rtp_integrity.paid_st=[1]`, and `out_of_engine_mechanics` (the fleet-standard
    CurJackpotStoreWin test-interface-zeroed progressive).
  - ZERO new plugins. paid_spin is absent from ROLE_ANALYSES, Normal is absent
    from PLAY_ANALYSES, and there is no DIMENSION_ANALYSES key on the ST — so
    derive_analyses(M78) is the PURE generic set (CROSS_CUTTING + PER_SPINTYPE),
    byte-identical to M15's. No machine_spec edit, no round_win rule, no synthesis.
  - Attribution dimension: the machine's OWN round-level PayoutIdToWinAmount
    symbol-line pay-id space. sum(payid)==WinCredits==server TotalWin natively;
    wins_with_empty_payid==0 → the fallback bucket is 0 with NO SynthesizePayIdRule.

Because M78 introduces no new keyed analysis, the headline non-leak is the
CONVERSE: NONE of the fleet's feature plugins (minigame_dynamics / wheel_dynamics /
respin_dynamics / freespin_dynamics / topdollar_choice / lock_respin_dynamics /
nudge_dynamics) may fire on M78. The positive controls (M104→lock_respin_dynamics,
M63→nudge_dynamics, M44→minigame_dynamics) confirm those plugins ARE real and DO
fire on their declaring machines — so the M78 absences are meaningful, not vacuous.

The whole test runs the REAL engine on the real cached chunks at
rawdata/M78/mode_1 (charter invariant 3: run the real thing; read the real summary;
bet=1000 = the chunk `_bet`, the M279 ×1000 inflation-trap guard).

Inject-bug → RED → revert → GREEN (TestInjectBugProof) — ALL injections go into a
TEMP COPY of M78's OWN manifest (the committed manifest is NEVER touched; no shared
plugin or other machine's file is mutated):
  - drop the `signature` array → the signature_audit extractor produces no output →
    structure_drift flips ok → "unaudited" (audited_rounds → 0). RED, auto-reverts.
  - add a phantom DECLARED ST=99 that never appears in the data →
    structure_drift.declared_sts_absent = ['99']. RED, auto-reverts.
  - add a `crazy_reel` DIMENSION block to ST1 → DIMENSION_ANALYSES attaches
    nudge_dynamics → it LEAKS into M78's report. The non-leak assertion goes RED.
    Auto-reverts. (Proves the non-leak test actually catches a wrongful attach.)
Each inject-bug was run manually during authoring (the RED was observed on the real
chunks before commit); the GREEN resumes from the un-patched module-scoped fixture.
"""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import pytest

# Repo root: tests/backend/<file> → parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_M78_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M78" / "mode_1"
_M78_MANIFEST = _REPO_ROOT / "configs" / "machine_manifests" / "M78.json"
_MANIFESTS_ROOT = _REPO_ROOT / "configs" / "machine_manifests"

# Positive-control machines (their feature plugins ARE real + DO fire on them).
_M104_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M104" / "mode_1"  # lock_respin_dynamics
_M63_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M63" / "mode_1"    # nudge_dynamics
_M44_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M44" / "mode_1"    # minigame_dynamics

# The bet M78 was sampled at (cost==bet==1000 per paid spin — W1 / chunk `_bet`).
# The report is value-agnostic; bet only feeds sampling.bet, which the frontend
# divides every "× bet" column by — so passing the WRONG bet (default 1) renders
# multiplier columns ×1000-inflated (the M279 trap). We assert the bet is correct.
_BET = 1000

# The sole SpinType (fixed by the manifest / rawdata protocol — NOT a value drift).
_ST_PAID = 1

# Every fleet feature plugin keyed on a role / play / dimension. NONE may fire on
# M78 (its ST is paid_spin / Normal with no DIMENSION key → none attach).
_FEATURE_PLUGINS = (
    "minigame_dynamics",       # PLAY WinMiniGame (M43/M44)
    "wheel_dynamics",          # PLAY Wheel (M279)
    "lock_respin_dynamics",    # PLAY LockSymbolSpin (M104)
    "respin_dynamics",         # ROLE respin (M43/M279)
    "freespin_dynamics",       # ROLE freespin / hold_respin (M275/M278)
    "topdollar_choice",        # ROLE player_choice (M15)
    "nudge_dynamics",          # DIMENSION crazy_reel (M63)
)

# Expected top-level keys (frontend contract — same current schema as M15/M279).
# M78 has no player_choice role, so NO top-level topdollar_choice. collect_mechanic
# lives at TOP-LEVEL (not under player_impact). Superset check, never equality.
_EXPECTED_TOP_KEYS = frozenset({
    "report_id", "run_id", "machine", "mode",
    "config_md5", "code_md5",
    "analyzer_version", "effective_analyzer_version", "effective_analyzer_version_error",
    "output_all_robots_result",
    "sampling", "rtp",
    "player_impact", "upstream_analysis",
    "collect_mechanic",
    "guideline_assessment", "guideline_comparison",
    "rtp_integrity_check", "structure_drift",
    "storage",
})

# Expected player_impact sub-keys — the standard generic-substrate set ONLY (M78
# adds no mechanic section). Superset check, never equality.
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

# RETURN_BUCKET label → numeric [lo, hi) range for the bet-sanity check. A bucket's
# avg_return_x_in_bucket must land inside its own label band; a ×1000 inflation
# (wrong bet) would shove every value far above its band. (lo, hi=None means open.)
_BUCKET_RANGE = {
    "loss": (0.0, 0.0),
    "gt0_lt1": (0.0, 1.0),
    "ge1_lt5": (1.0, 5.0),
    "ge5_lt10": (5.0, 10.0),
    "ge10_lt20": (10.0, 20.0),
    "ge20_lt50": (20.0, 50.0),
    "ge50_lt100": (50.0, 100.0),
    "ge100_lt300": (100.0, 300.0),
    "ge300_lt500": (300.0, 500.0),
    "ge500": (500.0, None),
}


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


def _generate(machine_id: str, chunk_dir: Path, out_dir, **kw):
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    return generate_report_from_chunks(
        machine_id, 1,
        chunk_dir=chunk_dir,
        output_dir=Path(out_dir),
        bet=_BET,
        **kw,
    )


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m78_summary():
    if not _has_chunks(_M78_CHUNK_DIR):
        pytest.skip("M78 cached chunks not present")
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = _generate("M78", _M78_CHUNK_DIR, tmpdir)
        assert (Path(tmpdir) / "player_impact_summary.json").exists(), (
            "write_summary_json must produce player_impact_summary.json"
        )
        yield summary


@pytest.fixture(scope="module")
def m78_player_impact(m78_summary):
    return m78_summary["player_impact"]


@pytest.fixture(scope="module")
def m78_manifest():
    if not _M78_MANIFEST.exists():
        pytest.skip("M78 manifest not present")
    return json.loads(_M78_MANIFEST.read_text(encoding="utf-8"))


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


def _all_payid_rows(player_impact) -> list[dict]:
    """Every per-ST pay-id row from payouts_by_spin_type (flattened)."""
    out: list[dict] = []
    pbst = player_impact.get("payouts_by_spin_type") or {}
    for rows in pbst.values():
        out.extend(rows)
    return out


# ---------------------------------------------------------------------------
# 1. CORRECTNESS GATE — integrity passes natively; no fallback bucket.
#    VALUE-AGNOSTIC: structure/flags only, no RTP number.
# ---------------------------------------------------------------------------

class TestCorrectnessGate:
    def test_report_generates_with_machine_and_mode(self, m78_summary):
        assert m78_summary["machine"] == "M78"
        assert m78_summary["mode"] == 1
        assert m78_summary["sampling"]["chunks"] > 0
        assert m78_summary["sampling"]["total_spins"] > 0
        # No emit-loop / extract errors surfaced (feedback_no_silent_swallow.md).
        assert not m78_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m78_summary.get('feature_errors')}"
        )

    def test_rtp_integrity_passes(self, m78_summary):
        """rtp_integrity_check.passed must be True (sum(payid)==total, no fallback,
        anchors hit). NO RTP number is asserted."""
        ric = m78_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M78 mode 1. "
            f"Got passed={ric.get('passed')}, message={ric.get('summary_message', 'N/A')}."
        )

    def test_layer1_sum_invariant_holds(self, m78_summary):
        """L1 (value-agnostic): sum(pay_id win) == our_total_win — no orphan/double-count."""
        ric = m78_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant broken: {ric.get('layer1_error')}"
        )

    def test_layer3_anchors_ok(self, m78_summary):
        """L3 (value-agnostic): the declared paid-ST anchor (paid_st=[1]) is hit."""
        ric = m78_summary.get("rtp_integrity_check", {})
        assert ric.get("layer3_anchors_ok") is True, (
            f"Layer-3 anchors missing: {ric.get('layer3_missing_anchors')}"
        )

    def test_no_fallback_bucket_native(self, m78_summary):
        """The attribution closes NATIVELY (every win carries a real PayoutIdToWinAmount
        pay-id; wins_with_empty_payid==0): NO _unattributed_*/_other Layer-2 fallback
        bucket and NO SynthesizePayIdRule. 'share == 0' = the bucket is absent."""
        ric = m78_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}."
        )
        assert not (ric.get("layer2_fallback_buckets_found") or []), (
            f"M78 must have ZERO fallback buckets; got {ric.get('layer2_fallback_buckets_found')}"
        )
        # And no _unattributed_*/_other/_misc/_default pid leaked anywhere we read.
        pids = _payout_ids(m78_summary)
        bad = [p for p in pids if p.startswith(("_unattributed", "_other", "_misc", "_default"))]
        assert not bad, f"a fallback pid leaked into payout_ids_top20: {bad}"
        # Likewise across the per-ST payout breakdown.
        bad2 = [
            str(r.get("payout_id", ""))
            for r in _all_payid_rows(m78_summary["player_impact"])
            if str(r.get("payout_id", "")).startswith(
                ("_unattributed", "_other", "_misc", "_default"))
        ]
        assert not bad2, f"a fallback pid leaked into payouts_by_spin_type: {bad2}"


# ---------------------------------------------------------------------------
# 2. THE SINGLE SPINTYPE — correct role/play, present in the report.
#    role/play come from the manifest (the source of truth, feedback_no_hardcode).
# ---------------------------------------------------------------------------

class TestSingleSpinType:
    def test_manifest_declares_st1_paid_spin_normal(self, m78_manifest):
        """The manifest is the source of truth: ST1 role=paid_spin / play=Normal,
        economy WinCredits/real, and exactly ONE SpinType (a single-ST machine)."""
        st = m78_manifest["spin_types"]
        assert list(st.keys()) == [str(_ST_PAID)], (
            f"M78 is a single-SpinType machine; got STs {list(st.keys())}"
        )
        assert st[str(_ST_PAID)]["role"] == "paid_spin"
        assert st[str(_ST_PAID)]["play"] == "Normal"
        econ = st[str(_ST_PAID)]["economy"]
        assert econ["win_field"] == "WinCredits"
        assert econ["kind"] == "real", (
            "ST1 settles a REAL in-place win (not a preview) — contrast M15 ST14"
        )

    def test_no_round_win_rule_or_trigger(self, m78_manifest):
        """No SynthesizePayIdRule (attribution closes natively, §3) and no
        bonus/feature trigger (M78 has no choice/freespin/collect/wheel/minigame)."""
        assert "round_win_rule" not in m78_manifest, (
            "M78 needs NO round_win_rule — every win carries a native pay-id"
        )
        assert m78_manifest.get("trigger") is None, (
            "M78 has no feature trigger; trigger must be null"
        )

    def test_report_contains_st1(self, m78_player_impact):
        """The real report's per-ST breakdown carries exactly ST=1 (the sole event)."""
        sts = _stb_spin_types(m78_player_impact)
        assert sts == {_ST_PAID}, (
            f"M78 spin_type_breakdown must be exactly {{{_ST_PAID}}}; got {sorted(sts)}"
        )

    def test_per_st_plugins_keyed_on_st1(self, m78_player_impact):
        """The PER_SPINTYPE plugins resolved ST=1 (key 'ST1_paid'): payouts /
        outcomes / rtp_buckets all carry the ST=1 bucket and ONLY it."""
        for plugin in ("payouts_by_spin_type", "spin_type_outcomes", "spin_type_rtp_buckets"):
            section = m78_player_impact.get(plugin)
            assert isinstance(section, dict) and section, f"{plugin} empty/missing"
            assert list(section.keys()) == ["ST1_paid"], (
                f"{plugin} must carry exactly the ST1_paid bucket; got {list(section.keys())}"
            )


# ---------------------------------------------------------------------------
# 3. SCHEMA / FRONTEND-CONTRACT keys present.
# ---------------------------------------------------------------------------

class TestSchema:
    def test_top_level_keys_superset(self, m78_summary):
        missing = _EXPECTED_TOP_KEYS - set(m78_summary.keys())
        assert not missing, f"Expected top-level keys absent: {sorted(missing)}"

    def test_player_impact_keys_superset(self, m78_player_impact):
        missing = _EXPECTED_PI_KEYS - set(m78_player_impact.keys())
        assert not missing, f"Expected player_impact keys absent: {sorted(missing)}"

    def test_rtp_integrity_check_has_layer_fields(self, m78_summary):
        ric = m78_summary["rtp_integrity_check"]
        for field in ("passed", "layer1_invariant_ok", "layer2_no_fallback_buckets_ok",
                      "layer3_anchors_ok", "summary_message"):
            assert field in ric, f"rtp_integrity_check missing field: {field}"


# ---------------------------------------------------------------------------
# 4. ATTRIBUTION — native PayoutIdToWinAmount space; parity holds; no synthesis.
#    VALUE-AGNOSTIC: parity / structure, never an RTP number.
# ---------------------------------------------------------------------------

class TestAttribution:
    def test_payid_parity_sum_equals_rtp(self, m78_summary):
        """Aggregator parity (feedback_aggregator_parity_invariant): the per-pay-id
        rtp_contribution_pp must sum to the summary RTP (different view, same total).
        We compare the two AGGREGATES to each other — never pin either value."""
        pi = m78_summary["player_impact"]
        payid_sum = sum(
            float(r.get("rtp_contribution_pp", 0.0))
            for r in _all_payid_rows(pi)
        )
        rtp = float(m78_summary["rtp"]["point_pct"])
        assert payid_sum == pytest.approx(rtp, abs=1e-3), (
            f"Σ(pay-id rtp_pp)={payid_sum} must equal summary rtp={rtp} (parity)"
        )

    def test_native_payids_present_no_synthetic(self, m78_player_impact):
        """The attribution dimension is the machine's OWN symbol-line pay-id space:
        the pay-ids must be NATIVE integer-string symbol ids (e.g. '1'..'7','101',
        '105'), NOT a synthesized 'stN' label (no SynthesizePayIdRule on M78)."""
        rows = _all_payid_rows(m78_player_impact)
        assert rows, "payouts_by_spin_type must carry pay-id rows"
        pids = [str(r.get("payout_id", "")) for r in rows]
        # No synthesized settlement label (st2 / stN) — there is no no-payid ST.
        assert not any(p.startswith("st") for p in pids), (
            f"a synthesized 'stN' pid leaked (M78 needs no synthesis); got {pids}"
        )
        # The native ids are integer-decodable symbol-line keys.
        assert all(p.lstrip("-").isdigit() for p in pids), (
            f"all M78 pay-ids must be native integer symbol-line keys; got {pids}"
        )

    def test_no_double_count_preview_zero(self, m78_summary):
        """No preview / no double-count: ST=1 settles its OWN real win, so L1
        (sum payid == our_total) holds AND session conservation is OK (no preview ST
        contributing phantom win). A preview ST would break conservation; M78 has none."""
        ric = m78_summary["rtp_integrity_check"]
        assert ric.get("layer1_invariant_ok") is True
        # session_conservation: session_win_sum == total_win (no orphan/preview leak).
        assert ric.get("session_conservation_ok") is True, (
            f"session conservation broken (possible double-count/preview leak): "
            f"{ric.get('session_conservation_notes')}"
        )


# ---------------------------------------------------------------------------
# 5. BET-SANITY + structure audit — the M279 ×1000-trap guard (value-agnostic).
# ---------------------------------------------------------------------------

class TestBetSanityAndAudit:
    def test_sampling_bet_is_chunk_bet_not_one(self, m78_summary):
        """The report was generated with bet==chunk `_bet`==1000 (NOT the engine
        default 1). sampling.bet feeds the frontend's "× bet" divisor — bet=1 would
        render every multiplier column ×1000-inflated (the M279 trap). We assert the
        bet is correct; this is the BACKEND half of the guard (the rendered values
        need the gate-7 Playwright check — see Gaps)."""
        bet = m78_summary["sampling"].get("bet")
        assert bet == _BET, (
            f"sampling.bet must be the chunk _bet ({_BET}); got {bet}. "
            f"bet=1 → the frontend renders multiplier columns ×1000-inflated (M279 trap)."
        )
        assert bet != 1, "bet must NOT be the engine default 1 (the ×1000 inflation trap)"

    def test_bucket_avg_return_within_label_band(self, m78_player_impact):
        """VALUE-AGNOSTIC sanity: each multiplier bucket's avg_return_x_in_bucket lands
        INSIDE its own label band (e.g. ge5_lt10 → [5,10)). A wrong-scale (×1000) or
        mis-decoded multiplier would shove values far outside their band. We assert
        membership in the band, NOT any specific multiplier."""
        srb = m78_player_impact["spin_type_rtp_buckets"]["ST1_paid"]
        checked = 0
        for row in srb:
            label = row.get("bucket")
            rng = _BUCKET_RANGE.get(label)
            if rng is None or row.get("spin_count", 0) == 0:
                continue
            avg = row.get("avg_return_x_in_bucket")
            if avg is None or label == "loss":
                continue
            lo, hi = rng
            assert avg >= lo - 1e-6, (
                f"bucket {label}: avg_return_x {avg} below band floor {lo} (scale bug?)"
            )
            if hi is not None:
                assert avg < hi + 1e-6, (
                    f"bucket {label}: avg_return_x {avg} above band ceiling {hi} "
                    f"(×1000 inflation / mis-decode?)"
                )
            checked += 1
        assert checked > 0, "at least one populated multiplier bucket must be checked"

    def test_structure_drift_audited_ok(self, m78_summary):
        """The `signature` declaration turned on the signature_audit extractor →
        structure_drift AUDITS (status 'ok', audited_rounds>0), NOT 'unaudited'. No
        undeclared ST, no declared-but-absent ST."""
        sd = m78_summary["structure_drift"]
        assert sd.get("status") == "ok", (
            f"structure_drift must be 'ok' (signature_audit active); got {sd.get('status')} "
            f"reason={sd.get('reason')}"
        )
        assert sd.get("audited_rounds", 0) > 0, (
            "signature_audit must have audited rounds (status would be 'unaudited' if not)"
        )
        assert not sd.get("undeclared_sts"), f"undeclared STs: {sd.get('undeclared_sts')}"
        assert not sd.get("declared_sts_absent"), (
            f"declared STs absent from data: {sd.get('declared_sts_absent')}"
        )


# ---------------------------------------------------------------------------
# 6. NO NEW PLUGIN — M78's derived analysis set is the PURE generic substrate.
#    The absent-mechanic CROSS_CUTTING plugins honestly report not-applicable.
# ---------------------------------------------------------------------------

class TestNoNewPlugin:
    def test_derived_set_is_pure_generic(self, m78_manifest):
        """derive_analyses(M78) == CROSS_CUTTING + PER_SPINTYPE EXACTLY — no
        role/play/dimension feature plugin attaches (paid_spin ∉ ROLE_ANALYSES,
        Normal ∉ PLAY_ANALYSES, no DIMENSION_ANALYSES key on the ST)."""
        from fresh_slotlab.analyzer.machine_spec import (
            derive_analyses, CROSS_CUTTING, PER_SPINTYPE,
        )
        derived = set(derive_analyses(m78_manifest))
        expected = set(CROSS_CUTTING) | set(PER_SPINTYPE)
        assert derived == expected, (
            f"M78 derived analyses must be the PURE generic set. "
            f"unexpected extras: {sorted(derived - expected)}; "
            f"missing: {sorted(expected - derived)}"
        )
        # No feature plugin is anywhere in the derived set.
        leaked = [p for p in _FEATURE_PLUGINS if p in derived]
        assert not leaked, f"feature plugin(s) wrongly in M78's derived set: {leaked}"

    def test_absent_mechanics_reported_honestly(self, m78_summary):
        """The CROSS_CUTTING mechanic plugins run but HONESTLY report inapplicable
        (feedback_invariant_with_fallback_hides_drift — absent ≠ silently ok):
        collect_mechanic.applicable False, bonus_chain_dynamics.applicable False."""
        cm = m78_summary.get("collect_mechanic")
        assert isinstance(cm, dict) and cm.get("applicable") is False, (
            f"collect_mechanic must be present + applicable:False on M78; got {cm}"
        )
        bcd = m78_summary["player_impact"].get("bonus_chain_dynamics")
        assert isinstance(bcd, dict) and bcd.get("applicable") is False, (
            f"bonus_chain_dynamics must be present + applicable:False on M78; got {bcd}"
        )


# ---------------------------------------------------------------------------
# 7. NON-LEAK — no fleet feature plugin fires on M78; positive controls confirm
#    those plugins ARE real and DO fire on their declaring machines.
# ---------------------------------------------------------------------------

class TestNonLeak:
    def test_m78_report_has_no_feature_plugin(self, m78_player_impact, m78_summary):
        """The CONVERSE non-leak: NONE of the role/play/dimension feature plugins is
        in M78's report (not even applicable:False — they are not in its derived set
        at all). This is the same lock test_m15_has_no_minigame_dynamics uses."""
        for plugin in _FEATURE_PLUGINS:
            assert plugin not in m78_player_impact, (
                f"{plugin} LEAKED into M78's player_impact — M78's ST is "
                f"paid_spin/Normal with no DIMENSION key; nothing should attach it."
            )
            # collect_mechanic is the only top-level mechanic key; feature plugins
            # must not appear at the top level either.
            assert plugin not in m78_summary, (
                f"{plugin} LEAKED into M78's top-level summary"
            )

    @pytest.fixture(scope="class")
    def m104_pi(self):
        if not _has_chunks(_M104_CHUNK_DIR):
            pytest.skip("M104 cached chunks not present")
        with tempfile.TemporaryDirectory() as tmp:
            return _generate("M104", _M104_CHUNK_DIR, tmp)["player_impact"]

    @pytest.fixture(scope="class")
    def m63_pi(self):
        if not _has_chunks(_M63_CHUNK_DIR):
            pytest.skip("M63 cached chunks not present")
        with tempfile.TemporaryDirectory() as tmp:
            return _generate("M63", _M63_CHUNK_DIR, tmp)["player_impact"]

    @pytest.fixture(scope="class")
    def m44_pi(self):
        if not _has_chunks(_M44_CHUNK_DIR):
            pytest.skip("M44 cached chunks not present")
        with tempfile.TemporaryDirectory() as tmp:
            return _generate("M44", _M44_CHUNK_DIR, tmp)["player_impact"]

    def test_positive_control_m104_has_lock_respin(self, m104_pi):
        """lock_respin_dynamics IS real and DOES fire on M104 (LockSymbolSpin play) —
        so its ABSENCE on M78 is meaningful, not vacuous. AND it does NOT leak onto M78."""
        assert "lock_respin_dynamics" in m104_pi, (
            "lock_respin_dynamics must fire on its declaring machine M104"
        )

    def test_positive_control_m63_has_nudge(self, m63_pi):
        """nudge_dynamics IS real and DOES fire on M63 (crazy_reel dimension)."""
        assert "nudge_dynamics" in m63_pi, (
            "nudge_dynamics must fire on its declaring machine M63"
        )

    def test_positive_control_m44_has_minigame(self, m44_pi):
        """minigame_dynamics IS real and DOES fire on M44 (WinMiniGame play)."""
        assert "minigame_dynamics" in m44_pi, (
            "minigame_dynamics must fire on its declaring machine M44"
        )

    def test_m78_distinct_from_controls(self, m78_player_impact):
        """Cross-machine: the M104/M63/M44 plugins are absent from M78 specifically
        (the play/dimension scoping held — feedback_no_machine_family_concept: the
        only legal cross-machine relation is a mechanism, and M78 shares none)."""
        for plugin in ("lock_respin_dynamics", "nudge_dynamics", "minigame_dynamics"):
            assert plugin not in m78_player_impact, (
                f"{plugin} (a control machine's mechanic) must NOT be on M78"
            )


# ---------------------------------------------------------------------------
# INJECT-BUG PROOF — break each safety claim → RED → (auto-revert) → GREEN.
#
# Every injection writes a TEMP COPY of M78's OWN manifest into a throwaway
# manifests_root; the committed configs/machine_manifests/M78.json is NEVER
# touched, and no shared plugin / other machine's file is mutated.
#
# Claim A: the `signature` array turns on signature_audit → structure_drift OK.
# Claim B: every DECLARED ST is present in the data (declared_sts_absent empty).
# Claim C: the non-leak (no feature plugin on M78) — a wrongful DIMENSION block
#          would attach nudge_dynamics; the non-leak assertion must catch it.
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def _gen_with_patched_manifest(self, patch_fn):
        """Write a patched COPY of M78.json to a temp manifests_root, regenerate,
        and return the summary. The committed manifest is never modified."""
        manifest = json.loads(_M78_MANIFEST.read_text(encoding="utf-8"))
        patched = copy.deepcopy(manifest)
        patch_fn(patched)
        with tempfile.TemporaryDirectory() as tmp_manifests, \
                tempfile.TemporaryDirectory() as tmp_out:
            (Path(tmp_manifests) / "M78.json").write_text(
                json.dumps(patched), encoding="utf-8"
            )
            return _generate(
                "M78", _M78_CHUNK_DIR, tmp_out, manifests_root=tmp_manifests,
            )

    def test_inject_drop_signature_flips_to_unaudited(self):
        """INJECT (Claim A): drop the ST1 `signature` array → the signature_audit
        extractor produces no output → structure_drift flips ok → 'unaudited'
        (audited_rounds → 0). RED. The committed manifest is never touched."""
        if not _has_chunks(_M78_CHUNK_DIR):
            pytest.skip("M78 cached chunks not present")

        def _drop_sig(m):
            del m["spin_types"]["1"]["signature"]  # BUG: structure_drift goes blind

        summary = self._gen_with_patched_manifest(_drop_sig)
        sd = summary["structure_drift"]
        # RED 1 — status is no longer the audited 'ok'.
        assert sd.get("status") == "unaudited", (
            f"inject-bug: without the signature, structure_drift must flip to "
            f"'unaudited'; got status={sd.get('status')}"
        )
        # RED 2 — nothing was audited.
        assert sd.get("audited_rounds", -1) == 0, (
            f"inject-bug: audited_rounds must be 0 with no signature_audit output; "
            f"got {sd.get('audited_rounds')}"
        )
        # Isolation: attribution is independent — RTP integrity still passes.
        assert summary["rtp_integrity_check"].get("passed") is True, (
            "inject-bug: dropping the audit signature must NOT break RTP integrity"
        )
        # temp manifests_root removed — the committed manifest was never modified.

    def test_inject_phantom_declared_st_surfaces_absent(self):
        """INJECT (Claim B): add a phantom DECLARED ST=99 that never appears in the
        data → structure_drift.declared_sts_absent surfaces ['99']. RED. The
        committed manifest is never touched."""
        if not _has_chunks(_M78_CHUNK_DIR):
            pytest.skip("M78 cached chunks not present")

        def _add_phantom(m):
            m["spin_types"]["99"] = copy.deepcopy(m["spin_types"]["1"])  # BUG: never in data

        summary = self._gen_with_patched_manifest(_add_phantom)
        sd = summary["structure_drift"]
        # RED — the phantom ST is flagged as declared-but-absent.
        absent = sd.get("declared_sts_absent") or []
        assert "99" in absent, (
            f"inject-bug: the phantom declared ST=99 must surface in "
            f"declared_sts_absent; got {absent}"
        )
        # Isolation: the real ST=1 still parses + integrity holds.
        assert summary["rtp_integrity_check"].get("passed") is True

    def test_inject_dimension_block_leaks_nudge_dynamics(self):
        """INJECT (Claim C — the non-leak): add a `crazy_reel` DIMENSION block to ST1
        → DIMENSION_ANALYSES attaches nudge_dynamics → it LEAKS into M78's report.
        The non-leak assertion (`nudge_dynamics not in player_impact`) goes RED,
        proving that test actually catches a wrongful attach. The committed manifest
        is never touched (the temp copy carries the bogus block)."""
        if not _has_chunks(_M78_CHUNK_DIR):
            pytest.skip("M78 cached chunks not present")

        def _add_crazy_reel(m):
            # BUG: declare the crazy_reel dimension M78 does NOT have.
            m["spin_types"]["1"]["crazy_reel"] = {"symbols": ["crazy_up", "crazy", "crazy_down"]}

        summary = self._gen_with_patched_manifest(_add_crazy_reel)
        pi = summary["player_impact"]
        # RED — nudge_dynamics is now present (the exact condition the non-leak
        # test asserts must NOT hold for the real M78).
        assert "nudge_dynamics" in pi, (
            "inject-bug: declaring crazy_reel must attach nudge_dynamics (so the "
            "non-leak test would catch a real wrongful attach); got keys "
            f"{sorted(k for k in pi if 'dynamic' in k)}"
        )

    def test_green_resumes_after_revert(self, m78_summary):
        """After every inject-bug (all temp-manifest copies removed), the real
        un-patched report is GREEN: integrity passes, no fallback, structure_drift
        audited ok, and NO feature plugin leaked. (m78_summary is built from the
        COMMITTED manifest, never patched.)"""
        ric = m78_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert ric.get("layer2_no_fallback_buckets_ok") is True
        assert not (ric.get("layer2_fallback_buckets_found") or [])
        assert m78_summary["structure_drift"].get("status") == "ok"
        assert m78_summary["structure_drift"].get("audited_rounds", 0) > 0
        for plugin in _FEATURE_PLUGINS:
            assert plugin not in m78_summary["player_impact"]
