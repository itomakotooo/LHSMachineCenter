"""Tests for batch-run server selection.

Before 2026-04-24, ``BatchRunRequest`` had no ``server_id`` field —
batch-run ALWAYS used the hardcoded ``SLOT_SPIN_ENDPOINT`` constant.
Rearranging ``configs/servers.json`` (e.g. flipping ``default_server``
or ``active`` via the 服务器管理 UI) changed nothing for the sampling
hot path. Operators switching from LAN to home / VPN had to edit the
constant + restart the backend.

Fix: ``BatchRunRequest.server_id`` accepts a caller-specified id, and
when empty the backend resolves from ``servers.json`` (default_server
→ first active-with-endpoint). The resolved id flows through
RunCreateRequest → RunManager → analyzer's ``--endpoint-url`` arg.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def _write_servers(tmp_path: Path, servers_json: dict) -> Path:
    p = tmp_path / "servers.json"
    p.write_text(
        json.dumps(servers_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return p


def _batch_payload(**kw):
    base = {
        "items": [{"machine": "M14", "mode": 1, "chunk_spin_times": 1000}],
        "chunk_robot_count": 8, "batch_concurrency": 8,
        "concurrency": 1, "max_chunks": 5, "timeout": 60.0,
        "target_halfwidth_pp": 0.5,
    }
    base.update(kw)
    return base


class TestResolveActiveServerId:
    def test_prefers_default_server_when_endpoint_set(self, tmp_path):
        import src.web_console.backend.app as app_mod
        p = _write_servers(tmp_path, {
            "servers": [
                {"id": "dev", "name": "内网", "endpoint": "http://1.1.1.1", "active": True},
                {"id": "prod", "name": "外网", "endpoint": "http://2.2.2.2", "active": True},
            ],
            "default_server": "dev",
        })
        assert app_mod._resolve_active_server_id(p) == "dev"

    def test_falls_through_when_default_has_empty_endpoint(self, tmp_path):
        import src.web_console.backend.app as app_mod
        p = _write_servers(tmp_path, {
            "servers": [
                {"id": "dev", "endpoint": "", "active": True},
                {"id": "prod", "endpoint": "http://2.2.2.2", "active": True},
            ],
            "default_server": "dev",
        })
        # Default has no endpoint → skip to first active-with-endpoint.
        assert app_mod._resolve_active_server_id(p) == "prod"

    def test_returns_empty_when_nothing_routable(self, tmp_path):
        import src.web_console.backend.app as app_mod
        p = _write_servers(tmp_path, {
            "servers": [
                {"id": "dev", "endpoint": "", "active": False},
                {"id": "prod", "endpoint": "", "active": False},
            ],
            "default_server": "dev",
        })
        assert app_mod._resolve_active_server_id(p) == ""

    def test_skips_inactive_entries_with_endpoint(self, tmp_path):
        import src.web_console.backend.app as app_mod
        p = _write_servers(tmp_path, {
            "servers": [
                {"id": "dev", "endpoint": "http://1.1.1.1", "active": False},
                {"id": "prod", "endpoint": "http://2.2.2.2", "active": True},
            ],
            "default_server": "",  # no default
        })
        assert app_mod._resolve_active_server_id(p) == "prod"


class TestBatchRunHonorsServerResolution:
    def test_default_server_prod_routes_analyzer_to_external(
        self, client, app_factory, tmp_path, monkeypatch,
    ):
        """servers.json has ``default_server=prod`` → batch-run
        spawned analyzer cmd carries ``--endpoint-url
        http://116.232.103.19:10288/MachineTest/MultiRobotTestSpinVariant``."""
        import src.web_console.backend.app as app_mod
        p = _write_servers(tmp_path, {
            "servers": [
                {
                    "id": "dev", "active": True,
                    "endpoint": "http://192.168.10.21:15060",
                },
                {
                    "id": "prod", "active": True,
                    "endpoint": "http://116.232.103.19:10288",
                },
            ],
            "default_server": "prod",
        })
        monkeypatch.setattr(app_mod, "SERVERS_CONFIG", p)

        c, _app = client
        resp = c.post("/api/batch-run", json=_batch_payload())
        assert resp.status_code == 200, resp.text

        deadline = time.time() + 3.0
        while time.time() < deadline:
            if app_factory.stub_popen.cmds:
                break
            time.sleep(0.05)

        assert app_factory.stub_popen.cmds
        cmd = app_factory.stub_popen.cmds[-1]
        assert "--endpoint-url" in cmd, f"no server routing; cmd={cmd}"
        idx = cmd.index("--endpoint-url")
        assert cmd[idx + 1] == (
            "http://116.232.103.19:10288/MachineTest/MultiRobotTestSpinVariant"
        )

    def test_explicit_server_id_wins_over_default(
        self, client, app_factory, tmp_path, monkeypatch,
    ):
        """Caller-specified ``server_id`` beats the resolver — useful
        for scripted one-off comparison runs against a non-default
        endpoint without mutating servers.json."""
        import src.web_console.backend.app as app_mod
        p = _write_servers(tmp_path, {
            "servers": [
                {"id": "dev", "active": True, "endpoint": "http://192.168.10.21:15060"},
                {"id": "prod", "active": True, "endpoint": "http://116.232.103.19:10288"},
            ],
            "default_server": "prod",  # resolver would pick this
        })
        monkeypatch.setattr(app_mod, "SERVERS_CONFIG", p)

        c, _app = client
        resp = c.post("/api/batch-run", json=_batch_payload(server_id="dev"))
        assert resp.status_code == 200, resp.text

        deadline = time.time() + 3.0
        while time.time() < deadline:
            if app_factory.stub_popen.cmds:
                break
            time.sleep(0.05)

        cmd = app_factory.stub_popen.cmds[-1]
        idx = cmd.index("--endpoint-url")
        # Caller-specified "dev" won, even though default is "prod".
        assert cmd[idx + 1].startswith("http://192.168.10.21:15060/")

    def test_no_routable_server_falls_through_silently(
        self, client, app_factory, tmp_path, monkeypatch,
    ):
        """When servers.json is empty / all inactive, resolver returns
        "" and RunManager skips ``--endpoint-url`` — analyzer then
        uses its own DEFAULT_ENDPOINT_URL constant. Back-compat path
        for test / dev setups without servers.json."""
        import src.web_console.backend.app as app_mod
        p = _write_servers(tmp_path, {
            "servers": [], "default_server": "",
        })
        monkeypatch.setattr(app_mod, "SERVERS_CONFIG", p)

        c, _app = client
        resp = c.post("/api/batch-run", json=_batch_payload())
        assert resp.status_code == 200, resp.text

        deadline = time.time() + 3.0
        while time.time() < deadline:
            if app_factory.stub_popen.cmds:
                break
            time.sleep(0.05)

        cmd = app_factory.stub_popen.cmds[-1]
        # No --endpoint-url means analyzer defaults apply.
        assert "--endpoint-url" not in cmd


class TestAutotuneHonorsServerResolution:
    """Autotune probes (``_post_slot_spin``) must hit the same
    endpoint batch-run does — i.e. resolve via servers.json
    ``default_server`` / first-active rather than the hardcoded
    SLOT_SPIN_ENDPOINT constant.

    User report 2026-04-25: 调参按钮在外网（prod default_server）
    下点了无效 — 因为 ``_post_slot_spin`` 一直 hard-pin 到内网常量。
    Lock: a single regression test that monkey-patches the urllib
    layer + asserts the URL matches the resolver output."""

    def test_post_slot_spin_routes_to_default_server(
        self, tmp_path, monkeypatch,
    ):
        import src.web_console.backend.app as app_mod

        p = _write_servers(tmp_path, {
            "servers": [
                {"id": "dev", "active": True, "endpoint": "http://192.168.10.21:15060"},
                {"id": "prod", "active": True, "endpoint": "http://116.232.103.19:10288"},
            ],
            "default_server": "prod",
        })
        monkeypatch.setattr(app_mod, "SERVERS_CONFIG", p)

        captured_urls: list[str] = []

        class _FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self):
                return b'[]'  # empty list response — _run_probe_request handles it

        def fake_urlopen(req, timeout=None):
            captured_urls.append(req.full_url)
            return _FakeResponse()

        monkeypatch.setattr(
            "src.web_console.backend.app.urllib.request.urlopen", fake_urlopen,
        )

        # Direct probe — analyzer-internal call path that the autotune
        # endpoint uses on every candidate.
        app_mod._post_slot_spin({"x": 1}, timeout=1.0)
        app_mod._post_slot_spin({"x": 2}, timeout=1.0)

        assert len(captured_urls) == 2
        # Both calls must go to prod (the default_server endpoint),
        # NOT the SLOT_SPIN_ENDPOINT constant.
        for url in captured_urls:
            assert url.startswith("http://116.232.103.19:10288/"), (
                f"autotune routed to wrong endpoint: {url}"
            )
            assert "192.168.10.21" not in url

    def test_post_slot_spin_falls_through_when_no_routable_server(
        self, tmp_path, monkeypatch,
    ):
        """Empty / inactive servers.json → resolver returns "" →
        ``get_server_endpoint("")`` falls back to SLOT_SPIN_ENDPOINT
        constant. Back-compat for test / dev setups."""
        import src.web_console.backend.app as app_mod

        p = _write_servers(tmp_path, {
            "servers": [], "default_server": "",
        })
        monkeypatch.setattr(app_mod, "SERVERS_CONFIG", p)

        captured: list[str] = []

        class _FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'[]'

        def fake_urlopen(req, timeout=None):
            captured.append(req.full_url)
            return _FakeResponse()

        monkeypatch.setattr(
            "src.web_console.backend.app.urllib.request.urlopen", fake_urlopen,
        )

        app_mod._post_slot_spin({}, timeout=1.0)
        assert captured[0] == app_mod.SLOT_SPIN_ENDPOINT


class TestSetDefaultServerEndpoint:
    """PUT /api/servers/{id}/set-default — UI-driven switch for the
    batch-run resolver's ``default_server`` priority. Without this,
    operators flipping between LAN and VPN had to hand-edit
    servers.json + restart."""

    def test_set_default_updates_config(self, client, tmp_path, monkeypatch):
        import src.web_console.backend.app as app_mod
        p = _write_servers(tmp_path, {
            "servers": [
                {"id": "dev", "active": True, "endpoint": "http://a"},
                {"id": "prod", "active": True, "endpoint": "http://b"},
            ],
            "default_server": "dev",
        })
        monkeypatch.setattr(app_mod, "SERVERS_CONFIG", p)

        c, _app = client
        resp = c.put("/api/servers/prod/set-default")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True, "default_server": "prod"}

        # Persisted to file + reflected in GET /api/servers.
        cfg = json.loads(p.read_text(encoding="utf-8"))
        assert cfg["default_server"] == "prod"

    def test_set_default_404_for_unknown_id(
        self, client, tmp_path, monkeypatch,
    ):
        import src.web_console.backend.app as app_mod
        p = _write_servers(tmp_path, {
            "servers": [{"id": "dev", "active": True, "endpoint": "http://a"}],
            "default_server": "dev",
        })
        monkeypatch.setattr(app_mod, "SERVERS_CONFIG", p)

        c, _app = client
        resp = c.put("/api/servers/ghost/set-default")
        assert resp.status_code == 404

    def test_set_default_400_for_empty_endpoint(
        self, client, tmp_path, monkeypatch,
    ):
        """Setting a no-endpoint entry as default would silently
        make the resolver fall through, masking operator intent."""
        import src.web_console.backend.app as app_mod
        p = _write_servers(tmp_path, {
            "servers": [
                {"id": "dev", "active": True, "endpoint": "http://a"},
                {"id": "test", "active": False, "endpoint": ""},
            ],
            "default_server": "dev",
        })
        monkeypatch.setattr(app_mod, "SERVERS_CONFIG", p)

        c, _app = client
        resp = c.put("/api/servers/test/set-default")
        assert resp.status_code == 400
        assert "endpoint" in resp.json()["detail"]
        # Config untouched.
        cfg = json.loads(p.read_text(encoding="utf-8"))
        assert cfg["default_server"] == "dev"

    def test_set_default_then_batch_run_routes_accordingly(
        self, client, app_factory, tmp_path, monkeypatch,
    ):
        """End-to-end: flip default via PUT → next batch-run's
        analyzer cmd uses the new endpoint without restart."""
        import src.web_console.backend.app as app_mod
        p = _write_servers(tmp_path, {
            "servers": [
                {"id": "dev", "active": True, "endpoint": "http://192.168.10.21:15060"},
                {"id": "prod", "active": True, "endpoint": "http://116.232.103.19:10288"},
            ],
            "default_server": "dev",
        })
        monkeypatch.setattr(app_mod, "SERVERS_CONFIG", p)

        c, _app = client
        # Flip default to prod via the new endpoint.
        flip = c.put("/api/servers/prod/set-default")
        assert flip.status_code == 200

        # Now kick off a batch-run — resolver should pick prod.
        resp = c.post("/api/batch-run", json=_batch_payload())
        assert resp.status_code == 200

        deadline = time.time() + 3.0
        while time.time() < deadline:
            if app_factory.stub_popen.cmds:
                break
            time.sleep(0.05)

        cmd = app_factory.stub_popen.cmds[-1]
        idx = cmd.index("--endpoint-url")
        assert cmd[idx + 1].startswith("http://116.232.103.19:10288/")
