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
        raw_root = tmp_path / "rawdata"
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
        raw_root = tmp_path / "rawdata"
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

    def test_first_time_sample_persists_to_rawdata(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """2026-04-21 REGRESSION: first-time sample used to route chunks
        to ``cache/<run_id>/`` scratch (auto-cleaned post-run), so
        consecutive samples of the same machine never accumulated in
        rawdata/. The user's "5pp 采完接着 0.5 但 5pp rawdata 没了"
        bug was exactly this — the 5pp chunks never landed in rawdata
        to begin with.

        Fix: when the rawdata dir has zero historical-md5 chunks
        (either empty OR all current-md5), backend passes
        ``--resume-from-cache <rawdata_dir>`` so the analyzer writes
        directly into rawdata/ — chunks persist for the next run."""
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "rawdata"
        raw_root.mkdir(exist_ok=True)  # exists but empty
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)

        r = c.post("/api/batch-run", json=_batch_payload("Mnew", 1, target=0.5))
        assert r.status_code == 200

        cmd = _wait_for_analyzer_cmd(app_factory.stub_popen)
        _release_stubs(app_factory.stub_popen)
        assert cmd is not None
        # --from-cache is read-only mode; never used from batch-run
        assert "--from-cache" not in cmd, cmd
        # --resume-from-cache points at the rawdata dir so new chunks
        # persist even on first-time sample.
        assert "--resume-from-cache" in cmd, cmd
        rfc_idx = cmd.index("--resume-from-cache")
        cache_arg = cmd[rfc_idx + 1]
        assert "Mnew" in cache_arg and "mode_1" in cache_arg, cache_arg

    def test_target_halfwidth_pp_propagates_to_cli(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """Regression guard: whatever target the user selected must
        land on the analyzer CLI as `--target-halfwidth-pp <value>`.
        Previously-silent bugs where the backend overrode target to
        a different tier would be caught here."""
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "rawdata"
        raw_root.mkdir(exist_ok=True)
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
        raw_root = tmp_path / "rawdata"
        raw_root.mkdir(exist_ok=True)
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)

        r = c.post("/api/batch-run", json=_batch_payload("MfuzzyNoCache", 2, target=0.0))
        assert r.status_code == 200

        cmd = _wait_for_analyzer_cmd(app_factory.stub_popen)
        _release_stubs(app_factory.stub_popen)
        assert cmd is not None
        assert "--from-cache" not in cmd
        # 2026-04-21: first-time sample now passes --resume-from-cache
        # pointed at the empty rawdata dir so new chunks persist (fix
        # for "5pp rawdata 没了" — first-time samples used to land in
        # cache/<run_id>/ scratch and vanish after auto_cleanup_cache).
        assert "--resume-from-cache" in cmd
        # RunManager rewrites target=0 (fuzzy signal from the user) to
        # 999 so the analyzer's CI-stop branch never fires, and bumps
        # max_chunks to cover ~1M spins. See RunManager.start_run.
        tp_idx = cmd.index("--target-halfwidth-pp")
        assert float(cmd[tp_idx + 1]) == 999.0, cmd


class TestBatchRawdataRootInjection:
    """2026-04-21: virtual console (port 8878) passes a distinct
    ``rawdata_root`` (``slot_designer/rawdata/``) into ``create_app``,
    separate from the real console's module-level ``RAWDATA_ROOT``
    (``./rawdata/``). ``BatchRunManager`` stores the injected value on
    ``self._rawdata_root`` — the batch-run cache-dir construction must
    read from there, not the module global, or every virtual batch-run
    targets the real console's rawdata/ tree and the delegate analyzer
    exits rc=1 with ``summary missing``.

    The existing tests in this file coincidentally co-locate the
    injected ``rawdata_root`` and the module-global ``RAWDATA_ROOT``
    on the same ``tmp_path / 'rawdata'`` so they pass either way —
    these tests split the two paths on purpose, then assert only the
    injected one flows into the analyzer cmd.
    """

    def test_analyzer_cmd_uses_injected_rawdata_root_not_global(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """The exact production bug: cache_dir_str = RAWDATA_ROOT / m /
        mode_n built with the module global. Fix is
        self._rawdata_root / m / mode_n.

        Setup splits the two paths:
          - app_factory injected ``tmp_rawdata`` = ``tmp_path/rawdata``
          - monkeypatched global ``RAWDATA_ROOT`` = ``tmp_path/wrong_rawdata``

        Only the injected path should appear in the --resume-from-cache
        argv; the global must never leak into the cmd.
        """
        import src.web_console.backend.app as app_mod
        c, _ = client
        injected_root = app_factory.rawdata_dir  # tmp_path / "rawdata"
        wrong_global = tmp_path / "wrong_rawdata"
        wrong_global.mkdir()
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", wrong_global)
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))

        r = c.post("/api/batch-run", json=_batch_payload("Mvirtual", 1, target=0.5))
        assert r.status_code == 200

        cmd = _wait_for_analyzer_cmd(app_factory.stub_popen)
        _release_stubs(app_factory.stub_popen)
        assert cmd is not None

        assert "--resume-from-cache" in cmd, cmd
        cache_arg = cmd[cmd.index("--resume-from-cache") + 1]
        # Must reference the INJECTED path, not the module global.
        assert str(injected_root) in cache_arg, (
            f"cache-dir arg doesn't use injected rawdata_root.\n"
            f"  injected (correct): {injected_root}\n"
            f"  global (wrong):     {wrong_global}\n"
            f"  cmd arg:            {cache_arg}"
        )
        assert str(wrong_global) not in cache_arg, (
            f"cache-dir arg leaks module-global RAWDATA_ROOT!\n"
            f"  cmd arg: {cache_arg}\n"
            f"  This is the virtual-console regression — code must use "
            f"self._rawdata_root from BatchRunManager, never the module "
            f"global. Check cache_dir_str construction around line 3302."
        )


class TestBatchAutoRefreshMd5:
    """Post-2026-04-21: POST /api/batch-run refreshes upstream md5
    before routing cache reuse. Fixes the "silently resume-from-cache
    on chunks that are actually historical once upstream updates"
    bug that would recur otherwise."""

    def test_default_triggers_md5_refresh(
        self, client, tmp_path, app_factory, monkeypatch,
    ):
        """Absent ``skip_md5_refresh``, the endpoint spawns a daemon
        thread that calls ``_do_refresh_machines_md5`` once per batch.

        Since be953cb moved the refresh to a fire-and-forget daemon
        thread (POST dropped 38s → 4s), the completed ok/error
        outcome isn't available in the sync response — only a
        ``{"ok": None, "pending": True}`` placeholder that tells the
        operator "yes, a refresh was triggered in the background".
        This test asserts both (a) the placeholder, and (b) that the
        thread actually fires the upstream fetch (polled via the
        stubbed ``_fetch_machine_config_md5``)."""
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "rawdata"
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))

        calls: list[tuple[str, bool]] = []
        monkeypatch.setattr(
            app_mod, "_fetch_machine_config_md5",
            lambda ep, timeout=30.0: (
                calls.append((ep, True))
                or {"M273": {"configSummaryMd5": "CUR", "codeSummaryMd5": "CUR"}}
            ),
        )
        # Server endpoint resolver — give it something non-empty so
        # the refresh helper proceeds past the "no endpoint" guard.
        monkeypatch.setattr(app_mod, "load_servers", lambda _path: {
            "servers": [{"id": "dev", "endpoint": "http://fake-upstream"}],
        })
        # Silence server snapshot write — helper calls it inside the
        # refresh. Snapshot is unrelated to this test.
        monkeypatch.setattr(app_mod, "_save_server_snapshot", lambda *a, **kw: None)

        r = c.post("/api/batch-run", json=_batch_payload("M273", 1, target=0.0))
        assert r.status_code == 200
        body = r.json()
        assert body.get("md5_refresh") == {"ok": None, "pending": True}, (
            "response should include an async placeholder when refresh is triggered"
        )

        # Wait for the daemon thread to actually fire the upstream
        # fetch. Proves the refresh was triggered in practice, not
        # just claimed in the response placeholder.
        deadline = time.time() + 5.0
        while time.time() < deadline and not calls:
            time.sleep(0.05)
        assert len(calls) == 1, "refresh fetch should fire exactly once per batch"
        # Let any stubbed analyzer subprocesses exit cleanly.
        _release_stubs(app_factory.stub_popen)

    def test_skip_md5_refresh_honored(
        self, client, tmp_path, app_factory, monkeypatch,
    ):
        """Setting ``skip_md5_refresh=True`` in the request body bypasses
        the refresh call — useful when operator knows local is current
        or wants to save the upstream round-trip."""
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "rawdata"
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))

        calls: list[tuple[str, bool]] = []
        monkeypatch.setattr(
            app_mod, "_fetch_machine_config_md5",
            lambda ep, timeout=30.0: (calls.append((ep, True)) or {}),
        )

        payload = _batch_payload("M273", 1, target=0.0)
        payload["skip_md5_refresh"] = True
        r = c.post("/api/batch-run", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert "md5_refresh" not in body, "response should omit md5_refresh when skipped"
        assert calls == [], "refresh fetch should NOT fire when skipped"
        _release_stubs(app_factory.stub_popen)

    def test_upstream_failure_does_not_block_batch(
        self, client, tmp_path, app_factory, monkeypatch,
    ):
        """Upstream unreachable → the batch still starts.

        Post-be953cb the refresh lives on a daemon thread, so the
        failure is swallowed inside the thread (by
        ``raise_on_error=False`` in ``_do_refresh_machines_md5``) and
        isn't observable in the sync response. What IS observable:
        (a) 200 OK and a batch_id (batch dispatched), (b) the
        pending placeholder (refresh was triggered), and (c) the
        upstream fetch was actually attempted by the background
        thread. Operators see stale-md5 risk surface on the next
        batch's classifier rather than via this response."""
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "rawdata"
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))

        calls: list[str] = []
        monkeypatch.setattr(
            app_mod, "_fetch_machine_config_md5",
            lambda ep, timeout=30.0: (calls.append(ep) or None),
        )
        monkeypatch.setattr(app_mod, "load_servers", lambda _path: {
            "servers": [{"id": "dev", "endpoint": "http://fake-upstream"}],
        })

        r = c.post("/api/batch-run", json=_batch_payload("M273", 1, target=0.0))
        assert r.status_code == 200, "upstream failure should NOT fail the batch"
        body = r.json()
        # Batch should still have kicked off (batch_id + items present).
        assert "batch_id" in body
        # Placeholder still set — operator knows refresh was fired
        # even though the outcome (failure) isn't surfaced in the
        # sync response.
        assert body.get("md5_refresh") == {"ok": None, "pending": True}

        # Wait for the background thread to actually attempt the
        # (failing) upstream fetch — proves the failure path WAS
        # exercised and swallowed, not that refresh was skipped.
        deadline = time.time() + 5.0
        while time.time() < deadline and not calls:
            time.sleep(0.05)
        assert len(calls) == 1, "background refresh should attempt the upstream fetch"
        _release_stubs(app_factory.stub_popen)

    def test_refresh_never_clobbers_real_md5_with_empty(
        self, tmp_path, monkeypatch,
    ):
        """REGRESSION 2026-04-21: auto-refresh on page load used to
        silently overwrite existing md5 values with "" when upstream
        returned a partial record. Dev machines.json lost all real
        md5 values the first time the refresh fired. Fix: only merge
        when upstream's md5 pair is non-empty."""
        import src.web_console.backend.app as app_mod

        # Seed machines.json with real md5 values
        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({
            "machines": [
                {"machine": "M1", "modes": [1], "logicClassNames": ["Foo"],
                 "configSummaryMd5": "REAL_CFG_1",
                 "codeSummaryMd5": "REAL_CODE_1"},
                {"machine": "M14", "modes": [1], "logicClassNames": ["Bar"],
                 "configSummaryMd5": "REAL_CFG_14",
                 "codeSummaryMd5": "REAL_CODE_14"},
            ]
        }), encoding="utf-8")

        # Fake upstream returns PARTIAL data: M1 gets empty md5, M14 gets
        # a new md5. Existing M1 real md5 must survive; M14 should update.
        monkeypatch.setattr(
            app_mod, "_fetch_machine_config_md5",
            lambda ep, timeout=30.0: {
                "M1": {"configSummaryMd5": "", "codeSummaryMd5": ""},
                "M14": {"configSummaryMd5": "NEW_CFG_14", "codeSummaryMd5": "NEW_CODE_14"},
            },
        )
        monkeypatch.setattr(app_mod, "load_servers", lambda _path: {
            "servers": [{"id": "dev", "endpoint": "http://fake-upstream"}],
        })
        monkeypatch.setattr(app_mod, "_save_server_snapshot", lambda *a, **kw: None)

        # Spin up just enough of create_app's closure to call the helper.
        # Easiest: create a full app (state_dir + reports + etc tmp).
        from src.web_console.backend.app import create_app
        from fastapi.testclient import TestClient
        app = create_app(
            state_dir=tmp_path / "state",
            reports_root=tmp_path / "reports",
            cache_root=tmp_path / "cache",
            machines_config=mc,
            rawdata_root=tmp_path / "rawdata",
        )
        with TestClient(app) as c:
            r = c.post("/api/machines/refresh-md5", json={"server_id": "dev"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["machines_fetched"] == 2
            assert body["machines_updated"] == 1  # only M14
            assert body["skipped_empty_upstream"] == 1  # M1 was empty
            # REGRESSION 2026-04-21: also return the *names* so the
            # activity log / alerts can surface them. Before this,
            # operators saw "N/M changed" and had no way to tell if
            # their working machine was in the N — dev fleet churn
            # caused false "my M1 drifted" panics after restart.
            assert body["updated_machines"] == ["M14"]

        # Reload file and confirm M1 still has REAL md5, M14 got NEW.
        data = json.loads(mc.read_text(encoding="utf-8"))
        by_name = {m["machine"]: m for m in data["machines"]}
        assert by_name["M1"]["configSummaryMd5"] == "REAL_CFG_1", (
            "empty upstream md5 should NOT have wiped the existing real md5"
        )
        assert by_name["M1"]["codeSummaryMd5"] == "REAL_CODE_1"
        assert by_name["M14"]["configSummaryMd5"] == "NEW_CFG_14"
        assert by_name["M14"]["codeSummaryMd5"] == "NEW_CODE_14"

    def test_refresh_updated_machines_empty_when_nothing_changed(
        self, tmp_path, monkeypatch,
    ):
        """2026-04-21: when upstream md5 matches what we already have,
        updated_machines must be [] (not missing, not null). Frontend
        reads Array.isArray(r.updated_machines) and expects a list.

        This is the scenario that triggered the bug fix: operator
        just sampled M1, restarted console, auto-refresh fires —
        nothing should appear in the activity log as "changed"."""
        import src.web_console.backend.app as app_mod

        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({
            "machines": [
                {"machine": "M1", "modes": [1], "logicClassNames": ["Foo"],
                 "configSummaryMd5": "SAME_CFG",
                 "codeSummaryMd5": "SAME_CODE"},
            ]
        }), encoding="utf-8")

        # Upstream returns the exact md5 we already have → no update.
        monkeypatch.setattr(
            app_mod, "_fetch_machine_config_md5",
            lambda ep, timeout=30.0: {
                "M1": {"configSummaryMd5": "SAME_CFG", "codeSummaryMd5": "SAME_CODE"},
            },
        )
        monkeypatch.setattr(app_mod, "load_servers", lambda _path: {
            "servers": [{"id": "dev", "endpoint": "http://fake-upstream"}],
        })
        monkeypatch.setattr(app_mod, "_save_server_snapshot", lambda *a, **kw: None)

        from src.web_console.backend.app import create_app
        from fastapi.testclient import TestClient
        app = create_app(
            state_dir=tmp_path / "state",
            reports_root=tmp_path / "reports",
            cache_root=tmp_path / "cache",
            machines_config=mc,
            rawdata_root=tmp_path / "rawdata",
        )
        with TestClient(app) as c:
            r = c.post("/api/machines/refresh-md5", json={"server_id": "dev"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["machines_updated"] == 0
            assert body["updated_machines"] == [], (
                "no drift → empty list, not None / missing"
            )

    def test_refresh_updated_machines_sorted(
        self, tmp_path, monkeypatch,
    ):
        """2026-04-21: stable sort so activity log renders
        deterministically. Upstream dict order is not guaranteed."""
        import src.web_console.backend.app as app_mod

        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": []}), encoding="utf-8")

        # Return machines in reverse alpha order; code must sort.
        monkeypatch.setattr(
            app_mod, "_fetch_machine_config_md5",
            lambda ep, timeout=30.0: {
                "M272": {"configSummaryMd5": "C272", "codeSummaryMd5": "K272"},
                "M14": {"configSummaryMd5": "C14", "codeSummaryMd5": "K14"},
                "M1": {"configSummaryMd5": "C1", "codeSummaryMd5": "K1"},
            },
        )
        monkeypatch.setattr(app_mod, "load_servers", lambda _path: {
            "servers": [{"id": "dev", "endpoint": "http://fake-upstream"}],
        })
        monkeypatch.setattr(app_mod, "_save_server_snapshot", lambda *a, **kw: None)

        from src.web_console.backend.app import create_app
        from fastapi.testclient import TestClient
        app = create_app(
            state_dir=tmp_path / "state",
            reports_root=tmp_path / "reports",
            cache_root=tmp_path / "cache",
            machines_config=mc,
            rawdata_root=tmp_path / "rawdata",
        )
        with TestClient(app) as c:
            r = c.post("/api/machines/refresh-md5", json={"server_id": "dev"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["machines_updated"] == 3
            assert body["updated_machines"] == ["M1", "M14", "M272"]
