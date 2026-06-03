# impl-critic: Phase E (M15 TopDollar ST=14 behavioral stats) — critique

**Date:** 2026-06-03 · **Branch:** `claude/playtype-rearch` · **Base:** Phase D `96300c4`
**Verdict:** APPROVE-WITH-FIXES (2 required) → all fixes applied by coordinator; see resolutions.

## Verdict rationale
Implementation is structurally sound. Feature correctly produces ST=14 behavioral stats; isolation gate works
(`topdollar_choice.py` not in `_CLOSURE_FILES`); `RTP_CONTRIBUTION=False` correct; byte-identical gated against a
real pre-change golden. The carve is genuine: the COMPUTATION is in the base-excluded feature; the ST=14
EXTRACTION in parser.py is shared infra (same pattern as every feature — bonus_chain/collect_mechanic).

## Required fixes (both RESOLVED by coordinator before commit)
1. **[SERIOUS] R-4 fleet guard gap** — `tests/analyzer/test_honesty2_drift_guard.py` `plugin_paths` list
   (`test_registered_plugin_edit_does_not_flip_base`) did not include `topdollar_choice.py`, leaving the
   fleet-wide "registered plugin edit doesn't flip base_hash" guard blind to the new plugin.
   → **RESOLVED**: added `"fresh_slotlab/analyzer/features/topdollar_choice.py"` to the list + comment 9→10.
2. **[SERIOUS-as-claim] settled_win_median possible target-fit** — `sorted[n//2]` (upper-median) gives 40000 =
   spec; the tester re-derived with the SAME formula, so the median match was self-consistent, not formula-agnostic.
   → **RESOLVED**: coordinator independently computed the two middle settled values from cached chunks —
   `sorted[219] == sorted[220] == 40000`. The median is FORMULA-AGNOSTIC (lower/upper/average all = 40000); the
   match is unambiguous, not target-fitted. Removed the dead `from statistics import median` import.

## Minor (cosmetic — applied)
- Renamed `test_nine_plugins_registered` → `test_ten_plugins_registered` (`test_c6_carve_completion.py`).
- Updated "9 plugins" docstring → "10 plugins" (`test_c6_bonus_chain_dynamics_plugin.py`).

## Verified by the critic (no fix needed)
- Genuine carve: editing `topdollar_choice.py` leaves base_hash unchanged + changes M15-only effective_version;
  parser.py addition is a true no-op for non-ST14 machines (byte-identical for M14).
- Committed state correct: M15.json staged (+topdollar_choice) + HEAD's other manifests → feature is M15-only;
  no path leaks the feature onto other machines in the committed repo.
- RTP integrity: `rtp_contribution_pp` is informational; `sum(pay_id.rtp_pp)==summary.rtp` holds.
- base_hash re-pins complete (`8a791a69cd05`→`adf08191dd9c`); no old-literal assertion left.
- 3 inject-bugs proven (bad_gamble, closure-leak, RTP-flag); 49 new tests.

## PRE-EXISTING finding surfaced (NOT Phase E; for follow-up)
- The R-1 drift guard `test_no_content_module_missing_from_closure` is import-order-fragile and reveals that the
  bare function-carves `bcm_cycle`/`wild_nudge` are base-excluded but NOT per-machine-hashed → editing them
  re-flags NOTHING (stale-report risk). Fails identically at `88d212e` (pre-Phase-A) in isolation; passes in the
  full suite only because the carve tests pre-import the modules. topdollar_choice does NOT have this gap (proper
  feature). Recommend migrating the function-carves to features (or wiring their hash into BCM effective_version).

## Informational (low priority, not blocking)
- `dollar_counts` accumulated in parser.py but not consumed by emit() (forward-looking; or drop).
- `OfferValue` parse-failure falls back to 0 silently (unlikely; could add a diagnostic).
- PIA registration block ~2131 asymmetry (pre-existing pattern; Phase E mirrored it).
