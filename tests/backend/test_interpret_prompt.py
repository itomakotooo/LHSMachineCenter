"""Locks the interpretation-prompt contract.

The prompt feeds gpt / gemini / claude via call_remote_interpreter, so
the structure (output sections + reference thresholds + included
subset keys) is part of the public contract for any future LLM swap.
"""
from __future__ import annotations

from src.web_console.backend.app import build_interpretation_prompt


def _summary_with_drilldown():
    return {
        "machine": "M14",
        "mode": 1,
        "sampling": {"total_spins": 360_000, "achieved_halfwidth_pp": 0.42},
        "rtp": {"point_pct": 90.4},
        "player_impact": {
            "volatility": {"classification": "High"},
            "multiplier_profile": {"buckets": [], "tail_dependency": 0.4},
            "hit_and_payout": {"zero_win_rate": 0.79, "profit_spin_rate": 0.12},
            "streaks": {"loss_streak_p95": 11},
            "bankruptcy_probe": [{"bankroll_multiplier": 100, "bankruptcy_rate": 0.18}],
            "paylines_top20": [
                {
                    "payline_id": "1",
                    "hit_count": 11_000,
                    "approx_rtp_contribution_pp": 10.6,
                    "top_symbols": [{"symbol": "cherry", "count": 7000}],
                }
            ],
            "payout_groups_top20": [
                {"group_id": 0, "hit_count": 285_000, "rtp_contribution_pp": 0.0},
                {"group_id": 12, "hit_count": 11_000, "rtp_contribution_pp": 9.5},
            ],
            "symbols_top20": [{"symbol": "cherry", "count": 557_000, "rate": 0.17}],
            "symbols_by_column_top10": {"0": [{"symbol": "blank", "count": 320_000}]},
        },
        "guideline_assessment": {"data_quality": {"quality_label": "EXPLORATORY"}},
        "guideline_comparison": {},
    }


def test_prompt_contains_all_six_output_sections():
    prompt = build_interpretation_prompt(_summary_with_drilldown())
    # Output structure: 6 sections, drilldown narrative is now mandatory.
    assert "1) 数据可信度" in prompt
    assert "2) 玩家体感" in prompt
    assert "3) RTP结构与倍率分桶" in prompt
    assert "4) 支付线与符号热点" in prompt
    assert "5) 关键风险与告警" in prompt
    assert "6) 优先调参建议" in prompt


def test_prompt_includes_reference_thresholds():
    prompt = build_interpretation_prompt(_summary_with_drilldown())
    # Specific numeric anchors so the LLM can ground "high / very high".
    assert "Very High: zero_win_rate>0.82" in prompt
    assert "loss_streak_p95>18" in prompt
    assert ">=15 触发告警" in prompt
    assert "x500>0.05" in prompt
    assert ">=0.45 表示头重" in prompt


def test_prompt_subset_carries_drilldowns():
    prompt = build_interpretation_prompt(_summary_with_drilldown())
    # Drilldown content is in the JSON payload section.
    assert '"paylines_top20"' in prompt
    assert '"payout_groups_top20"' in prompt
    assert '"symbols_top20"' in prompt
    assert '"symbols_by_column_top10"' in prompt
    assert "cherry" in prompt
    # Aggregate top-line still present (regression guard).
    assert '"player_impact"' in prompt
    assert '"guideline_assessment"' in prompt


def test_prompt_handles_missing_drilldown_gracefully():
    """Old reports (pre-payout-groups feature) must still produce a
    well-formed prompt with the drilldown keys present but null."""
    summary = _summary_with_drilldown()
    summary["player_impact"].pop("payout_groups_top20")
    prompt = build_interpretation_prompt(summary)
    # Key still rendered (as null) so the model knows it's intentionally
    # absent and can call out the legacy-report case.
    assert '"payout_groups_top20": null' in prompt
