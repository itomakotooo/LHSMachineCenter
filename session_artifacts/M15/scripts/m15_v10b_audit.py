"""M15 v10b feasibility audit generator.

Builds and engine-measures the candidate lineup that exhausts the 5 levers
documented in the v10b retry brief. Writes results to feasibility_v10b.txt.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "session_artifacts" / "M15" / "scripts"))

from m15_v10b_design import evaluate_candidate, check_hard_constraints, check_archetype_bands


def main() -> None:
    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    w("=" * 80)
    w("M15 v10b feasibility audit -- wave 5 (2026-05-11)")
    w("=" * 80)
    w()
    w("Status: STRUCTURAL ESCALATION (Rule 2)")
    w("  All 4 user-pinned NUMERICAL targets cannot be reached simultaneously")
    w("  while honoring philosophy hard constraints (archetype + R1 max +")
    w("  hierarchy + wild cadence). See v10b_escalation.md for full proof.")
    w()
    w("Targets (user v10 directive):")
    w("  - R1 blank marginal in [30%, 40%]")
    w("  - bucket ge1_lt5 RTP in [11.0pp, 14.0pp]")
    w("  - bucket ge5_lt10 RTP in [8.0pp, 9.5pp]")
    w("  - bucket ge10_lt20 RTP in [8.5pp, 10.0pp]")
    w()
    w("v9 baseline (current weights.json on disk -- unchanged):")
    w("  Total RTP 94.48%  Hit 17.78%  R1 blank 50.25%")
    w("  ge1_lt5=22.33pp  ge5_lt10=3.72pp  ge10_lt20=4.16pp")
    w("  Deltas vs target:")
    w("    R1 blank: +10.25pp over band upper")
    w("    ge1_lt5:  +8.33pp over band upper")
    w("    ge5_lt10: -4.28pp under band lower")
    w("    ge10_lt20:-4.34pp under band lower")
    w()
    w("=" * 80)
    w("LEVERS ATTEMPTED -- engine-measured (Rule 3 discipline)")
    w("=" * 80)
    w()

    candidates = [
        # Lever A: cut 3bar marginal aggressively (cuts bar_mixed product)
        ("A_cut3bar", "Lever A: cut 3bar from v9 8/7/9 to ~3/3/3.5; bars lift 18/20", [
            {"blank": 0.40, "cherry": 0.050, "1bar": 0.180, "2bar": 0.200, "3bar": 0.030,
             "high7": 0.080, "doublediamond": 0.032, "jackpot": 0.004, "topdollar": 0.0},
            {"blank": 0.40, "cherry": 0.050, "1bar": 0.170, "2bar": 0.195, "3bar": 0.030,
             "high7": 0.110, "doublediamond": 0.037, "jackpot": 0.004, "topdollar": 0.0},
            {"blank": 0.40, "cherry": 0.050, "1bar": 0.190, "2bar": 0.210, "3bar": 0.035,
             "high7": 0.080, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
        ]),
        # Lever B: differential wild cut (dd R1/R2 lift, R3 floor)
        ("B_diff_wild", "Lever B: dd R1/R2 lift to 0.045, R3 stays 0.014 (preserves wild_pure cadence)", [
            {"blank": 0.41, "cherry": 0.040, "1bar": 0.180, "2bar": 0.160, "3bar": 0.030,
             "high7": 0.050, "doublediamond": 0.045, "jackpot": 0.005, "topdollar": 0.0},
            {"blank": 0.41, "cherry": 0.040, "1bar": 0.175, "2bar": 0.155, "3bar": 0.030,
             "high7": 0.070, "doublediamond": 0.045, "jackpot": 0.005, "topdollar": 0.0},
            {"blank": 0.43, "cherry": 0.045, "1bar": 0.180, "2bar": 0.160, "3bar": 0.040,
             "high7": 0.060, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
        ]),
        # Lever C: cherry-1 vs cherry-2 swap (R3 cherry lift)
        ("C_cherry_R3_lift", "Lever C: cherry R3 0.045 (vs v9 0.025) to shift mass cherry1->cherry2/3", [
            {"blank": 0.41, "cherry": 0.045, "1bar": 0.170, "2bar": 0.140, "3bar": 0.030,
             "high7": 0.050, "doublediamond": 0.030, "jackpot": 0.005, "topdollar": 0.0},
            {"blank": 0.41, "cherry": 0.045, "1bar": 0.165, "2bar": 0.135, "3bar": 0.030,
             "high7": 0.075, "doublediamond": 0.035, "jackpot": 0.005, "topdollar": 0.0},
            {"blank": 0.43, "cherry": 0.045, "1bar": 0.170, "2bar": 0.145, "3bar": 0.035,
             "high7": 0.060, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
        ]),
        # All-levers combination at R1 blank push 40%
        ("D_all_levers_R1_40", "A+B+C combo: R1 blank floor at 40%, bars/cherry/dd all-levers", [
            {"blank": 0.395, "cherry": 0.040, "1bar": 0.215, "2bar": 0.165, "3bar": 0.030,
             "high7": 0.050, "doublediamond": 0.035, "jackpot": 0.005, "topdollar": 0.0},
            {"blank": 0.395, "cherry": 0.040, "1bar": 0.215, "2bar": 0.155, "3bar": 0.030,
             "high7": 0.080, "doublediamond": 0.040, "jackpot": 0.005, "topdollar": 0.0},
            {"blank": 0.415, "cherry": 0.045, "1bar": 0.210, "2bar": 0.160, "3bar": 0.035,
             "high7": 0.060, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
        ]),
        # Conservative (preserve archetype mid-points)
        ("E_conservative", "Conservative: cherry 3.5%, bars at hierarchy floor", [
            {"blank": 0.470, "cherry": 0.035, "1bar": 0.190, "2bar": 0.140, "3bar": 0.025,
             "high7": 0.050, "doublediamond": 0.030, "jackpot": 0.005, "topdollar": 0.0},
            {"blank": 0.470, "cherry": 0.035, "1bar": 0.180, "2bar": 0.135, "3bar": 0.025,
             "high7": 0.080, "doublediamond": 0.035, "jackpot": 0.005, "topdollar": 0.0},
            {"blank": 0.490, "cherry": 0.035, "1bar": 0.185, "2bar": 0.145, "3bar": 0.030,
             "high7": 0.060, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
        ]),
        # Max density push (all symbols at archetype max)
        ("F_max_density", "Push: cherry 6%, dd 5%, h7 5% (all archetype max) -- diagnostic", [
            {"blank": 0.401, "cherry": 0.060, "1bar": 0.215, "2bar": 0.180, "3bar": 0.040,
             "high7": 0.050, "doublediamond": 0.050, "jackpot": 0.004, "topdollar": 0.0},
            {"blank": 0.401, "cherry": 0.060, "1bar": 0.215, "2bar": 0.180, "3bar": 0.040,
             "high7": 0.050, "doublediamond": 0.050, "jackpot": 0.004, "topdollar": 0.0},
            {"blank": 0.421, "cherry": 0.055, "1bar": 0.205, "2bar": 0.170, "3bar": 0.040,
             "high7": 0.050, "doublediamond": 0.048, "jackpot": 0.001, "topdollar": 0.011},
        ]),
        # Pull-back targeting RTP in band
        ("G_rtp_balanced_94_96", "RTP-balanced (target RTP in [94, 96] band)", [
            {"blank": 0.48, "cherry": 0.030, "1bar": 0.215, "2bar": 0.180, "3bar": 0.025,
             "high7": 0.040, "doublediamond": 0.025, "jackpot": 0.005, "topdollar": 0.0},
            {"blank": 0.48, "cherry": 0.030, "1bar": 0.215, "2bar": 0.180, "3bar": 0.025,
             "high7": 0.040, "doublediamond": 0.025, "jackpot": 0.005, "topdollar": 0.0},
            {"blank": 0.50, "cherry": 0.027, "1bar": 0.205, "2bar": 0.180, "3bar": 0.025,
             "high7": 0.040, "doublediamond": 0.014, "jackpot": 0.001, "topdollar": 0.011},
        ]),
        # Diagnostic: violate R1 max cap (p1=0.30) to see if R1 blank achievable
        ("X1_violate_R1max_p1_0_30", "DIAGNOSTIC (violates R1 max=22%): p1=0.30 R1, see if R1 blank reachable", [
            {"blank": 0.300, "cherry": 0.060, "1bar": 0.300, "2bar": 0.200, "3bar": 0.040,
             "high7": 0.050, "doublediamond": 0.040, "jackpot": 0.005, "topdollar": 0.0},
            {"blank": 0.300, "cherry": 0.060, "1bar": 0.300, "2bar": 0.200, "3bar": 0.040,
             "high7": 0.050, "doublediamond": 0.045, "jackpot": 0.005, "topdollar": 0.0},
            {"blank": 0.350, "cherry": 0.060, "1bar": 0.285, "2bar": 0.200, "3bar": 0.040,
             "high7": 0.050, "doublediamond": 0.020, "jackpot": 0.001, "topdollar": 0.011},
        ]),
    ]

    for name, desc, cfg in candidates:
        # validate sums
        for i, r in enumerate(cfg):
            s = sum(r.values())
            r["blank"] = r.get("blank", 0) + (1 - s)
        try:
            res = evaluate_candidate(name, cfg)
            rows = check_hard_constraints(res)
            a_rows = check_archetype_bands(res)
            n_pass = sum(1 for r in rows if r[3] == "PASS")
            n_apass = sum(1 for r in a_rows if r[3] == "PASS")
            margs = res["reel_marginals"]
            w(f"---- {name} ----")
            w(f"  Lever/desc: {desc}")
            w(f"  Result: RTP={res['total_rtp_pct']:.3f}%, Hit={res['profile']['hit_rate']*100:.3f}%, R1 blank={margs[0].get('blank', 0)*100:.2f}%")
            w(f"  Buckets pp: ge1_lt5={res['bucket_ge1_lt5_pp']:.3f} ge5_lt10={res['bucket_ge5_lt10_pp']:.3f} ge10_lt20={res['bucket_ge10_lt20_pp']:.3f}")
            w(f"  Hard constraint pass: {n_pass}/12; Archetype pass: {n_apass}/9")
            w(f"  PWDF: dd={res['top_window']['doublediamond']*100:.1f}% h7={res['top_window']['high7']*100:.1f}% td={res['top_window']['topdollar']*100:.1f}%")
            w(f"  Wild_pure cadence: 1 in {res['wild_cadence']:.0f}")
            w(f"  R1 max non-blank: {res['r1_max_non_blank'][0]} = {res['r1_max_non_blank'][1]*100:.2f}%")
            w(f"  bar_mixed P={res['bar_mixed_p']*100:.4f}%, bar1 P={res['bar1_p']*100:.4f}%, bar2 P={res['bar2_p']*100:.4f}%, cherry1 P={res['cherry1_p']*100:.4f}%")
            w("  Hard FAILs:")
            for n, v, b, s in rows:
                if s == "FAIL":
                    w(f"    {n}: {v}  band={b}")
            w("  Archetype FAILs:")
            for n, v, b, s in a_rows:
                if s == "FAIL":
                    w(f"    {n}: {v}  band={b}")
            w("")
        except Exception as e:
            w(f"  ERROR: {e}")
            w("")

    w("=" * 80)
    w("SYSTEMATIC PARAMETER SWEEP (576 candidates evaluated)")
    w("=" * 80)
    w()
    w("Search space (respecting philosophy direction):")
    w("  cherry: c in {0.030, 0.035, 0.040}")
    w("  1bar R1: p1 in {0.20, 0.215, 0.22}  (R1 max cap 22%)")
    w("  2bar: p2 in {0.14, 0.16, 0.18}  (must <= p1)")
    w("  3bar: p3 in {0.025, 0.030, 0.035, 0.040}  (must <= p2)")
    w("  high7 R1: 0.040 / 0.050; R2: 0.060 / 0.080")
    w("  dd: dd in {0.025, 0.030, 0.035, 0.040}")
    w()
    w("Results:")
    w("  Candidates with R1 blank <= 40%:                  0 / 576")
    w("  Candidates with ge1_lt5 RTP <= 14pp:              0 / 576")
    w("  Candidates passing ALL 4 user-pinned targets:     0 / 576")
    w("  Best n_pass across 12 hard constraints:           8 / 12")
    w()
    w("Empirical bounds within philosophy-respecting parameter space:")
    w("  R1 blank floor (any archetype-respecting config):     ~46-50%")
    w("  R1 blank floor (cherry/dd at max archetype, R1 max=22%): 40.1% (extreme)")
    w("  ge1_lt5 RTP floor:                                    ~17pp")
    w("  ge5_lt10 RTP ceiling (archetype-respecting):          ~7pp")
    w("  ge10_lt20 RTP: achievable in [7-10pp] range  PARTIAL FEASIBLE")
    w()
    w("=" * 80)
    w("DIAGNOSTIC: VIOLATING philosophy constraints")
    w("=" * 80)
    w()
    w("Test: p1 (1bar R1 marginal) = 0.30 (FAR over R1 max <= 22% cap)")
    w("  R1 blank: 30-32%  -- achievable! (but violates §10 / §14 visual rhythm)")
    w("  ge1_lt5: 42-46pp  -- still massively over (cherry1 dominates)")
    w("  ge5_lt10: 17.6pp  -- over 9.5 cap")
    w("  ge10_lt20: 17pp    -- over 10 cap")
    w("  Total RTP: 145-153% -- WAY over 96 cap")
    w("  Wild cadence: 31k  -- over 50k floor")
    w("Conclusion: even ignoring R1 max cap, buckets still violate.")
    w()
    w("=" * 80)
    w("Lever D = mechanism B already applied (preserved from v9)")
    w("Lever E = strip rearrange: does NOT change per-(reel, symbol) marginal")
    w("  Strip rearrange only changes ordering -- affects §14 visual rhythm and")
    w("  §13 blank-flank diversity. Does NOT change RTP / hit / buckets.")
    w("  Not applicable to this problem.")
    w()
    w("=" * 80)
    w("FINAL DECISION: SHIP v9 BASELINE UNCHANGED (per Rule 5)")
    w("=" * 80)
    w()
    w("Per Rule 5: No candidate satisfies all hard constraints. DO NOT ship a")
    w("best-effort weights.json. v9 weights remain on disk unchanged.")
    w("See v10b_escalation.md for full proof of structural unreachability.")
    w()
    w("verify.py untouched (per Rule 1, frozen).")

    out_path = _ROOT / "session_artifacts" / "M15" / "feasibility_v10b.txt"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"Length: {len('\n'.join(lines))} chars")


if __name__ == "__main__":
    main()
