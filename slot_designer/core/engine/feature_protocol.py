"""FeaturePlugin Protocol — pluggable per-machine feature mechanic.

ARCHITECTURE.md §3 contract. Generic engine + emitter + driver call
this Protocol; concrete implementations live in
``machines/<M>/plugins/``. Plugins are loaded via importlib at
``load_engine`` time — generic core never imports a machine subpackage
statically.

Three responsibilities:

  1. ``simulate_session(rng) -> list[Any]``
     Run feature math, return opaque "feature round" objects (each
     plugin's own dataclass). Generic code never inspects them; the
     list is just passed through to ``emit_extra_rounds``.

  2. ``emit_extra_rounds(base_round, feature_rounds, *, last_credits,
        spin_times, rtp_id, bet_amount) -> list[dict]``
     Convert feature_rounds into rawdata round dicts following the
     machine's production schema. Generic emitter calls this and
     concatenates the result onto the base round; it does not know
     what spin_types or fields each machine uses.

  3. ``classify_round(round_dict, next_round_dict) -> tuple[str, int]``
     Analyzer-side. Tell generic ``robot.emit_robot`` what feature_name
     to bucket a round under (e.g. "<feature>", "Normal", or any
     machine-specific name). ``next_round_dict`` is the following row
     in the chunk (None if last); plugins use it for state-aware
     classification (e.g., "ST=14 followed by ST=14" → rejected reveal).

Plugin loading convention — a plugin module's ``__init__.py`` exposes:

  build_plugin(spec_dict, weights_doc) -> FeaturePlugin | None

  Returns a configured plugin instance, or None if the spec doesn't
  declare a feature. Base-only machines either have no
  ``machines/<M>/plugins/`` dir at all, or their build_plugin always
  returns None.

Example skeleton — see ``machines/<M>/plugins/`` for the concrete
implementation that conforms to this protocol.
"""
from __future__ import annotations

from random import Random
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class FeaturePlugin(Protocol):
    """Per-machine feature mechanic plugin contract.

    Implemented by ``machines/<M>/plugins/`` modules; consumed by
    generic ``core/engine/spin.py``, ``core/emitter/round.py``,
    ``core/emitter/robot.py``, ``core/emitter/driver.py``.

    The Protocol is decorated ``@runtime_checkable`` so consumers can
    use ``isinstance(plugin, FeaturePlugin)`` for diagnostic guards
    (load-time sanity checks) without importing concrete plugin types.
    """

    #: pay_id that, when present in a paid spin's scatter_pays,
    #: indicates the feature should fire. ``None`` for plugins that
    #: trigger via mechanisms other than scatter pay (e.g. single-line slots's
    #: collect-meter-fills-to-threshold).
    trigger_pay_id: int | None

    def simulate_session(self, rng: Random) -> list[Any]:
        """Run a single feature session, return per-round objects.

        The list type is plugin-private (e.g. ``M15FeatureRound``).
        Generic code passes the list to ``emit_extra_rounds`` without
        inspecting individual entries.
        """
        ...

    def emit_extra_rounds(
        self,
        base_round: dict,
        feature_rounds: list[Any],
        *,
        last_credits: int,
        spin_times: int,
        rtp_id: int,
        bet_amount: int,
    ) -> list[dict]:
        """Convert feature rounds into rawdata round dicts.

        Returned dicts MUST follow the machine's production rawdata
        schema (correct SpinType + field set). Generic emitter
        concatenates these onto the trigger paid spin to form the
        complete session.

        ``base_round`` is the ST=1 paid spin dict that triggered the
        feature, provided so plugins can read e.g. ``BetAmount`` if
        they don't already have it from session state.
        """
        ...

    def classify_round(
        self,
        round_dict: dict,
        next_round_dict: dict | None,
    ) -> tuple[str, int]:
        """Bucket a single round into a feature_name + effective_win.

        Generic ``robot.emit_robot`` calls this once per round in the
        rawdata stream. Returns ``(feature_name, effective_win)`` where
        feature_name is a machine-specific string used for the
        FeatureWin / SummaryWin breakdown.

        For paid base spins (no feature plugin context), generic code
        defaults to ``("Normal", round.WinCredits)`` — plugins only
        need to override for their own SpinType codes.

        ``next_round_dict`` enables state-aware classification (e.g.
        "ST=14 followed by another ST=14 → rejected reveal").
        """
        ...
