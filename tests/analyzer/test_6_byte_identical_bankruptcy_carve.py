"""Phase 6 — REAL full deep-diff byte-identity regression for the bankruptcy_simulation carve.

This is the gate-1 contract from
``session_artifacts/_impl/phase_extract_6_bankruptcy/brief.md`` §3/§4: the Phase 6
carve (the LAST carve of the analyzer unbundle) moved the tier ROW-BUILD loop —
the ``for m in bankruptcy_mults_tuple`` loop with its ``tier is None ->
_empty_bankruptcy_tier()`` fallback, the ``total_sessions`` /
``rate = bankrupt / total_sessions`` form, the
``sorted(int(v) for v in spins_done)`` view, the SHARED helper calls
(``compute_bankruptcy_percentiles`` / ``median_spins_from_list`` /
``fastest_bankruptcy_spins_from_list``), the ``{str(k): v for k, v in
percentiles.items()}`` serialization, and the final
``bankruptcy_rows.sort(key=...)`` — VERBATIM out of
``player_impact_analyzer.py`` main() (pre-summary, ~PIA:3609) into the module-level
``build_bankruptcy_rows(...)`` function in the ``bankruptcy_simulation`` plugin.
The ONLY textual change was ``args.bet`` -> the ``bet`` parameter (coordinator-verified).

The split-ownership shape (brief §0)
------------------------------------
``bankruptcy_rows`` is consumed by PIA in THREE places. ALL THREE must stay
byte-identical and are covered leaf-by-leaf by this test:

  1. ``guideline_assessment.bankruptcy_checks``  (x100_br / x200_br / x500_br,
     derived pre-summary from the rows returned by build_bankruptcy_rows).
  2. ``player_impact.bankruptcy_simulation``     (source / session_spins /
     percentile_keys / tiers — emit() reads the stashed rows).
  3. ``player_impact.bankruptcy_probe``          (the back-compat alias = tiers).

The pre-existing ``test_analyzer_bankruptcy.py`` units are only *helper-level*
(they exercise ``compute_bankruptcy_percentiles`` / ``_BankruptcyStreamAccumulator``
etc. via the ``pia`` re-exports) — they would NOT catch a reordered tier dict
key, a flipped tier sort direction, a dropped ``int()`` cast, a rewritten
``rate`` divisor, or a mis-routed x100/x200/x500 derivation in the carved
``build_bankruptcy_rows``. This test closes that gap with a TRUE full-JSON
leaf-by-leaf deep diff against a committed content-only golden.

This is the SIXTH (final) carve; this file MIRRORS
``test_5_byte_identical_reel_marginal_carve.py`` exactly (same helpers, same
strip-list, same guard-the-guard suite, same tight vary-key allowlist test).

Why a golden + leaf-allowlist (not a full-file hash)
----------------------------------------------------
The summary embeds 8 leaf KEY NAMES that legitimately vary and must be excluded:

  - per-RUN metadata (differ every run even at frozen code):
      run_id, report_id, started_at, finished_at, duration_seconds, evaluated_at
  - version STAMPS (differ when *any* analyzer code changes — but NOT this carve,
    because the row-build bytes now live in the R-4-excluded plugin file, so base
    is unchanged at d8b8c138874a; the stamps are stripped regardless):
      analyzer_version, effective_analyzer_version

These 8 keys are stripped wherever they occur (top-level AND nested — e.g.
``sampling.started_at``, ``guideline_comparison.evaluated_at``) before the diff.
EVERYTHING ELSE — the entire ``player_impact.bankruptcy_simulation`` dict,
``player_impact.bankruptcy_probe`` list, ``guideline_assessment.bankruptcy_checks``,
``rtp``, ``config_md5`` / ``code_md5`` — must match the golden exactly.

The golden was generated (impl-tester, 2026-05-30) by running the post-carve
analyzer and stripping the 8 varying keys; the result reproduced byte-identical
content (0 leaf drift) vs the committed pre-carve baseline at
``session_artifacts/_impl/phase_extract_6_bankruptcy/baseline/{M275,M14}/``
(deep-diff figure: M275 = 4667 raw leaves / 0 content drift; M14 = 6864 raw
leaves / 0 content drift — identical leaf counts to the Phase 5 baseline, the
carve is shape-preserving).  The goldens contain NONE of the 8 varying keys.

Inject-bug recipe (Path A — content drift; per feedback_enumerate_safety_paths.md)
----------------------------------------------------------------------------------
Temporarily mutate ONE moved expression in
``fresh_slotlab/analyzer/features/bankruptcy_simulation.py`` build_bankruptcy_rows(),
e.g. the per-tier rate form::

    rate = (tier["bankrupt"] / total_sessions) if total_sessions > 0 else 0.0
to::
    rate = (tier["bankrupt"] / total_sessions) + 0.001 if total_sessions > 0 else 0.0  # BUG

RED: ``test_m275_content_byte_identical`` (and M14) fail listing the drifted leaf
     paths under ``/player_impact/bankruptcy_simulation/tiers[<i>]/bankruptcy_rate``
     AND ``/player_impact/bankruptcy_probe/[<i>]/bankruptcy_rate`` AND
     ``/guideline_assessment/bankruptcy_checks/x100_bankruptcy_rate`` (the
     pre-summary consumer is fed by the SAME rows). Revert -> GREEN.
     (Verified 2026-05-30; evidence in inject_bug_evidence.md §A.)

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md
    inject-bug -> red -> revert -> green is mandatory for the new carve path.
- memory/feedback_perf_claim_needs_e2e_event_stream.md
    a REAL subprocess against real cached M275/M14 — unit tests alone cannot
    catch PIA<->plugin field drift.  The real ``_BankruptcyStreamAccumulator``
    finalize output, the live ``_bankruptcy_mults_tuple``, the actual ``args.bet``
    threading, and the THREE-place consumer wiring (pre-summary x100_br, the
    stash->emit panel, the alias) are ONLY exercised by REAL varied M275/M14 data.
    Mock nothing; run the actual CLI.
- memory/feedback_invariant_with_fallback_hides_drift.md
    the full deep-diff catches silent attribution drift (a dropped/extra tier, a
    reordered tier, a None-vs-int fastest flip, a mis-keyed percentile) that a
    helper-level "is P50 right?" unit misses.
- memory/feedback_aggregator_parity_invariant.md
    bankruptcy_simulation is RTP_CONTRIBUTION=False -> ``rtp`` must be unchanged;
    the deep diff covers ``rtp`` so any drift fails loud.
- memory/feedback_no_parallel_panel_impl.md
    build_bankruptcy_rows is a VERBATIM move (only args.bet->bet param); identical
    iteration order / float forms are what makes the build byte-identical — the
    deep diff is the witness.
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
# with this exact set; see module docstring).  Identical to the Phase 2a-5 sets.
_VARYING_LEAF_KEYS: frozenset[str] = frozenset(
    {
        # version stamps (NOT changed by this carve — base stays d8b8c138874a —
        # but stripped regardless since they vary run-to-run for unrelated reasons)
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
    surfaces as a distinct path (e.g. /player_impact/bankruptcy_simulation/
    tiers[2]/bankruptcy_rate) — this is exactly how a flipped tier sort or a
    dropped tier shows up.
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
    feedback_perf_claim_needs_e2e_event_stream.md. No mocking. Uses the
    production-default bankruptcy params (session_spins=10000, bankroll
    multipliers="10,100,200,500" — base_pipeline.py:186-198), so the 4 tiers
    [10,100,200,500] match the committed golden.
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
    path = _FIXTURES / f"{machine}_mode1_bankruptcy_golden.json"
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

    def test_diff_detects_none_vs_int(self):
        # The exact class a fastest_bankruptcy_spins regression could introduce
        # (None when a tier saw zero bankruptcies vs an int).
        diffs = _diff_leaves({"a": None}, {"a": 0})
        assert any("/a" in d and "DRIFT" in d for d in diffs), diffs

    def test_diff_detects_added_and_removed(self):
        diffs = _diff_leaves({"a": 1}, {"a": 1, "b": 2})
        assert any("ADDED" in d and "/b" in d for d in diffs), diffs
        diffs2 = _diff_leaves({"a": 1, "b": 2}, {"a": 1})
        assert any("REMOVED" in d and "/b" in d for d in diffs2), diffs2

    def test_diff_detects_tier_reorder(self):
        # A flipped tier sort direction surfaces as a positional reorder.
        diffs = _diff_leaves(
            {"tiers": [{"bankroll_multiplier": 10}, {"bankroll_multiplier": 100}]},
            {"tiers": [{"bankroll_multiplier": 100}, {"bankroll_multiplier": 10}]},
        )
        assert any("[0]/bankroll_multiplier" in d for d in diffs), diffs

    def test_identical_inputs_no_diff(self):
        obj = {"a": {"b": [1, 2, 3]}, "c": "x"}
        assert _diff_leaves(obj, json.loads(json.dumps(obj))) == []


# ---------------------------------------------------------------------------
# T1: M275 full content byte-identity (the carve contract)
#     M275 exercises the carved compute with rich, varied data: 4 bankroll
#     tiers (10/100/200/500), each with non-zero bankrupt+survived counts,
#     distinct bankruptcy_rate / fastest / median / percentile values. This
#     proves the moved row-build is byte-identical on real data, AND that all
#     three consumers (bankruptcy_checks, bankruptcy_simulation, bankruptcy_probe)
#     agree (the synthetic-input units in test_6_bankruptcy_coverage_gaps.py
#     cannot — they hand-build the totals dict).
# ---------------------------------------------------------------------------

class TestM275ByteIdentical:
    """M275 mode 1 report content must deep-equal the frozen golden."""

    def test_m275_content_byte_identical(self, m275_summary):
        """Every M275 leaf (minus the 8 varying keys) must match the golden.

        INJECT-BUG (Path A): mutate ONE moved expression in
        bankruptcy_simulation.py build_bankruptcy_rows() (e.g. perturb the
        bankruptcy_rate divisor, flip the final tier sort, drop an int() cast,
        or mis-key a percentile). RED: this test lists the drifted leaf paths
        under /player_impact/bankruptcy_simulation/, /player_impact/
        bankruptcy_probe/, AND /guideline_assessment/bankruptcy_checks/. Revert
        -> GREEN. See module docstring.
        """
        golden = _load_golden("M275")
        produced = _strip_varying(m275_summary)
        diffs = _diff_leaves(golden, produced)
        assert not diffs, (
            f"M275 content drifted from the pre-carve golden ({len(diffs)} leaf "
            f"path(s)). The bankruptcy_simulation carve must be byte-identical "
            f"content.\n"
            + "\n".join(diffs[:50])
            + ("" if len(diffs) <= 50 else f"\n... and {len(diffs) - 50} more")
        )

    def test_m275_leaf_count_matches_baseline(self, m275_summary):
        """Raw M275 leaf count must be 4667 (pre-carve baseline figure).

        A structural sanity check: if the leaf count moved, the carve added or
        dropped fields somewhere — the content diff above would also fail, but
        this pins the headline number for fast triage. (Same figure as Phase 5
        — the carve is shape-preserving.)
        """
        n = len(_flatten_leaves(m275_summary))
        assert n == 4667, (
            f"M275 raw leaf count must be 4667 (pre-carve baseline figure), got {n}. "
            f"The carve changed the report shape."
        )

    def test_m275_three_bankruptcy_consumers_equal_golden(self, m275_summary):
        """All THREE bankruptcy consumers must be present + non-trivially equal.

        Guards against a vacuous pass where both golden and produced somehow
        lacked a bankruptcy key (then the diff would be empty for the wrong
        reason). Asserts each of the split-ownership consumers (brief §0) equals
        the golden:
          1. guideline_assessment.bankruptcy_checks (x100/x200/x500 — pre-summary)
          2. player_impact.bankruptcy_simulation     (the emit() panel)
          3. player_impact.bankruptcy_probe          (the alias)
        """
        golden = _load_golden("M275")
        g_pi = golden.get("player_impact", {})
        p_pi = m275_summary.get("player_impact", {})
        g_ga = golden.get("guideline_assessment", {})
        p_ga = m275_summary.get("guideline_assessment", {})

        # Consumer 1: pre-summary x100/x200/x500 derivation.
        g_checks = g_ga.get("bankruptcy_checks")
        p_checks = p_ga.get("bankruptcy_checks")
        assert g_checks is not None, "golden missing guideline_assessment.bankruptcy_checks"
        assert p_checks is not None, "produced missing guideline_assessment.bankruptcy_checks"
        assert g_checks == p_checks, (
            "bankruptcy_checks (pre-summary x100/x200/x500) drifted between golden "
            "and produced — the rows feeding the pre-summary derivation changed."
        )
        # Non-vacuous: x100/x200/x500 must be present and the derivation must have
        # actually picked the 100/200/500 tiers (not all 0.0 defaults).
        for key in ("x100_bankruptcy_rate", "x200_bankruptcy_rate", "x500_bankruptcy_rate"):
            assert key in p_checks, f"bankruptcy_checks missing {key}"
            assert p_checks[key] > 0.0, (
                f"M275 {key} must be > 0 (the 100/200/500 tiers each saw bankruptcies); "
                f"a value of 0.0 would mean the bankruptcy_by_mult lookup mis-routed. "
                f"Got {p_checks[key]}"
            )

        # Consumer 2: the emit() panel.
        g_sim = g_pi.get("bankruptcy_simulation")
        p_sim = p_pi.get("bankruptcy_simulation")
        assert g_sim is not None, "golden missing player_impact.bankruptcy_simulation"
        assert p_sim is not None, "produced missing player_impact.bankruptcy_simulation"
        assert g_sim == p_sim, (
            "bankruptcy_simulation dict drifted between golden and produced — "
            "see test_m275_content_byte_identical for the exact leaf paths."
        )

        # Consumer 3: the back-compat alias.
        g_probe = g_pi.get("bankruptcy_probe")
        p_probe = p_pi.get("bankruptcy_probe")
        assert g_probe is not None, "golden missing player_impact.bankruptcy_probe"
        assert p_probe is not None, "produced missing player_impact.bankruptcy_probe"
        assert g_probe == p_probe, "bankruptcy_probe drifted between golden and produced"
        # The alias must be the SAME rows as the panel's tiers (the verbatim
        # ``player_impact["bankruptcy_probe"] = bankruptcy_rows`` aliasing).
        assert p_probe == p_sim["tiers"], (
            "produced bankruptcy_probe must equal bankruptcy_simulation.tiers (alias)."
        )

    def test_m275_exercises_rich_carved_paths(self, m275_summary):
        """M275 must drive the carved compute's non-trivial values (not empty defaults).

        The genuine M275 richness that the deep-diff locks is structural, asserted
        here so the byte-identity test is known to exercise live values rather than
        empty defaults:

          - exactly 4 tiers (bankroll multipliers 10/100/200/500),
          - tiers sorted ascending by bankroll_multiplier (the final sort branch),
          - each tier has non-zero robots and non-zero bankrupt_robots (NOT the
            ``total_sessions == 0 -> rate 0.0`` branch — that golden-missed branch
            is covered in test_6_bankruptcy_coverage_gaps.py),
          - bankruptcy_rate values are floats in (0, 1],
          - fastest_bankruptcy_spins is a non-None int (every tier saw a bankruptcy),
          - percentiles dict has 9 string keys (P10..P90).
        """
        sim = m275_summary["player_impact"]["bankruptcy_simulation"]
        assert sim["source"] == "rawdata_replay"
        assert sim["session_spins"] == 10000
        assert sim["percentile_keys"] == [10, 20, 30, 40, 50, 60, 70, 80, 90]
        tiers = sim["tiers"]
        mults = [t["bankroll_multiplier"] for t in tiers]
        assert mults == [10, 100, 200, 500], (
            f"M275 must have tiers [10,100,200,500] (production-default mults), got {mults}"
        )
        # Final sort branch: ascending by bankroll_multiplier.
        assert mults == sorted(mults), f"tiers must be sorted ascending; got {mults}"
        for t in tiers:
            assert isinstance(t["robots"], int) and t["robots"] > 0, (
                f"M275 tier x{t['bankroll_multiplier']} must have >0 robots "
                f"(the live, non-empty-tier branch); got {t['robots']}"
            )
            assert isinstance(t["bankrupt_robots"], int) and t["bankrupt_robots"] > 0, (
                f"M275 tier x{t['bankroll_multiplier']} must have >0 bankrupt_robots; "
                f"got {t['bankrupt_robots']}"
            )
            assert isinstance(t["bankruptcy_rate"], float), f"rate must be float: {t!r}"
            assert 0.0 < t["bankruptcy_rate"] <= 1.0, f"rate out of range: {t!r}"
            # init_credits = mult * bet (bet=1000) — the moved expression.
            assert t["init_credits"] == t["bankroll_multiplier"] * 1000, (
                f"init_credits must equal bankroll_multiplier * bet(1000): {t!r}"
            )
            assert isinstance(t["fastest_bankruptcy_spins"], int), (
                f"M275 tier x{t['bankroll_multiplier']} saw bankruptcies -> "
                f"fastest must be an int (the not-None branch); got "
                f"{t['fastest_bankruptcy_spins']!r}"
            )
            pct = t["percentiles"]
            assert isinstance(pct, dict) and len(pct) == 9, (
                f"percentiles must be a 9-key (P10..P90) dict; got {pct!r}"
            )
            # JSON keys serialize as strings (the ``{str(k): v}`` form).
            assert all(isinstance(k, str) for k in pct), (
                f"percentile keys must be strings (str(k) serialization); got {list(pct)}"
            )


# ---------------------------------------------------------------------------
# T2: M14 full content byte-identity (the second real machine)
# ---------------------------------------------------------------------------

class TestM14ByteIdentical:
    """M14 mode 1 report content must deep-equal the frozen golden.

    M14 is the isolation-anchor machine (M14==M37==M272 share an effective
    version). It exercises the carved build on a different real distribution
    (21 cached chunks vs M275's 2) — a second independent witness that the moved
    row-build is byte-identical.
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
            f"path(s)). The bankruptcy_simulation carve must be byte-identical "
            f"content.\n"
            + "\n".join(diffs[:50])
            + ("" if len(diffs) <= 50 else f"\n... and {len(diffs) - 50} more")
        )

    def test_m14_leaf_count_matches_baseline(self, m14_summary):
        """Raw M14 leaf count must be 6864 (pre-carve baseline figure)."""
        n = len(_flatten_leaves(m14_summary))
        assert n == 6864, (
            f"M14 raw leaf count must be 6864 (pre-carve baseline figure), got {n}."
        )

    def test_m14_three_bankruptcy_consumers_equal_golden(self, m14_summary):
        """M14: all three bankruptcy consumers present, equal to golden, 4 tiers.

        Also asserts the verbatim build form survives the carve: M14 has the same
        4-tier shape, every tier populated.
        """
        golden = _load_golden("M14")
        g_pi = golden.get("player_impact", {})
        p_pi = m14_summary.get("player_impact", {})
        g_ga = golden.get("guideline_assessment", {})
        p_ga = m14_summary.get("guideline_assessment", {})

        assert g_ga.get("bankruptcy_checks") == p_ga.get("bankruptcy_checks")
        assert g_pi.get("bankruptcy_simulation") == p_pi.get("bankruptcy_simulation")
        assert g_pi.get("bankruptcy_probe") == p_pi.get("bankruptcy_probe")

        p_sim = p_pi["bankruptcy_simulation"]
        mults = [t["bankroll_multiplier"] for t in p_sim["tiers"]]
        assert mults == [10, 100, 200, 500], (
            f"produced M14 tier mults must be [10,100,200,500]. Got {mults}"
        )
        # Every tier populated (the live branch, not the zero-bankrupt branch).
        for t in p_sim["tiers"]:
            assert t["robots"] > 0, f"M14 tier x{t['bankroll_multiplier']} must have robots"
        # Alias identity.
        assert p_pi["bankruptcy_probe"] == p_sim["tiers"]


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
        genuinely drifting content field (e.g. a bankruptcy value that somehow
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

    def test_bankruptcy_leaves_are_deterministic_between_runs(self, m275_summary):
        """The bankruptcy consumers specifically must be byte-identical run-to-run.

        Narrows the paranoid guard onto the carved feature: the bankruptcy_checks
        / bankruptcy_simulation / bankruptcy_probe leaves must NOT appear in the
        run-to-run diff at all (they are pure functions of the deterministic
        cached chunks).
        """
        second = _run_analyzer("M275", _M275_CACHE)
        a = _flatten_leaves(m275_summary)
        b = _flatten_leaves(second)
        bankruptcy_drift = sorted(
            p for p in set(a) | set(b)
            if a.get(p) != b.get(p)
            and ("bankruptcy" in p)
        )
        assert not bankruptcy_drift, (
            f"bankruptcy leaves drifted between two identical runs — the carved "
            f"build must be deterministic: {bankruptcy_drift}"
        )
