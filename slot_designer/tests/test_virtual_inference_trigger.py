"""Regression: virtual_analyzer auto-triggers inference scripts
(infer_paytable + verify_machine_labels) after delegate finishes.

2026-04-22 bug follow-up: the Pay ID 总览 panel on virtual console
stays at "形状推断暂未运行" after user samples via UI. The real
console has ``_run_post_analyzer_inference`` wired into
``_run_generate_report`` (in-process generate-report path), but the
SAMPLING path goes through ``_watch_run`` → no inference trigger.

Fix: mirror the inference trigger inside ``virtual_analyzer.py``'s
delegate flow. Runs the same two CLI scripts (infer_paytable.py +
verify_machine_labels.py) with ``SLOT_RAWDATA_ROOT`` pointed at
``slot_designer/rawdata``, writing to
``slot_designer/configs/paytables_virtual`` +
``slot_designer/dev_reports/_classify``.

Keeps the fix OUT of ``src/web_console/backend/app.py`` per the
structural guideline.

Tests:
  1. ``_run_inference_scripts(machine, mode)`` writes the expected
     paytable shape JSON.
  2. Missing rawdata → best-effort skip; no exception raised.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.backend.virtual_analyzer import _run_inference_scripts


_PAYTABLES_VIRTUAL = _ROOT / "slot_designer" / "configs" / "paytables_virtual"


def test_run_inference_scripts_writes_paytable_shape_json():
    """Happy path: M1sim has rawdata on disk (from the per-mode-md5
    retrofit earlier); running inference should write a shape JSON
    to paytables_virtual/ with populated ``paytable_rows``."""
    target = _PAYTABLES_VIRTUAL / "M1sim_mode2.json"
    # Remove any stale output so we can verify the write
    if target.exists():
        target.unlink()

    _run_inference_scripts("M1sim", 2)

    assert target.exists(), (
        f"inference didn't produce expected output at {target}. "
        f"Check: SLOT_RAWDATA_ROOT env in _run_inference_scripts points "
        f"at slot_designer/rawdata/, and rawdata exists for M1sim mode 2."
    )
    data = json.loads(target.read_text(encoding="utf-8"))
    rows = data.get("paytable_rows") or []
    assert len(rows) > 0, (
        f"paytable_rows should be non-empty — rawdata has chunks but "
        f"inference returned nothing. data: {json.dumps(data, default=str)[:300]!r}"
    )
    # Every row must have the two primary keys the UI needs
    for r in rows:
        assert "pay_id" in r
        assert "match_count" in r


def test_run_inference_scripts_missing_rawdata_does_not_raise(tmp_path: Path, monkeypatch):
    """If a virtual machine has no rawdata (first boot, or deleted),
    infer_paytable naturally writes nothing and exits 0 / 1 depending
    on its own logic. The wrapper must NOT raise — sampling should
    complete regardless of whether inference had data to work with."""
    # Point the wrapper at a definitely-empty rawdata tree
    empty_rawdata = tmp_path / "empty_rawdata"
    empty_rawdata.mkdir()
    monkeypatch.setenv("SLOT_RAWDATA_ROOT", str(empty_rawdata))

    # Should not raise — failure is logged to stderr, not propagated.
    try:
        _run_inference_scripts("NonExistentVirtualMachine", 1)
    except Exception as exc:
        raise AssertionError(
            f"_run_inference_scripts must be best-effort; raised "
            f"{type(exc).__name__}: {exc}"
        )


if __name__ == "__main__":
    import inspect
    import tempfile

    mod = sys.modules[__name__]
    tests = [obj for name, obj in inspect.getmembers(mod)
             if name.startswith("test_") and callable(obj)]
    passed, failures = 0, []

    class _Monkeypatch:
        def __init__(self):
            self._env_set: list[tuple[str, str | None]] = []

        def setenv(self, name: str, value: str) -> None:
            import os
            self._env_set.append((name, os.environ.get(name)))
            os.environ[name] = value

        def undo(self) -> None:
            import os
            for name, prev in reversed(self._env_set):
                if prev is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = prev

    for t in tests:
        mp = _Monkeypatch()
        try:
            sig = inspect.signature(t)
            kwargs = {}
            if "tmp_path" in sig.parameters:
                kwargs["tmp_path"] = Path(tempfile.mkdtemp())
            if "monkeypatch" in sig.parameters:
                kwargs["monkeypatch"] = mp
            t(**kwargs)
            print(f"ok  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failures.append((t.__name__, e))
        finally:
            mp.undo()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if not failures else 1)
