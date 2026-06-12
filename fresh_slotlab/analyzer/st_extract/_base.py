"""STExtractor — ABC for all per-ST extraction plugins.

Mirrors AnalyzerFeature (features/_base.py) exactly in structure and
versioning contract:
  - EXTRACTOR_ID   ClassVar[str]  — unique snake_case identifier
  - compute_hash() classmethod    — 12-char sha256 of the extractor's source file
  - begin_robot(robot_ctx)        — called once per robot before the round loop
  - observe_round(round_dict, spin_type, round_ctx) — called per round
  - finalize_chunk() -> dict      — called after the round loop; returns JSON-serializable dict

Design notes
------------
- Extractor modules are base-EXCLUDED (like feature plugin modules).
  Editing an extractor re-flags only machines declaring it, not the fleet.
- begin_robot / observe_round / finalize_chunk replace extract/reduce/emit
  because extractors need per-round sequential state, not chunk-level
  accumulator folding.
- clone_for_manifest(manifest) creates a fresh per-run instance with the
  manifest bound in.  The default implementation returns a new instance of
  the same class (cls(manifest)); subclasses that carry no extra constructor
  args need not override this.
- DECLARED_IN_KEY: the manifest spin_types block key that declares this
  extractor's configuration.  get_extractors_for_manifest() checks this key
  across all STs to decide whether to include the extractor.
- No import-time side effects per
  memory/feedback_subprocess_import_suicide_and_module_globals.md.
- Registry state (ALL_EXTRACTORS) is a module global in __init__.py;
  class methods in this file must NOT read it
  (feedback_subprocess_import_suicide_and_module_globals.md).
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar


class STExtractor(ABC):
    """Versioned, opt-in per-round extraction plugin.

    One instance is created per report run (via clone_for_manifest).
    The instance is NOT shared across robots — begin_robot() resets
    per-robot state, and finalize_chunk() returns the chunk-level result
    after all robots in the chunk are processed.

    Implementation template::

        class MyExtractor(STExtractor):
            EXTRACTOR_ID: ClassVar[str] = "my_extractor"
            DECLARED_IN_KEY: ClassVar[str] = "my_manifest_key"

            def __init__(self, manifest: dict):
                self._manifest = manifest
                # per-run state initialised here or in begin_robot

            @classmethod
            def clone_for_manifest(cls, manifest: dict) -> "MyExtractor":
                return cls(manifest)

            def begin_robot(self, robot_ctx: dict) -> None:
                # reset per-robot state
                pass

            def observe_round(self, round_dict: dict, spin_type: int,
                              round_ctx: dict) -> None:
                # accumulate per-round signal
                pass

            def finalize_chunk(self) -> dict:
                # return JSON-serializable dict; shape is extractor-defined
                return {}
    """

    # ------------------------------------------------------------------
    # ClassVars — MUST be set on every subclass
    # ------------------------------------------------------------------

    EXTRACTOR_ID: ClassVar[str] = ""
    """Unique snake_case identifier.  Must be set on every concrete subclass."""

    DECLARED_IN_KEY: ClassVar[str] = ""
    """The manifest spin_types block key that activates this extractor.

    get_extractors_for_manifest() includes this extractor when ANY ST block
    in the manifest carries this key.  E.g. "trigger_paths" for the
    trigger_path extractor.
    """

    # ------------------------------------------------------------------
    # Abstract methods
    # ------------------------------------------------------------------

    @abstractmethod
    def begin_robot(self, robot_ctx: dict) -> None:
        """Called once per robot, before the per-round loop.

        Parameters
        ----------
        robot_ctx:
            {
              "robot_idx":    int,           # 0-based index within chunk
              "trig_sessions": dict[int, dict],  # trigger_round_idx -> session record
                                                 # built from _trig_sessions_for_robot
              "cycle_peak":   int | None,    # BCM cycle peak for this robot
            }
        """
        ...

    @abstractmethod
    def observe_round(
        self,
        round_dict: dict,
        spin_type: int,
        round_ctx: dict,
    ) -> None:
        """Called once per round in the main parser loop.

        Parameters
        ----------
        round_dict:
            The raw round dict from the chunk response.
        spin_type:
            The integer SpinType for this round (pre-extracted by caller).
        round_ctx:
            {
              "robot_idx":       int,
              "round_idx":       int,         # 0-based index within this robot
              "session":         dict | None, # session record if this round belongs
                                              # to a trigger session, else None
              "bet":             int,          # effective bet for this chunk
              "win":             float,        # rule-view win for this round, as
                                              # computed by extract_round_win with
                                              # the full round_win_rules set.
                                              # Prefer this over reading WinCredits
                                              # directly from round_dict — on
                                              # machines with SynthesizePayIdRule
                                              # or chunk-residual attribution the
                                              # rule-view win may differ from the
                                              # raw field.  On machines where
                                              # raw == rule-view (e.g. M275) the
                                              # values are identical.
              "last_paid_round": dict | None,  # most recent paid round dict seen
                                              # in this robot walk; None before
                                              # the first paid round
              "block_id":        int | None,   # round_idx of last_paid_round —
                                              # identifies the bonus block opened
                                              # by that paid round; None before
                                              # the first paid round
            }
        """
        ...

    @abstractmethod
    def finalize_chunk(self) -> dict:
        """Return the chunk-level extraction result as a JSON-serializable dict.

        Called once after all robots in the chunk have been processed.
        The result is stored in the chunk record under
        ``rec["st_extract"][EXTRACTOR_ID]``.

        Returns an empty dict when no data was collected (e.g. no rounds
        matched the declared STs).  The caller treats an empty dict the
        same as no result — either way the key is present in the record.

        Error-handoff contract (per feedback_no_silent_swallow.md)
        -----------------------------------------------------------
        Cross-chunk error isolation is owned by the PARSER, not by extractor
        implementations.  The parser snapshots and resets the error
        accumulators before calling ``finalize_chunk``; finalize_chunk's own
        resets are idempotent guards only.  The sequence is always::

            _obs_errs = list(ext._obs_errors or [])   # 1. parser snapshots
            _begin_err = ext._begin_robot_error
            ext._obs_errors = []                      # 2. parser resets (auth.)
            ext._begin_robot_error = None
            result = ext.finalize_chunk()             # 3. resets payload state;
                                                      #    its error resets are
                                                      #    idempotent no-ops here
            # 4. parser surfaces snapshots if non-empty

        Implementations SHOULD still reset ``_obs_errors`` (to ``[]``) and
        ``_begin_robot_error`` (to ``None``) inside ``finalize_chunk`` as a
        defensive guard — e.g. if finalize_chunk is called outside the normal
        parser loop.  But cross-chunk correctness does NOT depend on this.
        """
        ...

    # ------------------------------------------------------------------
    # Classmethod — mirrors AnalyzerFeature.compute_hash exactly
    # ------------------------------------------------------------------

    @classmethod
    def compute_hash(cls) -> str:
        """Return 12-char sha256 hex of the extractor's source file.

        Identical algorithm to AnalyzerFeature.compute_hash (features/_base.py):
            sha256(<extractor module source bytes>).hexdigest()[:12]

        Used by extractor_hashes() to produce per-extractor hash components
        for versioning.  Editing an extractor changes only the hash of
        machines that declare it.

        Returns
        -------
        str
            12-character lowercase hex string.

        Raises
        ------
        FileNotFoundError
            If the source file cannot be located.
        """
        import sys
        mod = sys.modules.get(cls.__module__)
        path = getattr(mod, "__file__", None) if mod is not None else None
        if path is None:
            path = str(Path(cls.__module__.replace(".", "/") + ".py"))
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]

    # ------------------------------------------------------------------
    # clone_for_manifest — override in subclasses with extra ctor args
    # ------------------------------------------------------------------

    @classmethod
    def clone_for_manifest(cls, manifest: dict) -> "STExtractor":
        """Return a fresh instance with *manifest* bound in.

        Default implementation: ``cls(manifest)``.  Subclasses that take
        additional constructor arguments MUST override this.

        The returned instance is used for a SINGLE report run (one call
        to generate_report_from_chunks); it is never shared across runs.
        """
        return cls(manifest)  # type: ignore[call-arg]
