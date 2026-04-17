"""Regression tests for cache routing on /api/batch-run.

Three paths, picked in `start_batch`:
- fuzzy (target=0) + cache usable → `reuse_cache` → analyzer runs
  `--from-cache` (read-only, no live sampling).
- precise (target>0) + cache usable → `resume_cache` → analyzer runs
  `--resume-from-cache` (seeds state from cached chunks, then continues
  live sampling into the same dir until CI target hits).
- no cache → fresh API sample regardless of target.

History:
1. The original bug (reported via M273 mode 1 screenshot): precise
   target + cache silently used `--from-cache` (read-only) and returned
   12.9pp CI instead of actually sampling the ~3M spins the user's
   0.5pp ask needed.
2. First fix (4867): gate reuse on target==0, force fresh sample for
   precise targets. Correct but wasteful — discarded the 10k spins.
3. This test file now covers the final design: fresh sample is the
   last resort; precise+cache RESUMES sampling on top of existing
   chunks, only sampling the delta needed to hit target.
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
    def test_fuzzy_target_resumes_cache(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """target=0 (fuzzy) + cache → resume (not the old read-only
        reuse). Resume with max_chunks-bounded budget produces ~1M
        spins like the UI hint promises, using the cache as prefix."""
        c, app = client
        import src.web_console.backend.app as app_mod
        raw_root = tmp_path / "dev_rawdata"
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))
        _seed_v3_chunks(raw_root, "M273", 1, n=3)

        r = c.post("/api/batch-run", json=_batch_payload("M273", 1, target=0.0))
        assert r.status_code == 200
        batch_id = r.json()["batch_id"]
        b = c.get(f"/api/batch-run/{batch_id}").json()
        it = b["items"][0]
        # Fuzzy with cache now resumes, not reuses.
        assert it["resume_cache"] is True
        assert it["reuse_cache"] is False
        event_texts = " ".join(e["text"] for e in b["events"])
        assert "续采" in event_texts, event_texts
        # The old "跳过 API 采样" event no longer fires — that was the
        # read-only shortcut that left users stuck at cache CI.
        assert "跳过 API 采样" not in event_texts, event_texts

    def test_precise_target_resumes_cache(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """target=0.5 + cache → resume_cache=True, item carries the flag;
        batch event announces the continuation (not a fresh fresh sample).
        """
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
        # The item carries the resume flag, not reuse.
        it = b["items"][0]
        assert it["resume_cache"] is True
        assert it["reuse_cache"] is False
        event_texts = " ".join(e["text"] for e in b["events"])
        # "续采" announces we're continuing on top of the cache.
        assert "续采" in event_texts, event_texts
        # Must NOT be the fresh-sample-no-cache branch.
        assert "无可用本地 rawdata" not in event_texts, event_texts

    def test_precise_target_no_cache_samples_fresh(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        """Control: target>0 and no cache → plain 'sample fresh' event,
        neither reuse nor resume flags set."""
        c, app = client
        import src.web_console.backend.app as app_mod
        raw_root = tmp_path / "dev_rawdata"
        raw_root.mkdir()  # no chunks seeded
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)

        r = c.post("/api/batch-run", json=_batch_payload("M273", 1, target=0.5))
        assert r.status_code == 200
        batch_id = r.json()["batch_id"]
        b = c.get(f"/api/batch-run/{batch_id}").json()
        it = b["items"][0]
        assert it["resume_cache"] is False
        assert it["reuse_cache"] is False
        event_texts = " ".join(e["text"] for e in b["events"])
        assert "无可用本地 rawdata" in event_texts, event_texts
        assert "续采" not in event_texts, event_texts
