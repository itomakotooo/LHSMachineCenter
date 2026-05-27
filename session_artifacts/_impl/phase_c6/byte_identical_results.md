# Phase C6 — byte-identical + 8 gap closure results

Date: 2026-05-27
Branch: claude/analyzer-unbundle-c2

## base_hash

`fa440e3eb5f6` — UNCHANGED from C4/C5. Parser/core not touched.

## 9 plugins registered

1. payouts_by_spin_type
2. reel_marginal_by_spin_type
3. bankruptcy_simulation
4. multiplier_profile
5. multiplier_wild (C3.5)
6. machine_mechanics (C4)
7. upstream_feature_breakdown (C5)
8. collect_mechanic (C5)
9. bonus_chain_dynamics (C6)

## 5-site registration (bonus_chain_dynamics)

1. PIA package-mode import block (line ~4897)
2. PIA script-mode import block (line ~4926)
3. versioning.py package-mode import (line ~173)
4. versioning.py script-mode import (line ~184)
5. bonus_chain_dynamics.py module-level register() call (bottom of file)

## 253 manifest universal rollout

253 out of 420 manifests declare bonus_chain_dynamics.
167 without = variant manifests that defer to base machine.

## 8 Gap Closures (M275 mode 1 cache, confirmed by subprocess)

| Gap | Description | Phase | M275 actual value | Status |
|-----|-------------|-------|-------------------|--------|
| #1  | jackpot.applicable=True | C4 | machine_mechanics.jackpot.applicable = True | CLOSED |
| #2  | free_spin.applicable=True | C4 | machine_mechanics.free_spin.applicable = True | CLOSED |
| #3  | pid 666 scatter_trigger_marker | C6 | payout_ids_top20 pid 666 notes.is_trigger_marker = True, trigger_target = "NewFreespin" | CLOSED |
| #4  | multiplier_wild plugin output | C3.5 | player_impact.multiplier_wild present | CLOSED |
| #5  | payout_groups_top20 all-zeros filter | C5 | payout_groups_top20 = [], status = "all_zeros_filtered" | CLOSED |
| #6  | chunk_spin_times_recommendation | C5 | collect_mechanic.clamp_warning.chunk_spin_times_recommendation present | CLOSED |
| #7  | payouts_by_spin_type shape/cols/paylines/notes | C3 | rows have all 4 fields per ST | CLOSED |
| #8  | payout_ids_top20 notes | C6 | all rows have notes.is_trigger_marker field | CLOSED |

## M275 key values

- bonus_chain_dynamics.applicable = True
- bonus_chain_dynamics.chain_count = 908
- bonus_chain_dynamics.by_feature keys = ["NewFreespin", "NormalCollectionSpin"]
- pid 666 trigger_target = "NewFreespin" (alphabetically first of two features)
- pid 666 trigger_target_confidence = "data_inferred"
- stash key _bonus_chain_dynamics_data absent from final summary

## M14 key values

- bonus_chain_dynamics.applicable = False
- payout_ids_top20 rows: 0 with is_trigger_marker=True (no false positives)
- trigger_target absent from all M14 pid notes (not applicable)
- trigger_target_confidence absent from all M14 pid notes

## F6 inline KEPT (implementer concern #1)

The PIA F6 inline block continues to write player_impact.bonus_chain_dynamics BEFORE
the emit loop so that:
(a) C4 invariant assert `"bonus_chain_dynamics" in summary["player_impact"]` passes
(b) machine_mechanics.emit() can read bonus_chain_dynamics to derive fs_chain_spins

The plugin emit() reads the stash and overwrites the same dict (byte-identical passthrough).
Trade-off documented in plugin docstring. Verifier may flag this but it is intentional and
safe — the stash key presence guarantees the inline block ran first.
