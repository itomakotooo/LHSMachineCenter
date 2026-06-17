"""M34 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This file asserts STRUCTURE / ATTRIBUTION / NON-LEAK / HONESTY invariants,
NEVER an RTP value or range. M34's numbers (RTP, hit-rates, per-payid shares)
change on re-sample / re-tune / upstream drift; pinning ANY of them would be a
brittle false alarm (charter permanent invariant 1). The only hard constants
asserted are STRUCTURAL identifiers fixed by the manifest / protocol (the single
SpinType id 1, role paid_spin, play Normal, the 15-payid cardinality observed in
the data — and even that as ">= 1 / matches the live count", never pinned to 15).

What M34 shipped (session_artifacts/_onboard/M34/03_design.md):
  - configs/machine_manifests/M34.json — a SINGLE-SpinType manifest: ST1 =
    paid_spin / Normal, economy real (WinCredits), natural PayoutIdToWinAmount
    payid (sum==WinCredits 0/40,000 mismatches → the invariant closes natively).
  - NO new plugin, NO new frontend per-ST dimension, NO KNOWN_ROLES extension,
    NO SynthesizePayIdRule / round_win_rule. STRICT-REUSE of the shared
    paid_spin/Normal per-ST + cross-cutting plugin set (== M15 ST1 / M43 ST1).

The W3 acceptance bar (03_design.md §7) is the spec these tests encode:
  1. ST1 renders via the data-driven _stDim* renderers (summary row +
     spin_type_rtp_buckets + payouts_by_spin_type all present for ST1).
  2. rtp_integrity_check.passed == True; L2 fallback buckets == []; no
     _unattributed_* / _other key anywhere.
  3. Σ payid rtp_pp == summary RTP; Σ payid hits == win_rounds.
  4. upstream_feature_breakdown shows exactly one feature Normal, fire_rate 1.0.
  5. NO respin_dynamics / minigame_dynamics / wheel_dynamics / freespin_dynamics /
     topdollar_choice key (single-ST machine; none of those roles/plays present).

The whole test runs the REAL engine on the real cached chunk at rawdata/M34/mode_1
(charter invariant 3: run the real thing, pass bet=chunk _bet, read the real
summary). The inject-bug proofs edit ONLY M34's OWN manifest, byte-restore it
immediately, and the cross-machine non-leak test compares M34's derived analysis
set against role/play-keyed siblings (M275 freespin_dynamics, M283 wheel_dynamics).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M34_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M34" / "mode_1"
_M34_MANIFEST = _REPO_ROOT / "configs" / "machine_manifests" / "M34.json"
_MANIFESTS_ROOT = _REPO_ROOT / "configs" / "machine_manifests"

# The bet used during M34 sampling (cost=1000 per paid spin; chunk _bet == 1000).
# The report is value-agnostic; bet only affects coin totals, which this test
# never asserts. Passing it correctly avoids the M279 1000x multiplier trap (bet
# must land in sampling.bet) — but we never assert a multiplier VALUE.
_BET = 1000

# Structural identifiers fixed by the manifest / protocol (NOT values).
_ST1 = 1
_ST1_KEY = "ST1_paid"  # the per-ST dimension dict key the engine emits for ST1.

# Role/play-keyed analyses that exist on OTHER machines and must NEVER fire on
# M34 (single paid_spin, no respin/freespin/wheel/minigame/choice mechanic).
_FORBIDDEN_MECHANIC_ANALYSES = [
    "respin_dynamics",
    "minigame_dynamics",
    "wheel_dynamics",
    "freespin_dynamics",
    "topdollar_choice",
    "hold_respin_dynamics",
    "nudge_dynamics",
    "lock_respin_dynamics",
    "crazy_reel_dim",
]


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m34_summary():
    if not _has_chunks(_M34_CHUNK_DIR):
        pytest.skip("M34 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            "M34", 1,
            chunk_dir=_M34_CHUNK_DIR,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists(), (
            "write_summary_json must produce player_impact_summary.json"
        )
        yield summary


@pytest.fixture(scope="module")
def m34_pi(m34_summary):
    pi = m34_summary.get("player_impact")
    assert isinstance(pi, dict), "summary.player_impact missing"
    return pi


@pytest.fixture(scope="module")
def m34_manifest():
    if not _M34_MANIFEST.exists():
        pytest.skip("M34 manifest not present")
    return json.loads(_M34_MANIFEST.read_text(encoding="utf-8"))


def _st1_payouts(pi) -> list[dict]:
    pbs = pi.get("payouts_by_spin_type") or {}
    rows = pbs.get(_ST1_KEY)
    assert isinstance(rows, list), (
        f"payouts_by_spin_type[{_ST1_KEY!r}] must be a list; got {type(rows)} "
        f"(keys present: {sorted(pbs.keys())})"
    )
    return rows


def _payout_ids_top20(summary) -> list[str]:
    return [
        str(r.get("payout_id", ""))
        for r in summary["player_impact"].get("payout_ids_top20", [])
    ]


# ---------------------------------------------------------------------------
# 0. Smoke — report generates, identity correct, no feature errors.
# ---------------------------------------------------------------------------

class TestReportGenerates:
    def test_machine_and_mode(self, m34_summary):
        assert m34_summary["machine"] == "M34"
        assert m34_summary["mode"] == 1
        assert m34_summary["sampling"]["chunks"] > 0
        assert m34_summary["sampling"]["total_spins"] > 0
        assert not m34_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m34_summary.get('feature_errors')}"
        )

    def test_bet_landed_in_sampling(self, m34_summary):
        """The M279 trap guard: bet must land in sampling.bet so the frontend's
        'x bet' columns are NOT 1000x inflated. We assert it landed (structure),
        never a resulting multiplier VALUE."""
        assert m34_summary["sampling"]["bet"] == _BET, (
            f"bet must propagate to sampling.bet (={_BET}); got "
            f"{m34_summary['sampling'].get('bet')} — the frontend would render "
            f"every 'x bet' column inflated otherwise"
        )


# ---------------------------------------------------------------------------
# 1. Manifest STRUCTURE — single ST1 paid_spin/Normal, NO new plugin/rule.
#    (Structural identifiers fixed by the design, not values.)
# ---------------------------------------------------------------------------

class TestManifestStructure:
    def test_single_spin_type_paid_normal(self, m34_manifest):
        st = m34_manifest["spin_types"]
        assert list(st.keys()) == [str(_ST1)], (
            f"M34 mode 1 is a SINGLE-SpinType machine; spin_types must be exactly "
            f"{{'1'}}, got {sorted(st.keys())}"
        )
        assert st[str(_ST1)]["role"] == "paid_spin", (
            "ST1 must be role paid_spin (the only protocol event is a paid base spin)"
        )
        assert st[str(_ST1)]["play"] == "Normal"
        assert st[str(_ST1)]["economy"]["win_field"] == "WinCredits"
        assert st[str(_ST1)]["economy"]["kind"] == "real", (
            "M34 settles same-round (real economy, no preview)"
        )

    def test_no_new_plugin_or_synthesis_keys(self, m34_manifest):
        """STRICT-REUSE: the manifest declares NO new plugin, NO round_win_rule,
        NO new-event extraction block. A regression that smuggled one in (e.g. a
        wheel_cells block, a trigger_paths dimension, a round_win_rule) would
        flip this — they are precisely what M34's design says it does NOT need."""
        # No machine-level new-plugin / synthesis declarations.
        for forbidden in ("new_plugins", "round_win_rule", "round_win_rules"):
            assert not m34_manifest.get(forbidden), (
                f"M34 must declare no {forbidden!r}; got {m34_manifest.get(forbidden)!r}"
            )
        # ST1 must not carry any per-event extraction block (no new dimension).
        st1 = m34_manifest["spin_types"][str(_ST1)]
        for ext_key in ("trigger_paths", "wheel_cells", "wheel_cell_map",
                        "extraction", "extract"):
            assert ext_key not in st1, (
                f"ST1 must declare no {ext_key!r} extraction block (STRICT-REUSE; "
                f"no new in-ST dimension)"
            )

    def test_trigger_has_no_feature_event(self, m34_manifest):
        """No feature trigger fires on M34 (contrast M15 pid 666). trigger.payout_id
        is null and trigger.opens is null — a structural single-base-game fact."""
        trg = m34_manifest.get("trigger") or {}
        assert trg.get("payout_id") is None, (
            f"M34 has no feature trigger; trigger.payout_id must be null, got "
            f"{trg.get('payout_id')!r}"
        )
        assert trg.get("opens") is None

    def test_out_of_engine_mechanics_empty(self, m34_manifest):
        """No declared out-of-engine mechanic (CurJackpotStoreWin is gate-8
        pending, recorded as present-but-zeroed; the manifest must NOT fabricate
        a mechanic)."""
        assert m34_manifest.get("out_of_engine_mechanics") == [], (
            "out_of_engine_mechanics must be [] (no fabricated mechanic); got "
            f"{m34_manifest.get('out_of_engine_mechanics')!r}"
        )

    def test_rtp_integrity_paid_st_is_st1_only(self, m34_manifest):
        ri = m34_manifest.get("rtp_integrity") or {}
        assert ri.get("paid_st") == [_ST1], (
            f"rtp_integrity.paid_st must be [{_ST1}] (ST1 is the only paid spin); "
            f"got {ri.get('paid_st')!r}"
        )


# ---------------------------------------------------------------------------
# 2. Derived analysis set — STRICT-REUSE: only CROSS_CUTTING + PER_SPINTYPE.
#    NO role/play-keyed mechanic analysis (this is the non-leak core).
# ---------------------------------------------------------------------------

def _derived_analysis_ids(machine_id: str) -> list[str]:
    from fresh_slotlab.analyzer.machine_spec import load_manifest, derive_analyses
    m = load_manifest(machine_id, _MANIFESTS_ROOT)
    return sorted(str(a) for a in derive_analyses(m))


class TestDerivedAnalysisSet:
    def test_no_role_or_play_keyed_mechanic_analysis(self):
        """STRUCTURAL: derive_analyses(M34) must contain none of the role/play-
        keyed mechanic analyses. M34 declares no respin/freespin/wheel/minigame/
        choice role-or-play, so none may be derived."""
        ids = _derived_analysis_ids("M34")
        leaked = [a for a in _FORBIDDEN_MECHANIC_ANALYSES if a in ids]
        assert leaked == [], (
            f"M34's derived analysis set leaked role/play-keyed mechanic "
            f"analyses {leaked}; M34 is a single paid_spin with no such mechanic. "
            f"Full set: {ids}"
        )

    def test_per_spintype_and_cross_cutting_present(self):
        """The reused set IS present — the strict-reuse verdict means M34 still
        gets the full paid_spin/Normal per-ST + cross-cutting analyses."""
        ids = set(_derived_analysis_ids("M34"))
        for expected in (
            "payouts_by_spin_type", "spin_type_outcomes",
            "spin_type_rtp_buckets", "reel_marginal_by_spin_type",
            "upstream_feature_breakdown", "machine_mechanics",
            "collect_mechanic", "bonus_chain_dynamics",
            "bankruptcy_simulation", "structure_drift", "multiplier_profile",
        ):
            assert expected in ids, (
                f"reused analysis {expected!r} must be derived for M34; got {sorted(ids)}"
            )


# ---------------------------------------------------------------------------
# 3. Frontend-contract keys + ST1 renders via the data-driven dimensions.
#    (Acceptance bar §7.1: ST1 has summary row + rtp_buckets + payouts rows.)
# ---------------------------------------------------------------------------

class TestFrontendContract:
    def test_player_impact_contract_keys_present(self, m34_pi):
        for key in (
            "spin_type_breakdown", "spin_type_outcomes",
            "spin_type_rtp_buckets", "payouts_by_spin_type",
            "reel_marginal_by_spin_type", "upstream_feature_breakdown",
            "machine_mechanics", "multiplier_profile",
            "payout_ids_top20", "volatility",
        ):
            assert key in m34_pi, (
                f"frontend-contract key {key!r} missing from player_impact "
                f"(keys: {sorted(m34_pi.keys())})"
            )

    def test_spin_type_breakdown_single_st1_row(self, m34_pi):
        stb = m34_pi["spin_type_breakdown"]
        assert isinstance(stb, list) and len(stb) == 1, (
            f"spin_type_breakdown must be a single-row list (single ST machine); "
            f"got len={len(stb) if isinstance(stb, list) else stb}"
        )
        row = stb[0]
        assert int(row["spin_type"]) == _ST1
        # The three data-driven _stDim* renderers fire iff these are present:
        assert "hit_rate" in row and "win_rounds" in row and "spins" in row
        assert 0.0 <= row["hit_rate"] <= 1.0, (
            f"hit_rate is a probability in [0,1]; got {row['hit_rate']}"
        )
        assert row["win_rounds"] >= 1, "M34 ST1 has winning rounds"
        assert row["spins"] >= 1

    def test_st1_renders_all_three_dimensions(self, m34_pi):
        """Acceptance §7.1: ST1's section renders fully (no new _stDim*) because
        it supplies a summary row + spin_type_rtp_buckets + payouts_by_spin_type
        rows. Assert all three keyed dimensions exist for ST1_paid."""
        for dim in ("spin_type_outcomes", "spin_type_rtp_buckets",
                    "payouts_by_spin_type"):
            d = m34_pi.get(dim)
            assert isinstance(d, dict) and _ST1_KEY in d, (
                f"per-ST dimension {dim!r} must carry the {_ST1_KEY!r} key for "
                f"ST1 to render; got keys {sorted((d or {}).keys())}"
            )
        # rtp_buckets must be non-empty (the win-band distribution drives F2/F3).
        srb = m34_pi["spin_type_rtp_buckets"][_ST1_KEY]
        assert srb, "spin_type_rtp_buckets[ST1] must be non-empty (win-band view)"


# ---------------------------------------------------------------------------
# 4. Attribution / integrity — natural payid closes; ZERO fallback bucket.
#    (Acceptance §7.2/§7.3.)
# ---------------------------------------------------------------------------

class TestAttributionIntegrity:
    def test_rtp_integrity_passes(self, m34_summary):
        ric = m34_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M34 mode 1; got "
            f"passed={ric.get('passed')}, message={ric.get('summary_message','N/A')}"
        )

    def test_layer1_sum_invariant_holds(self, m34_summary):
        ric = m34_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant (sum==our_total) broken: {ric.get('layer1_error')}"
        )

    def test_no_unattributed_fallback_bucket(self, m34_summary):
        """Headline value-agnostic guard: NO _unattributed_* / _other (Layer-2).
        M34's natural PayoutIdToWinAmount closes the invariant with no synthesis,
        so the fallback-bucket share must be exactly 0 (empty list)."""
        ric = m34_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}"
        )
        assert (ric.get("layer2_fallback_buckets_found") or []) == [], (
            f"fallback-bucket share must be 0 (empty); got "
            f"{ric.get('layer2_fallback_buckets_found')}"
        )

    def test_no_unattributed_or_other_key_anywhere(self, m34_summary, m34_pi):
        """No _unattributed_* / _other payid leaks into any rendered surface."""
        for pid in _payout_ids_top20(m34_summary):
            assert not pid.startswith("_unattributed"), (
                f"_unattributed_* pid leaked into payout_ids_top20: {pid}"
            )
            assert pid != "_other"
        for r in _st1_payouts(m34_pi):
            pid = str(r.get("payout_id", ""))
            assert not pid.startswith("_unattributed") and pid != "_other", (
                f"_unattributed_*/_other pid leaked into payouts_by_spin_type: {pid}"
            )

    def test_payid_rtp_sum_equals_summary_rtp(self, m34_summary, m34_pi):
        """Σ payid rtp_pp == summary RTP (the aggregator-parity invariant). The
        EQUALITY is asserted (structural), the RTP value itself is read from the
        live report, never pinned."""
        rows = _st1_payouts(m34_pi)
        summed = sum(float(r.get("rtp_contribution_pp", 0.0)) for r in rows)
        summary_rtp = float(m34_summary["rtp"]["point_pct"])
        assert abs(summed - summary_rtp) < 1e-3, (
            f"Σ payid rtp_pp ({summed}) must equal summary RTP ({summary_rtp}) "
            f"— aggregator-parity invariant (value read live, not pinned)"
        )

    def test_payid_hits_sum_equals_win_rounds(self, m34_pi):
        """Σ payid hits == win_rounds (every winning round attributed exactly once;
        no preview/no-payid double-count)."""
        rows = _st1_payouts(m34_pi)
        hits = sum(int(r.get("hit_count", 0)) for r in rows)
        win_rounds = int(m34_pi["spin_type_breakdown"][0]["win_rounds"])
        assert hits == win_rounds, (
            f"Σ payid hits ({hits}) must equal win_rounds ({win_rounds}) — no "
            f"win double-counted or dropped"
        )

    def test_session_conservation_ok(self, m34_summary):
        ric = m34_summary.get("rtp_integrity_check", {})
        assert ric.get("session_conservation_level") == "ok", (
            f"session_conservation_level must be 'ok' (real economy, exact "
            f"conservation); got {ric.get('session_conservation_level')}"
        )


# ---------------------------------------------------------------------------
# 5. Single-feature confirm — exactly one Normal feature, fire_rate 1.0.
#    (Acceptance §7.4.)
# ---------------------------------------------------------------------------

class TestSingleFeature:
    def test_exactly_one_normal_feature_fire_rate_one(self, m34_pi):
        ufb = m34_pi.get("upstream_feature_breakdown") or {}
        feats = ufb.get("features") or []
        assert isinstance(feats, list) and len(feats) == 1, (
            f"upstream_feature_breakdown must show exactly ONE feature (single "
            f"base game); got {len(feats)} features"
        )
        feat = feats[0]
        assert feat.get("feature_name") == "Normal", (
            f"the single feature must be 'Normal'; got {feat.get('feature_name')!r}"
        )
        assert abs(float(feat.get("fire_rate", 0.0)) - 1.0) < 1e-9, (
            f"Normal fire_rate must be 1.0 (fires on every round); got "
            f"{feat.get('fire_rate')}"
        )

    def test_free_spin_and_jackpot_not_applicable(self, m34_pi):
        mm = m34_pi.get("machine_mechanics") or {}
        assert (mm.get("free_spin") or {}).get("applicable") is False, (
            "M34 has no free spins; machine_mechanics.free_spin.applicable must be False"
        )
        assert (mm.get("jackpot") or {}).get("applicable") is False, (
            "M34 has no jackpot; machine_mechanics.jackpot.applicable must be False"
        )


# ---------------------------------------------------------------------------
# 6. Wild identity is captured at the per-combo level (F4/F5) — HONESTY.
#    Value-agnostic: assert the is_wild flag STRUCTURE exists, never a share.
# ---------------------------------------------------------------------------

class TestWildComboStructure:
    def test_symbol_combo_carries_is_wild_flag(self, m34_pi):
        """F4/F5: the wild identity is surfaced via the per-payid symbol_combo's
        per-combo is_wild flag (the available approximation; the labeled ladder
        is a flagged framework-team item). Assert the flag STRUCTURE exists and
        at least one Wild combo is detected — never its share/RTP value."""
        rows = _st1_payouts(m34_pi)
        assert rows, "M34 ST1 has payout rows"
        any_wild_combo = False
        for r in rows:
            sc = r.get("symbol_combo")
            if not isinstance(sc, dict):
                continue
            combos = sc.get("combos") or []
            for c in combos:
                assert "is_wild" in c, (
                    f"each symbol_combo combo must carry an is_wild flag (F4/F5 "
                    f"wild identity); got {c}"
                )
                if c.get("is_wild"):
                    any_wild_combo = True
        assert any_wild_combo, (
            "at least one payid combo must carry is_wild:true (M34's wild "
            "mechanic — Wildx2/Wildx3 appear in winning combos)"
        )

    def test_distinct_symbols_include_wild_variants(self, m34_pi):
        """The wild variants (Wildx2/Wildx3) appear in distinct_symbols of at
        least one payid (structure, not frequency)."""
        rows = _st1_payouts(m34_pi)
        seen_wild_symbol = False
        for r in rows:
            sc = r.get("symbol_combo")
            if isinstance(sc, dict):
                for sym in (sc.get("distinct_symbols") or []):
                    if str(sym).lower().startswith("wild"):
                        seen_wild_symbol = True
        assert seen_wild_symbol, (
            "a Wild* variant must appear in some payid's distinct_symbols"
        )


# ---------------------------------------------------------------------------
# 7. CROSS-MACHINE NON-LEAK — M34 must not fire a play/dimension-keyed analysis
#    that another machine introduces, and vice-versa those siblings' analyses
#    do NOT leak onto M34. Compares M34's derived set to role/play-keyed siblings.
# ---------------------------------------------------------------------------

class TestCrossMachineNonLeak:
    def test_sibling_role_play_analyses_do_not_fire_on_m34(self):
        """M275 declares a freespin role → derives freespin_dynamics; M283 declares
        a Wheel play → derives wheel_dynamics. M34 declares NEITHER, so neither
        analysis may appear in M34's derived set. This is the structural keying
        guarantee: a play/dimension-keyed analysis fires ONLY on the machine that
        declares the keying role/play."""
        m34_ids = set(_derived_analysis_ids("M34"))

        for sib, keyed in (("M275", "freespin_dynamics"),
                           ("M283", "wheel_dynamics")):
            sib_manifest = _MANIFESTS_ROOT / f"{sib}.json"
            if not sib_manifest.exists():
                continue
            sib_ids = set(_derived_analysis_ids(sib))
            # The sibling DOES derive its keyed analysis (sanity: the keying is real).
            assert keyed in sib_ids, (
                f"{sib} must derive {keyed!r} (its declared role/play); got {sorted(sib_ids)}"
            )
            # ... and M34 does NOT (the non-leak).
            assert keyed not in m34_ids, (
                f"NON-LEAK VIOLATION: {keyed!r} (a {sib}-keyed analysis) leaked "
                f"into M34's derived set {sorted(m34_ids)} — M34 declares no such "
                f"role/play"
            )

    def test_m34_summary_carries_no_sibling_mechanic_section(self, m34_summary):
        """End-to-end: the REAL M34 summary text contains none of the sibling
        mechanic section keys (a stronger check than the derived set — catches a
        plugin that emits its key unconditionally)."""
        txt = json.dumps(m34_summary)
        for key in _FORBIDDEN_MECHANIC_ANALYSES:
            assert f'"{key}"' not in txt, (
                f"NON-LEAK VIOLATION: sibling mechanic section {key!r} present in "
                f"M34's real summary"
            )


# ---------------------------------------------------------------------------
# INJECT-BUG PROOF — break each safety claim → RED → (byte-restore) → GREEN.
#
# Injections touch ONLY M34's OWN manifest (configs/machine_manifests/M34.json),
# read once / written back byte-identically in a try/finally so the file is
# restored even on failure. NEVER a shared plugin or another machine's file.
#
# Claim A (non-leak): if ST1's role were a mechanic role (respin), M34 WOULD
#   derive respin_dynamics → the non-leak test goes RED. Revert → GREEN.
# Claim B (single-ST structure): if a second spin_type were added, the
#   single-row spin_type_breakdown / single-ST manifest assertions go RED.
# Claim C (manifest honesty): if out_of_engine_mechanics were fabricated, the
#   empty-mechanics assertion goes RED.
# ---------------------------------------------------------------------------

class _ManifestInjector:
    """Read M34.json's exact bytes once; mutate the JSON; write; restore the
    ORIGINAL BYTES on exit (byte-identical, no formatting drift)."""

    def __init__(self):
        self._orig_bytes = _M34_MANIFEST.read_bytes()

    def write_mutated(self, mutate):
        data = json.loads(self._orig_bytes.decode("utf-8"))
        mutate(data)
        _M34_MANIFEST.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def restore(self):
        _M34_MANIFEST.write_bytes(self._orig_bytes)


@pytest.fixture
def manifest_injector():
    if not _M34_MANIFEST.exists():
        pytest.skip("M34 manifest not present")
    inj = _ManifestInjector()
    try:
        yield inj
    finally:
        inj.restore()  # byte-restore even if the test body raises.


class TestInjectBugProof:
    def test_inject_mechanic_role_makes_nonleak_red(self, manifest_injector):
        """INJECT (Claim A): flip ST1 role paid_spin -> respin. Assert M34 now
        DERIVES respin_dynamics — i.e. the non-leak guard would FAIL with the bug
        in place. Proves test_no_role_or_play_keyed_mechanic_analysis is real."""
        # Baseline (un-injected): respin_dynamics absent.
        assert "respin_dynamics" not in _derived_analysis_ids("M34")

        def _flip(data):
            data["spin_types"]["1"]["role"] = "respin"

        manifest_injector.write_mutated(_flip)
        injected_ids = _derived_analysis_ids("M34")
        assert "respin_dynamics" in injected_ids, (
            "inject-bug: with ST1 role=respin, M34 must derive respin_dynamics "
            "(this is the regression the non-leak test catches)"
        )
        # fixture restore() reverts the bytes -> GREEN resumes.

    def test_inject_second_spin_type_makes_single_st_red(self, manifest_injector):
        """INJECT (Claim B): add a spurious second spin_type. Assert the manifest
        now reports >1 spin_type — i.e. test_single_spin_type_paid_normal would
        FAIL. Proves the single-ST structural claim is real."""
        def _add_st(data):
            data["spin_types"]["99"] = {
                "role": "settlement", "play": "Bogus",
                "economy": {"win_field": "WinCredits", "kind": "real"},
                "signature": ["WinCredits"],
                "observed_fields": ["WinCredits"],
                "observed_field_presence": {"WinCredits": 1.0},
                "observed_fields_source": "INJECTED-BUG",
            }

        manifest_injector.write_mutated(_add_st)
        from fresh_slotlab.analyzer.machine_spec import load_manifest
        m = load_manifest("M34", _MANIFESTS_ROOT)
        assert len(m["spin_types"]) > 1, (
            "inject-bug: a second spin_type must make M34 no longer single-ST "
            "(the regression test_single_spin_type_paid_normal catches)"
        )
        assert set(m["spin_types"].keys()) != {"1"}

    def test_inject_fabricated_out_of_engine_mechanic_red(self, manifest_injector):
        """INJECT (Claim C): fabricate an out_of_engine_mechanic. Assert the
        manifest now carries a non-empty list — i.e. the honesty assertion
        test_out_of_engine_mechanics_empty would FAIL."""
        def _fab(data):
            data["out_of_engine_mechanics"] = ["FAKE_progressive_jackpot"]

        manifest_injector.write_mutated(_fab)
        reloaded = json.loads(_M34_MANIFEST.read_text(encoding="utf-8"))
        assert reloaded.get("out_of_engine_mechanics"), (
            "inject-bug: a fabricated mechanic must make out_of_engine_mechanics "
            "non-empty (the honesty test catches)"
        )

    def test_green_resumes_after_restore(self, m34_summary):
        """After all inject-bug fixtures restore the manifest bytes, the real
        (un-injected) report is GREEN: integrity passes, no fallback, single ST,
        no leaked mechanic analysis."""
        # The manifest bytes are restored by each injector fixture's finally.
        ric = m34_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert (ric.get("layer2_fallback_buckets_found") or []) == []
        ids = set(_derived_analysis_ids("M34"))
        assert not (set(_FORBIDDEN_MECHANIC_ANALYSES) & ids), (
            f"after restore, no mechanic analysis may be derived; got {sorted(ids)}"
        )
        assert list(json.loads(_M34_MANIFEST.read_text(encoding="utf-8"))
                    ["spin_types"].keys()) == ["1"]
