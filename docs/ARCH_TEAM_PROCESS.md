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
| **arch-* team (this doc)** | **Cross-cutting refactor / architecture review touching shared code** | **`docs/ARCH_TEAM_PROCESS.md` (this file)** |
| Direct edit | Single-file fix, no fan-out | n/a — main session |

The two teams complement each other: arch-* designs the framework + shared code; slot-* uses the framework for per-machine onboarding. If arch-* output requires changes to slot-* definitions, that's part of the implementation pass downstream of arch-* approval.

---

## §9 Liveness check + troubleshooting (added 2026-05-17 after spawn opacity issues)

The Agent tool harness gives **limited mid-flight visibility**. To avoid panic-killing live agents (or assuming dead agents alive), use this procedure.

### What coordinator CAN see

- **Spawn response**: returns `agentId`. If Bash exit code = 0 + message says "Async agent launched successfully", harness accepted the spawn.
- **`.output` file size**: stays **0 bytes during run** (harness writes the full JSONL transcript only at completion). 0 bytes is NORMAL for in-flight tasks, even tasks running 30+ min.
- **`TaskOutput` tool with `block: false`**: returns harness's current status:
  - `running` — OS-level subprocess alive (harness tracks via PID lifecycle)
  - `completed` / `killed` / `error` — done states
  - `not_found` — task already disposed (e.g., after kill + cleanup, or harness restart wiped state)
- **Task notification**: pushed automatically when task completes (success/kill/error). Wait for it.

### What coordinator CANNOT see mid-flight

- Whether the agent's LLM is producing tokens or hung in a loop
- Tool-call success/failure (lives in JSONL transcript; reading it via Read overflows context — **do not Read the .output path**)
- Progress against the task plan

### Liveness procedure

When in doubt about an agent that's "running too long":

1. **Check elapsed time vs baseline**: smoke tests (trivial write) = 6-13 sec; Wave 1 mapper/taxonomist/auditor = 8-13 min; Wave 2 designer = 7-12 min; Wave 3 critic/validator = 7-13 min. Beyond 2× baseline → suspect hang.
2. **`TaskOutput block: false`**: if status = `running` AND time within 2× baseline → trust + wait. If status = anything else → act accordingly.
3. **DO NOT panic-kill** based on "0 bytes .output" — that's the design, not a failure signal.
4. **If killing**: prefer waiting at least 2× baseline first. The 2026-05-17 session lost a live Designer v4 because coordinator killed at ~30 min (1.5× v3 baseline); kill-time notification showed agent was alive about to write output.

### Smoke test baseline (run after any harness restart or agent-definition change)

After restarting Claude Code or editing any `.claude/agents/arch-*.md`, run smoke tests to verify all 6 agent types are recognized by harness:

```
For each arch-* agent type: spawn with trivial task (write single-line file to
session_artifacts/_arch/_team_test/test_<role>.md). Expect 6-13 seconds. If
spawn fails with "Agent type not found" → agent files haven't been hot-loaded;
restart Claude Code session. If spawn succeeds but task notification never
arrives → likely transient; respawn once before deeper diagnosis.
```

Verified 2026-05-17: all 6 types work post-restart. arch-mapper 10.4s / arch-taxonomist 10.7s / arch-coupling-auditor 12.6s / arch-designer 6.2s / arch-critic 8.0s / arch-validator 10.2s.

### Failure modes observed (2026-05-17 session)

1. **Spawn returns agentId but agent silently dies**: 1st Designer v4 attempt with `arch-designer` subagent_type post-restart. After 1 hour, TaskOutput returned `not_found` (harness had disposed it). Cause unknown — possibly race between restart-pickup of agent definitions and the spawn call. **Recovery**: respawn with same or fallback type.
2. **Coordinator kills live agent based on "0 bytes" assumption**: 2nd Designer v4 attempt. Killed at ~10 min when agent was about to write. Lost the work. **Recovery**: addressed by this troubleshooting section + procedure above.
3. **Spawn → immediate `not_found`**: 3rd Designer v4 attempt. Spawn returned agentId but TaskOutput within 60 sec returned `not_found`. Possibly harness in cleanup-pending state from previous kill. **Recovery**: respawn after 30+ sec delay.

---

## §10 Memory pointer

For future sessions: searchable via `memory/feedback_arch_team_process.md` (auto-memory pointer added 2026-05-15; troubleshooting added 2026-05-17).
