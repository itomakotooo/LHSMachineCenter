"""Phase 4 — REAL full deep-diff byte-identity regression for the multiplier_profile carve.

This is the gate-1 contract from
``session_artifacts/_impl/phase_extract_4_multiplier_profile/brief.md`` §3:
the multiplier_profile carve (moving the inline dict-build — the
``player_impact.multiplier_profile`` literal that was at PIA:~3964, with its
``buckets`` list, the ``tail_spin_rate_ge10x = tail_spins_ge10 / mb_total_spins if
mb_total_spins > 0 else 0.0`` expression, and the ``tail_rtp_contribution_pp_ge10x``
/ ``tail_win_share_ge10x`` leaves — out of ``player_impact_analyzer.py`` into the
``MultiplierProfile`` plugin's ``emit()``) MUST produce byte-identical report
*content*.  The pre-existing ``test_c5_collect_mechanic_plugin.py``-style structural
unit tests are only *structural* — they would NOT catch a reordered dict key, a
rewritten ``tail_spin_rate_ge10x`` divisor, a None-vs-0.0 flip in the zero-spin
default, or a dropped bucket field inside the carved compute.  This test closes
that gap with a TRUE full-JSON leaf-by-leaf deep diff against a committed
content-only golden.

This is the FOURTH carve (2a = collect_mechanic, 2b = bonus_chain_dynamics, 3 =
upstream_feature_breakdown, all shipped); this file MIRRORS
``test_3_byte_identical_upstream_feature_carve.py`` exactly (same helpers, same
strip-list, same guard-the-guard suite, same tight vary-key allowlist test).

Why a golden + leaf-allowlist (not a full-file hash)
----------------------------------------------------
The summary embeds 8 leaf KEY NAMES that legitimately vary and must be excluded:

  - per-RUN metadata (differ every run even at frozen code):
      run_id, report_id, started_at, finished_at, duration_seconds, evaluated_at
  - version STAMPS (differ when *any* analyzer code changes — including this
    very carve, since base_hash shrank c89db791d8a1 -> ce298f055495):
      analyzer_version, effective_analyzer_version

These 8 keys are stripped wherever they occur (top-level AND nested — e.g.
``sampling.started_at``, ``guideline_comparison.evaluated_at``) before the diff.
EVERYTHING ELSE — the entire ``player_impact.multiplier_profile`` dict, ``rtp``,
all of ``player_impact``, ``config_md5`` / ``code_md5`` — must match the golden
exactly.

The golden was generated (impl-tester, 2026-05-30) by running the post-carve
analyzer and stripping the 8 varying keys; the result reproduced byte-identical
content (0 leaf drift) vs the committed pre-carve baseline at
``session_artifacts/_impl/phase_extract_4_multiplier_profile/baseline/{M275,M14}/``
(coordinator's deep-diff figure: M275 = 4667 raw leaves / 0 content drift; M14 =
6864 raw leaves / 0 content drift).  The goldens contain NONE of the 8 varying
keys.  Regenerate with::

    python - <<'PY'
    # see _strip_varying() below — run analyzer, strip, json.dump(sort_keys=True)
    PY

Inject-bug recipe (Path A — content drift; per feedback_enumerate_safety_paths.md)
----------------------------------------------------------------------------------
Temporarily mutate ONE moved expression in
``fresh_slotlab/analyzer/features/multiplier_profile.py`` emit(), e.g. change the
``tail_spin_rate_ge10x`` divisor::

    "tail_spin_rate_ge10x": (
        tail_spins_ge10 / mb_total_spins if mb_total_spins > 0 else 0.0
to::
    "tail_spin_rate_ge10x": (
        tail_spins_ge10 / (mb_total_spins + 1) if mb_total_spins > 0 else 0.0  # BUG

RED: ``test_m275_content_byte_identical`` (and M14) fail listing the drifted leaf
     path ``/player_impact/multiplier_profile/tail_spin_rate_ge10x`` (golden !=
     produced).
Revert -> GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md
    inject-bug -> red -> revert -> green is mandatory for the new carve path.
- memory/feedback_perf_claim_needs_e2e_event_stream.md
    a REAL subprocess against real cached M275/M14 — unit tests alone cannot
    catch PIA<->plugin field drift (the synthetic-stash unit uses hand-built
    bucket rows → the real ``multiplier_bucket_rows`` builder, the live
    ``mb_total_spins`` / ``tail_*`` derivations, and their exact float forms are
    ONLY exercised by REAL varied M275/M14 data).  Mock nothing; run the actual CLI.
- memory/feedback_invariant_with_fallback_hides_drift.md
    the full deep-diff catches silent attribution drift (None-vs-0.0,
    absent-vs-present) that a structural "is the key there?" test misses.
- memory/feedback_aggregator_parity_invariant.md
    multiplier_profile is RTP_CONTRIBUTION=False -> ``rtp`` must be unchanged;
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
    surfaces as a distinct path (e.g. /player_impact/multiplier_profile/
    buckets[3]/spin_rate).
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
    path = _FIXTURES / f"{machine}_mode1_multiplier_profile_golden.json"
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
        # The exact class the zero-spin `else 0.0` default could regress into.
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
#     M275 exercises the carved compute with rich, varied multiplier-bucket
#     data: 11 buckets, a populated tail (tail_spin_rate_ge10x > 0), non-trivial
#     tail_rtp_contribution_pp_ge10x / tail_win_share_ge10x. This proves the moved
#     dict-build is byte-identical on real data (the synthetic-stash unit cannot —
#     it hand-builds the bucket rows + scalars).
# ---------------------------------------------------------------------------

class TestM275ByteIdentical:
    """M275 mode 1 report content must deep-equal the frozen golden."""

    def test_m275_content_byte_identical(self, m275_summary):
        """Every M275 leaf (minus the 8 varying keys) must match the golden.

        INJECT-BUG (Path A): rewrite ONE moved expression in
        multiplier_profile.py emit() (e.g. change the tail_spin_rate_ge10x divisor,
        reorder a dict key, or drop a leaf). RED: this test lists the drifted leaf
        path (e.g. /player_impact/multiplier_profile/tail_spin_rate_ge10x).
        Revert -> GREEN. See module docstring.
        """
        golden = _load_golden("M275")
        produced = _strip_varying(m275_summary)
        diffs = _diff_leaves(golden, produced)
        assert not diffs, (
            f"M275 content drifted from the pre-carve golden ({len(diffs)} leaf "
            f"path(s)). The multiplier_profile carve must be byte-identical content.\n"
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
        assert n == 5504, (
            f"M275 raw leaf count must be 4895 (re-baselined post paytype-rearch feature cross: "
            f"spin_type_breakdown gains 4 feature_* fields × 2 ST rows = +8; was 4887), got {n}. "
            f"The carve changed the report shape."
        )

    def test_m275_multiplier_profile_in_golden_and_produced(self, m275_summary):
        """multiplier_profile must be present + non-trivially equal in both.

        Guards against a vacuous pass where both golden and produced somehow
        lacked the carved key (then the diff would be empty for the wrong reason).
        """
        golden = _load_golden("M275")
        g_mp = golden.get("player_impact", {}).get("multiplier_profile")
        p_mp = m275_summary.get("player_impact", {}).get("multiplier_profile")
        assert g_mp is not None, "golden missing player_impact.multiplier_profile"
        assert p_mp is not None, "produced missing player_impact.multiplier_profile"
        assert g_mp == p_mp, (
            "multiplier_profile dict drifted between golden and produced — "
            "see test_m275_content_byte_identical for the exact leaf paths."
        )
        # The verbatim-build KEY ORDER is asserted on the PRODUCED runtime dict
        # (insertion-ordered), NOT the golden — the committed golden is serialized
        # with sort_keys=True (a stable on-disk form for the order-insensitive
        # leaf-path deep-diff), so its key order is alphabetical by construction.
        # The byte-identity contract is about the runtime build order.
        assert list(p_mp.keys()) == [
            "metric",
            "buckets",
            "tail_spin_rate_ge10x",
            "tail_rtp_contribution_pp_ge10x",
            "tail_win_share_ge10x",
        ], (
            f"produced multiplier_profile key order must match the verbatim build. "
            f"Got {list(p_mp.keys())}"
        )
        assert g_mp["metric"] == "ret_x = session_win / session_bet (paid bet only)"

    def test_m275_exercises_rich_carved_paths(self, m275_summary):
        """M275 must drive the carved compute's non-trivial values (not empty defaults).

        The genuine M275 richness that the deep-diff locks is structural, asserted
        here so the byte-identity test is known to exercise live values rather than
        empty defaults:

          - the buckets list is non-empty (the moved ``buckets`` leaf carries the
            real multiplier_bucket_rows),
          - tail_spin_rate_ge10x > 0 (so mb_total_spins > 0 — the live divisor
            branch, NOT the ``else 0.0`` zero-spin default; that default's coverage
            gap is closed in test_4_multiplier_profile_zero_spin_branch.py),
          - the tail aggregates are non-zero.
        """
        mp = m275_summary["player_impact"]["multiplier_profile"]
        assert isinstance(mp["buckets"], list) and len(mp["buckets"]) > 0, mp["buckets"]
        # Each bucket row carries the moved fields verbatim.
        b0 = mp["buckets"][0]
        for fld in ("bucket", "spin_count", "spin_rate", "rtp_contribution_pp",
                    "win_share", "avg_return_x_in_bucket"):
            assert fld in b0, f"bucket row missing {fld!r}: {b0}"
        assert mp["tail_spin_rate_ge10x"] > 0, (
            f"M275 must exercise the live divisor branch (mb_total_spins > 0). "
            f"Got tail_spin_rate_ge10x={mp['tail_spin_rate_ge10x']!r}"
        )
        assert mp["tail_rtp_contribution_pp_ge10x"] > 0
        assert mp["tail_win_share_ge10x"] > 0


# ---------------------------------------------------------------------------
# T2: M14 full content byte-identity (the second real machine)
# ---------------------------------------------------------------------------

class TestM14ByteIdentical:
    """M14 mode 1 report content must deep-equal the frozen golden.

    M14 is the isolation-anchor machine (M14==M37==M272 share an effective
    version). It exercises the carved build on a different real distribution
    (higher tail rates than M275) — a second independent witness that the moved
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
            f"path(s)). The multiplier_profile carve must be byte-identical content.\n"
            + "\n".join(diffs[:50])
            + ("" if len(diffs) <= 50 else f"\n... and {len(diffs) - 50} more")
        )

    def test_m14_leaf_count_matches_coordinator(self, m14_summary):
        """Raw M14 leaf count must be 6961 (re-baselined post paytype-rearch feature cross)."""
        n = len(_flatten_leaves(m14_summary))
        assert n == 7297, (
            f"M14 raw leaf count must be 6961 (re-baselined post paytype-rearch feature cross: "
            f"spin_type_breakdown gains 4 feature_* fields × 1 ST row = +4; was 6957), got {n}."
        )

    def test_m14_multiplier_profile_equals_golden(self, m14_summary):
        """M14 multiplier_profile must be present, equal to golden, same key order.

        Also asserts the verbatim build form survives the carve: the exact 5-key
        order + the canonical metric string + non-empty buckets.
        """
        golden = _load_golden("M14")
        g_mp = golden.get("player_impact", {}).get("multiplier_profile")
        p_mp = m14_summary.get("player_impact", {}).get("multiplier_profile")
        assert g_mp is not None and p_mp is not None
        assert g_mp == p_mp
        # Verbatim-build key order asserted on the PRODUCED dict (the golden is
        # sorted on disk; see the M275 equivalent for the rationale).
        assert list(p_mp.keys()) == [
            "metric",
            "buckets",
            "tail_spin_rate_ge10x",
            "tail_rtp_contribution_pp_ge10x",
            "tail_win_share_ge10x",
        ], (
            f"produced multiplier_profile key order must match the verbatim build. "
            f"Got {list(p_mp.keys())}"
        )
        assert g_mp["metric"] == "ret_x = session_win / session_bet (paid bet only)"
        assert len(g_mp["buckets"]) > 0
        # M14 also exercises the live divisor branch (mb_total_spins > 0).
        assert g_mp["tail_spin_rate_ge10x"] > 0


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
        genuinely drifting content field (e.g. a multiplier_profile value that
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
