# HANDOFF — play-type re-architecture (READ THIS FIRST)

> As of 2026-06-02. Branch `claude/playtype-rearch`, HEAD `c21eb4e`. Companions: `DIRECTION.md`
> (signed-off design/requirements) and **`CARVE_METHODOLOGY.md`** (how to carve + the acceptance gate).
> Every claim here is backed by a runnable check. If something doesn't match the code, trust the code
> and `CARVE_METHODOLOGY.md §0` — do not inherit a label on faith.

> **⚠ MODEL CORRECTED (2026-06-02) — read `DIRECTION.md §12`.** The play-type UNIT is the **trigger-session,
> NOT the SpinType**. Two layers: shared round-PARSING (by round type) vs trigger-session 统计口径 (by trigger).
> Same reward ST (freespin) via BCM vs scatter = identical parse, different 口径 → different play-types (real:
> M275). So `ST → one play-type` is false; the per-ST detector is insufficient; PT-2 ≠ PT-4; and the
> **trigger-session / win-attribution layer is the CORE**, not the deferred "Phase-2" framed below. PT-7
> wild-nudge is a shared round-CLASSIFIER, not a trigger-rooted play-type.

## TL;DR (honest state — no labels, just what's true)
- Framework built + wired (commits A–C3); flag `--use-play-type-plugins` default **OFF**.
- **2 GENUINE carves done** (logic moved OUT of the closure → editing it no longer re-flags the fleet;
  each proven by a per-carve base_hash gate test):
  - **PT-7 wild-nudge** (commit `8445312`) — `is_wild_nudge_round` → `play_types/wild_nudge.py`.
  - **PT-3 BCM cycle** (commit `c21eb4e`) — the 5 cycle fns (`detect_cycle_peak`,
    `compute_robot_cycle_peaks`, `get_collect_count`, `at_cycle_peak_indices`,
    `infer_bcm_target_spin_type`) → `play_types/bcm_cycle.py`. This **redid C2**, which had shipped
    HOLLOW (logic left in the `round_classification.py` closure; the plugin just called it → zero
    isolation; was mislabeled "MILESTONE"). `bcm_base.py` (the plugin) now imports from `bcm_cycle`.
  - Method + reference: `CARVE_METHODOLOGY.md`. PT-7 (1 fn) and PT-3 (5-fn cluster) are both worked examples.
- **Correctness is NOT "all clean."** 4 of 9 golden pilots carry a pre-existing layer-2 `_unattributed`
  fallback (M15 ~39pp, M268 ~40pp, M272/M279 ~4pp; `rtp_integrity_check.layer2_ok=False`). The branch
  preserves these **byte-identically (not a regression)**, but they are real per-pay_id attribution
  gaps, **DEFERRED by user decision (2026-06-02)**. The Phase-2 win-attribution carve is the lever that
  closes them — so remaining work is NOT "zero correctness value", just deferred by choice.

## Committed (branch `claude/playtype-rearch`)
| commit | what | status |
|---|---|---|
| `6ab4f8a` | docs — design (DIRECTION + W1–W3 + 04_v2) | — |
| `7babf1e` | **A** framework: `play_types/` + registry. Inert. | byte-identical |
| `ff5935c` | **B** wired into `parse_chunk_response`; flag default OFF. Dormant. | byte-identical |
| `adc42f6` | **C1** plumbing: per-ST ownership + 5 wiring fixes | byte-identical + inject-bug |
| `6b10942` | **C2** BCMBasePlugin | shipped HOLLOW (logic stayed in closure) — superseded by `c21eb4e` |
| `63dd609` | **C3** per-machine config layer (BCM bonus_feature off the silent side-file) | byte-identical |
| `cb35679` | docs handoff (prior version) | — |
| `8445312` | **PT-7 wild-nudge — GENUINE carve** | ✅ isolated (base_hash gate) + byte-identical + engaged |
| `cb888be` | docs — CARVE_METHODOLOGY + clean overclaims | — |
| `c21eb4e` | **PT-3 BCM cycle — GENUINE carve (redo of C2)**: 5 cycle fns → `bcm_cycle.py` | ✅ isolated + byte-identical (5 pilots) + engaged |

## Verification status (re-run; do not trust labels)
- HEAD `c21eb4e` suites green: **1221 passed** (`tests/analyzer/` + `test_bcm_base` + play-type framework)
  + the fast pin/gate runs (447 + 375 passed). Integration-skips only.
- Isolation gates (the property C2 lacked): `pytest tests/backend/test_wild_nudge_carve.py` (11) +
  `tests/backend/test_bcm_cycle_carve.py` (7) — each pins "edit the carved module → base_hash unchanged;
  edit `round_classification.py` → flips".
- `base_hash` is `85666c4c4407` (chain: `fd5f7d01e1cb` → `48eada424d82` [wild-nudge] → `85666c4c4407`
  [BCM carve]; each move edits closure files = expected one-time shift; the 8 base_hash-pin tests re-pinned).
- Prior fresh-session re-verify (recorded in memory): on a CLEAN tree the C-phase output byte-identical
  suite is 189/189 and canonical-md5 19/19 — the "task #8 reds" were **dirty-tree `configs/machines.json`
  drift**, not a real failure. `git stash push -- configs/machines.json` before running md5/canonical tests.

## What's genuinely done vs not
- **DONE (genuine, isolated):** PT-7 wild-nudge (`wild_nudge.py`) + PT-3 BCM cycle (`bcm_cycle.py`).
- **NEXT = the CORE (per `DIRECTION.md §12`), not deferred:** design + carve the two-layer model — a **shared
  round-parsing library** (freespin / wheel / respin / paid, keyed by round type) + the **trigger-session
  attribution layer** (`trigger_sessions.py` + `round_win.py`) that decides 统计口径. This layer DEFINES the
  play-types (a play-type = trigger + attribution + rollup) and also closes the 4 layer-2 gaps above. The W2
  design round (arch-*) produces this design from §12.
- **NOTE on the old play-type list:** PT-1 "pure-paid" is the BASE (not a carve-able play-type); PT-2 / PT-4 /
  etc. are trigger-rooted sessions that SHARE parsers (same ST, different 口径). Do NOT carve them per the old
  per-ST model — they get re-derived as trigger-rooted play-types in the §12 design.

## How to carve
**Read `CARVE_METHODOLOGY.md`.** One paragraph: move the logic OUT of the closure into a base-excluded
module; prove with the **base_hash gate** (edit the carved logic → hash unchanged; edit a universal fn →
hash flips) + **byte-identical** (on a machine that actually exercises the mechanic — deep-parse to
confirm its rounds are present) + **engagement** (corrupt it → parser output changes). **byte-identical
ALONE is NOT enough** — that is what let the hollow C2 pass. Worked examples: PT-7 wild-nudge (`8445312`,
1 fn) and PT-3 BCM cycle (`c21eb4e`, 5-fn cluster — the redo of the hollow C2).

## Other resume notes
- **Test isolation:** `ALL_PLAY_TYPE_PLUGINS` is a module global → every test file relying on the registry
  needs a module-level autouse snapshot/restore fixture (`test_bcm_base.py` 146–159), else engagement tests
  flake cross-file. Per `feedback_subprocess_import_suicide_and_module_globals.md`.
- **⚠ Background agents died silently TWICE** in an earlier session — run agents FOREGROUND / check liveness
  early; don't blind-wait on a background spawn.
- **Surgical commits:** the tree has pre-existing junk (`configs/machines.json`, `cache/`, `reports/`, prior
  `session_artifacts/_impl`) — never `git add -A`; stage explicit paths.
- **base_hash-pin re-pin:** any closure-touching change shifts `base_hash`; re-pin the 8 pin tests
  (`test_analyzer_core_parser`/`_aggregator`, `test_wave_2c_universal_features`,
  `tests/analyzer/test_c3_5`/`c3`/`c5`/`c6`) to the new value with a documented reason.

## File map
- **Methodology:** `CARVE_METHODOLOGY.md` (read before carving)
- Design record: `DIRECTION.md` (§1–11) + `01_pipeline_map` / `02_taxonomy` (15 play-types) / `03_coupling_audit` / `04_v2` / `05_critique` / `06_validation` + `impl/critique_commit{A,B,C1}.md`
- Genuine carves (REFERENCE): `play_types/wild_nudge.py` (+ `tests/backend/test_wild_nudge_carve.py`) and
  `play_types/bcm_cycle.py` (+ `tests/backend/test_bcm_cycle_carve.py`)
- BCM plugin wrapper: `play_types/bcm_base.py` (claim signature + accumulator; imports the cycle logic from `bcm_cycle.py`)
- Framework: `fresh_slotlab/analyzer/play_types/{_base,_probe,_claim,_plugin,_machine_config,_detector}.py` + `play_type_registry.py`
- Wiring + flag: `fresh_slotlab/analyzer/core/parser.py::parse_chunk_response` (`use_play_type_plugins`)
- Closure list (what `base_hash` covers): `fresh_slotlab/analyzer/versioning.py::_CLOSURE_FILES`
- Per-machine configs: `configs/play_type_configs/<M>/mode_<n>.json`
