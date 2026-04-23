"""Bundle rounds into a robot dict (roundResult JSON string + analysisResult).

analysisResult mirrors the upstream format (verified against production
M15$TopDollarSelector$0$ and M14 rawdata):

Outer analysisResult is a JSON STRING. When parsed it yields a dict with
three JSON-string values:
- ``TotalWin`` (AnalysisType=0): flat bucket histogram across ALL rounds
  (base wins + ACCEPTED feature wins). Rejected feature sub-rounds
  (intermediate ST=14 offers) count as Win=0. This makes
  ``server_total_win = sum TotalWin.WinCredits`` the authoritative RTP
  numerator; analyzer uses it via ``server_total_win_override`` to
  avoid the sum-all double-counting.
- ``FeatureWin`` (AnalysisType=1): per-feature_name breakdown.
  {feature_name: {bucket_key: entry}}. Feature names for M15:
    * "Normal": ST=1 paid spins (wins, plus trigger's regular pay if any)
    * "TopDollar": accepted feature offer wins (last ST=14 per session)
    * "TopDollarSelector": trigger markers (ST=15 rows, always Win=0)
- ``SummaryWin`` (AnalysisType=2): same shape as FeatureWin, same data.

Buckets keyed by lower-bound multiplier (1, 5, 10, 20, 50, 100 × bet);
"-1" = zero-win.

For machines without features (M1), all rounds categorize as "Normal"
and FeatureWin/SummaryWin have a single "Normal" entry — matches
pre-v5 behavior exactly.
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


def _classify_rounds(rounds: list[dict]) -> list[tuple[str, int]]:
    """Per-round classification: (feature_name, effective_win) tuples.

    Mapping (verified against M15$TopDollarSelector$0$ production):
      ST=1 (any ReMarks)     → "Normal"       effective_win = WinCredits
      ST=14 rejected         → "TopDollarSelector"  effective_win = 0
      ST=14 accepted (last)  → "TopDollar"    effective_win = WinCredits
      ST=15 end marker       → "TopDollarSelector"  effective_win = 0 (Win=0 anyway)

    ST=14 is "accepted" iff the next row is NOT ST=14 (end of run). All
    other ST=14 in a consecutive run are rejected reveals.

    Non-M15 machines emit only ST=1 → everything is "Normal" (M1 compat).

    Production Times check (208,840 total spins):
      Normal                200,000 (= ST=1 count)
      TopDollar               2,238 (= accepted ST=14 = triggers)
      TopDollarSelector       6,602 (= rejected ST=14 + ST=15
                                     = 4,364 + 2,238)
    Sum = 208,840 — matches total spins.
    """
    out: list[tuple[str, int]] = []
    n = len(rounds)
    for i in range(n):
        r = rounds[i]
        st = r.get("SpinType", 1)
        win = int(r.get("WinCredits", 0) or 0)
        if st == 14:
            # Accepted iff next row isn't ST=14 (end of run).
            next_st = rounds[i + 1].get("SpinType") if i + 1 < n else None
            if next_st == 14:
                out.append(("TopDollarSelector", 0))  # rejected reveal
            else:
                out.append(("TopDollar", win))          # accepted final
        elif st == 15:
            out.append(("TopDollarSelector", 0))        # end marker
        else:
            out.append(("Normal", win))                 # ST=1 paid spin
    return out


def emit_robot(rounds: list[dict], *, bet: int) -> dict:
    classification = _classify_rounds(rounds)

    # 1. TotalWin: flat bucket hist over all rounds using effective_win
    #    from classification (rejected ST=14 → 0, ST=15 → 0). SpinType
    #    label stays "Normal" per production convention.
    total_hist: dict[str, dict] = defaultdict(lambda: {"WinCredits": 0.0, "Times": 0})
    for (_feat, eff_win) in classification:
        k = _win_bucket_key(eff_win, bet)
        total_hist[k]["WinCredits"] += float(eff_win)
        total_hist[k]["Times"] += 1
    total_win = {
        k: {
            "WinCredits": v["WinCredits"],
            "SpinType": "Normal",
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
    # also JSON-encoded strings. Analyzer at line 2006 of
    # player_impact_analyzer.py rejects non-string analysisResult and
    # falls back to raw round-walk sum → inflated RTP on feature-bearing
    # machines. Double-encoded to match production exactly.
    analysis_result_dict = {
        "TotalWin": json.dumps(total_win, ensure_ascii=False),
        "FeatureWin": json.dumps(feature_win, ensure_ascii=False),
        "SummaryWin": json.dumps(summary_win, ensure_ascii=False),
    }
    return {
        "roundResult": json.dumps(rounds, ensure_ascii=False),
        "analysisResult": json.dumps(analysis_result_dict, ensure_ascii=False),
    }
