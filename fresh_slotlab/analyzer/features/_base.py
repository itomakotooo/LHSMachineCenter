"""AnalyzerFeature — ABC for all analyzer feature plugins.

Per ticket P2-A1 §3 C1 (Round 2 spec-aligned) and
04_architecture_proposal_v5.md §5.2 verbatim.

Phase C1 additions (04_v3 §4.1 / §7.2):
- ``DECLARED_DEPS``    ClassVar[tuple] — summary temp-keys this feature reads
                                         in its emit() call (for ordering validation)
- ``emit()`` signature extended to accept ``ctx: PipelineContext`` as 3rd arg

Design notes
------------
- ``FEATURE_ID``               ClassVar[str]  — unique snake_case plugin identifier
- ``SCHEMA_KEYS``              ClassVar[tuple] — keys written to the summary block
- ``SCHEMA_VERSION``           ClassVar[int]  — bump invalidates downstream renderers
- ``REQUIRES``                 ClassVar[tuple] — feature IDs this feature depends on
- ``DECLARED_DEPS``            ClassVar[tuple] — summary ``_`` temp-keys consumed in emit()
- ``RTP_CONTRIBUTION``         ClassVar[bool]  — True if this feature contributes RTP;
                                                 Wave 2e RTP gate reads this (AttributeError
                                                 if absent — this ClassVar is load-bearing)
- ``REGISTERED_FALLBACK_RULES`` ClassVar[dict] — per-SCHEMA_VERSION fallback renderer rules
- ``extract``                  abstractmethod — per-chunk extraction (called once per chunk)
- ``reduce``                   abstractmethod — accumulator reduction across chunks
- ``emit``                     abstractmethod — produce final summary block

Applicability semantic (04_v5 §5.5.2):
    Whether a feature applies to a machine is declared in the per-machine
    manifest's ``analyzer_features`` list — NOT via a runtime instance
    predicate.  ``get_features_for_machine`` reads the manifest list and
    returns features whose ``FEATURE_ID`` appears in it.

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    # Imported for type annotations only; avoids circular import at runtime.
    # PipelineContext lives in fresh_slotlab/analyzer/pipeline_context.py
    # (not under features/) so there is no import cycle at runtime.
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
    except ImportError:  # standalone script mode
        from analyzer.pipeline_context import PipelineContext  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------

class AnalyzerFeature(ABC):
    """Versioned, opt-in slice of analyzer functionality.

    Per 04_architecture_proposal_v5.md §5.2 (Plugin Protocol).

    All ClassVar attributes below MUST be defined at the class level.
    Subclasses MUST implement the three abstractmethods (extract, reduce,
    emit) or instantiation raises TypeError.

    Implementation template::

        class MyFeature(AnalyzerFeature):
            FEATURE_ID: ClassVar[str] = "my_feature"
            SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("my_key",)
            RTP_CONTRIBUTION: ClassVar[bool] = False

            def extract(self, parse_state, chunk_dict) -> dict:
                return {"my_key": parse_state.get("some_field", 0)}

            def reduce(self, prev_acc, this_acc) -> Any:
                result = dict(prev_acc)
                result["my_key"] = result.get("my_key", 0) + this_acc.get("my_key", 0)
                return result

            def emit(self, final_acc, summary: dict, ctx) -> None:
                summary["my_feature"] = final_acc  # mutate summary in place
    """

    # ------------------------------------------------------------------
    # ClassVars — per 04_v5 §5.2 verbatim
    # ------------------------------------------------------------------

    FEATURE_ID: ClassVar[str] = ""
    """Unique snake_case plugin identifier.  Must be set on every subclass."""

    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ()
    """Keys this feature writes to the summary block.

    Used by the frontend renderer registry to declare fallback rules.
    Leave empty for features with dynamic key sets.
    """

    SCHEMA_VERSION: ClassVar[int] = 1
    """Bump this when the shape of ``SCHEMA_KEYS`` changes incompatibly.

    Per 04_v5 §5.4: bump invalidates downstream renderers that have not
    been updated to handle the new shape.
    """

    REQUIRES: ClassVar[tuple[str, ...]] = ()
    """FEATURE_IDs of features this feature depends on.

    The orchestrator guarantees dependencies run before this feature.
    """

    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    """Summary ``_`` temp-keys this feature reads in its emit() call.

    Per 04_v3 §4.1 Phase C1.  Listing a key here signals to the emit-loop
    runner that this feature depends on a pre-stashed temp-key in the summary
    dict.  The runner validates that each declared dep key is present before
    invoking emit().

    Convention: dep keys use the ``_`` prefix (e.g. ``"_bankruptcy_rows"``,
    ``"_mechanism_registry"``).  They are cleaned up by the emit loop after
    all plugins have run.

    Subclasses that need no summary deps leave this as ``()`` (the default).
    """

    RTP_CONTRIBUTION: ClassVar[bool] = False
    """True if this feature contributes to the RTP sum.

    Wave 2e RTP integrity gate reads this ClassVar to decide whether to
    include the feature in the RTP invariant check.  **CRITICAL**: absence
    of this ClassVar on a registered feature raises AttributeError at gate
    time — always define it.
    """

    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}
    """Per-SCHEMA_VERSION fallback renderer rules.

    Keyed by old SCHEMA_VERSION.  Each value is a dict mapping old field
    names to new field names (or None for dropped fields).  Allows the
    frontend renderer registry to render historical summaries produced by
    older schema versions.
    """

    # ------------------------------------------------------------------
    # Abstract methods — per 04_v5 §5.2 verbatim
    # ------------------------------------------------------------------

    @abstractmethod
    def extract(self, parse_state, chunk_dict) -> dict:
        """Extract feature data from a single parsed round.

        Called once per round in the chunk iteration loop.

        Parameters
        ----------
        parse_state:
            The current parser state object (type narrowed to typed
            dataclass in Wave 2b core carve; dict[str, Any] at foundation
            layer to avoid circular imports).
        chunk_dict:
            The raw chunk dict produced by the analyzer's chunk-parsing
            step.  Do NOT mutate.

        Returns
        -------
        dict
            The round-level accumulator contribution for this feature.
            Returned dicts are passed to ``reduce`` to fold across chunks.
        """
        ...

    @abstractmethod
    def reduce(self, prev_acc, this_acc) -> Any:
        """Fold two accumulator values into one.

        Called to merge the running accumulator (``prev_acc``) with the
        new contribution from one round's ``extract`` output (``this_acc``).

        The orchestrator calls this for every round in every chunk:
            acc = feature.reduce(acc, feature.extract(parse_state, chunk))

        Parameters
        ----------
        prev_acc:
            The accumulator value so far.  On the first round, the
            orchestrator passes an empty dict ``{}`` as ``prev_acc``.
        this_acc:
            The dict returned by ``extract`` for the current round.

        Returns
        -------
        Any
            The new accumulator (should be the same type as ``prev_acc``
            for consistency across folds).
        """
        ...

    @abstractmethod
    def emit(self, final_acc: Any, summary: dict, ctx: "PipelineContext") -> None:
        """Write the final feature result into the summary dict.

        Called once after all rounds in all chunks have been processed.
        Mutates ``summary`` in place — does NOT return a new dict.

        Phase C1 change (04_v3 §4.1): added ``ctx`` as 3rd parameter.
        Existing Pattern-A plugins accept ``ctx`` but do not use it yet.
        Pattern-B plugins use ``ctx.effective_bet_for_rtp`` etc. for RTP math.

        Parameters
        ----------
        final_acc:
            The fully-reduced accumulator (result of all ``reduce`` calls).
            Pattern-A plugins receive ``{}`` (empty dict) for final_acc
            because their extract() / reduce() are no-ops.
        summary:
            The partial summary dict assembled so far.  Add this feature's
            keys to ``summary`` in place.  Read ``_``-prefixed temp keys
            listed in ``DECLARED_DEPS`` from here; they are cleaned up after
            the emit loop.
        ctx:
            PipelineContext carrying effective_bet_for_rtp, total_spins,
            total_paid_sessions, total_paid_spins, clamp_pending_robots_total,
            robots_with_pending_cycle, mechanism_registry, and manifest.
            None of the 4 existing Pattern-A plugins use ctx in C1.
        """
        ...

    # ------------------------------------------------------------------
    # Classmethod — per 04_v5 §5.2 lines 345-348
    # ------------------------------------------------------------------

    @classmethod
    def compute_hash(cls) -> str:
        """Return 12-char sha256 hex of the subclass's source file.

        Per 04_v5 §5.2 lines 345-348 the algorithm is:
            sha256(<feature module source bytes>).hexdigest()[:12]

        The spec's example expression
            ``Path(cls.__module__.replace(".", "/") + ".py")``
        only works when cwd resolves the resulting relative path to the
        same file. Under PIA's script-mode invocation (where the
        feature class is imported as ``analyzer.features.X`` with the
        repo root still the cwd), that relative path resolves nowhere.
        We use ``sys.modules`` to find the module's actual ``__file__``
        attribute, which is invariant across package- and script-mode.

        Used by ``compute_effective_analyzer_version`` to produce the
        per-feature hash component. Each feature's hash changes only
        when its own source file changes — not when unrelated features
        change.

        Returns
        -------
        str
            12-character lowercase hex string (sha256 truncated).

        Raises
        ------
        FileNotFoundError
            If the source file cannot be located. Happens when the
            class is defined in a REPL or a dynamically-constructed
            module; callers that need resilience should wrap in
            try/except.
        """
        import sys
        mod = sys.modules.get(cls.__module__)
        path = getattr(mod, "__file__", None) if mod is not None else None
        if path is None:
            # Fallback to the spec's literal expression so the behavior
            # is unchanged for callers that ALWAYS run in package-mode
            # and never touched the new sys.modules path.
            path = str(Path(cls.__module__.replace(".", "/") + ".py"))
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
