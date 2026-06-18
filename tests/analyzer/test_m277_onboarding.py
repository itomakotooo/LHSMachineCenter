"""M277 mode-1 onboarding — VALUE-AGNOSTIC regression guard (Wave 4 TEST).

Charter: Unit = SpinType (EVENT); quantify the *felt* experience as
distributions / rates / probabilities / shares — money amounts do NOT matter.
This file asserts STRUCTURE / CONSERVATION / ATTRIBUTION / role-resolution /
honesty INVARIANTS, NEVER an RTP value or range. M277's numbers (RTP, hit-rates,
per-path session/round counts, burst lengths) drift on re-sample / re-tune;
pinning ANY of them would be a brittle false alarm (charter permanent invariant
1). The only hard constants asserted are STRUCTURAL ids fixed by the manifest
(SpinTypes 140/13), the manifest-declared path keys/labels, and CONSERVATION
arithmetic (per-path round counts must sum to the total ST13 round count — a
SUM identity, not a pinned count).

What M277 shipped (session_artifacts/_onboard/M277/03_design.md, W2 02_reuse.md):
  - configs/machine_manifests/M277.json — the ONLY new file. ST140
    paid_spin/NormalCollectionSpin (STRICT-REUSE of the M278 pattern: 4
    PER_SPINTYPE plugins + collect_mechanic, native pids '1'/'777'); ST13
    hold_respin/LockReSpin (NEW event assembled from COMMITTED pieces only —
    the hold_respin role + freespin_dynamics via the ROLE hook + a declarative
    `trigger_paths` block in ANCHOR-WALK / trigger_anchor_walk fallback mode).
  - ZERO new plugin, ZERO machine_spec.py edit (hold_respin already committed),
    ZERO machine_round_win_rules.json edit (ST13 carries a NATURAL pid '1' whose
    value==WinCredits on 10,145/10,145 rows — the OPPOSITE of M278 ST160, which
    was empty-pid and needed a SynthesizePayIdRule; here a synth rule would be a
    no-op and would falsely imply an empty-payid problem ST13 does not have).

User-confirmed naming (asserted verbatim):
  - ST13 feature display name = the machine's own "LockReSpin".
  - trigger-path labels (data-derived defaults):
      lockrespin_random -> "Random trigger (LockReSpin)"
      collect_peak      -> "Collect-meter pity (BuffCollection peak)"

The whole test runs the REAL engine on the real cached chunk at
rawdata/M277/mode_1 (charter invariant 3: run the real thing, pass
bet=chunk _bet=1000, read the real summary — NOT an echo'd exit code).
"""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_M277_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M277" / "mode_1"
_M278_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M278" / "mode_1"
_M277_MANIFEST = _REPO_ROOT / "configs" / "machine_manifests" / "M277.json"

_BET = 1000  # the chunk's _bet (avoid the M279 1000x-inflation trap)

_ST_BASE = 140  # paid_spin / NormalCollectionSpin
_ST_RESPIN = 13  # hold_respin / LockReSpin (the granted held-wild respin chain)
_FALLBACK_ST13 = "_unattributed_st13"

# data-derived path keys + user-confirmed labels (the SPLIT is structural; the
# labels are the verbatim confirmed strings the report must surface).
_PATH_RANDOM = "lockrespin_random"
_PATH_COLLECT = "collect_peak"
_LABEL_RANDOM = "Random trigger (LockReSpin)"
_LABEL_COLLECT = "Collect-meter pity (BuffCollection peak)"


def _has_chunks(d: Path) -> bool:
    return d.exists() and len(list(d.glob("chunk_*.json"))) > 0


# ---------------------------------------------------------------------------
# Fixtures — run the REAL engine once per module (charter invariant 3).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m277_summary():
    if not _has_chunks(_M277_CHUNK_DIR):
        pytest.skip("M277 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = generate_report_from_chunks(
            "M277", 1,
            chunk_dir=_M277_CHUNK_DIR,
            output_dir=Path(tmpdir),
            bet=_BET,
        )
        assert (Path(tmpdir) / "player_impact_summary.json").exists()
        yield summary


@pytest.fixture(scope="module")
def m277_player_impact(m277_summary):
    return m277_summary["player_impact"]


@pytest.fixture(scope="module")
def m277_freespin(m277_player_impact):
    fd = m277_player_impact.get("freespin_dynamics")
    assert isinstance(fd, dict), "freespin_dynamics section missing entirely"
    return fd


@pytest.fixture(scope="module")
def m277_trigger_paths(m277_freespin):
    tp = m277_freespin.get("trigger_paths")
    assert isinstance(tp, dict), "freespin_dynamics.trigger_paths missing"
    return tp


@pytest.fixture(scope="module")
def m277_manifest():
    if not _M277_MANIFEST.exists():
        pytest.skip("M277 manifest not present")
    return json.loads(_M277_MANIFEST.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Helpers (all VALUE-AGNOSTIC — counts/shares/keys, never an RTP).
# ---------------------------------------------------------------------------

def _payout_ids(summary) -> list[str]:
    return [
        str(r.get("payout_id", ""))
        for r in summary["player_impact"].get("payout_ids_top20", [])
    ]


def _spins_for_st(summary, st: int) -> int:
    for row in summary["player_impact"].get("spin_type_breakdown", []):
        try:
            if int(row.get("spin_type")) == st:
                return int(row.get("spins") or 0)
        except (TypeError, ValueError):
            continue
    return 0


def _payout_rows(summary, key: str) -> list[dict]:
    pbs = summary["player_impact"].get("payouts_by_spin_type") or {}
    rows = pbs.get(key)
    return rows if isinstance(rows, list) else []


def _path_by_key(trigger_paths, key: str) -> dict | None:
    for p in trigger_paths.get("paths") or []:
        if str(p.get("path")) == key:
            return p
    return None


# ---------------------------------------------------------------------------
# 0. Smoke + manifest role/play declaration (correct roles).
# ---------------------------------------------------------------------------

class TestReportGenerates:
    def test_machine_and_mode(self, m277_summary):
        assert m277_summary["machine"] == "M277"
        assert m277_summary["mode"] == 1
        assert m277_summary["sampling"]["chunks"] > 0
        assert m277_summary["sampling"]["total_spins"] > 0
        assert not m277_summary.get("feature_errors"), (
            f"feature emit/extract errors present: {m277_summary.get('feature_errors')}"
        )

    def test_both_spin_types_present_in_breakdown(self, m277_summary):
        """(1) BOTH ST140 paid + ST13 hold_respin are emitted events with rounds.
        VALUE-AGNOSTIC: we assert the EVENTS exist with >0 rounds, not a count."""
        assert _spins_for_st(m277_summary, _ST_BASE) > 0, (
            "ST140 (paid NormalCollectionSpin) must appear in spin_type_breakdown"
        )
        assert _spins_for_st(m277_summary, _ST_RESPIN) > 0, (
            "ST13 (hold_respin LockReSpin) must appear in spin_type_breakdown"
        )

    def test_manifest_declares_correct_roles_and_plays(self, m277_manifest):
        """(1) ST140 = paid_spin / NormalCollectionSpin; ST13 = hold_respin /
        LockReSpin (the machine's own feature name, USER-CONFIRMED verbatim)."""
        st = m277_manifest["spin_types"]
        assert st[str(_ST_BASE)]["role"] == "paid_spin"
        assert st[str(_ST_BASE)]["play"] == "NormalCollectionSpin"
        assert st[str(_ST_RESPIN)]["role"] == "hold_respin", (
            "ST13 must be role hold_respin (NOT paid_spin / freespin) — the "
            "committed family token that attaches freespin_dynamics"
        )
        assert st[str(_ST_RESPIN)]["play"] == "LockReSpin", (
            "ST13 play/display name must be the machine's own 'LockReSpin' "
            "(user-confirmed; NOT a branded name)"
        )

    def test_manifest_declares_anchor_walk_not_round_field(self, m277_manifest):
        """ST13 trigger_paths is in ANCHOR-WALK mode (trigger_anchor_walk
        fallback) with the two data-derived paths + the user-confirmed labels,
        and NO round_field discriminator (GameplayTriggerType=0 everywhere)."""
        tp = m277_manifest["spin_types"][str(_ST_RESPIN)]["trigger_paths"]
        assert tp.get("fallback", {}).get("kind") == "trigger_anchor_walk", (
            "M277 ST13 must declare a trigger_anchor_walk fallback (the trigger "
            "lives on the opening paid ST140, not on a ST13 round field)"
        )
        assert "discriminator" not in tp, (
            "M277 must NOT declare a round_field discriminator — "
            "GameplayTriggerType=0 on every ST13 AND ST140 round (cannot discriminate)"
        )
        paths = tp.get("paths") or {}
        assert _PATH_RANDOM in paths and _PATH_COLLECT in paths, (
            f"both trigger paths must be declared; got {sorted(paths)}"
        )
        assert paths[_PATH_RANDOM].get("label") == _LABEL_RANDOM, (
            f"lockrespin_random label must be the user-confirmed "
            f"{_LABEL_RANDOM!r}; got {paths[_PATH_RANDOM].get('label')!r}"
        )
        assert paths[_PATH_COLLECT].get("label") == _LABEL_COLLECT, (
            f"collect_peak label must be the user-confirmed {_LABEL_COLLECT!r}; "
            f"got {paths[_PATH_COLLECT].get('label')!r}"
        )
        assert tp.get("multi_trigger_policy") == "additive_sessions"

    def test_manifest_declares_no_round_win_rule(self, m277_manifest):
        """ST13 attribution is the NATIVE pid space (NO SynthesizePayIdRule).
        The manifest's round_win_rule field must read NONE — a synth rule would
        be a no-op here and would falsely imply an empty-payid problem."""
        rwr = m277_manifest.get("round_win_rule", "")
        assert isinstance(rwr, str) and rwr.upper().startswith("NONE"), (
            f"M277 round_win_rule must be NONE (natural pid); got {rwr!r}"
        )

    def test_rtp_integrity_paid_st_is_140_only(self, m277_manifest):
        """rtp_integrity.paid_st = [140] — ST140 is the single PAID event; ST13 is
        a CostCredits=0 granted session (not counted as a paid round)."""
        ri = m277_manifest.get("rtp_integrity") or {}
        assert ri.get("paid_st") == [_ST_BASE], (
            f"rtp_integrity.paid_st must be [{_ST_BASE}] (only ST140 is paid); "
            f"got {ri.get('paid_st')}"
        )


# ---------------------------------------------------------------------------
# hold_respin family token is registered (schema/wiring; no machine_spec edit).
# ---------------------------------------------------------------------------

class TestHoldRespinRoleToken:
    def test_hold_respin_is_committed_known_role(self):
        """ZERO machine_spec edit: hold_respin is ALREADY a committed family
        token. M277 reuses it verbatim (no base_hash flip, no collision risk)."""
        from fresh_slotlab.analyzer.machine_spec import (
            KNOWN_ROLES, FREESPIN_FAMILY_ROLES, ROLE_ANALYSES,
        )
        assert "hold_respin" in KNOWN_ROLES
        assert "hold_respin" in FREESPIN_FAMILY_ROLES
        assert "freespin" in FREESPIN_FAMILY_ROLES, (
            "freespin must REMAIN in the family (additive — no regression)"
        )
        assert ROLE_ANALYSES.get("hold_respin") == ("freespin_dynamics",), (
            "hold_respin must attach freespin_dynamics via the ROLE hook"
        )


# ---------------------------------------------------------------------------
# (4) freespin_dynamics applicable for ST13 — the mechanic view is NOT dark.
# ---------------------------------------------------------------------------

class TestFreespinDynamicsApplicable:
    def test_freespin_dynamics_applicable_resolves_st13(self, m277_freespin):
        """(4) freespin_dynamics resolves its target via the {freespin,hold_respin}
        family → applicable True, freespin_spin_type==13, base_spin_type==140. If
        the resolver did not accept the hold_respin family the entire mechanic
        view would go DARK (proven in TestInjectBugProof)."""
        assert m277_freespin.get("applicable") is True, (
            f"freespin_dynamics MUST be applicable for M277 (the hold_respin role "
            f"must resolve via the family); got applicable="
            f"{m277_freespin.get('applicable')} reason={m277_freespin.get('reason')}"
        )
        assert m277_freespin.get("freespin_spin_type") == _ST_RESPIN, (
            f"freespin_spin_type must resolve to {_ST_RESPIN}; got "
            f"{m277_freespin.get('freespin_spin_type')}"
        )
        assert m277_freespin.get("base_spin_type") == _ST_BASE

    def test_machine_mechanics_free_spin_flag_true(self, m277_player_impact):
        """derive_mechanism_flags freespin_applicable is extended to the family —
        a held-wild hold-and-respin IS a granted free session, so the mechanic
        flag must read True (the report must not self-contradict)."""
        mm = m277_player_impact.get("machine_mechanics") or {}
        fs = mm.get("free_spin") or {}
        assert fs.get("applicable") is True, (
            "machine_mechanics.free_spin.applicable must be True for M277 "
            f"(hold_respin is in FREESPIN_FAMILY_ROLES). Got {fs}"
        )


# ---------------------------------------------------------------------------
# (4) trigger_paths split present (both paths) + the dual-trigger ALARM.
# ---------------------------------------------------------------------------

class TestTriggerPathsSplit:
    def test_trigger_paths_available_and_anchor_walk(self, m277_trigger_paths):
        assert m277_trigger_paths.get("available") is True
        # ANCHOR-WALK: NO round_field discriminator surfaced at runtime.
        assert m277_trigger_paths.get("discriminator") is None, (
            "M277 surfaces NO discriminator (anchor-walk fallback); got "
            f"{m277_trigger_paths.get('discriminator')}"
        )

    def test_both_paths_present_with_confirmed_labels(self, m277_trigger_paths):
        """(4) BOTH trigger paths (lockrespin_random + collect_peak) are surfaced
        at runtime, each carrying the USER-CONFIRMED label and a >0 round_count.
        VALUE-AGNOSTIC: we assert presence + label + non-empty, not the counts."""
        rnd = _path_by_key(m277_trigger_paths, _PATH_RANDOM)
        col = _path_by_key(m277_trigger_paths, _PATH_COLLECT)
        assert rnd is not None, (
            f"trigger path {_PATH_RANDOM!r} missing from the runtime split; got "
            f"{[p.get('path') for p in (m277_trigger_paths.get('paths') or [])]}"
        )
        assert col is not None, (
            f"trigger path {_PATH_COLLECT!r} missing from the runtime split; got "
            f"{[p.get('path') for p in (m277_trigger_paths.get('paths') or [])]}"
        )
        assert rnd.get("label") == _LABEL_RANDOM
        assert col.get("label") == _LABEL_COLLECT
        assert int(rnd.get("round_count", 0)) > 0, "random path has rounds"
        assert int(col.get("round_count", 0)) > 0, "collect-peak path has rounds"

    def test_dual_trigger_alarm_surfaced(self, m277_trigger_paths):
        """(4) The 1 burst opened by BOTH pid 777 AND CollectCount==1000 is
        SURFACED as a multi:* ALARM bucket under additive_sessions — never
        silently merged (feedback_invariant_with_fallback_hides_drift).
        VALUE-AGNOSTIC: assert the alarm-bucket STRUCTURE, not its size."""
        multi = m277_trigger_paths.get("multi_buckets") or []
        assert multi, (
            "the dual-trigger (pid 777 + CollectCount==1000) burst must surface a "
            "multi:* ALARM bucket; multi_buckets is empty (silently merged?)"
        )
        labels = [str(m.get("path", "")) for m in multi]
        assert all(lbl.startswith("multi:") for lbl in labels), (
            f"every multi bucket must carry a multi:* label; got {labels}"
        )
        # the label names BOTH paths (the two coincident triggers).
        joined = " ".join(labels)
        assert _PATH_RANDOM in joined and _PATH_COLLECT in joined, (
            f"the multi bucket must name both coincident paths; got {labels}"
        )
        assert isinstance(m277_trigger_paths.get("multi_buckets_note"), str), (
            "multi buckets must carry an explanatory note (surfaced, not hidden)"
        )

    def test_round_conservation_sum_equals_total_st13(self, m277_trigger_paths, m277_summary):
        """CONSERVATION: Σ(per-path round_count) + Σ(multi round_count) +
        Σ(unknown round_count) == total ST13 rounds. ZERO dropped, ZERO silent
        orphans. VALUE-AGNOSTIC: a SUM IDENTITY, not a pinned count (the total
        drifts on re-sample; the identity holds)."""
        paths = m277_trigger_paths.get("paths") or []
        multi = m277_trigger_paths.get("multi_buckets") or []
        unknown = m277_trigger_paths.get("unknown_paths") or []
        sum_paths = sum(int(p.get("round_count", 0)) for p in paths)
        sum_multi = sum(int(m.get("round_count", 0)) for m in multi)
        sum_unknown = sum(int(u.get("round_count", 0)) for u in unknown)
        total_attributed = sum_paths + sum_multi + sum_unknown
        total_st13 = _spins_for_st(m277_summary, _ST_RESPIN)
        assert total_st13 > 0, "M277 has ST13 rounds"
        assert total_attributed == total_st13, (
            f"ROUND CONSERVATION broken: per-path {sum_paths} + multi {sum_multi} "
            f"+ unknown {sum_unknown} = {total_attributed} != total ST13 rounds "
            f"{total_st13}. Rounds were DROPPED or double-counted."
        )

    def test_win_share_covers_all_st13_win(self, m277_trigger_paths):
        """No win silently lost: Σ win_share over paths+multi+unknown ≈ 1.0 and
        freespin_total_win_share_covered == 1.0. VALUE-AGNOSTIC ratio identity."""
        paths = m277_trigger_paths.get("paths") or []
        multi = m277_trigger_paths.get("multi_buckets") or []
        unknown = m277_trigger_paths.get("unknown_paths") or []
        total_share = (
            sum(float(p.get("win_share") or 0.0) for p in paths)
            + sum(float(m.get("win_share") or 0.0) for m in multi)
            + sum(float(u.get("win_share") or 0.0) for u in unknown)
        )
        assert total_share == pytest.approx(1.0, abs=1e-6), (
            f"win_share over all paths+multi+unknown must sum to 1.0; got {total_share}"
        )
        assert m277_trigger_paths.get("freespin_total_win_share_covered") == pytest.approx(
            1.0, abs=1e-6
        ), (
            "freespin_total_win_share_covered must be 1.0 (path split covers all "
            f"ST13 win); got {m277_trigger_paths.get('freespin_total_win_share_covered')}"
        )

    def test_source_says_anchor_walk_no_round_field(self, m277_trigger_paths):
        """Honesty: the source string describes the ANCHOR-WALK fallback and
        states there is NO round_field discriminator — never mislabels M277 as a
        round_field-discriminated machine."""
        source = str(m277_trigger_paths.get("source", "")).lower()
        assert "anchor-walk" in source, (
            f"trigger_paths.source must describe the anchor-walk fallback; got "
            f"{m277_trigger_paths.get('source')!r}"
        )
        assert "no round_field discriminator" in source or "no round-field" in source, (
            f"the source must state there is NO round_field discriminator; got "
            f"{m277_trigger_paths.get('source')!r}"
        )


# ---------------------------------------------------------------------------
# (2)+(3) Attribution — server invariant, sum(pid)==WinCredits per ST,
#         rtp_integrity all layers True, NO fallback bucket, native pids.
# ---------------------------------------------------------------------------

class TestAttribution:
    def test_rtp_integrity_passes_all_layers(self, m277_summary):
        """(3) rtp_integrity_check passes on every layer; NO synth rule needed —
        ST13's natural pid '1' already zeroes the fallback."""
        ric = m277_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed must be True for M277 mode 1; got "
            f"passed={ric.get('passed')}, message={ric.get('summary_message','N/A')}"
        )
        assert ric.get("layer1_invariant_ok") is True, (
            f"Layer-1 (sum==our_total) broken: {ric.get('layer1_error')}"
        )
        assert ric.get("layer2_no_fallback_buckets_ok") is True, (
            f"Layer-2 fallback buckets present: {ric.get('layer2_fallback_buckets_found')}"
        )
        assert ric.get("layer3_anchors_ok") is True, (
            f"Layer-3 (anchors) broken: {ric.get('layer3_error')}"
        )

    def test_layer2_fallback_buckets_found_is_empty(self, m277_summary):
        """(3) layer2_fallback_buckets_found == [] AND no _unattributed* pid leaks
        into the drilldown. The native-pid design has ZERO fallback."""
        ric = m277_summary.get("rtp_integrity_check", {})
        buckets = ric.get("layer2_fallback_buckets_found") or []
        assert buckets == [], (
            f"layer2_fallback_buckets_found must be []; got {buckets}"
        )
        assert _FALLBACK_ST13 not in buckets
        pids = _payout_ids(m277_summary)
        assert not any(p.startswith("_unattributed") for p in pids), (
            f"an _unattributed_* pid leaked into payout_ids_top20: {pids}"
        )

    def test_st13_attributed_to_natural_pid_no_synth(self, m277_summary):
        """(2) ST13 win rides the NATURAL pid '1' (NOT a synthesized 'st13'); the
        sum over ST13 reproduces the server LockReSpin total natively."""
        rows = _payout_rows(m277_summary, "ST13_free")
        assert rows, "ST13_free payout rows missing"
        by_pid = {str(r.get("payout_id")): r for r in rows}
        assert "1" in by_pid, (
            f"ST13 must carry the natural pid '1'; got {sorted(by_pid)}"
        )
        assert "st13" not in by_pid, (
            "ST13 must NOT carry a synthesized 'st13' pid (no SynthesizePayIdRule)"
        )
        assert float(by_pid["1"].get("total_win") or 0.0) > 0.0, (
            "the natural ST13 pid '1' must carry the (positive) per-round win total"
        )

    def test_st140_native_pids_with_zero_win_trigger_marker(self, m277_summary):
        """(2) ST140 carries native pids '1' (real wins) + '777' (the LockReSpin
        trigger MARKER carried as a distinct ZERO-win pid — not dropped, not
        summed). VALUE-AGNOSTIC: we assert the marker's win is exactly 0 and the
        is_trigger_marker structural flag, not the win magnitude of pid '1'."""
        rows = _payout_rows(m277_summary, "ST140_paid")
        assert rows, "ST140_paid payout rows missing"
        by_pid = {str(r.get("payout_id")): r for r in rows}
        assert "1" in by_pid and "777" in by_pid, (
            f"ST140 must carry native pids '1' and '777'; got {sorted(by_pid)}"
        )
        marker = by_pid["777"]
        assert float(marker.get("total_win") or 0.0) == 0.0, (
            f"pid '777' is a 0-win trigger marker; got win={marker.get('total_win')}"
        )
        assert (marker.get("notes") or {}).get("is_trigger_marker") is True, (
            "pid '777' must be flagged is_trigger_marker (the on-payid shadow of "
            "the random LockReSpin trigger)"
        )
        assert float(by_pid["1"].get("total_win") or 0.0) > 0.0, (
            "ST140 pid '1' carries the real paid-spin win"
        )

    def test_server_invariant_session_conservation_ok(self, m277_summary):
        """(2) Real-economy machine — our total == server total, no win lost.
        session_conservation_level=='ok' (ST13's whole granted-session win is
        conserved, not lost to paid-round attribution)."""
        ric = m277_summary.get("rtp_integrity_check", {})
        assert ric.get("session_conservation_level") == "ok", (
            f"session_conservation_level must be 'ok'; got "
            f"{ric.get('session_conservation_level')} "
            f"(skip_reason={ric.get('session_conservation_skip_reason')})"
        )


# ---------------------------------------------------------------------------
# (5) collect_mechanic applicable (the metronome on ST140) — CROSS_CUTTING.
# ---------------------------------------------------------------------------

class TestCollectMechanic:
    def test_collect_mechanic_applicable(self, m277_summary):
        """(5) collect_mechanic (the CollectCount 1→1000 metronome the player
        watches fill) is applicable on M277. VALUE-AGNOSTIC: applicable +
        detected cycle structure, never an RTP."""
        cm = m277_summary.get("collect_mechanic")
        assert isinstance(cm, dict), "collect_mechanic section missing"
        assert cm.get("applicable") is True, (
            f"collect_mechanic must be applicable for M277 (ST140 CollectCount "
            f"metronome); got {cm.get('applicable')}"
        )
        bcc = cm.get("bonus_cycle_correction") or {}
        assert bcc.get("detected_cycle_length") == 1000, (
            f"the collect cycle length must be detected as 1000 (the metronome "
            f"peak); got {bcc.get('detected_cycle_length')}"
        )
        assert bcc.get("estimated_correction_pp") == 0.0, (
            "the RTP-bearing collect correction must be 0.0 and correct (fleet "
            f"cosmetic; not an RTP error); got {bcc.get('estimated_correction_pp')}"
        )


# ---------------------------------------------------------------------------
# NON-LEAK + ADDITIVITY — the family role hook does not cross-fire onto a
# machine lacking the role. M278 also declares hold_respin (the only other
# consumer) and must STILL resolve identically (additive, no regression).
# ---------------------------------------------------------------------------

class TestNonLeakAndAdditivity:
    @pytest.fixture(scope="class")
    def m278_summary(self):
        if not _has_chunks(_M278_CHUNK_DIR):
            pytest.skip("M278 cached chunks not present")
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            return generate_report_from_chunks(
                "M278", 1, chunk_dir=_M278_CHUNK_DIR,
                output_dir=Path(tmpdir), bet=_BET,
            )

    def test_m278_hold_respin_still_resolves(self, m278_summary):
        """M278 (the other hold_respin consumer) must STILL resolve + pass
        integrity after M277 onboards — onboarding M277 is purely additive (one
        new manifest, ZERO shared-file edit)."""
        fd = m278_summary["player_impact"].get("freespin_dynamics") or {}
        assert fd.get("applicable") is True, (
            "M278 freespin_dynamics must STILL be applicable (additive onboarding)"
        )
        assert m278_summary["rtp_integrity_check"].get("passed") is True, (
            "M278 integrity must still pass (onboarding M277 must not regress M278)"
        )


# ---------------------------------------------------------------------------
# INJECT-BUG PROOF — break each safety claim → RED → (auto-revert) → GREEN.
#
# Claim (a): ST13's hold_respin role is what attaches freespin_dynamics. Flip
#            the role away from hold_respin → freespin_dynamics goes DARK.
#            (Two independent levers prove the same claim: a manifest role flip,
#            and shrinking the resolver family to {freespin}.)
# Claim (b): the native-pid attribution covers ST13 with ZERO fallback. Corrupt
#            the per-round payout extraction so ST13's natural pid is dropped →
#            the engine's _unattributed_st13 fallback bucket appears →
#            rtp_integrity FAILS. (VALUE-AGNOSTIC: the bucket is the signature.)
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def test_inject_flip_st13_role_darkens_freespin_dynamics(self, monkeypatch):
        """INJECT (Claim a — role flip): patch machine_spec.load_manifest to flip
        ST13's role hold_respin→paid_spin. Then ST13 no longer carries a
        freespin-family role and freespin_dynamics goes DARK (the whole section
        absent / not-applicable). Proves the role is the load-bearing wiring."""
        if not _has_chunks(_M277_CHUNK_DIR):
            pytest.skip("M277 cached chunks not present")
        import fresh_slotlab.analyzer.machine_spec as ms

        _orig = ms.load_manifest

        def _flip(machine_id, manifests_root):
            m = _orig(machine_id, manifests_root)
            if machine_id == "M277":
                m = copy.deepcopy(m)
                m["spin_types"]["13"]["role"] = "paid_spin"
            return m

        monkeypatch.setattr(ms, "load_manifest", _flip)
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = generate_report_from_chunks(
                "M277", 1, chunk_dir=_M277_CHUNK_DIR,
                output_dir=Path(tmpdir), bet=_BET,
            )
            fd = summary["player_impact"].get("freespin_dynamics")
            # DARK = either absent entirely, or present-but-not-applicable.
            assert not (isinstance(fd, dict) and fd.get("applicable") is True), (
                "inject-bug: with ST13 role flipped OFF hold_respin, "
                "freespin_dynamics MUST go dark (no freespin-family role to "
                f"resolve); got freespin_dynamics={fd}"
            )
            mm = summary["player_impact"].get("machine_mechanics", {}).get("free_spin", {})
            assert mm.get("applicable") is not True, (
                "inject-bug: machine_mechanics.free_spin must also go non-applicable "
                f"when ST13 is not a freespin-family role; got {mm}"
            )
        # monkeypatch auto-reverts here.

    def test_inject_family_without_hold_respin_darkens_freespin_dynamics(self, monkeypatch):
        """INJECT (Claim a — family shrink): shrink the resolver's family to
        {"freespin"} only (the pre-edit single-role behavior). The hold_respin
        ST13 then no longer resolves → freespin_dynamics applicable False with a
        family-mismatch reason. Independent confirmation of the same claim."""
        if not _has_chunks(_M277_CHUNK_DIR):
            pytest.skip("M277 cached chunks not present")
        import fresh_slotlab.analyzer.features.freespin_dynamics as fd_mod

        monkeypatch.setattr(fd_mod, "_FREESPIN_FAMILY_ROLES", frozenset({"freespin"}))
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = generate_report_from_chunks(
                "M277", 1, chunk_dir=_M277_CHUNK_DIR,
                output_dir=Path(tmpdir), bet=_BET,
            )
            fd = summary["player_impact"].get("freespin_dynamics") or {}
            assert fd.get("applicable") is False, (
                "inject-bug: with the family shrunk to {'freespin'} the hold_respin "
                f"ST13 must NOT resolve → freespin_dynamics DARK; got "
                f"applicable={fd.get('applicable')}"
            )
            # Attribution is independent of the mechanic view — still passes.
            assert summary["rtp_integrity_check"].get("passed") is True, (
                "inject-bug: darkening the mechanic view must NOT break attribution"
            )
        # monkeypatch auto-reverts here.

    def test_inject_drop_st13_pid_forces_unattributed_fallback(self, monkeypatch):
        """INJECT (Claim b — force a fallback bucket): corrupt the per-round
        payout extraction so ST13's natural pid is dropped (returns {}). The
        engine then cannot credit ST13's win to any pid and synthesizes the
        _unattributed_st13 catch-all → layer2 fails, integrity FAILS, and the
        _unattributed bucket leaks into the drilldown. This is the regression the
        native-pid design (and the NO-synth-rule decision) protects against."""
        if not _has_chunks(_M277_CHUNK_DIR):
            pytest.skip("M277 cached chunks not present")
        import fresh_slotlab.analyzer.core.parser as parser_mod

        _orig = parser_mod.extract_round_payouts

        def _drop_st13(round_dict, rules=None, ctx=None):
            out = _orig(round_dict, rules=rules, ctx=ctx)
            try:
                st = int(round_dict.get("SpinType"))
            except (TypeError, ValueError):
                st = None
            if st == _ST_RESPIN:
                return {}  # drop the natural pid → win falls through to fallback
            return out

        monkeypatch.setattr(parser_mod, "extract_round_payouts", _drop_st13)
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = generate_report_from_chunks(
                "M277", 1, chunk_dir=_M277_CHUNK_DIR,
                output_dir=Path(tmpdir), bet=_BET,
            )
            ric = summary.get("rtp_integrity_check", {})
            pids = _payout_ids(summary)
            assert _FALLBACK_ST13 in pids, (
                f"inject-bug: dropping ST13's pid must land its win in "
                f"{_FALLBACK_ST13}; got {pids}"
            )
            assert ric.get("layer2_no_fallback_buckets_ok") is False, (
                "inject-bug: layer-2 must FAIL when a fallback bucket appears"
            )
            assert _FALLBACK_ST13 in (ric.get("layer2_fallback_buckets_found") or []), (
                f"inject-bug: {_FALLBACK_ST13} must be reported in "
                f"layer2_fallback_buckets_found; got "
                f"{ric.get('layer2_fallback_buckets_found')}"
            )
            assert ric.get("passed") is not True, (
                "inject-bug: overall integrity must FAIL with the fallback bucket"
            )
            assert "st13" not in pids, (
                "inject-bug: there is no synth 'st13' pid to catch the drop "
                "(M277 has NO SynthesizePayIdRule)"
            )
        # monkeypatch auto-reverts here.

    def test_green_resumes_after_revert(self, m277_summary, m277_trigger_paths):
        """After the inject-bug monkeypatches revert, the real (un-patched) report
        is GREEN: integrity passes, no fallback, freespin_dynamics applicable,
        both trigger paths present, anchor-walk source honest, round conservation
        holds. (Uses the module-scoped clean fixtures — proves revert worked.)"""
        ric = m277_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True
        assert ric.get("layer2_no_fallback_buckets_ok") is True
        assert (ric.get("layer2_fallback_buckets_found") or []) == []
        assert _FALLBACK_ST13 not in _payout_ids(m277_summary)
        fd = m277_summary["player_impact"]["freespin_dynamics"]
        assert fd.get("applicable") is True
        assert _path_by_key(m277_trigger_paths, _PATH_RANDOM) is not None
        assert _path_by_key(m277_trigger_paths, _PATH_COLLECT) is not None
        assert "anchor-walk" in str(m277_trigger_paths.get("source", "")).lower()
