"""Client upload of the per-machine local MachineConfig override (2026-06-17).

The old flow had the operator drop machineconfig/<underlying>Cfg.txt on the
(then-local) box by hand; sampling read it via use_local_machine_config and
sent it as the upstream MachineConfig field, versioning rawdata under
localcfg_<hash>. With the service now remote, the operator can't place the
file — so POST /api/machines/{m}/config writes it from a CLIENT upload after
light validation, and DELETE clears it. Everything downstream is unchanged
(cfg-availability / use_local_machine_config / localcfg md5 / report_engine).

INJECT-BUG (per feedback_enumerate_safety_paths):
  * machine-match: drop the `if cfg_key not in doc` check in upload_machine_config
    -> test_rejects_machine_mismatch RED. Revert -> GREEN.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.web_console.backend.app as app_mod


def _cfg(machine: str) -> dict:
    """A minimal valid MachineConfig: the machine-matching <M>Cfg section +
    the core BetCfg / RTPCfg sections the validator requires."""
    return {
        f"{machine}Cfg": {"reelStrips": [[0, 1, 2]], "skin": 1},
        "BetCfg": {"betList": [1, 2, 5]},
        "RTPCfg": {"target": 95.0},
    }


@pytest.fixture
def cfg_client(client, monkeypatch, tmp_path):
    """app TestClient with MACHINECONFIG_DIR pointed at a tmp dir so uploads
    never touch the real machineconfig/ tree."""
    c, _app = client
    cfg_dir = tmp_path / "machineconfig"
    cfg_dir.mkdir()
    monkeypatch.setattr(app_mod, "MACHINECONFIG_DIR", cfg_dir)
    return c, cfg_dir


class TestUploadMachineConfig:
    def test_upload_valid_writes_file_and_flips_availability(self, cfg_client):
        c, cfg_dir = cfg_client
        # Before: not available.
        assert c.get("/api/machines/M283/cfg-availability").json()["available"] is False
        # Upload.
        resp = c.post("/api/machines/M283/config", json={"content": _cfg("M283")})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["underlying"] == "M283"
        assert body["filename"] == "M283Cfg.txt"
        assert body["bytes"] > 0
        # File on disk + parses + carries the machine section.
        written = cfg_dir / "M283Cfg.txt"
        assert written.is_file()
        assert "M283Cfg" in json.loads(written.read_text(encoding="utf-8"))
        # After: available (the existing read path sees it).
        avail = c.get("/api/machines/M283/cfg-availability").json()
        assert avail["available"] is True
        assert avail["filename"] == "M283Cfg.txt"

    def test_upload_accepts_json_string_content(self, cfg_client):
        c, _ = cfg_client
        resp = c.post("/api/machines/M283/config",
                      json={"content": json.dumps(_cfg("M283"))})
        assert resp.status_code == 200, resp.text

    def test_rejects_machine_mismatch(self, cfg_client):
        """An M15 config uploaded for M283 has no 'M283Cfg' section -> 400."""
        c, cfg_dir = cfg_client
        resp = c.post("/api/machines/M283/config", json={"content": _cfg("M15")})
        assert resp.status_code == 400
        assert "M283Cfg" in resp.text
        assert not (cfg_dir / "M283Cfg.txt").exists()  # nothing written on reject

    def test_rejects_invalid_json(self, cfg_client):
        c, _ = cfg_client
        resp = c.post("/api/machines/M283/config", json={"content": "{not json"})
        assert resp.status_code == 400
        assert "valid JSON" in resp.text

    def test_rejects_missing_core_sections(self, cfg_client):
        c, _ = cfg_client
        resp = c.post("/api/machines/M283/config",
                      json={"content": {"M283Cfg": {"x": 1}}})  # no BetCfg/RTPCfg
        assert resp.status_code == 400
        assert "BetCfg" in resp.text or "RTPCfg" in resp.text

    def test_upload_replaces_existing(self, cfg_client):
        c, cfg_dir = cfg_client
        c.post("/api/machines/M283/config", json={"content": _cfg("M283")})
        cfg2 = _cfg("M283"); cfg2["RTPCfg"]["target"] = 88.0
        resp = c.post("/api/machines/M283/config", json={"content": cfg2})
        assert resp.status_code == 200
        on_disk = json.loads((cfg_dir / "M283Cfg.txt").read_text(encoding="utf-8"))
        assert on_disk["RTPCfg"]["target"] == 88.0  # replaced, not appended

    def test_delete_clears(self, cfg_client):
        c, cfg_dir = cfg_client
        c.post("/api/machines/M283/config", json={"content": _cfg("M283")})
        assert (cfg_dir / "M283Cfg.txt").exists()
        resp = c.delete("/api/machines/M283/config")
        assert resp.status_code == 200
        assert resp.json()["cleared"] is True
        assert not (cfg_dir / "M283Cfg.txt").exists()
        assert c.get("/api/machines/M283/cfg-availability").json()["available"] is False

    def test_delete_noop_when_absent(self, cfg_client):
        c, _ = cfg_client
        resp = c.delete("/api/machines/M283/config")
        assert resp.status_code == 200
        assert resp.json()["cleared"] is False
