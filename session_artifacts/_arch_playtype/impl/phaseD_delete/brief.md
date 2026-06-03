# Phase D (impl) — DELETE the play-type layer; align code to the event model

> Coordinator brief for the impl-* team. Branch `claude/playtype-rearch`.
> Goal: remove the repudiated ST-primary play-type plugin framework + its C3 per-machine-config
> wiring from the live path, keeping ONLY the two genuine function carves. **One atomic commit.**
> Read `../../DIRECTION.md` (the event model) + `../../CARVE_METHODOLOGY.md` (the gate) first.

## 0. Why (user-signed direction)
The docs say "**There is NO play-type / PT layer**" but the code still carries the whole framework
(`detect_play_types` / `st_map` / `PlayTypePlugin` / `ClaimSignature` / `bcm_base` plugin / registry +
`configs/play_type_configs/` + flag-gated parser wiring + ~3.8k lines of framework tests). Its core
data structure `st_map[st] = winner.FEATURE_ID` (SpinType → single owner) is exactly the **ST-primary
model that `02_traces.md` M275 proves cannot express** "same SpinType, two triggers, two accounts".
User picked: delete it; keep the 2 function carves; build M15 (Phase B) as a function-carve.

## 1. The byte-identical correctness argument — THIS IS THE NORTH STAR
Deleting all of this is **byte-identical on every real run**. Two independent reasons, both verified by coordinator recon:

1. **The plugin framework is flag-off-dormant.** `--use-play-type-plugins` is `action="store_true",
   default=False` (`base_pipeline.py:282`). The ONLY callers that set it True are the 5 framework test
   files (being deleted). NO production path (web console / batch worker / scripts / configs) passes it.
   → every real run already takes the flag-off (inline) path.

2. **The C3 Layer-0 (`configs/play_type_configs/`) is output-redundant with bcm_pairings Layer-1.**
   `_resolve_bonus_feature` (PIA:673) layers: L0 `play_type_config.get_bcm_bonus_feature()` → `(feat,"config")`;
   L1 `config[machine][mode]` (= `_load_bcm_pairings()`) → `(feat,"config")`; L2 heuristic → `"heuristic"`; L3 → `"none"`.
   - For the 5 pilots, the L0 value **equals** the L1 value (verified: M268 CreditsSymbolRespin / M272,M275
     NewFreespin / M274 ListRewardWheel / M279 Wheel; play_type_configs `source: bcm_pairings_migration`).
   - `_load_bcm_pairings()` (PIA:433) does **NOT filter by confidence** (`if feat: per_mode[mode_int]=feat`,
     line 478) → M279 mode-1 "Wheel" (confidence "medium") **is** in the L1 map.
   - Both L0 and L1 return `source="config"`. So removing L0 → L1 fires → **identical (feature, source)**.
   - The C3 commit `63dd609` itself states: "_resolve_bonus_feature gains layer-0 ... **same VALUE →
     byte-identical** ... Phase-3 retires it." This is that retirement.
   - For all non-pilot machines `play_type_config` is already `None` (no file) → L0 already inert → no change.

**⚠ The #1 thing the tester must PROVE, not assume:** `bcm_bonus_source` is written to the summary output
(PIA:4313) — so the *source string* is byte-identical-compared. The whole argument hinges on L0→L1 keeping
`source=="config"` for the 5 pilots, **especially M279 mode 1 ("Wheel", medium confidence)**. If the
byte-identical gate shows ANY pilot's `bcm_bonus_source` flips config→heuristic/none, STOP and tell the
coordinator (do not relax the gate).

## 2. DELETE — files (surgical; never `git add -A`)
Framework code:
- `fresh_slotlab/analyzer/play_types/_base.py`
- `fresh_slotlab/analyzer/play_types/_claim.py`
- `fresh_slotlab/analyzer/play_types/_detector.py`
- `fresh_slotlab/analyzer/play_types/_machine_config.py`
- `fresh_slotlab/analyzer/play_types/_plugin.py`
- `fresh_slotlab/analyzer/play_types/_probe.py`
- `fresh_slotlab/analyzer/play_types/bcm_base.py`
- `fresh_slotlab/analyzer/play_type_registry.py`

Config data (live result reproduced by bcm_pairings L1):
- `configs/play_type_configs/` (whole dir: M268, M272, M274, M275, M279)

Framework tests (5 — these import the framework / set the flag True):
- `tests/backend/test_play_type_framework.py`
- `tests/backend/test_play_type_wiring.py`
- `tests/backend/test_play_type_c1_fixes.py`
- `tests/backend/test_play_type_c3_machine_config.py`
- `tests/backend/test_bcm_base.py`

## 3. KEEP — do NOT touch (except where noted)
- `fresh_slotlab/analyzer/play_types/wild_nudge.py` + `tests/backend/test_wild_nudge_carve.py` (genuine carve + gate)
- `fresh_slotlab/analyzer/play_types/bcm_cycle.py` + `tests/backend/test_bcm_cycle_carve.py` (genuine carve + gate)
- `configs/bcm_pairings.json` (the LIVE bonus_feature source after this change)
- **⚠ DO NOT DELETE `tests/analyzer/test_c3_*.py`** — these are a DIFFERENT refactor's "C3/C3.5"
  (multiplier_wild / round-level PayoutByPayline enrichment / schema-v2 / trigger-marker), NOT the
  play-type framework. They test LIVE behavior. They only need base_hash RE-PINNING where they pin the
  old value. (Verified: `test_c3_5_isolation_m275_only.py` = multiplier_wild M275-only isolation;
  `test_c3_base_hash_flips_for_round_level_enrichment.py` = PayoutByPayline enrichment.)

## 4. EDIT — closure files (remove framework wiring, keep the inline/live path)
Map the full footprint with grep before editing; the lines below are anchors, not exhaustive.

- **`fresh_slotlab/analyzer/play_types/__init__.py`** — strip the framework re-export block
  (`from ._base import ...`, `_claim`, `_detector`, `_machine_config`, `_plugin`, `_probe` + `__all__`).
  Leave a minimal package docstring. **Critical:** parser imports the carve submodules
  (`play_types.bcm_cycle`, `play_types.wild_nudge`), which triggers `__init__` first — it must NOT import
  any deleted module or the live import breaks. Smoke-test `import fresh_slotlab.analyzer.play_types.bcm_cycle`.

- **`fresh_slotlab/analyzer/core/parser.py`** — KEEP the live carve imports (`from ...play_types.bcm_cycle
  import ...` @73-90; `from ...play_types.wild_nudge import is_wild_nudge_round`). REMOVE:
  - the flag-gated framework import block (`_base.RoundCtx/MechanicAccumulator`, `_detector.detect_play_types`,
    `_machine_config.MachinePlayTypeConfig`, `play_type_registry.get_all_plugins`, `import ...bcm_base`) ~ lines 98-122
  - the `use_play_type_plugins` parameter on `parse_chunk_response` + the `machine_id`/`mode` params that
    C3 added purely to feed `detect_play_types` (confirm via grep they have no other consumer)
  - every `if use_play_type_plugins ...` block (~712-790, 1297-1306, 2202-…, 2243, 2349-…) and the
    `_bcm_base_active` machinery (~783-784). Where `_bcm_base_active` gated inline-vs-plugin
    (`if not _bcm_base_active:` @2441, @2468), the inline carve path must now run **unconditionally**
    (it was the flag-off path = the golden path → byte-identical). Make those calls unconditional.

- **`fresh_slotlab/analyzer/core/base_pipeline.py`** — remove the `--use-play-type-plugins` arg (~278-292)
  and the `use_play_type_plugins` param threading (~585, ~637).

- **`fresh_slotlab/player_impact_analyzer.py`** — remove:
  - the unconditional C3 load block (~3537-3556: the `_MachinePlayTypeConfig` import + `_pia_machine_pt_config = ...read(...)`)
  - the `play_type_config=_pia_machine_pt_config` kwarg at BOTH `_resolve_bonus_feature` call sites (~3569, ~4354)
  - the `play_type_config` parameter + Layer-0 block from `_resolve_bonus_feature` (~680, ~722-730)
  - the `use_play_type_plugins=getattr(args, ...)` threading (~1585, ~2324)
  - Leave `_load_bcm_pairings()` + L1/L2/L3 intact (now the primary path).

## 5. base_hash re-pin (the one-time cost; CARVE_METHODOLOGY §5)
Editing parser.py / base_pipeline.py / PIA (all in `_CLOSURE_FILES`) flips `base_hash` from
`85666c4c4407` → a NEW value. Compute it (`python -c "from fresh_slotlab.analyzer.versioning import
compute_base_analyzer_version as f; print(f())"`) and re-pin **every** occurrence of the old literal.
Grep `tests/` for `85666c4c4407` and update each (anchors: `test_analyzer_core_parser.py:754`,
`test_analyzer_core_aggregator.py:1304`, `test_wave_2c_universal_features.py:737`,
`test_c3_5_isolation_m275_only.py:113`, `test_c6_carve_completion.py:132`,
`test_c6_byte_identical_bonus_chain.py:128`, `test_c5_byte_identical_unrelated_fields.py:117`, and any
others grep finds). Document the reason in each pin's message/comment AND the commit:
"Phase D deleted the play-type framework + C3 Layer-0 wiring from the closure → base_hash X→Y; behavior
byte-identical (framework flag-off-dormant; C3 L0 redundant with bcm_pairings L1)."
**The carve isolation gates (`test_bcm_cycle_carve.py`, `test_wild_nudge_carve.py`) must stay GREEN** —
the carved files are untouched, so editing them must still leave base_hash unchanged.

## 6. Gates (impl-tester + impl-verifier — all required)
1. **byte-identical** (CARVE_METHODOLOGY §4 + `../golden_baseline.md`): capture golden from a CLEAN
   pre-change tree (git stash or a throwaway `git worktree` at HEAD), then compare post-change. Machines:
   the 5 BCM pilots (M268/M272/M274/M275/M279) across the modes present in cache **+ 2 controls**
   (M14 pure-paid, M15 TopDollar). Deep-parse the JSON-string `response` (raw grep false-negatives on
   escaped JSON); read UTF-8; normalize volatile fields (`report_id`,`run_id`,`*_version`,timestamps,
   durations) per golden_baseline.md; KEEP `config_md5`/`code_md5`/all analytical content incl.
   `bcm_bonus_source`. Any KEPT-field diff = gate FAIL.
2. **base_hash gate**: new value computed, all old-literal pins updated, carve isolation gates GREEN.
3. **inject-bug** (mandatory, `feedback_enumerate_safety_paths.md`): prove the carve gates still catch a
   closure edit (edit a closure fn → base_hash flips → gate RED → revert → GREEN).
4. **import smoke**: `import fresh_slotlab.analyzer.core.parser` and `...play_types.bcm_cycle` /
   `...wild_nudge` succeed; `grep -rn "play_type" fresh_slotlab/ src/` returns ONLY the 2 carve files
   (no dangling framework references); `grep -rn "use_play_type_plugins\|play_type_configs\|MachinePlayTypeConfig\|detect_play_types\|play_type_registry" fresh_slotlab/ src/` is empty.
5. **suites**: run the affected backend + analyzer suites green (1221-ish minus the 5 deleted framework
   files). Note the new pass count.

## 7. Memory feedback to honor
- `feedback_enumerate_safety_paths.md` — inject-bug → red → revert → green for the gate.
- `feedback_subprocess_import_suicide_and_module_globals.md` — confirm no import-time side effects added;
  the deleted `bcm_base.py` self-registered at import — make sure nothing else now relies on that.
- Surgical commits — stage explicit paths; the tree has pre-existing junk (`configs/machines.json`,
  `cache/`, `reports/`, other `session_artifacts/`). NEVER `git add -A`.
- `feedback_perf_claim_needs_e2e_event_stream.md` — the verifier spawns a REAL subprocess against cached
  fixtures (M15 + one BCM pilot) and asserts user-visible output unchanged, not just unit greens.
- Worktree Bash may be blocked by a bad hook (per memory) → use PowerShell for git if Bash fails.

## 8. Deliverable
Uncommitted working tree (implementer) → tests + inject-bug evidence (tester) → e2e report (verifier) →
critique.md APPROVE/REJECT (critic). Coordinator commits on APPROVE with the §5 reason + the gate results.
Do NOT start Phase B (M15) in this commit.
