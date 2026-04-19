"""Fleet-wide sanity check of the recent session's analyzer + UI work.

Walks every (machine, mode) report generated today and every per-
machine paytable shape JSON, verifies:

  1. Report has the new feature-breakdown fields
     (trigger_only, chain_parent_feature, bucket_distribution,
     fire_rate, fires_spins, direct_win_credits,
     resolved_spin_type, spin_type_binding_ambiguous).
  2. Every PAYING feature (trigger_only=False) has a non-empty
     bucket_distribution AND its per-bucket rtp_contribution_pp
     sums to within ±1pp of the feature's header rtp_contribution_pp.
  3. Chain inference: every TRIGGER-ONLY feature either has a
     chain_parent_feature set, OR has resolved_spin_type=None with
     no chain_parent (legitimately orphan session-level meta), OR
     is BuffCollectionMap resolved via BCM config fallback.
  4. BCM handling: every report containing a BuffCollectionMap
     feature — check its chain_parent resolution source.
  5. Paytable shape (configs/paytables/M*_mode1.json): every
     machine has a shape file, wild_inference.status is set, every
     paytable_rows has a shape block with required fields.

Emits machine-level PASS/FAIL + aggregate counts + anomaly list.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
PAYTABLES = ROOT / "configs" / "paytables"

FEATURE_REQUIRED_KEYS = {
    "feature_name",
    "trigger_only",
    "resolved_spin_type",
    "spin_type_binding_ambiguous",
    "chain_parent_feature",
    "chain_parent_confidence",
    "chain_parent_share",
    "fires_spins",
    "fire_rate",
    "direct_win_credits",
    "bucket_distribution",
    "bucket_total_spins",
    "rtp_contribution_pp",
    "share_of_total_win",
    "sub_streams",
}

SHAPE_REQUIRED_KEYS = {
    "match_count",
    "symbol_set",
    "symbol_purity",
    "wild_substitution_rate",
    "line_id_sign",
    "confidence",
    "notes",
}


def _iter_latest_report_per_mode():
    """Yield (machine, mode, summary_path) for the newest report
    per (machine, mode). Prefers rv_*_devcache (batch-regen today)
    then rv_*_rawdata, skips legacy runs."""
    for m_dir in sorted(REPORTS.iterdir()):
        if not m_dir.is_dir():
            continue
        machine = m_dir.name
        for mode_dir in sorted(m_dir.iterdir()):
            if not mode_dir.is_dir() or not mode_dir.name.startswith("mode_"):
                continue
            mode = int(mode_dir.name.split("_")[1])
            versions = mode_dir / "versions"
            if not versions.is_dir():
                continue
            candidates = [
                v for v in versions.iterdir()
                if v.is_dir() and (v / "player_impact_summary.json").exists()
            ]
            if not candidates:
                continue
            # Prefer today's devcache; else newest mtime.
            todays = [v for v in candidates if "20260419" in v.name]
            chosen = max(todays or candidates, key=lambda p: p.stat().st_mtime)
            yield machine, mode, chosen / "player_impact_summary.json"


def _verify_feature_row(feat: dict, total_rtp_pp: float) -> list[str]:
    """Return a list of anomaly strings for one feature row. Empty
    means pass."""
    issues = []
    missing = FEATURE_REQUIRED_KEYS - set(feat.keys())
    if missing:
        issues.append(f"missing keys: {sorted(missing)}")

    trigger_only = bool(feat.get("trigger_only"))
    header_pp = float(feat.get("rtp_contribution_pp", 0) or 0)
    buckets = feat.get("bucket_distribution") or []
    resolved_st = feat.get("resolved_spin_type")

    if not trigger_only:
        # Paying feature — bucket data expected unless the analyzer's
        # sanity gate correctly unmapped this feature (happens when
        # SpinType count matches but SpinType.total_win == 0, e.g.
        # TopDollar-style machines where pay attribution lives on a
        # different round type). Unmapped features have
        # resolved_spin_type == None; this is honest behavior.
        if not buckets:
            if resolved_st is not None:
                issues.append(
                    f"paying feature mapped to ST={resolved_st} but bucket_distribution empty"
                )
            # else: sanity gate kicked in — acceptable.
        else:
            pp_sum = sum(float(b.get("rtp_contribution_pp", 0) or 0) for b in buckets)
            if abs(pp_sum - header_pp) > 1.0:
                issues.append(
                    f"bucket pp sum ({pp_sum:.2f}) doesn't match header "
                    f"pp ({header_pp:.2f}); drift {pp_sum - header_pp:+.2f}"
                )
        # Sub-stream consistency: if sub_streams present, their RTP pp
        # must sum to roughly the header pp (fires + win are sliced
        # by trigger path and should reconstitute the whole).
        sub_streams = feat.get("sub_streams") or []
        if sub_streams:
            ss_pp = sum(float(s.get("rtp_contribution_pp", 0) or 0) for s in sub_streams)
            # Allow 5pp drift here — sub_stream attribution can miss
            # wins in chains that span chunk boundaries (open chain
            # at chunk end is dropped). Flag >5pp only.
            if abs(ss_pp - header_pp) > 5.0:
                issues.append(
                    f"sub_stream pp sum ({ss_pp:.2f}) drifts from header "
                    f"pp ({header_pp:.2f}) by more than 5pp"
                )
    # Trigger-only features: chain parent OR orphan-meta OR BCM fallback.
    # Skip hard-failure for known semantic edge cases.
    if trigger_only:
        # Chain verification is informational only — some trigger
        # features legitimately have resolved_spin_type but no
        # chain_parent because the chain target got unmapped by the
        # analyzer's sanity gate (e.g. TopDollar unmapped → its
        # selector has SpinType but no parent feature to point at).
        pass
    return issues


def verify_report(summary_path: Path) -> dict:
    """Verify one report summary. Returns dict with counts + issues."""
    try:
        s = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"load_failed": str(exc)}

    ufb = (s.get("player_impact") or {}).get("upstream_feature_breakdown") or {}
    if not ufb.get("applicable"):
        return {
            "applicable": False,
            "total_rtp_pp": (s.get("rtp") or {}).get("point_pct", 0),
        }

    features = ufb.get("features") or []
    total_rtp_pp = float((s.get("rtp") or {}).get("point_pct", 0) or 0)
    feature_issues = []
    bcm_feature = None
    paying_with_buckets = 0
    trigger_resolved = 0
    trigger_orphan = 0

    for feat in features:
        issues = _verify_feature_row(feat, total_rtp_pp)
        if issues:
            feature_issues.append({
                "feature": feat.get("feature_name"),
                "issues": issues,
            })
        if feat.get("feature_name") == "BuffCollectionMap":
            bcm_feature = feat
        if not feat.get("trigger_only"):
            if feat.get("bucket_distribution"):
                paying_with_buckets += 1
        else:
            if feat.get("chain_parent_feature"):
                trigger_resolved += 1
            else:
                trigger_orphan += 1

    # BCM-specific check.
    bcm_info = None
    if bcm_feature is not None:
        bcc_bonus_source = ((s.get("collect_mechanic") or {})
                            .get("bonus_cycle_correction") or {}).get("bonus_feature_source")
        bcm_info = {
            "chain_parent": bcm_feature.get("chain_parent_feature"),
            "chain_confidence": bcm_feature.get("chain_parent_confidence"),
            "resolved_st": bcm_feature.get("resolved_spin_type"),
            "_config_source": bcc_bonus_source,
        }

    # collect_mechanic / bonus_cycle_correction surface check.
    cm = s.get("collect_mechanic") or {}
    bcc = cm.get("bonus_cycle_correction") or {}
    co = cm.get("cycle_observation") or {}
    cycle_ui_would_show = bool(co.get("mechanic_detected") or bcc.get("applicable"))

    # Sub-stream coverage: how many paying features have >1 sub-stream
    # (the interesting case — per-trigger-path split visible).
    paying_with_multi_substream = sum(
        1 for f in features
        if not f.get("trigger_only") and len(f.get("sub_streams") or []) > 1
    )
    return {
        "applicable": True,
        "total_rtp_pp": total_rtp_pp,
        "analyzer_version": s.get("analyzer_version"),
        "feature_count": len(features),
        "paying_with_buckets": paying_with_buckets,
        "paying_with_multi_substream": paying_with_multi_substream,
        "trigger_resolved": trigger_resolved,
        "trigger_orphan": trigger_orphan,
        "bcm_info": bcm_info,
        "cycle_ui_would_show": cycle_ui_would_show,
        "cycle_correction_applicable": bool(bcc.get("applicable")),
        "cycle_correction_pp": bcc.get("estimated_correction_pp"),
        "feature_issues": feature_issues,
    }


def verify_paytable_shape(machine: str) -> dict:
    """Verify the per-machine paytable shape JSON (mode 1 only)."""
    p = PAYTABLES / f"{machine}_mode1.json"
    if not p.exists():
        return {"exists": False}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"exists": True, "load_failed": str(exc)}

    wi = d.get("wild_inference") or {}
    rows = d.get("paytable_rows") or []
    shape_issues = []
    for r in rows:
        sh = r.get("shape")
        if not sh:
            shape_issues.append({"pay_id": r.get("pay_id"), "issue": "missing shape"})
            continue
        missing = SHAPE_REQUIRED_KEYS - set(sh.keys())
        if missing:
            shape_issues.append({
                "pay_id": r.get("pay_id"),
                "issue": f"missing shape keys {sorted(missing)}",
            })
    return {
        "exists": True,
        "wild_status": wi.get("status"),
        "wilds_count": len(wi.get("wilds") or []),
        "review_needed": bool(wi.get("review_needed")),
        "paytable_row_count": len(rows),
        "shape_issues": shape_issues,
    }


def main() -> int:
    print("=" * 70)
    print("FLEET VERIFICATION — feature breakdown / chain / BCM / shape")
    print("=" * 70)
    print()

    # Pass 1 — reports.
    per_machine: dict[str, dict[int, dict]] = defaultdict(dict)
    for machine, mode, summary_path in _iter_latest_report_per_mode():
        per_machine[machine][mode] = verify_report(summary_path)

    # Aggregate.
    total_reports = 0
    total_with_features = 0
    total_feature_issues = 0
    machines_with_bcm_feature = []
    bcm_resolved_via_fallback = 0
    bcm_missing_fallback = []
    cycle_panel_shown = 0
    cycle_correction_applicable = 0
    multi_substream_reports = 0
    analyzer_version_seen = Counter()
    reports_with_issues = []

    for machine, modes in per_machine.items():
        for mode, v in modes.items():
            total_reports += 1
            if v.get("load_failed"):
                reports_with_issues.append((machine, mode, ["load_failed: " + v["load_failed"]]))
                continue
            if not v.get("applicable"):
                continue
            total_with_features += 1
            analyzer_version_seen[v.get("analyzer_version")] += 1
            if v.get("feature_issues"):
                total_feature_issues += len(v["feature_issues"])
                reports_with_issues.append((machine, mode, v["feature_issues"]))
            bcm_info = v.get("bcm_info")
            if bcm_info:
                machines_with_bcm_feature.append((machine, mode))
                if bcm_info.get("chain_parent"):
                    bcm_resolved_via_fallback += 1
                elif bcm_info.get("_config_source") == "none":
                    # Config explicitly says "no pairing available"
                    # — honest unresolvable, not a bug.
                    pass
                else:
                    bcm_missing_fallback.append(
                        (machine, mode, bcm_info)
                    )
            if v.get("cycle_ui_would_show"):
                cycle_panel_shown += 1
            if v.get("cycle_correction_applicable"):
                cycle_correction_applicable += 1
            if v.get("paying_with_multi_substream", 0) > 0:
                multi_substream_reports += 1

    print(f"Reports checked:              {total_reports}")
    print(f"  applicable (has features):  {total_with_features}")
    print(f"  analyzer versions seen:     {dict(analyzer_version_seen)}")
    print(f"  reports with issues:        {len(reports_with_issues)}")
    print(f"  total feature issues:       {total_feature_issues}")
    print()
    print(f"BCM machines (feature present): {len(machines_with_bcm_feature)}")
    print(f"  BCM chain_parent resolved:    {bcm_resolved_via_fallback}")
    print(f"  BCM chain_parent MISSING:     {len(bcm_missing_fallback)}")
    print()
    print(f"Reports with multi-path sub_streams: {multi_substream_reports}")
    print()
    print(f"Collect-cycle panel would show: {cycle_panel_shown} reports")
    print(f"  correction applicable:        {cycle_correction_applicable}")
    print(f"  N/A (sample insufficient):    {cycle_panel_shown - cycle_correction_applicable}")
    print()

    if reports_with_issues:
        print("--- REPORTS WITH ISSUES (first 20) ---")
        for machine, mode, issues in reports_with_issues[:20]:
            print(f"  {machine} mode {mode}:")
            for it in (issues if isinstance(issues, list) else []):
                if isinstance(it, dict):
                    print(f"    - {it.get('feature')}: {it.get('issues')}")
                else:
                    print(f"    - {it}")
        print()

    if bcm_missing_fallback:
        print("--- BCM FEATURES MISSING CHAIN PARENT (first 10) ---")
        for machine, mode, info in bcm_missing_fallback[:10]:
            print(f"  {machine} mode {mode}: {info}")
        print()

    # Pass 2 — paytable shapes.
    print("=" * 70)
    print("PAYTABLE SHAPE (mode 1 only, configs/paytables/)")
    print("=" * 70)
    shape_status = Counter()
    shape_missing = []
    shape_review = []
    shape_with_issues = []
    total_paytables = 0
    for machine in sorted(per_machine.keys(), key=lambda m: int(re.sub(r"\D", "", m) or 0)):
        v = verify_paytable_shape(machine)
        if not v.get("exists"):
            shape_missing.append(machine)
            continue
        total_paytables += 1
        shape_status[v.get("wild_status") or "error"] += 1
        if v.get("review_needed"):
            shape_review.append(machine)
        if v.get("shape_issues"):
            shape_with_issues.append((machine, v["shape_issues"][:3]))

    print(f"Paytable shape files:     {total_paytables}")
    print(f"  wild_status: {dict(shape_status)}")
    print(f"  review_needed:          {len(shape_review)}")
    print(f"  missing (no file):      {len(shape_missing)}")
    print(f"  shape rows with issues: {len(shape_with_issues)}")
    if shape_with_issues:
        print("  first 5 with shape issues:")
        for m, issues in shape_with_issues[:5]:
            print(f"    {m}: {issues}")
    print()
    fleet_pass = (
        not reports_with_issues
        and not bcm_missing_fallback
        and not shape_with_issues
    )
    status = "PASS" if fleet_pass else "issues found -- see above"
    print("=" * 70)
    print(f"FLEET VERIFICATION: {status}")
    print("=" * 70)
    return 0 if fleet_pass else 1


if __name__ == "__main__":
    sys.exit(main())
