"""M275 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This test asserts STRUCTURE / FLAGS / INVARIANTS / RELATIONS, never an RTP value
or an observed count. M275's numbers (RTP 89.24, openers 908, 829/80 path split)
change on re-sample / re-tune / upstream-config drift, so pinning ANY of them
here would be a brittle false alarm (charter permanent invariant 1). The ONLY
hard numbers asserted are STRUCTURAL identifiers fixed by the manifest /
rawdata protocol (SpinType ids 140/126, the declared trigger-path labels, the
GTT discriminator vocabulary {0,2} the manifest maps).

What M275 added (session_artifacts/_onboard/M275/03_design.md):
  - configs/machine_manifests/M275.json — ST140 paid_spin/NormalCollectionSpin,
    ST126 freespin/NewFreespin + the declarative `trigger_paths` block
    (round_field discriminator GameplayTriggerType {0: scatter, 2: collect_peak},
    surface_as_unknown_path policy, trigger_anchor_walk fallback,
    additive_sessions multi-trigger policy).
  - fresh_slotlab/analyzer/features/freespin_dynamics.py — the granted-freespin
    session mechanic view (F1 cadence / F2 hot-board uplift + band overlays +
    payid mix / F6 trigger-path dimension; F3a/F4/F5 flagged parser_blind).
  - machine_spec.py: KNOWN_ROLES += {"freespin"};
    ROLE_ANALYSES["freespin"] = ("freespin_dynamics",) (ROLE hook — generic
    across the freespin family, no role collision to scope away);
    derive_mechanism_flags: freespin_applicable now ALSO derives from
    role == "freespin" (M275's play is the literal "NewFreespin").
  - st_extract/trigger_path.py consumption: the manifest's trigger_paths block
    resolves through get_extractors_for_manifest → the per-ST extraction layer
    delivers the EXACT GTT-discriminated per-path split.
  - NO attribution rule: every round self-settles (sum(payids)==WinCredits);
    the fallback bucket is zero BY CONSTRUCTION — locked here as
    "no _unattributed_* anywhere".

The whole test runs the REAL engine on the real cached chunks at
rawdata/M275/mode_1 (charter invariant 3) and asserts on the WRITTEN
player_impact_summary.json (not just the in-memory dict). bet passes the chunk
_bet (1000) — the M279 bet trap: a bet=1 summary renders every "x bet" column
1000x inflated.

Tests
-----
1. Manifest: loads + schema-validates; role freespin in KNOWN_ROLES; the
   derived analysis set is EXACTLY the expected M275 composition (and does NOT
   contain respin/minigame/wheel/topdollar analyses).
2. Non-leak BOTH ways (manifest-level, committed expectations): M15/M43/M279
   derived sets do not gain freespin_dynamics + their mechanism flags stay
   freespin_applicable=False; M275's is True.
3. trigger_paths declaration sanity: exactly one extractor configured, for
   ST126 only; discriminator map covers exactly the observed GTT vocabulary
   {0,2}; unknown values surface (never merge).
4. REAL report regression: integrity passes; session_conservation_level "ok";
   zero _unattributed_*; freespin_dynamics present with alarm-clean per-path
   table + cross-signal relations; volatility/session KPIs present.
5. Frontend contract: every key the app.js _stDimFreespin renderer reads
   exists in the generated freespin_dynamics block (the M43 lesson:
   JSON-correct != rendered-correct; gate 7 renders for real, this catches
   key drift early) + every fmt() i18n key it uses exists in pure.js.
6. Mechanism flag: derive_mechanism_flags role-aware freespin derivation.

Inject-bug → RED → revert → GREEN (TestInjectBugProof):
  (i)   corrupt the manifest's discriminator map to {"0": "scatter"} only
        (temp manifests_root copy — the committed manifest is NEVER touched):
        GTT=2 rounds land in the surfaced "unknown:2" bucket → the alarm-clean
        assertions (path set == declared, no unknown_paths key) go RED.
  (ii)  remove ROLE_ANALYSES["freespin"] (monkeypatch): freespin_dynamics is
        absent from the derived set AND from the real report → derived-set +
        section-presence tests go RED. Integrity still passes (the wiring
        break is isolated — M275 has no attribution rule to break).
  (iii) blank the plugin's F6 extract (drop the st_extract read, monkeypatch):
        trigger_paths.available flips False, the per-path table vanishes →
        the cross-signal tests (4b/4c/4d) go RED.
  Each patch auto-reverts; the module-scoped fixture (built un-patched) is the
  GREEN proof (test_green_resumes_after_revert).
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest

# Repo root for locating rawdata + manifests + frontend sources.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M275_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M275" / "mode_1"
_MANIFESTS_ROOT = _REPO_ROOT / "configs" / "machine_manifests"
_M275_MANIFEST = _MANIFESTS_ROOT / "M275.json"
_APP_JS = _REPO_ROOT / "src" / "web_console" / "frontend" / "app.js"
_PURE_JS = _REPO_ROOT / "src" / "web_console" / "frontend" / "pure.js"

# The bet used during M275 sampling (chunk _bet == 1000). The report is
# value-agnostic; bet only affects coin totals, which this test never asserts —
# but NOT passing it is the M279 trap (sampling.bet=1 → frontend divides every
# "x bet" column by 1 → 1000x inflated multipliers). Locked in TestCorrectnessGate.
_BET = 1000

# Structural SpinType ids fixed by the rawdata protocol + manifest (NOT values
# that drift on re-sample): the base grind and the granted freespin session.
_ST_BASE = 140
_ST_FREESPIN = 126

# The manifest-declared trigger-path labels (structural identifiers — the
# declaration IS the contract the per-path table must match exactly).
_DECLARED_PATHS = frozenset({"scatter", "collect_peak"})

# COMMITTED derived-set expectations (hardcoded on purpose — independent of the
# live CROSS_CUTTING/PER_SPINTYPE constants, so a leak INTO those constants is
# caught too, not normalized away).
_EXPECTED_M275_ANALYSES = frozenset({
    "bankruptcy_simulation", "bonus_chain_dynamics", "collect_mechanic",
    "machine_mechanics", "multiplier_profile", "upstream_feature_breakdown",
    "payouts_by_spin_type", "reel_marginal_by_spin_type",
    "spin_type_outcomes", "spin_type_rtp_buckets",
    "freespin_dynamics",
    "structure_drift",
})
_EXPECTED_M15_ANALYSES = (_EXPECTED_M275_ANALYSES - {"freespin_dynamics"}) | {
    "topdollar_choice",
}
_EXPECTED_M43_ANALYSES = (_EXPECTED_M275_ANALYSES - {"freespin_dynamics"}) | {
    "respin_dynamics", "minigame_dynamics",
}
_EXPECTED_M279_ANALYSES = (_EXPECTED_M275_ANALYSES - {"freespin_dynamics"}) | {
    "respin_dynamics", "wheel_dynamics",
}

# Analyses that must NOT attach to M275 (no respin role, no player_choice role,
# no WinMiniGame/Wheel play).
_FOREIGN_ANALYSES = frozenset({
    "respin_dynamics", "minigame_dynamics", "wheel_dynamics", "topdollar_choice",
})

# Expected top-level keys (frontend contract — same current schema as the
# M43/M279 onboarding tests). Superset check, never equality.
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
    "structure_drift",
})

# Expected player_impact sub-keys: the standard set PLUS freespin_dynamics
# (the whole point of this onboarding). Superset check.
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
    "freespin_dynamics",
})

# trigger_paths keys that are CONDITIONAL (alarm / fallback semantics) — their
# ABSENCE on this clean data is itself an assertion (alarm-clean); the dynamic
# frontend-contract walk must not require them.
_TP_OPTIONAL_KEYS = frozenset({
    "unknown_paths", "unknown_paths_alarm",
    "multi_buckets", "multi_buckets_note",
    "extraction_errors", "reason", "declared_paths",
})


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


def _payout_ids(summary) -> list[str]:
    return [
        str(r.get("payout_id", ""))
        for r in summary["player_impact"].get("payout_ids_top20", [])
    ]


def _generate(machine: str, chunk_dir: Path, tmpdir: str, **kw) -> dict:
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    return generate_report_from_chunks(
        machine, 1, chunk_dir=chunk_dir, output_dir=Path(tmpdir), bet=_BET, **kw
    )


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3) and
# assert on the WRITTEN summary (the file the console serves), not just the
# returned dict.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m275_summary():
    if not _has_chunks(_M275_CHUNK_DIR):
        pytest.skip("M275 cached chunks not present")
    with tempfile.TemporaryDirectory() as tmpdir:
        returned = _generate("M275", _M275_CHUNK_DIR, tmpdir)
        written_path = Path(tmpdir) / "player_impact_summary.json"
        assert written_path.exists(), (
            "write_summary_json must produce player_impact_summary.json"
        )
        written = json.loads(written_path.read_text(encoding="utf-8"))
        # The written file is what the console serves — assert THAT. Sanity:
        # the new section survives JSON round-trip identically.
        assert written["player_impact"].get("freespin_dynamics") == \
            returned["player_impact"].get("freespin_dynamics"), (
                "freespin_dynamics must survive the JSON write identically"
            )
        yield written


@pytest.fixture(scope="module")
def m275_player_impact(m275_summary):
    return m275_summary["player_impact"]


@pytest.fixture(scope="module")
def m275_manifest():
    if not _M275_MANIFEST.exists():
        pytest.skip("M275 manifest not present")
    return json.loads(_M275_MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fd(m275_player_impact):
    fd = m275_player_impact.get("freespin_dynamics")
    assert isinstance(fd, dict), "freespin_dynamics section missing"
    return fd


# ---------------------------------------------------------------------------
# 1. MANIFEST — loads, validates, derives EXACTLY the expected analysis set.
# ---------------------------------------------------------------------------

class TestManifestRegistration:
    def test_manifest_loads_and_schema_validates(self, m275_manifest):
        from fresh_slotlab.analyzer.machine_spec import load_manifest, validate_schema
        assert validate_schema(m275_manifest) == [], (
            f"M275 manifest schema errors: {validate_schema(m275_manifest)}"
        )
        loaded = load_manifest("M275", _MANIFESTS_ROOT)  # raises on invalid
        assert loaded["machine_id"] == "M275"
        assert 1 in loaded["modes"]

    def test_freespin_role_is_known(self):
        """The W4 ordering rule: the KNOWN_ROLES extension must land WITH the
        manifest (validate_schema rejects unknown roles)."""
        from fresh_slotlab.analyzer.machine_spec import KNOWN_ROLES
        assert "freespin" in KNOWN_ROLES

    def test_manifest_declares_two_st_roles_and_plays(self, m275_manifest):
        """The manifest is the source of truth for role/play
        (feedback_no_hardcode.md — analyses resolve from here, not literals)."""
        st = m275_manifest["spin_types"]
        assert st[str(_ST_BASE)]["role"] == "paid_spin"
        assert st[str(_ST_BASE)]["play"] == "NormalCollectionSpin"
        assert st[str(_ST_FREESPIN)]["role"] == "freespin"
        assert st[str(_ST_FREESPIN)]["play"] == "NewFreespin"

    def test_derived_analysis_set_is_exactly_m275s(self, m275_manifest):
        """EXACT composition: CROSS_CUTTING + PER_SPINTYPE + the freespin ROLE
        hook — and nothing else (no cross-machine leak INTO M275)."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        derived = set(derive_analyses(m275_manifest))
        assert derived == set(_EXPECTED_M275_ANALYSES), (
            f"M275 derived set drifted.\n  unexpected: {sorted(derived - _EXPECTED_M275_ANALYSES)}"
            f"\n  missing: {sorted(_EXPECTED_M275_ANALYSES - derived)}"
        )

    def test_no_foreign_mechanic_analyses(self, m275_manifest):
        """Spelled out (implied by exactness, but the failure message matters):
        respin_dynamics (no respin role), topdollar_choice (no player_choice),
        minigame_dynamics / wheel_dynamics (no such plays) must NOT attach."""
        from fresh_slotlab.analyzer.machine_spec import derive_analyses
        derived = set(derive_analyses(m275_manifest))
        leaked = derived & _FOREIGN_ANALYSES
        assert not leaked, f"foreign mechanic analyses leaked onto M275: {sorted(leaked)}"

    def test_no_round_win_rule_declared(self, m275_manifest):
        """M275 self-settles (sum(payids)==WinCredits) — the manifest must NOT
        declare an attribution rule (03_design.md §5: nothing synthetic)."""
        assert m275_manifest.get("round_win_rule") is None
        assert m275_manifest["rtp_integrity"]["paid_st"] == [_ST_BASE], (
            "only ST140 costs; a global-bet denominator would inflate by "
            "st126's cost-0 BetAmount rows"
        )


# ---------------------------------------------------------------------------
# 2. NON-LEAK BOTH WAYS — M15/M43/M279 derived sets + mechanism flags stay at
#    their committed expectations (M275's registration is inert for them).
#    Report-level inertness is proven separately by the _fwpass_gate byte
#    checks; here the derivation layer is locked cheaply and exactly.
# ---------------------------------------------------------------------------

class TestNonLeak:
    @staticmethod
    def _derived(machine: str) -> set[str]:
        from fresh_slotlab.analyzer.machine_spec import load_manifest, derive_analyses
        return set(derive_analyses(load_manifest(machine, _MANIFESTS_ROOT)))

    @staticmethod
    def _flags(machine: str) -> dict:
        from fresh_slotlab.analyzer.machine_spec import (
            load_manifest, derive_mechanism_flags,
        )
        return derive_mechanism_flags(load_manifest(machine, _MANIFESTS_ROOT))

    def test_m15_has_no_freespin_dynamics(self):
        derived = self._derived("M15")
        assert "freespin_dynamics" not in derived, (
            "freespin_dynamics LEAKED onto M15 — the `freespin` role must not "
            "match M15's paid_spin/player_choice/settlement STs."
        )
        assert derived == set(_EXPECTED_M15_ANALYSES), (
            f"M15 derived set changed by M275's registration: {sorted(derived)}"
        )

    def test_m43_has_no_freespin_dynamics(self):
        derived = self._derived("M43")
        assert "freespin_dynamics" not in derived, (
            "freespin_dynamics LEAKED onto M43 — its respin (WinRespin) is a "
            "win-driven extension, NOT a granted freespin session."
        )
        assert derived == set(_EXPECTED_M43_ANALYSES), (
            f"M43 derived set changed by M275's registration: {sorted(derived)}"
        )

    def test_m279_has_no_freespin_dynamics(self):
        derived = self._derived("M279")
        assert "freespin_dynamics" not in derived, (
            "freespin_dynamics LEAKED onto M279 — its respin (MoveSpin) / "
            "settlement (Wheel) STs must not match the `freespin` role."
        )
        assert derived == set(_EXPECTED_M279_ANALYSES), (
            f"M279 derived set changed by M275's registration: {sorted(derived)}"
        )

    def test_fs_win_fallback_cannot_fire_on_siblings(self):
        """W5 breaker fix non-leak (machine_mechanics stb_win_fallback): the
        fallback is gated on fs_applicable — derived False for M15/M43/M279
        (no freespin role/play) ⇒ the branch is structurally unreachable on
        them and their free_spin cards keep whatever their own accumulators
        produce (detection_source can never gain '+stb_win_fallback').
        Report-level byte-proof = the four _fwpass_gate checks (the goldens
        predate the fix)."""
        from fresh_slotlab.analyzer.machine_spec import derive_mechanism_flags, load_manifest
        for machine in ("M15", "M43", "M279"):
            manifest = load_manifest(machine, _MANIFESTS_ROOT)
            flags = derive_mechanism_flags(manifest)
            assert flags["freespin_applicable"] is False, (
                f"{machine}: freespin_applicable must be False — the "
                f"stb_win_fallback gate (fs_win==0 AND applicable AND "
                f"chain_spins>0) must stay closed on non-freespin machines"
            )

    def test_mechanism_flag_role_aware_derivation(self, m275_manifest):
        """Requirement 6: derive_mechanism_flags keys freespin_applicable on
        role=='freespin' too (M275's play is the branded 'NewFreespin' — the
        play check alone would self-contradict the report). M15/M43/M279 stay
        False: the role-aware derivation is ADDITIVE, not a behavior change."""
        from fresh_slotlab.analyzer.machine_spec import derive_mechanism_flags
        assert derive_mechanism_flags(m275_manifest)["freespin_applicable"] is True
        for machine in ("M15", "M43", "M279"):
            flags = self._flags(machine)
            assert flags["freespin_applicable"] is False, (
                f"{machine} freespin_applicable flipped by M275's role-aware "
                f"derivation — it must stay False (no freespin role/play declared)"
            )
            assert flags["detection_source"] == "manifest_spin_types"


# ---------------------------------------------------------------------------
# 3. trigger_paths DECLARATION SANITY — the manifest block resolves through
#    get_extractors_for_manifest into exactly one extractor, configured for
#    ST126 only, with the observed-vocabulary-only discriminator map.
# ---------------------------------------------------------------------------

class TestTriggerPathDeclaration:
    def test_exactly_one_extractor_for_st126(self, m275_manifest):
        from fresh_slotlab.analyzer.st_extract import (
            discover_extractors, get_extractors_for_manifest,
        )
        discover_extractors()
        exts = get_extractors_for_manifest(m275_manifest)
        ext_ids = [e.EXTRACTOR_ID for e in exts]
        # trigger_path must be present (the M275-specific discriminated extractor).
        # signature_audit is also present because all M275 STs declare "signature".
        assert "trigger_path" in ext_ids, (
            f"M275 must configure the trigger_path extractor; got {ext_ids}"
        )
        tp_ext = next(e for e in exts if e.EXTRACTOR_ID == "trigger_path")
        # The per-ST declaration parsed: ST126 only (private attr read — the
        # only direct evidence the declaration reached the extractor config).
        assert set(tp_ext._st_declarations.keys()) == {_ST_FREESPIN}, (
            f"trigger_path must be configured for ST{_ST_FREESPIN} only; got "
            f"{sorted(tp_ext._st_declarations.keys())}"
        )

    def test_discriminator_maps_only_observed_gtt_vocabulary(self, m275_manifest):
        """The map covers exactly the OBSERVED GTT vocabulary {0,2}; anything
        else surfaces as unknown:* (signal, never residual —
        feedback_invariant_with_fallback_hides_drift.md)."""
        tp = m275_manifest["spin_types"][str(_ST_FREESPIN)]["trigger_paths"]
        disc = tp["discriminator"]
        assert disc["kind"] == "round_field"
        assert disc["field"] == "GameplayTriggerType"
        assert set(disc["map"].keys()) == {"0", "2"}, (
            "the discriminator must map ONLY the observed GTT vocabulary {0,2} "
            "— mapping unobserved values would be fabricated coverage"
        )
        assert set(disc["map"].values()) == set(_DECLARED_PATHS)
        assert disc["unmapped_value_policy"] == "surface_as_unknown_path"

    def test_declared_paths_consistent_with_map(self, m275_manifest):
        """Every discriminator target label is a declared path (and vice versa)
        + the proven additive double-grant policy is recorded."""
        tp = m275_manifest["spin_types"][str(_ST_FREESPIN)]["trigger_paths"]
        assert set(tp["paths"].keys()) == set(_DECLARED_PATHS)
        for label, spec in tp["paths"].items():
            assert "opened_by" in spec and "label" in spec, (
                f"path {label} must document its opening signal + display label"
            )
        assert tp["multi_trigger_policy"] == "additive_sessions"
        assert tp["fallback"]["kind"] == "trigger_anchor_walk"

    def test_sibling_manifests_configure_no_trigger_path_extractor(self):
        """Trigger-path non-leak: M15/M43/M279 declare no trigger_paths →
        the trigger_path extractor must NOT appear in their extractor list
        (the inertness contract the _fwpass_gate locks at report level).
        Note: signature_audit IS present for all machines that declare
        "signature" (all 4 registered manifests do), so the list is non-empty;
        the assertion is specifically about trigger_path isolation."""
        from fresh_slotlab.analyzer.machine_spec import load_manifest
        from fresh_slotlab.analyzer.st_extract import (
            discover_extractors, get_extractors_for_manifest,
        )
        discover_extractors()
        for machine in ("M15", "M43", "M279"):
            manifest = load_manifest(machine, _MANIFESTS_ROOT)
            exts = get_extractors_for_manifest(manifest)
            ext_ids = [e.EXTRACTOR_ID for e in exts]
            assert "trigger_path" not in ext_ids, (
                f"{machine} must NOT configure the trigger_path extractor "
                f"(no trigger_paths declared in manifest); got {ext_ids}"
            )


# ---------------------------------------------------------------------------
# 4. CORRECTNESS GATE — real report: integrity, conservation, zero fallback.
# ---------------------------------------------------------------------------

class TestCorrectnessGate:
    def test_report_generates_with_machine_and_mode(self, m275_summary):
        assert m275_summary["machine"] == "M275"
        assert m275_summary["mode"] == 1
        assert m275_summary["sampling"]["chunks"] > 0
        assert m275_summary["sampling"]["total_spins"] > 0
        # No emit-loop / extract errors surfaced (feedback_no_silent_swallow.md).
        assert not m275_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m275_summary.get('feature_errors')}"
        )

    def test_bet_stamped_from_sampling_not_default(self, m275_summary):
        """The M279 bet trap: the engine default bet=1 lands in sampling.bet and
        the frontend divides every 'x bet' column by it → 1000x inflated
        multipliers. The chunks were sampled at bet=1000; the summary must say so."""
        assert m275_summary["sampling"]["bet"] == _BET

    def test_rtp_integrity_passes(self, m275_summary):
        ric = m275_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M275 mode 1. Got "
            f"passed={ric.get('passed')}, message={ric.get('summary_message', 'N/A')}"
        )
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant broken: {ric.get('layer1_error')}"
        )
        assert ric.get("layer3_anchors_ok") is True

    def test_session_conservation_ok(self, m275_summary):
        """M275 is the machine whose scatter-session freespin wins exposed the
        session-dim fold bug (the W2 ABORT, fixed framework-side in b8826c5).
        The conservation alarm must read 'ok' — if the fold regresses, this is
        the first tripwire."""
        ric = m275_summary.get("rtp_integrity_check", {})
        assert ric.get("session_conservation_level") == "ok", (
            f"session conservation must be 'ok'; got "
            f"level={ric.get('session_conservation_level')}, "
            f"notes={ric.get('session_conservation_notes')}"
        )
        assert ric.get("session_conservation_ok") is True

    def test_zero_unattributed_buckets(self, m275_summary):
        """M275 needs NO attribution rule — every round self-settles. The
        Layer-2 fallback bucket is zero BY CONSTRUCTION; any _unattributed_*
        appearing is structural drift (the M274 lesson:
        feedback_invariant_with_fallback_hides_drift.md)."""
        ric = m275_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}"
        )
        assert (ric.get("layer2_fallback_buckets_found") or []) == []
        pids = _payout_ids(m275_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )

    def test_our_total_win_matches_server_aggregate(self, m275_summary):
        """Charter invariant 1: our==server when the server aggregate is present
        (W1/W2 proved sum(payids)==WinCredits==server on every round)."""
        rtp = m275_summary["rtp"]
        if rtp.get("server_total_win") is None:
            pytest.skip("server aggregate not present in this sample")
        assert rtp["our_total_win"] == pytest.approx(
            rtp["server_total_win"], rel=1e-9
        ), "our_total_win must equal the server aggregate (no orphan/double-count)"
        assert rtp["numerator_source"] == "our_total_win", (
            "server-override must NOT engage when our==server"
        )

    def test_volatility_session_kpis_present(self, m275_player_impact):
        """The post-session-fix KPIs (F3b): present and structurally sane.
        avg_return_x > 0 (the fold no longer drops 45.8% of win → a near-RTP
        return, not a half); max >= 10 (M275's bonus carries 3-digit session
        multipliers — structural, not pinned)."""
        vol = m275_player_impact["volatility"]
        assert vol["avg_return_x"] > 0
        assert vol["max_observed_return_x"] >= 10, (
            "M275's freespin sessions carry >=10x outcomes; a max below 10 "
            "means the session fold lost the bonus wins again (the W2 ABORT)"
        )
        hp = m275_player_impact["hit_and_payout"]
        for k in ("win_hit_rate", "big_win_x10_rate"):
            assert k in hp


# ---------------------------------------------------------------------------
# 5. SCHEMA / FRONTEND-CONTRACT keys present.
# ---------------------------------------------------------------------------

class TestSchema:
    def test_top_level_keys_superset(self, m275_summary):
        missing = _EXPECTED_TOP_KEYS - set(m275_summary.keys())
        assert not missing, f"Expected top-level keys absent: {sorted(missing)}"

    def test_player_impact_keys_superset(self, m275_player_impact):
        missing = _EXPECTED_PI_KEYS - set(m275_player_impact.keys())
        assert not missing, f"Expected player_impact keys absent: {sorted(missing)}"

    def test_no_foreign_mechanic_sections_in_report(self, m275_player_impact):
        """The report-level converse of the derived-set exactness: no
        respin/minigame/wheel/topdollar sections (not even applicable:False —
        they are not in M275's derived set at all)."""
        present = _FOREIGN_ANALYSES & set(m275_player_impact.keys())
        assert not present, (
            f"foreign mechanic sections leaked into the M275 report: {sorted(present)}"
        )

    def test_rtp_integrity_check_has_layer_fields(self, m275_summary):
        ric = m275_summary["rtp_integrity_check"]
        for field in ("passed", "layer1_invariant_ok", "layer2_no_fallback_buckets_ok",
                      "layer3_anchors_ok", "summary_message",
                      "session_conservation_ok", "session_conservation_level"):
            assert field in ric, f"rtp_integrity_check missing field: {field}"

    def test_the_two_spin_types_present(self, m275_player_impact):
        sts = set()
        for row in m275_player_impact.get("spin_type_breakdown", []):
            try:
                sts.add(int(row.get("spin_type")))
            except (TypeError, ValueError):
                continue
        for st in (_ST_BASE, _ST_FREESPIN):
            assert st in sts, f"ST{st} missing from spin_type_breakdown; got {sorted(sts)}"

    def test_machine_mechanics_free_spin_applicable(self, m275_player_impact):
        """The report-level mechanism flag (W2 note 3 resolved): free_spin
        applicable via the role-aware derivation — the report no longer
        self-contradicts (freespin chains shown + 'not applicable' flag)."""
        mm = m275_player_impact["machine_mechanics"]
        fs = mm.get("free_spin") or {}
        assert fs.get("applicable") is True, (
            f"machine_mechanics.free_spin.applicable must be True for M275 "
            f"(role-aware derivation); got {fs.get('applicable')}"
        )


# ---------------------------------------------------------------------------
# 5b. FREE-SPIN CARD WIN — the W5 breaker fix (machine_mechanics
#     stb_win_fallback): an APPLICABLE free_spin card must never render
#     rtp_contribution_pp 0.00 while the same report shows the real freespin
#     win elsewhere. On role/play-declared machines the CurFreeSpin-based
#     freespin_win accumulator stays 0; the fix sums the manifest-declared
#     freespin-role/play STs' spin_type_breakdown total_win (manifest-driven,
#     fires only when fs_win==0 AND applicable AND chain_spins>0).
# ---------------------------------------------------------------------------

class TestFreeSpinCardWinFallback:
    @pytest.fixture
    def fs_card(self, m275_player_impact):
        mm = m275_player_impact.get("machine_mechanics")
        assert isinstance(mm, dict), "machine_mechanics section missing"
        card = mm.get("free_spin")
        assert isinstance(card, dict), "free_spin card missing"
        return card

    def test_applicable_card_carries_real_win(self, fs_card):
        """The breaker counterexample, locked: applicable AND total_win > 0 AND
        rtp_contribution_pp > 0 (no self-contradicting 'applicable but 0.00pp'
        card). Value-agnostic — no win or pp value pinned."""
        assert fs_card.get("applicable") is True
        assert fs_card.get("chain_spins", 0) > 0, (
            "the chain_spins fallback (bonus_chain_dynamics round count) must "
            "have populated — it is the precondition of the win fallback"
        )
        assert fs_card.get("total_win", 0) > 0, (
            "applicable free_spin card with total_win 0 — the stb_win_fallback "
            "did not fire (the W5 breaker counterexample is back)"
        )
        assert fs_card.get("rtp_contribution_pp", 0) > 0, (
            "applicable free_spin card rendering rtp_contribution_pp 0.00 — "
            "the W5 breaker counterexample is back"
        )

    def test_cross_signal_card_win_equals_st126_breakdown(
        self, fs_card, m275_player_impact
    ):
        """THE cross-signal lock: free_spin.total_win == the freespin ST's
        total_win in spin_type_breakdown — two computed quantities from two
        sections, no pinned constant. This is exactly what the fallback sums,
        so any drift (double-count, wrong ST set, partial sum) goes RED."""
        stb_rows = m275_player_impact["spin_type_breakdown"]
        fs_row = next(r for r in stb_rows if int(r["spin_type"]) == _ST_FREESPIN)
        assert fs_card["total_win"] == pytest.approx(
            float(fs_row["total_win"]), rel=1e-9
        ), (
            f"free_spin.total_win ({fs_card['total_win']}) != ST{_ST_FREESPIN} "
            f"spin_type_breakdown total_win ({fs_row['total_win']})"
        )

    def test_cross_signal_card_pp_equals_trigger_path_pp_sum(self, fs_card, fd):
        """Third independent agreement: the card's rtp_contribution_pp and the
        F6 per-path pp split both use the report's RTP denominator — they must
        agree on the freespin pp (machine_mechanics vs st_extract, two
        completely separate data paths)."""
        tp = fd["trigger_paths"]
        pp_sum = sum(p["rtp_contribution_pp_split"] for p in tp["paths"])
        assert fs_card["rtp_contribution_pp"] == pytest.approx(pp_sum, rel=1e-6), (
            f"free_spin card pp ({fs_card['rtp_contribution_pp']}) != sum of "
            f"trigger-path pp splits ({pp_sum})"
        )

    def test_detection_source_records_the_fallback(self, fs_card):
        """C4 transparency: the card must SAY it used the fallback —
        '+stb_win_fallback' appended to the manifest-driven source (silent
        substitution would be the feedback_no_silent_swallow anti-pattern)."""
        src = str(fs_card.get("_detection_source") or "")
        assert "stb_win_fallback" in src, (
            f"detection_source must record the stb_win_fallback; got {src!r}"
        )
        assert "manifest_spin_types" in src, (
            f"the manifest-driven base source must be preserved, not replaced; "
            f"got {src!r}"
        )


# ---------------------------------------------------------------------------
# 6. freespin_dynamics DELIVERED — structure populated, parser_blind honest.
# ---------------------------------------------------------------------------

class TestFreespinDynamicsDelivered:
    def test_applicable_and_st_resolution(self, fd):
        """The `freespin` ROLE hook resolved fs_st=126 / base_st=140 from the
        manifest (proves the role declaration is wired, not just declared —
        feedback_no_hardcode.md: the plugin has no literal 126/140)."""
        assert fd.get("applicable") is True, (
            f"freespin_dynamics must be applicable; got {fd.get('applicable')} "
            f"reason={fd.get('reason')}"
        )
        assert fd.get("freespin_spin_type") == _ST_FREESPIN
        assert fd.get("base_spin_type") == _ST_BASE

    def test_session_cadence_populated(self, fd):
        """F1: the grant. Value-agnostic — openers > 0 and the derived rates
        are computed (not null), never pinned to 908."""
        sc = fd["session_cadence"]
        assert sc["openers"] > 0, "M275 has base->freespin openers"
        assert sc["per_paid_spin"] is not None and sc["per_paid_spin"] > 0
        assert sc["one_per_n_paid_spins"] is not None
        assert sc["avg_block_length_rounds"] is not None
        # internal consistency: one_per_n == 1 / per_paid_spin
        assert sc["one_per_n_paid_spins"] == pytest.approx(
            1.0 / sc["per_paid_spin"], rel=1e-9
        )
        cont = sc["continuation"]
        assert cont["continuation_prob"] is not None
        assert isinstance(cont["exit_breakdown"], dict) and cont["exit_breakdown"]
        assert "note" in cont, (
            "the fixed-block honesty note must be present (continuation_prob "
            "is arithmetic, not a win-gated chain)"
        )
        corr = sc["chain_structure_corroboration"]
        for k in ("chain_count", "avg_chain_length", "avg_retriggers_per_chain", "source"):
            assert k in corr
        assert "MUST NOT be cited" in corr["source"], (
            "the ER-surface disclaimer must stay on the corroboration source"
        )

    def test_hot_board_uplift_populated(self, fd):
        """F2: both hit rates + the ratio computed (no value pinned)."""
        hbu = fd["hot_board_uplift"]
        assert hbu["freespin_hit_rate"] is not None
        assert hbu["base_hit_rate"] is not None
        assert hbu["uplift_ratio"] is not None and hbu["uplift_ratio"] > 0
        # relation lock: the ratio IS freespin/base (not some other quotient)
        assert hbu["uplift_ratio"] == pytest.approx(
            hbu["freespin_hit_rate"] / hbu["base_hit_rate"], rel=1e-9
        )

    def test_multiplier_distributions_populated(self, fd):
        """F2 band overlays: both ST histograms present, well-formed, with
        probabilities that are a distribution (sum <= 1; eq0 excluded from bands)."""
        for key in ("freespin_multiplier_distribution", "base_multiplier_distribution"):
            dist = fd[key]
            assert dist["total_spins"] > 0, f"{key}.total_spins must be > 0"
            assert isinstance(dist["bands"], list) and dist["bands"], (
                f"{key}.bands must be a non-empty histogram"
            )
            prob_sum = 0.0
            for band in dist["bands"]:
                for k in ("band", "spin_count", "prob", "win_share"):
                    assert k in band, f"{key} band malformed: {band}"
                if band["prob"] is not None:
                    prob_sum += band["prob"]
            assert 0 < prob_sum <= 1.0 + 1e-9, (
                f"{key} band probs must form a (sub-)distribution; got {prob_sum}"
            )
            assert "tail_ge20x_win_share" in dist

    def test_payid_mix_populated(self, fd):
        """F2 payid mix: real pids on both sides; shares form distributions."""
        mix = fd["payid_mix"]
        for side in ("freespin_payid_share", "base_payid_share"):
            share = mix[side]
            assert isinstance(share, dict) and share, f"{side} must be non-empty"
            hit_sum = 0.0
            for pid, v in share.items():
                assert not pid.startswith("_"), f"synthetic pid leaked into {side}: {pid}"
                for k in ("hit_count", "hit_share", "win_share"):
                    assert k in v
                hit_sum += v["hit_share"]
            assert hit_sum == pytest.approx(1.0, abs=1e-9), (
                f"{side} hit_share must sum to 1; got {hit_sum}"
            )
        assert "note" in mix

    def test_rtp_concentration_populated(self, fd):
        rc = fd["rtp_concentration"]
        for k in ("freespin_rtp_contribution_pp", "share_of_all_win",
                  "fat_tail_ge20x_win_share", "zero_win_round_rate"):
            assert k in rc, f"rtp_concentration missing {k}"
        assert rc["share_of_all_win"] is not None
        assert 0 < rc["share_of_all_win"] <= 1
        assert rc["zero_win_round_rate"] is None or 0 <= rc["zero_win_round_rate"] <= 1

    def test_parser_blind_honesty_contract(self, fd):
        """The honesty contract (M279 wheel_dynamics precedent), UPDATED for Phase 3:
        F4 (ER ladder) + F5 (FS-index arc) are now DELIVERED by the
        freespin_progression extractor → they must NOT be claimed parser_blind
        anymore (claiming a delivered metric is blind would be a lie); the
        corresponding sections must be available and the reason must document the
        delivery. F3a (the server's OWN SummaryWin tier taxonomy — only a
        return_bucket proxy is delivered) stays genuinely flagged."""
        blind = fd.get("parser_blind")
        assert isinstance(blind, list) and blind, "parser_blind must be a non-empty list"
        blob = " ".join(blind)
        assert "F3a" in blob, f"F3a must still be flagged parser_blind; got {blind}"
        # F4/F5 DELIVERED (Phase 3): sections available + reason documents it.
        assert fd.get("er_ladder", {}).get("available") is True, "F4 ER ladder must be delivered"
        assert fd.get("fs_index_arc", {}).get("available") is True, "F5 FS arc must be delivered"
        reason = fd.get("parser_blind_reason")
        assert isinstance(reason, str) and reason, "parser_blind_reason must explain WHY"
        assert "F4" in reason and "F5" in reason, (
            "parser_blind_reason must document that F4/F5 are now delivered (Phase 3)"
        )


# ---------------------------------------------------------------------------
# 7. F6 TRIGGER-PATH DIMENSION — alarm-clean + cross-signal relations.
# ---------------------------------------------------------------------------

class TestTriggerPathsDelivered:
    @pytest.fixture
    def tp(self, fd):
        tp = fd.get("trigger_paths")
        assert isinstance(tp, dict), "trigger_paths section missing"
        return tp

    def test_available_with_full_extraction_coverage(self, tp):
        assert tp.get("available") is True, (
            f"trigger_paths must be available (st_extract ran); got "
            f"reason={tp.get('reason')}"
        )
        cov = tp["extraction_coverage"]
        assert cov["chunks_total"] > 0
        assert cov["chunks_with_extract"] == cov["chunks_total"], (
            f"every parsed chunk must carry the extractor output; got {cov}"
        )
        assert "extraction_errors" not in tp, (
            f"extractor errors surfaced: {tp.get('extraction_errors')}"
        )

    def test_path_set_is_exactly_the_declared_labels(self, tp, m275_manifest):
        """(4a) THE alarm-clean assertion: the observed path set == the
        manifest's declared labels — no unknown:* (vocabulary drift), no
        multi:* (no anchor-walk fallback engaged on discriminator data)."""
        declared = set(
            m275_manifest["spin_types"][str(_ST_FREESPIN)]["trigger_paths"]["paths"]
        )
        observed = {p["path"] for p in tp["paths"]}
        assert observed == declared, (
            f"path set drifted: observed {sorted(observed)} != declared {sorted(declared)}"
        )
        assert not any(p["path"].startswith(("unknown:", "multi:")) for p in tp["paths"])
        # The conditional alarm keys are ABSENT on clean data — their presence
        # IS the alarm (feedback_invariant_with_fallback_hides_drift.md).
        assert "unknown_paths" not in tp, (
            f"unknown:* discriminator values surfaced: {tp.get('unknown_paths')} "
            f"— GTT vocabulary drift, investigate before trusting the split"
        )
        assert "multi_buckets" not in tp, (
            f"multi:* buckets present on round_field-discriminated data: "
            f"{tp.get('multi_buckets')}"
        )

    def test_path_rows_well_formed(self, tp):
        for p in tp["paths"]:
            for k in ("path", "label", "session_count", "session_share",
                      "trigger_rate_per_paid_spin", "one_per_n_paid_spins",
                      "round_count", "win_share", "rtp_contribution_pp_split",
                      "win_band_hist"):
                assert k in p, f"path row missing {k}: {p}"
            assert p["session_count"] > 0, (
                f"both declared paths really occur in this data: {p['path']}"
            )
            assert p["round_count"] > 0
            # per-path internal consistency: one_per_n == 1/rate
            assert p["one_per_n_paid_spins"] == pytest.approx(
                1.0 / p["trigger_rate_per_paid_spin"], rel=1e-9
            )
            # the band histogram covers every round of the path
            hist_rounds = sum(b["round_count"] for b in p["win_band_hist"])
            assert hist_rounds == p["round_count"], (
                f"win_band_hist must cover all {p['round_count']} rounds of "
                f"{p['path']}; got {hist_rounds}"
            )
            for b in p["win_band_hist"]:
                for k in ("band", "round_count", "prob"):
                    assert k in b
                assert not b.get("unexpected_band"), (
                    f"out-of-canon band surfaced in {p['path']}: {b}"
                )

    def test_cross_signal_win_totals(self, tp, fd, m275_player_impact):
        """(4b) Cross-signal: the per-path win accumulation (st_extract layer)
        must equal the st126 total win the summary reports elsewhere
        (spin_type_breakdown — an INDEPENDENT accumulator). Delivered as the
        coverage ratio == 1.0 plus the win shares forming a full distribution."""
        assert tp["freespin_total_win_share_covered"] == pytest.approx(1.0, abs=1e-9), (
            f"sum(per-path win_sum) must equal the freespin ST's total win; "
            f"coverage={tp['freespin_total_win_share_covered']}"
        )
        win_share_sum = sum(p["win_share"] for p in tp["paths"])
        assert win_share_sum == pytest.approx(1.0, abs=1e-9), (
            f"declared paths must carry ALL the freespin win (no residual); "
            f"got {win_share_sum}"
        )
        # round-count cross-signal against two other accumulators
        stb_rows = m275_player_impact["spin_type_breakdown"]
        fs_row = next(r for r in stb_rows if int(r["spin_type"]) == _ST_FREESPIN)
        path_rounds = sum(p["round_count"] for p in tp["paths"])
        assert path_rounds == int(fs_row["spins"]), (
            f"per-path round counts ({path_rounds}) != spin_type_breakdown "
            f"ST126 spins ({fs_row['spins']})"
        )
        assert path_rounds == fd["freespin_multiplier_distribution"]["total_spins"]

    def test_cross_signal_rtp_pp_split(self, tp, fd, m275_summary):
        """(4b cont.) The per-path RTP-pp split uses the report's own RTP
        denominator — so Sum(path pp) == share_of_all_win * summary RTP
        (three INDEPENDENT sections agreeing on one quantity). NOTE: the
        plugin docstring claims the split sums to spin_type_breakdown's
        rtp_contribution_pp — on M275 that row uses the GLOBAL-bet denominator
        (st126 carries cost-0 BetAmount rows) so the docstring is wrong; the
        relation locked here is the one the code actually guarantees."""
        pp_sum = sum(p["rtp_contribution_pp_split"] for p in tp["paths"])
        share = fd["rtp_concentration"]["share_of_all_win"]
        rtp_pct = m275_summary["rtp"]["point_pct"]
        assert pp_sum == pytest.approx(share * rtp_pct, rel=1e-6), (
            f"per-path pp split ({pp_sum}) must equal share_of_all_win x "
            f"summary RTP ({share} x {rtp_pct} = {share * rtp_pct})"
        )

    def test_cross_signal_session_shares(self, tp):
        """(4c) Session shares form a full distribution over the declared paths
        and total_sessions is their sum (the additive_sessions ledger)."""
        share_sum = sum(p["session_share"] for p in tp["paths"])
        assert share_sum == pytest.approx(1.0, abs=1e-9)
        assert tp["total_sessions"] == sum(p["session_count"] for p in tp["paths"])
        assert tp["total_sessions"] > 0

    def test_discriminator_echoed_for_provenance(self, tp, m275_manifest):
        """The section echoes the manifest discriminator + policy it ran with
        (the reader can see WHICH declaration produced the split)."""
        decl = m275_manifest["spin_types"][str(_ST_FREESPIN)]["trigger_paths"]
        assert tp["discriminator"] == decl["discriminator"]
        assert tp["multi_trigger_policy"] == decl["multi_trigger_policy"]
        assert "source" in tp and "st_extract.trigger_path" in tp["source"]


# ---------------------------------------------------------------------------
# 8. FRONTEND CONTRACT — every key the _stDimFreespin renderer reads exists in
#    the generated block (the M43 lesson: JSON-correct != rendered-correct;
#    gate 7 renders for real, this catches key-contract drift early) + every
#    fmt() i18n key it uses exists in pure.js (zh + en).
# ---------------------------------------------------------------------------

def _stdim_freespin_body() -> str:
    src = _APP_JS.read_text(encoding="utf-8")
    start = src.find("function _stDimFreespin")
    assert start != -1, "_stDimFreespin not found in app.js"
    end = src.find("\nconst SPINTYPE_DIMENSIONS", start)
    if end == -1:
        end = src.find("\nfunction ", start + 10)
    assert end != -1
    return src[start:end]


class TestFrontendContract:
    @pytest.fixture(scope="class")
    def renderer_body(self):
        if not _APP_JS.exists():
            pytest.skip("app.js not present")
        return _stdim_freespin_body()

    def test_renderer_registered_in_dimension_list(self):
        if not _APP_JS.exists():
            pytest.skip("app.js not present")
        src = _APP_JS.read_text(encoding="utf-8")
        dims_start = src.find("const SPINTYPE_DIMENSIONS")
        assert dims_start != -1
        dims_block = src[dims_start:src.find("];", dims_start)]
        assert "_stDimFreespin" in dims_block, (
            "_stDimFreespin must be wired into SPINTYPE_DIMENSIONS (render order)"
        )

    def test_every_fd_read_exists_in_summary(self, renderer_body, fd):
        """Dynamic trace: every `fd.<key>` the renderer reads must exist in the
        generated block — if app.js grows a read the backend doesn't emit, this
        goes RED before gate 7 does."""
        reads = set(re.findall(r"\bfd\.([A-Za-z_][A-Za-z0-9_]*)", renderer_body))
        assert reads, "no fd.* reads traced — the renderer body slice is wrong"
        missing = {k for k in reads if k not in fd}
        assert not missing, (
            f"_stDimFreespin reads keys the summary does not emit: {sorted(missing)}"
        )

    def test_every_tp_read_exists_or_is_declared_optional(self, renderer_body, fd):
        """Same trace for `tp.<key>`: required keys must exist; the alarm /
        unavailable-branch keys are OPTIONAL (their absence on clean data is
        asserted by the alarm-clean test, not a contract violation)."""
        tp = fd["trigger_paths"]
        reads = set(re.findall(r"\btp\.([A-Za-z_][A-Za-z0-9_]*)", renderer_body))
        assert reads
        required = reads - _TP_OPTIONAL_KEYS
        missing = {k for k in required if k not in tp}
        assert not missing, (
            f"_stDimFreespin reads trigger_paths keys the summary does not emit: "
            f"{sorted(missing)}"
        )

    def test_nested_kpi_reads_exist(self, fd):
        """Hardcoded nested contract traced from _stDimFreespin (sc./cont./
        corr./hbu./mix./rtpC. locals + band-table fields)."""
        sc = fd["session_cadence"]
        for k in ("openers", "per_paid_spin", "one_per_n_paid_spins",
                  "avg_block_length_rounds", "continuation",
                  "chain_structure_corroboration"):
            assert k in sc, f"session_cadence missing renderer-read key {k}"
        cont = sc["continuation"]
        for k in ("continuation_prob", "exit_breakdown", "note"):
            assert k in cont
        corr = sc["chain_structure_corroboration"]
        for k in ("chain_count", "avg_chain_length", "avg_retriggers_per_chain",
                  "source"):
            assert k in corr
        for k in ("freespin_hit_rate", "base_hit_rate", "uplift_ratio"):
            assert k in fd["hot_board_uplift"]
        for dist_key in ("freespin_multiplier_distribution",
                         "base_multiplier_distribution"):
            dist = fd[dist_key]
            for k in ("bands", "total_spins", "win_rounds", "tail_ge20x_win_share"):
                assert k in dist, f"{dist_key} missing renderer-read key {k}"
            for band in dist["bands"]:
                for k in ("band", "spin_count", "prob", "win_share"):
                    assert k in band
        mix = fd["payid_mix"]
        for k in ("freespin_payid_share", "base_payid_share", "note"):
            assert k in mix
        for side in ("freespin_payid_share", "base_payid_share"):
            for v in mix[side].values():
                for k in ("hit_count", "hit_share", "win_share"):
                    assert k in v
        rc = fd["rtp_concentration"]
        for k in ("freespin_rtp_contribution_pp", "share_of_all_win",
                  "fat_tail_ge20x_win_share", "zero_win_round_rate", "note"):
            assert k in rc
        for p in fd["trigger_paths"]["paths"]:
            for k in ("path", "label", "session_count", "session_share",
                      "trigger_rate_per_paid_spin", "one_per_n_paid_spins",
                      "round_count", "win_share", "rtp_contribution_pp_split",
                      "win_band_hist"):
                assert k in p
            for b in p["win_band_hist"]:
                for k in ("band", "round_count", "prob"):
                    assert k in b

    def test_every_fmt_key_exists_in_pure_js_both_locales(self, renderer_body):
        """Every fmt("...") i18n key the renderer uses must be defined in
        pure.js — in BOTH locales (zh + en entries each appear as `key:`).
        A missing key renders as the raw key name (silent UI degradation)."""
        if not _PURE_JS.exists():
            pytest.skip("pure.js not present")
        pure_src = _PURE_JS.read_text(encoding="utf-8")
        keys = set(re.findall(r'fmt\("([A-Za-z0-9_]+)"\)', renderer_body))
        assert keys, "no fmt() keys traced from _stDimFreespin"
        problems = {}
        for key in sorted(keys):
            n = len(re.findall(rf"(?m)^\s*{re.escape(key)}:", pure_src))
            if n < 2:
                problems[key] = n
        assert not problems, (
            f"i18n keys missing from pure.js (need zh+en definitions): {problems}"
        )


# ---------------------------------------------------------------------------
# INJECT-BUG PROOF — break each safety claim → RED → (auto-revert) → GREEN.
#
# Claim A: the manifest discriminator map covers the GTT vocabulary; unmapped
#          values SURFACE as unknown:* and trip the alarm-clean assertions.
# Claim B: the ROLE_ANALYSES["freespin"] wiring attaches freespin_dynamics.
# Claim C: the F6 table is fed by the real st_extract read — blanking it
#          flips available:False and kills the cross-signals (no fabrication).
#
# All injections auto-revert (tempdir / monkeypatch), so the module-scoped
# m275_summary (built without any patch) stays GREEN.
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_corrupt_discriminator_map_surfaces_unknown_path(self):
        """INJECT (Claim A): a temp manifests_root carries an M275.json whose
        discriminator map is {"0": "scatter"} ONLY (collect_peak unmapped).
        The GTT=2 rounds must land in the SURFACED "unknown:2" bucket — the
        exact condition the alarm-clean test (path set == declared) trips on.
        The committed manifest is never touched."""
        if not _has_chunks(_M275_CHUNK_DIR):
            pytest.skip("M275 cached chunks not present")
        if not _M275_MANIFEST.exists():
            pytest.skip("M275 manifest not present")

        manifest = json.loads(_M275_MANIFEST.read_text(encoding="utf-8"))
        tp_decl = manifest["spin_types"][str(_ST_FREESPIN)]["trigger_paths"]
        tp_decl["discriminator"]["map"] = {"0": "scatter"}  # BUG: drop "2"

        with tempfile.TemporaryDirectory() as tmp_manifests, \
                tempfile.TemporaryDirectory() as tmp_out:
            (Path(tmp_manifests) / "M275.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            summary = _generate(
                "M275", _M275_CHUNK_DIR, tmp_out, manifests_root=tmp_manifests,
            )
            tp = summary["player_impact"]["freespin_dynamics"]["trigger_paths"]

            # RED 1 — the alarm bucket appears (signal, never residual).
            assert "unknown_paths" in tp, (
                "inject-bug: the unmapped GTT=2 value must SURFACE as an "
                "unknown_paths alarm bucket"
            )
            unknown_labels = {p["path"] for p in tp["unknown_paths"]}
            assert "unknown:2" in unknown_labels, (
                f"inject-bug: expected unknown:2; got {unknown_labels}"
            )
            assert tp.get("unknown_paths_alarm"), (
                "the alarm text must accompany the surfaced bucket"
            )
            # RED 2 — the alarm-clean condition (path set == declared) breaks.
            observed = {p["path"] for p in tp["paths"]}
            assert observed != _DECLARED_PATHS, (
                "inject-bug: the declared-path-set equality must FAIL"
            )
            assert observed == {"scatter"}
            # RED 3 — the declared paths no longer carry ALL the win
            # (the unknown bucket holds the remainder) → cross-signal (4b) RED.
            win_share_sum = sum(p["win_share"] for p in tp["paths"])
            assert win_share_sum < 1.0 - 1e-9, (
                f"inject-bug: real-path win shares must NOT sum to 1 "
                f"(the unknown bucket holds the rest); got {win_share_sum}"
            )
            # Isolation: extraction is display-level — integrity still passes.
            assert summary["rtp_integrity_check"].get("passed") is True, (
                "inject-bug: a display-level vocabulary gap must NOT break "
                "RTP integrity (attribution is independent)"
            )
        # tempdirs removed — the committed manifest was never modified.

    def test_inject_remove_freespin_role_wiring_drops_plugin(self, monkeypatch):
        """INJECT (Claim B): remove "freespin" from machine_spec.ROLE_ANALYSES
        (the role hook broken). The derived set loses freespin_dynamics AND the
        real report loses the section. Integrity still passes — the wiring
        break is isolated (M275 has no attribution rule to break)."""
        if not _has_chunks(_M275_CHUNK_DIR):
            pytest.skip("M275 cached chunks not present")

        import fresh_slotlab.analyzer.machine_spec as ms

        patched = {k: v for k, v in ms.ROLE_ANALYSES.items() if k != "freespin"}
        monkeypatch.setattr(ms, "ROLE_ANALYSES", patched)

        # RED 1 — the derived-set exactness test condition breaks.
        manifest = json.loads(_M275_MANIFEST.read_text(encoding="utf-8"))
        derived = set(ms.derive_analyses(manifest))
        assert "freespin_dynamics" not in derived, (
            "inject-bug: with the role hook removed, derive_analyses must not "
            "attach freespin_dynamics"
        )
        assert derived != set(_EXPECTED_M275_ANALYSES)

        # RED 2 — the real report loses the section entirely.
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = _generate("M275", _M275_CHUNK_DIR, tmpdir)
            pi = summary["player_impact"]
            assert "freespin_dynamics" not in pi, (
                f"inject-bug: freespin_dynamics must be absent from the report; "
                f"got keys {sorted(pi.keys())}"
            )
            assert summary["rtp_integrity_check"].get("passed") is True, (
                "inject-bug: breaking the analysis wiring must NOT break "
                "integrity (self-settling attribution is rule-free)"
            )
        # monkeypatch auto-reverts here.

    def test_inject_blank_f6_extract_kills_cross_signals(self, monkeypatch):
        """INJECT (Claim C): wrap FreespinDynamics.extract to DROP the
        st_extract read (the F6 feed). trigger_paths must flip to
        available:False with the honest reason — the per-path table and every
        cross-signal (4b/4c/4d) goes RED. Proves F6 is fed by the real
        extraction layer, not fabricated from somewhere else."""
        if not _has_chunks(_M275_CHUNK_DIR):
            pytest.skip("M275 cached chunks not present")

        import fresh_slotlab.analyzer.features.freespin_dynamics as fdmod

        original_extract = fdmod.FreespinDynamics.extract

        def _blanked_extract(self, parse_state, chunk_dict):
            acc = original_extract(self, parse_state, chunk_dict)
            acc["trigger_paths"] = {}        # BUG: skip the st_extract read
            acc["chunks_with_extract"] = 0
            return acc

        monkeypatch.setattr(fdmod.FreespinDynamics, "extract", _blanked_extract)

        with tempfile.TemporaryDirectory() as tmpdir:
            summary = _generate("M275", _M275_CHUNK_DIR, tmpdir)
            tp = summary["player_impact"]["freespin_dynamics"]["trigger_paths"]

            # RED — the section reports unavailability honestly (no fabrication).
            assert tp.get("available") is False, (
                f"inject-bug: with the st_extract read blanked, trigger_paths "
                f"must be available:False; got {tp.get('available')}"
            )
            assert "paths" not in tp, (
                "inject-bug: no per-path table may be fabricated without data"
            )
            assert "freespin_total_win_share_covered" not in tp, (
                "inject-bug: the win-coverage cross-signal must vanish, not "
                "read 1.0"
            )
            assert tp.get("reason"), "the unavailable branch must say WHY"
            # The declared labels are still echoed (the manifest is intact).
            assert set(tp.get("declared_paths") or {}) == _DECLARED_PATHS
        # monkeypatch auto-reverts here.

    def test_green_resumes_after_revert(self, fd, m275_summary):
        """After every injection reverts, the un-patched module fixture is
        GREEN: integrity + conservation pass, the section is present, the
        alarm-clean per-path table is back."""
        ric = m275_summary["rtp_integrity_check"]
        assert ric.get("passed") is True
        assert ric.get("session_conservation_level") == "ok"
        tp = fd["trigger_paths"]
        assert tp.get("available") is True
        assert {p["path"] for p in tp["paths"]} == _DECLARED_PATHS
        assert "unknown_paths" not in tp
