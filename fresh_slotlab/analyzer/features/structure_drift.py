"""AnalyzerFeature: structure_drift — ST signature runtime contract gate.

PROBLEM: Nothing validates incoming rounds against the manifest's declared
field signatures — new fields are silently ignored, removed fields silently
degrade, undeclared STs silently blend in.  The rtp_integrity gate only
catches economy-breaking drift; structural drift is silent.

This feature upgrades the manifest ST signatures from documentation to a
RUNTIME CONTRACT.  The model distinguishes three field classes:

  signature fields    = core/reuse contract (cardinal rule 4).  Must stay
                        present (~100%).  Missing = contract breach.
  observed_fields     = complete onboarding inventory (envelope fields).
                        Their PRESENCE RATE is config/mode-dependent (optional
                        feature fields, cardinal rule 4) and is NOT a structural
                        invariant — rate changes are NOT a drift signal.  A
                        known observed field absent this run is INFORMATIONAL.
  new fields          = not in either set.  Appearing = WARN (protocol growth).

Classification
--------------
  FAIL = (a) any undeclared ST with share > 0.1%, OR
          (b) any signature field with presence == 0 on a present ST.
  WARN = (a) signature field presence < 90% (degrading core field), OR
          (b) field in data NOT in signature NOR observed_fields (new field).
  OK   = none of the above.
  (Known observed fields absent this run → recorded in observed_fields_absent,
   INFORMATIONAL, does NOT flip status — optional-field presence is config-
   dependent; see the _WARN_SIG_FIELD_LOW note in the source.)
  unaudited = no extractor output in any chunk (machine without signature
              declarations or legacy chunks).

Per-ST "unaudited_fields" class
--------------------------------
When an ST has a "signature" but NO "observed_fields" in the manifest, the
new-field and observed-field audits cannot run.  The per-st block reports
  "observed_fields_status": "unaudited_fields"
for that ST (never silently "ok" for the envelope dimension).
The signature audit (declared-field presence) still runs normally.

"unaudited" top-level status is an EXPLICIT ALARM (feedback_invariant_with_
fallback_hides_drift, feedback_no_silent_swallow): unknown != ok.

Data path
---------
extract() lifts rec["st_extract"]["signature_audit"] from each chunk.
reduce() accumulates across chunks (additive counts).
emit() compares accumulated data against ctx.machine_spec_manifest.spin_types
and writes summary["structure_drift"].

Output schema
-------------
summary["structure_drift"]:
  {
    "status": "ok" | "warn" | "fail" | "unaudited",
    "reason": str | null,
    "undeclared_sts": [
      {"st": str, "rounds": int, "share": float}, ...
    ],
    "declared_sts_absent": [str, ...],
    "per_st": {
      "<st>": {
        "signature_fields_missing": {"<field>": float},  # presence < 1.0
        "observed_fields_absent": ["<field>", ...],  # known field, 0% this run (INFO)
        "new_fields": {"<field>": float},  # in data, not in either set (WARN)
        "observed_fields_status": "ok" | "warn" | "unaudited_fields",
      },
      ...
    },
    "audited_rounds": int,
    "source": "signature_audit extractor + manifest spin_types"
  }

RTP_CONTRIBUTION = False: this feature reads pre-attributed wins only for
round-count context; it adds NOTHING to the RTP sum.

Per-machine isolation
---------------------
NOT in versioning._CLOSURE_FILES — base-EXCLUDED (R-4).  Auto-discovered via
feature_registry.discover_features().  Editing it re-flags only machines
that declare "structure_drift" in their analysis set (which, after adding it
to CROSS_CUTTING in machine_spec.py, is all registered machines).

Memory feedback honored
-----------------------
- feedback_no_silent_swallow: absent extractor output → status "unaudited"
  with an explicit reason.  Extractor errors are re-surfaced, never dropped.
  STs without observed_fields are "unaudited_fields", never silently "ok".
- feedback_invariant_with_fallback_hides_drift: this block is an ALARM.
  Any drift over threshold is a FAIL/WARN, never a silent bucket.
- feedback_subprocess_import_suicide_and_module_globals: no I/O at import.
- feedback_no_parallel_panel_impl: mirrors sibling cross-cutting features
  (collect_mechanic, machine_mechanics) in extract/reduce/emit layout.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    from fresh_slotlab.analyzer.feature_registry import register
except ImportError:  # running as standalone script
    from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
    from analyzer.feature_registry import register  # type: ignore[no-redef]

if TYPE_CHECKING:
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
    except ImportError:
        from analyzer.pipeline_context import PipelineContext  # type: ignore[assignment]

# EXTRACTOR_ID that produces the raw audit data.
_AUDIT_EXTRACTOR_ID: str = "signature_audit"

# Classification thresholds.
_FAIL_UNDECLARED_ST_SHARE: float = 0.001   # > 0.1% rounds in undeclared ST → FAIL
_FAIL_SIG_FIELD_ZERO: float = 0.0          # signature field presence == 0 → FAIL
_WARN_SIG_FIELD_LOW: float = 0.90          # signature field presence < 90% → WARN
# NOTE: observed-inventory field PRESENCE RATE is intentionally NOT a status
# signal. Optional feature fields (cardinal rule 4 — e.g. GameplayTriggerType
# at ~15% on M15 ST1) appear at config/mode-dependent rates that are NOT a
# structural invariant; the SAME machine sampled on a different skin/mode shows
# a different rate (M43 mode1 vs mode7). Flagging <90% there is a pure false
# positive. The envelope dimension contributes WARN ONLY via genuinely NEW
# fields (a field in data that is in NEITHER the signature NOR the observed
# inventory = real protocol growth). Known observed fields that drop to 0% this
# run are recorded as INFORMATIONAL (observed_fields_absent) — surfaced, never
# silently dropped, but they do NOT flip the gate status.


class StructureDriftFeature(AnalyzerFeature):
    """Cross-cutting structure drift gate: manifest ST signatures as runtime contract."""

    FEATURE_ID: ClassVar[str] = "structure_drift"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("structure_drift",)
    SCHEMA_VERSION: ClassVar[int] = 2
    RTP_CONTRIBUTION: ClassVar[bool] = False
    REQUIRES: ClassVar[tuple[str, ...]] = ()
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """Lift signature_audit extractor output from one chunk.

        Returns a dict with the accumulated counts and coverage counters.
        Absence of extractor output is legitimate — tracked via
        chunks_with_extract/chunks_total.
        Extractor ERRORS are collected and re-surfaced (never dropped).
        """
        empty: dict[str, Any] = {
            "observed_st_counts": {},
            "per_st": {},
            "audit_errors": [],
            "chunks_with_extract": 0,
            "chunks_total": 0,
        }
        if not chunk_dict or not isinstance(chunk_dict, dict):
            return {**empty, "chunks_total": 1}

        st_extract = chunk_dict.get("st_extract")
        if not isinstance(st_extract, dict):
            return {**empty, "chunks_total": 1}

        # Surface any extractor errors (feedback_no_silent_swallow.md).
        audit_errors: list[str] = []
        err = st_extract.get(f"_extract_error_{_AUDIT_EXTRACTOR_ID}")
        if err:
            audit_errors.append(str(err))

        audit_raw = st_extract.get(_AUDIT_EXTRACTOR_ID)
        if not isinstance(audit_raw, dict):
            return {**empty, "audit_errors": audit_errors, "chunks_total": 1}

        # Coerce observed_st_counts: {str -> int}.
        raw_osc = audit_raw.get("observed_st_counts")
        observed_st_counts: dict[str, int] = {}
        if isinstance(raw_osc, dict):
            for st_s, cnt in raw_osc.items():
                try:
                    observed_st_counts[str(st_s)] = int(cnt or 0)
                except (TypeError, ValueError):
                    pass

        # Coerce per_st with three field-presence buckets.
        raw_pst = audit_raw.get("per_st")
        per_st: dict[str, dict[str, Any]] = {}
        if isinstance(raw_pst, dict):
            for st_s, st_data in raw_pst.items():
                if not isinstance(st_data, dict):
                    continue

                def _coerce_counts(src: Any) -> dict[str, int]:
                    out: dict[str, int] = {}
                    for f, c in (src or {}).items():
                        try:
                            out[str(f)] = int(c or 0)
                        except (TypeError, ValueError):
                            pass
                    return out

                per_st[str(st_s)] = {
                    "declared_field_presence": _coerce_counts(
                        st_data.get("declared_field_presence")),
                    "observed_field_presence": _coerce_counts(
                        st_data.get("observed_field_presence")),
                    "new_field_presence": _coerce_counts(
                        st_data.get("new_field_presence")),
                    "rounds": int(st_data.get("rounds") or 0),
                    "has_observed_fields": bool(st_data.get("has_observed_fields", False)),
                }

        return {
            "observed_st_counts": observed_st_counts,
            "per_st": per_st,
            "audit_errors": audit_errors,
            "chunks_with_extract": 1,
            "chunks_total": 1,
        }

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Additively merge accumulators across chunks."""
        if not prev_acc:
            return this_acc if this_acc else {
                "observed_st_counts": {},
                "per_st": {},
                "audit_errors": [],
                "chunks_with_extract": 0,
                "chunks_total": 0,
            }
        if not this_acc:
            return prev_acc

        # Merge observed_st_counts.
        merged_osc: dict[str, int] = dict(prev_acc.get("observed_st_counts") or {})
        for st_s, cnt in (this_acc.get("observed_st_counts") or {}).items():
            merged_osc[st_s] = merged_osc.get(st_s, 0) + int(cnt or 0)

        # Merge per_st (additive across all three presence buckets).
        merged_pst: dict[str, dict[str, Any]] = {}
        all_st_keys: set[str] = (
            set(prev_acc.get("per_st") or {}) | set(this_acc.get("per_st") or {})
        )
        for st_s in all_st_keys:
            p = (prev_acc.get("per_st") or {}).get(st_s) or {}
            t = (this_acc.get("per_st") or {}).get(st_s) or {}

            def _merge_counts(a: dict, b: dict) -> dict[str, int]:
                m: dict[str, int] = dict(a)
                for f, c in b.items():
                    m[f] = m.get(f, 0) + int(c or 0)
                return m

            # has_observed_fields is stable per manifest — True if either chunk reports True.
            has_obs = bool(p.get("has_observed_fields", False)) or bool(
                t.get("has_observed_fields", False)
            )
            rounds = int(p.get("rounds") or 0) + int(t.get("rounds") or 0)
            merged_pst[st_s] = {
                "declared_field_presence": _merge_counts(
                    p.get("declared_field_presence") or {},
                    t.get("declared_field_presence") or {}),
                "observed_field_presence": _merge_counts(
                    p.get("observed_field_presence") or {},
                    t.get("observed_field_presence") or {}),
                "new_field_presence": _merge_counts(
                    p.get("new_field_presence") or {},
                    t.get("new_field_presence") or {}),
                "rounds": rounds,
                "has_observed_fields": has_obs,
            }

        return {
            "observed_st_counts": merged_osc,
            "per_st": merged_pst,
            "audit_errors": list(prev_acc.get("audit_errors") or [])
                           + list(this_acc.get("audit_errors") or []),
            "chunks_with_extract": int(prev_acc.get("chunks_with_extract") or 0)
                                   + int(this_acc.get("chunks_with_extract") or 0),
            "chunks_total": int(prev_acc.get("chunks_total") or 0)
                            + int(this_acc.get("chunks_total") or 0),
        }

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Compare accumulated data against manifest spin_types; write structure_drift.

        Classification:
          FAIL = (a) undeclared ST share > 0.1%
                 (b) signature field presence == 0 on a present ST
          WARN = (a) signature field presence < 90%
                 (b) field in data NOT in signature NOR observed_fields (new_field)
          OK   = none of the above
          unaudited = no extractor output in any chunk
          (A known observed field absent this run is recorded in
           observed_fields_absent — INFORMATIONAL, does NOT flip status:
           optional-field presence is config/mode-dependent.)
        """
        # Absent extractor output → "unaudited" (never silently "ok").
        chunks_with_extract: int = int((final_acc or {}).get("chunks_with_extract") or 0)
        chunks_total: int = int((final_acc or {}).get("chunks_total") or 0)
        audit_errors: list[str] = list((final_acc or {}).get("audit_errors") or [])

        if chunks_with_extract == 0:
            reason = (
                "no signature_audit extractor output found "
                f"({chunks_total} chunks parsed, 0 with extraction data)"
            )
            if audit_errors:
                reason += "; extractor errors: " + "; ".join(audit_errors[:3])
            summary["structure_drift"] = {
                "status": "unaudited",
                "reason": reason,
                "undeclared_sts": [],
                "declared_sts_absent": [],
                "per_st": {},
                "audited_rounds": 0,
                "source": "signature_audit extractor + manifest spin_types",
            }
            return

        # --- Compute totals and gather manifest info ---
        observed_st_counts: dict[str, int] = (final_acc or {}).get("observed_st_counts") or {}
        per_st_acc: dict[str, dict] = (final_acc or {}).get("per_st") or {}

        total_rounds: int = sum(int(v or 0) for v in observed_st_counts.values())

        # Manifest declared STs with their signature and observed_fields.
        _manifest = getattr(ctx, "machine_spec_manifest", None) or {}
        spin_types_block: dict[str, Any] = _manifest.get("spin_types") or {}
        manifest_sts: set[str] = set(spin_types_block.keys())

        # --- Undeclared STs: in data but not in manifest ---
        undeclared_sts: list[dict] = []
        for st_s, cnt in sorted(observed_st_counts.items(), key=lambda x: -int(x[1] or 0)):
            if st_s not in manifest_sts:
                share = int(cnt or 0) / total_rounds if total_rounds > 0 else 0.0
                undeclared_sts.append({"st": st_s, "rounds": int(cnt or 0), "share": share})

        # --- Declared STs absent from data ---
        declared_sts_absent: list[str] = [
            st_s for st_s in sorted(manifest_sts)
            if st_s not in observed_st_counts or int(observed_st_counts.get(st_s) or 0) == 0
        ]

        # --- Per-ST field drift analysis ---
        per_st_out: dict[str, dict] = {}

        for st_s, st_data in per_st_acc.items():
            if st_s not in manifest_sts:
                continue  # undeclared ST — handled above
            rounds_for_st: int = int(observed_st_counts.get(st_s) or 0)
            if rounds_for_st == 0:
                continue

            st_block = spin_types_block.get(st_s) or {}
            declared_sig: list = st_block.get("signature") or []
            observed_inv: list = st_block.get("observed_fields") or []
            has_observed_fields: bool = bool(st_data.get("has_observed_fields", False))

            declared_pres: dict[str, int] = st_data.get("declared_field_presence") or {}
            observed_pres: dict[str, int] = st_data.get("observed_field_presence") or {}
            new_pres: dict[str, int] = st_data.get("new_field_presence") or {}

            # ---- Signature fields (core contract) ----
            sig_missing: dict[str, float] = {}
            for field in declared_sig:
                cnt = declared_pres.get(str(field), 0)
                pct = cnt / rounds_for_st
                if pct < 1.0:
                    sig_missing[str(field)] = round(pct, 6)

            # ---- Observed-inventory fields (envelope) — INFORMATIONAL only ----
            # A known observed field that is entirely ABSENT this run (0%) is
            # recorded for the operator but does NOT flip status: optional-field
            # presence is config/mode-dependent, not a structural invariant.
            obs_absent: list[str] = []
            if has_observed_fields:
                sig_set = frozenset(str(f) for f in declared_sig)
                obs_set = frozenset(str(f) for f in observed_inv) - sig_set
                for field in sorted(obs_set):
                    cnt = observed_pres.get(field, 0)
                    if cnt == 0:
                        obs_absent.append(field)

            # ---- New fields (not in either known set) → the real drift signal ----
            new_fields: dict[str, float] = {}
            for field, cnt in new_pres.items():
                pct = int(cnt or 0) / rounds_for_st
                if pct > 0.0:
                    new_fields[field] = round(pct, 6)

            # ---- observed_fields status for this ST ----
            if not has_observed_fields:
                obs_status = "unaudited_fields"
            elif new_fields:
                obs_status = "warn"
            else:
                obs_status = "ok"

            # Only emit a per_st entry when there is something to report.
            has_anything = (sig_missing or obs_absent
                            or new_fields or obs_status == "unaudited_fields")
            if has_anything:
                per_st_out[st_s] = {
                    "signature_fields_missing": sig_missing,
                    "observed_fields_absent": obs_absent,
                    "new_fields": new_fields,
                    "observed_fields_status": obs_status,
                }

        # --- Classification ---
        status = "ok"

        # FAIL conditions.
        for entry in undeclared_sts:
            if entry["share"] > _FAIL_UNDECLARED_ST_SHARE:
                status = "fail"
                break
        if status != "fail":
            for st_s, st_drift in per_st_out.items():
                for field, pct in st_drift.get("signature_fields_missing", {}).items():
                    if pct == _FAIL_SIG_FIELD_ZERO:
                        status = "fail"
                        break
                if status == "fail":
                    break

        # WARN conditions (only if not already FAIL).
        if status == "ok":
            for st_s, st_drift in per_st_out.items():
                # Signature field degraded (< 90% but > 0).
                for field, pct in st_drift.get("signature_fields_missing", {}).items():
                    if 0 < pct < _WARN_SIG_FIELD_LOW:
                        status = "warn"
                        break
                if status != "ok":
                    break
                # New fields appearing (not in either known set) = the real
                # protocol-growth signal. (observed_fields_absent is recorded
                # informationally above but is NOT a status trigger — see the
                # _WARN_SIG_FIELD_LOW note.)
                if st_drift.get("new_fields"):
                    status = "warn"
                    break

        # Build the output block.
        out: dict[str, Any] = {
            "status": status,
            "undeclared_sts": undeclared_sts,
            "declared_sts_absent": declared_sts_absent,
            "per_st": per_st_out,
            "audited_rounds": total_rounds,
            "source": "signature_audit extractor + manifest spin_types",
        }
        if audit_errors:
            out["audit_errors"] = audit_errors

        summary["structure_drift"] = out


# ---------------------------------------------------------------------------
# Self-registration — fires at module import time (idempotent).
# ---------------------------------------------------------------------------
register(StructureDriftFeature())
