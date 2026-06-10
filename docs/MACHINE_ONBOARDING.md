# Onboarding a New Machine — Analyzer Workflow

How to add analyzer support for a new slot machine, correctly, and at a cadence that
scales to a whole fleet. Written 2026-06-05 after the M15 / M90 investigation; distilled
2026-06-10 from the two machines now fully onboarded (M15 TopDollar, M43 ReSpin). The
rules below are hard-won — violating any of them produces a confident-but-wrong analysis.

> **STATUS — 2026-06-10.** The SpinType-native engine is LIVE and report generation WORKS.
> - Per-machine manifests at `configs/machine_manifests/<M>.json`; `machine_spec.derive_analyses`
>   is wired into report + versioning; feature plugins are AUTO-DISCOVERED (adding one does NOT
>   flip the fleet `base_hash`).
> - `report_engine.generate_report_from_chunks(<M>, <mode>, chunk_dir=…)` produces a full report
>   for any REGISTERED machine (registered = a `configs/machine_manifests/<M>.json` exists);
>   unregistered machines get a clean 422 "not registered".
> - The value-agnostic acceptance gates (`rtp_integrity_check`) RUN against the generated summary.
> - **Onboarded: M15** (confirmed) **+ M43** (confirmed; modes 1 & 7 generate clean reports).
> - ⚠ **The per-ST EXTRACTION layer is still a shared monolith parser** (`core/parser.py`).
>   Metrics that need per-round ReMarks / sequence data (node lists, run-lengths,
>   predecessor-outcome) are `parser_blind` until that layer is carved into a per-ST
>   base-excluded library (DIRECTION.md §3 — framework-team work; see the M43 case study).
> - This doc is the live onboarding playbook: **record every reusable workflow / method /
>   trap here (and agent-actionable methods into `.claude/agents/onboard-*.md`) in real
>   time** — the goal is a self-sufficient onboarding team that can run in batch.

---

## What onboarding PRODUCES — read this first

Onboarding does **NOT** produce a report. It produces the **parsing structure**: the
machine-specific content that, given rawdata, *can generate* a report. The report is an
on-demand **output**; the deliverable is the report-generating **capability**.

> "Done" = the parsing structure is correct and general — **proven** by: a report generates
> and passes the value-agnostic gates. The report is the acceptance test, not the product.

Why this framing matters for **batch**: onboarding N machines lands **N parsing structures**,
not N reports. Reports are regenerated on demand per `(machine, mode, md5)` from the structure
+ cached rawdata (the console's "⟳ 生成 Report" path). A machine is onboarded the moment its
structure exists and passes its gates — independent of whether any report has been rendered yet.

### The 4 deliverable artifacts (all base-excluded — onboarding never flips `base_hash`)

| # | Artifact | Path | What it carries |
|---|----------|------|-----------------|
| 1 | **Manifest** (declarative core) | `configs/machine_manifests/<M>.json` | per-ST `{role, play, economy, signature}` + `trigger` + `rtp_integrity` + `out_of_engine_mechanics` + `validation` |
| 2 | **Plugins** (new mechanics only) | `fresh_slotlab/analyzer/features/<mechanic>.py` | NEW `AnalyzerFeature` plugins, auto-discovered; STRICT-REUSE existing ones, never fork |
| 3 | **Wiring** (role/play → analysis) | `fresh_slotlab/analyzer/machine_spec.py` | `ROLE_ANALYSES`, `PLAY_ANALYSES`, `KNOWN_ROLES` extension — how a manifest's roles/plays pull in the right analyses |
| 4 | **Attribution rule** (only if needed) | `configs/machine_round_win_rules.json` | payid synthesis for a settlement ST with no natural payid, so `sum(payid)==summary` and the fallback bucket stays 0 |

None of these is a `_CLOSURE_FILES` member. That is the **isolation invariant**: a new machine
re-flags only ITS OWN `effective_version`, never the fleet `base_hash`. If onboarding ever needs
a closure change, STOP — that is framework-team work (it re-flags every machine).

---

## The model (locked)

- The unit is the **SpinType** — a protocol event token: a reel spin, a player choice, a
  settlement, a state round. NOT "a spin". A `win=0` ST (a choice / a state) still carries
  behavioral value.
- A machine = the set of SpinTypes it emits. A **玩法 / feature** = a group of related
  SpinTypes (M15 TopDollar = ST1 trigger + ST14 choice + ST15 settle; M43 = ST1 + ST50 respin
  + ST51 minigame). There is **no play-type layer** — do not fabricate one.
- Each ST has a **role** (its structural kind) and a **play** (its rawdata feature name).
- **Never fabricate a layer the rawdata doesn't have. Never assume — derive from the
  machine's OWN data.**

---

## Cardinal rules (read these first)

1. **Analyze the new machine FRESH, zero presumption.** Do NOT diff it against a known
   machine (e.g. M15) to "find" its structure — that imports a model the data may not
   support, and you pattern-match instead of observe. Derive the new machine's structure from
   its OWN rawdata first; compare to existing parsers ONLY after you have an independent
   conclusion.

2. **Analyze GAMEPLAY (structure / semantics), NOT numbers.** RTP, hit-rate, and distributions
   are analysis *output* — they have nothing to do with whether the framework can parse the
   machine. "Understand the gameplay" means: which SpinTypes, what each one DOES (its role),
   the event flow (state machine), and the economy (which field is the real win vs a preview).

3. **rawdata is NECESSARY but NOT SUFFICIENT.** The testspin endpoint
   (`MultiRobotTestSpinVariant`) returns the spin-engine math, sampled STATELESS
   (`ResetPlayerStateAfterEachSpin=true`, IID w.r.t. wallet). It is STRUCTURALLY BLIND to
   cross-spin / progression / stateful mechanics (counters, loyalty, pity timers) and anything
   applied OUTSIDE the spin engine (promo / wallet / account). Such mechanics can ONLY come
   from **user domain knowledge**. NEVER conclude "gameplay is complete" from rawdata alone
   (the M90 case: "10 triggers → gift one" is invisible to testspin at ANY length / reset /
   code version).

4. **Same ST number ≠ same semantics.** ST=14 on machine A is not ST=14 on machine B. Reuse a
   validated ST parser ONLY when the **field signature** matches; flag a new/divergent shape.
   Never reuse by bare number. Distinguish **core fields** (present ~100% on both → define the
   ST shape, drive reuse) from **optional feature fields** (variable presence → feature signals,
   not shape; `GameplayTriggerType` was a red herring).

5. **Value-agnostic invariants are the gate.** "Parsing logic correct" ≠ "RTP equals a
   reference value." An optimized variant with a different RTP is correct, not a regression
   (M43 mode 1 = 93.15%, mode 7 = 78.48% — both correct, different skins). The gate is internal
   consistency, value-independent: `sum(payid.rtp_pp) == summary.rtp`, `our_rtp == server_rtp`,
   fallback bucket < threshold, no double-count (previews → 0, settlement is the only real win).

---

## The per-SpinType decision framework

For EACH SpinType, the onboarding team resolves four questions — all from the data, none from
the user (naming / attribution / metric choice are internal; see the escalation boundary):

1. **ROLE?** — its structural kind, derived from its OWN fields, not a template.
   `paid_spin` (reel fields `StopSymbolsByCol`/`PayoutByPayline` + `cost>0`) · `player_choice`
   (offer fields `OfferValue`/`ChosenDollar`) · `settlement` (a bare `WinAmount`/`WinCredits`
   that settles a feature) · `state` (an empty/marker round) · `respin` (a FREE `cost=0` reel
   spin extending a paid spin — M43 ST50). If a ST's kind needs a role not in `KNOWN_ROLES`,
   **derive the token from the rawdata feature name and extend `KNOWN_ROLES` yourself**
   (`machine_spec.py` is base-excluded — no fleet flip). Never ask the user "what word".

2. **PLAY?** — the exact rawdata feature name (`Normal` / `TopDollar` / `WinRespin` /
   `WinMiniGame`), case-sensitive (it is the literal `FeatureWin` key from `analysisResult`).

3. **REUSE or NEW?** — does the ST's field signature match an existing validated ST/plugin?
   Match → **STRICT-REUSE** (verbatim, never modify/fork). No match → a genuinely **NEW**
   event → a new plugin (allowed; not a fork). Signature matches but the existing plugin does
   NOT actually assemble this machine → **ABORT + escalate** (the shared parser is inadequate;
   fixing it is framework-team work that re-flags all its machines).

4. **ATTRIBUTION dimension?** — how the ST's win attributes so `sum(payid)==summary` and the
   fallback bucket is 0. A settlement ST with a natural payid → reuse it. A settlement ST with
   NO payid (M43 ST51) → a config-only `SynthesizePayIdRule` that mints a stable pid
   (`st51`) — a rule in `machine_round_win_rules.json`, NOT a closure change.

### ROLE vs PLAY — which hook to attach an analysis to (the M43 lesson)

A machine's analysis set is `derive_analyses(manifest)` =
`CROSS_CUTTING` + `PER_SPINTYPE` + `ROLE_ANALYSES[role]` (per role present) +
`PLAY_ANALYSES[play]` (per play present). When you add a mechanic analysis, choose the hook:

- **Attach by ROLE** (`ROLE_ANALYSES`) when the analysis applies to ANY ST of that role,
  generically. E.g. `player_choice → topdollar_choice`, `respin → respin_dynamics`.
- **Attach by PLAY** (`PLAY_ANALYSES`) when the analysis is specific to ONE feature whose ROLE
  is SHARED with an unrelated feature on another machine. **M43's minigame settles via the
  `settlement` role — the SAME role M15's TopDollar settlement uses.** Attaching
  `minigame_dynamics` by role would wrongly fire it on M15. Keying on play `"WinMiniGame"`
  scopes it to the minigame feature only. (The regression test `test_m15_has_no_minigame_dynamics`
  locks this — see the tester.)

Rule of thumb: **role = generic structural kind; play = a specific named feature.** If two
machines share a role but the analysis is meaningful for only one of them, key by play.

---

## The workflow (per machine) = the 5 onboarding waves

Run as the agent team (below) or by hand; the substance is identical. Each wave consumes the
prior wave's artifact and is GATED before the next starts.

**W1 — Understand (ground truth).** Use cached rawdata only (`rawdata/<M>/mode_<n>/chunk_*.json`).
- **PROVENANCE FIRST (M43):** is the cache REAL or VIRTUAL? The deleted virtual framework wrote
  `_cache_version: 2` (+ `_dev_sample: true`); the real console sampler writes `_cache_version: 3`
  (cannot be faked — v3 requires the real payload hash). **v3 = real; v2 = virtual → delete
  before analysis** (per-machine, user-approved). Scan EVERY mode (a whole mode can be 100%
  virtual — M43 mode_2/5 were). Analyzing virtual chunks validates the parser against fabricated
  structures. *(Config/`code_md5` drift is secondary — it only affects reported NUMBERS, never
  parse correctness; a value-agnostic parser does not care about config VALUES. Note it; not a
  blocker. M43's data carried `code_md5` 6e02924b vs registry 473d1f54 → it shows in the console's
  "历史" rawdata cell and regenerates from there.)*
- Extract the ST inventory: `extract_st_inventory(<M>, <mode>)` (in `analyzer/st_inventory.py`;
  not in the closure) → `{spin_types: {st: {count, field_presence}}}`.
- Understand each ST from its OWN fields + the SpinType *sequence* (the state machine per robot).
- **Open the server `analysisResult`** (`TotalWin`/`FeatureWin`/`SummaryWin`) — it IS the
  machine's own multiplier × feature taxonomy, the centerpiece of the multiplier distribution.
  It is a JSON string whose views are themselves JSON strings → `json.loads` twice. Missing it
  was a real M43 first-pass error.
- Derive the economy: which field is the real win, which are previews (must count 0 or RTP
  double-counts), what settles. Prove it from THIS machine's data.
- Surface EVERY in-ST cross-dimension the data supports (symbol×mult, node×mult, context×outcome).
- Report what is testspin-blind (state / out-of-engine) — never paper over a gap.

**W2 — Reuse gate.** Per ST, decide STRICT-REUSE / NEW / ABORT by FIELD SIGNATURE, audited in
3 layers — ALL required: (a) signature match to a validated ST; (b) READ the candidate plugin
code (does it genuinely assemble this machine — not by name/docstring); (c) RUN it on this
machine's real chunks and inspect the SEMANTIC output (payids/economy actually correct).
"Emits rows" / "exit 0" ≠ pass (the trap: onboarding twice claimed "reused" for a mechanic the
generic plugin never implemented). Same ST → reuse verbatim, never modify/fork. Inadequate
shared parser → ABORT + escalate, never patch.

**W3 — Quant design.** Design each ST's player-experience metrics that EMERGE from the real
distributions (never structural guessing): multipliers, hit-rates, probabilities, shares,
in-ST cross-dimensions — **money-agnostic** (never a coin total). Prefer the machine's own
`SummaryWin` taxonomy over hand-rolled bands. Decide each ST's attribution dimension. Decide
each analysis's ROLE-vs-PLAY hook (above). Propose the manifest (`spin_types{role, play,
economy, signature}` + trigger + `rtp_integrity` + `validation:auto`). Naming, attribution, and
metric selection are resolved INTERNALLY from the rules — never a user question.

**W4 — Implement + Test (parallel).**
- *Implement:* write the manifest, write NEW plugins (`features/*.py`, mirror a sibling — read
  one first), wire `machine_spec.derive_analyses` (role/play), add any attribution rule. Touch
  ONLY the 4 artifacts. **Compute `base_hash` before AND after — it MUST be unchanged.** If it
  flipped you touched the closure → revert + escalate.
- *Test:* value-agnostic regression (structure/flags/invariants only — NEVER pin an RTP value
  or range) + **inject-bug → red → revert → green** for every safety claim. Regenerate the REAL
  report via `report_engine` and assert the REAL summary (integrity passed, `_unattributed_*`
  share == 0, the new ST's output present, the frontend contract keys present). Include the
  cross-machine non-leak tests (e.g. `test_m15_has_no_minigame_dynamics`).

**W5 — Break (adversarial).** Attack the manifest + plugins on the HARDEST real sessions (rare
high-mult, surprise/rescue, multi-trigger, longest chains). Independently recompute the headline
distributions from raw rounds and confirm the report's numbers MATCH and capture the claimed
experience. Re-run the value-agnostic gates. Confirm every REUSE ST was genuinely assembled and
NOT secretly modified/forked (`base_hash` unchanged; shared files untouched in the diff). Output
a BREAKING counterexample (machine + trace) OR the per-case held-traces.

**Coordinator (main session), between/after waves.** Run the objective gates (don't rubber-stamp);
do the **mandatory DOMAIN CHECK** with the user (the M90 lesson — any mechanic testspin can't
show?); get user sign-off on the parsing structure; commit (surgically, 4-section message);
upgrade `validation.status` → `confirmed` on sign-off.

---

## The objective acceptance gates (what makes the STRUCTURE correct)

A machine's structure is correct when ALL hold (value-independent — these never pin a number):

1. **Provenance clean** — analysis ran on real (`_cache_version:3`) chunks only; virtual excluded.
2. **ST roles from real fields** — every ST's role/play justified by its signature, not guessed.
3. **`base_hash` unchanged** — the 4 artifacts are all base-excluded; onboarding did not touch
   the closure.
4. **`rtp_integrity_check.passed == True`** — L1 `sum(payid) == our_total`; L2 NO `_unattributed_*`
   fallback bucket (share == 0); L3 anchors present; `our == server` when the server aggregate is
   present.
5. **Report generates** — `report_engine.generate_report_from_chunks` returns a full summary with
   the frontend-contract keys + every declared ST's output present.
6. **No double-count** — preview fields → 0; the settlement is the only real win.
7. **User domain sign-off** — including declaration of any rawdata-invisible (out-of-engine)
   mechanic. Until this, `validation.status` stays `auto` (data-derived, possibly incomplete),
   NOT `confirmed`. A same-archetype match to a confirmed machine is NOT enough — gate 7 still
   applies (M90 looks identical to M15 in data but isn't).

---

## Agent team — usage methodology

A dedicated 6-agent team (distinct from the arch-* / impl-* framework-dev teams — those develop
the framework; this team ONBOARDS onto the frozen one). Definitions in `.claude/agents/onboard-*.md`;
artifacts under `session_artifacts/_onboard/<M>/`.

| Wave | Agent | Consumes | Produces | Gate before next |
|------|-------|----------|----------|------------------|
| W1 | `onboard-understander` | cached rawdata | `01_understanding.md` | provenance clean; every ST + field + analysisResult + cross-dims enumerated |
| W2 | `onboard-reuse-adjudicator` | `01` | `02_reuse.md` | per-ST REUSE/NEW/ABORT with 3-layer proof; **any ABORT halts onboarding** |
| W3 | `onboard-quant-designer` | `01` + `02` | `03_design.md` | metrics data-grounded + money-agnostic; manifest proposed; attribution + role/play resolved |
| W4 | `onboard-implementer` | `03` + `02` | the 4 artifacts (uncommitted) | `base_hash` unchanged; report_engine smoke produces a summary |
| W4 | `onboard-tester` | implemented machine | tests + results | inject-bug→red→revert→green; REAL report asserted; non-leak tests |
| W5 | `onboard-breaker` | everything | `05_breaker.md` | hardest-session metric-vs-raw match; gates hold; reuse integrity held — or a counterexample |

**Driving the team (coordinator):**
- Spawn waves **sequentially** (each consumes the prior artifact); W4 implementer + tester can
  overlap. Read each wave's artifact and GATE before spawning the next — do not chain blindly.
- **A W2 ABORT or W5 counterexample STOPS the line.** ABORT = a shared-parser problem (framework
  team); a counterexample = the structure is wrong (back to W3/W4).
- **The escalation boundary is strict.** Naming, attribution mechanism, and metric selection are
  the team's to resolve from the rules — NEVER surfaced to the user. Escalate to the coordinator
  ONLY for (a) a genuine domain fact rawdata cannot answer (out-of-engine mechanic — the M90
  check) or (b) a re-sample need (requires user OK). If an agent asks the user a naming/attribution/
  metric question, the process is broken.
- **The coordinator owns** the objective gates, the user domain check + sign-off, and the commit.
  The user is given the hard real-data cases (with traces), not abstract summaries; the user does
  NOT review docs/briefs/specs (those are internal).
- **Never trust GREEN / exit-code** at any wave — verify the SEMANTIC, user-visible output.

---

## Batch automation foundation

The structure above is built to scale to many machines at once. What makes batch possible:

- **Per-machine isolation = parallelizable.** Each machine's 4 artifacts are machine-scoped and
  base-excluded; landing machine B never re-flags machine A. N machines can run the W1→W5 pipeline
  concurrently.
- **The one shared coordination point is the REUSE REGISTRY** — the set of existing validated
  STs/plugins that W2 checks against, and which GROWS as machines confirm. Two machines that need
  the SAME genuinely-new plugin is the only real conflict; the coordinator de-dups (one plugin,
  both strict-reuse it). Truly-new machine-specific plugins never conflict; reuse is read-only.
- **The objective gates ARE the batch QC.** Each machine self-certifies via gates 1–6 (value-
  agnostic, automatable). A machine that fails its gates is flagged and set aside — it does NOT
  block the others. Only gate 7 (user domain sign-off) is human-in-the-loop, and it batches: the
  coordinator collects all machines' domain questions and asks the user once.
- **ABORT is the back-pressure signal.** A shared-parser ABORT pauses only the machines that need
  that ST; it routes to the framework team (a closure fix re-flags that ST's machines), while
  unrelated machines proceed.
- **A fan-out driver** (future) runs W1→W5 per machine as parallel pipelines, collects the
  per-machine gate verdicts + the batched domain questions, and presents the coordinator a
  pass/abort/needs-domain table. The methodology here is the contract that driver automates; the
  per-machine artifacts + gates are its inputs and outputs.

What is NOT yet automated (the honest boundary): the fan-out driver itself, and the per-ST
EXTRACTION carve (parser-blind metrics stay deferred until that framework layer lands). Onboarding
today is per-machine team runs coordinated by the main session; this doc is the foundation that a
driver will encode.

---

## Case studies (real traps)

- **M15 (TopDollar) — confirmed.** Trigger = ST1 with payout `666` + `ReMarks="Trigger"` (pays 0
  credits, opens the mini-game). Then 1–4 sequential offers (ST14: `OfferValue` = Σ `ChosenDollar`;
  `WinCredits` = a per-offer PREVIEW). ST15 `WinAmount` settles the LAST offer (the only real win).
  ST14 `WinCredits` must count 0 (else RTP double-counts). All gates passed. Manifest:
  `configs/machine_manifests/M15.json`.

- **M90 ("M15 optimized") — the cautionary tale.** In testspin it looks IDENTICAL to M15: same
  STs, the M15 parser assembles it, every ST15 → ST1. A rawdata-only pass would conclude "M90 =
  M15, done" — **and be wrong.** M90 has a real "trigger the mini-game 10 times → gift one"
  mechanic **completely absent from testspin output**, verified across the stale cache AND a fresh
  `reset_each_spin=False` sample. The gift is applied outside the spin engine → invisible to ALL
  testspin sampling. Only user domain knowledge surfaced it. This is why Rule 3 + the domain check
  exist.

- **M43 (Bar/Seven/Wild + WinRespin + WinMiniGame) — confirmed.** 3 STs: **st1** Normal (paid reel
  spin → strict-reuse the per-ST plugins, no new code); **st50** WinRespin (FREE `cost=0` reel spin
  on a premium skin → NEW `respin` role + new `respin_dynamics`); **st51** WinMiniGame (settlement,
  NO payid, `ReMarks="MiniGame[101-110]"` → NEW `minigame_dynamics`; win attributed via a config-only
  `SynthesizePayIdRule` so `sum(payid)==summary` and `_unattributed_st51`→0). Reusable lessons:
  - **Provenance: the cache was contaminated with VIRTUAL chunks** (one `_cache_version:2` per mode;
    mode_2/5 were 100% virtual). Caught ONLY by the v2/v3 check. Deleted; the model was unchanged on
    the clean real chunks — but never assume a virtual chunk is representative.
  - **ROLE vs PLAY:** `minigame_dynamics` attaches by PLAY `"WinMiniGame"`, NOT by its `settlement`
    role — because M15's TopDollar also settles via `settlement`, and a role hook would cross-fire.
    Locked by `test_m15_has_no_minigame_dynamics`.
  - **`rtp_integrity.paid_st`:** st50/st51 carry `BetAmount` at `cost=0`, so a global-bet RTP
    denominator inflates; set `paid_st:[1]` (only truly-paid STs) for the correct paid-round RTP.
  - **The server `analysisResult` IS the machine's own multiplier × feature taxonomy** — the
    centerpiece for the multiplier distribution. `json.loads` twice. Opening it is mandatory.
  - **All modes share STRUCTURE, only config VALUES differ** → one manifest serves every mode.
    Validated end-to-end: mode 1 (680k spins, RTP 93.15%) AND mode 7 (80k, RTP 78.48%) both generate
    clean reports (integrity passed, no fallback) from the SAME manifest — different skins, both
    correct (value-agnostic).
  - **PARSER-BLIND → the per-ST extraction layer.** Some felt-experience metrics (minigame
    node-count×mult, node-code ladder, surprise-on-loss rate, respin burst-length) need PER-ROUND
    data the SHARED monolith parser does NOT accumulate. The implementer flagged these
    `parser_blind` and did NOT fabricate them. Fix (decided): make the per-ST EXTRACTION a
    base-excluded per-ST library (mirror the analysis-plugin layer) so adding an ST's extraction
    re-flags only that ST's machines (DIRECTION.md §3). Until that lands, such metrics are DEFERRED
    (flag, never fake).
  - **The report is not the deliverable.** M43 "still wrong" turned out to be a browser-cache trap
    (stale `index.html` → stale `app.js`), fixed with a `no-cache` header — the served structure
    was already correct. And the user regenerated from the "历史" rawdata cell (the `code_md5`-drift
    path), confirming the STRUCTURE, not a specific report, is what was delivered.

---

## Tools & paths

- **ST inventory:** `extract_st_inventory(<M>, <mode>, rawdata_root="rawdata")` in
  `fresh_slotlab/analyzer/st_inventory.py` (reuses `parse_rounds`; not in the closure → no
  `base_hash` flip). Returns per-ST `count` + `field_presence` (the signature driver).
- **Manifest schema + analysis derivation:** `fresh_slotlab/analyzer/machine_spec.py` — the LOCKED
  loader/validator, `KNOWN_ROLES`, `CROSS_CUTTING` / `PER_SPINTYPE` / `ROLE_ANALYSES` /
  `PLAY_ANALYSES`, and `derive_analyses()` (analysis set derived from `spin_types`). References:
  `configs/machine_manifests/M15.json` (player_choice/settlement) + `M43.json` (respin + play-keyed).
- **Report engine:** `report_engine.generate_report_from_chunks(<M>, <mode>, chunk_dir=…,
  output_dir=…, bet=…)` — the orchestrator; registered machines only. The console reaches it via
  `POST /api/rawdata/<M>/generate-report` (`{mode, config_md5?, code_md5?}` — pass the historical
  md5 to regenerate from a "历史" rawdata cell).
- **Attribution rules:** `configs/machine_round_win_rules.json` — `SynthesizePayIdRule` etc.
  (`spin_types`, `label_format`, `applies_to`). Config-only; never a closure change.
- **Invariant gate:** `rtp_integrity.py` scores the generated `player_impact_summary.json`
  (`rtp_integrity_check`); the tester asserts `passed==True` + fallback share 0.
- **Chunk structure:** file = metadata (`_cache_version`, `_config_md5`, `_code_md5`, `_dev_sample`,
  `_machine`, `_mode`) + `response` (list of robots); `parse_rounds(robot)` → ordered rounds, each
  a dict with `SpinType` + fields.
- **Existing per-ST features:** `fresh_slotlab/analyzer/features/*` — cross-cutting + per-ST
  (`spin_type_outcomes`, `spin_type_rtp_buckets`, `payouts_by_spin_type`, `reel_marginal_by_spin_type`),
  role-keyed (`topdollar_choice`, `respin_dynamics`), play-keyed (`minigame_dynamics`).
- **Sampler (re-sample only with user OK):** `fresh_slotlab/batch_dev_sampler.py` + `make_payload`.
  Endpoint = `base_pipeline.ENDPOINT_URL` (internal dev server). `reset_each_spin` toggles
  `ResetPlayerStateAfterEachSpin` — neither mode captures out-of-engine mechanics.
- **Roster note:** `configs/machines.json` (the per-machine config/code md5s) is a DOWNLOADED
  upstream cache (gitignored) — refreshed via the console, not hand-edited. A chunk whose `code_md5`
  differs from the roster shows in the console's "历史" rawdata cell and regenerates from there.
- **Direction / state:** `session_artifacts/_arch_playtype/` (DIRECTION, HANDOFF, 02_traces = M15
  ground truth) + `session_artifacts/_onboard/<M>/` (per-machine wave artifacts).
