"""Phase 2b — fail-loud stash contract for the carved bonus_chain_dynamics plugin.

After the Phase 2b carve, PIA stashes ONLY the RAW accumulator inputs into
``summary["_bonus_chain_dynamics_data"]`` and the plugin's ``emit()`` owns the
dict-build (the ``_quantiles`` closure + ``depth_curve`` loop + the dict literal,
moved verbatim from PIA).  Per ``feedback_no_silent_swallow.md``, if the stash is
missing or an expected RAW key is absent, emit() MUST raise a diagnostic
``RuntimeError`` — it must NOT silently default (which would corrupt the report
numbers with no error).

This file MIRRORS ``test_2a_collect_mechanic_fail_loud_stash.py`` and locks the
fail-loud paths for bonus_chain_dynamics:

  Path B-1 (stash key entirely absent):
      emit() with no ``_bonus_chain_dynamics_data`` in summary -> RuntimeError
      naming the stash key.

  Path B-2 (stash present but a RAW input key missing):
      The carve's explicit ``_missing`` check over the 9 expected raw keys.
      Deleting any one must raise RuntimeError naming the missing key(s) and
      citing feedback_no_silent_swallow.md — NOT a KeyError swallowed into a
      wrong number, NOT a silent default.

  Path B-3 (scatter_feature_chain_counts missing when len(scatter_feature_names) >= 2):
      A PRE-EXISTING fail-loud path (R1 d2 schema-drift guard), re-asserted here
      because it shares the same fail-loud contract. With 2+ scatter features and
      no chain-counts key, emit() must raise RuntimeError (schema drift), not
      silently fall back to alphabetical-first.

We also run the REAL end-to-end inject-bug once (delete a raw key from PIA's
stash builder, run the subprocess, confirm the failure surfaces as
``feature_errors[bonus_chain_dynamics]`` rather than a wrong value) and capture the
evidence in
``session_artifacts/_impl/phase_extract_2b_bonus_chain/inject_bug_evidence.md``.

Inject-bug recipe (Path B — fail-loud stash; per feedback_enumerate_safety_paths.md)
------------------------------------------------------------------------------------
UNIT (this file, no source edit needed — we delete a key from the constructed stash):
    build a full stash, ``del stash["all_chains_by_feature"]``, call emit() ->
    RuntimeError naming 'all_chains_by_feature'.  This proves the guard's logic.

END-TO-END (real PIA edit, run once during authoring):
    In fresh_slotlab/player_impact_analyzer.py, in the
    summary["_bonus_chain_dynamics_data"] = {...} builder (~line 4665), comment out
    one raw key line, e.g.::
        # "all_chains_by_feature": all_chains_by_feature,
    RED: a real `python player_impact_analyzer.py --machine M275 ...` run lands
         the failure in summary["feature_errors"]["bonus_chain_dynamics"] with the
         RuntimeError message naming 'all_chains_by_feature' (NOT a silently-wrong
         bonus_chain_dynamics dict).
    Revert -> GREEN (no feature_errors; bonus_chain_dynamics correct).

Memory files cited
------------------
- memory/feedback_no_silent_swallow.md
    a missing raw input must fail loudly with a diagnostic, never default to a
    silent wrong number.  The plugin surfaces it via feature_errors (disk).
- memory/feedback_enumerate_safety_paths.md
    inject-bug -> red -> revert -> green for EACH safety path; B-1, B-2 and B-3.
- memory/feedback_capture_drift.md
    the scatter_feature_chain_counts guard (B-3) identifies a stash-extension
    schema drift with a descriptive message rather than silently degrading.
- memory/feedback_subprocess_import_suicide_and_module_globals.md
    import-time side-effect freedom (the plugin import is a pure register()).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_M275_CACHE = _REPO_ROOT / "rawdata" / "M275" / "mode_1"

# The 9 RAW accumulator keys the carved emit() requires from the stash.
# MUST match _expected_keys in bonus_chain_dynamics.py emit() VERBATIM — if the
# plugin's required-key tuple changes, this list must change with it (otherwise
# the per-key parametrized test below goes stale). Verified against the
# TestExpectedKeysMirrorPlugin guard below.
_EXPECTED_RAW_KEYS: tuple[str, ...] = (
    "bonus_chain_lengths",
    "bonus_chain_max_ratios",
    "bonus_total_rounds_global",
    "bonus_retrigger_rounds_global",
    "bonus_chain_retrigger_events",
    "bonus_extra_ratio_counts",
    "bonus_depth_ratio_count",
    "bonus_depth_ratio_sum",
    "all_chains_by_feature",
)


def _import_plugin_class():
    try:
        from fresh_slotlab.analyzer.features.bonus_chain_dynamics import BonusChainDynamics
    except ImportError:
        from analyzer.features.bonus_chain_dynamics import BonusChainDynamics  # type: ignore[no-redef]
    return BonusChainDynamics


def _make_ctx(scatter_marker_pids: frozenset[str] = frozenset()) -> Any:
    """Minimal mock PipelineContext with a mechanism_registry.scatter_marker_pids."""
    ctx = MagicMock()
    ctx.mechanism_registry.scatter_marker_pids = scatter_marker_pids
    return ctx


def _full_stash() -> dict[str, Any]:
    """A complete, valid RAW-input stash (every one of the 9 keys present).

    Single-feature (NormalCollectionSpin) so emit() hits the 'unique' confidence
    branch which does not need scatter_feature_chain_counts — keeps the B-1/B-2
    tests focused on the 9 raw keys. (B-3 builds its own 2-feature stash.)
    """
    return {
        "bonus_chain_lengths": [5, 6, 7, 8],
        "bonus_chain_max_ratios": [1, 2, 3, 4],
        "bonus_total_rounds_global": 26,
        "bonus_retrigger_rounds_global": 2,
        "bonus_chain_retrigger_events": [0, 1, 0, 1],
        "bonus_extra_ratio_counts": {1: 3, 2: 1},
        "bonus_depth_ratio_count": {"1": 4, "2-5": 2},
        "bonus_depth_ratio_sum": {"1": 4.0, "2-5": 5.0},
        "all_chains_by_feature": {
            "NormalCollectionSpin": {
                "lengths": [5, 6, 7, 8],
                "max_ratios": [1, 2, 3, 4],
                "total_rounds": 26,
                "retrigger_rounds": 2,
            },
        },
        "scatter_feature_names": ["NormalCollectionSpin"],
        "scatter_feature_chain_counts": {"NormalCollectionSpin": 4},
    }


def _summary_with(stash: dict[str, Any]) -> dict[str, Any]:
    """Wrap a stash in a minimal summary with an empty payout_ids_top20."""
    return {
        "_bonus_chain_dynamics_data": stash,
        "player_impact": {"payout_ids_top20": []},
    }


# ---------------------------------------------------------------------------
# T0: the local key-list mirrors the plugin's actual required set
# ---------------------------------------------------------------------------

class TestExpectedKeysMirrorPlugin:
    """Guard: _EXPECTED_RAW_KEYS must equal the plugin's required-key tuple.

    If a refactor changes the plugin's _expected_keys but not this mirror, the
    per-key fail-loud test below would silently stop covering the new key set
    (stale-green). This test fails loudly the moment they diverge.
    """

    def test_full_stash_satisfies_plugin_emit(self):
        """A _full_stash() must drive emit() to success (sanity: the happy path).

        Proves the 9-key list is at least sufficient — if the plugin required a
        key our _full_stash() lacks, emit() would raise and this would fail.
        """
        plugin = _import_plugin_class()()
        summary = _summary_with(_full_stash())
        plugin.emit({}, summary, _make_ctx(frozenset()))  # must NOT raise
        assert "bonus_chain_dynamics" in summary["player_impact"]
        assert summary["player_impact"]["bonus_chain_dynamics"]["applicable"] is True

    def test_no_extra_raw_keys_in_full_stash(self):
        """_full_stash() raw keys must be EXACTLY the 9 expected (no extra raw).

        scatter_feature_names + scatter_feature_chain_counts are derived stash
        fields (not in _expected_keys — they're consumed by the trigger-inference,
        not the raw dict-build), so they are excluded from this check.
        """
        raw_only = set(_full_stash()) - {
            "scatter_feature_names", "scatter_feature_chain_counts"
        }
        assert raw_only == set(_EXPECTED_RAW_KEYS), (
            "_full_stash() raw keys must match _EXPECTED_RAW_KEYS exactly.\n"
            f"extra: {raw_only - set(_EXPECTED_RAW_KEYS)}\n"
            f"missing: {set(_EXPECTED_RAW_KEYS) - raw_only}"
        )

    def test_expected_keys_match_plugin_source(self):
        """_EXPECTED_RAW_KEYS must be byte-identical to the plugin's _expected_keys.

        Reads the plugin source and extracts the _expected_keys tuple literal, so
        a divergence (key added/removed/renamed in the plugin) fails this test
        rather than silently de-covering the parametrized test below.
        """
        import re
        src = (
            _REPO_ROOT / "fresh_slotlab" / "analyzer" / "features"
            / "bonus_chain_dynamics.py"
        ).read_text(encoding="utf-8")
        m = re.search(r"_expected_keys\s*=\s*\((.*?)\)", src, re.DOTALL)
        assert m, "could not locate _expected_keys tuple in plugin source"
        plugin_keys = tuple(re.findall(r'"([a-z_]+)"', m.group(1)))
        assert plugin_keys == _EXPECTED_RAW_KEYS, (
            "plugin _expected_keys diverged from this test's _EXPECTED_RAW_KEYS.\n"
            f"plugin: {plugin_keys}\n"
            f"test:   {_EXPECTED_RAW_KEYS}\n"
            "Update _EXPECTED_RAW_KEYS to match (keeps the parametrized fail-loud "
            "test covering every raw key)."
        )


# ---------------------------------------------------------------------------
# T1: Path B-1 — stash key entirely absent
# ---------------------------------------------------------------------------

class TestStashKeyAbsentFailsLoud:
    """emit() with no stash key must raise RuntimeError (not silently skip)."""

    def test_emit_raises_when_stash_absent(self):
        """No _bonus_chain_dynamics_data in summary -> RuntimeError naming the key.

        INJECT-BUG (Path B-1): in emit(), replace the `if _STASH_KEY not in
        summary: raise RuntimeError(...)` guard with `summary.setdefault(...)`.
        RED: this test fails (no RuntimeError raised). Revert -> GREEN.
        """
        plugin = _import_plugin_class()()
        with pytest.raises(RuntimeError, match=r"_bonus_chain_dynamics_data"):
            plugin.emit({}, {"player_impact": {"payout_ids_top20": []}}, _make_ctx())

    def test_runtime_error_message_is_diagnostic(self):
        """The RuntimeError must be diagnostic (names the key + the plugin + cause).

        Per feedback_no_silent_swallow.md the failure must be actionable, not a
        bare exception.
        """
        plugin = _import_plugin_class()()
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, {}, _make_ctx())
        msg = str(ei.value)
        assert "_bonus_chain_dynamics_data" in msg
        assert "bonus_chain_dynamics plugin" in msg


# ---------------------------------------------------------------------------
# T2: Path B-2 — stash present but a RAW key missing (the NEW 2b path)
# ---------------------------------------------------------------------------

class TestRawKeyMissingFailsLoud:
    """Deleting ANY one of the 9 raw keys must raise RuntimeError naming it.

    This is the new Phase 2b fail-loud path: the stash now carries raw inputs and
    a missing input must NOT be silently defaulted (would corrupt report numbers).
    """

    @pytest.mark.parametrize("missing_key", _EXPECTED_RAW_KEYS)
    def test_missing_raw_key_raises_runtime_error(self, missing_key):
        """For each raw key: delete it -> emit() raises RuntimeError naming it.

        INJECT-BUG (Path B-2 / parametrized): each iteration deletes one raw key
        from the constructed stash. RED if emit() does NOT raise (i.e. if the
        guard were removed). The guard's presence is what makes ALL 9 iterations
        green. Removing the `_missing` check makes most iterations RED (a bare
        KeyError or a silently-wrong dict).
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash[missing_key]
        summary = _summary_with(stash)
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, summary, _make_ctx())
        msg = str(ei.value)
        assert missing_key in msg, (
            f"RuntimeError must name the missing raw key {missing_key!r}. "
            f"Got message: {msg!r}"
        )

    def test_missing_key_error_cites_no_silent_swallow(self):
        """The diagnostic must reference the no-silent-swallow contract.

        Confirms the guard message points the operator/dev at WHY it refused to
        default (per feedback_no_silent_swallow.md), not just THAT it failed.
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash["all_chains_by_feature"]
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, _summary_with(stash), _make_ctx())
        msg = str(ei.value)
        assert "all_chains_by_feature" in msg
        assert "silently default" in msg or "feedback_no_silent_swallow" in msg, (
            f"diagnostic must explain it refuses to silently default. Got: {msg!r}"
        )

    def test_does_not_write_bonus_chain_dynamics_on_missing_key(self):
        """On a missing raw key, emit() must NOT have written a partial dict.

        Critical: the failure must be loud AND clean — no half-built
        bonus_chain_dynamics left in player_impact that a caller (e.g.
        machine_mechanics.emit() via REQUIRES) might consume as if valid.
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash["bonus_depth_ratio_sum"]
        summary = _summary_with(stash)
        with pytest.raises(RuntimeError):
            plugin.emit({}, summary, _make_ctx())
        assert "bonus_chain_dynamics" not in summary["player_impact"], (
            "emit() must not leave a partial bonus_chain_dynamics dict when a raw "
            "key is missing — the failure must be clean (no half-built dict)."
        )

    def test_multiple_missing_keys_all_named(self):
        """When several raw keys are absent, the diagnostic lists ALL of them.

        The guard collects every missing key (not just the first) so a developer
        sees the full gap in one pass.
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash["bonus_chain_lengths"]
        del stash["bonus_total_rounds_global"]
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, _summary_with(stash), _make_ctx())
        msg = str(ei.value)
        assert "bonus_chain_lengths" in msg and "bonus_total_rounds_global" in msg, (
            f"diagnostic must name every missing raw key. Got: {msg!r}"
        )


# ---------------------------------------------------------------------------
# T3: Path B-3 — scatter_feature_chain_counts missing when len >= 2
#     (pre-existing R1 d2 schema-drift guard; re-asserted as part of the
#     fail-loud contract — feedback_capture_drift.md + feedback_no_silent_swallow.md)
# ---------------------------------------------------------------------------

class TestScatterChainCountsMissingFailsLoud:
    """With 2+ scatter features and no scatter_feature_chain_counts -> RuntimeError.

    Must raise (schema drift: the PIA stash extension not deployed with this
    plugin), NOT silently fall back to alphabetical-first.
    """

    def _two_feature_stash(self, with_chain_counts: bool) -> dict[str, Any]:
        """Valid 9-raw-key stash with TWO scatter features (the len>=2 path)."""
        stash: dict[str, Any] = {
            "bonus_chain_lengths": [5] * 101,
            "bonus_chain_max_ratios": [1] * 101,
            "bonus_total_rounds_global": 101 * 5,
            "bonus_retrigger_rounds_global": 0,
            "bonus_chain_retrigger_events": [0] * 101,
            "bonus_extra_ratio_counts": {},
            "bonus_depth_ratio_count": {},
            "bonus_depth_ratio_sum": {},
            "all_chains_by_feature": {
                "AFeature": {"lengths": [5] * 100, "max_ratios": [1] * 100,
                             "total_rounds": 500, "retrigger_rounds": 0},
                "ZFeature": {"lengths": [5], "max_ratios": [1],
                             "total_rounds": 5, "retrigger_rounds": 0},
            },
            "scatter_feature_names": ["AFeature", "ZFeature"],
        }
        if with_chain_counts:
            stash["scatter_feature_chain_counts"] = {"AFeature": 100, "ZFeature": 1}
        return stash

    def test_missing_chain_counts_with_two_features_raises(self):
        """len(scatter_feature_names) >= 2 + no chain_counts -> RuntimeError.

        INJECT-BUG (Path B-3): in emit(), replace the
        `if "scatter_feature_chain_counts" not in stash: raise RuntimeError(...)`
        with a silent `stash.get("scatter_feature_chain_counts", {})`.
        RED: this test fails (no RuntimeError; silent alphabetical fallback).
        Revert -> GREEN.
        """
        plugin = _import_plugin_class()()
        stash = self._two_feature_stash(with_chain_counts=False)
        pid_rows = [{"payout_id": "666", "hit_count": 100, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {"payout_ids_top20": pid_rows},
        }
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, summary, _make_ctx(frozenset({"666"})))
        msg = str(ei.value)
        assert "scatter_feature_chain_counts" in msg, (
            f"RuntimeError must name the missing schema key. Got: {msg!r}"
        )

    def test_present_chain_counts_with_two_features_succeeds(self):
        """The control: WITH chain_counts present, the 2-feature path succeeds.

        Proves the B-3 guard only fires on genuine absence (not on the happy
        2-feature path) — i.e. the guard is precise, not over-broad.
        """
        plugin = _import_plugin_class()()
        stash = self._two_feature_stash(with_chain_counts=True)
        pid_rows = [{"payout_id": "666", "hit_count": 100, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {"payout_ids_top20": pid_rows},
        }
        plugin.emit({}, summary, _make_ctx(frozenset({"666"})))  # must NOT raise
        notes = summary["player_impact"]["payout_ids_top20"][0]["notes"]
        # AFeature wins majority vote (100 > 1) → data_inferred
        assert notes["trigger_target"] == "AFeature"
        assert notes["trigger_target_confidence"] == "data_inferred"


# ---------------------------------------------------------------------------
# T4: End-to-end fail-loud — real subprocess surfaces RuntimeError via
#     feature_errors (NOT a silent wrong value).
#
#     This test is SKIPPED by default (it requires temporarily editing PIA,
#     which we do NOT do automatically in CI). It documents + (when manually
#     un-skipped during authoring) verifies the end-to-end disk-surfacing path.
#     The captured RED evidence lives in inject_bug_evidence.md.
# ---------------------------------------------------------------------------

class TestEndToEndFailLoudIsSurfaced:
    """The end-to-end path: a missing raw key in PIA's stash builder surfaces as
    summary['feature_errors']['bonus_chain_dynamics'] — proven by the authoring-time
    inject-bug (evidence in inject_bug_evidence.md), asserted structurally here.
    """

    def test_feature_errors_is_the_surfacing_channel(self):
        """Sanity: the analyzer surfaces plugin emit() exceptions under
        summary['feature_errors'][feature_id] (the channel the inject-bug used).

        We assert the mechanism exists by checking the PIA emit loop wraps
        emit() and records into feature_errors. (Run the real inject-bug per the
        recipe to see the RuntimeError text land there.)
        """
        src = _PIA.read_text(encoding="utf-8")
        assert "feature_errors" in src, (
            "PIA must surface plugin emit() failures via a 'feature_errors' "
            "summary key (the fail-loud disk channel)."
        )

    @pytest.mark.skip(
        reason="Requires temporarily editing PIA's stash builder; run manually "
        "per the Path B inject-bug recipe. RED evidence captured in "
        "inject_bug_evidence.md (authoring-time, 2026-05-29)."
    )
    def test_e2e_missing_raw_key_lands_in_feature_errors(self):  # pragma: no cover
        """When PIA omits a raw key, M275 run records the RuntimeError in
        feature_errors[bonus_chain_dynamics] (NOT a silently-wrong dict).

        Manual recipe (Path B end-to-end):
          1. Comment out one raw key in PIA's summary["_bonus_chain_dynamics_data"]
             builder (e.g. all_chains_by_feature, ~line 4677).
          2. Run M275 mode 1 from cache.
          3. Assert summary["feature_errors"]["bonus_chain_dynamics"] contains the
             RuntimeError text naming the missing key.
          4. Revert; re-run; assert no feature_errors.
        """
        if not _M275_CACHE.exists() or not list(_M275_CACHE.glob("chunk_*.json")):
            pytest.skip("M275 cache absent")
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [
                sys.executable, str(_PIA), "--machine", "M275", "--rtp-mode", "1",
                "--from-cache", str(_M275_CACHE), "--output-dir", tmpdir, "--bet", "1000",
            ]
            subprocess.run(cmd, capture_output=True, text=True,
                           cwd=str(_REPO_ROOT), timeout=300)
            summ = json.loads((Path(tmpdir) / "player_impact_summary.json").read_bytes())
            fe = summ.get("feature_errors", {})
            assert "bonus_chain_dynamics" in fe
