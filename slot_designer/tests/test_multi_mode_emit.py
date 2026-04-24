"""Regression: emitter honors runtime ``mode`` override.

Prior to 2026-04-22, ``emit_simulation_to_dir`` and its callers read
``spec["mode"]`` as a single-valued field baked into the spec file.
Machines like M1 that share rules across modes (same paytable, same
evaluation_order, same single spin_type) but differ in reel weights
per mode had no way to stamp mode 2 chunks without forking the spec.

Fix: all three layers (``emit_simulation_to_dir``, ``simulate.py``,
``tune.py``) accept a ``mode`` / ``--mode`` parameter that overrides
the spec's default. Chunk envelope and per-round ``RTPId`` both
receive the override; spec's mode field stays untouched so the
same file keeps serving mode 1 by default.

Tests:
  1. emit_simulation_to_dir with ``mode=2`` stamps ``_mode=2`` on
     chunks and ``RTPId=2`` on rounds; spec file isn't mutated.
  2. Without ``mode``, default = ``spec["mode"]`` (back-compat).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.emitter.driver import emit_simulation_to_dir
from slot_designer.engine.loader import load_engine


_SPEC = _ROOT / "slot_designer" / "specs" / "M1.spec.json"
_MODE1_WEIGHTS = _ROOT / "slot_designer" / "weights" / "M1" / "mode_1" / "weights.json"


def _read_chunk(chunk_path: Path) -> dict:
    return json.loads(chunk_path.read_text(encoding="utf-8"))


def _extract_one_round(chunk: dict) -> dict:
    """Grab the first round from the first robot's roundResult."""
    robot = chunk["response"][0]
    round_result = robot["roundResult"]
    if isinstance(round_result, str):
        return json.loads(round_result)[0]
    return round_result[0]


def test_emit_simulation_respects_mode_override(tmp_path: Path):
    """``mode=2`` passed explicitly must stamp chunks + rounds with
    that value, NOT the spec's default mode=1."""
    engine, spec = load_engine(_SPEC, _MODE1_WEIGHTS)
    assert int(spec["mode"]) == 1, "sanity: spec defaults to mode 1"

    out_dir = tmp_path / "mode2_chunks"
    out_dir.mkdir()
    emit_simulation_to_dir(
        spec, engine, out_dir,
        chunks=1, robots=2, spins_per_robot=3, seed=42,
        mode=2,
    )
    chunks = sorted(out_dir.glob("chunk_*.json"))
    assert len(chunks) == 1
    chunk = _read_chunk(chunks[0])

    # Envelope carries the override
    assert chunk["_mode"] == 2, (
        f"chunk envelope _mode should reflect caller's override=2, "
        f"got {chunk['_mode']!r}"
    )
    # Per-round RTPId also overridden
    first_round = _extract_one_round(chunk)
    assert first_round["RTPId"] == 2, (
        f"round RTPId should reflect caller's override=2, "
        f"got {first_round['RTPId']!r}"
    )
    # Spec dict itself not mutated (important for shared-spec
    # multi-mode workflows)
    assert int(spec["mode"]) == 1


def test_emit_simulation_defaults_to_spec_mode(tmp_path: Path):
    """Without ``mode=`` kwarg, the emitter falls back to
    ``spec["mode"]`` — keeps existing single-mode callers working."""
    engine, spec = load_engine(_SPEC, _MODE1_WEIGHTS)
    out_dir = tmp_path / "default_mode_chunks"
    out_dir.mkdir()
    emit_simulation_to_dir(
        spec, engine, out_dir,
        chunks=1, robots=1, spins_per_robot=2, seed=99,
    )
    chunks = sorted(out_dir.glob("chunk_*.json"))
    chunk = _read_chunk(chunks[0])
    assert chunk["_mode"] == int(spec["mode"])
    assert _extract_one_round(chunk)["RTPId"] == int(spec["mode"])


def test_m1sim_registry_lists_all_shipped_modes():
    """Registry invariant: M1sim's ``modes`` list must match the set of
    mode directories on disk at ``slot_designer/weights/M1/mode_<N>/``.
    Drift here silently breaks config_md5 coverage (e.g. removing mode 5
    from the entry while leaving mode_5/weights.json behind would mean
    the machine-level md5 stops depending on it, so a re-tune of mode 5
    wouldn't roll the md5 and chunks wouldn't reclassify)."""
    registry = json.loads(
        (_ROOT / "slot_designer" / "configs" / "machines_virtual.json")
        .read_text(encoding="utf-8")
    )
    m1sim = next(
        (m for m in registry["machines"] if m["machine"] == "M1sim"), None,
    )
    assert m1sim is not None, "M1sim must be in virtual registry"

    weights_dir = _ROOT / "slot_designer" / "weights" / "M1"
    disk_modes = {
        int(p.name.split("_", 1)[1])
        for p in weights_dir.glob("mode_*")
        if p.is_dir() and (p / "weights.json").exists()
    }
    registry_modes = set(m1sim["modes"])
    assert registry_modes == disk_modes, (
        f"registry modes {sorted(registry_modes)} must match disk modes "
        f"{sorted(disk_modes)}. Drift means the machine's config_md5 "
        f"stops covering a mode whose weights file still lives on disk."
    )


def test_mode2_weights_exist_and_have_same_shape_as_mode1():
    """Mode 2 weights.json must exist and have the same per-reel stop
    count as mode 1 (since both modes share one reel_strips.json, the
    weights arrays must also have matching lengths per reel)."""
    m1_mode1 = json.loads(_MODE1_WEIGHTS.read_text(encoding="utf-8"))
    m2_path = _ROOT / "slot_designer" / "weights" / "M1" / "mode_2" / "weights.json"
    assert m2_path.exists(), f"missing mode 2 weights: {m2_path}"
    m1_mode2 = json.loads(m2_path.read_text(encoding="utf-8"))

    assert m1_mode2["machine"] == m1_mode1["machine"]
    assert m1_mode2["mode"] == 2
    r1 = m1_mode1["weights"]
    r2 = m1_mode2["weights"]
    assert len(r1) == len(r2), "reel count must match between modes"
    for reel_idx, (reel1, reel2) in enumerate(zip(r1, r2)):
        assert len(reel1) == len(reel2), (
            f"reel {reel_idx} stop count mismatch: "
            f"mode1={len(reel1)} vs mode2={len(reel2)}"
        )


def test_modes_share_reel_strips_file():
    """Invariant (2026-04-22): all modes of a machine must read from
    the SAME reel_strips.json. This is the file-layout enforcement of
    "symbol structure shared across modes" — verifying both modes' weight
    arrays align to the shared strip's shape."""
    strips_path = _ROOT / "slot_designer" / "weights" / "M1" / "reel_strips.json"
    assert strips_path.exists(), f"missing strips file: {strips_path}"
    strips = json.loads(strips_path.read_text(encoding="utf-8"))
    assert strips["machine"] == "M1"
    assert strips["reel_set"] == "default"

    # Every reel must match the archetype-declared physical length (M1 is
    # now 22 stops per IGT Triple Double Diamond archetype, 2026-04-24
    # rebuild — see reel_strips.json._archetype.physical_stops_per_reel).
    # All 3 reels must have the same length (shared strip file => single
    # length). Alternation is NOT required for M1 (TDD archetype has
    # consecutive blanks where Hot Roll bonus slot was replaced).
    expected_len = len(strips["reels"][0])
    for ri, reel in enumerate(strips["reels"]):
        assert len(reel) == expected_len, (
            f"reel {ri+1}: {len(reel)} stops; reel 1 has {expected_len} — "
            f"all reels in the same machine must share physical length."
        )

    # Both modes' weight arrays must match the strip's shape
    for mode in (1, 2):
        wp = _ROOT / "slot_designer" / "weights" / "M1" / f"mode_{mode}" / "weights.json"
        w = json.loads(wp.read_text(encoding="utf-8"))
        for ri, reel_weights in enumerate(w["weights"]):
            assert len(reel_weights) == len(strips["reels"][ri]), (
                f"mode {mode} reel {ri+1}: {len(reel_weights)} weights vs "
                f"strip has {len(strips['reels'][ri])} symbols"
            )


def test_mode2_target_file_has_plausible_numbers():
    """The synthetic target for mode 2 must have the numeric shape
    the tuner expects: rtp_pct + bucket_rate (sum ≈ hit_rate) +
    hit_rate, all internally consistent so evaluate_cost doesn't
    hit a zero-divide / NaN edge."""
    target_path = (
        _ROOT / "slot_designer" / "tuner" / "targets"
        / "M1_mode2_lucky.target.json"
    )
    assert target_path.exists(), f"missing target: {target_path}"
    t = json.loads(target_path.read_text(encoding="utf-8"))

    # User spec: hit 25-30%, RTP ~300%
    assert 0.25 <= t["hit_rate"] <= 0.30, (
        f"hit_rate {t['hit_rate']} outside user-specified 25-30% range"
    )
    assert 280 <= t["rtp_pct"] <= 320, (
        f"rtp_pct {t['rtp_pct']} outside user-specified ~300% range"
    )

    # Internal consistency: sum of bucket_rate ≈ hit_rate
    bucket_sum = sum(t["bucket_rate"].values())
    assert abs(bucket_sum - t["hit_rate"]) < 1e-9, (
        f"bucket_rate sum {bucket_sum} should equal hit_rate "
        f"{t['hit_rate']} (they're two views of the same thing)"
    )

    # Each bucket should be non-negative
    for name, rate in t["bucket_rate"].items():
        assert rate >= 0, f"negative rate {rate} for bucket {name}"


if __name__ == "__main__":
    import inspect
    import tempfile

    mod = sys.modules[__name__]
    tests = [obj for name, obj in inspect.getmembers(mod)
             if name.startswith("test_") and callable(obj)]
    passed, failures = 0, []
    for t in tests:
        try:
            sig = inspect.signature(t)
            if "tmp_path" in sig.parameters:
                with tempfile.TemporaryDirectory() as d:
                    t(tmp_path=Path(d))
            else:
                t()
            print(f"ok  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failures.append((t.__name__, e))
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if not failures else 1)
