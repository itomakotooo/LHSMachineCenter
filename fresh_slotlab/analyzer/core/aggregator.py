"""Aggregation and classification primitives carved from ``player_impact_analyzer.py``.

P2-B2 (Phase 2 / Wave 2b): moves 16 aggregation symbols from PIA into this
canonical module.  PIA re-exports all 16 via its dual-path import block so
existing callers keep working unchanged.

Ownership:
  - 13 aggregator-only symbols defined here:
      _BankruptcyStreamAccumulator, compute_bankruptcy_percentiles,
      fastest_bankruptcy_spins_from_list, median_spins_from_list,
      build_multiplier_bucket_rows, quantile_from_hist,
      classify_volatility, classify_experience_archetype,
      _metric_path_get, _eval_operator, _deviation,
      evaluate_guideline_comparison.
  - 6 shared helpers imported from ``core/_utils.py`` and re-exported:
      return_bucket, _empty_bankruptcy_tier, _extract_bankruptcy_reps,
      simulate_bankruptcy_from_response, _DEFAULT_BANKROLL_MULTIPLIERS,
      _DEFAULT_BANKRUPTCY_SESSION_SPINS.

Per memory feedback_subprocess_import_suicide_and_module_globals.md:
  - No I/O at import time.
  - No module-top side effects.
  - Only stdlib + ``core/_utils.py`` + ``fresh_slotlab.round_win`` imports.

C5 cycle-freedom (ticket §3):
  - MUST NOT import from ``fresh_slotlab.player_impact_analyzer``.
  - May import from ``core/_utils.py`` and ``core/parser.py`` (parser is
    upstream of aggregator in the pipeline); only ``_utils.py`` is needed.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Dual-path import of _utils symbols (P2-B2).
# Package-mode path in the try arm; standalone-script fallback in except.
try:
    from fresh_slotlab.analyzer.core._utils import (
        return_bucket,
        _empty_bankruptcy_tier,
        _extract_bankruptcy_reps,
        simulate_bankruptcy_from_response,
        _DEFAULT_BANKROLL_MULTIPLIERS,
        _DEFAULT_BANKRUPTCY_SESSION_SPINS,
    )
except ImportError:  # running as a standalone script (fresh_slotlab/ on sys.path)
    from analyzer.core._utils import (  # type: ignore[no-redef]
        return_bucket,
        _empty_bankruptcy_tier,
        _extract_bankruptcy_reps,
        simulate_bankruptcy_from_response,
        _DEFAULT_BANKROLL_MULTIPLIERS,
        _DEFAULT_BANKRUPTCY_SESSION_SPINS,
    )

# Re-export the 6 _utils symbols so callers can do:
#   from fresh_slotlab.analyzer.core.aggregator import return_bucket
# and get the single canonical definition.
__all__ = [
    # _utils re-exports
    "return_bucket",
    "_empty_bankruptcy_tier",
    "_extract_bankruptcy_reps",
    "simulate_bankruptcy_from_response",
    "_DEFAULT_BANKROLL_MULTIPLIERS",
    "_DEFAULT_BANKRUPTCY_SESSION_SPINS",
    # aggregator-only symbols
    "RETURN_BUCKET_ORDER",
    "_BankruptcyStreamAccumulator",
    "compute_bankruptcy_percentiles",
    "fastest_bankruptcy_spins_from_list",
    "median_spins_from_list",
    "build_multiplier_bucket_rows",
    "quantile_from_hist",
    "classify_volatility",
    "classify_experience_archetype",
    "_metric_path_get",
    "_eval_operator",
    "_deviation",
    "evaluate_guideline_comparison",
]

# Decile steps (P10, P20, ..., P90). Survivor-heavy tiers pin the
# higher percentiles to session_spins (once cum >= p*total exits the
# bankrupt region), so the table naturally surfaces "when does
# bankruptcy run out" -- the transition percentile matches the
# complement of the bankruptcy rate.
_BANKRUPTCY_PERCENTILES: tuple[int, ...] = (10, 20, 30, 40, 50, 60, 70, 80, 90)


# ---------------------------------------------------------------------------
# Bankruptcy stream accumulator
# ---------------------------------------------------------------------------

class _BankruptcyStreamAccumulator:
    """Streams (cost_bet, cost_win) tuples through per-tier bankruptcy
    simulation, pooling rounds across CHUNKS (not just within a chunk).

    Why this exists: the per-chunk simulator (``simulate_bankruptcy_
    from_response``) drops chunks where total_paid_spins < session_spins
    because they can't form even one complete window. With virtual
    sampling defaults (chunk_spin_times=1000 × chunk_robot_count=8 =
    8000 paid spins vs session_spins=10000), every chunk falls below
    the threshold and the bankruptcy panel renders empty. Pooling
    across chunks is statistically valid (RNG stateless per spin per
    the upstream contract) and gives proper coverage.

    Memory: O(num_tiers × spins_done_count). The spins_done list
    grows only with bankrupt windows; survival doesn't allocate.
    For the default 4-tier ladder × 561 windows × 4 bytes = ~9KB peak
    on a 5M-spin run.
    """
    def __init__(
        self,
        bet: int,
        session_spins: int,
        bankroll_mults: tuple[int, ...],
    ) -> None:
        self.bet = int(bet)
        self.session_spins = int(session_spins)
        self.applicable = bet > 0 and session_spins > 0
        self.tiers: dict[int, dict[str, Any]] = {}
        for m in bankroll_mults:
            init = int(m) * int(bet)
            self.tiers[int(m)] = {
                "init_bankroll": init,
                "balance": init,
                "spins_done": 0,
                "bankrupt": 0,
                "survived": 0,
                "spins_done_list": [],
            }
        self.fed_count = 0  # for "did we receive any reps?" detection at finalize

    def feed_reps(self, reps: list[tuple[int, int]]) -> None:
        """Feed a list of (cost_bet, cost_win) tuples through every tier's
        running window state. Called once per chunk during merge."""
        if not self.applicable or not reps:
            return
        for cost_bet, cost_win in reps:
            self.fed_count += 1
            for state in self.tiers.values():
                # Bankrupt branch: cost > balance and we're being asked
                # to consume a paid round we can't afford.
                if cost_bet > 0 and state["balance"] < cost_bet:
                    state["bankrupt"] += 1
                    state["spins_done_list"].append(int(state["spins_done"]))
                    # Reset for next window. Apply this round to the
                    # fresh window — same semantics as the per-chunk
                    # simulator (which "starts" each window at index w*
                    # session_spins and consumes round-by-round).
                    state["balance"] = state["init_bankroll"]
                    state["spins_done"] = 0
                    if cost_bet > 0 and state["balance"] < cost_bet:
                        # Pathological: bet > full bankroll. Mark instant
                        # bankruptcy at spin 0 and stay reset.
                        state["bankrupt"] += 1
                        state["spins_done_list"].append(0)
                        continue
                    state["balance"] -= cost_bet
                    state["balance"] += cost_win
                    state["spins_done"] = 1
                else:
                    state["balance"] -= cost_bet
                    state["balance"] += cost_win
                    state["spins_done"] += 1
                # Window complete?
                if state["spins_done"] >= self.session_spins:
                    state["survived"] += 1
                    state["balance"] = state["init_bankroll"]
                    state["spins_done"] = 0

    def finalize(self) -> dict[int, dict[str, Any]]:
        """Return per-tier {bankrupt, survived, spins_done} dict shaped
        identically to the per-chunk simulator's output, so finalize
        code can drop in the streaming result without further changes.
        Partial / in-progress windows are NOT counted (matches per-chunk
        simulator's drop-the-tail behavior — partial windows can't
        survive, so counting them would bias toward bankrupt)."""
        return {
            int(m): {
                "bankrupt": int(s["bankrupt"]),
                "survived": int(s["survived"]),
                "spins_done": list(s["spins_done_list"]),
            }
            for m, s in self.tiers.items()
        }

    @property
    def has_data(self) -> bool:
        return self.fed_count > 0


# ---------------------------------------------------------------------------
# Bankruptcy percentile / median helpers
# ---------------------------------------------------------------------------

def compute_bankruptcy_percentiles(
    spins_done_sorted: list[int],
    survived: int,
    session_spins: int,
    percentiles: tuple[int, ...] = _BANKRUPTCY_PERCENTILES,
) -> dict[int, int]:
    """Return the exact spin count at each requested percentile of the
    tier's full session population (bankrupt + survived). Percentiles
    are evaluated over ALL sessions — a tier with 80% bankrupt and
    20% survived will hit session_spins from P81 upward.

    ``spins_done_sorted`` MUST be pre-sorted ascending. Bankrupt
    sessions contribute their exact spins_done value; survivors are
    treated as session_spins each. Sub-bin quantization (the previous
    100-bin histogram bug where mass in the first few fine bins
    collapsed P10/P20/P30 to the same midpoint) is gone: the resolution
    is a single spin.
    """
    bankrupt = len(spins_done_sorted)
    total = bankrupt + int(survived or 0)
    if total == 0 or session_spins <= 0:
        return {int(p): 0 for p in percentiles}
    out: dict[int, int] = {}
    for p in percentiles:
        # Rank index (0-based) for percentile p. ``total - 1`` anchors
        # P100 to the last element; ``p/100 * (total-1)`` gives the
        # target rank in the combined bankrupt + survived array.
        target_rank = (p / 100.0) * (total - 1)
        idx = int(round(target_rank))
        if idx < 0:
            idx = 0
        if idx >= total:
            idx = total - 1
        # Indices 0..bankrupt-1 live in the sorted bankrupt list;
        # indices >= bankrupt are survivors at session_spins.
        if idx < bankrupt:
            out[int(p)] = int(spins_done_sorted[idx])
        else:
            out[int(p)] = int(session_spins)
    return out


def fastest_bankruptcy_spins_from_list(
    spins_done_sorted: list[int],
) -> int | None:
    """Return the exact spin count of the earliest bankruptcy in this
    tier. Returns None when no bankruptcies were observed (the tier
    never lost a single session).
    """
    if not spins_done_sorted:
        return None
    return int(spins_done_sorted[0])


def median_spins_from_list(
    spins_done_sorted: list[int],
    survived: int,
    session_spins: int,
) -> int:
    """Convenience alias for P50 via compute_bankruptcy_percentiles."""
    pct = compute_bankruptcy_percentiles(
        spins_done_sorted, survived, session_spins, percentiles=(50,)
    )
    return int(pct.get(50, 0))


# ---------------------------------------------------------------------------
# Multiplier bucket rows
# ---------------------------------------------------------------------------

# RETURN_BUCKET_ORDER is the canonical ordered bucket label list for the
# multiplier bucket chart.  Defined here (aggregator.py) as the natural
# home for aggregation constants; PIA re-exports it from its own scope.
# (No import of PIA needed — PIA will import from here via the P2-B2
# re-export block.)
RETURN_BUCKET_ORDER = [
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


# ---------------------------------------------------------------------------
# Classifiers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Guideline comparison helpers
# ---------------------------------------------------------------------------

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


def _utc_now_str() -> str:
    """UTC timestamp string — stdlib inline of PIA's utc_now().
    Avoids importing from player_impact_analyzer (C5 cycle-freedom)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        "evaluated_at": _utc_now_str(),
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
