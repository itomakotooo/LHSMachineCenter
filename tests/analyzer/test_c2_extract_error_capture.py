"""Phase C2 — tests for _extract_error_* capture mechanism and graceful degradation.

Verifies that when a plugin's extract() raises an exception:
1. The error is captured in feature_errors (not silently swallowed).
2. Other plugins still emit normally.
3. The summary is still written to disk (rc == 0, not a fatal crash).

This tests the `memory/feedback_no_silent_swallow.md` contract for the
extract/reduce phase specifically.

Mechanism tested (PIA code path, from-cache path)
-------------------------------------------------
In the from-cache merge loop:
    for _fc_feat in _fc_features:
        try:
            _fc_this = _fc_feat.extract(_fc_parse_state, rec)
            _feature_accs[_fc_feat.FEATURE_ID] = _fc_feat.reduce(...)
        except Exception as _fc_exc:
            # extract() / reduce() error: persist diagnostic
            _feature_accs.setdefault(
                f"_extract_error_{_fc_feat.FEATURE_ID}", []
            ).append(str(_fc_exc))

After the emit loop:
    for _feat_key, _feat_errs in _feature_accs.items():
        if _feat_key.startswith("_extract_error_") and _feat_errs:
            summary["feature_errors"][f"extract_{_fid}"] = ...

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug: remove the _extract_error_* accumulator append in PIA:
    Change:
        _feature_accs.setdefault(f"_extract_error_{_fc_feat.FEATURE_ID}", []).append(str(_fc_exc))
    To:
        pass  # silently swallow
RED: test_feature_errors_captured fails (feature_errors absent or empty).
Revert → GREEN.

This DIRECTLY proves that removing the capture mechanism (the C1 bug class
that critic flagged: "outer except Exception: pass swallowing Pattern-B errors")
would break the test.

Memory files cited
------------------
- memory/feedback_no_silent_swallow.md (diagnostic must be persisted to disk)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_perf_claim_needs_e2e_event_stream.md (real subprocess)
- memory/feedback_integration_test_argv.md (real subprocess argv)
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_PIA_PLUGIN = _REPO_ROOT / "fresh_slotlab" / "analyzer" / "features" / "payouts_by_spin_type.py"
_CACHE_DIR = _REPO_ROOT / "rawdata" / "M14" / "mode_1"


@pytest.fixture(scope="module")
def m14_has_chunks() -> bool:
    """Check if M14 cached chunks are available."""
    return bool(
        _CACHE_DIR.exists() and list(_CACHE_DIR.glob("chunk_*.json"))
    )


class TestExtractErrorInSubprocess:
    """Inject an extract() failure via patched plugin file and run real subprocess.

    The approach:
    1. Temporarily monkey-patch payouts_by_spin_type.py's extract() to raise.
    2. Run the PIA subprocess against M14 cached chunks.
    3. Assert the error is captured in feature_errors.
    4. Assert other plugins still emit (bankruptcy_simulation, etc. present).
    5. Assert rc == 0 (extract error is NOT fatal — only topo-sort errors are).
    """

    def _run_pia_with_injected_extract(
        self,
        inject_code: str,
        tmpdir: str,
    ) -> tuple[int, dict]:
        """Run PIA after writing a patched plugin file; return (rc, summary)."""
        # Read original plugin source
        original_src = _PIA_PLUGIN.read_text(encoding="utf-8")

        # Write patched version
        # We inject a raise into extract() by wrapping the return statement
        patched_src = original_src.replace(
            "        return {\"by_st_hits\": by_st_hits, \"by_st_win\": by_st_win}",
            inject_code,
        )
        if patched_src == original_src:
            pytest.skip(
                "Could not inject extract() failure — plugin source layout may have changed. "
                "Check payouts_by_spin_type.py extract() return statement."
            )

        try:
            _PIA_PLUGIN.write_text(patched_src, encoding="utf-8")
            cmd = [
                sys.executable,
                str(_PIA),
                "--machine", "M14",
                "--rtp-mode", "1",
                "--from-cache", str(_CACHE_DIR),
                "--output-dir", tmpdir,
                "--bet", "1000",
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(_REPO_ROOT),
                timeout=120,
            )
        finally:
            # Always restore original
            _PIA_PLUGIN.write_text(original_src, encoding="utf-8")

        summary_path = Path(tmpdir) / "player_impact_summary.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_bytes())
        else:
            summary = {}
        return result.returncode, summary

    def test_extract_error_captured_in_feature_errors(self, m14_has_chunks):
        """extract() exception must appear in summary['feature_errors'], not be swallowed.

        INJECT-BUG (primary): remove the _extract_error_ append in PIA:
            Change: _feature_accs.setdefault(f"_extract_error_...", []).append(...)
            To:     pass
        RED: feature_errors absent or empty → assertion fails.
        Revert → GREEN.
        """
        if not m14_has_chunks:
            pytest.skip("M14 cached chunks not available")

        inject_code = (
            "        raise ValueError("
            "\"TEST_INJECT: extract() forced failure for error capture test\")"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            rc, summary = self._run_pia_with_injected_extract(inject_code, tmpdir)

        # rc must be 0 — extract errors are per-feature degradation, not fatal
        assert rc == 0, (
            f"PIA exited with rc={rc}. extract() errors must NOT be fatal "
            f"(only topo-sort errors produce non-zero rc)."
        )

        # feature_errors must be present and contain our injected error
        fe = summary.get("feature_errors", {})
        assert fe, (
            f"feature_errors must be populated when extract() raises. "
            f"Got: {fe}. "
            "This proves feedback_no_silent_swallow.md invariant is maintained."
        )

        # The error key must mention payouts_by_spin_type
        pbst_error_keys = [k for k in fe if "payouts_by_spin_type" in k]
        assert pbst_error_keys, (
            f"feature_errors has no key mentioning payouts_by_spin_type. "
            f"Got keys: {sorted(fe.keys())}. "
            "The _extract_error_ capture mechanism may be broken."
        )

        # The error message must mention our inject text
        for key in pbst_error_keys:
            assert "TEST_INJECT" in fe[key] or "ValueError" in fe[key], (
                f"Error message doesn't mention TEST_INJECT or ValueError: {fe[key]!r}"
            )

    def test_other_plugins_emit_despite_extract_error(self, m14_has_chunks):
        """When extract() fails for payouts_by_spin_type, other plugins must still emit.

        This verifies that one plugin's extract() crash does NOT cascade to kill
        all other plugins. The emit loop runs all registered plugins independently.
        """
        if not m14_has_chunks:
            pytest.skip("M14 cached chunks not available")

        inject_code = (
            "        raise RuntimeError("
            "\"TEST_INJECT: extract() cascade test\")"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            rc, summary = self._run_pia_with_injected_extract(inject_code, tmpdir)

        assert rc == 0, f"PIA must not crash on extract() error. rc={rc}"

        pi = summary.get("player_impact", {})
        # bankruptcy_simulation is a Pattern B plugin that runs in emit loop —
        # its data should still be present despite payouts_by_spin_type extract failure.
        assert "bankruptcy_simulation" in pi, (
            f"bankruptcy_simulation missing from player_impact — "
            f"other plugin's extract() failure cascaded incorrectly. "
            f"Got keys: {sorted(pi.keys())}"
        )

        # multiplier_profile (Pattern A) should also be present
        assert "multiplier_profile" in pi, (
            f"multiplier_profile missing — Plugin isolation broken. "
            f"Got keys: {sorted(pi.keys())}"
        )

    def test_summary_written_to_disk_despite_extract_error(self, m14_has_chunks):
        """Summary JSON must be written to disk even when extract() raises.

        Per feedback_no_silent_swallow.md: degraded output (missing one plugin's
        data) is better than no output at all.
        """
        if not m14_has_chunks:
            pytest.skip("M14 cached chunks not available")

        inject_code = (
            "        raise IOError("
            "\"TEST_INJECT: disk write test\")"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            rc, summary = self._run_pia_with_injected_extract(inject_code, tmpdir)
            summary_path = Path(tmpdir) / "player_impact_summary.json"
            assert summary_path.exists(), (
                "player_impact_summary.json must exist even when extract() raised. "
                "extract() errors are degradation, not fatal."
            )

        assert rc == 0, f"PIA must exit 0 even with extract() error. rc={rc}"
        # Summary must have the core RTP fields
        assert "rtp" in summary, (
            "summary['rtp'] missing despite extract() error. "
            "Core pipeline must complete even if one plugin's extract() failed."
        )


class TestExtractErrorCleanup:
    """_extract_error_ keys must not leak into the final summary JSON."""

    def test_no_extract_error_keys_on_success_path(self, m14_has_chunks):
        """On success path (no extract errors), _extract_error_* keys must not appear.

        These are internal to _feature_accs and must be cleaned up or simply
        not surfaced if empty.
        """
        if not m14_has_chunks:
            pytest.skip("M14 cached chunks not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [
                sys.executable,
                str(_PIA),
                "--machine", "M14",
                "--rtp-mode", "1",
                "--from-cache", str(_CACHE_DIR),
                "--output-dir", tmpdir,
                "--bet", "1000",
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(_REPO_ROOT),
                timeout=120,
            )
            assert result.returncode == 0
            summary_path = Path(tmpdir) / "player_impact_summary.json"
            summary = json.loads(summary_path.read_bytes())

        # _extract_error_* keys must not appear anywhere in the summary
        for k in summary:
            assert "_extract_error_" not in k, (
                f"_extract_error_ key leaked into final summary: {k!r}"
            )
        pi = summary.get("player_impact", {})
        for k in pi:
            assert "_extract_error_" not in k, (
                f"_extract_error_ key leaked into player_impact: {k!r}"
            )

        # On success path, feature_errors must be absent (or empty)
        fe = summary.get("feature_errors", {})
        assert not fe, (
            f"feature_errors populated on success path: {fe}. "
            "Expected empty (no extract errors)."
        )
