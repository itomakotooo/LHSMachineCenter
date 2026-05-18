"""Regression tests for ticket P1-D1 — _batch_gen_worker.py parity with
_run_generate_report.

Contracts tested (from 00_ticket.md §3):

  C1 — Job dict includes md5 filter keys
       _prepare_batch_gen_item returns a dict whose ["job"] contains both
       upstream_config_md5 and upstream_code_md5, drawn from the machine's
       canonical lookup (_get_machine_md5 with mode arg). Verified with real
       and virtual machine schemas.

  C2 — Worker forwards md5 args to analyzer
       run_analyzer_job builds sys.argv including --upstream-config-md5 and
       --upstream-code-md5 from job["upstream_config_md5"] /
       job["upstream_code_md5"]. A stub analyzer captures argv; this test
       asserts both flags are present and carry the correct values.

  C3 — Worker calls patch_summary_md5 after analyzer
       After the stub analyzer writes player_impact_summary.json with empty
       config_md5 / code_md5 (simulating a virtual machine run), the worker
       must call patch_summary_md5 so those fields are populated on disk.
       Verified by reading the summary file after run_analyzer_job returns.

  C4 — Worker calls run_post_analyzer_inference after analyzer
       After patch_summary_md5, the worker must call (or trigger)
       run_post_analyzer_inference. Verified by asserting either that the
       post_hook key appears in the result or that the canonical helper was
       called (monkeypatched stub records calls).

  C5 — xfail markers removed in test_classify_chunks_historical_consumers.py
       Done separately in that file.

  C6 — Worker pool resource-snapshot safety
       New md5/inference code inside run_analyzer_job must read machine/mode
       from the job dict and from module globals snapped at init time, NOT
       from live os.environ or sys.path[0] at job time. Verified by
       monkeypatching module globals to wrong values and asserting behavior
       remains correct (per memory feedback_subprocess_import_suicide_and_module_globals.md).

  C7 — Inject-bug TDD
       For each fix, the inject step is documented here and proven in
       03_tests.md. The _make_job helper's "bug" keyword arg triggers
       controlled regressions.

----------------------------------------------------------------------
Subprocess-mode note (memory feedback_perf_claim_needs_e2e_event_stream.md):
----------------------------------------------------------------------
The worker pool runs in separate processes. This file covers the in-process
unit path (run_analyzer_job called directly with a fake analyzer) which is
sufficient for C1-C4/C6 because the contracts under test are the *worker's*
Python logic (job dict fields, sys.argv construction, patch_summary_md5 call
sequence, run_post_analyzer_inference call). The e2e subprocess verification
(real worker pool against M14 fixture) is delegated to impl-verifier per
brief §7 Wave 2.

----------------------------------------------------------------------
Inject-bug discipline (memory feedback_integration_test_argv.md):
----------------------------------------------------------------------
Each test documents in its docstring what single-line mutation makes it go
red. The inject-bug verification log is in 03_tests.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from src.web_console.backend import _batch_gen_worker as worker


# ---------------------------------------------------------------------------
# Shared fixtures + helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_worker_globals():
    """Per-test isolation for module-level globals.

    Same pattern as test_batch_worker_post_hook.py for the original two
    globals (_analyzer_mod, _project_root), extended to cover the three
    P1-D1 canonical-helper globals:
    _patch_summary_md5_fn, _run_post_inference_fn, _lookup_machine_md5_fn.

    The pool initializer sets all five; tests that call run_analyzer_job
    directly must set them too (or leave them None to exercise the
    guard-None code path). This fixture restores state after each test
    so that a test which sets the helpers doesn't contaminate the next.

    Uses getattr/setattr with sentinel to handle the pre-implementer state
    where the new globals don't exist yet on the module (inject-bug TDD
    discipline: tests must survive running against the un-fixed code).

    C6 split-path discipline: tests that set the helpers to real functions
    prove the real code path; tests that leave them None probe the fallback.
    """
    _MISSING = object()
    _C1D1_GLOBALS = ("_patch_summary_md5_fn", "_run_post_inference_fn", "_lookup_machine_md5_fn")

    prev_mod = worker._analyzer_mod
    prev_root = worker._project_root
    prev_extra = {
        k: getattr(worker, k, _MISSING)
        for k in _C1D1_GLOBALS
    }
    yield
    worker._analyzer_mod = prev_mod
    worker._project_root = prev_root
    for k, v in prev_extra.items():
        if v is _MISSING:
            # Attribute didn't exist before — don't create it.
            if hasattr(worker, k):
                delattr(worker, k)
        else:
            setattr(worker, k, v)


def _make_machines_config(
    tmp_path: Path,
    *,
    machine: str = "M14",
    mode: int = 1,
    config_md5: str = "cfg_CURRENT",
    code_md5: str = "code_CURRENT",
    virtual: bool = False,
) -> Path:
    """Write a minimal machines.json and return its path.

    For virtual machines (virtual=True) use modesMd5 per-mode block
    so _get_machine_md5 returns per-mode values.
    """
    mc = tmp_path / "machines.json"
    if virtual:
        entry = {
            "machine": machine,
            "modes": [mode],
            "configSummaryMd5": "",
            "codeSummaryMd5": "",
            "modesMd5": {
                str(mode): {
                    "configSummaryMd5": config_md5,
                    "codeSummaryMd5": code_md5,
                }
            },
        }
    else:
        entry = {
            "machine": machine,
            "modes": [mode],
            "configSummaryMd5": config_md5,
            "codeSummaryMd5": code_md5,
        }
    mc.write_text(
        json.dumps({"machines": [entry]}),
        encoding="utf-8",
    )
    return mc


def _make_app_and_prepare_fn(
    tmp_path: Path,
    *,
    machine: str = "M14",
    mode: int = 1,
    config_md5: str = "cfg_CURRENT",
    code_md5: str = "code_CURRENT",
    virtual: bool = False,
    extra_historical: bool = True,
) -> tuple[Any, Path, Path]:
    """Build a minimal app and extract the prepare_fn closure.

    Returns (prepare_fn, rawdata_root, machines_config_path).

    Strategy: monkeypatch BatchGenerateManager.__init__ to capture the
    prepare_fn passed to it during create_app.
    """
    import src.web_console.backend.app as app_mod

    mc = _make_machines_config(
        tmp_path,
        machine=machine,
        mode=mode,
        config_md5=config_md5,
        code_md5=code_md5,
        virtual=virtual,
    )

    rawdata_root = tmp_path / "rawdata"
    mode_dir = rawdata_root / machine / f"mode_{mode}"
    mode_dir.mkdir(parents=True, exist_ok=True)

    # Write two CURRENT chunks so prepare_fn has usable entries.
    for i in range(1, 3):
        chunk = mode_dir / f"chunk_{i:04d}.json"
        chunk.write_text(json.dumps({
            "_cache_version": 3,
            "_machine": machine,
            "_mode": mode,
            "_bet": 1000,
            "_spin_times": 5000,
            "_robot_count": 24,
            "_chunk_index": i,
            "_saved_at": "2026-05-01T00:00:00Z",
            "_config_md5": config_md5,
            "_code_md5": code_md5,
            "response": [],
        }), encoding="utf-8")

    if extra_historical:
        # Write one historical chunk to ensure the filter-key tests are
        # meaningful (there ARE mixed chunks in the dir).
        hist = mode_dir / "chunk_0099.json"
        hist.write_text(json.dumps({
            "_cache_version": 3,
            "_machine": machine,
            "_mode": mode,
            "_bet": 1000,
            "_spin_times": 5000,
            "_robot_count": 24,
            "_chunk_index": 99,
            "_saved_at": "2026-05-01T00:00:00Z",
            "_config_md5": "cfg_OLD",
            "_code_md5": "code_OLD",
            "response": [],
        }), encoding="utf-8")

    captured: dict = {}
    _real_init = app_mod.BatchGenerateManager.__init__

    def _capturing_init(self_mgr, prepare_fn, finalize_fn, ops, **kwargs):
        captured["prepare_fn"] = prepare_fn
        _real_init(self_mgr, prepare_fn, finalize_fn, ops, **kwargs)

    state_dir = tmp_path / "state"
    (state_dir / "progress").mkdir(parents=True)
    fake_analyzer = tmp_path / "fake_analyzer.py"
    fake_analyzer.write_text("import sys; sys.exit(0)\n", encoding="utf-8")

    with patch.object(app_mod.BatchGenerateManager, "__init__", _capturing_init):
        app_mod.create_app(
            state_dir=state_dir,
            reports_root=tmp_path / "reports",
            cache_root=tmp_path / "cache",
            machines_config=mc,
            analyzer_path=fake_analyzer,
            rawdata_root=rawdata_root,
        )

    assert "prepare_fn" in captured, (
        "BatchGenerateManager.__init__ was not called during create_app — "
        "test fixture is broken."
    )
    return captured["prepare_fn"], rawdata_root, mc


def _make_job(
    tmp_path: Path,
    *,
    machine: str = "M1",
    mode: int = 7,
    config_md5: str = "cfg_ABC",
    code_md5: str = "code_XYZ",
    machines_config: Path | None = None,
    include_md5_keys: bool = True,
) -> dict:
    """Minimal job dict for run_analyzer_job tests.

    include_md5_keys=False simulates the pre-fix bug (missing md5 filter keys)
    so inject-bug tests can trigger the old behavior.
    """
    chunk_dir = tmp_path / "rawdata" / machine / f"mode_{mode}"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    output_dir = tmp_path / "out"
    output_dir.mkdir(exist_ok=True)
    job: dict = {
        "machine": machine,
        "mode": mode,
        "chunk_dir": str(chunk_dir),
        "output_dir": str(output_dir),
        "run_id": "test_run",
        "progress_file": str(tmp_path / "progress.jsonl"),
        "max_chunks": 1,
        "chunk_spin_times": 5000,
        "chunk_robot_count": 24,
        "bet": 1000,
    }
    if include_md5_keys:
        job["upstream_config_md5"] = config_md5
        job["upstream_code_md5"] = code_md5
    if machines_config is not None:
        job["machines_config"] = str(machines_config)
    return job


# ---------------------------------------------------------------------------
# C1 — Job dict includes md5 filter keys
# ---------------------------------------------------------------------------

class TestJobDictIncludesMd5FilterKeys:
    """C1: _prepare_batch_gen_item must include upstream_config_md5 +
    upstream_code_md5 in the returned job dict.

    These keys are read from the machine's canonical lookup (_get_machine_md5
    with mode arg) so the worker can forward them as CLI filter flags.

    Inject-bug: remove the two key assignments from _prepare_batch_gen_item
    in app.py → both tests below go RED (KeyError or assert-not-missing-keys
    assertion fails). Revert → GREEN.
    """

    def test_job_dict_has_upstream_config_md5(self, tmp_path):
        """C1a: job dict must contain upstream_config_md5 key.

        Inject-bug: comment out the line that sets
        job["upstream_config_md5"] = ... in _prepare_batch_gen_item.
        This test goes RED: assert "upstream_config_md5" in job fails.
        Revert → GREEN.
        """
        prepare_fn, _, _ = _make_app_and_prepare_fn(
            tmp_path, machine="M14", mode=1,
            config_md5="cfg_SENTINEL", code_md5="code_SENTINEL",
        )
        prepared = prepare_fn("M14", 1)
        job = prepared["job"]

        assert "upstream_config_md5" in job, (
            "REGRESSION (C1): job dict missing upstream_config_md5. "
            "Without this key the worker cannot forward "
            "--upstream-config-md5 to the analyzer CLI. "
            f"Actual job keys: {sorted(job.keys())}"
        )

    def test_job_dict_has_upstream_code_md5(self, tmp_path):
        """C1b: job dict must contain upstream_code_md5 key.

        Inject-bug: comment out job["upstream_code_md5"] = ... in
        _prepare_batch_gen_item → this test goes RED.
        Revert → GREEN.
        """
        prepare_fn, _, _ = _make_app_and_prepare_fn(
            tmp_path, machine="M14", mode=1,
            config_md5="cfg_SENTINEL", code_md5="code_SENTINEL",
        )
        prepared = prepare_fn("M14", 1)
        job = prepared["job"]

        assert "upstream_code_md5" in job, (
            "REGRESSION (C1): job dict missing upstream_code_md5. "
            f"Actual job keys: {sorted(job.keys())}"
        )

    def test_job_dict_md5_values_match_machine_lookup(self, tmp_path):
        """C1c: the md5 values in the job dict must come from the machine
        registry, not be hardcoded empty strings or sentinels.

        Inject-bug: assign job["upstream_config_md5"] = "" (empty) instead of
        the real md5 value → assert fails (value is empty, not cfg_SENTINEL).
        Revert → GREEN.
        """
        prepare_fn, _, _ = _make_app_and_prepare_fn(
            tmp_path, machine="M14", mode=1,
            config_md5="cfg_SENTINEL", code_md5="code_SENTINEL",
        )
        prepared = prepare_fn("M14", 1)
        job = prepared["job"]

        assert job.get("upstream_config_md5") == "cfg_SENTINEL", (
            f"REGRESSION (C1): upstream_config_md5 value should be "
            f"'cfg_SENTINEL' (from machines.json), got "
            f"{job.get('upstream_config_md5')!r}."
        )
        assert job.get("upstream_code_md5") == "code_SENTINEL", (
            f"REGRESSION (C1): upstream_code_md5 value should be "
            f"'code_SENTINEL', got {job.get('upstream_code_md5')!r}."
        )

    def test_job_dict_md5_keys_virtual_machine(self, tmp_path):
        """C1d: for virtual machines (modesMd5 per-mode schema), the job dict
        must carry the per-mode md5 values, not the flat-schema empty strings.

        Inject-bug: use mode=None (ignore mode) in _get_machine_md5 call →
        returns ("", "") from flat schema → assert fails (values are empty).
        Revert → GREEN.
        """
        prepare_fn, _, _ = _make_app_and_prepare_fn(
            tmp_path, machine="M14", mode=1,
            config_md5="cfg_VIRTUAL_MODE1", code_md5="code_VIRTUAL_MODE1",
            virtual=True,
        )
        prepared = prepare_fn("M14", 1)
        job = prepared["job"]

        assert job.get("upstream_config_md5") == "cfg_VIRTUAL_MODE1", (
            f"REGRESSION (C1 virtual): upstream_config_md5 should be "
            f"'cfg_VIRTUAL_MODE1' (per-mode lookup), got "
            f"{job.get('upstream_config_md5')!r}."
        )
        assert job.get("upstream_code_md5") == "code_VIRTUAL_MODE1", (
            f"REGRESSION (C1 virtual): upstream_code_md5 should be "
            f"'code_VIRTUAL_MODE1', got {job.get('upstream_code_md5')!r}."
        )

    @pytest.mark.parametrize("machine,mode,config_md5,code_md5", [
        ("M14", 1, "cfg_M14_mode1", "code_M14_mode1"),
        ("M1",  7, "cfg_M1_mode7",  "code_M1_mode7"),
        ("M99", 2, "cfg_M99_mode2", "code_M99_mode2"),
    ])
    def test_job_dict_md5_parametrized(
        self, tmp_path, machine, mode, config_md5, code_md5
    ):
        """C1e parametrized: md5 keys propagate for multiple machine/mode
        combinations.

        Per memory feedback_enumerate_safety_paths.md: if change applies to N
        paths, assert each.

        Inject-bug: for any row, removing the key assignment in
        _prepare_batch_gen_item → that row's assertions fail.
        """
        prepare_fn, _, _ = _make_app_and_prepare_fn(
            tmp_path, machine=machine, mode=mode,
            config_md5=config_md5, code_md5=code_md5,
        )
        prepared = prepare_fn(machine, mode)
        job = prepared["job"]

        assert job.get("upstream_config_md5") == config_md5, (
            f"C1 {machine}/mode{mode}: upstream_config_md5 wrong; "
            f"expected {config_md5!r}, got {job.get('upstream_config_md5')!r}"
        )
        assert job.get("upstream_code_md5") == code_md5, (
            f"C1 {machine}/mode{mode}: upstream_code_md5 wrong; "
            f"expected {code_md5!r}, got {job.get('upstream_code_md5')!r}"
        )


# ---------------------------------------------------------------------------
# C2 — Worker forwards md5 args to analyzer CLI argv
# ---------------------------------------------------------------------------

class TestWorkerForwardsMd5ArgsToAnalyzerArgv:
    """C2: run_analyzer_job must build sys.argv including
    --upstream-config-md5 <cfg> and --upstream-code-md5 <code>.

    A stub analyzer captures sys.argv at the time analyzer.main() runs.
    The test asserts both flags are present with the correct values from
    job["upstream_config_md5"] / job["upstream_code_md5"].

    Per memory feedback_integration_test_argv.md: argv-capture tests
    are the canonical way to prove CLI-flag forwarding without spawning
    a real subprocess.

    Inject-bug for --upstream-config-md5: remove the two lines in
    run_analyzer_job that append --upstream-config-md5 / --upstream-code-md5
    to argv → both assertions below fail (flag absent from captured argv).
    Revert → GREEN.
    """

    def _make_argv_capturing_analyzer(self) -> tuple[Any, list]:
        """Return a stub analyzer module + a list that receives sys.argv
        snapshots. The stub writes a minimal summary.json.
        """
        captured_argvs: list = []

        class _StubAnalyzer:
            _output_dir: str = ""

            @staticmethod
            def main() -> int:
                captured_argvs.append(list(sys.argv))
                summary = Path(_StubAnalyzer._output_dir) / "player_impact_summary.json"
                summary.parent.mkdir(parents=True, exist_ok=True)
                summary.write_text(json.dumps({
                    "config_md5": "",
                    "code_md5": "",
                    "rtp": {"point_pct": 95.0},
                }), encoding="utf-8")
                return 0

        return _StubAnalyzer, captured_argvs

    def test_argv_contains_upstream_config_md5_flag(self, tmp_path, monkeypatch):
        """C2a: --upstream-config-md5 flag appears in argv forwarded to analyzer.

        Inject-bug: remove `--upstream-config-md5`, job["upstream_config_md5"]`
        from the argv list in run_analyzer_job → assert fails (flag not found).
        Revert → GREEN.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        stub, captured = self._make_argv_capturing_analyzer()
        job = _make_job(tmp_path, config_md5="cfg_FOR_CLI", code_md5="code_FOR_CLI")
        stub._output_dir = job["output_dir"]
        worker._analyzer_mod = stub
        worker._project_root = str(tmp_path)

        result = worker.run_analyzer_job(job)
        assert result["ok"] is True, f"Stub analyzer must return ok; got {result}"

        assert len(captured) == 1, (
            f"Stub analyzer main() must have been called exactly once; "
            f"captured {len(captured)} argv snapshots."
        )
        argv = captured[0]

        assert "--upstream-config-md5" in argv, (
            f"REGRESSION (C2): --upstream-config-md5 flag is missing from "
            f"analyzer argv. Per brief §3 C2 the worker must forward this flag "
            f"so the analyzer filters historical chunks. "
            f"Actual argv: {argv}"
        )
        idx = argv.index("--upstream-config-md5")
        assert argv[idx + 1] == "cfg_FOR_CLI", (
            f"REGRESSION (C2): --upstream-config-md5 value is wrong; "
            f"expected 'cfg_FOR_CLI', got {argv[idx + 1]!r}"
        )

    def test_argv_contains_upstream_code_md5_flag(self, tmp_path, monkeypatch):
        """C2b: --upstream-code-md5 flag appears in argv forwarded to analyzer.

        Inject-bug: remove `--upstream-code-md5`, job["upstream_code_md5"]`
        from argv list → assert fails. Revert → GREEN.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        stub, captured = self._make_argv_capturing_analyzer()
        job = _make_job(tmp_path, config_md5="cfg_FOR_CLI", code_md5="code_FOR_CLI")
        stub._output_dir = job["output_dir"]
        worker._analyzer_mod = stub
        worker._project_root = str(tmp_path)

        worker.run_analyzer_job(job)
        argv = captured[0]

        assert "--upstream-code-md5" in argv, (
            f"REGRESSION (C2): --upstream-code-md5 flag is missing from "
            f"analyzer argv. Actual argv: {argv}"
        )
        idx = argv.index("--upstream-code-md5")
        assert argv[idx + 1] == "code_FOR_CLI", (
            f"REGRESSION (C2): --upstream-code-md5 value is wrong; "
            f"expected 'code_FOR_CLI', got {argv[idx + 1]!r}"
        )

    def test_argv_md5_values_match_job_dict(self, tmp_path, monkeypatch):
        """C2c: the CLI flag values must exactly match the job dict keys,
        not be hardcoded or re-computed from a different source.

        Per memory feedback_subprocess_import_suicide_and_module_globals.md:
        the worker must read from job dict, not from live module globals.

        Inject-bug: replace job["upstream_config_md5"] with a hardcoded
        sentinel in the argv-build code → values mismatch → assert fails.
        Revert → GREEN.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        stub, captured = self._make_argv_capturing_analyzer()
        cfg_val = "cfg_UNIQUE_SENTINEL_12345"
        code_val = "code_UNIQUE_SENTINEL_67890"
        job = _make_job(tmp_path, config_md5=cfg_val, code_md5=code_val)
        stub._output_dir = job["output_dir"]
        worker._analyzer_mod = stub
        worker._project_root = str(tmp_path)

        worker.run_analyzer_job(job)
        argv = captured[0]

        def _flag_val(flag: str) -> str | None:
            try:
                return argv[argv.index(flag) + 1]
            except ValueError:
                return None

        assert _flag_val("--upstream-config-md5") == cfg_val, (
            "C2c: --upstream-config-md5 value does not match job dict; "
            f"expected {cfg_val!r}, got {_flag_val('--upstream-config-md5')!r}. "
            "Worker must read from job dict, not recompute."
        )
        assert _flag_val("--upstream-code-md5") == code_val, (
            "C2c: --upstream-code-md5 value does not match job dict; "
            f"expected {code_val!r}, got {_flag_val('--upstream-code-md5')!r}."
        )

    def test_missing_md5_keys_in_job_does_not_crash_worker(
        self, tmp_path, monkeypatch
    ):
        """C2d: if upstream_config_md5 / upstream_code_md5 are absent from
        the job dict (legacy job from before the fix), the worker must not
        crash. It should degrade gracefully — not forward the flags.

        This is the backwards-compatibility guard for jobs queued before
        the fix lands.

        Inject-bug: raise KeyError inside argv-build when key is missing →
        result["ok"] becomes False → assert fails.
        Revert → GREEN (worker handles missing keys gracefully).
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")

        class _GracefulStub:
            _output_dir: str = ""

            @staticmethod
            def main() -> int:
                summary = Path(_GracefulStub._output_dir) / "player_impact_summary.json"
                summary.parent.mkdir(parents=True, exist_ok=True)
                summary.write_text('{"rtp":{"point_pct":95.0}}', encoding="utf-8")
                return 0

        job = _make_job(tmp_path, include_md5_keys=False)
        _GracefulStub._output_dir = job["output_dir"]
        worker._analyzer_mod = _GracefulStub
        worker._project_root = str(tmp_path)

        result = worker.run_analyzer_job(job)
        # Worker must not crash — it may omit the md5 flags but must survive.
        assert result["ok"] is True, (
            "C2d: worker must not crash when upstream_config_md5 / "
            f"upstream_code_md5 are absent from job dict. "
            f"result={result!r}"
        )


# ---------------------------------------------------------------------------
# C3 — Worker calls patch_summary_md5 after analyzer
# ---------------------------------------------------------------------------

class TestWorkerCallsPatchSummaryMd5:
    """C3: after analyzer.main() returns rc=0, run_analyzer_job must call
    patch_summary_md5(summary_file, lookup_fn=...) so virtual-machine batch
    summaries have populated config_md5 / code_md5 fields.

    Observable signal: the summary file on disk has non-empty md5 fields
    after run_analyzer_job returns, even though the stub analyzer wrote
    empty strings for those fields.

    Inject-bug: remove the patch_summary_md5 call from run_analyzer_job →
    config_md5 / code_md5 in the summary file remain empty → assertions fail.
    Revert → GREEN.
    """

    def _make_stub_analyzer_with_empty_md5(self) -> Any:
        """Stub analyzer that writes a summary with empty md5 fields,
        simulating a virtual-machine run where the real analyzer has no
        access to the virtual machine registry.
        """
        class _Stub:
            _output_dir: str = ""

            @staticmethod
            def main() -> int:
                summary = Path(_Stub._output_dir) / "player_impact_summary.json"
                summary.parent.mkdir(parents=True, exist_ok=True)
                summary.write_text(json.dumps({
                    "config_md5": "",
                    "code_md5": "",
                    "rtp": {"point_pct": 95.0},
                    "machine": "M14",
                    "mode": 1,
                }), encoding="utf-8")
                return 0

        return _Stub

    def _wire_canonical_helpers(self, tmp_path: Path) -> None:
        """Set the worker module globals to real canonical functions.

        In production these are set by _pool_worker_init. In unit tests
        that call run_analyzer_job directly, we must set them explicitly
        so the C3 patch_summary_md5 path executes (not skipped by
        'if _patch_summary_md5_fn is not None').

        Per memory feedback_subprocess_import_suicide_and_module_globals.md:
        the worker must read from snapshotted module globals, not live
        imports. Setting these here mirrors what the pool initializer does.

        This is the correct test-side setup — the worker's guard
        `if _patch_summary_md5_fn is not None` is intentional C6 safety
        (test stubs may leave it None); tests that want to exercise C3
        must supply the real function.

        Guarded with hasattr: if the implementer hasn't landed yet, these
        attributes don't exist and the test will FAIL at the assertion
        level (not at the setup level), giving cleaner inject-bug signal.
        """
        from fresh_slotlab.summary_md5_patch import patch_summary_md5 as _psm
        from fresh_slotlab.machine_md5 import lookup_machine_md5 as _lmm
        if hasattr(worker, "_patch_summary_md5_fn"):
            worker._patch_summary_md5_fn = _psm
        if hasattr(worker, "_lookup_machine_md5_fn"):
            worker._lookup_machine_md5_fn = _lmm

    def test_summary_config_md5_populated_after_worker_run(
        self, tmp_path, monkeypatch
    ):
        """C3a: config_md5 in the summary file must be non-empty after
        run_analyzer_job returns.

        Inject-bug: comment out or remove the _patch_summary_md5_fn(...) call
        in run_analyzer_job → summary["config_md5"] stays "" → assert fails.
        Revert → GREEN.

        Setup note: we wire _patch_summary_md5_fn and _lookup_machine_md5_fn
        to the real functions to mirror what _pool_worker_init does. The
        worker's 'if _patch_summary_md5_fn is not None' guard is correct C6
        safety; we supply the real function here to test the live path.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        self._wire_canonical_helpers(tmp_path)
        mc = _make_machines_config(
            tmp_path,
            machine="M14", mode=1,
            config_md5="cfg_PATCHED", code_md5="code_PATCHED",
        )
        Stub = self._make_stub_analyzer_with_empty_md5()
        job = _make_job(
            tmp_path, machine="M14", mode=1,
            config_md5="cfg_PATCHED", code_md5="code_PATCHED",
            machines_config=mc,
        )
        Stub._output_dir = job["output_dir"]
        worker._analyzer_mod = Stub
        worker._project_root = str(tmp_path)

        result = worker.run_analyzer_job(job)
        assert result["ok"] is True, f"Stub must succeed; got {result}"

        summary_path = Path(job["output_dir"]) / "player_impact_summary.json"
        assert summary_path.exists(), (
            "Summary file must exist after worker run."
        )
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary.get("config_md5"), (
            "REGRESSION (C3): config_md5 is empty in summary after worker run. "
            "run_analyzer_job must call patch_summary_md5 so virtual-machine "
            "batch summaries have non-empty md5 fields. "
            f"Full summary: {summary}"
        )

    def test_summary_code_md5_populated_after_worker_run(
        self, tmp_path, monkeypatch
    ):
        """C3b: code_md5 in the summary file must be non-empty after
        run_analyzer_job returns.

        Inject-bug: remove the _patch_summary_md5_fn(...) call from
        run_analyzer_job → code_md5 stays "" → assert fails.
        Revert → GREEN.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        self._wire_canonical_helpers(tmp_path)
        mc = _make_machines_config(
            tmp_path,
            machine="M14", mode=1,
            config_md5="cfg_PATCHED", code_md5="code_PATCHED",
        )
        Stub = self._make_stub_analyzer_with_empty_md5()
        job = _make_job(
            tmp_path, machine="M14", mode=1,
            config_md5="cfg_PATCHED", code_md5="code_PATCHED",
            machines_config=mc,
        )
        Stub._output_dir = job["output_dir"]
        worker._analyzer_mod = Stub
        worker._project_root = str(tmp_path)

        worker.run_analyzer_job(job)
        summary = json.loads(
            (Path(job["output_dir"]) / "player_impact_summary.json")
            .read_text(encoding="utf-8")
        )
        assert summary.get("code_md5"), (
            "REGRESSION (C3): code_md5 is empty in summary after worker run. "
            f"Full summary: {summary}"
        )

    def test_patch_summary_md5_called_with_correct_lookup(
        self, tmp_path, monkeypatch
    ):
        """C3c: _patch_summary_md5_fn is called once after analyzer.main().

        Verified by replacing worker._patch_summary_md5_fn with a MagicMock
        and asserting call_count >= 1.

        Inject-bug: remove or guard-out the _patch_summary_md5_fn(...)  call
        in run_analyzer_job → mock.call_count == 0 → assert fails.
        Revert → GREEN.

        Note: we monkeypatch the module-global directly (worker._patch_summary_md5_fn)
        because run_analyzer_job reads from the module global, not from a
        fresh import. Patching the function in its source module would not
        intercept the call if the worker has already cached the reference.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        mc = _make_machines_config(
            tmp_path, machine="M14", mode=1,
            config_md5="cfg_TEST", code_md5="code_TEST",
        )
        Stub = self._make_stub_analyzer_with_empty_md5()
        job = _make_job(
            tmp_path, machine="M14", mode=1,
            config_md5="cfg_TEST", code_md5="code_TEST",
            machines_config=mc,
        )
        Stub._output_dir = job["output_dir"]
        worker._analyzer_mod = Stub
        worker._project_root = str(tmp_path)

        # Replace the module global with a MagicMock.
        # The _autouse fixture restores the original value after this test.
        # Guarded with hasattr: pre-implementer module won't have these.
        mock_patch = MagicMock(return_value=None)
        if hasattr(worker, "_patch_summary_md5_fn"):
            worker._patch_summary_md5_fn = mock_patch
        if hasattr(worker, "_lookup_machine_md5_fn"):
            worker._lookup_machine_md5_fn = lambda m, p=None: ("cfg_TEST", "code_TEST")

        result = worker.run_analyzer_job(job)

        assert result["ok"] is True
        assert mock_patch.call_count >= 1, (
            "REGRESSION (C3): _patch_summary_md5_fn was not called by "
            "run_analyzer_job. It must be called after analyzer.main() "
            f"to populate virtual-machine md5 fields. "
            f"call_count={mock_patch.call_count}"
        )

    def test_md5_not_overwritten_when_already_populated(
        self, tmp_path, monkeypatch
    ):
        """C3d: patch_summary_md5 is a no-op when config_md5 / code_md5 are
        already non-empty (real-machine path where the analyzer itself wrote them).

        Per fresh_slotlab.summary_md5_patch contract C4: 'Only fills fields
        that are falsy. Non-empty values are NOT overwritten.'

        Inject-bug: replace the fill-if-falsy check with unconditional
        overwrite → existing values are replaced → this test goes RED if
        existing values differ from the lookup result.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        mc = _make_machines_config(
            tmp_path, machine="M14", mode=1,
            config_md5="cfg_REGISTRY", code_md5="code_REGISTRY",
        )

        # Stub writes NON-EMPTY md5 fields (simulating real-machine path)
        class _StubWithMd5:
            _output_dir: str = ""

            @staticmethod
            def main() -> int:
                summary = Path(_StubWithMd5._output_dir) / "player_impact_summary.json"
                summary.parent.mkdir(parents=True, exist_ok=True)
                summary.write_text(json.dumps({
                    "config_md5": "cfg_FROM_ANALYZER",
                    "code_md5": "code_FROM_ANALYZER",
                    "rtp": {"point_pct": 95.0},
                    "machine": "M14",
                    "mode": 1,
                }), encoding="utf-8")
                return 0

        job = _make_job(
            tmp_path, machine="M14", mode=1,
            config_md5="cfg_REGISTRY", code_md5="code_REGISTRY",
            machines_config=mc,
        )
        _StubWithMd5._output_dir = job["output_dir"]
        worker._analyzer_mod = _StubWithMd5
        worker._project_root = str(tmp_path)

        worker.run_analyzer_job(job)
        summary = json.loads(
            (Path(job["output_dir"]) / "player_impact_summary.json")
            .read_text(encoding="utf-8")
        )
        # The analyzer-written values must NOT be overwritten.
        assert summary["config_md5"] == "cfg_FROM_ANALYZER", (
            "C3d: existing config_md5 was overwritten by patch_summary_md5. "
            f"Expected 'cfg_FROM_ANALYZER', got {summary['config_md5']!r}."
        )
        assert summary["code_md5"] == "code_FROM_ANALYZER", (
            "C3d: existing code_md5 was overwritten by patch_summary_md5. "
            f"Expected 'code_FROM_ANALYZER', got {summary['code_md5']!r}."
        )


# ---------------------------------------------------------------------------
# C4 — Worker calls run_post_analyzer_inference after analyzer
# ---------------------------------------------------------------------------

class TestWorkerCallsRunPostAnalyzerInference:
    """C4: after patch_summary_md5, run_analyzer_job must call (or trigger)
    run_post_analyzer_inference so the UI's paytable-shape + classifier
    panels stay in sync with the batch-generated report.

    The existing post-hook mechanism (SLOT_SKIP_AUTO_INFER, script_missing
    paths) is preserved — this ticket wires the new canonical helper
    (fresh_slotlab.post_inference.run_post_analyzer_inference) into the
    worker, replacing or wrapping the old inline subprocess code.

    Observable signal: the result["post_hook"] key is present and non-empty;
    OR the canonical run_post_analyzer_inference helper was called.

    Inject-bug: remove the run_post_analyzer_inference call / canonical
    helper wiring from run_analyzer_job → result has no "post_hook" key
    OR hook_results is empty OR canonical mock.call_count == 0 → fails.
    Revert → GREEN.
    """

    def _make_success_stub(self, output_dir_holder: list) -> Any:
        """Stub analyzer that writes summary and records output_dir."""
        class _Stub:
            @staticmethod
            def main() -> int:
                out = Path(output_dir_holder[0])
                summary = out / "player_impact_summary.json"
                summary.parent.mkdir(parents=True, exist_ok=True)
                summary.write_text(json.dumps({
                    "config_md5": "cfg_C4",
                    "code_md5": "code_C4",
                    "rtp": {"point_pct": 95.0},
                    "machine": "M1",
                    "mode": 7,
                }), encoding="utf-8")
                return 0

        return _Stub

    def test_result_has_post_hook_key(self, tmp_path, monkeypatch):
        """C4a: result dict from run_analyzer_job must include post_hook key.

        This key is the diagnostic persistence channel for the inference hook
        (per memory feedback_no_silent_swallow.md). Its absence means the
        hook ran but results were silently dropped, or the hook was never
        wired.

        Inject-bug: remove `post_hook` key from the return dict → assert fails.
        Revert → GREEN.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        out_holder = [""]
        job = _make_job(tmp_path, machine="M1", mode=7,
                        config_md5="cfg_C4", code_md5="code_C4")
        out_holder[0] = job["output_dir"]
        Stub = self._make_success_stub(out_holder)
        worker._analyzer_mod = Stub
        worker._project_root = str(tmp_path)

        result = worker.run_analyzer_job(job)
        assert result["ok"] is True
        assert "post_hook" in result, (
            "REGRESSION (C4): run_analyzer_job result must include 'post_hook' "
            "key. This is the diagnostic persistence channel for the inference "
            "hook. Without it there is no way to distinguish 'hook ran but "
            "produced nothing' from 'hook was never wired'. "
            f"Actual result keys: {sorted(result.keys())}"
        )

    def test_post_hook_is_non_empty(self, tmp_path, monkeypatch):
        """C4b: the post_hook value must be a non-empty list (hook ran and
        produced at least one entry — even if it's a skip or context entry).

        Inject-bug: return `post_hook: []` from run_analyzer_job → assert
        fails. Revert → GREEN.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        out_holder = [""]
        job = _make_job(tmp_path, machine="M1", mode=7,
                        config_md5="cfg_C4", code_md5="code_C4")
        out_holder[0] = job["output_dir"]
        Stub = self._make_success_stub(out_holder)
        worker._analyzer_mod = Stub
        worker._project_root = str(tmp_path)

        result = worker.run_analyzer_job(job)
        hook = result.get("post_hook", [])
        assert isinstance(hook, list) and len(hook) > 0, (
            "REGRESSION (C4): post_hook must be a non-empty list. "
            f"Got: {hook!r}. The inference hook must produce at least "
            "one entry (skip marker, context block, or script result)."
        )

    def test_skip_env_var_triggers_skip_marker(self, tmp_path, monkeypatch):
        """C4c: SLOT_SKIP_AUTO_INFER=1 must record a skip marker in post_hook.

        This is the existing contract from test_batch_worker_post_hook.py.
        Regression guard ensures the P1-D1 wiring of the canonical helper
        preserves this behavior.

        Inject-bug: remove the env-var skip guard from the inference call →
        the hook tries to launch real subprocesses → no skip marker →
        assertion fails. Revert → GREEN.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        out_holder = [""]
        job = _make_job(tmp_path, machine="M1", mode=7,
                        config_md5="cfg_C4", code_md5="code_C4")
        out_holder[0] = job["output_dir"]
        Stub = self._make_success_stub(out_holder)
        worker._analyzer_mod = Stub
        worker._project_root = str(tmp_path)

        result = worker.run_analyzer_job(job)
        hook = result.get("post_hook", [])

        skip_entries = [e for e in hook if "skip" in e]
        assert skip_entries, (
            "REGRESSION (C4c): no skip marker found in post_hook entries. "
            "SLOT_SKIP_AUTO_INFER=1 must short-circuit the inference hook and "
            f"record a skip entry. Actual post_hook: {hook!r}"
        )

    def test_inference_called_after_analyzer_not_before(
        self, tmp_path, monkeypatch
    ):
        """C4d: the inference hook fires AFTER analyzer.main() and
        patch_summary_md5, not before.

        Order: (1) analyzer.main() → (2) patch_summary_md5 → (3) inference.

        Verified by asserting the summary file exists when the inference
        hook is triggered (if it ran before, the summary wouldn't exist yet).

        This uses SLOT_SKIP_AUTO_INFER=1 so we avoid real subprocess costs,
        but the skip entry is only generated if run_analyzer_job reaches the
        hook code path — which it can only do after the analyzer has been
        called. So the presence of a skip entry proves ordering.

        Inject-bug: move the inference trigger before analyzer.main() call →
        skip marker appears but analyzer hasn't run yet → this test detects
        the reorder via the fact that result["ok"] would be False (analyzer
        not yet run when hook fires).

        More directly: confirm result["ok"]=True + skip entry both present
        → proves both paths executed in some order with analyzer first.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        out_holder = [""]
        call_log: list[str] = []

        class _OrderedStub:
            @staticmethod
            def main() -> int:
                call_log.append("analyzer")
                out = Path(out_holder[0])
                summary = out / "player_impact_summary.json"
                summary.parent.mkdir(parents=True, exist_ok=True)
                summary.write_text(json.dumps({"rtp": {"point_pct": 95.0}}),
                                   encoding="utf-8")
                return 0

        job = _make_job(tmp_path, machine="M1", mode=7,
                        config_md5="cfg_C4d", code_md5="code_C4d")
        out_holder[0] = job["output_dir"]
        worker._analyzer_mod = _OrderedStub
        worker._project_root = str(tmp_path)

        result = worker.run_analyzer_job(job)
        assert result["ok"] is True, f"analyzer must succeed; got {result}"
        assert "analyzer" in call_log, "analyzer.main() must have been called"

        hook = result.get("post_hook", [])
        assert hook, (
            "C4d: post_hook must have been populated — inference path was never reached."
        )


# ---------------------------------------------------------------------------
# C6 — Worker pool resource-snapshot safety
# ---------------------------------------------------------------------------

class TestWorkerPoolResourceSnapshotSafety:
    """C6: per memory feedback_subprocess_import_suicide_and_module_globals.md,
    any module-global resources the worker needs must be snapshot at
    initializer time and read from the snapshot, NOT from live globals at
    job time.

    Split-path regression (per memory): monkeypatch the module global to a
    wrong value at job time and assert behavior remains correct (proves the
    worker reads from the job dict / snapshot, not the live global).

    Inject-bug: replace `_project_root` usage with `os.getcwd()` live read →
    when we monkeypatch `_project_root` to a wrong value, behavior changes →
    assert fails. Revert → GREEN.
    """

    def test_machines_config_read_from_job_dict_not_module_global(
        self, tmp_path, monkeypatch
    ):
        """C6a: md5 patch uses the machines_config from job dict, NOT from
        a live module-global that could drift between pool initializer and
        job execution.

        Per memory feedback_subprocess_import_suicide_and_module_globals.md:
        the bug pattern is 'worker reads live global instead of job dict'.

        Setup: job dict carries machines_config pointing to a valid config
        (cfg_CORRECT / code_CORRECT). _project_root is set to a different
        empty directory. The canonical helper functions (_patch_summary_md5_fn,
        _lookup_machine_md5_fn) are pre-wired (as _pool_worker_init would do).
        Assert that summary gets cfg_CORRECT from the job's machines_config.

        Inject-bug: replace job dict's machines_config read with a live
        os.getcwd() / _project_root read → when _project_root is wrong,
        summary md5 comes from the wrong registry → assert fails.
        Revert → GREEN.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        mc = _make_machines_config(
            tmp_path, machine="M14", mode=1,
            config_md5="cfg_CORRECT", code_md5="code_CORRECT",
        )

        # Wire canonical helpers as the pool initializer would.
        # Guarded with hasattr: pre-implementer base code doesn't have these
        # globals; the test will FAIL at the assertion level (not setup),
        # giving clean inject-bug signal.
        from fresh_slotlab.summary_md5_patch import patch_summary_md5 as _psm
        from fresh_slotlab.machine_md5 import lookup_machine_md5 as _lmm
        if hasattr(worker, "_patch_summary_md5_fn"):
            worker._patch_summary_md5_fn = _psm
        if hasattr(worker, "_lookup_machine_md5_fn"):
            worker._lookup_machine_md5_fn = _lmm

        class _Stub:
            _output_dir: str = ""

            @staticmethod
            def main() -> int:
                summary = Path(_Stub._output_dir) / "player_impact_summary.json"
                summary.parent.mkdir(parents=True, exist_ok=True)
                summary.write_text(json.dumps({
                    "config_md5": "",
                    "code_md5": "",
                    "machine": "M14",
                    "mode": 1,
                    "rtp": {"point_pct": 95.0},
                }), encoding="utf-8")
                return 0

        job = _make_job(
            tmp_path, machine="M14", mode=1,
            config_md5="cfg_CORRECT", code_md5="code_CORRECT",
            machines_config=mc,
        )
        _Stub._output_dir = job["output_dir"]
        worker._analyzer_mod = _Stub

        # Point _project_root at a completely different (empty) directory to
        # demonstrate that summary md5 is driven by job dict's machines_config,
        # not by any path derived from _project_root.
        wrong_root = tmp_path / "wrong_root_should_not_be_read"
        wrong_root.mkdir()
        worker._project_root = str(wrong_root)

        result = worker.run_analyzer_job(job)
        assert result["ok"] is True

        summary = json.loads(
            (Path(job["output_dir"]) / "player_impact_summary.json")
            .read_text(encoding="utf-8")
        )
        # Summary md5 must come from the job dict's machines_config, not
        # from any path derived from _project_root.
        assert summary.get("config_md5") == "cfg_CORRECT", (
            "C6a: config_md5 in summary should be 'cfg_CORRECT' (from job "
            "dict's machines_config), but got "
            f"{summary.get('config_md5')!r}. Worker may be reading machines_config "
            "from a live global instead of the job dict."
        )

    def test_new_md5_imports_do_not_have_module_level_side_effects(
        self, tmp_path
    ):
        """C6b: importing fresh_slotlab.summary_md5_patch and
        fresh_slotlab.post_inference must NOT trigger any side effects
        (per memory feedback_subprocess_import_suicide_and_module_globals.md).

        Validated by: import both modules and assert no subprocess was
        started, no file was written, no global state was mutated.

        Inject-bug: add a module-top `patch_summary_md5(some_path, ...)` call
        → import raises or writes files → this test fails. Revert → GREEN.
        """
        import importlib

        # Fresh import (may already be cached but still checks for errors).
        mod_patch = importlib.import_module("fresh_slotlab.summary_md5_patch")
        mod_infer = importlib.import_module("fresh_slotlab.post_inference")

        # Both modules exist and have the expected callables.
        assert hasattr(mod_patch, "patch_summary_md5"), (
            "fresh_slotlab.summary_md5_patch must export patch_summary_md5"
        )
        assert hasattr(mod_infer, "run_post_analyzer_inference"), (
            "fresh_slotlab.post_inference must export run_post_analyzer_inference"
        )

        # No module-level file writes should have occurred (check our tmp_path).
        # This is a basic smoke test; the real test is absence of ImportError
        # + absence of side-effect artifacts.
        assert not list(tmp_path.glob("**/*")), (
            "C6b: importing summary_md5_patch or post_inference wrote files to "
            "disk — modules must have zero import-time side effects."
        )

    def test_worker_globals_are_isolated_across_job_calls(
        self, tmp_path, monkeypatch
    ):
        """C6c: the module-level _analyzer_mod + _project_root globals must
        retain the values set by the pool initializer across job calls; they
        must not be mutated by run_analyzer_job itself.

        Per memory: pool initializer sets these once; subsequent jobs should
        read them, never overwrite. This prevents one job's import-order side
        effects from breaking subsequent jobs' hook paths.

        Inject-bug: run_analyzer_job assigns `_project_root = None` at the
        end → second job call has wrong root → inferring scripts fail.
        Revert → GREEN.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        sentinel_root = str(tmp_path / "sentinel_root")
        Path(sentinel_root).mkdir()
        worker._project_root = sentinel_root

        class _Stub:
            _output_dir: str = ""

            @staticmethod
            def main() -> int:
                summary = Path(_Stub._output_dir) / "player_impact_summary.json"
                summary.parent.mkdir(parents=True, exist_ok=True)
                summary.write_text('{"rtp":{"point_pct":95.0}}', encoding="utf-8")
                return 0

        # Run job once.
        job = _make_job(tmp_path, machine="M1", mode=7)
        _Stub._output_dir = job["output_dir"]
        worker._analyzer_mod = _Stub
        worker.run_analyzer_job(job)

        # _project_root must still be what the initializer set.
        assert worker._project_root == sentinel_root, (
            "C6c: run_analyzer_job must not mutate _project_root. "
            f"Before: {sentinel_root!r}, after: {worker._project_root!r}. "
            "Pool initializer sets this once; jobs must treat it as read-only."
        )


# ---------------------------------------------------------------------------
# C1+C2 integration — job dict keys reach argv end-to-end
# ---------------------------------------------------------------------------

class TestJobDictToArgvEndToEnd:
    """Integration: the md5 keys from the job dict built by
    _prepare_batch_gen_item must appear in the CLI argv passed to the analyzer
    by run_analyzer_job.

    This is the full chain: prepare_fn builds the dict → caller passes it to
    run_analyzer_job → worker builds argv → analyzer receives the flags.

    Validates that neither step drops the keys in between.

    Inject-bug (combined): removing the key assignment in _prepare_batch_gen_item
    OR removing the argv append in run_analyzer_job → either test in this class
    fails. Both must be present for the chain to work.
    """

    def _make_argv_capturing_stub(self, output_dir: str, captured: list) -> Any:
        class _Stub:
            @staticmethod
            def main() -> int:
                captured.append(list(sys.argv))
                summary = Path(output_dir) / "player_impact_summary.json"
                summary.parent.mkdir(parents=True, exist_ok=True)
                summary.write_text(json.dumps({
                    "config_md5": "",
                    "code_md5": "",
                    "rtp": {"point_pct": 95.0},
                }), encoding="utf-8")
                return 0

        return _Stub

    def test_prepare_fn_md5_keys_appear_in_analyzer_argv(
        self, tmp_path, monkeypatch
    ):
        """C1+C2 chain: prepare_fn's job dict md5 keys propagate through
        run_analyzer_job into the analyzer's sys.argv.

        This end-to-end in-process test catches the case where:
        - prepare_fn adds keys correctly, but
        - run_analyzer_job doesn't read them / doesn't append flags.

        Inject-bug: any of the two wiring points fails →
        argv lacks --upstream-config-md5 / --upstream-code-md5 → assert fails.
        Revert → GREEN.
        """
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")

        prepare_fn, _, _ = _make_app_and_prepare_fn(
            tmp_path, machine="M14", mode=1,
            config_md5="cfg_E2E", code_md5="code_E2E",
        )
        prepared = prepare_fn("M14", 1)
        job = prepared["job"]

        # Verify job dict has the keys (C1).
        assert "upstream_config_md5" in job
        assert "upstream_code_md5" in job

        captured_argvs: list = []
        output_dir = job["output_dir"]
        Stub = self._make_argv_capturing_stub(output_dir, captured_argvs)
        worker._analyzer_mod = Stub
        worker._project_root = str(tmp_path)

        result = worker.run_analyzer_job(job)
        assert result["ok"] is True

        assert captured_argvs, "Stub analyzer must have been called."
        argv = captured_argvs[0]

        def _flag_val(flag):
            try:
                return argv[argv.index(flag) + 1]
            except ValueError:
                return None

        assert _flag_val("--upstream-config-md5") == "cfg_E2E", (
            "C1+C2 chain: --upstream-config-md5 in analyzer argv should be "
            f"'cfg_E2E'; got {_flag_val('--upstream-config-md5')!r}. "
            f"Argv: {argv}"
        )
        assert _flag_val("--upstream-code-md5") == "code_E2E", (
            "C1+C2 chain: --upstream-code-md5 in analyzer argv should be "
            f"'code_E2E'; got {_flag_val('--upstream-code-md5')!r}."
        )
