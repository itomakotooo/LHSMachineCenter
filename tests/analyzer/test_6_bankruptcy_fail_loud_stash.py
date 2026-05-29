"""Phase 6 — fail-loud stash + DECLARED_DEPS contract for the bankruptcy_simulation carve.

After the Phase 6 carve the split-ownership shape (brief §0/§2) is:

  * PIA calls the carved module-level ``build_bankruptcy_rows(totals, mults, bet,
    session_spins)`` PRE-SUMMARY (positional args, NOT a stash) to obtain the tier
    rows, derives x100/x200/x500 from them, and STASHES the rows into
    ``summary["_bankruptcy_rows"]`` + ``summary["_bankruptcy_sim_session_spins"]``.
  * The plugin's ``emit()`` is UNCHANGED: it reads those two temp keys by DIRECT
    INDEX (``summary["_bankruptcy_rows"]`` / ``summary["_bankruptcy_sim_session_spins"]``),
    writes ``player_impact.bankruptcy_simulation`` + ``player_impact.bankruptcy_probe``,
    then ``del``-etes both temp keys.

THIS PLUGIN'S FAIL-LOUD SHAPE DIFFERS FROM PHASES 4/5 (read the plugin, do not copy)
------------------------------------------------------------------------------------
Phases 4/5 carved the dict-BUILD into emit(), which guards a missing RAW input with
an explicit ``raise RuntimeError("...refuses to silently default...")``. Phase 6 is
different on BOTH ends of the split:

  1. ``build_bankruptcy_rows`` takes POSITIONAL args, not a stash. A missing input is
     a ``TypeError`` at the call site (``build_bankruptcy_rows() missing N required
     positional arguments``) — NOT a silent default. This is the documented fail-loud
     surface for the build half (brief deliverable #2 NOTE). We assert it directly.

  2. ``emit()`` reads the two stash keys by DIRECT INDEX. An absent key raises a bare
     ``KeyError`` naming the exact key — again NOT a silent default. There is NO
     explicit RuntimeError-with-diagnostic in this emit() (unlike reel_marginal /
     multiplier_profile). We assert the KeyError + the exact key named, and that no
     partial dict is left behind. (We do NOT assert a diagnostic message string — this
     plugin intentionally does not synthesize one; the KeyError IS the loud failure.)

TWO surfacing layers end-to-end (mirrors the Phase 4/5 contract structurally)
-----------------------------------------------------------------------------
1. STASH KEY ENTIRELY ABSENT — the plugin declares
   ``DECLARED_DEPS = ("_bankruptcy_rows", "_bankruptcy_sim_session_spins")``. The PIA
   emit-loop Region 2 pre-flight (player_impact_analyzer.py ~4725) fires
   ``_PluginDeclaredDepMissingError`` and writes ``summary["analyzer_init_error"]``
   (region=2) + ``SystemExit(1)`` BEFORE emit() is ever called. So end-to-end an
   absent stash surfaces as ``analyzer_init_error``, NOT feature_errors. emit()'s
   direct-index ``KeyError`` is the SECOND line (reachable only on a direct emit()
   call / if Region 2 were bypassed); the unit tests below exercise that directly.

2. emit() RAISES (direct-index KeyError) — caught by the PIA emit-error handler
   (~4755) → ``summary["feature_errors"]["bankruptcy_simulation"]`` on disk. (Not the
   primary production path here, because Region 2 catches the absent stash key first;
   asserted structurally.)

This file MIRRORS ``test_5_reel_marginal_fail_loud_stash.py`` STRUCTURALLY (T0
contract-mirror guards, T1 absent-stash unit, T2 missing-input fail-loud, T3 e2e
channel sanity) but the ASSERTIONS reflect Phase 6's KeyError/TypeError reality.

emit() reads ``ctx`` for nothing in the build path (verified: emit() only touches
summary), so emit() is called with ctx=None throughout.

Inject-bug recipe (Path B — fail-loud stash; per feedback_enumerate_safety_paths.md)
------------------------------------------------------------------------------------
UNIT (this file, no source edit needed — we omit a stash key from the summary):
    build a summary WITHOUT ``_bankruptcy_rows``, call emit() -> KeyError naming
    '_bankruptcy_rows'. This proves emit() reads by direct index (fails loud), not a
    ``.get(...)`` default.

    To PROVE the test catches a regression-to-silent-default (the inject-bug):
    temporarily change emit()'s
        bankruptcy_rows: list[dict] = summary["_bankruptcy_rows"]
    to
        bankruptcy_rows = summary.get("_bankruptcy_rows", [])   # BUG (silent default)
    RED: test_emit_raises_keyerror_when_rows_absent no longer raises (emit writes an
         empty tiers list instead of failing). Revert -> GREEN.
    (Verified 2026-05-30; evidence in inject_bug_evidence.md §B.)

END-TO-END (real PIA edit, run once during authoring — DECLARED_DEPS Region 2 path):
    In fresh_slotlab/player_impact_analyzer.py, comment out the stash assignment
    (~line 4434):
        # summary["_bankruptcy_rows"] = bankruptcy_rows
    RED: a real `python player_impact_analyzer.py --machine M275 ...` run lands the
         failure in summary["analyzer_init_error"] (region=2, affected_plugin=
         bankruptcy_simulation, naming '_bankruptcy_rows') with SystemExit(1) — NOT a
         silently-wrong report.
    Revert -> GREEN. (Verified 2026-05-30; evidence in inject_bug_evidence.md §B-e2e.)

Memory files cited
------------------
- memory/feedback_no_silent_swallow.md
    a missing input must fail loudly, never default to a silent wrong number. The
    build half fails via TypeError (positional args); the emit half fails via
    KeyError (direct index); the absent-stash-key case surfaces end-to-end via
    analyzer_init_error (Region 2 DECLARED_DEPS check).
- memory/feedback_enumerate_safety_paths.md
    inject-bug -> red -> revert -> green is mandatory for EACH safety path: the
    build-arg path, the emit() direct-index path, AND the end-to-end Region 2 path.
- memory/feedback_subprocess_import_suicide_and_module_globals.md
    import-time side-effect freedom (the plugin import is a pure register(); the
    module-top SHARED-helper imports resolve no-op).
- memory/feedback_perf_claim_needs_e2e_event_stream.md
    the end-to-end channel (analyzer_init_error / feature_errors) cannot be proven by
    a unit alone; the authoring-time inject-bug ran a REAL subprocess against real
    cached M275 (evidence in inject_bug_evidence.md).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_PLUGIN_SRC = (
    _REPO_ROOT / "fresh_slotlab" / "analyzer" / "features" / "bankruptcy_simulation.py"
)

# The two temp (stash) keys emit() reads by direct index.
# MUST match DECLARED_DEPS in bankruptcy_simulation.py VERBATIM (guarded below).
_STASH_ROWS_KEY = "_bankruptcy_rows"
_STASH_SPINS_KEY = "_bankruptcy_sim_session_spins"
_DECLARED_DEPS_EXPECTED: tuple[str, ...] = (_STASH_ROWS_KEY, _STASH_SPINS_KEY)


def _import_plugin_class():
    try:
        from fresh_slotlab.analyzer.features.bankruptcy_simulation import (
            BankruptcySimulation,
        )
    except ImportError:  # running as standalone script
        from analyzer.features.bankruptcy_simulation import (  # type: ignore[no-redef]
            BankruptcySimulation,
        )
    return BankruptcySimulation


def _import_build_fn():
    try:
        from fresh_slotlab.analyzer.features.bankruptcy_simulation import (
            build_bankruptcy_rows,
        )
    except ImportError:  # running as standalone script
        from analyzer.features.bankruptcy_simulation import (  # type: ignore[no-redef]
            build_bankruptcy_rows,
        )
    return build_bankruptcy_rows


def _one_tier_totals() -> dict[int, dict[str, Any]]:
    """A minimal valid bankruptcy_sim_totals dict for one tier.

    bankrupt=2 / survived=1 / two spins_done entries → a populated, non-degenerate
    tier so build_bankruptcy_rows emits a clean row (rate > 0, fastest not None).
    The rich byte-identical data is covered by the M275/M14 goldens in
    test_6_byte_identical_bankruptcy_carve.py; the empty / zero-session branches are
    covered in test_6_bankruptcy_coverage_gaps.py.
    """
    return {100: {"bankrupt": 2, "survived": 1, "spins_done": [50, 80]}}


def _full_stash_summary() -> dict[str, Any]:
    """A complete, valid summary for emit() (both stash keys + player_impact)."""
    rows = _import_build_fn()(_one_tier_totals(), (100,), 1000, 10000)
    return {
        _STASH_ROWS_KEY: rows,
        _STASH_SPINS_KEY: 10000,
        "player_impact": {},
    }


# ---------------------------------------------------------------------------
# T0: the local mirrors equal the plugin's actual declarations + invariants
# ---------------------------------------------------------------------------

class TestContractMirrorsPlugin:
    """Guard: the local mirrors must equal the plugin's actual declarations.

    If a refactor changes the plugin's DECLARED_DEPS / SCHEMA_KEYS / RTP flag but
    not these mirrors, the fail-loud + e2e tests would silently stop covering the
    new contract (stale-green). These fail loudly the moment they diverge.
    """

    def test_declared_deps_are_the_two_stash_keys(self):
        """DECLARED_DEPS must be exactly the two stash keys, in order.

        This is what wires the Region 2 pre-flight (the e2e absent-stash path lands
        in analyzer_init_error, not feature_errors). If DECLARED_DEPS drifted away
        from a stash key, that key's absence would no longer be caught by Region 2.
        """
        plugin = _import_plugin_class()()
        assert plugin.DECLARED_DEPS == _DECLARED_DEPS_EXPECTED, (
            f"DECLARED_DEPS must be {_DECLARED_DEPS_EXPECTED!r} so the Region 2 "
            f"pre-flight fires on either absent stash key. Got {plugin.DECLARED_DEPS!r}"
        )

    def test_declared_deps_match_plugin_source(self):
        """DECLARED_DEPS literal in the plugin source must match the expected tuple.

        Reads the source so a key added/removed/renamed in the plugin fails this
        test rather than silently de-covering the tests below.
        """
        src = _PLUGIN_SRC.read_text(encoding="utf-8")
        m = re.search(r"DECLARED_DEPS[^=]*=\s*\((.*?)\)", src, re.DOTALL)
        assert m, "could not locate DECLARED_DEPS tuple in plugin source"
        src_keys = tuple(re.findall(r'"(_[a-z0-9_]+)"', m.group(1)))
        assert src_keys == _DECLARED_DEPS_EXPECTED, (
            "plugin DECLARED_DEPS diverged from this test's expected tuple.\n"
            f"plugin: {src_keys}\n"
            f"test  : {_DECLARED_DEPS_EXPECTED}\n"
            "Update _DECLARED_DEPS_EXPECTED to match (keeps the fail-loud tests "
            "covering both stash keys)."
        )

    def test_schema_keys_are_the_two_bankruptcy_keys(self):
        """SCHEMA_KEYS must be the two final summary keys this plugin owns."""
        plugin = _import_plugin_class()()
        assert plugin.SCHEMA_KEYS == ("bankruptcy_simulation", "bankruptcy_probe"), (
            f"SCHEMA_KEYS drifted: {plugin.SCHEMA_KEYS!r}"
        )

    def test_rtp_contribution_is_false(self):
        """bankruptcy_simulation is display-only — RTP_CONTRIBUTION must be False.

        Pins the brief §5 invariant (RTP untouched). A flip to True would put this
        feature into the RTP-attribution path and break the aggregator parity
        invariant; the byte-identity ``rtp`` diff would also catch it, but this pins
        the declaration directly.
        """
        plugin = _import_plugin_class()()
        assert plugin.RTP_CONTRIBUTION is False

    def test_build_fn_lives_in_plugin_file(self):
        """build_bankruptcy_rows must be defined in the PLUGIN file (R-4 exclusion).

        The whole point of the carve: the row-build bytes live in the plugin file
        (NOT in core/, NOT in PIA), so editing them flips THIS feature's hash, not
        the shared base. If build_bankruptcy_rows were defined elsewhere this would
        regress the R-4 exclusion (and the drift-guard's
        test_registered_plugin_edit_does_not_flip_base would no longer cover it).
        """
        build_fn = _import_build_fn()
        defining_file = Path(build_fn.__code__.co_filename).resolve()
        assert defining_file == _PLUGIN_SRC.resolve(), (
            f"build_bankruptcy_rows must be defined in {_PLUGIN_SRC} (the R-4-excluded "
            f"plugin file), but is defined in {defining_file}. Moving it out of the "
            f"plugin would put its bytes back into base_hash."
        )
        # And the source literally contains the def (belt-and-suspenders).
        src = _PLUGIN_SRC.read_text(encoding="utf-8")
        assert "def build_bankruptcy_rows(" in src, (
            "plugin source must contain the build_bankruptcy_rows definition."
        )

    def test_full_stash_summary_drives_emit_success(self):
        """A complete summary must drive emit() to success (sanity: the happy path).

        Proves the stash key set is at least sufficient — if emit() required a key
        our _full_stash_summary() lacks, it would raise and this would fail. Also
        confirms emit() writes both final keys and deletes both temp keys.
        """
        plugin = _import_plugin_class()()
        summary = _full_stash_summary()
        plugin.emit({}, summary, None)  # must NOT raise (ctx unused)
        pi = summary["player_impact"]
        assert "bankruptcy_simulation" in pi
        assert "bankruptcy_probe" in pi
        assert pi["bankruptcy_simulation"]["source"] == "rawdata_replay"
        assert pi["bankruptcy_simulation"]["session_spins"] == 10000
        assert pi["bankruptcy_probe"] == pi["bankruptcy_simulation"]["tiers"]
        # Temp keys deleted (must not reach final JSON).
        assert _STASH_ROWS_KEY not in summary
        assert _STASH_SPINS_KEY not in summary


# ---------------------------------------------------------------------------
# T1: emit() with a stash key absent -> bare KeyError naming the key
#     (the plugin reads by DIRECT INDEX — fail loud, no silent default)
# ---------------------------------------------------------------------------

class TestStashKeyAbsentFailsLoud:
    """emit() with a missing stash key must raise KeyError (not silently skip).

    NOTE: end-to-end, the PIA Region 2 pre-flight catches an absent stash key FIRST
    (_PluginDeclaredDepMissingError -> analyzer_init_error -> SystemExit), so emit()
    is never reached in production. This direct-index KeyError is the second line and
    is exercised by calling emit() directly (the unit path).

    Phase-6-specific: there is NO explicit RuntimeError-with-diagnostic here (unlike
    reel_marginal/multiplier_profile). emit() reads ``summary["_bankruptcy_rows"]``
    by direct index; the KeyError IS the loud failure (NOT a ``.get(...)`` default).
    """

    def test_emit_raises_keyerror_when_rows_absent(self):
        """No _bankruptcy_rows in summary -> KeyError naming the key.

        INJECT-BUG (Path B): change emit()'s
            bankruptcy_rows = summary["_bankruptcy_rows"]
        to
            bankruptcy_rows = summary.get("_bankruptcy_rows", [])
        RED: this test no longer raises (emit silently writes an empty tiers list).
        Revert -> GREEN.
        """
        plugin = _import_plugin_class()()
        # session_spins present, rows absent.
        summary: dict[str, Any] = {_STASH_SPINS_KEY: 10000, "player_impact": {}}
        with pytest.raises(KeyError) as ei:
            plugin.emit({}, summary, None)
        assert _STASH_ROWS_KEY in str(ei.value), (
            f"KeyError must name the absent key {_STASH_ROWS_KEY!r}. Got {ei.value!r}"
        )

    def test_emit_raises_keyerror_when_session_spins_absent(self):
        """No _bankruptcy_sim_session_spins in summary -> KeyError naming the key.

        Rows present so the FIRST direct index (rows) succeeds; the SECOND
        (session_spins) is the one that must fail loud.
        """
        plugin = _import_plugin_class()()
        summary: dict[str, Any] = {_STASH_ROWS_KEY: [], "player_impact": {}}
        with pytest.raises(KeyError) as ei:
            plugin.emit({}, summary, None)
        assert _STASH_SPINS_KEY in str(ei.value), (
            f"KeyError must name the absent key {_STASH_SPINS_KEY!r}. Got {ei.value!r}"
        )

    def test_emit_raises_when_both_absent(self):
        """Both stash keys absent -> KeyError (names the first-read key, rows)."""
        plugin = _import_plugin_class()()
        with pytest.raises(KeyError) as ei:
            plugin.emit({}, {"player_impact": {}}, None)
        # emit() reads _bankruptcy_rows first, so that's the key named.
        assert _STASH_ROWS_KEY in str(ei.value), (
            f"with both absent, the first direct index ({_STASH_ROWS_KEY}) must be "
            f"the one that raises. Got {ei.value!r}"
        )

    def test_no_partial_dict_written_on_absent_rows(self):
        """On an absent rows key, emit() must NOT have written a partial dict.

        Critical: the failure must be loud AND clean — no half-built
        bankruptcy_simulation left in player_impact that a caller might consume as if
        valid. (emit() reads rows on its FIRST statement, before writing anything, so
        player_impact stays empty.)
        """
        plugin = _import_plugin_class()()
        summary: dict[str, Any] = {_STASH_SPINS_KEY: 10000, "player_impact": {}}
        with pytest.raises(KeyError):
            plugin.emit({}, summary, None)
        assert "bankruptcy_simulation" not in summary["player_impact"], (
            "emit() must not write bankruptcy_simulation when a stash key is absent "
            "— the failure must be clean (no half-built dict)."
        )
        assert "bankruptcy_probe" not in summary["player_impact"]

    def test_no_partial_dict_written_when_only_simulation_then_probe(self):
        """If session_spins is absent, emit() must not leave a half-written panel.

        emit() reads BOTH stash keys (rows then session_spins) BEFORE it writes
        anything into player_impact, so a missing session_spins must leave
        player_impact completely empty — not a bankruptcy_simulation written but no
        bankruptcy_probe. Pins the read-all-then-write ordering.
        """
        plugin = _import_plugin_class()()
        rows = _import_build_fn()(_one_tier_totals(), (100,), 1000, 10000)
        summary: dict[str, Any] = {_STASH_ROWS_KEY: rows, "player_impact": {}}
        with pytest.raises(KeyError):
            plugin.emit({}, summary, None)
        # Neither key written — not a half-state.
        assert "bankruptcy_simulation" not in summary["player_impact"]
        assert "bankruptcy_probe" not in summary["player_impact"]


# ---------------------------------------------------------------------------
# T2: build_bankruptcy_rows missing input -> TypeError at the call site
#     (positional args, NOT a stash — the documented fail-loud surface, brief #2)
# ---------------------------------------------------------------------------

class TestBuildFnMissingInputFailsLoud:
    """A missing build input must fail loud (TypeError), never a silent default.

    Unlike the Phase 4/5 carves (which stash a dict and guard the missing key with
    a RuntimeError), build_bankruptcy_rows takes 4 POSITIONAL args. Omitting one is
    a TypeError at the call site — Python's own fail-loud for a missing positional
    arg. The brief (deliverable #2 NOTE) flags this is NOT a silent default and asks
    us to document + assert it.
    """

    def test_missing_bet_and_session_spins_raises_type_error(self):
        """Calling with only 2 of 4 positional args -> TypeError naming them."""
        build_fn = _import_build_fn()
        with pytest.raises(TypeError) as ei:
            build_fn(_one_tier_totals(), (100,))  # missing bet + session_spins
        msg = str(ei.value)
        assert "missing" in msg and "positional argument" in msg, (
            f"a missing positional arg must raise the standard TypeError. Got {msg!r}"
        )
        # Names the missing params (CPython includes the arg names).
        assert "bet" in msg and "bankruptcy_sim_session_spins" in msg, (
            f"TypeError should name the missing args (bet, "
            f"bankruptcy_sim_session_spins). Got {msg!r}"
        )

    def test_missing_session_spins_raises_type_error(self):
        """Calling with 3 of 4 args (no session_spins) -> TypeError."""
        build_fn = _import_build_fn()
        with pytest.raises(TypeError) as ei:
            build_fn(_one_tier_totals(), (100,), 1000)  # missing session_spins
        assert "bankruptcy_sim_session_spins" in str(ei.value), (
            f"TypeError should name the missing session_spins arg. Got {ei.value!r}"
        )

    def test_full_positional_call_succeeds(self):
        """The happy path: all 4 positional args -> a clean rows list (sanity).

        Proves the TypeError tests above fail for the right reason (a missing arg),
        not because the function is broken for valid input.
        """
        build_fn = _import_build_fn()
        rows = build_fn(_one_tier_totals(), (100,), 1000, 10000)
        assert isinstance(rows, list) and len(rows) == 1
        assert rows[0]["bankroll_multiplier"] == 100
        assert rows[0]["init_credits"] == 100 * 1000


# ---------------------------------------------------------------------------
# T3: End-to-end fail-loud — real subprocess surfaces the failure on disk.
#
#     The first two tests assert the surfacing CHANNELS exist structurally (the
#     Region 2 DECLARED_DEPS check for the absent-stash path; feature_errors for an
#     emit() raise). The third is SKIPPED by default (it requires temporarily
#     editing PIA, which we do NOT do automatically in CI). It documents + (when
#     manually un-skipped during authoring) verifies the end-to-end disk-surfacing
#     path. The captured RED evidence lives in inject_bug_evidence.md §B-e2e.
# ---------------------------------------------------------------------------

class TestEndToEndFailLoudIsSurfaced:
    """The end-to-end paths surface on disk — proven by the authoring-time
    inject-bug (evidence in inject_bug_evidence.md §B-e2e), asserted structurally here.
    """

    def test_region2_declared_deps_check_is_the_absent_stash_channel(self):
        """Sanity: the PIA Region 2 pre-flight surfaces an absent DECLARED_DEPS key
        as analyzer_init_error (the channel an absent stash would use end-to-end).

        Confirms the mechanism the brief names: an absent stash key is caught by the
        Region 2 DECLARED_DEPS check (_PluginDeclaredDepMissingError ->
        analyzer_init_error region=2 -> SystemExit(1)) BEFORE emit() runs.
        """
        src = _PIA.read_text(encoding="utf-8")
        assert "_PluginDeclaredDepMissingError" in src
        assert "analyzer_init_error" in src
        assert "DECLARED_DEPS" in src

    def test_feature_errors_is_the_emit_raise_channel(self):
        """Sanity: the analyzer surfaces plugin emit() exceptions under
        summary['feature_errors'][feature_id] (the channel an emit() KeyError would
        use IF Region 2 were bypassed).
        """
        src = _PIA.read_text(encoding="utf-8")
        assert "feature_errors" in src, (
            "PIA must surface plugin emit() failures via a 'feature_errors' summary "
            "key (the fail-loud disk channel)."
        )

    def test_pia_stashes_both_keys_for_emit(self):
        """Sanity: PIA assigns BOTH temp keys before the feature loop.

        This is the producer side of the split-ownership contract — PIA builds the
        rows via build_bankruptcy_rows() pre-summary, then stashes them. If either
        assignment were dropped, the Region 2 check would fire (proven by the
        authoring-time e2e inject-bug). Asserts both assignments are present in source.
        """
        src = _PIA.read_text(encoding="utf-8")
        assert re.search(rf'summary\[["\']{_STASH_ROWS_KEY}["\']\]\s*=', src), (
            f"PIA must stash {_STASH_ROWS_KEY!r} for emit()."
        )
        assert re.search(rf'summary\[["\']{_STASH_SPINS_KEY}["\']\]\s*=', src), (
            f"PIA must stash {_STASH_SPINS_KEY!r} for emit()."
        )

    def test_pia_calls_build_bankruptcy_rows_pre_summary(self):
        """Sanity: PIA imports + calls build_bankruptcy_rows (the pre-summary site).

        The split-ownership resolution: PIA calls the carved function (dual-path
        import) to obtain the rows BEFORE the summary dict is built, because the
        pre-summary x100/x200/x500 derivation consumes them. Asserts the import +
        call exist in source (the import being the NEW pattern flagged in brief §3
        RISK 1 — PIA importing a plugin FUNCTION on the report path).
        """
        src = _PIA.read_text(encoding="utf-8")
        assert "from fresh_slotlab.analyzer.features.bankruptcy_simulation import" in src
        assert "build_bankruptcy_rows" in src
        # The x100/x200/x500 derivation must read from the rows.
        assert "x100_br" in src and "x200_br" in src and "x500_br" in src

    @pytest.mark.skip(
        reason="Requires temporarily editing PIA's stash assignment; run manually per "
        "the Path B-e2e inject-bug recipe. RED evidence captured in "
        "inject_bug_evidence.md §B-e2e (authoring-time, 2026-05-30)."
    )
    def test_e2e_missing_stash_lands_in_analyzer_init_error(self):  # pragma: no cover
        """When PIA omits the _bankruptcy_rows stash, M275 run records the failure in
        summary['analyzer_init_error'] (region=2), NOT a silently-wrong report.

        Manual recipe (Path B-e2e):
          1. Comment out the stash assignment in PIA (~line 4434):
             # summary["_bankruptcy_rows"] = bankruptcy_rows
          2. Run M275 mode 1 from cache.
          3. Assert summary["analyzer_init_error"]["region"] == 2 AND
             ["affected_plugin"] == "bankruptcy_simulation" AND the message names
             '_bankruptcy_rows'; assert the process exited non-zero.
          4. Revert; re-run; assert no analyzer_init_error + bankruptcy_simulation present.
        """
        pytest.skip("manual authoring-time inject-bug; see inject_bug_evidence.md §B-e2e")
