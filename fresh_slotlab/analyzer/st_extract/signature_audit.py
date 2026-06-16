"""Per-ST signature audit extractor.

Runs on every machine whose manifest declares "signature" arrays on its
SpinTypes.  Per round it tallies:
  - ST occurrence count
  - For STs WITH a declared signature:
      - per-declared-field presence count (fields in signature)
      - per-observed-field presence count (fields in observed_fields but NOT
        in signature; these are the "envelope" fields known from onboarding)
      - per-new-field presence count (fields seen in data that are in NEITHER
        signature NOR observed_fields — genuine protocol growth signal)

Distinction between the three buckets
--------------------------------------
  signature fields    = core/reuse contract (cardinal rule 4).  Must stay
                        present.  Missing = contract breach (FAIL).
  observed_fields     = complete field inventory from onboarding (st_inventory).
                        Envelope fields known to be there but not part of the
                        core contract.  Disappearing or degraded = WARN.
  new fields          = fields not in either set.  Appearance = WARN (protocol
                        growth signal); a new field never silently becomes "ok".

finalize_chunk() returns:

  {
    "observed_st_counts": {<st_str>: int, ...},
    "per_st": {
      <st_str>: {
        "declared_field_presence":  {<field>: int, ...},   # signature fields
        "observed_field_presence":  {<field>: int, ...},   # observed - signature
        "new_field_presence":       {<field>: int, ...},   # neither set
        "rounds": int,
        "has_observed_fields": bool   # False when manifest has no observed_fields
                                      # for this ST (explicit "unaudited_fields")
      },
      ...
    }
  }

Only STs WITH a declared signature contribute a "per_st" entry; STs without
a signature only appear in "observed_st_counts".

Design invariants honored
--------------------------
- feedback_subprocess_import_suicide_and_module_globals: no import-time I/O;
  no module globals mutated after initial registration.
- feedback_no_silent_swallow: errors in observe_round accumulate in
  _obs_errors (parser surfaces them); finalize_chunk clears its own state
  defensively per the _base.py snapshot/reset contract.
- LEAN implementation: all frozensets are precomputed once at clone_for_manifest;
  per-round logic is a single pass over round_dict.items() with bucket routing.
- Base-excluded (not in _CLOSURE_FILES): editing this extractor re-flags only
  machines whose manifests declare "signature" on at least one ST.

DECLARED_IN_KEY = "signature" — get_extractors_for_manifest() includes this
extractor when any ST block carries a "signature" key.  All 4 registered
manifests declare it on every ST (verified 2026-06-12).

Per the STExtractor snapshot/reset contract (_base.py): finalize_chunk
RESETS all chunk-level state so this instance can be reused across chunks
by the report engine.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, ClassVar

try:
    from fresh_slotlab.analyzer.st_extract._base import STExtractor
    from fresh_slotlab.analyzer.st_extract import register_extractor
except ImportError:
    from analyzer.st_extract._base import STExtractor  # type: ignore[no-redef]
    from analyzer.st_extract import register_extractor  # type: ignore[no-redef]

# Keys that are internal protocol artifacts, not semantic round fields.
# These are skipped when counting new fields so we don't flag the
# parser's own injected keys as "new_field drift".
_INTERNAL_PREFIXES: tuple[str, ...] = ("_",)

# Maximum number of distinct new fields we track per ST per chunk.
# Keeps memory bounded on adversarially-wide round dicts.
_MAX_NEW_TRACKED: int = 50


def _is_internal_key(k: str) -> bool:
    """Return True if *k* is an internal/underscore key that should be skipped."""
    return k.startswith(_INTERNAL_PREFIXES)


class SignatureAuditExtractor(STExtractor):
    """Per-ST field-presence auditor.

    Tallies:
      - declared_field_presence:  per-signature field occurrence count
      - observed_field_presence:  per-observed_fields-only field occurrence count
      - new_field_presence:       fields in neither signature nor observed_fields
    """

    EXTRACTOR_ID: ClassVar[str] = "signature_audit"
    DECLARED_IN_KEY: ClassVar[str] = "signature"

    def __init__(self, manifest: dict) -> None:
        self._manifest = manifest

        # Precompute per-ST frozensets once at construction time.
        # _st_signatures: {st_int -> frozenset[str]}  (STs with "signature")
        # _st_observed_only: {st_int -> frozenset[str]}  (observed_fields - signature;
        #                     empty frozenset when no observed_fields declared)
        # _st_has_observed: {st_int -> bool}  (False = no observed_fields key at all)
        self._st_signatures: dict[int, frozenset[str]] = {}
        self._st_observed_only: dict[int, frozenset[str]] = {}
        self._st_has_observed: dict[int, bool] = {}

        spin_types: dict[str, Any] = manifest.get("spin_types") or {}
        for st_str, st_block in spin_types.items():
            if not isinstance(st_block, dict):
                continue
            sig = st_block.get("signature")
            if not isinstance(sig, list) or not sig:
                continue
            try:
                st_int = int(st_str)
            except (TypeError, ValueError):
                continue

            sig_set: frozenset[str] = frozenset(str(f) for f in sig)
            self._st_signatures[st_int] = sig_set

            obs_raw = st_block.get("observed_fields")
            if isinstance(obs_raw, list) and obs_raw:
                obs_set = frozenset(str(f) for f in obs_raw)
                # observed_only = fields that are in observed_fields but NOT in
                # signature (these are envelope fields tracked separately).
                self._st_observed_only[st_int] = obs_set - sig_set
                self._st_has_observed[st_int] = True
            else:
                self._st_observed_only[st_int] = frozenset()
                self._st_has_observed[st_int] = False

        # Chunk-level state (reset in finalize_chunk).
        self._init_chunk_state()

        # Error accumulators — per _base.py contract.
        self._obs_errors: list[str] = []
        self._begin_robot_error: str | None = None

    def _init_chunk_state(self) -> None:
        """Initialise (or reset) all chunk-level accumulators."""
        # observed_st_counts[st_int] = total rounds seen for that ST in this chunk.
        self._observed_st_counts: dict[int, int] = defaultdict(int)
        # per-ST signature field presence: {st_int -> {field -> count}}
        self._declared_presence: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # per-ST observed-only field presence: {st_int -> {field -> count}}
        self._observed_presence: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # per-ST new-field presence: {st_int -> {field -> count}}
        self._new_presence: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    @classmethod
    def clone_for_manifest(cls, manifest: dict) -> "SignatureAuditExtractor":
        return cls(manifest)

    def begin_robot(self, robot_ctx: dict) -> None:
        """No per-robot state needed; satisfies the ABC contract."""
        pass

    def observe_round(
        self,
        round_dict: dict,
        spin_type: int,
        round_ctx: dict,  # noqa: ARG002
    ) -> None:
        """Accumulate per-round signal.

        For each round:
        (a) Tally ST occurrence.
        (b) For STs with a declared signature:
            - count presence of each declared (signature) field.
            - count presence of each observed-only field.
            - count presence of new fields (in neither set, non-internal).

        Performance: a single pass over round_dict.items() classifies every
        field into one of the three buckets.  New-field tracking has a capacity
        guard (_MAX_NEW_TRACKED) to bound per-chunk memory.
        """
        self._observed_st_counts[spin_type] += 1

        declared_fields = self._st_signatures.get(spin_type)
        if declared_fields is None:
            # No signature declared for this ST — only observation count.
            return

        if not isinstance(round_dict, dict):
            return

        observed_only = self._st_observed_only.get(spin_type, frozenset())
        all_known = declared_fields | observed_only  # union of both known sets

        dec_map = self._declared_presence[spin_type]
        obs_map = self._observed_presence[spin_type]
        new_map = self._new_presence[spin_type]
        new_full = len(new_map) >= _MAX_NEW_TRACKED

        for field, value in round_dict.items():
            if value is None:
                continue
            if _is_internal_key(field):
                continue
            if field in declared_fields:
                dec_map[field] += 1
            elif field in observed_only:
                obs_map[field] += 1
            else:
                # Field is not in signature and not in observed_fields.
                if field in new_map:
                    new_map[field] += 1
                elif not new_full:
                    new_map[field] = 1
                    new_full = len(new_map) >= _MAX_NEW_TRACKED

    def finalize_chunk(self) -> dict:
        """Return chunk-level audit data as a JSON-serializable dict.

        Shape::

            {
              "observed_st_counts": {"<st_str>": int, ...},
              "per_st": {
                "<st_str>": {
                  "declared_field_presence":  {"<field>": int, ...},
                  "observed_field_presence":  {"<field>": int, ...},
                  "new_field_presence":       {"<field>": int, ...},
                  "rounds": int,
                  "has_observed_fields": bool
                },
                ...   # only STs with a declared signature
              }
            }

        Resets all chunk-level accumulators after building the result
        so this instance can be reused by the report engine across chunks.
        """
        observed_st_counts: dict[str, int] = {
            str(st): cnt for st, cnt in self._observed_st_counts.items()
        }

        per_st: dict[str, dict] = {}
        for st_int, declared_fields in self._st_signatures.items():
            st_str = str(st_int)
            rounds = int(self._observed_st_counts.get(st_int, 0))
            declared_pres = dict(self._declared_presence.get(st_int) or {})
            observed_pres = dict(self._observed_presence.get(st_int) or {})
            new_pres = dict(self._new_presence.get(st_int) or {})
            has_obs = self._st_has_observed.get(st_int, False)
            per_st[st_str] = {
                "declared_field_presence": declared_pres,
                "observed_field_presence": observed_pres,
                "new_field_presence": new_pres,
                "rounds": rounds,
                "has_observed_fields": has_obs,
            }

        result = {
            "observed_st_counts": observed_st_counts,
            "per_st": per_st,
        }

        # Reset chunk state.
        self._init_chunk_state()
        self._obs_errors = []
        self._begin_robot_error = None

        return result


# ---------------------------------------------------------------------------
# Self-registration — fires at module import time (idempotent: duplicate
# EXTRACTOR_ID is a silent no-op in register_extractor).
# ---------------------------------------------------------------------------
register_extractor(SignatureAuditExtractor({}))
