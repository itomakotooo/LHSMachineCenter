"""Tests for chunk cache atomic write + payload sha256 (P0.1 session 2026-04).

Covers:
- `_payload_sha256` is deterministic and sensitive to mutations
- `_save_chunk_cache` writes atomically via `.tmp` + `os.replace`
- `.tmp` leftovers are cleaned up on failure (no partial garbage)
- `load_chunk_envelope` detects tampered payloads with a readable error
- Legacy v2 envelopes (no `_payload_sha256` field) still load cleanly
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import fresh_slotlab.analyzer.core.writer as analyzer
from fresh_slotlab.analyzer.core.writer import (
    CHUNK_CACHE_VERSION,
    _save_chunk_cache as _real_save_chunk_cache,
)
from fresh_slotlab.analyzer.core.parser import (
    ChunkIntegrityError,
    _payload_sha256,
    load_chunk_envelope,
)


def _stub_md5_lookup(_machine: str) -> tuple[str, str]:
    """Stub for the lookup_machine_md5 kwarg required post-P2-B3 carve.
    Tests don't need real md5 — they just exercise the chunk-write contract."""
    return ("", "")


def _save_chunk_cache(*args, **kwargs):
    """Wrapper that defaults the new required kwarg to a stub.
    Pre-P2-B3 callsites passed 8 positional args; this preserves them."""
    kwargs.setdefault("lookup_machine_md5", _stub_md5_lookup)
    return _real_save_chunk_cache(*args, **kwargs)


def _sample_response() -> list:
    return [
        {
            "roundResult": json.dumps(
                [{"BetAmount": 1000, "CurrentWin": 500, "SpinType": "Normal"}]
            ),
            "analysisResult": {},
        }
    ]


class TestPayloadSha256:
    def test_stable_across_calls(self):
        resp = _sample_response()
        assert _payload_sha256(resp) == _payload_sha256(resp)

    def test_differs_on_mutation(self):
        r1 = _sample_response()
        r2 = _sample_response()
        r2[0]["extra"] = "x"
        assert _payload_sha256(r1) != _payload_sha256(r2)

    def test_stable_across_key_order(self):
        # sort_keys=True → reordering same keys yields the same hash.
        assert _payload_sha256({"x": 1, "y": 2}) == _payload_sha256({"y": 2, "x": 1})

    def test_hex_length(self):
        assert len(_payload_sha256(_sample_response())) == 64


class TestSaveChunkCache:
    def test_writes_envelope_v3_with_sha(self, tmp_path: Path):
        _save_chunk_cache(_sample_response(), 1, "M14", 1, 1000, 100, 10, tmp_path)
        p = tmp_path / "chunk_0001.json"
        assert p.exists()
        d = json.loads(p.read_text(encoding="utf-8"))
        assert d["_cache_version"] == CHUNK_CACHE_VERSION == 3
        assert "_payload_sha256" in d
        assert d["_payload_sha256"] == _payload_sha256(d["response"])

    def test_no_tmp_leftover_on_success(self, tmp_path: Path):
        _save_chunk_cache(_sample_response(), 1, "M14", 1, 1000, 100, 10, tmp_path)
        assert not (tmp_path / "chunk_0001.json.tmp").exists()

    def test_cache_dir_none_is_noop(self, tmp_path: Path):
        # cache_dir=None means "don't cache" — must not touch tmp_path.
        _save_chunk_cache(_sample_response(), 1, "M14", 1, 1000, 100, 10, None)
        assert list(tmp_path.iterdir()) == []

    def test_atomic_no_partial_target_on_replace_failure(
        self, tmp_path: Path, monkeypatch
    ):
        # If os.replace fails after write_text succeeded, the target
        # must NOT exist half-written, and the .tmp must be cleaned up.
        def boom(*a, **kw):
            raise OSError("simulated: replace failed")

        monkeypatch.setattr(analyzer.os, "replace", boom)
        _save_chunk_cache(_sample_response(), 1, "M14", 1, 1000, 100, 10, tmp_path)
        assert not (tmp_path / "chunk_0001.json").exists()
        assert not (tmp_path / "chunk_0001.json.tmp").exists()

    def test_failed_write_preserves_prior_chunk(self, tmp_path: Path, monkeypatch):
        # A successful prior write must survive a later failed write —
        # atomicity means "no partial", not "rolls back to empty".
        _save_chunk_cache(_sample_response(), 1, "M14", 1, 1000, 100, 10, tmp_path)
        original_bytes = (tmp_path / "chunk_0001.json").read_bytes()

        def boom(*a, **kw):
            raise OSError("simulated")

        monkeypatch.setattr(analyzer.os, "replace", boom)
        # Second write (with different payload) should fail silently
        # without disturbing the previously-committed file.
        _save_chunk_cache([{"different": True}], 1, "M14", 1, 1000, 100, 10, tmp_path)
        assert (tmp_path / "chunk_0001.json").read_bytes() == original_bytes


class TestLoadChunkEnvelope:
    def _write_v3(self, tmp_path: Path) -> Path:
        _save_chunk_cache(_sample_response(), 1, "M14", 1, 1000, 100, 10, tmp_path)
        return tmp_path / "chunk_0001.json"

    def test_valid_v3_chunk_loads(self, tmp_path: Path):
        p = self._write_v3(tmp_path)
        d = load_chunk_envelope(p)
        assert d["_cache_version"] == 3
        assert d["response"] == _sample_response()

    def test_tampered_payload_raises(self, tmp_path: Path):
        p = self._write_v3(tmp_path)
        d = json.loads(p.read_text(encoding="utf-8"))
        # Mutate response after the sha was computed.
        d["response"][0]["roundResult"] = "[]"
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ChunkIntegrityError) as exc:
            load_chunk_envelope(p)
        assert "sha256 mismatch" in str(exc.value)
        assert "chunk_0001.json" in str(exc.value)

    def test_truncated_payload_raises_decode(self, tmp_path: Path):
        # A file chopped mid-JSON doesn't even parse — caller sees
        # JSONDecodeError, not ChunkIntegrityError. This is the correct
        # distinction: envelope-level vs payload-level corruption.
        p = self._write_v3(tmp_path)
        raw = p.read_bytes()
        p.write_bytes(raw[: len(raw) // 2])
        with pytest.raises(json.JSONDecodeError):
            load_chunk_envelope(p)

    def test_legacy_v2_envelope_loads_without_sha(self, tmp_path: Path):
        # v2 envelopes from the existing 5.6G rawdata don't carry
        # _payload_sha256 — reader must accept them unchecked so the
        # migration doesn't invalidate the historical cache.
        envelope = {
            "_cache_version": 2,
            "_machine": "M14",
            "_mode": 1,
            "_bet": 1000,
            "_spin_times": 1000,
            "_robot_count": 10,
            "_chunk_index": 1,
            "_saved_at": "2026-04-14T00:00:00Z",
            "_config_md5": "abc",
            "_code_md5": "def",
            "response": _sample_response(),
        }
        p = tmp_path / "chunk_0001.json"
        p.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        d = load_chunk_envelope(p)
        assert d["_cache_version"] == 2
        assert "_payload_sha256" not in d

    def test_v3_envelope_with_empty_sha_field_skips_check(self, tmp_path: Path):
        # Defensive: if sha field is explicitly empty string (shouldn't
        # happen but might if someone hand-edits), treat as "no check"
        # rather than failing. Truthy check in the reader handles this.
        envelope = {
            "_cache_version": 3,
            "_payload_sha256": "",
            "response": _sample_response(),
        }
        p = tmp_path / "chunk_0001.json"
        p.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        # No exception; envelope loads.
        d = load_chunk_envelope(p)
        assert d["response"] == _sample_response()
