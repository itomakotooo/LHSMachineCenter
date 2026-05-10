"""Bundle rounds into a robot dict (roundResult JSON string + analysisResult).

analysisResult mirrors the upstream rawdata format:

Outer analysisResult is a JSON STRING. When parsed it yields a dict with
three JSON-string values:
- ``TotalWin`` (AnalysisType=0): flat bucket histogram across ALL rounds.
  ``server_total_win = sum TotalWin.WinCredits`` is the authoritative
  RTP numerator; analyzer uses it via ``server_total_win_override`` to
  avoid sum-all double-counting.
- ``FeatureWin`` (AnalysisType=1): per-feature_name breakdown.
  ``{feature_name: {bucket_key: entry}}``. Names come from the plugin's
  ``classify_round`` (e.g. "Normal" + machine-specific feature buckets);
  base-only machines get a single "Normal" bucket.
- ``SummaryWin`` (AnalysisType=2): same shape as FeatureWin, same data.

Buckets keyed by lower-bound multiplier (1, 5, 10, 20, 50, 100 × bet);
"-1" = zero-win.

Plugin extension (ARCHITECTURE.md §3): when a plugin is provided,
``_classify_rounds`` calls ``plugin.classify_round(round_dict,
next_round_dict)`` per row to compute (feature_name, effective_win).
Generic emitter never inspects SpinType numbers or feature-name strings.
"""
from __future__ import annotations

import json
from collections import defaultdict

from ..engine.feature_protocol import FeaturePlugin

# Lower-bound edges for the upstream bucket histogram.
_BUCKET_EDGES_DESC = [(100, "100"), (50, "50"), (20, "20"), (10, "10"), (5, "5"), (1, "1")]

# Default classification for base-only machines (no plugin): everything
# goes into "Normal" with effective_win = WinCredits.
_DEFAULT_FEATURE_NAME = "Normal"


def _win_bucket_key(win: int, bet: int) -> str:
    if win == 0:
        return "-1"
    mult = win / bet if bet else 0
    for edge, key in _BUCKET_EDGES_DESC:
        if mult >= edge:
            return key
    return "-1"  # unreachable for positive win with bet=1000 and edge=1


def _classify_rounds(
    rounds: list[dict],
    plugin: FeaturePlugin | None,
) -> list[tuple[str, int]]:
    """Per-round classification: (feature_name, effective_win) tuples.

    Without plugin (base-only machine): every round → ("Normal",
    WinCredits).

    With plugin: delegate to ``plugin.classify_round(round_dict,
    next_round_dict)``. The plugin owns the SpinType / feature_name
    knowledge for its machine.
    """
    out: list[tuple[str, int]] = []
    n = len(rounds)
    for i, r in enumerate(rounds):
        if plugin is None:
            win = int(r.get("WinCredits", 0) or 0)
            out.append((_DEFAULT_FEATURE_NAME, win))
            continue
        next_r = rounds[i + 1] if i + 1 < n else None
        out.append(plugin.classify_round(r, next_r))
    return out


def emit_robot(
    rounds: list[dict],
    *,
    bet: int,
    plugin: FeaturePlugin | None = None,
) -> dict:
    classification = _classify_rounds(rounds, plugin)

    # 1. TotalWin: flat bucket hist over all rounds using effective_win
    #    from classification. SpinType label stays "Normal" per
    #    production convention.
    total_hist: dict[str, dict] = defaultdict(lambda: {"WinCredits": 0.0, "Times": 0})
    for (_feat, eff_win) in classification:
        k = _win_bucket_key(eff_win, bet)
        total_hist[k]["WinCredits"] += float(eff_win)
        total_hist[k]["Times"] += 1
    total_win = {
        k: {
            "WinCredits": v["WinCredits"],
            "SpinType": _DEFAULT_FEATURE_NAME,
            "AnalysisType": 0,
            "Times": v["Times"],
        }
        for k, v in total_hist.items()
    }

    # 2. FeatureWin / SummaryWin: per-feature_name bucket hist.
    per_feature_hist: dict[str, dict[str, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"WinCredits": 0.0, "Times": 0})
    )
    for (feat, eff_win) in classification:
        k = _win_bucket_key(eff_win, bet)
        per_feature_hist[feat][k]["WinCredits"] += float(eff_win)
        per_feature_hist[feat][k]["Times"] += 1

    def _feat_entries(analysis_type: int) -> dict:
        return {
            feat_name: {
                k: {
                    "WinCredits": v["WinCredits"],
                    "SpinType": feat_name,
                    "AnalysisType": analysis_type,
                    "Times": v["Times"],
                }
                for k, v in hist.items()
            }
            for feat_name, hist in per_feature_hist.items()
        }

    feature_win = _feat_entries(1)
    summary_win = _feat_entries(2)

    # Production rawdata emits analysisResult as a JSON-encoded STRING
    # (outer) with each inner section (TotalWin/FeatureWin/SummaryWin)
    # also JSON-encoded strings. The analyzer rejects non-string
    # analysisResult and falls back to raw round-walk sum → inflated
    # RTP on feature-bearing machines. Double-encoded to match
    # production exactly.
    analysis_result_dict = {
        "TotalWin": json.dumps(total_win, ensure_ascii=False),
        "FeatureWin": json.dumps(feature_win, ensure_ascii=False),
        "SummaryWin": json.dumps(summary_win, ensure_ascii=False),
    }
    return {
        "roundResult": json.dumps(rounds, ensure_ascii=False),
        "analysisResult": json.dumps(analysis_result_dict, ensure_ascii=False),
    }
