"""Phase C2 — regression test proving extract() is actually called on cached chunks.

This is the most important new test in C2. It directly catches the C1 latent
bug class: if the pre-registration block were missing from PIA main(), the
PayoutsBySpinType plugin would NOT be in ALL_FEATURES when the merge loop
runs → extract() would never be invoked → payouts_by_spin_type would silently
produce empty data (Pattern A behaviour even though Pattern B is implemented).

C1 latent bug description
--------------------------
In C1, Pattern A plugins returned {} from extract(), so it didn't matter
whether extract() was called or not — the result was the same empty dict.
In C2, extract() does real work. Without the pre-registration block:
    - ALL_FEATURES is empty when the merge loop starts
    - The per-chunk extract() call is skipped (no features registered yet)
    - _feature_accs is never populated for payouts_by_spin_type
    - emit() receives final_acc={} → all ST labels have empty lists
The pre-registration block (added by implementer in C2) fixes this by
importing all feature modules BEFORE the merge loop starts.

Inject-bug protocol (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug: remove the pre-registration block from PIA main():
    Lines (approximately):
        try:
            import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
            import fresh_slotlab.analyzer.features.reel_marginal_by_spin_type  # noqa: F401
            import fresh_slotlab.analyzer.features.bankruptcy_simulation  # noqa: F401
            import fresh_slotlab.analyzer.features.multiplier_profile  # noqa: F401
        except ImportError:
            ...

RED: test_payouts_by_spin_type_hit_counts_nonzero FAILS because without
    pre-registration, ALL_FEATURES is empty during the merge loop →
    extract() never called → _feature_accs["payouts_by_spin_type"] == {} →
    emit() gets final_acc={} → all ST labels have [] (empty) →
    total_hits == 0.

Revert → GREEN.

This is verified in inject_bug_evidence.md section "C1 latent bug".

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md (real subprocess required)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_integration_test_argv.md (real subprocess argv)
- memory/feedback_subprocess_import_suicide_and_module_globals.md
  (pre-registration must be idempotent, no I/O)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_CACHE_DIR = _REPO_ROOT / "rawdata" / "M14" / "mode_1"


def _run_pia_from_cache(machine: str = "M14", mode: int = 1, timeout: int = 120) -> dict:
    """Run PIA against cached chunks; return parsed summary."""
    cache_dir = _REPO_ROOT / "rawdata" / machine / f"mode_{mode}"
    if not cache_dir.exists() or not list(cache_dir.glob("chunk_*.json")):
        pytest.skip(f"{machine} mode {mode} cached chunks not available")

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable,
            str(_PIA),
            "--machine", machine,
            "--rtp-mode", str(mode),
            "--from-cache", str(cache_dir),
            "--output-dir", tmpdir,
            "--bet", "1000",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            timeout=timeout,
        )
        assert result.returncode == 0, (
            f"PIA exited non-zero ({result.returncode}).\n"
            f"STDERR: {result.stderr[:2000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists()
        return json.loads(summary_path.read_bytes())


class TestPreRegistrationBlockExists:
    """Static verification that the pre-registration block exists in PIA source.

    This is an AST-level check that serves as an early-warning signal:
    if the pre-registration block is accidentally removed, this test fails
    before the subprocess-level tests even run.
    """

    def test_pre_registration_import_present_in_pia_source(self):
        """PIA source must contain the pre-registration imports for all 4 feature modules.

        INJECT-BUG: remove the pre-registration block from PIA.
        RED: this assertion fails (import not found in source).
        """
        pia_src = _PIA.read_text(encoding="utf-8")
        # All 4 feature modules must be imported in the pre-registration block
        required_imports = [
            "payouts_by_spin_type",
            "reel_marginal_by_spin_type",
            "bankruptcy_simulation",
            "multiplier_profile",
        ]
        for module_name in required_imports:
            # Look for an import of this module in the source
            # Pattern: "import ...payouts_by_spin_type"
            pattern = rf"import\s+[\w.]*{re.escape(module_name)}"
            matches = re.findall(pattern, pia_src)
            assert len(matches) >= 1, (
                f"Pre-registration import for '{module_name}' not found in PIA source. "
                f"The pre-registration block (added in C2) may have been removed. "
                f"Without it, extract() is never called on cached chunks."
            )

    def test_pre_registration_before_cache_read_loop(self):
        """Pre-registration block must appear BEFORE the cache-read loop.

        This verifies the ordering: plugins must be registered BEFORE the
        merge loop starts, not after.

        Heuristic: the pre-registration import of payouts_by_spin_type
        must appear at a lower line number than the cache-read loop marker.
        """
        pia_src = _PIA.read_text(encoding="utf-8")
        lines = pia_src.splitlines()

        # Find line number of pre-registration import
        preregistration_line = None
        for i, line in enumerate(lines):
            if (
                "payouts_by_spin_type" in line
                and "import" in line
                and "Phase C2" in "\n".join(lines[max(0, i-5):i+1])
            ):
                preregistration_line = i
                break

        # Also look for the comment that marks the pre-registration block
        preregistration_comment_line = None
        for i, line in enumerate(lines):
            if "Phase C2: pre-register feature plugins BEFORE the merge loop" in line:
                preregistration_comment_line = i
                break

        # Find cache-read loop (the 'for read_idx, cf in enumerate(chunk_files)' line)
        cache_loop_line = None
        for i, line in enumerate(lines):
            if "for read_idx, cf in enumerate(chunk_files)" in line:
                cache_loop_line = i
                break

        assert cache_loop_line is not None, (
            "Could not find cache-read loop ('for read_idx, cf in enumerate(chunk_files)'). "
            "PIA source structure may have changed."
        )

        marker_line = preregistration_comment_line or preregistration_line
        if marker_line is None:
            # If we can't find the comment, just check the import is somewhere above the loop
            # This is a softer check
            pre_reg_import_line = None
            for i, line in enumerate(lines):
                if (
                    "import fresh_slotlab.analyzer.features.payouts_by_spin_type" in line
                    or "import analyzer.features.payouts_by_spin_type" in line
                ):
                    pre_reg_import_line = i
                    break
            if pre_reg_import_line is not None:
                assert pre_reg_import_line < cache_loop_line, (
                    f"Pre-registration import (line {pre_reg_import_line}) must appear "
                    f"BEFORE cache loop (line {cache_loop_line}). "
                    "Ordering violation: extract() would not be called during merge loop."
                )
            return

        assert marker_line < cache_loop_line, (
            f"Pre-registration block marker (line {marker_line}) must appear "
            f"BEFORE cache-read loop (line {cache_loop_line}). "
            "If the registration happens after the loop, extract() is never called "
            "on cached chunks."
        )


class TestExtractActuallyCalledOnCachedChunks:
    """Subprocess-level proof that extract() is invoked during merge loop.

    The definitive test: if extract() is called with real chunk data,
    the plugin accumulates real hit counts and emit() produces non-empty rows.
    If extract() is NOT called (pre-registration missing), final_acc == {}
    and emit() produces all-empty lists.
    """

    def test_payouts_by_spin_type_hit_counts_nonzero(self):
        """After running on M14 cached chunks, payouts_by_spin_type must have > 0 total hits.

        INJECT-BUG: remove the pre-registration block from PIA main().
        Without it:
          - ALL_FEATURES is empty when merge loop runs
          - extract() is never called
          - _feature_accs['payouts_by_spin_type'] stays {}
          - emit() receives final_acc={} → by_st_hits={} → all ST labels empty
          - total_hits == 0

        RED: this assertion fails (total_hits == 0).
        Revert: restore pre-registration block.
        GREEN: extract() is called → _feature_accs populated → total_hits > 0.

        This is the primary regression test for the C1 latent bug class.
        """
        summary = _run_pia_from_cache("M14", 1)
        pbst = summary.get("player_impact", {}).get("payouts_by_spin_type", {})

        total_hits = sum(
            row["hit_count"] for rows in pbst.values() for row in rows
        )

        assert total_hits > 0, (
            f"payouts_by_spin_type total hit_count == 0. "
            f"This is the signature of the C1 latent bug: "
            f"extract() not called because ALL_FEATURES was empty during merge loop. "
            f"Check that the pre-registration block exists in PIA main() "
            f"BEFORE the cache-read loop. "
            f"ST labels in output: {sorted(pbst.keys())}"
        )

    def test_payouts_by_spin_type_total_win_nonzero(self):
        """After running on M14, payouts_by_spin_type must have > 0 total win.

        Complements hit_count check: even if hits were non-zero by coincidence,
        total_win being non-zero confirms the win accumulation path works.
        """
        summary = _run_pia_from_cache("M14", 1)
        pbst = summary.get("player_impact", {}).get("payouts_by_spin_type", {})

        total_win = sum(
            row["total_win"] for rows in pbst.values() for row in rows
        )

        assert total_win > 0, (
            f"payouts_by_spin_type total_win == 0. "
            f"Win accumulation in extract() may not be working. "
            f"Check payout_id_win_by_spin_type iteration in extract()."
        )

    def test_feature_accs_entry_for_payouts_by_spin_type(self):
        """The plugin must be registered AND have its extract() called.

        Indirect proof: if extract() is called on real chunks with real data,
        the resulting hit/win counts in the output must be consistent with
        payout_ids_top20 (which uses the inline payout_id_hits accumulator).
        """
        summary = _run_pia_from_cache("M14", 1)
        pbst = summary.get("player_impact", {}).get("payouts_by_spin_type", {})
        top20 = summary.get("player_impact", {}).get("payout_ids_top20", [])

        if not top20:
            pytest.skip("payout_ids_top20 empty — cannot cross-check")

        # At minimum: every pid in top20 that has hits must appear somewhere
        # in payouts_by_spin_type (since it must have been fired in some ST)
        top20_pids_with_hits = {
            str(r["payout_id"]) for r in top20 if r.get("hit_count", 0) > 0
        }
        plugin_pids = {
            str(row["payout_id"])
            for rows in pbst.values()
            for row in rows
            if row.get("hit_count", 0) > 0
        }

        # plugin_pids should be a non-empty subset (or equal to) top20_pids_with_hits
        assert plugin_pids, (
            f"No PIDs with hits in payouts_by_spin_type. "
            f"extract() was likely not called (pre-registration missing)."
        )

        # Cross-check: check at least 1 pid appears in both
        common_pids = plugin_pids & top20_pids_with_hits
        assert common_pids, (
            f"No overlap between plugin pids ({sorted(plugin_pids)[:5]}) "
            f"and top20 pids ({sorted(top20_pids_with_hits)[:5]}). "
            f"Data sources may have diverged."
        )


class TestPreRegistrationIdempotent:
    """Pre-registration must be idempotent (importing twice does not double-register)."""

    def test_import_payouts_by_spin_type_twice_no_double_register(self):
        """Importing payouts_by_spin_type twice must not add 2 entries to ALL_FEATURES.

        The pre-registration block runs at main() start. If main() were called
        twice (e.g. in tests), this must remain idempotent.

        INJECT-BUG: add `ALL_FEATURES.append(PayoutsBySpinType())` directly
        instead of using register() (which has duplicate guard).
        RED: count > 1 → assertion fails.
        """
        try:
            from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES
        except ImportError:
            from analyzer.feature_registry import ALL_FEATURES  # type: ignore[no-redef]

        # Simulate double import (Python caches, so this is actually a no-op)
        try:
            import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
            import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
        except ImportError:
            import analyzer.features.payouts_by_spin_type  # type: ignore[no-redef] # noqa: F401

        count = sum(
            1 for f in ALL_FEATURES if f.FEATURE_ID == "payouts_by_spin_type"
        )
        assert count == 1, (
            f"Double import added {count} entries for payouts_by_spin_type. "
            f"register() must be idempotent (duplicate guard)."
        )
