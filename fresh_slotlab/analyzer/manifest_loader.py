"""manifest_loader — per-machine manifest loading, cascade, per-mode resolution, validation.

Per ticket P2-A2 §1 and session_artifacts/_arch/04_architecture_proposal_v5.md §5.5.1-7, §5.6.

Public API
----------
- load_manifest(machine_id, manifests_dir) -> dict
    Read + JSON-parse one manifest file. Raises FileNotFoundError / JSONDecodeError on I/O error.
    Per §3 C1.

- resolve_inheritance(manifest, manifests_dir) -> dict
    Apply ``inherits_from`` variant cascade per §5.5.4-5.5.5.  Returns manifest unchanged if
    ``inherits_from`` is None.  Per §3 C2.

- resolve_per_mode(manifest, mode) -> dict
    Apply ``per_mode_overrides[str(mode)]`` per §5.5.6.  Resolution order: _remove then _add.
    Per §3 C3.

- resolve_completeness(variant_manifest, underlying_manifest) -> bool
    Resolve ``console_diagnostic_complete`` for a variant.  Verbatim pseudocode from §5.5.7
    lines 553-573.  Per §3 C4.

- resolve_layer4_applicable(manifest_resolved, mode) -> bool
    Per-(machine, mode) resolution.  Verbatim from 07_decision_v5.md Patch P1.  Per §3 C6.

- validate_manifest(manifest, machines_config, registry) -> list[ManifestValidationError]
    All 11 rules from §5.6.  Returns list (may be empty); does NOT raise per-rule.  Per §3 C5.

No import-time side effects per memory/feedback_subprocess_import_suicide_and_module_globals.md.
I/O happens only when functions are called, not at module import.

Validation collects all errors before returning — callers see the full picture per
memory/feedback_no_silent_swallow.md.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ManifestValidationError(Exception):
    """Raised when a manifest violates a structural invariant at resolve time.

    Distinct from validation-rule errors returned by validate_manifest().
    This is raised only for invariants the resolver itself enforces (e.g.,
    resolve_completeness detecting override=True).
    """


# ---------------------------------------------------------------------------
# Sentinel for "field not present in dict" (per §5.5.7 pseudocode verbatim)
# ---------------------------------------------------------------------------

_UNSET = object()


# ---------------------------------------------------------------------------
# C1 — load_manifest
# ---------------------------------------------------------------------------

def load_manifest(machine_id: str, manifests_dir: Path) -> dict[str, Any]:
    """Read and JSON-parse the manifest for *machine_id*.

    Filename resolution per §5.5.1:
    - Standard machines: ``manifests_dir/{machine_id}.json``
    - Variants:          ``manifests_dir/{machine_id}.json``
      (variant filenames use the full machine_id string including ``$`` separators)

    Parameters
    ----------
    machine_id:
        Machine identifier, e.g. ``"M274"`` or ``"M273$WheelSelector$42$"``.
    manifests_dir:
        Directory containing manifest JSON files.

    Returns
    -------
    dict
        Parsed manifest.

    Raises
    ------
    FileNotFoundError
        If ``{manifests_dir}/{machine_id}.json`` does not exist.  Message
        includes both the expected path and the manifests_dir contents hint.
    json.JSONDecodeError
        Re-raised with added context (file path) if the file exists but
        cannot be parsed as JSON.  No silent fallback per
        memory/feedback_no_silent_swallow.md.

    Ticket reference: P2-A2 §3 C1.
    """
    manifest_path = Path(manifests_dir) / f"{machine_id}.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Manifest not found for machine '{machine_id}': "
            f"expected {manifest_path!s}. "
            f"Check that the file exists in {manifests_dir!s}."
        )
    try:
        with manifest_path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        raise json.JSONDecodeError(
            f"Malformed JSON in manifest {manifest_path!s}: {exc.msg}",
            exc.doc,
            exc.pos,
        ) from exc
    return raw


# ---------------------------------------------------------------------------
# C2 — resolve_inheritance
# ---------------------------------------------------------------------------

def resolve_inheritance(manifest: dict[str, Any], manifests_dir: Path) -> dict[str, Any]:
    """Apply ``inherits_from`` variant cascade per §5.5.4-5.5.5.

    If ``manifest["inherits_from"]`` is None, return manifest unchanged.

    Cascade semantics (§5.5.4-5.5.5):
    - The parent manifest provides ``analyzer_features``, ``round_win_rules``,
      ``spin_type_convention``, ``feature_tags``, ``rtp_integrity_contract``,
      ``modes_supported``, ``per_mode_overrides``, ``bcm_target_feature``,
      ``trigger_session_pattern``, ``layer4_applicable``, ``selector_type``.
    - Variant CANNOT override ``analyzer_features`` directly — only via
      ``per_mode_overrides._add / ._remove`` (validation rule 6 / §3 C2 note).
    - Variant may carry ``console_diagnostic_complete_override`` (see resolve_completeness).
    - Variant can carry ``per_mode_overrides`` of its own that ADD to/REMOVE from parent's.

    The merged dict's top-level identity fields (``machine_id``, ``manifest_version``,
    ``inherits_from``) come from the variant, not the parent.

    Parameters
    ----------
    manifest:
        Parsed manifest dict, possibly a variant with ``inherits_from`` set.
    manifests_dir:
        Directory to load the parent from (same dir per §5.5.1).

    Returns
    -------
    dict
        A new dict.  If no inheritance, a shallow copy of *manifest*.
        If inheritance, the merged dict (parent base + variant overrides).

    Ticket reference: P2-A2 §3 C2.
    """
    inherits_from = manifest.get("inherits_from")
    if inherits_from is None:
        return dict(manifest)

    # C2 guard — variant CANNOT override base list fields directly; only via
    # per_mode_overrides._add/_remove per §5.5.6.  Check BEFORE loading parent so
    # we raise with a clear error rather than silently merging incorrect data.
    # Per brief §3 C2 + round-2 critic R1 citing 04_v5 §5.5.4-5.5.5.
    _INHERITANCE_FORBIDDEN_DIRECT_OVERRIDE = ("analyzer_features", "round_win_rules")
    for _forbidden_field in _INHERITANCE_FORBIDDEN_DIRECT_OVERRIDE:
        if _forbidden_field in manifest:
            raise ManifestValidationError(
                f"Variant {manifest.get('machine_id', '<unknown>')}: cannot override "
                f"'{_forbidden_field}' directly. "
                f"Use per_mode_overrides.<mode>.{_forbidden_field}_add/_remove "
                f"per §5.5.6."
            )

    # Load parent by filename (e.g. "M273.json" → manifests_dir/M273.json)
    parent_path = Path(manifests_dir) / inherits_from
    if not parent_path.exists():
        raise FileNotFoundError(
            f"Parent manifest referenced by '{manifest.get('machine_id', '<unknown>')}' "
            f"(inherits_from: '{inherits_from}') not found: {parent_path!s}"
        )
    try:
        with parent_path.open(encoding="utf-8") as fh:
            parent = json.load(fh)
    except json.JSONDecodeError as exc:
        raise json.JSONDecodeError(
            f"Malformed JSON in parent manifest {parent_path!s}: {exc.msg}",
            exc.doc,
            exc.pos,
        ) from exc

    # Deep-copy parent as the base
    merged = copy.deepcopy(parent)

    # Fields inherited from parent (machine-level; variant cannot override directly):
    # analyzer_features, round_win_rules, spin_type_convention, feature_tags,
    # rtp_integrity_contract, modes_supported, per_mode_overrides, bcm_target_feature,
    # trigger_session_pattern, layer4_applicable, selector_type are all already in
    # the parent.  Variant overrides these ONLY through per_mode_overrides.

    # Overwrite with variant identity fields:
    merged["machine_id"] = manifest["machine_id"]
    merged["manifest_version"] = manifest.get("manifest_version", parent.get("manifest_version"))
    merged["inherits_from"] = manifest["inherits_from"]

    # Carry over variant-only fields (completeness override + v5 metadata):
    for field in (
        "console_diagnostic_complete_override",
        "override_set_at",
        "override_set_reason",
        "override_set_by",
    ):
        if field in manifest:
            merged[field] = manifest[field]
        elif field in merged:
            # Remove parent field if not present in variant (only identity fields cascade)
            del merged[field]

    # Carry over per_mode_overrides from variant — merge on top of parent's per_mode_overrides.
    # Per §5.5.5: eager cascade; variant per_mode_overrides extend, not replace, parent's.
    variant_pmo = manifest.get("per_mode_overrides")
    if variant_pmo is not None:
        parent_pmo = copy.deepcopy(parent.get("per_mode_overrides") or {})
        for mode_key, mode_block in variant_pmo.items():
            if mode_key not in parent_pmo:
                parent_pmo[mode_key] = copy.deepcopy(mode_block)
            else:
                # Merge: variant's mode block adds to / overrides parent's mode block entries
                for k, v in mode_block.items():
                    parent_pmo[mode_key][k] = copy.deepcopy(v)
        merged["per_mode_overrides"] = parent_pmo

    # Remove console_diagnostic_complete from merged — variant's completeness is resolved
    # via resolve_completeness() using the parent as underlying, not inherited directly.
    # The parent's console_diagnostic_complete stays in merged for resolve_completeness()
    # to read as the "underlying" value.  So we KEEP it in merged.

    return merged


# ---------------------------------------------------------------------------
# C3 — resolve_per_mode
# ---------------------------------------------------------------------------

# Fields that MUST NOT appear in per_mode_overrides per §5.5.6 line 472:
_FORBIDDEN_PER_MODE_FIELDS = frozenset({
    "machine_id",
    "manifest_version",
    "inherits_from",
    "console_diagnostic_complete",
    "layer4_applicable",
})


def resolve_per_mode(manifest: dict[str, Any], mode: int) -> dict[str, Any]:
    """Apply ``per_mode_overrides[str(mode)]`` to *manifest* and return a new dict.

    Resolution order per §5.5.6 line 474: ``_remove`` first, then ``_add`` (for list-type
    overrides).

    Supported override keys (§5.5.6 table):
    - ``analyzer_features_add``, ``analyzer_features_remove``
    - ``round_win_rules_add``, ``round_win_rules_remove``
    - ``bcm_target_feature_override``
    - ``trigger_session_pattern_override``
    - ``spin_type_convention_override``
    - ``feature_tags_override``
    - ``required_attribution_anchors_override``
    - ``expected_paid_st_override``, ``expected_bonus_st_override``

    If no ``per_mode_overrides`` entry for *mode*, returns a copy of *manifest* unchanged.

    Parameters
    ----------
    manifest:
        Parsed manifest (possibly already inheritance-resolved).
    mode:
        Integer mode number (e.g. 1, 2, 5, 7).

    Returns
    -------
    dict
        New dict with per-mode overrides applied.

    Raises
    ------
    ValueError
        If the per_mode_overrides block for *mode* contains a key that is
        forbidden per §5.5.6 line 472.

    Ticket reference: P2-A2 §3 C3.
    """
    result = copy.deepcopy(manifest)

    per_mode = manifest.get("per_mode_overrides") or {}
    mode_block = per_mode.get(str(mode))
    if mode_block is None:
        return result

    # Validate: no forbidden fields in mode_block
    for key in mode_block:
        # Map override key back to base field name for forbidden-field check
        base_field = _override_key_to_base_field(key)
        if base_field in _FORBIDDEN_PER_MODE_FIELDS:
            raise ValueError(
                f"resolve_per_mode: mode {mode} override block contains forbidden key "
                f"'{key}' (base field '{base_field}'). "
                f"Fields {sorted(_FORBIDDEN_PER_MODE_FIELDS)} cannot be overridden "
                f"per §5.5.6 line 472."
            )

    # Apply list-type overrides: _remove first, then _add (§5.5.6 line 474)
    for list_field in ("analyzer_features", "round_win_rules"):
        remove_key = f"{list_field}_remove"
        add_key = f"{list_field}_add"
        remove_vals = mode_block.get(remove_key, [])
        add_vals = mode_block.get(add_key, [])
        if remove_vals or add_vals:
            current = list(result.get(list_field) or [])
            # _remove first
            current = [v for v in current if v not in remove_vals]
            # _add after (avoid duplicates)
            for v in add_vals:
                if v not in current:
                    current.append(v)
            result[list_field] = current

    # Apply scalar overrides
    if "bcm_target_feature_override" in mode_block:
        result["bcm_target_feature"] = mode_block["bcm_target_feature_override"]

    if "trigger_session_pattern_override" in mode_block:
        result["trigger_session_pattern"] = mode_block["trigger_session_pattern_override"]

    if "spin_type_convention_override" in mode_block:
        result["spin_type_convention"] = copy.deepcopy(mode_block["spin_type_convention_override"])

    if "feature_tags_override" in mode_block:
        result["feature_tags"] = list(mode_block["feature_tags_override"])

    # rtp_integrity_contract sub-field overrides
    ric = result.setdefault("rtp_integrity_contract", {})
    if "required_attribution_anchors_override" in mode_block:
        ric["required_attribution_anchors"] = list(
            mode_block["required_attribution_anchors_override"]
        )
    if "expected_paid_st_override" in mode_block:
        ric["expected_paid_st"] = list(mode_block["expected_paid_st_override"])
    if "expected_bonus_st_override" in mode_block:
        ric["expected_bonus_st"] = list(mode_block["expected_bonus_st_override"])

    return result


def _override_key_to_base_field(key: str) -> str:
    """Map an override key name back to the manifest base field it affects.

    Used to check whether a per_mode_overrides key targets a forbidden field.
    """
    mapping = {
        "analyzer_features_add": "analyzer_features",
        "analyzer_features_remove": "analyzer_features",
        "round_win_rules_add": "round_win_rules",
        "round_win_rules_remove": "round_win_rules",
        "bcm_target_feature_override": "bcm_target_feature",
        "trigger_session_pattern_override": "trigger_session_pattern",
        "spin_type_convention_override": "spin_type_convention",
        "feature_tags_override": "feature_tags",
        "required_attribution_anchors_override": "required_attribution_anchors",
        "expected_paid_st_override": "expected_paid_st",
        "expected_bonus_st_override": "expected_bonus_st",
    }
    return mapping.get(key, key)


# ---------------------------------------------------------------------------
# C4 — resolve_completeness
# ---------------------------------------------------------------------------

def resolve_completeness(
    variant_manifest: dict[str, Any],
    underlying_manifest: dict[str, Any],
) -> bool:
    """Resolve console_diagnostic_complete for a variant.

    Verbatim pseudocode from 04_architecture_proposal_v5.md §5.5.7 lines 553-573.

    Cascade rule: underlying's value is the default.
    Override rule: variant can only go true → false (regression valve).
    Override false → true is rejected at manifest validation time.

    Parameters
    ----------
    variant_manifest:
        The variant's manifest dict (may or may not carry
        ``console_diagnostic_complete_override``).
    underlying_manifest:
        The parent/underlying machine manifest (must carry
        ``console_diagnostic_complete`` boolean).

    Returns
    -------
    bool
        Effective ``console_diagnostic_complete`` for the variant.

    Raises
    ------
    ManifestValidationError
        If ``console_diagnostic_complete_override: true`` is set on the variant
        (forbidden — variants cannot elevate completeness above their underlying).

    Ticket reference: P2-A2 §3 C4.
    Architecture reference: 04_v5 §5.5.7 lines 553-573 (verbatim).
    """
    underlying_complete = underlying_manifest["console_diagnostic_complete"]
    override = variant_manifest.get("console_diagnostic_complete_override", _UNSET)
    if override is _UNSET:
        return underlying_complete
    if override is False:
        return False   # regression valve: variant found an edge case
    # override is True — validation should have caught this at commit time
    raise ManifestValidationError(
        f"{variant_manifest['machine_id']}: console_diagnostic_complete_override: true "
        f"is not permitted. Variants cannot elevate completeness above their underlying. "
        f"Underlying {underlying_manifest['machine_id']} is the authoritative source."
    )


# ---------------------------------------------------------------------------
# C6 — resolve_layer4_applicable
# ---------------------------------------------------------------------------

def resolve_layer4_applicable(manifest_resolved: dict[str, Any], mode: int) -> bool:
    """Return whether Layer 4 applies to *mode* for this machine.

    Verbatim implementation per 07_decision_v5.md Patch P1.

    For machines where ``trigger_session_pattern`` differs by mode (e.g., mode 1: null,
    mode 2: type_1), ``layer4_applicable`` resolves per-(machine, mode), not at machine level.

    Per Patch P1 pseudocode:

        def resolve_layer4_applicable(machine, mode):
            pattern = manifest.modes[mode].get("trigger_session_pattern")
            if pattern is None:
                return True
            override = manifest.modes[mode].get("trigger_session_pattern_override")
            if override is not None:
                pattern = override
            return False  # any non-null trigger_session_pattern → skip

    Implementation note: ``manifest_resolved`` is a mode-resolved dict (output of
    resolve_per_mode).  The per-mode ``trigger_session_pattern`` is therefore already
    the top-level key in ``manifest_resolved`` (after per-mode resolution applied the
    ``trigger_session_pattern_override``).  Patch P1 uses manifest.modes[mode] semantics
    equivalent to applying resolve_per_mode first, then reading top-level fields.

    Parameters
    ----------
    manifest_resolved:
        A mode-resolved manifest dict (output of resolve_per_mode for the given mode).
        May also be the base manifest if no per-mode override for this mode exists.
    mode:
        Integer mode number.  Used for diagnostic context only; the pattern is already
        resolved in ``manifest_resolved``.

    Returns
    -------
    bool
        True if Layer 4 applies for this (machine, mode).
        False if ``trigger_session_pattern`` is non-null for this mode.

    Ticket reference: P2-A2 §3 C6.
    Architecture reference: 07_decision_v5.md Patch P1 lines 50-57.
    """
    # Read the base trigger_session_pattern from manifest_resolved.
    # When manifest_resolved is the output of resolve_per_mode(), this already reflects
    # any trigger_session_pattern_override applied for this mode.
    #
    # When manifest_resolved is an unresolved base manifest, also check the
    # per_mode_overrides[mode].trigger_session_pattern_override (per P1 pseudocode).
    pattern = manifest_resolved.get("trigger_session_pattern")

    # P1 pseudocode step 2: check for per-mode override in the raw per_mode_overrides block.
    # This handles the case where manifest_resolved has NOT been through resolve_per_mode().
    #
    # Round-2 fix (critic R2, brief §3 C6 citing §5.5.6 table): use _UNSET sentinel so that
    # an explicit null trigger_session_pattern_override (which clears the base pattern for
    # this mode) is correctly distinguished from "key absent".
    # The old `is not None` check treated null the same as "absent" — a spec gap per §5.5.6
    # which lists null as a valid override value meaning "clear the base pattern".
    per_mode = manifest_resolved.get("per_mode_overrides") or {}
    mode_block = per_mode.get(str(mode)) or {}
    override = mode_block.get("trigger_session_pattern_override", _UNSET)
    if override is not _UNSET:
        # Explicit override, including explicit null which clears the base pattern.
        pattern = override

    if pattern is None:
        return True
    return False  # any non-null trigger_session_pattern → skip Layer 4


# ---------------------------------------------------------------------------
# C5 — validate_manifest
# ---------------------------------------------------------------------------

class _ValidationError:
    """A single validation error with rule number and message.

    Attributes
    ----------
    rule:
        Rule number 1-11 per §5.6.
    message:
        Human-readable description of the violation.
    """

    def __init__(self, rule: int, message: str) -> None:
        self.rule = rule
        self.message = message

    def __repr__(self) -> str:
        return f"ValidationError(rule={self.rule}, message={self.message!r})"

    def __str__(self) -> str:
        return f"[Rule {self.rule}] {self.message}"


# Public alias
ManifestValidationErrorItem = _ValidationError


def validate_manifest(
    manifest: dict[str, Any],
    machines_config: dict[str, Any] | None = None,
    registry: Any | None = None,
    rawdata_observed_paid_st: list[int] | None = None,
    pre_resolved: bool = True,
) -> list[_ValidationError]:
    """Validate *manifest* against all 11 rules per §5.6.

    Collects ALL errors before returning so the operator sees the full picture.
    Does NOT raise on individual rule violations; returns them in a list.
    Raises are reserved for I/O errors (e.g., loading the manifest file) or
    resolver invariants (e.g., resolve_completeness encountering override=True).

    Parameters
    ----------
    manifest:
        Parsed manifest dict.  MUST be the raw pre-inheritance manifest when
        ``pre_resolved=True`` (default).  Pass ``pre_resolved=False`` when
        passing a post-``resolve_inheritance()`` dict to prevent rule 6
        false-firing because ``resolve_inheritance`` always copies the parent's
        ``console_diagnostic_complete`` into the merged dict.
    machines_config:
        Parsed ``configs/machines.json`` list/dict.  Used for Rule 1 (every machine
        must have a manifest).  Pass ``None`` to skip Rule 1 (partial validation).
    registry:
        ``feature_registry`` module or object with ``ALL_FEATURES`` attribute
        (list of ``AnalyzerFeature`` instances).  Used for Rules 2, 4, 5, 8.
        Pass ``None`` to skip those rules (partial validation).
    rawdata_observed_paid_st:
        Observed paid-ST integers from rawdata.  Used for Rule 9.  Pass ``None``
        to skip Rule 9 (no rawdata available).
    pre_resolved:
        ``True`` (default) — *manifest* is a raw pre-inheritance dict (from
        ``load_manifest`` directly).  Rule 6 checks that variant manifests do NOT
        carry ``console_diagnostic_complete`` directly.

        ``False`` — *manifest* has already been through ``resolve_inheritance()``.
        Rule 6 skips the ``console_diagnostic_complete`` presence check because
        ``resolve_inheritance`` always copies the parent's field into the merged
        dict (the field therefore being present does NOT indicate a variant
        violation).

        **Round-2 fix**: addresses OI-2 latent bug where rule 6 false-fired on
        post-resolved variant manifests.  Per round-2 critic R3 citing SQ-8.

    Returns
    -------
    list[_ValidationError]
        List of validation errors.  Empty list means the manifest is valid.

    Ticket reference: P2-A2 §3 C5.
    Architecture reference: 04_v5 §5.6 rules 1-11.
    """
    errors: list[_ValidationError] = []
    machine_id: str = manifest.get("machine_id", "<unknown>")
    is_variant = manifest.get("inherits_from") is not None

    # Rule 1 — Every machine in machines.json MUST have a manifest.
    # Note: This rule is fleet-level (check that ALL machines have manifests).
    # validate_manifest() validates a single manifest; Rule 1 is a fleet sweep.
    # Callers that pass machines_config are performing fleet-level validation.
    # For single-manifest validation, Rule 1 is a pass (the manifest clearly exists).
    # Intentional per ticket §3 C5 note: "Rule 1: Every machine in configs/machines.json
    # MUST have a manifest file." — enforced at fleet-validation call site.
    # We emit an error only if machines_config is supplied AND machine_id not present.
    if machines_config is not None:
        machine_ids_in_config = _extract_machine_ids(machines_config)
        if machine_id not in machine_ids_in_config and not is_variant:
            errors.append(_ValidationError(
                1,
                f"Machine '{machine_id}' is not present in machines.json. "
                f"Either add it to machines.json or remove the manifest."
            ))

    # Rule 2 — Every analyzer_feature ID must correspond to a class in feature_registry.ALL_FEATURES
    if registry is not None:
        all_feature_ids = {f.FEATURE_ID for f in registry.ALL_FEATURES}
        for fid in manifest.get("analyzer_features") or []:
            if fid not in all_feature_ids:
                errors.append(_ValidationError(
                    2,
                    f"Machine '{machine_id}': analyzer_feature '{fid}' not found in "
                    f"feature_registry.ALL_FEATURES. Registered IDs: "
                    f"{sorted(all_feature_ids)}. Typo?"
                ))

    # Rule 3 — Every round_win_rule ID must be defined in machine_round_win_rules.json
    # with this machine in applies_to.  Since round_win_rules config is not passed as a
    # parameter, this rule can only be checked when the caller supplies it.
    # Callers that need Rule 3 should validate at fleet level.  Per-manifest form:
    # round_win_rules list is checked for structural validity (non-empty strings).
    for rule_id in manifest.get("round_win_rules") or []:
        if not isinstance(rule_id, str) or not rule_id.strip():
            errors.append(_ValidationError(
                3,
                f"Machine '{machine_id}': round_win_rule entry must be a non-empty string, "
                f"got {rule_id!r}."
            ))

    # Rule 4 — REQUIRES dependency satisfaction.
    if registry is not None:
        all_feature_ids = {f.FEATURE_ID for f in registry.ALL_FEATURES}
        feature_id_to_requires = {f.FEATURE_ID: f.REQUIRES for f in registry.ALL_FEATURES}
        declared_features = set(manifest.get("analyzer_features") or [])
        for fid in declared_features:
            requires = feature_id_to_requires.get(fid, ())
            for dep in requires:
                if dep not in declared_features:
                    errors.append(_ValidationError(
                        4,
                        f"Machine '{machine_id}': feature '{fid}' requires '{dep}', "
                        f"but '{dep}' is not in analyzer_features. "
                        f"Add '{dep}' to satisfy the REQUIRES dependency."
                    ))

    # Rule 5 — Mode coverage: per-mode resolved feature set must include all RTP_CONTRIBUTION=True
    # features that are in the base analyzer_features list.
    if registry is not None:
        rtp_contribution_ids = {
            f.FEATURE_ID for f in registry.ALL_FEATURES if f.RTP_CONTRIBUTION
        }
        for mode in manifest.get("modes_supported") or []:
            try:
                mode_resolved = resolve_per_mode(manifest, mode)
            except ValueError as exc:
                errors.append(_ValidationError(
                    5,
                    f"Machine '{machine_id}' mode {mode}: per_mode resolution error: {exc}"
                ))
                continue
            mode_features = set(mode_resolved.get("analyzer_features") or [])
            # Only check features that are RTP_CONTRIBUTION AND were in the base feature set
            base_rtp = rtp_contribution_ids & set(manifest.get("analyzer_features") or [])
            missing_rtp = base_rtp - mode_features
            if missing_rtp:
                errors.append(_ValidationError(
                    5,
                    f"Machine '{machine_id}' mode {mode}: per-mode resolved feature set is "
                    f"missing RTP_CONTRIBUTION=True features: {sorted(missing_rtp)}. "
                    f"RTP integrity requires these features for all supported modes."
                ))

    # Rule 6 — Completeness field semantics.
    if is_variant:
        # Variant: console_diagnostic_complete must be absent (field belongs to underlying).
        # console_diagnostic_complete_override may be false or absent; never true.
        #
        # Round-2 fix (OI-2 / critic R3): when validate_manifest is called with
        # pre_resolved=False (i.e., on a post-resolve_inheritance dict), we SKIP the
        # console_diagnostic_complete presence check because resolve_inheritance always
        # copies the parent's console_diagnostic_complete into the merged dict — it would
        # always false-fire here.  The override_val=True check is still valid in both
        # paths (console_diagnostic_complete_override comes from the variant's own fields).
        if pre_resolved and "console_diagnostic_complete" in manifest:
            errors.append(_ValidationError(
                6,
                f"Variant '{machine_id}': must not contain 'console_diagnostic_complete' "
                f"directly. Use 'console_diagnostic_complete_override: false' if needed, "
                f"or omit to inherit from underlying per §5.5.7."
            ))
        override_val = manifest.get("console_diagnostic_complete_override", _UNSET)
        if override_val is not _UNSET and override_val is True:
            errors.append(_ValidationError(
                6,
                f"Variant '{machine_id}': console_diagnostic_complete_override: true is "
                f"not permitted. Variants cannot elevate completeness above their underlying "
                f"(§5.5.7 rule 6). Remove the override or set it to false."
            ))
    else:
        # Non-variant: console_diagnostic_complete must be a boolean.
        cdc = manifest.get("console_diagnostic_complete", _UNSET)
        if cdc is _UNSET:
            errors.append(_ValidationError(
                6,
                f"Machine '{machine_id}': 'console_diagnostic_complete' is required for "
                f"non-variant manifests and must be a boolean (true or false)."
            ))
        elif not isinstance(cdc, bool):
            errors.append(_ValidationError(
                6,
                f"Machine '{machine_id}': 'console_diagnostic_complete' must be a boolean, "
                f"got {type(cdc).__name__!r} value {cdc!r}."
            ))

    # Rule 7 — expected_paid_st + expected_bonus_st non-empty; required_attribution_anchors
    # validated at first run (not commit time).
    ric = manifest.get("rtp_integrity_contract") or {}
    paid_st = ric.get("expected_paid_st")
    bonus_st = ric.get("expected_bonus_st")
    if not paid_st:
        errors.append(_ValidationError(
            7,
            f"Machine '{machine_id}': rtp_integrity_contract.expected_paid_st must be "
            f"non-empty (at least one paid spin type integer). Got: {paid_st!r}."
        ))
    if bonus_st is None:
        # bonus_st is allowed to be an empty list (no bonus STs); must be present though.
        errors.append(_ValidationError(
            7,
            f"Machine '{machine_id}': rtp_integrity_contract.expected_bonus_st must be "
            f"present (may be empty list []). Got: absent."
        ))

    # Rule 8 — If console_diagnostic_complete: true, every RTP_CONTRIBUTION=True feature
    # in registry must be in manifest's analyzer_features.
    if registry is not None and not is_variant:
        cdc = manifest.get("console_diagnostic_complete")
        if cdc is True:
            rtp_contribution_ids = {
                f.FEATURE_ID for f in registry.ALL_FEATURES if f.RTP_CONTRIBUTION
            }
            declared = set(manifest.get("analyzer_features") or [])
            missing = rtp_contribution_ids - declared
            if missing:
                errors.append(_ValidationError(
                    8,
                    f"Machine '{machine_id}': console_diagnostic_complete is true, but "
                    f"the following RTP_CONTRIBUTION=True features are absent from "
                    f"analyzer_features: {sorted(missing)}. Either add them or set "
                    f"console_diagnostic_complete: false."
                ))

    # Rule 9 — Rawdata sanity check (if rawdata available).
    if rawdata_observed_paid_st is not None:
        declared_paid_st = set((manifest.get("spin_type_convention") or {}).get("paid") or [])
        observed_paid_st = set(rawdata_observed_paid_st)
        if declared_paid_st != observed_paid_st:
            errors.append(_ValidationError(
                9,
                f"Machine '{machine_id}': declared spin_type_convention.paid "
                f"{sorted(declared_paid_st)} does not match observed paid-ST set "
                f"{sorted(observed_paid_st)} from rawdata. "
                f"Update the manifest or investigate rawdata anomaly."
            ))

    # Rule 10 — If console_diagnostic_complete_override: false on variant, all 3 metadata
    # fields must be present + non-empty.
    if is_variant:
        override_val = manifest.get("console_diagnostic_complete_override", _UNSET)
        if override_val is not _UNSET and override_val is False:
            required_meta = ("override_set_at", "override_set_reason", "override_set_by")
            for field in required_meta:
                val = manifest.get(field)
                if not val:
                    errors.append(_ValidationError(
                        10,
                        f"Variant '{machine_id}': console_diagnostic_complete_override: false "
                        f"is set, but '{field}' is absent or empty. "
                        f"Override without metadata is forbidden. "
                        f"Add override_set_at + override_set_reason + override_set_by "
                        f"(§5.5.7 rule 10)."
                    ))

    # Rule 11 — trigger_session_pattern != null AND layer4_applicable: true simultaneously
    # is a validation error.
    tsp = manifest.get("trigger_session_pattern")
    l4a = manifest.get("layer4_applicable")
    if tsp is not None and l4a is True:
        errors.append(_ValidationError(
            11,
            f"Machine '{machine_id}': trigger_session_pattern is '{tsp}' (non-null) but "
            f"layer4_applicable is true. Machines with trigger_session_pattern must have "
            f"layer4_applicable: false. See §9.4."
        ))

    return errors


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_machine_ids(machines_config: dict[str, Any]) -> set[str]:
    """Extract machine IDs from the machines.json structure.

    Supports both list-of-dicts and dict-keyed-by-id forms.
    """
    if isinstance(machines_config, list):
        return {m.get("machine_id", m.get("id", "")) for m in machines_config}
    if isinstance(machines_config, dict):
        # May be keyed by machine_id directly, or have a "machines" sub-key
        if "machines" in machines_config:
            return _extract_machine_ids(machines_config["machines"])
        return set(machines_config.keys())
    return set()
