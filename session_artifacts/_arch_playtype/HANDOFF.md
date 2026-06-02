# HANDOFF — play-type re-architecture (READ THIS FIRST)

> As of 2026-06-02. Branch `claude/playtype-rearch`, HEAD `8445312`. Companions: `DIRECTION.md`
> (signed-off design/requirements) and **`CARVE_METHODOLOGY.md`** (how to carve + the acceptance gate).
> Every claim here is backed by a runnable check. If something doesn't match the code, trust the code
> and `CARVE_METHODOLOGY.md §0` — do not inherit a label on faith.

## TL;DR (honest state — no labels, just what's true)
- Framework built + wired (commits A–C3); flag `--use-play-type-plugins` default **OFF**.
- **C2's BCM "carve" is HOLLOW.** The cycle logic (`compute_robot_cycle_peaks` etc.) stayed in
  `round_classification.py`, a base-closure file; editing it still flips `base_hash` → **zero
  isolation**. It was mislabeled "first real carve / MILESTONE". It must be **redone**
  (move the BCM functions into `bcm_base.py`) per `CARVE_METHODOLOGY.md`.
- **PT-7 wild-nudge (commit `8445312`) is the FIRST GENUINE carve.** `is_wild_nudge_round` was moved
  OUT of the closure into `play_types/wild_nudge.py`; editing it leaves `base_hash` unchanged (proven
  by the gate test). This is the **reference implementation** for every future carve.
- **Genuine play-types carved: 1 (PT-7).** Hollow shell still needing a real carve: BCM cycle (C2).
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
| `6b10942` | **C2** BCMBasePlugin | ⚠ **HOLLOW** — logic still in closure; zero isolation; REDO |
| `63dd609` | **C3** per-machine config layer (BCM bonus_feature off the silent side-file) | byte-identical |
| `cb35679` | docs handoff (this file's prior version) | — |
| `8445312` | **PT-7 wild-nudge — FIRST GENUINE carve** | ✅ isolated (base_hash gate) + byte-identical + engaged |

## Verification status (re-run; do not trust labels)
- HEAD `8445312` suites green: **1353 passed** (`tests/analyzer/` + the re-pinned backend tests)
  + **222 passed** (`test_play_type_{framework,wiring,c1_fixes,c3_machine_config}` + `test_bcm_base`).
  13 integration-skips.
- Isolation gate (the one C2 lacked): `pytest tests/backend/test_wild_nudge_carve.py` (11 tests) pins
  "edit `wild_nudge.py` → base_hash unchanged; edit `round_classification.py` → flips".
- `base_hash` is `48eada424d82` (was `fd5f7d01e1cb` pre-wild-nudge — the move edited closure files, an
  expected one-time shift; the 8 base_hash-pin tests were re-pinned with reason).
- Prior fresh-session re-verify (recorded in memory): on a CLEAN tree the C-phase output byte-identical
  suite is 189/189 and canonical-md5 19/19 — the "task #8 reds" were **dirty-tree `configs/machines.json`
  drift**, not a real failure. `git stash push -- configs/machines.json` before running md5/canonical tests.

## What's genuinely done vs not
- **DONE (genuine, isolated):** PT-7 wild-nudge.
- **HOLLOW — must redo per methodology:** BCM cycle (C2). `compute_robot_cycle_peaks`, `detect_cycle_peak`,
  `at_cycle_peak_indices`, `infer_bcm_target_spin_type`, `get_collect_count` are all still in
  `round_classification.py` (closure); `bcm_base.py` just calls them. Redo = move them into `bcm_base.py`.
- **NOT STARTED:** PT-1 pure-paid, PT-2 scatter, PT-8 TopDollar, PT-9/10/11 lock-*, PT-12 win-respin,
  PT-13 minigame, PT-14 multi-collection, PT-15 wheel — and the heavy **Phase-2 trigger-session /
  win-attribution carve** (`trigger_sessions.py` + `round_win.py` rule classes). Phase-2 is the linchpin:
  it unlocks isolation for freespin/minigame/lockreels/scatter/TopDollar at once AND closes the 4 layer-2
  attribution gaps above.

## How to carve
**Read `CARVE_METHODOLOGY.md`.** One paragraph: move the logic OUT of the closure into a base-excluded
module; prove with the **base_hash gate** (edit the carved logic → hash unchanged; edit a universal fn →
hash flips) + **byte-identical** (on a machine that actually exercises the mechanic — deep-parse to
confirm its rounds are present) + **engagement** (corrupt it → parser output changes). **byte-identical
ALONE is NOT enough** — that is what let the hollow C2 pass. PT-7 wild-nudge (`8445312`) is the worked example.

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
- Genuine carve (REFERENCE): `fresh_slotlab/analyzer/play_types/wild_nudge.py` + `tests/backend/test_wild_nudge_carve.py`
- Hollow carve (REDO): `fresh_slotlab/analyzer/play_types/bcm_base.py` (calls into `round_classification.py`)
- Framework: `fresh_slotlab/analyzer/play_types/{_base,_probe,_claim,_plugin,_machine_config,_detector}.py` + `play_type_registry.py`
- Wiring + flag: `fresh_slotlab/analyzer/core/parser.py::parse_chunk_response` (`use_play_type_plugins`)
- Closure list (what `base_hash` covers): `fresh_slotlab/analyzer/versioning.py::_CLOSURE_FILES`
- Per-machine configs: `configs/play_type_configs/<M>/mode_<n>.json`
