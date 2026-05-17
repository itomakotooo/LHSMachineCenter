# Architecture Proposal v5 — rawdata → analyzer → console pipeline (Wave 2 v5 iteration)

> Wave 2 v5 deliverable from `arch-designer` (running on general-purpose harness; self-constrained to designer role). **Focused 7-issue revision of v4**, NOT a full rewrite. Reuses 80%+ of v4 verbatim.
>
> Changes vs v4 (the seven issues from addendum v5 §1):
>
> - **§9.4 Layer 4 — trigger-session false-positive structural fix** (Issue ①, CRITICAL): v4's Step B naively counts rawdata `R.SpinType` per round, but `compute_trigger_sessions` re-attributes free-spin wins to the triggering paid-spin session bucket in `payout_id_by_spin_type_total`. This means `analyzer_dispatch[pid][st]` (post-attribution) systematically diverges from `fresh_dispatch[pid][st]` (pre-attribution) for all machines with `trigger_session_pattern != null`. v5 picks **approach (b) — Skip approach**: machines with `trigger_session_pattern != null` in their manifest get `layer4_applicable: false` (skip Layer 4 entirely for those machines). Trade-off documented explicitly. §9.4 Step B + Step C updated.
>
> - **§6.3.3 Day-1 verification deliverable as item 0** (Issue ②): adds a numbered gating deliverable: "Run `rtp_integrity.py --machine M --mode N` against each Day-1 candidate; verify all 4 layers PASS before flipping to `complete: true`." Failed candidates → "Day-2 pending QA" subsection. Cost ~10 min total. This closes the Critic v4 Concern B / Q6 procedural gap.
>
> - **§5.5.7 override metadata + quarterly QA + lint rule** (Issue ③): when `console_diagnostic_complete_override: false` is set on a variant, manifest MUST also record `override_set_at`, `override_set_reason`, `override_set_by`. Quarterly QA review process. Lint rule: underlying `true` AND override set BEFORE last underlying flip → warning. This closes the Critic v4 Concern C / Validator v4 Scenario 4 spec gap.
>
> - **§9.4 perf estimate for Layer 4** (Issue ④): documents per-machine ~3s, full fleet pull ~20 min total, with rationale. Or "measure during implementation pass" option noted.
>
> - **§9.4 RoundWinRules constraint** (Issue ⑤): explicit 2-line constraint: "RoundWinRules MUST NOT write to `payout_id_by_spin_type_total` directly."
>
> - **§5.5.7 override-clearing procedure** (Issue ⑥): covered by Issue ③ above (override metadata makes the clearing criteria and audit log explicit).
>
> - **§9.4 Step C `_unattributed_*` note** (Issue ⑦): "If Step C mismatch involves a pid in `_unattributed_*` bucket, this corroborates Layer 2's existing fail rather than being a false-positive Layer 4. Implementers MUST NOT suppress these Step C mismatches."
>
> Unchanged from v4 (validated by Wave 3 v4 reviews):
> - §1 + §9.1 operator-diagnostic framing
> - Layers 1, 2, 3 of integrity check (§9.2)
> - `console_diagnostic_complete` mechanism core (§5.5.3)
> - §5.5.4 variant analyzer_features eager cascade
> - Phase 2 builds gate code; Phase 5 flips policy (§6.2, §6.5)
> - Hash composition algorithm (§4)
> - 6-phase migration framework (§6)
> - Plugin Protocol (§5.2), manifest schema baseline (§5.5.1–§5.5.2)
> - All v4 §8.1–§8.13 out-of-scope items (§8)
> - §5.5.7 variant cascade core (eager cascade with true→false-only override — only the metadata requirements and lint rule are added)
>
> **Date**: 2026-05-17
> **Brief**: `00_brief.md` + `00_brief_v2_addendum.md` + `00_brief_v3_addendum.md` + `00_brief_v4_addendum.md` + `00_brief_v5_addendum.md`
> **v4**: `04_architecture_proposal_v4.md` (1243 lines)
> **v4 reviews**: `05_critique_v4.md` (APPROVE-WITH-REVISIONS; 4 concerns A/B/C/D) + `06_validation_v4.md` (APPROVE-WITH-REVISIONS; 3 documentation gaps §3.1/§3.2/§3.3)
> **Repo root**: `User_Managerment_GPT/`

---

## §1 Problem statement (unchanged from v4 — operator-diagnostic framing)

### §1.1 The operator-diagnostic premise

The production console exists to serve a single, specific person: the **operator (策划)** who configures slot machines for the production fleet. The operator picks paytable values, weights, feature parameters, and RTP targets, then ships the resulting configuration to production. The machine code itself is **not** the source of error — production machines faithfully execute whatever the operator configured. The **rawdata** captured from production reflects exactly what the configuration produced, which **may be off-target if the operator misconfigured something** (a typo in a weight, wrong RTP target, mismatched paytable rows, etc.).

User's exact framing (from addendum v3 §1, verbatim):

> "console 的诉求是帮我分析真机数据,找到问题并优化,所以 console 必须要是正确的,真机数据是有可能存在错误的。包括刚刚我说的 rtp 报错,也是 console 认为分析不出机器的 rtp 报错。"

> "rawdata 错的意思不是机台的逻辑和数据错误,就是比如策划 rtp 配错了,手滑了,之类的。"

The console's job is **not** to certify the machine produced "correct" RTP in some absolute sense. The operator owns the configuration. The console's job is to **analyze the rawdata correctly so it can tell the operator whether the configuration produced the intended result**. When the operator looks at a console report and sees RTP, payout distribution, hit rates, or per-SpinType attribution, those numbers must be the actual analysis of rawdata — not a synthesized estimate, not a silent fallback, not a "we couldn't tell so we made one up".

This is the load-bearing inversion vs v2's framing:

| Aspect | v2 (incorrect) | v3/v4/v5 (corrected per addendum) |
|---|---|---|
| What "RTP error" means | Internal analyzer bug | Console claims it cannot reliably analyze this machine right now |
| What console is | An internal correctness checker | A diagnostic tool for the operator |
| What "correctness" means | RTP statistically matches a target | Console's logic accurately reflects rawdata into the report |
| What happens when console can't analyze | Silent fallback to a synthesized number (today's `_unattributed_st<N>`) | Explicit per-machine error with actionable diagnosis hints |
| Who owns "machine RTP is wrong" | Console (which would auto-fix or warn) | **Operator** (who debugs their own configuration) |

The architecture's purpose, rewritten per this framing:

> **The architecture must deliver per-machine, accurate-or-explicitly-error diagnostic signals to the operator across 421+ machines, while supporting cheap addition of new machines / new features without invalidating unrelated reports.**

The data chain:

```
[Operator]                          [Production machine]                  [Console]
  configures                          executes configuration                analyzes rawdata
  paytable + weights        ───►      faithfully               ───►        produces report
  + RTP target                        emits rawdata
                                                                           Either:
                                                                           (a) correct numbers → operator validates / debugs
                                                                           (b) explicit per-machine error → operator investigates
                                                                              (cause: operator misconfig OR console rule gap OR data corruption)
```

`console correct ∧ machine configured correctly → RTP signal trustworthy.` The console must be correct so its signals are trustworthy.

### §1.2 Five concrete pain points (each cited from Wave 1)

1. **Universal `analyzer_version` stamp invalidates 1007 (machine, mode) pairs on any byte change** —
   `compute_analyzer_version()` at `fresh_slotlab/player_impact_analyzer.py:2141` SHA256s the entire 8,176-line file. Per `03 §3.3` live DB measurement, 2030 completed runs across 1007 distinct (machine, mode) pairs get flagged `stale_analyzer` by `/api/reports/stale-count` on any comment-only edit. **v5 fix**: per-machine `effective_analyzer_version` composed from base hash + feature hashes the machine declares (§4).

2. **Schema renames silently break 17 frontend renderers** — `03 §4.3` tabulates ~30 schema fields × 17 renderers. **v5 fix**: explicit `SCHEMA_VERSION` per feature + frontend renderer registry with declared fallback rules (§5.3 + §5.4).

3. **Real-fleet hash is upstream, virtual hash is local** — `03 §3.4` measured 421 entries in `configs/machines.json` get `codeSummaryMd5` from upstream `/MachineConfigMd5`; `compute_code_md5(machine_name)` only feeds 6 virtual entries. **v5 stance**: preserved (out of scope per addendum §3).

4. **Duplication concentrated in md5 + summary-patch + session-CI + inference triggers** — `01 §4` itemizes six duplications. **v5 fix**: Phase 1 extracts ALL SIX (covered by v2 Phase 1; v5 keeps the same).

5. **Module globals + import-time side effects are latent suicide bombs** — `03 §4.1` enumerates 11 references to `RAWDATA_ROOT`, 33 module globals in the analyzer. Memory `feedback_subprocess_import_suicide_and_module_globals.md`. **v5 fix**: Phase 1 dependency injection (covered by v2).

### §1.3 The §9 framing change — operator diagnostic, not internal assertion

Memory `feedback_invariant_with_fallback_hides_drift.md` measured fleet-wide: 55 of 117 cached BCM (m, mode) pairs have >0.5% RTP falling into `_unattributed_st<N>` fallback buckets (M250 100%, M268/M260/M264 70-90%, M163/M147 ~35%). v2 framed this as an "internal RTP correctness" problem and built a 3-layer gate with a numeric threshold. **v3/v4/v5 reframes**: the fallback bucket is the symptom that the **console couldn't analyze this machine**. The architectural response is not "is RTP correct? fail if not", but **"can the console deliver a trustworthy signal to the operator? if not, say so explicitly with actionable diagnosis"**.

The reframe matters for two design decisions:

- The check is no longer a threshold gate (statistical noise can trip a threshold); it's a per-machine **completeness declaration** (operator-side concept; see §5.5 / §9).
- The check has 4 layers in v3/v4/v5 (was 3 in v2), with **Layer 4** (v4 revised; v5 trigger-session false-positive fix added) catching dispatch-routing bugs at the rawdata level.

### §1.4 Headline blast-radius framing (per addendum v2 §1.1, kept from v2/v3/v4)

| Change class | Blast under current architecture | Blast under proposal | Reduction |
|---|---|---|---|
| **Per-cluster feature edit** (e.g., adding BCM cleanup rule) | 421 machines | 12-30 machines (one cluster) | 12-30× |
| **Per-machine bespoke fix** (e.g., M21 Buffalo-counter tweak) | 421 machines | 1 machine | 421× |
| **Novel machine onboarding** (M400 with new feature plugin) | 421 machines | 1 machine (only declarant) | 421× |
| **Universal feature edit** (e.g., renaming a field used by every machine) | 421 machines | 421 machines | **1× (no reduction by design)** |
| **Frontend renderer plugin update** | varies (silent break risk) | machines using that renderer; schema-version gated | varies + safety improvement |
| **Bespoke-plugin lift for a previously-vanilla machine** | 421 (added to monolith) | 1 (new bespoke feature + manifest line) | 421× |
| **Schema rename inside a universal feature** | 421 + silent renderer break | 421 + explicit fallback rule applied | 1× invalidation but 0× silent break |

Universal-feature-edit class is explicitly **1× by design** — the proposal does not fake reduction.

---

## §2 Design alternatives

v5 keeps v4's 3 alternatives unchanged. Alternative A v5 is the recommended variant, refining A v4 per the v5 addendum.

### §2.1 Alternative A v5 — Per-machine manifests + sliced analyzer + operator-diagnostic console signal (recommended)

**Core idea (unchanged from A v4)**: Every one of the 421 machines has an explicit manifest declaring (a) which feature plugins it uses, (b) which round-win rules it uses, (c) **whether the console claims it can diagnose this machine completely** (the `console_diagnostic_complete` flag). The analyzer is sliced into `core/` (universal orchestration) + `features/` (opt-in). The per-machine effective analyzer version composes from base + the features the manifest declares.

**Key changes from A v4** (v5-specific):

- §9.4 Layer 4 trigger-session false-positive fix: **Skip approach** (approach b) — machines with `trigger_session_pattern != null` get `layer4_applicable: false` in manifest; Layer 4 does not run for those machines. Trade-off: trigger-session machines lose Layer 4 protection and rely on Layers 1-3 only. Documented and accepted — see §9.4.
- §6.3.3 deliverable list: **item 0 gates Day-1 verification** as a numbered formal deliverable, not prose advice (closes Critic v4 Q6 / E6 procedural gap).
- §5.5.7 override metadata + quarterly QA review + lint rule (closes Critic v4 Concern C / Validator v4 Scenario 4).
- §9.4 perf estimate: per-machine ~3s, full fleet pull ~20 min (or "measure during implementation").
- §9.4 RoundWinRules constraint explicitly stated.
- §9.4 Step C `_unattributed_*` note added.

**Pros (grounded in Wave 1)**:

- Implements addendum §1.5 philosophy — every machine has a manifest; sharing is opt-in via plugin composition.
- Implements addendum §1.4 constraint S **and** addendum v3 §1 operator-diagnostic framing — the console either delivers correct numbers OR an explicit per-machine error with actionable diagnosis hints.
- v4's Layer 4 (§9.4) performs an independent rawdata re-scan (Step B), not a same-dict readout, catching the dispatch-routing bug class Critic v3 identified as uncaught by v3.
- v5's trigger-session fix prevents systematic false-positives from machines using `compute_trigger_sessions` (M15/M273 etc.) without losing the structural benefit of Layer 4 for non-trigger-session machines.
- The Day-1 verification deliverable (§6.3.3 item 0) is now a formal gating step, not skippable prose.
- Override metadata + lint rule closes the stale-override organizational footgun.

**Cons (acknowledged)**:

- Skip approach (b) for trigger-session machines means Layer 4 cannot catch dispatch-routing bugs for M14/M15/M120/M139/M279 etc. (those machines rely on Layers 1-3 only). The mirror approach (a) would preserve Layer 4 coverage but at the cost of independence from `compute_trigger_sessions`.
- Fleet of trigger-session machines is material (~17 documented per addendum v5 §1 Issue ①, plus many BCM machines with trigger semantics). They permanently operate without Layer 4 protection until a future session-aware Layer 4 is designed.
- Day-1 verification adds ~10 min upfront cost before Phase 3.

**Migration cost estimate**: MEDIUM-HIGH (same as A v4). v5 adds minimal overhead.

### §2.2 Alternative B — Lightweight per-feature SCHEMA_VERSION sidecar (rejected as in v2/v3/v4)

**Why B remains rejected in v5**: B doesn't implement the operator-diagnostic framing from addendum v3 §1. Under B, the console has no per-machine completeness signal and cannot implement v4/v5's Layer 4 rawdata cross-check. Addendum v3 §1's framing strengthens the rejection.

### §2.3 Alternative C — Full per-machine analyzer plugin tree (rejected as in v2/v3/v4)

**Why C remains rejected in v5**: C eliminates sharing wholesale; addendum §1.5 says "sharing is opt-in via manifest". v4/v5's §5.5.7 variant cascade fix is the opposite of C's "no sharing" stance. C would force 166 per-variant plugin files (parallel-impl anti-pattern per memory `feedback_no_parallel_panel_impl.md`).

### §2.4 Comparison table (v5 update)

| Criterion | A v5 (recommended) | B (sidecar) | C (per-machine plugins) |
|---|---|---|---|
| Implements addendum v3 §1 operator-diagnostic framing | YES | NO | PARTIAL |
| Implements addendum §1.5 philosophy (every machine potentially unique) | YES | NO | OVERSHOOTS |
| Implements addendum §1.4 constraint S | YES (§9 with 4 layers; Layer 4 skipped for trigger-session machines) | NO | PARTIAL |
| **v4 Layer 4 catches dispatch-routing bugs (Critic v3 M1)** | **YES — Step B independent rawdata scan (non-trigger-session machines)** | NO | PARTIAL |
| **v5 trigger-session false-positive fix (Critic v4 Concern A)** | **YES — Skip approach: `layer4_applicable: false` for trigger-session machines** | N/A | N/A |
| **Day-1 verification as formal gated deliverable (Critic v4 Concern B / Q6)** | **YES — §6.3.3 item 0** | NO | NO |
| **Override metadata + quarterly QA + lint rule (Critic v4 Concern C)** | **YES — §5.5.7 extended** | NO | NO |
| **Day-1 strict candidates enumerated (Critic v3 M2)** | **YES — §6.3 names 46+ machines** | NO | NO |
| **Variant completeness cascade consistent (Critic v3 S1)** | **YES — §5.5.7 eager cascade with true→false-only override** | NO | NO |
| `inherits_from` cascade semantics resolved | YES — eager per addendum v3 §3 #4 | n/a | n/a |
| Phase 2 RTP-gate dependency resolved | YES — gate code in Phase 2 | n/a | n/a |
| `console_diagnostic_complete` per-machine flag | YES | NO | NO |
| Solves universal feature-edit blast | NO by design (honest about 1×) | NO | NO |
| Solves schema-rename silence | YES | YES | YES |
| LOC delta estimate | +3,500-4,000 | +250 | +12,000 |
| Migration risk | MEDIUM-HIGH | LOW | HIGH |

---

## §3 Recommended design — Alternative A v5

**Pick: Alternative A v5** (per-machine manifests + sliced analyzer + operator-diagnostic signal with 4-layer integrity check, Layer 4 skipped for trigger-session machines + per-machine completeness flag with Day-1 strict candidates formally gated + consistent variant cascade with override metadata + quarterly QA + lint rule).

**Reasoning** (cited from Wave 1 + addendum + Wave 3 v4 reviews):

1. **A v5 resolves the trigger-session false-positive class** — Critic v4 Concern A + addendum v5 Issue ① showed that machines with `trigger_session_pattern != null` (M14, M15, M120, M139, M279, M273 variants, plus many BCM machines per memory `reference_trigger_session_patterns.md`) would produce systematic false-positive Layer 4 failures on every fleet pull. `compute_trigger_sessions` re-attributes free-spin round wins to the triggering paid-spin session bucket, mutating `payout_id_by_spin_type_total`. Step B's naive rawdata SpinType count doesn't replicate this re-attribution. The Skip approach (`layer4_applicable: false` for `trigger_session_pattern != null`) removes the false-positive class entirely at the cost of Layer 4 coverage for those machines. The Mirror approach (approach a) would have preserved independence at the cost of having Step B share `compute_trigger_sessions` — if that helper has a bug, the cross-check would miss it. The Skip approach's trade-off is more honest: these machines have Layer 4 protection only if a future session-aware Layer 4 is designed.

2. **A v5 gates the Day-1 verification as a formal deliverable** — Critic v4 Q6/E6 identified that the pre-Phase-3 verification step was buried in §6.3.1 prose, not in the Phase 3 deliverable list. Any implementer following the deliverable list could write manifests for all 421 machines, set the ~45 SC-Vanilla to `true` based on expectation, and skip verification. v5 §6.3.3 item 0 makes the verification a gating step that must be completed before any subsequent Phase 3 deliverable.

3. **A v5 closes the override-clearing organizational footgun** — Critic v4 Concern C + Validator v4 Scenario 4 showed that the override mechanism was correct (sticky-conservative) but lacked a specified re-enablement lifecycle. Adding `override_set_at` / `override_set_reason` / `override_set_by` metadata + quarterly QA review + lint rule for stale overrides creates an auditable, durable cycle without making overrides auto-clear unsafely.

4. **A v5 preserves A v4's validated parts** — Validator v4 gave clean verifications on hash composition, manifest schema mechanics, Plugin Protocol, Phase 1 deliverables, Layer 4 Step B empirical pass on M274, synthetic mismatch scenario. v5 keeps all of these unchanged.

5. **B is rejected** per §2.2. **C is rejected** per §2.3.

The remaining sections specify A v5 in detail.

---

## §4 Hash composition rules (unchanged from v2/v3/v4)

v2's algorithm validated cleanly by Wave 3 v2 (Validator §4 cross-product 0 regressions). v3/v4 kept it unchanged. v5 keeps it unchanged.

### §4.1 The composition algorithm (unchanged)

```python
# fresh_slotlab/analyzer/versioning.py (NEW)

def compute_base_analyzer_version() -> str:
    """SHA256 of fresh_slotlab/analyzer/core/*.py — universally-invoked code only.
    Replaces compute_analyzer_version() at player_impact_analyzer.py:2141.
    Length: 12 hex chars (matches legacy)."""

def compute_feature_hashes() -> dict[str, str]:
    """For each module registered in feature_registry.ALL_FEATURES,
    return {feature_id: short_hex_hash}. Computed at startup."""

def compute_effective_analyzer_version(
    *, base_hash: str,
    feature_hashes: dict[str, str],
    machine_features: list[str],
    mode: int | None = None,
) -> str:
    """Per-machine (optionally per-mode) effective hash.

    Composition:
      h = sha256(base_hash)
      for fid in sorted(set(machine_features)):
        h.update(b"\\x00" + fid + b"=" + feature_hashes[fid])
      if mode is not None:
        h.update(b"\\x00mode=" + str(mode))
      return h.hexdigest()[:12]
    """
```

The per-(machine, mode) effective version is:

```
effective_analyzer_version(M, mode) =
    sha256( base_hash ||
            "\\x00".join(f"{fid}={feature_hashes[fid]}" for fid in sorted(manifest[M, mode].analyzer_features)) ||
            f"\\x00mode={mode}"
          )[:12]
```

### §4.2 Per-change-class blast table (unchanged from v2/v3/v4)

See §1.4 above. Six change classes; only one (universal-feature edit) stays at 1×, the rest reduce by 12-421×.

### §4.3 Worked examples — invalidation radius

Six examples carried unchanged from v2 §4.3. Example 6 (M250 graduation: vanilla → bespoke) is executable in Phase 2 because the RTP gate code is built in Phase 2.

### §4.4 Per-machine config_md5 and code_md5 — virtual side unchanged

Unchanged from v2/v3/v4 §4.4. Out of scope per addendum §3.

### §4.5 Honesty about universal-feature changes

Unchanged from v2/v3/v4 §4.5. The proposal does not claim to reduce blast for universal feature changes; it makes more features non-universal so the path of least resistance changes over time.

### §4.6 Hash composition map (unchanged from v2/v3/v4 §4.6)

```
Source-file edit
   |
   v
 [a] fresh_slotlab/analyzer/core/*.py             ──> base_hash flips → all 421 machines × all modes
 [b] fresh_slotlab/analyzer/features/<fid>.py    ──> feature_hashes[fid] flips → only machines declaring fid
 [c] slot_designer/core/engine/*.py +             ──> compute_code_md5(M) flips → 6 virtual machines only
     slot_designer/core/emitter/*.py                   (out of scope per addendum §3)
 [d] slot_designer/machines/<M>/plugins/**/*.py  ──> compute_code_md5(M) flips → only that virtual machine
 [e] slot_designer/machines/<M>/{spec,strips,    ──> compute_config_md5 flips → only that virtual machine + mode
       weights}
 [f] slot_designer/configs/machine_manifests/<M>.json
                                                  ──> effective_analyzer_version(M, mode) flips
                                                       only when manifest field affecting feature list changes
 [g] upstream /MachineConfigMd5 emission          ──> machines.json upstream md5 flips (real machines only)
   |
   v
 effective_analyzer_version(M, mode) =
     sha256(base_hash || sorted(features_M_uses) || mode)[:12]
   |
   v
 Stamped into:
   * summary.effective_analyzer_version  ← stamped at write time
   * summary.analyzer_features          ← list of features used; for debugability
   * summary.schema_versions[fid]       ← per-feature version map
   * runs.effective_analyzer_version    ← state/console/console.db (new col)
   * reports/<M>/mode_<N>/index.json[*].effective_analyzer_version
```

Per addendum §1.2 clean break: no compatibility layer for pre-v3 reports.

---

## §5 Plugin / extension Protocol + manifest

v2's Protocol + manifest mechanics validated by Wave 3 v2. v3 updated §5.5 for `console_diagnostic_complete` flag, variant justification, eager cascade, and `per_mode_overrides` field enumeration. v4 updated §5.5.7 (variant cascade for completeness flag). v5 updates **§5.5.7 only** (override metadata + quarterly QA review + lint rule, Issue ③). All other sections unchanged from v4.

### §5.1 Three plugin axes (unchanged from v2/v3/v4 §5.1)

| Axis | Existing artifact | v5 contract |
|---|---|---|
| Round-level extraction | `RoundWinRule` ABC at `round_win.py:102` + RULE_REGISTRY at `:423` | Formalized as-is; manifest declares rule_ids |
| Summary-level aggregation | (today: inline in `parse_chunk_response` + `main()`) | NEW `AnalyzerFeature` Protocol with REQUIRES + RTP_CONTRIBUTION flag |
| Frontend rendering | (today: 17 inline renderers; no contract) | NEW renderer registry with explicit fallback rules |
| **[v3 NEW]** Console diagnostic completeness | (today: silent `_unattributed_st<N>` synthesizer) | Per-machine `console_diagnostic_complete` boolean in manifest + 4-layer integrity check per §9 |

### §5.2 `AnalyzerFeature` Protocol (unchanged from v2/v3/v4 §5.2)

```python
# fresh_slotlab/analyzer/features/_base.py (NEW)
from abc import ABC, abstractmethod
from typing import ClassVar, Any
import hashlib
from pathlib import Path

class AnalyzerFeature(ABC):
    """Versioned, opt-in slice of analyzer functionality."""

    FEATURE_ID: ClassVar[str] = ""
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ()
    SCHEMA_VERSION: ClassVar[int] = 1
    REQUIRES: ClassVar[tuple[str, ...]] = ()
    RTP_CONTRIBUTION: ClassVar[bool] = False
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    @abstractmethod
    def extract(self, parse_state, chunk_dict) -> dict: ...

    @abstractmethod
    def reduce(self, prev_acc, this_acc) -> Any: ...

    @abstractmethod
    def emit(self, final_acc, summary: dict) -> None: ...

    @classmethod
    def compute_hash(cls) -> str:
        src = Path(cls.__module__.replace(".", "/") + ".py")
        return hashlib.sha256(src.read_bytes()).hexdigest()[:12]
```

### §5.3 Frontend renderer registry (unchanged from v2/v3/v4 §5.3)

```typescript
// src/web_console/frontend/renderers/registry.js (NEW)
interface RendererPlugin {
  readonly id: string;
  readonly schemaKey: string;
  readonly minSchemaVersion: number;
  readonly maxSchemaVersion: number;
  readonly fallbackRules?: Record<number, FallbackMap>;
  render(summary: object, host: HTMLElement, ctx: RendererCtx): void;
}
```

### §5.4 SCHEMA_VERSION bump policy (unchanged from v2/v3/v4 §5.4)

The table is identical to v2's. Pre-commit hook enforcement; fallback test required for any non-trivial bump. Resolves Critic v1 Q7 + §7.8.

### §5.5 Per-machine manifest format — v5 change in §5.5.7

Sections §5.5.1 through §5.5.6 are identical to v4. The v5 change is in §5.5.7 (override metadata + quarterly QA + lint rule for `console_diagnostic_complete` variants).

#### §5.5.1 Layout (unchanged from v2/v3/v4)

```
slot_designer/configs/machine_manifests/
  M1.json
  M14.json
  M15.json
  M15$TopDollarSelector$0$.json    # variant — see §5.5.4
  M21.json
  M260.json
  M274.json
  M279.json
  ...
  manifest_schema.json             # JSON Schema for validation
```

#### §5.5.2 Manifest schema (per-machine file) — v4/v5 form (unchanged from v4)

Full schema with M274 as example:

```json
{
  "machine_id": "M274",
  "manifest_version": 1,
  "inherits_from": null,
  "console_diagnostic_complete": true,
  "layer4_applicable": true,
  "spin_type_convention": {"paid": [140], "bonus": [139]},
  "feature_tags": ["BCM", "Wheel"],
  "round_win_rules": ["bcm_cycle_anchor_m274"],
  "analyzer_features": [
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "bankruptcy_simulation",
    "bonus_chain_dynamics",
    "collect_mechanic",
    "multiplier_profile",
    "cycle_peak_detection"
  ],
  "bcm_target_feature": "ListRewardWheel",
  "trigger_session_pattern": null,
  "modes_supported": [1, 5, 7],
  "per_mode_overrides": {
    "5": {
      "analyzer_features_remove": ["bonus_chain_dynamics"]
    }
  },
  "rtp_integrity_contract": {
    "expected_paid_st": [140],
    "expected_bonus_st": [139],
    "required_attribution_anchors": ["_bcm_cycle", "5801"]
  }
}
```

**v5 addition**: `layer4_applicable` boolean field (see §9.4). For machines with `trigger_session_pattern != null`, this field is `false`. For all other machines, it is `true` (default, may be omitted). The `rtp_integrity.py` gate reads this field before running Step B.

No `fallback_share_threshold_pct`, no `exception_policy`. The `console_diagnostic_complete` boolean is the single per-machine completeness signal.

#### §5.5.3 `console_diagnostic_complete` semantics (unchanged from v3/v4)

**`console_diagnostic_complete: true`** — the operator declares "console claims it can diagnose this machine correctly":

- All applicable layers from §9 enforced as **hard errors** if they fail (Layer 4 only when `layer4_applicable: true`)
- Failure blocks the individual machine's report write
- Does NOT block the fleet pull — other machines' reports continue to be produced
- Error message guides the operator per §9.3 format with actionable diagnosis hints

**`console_diagnostic_complete: false`** — used during development of new machine support:

- All applicable layers from §9 are still computed but their failure produces a **warning**, not an error
- Report is still produced + flagged "[INCOMPLETE]" in the summary metadata + visible in the rwtree UI
- Migration path: flip to `true` when rules are verified clean per §6.3.2 criteria

**Initial values at Phase 3 cutover** (v4 update, unchanged in v5): most machines ship `false`; Day-1 strict candidates (§6.3.1) ship `true`. See §6.3 for the enumerated list and flip criteria.

#### §5.5.4 Variant justification (unchanged from v3/v4)

`inherits_from` for variants is intentional. Variants represent the same underlying machine with different user-decision configurations. Analyzer rules and parsing must be identical between a variant and its underlying — they read the same rawdata schema from the same machine code. Storage and reports are isolated per variant because user-decision histories differ. `inherits_from` lets the variant manifest reuse the underlying's `analyzer_features` list by reference.

**This is NOT cluster-by-inheritance.** The parser sharing is **by definition** because variants ARE the same machine. There is no similarity assumption to be wrong about.

#### §5.5.5 Variant cascade — eager (unchanged from v3/v4)

When an underlying machine's manifest changes, all variants pick up the change immediately. Variants ARE the same machine; their parser cannot drift from the underlying's parser. Lazy resolution would create a silent correctness bug. Hash-composition consequence: when M273.json changes, all 86 hashes (1 underlying + 85 variants) flip — correct behavior.

#### §5.5.6 Fields that support `per_mode_overrides` (unchanged from v3/v4)

| Field | Override syntax | Example use case |
|---|---|---|
| `analyzer_features` | `analyzer_features_add: [...]`, `analyzer_features_remove: [...]` | M274 mode 5 removes `bonus_chain_dynamics` |
| `round_win_rules` | `round_win_rules_add: [...]`, `round_win_rules_remove: [...]` | M-something where one mode uses a different rule set |
| `bcm_target_feature` | `bcm_target_feature_override: "<feature_name>"` | M279 mode 1 = Wheel, modes 2/5/7 = MoveSpin |
| `trigger_session_pattern` | `trigger_session_pattern_override: "type_1" \| "type_2" \| null` | machines where session pattern differs per mode |
| `spin_type_convention` | `spin_type_convention_override: {"paid": [...], "bonus": [...]}` | rare; for machines whose ST set differs per mode |
| `feature_tags` | `feature_tags_override: [...]` | rare; for tagging mode-specific behavior |
| `rtp_integrity_contract.required_attribution_anchors` | `required_attribution_anchors_override: [...]` | M279 mode 1 (Wheel) requires `27905`; modes 2/5/7 (MoveSpin) require different anchors |
| `rtp_integrity_contract.expected_paid_st` / `expected_bonus_st` | `expected_paid_st_override: [...]`, `expected_bonus_st_override: [...]` | machines where ST set differs per mode |

Fields that **do NOT** support `per_mode_overrides`: `machine_id`, `manifest_version`, `inherits_from`, `console_diagnostic_complete`, `layer4_applicable` (both are per-machine; a machine either uses trigger-session re-attribution or it does not — per-mode variation is handled via `trigger_session_pattern_override` which, when non-null in any mode, drives the per-mode `layer4_applicable` resolution).

**Resolution order**: `per_mode_overrides.<mode>` first applies `_remove` operations to the base list, then applies `_add` operations.

#### §5.5.7 Variant cascade for `console_diagnostic_complete` (v5 CHANGE — extends v4 §5.5.7 with override metadata, quarterly QA, and lint rule)

**Core cascade mechanism (unchanged from v4)**: Variants inherit `console_diagnostic_complete` from their underlying machine (eager cascade), matching the `analyzer_features` cascade in §5.5.4–§5.5.5. Override allowed only `true → false` (regression valve); never `false → true`. Resolver logic and `resolve_completeness()` pseudocode are unchanged from v4.

**v5 addition — Override metadata** (Issue ③, closes Validator v4 Scenario 4 spec gap and Critic v4 Concern C):

When a variant's `console_diagnostic_complete_override: false` is set, the manifest MUST also include the following metadata fields:

```json
{
  "machine_id": "M273$WheelSelector$42$",
  "manifest_version": 1,
  "inherits_from": "M273.json",
  "console_diagnostic_complete_override": false,
  "override_set_at": "2026-05-17T09:00:00Z",
  "override_set_reason": "WheelSelector$42$ triggers an uncommonly-deep Wheel nesting path not present in M273 underlying's rawdata sample. Layer 2 fires on a ~0.4% RTP fallback bucket for a specific wheel stop combination. Bespoke rule pending.",
  "override_set_by": "arch-team / 2026-05-17 arch review"
}
```

- `override_set_at` (ISO-8601 timestamp): when the override was first applied
- `override_set_reason` (free-form text): which specific edge case triggered the override; must reference the Layer(s) that fail on the variant's rawdata
- `override_set_by` (free-form text): person/team/process responsible for the override decision

**Manifest validation rule**: if `console_diagnostic_complete_override: false` is present but any of `override_set_at`, `override_set_reason`, `override_set_by` are absent, the manifest validator emits an error: "Override without metadata is forbidden. Add override_set_at + override_set_reason + override_set_by."

**v5 addition — Override-clearing procedure** (Issue ⑥):

To clear an override when the edge case is resolved:

1. Run `rtp_integrity.py` against the specific variant's most recent rawdata sample (or a representative re-sample). All applicable layers must PASS (Layer 4 only if `layer4_applicable: true` for this variant).
2. Remove the `console_diagnostic_complete_override`, `override_set_at`, `override_set_reason`, `override_set_by` fields from the variant manifest entirely.
3. Commit with message:

   ```
   clear console_diagnostic_complete_override for <variant_id>
   Underlying edge case resolved: <brief description>
   Verification: rtp_integrity all applicable layers PASS on <rawdata version tag>
   Run date: <date>
   Verified by: <role / initials>
   ```

The variant then inherits `true` from the underlying (assuming underlying is `true`). The same §6.3.2 flip criteria apply (all applicable layers pass + no known issues + audit log).

**v5 addition — Quarterly QA review process** (Issue ③):

Once per calendar quarter, the QA team reviews all variant manifests that carry `console_diagnostic_complete_override: false`. For each such variant:

1. Locate the underlying machine's current `console_diagnostic_complete` value and the date of its last flip.
2. If the underlying is currently `true` AND the underlying's last flip date is AFTER `override_set_at` (i.e., the underlying was fixed after the override was set), the specific edge case may have been resolved by the same fix.
3. Re-run `rtp_integrity.py` against the variant's most recent rawdata. If all applicable layers pass, clear the override per the procedure above.
4. If layers still fail, leave the override in place and update `override_set_reason` with the new investigation finding.

This ensures overrides do not accumulate indefinitely after the underlying issue is fixed.

**v5 addition — Lint rule for stale overrides** (Issue ③):

`scripts/manifest_lint.py` (Phase 3 deliverable §6.3.3 item 9) is extended to include the following check:

```
For each variant manifest V carrying console_diagnostic_complete_override: false:
    underlying = resolve_underlying(V)
    if underlying.console_diagnostic_complete == true:
        underlying_last_flip = git_log_last_change(underlying_path, "console_diagnostic_complete")
        if underlying_last_flip > V.override_set_at:
            emit WARNING:
                "Variant {V.machine_id}: override_set_at ({V.override_set_at}) is earlier than
                 underlying {underlying.machine_id}'s last flip ({underlying_last_flip}).
                 The underlying issue may have been resolved. Re-run rtp_integrity.py against
                 {V.machine_id}'s rawdata and clear the override if all applicable layers pass."
```

This lint rule runs in CI on every PR that touches any manifest under `machine_manifests/`. It does NOT block merges — it emits a WARNING, not an error. The quarterly QA review is the enforcement mechanism; the lint rule is the reminder signal.

**Resolver logic (unchanged from v4)**:

```python
_UNSET = object()

def resolve_completeness(variant_manifest, underlying_manifest) -> bool:
    """Resolve console_diagnostic_complete for a variant.

    Cascade rule: underlying's value is the default.
    Override rule: variant can only go true → false (regression valve).
    Override false → true is rejected at manifest validation time.
    """
    underlying_complete = underlying_manifest["console_diagnostic_complete"]
    override = variant_manifest.get("console_diagnostic_complete_override", _UNSET)
    if override is _UNSET:
        return underlying_complete
    if override is False:
        return False   # regression valve: variant found an edge case
    # override is True — validation should have caught this at commit time
    raise ManifestValidationError(
        f"{variant_manifest['machine_id']}: console_diagnostic_complete_override: true "
        f"is not permitted. Variants cannot elevate completeness above their underlying. "
        f"Underlying {underlying_manifest['machine_id']} is the authoritative source."
    )
```

**Operational consequence**: when M273 is flipped to `true` (underlying verified complete), all 85 variants automatically become strict. The operator must verify that the underlying's parser quality covers the variant data shapes — guaranteed by the §5.5.4 parser-sharing premise.

**Blast-radius implication for flip decisions**: flipping the underlying to `true` also flips all 85 variants. The flip criteria in §6.3.2 apply to the underlying; passing the criteria implies all variants are also covered.

**Exception audit log**: any `console_diagnostic_complete_override: false` on a variant must be accompanied by the `override_set_at` + `override_set_reason` + `override_set_by` metadata (v5 addition). git history provides the full audit trail.

**Manifest validation rules (v5 additions)**:

- Rule 6 (from v4): `console_diagnostic_complete_override: true` on any variant manifest is a validation error.
- **Rule 10 (v5 NEW)**: if `console_diagnostic_complete_override: false` is present, all three metadata fields (`override_set_at`, `override_set_reason`, `override_set_by`) must be present and non-empty. Missing metadata = validation error.
- **Rule 11 (v5 NEW)**: if a manifest declares `trigger_session_pattern != null` and `layer4_applicable: true` simultaneously, this is a validation error: "Machines with trigger_session_pattern must have layer4_applicable: false. See §9.4."

### §5.6 Manifest validation rules — strict (updated for v5 §5.5.7 additions)

1. Every machine in `configs/machines.json` MUST have a manifest file. Missing file = error.
2. Every `analyzer_feature` ID MUST correspond to a class in `feature_registry.ALL_FEATURES`. Typo = error.
3. Every `round_win_rule` ID MUST be defined in `configs/machine_round_win_rules.json` with this machine in `applies_to`.
4. REQUIRES dependency satisfaction.
5. Mode coverage: for every mode in `modes_supported`, the resolved per-mode feature set must include all RTP_CONTRIBUTION=True features that the integrity contract requires.
6. Non-variant manifests: `console_diagnostic_complete` MUST be a boolean. Variant manifests: the field is either absent (inherited from underlying) or `console_diagnostic_complete_override: false` only. `console_diagnostic_complete_override: true` on any variant manifest is a validation error.
7. `expected_paid_st` + `expected_bonus_st` non-empty; `required_attribution_anchors` validated at first run (not commit time) against rawdata.
8. **v3 NEW**: if `console_diagnostic_complete: true`, every feature in `feature_registry.ALL_FEATURES` whose `RTP_CONTRIBUTION=True` flag is set MUST be present in the manifest's `analyzer_features`.
9. Rawdata sanity check (if rawdata available; 206 of 421 machines): declared `spin_type_convention.paid` must match observed paid-ST set; various feature-declaration consistency checks.
10. **v5 NEW**: if `console_diagnostic_complete_override: false` is present on a variant manifest, all three metadata fields (`override_set_at`, `override_set_reason`, `override_set_by`) must be present and non-empty. Missing metadata = validation error.
11. **v5 NEW**: `trigger_session_pattern != null` AND `layer4_applicable: true` simultaneously is a validation error. Layer 4 cannot run correctly for trigger-session machines without re-attribution — they must set `layer4_applicable: false`.

### §5.7 Feature discovery + missing-feature runtime error (unchanged from v2/v3/v4 §5.7)

`@register` decorator + manual import in `fresh_slotlab/analyzer/features/__init__.py`. `feature_registry.ALL_FEATURES` runtime source of truth. Manifest typo caught at validation; runtime missing-feature raises `RuntimeError` clearly.

### §5.8 In-process monkey-patch path under sliced architecture (unchanged from v2/v3/v4 §5.8)

`pia.main` remains entry point post-slice; thin orchestrator delegating to `analyzer/core/base_pipeline.py`. Monkey-patches attach at same attribute. Phase 1 deliverable 9 codifies 3-style parity test.

### §5.9 Per-machine `round_win_rule` plugin (unchanged from v2/v3/v4 §5.9)

`round_win.py:102` ABC + RULE_REGISTRY unchanged. Manifest references rule_ids.

### §5.10 Plugin lifecycle (unchanged from v2/v3/v4 §5.10)

Adding / deleting / renaming features; historical reports per addendum §1.2 clean-break.

### §5.11 Manifest examples — v5 form

**M1** (vanilla, SC-Vanilla — Day-1 strict candidate per §6.3.1; no trigger sessions):

```json
{
  "machine_id": "M1",
  "manifest_version": 1,
  "inherits_from": null,
  "console_diagnostic_complete": true,
  "layer4_applicable": true,
  "spin_type_convention": {"paid": [1], "bonus": []},
  "feature_tags": ["Plain"],
  "round_win_rules": [],
  "analyzer_features": [
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "bankruptcy_simulation",
    "multiplier_profile"
  ],
  "trigger_session_pattern": null,
  "modes_supported": [1, 2, 5, 7],
  "rtp_integrity_contract": {
    "expected_paid_st": [1],
    "expected_bonus_st": [],
    "required_attribution_anchors": []
  }
}
```

**M15** (TopDollar, rule-bearing, trigger sessions — starts `false`; `layer4_applicable: false`):

```json
{
  "machine_id": "M15",
  "manifest_version": 1,
  "inherits_from": null,
  "console_diagnostic_complete": false,
  "layer4_applicable": false,
  "spin_type_convention": {"paid": [1], "bonus": [14, 15]},
  "feature_tags": ["Selector"],
  "round_win_rules": ["topdollar_selector_settlement"],
  "analyzer_features": [
    "payouts_by_spin_type",
    "bankruptcy_simulation",
    "topdollar_settlement",
    "multiplier_profile"
  ],
  "selector_type": "TopDollarSelector",
  "trigger_session_pattern": "type_1",
  "modes_supported": [1, 2, 5, 7],
  "rtp_integrity_contract": {
    "expected_paid_st": [1],
    "expected_bonus_st": [14, 15],
    "required_attribution_anchors": ["666"]
  }
}
```

Note: `trigger_session_pattern: "type_1"` sets `layer4_applicable: false` per manifest validation rule 11. Layer 4 is not run for M15. Layers 1-3 are enforced when it graduates to `complete: true`.

**M274** (BCM + Wheel — Day-1 strict candidate per §6.3.1 Group B, pending Layer 4 v4 re-verification; no trigger sessions):

```json
{
  "machine_id": "M274",
  "manifest_version": 1,
  "inherits_from": null,
  "console_diagnostic_complete": true,
  "layer4_applicable": true,
  "spin_type_convention": {"paid": [140], "bonus": [139]},
  "feature_tags": ["BCM", "Wheel"],
  "round_win_rules": ["bcm_cycle_anchor_m274"],
  "analyzer_features": [
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "bankruptcy_simulation",
    "bonus_chain_dynamics",
    "collect_mechanic",
    "multiplier_profile",
    "cycle_peak_detection"
  ],
  "bcm_target_feature": "ListRewardWheel",
  "trigger_session_pattern": null,
  "modes_supported": [1, 5, 7],
  "per_mode_overrides": {
    "5": {
      "analyzer_features_remove": ["bonus_chain_dynamics"]
    }
  },
  "rtp_integrity_contract": {
    "expected_paid_st": [140],
    "expected_bonus_st": [139],
    "required_attribution_anchors": ["_bcm_cycle", "5801"]
  }
}
```

**M279** (heavy outlier — starts `false`; no trigger sessions but complex BCM routing):

```json
{
  "machine_id": "M279",
  "manifest_version": 1,
  "inherits_from": null,
  "console_diagnostic_complete": false,
  "layer4_applicable": true,
  "spin_type_convention": {"paid": [140], "bonus": [2, 36]},
  "feature_tags": ["BCM", "MoveNudge", "Wheel"],
  "round_win_rules": [],
  "analyzer_features": [
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "bankruptcy_simulation",
    "bonus_chain_dynamics",
    "collect_mechanic",
    "multiplier_profile",
    "cycle_peak_detection",
    "wild_nudge_classification",
    "pay_id_suffix_attribution",
    "bespoke_m279_combo"
  ],
  "bcm_target_feature": "Wheel",
  "trigger_session_pattern": null,
  "modes_supported": [1, 2, 5, 7],
  "per_mode_overrides": {
    "2": {"bcm_target_feature_override": "MoveSpin", "required_attribution_anchors_override": ["_bcm_cycle"]},
    "5": {"bcm_target_feature_override": "MoveSpin", "required_attribution_anchors_override": ["_bcm_cycle"]},
    "7": {"bcm_target_feature_override": "MoveSpin", "required_attribution_anchors_override": ["_bcm_cycle"]}
  },
  "rtp_integrity_contract": {
    "expected_paid_st": [140],
    "expected_bonus_st": [2, 36],
    "required_attribution_anchors": ["_bcm_cycle", "27905"]
  }
}
```

**M273$WheelSelector$0$** (variant — inherits completeness from M273 underlying; no override):

```json
{
  "machine_id": "M273$WheelSelector$0$",
  "manifest_version": 1,
  "inherits_from": "M273.json",
  "spin_type_convention_override": null,
  "feature_tags_override": null,
  "analyzer_features_override": null
}
```

**M273$WheelSelector$42$** (variant — override with v5 metadata; M273 is a trigger-session machine):

```json
{
  "machine_id": "M273$WheelSelector$42$",
  "manifest_version": 1,
  "inherits_from": "M273.json",
  "console_diagnostic_complete_override": false,
  "override_set_at": "2026-05-17T09:00:00Z",
  "override_set_reason": "WheelSelector$42$ triggers an uncommonly-deep Wheel nesting path not present in M273 underlying's rawdata sample. Layer 2 fires on a ~0.4% RTP fallback bucket for a specific wheel stop combination. Bespoke rule pending.",
  "override_set_by": "arch-team / 2026-05-17 arch review"
}
```

Note: M273 has `trigger_session_pattern: "type_2"` (per memory `reference_trigger_session_patterns.md` — WheelSelector = Type 2 session pattern). Therefore M273.json has `layer4_applicable: false`. The variant inherits this. The override on M273$WheelSelector$42$ applies to `console_diagnostic_complete` (inherited value), not Layer 4 applicability.

---

## §6 Migration plan — v5 changes

v5 keeps v4's 6 phases. The **change** in v5 is §6.3 (Phase 3 deliverables), specifically §6.3.3 which adds item 0 as a formal gating deliverable for Day-1 verification. Phase 2 (gate code construction) and Phase 5 (policy flip) are unchanged from v4.

### §6.1 Phase 1 — Foundation (unchanged from v2/v3/v4)

All 12 Phase 1 deliverables from v2/v3/v4 §6 unchanged. Resolves all 5 pre-Phase-1 blockers from `01 §5`. Risk LOW-MEDIUM; 4-6 days; trivial rollback.

### §6.2 Phase 2 — Slice analyzer + forcing function + RTP integrity gate code (unchanged from v3/v4)

Goals and deliverables unchanged from v4 §6.2. The key deliverable is `fresh_slotlab/rtp_integrity.py` with all applicable layers in warn-only mode. Layer 4 in Phase 2 is built per the v4/v5 Step A/B/C algorithm (§9.4), with the trigger-session skip logic (`if not manifest.layer4_applicable: skip Step B`). Risk HIGH; 12-16 days.

Deliverables (abbreviated; full list in v4 §6.2):
1. Carve `core/` (4 files).
2. Carve 4 universal features.
3. Carve 9 cluster-shared features.
4. Carve 12 forcing-function bespoke features.
5. **Build `fresh_slotlab/rtp_integrity.py`** — Layers 1-3 for all machines; Layer 4 per v4/v5 §9.4 Step A/B/C algorithm (skips Step B when `manifest.layer4_applicable == false`), runs in warn-only mode.
6. Demonstrate Example 6 workflow end-to-end on M250.
7. `fresh_slotlab/analyzer/versioning.py`.
8. `fresh_slotlab/analyzer/feature_registry.py`.
9. Per-cluster regression tests.

### §6.3 Phase 3 — Per-machine manifests + wiring + Day-1 strict candidates (v5 CHANGE in §6.3.3)

**Goals (unchanged from v4)**:
- Land 421 per-machine manifest files.
- Ship Day-1 strict candidates with `console_diagnostic_complete: true`. All remaining machines ship as `false`.
- Wire `compute_effective_analyzer_version` to consult manifest per machine, per mode.
- Frontend reads manifest-driven feature list to know which renderers to invoke.
- Clean break from old reports.

#### §6.3.1 Day-1 strict candidates (unchanged from v4)

The following machines ship as `console_diagnostic_complete: true` at Phase 3 cutover:

**Group A — SC-Vanilla cluster (~45 machines per `02 §4.2`)**:

Source: `02 §4.2` super-cluster table. SC-Vanilla definition: machines co-clustering across all 5 axes — ST-1A (paid=1, no bonus) / F-Plain (exact `{NormalRTPPreProcessor, NormalSpinGenerator, NormalSpinValidator}` logicClassNames) / 1-9 paylines / S-Base rawdata schema (Tier-0 keys only) / no round_win_rules entries.

Named members (rawdata-confirmed, per `02 §4.2` and `02 §3.5.3 Tier-1`): M1, M14, M37, M101, M105, M127, M13, M135, M137, M139, M142, M143, M145, plus the remaining machines with exact `{NormalRTPPreProcessor, NormalSpinGenerator, NormalSpinValidator}` logicClassNames as identified during Phase 3 manifest authoring (target: all 45 per `02 §4.2`).

**Eligibility basis**: SC-Vanilla machines have been in production for years with no known correctness issues. No bespoke rules needed. No `_unattributed_*` rows in historical reports (per `02 §3.5.3 Tier-1`). All have `trigger_session_pattern: null` (plain machines, no bonus ST). Memory `user_testing_machine.md` confirms M14 mode 1 is the primary validation machine.

**Layer 4 applicability**: SC-Vanilla machines have `layer4_applicable: true`. Their single-ST dispatch is trivially clean — all rounds use ST=1 (paid), no re-attribution by `compute_trigger_sessions`. Layer 4 Step B scan will show single-ST dispatch with 0 routing complexity.

**Group B — M274 (empirically verified per Validator v2 §2.6)**:

Source: Validator v2 §2.6 live data walkthrough — "0 `_unattributed_*` entries; pid `_bcm_cycle` has 315 hits / 4.867% rtp_pp; pid `5801` has 3592 hits / 54.11% rtp_pp; Sum of all rtp_pp = 106.338125 == summary.rtp.point_pct." Both required anchors present. M274 has `trigger_session_pattern: null` — Layer 4 is applicable.

**Layer 4 v4/v5 re-verification required**: M274 must be re-verified under v4/v5 Layer 4 (Step B independent rawdata scan) before Phase 3 cutover. Expected outcome: pass, per Validator v4 §2.6.2 empirical partial scan (0 ST-set mismatches).

**Group C — Other Validator v2 walkthroughs that passed cleanly**:

M37 (Group A SC-Vanilla), M14 (Group A SC-Vanilla). Non-candidates: M15 (trigger sessions), M99 (dedup bug), M279 (BCM routing complexity), M250 (100% fallback), M65 (collection mechanic complexity).

**Estimated Day-1 count**: ~45 (Group A) + 1 (M274, pending Layer 4 re-verification) = **~46 machines** shipping `console_diagnostic_complete: true` at Phase 3 cutover. Approximately 11% of the 421-machine fleet.

#### §6.3.2 Flip criteria for future machines (unchanged from v4)

A machine flips from `console_diagnostic_complete: false` → `true` when ALL of the following hold:

1. **All applicable layers PASS on representative rawdata**: run `python -m fresh_slotlab.rtp_integrity M<N> --mode <mode>` against the most recent representative rawdata sample (10k+ spins for the machine's primary mode). For machines with `layer4_applicable: true`, all 4 layers — including Layer 4 Step B rawdata scan — must return PASS. For machines with `layer4_applicable: false`, Layers 1-3 must return PASS (Layer 4 is not applicable by design).

2. **No known issue or pending rule update**: no open issue in the repo or QA backlog indicating a parser gap or pending rule addition for this machine.

3. **Audit log entry**: the flip commit message must include:
   ```
   flip console_diagnostic_complete: false → true for M<N>
   Basis: rtp_integrity all applicable layers PASS on [rawdata version tag]
   Layer 4 applicable: [true|false] — [if false: trigger_session_pattern = <value>]
   Run date: [date]
   Verified by: [role / initials]
   ```

**Direction asymmetry**: a machine flips `true → false` when a regression is discovered. Any team member can flip `true → false` without ceremony — the conservative direction is always permitted.

**Variant flip**: when an underlying machine is flipped to `true`, all its variants automatically inherit `true` (per §5.5.7 cascade). The flip commit for the underlying covers all variants. A variant-specific `console_diagnostic_complete_override: false` (with required metadata per v5 §5.5.7) is added if a specific variant's data reveals an edge case not present in the underlying's verification sample.

#### §6.3.3 Phase 3 deliverables — v5 CHANGE (item 0 added as formal gating deliverable)

> **v5 change**: Critic v4 Q6/E6 found that the pre-Phase-3 verification step was described in §6.3.1 prose but was NOT in the Phase 3 deliverable list, making it skippable. v5 adds it as item 0 (gates all subsequent items).

**Item 0 (GATE — must complete before proceeding to items 1-9)**: Run `rtp_integrity.py --machine M --mode N` against each Day-1 candidate's latest cached chunks; verify all applicable layers PASS.

- For each Group A machine (SC-Vanilla ~45): run `rtp_integrity.py` in Layer 1-4 mode (all applicable; `layer4_applicable: true` for all SC-Vanilla). Expected: trivial PASS (single ST=1, no bonus, no routing complexity). Cost: ~3s per machine × 45 machines = ~135s.
- For M274 (Group B): run `rtp_integrity.py` in Layer 1-4 mode (`layer4_applicable: true`). Expected: PASS per Validator v4 §2.6.2 empirical partial scan, but requires full 8-robot × 8-chunk run. Cost: ~3s.
- **Total estimated cost**: ~10 minutes for all 46 candidates (inclusive of setup, teardown, and any machine that requires rawdata re-fetch). This is a one-time upfront cost per Phase 3.
- **Recording**: implementation team records per-machine pass/fail in the Phase 3 kickoff commit message:
  ```
  Phase 3 Day-1 verification results:
    GROUP A: M1 PASS / M14 PASS / M37 PASS / ... (all 45 listed)
    GROUP B: M274 PASS
    TOTAL: 46 PASS / 0 FAIL → 46 machines authorized for console_diagnostic_complete: true
  ```
- **Failed candidates → Day-2 pending QA**: if any candidate fails verification (any layer), it does NOT ship `true`. Instead:
  - Set `console_diagnostic_complete: false` in that machine's manifest.
  - Add to "Day-2 pending QA" subsection in the Phase 3 commit description, noting which layer failed and the investigation hypothesis.
  - The Day-1 count drops accordingly (e.g., 45 instead of 46 if M274 fails Layer 4).
  - No Day-1 authorizations are blocked by the failure — the rest proceed.
  - The failed machine's flip is deferred to after the regression is investigated and fixed.

**Items 1-9** (unchanged from v4 §6.3.3, now renumbered):

1. Write 421 per-machine manifests. Day-1 candidates verified in item 0 ship `true`; all others ship `false`. Include `layer4_applicable` field per §5.5.2 for all machines with `trigger_session_pattern != null`.
2. `manifest_loader.py` — reads manifests, resolves `inherits_from` (eager), resolves `per_mode_overrides`, includes `resolve_completeness()` per §5.5.7.
3. Wire `compute_effective_analyzer_version` to read manifest per (machine, mode).
4. Update analyzer + backend write sites to use effective version.
5. Update `/api/reports/stale-count` to compare per-(machine, mode) `effective_analyzer_version`. No NULL handling (clean break).
6. ALTER TABLE runs ADD COLUMN effective_analyzer_version TEXT.
7. Frontend updates (`app.js`, `pure.js`): freshness and renderer-skip logic.
8. Manifest validation CLI: `scripts/validate_manifests.py` (includes v5 rules 10 and 11 from §5.6).
9. Manifest tooling: `scripts/manifest_lint.py` (includes v5 stale-override lint rule from §5.5.7), `manifest_diff.py`, `manifest_audit.py`.

**Phase 3 risk**: MEDIUM; 4-7 days (v4 was 4-7 + 0.5 for Day-1 verification step; v5 formalizes the verification as item 0 within the same time estimate — the work was always required, just not formally gated).

### §6.4 Phase 4 — Frontend renderer registry + schema-version contract enforcement (unchanged from v2/v3/v4)

All 7 Phase 4 deliverables from v2/v3/v4 §6 unchanged. Risk LOW; 2-3 days.

### §6.5 Phase 5 — Flip RTP integrity gate default policy from warn to error (unchanged from v4)

Goals, deliverables, and risk (LOW-MEDIUM; 2-3 days) are unchanged from v4 §6.5. The key v3 deliverable is the policy flip in `rtp_integrity.py`: when `manifest.console_diagnostic_complete == true`, applicable layer failures raise; when `== false`, warnings only.

**v4/v5 difference at Phase 5 deployment**:
- v3: 0 machines have `console_diagnostic_complete: true` on Phase 5 day 1 → strict-error mechanism dormant.
- v4/v5: ~46 machines have `console_diagnostic_complete: true` from Phase 3 (item 0 verified) → Phase 5 strict-error policy flip immediately engages for those ~46 machines.

Phase 5 deliverable 4 (known-broken machines triage): at Phase 5 deploy time, the operator continues flipping machines to `true` per §6.3.2 criteria.

**Rollback**: revert Phase 5 commits. Gate stays in warn-only mode globally. Per-machine `true` flags in manifests remain but are not enforced as errors. No data loss.

### §6.6 Phase 6 — (Optional / out-of-scope) Retro-fit + consolidation (unchanged from v2/v3/v4)

Optional. Phase 6 deliverables: consolidation of `machine_round_win_rules.json`, architecture docs, medium-outlier audit + flip for verified-clean machines. Risk LOW; 3-5 days.

### §6.7 Phase summary table (v5 updated)

| Phase | Risk | Days est. | Schema change | Rollback simplicity |
|---|---|---|---|---|
| 1 (dedup + globals + 5 mapper blockers) | LOW-MEDIUM | 4-6 | None | Trivial revert |
| 2 (slice analyzer + 12 forcing-function machines + RTP integrity gate code v4/v5 Layer 4 + trigger-session skip logic) | HIGH | 12-16 | Per-feature SCHEMA_VERSION; effective_analyzer_version; `summary.rtp_integrity_check`; `layer4_applicable` field | Per-feature revert |
| 3 (manifests + clean-break; **v5: item 0 gates Day-1 verification formally**; ~46 Day-1 candidates ship `true` if item 0 passes; remainder `false`) | MEDIUM | 4-7 | Manifest files; new DB col; `layer4_applicable` field | Manifest ignored on rollback |
| 4 (frontend registry + SCHEMA_VERSION enforcement) | LOW | 2-3 | None | Trivial revert |
| 5 (flip policy; **v4/v5: policy engages for ~46 `true` machines on day 1**) | LOW-MEDIUM | 2-3 | New `integrity_failures` DB table; new badge UI | Policy flip reverts globally |
| 6 (optional retro-fit + consolidation + outlier audit) | LOW | 3-5 | None | Optional throughout |

Total: ~28-41 dev days (sequential). Comparable to v4's 28-41 days (v5 formalizes the 0.5-day verification within Phase 3's estimate, no net addition).

### §6.8 Migration constraint compliance (v5 updated)

| Constraint | How honored by v5 plan |
|---|---|
| **00 §5.1** Backward-compat for 393 machines' reports | Per addendum §1.2 clean-break authorization, relaxed. Operators regen from rawdata. |
| **00 §5.2** Prod console (8877) never breaks | Each phase has rollback; Phase 2 verified against 12 forcing-function machines BEFORE commit. |
| **00 §5.3** Virtual reuses prod code | Phase 1 removes 6 dups; Phase 2's features shared. |
| **00 §5.4** New machine = O(1) hash | Phase 3 manifests + Phase 2's bespoke pattern. Universal-feature changes still 1× per §1.4. |
| **00 §5.5** Rollback per phase | Documented per phase. |
| **00 §5.6** No silent data loss | Phase 2 RTP integrity gate (applicable layers including v4/v5 Layer 4) makes silent loss explicit error or warning. |
| **Addendum §1.4** RTP integrity hard constraint S | Phase 2 gate + Phase 5 policy flip + §9 reframed per addendum v3 §1. |
| **Addendum §1.5** Every machine potentially unique | Phase 3 per-machine manifests; eager variant cascade per §5.5.5. |
| **Addendum v3 §1** Operator-diagnostic framing | §9 entirely rewritten; `console_diagnostic_complete` per-machine flag; §1 problem statement rewritten. |
| **Addendum v4 §1 Issue ①** Layer 4 must catch dispatch-routing bugs | §9.4 Step A/B/C rawdata-level cross-check (non-trigger-session machines). |
| **Addendum v4 §1 Issue ②** Day-1 strict candidates enumerated | §6.3.1 names ~46 machines; §6.3.2 specifies flip criteria; **v5: §6.3.3 item 0 formally gates verification**. |
| **Addendum v4 §1 Issue ③** Variant cascade for completeness flag | §5.5.7 — eager cascade from underlying; **v5: override metadata + quarterly QA + lint rule added**. |
| **Addendum v5 §1 Issue ①** Trigger-session false-positive structural fix | §9.4 — Skip approach: `layer4_applicable: false` for `trigger_session_pattern != null` machines; manifest validation rule 11 enforces consistency. |
| **Addendum v5 §1 Issue ②** Day-1 verification as formal deliverable item 0 | §6.3.3 item 0 (gates items 1-9); ~10 min estimate; failed candidates → "Day-2 pending QA". |
| **Addendum v5 §1 Issue ③** Variant override metadata + quarterly QA + lint | §5.5.7 override metadata fields; quarterly QA review procedure; stale-override lint rule in `manifest_lint.py`. |
| **Addendum v5 §1 Issue ④** Layer 4 perf estimate | §9.4 perf note: ~3s per machine; ~20 min full fleet pull (sequential; parallelized per-machine subprocess reduces wall time). |
| **Addendum v5 §1 Issue ⑤** RoundWinRules constraint on `payout_id_by_spin_type_total` | §9.4 explicit constraint statement. |
| **Addendum v5 §1 Issue ⑦** Step C `_unattributed_*` note | §9.4 Step C note — corroborates Layer 2; implementers must not suppress. |

---

## §7 Open questions for Wave 3 v5

v5 closes all 4 Critic v4 Concerns (A/B/C/D) and all 3 Validator v4 documentation gaps (§3.1/§3.2/§3.3). Remaining open questions are well-scoped:

### §7.1 Future session-aware Layer 4 for trigger-session machines

The Skip approach (approach b) accepted in v5 means that machines with `trigger_session_pattern != null` never benefit from Layer 4 dispatch-routing verification. They rely on Layers 1-3 only.

**For Wave 3 v5 / Wave 4 consideration**: is there a future session-aware Layer 4 variant worth specifying? The Mirror approach (approach a from addendum v5 §1 Issue ①) — having Step B also call `compute_trigger_sessions` after raw scan — would restore Layer 4 coverage for trigger-session machines. The trade-off is that a bug in `compute_trigger_sessions` would no longer be caught by Layer 4 (Step B would replicate the bug). Whether this trade-off is worth restoring coverage is a v6+ design question, not a v5 blocker.

Implementation team note: if the Mirror approach is revisited in a future session, the relevant entry point is `fresh_slotlab/trigger_sessions.py`'s `compute_trigger_sessions` function (per memory `reference_trigger_session_patterns.md`). The implementation would call `compute_trigger_sessions(rounds_list)` in Step B after the raw scan, and re-attribute the per-round ST counts accordingly before comparison.

### §7.2 Quarterly QA review: ownership and tooling

§5.5.7 specifies a quarterly QA review for stale overrides. The procedure is defined, but the organizational ownership is not: who schedules the review? Is it the QA team, the slot-designer team, the arch team? Does `manifest_audit.py` produce a per-quarter report for the reviewer?

This is an operational concern for the implementation team (same class as §8.13's out-of-scope items). The spec correctly defines the procedure and the lint rule provides the technical signal. Organizational assignment is out of this proposal's scope.

---

## §8 Out of scope (refined for v5)

§8.1–§8.12 unchanged from v2/v3/v4 §8. §8.13 is carried from v4 (partially specified flip mechanism). §8.14 is new.

### §8.13 `console_diagnostic_complete` flip mechanism — partially specified (unchanged from v4)

v4 §6.3.2 specifies the flip criteria and direction asymmetry. What remains explicitly out of scope:

- Which organizational role owns flip decisions for non-Day-1-candidate machines (QA / operator / slot-* team / arch team)
- Batch-flip tooling (e.g., a script that sweeps the fleet, identifies candidates passing all applicable layers, and generates bulk flip PRs)
- Scheduled re-verification cadence (e.g., weekly re-run of the gate for all `true` machines to catch regressions)

These are operational concerns for the implementation team. v4/v5 specifies the criteria and audit format; organizational ownership and tooling build are out of scope.

### §8.14 Session-aware Layer 4 for trigger-session machines

v5 uses the Skip approach (b): machines with `trigger_session_pattern != null` have `layer4_applicable: false` and are not subject to Layer 4. A session-aware Layer 4 (Mirror approach a — Step B calls `compute_trigger_sessions` after raw scan) would restore Layer 4 coverage for this class.

This is explicitly out of scope for v5. The Skip approach is accepted for this iteration. The Mirror approach trade-off (Step B shares `compute_trigger_sessions` → a bug in that helper would not be caught) is documented in §2.1 Cons. Future sessions may revisit this if Layer 4 coverage for trigger-session machines becomes a priority. See §7.1.

---

## §9 Operator diagnostic signal — Console's RTP integrity output (v5 CHANGES in §9.4)

Sections §9.1 through §9.3 and §9.5 through §9.8 are unchanged from v4. The v5 changes are in **§9.4**: trigger-session false-positive structural fix (Issue ①), perf estimate (Issue ④), RoundWinRules constraint (Issue ⑤), and Step C `_unattributed_*` note (Issue ⑦).

### §9.1 Purpose (unchanged from v3/v4)

The console exists to help the operator (策划) find issues in production machine configurations they themselves wrote. Production machines faithfully execute the operator's configuration. Rawdata reflects that configuration. The console's job is to analyze rawdata correctly and tell the operator whether the result matches intent.

**When the console cannot reliably analyze a machine, it must surface that to the operator with actionable diagnosis hints — not silently fall back to wrong numbers.**

Memory `feedback_invariant_with_fallback_hides_drift.md` documents the failure mode: "55 of 117 cached BCM (machine, mode) pairs have >0.5% RTP falling into the `_unattributed_st<N>` fallback bucket". The 4-layer check (with Layer 4 skipped for trigger-session machines) makes these explicit signals rather than silent leaks.

Memory `feedback_no_silent_swallow.md` documents the broader principle: any best-effort post-hook's outcome must persist to disk. The integrity check result is persisted per-run (DB + summary); never silently swallowed.

### §9.2 The 4-layer integrity check — Layers 1, 2, 3 (unchanged from v3/v4)

For every (machine, mode) analyzer run, the gate computes applicable layers and produces a structured result.

#### Layer 1 — Hard invariant (unchanged from v2/v3/v4)

```
sum(payout_id_win[pid] for all pid) == chunk_win  (across all chunks)
```

If this fails, the analyzer's arithmetic is wrong. Layer 1 catches pure arithmetic / accumulator bugs.

#### Layer 2 — Fallback-bucket non-existence (unchanged from v3/v4)

```
No payout_id starts with "_unattributed_", "_other", "_default", or "_misc".
```

**Any fallback-bucket row** is the signal that the console couldn't attribute some win to a real pay_id. No statistical threshold. The reserved fallback prefix list: `_unattributed_`, `_other`, `_default`, `_misc`.

#### Layer 3 — Attribution-anchor coverage (unchanged from v2/v3/v4)

Per manifest, every machine declares `required_attribution_anchors` — a list of pay_ids that MUST appear in the summary (with > 0 hits) if the machine's mechanic is functioning correctly.

- M274's manifest requires `["_bcm_cycle", "5801"]` — both must have hits.
- M15's manifest requires `["666"]`.
- A vanilla machine like M1 may have `[]` (no required anchors — vacuously passes).

If any required anchor has 0 hits, Layer 3 fires.

#### Combined check structure (unchanged from v3/v4)

```python
@dataclass
class RTPIntegrityResult:
    machine: str
    mode: int
    passed: bool
    layer1_invariant_ok: bool
    layer1_error: str | None
    layer2_no_fallback_buckets_ok: bool
    layer2_fallback_buckets_found: list[str]
    layer3_anchors_ok: bool
    layer3_missing_anchors: list[str]
    layer4_applicable: bool                     # v5: False for trigger-session machines
    layer4_per_st_consistency_ok: bool | None   # v5: None when layer4_applicable=False
    layer4_inconsistencies: list[dict]          # v5: empty list when layer4_applicable=False
    summary_message: str
    suggested_actions: list[str]
    completeness_declared: bool                 # mirrors manifest.console_diagnostic_complete
```

A machine **passes** only if all applicable layers pass. When `layer4_applicable` is `False`, Layer 4 is not evaluated and `layer4_per_st_consistency_ok` is `None` (not contributing to pass/fail).

### §9.3 Per-machine error format (unchanged from v4)

The JSON error format and human-readable CLI format are identical to v4 §9.3. The Layer 4 inconsistency entry format is the same as v4. When `layer4_applicable: false`, the error output includes: `"layer4_skipped": true, "layer4_skip_reason": "trigger_session_pattern is non-null; Layer 4 dispatch counts are expected to differ due to compute_trigger_sessions re-attribution."` This makes it explicit to the operator why Layer 4 did not run, and distinguishes "skipped by design" from "failed."

### §9.4 Layer 4 — Dispatch routing self-consistency via rawdata cross-check (v5 CHANGE: trigger-session fix + perf + constraint + Step C note)

**Why v3's Layer 4 failed (carried from v4)**: v3 §9.2 Layer 4 compared two readouts of the same in-memory dict `payout_id_by_spin_type_total`. Critic v3 Concern 2 verified this by reading `player_impact_analyzer.py:6438-6509`. v4 fixed this with the Step A/B/C rawdata cross-check.

**v5 new concern (Critic v4 Concern A + addendum v5 Issue ①)**: v4's Step B naively reads `R.SpinType` per round from rawdata without applying `compute_trigger_sessions`. However, `compute_trigger_sessions` (called from `parse_chunk_response`) re-attributes free-spin round wins to the triggering paid-spin session bucket, mutating `payout_id_by_spin_type_total`. Specifically (per memory `reference_trigger_session_patterns.md`):

- For Type 1 trigger-session machines (M15, M12, M32, M90, M132, M206, M39, M86, M116, M210, M123 etc.): bonus rounds (e.g., ST=14, ST=15 for M15) have their pids attributed to the paid-round bucket (ST=1) via `payout_id_win[pid] += session["session_win"]`.
- For Type 2 trigger-session machines (M273 WheelSelector, M201 CommonSelector, M257 Freespin etc.): same re-attribution logic applies via `sum_all` session win rule.

So `analyzer_dispatch[pid][paid_st]` would be higher than `fresh_dispatch[pid][paid_st]` (because re-attributed bonus-round pids inflate the paid-ST count), and `analyzer_dispatch[pid][bonus_st]` would be lower. Step C would fire false-positive mismatches for every trigger-session machine on every fleet pull.

**v5 structural fix — Skip approach (approach b)**:

For machines with `trigger_session_pattern != null` in their manifest, Layer 4 does NOT run. The manifest field `layer4_applicable: false` indicates this.

**Trade-off documented**:

| Aspect | Skip approach (v5, approach b) | Mirror approach (approach a, not chosen) |
|---|---|---|
| Layer 4 coverage for trigger-session machines | None — relies on Layers 1-3 only | Restored — Step B also calls `compute_trigger_sessions` |
| Independence of Layer 4 check | High (no change) | Reduced — Step B shares `compute_trigger_sessions`; a bug in that helper would not be caught by Layer 4 |
| False-positive risk | Eliminated | Eliminated |
| Trigger-session machines protected by Layer 4 | None (~17+ documented machines) | All trigger-session machines |
| Implementation complexity | Low — add `layer4_applicable` field + skip check | Medium — Step B must call and apply `compute_trigger_sessions` correctly |
| Future path | Mirror approach can be added in a future session as an opt-in for trigger-session machines | N/A (this is the future path) |

The Skip approach is chosen for v5 because:

1. Layer 4's goal is "verify dispatch routing correctness" — not "verify trigger-session re-attribution correctness" (which is a separate concern with its own tests per memory `reference_trigger_session_patterns.md`).
2. The Mirror approach would reduce Layer 4's independence for all trigger-session machines. A bug in `compute_trigger_sessions` (which has had 5+ iterations of fixes per memory `round_classification_primitives.md`) would silently evade detection.
3. Trigger-session machines already have Layers 1-3 enforced. Layer 3 requires that the trigger anchor pay_id (e.g., `666` for M15) is present with >0 hits — this indirectly verifies that `compute_trigger_sessions` attributed wins to the anchor correctly.
4. The affected fleet fraction (~17+ documented trigger-session machines per addendum v5 §1 Issue ①) is material but not the majority. The 45 SC-Vanilla Day-1 candidates (all `trigger_session_pattern: null`) retain full Layer 4 coverage.

**v5 Layer 4 applicability gating**:

```
Before executing Step B, the integrity check reads manifest.layer4_applicable:

if not manifest.layer4_applicable:
    result.layer4_applicable = False
    result.layer4_per_st_consistency_ok = None     # not evaluated
    result.layer4_inconsistencies = []
    result.layer4_skip_reason = (
        f"trigger_session_pattern={manifest.trigger_session_pattern!r}; "
        f"compute_trigger_sessions re-attributes free-spin round pids to paid-spin bucket, "
        f"making naive rawdata SpinType counts incomparable to analyzer_dispatch counts. "
        f"Layer 4 skipped. Layers 1-3 are enforced."
    )
    return result  # skip Steps A, B, C
```

**v5 constraint — RoundWinRules MUST NOT write to `payout_id_by_spin_type_total`** (Issue ⑤):

> **RoundWinRules MUST NOT write to `payout_id_by_spin_type_total` directly.** They interact only with the final summary accumulator (hits/win counters, e.g., `payout_id_win` and `payout_id_hits`). Writing synthetic pids (like `_bcm_cycle`) to `payout_id_by_spin_type_total` would cause Step A to capture those synthetic pids, while Step B (rawdata scan) would not find them in `PayoutIdToWinAmount`, producing a spurious Layer 4 mismatch.

This constraint is verified in practice: M274's `bcm_cycle_anchor_m274` rule does NOT write to `payout_id_by_spin_type_total` — confirmed by Validator v4 §2.6.4 finding that `_bcm_cycle` has `spin_type_breakdown = []` (empty) in live reports. The constraint makes this implicit requirement explicit for all future `RoundWinRule` authors.

**The Step A / B / C algorithm (v5 — identical to v4 except: applicability gate at top; perf note updated; Step C `_unattributed_*` note added)**:

```
Layer 4 (v4/v5 revised): Dispatch routing self-consistency via rawdata cross-check

For each (machine, mode) being analyzed — runs as part of rtp_integrity.py:

  Applicability gate (v5 NEW):
    if not manifest.layer4_applicable:
        emit layer4_skip with reason; return (do not execute Steps A/B/C)

  Step A — Capture analyzer's dispatch result:
    # Source: payout_id_by_spin_type_total built during parse_chunk_response
    # RoundWinRules MUST NOT write to this dict (see constraint above).
    # This dict drives both payouts_by_spin_type AND spin_type_breakdown.
    analyzer_dispatch = {}   # dict[pid, dict[st_int, count]]
    for pid_str, st_counts in payout_id_by_spin_type_total.items():
        pid = int(pid_str) if pid_str.isdigit() else pid_str
        analyzer_dispatch[pid] = dict(st_counts)   # copy; int ST keys

  Step B — Independent fresh scan of rawdata chunks:
    fresh_dispatch = {}   # dict[pid, dict[st_int, count]]
    # Iterate ALL chunk files independently — do NOT call any analyzer function.
    # Do NOT call compute_trigger_sessions (applicability gate above ensures
    # this Step only runs for machines where trigger-session re-attribution
    # does not apply, i.e., trigger_session_pattern == null).
    for chunk_path in sorted(rawdata_dir.glob("chunk_*.json")):
        chunk = json.loads(chunk_path.read_bytes())
        for robot_response in chunk["response"]:
            for round_result in robot_response.get("roundResult", []):

                # Edge case: SpinType field missing → data corruption
                raw_st = round_result.get("SpinType")
                if raw_st is None:
                    raise Layer4Error(
                        f"SpinType field missing in round at "
                        f"{chunk_path}:{robot_response['robotId']}. "
                        f"Possible cause: data corruption or rawdata envelope version drift."
                    )
                try:
                    st = int(raw_st)
                except (TypeError, ValueError):
                    raise Layer4Error(
                        f"SpinType field invalid (value={raw_st!r}) at "
                        f"{chunk_path}:{robot_response['robotId']}."
                    )

                # Extract pids fired this round (0-win-but-fired pids included
                # per 4cbcab2 fix — count existence in PayoutIdToWinAmount.keys())
                payout_id_to_win = round_result.get("PayoutIdToWinAmount", {})
                for pid_str in payout_id_to_win.keys():
                    try:
                        pid = int(pid_str)
                    except (TypeError, ValueError):
                        pid = pid_str   # keep as string for non-numeric pids

                    if pid not in fresh_dispatch:
                        fresh_dispatch[pid] = {}
                    fresh_dispatch[pid][st] = fresh_dispatch[pid].get(st, 0) + 1

  Step C — Compare:
    inconsistencies = []
    all_pids = set(analyzer_dispatch.keys()) | set(fresh_dispatch.keys())
    for pid in all_pids:
        a_sts = analyzer_dispatch.get(pid, {})
        f_sts = fresh_dispatch.get(pid, {})
        all_sts = set(a_sts.keys()) | set(f_sts.keys())
        for st in all_sts:
            a_count = a_sts.get(st, 0)
            f_count = f_sts.get(st, 0)
            if a_count != f_count:
                # v5 NOTE: if pid starts with "_unattributed_", "_other", "_default",
                # or "_misc", this mismatch CORROBORATES Layer 2's existing fail
                # (the fallback synthesizer wrote a synthetic pid to payout_id_by_spin_type_total
                # but that pid does not appear in rawdata's PayoutIdToWinAmount).
                # Implementers MUST NOT suppress these Step C mismatches — they are
                # additional evidence of the Layer 2 dispatch failure, not false positives.
                inconsistencies.append({
                    "pay_id": pid,
                    "spin_type": st,
                    "analyzer_dispatch_count": a_count,
                    "rawdata_observed_count": f_count,
                    "difference": a_count - f_count,
                    "is_fallback_pid": (
                        isinstance(pid, str) and
                        any(pid.startswith(p) for p in ("_unattributed_", "_other_", "_default_", "_misc_"))
                    ),
                    "note": (
                        f"Analyzer dispatched {a_count} round(s) with pid={pid} to ST={st}; "
                        f"rawdata shows {f_count}. "
                        + (
                            f"[FALLBACK PID] This mismatch corroborates Layer 2's fallback-bucket detection. "
                            f"The fallback synthesizer created this synthetic pid but rawdata has no such pid in PayoutIdToWinAmount. "
                            f"Do not suppress this mismatch — it is additive evidence of Layer 2 failure, not a false positive."
                            if (
                                isinstance(pid, str) and
                                any(pid.startswith(p) for p in ("_unattributed_", "_other_", "_default_", "_misc_"))
                            ) else
                            f"Possible causes: (a) dispatch rule routes these rounds to wrong ST bucket / "
                            f"(b) round_classification primitive mismatch for ST={st}. Investigate."
                        )
                    )
                })

    if inconsistencies:
        result.layer4_per_st_consistency_ok = False
        result.layer4_inconsistencies = inconsistencies
    else:
        result.layer4_per_st_consistency_ok = True
        result.layer4_inconsistencies = []
```

**Motivating cases**:

- **M31 pid-8 bug (dispatch routing, non-trigger-session machine)**: v3 Layer 4 PASSES (trivially-true self-check on same dict). v4/v5 Layer 4 Step B reads rawdata independently → `fresh_dispatch[8][43] = 22370`, `fresh_dispatch[8][44] = 10797` vs `analyzer_dispatch[8][43] = 33167` → Step C fires. Bug caught.

- **M15 trigger-session machine**: v5 `manifest.layer4_applicable = false` (M15 has `trigger_session_pattern: "type_1"`). Applicability gate fires → Layer 4 skipped. No false-positive. Layer 3 still enforces `required_attribution_anchors: ["666"]`.

- **M250 fallback pid case (corroborating Layer 2)**: M250's `_unattributed_st139` fallback synthesizer writes to `payout_id_by_spin_type_total`. Step A captures `_unattributed_st139` in `analyzer_dispatch`. Step B reads rawdata — `_unattributed_st139` never appears in `PayoutIdToWinAmount.keys()`. Step C finds mismatch for `_unattributed_st139`. The mismatch `is_fallback_pid: true` with note "[FALLBACK PID] This mismatch corroborates Layer 2's fallback-bucket detection." Layer 2 already fired (M250 has `_unattributed_st139` row). Layer 4 adds corroborating signal. Implementers MUST NOT suppress this Step C entry — it is additive detection, not a false positive.

**Performance note** (Issue ④):

Step B adds one full pass through rawdata chunks. Per addendum v5 §1 Issue ④ the estimate is:

- **Per machine**: ~3s for 414k spins on warm local disk. Basis: Step B's per-round loop is ~20 lines of direct Python with no rule resolution, no trigger-session computation, no feature extraction. Pure JSON key iteration. Contrast with the main analysis pass (1,607+ lines of code per `parse_chunk_response`). The ~3s estimate assumes chunks are already on local disk from the main pass (OS page cache warm) and sequential JSON parsing at typical Python throughput (~50-100k rounds/s).

- **Full fleet pull (~421 machines, sequential)**: 421 × ~3s = ~21 min. In practice, fleet pulls run per-machine subprocesses in parallel; Step B runs inside the same subprocess as the main pass. Wall-clock time for Step B in a parallelized fleet pull is dominated by the slowest machine's Step B, not the sum.

- **For machines with `layer4_applicable: false`**: 0s additional cost (Step B is skipped at the applicability gate).

- **Caveat for large rawdata**: machines with 1M+ spins scale linearly (1M spins ≈ 7-8s for Step B; 3M spins ≈ 22s). The ~3s estimate is per representative 414k-spin machine.

- **Measurement during implementation**: the implementation team SHOULD instrument Step B with a wall-clock timer and record actual per-machine times during Phase 2 development. If Step B exceeds 10s for any machine in the Day-1 candidate set, the implementation team should add a `--skip-layer4-rawdata-scan` escape hatch for development workflows (with a warning that Layer 4 is degraded). This flag MUST NOT be enabled for production fleet pulls.

**Edge cases (unchanged from v4)**:

| Edge case | Handling in Step B |
|---|---|
| `SpinType` field missing from a round | Raises `Layer4Error` with chunk path + robot ID + "data corruption" hypothesis. Layer 4 fails with specific error. |
| `SpinType` field present but value not in `expected_paid_st ∪ expected_bonus_st` | Counted into `fresh_dispatch` under the unexpected ST value. Step C comparison either finds a matching entry in `analyzer_dispatch` (dispatch handles unknown STs consistently) or reports a mismatch. The `note` field hints at "manifest's spin_type_convention may be incomplete". |
| `PayoutIdToWinAmount` field missing from a round | The round had no payouts (zero-win spin). Step B skips it (no pids to count). Consistent with analyzer's main pass behavior. |
| Round has pid with `win = 0` (fired but zero payout) | Step B counts the pid regardless of win amount — existence in `PayoutIdToWinAmount.keys()` is sufficient. Consistent with the `4cbcab2` fix ("retain 0-win-but-fired pids like M31 pid 666" per `00_brief.md §3` commit table). |
| Chunk file has malformed JSON | Step B raises `json.JSONDecodeError`; integrity check fails with data corruption note. |
| Machine has no rawdata cached (0 chunks on disk) | Step B detects "no rawdata chunks found" before iterating and emits specific error: "Layer 4 cannot run: no rawdata chunks found for this (machine, mode). Possible cause: rawdata not yet sampled or deleted." Layer 4 fails explicitly, not silently. |
| Machine has `layer4_applicable: false` | Applicability gate fires before Step A. Layer 4 is entirely skipped. Result records `layer4_applicable: false`, `layer4_per_st_consistency_ok: null`, `layer4_skip_reason: <description>`. |

### §9.5 When the check runs (unchanged from v4)

| Trigger | When integrity check runs |
|---|---|
| Live sampling via `POST /api/runs` | At end-of-run, before summary write |
| In-process replay via `POST /api/rawdata/{m}/generate-report` | After `pia.main()` returns |
| Batch generate-report `POST /api/rawdata/batch-generate-report` | Per item, after each subprocess run |
| Fleet-wide cron pull (e.g., nightly refresh) | Per machine after analyzer completes |
| On-demand fleet check `POST /api/runs/integrity-check-all` | Iterates all (machine, mode) with recent reports |
| Manifest validation `scripts/validate_manifests.py` | Static-only checks (no rawdata); flags machines whose `console_diagnostic_complete: true` is set without all RTP_CONTRIBUTION=True features |

The integrity check is **mandatory** — there is no flag to disable it globally.

### §9.6 Interaction with manifest validation (unchanged from v4)

- **Layer 2 fails**: manifest claims declared features cover this machine, but fallback buckets appeared. Operator: add/fix features or keep `complete: false`.
- **Layer 3 fails**: manifest claims anchor X should appear, but it didn't. Usually means the round_win_rule that synthesizes X isn't applied.
- **Layer 4 fails (applicable machines only)**: Step C found `analyzer_dispatch[pid][st] ≠ fresh_dispatch[pid][st]`. The analyzer's dispatch logic has a routing bug at rawdata level. Operator: investigate `round_classification` rules for the mismatched ST. The `note` field in the inconsistency entry provides the starting hypothesis.
- **Layer 4 skipped (`layer4_applicable: false`)**: expected for trigger-session machines. Not a failure — it is explicitly the Skip approach from §9.4. Operator sees `"layer4_skipped": true` in the report output.

### §9.7 Known-broken machines triage — Illustrative, not exhaustive (unchanged from v3/v4)

**This table is illustrative of the failure modes; it is NOT an exhaustive list. The comprehensive triage list is maintained by the QA team during the Phase 5 default-policy flip rollout.**

| Machine | Mode | Symptom | Failure layer (under v5 gate) | Phase 5 / QA action |
|---|---|---|---|---|
| M250 | 1 | ~100% RTP in `_unattributed_st139` | Layer 2 + Layer 3 (missing `_bcm_cycle`); Layer 4 corroborates (fallback pid in Step C) | Bespoke feature `bespoke_m250_grid.py` in Phase 2. Flip after verified. |
| M268 | 1 | ~70-90% fallback | Layer 2 + likely Layer 3 | Bespoke feature `bespoke_m268_credits_symbol.py` in Phase 2. |
| M260 | 1 | ~70-90% fallback | Layer 2 + likely Layer 3 | Bespoke feature `bespoke_m260_buffs.py` in Phase 2. |
| M264 | 1 | ~70-90% fallback | Layer 2 | Enable `cycle_peak_detection` in manifest; verify. |
| M163 | 1 | ~35% fallback | Layer 2 | Enable `cycle_peak_detection`; verify. |
| M147 | 1 | ~35% fallback | Layer 2 | Enable `cycle_peak_detection`; verify. |
| M274 | 1 | Resolved via `bcm_cycle_anchor_m274`; Layers 1-3 PASS | Layer 4 v4/v5 re-verification pending before Phase 3 cutover | Day-1 strict candidate per §6.3.1 Group B. |
| M99 / M112 | (varied) | Sub-round dedup defect | Likely Layer 1 or Layer 4 (if `layer4_applicable: true`) | Add dedup rule; verify. |
| M15, M273, M273$*, M201, M257, M209 etc. | (varied) | Trigger-session machines | Layers 1-3 only (`layer4_applicable: false`); no Layer 4 | Flip to `complete: true` after Layers 1-3 verified clean + trigger-session rules verified. |
| ~16-21 additional BCM machines | (varied) | 0.5-35% fallback share | Layer 2 | QA team's fleet sweep during Phase 5 rollout identifies them. |

### §9.8 Memory cross-reference (unchanged from v4)

- `feedback_invariant_with_fallback_hides_drift.md`: fallback buckets must be alerts, not silent accounting mechanisms. v4/v5 Layer 4 Step B catches dispatch mis-routing that v3's same-accumulator check missed (for non-trigger-session machines).
- `feedback_no_silent_swallow.md`: integrity check results persisted per-run (DB + summary); never silently swallowed.
- Addendum v3 §1: "Console must analyze rawdata correctly so its diagnostic signals are trustworthy." v4/v5 §9 is the architectural implementation.
- `reference_trigger_session_patterns.md`: documents `compute_trigger_sessions` semantics, Type 1 (ReMarks Trigger) and Type 2 (win=0 pay_id anchor) patterns, and the ~17 trigger-session machine families. This memory is the ground-truth for why Layer 4 must be skipped for `trigger_session_pattern != null` machines.

---

## §10 Resolution map — addendum v5 changes + v4 residuals

### §10.1 Addendum v5's 7 issues — where v5 addresses each

| # | Issue | v5 resolution |
|---|---|---|
| ① | Layer 4 systematic false-positive for trigger-session machines (CRITICAL) | §9.4 — Skip approach: `manifest.layer4_applicable: false` for `trigger_session_pattern != null` machines. Applicability gate fires before Step A. Manifest validation rule 11 enforces consistency. Trade-off documented: trigger-session machines lose Layer 4 coverage; they rely on Layers 1-3 only. §8.14 notes Mirror approach (a) as a future option. |
| ② | Day-1 verification as formal deliverable item 0 | §6.3.3 — item 0 added as gating deliverable that must complete before items 1-9. Cost ~10 min total. Failed candidates → "Day-2 pending QA" subsection. Closes Critic v4 Q6/E6 procedural gap. |
| ③ | Variant override metadata + quarterly QA + lint rule | §5.5.7 — `override_set_at` + `override_set_reason` + `override_set_by` required when override is set; override-clearing procedure specified; quarterly QA review procedure; stale-override lint rule in `manifest_lint.py`. Closes Critic v4 Concern C + Validator v4 Scenario 4. |
| ④ | Layer 4 perf estimate | §9.4 perf note — per machine ~3s; full fleet pull ~20 min sequential; 0s for `layer4_applicable: false` machines. Measurement during implementation recommended. |
| ⑤ | RoundWinRules MUST NOT write to `payout_id_by_spin_type_total` | §9.4 explicit constraint — 2-line statement before Step A pseudocode. Closes Validator v4 §3.1 spec clarification. |
| ⑥ | Override-clearing procedure | §5.5.7 — clearing procedure: run `rtp_integrity.py` against variant's rawdata; remove metadata fields; commit with audit log. Covered by Issue ③ above (same section). Closes Validator v4 §3.2. |
| ⑦ | Step C `_unattributed_*` note | §9.4 Step C — `is_fallback_pid` field in inconsistency dict; note text "[FALLBACK PID] This mismatch corroborates Layer 2's fallback-bucket detection. Do not suppress." Closes Validator v4 §3.3. |

### §10.2 Critic v4 Concerns — resolution status in v5

| Concern | v4 status | v5 resolution |
|---|---|---|
| A — Layer 4 trigger-session false-positive class | Acknowledged in note field; not structurally resolved | RESOLVED — Skip approach: `layer4_applicable: false` + manifest validation rule 11 |
| B — 46 Day-1 candidates unverified against v4 Layer 4; verification not gated | Procedural gap (described in prose, not formal deliverable) | RESOLVED — §6.3.3 item 0 as formal gating deliverable |
| C — Override re-enablement path unspecified | Soft concern; mechanism correct but no reminder | RESOLVED — override metadata + clearing procedure + quarterly QA + lint rule |
| D — Fleet-wide ~35 min Layer 4 penalty unspecified | Open question §7.4 | RESOLVED — §9.4 perf note: ~3s per machine; trigger-session machines (large fraction) 0s; fleet pull parallelized |

### §10.3 Validator v4 Documentation Gaps — resolution status in v5

| Gap | v4 status | v5 resolution |
|---|---|---|
| §3.1 — RoundWinRules MUST NOT write to `payout_id_by_spin_type_total` | Unspecified | RESOLVED — §9.4 explicit constraint before Step A pseudocode |
| §3.2 — Variant override removal procedure | Unspecified | RESOLVED — §5.5.7 clearing procedure (4-layer pass for variant + audit log commit) |
| §3.3 — `_unattributed_*` fallback pid Layer 4 signal note | Unspecified | RESOLVED — §9.4 Step C `is_fallback_pid` field + note text; implementers MUST NOT suppress |

### §10.4 Items NOT in v5's scope (per addendum v5 §2)

- Operator-diagnostic framing in §1 + §9.1 — preserved from v3
- Layers 1-3 of integrity check — preserved from v3
- `console_diagnostic_complete` mechanism core — preserved; v5 only adds metadata and lint to the override mechanism
- §5.5.4 variant analyzer_features eager cascade — preserved from v3
- Phase 2 builds gate code; Phase 5 flips policy — preserved from v3
- Hash composition algorithm — preserved from v2
- 6-phase migration framework — preserved from v2
- Session-aware Layer 4 for trigger-session machines (Mirror approach a) — deferred to §8.14 / future session

---

## §11 Closing

v5 is a focused 7-issue revision of v4 that:

1. **Fixes the Layer 4 trigger-session false-positive** (§9.4) with the Skip approach: machines with `trigger_session_pattern != null` get `layer4_applicable: false` and skip Step B. Manifest validation rule 11 enforces consistency. Trade-off is documented: ~17+ trigger-session machine families lose Layer 4 coverage; they rely on Layers 1-3 only. The Mirror approach (a) is documented as a future option in §8.14.

2. **Formalizes Day-1 verification as item 0 of Phase 3 deliverables** (§6.3.3), closing the Critic v4 Q6/E6 procedural gap where the verification step was buried in prose and skippable. Item 0 gates items 1-9. Failed candidates become "Day-2 pending QA." Estimated cost ~10 min total.

3. **Closes the override organizational footgun** (§5.5.7) with three additions: required override metadata (`override_set_at`, `override_set_reason`, `override_set_by`), a specified override-clearing procedure (4-layer pass for the variant + audit log commit), and a quarterly QA review process with a stale-override lint rule in `manifest_lint.py`.

4. **Specifies Layer 4 perf** (§9.4): ~3s per machine; full fleet pull ~20 min sequential; 0s for trigger-session machines (skipped); wall-clock reduced by per-machine parallelism.

5. **Explicitly constrains RoundWinRules** from writing to `payout_id_by_spin_type_total` (§9.4), closing the Validator v4 §3.1 spec clarification.

6. **Documents the `_unattributed_*` Step C behavior** (§9.4): fallback pid mismatches are additive evidence of Layer 2 failure, not false positives. Implementers must not suppress them.

The proposal preserves v2's validated parts (hash composition, manifest schema baseline, Plugin Protocol, 6-phase migration framework), v3's operator-diagnostic framing (§1, §9.1), v3's Layers 1-3 (§9.2), and v4's Step A/B/C independent rawdata cross-check (§9.4). The 7 v5 changes are surgical and targeted.

Expected next step: Critic v5 + Validator v5 in parallel (per addendum v5 §4). Critic v5 verifies the 4 Concerns (A/B/C/D) are addressed structurally and the 3 polish gaps closed. Validator v5 re-walks key cases, specifically Layer 4 v5 against a trigger-session machine (M14 or M15) to verify the Skip approach actually prevents the false-positive, and variant override-clearing scenarios.

---

```
arch-designer complete.
- Version: v5
- Alternatives explored: 3 (A v5 recommended; B rejected — no per-machine completeness signal or rawdata cross-check; C rejected — no sharing, incompatible with variant cascade)
- Recommended: Alternative A v5 — per-machine manifests + sliced analyzer + operator-diagnostic 4-layer integrity check (Layer 4 rawdata cross-check with trigger-session Skip approach) + Day-1 strict candidates formally gated via §6.3.3 item 0 + variant completeness cascade with override metadata + quarterly QA + lint rule
- Hash composition: per-(machine, mode) effective_analyzer_version = sha256(base_hash || sorted(feature_hashes_M_uses) || mode)[:12] (unchanged from v2/v3/v4)
- Migration phases: 6 (1 foundation+globals, 2 slice-analyzer+forcing-function+gate-code-v5-Layer4-with-trigger-session-skip, 3 manifests+clean-break+46-Day1-candidates-gated-by-item0, 4 frontend-registry, 5 policy-flip-engages-day1-for-46-machines, 6 optional-consolidation)
- v5 issues addressed: 7/7 (① trigger-session Layer4 false-positive Skip approach / ② Day-1 verification item 0 gating / ③ override metadata+quarterly-QA+lint / ④ Layer4 perf estimate / ⑤ RoundWinRules constraint / ⑥ override-clearing procedure / ⑦ Step C _unattributed_* note)
- Out-of-scope items: 14 (§8.1-§8.13 unchanged + §8.14 session-aware Layer 4 for trigger-session machines)
- Open questions for Wave 3 v5: 2 (§7.1 future session-aware Layer 4 Mirror approach / §7.2 quarterly QA review ownership)
- Output: session_artifacts/_arch/04_architecture_proposal_v5.md
```
