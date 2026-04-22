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
_MODE1_WEIGHTS = _ROOT / "slot_designer" / "weights" / "M1_mode1.current.json"


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


def test_m1sim_registry_has_modes_1_and_2():
    """Registry invariant: M1sim must list both mode 1 and mode 2 now
    that the lucky-mode weights live on disk. If someone removes mode 2
    from the entry without archiving the weights, the
    ``_weights_fallback_template`` still resolves to a real file →
    compute_machine_md5 would quietly exclude mode 2 from the config
    hash, causing silent drift between disk and registry."""
    registry = json.loads(
        (_ROOT / "slot_designer" / "configs" / "machines_virtual.json")
        .read_text(encoding="utf-8")
    )
    m1sim = next(
        (m for m in registry["machines"] if m["machine"] == "M1sim"), None,
    )
    assert m1sim is not None, "M1sim must be in virtual registry"
    assert set(m1sim["modes"]) == {1, 2}, (
        f"M1sim modes should be [1, 2]; got {m1sim['modes']!r}"
    )


def test_mode2_seed_weights_exist_and_have_same_shape_as_mode1():
    """M1_mode2.current.json is the tuner's starting point. It must
    exist and have the same schema as mode 1 so the same engine +
    tuner code path works without branching on mode."""
    m1_mode1 = json.loads(_MODE1_WEIGHTS.read_text(encoding="utf-8"))
    m2_path = _ROOT / "slot_designer" / "weights" / "M1_mode2.current.json"
    assert m2_path.exists(), f"missing seed file: {m2_path}"
    m1_mode2 = json.loads(m2_path.read_text(encoding="utf-8"))

    assert m1_mode2["machine"] == m1_mode1["machine"]
    assert m1_mode2["mode"] == 2
    # Both must have the same reel-set shape (same # reels, same # stops)
    r1 = m1_mode1["reel_sets"]["default"]["reels"]
    r2 = m1_mode2["reel_sets"]["default"]["reels"]
    assert len(r1) == len(r2), "reel count must match between modes"
    for reel_idx, (reel1, reel2) in enumerate(zip(r1, r2)):
        assert len(reel1) == len(reel2), (
            f"reel {reel_idx} stop count mismatch: "
            f"mode1={len(reel1)} vs mode2={len(reel2)}"
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
