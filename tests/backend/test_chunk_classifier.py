"""Tests for Commit 2 backend:

* ``_classify_chunks()`` tier logic (kept / deletable / historical)
* ``delete_rawdata()`` safe default vs ``force=True``
* ``/api/rawdata/{machine}`` response shape (classification + version groups)
* ``/api/settings`` GET/PUT round-trip + clamping
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _write_chunk(
    dir_: Path,
    idx: int,
    *,
    config_md5: str,
    code_md5: str,
    spin_times: int = 5_000,
    mtime: float | None = None,
) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / f"chunk_{idx:04d}.json"
    p.write_text(json.dumps({
        "_cache_version": 3,
        "_machine": "M14",
        "_mode": 1,
        "_bet": 1000,
        "_spin_times": spin_times,
        "_robot_count": 1,
        "_chunk_index": idx,
        "_saved_at": "2026-04-01T00:00:00Z",
        "_config_md5": config_md5,
        "_code_md5": code_md5,
        "response": [],
    }), encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


class TestClassifyChunks:
    def test_empty_mode_dir_returns_empty_groups(self, tmp_path):
        from src.web_console.backend.app import _classify_chunks
        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": []}), encoding="utf-8")
        rd_root = tmp_path / "rawdata"
        rd_root.mkdir()
        out = _classify_chunks("M14", 1, rd_root, mc, 100_000)
        assert out["kept"] == []
        assert out["deletable"] == []
        assert out["historical"] == []

    def test_all_chunks_kept_below_retention(self, tmp_path):
        """5 chunks × 10k spins = 50k < 100k retention → all kept."""
        from src.web_console.backend.app import _classify_chunks
        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "cfg1", "codeSummaryMd5": "code1",
        }]}), encoding="utf-8")
        rd_root = tmp_path / "rawdata"
        for i in range(1, 6):
            _write_chunk(rd_root / "M14" / "mode_1", i,
                         config_md5="cfg1", code_md5="code1",
                         spin_times=10_000)
        out = _classify_chunks("M14", 1, rd_root, mc, 100_000)
        assert len(out["kept"]) == 5
        assert out["deletable"] == []
        assert out["historical"] == []
        assert out["kept_spins"] == 50_000

    def test_split_at_retention_boundary(self, tmp_path):
        """15 chunks × 10k = 150k. Retention 100k → first 10 kept,
        last 5 deletable. (Chunk that crosses threshold is kept
        inclusive — that's chunk 10 which brings cumulative to 100k
        exactly.)"""
        from src.web_console.backend.app import _classify_chunks
        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "cfg1", "codeSummaryMd5": "code1",
        }]}), encoding="utf-8")
        rd_root = tmp_path / "rawdata"
        for i in range(1, 16):
            _write_chunk(rd_root / "M14" / "mode_1", i,
                         config_md5="cfg1", code_md5="code1",
                         spin_times=10_000)
        out = _classify_chunks("M14", 1, rd_root, mc, 100_000)
        assert len(out["kept"]) == 10
        assert len(out["deletable"]) == 5
        assert out["kept_spins"] == 100_000
        assert out["deletable_spins"] == 50_000

    def test_historical_md5_separated_regardless_of_quota(self, tmp_path):
        """Historical-md5 chunks bypass the kept quota entirely — the
        retention baseline only protects current-md5 chunks (user
        2026-04-21: 保底 only applies to 当前版本)."""
        from src.web_console.backend.app import _classify_chunks
        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "NEW", "codeSummaryMd5": "NEW",
        }]}), encoding="utf-8")
        rd_root = tmp_path / "rawdata"
        mode_dir = rd_root / "M14" / "mode_1"
        # 5 current chunks (all kept) + 3 historical-md5 chunks
        for i in range(1, 6):
            _write_chunk(mode_dir, i, config_md5="NEW", code_md5="NEW",
                         spin_times=10_000)
        for i in range(10, 13):
            _write_chunk(mode_dir, i, config_md5="OLD", code_md5="OLD",
                         spin_times=10_000)
        out = _classify_chunks("M14", 1, rd_root, mc, 100_000)
        assert len(out["kept"]) == 5
        assert out["deletable"] == []
        assert len(out["historical"]) == 3
        assert out["historical_spins"] == 30_000

    def test_code_md5_drift_alone_flips_cell_to_historical(self, tmp_path):
        """Upstream returns TWO md5s (configSummaryMd5 + codeSummaryMd5).
        User 2026-04-21: EITHER half flipping counts as a rawdata
        version change. Previously the user pointed out this might
        be mis-handled — verify chunks whose config_md5 matches
        current but code_md5 drifted land in `historical` (not kept)."""
        from src.web_console.backend.app import _classify_chunks
        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "CFG_CUR",
            "codeSummaryMd5": "CODE_CUR",  # code flipped: old chunks have CODE_OLD
        }]}), encoding="utf-8")
        rd_root = tmp_path / "rawdata"
        mode_dir = rd_root / "M14" / "mode_1"
        # 3 chunks with SAME config md5 but OLD code md5
        for i in range(1, 4):
            _write_chunk(mode_dir, i, config_md5="CFG_CUR", code_md5="CODE_OLD",
                         spin_times=10_000)
        # 2 chunks fully current (both md5s match)
        for i in range(10, 12):
            _write_chunk(mode_dir, i, config_md5="CFG_CUR", code_md5="CODE_CUR",
                         spin_times=10_000)
        out = _classify_chunks("M14", 1, rd_root, mc, 100_000)
        # The 3 code-drifted chunks → historical (NOT kept), even
        # though their config_md5 matches. Both halves must match.
        assert len(out["kept"]) == 2, "only 2 fully-current chunks should be kept"
        assert len(out["historical"]) == 3, (
            "code_md5 drift alone must push chunks into historical; "
            "previous versions considered only config_md5"
        )
        assert out["historical_spins"] == 30_000

    def test_config_md5_drift_alone_flips_cell_to_historical(self, tmp_path):
        """Inverse of the above: config_md5 flipped, code_md5 stable.
        Symmetric treatment — config drift = historical."""
        from src.web_console.backend.app import _classify_chunks
        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "CFG_CUR",
            "codeSummaryMd5": "CODE_CUR",
        }]}), encoding="utf-8")
        rd_root = tmp_path / "rawdata"
        mode_dir = rd_root / "M14" / "mode_1"
        for i in range(1, 4):
            _write_chunk(mode_dir, i, config_md5="CFG_OLD", code_md5="CODE_CUR",
                         spin_times=10_000)
        for i in range(10, 12):
            _write_chunk(mode_dir, i, config_md5="CFG_CUR", code_md5="CODE_CUR",
                         spin_times=10_000)
        out = _classify_chunks("M14", 1, rd_root, mc, 100_000)
        assert len(out["kept"]) == 2
        assert len(out["historical"]) == 3
        assert out["historical_spins"] == 30_000

    def test_mixed_chunk_sizes_aggregated_correctly(self, tmp_path):
        """Mix of 1000-spin baseline chunks (from batch_dev_sampler)
        and 5000-spin live-sample chunks. Retention computed on
        actual _spin_times accumulation, not chunk count."""
        from src.web_console.backend.app import _classify_chunks
        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "cfg1", "codeSummaryMd5": "code1",
        }]}), encoding="utf-8")
        rd_root = tmp_path / "rawdata"
        mode_dir = rd_root / "M14" / "mode_1"
        # 10 baseline × 1000 = 10,000 spins
        for i in range(1, 11):
            _write_chunk(mode_dir, i, config_md5="cfg1", code_md5="code1",
                         spin_times=1_000)
        # 30 live × 5000 = 150,000 spins (chunk 11-40)
        for i in range(11, 41):
            _write_chunk(mode_dir, i, config_md5="cfg1", code_md5="code1",
                         spin_times=5_000)
        # 100k retention: need 10k (baseline) + 90k (= 18 live chunks)
        # → chunks 1-10 + 11-28 kept, chunks 29-40 deletable
        out = _classify_chunks("M14", 1, rd_root, mc, 100_000)
        assert len(out["kept"]) == 28  # 10 baseline + 18 live
        assert len(out["deletable"]) == 12
        assert out["kept_spins"] == 100_000
        assert out["deletable_spins"] == 60_000

    def test_unverifiable_machines_json_accepts_all_as_kept(self, tmp_path):
        """When machines.json has no md5 fields → unverifiable mode →
        all chunks treated as valid (kept up to quota)."""
        from src.web_console.backend.app import _classify_chunks
        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
        }]}), encoding="utf-8")
        rd_root = tmp_path / "rawdata"
        for i in range(1, 6):
            _write_chunk(rd_root / "M14" / "mode_1", i,
                         config_md5="doesnt_matter", code_md5="anything",
                         spin_times=10_000)
        out = _classify_chunks("M14", 1, rd_root, mc, 100_000)
        assert len(out["kept"]) == 5
        assert out["historical"] == []

    def test_unreadable_envelope_counted_as_historical(self, tmp_path):
        """Corrupted envelope → reclaimable so it doesn't linger."""
        from src.web_console.backend.app import _classify_chunks
        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": []}), encoding="utf-8")
        mode_dir = tmp_path / "rawdata" / "M14" / "mode_1"
        mode_dir.mkdir(parents=True)
        (mode_dir / "chunk_0001.json").write_text(
            "{ not valid json", encoding="utf-8"
        )
        out = _classify_chunks("M14", 1, tmp_path / "rawdata", mc, 100_000)
        assert out["kept"] == []
        assert out["deletable"] == []
        assert len(out["historical"]) == 1


class TestDeleteRawdataSafeDefault:
    def test_safe_delete_preserves_kept_quota(self, client, app_factory):
        """UI delete default (force=false) removes deletable + historical,
        keeps kept baseline intact."""
        c, _app = client
        mode_dir = app_factory.rawdata_dir / "M14" / "mode_1"
        for i in range(1, 16):
            _write_chunk(mode_dir, i, config_md5="",
                         code_md5="", spin_times=10_000)
        resp = c.delete("/api/rawdata/M14?mode=1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["forced"] is False
        assert body["deleted_chunks"] == 5
        assert body["kept_chunks"] == 10
        # Only kept chunks remain
        remaining = sorted(mode_dir.glob("chunk_*.json"))
        assert len(remaining) == 10

    def test_force_delete_wipes_everything(self, client, app_factory):
        c, _app = client
        mode_dir = app_factory.rawdata_dir / "M14" / "mode_1"
        for i in range(1, 6):
            _write_chunk(mode_dir, i, config_md5="", code_md5="",
                         spin_times=10_000)
        resp = c.delete("/api/rawdata/M14?mode=1&force=true")
        assert resp.status_code == 200
        assert resp.json()["forced"] is True
        # Whole mode dir gone
        assert not mode_dir.exists()

    def test_delete_machine_all_modes_safe(self, client, app_factory):
        """mode=None iterates every mode under the machine."""
        c, _app = client
        for mode in (1, 2):
            mode_dir = app_factory.rawdata_dir / "M14" / f"mode_{mode}"
            for i in range(1, 16):
                _write_chunk(mode_dir, i, config_md5="", code_md5="",
                             spin_times=10_000)
        resp = c.delete("/api/rawdata/M14")
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted_chunks"] == 10  # 5 per mode × 2 modes
        assert body["kept_chunks"] == 20


class TestRawdataEndpointResponse:
    def test_response_includes_classified_and_versions(
        self, client, app_factory,
    ):
        c, _app = client
        mode_dir = app_factory.rawdata_dir / "M14" / "mode_1"
        for i in range(1, 16):
            _write_chunk(mode_dir, i, config_md5="cfg1", code_md5="code1",
                         spin_times=10_000)
        resp = c.get("/api/rawdata/M14")
        assert resp.status_code == 200
        body = resp.json()
        mode1 = body["modes"]["1"]
        assert "classified" in mode1
        assert mode1["classified"]["kept_chunks"] == 10
        assert mode1["classified"]["deletable_chunks"] == 5
        assert mode1["classified"]["kept_spins"] == 100_000
        # versions block: one group (all chunks share cfg1 + code1)
        assert "versions" in mode1
        assert len(mode1["versions"]) == 1
        v = mode1["versions"][0]
        # machines.json has no md5 → unverifiable → is_current True
        # (nothing to diverge from)
        assert v["kept_chunks"] == 10
        assert v["deletable_chunks"] == 5


class TestSettingsEndpoint:
    def test_get_returns_default_when_no_file(self, client):
        c, _ = client
        resp = c.get("/api/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["min_retention_spins"] == 100_000

    def test_put_persists_and_subsequent_get_reflects(self, client):
        c, _ = client
        resp = c.put("/api/settings", json={"min_retention_spins": 50_000})
        assert resp.status_code == 200
        assert resp.json()["min_retention_spins"] == 50_000
        resp2 = c.get("/api/settings")
        assert resp2.json()["min_retention_spins"] == 50_000

    def test_put_rejects_negative(self, client):
        c, _ = client
        resp = c.put("/api/settings", json={"min_retention_spins": -1})
        assert resp.status_code == 400

    def test_put_rejects_non_integer(self, client):
        c, _ = client
        resp = c.put("/api/settings", json={"min_retention_spins": "abc"})
        assert resp.status_code == 400

    def test_retention_setting_drives_classifier(self, client, app_factory):
        """Retention knob → PUT → next classify call uses it."""
        c, _ = client
        mode_dir = app_factory.rawdata_dir / "M14" / "mode_1"
        for i in range(1, 11):
            _write_chunk(mode_dir, i, config_md5="", code_md5="",
                         spin_times=10_000)
        # Default 100k → 10 chunks × 10k = 100k exactly → all kept
        r1 = c.get("/api/rawdata/M14").json()["modes"]["1"]["classified"]
        assert r1["deletable_chunks"] == 0
        # Drop retention to 50k → half the chunks become deletable
        c.put("/api/settings", json={"min_retention_spins": 50_000})
        r2 = c.get("/api/rawdata/M14").json()["modes"]["1"]["classified"]
        assert r2["kept_chunks"] == 5
        assert r2["deletable_chunks"] == 5
