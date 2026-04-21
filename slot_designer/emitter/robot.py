"""Bundle rounds into a robot dict (roundResult JSON string + analysisResult).

analysisResult mirrors the upstream format:
- ``TotalWin`` (AnalysisType=0) / ``FeatureWin`` (=1) / ``SummaryWin`` (=2)
- Each is a JSON-string of {bucket_key: {WinCredits, SpinType, AnalysisType, Times}}
- Buckets: "-1" = zero-win; others = floor-of lower-bound multiplier
  (1, 5, 10, 20, 50, 100 ×bet). Matches real M1 rawdata exactly.

Analyzer's upstream cross-check sums TotalWin.WinCredits vs our summed
WinCredits across rounds — must match. emit_robot guarantees this because
both come from the same rounds list.
"""
from __future__ import annotations

import json
from collections import defaultdict

# Lower-bound edges for the upstream bucket histogram (M1 observed set).
_BUCKET_EDGES_DESC = [(100, "100"), (50, "50"), (20, "20"), (10, "10"), (5, "5"), (1, "1")]


def _win_bucket_key(win: int, bet: int) -> str:
    if win == 0:
        return "-1"
    mult = win / bet if bet else 0
    for edge, key in _BUCKET_EDGES_DESC:
        if mult >= edge:
            return key
    return "-1"  # unreachable for positive win with bet=1000 and edge=1


def _bucket_histogram(rounds: list[dict], bet: int) -> dict:
    h: dict[str, dict] = defaultdict(lambda: {"WinCredits": 0.0, "Times": 0})
    for r in rounds:
        k = _win_bucket_key(r["WinCredits"], bet)
        h[k]["WinCredits"] += float(r["WinCredits"])
        h[k]["Times"] += 1
    return h


def _with_analysis_type(hist: dict, analysis_type: int) -> dict:
    return {
        k: {
            "WinCredits": v["WinCredits"],
            "SpinType": "Normal",
            "AnalysisType": analysis_type,
            "Times": v["Times"],
        }
        for k, v in hist.items()
    }


def emit_robot(rounds: list[dict], *, bet: int) -> dict:
    hist = _bucket_histogram(rounds, bet)

    total_win = _with_analysis_type(hist, 0)
    feature_win = {"Normal": _with_analysis_type(hist, 1)}
    summary_win = {"Normal": _with_analysis_type(hist, 2)}

    return {
        "roundResult": json.dumps(rounds, ensure_ascii=False),
        "analysisResult": {
            "TotalWin": json.dumps(total_win, ensure_ascii=False),
            "FeatureWin": json.dumps(feature_win, ensure_ascii=False),
            "SummaryWin": json.dumps(summary_win, ensure_ascii=False),
        },
    }
