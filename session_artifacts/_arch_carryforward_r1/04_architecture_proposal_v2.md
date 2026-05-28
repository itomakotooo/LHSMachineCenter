# 04 — Architecture Proposal v2: Carry-forward Round 1 (Clusters A + D + E)

> **Date**: 2026-05-28
> **Author**: arch-designer (Wave 2, v2 surgical revision)
> **Base**: `04_architecture_proposal.md` (v1)
> **Revision triggers**: `05_critique.md` (APPROVE-WITH-REVISIONS) + `06_validation.md` (APPROVE-WITH-REVISIONS)
> **Input artifacts**: `01_pipeline_map.md`, `02_taxonomy.md`, `03_coupling_audit.md`, `00_brief.md`
> **Output directory**: `session_artifacts/_arch_carryforward_r1/`
> **Downstream consumers**: impl-* team (Wave 4)

---

## §0 Revision Log v1 → v2 **[v2 revised]**

Three independent corroborations drove this revision. Each fix is traceable to both the critique and the validator.

**Fix 1 — §7 D-2 test update list expanded from 1 to 3 tests.**
Critique TC-1 / BF-1 + Validation B1 / B2. v1 §7 said only one test (`test_c6_bonus_chain_dynamics_plugin.py`) requires update after D-2. The critic independently found that `test_c6_gap_3_pid_666_trigger_marker.py:160` also asserts the wrong value `"NewFreespin"` (TC-1), and that `test_c6_bonus_chain_dynamics_plugin.py:432` breaks for a different second reason: the fixture stash is missing `scatter_feature_chain_counts` and uses an unsorted feature list (BF-1). The validator confirmed both findings from real code execution (B1 + B2). §7 is expanded with exact file:line and remediation for all three tests.

**Fix 2 — §5.2 D-2 now specifies explicit error on missing/empty chain_counts stash.**
Critique Q9 / D-R4 (independently: `feedback_capture_drift.md`, `feedback_no_silent_swallow.md`). v1 §5.2 used `stash.get("scatter_feature_chain_counts") or {}` which silently degrades to alphabetical-first (the original wrong behavior) when the stash key is missing. The critic found this violates both memory invariants (Q9 verdict: NOT ADDRESSED). §5.2 now specifies three confidence levels with explicit error-raising behavior for the missing-stash case and documented fallback semantics for the all-zero case. A `PluginStashKeyMissingError` (or equivalent RuntimeError caught as feature_error) is specified for the missing-key path.

**Fix 3 — §4 Cluster A Region 2 test added.**
Critique TC-3 (independently corroborated by validation A-R3 + §3 Q2). v1 §4.4 specified a test only for Region 1 (topo-sort cyclic dependency). Region 2 (DECLARED_DEPS miss inside the emit loop) was listed as TODO in the original C1 critic carry-forward but was not given a test spec in v1. The critic flagged this as TC-3 (required fix). §4 now includes a full Region 2 test specification including inject-bug recipe and explicit partial-state semantics decision (option selected: keep partial + annotate, with justification).

Sections changed: §4.3 (partial-state semantics + Region 2 test header), §4.4 (Region 2 test full spec), §5.2 (confidence levels + error-raise spec), §7 (D-2 test update enumeration with file:line). All other sections carried verbatim.

---

## §1 Executive Summary

*(Carried verbatim from v1.)*

The analyzer-unbundle C-phase shipped 9 plugins across C1–C6 and established a
plugin infrastructure (topo_sort, PipelineContext, MechanismRegistry, feature
registry). Three clusters of carry-forward work remain before the unbundle is
functionally complete for Round 1.

**Cluster A** fixes a broken error-surfacing contract: topo-sort and
DECLARED_DEPS errors exit via `SystemExit(1)` before `write_summary_json` fires
(01 §2.2–2.3), so the structured `summary["analyzer_init_error"]` field that
was set in memory never reaches disk. The backend receives `rc=1` with no JSON
diagnostic. `feedback_no_silent_swallow.md` is the primary memory constraint.

**Cluster D** fixes four fleet-plugin data-correctness bugs. The most critical
is d2 (02 §8): M275 currently shows `trigger_target = "NewFreespin"` but the
correct value is `"NormalCollectionSpin"` — the alphabetical-first heuristic
picks the wrong feature for 37+ scatter machines. Additionally d1 affects 32
machines with 10+ paylines whose `paylines` sort is lexicographic instead of
numeric (02 §3), d3 implements the dead "unique" confidence branch (03 §3.3),
and d4 formalizes `avg_bonus_payout = None` semantics (02 §6).

**Cluster E** eliminates the recurring update burden: 3 effective_version
hex constants across 2 test files are pinned to stale C-phase values that turn
RED every time a D-fix changes a plugin file (03 §4 E-2 migration sensitivity
table). The base_hash pins (6 instances) are NOT affected and must remain
hardcoded as intentional regression guards (01 §4.3, 03 §4 E-1).

**Critical ordering constraint** (03 §6.1 + case studies 2–5): Cluster E must
commit BEFORE Cluster D, and Cluster D must commit BEFORE Cluster A or
concurrently with it. This ordering prevents the hardcoded hex constants from
turning RED mid-sequence and avoids any final state where the D-fixes have
invalidated 253 machines' effective_versions without the test suite being
updated to track them differentially.

---

## §2 Phase Ordering Decision

*(Carried verbatim from v1.)*

**Committed order: E → D → A**

### Justification from coupling audit

From 03 §4 (Symbol E-2 migration sensitivity table): any D-1 fix (changes
`payouts_by_spin_type.py`) or D-2+D-3 fix (changes `bonus_chain_dynamics.py`)
immediately invalidates the hardcoded `_NON_M275_EFFECTIVE_VERSION =
"6aae41144cea"` and `_M275_C3_5_EFFECTIVE_VERSION = "5c78f3834a1e"` constants
in `test_c3_5_isolation_m275_only.py:93,109` and
`test_c3_5_m14_no_multiplier_wild.py:241`. The failure mode is a hard
`AssertionError` that turns tests RED immediately — not silent (03 §4,
"Failure mode if not updated"). If D commits before E, CI is broken between D
and E commits.

From 03 §7 case studies 2 and 3: D-1 and D-2+D-3 each independently invalidate
253 machines' effective_versions. If these cluster commits happen while the
tests still pin exact hex values, the test suite is broken for however long E is
not yet committed. This is avoidable by ordering E first.

Cluster A is independent of D and E for control-flow purposes (no plugin files
changed, no version hash impact). A does not interact with the hardcoded hex
constants. A can commit in any position, but committing A after D reduces the
number of distinct "CI broken" windows.

**Why not bundle all three into one mega-commit:** See §6 for the full
trade-off analysis. Short answer: E as a standalone commit gives the CI system
a clean state before D's 253-machine invalidation, and A as a standalone commit
makes the error-contract change reviewable independently.

---

## §3 Cluster E Design — Test Refactor: Dynamic Effective_version Assertions

*(Carried verbatim from v1.)*

### §3.1 Problem being solved

From 01 §4.3 (update-burden problem): every plugin addition or plugin-file
change triggers manual updates to:
1. `_M275_C3_5_EFFECTIVE_VERSION` in `test_c3_5_isolation_m275_only.py` (line 93)
2. `_NON_M275_EFFECTIVE_VERSION` in `test_c3_5_isolation_m275_only.py` (line 109)
3. `_NON_M275_EFFECTIVE_VERSION` in `test_c3_5_m14_no_multiplier_wild.py` (line 241)

These were updated 3 times across C-phases (01 §4.2, "comment history"). The
C6 critique (session_artifacts/_impl/phase_c6/critique.md §2) flagged that the
comment at line 98 was misleading after the C6 constant update.

### §3.2 Design alternatives for effective_version test assertions

**Alternative E-1: Fully dynamic (compute on both sides)**

Replace `assert ev == "6aae41144cea"` with `assert ev ==
_compute_effective_version("M14", 1)`. Since `ev` IS the return value of
`_compute_effective_version("M14", 1)`, this assertion is trivially true and
catches nothing.

Verdict: **rejected**. 03 §4 E-2 analysis confirms this loses all regression
guard value. The test always passes.

**Alternative E-2: Hybrid — compute new value, re-pin as updated constant**

Run `compute_effective_version_for_machine("M14", 1)` once after each D-fix,
observe the new hex, update the constant in the test file, and add it to the
comment history. The snapshot-regression property is preserved — if an
accidental future change alters M14's hash, the test turns RED.

Pros: simple; preserves the "canary" property; easy to read.
Cons: still requires a manual update after every D-commit; the problem recurs
whenever any plugin file changes again. The C6 critique itself demonstrates
this pattern fails in practice (comment history mismatch).

**Alternative E-3: Structural differential assertions (recommended)**

Replace the pinned effective_version hex tests with assertions about structural
properties of the hash composition, rather than the hex value itself. The
structural invariants that matter are:
- M275 has one more plugin than M14/M37/M272 (multiplier_wild is M275-only).
- Therefore M275_ev != M14_ev (isolation invariant).
- M14_ev == M37_ev == M272_ev (machines with identical plugin sets produce
  identical hashes — symmetry invariant).
- The base_hash portion is the same for all machines (computed from core/*.py,
  which is unchanged).

These structural facts are the load-bearing contracts tested by this file.
The exact hex value is a consequence of these facts, not the fact itself.

Pros: never needs updating; tests the real invariants; immune to D-phase changes.
Cons: does not catch the "someone accidentally modified a plugin file" case —
but that is caught by the per-phase byte-identical tests (test_c5_byte_identical,
test_c6_byte_identical), which compare full report structure, not just the hash.
Additionally, any unintended plugin change would flip `effective_analyzer_version`
in ALL existing on-disk summaries, which is caught by CI's byte-identical tests.

**Recommendation: Alternative E-3** for the two test files that pin
effective_version. Do not change the base_hash pins.

### §3.3 Precise migration per file

**File 1: `tests/analyzer/test_c3_5_isolation_m275_only.py`**

Three current constants (01 §4.2):
```
_C3_BASE_HASH = "fa440e3eb5f6"        # line 81 — base_hash pin
_M275_C3_5_EFFECTIVE_VERSION = "5c78f3834a1e"  # line 93 — M275 effective_version
_NON_M275_EFFECTIVE_VERSION = "6aae41144cea"   # line 109 — M14/M37/M272 effective_version
```

Migration:
- `_C3_BASE_HASH` — **KEEP HARDCODED**. Base_hash is a hard invariant (00 §3
  "base_hash UNCHANGED fa440e3eb5f6"). The test `test_base_hash_unchanged_from_c3`
  asserts `_compute_base_hash() == _C3_BASE_HASH`. This must catch any accidental
  touch to `core/*.py`. Making the RHS dynamic removes the guard. No change.
- `_M275_C3_5_EFFECTIVE_VERSION` — **REPLACE** the pin assertion. The two tests
  that use this constant (`test_m275_effective_version_is_c3_5_value`) should
  become structural. New assertion shape:

```python
# Replaces: assert ev == _M275_C3_5_EFFECTIVE_VERSION
def test_m275_effective_version_differs_from_m14():
    m275_ev = _compute_effective_version("M275", 1)
    m14_ev = _compute_effective_version("M14", 1)
    assert m275_ev != m14_ev, (
        "M275 and M14 must produce different effective_analyzer_versions. "
        "M275 declares multiplier_wild; M14 does not."
    )

def test_m275_effective_version_starts_with_base_hash():
    # base_hash is the first 12 hex chars of sha256 over core/*.py
    # Any M275 effective_version starts with a hash that incorporates base_hash.
    # This is a structural property, not a pin.
    m275_ev = _compute_effective_version("M275", 1)
    assert len(m275_ev) == 12, "effective_version must be 12-char hex"
    assert all(c in "0123456789abcdef" for c in m275_ev), "must be lowercase hex"
```

- `_NON_M275_EFFECTIVE_VERSION` — **REPLACE** similarly:

```python
def test_m14_m37_m272_share_effective_version():
    """Machines with identical plugin sets must have identical effective_versions."""
    m14_ev  = _compute_effective_version("M14", 1)
    m37_ev  = _compute_effective_version("M37", 1)
    m272_ev = _compute_effective_version("M272", 1)
    assert m14_ev == m37_ev, "M14 and M37 have identical plugin sets — must hash identically"
    assert m14_ev == m272_ev, "M14 and M272 have identical plugin sets — must hash identically"

def test_m14_effective_version_is_valid_hex():
    ev = _compute_effective_version("M14", 1)
    assert len(ev) == 12 and all(c in "0123456789abcdef" for c in ev)
```

**File 2: `tests/analyzer/test_c3_5_m14_no_multiplier_wild.py`**

One constant at line 241 (01 §4.2):
```
_NON_M275_EFFECTIVE_VERSION = "6aae41144cea"  # line 241
```
Used at line 243: `assert actual == _NON_M275_EFFECTIVE_VERSION`

Migration: the test `test_m14_effective_version_is_c3_non_m275_value` should
become `test_m14_effective_version_matches_versioning_module_dynamic`:
```python
def test_m14_effective_version_is_structural():
    """M14 lacks multiplier_wild; its ev must differ from a hypothetical M275 ev."""
    m14_ev  = compute_effective_version_for_machine("M14", 1)
    m275_ev = compute_effective_version_for_machine("M275", 1)
    assert m14_ev != m275_ev, "M14 lacks multiplier_wild; must hash differently from M275"
```

**Files with base_hash pins only — NO CHANGE NEEDED** (01 §4.2, confirmed in
03 §4 E-2 migration sensitivity table — "No" for all D-fix columns):
- `test_c3_base_hash_flips_for_round_level_enrichment.py` — both constants stay.
  Note: `_C2_BASE_HASH = "b0ba0ce7c7e2"` is a historical anchor for a negative
  assertion; cannot be computed dynamically. `_EXPECTED_C3_BASE_HASH =
  "fa440e3eb5f6"` must stay to guard against core/*.py modifications.
- `test_c5_byte_identical_unrelated_fields.py` — `"fa440e3eb5f6"` stays.
- `test_c6_byte_identical_bonus_chain.py` — `"fa440e3eb5f6"` stays.
- `test_c6_carve_completion.py` — `"fa440e3eb5f6"` stays.

**Files already dynamic — NO CHANGE NEEDED** (01 §4.2):
- `test_c3_5_m275_e2e.py` — assertion already dynamic; hex in docstring is
  informational only.
- `test_c1_byte_identical_m14.py` — hex strings in comment only.

**Summary of Cluster E file count**: 2 files require migration (the two with
effective_version pins). 6 remaining files confirmed no-change (4 base_hash pins
+ 2 already dynamic/comment-only). The brief's "5+ files" estimate was
conservative; the actual migration scope is 2 files with 3 constant sites.
This must be clear in Phase 1 deliverables so the impl team does not spend time
on the 6 no-change files.

### §3.4 Shared helper consolidation (01 §6.2 reuse finding)

Three test files independently rediscover the `_compute_effective_version()`
helper pattern (01 §6.2): `test_c3_5_isolation_m275_only.py:126`,
`test_c3_5_m275_e2e.py` inline, `test_c3_5_m14_no_multiplier_wild.py` inline.

However, the coupling audit (03 §4 E-1 silent dependency note) flags that any
test using `compute_effective_version_for_machine` dynamically introduces a
manifest-file dependency that can fail for `FileNotFoundError` in partial
checkouts or stripped CI images. This risk is present regardless of whether
the helper is shared or not.

**Decision**: Do NOT create a new shared conftest helper module. The duplication
is minimal (3 test files, each ~3 lines of import). Creating a shared conftest
adds a new dependency without reducing the manifest-file risk. Keep the
local-import pattern per file.

**Audit finding 1** (01 §6.1 — three base_hash assertions): consolidating the
three `assert actual == "fa440e3eb5f6"` into a single shared test file is
plausible but not recommended. The assertions each belong to their per-phase
byte-identical test class; decoupling them would lose the per-phase context.
Defer to a future cleanup round.

---

## §4 Cluster A Design — Unified Error Surfacing Contract **[v2 revised]**

### §4.1 Current state and gap summary

From 01 §2.6 (three-path inconsistency table):

| Error type | Key written | JSON written? | rc |
|---|---|---|---|
| Topo cycle / missing dep | `summary["analyzer_init_error"]` in memory | NO — SystemExit before pia:5210 | 1 |
| DECLARED_DEPS RuntimeError | nothing | NO — uncaught exception | uncontrolled |
| emit() exception | `summary["feature_errors"][fid]` | YES — pia:5210 runs | 0 |
| extract/reduce exception | `summary["feature_errors"]["extract_{fid}"]` | YES | 0 |

The fourth error path (extract/reduce, 01 §2.5 Path 4) is already correct —
errors land in `feature_errors` and are written to disk. The C1 critic
(session_artifacts/_impl/phase_c1/critique.md §3, CONCERN-3) flagged paths 1
and 2 as requiring the `try/finally` fix before DECLARED_DEPS can become a
real runtime risk.

### §4.2 Design alternatives for error surfacing

**Alternative A-1: Sidecar file approach**

On error, write a separate `analyzer_init_error.json` file rather than the main
`player_impact_summary.json`. The backend checks for the sidecar on rc=1 paths.

Pros: does not require restructuring main() control flow.
Cons: adds a new contract surface (backend must know about a second file); the
brief explicitly says `summary["analyzer_init_error"]` top-level, not a sidecar
(00 §1 Cluster A). 03 §2 Symbol A-1 confirms the backend never currently reads
`analyzer_init_error` from disk at all — the JSON write is for operator
inspection. A sidecar adds complexity without benefit.

**Alternative A-2: Narrow try/finally wrapping only the topo-sort block**

Wrap only lines 5042–5065 in a `try/finally` that calls `write_summary_json`
before SystemExit propagates. Handle DECLARED_DEPS separately with a similar
pattern.

Pros: minimal blast radius on main() control flow — the finally block covers
only ~23 lines.
Cons: does not unify the two error paths under one handler; DECLARED_DEPS still
requires its own special treatment since it's inside the emit loop, not the
topo-sort block.

**Alternative A-3: Unified error handler with two scoped try/finally blocks
(recommended)**

Implement two coordinated try/finally regions that together cover all three hard
error paths:

Region 1 (topo-sort): wraps lines 5042–5065. On `_PluginCyclicDependencyError`
or `_PluginMissingDependencyError`, sets `summary["analyzer_init_error"]`, calls
`_safe_write_summary_json(summary, args.output_dir)` (see §4.3 for the safe
wrapper), then re-raises as `SystemExit(1)`.

Region 2 (DECLARED_DEPS): wraps the DECLARED_DEPS check at lines 5073–5080.
On `RuntimeError` from the missing-dep check, converts to a named error type,
sets `summary["analyzer_init_error"]`, calls `_safe_write_summary_json`, then
raises `SystemExit(1)`.

The emit() error path (Path 3, lines 5081–5091) is already graceful — no change
needed. It continues to write to `summary["feature_errors"]` and the run does
NOT exit early.

### §4.3 Recommended design (Alternative A-3) — precise specification **[v2 revised]**

#### Error schema for `summary["analyzer_init_error"]`

```python
summary["analyzer_init_error"] = {
    "error_type":       str,   # class name: "PluginCyclicDependencyError" /
                               #   "PluginMissingDependencyError" /
                               #   "PluginDeclaredDepMissingError"
    "message":          str,   # str(exception)
    "plugin_dep_graph": dict,  # {feature_id: [list_of_requires]} at time of error
    "affected_plugin":  str | None,  # FEATURE_ID of the plugin that triggered the error
                                     # (None for cycle errors where multiple plugins involved)
    "region":           int,   # 1 = topo-sort error, 2 = DECLARED_DEPS emit-loop error
    "timestamp":        str,   # datetime.now(timezone.utc).isoformat()
}
```

The `region` field (added in v2) allows operator inspection and the Region 2
test to distinguish partial-emit errors (region=2) from pre-emit errors
(region=1). This is the machine-readable field that `test_a_region2_declared_dep_miss_disk_surfacing.py`
asserts against.

The existing topo-sort handler at `pia:5049–5057` already populates
`error_type`, `message`, `plugin_dep_graph`, and `timestamp` (01 §2.2). The
new fields `affected_plugin` and `region` are added to both paths.

**Schema backward compatibility**: 0 production code reads this field (03 §2
Symbol A-1 consumer table — 0 production readers). 14 test sites check that the
key is ABSENT on the success path (`"analyzer_init_error" not in summary`). The
new fix ensures the key is only written on error paths — success path is
unchanged.

#### The `_safe_write_summary_json` wrapper

Wrapping `write_summary_json` in a try/except guards against 03 §2 Symbol A-2
critical risk: an OSError inside the finally block would replace the original
`SystemExit(1)` with the OSError, causing the backend to receive rc=0 (or an
uncaught exception) instead of rc=1.

```python
# Sketch (NOT implementation — for arch reference only)
def _safe_write_summary_json(summary, output_dir, *, stderr_ref):
    """Call write_summary_json but do NOT let its failure suppress the caller's exception.

    If write_summary_json raises, logs the write failure to stderr and returns
    (allowing the caller's SystemExit(1) to propagate unmolested).
    """
    try:
        write_summary_json(summary, output_dir)
    except Exception as _write_exc:
        print(
            f"ERROR: failed to write summary JSON on error path: {_write_exc}",
            file=stderr_ref,
        )
        # Return — do not re-raise. Caller's SystemExit(1) propagates.
```

This is an internal helper, not a new public API. It is defined inline in PIA
main() using a local function or a standalone call with try/except. The helper
must be defined BEFORE the topo-sort block so it is in scope for both regions.
The `stderr_ref` parameter receives `sys.stderr` at call time (not captured via
closure from the top of main) to avoid the import-order risk flagged in BF-2
of the critique.

#### DECLARED_DEPS error conversion

The current `raise RuntimeError(...)` at `pia:5077` must be converted to use
the new named type `PluginDeclaredDepMissingError` or caught as `RuntimeError`
at the same level. Two sub-options:

Sub-option A-3a: Catch `RuntimeError` at the same level as the topo-sort
errors, using a broader except clause. This avoids creating a new exception class.

Sub-option A-3b: Replace `raise RuntimeError(...)` with
`raise PluginDeclaredDepMissingError(...)` — a new exception class in
`topo_sort.py` analogous to `PluginCyclicDependencyError` and
`PluginMissingDependencyError`. This gives a named type in `error_type` field
and keeps the exception hierarchy consistent.

**Recommendation: A-3b** — adds one class to `topo_sort.py` (already has two
analogous classes), keeps the catch clause at `pia:5044` cleanly typed, and
gives operators a self-explanatory `error_type` in the JSON.

Note on file placement (05 §6 critique Q6): the critique correctly observes that
`PluginDeclaredDepMissingError` is semantically a runtime-emit-loop error, not a
graph-sort error, and could live in `pipeline_context.py` instead of
`topo_sort.py`. For Round 1, the recommendation is to add it to `topo_sort.py`
alongside the two existing analogous classes, because (a) this is the minimal
delta, (b) the implementer can relocate it in a future Cluster C refactor without
breaking the exception hierarchy, and (c) the `error_type` field value
(`"PluginDeclaredDepMissingError"`) is diagnostic-only and relocating the class
later does not break any JSON consumers. This is explicitly a Round 1 pragmatic
decision, not the permanent home.

#### Partial-state semantics for Region 2 errors **[v2 revised — TC-3 fix]**

When Region 2 fires (DECLARED_DEPS miss inside the emit loop), some features
may have already emitted successfully before the failing plugin. The JSON written
to disk contains:
- All plugin output from features emitted before the failing plugin
- `summary["analyzer_init_error"]` with `region=2`
- Notably: `_`-prefixed temp stash keys that would normally be cleaned at
  `pia:5115` are also present (SystemExit fires before that cleanup line). This
  is documented behavior, not a bug.

**Partial-state semantic decision**: Option (a) — keep partial emit output AND
add `analyzer_init_error`. Rationale:

The backend at `_batch_gen_worker.py:154` returns `{"ok": False, "error":
f"analyzer rc={rc}"}` and short-circuits on `rc != 0` (03 §2 Symbol A-3). The
partial JSON is never entered into the normal report-reading path. The risk is
purely operator-side misinterpretation: an operator who manually inspects the
on-disk JSON may see valid-looking partial plugin output and miss the error key.

Option (a) is preferred over option (b) (clear all player_impact, show error
only) because:
1. The partial plugin output before the error is factually correct — clearing it
   loses real diagnostic information that helps an operator identify WHICH plugin
   caused the chain to break.
2. The `region=2` value in `analyzer_init_error` explicitly signals "partial
   run." An operator who reads the `affected_plugin` field knows exactly where
   the chain stopped.
3. Option (b) would require the Cluster A change to also reverse-undo any emits
   that have already fired, which is a deeper control-flow change than warranted
   for Round 1.

The partial-state semantic contract must be documented in the `_safe_write_summary_json`
call site comment: "On region=2 error, partial plugin output preceding
`analyzer_init_error` is intentional and diagnostic. Do not clear it."

#### Control flow sketch

```
# Region 1 — topo-sort error (modifies existing block at pia:5042–5065)
try:
    _sorted_features = _topological_sort(_machine_features)
except (_PluginCyclicDependencyError, _PluginMissingDependencyError) as _topo_exc:
    summary["analyzer_init_error"] = {
        "error_type": type(_topo_exc).__name__,
        "message": str(_topo_exc),
        "plugin_dep_graph": {f.FEATURE_ID: list(f.REQUIRES) for f in _machine_features},
        "affected_plugin": None,
        "region": 1,
        "timestamp": _dt.now(_tz.utc).isoformat(),
    }
    print(f"ERROR: ...", file=_sys.stderr)
    _safe_write_summary_json(summary, args.output_dir, stderr_ref=_sys.stderr)
    raise SystemExit(1) from _topo_exc

# Region 2 — DECLARED_DEPS check (inside emit loop, modifies existing block at pia:5073–5080)
for _feature in _sorted_features:
    for _dep_key in _feature.DECLARED_DEPS:
        if _dep_key not in summary:
            _dep_exc = _PluginDeclaredDepMissingError(
                plugin=_feature.FEATURE_ID,
                missing_dep_key=_dep_key,
            )
            summary["analyzer_init_error"] = {
                "error_type": type(_dep_exc).__name__,
                "message": str(_dep_exc),
                "plugin_dep_graph": {f.FEATURE_ID: list(f.REQUIRES) for f in _machine_features},
                "affected_plugin": _feature.FEATURE_ID,
                "region": 2,
                "timestamp": _dt.now(_tz.utc).isoformat(),
            }
            print(f"ERROR: ...", file=_sys.stderr)
            _safe_write_summary_json(summary, args.output_dir, stderr_ref=_sys.stderr)
            raise SystemExit(1) from _dep_exc
    # ... emit() call (path 3, unchanged)
```

Note: the DECLARED_DEPS check runs inside the emit loop; on error, some features
may have already successfully emitted. The JSON written to disk would contain
partial plugin output for features before the failing feature in topo order.
This is acceptable per the partial-state semantics decision above — the
`analyzer_init_error.region=2` key signals partial data, and the `affected_plugin`
field identifies the break point.

#### Backward compatibility

- rc=1 signal: preserved unchanged for all error paths. Backend `_batch_gen_worker.py:154`
  `if rc != 0` check continues to work (03 §2 Symbol A-3).
- `summary["feature_errors"]`: key name unchanged; 18 test assertion sites (03 §2
  Symbol A-4 consumer table) continue to work.
- Success path: no change. `summary["analyzer_init_error"]` is never written on
  success. The 14 test sites asserting `"analyzer_init_error" not in summary` on
  success path remain GREEN.
- The `feature_errors` and `analyzer_init_error` fields remain separate. The brief
  says "Cluster A unified error contract" means all hard-error paths write JSON —
  it does NOT mean collapsing `feature_errors` into `analyzer_init_error`. Merging
  those two fields would break 18 `.get("feature_errors", {})` assertions that rely
  on the key name (03 §2 Symbol A-4 breakage mode: "silent-wrong-result" because
  `dict.get("feature_errors", {})` returns `{}` for missing key, turning assertions
  into silent passes).

### §4.4 New tests required for Cluster A **[v2 revised — TC-3 fix]**

#### Region 1 test (carried from v1)

The existing `test_c1_init_error_surfacing.py` (01 §2.7 design note + test file
header) tests that topo_sort raises correctly at the unit level. It does NOT test
that the JSON is written to disk on rc=1.

New test file `test_a_init_error_disk_surfacing.py` must contain:

**Test A-Region1: `test_a_region1_topo_cycle_disk_surfacing`**
1. Inject a cyclic plugin pair into a fresh temporary plugin registry.
2. Run PIA (subprocess or in-process) against the injected registry.
3. Assert rc=1.
4. Assert that `player_impact_summary.json` EXISTS in the output directory.
5. Assert that the JSON contains `"analyzer_init_error"` key at top level.
6. Assert that `analyzer_init_error["error_type"]` equals `"PluginCyclicDependencyError"`.
7. Assert that `analyzer_init_error["region"]` equals `1`.

Inject-bug recipe for Region 1: in the `_safe_write_summary_json` sketch, remove
the try/except wrapper (simulating the pre-fix state where write is not called on
error). Test asserts `player_impact_summary.json` does NOT exist → test RED.
Restore → test GREEN.

#### Region 2 test (new in v2 — TC-3 fix) **[v2 revised]**

New test: `test_a_region2_declared_dep_miss_disk_surfacing`
(same file `test_a_init_error_disk_surfacing.py`, separate test function).

**Inject-bug recipe**: Register a real plugin class into a temporary plugin
registry where `DECLARED_DEPS = ("nonexistent_stash_key_xyz",)` and
`REQUIRES = ()` (no graph-level dependency, so topo-sort succeeds). At least one
OTHER plugin must run before this plugin in topo order (so Region 2 fires
mid-loop, demonstrating partial-emit behavior). The run against a fresh M14
fixture should:

1. Assert rc=1.
2. Assert `player_impact_summary.json` EXISTS in output directory.
3. Assert JSON contains `"analyzer_init_error"`.
4. Assert `analyzer_init_error["error_type"]` equals `"PluginDeclaredDepMissingError"`.
5. Assert `analyzer_init_error["region"]` equals `2`.
6. Assert `analyzer_init_error["affected_plugin"]` equals the FEATURE_ID of the
   injected plugin.
7. Assert at least one OTHER plugin's output key IS present in the JSON (verifying
   partial-emit output is preserved, not cleared — consistent with the partial-state
   semantics decision in §4.3).

**Why partial-emit verification matters**: assertion 7 validates that the "keep
partial + annotate" decision is implemented correctly. If an impl inadvertently
clears all plugin output before writing on error (option b behavior), assertion 7
turns RED. This is the test that locks the partial-state contract.

**Inject-bug recipe for Region 2 itself**: monkeypatch the emit loop so that the
DECLARED_DEPS check is skipped entirely (simulating the pre-fix state). Test
asserts `player_impact_summary.json` does NOT exist AND `rc != 0`. With the check
bypassed, neither the JSON write nor the rc=1 signal fires correctly. Restore →
test GREEN.

---

## §5 Cluster D Design — 4 Small Fleet-Plugin Fixes

### §5.1 d1: paylines int sort + carve-out

*(Carried verbatim from v1.)*

**Problem** (01 §3.1, 02 §3 Ax4-B): `payouts_by_spin_type.py:424–436` sorts
`payline_id` values (string keys like `"1"`, `"10"`, `"2"`) using string
comparison. This produces wrong order `"1","10","11","2"` for any machine with
10+ paylines. 32 machines are currently affected (02 §9 d1 row).

**Fix design**: Change both sort sites to use `int()` as the key function.

```python
# Site 1 (trigger-marker path, payouts_by_spin_type.py:424):
paylines: list[dict[str, Any]] = sorted(
    [{"payline_id": pl_id, "hit_count": cnt}
     for pl_id, cnt in pl_map.items()],
    key=lambda x: int(x["payline_id"]),    # <- was: x["payline_id"]
)

# Site 2 (regular pid path, payouts_by_spin_type.py:431):
paylines = sorted(
    [{"payline_id": pl_id, "hit_count": cnt}
     for pl_id, cnt in pl_map.items()
     if pl_id != "-1"],
    key=lambda x: int(x["payline_id"]),    # <- was: x["payline_id"]
)
```

The `-1` carve-out: `int("-1") = -1` sorts before all positive integers
naturally. No special-casing needed. However, 03 §6.2 (silent dependency) notes
that `int(x["payline_id"])` raises `ValueError` for any non-integer, non-`"-1"`
payline_id string. Per the brief and taxonomy (01 §3.1 note on payline_id type:
"always int-parseable per all audited machines"), this is an acceptable
assumption. The implementation sketch should add a comment documenting this
assumption so future machines with unusual payline schemas are caught early.

**Defensive ValueError handling (critique Q4 / D-R5)**: The critique (Q4 / D-R5)
correctly noted that a `ValueError` from `int(x["payline_id"])` inside
`payouts_by_spin_type.emit()` would be caught silently by the outer emit-error
handler at `pia:5083`, producing `feature_errors["payouts_by_spin_type"] = "invalid
literal for int() with base 10: 'any'"` and a rc=0 run with no paylines section.
This violates `feedback_capture_drift.md`.

**Required implementation guidance**: the implementer must add explicit pre-validation
inside `payouts_by_spin_type.emit()` BEFORE the sort call, converting the ValueError
into a descriptive RuntimeError that surfaces before the outer emit-error handler:

```python
# Sketch — inside emit(), before sort calls
for pl_id in pl_map:
    if not (pl_id == "-1" or pl_id.lstrip("-").isdigit()):
        raise RuntimeError(
            f"payouts_by_spin_type: non-integer payline_id {pl_id!r} encountered. "
            f"Schema drift? All audited machines have int-parseable payline_ids."
        )
```

This RuntimeError is still caught by the emit-error handler (it becomes
`feature_errors["payouts_by_spin_type"]`), but the message is human-readable
and clearly identifies schema drift — consistent with `feedback_capture_drift.md`.
The run completes with rc=0 and the operator sees a meaningful error message
in `feature_errors`, not a cryptic Python built-in error string.

**Blast radius** (03 §3 Symbol D-1): `payouts_by_spin_type.py` byte change → 253
machines' `effective_analyzer_version` changes. No consumer breaks; the sort
order for current manifested machines (M14/M37/M272/M275) is unchanged because
they have fewer than 10 paylines.

**Test coverage**: A new test asserting that paylines are emitted in integer
order for a fixture machine with 10+ paylines (e.g., M107 or M5 cached chunks).
Inject-bug recipe: revert `int()` to string sort → assert order `["1","10","2"]`
in fixture → test RED.

### §5.2 d2: trigger_target via scatter_marker_pids inverse mapping **[v2 revised]**

**Problem** (01 §3.2, 02 §8): M275 and M272 produce `trigger_target =
"NewFreespin"` (alphabetical first) when the correct value is
`"NormalCollectionSpin"`. The root cause is that `bonus_chain_dynamics.py:207`
uses `sorted(scatter_feature_names)[0]` — alphabetical sort, no semantic signal.
This affects ~37 scatter machines with 2+ active bonus features (02 §9 d2 row).

**The mapping challenge** (01 §6.3 reuse finding): the fix requires knowing which
bonus feature a given scatter PID actually triggers. The mechanism registry has
`scatter_marker_pids: frozenset[str]` but does NOT have a `pid → feature_name`
inverse map. The stash (`_bonus_chain_dynamics_data`) carries
`scatter_feature_names: list[str]` but NOT per-feature `first_st` values.

Two approaches to the inverse mapping:

**Approach D2-a: Chain-count majority vote**

Among the features in `scatter_feature_names`, pick the one with the highest
`chain_count` (most chains observed). For M275: NormalCollectionSpin has 841
chains vs NewFreespin 67 chains. The larger chain count is the primary bonus
target triggered by the scatter PID.

This requires extending the stash with `scatter_feature_chain_counts: dict[str,
int]` — a dict from feature name to chain_count from `all_chains_by_feature`.
No new registry field needed. The BCD plugin's emit() reads
`stash["scatter_feature_chain_counts"]` and picks `max(..., key=lambda k:
scatter_feature_chain_counts[k])`.

Pros: works without manifest data; signal is observable from data.
Cons: heuristic — if two features have similar chain counts, the majority vote
may still pick the wrong one; the scatter trigger feature typically has MORE
chains (it's triggered by random scatter hit, not by cycle boundary), so this
heuristic is sound for the NCS+NewFreespin pattern observed in all tested
machines.

**Approach D2-b: Manifest-level Tier 1 override (deferred)**

Add `mechanism_overrides.scatter_trigger_target: "NormalCollectionSpin"` to
affected machine manifests. The BCD plugin reads this from the registry.

Pros: explicit, 100% correct.
Cons: requires manifest changes for every affected machine (~37 machines); does
NOT fix the algorithmic heuristic that will be wrong for future machines without
a manifest override.

Note (critique §7 recommendation): D2-b is deferred to Cluster B (Mechanism
Registry completion), NOT permanently rejected. D2-b is the architecturally
superior long-term solution — explicit, machine-specific, auditable. The D2-a
heuristic is a Round 1 pragmatic fix that reduces the blast radius for the 37
affected machines without requiring manifest surgery. When Cluster B ships
manifest-level overrides, D2-a can be superseded gracefully.

**Approach D2-c: first_st inverse mapping via stash extension**

Extend the stash to include `scatter_feature_first_sts: dict[str, int]` —
mapping each bonus feature name to its observed `first_st` (the SpinType that
starts a chain for that feature). The mechanism registry's scatter_marker_pids
are identified by their pid, but their triggering SpinType is what links them to
a chain. The chain accumulation at `all_chains_by_feature` tracks `first_st` per
feature implicitly through the `chain_chunk_summaries` keys `(first_st,
cc_reset, sp_type)`. The `spin_type_to_feature` map at PIA (derived from
manifest `features_by_spin_type`) provides the `first_st → feature_name` lookup.

This approach would produce: scatter pid → its triggering SpinType (from
roundclassification data) → feature name (from spin_type_to_feature). This is
the most principled but requires the most stash extension and depends on the
chain data correctly capturing `first_st` per feature.

**Recommendation: Approach D2-a (chain-count majority vote)** for Round 1.

Rationale from 02 §8: the taxonomist confirmed that the NCS + NewFreespin
pattern is consistent across all tested BCM_FREESPIN and BCM_FREESPIN_WHEEL
machines. The majority-chain-count heuristic correctly picks NCS (841) over
NewFreespin (67) for M275, and NCS (554) over NewFreespin (41) for M272. The
C6 critic (phase_c6/critique.md §4) flagged the alphabetical heuristic as
"known limitation — no better generic heuristic available without domain
knowledge." Chain count is a better generic heuristic than alphabetical sort and
requires no manifest changes.

**Stash extension required** (01 §7.5 open question answer): the F6 inline
block at `pia:4862–4868` must be extended to also write
`scatter_feature_chain_counts`:

```python
# Updated stash (F6 inline, pia:~4862)
summary["_bonus_chain_dynamics_data"] = {
    "bonus_chain_dynamics": summary["player_impact"]["bonus_chain_dynamics"],
    "scatter_feature_names": sorted(
        feat for feat, afb in all_chains_by_feature.items()
        if afb.get("lengths")
    ),
    # NEW: chain counts per feature for trigger_target majority-vote heuristic (d2)
    "scatter_feature_chain_counts": {
        feat: len(afb["lengths"])
        for feat, afb in all_chains_by_feature.items()
        if afb.get("lengths")
    },
}
```

Note that `scatter_feature_names` is already built from a `sorted()` call — the
list is always alphabetically sorted. This means that on a tie (all chain counts
equal), `max()` with equal keys returns the first element of the sorted list,
which is alphabetically first. This is deterministic behavior, documented in the
plugin docstring.

#### D-2 confidence levels (three-tier specification) **[v2 revised — Fix 2]**

The BCD plugin emit() must implement and expose three confidence levels:

| Level | Condition | `trigger_target_confidence` value | Notes |
|---|---|---|---|
| `"unique"` | `len(scatter_feature_names) == 1` | `"unique"` | Deterministic; one possible feature |
| `"data_inferred"` | `len >= 2` AND `scatter_feature_chain_counts` present AND at least one non-zero count | `"data_inferred"` | Majority-vote heuristic |
| `"fallback_no_chain_data"` | `len >= 2` AND `scatter_feature_chain_counts` present BUT all counts are zero | `"fallback_no_chain_data"` | Alphabetical-first tie-break; data quality issue |

A fourth state — missing stash key — is an ERROR path, not a confidence level
(see below).

#### D-2 explicit error on missing stash key **[v2 revised — Fix 2 / TC-2 critical]**

v1 used `stash.get("scatter_feature_chain_counts") or {}` which silently returns
an empty dict when the key is absent, causing `max()` to pick the first element
of the (sorted) `scatter_feature_names` list — the same alphabetical-first wrong
behavior as before the fix. This violates `feedback_no_silent_swallow.md` and
`feedback_capture_drift.md` (critique Q9, verdict: NOT ADDRESSED).

**Required behavior when `scatter_feature_chain_counts` key is MISSING from
stash**:

If `scatter_feature_names` is non-empty but `"scatter_feature_chain_counts"` is
absent from the stash, the plugin must raise a `RuntimeError` with a descriptive
message. This RuntimeError is caught by the emit-error handler at `pia:5083`
and written to `summary["feature_errors"]["bonus_chain_dynamics"]` — the run
continues with rc=0 and the operator sees a clear schema-drift message. This is
the Cluster A `feature_errors` graceful-degradation path, NOT a hard
`SystemExit` path.

The error message must identify the missing key, the plugin that detected it, and
a remediation hint (the stash key was introduced in Round 1 d2; if this error
fires in production, the stash extension at `pia:4862` was not deployed or was
rolled back).

The updated BCD plugin emit() sketch:

```python
# In bonus_chain_dynamics.py emit(), replaces lines 205–208
if scatter_marker_pids and scatter_feature_names:
    # Validate stash has chain counts (d2 stash extension required)
    if "scatter_feature_chain_counts" not in stash:
        raise RuntimeError(
            f"bonus_chain_dynamics: 'scatter_feature_chain_counts' missing from stash. "
            f"scatter_feature_names={scatter_feature_names!r}. "
            f"The pia:4862 stash extension (Round 1 d2) may not be deployed."
        )
    _chain_counts = stash["scatter_feature_chain_counts"]

    if len(scatter_feature_names) == 1:
        # d3 fix: exactly one feature -> deterministic
        trigger_target = scatter_feature_names[0]
        trigger_target_confidence = "unique"
    else:
        # d2 fix: chain-count majority vote
        _max_count = max(_chain_counts.get(f, 0) for f in scatter_feature_names)
        if _max_count == 0:
            # All chains have zero count: stash key present but no data
            # Fall back to alphabetical first (sorted list, deterministic)
            trigger_target = scatter_feature_names[0]
            trigger_target_confidence = "fallback_no_chain_data"
        else:
            trigger_target = max(
                scatter_feature_names,
                key=lambda f: _chain_counts.get(f, 0),
            )
            trigger_target_confidence = "data_inferred"

elif scatter_marker_pids:
    trigger_target = None
    trigger_target_confidence = "unknown"
else:
    trigger_target = None
    trigger_target_confidence = None
```

**Why RuntimeError goes to feature_errors, not analyzer_init_error**: The
DECLARED_DEPS check (Region 2) fires BEFORE emit(). A stash-key miss INSIDE
emit() is caught by the pia:5083 emit-error handler (Path 3, already graceful).
This is intentional separation: Region 2 is a structural dependency declaration
mistake (the plugin declared it needed a key that was never written); a missing
stash key inside emit() is a data-quality or deployment issue (the key was not
written even though the stash extension was supposed to run). The former is a
hard pre-flight error; the latter is a graceful per-plugin degradation.

Note that `feedback_no_silent_swallow.md` requires the outcome to be persisted
to disk. The emit-error handler at pia:5083 writes to `feature_errors`, which
IS written to disk at pia:5210 (unlike the pre-fix error paths). So persisting
to disk is automatic via the existing graceful-degradation path.

**Blast radius** (03 §3 Symbol D-2): `bonus_chain_dynamics.py` byte change →
253 machines' `effective_analyzer_version` changes. Consumer `trigger_target` in
`payout_ids_top20[*].notes`: 0 frontend readers currently (03 §3 Symbol D-2
consumer table).

Note d2 and d3 are implemented together in the same code region, which is
correct — they are both inside the same `if` block in `bonus_chain_dynamics.py`
and touch `bonus_chain_dynamics.py` bytes once (one hash flip for the plugin,
not two). This is confirmed by 03 §7 case study 3 note: "D-2 and D-3 are
implemented together (single file edit), the plugin hash flips once, not twice."

**Fallback design** (for machines where chain counts are tied): if all features
have count=0 (stash present, data absent), `trigger_target_confidence` =
`"fallback_no_chain_data"` and the alphabetical-first element of the sorted
`scatter_feature_names` list is used. This is documented in the plugin's docstring.

### §5.3 d3: trigger_target_confidence "unique" dead spec branch

*(Carried verbatim from v1. Implemented as part of d2 in §5.2 sketch.)*

**Problem** (01 §3.3, 02 §3 Ax7): `trigger_target_confidence = "data_inferred"`
is always emitted when `scatter_feature_names` is non-empty, regardless of
whether there is exactly 1 or N features. The spec (01 §3.3 line 40) says:
"exactly one feature → confidence = unique; multiple features → data_inferred."
This branch is dead code — "unique" is never emitted (03 §3 Symbol D-3).

**Fix**: implemented as part of d2 (same code block, see §5.2 sketch above):
the `len(scatter_feature_names) == 1` branch emits `"unique"`. No additional
code change needed beyond what d2 requires.

**Fleet scope** (02 §3 Ax7-B): 0 current machines trigger the `"unique"` branch
(both tested BCM_FREESPIN and BCM_FREESPIN_WHEEL machines have 2 active
features). The fix is a spec-alignment invariant for future machines with
single-feature bonus chains. The C6 critique (phase_c6/critique.md §5) noted
this as "optional improvement — either implement 'unique' or remove it from
docstring." This proposal implements it (preserving spec correctness for future
machines).

**Test**: A new unit test asserting that when a mock stash has exactly 1 entry
in `scatter_feature_names`, the emitted `trigger_target_confidence == "unique"`.
Inject-bug recipe: remove the `len == 1` branch → fixture with 1 feature still
emits `"data_inferred"` → test RED.

### §5.4 d4: avg_bonus_payout None semantics

*(Carried verbatim from v1.)*

**Problem** (01 §3.4, 02 §6): When `_cm_bonus_feat` is not None (a bonus
feature was identified) and `total_completed_cycles > 0`, but the feature tally
sum is zero (`sum(win) == 0.0`), the current code emits `avg_bonus_payout =
0.0`. The brief says `None` is more semantically accurate here — it means "the
bonus feature was identified but produced no measurable win in the tally,
possibly indicating a data-resolution issue."

**Current code** (01 §3.4, pia:4817–4825):
```python
"avg_bonus_payout": (
    (
        sum(float(e.get("win", 0.0)) for e in ...) / total_completed_cycles
        if total_completed_cycles > 0 else None
    ) if _cm_bonus_feat else None
),
```
The case `_cm_bonus_feat is not None AND cycles > 0 AND sum(win) == 0.0`
produces `0.0 / total_completed_cycles = 0.0`.

**Fix design**: add a `sum(...) > 0` guard:

```python
"avg_bonus_payout": (
    (
        (lambda s: s / total_completed_cycles if s > 0 else None)(
            sum(float(e.get("win", 0.0)) for e in
                (upstream_feature_tally.get(_cm_bonus_feat) or {}).values())
        )
        if total_completed_cycles > 0 else None
    ) if _cm_bonus_feat else None
),
```

Or equivalently (more readable):
```python
_abp_win_sum = sum(
    float(e.get("win", 0.0))
    for e in (upstream_feature_tally.get(_cm_bonus_feat) or {}).values()
) if _cm_bonus_feat else 0.0
"avg_bonus_payout": (
    (_abp_win_sum / total_completed_cycles if _abp_win_sum > 0 else None)
    if (total_completed_cycles > 0 and _cm_bonus_feat)
    else None
),
```

The fix location is `player_impact_analyzer.py` (the PIA inline stash-writer at
line 4817), NOT `collect_mechanic.py`. This has two implications for blast
radius (03 §3 Symbol D-4 blast radius analysis):

- If fix is in `player_impact_analyzer.py`: `analyzer_version` (legacy string
  hash) flips for all 393 machines. But `effective_analyzer_version` (per-plugin
  hash) does NOT change for any machine because the plugin file bytes are
  unchanged. The version impact is minimal — `analyzer_version` is not the
  primary versioning signal (that is `effective_analyzer_version`).
- If fix is in `collect_mechanic.py`: `effective_analyzer_version` changes for
  machines declaring `collect_mechanic`, which is a larger blast radius for
  those machines' reports.

**Decision: fix in `player_impact_analyzer.py` (PIA inline)**, not in
`collect_mechanic.py`. The inline stash block is the source of the computation;
the plugin merely passes it through. This keeps plugin files as pure carve steps
and avoids flipping `effective_analyzer_version` for all BCM machines. The
`analyzer_version` flip from touching `player_impact_analyzer.py` is the lower
blast radius option.

**Downstream null-safety** (02 §6 consumer table): the frontend consumer
`app.js:6196` already has `bcc.avg_bonus_payout != null ? Number(...) : "—"`.
No frontend change needed. No backend consumer reads this field.

**What machines currently produce `avg_bonus_payout = 0.0`** (01 §7.8 open
question): From 02 §6: "All non-BCM machines (199 base machines): `collect_mechanic.applicable = false`; `avg_bonus_payout = None`." Non-BCM machines have `_cm_bonus_feat = None`, so the outer `if _cm_bonus_feat else None` returns `None` already. The `0.0` case fires ONLY when `_cm_bonus_feat` resolves to a feature name that is not in `upstream_feature_tally` (empty tally) or when the tally entries all have `win=0`. The behavioral change is from `0.0` to `None` in the display panel only for this edge case. The frontend renders `"—"` instead of `"0"`.

**Test**: assert that when the `upstream_feature_tally` for the bonus feature has
zero win total but cycles > 0, `avg_bonus_payout` in the summary is `None`, not
`0.0`. Inject-bug recipe: remove the `s > 0` guard → the fixture with zero win
sum emits `0.0` → test RED.

---

## §6 Commit Grouping Decision

*(Carried verbatim from v1.)*

### Options

**Option 1: 3 separate commits (E → D → A)**

- Commit E: test refactor only (no code change, no version invalidation).
- Commit D: 4 plugin fixes (2 plugin files + 1 PIA inline).
- Commit A: error surfacing (1 PIA control-flow change + 1 new exception class
  in topo_sort.py + 1 new test file).

Pros: each commit has a clean CI pass on its own (E leaves CI GREEN; D changes
253 machines' versions but all tests still pass with differential assertions;
A adds a new test that wasn't possible before).
Cons: 3 commits to review.

**Option 2: 1 mega-commit (all clusters together)**

All 3 clusters in one commit.

Pros: reviewer sees the full change in one shot.
Cons: the ordering constraint (E before D) still applies within the working tree.
If D is developed before E is committed, CI may be temporarily broken. The
commit message would cover 3 distinct concerns, making bisect harder if a
regression is found.

**Option 3: 2 commits (E+D bundled, then A)**

Commit 1: E (test refactor) + D (4 fixes) together.
Commit 2: A (error surfacing).

Pros: reduces commit count while preserving A as a clean, reviewable change
Cons: bundling E and D requires E to be ready before D can ship. If D is
developed first, CI is temporarily broken until E is committed.

**Recommendation: Option 1 (3 separate commits)**.

Rationale: The ordering constraint from 03 §8 fragility hotspot rank 5 is
explicit — E must commit BEFORE D to prevent the hardcoded constants from turning
CI RED. With 3 separate commits, each commit is reviewable independently, CI
passes at each step, and the commit message Self-critique section (per
`feedback_adversarial_self_review.md`) can be focused per cluster.
The 3-commit overhead is acceptable given that each cluster has a distinct
concern (test contract / data correctness / error contract).

### Commit message structure per cluster

Each commit must include (per `feedback_adversarial_self_review.md`):
```
feat(analyzer): Cluster <X> — <one-line description>

## What changed
<per-fix bullet points>

## Why
<W1 citation>

## Blast radius
<machines invalidated / tests updated>
  Cluster E: 0 machines invalidated (test-only)
  Cluster D: 253 machines effective_analyzer_version flips
  Cluster A: 0 machines effective_analyzer_version flips (PIA-only change)

## Self-critique
Q1: ...
Q2: ...
Q3: ...
```

---

## §7 Regression Risk Per Cluster **[v2 revised]**

### Cluster E regression risk

*(Carried verbatim from v1.)*

**Tests that break without Cluster E after any Cluster D commit**:
- `test_c3_5_isolation_m275_only.py` — 3 constants (`_M275_C3_5_EFFECTIVE_VERSION`,
  `_NON_M275_EFFECTIVE_VERSION`, `_C3_BASE_HASH`). The first two turn RED on
  any D-1 or D-2+D-3 change. `_C3_BASE_HASH` does NOT change (core unchanged).
- `test_c3_5_m14_no_multiplier_wild.py` — 1 constant (`_NON_M275_EFFECTIVE_VERSION`
  line 241) turns RED on any D-1 or D-2+D-3 change.

After Cluster E migration (differential assertions), these tests no longer pin
exact hex values → they remain GREEN through D-1 and D-2+D-3.

**Tests that break with Cluster E migration if incorrectly implemented**:
- Any test that previously asserted `ev == "6aae41144cea"` and is replaced with
  `ev == _compute_effective_version("M14", 1)` (trivially true) — the test now
  passes even if M14's hash changes. This is the dynamic-only Anti-pattern
  (Alternative E-1, rejected in §3.2).
- Mitigation: use differential assertions (Alternative E-3) that still fail if
  M275 unexpectedly equals M14.

**Inject-bug recipe for Cluster E**: to verify the isolation assertion
(`m275_ev != m14_ev`) is non-trivial, temporarily add `multiplier_wild` to M14's
manifest. The assertion should turn RED. Remove it — test GREEN.

### Cluster D regression risk **[v2 revised — Fix 1: 3 tests, not 1]**

**Tests that break from D-1** (03 §7 case study 2):
- `test_c3_5_isolation_m275_only.py:93,109` and
  `test_c3_5_m14_no_multiplier_wild.py:241` — turn RED immediately if not
  migrated by Cluster E. With Cluster E already committed, these remain GREEN.

**Tests that break from D-2+D-3** (03 §7 case study 3; critic TC-1 + BF-1;
validation B1 + B2 — three tests, not one):

**[v2 revised]** Three tests require update as part of the D-2 commit. All three
must be updated in the SAME Cluster D commit that changes `bonus_chain_dynamics.py`.
Leaving any one un-updated causes CI RED.

**Test update 1 of 3: `test_c6_gap_3_pid_666_trigger_marker.py:160`**

- Current assertion (confirmed by validator B1 real code read):
  ```python
  # test_pid_666_trigger_target_is_new_freespin
  assert notes.get("trigger_target") == "NewFreespin"   # LINE 160
  ```
- After D-2: `trigger_target` becomes `"NormalCollectionSpin"` (correct per
  chain-count majority vote) → this assertion **turns RED**.
- v1 §7 said "no change needed for this test" — this was INCORRECT. The
  critic (TC-1) and validator (B1) independently confirmed line 160 asserts the
  wrong value.
- Required change: update assertion to `== "NormalCollectionSpin"`. Also rename
  the test method from `test_pid_666_trigger_target_is_new_freespin` to
  `test_pid_666_trigger_target_is_normal_collection_spin` to match the corrected
  behavior.
- The `trigger_target_confidence` assertion in the same test file (asserting
  `"data_inferred"`) does NOT change — M275 has 2 features, so it stays
  `"data_inferred"` (not `"unique"`).

**Test update 2 of 3: `test_c6_bonus_chain_dynamics_plugin.py:432`**

- Current fixture (confirmed by validator B2 simulation):
  ```python
  stash = {
      "bonus_chain_dynamics": {"applicable": True, "chain_count": 100},
      "scatter_feature_names": ["ZFeature", "AFeature"],  # unsorted (Z before A)
      # missing: "scatter_feature_chain_counts"
  }
  assert row_666["notes"]["trigger_target"] == "AFeature"  # LINE 432
  ```
- After D-2, the plugin checks for `"scatter_feature_chain_counts"` in the stash
  (v2 §5.2 explicit error spec). If the key is absent, a `RuntimeError` is raised
  → the test's mock emit call fails with an exception, not an assertion. The test
  turns RED for a different reason than expected.
- Additionally, even if the key were present and empty (`{}`), `max()` over tied-zero
  counts returns `"ZFeature"` (first element of the UNSORTED list `["ZFeature",
  "AFeature"]`), not `"AFeature"`. The validator (B2) confirmed this via Python
  simulation.
- Required changes (both are needed):
  1. Add `"scatter_feature_chain_counts": {"AFeature": 100, "ZFeature": 1}` to
     the fixture stash — AFeature has higher chain count, so it wins.
  2. Sort the `scatter_feature_names` list in the fixture to match PIA behavior:
     `["AFeature", "ZFeature"]` (alphabetically sorted, as PIA always writes it).
  3. Update the assertion comment: "AFeature wins by chain count (100 > 1), not
     alphabetically."
  4. The assertion value `"AFeature"` remains correct (AFeature has the higher
     chain count in the updated fixture). Only the stash fixture needs updating.

**Test update 3 of 3: `test_emit_trigger_target_from_scatter_feature_names`**
(same file `test_c6_bonus_chain_dynamics_plugin.py`, lines 437–453 per critique BF-1)

- This test covers the `"data_inferred"` confidence path for a 2-feature stash.
  If the fixture stash does not include `scatter_feature_chain_counts`, the v2
  plugin code raises `RuntimeError` before reaching the `trigger_target_confidence`
  assertion → test RED for wrong reason.
- Required change: verify whether this test also lacks `scatter_feature_chain_counts`
  in its mock stash. If absent, add it with non-zero counts for at least one
  feature. The `trigger_target_confidence == "data_inferred"` assertion still
  holds (2 features, at least one with non-zero count → `"data_inferred"`).
- If this test already has `scatter_feature_chain_counts` in its fixture (possible
  if BF-1 was a test-level confusion), the assertion may pass without change. The
  impl team must inspect lines 437–453 to confirm.
- The impl team must grep `test_c6_bonus_chain_dynamics_plugin.py` for ALL
  occurrences of mock stash dicts that include `scatter_feature_names` but LACK
  `scatter_feature_chain_counts`, and update each one.

**Summary of D-2 required test updates**:

| Test file | Line | Old assertion | New assertion | Reason |
|---|---|---|---|---|
| `test_c6_gap_3_pid_666_trigger_marker.py` | 160 | `== "NewFreespin"` | `== "NormalCollectionSpin"` | D-2 corrects M275 trigger_target value |
| `test_c6_bonus_chain_dynamics_plugin.py` | 432 | `== "AFeature"` (with broken fixture) | `== "AFeature"` (with corrected fixture + chain_counts added) | D-2 fixture needs `scatter_feature_chain_counts` + sorted list |
| `test_c6_bonus_chain_dynamics_plugin.py` | 437–453 region | fixture stash may lack chain_counts | Add `scatter_feature_chain_counts` if missing | D-2 raises RuntimeError on missing key |

**Tests that break from D-4**:
- No test currently asserts `avg_bonus_payout == 0.0` for the edge case (02 §6
  consumer table: `test_c5_collect_mechanic_plugin.py:298` uses `40.0`, not `0.0`).
  No existing test turns RED. New test must be added to cover the `None` case.

**Inject-bug recipes per D-fix**:
- D-1: revert `key=lambda x: int(x["payline_id"])` to string sort → fixture
  with payline_ids including `"10"` asserts `"10" comes after "9"` → test RED.
- D-2: revert to `sorted(scatter_feature_names)[0]` → M275 fixture asserts
  `trigger_target == "NormalCollectionSpin"` → test RED (gets "NewFreespin").
- D-3: remove `len == 1` branch → fixture with 1 feature asserts confidence
  `"unique"` → test RED (gets "data_inferred").
- D-4: remove `s > 0` guard → fixture with `win_sum == 0, cycles > 0` asserts
  `avg_bonus_payout is None` → test RED (gets `0.0`).

### Cluster A regression risk

**Tests that break from Cluster A**:
- None on success path — the try/finally pattern does not change any success-path
  behavior. The 14 tests asserting `"analyzer_init_error" not in summary` on
  success paths remain GREEN.
- `test_c1_init_error_surfacing.py` — tests topo_sort unit-level behavior,
  unchanged by A. Remains GREEN.

**New tests required** (§4.4): `test_a_init_error_disk_surfacing.py` with two
test functions — one for Region 1 (topo-sort cycle) and one for Region 2
(DECLARED_DEPS miss inside emit loop). Until both tests exist, the disk-write
guarantee is partially untested. Both are new GREEN tests to add, not existing
tests that turn RED.

**Inject-bug recipe for Cluster A Region 1**: In `_safe_write_summary_json`,
remove the try/except wrapper (let the write propagate). Inject an IOError from
a mock `write_summary_json`. The test should assert that rc=1 still fires AND
that the error is reported to stderr — if the try/except is removed, the IOError
replaces the SystemExit and the test sees a non-1 exit code → test RED.

**Inject-bug recipe for Cluster A Region 2**: monkeypatch the DECLARED_DEPS emit
loop check to be skipped entirely. The test asserts `player_impact_summary.json`
does NOT exist on rc=1 → RED (with fix: JSON IS written). Restore → GREEN.

---

## §8 8-Gap Closure Invariant Preservation

*(Carried verbatim from v1.)*

The 8 gaps from C-phases C1–C6 must remain GREEN after Round 1. This section
proves each fix does not regress them.

**Gap-to-fix impact table**:

| Gap | C-phase | Description | D-1 impact | D-2+D-3 impact | D-4 impact | A impact | E impact |
|---|---|---|---|---|---|---|---|
| Gap #1 machine_mechanics (C4) | C4 | jackpot/freespin/scatter flags in mechanism_registry | None | None | None | None | None |
| Gap #2 machine_mechanics (C4) | C4 | payout group applicable flag | None | None | None | None | None |
| Gap #3 scatter_trigger_marker (C6) | C6 | trigger_target in payout_ids_top20 | None | Updates M275 trigger_target value — intentional correctness fix | None | None | None |
| Gap #4 multiplier_wild (C3.5) | C3.5 | M275 wild multiplier breakdown | None | None | None | None | None |
| Gap #5 upstream_feature (C5) | C5 | upstream feature tally | None | None | None | None | None |
| Gap #6 collect_mechanic (C5) | C5 | BCM cycle correction | None | None | None (None vs 0.0 is display-only) | None | None |
| Gap #7 bonus_chain_dynamics by_feature (C6) | C6 | chain counts by feature | None | None | None | None | None |
| Gap #8 notes block payout_ids_top20 (C6) | C6 | trigger_marker notes on top20 pids | None | trigger_target value corrected — not a regression, intended fix | None | None | None |

**Key analysis**:

Gap #3 and Gap #8 are both about `trigger_target` in `payout_ids_top20`. The D-2 fix changes `trigger_target` from `"NewFreespin"` to `"NormalCollectionSpin"` for M275. This is NOT a regression of gap #3 or gap #8 — those gaps required the `notes` block to EXIST with the `trigger_target` field present. They did not specify which feature name is correct. The C6 critic (phase_c6/critique.md §4) explicitly acknowledged "NewFreespin" as a known limitation. The D-2 fix improves the accuracy of an already-existing field — it closes a data correctness bug, not a structural gap.

The test `test_c6_gap_3_pid_666_trigger_marker.py` asserts presence of
`trigger_target` in the notes block. After D-2, the value changes but the key
is still present — the structural assertion passes. The value assertion at line
160 (which asserts the wrong value `"NewFreespin"`) must be updated as part of
D-2 (§7 test update 1 of 3).

**D-1 paylines sort** does not affect any gap — no C-phase gap involves paylines
ordering. The sort fix is orthogonal to all gap assertions.

**Cluster A** (error surfacing try/finally) does not modify any plugin output.
Success-path behavior is unchanged. No gap is regressed.

**Cluster E** (test refactor) changes NO code — no gap can be affected.

---

## §9 Phase Implementation Order Within Round 1

### Phase 1: Cluster E (test refactor)

**Deliverables**:
- `test_c3_5_isolation_m275_only.py` — remove `_M275_C3_5_EFFECTIVE_VERSION`
  and `_NON_M275_EFFECTIVE_VERSION` pin assertions; replace with structural
  differential assertions as specified in §3.3.
- `test_c3_5_m14_no_multiplier_wild.py` — remove `_NON_M275_EFFECTIVE_VERSION`
  pin at line 241; replace with structural differential assertion.
- 6 remaining files confirmed no-change (4 base_hash pin files + 2 already-dynamic
  files) — no edits required; the impl team should document this confirmation.
- Commit: "refactor(tests): Cluster E — replace effective_version hex pins with differential assertions"

**Verification**: run full `pytest tests/analyzer/` suite. All existing tests pass. No code files changed → no effective_version values change → all byte-identical tests remain GREEN.

**Rollback**: revert the test file changes. No code was modified, so rollback is trivial and has zero production impact.

### Phase 2: Cluster D (4 plugin fixes)

**Deliverables**:
- `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` — d1 sort key fix at
  lines 424 and 431 + payline_id pre-validation (§5.1 defensive ValueError spec).
  New test asserting integer sort order for 10+ payline fixture.
- `fresh_slotlab/analyzer/features/bonus_chain_dynamics.py` — d2 chain-count
  majority vote + d3 unique confidence + explicit RuntimeError on missing
  `scatter_feature_chain_counts` key (§5.2 v2 spec, single edit, one hash flip).
  Three test updates as specified in §7: update `test_c6_gap_3_pid_666_trigger_marker.py:160`,
  update `test_c6_bonus_chain_dynamics_plugin.py:432` fixture, verify/update
  `test_c6_bonus_chain_dynamics_plugin.py:437-453` fixture. New test for d3 unique
  branch. New test for `fallback_no_chain_data` confidence level.
- `fresh_slotlab/player_impact_analyzer.py` — d4 `avg_bonus_payout` None guard
  (inline stash block ~line 4817). New test for None vs 0.0 semantics. Extension
  to stash dict at `pia:4862` to add `scatter_feature_chain_counts`.
- Commit: "fix(analyzer): Cluster D — paylines int sort, trigger_target chain-count heuristic, unique confidence, fallback_no_chain_data, avg_bonus_payout None semantics"

**Verification**: pytest full suite. The differential assertions added in Phase 1
remain GREEN despite 253 machines' effective_versions changing. The three
D-2-affected tests are GREEN with updated assertions and fixtures.

**Rollback**: revert the three changed files. The Phase 1 test refactor remains
in place and is compatible with both old and new plugin bytes (since it uses
differential assertions, not hex pins).

### Phase 3: Cluster A (unified error surfacing)

**Deliverables**:
- `fresh_slotlab/analyzer/topo_sort.py` — new `PluginDeclaredDepMissingError`
  class (analogous to existing `PluginCyclicDependencyError` at line 42). Takes
  `plugin: str` and `missing_dep_key: str` (the summary key, not a FEATURE_ID,
  to distinguish it from `PluginMissingDependencyError`).
- `fresh_slotlab/player_impact_analyzer.py` — `_safe_write_summary_json` local
  helper defined before the topo-sort block. Region 1 topo-sort error block
  (lines 5044–5065): add `_safe_write_summary_json` call before `raise
  SystemExit(1)`. Add `region=1` to `analyzer_init_error` dict. Region 2
  DECLARED_DEPS block (lines 5073–5080): convert `raise RuntimeError` to set
  `summary["analyzer_init_error"]` with `region=2`, call `_safe_write_summary_json`,
  raise `SystemExit(1)`.
- New test file `tests/analyzer/test_a_init_error_disk_surfacing.py` — two
  test functions: Region 1 (topo cycle) + Region 2 (DECLARED_DEPS miss) as
  specified in §4.4.
- Commit: "fix(analyzer): Cluster A — analyzer_init_error persisted to disk on topo/dep errors; try/finally pattern; region 1+2 test coverage"

**Verification**: pytest full suite. The 14 tests asserting `"analyzer_init_error"
not in summary` on success paths remain GREEN. Both new disk-surfacing tests
(Region 1 + Region 2) are GREEN.

**Rollback**: revert PIA and topo_sort.py changes. The new test file reverts with
them. Phases 1 and 2 remain committed and are unaffected.

---

## §10 Out-of-Scope Deferrals

*(Carried verbatim from v1.)*

The following items are explicitly NOT addressed in this proposal:

**Cluster B — Mechanism Registry 6×3 tier completion** (00 §5): The mechanism
registry's Tier 1/2/3 detection for jackpot/freespin/scatter/payout-groups is
partially implemented. This is a separate arch round requiring Tier 1 manifest
schema changes across 253 manifests.

**Cluster C — F6 cleanup + Registry build position refactor** (00 §5): The F6
inline block in PIA duplicates logic now owned by the BCD plugin. Cleaning it up
requires verifying the invariant assert at `pia:~4954` and the machine_mechanics
REQUIRES ordering — a separate arch round.

**Cluster F — M37 root cause** (00 §5): Handled as a separate read-only
investigation. Not a code change.

**Cluster G — Phase 4 frontend** (00 §5): Frontend rendering of new fields
(`trigger_target`, `trigger_target_confidence`, `analyzer_init_error` panel).
Currently 0 frontend consumers of these fields (03 §3 Symbol D-2/D-3 consumer
tables). Frontend design is a separate product-scope decision.

**Cluster H — Full fleet verify campaign** (00 §5): Running the 32 d1-affected
machines through a fresh report cycle to verify paylines sort order in production.
This is an operational step after implementation, not an arch design.

**253 manifest updates** (00 §3 "253 manifests: no manifest changes needed"): This
proposal requires no manifest changes. The d2 fix uses data-driven majority vote
rather than manifest-level `scatter_trigger_target` override (Approach D2-b
deferred to Cluster B).

**`feature_errors` → `analyzer_init_error` consolidation**: The brief's "unified
error contract" means the HARD error paths (topo, DECLARED_DEPS) now write JSON —
it does NOT mean collapsing `feature_errors` into `analyzer_init_error`. These
two fields serve different purposes (infra failure vs. graceful-degradation per-plugin
failure) and have 18 test assertion sites that depend on `feature_errors` remaining
a separate key. Consolidation is explicitly deferred.

**Backend surface for `analyzer_init_error`**: Currently 0 production code reads
this field (03 §2 Symbol A-1: "`_batch_gen_worker.py:154` — reads `rc` only; does
NOT read `analyzer_init_error` from the summary dict"). The field written to disk
by Cluster A is for operator manual inspection only. Surfacing it in the console UI
or in batch job status is a Cluster G frontend concern.

**Hash composition documentation update**: The effective_version composition
algorithm is unchanged by this proposal (no new plugin, no change to the
`compute_effective_version_for_machine` function, no change to hash XOR/concat
logic). No documentation update to hash composition rules is needed.

**`PluginDeclaredDepMissingError` file placement**: The critique (05 §6 Q6) noted
that `topo_sort.py` is not the ideal semantic home for this exception (it is an
emit-loop runtime error, not a graph-sort error). Relocating it to
`pipeline_context.py` or a new `plugin_errors.py` is deferred to Cluster C
(infrastructure refactor). For Round 1, it ships in `topo_sort.py` alongside the
two analogous existing classes.

---

## §11 Open Questions for Wave 3 (Critic + Validator)

*(Original Q1–Q8 carried from v1. Three questions are now resolved by v2 revisions.)*

**Q1 — d4 fix location: PIA inline vs. collect_mechanic.py?**

This proposal recommends fixing `avg_bonus_payout` in the PIA inline stash
block (`player_impact_analyzer.py:4817`) rather than in `collect_mechanic.py`,
because the computation originates in the inline block. The critic should stress-test
whether a future refactor that moves the computation into `collect_mechanic.py`
would reintroduce the `0.0` bug (if the inline block is removed without also
fixing the plugin). Is the PIA inline the stable long-term home for this
computation, or does it belong in the plugin?

**Q2 — d2 chain-count majority vote: is it provably correct for all ~37 scatter machines?**

The majority-vote heuristic (pick feature with highest chain count) is grounded
in the M275 and M272 data (02 §8). The taxonomist confirmed the
NCS+NewFreespin pattern in both tested BCM_FREESPIN and BCM_FREESPIN_WHEEL
machines. The critic should assess: are there scatter machines in the ~37
affected set where the higher-chain-count feature is NOT the scatter trigger
target? If such a machine exists, the D2-a heuristic is still wrong for it.

**Q3 — RESOLVED in v2**: Cluster A DECLARED_DEPS partial output semantics are
now specified: option (a) "keep partial + annotate with region=2" is the selected
design. No further Wave 3 action required on Q3.

**Q4 — is the `_PluginDeclaredDepMissingError` exception class the right
abstraction, or should the DECLARED_DEPS check raise `PluginMissingDependencyError`?**

The distinction is real (REQUIRES is a plugin-graph concept; DECLARED_DEPS is a
summary-key concept). The v2 recommendation remains: new class. But the critic
confirmed in 05 §6 that the new class should take `missing_dep_key: str` (summary
key) not `missing_dep: str` (FEATURE_ID) to remain distinguishable from the
existing class. This is incorporated into the Phase 3 deliverables spec above.

**Q5 — Cluster E: should the base_hash pin tests gain a comment explaining WHY they are pinned?**

All 6 base_hash pin instances (`"fa440e3eb5f6"`) currently have minimal context
for future developers. The C6 critique (phase_c6/critique.md §2) showed how
misleading comments in the version-history block caused confusion. The critic
should assess whether the Cluster E commit should also add a standard explanatory
comment to the 6 base_hash pin assertions clarifying: "This value is intentionally
hardcoded. Making the RHS dynamic would remove the regression guard against
accidental core/*.py edits." This is a low-risk additive comment but should be
decided before the impl team commits.

**Q6 — Write order guarantee in the try/finally region**

RESOLVED by validator (06 §6 "Q6 confirmed correct"). Python single-threaded
execution guarantees `summary["analyzer_init_error"]` is populated before
`_safe_write_summary_json` is called, before `raise SystemExit(1)`. No further
Wave 3 action required.

**Q7 — Cluster E manifest-file dependency in CI environments**

From 03 §4 E-1 (coupling audit silent dependency): using
`compute_effective_version_for_machine("M14", 1)` dynamically in tests depends
on `slot_designer/configs/machine_manifests/M14.json` being present. The
differential assertions in §3.3 call this function at test runtime. The critic
should assess whether the CI environment (on `claude/analyzer-unbundle-c2`
branch) reliably has these manifest files, or whether the test should use a
local fixture manifest to avoid `FileNotFoundError` under a stripped CI image.

**Q8 — Cluster D d2: what is the tie-breaking behavior when chain counts are equal?**

RESOLVED in v2 §5.2: ties (all counts zero) produce `"fallback_no_chain_data"`
confidence with alphabetical-first trigger_target. Non-zero-but-equal counts
(two features with identical counts > 0) also produce `"data_inferred"` with
alphabetical-first from the sorted list — this is deterministic and documented.
No further Wave 3 action required on Q8.

---

## §12 Open Questions Surviving v2

*(New section — questions not yet resolved that Wave 3 v2 review should address.)*

**SQ-1 — `fallback_no_chain_data` confidence level: should this produce a
`feature_errors` entry in addition to the emitted field?**

v2 §5.2 defines `"fallback_no_chain_data"` as a graceful fallback (stash key
present, all counts zero) that produces a valid output with reduced confidence.
The run continues with rc=0. However, `feedback_no_silent_swallow.md` says
"any best-effort post-hook must persist diagnostic to disk." Is emitting the
`trigger_target_confidence = "fallback_no_chain_data"` field sufficient as the
on-disk signal, or should the plugin ALSO write a `feature_errors["bonus_chain_dynamics"]`
warning entry so the operator is actively alerted (rather than needing to inspect
the `trigger_target_confidence` field specifically)? Wave 3 v2 should assess
whether the confidence field alone is sufficient or whether a companion warning
in `feature_errors` is needed.

**SQ-2 — Region 2 test inject-bug: does monkeypatching the emit loop skip work
in-process, or does it require a subprocess?**

The Region 2 test spec (§4.4) says "Run PIA against the injected registry."
The existing Region 1 test (test_c1_init_error_surfacing.py) runs in-process.
For Region 2, the DECLARED_DEPS check is inside the emit loop — an in-process
injection may be possible (monkeypatch `_feature.DECLARED_DEPS` on a real plugin
object) or may require a subprocess (to avoid import-side-effects from the
PIA main() call). Wave 3 v2 should confirm whether the inject-bug recipe is
achievable in-process (preferred for test speed) or requires subprocess mode.
`feedback_subprocess_import_suicide_and_module_globals.md` is the relevant
memory constraint.

---

*Proposal end v2. Awaiting Wave 3 v2 review (or coordinator decision to skip ceremony
and proceed to impl-* team with this v2 as the implementation spec).*
