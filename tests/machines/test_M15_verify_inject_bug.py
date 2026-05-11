"""M15 verify.py inject-bug TDD test (Stage 5 step 5 gate).

Per ``slot_designer/ONBOARDING_PROCESS.md`` §5 Stage 5 "5 通过条件":

> "故意改坏 weights → 触发对应 RED；revert → 回 baseline"

This is the only way to prove ``machines/M15/verify.py`` actually catches
regression. Without this test, verify could be GREEN by silently not
testing the invariant. Per ``feedback_adversarial_self_review.md``:

> "Verify is what I designed. Every M37 commit (v1→v5) needed user to
>  catch what verify missed."

Tests:
  1. ``test_inject_jackpot_marginal_breach`` — silently raise jackpot R2
     marginal to >0.6% in mode 1 weights → expect [JACKPOT-VIS] RED
  2. ``test_inject_blank_flank_violation`` — rearrange strip to create
     X-blank-X → expect [BLANK-FLANK] RED
  3. ``test_inject_mode7_trigger_drift`` — corrupt mode 7 R3 topdollar
     weight to push trigger > +- 5e-4 from m1 → expect [MODE7-TRIGGER] RED
  4. ``test_inject_paytable_mutation`` — modify spec.json `pays` block
     → expect [PAYTABLE-LOCK] RED (universal rule, proc_imp #36)

For each: confirm verify is RED on the targeted category, then revert
(fixture cleanup) and confirm verify is GREEN on the same category
(other categories may remain RED — we only assert the targeted lock).

Fixture strategy: copy spec / strips / v2 candidate weights to tmpdir,
mutate, run verify. tmpdir is auto-cleaned by pytest. We never touch
production files in ``slot_designer/machines/M15/``.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from session_artifacts.M15.scripts.design_v2_feasibility import (  # noqa: E402
    build_candidate_mode1,
    build_candidate_mode2,
    build_candidate_mode5,
    build_candidate_mode7,
)
from slot_designer.machines.M15 import verify as m15_verify  # noqa: E402

# v7 weights snapshot pinned to this fixtures dir — insulates this test
# from future Stage 6 tune commits that overwrite live weights. Without
# this pin, `design_v2_feasibility.load_v7_weights` reads the live
# `slot_designer/machines/M15/weights/` (which became v8 at Stage 6),
# breaking the v2 baseline reproduction (see final_critique.md "Meta-test
# fix path" Option A).
FIXTURE_V7_DIR = _ROOT / "tests" / "machines" / "fixtures" / "M15_v7_weights"


def load_v7_weights(mode: int) -> dict:
    path = FIXTURE_V7_DIR / f"mode_{mode}" / "weights.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------
# fixtures
# ----------------------------------------------------------------------

@pytest.fixture
def baseline_fixture(tmp_path: Path) -> dict:
    """Materialize v2 candidate weights + copies of spec / strips into
    a temp directory. Returns a dict of paths the test can mutate.

    Layout mirrors the production tree:
        tmp_path/
          spec.json
          reel_strips.json
          weights/
            mode_1/weights.json
            mode_2/weights.json
            mode_5/weights.json
            mode_7/weights.json
    """
    # Copy spec + strips
    spec_src = m15_verify.DEFAULT_SPEC
    strips_src = m15_verify.DEFAULT_STRIPS
    spec_dst = tmp_path / "spec.json"
    strips_dst = tmp_path / "reel_strips.json"
    shutil.copy(spec_src, spec_dst)
    shutil.copy(strips_src, strips_dst)

    # Build v2 candidate weights
    v7 = {m: load_v7_weights(m) for m in (1, 2, 5, 7)}
    m1 = build_candidate_mode1(v7[1])
    m2 = build_candidate_mode2(v7[2], v7[1])
    m5 = build_candidate_mode5(v7[5], m2)
    m7 = build_candidate_mode7(v7[7], m1)

    weights_dir = tmp_path / "weights"
    weights_paths = {}
    for mode, doc in [(1, m1), (2, m2), (5, m5), (7, m7)]:
        mode_dir = weights_dir / f"mode_{mode}"
        mode_dir.mkdir(parents=True)
        wpath = mode_dir / "weights.json"
        wpath.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        weights_paths[mode] = wpath

    return {
        "tmp_path": tmp_path,
        "spec": spec_dst,
        "strips": strips_dst,
        "weights_dir": weights_dir,
        "weights_paths": weights_paths,
    }


def _run_verify(fixture: dict, *, paytable_hash: str | None = None) -> list:
    """Run verify against the fixture, return checks list."""
    checks, _exit = m15_verify.run_verification(
        spec_path=fixture["spec"],
        strips_path=fixture["strips"],
        weights_dir=fixture["weights_dir"],
        paytable_baseline_hash=paytable_hash,
    )
    return checks


def _checks_in_category(checks: list, category: str) -> list:
    return [c for c in checks if c.category == category]


def _any_red_in_category(checks: list, category: str) -> bool:
    return any(c.is_failing() for c in _checks_in_category(checks, category))


def _no_red_in_category(checks: list, category: str) -> bool:
    return all(not c.is_failing() for c in _checks_in_category(checks, category))


def _baseline_red_categories(checks: list) -> set[str]:
    """Returns set of categories that already RED on the baseline (the
    expected RTP RED on m2/m5/m7). Used to subtract baseline noise from
    inject-bug assertion."""
    return {c.category for c in checks if c.is_failing()}


# ----------------------------------------------------------------------
# helper: load + mutate weights for one mode
# ----------------------------------------------------------------------

def _read_weights(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_weights(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _set_symbol_weight(doc: dict, strip_reel: list, reel_idx: int,
                       symbol: str, new_weight: int) -> None:
    """Set every stop weight on this reel where symbol == sym."""
    for i, s in enumerate(strip_reel):
        if s == symbol:
            doc["weights"][reel_idx][i] = new_weight


# ----------------------------------------------------------------------
# test 1: jackpot marginal breach -> [JACKPOT-VIS] RED
# ----------------------------------------------------------------------

def test_inject_jackpot_marginal_breach(baseline_fixture):
    """Bug class 1: silently raise jackpot R2 marginal to >0.6% in mode 1.

    Mechanism: increase mode 1 R2 jackpot stop weight from 4 → 40, making
    jackpot R2 marginal ~7% (well above user_brief #6 cap 0.6%).

    Pre: baseline run should NOT have [JACKPOT-VIS] RED (clean cap).
    Inject: weight 4 → 40.
    Post: [JACKPOT-VIS] should now have at least one RED on mode 1 R2.
    Revert: restore weight 4. Final run should clear the [JACKPOT-VIS]
    RED again (proving the fixture isn't permanently dirty).
    """
    # === baseline: no [JACKPOT-VIS] RED expected ===
    baseline_checks = _run_verify(baseline_fixture)
    assert _no_red_in_category(baseline_checks, "JACKPOT-VIS"), (
        "baseline shouldn't have JACKPOT-VIS RED before inject; check fixture"
    )

    # === inject: raise R2 jackpot weight on mode 1 ===
    wpath = baseline_fixture["weights_paths"][1]
    doc = _read_weights(wpath)
    strips = json.loads(baseline_fixture["strips"].read_text(encoding="utf-8"))
    r2_strip = strips["reels"][1]
    original_weight = None
    for i, s in enumerate(r2_strip):
        if s == "jackpot":
            if original_weight is None:
                original_weight = doc["weights"][1][i]
            doc["weights"][1][i] = 40
    assert original_weight is not None, "fixture: jackpot not found on R2"
    _write_weights(wpath, doc)

    # === verify: should RED on [JACKPOT-VIS] for mode 1 R2 ===
    injected_checks = _run_verify(baseline_fixture)
    jv_checks = _checks_in_category(injected_checks, "JACKPOT-VIS")
    r2_fail = [c for c in jv_checks if c.mode == 1 and "R2" in c.label and c.is_failing()]
    assert len(r2_fail) > 0, (
        f"inject-bug should have triggered JACKPOT-VIS RED on mode 1 R2; "
        f"got JACKPOT-VIS checks: {[(c.label, c.ok) for c in jv_checks]}"
    )

    # === revert: restore original weight ===
    for i, s in enumerate(r2_strip):
        if s == "jackpot":
            doc["weights"][1][i] = original_weight
    _write_weights(wpath, doc)
    reverted_checks = _run_verify(baseline_fixture)
    assert _no_red_in_category(reverted_checks, "JACKPOT-VIS"), (
        "after revert, [JACKPOT-VIS] should return to clean"
    )


# ----------------------------------------------------------------------
# test 2: blank-flank violation -> [BLANK-FLANK] RED
# ----------------------------------------------------------------------

def test_inject_blank_flank_violation(baseline_fixture):
    """Bug class 2: rearrange strip to create X-blank-X.

    The current strips have strict blank/non-blank alternation. To create
    X-blank-X we need two adjacent non-blank positions of the same symbol
    flanking a blank — but the alternation invariant means non-blanks are
    never adjacent on the strip. So we need to put the same symbol at
    positions p-1 and p+1 (both non-blank stops surrounding a blank).

    Easiest mutation: swap one stop on R1 to make positions 1, 3 both
    "cherry" (currently pos 1 = cherry, pos 3 = 3bar). After mutation:
    pos 1 = cherry, pos 2 = blank, pos 3 = cherry → X-blank-X violation.
    """
    # === baseline: 0 violations ===
    baseline_checks = _run_verify(baseline_fixture)
    assert _no_red_in_category(baseline_checks, "BLANK-FLANK")

    # === inject: mutate strip pos 3 of R1 to "cherry" (was "3bar") ===
    strips_doc = json.loads(
        baseline_fixture["strips"].read_text(encoding="utf-8")
    )
    original_pos3 = strips_doc["reels"][0][3]
    assert original_pos3 != "cherry", \
        f"fixture: R1 pos 3 unexpectedly already cherry"
    strips_doc["reels"][0][3] = "cherry"
    baseline_fixture["strips"].write_text(
        json.dumps(strips_doc, indent=2), encoding="utf-8"
    )

    # === verify: [BLANK-FLANK] should now RED on R1 (cherry-blank-cherry at pos 1-2-3) ===
    injected_checks = _run_verify(baseline_fixture)
    bf_checks = _checks_in_category(injected_checks, "BLANK-FLANK")
    r1_fail = [c for c in bf_checks if "R1" in c.label and c.is_failing()]
    assert len(r1_fail) > 0, (
        f"inject-bug should have triggered BLANK-FLANK RED on R1; "
        f"got: {[(c.label, c.ok) for c in bf_checks]}"
    )

    # === revert ===
    strips_doc["reels"][0][3] = original_pos3
    baseline_fixture["strips"].write_text(
        json.dumps(strips_doc, indent=2), encoding="utf-8"
    )
    reverted_checks = _run_verify(baseline_fixture)
    assert _no_red_in_category(reverted_checks, "BLANK-FLANK")


# ----------------------------------------------------------------------
# test 3: mode 7 trigger drift -> [MODE7-TRIGGER] RED
# ----------------------------------------------------------------------

def test_inject_mode7_trigger_drift(baseline_fixture):
    """Bug class 3: corrupt mode 7 R3 topdollar weight so trigger drifts
    more than +- 5e-4 from mode 1.

    v2 candidate has m1 R3 topdollar = 8 and m7 R3 topdollar = 7 with
    trigger diff ~4.9e-4 (PASSES at edge of 5e-4 tolerance). Push m7 to
    5 → m7 trigger drops below m1 by ~2.5e-3 (well over tolerance).
    """
    # === baseline ===
    baseline_checks = _run_verify(baseline_fixture)
    assert _no_red_in_category(baseline_checks, "MODE7-TRIGGER")

    # === inject: cut m7 R3 topdollar weight from 7 -> 4 ===
    wpath = baseline_fixture["weights_paths"][7]
    doc = _read_weights(wpath)
    strips = json.loads(baseline_fixture["strips"].read_text(encoding="utf-8"))
    r3_strip = strips["reels"][2]
    originals: list[tuple[int, int]] = []
    for i, s in enumerate(r3_strip):
        if s == "topdollar":
            originals.append((i, doc["weights"][2][i]))
            doc["weights"][2][i] = 4
    assert originals, "fixture: topdollar not found on R3"
    _write_weights(wpath, doc)

    # === verify: [MODE7-TRIGGER] should RED ===
    injected_checks = _run_verify(baseline_fixture)
    assert _any_red_in_category(injected_checks, "MODE7-TRIGGER"), (
        f"inject-bug should trigger MODE7-TRIGGER RED; got: "
        f"{[(c.label, c.ok) for c in _checks_in_category(injected_checks, 'MODE7-TRIGGER')]}"
    )

    # === revert ===
    for i, w in originals:
        doc["weights"][2][i] = w
    _write_weights(wpath, doc)
    reverted_checks = _run_verify(baseline_fixture)
    assert _no_red_in_category(reverted_checks, "MODE7-TRIGGER")


# ----------------------------------------------------------------------
# test 4: paytable mutation -> [PAYTABLE-LOCK] RED (universal rule)
# ----------------------------------------------------------------------

def test_inject_paytable_mutation(baseline_fixture):
    """Bug class 4: modify spec.json `pays` block. Universal rule
    (process_improvements #36): paytable is immutable cross-machine.

    Mechanism: change pay_id 1 multiplier from 200 → 300. Recompute
    paytable hash; old hash mismatches new.
    """
    # === baseline ===
    baseline_checks = _run_verify(baseline_fixture)
    assert _no_red_in_category(baseline_checks, "PAYTABLE-LOCK")

    # === inject: mutate pay_id 1 multiplier ===
    spec_doc = json.loads(baseline_fixture["spec"].read_text(encoding="utf-8"))
    original = None
    for pay in spec_doc["pays"]:
        if pay.get("pay_id") == 1:
            original = pay["multiplier"]
            pay["multiplier"] = 300  # was 200
            break
    assert original == 200, f"fixture: unexpected pay_id 1 multiplier {original}"
    baseline_fixture["spec"].write_text(
        json.dumps(spec_doc, indent=2), encoding="utf-8"
    )

    # === verify: [PAYTABLE-LOCK] should RED ===
    injected_checks = _run_verify(baseline_fixture)
    assert _any_red_in_category(injected_checks, "PAYTABLE-LOCK"), (
        f"inject-bug should trigger PAYTABLE-LOCK RED; got: "
        f"{[(c.label, c.ok) for c in _checks_in_category(injected_checks, 'PAYTABLE-LOCK')]}"
    )

    # === revert ===
    for pay in spec_doc["pays"]:
        if pay.get("pay_id") == 1:
            pay["multiplier"] = original
            break
    baseline_fixture["spec"].write_text(
        json.dumps(spec_doc, indent=2), encoding="utf-8"
    )
    reverted_checks = _run_verify(baseline_fixture)
    assert _no_red_in_category(reverted_checks, "PAYTABLE-LOCK")


# ----------------------------------------------------------------------
# meta-test: baseline iter0 pattern matches Stage 5 expected
# ----------------------------------------------------------------------

def test_baseline_v2_iter0_pattern(baseline_fixture):
    """Meta-test: confirm the v2 candidate baseline pattern matches the
    Stage 5 expected output.

    Expected (per session_artifacts/M15/verify_run_v2_iter0.txt):
      * 3 [RTP] REDs on m2/m5/m7 (tuner-closable)
      * No other category should be RED on the baseline candidate

    This guards against a future verify.py refactor that quietly stops
    catching the iter0 RTP NEAR-MISS (which would be a regression — V
    would think the design is done when it's actually pre-tune).
    """
    checks = _run_verify(baseline_fixture)
    red_categories = _baseline_red_categories(checks)
    assert red_categories == {"RTP"}, (
        f"v2 baseline iter0 should RED ONLY on [RTP] (tuner-closable); "
        f"got REDs in: {red_categories}"
    )
    rtp_red = [c for c in checks if c.category == "RTP" and c.is_failing()]
    rtp_modes = {c.mode for c in rtp_red}
    assert rtp_modes == {2, 5, 7}, (
        f"v2 baseline RTP REDs should be modes 2/5/7; got: {rtp_modes}"
    )
