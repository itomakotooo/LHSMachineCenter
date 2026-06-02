# DIRECTION — analyzer re-architecture by play-type (玩法)

> **This is DIRECTION + REQUIREMENTS, NOT a task-start command.** Per the user (2026-05-30): the next session
> must **verify multiple machines' rawdata itself** to derive + validate the play-type taxonomy — do NOT take any
> play-type list on faith, and do NOT begin implementation off a brief. Re-derive from real rawdata + this direction,
> run the arch-* design round, then build.

## 1. Why this exists (what the current architecture does NOT achieve)
Just shipped (on `collab/dev`): honest per-(machine,mode) staleness signal + 9 SHARED display-feature plugins
(byte-identical carve). BUT the **core analysis logic** (chunk parse / round-classification / win-attribution /
mechanism detection) is still in the shared base (~13.5K lines: monolith 5135 + core 4074 + rule engines). So editing
it to support or fix ONE machine changes `base_hash` → **every machine re-flags → full fleet rebuild**. The original
goal — *add/fix one machine without rebuilding the fleet* — is **not met** for the common case (a new machine brings
new rules → a shared-core edit → everyone re-flags). The 6-feature unbundle was the DISPLAY-panel axis; this refactor
is the MECHANIC axis, which is where the real isolation lives.

## 2. Target architecture: play-type (玩法) plugins
- A machine = an **aggregation of play-types**, **auto-detected from its rawdata**.
- Each play-type = a plugin owning THAT mechanic's analysis logic (its round-classification, win-attribution, etc.).
  Play-type plugins are **base-EXCLUDED** (same hash trick as today's feature plugins).
- Result (this is the goal, achieved):
  - New machine reusing existing play-types → base + their hashes unchanged → **0 fleet rebuild**.
  - New play-type → one new plugin (base-excluded) → only machines exhibiting it re-flag.
  - Fix a play-type → only machines that have it. Change a machine's payid config → only that machine.

## 3. Decomposition principle (decided; grounded in real rawdata)
- **Split by the RIGOROUS signals: SpinType + feature** (server-authoritative, structurally meaningful, portable).
  Verified examples: M14 = `{ST1_paid}` (single paid play-type); M275 = `{ST126_free, ST140_paid}` + features
  (collect/freespin/scatter-trigger/jackpot) = an aggregation of several play-types.
- **PayId is per-machine CONFIG, NOT a decomposition axis.** Verified: payids 1–7 appear on BOTH M14 and M275 but
  mean different things — same id is just a config slot. Each machine **owns its payid → semantic**; payid
  interpretation lives with the machine (data); a shared win-attribution engine reads per-machine payid config.
- **"Granularity" is not a knob** — split exactly where SpinType/feature distinguish behaviors; do NOT split where only
  payid differs (that is config, not a play-type). The next session must confirm "which rawdata signals are rigorous"
  by inspecting many machines' rawdata before fixing the split.

## 4. Locked requirements
- **Boundary**: universal math (RTP / volatility / hit-rate / report shell / sampling / chunk-envelope parse) stays in
  base; mechanic-specific analysis → play-type plugins; payid semantics → per-machine data.
- **Detection = FULLY AUTOMATIC** from rawdata (SpinType + feature). **No human-confirmed manifest.** The current 420
  `machine_manifests/*.json` + the 9 feature plugins are **DISCARDED** (greenfield). If detection is wrong, a human
  RAISES it → the fix is to the **detection LOGIC** (a base/plugin change that correctly re-flags only affected
  machines), NOT a per-machine confirm file.
- **Isolation precision = HASH-LEVEL** (a play-type edit re-flags every machine that has that play-type, even if that
  machine's output didn't change — accepted over-invalidation). Output-level isolation is a LATER optimization.
- **Version model**: `effective(machine,mode) = base ⊕ {hashes of its auto-detected play-type plugins} ⊕
  per-machine-payid-config-hash ⊕ mode`.
- **Output byte-identical** to the current report is the **correctness gate** (validate the new clean impl against
  current output) — NOT a reason to keep old code.
- **Greenfield**: clean architecture is the priority. Discard old plugins/manifests; re-sample/re-analyze is cheap; do
  NOT make the architecture dirty for backward-compat (`不要把代码架构弄脏`).

## 5. Process direction (how the next session runs)
- **DIRECTION-only handoff** (user 2026-05-30): do NOT start from a generated task brief; the next session must verify
  multiple machines' rawdata itself to induce + validate the play-type taxonomy.
- **ITERATIVE, not big-bang**: pick **~10 representative machines** first (span the play-type variety — e.g. a simple
  single-paid machine, a free-spin/collect machine, a jackpot machine, a wild-nudge machine, a map-collection machine,
  a settlement-selector machine…). Design + build the architecture to **fully support those 10**. THEN onboard every
  remaining existing machine the **same way a brand-new machine is added** (compose existing play-types; add a new
  play-type plugin only when a genuinely-new mechanic appears). Do NOT analyze/support all 420 at once.
- **Must run the arch-* design round first** (touches base + cross-cutting). First concrete step = the rawdata-driven
  **play-type induction** (arch-taxonomist), validated across the ~10 pilot machines, before any implementation.

## 6. Test strategy (decided)
- The analyzer tests tied to the OLD model — C-phase byte-identical tests, `test_2a..6_*`, feature-plugin tests,
  manifest/closure-pin tests, the drift-guard's plugin-set assumptions — become **OBSOLETE** under greenfield →
  **clean + rebuild fresh** for the play-type architecture (tests follow the new play-type plugins; one per plugin,
  byte-identical golden + inject-bug TDD). Do NOT carry the old feature-plugin tests forward.
- **Keep/adapt**: console/backend infra tests, sampling tests, and the honest-staleness model tests (the staleness/hash
  MODEL persists even as the plugin set changes — re-pin to the new base + play-type hashes).
- **Carry the discipline forward**: byte-identical validation against current output + inject-bug red→green per plugin.

## 7. Agent-team review (decided)
- **Design** = arch-* team (mapper / taxonomist / coupling-auditor → designer → critic / validator).
  **Build** = impl-* team (implementer / tester / verifier / critic / committer). Together these COVER
  design / dev / test / verify for this refactor. (NOT slot-* — that team designs individual machines, not the
  analyzer architecture.)
- **拉数据 / sampling**: a tool/CLI action (cached rawdata for the fleet mostly exists; `--from-cache` / the console
  sampling path). No dedicated agent needed. Rawdata **analysis/induction** = **arch-taxonomist** (its exact charter:
  classify/cluster a fleet of similar objects by structural similarity = the play-type induction) + **slot-analyst**
  for deep per-machine rawdata reads.
- **Team-management update**: elevate arch-taxonomist as the FOUNDATION of this refactor (it must validate the
  play-type split across the ~10 pilot machines' real rawdata before design proceeds). Otherwise the existing
  arch-*/impl-* process + the binding memory feedback files apply unchanged. **No new agent type required.**

## 8. Explicitly out of scope for the next session's first cut
- The remaining ~410 machines (onboard iteratively, as "new machines", after the 10-machine architecture lands).
- Output-level isolation (hash-level first).
- Preserving any of the current 9 feature plugins / 420 manifests (greenfield — discard).

## 9. Session refinements (2026-06-01, locked in conversation — applies on top of §1–8)
- **Plain-language sign-off gate (refines §5).** The FIRST deliverable is arch-taxonomist's rawdata-derived
  play-type taxonomy across the ~10 pilots, presented to the user as a **plain-language** proposal he can judge —
  each play-type described as a *mechanic in business terms* + which machines have it + the one rawdata signal that
  identifies it (e.g. "免费旋转+收集，出现在 M275…，识别信号 = ST=126 free + collect feature"). **No code, no manifest
  JSON, no rule dumps, no plugin/hash jargon.** User signs off ONCE (slot_designer Stage-3.5 Boundary-Contract style);
  THEN W2 design proceeds. The pipeline-map / coupling-audit are technical inputs for the designer + coordinator,
  NOT part of the user gate.
- **Old work = reference + double-check, NEVER authority (refines §3/§5/§6).** The 420 `machine_manifests/*.json`,
  the prior `session_artifacts/_arch/01..09` artifacts, and the existing per-machine analysis rules (round_win rules,
  BCMCycleAnchorRule, trigger anchors, M99/M112 dedupe, the M279/M274 fixes, etc.) are **reference material to
  cross-check against — do NOT assume any of them is 100% correct.** Re-derive from real rawdata; where the
  re-derivation disagrees with old work, FLAG the disagreement rather than silently inheriting it.
- **byte-identical is refactor-safety, NOT a correctness claim (refines §4).** Output-byte-identical proves the CARVE
  didn't change behavior; it does NOT prove the behavior was right. Where a play-type's *current* output is itself
  suspect — `_unattributed_*` / `_other` / fallback buckets (e.g. M274 mode-1's `_unattributed_st139` ate 4.87% RTP),
  NOT_FIXED dedupes, historically drift-prone attribution — re-validate against rawdata ground truth. A deliberate
  correctness fix that diverges from current output is **surfaced to the user as a flagged diff**, not forced into
  byte-identity. Do NOT let byte-identical launder a pre-existing bug.

## 10. Foundation signed off (2026-06-01, user approved in conversation — the boundary contract W2+ designs against)
- **Taxonomy APPROVED**: the 15 play-types in `02_taxonomy.md` Part B are the round-1 play-type set.
- **Pilots LOCKED at 12**: M14, M31, M43, M15, M99, M272, M275, M274, M279, M268, M120, M10 — these exercise all
  15 play-types. Round-1 architecture must FULLY support these 12; the remaining ~310 onboard later as "new machines".
- **SpinType = the PRIMARY partition dimension.** Do NOT reduce to paid/free — ST is the axis. `number → mechanic`
  is CONSISTENT (no collision in pilot evidence): a given ST number denotes one mechanic-role across the machines
  that emit it. The reverse is one-to-many (one mechanic uses different ST numbers across engine generations — e.g.
  freespin = 44/126/138/157); that is normal, NOT instability. Same number / same meaning / different per-machine
  config (WheelId, cycle length, paytable) is the IDEAL shareable case — config lives in the per-machine config layer.
- **ST collisions = FORK + onboarding ALERT, never a pre-census.** Where one ST carries two mechanics — intra-machine
  (M15 ST=1 = base spin + TopDollar trigger) or a future machine — the architecture FORKS that ST using the finer
  feature signal. At new-machine onboarding, an ST that does not map cleanly RAISES AN ALERT for human review; then
  decide case-by-case. No upfront fleet-wide collision scan.
- **Feature = SUBORDINATE to ST, two jobs:**
  - (A) **Portable signature / labeler + fork-er** — the generation-independent field/remark signature that
    auto-labels each ST into a play-type and forks an ambiguous ST. This is the **claim key** (a plugin claims its
    rounds by feature signature, NOT by hardcoded ST number — so a new generation using a different ST number is
    still recognized). Use a play-type's DISTINCTIVE field (DollarCount, CollectCount); NOT generic fields
    (ExtraRatio appears in multiple mechanics); remark-only signals (PT-15 wheel) are weaker/provisional.
  - (B) **Per-mechanic analysis payload** — the fields each play-type plugin measures within its claimed ST segment
    (CollectCount→cycle, ExtraRatio→multiplier, DollarCount→offer, LockReels→lock behavior). The current 9 display
    plugins are essentially job-B logic; they get absorbed into the play-type plugins.
- **One-line model**: ST = which rounds are mine (partition); feature = (A) how I portably recognize/fork them
  [claim key] + (B) what I measure about them [payload].
- **Plugin claim key = feature signature; ST = the resulting per-machine partition** (NOT ST-number-as-key).

## 11. AS-BUILT status (2026-06-02 — full state in `HANDOFF.md`, carve method in `CARVE_METHODOLOGY.md`)
Built + committed on branch `claude/playtype-rearch` (HEAD `8445312`): **A** framework · **B** parse-loop wiring
(flag `--use-play-type-plugins`, default OFF) · **C1** plumbing (per-ST ownership + 5 fixes) · **C2** BCMBasePlugin
· **C3** per-machine config layer · **PT-7 wild-nudge** (the first genuine carve).
- **Genuine carves: 1 (PT-7 wild-nudge, commit `8445312`)** — `is_wild_nudge_round` moved OUT of the
  `round_classification.py` closure into `play_types/wild_nudge.py`; editing it leaves base_hash unchanged
  (proven by `tests/backend/test_wild_nudge_carve.py`). This is the reference implementation.
- **⚠ C2's BCM "carve" is HOLLOW, not a milestone.** The cycle logic stayed in `round_classification.py` (a
  closure file); editing it still flips base_hash → zero isolation. It must be REDONE per `CARVE_METHODOLOGY.md`.
  The earlier "first real carve / MILESTONE / 1 of 15 carved" framing was an overclaim — corrected here.
- **Correctness is NOT all-clean:** 4 of 9 golden pilots carry a pre-existing layer-2 `_unattributed` fallback
  (M15/M268 large, M272/M279 small). Preserved byte-identically (not a regression); real attribution gaps,
  DEFERRED by user decision. The Phase-2 win-attribution carve closes them.
- **Corrections to the sections above:** §9's M274 4.87% example is ALREADY FIXED (not a pending bug; the §9
  *principle* — byte-identical ≠ correctness — stands and was just re-proven by C2's hollow carve). §6's "delete
  obsolete tests" → in practice RE-PIN base_hash-value tests with a documented reason. On a CLEAN tree the C-phase
  output + canonical-md5 tests are green (the "task #8 reds" were dirty-tree `configs/machines.json` drift).
- **THE acceptance gate (replaces "byte-identical alone"):** a carve is done iff editing the carved logic leaves
  base_hash unchanged AND editing a universal closure fn flips it, pinned by a permanent test. byte-identical
  alone is what let the hollow C2 pass. **Read `CARVE_METHODOLOGY.md`.**
- **Process learning:** background impl agents died silently TWICE — prefer FOREGROUND / check liveness early.
