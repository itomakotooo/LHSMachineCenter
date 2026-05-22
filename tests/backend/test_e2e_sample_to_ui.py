"""End-to-end integration test for the sampling → report → import → UI chain.

Exercises the whole pipeline without hitting a real upstream:

    synthetic API response
        ↓ _save_chunk_cache (v3 envelope + sha256 + atomic write)
    rawdata/<machine>/mode_<N>/chunk_0001.json
        ↓ analyzer.main() with --from-cache
    <analyzer_out>/<machine>/mode_<N>/versions/rv_*/player_impact_summary.json
        ↓ POST /api/reports/import (transactional)
    reports/<machine>/mode_<N>/versions/rv_*/...   + DB runs row
        ↓ GET /api/machines-summary + /api/runs
    UI-facing data has the machine with rtp_pct + ci_halfwidth_pp

Takes ~2s — full analyzer run on 250 synthetic rounds. That's slower
than the typical unit test but not enough to warrant a separate marker.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest


# Mix of win amounts so session variance > 0 and CI is non-trivial.
# All-identical rounds (win=bet×0.9 every time) would give variance 0,
# which the analyzer now clamps to 0 rather than None — but realistic
# data always has spread.
_WIN_SEQUENCE = [0, 0, 500, 900, 1500, 0, 400, 2000, 0, 1000]


# Build a minimal valid round: BetAmount + WinCredits + StopSymbolsByCol
# cover the analyzer's _REQUIRED_ROUND_FIELDS + _REQUIRED_BET_FIELDS_ANY.
# SpinType="Normal" keeps session attribution simple (no bonus chains).
def _round(bet: int = 1000, win: int = 900) -> dict[str, Any]:
    return {
        "BetAmount": bet,
        "WinCredits": win,
        "StopSymbolsByCol": "A|B|C|D|E",
        "SpinType": "Normal",
        "IsLackCreditsSpin": False,
    }


def _synthetic_response(
    robot_count: int = 5, rounds_per_robot: int = 50, bet: int = 1000
) -> list[dict]:
    """Build a plausible upstream response payload.

    Cycles through `_WIN_SEQUENCE` so win amounts vary per round; average
    is 630/1000 ≈ 63% RTP with real variance. Single-robot shape is a
    dict with `roundResult` (JSON string) + `analysisResult` (dict),
    matching M14's real upstream shape.
    """
    rounds = [
        _round(bet=bet, win=_WIN_SEQUENCE[i % len(_WIN_SEQUENCE)])
        for i in range(rounds_per_robot)
    ]
    robots = []
    for _ in range(robot_count):
        robots.append({
            "roundResult": json.dumps(rounds),
            "analysisResult": json.dumps({
                "TotalWin": {}, "FeatureWin": {}, "SummaryWin": 0,
            }),
        })
    return robots


def _run_analyzer_in_process(
    *, machine: str, mode: int, bet: int,
    from_cache: Path, output_dir: Path,
) -> int:
    """Call analyzer.main() directly with a synthetic argv.

    Captures stdout (analyzer prints the full summary JSON at the end;
    we don't want it flooding pytest output).
    """
    import fresh_slotlab.player_impact_analyzer as analyzer

    argv = [
        "player_impact_analyzer.py",
        "--machine", machine,
        "--rtp-mode", str(mode),
        "--bet", str(bet),
        "--from-cache", str(from_cache),
        "--output-dir", str(output_dir),
        "--max-chunks", "999",
    ]
    orig_argv = sys.argv
    sys.argv = argv
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return analyzer.main()
    finally:
        sys.argv = orig_argv


class TestEndToEndPipeline:
    def test_full_chain(self, client, tmp_path: Path, app_factory):
        c, app = client
        machine = "MTEST"
        mode = 1

        # 1. Synthesize one chunk into a rawdata-layout dir.
        rawdata_root = tmp_path / "rawdata"
        mode_cache_dir = rawdata_root / machine / f"mode_{mode}"
        mode_cache_dir.mkdir(parents=True)

        from tests.backend._save_chunk_cache_compat import _save_chunk_cache
        resp = _synthetic_response(robot_count=5, rounds_per_robot=50, bet=1000)
        _save_chunk_cache(
            resp, chunk_index=1, machine=machine, rtp_mode=mode,
            bet=1000, spin_times=50, robot_count=5,
            cache_dir=mode_cache_dir,
        )
        chunk_file = mode_cache_dir / "chunk_0001.json"
        assert chunk_file.exists(), "chunk_0001.json should have been written"
        # Envelope has v3 metadata.
        env = json.loads(chunk_file.read_text(encoding="utf-8"))
        assert env["_cache_version"] == 3
        assert "_payload_sha256" in env

        # 2. Run the analyzer against the cache. Output to a separate
        #    "source" tree we'll then feed into /api/reports/import.
        analyzer_out = tmp_path / "analyzer_out"
        version_name = "rv_20260417T120000Z_e2etest"
        output_dir = analyzer_out / machine / f"mode_{mode}" / "versions" / version_name
        output_dir.mkdir(parents=True)

        rc = _run_analyzer_in_process(
            machine=machine, mode=mode, bet=1000,
            from_cache=mode_cache_dir, output_dir=output_dir,
        )
        assert rc == 0, f"analyzer exited with rc={rc}"
        summary_path = output_dir / "player_impact_summary.json"
        assert summary_path.exists()
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        # Sanity: RTP is near the synthetic mean (~63%) and CI came
        # from session-level math (not a fallback null).
        rtp = summary["rtp"]["point_pct"]
        expected_rtp = (sum(_WIN_SEQUENCE) / len(_WIN_SEQUENCE)) / 1000 * 100
        assert abs(rtp - expected_rtp) < 5.0, (
            f"synthetic {expected_rtp:.1f}% expected, got {rtp}"
        )
        hw = summary["sampling"]["achieved_halfwidth_pp"]
        assert hw is not None, "session-level CI should be populated (P0.2)"
        assert hw == summary["sampling"]["session_level_halfwidth_pp"]

        # 3. Import into the app's reports_root + create DB row.
        r = c.post(
            "/api/reports/import",
            json={"source_path": str(analyzer_out), "mode": "merge"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["imported"] == 1
        assert body["failed"] == 0
        assert machine in body["machines_affected"]

        # 4. Machine shows up in the summary.
        summary_r = c.get("/api/machines/summary")
        assert summary_r.status_code == 200
        machines_summary = summary_r.json().get("machines", {})
        assert machine in machines_summary
        mode_data = machines_summary[machine][str(mode)]
        assert abs(mode_data["rtp_pct"] - expected_rtp) < 5.0
        assert mode_data["ci_halfwidth_pp"] is not None
        assert mode_data["ci_halfwidth_pp"] > 0

        # 5. Run row exists with status=completed and the CI column
        #    populated (backfill happened at insert time, not via the
        #    backfill migration).
        runs_r = c.get("/api/runs")
        assert runs_r.status_code == 200
        runs = runs_r.json().get("runs", [])
        matching = [r for r in runs if r["machine"] == machine and r["mode"] == mode]
        assert len(matching) == 1
        run_row = matching[0]
        assert run_row["status"] == "completed"
        assert run_row["report_version"] == version_name
        assert run_row.get("achieved_halfwidth_pp") is not None


class TestEndToEndPartial:
    """The other side of the contract: what happens when one step in
    the chain breaks."""

    def test_corrupt_chunk_fails_analyzer_clean_errno(self, tmp_path: Path):
        # Write a v3 envelope then tamper with response so sha mismatches.
        from fresh_slotlab.player_impact_analyzer import (
            ChunkIntegrityError, load_chunk_envelope,
        )
        from tests.backend._save_chunk_cache_compat import _save_chunk_cache
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _save_chunk_cache(
            _synthetic_response(2, 10, 1000), 1, "MTEST", 1, 1000, 10, 2, cache_dir,
        )
        p = cache_dir / "chunk_0001.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["response"][0]["roundResult"] = "[]"  # drift
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

        # load_chunk_envelope is the layer that catches this; the full
        # analyzer run wraps it as SystemExit("--from-cache: ...").
        with pytest.raises(ChunkIntegrityError):
            load_chunk_envelope(p)
