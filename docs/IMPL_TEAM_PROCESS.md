# impl-* Team Process — cross-cutting refactor implementation

> **Purpose**: when arch-* has finished its 3-wave design pass and the codebase is ready for change, this 4-agent team translates the approved architecture proposal into shipped code, one ticket at a time, with parallel critic + validator pressure. Designed to prevent the failure mode "implementer designs their own diff + writes their own tests → no adversarial pressure → 5/10 regressions per memory `feedback_impl_team_required.md`".
>
> **Status**: actively used. Most recently it ran the full 6-phase analyzer plugin unbundle (2026-05-29/30 — carving `bonus_chain_dynamics`, `collect_mechanic`, `upstream_feature_breakdown`, `multiplier_profile`, `reel_marginal_by_spin_type`, `bankruptcy_simulation` out of the monolith into byte-identical plugins), where the critic/verifier loop caught regressions a solo pass would have missed. Per-phase artifacts are under `session_artifacts/_impl/phase_extract_*/` (audit trail, not living docs).
>
> **Not for**: single-file fixes with no fan-out, docs-only changes, per-machine `slot_designer/machines/<M>/` edits. Use direct edit (single file) or slot-* team (per-machine) for those.

---

## §1 When to use this team

Trigger this team when **all** of the following apply:

- arch-* team has shipped `04_architecture_proposal_v*.md` + `07_decision_v*.md` + `08_handoff.md` — design phase complete
- Change touches `fresh_slotlab/`, `slot_designer/core/`, `src/web_console/backend/`, or `src/web_console/frontend/` (fleet-shared code)
- Change is broken into discrete tickets (one ticket = one logical edit; tickets are sized so one impl-implementer + impl-tester cycle = 1-3 hours of work)

Do NOT trigger for:

- Pre-design changes (run arch-* first)
- Single-file bug fix isolated to one module (direct edit — implementer's eyes + main session pytest suffices)
- Docs / spec-only changes
- Per-machine `slot_designer/machines/<M>/` content (slot-* team)

---

## §2 Team composition (4 agents, 2 waves)

| Agent | `subagent_type` | Wave | Responsibility | Output |
|---|---|---|---|---|
| Implementer | `impl-implementer` | 1 | Translate ticket → code change; minimal-delta diff | `02_implementation.md` + repo edits |
| Tester | `impl-tester` | 1 | Translate ticket → regression tests; inject-bug TDD | `03_tests.md` + tests/* files |
| Verifier | `impl-verifier` | 2 | End-to-end empirical verification against real fixtures | `04_verification.md` |
| Critic | `impl-critic` | 2 | Adversarial review of full chain; commit-msg Self-critique | `05_critique.md` |

Tools per agent are enforced via frontmatter `tools:` whitelist in `.claude/agents/impl-*.md`. Implementer + Tester can Edit/Write code; Verifier is read-only on prod code (Bash only); Critic is read-only (Write to critique markdown only).

---

## §3 Wave structure

### Wave 1 — Build (parallel)

Spawn `impl-implementer` and `impl-tester` in **parallel** (background). Each reads `00_ticket.md` and works independently — implementer translates ticket to code, tester translates ticket to assertions. Independent paths surface ticket-spec ambiguity.

Inputs to each: ticket brief + relevant arch-* artifacts (`04_v5.md`, `07_decision_v5.md`).

When both complete → Wave 2 starts. If implementer is blocked (e.g., needs arch-* clarification) → escalate to main session before Wave 2.

### Wave 2 — Review (parallel)

Spawn `impl-verifier` and `impl-critic` in **parallel**. Both read full chain (`00_ticket.md`, implementer's diff + `02_implementation.md`, tester's tests + `03_tests.md`). Verifier runs the actually-built thing end-to-end + reports PASS/FAIL; Critic adversarially reviews + reports APPROVE / APPROVE-WITH-REVISIONS / REJECT.

### Consolidation (main session, coordinator)

Main session reads `04_verification.md` + `05_critique.md` → decides:

- **Verifier PASS + Critic APPROVE** → ticket merges with critic's drafted `## Self-critique` section in commit message
- **Verifier FAIL** → ticket goes back to W1 with verifier's failure report attached (implementer fixes, tester adjusts if test was wrong, re-run W2)
- **Critic APPROVE-WITH-REVISIONS** → ticket goes back to W1 with critic's required revisions attached (implementer + tester address, re-run W2)
- **Critic REJECT** → ticket may need arch-* re-review per `docs/ARCH_TEAM_PROCESS.md`; main session decides

Main session does **NOT** override critic / verifier verdicts unilaterally. If user wants to ship despite a verdict, user must explicitly authorize.

---

## §4 Information flow

All artifacts under `session_artifacts/_impl/<phase>/<ticket>/`:

```
session_artifacts/_impl/
├── phase1/
│   ├── 01_dedup_md5_lookup/
│   │   ├── 00_ticket.md            # main session writes: contract + arch refs
│   │   ├── 02_implementation.md    # impl-implementer
│   │   ├── 03_tests.md             # impl-tester
│   │   ├── 04_verification.md      # impl-verifier
│   │   ├── 05_critique.md          # impl-critic
│   │   └── 06_resolution.md        # main session writes: ship / revise / reject
│   ├── 02_dedup_summary_patcher/
│   │   └── ...
│   └── ...
├── phase2/
│   └── ...
└── ...
```

Agents read other agents' artifacts directly from disk. Main session only authors `00_ticket.md` and `06_resolution.md` per ticket.

`02` and `03` are the numbering convention because `00` is the ticket brief; `01` is reserved for any per-ticket discovery notes the main session writes before W1. Verifier + Critic are `04` and `05` per the Wave 2 parallel structure.

---

## §5 Invariants

1. **W1 agents work from the BRIEF, not from each other's output** — implementer doesn't read tester's tests; tester doesn't read implementer's diff. They both read `00_ticket.md`. Independent paths surface brief ambiguity.
2. **W2 agents read the full W1 chain** — verifier and critic need brief + diff + tests + notes.
3. **Verifier is read-only on prod code** — runs pytest / subprocess / preview, reports observed; does not Edit. Same for Critic.
4. **Implementer cannot write tests; Tester cannot edit prod code** — clean separation. If implementer needs an internal helper visible to test it, that's a test-shaped change to prod code (acceptable, tester flags it; impl re-runs).
5. **Inject-bug TDD on every regression test** — per memory `feedback_integration_test_argv.md`: every new regression test proven by injecting the bug it claims to catch. Tester documents the inject step in `03_tests.md`.
6. **Subprocess-mode verification when subprocess-mode change** — per memory `feedback_perf_claim_needs_e2e_event_stream.md`: verifier spawns real subprocess against real fixture, not just pytest.
7. **Per-ticket rollback path** — every ticket merges as a self-contained commit; revertable in isolation; no bundled drive-bys.
8. **Commit message MUST include `## Self-critique` section** — critic drafts it; main session pastes verbatim (or with explicit additions). Per memory `feedback_adversarial_self_review.md`.

---

## §6 How to invoke

### Coordinator (main session) kickoff for one ticket

1. Write `session_artifacts/_impl/<phase>/<ticket>/00_ticket.md` with:
   - **Ticket scope**: what is the one change? (one paragraph, plus a bullet list of files expected to change)
   - **Brief sections cited**: which `04_v5 §X.Y` + `07_decision_v5 PN` this ticket implements
   - **Contract**: the explicit invariants the change must satisfy (one to five bullets, each testable)
   - **Out of scope**: what NOT to change in this ticket
   - **Rollback path**: how to revert this commit cleanly if it breaks
2. Spawn W1: `impl-implementer` + `impl-tester` in parallel (background). Brief each with path to `00_ticket.md`.
3. Wait for both notifications. If implementer escalates → resolve, restart W1 if needed.
4. Spawn W2: `impl-verifier` + `impl-critic` in parallel. Brief each with path to `00_ticket.md` + paths to W1 outputs.
5. Wait for both notifications.
6. Read `04_verification.md` + `05_critique.md`. Write `06_resolution.md`:
   - Ship / revise / reject decision
   - If ship: commit with `## Self-critique` from critic
   - If revise: re-run W1 with addendum brief; loop W2 until clean
   - If reject: escalate to arch-* re-review or to user

### Phase kickoff (multiple tickets)

1. Read `08_handoff.md §4` for the phase's deliverables
2. Break phase into discrete tickets (one logical edit each, 1-3 hours per ticket)
3. Write all `00_ticket.md` files up front
4. Run tickets serially OR in parallel (depending on whether they share files). Default: serial within a phase, parallel across phases only when handoff allows it.
5. Each phase ends with a phase-level summary commit + entry in `session_artifacts/_impl/<phase>/PHASE_SUMMARY.md`

### Reuse for future tasks

When user starts a new cross-cutting implementation pass:
- Create a new `session_artifacts/_impl_<topic>/` directory if not under the arch-* topic
- Re-spawn the 4 agents with paths pointing to the new directory
- The agent definitions in `.claude/agents/impl-*.md` are stable and reusable; only the briefs change per ticket

---

## §7 Anti-patterns (don't do these)

- **Implementer writing the tests** — defeats the parallel-paths discipline. Tester must read the brief independently.
- **Tester editing prod code** — if a test needs a code reshape, tester flags it; implementer reshapes. No backdoor edits.
- **Verifier writing code** — same. Read-only.
- **Critic suggesting fixes inline** — critic flags; implementer iterates. (Exception: a tiny one-line obviously-correct suggestion is OK as a comment, but no Edit.)
- **Skipping the inject-bug step** — `feedback_integration_test_argv.md`: untested-by-injection tests don't guard regression. Tester MUST verify each new test goes red on inject.
- **Skipping subprocess verification when change touches subprocess code** — `feedback_perf_claim_needs_e2e_event_stream.md`. Pytest-only is not verification for subprocess-mode bugs.
- **Main session deciding to ship despite Critic REJECT** — without explicit user authorization. Critic verdicts have teeth; the team exists because solo implementation regresses 50% of the time per memory.
- **Bundling multiple tickets in one commit** — defeats per-ticket rollback. One commit = one ticket.
- **Test floor relaxation** — `feedback_adversarial_self_review.md`: moving goalposts is a critic-flag offense.

---

## §8 Relation to other team processes

| Pattern | When | Where defined |
|---|---|---|
| arch-* team | Design pass before implementation; touches fleet-shared code | `docs/ARCH_TEAM_PROCESS.md` |
| **impl-* team (this doc)** | **Implementation pass after arch-* approval; touches fleet-shared code** | **`docs/IMPL_TEAM_PROCESS.md` (this file)** |
| slot-* team | Per-machine onboarding (rawdata → spec → weights → verify) | `slot_designer/ONBOARDING_PROCESS.md` |
| Direct edit | Single-file fix, no fan-out, no design implication | n/a — main session |

Sequence: arch-* → impl-* → slot-*. arch-* sets the framework; impl-* implements the framework; slot-* uses the framework for per-machine work. If impl-* surfaces a structural issue not covered by arch-* design → loop back to arch-* for a re-review (per `docs/ARCH_TEAM_PROCESS.md §3 Consolidation`).

---

## §9 Liveness check + troubleshooting

Per memory `feedback_arch_team_process.md §9` (the arch-* team's troubleshooting), the same Agent-tool harness limits apply here:

- **Spawn response**: returns agentId. If Bash exit code = 0 + "Async agent launched successfully" → harness accepted.
- **`.output` file stays 0 bytes during run**. Normal. Do NOT Read it (overflows context).
- **`TaskOutput block: false`** returns `running` | `completed` | `killed` | `error` | `not_found`. Use this to check liveness, not stdout polling.
- **Task notification pushes on completion**. Wait for it.

### Baseline (run smoke tests after harness restart or agent-def edit)

```
For each impl-* agent type: spawn with trivial task (Bash echo + write single-line file to
session_artifacts/_impl/_team_test/test_<role>.md or similar). Expect 6-15 seconds.
If spawn fails "Agent type not found" → restart Claude Code session.
If spawn succeeds but task never notifies → respawn once before deeper diagnosis.
```

Expected baselines (rough): implementer 8-15 min per ticket / tester 6-12 min / verifier 5-10 min (longer if running preview) / critic 4-8 min.

### Failure modes to watch for

(Mostly inherited from arch-* §9 — same harness, same issues.)

1. Spawn returns agentId but agent silently dies → TaskOutput later returns `not_found`. Recovery: respawn.
2. Coordinator panic-killing a live agent based on "0 bytes output" → never do this; output is written at completion only.
3. Spawn → immediate `not_found` → harness in cleanup-pending state; wait 30+ sec, respawn.

---

## §10 Memory pointer

Searchable via `memory/feedback_impl_team_required.md` (auto-memory created 2026-05-17; reasons + scope). Update that memory when team scope or process changes materially.
