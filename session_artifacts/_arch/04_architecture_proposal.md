# Architecture Proposal — rawdata → analyzer → console pipeline (Wave 2)

> Wave 2 deliverable from `arch-designer`. Synthesizes Wave 1 findings
> (`01_pipeline_map.md` mapper, `02_taxonomy.md` taxonomist,
> `03_coupling_audit.md` coupling-auditor) into a concrete proposal.
> Markdown only — no code edits, no implementation. Per
> `.claude/agents/arch-designer.md`: 2-3 alternatives mandatory,
> migration plan mandatory with rollback, every decision cites Wave 1
> evidence.
>
> **Date**: 2026-05-15
> **Brief**: `session_artifacts/_arch/00_brief.md`
> **Repo root**: `User_Managerment_GPT/`

---

## §1 Problem statement

The production console pipeline today is structurally sound at the
heavy edges — `create_app` factory is shared by both consoles
(`01 §4` verdict "thin shell"); `parse_chunk_response`,
`chunk_index`, `rawdata_index` are single-sourced; frontend bundle
serves both real (8877) and virtual (8878). **The architectural rot
is concentrated at the version-stamping layer**, not in the main
analyzer/render path.

Five concrete pain points, each cited from Wave 1:

1. **Universal `analyzer_version` stamp invalidates 1007 (machine,
   mode) pairs on any byte change** —
   `compute_analyzer_version()` in
   `fresh_slotlab/player_impact_analyzer.py:2141` SHA256s the entire
   8,176-line analyzer source. Per `03 §3.3` live DB measurement:
   2030 completed runs across **1007 distinct (machine, mode) pairs**
   get flagged `stale_analyzer` by `/api/reports/stale-count`
   (`app.py:5694`) the moment any comment-only edit lands. The
   docstring at `:2147` even endorses this: "Intentionally broad: any
   edit to player_impact_analyzer.py — including comments — changes
   the hash." The brief's headline user goal (§4) — "添加新机台,有
   一些新 feature,更新分析器,会不会导致我所有的 report 失效?但有
   没有失效必要?" — names exactly this surface as the primary
   architectural defect.

2. **Schema renames silently break 17 frontend renderers** — `03 §4.3`
   tabulates ~30 schema fields × 17 renderers (`app.js` 14 + `pure.js`
   3). Only the `payouts_by_spin_type` family has frontend fallback
   (added in `00 §3` commit `7e5fe32`). Every other field rename
   (e.g. `8411c9d`'s `hit_rate_pct → hit_rate`) would have broken
   `.toFixed(3)` on `undefined` if not specifically guarded — and no
   contract or test prevents the next analyzer field rename from
   doing the same to a different field. `02 §6.4` and `01 §6` both
   surface this as a load-bearing contract with no versioning.

3. **Real-fleet hash is upstream, virtual hash is local — two
   universes with no shared abstraction** — `03 §3.4` measured that
   `configs/machines.json`'s 421 entries get their `codeSummaryMd5`
   from the upstream `/MachineConfigMd5` endpoint
   (`machine_variants.py:336`), and `01 §3` confirms
   `compute_code_md5(machine_name)` in
   `slot_designer/core/backend/machine_version.py:109` only feeds the
   6 virtual entries. **Editing `core/engine/symbol.py` flips 6
   virtual hashes and 0 real hashes** (`03 §5.1`). This nuance has
   to be respected by any migration design — touching the real-fleet
   md5 path requires upstream changes outside this team's scope.

4. **Duplication concentrated in md5 + summary-patch + session-CI** —
   `01 §4` itemizes six exact duplications between real and virtual:
   two md5 lookup implementations, two summary md5-write sites, two
   session-CI helpers, two t-critical tables, two inference-trigger
   hooks. Crucially this is **not** in the heavy path (analyzer +
   render are correctly shared); it's in the supplementary glue. Fix
   here pays compounding interest because every new identity field
   added in the future would otherwise need to land in both forks
   (per memory `feedback_md5_granularity_and_stamping.md` lesson:
   "if your analyzer has N entry points that invoke the same
   summary-writing function, they all need the identity-stamping
   patch").

5. **`RAWDATA_ROOT` module global + 33 analyzer module globals are
   latent suicide bombs** — `03 §4.1` enumerates 11 references to
   `RAWDATA_ROOT` in `app.py` (defended only by `rawdata_root if
   rawdata_root is not None else RAWDATA_ROOT` fallback at 4 sites:
   `695, 1064, 3187, 5318`) plus 33 module globals in the analyzer,
   plus `virtual_app.py:201`'s import-time `app = build_virtual_app()`
   side effect. Per memory
   `feedback_subprocess_import_suicide_and_module_globals.md` this
   class of bug masquerades as healthy in tests where fixtures
   co-locate the wrong-and-right paths on the same tmp_path, and
   only manifests in production when virtual and real are split.

**Cross-cutting evidence**: `02 §6.5` projects the **available**
blast-radius reduction at roughly 10× for most change classes if
plugin lines are drawn along the natural co-clusters from `02 §6.2`.
This proposal aims to realize that reduction while preserving the
brief's constraint (`00 §5.1`) that **no existing report regenerates
during migration**.

---

## §2 Design alternatives

Three alternatives, listed from least to most invasive. All three
keep `parse_chunk_response`, `chunk_index`, `rawdata_index`, and the
frontend bundle exactly where they are — those are correctly shared
per `01 §3` and the brief's §2 audit-only verdict.

The choice axis is **how aggressively to slice
`compute_analyzer_version`** (the primary blast surface per `03 §6`
#1) and **where the plugin boundary lives** (manifests vs registries
vs inline-stamps).

### §2.1 Alternative A — Granular analyzer version + manifest-declared
plugins (recommended)

**Core idea**: Replace the single `compute_analyzer_version()` hash
with **a composition of per-feature hashes** of the analyzer's
internal sub-modules. Each machine's manifest declares the
features/plugins it uses; the per-machine
`effective_analyzer_version` is the sum of (base_core_hash +
sorted_feature_hashes_M_uses). A change to one feature module
invalidates only machines listing it.

**File tree sketch** (new files marked `(new)`):

```
fresh_slotlab/
  player_impact_analyzer.py        # main() + parse_chunk_response orchestration (slim)
  analyzer/                        # (new) sliced feature modules
    __init__.py
    core/                          # always-invoked code (universal)
      base_pipeline.py
      chunk_aggregation.py
      summary_writer.py
    features/                      # optional, plugin-able analysis features
      payouts_by_spin_type.py      # the 729a6ca / 8411c9d / 4cbcab2 surface
      reel_marginal_by_spin_type.py
      bankruptcy_simulation.py
      bonus_chain_dynamics.py
      collect_mechanic.py
      multiplier_profile.py
      ...
    versioning.py                  # (new) hash composition
  round_classification.py          # unchanged
  round_win.py                     # unchanged (existing rule pattern, formalized)
  chunk_index.py                   # unchanged
  rawdata_index.py                 # unchanged

slot_designer/configs/
  machine_plugin_manifest.json     # (new) per-machine plugin declaration

slot_designer/machines/<M>/
  manifest.json                    # (new) per-machine; cites which plugins this machine uses
  plugins/feature.py               # (existing, virtual-only path; unchanged)
```

**Key Protocol interfaces** (Python ABC sketch):

```python
# fresh_slotlab/analyzer/versioning.py (NEW)
from typing import Protocol, Iterable
import hashlib

class AnalyzerFeature(Protocol):
    """A versioned slice of analyzer functionality.

    Each feature module must expose:
      - FEATURE_ID: stable string label (e.g. "payouts_by_spin_type")
      - SCHEMA_KEYS: tuple of summary-JSON keys this feature produces
      - SCHEMA_VERSION: int, bumped on breaking rename
      - extract(parse_state, chunk_dict) -> dict[summary_key, value]
      - compute_hash() -> str: short hex digest of THIS module's code only
    """
    FEATURE_ID: str
    SCHEMA_KEYS: tuple[str, ...]
    SCHEMA_VERSION: int

    def extract(self, parse_state, chunk_dict) -> dict: ...
    def compute_hash(self) -> str: ...

def compute_effective_analyzer_version(
    *,
    base_hash: str,
    feature_hashes: dict[str, str],   # feature_id → hash
    machine_features: list[str],      # feature_ids this machine declares
) -> str:
    """Compose a per-machine analyzer version.

    Replaces compute_analyzer_version() at player_impact_analyzer.py:2141.
    """
    h = hashlib.sha256()
    h.update(base_hash.encode("ascii"))
    for fid in sorted(set(machine_features)):
        h.update(b"\x00")
        h.update(fid.encode("ascii"))
        h.update(b"\x00")
        h.update(feature_hashes.get(fid, "").encode("ascii"))
    return h.hexdigest()[:12]
```

**Manifest schema** (`slot_designer/configs/machine_plugin_manifest.json`
or per-machine `slot_designer/machines/<M>/manifest.json`):

```json
{
  "machine_id": "M31",
  "schema_tier": "vanilla",
  "spin_type_convention": { "paid": [43], "bonus": [44] },
  "feature_tags": ["FreeSpin"],
  "round_win_rules": [],
  "classification_primitives": ["default"],
  "analyzer_features": [
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "bankruptcy_simulation"
  ],
  "selector_type": null,
  "bcm_target_feature": null,
  "trigger_session_pattern": null
}
```

**Pros** (grounded in Wave 1):

- **Realizes the blast-radius reduction `02 §6.5` projects**: the
  `02 §6.5` table shows changes to `payouts_by_spin_type` go from
  421 → ~45 affected (SC-Vanilla unaffected); BCM cleanup rule goes
  421 → 28 (S-BCM-21k only); theme tweak on M21 Buffalo goes 421 →
  1. Worked example in §4 below.
- **Backward-compatible by construction**: manifests are additive
  (every machine declares its features); old reports keep their
  legacy `analyzer_version` and continue to render via existing
  fallback rules. No regen forced (satisfies brief §5.1).
- **Formalizes the existing `RoundWinRule` pattern** (`round_win.py:102`
  RULE_REGISTRY, `02 §3.5.1` shows 13 of 421 machines registered)
  rather than introducing a parallel one. Memory
  `reference_round_win_rule_architecture.md` validates the pattern.
- **Aligns with `02 §6.2` natural seams**: the 9 plugin candidates
  identified by the taxonomist (`plugin-vanilla-paytable`,
  `plugin-bcm-cycle`, `plugin-wild-nudge`, etc.) map directly onto
  `AnalyzerFeature` instances.
- **Solves md5 duplication** (`01 §4`) by making the
  `effective_analyzer_version` calculation a shared primitive used
  by both real and virtual stamping paths.

**Cons**:

- **Surface area increase**: ~10 new feature modules require careful
  identification of cut-points in the existing 8,176-line monolith.
  Risk of accidentally splitting a feature across two modules and
  losing co-evolution.
- **Manifest accuracy is now load-bearing**: an under-declared
  manifest (machine claims "no `wild_nudge`" but actually has ST=36
  + ReMarks=move rounds) → wrong-but-passes-checks. Validator phase
  (Wave 3) needs to verify manifests via rawdata scan.
- **Existing reports on disk show `analyzer_version` as a single
  string**; the new field shape adds `effective_analyzer_version`
  alongside without breaking the old. Frontend `_renderRwtreeCell`
  at `app.js:1895` needs a dual-read path (one new schema field).

**Migration cost estimate**: **MEDIUM**. Slicing the monolith is the
biggest line-of-code lift; the manifest infrastructure and hash
composition are straightforward. Backward-compat preserved by
keeping `compute_analyzer_version()` as a fallback for un-manifested
machines during phase 1 of migration.

### §2.2 Alternative B — Lightweight per-feature SCHEMA_VERSION
sidecar (smallest change)

**Core idea**: Leave `compute_analyzer_version()` exactly as it is
(SHA256 of whole file). Add a **second** identity field —
`schema_versions: {feature_id: int}` — into the summary JSON.
Frontend renderers consult this map for fallback decisions instead
of inferring from field presence/absence. Don't slice the analyzer.
Don't introduce per-machine manifests.

**File tree sketch**:

```
fresh_slotlab/
  player_impact_analyzer.py        # add SCHEMA_VERSIONS dict at top
  schema_versions.py               # (new) static const map: feature_id → int

src/web_console/frontend/
  app.js                           # add explicit version-check before renderer dispatch
  pure.js                          # same
```

**Key TypeScript interface sketch** (frontend side):

```javascript
// src/web_console/frontend/schema_versions.js (NEW)
// Frontend declares which schema versions each renderer supports
const RENDERER_SCHEMA_SUPPORT = {
  renderPayoutsBySpinType: {
    feature: "payouts_by_spin_type",
    minVersion: 1,
    maxVersion: 2,
    fallbacks: {
      1: {hit_rate: "hit_rate_pct/100", rtp_contribution_pp: "rtp_pp"}
    }
  },
  renderSpinTypeBreakdown: { feature: "spin_type_breakdown", minVersion: 1, maxVersion: 1, fallbacks: {} },
  // ... 17 entries
};
```

Analyzer-side: add `SCHEMA_VERSIONS = {"payouts_by_spin_type": 2,
"reel_marginal_by_spin_type": 1, ...}` constant; write into every
summary.json's `schema_versions` block.

**Pros** (grounded in Wave 1):

- **Minimal disruption**: zero changes to analyzer structure, zero
  changes to manifest infrastructure. Just two new const maps.
- **Solves pain point #2** (schema rename silence — `03 §4.3`):
  every renderer becomes explicit about its supported versions and
  fallbacks, so the next rename can't silently break.

**Cons**:

- **Does NOT solve pain point #1** (the 1007-pair blast on
  `analyzer_version`). Comment-only edit still invalidates the same
  1007 pairs. Brief §4 user goal "添加新 feature 会不会导致所有
  report 失效" remains unfixed.
- **Does NOT solve pain point #4** (md5/summary-patch duplication
  per `01 §4`). The two implementations stay.
- **Manifest-less means no per-machine declaration of features**:
  the natural seams from `02 §6.2` go unused. Adding a new feature
  to one BCM machine still updates analyzer source → 1007-pair
  blast.
- **Defers the real problem**. `02 §6.5` projects 10× available
  reduction; B leaves it on the table.

**Migration cost estimate**: **LOW**. ~50 lines of analyzer changes
+ frontend version-check refactor (~200 lines). Could be done in
1-2 commits.

### §2.3 Alternative C — Full per-machine analyzer plugin tree (most
aggressive)

**Core idea**: Move ALL per-machine logic out of the analyzer
monolith into `slot_designer/machines/<M>/analyzer_plugin.py` files.
Each machine has its own complete `parse_chunk_response` plugin that
inherits a thin `BaseChunkAnalyzer` class. The fleet-shared
analyzer becomes just the orchestration loop + base class.

**File tree sketch**:

```
fresh_slotlab/
  player_impact_analyzer.py        # ~500 lines: orchestration loop only
  base_chunk_analyzer.py           # (new) abstract base class with
                                   # hook methods for every analysis stage
  default_analyzer_plugin.py       # (new) the legacy behavior, used for
                                   # 408 machines without explicit plugins

slot_designer/machines/<M>/
  analyzer_plugin.py               # (new) per-machine inherits BaseChunkAnalyzer,
                                   # overrides only what differs
```

**Key Protocol interface**:

```python
# fresh_slotlab/base_chunk_analyzer.py (NEW)
class BaseChunkAnalyzer(ABC):
    SCHEMA_KEYS_PRODUCED: tuple[str, ...]

    @abstractmethod
    def parse_chunk(self, raw_response: list, ctx: dict) -> dict: ...

    def extract_round_win(self, round_dict: dict, ctx: dict) -> float: ...
    def extract_round_payouts(self, round_dict: dict, ctx: dict) -> dict: ...
    def classify_round(self, round_dict: dict) -> str: ...
    def emit_summary_block(self, key: str, accumulator: dict) -> dict: ...
    def compute_hash(self) -> str: ...
```

**Pros**:

- **Maximum blast-radius reduction**: a per-machine plugin change
  literally affects only that machine.
- **Maximum per-machine clarity**: M279's specifics live in
  `machines/M279/analyzer_plugin.py`, not scattered through 8,000
  lines of monolith.

**Cons** (grounded in Wave 1):

- **Reuse becomes hard**: the existing `RoundWinRule` registry
  (`02 §3.5.1`, 13 machines × shared rule types) explicitly carves
  out "share rule code; vary parameters" — moving every machine to
  its own plugin tree breaks that cleanly-shared abstraction. The
  taxonomist's `02 §4.1` co-cluster observation #5 ("28 schema-BCM
  machines all have BCM in feature tags") points the OTHER way —
  these machines share enough that per-machine isolation
  overshoots.
- **Onboarding cost balloons**: brief §6 success criterion is
  "supports cheap onboarding" — but plain-vanilla SC-Vanilla
  machines (45 machines per `02 §4.2`) would each need a plugin
  file even though they share 100% behavior. That violates "exploit
  similarity" (brief §1).
- **Hash composition becomes per-machine**: every plugin file is
  its own hash input. New plugin code on M260 doesn't affect M21,
  but M260's full plugin file becomes load-bearing for blast tests.
  Risk of plugin drift increases (no shared code path = no shared
  test surface).
- **Migration is enormous**: 408 machines that today run on default
  legacy paths would each need a plugin shim or a "this machine
  uses default" sentinel. Backward-compat for existing reports
  requires extensive shim work.
- **Memory `feedback_no_parallel_panel_impl.md`** explicitly warned
  against per-machine parallel impl; this alternative goes the
  other direction.

**Migration cost estimate**: **HIGH**. ~50 plugin files × ~200
lines each = 10k LOC of new code. Backward compat shims and
default-routing machinery add 1-2k more.

### §2.4 Comparison table

| Criterion | A (granular version + manifest) | B (sidecar version sidecar) | C (per-machine plugins) |
|---|---|---|---|
| Solves `analyzer_version` blast (`03 §3.3`) | YES (composes per-machine) | NO (whole-file hash stays) | YES (per-machine isolated) |
| Solves schema-rename silence (`03 §4.3`) | YES (versioned features) | YES (explicit version map) | YES (per-machine schema) |
| Solves md5/summary-patch dup (`01 §4`) | YES (shared `effective_version` primitive) | NO (preserves dup) | PARTIAL (still need shared base class hash) |
| Solves `RAWDATA_ROOT` global (`03 §4.1`) | OUT-OF-SCOPE (handled separately in §6) | OUT-OF-SCOPE | OUT-OF-SCOPE |
| Exploits `02 §6.2` co-clusters | YES (`feature_tags` in manifest) | NO | OVERSHOOTS (per-machine, ignores clusters) |
| Backward-compat for 393+ machines (`00 §5.1`) | YES (manifest defaults; old summary keys stay) | YES (additive) | HARD (shim required for 408 machines) |
| Onboarding cost (brief §6 "cheap onboarding") | LOW (drop manifest + optional plugin) | LOW (nothing to add) | HIGH (force plugin file per machine) |
| LOC delta estimate | +2,000 (slice + manifest infra) | +250 (const maps + version-check) | +12,000 (50 plugins × 200 + shims) |
| Migration risk | MEDIUM (slicing is the hardest part) | LOW | HIGH (touches every machine) |
| Realizes `02 §6.5` 10× reduction | YES | NO | YES-but-overshoots |

---

## §3 Recommended design — Alternative A

**Pick: Alternative A** (granular analyzer version + manifest-declared plugins).

**Reasoning, cited from Wave 1**:

1. **A is the only alternative that solves all five pain points
   from §1** (B leaves #1, #4 unsolved; C overshoots on #4 and
   creates new problems). `03 §6 #1` ranks `compute_analyzer_version`
   the **maximum non-architectural blast** in the system; ignoring
   it (B) means not addressing the brief's headline user goal
   (`00 §4`).

2. **A respects the existing `RoundWinRule` shape** rather than
   creating a parallel system. `02 §3.5.1` shows 13 machines with
   2 rule types already use this exact pattern; memory
   `reference_round_win_rule_architecture.md` documents its success.
   The new `AnalyzerFeature` Protocol is a sibling concept, not a
   replacement — they coexist (rules drive round-level extraction;
   features drive summary-level aggregation).

3. **A matches the data taxonomy's natural seams.** `02 §4.2`
   identifies 6 super-clusters (SC-Vanilla, SC-BCM-Modern,
   SC-TopDollar, SC-WheelSelector, SC-LockRespin-50, SC-MoveNudge)
   covering ~213/255 non-variant machines. `02 §6.5` quantifies the
   reduction with concrete worked examples. A's manifest realizes
   exactly the clustering the taxonomist found.

4. **A is the lowest-risk way to slice the monolith.** Per-feature
   modules can be lifted out one at a time (phase 2 of migration
   below); each lift is verifiable against a frozen golden report.
   C's per-machine plugin requires touching every machine before
   anyone benefits.

5. **A solves md5/summary-patch duplication as a side effect.**
   `01 §4` flags six duplications between real and virtual; A's
   `compute_effective_analyzer_version` becomes the shared primitive
   that replaces both, and the manifest provides the single source
   of truth that both consoles consult.

6. **A preserves the brief's explicit constraint `00 §5.4`** —
   "Adding a new machine should affect O(1) hashes, not O(N=393)".
   A's hash composition (proven mathematically in §4 below) achieves
   exactly that.

7. **C is intentionally rejected** for the reasons in §2.3 cons:
   onboarding regression (brief §1 + §6), reuse breakdown, and the
   memory `feedback_no_parallel_panel_impl.md` lesson about avoiding
   parallel-impl-per-X. A's 9 cross-cutting plugins are a better fit
   than 50 per-machine plugins.

The remaining sections (§4-§6) specify A in detail.

---

## §4 Hash composition rules

### §4.1 The new composition algorithm

There are **three independent hash inputs** that compose into the
effective per-machine version. Renaming `compute_analyzer_version`
to `compute_base_analyzer_version` makes the contract explicit.

```python
# fresh_slotlab/analyzer/versioning.py (NEW; replaces the implicit
# whole-file hash currently in player_impact_analyzer.py:2141)

def compute_base_analyzer_version() -> str:
    """SHA256 of fresh_slotlab/analyzer/core/*.py only.

    Replaces the whole-file hash. Covers only universally-invoked
    code (orchestration, summary writer, chunk aggregation).
    Excludes feature modules (those get their own hashes).
    """

def compute_feature_hashes() -> dict[str, str]:
    """For each module in fresh_slotlab/analyzer/features/*.py,
    return {feature_id: short_hex_hash}. One pass at startup,
    cached in-memory.
    """

def compute_effective_analyzer_version(
    *, base_hash: str, feature_hashes: dict[str, str],
    machine_features: list[str],
) -> str:
    """Per-machine: SHA256(base_hash + sorted(features_M_uses)).
    Stamped into summary.effective_analyzer_version.
    Length: 12 hex chars (same as legacy)."""
```

The **per-machine effective version** is:
```
effective_analyzer_version(M) =
    sha256( base_hash ||
            "\x00".join(f"{fid}={feature_hashes[fid]}" for fid in sorted(manifest[M].analyzer_features))
          )[:12]
```

### §4.2 Worked examples — invalidation radius reduction

Assume the analyzer is sliced as follows (validator phase will
finalize the cut-points; this is a plausible illustrative split):

| Module | Used by | Member count (from `02`) |
|---|---|---|
| `core/base_pipeline.py` | all 421 machines | 421 (universal) |
| `core/chunk_aggregation.py` | all 421 | 421 |
| `core/summary_writer.py` | all 421 | 421 |
| `features/payouts_by_spin_type.py` | all 421 (current behavior; declared in every manifest) | 421 |
| `features/reel_marginal_by_spin_type.py` | machines with >1 SpinType (~140 from `02 §3.1`) | 140 |
| `features/bankruptcy_simulation.py` | all 421 (universal KPI) | 421 |
| `features/bonus_chain_dynamics.py` | machines with bonus rounds (`02 §3.1` excluding ST-1A) | ~152 (= 206 - 54 ST-1A) |
| `features/collect_mechanic.py` | BCM machines (S-BCM-21k + bcm_pairings.json) | 30 |
| `features/multiplier_profile.py` | all 421 | 421 |
| `features/wild_nudge_classification.py` | machines with ST=36+move (`02 §3.5.2`) | 7 confirmed + variants |
| `features/cycle_peak_detection.py` | machines with `CollectCount` extra | ~35 (BCM-21k + adjacent) |
| `features/topdollar_settlement.py` | M12/M15/M90/M132 + variants (`02 §3.5.1`) | 17 |
| `features/wheel_selector_type2.py` | M273 + 84 variants + others (`02 §4.2 SC-WheelSelector`) | 96 |
| `features/bespoke_m21_buffalo.py` | M21 only (`02 §5.1`) | 1 |
| `features/bespoke_m260_buffs.py` | M260 only | 1 |
| `features/bespoke_m11_diamond.py` | M11 only | 1 |
| ... (12 heavy outliers total, `02 §5.1`) | ... | 1 each |

#### Worked example #1: comment-only edit to `features/bankruptcy_simulation.py`

- `feature_hashes["bankruptcy_simulation"]` flips.
- Every machine's manifest lists `bankruptcy_simulation` (universal KPI).
- Therefore: **all 421 machines'** `effective_analyzer_version` flips.
- **Same as today**. 1007 (machine, mode) pairs (`03 §3.3`) get flagged.
- **But**: with manifests in place, the *kind* of change that
  invalidates 421 is now narrow (universal feature only). The
  previous comment-only edit anywhere in the file did the same; now
  it's explicit which features are universal.

#### Worked example #2: rename a field inside `features/payouts_by_spin_type.py` (the `8411c9d`-class change)

- `feature_hashes["payouts_by_spin_type"]` flips.
- This feature is currently declared in every manifest (it produces
  a top-level summary key for all machines).
- Invalidation radius: **same as today (421)**.
- **But**: a per-machine opt-out (manifest says `analyzer_features:
  []` for that feature) would let you experiment on M31 alone. The
  current architecture has no such opt-out.

#### Worked example #3: add new BCM cleanup rule in `features/cycle_peak_detection.py`

- `feature_hashes["cycle_peak_detection"]` flips.
- Per manifest, only ~35 BCM machines declare this feature.
- Invalidation radius: **35 machines** (down from 421).
- **Reduction: 12×**. Matches the `02 §6.5` projection ("28 schema-BCM
  machines all have BCM in feature tags" + ~7 adjacents).

#### Worked example #4: theme tweak on M21 Buffalo in `features/bespoke_m21_buffalo.py`

- `feature_hashes["bespoke_m21_buffalo"]` flips.
- Only M21's manifest lists this feature.
- Invalidation radius: **1 machine**.
- **Reduction: 421×**. Matches `02 §6.5` worked-example bottom row.

#### Worked example #5: change to `core/base_pipeline.py` (orchestration loop change)

- `base_hash` flips.
- Every machine's `effective_analyzer_version` flips by construction.
- Invalidation radius: **421**.
- **This is the desired behavior**: core changes should still
  trigger fleet-wide validation. The change has to be substantive
  (not comment-only) because the slim core has fewer surface lines
  to edit, so accidental flips reduce.

### §4.3 Per-machine config_md5 and code_md5 (unchanged for real fleet; clarified for virtual)

The brief flagged `compute_code_md5` (`slot_designer/core/backend/machine_version.py:109`)
as the second-most-important hash. Per `03 §3.1`:

- **6 virtual machines** use `compute_code_md5` directly.
- **421 real-fleet machines** get `codeSummaryMd5` from upstream
  `/MachineConfigMd5`, not from local Python.

This proposal **does not change** either path's hash composition.
The proposal **does** make the dual-stamping unified at the
write-summary site (§5 below covers this).

The existing per-mode `compute_machine_md5_for_mode` (per memory
`feedback_md5_granularity_and_stamping.md`) stays as-is.

### §4.4 Hash composition map (text diagram, post-migration)

```
Source-file edit
   |
   v
 [a] fresh_slotlab/analyzer/core/*.py             ──> base_hash flips
 [b] fresh_slotlab/analyzer/features/<fid>.py    ──> feature_hashes[fid] flips
 [c] slot_designer/core/engine/*.py +             ──> compute_code_md5(machine) flips
     slot_designer/core/emitter/*.py                   (virtual machines only — 6 entries)
 [d] slot_designer/machines/<M>/plugins/**/*.py  ──> compute_code_md5(M) flips
                                                      (only THIS virtual machine)
 [e] slot_designer/machines/<M>/{spec,strips,    ──> compute_config_md5 flips
       weights}                                       (only THIS virtual machine + mode)
 [f] slot_designer/configs/machine_plugin_       ──> effective_analyzer_version flips
       manifest.json (or per-machine manifest.json)    (machines whose manifest changed)
 [g] upstream /MachineConfigMd5 emission         ──> machines.json upstream md5 flips
                                                      (real machines only)
   |
   v
 effective_analyzer_version(M) =
     sha256(base_hash || features_M_used)[:12]
   |
   v
 Stamped into:
   * summary.effective_analyzer_version  ← NEW field
   * summary.analyzer_version            ← legacy field, kept for backward-compat
                                            equals compute_legacy_analyzer_version()
                                            (whole-file sha256, deprecated)
   * runs.effective_analyzer_version  ← state/console/console.db (new col)
   * reports/<M>/mode_<N>/index.json[*].effective_analyzer_version
```

**Backward-compat invariant**: every report on disk today has the
old `analyzer_version` field, no `effective_analyzer_version`.
Frontend reads `effective_analyzer_version` first, falls back to
legacy `analyzer_version`. Per `03 §4.3` style fallback pattern.

---

## §5 Plugin / extension contract

### §5.1 Three plugin axes (each independent)

Per `02 §3` axes and `01 §3` boundary table, the natural plugin axes
are:

| Axis | Existing artifact | New contract |
|---|---|---|
| Round-level extraction | `RoundWinRule` ABC at `round_win.py:102` + RULE_REGISTRY at `:423` | **Formalized as-is**; manifest declares which rules a machine uses |
| Summary-level aggregation | (today: inline in `parse_chunk_response` + `main()`) | **NEW `AnalyzerFeature` Protocol** (§5.2) |
| Frontend rendering | (today: 17 inline renderers in `app.js`; no contract) | **NEW renderer registration** (§5.3) |

### §5.2 `AnalyzerFeature` Protocol — Python ABC sketch

```python
# fresh_slotlab/analyzer/features/_base.py (NEW)
from abc import ABC, abstractmethod
from typing import Any
import hashlib
from pathlib import Path

class AnalyzerFeature(ABC):
    """Versioned, opt-in slice of analyzer functionality.

    Each subclass module corresponds to one feature module file
    under fresh_slotlab/analyzer/features/. The file's own bytes
    are hashed for compute_hash().

    Contract:
      - FEATURE_ID: stable string. Used as manifest key. Never
        renamed (rename = new feature_id = manifest migration).
      - SCHEMA_KEYS: tuple of keys this feature WRITES into
        the summary dict. The orchestrator at main() reads
        SCHEMA_KEYS during summary assembly to know what
        keys to expect.
      - SCHEMA_VERSION: int, bumped on breaking field rename.
        Frontend renderer support is gated by this.
      - extract(parse_state, chunk_dict) -> dict[summary_key, value]:
        feature-specific extraction; produces values for SCHEMA_KEYS.
        Called once per chunk in parse_chunk_response.
      - reduce(prev_acc, this_acc) -> next_acc: merge accumulators
        across chunks in main()'s aggregation block.
      - emit(final_acc, summary) -> None: write final values into
        the summary dict at SCHEMA_KEYS paths.
      - compute_hash() -> str: SHA256 of feature module's bytes,
        first 12 hex chars. Default impl reads __file__.
    """
    FEATURE_ID: str = ""
    SCHEMA_KEYS: tuple[str, ...] = ()
    SCHEMA_VERSION: int = 1

    @abstractmethod
    def extract(self, parse_state: dict, chunk_dict: dict) -> dict:
        ...

    @abstractmethod
    def reduce(self, prev_acc: Any, this_acc: dict) -> Any:
        ...

    @abstractmethod
    def emit(self, final_acc: Any, summary: dict) -> None:
        ...

    @classmethod
    def compute_hash(cls) -> str:
        src = Path(__file__).resolve()
        return hashlib.sha256(src.read_bytes()).hexdigest()[:12]
```

**Example skeleton — extracting `payouts_by_spin_type` (the `729a6ca`
surface, currently inline at `player_impact_analyzer.py` ~6481):

```python
# fresh_slotlab/analyzer/features/payouts_by_spin_type.py (NEW)
from ._base import AnalyzerFeature

class PayoutsBySpinTypeFeature(AnalyzerFeature):
    FEATURE_ID = "payouts_by_spin_type"
    SCHEMA_KEYS = ("player_impact.payouts_by_spin_type",)
    SCHEMA_VERSION = 2  # bumped on the 8411c9d rename

    def extract(self, parse_state, chunk_dict):
        # Reads chunk rounds via parse_state.rounds_iter,
        # produces {(st_label, pid): {hits, win}}.
        ...

    def reduce(self, prev_acc, this_acc):
        # Sum dicts; idempotent.
        ...

    def emit(self, final_acc, summary):
        # Build the {ST{N}_{behavior}: [pid_row, ...]} structure
        # at the new schema (post-8411c9d); writes into
        # summary["player_impact"]["payouts_by_spin_type"].
        ...
```

### §5.3 Frontend renderer plugin — TypeScript interface sketch

```typescript
// src/web_console/frontend/renderers/_types.d.ts (NEW)
interface RendererPlugin {
  readonly id: string;                    // matches FEATURE_ID
  readonly schemaKey: string;             // e.g. "player_impact.payouts_by_spin_type"
  readonly minSchemaVersion: number;
  readonly maxSchemaVersion: number;
  readonly fallbackRules?: Record<number, FallbackMap>;
  render(summary: object, host: HTMLElement, ctx: RendererCtx): void;
}

interface FallbackMap {
  // For old reports lacking new fields, map old->new fieldname or transformation.
  // e.g. { hit_rate: { source: "hit_rate_pct", transform: "divide_100" } }
}

// Registry replacing the implicit inline calls in _paintAnalysisFromSummary
const RENDERER_REGISTRY: Record<string, RendererPlugin> = {
  "payouts_by_spin_type": {
    id: "payouts_by_spin_type",
    schemaKey: "player_impact.payouts_by_spin_type",
    minSchemaVersion: 1,
    maxSchemaVersion: 2,
    fallbackRules: {
      1: {
        hit_rate: { source: "hit_rate_pct", transform: "divide_100" },
        rtp_contribution_pp: { source: "rtp_pp", transform: "identity" }
      }
    },
    render: renderPayoutsBySpinType  // existing app.js:5026
  },
  // ...
};
```

The painter `_paintAnalysisFromSummary` at `app.js:6676` iterates the
registry instead of hardcoding renderer names. Reading the new
`schema_versions` field on the summary (added by the analyzer)
selects the right fallback rule.

This **directly addresses memory `feedback_no_parallel_panel_impl.md`**
("加同类 UI panel 前必须 reuse sibling renderer 不许 parallel
impl"): the registry forces every new panel to declare which
renderer plugin it pairs with, and the schema-version gate prevents
parallel hit_rate_pct vs hit_rate divergence.

### §5.4 Per-machine `round_win_rule` plugin — formalize existing pattern

The existing pattern (`round_win.py:102` ABC, RULE_REGISTRY at `:423`)
**stays unchanged**. The manifest now references rule_ids:

```json
{
  "machine_id": "M274",
  "round_win_rules": ["bcm_cycle_anchor_m274"]
}
```

The `load_rules_for_machine` function at `round_win.py:557` already
reads `applies_to` from `configs/machine_round_win_rules.json` — the
new manifest provides a forward-compatible alternative read path,
where the manifest's `round_win_rules` array can either be:

- **Empty**: machine uses no rules (default; 408 machines today).
- **List of rule_ids**: read from the central
  `machine_round_win_rules.json` (existing infra preserved).

Migration: phase 2 below introduces the manifest; phase 3
optionally migrates `machine_round_win_rules.json` into per-machine
manifests for surface-area reduction.

### §5.5 Per-machine manifest format

**File location options** (validator phase to pick):

- **Option 5.5a**: Central `slot_designer/configs/machine_plugin_manifest.json`,
  one JSON object per machine.
  - Pro: single file scan; no per-machine boilerplate.
  - Con: large file; conflicts on multi-machine PRs.
- **Option 5.5b**: Per-machine `slot_designer/machines/<M>/manifest.json`.
  - Pro: co-located with machine spec/weights; per-machine PR
    isolation.
  - Con: 421 manifest files; scan cost on console boot.
- **Option 5.5c** (recommended): **hybrid** — central file holds
  defaults per super-cluster (`02 §4.2`); per-machine file holds
  overrides only. Empty per-machine file = inherit cluster defaults.

**Schema** (machine-level manifest):

```json
{
  "machine_id": "M274",
  "schema_tier": "bcm-21k",
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
  "selector_type": null,
  "bcm_target_feature": "ListRewardWheel",
  "trigger_session_pattern": null
}
```

**Cluster-default schema** (central):

```json
{
  "_clusters": {
    "SC-Vanilla": {
      "analyzer_features": [
        "payouts_by_spin_type", "reel_marginal_by_spin_type",
        "bankruptcy_simulation", "multiplier_profile"
      ],
      "feature_tags": ["Plain"],
      "round_win_rules": []
    },
    "SC-BCM-Modern": {
      "analyzer_features": [
        "payouts_by_spin_type", "reel_marginal_by_spin_type",
        "bankruptcy_simulation", "bonus_chain_dynamics",
        "collect_mechanic", "multiplier_profile",
        "cycle_peak_detection"
      ],
      "feature_tags": ["BCM"],
      "round_win_rules": []
    },
    "SC-TopDollar": {
      "analyzer_features": [
        "payouts_by_spin_type", "bankruptcy_simulation",
        "topdollar_settlement", "multiplier_profile"
      ],
      "feature_tags": ["Selector"],
      "round_win_rules": ["topdollar_selector_settlement"]
    }
    // ... 6 super-clusters
  },
  "_per_machine": {
    "M274": { "cluster": "SC-BCM-Modern", "overrides": {
      "analyzer_features": ["+bespoke_m274_cycle_anchor"],
      "round_win_rules": ["bcm_cycle_anchor_m274"]
    }},
    "M21": { "cluster": null, "overrides": {
      "analyzer_features": [
        "payouts_by_spin_type", "bankruptcy_simulation",
        "multiplier_profile", "bespoke_m21_buffalo"
      ],
      "feature_tags": ["Plain"]
    }},
    "M260": { "cluster": "SC-BCM-Modern", "overrides": {
      "analyzer_features": ["+bespoke_m260_buffs"]
    }}
    // ... 421 entries (most just say "cluster": "<sc>", no overrides)
  }
}
```

**Validation rules** (validator phase finalizes; spec sketch):

1. Every machine in `configs/machines.json` must have an entry
   (cluster reference or explicit overrides).
2. Every `analyzer_feature` ID listed must correspond to a real
   module under `fresh_slotlab/analyzer/features/`.
3. Every `round_win_rule` ID listed must be defined in
   `configs/machine_round_win_rules.json` and contain this machine
   in `applies_to`.
4. **Sanity check against rawdata**: if rawdata is available for
   this machine, scan the chunks and verify:
   - Declared `spin_type_convention` matches observed (Axis 1).
   - If `wild_nudge_classification` is NOT listed but rawdata has
     ST=36+ReMarks=move, flag as MANIFEST_DRIFT warning.
   - If `cycle_peak_detection` is NOT listed but rawdata has
     `CollectCount`, flag MANIFEST_DRIFT warning.
   - Aligns with `02 §6.4` suggested dimensions.

### §5.6 Manifest examples for representative machines (per `02 §4` matrix)

**M31** (`02 §4.1` row: ST-1G / F-FreeSpin / S-Base):
```json
{
  "machine_id": "M31",
  "cluster": "SC-Vanilla",
  "overrides": {
    "feature_tags": ["FreeSpin"],
    "spin_type_convention": {"paid": [43], "bonus": [44]}
  }
}
```
Effective analyzer_features (from SC-Vanilla cluster defaults):
`[payouts_by_spin_type, reel_marginal_by_spin_type,
bankruptcy_simulation, multiplier_profile]`. **Adding a new
feature like the 4cbcab2 filter fix only affects M31 if M31's
manifest lists it** — see §4.2 worked example #2.

**M279** (`02 §4.1` row: singleton / F-BCM+MoveNudge+Wheel /
S-BCM-21k):
```json
{
  "machine_id": "M279",
  "cluster": "SC-BCM-Modern",
  "overrides": {
    "feature_tags": ["BCM", "MoveNudge", "Wheel"],
    "spin_type_convention": {"paid": [140], "bonus": [2, 36]},
    "analyzer_features": ["+wild_nudge_classification"]
  }
}
```
Inherits SC-BCM-Modern's 7 features + adds `wild_nudge_classification`.
The `+` prefix means "append to cluster default".

**M12$TopDollarSelector$0$** (variant; `02 §5.3` variant-explosion):
```json
{
  "machine_id": "M12$TopDollarSelector$0$",
  "cluster": "SC-TopDollar",
  "overrides": {
    "spin_type_convention": {"paid": [1], "bonus": [14, 15]}
  }
}
```
All 12 TopDollar variants inherit the same cluster: identical
analyzer_features and round_win_rules. Per `02 §4.1` variant
explosion observation: "166 variants share Axes 1-4 with their
underlying".

**SC-Vanilla machine** (e.g. M14, 45 in the cluster per `02 §4.2`):
```json
{
  "machine_id": "M14",
  "cluster": "SC-Vanilla",
  "overrides": {}
}
```
Minimal manifest. Single-line. **The cheapest possible onboarding**
(brief §6 success criterion).

---

## §6 Migration plan

Five phases. Each phase delivers a verifiable end-state and has an
explicit rollback path. Every phase preserves brief §5.1 (in-flight
reports keep working) and brief §5.2 (prod console never breaks).

### Phase 1 — Foundation: dedup md5/summary-patch + RAWDATA_ROOT global fix

**Goals**:
- Eliminate the 6 duplications between real and virtual identified
  by `01 §4`.
- Resolve the `RAWDATA_ROOT` module-global hazard at `app.py:518`
  per memory `feedback_subprocess_import_suicide_and_module_globals.md`.

**Deliverables**:

1. **Extract `_lookup_machine_md5` to a shared module**: today it
   lives in `player_impact_analyzer.py:2163` AND `app.py:548-591`.
   Move both into `fresh_slotlab/identity_stamp.py` (new module);
   both call sites import. Per `01 §4` ("Two ENTIRELY SEPARATE md5
   implementations").
2. **Extract `_patch_summary_md5_tags` to shared module**: today at
   `virtual_analyzer.py:506-558` AND `_run_generate_report:6955-6973`.
   Both call sites use new shared `stamp_summary_identity(summary,
   machines_config, machine, mode)` function in
   `fresh_slotlab/identity_stamp.py`. Per `01 §4` ("Two
   implementations; comments at both sites cross-reference each
   other").
3. **Unify session-CI helpers**: `_ci_halfwidth_pp` at
   `virtual_analyzer.py:278-291` reads "matches the formula used by
   the real analyzer". Move to `fresh_slotlab/session_ci.py`; both
   sites import. Per `01 §4` ("Two t-critical tables").
4. **Replace all `RAWDATA_ROOT` module-global reads inside class
   methods** (11 references per `03 §4.1`): grep `app.py` for
   `RAWDATA_ROOT` outside the const declaration; convert each to
   `self._rawdata_root` (using the existing injection at
   `create_app`'s `rawdata_root=...` param). Per memory's "Convert
   to `self._xxx`" template.
5. **Add the import-suicide regression test** (per memory
   `feedback_subprocess_import_suicide_and_module_globals.md` test
   template): `tests/backend/test_virtual_registry_subprocess_safety.py`
   spawns `python -c "import slot_designer.core.backend.virtual_registry; assert no web_console in sys.modules"`.

**Rollback**: revert the phase-1 commit(s). The new shared modules
are additive; the old paths in `app.py` and `virtual_analyzer.py`
can be restored from git without touching any schema. No reports
become unreadable.

**Why phase 1**: this is the **safest** lift — no schema change, no
hash change, no manifest infrastructure. It pays down the
duplication debt that would otherwise compound under later phases.

### Phase 2 — Slice analyzer: introduce feature modules + base hash

**Goals**:
- Migrate the analyzer monolith from `player_impact_analyzer.py:1-8176`
  into the new `fresh_slotlab/analyzer/{core,features}/` tree.
- Introduce `compute_base_analyzer_version` + `compute_feature_hashes`
  in `fresh_slotlab/analyzer/versioning.py`.
- Keep `compute_analyzer_version()` as a thin wrapper that returns
  the **whole-file** hash for backward compatibility (so existing
  `summary.analyzer_version` keeps the same shape).

**Deliverables**:

1. **Carve `features/payouts_by_spin_type.py`** out first (smallest
   self-contained surface; the `729a6ca` + `8411c9d` + `4cbcab2`
   commit cluster from `00 §3` lands here). Verify byte-identical
   summary output via golden-file regen.
2. **Carve `features/reel_marginal_by_spin_type.py`** (paired with
   above).
3. **Carve `features/bankruptcy_simulation.py`** (universal KPI,
   `01 §2.3` line 154; +`_BankruptcyStreamAccumulator` at `:1266`).
4. **Carve `features/bonus_chain_dynamics.py`** (per `02 §3.1`
   serves ~152 machines).
5. **Carve `features/collect_mechanic.py`** (BCM cycle support,
   `01 §2.3` `_compute_bonus_correction:1811`).
6. **Carve `features/multiplier_profile.py`** (universal KPI,
   `01 §2.3` `build_multiplier_bucket_rows:1978`).
7. **Carve `features/wild_nudge_classification.py`** (`02 §3.5.2`
   row 1, ~7 machines).
8. **Carve `features/cycle_peak_detection.py`** (`02 §3.5.2` row 2,
   ~35 machines).
9. **Carve `features/topdollar_settlement.py`** (`02 §3.5.1` row 2,
   17 machines).
10. **Carve `features/wheel_selector_type2.py`** (`02 §3.5.4`
    Pattern 2, 96 rows).
11. **Carve per-bespoke for the 12 heavy outliers** (`02 §5.1`):
    `features/bespoke_m21_buffalo.py`, `bespoke_m11_diamond.py`,
    `bespoke_m113_expanded.py`, `bespoke_m120_reward_id.py`,
    `bespoke_m260_buffs.py`, `bespoke_m268_credits_symbol.py`,
    `bespoke_m279_combo.py`, etc.
12. **Introduce `fresh_slotlab/analyzer/versioning.py`** with
    `compute_base_analyzer_version` + `compute_feature_hashes` +
    `compute_effective_analyzer_version`.
13. **Write summary.effective_analyzer_version alongside
    summary.analyzer_version** (additive — no field rename).
14. **Add tests**: byte-identical summary regression vs golden
    files for at least one machine per super-cluster
    (M14/SC-Vanilla, M272/SC-BCM-Modern, M15/SC-TopDollar,
    M273/SC-WheelSelector, M150/SC-LockRespin-50, M140/SC-MoveNudge,
    plus 6 of the 12 heavy outliers).

**Rollback**: revert the phase-2 commits. The pre-phase-2 monolith
is preserved in git; reverting restores it. Old reports continue
working (their `analyzer_version` field still matches what the
restored code produces). No data loss.

**Why phase 2 second**: this is the riskiest lift (slicing 8,176
LoC). Validator and Critic must approve the cut-points before phase
2 ships. Each feature carve-out can be a separate commit, each
verified against frozen golden reports.

### Phase 3 — Manifests: introduce per-machine declaration + cluster defaults

**Goals**:
- Land the manifest schema described in §5.5.
- Wire it through to `compute_effective_analyzer_version` so the
  per-machine hash actually reflects declared features.
- Frontend reads manifest-driven feature list to know which
  renderers to invoke.

**Deliverables**:

1. **Write `slot_designer/configs/machine_plugin_manifest.json`**
   per §5.5 Option 5.5c hybrid format. Seed all 421 machines —
   most via cluster reference, 12 heavy outliers + the
   feature-bearing variants with explicit overrides.
2. **Implement `manifest_loader.py`**: reads manifest, resolves
   cluster defaults + overrides, returns
   `EffectiveManifest(machine_id)`. One source of truth.
3. **Wire `compute_effective_analyzer_version` to read manifest**:
   each call passes `machine_features = manifest.analyzer_features`.
4. **Update `_run_generate_report` + virtual_analyzer + RunManager.start_run**
   to use effective version when stamping `summary.effective_analyzer_version`
   AND writing the `runs` DB column AND writing the
   reports/<M>/mode_<N>/index.json `effective_analyzer_version` field.
5. **Update `/api/reports/stale-count` at `app.py:5694`** to compare
   `runs.effective_analyzer_version` vs the freshly-computed
   per-machine effective version, not the whole-file hash.
6. **Frontend updates** (`app.js`, `pure.js`):
   - `app.js:_renderRwtreeCell:1895`: read both legacy and effective
     versions; show "stale" only if effective doesn't match.
   - `_paintAnalysisFromSummary:6676`: skip renderers whose
     feature_id isn't in the report's manifest (avoid empty panels
     for features the machine doesn't have).
7. **Manifest validation CLI**:
   `scripts/validate_manifests.py` — reads every manifest, checks
   `02 §6.4` sanity rules, reports MANIFEST_DRIFT warnings.

**Rollback**: revert phase-3 commits. Manifest file stays on disk
but is ignored. `compute_effective_analyzer_version` returns the
same value as `compute_analyzer_version` (whole-file hash). The 421
machines' reports stay valid.

**Why phase 3 third**: needs phase 2's feature modules to exist so
manifest can reference them. Independent of phase 4 (frontend
versioning) and phase 5 (fleet-shared commit retro-fit).

### Phase 4 — Frontend renderer registry + schema-version contract

**Goals**:
- Land §5.3 frontend renderer registry.
- Wire schema-version fallback rules per §5.3 example.

**Deliverables**:

1. **New `src/web_console/frontend/renderers/registry.js`** with
   the 17 renderer entries from `03 §2.10`. Each entry declares
   `feature_id`, `minSchemaVersion`, `maxSchemaVersion`, `fallbackRules`.
2. **Refactor `_paintAnalysisFromSummary`** (`app.js:6676`) to
   iterate `RENDERER_REGISTRY` instead of inline dispatch. Each
   renderer call now checks `summary.schema_versions[feature_id]`
   vs its supported range; selects fallback rule if needed.
3. **Replace silent `??` fallbacks scattered through `app.js`**
   (`03 §4.3` enumerates these) with explicit registry-driven
   fallback application.
4. **Add fallback unit tests**: load a frozen v1-schema fixture and
   a v2-schema fixture; assert renderer produces identical
   rendered output for both.

**Rollback**: revert phase-4 commits. The new registry file stays
but is unused. The inline dispatch is restored. Reports keep
rendering.

**Why phase 4 fourth**: independent of analyzer slicing; could in
principle be phase 1, but pairs better with phase 3 (manifest's
feature_tags inform which renderers to even attempt).

### Phase 5 — Retro-fit the 7 fleet-shared commits + outlier conversion + machine_round_win_rules consolidation

**Goals**:
- Retroactively map the 7 commits in brief §3 into the new model.
- Convert all 12 heavy outliers to use per-machine bespoke plugin
  modules.
- Optionally consolidate `configs/machine_round_win_rules.json`
  into per-machine manifests (`02 §3.5.1` shows only 13 entries; a
  consolidation simplifies but isn't required).

**Deliverables**:

1. **Retro-fit map**:
   | Commit | Maps to |
   |---|---|
   | `54b7d01` (scatter symbol kind) | `core/engine/symbol.py` is virtual-only; affects `compute_code_md5` for 6 virtual machines only (per `03 §5.1`). Does NOT need feature module. Document in manifest as: virtual machines list `core_engine_v2` feature_tag if cluster requires scatter awareness. |
   | `729a6ca` (ST-split add) | `features/payouts_by_spin_type.py` + `features/reel_marginal_by_spin_type.py`. The `+` adds were schema_version=1 → schema_version=2 transition. |
   | `8411c9d` (rename schema fields) | Bumps `payouts_by_spin_type.SCHEMA_VERSION` to 2. Frontend registry adds fallback rule for v1 → v2 (the existing `?? hit_rate_pct/100` pattern, now declarative). |
   | `7e5fe32` (frontend fallback) | Becomes the registry's `fallbackRules[1]` entry for `payouts_by_spin_type`. |
   | `0f981b9` (derive spin_type_category) | Becomes a feature-extracted summary field in `features/payouts_by_spin_type.py` (not derived on frontend). |
   | `4cbcab2` (st_hits filter) | Bumps `payouts_by_spin_type.SCHEMA_VERSION` to 3 (or stays at 2 with bug-fix changelog). |
   | `284fd19` (revert 80% threshold) | Threshold logic lives in `features/payouts_by_spin_type.py`. Out-of-scope per brief §7. |

2. **Bespoke-outlier plugin files** (`02 §5.1` 12 machines):
   `features/bespoke_m21_buffalo.py`, ..., `features/bespoke_m120_reward_id.py`,
   ..., `features/bespoke_m260_buffs.py`. Each lifts the machine-specific
   logic currently buried in `parse_chunk_response` conditionals
   (e.g. M21's named-symbol counter extras handling) into a single
   file declared in M21's manifest only.

3. **Update `configs/machine_round_win_rules.json`** to add
   `manifest_seeded: true` marker. Optionally drop this file
   entirely in favor of per-machine manifest `round_win_rules`
   arrays — `load_rules_for_machine` reads either source.

4. **Fleet validation sweep**: run
   `scripts/validate_manifests.py` over all 421 machines + sample
   rawdata; report any MANIFEST_DRIFT warning. Reconcile with
   user before declaring phase 5 complete.

**Rollback**: revert phase-5 commits per outlier. Each bespoke
plugin lift is independently reversible (the manifest just
removes the bespoke feature_id; the orchestrator skips it).

**Why phase 5 last**: needs the manifest infrastructure (phase 3)
and feature modules (phase 2). Also the most likely to discover
edge cases that need manifest-schema iteration; doing it last keeps
the schema stable for earlier phases.

### §6.5 Phase summary table

| Phase | Risk | Days est. | Schema change | Rollback simplicity |
|---|---|---|---|---|
| 1 (dedup + globals) | LOW | 2-3 | None | Trivial (revert) |
| 2 (slice analyzer) | HIGH | 7-10 | Additive `effective_analyzer_version` field | Per-feature reverts |
| 3 (manifests) | MEDIUM | 3-5 | None (manifest read; old hash kept as fallback) | Trivial (delete manifest reads) |
| 4 (frontend registry) | LOW | 2-3 | None | Trivial (revert) |
| 5 (retro-fit + outliers) | MEDIUM | 4-6 | None | Per-outlier reverts |

Total: ~20-27 dev days (sequential), longer if validation rounds
loop back.

### §6.6 Migration constraint compliance

| Brief constraint | How honored by this plan |
|---|---|
| §5.1 Backward-compat 393+ machines reports | Phase 2 keeps `analyzer_version` field; phase 3 adds `effective_analyzer_version` alongside; frontend (phase 4) reads new, falls back to old. No regen forced. |
| §5.2 Prod console (8877) never breaks | Each phase has rollback; phase 2's feature carve-outs are byte-identical-summary tests per cluster. |
| §5.3 Virtual reuses prod code | Phase 1 removes dups; phase 2's feature modules are shared. |
| §5.4 New machine = O(1) hash | Phase 3 manifests + phase 5 outliers achieve this; §4.2 worked examples prove the math. |
| §5.5 Rollback per phase | Documented per phase above. |
| §5.6 No silent data loss | All field renames are versioned in §5.3 schema_versions; old fields preserved in summaries; manifest defaults conservative. |

---

## §7 Open questions for Wave 3

These are points where Critic and Validator need to weigh in before
implementation begins.

### §7.1 Where exactly to draw the cut between `core/` and `features/`?

§4.1 lists ~16 plausible feature modules and identifies which
`core/` ones are universal. **Validator**: please run the
analyzer's `parse_chunk_response` (`01 §2 layer 2`) line-by-line
and classify every block. Cases I'm uncertain about:

- **Trigger session detection** (`01 §2` layer 2 row 6,
  `trigger_sessions.py:131`): used by all bonus-bearing machines
  (`02 §3.5.4` covers ~12 underlying + variants). Is this a
  `core/` (always-on) or a `features/` (opt-in)? Today it's invoked
  unconditionally; could become opt-in based on
  `manifest.feature_tags`.

- **Pay-id attribution** (`01 §2` layer 2 row 7,
  `round_classification.py:172,232`): the suffix-fallback path
  affects M120/M123/M139/M279 specifically. Should this become
  `features/pay_id_suffix_attribution.py`, or stay in `core/`
  because it falls through to a no-op for the 408 machines that
  don't need it?

- **`_REQUIRED_ROUND_FIELDS` schema gate** (`03 §6` honorable
  mention, `player_impact_analyzer.py:1465`): this is the
  upstream-API-contract guard. Is it `core/` (universal) or a
  per-cluster `features/` (each cluster declares its required
  fields)?

### §7.2 Cluster-default inheritance semantics

§5.5 Option 5.5c uses `+feature_id` to mean "add to cluster
default". Should it also support `-feature_id` (remove from
cluster default)? Use case: a SC-BCM-Modern machine that
specifically doesn't have `cycle_peak_detection` for some reason.
**Critic**: please weigh in.

### §7.3 `core/engine/*.py` virtual hash vs `core/` analyzer hash — do we unify the naming?

`compute_code_md5(machine_name)` at `machine_version.py:109` and
the proposed `compute_base_analyzer_version` are conceptually
different things on different sides (virtual machine identity vs
analyzer process version). Naming collision risk: both feel
"hash this Python source". Should they share a primitive or stay
separate? **Validator**: verify the boundary doesn't conflate.

### §7.4 Manifest-rawdata drift handling

§5.5 validation rule 4 flags MANIFEST_DRIFT as a warning. Should
it be an error (block deploy) or warning (allow with red banner)?
Per `02 §3.5.2`: implicit primitive reliance (Bugs 1-4 from
memory) is fleet-wide ~35-40 machines today, but only ~7 are
declared. Drift surface is large. **Critic**: what's the right
default — strict or lenient?

### §7.5 SC-WheelSelector (96 rows including 85 M273 variants) — manifest size sanity

The 85 M273 variants all share Axes 1-4 with M273 (`02 §4.1`
observation 6). Should the manifest carry 85 nearly-identical
rows (one per variant), or a single variant-template row that
fans out via the existing `machine_variants.py:336` machinery?
**Validator**: please review the variant-fanout integration.

### §7.6 Heavy-outlier bespoke plugin — does this scale beyond 12?

`02 §5.1` lists 12 heavy outliers; `02 §5.2` lists ~30 medium
outliers. If medium outliers also need bespoke plugins, total
goes to 42 (per `02 §5.4`). Is that too many? Should there be a
shared "bespoke-extras-ignored" plugin that just acknowledges
non-standard extras without analyzing them, used by the medium
group? **Critic + Validator**: please weigh in on the
plugin-count budget.

### §7.7 `RoundWinRule` ABC API stability under Protocol-conversion

§5.4 keeps `RoundWinRule` ABC unchanged. But the new
`AnalyzerFeature` Protocol could also accommodate round-level
extraction (just override `extract` to read individual rounds).
Should we unify the two abstractions long-term, or keep them
separate (round-level vs summary-level)? Memory
`reference_round_win_rule_architecture.md` argues separate; the
proposal accepts that. **Critic**: confirm or counter.

### §7.8 Schema version-bump policy

§5.2 says `SCHEMA_VERSION: int, bumped on breaking field rename`.
But what counts as "breaking"? Adding an optional field doesn't
break the renderer (it just doesn't render it). Renaming an
existing field always breaks (the `8411c9d` case). Removing a
field breaks. Changing a field's units (e.g. percent → fraction,
the `8411c9d` case) breaks. **Validator**: please draft an
explicit policy document for the SCHEMA_VERSION bump rules.

### §7.9 The 5 open questions from `01 §5` mapper

01_pipeline_map.md §5 raised 8 questions about the current state
that the mapper couldn't resolve from observation alone. Several
of them (especially #1 — "three invocation styles, no spec saying
they behave identically" — and #5 — "frontend probe-and-fallback
location unknown" — and #8 — "compareReports cache-bust race")
deserve resolution before phase 1 of migration to make sure the
new shared primitives don't accidentally break unobserved
invariants. **Critic**: please walk through 01 §5 and flag any
that block this proposal.

---

## §8 Out of scope

### §8.1 Upstream API schema changes

The chunk envelope (per `01 §2 layer 0`, `_BASELINE_ROUND_FIELDS`
at `:1444-1452`, `_REQUIRED_ROUND_FIELDS` at `:1465-1468`) is
treated as immutable per brief §7. This proposal works inside the
existing schema; it does not propose changes to the upstream
fields or to the chunk envelope shape. Future upstream-schema
work (e.g. dropping `CurJackpotStoreWin` per `02 §3` reference) is
out of scope.

### §8.2 The 80% spin_type_category threshold (`5c4a111` revert)

Brief §7 explicitly defers this. Proposal preserves the current
80% threshold logic inside `features/payouts_by_spin_type.py`
without touching it.

### §8.3 Performance optimization unrelated to architecture

Per brief §7: "blast-radius reduction is in scope; sampling
speed-ups are not." This proposal does not touch the AIMD
sampling loop (`player_impact_analyzer.py:860`), the chunk
inverted-md5 lookup (`chunks_by_md5` per memory
`reference_chunk_index_inverted_md5.md`), or the bankruptcy
streaming accumulator (`:1266`). These already work well.

### §8.4 UX / visual redesign

Per brief §7: "focus on data/logic architecture." Frontend
renderer registry (§5.3, phase 4) is a structural change to how
renderers are dispatched; it does not change layout, color, or
text content. The new `RENDERER_REGISTRY` pattern is purely
internal.

### §8.5 Implementing this proposal

Per brief §7: "this team produces design only. Implementation =
next session." Migration phases above describe deliverables but
do not commit code.

### §8.6 Re-onboarding the 6 virtual machines under a new spec format

`compute_code_md5(machine_name)` at `machine_version.py:109` and
the per-machine `slot_designer/machines/<M>/{spec.json, weights/,
reel_strips.json, plugins/}` layout is per brief §2 audit-only
(handled by slot-* team for individual machine onboarding). This
proposal touches only **how analyzer features are declared per
machine** (manifest) — not how virtual machine specs or plugins
are structured.

### §8.7 Reporter.py legacy module + sampler.py M14-hardcoded path

`01 §5 question 4` flagged `fresh_slotlab/reporter.py` (131
lines, no production callers found) and `fresh_slotlab/sampler.py`
(365 lines, hardcoded `MACHINE_NAME = "M14"` at line 18) as
orphan / legacy code. This proposal leaves them in place. Cleanup
is a separate task — the only thing the proposal asks is that
these files **do not become reference patterns for the new
analyzer slicing** (use `parse_chunk_response` as the cut-source).

### §8.8 Database schema migration for state/console/console.db

The proposal adds `effective_analyzer_version` to the `runs`
table (phase 3). The schema migration itself (ALTER TABLE) is a
trivial commit in phase 3's deliverables. Out of scope: any
broader DB restructuring (multi-tenancy, encryption at rest,
etc.).

### §8.9 Sub-fleet expansion (new variant explosion modes)

`02 §3` notes M273 has 85 variants; future selectors might have
more. The proposal works with the existing variant-fanout machinery
(`machine_variants.py:336`); does not propose changes to variant
declaration syntax in `configs/machines.json` or to the `$`
separator parsing.

### §8.10 Multi-language / i18n updates

Per brief §7 (aesthetic / UX out of scope) and memory
`feedback_no_parallel_panel_impl.md` (i18n keys must reuse, not
parallel-impl). The proposal's renderer registry refactor (phase
4) does not add new i18n keys or rename existing ones — every
renderer's text strings come from existing `I18N` table at
`pure.js:15-948`.

---

```
arch-designer complete.
- Alternatives explored: 3
- Recommended: Alternative A — granular analyzer version + manifest-declared plugins
- Hash composition: per-machine effective_analyzer_version = sha256(base_hash || sorted(feature_hashes_M_uses))[:12]
- Migration phases: 5 (1 foundation/dedup-globals, 2 slice-analyzer, 3 manifests, 4 frontend-registry, 5 retro-fit-outliers)
- Out-of-scope items: 10
- Open questions for Wave 3: 9
- Output: session_artifacts/_arch/04_architecture_proposal.md
```
