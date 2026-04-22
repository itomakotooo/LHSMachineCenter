"""Regression: dev rawdata stays in ``_dev_scratch/``, never leaks into
the virtual console's rawdata pool (``slot_designer/rawdata/``).

Locks the 2026-04-21 boundary fix: before this, ``simulate.py`` wrote
to ``slot_designer/rawdata/<m>/mode_<n>/`` directly, which meant
re-sampling overwrote the console's chunks (same chunk_index, different
md5). Now dev sampling defaults to
``slot_designer/_dev_scratch/rawdata/<m>/mode_<n>/`` and the console's
rawdata is populated only via ``POST /api/batch-run`` → virtual_analyzer.

Invariants:
  1. ``simulate.py`` default out-dir resolves under ``_dev_scratch/``,
     never under ``slot_designer/rawdata/``.
  2. End-to-end: running ``simulate.py`` with default out-dir creates
     chunks in ``_dev_scratch/``, leaves ``slot_designer/rawdata/`` alone.
  3. Re-running simulate wipes pre-existing ``chunk_*.json`` in the
     target dir (fresh-slate semantics; no mixing md5 versions silently).
  4. The wipe only touches ``chunk_*.json`` — unrelated operator files
     are preserved (safety net if ``--out-dir`` accidentally points
     outside the scratch root).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.scripts.simulate import (
    _DEV_SCRATCH_ROOT,
    _resolve_default_out_dir,
    _wipe_chunks,
)


_SPEC = _ROOT / "slot_designer" / "specs" / "M1.spec.json"
_WEIGHTS = _ROOT / "slot_designer" / "weights" / "M1" / "mode_1" / "weights.json"
_CONSOLE_RAWDATA = _ROOT / "slot_designer" / "rawdata"


def _dev_scratch_dir(machine: str, mode: int) -> Path:
    return _resolve_default_out_dir(machine, mode)


def test_default_out_dir_is_under_dev_scratch():
    """The resolved default must live under ``_dev_scratch/``, never
    under the console's ``slot_designer/rawdata/`` root. If someone
    'fixes' simulate.py to default back to console rawdata, this
    catches it."""
    out = _resolve_default_out_dir("M1sim", 1)
    # Normalize to an absolute path so the substring check is stable
    # across Windows backslashes vs POSIX slashes.
    s = str(out.resolve()).replace("\\", "/")
    assert "/_dev_scratch/rawdata/" in s, (
        f"default out-dir must live under _dev_scratch/rawdata/, got: {s}"
    )
    assert "slot_designer/rawdata/M1sim" not in s, (
        f"default out-dir must NOT target the console's rawdata pool, "
        f"got: {s}"
    )
    # Sanity: the declared root constant is what we resolve against.
    assert _DEV_SCRATCH_ROOT in out.parents or _DEV_SCRATCH_ROOT == out.parent.parent


def test_wipe_chunks_only_removes_chunk_jsons():
    """The wipe-before-simulate step is bounded to ``chunk_*.json``.
    Keeps operator-owned files safe even if ``--out-dir`` accidentally
    points at a directory that isn't the scratch root."""
    scratch = _DEV_SCRATCH_ROOT / "_test" / "wipe_scope"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        (scratch / "chunk_0001.json").write_text("{}", encoding="utf-8")
        (scratch / "chunk_0002.json").write_text("{}", encoding="utf-8")
        keep = scratch / "operator_notes.md"
        keep.write_text("don't delete me", encoding="utf-8")
        also_keep = scratch / "other.json"
        also_keep.write_text("[]", encoding="utf-8")

        removed = _wipe_chunks(scratch)
        assert removed == 2, f"expected to wipe 2 chunks, got {removed}"
        remaining = sorted(p.name for p in scratch.iterdir())
        assert remaining == ["operator_notes.md", "other.json"], (
            f"wipe touched non-chunk files! remaining: {remaining}"
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_simulate_default_writes_to_dev_scratch_and_not_console_rawdata():
    """End-to-end: run ``simulate.py`` with default out-dir, verify
    chunks land in ``_dev_scratch/``, console rawdata stays empty.

    The 2026-04-21 bug was: simulate.py writing to console rawdata by
    default → any dev iteration collided with the console's own data.
    This test fails loudly if that default ever regresses.
    """
    target_machine = "M1sim"
    target_mode = 1
    dev_dir = _dev_scratch_dir(target_machine, target_mode)
    console_dir = _CONSOLE_RAWDATA / target_machine

    # Clean state pre-test
    shutil.rmtree(dev_dir, ignore_errors=True)
    console_existed_before = console_dir.exists()
    console_chunks_before = (
        sorted(p.name for p in (console_dir / f"mode_{target_mode}").glob("chunk_*.json"))
        if console_existed_before and (console_dir / f"mode_{target_mode}").is_dir()
        else []
    )

    # Run simulate with just 1 chunk (fast). Small robot/spin counts
    # keep the test under 1s.
    cmd = [
        sys.executable, "-m", "slot_designer.scripts.simulate",
        "--spec", str(_SPEC),
        "--weights", str(_WEIGHTS),
        "--chunks", "1",
        "--robots", "1",
        "--spins-per-robot", "10",
        "--machine-name", target_machine,
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        cmd, cwd=str(_ROOT), capture_output=True, text=True, env=env,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"simulate.py failed (rc={proc.returncode})\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )

    # Dev scratch got the chunk
    dev_chunks = sorted(p.name for p in dev_dir.glob("chunk_*.json"))
    assert dev_chunks == ["chunk_0001.json"], (
        f"expected chunk_0001.json in {dev_dir}, got {dev_chunks}.\n"
        f"stdout: {proc.stdout}"
    )

    # Console rawdata was NOT touched
    console_chunks_after = (
        sorted(p.name for p in (console_dir / f"mode_{target_mode}").glob("chunk_*.json"))
        if (console_dir / f"mode_{target_mode}").is_dir()
        else []
    )
    assert console_chunks_after == console_chunks_before, (
        f"simulate.py wrote into the console's rawdata pool!\n"
        f"before: {console_chunks_before}\nafter:  {console_chunks_after}\n"
        f"(dev sampling must stay in _dev_scratch; console rawdata is "
        f"only written by virtual_analyzer via POST /api/batch-run)"
    )


def test_simulate_wipes_chunks_on_rerun():
    """Re-running simulate with the same out-dir must NOT mix old and
    new chunks. Fresh simulate = fresh data; old chunks are wiped before
    new ones emit. Matches the 'no retention' contract for dev rawdata.
    """
    target_machine = "M1sim"
    target_mode = 1
    dev_dir = _dev_scratch_dir(target_machine, target_mode)
    shutil.rmtree(dev_dir, ignore_errors=True)

    # Seed with a decoy chunk_0001.json pretending to be an older run.
    # A real simulate must blow this away before writing its own
    # chunk_0001.json (fresh content, current md5).
    dev_dir.mkdir(parents=True, exist_ok=True)
    decoy = dev_dir / "chunk_0001.json"
    decoy.write_text('{"_decoy": true, "_config_md5": "deadbeef"}', encoding="utf-8")
    # Also a chunk that simulate at chunks=1 wouldn't naturally produce;
    # it should also be wiped (indices above N shouldn't linger).
    stale_high = dev_dir / "chunk_0077.json"
    stale_high.write_text('{"_decoy": true}', encoding="utf-8")

    cmd = [
        sys.executable, "-m", "slot_designer.scripts.simulate",
        "--spec", str(_SPEC),
        "--weights", str(_WEIGHTS),
        "--chunks", "1",
        "--robots", "1",
        "--spins-per-robot", "10",
        "--machine-name", target_machine,
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        cmd, cwd=str(_ROOT), capture_output=True, text=True, env=env,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"simulate.py failed (rc={proc.returncode})\nstderr:\n{proc.stderr}"
    )

    # Only chunk_0001.json should exist, and it must be the real sim
    # output (not our decoy).
    remaining = sorted(p.name for p in dev_dir.glob("chunk_*.json"))
    assert remaining == ["chunk_0001.json"], (
        f"stale chunk_0077.json should have been wiped; got {remaining}"
    )
    payload = json.loads((dev_dir / "chunk_0001.json").read_text(encoding="utf-8"))
    assert not payload.get("_decoy"), (
        "chunk_0001.json still contains decoy content — the wipe didn't "
        "run before emission, so old chunks silently persisted"
    )
    # Real sim chunks carry a response list, not our decoy markers.
    assert "response" in payload, (
        f"chunk_0001.json missing 'response' field (not a real sim output): "
        f"{list(payload.keys())[:10]}"
    )


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
