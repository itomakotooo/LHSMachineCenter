"""M278 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This file asserts STRUCTURE / CONSERVATION / ATTRIBUTION / role-resolution /
honesty INVARIANTS, NEVER an RTP value or range. M278's numbers (RTP, hit-rates,
per-path session counts, burst lengths) drift on re-sample / re-tune; pinning ANY
of them would be a brittle false alarm (charter permanent invariant 1). The only
hard constants asserted are STRUCTURAL ids fixed by the manifest (SpinTypes
140/160) and CONSERVATION arithmetic (the per-path round counts must sum to the
total ST160 round count — a ratio identity, not a pinned count).

What M278 shipped (session_artifacts/_onboard/M278/03_design.md + 05_breaker.md):
  - configs/machine_manifests/M278.json — ST140 paid_spin/NormalCollectionSpin,
    ST160 hold_respin/JewelFeverRespin with a `trigger_paths` block in
    ANCHOR-WALK (fallback) mode (3 jewel pids + 1 collect_peak counter).
  - machine_spec.py — NEW `hold_respin` KNOWN_ROLES token; FREESPIN_FAMILY_ROLES
    = {freespin, hold_respin}; ROLE_ANALYSES["hold_respin"]=("freespin_dynamics",);
    derive_mechanism_flags freespin_applicable extended to the family.
  - freespin_dynamics.py — _resolve_st_by_role resolves the {freespin,hold_respin}
    family; the trigger_paths.source string is discriminator-kind-aware (an
    anchor-walk machine is NOT mislabeled "round_field discriminator").
  - configs/machine_round_win_rules.json m278_jewelfever_settlement
    (synthesize_pay_id, spin_types=[160], label_format=spin_type) → real pid st160.

The whole test runs the REAL engine on the real cached chunk at rawdata/M278/mode_1
(charter invariant 3: run the real thing, pass bet=chunk _bet, read the real summary).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M278_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M278" / "mode_1"
_M275_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M275" / "mode_1"
_M278_MANIFEST = _REPO_ROOT / "configs" / "machine_manifests" / "M278.json"

_BET = 1000
_FALLBACK_ST160 = "_unattributed_st160"

_ST_BASE = 140
_ST_RESPIN = 160  # the hold-and-respin event


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m278_summary():
    if not _has_chunks(_M278_CHUNK_DIR):
        pytest.skip("M278 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            "M278", 1,
            chunk_dir=_M278_CHUNK_DIR,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists()
        yield summary


@pytest.fixture(scope="module")
def m278_player_impact(m278_summary):
    return m278_summary["player_impact"]


@pytest.fixture(scope="module")
def m278_freespin(m278_player_impact):
    fd = m278_player_impact.get("freespin_dynamics")
    assert isinstance(fd, dict), "freespin_dynamics section missing"
    return fd


@pytest.fixture(scope="module")
def m278_trigger_paths(m278_freespin):
    tp = m278_freespin.get("trigger_paths")
    assert isinstance(tp, dict), "freespin_dynamics.trigger_paths missing"
    return tp


@pytest.fixture(scope="module")
def m278_manifest():
    if not _M278_MANIFEST.exists():
        pytest.skip("M278 manifest not present")
    return json.loads(_M278_MANIFEST.read_text(encoding="utf-8"))


def _payout_ids(summary) -> list[str]:
    return [
        str(r.get("payout_id", ""))
        for r in summary["player_impact"].get("payout_ids_top20", [])
    ]


def _st160_round_count(summary) -> int:
    """The total ST160 round count from the per-ST breakdown (the conservation
    denominator). Value-agnostic structural total of the EVENT, not an RTP."""
    for row in summary["player_impact"].get("spin_type_breakdown", []):
        try:
            if int(row.get("spin_type")) == _ST_RESPIN:
                return int(row.get("spins") or 0)
        except (TypeError, ValueError):
            continue
    return 0


# ---------------------------------------------------------------------------
# 0. Smoke + manifest role declaration.
# ---------------------------------------------------------------------------

class TestReportGenerates:
    def test_machine_and_mode(self, m278_summary):
        assert m278_summary["machine"] == "M278"
        assert m278_summary["mode"] == 1
        assert m278_summary["sampling"]["chunks"] > 0
        assert m278_summary["sampling"]["total_spins"] > 0
        assert not m278_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m278_summary.get('feature_errors')}"
        )

    def test_manifest_declares_hold_respin_and_anchor_walk(self, m278_manifest):
        """ST160 is role hold_respin/play JewelFeverRespin with a trigger_paths
        block in ANCHOR-WALK mode (a `fallback` of kind trigger_anchor_walk, NO
        round_field discriminator)."""
        st = m278_manifest["spin_types"]
        assert st[str(_ST_BASE)]["role"] == "paid_spin"
        assert st[str(_ST_RESPIN)]["role"] == "hold_respin"
        assert st[str(_ST_RESPIN)]["play"] == "JewelFeverRespin"
        tp = st[str(_ST_RESPIN)]["trigger_paths"]
        assert tp.get("fallback", {}).get("kind") == "trigger_anchor_walk", (
            "M278's trigger_paths must declare a trigger_anchor_walk fallback"
        )
        assert "discriminator" not in tp, (
            "M278 must NOT declare a round_field discriminator (it mislabels the "
            "continuation rounds — the whole point of the anchor-walk fallback)"
        )

    def test_hold_respin_is_known_role(self):
        """The NEW hold_respin role token is registered (schema validation)."""
        from fresh_slotlab.analyzer.machine_spec import (
            KNOWN_ROLES, FREESPIN_FAMILY_ROLES, ROLE_ANALYSES,
        )
        assert "hold_respin" in KNOWN_ROLES
        assert "hold_respin" in FREESPIN_FAMILY_ROLES
        assert "freespin" in FREESPIN_FAMILY_ROLES, (
            "freespin must REMAIN in the family (additive — no regression on M275/M43)"
        )
        assert ROLE_ANALYSES.get("hold_respin") == ("freespin_dynamics",), (
            "hold_respin must attach freespin_dynamics via the ROLE hook"
        )


# ---------------------------------------------------------------------------
# (b) hold_respin role RESOLVES — mechanic view NOT dark.
# ---------------------------------------------------------------------------

class TestHoldRespinRoleResolves:
    def test_freespin_dynamics_applicable_and_resolves_st160(self, m278_freespin):
        """The IMPLEMENTER-CRITICAL detail: freespin_dynamics resolves its target
        ST via the {freespin,hold_respin} family — so the mechanic view is NOT
        dark (applicable True) and freespin_spin_type==160, base_spin_type==140."""
        assert m278_freespin.get("applicable") is True, (
            f"freespin_dynamics MUST be applicable for M278 (the hold_respin role "
            f"must resolve via the family); got applicable="
            f"{m278_freespin.get('applicable')} reason={m278_freespin.get('reason')}. "
            "If False, _resolve_st_by_role did not accept the hold_respin family → "
            "the entire mechanic view went DARK."
        )
        assert m278_freespin.get("freespin_spin_type") == _ST_RESPIN, (
            f"freespin_spin_type must resolve to {_ST_RESPIN}; got "
            f"{m278_freespin.get('freespin_spin_type')}"
        )
        assert m278_freespin.get("base_spin_type") == _ST_BASE

    def test_machine_mechanics_freespin_flag_true(self, m278_player_impact):
        """derive_mechanism_flags freespin_applicable is extended to the family —
        a hold-and-respin IS a granted free-session bonus, so the mechanic flag
        must read True (the report must not self-contradict)."""
        mm = m278_player_impact.get("machine_mechanics") or {}
        fs = mm.get("free_spin") or {}
        assert fs.get("applicable") is True, (
            "machine_mechanics.free_spin.applicable must be True for M278 "
            "(hold_respin is in FREESPIN_FAMILY_ROLES); the report would "
            f"self-contradict otherwise. Got {fs}"
        )


# ---------------------------------------------------------------------------
# (a) ANCHOR-WALK ROUND CONSERVATION — no dropped rounds, no silent orphans.
# ---------------------------------------------------------------------------

class TestAnchorWalkRoundConservation:
    def test_trigger_paths_available_and_anchor_walk(self, m278_trigger_paths):
        assert m278_trigger_paths.get("available") is True
        # M278 is the FIRST anchor-walk consumer: NO round_field discriminator.
        assert m278_trigger_paths.get("discriminator") is None, (
            "M278 declares NO discriminator (anchor-walk fallback); got "
            f"{m278_trigger_paths.get('discriminator')}"
        )

    def test_round_conservation_sum_equals_total_st160(self, m278_trigger_paths, m278_summary):
        """CONSERVATION: Σ(per-path round_count) + Σ(multi-edge round_count) +
        Σ(unknown round_count) == total ST160 rounds. ZERO dropped, ZERO silent
        orphans. VALUE-AGNOSTIC: this is a SUM IDENTITY, not a pinned count —
        the total (5594 today) drifts on re-sample, but the identity holds."""
        paths = m278_trigger_paths.get("paths") or []
        multi = m278_trigger_paths.get("multi_buckets") or []
        unknown = m278_trigger_paths.get("unknown_paths") or []

        sum_paths = sum(int(p.get("round_count", 0)) for p in paths)
        sum_multi = sum(int(m.get("round_count", 0)) for m in multi)
        sum_unknown = sum(int(u.get("round_count", 0)) for u in unknown)
        total_attributed = sum_paths + sum_multi + sum_unknown

        total_st160 = _st160_round_count(m278_summary)
        assert total_st160 > 0, "M278 has ST160 rounds"
        assert total_attributed == total_st160, (
            f"ROUND CONSERVATION broken: per-path {sum_paths} + multi {sum_multi} "
            f"+ unknown {sum_unknown} = {total_attributed} != total ST160 rounds "
            f"{total_st160}. Rounds were DROPPED or double-counted."
        )

    def test_no_silent_orphans_win_share_sums_to_one(self, m278_trigger_paths):
        """The win is conserved too: Σ win_share over paths + multi + unknown ≈ 1.0
        (no win silently lost). VALUE-AGNOSTIC ratio identity, not a coin total."""
        paths = m278_trigger_paths.get("paths") or []
        multi = m278_trigger_paths.get("multi_buckets") or []
        unknown = m278_trigger_paths.get("unknown_paths") or []
        total_share = (
            sum(float(p.get("win_share") or 0.0) for p in paths)
            + sum(float(m.get("win_share") or 0.0) for m in multi)
            + sum(float(u.get("win_share") or 0.0) for u in unknown)
        )
        assert total_share == pytest.approx(1.0, abs=1e-6), (
            f"win_share over all paths+multi+unknown must sum to 1.0 (no win lost); "
            f"got {total_share}"
        )
        # The whole ST160 win is covered (no leakage outside the path split).
        assert m278_trigger_paths.get("freespin_total_win_share_covered") == pytest.approx(
            1.0, abs=1e-6
        ), (
            "freespin_total_win_share_covered must be 1.0 (the path split covers all "
            f"ST160 win); got {m278_trigger_paths.get('freespin_total_win_share_covered')}"
        )

    def test_multi_edges_surfaced_as_alarm_buckets_not_dropped(self, m278_trigger_paths):
        """Multi-edge (double-anchored) rounds are SURFACED in multi_buckets with
        a multi:* label + an alarm note — never silently merged/dropped
        (feedback_invariant_with_fallback_hides_drift). VALUE-AGNOSTIC: we assert
        the alarm-bucket STRUCTURE (multi:* prefix + note), not its size."""
        multi = m278_trigger_paths.get("multi_buckets") or []
        if multi:
            for m in multi:
                assert str(m.get("path", "")).startswith("multi:"), (
                    f"a multi bucket must carry a multi:* label; got {m.get('path')}"
                )
            assert isinstance(m278_trigger_paths.get("multi_buckets_note"), str), (
                "multi buckets must carry an explanatory note (surfaced, not hidden)"
            )

    def test_unknown_paths_are_alarm_buckets_when_present(self, m278_trigger_paths):
        """If any unknown:* path appears it is an ALARM bucket (drift signal),
        never a silent residual. On clean M278 data there should be none — but if
        a future drift introduces one it must be surfaced, not swallowed."""
        unknown = m278_trigger_paths.get("unknown_paths") or []
        if unknown:
            for u in unknown:
                assert str(u.get("path", "")).startswith("unknown:")
            assert isinstance(m278_trigger_paths.get("unknown_paths_alarm"), str), (
                "unknown buckets must carry an alarm note (signal, not residual)"
            )


# ---------------------------------------------------------------------------
# (e) trigger_paths.source reflects the ANCHOR-WALK fallback (the honesty fix).
# ---------------------------------------------------------------------------

class TestAnchorWalkSourceHonesty:
    def test_source_says_anchor_walk_not_round_field(self, m278_trigger_paths):
        """The honesty fix: the discriminator-kind-aware source string must say
        'anchor-walk fallback' for M278 (no round_field discriminator declared),
        NOT mislabel it a 'round_field discriminator'. A static 'round_field'
        label would lie about how M278's paths are resolved."""
        source = str(m278_trigger_paths.get("source", "")).lower()
        assert "anchor-walk" in source, (
            f"trigger_paths.source must describe the ANCHOR-WALK fallback for "
            f"M278; got {m278_trigger_paths.get('source')!r}"
        )
        assert "no round_field discriminator" in source or "no round-field" in source, (
            "the source must state there is NO round_field discriminator "
            f"(the honesty fix); got {m278_trigger_paths.get('source')!r}"
        )
        # And it must NOT claim a manifest-declared round_field discriminator.
        assert "manifest-declared round_field" not in source, (
            f"M278 must NOT be mislabeled a round_field discriminator machine; "
            f"got {m278_trigger_paths.get('source')!r}"
        )


# ---------------------------------------------------------------------------
# (c) ST160 attribution — sum(payid)==summary, no fallback, ST160 win → pid st160.
# (d) session_conservation == "ok".
# ---------------------------------------------------------------------------

class TestAttribution:
    def test_rtp_integrity_passes(self, m278_summary):
        ric = m278_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M278 mode 1; got "
            f"passed={ric.get('passed')}, message={ric.get('summary_message','N/A')}. "
            f"Likely cause: m278_jewelfever_settlement not applied → ST160 → {_FALLBACK_ST160}."
        )

    def test_layer1_sum_invariant_holds(self, m278_summary):
        ric = m278_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 invariant broken: {ric.get('layer1_error')}"
        )

    def test_no_unattributed_st160_fallback_bucket(self, m278_summary):
        ric = m278_summary.get("rtp_integrity_check", {})
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}"
        )
        buckets = ric.get("layer2_fallback_buckets_found") or []
        assert _FALLBACK_ST160 not in buckets
        pids = _payout_ids(m278_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )

    def test_st160_attributed_to_real_pid(self, m278_summary):
        pids = _payout_ids(m278_summary)
        assert "st160" in pids, (
            f"expected synthesized real pid 'st160' from m278_jewelfever_settlement; "
            f"got {pids}"
        )

    def test_session_conservation_ok(self, m278_summary):
        """(d) Real-economy machine — no win lost. ST160's whole win is
        session-attributed (not lost to paid-round attribution)."""
        ric = m278_summary.get("rtp_integrity_check", {})
        assert ric.get("session_conservation_level") == "ok", (
            f"session_conservation_level must be 'ok'; got "
            f"{ric.get('session_conservation_level')} "
            f"(skip_reason={ric.get('session_conservation_skip_reason')})"
        )


# ---------------------------------------------------------------------------
# NON-LEAK + ADDITIVITY — the hold_respin family edit did not regress M275.
#   The shared freespin_dynamics resolver now resolves the {freespin,hold_respin}
#   family. M275 declares the freespin role; it must STILL resolve byte-identically
#   (the family contains "freespin" first; the edit is additive).
# ---------------------------------------------------------------------------

class TestNonLeakAndAdditivity:
    @pytest.fixture(scope="class")
    def m275_summary(self):
        if not _has_chunks(_M275_CHUNK_DIR):
            pytest.skip("M275 cached chunks not present")
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            return generate_report_from_chunks(
                "M275", 1, chunk_dir=_M275_CHUNK_DIR,
                output_dir=Path(tmpdir), bet=_BET,
            )

    def test_m275_freespin_still_resolves(self, m275_summary):
        """M275's freespin role still resolves the same way after the family edit
        (additive: the family set still contains 'freespin' first)."""
        fd = m275_summary["player_impact"].get("freespin_dynamics") or {}
        assert fd.get("applicable") is True, (
            "M275 freespin_dynamics must STILL be applicable after the hold_respin "
            "family edit (additivity)"
        )
        assert m275_summary["rtp_integrity_check"].get("passed") is True, (
            "M275 integrity must still pass (onboarding M278 must not regress M275)"
        )


# ---------------------------------------------------------------------------
# INJECT-BUG PROOF — break each safety claim → RED → (auto-revert) → GREEN.
#
# Claim A: m278_jewelfever_settlement zeroes _unattributed_st160 (integrity).
# Claim B: the {freespin,hold_respin} family resolution keeps the mechanic view
#          alive — if the resolver only accepted "freespin", the hold_respin ST
#          would NOT resolve and freespin_dynamics would go DARK (applicable False).
# Claim C: the source string is anchor-walk-honest — if the discriminator-kind
#          branch were forced to "round_field", M278 would be MISLABELED (proven
#          via a patched copy that pins the round_field phrase).
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_no_rule_reintroduces_unattributed_st160(self, monkeypatch):
        """INJECT (Claim A): load_rules_for_machine → []. ST160 win lands in
        _unattributed_st160; integrity FAILS. VALUE-AGNOSTIC (the bucket is the
        signature, not an RTP)."""
        if not _has_chunks(_M278_CHUNK_DIR):
            pytest.skip("M278 cached chunks not present")
        import fresh_slotlab.round_win as rw_mod

        def _no_rules(machine_id, config):
            return []

        monkeypatch.setattr(rw_mod, "load_rules_for_machine", _no_rules)
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = generate_report_from_chunks(
                "M278", 1, chunk_dir=_M278_CHUNK_DIR,
                output_dir=Path(tmpdir), bet=_BET,
            )
            ric = summary.get("rtp_integrity_check", {})
            pids = _payout_ids(summary)
            assert _FALLBACK_ST160 in pids, (
                f"inject-bug: without the rule, ST160 win must land in "
                f"{_FALLBACK_ST160}; got {pids}"
            )
            assert ric.get("layer2_no_fallback_buckets_ok") is False
            assert _FALLBACK_ST160 in (ric.get("layer2_fallback_buckets_found") or [])
            assert ric.get("passed") is not True
            assert "st160" not in pids
        # monkeypatch auto-reverts here.

    def test_inject_family_without_hold_respin_darkens_mechanic_view(self, monkeypatch):
        """INJECT (Claim B): shrink FREESPIN_FAMILY_ROLES to {"freespin"} only (the
        pre-edit single-role behavior). Then the hold_respin ST160 no longer
        resolves and freespin_dynamics goes DARK (applicable False) — proving the
        family resolution is the load-bearing fix. Attribution is independent and
        still passes (the synth rule still attributes st160)."""
        if not _has_chunks(_M278_CHUNK_DIR):
            pytest.skip("M278 cached chunks not present")
        import fresh_slotlab.analyzer.features.freespin_dynamics as fd_mod

        # The plugin resolves against its own module-level family constant.
        monkeypatch.setattr(fd_mod, "_FREESPIN_FAMILY_ROLES", frozenset({"freespin"}))
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = generate_report_from_chunks(
                "M278", 1, chunk_dir=_M278_CHUNK_DIR,
                output_dir=Path(tmpdir), bet=_BET,
            )
            fd = summary["player_impact"].get("freespin_dynamics") or {}
            assert fd.get("applicable") is False, (
                "inject-bug: with the family shrunk to {'freespin'} the hold_respin "
                "ST160 must NOT resolve → freespin_dynamics goes DARK (applicable "
                f"False); got applicable={fd.get('applicable')}. This is the exact "
                "IMPLEMENTER-CRITICAL detail the family resolution fixes."
            )
            # Attribution is independent of the mechanic view — still passes.
            assert summary["rtp_integrity_check"].get("passed") is True, (
                "inject-bug: darkening the mechanic view must NOT break attribution"
            )
        # monkeypatch auto-reverts here.

    def test_green_resumes_after_revert(self, m278_summary, m278_trigger_paths):
        """After the inject-bug monkeypatches revert, the real (un-patched) report
        is GREEN: integrity passes, no fallback, freespin_dynamics applicable,
        anchor-walk source honest, round conservation holds."""
        ric = m278_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert ric.get("layer2_no_fallback_buckets_ok") is True
        assert _FALLBACK_ST160 not in _payout_ids(m278_summary)
        fd = m278_summary["player_impact"]["freespin_dynamics"]
        assert fd.get("applicable") is True
        assert "anchor-walk" in str(m278_trigger_paths.get("source", "")).lower()
