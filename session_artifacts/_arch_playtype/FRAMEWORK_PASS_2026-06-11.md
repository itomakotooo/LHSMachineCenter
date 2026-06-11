# Framework pass — session-dim fix + per-ST extraction layer (2026-06-11)

User-approved (architecture discussion, this session): framework-first, ONE pass, then M275 W4.
Two gated sub-commits. Both touch the closure → base_hash flips (expected; no pins exist).
Coordinator gates every sub-commit. Internal spec — agents read this; user never reviews it.

Vocabulary rule (user, 2026-06-11): NO "machine family" concept anywhere (briefs, names,
comments). The only legal cross-machine relation is VARIANTS (a mechanism). Generality lives
in MECHANISMS ("machines whose ST carries a per-round discriminator field"), never in claimed
machine groups.

---

## Sub-pass A — session-dimension win fix (the W2 ABORT, coordinator-verified)

**Defect (verified on M275 real chunks):** `trigger_sessions.compute_trigger_sessions` produces
`session_win` with the `round_has_credited_win` exclusion — CORRECT for pid attribution (no
double count), but `core/parser.py` `_close_session` reuses that SAME number for the SESSION
KPI dimension (`bonus_win_from_helper`). On a machine whose bonus rounds self-credit at pid
level AND whose trigger anchor is a win==0 pid (M275: pid 666), every such session's bonus win
vanishes from the session view: M275 loses 45.8% of all win there (avg_return_x 0.48339 vs true
0.89236; ≥10× 851 vs 1,517; max 172.5× vs 338×; winning sessions 11,150 vs 11,893 — all four
independently recomputed by the coordinator, `_tmp/m275_coord_check.py`).

**Fix design (two numbers, two dimensions):**
1. `trigger_sessions.compute_trigger_sessions`: each session dict gains **`session_dim_win`** —
   the SAME `win_rule` (Type 1 `last_non_none` / Type 2 `sum_all`) over the rule-view per-round
   wins, **WITHOUT** the `round_has_credited_win` exclusion. Compute both in the same walk.
   On Type-1 shapes (M15) the exclusion never fires → `session_dim_win == session_win` →
   byte-identical by construction. Additive key; no consumer breaks.
2. `core/parser.py`: build `session_dim_win_by_trigger_idx` next to the existing map
   (~L1224); `_close_session`'s `bonus_win_from_helper` (~L1607) takes the DIM value.
   Every OTHER consumer of `session_win` (pid attribution fold, `session_handled_bonus_indices`)
   stays on `session_win` — pid dimension untouched, parity preserved.
3. **Investigate (decide with evidence + cover with a test):** the Pass-5/iter-6 settlement-ST
   bucket feed (~L1249) bins each trigger session's `session_win` into the LAST bonus round's
   ST bucket histogram. That histogram is a session-level display → prior: switch it to
   `session_dim_win` (M15 equal → byte-identical; M43/M279 have no detected trigger sessions →
   unaffected). If evidence says it is pid-scoped, keep and document why.
4. **Session-conservation alarm (rtp_integrity.py, closure — same flip):** new summary-level
   check: when the machine_spec manifest declares EVERY ST's `economy.kind == "real"`,
   `Σ session wins (session dimension) ≈ total win` (tolerance for float; orphan bonus rounds
   — bonus before any paid round — are excluded from sessions, so the check compares against
   total win MINUS orphan bonus win if the parser can surface that; if surfacing orphan win is
   disproportionate, document the limitation and check ≤/≥ accordingly). Machines with preview
   economy STs (M15 ST14) SKIP (the session dim is rule-view, not raw — conservation does not
   hold by design). Surfaced as a class like the fallback-share check (OK/WARN/FAIL), never a
   silent residual (feedback_invariant_with_fallback_hides_drift). Value-agnostic.

**Gates (A):** M15 + M43 + M279 regenerated reports byte-identical pre/post (modulo version
stamps — reuse the `_p5_gate.py` method); full suite green; M275 one-shot verification at
parser level (machine not yet registered): session dim == 0.89236 / 11,893 / 1,517 / 338×
(these four exact numbers are the coordinator-verified TRUE values for THIS md5 bucket —
one-shot acceptance only; the PERMANENT regression tests stay value-agnostic: synthetic
fixture with self-crediting bonus rounds + zero-win anchor pid → session dim == raw sum,
inject-bug→red→revert→green).

## Sub-pass B — per-ST extraction layer + generic trigger_path extractor (DIRECTION.md §3)

**Gap (verified):** `AnalyzerFeature.extract(parse_state, rec)` is per-CHUNK; `rec` is the L1
parser's accumulated record — plugins never see raw rounds. Every per-round dimension metric
(M275 GTT path split / ER ladder / FS arc; M43 minigame nodes; M279 wheel cell-map) is
parser_blind. Fix = ONE stable hook in the closure + a base-excluded extractor layer, mirroring
the features layout exactly:

1. **Package `fresh_slotlab/analyzer/st_extract/`** —
   - `__init__.py` (discovery/registry: `get_extractors_for_manifest(manifest)` returns
     instantiated extractors declared by the manifest) and `_base.py` (`STExtractor` ABC:
     `EXTRACTOR_ID`, `compute_hash()` — same source-hash classmethod as features,
     `begin_robot(robot_ctx)`, `observe_round(round_dict, spin_type, round_ctx)`,
     `finalize_chunk() -> dict`): these two framework files GO INTO `_CLOSURE_FILES`
     (stable, like `features/__init__.py` + `features/_base.py`).
   - Extractor MODULES (e.g. `trigger_path.py`) are base-EXCLUDED (like feature modules),
     auto-discovered, per-extractor `compute_hash()`.
2. **Parser hook (closure, the one-time cost):** parser accepts optional `st_extractors`
   (default empty — legacy callers unchanged). Per robot: `begin_robot` with a ctx exposing the
   robot's `_trig_sessions_for_robot` (already computed ~L1221) as a round-index→session-record
   map + `cycle_peak`. Per round in the main loop: `observe_round(rd, sp_type, round_ctx)` where
   round_ctx = {robot_idx, round_idx, session record or None, bet}. At record build (~L2404):
   `"st_extract": {extractor_id: finalize_chunk()}` (omitted when no extractors — old chunks/
   records remain valid; absence of the key is a legitimate state, feedback_no_silent_swallow
   notwithstanding: extract() readers treat missing as empty, the respin_dynamics pattern).
   Exceptions inside an extractor must NOT kill the parse: catch per-extractor, surface in the
   record (`_extract_error_*` pattern report_engine already uses), never swallow silently.
   Update the R-1 drift guard allowlist (it allowlists `play_types/` imports today) for
   `st_extract` extractor-module imports if the guard trips.
3. **`report_engine.py` (closure):** resolve `get_extractors_for_manifest(manifest)` once,
   pass to the parser. Registered machines only; manifests without extraction declarations →
   empty list → byte-identical behavior.
4. **Generic `trigger_path` extractor (base-excluded)** — reads per-ST manifest block:
   ```json
   "trigger_paths": {
     "discriminator": {"kind": "round_field", "field": "...", "map": {"<value>": "<label>"},
                        "unmapped_value_policy": "surface_as_unknown_path"},
     "fallback": {"kind": "trigger_anchor_walk"},
     "paths": {"<label>": {"opened_by": {"payout_id": "..."} | {"counter": "...", "at_peak": N},
                "label": "..."}},
     "multi_trigger_policy": "additive_sessions"
   }
   ```
   Per declared ST, per round: label via the discriminator field map; unmapped value →
   `"unknown:<value>"` (a SIGNAL bucket, surfaced, never merged); machines without a
   discriminator field use the anchor-walk fallback (the session record's trigger_pay_ids /
   counter-peak entry — the same walk ufb's `[via …]` split implements). Accumulate per
   (st, path): `round_count`, `win_sum`, `session_count` (counted at session entry), and a
   per-path win-multiplier band histogram (reuse the existing band-edge helper the chain
   buckets use; bet from round_ctx). Output shape is generic — NO M275-specific code anywhere.
5. **Versioning (closure):** machines whose manifest declares extraction fold extractor hashes
   into `effective_version` via the EXISTING `compute_effective_analyzer_version` composition —
   append pseudo-entries (`"xt:trigger_path"` → its `compute_hash()`) into the feature_hashes/
   machine_features inputs at the call sites (`effective_version_cache` / wherever
   get_features_for_machine feeds it). No signature change. Editing an extractor re-flags ONLY
   machines declaring it; editing st_extract framework files flips base_hash (correct - closure).
6. **Carve-gate tests (permanent):** editing `st_extract/trigger_path.py` does NOT flip
   base_hash; `st_extract/{__init__,_base}.py` ARE in the closure; a manifest WITHOUT
   declarations produces a record with NO st_extract key (inertness).

**Gates (B):** M15 + M43 + M279 byte-identical pre/post (they declare nothing); full suite
green; one-shot semantic verification on M275 real chunks via a direct parser call with a
synthetic manifest carrying the W3 trigger_paths block (03_design.md §4.4): per-path session
counts 829 scatter / 80 collect_peak, round split 8,280+10 / 810−10±(the 1-in-909
double-trigger round binned per the discriminator field — document which way it lands),
win sums reconcile with W1 §7.2 (32,637,000 + 80,500 vs 2,894,500 — exact split per GTT);
permanent tests value-agnostic (synthetic fixture: field discriminator, unknown value
surfacing, fallback walk, additive multi-trigger).

## Sequencing
A then B (same files). Each sub-pass: implement → test → verify → adversarial critique →
coordinator gate → commit (surgical adds, never `git add -A`; 4-section message with
Self-critique). Then M275 W4 onboarding resumes on the new foundation.
