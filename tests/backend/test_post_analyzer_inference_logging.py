"""Tests for ``_run_post_analyzer_inference``'s log-to-disk contract.

The in-process generate-report path spawns the inference hook as a
daemon thread — silently dropping its return value on the floor.
Before this fix, variant machines whose hook timed out or failed
left the UI's Pay ID 总览 panel permanently showing "形状推断暂未
运行" with no way to tell why. These tests lock that the hook now
persists its outcome to ``<log_to_dir>/_post_hook.json`` so
operators / engineers can diagnose after the fact.

The tests monkey-patch subprocess.run so they don't actually spawn
the two real inference scripts (which would need full rawdata
fixtures). They focus on the log-to-disk path shape — what the
file contains under each outcome — because that's the specific
regression surface.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.web_console.backend.app import _run_post_analyzer_inference


class TestPostHookLogsToDisk:
    def test_writes_post_hook_json_with_ok_outcome(
        self, tmp_path: Path, monkeypatch,
    ):
        """Successful subprocess → rc=0, _post_hook.json written
        with ok=True for both hooks."""
        # Stub: both subprocesses succeed with empty stderr.
        import subprocess as sp
        def fake_run(cmd, **_kwargs):
            class _P: pass
            p = _P()
            p.returncode = 0
            p.stderr = ""
            p.stdout = ""
            return p
        monkeypatch.setattr(sp, "run", fake_run)
        # Need a fake rawdata dir so the "no_rawdata" shortcut
        # doesn't short-circuit before the subprocesses run.
        raw = tmp_path / "rawdata" / "M14" / "mode_1"
        raw.mkdir(parents=True)
        # SKIP env must NOT be set (conftest autouse fixture flips it
        # on for every test; disable it here so we hit the real path).
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        log_dir = tmp_path / "run_output"
        result = _run_post_analyzer_inference(
            "M14", 1,
            rawdata_root=tmp_path / "rawdata",
            log_to_dir=log_dir,
        )

        log_file = log_dir / "_post_hook.json"
        assert log_file.is_file(), "log file must exist after successful run"
        logged = json.loads(log_file.read_text(encoding="utf-8"))
        assert logged["machine"] == "M14"
        assert logged["mode"] == 1
        assert logged["paytable_shape"]["ok"] is True
        assert logged["classifier"]["ok"] is True
        # Returned dict equals what's on disk — single source of truth
        # (no divergence between caller-visible result and log file).
        assert logged == result

    def test_writes_post_hook_json_with_timeout_outcome(
        self, tmp_path: Path, monkeypatch,
    ):
        """Regression: a timing-out subprocess previously vanished
        silently (daemon thread dropped the error). Now persisted."""
        import subprocess as sp
        def fake_run(cmd, **_kwargs):
            raise sp.TimeoutExpired(cmd, timeout=1.0)
        monkeypatch.setattr(sp, "run", fake_run)
        raw = tmp_path / "rawdata" / "M14" / "mode_1"
        raw.mkdir(parents=True)
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        log_dir = tmp_path / "run_output"
        _run_post_analyzer_inference(
            "M14", 1,
            rawdata_root=tmp_path / "rawdata",
            log_to_dir=log_dir,
        )

        logged = json.loads((log_dir / "_post_hook.json").read_text(encoding="utf-8"))
        assert logged["paytable_shape"]["ok"] is False
        assert logged["paytable_shape"]["error"] == "timeout"
        assert logged["classifier"]["error"] == "timeout"

    def test_writes_post_hook_json_with_nonzero_rc(
        self, tmp_path: Path, monkeypatch,
    ):
        """Subprocess exits non-zero — rc + stderr_tail recorded
        so the operator can diagnose why inference failed."""
        import subprocess as sp
        def fake_run(cmd, **_kwargs):
            class _P: pass
            p = _P()
            p.returncode = 1
            p.stderr = "Traceback (most recent call last):\n  ...boom"
            p.stdout = ""
            return p
        monkeypatch.setattr(sp, "run", fake_run)
        raw = tmp_path / "rawdata" / "M14" / "mode_1"
        raw.mkdir(parents=True)
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)

        log_dir = tmp_path / "run_output"
        _run_post_analyzer_inference(
            "M14", 1,
            rawdata_root=tmp_path / "rawdata",
            log_to_dir=log_dir,
        )

        logged = json.loads((log_dir / "_post_hook.json").read_text(encoding="utf-8"))
        assert logged["paytable_shape"]["ok"] is False
        assert logged["paytable_shape"]["returncode"] == 1
        assert "boom" in logged["paytable_shape"]["stderr_tail"]

    def test_persists_skip_env_shortcircuit(self, tmp_path: Path, monkeypatch):
        """Even the SLOT_SKIP_AUTO_INFER shortcircuit path logs, so
        tests + operators can confirm the env flag actually fired."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        log_dir = tmp_path / "run_output"
        _run_post_analyzer_inference("M14", 1, log_to_dir=log_dir)
        logged = json.loads((log_dir / "_post_hook.json").read_text(encoding="utf-8"))
        assert logged["skipped"] == "env_SLOT_SKIP_AUTO_INFER"

    def test_persists_no_rawdata_shortcircuit(
        self, tmp_path: Path, monkeypatch,
    ):
        """The rawdata-missing shortcircuit also logs — useful for
        variant machines whose first sample hasn't landed yet."""
        monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)
        # rawdata_root/<machine>/mode_<N>/ does NOT exist.
        log_dir = tmp_path / "run_output"
        _run_post_analyzer_inference(
            "M273$WheelSelector$1$1-2-3", 1,
            rawdata_root=tmp_path / "rawdata",
            log_to_dir=log_dir,
        )
        logged = json.loads((log_dir / "_post_hook.json").read_text(encoding="utf-8"))
        assert logged["skipped"] == "no_rawdata_for_pair"

    def test_no_log_dir_preserves_no_op_behaviour(
        self, tmp_path: Path, monkeypatch,
    ):
        """Callers that don't want a log (virtual console, unit
        tests) pass log_to_dir=None — no file is written, return
        value still carries the outcome."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        result = _run_post_analyzer_inference("M14", 1, log_to_dir=None)
        # No file to find — scan tmp_path to prove nothing leaked.
        assert not any(tmp_path.rglob("_post_hook.json"))
        assert result["skipped"] == "env_SLOT_SKIP_AUTO_INFER"

    def test_log_dir_created_if_missing(self, tmp_path: Path, monkeypatch):
        """Defensive: generate-report's output_dir IS created before
        this hook runs, but belt-and-suspenders — the hook mkdir's
        its own log dir so a race during dir cleanup doesn't swallow
        diagnostics."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        log_dir = tmp_path / "deeply" / "nested" / "that" / "doesn't" / "exist"
        assert not log_dir.exists()
        _run_post_analyzer_inference("M14", 1, log_to_dir=log_dir)
        assert (log_dir / "_post_hook.json").is_file()

    def test_variant_machine_name_with_dollars_survives_log_write(
        self, tmp_path: Path, monkeypatch,
    ):
        """Regression guard tied specifically to the variants
        rollout: the machine name in the log payload is a variant
        display name containing ``$``. JSON dump handles it fine;
        path + JSON contents roundtrip without mangling."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        log_dir = tmp_path / "run_output"
        machine = "M201$CommonSelector$1$2,3,4"
        _run_post_analyzer_inference(machine, 1, log_to_dir=log_dir)
        logged = json.loads((log_dir / "_post_hook.json").read_text(encoding="utf-8"))
        assert logged["machine"] == machine
