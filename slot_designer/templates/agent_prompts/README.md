# Agent prompts — usage guide

> **Purpose**: 6 base prompts that define each agent's permanent identity, tool surface, and invariants. Main session combines these with per-task instructions when spawning agents during new-machine onboarding.
>
> **Why base + per-task split**:
> - **Base** = the agent's permanent role / what it always does / never does. Reusable across all stages.
> - **Per-task** = this run's specific input artifact paths, output artifact path, success criteria, stage number. Highly machine-and-stage-specific; main session writes fresh each time.
> - If we baked per-task into templates, they'd rot fast (artifact paths change per machine, per iter). Base is the durable contract.

## How main session uses these

When spawning an agent in any onboarding stage, the prompt should be **base content + per-task wrapper**, structured like this:

```
[paste full content of base/<AGENT>_base.md here]

---

## This task (Stage <N>, <machine_code>)

**Inputs you should Read first**:
- session_artifacts/<M>/<input_artifact_1>.md
- session_artifacts/<M>/<input_artifact_2>.md
- machines/<M>/<input_file_3>.json
- (any others)

**Your output**:
- Write to: session_artifacts/<M>/<output_artifact>.md
- Format: <markdown / JSON / table / verdict file>
- Must include: <specific sections, derived from ONBOARDING_PROCESS §5.<stage>>

**Success criteria** (you self-check before returning):
- <criterion 1>
- <criterion 2>
- ...

**Stage reference**: slot_designer/ONBOARDING_PROCESS.md §5.<stage>

**Specific notes for this run** (machine-specific context):
- <e.g., "this machine has cherry-anywhere mechanic; pay 1 dominates Low bucket — be aware in your analysis">
- <e.g., "this is iter 2 of mode 5 tune; previous iter critique at empirical_v3_mode5_iter1.md">
```

The base prompt sets the agent's compass; the per-task wrapper points it at the specific task.

## File map

| File | Agent | When used |
|---|---|---|
| `R_base.md` | Researcher | Stage 1d, Stage 3.5 review |
| `A_base.md` | Analyst | Stage 1a/1b/1c, Stage 3.5 feasibility, Stage 6 empirical, Stage 8 |
| `I_base.md` | Implementer | Stage 2, Stage 3 (with A), Stage 3.5 feasibility (with A) |
| `D_base.md` | Designer | Stage 3.5 draft, Stage 4 narrative |
| `V_base.md` | Verifier | Stage 3.5 review, Stage 5 TDD, Stage 6 verify-each-iter, Stage 7 cross-mode |
| `X_base.md` | Critic | Stage 3.5 review, Stage 4 pre-tune review, Stage 6 per-mode review, Stage 8 narrative review, Stage 9 final gate |

## When to add new agent prompts

Don't proliferate. If a new responsibility shows up (e.g., a "Profiler" agent that benchmarks performance), check whether it's truly a new agent identity or a per-task specialization of an existing one. Adding a 7th agent should be a deliberate decision discussed with the user; per-task variants belong in the wrapper, not new base files.

## Cross-references

- `slot_designer/ONBOARDING_PROCESS.md` §4 — agent team roles and tool surface
- `slot_designer/ONBOARDING_PROCESS.md` §4.0 — Stage 3.5 all-team participation
- `slot_designer/WORKFLOW.md` §2.6 — boundary discipline under BOUNDARY_CONTRACT
- `slot_designer/templates/BOUNDARY_CONTRACT_TEMPLATE.md` — what Stage 3.5 produces
