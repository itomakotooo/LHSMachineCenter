"""Regression test for the cache-reuse gate on /api/batch-run.

Bug (2026-04-17, reported by user with M273 mode 1 screenshot):
when the user clicked 开始采样 with target_halfwidth_pp=0.5, the batch
endpoint saw 10k spins of local rawdata, set `reuse_cache=True`, ran
analyzer `--from-cache`, and marked the item "completed" with CI≈12.9pp
— completely ignoring the user's 0.5pp target. The dev rawdata is a
fixed ~10k spins per machine intended for fuzzy / functional testing;
a precise target typically needs 100k–10M+ spins.

Fix: cache reuse is now gated on `target_halfwidth_pp == 0` (fuzzy
tier). Any positive target forces a fresh API sample even when local
cache exists. An informative event is emitted so the operator sees why.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _seed_v3_chunks(root: Path, machine: str, mode: int, n: int = 3) -> None:
    from fresh_slotlab.player_impact_analyzer import _save_chunk_cache
    mode_dir = root / machine / f"mode_{mode}"
    mode_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        resp = [
            {
                "roundResult": json.dumps(
                    [{"BetAmount": 1000, "WinCredits": 900,
                      "StopSymbolsByCol": "A|B|C|D|E", "SpinType": "Normal"}]
                ),
            }
        ]
        _save_chunk_cache(resp, i, machine, mode, 1000, 1000, 10, mode_dir)


def _batch_payload(machine: str, mode: int, target: float) -> dict[str, Any]:
    return {
        "items": [{"machine": machine, "mode": mode, "chunk_spin_times": 1000}],
        "concurrency": 1,
        "chunk_spin_times": 1000,
        "chunk_robot_count": 20,
        "max_chunks": 20,
        "target_halfwidth_pp": target,
        "batch_concurrency": 2,
        "timeout": 300,
        "auto_cleanup_cache": False,
    }


class TestBatchCacheReuseGate:
    def test_fuzzy_target_reuses_cache(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """target=0 (fuzzy) → reuse_cache=True when local chunks exist."""
        c, app = client
        # Point the backend's RAWDATA_ROOT at our tmp so seeded chunks are
        # found by check_rawdata_status.
        import src.web_console.backend.app as app_mod
        raw_root = tmp_path / "dev_rawdata"
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)
        # Also force unverifiable path (no machines.json lookup) so the
        # seeded chunks count as usable without MD5 match.
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))
        _seed_v3_chunks(raw_root, "M273", 1, n=3)

        r = c.post("/api/batch-run", json=_batch_payload("M273", 1, target=0.0))
        assert r.status_code == 200
        batch_id = r.json()["batch_id"]
        b = c.get(f"/api/batch-run/{batch_id}").json()
        assert len(b["items"]) == 1
        # reuse_cache True is reflected in the info event text.
        event_texts = " ".join(e["text"] for e in b["events"])
        assert "跳过 API 采样" in event_texts, event_texts

    def test_precise_target_refuses_cache(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """target=0.5 → reuse_cache=False even when local chunks exist.
        Also emits a warning event explaining why."""
        c, app = client
        import src.web_console.backend.app as app_mod
        raw_root = tmp_path / "dev_rawdata"
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))
        _seed_v3_chunks(raw_root, "M273", 1, n=3)

        r = c.post("/api/batch-run", json=_batch_payload("M273", 1, target=0.5))
        assert r.status_code == 200
        batch_id = r.json()["batch_id"]
        b = c.get(f"/api/batch-run/{batch_id}").json()
        event_texts = " ".join(e["text"] for e in b["events"])
        # Must NOT show the reuse-cache shortcut line.
        assert "跳过 API 采样" not in event_texts, event_texts
        # Must show the warning that explains why cache was not reused.
        assert "精度目标" in event_texts, event_texts
        assert "重新从 API 采样" in event_texts, event_texts

    def test_precise_target_no_cache_samples_fresh(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """Control: target>0 and no cache → plain 'sample fresh' event,
        not the '有 cache 但 target 需要更多' warning."""
        c, app = client
        import src.web_console.backend.app as app_mod
        raw_root = tmp_path / "dev_rawdata"
        raw_root.mkdir()  # no chunks seeded
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)

        r = c.post("/api/batch-run", json=_batch_payload("M273", 1, target=0.5))
        assert r.status_code == 200
        batch_id = r.json()["batch_id"]
        b = c.get(f"/api/batch-run/{batch_id}").json()
        event_texts = " ".join(e["text"] for e in b["events"])
        assert "无可用本地 rawdata" in event_texts, event_texts
        assert "精度目标" not in event_texts, event_texts
