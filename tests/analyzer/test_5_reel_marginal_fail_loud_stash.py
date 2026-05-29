"""Phase 5 — fail-loud stash contract for the carved reel_marginal_by_spin_type plugin.

After the Phase 5 carve, PIA stashes ONLY the RAW dict-build input into
``summary["_reel_marginal_by_spin_type_data"]`` (the single accumulator
``symbol_counts_by_col_by_spin_type_total``) and the plugin's ``emit()`` OWNS the
``reel_marginal_by_spin_type`` dict-build (the
``player_impact.reel_marginal_by_spin_type`` literal moved VERBATIM from pre-carve
PIA:~3432 — the ``for st_int, label in sorted(_st_label.items())`` loop, the
``col_total == 0`` skip, the ``int(cnt)``, and the
``prob_pct = (cnt / col_total) * 100.0`` leaf — with ``_st_label`` RE-DERIVED from
the already-emitted ``spin_type_breakdown``).  Per ``feedback_no_silent_swallow.md``,
if the stash or an expected RAW key is absent, the failure MUST be loud — never a
silent default that would corrupt the report numbers.

TWO surfacing layers (this is the Phase 5 contract; mirrors multiplier_profile
Phase 4 / bonus_chain_dynamics R2 Phase 2 C-4)
-----------------------------------------------------------------------------------
1. STASH KEY ENTIRELY ABSENT — the plugin declares
   ``DECLARED_DEPS = ("_reel_marginal_by_spin_type_data",)``.  The PIA emit-loop
   Region 2 pre-flight (player_impact_analyzer.py ~4740) fires
   ``PluginDeclaredDepMissingError`` and writes ``summary["analyzer_init_error"]``
   (region=2) + ``SystemExit(1)`` BEFORE emit() is ever called.  So end-to-end an
   absent stash surfaces as ``analyzer_init_error``, NOT feature_errors.  The
   plugin ALSO has a defensive ``if _STASH_KEY not in summary: raise RuntimeError``
   guard in emit() (reachable only on a direct emit() call / if Region 2 were
   bypassed); the unit tests below exercise that guard directly.

2. STASH PRESENT BUT THE RAW KEY MISSING — the Region 2 check verifies only that
   the stash KEY exists, not its CONTENTS.  A present-but-incomplete stash passes
   Region 2 and reaches emit(), where the explicit ``_missing`` check over
   ``_expected_keys`` raises ``RuntimeError`` → caught by the PIA emit-error
   handler → ``summary["feature_errors"]["reel_marginal_by_spin_type"]`` on disk.
   This is the path the real PIA-edit e2e exercises (drop the raw key, NOT the
   stash key, per the brief).

This file MIRRORS ``test_4_multiplier_profile_fail_loud_stash.py`` and locks both
paths for reel_marginal_by_spin_type.

The plugin reads ``ctx`` for nothing in the build path (verified: the dict-build
never touches ``ctx``; it re-derives _st_label from summary, reads the stash from
summary), so emit() is called with ctx=None throughout.

We also run the REAL end-to-end inject-bug once (delete the raw key from PIA's stash
builder, run the M275 subprocess, confirm the failure surfaces as
``summary["feature_errors"]["reel_marginal_by_spin_type"]`` rather than a wrong value
AND no half-built dict is left in player_impact) and capture the evidence in
``session_artifacts/_impl/phase_extract_5_reel_marginal/inject_bug_evidence.md``.

Inject-bug recipe (Path B — fail-loud stash; per feedback_enumerate_safety_paths.md)
------------------------------------------------------------------------------------
UNIT (this file, no source edit needed — we delete a key from the constructed stash):
    build a full stash, ``del stash["symbol_counts_by_col_by_spin_type_total"]``,
    call emit() -> RuntimeError naming 'symbol_counts_by_col_by_spin_type_total'.
    This proves the guard's logic for the (single) raw key.

END-TO-END (real PIA edit, run once during authoring):
    In fresh_slotlab/player_impact_analyzer.py, in the
    summary["_reel_marginal_by_spin_type_data"] = {...} builder (~line 4433),
    comment out the raw key line::
        # "symbol_counts_by_col_by_spin_type_total": symbol_counts_by_col_by_spin_type_total,
    RED: a real `python player_impact_analyzer.py --machine M275 ...` run lands the
         failure in summary["feature_errors"]["reel_marginal_by_spin_type"] with the
         RuntimeError message naming 'symbol_counts_by_col_by_spin_type_total' (NOT a
         silently-wrong dict; NOT a half-built dict in player_impact).
    Revert -> GREEN (no feature_errors; reel_marginal_by_spin_type correct).
    (Verified 2026-05-30; evidence in inject_bug_evidence.md §B.)

Memory files cited
------------------
- memory/feedback_no_silent_swallow.md
    a missing raw input must fail loudly with a diagnostic, never default to a
    silent wrong number.  The plugin surfaces it via feature_errors (disk); the
    absent-stash-key case surfaces via analyzer_init_error (region 2).
- memory/feedback_enumerate_safety_paths.md
    inject-bug -> red -> revert -> green is mandatory for EACH safety path: the
    stash-absent emit() guard, the raw-key-missing emit() guard, AND the
    end-to-end PIA-drop path.
- memory/feedback_subprocess_import_suicide_and_module_globals.md
    import-time side-effect freedom (the plugin import is a pure register()).
- memory/feedback_perf_claim_needs_e2e_event_stream.md
    the end-to-end B path runs a REAL subprocess against real cached M275 — the
    disk-surfacing channel (feature_errors / analyzer_init_error) cannot be proven
    by a unit alone.
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
    / "reel_marginal_by_spin_type.py"
)
_M275_CACHE = _REPO_ROOT / "rawdata" / "M275" / "mode_1"

# The RAW dict-build input the carved emit() requires from the stash.
# MUST match _expected_keys in reel_marginal_by_spin_type.py emit() VERBATIM — if
# the plugin's required-key tuple changes, this list must change with it (otherwise
# the per-key parametrized test below goes stale). Verified against the
# TestExpectedKeysMirrorPlugin guard below (which reads the plugin source).
_EXPECTED_RAW_KEYS: tuple[str, ...] = (
    "symbol_counts_by_col_by_spin_type_total",
)

_STASH_KEY = "_reel_marginal_by_spin_type_data"


def _import_plugin_class():
    try:
        from fresh_slotlab.analyzer.features.reel_marginal_by_spin_type import (
            ReelMarginalBySpinType,
        )
    except ImportError:  # running as standalone script
        from analyzer.features.reel_marginal_by_spin_type import (  # type: ignore[no-redef]
            ReelMarginalBySpinType,
        )
    return ReelMarginalBySpinType


def _full_stash() -> dict[str, Any]:
    """A complete, valid RAW-input stash (the one raw key present).

    A single ST (int) with one column of two symbols so the build emits a clean
    reel_marginal_by_spin_type dict and exercises the live (col_total > 0,
    count-descending sort) path.  The rich byte-identical data is covered by the
    M275/M14 goldens in test_5_byte_identical_reel_marginal_carve.py; the empty
    branches (empty col_rows / empty spin_type_breakdown / col_total==0 skip) are
    covered in test_5_reel_marginal_coverage_gaps.py.

    Note the accumulator is keyed by spin_type INT (st_int) at the top level — the
    plugin does ``symbol_counts_by_col_by_spin_type_total.get(st_int)`` — and the
    inner keys are reel-column INTs.  The _st_label map is re-derived from
    spin_type_breakdown (we pair a matching breakdown row in _summary_with()).
    """
    return {
        "symbol_counts_by_col_by_spin_type_total": {
            1: {  # st_int = 1 (matches the spin_type_breakdown row below)
                0: {"WILD": 30, "A": 70},  # col 0
            }
        },
    }


def _summary_with(stash: dict[str, Any], *, with_breakdown: bool = True) -> dict[str, Any]:
    """Wrap a stash in a minimal summary.

    By default include a spin_type_breakdown row for st=1 so the re-derived
    _st_label maps 1 -> "ST1_paid" and the build produces a populated dict. Set
    with_breakdown=False for the fail-loud tests where the build must NOT be
    reached (so the breakdown is irrelevant).
    """
    summary: dict[str, Any] = {_STASH_KEY: stash}
    if with_breakdown:
        summary["player_impact"] = {
            "spin_type_breakdown": [
                {"spin_type": 1, "behavior_name": "paid"},
            ]
        }
    return summary


# ---------------------------------------------------------------------------
# T0: the local key-list mirrors the plugin's actual required set + DECLARED_DEPS
# ---------------------------------------------------------------------------

class TestExpectedKeysMirrorPlugin:
    """Guard: the local mirrors must equal the plugin's actual declarations.

    If a refactor changes the plugin's _expected_keys / DECLARED_DEPS / _STASH_KEY
    but not these mirrors, the per-key fail-loud + e2e tests would silently stop
    covering the new contract (stale-green). These fail loudly the moment they
    diverge.
    """

    def test_full_stash_satisfies_plugin_emit(self):
        """A _full_stash() must drive emit() to success (sanity: the happy path).

        Proves the raw-key list is at least sufficient — if the plugin required a
        key our _full_stash() lacks, emit() would raise and this would fail. Also
        confirms the re-derived _st_label + verbatim build produce the expected
        nested shape.
        """
        plugin = _import_plugin_class()()
        summary = _summary_with(_full_stash())
        plugin.emit({}, summary, None)  # must NOT raise (ctx unused in build path)
        rm = summary["player_impact"]["reel_marginal_by_spin_type"]
        # st=1 -> "ST1_paid"; col 0 with two symbols, count-descending.
        assert list(rm.keys()) == ["ST1_paid"], rm
        assert list(rm["ST1_paid"].keys()) == ["0"], rm["ST1_paid"]
        rows = rm["ST1_paid"]["0"]
        assert [r["symbol"] for r in rows] == ["A", "WILD"], rows  # 70 > 30
        assert rows[0]["count"] == 70 and rows[1]["count"] == 30
        assert rows[0]["prob_pct"] == (70 / 100) * 100.0
        assert rows[1]["prob_pct"] == (30 / 100) * 100.0

    def test_full_stash_keys_are_exactly_the_expected_raw_keys(self):
        """_full_stash() keys must be EXACTLY the expected raw keys (no extra).

        The reel_marginal stash carries ONLY the single raw accumulator — there are
        no derived/auxiliary stash fields. So the stash key set must equal
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

    def test_expected_keys_count_is_1(self):
        """The brief pins ONE RAW input — assert the count so a silent add/drop fails."""
        assert len(_EXPECTED_RAW_KEYS) == 1, (
            f"Phase 5 brief: the stash carries 1 RAW input "
            f"(symbol_counts_by_col_by_spin_type_total). Got {len(_EXPECTED_RAW_KEYS)}."
        )

    def test_declared_deps_is_the_stash_key(self):
        """The plugin's DECLARED_DEPS must declare exactly the stash key.

        This is what wires the Region 2 pre-flight (the e2e absent-stash path lands
        in analyzer_init_error, not feature_errors). If DECLARED_DEPS drifted away
        from the stash key, the absent-stash failure mode would change silently.
        """
        plugin = _import_plugin_class()()
        assert plugin.DECLARED_DEPS == (_STASH_KEY,), (
            f"DECLARED_DEPS must be ({_STASH_KEY!r},) so the Region 2 pre-flight "
            f"fires on an absent stash. Got {plugin.DECLARED_DEPS!r}"
        )

    def test_stash_key_constant_matches_plugin_source(self):
        """_STASH_KEY here must match the plugin's _STASH_KEY module constant."""
        src = _PLUGIN_SRC.read_text(encoding="utf-8")
        m = re.search(r'_STASH_KEY\s*=\s*"([^"]+)"', src)
        assert m, "could not locate _STASH_KEY in plugin source"
        assert m.group(1) == _STASH_KEY, (
            f"plugin _STASH_KEY {m.group(1)!r} != test _STASH_KEY {_STASH_KEY!r}"
        )

    def test_rtp_contribution_is_false(self):
        """reel_marginal_by_spin_type is display-only — RTP_CONTRIBUTION must be False.

        Pins the brief §3.5 invariant (RTP untouched). A flip to True would put this
        feature into the RTP-attribution path and break the aggregator parity
        invariant; the byte-identity ``rtp`` diff would also catch it, but this pins
        the declaration directly.
        """
        plugin = _import_plugin_class()()
        assert plugin.RTP_CONTRIBUTION is False


# ---------------------------------------------------------------------------
# T1: Path B-1 — stash key entirely absent (emit() defensive guard)
# ---------------------------------------------------------------------------

class TestStashKeyAbsentFailsLoud:
    """emit() with no stash key must raise RuntimeError (not silently skip).

    NOTE: end-to-end, the PIA Region 2 pre-flight catches an absent stash FIRST
    (PluginDeclaredDepMissingError -> analyzer_init_error -> SystemExit), so emit()
    is never reached in production. This defensive guard is the second line and is
    exercised by calling emit() directly (the unit path).
    """

    def test_emit_raises_when_stash_absent(self):
        """No _reel_marginal_by_spin_type_data in summary -> RuntimeError naming key.

        INJECT-BUG (Path B-1): in emit(), replace the `if _STASH_KEY not in
        summary: raise RuntimeError(...)` guard with `summary.setdefault(...)`.
        RED: this test fails (no RuntimeError raised). Revert -> GREEN.
        """
        plugin = _import_plugin_class()()
        with pytest.raises(RuntimeError, match=r"_reel_marginal_by_spin_type_data"):
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
        assert "_reel_marginal_by_spin_type_data" in msg
        assert "reel_marginal_by_spin_type plugin" in msg

    def test_no_player_impact_profile_written_on_absent_stash(self):
        """On an absent stash, emit() must NOT have written a partial dict."""
        plugin = _import_plugin_class()()
        summary: dict[str, Any] = {"player_impact": {}}
        with pytest.raises(RuntimeError):
            plugin.emit({}, summary, None)
        assert "reel_marginal_by_spin_type" not in summary["player_impact"], (
            "emit() must not write reel_marginal_by_spin_type when the stash is "
            "absent — the failure must be clean (no half-built dict)."
        )


# ---------------------------------------------------------------------------
# T2: Path B-2 — stash present but the RAW key missing (the NEW Phase 5 path)
# ---------------------------------------------------------------------------

class TestRawKeyMissingFailsLoud:
    """Deleting the raw key must raise RuntimeError naming it.

    This is the Phase 5 fail-loud path: the stash now carries the raw input and a
    missing input must NOT be silently defaulted (would corrupt report numbers).
    The Region 2 pre-flight does NOT catch this (it only checks the stash KEY
    presence, not contents), so emit()'s _missing guard is the sole defense.
    """

    @pytest.mark.parametrize("missing_key", _EXPECTED_RAW_KEYS)
    def test_missing_raw_key_raises_runtime_error(self, missing_key):
        """For the raw key: delete it -> emit() raises RuntimeError naming it.

        INJECT-BUG (Path B-2 / parametrized): each iteration deletes one raw key
        from the constructed stash. RED if emit() does NOT raise (i.e. if the guard
        were removed). The guard's presence is what makes the iteration green.
        Removing the `_missing` check makes it RED (a bare AttributeError from
        ``None.get(...)`` or a silently-wrong empty dict).
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
        del stash["symbol_counts_by_col_by_spin_type_total"]
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, _summary_with(stash), None)
        msg = str(ei.value)
        assert "symbol_counts_by_col_by_spin_type_total" in msg
        assert "silently default" in msg or "feedback_no_silent_swallow" in msg, (
            f"diagnostic must explain it refuses to silently default. Got: {msg!r}"
        )

    def test_does_not_write_profile_on_missing_key(self):
        """On a missing raw key, emit() must NOT have written a partial dict.

        Critical: the failure must be loud AND clean — no half-built
        reel_marginal_by_spin_type left in player_impact that a caller might consume
        as if valid.
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash["symbol_counts_by_col_by_spin_type_total"]
        summary = _summary_with(stash)
        with pytest.raises(RuntimeError):
            plugin.emit({}, summary, None)
        pi = summary.get("player_impact", {})
        assert "reel_marginal_by_spin_type" not in pi, (
            "emit() must not leave a partial reel_marginal_by_spin_type dict when a "
            "raw key is missing — the failure must be clean (no half-built dict)."
        )

    def test_does_not_index_stash_before_missing_check(self):
        """A missing-key failure must NOT silently swallow into a downstream error.

        The guard runs BEFORE any raw value is indexed, so the message is the
        descriptive RuntimeError — not a bare ``KeyError`` /
        ``AttributeError: 'NoneType' object has no attribute 'get'`` from a later
        ``stash["..."]`` / ``.get(st_int)`` access. Asserts the error TYPE + that
        the message is the plugin's diagnostic (contains the plugin name), proving
        the explicit ``_missing`` guard fires first.
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash["symbol_counts_by_col_by_spin_type_total"]
        with pytest.raises(RuntimeError) as ei:
            plugin.emit({}, _summary_with(stash), None)
        # A bare KeyError / AttributeError would NOT contain the plugin diagnostic.
        assert "reel_marginal_by_spin_type plugin" in str(ei.value), (
            "the explicit _missing guard must fire before any raw-value indexing "
            f"(no bare KeyError/AttributeError). Got: {str(ei.value)!r}"
        )

    def test_stash_pop_does_not_leave_stash_in_summary_after_failure(self):
        """Even on a missing-key failure, the popped stash key is not re-added.

        emit() pops _STASH_KEY before validating; a missing-raw-key failure must
        leave the summary clean (no stash key re-injected, no partial profile). A
        downstream consumer must not find a half-state to act on.
        """
        plugin = _import_plugin_class()()
        stash = _full_stash()
        del stash["symbol_counts_by_col_by_spin_type_total"]
        summary = _summary_with(stash)
        with pytest.raises(RuntimeError):
            plugin.emit({}, summary, None)
        assert _STASH_KEY not in summary, (
            "emit() pops the stash key; on failure it must not be left behind."
        )
        assert "reel_marginal_by_spin_type" not in summary.get("player_impact", {})


# ---------------------------------------------------------------------------
# T3: End-to-end fail-loud — real subprocess surfaces the failure on disk.
#
#     The first two tests assert the surfacing CHANNELS exist structurally
#     (feature_errors for the raw-key path; the Region 2 DECLARED_DEPS check for
#     the absent-stash path). The third is SKIPPED by default (it requires
#     temporarily editing PIA, which we do NOT do automatically in CI). It
#     documents + (when manually un-skipped during authoring) verifies the
#     end-to-end disk-surfacing path. The captured RED evidence lives in
#     inject_bug_evidence.md.
# ---------------------------------------------------------------------------

class TestEndToEndFailLoudIsSurfaced:
    """The end-to-end paths surface on disk — proven by the authoring-time
    inject-bug (evidence in inject_bug_evidence.md §B), asserted structurally here.
    """

    def test_feature_errors_is_the_surfacing_channel(self):
        """Sanity: the analyzer surfaces plugin emit() exceptions under
        summary['feature_errors'][feature_id] (the channel the raw-key inject-bug
        used).

        We assert the mechanism exists by checking the PIA emit loop records into
        feature_errors. (Run the real inject-bug per the recipe to see the
        RuntimeError text land there.)
        """
        src = _PIA.read_text(encoding="utf-8")
        assert "feature_errors" in src, (
            "PIA must surface plugin emit() failures via a 'feature_errors' summary "
            "key (the fail-loud disk channel)."
        )

    def test_region2_declared_deps_check_is_the_absent_stash_channel(self):
        """Sanity: the PIA Region 2 pre-flight surfaces an absent DECLARED_DEPS key
        as analyzer_init_error (the channel an absent stash would use end-to-end).

        Confirms the mechanism the brief names: an absent stash key is caught by
        the Region 2 DECLARED_DEPS check (PluginDeclaredDepMissingError ->
        analyzer_init_error region=2 -> SystemExit(1)) BEFORE emit() runs.
        """
        src = _PIA.read_text(encoding="utf-8")
        assert "PluginDeclaredDepMissingError" in src
        assert "analyzer_init_error" in src
        assert "DECLARED_DEPS" in src

    @pytest.mark.skip(
        reason="Requires temporarily editing PIA's stash builder; run manually per "
        "the Path B inject-bug recipe. RED evidence captured in "
        "inject_bug_evidence.md §B (authoring-time, 2026-05-30)."
    )
    def test_e2e_missing_raw_key_lands_in_feature_errors(self):  # pragma: no cover
        """When PIA omits the raw key, M275 run records the RuntimeError in
        feature_errors[reel_marginal_by_spin_type] (NOT a silently-wrong dict).

        Manual recipe (Path B end-to-end):
          1. Comment out the raw key in PIA's
             summary["_reel_marginal_by_spin_type_data"] builder (~line 4434):
             # "symbol_counts_by_col_by_spin_type_total": symbol_counts_by_col_by_spin_type_total,
          2. Run M275 mode 1 from cache.
          3. Assert summary["feature_errors"]["reel_marginal_by_spin_type"] contains
             the RuntimeError text naming the missing key AND player_impact has no
             reel_marginal_by_spin_type.
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
            assert "reel_marginal_by_spin_type" in fe
