from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build report.json and report.md from run_summary.json")
    parser.add_argument("--input", required=True, help="Path to run_summary.json")
    parser.add_argument("--json", required=True, help="Output report.json")
    parser.add_argument("--md", required=True, help="Output report.md")
    return parser.parse_args()


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or isinstance(v, bool):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or isinstance(v, bool):
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def _fmt(v: Any, p: int = 4) -> str:
    if v is None:
        return "n/a"
    try:
        x = float(v)
        return f"{x:.{p}f}"
    except (TypeError, ValueError):
        return str(v)


def load_summary(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("run_summary.json must be a JSON object")
    return data


def build_report(summary: dict[str, Any]) -> dict[str, Any]:
    target = _as_float(summary.get("target_halfwidth_pp"), 0.0)
    achieved = summary.get("achieved_halfwidth_pp")
    achieved_f = _as_float(achieved, 0.0) if achieved is not None else None
    ci = summary.get("ci95_interval_pct")
    achieved_target = None
    if achieved_f is not None:
        achieved_target = achieved_f <= target

    return {
        "report_id": summary.get("report_id"),
        "machine": summary.get("machine", "M14"),
        "mode": summary.get("mode", 1),
        "target_halfwidth_pp": target,
        "achieved_halfwidth_pp": achieved_f,
        "total_spins": _as_int(summary.get("total_spins"), 0),
        "chunks": _as_int(summary.get("chunks"), 0),
        "rtp_point_pct": _as_float(summary.get("rtp_point_pct"), 0.0),
        "ci95_interval_pct": ci,
        "duration_seconds": _as_float(summary.get("duration_seconds"), 0.0),
        "stop_reason": summary.get("stop_reason"),
        "created_at": summary.get("finished_at") or summary.get("created_at"),
        "achieved_target": achieved_target,
    }


def render_md(report: dict[str, Any]) -> str:
    verdict = "TARGET_MET" if report.get("achieved_target") is True else "TARGET_NOT_MET"
    if report.get("achieved_target") is None:
        verdict = "TARGET_UNKNOWN"

    ci = report.get("ci95_interval_pct")
    if isinstance(ci, list) and len(ci) == 2:
        ci_text = f"[{_fmt(ci[0],4)}%, {_fmt(ci[1],4)}%]"
    else:
        ci_text = "n/a"

    lines = [
        "# M14 Mode=1 Adaptive Sampling Report",
        "",
        f"- Report ID: `{report.get('report_id')}`",
        f"- Machine: `{report.get('machine')}`",
        f"- Mode: `{report.get('mode')}`",
        f"- Target CI Half-width: `{_fmt(report.get('target_halfwidth_pp'),4)} pp`",
        f"- Achieved CI Half-width: `{_fmt(report.get('achieved_halfwidth_pp'),4)} pp`",
        f"- Total Spins: `{report.get('total_spins')}`",
        f"- Chunks: `{report.get('chunks')}`",
        f"- RTP Point Estimate: `{_fmt(report.get('rtp_point_pct'),4)}%`",
        f"- CI95 Interval: `{ci_text}`",
        f"- Duration: `{_fmt(report.get('duration_seconds'),2)} s`",
        f"- Stop Reason: `{report.get('stop_reason')}`",
        f"- Created At: `{report.get('created_at')}`",
        "",
        "## Conclusion",
        "",
        f"{verdict} (goal: CI half-width <= {_fmt(report.get('target_halfwidth_pp'),4)} pp).",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()
    json_out = Path(args.json).resolve()
    md_out = Path(args.md).resolve()

    summary = load_summary(input_path)
    report = build_report(summary)

    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)

    json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_out.write_text(render_md(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
