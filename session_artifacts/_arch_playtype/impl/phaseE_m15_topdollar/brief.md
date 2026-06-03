# Phase E (impl) — M15 TopDollar ST=14 player-choice behavioral stats (additive feature)

> Coordinator brief for the impl-* team. Branch `claude/playtype-rearch`, on top of Phase D (`96300c4`).
> Goal: build the **first real instance of the event model** — a base-excluded analyzer feature that
> computes the **ST=14 player-CHOICE behavioral statistics** for M15 TopDollar, per the validated spec in
> `../../02_traces.md`. **ADDITIVE**: existing M15 economy output stays byte-identical; this only ADDS a new
> summary section. Scope: **M15 only** (user-confirmed 2026-06-03); design to generalize to the TopDollar
> family later but validate on M15. Read `../../DIRECTION.md` (the event model) first.

## 0. Why this is the build (recon already done by coordinator)
- M15's **economy is already correct**: `round_win.SettlementWinAmountRule` suppresses the ST=14 offer preview
  (`WinCredits`→0) and books the real win on ST=15 `WinAmount`; `trigger_sessions.py` does the ST=1
  `ReMarks="Trigger"`→session attribution (validated there: M15 $0$ 2238 sessions sum = 105,665,000 =
  `FeatureWin.TopDollar.total_win` exactly). So do NOT touch economy/RTP — it is done and must stay byte-identical.
- The **gap** = the ST=14 *behavioral* statistics (the "1.1% event carrying ~50% RTP; 46% gamble-to-4th; 45% of
  those a bad gamble" insight) are NOT a computed analyzer output. This phase computes them.
- The analyzer's **feature system already gives the isolation goal**: feature modules live in
  `fresh_slotlab/analyzer/features/` (base-EXCLUDED — NOT in `versioning._CLOSURE_FILES`); each self-registers via
  `feature_registry.register(...)` at import; `compute_effective_version_for_machine` = `hash(base_hash + that
  machine's feature hashes)`. → editing this new feature later re-flags ONLY M15. This is a genuine carve by construction.

## 1. The validated target (from 02_traces.md — the gate's ground truth)
M15 mode_1, 5 chunks, 440 TopDollar sessions / 40,000 base spins. The feature output MUST reproduce:

| stat | target |
|---|---|
| picks-per-session (1 / 2 / 3 / 4) | 104 / 66 / 69 / 201 |
| stopped-early vs forced-4th | 54.3% / 45.7% |
| bad-gamble (forced 4th < a passed offer) | 91 / 201 = 45.3% |
| final settled value | median 40k, max 440k |
| dollar tiers (5/10/20/50/100) | 2188 / 1030 / 230 / 22 / 2 |
| trigger rate | 440 / 40000 = 1.10% |
| TopDollar RTP contribution | 50.4% |

ST=14 fields: `DollarCount`, `ChosenDollar` (e.g. "5-10-5"), `OfferValue`. ST=1 `ReMarks="Trigger"` opens a
session; ST=15 `WinAmount` = the settled win. (Deep-parse cached chunks with `json.loads` on the JSON-string
`response`; a raw grep false-negatives on escaped JSON. Read UTF-8.)

## 2. Deliverables
1. **New feature module** `fresh_slotlab/analyzer/features/topdollar_choice.py` — an `AnalyzerFeature` subclass
   (read `features/_base.py` for the exact ABC: `FEATURE_ID`, `SCHEMA_KEYS`, `SCHEMA_VERSION`, `REQUIRES`,
   `DECLARED_DEPS`, `RTP_CONTRIBUTION`, + `extract`/`reduce`/`emit`). **`RTP_CONTRIBUTION = False`** (economy is
   already counted by SettlementWinAmountRule — this feature must NOT add to the RTP sum or the RTP integrity gate
   double-counts). No import-time side effects beyond the standard self-`register()` call.
   - Decompose the per-session stats into extract (per-round) → reduce (fold) → emit (final table). The stats are
     SESSION-level (group ST=14 picks by the TopDollar session opened by ST=1 `ReMarks="Trigger"`). **Read a
     sibling that already does session/multi-round aggregation** — `features/bonus_chain_dynamics.py` and
     `features/collect_mechanic.py` are the closest patterns; mirror their extract/reduce/emit decomposition,
     their RoundCtx/round access, and how they read trigger-session structure (check whether session grouping is
     available via a `DECLARED_DEPS` temp-key PIA stashes, e.g. from `trigger_sessions.py`, or must be derived).
   - "bad-gamble" = a session that went to the forced 4th pick whose final `OfferValue` was LESS than an
     `OfferValue` it had already passed earlier in the same session. Derive precisely from `ChosenDollar` /
     `OfferValue` per the 02_traces definition; if the exact per-pick offer sequence isn't recoverable from the
     fields, STOP and report what IS recoverable rather than guessing.
2. **Register it**: add `import fresh_slotlab.analyzer.features.topdollar_choice` (+ the `analyzer.features...`
   standalone-mode twin) at the EXISTING feature-registration sites — `versioning.py` (~296-312) and
   `player_impact_analyzer.py` (the ~1446/2124/4438 blocks). These are closure files → base_hash flips ONCE
   (the accepted one-time onboarding cost, like every prior `# C4/C5/C6` feature). Re-pin (see §4).
3. **Apply it to M15**: add `"topdollar_choice"` to `analyzer_features` in
   `slot_designer/configs/machine_manifests/M15.json`. ⚠ That file is DELETED in the working tree (pre-existing
   junk) but COMMITTED at HEAD — restore it surgically first: `git checkout HEAD --
   slot_designer/configs/machine_manifests/M15.json`, then add the entry. Stage ONLY M15.json from slot_designer/
   (leave the other ~618 slot_designer deletions untouched). If M15 has a variant/inheritance manifest, follow the
   `analyzer_features_add` rule in `manifest_loader.py` (§ resolve_per_mode) rather than editing a forbidden field.

## 3. Gates (impl-tester + impl-verifier — all required)
1. **Existing M15 output byte-identical (additive-only)**: capture golden from a CLEAN pre-change tree, run M15
   post-change, diff. EVERY pre-existing field must be unchanged; the ONLY delta allowed is the new
   `topdollar_choice` summary section. Also spot-check one non-TopDollar machine (e.g. M14) is byte-identical
   (it doesn't list the feature → must be untouched). Normalize volatile fields per `../golden_baseline.md`.
2. **Stats match the 02_traces target (§1)**: run M15 full 5 chunks; assert the feature output reproduces the
   table (104/66/69/201; 54.3/45.7; 45.3%; tiers 2188/1030/230/22/2; 1.10%; ~50.4% RTP). Tolerate only
   rounding. If a stat can't be reproduced, that's a real finding — report it, don't fudge the target.
3. **per-feature isolation gate (the carve property)**: a permanent test asserting (a) editing
   `topdollar_choice.py` leaves **base_hash UNCHANGED** but changes **M15's effective_version**; (b) a
   non-TopDollar machine's effective_version is UNCHANGED by it. Mirror `test_bcm_cycle_carve.py` /
   `test_c3_5_isolation_m275_only.py`. Inject-bug: corrupt the feature → M15 stat output changes (engagement) →
   revert → restored.
4. **RTP integrity**: confirm `RTP_CONTRIBUTION=False` keeps `sum(pay_id.rtp_pp)==summary.rtp` intact (the
   feature must not perturb the RTP invariant). Run the rtp_integrity gate.
5. **base_hash re-pin**: the registration import flips base_hash `8a791a69cd05`→NEW. Re-pin all 8 pins (grep
   `tests/` for `8a791a69cd05`) with a documented reason ("Phase E registered the topdollar_choice feature →
   closure import add → base_hash X→Y; M15-only applicability; existing output additive-only").
6. **e2e subprocess** (`feedback_perf_claim_needs_e2e_event_stream.md`): real `python -m
   fresh_slotlab.player_impact_analyzer --machine M15 --rtp-mode 1 --from-cache ... ` — assert the new section
   appears with the right numbers AND existing RTP/economy unchanged; M14 run shows NO topdollar_choice section.

## 4. Memory feedback to honor
- `feedback_self_verify_output.md` + `feedback_adversarial_self_review.md` — cross-check the stats against
  02_traces + RTP/feature_tally before claiming; dump actual numbers.
- `feedback_no_hardcode.md` — don't hardcode M15-specific field semantics in a shared place; the feature reads
  ST/fields generically (TopDollar family), applicability is the manifest list.
- `feedback_aggregator_parity_invariant.md` / `feedback_invariant_with_fallback_hides_drift.md` — keep RTP parity;
  no new `_unattributed`/fallback bucket that hides drift.
- `feedback_no_parallel_panel_impl.md` — if this adds a web-console panel later, reuse sibling renderers; for THIS
  phase (analyzer output only) mirror a sibling feature's summary-section shape; do NOT invent a parallel structure.
- Surgical commits — stage explicit paths only; NEVER `git add -A` (618 pre-existing slot_designer deletions +
  cache/reports/machines.json junk in the tree). Restore M15.json from HEAD; stage only it from slot_designer/.
- `feedback_subprocess_import_suicide_and_module_globals.md` — feature self-registers idempotently; no other
  import-time side effects.

## 5. Out of scope (do NOT)
- Do NOT touch M15 economy / RTP / SettlementWinAmountRule / trigger_sessions (already correct; must stay byte-identical).
- Do NOT build the web-console panel (analyzer output only this phase).
- Do NOT generalize to M12/M90/M132/M206 (M15-only; design cleanly so it CAN later).
- Do NOT restore the other slot_designer/ deletions (only M15.json).

## 6. Deliverable
Uncommitted tree (implementer) → tests + inject-bug (tester) → e2e + isolation report (verifier) → critique.md
APPROVE/REJECT (critic). Coordinator commits on APPROVE with the §5 reason + gate results.
