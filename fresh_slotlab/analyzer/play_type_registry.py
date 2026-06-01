"""play_type_registry — global registry of PlayTypePlugin classes.

Mirrors ``feature_registry.py`` in design and public API.

Per 04_v2.md §9-rev Phase 1 deliverable 6.

Usage
-----
Play-type plugins register themselves by calling ``register(MyPlugin())`` at
plugin module import time.  This is done by each concrete plugin module, NOT
here.  This file must be importable with zero side effects.

    # in a plugin module:
    from fresh_slotlab.analyzer.play_type_registry import register
    register(MyPlugin())

Then callers query:
    from fresh_slotlab.analyzer.play_type_registry import get_plugins_for_machine
    plugins = get_plugins_for_machine(active_plugin_ids)

Design
------
- ``ALL_PLAY_TYPE_PLUGINS``  starts empty (no concrete plugins at foundation layer).
- ``register()``             appends; duplicate registration by FEATURE_ID is a
                             no-op (silent dedup by FEATURE_ID, mirroring
                             feature_registry.register() semantics).
- ``get_plugins_for_machine()``  filters registered plugins to those whose
                             FEATURE_ID appears in the given active_plugin_ids
                             list.  Registration order is preserved.
- ``get_all_plugins()``      returns all registered plugins.

This file is EMPTY of concrete plugins in Commit A.  Concrete plugins are
registered in their own modules (Commit B+).

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Dual-path import — mirrors feature_registry.py convention.
try:
    from fresh_slotlab.analyzer.play_types._plugin import PlayTypePlugin
except ImportError:  # running as standalone script
    from analyzer.play_types._plugin import PlayTypePlugin  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Registry state
# ---------------------------------------------------------------------------

ALL_PLAY_TYPE_PLUGINS: list[PlayTypePlugin] = []
"""Global list of registered PlayTypePlugin instances.

Empty on module import.  Concrete play-type plugin modules register
themselves by calling ``register(plugin_instance)`` at import time.
Registration order is preserved; ``get_plugins_for_machine`` returns
plugins in registration order (filtered by active_plugin_ids).
"""


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------

def register(plugin: PlayTypePlugin) -> None:
    """Register *plugin* in ALL_PLAY_TYPE_PLUGINS.

    Duplicate registration (same FEATURE_ID) is a silent no-op — the
    existing registration is kept and the new one is discarded.  This
    guards against double-import of a plugin module without raising an
    error.

    Mirrors ``feature_registry.register()`` semantics.

    Parameters
    ----------
    plugin:
        An instance subclassing ``PlayTypePlugin`` ABC.

    Raises
    ------
    TypeError
        If *plugin* is not an instance of ``PlayTypePlugin`` (ABC subclass
        check via ``isinstance``).
    """
    if not isinstance(plugin, PlayTypePlugin):
        raise TypeError(
            f"register() requires a PlayTypePlugin instance, "
            f"got {type(plugin)!r}.  Ensure the class subclasses "
            "PlayTypePlugin and implements make_accumulator()."
        )

    # Idempotency: skip if FEATURE_ID already registered (mirrors feature_registry).
    feature_id = plugin.FEATURE_ID
    for existing in ALL_PLAY_TYPE_PLUGINS:
        if existing.FEATURE_ID == feature_id:
            return  # silent no-op

    ALL_PLAY_TYPE_PLUGINS.append(plugin)


def get_plugins_for_machine(
    active_plugin_ids: list[str],
) -> list[PlayTypePlugin]:
    """Return play-type plugin instances for the given active plugin IDs.

    Filters the registered plugins to those whose FEATURE_ID appears in
    *active_plugin_ids*, in registration order (stable).

    Parameters
    ----------
    active_plugin_ids:
        List of FEATURE_IDs to include, typically from
        ``MachinePlayTypeConfig.active_plugins``.  The order in the returned
        list is registration order, not the order in *active_plugin_ids*.
        The caller is responsible for topo-sorting by MECHANIC_DEPS if needed.

    Returns
    -------
    list[PlayTypePlugin]
        Matching plugins in registration order.
    """
    requested = set(active_plugin_ids)
    return [p for p in ALL_PLAY_TYPE_PLUGINS if p.FEATURE_ID in requested]


def get_all_plugins() -> list[PlayTypePlugin]:
    """Return all registered play-type plugin instances.

    Used by ``detect_play_types()`` to evaluate all plugin ClaimSignatures
    against a machine's sample rounds.

    Returns
    -------
    list[PlayTypePlugin]
        All registered plugins in registration order.
    """
    return list(ALL_PLAY_TYPE_PLUGINS)
