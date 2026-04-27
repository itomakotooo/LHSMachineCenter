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
import fresh_slotlab.player_impact_analyzer as analyzer

# post_json_with_retry lives in analyzer now (shared with the live
# sampling loop). The helper's internal `post_json` call and `time.sleep`
# both resolve to analyzer's module namespace, so monkeypatches must
# target analyzer — not sampler — to take effect.


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

        monkeypatch.setattr(analyzer, "post_json", post_ok)
        result = sampler._post_json_with_retry({}, timeout=1.0)
        assert result == [{"ok": True}]
        assert calls["n"] == 1

    def test_retries_on_502_then_succeeds(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr(analyzer.time, "sleep", lambda s: sleeps.append(s))
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise _http_error(502)
            return [{"final": True}]

        monkeypatch.setattr(analyzer, "post_json", post)
        result = sampler._post_json_with_retry(
            {}, timeout=1.0, max_attempts=3, initial_backoff_s=1.0
        )
        assert result == [{"final": True}]
        assert attempts["n"] == 3
        # Backoff doubles: 1s then 2s (no sleep after final success).
        assert sleeps == [1.0, 2.0]

    def test_retries_on_url_error(self, monkeypatch):
        monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise urllib.error.URLError("connection refused")
            return [{"ok": True}]

        monkeypatch.setattr(analyzer, "post_json", post)
        result = sampler._post_json_with_retry({}, timeout=1.0)
        assert result == [{"ok": True}]
        assert attempts["n"] == 2

    def test_retries_on_timeout(self, monkeypatch):
        monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise TimeoutError("read timeout")
            return [{"ok": True}]

        monkeypatch.setattr(analyzer, "post_json", post)
        assert sampler._post_json_with_retry({}, timeout=1.0)[0]["ok"]

    def test_retries_on_socket_timeout(self, monkeypatch):
        monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise socket.timeout("connect")
            return [{"ok": True}]

        monkeypatch.setattr(analyzer, "post_json", post)
        assert sampler._post_json_with_retry({}, timeout=1.0)[0]["ok"]

    def test_non_retryable_http_error_fails_fast(self, monkeypatch):
        # 404 is not retryable — operator bug, retrying masks it.
        sleeps: list[float] = []
        monkeypatch.setattr(analyzer.time, "sleep", lambda s: sleeps.append(s))
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            raise _http_error(404)

        monkeypatch.setattr(analyzer, "post_json", post)
        with pytest.raises(urllib.error.HTTPError):
            sampler._post_json_with_retry({}, timeout=1.0)
        assert attempts["n"] == 1
        assert sleeps == []

    def test_json_decode_propagates_immediately(self, monkeypatch):
        # post_json's json.loads failure surfaces as JSONDecodeError;
        # that's a data problem, not a transient upstream problem.
        monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            raise json.JSONDecodeError("bad", "x", 0)

        monkeypatch.setattr(analyzer, "post_json", post)
        with pytest.raises(json.JSONDecodeError):
            sampler._post_json_with_retry({}, timeout=1.0)
        assert attempts["n"] == 1

    def test_all_attempts_exhausted_raises_last_error(self, monkeypatch):
        monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            raise urllib.error.URLError(f"fail-{attempts['n']}")

        monkeypatch.setattr(analyzer, "post_json", post)
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


# ---------- transient burst regression (M273 2026-04-17 incident) ----------


class TestTransientBurstRetries:
    """2026-04-17 user incident: M273 mode_1 ran fine then a ~10s
    upstream hiccup (mix of IncompleteRead + http_502) killed the
    entire run at cumulative_failed_chunks=12. Two gaps surfaced:

    1. `IncompleteRead` (truncated HTTP body, very common on flaky
       proxies) was NOT in the retry list at all. It fell through to
       `run_sampling_chunk`'s bare `except Exception` — zero retries,
       instant failure. Same for ConnectionResetError (TCP RST) and
       http.client.RemoteDisconnected (close-before-response).

    2. Default ``max_attempts=3`` with 1s→2s backoff exhausts the retry
       window in ~3s of sleeps. A realistic upstream hiccup lasts
       10-30s. The retry budget needs to cover that window.

    3. ``_MAX_CONSECUTIVE_FAILED_BATCHES = 3`` (with
       batch_concurrency=4, that's ~12 chunks) triggers bailout after
       ~10s of sustained failures — too aggressive given upstream
       recovery typically takes 15-30s."""

    def test_incomplete_read_is_retryable(self, monkeypatch):
        """http.client.IncompleteRead → retry. Previously surfaced as
        a generic Exception outside the retry wrapper; the chunk failed
        on its first attempt with zero retries."""
        from http.client import IncompleteRead
        monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise IncompleteRead(partial=b"")
            return [{"ok": True}]

        monkeypatch.setattr(analyzer, "post_json", post)
        result = sampler._post_json_with_retry(
            {}, timeout=1.0, max_attempts=5, initial_backoff_s=1.0
        )
        assert result == [{"ok": True}]
        assert attempts["n"] == 3

    def test_connection_reset_is_retryable(self, monkeypatch):
        """ConnectionResetError (TCP RST from upstream / proxy drain).
        Subclass of OSError, previously not matched by the retry
        except-clause."""
        monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ConnectionResetError("upstream sent RST")
            return [{"ok": True}]

        monkeypatch.setattr(analyzer, "post_json", post)
        assert sampler._post_json_with_retry({}, timeout=1.0)[0]["ok"]
        assert attempts["n"] == 2

    def test_remote_disconnected_is_retryable(self, monkeypatch):
        """http.client.RemoteDisconnected (connection closed before a
        response arrived — happens on LB drain mid-request)."""
        from http.client import RemoteDisconnected
        monkeypatch.setattr(analyzer.time, "sleep", lambda s: None)
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RemoteDisconnected("close before response")
            return [{"ok": True}]

        monkeypatch.setattr(analyzer, "post_json", post)
        assert sampler._post_json_with_retry({}, timeout=1.0)[0]["ok"]

    def test_backoff_capped_at_max_backoff_s(self, monkeypatch):
        """Unbounded 2^n doubling at max_attempts=7 gives 64s final
        sleep — absurd. Cap via max_backoff_s. Default cap is
        tested separately; this locks the cap parameter's shape."""
        sleeps: list[float] = []
        monkeypatch.setattr(analyzer.time, "sleep", lambda s: sleeps.append(s))
        attempts = {"n": 0}

        def post(payload, timeout):
            attempts["n"] += 1
            if attempts["n"] < 6:
                raise _http_error(502)
            return [{"ok": True}]

        monkeypatch.setattr(analyzer, "post_json", post)
        sampler._post_json_with_retry(
            {}, timeout=1.0, max_attempts=6,
            initial_backoff_s=1.0, max_backoff_s=5.0,
        )
        # Sleeps at attempts 0,1,2,3,4: unbounded would be 1,2,4,8,16.
        # Cap 5 clips the last two to 5.
        assert sleeps == [1.0, 2.0, 4.0, 5.0, 5.0]

    def test_default_max_attempts_covers_internal_hiccup_window(self):
        """Default max_attempts is sized for the current upstream
        environment (internal-network since 2026-04-26). Internal
        hiccups are sub-second TCP blips — 3 attempts × cap-5s ≈ ~6s
        retry window is plenty without burning time on errors that
        won't transiently clear (those bail-fast via the machine-class
        counter at the loop level instead).

        Earlier 5-attempt × 30s default targeted external upstream's
        per-IP throttling cooldowns; that's no longer the default
        environment per ``feedback_upstream_throttle_ceiling.md``.
        """
        import inspect
        sig = inspect.signature(analyzer.post_json_with_retry)
        attempts = sig.parameters["max_attempts"].default
        assert attempts >= 3, (
            f"default max_attempts={attempts}; need >=3 so a single "
            f"transient blip doesn't kill the chunk on first try"
        )
        assert attempts <= 5, (
            f"default max_attempts={attempts}; >5 burns time on errors "
            f"that won't transiently clear. Bail-fast via the machine-"
            f"class counter is the right path for those."
        )

    def test_default_max_backoff_present(self):
        """``max_backoff_s`` is a named parameter so callers (e.g.
        future per-run override) can tune it. Also guards against a
        well-meaning tweak that removes the cap. Default sized for the
        current internal-network environment."""
        import inspect
        sig = inspect.signature(analyzer.post_json_with_retry)
        assert "max_backoff_s" in sig.parameters, (
            "post_json_with_retry must accept max_backoff_s so unbounded "
            "doubling can't produce multi-minute sleeps"
        )
        default = sig.parameters["max_backoff_s"].default
        assert 3 <= default <= 30, (
            f"max_backoff_s default should land in [3, 30]s for the "
            f"internal-network default; got {default}"
        )

    def test_network_class_consecutive_batch_threshold(self):
        """Network-class consecutive-batch tolerance. Lower than 2
        would bail inside any real hiccup; higher than ~5 keeps
        the operator waiting too long before getting an
        upstream_unstable signal."""
        assert 2 <= analyzer.MAX_CONSECUTIVE_FAILED_BATCHES_NET <= 5, (
            f"MAX_CONSECUTIVE_FAILED_BATCHES_NET="
            f"{analyzer.MAX_CONSECUTIVE_FAILED_BATCHES_NET}; "
            f"keep in [2, 5] for sane internal-network tolerance"
        )

    def test_network_class_cumulative_chunk_threshold(self):
        """Network-class cumulative tolerance. Sized for ~20s of
        bad-network at typical batch sizes — internal blips never
        last that long, so this only fires on real upstream
        breakage."""
        assert analyzer.MAX_CUMULATIVE_FAILED_CHUNKS_NET >= 10, (
            f"MAX_CUMULATIVE_FAILED_CHUNKS_NET="
            f"{analyzer.MAX_CUMULATIVE_FAILED_CHUNKS_NET}; "
            f">=10 keeps brief network bursts from bailing a long run"
        )

    def test_machine_class_threshold_is_fail_fast(self):
        """Machine-class threshold must be SMALL — schema_drift /
        parse_failed / 4xx are bugs that retry won't fix, so we
        bail early to surface the signal. >5 burns operator time
        watching the same error N times before bail."""
        assert analyzer.MAX_CUMULATIVE_FAILED_CHUNKS_MACHINE <= 10, (
            f"MAX_CUMULATIVE_FAILED_CHUNKS_MACHINE="
            f"{analyzer.MAX_CUMULATIVE_FAILED_CHUNKS_MACHINE}; "
            f"machine-class failures don't get better with retries — "
            f"keep <=10 so bugs surface fast"
        )
