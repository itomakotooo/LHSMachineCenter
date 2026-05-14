# M43 — Session 1 handoff (2026-05-13 → 2026-05-14)

> **Pickup note for next session.** Read this first, then `00_SESSION_BRIEF.md`, then `02_engine_implementation_notes.md`.

---

## Current ship state

| Stage | Status | Commit |
|---|---|---|
| 0 — kickoff | ✓ committed | `dd65211` |
| 1a — data inventory | ✓ committed | `dd65211` |
| 1b — baseline 12 sections | ✓ committed | `dd65211` |
| 1c — mechanism inference | ✓ committed (paytable HIGH; respin trigger LOW; mini-game trigger LOW) | `dd65211` |
| 1d — archetype research | ✓ committed (Lucky Ducky = VGT Class II, not IGT) | `dd65211` |
| 1d-supp — duck multiplier reference | ✓ committed (Proposals A vs B) | `dd65211` |
| 2 — engine implementation | ✓ committed (byte-aligned, 25/25 tests, schema fp `5d02773c069fc396` matches production) | `dd65211` |
| 3 — bootstrap weights | ✓ implicit (Implementer derived directly from xlsx skinId 1 in Stage 2; rawdata cross-check 0.04pp max drift) | `dd65211` |
| **2.5 — fill structural gaps** | **DEFERRED — decision pending** | — |
| 3.5 — Boundary Contract | not started | — |
| 4-10 | not started | — |

## Deferred decision — Stage 2.5 vs Stage 3.5 (user pending)

Engine RTP 88.6% vs production 93.23% — 4.6pp structural gap, decomposed:

| gap | RTP pp | status |
|---|---|---|
| pay_id 8 ("wild_blank_special", 912/650k @5×) unimplemented | ~1.0pp | predicate ambiguous — 01c §3 lists 3 candidate rules. Needs user clarification or rawdata deeper dig |
| Off-payline wild doubling unimplemented | ~2-3pp | engine only stacks ON-payline wilds; production doubles when wild lands in 3×3 window OFF the payline. Plugin post-processor ~1h work |
| Mini-game trigger rate small drift + small N noise | ~1pp | Stage 6 refit candidate |

**Three user options previously offered, no answer yet**:
- (A) Stage 2.5: Implementer fills gaps (off-payline wild + pay_id 8 deeper dig from rawdata) before Stage 3.5 → contract drafted on faithful engine
- (B) Direct Stage 3.5: accept 4.6pp gap as Stage 6 close-out; contract drafting may be less precise on feasibility
- (C) User fetches server spec / paytable doc to lock pay_id 8 + off-payline rule deterministically (would shorten 2.5 to ~30 min)

Next session: re-pose to user, get decision, proceed.

## Critical: Claude Code restart required

This session ended after committing `.claude/agents/slot-{role}.md` × 6
(commit `9dae83f`). The Claude Code harness scans `.claude/agents/` only
at **session startup** — current session does NOT see the new agents.

**Before next session starts: restart Claude Code.** Then:
- Typeahead `@agent-slot-researcher` should surface the 6 subagents
- Agent tool's "Available agent types" list (in system prompt) will
  include `slot-researcher / slot-analyst / slot-implementer /
  slot-designer / slot-verifier / slot-critic`
- Each agent's `tools:` whitelist is harness-enforced (Researcher
  physically cannot call Bash; Designer / Critic cannot Edit; etc.)

If the typeahead doesn't show them after restart:
- Verify files at `.claude/agents/*.md` present (commit ef6bc6e has
  6 files)
- Try `claude agents | cat` to list registered agents
- Check no YAML parse error in frontmatter

## Stage 3.5 = first real validation of agent team

Stage 3.5 (Boundary Contract drafting) is the only stage that uses
**all 6 agents in one collaborative pass** (per ONBOARDING §4.0 +
§5.3.5). It's the most stressful test of:
- Tool-surface enforcement (Designer can't accidentally Edit weights;
  Verifier can't accidentally write design narrative; etc.)
- Multi-agent artifact handoff via files (not chat)
- User sign-off mechanic (frozen contract + immutability)

Recommend: after restart, spawn `slot-analyst` first for a fast
feasibility-pre-check warmup, verify it works as expected, then commit
to the full Stage 3.5 sequence.

## Session 1 commits (chronological)

```
6d5ffae docs(slot_designer): add Stage 3.5 Boundary Contract
a965b6c docs(slot_designer): mode-1-first universal workflow
[566da66 docs(slot_designer): add 6 agent base prompts + assembly README]  # user-added during my work, later superseded
dd65211 feat(slot_designer/M43): Stage 1+2 — Lucky Ducky onboarding kickoff
9dae83f feat(slot_designer): real agent team via .claude/agents/
ef6bc6e chore(slot_designer): remove slot_designer/templates/agent_prompts/
```

## Next session ground rules (user-mandated 2026-05-14)

**Main session role: coordinator only.** All substantive work goes to agents.

| Main session DOES | Main session does NOT |
|---|---|
| Decide which agent to spawn for which task | Read rawdata / xlsx / config files for analysis (Analyst does this) |
| Translate user input into agent prompts | Run Python scripts for data verification (Analyst) |
| Git commits / file operations / dir creation | Write spec.json / strips / weights / plugins (Implementer) |
| Summarize agent outputs back to user | Write DESIGN.md / MODE_DESIGN.md / target.json / BOUNDARY_CONTRACT (Designer) |
| Wait for user decisions and relay | Write verify.py red lines or run them (Verifier) |
| Spawn X for critique at milestones | Make design / verify / review decisions (the corresponding agent) |
| Track todos | Cross-check agent outputs by re-doing the work inline |

**Session 1 violations (for awareness, not repeat)**:
- Read M43Basic / M43Reel / M43Wheel / Caculate / Jackpot xlsx with inline Python — should have been Analyst with a "cross-check xlsx vs 01c rawdata-inferred mechanism" task
- Mini-game token-to-multiplier sum verification (4199 records, 100% match) — should have been Analyst supplementary task
- Respin reel marginal comparison (base vs respin) — should have been Analyst supplementary task
- xlsx surface triage (4 buckets: tunable / read-only / useless / hidden) — should have been Analyst output

These were all "main session figured it out inline because it was faster". User correction: even faster is no excuse — agent boundary must hold or Stage 3.5+ stakes break down (Designer needs A's report, not main session's summary; Verifier needs the artifact, not transcript).

**Operational rule**: if at any point next session main session is about to Read a rawdata chunk / Edit a spec file / run a Python analysis / write a design narrative — STOP, spawn the right agent.

Exceptions (genuinely main-session work):
- Reading agent output artifacts to brief the next agent or relay to user
- Writing SESSION_BRIEF / handoff notes / commit messages
- Running `git` / `mkdir` / `ls`-style ops
- Reading ONBOARDING / WORKFLOW / PHILOSOPHY / ARCHITECTURE (coordinator must know these)

## Process improvement candidates from this session

1. **Agent base prompts confusion** — at one point I (main session)
   thought `slot_designer/templates/agent_prompts/` didn't exist when
   it did (user had committed during my work). Cost: one inaccurate
   commit message ("files never created") and a duplicate `.claude/agents/`
   workstream. Lesson: always `git log -- <path>` before claiming
   a file doesn't exist. Or `git ls-files | grep <pattern>`.

2. **R agent stall** — first Researcher attempt for duck multiplier
   research stalled at 10 minutes no progress (likely WebSearch rate
   limit). Retry with explicit 30-min budget + 5 query cap delivered
   in 20 min. Pattern: any agent task involving WebSearch on niche
   topic should pre-budget time + accept partial results.

3. **Implementer extending core/** — M43 needed FeaturePlugin Protocol
   extension (`outcome=` kwarg) for outcome-conditional triggers.
   Implementer rightly extended core/engine/ + updated docs +
   M15 plugin backward-compat. This was an acceptable scope expansion
   because of strict additive semantics. But should be flagged
   explicitly in `02_engine_implementation_notes.md` for main session
   to ratify (it was). Pattern OK; document it.
