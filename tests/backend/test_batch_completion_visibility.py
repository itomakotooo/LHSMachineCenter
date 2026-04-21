"""Post-completion observability of batch runs.

Bug A: ``get_batch`` used to gate the progress.jsonl read on
``status == "running"``, so the UI wiped every per-chunk event the
instant a run finished. The user reports upstream_unstable + 18 chunk
failures but the log shows none of them once the batch ends — exactly
the information the operator needs after the run.

Bug B: ``_run_one`` emitted the completion event at "ok" level
regardless of stop_reason, and never exposed ``stop_reason`` or
``ci_target_met`` on the batch item. A run that bailed at
``upstream_unstable`` (CI never reached the target) looked identical
to ``target_ci_reached`` in the UI — both green ✓.

These tests follow the "inject bug → red → fix → green" convention
documented in ``tests/backend/test_batch_analyzer_cli.py``. They drive
POST /api/batch-run through the full stack and assert on the
``get_batch`` response shape (+ batch-level event levels) rather than
testing helper logic in isolation.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


def _batch_payload(
    machine: str = "M14", mode: int = 1, target: float = 0.5
) -> dict[str, Any]:
    return {
        "items": [{"machine": machine, "mode": mode, "chunk_spin_times": 5000}],
        "concurrency": 1,
        "chunk_spin_times": 5000,
        "chunk_robot_count": 20,
        "max_chunks": 5,
        "target_halfwidth_pp": target,
        "batch_concurrency": 2,
        "timeout": 300,
        "auto_cleanup_cache": False,
    }


def _wait_for_run_id(client, batch_id: str, deadline_s: float = 15.0) -> str:
    """Poll until BatchRunManager has called RunManager.start_run and
    stamped the resulting run_id back onto the batch item."""
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        r = client.get(f"/api/batch-run/{batch_id}")
        if r.status_code == 200:
            items = r.json().get("items", [])
            if items and items[0].get("run_id"):
                return items[0]["run_id"]
        time.sleep(0.05)
    raise AssertionError(f"batch {batch_id} item never acquired a run_id")


def _resolve_run_paths(db_path: Path, run_id: str) -> tuple[Path, Path]:
    """Read the DB row to find where the analyzer would write its
    progress.jsonl + summary.json. Tests write to these paths directly
    as a stand-in for the stubbed analyzer subprocess."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT progress_file, summary_file FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"run {run_id} missing from DB"
    return Path(row[0]), Path(row[1])


def _append_event(progress_file: Path, event: dict[str, Any]) -> None:
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    with progress_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def _completed_summary(
    stop_reason: str, halfwidth_pp: float | None = 0.42
) -> dict[str, Any]:
    """Realistic-enough summary shape for _watch_run to flip status to
    completed (non-zero total_spins, valid rtp block). stop_reason +
    achieved_halfwidth_pp drive the ci_target_met classification."""
    return {
        "machine": "M14",
        "mode": 1,
        "sampling": {
            "target_halfwidth_pp": 0.5,
            "achieved_halfwidth_pp": halfwidth_pp,
            "chunks": 31,
            "total_spins": 4_085_704,
            "stop_reason": stop_reason,
            "duration_seconds": 1578,
            "chunk_spin_times": 5000,
            "chunk_robot_count": 20,
            "batch_concurrency": 4,
            "started_at": "2026-04-17T10:15:21Z",
            "finished_at": "2026-04-17T10:41:54Z",
        },
        "rtp": {"point_pct": 92.07, "ci95_interval_pct": [91.44, 92.70]},
        "player_impact": {
            "paylines_top20": [],
            "payout_groups_top20": [],
            "symbols_top20": [],
        },
        "guideline_assessment": {},
    }


def _release_stubs(stub_popen) -> None:
    for p in list(stub_popen.processes):
        if not getattr(p, "_communicated", False):
            p.finish(0)


# ---------- Bug A ----------


class TestChunkEventsVisibilityPostCompletion:
    """Bug A: chunk_events must stay populated after status flips out
    of "running". Previously the backend gated the progress.jsonl read
    on status == "running", so the UI went blank the moment the run
    finished — the operator lost the very failure log they needed."""

    def test_critical_chunk_events_survive_status_flip_to_completed(
        self, client, tmp_path: Path, app_factory, monkeypatch, wait_until_fixture
    ):
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "rawdata"
        raw_root.mkdir(exist_ok=True)
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)

        r = c.post("/api/batch-run", json=_batch_payload("M14", 1))
        assert r.status_code == 200, r.text
        batch_id = r.json()["batch_id"]

        run_id = _wait_for_run_id(c, batch_id)
        progress_file, summary_file = _resolve_run_paths(app_factory.db_path, run_id)

        # Seed the progress.jsonl with exactly the event classes the
        # user reported missing from the UI after completion.
        _append_event(progress_file, {
            "event": "resume_from_cache", "run_id": run_id,
            "existing_chunks": 9, "existing_spins": 1_080_000,
            "next_chunk_index": 10, "ts": "2026-04-17T10:15:21Z",
        })
        _append_event(progress_file, {
            "event": "chunk_failed", "run_id": run_id, "chunk_index": 15,
            "error": "request_failed_http_504",
            "cumulative_failed": 1, "ts": "2026-04-17T10:20:00Z",
        })
        _append_event(progress_file, {
            "event": "chunk_progress", "run_id": run_id, "chunk_index": 16,
            "total_spins": 1_900_000, "current_rtp_pct": 92.1,
            "current_halfwidth_pp": 0.9, "ts": "2026-04-17T10:20:30Z",
        })

        # Write summary + report so _watch_run flips status to completed.
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        summary_file.write_text(
            json.dumps(_completed_summary("target_ci_reached", halfwidth_pp=0.42)),
            encoding="utf-8",
        )
        (summary_file.parent / "player_impact_report.md").write_text(
            "# report\n", encoding="utf-8"
        )

        _release_stubs(app_factory.stub_popen)

        wait_until_fixture(
            lambda: c.get(f"/api/batch-run/{batch_id}").json()["items"][0]["status"]
            == "completed",
            timeout=5.0,
            msg="batch item never completed",
        )

        body = c.get(f"/api/batch-run/{batch_id}").json()
        item = body["items"][0]
        assert item["status"] == "completed"
        events = item.get("chunk_events") or []
        kinds = [e.get("event") for e in events]

        # THE regression: after completion, chunk_events must still
        # contain the criticals + the last progress frame. Before the
        # fix this list was empty because get_batch only read
        # progress.jsonl when status == "running".
        assert "chunk_failed" in kinds, (
            f"chunk_failed event lost post-completion; events seen: {kinds!r}"
        )
        assert "resume_from_cache" in kinds, (
            f"resume_from_cache lost post-completion; events seen: {kinds!r}"
        )
        assert "chunk_progress" in kinds, (
            f"chunk_progress lost post-completion; events seen: {kinds!r}"
        )


# ---------- Bug B ----------


class TestCiTargetMetSurfaced:
    """Bug B: completion semantics must distinguish
    ``target_ci_reached`` from graceful-stop-with-valid-data
    (``upstream_unstable`` / ``max_chunks_reached`` / etc.). Before the
    fix all "completed" items showed the green ✓ icon, so an operator
    couldn't tell the run actually hit its CI goal."""

    def test_upstream_unstable_marks_ci_target_not_met(
        self, client, tmp_path: Path, app_factory, monkeypatch, wait_until_fixture
    ):
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "rawdata"
        raw_root.mkdir(exist_ok=True)
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)

        r = c.post("/api/batch-run", json=_batch_payload(target=0.5))
        batch_id = r.json()["batch_id"]
        run_id = _wait_for_run_id(c, batch_id)
        _progress, summary_file = _resolve_run_paths(app_factory.db_path, run_id)

        stop_reason = (
            "upstream_unstable:consecutive_failed_batches=3,"
            "cumulative_failed_chunks=18,last_error=request_failed_http_504"
        )
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        summary_file.write_text(
            json.dumps(_completed_summary(stop_reason, halfwidth_pp=0.63)),
            encoding="utf-8",
        )
        (summary_file.parent / "player_impact_report.md").write_text(
            "# report\n", encoding="utf-8"
        )

        _release_stubs(app_factory.stub_popen)

        wait_until_fixture(
            lambda: c.get(f"/api/batch-run/{batch_id}").json()["items"][0]["status"]
            == "completed",
            timeout=5.0,
        )

        body = c.get(f"/api/batch-run/{batch_id}").json()
        item = body["items"][0]
        assert item["status"] == "completed"
        # stop_reason + ci_target_met must be on the batch item so the
        # frontend can render ⚠ instead of ✓.
        assert (item.get("stop_reason") or "").startswith("upstream_unstable"), (
            f"stop_reason not propagated; item: {item!r}"
        )
        assert item.get("ci_target_met") is False, (
            f"upstream_unstable with CI 0.63pp > target 0.5pp must report "
            f"ci_target_met=False; got {item.get('ci_target_met')!r}"
        )
        # And the batch-level log must surface a warn-level event,
        # otherwise the frontend banner stays green.
        warn_events = [e for e in body.get("events", []) if e.get("level") == "warn"]
        assert warn_events, (
            f"upstream_unstable completion should emit warn-level event; "
            f"events: {body.get('events')!r}"
        )

    def test_target_ci_reached_marks_ci_target_met(
        self, client, tmp_path: Path, app_factory, monkeypatch, wait_until_fixture
    ):
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "rawdata"
        raw_root.mkdir(exist_ok=True)
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)

        r = c.post("/api/batch-run", json=_batch_payload(target=0.5))
        batch_id = r.json()["batch_id"]
        run_id = _wait_for_run_id(c, batch_id)
        _progress, summary_file = _resolve_run_paths(app_factory.db_path, run_id)

        summary_file.parent.mkdir(parents=True, exist_ok=True)
        summary_file.write_text(
            json.dumps(_completed_summary("target_ci_reached", halfwidth_pp=0.42)),
            encoding="utf-8",
        )
        (summary_file.parent / "player_impact_report.md").write_text(
            "# report\n", encoding="utf-8"
        )

        _release_stubs(app_factory.stub_popen)

        wait_until_fixture(
            lambda: c.get(f"/api/batch-run/{batch_id}").json()["items"][0]["status"]
            == "completed",
            timeout=5.0,
        )

        body = c.get(f"/api/batch-run/{batch_id}").json()
        item = body["items"][0]
        assert item.get("ci_target_met") is True, (
            f"target_ci_reached must report ci_target_met=True; item: {item!r}"
        )
        assert (item.get("stop_reason") or "") == "target_ci_reached"
        levels = [e.get("level") for e in body.get("events", [])]
        assert "ok" in levels, (
            f"happy-path completion should include ok-level event; levels: {levels!r}"
        )

    def test_fuzzy_max_chunks_counts_as_ci_target_met(
        self, client, tmp_path: Path, app_factory, monkeypatch, wait_until_fixture
    ):
        """Fuzzy mode (target=0 → rewritten to 999 in the analyzer CLI)
        has no CI gate — the budget is max_chunks. A fuzzy run that
        reaches ``max_chunks_reached`` is the *intended* terminal state,
        not a failure to converge. So for fuzzy, max_chunks_reached +
        from_cache_complete both count as ci_target_met=True."""
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "rawdata"
        raw_root.mkdir(exist_ok=True)
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)

        r = c.post("/api/batch-run", json=_batch_payload(target=0.0))  # fuzzy
        batch_id = r.json()["batch_id"]
        run_id = _wait_for_run_id(c, batch_id)
        _progress, summary_file = _resolve_run_paths(app_factory.db_path, run_id)

        summary_file.parent.mkdir(parents=True, exist_ok=True)
        # Fuzzy run: analyzer gets target_halfwidth_pp=999 rewritten by
        # RunManager.start_run, and summary reflects that. CI not met
        # in the strict sense — target=999 was never going to be — but
        # semantically the run completed its budget.
        summary = _completed_summary("max_chunks_reached", halfwidth_pp=12.7)
        summary["sampling"]["target_halfwidth_pp"] = 999.0
        summary_file.write_text(json.dumps(summary), encoding="utf-8")
        (summary_file.parent / "player_impact_report.md").write_text(
            "# report\n", encoding="utf-8"
        )

        _release_stubs(app_factory.stub_popen)

        wait_until_fixture(
            lambda: c.get(f"/api/batch-run/{batch_id}").json()["items"][0]["status"]
            == "completed",
            timeout=5.0,
        )

        body = c.get(f"/api/batch-run/{batch_id}").json()
        item = body["items"][0]
        assert item.get("ci_target_met") is True, (
            f"fuzzy max_chunks_reached must count as success; item: {item!r}"
        )

    def test_from_cache_complete_with_ci_met_numerically_counts_as_ci_target_met(
        self, client, tmp_path: Path, app_factory, monkeypatch, wait_until_fixture
    ):
        """2026-04-21 virtual-console regression: virtual_analyzer's sim
        loop broke with ``target_ci_reached``, but then it delegated to
        real analyzer's ``--from-cache`` which overwrote the summary's
        ``stop_reason`` to ``from_cache_complete``. Backend's
        ``ci_target_met`` was string-matching only, so the UI said
        "完成但未达 CI 目标" even though achieved CI (±4.42pp) was
        well under target (±5.0pp).

        Fix: numeric tie-breaker. If achieved_halfwidth_pp ≤
        target_halfwidth_pp (and target < 999 = not fuzzy), the goal
        was met regardless of the stop_reason string label.
        """
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "rawdata"
        raw_root.mkdir(exist_ok=True)
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)

        r = c.post("/api/batch-run", json=_batch_payload(target=5.0))
        batch_id = r.json()["batch_id"]
        run_id = _wait_for_run_id(c, batch_id)
        _progress, summary_file = _resolve_run_paths(app_factory.db_path, run_id)

        # Post a summary with:
        #   stop_reason: "from_cache_complete"  (would-be failure signal)
        #   achieved_halfwidth_pp: 4.42         (< target 5.0, so met)
        #   target_halfwidth_pp: 5.0            (user's selected target)
        summary = _completed_summary("from_cache_complete", halfwidth_pp=4.42)
        summary["sampling"]["target_halfwidth_pp"] = 5.0
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        summary_file.write_text(json.dumps(summary), encoding="utf-8")
        (summary_file.parent / "player_impact_report.md").write_text(
            "# report\n", encoding="utf-8"
        )

        _release_stubs(app_factory.stub_popen)

        wait_until_fixture(
            lambda: c.get(f"/api/batch-run/{batch_id}").json()["items"][0]["status"]
            == "completed",
            timeout=5.0,
        )

        body = c.get(f"/api/batch-run/{batch_id}").json()
        item = body["items"][0]
        assert item.get("ci_target_met") is True, (
            f"achieved CI ±4.42pp ≤ target ±5.0pp must count as met "
            f"regardless of stop_reason='from_cache_complete'; item: {item!r}"
        )
        # Event level should be "ok", not "warn" — the run hit its goal.
        levels = [e.get("level") for e in body.get("events", [])]
        assert "ok" in levels, (
            f"goal met numerically should emit ok-level event; levels: {levels!r}"
        )
        assert "warn" not in levels or all(
            "CI 目标" not in (e.get("text") or "") for e in body.get("events", [])
            if e.get("level") == "warn"
        ), (
            f"should NOT emit '完成但未达 CI 目标' warn event when achieved ≤ target; "
            f"events: {body.get('events', [])!r}"
        )

    def test_from_cache_complete_with_ci_not_met_stays_unmet(
        self, client, tmp_path: Path, app_factory, monkeypatch, wait_until_fixture
    ):
        """Counter-case: from_cache_complete with achieved CI > target
        must STILL report ci_target_met=False (the numeric tie-breaker
        only helps when CI actually met; it doesn't rescue genuine
        under-convergence)."""
        import src.web_console.backend.app as app_mod
        c, _ = client
        raw_root = tmp_path / "rawdata"
        raw_root.mkdir(exist_ok=True)
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)

        r = c.post("/api/batch-run", json=_batch_payload(target=0.5))
        batch_id = r.json()["batch_id"]
        run_id = _wait_for_run_id(c, batch_id)
        _progress, summary_file = _resolve_run_paths(app_factory.db_path, run_id)

        # stop_reason=from_cache_complete + achieved 1.2pp + target 0.5pp
        # = UNDER target, not met.
        summary = _completed_summary("from_cache_complete", halfwidth_pp=1.2)
        summary["sampling"]["target_halfwidth_pp"] = 0.5
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        summary_file.write_text(json.dumps(summary), encoding="utf-8")
        (summary_file.parent / "player_impact_report.md").write_text(
            "# report\n", encoding="utf-8"
        )

        _release_stubs(app_factory.stub_popen)

        wait_until_fixture(
            lambda: c.get(f"/api/batch-run/{batch_id}").json()["items"][0]["status"]
            == "completed",
            timeout=5.0,
        )

        body = c.get(f"/api/batch-run/{batch_id}").json()
        item = body["items"][0]
        assert item.get("ci_target_met") is False, (
            f"achieved CI ±1.2pp > target ±0.5pp must stay ci_target_met=False; "
            f"item: {item!r}"
        )
