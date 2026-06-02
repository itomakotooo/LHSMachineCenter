# arch-* Team Process — cross-cutting refactor / architecture review

> **Purpose**: when a task touches **fleet-shared code** (analyzer, console backend/frontend, core engine, version hashing, schema, etc.), running this 6-agent team produces an architecture-grade review + design before code is changed. Designed to prevent the failure mode "one-machine observation → fleet-wide unilateral change → fleet impact never measured".
>
> **Not for**: per-machine bug fixes, small features confined to `slot_designer/machines/<M>/`, single-file edits with no cross-cutting concerns. Use direct edit or the slot-* team for those.

---

## §0 REDESIGN (2026-06-02) — why, and the one principle

**Why redesigned.** The original team (mapper/taxonomist/coupling → designer → critic/validator) produced an architecture that was **fundamentally wrong, and its own critic + validator did not catch it**: the play-type model was ST-primary and could not express "same SpinType, different trigger, different 统计口径" — which is real on M275 (one freespin ST, triggered by both a scatter and the BCM cycle, same parse but different accounting). **Every correction came from the USER's domain knowledge applied to real rawdata, never from the team's internal review.** Root cause: the team reasoned about the DOMAIN from artifacts (a signal census, the code) without grounding in how machines actually behave; its adversarial layer checked internal consistency, not domain truth against real data; and the coordinator "review" was abstract endorsement (it rubber-stamped a hollow carve as a "milestone").

**The one principle (everything below enforces it):**
> **Every architectural claim must be anchored to (a) a real-rawdata TRACE, (b) an objective GATE result (base_hash gate / byte-identical), or (c) the user's explicit domain SIGN-OFF. A claim resting on plausibility or "I read it and it looks right" is NOT done. Agents do NOT invent the domain model.**

This brings the arch team up to the discipline the **slot_designer team already has and that works**: a real-data analyst (there: `slot-analyst`), objective red-line gates (there: `verify.py` + inject-bug), and a user-signed contract grounded in data (there: the Boundary Contract). The arch team had **none** of those equivalents — that is the gap this redesign closes.

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

## §2 Team composition (redesigned 2026-06-02)

| Agent | `subagent_type` | Wave | Responsibility | Anchored to | Output |
|---|---|---|---|---|---|
| Pipeline Mapper | `arch-mapper` | 1 | Data/control-flow map + reuse-vs-duplication audit (mechanical) | code (objective) | `01_pipeline_map.md` |
| **Tracer** (NEW) | `arch-tracer` | 1 | **Real-rawdata TRACES of how machines actually behave** — session traces, trigger→reward attribution, per-round economy, edge cases. **NO design, NO opinions — evidence tables only.** Has **Bash**; deep-parses cached chunks (`json.loads` the JSON-string `response`). | **real rawdata (ground truth)** | `02_traces.md` |
| Coupling Auditor | `arch-coupling-auditor` | 1 | Blast radius of shared symbols + closure / hash-composition map (mechanical) | code + `_CLOSURE_FILES` (objective) | `03_coupling_audit.md` |
| Architecture Designer | `arch-designer` | 2 | Synthesize → proposal. **Every domain claim cites a Tracer trace ID, or is tagged `UNVERIFIED-NEEDS-TRACE`.** May NOT assert domain facts on its own. | Tracer traces + coupling map | `04_architecture_proposal.md` |
| **Breaker** (replaces critic+validator) | `arch-breaker` | 3 | **Adversarial against REAL machines**: pick the hardest / weirdest real machines, trace them through the design, and produce a concrete **breaking counterexample (with the rawdata)** OR attach the traces proving the design held. Has **Bash**. NOT internal-consistency review. | real-rawdata counterexamples | `05_breaker.md` |

**Demoted — `arch-taxonomist`:** its old job (abstract clustering of fleet signals into an *ontology*) is exactly what produced the wrong play-type taxonomy. It is retained ONLY as a fleet **census** input (which machines emit which signals), NEVER as the source of the domain model. The model comes from Tracer evidence → Designer → the user's sign-off.

**Superseded — `arch-critic` + `arch-validator`:** the internal-consistency reviewer pair is replaced by `arch-breaker` (real-data counterexample attacker). The old pair failed to catch the M275 flaw precisely because they attacked the proposal's internal logic, not ground truth. (The `.md` files remain but are not spawned for this kind of work.)

Tools per agent are enforced via the frontmatter `tools:` whitelist in `.claude/agents/arch-*.md`. **No agent edits source code** — design output is markdown only; the Tracer/Breaker get Bash for read-only rawdata tracing (no Edit/Write to code). Implementation is a separate pass (impl-* team, §9), gated objectively.

---

## §2A Coordinator (main session) responsibilities

The main session is **NOT a passive relay**, and **NOT an architect who endorses on reading**. Its job:

1. **Own the gates, not the opinions.** For every agent deliverable, the coordinator runs an **independent objective check** — re-run a Tracer trace, run the base_hash gate, run byte-identical, or try to break a claim — and reports **"verified by trace/gate X"** or **"UNVERIFIED — needs the user's domain check."** The coordinator **NEVER** signs off on "it reads correctly." (Abstract endorsement is the exact original failure: it stamped a hollow carve "MILESTONE".)
2. **Bring the user DATA-STRESS-TESTED choices, not summaries.** When presenting the domain model for sign-off, the package MUST include the **hardest real cases TRACED OUT** (e.g. "M275: same freespin ST, two triggers — here is the trace; does your model handle it?"). The ST-primary model would have been caught at sign-off had M275 been traced; a clean summary hid it.
3. **Do not scale past the pilot before the user signs the domain model.** No carving all N play-types, no fleet onboarding, no flipping a default flag, on the strength of a design review alone.
4. **Route + sequence agents; author `00_brief.md` + `07_decision.md`.** Don't do an agent's job; don't let an agent invent the domain model.

### §2A.1 Interaction boundary with the user (what to discuss, what NOT to) — user directive, 2026-06-02

- **DISCUSS WITH THE USER → architecture + domain model.** What is a play-type; how attribution / 统计口径 works; the trigger-session model; which mechanic is which; the boundary contract. The user holds the domain knowledge and is the authority here — surface these, **with real-data traces**, and get sign-off.
- **DO NOT bring to the user → internal implementation.** Variable names, function/class names, file layout, plugin internals, code structure, hash-composition mechanics, test names. The user explicitly does not read these ("变量名什么的我又看不懂"). They are verified by the **objective gates** (base_hash / byte-identical / trace-match) + the impl-* team — never by user review.
- **The line:** if a decision changes **WHAT the analyzer concludes** about a machine (domain / semantics) → **user**. If it only changes **HOW the code is organized** (implementation) → **coordinator + gates, never the user**.

---

## §3 Wave structure

### Wave 1 — Discovery (parallel)

Spawn `arch-mapper`, `arch-tracer`, `arch-coupling-auditor` in **parallel** (background). Each is independent. **`arch-tracer` is the ground-truth role — it deep-parses real cached rawdata and produces evidence tables, NO design.** (`arch-taxonomist` may be spawned as a census input only — which machines emit which signals — never as the source of the domain model; see §2.)

Inputs to each: codebase + relevant config files + user-supplied scope (which pipeline, which fleet).

When all three complete → Wave 2 starts.

### Wave 2 — Design (single agent)

Spawn `arch-designer`. Reads `01_pipeline_map.md` + `02_taxonomy.md` + `03_coupling_audit.md` + user-stated goals. Produces `04_architecture_proposal.md` with 2-3 design alternatives + recommended choice + migration plan.

### Wave 3 — Break against real data (single agent)

Spawn `arch-breaker`. It reads `04_architecture_proposal.md` + the Tracer's `02_traces.md`, picks the hardest / weirdest real machines, and **traces them through the design against real rawdata** (it has Bash). Output `05_breaker.md`: either a concrete **breaking counterexample** (machine + the rawdata trace the design mis-handles) OR the **per-machine traces proving the design held** — verdict `HELD` / `BREAKS-ON-<machine>`. It does NOT do internal-consistency review (that is what missed the M275 flaw).

### Consolidation (main session, coordinator) — run gates, present data-stress-tested choices

Main session (per §2A): (1) **independently re-runs** the key Tracer traces + the Breaker's counterexample (or a base_hash / byte-identical gate where code exists) — verifies, does not endorse; (2) assembles the **domain-model sign-off package = the design + the Breaker's hardest-case traces + the `UNVERIFIED` list** and presents it to the user **at the architecture / domain level only** (§2A.1); (3) does NOT decide the domain model itself, and does NOT scale past the pilot before sign-off.

If the Breaker reports `BREAKS-ON`, or the user's domain check rejects the model → loop back: `arch-designer` reads `05_breaker.md` + the user's correction → `04_..._v2.md`; Tracer adds any missing traces; Breaker re-runs.

---

## §4 Information flow

All artifacts under `session_artifacts/_arch/`:

```
session_artifacts/_arch/
├── 00_brief.md                       # main session: task scope + user goals
├── 01_pipeline_map.md                # arch-mapper
├── 02_traces.md                      # arch-tracer (real-rawdata evidence — ground truth)
├── 03_coupling_audit.md              # arch-coupling-auditor
├── 04_architecture_proposal.md       # arch-designer (vN on revisions; every claim cites a 02 trace ID)
├── 05_breaker.md                     # arch-breaker (counterexample or held-traces; HELD / BREAKS-ON-<M>)
└── 07_decision.md                    # main session: user DOMAIN sign-off + next steps
```

Agents read other agents' artifacts directly from disk (not via main session relay). Main session only authors `00_brief.md` and `07_decision.md`.

---

## §5 Invariants

1. **No agent edits code** — all output is markdown only. Implementation happens in a separate pass after user approval (different team / direct edit).
2. **No agent does another agent's job** — Mapper doesn't propose; Designer doesn't validate; Critic doesn't redesign. Single responsibility enforced by tool surface in frontmatter.
3. **Wave 1 agents run in parallel** — they don't depend on each other.
4. **Wave 3 agents run in parallel** — they're independent reviewers.
5. **All decisions cite Wave 1 evidence** — Designer cannot propose without grounding in 01/02/03; Critic cannot critique without specific references.
6. **User signs off the DATA-STRESS-TESTED domain model** — the sign-off package includes the hardest real cases traced out (§2A point 2), not a clean summary. (A "user signed a plausible summary" gate is what let the ST-primary model through.)
7. **Every claim anchored to evidence (§0 principle)** — a real-rawdata trace, an objective gate (base_hash / byte-identical), or the user's domain sign-off. Never abstract endorsement. Agents do NOT invent the domain model.
8. **Architecture ↔ user; implementation ↛ user (§2A.1)** — domain / semantic decisions go to the user with traces; implementation detail (names, layout, code) is gated objectively, never user-reviewed.

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
> **Status**: actively used. The impl-* loop ran end-to-end for the 6-phase analyzer plugin unbundle (2026-05-29/30) and caught real regressions a solo pass would have missed. The full process lives in `docs/IMPL_TEAM_PROCESS.md`; this section is the arch-* → impl-* handoff summary.
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

## §10 Liveness check + troubleshooting (added 2026-05-17 after spawn opacity issues)

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

## §11 Memory pointer

For future sessions:
- `memory/feedback_arch_team_process.md` — when to spawn arch-* team for design phase (auto-memory pointer added 2026-05-15; troubleshooting added 2026-05-17)
- `memory/feedback_impl_team_required.md` — when to spawn impl-* team for implementation phase (auto-memory pointer added 2026-05-17)
