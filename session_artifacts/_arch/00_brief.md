# Architecture Review Brief — rawdata → analyzer → console pipeline

> **Inaugural use of `arch-*` 6-agent team** (per `docs/ARCH_TEAM_PROCESS.md`). All 6 agents read this brief as the spec contract before producing 01-06 artifacts.
>
> **Date**: 2026-05-15
> **Trigger**: 2026-05-14/15 M31 onboarding session — 6 fleet-shared commits made for single-machine UX needs, fleet impact never audited, user repeatedly pushed back. Pattern documented in `memory/feedback_arch_team_process.md`.

---

## §1 Task

Review the **real-machine console pipeline** end-to-end and propose a refactor that:
- **Reduces blast radius** of touching fleet-shared code (currently any analyzer change cascades to all 393 machines' reports)
- **Exploits cluster similarity** across machines (per-archetype shared logic) without losing per-machine uniqueness
- **Supports cheap onboarding** of future machines (drop spec/weights/plugin; minimal cross-cutting changes)
- **Eliminates duplication** between production console (port 8877) and virtual/dev console (port 8878)

Output: a concrete proposal user approves before implementation begins. **No code changes during this review** — markdown only.

---

## §2 Scope

### In scope

- `rawdata/<M>/mode_<N>/` — upstream chunk format + envelope
- `fresh_slotlab/` — production analyzer + sampling + round classification + round-win rules
- `reports/<M>/mode_<N>/versions/*/player_impact_summary.json` + `player_impact_report.md` — output reports
- `src/web_console/backend/` — FastAPI routes, run management, report serving
- `src/web_console/frontend/` — JS rendering + i18n + DOM dispatch
- `slot_designer/core/version.py` — `compute_code_md5(machine_name)` hash composition
- `slot_designer/configs/machines_virtual.json` — virtual registry + md5 fanout

### Audit-only (check, do not redesign primary path here)

- `slot_designer/core/backend/` (virtual console) — verify it is a **thin shell** delegating to fresh_slotlab; flag any independent parsing/display logic as duplication-to-eliminate
- `slot_designer/core/devtools/` — verify they consume fresh_slotlab outputs, not parallel implementations

### Out of scope

- `slot_designer/machines/<M>/` — per-machine spec / weights / plugin code (handled by slot-* team for individual machine onboarding)
- `MachineBuilder/` — upstream xlsx-based build pipeline
- `session_artifacts/<M>/` — per-machine research / inference notes
- New machine onboarding workflow (`slot_designer/ONBOARDING_PROCESS.md`) — this team designs the framework; the slot-* team uses it
- UI / visual design choices in console (color, layout) — focus on the data/logic architecture, not aesthetics

---

## §3 Current state of fleet-shared code (post-M31 session)

The following commits in this session touched fleet-shared code. Designer should treat these as the **current baseline** to start migration from (user decision: not reverting):

| Commit | File(s) | Change | Notes for Designer |
|---|---|---|---|
| `54b7d01` | `slot_designer/core/engine/{symbol,evaluator,spin,feature_protocol}.py` | Added native `'scatter'` symbol kind + scrubbed `M15` tokens from core comments | Core API surface change |
| `729a6ca` | `fresh_slotlab/player_impact_analyzer.py` + `tests/backend/test_analyzer_st_split.py` | Added `payouts_by_spin_type` + `reel_marginal_by_spin_type` to summary JSON | New fields appended (not breaking); machine-agnostic via `ST{N}_{behavior}` label |
| `8411c9d` | `fresh_slotlab/player_impact_analyzer.py` + `src/web_console/frontend/{app.js,pure.js}` | Renamed payouts_by_spin_type row fields to match aggregate (`hit_rate`, `rtp_contribution_pp`); extracted shared `_renderPayoutRowsHtml` + `_renderReelColumnHtml` frontend helpers | Schema alignment + render-side dedup |
| `7e5fe32` | `src/web_console/frontend/app.js` | Schema fallback (`hit_rate ?? hit_rate_pct/100`, `rtp_contribution_pp ?? rtp_pp`) for pre/post-rename reports | Backward-compat for old reports on disk |
| `0f981b9` | `src/web_console/frontend/app.js` | Derive `spin_type_category` from parent label so split row '类型' badge matches aggregate | Frontend-only; covers analyzer-side schema gap |
| `4cbcab2` | `fresh_slotlab/player_impact_analyzer.py` + `tests/backend/test_analyzer_st_split.py` | Filter changed from `st_win == 0.0` to `st_hits == 0` (retain 0-win-but-fired pids like M31 pid 666) | Logic correctness fix; fleet-wide impact unaudited |
| `284fd19` | (revert of `5c4a111`) | Reverted strict-binary spin_type_category change (kept 80% threshold) | Threshold semantic remains current |

**Caveat**: every commit above was verified only on M31. Other machines' behavior under these changes is **unaudited**. Coupling auditor + validator should flag any of these as risk vectors.

---

## §4 User goals (verbatim)

> "添加新机台,有一些新 feature,更新分析器,会不会导致我所有的 report 失效?但有没有失效必要?" — Adding a new machine with new features should NOT unnecessarily invalidate all 393 machines' reports.

> "理解目前的 rawdata-分析器-网页 console 展示的框架,以现有机台数据了解大致机台之间的相关性程度,合理设计和重构,做到利用相关性,支持独特性。为以后持续添加机台做准备。"

> "虚拟 console 按理不应该有独立的解析和展示逻辑,从框架设计来讲完全应该公用真机 console 的这部分内容。"

> "你为了 m31 就胡乱改了全局代码？先不说你改的对不对吧，就一点不考虑健壮性？" — Process critique: shared-code changes need fleet-wide audit before landing.

---

## §5 Constraints (must hold during + after migration)

1. **Backward-compat for existing 393 machines' reports**: in-flight reports must continue to be served + displayed correctly throughout migration. Forced regen of all reports = unacceptable.
2. **Production console (port 8877) must not break**: every commit during migration keeps prod fully operational.
3. **Virtual console (port 8878) reuses production code**: by end-state, virtual is a thin shell with no independent parse/display logic.
4. **Adding a new machine should affect O(1) hashes, not O(N=393)**: new feature plugin should invalidate only machines declaring use of that plugin, not the whole fleet.
5. **Rollback path for every migration phase**: each phase has a clean revert plan if it breaks something downstream.
6. **No silent data loss**: any field rename / structural change preserves the underlying data; old reports remain interpretable (via fallback rules or migration script).

---

## §6 Goals (success criteria for the proposal)

A successful Wave 2 proposal:

- **Quantifies blast radius reduction**: "currently changing X invalidates 393 reports; under proposal, changes 1 plugin invalidates K reports where K ≤ ..."
- **Defines a Plugin Protocol** (interface sketch) for analyzer features + frontend renderers, with example skeleton
- **Specifies hash composition algorithm** with worked example: "machine M's hash = base_hash + sorted(plugin_hashes_M_uses); adding feature F as plugin → invalidates only machines listing F"
- **Defines manifest format**: per-machine declaration of which features/plugins it uses (file format, validation rules)
- **Migration plan**: phase 1 / phase 2 / phase 3 with concrete deliverables + rollback per phase
- **Handles outliers**: M99 / M260 / M268 / M274 / M279 etc. (outliers identified in Wave 1 by taxonomist) cleanly under the new architecture
- **Resolves prod/virtual duplication**: if any duplication exists, propose a consolidation path

---

## §7 Non-goals (explicitly out of this proposal's scope)

- **Implementing the proposal**: this team produces design only. Implementation = next session, different team or direct.
- **Aesthetic / UX redesign**: focus on data/logic architecture.
- **Re-onboarding existing machines**: assume existing per-machine spec/weights/plugins keep working with shims as needed.
- **Performance optimization unrelated to architecture**: blast-radius reduction is in scope; sampling speed-ups are not.
- **Upstream rawdata format changes**: the chunk envelope + roundResult schema is treated as immutable contract.
- **The 80% spin_type_category threshold question**: explicitly deferred — not within this team's scope to decide (`5c4a111` was reverted via `284fd19` and that semantic stays for now).

---

## §8 Data availability note

- **rawdata coverage**: user has rawdata for **a subset** of 393 machines, not all. Taxonomist should sample what's available rather than assume full fleet coverage.
- **report coverage**: most machines have at least one historical dev report under `reports/<M>/mode_<N>/versions/*/`. Coupling auditor should use these as ground-truth for "what fields the frontend currently consumes".
- **machines.json**: full 393-machine registry available at `configs/machines.json` — use this for fleet inventory.
- **machine xlsx specs**: under `MachineBuilder/Buffalo/Assets/Config/Excel/Machine/<M>/` — coverage incomplete, sample-based analysis acceptable.

---

## §9 Decisions baked into this brief

(User authorized "全权由你负责" — these are coordinator-level default decisions for the team's operating mode.)

- **Scope**: §2 above
- **Existing commits**: KEEP all 7 fleet-shared commits as current baseline; designer's migration plan walks forward from here, not from before
- **Concurrency**: Wave 1 (3 agents) parallel; Wave 3 (2 agents) parallel
- **Iteration policy**: if Wave 3 verdict = REJECT or APPROVE-WITH-MAJOR-REVISIONS, coordinator loops back to Wave 2 (designer v2); minor revisions handled in main-session-authored `07_decision.md`
- **Implementation handoff**: after `07_decision.md` user approval, implementation is OUT of this team's scope — next session uses slot-implementer / general-purpose agents

---

## §10 Cross-references

- Process spec: `docs/ARCH_TEAM_PROCESS.md`
- Agent definitions: `.claude/agents/arch-{mapper,taxonomist,coupling-auditor,designer,critic,validator}.md`
- Memory pointer: `memory/feedback_arch_team_process.md`
- Sibling team (slot machine onboarding): `slot_designer/ONBOARDING_PROCESS.md`
- Recent failure-mode evidence: M31 session in `session_artifacts/M31/` (12+ commits, many fleet-wide unaudited)
