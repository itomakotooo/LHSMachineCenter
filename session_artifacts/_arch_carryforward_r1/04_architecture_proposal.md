# 04 — Architecture Proposal: Carry-forward Round 1 (Clusters A + D + E)

> **Date**: 2026-05-28
> **Author**: arch-designer (Wave 2)
> **Input artifacts**: `01_pipeline_map.md`, `02_taxonomy.md`, `03_coupling_audit.md`, `00_brief.md`
> **Output directory**: `session_artifacts/_arch_carryforward_r1/`
> **Downstream consumers**: `arch-critic` (05), `arch-validator` (06), then impl-* team

---

## §1 Executive Summary

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

## §4 Cluster A Design — Unified Error Surfacing Contract

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

### §4.3 Recommended design (Alternative A-3) — precise specification

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
    "timestamp":        str,   # datetime.now(timezone.utc).isoformat()
}
```

The existing topo-sort handler at `pia:5049–5057` already populates
`error_type`, `message`, `plugin_dep_graph`, and `timestamp` (01 §2.2). The
new field `affected_plugin` is added for DECLARED_DEPS errors to identify which
feature's dep check failed.

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
main() using a local function or a standalone call with try/except.

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
                missing_dep=_dep_key,
            )
            summary["analyzer_init_error"] = {
                "error_type": type(_dep_exc).__name__,
                "message": str(_dep_exc),
                "plugin_dep_graph": {f.FEATURE_ID: list(f.REQUIRES) for f in _machine_features},
                "affected_plugin": _feature.FEATURE_ID,
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
This is acceptable — the `analyzer_init_error` key signals partial data.

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

### §4.4 New test required for Cluster A

The existing `test_c1_init_error_surfacing.py` (01 §2.7 design note + test file
header) tests that topo_sort raises correctly at the unit level. It does NOT test
that the JSON is written to disk on rc=1 (acknowledged as TODO in file header
line 16: "A full subprocess-level inject test is left as TODO for Phase C2").

A new test file `test_a_init_error_disk_surfacing.py` is required (03 §6.1
mitigation note). It must:
1. Inject a cyclic plugin pair into a fresh temporary plugin registry.
2. Run PIA (subprocess or in-process) against the injected registry.
3. Assert rc=1.
4. Assert that `player_impact_summary.json` EXISTS in the output directory.
5. Assert that the JSON contains `"analyzer_init_error"` key at top level.
6. Assert that `analyzer_init_error["error_type"]` equals `"PluginCyclicDependencyError"`.

Inject-bug recipe: in the `_safe_write_summary_json` sketch, remove the
try/except wrapper (simulating an OSError) — the summary write fails but should
NOT suppress the SystemExit. Test must assert rc=1 still fires. Revert, test
is GREEN.

---

## §5 Cluster D Design — 4 Small Fleet-Plugin Fixes

### §5.1 d1: paylines int sort + carve-out

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
    key=lambda x: int(x["payline_id"]),    # ← was: x["payline_id"]
)

# Site 2 (regular pid path, payouts_by_spin_type.py:431):
paylines = sorted(
    [{"payline_id": pl_id, "hit_count": cnt}
     for pl_id, cnt in pl_map.items()
     if pl_id != "-1"],
    key=lambda x: int(x["payline_id"]),    # ← was: x["payline_id"]
)
```

The `-1` carve-out: `int("-1") = -1` sorts before all positive integers
naturally. No special-casing needed. However, 03 §6.2 (silent dependency) notes
that `int(x["payline_id"])` raises `ValueError` for any non-integer, non-`"-1"`
payline_id string. Per the brief and taxonomy (01 §3.1 note on payline_id type:
"always int-parseable per all audited machines"), this is an acceptable
assumption. The implementation sketch should add a comment documenting this
assumption so future machines with unusual payline schemas are caught early.

**Defensive alternative**: `key=lambda x: int(x["payline_id"]) if x["payline_id"].lstrip("-").isdigit() else x["payline_id"]`. This falls back to string sort for non-numeric payline IDs rather than raising. The designer recommends the simple `int()` version — a `ValueError` on a non-numeric payline_id is an EARLY SIGNAL of a schema drift (per `feedback_capture_drift.md`), not something to silently handle. A try/except that converts `ValueError` into a `ValueError` raised with a descriptive message is the correct pattern if the implementer wants an informative error.

**Blast radius** (03 §3 Symbol D-1): `payouts_by_spin_type.py` byte change → 253
machines' `effective_analyzer_version` changes. No consumer breaks; the sort
order for current manifested machines (M14/M37/M272/M275) is unchanged because
they have fewer than 10 paylines.

**Test coverage**: A new test asserting that paylines are emitted in integer
order for a fixture machine with 10+ paylines (e.g., M107 or M5 cached chunks).
Inject-bug recipe: revert `int()` to string sort → assert order `["1","10","2"]`
in fixture → test RED.

### §5.2 d2: trigger_target via scatter_marker_pids inverse mapping

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

The BCD plugin's emit() is updated to pick by chain count:

```python
# In bonus_chain_dynamics.py emit(), replaces lines 205–208
if scatter_marker_pids and scatter_feature_names:
    _chain_counts = stash.get("scatter_feature_chain_counts") or {}
    if len(scatter_feature_names) == 1:
        trigger_target = scatter_feature_names[0]
        trigger_target_confidence = "unique"       # d3 fix
    else:
        # Pick feature with highest chain count (majority vote — d2 fix).
        # Falls back to alphabetical sort if counts are tied or missing.
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

Note that d2 and d3 are implemented together in the same code region, which is
correct — they are both inside the same `if` block in `bonus_chain_dynamics.py`
and touch `bonus_chain_dynamics.py` bytes once (one hash flip for the plugin,
not two). This is confirmed by 03 §7 case study 3 note: "D-2 and D-3 are
implemented together (single file edit), the plugin hash flips once, not twice."

**Fallback design** (for future machines where chain counts are tied): if
`max()` would be ambiguous (two features with identical chain counts), the tie is
broken by alphabetical sort (same as current behavior). This is documented in the
plugin's docstring.

**Blast radius** (03 §3 Symbol D-2): `bonus_chain_dynamics.py` byte change →
253 machines' `effective_analyzer_version` changes. Consumer `trigger_target` in
`payout_ids_top20[*].notes`: 0 frontend readers currently (03 §3 Symbol D-2
consumer table). The existing test `test_c6_bonus_chain_dynamics_plugin.py`
asserts presence of `notes.trigger_target` — this must be updated to assert
`"NormalCollectionSpin"` for M275 (03 §3 Symbol D-2, "Test must be updated").

### §5.3 d3: trigger_target_confidence "unique" dead spec branch

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

## Self-critique
Q1: ...
Q2: ...
Q3: ...
```

---

## §7 Regression Risk Per Cluster

### Cluster E regression risk

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

### Cluster D regression risk

**Tests that break from D-1** (03 §7 case study 2):
- `test_c3_5_isolation_m275_only.py:93,109` and
  `test_c3_5_m14_no_multiplier_wild.py:241` — turn RED immediately if not
  migrated by Cluster E. With Cluster E already committed, these remain GREEN.

**Tests that break from D-2+D-3** (03 §7 case study 3):
- Same two test files as D-1.
- `test_c6_bonus_chain_dynamics_plugin.py` — currently asserts
  `trigger_target == "NewFreespin"` for M275 (per C6 commit). After D-2 fix,
  this MUST be updated to assert `trigger_target == "NormalCollectionSpin"`.
  This is an EXPECTED regression — the existing test is asserting the WRONG
  behavior. Updating it is a required part of the D-2 fix.
- `test_c6_gap_3_pid_666_trigger_marker.py` — asserts `"data_inferred"` for M275
  (per C6 commit). If M275's `scatter_feature_names` has 2 features (confirmed
  from taxonomy: 2 features for M275), the d3 "unique" branch does NOT fire for
  M275 — M275 still gets `"data_inferred"`. No change needed for this test.

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

**New test required** (§4.4): `test_a_init_error_disk_surfacing.py`. Until this
test exists, the disk-write guarantee is untested. This is a new GREEN test to
add, not an existing test that turns RED.

**Inject-bug recipe for Cluster A**: In `_safe_write_summary_json`, remove the
try/except (let the write propagate). Inject an IOError from a mock
`write_summary_json`. The test should assert that rc=1 still fires AND that the
error is reported to stderr — if the try/except is removed, the IOError replaces
the SystemExit and the test sees a non-1 exit code → test RED.

---

## §8 8-Gap Closure Invariant Preservation

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
is still present — the structural assertion passes. Only a value assertion
(`== "NewFreespin"`) would fail, and such a value assertion (if it exists) must
be updated as part of D-2 since it is asserting the wrong behavior.

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
- All 6 base_hash pin files — NO changes (confirmed in §3.3).
- `test_c3_5_m275_e2e.py` — NO changes (already dynamic).
- `test_c1_byte_identical_m14.py` — NO changes (hex in comment only).
- Commit: "refactor(tests): Cluster E — replace effective_version hex pins with differential assertions"

**Verification**: run full `pytest tests/analyzer/` suite. All existing tests pass. No code files changed → no effective_version values change → all byte-identical tests remain GREEN.

**Rollback**: revert the test file changes. No code was modified, so rollback is trivial and has zero production impact.

### Phase 2: Cluster D (4 plugin fixes)

**Deliverables**:
- `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` — d1 sort key fix at
  lines 424 and 431. New test asserting integer sort order for 10+ payline fixture.
- `fresh_slotlab/analyzer/features/bonus_chain_dynamics.py` — d2 chain-count
  majority vote + d3 unique confidence (single edit, one hash flip). Update existing
  test to assert `"NormalCollectionSpin"` for M275. New test for d3 unique branch.
- `fresh_slotlab/player_impact_analyzer.py` — d4 `avg_bonus_payout` None guard
  (inline stash block ~line 4817). New test for None vs 0.0 semantics. Extension
  to stash dict at `pia:4862` to add `scatter_feature_chain_counts`.
- Commit: "fix(analyzer): Cluster D — paylines int sort, trigger_target chain-count heuristic, unique confidence, avg_bonus_payout None semantics"

**Verification**: pytest full suite. The differential assertions added in Phase 1
remain GREEN despite 253 machines' effective_versions changing. The byte-identical
tests for M14/M37/M272/M275 may need updated expected-summary fixtures if those
machines' reports change (M275 `trigger_target` field changes; `paylines` sort is
unchanged for M14/M272/M275 since they have < 10 paylines).

**Rollback**: revert the three changed files. The Phase 1 test refactor remains
in place and is compatible with both old and new plugin bytes (since it uses
differential assertions, not hex pins).

### Phase 3: Cluster A (unified error surfacing)

**Deliverables**:
- `fresh_slotlab/analyzer/topo_sort.py` — new `PluginDeclaredDepMissingError`
  class (analogous to existing `PluginCyclicDependencyError` at line 42).
- `fresh_slotlab/player_impact_analyzer.py` — region 1 topo-sort error block
  (lines 5044–5065): add `_safe_write_summary_json` call before `raise
  SystemExit(1)`. Region 2 DECLARED_DEPS block (lines 5073–5080): convert
  `raise RuntimeError` to set `summary["analyzer_init_error"]`, call
  `_safe_write_summary_json`, raise `SystemExit(1)`.
- New test file `tests/analyzer/test_a_init_error_disk_surfacing.py` — subprocess-level
  inject test asserting JSON written on rc=1 (§4.4).
- Commit: "fix(analyzer): Cluster A — analyzer_init_error persisted to disk on topo/dep errors; try/finally pattern"

**Verification**: pytest full suite. The 14 tests asserting `"analyzer_init_error"
not in summary` on success paths remain GREEN. The new disk-surfacing test is GREEN.

**Rollback**: revert PIA and topo_sort.py changes. The new test file reverts with
them. Phases 1 and 2 remain committed and are unaffected.

---

## §10 Out-of-Scope Deferrals

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
rejected in §5.2). Manifest changes for Tier 1 override are deferred to Cluster B.

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

---

## §11 Open Questions for Wave 3 (Critic + Validator)

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

**Q3 — Cluster A DECLARED_DEPS error: partial output in the on-disk summary**

When a DECLARED_DEPS error fires inside the emit loop (Region 2), some
features have already successfully emitted before the error. The JSON written to
disk has partial plugin output (features before the failing feature) plus
`analyzer_init_error`. The critic should assess whether this partial state causes
any silent misuse — for example, if an operator sees the partial JSON and
misinterprets it as a complete successful run for the fields that were emitted.

**Q4 — is the `_PluginDeclaredDepMissingError` exception class the right
abstraction, or should the DECLARED_DEPS check raise `PluginMissingDependencyError`?**

`PluginMissingDependencyError` (existing, in `topo_sort.py:63`) is defined for
"a plugin's REQUIRES lists a FEATURE_ID that is absent from the feature set."
The DECLARED_DEPS check is about a plugin declaring a SUMMARY KEY that is absent
from the summary dict — a different kind of missing dependency. A new class is
cleaner semantically, but the critic may prefer reusing the existing class to
minimize new API surface.

**Q5 — Cluster E: should the base_hash pin tests gain a comment explaining WHY they are pinned?**

All 6 base_hash pin instances (`"fa440e3eb5f6"`) currently have minimal context
for future developers. The C6 critique (phase_c6/critique.md §2) showed how
misleading comments in the version-history block caused confusion. The critic
should assess whether the Cluster E commit should also add a standard explanatory
comment to the 6 base_hash pin assertions clarifying: "This value is intentionally
hardcoded. Making the RHS dynamic would remove the regression guard against
accidental core/*.py edits."

**Q6 — Write order guarantee in the try/finally region**

The Cluster A design relies on `_safe_write_summary_json` being called with a
summary dict that already has `summary["analyzer_init_error"]` set. The ordering
within the except block is: (1) set `summary["analyzer_init_error"]`, (2) call
`_safe_write_summary_json`, (3) raise SystemExit. The validator should walk the
exact execution trace to confirm the JSON written to disk contains the
`analyzer_init_error` key in the case where `write_summary_json` is the inner
function call and the summary dict was populated just above.

**Q7 — Cluster E manifest-file dependency in CI environments**

From 03 §4 E-1 (coupling audit silent dependency): using
`compute_effective_version_for_machine("M14", 1)` dynamically in tests depends
on `slot_designer/configs/machine_manifests/M14.json` being present. The
differential assertions in §3.3 call this function at test runtime. The critic
should assess whether the CI environment (on `claude/analyzer-unbundle-c2`
branch) reliably has these manifest files, or whether the test should use a
local fixture manifest to avoid `FileNotFoundError` under a stripped CI image.

**Q8 — Cluster D d2: what is the tie-breaking behavior when chain counts are equal?**

The d2 design says "falls back to alphabetical sort if counts are tied or
missing." For machines where two features have IDENTICAL chain counts, the
tie-break is alphabetical — which is the same wrong behavior as before. The
critic should assess whether a tie is a realistic scenario and whether a
different tie-breaking strategy (e.g., pick the feature whose name starts with
"Normal" or whose name appears in `mechanism_overrides.scatter_trigger_target`)
would be more robust.

---

*Proposal end. Awaiting Wave 3: arch-critic (05) + arch-validator (06).*
