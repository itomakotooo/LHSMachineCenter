"""play_types._plugin — PlayTypePlugin base class.

Per 04_v2.md §4.5 (updated PlayTypePlugin sketch with get_probe()).

PlayTypePlugin is the base class for all play-type plugins.  It extends
AnalyzerFeature (the existing display feature ABC) so that play-type plugins
can serve BOTH roles:
  1. The mechanic role: run MechanicAccumulator per robot during parsing
     (get_probe / make_accumulator / MECHANIC_DEPS / CLAIM_SIGNATURE).
  2. The display role: produce summary output panels
     (extract / reduce / emit inherited from AnalyzerFeature).

Import notes
------------
This module has a dual-path import for AnalyzerFeature to support both
package-mode (repo root on sys.path) and standalone-script mode
(fresh_slotlab/ on sys.path), mirroring the pattern in feature_registry.py.

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, ClassVar, Optional

# Dual-path import — mirrors feature_registry.py convention.
try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    from fresh_slotlab.analyzer.play_types._claim import ClaimSignature
    from fresh_slotlab.analyzer.play_types._probe import PreParseProbe
    from fresh_slotlab.analyzer.play_types._base import MechanicAccumulator
except ImportError:  # running as standalone script
    from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
    from analyzer.play_types._claim import ClaimSignature  # type: ignore[no-redef]
    from analyzer.play_types._probe import PreParseProbe  # type: ignore[no-redef]
    from analyzer.play_types._base import MechanicAccumulator  # type: ignore[no-redef]

if TYPE_CHECKING:
    try:
        from fresh_slotlab.analyzer.play_types._machine_config import MachinePlayTypeConfig
    except ImportError:
        from analyzer.play_types._machine_config import MachinePlayTypeConfig  # type: ignore[assignment]


class PlayTypePlugin(AnalyzerFeature):
    """Base class for all play-type plugins.

    Extends ``AnalyzerFeature`` to add the mechanic role:
    - ``CLAIM_SIGNATURE`` — auto-detection predicate (§4.2-rev)
    - ``MECHANIC_DEPS``   — topo-sort deps for on_round() and emit() ordering
                            (§4.1-rev EC-6 invariant)
    - ``get_probe()``     — optional PreParseProbe for pre-loop flags (§4.5)
    - ``make_accumulator()`` — factory for per-robot MechanicAccumulator

    ClassVar ``REQUIRES_PLAY_TYPES`` (§4.7)
    ----------------------------------------
    Inherited from AnalyzerFeature.  Play-type plugins that are themselves
    display features should set REQUIRES_PLAY_TYPES to restrict which machines
    show the display panel.  Concrete plugins set this at the class level.

    Usage
    -----
    Subclass PlayTypePlugin, define FEATURE_ID, CLAIM_SIGNATURE, MECHANIC_DEPS,
    implement make_accumulator(), and implement extract/reduce/emit for the
    display role.

    Registration
    ------------
    Concrete plugins register themselves in play_type_registry.py by calling
    ``play_type_registry.register(MyPlugin())`` at module import time.

    No import-time side effects per
    memory/feedback_subprocess_import_suicide_and_module_globals.md.
    """

    # ------------------------------------------------------------------
    # Play-type ClassVars
    # ------------------------------------------------------------------

    CLAIM_SIGNATURE: ClassVar[ClaimSignature]
    """Auto-detection predicate for this plugin.

    The detector evaluates this against the 5,000-round sample from
    chunk_0001 to determine whether this plugin applies to a machine.
    Must be defined on every concrete subclass.
    """

    MECHANIC_DEPS: ClassVar[tuple[str, ...]] = ()
    """FEATURE_IDs of play-type plugins this plugin depends on.

    Governs BOTH:
    1. on_round() dispatch order (Step P — EC-6 invariant from §4.1-rev):
       this plugin's accumulator fires AFTER all deps' accumulators for each
       round.
    2. to_chunk_partial() merge order: this plugin's chunk partial is merged
       AFTER deps' partials.

    Empty tuple (the default) means this plugin has no play-type deps and
    runs first in topo-sort (ties broken lexicographically by FEATURE_ID,
    matching topo_sort.topological_sort() behaviour).

    Note: MECHANIC_DEPS is distinct from REQUIRES (the display-feature DAG
    used by AnalyzerFeature.emit() ordering).  Plugins that depend on another
    plugin at both the mechanic level AND the display level should declare
    both MECHANIC_DEPS and REQUIRES.
    """

    # REQUIRES_PLAY_TYPES is defined on AnalyzerFeature (§4.7).
    # PlayTypePlugin subclasses inherit it; concrete plugins set it as needed.
    REQUIRES_PLAY_TYPES: ClassVar[Optional[frozenset]] = None

    # ------------------------------------------------------------------
    # Mechanic role methods
    # ------------------------------------------------------------------

    def get_probe(self) -> Optional[PreParseProbe]:
        """Return a PreParseProbe instance, or None if no pre-loop probe needed.

        Called once per chunk before the per-robot loop begins.  The probe
        result is written to ParseState and read by the universal U1 body.

        Default implementation returns None (no probe).  Override in plugins
        that require pre-loop flags (e.g. CostCreditsReliabilityProbe for the
        M10 family where CostCredits is always 0 despite real wagers).
        """
        return None

    @abstractmethod
    def make_accumulator(
        self, machine_config: "MachinePlayTypeConfig"
    ) -> MechanicAccumulator:
        """Return a fresh MechanicAccumulator for one robot.

        Called once per robot per chunk.  The returned accumulator must be
        stateful (not shared between robots or chunks).

        Parameters
        ----------
        machine_config:
            Per-machine play-type config (active plugins, st_map, per-plugin
            config blobs).  Plugins read their config slice from here.

        Returns
        -------
        MechanicAccumulator
            A fresh instance ready to receive on_round() calls.
        """
        ...

    # ------------------------------------------------------------------
    # AnalyzerFeature abstract methods — default no-op implementations
    # for plugins that serve only the mechanic role and have no display panel.
    # Concrete plugins that DO produce display panels override these.
    # ------------------------------------------------------------------

    def extract(self, parse_state: object, chunk_dict: dict) -> dict:
        """Default no-op extract for mechanic-only plugins.

        Override in plugins that produce display panel data via the
        standard extract/reduce/emit pipeline.
        """
        return {}

    def reduce(self, prev_acc: object, this_acc: object) -> object:
        """Default no-op reduce for mechanic-only plugins."""
        return {}

    def emit(self, final_acc: object, summary: dict, ctx: object) -> None:
        """Default no-op emit for mechanic-only plugins.

        Override in plugins that write display panel keys to summary.
        """
        return None
