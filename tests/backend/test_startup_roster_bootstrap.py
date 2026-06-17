"""Startup roster self-heal (2026-06-17).

machines.json is a gitignored, runtime-fetched file (the downloaded upstream
roster). load_machines() falls back to an EMPTY fleet when it's missing, so a
fresh deploy / wiped-or-rebuilt checkout shows an empty machine list until
someone manually hits refresh-md5 or starts a batch. create_app() now spawns a
`roster-bootstrap` daemon that, IFF machines.json is empty/missing, fetches the
roster once from the active upstream — so the operator's deploy flow stays just
"git pull + restart service" and the list comes back on its own.

These tests drive the actual create_app startup with the upstream fetch
(`_fetch_machine_config_md5`) spied, and assert the bootstrap fires only when
the roster is empty and only when not disabled.

INJECT-BUG recipes (per feedback_enumerate_safety_paths):
  * empty-case: in app.py _bootstrap_roster_if_empty change `if existing > 0:`
    to `if existing >= 0:` (always returns) -> test_bootstraps_when_empty RED.
  * skip-env: delete the `if os.environ.get("SLOT_SKIP_ROSTER_BOOTSTRAP"):
    return` guard -> test_skip_env_disables_bootstrap RED.
  Revert -> GREEN.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.web_console.backend.app as app_mod
from src.web_console.backend.app import create_app


def _write_servers(tmp_path: Path) -> Path:
    p = tmp_path / "servers.json"
    p.write_text(
        json.dumps({
            "servers": [
                {"id": "dev", "name": "dev", "endpoint": "http://fake-upstream:1",
                 "active": True},
            ],
            "default_server": "dev",
        }),
        encoding="utf-8",
    )
    return p


def _make_app(tmp_path: Path, machines_json: str):
    mc = tmp_path / "machines.json"
    mc.write_text(machines_json, encoding="utf-8")
    state_dir = tmp_path / "state"
    (state_dir / "progress").mkdir(parents=True)
    reports = tmp_path / "reports"; reports.mkdir()
    rawdata = tmp_path / "rawdata"; rawdata.mkdir()
    app = create_app(
        state_dir=state_dir,
        reports_root=reports,
        machines_config=mc,
        rawdata_root=rawdata,
    )
    return app, mc


class TestStartupRosterBootstrap:
    def _install_upstream_spy(self, monkeypatch, tmp_path: Path) -> list:
        """Spy the module-level upstream fetch + point SERVERS_CONFIG at a tmp
        servers.json with an active endpoint, so _do_refresh_machines_md5
        reaches the (spied) fetch. Returns the list of endpoints fetched."""
        calls: list[str] = []

        def _spy(endpoint, timeout=30.0):
            calls.append(endpoint)
            return {}  # valid non-None upstream payload (empty roster is fine)

        monkeypatch.setattr(app_mod, "_fetch_machine_config_md5", _spy)
        monkeypatch.setattr(app_mod, "SERVERS_CONFIG", _write_servers(tmp_path))
        return calls

    def test_bootstraps_when_roster_empty(self, tmp_path, monkeypatch):
        """machines.json == {"machines": []} -> startup fetches the roster."""
        monkeypatch.delenv("SLOT_SKIP_ROSTER_BOOTSTRAP", raising=False)  # enable
        calls = self._install_upstream_spy(monkeypatch, tmp_path)
        app, _mc = _make_app(tmp_path, '{"machines": []}')
        with TestClient(app):
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and not calls:
                time.sleep(0.05)
        assert calls, (
            "startup must fetch the roster from the active upstream when "
            "machines.json is empty (the deploy self-heal)"
        )

    def test_does_not_bootstrap_when_roster_present(self, tmp_path, monkeypatch):
        """machines.json already has machines -> NO upstream fetch (never
        override an existing roster / hammer upstream on every restart)."""
        monkeypatch.delenv("SLOT_SKIP_ROSTER_BOOTSTRAP", raising=False)
        calls = self._install_upstream_spy(monkeypatch, tmp_path)
        app, _mc = _make_app(tmp_path, '{"machines": [{"machine": "M14"}]}')
        with TestClient(app):
            time.sleep(1.0)  # ample time for the daemon to (not) fire
        assert not calls, (
            "startup must NOT fetch when machines.json already has a roster; "
            f"got fetch(es): {calls}"
        )

    def test_skip_env_disables_bootstrap(self, tmp_path, monkeypatch):
        """SLOT_SKIP_ROSTER_BOOTSTRAP=1 disables the fetch even when empty
        (the guard backend tests rely on so they never hit the network)."""
        monkeypatch.setenv("SLOT_SKIP_ROSTER_BOOTSTRAP", "1")
        calls = self._install_upstream_spy(monkeypatch, tmp_path)
        app, _mc = _make_app(tmp_path, '{"machines": []}')
        with TestClient(app):
            time.sleep(1.0)
        assert not calls, (
            "SLOT_SKIP_ROSTER_BOOTSTRAP=1 must disable the startup roster fetch; "
            f"got fetch(es): {calls}"
        )
