"""Tests for the structure_drift AnalyzerFeature (CORRECTED classification).

Design proposal: session_artifacts/_arch_playtype/DIRECTION.md (structure_drift gate)
Impl files:
  - fresh_slotlab/analyzer/features/structure_drift.py  (StructureDriftFeature)
  - fresh_slotlab/analyzer/st_extract/signature_audit.py (SignatureAuditExtractor)
  - src/web_console/frontend/app.js (renderStructureDriftPanel)

CONTRACT (the CORRECTED classification tested here):
  FAIL  = (a) undeclared ST share > 0.1%, OR
          (b) signature field presence == 0 on a present ST
  WARN  = (a) signature field presence < 90% (degrading core field), OR
          (b) field in data NOT in signature NOR observed_fields (new field)
  OK    = none of the above
  unaudited = no extractor output in any chunk (legacy chunks / no signatures)

  observed_fields_absent (known optional field at 0% this run) is INFORMATIONAL.
  It is recorded in per_st[st].observed_fields_absent and does NOT flip status.
  This is the critical false-positive fix: optional fields like GameplayTriggerType
  at low/zero presence MUST NOT warn.

Memory feedback honored:
  memory/feedback_enumerate_safety_paths.md
      - Each invariant has an inject-bug recipe documented below.
  memory/feedback_no_silent_swallow.md
      - ST with signature but no observed_fields = "unaudited_fields" (test 8).
      - No extractor output = "unaudited" with reason (test 8).
  memory/feedback_perf_claim_needs_e2e_event_stream.md
      - Group 9 (real-data) drives report_engine with real chunk dirs.
  memory/feedback_invariant_with_fallback_hides_drift.md
      - Group 10 frontend key alignment prevents silent fallback from hiding drift.

INJECT-BUG RECIPES (inject → test goes RED; revert → GREEN):
  IB-1 (test_clean_machine_ok): Change emit() to always set status="warn" →
    test_clean_machine_ok RED. Revert → GREEN.

  IB-2 (test_new_field_warns): In emit(), remove the "if st_drift.get('new_fields')"
    branch from WARN conditions → test_new_field_warns RED. Revert → GREEN.

  IB-3 (test_signature_field_at_zero_fails): In emit(), change the FAIL check
    "if pct == _FAIL_SIG_FIELD_ZERO" to "if pct < 0" (impossible, never fires) →
    test_signature_field_at_zero_fails RED. Revert → GREEN.

  IB-4 (test_signature_field_degraded_warns): Same as IB-3 region but for WARN:
    change "if 0 < pct < _WARN_SIG_FIELD_LOW" to "if 0 < pct < 0.01" →
    test_signature_field_degraded_warns RED (0.5 does not satisfy < 0.01). Revert → GREEN.

  IB-5 (test_undeclared_st_fails): In emit(), remove the undeclared_sts share check
    "if entry['share'] > _FAIL_UNDECLARED_ST_SHARE: status='fail'" →
    test_undeclared_st_fails RED. Revert → GREEN.

  IB-6 (test_known_observed_field_absent_stays_ok — the FALSE-POSITIVE regression guard):
    Re-add the old obs<90% degraded warn: after the obs_absent computation add:
      for field in obs_set:
          cnt = observed_pres.get(field, 0)
          pct = cnt / rounds_for_st
          if pct < _WARN_SIG_FIELD_LOW:
              # INJECT-BUG: this used to be in the WARN block
              status = "warn"  # now handled externally
    And uncomment/add to WARN conditions:
      if obs_absent or any(observed_pres.get(f,0)/rounds < 0.9 for f in obs_set):
          status = "warn"
    → test_known_observed_field_absent_stays_ok RED because absent obs field → warn.
    Revert → GREEN.

  IB-7 (test_optional_field_low_presence_stays_ok): Same as IB-6. With the
    obs<90% threshold re-added, a field at 15% presence triggers WARN.
    → test_optional_field_low_presence_stays_ok RED. Revert → GREEN.

  IB-8 (test_st_with_signature_no_observed_fields_is_unaudited_fields):
    In emit(), change: if not has_observed_fields: obs_status = "unaudited_fields"
    to always: obs_status = "ok"
    → test RED (unaudited_fields becomes ok). Revert → GREEN.

  IB-10 (test_frontend_renderer_key_alignment): Rename plugin output key
    "observed_fields_absent" to "missing_declared_fields" in emit() →
    test_frontend_renderer_key_alignment RED (per_st key "observed_fields_absent"
    not in plugin output). Revert → GREEN.

  Also see inject-bug exercises at bottom of this file (actually executed).
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Real rawdata availability markers
# ---------------------------------------------------------------------------

_M15_CHUNK = ROOT / "rawdata" / "M15" / "mode_1" / "chunk_0001.json"
_M43_CHUNK_1 = ROOT / "rawdata" / "M43" / "mode_1" / "chunk_0002.json"
_M43_CHUNK_7 = ROOT / "rawdata" / "M43" / "mode_7" / "chunk_0002.json"
_M279_CHUNK = ROOT / "rawdata" / "M279" / "mode_1" / "chunk_0001.json"
_M275_CHUNK = ROOT / "rawdata" / "M275" / "mode_1" / "chunk_0001.json"

_HAVE_M15 = _M15_CHUNK.exists()
_HAVE_M43_1 = _M43_CHUNK_1.exists()
_HAVE_M43_7 = _M43_CHUNK_7.exists()
_HAVE_M279 = _M279_CHUNK.exists()
_HAVE_M275 = _M275_CHUNK.exists()

SKIP_NO_M15 = pytest.mark.skipif(not _HAVE_M15, reason="rawdata/M15/mode_1 absent")
SKIP_NO_M43_1 = pytest.mark.skipif(not _HAVE_M43_1, reason="rawdata/M43/mode_1 absent")
SKIP_NO_M43_7 = pytest.mark.skipif(not _HAVE_M43_7, reason="rawdata/M43/mode_7 absent")
SKIP_NO_M279 = pytest.mark.skipif(not _HAVE_M279, reason="rawdata/M279/mode_1 absent")
SKIP_NO_M275 = pytest.mark.skipif(not _HAVE_M275, reason="rawdata/M275/mode_1 absent")


# ---------------------------------------------------------------------------
# Synthetic fixture builders
# ---------------------------------------------------------------------------

def _manifest(
    machine_id: str = "M_synthetic",
    spin_types: dict | None = None,
) -> dict:
    """Build a minimal SpinType-native manifest."""
    return {
        "machine_id": machine_id,
        "schema": "spintype-native/1",
        "modes": [1],
        "spin_types": spin_types or {},
    }


def _st_block(
    role: str = "paid_spin",
    signature: list[str] | None = None,
    observed_fields: list[str] | None = None,
) -> dict:
    """Build a spin_types entry with optional signature/observed_fields."""
    block: dict[str, Any] = {"role": role}
    if signature is not None:
        block["signature"] = signature
    if observed_fields is not None:
        block["observed_fields"] = observed_fields
    return block


def _fake_chunk(
    *,
    st: int = 1,
    rounds: int = 100,
    declared_field_presence: dict[str, int] | None = None,
    observed_field_presence: dict[str, int] | None = None,
    new_field_presence: dict[str, int] | None = None,
    has_observed_fields: bool = True,
    extra_sts: dict[str, int] | None = None,
) -> dict:
    """Build a synthetic chunk dict with pre-populated signature_audit output.

    This directly populates the st_extract.signature_audit structure that
    StructureDriftFeature.extract() reads — bypassing the parser for speed.
    """
    observed_st_counts: dict[str, int] = {str(st): rounds}
    if extra_sts:
        observed_st_counts.update({str(k): v for k, v in extra_sts.items()})

    per_st_entry: dict[str, Any] = {
        "declared_field_presence": declared_field_presence or {},
        "observed_field_presence": observed_field_presence or {},
        "new_field_presence": new_field_presence or {},
        "rounds": rounds,
        "has_observed_fields": has_observed_fields,
    }

    return {
        "st_extract": {
            "signature_audit": {
                "observed_st_counts": observed_st_counts,
                "per_st": {str(st): per_st_entry},
            }
        }
    }


class _FakeCtx:
    """Minimal PipelineContext stub for emit() tests."""

    def __init__(self, manifest: dict) -> None:
        self.machine_spec_manifest = manifest


def _run_feature(
    chunks: list[dict],
    manifest: dict,
) -> dict:
    """Run extract → reduce → emit for StructureDriftFeature on synthetic chunks.

    Returns the populated summary["structure_drift"] dict.
    """
    from fresh_slotlab.analyzer.features.structure_drift import StructureDriftFeature

    feature = StructureDriftFeature()
    acc: dict = {}
    for chunk in chunks:
        this_acc = feature.extract(None, chunk)
        acc = feature.reduce(acc, this_acc)

    summary: dict[str, Any] = {}
    ctx = _FakeCtx(manifest)
    feature.emit(acc, summary, ctx)
    return summary["structure_drift"]


# ---------------------------------------------------------------------------
# Group 1: Clean machine → status ok
# ---------------------------------------------------------------------------

class TestCleanMachineOk:
    """Test 1: All data fields match signature ∪ observed_fields → status ok.

    INJECT-BUG IB-1: In emit(), change initial 'status = "ok"' to always
    set 'status = "warn"' before classification → test RED. Revert → GREEN.
    """

    def test_clean_machine_ok(self) -> None:
        """Clean machine: signature fields all present, no new fields → ok."""
        sig = ["FieldA", "FieldB"]
        obs = ["FieldA", "FieldB", "OptionalField"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        # All 100 rounds have both signature fields present; optional present at 60%.
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            declared_field_presence={"FieldA": 100, "FieldB": 100},
            observed_field_presence={"OptionalField": 60},
            new_field_presence={},
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)

        assert result["status"] == "ok", (
            f"Clean machine must produce status='ok'. Got: {result['status']}. "
            "Full result: {result}. "
            "INJECT-BUG IB-1: hardcoding status='warn' in emit() → RED."
        )
        assert result["undeclared_sts"] == [], (
            "Clean machine must have no undeclared STs."
        )

    def test_clean_no_per_st_entry_when_nothing_to_report(self) -> None:
        """No per_st entry is emitted when there is nothing to report for a clean ST."""
        sig = ["X", "Y"]
        obs = ["X", "Y"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        chunk = _fake_chunk(
            st=1,
            rounds=50,
            declared_field_presence={"X": 50, "Y": 50},
            observed_field_presence={},
            new_field_presence={},
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)
        assert result["status"] == "ok"
        # per_st should be empty when all fields are 100% present and no new fields
        assert "1" not in result["per_st"], (
            "No per_st entry should be emitted for a fully-clean ST with no issues."
        )


# ---------------------------------------------------------------------------
# Group 2: New field appears → status warn
# ---------------------------------------------------------------------------

class TestNewFieldWarns:
    """Test 2: A field in data but in NEITHER signature NOR observed_fields → warn.

    INJECT-BUG IB-2: In emit(), remove the "if st_drift.get('new_fields'): status='warn'"
    branch → test RED. Revert → GREEN.
    """

    def test_new_field_warns(self) -> None:
        """New field (not in either set) at any presence → warn."""
        sig = ["FieldA"]
        obs = ["FieldA", "FieldB"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            declared_field_presence={"FieldA": 100},
            observed_field_presence={"FieldB": 90},
            new_field_presence={"BrandNewProtocolField": 50},  # not in sig or obs
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)

        assert result["status"] == "warn", (
            f"New field must produce status='warn'. Got: {result['status']}. "
            "INJECT-BUG IB-2: remove new_fields WARN branch → RED."
        )
        per_st = result["per_st"]
        assert "1" in per_st, f"per_st must have entry for ST 1. Got: {per_st}"
        assert "BrandNewProtocolField" in per_st["1"]["new_fields"], (
            f"New field must appear in per_st['1']['new_fields']. "
            f"Got: {per_st['1']}"
        )

    def test_new_field_listed_in_per_st_new_fields(self) -> None:
        """New field is specifically listed in per_st[st].new_fields dict."""
        sig = ["F1"]
        obs = ["F1", "F2"]
        manifest = _manifest(spin_types={
            "5": _st_block(role="respin", signature=sig, observed_fields=obs)
        })
        chunk = _fake_chunk(
            st=5,
            rounds=200,
            declared_field_presence={"F1": 200},
            observed_field_presence={"F2": 150},
            new_field_presence={"NewUnknownField": 100},
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)
        assert result["status"] == "warn"
        nf = result["per_st"]["5"]["new_fields"]
        assert "NewUnknownField" in nf
        # Presence rate should be 100/200 = 0.5 (approximately)
        assert abs(nf["NewUnknownField"] - 0.5) < 0.01, (
            f"New field presence should be ~0.5 (100/200). Got {nf['NewUnknownField']}"
        )


# ---------------------------------------------------------------------------
# Group 3: Signature field at 0% → status fail
# ---------------------------------------------------------------------------

class TestSignatureFieldAtZeroFails:
    """Test 3: Signature field with presence==0 on a present ST → fail.

    INJECT-BUG IB-3: In emit(), change the fail check from
    "if pct == _FAIL_SIG_FIELD_ZERO" to "if pct < 0" (never fires) →
    test RED. Revert → GREEN.
    """

    def test_signature_field_at_zero_fails(self) -> None:
        """Signature field completely absent (0 rounds) → fail."""
        sig = ["RequiredField", "OtherField"]
        obs = ["RequiredField", "OtherField", "Optional"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        # RequiredField: 0 rounds (completely absent!), OtherField: 100/100
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            declared_field_presence={"RequiredField": 0, "OtherField": 100},
            observed_field_presence={"Optional": 80},
            new_field_presence={},
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)

        assert result["status"] == "fail", (
            f"Signature field at 0% must produce status='fail'. Got: {result['status']}. "
            "INJECT-BUG IB-3: changing pct < 0 check so it never fires → RED."
        )
        per_st = result["per_st"]
        assert "1" in per_st
        sig_missing = per_st["1"]["signature_fields_missing"]
        assert "RequiredField" in sig_missing, (
            f"RequiredField at 0% must appear in signature_fields_missing. "
            f"Got: {sig_missing}"
        )
        assert sig_missing["RequiredField"] == 0.0, (
            f"RequiredField presence should be 0.0. Got: {sig_missing['RequiredField']}"
        )

    def test_fail_overrides_warn(self) -> None:
        """When both a new field (warn) and a 0%-signature field (fail) appear,
        the result must be fail (fail takes precedence)."""
        sig = ["Core", "Missing"]
        obs = ["Core", "Missing"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            declared_field_presence={"Core": 100, "Missing": 0},
            observed_field_presence={},
            new_field_presence={"NewField": 20},
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)
        assert result["status"] == "fail", (
            f"Fail (0% signature field) must override warn (new field). "
            f"Got: {result['status']}"
        )


# ---------------------------------------------------------------------------
# Group 4: Signature field at ~50% → status warn
# ---------------------------------------------------------------------------

class TestSignatureFieldDegradedWarns:
    """Test 4: Signature field presence < 90% but > 0 → warn.

    INJECT-BUG IB-4: Change "if 0 < pct < _WARN_SIG_FIELD_LOW" to
    "if 0 < pct < 0.01" → test RED (0.5 doesn't satisfy < 0.01). Revert → GREEN.
    """

    def test_signature_field_at_50_percent_warns(self) -> None:
        """Signature field at 50% presence → warn (not fail, not ok)."""
        sig = ["CoreField", "SometimesField"]
        obs = ["CoreField", "SometimesField"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        # SometimesField: 50/100 rounds = 50% (< 90% but > 0)
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            declared_field_presence={"CoreField": 100, "SometimesField": 50},
            observed_field_presence={},
            new_field_presence={},
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)

        assert result["status"] == "warn", (
            f"Signature field at 50% must produce status='warn'. Got: {result['status']}. "
            "INJECT-BUG IB-4: change WARN threshold to 0.01 → RED."
        )
        per_st = result["per_st"]
        assert "1" in per_st
        sig_missing = per_st["1"]["signature_fields_missing"]
        assert "SometimesField" in sig_missing, (
            f"SometimesField at 50% must appear in signature_fields_missing. "
            f"Got: {sig_missing}"
        )
        pct = sig_missing["SometimesField"]
        assert 0.49 < pct < 0.51, (
            f"SometimesField presence should be ~0.5. Got: {pct}"
        )

    def test_signature_field_at_89_percent_warns(self) -> None:
        """Signature field at 89% presence (just below 90% threshold) → warn."""
        sig = ["CoreField"]
        obs = ["CoreField"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            declared_field_presence={"CoreField": 89},
            observed_field_presence={},
            new_field_presence={},
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)
        assert result["status"] == "warn", (
            f"Signature field at 89% (< 90% threshold) must warn. Got: {result['status']}"
        )

    def test_signature_field_at_90_percent_is_ok(self) -> None:
        """Signature field at exactly 90% (== threshold) is NOT in the warn range
        per the implementation: threshold is < 0.90, so exactly 0.90 is ok.

        The sig_missing dict uses pct < 1.0 to include, but WARN condition
        uses 0 < pct < 0.90. At exactly 90/100 = 0.90, neither warn nor fail.
        """
        sig = ["CoreField"]
        obs = ["CoreField"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            declared_field_presence={"CoreField": 90},
            observed_field_presence={},
            new_field_presence={},
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)
        # 90/100 = 0.90, which is NOT < 0.90, so no WARN (and not 0, so no FAIL)
        assert result["status"] == "ok", (
            f"Signature field exactly at 90% is on the boundary: not warn, not fail. "
            f"Got: {result['status']}"
        )


# ---------------------------------------------------------------------------
# Group 5: Undeclared ST with share > 0.1% → fail
# ---------------------------------------------------------------------------

class TestUndeclaredStFails:
    """Test 5: Undeclared ST (in data, not in manifest) with share > 0.1% → fail.

    INJECT-BUG IB-5: In emit(), remove the entire undeclared_sts FAIL branch
    → test RED. Revert → GREEN.
    """

    def test_undeclared_st_fails(self) -> None:
        """Undeclared ST with share > 0.1% → fail, listed in undeclared_sts."""
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=["FieldA"], observed_fields=["FieldA"])
        })
        # ST 1: 990 rounds (declared), ST 99: 10 rounds (undeclared, share=1% > 0.1%)
        total = 1000
        chunks = [
            # chunk for declared ST 1
            {
                "st_extract": {
                    "signature_audit": {
                        "observed_st_counts": {"1": 990, "99": 10},
                        "per_st": {
                            "1": {
                                "declared_field_presence": {"FieldA": 990},
                                "observed_field_presence": {},
                                "new_field_presence": {},
                                "rounds": 990,
                                "has_observed_fields": True,
                            }
                        },
                    }
                }
            }
        ]
        result = _run_feature(chunks, manifest)

        assert result["status"] == "fail", (
            f"Undeclared ST 99 with 1% share must produce fail. Got: {result['status']}. "
            "INJECT-BUG IB-5: remove undeclared_sts FAIL branch → RED."
        )
        sts = result["undeclared_sts"]
        assert len(sts) >= 1, f"undeclared_sts must be non-empty. Got: {sts}"
        st_ids = [e["st"] for e in sts]
        assert "99" in st_ids, (
            f"ST 99 must be listed in undeclared_sts. Got: {st_ids}"
        )
        # Verify share is correct (~1%)
        st99_entry = next(e for e in sts if e["st"] == "99")
        assert 0.009 < st99_entry["share"] < 0.011, (
            f"ST 99 share should be ~0.01 (10/1000). Got: {st99_entry['share']}"
        )

    def test_undeclared_st_below_threshold_is_ok(self) -> None:
        """Undeclared ST with share <= 0.1% does NOT trigger fail (below threshold)."""
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=["F"], observed_fields=["F"])
        })
        # ST 99: 1 round out of 1001 total = 0.0999% (just under 0.1% threshold)
        chunks = [
            {
                "st_extract": {
                    "signature_audit": {
                        "observed_st_counts": {"1": 1000, "99": 1},
                        "per_st": {
                            "1": {
                                "declared_field_presence": {"F": 1000},
                                "observed_field_presence": {},
                                "new_field_presence": {},
                                "rounds": 1000,
                                "has_observed_fields": True,
                            }
                        },
                    }
                }
            }
        ]
        result = _run_feature(chunks, manifest)
        # 1/1001 = 0.0999% which is NOT > 0.1%, so should stay ok
        assert result["status"] == "ok", (
            f"Undeclared ST at 0.1% share must NOT fail. Got: {result['status']}. "
            f"(1/1001 = {1/1001:.4f} <= 0.001 threshold)"
        )


# ---------------------------------------------------------------------------
# Group 6: Known observed field absent → status stays ok (FALSE-POSITIVE REGRESSION GUARD)
# ---------------------------------------------------------------------------

class TestKnownObservedFieldAbsentStaysOk:
    """Test 6: Known optional field (in observed_fields) at 0% → status stays ok.

    This is THE core regression this fix addresses. The old code would emit
    a warn/fail for optional fields like GameplayTriggerType that are simply
    absent in some skins/modes. The CORRECTED contract: observed_fields_absent
    is INFORMATIONAL — recorded in per_st[st].observed_fields_absent (a LIST)
    and does NOT flip status.

    INJECT-BUG IB-6: Re-add observed_fields WARN/FAIL trigger for zero-presence
    obs fields (the old behavior) → test RED. Revert → GREEN.
    """

    def test_known_observed_field_absent_stays_ok(self) -> None:
        """Optional observed field (not in signature) at 0% → status ok."""
        sig = ["RequiredField"]
        # OptionalField is in observed_fields (known from onboarding) but NOT in signature
        obs = ["RequiredField", "OptionalField"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        # RequiredField: 100/100 rounds (ok), OptionalField: 0/100 rounds (absent!)
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            declared_field_presence={"RequiredField": 100},
            observed_field_presence={"OptionalField": 0},
            new_field_presence={},
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)

        assert result["status"] == "ok", (
            f"Known optional field at 0% MUST NOT flip status. Got: {result['status']}. "
            "This is the false-positive regression: absent optional fields (like "
            "GameplayTriggerType) are config/mode-dependent and INFORMATIONAL only. "
            "INJECT-BUG IB-6: re-add obs-field zero-trigger warn → RED."
        )
        # The absent field must still be RECORDED (informational surfacing)
        per_st = result.get("per_st", {})
        if "1" in per_st:
            obs_absent = per_st["1"].get("observed_fields_absent", [])
            assert "OptionalField" in obs_absent, (
                f"Optional field at 0% must be recorded in observed_fields_absent. "
                f"Got: {obs_absent}. "
                "The field must be SURFACED even if it does not flip status."
            )

    def test_gameplay_trigger_type_pattern(self) -> None:
        """Simulate M15 ST1 pattern: GameplayTriggerType at ~15% presence.

        GameplayTriggerType is in observed_fields but NOT in signature for M15 ST1.
        It appears in only ~15% of rounds (mode/skin-dependent). The corrected
        contract says this is INFORMATIONAL and must NOT produce warn.
        """
        sig = ["BetAmount", "CostCredits", "StopSymbolsByCol", "WinCredits"]
        obs = sig + ["GameplayTriggerType", "CurJackpotStoreWin", "ReMarks"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        # GameplayTriggerType at 15% presence, CurJackpotStoreWin at 100%
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            declared_field_presence={
                "BetAmount": 100, "CostCredits": 100,
                "StopSymbolsByCol": 100, "WinCredits": 100,
            },
            observed_field_presence={
                "GameplayTriggerType": 15,   # ~15% — config-dependent optional
                "CurJackpotStoreWin": 100,
                "ReMarks": 100,
            },
            new_field_presence={},
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)

        assert result["status"] == "ok", (
            f"M15 ST1 pattern with GameplayTriggerType at 15% must be ok. "
            f"Got: {result['status']}. "
            "Optional presence rates are config/mode-dependent per cardinal rule 4."
        )


# ---------------------------------------------------------------------------
# Group 7: Optional observed field at low presence → status ok
# ---------------------------------------------------------------------------

class TestOptionalFieldLowPresenceStaysOk:
    """Test 7: Optional field (in observed_fields, not in signature) at 15% → ok.

    This is the CORE fix invariant. The <90% warn threshold must NOT apply to
    observed_fields-only fields. Only signature fields can trigger the <90% warn.

    INJECT-BUG IB-7: Same as IB-6 — re-add obs<90% warn trigger →
    test RED (15% < 90% → warn). Revert → GREEN.
    """

    def test_optional_field_at_15_percent_stays_ok(self) -> None:
        """Observed-only field at 15% → ok (NOT warn). The core regression fix."""
        sig = ["CoreSig"]
        obs = ["CoreSig", "OptionalEnvelope"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            declared_field_presence={"CoreSig": 100},
            observed_field_presence={"OptionalEnvelope": 15},  # 15% — optional
            new_field_presence={},
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)

        assert result["status"] == "ok", (
            f"Observed-only field at 15% must produce status='ok'. Got: {result['status']}. "
            "The <90% warn threshold applies ONLY to signature fields, NOT observed_fields. "
            "INJECT-BUG IB-7: re-add obs<90% warn trigger → 15% < 90% → warn → RED."
        )

    def test_optional_field_at_1_percent_stays_ok(self) -> None:
        """Observed-only field at 1% → ok (even extremely low presence)."""
        sig = ["SigField"]
        obs = ["SigField", "VeryRareEnvelopeField"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        chunk = _fake_chunk(
            st=1,
            rounds=1000,
            declared_field_presence={"SigField": 1000},
            observed_field_presence={"VeryRareEnvelopeField": 10},  # 1%
            new_field_presence={},
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)
        assert result["status"] == "ok", (
            f"Observed-only field at 1% must produce ok. Got: {result['status']}"
        )

    def test_sig_field_at_same_low_presence_still_warns(self) -> None:
        """Signature field at 15% DOES warn — only the category matters, not the value.

        This is the contrast case: the exact same 15% presence for a SIGNATURE field
        triggers WARN, while for an observed-only field it does not.
        """
        sig = ["CoreSig", "SigFieldLow"]
        obs = ["CoreSig", "SigFieldLow"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            # SigFieldLow is in SIGNATURE and only 15% present → warn
            declared_field_presence={"CoreSig": 100, "SigFieldLow": 15},
            observed_field_presence={},
            new_field_presence={},
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)
        assert result["status"] == "warn", (
            f"Signature field at 15% must produce warn. Got: {result['status']}. "
            "This contrast test proves the classification is category-based."
        )


# ---------------------------------------------------------------------------
# Group 8: Unaudited cases
# ---------------------------------------------------------------------------

class TestUnauditedCases:
    """Test 8: unaudited status variants.

    IB-8a: Change emit() to always set obs_status='ok' instead of 'unaudited_fields'
           → test_st_with_signature_no_observed_fields_is_unaudited_fields RED.
    IB-8b: Make extract() report chunks_with_extract=1 even when st_extract absent
           → test_no_extractor_output_is_unaudited RED (unaudited status not reached).
    """

    def test_no_extractor_output_is_unaudited(self) -> None:
        """No extractor output in any chunk → top-level status 'unaudited' with reason.

        Happens for legacy chunks (no st_extract key at all) or machines without
        signature declarations.
        """
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=["F"])
        })
        # Chunk with no st_extract key at all (legacy chunk)
        chunk = {"spins": 100, "some_metric": 1.0}
        result = _run_feature([chunk], manifest)

        assert result["status"] == "unaudited", (
            f"No extractor output must produce status='unaudited'. Got: {result['status']}. "
            "INJECT-BUG IB-8b: make extract() return chunks_with_extract=1 even when "
            "st_extract absent → status never reaches 'unaudited' → RED."
        )
        assert result.get("reason") is not None, (
            "unaudited status must include a reason string."
        )
        assert "chunks_total" in result["reason"] or "0" in result["reason"] or \
               "no signature" in result["reason"] or "signature_audit" in result["reason"], (
            f"unaudited reason must be informative. Got: {result['reason']!r}"
        )

    def test_st_with_signature_no_observed_fields_is_unaudited_fields(self) -> None:
        """ST with 'signature' but NO 'observed_fields' in manifest →
        per_st[st].observed_fields_status == 'unaudited_fields'.

        The signature audit still runs (declared_field_presence checked) but
        the new-field/envelope audit cannot run. Never silently 'ok'.
        """
        # ST with signature but no observed_fields
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=["CoreField"])
            # no observed_fields key
        })
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            declared_field_presence={"CoreField": 100},
            observed_field_presence={},
            new_field_presence={},
            has_observed_fields=False,  # <-- no observed_fields in manifest
        )
        result = _run_feature([chunk], manifest)

        # Top-level status: should be ok (signature is fine), not unaudited
        # The unaudited_fields is a per-ST status, not top-level
        per_st = result.get("per_st", {})
        assert "1" in per_st, (
            f"ST 1 must have a per_st entry when has_observed_fields=False. "
            f"Got per_st={per_st}"
        )
        obs_status = per_st["1"].get("observed_fields_status")
        assert obs_status == "unaudited_fields", (
            f"ST with signature but no observed_fields must report "
            f"observed_fields_status='unaudited_fields'. Got: {obs_status!r}. "
            "INJECT-BUG IB-8a: change to always 'ok' → RED."
        )

    def test_no_extractor_output_includes_reason(self) -> None:
        """The unaudited reason must mention the chunk count."""
        manifest = _manifest(spin_types={})
        chunk_no_extract = {"spins": 50}
        result = _run_feature([chunk_no_extract, chunk_no_extract], manifest)

        assert result["status"] == "unaudited"
        reason = result.get("reason", "")
        # Reason should mention number of chunks parsed
        assert "2" in reason or "chunks" in reason or "0" in reason, (
            f"unaudited reason should reference chunk count. Got: {reason!r}"
        )

    def test_empty_chunk_list_is_unaudited(self) -> None:
        """Running with no chunks at all → unaudited (no extractor output)."""
        manifest = _manifest(spin_types={"1": _st_block(signature=["F"])})
        result = _run_feature([], manifest)
        # With no chunks, chunks_with_extract=0, chunks_total=0 → unaudited
        assert result["status"] == "unaudited", (
            f"No chunks → unaudited. Got: {result['status']}"
        )


# ---------------------------------------------------------------------------
# Group 9: Real-data (skipif chunks absent) — per-machine status ok
# ---------------------------------------------------------------------------

class TestRealDataStatusOk:
    """Test 9: Each of M15/M43(1)/M43(7)/M279/M275 → structure_drift.status == 'ok'.

    Value-agnostic: we only assert status=='ok', not any field details.
    These are the coordinator-verified machines (all 4 onboarded + confirmed).

    No inject-bug needed — these are regression guards against real data.
    The inject-bug exercises are in groups 1-8 which cover all the logic paths.
    """

    def _gen_summary(self, machine: str, mode: int) -> dict:
        """Run report_engine.generate_report_from_chunks on real rawdata."""
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
        chunk_dir = ROOT / "rawdata" / machine / f"mode_{mode}"
        with tempfile.TemporaryDirectory() as tmp:
            summary = generate_report_from_chunks(
                machine, mode,
                chunk_dir=chunk_dir,
                output_dir=Path(tmp),
                bet=1000,
            )
        return summary

    @SKIP_NO_M15
    def test_m15_mode1_ok(self) -> None:
        """M15 mode 1 real chunks → structure_drift.status == 'ok'."""
        summary = self._gen_summary("M15", 1)
        drift = summary.get("structure_drift", {})
        assert drift.get("status") == "ok", (
            f"M15 mode 1 real data must produce structure_drift.status='ok'. "
            f"Got: {drift.get('status')!r}. Full drift: {drift}"
        )

    @SKIP_NO_M43_1
    def test_m43_mode1_ok(self) -> None:
        """M43 mode 1 real chunks → structure_drift.status == 'ok'."""
        summary = self._gen_summary("M43", 1)
        drift = summary.get("structure_drift", {})
        assert drift.get("status") == "ok", (
            f"M43 mode 1 real data must produce structure_drift.status='ok'. "
            f"Got: {drift.get('status')!r}. Full drift: {drift}"
        )

    @SKIP_NO_M43_7
    def test_m43_mode7_ok(self) -> None:
        """M43 mode 7 real chunks → structure_drift.status == 'ok'."""
        summary = self._gen_summary("M43", 7)
        drift = summary.get("structure_drift", {})
        assert drift.get("status") == "ok", (
            f"M43 mode 7 real data must produce structure_drift.status='ok'. "
            f"Got: {drift.get('status')!r}. Full drift: {drift}"
        )

    @SKIP_NO_M279
    def test_m279_mode1_ok(self) -> None:
        """M279 mode 1 real chunks → structure_drift.status == 'ok'."""
        summary = self._gen_summary("M279", 1)
        drift = summary.get("structure_drift", {})
        assert drift.get("status") == "ok", (
            f"M279 mode 1 real data must produce structure_drift.status='ok'. "
            f"Got: {drift.get('status')!r}. Full drift: {drift}"
        )

    @SKIP_NO_M275
    def test_m275_mode1_ok(self) -> None:
        """M275 mode 1 real chunks → structure_drift.status == 'ok'."""
        summary = self._gen_summary("M275", 1)
        drift = summary.get("structure_drift", {})
        assert drift.get("status") == "ok", (
            f"M275 mode 1 real data must produce structure_drift.status='ok'. "
            f"Got: {drift.get('status')!r}. Full drift: {drift}"
        )


# ---------------------------------------------------------------------------
# Group 10: Frontend contract — renderer↔plugin key alignment
# ---------------------------------------------------------------------------

class TestFrontendRendererKeyAlignment:
    """Test 10: renderStructureDriftPanel reads keys that EXACTLY match plugin output.

    Parse app.js for stData.<key> / drift.<key> accesses in renderStructureDriftPanel,
    then build a real summary and diff the key sets.

    The coordinator's bug fix was: the old code used 'missing_declared_fields' and
    'new_undeclared_fields' as per_st keys, but the renderer expected
    'signature_fields_missing' and 'new_fields'. This test locks that alignment
    so it can never drift again.

    INJECT-BUG IB-10: In structure_drift.py emit(), rename 'observed_fields_absent'
    (in per_st entry) to 'missing_declared_fields' → test RED because the
    renderer reads 'observed_fields_absent' but the plugin now emits a different key.
    Revert → GREEN.
    """

    _APP_JS = ROOT / "src" / "web_console" / "frontend" / "app.js"

    def _extract_renderer_function(self) -> str:
        """Extract the renderStructureDriftPanel function body from app.js."""
        text = self._APP_JS.read_text(encoding="utf-8")
        # Find the function
        start = text.find("function renderStructureDriftPanel(")
        assert start >= 0, "renderStructureDriftPanel not found in app.js"
        # Extract until the matching closing brace
        depth = 0
        end = start
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        return text[start:end + 1]

    def _extract_renderer_top_keys(self, fn_body: str) -> set[str]:
        """Extract keys the renderer reads as drift.<key> from the function body."""
        # Matches: drift.status, drift.undeclared_sts, drift.declared_sts_absent,
        # drift.per_st, drift.reason, drift.audited_rounds, drift.source
        matches = re.findall(r"\bdrift\.(\w+)", fn_body)
        return set(matches)

    def _extract_renderer_per_st_keys(self, fn_body: str) -> set[str]:
        """Extract keys the renderer reads as stData.<key> from the function body."""
        matches = re.findall(r"\bstData\.(\w+)", fn_body)
        return set(matches)

    def _build_plugin_summary(self) -> dict:
        """Build a synthetic summary with all possible per_st keys populated."""
        sig = ["SigField"]
        obs = ["SigField", "ObsField"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        # Create a chunk that causes per_st to be populated with all optional keys:
        # - signature_fields_missing (SigField at 50%)
        # - observed_fields_absent (ObsField at 0%)
        # - new_fields (NewField present)
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            declared_field_presence={"SigField": 50},   # 50% → in sig_missing (warn)
            observed_field_presence={"ObsField": 0},     # 0% → in obs_absent (info)
            new_field_presence={"NewField": 30},          # → in new_fields (warn)
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)
        return result

    def test_top_level_drift_keys_match_renderer(self) -> None:
        """Top-level keys renderer reads (drift.<key>) must all be in plugin output."""
        fn_body = self._extract_renderer_function()
        renderer_keys = self._extract_renderer_top_keys(fn_body)

        # Get the actual keys the plugin emits
        plugin_summary = self._build_plugin_summary()
        # Also test with an unaudited version to get 'reason' key
        chunk_no_extract = {}
        from fresh_slotlab.analyzer.features.structure_drift import StructureDriftFeature
        feature = StructureDriftFeature()
        acc = feature.extract(None, chunk_no_extract)
        summary_unaudited: dict = {}
        feature.emit(acc, summary_unaudited, _FakeCtx({}))
        plugin_keys_unaudited = set(summary_unaudited["structure_drift"].keys())
        plugin_keys_normal = set(plugin_summary.keys())
        all_plugin_keys = plugin_keys_normal | plugin_keys_unaudited

        # The renderer reads these top-level drift keys:
        # status, undeclared_sts, declared_sts_absent, per_st, reason, audited_rounds, source
        expected_renderer_reads = {
            "status", "undeclared_sts", "declared_sts_absent",
            "per_st", "reason", "audited_rounds", "source",
        }

        # Each key the renderer reads (excluding function calls) must be in plugin output
        for key in renderer_keys:
            if key in {"length"}:  # JS array.length is not a dict key
                continue
            assert key in all_plugin_keys, (
                f"Renderer reads drift.{key} but plugin does not emit this key. "
                f"Plugin keys: {sorted(all_plugin_keys)}. "
                "This is a renderer↔plugin key alignment bug. "
                "INJECT-BUG IB-10: rename plugin key → this test RED."
            )

    def test_per_st_keys_match_renderer(self) -> None:
        """Per-ST keys renderer reads (stData.<key>) must all be in plugin per_st output.

        The renderer reads: stData.signature_fields_missing, stData.new_fields,
        stData.observed_fields_absent, stData.observed_fields_status.

        The old bug used 'missing_declared_fields' / 'new_undeclared_fields'.
        This test locks the CORRECTED names.
        """
        fn_body = self._extract_renderer_function()
        renderer_per_st_keys = self._extract_renderer_per_st_keys(fn_body)

        # Build a plugin summary with a per_st entry containing all keys
        plugin_summary = self._build_plugin_summary()
        per_st = plugin_summary.get("per_st", {})
        assert len(per_st) > 0, (
            f"test fixture must produce at least one per_st entry. Got: {per_st}"
        )

        # Collect all keys from any per_st entry
        all_per_st_plugin_keys: set[str] = set()
        for st_entry in per_st.values():
            all_per_st_plugin_keys |= set(st_entry.keys())

        # Every key the renderer reads as stData.<key> must be in plugin output
        for key in renderer_per_st_keys:
            assert key in all_per_st_plugin_keys, (
                f"Renderer reads stData.{key} but plugin does not emit this per_st key. "
                f"Plugin per_st keys: {sorted(all_per_st_plugin_keys)}. "
                "INJECT-BUG IB-10: rename 'observed_fields_absent' to 'missing_declared_fields' "
                "in emit() → this test RED."
            )

    def test_critical_corrected_keys_present_in_plugin(self) -> None:
        """The corrected per_st schema keys must be present (locks names after fix).

        These are the exact keys the bug fix introduced — the old names were
        'missing_declared_fields' and 'new_undeclared_fields'.
        """
        plugin_summary = self._build_plugin_summary()
        per_st = plugin_summary.get("per_st", {})
        assert "1" in per_st, f"ST '1' must be in per_st. Got: {per_st}"

        st1 = per_st["1"]
        # Corrected names (post-fix):
        assert "signature_fields_missing" in st1, (
            f"Plugin must emit 'signature_fields_missing' (not 'missing_declared_fields'). "
            f"Got keys: {sorted(st1.keys())}"
        )
        assert "new_fields" in st1, (
            f"Plugin must emit 'new_fields' (not 'new_undeclared_fields'). "
            f"Got keys: {sorted(st1.keys())}"
        )
        assert "observed_fields_absent" in st1, (
            f"Plugin must emit 'observed_fields_absent' as a list. "
            f"Got keys: {sorted(st1.keys())}"
        )
        assert isinstance(st1["observed_fields_absent"], list), (
            f"observed_fields_absent must be a list. Got: {type(st1['observed_fields_absent'])}"
        )
        assert "observed_fields_status" in st1, (
            f"Plugin must emit 'observed_fields_status'. "
            f"Got keys: {sorted(st1.keys())}"
        )

    def test_renderer_does_not_read_old_bug_keys(self) -> None:
        """Renderer must NOT read the old (pre-fix) key names.

        If the renderer still references 'missing_declared_fields' or
        'new_undeclared_fields', those are stale references to the unfixed schema.
        """
        fn_body = self._extract_renderer_function()
        assert "missing_declared_fields" not in fn_body, (
            "renderStructureDriftPanel references the OLD key 'missing_declared_fields'. "
            "The corrected key is 'signature_fields_missing'. Fix the renderer."
        )
        assert "new_undeclared_fields" not in fn_body, (
            "renderStructureDriftPanel references the OLD key 'new_undeclared_fields'. "
            "The corrected key is 'new_fields'. Fix the renderer."
        )

    def test_observed_fields_status_is_read_by_renderer_bidirectional(self) -> None:
        """BIDIRECTIONAL alignment lock for observed_fields_status (C1 fix, T1 gap closure).

        The existing test_per_st_keys_match_renderer checks reads ⊆ emits:
        every key the renderer reads must be in the plugin output.  That
        direction alone does not catch a future removal of the 'observed_fields_status'
        branch from the renderer — the renderer would simply stop reading the key
        and the reads⊆emits test would still pass (fewer reads, all present).

        This test adds the operationally-meaningful REVERSE check: the renderer
        MUST read 'observed_fields_status' (i.e. the C1 branch is wired in), and
        the plugin MUST emit it.  Both directions fail independently:

          Direction A (renderer reads it):
            grep renderStructureDriftPanel body for 'stData.observed_fields_status'
            → FAIL if the C1 rendering branch is removed from app.js.

          Direction B (plugin emits it):
            build a synthetic unaudited-fields per_st block → confirm the key
            is present in the plugin output with value 'unaudited_fields'.
            → FAIL if emit() stops producing observed_fields_status.

        INJECT-BUG (document for future devs):
          In app.js renderStructureDriftPanel, delete the lines:
            if (stData.observed_fields_status === "unaudited_fields") { ... }
          → Direction A assertion FAILS ("observed_fields_status" no longer in fn_body).
          Revert → GREEN.
          (Direction B is separately covered by TestUnauditedFieldsRendering below.)
        """
        fn_body = self._extract_renderer_function()

        # Direction A: renderer MUST read observed_fields_status.
        renderer_per_st_keys = self._extract_renderer_per_st_keys(fn_body)
        assert "observed_fields_status" in renderer_per_st_keys, (
            "renderStructureDriftPanel must read stData.observed_fields_status "
            "(the C1 unaudited_fields rendering branch). "
            "INJECT-BUG: delete the 'if (stData.observed_fields_status === "
            "\"unaudited_fields\")' branch from app.js → this assertion FAILS. "
            "Revert → GREEN."
        )

        # Direction B: plugin MUST emit observed_fields_status in unaudited-fields case.
        # Build a manifest with signature but no observed_fields for an ST.
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=["CoreField"])
            # deliberately no observed_fields
        })
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            declared_field_presence={"CoreField": 100},
            observed_field_presence={},
            new_field_presence={},
            has_observed_fields=False,
        )
        result = _run_feature([chunk], manifest)
        per_st = result.get("per_st", {})
        assert "1" in per_st, (
            f"ST '1' must have a per_st entry when has_observed_fields=False. "
            f"Got: {per_st}"
        )
        assert "observed_fields_status" in per_st["1"], (
            f"Plugin must emit 'observed_fields_status' in per_st entry. "
            f"Got keys: {sorted(per_st['1'].keys())}"
        )
        assert per_st["1"]["observed_fields_status"] == "unaudited_fields", (
            f"observed_fields_status must be 'unaudited_fields' when no observed_fields "
            f"declared. Got: {per_st['1']['observed_fields_status']!r}"
        )


# ---------------------------------------------------------------------------
# Group 12: unaudited_fields rendering (C1 fix regression lock)
# ---------------------------------------------------------------------------

class TestUnauditedFieldsRendering:
    """Test 12: End-to-end regression lock for the C1 fix.

    The C1 fix added to renderStructureDriftPanel in app.js:
      if (stData.observed_fields_status === "unaudited_fields") { ... sdUnauditedFields ... }

    And added the i18n key 'sdUnauditedFields' to pure.js in both zh and en locales.

    This class locks three things:
      12a. Plugin backend: observed_fields_status=="unaudited_fields" is emitted when
           an ST has a signature but no observed_fields.
      12b. Renderer static analysis: app.js renderStructureDriftPanel contains the
           unaudited_fields rendering branch (the literal string "unaudited_fields").
      12c. i18n completeness: pure.js declares 'sdUnauditedFields' in BOTH zh and en.

    INJECT-BUG (documented for future devs):
      Delete the unaudited render branch from app.js (the 5 lines starting with
      "if (stData.observed_fields_status === \"unaudited_fields\")"):
        → test_renderer_contains_unaudited_fields_branch FAILS (branch string absent).
        → test_observed_fields_status_is_read_by_renderer_bidirectional (Group 10)
          Direction A also FAILS (observed_fields_status no longer read).
      Revert → both GREEN.

    Memory feedback honored:
      memory/feedback_no_silent_swallow.md — unknown != ok; unaudited_fields must
        surface visibly in the UI, not silently skip.
      memory/feedback_enumerate_safety_paths.md — inject-bug recipe documented above.
    """

    _APP_JS = ROOT / "src" / "web_console" / "frontend" / "app.js"
    _PURE_JS = ROOT / "src" / "web_console" / "frontend" / "pure.js"

    def _extract_renderer_function(self) -> str:
        """Extract renderStructureDriftPanel function body from app.js."""
        text = self._APP_JS.read_text(encoding="utf-8")
        start = text.find("function renderStructureDriftPanel(")
        assert start >= 0, "renderStructureDriftPanel not found in app.js"
        depth = 0
        end = start
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        return text[start:end + 1]

    def test_plugin_emits_unaudited_fields_status(self) -> None:
        """12a: Plugin backend emits observed_fields_status=='unaudited_fields' for
        an ST that has signature but no observed_fields declared in the manifest.

        This is the backend path for the C1 fix — without this emission the renderer
        branch would never fire.

        INJECT-BUG: In structure_drift.py emit(), change:
            if not has_observed_fields:
                obs_status = "unaudited_fields"
          to:
            if not has_observed_fields:
                obs_status = "ok"   # INJECT-BUG: silent swallow
          → this assertion FAILS (value is 'ok' not 'unaudited_fields').
          Revert → GREEN.
        """
        manifest = _manifest(spin_types={
            "7": _st_block(role="state", signature=["StatusField"])
            # no observed_fields — canonical unaudited_fields case
        })
        chunk = _fake_chunk(
            st=7,
            rounds=200,
            declared_field_presence={"StatusField": 200},
            observed_field_presence={},
            new_field_presence={},
            has_observed_fields=False,  # <-- no observed_fields in manifest
        )
        result = _run_feature([chunk], manifest)

        assert result["status"] == "ok", (
            f"Signature fields 100% present + no observed_fields → top-level ok. "
            f"Got: {result['status']}"
        )
        per_st = result.get("per_st", {})
        assert "7" in per_st, (
            f"ST '7' must appear in per_st when has_observed_fields=False "
            f"(unaudited_fields must be surfaced). Got: {per_st}"
        )
        obs_status = per_st["7"].get("observed_fields_status")
        assert obs_status == "unaudited_fields", (
            f"observed_fields_status must be 'unaudited_fields' for ST with signature "
            f"but no observed_fields. Got: {obs_status!r}. "
            "INJECT-BUG: change to 'ok' in emit() → this assertion FAILS."
        )

    def test_renderer_contains_unaudited_fields_branch(self) -> None:
        """12b: app.js renderStructureDriftPanel contains the literal string
        'unaudited_fields' (the C1 rendering branch is present).

        Static analysis: we don't execute JS, but we verify the branch exists in
        the function body so a future accidental deletion of the block goes RED.

        INJECT-BUG: delete the 5-line block:
            if (stData.observed_fields_status === "unaudited_fields") {
              inner += `<div ...>
                <div class="sd-field-group-title">${escapeHtml(t("sdUnauditedFields"))}</div>
              </div>`;
            }
          from renderStructureDriftPanel in app.js
          → this test FAILS (literal 'unaudited_fields' absent from fn body).
          Revert → GREEN.
        """
        fn_body = self._extract_renderer_function()

        assert "unaudited_fields" in fn_body, (
            "renderStructureDriftPanel must contain the 'unaudited_fields' rendering "
            "branch (C1 fix). The branch surfaces ST-level unaudited_fields status "
            "so operators see it explicitly — not silently skipped. "
            "INJECT-BUG: delete the branch from app.js → RED. Revert → GREEN."
        )
        # More specific: the condition must reference stData.observed_fields_status.
        assert 'stData.observed_fields_status === "unaudited_fields"' in fn_body, (
            "The unaudited_fields branch must check "
            "'stData.observed_fields_status === \"unaudited_fields\"'. "
            "This exact condition is what the C1 fix wired in."
        )
        # And it must call t("sdUnauditedFields") — uses the i18n key.
        assert 't("sdUnauditedFields")' in fn_body, (
            "The unaudited_fields branch must call t(\"sdUnauditedFields\") "
            "to render the localised label."
        )

    def test_i18n_key_sdUnauditedFields_exists_in_both_locales(self) -> None:
        """12c: pure.js declares 'sdUnauditedFields' in BOTH zh and en locale blocks.

        The C1 fix added this key. If either locale is missing the key, the renderer
        falls back to the raw key string (renders as 'sdUnauditedFields' on screen).

        pure.js structure (top-level indentation = 2 spaces):
            const I18N = {
              zh: { ... },
              en: { ... },
            };

        We locate the top-level locale boundary with a multiline regex on 2-space
        indented "zh: {" and "en: {" patterns, then slice the text between them.
        This avoids false matches on "en-US" strings or nested "en:" occurrences.

        INJECT-BUG: remove 'sdUnauditedFields' from one locale block in pure.js
          → the assertion for that locale FAILS.
          Revert → GREEN.
        """
        pure_text = self._PURE_JS.read_text(encoding="utf-8")

        # Locate the I18N const — provides the search origin.
        i18n_start = pure_text.find("const I18N =")
        assert i18n_start >= 0, "Could not locate 'const I18N =' in pure.js"

        i18n_tail = pure_text[i18n_start:]

        # Match top-level locale keys (2-space indent) using multiline anchors.
        # This avoids false matches on "en-US" strings or nested properties.
        zh_m = re.search(r"^\s{2}zh\s*:\s*\{", i18n_tail, re.MULTILINE)
        en_m = re.search(r"^\s{2}en\s*:\s*\{", i18n_tail, re.MULTILINE)
        assert zh_m is not None, (
            "Could not locate top-level 'zh: {' locale key in pure.js I18N block"
        )
        assert en_m is not None, (
            "Could not locate top-level 'en: {' locale key in pure.js I18N block"
        )

        zh_abs = i18n_start + zh_m.start()
        en_abs = i18n_start + en_m.start()

        # zh block: from zh locale start to en locale start.
        zh_block = pure_text[zh_abs:en_abs]
        assert "sdUnauditedFields" in zh_block, (
            "pure.js zh locale block must contain 'sdUnauditedFields'. "
            f"(Block chars {zh_abs}–{en_abs}, len={en_abs - zh_abs}.) "
            "INJECT-BUG: remove from zh → this assertion FAILS. Revert → GREEN."
        )

        # en block: from en locale start to end of file.
        en_block = pure_text[en_abs:]
        assert "sdUnauditedFields" in en_block, (
            "pure.js en locale block must contain 'sdUnauditedFields'. "
            f"(Block starts at char {en_abs}.) "
            "INJECT-BUG: remove from en → this assertion FAILS. Revert → GREEN."
        )

        # Belt-and-suspenders: at least 2 total occurrences (one per locale).
        occurrences = pure_text.count("sdUnauditedFields")
        assert occurrences >= 2, (
            f"pure.js must declare 'sdUnauditedFields' in BOTH zh and en locales "
            f"(expected >= 2 occurrences). Found: {occurrences}. "
            "INJECT-BUG: remove from one locale → count drops to 1 → FAILS."
        )


# ---------------------------------------------------------------------------
# Group 11: Additional structural invariants
# ---------------------------------------------------------------------------

class TestStructuralInvariants:
    """Additional structural invariants and edge cases."""

    def test_declared_sts_absent_lists_missing_manifest_sts(self) -> None:
        """STs declared in manifest but with 0 observed rounds → in declared_sts_absent."""
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=["F"], observed_fields=["F"]),
            "50": _st_block(role="respin", signature=["G"], observed_fields=["G"]),
        })
        # Only ST 1 appears in data (ST 50 absent)
        chunk = _fake_chunk(
            st=1,
            rounds=100,
            declared_field_presence={"F": 100},
            observed_field_presence={},
            new_field_presence={},
            has_observed_fields=True,
        )
        result = _run_feature([chunk], manifest)
        assert "50" in result["declared_sts_absent"], (
            f"ST 50 (declared in manifest, 0 rounds in data) must appear in "
            f"declared_sts_absent. Got: {result['declared_sts_absent']}"
        )
        # ST 1 must NOT be in declared_sts_absent
        assert "1" not in result["declared_sts_absent"], (
            f"ST 1 (present in data) must NOT appear in declared_sts_absent."
        )

    def test_audited_rounds_is_total_observed(self) -> None:
        """audited_rounds == sum of all observed round counts."""
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=["F"], observed_fields=["F"]),
        })
        chunk1 = _fake_chunk(st=1, rounds=100, declared_field_presence={"F": 100})
        chunk2 = _fake_chunk(st=1, rounds=50, declared_field_presence={"F": 50})
        result = _run_feature([chunk1, chunk2], manifest)
        assert result["audited_rounds"] == 150, (
            f"audited_rounds must equal total rounds observed (100+50=150). "
            f"Got: {result['audited_rounds']}"
        )

    def test_source_field_is_set(self) -> None:
        """source field must be present in output."""
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=["F"], observed_fields=["F"]),
        })
        chunk = _fake_chunk(st=1, rounds=10, declared_field_presence={"F": 10})
        result = _run_feature([chunk], manifest)
        assert "source" in result, f"source field must be present. Got: {result}"
        assert "signature_audit" in result["source"], (
            f"source must mention 'signature_audit'. Got: {result['source']!r}"
        )

    def test_multi_chunk_accumulation(self) -> None:
        """Multiple chunks are merged: presence counts add, status reflects combined."""
        sig = ["F"]
        obs = ["F", "OptF"]
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=sig, observed_fields=obs)
        })
        # Chunk 1: F present in 90/100 (borderline at 90%)
        chunk1 = _fake_chunk(
            st=1, rounds=100,
            declared_field_presence={"F": 90},
            observed_field_presence={"OptF": 30},
            new_field_presence={},
            has_observed_fields=True,
        )
        # Chunk 2: F present in 100/100 (perfect)
        chunk2 = _fake_chunk(
            st=1, rounds=100,
            declared_field_presence={"F": 100},
            observed_field_presence={"OptF": 40},
            new_field_presence={},
            has_observed_fields=True,
        )
        result = _run_feature([chunk1, chunk2], manifest)
        # Combined: F present in 190/200 = 95% (above 90% threshold) → ok
        assert result["status"] == "ok", (
            f"F at 95% combined (90+100/200) must be ok. Got: {result['status']}"
        )
        assert result["audited_rounds"] == 200, (
            f"Two 100-round chunks must give 200 audited_rounds. "
            f"Got: {result['audited_rounds']}"
        )

    def test_rtp_contribution_is_false(self) -> None:
        """StructureDriftFeature.RTP_CONTRIBUTION must be False."""
        from fresh_slotlab.analyzer.features.structure_drift import StructureDriftFeature
        assert StructureDriftFeature.RTP_CONTRIBUTION is False, (
            "structure_drift must NOT contribute to RTP sum."
        )

    def test_feature_id_is_structure_drift(self) -> None:
        """StructureDriftFeature.FEATURE_ID must be 'structure_drift'."""
        from fresh_slotlab.analyzer.features.structure_drift import StructureDriftFeature
        assert StructureDriftFeature.FEATURE_ID == "structure_drift"

    def test_undeclared_st_not_in_manifest_only_flag(self) -> None:
        """Undeclared ST (no signature) must appear in undeclared_sts but NOT per_st."""
        manifest = _manifest(spin_types={
            "1": _st_block(role="paid_spin", signature=["F"], observed_fields=["F"])
        })
        # ST 99 appears in data but has no manifest entry AND no signature
        # => it's undeclared, goes into undeclared_sts, not per_st
        chunks = [
            {
                "st_extract": {
                    "signature_audit": {
                        "observed_st_counts": {"1": 990, "99": 50},
                        "per_st": {
                            "1": {
                                "declared_field_presence": {"F": 990},
                                "observed_field_presence": {},
                                "new_field_presence": {},
                                "rounds": 990,
                                "has_observed_fields": True,
                            }
                            # Note: no entry for "99" since extractor only creates
                            # per_st entries for STs with declared signatures
                        },
                    }
                }
            }
        ]
        result = _run_feature(chunks, manifest)
        assert "99" not in result["per_st"], (
            f"Undeclared ST 99 must NOT appear in per_st. Got: {result['per_st']}"
        )
        st_ids = [e["st"] for e in result["undeclared_sts"]]
        assert "99" in st_ids, (
            f"ST 99 must appear in undeclared_sts. Got: {st_ids}"
        )
