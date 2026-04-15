from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import re
import statistics
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENDPOINT_URL = "http://buffalo-debug.citrusjoy.com/MachineTest/MultiRobotTestSpin"
PAYLINE_RE = re.compile(r"(\d+):")
RETURN_BUCKET_ORDER = [
    "eq0",
    "gt0_lt1",
    "ge1_lt5",
    "ge5_lt10",
    "ge10_lt20",
    "ge20_lt50",
    "ge50_lt100",
    "ge100_lt200",
    "ge200_lt500",
    "ge500_lt1000",
    "ge1000_lt5000",
    "ge5000",
]
# Tail dependency uses every bucket >= 10x. The previous schema lumped
# everything >=100 into one bucket; the refined schema splits it into
# 100-200 / 200-500 / 500-1000 / 1000-5000 / 5000+ so the tail is more
# than just a pile.
TAIL_GEX10_BUCKETS = {
    "ge10_lt20",
    "ge20_lt50",
    "ge50_lt100",
    "ge100_lt200",
    "ge200_lt500",
    "ge500_lt1000",
    "ge1000_lt5000",
    "ge5000",
}
DEFAULT_GUIDELINE_RULES_PATH = (
    Path(__file__).resolve().parents[1] / "configs" / "classic_slots_guideline_rules.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Player-impact analyzer for slot test endpoint with true batch concurrency."
    )
    parser.add_argument("--machine", default="M14")
    parser.add_argument("--rtp-mode", type=int, default=1)
    parser.add_argument("--bet", type=int, default=1000)
    parser.add_argument("--target-halfwidth-pp", type=float, default=0.5)
    parser.add_argument("--chunk-spin-times", type=int, default=5000)
    parser.add_argument("--chunk-robot-count", type=int, default=20)
    parser.add_argument("--batch-concurrency", type=int, default=2)
    parser.add_argument("--max-chunks", type=int, default=120)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", default=None, help="optional external run id for orchestration")
    parser.add_argument(
        "--progress-file",
        type=Path,
        default=None,
        help="optional jsonl file path for chunk-level progress events",
    )
    parser.add_argument("--bankruptcy-session-spins", type=int, default=500)
    parser.add_argument(
        "--bankruptcy-bankroll-multipliers",
        default="100,200,500",
        help="comma-separated bet multipliers for bankruptcy probe",
    )
    parser.add_argument(
        "--bankruptcy-robot-count",
        type=int,
        default=None,
        help="optional override for bankruptcy probe robot count; defaults to chunk-robot-count",
    )
    parser.add_argument(
        "--guideline-rules",
        type=Path,
        default=DEFAULT_GUIDELINE_RULES_PATH,
        help="path to external deterministic guideline check rules JSON",
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def to_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return float(text)
            except ValueError:
                return default
    return default


def post_json(payload: dict[str, Any], timeout: float) -> Any:
    req = urllib.request.Request(
        ENDPOINT_URL,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


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
        20: 2.086,
        30: 2.042,
        40: 2.021,
        60: 2.000,
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


def ci_halfwidth_pp(chunk_rtps_pct: list[float]) -> float:
    if len(chunk_rtps_pct) < 2:
        return math.inf
    if len(set(chunk_rtps_pct)) == 1:
        return 0.0
    return (
        t_critical_95(len(chunk_rtps_pct) - 1)
        * statistics.stdev(chunk_rtps_pct)
        / math.sqrt(len(chunk_rtps_pct))
    )


def parse_rounds(robot: dict[str, Any]) -> list[dict[str, Any]]:
    rr = robot.get("roundResult")
    if not rr:
        return []
    if isinstance(rr, str):
        try:
            parsed = json.loads(rr)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return rr if isinstance(rr, list) else []


# Round-level fields that MUST appear on every spin regardless of
# win / lose state. Missing one is almost certainly an upstream API
# field rename and the analyzer should fail loudly instead of silently
# producing all-zero metrics.
#
# Intentionally NOT in this set:
#   - PayoutByPayline: legitimately absent on lose spins (no payline).
#   - PayoutGroupId:   legitimately absent on no-payout spins.
#   The first round of a chunk is statistically very likely to be a
#   lose spin (RTP ~95% with hit_rate ~30% means ~70% lose), so
#   strict-checking these caused false-positive run aborts.
_REQUIRED_ROUND_FIELDS = (
    "WinCredits",
    "StopSymbolsByCol",
)
# Bet amount has a documented fallback chain (BetAmount -> CostCredits
# -> the chunk-level `bet` arg). The schema check still wants AT LEAST
# one of the first two to exist on a real round.
_REQUIRED_BET_FIELDS_ANY = ("BetAmount", "CostCredits")


def _check_round_schema(resp: list[Any]) -> list[str]:
    """Inspect the first parsed round of a chunk response and return the
    names of required fields that are missing. Returns [] when the
    schema is intact, or when there are no parsed rounds at all (the
    existing parse_failed_zero_chunk path handles the empty case).
    """
    if not isinstance(resp, list):
        return []
    for robot in resp:
        if not isinstance(robot, dict):
            continue
        rounds = parse_rounds(robot)
        for round_obj in rounds:
            if not isinstance(round_obj, dict):
                continue
            missing = [f for f in _REQUIRED_ROUND_FIELDS if f not in round_obj]
            if not any(f in round_obj for f in _REQUIRED_BET_FIELDS_ANY):
                missing.append("BetAmount|CostCredits")
            return missing
    return []


def parse_paylines(text: str) -> list[str]:
    if not text:
        return []
    return PAYLINE_RE.findall(text)


def split_symbols(col_text: str) -> list[str]:
    if not col_text:
        return []
    return [x for x in col_text.split("-") if x]


def quantile_from_hist(hist: dict[int, int], q: float) -> int:
    total = sum(hist.values())
    if total <= 0:
        return 0
    target = math.ceil(total * q)
    acc = 0
    for k in sorted(hist.keys()):
        acc += hist[k]
        if acc >= target:
            return k
    return max(hist.keys())


def safe_div(numerator: float, denominator: float) -> float:
    return (numerator / denominator) if denominator > 0 else 0.0


def append_jsonl(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _metric_path_get(payload: dict[str, Any], path: str) -> tuple[Any, bool]:
    cur: Any = payload
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return (None, False)
    return (cur, True)


def _eval_operator(observed: Any, operator: str, target: Any) -> bool:
    if observed is None and operator in ("<", "<=", ">", ">=", "between"):
        return False
    try:
        if operator == "<":
            return observed < target
        if operator == "<=":
            return observed <= target
        if operator == ">":
            return observed > target
        if operator == ">=":
            return observed >= target
        if operator == "==":
            return observed == target
        if operator == "!=":
            return observed != target
        if operator == "between":
            if not isinstance(target, dict):
                return False
            low = target.get("min")
            high = target.get("max")
            if low is None or high is None:
                return False
            return low <= observed <= high
    except TypeError:
        return False
    raise ValueError(f"unsupported operator: {operator}")


def _deviation(observed: Any, operator: str, target: Any) -> float | None:
    if not isinstance(observed, (int, float)):
        return None
    if operator in ("<", "<=") and isinstance(target, (int, float)):
        return float(observed - target)
    if operator in (">", ">=") and isinstance(target, (int, float)):
        return float(target - observed)
    if operator == "between" and isinstance(target, dict):
        low = target.get("min")
        high = target.get("max")
        if isinstance(low, (int, float)) and observed < low:
            return float(low - observed)
        if isinstance(high, (int, float)) and observed > high:
            return float(observed - high)
        return 0.0
    return 0.0


def evaluate_guideline_comparison(summary: dict[str, Any], rules_path: Path) -> dict[str, Any]:
    if not rules_path.exists():
        return {
            "guideline_id": "unknown",
            "rules_path": str(rules_path),
            "overall_status": "ERROR",
            "error": "rules_file_not_found",
            "checks": [],
        }
    try:
        rules_payload = json.loads(rules_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "guideline_id": "unknown",
            "rules_path": str(rules_path),
            "overall_status": "ERROR",
            "error": "rules_json_parse_failed",
            "checks": [],
        }

    checks = rules_payload.get("checks", [])
    if not isinstance(checks, list):
        return {
            "guideline_id": rules_payload.get("guideline_id", "unknown"),
            "rules_path": str(rules_path),
            "overall_status": "ERROR",
            "error": "rules_checks_not_list",
            "checks": [],
        }

    results: list[dict[str, Any]] = []
    pass_count = 0
    fail_count = 0
    na_count = 0
    missing_count = 0
    for check in checks:
        if not isinstance(check, dict):
            continue
        row = {
            "id": check.get("id", "UNKNOWN"),
            "section": check.get("section", "General"),
            "severity": check.get("severity", "medium"),
            "description": check.get("description", ""),
            "path": check.get("path", ""),
            "operator": check.get("operator", ""),
            "target": check.get("target"),
            "status": "missing",
        }
        when = check.get("when")
        if isinstance(when, dict):
            when_path = str(when.get("path", ""))
            when_op = str(when.get("operator", "=="))
            when_target = when.get("target")
            when_observed, when_ok = _metric_path_get(summary, when_path)
            row["when"] = {
                "path": when_path,
                "operator": when_op,
                "target": when_target,
                "observed": when_observed if when_ok else None,
            }
            if not when_ok:
                row["status"] = "missing"
                row["error"] = f"missing_when_path:{when_path}"
                missing_count += 1
                results.append(row)
                continue
            try:
                when_passed = _eval_operator(when_observed, when_op, when_target)
            except Exception as exc:  # noqa: BLE001
                row["status"] = "missing"
                row["error"] = f"when_eval_error:{exc.__class__.__name__}"
                missing_count += 1
                results.append(row)
                continue
            if not when_passed:
                row["status"] = "not_applicable"
                na_count += 1
                results.append(row)
                continue

        path = str(check.get("path", ""))
        operator = str(check.get("operator", "=="))
        target = check.get("target")
        observed, found = _metric_path_get(summary, path)
        if not found:
            row["status"] = "missing"
            row["error"] = f"missing_path:{path}"
            missing_count += 1
            results.append(row)
            continue
        row["observed"] = observed
        try:
            passed = _eval_operator(observed, operator, target)
        except Exception as exc:  # noqa: BLE001
            row["status"] = "missing"
            row["error"] = f"eval_error:{exc.__class__.__name__}"
            missing_count += 1
            results.append(row)
            continue
        row["deviation"] = _deviation(observed, operator, target)
        if passed:
            row["status"] = "pass"
            pass_count += 1
        else:
            row["status"] = "fail"
            fail_count += 1
        results.append(row)

    hard_fail_count = sum(1 for r in results if r.get("status") == "fail" and r.get("severity") == "high")
    overall_status = "FAIL" if (fail_count > 0 or missing_count > 0) else "PASS"
    return {
        "guideline_id": rules_payload.get("guideline_id", "unknown"),
        "rules_path": str(rules_path),
        "evaluated_at": utc_now(),
        "overall_status": overall_status,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "not_applicable_count": na_count,
        "missing_count": missing_count,
        "hard_fail_count": hard_fail_count,
        "check_count": len(results),
        "failed_check_ids": [r.get("id") for r in results if r.get("status") == "fail"],
        "checks": results,
    }


def classify_volatility(zero_win_rate: float, loss_streak_p95: int, tail_dependency: float) -> str:
    if zero_win_rate > 0.82 or loss_streak_p95 > 18 or tail_dependency > 0.50:
        return "Very High"
    if zero_win_rate >= 0.75 or loss_streak_p95 >= 13 or tail_dependency >= 0.35:
        return "High"
    if zero_win_rate >= 0.65 or loss_streak_p95 >= 9 or tail_dependency >= 0.20:
        return "Medium"
    return "Low"


def classify_experience_archetype(
    zero_win_rate: float,
    big_win_x10_rate: float,
    tail_dependency: float,
    profit_spin_rate: float,
) -> str:
    if zero_win_rate >= 0.75 and tail_dependency >= 0.35 and big_win_x10_rate >= 0.015:
        return "Boom-Bust"
    if zero_win_rate >= 0.75 and big_win_x10_rate < 0.015:
        return "Grindy"
    if zero_win_rate < 0.75 and 0.08 <= profit_spin_rate <= 0.16 and tail_dependency < 0.35:
        return "Balanced"
    if zero_win_rate >= 0.78:
        return "Grindy"
    return "Balanced"


def blank_like_symbol(symbol: str) -> bool:
    s = symbol.lower()
    return ("blank" in s) or ("empty" in s) or (s == "none")


def make_payload(
    machine: str,
    rtp_mode: int,
    bet: int,
    spin_times: int,
    robot_count: int,
    init_credits: int,
    reset_each_spin: bool,
    continue_after_bankrupt: bool,
) -> dict[str, Any]:
    return {
        "MachineName": machine,
        "InitCreditsStr": str(init_credits),
        "BetStrategy": 0,
        "BetOriginStr": str(bet),
        "SpinTimes": int(spin_times),
        "RtpId": int(rtp_mode),
        "ShouldTestLuckyGame": False,
        "ContinueAfterBankrupt": bool(continue_after_bankrupt),
        "ResetPlayerStateAfterEachSpin": bool(reset_each_spin),
        "RobotCount": int(robot_count),
        "OutputAllRobotResult": True,
    }


def return_bucket(ret_x: float) -> str:
    if ret_x <= 0.0:
        return "eq0"
    if ret_x < 1.0:
        return "gt0_lt1"
    if ret_x < 5.0:
        return "ge1_lt5"
    if ret_x < 10.0:
        return "ge5_lt10"
    if ret_x < 20.0:
        return "ge10_lt20"
    if ret_x < 50.0:
        return "ge20_lt50"
    if ret_x < 100.0:
        return "ge50_lt100"
    if ret_x < 200.0:
        return "ge100_lt200"
    if ret_x < 500.0:
        return "ge200_lt500"
    if ret_x < 1000.0:
        return "ge500_lt1000"
    if ret_x < 5000.0:
        return "ge1000_lt5000"
    return "ge5000"


def build_multiplier_bucket_rows(
    bucket_spins: dict[str, int],
    bucket_bet: dict[str, float],
    bucket_win: dict[str, float],
    total_spins: int,
    total_bet: float,
    total_win: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label in RETURN_BUCKET_ORDER:
        spin_count = int(bucket_spins.get(label, 0))
        bet_sum = float(bucket_bet.get(label, 0.0))
        win_sum = float(bucket_win.get(label, 0.0))
        rows.append(
            {
                "bucket": label,
                "spin_count": spin_count,
                "spin_rate": (spin_count / total_spins) if total_spins > 0 else 0.0,
                "avg_return_x_in_bucket": (win_sum / bet_sum) if bet_sum > 0 else 0.0,
                "rtp_contribution_pp": (win_sum / total_bet) * 100.0 if total_bet > 0 else 0.0,
                "win_share": (win_sum / total_win) if total_win > 0 else 0.0,
            }
        )
    return rows


def run_sampling_chunk(
    chunk_index: int,
    machine: str,
    rtp_mode: int,
    bet: int,
    spin_times: int,
    robot_count: int,
    timeout: float,
) -> dict[str, Any]:
    payload = make_payload(
        machine=machine,
        rtp_mode=rtp_mode,
        bet=bet,
        spin_times=spin_times,
        robot_count=robot_count,
        init_credits=10**14,
        reset_each_spin=True,
        continue_after_bankrupt=True,
    )

    started = time.time()
    try:
        resp = post_json(payload, timeout)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "index": chunk_index, "error": f"request_failed_http_{exc.code}"}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {
            "ok": False,
            "index": chunk_index,
            "error": f"request_failed_network_{exc.__class__.__name__}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "index": chunk_index,
            "error": f"request_failed_{exc.__class__.__name__}",
        }

    # Top-level shape sanity. Different machines can return slightly
    # different envelopes (M14 returns list-of-robots, exploratory probes
    # of new machines have surfaced single-dict variants). Catch and
    # report explicitly so the operator can ask us to add support for the
    # new shape rather than seeing silent all-zero data. The downstream
    # code path assumes resp is a non-empty list of robot dicts.
    if not isinstance(resp, list):
        sample_keys = list(resp.keys())[:6] if isinstance(resp, dict) else None
        detail = (
            f"got_dict_keys={sample_keys}"
            if sample_keys is not None
            else f"got_type={type(resp).__name__}"
        )
        return {
            "ok": False,
            "index": chunk_index,
            "error": f"response_shape_unexpected:expected_list:{detail}",
        }
    if not resp:
        return {"ok": False, "index": chunk_index, "error": "parse_failed_empty_response"}
    if not any(isinstance(robot, dict) for robot in resp):
        item_types = sorted({type(item).__name__ for item in resp[:5]})
        return {
            "ok": False,
            "index": chunk_index,
            "error": f"response_shape_unexpected:expected_robot_dicts:item_types={item_types}",
        }

    # Capture the server-side analysisResult for cross-check. Each robot's
    # analysisResult is a string-encoded JSON {"TotalWin", "FeatureWin",
    # "SummaryWin"} where TotalWin maps payout_id -> {WinCredits, ...,
    # Times}. Summing WinCredits across all keys yields the server's view
    # of total credits won this chunk; compared against our parsed
    # chunk_win it surfaces any drift between our aggregator and the
    # upstream's. Best-effort: any malformed analysisResult is skipped
    # (no crash; the sanity check just won't include that robot).
    upstream_chunk_total_win = 0.0
    upstream_chunk_robots_seen = 0
    for robot in resp:
        if not isinstance(robot, dict):
            continue
        ar = robot.get("analysisResult")
        if not isinstance(ar, str):
            continue
        try:
            parsed = json.loads(ar)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        tw = parsed.get("TotalWin") if isinstance(parsed, dict) else None
        if isinstance(tw, str):
            try:
                tw = json.loads(tw)
            except (json.JSONDecodeError, TypeError, ValueError):
                tw = None
        if not isinstance(tw, dict):
            continue
        upstream_chunk_robots_seen += 1
        for v in tw.values():
            if isinstance(v, dict):
                upstream_chunk_total_win += to_float(v.get("WinCredits"), default=0.0)

    # Schema sanity check on the first non-empty round. Without this, an
    # upstream field rename (e.g. WinCredits -> winCredits) would slip
    # through every .get(default=0) fallback in the parsing loop and
    # silently produce all-zero metrics. _watch_run will surface the
    # "schema_drift_missing_fields:..." reason in error_message so the
    # operator sees exactly which field went missing.
    schema_missing = _check_round_schema(resp)
    if schema_missing:
        return {
            "ok": False,
            "index": chunk_index,
            "error": "schema_drift_missing_fields:" + ",".join(schema_missing),
        }

    chunk_spins = 0
    chunk_bet = 0.0
    chunk_win = 0.0

    ret_count = 0
    ret_sum = 0.0
    ret_sq_sum = 0.0
    max_return_x = 0.0

    win_spins = 0
    loss_spins = 0
    profit_spins = 0
    breakeven_or_more_spins = 0
    big_win_x10_spins = 0
    win_sum = 0.0

    payline_hits: dict[str, int] = defaultdict(int)
    payline_win_approx: dict[str, float] = defaultdict(float)
    symbol_counts: dict[str, int] = defaultdict(int)
    symbol_counts_by_col: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total_symbol_slots = 0

    loss_streak_hist: dict[int, int] = defaultdict(int)
    win_streak_hist: dict[int, int] = defaultdict(int)
    max_loss_streak = 0
    max_win_streak = 0

    lack_credit_spins = 0
    multiplier_bucket_spins: dict[str, int] = defaultdict(int)
    multiplier_bucket_bet: dict[str, float] = defaultdict(float)
    multiplier_bucket_win: dict[str, float] = defaultdict(float)

    # Per-PayoutGroupId tally. Both M14 and M272 mode 1/2 always return
    # PayoutGroupId=0 in practice (the field doesn't differentiate), so
    # the drilldown built from this is informationally empty; kept for
    # backward compat in case other modes / machines actually fill it.
    payout_group_hits: dict[int, int] = defaultdict(int)
    payout_group_win: dict[int, float] = defaultdict(float)

    # Per-PayoutId tally from PayoutIdToWinAmount. This is the actual
    # payout-source breakdown the operator wants ("PayoutId 1 contributes
    # 73% of RTP via 333,300 win"). Both M14 and M272 winning rounds
    # populate it (unlike PayoutGroupId which is always 0). hit_count
    # increments per (round, payout_id) appearance, win sums the amount.
    payout_id_hits: dict[str, int] = defaultdict(int)
    payout_id_win: dict[str, float] = defaultdict(float)

    # Per-SpinType tally. M14 mode 1 only emits SpinType=1 (Normal).
    # M272 mode 1 emits 140 (main) + 126 (collect/bonus re-spin); mode
    # 2 has ~36% bonus rounds. Tallying per type lets the drilldown show
    # how much of total RTP comes from main vs bonus, and what fraction
    # of round volume is bonus -- a key insight for collect-mechanic
    # machines that the aggregate RTP / hit_rate alone can't reveal.
    spin_type_spins: dict[int, int] = defaultdict(int)
    spin_type_bet: dict[int, float] = defaultdict(float)
    spin_type_win: dict[int, float] = defaultdict(float)
    spin_type_wins: dict[int, int] = defaultdict(int)  # count of winning rounds per type

    # Collect-mechanic accumulation. M272's mode 1/2 carries CollectCount
    # (per-robot monotonic counter of triggered collects) and AccCredits
    # (cumulative collected credits). M14 has neither; chunk_collect_seen
    # stays at 0 and the summary marks the surface as not applicable.
    chunk_collect_count_total = 0  # sum of max CollectCount across robots
    chunk_acc_credits_max = 0      # peak AccCredits seen this chunk
    chunk_collect_seen = 0         # robots whose rounds carried the fields

    # Per-payline winning-symbol inference. The API returns
    # PayoutByPayline (which line ids paid) and StopSymbolsByCol (the
    # 5 columns of stopped symbols), but no direct payline->position
    # mapping. Heuristic: classic slots pay 3+ same symbols left-to-
    # right, so the symbol that appears in the leftmost three columns'
    # stopped sets is almost certainly the winner for any line that
    # hit on this spin. We tally per-(payline_id, symbol) frequency so
    # the drilldown can show which symbols carry each payline's RTP.
    payline_winning_symbols: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    for robot in resp:
        if not isinstance(robot, dict):
            continue
        rounds = parse_rounds(robot)
        cur_loss = 0
        cur_win = 0
        # Per-robot collect tracking: max CollectCount + max AccCredits
        # observed within this robot's rounds.
        robot_max_collect_count = 0
        robot_max_acc_credits = 0
        robot_collect_observed = False

        for r in rounds:
            if not isinstance(r, dict):
                continue

            bet_amt = to_float(r.get("BetAmount"), default=0.0)
            if bet_amt <= 0.0:
                bet_amt = to_float(r.get("CostCredits"), default=float(bet))
            if bet_amt <= 0.0:
                bet_amt = float(bet)

            win_amt = to_float(r.get("WinCredits"), default=0.0)
            chunk_spins += 1
            chunk_bet += bet_amt
            chunk_win += win_amt

            ret_x = (win_amt / bet_amt) if bet_amt > 0 else 0.0
            max_return_x = max(max_return_x, ret_x)
            ret_count += 1
            ret_sum += ret_x
            ret_sq_sum += ret_x * ret_x
            bucket = return_bucket(ret_x)
            multiplier_bucket_spins[bucket] += 1
            multiplier_bucket_bet[bucket] += bet_amt
            multiplier_bucket_win[bucket] += win_amt

            if win_amt > 0:
                win_spins += 1
                win_sum += win_amt
                if win_amt > bet_amt:
                    profit_spins += 1
                if win_amt >= bet_amt:
                    breakeven_or_more_spins += 1
                if win_amt >= 10.0 * bet_amt:
                    big_win_x10_spins += 1

                if cur_loss > 0:
                    loss_streak_hist[cur_loss] += 1
                    max_loss_streak = max(max_loss_streak, cur_loss)
                    cur_loss = 0
                cur_win += 1
            else:
                loss_spins += 1
                if cur_win > 0:
                    win_streak_hist[cur_win] += 1
                    max_win_streak = max(max_win_streak, cur_win)
                    cur_win = 0
                cur_loss += 1

            if bool(r.get("IsLackCreditsSpin", False)):
                lack_credit_spins += 1

            # PayoutGroupId aggregation: each spin reports one group id.
            # Group 0 means "no payout"; non-zero ids carry the win.
            try:
                pg_id = int(r.get("PayoutGroupId", 0) or 0)
            except (TypeError, ValueError):
                pg_id = 0
            payout_group_hits[pg_id] += 1
            payout_group_win[pg_id] += win_amt

            # SpinType per-spin tally. Type semantics are machine-specific
            # (M14: 1; M272: 140 main + 126 bonus; future machines may
            # introduce new types). Aggregating spins/bet/win per type
            # lets the drilldown show per-mechanic RTP and bonus-share
            # without us hardcoding any meaning.
            try:
                sp_type = int(r.get("SpinType", 0) or 0)
            except (TypeError, ValueError):
                sp_type = 0
            spin_type_spins[sp_type] += 1
            spin_type_bet[sp_type] += bet_amt
            spin_type_win[sp_type] += win_amt
            if win_amt > 0:
                spin_type_wins[sp_type] += 1

            # Collect mechanic (M272+): track max CollectCount (per-robot
            # monotonic counter of triggered collect bonuses) and max
            # AccCredits (peak accumulated credit balance). Fields are
            # absent on M14 / non-collect machines -- we only mark this
            # robot as "observed" when at least one of the two appears.
            cc_raw = r.get("CollectCount")
            ac_raw = r.get("AccCredits")
            if cc_raw is not None or ac_raw is not None:
                robot_collect_observed = True
            try:
                cc_int = int(cc_raw or 0)
            except (TypeError, ValueError):
                cc_int = 0
            try:
                ac_int = int(ac_raw or 0)
            except (TypeError, ValueError):
                ac_int = 0
            if cc_int > robot_max_collect_count:
                robot_max_collect_count = cc_int
            if ac_int > robot_max_acc_credits:
                robot_max_acc_credits = ac_int

            # PayoutIdToWinAmount aggregation: dict of {payout_id: win}
            # populated on winning rounds. Sum win and count occurrences
            # per id so the drilldown can rank by total contribution.
            pid_to_win = r.get("PayoutIdToWinAmount") or {}
            if isinstance(pid_to_win, dict):
                for pid_raw, amount_raw in pid_to_win.items():
                    pid = str(pid_raw)
                    payout_id_hits[pid] += 1
                    payout_id_win[pid] += to_float(amount_raw, default=0.0)

            line_ids = parse_paylines(str(r.get("PayoutByPayline") or ""))
            if line_ids:
                share = win_amt / len(line_ids)
                for lid in line_ids:
                    payline_hits[lid] += 1
                    payline_win_approx[lid] += share

            stop_cols = r.get("StopSymbolsByCol") or []
            col_symbol_sets: list[set[str]] = []
            if isinstance(stop_cols, list):
                for ci, col_text in enumerate(stop_cols):
                    col_syms = split_symbols(str(col_text))
                    col_symbol_sets.append({s for s in col_syms if s})
                    for sym in col_syms:
                        symbol_counts[sym] += 1
                        symbol_counts_by_col[ci][sym] += 1
                        total_symbol_slots += 1

            # Infer the winning symbol(s) for each line that paid this
            # spin. Take the intersection of stopped-symbol sets across
            # the leftmost three columns (classic slot pays 3+ matching
            # symbols left-to-right) AFTER filtering blank-like symbols
            # (paylines almost never pay blanks; crediting them is
            # noise when blanks happen to appear in all 3 cols beside
            # the actual winner). If no intersection (atypical bonus
            # payout), fall back to any non-blank symbol on the leftmost
            # column so the line is still represented.
            if line_ids and len(col_symbol_sets) >= 3:
                c0 = {s for s in col_symbol_sets[0] if not blank_like_symbol(s)}
                c1 = {s for s in col_symbol_sets[1] if not blank_like_symbol(s)}
                c2 = {s for s in col_symbol_sets[2] if not blank_like_symbol(s)}
                first3 = c0 & c1 & c2
                if not first3 and c0:
                    first3 = {next(iter(c0))}
                for lid in line_ids:
                    for sym in first3:
                        payline_winning_symbols[lid][sym] += 1

        if cur_loss > 0:
            loss_streak_hist[cur_loss] += 1
            max_loss_streak = max(max_loss_streak, cur_loss)
        if cur_win > 0:
            win_streak_hist[cur_win] += 1
            max_win_streak = max(max_win_streak, cur_win)

        # Roll the per-robot collect totals into the chunk-level tally.
        chunk_collect_count_total += robot_max_collect_count
        if robot_max_acc_credits > chunk_acc_credits_max:
            chunk_acc_credits_max = robot_max_acc_credits
        if robot_collect_observed:
            chunk_collect_seen += 1

    if chunk_spins <= 0 or chunk_bet <= 0:
        return {"ok": False, "index": chunk_index, "error": "parse_failed_zero_chunk"}

    return {
        "ok": True,
        "index": chunk_index,
        "elapsed_seconds": round(time.time() - started, 3),
        "spins": chunk_spins,
        "bet": chunk_bet,
        "win": chunk_win,
        "ret_count": ret_count,
        "ret_sum": ret_sum,
        "ret_sq_sum": ret_sq_sum,
        "max_return_x": max_return_x,
        "win_spins": win_spins,
        "loss_spins": loss_spins,
        "profit_spins": profit_spins,
        "breakeven_or_more_spins": breakeven_or_more_spins,
        "big_win_x10_spins": big_win_x10_spins,
        "win_sum": win_sum,
        "lack_credit_spins": lack_credit_spins,
        "payline_hits": dict(payline_hits),
        "payline_win_approx": dict(payline_win_approx),
        "payline_winning_symbols": {
            str(lid): dict(syms) for lid, syms in payline_winning_symbols.items()
        },
        "symbol_counts": dict(symbol_counts),
        "symbol_counts_by_col": {str(k): dict(v) for k, v in symbol_counts_by_col.items()},
        "total_symbol_slots": total_symbol_slots,
        "loss_streak_hist": dict(loss_streak_hist),
        "win_streak_hist": dict(win_streak_hist),
        "max_loss_streak": max_loss_streak,
        "max_win_streak": max_win_streak,
        "multiplier_bucket_spins": dict(multiplier_bucket_spins),
        "multiplier_bucket_bet": dict(multiplier_bucket_bet),
        "multiplier_bucket_win": dict(multiplier_bucket_win),
        "payout_group_hits": {str(k): v for k, v in payout_group_hits.items()},
        "payout_group_win": {str(k): v for k, v in payout_group_win.items()},
        "payout_id_hits": dict(payout_id_hits),
        "payout_id_win": dict(payout_id_win),
        "spin_type_spins": {str(k): v for k, v in spin_type_spins.items()},
        "spin_type_bet": {str(k): v for k, v in spin_type_bet.items()},
        "spin_type_win": {str(k): v for k, v in spin_type_win.items()},
        "spin_type_wins": {str(k): v for k, v in spin_type_wins.items()},
        "upstream_chunk_total_win": upstream_chunk_total_win,
        "upstream_chunk_robots_seen": upstream_chunk_robots_seen,
        "collect_count_total": chunk_collect_count_total,
        "acc_credits_max": chunk_acc_credits_max,
        "collect_robots_seen": chunk_collect_seen,
    }


def run_bankruptcy_probe(
    machine: str,
    rtp_mode: int,
    bet: int,
    session_spins: int,
    robot_count: int,
    bankroll_mult: int,
    timeout: float,
) -> dict[str, Any]:
    init_credits = bankroll_mult * bet
    payload = make_payload(
        machine=machine,
        rtp_mode=rtp_mode,
        bet=bet,
        spin_times=session_spins,
        robot_count=robot_count,
        init_credits=init_credits,
        reset_each_spin=False,
        continue_after_bankrupt=False,
    )
    resp = post_json(payload, timeout)
    if not isinstance(resp, list):
        raise ValueError("bankruptcy probe response is not list")

    bankrupt = 0
    completed = 0
    spins_done_sum = 0
    for robot in resp:
        if not isinstance(robot, dict):
            continue
        rounds = parse_rounds(robot)
        spins_done = len(rounds)
        spins_done_sum += spins_done
        if spins_done < session_spins:
            bankrupt += 1
        else:
            completed += 1

    total = len(resp)
    return {
        "bankroll_multiplier": bankroll_mult,
        "init_credits": init_credits,
        "session_spins": session_spins,
        "robots": total,
        "bankrupt_robots": bankrupt,
        "completed_robots": completed,
        "bankruptcy_rate": (bankrupt / total) if total > 0 else 0.0,
        "avg_spins_completed": (spins_done_sum / total) if total > 0 else 0.0,
    }


def main() -> int:
    args = parse_args()

    if args.bet <= 0:
        raise SystemExit("--bet must be positive")
    if args.target_halfwidth_pp <= 0:
        raise SystemExit("--target-halfwidth-pp must be positive")
    if args.chunk_spin_times <= 0 or args.chunk_robot_count <= 0:
        raise SystemExit("--chunk-spin-times and --chunk-robot-count must be positive")
    if args.batch_concurrency <= 0 or args.max_chunks <= 0 or args.timeout <= 0:
        raise SystemExit("--batch-concurrency, --max-chunks, --timeout must be positive")
    if args.bankruptcy_session_spins <= 0:
        raise SystemExit("--bankruptcy-session-spins must be positive")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    run_id = args.run_id or f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    progress_file = args.progress_file

    started_at = utc_now()
    t0 = time.time()
    append_jsonl(
        progress_file,
        {
            "event": "started",
            "run_id": run_id,
            "machine": args.machine,
            "mode": args.rtp_mode,
            "target_halfwidth_pp": args.target_halfwidth_pp,
            "chunk_spin_times": args.chunk_spin_times,
            "chunk_robot_count": args.chunk_robot_count,
            "batch_concurrency": args.batch_concurrency,
            "started_at": started_at,
        },
    )

    total_spins = 0
    total_bet = 0.0
    total_win = 0.0
    chunk_rtps_pct: list[float] = []

    ret_count = 0
    ret_sum = 0.0
    ret_sq_sum = 0.0
    max_observed_return_x = 0.0

    win_spins = 0
    loss_spins = 0
    profit_spins = 0
    breakeven_or_more_spins = 0
    big_win_x10_spins = 0
    win_sum = 0.0

    payline_hits: dict[str, int] = defaultdict(int)
    payline_win_approx: dict[str, float] = defaultdict(float)
    payline_winning_symbols: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    symbol_counts: dict[str, int] = defaultdict(int)
    symbol_counts_by_col: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total_symbol_slots = 0

    loss_streak_hist: dict[int, int] = defaultdict(int)
    win_streak_hist: dict[int, int] = defaultdict(int)
    max_loss_streak = 0
    max_win_streak = 0

    multiplier_bucket_spins: dict[str, int] = defaultdict(int)
    multiplier_bucket_bet: dict[str, float] = defaultdict(float)
    multiplier_bucket_win: dict[str, float] = defaultdict(float)

    payout_group_hits: dict[int, int] = defaultdict(int)
    payout_group_win: dict[int, float] = defaultdict(float)
    payout_id_hits: dict[str, int] = defaultdict(int)
    payout_id_win: dict[str, float] = defaultdict(float)
    spin_type_spins: dict[int, int] = defaultdict(int)
    spin_type_bet: dict[int, float] = defaultdict(float)
    spin_type_win: dict[int, float] = defaultdict(float)
    spin_type_wins: dict[int, int] = defaultdict(int)
    upstream_total_win = 0.0
    upstream_robots_seen = 0
    collect_count_total = 0
    acc_credits_max_global = 0
    collect_robots_seen_total = 0

    lack_credit_spins = 0
    chunks = 0
    stop_reason = "max_chunks_reached"
    achieved_halfwidth_pp: float | None = None
    next_chunk_index = 1

    while next_chunk_index <= args.max_chunks:
        remaining = args.max_chunks - chunks
        batch_size = min(args.batch_concurrency, remaining)
        if batch_size <= 0:
            break

        indices = list(range(next_chunk_index, next_chunk_index + batch_size))
        next_chunk_index += batch_size

        batch_results: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = [
                executor.submit(
                    run_sampling_chunk,
                    idx,
                    args.machine,
                    args.rtp_mode,
                    args.bet,
                    args.chunk_spin_times,
                    args.chunk_robot_count,
                    args.timeout,
                )
                for idx in indices
            ]
            for future in concurrent.futures.as_completed(futures):
                batch_results.append(future.result())

        error = next((r for r in batch_results if not bool(r.get("ok"))), None)
        if error is not None:
            stop_reason = str(error.get("error") or "unknown_error")
            append_jsonl(
                progress_file,
                {
                    "event": "failed",
                    "run_id": run_id,
                    "reason": stop_reason,
                    "chunks": chunks,
                    "total_spins": total_spins,
                    "elapsed_seconds": round(time.time() - t0, 3),
                    "ts": utc_now(),
                },
            )
            break

        for rec in sorted(batch_results, key=lambda x: int(x["index"])):
            chunks += 1
            spins = int(rec["spins"])
            bet_amt = float(rec["bet"])
            win_amt = float(rec["win"])

            total_spins += spins
            total_bet += bet_amt
            total_win += win_amt

            chunk_rtp = (win_amt / bet_amt) * 100.0 if bet_amt > 0 else 0.0
            chunk_rtps_pct.append(chunk_rtp)

            ret_count += int(rec["ret_count"])
            ret_sum += float(rec["ret_sum"])
            ret_sq_sum += float(rec["ret_sq_sum"])
            max_observed_return_x = max(max_observed_return_x, float(rec["max_return_x"]))

            win_spins += int(rec["win_spins"])
            loss_spins += int(rec["loss_spins"])
            profit_spins += int(rec["profit_spins"])
            breakeven_or_more_spins += int(rec["breakeven_or_more_spins"])
            big_win_x10_spins += int(rec["big_win_x10_spins"])
            win_sum += float(rec["win_sum"])
            lack_credit_spins += int(rec["lack_credit_spins"])

            for lid, c in rec["payline_hits"].items():
                payline_hits[str(lid)] += int(c)
            for lid, w in rec["payline_win_approx"].items():
                payline_win_approx[str(lid)] += float(w)
            # payline_winning_symbols was added in the symbol-inference
            # commit; old chunk records (pre-feature) won't have it.
            for lid, smap in (rec.get("payline_winning_symbols") or {}).items():
                if isinstance(smap, dict):
                    for sym, c in smap.items():
                        payline_winning_symbols[str(lid)][str(sym)] += int(c)

            for sym, c in rec["symbol_counts"].items():
                symbol_counts[str(sym)] += int(c)
            for ci_text, cmap in rec["symbol_counts_by_col"].items():
                ci = int(ci_text)
                if isinstance(cmap, dict):
                    for sym, c in cmap.items():
                        symbol_counts_by_col[ci][str(sym)] += int(c)

            total_symbol_slots += int(rec["total_symbol_slots"])

            for k, c in rec["loss_streak_hist"].items():
                loss_streak_hist[int(k)] += int(c)
            for k, c in rec["win_streak_hist"].items():
                win_streak_hist[int(k)] += int(c)
            max_loss_streak = max(max_loss_streak, int(rec["max_loss_streak"]))
            max_win_streak = max(max_win_streak, int(rec["max_win_streak"]))

            for k, c in rec["multiplier_bucket_spins"].items():
                multiplier_bucket_spins[str(k)] += int(c)
            for k, v in rec["multiplier_bucket_bet"].items():
                multiplier_bucket_bet[str(k)] += float(v)
            for k, v in rec["multiplier_bucket_win"].items():
                multiplier_bucket_win[str(k)] += float(v)

            for k, c in (rec.get("payout_group_hits") or {}).items():
                payout_group_hits[int(k)] += int(c)
            for k, w in (rec.get("payout_group_win") or {}).items():
                payout_group_win[int(k)] += float(w)
            # payout_id_* added in the PayoutIdToWinAmount commit; old
            # chunk records (pre-feature) tolerate missing via .get().
            for pid, c in (rec.get("payout_id_hits") or {}).items():
                payout_id_hits[str(pid)] += int(c)
            for pid, w in (rec.get("payout_id_win") or {}).items():
                payout_id_win[str(pid)] += float(w)
            # spin_type_* added in the SpinType-breakdown commit; old
            # chunk records tolerate missing via .get().
            for st, c in (rec.get("spin_type_spins") or {}).items():
                spin_type_spins[int(st)] += int(c)
            for st, b in (rec.get("spin_type_bet") or {}).items():
                spin_type_bet[int(st)] += float(b)
            for st, w in (rec.get("spin_type_win") or {}).items():
                spin_type_win[int(st)] += float(w)
            for st, c in (rec.get("spin_type_wins") or {}).items():
                spin_type_wins[int(st)] += int(c)
            # upstream analysis cross-check (older chunk records lack
            # these fields; .get() default keeps the comparison neutral).
            upstream_total_win += float(rec.get("upstream_chunk_total_win", 0.0) or 0.0)
            upstream_robots_seen += int(rec.get("upstream_chunk_robots_seen", 0) or 0)
            # collect-mechanic accumulators (M272+; absent on M14).
            collect_count_total += int(rec.get("collect_count_total", 0) or 0)
            chunk_acc_max = int(rec.get("acc_credits_max", 0) or 0)
            if chunk_acc_max > acc_credits_max_global:
                acc_credits_max_global = chunk_acc_max
            collect_robots_seen_total += int(rec.get("collect_robots_seen", 0) or 0)

            hw = ci_halfwidth_pp(chunk_rtps_pct)
            if math.isfinite(hw):
                achieved_halfwidth_pp = hw

            current_rtp_pct = (total_win / total_bet) * 100.0 if total_bet > 0 else 0.0
            append_jsonl(
                progress_file,
                {
                    "event": "chunk_progress",
                    "run_id": run_id,
                    "chunk_index": chunks,
                    "total_spins": total_spins,
                    "current_rtp_pct": current_rtp_pct,
                    "current_halfwidth_pp": achieved_halfwidth_pp,
                    "target_halfwidth_pp": args.target_halfwidth_pp,
                    "elapsed_seconds": round(time.time() - t0, 3),
                    "ts": utc_now(),
                },
            )

        if len(chunk_rtps_pct) >= 2 and achieved_halfwidth_pp is not None:
            if achieved_halfwidth_pp <= args.target_halfwidth_pp:
                stop_reason = "target_ci_reached"
                break

    duration_seconds = round(time.time() - t0, 3)
    finished_at = utc_now()

    rtp_point_pct = (total_win / total_bet) * 100.0 if total_bet > 0 else 0.0
    ci_interval = None
    if achieved_halfwidth_pp is not None:
        ci_interval = [rtp_point_pct - achieved_halfwidth_pp, rtp_point_pct + achieved_halfwidth_pp]

    avg_return_x = (ret_sum / ret_count) if ret_count > 0 else 0.0
    if ret_count > 1:
        variance = (ret_sq_sum - (ret_sum * ret_sum / ret_count)) / (ret_count - 1)
        std_return_x = math.sqrt(max(variance, 0.0))
    else:
        std_return_x = 0.0

    hit_rate = (win_spins / total_spins) if total_spins > 0 else 0.0
    zero_win_rate = (loss_spins / total_spins) if total_spins > 0 else 0.0
    profit_spin_rate = (profit_spins / total_spins) if total_spins > 0 else 0.0
    breakeven_or_more_rate = (
        breakeven_or_more_spins / total_spins if total_spins > 0 else 0.0
    )
    big_win_x10_rate = (big_win_x10_spins / total_spins) if total_spins > 0 else 0.0
    avg_win_when_hit_x = (
        (win_sum / win_spins) / args.bet if win_spins > 0 and args.bet > 0 else 0.0
    )

    multiplier_bucket_rows = build_multiplier_bucket_rows(
        bucket_spins=multiplier_bucket_spins,
        bucket_bet=multiplier_bucket_bet,
        bucket_win=multiplier_bucket_win,
        total_spins=total_spins,
        total_bet=total_bet,
        total_win=total_win,
    )
    tail_spins_ge10 = sum(multiplier_bucket_spins.get(k, 0) for k in TAIL_GEX10_BUCKETS)
    tail_win_ge10 = sum(multiplier_bucket_win.get(k, 0.0) for k in TAIL_GEX10_BUCKETS)

    payline_rows = []
    for lid, hits in sorted(payline_hits.items(), key=lambda kv: kv[1], reverse=True):
        # Top winning symbols for this payline (heuristic: leftmost-3-col
        # intersection per spin). Take top 5 by frequency so the UI table
        # can show the dominant symbols without bloating the row.
        sym_counts = payline_winning_symbols.get(lid, {})
        top_syms = sorted(sym_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
        payline_rows.append(
            {
                "payline_id": lid,
                "hit_count": hits,
                "hit_rate": hits / total_spins if total_spins > 0 else 0.0,
                "approx_win_credits": payline_win_approx[lid],
                "approx_rtp_contribution_pp": (
                    (payline_win_approx[lid] / total_bet) * 100.0 if total_bet > 0 else 0.0
                ),
                "top_symbols": [{"symbol": s, "count": c} for s, c in top_syms],
            }
        )

    payout_group_rows: list[dict[str, Any]] = []
    for gid, hits in sorted(payout_group_hits.items(), key=lambda kv: kv[1], reverse=True):
        wins = float(payout_group_win.get(gid, 0.0))
        win_spins_in_group = hits if gid != 0 else 0
        payout_group_rows.append(
            {
                "group_id": int(gid),
                "hit_count": int(hits),
                "hit_rate": (hits / total_spins) if total_spins > 0 else 0.0,
                "total_win": wins,
                "avg_win_when_hit_x": (
                    (wins / win_spins_in_group) / args.bet
                    if win_spins_in_group > 0 and args.bet > 0
                    else 0.0
                ),
                "rtp_contribution_pp": (
                    (wins / total_bet) * 100.0 if total_bet > 0 else 0.0
                ),
            }
        )

    # SpinType breakdown: per-type spins / bet / win + share of total.
    # Order by spins desc so the dominant type lands first; for collect
    # mechanics this immediately surfaces "X% of rounds are bonus".
    spin_type_rows: list[dict[str, Any]] = []
    for st, spins in sorted(spin_type_spins.items(), key=lambda kv: -kv[1]):
        bet = float(spin_type_bet.get(st, 0.0))
        win = float(spin_type_win.get(st, 0.0))
        win_rounds = int(spin_type_wins.get(st, 0))
        spin_type_rows.append(
            {
                "spin_type": int(st),
                "spins": int(spins),
                "share_pct": (spins / total_spins) * 100.0 if total_spins > 0 else 0.0,
                "win_rounds": win_rounds,
                "hit_rate": (win_rounds / spins) if spins > 0 else 0.0,
                "total_bet": bet,
                "total_win": win,
                "rtp_pct": (win / bet) * 100.0 if bet > 0 else 0.0,
                "rtp_contribution_pp": (win / total_bet) * 100.0 if total_bet > 0 else 0.0,
            }
        )

    # PayoutIdToWinAmount-derived drilldown. Sort by total_win desc so the
    # operator immediately sees which payout ids carry the RTP. Unlike
    # payout_groups_top20 (which is informationally empty for M14/M272 mode
    # 1/2 because the field is always 0), this surface actually
    # discriminates between payout sources.
    payout_id_rows: list[dict[str, Any]] = []
    for pid, wins in sorted(payout_id_win.items(), key=lambda kv: kv[1], reverse=True):
        hits = int(payout_id_hits.get(pid, 0))
        wins_f = float(wins)
        payout_id_rows.append(
            {
                "payout_id": str(pid),
                "hit_count": hits,
                "hit_rate": (hits / total_spins) if total_spins > 0 else 0.0,
                "total_win": wins_f,
                "avg_win_when_hit": (wins_f / hits) if hits > 0 else 0.0,
                "rtp_contribution_pp": (
                    (wins_f / total_bet) * 100.0 if total_bet > 0 else 0.0
                ),
            }
        )

    symbol_rows = []
    for sym, cnt in sorted(symbol_counts.items(), key=lambda kv: kv[1], reverse=True):
        symbol_rows.append(
            {
                "symbol": sym,
                "count": cnt,
                "rate": cnt / total_symbol_slots if total_symbol_slots > 0 else 0.0,
            }
        )

    symbol_by_col_rows = {}
    for ci, cmap in symbol_counts_by_col.items():
        total_col = sum(cmap.values())
        rows = []
        for sym, cnt in sorted(cmap.items(), key=lambda kv: kv[1], reverse=True):
            rows.append(
                {
                    "symbol": sym,
                    "count": cnt,
                    "rate": cnt / total_col if total_col > 0 else 0.0,
                }
            )
        symbol_by_col_rows[str(ci)] = rows

    loss_streak_p50 = quantile_from_hist(loss_streak_hist, 0.50)
    loss_streak_p90 = quantile_from_hist(loss_streak_hist, 0.90)
    loss_streak_p95 = quantile_from_hist(loss_streak_hist, 0.95)
    win_streak_p50 = quantile_from_hist(win_streak_hist, 0.50)
    win_streak_p90 = quantile_from_hist(win_streak_hist, 0.90)
    win_streak_p95 = quantile_from_hist(win_streak_hist, 0.95)

    bankruptcy_rows = []
    mults = [
        int(x.strip())
        for x in args.bankruptcy_bankroll_multipliers.split(",")
        if x.strip()
    ]
    probe_robots = (
        args.bankruptcy_robot_count
        if args.bankruptcy_robot_count is not None
        else args.chunk_robot_count
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(mults))) as executor:
        future_map = {
            executor.submit(
                run_bankruptcy_probe,
                args.machine,
                args.rtp_mode,
                args.bet,
                args.bankruptcy_session_spins,
                probe_robots,
                m,
                args.timeout,
            ): m
            for m in mults
        }
        for future in concurrent.futures.as_completed(future_map):
            m = future_map[future]
            try:
                bankruptcy_rows.append(future.result())
            except Exception as exc:  # noqa: BLE001
                bankruptcy_rows.append(
                    {
                        "bankroll_multiplier": m,
                        "error": exc.__class__.__name__,
                    }
                )
    bankruptcy_rows.sort(key=lambda row: int(row.get("bankroll_multiplier", 0)))

    ci_met = achieved_halfwidth_pp is not None and achieved_halfwidth_pp <= args.target_halfwidth_pp
    sample_size_met = total_spins >= 2_000_000
    buckets_complete = len(multiplier_bucket_rows) == len(RETURN_BUCKET_ORDER)
    bankruptcy_ladder_met = sum(1 for row in bankruptcy_rows if "error" not in row) >= 3
    quality_label = (
        "REPORT_GRADE"
        if (ci_met and sample_size_met and buckets_complete and bankruptcy_ladder_met)
        else "EXPLORATORY"
    )

    recovery_gap = hit_rate - profit_spin_rate
    tail_rtp_contribution_pp_ge10x = (
        (tail_win_ge10 / total_bet) * 100.0 if total_bet > 0 else 0.0
    )
    tail_win_share_ge10x = tail_win_ge10 / total_win if total_win > 0 else 0.0
    tail_dependency = safe_div(tail_rtp_contribution_pp_ge10x, rtp_point_pct)

    volatility_class = classify_volatility(
        zero_win_rate=zero_win_rate,
        loss_streak_p95=loss_streak_p95,
        tail_dependency=tail_dependency,
    )
    experience_archetype = classify_experience_archetype(
        zero_win_rate=zero_win_rate,
        big_win_x10_rate=big_win_x10_rate,
        tail_dependency=tail_dependency,
        profit_spin_rate=profit_spin_rate,
    )

    payline_total_pp = sum(float(row["approx_rtp_contribution_pp"]) for row in payline_rows)
    payline_top1_share = (
        safe_div(float(payline_rows[0]["approx_rtp_contribution_pp"]), payline_total_pp)
        if payline_rows
        else 0.0
    )
    payline_top3_share = (
        safe_div(sum(float(row["approx_rtp_contribution_pp"]) for row in payline_rows[:3]), payline_total_pp)
        if payline_rows
        else 0.0
    )
    payline_top1_concentrated = payline_top1_share > 0.20
    payline_top3_concentrated = payline_top3_share > 0.55

    blank_like_total = sum(cnt for sym, cnt in symbol_counts.items() if blank_like_symbol(sym))
    blank_like_rate = safe_div(float(blank_like_total), float(total_symbol_slots))
    blank_like_rate_by_col: dict[str, float] = {}
    for ci, cmap in symbol_counts_by_col.items():
        total_col = sum(cmap.values())
        blank_col = sum(c for sym, c in cmap.items() if blank_like_symbol(sym))
        blank_like_rate_by_col[str(ci)] = safe_div(float(blank_col), float(total_col))
    if blank_like_rate_by_col:
        blank_like_col_spread = max(blank_like_rate_by_col.values()) - min(blank_like_rate_by_col.values())
    else:
        blank_like_col_spread = 0.0
    symbol_distribution_skew = blank_like_col_spread > 0.05

    bankruptcy_by_mult = {
        int(row["bankroll_multiplier"]): row
        for row in bankruptcy_rows
        if "error" not in row
    }
    x100_br = float(bankruptcy_by_mult.get(100, {}).get("bankruptcy_rate", 0.0))
    x200_br = float(bankruptcy_by_mult.get(200, {}).get("bankruptcy_rate", 0.0))
    x500_br = float(bankruptcy_by_mult.get(500, {}).get("bankruptcy_rate", 0.0))

    alerts: list[dict[str, str]] = []
    if not ci_met:
        alerts.append(
            {
                "code": "A1_CI_NOT_REACHED",
                "severity": "high",
                "message": "CI half-width target not reached.",
            }
        )
    if zero_win_rate > 0.80 and profit_spin_rate < 0.10:
        alerts.append(
            {
                "code": "A2_DRY_AND_LOW_PROFIT",
                "severity": "high",
                "message": "High dead-spin rate with low profit-spin rate.",
            }
        )
    if loss_streak_p95 >= 15:
        alerts.append(
            {
                "code": "A3_LONG_LOSS_STREAK",
                "severity": "medium",
                "message": "Loss streak p95 is high.",
            }
        )
    if tail_dependency >= 0.45:
        alerts.append(
            {
                "code": "A4_HIGH_TAIL_DEPENDENCY",
                "severity": "medium",
                "message": "RTP depends heavily on >=10x tail outcomes.",
            }
        )
    if x200_br >= 0.10:
        alerts.append(
            {
                "code": "A5_X200_BANKRUPTCY_HIGH",
                "severity": "high",
                "message": "x200 bankroll bankruptcy rate is above 10%.",
            }
        )
    if payline_top1_concentrated or payline_top3_concentrated:
        alerts.append(
            {
                "code": "A6_PAYLINE_CONCENTRATION",
                "severity": "medium",
                "message": "Payline RTP contribution is concentrated.",
            }
        )
    if symbol_distribution_skew:
        alerts.append(
            {
                "code": "A7_SYMBOL_SKEW",
                "severity": "medium",
                "message": "Blank-like symbol distribution spread across columns exceeds 5pp.",
            }
        )

    action_recommendations: list[str] = []
    if zero_win_rate > 0.80 or loss_streak_p95 >= 15:
        action_recommendations.append(
            "Increase low return bucket (gt0_lt1) to reduce dry feel."
        )
    if tail_dependency >= 0.45:
        action_recommendations.append(
            "Reduce >=10x tail RTP share slightly and reallocate to ge1_lt5."
        )
    if x200_br >= 0.10:
        action_recommendations.append(
            "Improve session survivability at x200 bankroll by raising mid-tier payout continuity."
        )
    if not action_recommendations:
        action_recommendations.append(
            "Profile is within baseline guardrails; run targeted A/B tests on mid buckets for finer tuning."
        )

    conclusion_data_confidence = (
        f"CI half-width={achieved_halfwidth_pp}, target<={args.target_halfwidth_pp}, spins={total_spins}, quality={quality_label}."
    )
    conclusion_player_feel = (
        f"{experience_archetype} feel with {volatility_class} volatility: zero_win_rate={zero_win_rate:.4f}, loss_streak_p95={loss_streak_p95}."
    )
    conclusion_rtp_structure = (
        f">=10x tail contributes {tail_rtp_contribution_pp_ge10x:.4f}pp RTP (dependency={tail_dependency:.4f})."
    )
    conclusion_session_risk = (
        f"Bankruptcy ladder: x100={x100_br:.4f}, x200={x200_br:.4f}, x500={x500_br:.4f}."
    )
    conclusion_design_action = action_recommendations[0]

    summary = {
        "report_id": f"impact_{args.machine}_mode{args.rtp_mode}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "run_id": run_id,
        "machine": args.machine,
        "mode": args.rtp_mode,
        "output_all_robots_result": True,
        "sampling": {
            "target_halfwidth_pp": args.target_halfwidth_pp,
            "achieved_halfwidth_pp": achieved_halfwidth_pp,
            "chunk_spin_times": args.chunk_spin_times,
            "chunk_robot_count": args.chunk_robot_count,
            "batch_concurrency": args.batch_concurrency,
            "chunks": chunks,
            "total_spins": total_spins,
            "stop_reason": stop_reason,
            "duration_seconds": duration_seconds,
            "started_at": started_at,
            "finished_at": finished_at,
        },
        "rtp": {
            "point_pct": rtp_point_pct,
            "ci95_interval_pct": ci_interval,
        },
        "storage": {
            "raw_round_data_persisted": False,
            "reason": "Only aggregated metrics are persisted to keep local storage bounded.",
        },
        "player_impact": {
            "volatility": {
                "avg_return_x": avg_return_x,
                "std_return_x": std_return_x,
                "max_observed_return_x": max_observed_return_x,
                "return_bucket_rate": {
                    row["bucket"]: row["spin_rate"]
                    for row in multiplier_bucket_rows
                },
            },
            "multiplier_profile": {
                "metric": "ret_x = win_credits / bet_credits",
                "buckets": multiplier_bucket_rows,
                "tail_spin_rate_ge10x": (
                    tail_spins_ge10 / total_spins if total_spins > 0 else 0.0
                ),
                "tail_rtp_contribution_pp_ge10x": tail_rtp_contribution_pp_ge10x,
                "tail_win_share_ge10x": tail_win_share_ge10x,
            },
            "hit_and_payout": {
                "win_hit_rate": hit_rate,
                "zero_win_rate": zero_win_rate,
                "profit_spin_rate": profit_spin_rate,
                "breakeven_or_more_rate": breakeven_or_more_rate,
                "big_win_x10_rate": big_win_x10_rate,
                "avg_win_when_hit_x": avg_win_when_hit_x,
                "lack_credit_spin_rate": (lack_credit_spins / total_spins) if total_spins > 0 else 0.0,
            },
            "streaks": {
                "loss_streak_p50": loss_streak_p50,
                "loss_streak_p90": loss_streak_p90,
                "loss_streak_p95": loss_streak_p95,
                "loss_streak_max": max_loss_streak,
                "win_streak_p50": win_streak_p50,
                "win_streak_p90": win_streak_p90,
                "win_streak_p95": win_streak_p95,
                "win_streak_max": max_win_streak,
            },
            "paylines_top20": payline_rows[:20],
            "payout_groups_top20": payout_group_rows[:20],
            "payout_ids_top20": payout_id_rows[:20],
            "spin_type_breakdown": spin_type_rows,
            "symbols_top20": symbol_rows[:20],
            "symbols_by_column_top10": {k: v[:10] for k, v in symbol_by_col_rows.items()},
            "bankruptcy_probe": bankruptcy_rows,
        },
        "upstream_analysis": {
            # Server-side analysisResult.TotalWin sum (across all chunk
            # responses that included it). Used as a sanity check
            # against our parsed total_win; persistent drift suggests
            # our aggregator misses a field or mis-counts a SpinType.
            "server_total_win": upstream_total_win,
            "our_total_win": total_win,
            "delta": total_win - upstream_total_win,
            "delta_pct": (
                ((total_win - upstream_total_win) / upstream_total_win) * 100.0
                if upstream_total_win > 0
                else None
            ),
            # Tolerate rounding to 0.5 credit per robot per chunk; below
            # that, treat it as a match. server_robots_seen tells whether
            # ANY response actually carried analysisResult (older
            # machines may not).
            "matches": (
                abs(total_win - upstream_total_win) < max(1.0, upstream_total_win * 1e-6)
                if upstream_robots_seen > 0
                else None
            ),
            "server_robots_seen": upstream_robots_seen,
        },
        "collect_mechanic": {
            # M272+ collect mechanic: total CollectCount triggers across
            # all robots, plus peak AccCredits seen. M14 (and any other
            # non-collect machine) reports applicable=false so the
            # frontend / interpretation can suppress the section
            # entirely. avg_spins_between_collects is null when no
            # triggers were observed (avoids div-by-zero).
            "applicable": collect_robots_seen_total > 0,
            "robots_with_data": collect_robots_seen_total,
            "total_collects": collect_count_total,
            "max_acc_credits_observed": acc_credits_max_global,
            "avg_spins_between_collects": (
                (total_spins / collect_count_total)
                if collect_count_total > 0
                else None
            ),
        },
        "guideline_assessment": {
            "guideline": "classic_slots_report_guideline_v1",
            "data_quality": {
                "quality_label": quality_label,
                "ci_met": ci_met,
                "sample_size_met": sample_size_met,
                "buckets_complete": buckets_complete,
                "bankruptcy_ladder_met": bankruptcy_ladder_met,
            },
            "derived_metrics": {
                "recovery_gap": recovery_gap,
                "tail_dependency": tail_dependency,
            },
            "classification": {
                "volatility_class": volatility_class,
                "experience_archetype": experience_archetype,
            },
            "concentration_checks": {
                "payline_top1_share": payline_top1_share,
                "payline_top3_share": payline_top3_share,
                "payline_top1_concentrated": payline_top1_concentrated,
                "payline_top3_concentrated": payline_top3_concentrated,
            },
            "symbol_checks": {
                "blank_like_rate": blank_like_rate,
                "blank_like_rate_by_column": blank_like_rate_by_col,
                "blank_like_col_spread": blank_like_col_spread,
                "symbol_distribution_skew": symbol_distribution_skew,
            },
            "bankruptcy_checks": {
                "x100_bankruptcy_rate": x100_br,
                "x200_bankruptcy_rate": x200_br,
                "x500_bankruptcy_rate": x500_br,
            },
            "alerts": alerts,
            "action_recommendations": action_recommendations,
            "conclusion_template": {
                "data_confidence": conclusion_data_confidence,
                "player_feel": conclusion_player_feel,
                "rtp_structure": conclusion_rtp_structure,
                "session_risk": conclusion_session_risk,
                "design_action": conclusion_design_action,
            },
        },
    }

    guideline_comparison = evaluate_guideline_comparison(summary, args.guideline_rules)
    summary["guideline_comparison"] = guideline_comparison

    out_json = args.output_dir / "player_impact_summary.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [
        f"# {args.machine} Mode={args.rtp_mode} Player Impact Report",
        "",
        "## Sampling",
        f"- total_spins: {total_spins}",
        f"- chunks: {chunks}",
        f"- target_halfwidth_pp: {args.target_halfwidth_pp}",
        f"- achieved_halfwidth_pp: {achieved_halfwidth_pp}",
        f"- stop_reason: {stop_reason}",
        f"- duration_seconds: {duration_seconds}",
        "",
        "## RTP",
        f"- point_pct: {rtp_point_pct:.6f}%",
        f"- ci95_interval_pct: {ci_interval}",
        "",
        "## Player Impact",
        f"- volatility.avg_return_x: {avg_return_x:.6f}",
        f"- volatility.std_return_x: {std_return_x:.6f}",
        f"- volatility.max_observed_return_x: {max_observed_return_x:.6f}",
        f"- win_hit_rate: {hit_rate:.6f}",
        f"- zero_win_rate: {zero_win_rate:.6f}",
        f"- profit_spin_rate: {profit_spin_rate:.6f}",
        f"- breakeven_or_more_rate: {breakeven_or_more_rate:.6f}",
        f"- big_win_x10_rate: {big_win_x10_rate:.6f}",
        f"- avg_win_when_hit_x: {avg_win_when_hit_x:.6f}",
        f"- loss_streak p50/p90/p95/max: {loss_streak_p50}/{loss_streak_p90}/{loss_streak_p95}/{max_loss_streak}",
        f"- win_streak p50/p90/p95/max: {win_streak_p50}/{win_streak_p90}/{win_streak_p95}/{max_win_streak}",
        "",
        "## Multiplier Buckets (ret_x = win/bet)",
        f"- tail_spin_rate_ge10x: {(tail_spins_ge10 / total_spins) if total_spins > 0 else 0.0:.6f}",
        f"- tail_rtp_contribution_pp_ge10x: {((tail_win_ge10 / total_bet) * 100.0) if total_bet > 0 else 0.0:.6f}",
        f"- tail_win_share_ge10x: {(tail_win_ge10 / total_win) if total_win > 0 else 0.0:.6f}",
    ]
    for row in multiplier_bucket_rows:
        md_lines.append(
            "- {bucket}: spin_rate={spin_rate:.6f}, avg_x={avg_return_x_in_bucket:.6f}, "
            "rtp_pp={rtp_contribution_pp:.6f}, win_share={win_share:.6f}".format(**row)
        )

    md_lines.extend(
        [
            "",
            "## Guideline Assessment",
            f"- quality_label: {quality_label}",
            f"- volatility_class: {volatility_class}",
            f"- experience_archetype: {experience_archetype}",
            f"- recovery_gap: {recovery_gap:.6f}",
            f"- tail_dependency: {tail_dependency:.6f}",
            f"- payline_top1_share: {payline_top1_share:.6f}",
            f"- payline_top3_share: {payline_top3_share:.6f}",
            f"- blank_like_rate: {blank_like_rate:.6f}",
            f"- blank_like_col_spread: {blank_like_col_spread:.6f}",
            f"- x100_bankruptcy_rate: {x100_br:.6f}",
            f"- x200_bankruptcy_rate: {x200_br:.6f}",
            f"- x500_bankruptcy_rate: {x500_br:.6f}",
        ]
    )

    md_lines.extend(
        [
            "",
            "## Guideline Rule Comparison (External Rules)",
            f"- guideline_id: {guideline_comparison.get('guideline_id', 'unknown')}",
            f"- overall_status: {guideline_comparison.get('overall_status', 'UNKNOWN')}",
            (
                "- checks: total={check_count} pass={pass_count} fail={fail_count} "
                "missing={missing_count} not_applicable={not_applicable_count}".format(
                    check_count=guideline_comparison.get("check_count", 0),
                    pass_count=guideline_comparison.get("pass_count", 0),
                    fail_count=guideline_comparison.get("fail_count", 0),
                    missing_count=guideline_comparison.get("missing_count", 0),
                    not_applicable_count=guideline_comparison.get("not_applicable_count", 0),
                )
            ),
        ]
    )
    for row in guideline_comparison.get("checks", []):
        status = row.get("status", "unknown")
        if status == "pass":
            continue
        md_lines.append(
            f"- [{status}] {row.get('id', 'UNKNOWN')} ({row.get('severity', 'medium')}): "
            f"{row.get('description', '')} observed={row.get('observed', 'N/A')} target={row.get('target', 'N/A')}"
        )

    if alerts:
        md_lines.append("- alerts:")
        for alert in alerts:
            md_lines.append(f"- [{alert['severity']}] {alert['code']}: {alert['message']}")
    else:
        md_lines.append("- alerts: none")

    for idx, action in enumerate(action_recommendations, 1):
        md_lines.append(f"- action_{idx}: {action}")

    md_lines.extend(
        [
            "",
            "## Conclusion Template (Filled)",
            f"1. Data confidence: {conclusion_data_confidence}",
            f"2. Player feel: {conclusion_player_feel}",
            f"3. RTP structure: {conclusion_rtp_structure}",
            f"4. Session risk: {conclusion_session_risk}",
            f"5. Design action: {conclusion_design_action}",
        ]
    )

    md_lines.extend(
        [
            "",
            "## Top Paylines (approx by split win)",
        ]
    )
    for row in payline_rows[:20]:
        md_lines.append(
            f"- line {row['payline_id']}: hit_rate={row['hit_rate']:.6f}, approx_rtp_pp={row['approx_rtp_contribution_pp']:.6f}"
        )

    md_lines.append("")
    md_lines.append("## Top Symbols")
    for row in symbol_rows[:20]:
        md_lines.append(f"- {row['symbol']}: rate={row['rate']:.6f}")

    md_lines.append("")
    md_lines.append("## Bankruptcy Probe")
    for row in bankruptcy_rows:
        if "error" in row:
            md_lines.append(f"- bankroll x{row['bankroll_multiplier']}: error={row['error']}")
        else:
            md_lines.append(
                f"- bankroll x{row['bankroll_multiplier']}: bankruptcy_rate={row['bankruptcy_rate']:.6f}, avg_spins_completed={row['avg_spins_completed']:.2f}"
            )

    md_lines.append("")
    md_lines.append("## Storage")
    md_lines.append("- raw_round_data_persisted: false")
    md_lines.append("- persisted: player_impact_summary.json + player_impact_report.md")
    md_lines.append("")
    md_lines.append(
        "Note: payline contribution is approximate because one spin may hit multiple paylines and win is split evenly across parsed line ids."
    )

    out_md = args.output_dir / "player_impact_report.md"
    out_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    append_jsonl(
        progress_file,
        {
            "event": "completed",
            "run_id": run_id,
            "stop_reason": stop_reason,
            "total_spins": total_spins,
            "chunks": chunks,
            "duration_seconds": duration_seconds,
            "rtp_point_pct": rtp_point_pct,
            "ci95_interval_pct": ci_interval,
            "output_dir": str(args.output_dir),
            "summary_file": str(out_json),
            "report_file": str(out_md),
            "quality_label": quality_label,
            "ts": utc_now(),
        },
    )

    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
