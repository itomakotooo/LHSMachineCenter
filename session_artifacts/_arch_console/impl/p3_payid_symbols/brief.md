# payid symbol-combination + covered-columns — analyzer enrichment (Phase 1: data)

> Coordinator brief, impl-* team. Branch `claude/playtype-rearch`. User directive (2026-06-03): the payid
> analysis (总览 payout_ids_top20 + 按-SpinType payouts_by_spin_type) must parse each payid down to its
> **specific symbol combination + covered columns**, from the LIVE rawdata, with a **single cross-machine
> parser** (the format is uniform — verified). This phase = the ANALYZER DATA. Frontend display = Phase 2.

## What already exists (REUSE — do not rebuild)
- `round_classification.attribute_lines_to_pay_ids(r)` already parses `PayoutByPayline` → records with
  `pay_id`, `line_id`, `positions` (the raw nodes e.g. 100,200,299), `match_count`. (existing helper, fleet-wide)
- `parser.py` ~1942-1962 already aggregates per-pid from those records: `payout_id_payline_hits`,
  `payout_id_match_count_dist`, `payout_id_col_set` (covered columns), `payout_id_has_regular_line`.
  Column decode in use: `col0idx = (pos + 1)//100 - 1` (0-indexed).
- `features/payouts_by_spin_type.py` (SCHEMA_VERSION 2) consumes those via chunk_dict keys
  (`payout_id_col_set` etc.) and emits per-(pid,ST) rows with `covered_columns` / `shape` / `paylines` / `notes`.
- The overview `payout_ids_top20` is built in PIA (`player_impact_analyzer.py` ~3991) — rows: `payout_id,
  hit_count, hit_rate, total_win, avg_win_when_hit, rtp_contribution_pp`. It currently gets "symbol shape" only
  from a SEPARATE offline endpoint `/api/paytables/.../shape` (frontend fetch), NOT from the live data.

## The gap (the ONLY new thing)
The live enrichment captures covered COLUMNS + n-of-a-kind, but NOT the actual SYMBOL NAMES. The user wants the
**specific symbol combination** (e.g. "cherry-cherry-wild") parsed from the live data, in BOTH views, uniformly.

## The decode (VERIFIED across M14/M1/M275/M279/M268/M274 — cross-machine + cross-SpinType uniform)
For each record from `attribute_lines_to_pay_ids(r)`, for each `pos` in `record["positions"]`:
- `col_1indexed = (pos + 1)//100`  (so col0idx = col_1indexed - 1 — matches the existing col_set decode)
- `row = pos - col_1indexed*100 + 1`  (offset 0→row1 center, +1→row2, -1 i.e. ...99→row0)
- `symbol = StopSymbolsByCol[col0idx].split("-")[row]`  (StopSymbolsByCol[c] = "s0-s1-s2-")
Examples proven: M14 `5:7-7(101,200,299)` → cherry/cherry/wild(35x_wild); M1 `1:11-11(100,200,300)` → Bar2/Bar1/Bar1;
M275 `4:7-7(99,200,301)` → wild/wild/1bar.
Edge cases the parser MUST handle (verified present in fleet):
- **empty positions `()`** (e.g. M120 ST=138 `-1000:10-10()`): scatter/feature pay, no covered cells → symbol
  combo = none / "(scatter)"; covered columns = none.
- **special line_id** `-1` / `-1000`: trigger/scatter lines (already handled for col_set; keep consistent).
- a position whose decoded row/col is out of range for StopSymbolsByCol → skip that cell (don't crash); if
  StopSymbolsByCol absent on the round → no symbols (some STs have none).
- **DO NOT assume 3 rows fleet-wide.** Derive row-count from `len(StopSymbolsByCol[col].split("-"))` and center
  = (rowcount-1)//2 if the offset interpretation needs it; for the sampled 3-row fleet center=1. If a machine's
  grid breaks the decode, FAIL LOUD / record nothing for it (per user: "新机台碰到问题再看") — do NOT silently mis-map.

## Deliverables (analyzer data only)
1. **parser.py**: in the existing C3 block (~1942), ALSO capture the symbol per decoded cell (reuse the same
   `attribute_lines_to_pay_ids` records — no second parse). Aggregate a new per-pid accumulator, e.g.
   `payout_id_symbol_combos[pid_str][combo_tuple] += 1` where combo is the column-ordered symbol tuple (wilds
   kept as-is). Thread it into the chunk return dict (like `payout_id_col_set`). This is UNIVERSAL parsing
   (format fleet-uniform) so it belongs in the base — base_hash flips once (re-pin, documented).
2. **features/payouts_by_spin_type.py**: consume the new chunk key; add a per-(pid,ST) `symbol_combo` field
   (the dominant / representative combo + maybe the distinct symbol set). Bump SCHEMA_VERSION 2→3 + add a
   REGISTERED_FALLBACK_RULE for the new field (v2→v3). (Editing this feature is isolated — base-excluded.)
3. **payout_ids_top20 (PIA overview)**: add `symbol_combo` + `covered_columns` per payid (aggregate across STs).
   Source from the SAME live enrichment (not the offline shape API) so it's consistent + cross-machine.
4. Keep RTP/parity invariants intact (`sum(pay_id.rtp_pp)==summary.rtp` must still hold — this is display-only enrichment).

## Gates (impl-tester + impl-verifier)
1. **Symbol decode correctness** (the core): independently deep-parse cached rounds for M14, M1, M275, M120, M268
   and assert the captured `symbol_combo` for representative payids matches the StopSymbolsByCol cells at the
   decoded positions (e.g. M14 payid 7 → cherry combos; M1 payid 11 → bar combos). Dump actuals. Cross-machine.
2. **byte-identical** for all EXISTING fields (covered_columns/match_count/hits/RTP unchanged); the ONLY additions
   are the new symbol_combo fields. base_hash re-pin (parser edit) with documented reason.
3. **RTP integrity**: `sum(pay_id.rtp_pp)==summary.rtp` still GREEN; no double-count.
4. **edge cases**: empty positions `()` → combo=none (no crash); special line_id; missing StopSymbolsByCol.
5. inject-bug: corrupt the row decode → symbol_combo wrong → revert.
6. e2e subprocess on M14 + M15 + M275: report builds, symbol_combo populated for reel-spin STs, absent for
   ST=14/15 (no PayoutByPayline).

## Out of scope (Phase 2)
Frontend rendering (renderPayoutsBySpinType per-ST columns + renderPayIdOverview overview columns) — next phase.

## Memory feedback
- `feedback_no_hardcode` — symbol/decode logic is generic (no per-machine symbol names hardcoded).
- `feedback_respect_existing_codebase` — REUSE attribute_lines_to_pay_ids + the C3 accumulator pattern; minimal delta.
- `feedback_invariant_with_fallback_hides_drift` — no new `_unattributed` bucket; keep RTP parity.
- Surgical commit; closure edit → re-pin base_hash with documented reason.
