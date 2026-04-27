"""Generate machine_round_win_rules.json entries for all RED+YELLOW
machines from the gap-scan TSV.

Strategy: ONE universal SynthesizePayIdRule entry with
``label_format: "spin_type"`` covering the union of all culprit
SpinTypes across affected machines. Applies-to lists every
non-TopDollar affected machine. SpinType filter on the rule means
machines whose rounds have non-empty PayoutIdToWinAmount on those
SpinTypes won't be touched (rule self-gates).

TopDollar selector machines (M12/M15/M90/M132) are already handled
by the existing settlement_winamount rule + multi-settlement
sum_win fix in trigger_sessions; they're excluded from the
synthesize entry.

Output: prints JSON snippet to stdout for hand-merge into
configs/machine_round_win_rules.json.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCAN_TSV = REPO / "scripts" / "_payid_gap_scan.tsv"


def main():
    if not SCAN_TSV.exists():
        print(f"need {SCAN_TSV} -- run scan_payid_attribution_gap.py first",
              file=sys.stderr)
        sys.exit(1)

    affected_machines: set[str] = set()
    culprit_sts: set[int] = set()
    with open(SCAN_TSV, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or line.startswith("class\t"):
                continue
            parts = line.rstrip("\n").split("\t")
            if not parts or len(parts) < 9:
                continue
            cls = parts[0]
            machine = parts[1]
            culprits_str = parts[8] if len(parts) > 8 else ""
            if cls not in ("RED_LARGE", "YELLOW_SMALL"):
                continue
            # TopDollar selectors are handled by settlement_winamount rule.
            if "$TopDollarSelector$" in machine:
                continue
            affected_machines.add(machine)
            for st_str in re.findall(r"ST(\d+):", culprits_str):
                culprit_sts.add(int(st_str))

    sts_sorted = sorted(culprit_sts)
    machines_sorted = sorted(affected_machines)

    print(f"# {len(machines_sorted)} affected machines, "
          f"{len(sts_sorted)} unique culprit SpinTypes", file=sys.stderr)

    snippet = {
        "synthesize_pay_id_for_empty_pid": {
            "_doc": (
                "Catch-all for machines where bonus rounds (ST in spin_types) "
                "emit WinCredits > 0 but empty/None PayoutIdToWinAmount, so the "
                "round-level pid aggregator can't attribute the win and the "
                "drilldown shows a gap between sum(payid_rtp) and headline RTP. "
                "Each affected round synthesizes a single pay_id label "
                "'st<SpinType>' so the drilldown surfaces 'how much each "
                "feature/SpinType contributed' even when upstream omits per-pid "
                "info. Self-gating: rule no-ops on rounds whose PayoutIdToWinAmount "
                "is non-empty (so machines listed here that DO have proper pid "
                "on most rounds are unaffected on those rounds). "
                "Identified via scripts/scan_payid_attribution_gap.py 2026-04-27."
            ),
            "type": "synthesize_pay_id",
            "params": {
                "spin_types": sts_sorted,
                "label_format": "spin_type"
            },
            "applies_to": machines_sorted
        }
    }

    print(json.dumps(snippet, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
