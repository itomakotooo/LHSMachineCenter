# impl-critic — dimension framework Phase 2

**Date:** 2026-06-15
**Branch:** `claude/playtype-rearch`
**Scope (uncommitted working-tree changes):**
  - `fresh_slotlab/analyzer/features/freespin_dynamics.py` (new file, 815 lines + 244-line Phase 2 patch)
  - `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` (Phase B symbol_combo + Phase 2 dim split)
  - `fresh_slotlab/analyzer/features/spin_type_outcomes.py` (new file, 503 lines + 126-line Phase 2 patch)
  - `fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py` (Phase 2 extract/reduce/emit extension)
  - `src/web_console/frontend/app.js` (_stDimGenericDimension + SPINTYPE_DIMENSIONS entry)
  - `src/web_console/frontend/pure.js` (dim* i18n keys)

**Coordinator-verified facts confirmed during read:**
  - base_hash c5d2199142c3 unchanged (TestBaseHashUnchanged in test suite, test_dimension_phase2.py:1133)
  - M15/M43/M43-7/M279 fwpass goldens byte-identical (TestAdditiveGate, runs real reports)
  - M275 golden re-baselined additive (by_dim/__by_dim__ keys only in 3 plugins)
  - GAP-B self-consistency: freespin rtp_concentration.by_dim exposes BOTH named bases
  - 661 tests passed (impl-verifier claim, not independently re-run here)

---

## VERDICT: APPROVE-WITH-FIXES

**Ship-blocker count: 2** (Q3-PREFIX-MISMATCH, Q7-UNKNOWN-SILENT-REEL)
**Required-before-commit count: 2**
**Optional improvements: 4**

---

## 1. ADDITIVITY — Existing key drift (file:line + verdict)

**QUESTION:** Does any existing key inside the 3 plugins' M275 output shift (reorder, retype,
re-value) beyond the additive by_dim/__by_dim__ keys?

**freespin_dynamics.py — NEW FILE, not a patch.** The entire plugin is new; the M275 golden
is re-baselined. The commit claims the F6 `trigger_paths` block (the F6 side-by-side table)
is "PRESERVED as-is." Confirmed: `_trigger_path_section()` reads `st_extract["trigger_path"]`
(unchanged legacy extractor key) and emits the same structure as the old M275 onboarding
commit. The `trigger_paths` output key in `freespin_dynamics` is present, and
`TestRealDataM275.test_trigger_paths_table_still_present_unchanged_shape` asserts it.

**payouts_by_spin_type.py — SCHEMA_VERSION 3→4 (Phase B symbol_combo.combos).** This is an
additive enrichment to an already-bumped field, not a Phase 2 dimension change.
The `__by_dim__` keys are NEW SIBLING keys. The aggregate `ST126_free` list key is a
`list` (verified: `test_aggregate_st_label_unchanged`). The byte-gate strips version metadata
so a combos field change alone would not hide a content change. VERDICT: OK for additivity.

**spin_type_outcomes.py — NEW FILE.** No prior output to regress. The `by_dim` sub-key is
added only when `__by_dim__` sibling exists in payouts AND >=2 real values.
`result[label]` dict structure is unchanged; `by_dim` is conditionally appended.
VERDICT: OK.

**reel_marginal_by_spin_type.py — ADDITIVE sibling key only.** The `reel_marginal_by_spin_type`
dict is written FIRST (unchanged logic), then `__by_dim__` siblings are appended. For M275 only.
VERDICT: OK — unless the >=2 guard in `emit()` has the wrong prefix (see Q3 below).

---

## 2. GUARD (BREAK-1) — precise "dimensions" sub-key guard

**QUESTION:** Is the guard in each plugin the precise "dimensions" sub-key inside
st_extract["trigger_path"], not on st_extract presence?

All four plugins that accumulate dim data guard correctly:

| Plugin | Guard path |
|--------|-----------|
| `payouts_by_spin_type.extract()` line 297-300 | `_st_extract.get("trigger_path").get("dimensions")` |
| `spin_type_outcomes.extract()` line 263-268 | same pattern |
| `reel_marginal_by_spin_type.extract()` line 160-170 | same pattern |
| `freespin_dynamics.extract()` line 298-303 | same pattern + int-guard |

The `freespin_dynamics` int-guard (`if not str(st_key).isdigit(): continue`) from Phase 1
(locked by `TestFreespinIngestionGuard`) is present in the committed `freespin_dynamics.py`.

`TestBreak1Guard` in `test_dimension_phase2.py` directly injects a chunk_dict with
`st_extract = {"signature_audit": ..., "trigger_path": {"1": {}}}` (no "dimensions" sub-key)
and asserts empty `dim_by_st_hits`, `dim_round_count`, and `dim_symbol_counts` for all three
plugins. The inject-bug recipe (IB-2) for `payouts_by_spin_type` is documented.

VERDICT: **OK** — guard is precise and locked by tests.

However: `_tp_raw` is checked for `isinstance(_tp_raw, dict)` BEFORE accessing
`_tp_raw.get("dimensions")`. For M15/M43/M279, `trigger_path` is NOT present in
`st_extract` at all (only `signature_audit` is). So `chunk_dict.get("st_extract").get("trigger_path")`
returns `None`, and `isinstance(None, dict)` is `False` — the guard is safe. CONFIRMED.

---

## 3. PER-PANEL RTP BASIS (GAP-B) — cross-contamination check

**QUESTION:** Is each plugin's per-dim value computed with its OWN aggregate's formula?

**spin_type_outcomes by_dim:** formula is `(_dv_total_win / total_win_stb) * rtp_pp_stb`
(outcome/global-bet denominator). `total_win_stb = float(stb_row.get("total_win"))`.
This is the outcome basis. `_dv_total_win` comes from `sum(r["total_win"] for r in dv_rows)`
where `dv_rows` is from the `__by_dim__` sibling key in payouts (payid basis rows).
Wait — `total_win` in payid rows IS the payid win (credits), so this is consistent. OK.

**payouts_by_spin_type __by_dim__ sibling key:** `rtp_contribution_pp = (dv_win / effective_bet_for_rtp) * 100.0`
where `dv_win = pid_win * _share` and `_share = dim_win_sum_extractor / st_total_win_extractor`.
This is payid basis. Denominator: `effective_bet_for_rtp`. CORRECT for payid panel.

**freespin_dynamics.rtp_concentration.by_dim:** emits BOTH
`rtp_contribution_pp_payid_basis` and `rtp_contribution_pp_outcome_basis`. Frontend
`_stDimFreespin` reads `rtpC = fd.rtp_concentration || {}` and renders the AGGREGATE view
(not by_dim). The `_stDimGenericDimension` reads `outcome.by_dim` (spin_type_outcomes).
So the freespin-specific `rtp_concentration.by_dim` is emitted but NEVER RENDERED
by any frontend function. The coordinator noted "freespin rtp_concentration.by_dim
exposes BOTH named bases" — which is correct in JSON, but the frontend does NOT display it.
VERDICT: The JSON is correct; the rendering gap is cosmetic (not a data error) and the
tests assert the JSON shape. Flagged as non-blocking but see Q5.

**4.53pp gap:** `spin_type_outcomes["ST126_free"].rtp_contribution_pp = 39.88pp` (outcome basis).
`payouts_by_spin_type["ST126_free"] Sigma(rtp_pp) = 44.41pp` (payid basis). The frontend
`_stDimGenericDimension` reads `d.rtp_contribution_pp` from `outcome.by_dim.trigger_path.scatter`
(which has the OUTCOME basis, 40.86pp / 3.56pp). The payid mini-table reads from
`payidByDv[v]` (payid basis). A user seeing side-by-side columns will see:
- `dimRowRtpPp = 40.86pp` (outcome basis, from `spin_type_outcomes.by_dim`)
- payid mini: `Sigma 44.41pp` (payid basis, from `payouts.__by_dim__`)

These two numbers in the same table are from DIFFERENT denominators. There is no label
differentiating the RTP basis from the payid sum. This is the GAP-B user-confusion risk
the breaker identified — it remains unaddressed in the rendered output. VERDICT:
flagged below as Q2-BASIS-LABEL (non-blocking cosmetic risk).

---

## 4. FRONTEND — _stDimGenericDimension analysis

### 4a. N >= 2 real values guard
`realVals = dimValues.filter(v => !v.startsWith("unknown:") && !v.startsWith("multi:"))`.
Then `if (realVals.length < 2) continue`. This correctly excludes unknown/multi from
the column count. For N=1 or absent: `continue` → no HTML for that dim → returns `""`.
For absent by_dim: guard at line 5333 `if (!byDim ...) return ""`. VERDICT: OK.

### 4b. XSS surface
- `headCols = realVals.map(v => <th>${_escHtml(String(v))}</th>)` — dim values are escaped.
- `dimLabel = dimMeta._dim_label || dimName.replace(/_/g, " ")` — then `<h3>${_escHtml(dimLabel)}</h3>` — escaped.
- `_payidMini`: `${_escHtml(String(r.payout_id || ""))} ${(...).toFixed(2)}pp` — payout_id escaped.
- The alarm HTML: `_escHtml("unknown/multi buckets: " + [...].join(", "))` — the list of keys is escaped as a pre-joined string.
VERDICT: **OK** — no unescaped interpolation of server data found.

### 4c. freespin both-bases rendering
The `_stDimGenericDimension` reads `outcome.by_dim` (spin_type_outcomes, outcome basis).
It shows `d.rtp_contribution_pp` = outcome basis. The `_stDimFreespin` is ALSO in
`SPINTYPE_DIMENSIONS` and fires for the same ST126. `_stDimFreespin` reads
`fd.rtp_concentration` (aggregate, not by_dim). So the user sees:
  1. Generic dim panel: scatter 40.86pp / collect_peak 3.56pp (outcome basis)
  2. Freespin mechanic panel: trigger_paths table (from `_trigger_path_section`, payid basis 44.41pp)

The basis difference between panel 1 (outcome) and panel 2 (payid) is not labeled. A user
comparing them will see conflicting numbers. VERDICT: flagged as Q2-BASIS-LABEL (risk,
non-blocking for correctness).

### 4d. Dead i18n keys
`dimByPathTitle`, `dimRowSessions`, `dimRowWinSum` are defined in pure.js (both zh + en)
but NEVER used in app.js. VERDICT: **RISK** — flagged as Q8-DEAD-I18N.

### 4e. _unknown/_multi handling in frontend
The alarm section in `_stDimGenericDimension` (lines 5395-5399) finds `unknown:*` or
`_unknown` keys in `dimMeta` and shows them. For M275, `_unknown = []` and `_multi = []`
are present in the `by_dim` block (alarm-semantics empty lists). The filter
`filter(k => k !== "$meta")` looks for a `$meta` sentinel that does NOT exist in the
output schema — this filter is harmless dead code but could confuse future readers.
VERDICT: minor.

---

## 5. FREESPIN TRIGGER_PATHS vs BY_DIM REDUNDANCY

**QUESTION:** Is there redundant/conflicting per-path info in the same panel?

`freespin_dynamics` output has:
1. `trigger_paths` (F6 block) — per-path session_count, session_share, trigger_rate,
   round_count, win_band_hist. RTP basis: `rtp_contribution_pp_split = win_sum / effective_bet_for_rtp * 100`.
2. `rtp_concentration.by_dim` (Phase 2) — per-dim rtp on BOTH bases, win_sum, session_count.

The F6 `trigger_paths` panel says scatter: 829 sessions, collect_peak: 80 sessions.
`rtp_concentration.by_dim.trigger_path.scatter.session_count` would show 829.
These are CONSISTENT but DUPLICATED. The frontend `_stDimFreespin` renders the F6 block;
`_stDimGenericDimension` renders the outcome.by_dim split from `spin_type_outcomes`.
So the user sees:
- `_stDimFreespin`: F6 trigger paths table (sessions, trigger rate, band hist)
- `_stDimGenericDimension`: spin_type_outcomes by_dim (rounds, hit_rate, rtp_pp, payid mini)

These are complementary, not redundant, and come from DIFFERENT section paths. No direct
duplication on the rendered page. VERDICT: **OK as designed for Phase 2** — the F6 block
is the mechanic view; the generic dim renderer is the per-ST outcome view. The Phase 3
migration plan to unify them is documented.

---

## 6. REDUCE() MERGE — freespin dim_stats across chunks

**QUESTION:** Is dim_stats merged correctly across M275 chunks?

`reduce()` in `freespin_dynamics` (Phase 2 patch, lines 382-435):
- Initializes `merged_ds = dict(prev_ds)` — shallow copy of prev
- For `_k` not in `merged_ds`: `merged_ds[_k] = dict(_v)` then deep-copies
  `bucket_hist = dict(...)` and `next_st_counts = dict(...)` separately.
- For `_k` already in `merged_ds`: additively merges all fields.

**BUG RISK — shallow copy of `bucket_hist` and `next_st_counts` in the not-in-merged_ds branch:**
`merged_ds[_k] = dict(_v)` does a shallow copy of `_v`. Then the code separately does
`merged_ds[_k]["bucket_hist"] = dict(_v.get("bucket_hist") or {})` and
`merged_ds[_k]["next_st_counts"] = dict(_v.get("next_st_counts") or {})`.
This IS correct — the shallow copy is immediately overwritten with deep copies for the
two mutable sub-fields. VERDICT: OK (though the intent is not obvious; a comment clarifying
"re-assign to prevent aliasing" would help).

**CORRECTNESS:** Session_count is summed additively across chunks. The extractor keys sessions
by (robot_idx, block_id) WITHIN a chunk; robots are distinct across chunks (confirmed in
Phase 1 extractor design), so per-chunk session counts are additive. VERDICT: OK.

---

## 7. DROPPED BYTE-IDENTICAL GOLDEN TEST

**QUESTION:** Was dropping TestFwpassGate justified? Is TestAdditiveGate a sufficient lock?

The tester dropped the byte-identical fwpass golden test, citing "stale goldens /
bankruptcy_rate drift." However, the coordinator confirmed all 5 `_fwpass_gate` checks
PASS byte-identical.

`TestAdditiveGate` (test_dimension_phase2.py:1152-1213) runs real reports on M15/M43/M43-7/M279
and asserts NO `__by_dim__` or `by_dim` keys appear in any output. This is a STRONGER test
than a byte-identical golden in one respect: it tests the PROPERTY (no contamination) rather
than pinning a specific output shape, so it won't false-fail on unrelated schema changes
like bankruptcy_rate drift.

HOWEVER: `TestAdditiveGate` does NOT verify that M15/M43/M279 EXISTING keys are unchanged.
If a Phase 2 code path accidentally modifies the aggregate spin_type_outcomes or
payouts_by_spin_type output for these machines (not adding by_dim, but changing existing
values), `TestAdditiveGate` would not catch it.

The fwpass goldens (byte-identical JSON comparison) DO catch that. The tester's claim that
they are "stale" is factually wrong per coordinator. VERDICT: **RISK** — the replacement is
weaker in one dimension. See Q6-FWPASS below.

---

## 8. _UNKNOWN/_MULTI in BY_DIM — reconciliation analysis

**QUESTION:** Are unknown/multi excluded from "real values" count AND from Sigma==aggregate?

**Count guard (consistent):** All plugins check `not str(v).startswith("unknown:")` and
`not str(v).startswith("multi:")` for the >=2 real-values guard. CONSISTENT.

**Sigma==aggregate (payid basis):** In `payouts_by_spin_type.extract()`, the proportional split
denominator is `_ext_total_win = sum(win_sum for ALL _dim_vals including unknown/multi)`.
So `Sigma(_share for all v including unknown/multi) = 1.0`. The `dim_by_st_hits/wins` carries
entries for unknown/multi values too. In `emit()`, these unknown/multi keys get mapped to
`_unknown`/`_multi` output keys. So `Sigma(rtp_pp over ALL keys including _unknown/_multi) ==
aggregate`. But `Sigma(rtp_pp over REAL values only) < aggregate` when unknowns are present.

The GAP-B test (`test_payouts_by_spin_type_sum_equals_aggregate_payid_basis`) sums over ONLY
`alpha` and `beta`, not `_unknown`. So if there are unknown:* rounds, the test would FAIL even
though the code is correct (unknowns carry their share, total adds up). For M275 with 0 unknown
rounds, this is not an issue. For a future machine with unknowns, the test assertion would fail
even for correct code. VERDICT: test scope matches current M275 reality (0 unknowns), but
misrepresents the invariant for the general case. See Q4-UNKNOWN-SIGMA below.

**reel_marginal — SILENT SWALLOW:** In `reel_marginal_by_spin_type.extract()`, unknown/multi
rounds are EXCLUDED from `dim_symbol_counts` (the guard on line 165-169 filters them out).
In `emit()`, the `__by_dim__` sibling key is built only from the collected symbol counts —
no `_unknown`/`_multi` alarm sub-key is emitted. Per `feedback_invariant_with_fallback_hides_drift.md`,
any `_unknown`/`_other`/fallback bucket MUST be an alarm signal, never silently absorbed.
VERDICT: **SHIP-BLOCKER** — see Q7-UNKNOWN-SILENT-REEL.

---

## 10 STRESS QUESTIONS

### Q1 — ADDITIVITY: Are M15/M43/M279 spin_type_outcomes entries truly unchanged?

`TestAdditiveGate` asserts no `by_dim` key present, but does NOT assert that `hit_rate`,
`rtp_contribution_pp`, `win_bands`, or `top_combos` values are byte-identical to the pre-Phase-2
output. `spin_type_outcomes` is a NEW plugin — its output didn't exist before Phase 2. So
for pre-existing plugins (payouts, reel_marginal), the byte-identical question applies.
The fwpass goldens DID include `payouts_by_spin_type` and `reel_marginal_by_spin_type`.
If those goldens pass, then the aggregate payouts and reel_marginal keys are byte-identical.
CONFIRMED by coordinator (byte-identical gate passes). But: SCHEMA_VERSION went from 3→4
in `payouts_by_spin_type`. Does the fallback rule system produce byte-identical output for
old reports served via REGISTERED_FALLBACK_RULES key 3 → add empty `combos: []`? The fwpass
gate tests current generation, not old cached reports. **Risk: medium-low.**

### Q2 — BASIS-LABEL: When user sees `_stDimGenericDimension` scatter 40.86pp and F6 trigger_paths scatter 40.86pp with `rtp_contribution_pp_split`, do the numbers match?

F6 `rtp_contribution_pp_split = win_sum / effective_bet_for_rtp * 100` = payid basis.
`spin_type_outcomes.by_dim.scatter.rtp_contribution_pp` = outcome basis (proportional of 39.88).
The design says scatter outcome rtp = 40.86 * (39.88/44.41) ≈ 36.7pp, not 40.86pp.
So the two panels show 36.7pp (outcome dim) vs 40.86pp (F6 payid). A user comparing them
will see **different numbers for scatter RTP in two adjacent panels**. No label differentiates
the basis. **Risk: user confusion, non-blocking for correctness.** Flagged.

### Q3 — PREFIX-MISMATCH (SHIP-BLOCKER): `reel_marginal_by_spin_type.emit()` real-values guard uses `"_unknown"` prefix but dim_value keys use `"unknown:"` prefix

**File:** `fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py` lines 347-351:
```python
_real_dv = [
    v for v in dv_map
    if not str(v).startswith("_unknown")
    and not str(v).startswith("_multi")
]
```

But in `st_dim_data`, `dv_map` is populated from `dim_symbol_counts` which was extracted in
`extract()` with the guard `if not str(v).startswith("unknown:") and not str(v).startswith("multi:")`.
So unknown/multi keys with the `"unknown:"` prefix are NEVER added to `st_dim_data`.
The guard in `emit()` checks `"_unknown"` (underscore prefix) — a different key format.

**Result 1:** The guard is functionally inert — it never matches any key because the keys
it would need to match were pre-filtered in `extract()`. So the by_dim sibling key is emitted
only for real values. That part is correct.

**Result 2:** Unknown/multi symbol data is silently excluded from the reel_marginal by_dim
output with NO alarm sub-key (unlike `spin_type_outcomes` which explicitly adds `"_unknown": []`).
This violates `feedback_invariant_with_fallback_hides_drift.md`.

**Result 3:** For the specific case of M275 with 0 unknown rounds, this is harmless. For a
future machine with unknown:* rounds, those rounds' symbol distributions are silently absent
from the reel_marginal by_dim output. The test suite does NOT test for alarm presence in
reel_marginal by_dim (it only tests for presence of the sibling key and absence for no-dim machines).

**VERDICT: SHIP-BLOCKER** — silent swallow of unknown rounds in reel_marginal by_dim.
Fix: after building `_sibling_val`, if any `unknown:*` keys were excluded from
`dim_symbol_counts` (or equivalently, if the by_dim alarm list in the corresponding
`spin_type_outcomes` entry has any non-empty `_unknown`), surface a `"_unknown_excluded": True`
or `"_unknown_rounds_excluded": <count>` sub-field in the sibling value. Alternatively,
accumulate unknown symbol counts separately and include them as a flagged `_unknown` sub-key.

### Q4 — UNKNOWN-SIGMA: `TestUnknownMultiHandling.test_by_dim_emitted_despite_unknowns` asserts `_unknown` is in spin_type_outcomes by_dim, but the GAP-B test `test_spin_type_outcomes_by_dim_sum_equals_aggregate_outcome_basis` only sums alpha+beta

If 2 rounds hit `unknown:99`, those 2 rounds' `win_round_count` is counted in `stb_row.win_rounds`
(aggregate), contributing to `rtp_pp_stb`. But the by_dim formula assigns them to `_unknown`:
`_dim_data["_unknown"]["rtp_contribution_pp"] = (unk_total_win / total_win_stb) * rtp_pp_stb`.

The GAP-B test sums ONLY alpha+beta: `dim_sum = sum(dim_block[dv]["rtp_contribution_pp"] for dv in ("alpha", "beta"))`.
This `dim_sum < agg_rtp_pp` when unknowns are non-zero. The test passes with tolerance 0.001
because the synthetic fixture uses FieldX=99 → unknown:99 with win=100 credits (small share).
But the test's description says "Sigma(per-dim rtp_pp) == ST126 aggregate rtp_pp" — which
is FALSE when unknowns exist. **Risk: misleading test invariant description.** Should add:
`dim_sum + unknown_rtp == agg_rtp_pp` as the correct assertion. Non-blocking for M275 (0 unknowns),
but misleading for future machines.

### Q5 — FREESPIN BY_DIM NEVER RENDERED: `freespin_dynamics.rtp_concentration.by_dim` is emitted but no frontend function reads it

The Phase 2 patch to `freespin_dynamics` adds `session_cadence["by_dim"]`,
`hot_board_uplift["by_dim"]`, `fs_dist["by_dim"]`, `payid_mix["by_dim"]`,
`rtp_concentration["by_dim"]`. The `_stDimFreespin` function in `app.js` reads none of these
`by_dim` keys — it reads the aggregate F-section values. The generic `_stDimGenericDimension`
reads `spin_type_outcomes[label].by_dim`, not `freespin_dynamics.rtp_concentration.by_dim`.

The only way a user sees per-dim freespin data is through `_stDimGenericDimension`'s
`spin_type_outcomes` path (round counts, hit_rate, outcome rtp_pp, payid mini).

**Claim-vs-reality gap:** The coordinator claim that "freespin rtp_concentration.by_dim exposes
BOTH named bases" is true in JSON but NOT rendered in the console. The test
`test_freespin_rtp_concentration_both_bases_present` verifies JSON shape, not rendering.
**Risk: the by_dim F-section enrichment in freespin_dynamics is dead code for Phase 2 UI.**
Non-blocking (design says Phase 3 will wire it up), but the 244-line patch is wasted work
until Phase 3 frontend updates.

### Q6 — FWPASS DROPPED: TestFwpassGate was removed; TestAdditiveGate does not check existing key values for M15/M43/M279

If `payouts_by_spin_type.emit()` accidentally changed `total_win` or `rtp_contribution_pp`
for a non-dimension ST (e.g. ST1_paid on M15), `TestAdditiveGate` would not catch it —
it only checks for ABSENCE of `__by_dim__` keys. The Phase 2 emit path for the
`__by_dim__` emission runs `if dim_by_st_hits or dim_by_st_win:` — empty for M15 —
so no risk from that code path. But the new `SCHEMA_VERSION = 4` bump and the Phase B
symbol_combo.combos mutation to `payout_ids_top20` ARE live for M15. The fwpass goldens
that the tester dropped would have caught any unintended change to those fields.
**Risk: medium — the tester's reasoning ("stale goldens") is factually wrong.** The coordinator
confirmed goldens pass byte-identical. Recommendation: re-add the fwpass test as
`TestFwpassGate` against the golden files confirmed by the coordinator.

### Q7 — UNKNOWN-SILENT-REEL (SHIP-BLOCKER): reel_marginal by_dim silently drops unknown:* rounds

Detailed above in Q3. `feedback_invariant_with_fallback_hides_drift.md` explicitly forbids
silent residuals. The `reel_marginal.__by_dim__trigger_path` sibling key for a machine with
unknown rounds would show symbol distributions only for the real values, with no indication
that some rounds are absent. There is no test in `test_dimension_phase2.py` that:
  1. Has rounds mapping to unknown:*
  2. Asserts that `reel_marginal_by_spin_type["__by_dim__trigger_path"]` surfaces an
     alarm key or a count of excluded unknown rounds.

The `TestUnknownMultiHandling` class only tests `spin_type_outcomes` and
`payouts_by_spin_type` for unknown handling — NOT `reel_marginal`.

### Q8 — DEAD I18N: `dimByPathTitle`, `dimRowSessions`, `dimRowWinSum` defined but unused

`pure.js` adds 3 keys in each locale that are never referenced in `app.js`. This violates
`feedback_no_parallel_panel_impl.md` ("No parallel i18n key sets"). They were probably added
for anticipated Phase 3 use but are dead in the Phase 2 diff. No impact on correctness,
but clutters the i18n dictionary.

### Q9 — PROPORTIONAL SPLIT CROSS-CHUNK CORRECTNESS: Is Sigma(per-dim payid rtp_pp) == aggregate exact across 2 chunks?

The per-dim proportional split in `payouts_by_spin_type.extract()` computes `_share` as
`dim_win_sum_from_extractor / st_total_win_from_extractor` using the SAME-CHUNK extractor
data and the SAME-CHUNK payout accumulator. The reduce() sums these.

For the GAP-B payid invariant `Sigma(per-dim payid rtp_pp) == aggregate payid rtp_pp`:
Let `chunk_k` have share `s_k` for dim value `v`, and pid win `p_k`.
Then `dim_pid_win_v_total = Sigma_k(p_k * s_k)`.
The aggregate payid win is `Sigma_k(p_k)`.
The exact invariant `dim_pid_win_v_total = aggregate * (dim_win_total / st_win_total)` holds
ONLY if `s_k` is the SAME across all chunks (constant dim share).
If chunk-1 has 92% scatter share and chunk-2 has 89% scatter share, the aggregated
proportional split will be slightly off from the true aggregate dim split.

For M275 (scatter vs collect_peak), the share is stable (pity meter fires at a fixed
counter threshold regardless of which chunk the robot is in). So the error is negligible.
But the `test_payouts_by_dim_sum_equals_aggregate_payid_basis` tolerance is `< 0.01`.
For a future machine with volatile dim shares, this test could falsely pass with a significant
error. **Risk: low for M275, medium for future machines.** Non-blocking.

### Q10 — STACKING: _stDimFreespin and _stDimGenericDimension BOTH fire for M275 ST126

`SPINTYPE_DIMENSIONS = [..., _stDimFreespin, _stDimGenericDimension]`. For M275 ST126:
- `_stDimFreespin` guards: `if (Number(fd.freespin_spin_type) !== Number(stCtx.row.spin_type)) return ""`. ST126 matches → renders.
- `_stDimGenericDimension` guards: `outcome.by_dim` present with 2 real values → renders.

Both fire. The user sees:
1. `_stDimFreespin` section: session cadence, hot-board uplift, mult dist, payid mix, F6 trigger paths, RTP concentration (all aggregate + F6 path split, payid basis)
2. `_stDimGenericDimension` section: outcome by_dim (outcome basis rtp_pp), payid mini

These provide complementary information but expose both bases without labeling which
denominator each uses. This is the same GAP-B user-confusion risk as Q2. The design
acknowledged this as a Phase 3 item (migrate _stDimFreespin to read from by_dim and
unify the basis). **For Phase 2 as specified, this is acceptable.** Risk: moderate
user confusion on M275; non-blocking.

---

## Summary of findings

### Code-level bugs / risks

- **Q3 / Q7 (SHIP-BLOCKER):** `reel_marginal_by_spin_type.emit()` guard uses `"_unknown"` prefix
  but actual keys use `"unknown:"` prefix. Functionally inert for correctness (unknown rounds
  were pre-filtered in `extract()`), but means unknown symbol data is silently absent from the
  reel_marginal by_dim output with no alarm key — violates `feedback_invariant_with_fallback_hides_drift.md`.
  File: `fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py` lines 315-332 (extract
  filter) and lines 347-351 + no alarm emission in emit().

- **Q9 (medium):** Proportional split across chunks computes per-chunk shares independently
  and sums — exact only when dim share is constant across chunks. For M275 it is stable;
  for future volatile-share machines the invariant drifts. Tolerance in test (0.01) may
  mask the error.

- **Q5 (medium):** `freespin_dynamics.by_dim` F-section enrichment (244 lines, 5 sub-key
  mutations) is emitted to JSON but rendered by no frontend function. Dead-weight for Phase 2.
  The `test_freespin_rtp_concentration_both_bases_present` verifies JSON but not rendering.

### Test-level gaps

- **Q3/Q7:** No test asserts that `reel_marginal_by_spin_type.__by_dim__` surfaces an
  alarm/count when unknown rounds are present. `TestUnknownMultiHandling` covers
  spin_type_outcomes and payouts only.

- **Q4:** `TestTwoValueSt.test_spin_type_outcomes_by_dim_sum_equals_aggregate_outcome_basis`
  sums only real values — the assertion is correct for M275 (0 unknowns) but misrepresents
  the invariant when unknowns are non-zero.

- **Q6 (FWPASS DROPPED):** `TestFwpassGate` was removed. `TestAdditiveGate` does not verify
  that existing key values in M15/M43/M279 payouts/reel_marginal are unchanged — only that
  `__by_dim__` keys are absent.

### Claim-vs-reality gaps

- **Q5:** Coordinator claim "freespin rtp_concentration.by_dim exposes BOTH named bases" is
  true in JSON; false in rendered console (no frontend function reads it).

- **Q6:** Tester claim that fwpass goldens are "stale" is factually wrong per coordinator
  (all 5 byte-identical). The removal was not justified.

- **Q8:** 3 i18n keys (`dimByPathTitle`, `dimRowSessions`, `dimRowWinSum`) defined in pure.js
  but referenced nowhere in app.js. Claimed as "reusing existing i18n discipline" but these
  are net-new dead keys.

- **Q2:** The `dimRowRtpPp` row shows outcome-basis RTP (36.7pp for scatter) while the F6
  trigger paths panel shows payid-basis RTP (40.86pp for scatter). Both are labeled "RTP"
  with no basis qualifier in the console.

### Memory feedback violations

- `feedback_invariant_with_fallback_hides_drift.md`: `reel_marginal_by_spin_type` silently
  excludes unknown:* rounds from `__by_dim__` without an alarm sub-key. **1 violation.** File:
  `fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py`.

---

## Verdict: APPROVE-WITH-FIXES

### Required fixes before commit/merge (2)

1. **Q3/Q7 — reel_marginal_by_spin_type: surface alarm for unknown:* excluded rounds.**
   In `extract()`, accumulate unknown/multi round counts separately
   (e.g. `dim_unknown_counts[(st_str, dim_name)] = int`). In `emit()`, after building
   `_sibling_val`, if any unknown/multi rounds were excluded, add a
   `"_unknown_excluded_count": N` sub-key to `_sibling_val` at the top level, AND add a
   test in `TestUnknownMultiHandling` that asserts its presence. This brings reel_marginal
   into parity with spin_type_outcomes' explicit `"_unknown": []` alarm semantics.

2. **Q6 — Re-add byte-identical gate for M15/M43/M279 existing payouts/reel_marginal output.**
   Either restore `TestFwpassGate` pointing at the coordinator-confirmed byte-identical goldens,
   OR add a targeted `TestExistingKeyValues` class that runs M15 and asserts that
   `payouts_by_spin_type["ST1_paid"]` row values are byte-identical to a known fixture.
   Rationale: `TestAdditiveGate` proves no `by_dim` contamination but not value-level stability.

### Optional improvements (4)

1. **Q2/Q10 — Basis label in `_stDimGenericDimension`:** Add a sub-label "(outcome basis)"
   below the `dimRowRtpPp` row in the table, or add a `drilldown-hint` beneath the table
   noting "RTP column uses global-bet (outcome) basis; payouts panel uses effective-bet (payid) basis."

2. **Q4 — Fix GAP-B test assertion:** `test_spin_type_outcomes_by_dim_sum_equals_aggregate_outcome_basis`
   should assert `dim_sum + unk_rtp == agg_rtp_pp` (where `unk_rtp` is the `_unknown` dim
   value's rtp_contribution_pp), not just `dim_sum == agg_rtp_pp`. This makes the invariant
   description accurate for future machines with unknowns.

3. **Q8 — Remove dead i18n keys:** Remove `dimByPathTitle`, `dimRowSessions`, `dimRowWinSum`
   from pure.js (both locales) until they are actually used. Alternatively, annotate them
   with `// RESERVED Phase 3` if intentional.

4. **Q5 — Remove or defer freespin by_dim F-section mutations:** The `_build_dim_by_sections()`
   call and the 5 F-section `by_dim` assignments in `emit()` are dead weight for Phase 2
   UI. Either defer to Phase 3 (when `_stDimFreespin` is updated to read them) or at minimum
   add a comment noting they are JSON-only for Phase 2 and not rendered.
