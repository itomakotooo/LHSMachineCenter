# M&lt;XX&gt; — Boundary Contract

> **Purpose**: user-facing contract bounding the deliverable. Once user sign-off, team operates against this contract without further user consultation, except (a) team finds a better design and proposes contract amendment, or (b) team hits structural infeasibility after mechanism exhaustion.
>
> **Authoring**: produced collaboratively by R + A + I + D + V + X in Stage 3.5. Frozen after user sign-off.
>
> **Reading order** (for any agent or future session referencing this file):
> 1. §0 Sign-off status — is the contract frozen?
> 2. §1-4 the 4 layers below
> 3. §5 amendment log (if any) — non-trivial changes after sign-off
>
> **Relation to other docs**:
> - `session_artifacts/<M>/user_brief.md` is the **input** (user qualitative preferences)
> - This file is the **negotiated output** (quantified contract)
> - `verify.py` red lines and `targets/<M>_mode<N>_*.target.json` are **derived** from this contract — they cannot introduce constraints not in this file

---

## §0 Sign-off

- **Status**: [ ] Drafted (Stage 3.5 team proposal) → [ ] User sign-off received → [ ] Frozen
- **Sign-off date**: YYYY-MM-DD
- **Sign-off message / commit**: (link to user message or commit SHA where user said "approved")
- **Frozen at version**: v1 (bump on amendment per §5)

---

## §1 User-stated qualitative direction (verbatim from user_brief)

> Direct quotes from `session_artifacts/<M>/user_brief.md`. No paraphrase, no interpretation. If user said "low volatility on base", quote that — do not translate to a number here. Translation lives in §2.

- (quote 1)
- (quote 2)
- (quote 3)
- ...

---

## §2 Team-translated quantitative bounds (proposed by D, audited by V/X)

> Every line is a **number with units** that the deliverable must satisfy. Each line cites: (a) which §1 direction it operationalizes, (b) which philosophy § / archetype data / paytable math justifies the specific number, (c) feasibility status (verified vs assumed).

### §2.1 Mode 1 (paid baseline) bounds

| dimension | bound | cites §1 | cites philosophy/archetype | feasibility |
|---|---|---|---|---|
| Total RTP | [a, b]% | direction X | mode 1 = 95% baseline (universal §C) | ✓ verified analytic |
| Hit rate (session-centric) | [a, b]% | direction Y | archetype Z, baseline 17% | ✓ verified analytic |
| (more rows) | | | | |

### §2.2 Mode 2 (lucky) bounds

| dimension | bound | cites §1 | cites philosophy/archetype | feasibility |
|---|---|---|---|---|

### §2.3 Mode 5 (super-lucky) bounds

(same structure)

### §2.4 Mode 7 (cut) bounds

(same structure)

### §2.5 Cross-mode invariants

| invariant | bound | rationale |
|---|---|---|
| mode 5 RTP > mode 2 RTP > mode 1 RTP > mode 7 RTP | strict | universal §9 monotonicity |
| mode 7 big-pay marginal = mode 1 (within ±5%) | tolerance | universal §D cut semantic |
| ... | | |

### §2.6 Family / paytable bounds (machine-specific)

| family | share% target | share% band | rationale |
|---|---|---|---|

---

## §3 Physics floor (informational — non-negotiable structural limits)

> Paytable math constraints that bound the search space. Not user-approved (user doesn't sign-off on physics), but team must be transparent: if §2 bounds conflict with §3 physics, §2 must yield.

- (Floor 1: e.g., cherry-anywhere paytable forces cherry1 hit share ≥ X% — can't be lower without changing paytable, which is forbidden per universal rule paytable-immutable)
- (Floor 2: e.g., wild-substitution mechanic forces P(bar2) > P(bar1) in lucky modes regardless of weights — §1 inverse-pyramid carve-out)
- (Floor 3: e.g., strip stop count = 22 limits per-symbol marginal granularity to ~4.5% increments)
- ...

**If §3 floor blocks a §2 bound**: D must annotate the §2 line as `STRUCTURAL`, document mechanism exhaustion (per `feedback_dont_lower_floor_when_blocked.md`), and propose a band that respects the floor + escalate to user (does user accept the floor-respecting band, or change paytable / strip / etc.?).

---

## §4 Informational metrics (dump in final report, not red lines)

> Numbers the team will surface in the final deliverable report for player-experience self-check, but **not** verify.py red lines. User can eyeball these on final review; the team is not bound to a specific number.

- Base : Feature split (e.g., "report shows 46:54, target reference ~45:55 archetype")
- CV / volatility profile
- Per-mode bucket shape narrative dump (Low / Mid / High / Top RTP+rate)
- Per-reel symbol density visual rhythm dump
- Top symbol any-reel PWDF visibility per mode
- (more — anything where user said "感性" or "informational")

**Difference from §2**: §4 metrics are *dumped*, not *bounded*. If user said "low volatility on base" without a number → §4 (CV dumped + reasonableness checked vs archetype reference, but no numeric RED line).

---

## §5 Amendment log (post sign-off only)

> Any change to §1-§4 after user sign-off requires a new entry here with reason + new user sign-off. Empty if contract held through ship.

| date | version | what changed | reason | user re-sign-off |
|---|---|---|---|---|

---

## §6 Feasibility pre-check (Stage 3.5 deliverable, archived)

> Brief evidence that the §2 bounds are mathematically feasible against §3 physics. Produced by A + I + V in Stage 3.5. Frozen with contract.

- **Method**: (e.g., analytic_profile() on bootstrap weights with §2 lower-bound targets, then nudge towards upper-bound — feasibility = a non-empty solution region exists)
- **Result**: ✓ all §2 bounds have non-empty feasibility region under §3 physics. OR ⚠ some bounds tight — listed below.
- **Tight bounds** (low feasibility margin, flag for tune-time attention):
  - (bound X has margin < Y) ...
- **Infeasible proposals dropped before sign-off**:
  - (original D proposal: ...; A/I/V verdict: infeasible because ...; revised proposal: ...)

---

## §7 Agent operating rules (under sign-off contract)

> Reminder for all agents in Stage 4+ when reading this file:

1. **No new boundary** — Agent must not introduce a number (band / floor / cap) not in §2 or §3. If a number is needed for a verify red line or tune cost weight, it must trace back to §2 or §3. If §2 doesn't bound it but §4 dumps it → no red line, just dump.
2. **No silent widening** — Agent must not relax / widen / soften a §2 bound to make verify pass. If iter keeps failing, escalate to user per §7.4.
3. **No silent override** — Agent must not write `verify.py` carve-outs / per-mode exception bands without amending §2 first.
4. **Two escalation triggers** (only):
   - **Better idea**: Agent / team discovers a design choice that would improve user experience but requires contract amendment → propose to user with explicit "before / after" comparison.
   - **Structurally infeasible**: After exhausting all mechanism options (per `feedback_dont_lower_floor_when_blocked.md` — try mult / redistribute / restructure / architecture upgrade), the contract bound is unreachable → escalate to user with mechanism-exhaustion evidence + proposed alternative (different bound vs accepted deviation).
5. **Process-internal numbers** (tune step size, SA temperature, candidate enumeration counts, etc.) are not boundary values — agents pick freely.

---

## §8 References

- `session_artifacts/<M>/user_brief.md` — §1 source
- `session_artifacts/<M>/01b_baseline_report.md` — A baseline that anchored §2 numbers
- `session_artifacts/<M>/01d_research.md` — R archetype data that anchored §2 numbers
- `session_artifacts/<M>/01c_field_analysis.md` — A mechanism inference that informs §3 physics
- `slot_designer/DESIGN_PHILOSOPHY.md` — universal direction that justifies §2 bounds (per §9 truth-order in ONBOARDING_PROCESS.md)
- `slot_designer/ONBOARDING_PROCESS.md` §3.5 — process producing this contract
- `slot_designer/WORKFLOW.md` §2.6 — agent boundary discipline under this contract
