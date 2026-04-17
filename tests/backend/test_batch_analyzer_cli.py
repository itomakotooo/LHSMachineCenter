"""End-to-end integration: POST /api/batch-run → analyzer CLI args.

This closes a testing gap that hid the M273 Fuzzy bug multiple times
across 2026-04-17. Prior tests verified:
  - backend flag logic (item["reuse_cache"] / ["resume_cache"])
  - analyzer CLI accepting --resume-from-cache
  - session_halfwidth_pp math in isolation
…but NO test followed the full chain `POST /batch-run → _run_one →
RunManager.start_run → popen_factory cmd` to check that the analyzer
actually receives the flag the user expected. So when Fuzzy was routed
through `--from-cache` (read-only) and finished in 1s at cache-CI, the
test suite accepted that behavior as "correct" because one test even
asserted the read-only event text appeared.

These tests assert on the actual argv list captured by `stub_popen`.
If someone re-introduces a code path where Fuzzy hits `--from-cache`,
or where precise target skips the cache, the red test will make it
visible BEFORE the user does.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _seed_v3_chunks(root: Path, machine: str, mode: int, n: int = 3) -> None:
    from fresh_slotlab.player_impact_analyzer import _save_chunk_cache
    mode_dir = root / machine / f"mode_{mode}"
    mode_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        resp = [
            {"roundResult": json.dumps([
                {"BetAmount": 1000, "WinCredits": 900,
                 "StopSymbolsByCol": "A|B|C|D|E", "SpinType": "Normal"}
            ])}
        ]
        _save_chunk_cache(resp, i, machine, mode, 1000, 1000, 10, mode_dir)


def _batch_payload(machine: str, mode: int, target: float) -> dict[str, Any]:
    return {
        "items": [{"machine": machine, "mode": mode, "chunk_spin_times": 1000}],
        "concurrency": 1,
        "chunk_spin_times": 1000,
        "chunk_robot_count": 20,
        "max_chunks": 5,
        "target_halfwidth_pp": target,
        "batch_concurrency": 2,
        "timeout": 300,
        "auto_cleanup_cache": False,
    }


def _wait_for_analyzer_cmd(stub_popen, deadline_s: float = 15.0) -> list[str] | None:
    """Poll until _run_one spawns the analyzer subprocess, capturing
    its argv via stub_popen. Returns the captured command or None on
    timeout. Conftest fake_analyzer is a tmp `.py` file (not the real
    player_impact_analyzer.py), so match by the script's actual name."""
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        # stub_popen captures ALL subprocess spawns; in test mode the
        # analyzer is pointed at `fake_analyzer.py` per conftest, so
        # we check for any cmd that includes --target-halfwidth-pp
        # (unique to the analyzer call).
        for cmd in stub_popen.cmds:
            if "--target-halfwidth-pp" in cmd:
                return list(cmd)
        time.sleep(0.05)
    return None


def _release_stubs(stub_popen) -> None:
    """Let the watcher thread finish communicate() so the batch item
    transitions out of 'running' and _run_one's _wait_for_run returns."""
    for p in list(stub_popen.processes):
        if not getattr(p, "_communicated", False):
            p.finish(0)


class TestAnalyzerReceivesResumeFlag:
    """The regression the test suite should have caught but didn't."""

    def test_fuzzy_target_with_cache_passes_resume_from_cache(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """Fuzzy (target=0) + local cache must launch analyzer with
        `--resume-from-cache <dir>`, NOT `--from-cache <dir>`. Read-only
        `--from-cache` is what silently returned 12.9pp CI after 1s."""
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "dev_rawdata"
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))
        _seed_v3_chunks(raw_root, "M273", 1, n=2)

        r = c.post("/api/batch-run", json=_batch_payload("M273", 1, target=0.0))
        assert r.status_code == 200

        cmd = _wait_for_analyzer_cmd(app_factory.stub_popen)
        _release_stubs(app_factory.stub_popen)
        assert cmd is not None, "analyzer subprocess never launched"

        # THE REGRESSION: cmd must contain --resume-from-cache, not --from-cache.
        assert "--resume-from-cache" in cmd, (
            f"Fuzzy+cache should resume, but cmd was: {cmd}"
        )
        assert "--from-cache" not in cmd, (
            f"Fuzzy+cache must NOT use read-only --from-cache. cmd: {cmd}"
        )
        # And the cache dir argument must point at the seeded dir.
        rfc_idx = cmd.index("--resume-from-cache")
        cache_arg = cmd[rfc_idx + 1]
        assert "M273" in cache_arg and "mode_1" in cache_arg, cache_arg

    def test_precise_target_with_cache_passes_resume_from_cache(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """Precise target (0.5pp) + cache: same expectation — resume,
        not read-only. Without this, user's 0.5pp ask is silently
        served from a 10k-spin cache giving 12.9pp."""
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "dev_rawdata"
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))
        _seed_v3_chunks(raw_root, "M1", 1, n=3)

        r = c.post("/api/batch-run", json=_batch_payload("M1", 1, target=0.5))
        assert r.status_code == 200

        cmd = _wait_for_analyzer_cmd(app_factory.stub_popen)
        _release_stubs(app_factory.stub_popen)
        assert cmd is not None
        assert "--resume-from-cache" in cmd, cmd
        assert "--from-cache" not in cmd, cmd

    def test_no_cache_no_cache_flag_fresh_sample(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """Negative case: no cache → analyzer CLI must have neither
        --from-cache nor --resume-from-cache."""
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "dev_rawdata"
        raw_root.mkdir()  # exists but empty
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)

        r = c.post("/api/batch-run", json=_batch_payload("Mnew", 1, target=0.5))
        assert r.status_code == 200

        cmd = _wait_for_analyzer_cmd(app_factory.stub_popen)
        _release_stubs(app_factory.stub_popen)
        assert cmd is not None
        assert "--from-cache" not in cmd, cmd
        assert "--resume-from-cache" not in cmd, cmd

    def test_target_halfwidth_pp_propagates_to_cli(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """Regression guard: whatever target the user selected must
        land on the analyzer CLI as `--target-halfwidth-pp <value>`.
        Previously-silent bugs where the backend overrode target to
        a different tier would be caught here."""
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "dev_rawdata"
        raw_root.mkdir()
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)

        r = c.post("/api/batch-run", json=_batch_payload("Mx", 1, target=0.5))
        assert r.status_code == 200

        cmd = _wait_for_analyzer_cmd(app_factory.stub_popen)
        _release_stubs(app_factory.stub_popen)
        assert cmd is not None
        assert "--target-halfwidth-pp" in cmd
        tp_idx = cmd.index("--target-halfwidth-pp")
        assert float(cmd[tp_idx + 1]) == 0.5, cmd


class TestAnalyzerCmdForFuzzyNoCache:
    """Fuzzy without cache should be fresh sample with target=0 passed
    through so analyzer's loop uses max_chunks (not CI) as the budget."""

    def test_fuzzy_no_cache(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "dev_rawdata"
        raw_root.mkdir()
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)

        r = c.post("/api/batch-run", json=_batch_payload("MfuzzyNoCache", 2, target=0.0))
        assert r.status_code == 200

        cmd = _wait_for_analyzer_cmd(app_factory.stub_popen)
        _release_stubs(app_factory.stub_popen)
        assert cmd is not None
        assert "--from-cache" not in cmd
        assert "--resume-from-cache" not in cmd
        # RunManager rewrites target=0 (fuzzy signal from the user) to
        # 999 so the analyzer's CI-stop branch never fires, and bumps
        # max_chunks to cover ~1M spins. See RunManager.start_run.
        tp_idx = cmd.index("--target-halfwidth-pp")
        assert float(cmd[tp_idx + 1]) == 999.0, cmd
