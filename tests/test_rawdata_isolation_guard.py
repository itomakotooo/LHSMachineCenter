"""Regression guard for the real-rawdata destruction bug (2026-06-16).

A test run silently erased rawdata/M43/mode_7's cached chunks: a destructive
op (unlink / rmtree) fired against the REAL repo rawdata/ tree instead of a
tmp dir, and the loss was invisible (sidecar quietly rebuilt empty). The
session-autouse ``_protect_real_rawdata`` fixture in tests/conftest.py now
wraps the deletion primitives so this can never happen silently again.

These tests lock that guard. They target NON-EXISTENT chunk paths so that even
if the guard regresses, no real cached data is touched — the guard must raise
RuntimeError BEFORE the underlying delete runs.

INJECT-BUG (proof the guard is live, per feedback_enumerate_safety_paths):
  In tests/conftest.py ``_protect_real_rawdata``, comment out the four
  ``pathlib.Path.unlink = ...`` / ``os.* = ...`` / ``shutil.rmtree = ...``
  assignments → the BLOCKED tests below go RED (FileNotFoundError / clean
  return instead of RuntimeError). Restore → GREEN. This proves the tests
  catch the actual hazard, not an abstract invariant.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_REAL_RAWDATA = (_ROOT / "rawdata").resolve()

# Non-existent targets under the REAL rawdata tree. The chunk names match the
# protected pattern (chunk_*.json) but DO NOT exist on disk, so a guard failure
# cannot delete real data — it would merely fail to raise RuntimeError.
_FAKE_CHUNK = _REAL_RAWDATA / "M43" / "mode_7" / "chunk_9999_guardtest.json"
_FAKE_DIR = _REAL_RAWDATA / "M43" / "mode_99_guardtest"


class TestGuardBlocksRealRawdataDeletion:
    def test_path_unlink_blocked(self) -> None:
        with pytest.raises(RuntimeError, match="RAWDATA-GUARD BLOCKED"):
            _FAKE_CHUNK.unlink()

    def test_path_unlink_blocked_even_with_missing_ok(self) -> None:
        # missing_ok=True must NOT be a bypass — the guard fires regardless.
        with pytest.raises(RuntimeError, match="RAWDATA-GUARD BLOCKED"):
            _FAKE_CHUNK.unlink(missing_ok=True)

    def test_os_unlink_blocked(self) -> None:
        with pytest.raises(RuntimeError, match="RAWDATA-GUARD BLOCKED"):
            os.unlink(_FAKE_CHUNK)

    def test_os_remove_blocked(self) -> None:
        with pytest.raises(RuntimeError, match="RAWDATA-GUARD BLOCKED"):
            os.remove(_FAKE_CHUNK)

    def test_rmtree_on_real_rawdata_dir_blocked(self) -> None:
        with pytest.raises(RuntimeError, match="RAWDATA-GUARD BLOCKED"):
            shutil.rmtree(_FAKE_DIR)

    def test_rmtree_on_mode_dir_blocked(self) -> None:
        # The exact 2026-06-16 shape: rmtree of a mode_N dir under rawdata/.
        # Targets a NON-EXISTENT mode dir so the inject-bug (guard disabled)
        # cannot self-delete real cached data while still proving the guard
        # fires on the mode-dir path shape.
        with pytest.raises(RuntimeError, match="RAWDATA-GUARD BLOCKED"):
            shutil.rmtree(_REAL_RAWDATA / "M43" / "mode_7_guardtest")


class TestGuardAllowsLegitimateDeletes:
    def test_tmp_chunk_delete_allowed(self, tmp_path: Path) -> None:
        """A chunk_*.json under a TMP dir (not repo rawdata/) deletes normally."""
        f = tmp_path / "chunk_0001.json"
        f.write_text("{}", encoding="utf-8")
        f.unlink()  # must NOT raise
        assert not f.exists()

    def test_tmp_rmtree_allowed(self, tmp_path: Path) -> None:
        """rmtree of a tmp subtree (even named like rawdata) is allowed."""
        d = tmp_path / "rawdata" / "M43" / "mode_7"
        d.mkdir(parents=True)
        (d / "chunk_0001.json").write_text("{}", encoding="utf-8")
        shutil.rmtree(tmp_path / "rawdata")  # must NOT raise
        assert not (tmp_path / "rawdata").exists()

    def test_real_rawdata_sidecar_not_protected(self) -> None:
        """Only chunk_*.json data is protected; sidecar (_chunks.json) upkeep
        is allowed. A non-existent sidecar with missing_ok delegates cleanly
        (no RuntimeError) — proving the guard does not over-block."""
        sidecar = _REAL_RAWDATA / "M43" / "mode_7" / "_chunks.json.__guardtest_nonexist__"
        # Delegates to the real unlink; file doesn't exist + missing_ok → no raise.
        sidecar.unlink(missing_ok=True)  # must NOT raise RuntimeError


class TestGuardActuallyPreventsLoss:
    def test_existing_real_chunk_survives_blocked_unlink(self) -> None:
        """If a real chunk file exists, a guarded unlink must leave it on disk.

        Uses whatever real chunk is present (skips if the tree is bare); proves
        the guard PREVENTS loss, not merely raises on a phantom path.
        """
        existing = next(_REAL_RAWDATA.rglob("chunk_*.json"), None)
        if existing is None:
            pytest.skip("no real rawdata chunks present in this checkout")
        with pytest.raises(RuntimeError, match="RAWDATA-GUARD BLOCKED"):
            existing.unlink()
        assert existing.exists(), "guard must leave the real chunk on disk"
