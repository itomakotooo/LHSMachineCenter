"""P3-T1: Config upload endpoint tests.

Covers the 6 tests from session_artifacts/_impl/p3/brief.md §6 P3-T1:
  test_post_upload_creates_config_with_correct_hash_id
  test_post_upload_dedups_identical_content
  test_get_configs_lists_uploaded
  test_get_config_by_id_returns_content
  test_upload_invalid_json_returns_400
  test_concurrent_upload_same_content_no_file_corruption

Design source: 04_deploy_architecture_proposal_v2.md §4.3 "Config Object Design"
D1: POST/GET /api/configs/upload + /api/configs + /api/configs/{id}

Memory feedback files honored:
  memory/feedback_enumerate_safety_paths.md — inject-bug recipe in each test.
  memory/feedback_no_silent_swallow.md — concurrent upload must not corrupt
    registry; dedup tested.
  memory/feedback_integration_test_argv.md — HTTP-level tests via TestClient,
    not mocks.
  memory/feedback_perf_claim_needs_e2e_event_stream.md — concurrent test
    uses real threads, not mocked concurrency.

Inject-bug recipes (for future devs to reproduce):

  D1a (test_post_upload_creates_config_with_correct_hash_id):
    In app.py upload_config, change:
        config_id = _hashlib.sha1(content_str.encode("utf-8")).hexdigest()
    to:
        config_id = "hardcoded_bad_id"
    Run test → FAILS (sha1 assertion fails).  Revert → PASSES.

  D1b (test_post_upload_dedups_identical_content):
    In app.py upload_config, in the _register inner function, remove the
    idempotent guard:
        for e in entries:
            if (e.get("config_id") == config_id
                    and e.get("display_name") == display_name):
                return reg  # Idempotent
    Run test → FAILS (registry has >1 entry for same content + display_name).
    Revert → PASSES.

  D1c (test_upload_invalid_json_returns_400):
    In app.py upload_config, remove the json.JSONDecodeError branch that
    raises HTTPException(400). Replace with: pass (no-op).
    Run test → FAILS (gets 500 or 200 instead of 400). Revert → PASSES.

  D1d (test_concurrent_upload_same_content_no_file_corruption):
    In app.py upload_config, replace:
        if not content_path.exists():
            atomic_json_write(content_path, parsed_content)
    with:
        atomic_json_write(content_path, parsed_content)  # writes unconditionally
    This alone doesn't break dedup, but the concurrent write to the same path
    via a non-atomic writer would corrupt. The test catches idempotency
    guarantee via the registry entries count == 1 check (if _register is also
    broken to not dedup, this would catch it).

Cross-refs:
  session_artifacts/_impl/p3/brief.md §6 P3-T1
  session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md §4.3
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.web_console.backend.app as _app_module
from src.web_console.backend.app import create_app


# ---------------------------------------------------------------------------
# Fixture: isolated app with tmp upload dir
# ---------------------------------------------------------------------------


@pytest.fixture
def upload_app(tmp_path: Path, tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
               fake_machines, fake_analyzer, stub_popen, monkeypatch):
    """App instance with all state isolated to tmp_path, including config upload dir."""
    monkeypatch.setattr("src.web_console.backend.app._default_popen_factory", stub_popen)
    monkeypatch.setattr("src.web_console.backend.app._terminate_pid_if_running",
                        lambda pid: True)

    # Redirect the module-level CONFIGS_UPLOAD_DIR to tmp so tests don't
    # pollute the real configs/uploaded_configs/ directory.
    tmp_upload = tmp_path / "uploaded_configs"
    tmp_upload.mkdir()
    monkeypatch.setattr("src.web_console.backend.app.CONFIGS_UPLOAD_DIR", tmp_upload)

    app = create_app(
        state_dir=tmp_state_dir,
        reports_root=tmp_reports,
        cache_root=tmp_cache,
        machines_config=fake_machines,
        analyzer_path=fake_analyzer,
        rawdata_root=tmp_rawdata,
    )
    app._test_upload_dir = tmp_upload  # expose for assertions
    return app


@pytest.fixture
def upload_client(upload_app):
    with TestClient(upload_app) as c:
        yield c, upload_app


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _sha1(content: dict | str) -> str:
    """Compute the expected config_id for a given content."""
    if isinstance(content, str):
        obj = json.loads(content)
    else:
        obj = content
    canonical = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# P3-T1 tests
# ---------------------------------------------------------------------------


class TestConfigUpload:
    """D1: POST /api/configs/upload — SHA1 dedup + atomic registry update."""

    def test_post_upload_creates_config_with_correct_hash_id(self, upload_client):
        """Upload content; assert config_id == sha1(canonical_json(content)).

        Inject-bug: change sha1 computation to use a hardcoded string →
        test fails (computed id doesn't match sha1 of content). Revert → passes.
        """
        c, app = upload_client
        content = {"machine": "M14", "rtp": 95.0}
        resp = c.post("/api/configs/upload", json={
            "content": content,
            "display_name": "test-config-A",
        })
        assert resp.status_code == 200, f"Upload failed: {resp.text}"
        data = resp.json()
        assert data["ok"] is True
        expected_id = _sha1(content)
        assert data["config_id"] == expected_id, (
            f"config_id mismatch: expected sha1={expected_id!r}, got {data['config_id']!r}"
        )
        assert data["display_name"] == "test-config-A"

        # Content file must exist on disk at the right path
        upload_dir = app._test_upload_dir
        content_file = upload_dir / f"{expected_id}.json"
        assert content_file.exists(), f"Content file not written to {content_file}"
        on_disk = json.loads(content_file.read_text(encoding="utf-8"))
        assert on_disk == content

    def test_post_upload_dedups_identical_content(self, upload_client):
        """Upload same content twice with different display names.

        Same content → same config_id.
        Second upload with different display_name → two registry entries with same config_id.
        BUT same (config_id, display_name) → exactly one entry (idempotent).

        Inject-bug: remove the idempotent guard inside _register → uploading
        same (config_id, display_name) twice creates two registry entries →
        test fails (entry count check). Revert → passes.
        """
        c, app = upload_client
        content = {"type": "classic", "reels": 3}

        # First upload
        r1 = c.post("/api/configs/upload", json={
            "content": content, "display_name": "nameA"
        })
        assert r1.status_code == 200
        cid = r1.json()["config_id"]

        # Second upload — same content, different display_name
        r2 = c.post("/api/configs/upload", json={
            "content": content, "display_name": "nameB"
        })
        assert r2.status_code == 200
        assert r2.json()["config_id"] == cid, "Same content must produce same config_id"

        # Third upload — same (content, display_name) as first → idempotent
        r3 = c.post("/api/configs/upload", json={
            "content": content, "display_name": "nameA"
        })
        assert r3.status_code == 200
        assert r3.json()["config_id"] == cid

        # Registry must have exactly 2 entries (nameA + nameB), not 3
        upload_dir = app._test_upload_dir
        reg = json.loads((upload_dir / "_registry.json").read_text(encoding="utf-8"))
        entries = reg["entries"]
        assert len(entries) == 2, (
            f"Expected 2 registry entries (nameA + nameB), got {len(entries)}: {entries}"
        )

        # Only one content file
        json_files = [f for f in upload_dir.iterdir()
                      if f.suffix == ".json" and f.name != "_registry.json"]
        assert len(json_files) == 1, (
            f"Expected 1 content file, got {len(json_files)}: {[f.name for f in json_files]}"
        )

    def test_get_configs_lists_uploaded(self, upload_client):
        """Upload N configs; GET /api/configs returns N entries.

        Inject-bug: remove the GET /api/configs endpoint → 404 instead of list.
        Or change the endpoint to return an empty list → test fails (count != N).
        """
        c, app = upload_client
        configs = [
            {"machine": f"M{i}", "rtp": 90.0 + i}
            for i in range(4)
        ]
        cids = set()
        for i, cfg in enumerate(configs):
            resp = c.post("/api/configs/upload", json={
                "content": cfg, "display_name": f"cfg-{i}"
            })
            assert resp.status_code == 200
            cids.add(resp.json()["config_id"])

        # All 4 are distinct (different content → different sha1)
        assert len(cids) == 4

        list_resp = c.get("/api/configs")
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert "entries" in data, f"Response missing 'entries' key: {data}"
        assert len(data["entries"]) == 4, (
            f"Expected 4 entries, got {len(data['entries'])}: {data['entries']}"
        )
        returned_ids = {e["config_id"] for e in data["entries"]}
        assert returned_ids == cids, (
            f"Listed config_ids don't match uploaded: {returned_ids} vs {cids}"
        )

    def test_get_config_by_id_returns_content(self, upload_client):
        """Upload; GET /api/configs/{config_id}; verify content + metadata.

        Inject-bug: in get_config, return an empty dict → content missing →
        test fails (content assertion). Revert → passes.
        """
        c, app = upload_client
        content = {"slot": "M99", "version": "3.1", "rtp_target": 94.5}
        up_resp = c.post("/api/configs/upload", json={
            "content": content, "display_name": "my-special-config"
        })
        assert up_resp.status_code == 200
        config_id = up_resp.json()["config_id"]

        get_resp = c.get(f"/api/configs/{config_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["config_id"] == config_id
        assert data["display_name"] == "my-special-config"
        assert data["content"] == content, (
            f"Content mismatch: expected {content}, got {data['content']}"
        )

    def test_upload_invalid_json_returns_400(self, upload_client):
        """POST non-JSON string as content → 400.

        Inject-bug: remove the json.JSONDecodeError except branch → endpoint
        crashes with 500 or processes bad input → test fails (status != 400).
        Revert → passes.
        """
        c, _ = upload_client

        # String that is not valid JSON
        resp = c.post("/api/configs/upload", json={
            "content": "this is not { valid json",
            "display_name": "bad-upload",
        })
        assert resp.status_code == 400, (
            f"Expected 400 for invalid JSON content, got {resp.status_code}: {resp.text}"
        )

        # None content → 400 (content is required)
        resp2 = c.post("/api/configs/upload", json={"display_name": "no-content"})
        assert resp2.status_code == 400, (
            f"Expected 400 when content is missing, got {resp2.status_code}"
        )

    def test_get_config_by_nonexistent_id_returns_404(self, upload_client):
        """GET /api/configs/{bad_id} → 404.

        Simple guard: endpoint must not crash on missing config_id.
        """
        c, _ = upload_client
        resp = c.get("/api/configs/nonexistent_sha1_abc123def456")
        assert resp.status_code == 404, (
            f"Expected 404 for unknown config_id, got {resp.status_code}"
        )

    def test_concurrent_upload_same_content_no_file_corruption(
        self, tmp_path, tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_machines, fake_analyzer, stub_popen, monkeypatch
    ):
        """5 threads upload same content concurrently; assert one content file,
        registry has exactly 1 entry (all same (config_id, display_name)).

        Per memory/feedback_perf_claim_needs_e2e_event_stream.md: uses real
        threads (not mock concurrency).

        Inject-bug: replace atomic_json_read_modify_write with a non-atomic
        read-then-write (two separate calls) → concurrent writes race → registry
        ends up with 0-5 entries depending on timing → test fails (count != 1
        OR file is corrupted). The atomic write makes this safe.
        """
        monkeypatch.setattr("src.web_console.backend.app._default_popen_factory", stub_popen)
        monkeypatch.setattr("src.web_console.backend.app._terminate_pid_if_running",
                            lambda pid: True)
        tmp_upload = tmp_path / "uploaded_configs_concurrent"
        tmp_upload.mkdir()
        monkeypatch.setattr("src.web_console.backend.app.CONFIGS_UPLOAD_DIR", tmp_upload)

        app = create_app(
            state_dir=tmp_state_dir,
            reports_root=tmp_reports,
            cache_root=tmp_cache,
            machines_config=fake_machines,
            analyzer_path=fake_analyzer,
            rawdata_root=tmp_rawdata,
        )

        content = {"concurrent": True, "data": [1, 2, 3, 4, 5]}
        errors: list[str] = []
        results: list[dict] = []
        lock = threading.Lock()

        def do_upload(i: int) -> None:
            with TestClient(app) as c:
                resp = c.post("/api/configs/upload", json={
                    "content": content,
                    "display_name": "concurrent-upload",  # all same name
                })
                with lock:
                    if resp.status_code != 200:
                        errors.append(f"Thread {i}: got {resp.status_code}: {resp.text[:100]}")
                    else:
                        results.append(resp.json())

        N = 5
        threads = [threading.Thread(target=do_upload, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Upload errors in concurrent threads: {errors}"
        assert len(results) == N, f"Expected {N} results, got {len(results)}"

        # All config_ids must be identical (same content)
        all_ids = {r["config_id"] for r in results}
        assert len(all_ids) == 1, f"Concurrent same-content uploads produced multiple ids: {all_ids}"
        expected_id = _sha1(content)
        assert list(all_ids)[0] == expected_id

        # Exactly one content file on disk
        json_files = [f for f in tmp_upload.iterdir()
                      if f.suffix == ".json" and f.name != "_registry.json"]
        assert len(json_files) == 1, (
            f"Expected 1 content file after concurrent uploads, got {len(json_files)}: "
            f"{[f.name for f in json_files]}"
        )

        # Registry has exactly 1 entry (all same (config_id, display_name) → idempotent)
        reg = json.loads((tmp_upload / "_registry.json").read_text(encoding="utf-8"))
        entries = reg.get("entries", [])
        assert len(entries) == 1, (
            f"Expected 1 registry entry after concurrent same-content uploads, "
            f"got {len(entries)}: {entries}"
        )
        # Registry must be valid JSON (not corrupted)
        assert json.loads((tmp_upload / "_registry.json").read_text(encoding="utf-8"))
