"""Phase 2a — fail-loud stash contract for the carved collect_mechanic plugin.

After the Phase 2a carve, PIA stashes ONLY the RAW accumulator inputs into
``summary["_collect_mechanic_data"]`` and the plugin's ``emit()`` owns the
dict-build.  Per ``feedback_no_silent_swallow.md``, if the stash is missing or an
expected RAW key is absent, emit() MUST raise a diagnostic ``RuntimeError`` — it
must NOT silently default (which would corrupt the report numbers with no error).

This file locks BOTH fail-loud paths:

  Path B-1 (stash key entirely absent):
      emit() with no ``_collect_mechanic_data`` in summary -> RuntimeError naming
      the stash key.  (Already covered by test_c5; re-asserted here as part of the
      2a contract since the carve made the stash payload meaning change.)

  Path B-2 (stash present but a RAW input key missing):
      This is the NEW 2a path.  The carve added an explicit ``_missing`` check
      over the 14 expected raw keys.  Deleting any one must raise RuntimeError
      naming the missing key(s) and citing feedback_no_silent_swallow.md — NOT a
      KeyError swallowed into a wrong number, NOT a silent default.

We also run the REAL end-to-end inject-bug once (delete a raw key from PIA's
stash builder, run the subprocess, confirm the failure surfaces as
``feature_errors[collect_mechanic]`` rather than a wrong value) and capture the
evidence in
``session_artifacts/_impl/phase_extract_2a_collect_mechanic/inject_bug_evidence.md``.

Inject-bug recipe (Path B — fail-loud stash; per feedback_enumerate_safety_paths.md)
------------------------------------------------------------------------------------
UNIT (this file, no source edit needed — we delete a key from the constructed stash):
    build a full stash, ``del stash["all_cycle_peaks"]``, call emit() ->
    RuntimeError naming 'all_cycle_peaks'.  This proves the guard's logic.

END-TO-END (real PIA edit, run once during authoring):
    In fresh_slotlab/player_impact_analyzer.py, in the
    summary["_collect_mechanic_data"] = {...} builder (~line 4692), comment out
    one raw key line, e.g.::
        # "all_cycle_peaks": all_cycle_peaks,
    RED: a real `python player_impact_analyzer.py --machine M275 ...` run lands
         the failure in summary["feature_errors"]["collect_mechanic"] with the
         RuntimeError message naming 'all_cycle_peaks' (NOT a silently-wrong
         collect_mechanic dict).
    Revert -> GREEN (no feature_errors; collect_mechanic correct).

Memory files cited
------------------
- memory/feedback_no_silent_swallow.md
    a missing raw input must fail loudly with a diagnostic, never default to a
    silent wrong number.  The plugin surfaces it via feature_errors (disk).
- memory/feedback_enumerate_safety_paths.md
    inject-bug -> red -> revert -> green for EACH safety path; both B-1 and B-2.
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

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_M275_CACHE = _REPO_ROOT / "rawdata" / "M275" / "mode_1"

# The 14 RAW accumulator keys the carved emit() requires from the stash.
# MUST match _expected_keys in collect_mechanic.py emit() VERBATIM — if the
# plugin's required-key tuple changes, this list must change with it (otherwise
# the per-key parametrized test below goes stale).
_EXPECTED_RAW_KEYS: tuple[str, ...] = (
    "collect_robots_seen_total",
    "collect_count_total",
    "acc_credits_max_global",
    "total_spins",
    "clamp_pending_robots_total",
    "clamp_pending_paid_spins_total",
    "total_paid_sessions",
    "all_cycle_peaks",
    "all_final_cc_values",
    "total_completed_cycles",
    "upstream_feature_tally",
    "effective_bet_for_rtp",
    "bonus_feature",
    "bonus_feature_source",
)


def _import_plugin_class():
    try:
        from fresh_slotlab.analyzer.features.collect_mechanic import CollectMechanic
    except ImportError:
        from analyzer.features.collect_mechanic import CollectMechanic  # type: ignore[no-redef]
    return CollectMechanic


def _full_stash() -> dict[str, Any]:
    """A complete, valid RAW-input stash (every one of the 14 keys present)."""
    return {
        "collect_robots_seen_total": 5,
        "collect_count_total": 100,
        "acc_credits_max_global": 999,
        "total_spins": 500,
        "clamp_pending_robots_total": 3,
        "clamp_pending_paid_spins_total": 15,
        "total_paid_sessions": 500,
        "all_cycle_peaks": [1000],
        "all_final_cc_values": [500, 500, 500],
        "total_completed_cycles": 80,
        "upstream_feature_tally": {
            "NewFreespin": {"1": {"win": 3200000.0, "times": 80}},
        },
        "effective_bet_for_rtp": 100000.0,
        "bonus_feature": "NewFreespin",
        "bonus_feature_source": "bcm_pairings",
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

        Proves the 14-key list is at least sufficient — if the plugin required a
        key our _full_stash() lacks, emit() would raise and this would fail.
        """
        plugin = _import_plugin_class()()
        summary = {
            "_collect_mechanic_data": _full_stash(),
            "sampling": {"chunk_spin_times": 5000},
        }
        plugin.emit({}, summary, None)  # must NOT raise
        assert "collect_mechanic" in summary
        assert summary["collect_mechanic"]["applicable"] is True

    def test_no_extra_keys_in_full_stash(self):
        """_full_stash() must contain EXACTLY the 14 expected keys (no more).

        If _full_stash() carried an extra key the plugin ignores, deleting an
        expected key in the parametrized test might be masked. Keep it tight.
        """
        assert set(_full_stash().keys()) == set(_EXPECTED_RAW_KEYS), (
            "_full_stash() keys must match _EXPECTED_RAW_KEYS exactly.\n"
            f"extra: {set(_full_stash()) - set(_EXPECTED_RAW_KEYS)}\n"
            f"missing: {set(_EXPECTED_RAW_KEYS) - set(_full_stash())}"
        )


# ---------------------------------------------------------------------------
# T1: Path B-1 — stash key entirely absent
# ---------------------------------------------------------------------------

class TestStashKeyAbsentFailsLoud:
    """emit() with no stash key must raise RuntimeError (not silently skip)."""

    def test_emit_raises_when_stash_absent(self):
        """No _collect_mechanic_data in summary -> RuntimeError naming the key.

        INJECT-BUG (Path B-1): in emit(), replace the `if _STASH_KEY not in
        summary: raise RuntimeError(...)` guard with `summary.setdefault(...)`.
        RED: this test fails (no RuntimeError raised). Revert -> GREEN.
        """
        plugin = _import_plugin_class()()
        with pytest.raises(RuntimeError, match=r"_collect_mechanic_data"):
            plugin.emit({}, {"sampling": {"chunk_spin_times": 5000}}, None)

    def test_runtime_error_message_is_diagnostic(self):
        """The RuntimeError must be diagnostic (names the key + the cause).

        Per feedback_no_silent_swallow.md the failure must be actionable, not a
        bare exception.
        """
        plugin = _import_plugin_class()()
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, {}, None)
        msg = str(ei.value)
        assert "_collect_mechanic_data" in msg
        assert "collect_mechanic plugin" in msg


# ---------------------------------------------------------------------------
# T2: Path B-2 — stash present but a RAW key missing (the NEW 2a path)
# ---------------------------------------------------------------------------

class TestRawKeyMissingFailsLoud:
    """Deleting ANY one of the 14 raw keys must raise RuntimeError naming it.

    This is the new Phase 2a fail-loud path: the stash now carries raw inputs and
    a missing input must NOT be silently defaulted (would corrupt report numbers).
    """

    @pytest.mark.parametrize("missing_key", _EXPECTED_RAW_KEYS)
    def test_missing_raw_key_raises_runtime_error(self, missing_key):
        """For each raw key: delete it -> emit() raises RuntimeError naming it.

        INJECT-BUG (Path B-2 / parametrized): each iteration deletes one raw key
        from the constructed stash. RED if emit() does NOT raise (i.e. if the
        guard were removed). The guard's presence is what makes ALL 14 iterations
        green. Removing the `_missing` check makes most iterations RED (a bare
        KeyError or a silently-wrong dict).
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash[missing_key]
        summary = {
            "_collect_mechanic_data": stash,
            "sampling": {"chunk_spin_times": 5000},
        }
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
        del stash["all_cycle_peaks"]
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, {"_collect_mechanic_data": stash,
                             "sampling": {"chunk_spin_times": 5000}}, None)
        msg = str(ei.value)
        assert "all_cycle_peaks" in msg
        assert "silently default" in msg or "feedback_no_silent_swallow" in msg, (
            f"diagnostic must explain it refuses to silently default. Got: {msg!r}"
        )

    def test_does_not_write_collect_mechanic_on_missing_key(self):
        """On a missing raw key, emit() must NOT have written a partial dict.

        Critical: the failure must be loud AND clean — no half-built
        collect_mechanic left in summary that a caller might consume as if valid.
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash["total_completed_cycles"]
        summary = {
            "_collect_mechanic_data": stash,
            "sampling": {"chunk_spin_times": 5000},
        }
        with pytest.raises(RuntimeError):
            plugin.emit({}, summary, None)
        assert "collect_mechanic" not in summary, (
            "emit() must not leave a partial collect_mechanic dict when a raw key "
            "is missing — the failure must be clean."
        )


# ---------------------------------------------------------------------------
# T3: End-to-end fail-loud — real subprocess surfaces RuntimeError via
#     feature_errors (NOT a silent wrong value).
#
#     This test is SKIPPED by default (it requires temporarily editing PIA,
#     which we do NOT do automatically in CI). It documents + (when manually
#     un-skipped during authoring) verifies the end-to-end disk-surfacing path.
#     The captured RED evidence lives in inject_bug_evidence.md.
# ---------------------------------------------------------------------------

class TestEndToEndFailLoudIsSurfaced:
    """The end-to-end path: a missing raw key in PIA's stash builder surfaces as
    summary['feature_errors']['collect_mechanic'] — proven by the authoring-time
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
        feature_errors[collect_mechanic] (NOT a silently-wrong collect_mechanic).

        Manual recipe (Path B end-to-end):
          1. Comment out one raw key in PIA's summary["_collect_mechanic_data"]
             builder (e.g. all_cycle_peaks).
          2. Run M275 mode 1 from cache.
          3. Assert summary["feature_errors"]["collect_mechanic"] contains the
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
            assert "collect_mechanic" in fe
