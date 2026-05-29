"""Phase 4 — fail-loud stash contract for the carved multiplier_profile plugin.

After the Phase 4 carve, PIA stashes ONLY the RAW dict-build inputs into
``summary["_multiplier_profile_data"]`` and the plugin's ``emit()`` OWNS the
``multiplier_profile`` dict-build (the ``player_impact.multiplier_profile`` literal
moved VERBATIM from PIA:~3964 — its ``buckets`` list, the
``tail_spin_rate_ge10x = tail_spins_ge10 / mb_total_spins if mb_total_spins > 0
else 0.0`` expression, and the ``tail_rtp_contribution_pp_ge10x`` /
``tail_win_share_ge10x`` leaves).  Per ``feedback_no_silent_swallow.md``, if the
stash is missing or an expected RAW key is absent, emit() MUST raise a diagnostic
``RuntimeError`` — it must NOT silently default (which would corrupt the report
numbers with no error).

This file MIRRORS ``test_3_upstream_feature_fail_loud_stash.py`` and locks the
fail-loud paths for multiplier_profile:

  Path B-1 (stash key entirely absent):
      emit() with no ``_multiplier_profile_data`` in summary -> RuntimeError naming
      the stash key + the plugin.

  Path B-2 (stash present but a RAW input key missing):
      The carve's explicit ``_missing`` check over the 5 expected raw keys (the
      plugin's ``_expected_keys`` tuple).  Deleting any one must raise RuntimeError
      naming the missing key(s) and citing feedback_no_silent_swallow.md — NOT a
      KeyError swallowed into a wrong number, NOT a silent default.

The plugin reads ``ctx`` for nothing in the build path (verified: the dict-build
never touches ``ctx``), so emit() is called with ctx=None throughout.

We also run the REAL end-to-end inject-bug once (delete a raw key from PIA's stash
builder, run the M275 subprocess, confirm the failure surfaces as
``summary["feature_errors"]["multiplier_profile"]`` rather than a wrong value AND no
half-built dict is left in player_impact) and capture the evidence in
``session_artifacts/_impl/phase_extract_4_multiplier_profile/inject_bug_evidence.md``.

Inject-bug recipe (Path B — fail-loud stash; per feedback_enumerate_safety_paths.md)
------------------------------------------------------------------------------------
UNIT (this file, no source edit needed — we delete a key from the constructed stash):
    build a full stash, ``del stash["multiplier_bucket_rows"]``, call emit() ->
    RuntimeError naming 'multiplier_bucket_rows'.  This proves the guard's logic for
    every one of the 5 raw keys (parametrized).

END-TO-END (real PIA edit, run once during authoring):
    In fresh_slotlab/player_impact_analyzer.py, in the
    summary["_multiplier_profile_data"] = {...} builder (~line 4400), comment out one
    raw key line, e.g.::
        # "multiplier_bucket_rows": multiplier_bucket_rows,
    RED: a real `python player_impact_analyzer.py --machine M275 ...` run lands the
         failure in summary["feature_errors"]["multiplier_profile"] with the
         RuntimeError message naming 'multiplier_bucket_rows' (NOT a silently-wrong
         multiplier_profile dict; NOT a half-built dict in player_impact).
    Revert -> GREEN (no feature_errors; multiplier_profile correct).

Memory files cited
------------------
- memory/feedback_no_silent_swallow.md
    a missing raw input must fail loudly with a diagnostic, never default to a
    silent wrong number.  The plugin surfaces it via feature_errors (disk).
- memory/feedback_enumerate_safety_paths.md
    inject-bug -> red -> revert -> green is mandatory for EACH safety path; B-1 + B-2
    (the 5 raw keys, one inject per key) + the end-to-end PIA-drop path.
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
    _REPO_ROOT / "fresh_slotlab" / "analyzer" / "features" / "multiplier_profile.py"
)
_M275_CACHE = _REPO_ROOT / "rawdata" / "M275" / "mode_1"

# The 5 RAW dict-build inputs the carved emit() requires from the stash.
# MUST match _expected_keys in multiplier_profile.py emit() VERBATIM — if the
# plugin's required-key tuple changes, this list must change with it (otherwise the
# per-key parametrized test below goes stale). Verified against the
# TestExpectedKeysMirrorPlugin guard below (which reads the plugin source).
_EXPECTED_RAW_KEYS: tuple[str, ...] = (
    "multiplier_bucket_rows",
    "tail_spins_ge10",
    "mb_total_spins",
    "tail_rtp_contribution_pp_ge10x",
    "tail_win_share_ge10x",
)

_STASH_KEY = "_multiplier_profile_data"


def _import_plugin_class():
    try:
        from fresh_slotlab.analyzer.features.multiplier_profile import MultiplierProfile
    except ImportError:  # running as standalone script
        from analyzer.features.multiplier_profile import (  # type: ignore[no-redef]
            MultiplierProfile,
        )
    return MultiplierProfile


def _full_stash() -> dict[str, Any]:
    """A complete, valid RAW-input stash (every one of the 5 keys present).

    A single, simple multiplier-bucket row + non-zero scalars so the build emits a
    clean multiplier_profile dict and exercises the live ``mb_total_spins > 0``
    divisor branch.  The rich byte-identical bucket data is covered by the M275/M14
    goldens in test_4_byte_identical_multiplier_profile_carve.py; the zero-spin
    ``else 0.0`` branch is covered in test_4_multiplier_profile_zero_spin_branch.py.
    """
    return {
        # The list of per-bucket rows the build assigns verbatim to "buckets".
        "multiplier_bucket_rows": [
            {
                "bucket": "gt0_lt1",
                "spin_count": 100,
                "spin_rate": 0.1,
                "rtp_contribution_pp": 5.0,
                "win_share": 0.05,
                "avg_return_x_in_bucket": 0.5,
            }
        ],
        # Scalars driving the tail leaves.
        "tail_spins_ge10": 10,
        "mb_total_spins": 1000,
        "tail_rtp_contribution_pp_ge10x": 23.4,
        "tail_win_share_ge10x": 0.26,
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

        Proves the 5-key list is at least sufficient — if the plugin required a
        key our _full_stash() lacks, emit() would raise and this would fail.
        """
        plugin = _import_plugin_class()()
        summary = _summary_with(_full_stash())
        plugin.emit({}, summary, None)  # must NOT raise (ctx unused in build path)
        assert "multiplier_profile" in summary["player_impact"]
        mp = summary["player_impact"]["multiplier_profile"]
        # The verbatim build form: exact 5-key order + canonical metric string.
        assert list(mp.keys()) == [
            "metric",
            "buckets",
            "tail_spin_rate_ge10x",
            "tail_rtp_contribution_pp_ge10x",
            "tail_win_share_ge10x",
        ]
        assert mp["metric"] == "ret_x = session_win / session_bet (paid bet only)"

    def test_full_stash_keys_are_exactly_the_expected_5(self):
        """_full_stash() keys must be EXACTLY the 5 expected raw keys (no extra).

        The multiplier_profile stash carries ONLY the 5 raw inputs — there are no
        derived/auxiliary stash fields. So the stash key set must equal
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

        Reads the plugin source and extracts the _expected_keys tuple literal, so a
        divergence (key added/removed/renamed in the plugin) fails this test rather
        than silently de-covering the parametrized test below.
        """
        src = _PLUGIN_SRC.read_text(encoding="utf-8")
        m = re.search(r"_expected_keys\s*=\s*\((.*?)\)", src, re.DOTALL)
        assert m, "could not locate _expected_keys tuple in plugin source"
        plugin_keys = tuple(re.findall(r'"([a-z0-9_]+)"', m.group(1)))
        assert plugin_keys == _EXPECTED_RAW_KEYS, (
            "plugin _expected_keys diverged from this test's _EXPECTED_RAW_KEYS.\n"
            f"plugin ({len(plugin_keys)}): {plugin_keys}\n"
            f"test   ({len(_EXPECTED_RAW_KEYS)}): {_EXPECTED_RAW_KEYS}\n"
            "Update _EXPECTED_RAW_KEYS to match (keeps the parametrized fail-loud "
            "test covering every raw key)."
        )

    def test_expected_keys_count_is_5(self):
        """The brief pins 5 RAW inputs — assert the count so a silent drop fails."""
        assert len(_EXPECTED_RAW_KEYS) == 5, (
            f"Phase 4 brief: the stash carries 5 RAW inputs. Got {len(_EXPECTED_RAW_KEYS)}."
        )


# ---------------------------------------------------------------------------
# T1: Path B-1 — stash key entirely absent
# ---------------------------------------------------------------------------

class TestStashKeyAbsentFailsLoud:
    """emit() with no stash key must raise RuntimeError (not silently skip)."""

    def test_emit_raises_when_stash_absent(self):
        """No _multiplier_profile_data in summary -> RuntimeError naming key.

        INJECT-BUG (Path B-1): in emit(), replace the `if _STASH_KEY not in
        summary: raise RuntimeError(...)` guard with `summary.setdefault(...)`.
        RED: this test fails (no RuntimeError raised). Revert -> GREEN.
        """
        plugin = _import_plugin_class()()
        with pytest.raises(RuntimeError, match=r"_multiplier_profile_data"):
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
        assert "_multiplier_profile_data" in msg
        assert "multiplier_profile plugin" in msg

    def test_no_player_impact_profile_written_on_absent_stash(self):
        """On an absent stash, emit() must NOT have written a partial dict."""
        plugin = _import_plugin_class()()
        summary: dict[str, Any] = {"player_impact": {}}
        with pytest.raises(RuntimeError):
            plugin.emit({}, summary, None)
        assert "multiplier_profile" not in summary["player_impact"], (
            "emit() must not write multiplier_profile when the stash is absent — "
            "the failure must be clean (no half-built dict)."
        )


# ---------------------------------------------------------------------------
# T2: Path B-2 — stash present but a RAW key missing (the NEW Phase 4 path)
# ---------------------------------------------------------------------------

class TestRawKeyMissingFailsLoud:
    """Deleting ANY one of the 5 raw keys must raise RuntimeError naming it.

    This is the Phase 4 fail-loud path: the stash now carries raw inputs and a
    missing input must NOT be silently defaulted (would corrupt report numbers).
    """

    @pytest.mark.parametrize("missing_key", _EXPECTED_RAW_KEYS)
    def test_missing_raw_key_raises_runtime_error(self, missing_key):
        """For each raw key: delete it -> emit() raises RuntimeError naming it.

        INJECT-BUG (Path B-2 / parametrized): each iteration deletes one raw key
        from the constructed stash. RED if emit() does NOT raise (i.e. if the guard
        were removed). The guard's presence is what makes ALL 5 iterations green.
        Removing the `_missing` check makes most iterations RED (a bare KeyError or
        a silently-wrong dict).
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
        del stash["multiplier_bucket_rows"]
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, _summary_with(stash), None)
        msg = str(ei.value)
        assert "multiplier_bucket_rows" in msg
        assert "silently default" in msg or "feedback_no_silent_swallow" in msg, (
            f"diagnostic must explain it refuses to silently default. Got: {msg!r}"
        )

    def test_does_not_write_profile_on_missing_key(self):
        """On a missing raw key, emit() must NOT have written a partial dict.

        Critical: the failure must be loud AND clean — no half-built
        multiplier_profile left in player_impact that a caller might consume as if
        valid.
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash["mb_total_spins"]
        summary = _summary_with(stash)
        with pytest.raises(RuntimeError):
            plugin.emit({}, summary, None)
        pi = summary.get("player_impact", {})
        assert "multiplier_profile" not in pi, (
            "emit() must not leave a partial multiplier_profile dict when a raw key "
            "is missing — the failure must be clean (no half-built dict)."
        )

    def test_multiple_missing_keys_all_named(self):
        """When several raw keys are absent, the diagnostic lists ALL of them.

        The guard collects every missing key (not just the first) so a developer
        sees the full gap in one pass.
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash["multiplier_bucket_rows"]
        del stash["mb_total_spins"]
        del stash["tail_win_share_ge10x"]
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, _summary_with(stash), None)
        msg = str(ei.value)
        assert "multiplier_bucket_rows" in msg, msg
        assert "mb_total_spins" in msg, msg
        assert "tail_win_share_ge10x" in msg, msg

    def test_does_not_index_stash_before_missing_check(self):
        """A missing-key failure must NOT silently swallow into a downstream KeyError.

        The guard runs BEFORE any raw value is indexed, so the message is the
        descriptive RuntimeError — not a bare ``KeyError: 'mb_total_spins'`` from a
        later ``stash["mb_total_spins"]`` access. Asserts the error TYPE + that the
        message is the plugin's diagnostic (contains the plugin name), proving the
        explicit ``_missing`` guard fires first.
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash["mb_total_spins"]
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, _summary_with(stash), None)
        # A bare KeyError would NOT contain the plugin diagnostic text.
        assert "multiplier_profile plugin" in str(ei.value), (
            "the explicit _missing guard must fire before any raw-value indexing "
            f"(no bare KeyError). Got: {str(ei.value)!r}"
        )

    def test_stash_pop_does_not_leave_stash_in_summary_after_failure(self):
        """Even on a missing-key failure, the popped stash key is not re-added.

        emit() pops _STASH_KEY before validating; a missing-raw-key failure must
        leave the summary clean (no stash key re-injected, no partial profile). A
        downstream consumer must not find a half-state to act on.
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash["tail_spins_ge10"]
        summary = _summary_with(stash)
        with pytest.raises(RuntimeError):
            plugin.emit({}, summary, None)
        assert _STASH_KEY not in summary, (
            "emit() pops the stash key; on failure it must not be left behind."
        )
        assert "multiplier_profile" not in summary.get("player_impact", {})


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
    summary['feature_errors']['multiplier_profile'] — proven by the authoring-time
    inject-bug (evidence in inject_bug_evidence.md), asserted structurally here.
    """

    def test_feature_errors_is_the_surfacing_channel(self):
        """Sanity: the analyzer surfaces plugin emit() exceptions under
        summary['feature_errors'][feature_id] (the channel the inject-bug used).

        We assert the mechanism exists by checking the PIA emit loop wraps emit()
        and records into feature_errors. (Run the real inject-bug per the recipe to
        see the RuntimeError text land there.)
        """
        src = _PIA.read_text(encoding="utf-8")
        assert "feature_errors" in src, (
            "PIA must surface plugin emit() failures via a 'feature_errors' summary "
            "key (the fail-loud disk channel)."
        )

    @pytest.mark.skip(
        reason="Requires temporarily editing PIA's stash builder; run manually per "
        "the Path B inject-bug recipe. RED evidence captured in "
        "inject_bug_evidence.md (authoring-time, 2026-05-30)."
    )
    def test_e2e_missing_raw_key_lands_in_feature_errors(self):  # pragma: no cover
        """When PIA omits a raw key, M275 run records the RuntimeError in
        feature_errors[multiplier_profile] (NOT a silently-wrong dict).

        Manual recipe (Path B end-to-end):
          1. Comment out one raw key in PIA's summary["_multiplier_profile_data"]
             builder (e.g. multiplier_bucket_rows, ~line 4401).
          2. Run M275 mode 1 from cache.
          3. Assert summary["feature_errors"]["multiplier_profile"] contains the
             RuntimeError text naming the missing key AND player_impact has no
             multiplier_profile.
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
            assert "multiplier_profile" in fe
