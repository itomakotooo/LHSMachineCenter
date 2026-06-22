"""M93 re-onboarding — VALUE-AGNOSTIC regression guard.

M93 was HELD: its report RTP was 10745% vs a true 88.4%, because the spin cost is
ECHOED onto a feature round (ST82 DiamondManiaFreespin, CostCredits=1000) while the
paid base spin (ST13 LockReSpin) carries CostCredits=0. The "paid ⟺ CostCredits>0"
session count collapsed to 329 cost-bearing groups vs the true 40000 base spins, AND
the deriver inverted the classification (ST82→paid base, ST13→free feature).

Fixed in two base-EXCLUDED + one closure change (commits a6d0a0e parser + this
re-onboard): generalized `cost_credits_unreliable` (cost-bearing SpinTimes ⊊ all
SpinTimes ⇒ count paid units by distinct SpinTimes; deriver economy/position from the
mechanism). M93 then classifies correctly (ST13 paid_spin/LockReSpin base, ST82/ST83
freespin features, ST2 wheel) and onboards: 40000 paid spins, integrity clean.

VALUE-AGNOSTIC per the charter: STRUCTURE / DENOMINATOR-CORRECTNESS / INTEGRITY /
classification invariants only — never an RTP value or range (M93's numbers drift on
re-sample). The hard constants are the structural ST ids (13/82/83/2), the declared
roles, and the paid-unit count == distinct SpinTimes invariant (the bug's signature).
"""
from __future__ import annotations

import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CHUNK_DIR = _ROOT / "rawdata" / "M93" / "mode_1"
_MANIFEST = _ROOT / "configs" / "machine_manifests" / "M93.json"
_BET = 1000


def _has_chunks() -> bool:
    return _CHUNK_DIR.exists() and len(list(_CHUNK_DIR.glob("chunk_*.json"))) > 0


@pytest.fixture(scope="module")
def m93_summary():
    if not _has_chunks():
        pytest.skip("M93 cached chunks not present")
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    with tempfile.TemporaryDirectory() as out:
        return generate_report_from_chunks(
            "M93", 1, chunk_dir=_CHUNK_DIR, output_dir=Path(out), bet=_BET
        )


@pytest.fixture(scope="module")
def m93_manifest():
    if not _MANIFEST.exists():
        pytest.skip("M93 manifest not present")
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


class TestM93Registered:
    def test_manifest_declares_four_spin_types(self, m93_manifest):
        sts = m93_manifest.get("spin_types") or {}
        assert set(sts) == {"13", "82", "83", "2"}, f"M93 STs: {sorted(sts)}"

    def test_base_is_paid_spin_features_are_free(self, m93_manifest):
        sts = m93_manifest["spin_types"]
        assert sts["13"]["role"] == "paid_spin"        # LockReSpin base
        assert sts["13"]["play"] == "LockReSpin"
        assert sts["82"]["role"] == "freespin"          # DiamondManiaFreespin
        assert sts["83"]["role"] == "freespin"          # DiamondManiaFreespinWheel
        assert sts["2"]["role"] == "settlement"         # Wheel


class TestM93Report:
    def test_report_generates_no_feature_errors(self, m93_summary):
        assert m93_summary["machine"] == "M93"
        assert not m93_summary.get("feature_errors"), m93_summary.get("feature_errors")

    def test_paid_spins_is_distinct_spin_times_not_cost_groups(self, m93_summary):
        """The bug's signature: paid_spins must be the 40000 base spins (distinct
        SpinTimes), NOT the 329 cost-bearing ST82 groups. Value-agnostic — asserts the
        count equals the requested sample size (8 robots × 5000), not an RTP value."""
        paid = int(m93_summary["sampling"]["paid_spins"])
        # distinct SpinTimes == the requested base spins for this cached sample.
        n_distinct = 0
        for cf in sorted(_CHUNK_DIR.glob("chunk_*.json")):
            d = json.loads(cf.read_text(encoding="utf-8"))
            for rob in d["response"]:
                rr = rob.get("roundResult")
                if isinstance(rr, str):
                    rr = json.loads(rr)
                n_distinct += len({r.get("SpinTimes") for r in (rr or []) if r.get("SpinTimes") is not None})
        assert paid == n_distinct, (
            f"paid_spins={paid} != distinct SpinTimes={n_distinct}. The cost-echo "
            f"denominator bug has regressed (paid units must be counted by distinct "
            f"SpinTimes, not cost-bearing groups)."
        )

    def test_integrity_clean_no_fallback_buckets(self, m93_summary):
        ic = m93_summary.get("rtp_integrity_check", {}) or {}
        assert ic.get("passed") is True, ic.get("summary_message")
        assert (ic.get("layer2_fallback_buckets_found") or []) == [], (
            "M93 has fallback buckets — ST83 DiamondManiaFreespinWheel win must be "
            "attributed (the m93_st83_freespinwheel_settlement synth rule)."
        )


class TestM93Classification:
    def test_cost_credits_unreliable_detected(self):
        if not _has_chunks():
            pytest.skip("M93 cached chunks not present")
        from fresh_slotlab.analyzer.core.parser import parse_rounds
        from fresh_slotlab.analyzer.spin_type_deriver import derive_cost_credits_unreliable
        d = json.loads(sorted(_CHUNK_DIR.glob("chunk_*.json"))[0].read_text(encoding="utf-8"))
        rbs = defaultdict(list)
        for rob in d["response"]:
            for r in parse_rounds(rob):
                rbs[str(r.get("SpinType"))].append(r)
        assert derive_cost_credits_unreliable(rbs) is True, (
            "M93 must be detected cost_credits_unreliable (cost echoed on ST82)."
        )

    def test_classification_gate_clean(self, m93_manifest):
        if not _has_chunks():
            pytest.skip("M93 cached chunks not present")
        from fresh_slotlab.analyzer.core.parser import parse_rounds
        from fresh_slotlab.analyzer.spin_type_classification_gate import check_machine
        d = json.loads(sorted(_CHUNK_DIR.glob("chunk_*.json"))[0].read_text(encoding="utf-8"))
        rbs = defaultdict(list)
        prevby = defaultdict(Counter)
        for rob in d["response"]:
            prev = None
            for r in parse_rounds(rob):
                st = str(r.get("SpinType"))
                rbs[st].append(r)
                if prev is not None:
                    prevby[st][prev] += 1
                prev = st
        violations = check_machine(
            m93_manifest, rbs, machine_has_paid_base=True, prev_st_counts=prevby
        )
        assert violations == [], f"M93 classification violations: {violations}"
