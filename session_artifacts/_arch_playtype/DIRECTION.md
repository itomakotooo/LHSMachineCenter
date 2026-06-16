# DIRECTION — analyzer re-architecture (event-based, by SpinType)

> Authoritative direction + the corrected model. Rewritten 2026-06-02. The old play-type / PT-1..PT-15 /
> SpinType-primary framing was **deleted** (it was a fabricated abstraction the rawdata does not have).
> Hard rule from the user: **do NOT invent any layer beyond what the rawdata format already has.**

## 1. The goal (unchanged)
The analyzer's core logic (chunk parse / round classification / win attribution) lives in the `base_hash`
closure (`fresh_slotlab/analyzer/versioning.py::_CLOSURE_FILES`). Editing it to support or fix ONE machine
flips `base_hash` → the whole fleet re-flags. **Goal: relocate mechanic logic so editing one machine's logic
re-flags only the machines that use it, not the fleet.**

## 2. THE MODEL — mirror the rawdata, invent nothing
The rawdata is records, each tagged with a **SpinType** plus fields. Model exactly that. No layer the rawdata
doesn't have.

- **SpinType = a server↔client protocol token for a kind of EVENT** (a kind of machine logic). **NOT "a spin".**
  An event can be a reel spin, a **player choice / operation** (M15 ST=14: the player picks dollars —
  `DollarCount` / `ChosenDollar` / `OfferValue`), a **settlement** (M15 ST=15: `WinAmount`), or a
  **state / transition** (M260 ST=105: cost 0, win 0, empty). You learn what a SpinType means by **understanding
  the rawdata**, never by assuming — `win=0` ⇏ meaningless (a player choice has behavioral statistical value).
- **The unit of analysis = the SpinType (event).** For each SpinType: understand it → parse it → compute its
  statistics (economy / player-behavior / state) → (later) the web console renders it per-SpinType. A machine =
  its set of SpinTypes.
- **"Trigger" is NOT a layer — it only decides 统计口径 (which account an event's economy books to).** Real case
  **M275**: the SAME freespin SpinType is opened by either a scatter (`pay_id 666`) or the BCM cycle; the rounds
  parse identically but their economy books to different places, decided by the trigger. Attribution is
  per-trigger, not per-SpinType. (This is the existing `trigger_sessions.py` / `round_win.py` logic.)
- **"玩法" (e.g. TopDollar) = a group of related SpinTypes** (M15 TopDollar = ST1 trigger + ST14 choice +
  ST15 settlement) — a feature, NOT a separate "play-type" abstraction.
- **There is NO "play-type / PT" layer.** The PT-1..PT-15 taxonomy and the "play-type = trigger-session"
  framing were fabricated and have been deleted.

## 3. The two real concerns (both mirror the rawdata, neither is invented)
1. **Per-SpinType parsing** — shared by event kind (a freespin parses the same no matter what triggered it):
   a base-excluded library of "how to read each SpinType + the statistics it yields".
2. **Trigger attribution (统计口径)** — which account an event's economy books to, decided by what triggered the
   session it belongs to.

Isolation consequence: editing a shared per-SpinType parser re-flags every machine with that SpinType (correct —
it IS shared); editing a machine's trigger/attribution re-flags only that machine.

## 4. The isolation method (unchanged — this part works)
`CARVE_METHODOLOGY.md`: move a mechanic's logic OUT of the `base_hash` closure into a base-excluded module; prove
with the **base_hash gate** (edit the carved logic → `base_hash` unchanged; edit a universal closure fn → it
flips; pinned by a permanent test) **+ byte-identical + engagement**. byte-identical ALONE is not enough (that is
what let a hollow earlier carve pass).

## 5. Current state (HEAD)
- **2 genuine carves done** (logic moved OUT of the closure, base_hash-gate-proven): the **wild-nudge classifier**
  (`fresh_slotlab/analyzer/play_types/wild_nudge.py`) and the **BCM-cycle functions**
  (`fresh_slotlab/analyzer/play_types/bcm_cycle.py`, a redo of a hollow earlier attempt). Correct as isolation —
  they are per-SpinType parsing + a trigger primitive, NOT "play-types".
- **Phase D done — the play-type plugin FRAMEWORK was DELETED** (it was dormant scaffolding that contradicted
  §2: its `st_map[st]=owner` was the ST-primary model M275 disproves). The code now matches "no play-type layer":
  only the 2 carves remain under `play_types/`. `base_hash 85666c4c4407 → 8a791a69cd05` (byte-identical; the C3
  per-machine-config Layer-0 was output-redundant with `bcm_pairings.json`). Detail: `impl/phaseD_delete/`.
- **M15 TopDollar event model + ST=14 statistics validated on real rawdata** (`02_traces.md`):
  ST=14 is the player's pick (win is a preview = 0 economy; real win on ST=15); the pick statistics are real
  (TopDollar is a 1.1%-frequency event carrying ~50% of RTP).
- **BUILT (2026-06-07..11):** the SpinType-native engine is LIVE — `report_engine.py` + per-machine manifests
  (`machine_spec.derive_analyses`) + auto-discovered plugins; **M15 + M43 + M279 onboarded & confirmed** via the
  onboard-* 5-wave team (`docs/MACHINE_ONBOARDING.md` is the living playbook; `docs/ANALYZER_ARCHITECTURE.md`
  the framework spec). REMAINING from §3.1: the per-ST EXTRACTION layer is still the shared monolith parser —
  metrics needing per-round ReMarks/sequence accumulation (wheel CellIndex map, 6-prize un-merge, move
  burst-length, reel-skin breakout) are `parser_blind` until that carve lands (framework-team).

## 6. Process (the redesigned arch team)
Agent definitions: `.claude/agents/arch-*.md` (the process doc was deleted; the principles live in the agent
charters + memory). Ground every claim in a **real-rawdata trace** (`arch-tracer`) / an **objective gate**
(base_hash, byte-identical) / the **user's domain sign-off** — never abstract endorsement, **never a fabricated
layer**. Architecture / domain is discussed with the user (with traces); implementation detail (names, layout,
code) is gated objectively, not user-reviewed. Machine ONBOARDING (vs framework dev) uses the onboard-* team:
`docs/MACHINE_ONBOARDING.md`.
