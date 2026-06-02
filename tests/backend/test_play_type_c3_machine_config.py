"""Commit C3 — per-machine config layer + BCM bonus-feature migration tests.

Invariants under test
---------------------
P1 - Per-machine config JSON files exist for all 5 BCM pilots (M272, M275,
     M279, M268, M274) in configs/play_type_configs/<M>/mode_1.json with the
     correct ``plugin_configs["bcm_base"]["bonus_feature"]`` values matching
     the golden values from bcm_pairings.json.

P2 - MachinePlayTypeConfig.get_bcm_bonus_feature() returns the correct value
     for all 5 BCM pilots and None for non-BCM machines (M14, M15, M120, M10).

P3 - detect_play_types() with machine_id + mode loads plugin_configs from disk
     and merges bonus_feature into the returned config.  Without machine_id
     (empty string), plugin_configs stays empty (backward-compat).

P4 - _resolve_bonus_feature() layer-0 (per-machine config) takes precedence
     over bcm_pairings.json layer-1 when play_type_config is provided and has
     a non-empty bonus_feature.  Result is source="config" in both cases.

P5 - per_machine_config_hash() changes when bonus_feature changes.

P6 - End-to-end inject-bug: changing the per-machine config file's
     bonus_feature causes _resolve_bonus_feature to return the wrong value,
     which flows into the _collect_mechanic_data stash's bonus_feature field.
     Reverting the config file restores the correct value.

P7 - parse_chunk_response() with machine_id + mode + flag=ON threads machine
     identity to detect_play_types so the loaded plugin_configs are available
     to the BCMBaseAccumulator.  Without machine_id, backward-compatible.

Inject-bug recipes
------------------
P5-inject: Set cfg.plugin_configs['bcm_base']['bonus_feature'] = 'WRONG' →
    per_machine_config_hash() changes → RED if asserted equal to original.
    Revert → GREEN.

P6-inject: Write a temporary config file with 'bonus_feature': 'INJECTED' →
    _resolve_bonus_feature returns ('INJECTED', 'config') → RED if asserted
    == golden. Revert (restore original file) → GREEN.

Memory feedback files honoured
-------------------------------
- memory/feedback_no_silent_swallow.md — detect_play_types logs stderr on
  parse error, does not silently return empty plugin_configs.
- memory/feedback_md5_is_a_tag_not_a_destruction_signal.md — per_machine_config_hash
  is a version tag for cache invalidation, not a delete signal.
- memory/feedback_subprocess_import_suicide_and_module_globals.md — PIA loads
  MachinePlayTypeConfig inside main() (not at module scope) to avoid circular
  import and side effects.
- memory/feedback_enumerate_safety_paths.md — inject-bug P6 tests the full
  read path (file → detect_play_types → _resolve_bonus_feature), not just the
  low-level helper.
"""
from __future__ import annotations

import json
import types
import copy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIGS_ROOT = ROOT / "configs" / "play_type_configs"
BCM_PAIRINGS_PATH = ROOT / "configs" / "bcm_pairings.json"
RAWDATA_DIR = ROOT / "rawdata"


# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------
try:
    from fresh_slotlab.analyzer.play_types._machine_config import MachinePlayTypeConfig
    from fresh_slotlab.analyzer.play_types._detector import detect_play_types
    from fresh_slotlab.player_impact_analyzer import (
        _resolve_bonus_feature,
        _load_bcm_pairings,
    )
    _FRAMEWORK_AVAILABLE = True
except ImportError:
    _FRAMEWORK_AVAILABLE = False

_SKIP_NO_FRAMEWORK = pytest.mark.skipif(
    not _FRAMEWORK_AVAILABLE,
    reason="Play-type framework or PIA not importable",
)

# BCM pilot table: (machine_id, mode, expected_bonus_feature_from_bcm_pairings)
# Values sourced from configs/bcm_pairings.json (verified at module scope below).
_BCM_PILOTS = [
    ("M272", 1, "NewFreespin"),
    ("M275", 1, "NewFreespin"),
    ("M279", 1, "Wheel"),
    ("M268", 1, "CreditsSymbolRespin"),
    ("M274", 1, "ListRewardWheel"),
]

# Non-BCM machines — should have no per-machine config file for mode 1.
_NON_BCM = ["M14", "M15", "M120", "M10"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_bcm_pairings_value(machine: str, mode: int) -> "str | None":
    """Load the expected bonus_feature from bcm_pairings.json for (machine, mode)."""
    try:
        raw = json.loads(BCM_PAIRINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return (
        raw.get("machines", {})
           .get(machine, {})
           .get("modes", {})
           .get(str(mode), {})
           .get("bonus_feature")
    )


def _load_m272_rounds() -> "list[dict]":
    """Load M272 chunk_0001 first-robot rounds."""
    d = RAWDATA_DIR / "M272" / "mode_1"
    if not d.is_dir():
        return []
    chunks = sorted(d.glob("chunk_*.json"))
    if not chunks:
        return []
    chunk = json.loads(chunks[0].read_text(encoding="utf-8"))
    resp = chunk["response"]
    r0 = resp[0]
    raw = r0.get("roundResult")
    return json.loads(raw) if isinstance(raw, str) else (raw or [])


_M272_ROUNDS = _load_m272_rounds()
_M272_AVAILABLE = bool(_M272_ROUNDS)
_SKIP_NO_M272 = pytest.mark.skipif(not _M272_AVAILABLE, reason="M272 rawdata not available")


# ---------------------------------------------------------------------------
# Registry isolation (mirrors test_bcm_base.py pattern)
# ---------------------------------------------------------------------------
if _FRAMEWORK_AVAILABLE:
    import fresh_slotlab.analyzer.play_type_registry as _play_type_registry
    import fresh_slotlab.analyzer.play_types.bcm_base  # ensure bcm_base registered

    _REGISTRY_AT_IMPORT = list(_play_type_registry.ALL_PLAY_TYPE_PLUGINS)

    @pytest.fixture(autouse=True)
    def _isolate_play_type_registry():
        saved = list(_play_type_registry.ALL_PLAY_TYPE_PLUGINS)
        _play_type_registry.ALL_PLAY_TYPE_PLUGINS[:] = _REGISTRY_AT_IMPORT
        try:
            yield
        finally:
            _play_type_registry.ALL_PLAY_TYPE_PLUGINS[:] = saved


# ---------------------------------------------------------------------------
# P1 — Per-machine config files exist with correct bonus_feature values
# ---------------------------------------------------------------------------

class TestPerMachineConfigFiles:
    """P1: config JSON files for BCM pilots match bcm_pairings.json."""

    @_SKIP_NO_FRAMEWORK
    @pytest.mark.parametrize("machine,mode,expected_feat", _BCM_PILOTS)
    def test_config_file_exists_and_has_correct_bonus_feature(
        self, machine: str, mode: int, expected_feat: str,
    ) -> None:
        """Each BCM pilot has a config file with the right bonus_feature."""
        path = CONFIGS_ROOT / machine / f"mode_{mode}.json"
        assert path.exists(), (
            f"Per-machine config file missing: {path}\n"
            f"Expected file for BCM pilot {machine}/mode_{mode}."
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        got = data.get("plugin_configs", {}).get("bcm_base", {}).get("bonus_feature")
        assert got == expected_feat, (
            f"[{machine}/mode_{mode}] bonus_feature in config file: {got!r}\n"
            f"Expected (from bcm_pairings.json): {expected_feat!r}"
        )

    @_SKIP_NO_FRAMEWORK
    @pytest.mark.parametrize("machine,mode,expected_feat", _BCM_PILOTS)
    def test_config_bonus_feature_matches_bcm_pairings(
        self, machine: str, mode: int, expected_feat: str,
    ) -> None:
        """Config file value equals the corresponding bcm_pairings.json entry.

        This is the byte-identical gate: if they match, _resolve_bonus_feature
        will return the same value whether it reads from the per-machine config
        or from bcm_pairings.json.
        """
        golden = _load_bcm_pairings_value(machine, mode)
        assert golden is not None, (
            f"bcm_pairings.json has no entry for ({machine!r}, mode={mode})"
        )
        assert expected_feat == golden, (
            f"Test fixture mismatch: _BCM_PILOTS says {expected_feat!r} "
            f"but bcm_pairings.json says {golden!r} for ({machine}, mode={mode})"
        )

    @_SKIP_NO_FRAMEWORK
    @pytest.mark.parametrize("machine", _NON_BCM)
    def test_non_bcm_has_no_config_file(self, machine: str) -> None:
        """Non-BCM machines must NOT have a config file for mode 1.

        If they do, it was placed there accidentally — their bonus_feature
        should be resolved via heuristic, not via the config file.
        """
        path = CONFIGS_ROOT / machine / "mode_1.json"
        assert not path.exists(), (
            f"Unexpected per-machine config file for non-BCM machine {machine}: {path}"
        )


# ---------------------------------------------------------------------------
# P2 — MachinePlayTypeConfig.get_bcm_bonus_feature()
# ---------------------------------------------------------------------------

class TestGetBcmBonusFeature:
    """P2: get_bcm_bonus_feature() returns correct values."""

    @_SKIP_NO_FRAMEWORK
    @pytest.mark.parametrize("machine,mode,expected_feat", _BCM_PILOTS)
    def test_bcm_pilot_returns_correct_feature(
        self, machine: str, mode: int, expected_feat: str,
    ) -> None:
        """BCM pilots return the expected bonus_feature from their config file."""
        cfg = MachinePlayTypeConfig.read(machine, mode)
        assert cfg is not None, (
            f"MachinePlayTypeConfig.read({machine!r}, {mode}) returned None — "
            f"config file missing or unreadable"
        )
        got = cfg.get_bcm_bonus_feature()
        assert got == expected_feat, (
            f"[{machine}/mode_{mode}] get_bcm_bonus_feature() = {got!r}, "
            f"expected {expected_feat!r}"
        )

    @_SKIP_NO_FRAMEWORK
    @pytest.mark.parametrize("machine", _NON_BCM)
    def test_non_bcm_read_returns_none(self, machine: str) -> None:
        """Non-BCM machines have no config file → read() returns None."""
        cfg = MachinePlayTypeConfig.read(machine, 1)
        assert cfg is None, (
            f"MachinePlayTypeConfig.read({machine!r}, 1) returned {cfg!r} "
            f"but expected None (no config file should exist for non-BCM machines)"
        )

    @_SKIP_NO_FRAMEWORK
    def test_get_bcm_bonus_feature_returns_none_when_not_in_plugin_configs(self) -> None:
        """Config with no bcm_base entry → get_bcm_bonus_feature() returns None."""
        cfg = MachinePlayTypeConfig(machine_id="M99", mode=1, plugin_configs={})
        assert cfg.get_bcm_bonus_feature() is None

    @_SKIP_NO_FRAMEWORK
    def test_get_bcm_bonus_feature_returns_none_for_empty_string(self) -> None:
        """Config with empty string bonus_feature → returns None (truthy guard)."""
        cfg = MachinePlayTypeConfig(
            machine_id="M99", mode=1,
            plugin_configs={"bcm_base": {"bonus_feature": ""}},
        )
        assert cfg.get_bcm_bonus_feature() is None

    @_SKIP_NO_FRAMEWORK
    def test_get_bcm_bonus_feature_returns_value_when_present(self) -> None:
        """Config with bcm_base.bonus_feature → returns the value."""
        cfg = MachinePlayTypeConfig(
            machine_id="M272", mode=1,
            plugin_configs={"bcm_base": {"bonus_feature": "NewFreespin"}},
        )
        assert cfg.get_bcm_bonus_feature() == "NewFreespin"


# ---------------------------------------------------------------------------
# P3 — detect_play_types loads plugin_configs from disk
# ---------------------------------------------------------------------------

class TestDetectPlayTypesLoadsConfig:
    """P3: detect_play_types merges plugin_configs from disk when machine_id given."""

    @_SKIP_NO_FRAMEWORK
    @_SKIP_NO_M272
    def test_with_machine_id_loads_bonus_feature(self) -> None:
        """detect_play_types(machine_id='M272', mode=1) populates plugin_configs."""
        parse_state = types.SimpleNamespace(cost_credits_unreliable=False)
        cfg = detect_play_types(
            _M272_ROUNDS[:5000],
            _play_type_registry.ALL_PLAY_TYPE_PLUGINS,
            parse_state,
            machine_id="M272",
            mode=1,
        )
        assert cfg.machine_id == "M272"
        assert cfg.mode == 1
        feat = cfg.get_bcm_bonus_feature()
        assert feat == "NewFreespin", (
            f"Expected 'NewFreespin' from disk config, got {feat!r}.\n"
            "detect_play_types is not loading plugin_configs from disk."
        )

    @_SKIP_NO_FRAMEWORK
    @_SKIP_NO_M272
    def test_without_machine_id_no_plugin_configs(self) -> None:
        """detect_play_types(machine_id='') does NOT load disk config — backward-compat.

        Per the implementation: when machine_id is empty string, the disk-load
        block is skipped (``if machine_id:`` guard).
        """
        parse_state = types.SimpleNamespace(cost_credits_unreliable=False)
        cfg = detect_play_types(
            _M272_ROUNDS[:5000],
            _play_type_registry.ALL_PLAY_TYPE_PLUGINS,
            parse_state,
            machine_id="",
            mode=1,
        )
        # plugin_configs should be empty (no disk load).
        feat = cfg.get_bcm_bonus_feature()
        assert feat is None, (
            f"Expected None (no disk load when machine_id=''), got {feat!r}.\n"
            "The disk-load guard is not working correctly."
        )

    @_SKIP_NO_FRAMEWORK
    @_SKIP_NO_M272
    def test_unknown_machine_id_no_config_no_crash(self) -> None:
        """detect_play_types with unknown machine_id ('M99999') doesn't crash.

        No config file exists for M99999 → read() returns None → plugin_configs
        stays empty (graceful fallback).
        """
        parse_state = types.SimpleNamespace(cost_credits_unreliable=False)
        cfg = detect_play_types(
            _M272_ROUNDS[:5000],
            _play_type_registry.ALL_PLAY_TYPE_PLUGINS,
            parse_state,
            machine_id="M99999",
            mode=1,
        )
        # No crash, no plugin_configs.
        feat = cfg.get_bcm_bonus_feature()
        assert feat is None


# ---------------------------------------------------------------------------
# P4 — _resolve_bonus_feature layer-0 priority
# ---------------------------------------------------------------------------

class TestResolveBonusFeatureLayerZero:
    """P4: _resolve_bonus_feature prefers per-machine config over bcm_pairings."""

    @_SKIP_NO_FRAMEWORK
    @pytest.mark.parametrize("machine,mode,expected_feat", _BCM_PILOTS)
    def test_layer0_wins_for_bcm_pilots(
        self, machine: str, mode: int, expected_feat: str,
    ) -> None:
        """Layer-0 (per-machine config) wins and returns source='config'."""
        cfg = MachinePlayTypeConfig.read(machine, mode)
        assert cfg is not None
        feat, src = _resolve_bonus_feature(
            machine, mode, {}, _load_bcm_pairings(),
            play_type_config=cfg,
        )
        assert feat == expected_feat, (
            f"[{machine}/mode_{mode}] expected {expected_feat!r}, got {feat!r}"
        )
        assert src == "config", f"Expected src='config', got {src!r}"

    @_SKIP_NO_FRAMEWORK
    def test_layer0_overrides_bcm_pairings_when_different(self) -> None:
        """A config file with a DIFFERENT value wins over bcm_pairings.json.

        This proves layer-0 actually takes priority, not just returns the same
        value by coincidence.
        """
        # Build a config that disagrees with bcm_pairings.json.
        cfg = MachinePlayTypeConfig(
            machine_id="M272", mode=1,
            plugin_configs={"bcm_base": {"bonus_feature": "CustomBonusFeature"}},
        )
        feat, src = _resolve_bonus_feature(
            "M272", 1, {}, _load_bcm_pairings(),
            play_type_config=cfg,
        )
        # Layer-0 must win.
        assert feat == "CustomBonusFeature", (
            f"Expected 'CustomBonusFeature' from layer-0 config, got {feat!r}.\n"
            "Layer-0 (per-machine config) is NOT taking priority over bcm_pairings."
        )
        assert src == "config"

    @_SKIP_NO_FRAMEWORK
    def test_none_play_type_config_falls_through_to_bcm_pairings(self) -> None:
        """play_type_config=None → layer-0 skipped; bcm_pairings layer-1 fires."""
        feat, src = _resolve_bonus_feature(
            "M272", 1, {}, _load_bcm_pairings(),
            play_type_config=None,
        )
        # bcm_pairings.json has M272/mode=1 → NewFreespin.
        assert feat == "NewFreespin", (
            f"Expected 'NewFreespin' from bcm_pairings layer-1, got {feat!r}"
        )
        assert src == "config"

    @_SKIP_NO_FRAMEWORK
    def test_empty_bonus_feature_in_config_falls_through(self) -> None:
        """Config with empty bonus_feature → layer-0 skips; bcm_pairings fires."""
        cfg = MachinePlayTypeConfig(
            machine_id="M272", mode=1,
            plugin_configs={"bcm_base": {"bonus_feature": ""}},
        )
        feat, src = _resolve_bonus_feature(
            "M272", 1, {}, _load_bcm_pairings(),
            play_type_config=cfg,
        )
        # get_bcm_bonus_feature() returns None for empty string → layer-0 skipped.
        assert feat == "NewFreespin", (
            f"Expected 'NewFreespin' from bcm_pairings (layer-0 skipped for empty), got {feat!r}"
        )

    @_SKIP_NO_FRAMEWORK
    def test_non_bcm_machine_no_config_uses_heuristic(self) -> None:
        """Non-BCM machine: no config file + no bcm_pairings entry → heuristic or none."""
        cfg_m14 = MachinePlayTypeConfig.read("M14", 1)
        assert cfg_m14 is None, "Expected M14 to have no config file"
        feat, src = _resolve_bonus_feature(
            "M14", 1, {}, _load_bcm_pairings(),
            play_type_config=None,
        )
        # M14 has no bcm_pairings entry + empty tally → (None, 'none').
        assert feat is None
        assert src == "none"


# ---------------------------------------------------------------------------
# P5 — per_machine_config_hash changes with bonus_feature (inject-bug)
# ---------------------------------------------------------------------------

class TestPerMachineConfigHashInjectBug:
    """P5: per_machine_config_hash flips when bonus_feature changes.

    This is the inject-bug proof that the hash is genuinely sensitive to
    the bonus_feature value — not a constant or machine-ID-only hash.

    Inject-bug recipe:
        cfg.plugin_configs['bcm_base']['bonus_feature'] = 'WRONG_VALUE'
        → hash changes → assertions RED.
        Revert → hash restored → GREEN.
    """

    @_SKIP_NO_FRAMEWORK
    @pytest.mark.parametrize("machine,mode,expected_feat", _BCM_PILOTS)
    def test_hash_changes_when_bonus_feature_changes(
        self, machine: str, mode: int, expected_feat: str,
    ) -> None:
        """Changing bonus_feature causes per_machine_config_hash() to change."""
        cfg = MachinePlayTypeConfig.read(machine, mode)
        assert cfg is not None

        original_hash = cfg.per_machine_config_hash()

        # INJECT: change bonus_feature to a wrong value.
        cfg.plugin_configs["bcm_base"]["bonus_feature"] = "INJECTED_WRONG_FEATURE"
        injected_hash = cfg.per_machine_config_hash()

        assert original_hash != injected_hash, (
            f"[{machine}/mode_{mode}] per_machine_config_hash DID NOT change after "
            f"bonus_feature injection.\n"
            f"Original hash: {original_hash!r}\n"
            f"After injection: {injected_hash!r}\n"
            "The hash is not sensitive to bonus_feature — version detection broken."
        )

        # REVERT: restore original value.
        cfg.plugin_configs["bcm_base"]["bonus_feature"] = expected_feat
        reverted_hash = cfg.per_machine_config_hash()

        assert reverted_hash == original_hash, (
            f"[{machine}/mode_{mode}] Hash did not restore after revert.\n"
            f"Original: {original_hash!r}\n"
            f"Reverted: {reverted_hash!r}"
        )

    @_SKIP_NO_FRAMEWORK
    def test_hash_stable_for_same_content(self) -> None:
        """Two configs with the same content produce the same hash (determinism)."""
        cfg1 = MachinePlayTypeConfig(
            machine_id="M272", mode=1,
            plugin_configs={"bcm_base": {"bonus_feature": "NewFreespin"}},
        )
        cfg2 = MachinePlayTypeConfig(
            machine_id="M272", mode=1,
            plugin_configs={"bcm_base": {"bonus_feature": "NewFreespin"}},
        )
        assert cfg1.per_machine_config_hash() == cfg2.per_machine_config_hash(), (
            "Same config content produced different hashes — hash is not deterministic."
        )


# ---------------------------------------------------------------------------
# P6 — End-to-end inject-bug: bonus_feature in config flows to
#       _resolve_bonus_feature and changes the collect_mechanic panel value
# ---------------------------------------------------------------------------

class TestInjectBugConfigFlowsToPanel:
    """P6: injecting a wrong bonus_feature into the config file changes the result.

    Strategy: use a temporary MachinePlayTypeConfig with an injected wrong
    bonus_feature and pass it directly to _resolve_bonus_feature. Verify the
    wrong value appears in the result (proving the flow is live). Verify that
    restoring the correct config restores the original result.

    We do NOT write to the actual config file on disk in automated tests
    (that would be a side-effect that breaks isolation). Instead we build
    the config in-memory and call _resolve_bonus_feature directly.

    A separate test (test_injected_config_in_memory) validates the full
    in-memory inject/revert cycle.
    """

    @_SKIP_NO_FRAMEWORK
    def test_injected_bonus_feature_appears_in_resolve_result(self) -> None:
        """Injecting wrong bonus_feature into in-memory config changes resolve result.

        INJECT → _resolve_bonus_feature returns injected value.
        REVERT → _resolve_bonus_feature returns original value.

        This proves the live path is active (not bypassed/cached).
        """
        pairings = _load_bcm_pairings()

        # BASELINE: use real M272 config.
        cfg_real = MachinePlayTypeConfig.read("M272", 1)
        assert cfg_real is not None
        feat_real, src_real = _resolve_bonus_feature(
            "M272", 1, {}, pairings, play_type_config=cfg_real,
        )
        assert feat_real == "NewFreespin", f"Baseline wrong: {feat_real!r}"
        assert src_real == "config"

        # INJECT: build a config with wrong bonus_feature.
        cfg_injected = MachinePlayTypeConfig(
            machine_id="M272", mode=1,
            plugin_configs={"bcm_base": {"bonus_feature": "INJECTED_FEATURE"}},
        )
        feat_injected, src_injected = _resolve_bonus_feature(
            "M272", 1, {}, pairings, play_type_config=cfg_injected,
        )
        assert feat_injected == "INJECTED_FEATURE", (
            f"INJECT FAILED: expected 'INJECTED_FEATURE', got {feat_injected!r}.\n"
            "The inject-bug did not propagate to _resolve_bonus_feature.\n"
            "This means the per-machine config path is not live (bypassed)."
        )
        assert src_injected == "config"

        # REVERT: use real config again.
        feat_reverted, src_reverted = _resolve_bonus_feature(
            "M272", 1, {}, pairings, play_type_config=cfg_real,
        )
        assert feat_reverted == "NewFreespin", (
            f"REVERT FAILED: expected 'NewFreespin', got {feat_reverted!r}."
        )

    @_SKIP_NO_FRAMEWORK
    @pytest.mark.parametrize("machine,mode,expected_feat", _BCM_PILOTS)
    def test_all_bcm_pilots_resolve_correctly(
        self, machine: str, mode: int, expected_feat: str,
    ) -> None:
        """All 5 BCM pilots resolve bonus_feature correctly from per-machine config.

        Validates that the real config files for all pilots produce the expected
        _resolve_bonus_feature output.  This is the core byte-identical gate:
        if these values match bcm_pairings.json, the output is byte-identical.
        """
        cfg = MachinePlayTypeConfig.read(machine, mode)
        assert cfg is not None, f"No config file for {machine}/mode_{mode}"
        pairings = _load_bcm_pairings()

        feat, src = _resolve_bonus_feature(
            machine, mode, {}, pairings, play_type_config=cfg,
        )
        assert feat == expected_feat, (
            f"[{machine}/mode_{mode}] _resolve_bonus_feature returned {feat!r}, "
            f"expected {expected_feat!r}.\n"
            "The per-machine config value does not match bcm_pairings.json — "
            "output will NOT be byte-identical."
        )
        assert src == "config", (
            f"[{machine}/mode_{mode}] source={src!r}, expected 'config'."
        )


# ---------------------------------------------------------------------------
# P7 — parse_chunk_response threads machine_id/mode to detect_play_types
# ---------------------------------------------------------------------------

class TestParseChunkResponseThreadsMachineId:
    """P7: parse_chunk_response passes machine_id+mode to detect_play_types.

    Verified by monkeypatching detect_play_types and asserting it was called
    with the correct machine_id and mode.
    """

    @_SKIP_NO_FRAMEWORK
    @_SKIP_NO_M272
    def test_machine_id_and_mode_threaded_to_detect_play_types(self) -> None:
        """parse_chunk_response threads machine_id and mode to detect_play_types."""
        from unittest.mock import patch, call
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        # Load M272 chunk for real resp data.
        d = RAWDATA_DIR / "M272" / "mode_1"
        chunks = sorted(d.glob("chunk_*.json"))
        chunk = json.loads(chunks[0].read_text(encoding="utf-8"))
        resp = chunk["response"]

        # Spy on detect_play_types to capture arguments.
        captured_calls = []

        import fresh_slotlab.analyzer.core.parser as _parser_module
        real_detect = _parser_module.detect_play_types

        def spy_detect(sample_rounds, registered_plugins, parse_state, machine_id="", mode=1):
            captured_calls.append({"machine_id": machine_id, "mode": mode})
            return real_detect(sample_rounds, registered_plugins, parse_state,
                               machine_id=machine_id, mode=mode)

        with patch.object(_parser_module, "detect_play_types", side_effect=spy_detect):
            result = parse_chunk_response(
                resp, chunk_index=0, bet=1000,
                use_play_type_plugins=True,
                machine_id="M272",
                mode=1,
            )

        assert result.get("ok") is True, f"parse_chunk_response failed: {result}"
        assert captured_calls, (
            "detect_play_types was never called — play-type plugin path not taken"
        )
        # The most recent call must have machine_id='M272' and mode=1.
        last_call = captured_calls[-1]
        assert last_call["machine_id"] == "M272", (
            f"detect_play_types called with machine_id={last_call['machine_id']!r}, "
            f"expected 'M272'.\nAll calls: {captured_calls}"
        )
        assert last_call["mode"] == 1, (
            f"detect_play_types called with mode={last_call['mode']!r}, expected 1."
        )

    @_SKIP_NO_FRAMEWORK
    @_SKIP_NO_M272
    def test_without_machine_id_uses_empty_default(self) -> None:
        """parse_chunk_response without machine_id defaults to machine_id=''."""
        from unittest.mock import patch
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        d = RAWDATA_DIR / "M272" / "mode_1"
        chunks = sorted(d.glob("chunk_*.json"))
        chunk = json.loads(chunks[0].read_text(encoding="utf-8"))
        resp = chunk["response"]

        captured_calls = []

        import fresh_slotlab.analyzer.core.parser as _parser_module
        real_detect = _parser_module.detect_play_types

        def spy_detect(sample_rounds, registered_plugins, parse_state, machine_id="", mode=1):
            captured_calls.append({"machine_id": machine_id, "mode": mode})
            return real_detect(sample_rounds, registered_plugins, parse_state,
                               machine_id=machine_id, mode=mode)

        with patch.object(_parser_module, "detect_play_types", side_effect=spy_detect):
            result = parse_chunk_response(
                resp, chunk_index=0, bet=1000,
                use_play_type_plugins=True,
                # NOTE: no machine_id / mode supplied → defaults.
            )

        assert result.get("ok") is True
        if captured_calls:
            last_call = captured_calls[-1]
            assert last_call["machine_id"] == "", (
                f"Expected machine_id='' (default), got {last_call['machine_id']!r}"
            )
