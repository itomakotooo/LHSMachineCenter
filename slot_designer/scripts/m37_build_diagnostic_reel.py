"""Build a diagnostic test reel for M37.

Goal: distinguish between sampling hypotheses by giving ONE position per
reel a weight 1000x larger than other non-blank stops.

If real machine samples per cfg weight, that one symbol will dominate
(43% mid marginal). If Buffalo does anything else (uniform per stop, per
symbol type, outcome-driven), the marginal will be 4-10% range.

Layout (each reel 26 stops, blank/non-blank alternating):
  R1 = R3 (matches prod convention):
    13 blanks @ pos 0,2,...,24, each w=100
    pos 1=1bar(w=1), 3=2bar(1), 5=3bar(1), 7=7bar(1), 9=high7(1)
    pos 11=1bar(w=1000)  ← HEAVY DIAGNOSTIC SYMBOL
    pos 13=2bar(1), 15=3bar(1), 17=7bar(1), 19=high7(1)
    pos 21=wild(1), 23=wild(1), 25=wild(1)
  R2:
    13 blanks @ pos 0,2,...,24, each w=100
    pos 1=1bar(1), 3=2bar(1), 5=3bar(1), 7=7bar(1), 9=high7(1)
    pos 11=mini(w=1000)  ← HEAVY DIAGNOSTIC SYMBOL
    pos 13=minor(1), 15=major(1), 17=grand(1), 19=7bar(1)
    pos 21=high7(1), 23=3bar(1), 25=2bar(1)

Total weight per reel: 13×100 + 1000 + 12×1 = 2312

Cfg-natural marginals (hypothesis A "weighted-stop landing"):
  R1: blank 56.23%, 1bar 43.30%, 2bar/3bar/7bar/high7 0.087% each, wild 0.13%
  R2: blank 56.23%, mini 43.30%, 1bar/minor/major/grand 0.043% each,
      2bar/3bar/7bar/high7 0.087% each

Modify only skin 1 (mode 1). Skins 2/5/7 left at prod values so other
modes still work (test only mode 1).
"""
import openpyxl
from pathlib import Path

XLSX_PATH = Path(r'C:\Users\pangg\Documents\Projects\LHS\MachineBuilder\Buffalo\Assets\Config\Excel\Machine\M37\M37Reel.xlsx')

# 26 stops, alternating blank / non-blank
def build_reel(non_blank_pattern):
    """non_blank_pattern: list of 13 (sym, weight) for odd positions 1,3,...,25.
    Returns 26-stop strip with blank at even positions (w=100)."""
    rows = []
    for i in range(13):
        # Even pos: blank
        rows.append(('blank', 100))
        # Odd pos: from pattern
        rows.append(non_blank_pattern[i])
    return rows  # 26 entries

# R1 = R3: 5 regular types × 2 stops + 3 wilds. Heavy 1bar at pos 11.
R1_pattern = [
    ('1bar', 1),     # pos 1
    ('2bar', 1),     # pos 3
    ('3bar', 1),     # pos 5
    ('7bar', 1),     # pos 7
    ('high7', 1),    # pos 9
    ('1bar', 1000),  # pos 11 ← HEAVY
    ('2bar', 1),     # pos 13
    ('3bar', 1),     # pos 15
    ('7bar', 1),     # pos 17
    ('high7', 1),    # pos 19
    ('wild', 1),     # pos 21
    ('wild', 1),     # pos 23
    ('wild', 1),     # pos 25
]

# R2: 5 regulars × 2 stops + 4 boosters. Heavy mini at pos 11.
R2_pattern = [
    ('1bar', 1),     # pos 1
    ('2bar', 1),     # pos 3
    ('3bar', 1),     # pos 5
    ('7bar', 1),     # pos 7
    ('high7', 1),    # pos 9
    ('mini', 1000),  # pos 11 ← HEAVY
    ('minor', 1),    # pos 13
    ('major', 1),    # pos 15
    ('grand', 1),    # pos 17
    ('7bar', 1),     # pos 19
    ('high7', 1),    # pos 21
    ('3bar', 1),     # pos 23
    ('2bar', 1),     # pos 25
]

R3_pattern = R1_pattern  # Match prod convention R1==R3

R1 = build_reel(R1_pattern)
R2 = build_reel(R2_pattern)
R3 = build_reel(R3_pattern)

# Verify totals
print(f'Layout sanity check:')
print(f'  R1 total w = {sum(w for _, w in R1)} (expect 2312)')
print(f'  R2 total w = {sum(w for _, w in R2)} (expect 2312)')
print(f'  R3 total w = {sum(w for _, w in R3)} (expect 2312)')

# Compute cfg-natural marginals
from collections import Counter
def marg(reel):
    total = sum(w for _, w in reel)
    counts = Counter()
    for sym, w in reel:
        counts[sym] += w
    return {s: c/total for s, c in counts.items()}

print(f'\\nCfg-natural marginals (hypothesis A):')
for label, reel in [('R1', R1), ('R2', R2), ('R3', R3)]:
    print(f'  {label}:')
    for s, p in sorted(marg(reel).items(), key=lambda x: -x[1]):
        print(f'    {s:<8}: {p*100:>7.3f}%')

# Write to xlsx skin 1
wb = openpyxl.load_workbook(XLSX_PATH)
ws = wb['Sheet1']

# skin 1 is rows 2-27 (1-indexed)
# col 1=skinId, 2=R1sym, 3=R1w, 4=R2sym, 5=R2w, 6=R3sym, 7=R3w
for i in range(26):
    row = 2 + i
    ws.cell(row, 1).value = 1
    ws.cell(row, 2).value = R1[i][0]
    ws.cell(row, 3).value = R1[i][1]
    ws.cell(row, 4).value = R2[i][0]
    ws.cell(row, 5).value = R2[i][1]
    ws.cell(row, 6).value = R3[i][0]
    ws.cell(row, 7).value = R3[i][1]

wb.save(XLSX_PATH)
print(f'\\n✓ saved diagnostic reel to skin 1 of: {XLSX_PATH}')
print(f'\\nNext steps:')
print(f'  1. Run buildkit to generate cfg')
print(f'  2. User runs cfg on real Buffalo, pulls mode 1 rawdata')
print(f'  3. Check observed R1 1bar mid + R2 mini mid marginal')
print(f'     43% → cfg weighted (my engine right)')
print(f'     8% → uniform per type')
print(f'     7.7% (R1) / 3.85% (R2) → uniform per stop')
print(f'     other → outcome-driven / unknown')
