# arch-* Team Process — cross-cutting refactor / architecture review

> **Purpose**: when a task touches **fleet-shared code** (analyzer, console backend/frontend, core engine, version hashing, schema, etc.), running this 6-agent team produces an architecture-grade review + design before code is changed. Designed to prevent the failure mode "one-machine observation → fleet-wide unilateral change → fleet impact never measured".
>
> **Not for**: per-machine bug fixes, small features confined to `slot_designer/machines/<M>/`, single-file edits with no cross-cutting concerns. Use direct edit or the slot-* team for those.

---

## §1 When to use this team

Trigger this team when any of the following apply to a planned change:

- Touches `fresh_slotlab/`, `slot_designer/core/`, `src/web_console/backend/`, or `src/web_console/frontend/` (fleet-shared code)
- Adds a new feature class or plugin Protocol
- Changes a hash/version composition rule
- Renames or restructures a schema field consumed by multiple downstream readers
- Migrates data format / report file layout
- Removes or consolidates duplicated code across sibling systems (e.g., prod console vs virtual console)
- User explicitly says "design", "refactor", "architecture", "framework"

Do NOT trigger for:

- Per-machine spec.json / weights.json / plugin.py edits (slot-* team handles)
- Bug fix isolated to a single file with no fan-out (direct edit)
- Documentation only changes
- Test additions for already-shipped behavior

---

## §2 Team composition (6 agents, 3 waves)

| Agent | `subagent_type` | Wave | Responsibility | Output |
|---|---|---|---|---|
| Pipeline Mapper | `arch-mapper` | 1 | End-to-end data-flow map of target pipeline; reuse-vs-duplication audit | `01_pipeline_map.md` |
| Fleet Taxonomist | `arch-taxonomist` | 1 | Classify fleet by structural similarity; outliers named | `02_taxonomy.md` |
| Coupling Auditor | `arch-coupling-auditor` | 1 | Blast radius of every shared symbol; hash composition map | `03_coupling_audit.md` |
| Architecture Designer | `arch-designer` | 2 | Synthesize Wave 1 → proposal with plugin model + hash rules + migration | `04_architecture_proposal.md` |
| Adversarial Critic | `arch-critic` | 3 | Hostile review; 10 stress questions; verdict | `05_critique.md` |
| Sample Validator | `arch-validator` | 3 | Walk 5-7 representative cases through proposal; verdict | `06_validation.md` |

Tools per agent are enforced via frontmatter `tools:` whitelist in `.claude/agents/arch-*.md`. None of them edit code — proposal stays in markdown until the user approves implementation.

---

## §3 Wave structure

### Wave 1 — Discovery (parallel)

Spawn `arch-mapper`, `arch-taxonomist`, `arch-coupling-auditor` in **parallel** (background). Each is independent — they don't read each other's output.

Inputs to each: codebase + relevant config files + user-supplied scope (which pipeline, which fleet).

When all three complete → Wave 2 starts.

### Wave 2 — Design (single agent)

Spawn `arch-designer`. Reads `01_pipeline_map.md` + `02_taxonomy.md` + `03_coupling_audit.md` + user-stated goals. Produces `04_architecture_proposal.md` with 2-3 design alternatives + recommended choice + migration plan.

### Wave 3 — Review (parallel)

Spawn `arch-critic` and `arch-validator` in **parallel**. Both read `04_architecture_proposal.md` + Wave 1 outputs. Produce `05_critique.md` + `06_validation.md`. Both deliver a verdict: APPROVE / APPROVE-WITH-REVISIONS / REJECT.

### Consolidation (main session, coordinator)

Main session reads all 6 artifacts → produces a short decision summary for the user. **Main session does NOT make the architectural decision** — it relays critic + validator verdicts and asks user to pick.

If Wave 3 verdict is APPROVE-WITH-REVISIONS or REJECT → loop back: arch-designer reads 05 + 06, produces `04_architecture_proposal_v2.md`. Wave 3 re-runs.

---

## §4 Information flow

All artifacts under `session_artifacts/_arch/`:

```
session_artifacts/_arch/
├── 00_brief.md                       # main session writes: task scope + user goals
├── 01_pipeline_map.md                # arch-mapper
├── 02_taxonomy.md                    # arch-taxonomist
├── 03_coupling_audit.md              # arch-coupling-auditor
├── 04_architecture_proposal.md       # arch-designer (vN bump on revisions)
├── 05_critique.md                    # arch-critic (vN matches 04 version)
├── 06_validation.md                  # arch-validator
└── 07_decision.md                    # main session writes: user decision + next steps
```

Agents read other agents' artifacts directly from disk (not via main session relay). Main session only authors `00_brief.md` and `07_decision.md`.

---

## §5 Invariants

1. **No agent edits code** — all output is markdown only. Implementation happens in a separate pass after user approval (different team / direct edit).
2. **No agent does another agent's job** — Mapper doesn't propose; Designer doesn't validate; Critic doesn't redesign. Single responsibility enforced by tool surface in frontmatter.
3. **Wave 1 agents run in parallel** — they don't depend on each other.
4. **Wave 3 agents run in parallel** — they're independent reviewers.
5. **All decisions cite Wave 1 evidence** — Designer cannot propose without grounding in 01/02/03; Critic cannot critique without specific references.
6. **User signs off the recommendation** — main session presents critic + validator verdicts; user decides whether to proceed to implementation, request revision, or abandon.

---

## §6 How to invoke

### Coordinator (main session) kickoff

1. Write `session_artifacts/_arch/00_brief.md` with:
   - Task: what is the architectural problem?
   - Scope: which pipeline / which fleet / which files in / out of scope?
   - Constraints: what must not break? what's already shipped?
   - Goals: cite user statements verbatim
2. Spawn Wave 1 three agents (parallel, background):
   - `subagent_type: arch-mapper` with brief pointing to `00_brief.md` + scope hints
   - `subagent_type: arch-taxonomist` likewise
   - `subagent_type: arch-coupling-auditor` likewise
3. Wait for all three completion notifications
4. Spawn `arch-designer` (Wave 2). Brief includes paths to 01/02/03.
5. Wait. Spawn Wave 3 two agents in parallel.
6. Read 04+05+06 → write `07_decision.md` summary → present to user

### Reuse for future tasks

When user requests a new cross-cutting refactor / feature:
- Create a new `session_artifacts/_arch_<topic>/` directory (e.g., `_arch_auth_refactor/`)
- Write fresh `00_brief.md`
- Re-spawn the agents with paths pointing to the new directory
- The agent definitions in `.claude/agents/arch-*.md` are stable and reusable; only the brief changes per task

---

## §7 Anti-patterns (don't do these)

- **Skipping Wave 1**: jumping to Designer without Mapper / Taxonomist / Auditor = design grounded in main-session assumptions, not codebase reality. Same failure mode as past "one-machine change → fleet impact" mistakes.
- **Designer doing Critic's job**: Designer self-critiquing in the proposal hides weak points. Use Critic as adversary.
- **Critic redesigning**: Critic flags problems, Designer iterates. If Critic redesigns, you lose the adversarial review.
- **Spawning agents in series when they should be parallel**: Wave 1 and Wave 3 are independent within wave; parallel saves time.
- **Main session deciding the architecture**: Main session relays verdicts + summarises; user decides. Coordinator-only discipline (per slot_designer/ONBOARDING_PROCESS.md §4.0.1) applies here too.
- **Adding implementation tools to agents**: Edit/Write to source code is forbidden in Wave 1/2/3. All artifacts are markdown. Implementation is a separate pass.

---

## §8 Relation to other team processes

| Pattern | When | Where defined |
|---|---|---|
| slot-* team (R/A/I/D/V/X) | New slot machine onboarding (rawdata → spec → weights → verify → ship) | `slot_designer/ONBOARDING_PROCESS.md` |
| **arch-* team (this doc §1-7)** | **Cross-cutting refactor / architecture review touching shared code (design phase)** | **`docs/ARCH_TEAM_PROCESS.md` §1-7** |
| **impl-* team (this doc §9)** | **Implementation phase — execute an arch-* approved proposal (multi-file refactor, new module, cross-cutting code change)** | **`docs/ARCH_TEAM_PROCESS.md` §9** |
| Direct edit | Single-file fix, no fan-out, trivial patches | n/a — main session |

The teams complement each other: arch-* designs the framework + produces a written proposal; impl-* executes the proposal phase-by-phase (one commit per phase, with full implementer → tester → verifier → critic loop); slot-* uses the framework for per-machine onboarding (independent domain).

---

## §9 Implementation phase (impl-* team)

> **Purpose**: when an arch-* proposal needs to be implemented (or any multi-file refactor / new module / cross-cutting code change), the impl-* 4-agent team executes the work with separation between author + reviewer. Designed to prevent the failure mode "same Claude wrote the code, wrote the test, signed off the commit — no external angle".
>
> **Not for**: single-file bug fix, docs-only commits, trivial patches. Use direct edit for those.

### §9.1 When to use this team

- Implementing a phase from an arch-* proposal (e.g. `04_v2.md §6 Phase N deliverables`)
- Multi-file code change touching fleet-shared code
- New module addition with non-trivial test coverage
- Refactor that needs adversarial review before commit

### §9.2 Team composition (4 agents, sequential)

| Agent | `subagent_type` | Responsibility | Tool surface | Output |
|---|---|---|---|---|
| Implementer | `impl-implementer` | Write code per design proposal; minimum-delta; reuse sibling patterns; smoke check | Read, Glob, Grep, Edit, Write, Bash | uncommitted file changes |
| Tester | `impl-tester` | Write tests + run inject-bug → red → revert → green per `feedback_enumerate_safety_paths.md` | Read, Glob, Grep, Edit, Write, Bash | uncommitted test files + inject-bug evidence |
| Verifier | `impl-verifier` | E2E / smoke / broader-suite verification; real subprocess against cached fixtures; failure injection | Read, Glob, Grep, Bash | claim-by-claim verification report |
| Critic | `impl-critic` | Adversarial review of diff + tests + claims before commit; 10+ stress questions; verdict | Read, Glob, Grep, Bash (read-only), Write | `session_artifacts/_impl/<phase>/critique.md` + APPROVE / APPROVE-WITH-FIXES / REJECT verdict |

Sequential, not parallel — each agent reads the previous agent's output. Critic is the final gate before coordinator commits.

### §9.3 Phase structure (per commit)

```
1. Coordinator briefs impl-implementer with design proposal section
   → impl-implementer writes code + smoke check
2. Coordinator briefs impl-tester with implementer's summary
   → impl-tester writes tests + runs inject-bug verification
3. Coordinator briefs impl-verifier with implementer + tester summaries
   → impl-verifier runs broader e2e / smoke
4. Coordinator briefs impl-critic with all three summaries + commit-message draft
   → impl-critic adversarial review + verdict
5. If REJECT or APPROVE-WITH-FIXES → loop back (implementer fixes; tester re-runs)
6. If APPROVE → coordinator commits with 4-section message
```

### §9.4 Information flow

All artifacts under `session_artifacts/_impl/<phase>/`:

```
session_artifacts/_impl/p1/
├── brief.md         # coordinator writes: phase scope + deliverables + memory feedback to honor
├── verification.md  # impl-verifier (optional — for written e2e report)
└── critique.md      # impl-critic (always — final gate)
```

The implementer + tester outputs are CODE (committed via coordinator), not markdown artifacts.

### §9.5 Invariants

1. **No agent solo-commits** — only main-session coordinator commits, after impl-critic APPROVE
2. **No skipping agents** — even if "obvious", run the loop. Especially impl-critic.
3. **Each agent reads its predecessors' summaries** — coordinator passes them in brief
4. **Inject-bug is mandatory** — per `feedback_enumerate_safety_paths.md`, tester must temporarily break protection and observe test failure as evidence the test catches the regression
5. **Critic verdict is binding** — REJECT means loop. APPROVE-WITH-FIXES means fix before commit. APPROVE means commit.
6. **Phases are atomic at commit boundary** — each phase is one logical commit (or one PR with multiple commits per the design). Don't mix phases.

### §9.6 Anti-patterns

- **Coordinator writing the code directly** — defeats the separation; use impl-implementer even for "small" tasks within a phase
- **Skipping impl-critic because "tests pass"** — `memory/feedback_adversarial_self_review.md`: verify GREEN ≠ done when verify is what I designed
- **Combining impl-implementer + impl-tester** — same Claude writes code + tests = no adversarial angle, even with the agent separation. Use distinct agent invocations.
- **Running phases in parallel** — phases have dependencies (Phase 2 depends on Phase 1 backward-compat); serialize them

### §9.7 How to invoke (coordinator)

1. Read design proposal section for this phase (e.g. `04_v2.md §6 Phase 1`)
2. Write `session_artifacts/_impl/<phase>/brief.md` with phase scope + memory feedback files + claims to verify
3. Spawn `impl-implementer` (foreground or background) with brief → wait for completion
4. Spawn `impl-tester` with implementer's summary → wait
5. Spawn `impl-verifier` with both summaries → wait
6. Spawn `impl-critic` with all three summaries + commit-message draft → wait
7. Process critic verdict:
   - APPROVE → coordinator commits
   - APPROVE-WITH-FIXES → loop steps 3-6 with fix list
   - REJECT → loop steps 3-6 with major rework
8. After commit → mark phase done in TodoWrite → next phase

---

## §10 Memory pointer

For future sessions:
- `memory/feedback_arch_team_process.md` — when to spawn arch-* team for design phase (auto-memory pointer added 2026-05-15)
- `memory/feedback_impl_team_required.md` — when to spawn impl-* team for implementation phase (auto-memory pointer added 2026-05-17)
