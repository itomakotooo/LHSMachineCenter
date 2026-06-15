# Dimension Framework Design
## `session_artifacts/_arch_playtype/dimension/04_dimension_framework.md`

**Role:** arch-designer
**Date:** 2026-06-15
**Branch:** `claude/playtype-rearch`
**Ground truth:** 01_pipeline_map.md (pipeline map), 02_path_traces.md (rawdata traces),
03_coupling.md (blast-radius audit)

---

## 1. Problem Statement

The analyzer's per-ST analysis layer produces one merged view per SpinType regardless
of HOW a SpinType was triggered. M275 ST126 (NewFreespin) is opened by two genuinely
distinct trigger paths — scatter (pid-666) and collect_peak (CollectCount==1000) —
confirmed by `GameplayTriggerType` field discrimination on 9,090 freespin rounds
(trace: 02_path_traces.md §M275 ST126, 8,290 scatter / 800 collect_peak). Today,
those two paths share identical config slot values (02_path_traces.md §Outcome
comparison, Z=1.07 not significant), so the merge is harmless. If the slots diverge,
every ST126 metric — hit rate, avg-win, session cadence, ER ladder, skin distribution,
multiplier histogram, payid mix — would describe an average of two different games.

The design task: make the per-ST analysis layer DIMENSION-AWARE, so each declared
trigger path produces its own metric slice, generically and declaratively for any ST
on any machine.

### 5 concrete pain points (cited from Wave 1)

**P1 — partial path split with full metric blindspot (01 §3F, 03 §4c fragility
rank 9):** `freespin_dynamics` splits only 4 stats per path (round_count, win_sum,
session_count, win_band_hist). The remaining dozen metrics — hot-board uplift, payid
mix, multiplier distribution, ER ladder, FS arc, session tier distributions — remain
ST-aggregate. If the paths' config slots diverge, these metrics lie by averaging
(01_pipeline_map.md §7 "What is NOT path-split today").

**P2 — generic per-ST plugins are path-blind (01 §3A, 03 §2d):** The four
`PER_SPINTYPE` analyses (`payouts_by_spin_type`, `spin_type_outcomes`,
`spin_type_rtp_buckets`, `reel_marginal_by_spin_type`) aggregate across all rounds of
a ST regardless of dimension. Their accumulators are keyed by `(pid_str, st_int)` or
`str(st_int)` — never `(st_int, dim_label)`. Extending them requires each one to read
the per-path data, currently sitting only in `chunk_dict["st_extract"]["trigger_path"]`
and accessible to `freespin_dynamics` only (01_pipeline_map.md §8 "freespin_dynamics is
the ONLY feature that reads st_extract from the chunk dict").

**P3 — parser accumulators are the highest-cost change surface (03 §3a, Case 3):**
Adding a `(st, path_label)` keyed accumulator to `parser.py` flips `base_hash` for
all 4 registered machines and stales every cached report. The `st_extract` extraction
layer was built precisely to avoid this (03_coupling.md §8 "Path A vs Path B").

**P4 — role/play mechanic plugins can't read per-path data (01 §3C-3E, 03 §2e
Case 5):** `respin_dynamics`, `minigame_dynamics`, `wheel_dynamics` read only
ST-keyed accumulators from the chunk dict. If any of their STs ever have two trigger
paths (e.g. a future machine's respin ST opened by scatter vs win-gate), those plugins
have no mechanism to produce per-path metric slices. Making them do so currently
requires editing each plugin file, which re-flags all machines declaring that plugin
(e.g. editing `respin_dynamics.py` re-flags both M43 and M279 — 03 §5 Case 5).

**P5 — long-deferred parser-blind metrics have no home (01 §9 Q1, M275.json
caveats):** FS-index arc, ER ladder progression, per-path session tiers are
"parser_blind" — the information is in per-round fields but no per-round accumulator
captures it. Building them requires per-round extraction, which the `st_extract` hook
provides; but the hook only calls the single `TriggerPathExtractor` today. A generic
dimension-aware extractor that accumulates richer per-round stats per (ST, dim) would
produce these for free, with no parser.py changes.

---

## 2. Design Alternatives

### Key design decision: where does the (ST, dim) fork live?

The core question is: does per-dimension metric accumulation happen INSIDE the parser
(changing `_CLOSURE_FILES`), or OUTSIDE (using the already-built `st_extract` hook)?

---

### Alternative A — Subsume: extend parser ST-keyed accumulators to (ST, dim) keys

**Sketch:** Add new accumulators in `parser.py`:

```
spin_type_dim_bucket_spins[(st, dim_label)][bucket] += 1
spin_type_dim_win[(st, dim_label)] += win
spin_type_dim_paid_rounds[(st, dim_label)] += 1
...
```

During the per-round loop, resolve the dim label (via the manifest's trigger_paths
discriminator, consulted in-line) and update both the existing ST-only key and the
new (ST, dim) key. The report_engine merges the new dict the same way as existing
ST-keyed dicts.

**Pros:**
- Single accumulation pass; no separate per-round extractor callback.
- All per-ST plugins can read `(ST, dim)` directly from `chunk_dict`, no
  architectural change to the extract/reduce/emit lifecycle.
- `spin_type_bucket_win[(st, dim_label)]` would be the natural input to a
  dimension-split version of `spin_type_rtp_buckets`.

**Cons:**
- `parser.py` is in `_CLOSURE_FILES` (03_coupling.md §3a). ANY edit flips `base_hash`
  for all 4 machines and stales ALL cached reports. This is the highest-cost change
  in the system (03_coupling.md §6 rank 2).
- `report_engine.py` merge loops also in `_CLOSURE_FILES` — the new accumulators
  add ~10 new merge loops, each a closure change.
- The "one-time re-baseline" cost is real but also masks: if the accumulator shape
  changes again later (a second round of dimension work), it stales everything AGAIN.
  The closure is a global liability that compounds.
- Machines without trigger_paths (M15, M43, M279) would still compute dim-keyed
  accumulators with a single implicit dim "default", adding memory and serialization
  overhead for zero benefit on 3 of 4 current machines.
- Counter to DIRECTION.md §4 (the isolation method): the `st_extract` layer was built
  specifically to avoid parser.py changes for per-round work.

**Migration cost:** High. One mandatory re-baseline of `base_hash` + all 5 fwpass
goldens. Full suite must pass with new key shapes.

---

### Alternative B — Layer on top: extend the existing `st_extract` extractor to accumulate the FULL per-ST metric set per (ST, dim), plugins read from chunk_dict["st_extract"]

**Sketch:** The `TriggerPathExtractor` (or a companion) in `st_extract/` accumulates,
per `(ST, dim_label)`, the full set of metrics that currently come from the parser's
ST-keyed accumulators for that ST's rounds:

```
# Inside observe_round() in a DimensionExtractor (base-excluded):
# All triggered for rounds matching declared STs only.

dim_round_count[(st, label)] += 1
dim_win_sum[(st, label)] += win_amt
dim_bucket_spins[(st, label)][return_bucket(win/bet)] += 1
dim_paid_rounds[(st, label)] += 1 if is_paid else 0
dim_win_rounds[(st, label)] += 1 if win > 0 else 0
dim_next_counts[(st, label)][next_st] += 1   # requires look-ahead or sequence walk
dim_symbol_counts[(st, label)][col][sym] += 1
```

`finalize_chunk()` returns all these keyed by `{st_str: {dim_label: {all_stats}}}`.

Each mechanic plugin (PER_SPINTYPE + role/play) gains a conditional branch: if
`chunk_dict["st_extract"]["dimensions"]` is present for this ST, it uses the
per-dim breakdown; otherwise falls back to the existing ST-keyed accumulators. For
machines without trigger_paths declared, the `st_extract` key is absent (by the
existing inertness contract), and the fallback path produces BYTE-IDENTICAL output
to today.

**Pros:**
- `parser.py` and `report_engine.py` are UNTOUCHED. `base_hash` stays at `916ed8021606`.
  No re-baseline. The 5 fwpass goldens for M15/M43/M43-7/M279 remain byte-identical
  (those machines declare no trigger_paths; `st_extract` key absent from their chunks;
  plugins take the fallback branch; output unchanged). (03_coupling.md §8 "Path A".)
- Extractor modules are base-excluded. Editing the dimension extractor re-flags only
  machines declaring `trigger_paths` — currently M275 only.
- The existing `TriggerPathExtractor` already accumulates 4 stats per (ST, dim).
  This extends it to the full metric set. No new framework files, no new closure changes.
- `observe_round()` already receives `round_ctx` including `bet`, `win`, `last_paid_round`,
  `block_id` — all needed for the extended metrics.
- The long-deferred parser-blind metrics (FS arc, ER ladder) fall out naturally: a
  `FreespinProgressionExtractor` can accumulate per-round ER/FS-index per (ST, dim)
  in the same hook, same per-machine isolation.
- Each plugin's fallback path preserves byte-identical behavior for single-dim machines
  — the invariant is testable mechanically.

**Cons:**
- Some per-round state is hard to accumulate in the extractor hook without look-ahead.
  Specifically: `spin_type_next_counts[(st, dim)][next_st]` requires knowing the NEXT
  round's ST when processing THIS round. The existing parser does this because it holds
  all rounds in memory per robot. The extractor only sees one round at a time.
  Mitigation: emit "last ST seen per dim" state across observe_round calls within a
  robot (begin_robot resets it). The extractor can track `_prev_st` and `_prev_dim`
  to compute the outgoing transition on the NEXT call. This is a stateful extractor
  pattern, workable but not zero-complexity.
- Plugin code becomes bifurcated: each plugin has an "ST-keyed (no dim)" branch and an
  "(ST, dim)-keyed" branch. The logic duplication is manageable with shared helper
  functions but requires discipline in each plugin.
- The accumulated stats in the extractor and the parser's ST-keyed accumulators must
  stay in agreement: `sum over dim of dim_round_count[(st, dim)]` must equal
  `spin_type_spins[st]` for all STs with declared trigger_paths. This is a new
  internal invariant that must be verified (value-agnostic: covered by the per-path
  sum == aggregate gate in §7).

**Migration cost:** Medium. No closure changes. Each PER_SPINTYPE plugin and each
mechanic plugin needs a new conditional branch. The extractor module grows. All changes
are base-excluded.

---

### Alternative C — Hybrid: extend the extractor for derived stats only; parser gains ONE new (ST, dim) accumulator for bucket spins/win

A middle path: keep `spin_type_bucket_spins` and `spin_type_bucket_win` in the parser
but add a parallel `spin_type_dim_bucket_spins[(st, dim_label)][bucket]` and
`spin_type_dim_bucket_win[(st, dim_label)][bucket]` accumulator, accepting ONE
`base_hash` flip. The extractor handles round_count, win_sum, session_count,
win_band_hist (already there), next_counts (via prev-ST tracking), and symbol_counts.
The parser handles the bucket histograms in dim-keyed form.

**Pros:**
- The bucket histogram is the most data-intensive accumulation (11 return buckets
  per ST per round). Having it in the parser avoids O(n_rounds) per-dim overhead
  in the extractor for the general case.
- Cleaner separation: raw statistical distributions in the parser; sequencing/session
  context in the extractor.

**Cons:**
- Still flips `base_hash` (the parser change is inescapable for the bucket part).
- Partial bifurcation: some metrics come from the extractor, some from the parser;
  plugin code must read from two sources and merge them. More coupling than Alternative B.
- The benefit over B is marginal: `return_bucket()` is O(1) per round; adding it to
  the extractor for declared-ST rounds only is negligible overhead given 9,090 freespin
  rounds per 89,090 total (10.2%).

**Migration cost:** Medium-high. One closure change (base_hash flip) + extractor +
plugin bifurcation.

---

### Recommended Design: Alternative B (pure extraction layer)

**Reason:** 03_coupling.md §8 makes the case directly: "the extraction layer was designed
precisely to avoid parser.py changes for per-round accumulation." The cost of a
`base_hash` flip is real — ALL 4 machines re-flag, ALL existing reports become
historical — and is not justified when Alternative B achieves the same result without
touching the closure. The fwpass goldens for M15/M43/M43-7/M279 remaining byte-identical
is a hard contractual requirement (03_coupling.md §7c); Alternative B satisfies it by
design.

The look-ahead problem for `next_counts` is solvable with a stateful extractor that
carries `_prev_st` and `_prev_dim_label` across `observe_round` calls within a robot.
The per-round overhead for declared-ST rounds is near-zero at current data volume.

The remainder of this document specifies Alternative B.

---

## 3. Recommended Design

### 3.1 Declaration — Generalizing `trigger_paths` into `dimensions`

**Current state (M275.json):** The manifest's `spin_types["126"]["trigger_paths"]` block is
the sole declaration point. It is specific to the freespin role (consumed only by
`freespin_dynamics` and `TriggerPathExtractor`).

**Generalization:** Rename the manifest block from `trigger_paths` to `dimensions` (or
keep `trigger_paths` as an alias; see migration §6). The concept generalizes: a
"dimension" is an optional per-ST declaration that describes how rounds of that ST
should be split into named groups (dimension-values / path-labels). The split logic
is declarative (no per-machine code). Undeclared STs, or STs with a single effective
dimension-value, produce behavior byte-identical to today.

**Generalized manifest schema (per ST):**

```json
"spin_types": {
  "126": {
    "role": "freespin",
    "play": "NewFreespin",
    "dimensions": {
      "trigger_path": {
        "label": "Trigger Path",
        "discriminator": {
          "kind": "round_field",
          "field": "GameplayTriggerType",
          "map": {"0": "scatter", "2": "collect_peak"},
          "unmapped_value_policy": "surface_as_unknown"
        },
        "fallback": {"kind": "trigger_anchor_walk"},
        "values": {
          "scatter": {
            "opened_by": {"payout_id": "666"},
            "label": "scatter (3 bonus symbols)"
          },
          "collect_peak": {
            "opened_by": {"counter": "CollectCount", "at_peak": 1000},
            "label": "collect-peak (pity timer)"
          }
        },
        "unknown_value_policy": "surface_as_alarm",
        "multi_trigger_policy": "additive_sessions"
      }
    }
  }
}
```

**Key schema decisions:**

1. **`dimensions` is a dict keyed by dimension-name** (e.g. `"trigger_path"`), not a
   single flat block. This allows future STs to declare multiple orthogonal dimensions
   (e.g. `"trigger_path"` AND `"stake_tier"`). For Phase 1, only single-dimension STs
   are built. Multi-dimension is out of scope (see §8).

2. **Undeclared ST = one implicit dimension-value `"_all"`**. All plugins see the same
   data shape; the single-value case collapses to today's ST-only view and emits
   byte-identical JSON.

3. **`values` replaces `paths`** (rename for generic applicability — "value" is a
   dimension-value, "path" was freespin-specific language). The semantics are identical.

4. **Backward compatibility bridge:** The existing `trigger_paths` key in M275.json
   continues to be recognized during migration (Phase 1). The extractor reads `dimensions`
   first, falls back to `trigger_paths` for shape-equivalence. After all plugins are
   migrated (Phase 2), the old key is dropped from manifests.

5. **`DECLARED_IN_KEY` in the extractor** changes from `"trigger_paths"` to
   `"dimensions"` once all manifests have been migrated. During Phase 1, the extractor
   recognizes BOTH keys.

---

### 3.2 Data / Extraction Model

**Decision: Layer on top (Alternative B) — the extractor accumulates the FULL per-ST
metric set per (ST, dim-value), while the parser's ST-keyed accumulators remain unchanged.**

**The central fork:** In `observe_round()`, when `spin_type` matches a declared ST,
BOTH the parser's ST-keyed accumulators AND the extractor's `(ST, dim)` keyed
accumulators are updated (the former by the existing parser code, the latter by the
extractor hook which fires after the parser's per-round code). This means for each
declared-ST round, we do two accounting passes — one ST-level (existing, mandatory for
non-dimensional plugins), one `(ST, dim)` level (new, additive). The sum invariant
`sum over all dim-values of dim_round_count[(st, dim)] == spin_type_spins[st]` holds
by construction (every round maps to exactly one dim-value, or to `"unknown:..."` which
is included in the sum).

**Extractor output shape (per finalize_chunk):**

```
chunk_dict["st_extract"]["dimensions"] = {
  "<st_int>": {
    "<dim_name>": {            # e.g. "trigger_path"
      "<dim_value>": {         # e.g. "scatter", "collect_peak"
        "round_count": int,
        "win_sum": float,
        "paid_round_count": int,
        "win_round_count": int,
        "bet_sum": float,
        "bucket_hist": {"0x": int, "0.5x": int, "1x": int, ...},   # return_bucket
        "session_count": int,
        "symbol_counts": {col_int: {sym: count}},   # per col, per symbol
        "next_st_counts": {next_st_int: int}         # outgoing transitions
      }
    }
  }
}
```

For rounds that map to `"unknown:..."` (no discriminator match), all stats go to a
`"unknown:<value>"` bucket (alarm semantics, surfaced in summary, never merged into
a real dimension-value). The `"multi:<A>+<B>"` bucket handles double-trigger per
the existing additive_sessions policy (02_path_traces.md §Double-trigger edge case:
1 event in 89,090 rounds).

**Note on `next_st_counts` accumulation:** The extractor carries per-robot state
`_prev_st_and_dim` — a `(st, dim_value)` tuple from the previous round. At the start
of each `observe_round()`, if the previous round was a declared ST, we update
`dim_next_st_counts[prev_key][current_st] += 1`. At `begin_robot()`, `_prev_st_and_dim`
is reset to None. This is a well-defined stateful pattern (no look-ahead required).

**Note on `symbol_counts`:** Symbol counts per column per (ST, dim) allow
`reel_marginal_by_spin_type` to produce per-dimension reel distribution tables.
The parser already accumulates `symbol_counts_by_col_by_spin_type[(st, col, sym)]`;
the extractor adds `(st, dim, col, sym)` keying at near-zero overhead for declared-ST
rounds only.

**Parser-blind metrics now covered:** The per-round extractor is the right place for
ER ladder progression (ExtraRatio field per round per dim), FS-index arc
(spin-count-within-session per dim), per-session tier (session win total per dim).
These are accumulated in a companion `FreespinProgressionExtractor` (base-excluded,
same hook, DECLARED_IN_KEY = `"dimensions"` on `freespin` role STs). This is a Phase 2
item (see §6 migration).

**Aggregate == sum invariant (value-agnostic gate):**
For every declared ST, for every metric M in {round_count, win_sum, session_count}:

```
sum(dim_data[st][dim][v][M] for v in all_dim_values_including_unknown) == parser_st_acc[st][M]
```

This is verified by a value-agnostic test (synthetic fixture with known dim split,
verify sum == total — see §7).

---

### 3.3 Summary Schema

**Principle:** The JSON schema for per-ST sections is backward-compatible by being
ADDITIVE. When a ST has no declared dimensions (or a single effective dimension-value),
the existing key structure is byte-identical to today. When a ST has N >= 2
dimension-values, each per-ST analysis key gains an additional `"by_dim"` sub-key
containing the per-dimension breakdown. The top-level key remains the ST-aggregate view
(computed from the unchanged parser ST-keyed accumulators) — this ensures any consumer
that ignores `"by_dim"` continues to work.

**Single-dimension (no trigger_paths declared) — BYTE-IDENTICAL to today:**

```json
"spin_type_outcomes": {
  "ST1_paid": {
    "spin_type": 1,
    "label": "ST1_paid",
    "hit_rate": 0.123,
    "avg_win_when_hit": 4321.0,
    "rtp_contribution_pp": 44.82,
    ...
  }
}
```

No `"by_dim"` key present. Frontend `_stDimWinDistribution` reads this and renders as today.

**Two-dimension ST (M275 ST126 with scatter / collect_peak):**

```json
"spin_type_outcomes": {
  "ST126_free": {
    "spin_type": 126,
    "label": "ST126_free",
    "hit_rate": 0.953,
    "avg_win_when_hit": 4000.0,
    "rtp_contribution_pp": 44.41,
    "by_dim": {
      "trigger_path": {
        "_dim_label": "Trigger Path",
        "_dim_values": ["scatter", "collect_peak"],
        "scatter": {
          "hit_rate": 0.953,
          "avg_win_when_hit": 4100.0,
          "rtp_contribution_pp": 40.86,
          "round_count": 8290,
          "win_sum": 32685500,
          "session_count": 829,
          "dead_spin_rate": 0.047,
          "bucket_hist": {...},
          "top_combos": [...],
          "max_mult": 1200,
          "symbol_dist": {"col_0": {...}, "col_1": {...}}
        },
        "collect_peak": {
          "hit_rate": 0.950,
          ...
          "rtp_contribution_pp": 3.56,
          "round_count": 800,
          "session_count": 80
        },
        "_unknown": [],
        "_multi": []
      }
    }
  }
}
```

**Same pattern applies to ALL per-ST output keys:**

```json
"payouts_by_spin_type": {
  "ST126_free": [
    {"payout_id": "...", "hit_count": ..., "rtp_contribution_pp": ..., ...},
    ...
  ],
  "ST126_free__by_dim__trigger_path": {
    "scatter": [{"payout_id": "...", ...}, ...],
    "collect_peak": [{"payout_id": "...", ...}, ...]
  }
}
```

Alternatively: the `"by_dim"` sub-key is nested inside the existing per-label dict
(as shown in `spin_type_outcomes` above). For list-valued keys like
`payouts_by_spin_type`, a separate key with a `__by_dim__` suffix avoids breaking
the existing list-schema expectation at the top level. The choice is:

- **Option 3.3a (nested `by_dim` inside the label dict):** Works for dict-valued
  per-ST keys. For list-valued keys, wraps the list under an `"aggregate"` key and
  adds `"by_dim"` alongside. Breaking change to the list shape for declaring machines.
- **Option 3.3b (separate sibling key with suffix):** The original list key is
  unchanged; a sibling key `"<label>__by_dim__<dim_name>"` carries the per-dim rows.
  Frontend can read both. Zero breaking change.

**Recommended: Option 3.3b (sibling key with suffix)** for list-valued keys.
For dict-valued keys (spin_type_outcomes, spin_type_rtp_buckets, reel_marginal),
the `"by_dim"` sub-key inside the per-label dict is cleaner.

**Degenerate single-value assertion:** If a declared dimension has exactly one
effective dimension-value (all rounds map to it, no unknowns), the `"by_dim"` key
is OMITTED. This covers the case where a machine declares a dimension in its manifest
but all observed rounds fall in one value — the output is byte-identical to the
no-dimension case.

**M275 ST126 — concrete `freespin_dynamics.trigger_paths` migration:**

The existing `freespin_dynamics` output block:
```json
"freespin_dynamics": {
  "trigger_paths": {
    "available": true,
    "paths": [{"path": "scatter", "session_count": 829, ...}, ...],
    ...
  },
  ...
}
```
is PRESERVED as-is in Phase 1 (the fwpass golden for M275_1 remains the acceptance
target). In Phase 2, this block migrates to reading from `spin_type_outcomes.ST126_free.by_dim.trigger_path`,
and the `trigger_paths` key inside `freespin_dynamics` becomes a reference pointer.

---

### 3.4 Per-Plugin Refactor Plan

**Migration priority rule:** Phase 1 (extractor expansion) → Phase 2 (generic per-ST plugins)
→ Phase 3 (mechanic plugins). Each phase is gated.

#### 3.4.1 Core extractor (`st_extract/trigger_path.py` → `st_extract/dimensions.py`)

**Action:** Rename / extend `TriggerPathExtractor` to `DimensionExtractor`.

The new extractor accumulates the full metric set per `(ST, dim, value)`:
`round_count`, `win_sum`, `paid_round_count`, `win_round_count`, `bet_sum`,
`bucket_hist` (return_bucket via existing `_utils.return_bucket`), `session_count`
(via block_id), `symbol_counts` (from `round_dict["StopSymbolsByCol"]` when present),
`next_st_counts` (via `_prev_dim_key` carried across calls in the robot walk).

The existing `trigger_path` output key is kept as a sub-key (for backward compat
with `freespin_dynamics.extract()` which reads `chunk_dict["st_extract"]["trigger_path"]`).

```
chunk_dict["st_extract"] = {
  "trigger_path": {...},   # BACKWARD COMPAT: existing 4-stat per-path output
  "dimensions": {...}      # NEW: full per-dim metric set
}
```

During Phase 1, both keys are emitted. In Phase 2, `freespin_dynamics` migrates to
reading from `"dimensions"` and the `"trigger_path"` key is deprecated.

**Isolation:** `st_extract/dimensions.py` is base-excluded. Editing it changes
only effective_version for machines declaring `"dimensions"` in their manifest.
Currently: M275 only.

**DECLARED_IN_KEY:** `"dimensions"` (new) AND `"trigger_paths"` (legacy alias).

**Migration order:** First in Phase 1 — all other work depends on this.

#### 3.4.2 Generic per-ST plugins — PER_SPINTYPE group

All four are base-excluded (`features/*.py`). Each gains a conditional branch in
`extract()` and `emit()`.

**`payouts_by_spin_type`:**
- In `extract()`: if `chunk_dict["st_extract"]["dimensions"][st_str][dim_name]` is
  present, also accumulate per `(pid_str, st_int, dim_value)`.
- In `emit()`: if `by_dim` data exists for a ST label, emit sibling key
  `"<label>__by_dim__<dim_name>"` → dict of `{dim_value: [payid_rows]}`.
- Fallback: no `"dimensions"` key → emit exactly as today (byte-identical).
- Isolation: all 4 machines re-flag (payouts_by_spin_type is declared by all),
  but the fallback path guarantees byte-identical output for M15/M43/M279.
  Golden for those 3 machines MUST remain byte-identical — this is testable.

**`spin_type_outcomes`:**
- Reads from `payouts_by_spin_type` and `spin_type_breakdown`. The `by_dim` extension
  reads from `payouts_by_spin_type.<label>__by_dim__<dim_name>` per dim-value, and
  from the extractor's per-dim `hit_rate` / `dead_spin_rate` (from `round_count` and
  `win_round_count`).
- Emits nested `by_dim` sub-key inside each ST label dict in `spin_type_outcomes`.
- Fallback: byte-identical.

**`spin_type_rtp_buckets`:**
- Currently skips free STs (paid_rounds == 0) — M275 ST126 does not appear here.
  No change needed for M275 Phase 1. FUTURE: if a declared-dimension paid ST exists,
  the per-dim bucket histogram from the extractor's `bucket_hist` feeds this plugin.
- Fallback: byte-identical (M15/M43/M279 unaffected).

**`reel_marginal_by_spin_type`:**
- The `_reel_marginal_by_spin_type_data` stash feeds from
  `symbol_counts_by_col_by_spin_type_total` (parser ST-keyed). The extractor
  now also carries `symbol_counts` per `(ST, dim, col)`.
- In `emit()`: if extractor dim data is present for a ST label, emit sibling
  `"<label>__by_dim__<dim_name>"` → `{dim_value: {col: [symbol_rows]}}`.
- Fallback: byte-identical.

**Migration order:** payouts_by_spin_type first (dependency of spin_type_outcomes),
then spin_type_outcomes, then spin_type_rtp_buckets (may be no-op for Phase 1),
then reel_marginal_by_spin_type.

#### 3.4.3 Role plugin: `freespin_dynamics`

This is the only plugin that already reads `st_extract["trigger_path"]`.

**Phase 1:** No change to `freespin_dynamics.py`. The plugin continues to read the
`"trigger_path"` sub-key from `st_extract` (which remains emitted by the extended
extractor for backward compat). The fwpass golden for M275_1 stays the acceptance
target.

**Phase 2:** Migrate `freespin_dynamics` to read from `st_extract["dimensions"]`
instead of `st_extract["trigger_path"]`. The `trigger_paths` output block inside
`freespin_dynamics` migrates: `session_cadence`, `hot_board_uplift`,
`freespin_multiplier_distribution`, `payid_mix`, `rtp_concentration` now each carry
a `by_dim` sub-key populated from the extractor's per-dim data. The old monolithic
F6 `trigger_paths` table in the output is replaced by per-dimension slices of EVERY
F-section.

**At Phase 2 completion, EVERY freespin metric is per-dim:**
- `session_cadence.by_dim.trigger_path.scatter.openers = 829`
- `hot_board_uplift.by_dim.trigger_path.scatter.hit_rate = 0.953`
- `freespin_multiplier_distribution.by_dim.trigger_path.collect_peak.bands = {...}`
- `payid_mix.by_dim.trigger_path.scatter.freespin_payid_share = {...}`

The aggregate (ST-level) values remain at the top level for machines that
only care about the total picture.

#### 3.4.4 Role plugin: `respin_dynamics`

**Current state:** Reads only ST-keyed accumulators (`spin_type_next_counts`,
`spin_type_bucket_{spins,win}`). M43 ST50 (WinRespin) and M279 ST36 (MoveSpin)
are confirmed single-path (02_path_traces.md §M43 ST50, §M279 ST36 — both 1 path,
no discriminating field).

**Action Phase 1:** No change. `respin_dynamics.py` is unchanged; it does not read
`st_extract`. M43 and M279 effective_version unchanged.

**Action Phase 2+:** If a future machine declares a respin ST with `"dimensions"`,
`respin_dynamics` gains the same conditional branch: reads per-dim data from
extractor, emits `by_dim` sub-keys. Only then does the plugin file change, re-flagging
M43 and M279 (the currently registered respin machines) — expected and acceptable.
**IMPORTANT:** M279 re-flagging when M43 gains a dimension is the shared-plugin cost
documented in 03_coupling.md §5 Case 5. The fwpass golden for M279_1 must remain
byte-identical (the fallback branch ensures this).

#### 3.4.5 Play plugin: `minigame_dynamics` (M43 ST51)

**Current state:** M43 ST51 has TWO sequence-level paths (ST1->ST51 and ST50->ST51)
with NO in-round discriminating field and STATISTICALLY IDENTICAL outcomes
(02_path_traces.md §M43 ST51, Z=0.27). This is NOT a configurable dimension split —
there is no config slot divergence possible. (02_path_traces.md: "M43 ST51 has two
sequence-level paths that the rawdata cannot distinguish via any per-round field.")

**Action:** No `"dimensions"` block is declared for M43 ST51. `minigame_dynamics`
is unchanged. No path-split analysis is needed or possible.

#### 3.4.6 Play plugin: `wheel_dynamics` (M279 ST2)

**Current state:** M279 ST2 has two sequence-level paths (direct and via ST36) with
NO in-round discriminating field and statistically identical outcomes
(02_path_traces.md §M279 ST2, Z not significant, same WheelId=1).

**Action:** No `"dimensions"` block is declared for M279 ST2. `wheel_dynamics` is
unchanged.

#### 3.4.7 Role plugin: `topdollar_choice` (M15 ST14)

**Current state:** M15 ST14 is confirmed single-path (02_path_traces.md §M15 ST14 —
"ExtraRatio is a per-event property of individual ST14 rounds, not an entry path").
ExtraRatio (1x/2x/4x) is a per-round multiplier within a session, not a
session-level dimension.

**Action:** No `"dimensions"` block is declared for M15 ST14. `topdollar_choice`
is unchanged.

**UNVERIFIED-NEEDS-TRACE:** Whether ExtraRatio assignment can be predicted by any
trigger-round feature (e.g. DoubleDiamond stop count). 02_path_traces.md notes
"the engine-internal rule for assigning ER to each pick is unobservable in rawdata"
— this closes the question for now.

#### 3.4.8 Cross-cutting plugins

**`upstream_feature_breakdown`:**
Currently uses the coarse `chain_chunk_summaries` mechanism to produce sub_streams
(03_coupling.md §2e, "sub_streams split uses the chain_chunk_summaries coarse
mechanism"). For M275, this gives `[via NormalCollectionSpin]` vs `[via NewFreespin]`
with 841/67 counts vs GTT truth 829/80 (01_pipeline_map.md §3G caveat).

In Phase 2: `upstream_feature_breakdown` gains a new path — when `st_extract["dimensions"]`
is present for the feature's ST, use the accurate dimension counts from the extractor
instead of the coarse heuristic. The `sub_streams` labels are replaced with the
dimension-value labels.

**No base_hash change:** `upstream_feature_breakdown` is base-excluded.
Re-flags all 4 machines (it is declared by all). The fallback path (no dimensions
declared) is byte-identical for M15/M43/M279.

**`bonus_chain_dynamics`:**
Reads from stash `_bonus_chain_dynamics_data` which contains `chain_chunk_summaries`
keyed by `(first_st, entry_cc_reset, sp_type_within_chain)`. This is a different
indexing than the declarative dimension system. Phase 3 item: align the chain split
with dimension labels when available. No change in Phase 1.

**`collect_mechanic`:**
Operates at the cycle/CCState level, not per-ST per-dim. No change required.

**`structure_drift`:**
Reads `chunk_dict["st_extract"]["signature_audit"]` per 01_pipeline_map.md §3G.
The dimension system does not affect structural field auditing. No change required.
(Note: 01_pipeline_map.md §9 Q2 flags that the `signature_audit` data path has
an unresolved question — this is an open question for Wave 3, not a blocker here.)

---

### 3.5 Frontend Model

**Principle from 03_coupling.md §2f and feedback_no_parallel_panel_impl.md:**
Any new per-dim card MUST reuse existing sibling renderers, formatters, and i18n keys.
The `_stDim*` function pattern is the established model. Adding a new dimension
function to `SPINTYPE_DIMENSIONS` fires it for every ST on every machine — each
function guards on data presence and returns `""` when absent.

#### 3.5.1 Generic dimension renderer protocol

Each per-ST analysis card gains a dimension-aware variant renderer. The pattern:

```
function _stDimXxx(stCtx) {
  const data = stCtx.summary.player_impact["xxx"][stCtx.label];
  if (!data) return "";

  const byDim = data.by_dim;   // may be undefined (no dimensions declared)
  if (!byDim) {
    // Single-dim path: render as today — byte-identical appearance
    return _renderXxxCard(data, stCtx);
  }

  // Multi-dim path: for each dimension, render a column set
  const dimName = Object.keys(byDim)[0];  // first (only) dimension in Phase 1
  const dimMeta = byDim[dimName];
  const dimValues = dimMeta._dim_values || [];

  if (dimValues.length <= 1) {
    return _renderXxxCard(data, stCtx);   // degenerate: act as single-dim
  }

  // Side-by-side or toggle layout with one column per dim-value
  return _renderXxxDimCard(data, dimMeta, dimValues, stCtx);
}
```

`_renderXxxCard` is the EXISTING single-dim renderer (unchanged). `_renderXxxDimCard`
is a new wrapper that renders N columns. N=1 MUST produce visually identical output
to `_renderXxxCard`.

#### 3.5.2 Display layout for N dimensions

**N=2 (M275 ST126 scatter / collect_peak):** Side-by-side table with one column per
dimension-value, identical to the existing `_stDimFreespin` F6 trigger_paths table
(`app.js:5216-5291`). This table already exists and is the reference implementation.

**N>2 (future):** Toggle/tab layout. Out of scope for Phase 1.

**N=1 (undeclared or degenerate):** Single column — render identically to today.

#### 3.5.3 i18n approach

Follow the existing `SPINTYPE_DIMENSIONS` i18n discipline:
- Per-ST analysis keys: `sto*` prefix (already used for `_stDimOverview`, `_stDimWinDistribution`,
  `_stDimPayid`).
- Dimension-specific labels: add `dim_<name>_<value>` keys in `pure.js`, OR use the
  manifest's `values.<v>.label` string directly from the summary JSON (avoiding
  i18n key proliferation). The `label` field in each dimension-value declaration is
  the display string.
- **No parallel i18n key sets** (feedback_no_parallel_panel_impl.md): reuse all
  existing `sto*` / `fs*` / `rd*` keys for the metric values; only add new keys for
  the dimension header labels themselves.

#### 3.5.4 `_stDimFreespin` migration path

The existing `_stDimFreespin` at `app.js:5100` reads `freespin_dynamics.trigger_paths`.
This is the only currently-live per-path split (03_coupling.md §2f).

**Phase 1:** No change to `_stDimFreespin`. The frontend continues to render the
`trigger_paths` sub-section inside `freespin_dynamics` as today. The fwpass golden
for M275_1 is the byte-identical regression target.

**Phase 2:** As `freespin_dynamics` migrates to per-dim output per §3.4.3:
- `_stDimFreespin` is updated to read from `spin_type_outcomes.ST126_free.by_dim`
  (for hit_rate, multiplier distribution) and `payouts_by_spin_type.ST126_free__by_dim__trigger_path`
  (for payid mix).
- The trigger_paths sub-table migrates from F6 (a special table) to a GENERIC
  dimension-aware version of `_stDimWinDistribution` + `_stDimPayid`, reusing those
  renderers.
- The specific `_stDimFreespin` shrinks; much of its logic moves into the generic
  per-ST dimension renderers.

#### 3.5.5 `renderStructureDriftPanel` — no change

Structure drift operates at the field level (`per_st_audits[st_str]`), not at the
dimension level. No changes to this renderer.

#### 3.5.6 Contract keys visible to frontend

For Phase 1, the only NEW keys visible to the frontend are ADDITIVE:

```
spin_type_outcomes["ST126_free"]["by_dim"]          # new sub-key; absent for M15/M43/M279
payouts_by_spin_type["ST126_free__by_dim__trigger_path"]  # new sibling key; absent for others
reel_marginal_by_spin_type["ST126_free__by_dim__trigger_path"]  # new sibling key
```

All existing keys are unchanged. The frontend guards on key presence; no fallback code
breaks. The fwpass goldens for M15/M43/M43-7/M279 remain byte-identical.

---

### 3.6 Isolation / base_hash

**Closure = one-time intentional re-baseline:** Under Alternative B (recommended),
there is NO closure change for the dimension framework. `base_hash` remains at
`916ed8021606` throughout Phases 1, 2, and 3.

The ONLY files that change:

| File | Type | Re-flags |
|------|------|----------|
| `st_extract/trigger_path.py` (extended / renamed to `dimensions.py`) | base-excluded | M275 only |
| `features/freespin_dynamics.py` (Phase 2 migration) | base-excluded | M275 only |
| `features/payouts_by_spin_type.py` | base-excluded | All 4 machines (conditional branch is additive; fallback byte-identical) |
| `features/spin_type_outcomes.py` | base-excluded | All 4 machines |
| `features/reel_marginal_by_spin_type.py` | base-excluded | All 4 machines |
| `features/upstream_feature_breakdown.py` (Phase 2) | base-excluded | All 4 machines |
| `configs/machine_manifests/M275.json` | manifest (base-excluded) | M275 only |
| `src/web_console/frontend/app.js` | frontend (not in versioning) | Render only |

**Carve gates:**
- Gate 1 (existing, permanent): editing `st_extract/dimensions.py` does NOT flip
  `base_hash`. Verified by the existing honesty2 drift guard test.
- Gate 2 (new): all PER_SPINTYPE plugin edits produce BYTE-IDENTICAL output for
  M15/M43/M279 (machines declaring no dimensions). Verified by fwpass goldens for
  those 3 machines.
- Gate 3 (new): for M275, `sum(scatter.round_count + collect_peak.round_count + unknowns.round_count) == ST126_spins`. Value-agnostic.

**Per-machine isolation rule (from task spec):** Editing M275.json to add or change
a dimension declaration must not re-flag M15, M43, or M279. This is satisfied by
Alternative B: manifest changes never touch `_CLOSURE_FILES`, and plugin file changes
are guarded by the fallback path.

---

## 4. Hash Composition Rules

### Current algorithm (unchanged)

```
base_hash = sha256(sorted(_CLOSURE_FILES contents))[:12]
                   # current: 916ed8021606

effective_version(machine, mode) = sha256(chain):
  h = sha256(base_hash)
  for fid in sorted(machine_features):
    h.update("\x00" + fid + "=" + feature_hashes[fid])
  for xid in sorted(declared_extractor_ids):
    h.update("\x00xt:" + xid + "=" + extractor_hashes[xid])
  h.update("\x00mode=" + str(mode))
  return h.hexdigest()[:12]
```

### Dimension framework additions

The dimension extractor is registered with `EXTRACTOR_ID = "dimensions"` (or retains
`"trigger_path"` with an alias). Its `compute_hash()` = sha256 of its source bytes.

When M275.json declares `"dimensions"` on ST126:
- `get_extractors_for_manifest(M275_manifest)` returns the `DimensionExtractor`
- `effective_version(M275, 1)` includes `"\x00xt:dimensions=<extractor_hash>"`

When M15/M43/M279 manifests have no `"dimensions"` key:
- `get_extractors_for_manifest(M15_manifest)` returns `[]`
- Their `effective_version` does NOT include any `xt:*` entry
- Editing `dimensions.py` changes `extractor_hashes()["dimensions"]` but this
  only affects machines whose `effective_version` references that extractor

### Worked example: adding a dimension to a new machine M999

1. Add `configs/machine_manifests/M999.json` with `spin_types["50"]["dimensions"]["trigger_path"]`
2. No changes to any other file.
3. `base_hash` = `916ed8021606` (UNCHANGED — no closure file touched)
4. `effective_version(M999, 1)` = new computation (first run)
5. `effective_version(M15, 1)` = UNCHANGED (M15 manifest unchanged)
6. `effective_version(M43, 1)` = UNCHANGED (M43 manifest unchanged)
7. `effective_version(M279, 1)` = UNCHANGED
8. `effective_version(M275, 1)` = UNCHANGED (M275 manifest unchanged; M999 manifest independent)
9. Reports staled: 0 existing reports.

**Worked example: editing dimensions.py to add a new per-round metric**

1. Edit `st_extract/dimensions.py` — new `per_session_tier` accumulator
2. `base_hash` = `916ed8021606` (UNCHANGED — dimensions.py is base-excluded)
3. `extractor_hashes()["dimensions"]` = new value
4. `effective_version(M275, 1)` changes (M275 declares dimensions)
5. M275 existing reports: staled (effective_version mismatch)
6. `effective_version(M15, M43, M279)` = UNCHANGED (no dimensions declared)
7. Reports staled: M275/mode_1 only.

**Worked example: adding `"dimensions"` to M43 ST50 (hypothetical future machine)**

1. Edit `configs/machine_manifests/M43.json` — add `dimensions` block to ST50
2. Extend `respin_dynamics.py` to read from `st_extract["dimensions"]` (conditional)
3. `base_hash` = `916ed8021606` (UNCHANGED)
4. `feature_hashes["respin_dynamics"]` changes
5. `effective_version(M43, 1)` changes (manifest change + respin_dynamics hash change)
6. `effective_version(M279, 1)` changes (respin_dynamics hash change — the shared-plugin cost)
7. `effective_version(M15, M275)` = UNCHANGED
8. `_fwpass_gate/M279_1.json`: byte-identical (fallback branch taken for M279 which has no dimensions on ST36)
9. `_fwpass_gate/M43_1.json`: diverges (new by_dim keys emitted for ST50)

---

## 5. Plugin / Extension Contract

### 5.1 DimensionExtractor (extending TriggerPathExtractor)

The existing `STExtractor` ABC (`st_extract/_base.py`, in `_CLOSURE_FILES`) is
unchanged. The `DimensionExtractor` is a new module in `st_extract/dimensions.py`
(base-excluded), subclassing `STExtractor`.

**Class sketch:**

```python
class DimensionExtractor(STExtractor):
    EXTRACTOR_ID: ClassVar[str] = "dimensions"
    DECLARED_IN_KEY: ClassVar[str] = "dimensions"

    # Also responds to legacy "trigger_paths" key for backward compat.
    DECLARED_IN_KEY_LEGACY: ClassVar[str] = "trigger_paths"

    def __init__(self, manifest: dict) -> None:
        # Parse manifest spin_types for "dimensions" blocks (or "trigger_paths" alias)
        # Build self._st_declarations: {st_int: {dim_name: {discriminator, values, policy}}}
        ...

    def begin_robot(self, robot_ctx: dict) -> None:
        # Reset per-robot state:
        #   self._prev_dim_key = None   # (st, dim_name, dim_value) of previous round
        ...

    def observe_round(self, round_dict, spin_type, round_ctx) -> None:
        # 1. If spin_type in self._st_declarations:
        #    a. Resolve dim_value via discriminator or anchor walk
        #    b. Accumulate into (st, dim_name, dim_value) buckets:
        #       - round_count, win_sum, paid_round_count, win_round_count
        #       - bucket_hist[return_bucket(win/bet)]
        #       - session_count via block_id
        #       - symbol_counts from StopSymbolsByCol
        # 2. Update next_st_counts using _prev_dim_key (if set):
        #    dim_next_st_counts[prev_key][spin_type] += 1
        # 3. Set self._prev_dim_key = current key (for this robot's next round)
        ...

    def finalize_chunk(self) -> dict:
        # Build output:
        # {
        #   "dimensions": {st_str: {dim_name: {dim_value: {all_stats}}}},
        #   "trigger_path": {st_str: {dim_value: {round_count, win_sum, session_count, win_band_hist}}}
        #                   # backward-compat key (same data, reduced shape)
        # }
        ...
```

### 5.2 Plugin conditional pattern (PER_SPINTYPE plugins)

Each PER_SPINTYPE plugin gains a helper function (shared or per-plugin):

```python
def _get_dim_data(chunk_dict, st_int):
    """Return dimension data for st_int from st_extract, or None if absent."""
    st_extract = chunk_dict.get("st_extract") or {}
    dims = st_extract.get("dimensions") or {}
    return dims.get(str(st_int))   # {dim_name: {dim_value: {stats}}} or None

def _has_dimensions(chunk_dict, st_int):
    d = _get_dim_data(chunk_dict, st_int)
    if d is None:
        return False
    # True if any dim_name has >= 2 real (non-unknown) values
    for dim_name, dim_vals in d.items():
        real_vals = [v for v in dim_vals if not v.startswith("unknown:") and not v.startswith("multi:")]
        if len(real_vals) >= 2:
            return True
    return False
```

Each plugin's `extract()`:

```python
def extract(self, parse_state, chunk_dict):
    ...
    for st_int, label in self._st_labels.items():
        # Existing ST-keyed path (unchanged — always runs)
        st_data = chunk_dict.get("payouts_by_spin_type", {}).get(str(st_int), {})
        # ... existing accumulation ...

        # New dimension-aware path (additive — runs only when dim data present)
        dim_data = _get_dim_data(chunk_dict, st_int)
        if dim_data:
            for dim_name, dim_vals in dim_data.items():
                for dim_value, stats in dim_vals.items():
                    # accumulate into per-(dim_name, dim_value) buckets
                    ...
```

### 5.3 How to add a new machine with a multi-dim ST

1. Create `configs/machine_manifests/MXxx.json` with `"dimensions"` block on the
   relevant ST.
2. No extractor code change (DimensionExtractor is generic).
3. No plugin code change (conditional branch already handles it).
4. No manifest change on other machines.
5. `base_hash` unchanged.
6. The new machine's `effective_version` includes `"xt:dimensions=<hash>"`.
7. Generate a report; verify per-dim output in the new ST's `by_dim` sub-key.
8. Add to fwpass goldens.

---

## 6. Migration Plan

### Phase 1: Extractor expansion (base-excluded, no base_hash change)

**Goal:** Extend `DimensionExtractor` to accumulate the full per-ST metric set per
`(ST, dim)`. The `"trigger_path"` backward-compat key is preserved.

**Deliverables:**
- `st_extract/dimensions.py`: new extractor (replaces / extends `trigger_path.py`)
  accumulating `round_count`, `win_sum`, `paid_round_count`, `win_round_count`,
  `bet_sum`, `bucket_hist`, `session_count`, `symbol_counts`, `next_st_counts`.
- `st_extract/__init__.py`: register the new extractor; continue registering old
  `trigger_path` EXTRACTOR_ID as an alias during transition.
- `configs/machine_manifests/M275.json`: add `"dimensions"` block (mirror of existing
  `trigger_paths` block). Keep `trigger_paths` key present for Phase 1.
- Tests: value-agnostic synthetic fixture covering discriminator resolution, unknown
  surfacing, fallback walk, multi-trigger, sum==total invariant, backward-compat
  output.

**Gate:** M15/M43/M43-7/M279 fwpass goldens byte-identical. M275 per-dim round_count
sum equals ST126 total (8,290+800+0_unknown == 9,090 — per 02_path_traces.md §M275 ST126).
Full suite green.

**Rollback:** Revert `st_extract/dimensions.py` to `trigger_path.py`. The old extractor
self-registers with `EXTRACTOR_ID = "trigger_path"`. `freespin_dynamics` reads the old
key. M275 fwpass golden remains unchanged. Zero impact on M15/M43/M279.

---

### Phase 2: Generic PER_SPINTYPE plugins gain dimension-awareness

**Goal:** `payouts_by_spin_type`, `spin_type_outcomes`, `reel_marginal_by_spin_type`
produce `by_dim` sub-keys when dimension data is present.

**Deliverables:**
- `features/payouts_by_spin_type.py`: `by_dim` sibling key for declared-dimension STs.
- `features/spin_type_outcomes.py`: `by_dim` sub-key inside each ST dict.
- `features/reel_marginal_by_spin_type.py`: `by_dim` sibling key.
- `features/spin_type_rtp_buckets.py`: no change for Phase 2 (free STs excluded).
- `features/freespin_dynamics.py`: migrate to reading from `st_extract["dimensions"]`
  (instead of `st_extract["trigger_path"]`). ALL F-sections gain `by_dim` sub-keys.
  The `trigger_paths` output block inside `freespin_dynamics` is replaced by per-dim
  slices of each F-section metric.
- `src/web_console/frontend/app.js`: add `_stDimGenericDimension(stCtx)` to
  `SPINTYPE_DIMENSIONS`. This renderer reads `spin_type_outcomes[label].by_dim` and
  `payouts_by_spin_type[label+"__by_dim__"+dimName]` and renders side-by-side columns
  when N >= 2 dimension-values. For N=1 or absent: returns `""`.
  Update `_stDimFreespin` to read from the new `by_dim` structure instead of the old
  `trigger_paths` block.

**Gate:**
- M15/M43/M43-7/M279 fwpass goldens byte-identical (no `by_dim` keys present —
  verified by JSON diff).
- M275_1 semantic gate: per-dim payid rows sum to ST-aggregate. Per-dim
  `rtp_contribution_pp` values sum to total ST `rtp_contribution_pp` (value-agnostic:
  checked as invariant sum, not pinned numbers).
- `sum(payid) == summary.rtp` invariant holds (M275 and all other machines).
- Playwright gate-7: console renders M275 ST126 with two columns (scatter/collect_peak)
  in `_stDimWinDistribution` and `_stDimPayid` panels. No page errors.

**Rollback:** Revert plugin files. The `st_extract["trigger_path"]` backward-compat
key is still present; `freespin_dynamics` can be reverted to Phase 1 state. M275_1
golden reverts to Phase 1 shape (which matches the pre-Phase-2 golden).

---

### Phase 3: Cross-cutting readers and remaining items

**Goal:** `upstream_feature_breakdown` replaces coarse chain heuristic with accurate
dimension labels; parser-blind metrics (ER ladder, FS arc) via `FreespinProgressionExtractor`.

**Deliverables:**
- `features/upstream_feature_breakdown.py`: conditional branch reads dim labels from
  `st_extract["dimensions"]` for feature STs; sub_streams labels are now
  dimension-value labels.
- `st_extract/freespin_progression.py`: new base-excluded extractor accumulating
  per-round `ExtraRatio`, spin-count-within-session, per-session win total — per
  `(ST, dim)`. DECLARED_IN_KEY = `"dimensions"` on `freespin` role STs. M275 only.
- `features/freespin_dynamics.py`: consume progression extractor output for ER ladder
  and FS arc sections (closing `parser_blind` items (a) and (b) from M275.json caveats).
- Frontend: new sub-panels for ER ladder and FS arc, reusing existing histogram
  renderer helpers.

**Gate:** All existing gates hold. M275 ER ladder and FS arc panels render correctly
(Playwright). Value-agnostic (structural, no pinned numbers).

**Rollback:** Revert Phase 3 files. Phase 2 output is unaffected.

---

### Backward compatibility during migration

**What must continue working unchanged during ALL phases:**
- `player_impact_summary.json` for M15, M43, M279: byte-identical at every phase
  gate. Verified by fwpass goldens.
- `sum(payid) == summary.rtp` for all 4 machines: value-agnostic invariant.
- `our == server` check (when applicable): unaffected (no attribution logic changes).
- Frontend rendering for M15, M43, M279: no `by_dim` keys present; all existing
  `_stDim*` renderers return the same output.
- The existing `freespin_dynamics.trigger_paths` block in M275 summaries: preserved
  through Phase 1; migrated away in Phase 2 with frontend simultaneous update.

**What can be regenerated:**
- M275 reports: will change at Phase 1 (new extractor hash → effective_version change)
  and again at Phase 2 (plugin hashes change). Both changes are expected and desirable.

---

## 7. Open Questions for Wave 3

**OQ-1 — `spin_type_rtp_buckets` for paid declared-dimension STs:**
Current design: `spin_type_rtp_buckets` is Phase 2 no-op for M275 (ST126 is free).
If a future machine has a PAID ST with two trigger paths, do we want per-dim bucket
histograms in `spin_type_rtp_buckets`? The extractor's `bucket_hist` per `(ST, dim)`
already provides this data. The plugin just needs to read it. Recommend: add this in
Phase 2 under a `by_dim` sub-key, even if it does nothing for current machines.
Wave 3 should confirm whether the paid-ST exclusion for free STs is a hard design
decision or a convenience assumption.

**OQ-2 — `freespin_dynamics.trigger_paths` output block removal timing:**
Phase 2 proposes replacing the `trigger_paths` block with per-dim sub-keys in each
F-section. This is a SCHEMA CHANGE for M275. The fwpass golden for M275_1 WILL diverge.
Wave 3 (critic + validator) must confirm: (a) is there any external consumer of the
M275_1 golden's `trigger_paths` block structure that would break? (b) should the old
block be preserved as a derived summary alongside the new per-dim structure? The
breaker role should test this against the real M275 console.

**OQ-3 — `structure_drift` path-awareness:**
The `structure_drift` plugin reads field presence per ST. If a declared dimension's
two paths have different field sets (e.g. scatter ST126 has ExtraRatio, collect_peak
does not), the merged field presence would not catch the divergence. Should the
dimension framework extend structure_drift to audit per `(ST, dim)` field presence?
This would require the DimensionExtractor to also track observed fields per dim-value.
Low priority for Phase 1; open for Wave 3 opinion.

**OQ-4 — `payout_id_win_by_spin_type` attribution for trigger sessions (01 §9 Q3):**
The pipeline map notes that for M275, freespin session wins attributed to the trigger
round's ST140 may not appear in `payouts_by_spin_type["ST126_free"]` rows. If this
is true, the per-dim payid rows for ST126 scatter vs collect_peak may be incomplete.
Wave 3 should trace: what does `payouts_by_spin_type["ST126_free"]` actually contain
for M275_1? Does `rtp_contribution_pp` for ST126 payids sum to the per-ST RTP
contribution, or is there a gap? This matters for Phase 2's per-dim payid mix quality.

**OQ-5 — Multi-dimension design for single manifests:**
The schema supports multiple named dimensions per ST (e.g. `"trigger_path"` AND
`"stake_tier"` on the same ST). This design proposal supports the schema but only
implements single-dimension rendering (Phase 1/2). Wave 3 should declare whether
multi-dimension cross-tabulation (per `(ST, dim1_value, dim2_value)`) is in scope
for a future phase, or whether the cardinality explosion makes it undesirable.

**OQ-6 — `signature_audit` STExtractor resolution (01 §9 Q2):**
The pipeline map flags an unresolved question about whether `structure_drift` reads
`chunk_dict["st_extract"]["signature_audit"]` from a real extractor or some other
mechanism. Before Phase 3 (which may add new extractor modules), Wave 3 should trace
the actual data flow for `signature_audit` and confirm: does a `SignatureAuditExtractor`
exist in `st_extract/`? Is it registered? Or does `structure_drift` get its data
from a different stash path? This matters for extractor registration ordering.

**OQ-7 — Double-trigger session attribution at full production scale (02 §M275 edge case):**
1 double-trigger observed in 89,090 rounds (~1.09% of sessions). The design routes
the double-trigger round to `"multi:<A>+<B>"` per the existing `additive_sessions`
policy. At production scale (10M rounds), the double-trigger count may be meaningful.
Wave 3 should assess: should the double-trigger be un-merged into separate sessions
for per-dim accounting, or is the multi-bucket alarm semantics sufficient?

---

## 8. Out of Scope

**OS-1 — Multi-dimension cross-tabulation.** This proposal supports one active
dimension per ST. Analyzing round outcomes grouped by `(trigger_path AND stake_tier)`
simultaneously is not designed here. The schema accommodates it but the extraction,
summary schema, and frontend rendering for cross-tabulated dimensions are out of scope.
Rationale: the only confirmed multi-path ST in the current fleet is M275 ST126, which
has exactly one declared dimension. Building cross-tabulation before a second dimension
is observed in rawdata would be UNVERIFIED-NEEDS-TRACE work.

**OS-2 — M43 ST51 and M279 ST2 sequence-path splitting.** Both STs have two
sequence-level paths with NO in-round discriminating field and statistically identical
outcomes (02_path_traces.md, Z=0.27 and Z not significant respectively). No
`"dimensions"` block will be declared for these STs because there is no config-slot
divergence possible. The sequence paths are a curiosity, not an actionable dimension.
Adding fake dimension labels would violate the "mirror the rawdata, invent nothing"
invariant (DIRECTION.md §2).

**OS-3 — ExtraRatio as a dimension on M15 ST14.** ExtraRatio (1x/2x/4x) is a
per-pick multiplier within a TopDollar session, not a session-level dimension. The
assignment mechanism is opaque (02_path_traces.md: "the engine-internal rule for
assigning ER to each pick is unobservable in rawdata"). Splitting ST14 analysis by
ExtraRatio would not correspond to a different config slot or a different game
experience — it would split arbitrary in-round variance. Out of scope.

**OS-4 — Changing the `spin_type_breakdown` key name or schema.** The pipeline map
(01 §3) and coupling audit (03 §4 Case 4) show this key has 10 direct consumers and
any rename triggers a base_hash flip. This proposal adds `by_dim` sub-keys inside
existing per-label dicts and sibling keys with suffixes — no rename of any existing key.

**OS-5 — Non-registered machines (the legacy 420-machine fleet).** The dimension
framework applies only to registered machines (those with manifests in
`configs/machine_manifests/`). The other machines have no manifests, generate no
reports, and are therefore out of scope.

**OS-6 — `bonus_chain_dynamics` dimension alignment (Phase 3+).** The chain
mechanism uses `(first_st, entry_cc_reset, sp_type)` keying — a structural axis
orthogonal to the declarative dimension system. Aligning them requires understanding
how the chain's `entry_cc_reset` heuristic relates to the dimension's discriminator.
This is a Phase 3+ item pending the Phase 2 foundation.

**OS-7 — Parser.py accumulator changes of any kind.** Under Alternative B (recommended),
`parser.py` is not touched by the dimension framework. Any proposal that requires
touching the parser is out of scope for this pass (it belongs to a separate framework
pass with an intentional base_hash re-baseline).

**OS-8 — `spin_type_next_counts[(st, dim)]` in the parser.** The transition tally
from the parser is used by `freespin_dynamics`, `respin_dynamics`, and
`upstream_feature_breakdown`. Under Alternative B, next_st counts per dim are computed
in the extractor via the `_prev_dim_key` stateful pattern. The parser accumulator is
unchanged. If the stateful extractor pattern proves insufficient in practice (e.g.
cross-robot transitions), this becomes an open question for Wave 3.
