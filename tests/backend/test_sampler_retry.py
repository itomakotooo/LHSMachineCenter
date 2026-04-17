"""Tests for batch_dev_sampler retry + atomic envelope parity.

Covers P1.3:
- Transient upstream failures (5xx / URLError / TimeoutError) retry with
  exponential backoff until success or attempt limit
- Non-retryable HTTPError (e.g. 404) fails fast
- Non-network errors (JSONDecodeError in post_json) propagate immediately
- Backoff sleeps are monkey-patched so tests run fast
- _atomic_write_envelope uses .tmp + os.replace and cleans up on failure
"""

from __future__ import annotations

import json
import socket
import urllib.error
from pathlib import Path

import pytest

import fresh_slotlab.batch_dev_sampler as sampler


class _StubResp:
    """Stand-in HTTPError response for urllib.error.HTTPError(code=...)."""
    def __init__(self, code: int):
        self.code = code
    def read(self) -> bytes:
        return b""
    def getcode(self) -> int:
        return self.code


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://upstream/", code=code, msg="simulated",
        hdrs=None, fp=None,
    )


class TestPostJsonWithRetry:
    def test_success_on_first_attempt(self, monkeypatch):
        calls = {"n": 0}

        def post_ok(payload, timeout):
            calls["n"] += 1
            return [{"ok": True}]

        monkeypatch.setattr(sampler, "post_json", post_ok)
        result = sampler._post_json_with_retry({}, timeout=1.0)
        assert result == [{"ok": True}]
        assert calls["n"] == 1

    def test_retries_on_502_then_succeeds(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr(sampler.time, "sleep", lambda s: sleeps.append(s))
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise _http_error(502)
            return [{"final": True}]

        monkeypatch.setattr(sampler, "post_json", post)
        result = sampler._post_json_with_retry(
            {}, timeout=1.0, max_attempts=3, initial_backoff_s=1.0
        )
        assert result == [{"final": True}]
        assert attempts["n"] == 3
        # Backoff doubles: 1s then 2s (no sleep after final success).
        assert sleeps == [1.0, 2.0]

    def test_retries_on_url_error(self, monkeypatch):
        monkeypatch.setattr(sampler.time, "sleep", lambda s: None)
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise urllib.error.URLError("connection refused")
            return [{"ok": True}]

        monkeypatch.setattr(sampler, "post_json", post)
        result = sampler._post_json_with_retry({}, timeout=1.0)
        assert result == [{"ok": True}]
        assert attempts["n"] == 2

    def test_retries_on_timeout(self, monkeypatch):
        monkeypatch.setattr(sampler.time, "sleep", lambda s: None)
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise TimeoutError("read timeout")
            return [{"ok": True}]

        monkeypatch.setattr(sampler, "post_json", post)
        assert sampler._post_json_with_retry({}, timeout=1.0)[0]["ok"]

    def test_retries_on_socket_timeout(self, monkeypatch):
        monkeypatch.setattr(sampler.time, "sleep", lambda s: None)
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise socket.timeout("connect")
            return [{"ok": True}]

        monkeypatch.setattr(sampler, "post_json", post)
        assert sampler._post_json_with_retry({}, timeout=1.0)[0]["ok"]

    def test_non_retryable_http_error_fails_fast(self, monkeypatch):
        # 404 is not retryable — operator bug, retrying masks it.
        sleeps: list[float] = []
        monkeypatch.setattr(sampler.time, "sleep", lambda s: sleeps.append(s))
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            raise _http_error(404)

        monkeypatch.setattr(sampler, "post_json", post)
        with pytest.raises(urllib.error.HTTPError):
            sampler._post_json_with_retry({}, timeout=1.0)
        assert attempts["n"] == 1
        assert sleeps == []

    def test_json_decode_propagates_immediately(self, monkeypatch):
        # post_json's json.loads failure surfaces as JSONDecodeError;
        # that's a data problem, not a transient upstream problem.
        monkeypatch.setattr(sampler.time, "sleep", lambda s: None)
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            raise json.JSONDecodeError("bad", "x", 0)

        monkeypatch.setattr(sampler, "post_json", post)
        with pytest.raises(json.JSONDecodeError):
            sampler._post_json_with_retry({}, timeout=1.0)
        assert attempts["n"] == 1

    def test_all_attempts_exhausted_raises_last_error(self, monkeypatch):
        monkeypatch.setattr(sampler.time, "sleep", lambda s: None)
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            raise urllib.error.URLError(f"fail-{attempts['n']}")

        monkeypatch.setattr(sampler, "post_json", post)
        with pytest.raises(urllib.error.URLError) as exc_info:
            sampler._post_json_with_retry({}, timeout=1.0, max_attempts=3)
        assert attempts["n"] == 3
        assert "fail-3" in str(exc_info.value)


class TestAtomicWriteEnvelope:
    def test_writes_and_cleans_tmp(self, tmp_path: Path):
        out = tmp_path / "chunk_0001.json"
        sampler._atomic_write_envelope(out, {"hello": "world"})
        assert out.exists()
        assert not (tmp_path / "chunk_0001.json.tmp").exists()
        assert json.loads(out.read_text(encoding="utf-8")) == {"hello": "world"}

    def test_replace_failure_cleans_tmp(self, tmp_path: Path, monkeypatch):
        out = tmp_path / "chunk_0001.json"

        def boom(*a, **kw):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(sampler.os, "replace", boom)
        with pytest.raises(OSError):
            sampler._atomic_write_envelope(out, {"x": 1})
        # .tmp cleaned; target never existed.
        assert not out.exists()
        assert not (tmp_path / "chunk_0001.json.tmp").exists()

    def test_replace_failure_preserves_prior_chunk(self, tmp_path: Path, monkeypatch):
        out = tmp_path / "chunk_0001.json"
        sampler._atomic_write_envelope(out, {"original": True})
        original_bytes = out.read_bytes()

        def boom(*a, **kw):
            raise OSError("simulated")

        monkeypatch.setattr(sampler.os, "replace", boom)
        with pytest.raises(OSError):
            sampler._atomic_write_envelope(out, {"new": True})
        # Prior chunk intact.
        assert out.read_bytes() == original_bytes
