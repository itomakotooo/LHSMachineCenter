# P1-A4 — `_classify_chunks` historical semantics spec'd
# impl-implementer report

## Verdict: pass

## Files changed

| File | Lines changed | Description |
|---|---|---|
| `src/web_console/backend/app.py` | 919-1016 (docstring extension, +89 lines) | Extended `_classify_chunks` docstring with consumer enumeration + safety invariant section |

## Brief-section traceability

| Change | Brief section |
|---|---|
| Consumer enumeration section added to docstring | §3 C1 — "extended docstring enumerates each known consumer … with file:line and purpose" |
| Display-only consumers documented (_build_rawdata_overview, get_rawdata_status) | §3 C1 — "UI display routes … list them" |
| Deletion consumers documented (delete_rawdata, _auto_cleanup_for_space, _enumerate_rawdata_deletable) | §3 C1 — "_auto_cleanup_for_space:2455+ — uses deletable + historical for mtime-based eviction" |
| Analyzer-input consumers documented (_run_generate_report, _prepare_batch_gen_item) | §3 C1 — "_run_generate_report:6733 — uses kept for in-process analyzer replay; NEVER passes historical" |
| Per-version DELETE endpoint noted as non-consumer | §3 C1 — "Per-version DELETE endpoint at :6042-6162 — uses explicit version, not bucket" |
| Safety invariant section: historical never auto-deleted by md5 drift | Memory `feedback_md5_is_a_tag_not_a_destruction_signal.md` |
| check_rawdata_status no auto_delete_* confirmed in docstring | §3 C5 — "check_rawdata_status does NOT accept any auto_delete_* parameter" |

## Consumer survey results

Grep for `_classify_chunks(` in `src/web_console/backend/app.py` found 6 call sites (excluding definition):

| Line | Calling function | Buckets consumed | Purpose |
|---|---|---|---|
| ~1133 | `delete_rawdata` | deletable + historical | Manual per-machine/mode deletion (一键清理 button) |
| ~2087 | `_build_rawdata_overview` | kept + deletable + historical | Display-only: rawdata overview panel byte/chunk counts |
| ~2528 | `_auto_cleanup_for_space` | deletable + historical | Disk-pressure mtime-based eviction |
| ~5971 | `get_rawdata_status` (endpoint) | kept + deletable + historical | Display-only: per-mode version grouping for UI rawdata panel |
| ~6733 | `_run_generate_report` | kept + deletable (default); all 3 filtered by md5 (operator-explicit path) | In-process analyzer replay |
| ~7136 | `_prepare_batch_gen_item` | kept + deletable | Batch-generate parent-thread chunk validation |
| ~8713 | `_enumerate_rawdata_deletable` | deletable + historical | Candidate collector for background auto-cleanup scheduler |

Note: 7 call sites total (not 6) — `_enumerate_rawdata_deletable` at ~8713 was found in addition to the 6 enumerated in the brief §3 C1. This is documented in the docstring. Not a bug — it's a helper that feeds `_auto_cleanup_for_space`, same deletion semantics.

No consumer was found that passes historical chunks to the analyzer without md5-filter intent. Brief §3 C1 invariant confirmed.

## check_rawdata_status parameter audit (brief §3 C5)

`check_rawdata_status` signature at line 655:
```python
def check_rawdata_status(
    machine: str,
    mode: int,
    rawdata_root: Path | None = None,
    machines_config: Path | None = None,
) -> dict[str, Any]:
```
No `auto_delete_*` parameter present. Existing docstring at line 670 already documents the removal: "Before 2026-04-21 this function took `auto_delete_mismatched=True` …". Confirmed per brief §3 C5.

## Pytest results (touched modules)

```
tests/backend/test_chunk_classifier.py   — PASS
tests/backend/test_cache_cleanup.py      — PASS
tests/backend/test_machine_config_override.py — PASS
tests/backend/test_chunk_index.py        — PASS
Total: 92 passed in 4.65s
```

## Open issues / out-of-scope items

None. All 7 call sites match the expected patterns (display / filter / deletion via explicit paths). No anomalous consumer found that would require a separate ticket.

## Risk notes for impl-verifier and impl-critic

- The `_run_generate_report` md5-filter path (lines ~6734-6756) passes historical chunks to the analyzer when the operator explicitly requests a historical-md5 cell. This is intentional per the design ("operator explicitly asked for this bucket"). The docstring now calls this out explicitly as "safe because the operator explicitly named the version."
- `_enumerate_rawdata_deletable` (~line 8713) is a 7th consumer not enumerated in the brief §3 C1 text. It is documented in the docstring and is semantically identical to `_auto_cleanup_for_space` (same deletable+historical pool, same lock/in-use guards). Not a bug; not out-of-place. Critic should verify the brief's enumeration was meant as illustrative (not exhaustive) or flag if a separate ticket is needed.
- No behavioral code was modified. This is a docstring-only change; rollback is `git revert <sha>`.
