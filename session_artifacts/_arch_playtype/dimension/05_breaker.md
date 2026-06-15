# 05_breaker.md — Dimension Framework, Adversarial Real-Machine Attack

**Role:** arch-breaker
**Date:** 2026-06-15
**Target:** `04_dimension_framework.md` (Alternative B — pure st_extract layer)
**Method:** deep-parse cached chunks (`json.loads(roundResult)`), run the REAL
`TriggerPathExtractor` / `parse_chunk_response` / `versioning` against M15/M43/M279/M275,
reconcile against the fwpass goldens. No estimates; every number below is from parsed rounds
or executed code.

Machines attacked: **M275** (st126 2-path, st140), **M15** (st1/14/15), **M43** (st51/st50),
**M279** (st2/st36/st140).

---

## VERDICT: BREAKS-ON-M275 (design self-consistency) + BREAKS-ON-M15/M43/M279 (false inertness premise)

The *recommended mechanism* (Alternative B, layer on st_extract) is structurally sound and
its per-path arithmetic reconciles on real data. But the document contains **three concrete
factual breaks** that invalidate its load-bearing claims as written, plus **two design-logic
gaps** an implementer would ship as bugs. These are not "looks fine" nitpicks — each is a
counterexample proven against the repo or the real chunks.

---

## BREAK 1 (highest risk) — "st_extract key absent for M15/M43/M279" is FALSE; the inertness argument collapses

**The claim (cited verbatim, appears 4×):**
- §3.3: *"the `st_extract` key is absent (by the existing inertness contract), and the fallback path produces BYTE-IDENTICAL output to today."*
- §2 Alt B Pros: *"`st_extract` key absent from their chunks; plugins take the fallback branch."*
- §3.6 Gate 2 reasoning; §3.5.6.

**Ground truth (executed):** A SECOND extractor — `SignatureAuditExtractor`
(`st_extract/signature_audit.py`, `DECLARED_IN_KEY = "signature"`) — is registered and is
declared by **every ST of all 4 manifests**. Running the real parser:

```
get_extractors_for_manifest:
  M15  -> ['signature_audit']
  M43  -> ['signature_audit']
  M279 -> ['signature_audit']
  M275 -> ['signature_audit', 'trigger_path']

parse_chunk_response(M15 chunk_0001, st_extractors=[signature_audit]):
  rec['st_extract'] = {'signature_audit': {...}}   # PRESENT, not absent
```

The document's own Wave-1 input (01_pipeline_map §8) propagated this error
("freespin_dynamics is the ONLY feature that reads st_extract" — false; `structure_drift`
reads `st_extract['signature_audit']` for all 4 machines, see `structure_drift.py:160-170`)
and 01 §9 Q2 even flagged "unclear whether a SignatureAuditExtractor exists." It does, it is
registered, it fires fleet-wide.

**Why it's a break, not a typo:** the design's CODE helper (§5.2 `_get_dim_data` →
`st_extract.get("dimensions")`) is actually safe (it checks the `"dimensions"` sub-key, which
IS absent for M15/M43/M279). But the PROSE that justifies byte-identical output is wrong, and
an implementer who follows the prose and writes the obvious guard
`if "st_extract" in chunk_dict:` will fire the dimension branch for **all three single-path
machines** and break their fwpass goldens. The byte-identical contract survives ONLY if every
plugin guards on the precise `"dimensions"` sub-key AND on `>=2 real values`. The design must
(a) correct the premise, (b) make the sub-key guard a hard, tested contract, (c) state that
`st_extract` is always non-empty fleet-wide.

**Required fix:** restate inertness as "the `dimensions` SUB-key is absent" everywhere;
add Gate 2 as "M15/M43/M279 produce no `by_dim`/`__by_dim__` keys" verified by JSON-diff of
the actual goldens (not by `st_extract` presence).

---

## BREAK 2 — the base_hash anchor `916ed8021606` does not exist in the repo

**The claim (6 occurrences):** §2 Alt B Pros, §3.6, §4 worked examples all state
`base_hash` "remains at / stays at `916ed8021606`."

**Ground truth (executed `compute_base_analyzer_version()`):**
```
ACTUAL current base_hash: c5d2199142c3
Design quotes:            916ed8021606   (matches neither current nor historical)
memory/DIRECTION historical: 85666c4c4407
```

The design's central no-churn promise is anchored to a phantom value. Alt B genuinely does
not touch `_CLOSURE_FILES` (verified — `parser.py`, `report_engine.py`, `st_extract/__init__.py`,
`_base.py` are the closure entries; `trigger_path.py`/`signature_audit.py` are base-EXCLUDED),
so the LOGIC holds. But any acceptance gate written as `assert base_hash == "916ed8021606"`
FAILS on a clean checkout. Per the arch cardinal rule (conclusions anchor to REAL hashes), a
wrong anchor is a break. **Fix:** replace all 6 with `c5d2199142c3` (or, better, "unchanged
from pre-change value" with the gate computing the delta, not pinning a literal).

---

## BREAK 3 — hash-composition worked examples omit the always-present `xt:signature_audit`; EXTRACTOR_ID rename is internally inconsistent

**Ground truth (executed):**
```
extractor_hashes() = {'signature_audit':'6a6f152698f1', 'trigger_path':'add384d03470'}
effective_version xt: entries —
  M15/M43/M279 : ['xt:signature_audit']
  M275         : ['xt:signature_audit', 'xt:trigger_path']
```

Every §4 worked example shows only `xt:dimensions` (or nothing) and never `xt:signature_audit`,
which is present on ALL 4 machines. Two concrete consequences the design leaves unhandled:

1. **Rename inconsistency.** §3.4.1 renames the extractor file to `dimensions.py`; §4 says
   `effective_version(M275)` then includes `"xt:dimensions"`. But §3.4.1 ALSO says
   "continue registering old `trigger_path` EXTRACTOR_ID as an alias" and §3.1.4 keeps the
   `trigger_paths` manifest key. The `xt:` fold uses `EXTRACTOR_ID` (verified
   `versioning.py:396`). If `EXTRACTOR_ID` becomes `"dimensions"`, the legacy
   `freespin_dynamics.py:127` (`_TRIGGER_PATH_EXTRACTOR_ID = "trigger_path"`,
   reads `st_extract.get("trigger_path")`) gets **None** in Phase 1 and the M275 trigger_paths
   panel goes empty — breaking the M275_1 golden the design swears to preserve in Phase 1.
   The design's "keep emitting the `trigger_path` sub-key" mitigation is correct ONLY if the
   class keeps `EXTRACTOR_ID = "trigger_path"` (so the parser stores under `_eid="trigger_path"`),
   which contradicts §4's `xt:dimensions`.

2. **Double-run during the bridge.** If both a legacy `trigger_path` extractor AND a new
   `dimensions` extractor are registered while M275.json declares BOTH `trigger_paths` and
   `dimensions` keys (§3.1.4 bridge), the parser runs both over the same 9,090 ST126 rounds
   and M275 carries `xt:signature_audit` + `xt:trigger_path` + `xt:dimensions`. No data
   corruption (separate `_eid` keys, verified `parser.py:2494`), but the design's isolation
   table and §4 examples never show this 3-extractor fan-out.

**Fix:** pick ONE: either keep `EXTRACTOR_ID = "trigger_path"` and add the `dimensions`
output sub-key under the SAME extractor (no rename, no second registration — cleanest), or
do a hard rename with a Phase-1 freespin_dynamics edit. The "rename + alias + dual manifest
key" middle path as written breaks the Phase-1 golden.

---

## Per-case held proofs (the mechanism, where the design is right)

### CASE 1 (claim 1) — M275 st126 two paths reconcile: HELD

Real `TriggerPathExtractor` over chunk_0001+0002 (89,090 rounds), summed across chunks:

```
ST126 scatter:      round=8290  win=32,685,500  sessions=829
ST126 collect_peak: round= 800  win= 2,846,000  sessions= 80
SUM:                round=9090  win=35,531,500  sessions=909
raw deep-parse:     round=9090  win=35,531,500  sessions=909   ✓ exact
GTT tally: {0:8290, 2:800}, 0 unknown
```

Σ per-path == aggregate on round_count, win_sum, session_count — exact. **HELD.**

### CASE 3 (claim 3) — divergent columns + additive rtp_pp: HELD

```
ST126 aggregate rtp_pp = 44.4144  (= ST126 win 35,531,500 / paid_bet 80,000,000 ×100)
  scatter:      rtp_pp=40.8569  hit_rate(round)=25.08%  mean_win=3942.8
  collect_peak: rtp_pp= 3.5575  hit_rate(round)=24.62%  mean_win=3557.5
  Σ per-dim rtp_pp = 44.4144  == aggregate ✓ (win is path-additive ⇒ rtp_pp is too)
```

Columns are genuinely divergent (40.86 vs 3.56 pp). If config slots diverged the split renders
independently with no aggregate leakage. **HELD** — with the precision caveat in OQ-4 below.

### Double-trigger edge case — HELD (and proven on the real event)

Traced chunk_0001 robot 3 round 4459: ONE ST140 (CC=1000 AND pid-666, win=0) opens TWO
freespin sessions — collect_peak [4460-4469] (GTT=2) then scatter [4470-4479] (GTT=0). Both
share `block_id=4459`. The extractor routes them by GTT into separate `(126,"scatter")` and
`(126,"collect_peak")` keys; the shared block_id lands as `(robot,4459)` in BOTH session sets,
so each path correctly gets +1 session. The discriminator path **never invokes** the
`multi:<A>+<B>` bucket (that only fires in the anchor-walk fallback) — confirmed: 909 sessions
= 829+80, no `multi:` bucket. **HELD.** (Note: the manifest's fallback note about the
double-trigger "binning to the counter path" is moot here because GTT discriminates per-round.)

### CASE 4 (latent multi-path) — HELD: no missed discriminable path

Independent re-probe of the two sequence-path STs the trace flagged:
```
M43 ST51 (from ST1 vs from ST50): fields {SpinType,RTPId,IsLackCreditsSpin} all single-valued,
  no field whose value-SET differs by preceding ST. No in-round discriminator.
M279 ST2 (from ST140 vs from ST36): {SpinType=2,RTPId=1,IsLackCreditsSpin=False} identical
  across both paths. No in-round discriminator.
```
The design's OS-2 ("declare no dimension; inventing fake labels violates mirror-the-rawdata")
is correct. M15 ST14 ExtraRatio is a per-pick multiplier (OS-3) — also correctly excluded.
**HELD.**

### CASE 6 (isolation) — HELD for the extractor, with the BREAK-3 caveat

Editing `trigger_path.py` changes only `xt:trigger_path`; only M275 carries it ⇒
M15/M43/M279 effective_version unchanged. Editing a PER_SPINTYPE plugin changes its
`feature_hash` and re-flags all 4 (all declare PER_SPINTYPE) — matches §3.6. The
free-ST exclusion is real: M275 golden `spin_type_rtp_buckets` = `['ST140_paid']` only, so
ST126 truly doesn't appear there (§3.4.2 correct). **HELD.**

---

## DESIGN-LOGIC GAPS (would ship as bugs)

### GAP A — next_st_counts loses 9.8% of transitions (the most interesting ones)

The proposed `DimensionExtractor` mirrors `trigger_path.py:209`'s early-return
(`if spin_type not in self._st_declarations: return`). The §3.2 `_prev_dim_key` scheme records
the outgoing transition "at the start of each observe_round, if the previous round was a
declared ST." But for ST126→ST140 (892 of 9,090 transitions = 9.8%, the
*freespin-session-ends* transition), the NEXT round is ST140 — undeclared — so its
`observe_round` early-returns BEFORE the `_prev_dim_key` update fires, silently dropping all
892 exit transitions. Verified:
```
126 -> 126: 8182    (captured)
126 -> 140:  892    (DROPPED if early-return precedes the prev-key update)
126 -> END:   16
```
The design calls this "workable but not zero-complexity" yet its own pseudocode places the
update after the guard. **Fix:** move the prev→current transition-recording ABOVE the
`spin_type not in declarations` early-return. Surface, not fatal — but it is a real bug as
specified.

### GAP B (= OQ-4) — the per-dim Σ==aggregate gate is AMBIGUOUS: the ST126 aggregate has TWO values that disagree by 4.53pp

M275 golden, ST126 already exposes two different RTP aggregates:
```
payouts_by_spin_type['ST126_free']  Σ payid rtp_pp = 44.414   (WinCredits/complete view)
freespin_dynamics.trigger_paths     Σ split rtp_pp = 44.414   (scatter 40.857 + cc 3.558)
spin_type_outcomes['ST126_free'].rtp_contribution_pp = 39.883 (payline-only view)
```
The design's Phase-2 gate (§6) says "per-dim `rtp_contribution_pp` values sum to total ST
`rtp_contribution_pp`." But the per-dim columns are built from `payouts_by_spin_type` (basis
44.41) while the ST-aggregate shown in the outcome panel is 39.88. A console reviewer will see
per-dim columns summing to 44.41 next to an ST header reading 39.88 — a visible 4.53pp
inconsistency. The "Σ per-dim == aggregate" gate passes on the payid basis and FAILS on the
outcome basis; the design never says which. **Fix:** the design must pin the per-dim RTP basis
to the SAME accumulator the displayed aggregate uses, per panel, and the gate must name the
basis. Otherwise Phase 2 ships a self-contradicting RTP display for the one machine it targets.

---

## Cross-cutting readers (claim 5) — assessment

- `structure_drift`: reads `st_extract['signature_audit']` (not `trigger_path`/`dimensions`).
  Dimensioning the per-ST metric input does NOT feed structure_drift; its data path is the
  separate `signature_audit` extractor. §3.4.8 "no change" is correct — BUT the design's claim
  that this is because structure_drift "operates at field level" misses that it depends on a
  registered extractor whose existence the design (via 01) denied. OQ-3/OQ-6 are real and the
  signature_audit extractor must be acknowledged as a first-class, fleet-wide st_extract
  producer before Phase 3 adds `freespin_progression.py` (3 registered extractors then).
- `upstream_feature_breakdown` / `bonus_chain_dynamics`: their `[via ...]` split is the coarse
  prev-pid heuristic (841/67) vs GTT truth (829/80) — confirmed in the M275 golden. Replacing
  it with dimension labels (Phase 2/3) is sound; the 829/80 GTT split is the verified-correct
  target (matches the extractor output above). No break in the mechanism; flagged that the
  heuristic and the dimension count WILL disagree by 12/13 sessions and the migration must not
  leave both visible.

---

## Highest-risk break (for the designer)

**BREAK 1 — M15/M43/M279:** the byte-identical guarantee rests on a FALSE premise
(`st_extract` "absent" for single-path machines). It is present fleet-wide
(`{'signature_audit': {...}}`). The contract only holds if every plugin guards on the precise
`"dimensions"` sub-key with `>=2 real values`; an implementer following the document's prose
guard (`if "st_extract" in chunk_dict`) breaks all three single-path goldens. This is the one
that turns "no-regression" into a fleet regression.

---

## Summary table

| Attack | Verdict | Evidence |
|--------|---------|----------|
| 1. M275 st126 Σ per-path == aggregate | HELD | real extractor: 9090/35,531,500/909 exact |
| 1b. double-trigger (1 in 89,090) | HELD | chunk0001 r3 i4459 traced; GTT per-round, no multi-bucket |
| 2. single-path byte-identical | **BREAKS-ON M15/M43/M279** | st_extract NON-empty (signature_audit) fleet-wide |
| 3. differing config / divergent columns | HELD | rtp_pp 40.86/3.56 Σ=44.41=aggregate; columns diverge |
| 4. latent multi-path | HELD | M43 ST51 / M279 ST2 / M15 ST14 — no discriminator |
| 5. cross-cutting reader | HELD (mechanism) | structure_drift via signature_audit; ufb heuristic 841/67 vs 829/80 |
| 6. base_hash + isolation | **BREAKS-ON anchor** | actual c5d2199142c3, design quotes phantom 916ed8021606 |
| GAP A. next_st_counts | bug-as-specified | 892/9090 (9.8%) exit transitions dropped by early-return |
| GAP B. per-dim RTP basis (OQ-4) | bug-as-specified | aggregate 39.88 (outcome) vs 44.41 (payid) — 4.53pp |
