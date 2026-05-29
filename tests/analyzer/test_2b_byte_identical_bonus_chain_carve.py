"""Phase 2b — REAL full deep-diff byte-identity regression for the bonus_chain_dynamics carve.

This is the gate-1 contract from
``session_artifacts/_impl/phase_extract_2b_bonus_chain/brief.md`` §3:
the bonus_chain_dynamics carve (moving the dict-build — the ``_quantiles`` closure,
the ``depth_curve`` loop, and the ``bonus_chain_dynamics`` dict literal with its
``by_feature`` comprehension — out of ``player_impact_analyzer.py`` into the plugin)
MUST produce byte-identical report *content*.  The pre-existing
``test_c6_byte_identical_bonus_chain.py`` is only *structural* (it asserts
``applicable`` / ``chain_count`` / a handful of named fields) — it would NOT catch
a reordered dict key, a rewritten ``_quantiles`` index, an ``avg_chain_length``
divisor change, a None-vs-0.0 flip, or a drifted ``by_feature`` sub-field inside the
carved compute.  This test closes that gap with a TRUE full-JSON leaf-by-leaf deep
diff against a committed content-only golden.

This is the SECOND carve (2a = collect_mechanic, shipped); this file MIRRORS
``test_2a_byte_identical_collect_mechanic_carve.py`` exactly (same helpers, same
strip-list, same guard-the-guard suite, same vary-key allowlist test).

Why a golden + leaf-allowlist (not a full-file hash)
----------------------------------------------------
The summary embeds 8 leaf KEY NAMES that legitimately vary and must be excluded:

  - per-RUN metadata (differ every run even at frozen code):
      run_id, report_id, started_at, finished_at, duration_seconds, evaluated_at
  - version STAMPS (differ when *any* analyzer code changes — including this
    very carve, since base_hash shrank 57fdb323585d -> 980f488f4bb2):
      analyzer_version, effective_analyzer_version

These 8 keys are stripped wherever they occur (top-level AND nested — e.g.
``sampling.started_at``, ``guideline_comparison.evaluated_at``) before the diff.
EVERYTHING ELSE — the entire ``player_impact.bonus_chain_dynamics`` dict, the
``payout_ids_top20`` ``notes`` blocks, ``rtp``, all of ``player_impact``,
``config_md5`` / ``code_md5`` — must match the golden exactly.

The golden was committed by the impl-implementer and INDEPENDENTLY RE-VALIDATED by
the impl-tester (2026-05-29): running the CURRENT post-carve analyzer and stripping
the 8 varying keys reproduced the golden leaf-for-leaf (M275 = 4659 content leaves /
0 drift; M14 = 6856 content leaves / 0 drift), and the goldens contain NONE of the 8
varying keys.  The coordinator independently proved post-carve content == pre-carve
content (M275 = 4667 raw leaves, M14 = 6864 raw leaves, 0 content drift).  Regenerate
with::

    python - <<'PY'
    # see _strip_varying() below — run analyzer, strip, json.dump(sort_keys=True)
    PY

Inject-bug recipe (Path A — content drift; per feedback_enumerate_safety_paths.md)
----------------------------------------------------------------------------------
Temporarily mutate ONE moved expression in
``fresh_slotlab/analyzer/features/bonus_chain_dynamics.py`` emit(), e.g. change the
``avg_chain_length`` divisor::

    "avg_chain_length": (
        sum(bonus_chain_lengths) / bonus_chain_count
to::
    "avg_chain_length": (
        sum(bonus_chain_lengths) / (bonus_chain_count + 1)   # BUG

RED: ``test_m275_content_byte_identical`` fails listing the drifted leaf path
     ``/player_impact/bonus_chain_dynamics/avg_chain_length`` (golden != produced).
Revert -> GREEN.

Captured evidence (2026-05-29) lives at
``session_artifacts/_impl/phase_extract_2b_bonus_chain/inject_bug_evidence.md``.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md
    inject-bug -> red -> revert -> green is mandatory for the new carve path.
- memory/feedback_perf_claim_needs_e2e_event_stream.md
    a REAL subprocess against real cached M275/M14 — unit tests alone cannot
    catch PIA<->plugin field drift (the _make_stash() unit uses uniform [5]*908
    data → quantiles all collapse; only REAL varied M275 data exercises the
    _quantiles p50/p90/p95 spread, the depth_curve buckets, and the by_feature
    NCS+NewFreespin split).  Mock nothing; run the actual CLI.
- memory/feedback_invariant_with_fallback_hides_drift.md
    the full deep-diff catches silent attribution drift (None-vs-0.0,
    absent-vs-present) that a structural "is the key there?" test misses.
- memory/feedback_aggregator_parity_invariant.md
    bonus_chain_dynamics is RTP_CONTRIBUTION=False -> ``rtp`` must be unchanged;
    the deep diff covers ``rtp`` so any drift fails loud.
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
# with this exact set; see module docstring — re-validated by the impl-tester).
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
    surfaces as a distinct path (e.g. /player_impact/payout_ids_top20[3]/notes/
    is_trigger_marker).
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
    path = _FIXTURES / f"{machine}_mode1_bonus_chain_golden.json"
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
        diffs = _diff_leaves({"a": None}, {"a": 0.0})
        assert any("/a" in d and "DRIFT" in d for d in diffs), diffs

    def test_diff_detects_added_and_removed(self):
        diffs = _diff_leaves({"a": 1}, {"a": 1, "b": 2})
        assert any("ADDED" in d and "/b" in d for d in diffs), diffs
        diffs2 = _diff_leaves({"a": 1, "b": 2}, {"a": 1})
        assert any("REMOVED" in d and "/b" in d for d in diffs2), diffs2

    def test_diff_detects_list_reorder(self):
        diffs = _diff_leaves({"l": [{"k": 1}, {"k": 2}]}, {"l": [{"k": 2}, {"k": 1}]})
        # positional indexing makes a reorder a value drift at [0]/k and [1]/k
        assert any("[0]/k" in d for d in diffs), diffs

    def test_identical_inputs_no_diff(self):
        obj = {"a": {"b": [1, 2, 3]}, "c": "x"}
        assert _diff_leaves(obj, json.loads(json.dumps(obj))) == []


# ---------------------------------------------------------------------------
# T1: M275 full content byte-identity (the carve contract)
#     M275 is the KEY machine: chain_count=908, NCS=841 + NewFreespin=67 →
#     len>=2 majority-vote trigger path + a real _quantiles spread + a populated
#     depth_curve + a two-feature by_feature split. This is what proves the
#     moved compute is byte-identical on RICH varied data (the uniform [5]*908
#     unit fixture in test_c6_*.py cannot — its quantiles all collapse to 5).
# ---------------------------------------------------------------------------

class TestM275ByteIdentical:
    """M275 mode 1 report content must deep-equal the frozen golden."""

    def test_m275_content_byte_identical(self, m275_summary):
        """Every M275 leaf (minus the 8 varying keys) must match the golden.

        INJECT-BUG (Path A): rewrite ONE moved expression in
        bonus_chain_dynamics.py emit() (e.g. change the avg_chain_length divisor,
        a _quantiles index, or a by_feature sub-field). RED: this test lists the
        drifted leaf path (e.g. /player_impact/bonus_chain_dynamics/avg_chain_length).
        Revert -> GREEN. See module docstring + inject_bug_evidence.md.
        """
        golden = _load_golden("M275")
        produced = _strip_varying(m275_summary)
        diffs = _diff_leaves(golden, produced)
        assert not diffs, (
            f"M275 content drifted from the pre-carve golden ({len(diffs)} leaf "
            f"path(s)). The bonus_chain_dynamics carve must be byte-identical content.\n"
            + "\n".join(diffs[:50])
            + ("" if len(diffs) <= 50 else f"\n... and {len(diffs) - 50} more")
        )

    def test_m275_leaf_count_matches_coordinator(self, m275_summary):
        """Raw M275 leaf count must be 4667 (coordinator's deep-diff figure).

        A structural sanity check: if the leaf count moved, the carve added or
        dropped fields somewhere — the content diff above would also fail, but
        this pins the headline number from the brief for fast triage.
        """
        n = len(_flatten_leaves(m275_summary))
        assert n == 4667, (
            f"M275 raw leaf count must be 4667 (brief §3 coordinator figure), got {n}. "
            f"The carve changed the report shape."
        )

    def test_m275_bonus_chain_dynamics_in_golden_and_produced(self, m275_summary):
        """bonus_chain_dynamics must be present + non-trivially equal in both.

        Guards against a vacuous pass where both golden and produced somehow
        lacked the carved key (then the diff would be empty for the wrong reason).
        """
        golden = _load_golden("M275")
        g_bcd = golden.get("player_impact", {}).get("bonus_chain_dynamics")
        p_bcd = m275_summary.get("player_impact", {}).get("bonus_chain_dynamics")
        assert g_bcd is not None, "golden missing player_impact.bonus_chain_dynamics"
        assert p_bcd is not None, "produced missing player_impact.bonus_chain_dynamics"
        assert g_bcd == p_bcd, (
            "bonus_chain_dynamics dict drifted between golden and produced — "
            "see test_m275_content_byte_identical for the exact leaf paths."
        )
        # The carved feature is genuinely exercised on M275 (applicable=True),
        # with the rich data that drives _quantiles / depth_curve / by_feature.
        assert g_bcd["applicable"] is True
        assert g_bcd["chain_count"] == 908
        # by_feature must carry the two-feature split (the len>=2 path).
        assert "NormalCollectionSpin" in g_bcd["by_feature"]
        assert "NewFreespin" in g_bcd["by_feature"]

    def test_m275_exercises_rich_carved_paths(self, m275_summary):
        """M275 must drive the carved compute's RICH branches (not collapsed ones).

        IMPORTANT (impl-tester finding 2026-05-29): M275 mode 1's bonus chains are
        ALL length 10 / ratio 100, so chain_length_quantiles is degenerate
        (p50==p90==p95==max==10) on REAL data too — a `_quantiles` *index* bug
        would NOT surface in the chain_length/max_ratio quantiles deep-diff
        (uniform input → every index lands on 10).  The genuine M275 richness that
        the deep-diff DOES lock is structural, asserted here so the byte-identity
        test is known to exercise live branches rather than empty defaults:

          - by_feature carries the TWO-feature split (NewFreespin=67 +
            NormalCollectionSpin=841) → the by_feature comprehension + the
            len>=2 majority-vote trigger path,
          - extra_ratio_by_chain_depth (the moved depth_curve loop) has POPULATED
            buckets with the `tot/cnt` division exercised (avg_extra_ratio>0),
          - extra_ratio_histogram (the sorted-keys comprehension) is non-empty.

        The `_quantiles` *value* path is still covered byte-identically (it must
        emit {p50:10,...avg:10.0}); the index-sensitivity gap is covered instead by
        a dedicated synthetic-input unit test — see
        test_2b_bonus_chain_quantiles_index.py.
        """
        bcd = m275_summary["player_impact"]["bonus_chain_dynamics"]
        # Two-feature by_feature split (len>=2 path).
        bf = bcd["by_feature"]
        assert set(bf) == {"NewFreespin", "NormalCollectionSpin"}, (
            f"M275 by_feature must carry both features (len>=2 path). Got {list(bf)}"
        )
        assert bf["NormalCollectionSpin"]["chain_count"] == 841
        assert bf["NewFreespin"]["chain_count"] == 67
        assert bf["NormalCollectionSpin"]["chain_count"] + bf["NewFreespin"]["chain_count"] == 908
        # depth_curve loop produced populated buckets with the tot/cnt division.
        depth = {d["depth_bucket"]: d for d in bcd["extra_ratio_by_chain_depth"]}
        assert depth["6-10"]["rounds"] > 0 and depth["6-10"]["avg_extra_ratio"] > 0, (
            f"M275 depth_curve must have a populated 6-10 bucket. Got {depth.get('6-10')}"
        )
        # extra_ratio_histogram (sorted-keys comprehension) is non-empty.
        assert len(bcd["extra_ratio_histogram"]) >= 1, (
            f"M275 extra_ratio_histogram must be non-empty. Got {bcd['extra_ratio_histogram']}"
        )


# ---------------------------------------------------------------------------
# T2: M14 full content byte-identity (the non-applicable machine)
# ---------------------------------------------------------------------------

class TestM14ByteIdentical:
    """M14 mode 1 report content must deep-equal the frozen golden.

    M14 has bonus_chain_dynamics.applicable=False — it exercises the other half
    of the carved branch logic (empty bonus_chain_lengths -> the 0.0/[] default
    paths in every dict field, the empty by_feature comprehension, and the
    empty-list _quantiles early-return {"p50":0,...}).
    """

    def test_m14_content_byte_identical(self, m14_summary):
        """Every M14 leaf (minus the 8 varying keys) must match the golden.

        INJECT-BUG (Path A): same as M275 — a content drift in the carve surfaces
        here too (M14 exercises the applicable=False / empty-default branch). The
        empty-list _quantiles default {"p50":0,...} is uniquely exercised here.
        RED -> revert -> GREEN.
        """
        golden = _load_golden("M14")
        produced = _strip_varying(m14_summary)
        diffs = _diff_leaves(golden, produced)
        assert not diffs, (
            f"M14 content drifted from the pre-carve golden ({len(diffs)} leaf "
            f"path(s)). The bonus_chain_dynamics carve must be byte-identical content.\n"
            + "\n".join(diffs[:50])
            + ("" if len(diffs) <= 50 else f"\n... and {len(diffs) - 50} more")
        )

    def test_m14_leaf_count_matches_coordinator(self, m14_summary):
        """Raw M14 leaf count must be 6864 (coordinator's deep-diff figure)."""
        n = len(_flatten_leaves(m14_summary))
        assert n == 6864, (
            f"M14 raw leaf count must be 6864 (brief §3 coordinator figure), got {n}."
        )

    def test_m14_bonus_chain_dynamics_not_applicable(self, m14_summary):
        """M14 bonus_chain_dynamics must be present, applicable=False, equal to golden.

        Also asserts the empty-default forms survive the carve verbatim:
        chain_count=0, avg_chain_length=0.0, by_feature={}, and the empty-list
        _quantiles early-return ({"p50":0,"p90":0,"p95":0,"max":0,"avg":0.0}).
        """
        golden = _load_golden("M14")
        g_bcd = golden.get("player_impact", {}).get("bonus_chain_dynamics")
        p_bcd = m14_summary.get("player_impact", {}).get("bonus_chain_dynamics")
        assert g_bcd is not None and p_bcd is not None
        assert g_bcd == p_bcd
        assert g_bcd["applicable"] is False
        assert g_bcd["chain_count"] == 0
        assert g_bcd["avg_chain_length"] == 0.0
        assert g_bcd["by_feature"] == {}
        # empty-list _quantiles early-return (the moved closure's no-data branch)
        assert g_bcd["chain_length_quantiles"] == {
            "p50": 0, "p90": 0, "p95": 0, "max": 0, "avg": 0.0
        }


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
        genuinely drifting content field (e.g. a bonus_chain_dynamics value that
        somehow became nondeterministic). Version stamps are constant at fixed
        code, so only the 6 metadata keys appear here.
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
