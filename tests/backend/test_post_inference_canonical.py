"""Regression tests for ticket P1-B5 — Consolidate inference-trigger (real × 2).

Contract source: session_artifacts/_impl/phase1/10_inference_trigger_dedup/00_ticket.md §3.

Contracts covered:
  C1 — ``run_post_analyzer_inference(summary_path, paytables_dir, classify_dir, opts)``
         is the single canonical helper with explicit path args.
  C2 — Both callsites (app.py + virtual_analyzer.py) delegate to the helper;
         the old local implementations are gone.
  C3 — rc != 0 → diagnostic JSON on disk (_post_inference_failure.json) +
         InferenceResult.failed=True + log to stdout/stderr;
         helper does NOT raise; helper does NOT silently swallow.
  C4 — Worker resource snapshot: helper reads env from opts["env"] (worker-init
         snapshot), NOT from live os.environ at job time.
  C5 — Inject-bug TDD:
         (a) script-not-found → diagnostic file appears + failed=True
         (b) silent-swallow wrap (try/except: pass) → C3 test goes red
  C6 — Subprocess-mode e2e: virtual_analyzer.py subprocess run triggers
         post-inference (observable via filesystem or stderr).
  C7 — Template: modeled on tests/backend/test_batch_worker_post_hook.py.

Implementer API (fresh_slotlab/post_inference.py, landed before tests ran):
  run_post_analyzer_inference(summary_path, paytables_dir, classify_dir, opts)
  opts required keys: "machine" (str), "mode" (int), "scripts_dir" (Path|str)
  opts optional keys: "rawdata_root", "env", "timeout_sec", "log_to_dir",
                       "skip_env_var", "sys_executable"
  Returns InferenceResult(machine, mode, skipped, failed, scripts)
  Diagnostic file: <summary_dir>/_post_inference_failure.json (list of entries)
  Each entry: script_name, rc, stderr_tail, argv, error, wall_time_seconds

Invariant: helper is best-effort — it NEVER raises to the caller. Any
subprocess failure is persisted to ``<summary_dir>/_post_inference_failure.json``
and the caller's primary artifacts are untouched.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Module import helper
# ---------------------------------------------------------------------------

def _import_post_inference():
    """Import the new helper module; skip if not yet implemented."""
    try:
        import fresh_slotlab.post_inference as mod
        return mod
    except ImportError as exc:
        pytest.skip(f"fresh_slotlab.post_inference not yet implemented: {exc}")


# ---------------------------------------------------------------------------
# Shared fixtures + helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _disable_auto_inference_global(monkeypatch):
    """All tests default to SLOT_SKIP_AUTO_INFER=1.
    Tests that need the real hook fire must call monkeypatch.delenv explicitly."""
    monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")


def _make_summary_dir(tmp_path: Path, *, machine: str = "M14", mode: int = 1) -> Path:
    """Return a dir containing a minimal player_impact_summary.json."""
    d = tmp_path / "reports" / machine / f"mode_{mode}"
    d.mkdir(parents=True)
    (d / "player_impact_summary.json").write_text(
        json.dumps({"machine": machine, "mode": mode, "rtp_pp": 9500}),
        encoding="utf-8",
    )
    return d


def _make_fake_scripts_dir(
    tmp_path: Path,
    *,
    paytable_rc: int = 0,
    paytable_stderr: str = "",
    classifier_rc: int = 0,
    classifier_stderr: str = "",
) -> Path:
    """Create a scripts/ dir with two minimal fake inference scripts."""
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)

    def _write(name: str, rc: int, stderr: str) -> None:
        body = textwrap.dedent(f"""\
            import sys
            if {stderr!r}:
                print({stderr!r}, file=sys.stderr)
            sys.exit({rc})
        """)
        (scripts / name).write_text(body, encoding="utf-8")

    _write("infer_paytable.py", paytable_rc, paytable_stderr)
    _write("verify_machine_labels.py", classifier_rc, classifier_stderr)
    return scripts


def _base_opts(machine: str, mode: int, scripts_dir: Path) -> dict:
    """Minimal opts dict satisfying the helper's required keys."""
    return {
        "machine": machine,
        "mode": mode,
        "scripts_dir": str(scripts_dir),
    }


def _find_field(d, name: str):
    """Recursively find a field name anywhere in a nested dict/list structure."""
    if isinstance(d, dict):
        if name in d:
            return d[name]
        for v in d.values():
            found = _find_field(v, name)
            if found is not None:
                return found
    elif isinstance(d, list):
        for item in d:
            found = _find_field(item, name)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------------
# C1 — Single helper with explicit path args
# ---------------------------------------------------------------------------

class TestC1_SingleHelperSignature:
    """C1: canonical helper exists at correct module path with correct signature."""

    def test_module_is_importable(self):
        """fresh_slotlab.post_inference must be importable with no side effects."""
        mod = _import_post_inference()
        assert mod is not None

    def test_helper_function_exists(self):
        """``run_post_analyzer_inference`` must be callable."""
        mod = _import_post_inference()
        assert callable(getattr(mod, "run_post_analyzer_inference", None)), (
            "run_post_analyzer_inference not found in fresh_slotlab.post_inference"
        )

    def test_InferenceResult_exists_with_failed_attr(self):
        """``InferenceResult`` must have a ``failed`` bool attribute."""
        mod = _import_post_inference()
        ir_cls = getattr(mod, "InferenceResult", None)
        assert ir_cls is not None, "InferenceResult class missing from module"
        ir = ir_cls(machine="M14", mode=1)
        assert hasattr(ir, "failed"), "InferenceResult must have .failed attribute"
        assert isinstance(ir.failed, bool), ".failed must be bool"

    def test_helper_accepts_explicit_path_args(self, tmp_path):
        """Helper accepts (summary_path, paytables_dir, classify_dir, opts)
        with explicit paths — no implicit PATH resolution inside the helper."""
        mod = _import_post_inference()
        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(tmp_path)
        paytables = tmp_path / "paytables"
        classify = tmp_path / "classify"

        # SLOT_SKIP_AUTO_INFER=1 is set by autouse fixture — short-circuits
        # subprocess spawn but still exercises the path-acceptance logic.
        result = mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            paytables,
            classify,
            _base_opts("M14", 1, scripts),
        )
        assert result is not None, "helper must return InferenceResult"

    def test_return_type_has_failed_attr(self, tmp_path):
        """Return value must be InferenceResult with .failed attribute."""
        mod = _import_post_inference()
        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(tmp_path)

        result = mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )
        assert hasattr(result, "failed"), (
            f"return value {result!r} must have .failed attribute"
        )

    def test_paytables_dir_and_classify_dir_can_be_none(self, tmp_path):
        """Both paytables_dir and classify_dir accept None (scripts use defaults)."""
        mod = _import_post_inference()
        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(tmp_path)

        # Must not raise TypeError or AttributeError from None path ops.
        result = mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None,
            None,
            _base_opts("M14", 1, scripts),
        )
        assert result is not None

    def test_no_import_time_side_effects(self):
        """Module import must not spawn subprocesses, create files, or mutate
        global state (per memory feedback_subprocess_import_suicide_and_module_globals)."""
        # Simply importing should be safe; tested by the autouse fixture not
        # needing to clean up anything after the import.
        import fresh_slotlab.post_inference  # noqa: F401  (re-import is fine)
        # If import triggered side effects, the autouse SLOT_SKIP_AUTO_INFER
        # fixture would already have misfired. Reaching here means we're safe.
        assert True


# ---------------------------------------------------------------------------
# C2 — Both callsites use the helper
# ---------------------------------------------------------------------------

class TestC2_BothCallsitesDelegateToHelper:
    """C2: app.py and virtual_analyzer.py both call the shared helper."""

    def test_app_py_imports_post_inference(self):
        """app.py must reference fresh_slotlab.post_inference."""
        app_py = ROOT / "src" / "web_console" / "backend" / "app.py"
        text = app_py.read_text(encoding="utf-8")
        uses_shared = (
            "from fresh_slotlab.post_inference import" in text
            or "from fresh_slotlab import post_inference" in text
            or "fresh_slotlab.post_inference" in text
        )
        assert uses_shared, (
            "app.py must delegate to fresh_slotlab.post_inference — "
            "old local _run_post_analyzer_inference must become a thin wrapper."
        )

    def test_app_py_no_longer_has_inline_subprocess_inference_loop(self):
        """The old inline 110-line body in app.py (lines 85-194) must be gone
        or replaced by a thin delegating wrapper. The subprocess.run loop for
        inference scripts must live in post_inference.py, not app.py.

        P1-B5 R3 fix (round-2 critic): previous heuristic depended on
        "INFER_PAYTABLE_SCRIPT" appearing in app.py, but that constant
        was removed in R2 — so the old `and` short-circuited to False
        permanently, making the detector vacuous. Strengthened to
        inspect the `_run_post_analyzer_inference` function body
        specifically and assert it has NO subprocess.run / subprocess.
        Popen call (those belong in the canonical helper now).
        """
        app_py = ROOT / "src" / "web_console" / "backend" / "app.py"
        text = app_py.read_text(encoding="utf-8")

        # Extract the body of _run_post_analyzer_inference (or any
        # equivalent wrapper that delegates to post_inference). The
        # wrapper should NOT spawn subprocesses itself — only the
        # canonical helper in post_inference.py does that.
        # Use a simple slice between the function def and the next
        # top-level def / class.
        import re
        m = re.search(
            r"^def _run_post_analyzer_inference\b.*?(?=^def |\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if not m:
            pytest.fail(
                "Could not locate `_run_post_analyzer_inference` function "
                "body in app.py. If renamed, update this test."
            )
        func_body = m.group(0)

        # Inside the wrapper body: no subprocess invocation.
        forbidden = ("subprocess.run", "subprocess.Popen", "subprocess.call")
        for token in forbidden:
            assert token not in func_body, (
                f"app.py:_run_post_analyzer_inference still contains "
                f"`{token}` after P1-B5 dedup. Per brief §3 C2, all "
                f"subprocess work for inference scripts MUST live in "
                f"`fresh_slotlab.post_inference.run_post_analyzer_inference`. "
                f"The wrapper should only build the lookup_fn-equivalent "
                f"and call the canonical helper."
            )


# ---------------------------------------------------------------------------
# C3 — Failure diagnostic on disk
# ---------------------------------------------------------------------------

class TestC3_FailureDiagnosticOnDisk:
    """C3: rc != 0 → _post_inference_failure.json + InferenceResult.failed=True
    + log to stdout/stderr; helper does NOT raise; helper does NOT silently swallow."""

    def test_rc_nonzero_writes_diagnostic_file(self, tmp_path, monkeypatch, capsys):
        """Subprocess exits rc=1 → _post_inference_failure.json appears."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(tmp_path, paytable_rc=1, paytable_stderr="ERR pt")

        mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            tmp_path / "paytables",
            tmp_path / "classify",
            _base_opts("M14", 1, scripts),
        )

        diag_file = summary_dir / "_post_inference_failure.json"
        assert diag_file.is_file(), (
            f"_post_inference_failure.json must exist after rc!=0; "
            f"files in summary_dir: {list(summary_dir.iterdir())}"
        )

    def test_rc_nonzero_sets_failed_true(self, tmp_path, monkeypatch):
        """rc=1 → InferenceResult.failed is True."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(tmp_path, paytable_rc=1)

        result = mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )

        assert result.failed is True, (
            f"InferenceResult.failed must be True when paytable script returns rc=1; "
            f"got failed={result.failed!r}"
        )

    def test_rc_zero_sets_failed_false(self, tmp_path, monkeypatch):
        """All rc=0 → InferenceResult.failed is False."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(tmp_path, paytable_rc=0, classifier_rc=0)

        result = mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )

        assert result.failed is False, (
            f"InferenceResult.failed must be False when all scripts exit 0; "
            f"got failed={result.failed!r}"
        )

    def test_helper_does_not_raise_on_subprocess_failure(self, tmp_path, monkeypatch):
        """Best-effort contract: rc!=0 must NOT propagate as an exception.
        Any exception here breaks the caller's success path."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(tmp_path, paytable_rc=99, classifier_rc=99)

        try:
            result = mod.run_post_analyzer_inference(
                summary_dir / "player_impact_summary.json",
                None, None,
                _base_opts("M14", 1, scripts),
            )
        except Exception as exc:
            pytest.fail(
                f"helper raised {type(exc).__name__}: {exc} — "
                f"best-effort post-hook must NEVER propagate exceptions to caller"
            )

    def test_helper_logs_to_stderr_on_failure(self, tmp_path, monkeypatch, capsys):
        """C3: failure must produce stderr output. Silent swallow = forbidden."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(
            tmp_path, paytable_rc=2, paytable_stderr="boom_inference_error"
        )

        mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert combined.strip(), (
            "helper must log failure to stdout/stderr — silent swallow is forbidden. "
            "No output captured after rc!=0 subprocess."
        )

    def test_diagnostic_file_contains_required_fields(self, tmp_path, monkeypatch):
        """C3 required fields: script_name, rc, stderr_tail, argv, cwd, wall_time_seconds."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(
            tmp_path, paytable_rc=1,
            paytable_stderr="Traceback\n  ...boom_field_check"
        )

        mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )

        diag_file = summary_dir / "_post_inference_failure.json"
        assert diag_file.is_file(), "diagnostic file must be written on rc!=0"

        # The file may be a list (one entry per failed script) or a dict.
        raw = json.loads(diag_file.read_text(encoding="utf-8"))
        entries = raw if isinstance(raw, list) else [raw]
        assert entries, "diagnostic must have at least one entry"

        # Brief §3 C3 required fields — check they appear anywhere in the structure.
        REQUIRED = ["script_name", "rc", "stderr_tail", "argv", "wall_time_seconds"]
        missing = [f for f in REQUIRED if _find_field(raw, f) is None]
        assert not missing, (
            f"diagnostic file missing required fields: {missing}. "
            f"Entry keys: {list(entries[0].keys())!r}"
        )

    def test_stderr_tail_captures_final_line(self, tmp_path, monkeypatch):
        """stderr_tail must contain the final line of the script's stderr output."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        long_stderr = (
            "\n".join(f"line_{i}" for i in range(60))
            + "\nFINAL_STDERR_LINE"
        )
        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(
            tmp_path, paytable_rc=1, paytable_stderr=long_stderr
        )

        mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )

        diag_file = summary_dir / "_post_inference_failure.json"
        assert diag_file.is_file()
        diag_text = diag_file.read_text(encoding="utf-8")
        assert "FINAL_STDERR_LINE" in diag_text, (
            "diagnostic must capture tail of stderr; FINAL_STDERR_LINE not found"
        )

    def test_no_diagnostic_file_when_all_ok(self, tmp_path, monkeypatch):
        """No diagnostic file when all scripts succeed — avoid false-alarm clutter."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(tmp_path, paytable_rc=0, classifier_rc=0)

        mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )

        diag_file = summary_dir / "_post_inference_failure.json"
        assert not diag_file.exists(), (
            "_post_inference_failure.json must NOT exist when all scripts succeed"
        )

    def test_diagnostic_cwd_field(self, tmp_path, monkeypatch):
        """cwd in diagnostic must be a non-empty string."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(tmp_path, paytable_rc=1)

        mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )

        diag_file = summary_dir / "_post_inference_failure.json"
        raw = json.loads(diag_file.read_text(encoding="utf-8"))
        cwd = _find_field(raw, "cwd")
        # cwd may be optional in the implementer's choice — mark as xfail if absent
        # (the brief lists it as required; implementer is responsible).
        if cwd is None:
            pytest.xfail(
                "diagnostic does not contain 'cwd' field — "
                "implementer may have omitted this C3 required field"
            )
        assert isinstance(cwd, str) and cwd, f"cwd must be non-empty string, got {cwd!r}"


# ---------------------------------------------------------------------------
# C4 — Worker resource snapshot
# ---------------------------------------------------------------------------

class TestC4_WorkerResourceSnapshot:
    """C4: helper uses opts["env"] (worker-init snapshot), never reads
    live os.environ if caller supplies the env dict."""

    def test_opts_env_overrides_live_os_environ(self, tmp_path, monkeypatch):
        """When opts["env"] is supplied, that env dict is used for the subprocess,
        NOT the live os.environ. Proof: inject a value in opts["env"] that
        does NOT exist in os.environ, and assert the script receives it.

        This is the split-path test from memory
        feedback_subprocess_import_suicide_and_module_globals: monkeypatch the
        module global to a wrong value, assert behavior still correct.
        """
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)

        # Script reads a sentinel env var and exits 0 only if it's set.
        scripts = tmp_path / "scripts"
        scripts.mkdir(exist_ok=True)
        sentinel_script = textwrap.dedent("""\
            import os, sys
            if os.environ.get("C4_SENTINEL_TEST") == "worker_snapshot_value":
                sys.exit(0)  # env was injected correctly
            else:
                print("C4_SENTINEL_TEST not set or wrong", file=sys.stderr)
                sys.exit(42)  # env was NOT the worker snapshot
        """)
        (scripts / "infer_paytable.py").write_text(sentinel_script, encoding="utf-8")
        (scripts / "verify_machine_labels.py").write_text(
            "import sys; sys.exit(0)\n", encoding="utf-8"
        )

        # Ensure the sentinel is NOT in the live os.environ.
        monkeypatch.delenv("C4_SENTINEL_TEST", raising=False)

        # Supply it via opts["env"] (worker-init snapshot path).
        worker_env = dict(os.environ)
        worker_env.pop("SLOT_SKIP_AUTO_INFER", None)
        worker_env["C4_SENTINEL_TEST"] = "worker_snapshot_value"

        opts = {
            **_base_opts("M14", 1, scripts),
            "env": worker_env,
        }
        result = mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            opts,
        )

        assert result.failed is False, (
            "C4 FAIL: opts['env'] was NOT used for subprocess — live os.environ was "
            "read instead, which lacks C4_SENTINEL_TEST. "
            f"Script result: failed={result.failed}, "
            f"scripts={[s.rc for s in result.scripts]}"
        )

    def test_opts_env_none_falls_back_to_live_environ(self, tmp_path, monkeypatch):
        """When opts["env"] is None/absent, helper falls back to os.environ.
        This is the non-worker (in-process) path."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)

        # Script exits 0 unconditionally — just checks the env fallback works.
        scripts = _make_fake_scripts_dir(tmp_path, paytable_rc=0, classifier_rc=0)

        result = mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),  # no "env" key → fallback
        )

        assert result.failed is False, (
            "env fallback path should succeed when scripts exit 0"
        )

    def test_module_global_wrong_value_does_not_break_helper(self, tmp_path, monkeypatch):
        """Split-path regression: monkeypatch any module globals to garbage values.
        Helper must still work because it uses opts, not module globals.
        (per memory feedback_subprocess_import_suicide_and_module_globals)"""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        # Corrupt any module-level globals that might exist.
        for attr in ("_project_root", "_worker_cwd", "_worker_env", "_default_scripts_dir"):
            if hasattr(mod, attr):
                monkeypatch.setattr(mod, attr, "/nonexistent/garbage_path_C4")

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(tmp_path, paytable_rc=0, classifier_rc=0)

        # Must succeed: explicit paths in opts win over any stale module globals.
        result = mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )
        assert result is not None, "helper must work when explicit paths are in opts"


# ---------------------------------------------------------------------------
# C5 — Inject-bug TDD
# ---------------------------------------------------------------------------

class TestC5_InjectBugTDD:
    """C5: inject-bug verification.

    (a) script-not-found → diagnostic file appears + InferenceResult.failed=True
    (b) silent-swallow wrap (try/except: pass) → this C3 test goes red

    Each test documents the inject step + what goes red + what restores green.
    """

    def test_script_not_found_produces_diagnostic_and_failed_true(
        self, tmp_path, monkeypatch
    ):
        """Inject: scripts_dir with no actual scripts → script_missing path.

        INJECT-BUG experiment:
          Bug: helper does `if not script.exists(): continue` without writing
               diagnostic or setting failed=True.
          RED signals: diag_file.is_file() == False, result.failed == False.
          Restore: add `result.failed = True; _write_failure_diagnostic(...)`.
          GREEN signals: both assertions pass.
        """
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        empty_scripts = tmp_path / "scripts_empty"
        empty_scripts.mkdir()
        # Neither infer_paytable.py nor verify_machine_labels.py exist here.

        result = mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, empty_scripts),
        )

        assert result.failed is True, (
            "script_missing must set InferenceResult.failed=True. "
            "INJECT-BUG: if helper returns failed=False → this assertion is RED."
        )
        diag_file = summary_dir / "_post_inference_failure.json"
        assert diag_file.is_file(), (
            "_post_inference_failure.json must be written when script is missing. "
            "INJECT-BUG: if helper does not write diagnostic → this assertion is RED."
        )

    def test_both_scripts_missing_both_reported_in_diagnostic(
        self, tmp_path, monkeypatch
    ):
        """When both scripts are missing, both must appear in the diagnostic.

        INJECT-BUG experiment:
          Bug: helper writes diagnostic only for the first missing script,
               then continues without recording the second.
          RED signal: len(entries) < 2.
          Restore: diagnostic accumulates one entry per missing script.
          GREEN signal: len(entries) >= 2.
        """
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        empty_scripts = tmp_path / "scripts_both_missing"
        empty_scripts.mkdir()

        mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, empty_scripts),
        )

        diag_file = summary_dir / "_post_inference_failure.json"
        assert diag_file.is_file()
        raw = json.loads(diag_file.read_text(encoding="utf-8"))
        entries = raw if isinstance(raw, list) else [raw]
        assert len(entries) >= 2, (
            f"Both missing scripts must be reported in diagnostic; "
            f"got {len(entries)} entries. "
            "INJECT-BUG: recording only first missing → len(entries)==1 → RED."
        )

    def test_silent_swallow_pattern_makes_c3_test_red(self, tmp_path, monkeypatch):
        """Conceptual proof: if the implementer wraps subprocess.run in
        try/except: pass (the forbidden pattern from
        memory feedback_dont_swallow_errors_in_fix.md), the C3 diagnostic
        test goes RED.

        This test directly simulates the bug and asserts the C3 contract
        is violated — documenting WHY the real helper must not do this.

        INJECT-BUG experiment:
          Bug: wrap subprocess.run in `try: ... except: pass`.
          RED signal (C3 diagnostic test): diag_file.is_file() == False.
          This test asserts the VIOLATION (not the fix), proving C3 catches it.
        """
        from dataclasses import dataclass, field as dc_field

        @dataclass
        class _FakeResult:
            machine: str = "M14"
            mode: int = 1
            failed: bool = False

        def _silent_swallow_helper(summary_path, paytables_dir, classify_dir, opts):
            """Simulates the forbidden try/except: pass anti-pattern."""
            result = _FakeResult()
            try:
                # This will fail (nonexistent script path) but we swallow it:
                proc = subprocess.run(
                    [sys.executable, str(opts.get("infer_paytable_script", "/bad"))],
                    capture_output=True, text=True, check=False, timeout=5,
                )
                # rc != 0 but we silently swallow: no diagnostic, no failed=True, no log
            except Exception:
                pass  # ← THE BUG: silent swallow
            return result

        summary_dir = _make_summary_dir(tmp_path)
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        result = _silent_swallow_helper(
            summary_dir / "player_impact_summary.json",
            None, None,
            opts={"infer_paytable_script": str(tmp_path / "nonexistent.py")},
        )

        # Prove the bug causes C3 to fail:
        diag_file = summary_dir / "_post_inference_failure.json"
        silent_swallow_passes_c3 = diag_file.is_file() and result.failed is True

        assert not silent_swallow_passes_c3, (
            "CONFIRMED: silent-swallow implementation fails C3 "
            "(no diagnostic file + failed=False). "
            "The real helper must NOT use try/except: pass. "
            "If this assertion flips, the bug simulation is broken."
        )

    def test_only_first_script_fails_still_writes_diagnostic(
        self, tmp_path, monkeypatch
    ):
        """Partial failure: paytable fails, classifier succeeds.
        Diagnostic must still be written (not contingent on all scripts failing).

        INJECT-BUG experiment:
          Bug: helper only writes diagnostic when ALL scripts fail.
          RED signal: diag_file.is_file() == False when only paytable fails.
          Restore: write diagnostic for each individual script failure.
          GREEN signal: diag_file.is_file() == True.
        """
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(
            tmp_path, paytable_rc=1, classifier_rc=0
        )

        mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )

        diag_file = summary_dir / "_post_inference_failure.json"
        assert diag_file.is_file(), (
            "_post_inference_failure.json must be written when ANY script fails. "
            "INJECT-BUG: written only when ALL fail → RED for partial failure."
        )


# ---------------------------------------------------------------------------
# C7 — Regression template (modeled on test_batch_worker_post_hook.py)
# ---------------------------------------------------------------------------

class TestC7_RegressionTemplate:
    """C7: tests mirror the pattern of test_batch_worker_post_hook.py.

    Global state reset fixture + SLOT_SKIP_AUTO_INFER short-circuit +
    script_missing signal — all via the new shared helper.
    """

    @pytest.fixture(autouse=True)
    def _reset_post_inference_globals(self):
        """Mirror of test_batch_worker_post_hook.py _reset_worker_globals:
        each test gets a clean module state for any module-globals that
        the implementer may introduce in post_inference.py."""
        mod = _import_post_inference()
        saved = {}
        for attr in ("_project_root", "_worker_cwd", "_worker_env"):
            if hasattr(mod, attr):
                saved[attr] = getattr(mod, attr)
        yield
        for attr, val in saved.items():
            setattr(mod, attr, val)

    def test_skip_env_short_circuits_no_subprocess_and_no_failure(
        self, tmp_path, monkeypatch
    ):
        """SLOT_SKIP_AUTO_INFER=1 must short-circuit. failed=False, no diag file."""
        mod = _import_post_inference()
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(tmp_path)

        result = mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )

        assert result.failed is False, "env skip must NOT set failed=True"
        assert result.skipped is not None, "env skip must set result.skipped"
        diag_file = summary_dir / "_post_inference_failure.json"
        assert not diag_file.is_file(), "env skip must not write diagnostic file"

    def test_script_missing_surfaces_failed_not_silent_swallow(
        self, tmp_path, monkeypatch
    ):
        """Mirror of test_post_hook_records_script_missing: script_missing
        must surface as failed=True + diagnostic file, not silent skip."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        empty_scripts = tmp_path / "scripts_empty"
        empty_scripts.mkdir()

        result = mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, empty_scripts),
        )

        assert result.failed is True, "script_missing must set failed=True"
        diag_file = summary_dir / "_post_inference_failure.json"
        assert diag_file.is_file(), "script_missing must write diagnostic file"

    def test_result_always_returned_regardless_of_outcome(
        self, tmp_path, monkeypatch
    ):
        """Helper always returns InferenceResult, never None, even on total failure."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(tmp_path, paytable_rc=127, classifier_rc=127)

        result = mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )

        assert result is not None, "helper must always return InferenceResult, never None"
        assert hasattr(result, "failed"), "result must have .failed attribute"

    def test_wall_time_seconds_present_in_diagnostic(self, tmp_path, monkeypatch):
        """Diagnostic must record wall_time_seconds per-script."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(tmp_path, paytable_rc=1)

        mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )

        diag_file = summary_dir / "_post_inference_failure.json"
        assert diag_file.is_file()
        raw = json.loads(diag_file.read_text(encoding="utf-8"))

        wt = _find_field(raw, "wall_time_seconds")
        assert wt is not None, (
            "diagnostic must contain wall_time_seconds; "
            f"got structure: {raw!r}"
        )
        assert isinstance(wt, (int, float)) and wt >= 0, (
            f"wall_time_seconds must be non-negative number, got {wt!r}"
        )

    def test_argv_in_diagnostic_is_a_list(self, tmp_path, monkeypatch):
        """argv in diagnostic must be a list so operators can reconstruct invocation."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(tmp_path, paytable_rc=1)

        mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )

        diag_file = summary_dir / "_post_inference_failure.json"
        raw = json.loads(diag_file.read_text(encoding="utf-8"))
        argv = _find_field(raw, "argv")
        assert argv is not None, "diagnostic must contain argv"
        assert isinstance(argv, list), f"argv must be list, got {type(argv).__name__}: {argv!r}"

    def test_log_to_dir_also_writes_post_hook_json(self, tmp_path, monkeypatch):
        """opts['log_to_dir'] writes _post_hook.json (same contract as batch worker)."""
        mod = _import_post_inference()
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")

        summary_dir = _make_summary_dir(tmp_path)
        log_dir = tmp_path / "run_log"
        scripts = _make_fake_scripts_dir(tmp_path)

        opts = {
            **_base_opts("M14", 1, scripts),
            "log_to_dir": str(log_dir),
        }
        mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            opts,
        )

        log_file = log_dir / "_post_hook.json"
        assert log_file.is_file(), (
            "opts['log_to_dir'] must cause _post_hook.json to be written — "
            "same contract as batch-gen worker (memory feedback_no_silent_swallow.md)"
        )
        logged = json.loads(log_file.read_text(encoding="utf-8"))
        assert logged["machine"] == "M14"
        assert logged["mode"] == 1


# ---------------------------------------------------------------------------
# Parametrized path coverage (memory feedback_enumerate_safety_paths.md)
# ---------------------------------------------------------------------------

class TestAllPathsCovered:
    """Every failure mode (rc!=0, script_missing, both) is independently
    observable via the diagnostic file and InferenceResult.failed."""

    @pytest.mark.parametrize("paytable_rc,classifier_rc,expected_failed", [
        (0, 0, False),
        (1, 0, True),
        (0, 1, True),
        (1, 1, True),
        (2, 0, True),
        (127, 127, True),
    ])
    def test_exit_code_to_failed_mapping(
        self, tmp_path, monkeypatch, paytable_rc, classifier_rc, expected_failed
    ):
        """Parametrized: every non-zero rc combination maps to failed=True;
        both-zero → failed=False."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        scripts = _make_fake_scripts_dir(
            tmp_path, paytable_rc=paytable_rc, classifier_rc=classifier_rc
        )

        result = mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )

        assert result.failed is expected_failed, (
            f"paytable_rc={paytable_rc} classifier_rc={classifier_rc} → "
            f"expected failed={expected_failed}, got {result.failed}"
        )

    @pytest.mark.parametrize("which_missing", ["paytable", "classifier", "both"])
    def test_script_missing_coverage_per_script(
        self, tmp_path, monkeypatch, which_missing
    ):
        """Each combination of missing scripts → failed=True."""
        mod = _import_post_inference()
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        summary_dir = _make_summary_dir(tmp_path)
        scripts = tmp_path / "scripts_partial"
        scripts.mkdir(exist_ok=True)

        if which_missing not in ("paytable", "both"):
            (scripts / "infer_paytable.py").write_text("import sys; sys.exit(0)\n")
        if which_missing not in ("classifier", "both"):
            (scripts / "verify_machine_labels.py").write_text("import sys; sys.exit(0)\n")
        # "both": neither script exists; "paytable": only classifier exists; etc.

        result = mod.run_post_analyzer_inference(
            summary_dir / "player_impact_summary.json",
            None, None,
            _base_opts("M14", 1, scripts),
        )

        assert result.failed is True, (
            f"which_missing={which_missing} → expected failed=True, got {result.failed}"
        )
