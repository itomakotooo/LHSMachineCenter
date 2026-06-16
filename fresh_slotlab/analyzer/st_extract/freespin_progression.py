"""Parser-blind freespin-progression extractor — Phase 3.

Accumulates per-round ExtraRatio, FS-index (from ReMarks "Freespin N; "),
and per-session win totals for declared freespin-role STs, split by
dimension/trigger-path.

ZERO machine-specific code in this file.  Discovery happens via
DECLARED_IN_KEY = "trigger_paths" — the same manifest key the
TriggerPathExtractor uses.  This extractor fires ONLY on STs whose
spec has both (a) a "trigger_paths" block AND (b) role == "freespin".
Non-freespin trigger_paths STs are silently ignored (early-return per
role check at __init__ time).

Label resolution
----------------
REUSES TriggerPathExtractor._resolve_labels() logic via the shared
private helper _resolve_path_label() extracted into _label_helpers module.
We do NOT copy-paste the discriminator/anchor-walk logic — instead we
re-instantiate the resolution by importing the helper from trigger_path.py
directly.  trigger_path.py is already base-excluded so there is no new
closure dependency.

Per-round accumulation (per (ST, dim_name, path_label)):
  er_by_fs_index    : {fs_idx: {er_val: count}} — ER value distribution
                       per FS position (shows the monotone-climbing ladder
                       01_understanding.md §8.5).
  er_sum_by_fs_index: {fs_idx: float} — ER sum (for mean ER per FS index).
  fs_arc_round_count : {fs_idx: int} — rounds at each FS position.
  fs_arc_win_round   : {fs_idx: int} — win rounds (WinCredits > 0) at each FS pos.
  fs_arc_win_sum     : {fs_idx: float} — win sum per FS position.

Per-session accumulation (per (ST, dim_name, path_label)):
  session_win_totals : list[float] — one per session (distinct block_id),
                        the total win for that session.  Used to build a
                        return-bucket histogram per path (session-tier dist).

finalize_chunk output shape
---------------------------
{
  "<st_int>": {
    "<dim_name>": {                            # e.g. "trigger_path"
      "<path_label>": {                        # e.g. "scatter"
        "er_ladder": {
          "<fs_idx>": {                        # "1" .. "10"
            "er_distribution": {"<er_val>": int, ...},
            "er_sum": float,
            "round_count": int
          }, ...
        },
        "fs_arc": {
          "<fs_idx>": {
            "round_count": int,
            "win_round_count": int,
            "win_sum": float
          }, ...
        },
        "session_tier_hist": {<return_bucket>: int, ...}
      },
      ...
      "_unknown": {},       # if any unknown path buckets
      "_multi": {},         # if any multi-trigger buckets
    }
  }
}

INVARIANT: for any declared freespin ST and any real path_label:
  sum over fs_idx of fs_arc[fs_idx]["round_count"]
  == trigger_path extractor's round_count for (st, path_label)
(value-agnostic; verifiable by the tester).

Error contract (feedback_no_silent_swallow.md)
----------------------------------------------
Errors inside observe_round are NOT swallowed.  The parser wraps each
extractor call in its own try/except and surfaces as
_extract_error_freespin_progression.

Module-global discipline (feedback_subprocess_import_suicide_and_module_globals.md)
------------------------------------------------------------------------------------
No module-level I/O.  Registry state is in st_extract/__init__.py, not here.
Class methods do not read module globals.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, ClassVar

try:
    from fresh_slotlab.analyzer.st_extract._base import STExtractor
    from fresh_slotlab.analyzer.st_extract import register_extractor
    from fresh_slotlab.analyzer.core._utils import return_bucket
except ImportError:
    from analyzer.st_extract._base import STExtractor  # type: ignore[no-redef]
    from analyzer.st_extract import register_extractor  # type: ignore[no-redef]
    from analyzer.core._utils import return_bucket  # type: ignore[no-redef]

# Compile the ReMarks pattern once at module level (regex is stateless).
# M275 uses "Freespin N; " (N = 1..10).  The pattern accepts any integer
# to be forward-compatible with longer or differently-formatted sessions.
_FS_INDEX_RE = re.compile(r"Freespin\s+(\d+)", re.IGNORECASE)

# Dimension name matching the TriggerPathExtractor convention.
_DIM_NAME: str = "trigger_path"


def _parse_fs_index(round_dict: dict) -> int | None:
    """Extract the Freespin index (1-10) from ReMarks, or None if absent."""
    remarks = round_dict.get("ReMarks")
    if not remarks:
        return None
    m = _FS_INDEX_RE.search(str(remarks))
    if m is None:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _parse_er(round_dict: dict) -> float | None:
    """Extract the ExtraRatio value, or None if absent/invalid."""
    raw = round_dict.get("ExtraRatio")
    if raw is None:
        return None
    try:
        v = float(raw)
        return v if v >= 0.0 else None
    except (TypeError, ValueError):
        return None


class FreespinProgressionExtractor(STExtractor):
    """Per-round ExtraRatio + FS-index arc + session-tier accumulator.

    Declared by manifest spin_types blocks carrying "trigger_paths" on
    a ST with role == "freespin".  STs without that role are skipped.

    Reuses the discriminator/anchor-walk label resolution from
    TriggerPathExtractor by importing the class and calling
    _resolve_labels() directly — avoids copy-pasting the logic.

    Phase 3 deliverable (04_dimension_framework.md §6 Phase 3).
    """

    EXTRACTOR_ID: ClassVar[str] = "freespin_progression"
    DECLARED_IN_KEY: ClassVar[str] = "trigger_paths"

    def __init__(self, manifest: dict) -> None:
        self._manifest = manifest

        # Collect only freespin-role STs that also have trigger_paths.
        # (Other trigger_paths STs are handled by TriggerPathExtractor only.)
        self._fs_st_declarations: dict[int, dict] = {}  # st_int -> tp_block
        spin_types = manifest.get("spin_types") or {}
        for st_str, st_block in spin_types.items():
            if not isinstance(st_block, dict):
                continue
            if str(st_block.get("role", "")) != "freespin":
                continue
            tp = st_block.get("trigger_paths")
            if isinstance(tp, dict):
                try:
                    st_int = int(st_str)
                except (TypeError, ValueError):
                    continue
                self._fs_st_declarations[st_int] = tp

        # We need a TriggerPathExtractor instance bound to the same manifest
        # to reuse its label resolution (avoids copy-pasting discriminator
        # and anchor-walk logic).  Lazy import to avoid circular at module top.
        try:
            from fresh_slotlab.analyzer.st_extract.trigger_path import (
                TriggerPathExtractor,
            )
        except ImportError:
            from analyzer.st_extract.trigger_path import (  # type: ignore[no-redef]
                TriggerPathExtractor,
            )
        self._label_resolver = TriggerPathExtractor(manifest)

        # ── Chunk-level accumulators ──
        # (st_int, dim_name, path_label, fs_idx) -> er_val -> count
        self._er_by_fs_index: dict[
            tuple[int, str, str, int], dict[int, int]
        ] = defaultdict(lambda: defaultdict(int))
        # (st_int, dim_name, path_label, fs_idx) -> float
        self._er_sum_by_fs_index: dict[tuple[int, str, str, int], float] = defaultdict(float)
        # (st_int, dim_name, path_label, fs_idx) -> int
        self._fs_arc_round_count: dict[tuple[int, str, str, int], int] = defaultdict(int)
        self._fs_arc_win_round: dict[tuple[int, str, str, int], int] = defaultdict(int)
        self._fs_arc_win_sum: dict[tuple[int, str, str, int], float] = defaultdict(float)
        # (st_int, dim_name, path_label, robot_idx, block_id) -> float (session win so far)
        self._session_win_acc: dict[tuple[int, str, str, int, int], float] = defaultdict(float)
        # Set of (robot_idx, block_id) seen per (st_int, dim_name, path_label)
        self._session_keys_per_path: dict[
            tuple[int, str, str], set[tuple[int, int]]
        ] = defaultdict(set)

        # Per-robot state.
        self._robot_ctx: dict = {}
        # Alarm buckets surfaced as _unknown / _multi counts per (st, label).
        self._unknown_rounds: dict[tuple[int, str], int] = defaultdict(int)
        self._multi_rounds: dict[tuple[int, str], int] = defaultdict(int)

        # Error accumulator.
        self._obs_errors: list[str] = []
        self._begin_robot_error: str | None = None

    @classmethod
    def clone_for_manifest(cls, manifest: dict) -> "FreespinProgressionExtractor":
        return cls(manifest)

    def begin_robot(self, robot_ctx: dict) -> None:
        """Reset per-robot transient state (label resolver is stateful within robot)."""
        self._robot_ctx = robot_ctx
        # Forward begin_robot to the label resolver so it resets _prev_dim_key.
        self._label_resolver.begin_robot(robot_ctx)

    def observe_round(
        self,
        round_dict: dict,
        spin_type: int,
        round_ctx: dict,
    ) -> None:
        """Accumulate ER ladder + FS arc + session win per declared freespin ST."""
        # Forward every round to the label resolver so it can track _prev_dim_key
        # for the anchor-walk fallback.  This must happen BEFORE the early-return.
        self._label_resolver.observe_round(round_dict, spin_type, round_ctx)

        if spin_type not in self._fs_st_declarations:
            return

        tp_block: dict = self._fs_st_declarations[spin_type]
        robot_idx: int = round_ctx.get("robot_idx", 0)
        block_id: int | None = round_ctx.get("block_id")
        bet: int = round_ctx.get("bet", 1)
        effective_bet = float(bet) if bet and bet > 0 else 1.0
        win_amt: float = self._get_win(round_dict, round_ctx)

        # Resolve label via the shared resolver (round_field discriminator
        # or anchor-walk fallback — same logic as TriggerPathExtractor).
        labels = self._label_resolver._resolve_labels(
            round_dict, spin_type, tp_block, round_ctx
        )

        # Determine effective label for accumulation.
        is_multi = isinstance(labels, list)
        if is_multi:
            eff_label: str = "multi:" + "+".join(sorted(labels))
        else:
            eff_label = str(labels)

        dim_name = _DIM_NAME

        # Parse FS index and ExtraRatio from the round fields.
        fs_idx = _parse_fs_index(round_dict)
        er_val = _parse_er(round_dict)

        # Surface unknown/multi counts for alarm semantics.
        if eff_label.startswith("unknown:"):
            self._unknown_rounds[(spin_type, eff_label)] += 1
        elif is_multi:
            self._multi_rounds[(spin_type, eff_label)] += 1

        # Accumulate FS arc for this path label.
        if fs_idx is not None:
            arc_key = (spin_type, dim_name, eff_label, fs_idx)
            self._fs_arc_round_count[arc_key] += 1
            if win_amt > 0.0:
                self._fs_arc_win_round[arc_key] += 1
                self._fs_arc_win_sum[arc_key] += win_amt

        # Accumulate ER ladder: only when BOTH fs_idx and er_val are present.
        if fs_idx is not None and er_val is not None:
            er_ladder_key = (spin_type, dim_name, eff_label, fs_idx)
            er_int = int(er_val) if er_val == int(er_val) else er_val
            self._er_by_fs_index[er_ladder_key][int(er_int)] += 1
            self._er_sum_by_fs_index[er_ladder_key] += float(er_val)

        # Accumulate per-session win total (for session-tier histogram).
        if block_id is not None:
            sess_path_key = (spin_type, dim_name, eff_label, robot_idx, block_id)
            self._session_win_acc[sess_path_key] += win_amt
            sess_set_key = (spin_type, dim_name, eff_label)
            self._session_keys_per_path[sess_set_key].add((robot_idx, block_id))

            # For multi-trigger, also credit each individual path's session set.
            if is_multi:
                for path_label in labels:
                    ind_key = (spin_type, dim_name, path_label)
                    self._session_keys_per_path[ind_key].add((robot_idx, block_id))

    def finalize_chunk(self) -> dict:
        """Build the freespin-progression output dict.

        Shape: {st_str: {dim_name: {path_label: {er_ladder, fs_arc, session_tier_hist}}}}
        """
        result: dict[str, Any] = {}

        # Collect all (st_int, dim_name, path_label) keys.
        all_arc_keys: set[tuple[int, str, str, int]] = (
            set(self._fs_arc_round_count)
            | set(self._er_by_fs_index)
        )

        # Rebuild per (st, dim, path) aggregations.
        # First pass: collect all distinct (st, dim, path) tuples.
        st_dim_path_set: set[tuple[int, str, str]] = {
            (st, dim, path) for (st, dim, path, _) in all_arc_keys
        }

        for (st_int, dim_name, path_label) in st_dim_path_set:
            st_str = str(st_int)
            if st_str not in result:
                result[st_str] = {}
            if dim_name not in result[st_str]:
                result[st_str][dim_name] = {}

            # Collect all fs_indices for this (st, dim, path).
            fs_indices: set[int] = set()
            for (s, d, p, fi) in all_arc_keys:
                if (s, d, p) == (st_int, dim_name, path_label):
                    fs_indices.add(fi)

            er_ladder: dict[str, Any] = {}
            fs_arc: dict[str, Any] = {}

            for fs_idx in sorted(fs_indices):
                arc_key = (st_int, dim_name, path_label, fs_idx)
                rcount = int(self._fs_arc_round_count.get(arc_key, 0))
                wcount = int(self._fs_arc_win_round.get(arc_key, 0))
                wsum = float(self._fs_arc_win_sum.get(arc_key, 0.0))
                fs_arc[str(fs_idx)] = {
                    "round_count": rcount,
                    "win_round_count": wcount,
                    "win_sum": wsum,
                }

                er_dist = self._er_by_fs_index.get(arc_key)
                if er_dist:
                    er_sum = float(self._er_sum_by_fs_index.get(arc_key, 0.0))
                    er_ladder[str(fs_idx)] = {
                        "er_distribution": {str(k): int(v) for k, v in sorted(er_dist.items())},
                        "er_sum": er_sum,
                        "round_count": rcount,
                    }

            # Build session-tier histogram from per-session win totals.
            sess_path_key_prefix = (st_int, dim_name, path_label)
            sess_keys = self._session_keys_per_path.get(sess_path_key_prefix) or set()
            session_tier_hist: dict[str, int] = defaultdict(int)
            effective_bet = 1.0  # bet is stored via sessions; use 1.0 for relative bucketing
            # Retrieve the bet from _robot_ctx if available.
            bet_val = self._robot_ctx.get("bet", 1) if self._robot_ctx else 1
            if bet_val and bet_val > 0:
                effective_bet = float(bet_val)

            for (robot_idx, block_id) in sess_keys:
                win_total = float(
                    self._session_win_acc.get(
                        (st_int, dim_name, path_label, robot_idx, block_id), 0.0
                    )
                )
                mult = win_total / effective_bet if effective_bet > 0 else 0.0
                bucket = return_bucket(mult)
                session_tier_hist[bucket] += 1

            result[st_str][dim_name][path_label] = {
                "er_ladder": er_ladder,
                "fs_arc": fs_arc,
                "session_tier_hist": dict(session_tier_hist),
            }

        # Surface unknown/multi alarm counts.
        for (st_int, eff_label), count in self._unknown_rounds.items():
            st_str = str(st_int)
            if st_str not in result:
                result[st_str] = {}
            dim_name = _DIM_NAME
            if dim_name not in result[st_str]:
                result[st_str][dim_name] = {}
            result[st_str][dim_name][eff_label] = {
                "er_ladder": {},
                "fs_arc": {},
                "session_tier_hist": {},
                "_alarm": f"unknown path bucket: {count} rounds — see trigger_path extractor",
            }
        for (st_int, eff_label), count in self._multi_rounds.items():
            st_str = str(st_int)
            if st_str not in result:
                result[st_str] = {}
            dim_name = _DIM_NAME
            if dim_name not in result[st_str]:
                result[st_str][dim_name] = {}
            if eff_label not in result[st_str][dim_name]:
                result[st_str][dim_name][eff_label] = {
                    "er_ladder": {},
                    "fs_arc": {},
                    "session_tier_hist": {},
                    "_alarm": f"multi-trigger bucket: {count} rounds (additive_sessions)",
                }

        # Reset all accumulators for next chunk.
        self._er_by_fs_index = defaultdict(lambda: defaultdict(int))
        self._er_sum_by_fs_index = defaultdict(float)
        self._fs_arc_round_count = defaultdict(int)
        self._fs_arc_win_round = defaultdict(int)
        self._fs_arc_win_sum = defaultdict(float)
        self._session_win_acc = defaultdict(float)
        self._session_keys_per_path = defaultdict(set)
        self._unknown_rounds = defaultdict(int)
        self._multi_rounds = defaultdict(int)
        self._obs_errors = []
        self._begin_robot_error = None

        return result

    def _get_win(self, round_dict: dict, round_ctx: dict | None = None) -> float:
        """Extract win amount preferring rule-view win from round_ctx."""
        if round_ctx is not None and "win" in round_ctx:
            v = round_ctx["win"]
            try:
                fv = float(v)
                return fv if fv > 0.0 else 0.0
            except (TypeError, ValueError):
                pass
        raw = round_dict.get("WinCredits")
        if raw is None:
            raw = round_dict.get("WinAmount")
        if raw is None:
            return 0.0
        try:
            v = float(raw)
            return v if v > 0.0 else 0.0
        except (TypeError, ValueError):
            return 0.0


# ---------------------------------------------------------------------------
# Self-registration — fires at module import time
# ---------------------------------------------------------------------------
register_extractor(FreespinProgressionExtractor({}))
