"""Honesty-1 safety regression: `cleanup_old_reports` must NEVER delete a
report version or DB run row *because* its analyzer_version mismatches the
current one.

Spec: session_artifacts/_impl/phase_honesty_1/brief.md §2.1/§2.2/§3/§4
      session_artifacts/_arch_honesty_isolation/07_decision.md §3 R-2

Why this file exists
--------------------
The fleet analyzer shows 策划 a per-machine freshness/staleness badge. The
upcoming honesty cutover redefines the freshness signal so it is honest, which
marks EVERY machine stale exactly once at the changeover. Before honesty-1 the
`POST /api/reports/cleanup` endpoint (`cleanup_old_reports`) deleted every
analyzer-stale version from disk (`shutil.rmtree`) AND deleted their DB rows,
PLUS a DB "second pass" that dropped every run row whose
``analyzer_version != current`` with no disk coupling. If that coupling stayed,
the cutover could wipe the whole fleet's reports. honesty-1 decouples the
verdict from deletion: a version/staleness tag is a classification signal, not a
destruction trigger (`memory/feedback_md5_is_a_tag_not_a_destruction_signal.md`).

Per `memory/feedback_enumerate_safety_paths.md` (the M1|1 million-spin loss was
a missed *third* path), each defanged deletion path gets its own regression test
proven with inject-bug -> red -> revert -> green.

Defanged paths under test
-------------------------
  P1 (disk rmtree)      `cleanup_old_reports` deleted `stale_versions` from disk
                        (former app.py:11016-11041 `shutil.rmtree`).
  P2 (disk rmtree)      `cleanup_old_reports` deleted `untagged_versions` when a
                        match version existed (former app.py:11019).
  P3 (DB second pass)   `cleanup_old_reports` dropped every run row whose
                        analyzer_version != current (former app.py:11101-11127).

Legitimate hygiene that MUST still work (so the function is not a no-op):
  H1 within-same-tag recency dedup — older EXACT-tag duplicates of the survivor
     are still pruned (operator freeing disk; not a verdict).

Inject-bug recipes (reproduce the RED, then revert for GREEN)
-------------------------------------------------------------
  P1 (test_stale_analyzer_version_dir_survives_cleanup):
    In `cleanup_old_reports`, re-add the verdict-coupled deletion. Replace the
    survivor/to_delete block with the pre-honesty-1 cross-class delete, e.g.::

        from fresh_slotlab.analyzer.versioning import compute_analyzer_version
        cur = compute_analyzer_version()
        survivor = versions[0]
        to_delete = [v for v in versions if _version_analyzer(v) not in ("", cur)]

    Run test -> FAILS (the stale version dir is rmtree'd). Revert -> PASSES.

  P2 (test_untagged_version_survives_when_match_present):
    In the same block, add untagged versions to `to_delete` when a match exists::

        to_delete += [v for v in versions if _version_analyzer(v) == ""]

    Run test -> FAILS (untagged dir deleted). Revert -> PASSES.

  P3 (test_stale_db_run_row_survives_cleanup):
    Re-introduce the DB second pass right before the `return`::

        for row in store.list_runs(limit=100000):
            ra = (row.get("analyzer_version") or "").strip()
            if ra and ra != compute_analyzer_version():
                store.delete_run(row.get("run_id", ""))

    Run test -> FAILS (stale-tagged orphan run row deleted). Revert -> PASSES.

  H1 (test_recency_dedup_of_same_tag_still_prunes):
    In the survivor/to_delete block, make it a no-op::

        survivor = versions[0]; to_delete = []

    Run test -> FAILS (older exact-duplicate of the SAME tag not pruned).
    Revert -> PASSES. (Guards against "defang = disable" over-correction.)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fresh_slotlab.analyzer.versioning import compute_analyzer_version
from src.web_console.backend.app import StateStore


# A tag that is guaranteed != the real current analyzer version.
STALE_TAG = "deadbeefdead"
# A second distinct stale tag (used to prove cross-tag versions are NOT pruned).
STALE_TAG_2 = "0ldec0de0ld0"


def _seed_version_dir(
    reports_root: Path, machine: str, mode: int, rv_name: str,
    analyzer_version: str,
) -> Path:
    """Create reports/<machine>/mode_<n>/versions/<rv_name>/ with a
    player_impact_summary.json carrying the given analyzer_version tag.

    `cleanup_old_reports` reads `summary.analyzer_version` via its
    `_version_analyzer` helper, so the tag must live in that file.
    """
    vdir = reports_root / machine / f"mode_{mode}" / "versions" / rv_name
    vdir.mkdir(parents=True, exist_ok=True)
    summary = vdir / "player_impact_summary.json"
    payload: dict[str, object] = {"machine": machine, "mode": mode}
    if analyzer_version is not None:
        # Empty string == "untagged" (pre-tagging migration) for the helper.
        payload["analyzer_version"] = analyzer_version
    summary.write_text(json.dumps(payload), encoding="utf-8")
    return vdir


def _seed_run_row(
    store: StateStore, machine: str, mode: int, run_id: str,
    report_version: str, analyzer_version: str,
) -> str:
    """Insert one completed run row keyed to a report_version + analyzer tag.

    Mirrors the NOT_NULL column set used by tests/backend/test_report_stale_tagging.py.
    `report_version` ties the row to a version dir so the disk pass's
    rv_to_run_id lookup would have deleted it; `analyzer_version` is what the
    (removed) DB second-pass keyed its deletion on.
    """
    store.insert_run({
        "run_id": run_id,
        "machine": machine,
        "mode": mode,
        "status": "completed",
        "model_id": "test-model",
        "created_at": "2026-01-01T00:00:00Z",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:30Z",
        "chunk_spin_times": 1000,
        "chunk_robot_count": 8,
        "batch_concurrency": 8,
        "max_chunks": 10,
        "timeout": 300.0,
        "target_halfwidth_pp": 0.5,
        "bankruptcy_session_spins": 0,
        "bankruptcy_bankroll_multipliers": "[]",
        "report_version": report_version,
        "output_dir": "",
        "progress_file": "",
        "analyzer_version": analyzer_version,
    })
    return run_id


def _run_cleanup(client: TestClient) -> dict:
    resp = client.post("/api/reports/cleanup")
    assert resp.status_code == 200, f"cleanup failed: {resp.text}"
    return resp.json()


def _row_exists(db_path: Path, run_id: str) -> bool:
    with sqlite3.connect(db_path) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()[0]
    return n > 0


class TestCleanupDoesNotDeleteOnVerdict:
    """Honesty-1 acceptance: analyzer-version staleness never deletes."""

    def test_current_analyzer_version_is_not_the_stale_tag(self):
        """Guard: STALE_TAG really differs from the current analyzer version,
        otherwise every test below is vacuously green."""
        cur = compute_analyzer_version()
        assert cur and cur != STALE_TAG and cur != STALE_TAG_2, (
            f"test fixture tag collides with real analyzer version {cur!r}"
        )

    def test_stale_analyzer_version_dir_survives_cleanup(self, client, app_factory):
        """P1 disk path: a version whose analyzer_version != current, with a
        matching run row, survives cleanup — both dir AND row remain.

        Inject-bug P1 (see module docstring) -> RED; revert -> GREEN.
        """
        c, app = client
        machine, mode = "M14", 1
        rv = "rv_20260101T000001Z_stale001"

        vdir = _seed_version_dir(app_factory.reports_dir, machine, mode, rv, STALE_TAG)
        store: StateStore = app.state.store
        run_id = _seed_run_row(store, machine, mode, "run-stale-001", rv, STALE_TAG)

        result = _run_cleanup(c)

        assert vdir.exists(), (
            f"stale-analyzer version dir {vdir} was deleted by cleanup. "
            "Honesty-1: analyzer-version mismatch must NOT delete report artifacts. "
            "Inject-bug P1 re-introduces this."
        )
        assert (vdir / "player_impact_summary.json").exists()
        assert _row_exists(app_factory.db_path, run_id), (
            f"run row {run_id} was deleted by cleanup despite only its analyzer "
            "tag mismatching. The disk-pass run delete must not fire on a stale tag."
        )
        # Nothing should have been reported deleted (no exact-tag duplicates).
        assert result["deleted"] == 0, result

    def test_untagged_version_survives_when_match_present(self, client, app_factory):
        """P2 disk path: an UNTAGGED (pre-migration) version is kept even when a
        current-analyzer match version exists alongside it.

        Inject-bug P2 (see module docstring) -> RED; revert -> GREEN.
        """
        c, app = client
        machine, mode = "M14", 1
        cur = compute_analyzer_version()

        # Newest = current-tagged match; older = untagged baseline.
        rv_match = "rv_20260101T000002Z_match01"
        rv_untag = "rv_20260101T000001Z_untag01"
        match_dir = _seed_version_dir(app_factory.reports_dir, machine, mode, rv_match, cur)
        untag_dir = _seed_version_dir(app_factory.reports_dir, machine, mode, rv_untag, "")

        _run_cleanup(c)

        assert untag_dir.exists(), (
            f"untagged version dir {untag_dir} deleted despite a match version "
            "existing. Honesty-1 keeps untagged versions (a tag is not a "
            "destruction signal). Inject-bug P2 re-introduces this."
        )
        # The match (newest) survivor obviously stays too.
        assert match_dir.exists()

    def test_stale_db_run_row_survives_cleanup(self, client, app_factory):
        """P3 DB second pass: an orphan run row (stale analyzer tag, NO version
        dir on disk) survives cleanup. This is exactly the row the removed
        second pass targeted.

        Inject-bug P3 (see module docstring) -> RED; revert -> GREEN.
        """
        c, app = client
        machine, mode = "M14", 1
        store: StateStore = app.state.store
        # No version dir seeded for this report_version -> pure DB-only orphan.
        run_id = _seed_run_row(
            store, machine, mode, "run-orphan-stale",
            report_version="rv_gone_long_ago", analyzer_version=STALE_TAG,
        )

        _run_cleanup(c)

        assert _row_exists(app_factory.db_path, run_id), (
            f"orphan run row {run_id} (stale analyzer tag, no disk artifact) was "
            "deleted. Honesty-1 removed the DB second pass entirely — dropping a "
            "row purely because its analyzer tag mismatches the current one is the "
            "tag-as-destruction anti-pattern. Inject-bug P3 re-introduces this."
        )

    def test_recency_dedup_of_same_tag_still_prunes(self, client, app_factory):
        """H1 legitimate hygiene: among versions sharing the survivor's EXACT
        analyzer tag, older duplicates are still pruned — but a version with a
        DIFFERENT tag is NOT pruned (proving dedup is tag-homogeneous, not a
        verdict). Guards against the over-correction "defang = make it a no-op".

        Inject-bug H1 (see module docstring) -> RED; revert -> GREEN.
        """
        c, app = client
        machine, mode = "M14", 1
        cur = compute_analyzer_version()

        # Three versions, newest first by name:
        #   newest  -> current tag (survivor)
        #   middle  -> current tag (older EXACT-tag duplicate -> SHOULD be pruned)
        #   oldest  -> a DIFFERENT stale tag (-> MUST survive)
        rv_new = "rv_20260101T000003Z_curnew0"
        rv_dup = "rv_20260101T000002Z_curdup0"
        rv_other = "rv_20260101T000001Z_other00"
        new_dir = _seed_version_dir(app_factory.reports_dir, machine, mode, rv_new, cur)
        dup_dir = _seed_version_dir(app_factory.reports_dir, machine, mode, rv_dup, cur)
        other_dir = _seed_version_dir(app_factory.reports_dir, machine, mode, rv_other, STALE_TAG_2)

        store: StateStore = app.state.store
        dup_run = _seed_run_row(store, machine, mode, "run-dup", rv_dup, cur)
        other_run = _seed_run_row(store, machine, mode, "run-other", rv_other, STALE_TAG_2)

        result = _run_cleanup(c)

        # Survivor stays.
        assert new_dir.exists()
        # Older EXACT-tag duplicate pruned (legitimate recency dedup).
        assert not dup_dir.exists(), (
            f"older exact-tag duplicate {dup_dir} should be pruned by recency "
            "dedup. Inject-bug H1 (make to_delete=[]) re-introduces this failure."
        )
        assert not _row_exists(app_factory.db_path, dup_run)
        # Different-tag older version is NOT a duplicate -> MUST survive.
        assert other_dir.exists(), (
            f"different-tag version {other_dir} was pruned. Dedup must be "
            "tag-homogeneous; a mismatching tag is never grounds for deletion."
        )
        assert _row_exists(app_factory.db_path, other_run)
        assert result["deleted"] == 1, result

    def test_index_json_keeps_surviving_distinct_tag_versions(self, client, app_factory):
        """Index/disk consistency: after a same-tag duplicate is pruned, the
        index.json version list must still contain EVERY surviving on-disk
        version — it must NOT collapse to the survivor alone.

        honesty-1 keeps the survivor PLUS all distinct-tag versions on disk,
        but the index.json rewrite formerly kept only the survivor's entry
        (``report_version == survivor_name``). That would orphan a surviving
        distinct-tag version from the version-history panel (the UI reads
        index.json as the version list, app.py:10176) — the report file is on
        disk but invisible, recreating the user's "my reports disappeared"
        fear. The fix drops ONLY the pruned entries
        (``report_version not in deleted_names``), mirroring the explicit
        per-version DELETE rewrite (app.py:10385).

        Inject-bug recipe:
          In cleanup_old_reports' index.json rewrite, revert the filter to
          ``idx = [e for e in idx if e.get("report_version") == survivor_name]``
          -> this test FAILS (the distinct-tag survivor vanishes from index).
          Restore the ``not in deleted_names`` filter -> PASSES.
        """
        c, app = client
        machine, mode = "M14", 1
        cur = compute_analyzer_version()

        # newest = survivor (cur tag); middle = older EXACT-tag dup (pruned);
        # oldest = different stale tag (survives on disk -> must stay in index).
        rv_new = "rv_20260101T000003Z_ixnew00"
        rv_dup = "rv_20260101T000002Z_ixdup00"
        rv_other = "rv_20260101T000001Z_ixoth00"
        new_dir = _seed_version_dir(app_factory.reports_dir, machine, mode, rv_new, cur)
        dup_dir = _seed_version_dir(app_factory.reports_dir, machine, mode, rv_dup, cur)
        other_dir = _seed_version_dir(app_factory.reports_dir, machine, mode, rv_other, STALE_TAG_2)

        index_path = app_factory.reports_dir / machine / f"mode_{mode}" / "index.json"
        index_path.write_text(
            json.dumps([
                {"report_version": rv_new},
                {"report_version": rv_dup},
                {"report_version": rv_other},
            ]),
            encoding="utf-8",
        )

        result = _run_cleanup(c)

        # Disk: survivor + distinct-tag version stay; exact-tag dup pruned.
        assert new_dir.exists()
        assert other_dir.exists()
        assert not dup_dir.exists()
        assert result["deleted"] == 1, result

        # Index must reflect disk: keep BOTH survivors, drop ONLY the pruned dup.
        listed = {
            e.get("report_version")
            for e in json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(e, dict)
        }
        assert rv_new in listed, "survivor missing from index.json after cleanup"
        assert rv_other in listed, (
            f"distinct-tag surviving version {rv_other} was dropped from "
            "index.json even though it remains on disk — it would vanish from "
            "the version-history panel. The index rewrite must drop ONLY pruned "
            "entries (inject-bug: revert to '== survivor_name' to reproduce)."
        )
        assert rv_dup not in listed, (
            f"pruned duplicate {rv_dup} still listed in index.json (stale entry)."
        )


class TestDiagnosticFstringNameError:
    """Task C: regression for the NameError in the except-branch diagnostics.

    The two except blocks that fire when index.json / latest.json rewrite
    fails contain f-strings referencing ``{machine}`` and ``{mode}``. Those
    names do NOT exist in local scope — the loop variables are
    ``machine_dir`` and ``mode_dir``. So if either rewrite raises, the
    diagnostic f-string itself raises a NameError, turning a
    no_silent_swallow diagnostic path into a crash rather than a graceful
    log. This directly violates ``memory/feedback_no_silent_swallow.md``
    (best-effort post-hooks must persist a diagnostic, never crash).

    The lines are PRE-EXISTING (not introduced by honesty-1) but live inside
    the exact function honesty-1 modifies, and the brief §2.1 explicitly says
    "keep ... the no_silent_swallow diagnostics" working.

    Reproduce NameError (RED before fix):
      In app.py cleanup_old_reports, the two except blocks read:
        f"for {machine}|{mode}: ..."        # line ~11072
        f"for {machine}|{mode}: ..."        # line ~11097
      ``machine`` and ``mode`` are not bound in the enclosing scope;
      ``machine_dir`` and ``mode_dir`` are. Running this test with that
      code raises NameError inside the except block, which propagates out
      of cleanup and returns a 500 instead of 200.

    Minimal fix (GREEN after):
      Change the two f-strings to use ``{machine_dir.name}|{mode_dir.name}``
      (in-scope variables). No other logic changed.

    Inject-bug recipe (future devs):
      Revert the two f-string changes back to ``{machine}|{mode}`` and run
      this test -> RED. Restore -> GREEN.
    """

    def test_index_rewrite_except_does_not_raise_name_error(
        self, client, app_factory, monkeypatch
    ):
        """Force index.json rewrite to raise; assert cleanup returns 200 and
        emits a diagnostic line to stderr containing the machine/mode
        identity, NOT a NameError crash.

        Requires to_delete non-empty: seed two same-tag versions so the
        survivor/dup dedup fires and the index-rewrite branch executes.
        """
        c, app = client
        machine, mode = "M14", 1
        cur = compute_analyzer_version()

        # Seed two same-tag versions so to_delete becomes non-empty.
        rv_new = "rv_20260101T000002Z_idxnew0"
        rv_dup = "rv_20260101T000001Z_idxdup0"
        _seed_version_dir(app_factory.reports_dir, machine, mode, rv_new, cur)
        _seed_version_dir(app_factory.reports_dir, machine, mode, rv_dup, cur)

        # Write index.json so the branch opens the file.
        index_path = app_factory.reports_dir / machine / f"mode_{mode}" / "index.json"
        index_path.write_text(
            json.dumps([
                {"report_version": rv_new},
                {"report_version": rv_dup},
            ]),
            encoding="utf-8",
        )

        # Monkeypatch atomic_json_write to raise when called with index_path.
        import src.web_console.backend.app as app_module
        original_ajw = app_module.atomic_json_write

        def _raising_ajw(path, data, **kwargs):
            if Path(path).name == "index.json":
                raise RuntimeError("injected index.json write failure")
            return original_ajw(path, data, **kwargs)

        monkeypatch.setattr(app_module, "atomic_json_write", _raising_ajw)

        # Cleanup must NOT crash — it must return 200 (the except swallows it
        # as a best-effort diagnostic, NOT propagate as a 500).
        result = _run_cleanup(c)  # would raise 500 if NameError propagates

        # Confirm the result is a normal dict (not an exception trace).
        assert result.get("ok") is True, (
            "cleanup_old_reports returned non-ok after index.json write failure. "
            "The except branch must swallow the rewrite error gracefully (log+continue)."
        )

    def test_index_rewrite_except_emits_machine_mode_diagnostic(
        self, client, app_factory, monkeypatch, capsys
    ):
        """Same setup as above but asserts stderr contains a machine/mode
        identification string — proving the diagnostic IS emitted (not
        swallowed silently) and names the right location.

        Before fix: NameError in the f-string prevents stderr output entirely.
        After fix: stderr contains machine_dir.name and mode_dir.name values.
        """
        c, app = client
        machine, mode = "M14", 1
        cur = compute_analyzer_version()

        rv_new = "rv_20260101T000002Z_diag001"
        rv_dup = "rv_20260101T000001Z_diag002"
        _seed_version_dir(app_factory.reports_dir, machine, mode, rv_new, cur)
        _seed_version_dir(app_factory.reports_dir, machine, mode, rv_dup, cur)

        index_path = app_factory.reports_dir / machine / f"mode_{mode}" / "index.json"
        index_path.write_text(
            json.dumps([
                {"report_version": rv_new},
                {"report_version": rv_dup},
            ]),
            encoding="utf-8",
        )

        import src.web_console.backend.app as app_module
        original_ajw = app_module.atomic_json_write

        def _raising_ajw(path, data, **kwargs):
            if Path(path).name == "index.json":
                raise RuntimeError("injected index.json write failure for diag test")
            return original_ajw(path, data, **kwargs)

        monkeypatch.setattr(app_module, "atomic_json_write", _raising_ajw)

        _run_cleanup(c)

        captured = capsys.readouterr()
        stderr_out = captured.err
        assert "M14" in stderr_out, (
            f"Expected machine name 'M14' in stderr diagnostic after index.json write "
            f"failure, but stderr was:\n{stderr_out!r}\n"
            "Before fix: NameError in f-string swallows the message entirely. "
            "After fix: stderr should contain machine_dir.name."
        )
        assert "mode_1" in stderr_out or "1" in stderr_out, (
            f"Expected mode '1' or 'mode_1' in stderr diagnostic, got:\n{stderr_out!r}"
        )


class TestLegitimateDeletePathsUntouched:
    """Honesty-1 acceptance #3: explicit operator deletes still work — proves
    the defang was surgical (only the verdict coupling was removed)."""

    def test_explicit_per_version_delete_still_deletes(self, client, app_factory):
        """The explicit DELETE /api/reports/<m>/<n>/<rv> endpoint still removes
        its explicit target (an analyzer-stale tag must NOT block an explicit
        operator delete)."""
        c, app = client
        machine, mode = "M14", 1
        rv = "rv_20260101T000001Z_explicit"
        vdir = _seed_version_dir(app_factory.reports_dir, machine, mode, rv, STALE_TAG)
        # Seed an index.json entry so the endpoint's existence probe passes.
        index_path = app_factory.reports_dir / machine / f"mode_{mode}" / "index.json"
        index_path.write_text(
            json.dumps([{"report_version": rv}]), encoding="utf-8"
        )

        resp = c.delete(f"/api/reports/{machine}/{mode}/{rv}")
        assert resp.status_code == 200, f"explicit delete failed: {resp.text}"
        assert not vdir.exists(), (
            "explicit per-version delete must still remove its target — honesty-1 "
            "only removed the verdict-coupled deletion, not operator surgery."
        )
