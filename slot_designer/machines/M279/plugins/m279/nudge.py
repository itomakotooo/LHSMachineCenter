"""Wild stack nudge — bidirectional MoveSpin sequencer.

Mechanic (per Light & Wonder 'Blazing 777 Nudging Stacks' archetype):
  - The reel strip places a 3-symbol "wild stack" trio at adjacent
    positions: ``wild_up`` → ``wild2x_mid`` → ``wild_down`` (top-to-bot
    on the strip, mapping to row 0 → row 1 → row 2 when fully visible).
  - When a paid spin's window shows the stack PARTIALLY (only 1 or 2
    of the 3 wilds visible), the system fires a free MoveSpin (ST=36)
    that nudges the stack one row toward full visibility.
  - The chain continues (max 2 MoveSpins per archetype) until the full
    3-row stack is visible, then ends.

Direction inference:
  - ``wild_up`` alone visible at the BOTTOM row (row 2) → stack lives
    BELOW the window → window must shift DOWN (= strip pointer moves
    UP) to expose more of the stack from below
  - ``wild_down`` alone visible at the TOP row (row 0) → stack lives
    ABOVE the window → window shifts UP (strip pointer moves DOWN)
  - 2 visible (any combination) → one final shift to center

Implementation: rather than tracking strip-position-relative window
shifts (which would require knowing which anchor pair on the strip the
trigger came from), we just compute the next "more visible" stack
configuration analytically:
  - 1 visible → shift to 2 visible (wild_up + wild2x_mid OR wild2x_mid
    + wild_down depending on direction)
  - 2 visible → shift to 3 visible (full reveal)
  - 3 visible → no shift (no MoveSpin)

For symbols outside the reel that has the partial stack, the column's
3 cells are FROZEN — MoveSpin only re-renders the partial-stack
column. The other 2 columns retain the paid spin's symbols.

This matches observed rawdata behavior where MoveSpin grid differs
from prev paid grid in exactly ONE column (the one that had the
partial stack on the paid spin).
"""
from __future__ import annotations

from dataclasses import dataclass


# Stack anchor symbols (M279). These names live in the spec — the
# values here are duplicated for clarity / nudge logic anchoring.
STACK_TOP = "wild_up"        # wild_up sits at row 0 when fully visible
STACK_MID = "wild2x_mid"
STACK_BOT = "wild_down"      # wild_down sits at row 2 when fully visible
STACK_SYMS = frozenset({STACK_TOP, STACK_MID, STACK_BOT})


@dataclass
class NudgeConfig:
    anchor_symbols: tuple[str, ...]   # ("wild_up", "wild2x_mid", "wild_down")
    stack_order: tuple[str, ...]      # top-to-bot: ("wild_up", "wild2x_mid", "wild_down")
    max_chain_length: int = 2


def load_nudge_config(spec: dict) -> NudgeConfig:
    block = (spec.get("_m279_features") or {}).get("nudge_stack")
    if not block:
        raise ValueError("M279 spec missing _m279_features.nudge_stack block")
    anchor_layout = block.get("anchor_layout", {})
    return NudgeConfig(
        anchor_symbols=tuple(block["anchor_symbols"]),
        stack_order=tuple(anchor_layout.get(
            "stack_order",
            ("wild_up", "wild2x_mid", "wild_down"),
        )),
        max_chain_length=int(block.get("max_chain_length", 2)),
    )


def stack_visible_count(column: list[str]) -> int:
    """Return number of stack symbols visible in this column (0-3)."""
    return sum(1 for s in column if s in STACK_SYMS)


def detect_partial_stack_reels(grid: list[list[str]]) -> list[int]:
    """Find columns where the stack is PARTIALLY visible (1 or 2 wilds
    of the trio). Returns list of column indices, in order.

    Per archetype, only one reel typically triggers nudge per session;
    if multiple reels show partial stacks (rare), they're processed in
    column order.
    """
    out: list[int] = []
    for col_idx, col in enumerate(grid):
        n = stack_visible_count(col)
        if 1 <= n <= 2:
            out.append(col_idx)
    return out


def _nudge_step(column: list[str]) -> list[str]:
    """Return the column after one nudge step toward full reveal.

    Logic:
      - count visible stack symbols → 1 / 2 / 3
      - if 3: return as-is (no change; should not happen if caller
        respected detect_partial_stack_reels)
      - if 2: snap to fully-visible canonical layout [up, mid, bot]
      - if 1: shift to a 2-wild intermediate based on which symbol
        is visible and at which row:
          wild_up at row 2 → [blank, up, mid]
          wild_up at row 1 → [up, mid, bot]   (already a 2-step jump
                                                actually handled by
                                                "2 visible" branch but
                                                row-1 only happens
                                                with mid+up combos;
                                                this case is rare)
          wild_down at row 0 → [mid, bot, blank]
          wild_down at row 1 → [up, mid, bot] (similar — handled by 2
                                                visible)
      - "blank" filler symbol used when the stack hasn't fully entered
        the window yet
    """
    n = stack_visible_count(column)
    if n >= 3:
        return list(column)
    if n == 2:
        # Snap to fully visible canonical layout
        return [STACK_TOP, STACK_MID, STACK_BOT]
    # n == 1: identify which stack symbol + position
    visible_idx = next(i for i, s in enumerate(column) if s in STACK_SYMS)
    visible_sym = column[visible_idx]
    # Use 'blank' as the placeholder for cells the stack hasn't filled
    # yet. This matches rawdata observation (the cells that aren't
    # part of the stack show 'blank' or other strip symbols; we use
    # blank for simulation since the non-stack cells in the partial
    # window are arbitrary fillers — whatever the strip happens to
    # have at neighboring positions).
    if visible_sym == STACK_TOP:
        # wild_up alone — stack is below window. Shift to expose mid.
        if visible_idx == 2:  # at bot row
            return ["blank", STACK_TOP, STACK_MID]
        # at row 1 → just snap to full (rare)
        return [STACK_TOP, STACK_MID, STACK_BOT]
    if visible_sym == STACK_BOT:
        # wild_down alone — stack is above window. Shift to expose mid.
        if visible_idx == 0:  # at top row
            return [STACK_MID, STACK_BOT, "blank"]
        return [STACK_TOP, STACK_MID, STACK_BOT]
    # visible_sym == STACK_MID alone — should be impossible (mid is
    # surrounded by up + down on the strip, and a window of 3 cells
    # straddling mid will see at least one of up/down). Defensive
    # fallback: snap to full.
    return [STACK_TOP, STACK_MID, STACK_BOT]


def nudge_chain(
    paid_grid: list[list[str]],
    cfg: NudgeConfig,
) -> list[list[list[str]]]:
    """Generate the chain of MoveSpin grids triggered by a paid spin.

    Returns: list of grids (one per MoveSpin round). Each grid
    differs from the prior grid (or paid_grid for the first step) in
    exactly one column — the partial-stack column being nudged.

    Empty list when no partial stack is on any column.

    Multi-reel partial stacks: chain processes one reel at a time in
    column order. Per archetype "nudge up to two times" cap, the
    cumulative MoveSpin count across all triggered reels is bounded
    by ``cfg.max_chain_length``.
    """
    chain: list[list[list[str]]] = []
    # Deep-copy the paid grid for stepwise mutation
    cur = [list(col) for col in paid_grid]
    partial_reels = detect_partial_stack_reels(cur)
    if not partial_reels:
        return chain
    chain_count = 0
    for col_idx in partial_reels:
        # Keep nudging this reel until full reveal or chain cap
        while (
            chain_count < cfg.max_chain_length
            and stack_visible_count(cur[col_idx]) < 3
        ):
            cur[col_idx] = _nudge_step(cur[col_idx])
            chain_count += 1
            # Snapshot the current grid as a MoveSpin frame
            chain.append([list(c) for c in cur])
            if chain_count >= cfg.max_chain_length:
                break
        if chain_count >= cfg.max_chain_length:
            break
    return chain
