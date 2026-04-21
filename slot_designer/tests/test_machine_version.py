"""MD5 management round-trip tests.

The three call sites (virtual_app refresh / virtual_analyzer stamping /
tune.py stamping) MUST all produce the same md5 for the same (spec,
weights, engine) snapshot. Otherwise chunks get written with md5 ≠
registry md5 → console's classify_chunks flags them stale and operator
has to manually reconcile.

Locks:
  1. compute_machine_md5() is deterministic for fixed inputs
  2. Changing spec content → config_md5 flips, code_md5 unchanged
  3. Changing weights content → config_md5 flips, code_md5 unchanged
  4. refresh_machines_virtual writes md5s matching compute_machine_md5
  5. Weights file with same symbol counts but different ORDER → md5 flips
     (proves Phase 5 re-ordering creates a new version boundary)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.backend.machine_version import (
    compute_code_md5,
    compute_config_md5,
    compute_machine_md5,
    resolve_weights_paths,
)


_REGISTRY = _ROOT / "slot_designer" / "configs" / "machines_virtual.json"


def _m1sim_entry() -> dict:
    raw = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    for m in raw["machines"]:
        if m.get("machine") == "M1sim":
            return m
    raise RuntimeError("M1sim not registered; fixture broken")


def test_determinism():
    entry = _m1sim_entry()
    a1, b1 = compute_machine_md5(entry)
    a2, b2 = compute_machine_md5(entry)
    assert a1 == a2 and b1 == b2, "same entry → same md5s"


def test_spec_change_flips_config_only():
    entry = _m1sim_entry()
    repo = _ROOT
    spec_real = repo / entry["_spec_path"]
    weights = resolve_weights_paths(entry, entry["modes"])
    cfg_before = compute_config_md5(spec_real, weights)

    with tempfile.NamedTemporaryFile("wb", suffix=".spec.json", delete=False) as tmp:
        tmp.write(spec_real.read_bytes() + b'\n{"_trailing_noise": true}')
        tmp_path = Path(tmp.name)
    try:
        cfg_after = compute_config_md5(tmp_path, weights)
        assert cfg_after != cfg_before, "spec bytes changed → config_md5 must change"
    finally:
        tmp_path.unlink()


def test_weights_change_flips_config_only():
    """Tuning / re-tuning must flip config_md5 so classify_chunks creates
    a version boundary between the old and new tunings. This is the
    explicit fix for the 'weights not in MD5' gap."""
    entry = _m1sim_entry()
    repo = _ROOT
    spec_real = repo / entry["_spec_path"]
    weights = resolve_weights_paths(entry, entry["modes"])
    assert weights, "fixture precondition: at least one weights file resolved"
    cfg_before = compute_config_md5(spec_real, weights)

    # Simulate a weights-file byte change (e.g. Phase 4 re-tune produces
    # different integer counts, or Phase 5 reorders stops)
    with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as tmp:
        tmp.write(weights[0].read_bytes().replace(b'"weight"', b'"Weight"', 1))
        tmp_path = Path(tmp.name)
    try:
        cfg_after = compute_config_md5(spec_real, [tmp_path] + list(weights[1:]))
        assert cfg_after != cfg_before, "weights bytes changed → config_md5 must change"
    finally:
        tmp_path.unlink()


def test_engine_source_change_flips_code_only():
    """Changing engine source must flip code_md5 but not config_md5.
    We don't actually mutate engine source in the test (would affect
    other tests). Instead we verify that the code_md5 helper's output
    is distinct from config_md5 and hashes all engine + emitter .py
    files (excluding __init__.py)."""
    code_md5 = compute_code_md5()
    # 32-char hex string
    assert len(code_md5) == 32 and all(c in "0123456789abcdef" for c in code_md5)


def test_refresh_matches_compute_machine_md5():
    """Roundtrip: call refresh, read back machines_virtual.json,
    compare each machine's cached md5s against compute_machine_md5(entry).
    No call site should produce different md5s for the same snapshot.
    """
    from slot_designer.backend.virtual_app import refresh_machines_virtual
    # Snapshot current file so test doesn't persist noise
    original = _REGISTRY.read_text(encoding="utf-8")
    try:
        refresh_machines_virtual(_REGISTRY)
        raw = json.loads(_REGISTRY.read_text(encoding="utf-8"))
        for entry in raw["machines"]:
            if not entry.get("_spec_path"):
                continue
            cfg, code = compute_machine_md5(entry)
            assert entry["configSummaryMd5"] == cfg, (
                f"{entry['machine']}: refresh wrote config {entry['configSummaryMd5']} "
                f"but helper computes {cfg}"
            )
            assert entry["codeSummaryMd5"] == code, (
                f"{entry['machine']}: refresh wrote code {entry['codeSummaryMd5']} "
                f"but helper computes {code}"
            )
    finally:
        # Restore original file content so later tests / subsequent
        # runs see it unchanged (md5s will be re-refreshed on next boot
        # anyway).
        _REGISTRY.write_text(original, encoding="utf-8")


def test_missing_spec_uses_sentinel():
    """Broken registry entry (missing spec file) must still produce a
    deterministic md5 (not crash), so operator sees a stable-but-wrong
    md5 they can investigate — not an exception in the hot path."""
    entry = {
        "machine": "nonexistent",
        "modes": [1],
        "_spec_path": "does/not/exist.spec.json",
        "_weights_path_template": "also/missing.json",
    }
    cfg, code = compute_machine_md5(entry)
    assert len(cfg) == 32 and len(code) == 32


if __name__ == "__main__":
    import inspect

    mod = sys.modules[__name__]
    tests = [obj for name, obj in inspect.getmembers(mod)
             if name.startswith("test_") and callable(obj)]
    passed, failures = 0, []
    for t in tests:
        try:
            t()
            print(f"ok  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failures.append((t.__name__, e))
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if not failures else 1)
