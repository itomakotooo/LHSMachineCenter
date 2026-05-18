"""Stub AnalyzerFeature implementations for testing only.

Per ticket P2-A1 §7 Wave 1 impl note: "4 stub features for smoke tests".
Round 2: rewritten to subclass new ABC per §3 C1 (spec-aligned).

These stubs are NOT registered in ALL_FEATURES at import time.
Tests call ``register(SomeStub())`` explicitly and should clean up
(or use a fresh registry state) to avoid cross-test pollution.

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

from typing import Any, ClassVar

from fresh_slotlab.analyzer.features._base import AnalyzerFeature


# ---------------------------------------------------------------------------
# Stub A — universal (applies to all machines via manifest listing)
# ---------------------------------------------------------------------------

class UniversalStubFeature(AnalyzerFeature):
    """Universal feature stub.  FEATURE_ID = 'universal_stub'.

    Used for ABC isinstance smoke test and registry round-trip testing.
    Manifest lists this as 'universal_stub' for machines that use it.
    """

    FEATURE_ID: ClassVar[str] = "universal_stub"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("universal_stub_count",)
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False

    def extract(self, parse_state, chunk_dict) -> dict:
        return {"count": 1}

    def reduce(self, prev_acc, this_acc) -> Any:
        result = dict(prev_acc)
        result["count"] = result.get("count", 0) + this_acc.get("count", 0)
        return result

    def emit(self, final_acc, summary: dict) -> None:
        summary["universal_stub_count"] = final_acc.get("count", 0)


# ---------------------------------------------------------------------------
# Stub B — machine-specific (declared in M274 manifest only)
# ---------------------------------------------------------------------------

class M274OnlyStubFeature(AnalyzerFeature):
    """M274-specific feature stub.  FEATURE_ID = 'm274_only_stub'.

    Used to test get_features_for_machine manifest-list filtering.
    Only M274's manifest lists 'm274_only_stub' in analyzer_features.
    """

    FEATURE_ID: ClassVar[str] = "m274_only_stub"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("m274_only",)
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False

    def extract(self, parse_state, chunk_dict) -> dict:
        return {"m274_only": True}

    def reduce(self, prev_acc, this_acc) -> Any:
        return this_acc  # last value wins (boolean, not additive)

    def emit(self, final_acc, summary: dict) -> None:
        summary["m274_only"] = final_acc.get("m274_only", False)


# ---------------------------------------------------------------------------
# Stub C — another universal feature (different FEATURE_ID)
# ---------------------------------------------------------------------------

class AnotherUniversalStubFeature(AnalyzerFeature):
    """Second universal stub.  FEATURE_ID = 'another_universal_stub'.

    Tests ordering in get_features_for_machine (registration order stable).
    """

    FEATURE_ID: ClassVar[str] = "another_universal_stub"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("another_universal_stub",)
    SCHEMA_VERSION: ClassVar[int] = 2
    RTP_CONTRIBUTION: ClassVar[bool] = False

    def extract(self, parse_state, chunk_dict) -> dict:
        return {"another_universal_stub": True}

    def reduce(self, prev_acc, this_acc) -> Any:
        return this_acc

    def emit(self, final_acc, summary: dict) -> None:
        summary["another_universal_stub"] = final_acc.get("another_universal_stub", False)


# ---------------------------------------------------------------------------
# Stub D — declared in no manifest (never returned by get_features_for_machine)
# ---------------------------------------------------------------------------

class NeverDeclaredStubFeature(AnalyzerFeature):
    """Feature stub never declared in any manifest.  FEATURE_ID = 'never_declared_stub'.

    Tests that get_features_for_machine returns [] when no manifest lists this feature.
    """

    FEATURE_ID: ClassVar[str] = "never_declared_stub"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ()
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False

    def extract(self, parse_state, chunk_dict) -> dict:
        return {}

    def reduce(self, prev_acc, this_acc) -> Any:
        return {}

    def emit(self, final_acc, summary: dict) -> None:
        pass  # no-op; feature not declared in any manifest
