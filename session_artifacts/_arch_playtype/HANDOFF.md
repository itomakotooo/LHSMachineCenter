# HANDOFF — analyzer event-based re-architecture (READ THIS FIRST)

> 2026-06-02, branch `claude/playtype-rearch`. The MODEL lives in `DIRECTION.md` — read it first. It is
> **event-based, by SpinType, with NO fabricated "play-type / PT" layer.** `CARVE_METHODOLOGY.md` = the
> isolation gate. Every claim here is backed by a runnable check — trust the code over any label.

## The model (one line; full in DIRECTION)
The rawdata is records tagged with a **SpinType** (an EVENT kind: reel spin / player-choice / settlement / state)
plus fields. **The unit is the SpinType** — each is understood → parsed → its statistics. **"Trigger" is not a
layer**; it only decides 统计口径 (which account an event's economy books to). **"玩法"** (e.g. TopDollar) = a
group of related SpinTypes. **Do not invent any layer the rawdata doesn't have.**

## Done — genuine, isolation-proven by the base_hash gate
- **wild-nudge classifier** moved OUT of the closure → `fresh_slotlab/analyzer/play_types/wild_nudge.py`
  (pinned by `tests/backend/test_wild_nudge_carve.py`).
- **BCM-cycle functions** moved OUT → `fresh_slotlab/analyzer/play_types/bcm_cycle.py`
  (pinned by `tests/backend/test_bcm_cycle_carve.py`; a redo of a hollow earlier attempt that stayed in the closure).
- These are per-SpinType parsing + a trigger primitive — **NOT "play-types"**.
- `base_hash = 85666c4c4407`. Suites green at **code-HEAD `c21eb4e`** (1221 passed + pin/gate 447 + 375).
  Every commit since is **docs-only** (deletions + this rewrite) → code unchanged → still green.

## Validated on real rawdata (the model proven, not asserted)
- **M275**: the same freespin SpinType is opened by a scatter (437 sessions) or the BCM cycle (39) — **identical
  parse, different account**; every session attributes to exactly one trigger (0 orphan, no double-count).
  → proves trigger = attribution, not a per-SpinType thing; the old "split by SpinType" model can't express it.
- **M15 TopDollar**: ST=14 is the player's pick (玩法: up to 4 picks, stop early or forced at the 4th); its
  `WinCredits` is a preview (0 economy), real win on ST=15. The pick statistics are real — **1.1% trigger rate,
  ~50% of RTP**, gamble-to-4th 46%, of which 45% land below a passed offer. Spec + the M275 trace: `02_traces.md`.

## Next
Build the integrated per-SpinType event parser — first instance **M15** (parse ST=1 / 14 / 15 + the ST=14 stats +
trigger attribution), gated byte-identical + base_hash + the M275/M15 traces. Through the redesigned arch process
(`docs/ARCH_TEAM_PROCESS.md`).

## Carve method (read `CARVE_METHODOLOGY.md`)
Move the logic OUT of the `base_hash` closure → prove with the **base_hash gate** (edit it → hash unchanged; edit
a universal closure fn → flips; permanent test) **+ byte-identical + engagement**. byte-identical alone is not enough.

## Resume notes
- `ALL_PLAY_TYPE_PLUGINS` is a module global → test files need a module-level autouse snapshot/restore fixture
  (`test_bcm_base.py` 146–159), else engagement tests flake cross-file.
- ⚠ Background agents died silently twice — run agents FOREGROUND / check liveness; don't blind-wait.
- Surgical commits — the tree has pre-existing junk (`configs/machines.json`, `cache/`, `reports/`, prior
  `session_artifacts/_impl`) — never `git add -A`; stage explicit paths.
- Any closure-touching change shifts `base_hash` → re-pin the 8 base_hash-pin tests with a documented reason.

## File map
- Model + direction: `DIRECTION.md` · isolation gate: `CARVE_METHODOLOGY.md` · arch process: `docs/ARCH_TEAM_PROCESS.md`
- Carves (reference): `play_types/wild_nudge.py` + `play_types/bcm_cycle.py` (+ their `test_*_carve.py`)
- Real-rawdata ground truth (the M275 trigger trace + the M15 event spec / ST=14 stats): `02_traces.md`
- Closure list (what `base_hash` covers): `fresh_slotlab/analyzer/versioning.py::_CLOSURE_FILES`
