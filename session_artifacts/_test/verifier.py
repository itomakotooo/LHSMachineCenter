"""Per-report verifier — RTP calculation correctness, not RTP value plausibility.

Reads completed rows from work_plan_copy.csv + work_plan_sample.csv and
walks each row's summary.json. Per the user's 2026-05-20 direction:

  保证的是 rtp 计算过程正确，不是 rtp 结果在什么区间

So we check schema, field presence/types, and the 4 integrity-gate
layers + the cross-aggregator parity invariant from memory
`feedback_aggregator_parity_invariant.md`. We DO NOT judge whether
the RTP value is in any range.

Output: ``02_verification.csv`` next to this script.

Runs are idempotent + incremental: re-running picks up any new
completed rows since the last run and rewrites the CSV fresh each
time (cheap — 255 rows max).

Usage::

    python verifier.py
    python verifier.py --inject-bug   # self-bug-check (synthetic L1 flip)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
WORK_PLAN_PATHS = [HERE / "work_plan_copy.csv", HERE / "work_plan_sample.csv"]
VERIFICATION_CSV = HERE / "02_verification.csv"

# Tolerance for the sum_pid_rtp_pp == summary.rtp.point_pct parity check.
PARITY_TOLERANCE_PP = 0.001

# Fallback prefix list per architecture proposal v5 §9.2 Layer 2.
FALLBACK_PREFIXES = ("_unattributed_", "_other", "_default", "_misc")

CSV_FIELDS = [
    "machine", "mode", "schema_ok", "fields_present", "eff_ver_format_ok",
    "gate_struct_ok", "rtp_is_number", "total_spins",
    "l1", "l2", "l3", "l4_applicable", "l4_ok", "parity_check",
    "rtp_value", "issues_summary",
]


def _result(label: str) -> str:
    """Constrain result strings to a known set so the synthesizer can
    count without surprises."""
    assert label in ("pass", "fail", "skip", "na"), label
    return label


def _verify_one(summary_path: Path, machine: str, mode: int) -> dict[str, Any]:
    """Return one CSV row dict per the schema above."""
    issues: list[str] = []
    row: dict[str, Any] = {
        "machine": machine,
        "mode": mode,
        "schema_ok": "na",
        "fields_present": "na",
        "eff_ver_format_ok": "na",
        "gate_struct_ok": "na",
        "rtp_is_number": "na",
        "total_spins": "",
        "l1": "skip",
        "l2": "skip",
        "l3": "skip",
        "l4_applicable": "na",
        "l4_ok": "skip",
        "parity_check": "na",
        "rtp_value": "",
        "issues_summary": "",
    }

    # A — schema
    if not summary_path or not summary_path.exists():
        row["schema_ok"] = "fail"
        issues.append(f"summary file missing: {summary_path}")
        row["issues_summary"] = "; ".join(issues)
        return row

    try:
        s = json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        row["schema_ok"] = "fail"
        issues.append(f"JSON load failed: {type(exc).__name__}")
        row["issues_summary"] = "; ".join(issues)
        return row
    if not isinstance(s, dict):
        row["schema_ok"] = "fail"
        issues.append(f"summary top-level is {type(s).__name__}, not dict")
        row["issues_summary"] = "; ".join(issues)
        return row
    row["schema_ok"] = "pass"

    # Field presence check
    required = ["machine", "mode", "rtp", "sampling", "player_impact",
                "analyzer_version", "effective_analyzer_version",
                "rtp_integrity_check"]
    missing = [k for k in required if k not in s]
    if missing:
        row["fields_present"] = "fail"
        issues.append(f"missing fields: {missing}")
    else:
        row["fields_present"] = "pass"

    # rtp.point_pct is a number
    rtp_obj = s.get("rtp") or {}
    rtp_value = rtp_obj.get("point_pct") if isinstance(rtp_obj, dict) else None
    if isinstance(rtp_value, (int, float)):
        row["rtp_is_number"] = "pass"
        row["rtp_value"] = f"{rtp_value:.4f}"
    else:
        row["rtp_is_number"] = "fail"
        issues.append(f"rtp.point_pct is {type(rtp_value).__name__}, not number")

    # total_spins > 0
    sampling = s.get("sampling") or {}
    total_spins = sampling.get("total_spins") if isinstance(sampling, dict) else None
    if isinstance(total_spins, int) and total_spins > 0:
        row["total_spins"] = total_spins
    else:
        issues.append(f"total_spins={total_spins!r} not positive int")

    # B — new field shape
    eff_ver = s.get("effective_analyzer_version") or ""
    if (isinstance(eff_ver, str) and len(eff_ver) == 12
            and all(c in "0123456789abcdef" for c in eff_ver)):
        row["eff_ver_format_ok"] = "pass"
    else:
        row["eff_ver_format_ok"] = "fail"
        eav_err = s.get("effective_analyzer_version_error")
        if eav_err:
            issues.append(f"effective_analyzer_version err: {eav_err[:120]}")
        else:
            issues.append(f"effective_analyzer_version invalid: {eff_ver!r}")

    chk = s.get("rtp_integrity_check") or {}
    if isinstance(chk, dict):
        # Check expected keys present
        required_chk_keys = ("layer1_invariant_ok",
                             "layer2_no_fallback_buckets_ok",
                             "layer3_anchors_ok", "layer4_applicable",
                             "layer4_per_st_consistency_ok", "passed",
                             "completeness_declared")
        missing_chk = [k for k in required_chk_keys if k not in chk]
        if missing_chk:
            row["gate_struct_ok"] = "fail"
            issues.append(f"gate missing keys: {missing_chk}")
        else:
            row["gate_struct_ok"] = "pass"
    else:
        row["gate_struct_ok"] = "fail"
        issues.append(f"rtp_integrity_check is {type(chk).__name__}, not dict")
        chk = {}

    # C — RTP calculation correctness signals
    # L1 — sum(payout_id_win) == chunk_win invariant
    l1 = chk.get("layer1_invariant_ok")
    if l1 is True:
        row["l1"] = "pass"
    elif l1 is False:
        row["l1"] = "fail"
        l1_err = chk.get("layer1_error") or "?"
        issues.append(f"L1 fail: {l1_err[:80]}")

    # L2 — no fallback-prefix pay_id row
    l2 = chk.get("layer2_no_fallback_buckets_ok")
    if l2 is True:
        row["l2"] = "pass"
    elif l2 is False:
        row["l2"] = "fail"
        fallbacks = chk.get("layer2_fallback_buckets_found") or []
        issues.append(f"L2 fail: {fallbacks[:3]}")

    # L3 — anchor coverage
    l3 = chk.get("layer3_anchors_ok")
    if l3 is True:
        row["l3"] = "pass"
    elif l3 is False:
        row["l3"] = "fail"
        missing_anch = chk.get("layer3_missing_anchors") or []
        issues.append(f"L3 fail: missing {missing_anch[:3]}")

    # L4 — applicability gate + per-ST consistency
    l4_applicable = chk.get("layer4_applicable")
    if l4_applicable is True:
        row["l4_applicable"] = "yes"
        l4_ok = chk.get("layer4_per_st_consistency_ok")
        if l4_ok is True:
            row["l4_ok"] = "pass"
        elif l4_ok is False:
            row["l4_ok"] = "fail"
            inc = chk.get("layer4_inconsistencies") or []
            issues.append(f"L4 fail: {len(inc)} per-ST mismatches")
    elif l4_applicable is False:
        row["l4_applicable"] = "no"
        # Per architecture proposal section 9.4 Skip approach: trigger-session
        # machines structurally skip Layer 4. Not a failure.
        row["l4_ok"] = "skip"

    # Cross-aggregator parity check (memory feedback_aggregator_parity_invariant.md)
    # sum(per_pay_id.rtp_pp) ?= summary.rtp.point_pct
    pi = s.get("player_impact") or {}
    pay_overview = (pi.get("pay_id_overview") if isinstance(pi, dict) else None) or {}
    pid_rows = pay_overview.get("rows") if isinstance(pay_overview, dict) else None
    if pid_rows is None:
        # try alternate locations
        pid_rows = pi.get("payouts_top20") if isinstance(pi, dict) else None
    if isinstance(pid_rows, list) and pid_rows and isinstance(rtp_value, (int, float)):
        # Sum any per-row rtp_pp; field may be named rtp_contribution_pp or rtp_pp
        rtp_pp_sum = 0.0
        n_pids = 0
        for r in pid_rows:
            if not isinstance(r, dict):
                continue
            v = r.get("rtp_pp")
            if v is None:
                v = r.get("rtp_contribution_pp")
            if v is None:
                v = r.get("approx_rtp_contribution_pp")
            if isinstance(v, (int, float)):
                rtp_pp_sum += float(v)
                n_pids += 1
        if n_pids:
            diff = abs(rtp_pp_sum - float(rtp_value))
            if diff < PARITY_TOLERANCE_PP:
                row["parity_check"] = "pass"
            else:
                row["parity_check"] = "fail"
                issues.append(
                    f"parity fail: sum(pid.rtp_pp)={rtp_pp_sum:.4f} vs "
                    f"summary.rtp.point_pct={rtp_value:.4f}"
                )
        # If n_pids == 0, leave parity_check = "na" — no per-pid breakdown.

    row["issues_summary"] = "; ".join(issues)
    return row


def _load_all_completed_rows() -> list[dict[str, Any]]:
    """Walk both work plans, yield rows with status=='completed' that
    have a summary_path."""
    out = []
    for path in WORK_PLAN_PATHS:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("status") == "completed" and r.get("summary_path"):
                    out.append(r)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inject-bug", action="store_true",
                    help="Self-bug-check: synthetically flip L1=fail in a "
                         "copy of one summary, confirm verifier catches it.")
    args = ap.parse_args()

    if args.inject_bug:
        return _inject_bug_self_check()

    rows = _load_all_completed_rows()
    out_rows: list[dict[str, Any]] = []
    for r in rows:
        try:
            mode = int(r.get("mode") or 1)
        except ValueError:
            mode = 1
        out = _verify_one(Path(r["summary_path"]), r["machine"], mode)
        out_rows.append(out)

    with VERIFICATION_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for o in out_rows:
            w.writerow(o)

    # Print quick summary so the operator sees something
    import collections
    counts = {}
    for col in ("l1", "l2", "l3", "l4_ok", "parity_check",
                "eff_ver_format_ok", "gate_struct_ok", "schema_ok"):
        c = collections.Counter(o[col] for o in out_rows)
        counts[col] = dict(c)
    print(f"[verifier] scanned {len(out_rows)} completed reports")
    for col, c in counts.items():
        print(f"  {col:18}: {c}")
    print(f"[verifier] wrote {VERIFICATION_CSV}")
    return 0


def _inject_bug_self_check() -> int:
    """Synthetic L1 flip — proves the verifier actually catches a forged
    failure (regression guard per memory feedback_integration_test_argv.md)."""
    completed = _load_all_completed_rows()
    if not completed:
        print("[verifier] no completed rows to inject against; run runner first",
              file=sys.stderr)
        return 2
    src = Path(completed[0]["summary_path"])
    if not src.exists():
        print(f"[verifier] sample summary not on disk: {src}", file=sys.stderr)
        return 2
    s = json.loads(src.read_text(encoding="utf-8"))
    s.setdefault("rtp_integrity_check", {})["layer1_invariant_ok"] = False
    s["rtp_integrity_check"]["layer1_error"] = "injected: synthetic L1 failure"
    import tempfile
    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(s, f)
        tmp = Path(f.name)
    try:
        row = _verify_one(tmp, completed[0]["machine"], 1)
        if row["l1"] != "fail":
            print(f"[verifier] INJECT BUG NOT CAUGHT: row['l1']={row['l1']!r}",
                  file=sys.stderr)
            return 1
        if "L1 fail" not in row["issues_summary"]:
            print(f"[verifier] INJECT BUG caught but issues_summary missing "
                  f"L1 mention: {row['issues_summary']!r}", file=sys.stderr)
            return 1
        print(f"[verifier] inject-bug PASS: L1 flip caught for {completed[0]['machine']}")
        return 0
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
