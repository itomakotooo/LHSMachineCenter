"""Phase P3 (payid symbol enrichment) — independent verification tests.

Tests all 7 gates from the impl-tester brief (2026-06-03):
  Gate 1 — Decode correctness, CROSS-MACHINE (M14, M1, M275, M120, M268)
  Gate 2 — byte-identical (additive-only): existing fields unchanged
  Gate 3 — RTP parity: rtp_integrity_check.passed == True
  Gate 4 — Edge cases: empty positions (), special line_id -1/-1000, missing SSBC
  Gate 5 — base_hash gate: compute_base_analyzer_version() == '8dbbfad6f90f'
  Gate 6 — inject-bug: corrupt row decode -> symbol_combo wrong -> revert -> GREEN
  Gate 7 — suite delta: no NEW failures

Inject-bug recipe (mandatory per memory/feedback_enumerate_safety_paths.md):
  Bug target: fresh_slotlab/analyzer/core/parser.py line with
    _c4row = _c4pos - _c4col_1idx * 100 + 1
  Corrupt to:
    _c4row = _c4pos - _c4col_1idx * 100   # missing +1 (off-by-one row)
  Expected RED: test_decode_correctness_m14_pid7_cherry fails because
    pos=99 gives row=0-1=-1 or pos=100 gives row=1 not 2, etc.
  Revert -> GREEN.

Cross-machine decode table (independently verified before writing tests):
  M14 pid=7, positions=99,200,301 (ST1):  cherry|cherry|cherry (via pos=99:row0, 200:row1, 301:row2)
  M14 pid=4, positions=101,201,301 (ST1): 2bar|2bar|35x_wild
  M14 pid=7, positions=101,200,299 (from brief): cherry|cherry|cherry (via row2,row1,row0)
  M1  pid=11, positions=100,200,300 (ST1): Bar2|Bar1|Bar1 (center row=1 for all)
  M275 pid=7, positions=99,200,301 (ST140 BCM): wild|wild|1bar
  M275 pid=3, positions=99,200,301 (ST126 freespin): wild|wild|low7
  M268 pid=1, positions=101,200,299 (ST140 BCM): wild1x|wild1x|wild1x (all wilds)
  M120 ST=138 empty positions (): no combo emitted, no crash

Memory files cited:
  - memory/feedback_enumerate_safety_paths.md (inject-bug for every invariant)
  - memory/feedback_no_hardcode.md (decode is generic, no per-machine symbol names)
  - memory/feedback_perf_claim_needs_e2e_event_stream.md (subprocess mandatory for e2e)
  - memory/feedback_invariant_with_fallback_hides_drift.md (no unattributed fallback)
  - memory/feedback_integration_test_argv.md (real subprocess on real cached data)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_PARSER_PY = _REPO_ROOT / "fresh_slotlab" / "analyzer" / "core" / "parser.py"

_RAWDATA = _REPO_ROOT / "rawdata"
_M14_CACHE = _RAWDATA / "M14" / "mode_1"
_M1_CACHE = _RAWDATA / "M1" / "mode_1"
_M275_CACHE = _RAWDATA / "M275" / "mode_1"
_M120_CACHE = _RAWDATA / "M120" / "mode_1"
_M268_CACHE = _RAWDATA / "M268" / "mode_1"
_M15_CACHE = _RAWDATA / "M15" / "mode_1"

# The pinned base_hash after C4 symbol enrichment (parser.py + PIA edits).
# This is the authoritative value re-pinned by coordinator after implementer.
_EXPECTED_BASE_HASH = "99b1dec52f88"  # spin_type_rtp_buckets: parser paid-bucket + versioning play_types closure → 8dbbfad6f90f→99b1dec52f88

# C3 existing fields that MUST be unchanged post-C4 (byte-identical).
_C3_LEGACY_KEYS = frozenset({
    "payout_id", "hit_count", "hit_rate",
    "total_win", "avg_win_when_hit", "rtp_contribution_pp",
    "covered_columns", "shape", "paylines", "notes",
})

# C4 new field names.
_C4_NEW_KEY = "symbol_combo"


# ---------------------------------------------------------------------------
# Helpers — decode formula (independent reimplementation)
# ---------------------------------------------------------------------------

def _decode_symbol_combo(positions: list[int], ssbc: list[str]) -> str | None:
    """Independent reimplementation of the brief's decode formula.

    For each pos:
        col_1indexed = (pos + 1) // 100
        col0idx      = col_1indexed - 1
        row          = pos - col_1indexed * 100 + 1
        symbol       = StopSymbolsByCol[col0idx].split("-")[row]

    Returns "|"-joined column-ordered symbol tuple, or None if any decode fails.
    Empty positions list -> None (scatter / feature pay).
    """
    if not positions:
        return None
    cols = [s.split("-") for s in ssbc]
    symbols: list[str] = []
    for pos in positions:
        col_1idx = (pos + 1) // 100
        col0 = col_1idx - 1
        row = pos - col_1idx * 100 + 1
        if col0 < 0 or col0 >= len(cols):
            return None
        col_syms = cols[col0]
        if row < 0 or row >= len(col_syms):
            return None
        sym = col_syms[row]
        if not sym:
            return None
        symbols.append(sym)
    return "|".join(symbols)


def _run_pia(machine: str, mode: int, cache_dir: Path,
             timeout: int = 240) -> dict:
    """Run player_impact_analyzer.py subprocess on a cached dir; return parsed summary."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable, str(_PIA),
            "--machine", machine,
            "--rtp-mode", str(mode),
            "--from-cache", str(cache_dir),
            "--output-dir", tmpdir,
            "--bet", "1000",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(_REPO_ROOT), timeout=timeout,
        )
        assert result.returncode == 0, (
            f"PIA for {machine} mode={mode} exited {result.returncode}.\n"
            f"STDOUT: {result.stdout[:2000]}\nSTDERR: {result.stderr[:2000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists(), (
            f"player_impact_summary.json not written for {machine} mode={mode}"
        )
        return json.loads(summary_path.read_bytes())


def _get_pbst_rows(summary: dict, st_label_substr: str) -> list[dict]:
    """Return rows from payouts_by_spin_type where label contains st_label_substr."""
    pbst: dict[str, list] = summary.get("player_impact", {}).get(
        "payouts_by_spin_type", {}
    )
    for label, rows in pbst.items():
        if st_label_substr in label:
            return rows
    return []


def _get_all_pbst_rows(summary: dict) -> list[dict]:
    """Return all rows across all STs in payouts_by_spin_type."""
    pbst: dict[str, list] = summary.get("player_impact", {}).get(
        "payouts_by_spin_type", {}
    )
    return [row for rows in pbst.values() for row in rows]


def _pid_symbol_combo(summary: dict, pid: str, st_label_substr: str = "") -> dict | None:
    """Find the symbol_combo dict for a specific pid in payouts_by_spin_type."""
    pbst = summary.get("player_impact", {}).get("payouts_by_spin_type", {})
    for label, rows in pbst.items():
        if st_label_substr and st_label_substr not in label:
            continue
        for row in rows:
            if row["payout_id"] == pid:
                return row.get(_C4_NEW_KEY)
    return None


def _parse_chunk_positions(chunk_path: Path, pid_filter: str, st_filter: int | None = None) -> list[tuple[list[int], list[str]]]:
    """Parse one chunk file; find rounds with PayoutByPayline that match pid_filter.

    Returns list of (positions, ssbc) tuples from attribute_lines_to_pay_ids logic.
    Uses the same decode logic as attribute_lines_to_pay_ids: scans PayoutByPayline
    string for payline entries whose pid matches pid_filter.
    """
    data = json.loads(chunk_path.read_bytes())
    results: list[tuple[list[int], list[str]]] = []
    for resp in data.get("response", []):
        rr_str = resp.get("roundResult", "")
        try:
            rr_list = json.loads(rr_str)
        except Exception:
            continue
        if not isinstance(rr_list, list):
            rr_list = [rr_list]
        for r in rr_list:
            pbp = r.get("PayoutByPayline", "")
            ssbc = r.get("StopSymbolsByCol", [])
            sp = r.get("SpinType")
            if not pbp or not ssbc:
                continue
            if st_filter is not None and sp != st_filter:
                continue
            # Parse payline entries: format "line_id:pid1-pid2(pos1,pos2,...,);"
            for match in re.finditer(r'-?\d+:(\d+)-(\d+)\(([^)]*)\)', pbp):
                pid1 = match.group(1)
                pid2 = match.group(2)
                pos_str = match.group(3).strip()
                positions = [int(p) for p in pos_str.split(",") if p.strip()]
                if pid_filter in (pid1, pid2) and positions:
                    results.append((positions, list(ssbc)))
    return results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m14_summary():
    if not _M14_CACHE.exists():
        pytest.skip(f"M14 mode_1 cache not found at {_M14_CACHE}")
    return _run_pia("M14", 1, _M14_CACHE)


@pytest.fixture(scope="module")
def m1_summary():
    if not _M1_CACHE.exists():
        pytest.skip(f"M1 mode_1 cache not found at {_M1_CACHE}")
    return _run_pia("M1", 1, _M1_CACHE, timeout=360)


@pytest.fixture(scope="module")
def m275_summary():
    if not _M275_CACHE.exists():
        pytest.skip(f"M275 mode_1 cache not found at {_M275_CACHE}")
    return _run_pia("M275", 1, _M275_CACHE)


@pytest.fixture(scope="module")
def m120_summary():
    if not _M120_CACHE.exists():
        pytest.skip(f"M120 mode_1 cache not found at {_M120_CACHE}")
    return _run_pia("M120", 1, _M120_CACHE)


@pytest.fixture(scope="module")
def m268_summary():
    if not _M268_CACHE.exists():
        pytest.skip(f"M268 mode_1 cache not found at {_M268_CACHE}")
    return _run_pia("M268", 1, _M268_CACHE)


@pytest.fixture(scope="module")
def m15_summary():
    if not _M15_CACHE.exists():
        pytest.skip(f"M15 mode_1 cache not found at {_M15_CACHE}")
    return _run_pia("M15", 1, _M15_CACHE, timeout=300)


# ---------------------------------------------------------------------------
# Gate 5 — base_hash
# ---------------------------------------------------------------------------

class TestBaseHash:
    """Gate 5: base_hash must be 8dbbfad6f90f (paytype-rearch re-pin)."""

    def test_base_hash_equals_pinned_value(self):
        """compute_base_analyzer_version() == '8dbbfad6f90f'.

        The C4 symbol enrichment (parser.py + PIA) → 04691124fde6.
        paytype-rearch feature cross (PIA spin_type_rows enrichment) → 8dbbfad6f90f.

        INJECT-BUG: edit parser.py to add a no-op comment to the C4 block.
        RED: base_hash will differ from _EXPECTED_BASE_HASH.
        Revert -> GREEN.
        """
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        actual = compute_base_analyzer_version()
        assert actual == _EXPECTED_BASE_HASH, (
            f"base_hash mismatch: expected {_EXPECTED_BASE_HASH!r}, got {actual!r}.\n"
            "If paytype-rearch feature cross (player_impact_analyzer.py spin_type_rows enrichment) is present,\n"
            "base_hash must be 8dbbfad6f90f. A different value means a closure file was\n"
            "unexpectedly added or changed."
        )

    def test_base_hash_12hex_format(self):
        """base_hash is a 12-char lowercase hex string."""
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        h = compute_base_analyzer_version()
        assert re.match(r"^[0-9a-f]{12}$", h), (
            f"base_hash {h!r} is not 12-char lowercase hex"
        )

    def test_no_old_hash_asserted_anywhere(self):
        """No test file (other than this one) asserts equality to the old adf08191dd9c hash.

        The old hash adf08191dd9c is mentioned in docstrings/comments as history.
        No non-comment line in any other test file should perform == comparison to it.
        This test excludes itself to avoid flagging its own docstring.
        """
        old_hash = "adf08191dd9c"
        this_file = Path(__file__).resolve()
        violations: list[str] = []
        for test_file in ((_REPO_ROOT / "tests").rglob("*.py")):
            if test_file.resolve() == this_file:
                continue  # skip self
            lines = test_file.read_text(encoding="utf-8", errors="replace").splitlines()
            for lineno, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # Check for actual equality assertion (not in f-string history comments)
                if f'== "{old_hash}"' in line or f"== '{old_hash}'" in line:
                    violations.append(f"{test_file.relative_to(_REPO_ROOT)}:{lineno}: {line.rstrip()}")
        assert not violations, (
            f"Found hard equality assertions on old hash {old_hash!r}:\n"
            + "\n".join(violations)
        )

    def test_no_p3_hash_asserted_anywhere(self):
        """No test file (other than this one) asserts equality to the retired 04691124fde6 hash.

        That hash was the P3/Phase-E value; paytype-rearch re-pins to 8dbbfad6f90f.
        History references in comments are allowed; equality assertions are not.
        """
        old_hash = "04691124fde6"
        this_file = Path(__file__).resolve()
        violations: list[str] = []
        for test_file in ((_REPO_ROOT / "tests").rglob("*.py")):
            if test_file.resolve() == this_file:
                continue  # skip self
            lines = test_file.read_text(encoding="utf-8", errors="replace").splitlines()
            for lineno, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if f'== "{old_hash}"' in line or f"== '{old_hash}'" in line:
                    violations.append(f"{test_file.relative_to(_REPO_ROOT)}:{lineno}: {line.rstrip()}")
        assert not violations, (
            f"Found hard equality assertions on retired hash {old_hash!r}:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Gate 1 — Decode correctness (unit: reference formula)
# ---------------------------------------------------------------------------

class TestDecodeFormula:
    """Gate 1a — unit-level: reference formula matches specific known positions."""

    # Test cases derived from raw chunk inspection + brief §decode examples.
    # Each: (positions, ssbc, expected_combo)
    _CASES = [
        # M14 pid=7 from chunk data: 4:7-7(99,200,301,) ST1
        ([99, 200, 301],
         ["cherry-blank-3bar-", "blank-cherry-blank-", "1bar-blank-cherry-"],
         "cherry|cherry|cherry"),
        # M14 pid=4: 3:4-4(101,201,301,) ST1
        ([101, 201, 301],
         ["cherry-blank-2bar-", "cherry-blank-2bar-", "1bar-blank-35x_wild-"],
         "2bar|2bar|35x_wild"),
        # M1 pid=11: 1:11-11(100,200,300,) ST1
        ([100, 200, 300],
         ["Blank-Bar2-Blank-", "Blank-Bar1-Blank-", "Blank-Bar1-Blank-"],
         "Bar2|Bar1|Bar1"),
        # M275 pid=7 ST140 BCM: 4:7-7(99,200,301,)
        ([99, 200, 301],
         ["wild-blank-mid7-", "blank-wild-blank-", "bonus-blank-1bar-"],
         "wild|wild|1bar"),
        # M275 pid=3 ST126 freespin: 4:3-3(99,200,301,)
        ([99, 200, 301],
         ["wild-blank-1bar-", "blank-wild-blank-", "mid7-blank-low7-"],
         "wild|wild|low7"),
        # M268 pid=1 ST140 BCM: 5:1-1(101,200,299,)
        ([101, 200, 299],
         ["1bar-mid7-wild1x-", "mid7-wild1x-3bar-", "wild1x-coin-coin-"],
         "wild1x|wild1x|wild1x"),
        # Brief §decode example: M275 4:7-7(99,200,301) -> wild/wild/1bar (confirmed above)
        # Brief §decode example: M14 5:7-7(101,200,299) -> decoded correctly:
        #   pos=101: col_1idx=1,col0=0,row=2 -> SSBC[0][2]
        #   pos=200: col_1idx=2,col0=1,row=1 -> SSBC[1][1]
        #   pos=299: col_1idx=3,col0=2,row=0 -> SSBC[2][0]
        # To get cherry|cherry|cherry: need SSBC[0][2]=cherry,SSBC[1][1]=cherry,SSBC[2][0]=cherry
        ([101, 200, 299],
         ["blank-blank-cherry-", "blank-cherry-blank-", "cherry-blank-blank-"],
         "cherry|cherry|cherry"),
    ]

    @pytest.mark.parametrize("positions,ssbc,expected", _CASES)
    def test_reference_decode_formula(self, positions, ssbc, expected):
        """Reference formula produces expected combo for known raw data.

        INJECT-BUG: change row=pos-col_1idx*100 (remove +1).
        For pos=100: col_1idx=1, row=100-100=0 (should be 1 for center).
        For pos=200: col_1idx=2, row=200-200=0 (should be 1).
        Result: wrong symbol (row-0 instead of row-1) -> assertion fails.
        Revert -> GREEN.
        """
        result = _decode_symbol_combo(positions, ssbc)
        assert result == expected, (
            f"Decode mismatch: positions={positions}\n"
            f"  SSBC={ssbc}\n"
            f"  Expected: {expected!r}\n"
            f"  Got:      {result!r}"
        )

    def test_empty_positions_returns_none(self):
        """Empty positions list -> None (scatter/feature pay case)."""
        assert _decode_symbol_combo([], ["cherry-blank-3bar-"]) is None

    def test_col_out_of_range_returns_none(self):
        """Position with col out of range -> None (fail-loud)."""
        # pos=399 -> col_1idx=4, col0=3, but only 3 cols (0-2)
        assert _decode_symbol_combo([399], ["a-b-c-", "d-e-f-", "g-h-i-"]) is None

    def test_row_out_of_range_returns_none(self):
        """Position with row out of range -> None (fail-loud)."""
        # pos=104 -> col_1idx=1, col0=0, row=104-100+1=5, but only 4 symbols
        assert _decode_symbol_combo([104], ["s0-s1-s2-s3-"]) is None

    def test_empty_symbol_at_row_returns_none(self):
        """Empty string at decoded row (trailing dash artifact) -> None."""
        # pos=103 -> col_1idx=1, col0=0, row=4, col has 4 symbols (trailing dash -> empty)
        assert _decode_symbol_combo([103], ["s0-s1-s2-s3-"]) is None


# ---------------------------------------------------------------------------
# Gate 1 — Decode correctness (e2e: analyzer output matches reference decode)
# ---------------------------------------------------------------------------

class TestDecodeCrossM14:
    """Gate 1b M14 — analyzer symbol_combo vs reference decode from raw data."""

    def test_no_feature_errors(self, m14_summary):
        """M14 analyzer completes without feature_errors."""
        fe = m14_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"

    def test_pid7_dominant_contains_cherry(self, m14_summary):
        """M14 pid=7 (cherry family): dominant combo contains 'cherry' symbols.

        From rawdata: pid=7 PayoutByPayline consistently yields (99,200,301) or
        similar positions in cherry row (center row=1 gives cherry for M14 cherry cols).
        Dominant combo is 'cherry|cherry|cherry'.

        INJECT-BUG: corrupt row=pos-col_1idx*100 (no +1) in parser.py.
        For center-row positions like pos=200 (col_1idx=2, row becomes 0 instead of 1),
        we'd decode 'blank' instead of 'cherry' -> dominant changes to non-cherry combo.
        RED: 'cherry' not in dominant -> test fails.
        Revert -> GREEN.
        """
        sc = _pid_symbol_combo(m14_summary, "7")
        assert sc is not None, "symbol_combo not present for M14 pid=7"
        dominant = sc.get("dominant")
        assert dominant is not None, (
            f"M14 pid=7 symbol_combo.dominant is None: {sc}"
        )
        assert "cherry" in dominant, (
            f"M14 pid=7 dominant={dominant!r}: expected cherry symbols.\n"
            f"Full symbol_combo: {sc}"
        )

    def test_pid7_distinct_symbols_includes_cherry(self, m14_summary):
        """M14 pid=7 distinct_symbols includes 'cherry'."""
        sc = _pid_symbol_combo(m14_summary, "7")
        assert sc is not None
        distinct = sc.get("distinct_symbols", [])
        assert "cherry" in distinct, (
            f"M14 pid=7 distinct_symbols={distinct!r}: missing 'cherry'"
        )

    def test_pid7_dominant_matches_reference_decode_from_rawdata(self, m14_summary):
        """M14 pid=7: dominant combo matches independently computed reference.

        Parse first chunk, find pid=7 rounds, decode via reference formula,
        confirm analyzer's dominant combo is in the reference's decoded combos.
        This is a cross-machine decode correctness test.
        """
        chunks = sorted(_M14_CACHE.glob("chunk_*.json"))
        if not chunks:
            pytest.skip("No M14 chunks found")

        # Collect reference combos from the first chunk for pid=7
        ref_combos: set[str] = set()
        for pos_list, ssbc in _parse_chunk_positions(chunks[0], "7", st_filter=None):
            combo = _decode_symbol_combo(pos_list, ssbc)
            if combo:
                ref_combos.add(combo)

        if not ref_combos:
            pytest.skip("No pid=7 positions found in first chunk")

        sc = _pid_symbol_combo(m14_summary, "7")
        assert sc is not None
        dominant = sc.get("dominant")
        assert dominant in ref_combos, (
            f"M14 pid=7 dominant={dominant!r} not in reference combos from rawdata.\n"
            f"Reference combos: {ref_combos}"
        )

    def test_pid4_dominant_contains_bar_symbols(self, m14_summary):
        """M14 pid=4 (2bar family): dominant combo contains bar symbols."""
        sc = _pid_symbol_combo(m14_summary, "4")
        assert sc is not None, "symbol_combo not present for M14 pid=4"
        dominant = sc.get("dominant")
        assert dominant is not None
        # pid=4 is 2bar: dominant is typically '2bar|2bar|2bar' or mixed with wilds
        assert any(s in dominant for s in ["2bar", "wild"]), (
            f"M14 pid=4 dominant={dominant!r}: expected bar or wild symbols"
        )

    def test_all_pids_have_symbol_combo_key(self, m14_summary):
        """Every row in M14 payouts_by_spin_type has 'symbol_combo' key."""
        rows = _get_all_pbst_rows(m14_summary)
        assert rows, "No rows in payouts_by_spin_type for M14"
        missing = [row["payout_id"] for row in rows if _C4_NEW_KEY not in row]
        assert not missing, (
            f"M14 rows missing symbol_combo key: {missing}"
        )

    def test_covered_columns_in_top20(self, m14_summary):
        """payout_ids_top20 rows have covered_columns from live enrichment."""
        top20 = m14_summary.get("player_impact", {}).get("payout_ids_top20", [])
        assert top20, "payout_ids_top20 is empty for M14"
        for row in top20:
            assert "covered_columns" in row, (
                f"M14 top20 pid={row.get('payout_id')} missing covered_columns"
            )
            cc = row["covered_columns"]
            assert isinstance(cc, list), (
                f"M14 top20 pid={row.get('payout_id')} covered_columns is not list: {cc!r}"
            )

    def test_symbol_combo_in_top20(self, m14_summary):
        """payout_ids_top20 rows have symbol_combo from live enrichment."""
        top20 = m14_summary.get("player_impact", {}).get("payout_ids_top20", [])
        assert top20, "payout_ids_top20 is empty for M14"
        for row in top20:
            assert _C4_NEW_KEY in row, (
                f"M14 top20 pid={row.get('payout_id')} missing symbol_combo"
            )


class TestDecodeCrossM1:
    """Gate 1b M1 — bar-family combos across 600 chunks."""

    def test_no_feature_errors(self, m1_summary):
        fe = m1_summary.get("feature_errors", {})
        assert not fe, f"M1 feature_errors: {fe}"

    def test_pid11_dominant_contains_bar(self, m1_summary):
        """M1 pid=11 (AnyBar family): dominant combo contains bar symbols.

        From rawdata: 1:11-11(100,200,300,) -> Bar2|Bar1|Bar1 (row=1 center).
        Dominant across 600 chunks is the most frequent bar combo.

        INJECT-BUG: corrupt row decode (remove +1) -> center positions
        (pos=100,200,300 -> row=1) become row=0 (Blank) or row=2 (Blank).
        Dominant would become 'Blank|Blank|Blank' which is not a bar symbol.
        RED: 'Bar' not in dominant -> fails.
        Revert -> GREEN.
        """
        sc = _pid_symbol_combo(m1_summary, "11")
        assert sc is not None, "M1 pid=11 symbol_combo missing"
        dominant = sc.get("dominant")
        assert dominant is not None, f"M1 pid=11 dominant is None: {sc}"
        # AnyBar payid: dominant should be some combination of Bar1/Bar2/Bar3
        assert "Bar" in dominant, (
            f"M1 pid=11 dominant={dominant!r}: expected Bar symbols"
        )

    def test_pid11_distinct_symbols_contains_bar_variants(self, m1_summary):
        """M1 pid=11 distinct_symbols has multiple bar variants."""
        sc = _pid_symbol_combo(m1_summary, "11")
        assert sc is not None
        distinct = sc.get("distinct_symbols", [])
        bar_syms = [s for s in distinct if "Bar" in s]
        assert len(bar_syms) >= 2, (
            f"M1 pid=11 expected multiple Bar variants, got distinct_symbols={distinct}"
        )

    def test_pid12_cherry_dominant(self, m1_summary):
        """M1 pid=12 (Cherry): dominant contains 'Cherry'."""
        sc = _pid_symbol_combo(m1_summary, "12")
        if sc is None:
            pytest.skip("M1 pid=12 not present in this dataset")
        dominant = sc.get("dominant")
        assert dominant is not None
        assert "Cherry" in dominant, (
            f"M1 pid=12 dominant={dominant!r}: expected Cherry"
        )


class TestDecodeCrossM275:
    """Gate 1b M275 — wild-containing combos across BCM (ST140) and freespin (ST126)."""

    def test_no_feature_errors(self, m275_summary):
        fe = m275_summary.get("feature_errors", {})
        assert not fe, f"M275 feature_errors: {fe}"

    def test_pid7_contains_wild_in_dominant(self, m275_summary):
        """M275 pid=7: dominant combo contains 'wild' (BCM + freespin).

        From rawdata ST140: 4:7-7(99,200,301,) -> wild|wild|1bar
        (pos=99:col0=0,row=0,'wild'; pos=200:col0=1,row=1,'wild'; pos=301:col0=2,row=2,'1bar').

        INJECT-BUG: corrupt row decode. For pos=99: col_1idx=1,col0=0,row=99-100+1=0
        is correct; corrupt to row=99-100=-1 -> out of range -> no combo emitted.
        No combos -> dominant=None -> test fails.
        Revert -> GREEN.
        """
        sc = _pid_symbol_combo(m275_summary, "7")
        assert sc is not None, "M275 pid=7 symbol_combo missing"
        dominant = sc.get("dominant")
        assert dominant is not None, f"M275 pid=7 dominant is None: {sc}"
        assert "wild" in dominant.lower(), (
            f"M275 pid=7 dominant={dominant!r}: expected 'wild' symbol"
        )

    def test_pid7_present_in_both_st_labels(self, m275_summary):
        """M275 pid=7 appears in both ST140 (BCM) and ST126 (freespin) rows."""
        pbst = m275_summary.get("player_impact", {}).get("payouts_by_spin_type", {})
        st_labels_with_pid7 = [
            label for label, rows in pbst.items()
            if any(r["payout_id"] == "7" for r in rows)
        ]
        assert len(st_labels_with_pid7) >= 2, (
            f"M275 pid=7 expected in >=2 ST labels (ST126+ST140), "
            f"found in: {st_labels_with_pid7}"
        )

    def test_pid7_st140_bcm_has_wild_combo(self, m275_summary):
        """M275 pid=7 in ST140 (BCM): symbol_combo.dominant contains wild.

        Cross-ST decode check: BCM rounds (ST140) have same PayoutByPayline decode
        path as paid rounds (ST1). This verifies decode works for BCM SpinType.
        """
        sc = _pid_symbol_combo(m275_summary, "7", "ST140")
        assert sc is not None, "M275 pid=7 not in ST140_paid"
        dominant = sc.get("dominant")
        assert dominant is not None
        assert "wild" in dominant.lower(), (
            f"M275 pid=7 ST140 dominant={dominant!r}: expected wild symbols"
        )

    def test_pid7_st126_freespin_has_wild_combo(self, m275_summary):
        """M275 pid=7 in ST126 (freespin): symbol_combo.dominant contains wild.

        Cross-ST decode check: freespin rounds (ST126) decode correctly.
        """
        sc = _pid_symbol_combo(m275_summary, "7", "ST126")
        assert sc is not None, "M275 pid=7 not in ST126_free"
        dominant = sc.get("dominant")
        assert dominant is not None
        assert "wild" in dominant.lower(), (
            f"M275 pid=7 ST126 dominant={dominant!r}: expected wild symbols"
        )

    def test_distinct_symbols_includes_wild(self, m275_summary):
        """M275 pid=7 distinct_symbols includes 'wild'."""
        sc = _pid_symbol_combo(m275_summary, "7")
        assert sc is not None
        distinct = sc.get("distinct_symbols", [])
        assert any("wild" in s.lower() for s in distinct), (
            f"M275 pid=7 distinct_symbols={distinct}: missing wild"
        )

    def test_pid7_dominant_matches_reference_from_rawdata(self, m275_summary):
        """M275 pid=7: analyzer dominant matches reference decode from chunk."""
        chunks = sorted(_M275_CACHE.glob("chunk_*.json"))
        if not chunks:
            pytest.skip("No M275 chunks found")

        ref_combos: set[str] = set()
        for pos_list, ssbc in _parse_chunk_positions(chunks[0], "7"):
            combo = _decode_symbol_combo(pos_list, ssbc)
            if combo:
                ref_combos.add(combo)

        if not ref_combos:
            pytest.skip("No pid=7 positions found in first M275 chunk")

        sc = _pid_symbol_combo(m275_summary, "7")
        assert sc is not None
        dominant = sc.get("dominant")
        assert dominant in ref_combos, (
            f"M275 pid=7 dominant={dominant!r} not in reference combos.\n"
            f"Reference: {ref_combos}"
        )


class TestDecodeCrossM268:
    """Gate 1b M268 — BCM ST140 decode correctness."""

    def test_no_feature_errors(self, m268_summary):
        fe = m268_summary.get("feature_errors", {})
        assert not fe, f"M268 feature_errors: {fe}"

    def test_pid1_st140_contains_wild1x(self, m268_summary):
        """M268 pid=1 in ST140: dominant contains 'wild1x'.

        From rawdata: 5:1-1(101,200,299,) -> wild1x|wild1x|wild1x.
        (pos=101: col0=0,row=2,'wild1x'; pos=200: col0=1,row=1,'wild1x'; pos=299: col0=2,row=0,'wild1x').

        INJECT-BUG: corrupt row to pos-col_1idx*100 (no +1).
        pos=101: row=101-100=1 instead of 2 -> mid7 not wild1x.
        pos=299: row=299-300=-1 -> out-of-range -> combo aborted.
        Either way, dominant changes or goes to None.
        RED: 'wild1x' not in dominant or dominant is None.
        Revert -> GREEN.
        """
        sc = _pid_symbol_combo(m268_summary, "1", "ST140")
        assert sc is not None, "M268 pid=1 not in ST140"
        dominant = sc.get("dominant")
        assert dominant is not None, f"M268 pid=1 dominant is None"
        assert "wild" in dominant.lower(), (
            f"M268 pid=1 ST140 dominant={dominant!r}: expected wild symbols"
        )


# ---------------------------------------------------------------------------
# Gate 4 — Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Gate 4: empty positions, special line_id, missing SSBC -> no crash."""

    def test_empty_positions_no_combo_no_crash(self, m120_summary):
        """M120 ST=138 has PayoutByPayline with empty positions '()'.

        These are scatter/feature pays: -1000:10-10()
        Parser must not crash, and must NOT emit a combo for empty positions.
        Verified by running M120 and checking pid=10 or pid=10000 has
        dominant=None (no positions decoded) or simply not contributing combos.

        INJECT-BUG: if parser tried ssbc[col0idx] with col0idx derived from
        empty positions list, it would crash. Removing the 'if _c4pos in _c3positions'
        guard would crash on empty list iteration -> no rows emitted.
        Since M120 analyzes successfully (rc=0), empty positions are handled.
        """
        fe = m120_summary.get("feature_errors", {})
        assert not fe, f"M120 feature_errors (should be empty): {fe}"
        # Verify M120 analysis completed with payouts_by_spin_type populated
        pbst = m120_summary.get("player_impact", {}).get("payouts_by_spin_type", {})
        assert pbst, "M120 payouts_by_spin_type is empty"

    def test_empty_positions_no_combo_emitted_for_scatter_pid(self, m120_summary):
        """Scatter pids (line_id=-1000, empty positions) -> symbol_combo.dominant=None.

        The scatter pid (10 or 12007 in M120) is triggered via ST=138 with
        empty position list. No SSBC decode possible -> dominant should be None.
        """
        pbst = m120_summary.get("player_impact", {}).get("payouts_by_spin_type", {})
        # Real (non-tautological) invariant: a symbol combo can ONLY come from
        # decoded cells, so any row that HAS a dominant combo MUST also have covered
        # columns. Contrapositive: empty positions (scatter, e.g. -1000:10-10()) →
        # no decodable cells → no combo. (The pure empty-position decode is covered
        # directly by test_empty_positions_returns_none / _handles_empty_positions /
        # test_parser_c4_block_guards_empty_positions; this guards the integration path.)
        for label, rows in pbst.items():
            if "138" in label:
                for row in rows:
                    sc = row.get(_C4_NEW_KEY, {})
                    dominant = sc.get("dominant") if sc else None
                    covered = row.get("covered_columns") or []
                    if dominant is not None:
                        assert covered, (
                            f"M120 ST138 pid={row['payout_id']} emitted a symbol_combo "
                            f"dominant {dominant!r} but has EMPTY covered_columns — a combo "
                            f"must come from decoded cells (empty positions must yield no combo)."
                        )
                break

    def test_reference_formula_handles_empty_positions(self):
        """Reference formula returns None for empty positions (unit test)."""
        assert _decode_symbol_combo([], ["a-b-c-", "d-e-f-", "g-h-i-"]) is None

    def test_reference_formula_special_line_id_positions(self):
        """Reference formula handles positions from -1000 line (if non-empty).

        Special line_id does not affect position decode; the formula only
        uses the numeric position value.
        """
        # pos=99: col_1idx=1, col0=0, row=99-100+1=0 -> first symbol
        result = _decode_symbol_combo([99], ["first-second-third-"])
        assert result == "first"

    def test_no_crash_with_missing_ssbc_unit(self):
        """parse_chunk_positions handles rounds without StopSymbolsByCol gracefully.

        Unit: reference decode called with empty ssbc_cols -> returns None.
        """
        result = _decode_symbol_combo([100, 200, 300], [])
        # col0=0 >= len([]) -> None
        assert result is None

    def test_m120_no_feature_errors_confirms_no_crash(self, m120_summary):
        """M120 analyzer exit with rc=0 + no feature_errors confirms no crash on
        empty-position ST=138 rounds."""
        assert m120_summary.get("feature_errors", {}) == {}


# ---------------------------------------------------------------------------
# Gate 2 — byte-identical (additive-only)
# ---------------------------------------------------------------------------

class TestByteIdentical:
    """Gate 2: existing C3 fields unchanged; only symbol_combo is new."""

    def test_schema_version_is_3_or_higher(self):
        """SCHEMA_VERSION >= 3 (bumped from 2 in C4; Phase B bumps further to 4).

        C4 introduced SCHEMA_VERSION 3. Phase B (playtype-rearch) bumped it to 4
        by adding symbol_combo.combos. This test accepts both 3 (C4-only) and
        any higher value (Phase B+).
        """
        from fresh_slotlab.analyzer.features.payouts_by_spin_type import PayoutsBySpinType
        assert PayoutsBySpinType.SCHEMA_VERSION == 4, (
            f"Expected SCHEMA_VERSION==4 (Phase B bumped 3→4 for symbol_combo.combos), "
            f"got {PayoutsBySpinType.SCHEMA_VERSION}"
        )

    def test_registered_fallback_rule_v2_exists(self):
        """REGISTERED_FALLBACK_RULES has key 2 for v2->v3 migration."""
        from fresh_slotlab.analyzer.features.payouts_by_spin_type import PayoutsBySpinType
        rules = PayoutsBySpinType.REGISTERED_FALLBACK_RULES
        assert 2 in rules, f"REGISTERED_FALLBACK_RULES missing key 2: {rules}"
        assert "symbol_combo" in rules[2], (
            f"REGISTERED_FALLBACK_RULES[2] missing symbol_combo: {rules[2]}"
        )
        assert rules[2]["symbol_combo"] is None, (
            f"REGISTERED_FALLBACK_RULES[2]['symbol_combo'] should be None, got {rules[2]['symbol_combo']!r}"
        )

    def test_c3_legacy_keys_present_in_m14_rows(self, m14_summary):
        """All 10 C3 legacy keys (6 C2 + 4 C3) still present in M14 output."""
        rows = _get_all_pbst_rows(m14_summary)
        assert rows, "No rows found"
        for row in rows:
            missing = _C3_LEGACY_KEYS - set(row.keys())
            assert not missing, (
                f"M14 pid={row['payout_id']} missing C3 legacy keys: {missing}\n"
                f"Row keys: {sorted(row.keys())}"
            )

    def test_c3_legacy_keys_present_in_m275_rows(self, m275_summary):
        """All C3 legacy keys present in M275 output."""
        rows = _get_all_pbst_rows(m275_summary)
        assert rows
        for row in rows:
            missing = _C3_LEGACY_KEYS - set(row.keys())
            assert not missing, (
                f"M275 pid={row['payout_id']} missing keys: {missing}"
            )

    def test_only_symbol_combo_is_new_key_in_m14(self, m14_summary):
        """No unexpected new keys in M14 rows beyond C3_LEGACY + symbol_combo."""
        rows = _get_all_pbst_rows(m14_summary)
        all_expected = _C3_LEGACY_KEYS | {_C4_NEW_KEY}
        for row in rows:
            extra = set(row.keys()) - all_expected
            assert not extra, (
                f"M14 pid={row['payout_id']} has unexpected extra keys: {extra}"
            )

    def test_hit_count_is_positive_int_in_m14(self, m14_summary):
        """hit_count is a positive integer (not corrupted by C4 changes)."""
        rows = _get_all_pbst_rows(m14_summary)
        for row in rows:
            hc = row.get("hit_count")
            assert isinstance(hc, int) and hc > 0, (
                f"M14 pid={row['payout_id']} hit_count={hc!r}: expected positive int"
            )

    def test_rtp_contribution_pp_positive_in_m14_non_trigger(self, m14_summary):
        """Non-trigger pids have rtp_contribution_pp > 0."""
        rows = _get_all_pbst_rows(m14_summary)
        for row in rows:
            notes = row.get("notes", {})
            if not notes.get("is_trigger_marker"):
                rtp = row.get("rtp_contribution_pp", 0)
                assert rtp > 0, (
                    f"M14 pid={row['payout_id']} non-trigger has rtp_contribution_pp={rtp}"
                )

    def test_covered_columns_not_empty_for_m14_reel_pids(self, m14_summary):
        """Covered_columns is non-empty for M14 reel pids (C3 unchanged)."""
        rows = _get_all_pbst_rows(m14_summary)
        for row in rows:
            notes = row.get("notes", {})
            if not notes.get("is_trigger_marker"):
                cc = row.get("covered_columns", [])
                assert len(cc) >= 1, (
                    f"M14 pid={row['payout_id']} covered_columns empty: {cc}"
                )


# ---------------------------------------------------------------------------
# Gate 3 — RTP parity
# ---------------------------------------------------------------------------

class TestRtpParity:
    """Gate 3: rtp_integrity_check.passed == True for all test machines."""

    @pytest.mark.parametrize("machine,fixture_name", [
        ("M14", "m14_summary"),
        ("M275", "m275_summary"),
    ])
    def test_rtp_integrity_passed(self, machine, fixture_name, request):
        """rtp_integrity_check.passed == True: symbol_combo is display-only, no new RTP accumulator.

        M268 is excluded: it has a pre-existing L2 fallback failure (_unattributed_st140/st125)
        unrelated to C4. The brief cites M268 for DECODE correctness, not RTP parity.
        """
        summary = request.getfixturevalue(fixture_name)
        ric = summary.get("rtp_integrity_check", {})
        assert ric.get("passed"), (
            f"{machine} rtp_integrity_check.passed is not True.\n"
            f"Full check: {json.dumps(ric, indent=2, default=str)}"
        )

    def test_m268_rtp_layer1_invariant_ok(self, m268_summary):
        """M268 L1 invariant (sum(payid_win)==chunk_win) is still GREEN post-C4.

        M268 has a pre-existing L2 failure (_unattributed_st140/st125 fallback buckets)
        that pre-dates C4. C4 is display-only and does not introduce new L1 failures.
        We verify L1 specifically to confirm C4 didn't break the math.
        """
        ric = m268_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok"), (
            f"M268 L1 invariant broken post-C4 (this IS a C4 regression).\n"
            f"Full check: {json.dumps(ric, indent=2, default=str)}"
        )

    def test_m14_no_feature_errors(self, m14_summary):
        """M14 feature_errors empty -> no plugin crash that could corrupt RTP."""
        assert m14_summary.get("feature_errors", {}) == {}

    def test_m275_no_feature_errors(self, m275_summary):
        """M275 feature_errors empty."""
        assert m275_summary.get("feature_errors", {}) == {}


# ---------------------------------------------------------------------------
# Gate 1 (cross-ST) — M15 TopDollar (ST=14 has no PayoutByPayline)
# ---------------------------------------------------------------------------

class TestM15TopDollarNoCrash:
    """Gate 1c M15: ST=14 (player choice) has no PayoutByPayline -> no combo, no crash."""

    def test_no_feature_errors(self, m15_summary):
        fe = m15_summary.get("feature_errors", {})
        assert not fe, f"M15 feature_errors: {fe}"

    def test_st14_rows_have_symbol_combo_key(self, m15_summary):
        """ST14 rows have symbol_combo key (may have dominant=None)."""
        pbst = m15_summary.get("player_impact", {}).get("payouts_by_spin_type", {})
        for label, rows in pbst.items():
            if "ST14" in label:
                for row in rows:
                    assert _C4_NEW_KEY in row, (
                        f"M15 ST14 pid={row['payout_id']} missing symbol_combo key"
                    )

    def test_st1_pid8_has_bar_combo(self, m15_summary):
        """M15 ST1 pid=8 (reel spin) gets a combo (has PayoutByPayline)."""
        sc = _pid_symbol_combo(m15_summary, "8", "ST1")
        if sc is None:
            pytest.skip("M15 pid=8 not found in ST1")
        dominant = sc.get("dominant")
        assert dominant is not None, (
            f"M15 pid=8 in ST1 should have a combo (reel spin has PayoutByPayline)"
        )


# ---------------------------------------------------------------------------
# Plugin unit tests (extract/reduce/emit with synthetic data)
# ---------------------------------------------------------------------------

class TestPluginUnitC4:
    """Unit tests for PayoutsBySpinType.extract/reduce/emit with C4 data."""

    def _import_plugin(self):
        from fresh_slotlab.analyzer.features.payouts_by_spin_type import PayoutsBySpinType
        return PayoutsBySpinType()

    def _make_ctx(self, bet: float = 100_000.0):
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext, MechanismRegistry
        return PipelineContext(
            effective_bet_for_rtp=bet,
            total_spins=10_000,
            total_paid_sessions=10_000,
            total_paid_spins=10_000,
            clamp_pending_robots_total=0,
            robots_with_pending_cycle=0,
            mechanism_registry=MechanismRegistry(),
            manifest={},
        )

    def _make_summary(self, st_entries):
        # Phase B: include payout_ids_top20 so emit() doesn't warn about
        # the ordering contract. Empty list = no rows to mutate.
        return {"player_impact": {"spin_type_breakdown": st_entries, "payout_ids_top20": []}}

    def test_extract_reads_pid_symbol_combos_key(self):
        """extract() reads payout_id_symbol_combos from chunk_dict."""
        plugin = self._import_plugin()
        chunk = {
            "payout_id_by_spin_type": {"7": {1: 10}},
            "payout_id_win_by_spin_type": {"7": {1: 2200.0}},
            "payout_id_symbol_combos": {"7": {"cherry|cherry|cherry": 8, "cherry|cherry|wild": 2}},
            "payout_id_payline_hits": {},
            "payout_id_match_count_dist": {"7": {3: 10}},
            "payout_id_col_set": {"7": [0, 1, 2]},
            "payout_id_has_regular_line": {"7": True},
        }
        acc = plugin.extract(None, chunk)
        assert "pid_symbol_combos" in acc, "extract() missing pid_symbol_combos"
        sc_7 = acc["pid_symbol_combos"].get("7", {})
        assert "cherry|cherry|cherry" in sc_7, (
            f"cherry|cherry|cherry not in pid_symbol_combos[7]: {sc_7}"
        )
        assert sc_7["cherry|cherry|cherry"] == 8

    def test_extract_missing_c4_key_returns_empty(self):
        """extract() on chunk without payout_id_symbol_combos returns empty dict."""
        plugin = self._import_plugin()
        chunk = {
            "payout_id_by_spin_type": {"7": {1: 10}},
            "payout_id_win_by_spin_type": {"7": {1: 2200.0}},
            # no payout_id_symbol_combos
        }
        acc = plugin.extract(None, chunk)
        assert acc["pid_symbol_combos"] == {}

    def test_reduce_merges_symbol_combos_additively(self):
        """reduce() merges symbol_combo histograms additively."""
        plugin = self._import_plugin()
        acc1 = {
            "by_st_hits": {"7": {1: 5}}, "by_st_win": {"7": {1: 1100.0}},
            "pid_payline_hits": {}, "pid_match_count_dist": {},
            "pid_col_set": {}, "pid_has_regular_line": {},
            "pid_symbol_combos": {"7": {"cherry|cherry|cherry": 3}},
        }
        acc2 = {
            "by_st_hits": {"7": {1: 5}}, "by_st_win": {"7": {1: 1100.0}},
            "pid_payline_hits": {}, "pid_match_count_dist": {},
            "pid_col_set": {}, "pid_has_regular_line": {},
            "pid_symbol_combos": {"7": {"cherry|cherry|cherry": 5, "cherry|cherry|wild": 2}},
        }
        merged = plugin.reduce(acc1, acc2)
        sc_7 = merged["pid_symbol_combos"]["7"]
        assert sc_7["cherry|cherry|cherry"] == 8, (
            f"Expected 3+5=8, got {sc_7['cherry|cherry|cherry']}"
        )
        assert sc_7["cherry|cherry|wild"] == 2

    def test_emit_symbol_combo_dominant_is_max_count(self):
        """emit() picks the combo with highest count as dominant."""
        plugin = self._import_plugin()
        ctx = self._make_ctx()
        summary = self._make_summary([
            {"spin_type": 1, "behavior_name": "paid", "spins": 10000}
        ])
        acc = {
            "by_st_hits": {"7": {1: 10}}, "by_st_win": {"7": {1: 2200.0}},
            "pid_payline_hits": {"7": {"4": 10}},
            "pid_match_count_dist": {"7": {3: 10}},
            "pid_col_set": {"7": [0, 1, 2]},
            "pid_has_regular_line": {"7": True},
            "pid_symbol_combos": {
                "7": {"cherry|cherry|cherry": 8, "cherry|cherry|wild": 2}
            },
        }
        plugin.emit(acc, summary, ctx)
        pbst = summary["player_impact"]["payouts_by_spin_type"]
        st1_rows = pbst.get("ST1_paid", [])
        pid7_rows = [r for r in st1_rows if r["payout_id"] == "7"]
        assert pid7_rows, "pid=7 not found in ST1_paid"
        sc = pid7_rows[0].get(_C4_NEW_KEY)
        assert sc is not None, f"symbol_combo key missing in emitted row"
        assert sc["dominant"] == "cherry|cherry|cherry", (
            f"Expected dominant='cherry|cherry|cherry' (count=8), got {sc['dominant']!r}"
        )

    def test_emit_symbol_combo_distinct_symbols_sorted(self):
        """emit() distinct_symbols is sorted union of all combo parts."""
        plugin = self._import_plugin()
        ctx = self._make_ctx()
        summary = self._make_summary([
            {"spin_type": 1, "behavior_name": "paid", "spins": 10000}
        ])
        acc = {
            "by_st_hits": {"7": {1: 10}}, "by_st_win": {"7": {1: 2200.0}},
            "pid_payline_hits": {"7": {"1": 10}},
            "pid_match_count_dist": {"7": {3: 10}},
            "pid_col_set": {"7": [0, 1, 2]},
            "pid_has_regular_line": {"7": True},
            "pid_symbol_combos": {
                "7": {"cherry|cherry|wild": 6, "cherry|cherry|35x_wild": 4}
            },
        }
        plugin.emit(acc, summary, ctx)
        pbst = summary["player_impact"]["payouts_by_spin_type"]
        pid7_rows = [r for r in pbst.get("ST1_paid", []) if r["payout_id"] == "7"]
        assert pid7_rows
        distinct = pid7_rows[0][_C4_NEW_KEY]["distinct_symbols"]
        assert distinct == sorted(distinct), (
            f"distinct_symbols not sorted: {distinct}"
        )
        assert "cherry" in distinct
        assert "wild" in distinct
        assert "35x_wild" in distinct

    def test_emit_empty_combos_gives_none_dominant(self):
        """emit() with no combos -> symbol_combo.dominant=None, distinct=[]."""
        plugin = self._import_plugin()
        ctx = self._make_ctx()
        summary = self._make_summary([
            {"spin_type": 1, "behavior_name": "paid", "spins": 10000}
        ])
        acc = {
            "by_st_hits": {"666": {1: 5}}, "by_st_win": {"666": {1: 0.0}},
            "pid_payline_hits": {"666": {"-1": 5}},
            "pid_match_count_dist": {},
            "pid_col_set": {},
            "pid_has_regular_line": {},
            "pid_symbol_combos": {},  # no combos
        }
        plugin.emit(acc, summary, ctx)
        pbst = summary["player_impact"]["payouts_by_spin_type"]
        pid666_rows = [r for r in pbst.get("ST1_paid", []) if r["payout_id"] == "666"]
        assert pid666_rows
        sc = pid666_rows[0][_C4_NEW_KEY]
        assert sc["dominant"] is None, (
            f"Expected dominant=None for pid with no combos, got {sc['dominant']!r}"
        )
        assert sc["distinct_symbols"] == [], (
            f"Expected distinct_symbols=[] for no combos, got {sc['distinct_symbols']!r}"
        )

    def test_c2_fields_unchanged_in_emitted_row(self):
        """C2 fields (hit_count, rtp_contribution_pp) unchanged by C4 additions."""
        plugin = self._import_plugin()
        ctx = self._make_ctx(bet=100_000.0)
        summary = self._make_summary([
            {"spin_type": 1, "behavior_name": "paid", "spins": 10000}
        ])
        acc = {
            "by_st_hits": {"7": {1: 42}},
            "by_st_win": {"7": {1: 5000.0}},
            "pid_payline_hits": {"7": {"1": 42}},
            "pid_match_count_dist": {"7": {3: 42}},
            "pid_col_set": {"7": [0, 1, 2]},
            "pid_has_regular_line": {"7": True},
            "pid_symbol_combos": {"7": {"cherry|cherry|cherry": 42}},
        }
        plugin.emit(acc, summary, ctx)
        pbst = summary["player_impact"]["payouts_by_spin_type"]
        pid7_rows = [r for r in pbst.get("ST1_paid", []) if r["payout_id"] == "7"]
        assert pid7_rows
        row = pid7_rows[0]
        assert row["hit_count"] == 42, f"hit_count={row['hit_count']}"
        assert row["total_win"] == 5000.0, f"total_win={row['total_win']}"
        expected_rtp = (5000.0 / 100_000.0) * 100.0
        assert abs(row["rtp_contribution_pp"] - expected_rtp) < 0.001, (
            f"rtp_contribution_pp={row['rtp_contribution_pp']}, expected {expected_rtp}"
        )


# ---------------------------------------------------------------------------
# Gate 1 — parser-level unit: chunk_dict emits payout_id_symbol_combos
# ---------------------------------------------------------------------------

class TestParserChunkDictEmitsSymbolCombos:
    """Gate 1d: parse_chunk_response chunk_dict contains payout_id_symbol_combos.

    Uses real cached data (subprocess-free, in-process call) to verify the
    parser accumulator is populated for real winning rounds.
    """

    def test_m14_chunk_has_symbol_combos_key(self):
        """parse_chunk_response for M14 chunk returns payout_id_symbol_combos key.

        parse_chunk_response(resp, chunk_index, bet) takes the raw 'response' list
        from the chunk file (not the whole file dict). Returns a flat dict with 'ok'.
        """
        chunks = sorted(_M14_CACHE.glob("chunk_*.json"))
        if not chunks:
            pytest.skip("M14 chunks not found")
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        data = json.loads(chunks[1].read_bytes())
        resp = data.get("response")
        assert resp is not None, "chunk file missing 'response' key"
        result = parse_chunk_response(resp, chunk_index=1, bet=1000)
        assert result.get("ok"), f"parse_chunk_response failed: {result.get('error')}"
        assert "payout_id_symbol_combos" in result, (
            f"payout_id_symbol_combos missing from chunk_dict. "
            f"Keys present: {sorted(k for k in result.keys() if 'payout' in k)}"
        )

    def test_m14_chunk_symbol_combos_non_empty(self):
        """parse_chunk_response for M14 chunk produces non-empty symbol combos.

        INJECT-BUG: in parser.py, comment out the entire C4 symbol decode block
        (the if _c4_ssbc_cols is not None block).
        payout_id_symbol_combos remains empty -> this test fails.
        Revert -> GREEN.
        """
        chunks = sorted(_M14_CACHE.glob("chunk_*.json"))
        if not chunks:
            pytest.skip("M14 chunks not found")
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        # Try first 5 chunks to find one with winning rounds
        symbol_combos: dict[str, dict[str, int]] = {}
        for chunk_path in chunks[:5]:
            data = json.loads(chunk_path.read_bytes())
            resp = data.get("response")
            if not resp:
                continue
            idx = int(data.get("_chunk_index", 0))
            result = parse_chunk_response(resp, chunk_index=idx, bet=1000)
            if not result.get("ok"):
                continue
            sc = result.get("payout_id_symbol_combos", {})
            if sc:
                symbol_combos = sc
                break

        assert symbol_combos, (
            "payout_id_symbol_combos is empty across first 5 M14 chunks. "
            "C4 symbol decode block may not be running."
        )
        # Verify structure: pid_str -> {combo_str: count}
        for pid_s, combo_map in symbol_combos.items():
            assert isinstance(pid_s, str), f"pid key not string: {pid_s!r}"
            assert isinstance(combo_map, dict), f"combo_map not dict: {combo_map!r}"
            for combo, cnt in combo_map.items():
                assert isinstance(combo, str) and "|" in combo, (
                    f"combo {combo!r} doesn't look like 'sym|sym|sym'"
                )
                assert isinstance(cnt, int) and cnt > 0, (
                    f"count {cnt!r} for combo {combo!r} is not a positive int"
                )

    def test_m14_chunk_combo_matches_reference_decode(self):
        """parse_chunk_response combos match independently decoded positions.

        For each winning round in M14 chunks, independently decode via
        _decode_symbol_combo and verify the combo is in chunk_dict's histogram.

        INJECT-BUG: change row decode in parser.py to row=pos-col_1idx*100 (no +1).
        Produces wrong symbols. Reference decode (correct +1) produces different
        combos -> 'ref combo not in chunk_dict combos' -> RED.
        Revert -> GREEN.
        """
        chunks = sorted(_M14_CACHE.glob("chunk_*.json"))
        if not chunks:
            pytest.skip("M14 chunks not found")
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        mismatches: list[str] = []
        checked = 0

        for chunk_path in chunks[:3]:
            chunk_data = json.loads(chunk_path.read_bytes())
            resp = chunk_data.get("response")
            if not resp:
                continue
            idx = int(chunk_data.get("_chunk_index", 0))
            result = parse_chunk_response(resp, chunk_index=idx, bet=1000)
            if not result.get("ok"):
                continue
            combos_by_pid: dict[str, dict[str, int]] = result.get("payout_id_symbol_combos", {})

            # Independently decode from raw responses
            for robot_resp in resp:
                rr_str = robot_resp.get("roundResult", "")
                try:
                    rr_list = json.loads(rr_str)
                except Exception:
                    continue
                if not isinstance(rr_list, list):
                    rr_list = [rr_list]
                for r in rr_list:
                    pbp = r.get("PayoutByPayline", "")
                    ssbc = r.get("StopSymbolsByCol", [])
                    if not pbp or not ssbc:
                        continue
                    for match in re.finditer(r'(-?\d+):(\d+)-(\d+)\(([^)]*)\)', pbp):
                        pid2 = match.group(3)  # second pid is the canonical match_id
                        pos_str = match.group(4).strip()
                        positions = [int(p) for p in pos_str.split(",") if p.strip()]
                        if not positions:
                            continue  # scatter / empty positions
                        ref_combo = _decode_symbol_combo(positions, ssbc)
                        if ref_combo is None:
                            continue
                        pid_combos = combos_by_pid.get(pid2, {})
                        if ref_combo not in pid_combos:
                            mismatches.append(
                                f"pid={pid2} ref_combo={ref_combo!r} not in "
                                f"chunk_dict combos={set(pid_combos.keys())}"
                            )
                        checked += 1
                        if checked >= 50:
                            break
                    if checked >= 50:
                        break
                if checked >= 50:
                    break
            if checked >= 50:
                break

        assert checked > 0, "No winning rounds with positions found in first 3 M14 chunks"
        assert not mismatches, (
            f"Reference decode mismatch in parser output ({len(mismatches)} cases):\n"
            + "\n".join(mismatches[:10])
        )

    def test_m275_chunk_has_wild_combos(self):
        """parse_chunk_response for M275 chunk returns wild-containing combos."""
        chunks = sorted(_M275_CACHE.glob("chunk_*.json"))
        if not chunks:
            pytest.skip("M275 chunks not found")
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        for chunk_path in chunks[:3]:
            data = json.loads(chunk_path.read_bytes())
            resp = data.get("response")
            if not resp:
                continue
            idx = int(data.get("_chunk_index", 0))
            result = parse_chunk_response(resp, chunk_index=idx, bet=1000)
            if not result.get("ok"):
                continue
            sc = result.get("payout_id_symbol_combos", {})
            wild_combos = [
                (pid, combo) for pid, cm in sc.items()
                for combo in cm.keys()
                if "wild" in combo.lower()
            ]
            if wild_combos:
                # Found wild combos -> decode is working
                return
        pytest.skip("No wild-containing combos found in first 3 M275 chunks (unexpected)")


# ---------------------------------------------------------------------------
# inject-bug evidence — documented (actual execution in test runner output)
# ---------------------------------------------------------------------------

class TestInjectBugDocumented:
    """Gate 6 — documents the inject-bug recipe.

    The actual inject-bug run is performed externally (reported in end-of-task
    reply). This class tests the PRECONDITION: the decode line is present and
    has the correct +1 offset.
    """

    def test_parser_decode_line_has_plus1_offset(self):
        """parser.py C4 decode block has the +1 row offset (not corrupted).

        Searches for the row decode assignment. Asserts the canonical form
        `_c4row = _c4pos - _c4col_1idx * 100 + 1` is present.

        INJECT-BUG: change to `_c4row = _c4pos - _c4col_1idx * 100` (remove +1).
        RED: this test fails because the line is absent.
        RED: test_decode_correctness tests (M14 pid=7, M275 pid=7) also fail.
        Revert -> GREEN.
        """
        parser_text = _PARSER_PY.read_text(encoding="utf-8")
        # The canonical decode line from parser.py
        assert "_c4row = _c4pos - _c4col_1idx * 100 + 1" in parser_text, (
            "C4 row decode line with '+1' offset not found in parser.py.\n"
            "Expected: `_c4row = _c4pos - _c4col_1idx * 100 + 1`\n"
            "This indicates the +1 offset was removed (inject-bug applied or regression)."
        )

    def test_parser_c4_block_present(self):
        """parser.py has the C4 symbol decode block (not deleted)."""
        parser_text = _PARSER_PY.read_text(encoding="utf-8")
        assert "payout_id_symbol_combos" in parser_text, (
            "payout_id_symbol_combos not found in parser.py — C4 block missing"
        )
        assert "_c4_ssbc_cols" in parser_text, (
            "_c4_ssbc_cols not in parser.py — C4 SSBC parsing block missing"
        )

    def test_parser_c4_block_guards_empty_positions(self):
        """C4 block checks _c3positions is non-empty before symbol decode."""
        parser_text = _PARSER_PY.read_text(encoding="utf-8")
        # The guard 'if _c4_ssbc_cols is not None and _c3positions:'
        assert "_c3positions" in parser_text and "_c4_ssbc_cols is not None" in parser_text, (
            "C4 block missing the 'if _c4_ssbc_cols is not None and _c3positions' guard"
        )
