# CARVE METHODOLOGY — how to move a mechanic out of the base, and PROVE it

> Authoritative "how to carve a play-type" doc. Written 2026-06-02 after C2 shipped a **hollow**
> carve (the logic never left the base closure → zero isolation) that was mislabeled a "milestone".
> Reference implementation of a GENUINE carve: PT-7 wild-nudge, commit `8445312`.

## 0. The rule that stops "docs don't match reality"
Every carve claim — in any doc, commit message, or handoff — MUST be a **verified, reproducible
property**, never a subjective label.

- ❌ "first real carve / MILESTONE / 1 of 15 carved" — unfalsifiable; drifts from reality; this is
  exactly what kept mismatching each new session.
- ✅ "editing `play_types/wild_nudge.py` leaves `base_hash` at `48eada424d82` (was `fd5f7d01e1cb`);
  `pytest tests/backend/test_wild_nudge_carve.py` pins it" — anyone can run it.

If you cannot cite the hash before/after **and** a passing gate test, you have not carved anything.
Then say "not carved", not "milestone".

## 1. The goal (what isolation actually means)
`base_hash` = sha256 of the files **listed in** `fresh_slotlab/analyzer/versioning.py::_CLOSURE_FILES`
(a curated list — NOT the Python import graph). Every machine's `effective_analyzer_version` includes
`base_hash`. Therefore **editing any file in that list re-flags the entire fleet.**

The refactor's only goal: relocate a mechanic's logic so editing it no longer changes `base_hash` →
only machines that use that mechanic re-flag.

## 2. Genuine carve vs the hollow trap
- **Genuine carve:** the mechanic's logic CODE physically lives in a module that is **NOT** in
  `_CLOSURE_FILES` (e.g. `analyzer/play_types/<x>.py`, `analyzer/features/<x>.py`). Editing that file
  cannot change `base_hash`.
- **Hollow carve (the C2 anti-pattern — DO NOT do this):** the logic stays in a closure file
  (`round_classification.py`, `parser.py`, `round_win.py`, `trigger_sessions.py`, ...) and a plugin
  merely CALLS it — or, worst form, both the inline path and the plugin call a "shared helper" left
  in the base. This passes byte-identical **trivially** (the code never moved) and delivers **zero
  isolation**: editing the mechanic still flips `base_hash`.

> **C2 (commit `6b10942`)** added `compute_robot_cycle_peaks` to `round_classification.py` (a closure
> file, +58 lines) and had `BCMBaseAccumulator` call it. Editing the BCM cycle rule flips `base_hash`
> → the whole fleet re-flags. It is NOT a carve. It must be redone by moving the BCM functions into
> `bcm_base.py`.

**The tell:** if your carve is "byte-identical *by construction*", you almost certainly did NOT move
the logic — "byte-identical by construction" means "nothing moved".

## 3. The acceptance gate — this REPLACES "byte-identical alone"
A carve is done **iff** a permanent test asserts BOTH:

1. **Isolation:** editing the carved logic (in its new non-closure home) → `base_hash` **UNCHANGED**.
2. **Paired guard:** editing a universal function still in the closure → `base_hash` **FLIPS**.
   (Without #2 you could fake isolation by deleting the whole file from `_CLOSURE_FILES`, which would
   also silence legitimate universal-edit re-flags — over-isolation.)

Reference: `tests/backend/test_wild_nudge_carve.py`. byte-identical / engagement / exact-relocation
(below) are **necessary supporting checks, NOT the gate**. byte-identical alone is exactly what let
the hollow C2 pass.

## 4. Supporting checks (all required; none sufficient alone)
- **byte-identical output:** analyzer flag-OFF **and** flag-ON vs a pre-carve baseline, on a machine
  whose data ACTUALLY exercises the mechanic. **Verify the mechanic's rounds are present first** —
  deep-parse the JSON-string-encoded `response` (a raw-text grep FALSE-NEGATIVES on escaped JSON; this
  bit me — M279 mode_1 has 4,599 `ST=36` nudge rounds/chunk that a raw grep reported as 0). Normalize
  volatile/version fields (`report_id`, `run_id`, `analyzer_version`, `effective_analyzer_version`,
  timestamps) + sort set-ordering fields (`top_symbols`, `payline_symbol_top20`, `paylines_top20`).
  Read JSON as **UTF-8** (Windows gbk default errors on these files).
- **engagement:** monkeypatch the relocated function to misbehave → the real parser output CHANGES →
  it is live, not bypassed. (wild-nudge: corrupt it → `spin_type_nudge_round_count` + `chain_*` fields
  change.) Patch the CONSUMER's binding (parser imported the name, so patch
  `analyzer.core.parser.<fn>`, not the source module's attribute).
- **exact-relocation (pure moves):** diff the moved function vs `git show HEAD:<oldfile>` → byte-identical
  → behavior cannot have changed.

## 5. The one-time cost (don't confuse it with the ongoing property)
Moving logic OUT edits closure files (delete from the old file; repoint importers in parser.py etc.).
That changes `base_hash` **once** (wild-nudge: `fd5f7d01e1cb → 48eada424d82`). Expected for every
carve. Re-pin the 8 base_hash-pin tests to the new value **with a documented reason** (the
conscious-acknowledgment gate). The ISOLATION property (§3.1) is about edits made AFTER the move.

## 6. Workflow (the wild-nudge carve, step by step — `8445312`)
1. **Recon:** find the function + ALL call sites + ALL importers (grep repo-wide incl. `tests/`,
   `scripts/`). Confirm closure→plugin import is already accepted (PIA imports `analyzer/features/*`).
2. **Baseline:** capture pre-carve analyzer output (flag off+on) on a mechanic-exercising machine.
3. **Move:** relocate the logic into a new base-excluded module (`play_types/<x>.py`). Import-only;
   do NOT self-register a plugin if that would change flag-on output (keep byte-identical risk zero).
4. **Repoint:** importers (parser.py dual-path); drop dead imports; fix the old file's docstring.
5. **Tests:** repoint the function's existing unit tests (they validate behavior post-move).
6. **Gate test:** add the §3 isolation+paired-guard test.
7. **Verify, in order:** import smoke → §3 base_hash gate → §4 byte-identical → §4 engagement →
   §4 exact-relocation → §5 re-pin base_hash tests → run all affected suites green.
8. **Commit surgically** (explicit paths; never `git add -A`). The commit message states the hash
   before/after + the gate result.

## 7. Scope honesty
A function-level carve (logic out of the closure; parser imports it) achieves the isolation property
**already**. Wrapping it as an accumulator-dispatched `PlayTypePlugin` is a SEPARATE refinement that
does NOT change the hash property. Do not conflate "function carved" with "full plugin built", and do
not claim either without the §3 gate.

## 8. What counts as a carve UNIT (per `DIRECTION.md §12`)
This doc is about HOW to carve (move logic out of the closure + the base_hash gate) — unchanged, applies to
any unit. But WHAT to carve is defined by the trigger-session model in `DIRECTION.md §12`, NOT by SpinType:
- **Shared round parsers** (freespin / wheel / paid / respin, keyed by round TYPE) carve into a shared
  base-excluded library — editing one re-flags every machine with that round type (correct; it IS shared).
- **A play-type** = a TRIGGER + its session attribution (统计口径) + stat rollup; it carves out the
  trigger/attribution logic and DELEGATES parsing to the shared library. The same reward ST under different
  triggers belongs to different play-types (real: M275 freespin via BCM cycle vs scatter).
Do NOT carve "an ST's parsing" as if it were a play-type — that re-conflates the two layers. Already-done
examples of the distinction: PT-3 BCM-cycle (a trigger detector) vs PT-7 wild-nudge (a shared round-classifier).
