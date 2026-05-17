# Ticket P1-A2 — Resolution

> Main session consolidation of W1 + W2 rounds 1+2.

---

## Decision: **SHIP** (round 2 closed both R1+R2 blockers; RR3 brief-typo also fixed by main session)

| Source | Round 1 | Round 2 |
|---|---|---|
| impl-tester | sufficient (29 tests, 3/3 inject-bug) | sufficient (30 tests, R1+R2 fixed, 2/2 round-2 inject-bug) |
| impl-verifier | PASS (5/5 C, asymmetry confirmed) | PASS (R1 verified at 8 callsite lines; R2 verified at 2206 callsite; 30/30 targeted, 2256/2265 full suite) |
| impl-critic | APPROVE-WITH-REVISIONS (R1 stub / R2 vacuous / R3 brief typo) | APPROVE-WITH-REVISIONS (RR1 verifier absent → resolved by round-2 verifier; RR2 R2 RED prose-only → non-blocking accept; RR3 P1-B1 brief typo → already fixed) |

---

## Round 1 → Round 2 deltas

**R1 (stub→real α call)**: All 5 C1+C2 agreement tests now call `pia._lookup_machine_md5` directly (verified at test lines 163, 254, 282, 323, 400, 697, 774, 920 per round-2 verifier). The 3 remaining `_patched_alpha_lookup` uses are justified: 2 inject-bug scenarios (wrong-machine + monkeypatch seed) + 1 malformed-JSON edge case where the real function's hardcoded path cannot be safely redirected. Inject-bug spot-check: monkeypatch real α to wrong value → Diverge=True; revert → Agree=True.

**R2 (vacuous→call-site split-path)**: Replaced `test_c5_module_global_split_path_alpha_uses_call_not_global` (which only proved `setattr` works on a module attribute — trivially true) with `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr`. New test invokes real `pia._save_chunk_cache` (production function at `fresh_slotlab/player_impact_analyzer.py:2162`); call site at line 2206 is bare `_lookup_machine_md5(machine)` with no local alias. Monkeypatches lookup to sentinel values; reads back `chunk_0000.json` from disk; asserts sentinel propagated. Manual round-2 spot-check confirmed buggy cached-local would NOT propagate the sentinel.

**RR3 (P1-B1 brief tuple-order typo)**: Critic round 1 caught that P1-B1 brief documented `lookup_machine_md5(...) -> (code_md5, config_md5)` while actual `_lookup_machine_md5` at player_impact_analyzer.py:2138 returns `(config_md5, code_md5)`. Main session fixed the brief in this commit (config_md5 first per actual return order; added explicit "do not flip" note). When P1-B1 ticket runs, implementer uses correct tuple order.

**RR2 non-blocking accept**: R2's RED simulation is documented in 03_tests.md prose but not encoded as a separate executable test. The R2 GREEN test (`test_c5_save_chunk_cache_propagates_sentinel_via_module_attr`) inherently covers the RED case — if `_save_chunk_cache` used a cached local instead of live attribute, the monkeypatch wouldn't affect the call site and the sentinel wouldn't propagate → assertion fails. So the GREEN test naturally guards both directions. Per memory `feedback_adversarial_self_review.md`: accepting non-blocking critic findings with documented rationale is OK; not moving-goalposts.

---

## Pytest results

- Targeted (`tests/backend/test_summary_md5_writer_parity.py`): 30/30 pass, no flakiness
- Full suite: 2256/2265 (7-9 pre-existing baseline failures; mtime-flaky variance per round-2 verifier)
- Regressions in untouched areas: 0

---

## Real vs virtual md5 asymmetry — verified architectural fact

Round-1 verifier surfaced + round-2 confirmed:
- `configs/machines.json` (real machines): FLAT schema, no `modesMd5` field, single md5 shared across all modes
- `slot_designer/configs/machines_virtual.json` (virtual machines): PER-MODE schema, `modesMd5` field with distinct hashes per mode (M1sim has 4 distinct hashes for modes 1/2/5/7)
- Consequence for downstream P1-B1/P1-B2: `_get_machine_md5` β already handles both schema variants via `modesMd5` branch check; dedup must preserve this asymmetry

This finding will be cited in P1-B1's 00_ticket if the brief needs updating; otherwise the asymmetry is implicitly covered by C2 + C3 contracts in this ticket.

---

## Commit reference

Commit `<sha>` on `claude/stoic-napier-f0ea00`. Includes:
- `tests/backend/test_summary_md5_writer_parity.py` (NEW, 30 tests)
- 6 markdown artifacts in `session_artifacts/_impl/phase1/03_three_summary_md5_writer_parity/` (00 ticket, 03 tests R1+R2 round-2 section, 04 verification rounds 1+2, 05 critique rounds 1+2, 06 resolution this doc)
- `session_artifacts/_impl/phase1/07_lookup_machine_md5_dedup/00_ticket.md` (RR3 brief tuple-order typo fix, 2-line edit)
