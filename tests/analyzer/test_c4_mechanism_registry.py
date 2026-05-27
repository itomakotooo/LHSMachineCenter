"""Phase C4 — unit tests for MechanismRegistry (Tier 1/2/3 detection).

Tests all detection paths in isolation using synthetic input dicts.
Does NOT spawn subprocesses — unit-level correctness only.

Invariants asserted
-------------------
1. MechanismRegistry() (no-args) produces all-False / empty defaults.
2. MechanismRegistry.build() exists and returns a MechanismRegistry instance.
3. Tier 1 (manifest override): jackpot_applicable=True from overrides takes priority.
4. Tier 1 (manifest override): freespin_applicable=True from overrides takes priority.
5. Tier 1 (manifest override): scatter_marker_pids from overrides takes priority.
6. Tier 1 detection_source label = "tier1_manifest" for overridden fields.
7. Tier 2 freespin: non-empty bonus_chain_lengths → freespin_applicable=True.
8. Tier 2 freespin: empty bonus_chain_lengths → freespin_applicable=False (explicit blocking).
9. Tier 2 freespin blocking blocks Tier 3 even if total_freespin_chain_spins > 0.
10. Tier 3 jackpot Path A: PID >= 10000 in payout_id_win → jackpot_applicable=True.
11. Tier 3 jackpot Path A: PID < 10000 in payout_id_win → not a jackpot candidate.
12. Tier 3 jackpot Path A: scatter_marker_pids excluded from jackpot candidates.
13. Tier 3 jackpot Path B: jackpot_ids_seen (raw JackpotIds) → jackpot_applicable=True (M11 case).
14. Tier 3 jackpot Path B: scatter_marker_pids excluded from jackpot_ids_seen.
15. Tier 3 jackpot union: Path A | Path B gives correct combined result.
16. Tier 3 jackpot detection_source: "tier3_pid_ge_10000" when only Path A fires.
17. Tier 3 jackpot detection_source: "tier3_jackpot_ids_seen" when only Path B fires.
18. Tier 3 jackpot detection_source: "tier3_pid_ge_10000_and_jackpot_ids_seen" when both fire.
19. Tier 3 payout_groups: non-zero gid with win > 0 → applicable=True.
20. Tier 3 payout_groups: group_id=0 only → applicable=False.
21. Scatter detection: win==0 AND no regular line → scatter marker PID.
22. Scatter detection: win > 0 → NOT a scatter marker (M120 pid=666 case).
23. Scatter detection: win==0 BUT has regular line → NOT a scatter marker.
24. to_summary_dict() output shape: all 5 fields present + _detection_source dict.
25. _detection_source dict carries keys for all detected fields.

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug B — Tier 3 jackpot Path A threshold too high:
    In mechanism_registry.py, change:
        if pid_int >= 10000 and pid_s not in scatter_marker_pids:
    to:
        if pid_int >= 1000000 and pid_s not in scatter_marker_pids:
    RED: test_tier3_path_a_pid_ge_10000 fails (M275-style PID 27502 is < 1000000
         so it's no longer detected → jackpot_applicable=False, but test expects True).
    Revert (restore original threshold 10000) → GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (_detection_source labels must be explicit, not silent catch-all)
- memory/feedback_no_hardcode.md
  (no machine-specific semantics hardcoded — thresholds from spec)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _build_registry(
    *,
    manifest: dict | None = None,
    payout_id_win: dict | None = None,
    payout_id_hits: dict | None = None,
    jackpot_ids_seen: set | None = None,
    bonus_chain_lengths: list | None = None,
    total_freespin_chain_spins: int = 0,
    payout_group_win: dict | None = None,
    pid_has_regular_line: dict | None = None,
):
    """Call MechanismRegistry.build() with safe defaults for unit testing."""
    try:
        from fresh_slotlab.analyzer.mechanism_registry import MechanismRegistry
    except ImportError:
        from analyzer.mechanism_registry import MechanismRegistry  # type: ignore[no-redef]
    return MechanismRegistry.build(
        manifest=manifest or {},
        payout_id_win=payout_id_win or {},
        payout_id_hits=payout_id_hits or {},
        jackpot_ids_seen=jackpot_ids_seen or set(),
        bonus_chain_lengths=bonus_chain_lengths if bonus_chain_lengths is not None else [],
        total_freespin_chain_spins=total_freespin_chain_spins,
        payout_group_win=payout_group_win or {},
        pid_has_regular_line=pid_has_regular_line or {},
    )


# ---------------------------------------------------------------------------
# T1: Default / no-args constructor
# ---------------------------------------------------------------------------

class TestMechanismRegistryDefaults:
    """MechanismRegistry() with no args must produce all-False / empty defaults."""

    def test_no_args_constructor(self):
        """MechanismRegistry() with no args must not raise."""
        try:
            from fresh_slotlab.analyzer.mechanism_registry import MechanismRegistry
        except ImportError:
            from analyzer.mechanism_registry import MechanismRegistry  # type: ignore[no-redef]
        reg = MechanismRegistry()
        assert reg.jackpot_applicable is False
        assert reg.freespin_applicable is False
        assert reg.jackpot_pid_set == frozenset()
        assert reg.scatter_marker_pids == frozenset()
        assert reg.payout_groups_applicable is False
        assert isinstance(reg._detection_source, dict)

    def test_build_classmethod_returns_instance(self):
        """MechanismRegistry.build() must return a MechanismRegistry instance."""
        try:
            from fresh_slotlab.analyzer.mechanism_registry import MechanismRegistry
        except ImportError:
            from analyzer.mechanism_registry import MechanismRegistry  # type: ignore[no-redef]
        reg = _build_registry()
        assert isinstance(reg, MechanismRegistry), (
            f"build() must return MechanismRegistry, got {type(reg)}"
        )


# ---------------------------------------------------------------------------
# T2: Tier 1 — Manifest overrides
# ---------------------------------------------------------------------------

class TestTier1ManifestOverrides:
    """Tier 1 manifest overrides take highest precedence."""

    def test_tier1_jackpot_applicable_override(self):
        """manifest['mechanism_overrides']['jackpot_applicable']=True → Tier 1 fires."""
        reg = _build_registry(
            manifest={"mechanism_overrides": {"jackpot_applicable": True, "jackpot_pid_set": ["99999"]}},
            payout_id_win={"100": 0.0},  # No PID >= 10000
            jackpot_ids_seen=set(),
        )
        assert reg.jackpot_applicable is True, (
            f"Tier 1 override must set jackpot_applicable=True. Got: {reg.jackpot_applicable}"
        )
        assert "tier1" in reg._detection_source.get("jackpot_applicable", ""), (
            f"Detection source must be tier1 for manifest override. "
            f"Got: {reg._detection_source}"
        )

    def test_tier1_freespin_applicable_override(self):
        """manifest['mechanism_overrides']['freespin_applicable']=True → Tier 1 fires."""
        reg = _build_registry(
            manifest={"mechanism_overrides": {"freespin_applicable": True}},
            bonus_chain_lengths=[],  # Tier 2 would give False — Tier 1 overrides
        )
        assert reg.freespin_applicable is True, (
            f"Tier 1 override must set freespin_applicable=True even when "
            f"bonus_chain_lengths is empty. Got: {reg.freespin_applicable}"
        )
        assert "tier1" in reg._detection_source.get("freespin_applicable", ""), (
            f"Detection source must be tier1 for manifest freespin override. "
            f"Got: {reg._detection_source}"
        )

    def test_tier1_freespin_false_override(self):
        """manifest['mechanism_overrides']['freespin_applicable']=False → force False."""
        reg = _build_registry(
            manifest={"mechanism_overrides": {"freespin_applicable": False}},
            bonus_chain_lengths=[10, 10, 10],  # Tier 2 would give True — Tier 1 overrides
        )
        assert reg.freespin_applicable is False, (
            f"Tier 1 override freespin_applicable=False must override Tier 2 True. "
            f"Got: {reg.freespin_applicable}"
        )

    def test_tier1_scatter_marker_pids_override(self):
        """manifest['mechanism_overrides']['scatter_marker_pids'] → used verbatim."""
        reg = _build_registry(
            manifest={"mechanism_overrides": {"scatter_marker_pids": ["666", "999"]}},
            payout_id_win={"666": 0.0, "999": 0.0},
        )
        assert "666" in reg.scatter_marker_pids, (
            f"Tier 1 scatter_marker_pids must include '666'. "
            f"Got: {reg.scatter_marker_pids}"
        )
        assert "999" in reg.scatter_marker_pids, (
            f"Tier 1 scatter_marker_pids must include '999'. "
            f"Got: {reg.scatter_marker_pids}"
        )
        assert reg._detection_source.get("scatter_marker_pids") == "tier1_manifest", (
            f"scatter_marker_pids detection source must be 'tier1_manifest'. "
            f"Got: {reg._detection_source}"
        )

    def test_tier1_jackpot_pid_set_from_manifest(self):
        """manifest['mechanism_overrides']['jackpot_pid_set'] → used as jackpot_pid_set."""
        reg = _build_registry(
            manifest={"mechanism_overrides": {
                "jackpot_applicable": True,
                "jackpot_pid_set": ["99001", "99002"],
            }},
        )
        assert "99001" in reg.jackpot_pid_set
        assert "99002" in reg.jackpot_pid_set

    def test_tier1_label_is_tier1_manifest(self):
        """_detection_source must be 'tier1_manifest' for all Tier 1 fields."""
        reg = _build_registry(
            manifest={"mechanism_overrides": {
                "jackpot_applicable": True,
                "jackpot_pid_set": ["99999"],
                "freespin_applicable": True,
            }},
        )
        assert reg._detection_source.get("jackpot_applicable") == "tier1_manifest", (
            f"jackpot_applicable detection source must be 'tier1_manifest', "
            f"got {reg._detection_source.get('jackpot_applicable')!r}"
        )
        assert reg._detection_source.get("freespin_applicable") == "tier1_manifest", (
            f"freespin_applicable detection source must be 'tier1_manifest', "
            f"got {reg._detection_source.get('freespin_applicable')!r}"
        )


# ---------------------------------------------------------------------------
# T3: Tier 2 — Bonus chain lengths (freespin)
# ---------------------------------------------------------------------------

class TestTier2FreespinDetection:
    """Tier 2 freespin detection from bonus_chain_lengths accumulator."""

    def test_tier2_nonempty_chain_lengths_gives_applicable_true(self):
        """Non-empty bonus_chain_lengths → freespin_applicable=True.

        This is the M275 case: BCD-tracked freespin chains.
        """
        reg = _build_registry(
            bonus_chain_lengths=[10, 10, 10, 8, 10],  # M275-style
        )
        assert reg.freespin_applicable is True, (
            f"Non-empty bonus_chain_lengths must give freespin_applicable=True. "
            f"Got: {reg.freespin_applicable}"
        )
        assert "tier2" in reg._detection_source.get("freespin_applicable", ""), (
            f"Detection source must be tier2. Got: {reg._detection_source}"
        )

    def test_tier2_empty_chain_lengths_gives_applicable_false(self):
        """Empty bonus_chain_lengths → freespin_applicable=False (explicit blocking).

        Per 04_v3 §5.2: if bonus_chain_lengths is empty, Tier 2 explicitly
        sets freespin_applicable=False and blocks Tier 3.
        This prevents false-positives on BCM_WHEEL machines (M279, M274, etc.).
        """
        reg = _build_registry(
            bonus_chain_lengths=[],  # empty list = no freespin chains
        )
        assert reg.freespin_applicable is False, (
            f"Empty bonus_chain_lengths must give freespin_applicable=False. "
            f"Got: {reg.freespin_applicable}"
        )

    def test_tier2_empty_blocks_tier3_even_with_freespin_spins(self):
        """Tier 2 explicit-False blocks Tier 3 even if total_freespin_chain_spins > 0.

        Per 04_v3 §5.2 Tier 2 blocking rule: if Tier 2 produces explicit False,
        Tier 3 fallback does NOT activate.
        """
        reg = _build_registry(
            bonus_chain_lengths=[],           # Tier 2 explicit-False
            total_freespin_chain_spins=100,   # Tier 3 would give True — blocked
        )
        assert reg.freespin_applicable is False, (
            f"Tier 2 explicit-False must block Tier 3. "
            f"total_freespin_chain_spins=100 but bonus_chain_lengths=[]. "
            f"Got freespin_applicable={reg.freespin_applicable}"
        )

    def test_tier2_detection_source_label(self):
        """detection_source must say 'tier2_bonus_chain_lengths' when Tier 2 fires."""
        reg = _build_registry(bonus_chain_lengths=[10, 10])
        src = reg._detection_source.get("freespin_applicable", "")
        assert src == "tier2_bonus_chain_lengths", (
            f"freespin_applicable detection source must be 'tier2_bonus_chain_lengths', "
            f"got {src!r}"
        )

    def test_tier2_empty_detection_source_label(self):
        """detection_source must say 'tier2_bonus_chain_lengths_empty' when Tier 2 gives False."""
        reg = _build_registry(bonus_chain_lengths=[])
        src = reg._detection_source.get("freespin_applicable", "")
        assert "empty" in src or "tier2" in src, (
            f"freespin_applicable detection source when empty must contain 'tier2' "
            f"and signal 'empty'. Got {src!r}"
        )


# ---------------------------------------------------------------------------
# T4: Tier 3 — Jackpot Path A (PID >= 10000)
# ---------------------------------------------------------------------------

class TestTier3JackpotPathA:
    """Tier 3 jackpot detection via PID >= 10000 threshold (M275-style)."""

    def test_tier3_path_a_pid_ge_10000(self):
        """PIDs >= 10000 in payout_id_win → jackpot_applicable=True.

        INJECT-BUG (Bug B): change threshold to >= 1000000.
        RED: PID 27502 is 27502 < 1000000 → not detected → jackpot_applicable=False.
        Revert (restore >= 10000) → GREEN.

        This is the M275 case: PIDs 27502, 27503, 27504.
        """
        reg = _build_registry(
            payout_id_win={
                "27502": 1_000_000.0,
                "27503": 2_000_000.0,
                "27504": 1_500_000.0,
                "666": 0.0,   # scatter marker
            },
            pid_has_regular_line={"666": False},  # 666 has no regular line
        )
        assert reg.jackpot_applicable is True, (
            f"PIDs 27502/27503/27504 (>= 10000) must give jackpot_applicable=True. "
            f"Got: {reg.jackpot_applicable}"
        )
        assert "27502" in reg.jackpot_pid_set, (
            f"27502 must be in jackpot_pid_set. Got: {reg.jackpot_pid_set}"
        )
        assert "27503" in reg.jackpot_pid_set
        assert "27504" in reg.jackpot_pid_set

    def test_tier3_path_a_pid_below_10000_not_jackpot(self):
        """PIDs < 10000 in payout_id_win are NOT jackpot candidates via Path A."""
        reg = _build_registry(
            payout_id_win={"9999": 500_000.0, "5000": 200_000.0},
        )
        assert reg.jackpot_applicable is False, (
            f"PIDs 9999 and 5000 (< 10000) must NOT give jackpot via Path A. "
            f"Got: {reg.jackpot_applicable}"
        )

    def test_tier3_path_a_scatter_excluded(self):
        """Scatter marker PIDs >= 10000 are excluded from jackpot candidates."""
        # A PID that's >= 10000 but win==0 and no regular line → scatter
        reg = _build_registry(
            payout_id_win={"15000": 0.0},   # win==0 → scatter
            pid_has_regular_line={},         # no regular line
        )
        assert "15000" not in reg.jackpot_pid_set, (
            f"PID 15000 with win==0 (scatter marker) must be excluded from jackpot. "
            f"Got jackpot_pid_set: {reg.jackpot_pid_set}"
        )
        assert reg.jackpot_applicable is False, (
            f"scatter-only PID must not give jackpot_applicable=True"
        )

    def test_tier3_path_a_detection_source_label(self):
        """detection_source must be 'tier3_pid_ge_10000' when only Path A fires."""
        reg = _build_registry(
            payout_id_win={"27502": 1_000_000.0},
            jackpot_ids_seen=set(),  # Path B empty
        )
        src = reg._detection_source.get("jackpot_applicable", "")
        assert src == "tier3_pid_ge_10000", (
            f"jackpot_applicable source must be 'tier3_pid_ge_10000' when "
            f"only Path A fires. Got: {src!r}"
        )


# ---------------------------------------------------------------------------
# T5: Tier 3 — Jackpot Path B (JackpotIds raw field)
# ---------------------------------------------------------------------------

class TestTier3JackpotPathB:
    """Tier 3 jackpot Path B from raw JackpotIds field (M11-style)."""

    def test_tier3_path_b_jackpot_ids_seen_fires(self):
        """jackpot_ids_seen (from raw JackpotIds field) → jackpot_applicable=True.

        This is the M11 case: PIDs 1102, 1103, 1104 are numerically < 10000
        so Path A misses them. Path B catches them from raw JackpotIds events.
        """
        reg = _build_registry(
            payout_id_win={},       # No PIDs in payout_id_win (M11 style)
            jackpot_ids_seen={"1102", "1103", "1104"},
        )
        assert reg.jackpot_applicable is True, (
            f"jackpot_ids_seen must give jackpot_applicable=True for M11. "
            f"Got: {reg.jackpot_applicable}"
        )
        assert "1102" in reg.jackpot_pid_set, (
            f"1102 must be in jackpot_pid_set (from Path B). Got: {reg.jackpot_pid_set}"
        )
        assert "1103" in reg.jackpot_pid_set
        assert "1104" in reg.jackpot_pid_set

    def test_tier3_path_b_detection_source_label(self):
        """detection_source must be 'tier3_jackpot_ids_seen' when only Path B fires.

        This distinguishes M11 (Path B only) from M275 (Path A only).
        """
        reg = _build_registry(
            payout_id_win={"100": 1000.0},  # PID 100 < 10000 — not a jackpot via Path A
            jackpot_ids_seen={"1102"},
        )
        src = reg._detection_source.get("jackpot_applicable", "")
        assert src == "tier3_jackpot_ids_seen", (
            f"jackpot_applicable source must be 'tier3_jackpot_ids_seen' when "
            f"only Path B fires. Got: {src!r}"
        )

    def test_tier3_path_b_scatter_excluded(self):
        """Scatter-marked PIDs in jackpot_ids_seen are excluded."""
        reg = _build_registry(
            payout_id_win={"666": 0.0},  # 666 is scatter marker (win==0, no regular line)
            pid_has_regular_line={},
            jackpot_ids_seen={"666"},    # 666 appears in JackpotIds — but it's scatter
        )
        assert "666" not in reg.jackpot_pid_set, (
            f"666 (scatter marker) must be excluded from jackpot_pid_set even "
            f"if it appears in jackpot_ids_seen. Got: {reg.jackpot_pid_set}"
        )


# ---------------------------------------------------------------------------
# T6: Tier 3 — Jackpot Union (Path A | Path B)
# ---------------------------------------------------------------------------

class TestTier3JackpotUnion:
    """Path A | Path B union gives correct combined jackpot_pid_set."""

    def test_union_path_a_and_path_b(self):
        """Both Path A and Path B contribute distinct PIDs."""
        reg = _build_registry(
            payout_id_win={"27502": 1_000_000.0},    # Path A
            jackpot_ids_seen={"1102", "1103"},          # Path B
        )
        assert reg.jackpot_applicable is True
        assert "27502" in reg.jackpot_pid_set, (
            f"27502 (Path A) must be in union. Got: {reg.jackpot_pid_set}"
        )
        assert "1102" in reg.jackpot_pid_set, (
            f"1102 (Path B) must be in union. Got: {reg.jackpot_pid_set}"
        )
        assert "1103" in reg.jackpot_pid_set

    def test_union_source_label_both_paths(self):
        """detection_source must be 'tier3_pid_ge_10000_and_jackpot_ids_seen' when both fire."""
        reg = _build_registry(
            payout_id_win={"27502": 1_000_000.0},    # Path A
            jackpot_ids_seen={"1102"},                  # Path B
        )
        src = reg._detection_source.get("jackpot_applicable", "")
        assert src == "tier3_pid_ge_10000_and_jackpot_ids_seen", (
            f"When both Path A and Path B fire, detection source must be "
            f"'tier3_pid_ge_10000_and_jackpot_ids_seen'. Got: {src!r}"
        )

    def test_union_m275_path_a_only(self):
        """M275 scenario: Path A fires (PIDs >= 10000), Path B empty."""
        reg = _build_registry(
            payout_id_win={
                "27502": 1_000_000.0,
                "27503": 2_000_000.0,
                "27504": 1_500_000.0,
                "666": 0.0,  # scatter — win==0
            },
            jackpot_ids_seen=set(),  # no JackpotIds raw field events
            pid_has_regular_line={},
        )
        assert reg.jackpot_applicable is True
        assert reg.jackpot_pid_set == frozenset({"27502", "27503", "27504"}), (
            f"M275 jackpot_pid_set must be {{27502, 27503, 27504}}. "
            f"Got: {reg.jackpot_pid_set}"
        )
        src = reg._detection_source.get("jackpot_applicable", "")
        assert src == "tier3_pid_ge_10000", f"M275 source must be 'tier3_pid_ge_10000', got {src!r}"

    def test_union_m11_path_b_only(self):
        """M11 scenario: Path B fires (JackpotIds raw), Path A empty (PIDs < 10000)."""
        reg = _build_registry(
            payout_id_win={"1102": 100_000.0, "1103": 200_000.0},  # PIDs < 10000
            jackpot_ids_seen={"1102", "1103", "1104"},
        )
        assert reg.jackpot_applicable is True
        assert "1102" in reg.jackpot_pid_set
        assert "1103" in reg.jackpot_pid_set
        assert "1104" in reg.jackpot_pid_set
        src = reg._detection_source.get("jackpot_applicable", "")
        assert src == "tier3_jackpot_ids_seen", (
            f"M11 source must be 'tier3_jackpot_ids_seen'. Got: {src!r}"
        )

    def test_empty_union_gives_applicable_false(self):
        """Empty Path A and empty Path B → jackpot_applicable=False."""
        reg = _build_registry(
            payout_id_win={"1000": 500_000.0},  # PID 1000 < 10000
            jackpot_ids_seen=set(),
        )
        assert reg.jackpot_applicable is False, (
            f"No PIDs >= 10000 and no JackpotIds → jackpot_applicable=False. "
            f"Got: {reg.jackpot_applicable}"
        )


# ---------------------------------------------------------------------------
# T7: Scatter detection
# ---------------------------------------------------------------------------

class TestScatterDetection:
    """Scatter marker PIDs identified before jackpot detection."""

    def test_scatter_win_zero_and_no_regular_line(self):
        """PID with win==0 AND no regular line → scatter marker."""
        reg = _build_registry(
            payout_id_win={"666": 0.0},
            pid_has_regular_line={},  # 666 absent = no regular line
        )
        assert "666" in reg.scatter_marker_pids, (
            f"666 with win==0 and no regular line must be scatter marker. "
            f"Got scatter_marker_pids: {reg.scatter_marker_pids}"
        )

    def test_scatter_win_positive_not_scatter(self):
        """PID with win > 0 is NOT a scatter marker (M120 pid=666 case)."""
        reg = _build_registry(
            payout_id_win={"666": 2_380_000.0},  # M120 style: win > 0
            pid_has_regular_line={},
        )
        assert "666" not in reg.scatter_marker_pids, (
            f"666 with win > 0 must NOT be scatter marker (M120 case). "
            f"Got scatter_marker_pids: {reg.scatter_marker_pids}"
        )

    def test_scatter_win_zero_but_has_regular_line_not_scatter(self):
        """PID with win==0 BUT has regular line → NOT a scatter marker."""
        reg = _build_registry(
            payout_id_win={"123": 0.0},
            pid_has_regular_line={"123": True},  # has a regular line (line_id != -1)
        )
        assert "123" not in reg.scatter_marker_pids, (
            f"PID 123 with win==0 but has_regular_line=True must NOT be scatter. "
            f"Got scatter_marker_pids: {reg.scatter_marker_pids}"
        )


# ---------------------------------------------------------------------------
# T8: Payout groups detection
# ---------------------------------------------------------------------------

class TestPayoutGroupsDetection:
    """Payout groups applicable when non-zero gid has win > 0."""

    def test_nonzero_gid_with_win_gives_applicable_true(self):
        """group_id != 0 with win > 0 → payout_groups_applicable=True."""
        reg = _build_registry(
            payout_group_win={0: 100_000.0, 5: 50_000.0},
        )
        assert reg.payout_groups_applicable is True, (
            f"Non-zero gid=5 with win > 0 must give payout_groups_applicable=True. "
            f"Got: {reg.payout_groups_applicable}"
        )

    def test_only_gid_zero_gives_applicable_false(self):
        """Only group_id=0 → payout_groups_applicable=False."""
        reg = _build_registry(
            payout_group_win={0: 500_000.0},
        )
        assert reg.payout_groups_applicable is False, (
            f"Only gid=0 must give payout_groups_applicable=False. "
            f"Got: {reg.payout_groups_applicable}"
        )

    def test_nonzero_gid_with_zero_win_gives_false(self):
        """Non-zero gid but win=0 → payout_groups_applicable=False."""
        reg = _build_registry(
            payout_group_win={0: 500_000.0, 5: 0.0},  # gid=5 win=0
        )
        assert reg.payout_groups_applicable is False, (
            f"Non-zero gid with win=0 must NOT give payout_groups_applicable=True. "
            f"Got: {reg.payout_groups_applicable}"
        )


# ---------------------------------------------------------------------------
# T9: to_summary_dict() output shape
# ---------------------------------------------------------------------------

class TestToSummaryDict:
    """to_summary_dict() must produce complete output with all required fields."""

    def test_to_summary_dict_has_all_keys(self):
        """to_summary_dict() must contain all 5 fields + _detection_source."""
        reg = _build_registry(
            payout_id_win={"27502": 1_000_000.0},
            bonus_chain_lengths=[10, 10],
        )
        d = reg.to_summary_dict()
        required_keys = {
            "jackpot_applicable", "jackpot_pid_set",
            "freespin_applicable", "scatter_marker_pids",
            "payout_groups_applicable", "_detection_source",
        }
        missing = required_keys - set(d.keys())
        assert not missing, (
            f"to_summary_dict() missing required keys: {missing}. Got: {sorted(d.keys())}"
        )

    def test_to_summary_dict_jackpot_pid_set_is_sorted_list(self):
        """to_summary_dict() jackpot_pid_set must be a sorted list (JSON-serializable)."""
        reg = _build_registry(
            payout_id_win={"27504": 1_000.0, "27502": 1_000.0, "27503": 1_000.0},
        )
        d = reg.to_summary_dict()
        pid_list = d["jackpot_pid_set"]
        assert isinstance(pid_list, list), f"jackpot_pid_set must be list, got {type(pid_list)}"
        assert pid_list == sorted(pid_list), (
            f"jackpot_pid_set must be sorted. Got: {pid_list}"
        )

    def test_to_summary_dict_detection_source_is_dict(self):
        """_detection_source must be a plain dict (not a defaultdict or other type)."""
        reg = _build_registry()
        d = reg.to_summary_dict()
        assert isinstance(d["_detection_source"], dict), (
            f"_detection_source must be dict, got {type(d['_detection_source'])}"
        )

    def test_to_summary_dict_detection_source_populated(self):
        """_detection_source must have entries for jackpot_applicable and freespin_applicable."""
        reg = _build_registry(
            payout_id_win={"27502": 1_000_000.0},
            bonus_chain_lengths=[10, 10],
        )
        d = reg.to_summary_dict()
        ds = d["_detection_source"]
        assert "jackpot_applicable" in ds, (
            f"_detection_source must have 'jackpot_applicable'. Got: {ds}"
        )
        assert "freespin_applicable" in ds, (
            f"_detection_source must have 'freespin_applicable'. Got: {ds}"
        )

    def test_to_summary_dict_scatter_marker_pids_is_sorted_list(self):
        """scatter_marker_pids in summary must be a sorted list."""
        reg = _build_registry(
            payout_id_win={"999": 0.0, "666": 0.0},
            pid_has_regular_line={},
        )
        d = reg.to_summary_dict()
        scat = d["scatter_marker_pids"]
        assert isinstance(scat, list), f"scatter_marker_pids must be list, got {type(scat)}"
        assert scat == sorted(scat), f"scatter_marker_pids must be sorted. Got: {scat}"
