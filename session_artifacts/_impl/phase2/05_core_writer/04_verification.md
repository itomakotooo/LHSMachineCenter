# P2-B3 Verification Report

**Verdict**: PASS
**Verifier**: impl-verifier
**Date**: 2026-05-19

## Step 1 - P1-A1 Canary: PASS
Command: python -m pytest tests/integration/test_analyzer_three_invocation_parity.py -q
Observed: 23 passed in 20.59s

## Step 2 - Full 8-Suite Regression: PASS
Observed: 519 passed, 11 skipped in 23.95s (expected 519/11)

## Step 3 - Subprocess Import Smoke: PASS
python -c import fresh_slotlab.analyzer.core.writer -> rc=0, no stderr
python -c import fresh_slotlab.player_impact_analyzer -> rc=0, no stderr

## Step 4 - Cycle Freedom (AST-based): PASS
Method: Walk ast.Import/ast.ImportFrom nodes in writer.py.
Correctly ignores PIA name in docstring (lines 6,22) that raw grep would false-positive on.
Observed: CYCLE_FREE: 0 back-imports to PIA found
All 6 ExceptHandlers are import-safety or swallow patterns. Zero PIA import nodes.

## Step 5 - Identity and Shadow-Def Check: PASS
Identity assertions:
  pia._save_chunk_cache IS w._save_chunk_cache      -> PASS
  pia.write_summary_json IS w.write_summary_json    -> PASS
  pia.CHUNK_CACHE_VERSION == w.CHUNK_CACHE_VERSION  -> PASS (value=3)
Shadow-def check (grep defs in PIA -- all rc=1, 0 matches):
  grep def _save_chunk_cache -> 0 matches
  grep def write_summary_json -> 0 matches
  grep def utc_now -> 0 matches
  grep ^CHUNK_CACHE_VERSION -> 0 matches
  Result: SHADOW_DEF_PASS

PIA lines 433,1330 are comments only. Symbols appear only in dual-path re-export block
(lines 219-230) and call sites (lines 1446, 5187).

## Step 6 - End-to-End Cached Chunk Envelope Verification: PASS
V3 chunk: rawdata/M1/mode_1/chunk_0387.json
  _cache_version = 3
  ALL 13 REQUIRED FIELDS PRESENT:
    _cache_version, _machine, _mode, _bet, _spin_times, _robot_count, _chunk_index,
    _saved_at, _config_md5, _code_md5, _upstream_schema_fingerprint, _payload_sha256, response

V2 chunk (pre-carve, canonical M14 test machine): rawdata/M14/mode_1/chunk_0001.json
  _cache_version = 2
  12/13 fields present (_payload_sha256 absent -- added in CHUNK_CACHE_VERSION=3, by design)
V2 backward compatibility confirmed by P1-A1 canary 23/23 GREEN against M14 v2 chunks.

## Step 7 - Override Path Semantic Preservation: PASS
Direct call to writer._save_chunk_cache with override_config_md5=localcfg_test_xyz
and stub lookup_machine_md5 returning (global_cfg_md5, global_code_md5).
Observed:
  envelope._config_md5 = localcfg_test_xyz  (OVERRIDE_PATH_PASS -- not global lookup)
  envelope._code_md5 = empty string         (partial override: config only, correct)
  ALL_13_FIELDS_PRESENT: PASS
localcfg/virtual-machine override path per feedback_md5_granularity_and_stamping.md preserved.

## Step 8 - No Silent Swallow Regression: PASS
AST walk of all ExceptHandler nodes in writer.py (6 total):
  line 56:  except ImportError: body=[ImportFrom]  -- import fallback, not a swallow
  line 66:  except ImportError: body=[ImportFrom]  -- import fallback, not a swallow
  line 170: except Exception:   body=[Pass]        -- SILENT_SWALLOW (rawdata_index_update_entry)
  line 186: except Exception:   body=[Pass]        -- SILENT_SWALLOW (update_chunk_entry)
  line 188: except Exception:   body=[Try]         -- outer cleanup handler, NOT silent
  line 195: except OSError:     body=[Pass]        -- SILENT_SWALLOW (cleanup unlink)
Silent swallow count: 3 (tester reported 3, CONFIRMED)
No new swallows added by the carve. Outer handler at line 188 does active cleanup (unlink .tmp).
Verbatim preservation per brief S2 and feedback_no_silent_swallow.md.

## Step 9 - No PIA Stale Definitions: PASS
grep def _save_chunk_cache in player_impact_analyzer.py -> rc=1, 0 matches
grep def write_summary_json in player_impact_analyzer.py -> rc=1, 0 matches
grep ^CHUNK_CACHE_VERSION in player_impact_analyzer.py -> rc=1, 0 matches
PIA exports all four symbols only via dual-path import block at lines 219-230.

---

## Subprocess vs In-Process Coverage
| Contract | Mode | Verdict |
|---|---|---|
| C3 chunk envelope write/read | In-process (tempdir) + real v3 chunk read | PASS |
| C4 subprocess import safety | Real subprocess python -c rc=0 no stderr | PASS |
| C5 cycle freedom | Static AST scan + C8-d inject proof | PASS |
| C7 override path | Direct in-process call with stub callable | PASS |
| P1-A1 parity canary | Full pytest subprocess vs M14 mode_1 fixture | PASS |

_save_chunk_cache is invoked in-process during sampling (not a subprocess target),
so in-process round-trip tests are the correct primary mode for C3.

## Regressions in Untouched Areas
None. Full 8-suite: 519 passed / 11 skipped / 0 failed. All 11 skips pre-existing.

## Frontend/Preview
N/A. Backend-only ticket.

## MD5 / Version Invariants
- CHUNK_CACHE_VERSION = 3 in writer.py (canonical). PIA re-exports same value, identity confirmed.
- V3 chunk (M1/mode_1/chunk_0387.json): all 13 envelope fields including _payload_sha256.
- V2 chunk (M14/mode_1/chunk_0001.json): 12/13 fields, _payload_sha256 absent by design for v2.
- Override path: _config_md5 == override value, not global lookup. Verified directly.
- P1-A1 canary 23/23 GREEN against V2 M14 chunks proves backward compatibility intact.

## Brief Contract Checklist
| Contract | Verdict |
|---|---|
| C1: writer.py exists with both symbols carved | PASS |
| C1: PIA re-exports via dual-path import block | PASS |
| C2: P1-A1 canary 23/23 GREEN | PASS |
| C3: Atomic write preserved (tmp + os.replace) | PASS |
| C3: override_config_md5 / override_code_md5 path preserved | PASS |
| C3: rawdata_index_update_entry side-effect fires | PASS (inject-tested) |
| C4: subprocess import safety | PASS |
| C5: cycle freedom (no writer->PIA back-import) | PASS |
| C6: hash composition | SKIPPED (gated on versioning.py export, pre-existing) |
| C7: 519/519 existing tests pass, 11 pre-existing skips | PASS |
| C8: inject-bug TDD (4 scenarios RED->GREEN proven) | PASS |
| Shadow-def trap: 0 stale defs in PIA | PASS |
| Silent swallow count: exactly 3, verbatim preservation | PASS |

## Final Verdict: PASS
All 9 verification steps pass. No regressions found.
The implementation correctly:
1. Carves _save_chunk_cache and write_summary_json into writer.py (215 lines).
2. Eliminates writer->PIA cycle via dependency injection (keyword-only args).
3. Preserves override-md5 stamp path (localcfg/virtual-machine) exactly.
4. Preserves atomic write semantics and exactly 3 silent swallows verbatim from PIA.
5. PIA re-exports all 4 symbols with confirmed identity equality.
6. P1-A1 parity canary 23/23 GREEN -- e2e gold standard.
7. Full 8-suite: 519 passed / 11 skipped / 0 failed -- exact expected count.
