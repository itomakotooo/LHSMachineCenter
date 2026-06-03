"""Phase 5 — REAL full deep-diff byte-identity regression for the reel_marginal_by_spin_type carve.

This is the gate-1 contract from
``session_artifacts/_impl/phase_extract_5_reel_marginal/brief.md`` §3:
the reel_marginal_by_spin_type carve (moving the inline dict-build — the
``player_impact.reel_marginal_by_spin_type`` literal that was at pre-carve
PIA:~3432, the ``for st_int, label in sorted(_st_label.items())`` loop with its
nested ``for ci, sym_map in sorted(st_col_map.items())`` column loop, the
``col_total == 0`` skip, the ``int(cnt)`` count, and the
``prob_pct = (cnt / col_total) * 100.0`` leaf — out of
``player_impact_analyzer.py`` into the ``ReelMarginalBySpinType`` plugin's
``emit()``, which RE-DERIVES ``_st_label`` from the already-emitted
``spin_type_breakdown``) MUST produce byte-identical report *content*.  The
pre-existing ``test_c5_collect_mechanic_plugin.py``-style structural unit tests
are only *structural* — they would NOT catch a reordered dict key, a rewritten
``prob_pct`` divisor, an ``int(cnt)`` dropped, a flipped sort direction, or a
dropped/added label inside the carved compute.  This test closes that gap with a
TRUE full-JSON leaf-by-leaf deep diff against a committed content-only golden.

This is the FIFTH carve (2a = collect_mechanic, 2b = bonus_chain_dynamics, 3 =
upstream_feature_breakdown, 4 = multiplier_profile, all shipped); this file MIRRORS
``test_4_byte_identical_multiplier_profile_carve.py`` exactly (same helpers, same
strip-list, same guard-the-guard suite, same tight vary-key allowlist test).

Why a golden + leaf-allowlist (not a full-file hash)
----------------------------------------------------
The summary embeds 8 leaf KEY NAMES that legitimately vary and must be excluded:

  - per-RUN metadata (differ every run even at frozen code):
      run_id, report_id, started_at, finished_at, duration_seconds, evaluated_at
  - version STAMPS (differ when *any* analyzer code changes — including this
    very carve, since base_hash shrank ce298f055495 -> ccc1ecce185d):
      analyzer_version, effective_analyzer_version

These 8 keys are stripped wherever they occur (top-level AND nested — e.g.
``sampling.started_at``, ``guideline_comparison.evaluated_at``) before the diff.
EVERYTHING ELSE — the entire ``player_impact.reel_marginal_by_spin_type`` dict,
``rtp``, all of ``player_impact``, ``config_md5`` / ``code_md5`` — must match the
golden exactly.

The golden was generated (impl-tester, 2026-05-30) by running the post-carve
analyzer and stripping the 8 varying keys; the result reproduced byte-identical
content (0 leaf drift) vs the committed pre-carve baseline at
``session_artifacts/_impl/phase_extract_5_reel_marginal/baseline/{M275,M14}/``
(deep-diff figure: M275 = 4667 raw leaves / 0 content drift; M14 = 6864 raw
leaves / 0 content drift).  The goldens contain NONE of the 8 varying keys.
Regenerate with::

    python - <<'PY'
    # see _strip_varying() below — run analyzer, strip, json.dump(sort_keys=True)
    PY

Inject-bug recipe (Path A — content drift; per feedback_enumerate_safety_paths.md)
----------------------------------------------------------------------------------
Temporarily mutate ONE moved expression in
``fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py`` emit(), e.g. the
``prob_pct`` form::

    "prob_pct": (cnt / col_total) * 100.0,
to::
    "prob_pct": (cnt / col_total) * 100.0 + 0.001,  # BUG

RED: ``test_m275_content_byte_identical`` (and M14) fail listing the drifted leaf
     paths under ``/player_impact/reel_marginal_by_spin_type/<label>/<col>[<i>]/
     prob_pct`` (golden != produced).
Revert -> GREEN. (Verified 2026-05-30; evidence in inject_bug_evidence.md §A.)

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md
    inject-bug -> red -> revert -> green is mandatory for the new carve path.
- memory/feedback_perf_claim_needs_e2e_event_stream.md
    a REAL subprocess against real cached M275/M14 — unit tests alone cannot
    catch PIA<->plugin field drift (the synthetic-stash unit uses a hand-built
    ``symbol_counts_by_col_by_spin_type_total`` accumulator → the REAL accumulator
    populated at PIA:~1655/~2425, the live ``spin_type_breakdown`` rows F1 wrote,
    the re-derived ``_st_label`` map, and their exact iteration order / float
    forms are ONLY exercised by REAL varied M275/M14 data).  Mock nothing; run the
    actual CLI.
- memory/feedback_invariant_with_fallback_hides_drift.md
    the full deep-diff catches silent attribution drift (a dropped/extra label,
    a reordered symbol row, a None-vs-0.0 flip) that a structural "is the key
    there?" test misses.
- memory/feedback_aggregator_parity_invariant.md
    reel_marginal_by_spin_type is RTP_CONTRIBUTION=False -> ``rtp`` must be
    unchanged; the deep diff covers ``rtp`` so any drift fails loud.
- memory/feedback_no_parallel_panel_impl.md
    the plugin re-derives ``_st_label`` with the SAME comprehension
    PayoutsBySpinType.emit() uses (no parallel derivation); identical iteration
    order is what makes the build byte-identical — the deep diff is the witness.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_M275_CACHE = _REPO_ROOT / "rawdata" / "M275" / "mode_1"
_M14_CACHE = _REPO_ROOT / "rawdata" / "M14" / "mode_1"

# The 8 leaf KEY NAMES that legitimately vary (per-run metadata + version stamps).
# Stripped wherever they appear (top-level or nested) before the deep-diff.
# MUST stay in sync with the golden-generation strip (the goldens were produced
# with this exact set; see module docstring).
_VARYING_LEAF_KEYS: frozenset[str] = frozenset(
    {
        # version stamps (change when any analyzer code changes — incl. this carve)
        "analyzer_version",
        "effective_analyzer_version",
        # per-run metadata
        "run_id",
        "report_id",
        "started_at",
        "finished_at",
        "duration_seconds",
        "evaluated_at",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_varying(obj: Any) -> Any:
    """Recursively drop every leaf whose KEY NAME is in _VARYING_LEAF_KEYS.

    Drops at any depth (top-level run_id AND nested sampling.started_at), so the
    diff compares only the stable report *content*.
    """
    if isinstance(obj, dict):
        return {
            k: _strip_varying(v)
            for k, v in obj.items()
            if k not in _VARYING_LEAF_KEYS
        }
    if isinstance(obj, list):
        return [_strip_varying(v) for v in obj]
    return obj


def _flatten_leaves(obj: Any, path: str = "") -> dict[str, Any]:
    """Flatten a nested dict/list into {leaf_path: value}.

    Lists are indexed positionally so a reordered/added/removed list element
    surfaces as a distinct path (e.g. /player_impact/reel_marginal_by_spin_type/
    ST140_paid/0[3]/prob_pct).
    """
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten_leaves(v, f"{path}/{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten_leaves(v, f"{path}[{i}]"))
    else:
        out[path] = obj
    return out


def _diff_leaves(golden: Any, produced: Any) -> list[str]:
    """Return human-readable descriptions of every differing leaf path.

    Catches: value drift, type drift, added leaves, removed leaves, and any
    list reordering (positional path mismatch).
    """
    g = _flatten_leaves(golden)
    p = _flatten_leaves(produced)
    diffs: list[str] = []
    for path in sorted(set(g) | set(p)):
        if path not in g:
            diffs.append(f"ADDED   {path} = {p[path]!r} (absent in golden)")
        elif path not in p:
            diffs.append(f"REMOVED {path} (was {g[path]!r}; absent in produced)")
        elif g[path] != p[path]:
            diffs.append(f"DRIFT   {path}: golden={g[path]!r} != produced={p[path]!r}")
    return diffs


def _run_analyzer(machine: str, cache: Path) -> dict:
    """Run the analyzer for ``machine`` mode 1 from cache; return parsed summary.

    REAL subprocess (cwd=repo root) against REAL cached chunks — per
    feedback_perf_claim_needs_e2e_event_stream.md. No mocking.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable, str(_PIA),
            "--machine", machine,
            "--rtp-mode", "1",
            "--from-cache", str(cache),
            "--output-dir", tmpdir,
            "--bet", "1000",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=300
        )
        assert result.returncode == 0, (
            f"{machine} analyzer exited {result.returncode}.\n"
            f"STDOUT: {result.stdout[-2000:]}\n"
            f"STDERR: {result.stderr[-2000:]}"
        )
        return json.loads((Path(tmpdir) / "player_impact_summary.json").read_bytes())


def _load_golden(machine: str) -> dict:
    path = _FIXTURES / f"{machine}_mode1_reel_marginal_golden.json"
    if not path.exists():  # pragma: no cover - fixture should be committed
        pytest.skip(f"golden fixture missing: {path}")
    return json.loads(path.read_bytes())


# ---------------------------------------------------------------------------
# Subprocess fixtures (module-scoped — one run per machine)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m275_summary() -> dict:
    if not _M275_CACHE.exists() or not list(_M275_CACHE.glob("chunk_*.json")):
        pytest.skip(f"M275 mode 1 cached chunks not found at {_M275_CACHE}")
    return _run_analyzer("M275", _M275_CACHE)


@pytest.fixture(scope="module")
def m14_summary() -> dict:
    if not _M14_CACHE.exists() or not list(_M14_CACHE.glob("chunk_*.json")):
        pytest.skip(f"M14 mode 1 cached chunks not found at {_M14_CACHE}")
    return _run_analyzer("M14", _M14_CACHE)


# ---------------------------------------------------------------------------
# Self-tests for the diff machinery (so a broken helper can't hide drift)
# ---------------------------------------------------------------------------

class TestDiffMachinery:
    """The deep-diff helpers must actually detect each drift class.

    If these are wrong, the byte-identity tests below would be stale-green
    (vacuously passing). These guard the guard.
    """

    def test_strip_removes_nested_varying_keys(self):
        obj = {
            "run_id": "x",
            "sampling": {"started_at": "t", "chunk_spin_times": 5000},
            "guideline_comparison": {"evaluated_at": "z", "verdict": "ok"},
            "rtp": 0.95,
        }
        stripped = _strip_varying(obj)
        assert "run_id" not in stripped
        assert "started_at" not in stripped["sampling"]
        assert stripped["sampling"]["chunk_spin_times"] == 5000
        assert "evaluated_at" not in stripped["guideline_comparison"]
        assert stripped["guideline_comparison"]["verdict"] == "ok"
        assert stripped["rtp"] == 0.95

    def test_diff_detects_value_drift(self):
        diffs = _diff_leaves({"a": {"b": 1.0}}, {"a": {"b": 1.1}})
        assert any("/a/b" in d and "DRIFT" in d for d in diffs), diffs

    def test_diff_detects_none_vs_zero(self):
        # The exact class a prob_pct / col-skip regression could introduce.
        diffs = _diff_leaves({"a": None}, {"a": 0.0})
        assert any("/a" in d and "DRIFT" in d for d in diffs), diffs

    def test_diff_detects_added_and_removed(self):
        diffs = _diff_leaves({"a": 1}, {"a": 1, "b": 2})
        assert any("ADDED" in d and "/b" in d for d in diffs), diffs
        diffs2 = _diff_leaves({"a": 1, "b": 2}, {"a": 1})
        assert any("REMOVED" in d and "/b" in d for d in diffs2), diffs2

    def test_diff_detects_list_reorder(self):
        # A flipped symbol-row sort direction surfaces as a positional reorder.
        diffs = _diff_leaves({"l": [{"k": 1}, {"k": 2}]}, {"l": [{"k": 2}, {"k": 1}]})
        # positional indexing makes a reorder a value drift at [0]/k and [1]/k
        assert any("[0]/k" in d for d in diffs), diffs

    def test_identical_inputs_no_diff(self):
        obj = {"a": {"b": [1, 2, 3]}, "c": "x"}
        assert _diff_leaves(obj, json.loads(json.dumps(obj))) == []


# ---------------------------------------------------------------------------
# T1: M275 full content byte-identity (the carve contract)
#     M275 exercises the carved compute with rich, varied data: 2 SpinType
#     labels (ST126_free, ST140_paid), each with 3 reel columns of symbol rows
#     sorted count-descending with distinct prob_pct floats. This proves the
#     moved dict-build is byte-identical on real data (the synthetic-stash unit
#     cannot — it hand-builds the accumulator + breakdown rows).
# ---------------------------------------------------------------------------

class TestM275ByteIdentical:
    """M275 mode 1 report content must deep-equal the frozen golden."""

    def test_m275_content_byte_identical(self, m275_summary):
        """Every M275 leaf (minus the 8 varying keys) must match the golden.

        INJECT-BUG (Path A): rewrite ONE moved expression in
        reel_marginal_by_spin_type.py emit() (e.g. change the prob_pct form,
        flip the symbol-row sort direction, or drop the int(cnt)). RED: this test
        lists the drifted leaf paths under
        /player_impact/reel_marginal_by_spin_type/. Revert -> GREEN.
        See module docstring.
        """
        golden = _load_golden("M275")
        produced = _strip_varying(m275_summary)
        diffs = _diff_leaves(golden, produced)
        assert not diffs, (
            f"M275 content drifted from the pre-carve golden ({len(diffs)} leaf "
            f"path(s)). The reel_marginal_by_spin_type carve must be byte-identical "
            f"content.\n"
            + "\n".join(diffs[:50])
            + ("" if len(diffs) <= 50 else f"\n... and {len(diffs) - 50} more")
        )

    def test_m275_leaf_count_matches_baseline(self, m275_summary):
        """Raw M275 leaf count must be 4667 (pre-carve baseline figure).

        A structural sanity check: if the leaf count moved, the carve added or
        dropped fields somewhere — the content diff above would also fail, but
        this pins the headline number for fast triage.
        """
        n = len(_flatten_leaves(m275_summary))
        assert n == 4887, (
            f"M275 raw leaf count must be 4887 (re-baselined post Phase-P3 symbol_combo/covered_columns enrichment), got {n}. "
            f"The carve changed the report shape."
        )

    def test_m275_reel_marginal_in_golden_and_produced(self, m275_summary):
        """reel_marginal_by_spin_type must be present + non-trivially equal in both.

        Guards against a vacuous pass where both golden and produced somehow
        lacked the carved key (then the diff would be empty for the wrong reason).
        """
        golden = _load_golden("M275")
        g_rm = golden.get("player_impact", {}).get("reel_marginal_by_spin_type")
        p_rm = m275_summary.get("player_impact", {}).get("reel_marginal_by_spin_type")
        assert g_rm is not None, "golden missing player_impact.reel_marginal_by_spin_type"
        assert p_rm is not None, "produced missing player_impact.reel_marginal_by_spin_type"
        assert g_rm == p_rm, (
            "reel_marginal_by_spin_type dict drifted between golden and produced — "
            "see test_m275_content_byte_identical for the exact leaf paths."
        )
        # The verbatim-build LABEL ORDER is asserted on the PRODUCED runtime dict
        # (insertion-ordered by sorted(_st_label.items())), NOT the golden — the
        # committed golden is serialized with sort_keys=True (a stable on-disk form
        # for the order-insensitive leaf-path deep-diff), so its key order is
        # alphabetical by construction. The byte-identity contract is about the
        # runtime build order: labels are sorted by spin_type INT (ST126 before
        # ST140 -> 126 < 140), and within a label the columns are sorted by int.
        assert list(p_rm.keys()) == ["ST126_free", "ST140_paid"], (
            f"produced reel_marginal label order must match the verbatim build "
            f"(sorted by spin_type int). Got {list(p_rm.keys())}"
        )

    def test_m275_exercises_rich_carved_paths(self, m275_summary):
        """M275 must drive the carved compute's non-trivial values (not empty defaults).

        The genuine M275 richness that the deep-diff locks is structural, asserted
        here so the byte-identity test is known to exercise live values rather than
        empty defaults:

          - >= 2 SpinType labels, each with non-empty col_rows (NOT the empty
            ``reel_marginal_by_spin_type[label] = {}`` branch — that golden-missed
            branch is covered in test_5_reel_marginal_coverage_gaps.py),
          - each surviving column has a non-empty symbol-row list,
          - rows are sorted count-descending (the live sort branch),
          - prob_pct values are floats in (0, 100].
        """
        rm = m275_summary["player_impact"]["reel_marginal_by_spin_type"]
        assert len(rm) >= 2, f"M275 must have >= 2 labels, got {list(rm.keys())}"
        any_rows_seen = False
        for label, col_rows in rm.items():
            assert isinstance(col_rows, dict) and len(col_rows) > 0, (
                f"M275 label {label!r} must have non-empty col_rows "
                f"(live branch, not the empty-dict branch); got {col_rows!r}"
            )
            for col_key, rows in col_rows.items():
                assert isinstance(rows, list) and len(rows) > 0, (
                    f"M275 {label!r} col {col_key!r} must have a non-empty row list"
                )
                # rows sorted count-descending (the live sort branch)
                counts = [r["count"] for r in rows]
                assert counts == sorted(counts, reverse=True), (
                    f"M275 {label!r} col {col_key!r} rows must be count-descending; "
                    f"got {counts}"
                )
                for r in rows:
                    assert isinstance(r["count"], int), f"count must be int: {r!r}"
                    assert isinstance(r["prob_pct"], float), f"prob_pct must be float: {r!r}"
                    assert 0.0 < r["prob_pct"] <= 100.0, f"prob_pct out of range: {r!r}"
                    any_rows_seen = True
        assert any_rows_seen, "M275 must have at least one symbol row"


# ---------------------------------------------------------------------------
# T2: M14 full content byte-identity (the second real machine)
# ---------------------------------------------------------------------------

class TestM14ByteIdentical:
    """M14 mode 1 report content must deep-equal the frozen golden.

    M14 is the isolation-anchor machine (M14==M37==M272 share an effective
    version). It exercises the carved build on a different real distribution
    (single SpinType ST1_paid) — a second independent witness that the moved
    dict-build is byte-identical.
    """

    def test_m14_content_byte_identical(self, m14_summary):
        """Every M14 leaf (minus the 8 varying keys) must match the golden.

        INJECT-BUG (Path A): same as M275 — a content drift in the carve surfaces
        here too. RED -> revert -> GREEN.
        """
        golden = _load_golden("M14")
        produced = _strip_varying(m14_summary)
        diffs = _diff_leaves(golden, produced)
        assert not diffs, (
            f"M14 content drifted from the pre-carve golden ({len(diffs)} leaf "
            f"path(s)). The reel_marginal_by_spin_type carve must be byte-identical "
            f"content.\n"
            + "\n".join(diffs[:50])
            + ("" if len(diffs) <= 50 else f"\n... and {len(diffs) - 50} more")
        )

    def test_m14_leaf_count_matches_baseline(self, m14_summary):
        """Raw M14 leaf count must be 6957 (re-baselined post Phase-P3 symbol_combo enrichment)."""
        n = len(_flatten_leaves(m14_summary))
        assert n == 6957, (
            f"M14 raw leaf count must be 6957 (re-baselined post Phase-P3 symbol_combo enrichment), got {n}."
        )

    def test_m14_reel_marginal_equals_golden(self, m14_summary):
        """M14 reel_marginal_by_spin_type must be present, equal to golden, single label.

        Also asserts the verbatim build form survives the carve: M14 has exactly
        ONE SpinType (ST1_paid) with non-empty columns.
        """
        golden = _load_golden("M14")
        g_rm = golden.get("player_impact", {}).get("reel_marginal_by_spin_type")
        p_rm = m14_summary.get("player_impact", {}).get("reel_marginal_by_spin_type")
        assert g_rm is not None and p_rm is not None
        assert g_rm == p_rm
        # M14 has a single SpinType label (the isolation-anchor distribution).
        assert list(p_rm.keys()) == ["ST1_paid"], (
            f"produced M14 reel_marginal label set must be ['ST1_paid']. "
            f"Got {list(p_rm.keys())}"
        )
        # Non-empty columns (the live branch, not the empty-dict branch).
        assert len(p_rm["ST1_paid"]) > 0
        for col_key, rows in p_rm["ST1_paid"].items():
            assert len(rows) > 0, f"M14 ST1_paid col {col_key!r} must have rows"


# ---------------------------------------------------------------------------
# T3: only the 8 allowlisted keys are permitted to vary (proves the allowlist
#     is not over-broad — a real drift in a NON-varying field still fails)
# ---------------------------------------------------------------------------

class TestVaryingKeyAllowlistIsTight:
    """The 8-key allowlist must be exactly the per-run/version-stamp set.

    If a future change accidentally makes a *content* field run-dependent, this
    test ensures it would NOT be silently swallowed by an over-broad allowlist:
    we re-run the analyzer and confirm the ONLY raw-leaf differences between two
    runs are the 6 per-run keys (the 2 version stamps are stable at fixed code).
    """

    def test_only_per_run_keys_vary_between_two_runs(self, m275_summary):
        """A second M275 run must differ from the first ONLY in per-run leaf keys.

        This is the paranoid guard: it proves the strip-list is not hiding a
        genuinely drifting content field (e.g. a reel_marginal value that somehow
        became nondeterministic). Version stamps are constant at fixed code, so
        only the 6 metadata keys appear here.
        """
        second = _run_analyzer("M275", _M275_CACHE)
        a = _flatten_leaves(m275_summary)
        b = _flatten_leaves(second)
        differing = sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p))
        # Every differing path's final key segment must be in the allowlist.
        offenders = [
            p for p in differing
            if p.rsplit("/", 1)[-1].split("[")[0] not in _VARYING_LEAF_KEYS
        ]
        assert not offenders, (
            f"Run-to-run drift in NON-allowlisted leaf path(s) — the strip-list "
            f"may be hiding genuine content nondeterminism: {offenders}"
        )
