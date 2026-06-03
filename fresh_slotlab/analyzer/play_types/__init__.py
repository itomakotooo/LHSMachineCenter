"""fresh_slotlab.analyzer.play_types — carve library for per-mechanic logic.

Phase D (2026-06-03): the ST-primary play-type plugin framework
(_base / _claim / _detector / _machine_config / _plugin / _probe / bcm_base /
play_type_registry + configs/play_type_configs/) has been deleted.  Only the
two genuine function carves remain:

  bcm_cycle   — BCM-cycle detection helpers (compute_robot_cycle_peaks,
                detect_cycle_peak).  NOT in the base_hash closure.
  wild_nudge  — Wild-nudge round classifier (is_wild_nudge_round).
                NOT in the base_hash closure.

Consumers import the carve submodules directly:
  from fresh_slotlab.analyzer.play_types.bcm_cycle import ...
  from fresh_slotlab.analyzer.play_types.wild_nudge import ...

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""
