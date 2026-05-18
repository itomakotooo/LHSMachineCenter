"""fresh_slotlab.analyzer — plugin-style analyzer framework.

Package marker only. No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.

Sub-modules:
  features/_base    — AnalyzerFeature ABC (04_v5 §5.2 verbatim; Round 2)
  versioning        — compute_effective_analyzer_version()
  feature_registry  — ALL_FEATURES list + register() + get_features_for_machine()

Deprecated (Round 1, kept for backward compat during test migration):
  feature_protocol  — old @runtime_checkable Protocol (NAME/applies_to/aggregate/finalize)
                      Round 2 replaces this with features/_base.py ABC.
                      Will be removed once impl-tester round-2 test migration completes.
"""
