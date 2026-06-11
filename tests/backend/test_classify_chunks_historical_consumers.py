"""Regression tests for ticket P1-A4 — _classify_chunks historical semantics.

Contracts tested (from 00_ticket.md §3):

  C2 — Historical-bucket chunks NEVER appear in the default (no-md5-filter)
       analyzer execution paths. Surviving code paths tested here:
         * direct filter logic verification at _classify_chunks output level
         * _prepare_batch_gen_item / run_analyzer_job batch path (R2 addition,
           xfail — current code passes raw chunk_dir to worker without md5 filter)
       (The former POST /api/rawdata/M14/generate-report end-to-end test that
       spied on what the analyzer ingested was removed: that orchestrator path
       spawned the deleted player_impact_analyzer.py. The _classify_chunks
       bucket-separation logic it depended on is still covered directly below.)

  C3 — md5-is-tag invariant: historical bucket chunks survive on disk after
       _classify_chunks and check_rawdata_status are called (read-only).
       _auto_cleanup_for_space only deletes under space pressure (target=0 →
       already above target → no eviction even with historical chunks present).

  C4 — Inject-bug TDD verification is documented in 03_tests.md.
       The inject-bug target for C2 is the line in _run_generate_report:
           usable_entries = classified["kept"] + classified["deletable"]
       Bug: include classified["historical"] → test goes red.
       Revert → green.

  C5 — check_rawdata_status does NOT accept any auto_delete_* parameter.
       Test asserts the function signature (per memory
       feedback_md5_is_a_tag_not_a_destruction_signal.md — the M1|1 incident).

  R2 (Round 2) — Batch path subprocess xfail test.
       _prepare_batch_gen_item computes usable = kept + deletable at the Python
       layer but passes raw chunk_dir (the mode directory) to the worker without
       forwarding --upstream-config-md5 / --upstream-code-md5. The worker's
       analyzer subprocess therefore reads ALL chunks in the directory, including
       historical-md5 ones. The correct behavior (after the fix ticket) is for
       the job dict to include upstream_config_md5 + upstream_code_md5 so the
       worker can forward them as analyzer CLI flags.
       See: 05_critique.md SQ4 / R2 and 03_tests.md §Round 2.

Subprocess context note: all in-process tests (C2/C3/C4/C5) cover the
API-layer filtering logic. The R2 batch test is also in-process — it calls
_prepare_batch_gen_item's prepare_fn directly (no subprocess spawn needed)
because the contract under test is the job dict shape, not the analyzer output.
Subprocess-mode behavior (analyzer consuming only matching-md5 chunks) is
covered by the existing test_analyzer_e2e_md5_filter.py.

Inject-bug discipline (memory feedback_integration_test_argv.md):
  For each critical test, document what mutation makes it go red in 03_tests.md.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENTINEL_RESPONSE = [{"SpinType": 0, "TotalWin": 0, "Credits": 1000, "_marker": "CURRENT"}]
_HISTORICAL_RESPONSE = [{"SpinType": 0, "TotalWin": 0, "Credits": 1000, "_marker": "HISTORICAL"}]


def _make_chunk_entry(
    path: str,
    *,
    config_md5: str = "cfg_CURRENT",
    code_md5: str = "code_CURRENT",
    spins: int = 10_000,
    mtime: float = 1_000_000.0,
) -> dict[str, Any]:
    """Return a synthetic _classify_chunks entry dict."""
    return {
        "path": path,
        "spins": spins,
        "mtime": mtime,
        "config_md5": config_md5,
        "code_md5": code_md5,
    }


def _write_chunk_file(
    path: Path,
    *,
    config_md5: str = "cfg_CURRENT",
    code_md5: str = "code_CURRENT",
    spin_times: int = 10_000,
    robot_count: int = 1,
    response: list | None = None,
) -> Path:
    """Write a minimal rawdata chunk JSON to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "_cache_version": 3,
        "_machine": "M14",
        "_mode": 1,
        "_bet": 1000,
        "_spin_times": spin_times,
        "_robot_count": robot_count,
        "_chunk_index": int(path.stem.split("_")[-1]),
        "_saved_at": "2026-04-01T00:00:00Z",
        "_config_md5": config_md5,
        "_code_md5": code_md5,
        "response": response if response is not None else _SENTINEL_RESPONSE,
    }), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# C5 — check_rawdata_status signature: no auto_delete_* parameter
# ---------------------------------------------------------------------------

class TestCheckRawdataStatusSignature:
    """C5: check_rawdata_status must NOT accept any auto_delete_* parameter.

    Per memory feedback_md5_is_a_tag_not_a_destruction_signal.md:
    Before 2026-04-21 this function took auto_delete_mismatched=True and
    unlinked md5-mismatched chunks directly — that was the M1|1 regression
    path. The parameter must be gone and must NEVER come back.

    Inject-bug: Adding auto_delete_mismatched=False (or any auto_delete_*)
    to check_rawdata_status's signature makes test_no_auto_delete_parameter_in_signature
    fail immediately.
    """

    def test_no_auto_delete_parameter_in_signature(self):
        """check_rawdata_status must have no auto_delete_* parameter."""
        from src.web_console.backend.app import check_rawdata_status

        sig = inspect.signature(check_rawdata_status)
        auto_delete_params = [
            name for name in sig.parameters
            if name.startswith("auto_delete")
        ]
        assert auto_delete_params == [], (
            f"check_rawdata_status must NOT accept any auto_delete_* parameter; "
            f"found: {auto_delete_params}. "
            f"Per M1|1 incident: md5 drift is a classification tag, not a "
            f"destruction signal. Revival of auto_delete_mismatched is a "
            f"critic-flag offense."
        )

    def test_accepted_parameters_are_read_only_in_intent(self):
        """The permitted parameters are: machine, mode, rawdata_root,
        machines_config. All are inputs for computing status, not for
        triggering side-effects."""
        from src.web_console.backend.app import check_rawdata_status

        sig = inspect.signature(check_rawdata_status)
        param_names = set(sig.parameters.keys())
        # These are the only parameters that should exist.
        allowed = {"machine", "mode", "rawdata_root", "machines_config"}
        unexpected = param_names - allowed
        assert not unexpected, (
            f"check_rawdata_status has unexpected parameters: {unexpected}. "
            f"Expected only {allowed}. Any addition that triggers side-effects "
            f"(deletion, mutation) must be blocked."
        )


# ---------------------------------------------------------------------------
# C2 (direct filter logic) — verify _classify_chunks output shape guarantees
# that kept+deletable filter correctly excludes historical
# ---------------------------------------------------------------------------

class TestClassifyChunksBucketSeparation:
    """Verifies that the classifier properly separates historical from
    current-md5 chunks — prerequisite for C2 filtering to work.

    The invariant: for any correct _classify_chunks output, the expression
        usable = classified["kept"] + classified["deletable"]
    naturally excludes all historical entries because the three buckets
    are mutually disjoint (no path appears in more than one bucket).

    Per feedback_enumerate_safety_paths.md: test each path the classifier
    touches separately.
    """

    def test_historical_not_in_kept(self, tmp_path):
        """No chunk in historical bucket appears in kept bucket."""
        from src.web_console.backend.app import _classify_chunks

        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "CURRENT_CFG",
            "codeSummaryMd5": "CURRENT_CODE",
        }]}), encoding="utf-8")
        mode_dir = tmp_path / "rawdata" / "M14" / "mode_1"
        mode_dir.mkdir(parents=True)

        for i in range(1, 3):
            _write_chunk_file(mode_dir / f"chunk_{i:04d}.json",
                              config_md5="CURRENT_CFG", code_md5="CURRENT_CODE")
        for i in range(3, 5):
            _write_chunk_file(mode_dir / f"chunk_{i:04d}.json",
                              config_md5="OLD_CFG", code_md5="OLD_CODE")

        out = _classify_chunks("M14", 1, tmp_path / "rawdata", mc, 100_000)

        kept_paths = {e["path"] for e in out["kept"]}
        historical_paths = {e["path"] for e in out["historical"]}

        assert not (historical_paths & kept_paths), (
            f"Historical chunks appear in kept bucket: "
            f"{historical_paths & kept_paths}"
        )

    def test_historical_not_in_deletable(self, tmp_path):
        """Above-retention historical chunks still land in historical, not deletable."""
        from src.web_console.backend.app import _classify_chunks

        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "CURRENT_CFG",
            "codeSummaryMd5": "CURRENT_CODE",
        }]}), encoding="utf-8")
        mode_dir = tmp_path / "rawdata" / "M14" / "mode_1"
        mode_dir.mkdir(parents=True)

        # Many historical chunks — they exceed any retention quota but must
        # still be classified as historical, not deletable.
        for i in range(1, 20):
            _write_chunk_file(
                mode_dir / f"chunk_{i:04d}.json",
                config_md5="OLD_CFG", code_md5="OLD_CODE",
                spin_times=10_000,
            )

        out = _classify_chunks("M14", 1, tmp_path / "rawdata", mc, 10_000)

        deletable_paths = {e["path"] for e in out["deletable"]}
        historical_paths = {e["path"] for e in out["historical"]}

        assert not (historical_paths & deletable_paths), (
            "Historical chunks must not cross-contaminate deletable bucket "
            "even when they would exceed retention quota."
        )
        assert len(out["historical"]) == 19, (
            f"All 19 old-md5 chunks must land in historical; got {len(out['historical'])}"
        )
        assert out["deletable"] == [], (
            "No current-md5 chunks exist → deletable must be empty"
        )

    def test_buckets_are_disjoint_mixed_scenario(self, tmp_path):
        """All three buckets are mutually disjoint in a mixed scenario.

        8 current chunks (5 kept + 3 deletable) + 4 historical.
        Total = 12 chunks on disk, 3 disjoint buckets.

        Per feedback_enumerate_safety_paths.md: if change applies to N paths,
        assert each.
        """
        from src.web_console.backend.app import _classify_chunks

        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "CFG_CUR",
            "codeSummaryMd5": "CODE_CUR",
        }]}), encoding="utf-8")
        mode_dir = tmp_path / "rawdata" / "M14" / "mode_1"
        mode_dir.mkdir(parents=True)

        # 8 current chunks × 10k spins = 80k. Retention = 50k → 5 kept, 3 deletable.
        for i in range(1, 9):
            _write_chunk_file(
                mode_dir / f"chunk_{i:04d}.json",
                config_md5="CFG_CUR", code_md5="CODE_CUR",
                spin_times=10_000,
            )
        # 4 historical chunks
        for i in range(9, 13):
            _write_chunk_file(
                mode_dir / f"chunk_{i:04d}.json",
                config_md5="CFG_OLD", code_md5="CODE_OLD",
                spin_times=10_000,
            )

        out = _classify_chunks("M14", 1, tmp_path / "rawdata", mc, 50_000)

        kept_paths = {e["path"] for e in out["kept"]}
        deletable_paths = {e["path"] for e in out["deletable"]}
        historical_paths = {e["path"] for e in out["historical"]}

        # Disjoint: no path in more than one bucket
        assert not (kept_paths & deletable_paths), "kept ∩ deletable must be empty"
        assert not (kept_paths & historical_paths), "kept ∩ historical must be empty"
        assert not (deletable_paths & historical_paths), "deletable ∩ historical must be empty"

        assert len(out["kept"]) == 5
        assert len(out["deletable"]) == 3
        assert len(out["historical"]) == 4

    @pytest.mark.parametrize("current_count,historical_count,retention,expected_kept,expected_deletable", [
        # All current within quota: all kept, none deletable
        (3, 2, 100_000, 3, 0),
        # All current over quota: some kept, some deletable
        (10, 3, 50_000, 5, 5),
        # Only historical, no current
        (0, 5, 100_000, 0, 0),
    ])
    def test_parametrized_bucket_sizes(
        self, tmp_path,
        current_count, historical_count, retention,
        expected_kept, expected_deletable,
    ):
        """Parametrized coverage: historical bucket size is never affected
        by kept/deletable quota — it's always exactly historical_count.
        """
        from src.web_console.backend.app import _classify_chunks

        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "CUR_CFG",
            "codeSummaryMd5": "CUR_CODE",
        }]}), encoding="utf-8")
        mode_dir = tmp_path / "rawdata" / "M14" / "mode_1"
        mode_dir.mkdir(parents=True)

        idx = 1
        for _ in range(current_count):
            _write_chunk_file(
                mode_dir / f"chunk_{idx:04d}.json",
                config_md5="CUR_CFG", code_md5="CUR_CODE",
                spin_times=10_000,
            )
            idx += 1
        for _ in range(historical_count):
            _write_chunk_file(
                mode_dir / f"chunk_{idx:04d}.json",
                config_md5="OLD_CFG", code_md5="OLD_CODE",
                spin_times=10_000,
            )
            idx += 1

        out = _classify_chunks("M14", 1, tmp_path / "rawdata", mc, retention)

        assert len(out["historical"]) == historical_count, (
            f"Expected {historical_count} historical chunks; "
            f"got {len(out['historical'])}"
        )
        assert len(out["kept"]) == expected_kept, (
            f"Expected {expected_kept} kept chunks; got {len(out['kept'])}"
        )
        assert len(out["deletable"]) == expected_deletable, (
            f"Expected {expected_deletable} deletable chunks; "
            f"got {len(out['deletable'])}"
        )


# ---------------------------------------------------------------------------
# C3 — md5-is-tag: historical bucket alone does not trigger auto-delete
# ---------------------------------------------------------------------------

class TestHistoricalIsTagNotDestructionSignal:
    """C3: historical bucket chunks survive on disk even after classification.

    _classify_chunks is read-only. The historical tag must not cause any
    automatic unlink in the classification call itself.

    Per memory feedback_md5_is_a_tag_not_a_destruction_signal.md:
    Deletion only happens through _auto_cleanup_for_space (space pressure)
    or explicit per-version DELETE endpoint — never from md5 drift alone.

    Inject-bug: add an unlink() call inside _classify_chunks after building
    the historical list → test_classify_chunks_does_not_delete_historical_files
    goes RED (file gone after classify call).
    """

    def test_classify_chunks_does_not_delete_historical_files(self, tmp_path):
        """Historical chunks remain on disk after _classify_chunks is called."""
        from src.web_console.backend.app import _classify_chunks

        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "NEW_CFG",
            "codeSummaryMd5": "NEW_CODE",
        }]}), encoding="utf-8")
        mode_dir = tmp_path / "rawdata" / "M14" / "mode_1"
        mode_dir.mkdir(parents=True)

        hist_chunk = mode_dir / "chunk_0001.json"
        _write_chunk_file(hist_chunk, config_md5="OLD_CFG", code_md5="OLD_CODE")

        cur_chunk = mode_dir / "chunk_0002.json"
        _write_chunk_file(cur_chunk, config_md5="NEW_CFG", code_md5="NEW_CODE")

        assert hist_chunk.exists(), "Precondition: historical chunk exists before classify"

        out = _classify_chunks("M14", 1, tmp_path / "rawdata", mc, 100_000)

        assert hist_chunk.exists(), (
            "REGRESSION: _classify_chunks deleted the historical chunk! "
            "md5 drift is a classification tag only — no auto-delete. "
            "Per M1|1 incident: historical chunks must stay on disk until "
            "explicit cache-management action."
        )
        assert len(out["historical"]) == 1, "Historical chunk must be classified as historical"

    def test_check_rawdata_status_does_not_delete_historical_files(self, tmp_path):
        """C3: check_rawdata_status must not delete historical-md5 chunks.

        This was the M1|1 regression: before 2026-04-21 start_batch called
        check_rawdata_status which auto-deleted mismatched chunks. This test
        ensures the current code is read-only.

        Inject-bug: restore auto_delete_mismatched logic inside
        check_rawdata_status → files get unlinked → this test goes RED.
        """
        from src.web_console.backend.app import check_rawdata_status

        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "CURRENT_CFG",
            "codeSummaryMd5": "CURRENT_CODE",
        }]}), encoding="utf-8")
        mode_dir = tmp_path / "rawdata" / "M14" / "mode_1"
        mode_dir.mkdir(parents=True)

        hist1 = mode_dir / "chunk_0001.json"
        hist2 = mode_dir / "chunk_0002.json"
        _write_chunk_file(hist1, config_md5="OLD_CFG", code_md5="OLD_CODE")
        _write_chunk_file(hist2, config_md5="OLD_CFG", code_md5="OLD_CODE")

        assert hist1.exists() and hist2.exists(), "Precondition"

        check_rawdata_status(
            "M14", 1,
            rawdata_root=tmp_path / "rawdata",
            machines_config=mc,
        )

        assert hist1.exists(), (
            "check_rawdata_status deleted hist1 — md5 tag must not trigger deletion"
        )
        assert hist2.exists(), (
            "check_rawdata_status deleted hist2 — md5 tag must not trigger deletion"
        )

    @pytest.mark.parametrize("caller_name", [
        "_classify_chunks",
        "check_rawdata_status",
    ])
    def test_read_only_callers_preserve_historical_file(self, tmp_path, caller_name):
        """C3 parametrized: every read-only classifier caller preserves
        historical files.

        Per feedback_enumerate_safety_paths.md: if change applies to N paths
        (here: two read-only classification functions), assert each.

        Inject-bug: add Path.unlink() in either function after historical
        classification → this test goes RED for that caller.
        """
        import src.web_console.backend.app as app_mod

        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "CFG_CURRENT",
            "codeSummaryMd5": "CODE_CURRENT",
        }]}), encoding="utf-8")
        mode_dir = tmp_path / "rawdata" / "M14" / "mode_1"
        mode_dir.mkdir(parents=True)
        hist_chunk = mode_dir / "chunk_0001.json"
        _write_chunk_file(hist_chunk, config_md5="CFG_OLD", code_md5="CODE_OLD")
        cur_chunk = mode_dir / "chunk_0002.json"
        _write_chunk_file(cur_chunk, config_md5="CFG_CURRENT", code_md5="CODE_CURRENT")

        assert hist_chunk.exists(), "Precondition"

        caller = getattr(app_mod, caller_name)
        if caller_name == "_classify_chunks":
            caller("M14", 1, tmp_path / "rawdata", mc, 100_000)
        elif caller_name == "check_rawdata_status":
            caller("M14", 1, rawdata_root=tmp_path / "rawdata", machines_config=mc)

        assert hist_chunk.exists(), (
            f"{caller_name} deleted the historical chunk — "
            f"md5 tag must never trigger file deletion."
        )


# ---------------------------------------------------------------------------
# C3 (supplement) — auto_cleanup_for_space requires space pressure:
# historical alone is insufficient trigger
# ---------------------------------------------------------------------------

class TestAutoCleanupRequiresSpacePressure:
    """C3: _auto_cleanup_for_space only deletes when disk is below target.

    The historical bucket IS in the eviction candidate pool (deletable +
    historical), but eviction only fires when current_free < target_bytes.
    When already above target (target=0), no file is deleted even if
    historical chunks exist — proving md5 tag alone ≠ deletion trigger.

    Inject-bug: remove the `if initial_free >= target_bytes: return` guard
    in _auto_cleanup_for_space → cleanup runs even at target=0 → historical
    files may be unlinked → this test goes RED.
    """

    def test_no_deletion_when_above_target_despite_historical_chunks(self, tmp_path):
        """When disk is already above target_free_gb (target=0.0 → always
        satisfied), historical chunks are NOT deleted even though they're
        in the candidate pool."""
        import src.web_console.backend.app as app_mod

        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "CFG_NEW",
            "codeSummaryMd5": "CODE_NEW",
        }]}), encoding="utf-8")
        rawdata = tmp_path / "rawdata"
        mode_dir = rawdata / "M14" / "mode_1"
        mode_dir.mkdir(parents=True)

        hist_chunk = mode_dir / "chunk_0001.json"
        _write_chunk_file(hist_chunk, config_md5="CFG_OLD", code_md5="CODE_OLD")

        assert hist_chunk.exists(), "Precondition: historical chunk exists"

        # target_free_gb=0 means we're always above target → no eviction.
        result = app_mod._auto_cleanup_for_space(
            rawdata_root=rawdata,
            machines_config=mc,
            retention=100_000,
            target_free_gb=0.0,
        )

        assert result["reached_target"] is True, (
            "With target_free_gb=0, auto_cleanup must report already_reached"
        )
        assert result["deleted_files"] == 0, (
            "No files should be deleted when already above target"
        )
        assert hist_chunk.exists(), (
            "Historical chunk must survive when no space pressure exists — "
            "historical tag alone does not trigger deletion."
        )


# ---------------------------------------------------------------------------
# R2 — Batch path: _prepare_batch_gen_item job dict must carry md5 filter
#
# KNOWN BUG (P1-A4 R1 critic finding, SQ4): The current implementation
# passes chunk_dir (raw mode directory) to the worker WITHOUT md5 filter
# flags. The worker forwards this as --from-cache <chunk_dir> with no
# --upstream-config-md5 / --upstream-code-md5, so the analyzer subprocess
# reads ALL chunks in the directory, including historical-md5 ones.
#
# The tests here are marked @pytest.mark.xfail because they assert the
# FUTURE correct behavior. They will pass once the fix is applied:
#   Option A: job["chunk_dir"] is a filtered list of per-chunk paths
#   Option B: job includes "upstream_config_md5" + "upstream_code_md5" keys
#             (the worker then forwards --upstream-config-md5 / --upstream-code-md5
#             to the analyzer CLI).
#
# Approach A (per 03_tests.md R2 section):
#   Write test as ASSERTION (will FAIL today -> expose bug).
#   Mark @pytest.mark.xfail with clear reason.
#   When the bug is fixed (separate ticket), remove xfail.
#
# Inject-bug discipline for xfail tests (memory feedback_integration_test_argv.md):
#   The "bug injection" is the CURRENT production code. The xfail documents
#   the gap. When the fix lands, the test transitions from xfail (expected-fail)
#   to pass. Removing the xfail marker IS the inject-bug verification step for
#   the fix PR -- the test goes RED if the fix is incomplete, GREEN when correct.
#   See 03_tests.md Round 2 section for the full inject-bug scenario description.
# ---------------------------------------------------------------------------

class TestBatchPathHistoricalFilterGap:
    """R2: _prepare_batch_gen_item / run_analyzer_job must not feed historical
    chunks to the analyzer subprocess. Currently they do.

    The test captures the job dict built by _prepare_batch_gen_item (via the
    BatchGenerateManager.prepare_fn hook) and asserts the CORRECT future
    invariant: the job includes md5 filter keys so the worker can forward them
    to the analyzer CLI. Today both assertions fail (xfail).

    Why in-process: the job dict shape is the contract. We do not need to spawn
    an actual analyzer subprocess -- the bug is in the job dict construction,
    not in the analyzer's chunk-reading logic (which is already covered by
    test_analyzer_e2e_md5_filter.py). Catching the wrong job dict is sufficient
    and faster than an e2e subprocess run.

    Per memory feedback_subprocess_import_suicide_and_module_globals.md:
    test must prove the Python-layer variable (usable = kept+deletable) is
    actually forwarded to the subprocess, not just computed and dropped.
    """

    @pytest.fixture
    def _app_and_prepare_fn(self, tmp_path: Path):
        """Create the app and intercept BatchGenerateManager to capture
        the prepare_fn closure. Returns (prepare_fn, rawdata_root, mode_dir).

        Strategy: monkeypatch BatchGenerateManager.__init__ to capture the
        prepare_fn argument before app creation completes. The prepare_fn is
        _prepare_batch_gen_item_wrapper, which calls _prepare_batch_gen_item.
        We call it directly -- no threading or ProcessPoolExecutor needed.
        """
        import src.web_console.backend.app as app_mod

        machines_config = tmp_path / "machines.json"
        machines_config.write_text(json.dumps({"machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "cfg_CURRENT",
            "codeSummaryMd5": "code_CURRENT",
        }]}), encoding="utf-8")

        rawdata_root = tmp_path / "rawdata"
        mode_dir = rawdata_root / "M14" / "mode_1"
        mode_dir.mkdir(parents=True, exist_ok=True)

        # Write CURRENT-md5 chunks
        for i in range(1, 3):
            _write_chunk_file(
                mode_dir / f"chunk_{i:04d}.json",
                config_md5="cfg_CURRENT", code_md5="code_CURRENT",
            )
        # Write HISTORICAL-md5 chunks -- these must NOT reach the analyzer
        for i in range(3, 6):
            _write_chunk_file(
                mode_dir / f"chunk_{i:04d}.json",
                config_md5="cfg_OLD", code_md5="code_OLD",
                response=_HISTORICAL_RESPONSE,
            )

        # Capture prepare_fn by intercepting BatchGenerateManager.__init__
        captured: dict = {}
        _real_init = app_mod.BatchGenerateManager.__init__

        # Phase 2 deploy refactor removed `ops` param from
        # BatchGenerateManager.__init__ (per-item registry GENERATING
        # replaces it). Accept variadic to stay version-tolerant.
        def _capturing_init(self_mgr, prepare_fn, finalize_fn, *args, **kwargs):
            captured["prepare_fn"] = prepare_fn
            _real_init(self_mgr, prepare_fn, finalize_fn, *args, **kwargs)

        state_dir = tmp_path / "state"
        (state_dir / "progress").mkdir(parents=True)
        fake_analyzer = tmp_path / "fake_analyzer.py"
        fake_analyzer.write_text("import sys; sys.exit(0)\n", encoding="utf-8")

        with patch.object(app_mod.BatchGenerateManager, "__init__", _capturing_init):
            app_mod.create_app(
                state_dir=state_dir,
                reports_root=tmp_path / "reports",
                cache_root=tmp_path / "cache",
                machines_config=machines_config,
                analyzer_path=fake_analyzer,
                rawdata_root=rawdata_root,
            )

        assert "prepare_fn" in captured, (
            "BatchGenerateManager.__init__ was not called during create_app -- "
            "test setup is broken."
        )
        return captured["prepare_fn"], rawdata_root, mode_dir

    def test_batch_job_dict_includes_md5_filter_keys(self, _app_and_prepare_fn, tmp_path):
        """C2 batch path (xfail): the job dict built by _prepare_batch_gen_item
        must include upstream_config_md5 + upstream_code_md5 so the worker can
        forward them to the analyzer as CLI filter flags.

        Today the job dict has only chunk_dir (raw mode directory) + max_chunks,
        with no md5 filter keys. This means the analyzer subprocess reads every
        chunk in the directory regardless of md5.

        Inject-bug discipline: the CURRENT code IS the bug. This xfail documents
        the gap. When the fix is applied:
          1. The job dict will include "upstream_config_md5" + "upstream_code_md5"
          2. This test transitions from xfail-FAIL to xfail-PASS -> remove xfail
          3. Remove xfail and the test becomes a GREEN regression guard forever.
        """
        prepare_fn, rawdata_root, mode_dir = _app_and_prepare_fn
        prepared = prepare_fn("M14", 1)
        job = prepared["job"]

        # CORRECT future invariant (both keys must be present)
        missing_keys = [k for k in ("upstream_config_md5", "upstream_code_md5")
                        if k not in job]
        assert not missing_keys, (
            f"REGRESSION (batch path): job dict is missing md5 filter keys: "
            f"{missing_keys}. Without these, the batch worker cannot forward "
            f"--upstream-config-md5 / --upstream-code-md5 to the analyzer CLI. "
            f"The analyzer will read ALL chunks from chunk_dir={job.get('chunk_dir')!r} "
            f"including historical-md5 ones, violating brief S3 C2. "
            f"Full job keys: {sorted(job.keys())}"
        )

    def test_batch_job_chunk_dir_does_not_contain_historical_chunks(
        self, _app_and_prepare_fn, tmp_path
    ):
        """C2 batch path: the directory the job hands the engine must not
        contain any historical-md5 chunks at the time the job is built.

        FIXED (the long-deferred "Fix A"): since the batch md5-scope port of
        fd6b507, _prepare_batch_gen_item hardlinks the usable (current-md5)
        selection into cache/_gen_scope/<run_id> and puts THAT in
        job["chunk_dir"] whenever the mode dir holds extra chunks — the
        SpinType-native engine reads every chunk in chunk_dir and has no CLI
        filter, so directory-level scoping is the only enforcement. The
        xfail marker was removed when the fix landed (this test is now the
        hard regression guard; see also tests/backend/test_batch_gen_md5_scope.py).
        """
        prepare_fn, rawdata_root, mode_dir = _app_and_prepare_fn
        prepared = prepare_fn("M14", 1)
        job = prepared["job"]
        chunk_dir = Path(job["chunk_dir"])

        # Enumerate all chunk files the analyzer will see when given this chunk_dir
        all_chunks_in_dir = sorted(chunk_dir.glob("chunk_*.json"))
        historical_chunks_in_dir = []
        for chunk_path in all_chunks_in_dir:
            try:
                data = json.loads(chunk_path.read_text(encoding="utf-8"))
                config_md5 = data.get("_config_md5", "")
                code_md5 = data.get("_code_md5", "")
                if config_md5 != "cfg_CURRENT" or code_md5 != "code_CURRENT":
                    historical_chunks_in_dir.append(str(chunk_path))
            except Exception:
                pass

        assert not historical_chunks_in_dir, (
            f"REGRESSION (batch path): chunk_dir={str(chunk_dir)!r} contains "
            f"{len(historical_chunks_in_dir)} historical-md5 chunk(s) that the "
            f"analyzer subprocess will read (no md5 filter is applied). "
            f"Historical chunks: {historical_chunks_in_dir}. "
            f"max_chunks={job.get('max_chunks')} limits count but not md5-selectivity. "
            f"Brief S3 C2: any code path that calls equivalent analyzer execution "
            f"must contain zero historical-bucket chunks."
        )
