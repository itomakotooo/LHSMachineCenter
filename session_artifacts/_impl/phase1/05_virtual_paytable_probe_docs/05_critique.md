# Critique — P1-A3: Frontend probe location documented

**Ticket**: `phase1/05_virtual_paytable_probe_docs`
**Critic**: impl-critic
**Date**: 2026-05-17
**Verdict**: APPROVE-WITH-REVISIONS

---

## Verdict rationale

The deliverable is substantially correct: all seven entries are present, each
carries all four required fields (What / Why / Code location / Risk), the two
cross-reference comments exist at the right functional sites, and no runtime
code was touched. The implementation is 90% of what it needs to be.

Two revisions are required:

1. **Implementation report mis-states the app.js comment line number** (line
   4483 vs actual 4558). The comment itself is correctly placed in the code;
   the report is wrong. This is a documentation accuracy issue in the
   deliverable artifact that auditors will read.

2. **Three `01_pipeline_map.md §4` duplications are documented in
   `02_implementation.md` as deferred but are absent from the doc entirely** —
   session-CI formula, t-critical table, schema fingerprint. The brief's §2
   cites `01_pipeline_map.md §4` "entire" as the source material. The §4 "Where
   they overlap in function but code lives separately" table has 5 rows, of
   which A4+A5 cover 2. The remaining 3 (session-CI / t-critical / schema
   fingerprint) are dropped with the justification "the brief's minimum-6 list
   doesn't include them." That is correct for the minimum count but leaves the
   doc incomplete as a source-of-truth reference — a future auditor reading the
   doc won't know these duplications exist. They should appear in §A or at
   minimum in a §C-adjacent "Known duplications not yet ticketed" section.

Neither revision touches runtime code. Both are doc-only changes.

---

## Stress questions (5)

---

### SQ1 — Is `01_pipeline_map.md §4` fully covered?

**Question**: The brief §2 cites `01_pipeline_map.md §4` "entire" as the source
material and `03_coupling_audit.md §4.5` as an additional source. §4 has a
"Where they overlap in function but code lives separately" table with 5 rows:
md5 computation, md5 patch into summary, session CI half-width, t-critical table,
inference scripts trigger. The doc covers rows 4 (A4) and 5 (A5). Are rows 1
(md5 computation), 3 (session CI), and 4 (t-critical table in `01_pipeline_map`
numbering) absent from the doc?

**Investigation**: Reading `01_pipeline_map.md §4` "Where they overlap" table
rows: (1) md5 computation for chunk stamping — two entirely separate
implementations; (2) md5 patch into summary — captured as A4; (3) session CI
half-width formula — not in doc; (4) t-critical table — not in doc; (5)
inference scripts trigger — captured as A5.

The implementer's `02_implementation.md §Open issues` items 3-5 explicitly
acknowledge the session-CI formula, t-critical table, and schema fingerprint
duplications are known from `01_pipeline_map.md §4` but were "intentionally
not added to avoid scope creep beyond the 6 asymmetries the brief specifies."

That reasoning is partially valid (the brief's §3 C1 minimum-6 list does not
enumerate these), but the brief also says in §2 that `01_pipeline_map.md §4`
(entire) is the source material, and the doc's own header says it is generated
from that source. A doc that omits three rows from its own cited source table
is an incomplete source of truth.

**Verdict**: PARTIAL — the omission is acknowledged but the justification
("brief's minimum-6") doesn't fully satisfy "exhaustive against §4". The three
omitted items should appear somewhere in the doc, even if only as a "deferred /
no ticket yet" subsection. The doc currently reads as if the five-row table
doesn't exist.

---

### SQ2 — Are cross-reference comments at the correct probe/registration sites?

**Question**: The brief §3 C3 specifies the comments go at the "Frontend probe
site (app.js:4475-4482)" and the "virtual route registration site
(virtual_app.py:152-159)". Implementation report claims `app.js:4483`. Actual
grep result: the comment is at `app.js:4558`. Is 4558 the right functional
location?

**Investigation**:

`app.js:4476-4499` is the pre-existing header comment for `renderPayIdOverview`
that describes the shape panel. This is NOT the probe site.

The actual probe — `apiGet('/api/virtual/paytable/${machine}')` — is at
`app.js:4562-4564`, inside a try/catch block starting at line 4561. The new
cross-reference comment at line 4558 is directly above `let declaredPays = []`
which is immediately above the try/catch. This is the closest comment position
to the actual callsite that fits naturally into the existing comment block
(4547-4557) explaining the virtual-console probe behavior.

So the **comment placement in code is correct**. The **implementation report's
claimed line number (4483) is wrong**. 4483 is part of the header comment
describing the shape panel, nowhere near the probe. The report's "cross-reference
comments" table therefore contains a factually incorrect line number that any
auditor following the report to the code will find confusing.

**Verdict**: PARTIAL (comment correctly placed; implementation report line
number wrong — requires correction in `02_implementation.md`)

---

### SQ3 — Does the "B2 bonus non-asymmetry" entry add real value or is it noise?

**Question**: B2 documents that `chunk_index + rawdata_index` are shared verbatim.
The entry is well-sourced (cites the docstring). But is this worth documenting
in a doc whose stated purpose is cataloguing asymmetries? Could the entry
mislead a future contributor into thinking the list is exhaustive about
non-asymmetries when many other shared files (e.g. `fresh_slotlab/round_win.py`,
`fresh_slotlab/trigger_sessions.py`) are not listed?

**Investigation**: The brief's §3 C1 bullet 7 explicitly requires "chunk_index +
rawdata_index are shared verbatim (no asymmetry — positive)". The brief justifies
this: "future auditors don't re-investigate them." The doc's §B preamble also
makes this explicit: "Recorded here so future auditors don't re-investigate
them."

The entry is NOT presented as exhaustive about non-asymmetries — §B is labeled
"items that were audited and confirmed". The risk that a reader thinks "if it's
not in §B it must be asymmetric" is mitigated by the §B preamble's "initial
pass" framing.

**Verdict**: ADEQUATE — the non-asymmetry entries serve the stated purpose.
The noise concern is answered by the brief's explicit requirement and the §B
preamble's scoped framing.

---

### SQ4 — Does the doc accidentally describe a planned future state (post-P1-B2/P1-B5) as current?

**Question**: A4 and A5 reference P1-B2 and P1-B5 as pending consolidation
tickets. Do any doc statements describe the post-consolidation state as if it
already exists, creating confusion about current vs future behavior?

**Investigation**: A4 says "Two separate code paths patch these fields post-run"
and explicitly labels this "Accidental duplication … P1-B2 is the consolidation
ticket that will unify these into a single helper." A5 similarly says "Two
separate implementations have diverging argument signatures … Forgetting one
side silently breaks inference for one console type."

Both entries describe the CURRENT (pre-consolidation) state as the problem.
The Risk fields in A4 and A5 describe what breaks if consolidation is only
partial — that is forward-looking but as a warning, not as a current-state
claim.

The §D ticket cross-reference table shows A4/A5 as "Accidental; pending
consolidation" with P1-B2/P1-B5 as the respective tickets.

**Verdict**: ADEQUATE — no future state is described as current.

---

### SQ5 — Is the doc self-consistent with `03_coupling_audit.md §4.5` (the other cited source)?

**Question**: The doc header cites `03_coupling_audit.md §4.5` as a source. §4.5
("Duplicate primitives: real-vs-virtual coupling") enumerates: (1) sampler.py
vs analyzer.py duplications (`post_json`, `t_critical_95`, `compute_ci_halfwidth_pp`),
(2) `peek_chunk_envelope` dual-impl, (3) virtual_analyzer stays thin (good), (4)
`_register_virtual_only_routes` asymmetry. Does the doc cover these?

**Investigation**:

- §4.5 item (1): `sampler.py` vs `player_impact_analyzer.py` duplications of
  `post_json`, `t_critical_95`, `compute_ci_halfwidth_pp`. The doc does NOT
  cover `sampler.py` duplications at all. `sampler.py` is confirmed legacy/dead
  code ("legacy CLI, not on prod path" per `01_pipeline_map.md §3`). So its
  omission is defensible — non-production code.

- §4.5 item (2): `peek_chunk_envelope` dual implementation (analyzer:2083 vs
  chunk_index:145). The doc does NOT cover this. It is NOT in the brief's
  minimum-6 list and NOT in `01_pipeline_map.md §4` overlap table. This is a
  genuine omission from `03_coupling_audit.md §4.5` coverage. Risk is low
  (coupling-only, no live consumer divergence today per §4.5) but the doc claims
  to be generated from `03_coupling_audit.md §4.5` and the item doesn't appear.

- §4.5 item (3): virtual_analyzer stays thin — this is a positive finding, not
  an asymmetry. Not needed in the doc.

- §4.5 item (4): `_register_virtual_only_routes` asymmetry — covered as A1.

**Verdict**: PARTIAL — `peek_chunk_envelope` dual-impl from §4.5 is a genuine
omission from the stated source coverage. Low-risk item but the doc's header
claim of being "Generated from … `03_coupling_audit.md §4.5`" is incomplete
if that section's second bullet is absent. Should be noted (even briefly) in
the doc.

---

## Chain disagreements (implementer vs tester vs verifier)

- **No `03_tests.md`**: Tester artifact is absent. Brief §7 specifies tester
  writes `03_tests.md` with "N/A: docs only" verdict + cites the asymmetries
  from `01 §4` as the validation criterion. The file does not exist.

- **No `04_verification.md`**: Verifier artifact is absent. Brief §7 specifies
  verifier reads the doc against `01 §4` source material and asserts all 6+
  known asymmetries are documented. Without this artifact the critic cannot
  verify that the chain is complete. This is the most significant chain gap.

- **Implementer `02_implementation.md` claims `app.js` comment at line 4483**.
  Grep of the actual file shows the comment is at line 4558. These are
  inconsistent. A future auditor following `02_implementation.md` to line 4483
  finds the `renderPayIdOverview` header comment about shape panels, not the
  cross-reference to the asymmetry contract.

---

## Hidden assumptions the chain makes

1. **"Brief's minimum-6 satisfies completeness"**: The chain equates "brief says
   minimum 6" with "covering 7 satisfies the doc's stated source-material
   coverage." The brief's §2 cites the full §4 table as source material, not
   just the minimum-6 bullet list. The three deferred items (session-CI /
   t-critical / schema fingerprint) live in the source material but not in the
   doc.

2. **"The doc is a living document that grows"**: The §A "How to add" guidance
   and §D table imply the doc will be updated as asymmetries are discovered.
   But there is no guidance on how to audit the doc against the source table
   when future contributors add entries — without a "last full-sweep date" or
   a checklist, the source table can diverge silently.

---

## Edge cases not covered by the test / verification chain

Since this is a docs-only ticket, "edge cases" map to documentation completeness
gaps rather than runtime failures:

1. **`peek_chunk_envelope` dual implementation** (`01_pipeline_map.md §4` row /
   `03_coupling_audit.md §4.5` bullet 2): not in doc, not mentioned in
   `02_implementation.md §Open issues`.

2. **`sampler.py` `t_critical_95` / `post_json` duplication** (`03_coupling_audit.md §4.5`
   bullet 1): not in doc. Defensible since `sampler.py` is dead production code
   — but the chain never explicitly says "sampler.py is out of scope."

3. **`_watch_run` inference hook status** (`01_pipeline_map.md §5 Q2`): the
   pipeline map notes it "could not find an inference call in `_watch_run`."
   A5's Risk field describes what breaks if the two trigger sites get out of
   sync, but doesn't mention the open question about whether live-sampling via
   `RunManager.start_run` + subprocess also triggers inference at all. A reader
   of the doc is not warned that the live-sampling path's inference coverage is
   unverified — a potential third asymmetry lurking under A5.

---

## Required revisions (APPROVE-WITH-REVISIONS)

### R1 — Correct implementation report's app.js line number

`02_implementation.md` cross-reference table claims:
```
src/web_console/frontend/app.js | 4483 | // Real ↔ virtual asymmetries catalogued...
```
Actual line is 4558. Correct the table. Also correct the "Risk notes" section
which says "lines 4472-4483".

**Points to**: SQ2.

### R2 — Add deferred-duplications subsection to `PROD_VS_VIRTUAL_CONTRACT.md`

Add a short subsection (e.g. `§E — Known duplications not yet ticketed`) that
lists the three rows from `01_pipeline_map.md §4` "Where they overlap" table
that are not covered by A4/A5:

- Session-CI half-width formula (`player_impact_analyzer.py:1012-1034` vs
  `virtual_analyzer.py:278-291`)
- t-critical table (`player_impact_analyzer.py:965-997` vs
  `virtual_analyzer.py:262-275`)
- Schema fingerprint (`player_impact_analyzer.py:2108-2138` vs
  `slot_designer/core/emitter/chunk.py + driver.py`)
- `peek_chunk_envelope` dual implementation (`player_impact_analyzer.py:2083`
  vs `chunk_index.py:145`) [from `03_coupling_audit.md §4.5`]

Each needs only a one-liner (no full C2 treatment since they are not yet
ticketed). The subsection header makes clear these are "on record but not yet
assigned a consolidation ticket."

**Points to**: SQ1, SQ5.

---

## Commit-message `## Self-critique` section

(Verbatim, paste-ready for commit body)

```
## Self-critique

- [OPEN] app.js cross-reference comment line number in 02_implementation.md
  is stated as 4483 but actual line is 4558 (comment sits directly above
  `let declaredPays = []`, not inside the shape-panel header comment).
  Cosmetic doc inaccuracy; code placement is correct. Requires correction in
  implementation report.

- [OPEN] Three `01_pipeline_map.md §4` overlap-table rows (session-CI
  formula, t-critical table, schema fingerprint) and one `03_coupling_audit.md
  §4.5` bullet (peek_chunk_envelope dual-impl) are absent from
  PROD_VS_VIRTUAL_CONTRACT.md. Implementer deferred these citing "brief's
  minimum-6" but the doc header claims generation from the full §4 source.
  Addressed by adding §E "Known duplications not yet ticketed" section.

- [ADDRESSED] B2 non-asymmetry noise risk: §B preamble explicitly scopes
  entries as "items audited on this pass"; not claiming exhaustive coverage
  of non-asymmetries.

- [ADDRESSED] A4/A5 future-state confusion: both entries describe current
  pre-consolidation state as the problem; post-consolidation state appears
  only in Risk fields as a warning.

- [ADDRESSED] 03_tests.md and 04_verification.md absent: docs-only ticket;
  brief §6 + IMPL_TEAM_PROCESS §5 permit "N/A: docs only" for test artifact.
  Critic notes absence for record.
```

---

## Summary table

| Stress question | Verdict |
|---|---|
| SQ1 — §4 full coverage | PARTIAL |
| SQ2 — Cross-reference at correct site | PARTIAL (code correct; report wrong) |
| SQ3 — B2 non-asymmetry noise | ADEQUATE |
| SQ4 — No future state described as current | ADEQUATE |
| SQ5 — §4.5 source coverage | PARTIAL |
