# M43 — Session Brief (onboarding kickoff)

> Reading order for any agent on this session: this file → `user_brief.md` → `slot_designer/ONBOARDING_PROCESS.md`.

## Machine identity

- **Internal code**: M43
- **Upstream machine name** (per `configs/machines.json`): `M43`
- **Archetype hint** (user-supplied): **Lucky Ducky** — IGT classic, 3-reel known machine
- **Mechanics** (from `configs/machines.json` logicClassNames): base spin + win-respin + wild substitution + win mini-game generator (feature mechanism details to be reverse-engineered in Stage 1c)

## Scope — mode 1 first (new universal workflow)

**This session ships mode 1 only.** Mode 7 / 2 / 5 are not in scope until mode 1 is shipped on `collab/dev`. Stage 7-10 (cross-mode + full-fleet empirical + commit) are deferred until subsequent sessions derive 7/2/5 per universal §C/§D rules.

User direction (2026-05-13): "以后所有机台都这么做" — sequential mode roll-out, mode 1 as standalone shippable milestone. This direction will be backported to `slot_designer/ONBOARDING_PROCESS.md` as a universal workflow change in parallel with this onboarding.

## Inputs already available

- **Production rawdata** at `rawdata/M43/mode_1/` — 42 chunks (mode 2/5/7 have 2-4 chunks; out of scope this session)
- **Production registry entry** in `configs/machines.json` — provides `logicClassNames` for mechanism reverse-engineering anchor
- **No prior `slot_designer/machines/M43/` files** — this is a fresh onboarding
- **No production paytable doc** provided by user — Stage 1c will reverse-engineer from rawdata

## What's "稀烂" (user's word for current production state)

User direction (2026-05-13):
- Bucket distribution looks bad from a multiplier-bucket standpoint
- High-multiplier bucket share too thin
- Distribution shape "needs to be more reasonable"
- Will be quantified in Stage 1b §2 (bucket distribution) and §3 (per pay_id breakdown); contract §2 will translate into bounds in Stage 3.5

## Hard inputs

- **Total RTP mode 1**: 95% ± 1pp (95% ± 1)
- **Bucket distribution**: high-multiplier buckets need more share; current shape unreasonable (qualitative, will quantify post-baseline)
- All other constraints: not yet specified — will be elicited at Stage 3.5 boundary contract drafting

## Stage 0 deliverables completed

- [x] `machines/M43/` directory skeleton (spec / strips / weights/mode_<N>/ folders empty)
- [x] `session_artifacts/M43/` directory + this SESSION_BRIEF + user_brief.md
- [x] Mode 1 rawdata location confirmed (`rawdata/M43/mode_1/`)

## Spawned agents (Stage 1, this session)

- **A** — Stage 1a (data inventory) + Stage 1b (12-section baseline, mode 1 only) + Stage 1c (mechanism inference from rawdata + logicClassNames cross-check)
- **R** — Stage 1d (Lucky Ducky archetype WebSearch + industry data)

Outputs land at:
- `session_artifacts/M43/01a_data_inventory.md`
- `session_artifacts/M43/01b_baseline_report.md` (mode 1 only this session)
- `session_artifacts/M43/01c_field_analysis.md`
- `session_artifacts/M43/01d_research.md`

After Stage 1 outputs land, main session evaluates and decides Stage 2 engine implementation + Stage 3 bootstrap + Stage 3.5 boundary contract launch.

## Stop conditions (this session)

- ✗ Stage 1c mechanism inference fails to reproduce production rawdata byte alignment → escalate user (paytable doc may be needed)
- ✗ Stage 3.5 feasibility pre-check finds mode 1 RTP 95% ± 1 + "high-bucket more share" infeasible against M43 paytable → escalate user with mechanism-exhaustion evidence + options
- ✗ Stage 6 mode 1 tune iter > 5 still RED on same category → escalate user

## Cross-references

- `slot_designer/ONBOARDING_PROCESS.md` — 11-stage flow + this session follows mode-1-first universal amendment
- `slot_designer/templates/BOUNDARY_CONTRACT_TEMPLATE.md` — Stage 3.5 output template
- `.claude/agents/slot-{researcher, analyst, implementer, designer, verifier, critic}.md` — Claude Code custom subagents with harness-enforced tool whitelists (replaces the deprecated `slot_designer/templates/agent_prompts/` assembly-template approach as of commit cleanup)
