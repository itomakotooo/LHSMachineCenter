from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENDPOINT_URL = "http://buffalo-debug.citrusjoy.com/MachineTest/MultiRobotTestSpinVariant"
MACHINE_NAME = "M14"
RTP_MODE = 1
BET_ORIGIN = 1000
INIT_CREDITS_STR = "100000000000000"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Adaptive sampler for M14 mode=1 with batch concurrency. "
            "Each batch runs multiple chunks in parallel, then CI is recomputed."
        )
    )
    parser.add_argument("--target-halfwidth-pp", type=float, default=0.5)
    parser.add_argument("--chunk-spin-times", type=int, default=5000)
    parser.add_argument("--chunk-robot-count", type=int, default=20)
    parser.add_argument("--batch-concurrency", type=int, default=5)
    parser.add_argument(
        "--output-all-robots-result",
        dest="output_all_robots_result",
        action="store_true",
        help="Set request field OutputAllRobotResult=true",
    )
    parser.add_argument(
        "--no-output-all-robots-result",
        dest="output_all_robots_result",
        action="store_false",
        help="Set request field OutputAllRobotResult=false",
    )
    parser.add_argument("--max-chunks", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--output-dir", type=Path, default=Path("fresh_slotlab/runs/latest"))
    parser.set_defaults(output_all_robots_result=True)
    return parser.parse_args(argv)


def build_payload(
    chunk_spin_times: int,
    chunk_robot_count: int,
    output_all_robots_result: bool,
) -> dict[str, Any]:
    return {
        "MachineName": MACHINE_NAME,
        "InitCreditsStr": INIT_CREDITS_STR,
        "BetStrategy": 0,
        "BetOriginStr": str(BET_ORIGIN),
        "SpinTimes": int(chunk_spin_times),
        "RtpId": RTP_MODE,
        "ShouldTestLuckyGame": False,
        "ContinueAfterBankrupt": True,
        "ResetPlayerStateAfterEachSpin": True,
        "RobotCount": int(chunk_robot_count),
        "OutputAllRobotResult": bool(output_all_robots_result),
    }


def post_json(url: str, payload: dict[str, Any], timeout: float) -> Any:
    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8").strip()
    if not text:
        raise ValueError("empty response body")
    return json.loads(text)


def _as_number(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value)
    return 0.0


def parse_robot_totals(analysis_result: str) -> tuple[int, float]:
    outer = json.loads(analysis_result)
    total_win_raw = outer.get("TotalWin")
    if isinstance(total_win_raw, str):
        bucket_map = json.loads(total_win_raw)
    elif isinstance(total_win_raw, dict):
        bucket_map = total_win_raw
    else:
        raise ValueError("analysisResult.TotalWin missing")

    spins = 0
    win = 0.0
    for bucket in bucket_map.values():
        if not isinstance(bucket, dict):
            continue
        spins += int(_as_number(bucket.get("Times")))
        win += _as_number(bucket.get("WinCredits"))
    return spins, win


def extract_chunk_metrics(response: Any) -> tuple[int, float, float]:
    if not isinstance(response, list):
        raise ValueError("response is not a robot list")

    total_spins = 0
    total_win = 0.0
    for robot in response:
        if not isinstance(robot, dict):
            continue
        analysis_result = robot.get("analysisResult")
        if not analysis_result:
            continue
        spins, win = parse_robot_totals(analysis_result)
        total_spins += spins
        total_win += win

    if total_spins <= 0:
        raise ValueError("no robot spins parsed from response")
    total_bet = float(total_spins * BET_ORIGIN)
    return total_spins, total_bet, total_win


def t_critical_95(df: int) -> float:
    if df <= 0:
        return math.inf
    table = {
        1: 12.706,
        2: 4.303,
        3: 3.182,
        4: 2.776,
        5: 2.571,
        6: 2.447,
        7: 2.365,
        8: 2.306,
        9: 2.262,
        10: 2.228,
        11: 2.201,
        12: 2.179,
        13: 2.160,
        14: 2.145,
        15: 2.131,
        16: 2.120,
        17: 2.110,
        18: 2.101,
        19: 2.093,
        20: 2.086,
        21: 2.080,
        22: 2.074,
        23: 2.069,
        24: 2.064,
        25: 2.060,
        26: 2.056,
        27: 2.052,
        28: 2.048,
        29: 2.045,
        30: 2.042,
        40: 2.021,
        60: 2.000,
        80: 1.990,
        120: 1.980,
        1000: 1.962,
    }
    if df in table:
        return table[df]
    points = sorted(table.items())
    if df < points[0][0]:
        return points[0][1]
    if df > points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= df <= x1:
            ratio = (df - x0) / (x1 - x0)
            return y0 + (y1 - y0) * ratio
    return 1.962


def compute_ci_halfwidth_pp(chunk_rtps_pct: list[float]) -> float:
    if len(chunk_rtps_pct) < 2:
        return math.inf
    if len(set(chunk_rtps_pct)) == 1:
        return 0.0
    s = statistics.stdev(chunk_rtps_pct)
    t = t_critical_95(len(chunk_rtps_pct) - 1)
    return t * s / math.sqrt(len(chunk_rtps_pct))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_one_chunk(
    chunk_index: int,
    chunk_spin_times: int,
    chunk_robot_count: int,
    output_all_robots_result: bool,
    timeout: float,
) -> dict[str, Any]:
    payload = build_payload(chunk_spin_times, chunk_robot_count, output_all_robots_result)
    chunk_started_ts = time.time()
    try:
        response = post_json(ENDPOINT_URL, payload, timeout)
        spins, bet, win = extract_chunk_metrics(response)
        return {
            "ok": True,
            "index": chunk_index,
            "spins": spins,
            "bet": bet,
            "win": win,
            "elapsed_seconds": round(time.time() - chunk_started_ts, 3),
        }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "index": chunk_index, "error": f"request_failed_http_{exc.code}"}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {
            "ok": False,
            "index": chunk_index,
            "error": f"request_failed_network_{exc.__class__.__name__}",
        }
    except (ValueError, json.JSONDecodeError, KeyError) as exc:
        return {"ok": False, "index": chunk_index, "error": f"parse_failed_{exc.__class__.__name__}"}


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.target_halfwidth_pp <= 0:
        raise SystemExit("--target-halfwidth-pp must be positive")
    if args.chunk_spin_times <= 0 or args.chunk_robot_count <= 0:
        raise SystemExit("chunk size arguments must be positive")
    if args.batch_concurrency <= 0:
        raise SystemExit("--batch-concurrency must be positive")
    if args.max_chunks <= 0 or args.timeout <= 0:
        raise SystemExit("--max-chunks/--timeout must be positive")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    started_ts = time.time()

    chunk_rtps_pct: list[float] = []
    chunk_records: list[dict[str, Any]] = []
    total_spins = 0
    total_bet = 0.0
    total_win = 0.0
    stop_reason = "max_chunks_reached"
    ci_halfwidth_pp = math.inf
    next_chunk_index = 1

    while next_chunk_index <= args.max_chunks:
        remaining = args.max_chunks - len(chunk_records)
        batch_size = min(args.batch_concurrency, remaining)
        if batch_size <= 0:
            break

        batch_indices = list(range(next_chunk_index, next_chunk_index + batch_size))
        next_chunk_index += batch_size

        batch_results: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = [
                executor.submit(
                    run_one_chunk,
                    i,
                    args.chunk_spin_times,
                    args.chunk_robot_count,
                    args.output_all_robots_result,
                    args.timeout,
                )
                for i in batch_indices
            ]
            for future in concurrent.futures.as_completed(futures):
                batch_results.append(future.result())

        error = next((r for r in batch_results if not r["ok"]), None)
        if error is not None:
            stop_reason = str(error["error"])
            break

        for rec in sorted(batch_results, key=lambda x: int(x["index"])):
            spins = int(rec["spins"])
            bet = float(rec["bet"])
            win = float(rec["win"])
            chunk_rtp_pct = (win / bet) * 100.0 if bet > 0 else 0.0
            chunk_rtps_pct.append(chunk_rtp_pct)
            total_spins += spins
            total_bet += bet
            total_win += win
            ci_halfwidth_pp = compute_ci_halfwidth_pp(chunk_rtps_pct)
            chunk_records.append(
                {
                    "index": rec["index"],
                    "spins": spins,
                    "bet": bet,
                    "win": win,
                    "rtp_pct": chunk_rtp_pct,
                    "ci_halfwidth_pp_after_chunk": (
                        ci_halfwidth_pp if math.isfinite(ci_halfwidth_pp) else None
                    ),
                    "elapsed_seconds": rec["elapsed_seconds"],
                }
            )

        if len(chunk_rtps_pct) >= 2 and ci_halfwidth_pp <= args.target_halfwidth_pp:
            stop_reason = "target_ci_reached"
            break

    finished_at = utc_now()
    duration_seconds = round(time.time() - started_ts, 3)
    rtp_point_frac = (total_win / total_bet) if total_bet > 0 else 0.0
    rtp_point_pct = rtp_point_frac * 100.0
    ci_pp = ci_halfwidth_pp if math.isfinite(ci_halfwidth_pp) else None
    ci95_interval_pct = (
        [rtp_point_pct - ci_pp, rtp_point_pct + ci_pp] if ci_pp is not None else None
    )

    summary = {
        "report_id": f"run_M14_mode1_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "machine": MACHINE_NAME,
        "mode": RTP_MODE,
        "endpoint": ENDPOINT_URL,
        "target_halfwidth_pp": args.target_halfwidth_pp,
        "achieved_halfwidth_pp": ci_pp,
        "chunk_spin_times": args.chunk_spin_times,
        "chunk_robot_count": args.chunk_robot_count,
        "batch_concurrency": args.batch_concurrency,
        "output_all_robots_result": args.output_all_robots_result,
        "max_chunks": args.max_chunks,
        "timeout": args.timeout,
        "total_spins": total_spins,
        "chunks": len(chunk_records),
        "total_bet": total_bet,
        "total_win": total_win,
        "rtp_point_frac": rtp_point_frac,
        "rtp_point_pct": rtp_point_pct,
        "ci95_interval_pct": ci95_interval_pct,
        "stop_reason": stop_reason,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "chunk_rtps_pct": chunk_rtps_pct,
        "chunk_records": chunk_records,
    }

    output_path = args.output_dir / "run_summary.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
