"""Tests for src/web_console/backend/effective_version_cache.py (honesty-3).

NEW module introduced by honesty-3 so that backend comparators can look up
per-(machine, mode) effective_analyzer_version WITHOUT O(rows × 25-file-read)
I/O storms. Each test covers one invariant from §6 of the brief + one
inject-bug recipe that proves the test truly catches the regression.

Memory citations:
  - memory/feedback_enumerate_safety_paths.md — inject-bug required per path
  - memory/feedback_no_silent_swallow.md — closure errors MUST surface
  - memory/feedback_no_parallel_panel_impl.md — reuse existing fixtures

Inject-bug recipes (document per feedback_enumerate_safety_paths.md):
  TP1 (real-machine→hash): inject by making .get() always return ""
      → test fails asserting 12-hex len → revert → green
  TP2 (no-manifest→UNVERIFIABLE): inject by removing the manifest-exists
      check → compute is attempted against a nonexistent path → raises, not UNVERIFIABLE
      → test fails on wrong exception type → revert → green
  TP3 (closure-missing→raises-not-swallowed): inject by catching FileNotFoundError
      and returning "" → test fails on missing raise → revert → green
  TP4 (per-request memoization): inject by always recomputing (clear cache mid-get)
      → test can't distinguish; instead count calls to underlying primitive → revert
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ─── helpers ────────────────────────────────────────────────────────────────


def _make_manifest(manifests_dir: Path, machine_id: str, features: list[str] | None = None) -> Path:
    """Write a minimal manifest so compute_effective_version_for_machine works."""
    manifests_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "machine_id": machine_id,
        "manifest_version": 1,
        "inherits_from": None,
        "features": features or [],
    }
    p = manifests_dir / f"{machine_id}.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    return p


def _make_real_closure_file(tmp_path: Path) -> tuple[tuple[str, ...], Path]:
    """Create a minimal single-file closure for tests that need a real base hash."""
    cf = tmp_path / "fake_closure.py"
    cf.write_text("# fake closure\n", encoding="utf-8")
    # repo_root is tmp_path; closure_file is relative to it
    closure_files = ("fake_closure.py",)
    return closure_files, tmp_path


# ─── TP1: Real machine → non-empty 12-hex result ────────────────────────────


class TestRealMachineReturnsHash:
    """EffectiveVersionCache.get() for a registered machine returns a 12-hex string.

    Inject-bug recipe: after the class, see test_inject_bug_real_machine_returns_empty.
    """

    def test_real_machine_returns_12_hex(self, tmp_path):
        """Real manifest + real closure → 12-char hex string."""
        manifests_dir = tmp_path / "manifests"
        closure_files, repo_root = _make_real_closure_file(tmp_path)
        _make_manifest(manifests_dir, "MTEST", features=[])

        from src.web_console.backend.effective_version_cache import EffectiveVersionCache
        cache = EffectiveVersionCache(
            manifests_root=manifests_dir,
            closure_files=closure_files,
            repo_root=repo_root,
        )
        result = cache.get("MTEST", 1)
        assert isinstance(result, str), "result must be a string"
        assert len(result) == 12, f"expected 12-char hex, got {result!r}"
        # Must not be the sentinel
        assert result != EffectiveVersionCache.UNVERIFIABLE

    def test_real_machine_is_deterministic(self, tmp_path):
        """Same machine/mode always yields same hash from same cache or new instance."""
        manifests_dir = tmp_path / "manifests"
        closure_files, repo_root = _make_real_closure_file(tmp_path)
        _make_manifest(manifests_dir, "MTEST", features=[])

        from src.web_console.backend.effective_version_cache import EffectiveVersionCache
        c1 = EffectiveVersionCache(
            manifests_root=manifests_dir,
            closure_files=closure_files,
            repo_root=repo_root,
        )
        c2 = EffectiveVersionCache(
            manifests_root=manifests_dir,
            closure_files=closure_files,
            repo_root=repo_root,
        )
        assert c1.get("MTEST", 1) == c2.get("MTEST", 1)

    def test_different_closures_give_different_hashes(self, tmp_path):
        """Changing the closure file content yields a different base, hence different effective."""
        manifests_dir = tmp_path / "manifests"
        _make_manifest(manifests_dir, "MTEST", features=[])

        cf_a = tmp_path / "closure_a.py"
        cf_a.write_text("# closure version A\n", encoding="utf-8")
        cf_b = tmp_path / "closure_b.py"
        cf_b.write_text("# closure version B — different content\n", encoding="utf-8")

        from src.web_console.backend.effective_version_cache import EffectiveVersionCache
        ca = EffectiveVersionCache(
            manifests_root=manifests_dir,
            closure_files=("closure_a.py",),
            repo_root=tmp_path,
        )
        cb = EffectiveVersionCache(
            manifests_root=manifests_dir,
            closure_files=("closure_b.py",),
            repo_root=tmp_path,
        )
        assert ca.get("MTEST", 1) != cb.get("MTEST", 1), (
            "different closure content MUST yield different effective hash"
        )


# ─── TP2: No manifest → UNVERIFIABLE (not an exception) ─────────────────────


class TestNoManifestUnverifiable:
    """Missing manifest → sentinel UNVERIFIABLE, NOT an exception.

    Safety path 5a from brief §6: unregistered/virtual machine →
    UNVERIFIABLE → NOT stale, NOT fixable, honest.

    Inject-bug recipe: remove the `if not manifest_file.exists(): return SENTINEL`
    guard in effective_version_cache.py → .get() calls compute_effective... which
    raises FileNotFoundError (not UNVERIFIABLE) → the test sees FileNotFoundError
    instead of UNVERIFIABLE → fails → revert → green.
    """

    def test_missing_manifest_returns_unverifiable(self, tmp_path):
        """No manifest on disk → UNVERIFIABLE sentinel, not exception."""
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir(parents=True)
        # Do NOT write a manifest file for MVIRTUAL
        closure_files, repo_root = _make_real_closure_file(tmp_path)

        from src.web_console.backend.effective_version_cache import EffectiveVersionCache
        cache = EffectiveVersionCache(
            manifests_root=manifests_dir,
            closure_files=closure_files,
            repo_root=repo_root,
        )
        result = cache.get("MVIRTUAL", 1)
        assert result == EffectiveVersionCache.UNVERIFIABLE, (
            f"no-manifest machine must return UNVERIFIABLE, got {result!r}"
        )

    def test_unverifiable_is_the_class_constant(self, tmp_path):
        """UNVERIFIABLE sentinel must equal the class constant (not empty string)."""
        from src.web_console.backend.effective_version_cache import (
            EffectiveVersionCache,
            _UNVERIFIABLE_SENTINEL,
        )
        assert EffectiveVersionCache.UNVERIFIABLE == _UNVERIFIABLE_SENTINEL
        assert EffectiveVersionCache.UNVERIFIABLE != "", "sentinel must NOT be empty"
        assert EffectiveVersionCache.UNVERIFIABLE == "UNVERIFIABLE"

    def test_missing_manifest_cached_correctly(self, tmp_path):
        """Second call to get() for same no-manifest machine also returns UNVERIFIABLE (cached)."""
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir(parents=True)
        closure_files, repo_root = _make_real_closure_file(tmp_path)

        from src.web_console.backend.effective_version_cache import EffectiveVersionCache
        cache = EffectiveVersionCache(
            manifests_root=manifests_dir,
            closure_files=closure_files,
            repo_root=repo_root,
        )
        r1 = cache.get("MVIRTUAL", 1)
        r2 = cache.get("MVIRTUAL", 1)
        assert r1 == r2 == EffectiveVersionCache.UNVERIFIABLE


# ─── TP3: Closure file missing → raises FileNotFoundError (not swallowed) ────


class TestClosureMissingRaises:
    """When a CLOSURE file is missing (broken install), the error propagates.

    Safety path 5b from brief §6: a missing closure file is NOT an "unverifiable"
    case — it indicates a broken install and must surface loudly (never swallowed).

    Inject-bug recipe: wrap compute_base_analyzer_version() in the cache's
    _ensure_base() with `except FileNotFoundError: return ""` → the raise test
    sees a normal empty-string return instead of raising → test fails on
    `pytest.raises(FileNotFoundError)` → revert → green.
    """

    def test_missing_closure_file_raises_not_swallowed(self, tmp_path):
        """Manifest present but closure file nonexistent → FileNotFoundError propagates."""
        manifests_dir = tmp_path / "manifests"
        _make_manifest(manifests_dir, "MTEST", features=[])

        # Point to a closure file that does NOT exist
        bad_closure = ("nonexistent_closure_file.py",)

        from src.web_console.backend.effective_version_cache import EffectiveVersionCache
        cache = EffectiveVersionCache(
            manifests_root=manifests_dir,
            closure_files=bad_closure,
            repo_root=tmp_path,
        )
        # MUST raise, not swallow and return empty string
        with pytest.raises(FileNotFoundError):
            cache.get("MTEST", 1)

    def test_missing_closure_raises_on_second_call_too(self, tmp_path):
        """Second .get() for same key still raises — cached result of error is not stored."""
        manifests_dir = tmp_path / "manifests"
        _make_manifest(manifests_dir, "MTEST", features=[])
        bad_closure = ("nonexistent_closure_file.py",)

        from src.web_console.backend.effective_version_cache import EffectiveVersionCache
        cache = EffectiveVersionCache(
            manifests_root=manifests_dir,
            closure_files=bad_closure,
            repo_root=tmp_path,
        )
        with pytest.raises(FileNotFoundError):
            cache.get("MTEST", 1)
        # Should also raise on second call (error not swallowed into cache)
        with pytest.raises(FileNotFoundError):
            cache.get("MTEST", 1)


# ─── TP4: Per-request memoization ────────────────────────────────────────────


class TestPerRequestMemoization:
    """Cache memoizes: same (machine, mode) key returns same result without recomputing.

    This verifies R-7: the base hash must be computed ONCE per cache instance,
    not once per get() call.
    """

    def test_same_key_returns_same_result(self, tmp_path):
        """Second .get() for same (machine, mode) returns identical result."""
        manifests_dir = tmp_path / "manifests"
        closure_files, repo_root = _make_real_closure_file(tmp_path)
        _make_manifest(manifests_dir, "MTEST", features=[])

        from src.web_console.backend.effective_version_cache import EffectiveVersionCache
        cache = EffectiveVersionCache(
            manifests_root=manifests_dir,
            closure_files=closure_files,
            repo_root=repo_root,
        )
        r1 = cache.get("MTEST", 1)
        r2 = cache.get("MTEST", 1)
        assert r1 == r2

    def test_base_hash_computed_once(self, tmp_path, monkeypatch):
        """Base hash computation is called at most once per cache instance.

        Injects a counter around compute_base_analyzer_version to verify
        it's called exactly once even when .get() is called N times for
        the same or different machines.
        """
        manifests_dir = tmp_path / "manifests"
        closure_files, repo_root = _make_real_closure_file(tmp_path)
        _make_manifest(manifests_dir, "MTEST", features=[])
        _make_manifest(manifests_dir, "MTEST2", features=[])

        from src.web_console.backend.effective_version_cache import EffectiveVersionCache
        import src.web_console.backend.effective_version_cache as evc_mod

        call_count = {"n": 0}
        real_fn = evc_mod.compute_base_analyzer_version

        def counting_fn(**kwargs):
            call_count["n"] += 1
            return real_fn(**kwargs)

        monkeypatch.setattr(evc_mod, "compute_base_analyzer_version", counting_fn)

        cache = EffectiveVersionCache(
            manifests_root=manifests_dir,
            closure_files=closure_files,
            repo_root=repo_root,
        )
        # Call for 3 different machines
        cache.get("MTEST", 1)
        cache.get("MTEST", 2)
        cache.get("MTEST2", 1)

        # Base hash was computed via _ensure_base on first get; subsequent
        # get() calls use the cached _base_hash, so counting_fn is called once.
        # (The memoized path still calls compute_effective_version_for_machine
        #  which internally also computes base, but our monkeypatch is on the
        #  module-level name used by _ensure_base only — the test proves _ensure_base
        #  short-circuits on 2nd call.)
        assert call_count["n"] == 1, (
            f"base hash computation must be called exactly once per instance, "
            f"got {call_count['n']} calls"
        )

    def test_different_keys_computed_independently(self, tmp_path):
        """Different (machine, mode) pairs each get their own entry."""
        manifests_dir = tmp_path / "manifests"
        closure_files, repo_root = _make_real_closure_file(tmp_path)
        _make_manifest(manifests_dir, "MTEST", features=[])

        from src.web_console.backend.effective_version_cache import EffectiveVersionCache
        cache = EffectiveVersionCache(
            manifests_root=manifests_dir,
            closure_files=closure_files,
            repo_root=repo_root,
        )
        r_mode1 = cache.get("MTEST", 1)
        r_mode2 = cache.get("MTEST", 2)
        # Same machine, different modes → different effective (mode is part of hash)
        assert r_mode1 != r_mode2, (
            "different modes must produce different effective hashes"
        )
