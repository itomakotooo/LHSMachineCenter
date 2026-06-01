# Commit B — Adversarial Review (impl-critic)
> Branch: claude/playtype-rearch. Base: 7babf1e (Commit A). Diff: unstaged changes to parser.py, base_pipeline.py, player_impact_analyzer.py.
> Reviewer: impl-critic agent. 2026-06-01.

---

## Severity scale: BLOCKER / SERIOUS / MINOR

---

## 1. TOPO-SORT ORDER BROKEN: _active_plugins rebuilt in REGISTRATION order, not MECHANIC_DEPS order

**Severity: SERIOUS (latent — bites at Commit C, not observable now)**

**Location**: `parser.py` wiring point 1, lines 703-707.

```python
_active_plugin_fids = set(_pt_config.active_plugins)
_active_plugins = [
    p for p in _registry_plugins        # <-- REGISTRATION ORDER
    if p.FEATURE_ID in _active_plugin_fids
]
```

`detect_play_types()` correctly topo-sorts active plugins via `_topo_sort_plugins()` and returns `_pt_config.active_plugins` as a FEATURE_ID list in topo order. But the wiring code then re-filters `_registry_plugins` — which is in REGISTRATION ORDER — by FID set. The resulting `_active_plugins` list is in REGISTRATION ORDER, which may differ from MECHANIC_DEPS topo order when multiple concrete plugins exist.

All three wiring points that iterate `_active_plugins` (points 2, 3, 4+5) therefore dispatch in registration order instead of topo order. The design doc (§4.1-rev Step P) states topo-sort governs `on_round()` dispatch order AND `to_chunk_partial()` merge order; this is violated.

**Fix direction** (not a fix, just the flag): reconstruct `_active_plugins` from `_pt_config.active_plugins` (the FID list in topo order) by mapping FIDs back to instances via a lookup dict, not by filtering `_registry_plugins`.

---

## 2. EC-4 DIAGNOSTIC NOT PERSISTED TO CHUNK DICT — violates design doc + memory feedback

**Severity: SERIOUS**

**Location**: `parser.py` wiring points 3 and 4+5 exception handlers, lines 2159-2171 and 2255-2261.

The design doc (04_v2.md §13 EC-4) states:
> "mark the chunk as `partial_attribution=True` in the chunk dict ... The report surfaces a warning."

The code comment at line 2160-2163 says:
> "Per memory/feedback_no_silent_swallow.md: persist diagnostic (written to return dict at finalize)."

But the implementation ONLY prints to `sys.stderr`. No `partial_attribution` key is set anywhere in `_chunk_plugin_partial` or the return dict. The comment claims this diagnostic is "written to return dict at finalize" — that is false. It is only written to stderr, which workers can silently swallow (per `feedback_no_silent_swallow.md`, the exact failure mode this memory warns against).

For the batch worker path (`_batch_gen_worker.py`), stderr from child processes may or may not surface to the operator. With 10 concurrent workers hammering this path, a faulting accumulator generating thousands of on_round errors would produce thousands of stderr lines that scroll away — the operator would see no structured signal in the report.

The comment ("written to return dict at finalize") is a false claim. This is a correctness gap vs both the design doc and the memory file.

---

## 3. PROBE RUNS AFTER detect_play_types — bootstrapping order inversion for CostCreditsReliabilityProbe

**Severity: SERIOUS (latent — bites at Commit C when LockRespinPlugin / CostCreditsReliabilityProbe is concrete)**

**Location**: `parser.py` lines 699-715.

The order is:
1. `detect_play_types(_probe_sample, _registry_plugins, _chunk_parse_state)` — evaluates `ClaimSignature.matches()` using current `_chunk_parse_state.cost_credits_unreliable`
2. Probes run: `_probe.run(_probe_sample, _chunk_parse_state)` — may set `cost_credits_unreliable=True`
3. Sync back to local: `cost_credits_unreliable = _chunk_parse_state.cost_credits_unreliable`

For Commit C, `LockRespinPlugin` declares `CostCreditsReliabilityProbe`. On M10 machines, the probe sets `cost_credits_unreliable=True`. But `detect_play_types` was already called at step 1 with the OLD value (False — the pre-existing pre-scan may also correctly detect cc=0 on M10, so this may be redundant). More precisely: `ClaimSignature.matches()` uses `parse_state.cost_credits_unreliable` to classify paid/bonus rounds for signature evaluation. If the probe's result should influence whether a plugin's signature matches (per §4.2-rev: "evaluated against rounds where CostCredits > 0 OR parse_state.cost_credits_unreliable=True"), then running probes AFTER detection means the probe's classification override is not used during detection.

The design doc (§4.5 lifecycle) says: "The probe runs before any `on_round()` call. By the time LockRespinAccumulator.on_round() fires, parse_state.cost_credits_unreliable=True is already set." This is correctly honored. But the doc also says: "parse_state.cost_credits_unreliable is available at Step U1 because the probe runs PRE-LOOP." The probe DOES run pre-loop (before the robot loop). But it runs AFTER `detect_play_types`, creating a bootstrapping problem: the probe is only enabled if its plugin is in `active_plugins`, but `active_plugins` was determined by `detect_play_types` running BEFORE the probe. For M10, the pre-existing inline cc-detection (lines 650-664) already sets the local `cost_credits_unreliable`, so `_chunk_parse_state` is initialized from the correct value — this is a coincidence, not a structural guarantee.

The correct order per design is: probes should inform detection, not be gated by detection. The current code inverts this.

---

## 4. win_credits IN RoundCtx IS RAW WinCredits, NOT rule-processed win_amt

**Severity: SERIOUS (latent — bites at Commit C for TopDollar/SettlementWinAmountRule machines)**

**Location**: `parser.py` wiring point 3, lines 2119-2123.

```python
_win_credits_raw = r.get("WinCredits")
try:
    _win_credits_int = int(_win_credits_raw) if _win_credits_raw is not None else 0
except (TypeError, ValueError):
    _win_credits_int = 0
```

`RoundCtx.win_credits` is set to `int(r.get("WinCredits"))` — the RAW field.

But the U1 body computed `win_amt = extract_round_win(r, rules=round_win_rules)` at line 1566. For machines with active round_win_rules (e.g. `SettlementWinAmountRule` on TopDollar/M15 suppresses round-level WinCredits), `extract_round_win()` may return a DIFFERENT value than `r.get("WinCredits")`.

A Commit C plugin accumulator reading `ctx.win_credits` would see the raw field, not the rule-processed `win_amt`. This is a fidelity gap between the `RoundCtx` contract (§4.1-rev: "Accumulators read universal-derived values from here instead of re-deriving them") and the actual implementation.

**Design note**: `RoundCtx.win_credits` is typed as `int` in the NamedTuple, but `win_amt` (from `extract_round_win`) is a float. This is a type-mismatch that would fail on machines where WinCredits is fractional or where a rule overrides to a float.

---

## 5. authoritative_pay_ids IN RoundCtx ALSO RAW — not rule-processed pid_to_win keys

**Severity: SERIOUS (latent — bites at Commit C for SynthesizePayIdRule / SettlementWinAmountRule machines)**

**Location**: `parser.py` wiring point 3, lines 2124-2127.

```python
_auth_pids_raw = r.get("PayoutIdToWinAmount")
_auth_pay_ids = frozenset(
    str(k) for k in (_auth_pids_raw.keys() if isinstance(_auth_pids_raw, dict) else ())
)
```

`RoundCtx.authoritative_pay_ids` is built from `r.get("PayoutIdToWinAmount")` — the raw upstream dict.

But the U1 body called `extract_round_payouts(r, rules=round_win_rules, ctx={"bet": bet})` at line 1912 to get `pid_to_win`. For machines with `SynthesizePayIdRule`, `extract_round_payouts` returns SYNTHESIZED pay_ids (e.g. `{"20": 20000}` for a wheel round), not the raw `PayoutIdToWinAmount` keys. For `SettlementWinAmountRule`, it returns `{}` (suppression).

An accumulator reading `ctx.authoritative_pay_ids` on a rule-active machine would see the raw pay_ids, not the rule-synthesized ones. Same structural mismatch as finding #4.

---

## 6. _chunk_plugin_partial.update() OVERWRITES CROSS-ROBOT KEYS — implementer concern #1 is a real latent bug

**Severity: SERIOUS (latent — bites at Commit C when BCMBaseAccumulator writes all_cycle_peaks)**

**Location**: `parser.py` wiring points 4+5, line 2270.

```python
_chunk_plugin_partial.update(_robot_partial)
```

This is called once per robot. If two robots both return `{"all_cycle_peaks": [...]}`, the second robot's dict OVERWRITES the first's. The chunk partial accumulates only the LAST robot's `all_cycle_peaks`.

The existing inline code at line 2295 correctly uses `extend()`:
```python
chunk_cycle_peaks.extend(robot_cycle_peaks)
```

The implementer flagged this concern and claimed "it matches inline `extend` behavior" — this claim is INCORRECT. `dict.update()` is NOT semantically equivalent to `list.extend()` for list-valued keys. This is a real cross-robot data loss bug that will fire when `BCMBaseAccumulator` writes `all_cycle_peaks` at Commit C.

The `collect_robots_seen_total` key has the same problem: it's an int, so `update` would overwrite it with the last robot's count instead of accumulating the total.

---

## 7. FLAG THREADING USES getattr SENTINEL — inconsistent behavior if args lacks attribute

**Severity: MINOR (safe for Commit B; potential confusion in Commit C+)**

**Location**: `player_impact_analyzer.py` lines 1558 and 2285.

```python
use_play_type_plugins=getattr(args, "use_play_type_plugins", False),
```

`getattr(args, ..., False)` is used instead of `args.use_play_type_plugins`. If PIA is invoked from a code path that builds `args` without going through `base_pipeline.parse_args()` (e.g., a test harness that constructs a mock `Namespace`), the attribute silently defaults to False. This is safer than crashing, but it means a test that forgets to add `use_play_type_plugins` to its mock `args` will silently test flag-off behavior while thinking it's testing flag-on.

The `--from-cache` and online paths use the same pattern at both call sites, so the flag IS threaded to both paths. Flag threading completeness: PASS for production paths.

---

## 8. import sys INSIDE EXCEPTION HANDLERS — implementer concern #3 is mostly harmless

**Severity: MINOR**

**Location**: `parser.py` lines 2164, 2256, 2272.

`import sys as _sys` inside the except block. The implementer flagged this.

Python caches all imports in `sys.modules`, so a repeated `import sys` costs a single dict lookup — effectively free. It is mildly unidiomatic (sys is always available; it should be at module top). The current parser.py already imports `json`, `re`, `time` at the top; `sys` is conspicuously absent. This is a style issue, not a correctness bug. The exception handler path is cold; no performance concern.

The implementation's justification ("avoid a new import") is unconvincing — sys is a stdlib builtin. Real risk is zero. The minor code smell is that if sys is not in the global namespace, a NameError here would be swallowed by the outer `except Exception`. But since sys IS always available in Python, this scenario is impossible.

---

## 9. _pt_cfg_empty STUB RECONSTRUCTED PER ROBOT — inefficiency + correctness time-bomb

**Severity: MINOR (Commit B safe; SERIOUS at Commit C)**

**Location**: `parser.py` wiring point 2, line 1222.

```python
_pt_cfg_empty = _PlayTypeMachineConfig(machine_id="", mode=0)
```

This stub is constructed once per robot (inside the robot loop). It's cheap for Commit B (empty registry means the block doesn't execute). But at Commit C, a concrete accumulator like `BCMBaseAccumulator(machine_config)` expects a real config with `machine_id` and `mode`. If the stub is not replaced, `make_accumulator("")` on BCMBaseAccumulator would produce an accumulator with no machine context — silently wrong behavior, not a crash.

The implementer flagged this as "safe for B, but what breaks at C if not replaced with a real config?" The answer: any accumulator that reads `machine_config.machine_id` or `machine_config.plugin_configs` to configure its behavior (e.g., trigger pay_id overrides) will silently use empty/default values. This is a correctness bug that won't crash — exactly the worst kind.

---

## 10. PROBE DETECTION RUNS PER-CHUNK, NOT PER-(MACHINE,MODE) — performance + correctness concern

**Severity: MINOR (Commit B) / SERIOUS (at Commit C scale)**

**Location**: `parser.py` wiring point 1, lines 680-715.

`detect_play_types()` is called inside `parse_chunk_response()`, which is called once per chunk. For a 1000-chunk run (100k spins × 10 chunks), `detect_play_types` runs 1000 times on different chunk samples. The design doc (§9-rev Phase 1 #18) says the per-machine config is generated once and cached to disk as `configs/play_type_configs/<M>/mode_<n>.json`. The current wiring does NOT read from this cache — it re-detects on every chunk.

Consequences:
1. **Performance**: 1000 calls to `detect_play_types` instead of 1, each scanning up to 5000 rounds. Minor overhead today (empty registry), severe at Commit C with real plugins and real detection logic.
2. **Non-determinism**: Detection may produce different `active_plugins` on different chunks if a rare trigger doesn't appear in every chunk's first robot sample. The `st_map` could flip between chunks — making the MachinePlayTypeConfig inconsistently applied across a multi-chunk run.
3. **Design mismatch**: The design says config is generated once (Phase 1 #18) then read from disk. The wiring should read the on-disk config first (if it exists) and fall back to detection only if the config file is absent.

---

## 11. _probe_sample PARSES FIRST ROBOT TWICE — redundant work

**Severity: MINOR (negligible performance)**

**Location**: `parser.py` lines 650-664 and 691-696.

The pre-existing cc-detection pre-scan calls `parse_rounds(_sample_robot)` at line 652. Wiring point 1 then calls `parse_rounds(_first_robot_for_probe)[:5000]` at line 696 — a second full parse of the same robot's rounds (different variable names, same underlying data). This is redundant work: `parse_rounds` likely does non-trivial JSON parsing. The wiring could reuse `_sample_rounds` from the pre-scan (already available in scope), capping at 5000 rounds.

This does not affect correctness, only efficiency.

---

## 12. detect_play_types CALLED WITHOUT machine_id OR mode — config written with empty strings

**Severity: MINOR**

**Location**: `parser.py` line 699-701.

```python
_pt_config = detect_play_types(
    _probe_sample, _registry_plugins, _chunk_parse_state,
)
```

`machine_id` and `mode` default to `""` and `1`. The returned `MachinePlayTypeConfig` would have `machine_id=""` and `mode=1`. If this config is ever written to disk (at Commit C), it would overwrite a real config with an anonymous one. For Commit B (empty registry, config not written), this is harmless. But the `parse_chunk_response` function receives `chunk_index` not machine/mode — the caller (PIA's `main()`) has access to `args.machine` and `args.rtp_mode`, but these are not threaded into `parse_chunk_response`.

---

## Adjudication of implementer's 3 flagged concerns

**Concern (1): `_chunk_plugin_partial` per-robot key OVERWRITE**
The implementer claims it "matches inline `extend` behavior." This is WRONG. Finding #6 above demonstrates that `all_cycle_peaks` uses `extend()` in the inline code; `dict.update()` overwrites. This is a real latent cross-robot data loss bug for Commit C. Rating: REAL BUG, not safely deferred.

**Concern (2): Stub `_PlayTypeMachineConfig(machine_id="", mode=0)`**
Safe for Commit B. Will silently produce wrong behavior at Commit C if any accumulator reads `machine_config` fields. Rating: CORRECTLY FLAGGED, must be fixed at Commit C before the first concrete accumulator.

**Concern (3): `import sys` inside exception handlers**
Harmless (sys is always in sys.modules). Style issue only. Rating: NON-ISSUE for correctness, minor style violation.

---

## Flag-OFF path: is ALL new code strictly behind the gate?

Audit of always-executed new statements:

1. **Module-level imports** (lines 92-107): `from fresh_slotlab.analyzer.play_types._base import RoundCtx, MechanicAccumulator` etc. These execute at module import time, unconditionally. If the `play_types` package has any import-time side effects that were missed in Commit A review, this would affect the flag-off path. The Commit A review verified no side effects. Accept as safe.

2. **`_active_plugins: list = []`** (line 678): always executed. Empty list initialization — no side effect.

3. **`_chunk_plugin_partial: dict = {}`** (line 1206): always executed (before the robot loop). Empty dict initialization — no side effect.

4. **`_robot_accs: dict = {}`**, **`_all_round_ctxs: list = []`**, **`_all_rounds_for_accs: list = []`** (lines 1218-1220): always executed (inside robot loop). Three empty container initializations per robot — negligible overhead, no side effect.

5. **`**_chunk_plugin_partial` spread** (line 2607): always executed. When the dict is `{}`, the spread adds zero keys. The resulting dict is identical to not having the spread.

Verdict on flag-off: Items 1-5 are genuinely safe. The always-executed new statements are pure empty-initialization and are not observable. The byte-identical gate should pass for flag-off.

---

## Flag-ON-empty path: is it a TRUE no-op?

When `use_play_type_plugins=True` and `get_all_plugins()` returns `[]`:

- Wiring point 1: `if _registry_plugins:` is False → `_active_plugins` stays `[]`, no namespace created, no `detect_play_types` call. Correct.
- Wiring point 2: `if use_play_type_plugins and _active_plugins:` → `_active_plugins` is `[]` → block skipped. `_robot_accs` stays `{}`. Correct.
- Wiring points 3, 4+5: gated on `_robot_accs` being non-empty. Empty → both blocks skip. Correct.
- Wiring point 5 final spread: `_chunk_plugin_partial` is `{}` → no keys added. Correct.

Flag-ON-empty is a TRUE no-op. No observable difference vs flag-off. Byte-identical gate for flag-on-empty should pass.

**Residual: `RoundCtx` object is built but only if `_robot_accs` is non-empty (which requires `_active_plugins` non-empty). When registry is empty, `RoundCtx` is never built. Correct.**

---

## 10+ Stress Questions (specific file:line references)

1. **[parser.py:703-707]** `_active_plugins = [p for p in _registry_plugins if ...]` — if two plugins A (deps=("B",)) and B are registered, registration order might be [A, B]. Topo-sort wants [B, A]. `_active_plugins` gives [A, B]. At Commit C, `BCMFreespinAccumulator.on_round()` calls `peers["bcm_base"].state` — but bcm_base's accumulator hasn't fired yet because A fires before B. The `peers` dict is empty for A. Silent wrong behavior. Does the byte-identical gate catch this? NO — the gate runs Commit B (empty registry); it cannot catch a multi-plugin topo-order bug.

2. **[parser.py:2119-2127]** `RoundCtx.win_credits = int(r.get("WinCredits"))`. On M15 with `SettlementWinAmountRule`, `extract_round_win()` returns 0 for settlement rounds (win suppressed, attributed to trigger session). But `ctx.win_credits = int(r.get("WinCredits"))` reads the raw non-zero field. When `TopDollarPlugin.on_round()` reads `ctx.win_credits` to decide "is this a settlement round?", it gets the wrong signal. Does any test at Commit B catch this divergence? No — empty registry means no accumulator fires.

3. **[parser.py:2270]** `_chunk_plugin_partial.update(_robot_partial)` on 10 robots each returning `{"all_cycle_peaks": [peak1, peak2, ...]}`. Final `_chunk_plugin_partial["all_cycle_peaks"]` contains ONLY the last robot's peaks. The inline code at line 2295 uses `extend()` to accumulate all robots' peaks. With 10 concurrent workers each processing a different chunk, `_compute_bonus_correction` (which reads `all_cycle_peaks` from all chunks) would see only 1/10th of the expected cycle peak data per chunk. BCM RTP correction would be proportionally wrong. Does the byte-identical gate catch this? NOT AT COMMIT B. Requires the concrete accumulator (Commit C) + a multi-robot fixture.

4. **[parser.py:699-701]** `detect_play_types(...)` is called with `machine_id=""` and `mode=1`. If at Commit C the wiring adds config-write logic ("if no on-disk config, write the detected one"), all machines get config files with `machine_id=""`. This silently corrupts the config store. Is there a guard? No.

5. **[parser.py:699-715 ordering]** On M10 (cc=0), the pre-existing scan at lines 650-664 correctly sets `cost_credits_unreliable=True`. So `_chunk_parse_state` is initialized from the correct value. `detect_play_types` runs and evaluates LockRespinPlugin's signature with `cost_credits_unreliable=True` — correct. Then the probe runs again and sets the same value again — redundant but harmless. HOWEVER: what if a future probe detects something the pre-existing scan does NOT detect? That probe's result would not be available during `detect_play_types`. This is the structural bootstrapping problem. Is there a test asserting the probe→detection ordering? No — the framework tests (test_play_type_framework.py) test Commit A scaffolding; they don't test the wiring.

6. **[parser.py:678-715]** `get_all_plugins()` is called on every call to `parse_chunk_response`. `play_type_registry.ALL_PLAY_TYPE_PLUGINS` is a module-level mutable list. In a ThreadPoolExecutor with 10 concurrent workers, if a plugin registers itself at import time in one thread while another thread reads `get_all_plugins()`, is the list access thread-safe? Python's GIL makes list `append` and list iteration individually atomic, but a concurrent `register()` + `get_all_plugins()` could produce a partially-appended view. For Commit B (no concrete plugins, no registrations during processing), this is safe. For Commit C, if a plugin module is imported lazily in a worker thread, this is a race.

7. **[parser.py:1222]** `_PlayTypeMachineConfig(machine_id="", mode=0)` is constructed inside the robot loop. If there are 100 robots, 100 identical stub configs are constructed and discarded. This is wasteful. More importantly, at Commit C a concrete accumulator might call `machine_config.plugin_configs.get("my_plugin", {})` and silently receive `{}` (empty), using default parameters instead of the per-machine config. No crash, wrong behavior. Is there a test that would catch this? No — requires a concrete accumulator.

8. **[base_pipeline.py:632-638]** `run_sampling_chunk` passes `use_play_type_plugins=use_play_type_plugins` to `parse_chunk_response`. But `run_sampling_chunk` is submitted to `ThreadPoolExecutor` via `executor.submit(run_sampling_chunk, ..., use_play_type_plugins=getattr(args, ..., False))`. The keyword argument is passed correctly. Is there any `functools.partial` wrapping or other indirection that drops the kwarg? Looking at PIA line 2252-2286: direct `executor.submit(run_sampling_chunk, idx, ..., use_play_type_plugins=...)`. PASS — threading completeness confirmed for online path.

9. **[parser.py:2246]** `if use_play_type_plugins and _robot_accs:` — wiring points 4+5 are gated on `_robot_accs` being truthy. If wiring point 3 disabled ALL accumulators (all raised exceptions), `_robot_accs` becomes `{}` (all popped). Then `on_robot_end` and `to_chunk_partial` are never called for any accumulator. The chunk partial contributes nothing. Is this the right failure mode? For point 3 exceptions, yes — the accumulator was already broken. But for point 4 (`on_robot_end` exceptions), the code does `_robot_accs.pop(_fid, None)` and `continue` — it skips `to_chunk_partial` for the faulting acc. If `on_robot_end` faults on acc A but `to_chunk_partial` of acc A would have returned valid partial data (not all faults in `on_robot_end` mean the state is corrupt), silently skipping `to_chunk_partial` is a data loss. The design doc (EC-4) says this is acceptable, but the implementation's comment ("accumulator state is invalid") is an unverified assumption about `on_robot_end` faults.

10. **[parser.py: detect_play_types called per chunk]** In a 1000-chunk run with the concrete LockRespinPlugin, `detect_play_types` scans up to 5000 rounds from the first robot of EACH chunk. For 1000 chunks that's 5,000,000 rounds scanned just for detection — rounds that were already parsed once by the normal loop. Is this acceptable? At Commit B it doesn't execute. But the Commit B wiring puts no per-chunk detection behind any "already-detected" cache check. Every call to `parse_chunk_response` with flag-on re-detects from scratch. The byte-identical gate won't catch this because it only tests 2 chunks.

---

## Memory feedback violations

- **`feedback_no_silent_swallow.md`**: VIOLATED. Exception handlers in wiring points 3 and 4+5 print to stderr but do NOT persist a structured diagnostic key to the return dict. The comment at line 2160 falsely claims "written to return dict at finalize." The design doc (EC-4) explicitly requires `partial_attribution=True` in the chunk dict. The stderr print is insufficient for the batch worker path. (Finding #2.)
- All other cited memory files: no violations detected for the flag-off path.

---

## Verdict

**APPROVE-WITH-FIXES**

Commit B is safe to commit as-is for its stated purpose: flag-gated parse-loop wiring with an empty plugin registry. The byte-identical gate (flag-off and flag-on-empty) should pass. No existing behavior is perturbed.

However, two findings must be tracked as Commit C prerequisites or they will cause silent data corruption when the first concrete accumulator is registered:

### Required fixes before Commit C (not blocking Commit B)

1. **Fix topo-sort order** (Finding #1): rebuild `_active_plugins` from `_pt_config.active_plugins` in FID order (map back to instances via a lookup dict), not by filtering `_registry_plugins`.

2. **Fix per-robot partial merge** (Finding #6 / implementer concern #1): `_chunk_plugin_partial.update(_robot_partial)` MUST be replaced with accumulator-key-aware merge logic. List-valued keys (e.g. `all_cycle_peaks`) need `extend()`; int-valued keys (e.g. `collect_robots_seen_total`) need `+= `. The merge strategy is accumulator-type-specific and cannot be handled by a generic `dict.update()`.

3. **Fix EC-4 diagnostic persistence** (Finding #2): add `"_plugin_partial_attribution_errors": [...]` key to `_chunk_plugin_partial` when any accumulator faults. The comment at line 2160 ("written to return dict at finalize") is currently false and must become true.

4. **Fix RoundCtx fidelity** (Findings #4, #5): `win_credits` must be set from the rule-processed `win_amt` (as float or converted after rules run), not from `r.get("WinCredits")`. `authoritative_pay_ids` must be set from the rule-processed `pid_to_win.keys()`, not from `r.get("PayoutIdToWinAmount").keys()`. This requires making `win_amt` and `pid_to_win` available at wiring point 3, which they already are as local variables — the wiring just needs to reference them instead of re-reading `r`.

5. **Fix probe-before-detection ordering** (Finding #3): The bootstrapping problem is partially mitigated by the pre-existing cc-detection (which already runs before wiring point 1). But the structural fix is to run all probes first, THEN call `detect_play_types` with the updated `_chunk_parse_state`. Requires a two-pass approach or making the pre-existing cc-detection redundant by folding it into a probe that runs unconditionally.

### Optional improvements

1. Replace `getattr(args, "use_play_type_plugins", False)` with `args.use_play_type_plugins` (cleaner; the attribute always exists when PIA is invoked via `parse_args()`).
2. Move `import sys` to module top (it's already available; no reason for deferred import).
3. Cache the detected config per (machine, mode) across chunks rather than calling `detect_play_types` per-chunk.
4. Reuse `_sample_rounds` from the pre-existing cc-scan instead of calling `parse_rounds` a second time for `_probe_sample`.
5. Pass `machine_id` and `mode` to `detect_play_types` (threading requires making them available in `parse_chunk_response`'s signature or inferring from `resp` metadata).
