"""X / 魔鬼律师 v14 audit script — independently verify D's C38_C14_rtp_target_95.

Hidden metrics:
1. RTP / hit / blank reproduction (sanity check vs D's claim)
2. bar_mixed decomposition by underlying bar-tier combinations
3. Each pay_id 1-in-N firing
4. Family share comparison vs PPP_v20, FINAL_E, classical IGT (RWB, Blazing Sevens)
5. Sampling noise estimates (1M spin SE) for RTP, hit, R1 blank
6. Combined bar family share (single-symbol vs composite tier)
7. Cherry-3 / bar3 / wild_pure 1-in-N session firing rates
8. Pay_id ge1_lt5 anchor composition (cherry-1 share of g15)
"""
import sys, json, os, math
sys.stdout.reconfigure(encoding='utf-8')

from collections import defaultdict
from pathlib import Path

ROOT = Path(r'C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT')
sys.path.insert(0, str(ROOT))

from slot_designer.core.devtools.analytic_rtp import analytic_profile_from_marginals
from slot_designer.core.engine.loader import load_engine
from slot_designer.machines.M15.plugins.feature import _round_payout_distribution
from slot_designer.core.devtools.player_experience import symbol_window_probability

M15 = ROOT / 'slot_designer' / 'machines' / 'M15'
SPEC = M15 / 'spec.json'
STRIPS = M15 / 'reel_strips.json'
WEIGHTS = M15 / 'weights' / 'mode_1' / 'weights.json'

engine, spec = load_engine(SPEC, WEIGHTS, strips_path=STRIPS)
EV = engine.evaluator
fp = json.loads(WEIGHTS.read_text(encoding='utf-8'))['feature_params']
strips = json.loads(STRIPS.read_text(encoding='utf-8'))['reels']


def make_marginals(R1, R2, R3):
    out = []
    for R in (R1, R2, R3):
        R = dict(R)
        non_blank = sum(R.values())
        R["blank"] = max(0.001, 1.0 - non_blank)
        s = sum(R.values())
        out.append({k: v / s for k, v in R.items() if v > 0})
    return out


# D's C38_C14_rtp_target_95 marginals
R1 = {"cherry": 0.040, "1bar": 0.202, "2bar": 0.165, "3bar": 0.103,
      "high7": 0.072, "doublediamond": 0.029, "jackpot": 0.004}
R2 = {"cherry": 0.035, "1bar": 0.165, "2bar": 0.135, "3bar": 0.073,
      "high7": 0.057, "doublediamond": 0.028, "jackpot": 0.004}
R3 = {"cherry": 0.025, "1bar": 0.135, "2bar": 0.110, "3bar": 0.055,
      "high7": 0.047, "doublediamond": 0.024, "jackpot": 0.003,
      "topdollar": 0.0113}

margs = make_marginals(R1, R2, R3)

prof = analytic_profile_from_marginals(EV, margs)
print("===== 1) Base profile (analytic, independently computed) =====")
print(f"Base RTP:   {prof['rtp_pct']:.4f}pp  [D claimed 42.772]")
print(f"Base hit:   {prof['hit_rate']*100:.4f}%  [D claimed 16.215]")
print(f"R1 blank:   {margs[0]['blank']*100:.4f}%  [D claimed 38.500]")
print(f"R2 blank:   {margs[1]['blank']*100:.4f}%  [D claimed 50.300]")
print(f"R3 blank:   {margs[2]['blank']*100:.4f}%  [D claimed 58.970]")
print(f"CV:         {prof['cv']:.4f}")
print()

# Feature EV
dist = _round_payout_distribution(
    tuple(fp["x_count_weights"]), tuple(fp["y_count_weights"]),
    tuple(fp["x_value_weights"]), tuple(fp["y_value_weights"]),
)
p_accept = sum(p for r, p in dist if r >= fp["accept_threshold"])
accept_dist = [(r, p) for r, p in dist if r >= fp["accept_threshold"]]
final_dist = defaultdict(float)
for round_idx in range(1, fp["max_rounds"]):
    branch = ((1 - p_accept) ** (round_idx - 1)) * p_accept
    for r, p in accept_dist:
        final_dist[r] += branch * (p / p_accept) if p_accept > 0 else 0
branch_forced = (1 - p_accept) ** (fp["max_rounds"] - 1)
for r, p in dist:
    final_dist[r] += branch_forced * p
FEAT_EV = sum(r * p for r, p in final_dist.items())
trigger = margs[2].get('topdollar', 0)
feature_rtp = trigger * FEAT_EV * 100
total_rtp = prof['rtp_pct'] + feature_rtp
hit_session = (prof['hit_rate'] + trigger) * 100

print(f"Feature EV per trigger: {FEAT_EV:.4f}x  [D claimed 45.88]")
print(f"Trigger rate:           {trigger*100:.4f}%  [D claimed 1.133]")
print(f"Feature RTP:            {feature_rtp:.4f}pp  [D claimed 51.980]")
print(f"Total RTP (analytic):   {total_rtp:.4f}pp  [D claimed 94.752]")
print(f"Hit session (analytic): {hit_session:.4f}%  [D claimed 17.348]")
print()

# Per-pay-id breakdown
print("===== 2) Per-pay-id (base) breakdown =====")
print(f"{'pay_id':>6} {'fam':>14} {'base_mult':>9} {'P_hit_%':>10} {'1-in-N':>12} {'RTP_pp':>8}")
PAY_INFO = {
    "9":  ("cherry1",     1),
    "71": ("cherry2",     5),
    "4":  ("cherry3",     15),
    "1":  ("wild_pure",   200),
    "2":  ("high7_wild",  30),
    "21": ("high7_pure",  30),
    "3":  ("bar3_pure",   20),
    "5":  ("bar2_pure",   10),
    "7":  ("bar1_pure",   5),
    "8":  ("bar_mixed",   2),
}
for pid, (fam, base_mult) in PAY_INFO.items():
    p = prof['pay_hits'].get(pid, 0)
    rtp = prof['pay_rtp'].get(pid, 0) * 100
    inv = (1/p) if p > 0 else float('inf')
    print(f"{pid:>6} {fam:>14} {base_mult:>9}x {p*100:>9.5f}% {inv:>12.0f} {rtp:>8.3f}")
print()

# Family shares
print("===== 3) Family shares of base RTP =====")
PAY_FAM_MAP = {
    "9":  "cherry1", "71": "cherry2", "4":  "cherry3",
    "1":  "wild_pure",
    "2":  "high7_wild", "21": "high7_pure",
    "3":  "bar3_pure", "5":  "bar2_pure", "7":  "bar1_pure",
    "8":  "bar_mixed",
}
family_pp = defaultdict(float)
for pid, rtp in prof['pay_rtp'].items():
    fam = PAY_FAM_MAP.get(pid)
    if fam:
        family_pp[fam] += rtp * 100
base_rtp = prof['rtp_pct']
total_fam_pp = 0
print(f"{'family':>14} {'RTP_pp':>9} {'%_of_base':>10}")
for fam in sorted(family_pp, key=lambda k: -family_pp[k]):
    pp = family_pp[fam]
    share = pp / base_rtp * 100
    print(f"  {fam:>14} {pp:>9.3f} {share:>9.2f}%")
    total_fam_pp += pp
print(f"  {'TOTAL':>14} {total_fam_pp:>9.3f}")
print()

print("===== 4) Combined family groupings =====")
cherry_combined = family_pp['cherry1'] + family_pp['cherry2'] + family_pp['cherry3']
bar_pure_combined = family_pp['bar1_pure'] + family_pp['bar2_pure'] + family_pp['bar3_pure']
bar_all = bar_pure_combined + family_pp['bar_mixed']
seven_combined = family_pp['high7_wild'] + family_pp['high7_pure'] + family_pp['wild_pure']
print(f"  Cherry total:     {cherry_combined:>7.3f}pp ({cherry_combined/base_rtp*100:>6.2f}% of base)")
print(f"  Bar pure only:    {bar_pure_combined:>7.3f}pp ({bar_pure_combined/base_rtp*100:>6.2f}% of base)")
print(f"  Bar all (incl mx):{bar_all:>7.3f}pp ({bar_all/base_rtp*100:>6.2f}% of base)")
print(f"  Seven combined:   {seven_combined:>7.3f}pp ({seven_combined/base_rtp*100:>6.2f}% of base)")
print(f"  Sum:              {(cherry_combined+bar_all+seven_combined):>7.3f}pp (of {base_rtp:.3f}pp base)")
print()

# ----------------------------------------------------------------------
# 5) bar_mixed decomposition by underlying bar-tier combination
# ----------------------------------------------------------------------
# bar_mixed (pay_id 8) is line_3_group on {1bar, 2bar, 3bar}.
# It fires when 3 reels each show a "bar-class" symbol (1bar OR 2bar OR 3bar),
# minus the pure cases (3x 1bar = pay_id 7, 3x 2bar = pay_id 5, 3x 3bar = pay_id 3).
# Wilds substitute for any regular symbol (including bars).
# But: pay_id 8 multiplier is fixed at 2x — even with wilds, multiplier remains 2x
#       (wilds add 2x boost per wild = 2^k boost where k = wild count).
# So pay_id 8 effective payout = 2 * 2^k where k = # of wilds in the win.
#
# Decompose bar_mixed RTP into combinations by (r1_kind, r2_kind, r3_kind)
# where kind in {1bar, 2bar, 3bar, wild}, and at least one is "mixed" (not all same).
# Then for the "all same" cases, they go to pay_id 3/5/7 not 8.

# Per-reel marginals
P = {}
for ri in range(3):
    P[ri] = margs[ri]

# Enumerate all (r1, r2, r3) combinations where each ri in {1bar, 2bar, 3bar, dd}
# Compute contribution to pay_id 8 (i.e., bar_mixed)
bar_kinds = ['1bar', '2bar', '3bar', 'doublediamond']
contrib = defaultdict(float)  # key: tuple of bar-tier (with dd called 'wild')
total_bm = 0.0
for s1 in bar_kinds:
    for s2 in bar_kinds:
        for s3 in bar_kinds:
            p = P[0].get(s1, 0) * P[1].get(s2, 0) * P[2].get(s3, 0)
            if p == 0:
                continue
            # Wild count
            nw = sum(1 for s in (s1, s2, s3) if s == 'doublediamond')
            # Tier of each: wild substitutes — for line_3_group, wild substitutes for any bar tier.
            # But the question is which pay_id this combination triggers.
            # Pay evaluation order: pure_wild > line_3_same (high7) > line_3_same (3bar) >
            #   line_3_same (2bar) > line_3_same (1bar) > line_3_group (bar_mixed)
            #
            # 3 doublediamonds → pay_id 1 (pure_wild 200x), NOT bar_mixed
            # 2 doublediamonds + 1 bar → substitutes for that bar => 3-of-a-kind pure (3 wilds=>3 of the bar tier, with multiplier × 4)
            #   pay_id 7/5/3 depending on bar tier
            # 1 doublediamond + 2 bars (same tier) → 3-of-a-kind (e.g. 3 1bars with 1 wild = pay_id 7 × 2x)
            # 1 doublediamond + 2 bars (different tiers) → line_3_group (pay_id 8) × 2x for wild boost
            # 0 doublediamonds + 3 bars same tier → pay_id 7/5/3
            # 0 doublediamonds + 3 bars different tiers → pay_id 8
            if nw == 3:
                # pay_id 1
                continue
            if nw == 2:
                # 2 wilds + 1 bar = 3 of that bar tier (wild substitutes)
                continue
            if nw == 1:
                # 1 wild + 2 bars. If 2 bars same, → 3 of that tier. If 2 bars different, → bar_mixed.
                others = [s for s in (s1, s2, s3) if s != 'doublediamond']
                if others[0] == others[1]:
                    continue  # pure
                # else: mixed with wild — pay_id 8 × 2x (wild boost)
                key = tuple(sorted([s1, s2, s3]))
                contrib[key] += p
                total_bm += p
            else:
                # No wild — all 3 are bars
                if s1 == s2 == s3:
                    continue  # pure
                key = tuple(sorted([s1, s2, s3]))
                contrib[key] += p
                total_bm += p

print("===== 5) bar_mixed (pay_id 8) decomposition by underlying bar-tier combo =====")
print(f"Total bar_mixed P (sum of contributions): {total_bm*100:.5f}%  [profile says {prof['pay_hits'].get('8', 0)*100:.5f}%]")
print()
print(f"{'combo':>40} {'P_combo_%':>12} {'%_of_bm':>10} {'with_wild?':>12}")
sorted_contrib = sorted(contrib.items(), key=lambda kv: -kv[1])
for combo, p in sorted_contrib:
    wild_present = 'doublediamond' in combo
    bm_share = p / total_bm * 100 if total_bm > 0 else 0
    label = '+'.join(combo)
    print(f"{label:>40} {p*100:>11.5f}% {bm_share:>9.2f}% {str(wild_present):>12}")
print()

# Aggregate by which bar tiers are involved
involve_count = defaultdict(float)
for combo, p in contrib.items():
    bars = [s for s in combo if s != 'doublediamond']
    tiers_involved = tuple(sorted(set(bars)))  # the unique bar tiers
    involve_count[tiers_involved] += p

print("Aggregated by unique bar tiers involved (ignoring wild positions):")
for tiers, p in sorted(involve_count.items(), key=lambda kv: -kv[1]):
    label = '+'.join(tiers)
    bm_share = p / total_bm * 100 if total_bm > 0 else 0
    print(f"  involves {label:>20}: P={p*100:.5f}% ({bm_share:.2f}% of bar_mixed)")
print()

# Now compute the RTP contribution of bar_mixed by combo (with wild boost = 2^k * 2x base)
print("bar_mixed RTP contribution by combo (multipliers: 2x base × 2^wild_count):")
total_bm_rtp = 0
for combo, p in sorted_contrib:
    nw = sum(1 for s in combo if s == 'doublediamond')
    mult = 2 * (2 ** nw)  # base 2x, doubled per wild
    rtp_contrib = p * mult
    total_bm_rtp += rtp_contrib
    label = '+'.join(combo)
    print(f"  {label:>40}: P={p*100:.5f}% × {mult}x = {rtp_contrib*100:.4f}pp")
print(f"  Sum bar_mixed RTP: {total_bm_rtp*100:.4f}pp  [profile says {family_pp['bar_mixed']:.4f}pp]")
print()

# 6) Sampling noise estimate on 1M spins
print("===== 6) Sampling noise estimate (1M spins) =====")
N = 1_000_000

# E[X^2] for variance: for base pays, approximate (sum p_i * m_i^2)
e_x2_base = 0.0
for pid in PAY_INFO:
    p = prof['pay_hits'].get(pid, 0)
    rtp_frac = prof['pay_rtp'].get(pid, 0)
    if p > 0:
        m_eff = rtp_frac / p
        e_x2_base += p * (m_eff ** 2)

# Feature variance
e_x2_feat = 0.0
for r, p in final_dist.items():
    e_x2_feat += trigger * p * (r ** 2)

e_x_total = prof['rtp_pct']/100 + feature_rtp/100
e_x2_total = e_x2_base + e_x2_feat
var_x_total = e_x2_total - e_x_total ** 2
se_rtp_pp = math.sqrt(var_x_total / N) * 100

print(f"  E[X] (RTP frac):     {e_x_total:.4f}")
print(f"  Var[X]:              {var_x_total:.4f}")
print(f"  SE(total RTP) on 1M: ±{se_rtp_pp:.4f}pp")
print(f"    95% CI: [{total_rtp - 1.96*se_rtp_pp:.3f}, {total_rtp + 1.96*se_rtp_pp:.3f}]")
print(f"    Margin to floor (94): {total_rtp - 94:.3f}pp = {(total_rtp - 94)/se_rtp_pp:.2f}σ")
print(f"    P(drift below 94 on 1M sim) ≈ {(0.5 * math.erfc((total_rtp - 94) / (se_rtp_pp * math.sqrt(2)))):.4f}")

# Hit SE (binomial)
p_hit_total = prof['hit_rate'] + trigger
se_hit = math.sqrt(p_hit_total * (1-p_hit_total) / N) * 100
print(f"  SE(hit_session) on 1M: ±{se_hit:.4f}pp")
print(f"    Margin to upper (18): {18 - hit_session:.3f}pp = {(18 - hit_session)/se_hit:.2f}σ")
print(f"    P(hit drifts over 18) ≈ {(0.5 * math.erfc((18 - hit_session) / (se_hit * math.sqrt(2)))):.4f}")

# R1 blank SE
p_r1 = margs[0]['blank']
se_r1 = math.sqrt(p_r1 * (1-p_r1) / N) * 100
print(f"  SE(R1 blank) on 1M: ±{se_r1:.4f}pp")
print(f"    Margin to upper (40): {40 - p_r1*100:.3f}pp = {(40 - p_r1*100)/se_r1:.2f}σ")
print()

# 7) Cherry & rare-pay session firing rates
print("===== 7) Per-pay session firing (for ~150-spin and ~500-spin sessions) =====")
print(f"{'pay':>14} {'1-in-N':>10} {'avg_per_150':>12} {'avg_per_500':>12} {'P(≥1 in 150)':>15} {'P(≥1 in 500)':>15}")
for pid, (fam, _) in PAY_INFO.items():
    p = prof['pay_hits'].get(pid, 0)
    if p > 0:
        n_per_150 = 150 * p
        n_per_500 = 500 * p
        p_at_least_1_150 = 1 - (1 - p) ** 150
        p_at_least_1_500 = 1 - (1 - p) ** 500
        print(f"{fam:>14} {(1/p):>10.0f} {n_per_150:>12.4f} {n_per_500:>12.4f} {p_at_least_1_150:>14.4f} {p_at_least_1_500:>14.4f}")
print()

# 8) g15 (cumulative session bucket < 5x) composition
print("===== 8) g15 (gt0_lt5) composition =====")
# session_bucket from base
session_bucket_base = {k: v * 100 for k, v in prof['bucket_rtp'].items()}
# Add feature
_BUCKET_EDGES = [
    (5000, "ge5000"), (1000, "ge1000_lt5000"), (500, "ge500_lt1000"),
    (200, "ge200_lt500"), (100, "ge100_lt200"), (50, "ge50_lt100"),
    (20, "ge20_lt50"), (10, "ge10_lt20"), (5, "ge5_lt10"),
    (1, "ge1_lt5"), (0, "gt0_lt1"),
]
def to_bucket(r):
    if r <= 0: return None
    for edge, k in _BUCKET_EDGES:
        if r >= edge: return k
    return None
FEAT_BUCKET_EV = defaultdict(float)
for r, p in final_dist.items():
    b = to_bucket(r)
    if b:
        FEAT_BUCKET_EV[b] += r * p
session_bucket = dict(session_bucket_base)
for k, ev in FEAT_BUCKET_EV.items():
    session_bucket[k] = session_bucket.get(k, 0) + trigger * ev * 100

print(f"  Total session bucket sum: {sum(session_bucket.values()):.3f}pp (should ≈ total RTP {total_rtp:.3f})")
print("  All buckets:")
for k in sorted(session_bucket.keys(), key=lambda k: -[e[0] for e in _BUCKET_EDGES if e[1] == k][0]):
    v = session_bucket.get(k, 0)
    print(f"    {k}: {v:>7.3f}pp ({v/total_rtp*100:>6.2f}% of total)")
print()

# g15 composition: which pays land here?
print("g15 / ge1_lt5 composition by pay_id (base game):")
g15_total = 0
for pid, (fam, mult) in PAY_INFO.items():
    p = prof['pay_hits'].get(pid, 0)
    rtp = prof['pay_rtp'].get(pid, 0) * 100
    # Determine which bucket this pay lands in. But pay_id 8 (bar_mixed) has variable mult (2/4/8 with wilds)
    # pay_id 3/5/7 (bar pures) also variable with wilds.
    # We need to check actual win amounts.
    # For purity, use base mult — most of the family's RTP lands in their nominal bucket.
    # cherry1 mult=1 → ge1_lt5
    # bar_mixed base mult=2 → ge1_lt5
    # cherry2 mult=5 → ge5_lt10
    # bar1_pure mult=5 → ge5_lt10
    # bar2_pure mult=10 → ge10_lt20
    # cherry3 mult=15 → ge10_lt20
    # bar3_pure mult=20 → ge20_lt50
    # high7 mult=30 → ge20_lt50
    # wild_pure mult=200 → ge200_lt500
    # (wild-boosted versions land in higher buckets — bar_mixed with 1 wild → 4x, still ge1_lt5)
    # bar_mixed with 2 wilds → 8x → ge5_lt10
    # bar1+1wild → 10x → ge10_lt20
    # bar1+2wilds → 20x → ge20_lt50
    if pid in ('9', '8'):
        # cherry1=1x and bar_mixed nominal=2x land in ge1_lt5
        g15_total += rtp
        print(f"  pay_id {pid} ({fam}, base mult {mult}x): contributes ~{rtp:.4f}pp to g15")
print(f"  Sum g15 from base ≈ {g15_total:.3f}pp (session g15 reads {session_bucket.get('ge1_lt5', 0):.3f}pp)")
print()
print("NOTE: bar_mixed boost via wilds: pay_id 8 base 2x with k wilds = 2*2^k.")
print("  2*2^0=2 (g15), 2*2^1=4 (g15), 2*2^2=8 (g5-10), 2*2^3=16 (g10-20)")
print("  So all 0 or 1-wild bar_mixed wins are in g15. Most weight is here.")
print()

# 9) bar_mixed share of pure-symbol marginal (visual)
print("===== 9) Visual marginal check (per reel) =====")
print(f"{'symbol':>14} {'R1':>8} {'R2':>8} {'R3':>8} {'max':>8}")
for sym in ['blank', '1bar', '2bar', '3bar', 'high7', 'cherry', 'doublediamond', 'topdollar', 'jackpot']:
    r1 = margs[0].get(sym, 0) * 100
    r2 = margs[1].get(sym, 0) * 100
    r3 = margs[2].get(sym, 0) * 100
    m = max(r1, r2, r3)
    print(f"{sym:>14} {r1:>7.3f}% {r2:>7.3f}% {r3:>7.3f}% {m:>7.3f}%")
print()
print("===== 10) Combined bar visual density (bar1+bar2+bar3 per reel) =====")
for ri in range(3):
    bd = (margs[ri].get('1bar', 0) + margs[ri].get('2bar', 0) + margs[ri].get('3bar', 0)) * 100
    print(f"  R{ri+1}: {bd:.3f}% of reel stops are some bar tier")
