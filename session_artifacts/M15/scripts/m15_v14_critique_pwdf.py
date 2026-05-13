"""X v14 audit: PWDF mech B reproduction + R1 vs R3 archetype check."""
import sys, json
sys.stdout.reconfigure(encoding='utf-8')
from collections import defaultdict
from pathlib import Path

ROOT = Path(r'C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT')
sys.path.insert(0, str(ROOT))

from slot_designer.core.devtools.player_experience import symbol_window_probability

M15 = ROOT / 'slot_designer' / 'machines' / 'M15'
STRIPS = M15 / 'reel_strips.json'
strips_doc = json.loads(STRIPS.read_text(encoding='utf-8'))
strips = strips_doc['reels']

print("===== Strip layout (M15 v8.1, 36-stop alternating) =====")
print(f"R1 length: {len(strips[0])}")
print(f"R2 length: {len(strips[1])}")
print(f"R3 length: {len(strips[2])}")
print()

# Symbol counts per reel
for ri in range(3):
    counts = defaultdict(int)
    for s in strips[ri]:
        counts[s] += 1
    print(f"R{ri+1} symbol counts:")
    for s, c in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {s}: {c} stops ({c/len(strips[ri])*100:.2f}%)")
    print()


# C38 marginals
def make_marginals(R1, R2, R3):
    out = []
    for R in (R1, R2, R3):
        R = dict(R)
        non_blank = sum(R.values())
        R["blank"] = max(0.001, 1.0 - non_blank)
        s = sum(R.values())
        out.append({k: v / s for k, v in R.items() if v > 0})
    return out


R1 = {"cherry": 0.040, "1bar": 0.202, "2bar": 0.165, "3bar": 0.103,
      "high7": 0.072, "doublediamond": 0.029, "jackpot": 0.004}
R2 = {"cherry": 0.035, "1bar": 0.165, "2bar": 0.135, "3bar": 0.073,
      "high7": 0.057, "doublediamond": 0.028, "jackpot": 0.004}
R3 = {"cherry": 0.025, "1bar": 0.135, "2bar": 0.110, "3bar": 0.055,
      "high7": 0.047, "doublediamond": 0.024, "jackpot": 0.003,
      "topdollar": 0.0113}
margs = make_marginals(R1, R2, R3)


def marginals_to_weights(strips, margs, scale=10000):
    counts_per_reel = []
    for reel in strips:
        c = defaultdict(int)
        for s in reel:
            c[s] += 1
        counts_per_reel.append(dict(c))
    out = []
    for ri, reel in enumerate(strips):
        target = margs[ri]
        counts = counts_per_reel[ri]
        wps = {}
        for sym, frac in target.items():
            cnt = counts.get(sym, 0)
            if cnt == 0:
                continue
            w = scale * frac / cnt
            wps[sym] = max(1, int(round(w)))
        row = [wps.get(s, 1) for s in reel]
        out.append(row)
    return out


def apply_mechanism_b_blanks(strips, weights, top_symbols=("doublediamond", "high7", "topdollar"), floor=1):
    out = [list(r) for r in weights]
    top = set(top_symbols)
    for ri, reel in enumerate(strips):
        n = len(reel)
        total_blank = sum(out[ri][i] for i in range(n) if reel[i] == "blank")
        top_adj, non_top_adj = [], []
        for i in range(n):
            if reel[i] != "blank":
                continue
            if reel[(i - 1) % n] in top or reel[(i + 1) % n] in top:
                top_adj.append(i)
            else:
                non_top_adj.append(i)
        if not top_adj:
            continue
        reserve = floor * len(non_top_adj)
        leftover = total_blank - reserve
        if leftover <= 0:
            continue
        per = leftover // len(top_adj)
        rem = leftover - per * len(top_adj)
        for i in non_top_adj:
            out[ri][i] = floor
        for k, i in enumerate(top_adj):
            out[ri][i] = per + (1 if k < rem else 0)
    return out


weights_raw = marginals_to_weights(strips, margs)
weights_mb = apply_mechanism_b_blanks(strips, weights_raw)

print("===== PWDF after mechanism B =====")
print(f"{'symbol':>14} {'R1':>8} {'R2':>8} {'R3':>8} {'MAX':>8}")
for sym in ['doublediamond', 'high7', 'topdollar']:
    row = []
    for ri in range(3):
        strip_dicts = [{"symbol": s, "weight": w}
                       for s, w in zip(strips[ri], weights_mb[ri])]
        pw = symbol_window_probability(strip_dicts, sym)
        row.append(pw * 100)
    print(f"{sym:>14} {row[0]:>7.3f}% {row[1]:>7.3f}% {row[2]:>7.3f}% {max(row):>7.3f}%")
print()

# What if we tried alternative top_symbols sets?
print("===== Alternative mechanism B configurations =====")
for alt_top in [
    ("doublediamond", "high7"),  # drop topdollar
    ("doublediamond",),  # only dd
    ("doublediamond", "high7", "topdollar", "jackpot"),  # add jackpot
]:
    w_alt = apply_mechanism_b_blanks(strips, weights_raw, top_symbols=alt_top)
    pwdfs = {}
    for sym in ['doublediamond', 'high7', 'topdollar']:
        row = []
        for ri in range(3):
            strip_dicts = [{"symbol": s, "weight": w}
                           for s, w in zip(strips[ri], w_alt[ri])]
            pw = symbol_window_probability(strip_dicts, sym)
            row.append(pw * 100)
        pwdfs[sym] = (row, max(row))
    print(f"  top_symbols={alt_top}: dd_max={pwdfs['doublediamond'][1]:.3f}%  h7_max={pwdfs['high7'][1]:.3f}%  td_max={pwdfs['topdollar'][1]:.3f}%")
print()

# Check strip dd stop positions and adjacency
print("===== Strip dd stop position analysis =====")
for ri in range(3):
    n = len(strips[ri])
    dd_pos = [i for i, s in enumerate(strips[ri]) if s == 'doublediamond']
    print(f"R{ri+1}: dd at positions {dd_pos} (n_stops={len(dd_pos)} of {n})")
    for p in dd_pos:
        prev_s = strips[ri][(p-1) % n]
        next_s = strips[ri][(p+1) % n]
        # 3-row window when reel stops on this dd: showing prev_s, dd, next_s
        # If reel stops on (p-1): window shows prev_s_prev, prev_s, dd
        # If reel stops on (p+1): window shows dd, next_s, next_s_next
        # So dd is visible from stops (p-1), p, (p+1)
        print(f"  pos {p}: prev={prev_s}  next={next_s}  (window includes dd when reel stops at {p-1}, {p}, or {p+1})")
print()
