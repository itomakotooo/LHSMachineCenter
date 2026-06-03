"""play_types.wild_nudge — wild auto-nudge classification.

Home of the wild-nudge mechanic logic. ``is_wild_nudge_round`` was
CARVED OUT of ``round_classification.py`` (a base-closure file listed in
``versioning._CLOSURE_FILES``) into this module, which is **NOT** in the
closure. Consequence: editing the wild-nudge detection logic no longer changes
``base_hash`` — it does not re-flag the fleet; only machines whose analysis
depends on this module are affected. That hash-level isolation is the whole
point of the carve, and it is the property an automated test in
``tests/backend/test_wild_nudge_carve.py`` pins.

Scope note: this module houses the pure per-SpinType classifier. ``parser.py``
imports and calls it directly — the same dependency pattern PIA already uses for
the base-excluded ``analyzer/features/*`` modules. The carve IS the isolation
(the logic already lives outside the closure; that is what makes editing it free
of fleet re-flags) — there is no plugin wrapper (the event model has no
play-type plugin layer; see ``session_artifacts/_arch_playtype/DIRECTION.md``).

Verified across M279 / M226 / M149 / M140 / M26 / M51 / M256 (2026-04-27 fleet
investigation): 25 (machine, mode) pairs emit ST=36 + ReMarks="move" +
CostCredits=0 in a uniform shape; all other machines are False by construction.

No import-time side effects (no registration, no I/O) per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

import re
from typing import Any

# Wild-nudge ReMarks signature: a "move" or "nudge" token (case-insensitive).
_NUDGE_REMARK_RE = re.compile(r"\b(move|nudge)\b", re.IGNORECASE)


def is_wild_nudge_round(r: Any) -> bool:
    """True iff this round is a wild auto-nudge continuation of a
    preceding paid spin.

    Detection signals (all required):
      * ``CostCredits`` is None or 0 (no extra cost; nudge is free)
      * ``ReMarks`` contains "move" or "nudge" (case-insensitive)

    Verified across M279 / M226 / M149 / M140 / M26 / M51 / M256 in
    the 2026-04-27 fleet investigation: 25 (machine, mode) pairs
    emit ST=36 + ReMarks="move" + CostCredits=0 in a uniform shape.
    Other machines emit nothing matching this signature, so the
    classifier is False on them by construction.
    """
    if not isinstance(r, dict):
        return False
    cost = r.get("CostCredits")
    if cost is not None:
        try:
            if float(cost) > 0.0:
                return False
        except (TypeError, ValueError):
            return False
    rmk = r.get("ReMarks")
    if not isinstance(rmk, str):
        return False
    return bool(_NUDGE_REMARK_RE.search(rmk))
