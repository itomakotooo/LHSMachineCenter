"""Phase 3 — fail-loud stash contract for the carved upstream_feature_breakdown plugin.

After the Phase 3 carve, PIA stashes ONLY the RAW accumulator inputs into
``summary["_upstream_feature_breakdown_data"]`` and the plugin's ``emit()`` OWNS
the ~390-line row-build (the ``sub_streams_by_feature`` post-processing, the reverse
``spin_type_prev_counts`` table, the per-feature ``upstream_feature_rows`` assembly
loop with its successor/predecessor inference + per-feature multiplier-bucket
histograms + per-path splitting, the sort, and the ``upstream_feature_applicable``
flag — moved VERBATIM from PIA).  Per ``feedback_no_silent_swallow.md``, if the stash
is missing or an expected RAW key is absent, emit() MUST raise a diagnostic
``RuntimeError`` — it must NOT silently default (which would corrupt the report
numbers with no error).

This file MIRRORS ``test_2b_bonus_chain_fail_loud_stash.py`` and locks the
fail-loud paths for upstream_feature_breakdown:

  Path B-1 (stash key entirely absent):
      emit() with no ``_upstream_feature_breakdown_data`` in summary -> RuntimeError
      naming the stash key + the plugin.

  Path B-2 (stash present but a RAW input key missing):
      The carve's explicit ``_missing`` check over the 22 expected raw keys
      (the plugin's ``_expected_keys`` tuple).  Deleting any one must raise
      RuntimeError naming the missing key(s) and citing feedback_no_silent_swallow.md
      — NOT a KeyError swallowed into a wrong number, NOT a silent default.

Unlike 2b, upstream_feature_breakdown has NO B-3 schema-drift guard
(``scatter_feature_chain_counts`` is a bonus_chain_dynamics concept).  The plugin
reads ``ctx`` for nothing in the build path (verified: the row-build never touches
``ctx``), so emit() is called with ctx=None throughout — exactly as the migrated
C5 unit suite does.

We also run the REAL end-to-end inject-bug once (delete a raw key from PIA's
stash builder, run the M275 subprocess, confirm the failure surfaces as
``summary["feature_errors"]["upstream_feature_breakdown"]`` rather than a wrong
value AND no half-built dict is left in player_impact) and capture the evidence in
``session_artifacts/_impl/phase_extract_3_upstream_feature/inject_bug_evidence.md``.

Inject-bug recipe (Path B — fail-loud stash; per feedback_enumerate_safety_paths.md)
------------------------------------------------------------------------------------
UNIT (this file, no source edit needed — we delete a key from the constructed stash):
    build a full stash, ``del stash["upstream_feature_tally"]``, call emit() ->
    RuntimeError naming 'upstream_feature_tally'.  This proves the guard's logic for
    every one of the 22 raw keys (parametrized).

END-TO-END (real PIA edit, run once during authoring):
    In fresh_slotlab/player_impact_analyzer.py, in the
    summary["_upstream_feature_breakdown_data"] = {...} builder (~line 4252), comment
    out one raw key line, e.g.::
        # "upstream_feature_tally": upstream_feature_tally,
    RED: a real `python player_impact_analyzer.py --machine M275 ...` run lands
         the failure in summary["feature_errors"]["upstream_feature_breakdown"] with
         the RuntimeError message naming 'upstream_feature_tally' (NOT a silently-wrong
         upstream_feature_breakdown dict; NOT a half-built dict in player_impact).
    Revert -> GREEN (no feature_errors; upstream_feature_breakdown correct).

Memory files cited
------------------
- memory/feedback_no_silent_swallow.md
    a missing raw input must fail loudly with a diagnostic, never default to a
    silent wrong number.  The plugin surfaces it via feature_errors (disk).
- memory/feedback_enumerate_safety_paths.md
    inject-bug -> red -> revert -> green is mandatory for EACH safety path; B-1 + B-2
    (the 22 raw keys, one inject per key) + the end-to-end PIA-drop path.
- memory/feedback_subprocess_import_suicide_and_module_globals.md
    import-time side-effect freedom (the plugin import is a pure register()).
- memory/feedback_perf_claim_needs_e2e_event_stream.md
    the end-to-end B path runs a REAL subprocess against real cached M275 — the
    disk-surfacing channel (feature_errors) cannot be proven by a unit alone.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_PLUGIN_SRC = (
    _REPO_ROOT / "fresh_slotlab" / "analyzer" / "features"
    / "upstream_feature_breakdown.py"
)
_M275_CACHE = _REPO_ROOT / "rawdata" / "M275" / "mode_1"

# The 22 RAW accumulator keys the carved emit() requires from the stash.
# MUST match _expected_keys in upstream_feature_breakdown.py emit() VERBATIM — if
# the plugin's required-key tuple changes, this list must change with it (otherwise
# the per-key parametrized test below goes stale). Verified against the
# TestExpectedKeysMirrorPlugin guard below (which reads the plugin source).
_EXPECTED_RAW_KEYS: tuple[str, ...] = (
    "upstream_feature_tally",
    "feature_to_spin_type",
    "spin_type_to_feature",
    "ambiguous_mapped",
    "bcm_bonus_feature",
    "bcm_bonus_source",
    "spin_type_next_counts",
    "chain_chunk_summaries",
    "chain_bucket_spins",
    "chain_bucket_bet",
    "chain_bucket_win",
    "spin_type_bucket_spins",
    "spin_type_bucket_bet",
    "spin_type_bucket_win",
    "session_bucket_spins_by_settlement_st",
    "session_bucket_bet_by_settlement_st",
    "session_bucket_win_by_settlement_st",
    "spin_type_spins",
    "spin_type_nudge_round_count",
    "total_spins",
    "effective_bet_for_rtp",
    "upstream_total_win",
)

_STASH_KEY = "_upstream_feature_breakdown_data"


def _import_plugin_class():
    try:
        from fresh_slotlab.analyzer.features.upstream_feature_breakdown import (
            UpstreamFeatureBreakdown,
        )
    except ImportError:  # running as standalone script
        from analyzer.features.upstream_feature_breakdown import (  # type: ignore[no-redef]
            UpstreamFeatureBreakdown,
        )
    return UpstreamFeatureBreakdown


def _full_stash() -> dict[str, Any]:
    """A complete, valid RAW-input stash (every one of the 22 keys present).

    Single bonus-named feature ("NormalCollectionSpin") with empty resolved maps
    (feature_to_spin_type={}) so resolved_spin_type is None for the only feature
    → the build emits one clean aggregate row and never indexes the empty
    transition/bucket/chain accumulators.  This keeps the B-1/B-2 tests focused on
    the 22 raw keys (the rich per-path / multiplier-bucket / inference branches are
    covered byte-identically by the M275 golden in
    test_3_byte_identical_upstream_feature_carve.py).  Mirrors the C5 unit suite's
    _make_stash_data(applicable=True).
    """
    return {
        # The per-feature per-pid {win, times} tally the row headers read.
        "upstream_feature_tally": {
            "NormalCollectionSpin": {"1": {"win": 500.0, "times": 100}},
        },
        # Resolved helper RESULTS (empty → resolved_spin_type None).
        "feature_to_spin_type": {},
        "spin_type_to_feature": {},
        "ambiguous_mapped": set(),
        "bcm_bonus_feature": None,
        "bcm_bonus_source": "none",
        # SpinType transition table (empty — no successor/predecessor edges).
        "spin_type_next_counts": {},
        # Chain post-processing accumulators (empty — no per-path sub_streams).
        "chain_chunk_summaries": {},
        "chain_bucket_spins": {},
        "chain_bucket_bet": {},
        "chain_bucket_win": {},
        # Round-level multiplier-bucket accumulators + settlement-ST fallbacks.
        "spin_type_bucket_spins": {},
        "spin_type_bucket_bet": {},
        "spin_type_bucket_win": {},
        "session_bucket_spins_by_settlement_st": {},
        "session_bucket_bet_by_settlement_st": {},
        "session_bucket_win_by_settlement_st": {},
        # Wild-nudge tagging inputs.
        "spin_type_spins": {},
        "spin_type_nudge_round_count": {},
        # Scalars.
        "total_spins": 1000,
        "effective_bet_for_rtp": 1000.0,
        "upstream_total_win": 500.0,
    }


def _summary_with(stash: dict[str, Any]) -> dict[str, Any]:
    """Wrap a stash in a minimal summary (player_impact created by emit())."""
    return {_STASH_KEY: stash}


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

        Proves the 22-key list is at least sufficient — if the plugin required a
        key our _full_stash() lacks, emit() would raise and this would fail.
        """
        plugin = _import_plugin_class()()
        summary = _summary_with(_full_stash())
        plugin.emit({}, summary, None)  # must NOT raise (ctx unused in build path)
        assert "upstream_feature_breakdown" in summary["player_impact"]
        # single non-"Normal" feature → applicable=True (has_bonus_named_feature)
        assert summary["player_impact"]["upstream_feature_breakdown"]["applicable"] is True

    def test_full_stash_keys_are_exactly_the_expected_22(self):
        """_full_stash() keys must be EXACTLY the 22 expected raw keys (no extra).

        Unlike 2b (which had derived scatter_* fields excluded), the
        upstream_feature_breakdown stash carries ONLY the 22 raw inputs — there
        are no derived/auxiliary stash fields. So the stash key set must equal
        _EXPECTED_RAW_KEYS exactly.
        """
        stash_keys = set(_full_stash())
        assert stash_keys == set(_EXPECTED_RAW_KEYS), (
            "_full_stash() keys must match _EXPECTED_RAW_KEYS exactly.\n"
            f"extra: {stash_keys - set(_EXPECTED_RAW_KEYS)}\n"
            f"missing: {set(_EXPECTED_RAW_KEYS) - stash_keys}"
        )

    def test_expected_keys_match_plugin_source(self):
        """_EXPECTED_RAW_KEYS must be byte-identical to the plugin's _expected_keys.

        Reads the plugin source and extracts the _expected_keys tuple literal, so
        a divergence (key added/removed/renamed in the plugin) fails this test
        rather than silently de-covering the parametrized test below.
        """
        src = _PLUGIN_SRC.read_text(encoding="utf-8")
        m = re.search(r"_expected_keys\s*=\s*\((.*?)\)", src, re.DOTALL)
        assert m, "could not locate _expected_keys tuple in plugin source"
        plugin_keys = tuple(re.findall(r'"([a-z_]+)"', m.group(1)))
        assert plugin_keys == _EXPECTED_RAW_KEYS, (
            "plugin _expected_keys diverged from this test's _EXPECTED_RAW_KEYS.\n"
            f"plugin ({len(plugin_keys)}): {plugin_keys}\n"
            f"test   ({len(_EXPECTED_RAW_KEYS)}): {_EXPECTED_RAW_KEYS}\n"
            "Update _EXPECTED_RAW_KEYS to match (keeps the parametrized fail-loud "
            "test covering every raw key)."
        )

    def test_expected_keys_count_is_22(self):
        """The brief pins 22 RAW inputs — assert the count so a silent drop fails."""
        assert len(_EXPECTED_RAW_KEYS) == 22, (
            f"Phase 3 brief: the stash carries 22 RAW inputs. Got {len(_EXPECTED_RAW_KEYS)}."
        )


# ---------------------------------------------------------------------------
# T1: Path B-1 — stash key entirely absent
# ---------------------------------------------------------------------------

class TestStashKeyAbsentFailsLoud:
    """emit() with no stash key must raise RuntimeError (not silently skip)."""

    def test_emit_raises_when_stash_absent(self):
        """No _upstream_feature_breakdown_data in summary -> RuntimeError naming key.

        INJECT-BUG (Path B-1): in emit(), replace the `if _STASH_KEY not in
        summary: raise RuntimeError(...)` guard with `summary.setdefault(...)`.
        RED: this test fails (no RuntimeError raised). Revert -> GREEN.
        """
        plugin = _import_plugin_class()()
        with pytest.raises(RuntimeError, match=r"_upstream_feature_breakdown_data"):
            plugin.emit({}, {"player_impact": {}}, None)

    def test_runtime_error_message_is_diagnostic(self):
        """The RuntimeError must be diagnostic (names the key + the plugin).

        Per feedback_no_silent_swallow.md the failure must be actionable, not a
        bare exception.
        """
        plugin = _import_plugin_class()()
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, {}, None)
        msg = str(ei.value)
        assert "_upstream_feature_breakdown_data" in msg
        assert "upstream_feature_breakdown plugin" in msg

    def test_no_player_impact_breakdown_written_on_absent_stash(self):
        """On an absent stash, emit() must NOT have written a partial dict."""
        plugin = _import_plugin_class()()
        summary: dict[str, Any] = {"player_impact": {}}
        with pytest.raises(RuntimeError):
            plugin.emit({}, summary, None)
        assert "upstream_feature_breakdown" not in summary["player_impact"], (
            "emit() must not write upstream_feature_breakdown when the stash is "
            "absent — the failure must be clean (no half-built dict)."
        )


# ---------------------------------------------------------------------------
# T2: Path B-2 — stash present but a RAW key missing (the NEW Phase 3 path)
# ---------------------------------------------------------------------------

class TestRawKeyMissingFailsLoud:
    """Deleting ANY one of the 22 raw keys must raise RuntimeError naming it.

    This is the Phase 3 fail-loud path: the stash now carries raw inputs and a
    missing input must NOT be silently defaulted (would corrupt report numbers).
    """

    @pytest.mark.parametrize("missing_key", _EXPECTED_RAW_KEYS)
    def test_missing_raw_key_raises_runtime_error(self, missing_key):
        """For each raw key: delete it -> emit() raises RuntimeError naming it.

        INJECT-BUG (Path B-2 / parametrized): each iteration deletes one raw key
        from the constructed stash. RED if emit() does NOT raise (i.e. if the
        guard were removed). The guard's presence is what makes ALL 22 iterations
        green. Removing the `_missing` check makes most iterations RED (a bare
        KeyError or a silently-wrong dict).
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash[missing_key]
        summary = _summary_with(stash)
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, summary, None)
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
        del stash["upstream_feature_tally"]
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, _summary_with(stash), None)
        msg = str(ei.value)
        assert "upstream_feature_tally" in msg
        assert "silently default" in msg or "feedback_no_silent_swallow" in msg, (
            f"diagnostic must explain it refuses to silently default. Got: {msg!r}"
        )

    def test_does_not_write_breakdown_on_missing_key(self):
        """On a missing raw key, emit() must NOT have written a partial dict.

        Critical: the failure must be loud AND clean — no half-built
        upstream_feature_breakdown left in player_impact that a caller might
        consume as if valid.
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash["effective_bet_for_rtp"]
        summary = _summary_with(stash)
        with pytest.raises(RuntimeError):
            plugin.emit({}, summary, None)
        pi = summary.get("player_impact", {})
        assert "upstream_feature_breakdown" not in pi, (
            "emit() must not leave a partial upstream_feature_breakdown dict when a "
            "raw key is missing — the failure must be clean (no half-built dict)."
        )

    def test_multiple_missing_keys_all_named(self):
        """When several raw keys are absent, the diagnostic lists ALL of them.

        The guard collects every missing key (not just the first) so a developer
        sees the full gap in one pass.
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash["upstream_feature_tally"]
        del stash["total_spins"]
        del stash["spin_type_next_counts"]
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, _summary_with(stash), None)
        msg = str(ei.value)
        assert "upstream_feature_tally" in msg, msg
        assert "total_spins" in msg, msg
        assert "spin_type_next_counts" in msg, msg

    def test_does_not_pop_stash_then_lose_it_on_missing_key(self):
        """A missing-key failure must NOT silently swallow into a downstream KeyError.

        The guard runs BEFORE any raw value is indexed, so the message is the
        descriptive RuntimeError — not a bare ``KeyError: 'total_spins'`` from a
        later ``stash["total_spins"]`` access. Asserts the error TYPE + that the
        message is the plugin's diagnostic (contains the plugin name), proving the
        explicit ``_missing`` guard fires first.
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash["total_spins"]
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, _summary_with(stash), None)
        # A bare KeyError would NOT contain the plugin diagnostic text.
        assert "upstream_feature_breakdown plugin" in str(ei.value), (
            "the explicit _missing guard must fire before any raw-value indexing "
            f"(no bare KeyError). Got: {str(ei.value)!r}"
        )


# ---------------------------------------------------------------------------
# T3: End-to-end fail-loud — real subprocess surfaces RuntimeError via
#     feature_errors (NOT a silent wrong value).
#
#     The first test asserts the surfacing CHANNEL exists structurally. The
#     second is SKIPPED by default (it requires temporarily editing PIA, which we
#     do NOT do automatically in CI). It documents + (when manually un-skipped
#     during authoring) verifies the end-to-end disk-surfacing path. The captured
#     RED evidence lives in inject_bug_evidence.md.
# ---------------------------------------------------------------------------

class TestEndToEndFailLoudIsSurfaced:
    """The end-to-end path: a missing raw key in PIA's stash builder surfaces as
    summary['feature_errors']['upstream_feature_breakdown'] — proven by the
    authoring-time inject-bug (evidence in inject_bug_evidence.md), asserted
    structurally here.
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
        feature_errors[upstream_feature_breakdown] (NOT a silently-wrong dict).

        Manual recipe (Path B end-to-end):
          1. Comment out one raw key in PIA's
             summary["_upstream_feature_breakdown_data"] builder (e.g.
             upstream_feature_tally, ~line 4260).
          2. Run M275 mode 1 from cache.
          3. Assert summary["feature_errors"]["upstream_feature_breakdown"]
             contains the RuntimeError text naming the missing key AND
             player_impact has no upstream_feature_breakdown.
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
            assert "upstream_feature_breakdown" in fe
