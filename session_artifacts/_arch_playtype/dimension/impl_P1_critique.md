# impl-critic — dimension framework Phase 1 (data substrate)

> Recorded by the coordinator from the impl-critic run (2026-06-15; the agent returned
> findings inline but died before persisting this file). Verdict: **APPROVE-WITH-FIXES** —
> the two required fixes landed before commit; locked by Group I regression tests.

Phase 1 scope: extend the (kept-name) `trigger_path` extractor to emit a new `dimensions`
output sub-key carrying the FULL per-(ST, dim, value) metric set; GAP-A transition fix
(record prev→current ABOVE the declared-ST early-return). Data-substrate only — no plugin
consumes `dimensions` yet. Verified: base_hash c5d2199142c3 unchanged, all 5 fwpass goldens
byte-identical, M275 reconciles (9090 / 35,531,500 / 829 / 80), 126→140 = 892, suite green.

## Required fixes (both landed)

1. **Q1/Q10 — `dimensions` sibling key pollutes `freespin_dynamics`.** The extractor stores
   its whole `finalize_chunk` return under `st_extract["trigger_path"]`, so that dict now
   has both numeric ST keys AND a `"dimensions"` sibling. `freespin_dynamics.extract()`
   iterates those keys and ingested `"dimensions"` as a fake ST into its accumulator (inert
   at emit today — emit reads only `["126"]` — but a Phase-2 foot-gun and a silent-swallow
   smell). **FIX (landed):** one-line int-guard `if not str(st_key).isdigit(): continue` in
   `freespin_dynamics.extract()`. Locked by `TestFreespinIngestionGuard` (inject-bug: remove
   guard → RED, restore → GREEN — coordinator-verified).

2. **Q2 — `finalize_chunk` docstring mismatch.** Docstring described the output as having a
   `"trigger_path"` sub-key; actually the backward-compat flat data is at the TOP LEVEL of
   the returned dict and `"dimensions"` is a SIBLING of the numeric ST keys. **FIX (landed):**
   docstring corrected to the real shape + a note that the clean top-level `dimensions`
   EXTRACTOR_ID rename is deferred to Phase 2 (when freespin_dynamics migrates off the legacy
   flat key), so the int-guard is a known transitional guard.

## Held (mechanism correct)

GAP-A lifecycle (begin_robot resets prev-key; first/last round; undeclared→undeclared; cross-chunk
reset) — OK. sum==aggregate with unknown/multi included — OK. multi-trigger: round counted once,
session +1 to each path (Σ round_count == total; Σ session_count ≥ distinct blocks per policy) — OK.
State-reset contract honored.

## Phase-2 hazards — DOCUMENTED in code, not fixed now (by design)

- **next_st_counts keys**: int in memory, become str after JSON round-trip — Phase-2 consumers
  reading from stored report JSON must use str keys.
- **symbol_counts extraction is O(D×C)** per (st,dim,value) in finalize_chunk — fine for M275,
  flag for a future high-cardinality discriminator (unbounded unknown buckets).
- **Naming collision**: dim_name "trigger_path" == EXTRACTOR_ID → access path repeats
  "trigger_path"; resolved by the Phase-2 rename.

## Deferred to Phase 2 (not Phase-1 blockers)
Clean top-level `st_extract["dimensions"]` location + EXTRACTOR_ID rename (safe once
freespin_dynamics no longer reads the legacy flat key); plugin consumption of the substrate.
