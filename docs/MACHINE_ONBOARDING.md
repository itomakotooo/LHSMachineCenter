# Onboarding a New Machine — Analyzer Workflow

How to add analyzer support for a new slot machine, correctly. Written 2026-06-05
after the M15 / M90 investigation; the rules below are hard-won — violating any of
them produces a confident-but-wrong analysis.

> **STATUS — 2026-06-07 (post-rebuild).** The SpinType-native rebuild LANDED:
> `fresh_slotlab/analyzer/report_engine.py` replaced the deleted PIA; per-machine manifests
> at `configs/machine_manifests/<M>.json`; `machine_spec.derive_analyses` is wired into the
> report + versioning; feature plugins are AUTO-DISCOVERED (adding one no longer flips the
> fleet `base_hash`). Report generation + the step-5 value-agnostic gates WORK again, via
> `report_engine.generate_report_from_chunks(<M>, <mode>, chunk_dir=…)`, for REGISTERED
> machines (registered = a confirmed `configs/machine_manifests/<M>.json`); unregistered
> machines get a clean "not registered" (only M15 + M43 onboarded so far).
> - ⚠ **The per-ST EXTRACTION layer is still a shared monolith parser** (`core/parser.py`).
>   Metrics that need per-round ReMarks / sequence data (node lists, run-lengths,
>   predecessor-outcome) are `parser_blind` until that layer is carved into a per-ST
>   base-excluded library (DIRECTION.md §3 — framework work; see the M43 case study).
> - This doc is the live onboarding playbook: **record every reusable workflow / method /
>   trap here (and agent-actionable methods into `.claude/agents/onboard-*.md`) in real
>   time** — the goal is a self-sufficient onboarding team.

---

## The model (locked)

- The unit is the **SpinType** — a protocol event token: a reel spin, a player
  choice, a settlement, a state round. NOT "a spin".
- A machine = the set of SpinTypes it emits. A **玩法 / feature** = a group of
  related SpinTypes (e.g. TopDollar = ST1 trigger + ST14 choice + ST15 settle).
- **Never fabricate a layer the rawdata doesn't have. Never assume — derive from
  the machine's OWN data.**

---

## Cardinal rules (read these first)

1. **Analyze the new machine FRESH, zero presumption.** Do NOT diff it against a
   known machine (e.g. M15) to "find" its structure — that imports a model the data
   may not support, and you will pattern-match instead of observe. Derive the new
   machine's structure from its OWN rawdata first; compare to existing parsers ONLY
   after you have an independent conclusion.

2. **Analyze GAMEPLAY (structure / semantics), NOT numbers.** RTP, hit-rate, and
   distributions are analysis *output* — they have nothing to do with whether the
   framework can parse the machine. "Understand the gameplay" means: which
   SpinTypes, what each one DOES (its role), the event flow (state machine), and the
   economy semantics (which field is the real win vs a preview).

3. **rawdata is NECESSARY but NOT SUFFICIENT.** The testspin endpoint
   (`MultiRobotTestSpinVariant`) returns the spin-engine math, sampled STATELESS
   (`ResetPlayerStateAfterEachSpin=true`, IID w.r.t. wallet). It is STRUCTURALLY
   BLIND to:
   - cross-spin / progression / stateful mechanics (counters, loyalty, pity timers);
   - anything applied OUTSIDE the spin engine (promo / wallet / account services).
   Such mechanics can ONLY come from **user domain knowledge**. NEVER conclude
   "gameplay is complete" from rawdata alone. (See the M90 case study — its
   "10 triggers → gift one" mechanic is invisible to testspin at ANY length /
   reset mode / code version.)

4. **Same ST number ≠ same semantics.** ST=14 on machine A is not necessarily ST=14
   on machine B. Reuse a validated ST parser ONLY when the **field signature**
   matches; flag a new/divergent shape for confirmation. Never reuse by bare number.
   Distinguish **core fields** (present ~100% on both → define the ST shape, drive
   reuse) from **optional feature fields** (variable presence → feature signals, not
   shape; e.g. `GameplayTriggerType` was a red herring).

5. **Value-agnostic invariants are the gate.** "Parsing logic correct" ≠ "RTP equals
   some reference value." An optimized variant with a different RTP is correct, not a
   regression. The gate is internal consistency, value-independent:
   `sum(payid.rtp_pp) == summary.rtp`, `our_rtp == server_rtp`, fallback bucket <
   threshold, no double-count (preview fields → 0, settlement is the only real win).

---

## The workflow (per machine)

0. **Use cached rawdata** (`rawdata/<M>/mode_<n>/chunk_*.json`). Re-sample only with user OK.
   - **PROVENANCE FIRST — is the cache REAL or VIRTUAL? (M43 lesson, do this before anything.)**
     The deleted virtual framework's chunk emitter wrote `_cache_version: 2` (+ `_dev_sample:
     true`); the real console sampler writes `_cache_version: 3` and CANNOT be faked (v3
     requires the real payload hash the decoupled virtual emitter couldn't compute). So
     **v3 = real; v2 = virtual → must be deleted before analysis** (a per-machine,
     user-approved delete — not auto). Scan EVERY mode (a whole mode can be 100% virtual).
     Analyzing virtual chunks = validating the parser against fabricated event structures.
     *Why this beats worrying about config drift:* you are writing a **value-agnostic parser** —
     the config VALUES don't matter; what matters is that the event STRUCTURES are the real
     machine's.
   - **Cache staleness** (secondary): chunk `_config_md5`/`_code_md5` vs `machines.json`.
     A `code_md5` drift does NOT threaten the parser (value-agnostic) — it only means the
     reported NUMBERS may reflect older logic. Note it; it is not a blocker.

1. **Extract the ST inventory** from real data:
   `python -m fresh_slotlab.analyzer.st_inventory <M> <mode>` →
   `{spin_types: {st: {count, field_presence}}}`.

2. **Understand each ST from its OWN raw fields** (zero presumption). Dump raw
   records AND the SpinType *sequence* (the state machine) per robot. Derive each
   ST's role from its fields + position — e.g. reel fields (`StopSymbolsByCol`,
   `PayoutByPayline`) = a spin; offer fields (`OfferValue`, `ChosenDollar`) = a
   choice; a bare `WinAmount` = a settlement. Do NOT label it from a template.

3. **Derive the gameplay structure**: the event flow (X → Y → Z), the trigger signal
   (a payout id + `ReMarks`, etc.), and the **economy** — which field is the real
   win, which are previews (must be counted 0 or RTP double-counts), what settles.
   Prove the economy from THIS machine's data (e.g. session ST15 ≠ Σ ST14 ⇒ ST14 is
   a preview).

4. **THEN compare to existing parsers.** For each ST, does its field signature match
   a validated ST (an existing parser / feature)? Match → candidate for reuse.
   New / divergent → flag for confirmation. **Read the actual parser code**
   (segmentation, settled-offer rule in `core/parser.py`; the feature in
   `features/*`) and verify it genuinely ASSEMBLES this machine — do not assume from
   the docstring.

5. **Run value-agnostic invariants** on this machine (rule 5). They prove the global
   numeric parsing is logically correct regardless of the RTP value. (⚠ currently
   PAUSED — these gates run against a generated report and report generation is offline
   pending the new engine; see STATUS at the top. Resume this step with the new engine.)

6. **DOMAIN CHECK — mandatory (the M90 lesson).** Ask the user: *does this machine
   have any mechanic that random testspin can't show* — a progression/loyalty
   counter, a gift/promo, a wallet feature, anything stateful or applied outside the
   spin engine? If yes: it is NOT in the rawdata; record it from the user, and if it
   affects RTP, flag the data-derived RTP as INCOMPLETE.

7. **Directed test — only if needed.** If a mechanic's precondition is rare but
   *in-engine*, force it (diagnostic-reel pattern: push one variable to an extreme so
   the condition fires; deploy → sample → compare). If the mechanic is *outside* the
   spin engine, no test captures it — it stays domain-declared.

8. **Confirm + record.** When the 5 gates pass, write the machine's SpinType-native
   manifest (`spin_types{role, play}` + derived analyses + `validation: confirmed` +
   any domain-declared invisible mechanics) and its per-machine digest regression
   baseline. (The SpinType-native manifest SCHEMA is now LOCKED —
   `fresh_slotlab/analyzer/machine_spec.py` + the `configs/machine_manifests/M15.json`
   reference; `machine_spec.derive_analyses()` derives the analysis set from `spin_types`.
   The per-machine DIGEST harness and wiring the schema into the live engine are pending
   the orchestrator rebuild. Until then: steps 0–4 / 6–7 + the authored manifest are the
   substance; the numeric gates (step 5) resume with the new engine.)

---

## The 5-gate confirmation (what makes a machine "confirmed")

1. ST inventory extracted from real rawdata.
2. Each ST's role determined from its real FIELDS (not guessed).
3. Economy / RTP invariants hold (previews → 0, settlement is the real win,
   `sum == summary`, no orphan / no double-count).
4. Behavioral stats reproduce (independently re-derived).
5. **User domain sign-off** — including declaration of any rawdata-invisible
   mechanics.

Until all 5 pass, the machine is `auto` (data-derived, possibly incomplete), NOT
`confirmed`. A same-archetype match to a confirmed machine is NOT enough on its own —
gate 5 still applies (M90 looks identical to M15 in data but isn't).

---

## Case studies (real traps)

- **M15 (TopDollar) — confirmed.** Trigger = ST1 with payout `666` + `ReMarks="Trigger"`
  (pays 0 credits, opens the mini-game). Then 1–4 sequential offers (ST14:
  `OfferValue` = Σ `ChosenDollar` denominations; `WinCredits` = a per-offer PREVIEW).
  ST15 `WinAmount` settles the LAST offer (the only real win). ST14 `WinCredits` must
  be counted 0 (else RTP double-counts). All 5 gates passed.

- **M90 ("M15 optimized") — the cautionary tale.** In testspin it looks IDENTICAL to
  M15: same STs, the M15 parser assembles it, every ST15 → ST1, mini-games == paid
  triggers. A rawdata-only pass would conclude "M90 = M15, done" — **and be wrong.**
  M90 has a real "trigger the mini-game 10 times → gift one" mechanic that is
  **completely absent from testspin output**, verified across the stale cache AND a
  fresh `reset_each_spin=False` sample on current code. The gift is applied outside
  the spin engine → invisible to ALL testspin sampling, at any length / reset / code.
  Only the user's domain knowledge surfaced it. This is exactly why Rule 3 + Step 6
  exist.

- **M43 (Bar/Seven/Wild + WinRespin + WinMiniGame) — onboarded; multiple reusable traps.**
  3 STs: **st1** Normal (paid reel spin → strict-reuse the per-ST plugins, no new code);
  **st50** WinRespin (FREE `cost=0` reel spin on a premium **skin-6** reel → a NEW `respin`
  role + new respin-mechanic analysis); **st51** WinMiniGame (settlement, NO payid,
  `ReMarks="MiniGame[101-110]"` → NEW; its win attributed via a **config-only**
  `SynthesizePayIdRule` so `sum(payid)==summary` holds and `_unattributed_st51`→0). Lessons:
  - **Provenance: the cache was contaminated with VIRTUAL chunks** (one `_cache_version:2`
    chunk per mode; mode_2/5 were 100% virtual). Caught ONLY by the v2/v3 check (step 0).
    Deleted; the model was unchanged on the clean real chunks — but you can NEVER assume a
    virtual chunk is representative; exclude on principle.
  - **Naming from rawdata, not invented:** the new role for st50 = `respin` (from
    `ReMarks="ReSpin"` / feature `WinRespin`). The team resolves naming/attribution/metric
    selection INTERNALLY — do NOT ask the user (that signals a process gap).
  - **`rtp_integrity.paid_st`:** st50/st51 carry `BetAmount` at `cost=0`, so a global-bet RTP
    denominator inflates; set `paid_st:[1]` (only truly-paid STs) for the correct paid-round RTP.
  - **The server `analysisResult` (`TotalWin`/`FeatureWin`/`SummaryWin`) IS the machine's own
    multiplier×feature taxonomy** — the centerpiece for the multiplier distribution; prefer it
    over hand-rolled bands. (`analysisResult` is a JSON string; each view is a nested JSON
    string — `json.loads` twice. It was missed on the first pass; opening it is mandatory.)
  - **All modes share STRUCTURE, only config VALUES differ** (user-confirmed) → onboarding ONE
    real mode confirms the parsing for all modes (the parser is value-agnostic); the manifest
    lists all `modes` but `confirmed_against` the one with real data.
  - **PARSER-BLIND → the per-ST extraction layer (the structural finding).** Some
    felt-experience metrics (minigame node-count×mult, node-code ladder, surprise-on-loss
    rate, respin burst-length) need PER-ROUND data (ReMarks node-lists, run-lengths,
    predecessor-outcome) that the SHARED monolith parser does NOT accumulate. The implementer
    correctly flagged these `parser_blind` and **did NOT fabricate them**. Fix (decided): make
    the per-ST EXTRACTION a base-excluded per-ST library — mirror the analysis-plugin layer
    (registry + auto-discover) — so adding an ST's extraction re-flags only that ST's machines,
    not the fleet (DIRECTION.md §3). Until that framework layer lands, such metrics are
    DEFERRED (flag, never fake).

---

## Tools & paths

- **ST extractor**: `fresh_slotlab/analyzer/st_inventory.py` (reuses `parse_rounds`;
  not in the report closure, so it does not flip `base_hash`).
- **Manifest schema + analysis derivation**: `fresh_slotlab/analyzer/machine_spec.py` —
  the LOCKED SpinType-native manifest loader/validator, `derive_analyses()` (analysis set
  derived from `spin_types`), the validation state (`auto`|`confirmed`), and the
  `out_of_engine_mechanics` slot (the M90 case). Reference instance:
  `configs/machine_manifests/M15.json`.
- **Chunk structure**: file = metadata + `response` (list of robots);
  `parse_rounds(robot)` → ordered rounds, each a dict with `SpinType` + fields.
- **Existing per-ST features**: `fresh_slotlab/analyzer/features/*`
  (e.g. `topdollar_choice` = the ST=14 choice; `spin_type_outcomes`,
  `spin_type_rtp_buckets`, `payouts_by_spin_type` = per-ST; others are cross-cutting).
- **Invariant gate**: `fresh_slotlab/analyzer/rtp_integrity.py` logic +
  `tests/backend/test_rtp_integrity_gate.py` (the value-agnostic correctness net). ⚠ it
  scores a generated `player_impact_summary.json` — report generation is currently offline
  pending the new engine (see STATUS), so this gate is not runnable end-to-end yet.
- **Sampler**: `fresh_slotlab/batch_dev_sampler.py` + `make_payload`
  (`analyzer/core/base_pipeline.py`). Endpoint = `base_pipeline.ENDPOINT_URL`
  (default `http://192.168.10.21:15060/MachineTest/MultiRobotTestSpinVariant`, the
  internal dev server). `reset_each_spin` toggles `ResetPlayerStateAfterEachSpin`
  (True = stateless IID for clean RTP; False = continuous session — but **neither
  captures out-of-engine mechanics**).
- **Per-machine manifests**: NEW SpinType-native schema → `configs/machine_manifests/<M>.json`
  (M15 is the first; load via `machine_spec.load_manifest`). LEGACY flat manifests still
  live at `slot_designer/configs/machine_manifests/<M>.json` and are read by `versioning.py`
  for the per-machine `effective_version`; converting + relocating them to the new schema
  is pending (the `player_impact_analyzer.py` that also read them is deleted).
- **Note**: `configs/machines.json` (the roster + per-machine config/code md5s) is a
  DOWNLOADED upstream cache (gitignored) — refreshed via the console's MapMachineOrder /
  refresh-md5 path, not hand-edited.
- **Direction / state**: `session_artifacts/_arch_playtype/` (DIRECTION, HANDOFF,
  02_traces = M15 ground truth, CARVE_METHODOLOGY).
