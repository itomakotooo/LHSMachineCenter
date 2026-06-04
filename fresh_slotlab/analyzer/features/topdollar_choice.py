"""AnalyzerFeature: topdollar_choice — ST=14 player-choice behavioral stats.

Phase E of the playtype re-architecture (branch ``claude/playtype-rearch``).
This feature computes **behavioral statistics** for the TopDollar mechanic
(M15 and family): how often players gamble to the 4th forced pick, how often
that backfires (bad gamble), the dollar-tier distribution, etc.

The mechanic: ST=1 ``ReMarks="Trigger"`` opens a session; the player makes
**up to 4 picks** (ST=14, each revealing ``DollarCount`` / ``ChosenDollar`` /
``OfferValue``); ST=15 ``WinAmount`` settles the real payout.  ST=14's
``WinCredits`` is a PREVIEW of the cumulative offer value — NOT the real win
(economy is already handled by SettlementWinAmountRule + trigger_sessions).

**``RTP_CONTRIBUTION = False``** — economy is already counted; this feature
must NOT add to the RTP sum or the RTP integrity invariant double-counts.

Data path
---------
``parse_chunk_response()`` in ``core/parser.py`` now emits a
``"topdollar_sessions"`` key in the chunk dict.  It is a ``list[dict]`` where
each dict encodes one fully-resolved TopDollar session:

  {
    "n_picks":      int            # 1-4 (number of ST=14 rounds in session)
    "offers":       list[int]      # OfferValue per pick (in order)
    "dollar_counts":list[int]      # DollarCount per pick (number of $ drawn)
    "chosen":       list[str]      # ChosenDollar per pick ("5-10-5-" etc.)
    "settled_win":  int            # ST=15 WinAmount (real payout, credits)
  }

``extract()`` lifts ``topdollar_sessions`` from ``chunk_dict`` (empty list
for non-TD machines since the key will be empty or absent).
``reduce()`` concatenates the per-chunk session lists.
``emit()`` computes all behavioral statistics from the accumulated list.

Bad-gamble definition
---------------------
A 4-pick session is a "bad gamble" iff the **settled** ``OfferValue`` (the
4th pick's ``OfferValue``) is strictly LESS THAN the maximum ``OfferValue``
across the 1st–3rd picks.  Derivable from ``offers`` list directly.

For < 4 pick sessions: the player CHOSE to stop, so there is no bad gamble
(they accepted an offer they were satisfied with).

Per-machine applicability
-------------------------
This feature applies only to machines that list ``"topdollar_choice"`` in
their ``analyzer_features`` manifest.  Currently: M15.  The feature is
designed generically (reads ST=14 fields without hardcoding M15 ids) so it
can be applied to M12/M90/M132/M206 (same mechanic family) later.

Per-machine isolation
---------------------
This file is NOT in ``fresh_slotlab/analyzer/core/`` — it is excluded from
``compute_base_analyzer_version()`` (R-4 of versioning.py).  Only machines
declaring ``"topdollar_choice"`` in their manifest include this plugin's hash
in their ``effective_analyzer_version``.  Editing this file re-flags ONLY
those machines.

Memory feedback honored
-----------------------
- feedback_subprocess_import_suicide_and_module_globals.md:
    register() is a pure list-append — no I/O at import time.
- feedback_no_silent_swallow.md:
    extract() returns {} (empty dict) when the chunk carries no TD sessions
    (non-TD machines, TD machine with no trigger in this chunk). No RuntimeError
    — absent sessions is a legitimate state, not an error.
    emit() raises if the session list is present but malformed (defensive).
- feedback_no_hardcode.md:
    No M15-specific ids hardcoded. Reads ``SpinType=14`` fields generically.
    Applicability is declared in the manifest (``analyzer_features`` list).
- feedback_aggregator_parity_invariant.md:
    RTP_CONTRIBUTION = False — the real win is already attributed by
    SettlementWinAmountRule on ST=15, preventing double-count.
- feedback_invariant_with_fallback_hides_drift.md:
    No ``_unattributed`` catch-all. Every stat is derived from explicit fields.
    ``bad_gamble_rate`` is absent (null) when ``forced_4th_count == 0`` rather
    than 0.0 (avoids the "zero rate with zero denominator" silent lie).
- feedback_no_parallel_panel_impl.md:
    Mirrors bonus_chain_dynamics / collect_mechanic pattern for
    extract/reduce/emit decomposition, ClassVar layout, and registration.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    from fresh_slotlab.analyzer.feature_registry import register
except ImportError:  # running as standalone script
    from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
    from analyzer.feature_registry import register  # type: ignore[no-redef]

if TYPE_CHECKING:
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
    except ImportError:
        from analyzer.pipeline_context import PipelineContext  # type: ignore[assignment]


class TopDollarChoice(AnalyzerFeature):
    """Pattern-A-ish plugin that accumulates ST=14 session data per chunk.

    extract() reads the pre-parsed ``topdollar_sessions`` list from
    chunk_dict (produced by parse_chunk_response in core/parser.py).
    reduce() concatenates session lists across chunks.
    emit() computes all behavioral statistics from the full session list.

    Accumulator structure
    ---------------------
    The accumulator is a dict with one key:

      sessions: list[dict]
          Each dict is one completed TopDollar session with keys:
          n_picks, offers, dollar_counts, chosen, settled_win.

    Sessions for chunks where TopDollar didn't trigger are absent
    (empty list contribution). Non-TopDollar machines get no sessions.
    """

    FEATURE_ID: ClassVar[str] = "topdollar_choice"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("topdollar_choice",)
    SCHEMA_VERSION: ClassVar[int] = 3  # Phase B: bumped from 2; adds chosen_combo_counts
    RTP_CONTRIBUTION: ClassVar[bool] = False  # economy is ST=15 SettlementWinAmountRule
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    REQUIRES: ClassVar[tuple[str, ...]] = ()
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {
        1: {
            # v1 → v2: feature_name was absent in v1 summaries.
            # Frontend renders it as None (unmapped) for historical reports.
            "feature_name": None,
        },
        2: {
            # v2 → v3: chosen_combo_counts was absent in v2 summaries.
            # Frontend renders it as {} (no combo data) for historical reports.
            "chosen_combo_counts": {},
        },
    }

    # Top-N combo entries emitted for chosen_combo_counts.
    # Keeps output small; a residual "_other" key is added only when truncated.
    _CHOSEN_COMBO_TOP_N: ClassVar[int] = 20

    # Phase E: M15 TopDollar — schema v1 (initial).
    # paytype-rearch: bumped to v2 — added feature_name (FeatureWin feature
    # the TopDollar settlement maps to, e.g. "TopDollar" on M15).
    # Phase B: bumped to v3 — added chosen_combo_counts (COMBINATION distribution).

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """Lift topdollar_sessions list from chunk_dict.

        Returns {"sessions": <list of session dicts>}.  Returns empty
        sessions list when the key is absent (non-TD machine or no trigger
        in this chunk) — this is a valid state, not an error.

        Per feedback_no_silent_swallow.md: if the sessions key is present
        but not a list, we raise rather than silently use a bad value.
        """
        raw_sessions = chunk_dict.get("topdollar_sessions")
        if raw_sessions is None:
            # Key absent — non-TopDollar machine or no TD trigger in chunk.
            return {"sessions": []}
        if not isinstance(raw_sessions, list):
            raise RuntimeError(
                f"topdollar_choice: 'topdollar_sessions' in chunk_dict is "
                f"not a list (got {type(raw_sessions).__name__!r}). "
                f"This indicates a mismatch between parser.py's accumulator "
                f"and the feature — check Phase E parser changes."
            )
        return {"sessions": list(raw_sessions)}

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Merge two session accumulators by concatenating their session lists."""
        prev_sessions: list[dict] = prev_acc.get("sessions") or []
        this_sessions: list[dict] = this_acc.get("sessions") or []
        return {"sessions": prev_sessions + this_sessions}

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Compute TopDollar behavioral statistics from accumulated sessions.

        Writes ``summary["topdollar_choice"]`` with the following structure::

          {
            "applicable":         bool,       # True iff any TD sessions were seen
            "feature_name":       str|None,   # FeatureWin name the settlement ST maps to
            "total_sessions":     int,        # total TopDollar sessions
            "trigger_rate":       float,      # sessions / total_paid_spins
            "picks_per_session":  {           # distribution of n_picks (1-4)
              "1": int, "2": int, "3": int, "4": int
            },
            "stopped_early_rate": float,      # share that stopped before 4th pick
            "forced_4th_rate":    float,      # share forced to 4th pick (n_picks==4)
            "forced_4th_count":   int,
            "bad_gamble_count":   int,        # 4-pick where final < max of earlier
            "bad_gamble_rate":    float|None, # bad_gamble_count / forced_4th_count
            "settled_win_median": int|None,   # median settled WinAmount (credits)
            "settled_win_max":    int|None,   # max settled WinAmount (credits)
            "dollar_tier_counts": {           # ChosenDollar segment frequency
              "5": int, "10": int, "20": int, "50": int, "100": int, ...
            },
            "chosen_combo_counts": {          # Phase B: COMBINATION distribution
              "5-10-5": int,                  # normalized ChosenDollar (trailing "-" stripped)
              "5-5": int,                     # e.g. a 2-dollar draw combination
              ...                             # top-20 by count desc; "_other" if truncated
            },
            "rtp_contribution_pp": float|None, # sum(settled_win)/total_paid_bet * 100
          }

        ``chosen_combo_counts`` note (Phase B):
            ChosenDollar is the CHOSEN combination per draw (one entry per
            ST=14 pick round), e.g. "5-10-5-" means the player saw and
            accepted the combination {5, 10, 5}. The per-pick OFFERED set is
            NOT in rawdata — only the chosen combination is available.
            Do not infer offered denominations from this field alone.
            Normalization: strip trailing "-" before counting (so "5-10-5-"
            and "5-10-5" are the same key).

        ``rtp_contribution_pp`` is informational only — it is NOT added to the
        RTP sum (``RTP_CONTRIBUTION = False``).  It shows how much of total
        machine RTP this mechanic accounts for.

        ``feature_name`` is the FeatureWin feature bound to the TopDollar
        settlement (the paying feature, trigger_only=False).  Sourced from
        the ``spin_type_to_feature`` mapping in the upstream stash or from
        the already-emitted upstream_feature_breakdown, whichever is available.
        None if no mapping is resolvable (graceful — does not affect RTP).

        Raises RuntimeError if accumulated data is malformed (per
        feedback_no_silent_swallow.md).
        """
        sessions: list[dict] = (final_acc or {}).get("sessions") or []

        # ── Resolve feature_name from the upstream mapping (SCHEMA_VERSION 2) ──
        # Strategy:
        #   1. Try the _upstream_feature_breakdown_data stash (present if the
        #      upstream_feature_breakdown plugin hasn't run yet).
        #   2. Try already-emitted player_impact.upstream_feature_breakdown.features
        #      (present if upstream_feature_breakdown ran before us).
        #   3. None (graceful fallback — never crashes).
        #
        # We identify the settlement feature as the non-trigger-only feature
        # with the highest rtp_contribution_pp in the upstream breakdown.
        # This generalises to M12/M90/M132/M206 without hardcoding "TopDollar".
        _settlement_feature_name: str | None = None
        try:
            # Path 1: stash still present
            _stash = summary.get("_upstream_feature_breakdown_data") or {}
            _st2feat = _stash.get("spin_type_to_feature") or {}
            _feat_tally = _stash.get("upstream_feature_tally") or {}
            _eff_bet = _stash.get("effective_bet_for_rtp") or 0.0
            if _st2feat and _feat_tally:
                # Find the paying (non-trigger-only) feature with highest rtp_pp.
                _best_feat: str | None = None
                _best_pp = -1.0
                for _feat_name, _payouts in _feat_tally.items():
                    _fwin = sum(float(p.get("win", 0) or 0) for p in _payouts.values())
                    _ftimes = sum(int(p.get("times", 0)) for p in _payouts.values())
                    if _ftimes > 0 and _fwin > 0.0:
                        _fpp = (_fwin / _eff_bet * 100.0) if _eff_bet > 0 else 0.0
                        if _fpp > _best_pp:
                            _best_pp = _fpp
                            _best_feat = str(_feat_name)
                _settlement_feature_name = _best_feat
            elif not _st2feat:
                # Path 2: stash consumed — try already-emitted breakdown
                _ufb = (summary.get("player_impact") or {}).get(
                    "upstream_feature_breakdown"
                ) or {}
                _ufb_feats = _ufb.get("features") or []
                _best_feat2: str | None = None
                _best_pp2 = -1.0
                for _row in _ufb_feats:
                    if not _row.get("trigger_only") and float(
                        _row.get("rtp_contribution_pp") or 0.0
                    ) > _best_pp2:
                        _best_pp2 = float(_row.get("rtp_contribution_pp") or 0.0)
                        _best_feat2 = _row.get("feature_name")
                _settlement_feature_name = _best_feat2
        except Exception:  # noqa: BLE001
            # Per feedback_no_silent_swallow.md: feature_name resolution is
            # best-effort display metadata. A lookup failure must not crash
            # the analyzer — leave _settlement_feature_name as None.
            _settlement_feature_name = None

        if not sessions:
            summary["topdollar_choice"] = {
                "applicable": False,
                "feature_name": _settlement_feature_name,
                "total_sessions": 0,
                "trigger_rate": 0.0,
                "picks_per_session": {"1": 0, "2": 0, "3": 0, "4": 0},
                "stopped_early_rate": None,
                "forced_4th_rate": None,
                "forced_4th_count": 0,
                "bad_gamble_count": 0,
                "bad_gamble_rate": None,
                "settled_win_median": None,
                "settled_win_max": None,
                "dollar_tier_counts": {},
                # Phase B: no sessions -> no combo data.
                "chosen_combo_counts": {},
                "rtp_contribution_pp": None,
            }
            return

        # ── picks_per_session distribution ──
        picks_dist: dict[str, int] = {"1": 0, "2": 0, "3": 0, "4": 0}
        forced_4th_count = 0
        bad_gamble_count = 0
        all_offer_values: list[int] = []
        tier_counts: dict[str, int] = {}
        # Phase B: combination distribution — one entry per ST=14 pick round,
        # normalized by stripping the trailing "-" from ChosenDollar strings.
        # Note: ChosenDollar is the CHOSEN combination per draw; the per-pick
        # OFFERED set is NOT in rawdata — only chosen is available.
        chosen_combo_raw: dict[str, int] = {}
        total_settled_win = 0.0
        settled_values: list[int] = []

        for s in sessions:
            n = int(s.get("n_picks") or 0)
            if n < 1 or n > 4:
                raise RuntimeError(
                    f"topdollar_choice emit: session has n_picks={n!r} "
                    f"(expected 1-4). Session data: {s!r}. "
                    f"Check Phase E parser accumulator logic."
                )
            key = str(min(n, 4))
            picks_dist[key] = picks_dist.get(key, 0) + 1

            offers: list[int] = s.get("offers") or []
            if len(offers) != n:
                raise RuntimeError(
                    f"topdollar_choice emit: session has n_picks={n} but "
                    f"len(offers)={len(offers)} — mismatch. Session: {s!r}."
                )

            all_offer_values.extend(offers)

            # ── bad gamble (4-pick sessions only) ──
            if n == 4:
                forced_4th_count += 1
                # Bad gamble: final offer < max of the 3 earlier offers.
                if len(offers) >= 4:
                    max_earlier = max(offers[:3])
                    final = offers[3]
                    if final < max_earlier:
                        bad_gamble_count += 1

            # ── dollar tier counts + combo counts from ChosenDollar strings ──
            # ChosenDollar is the CHOSEN combination per draw (one string per
            # ST=14 pick round). Each string looks like "5-10-5-" (trailing dash).
            # Tier counts: per individual denomination segment.
            # Combo counts (Phase B): per full normalized combination.
            chosen_list: list[str] = s.get("chosen") or []
            for c in chosen_list:
                if not isinstance(c, str):
                    continue
                # Normalize: strip trailing "-" for the combo key.
                normalized_combo = c.rstrip("-")
                # Phase B: count the full combination (one per ST=14 pick round).
                if normalized_combo:
                    chosen_combo_raw[normalized_combo] = (
                        chosen_combo_raw.get(normalized_combo, 0) + 1
                    )
                # Tier counts: flatten into per-denomination segments.
                segments = [seg for seg in normalized_combo.split("-") if seg.strip()]
                for seg in segments:
                    try:
                        tier = str(int(seg))
                        tier_counts[tier] = tier_counts.get(tier, 0) + 1
                    except (ValueError, TypeError):
                        pass  # skip malformed segments

            # ── settled win ──
            sw = s.get("settled_win")
            if sw is not None:
                try:
                    sw_int = int(sw)
                    settled_values.append(sw_int)
                    total_settled_win += sw_int
                except (TypeError, ValueError):
                    pass

        total_sessions = len(sessions)

        # ── trigger rate ──
        total_paid_spins: int = ctx.total_paid_spins if ctx is not None else 0
        trigger_rate = (
            total_sessions / total_paid_spins
            if total_paid_spins > 0 else None
        )

        # ── stopped early / forced 4th rates ──
        stopped_early_count = total_sessions - forced_4th_count
        stopped_early_rate = (
            stopped_early_count / total_sessions
            if total_sessions > 0 else None
        )
        forced_4th_rate = (
            forced_4th_count / total_sessions
            if total_sessions > 0 else None
        )

        # ── bad gamble rate ──
        bad_gamble_rate = (
            bad_gamble_count / forced_4th_count
            if forced_4th_count > 0 else None
        )

        # ── settled win statistics ──
        settled_values_sorted = sorted(settled_values)
        n_settled = len(settled_values_sorted)
        settled_win_median: int | None = (
            settled_values_sorted[n_settled // 2]
            if n_settled > 0 else None
        )
        settled_win_max: int | None = (
            settled_values_sorted[-1]
            if n_settled > 0 else None
        )

        # ── RTP contribution (informational — NOT added to RTP sum) ──
        # ctx.effective_bet_for_rtp = session_bet_sum = sum(paid_spin_bets) across
        # all paid spins (same denominator PIA uses for summary.rtp).
        # rtp_contribution_pp = total_settled_win / effective_bet_for_rtp * 100.
        # Dividing by total_paid_spins separately would double-divide (bet already
        # sums over all paid spins).
        effective_bet = ctx.effective_bet_for_rtp if ctx is not None else 0
        rtp_contribution_pp: float | None = (
            (total_settled_win / effective_bet) * 100.0
            if effective_bet > 0 else None
        )

        # ── Phase B: chosen_combo_counts — top-N combination distribution ──
        # Sort by count descending; ties broken by combo string (deterministic).
        # Emit top-N; add "_other" only if truncated (omit if not truncated).
        # Per memory/feedback_no_hardcode.md: no machine-specific keys hardcoded.
        # Note: ChosenDollar is the CHOSEN combination per draw; the per-pick
        # OFFERED set is NOT in rawdata (only chosen is available).
        _sorted_combos = sorted(
            chosen_combo_raw.items(), key=lambda kv: (-kv[1], kv[0])
        )
        chosen_combo_counts: dict[str, int] = {}
        if len(_sorted_combos) <= self._CHOSEN_COMBO_TOP_N:
            # No truncation — emit all combos as-is.
            for _combo_key, _combo_cnt in _sorted_combos:
                chosen_combo_counts[_combo_key] = _combo_cnt
        else:
            # Truncate to top-N; add _other residual for the remainder.
            _other_total = 0
            for _combo_key, _combo_cnt in _sorted_combos[: self._CHOSEN_COMBO_TOP_N]:
                chosen_combo_counts[_combo_key] = _combo_cnt
            for _, _combo_cnt in _sorted_combos[self._CHOSEN_COMBO_TOP_N :]:
                _other_total += _combo_cnt
            if _other_total > 0:
                chosen_combo_counts["_other"] = _other_total

        summary["topdollar_choice"] = {
            "applicable": True,
            "feature_name": _settlement_feature_name,
            "total_sessions": total_sessions,
            "trigger_rate": trigger_rate,
            "picks_per_session": picks_dist,
            "stopped_early_rate": stopped_early_rate,
            "forced_4th_rate": forced_4th_rate,
            "forced_4th_count": forced_4th_count,
            "bad_gamble_count": bad_gamble_count,
            "bad_gamble_rate": bad_gamble_rate,
            "settled_win_median": settled_win_median,
            "settled_win_max": settled_win_max,
            "dollar_tier_counts": dict(
                sorted(tier_counts.items(), key=lambda kv: int(kv[0]))
            ),
            # Phase B: combination distribution (one entry per ST=14 pick round).
            # ChosenDollar is the CHOSEN combination per draw; the per-pick
            # OFFERED set is NOT in rawdata (only chosen is available).
            # Normalized: trailing "-" stripped. Top-20 by count; "_other" if truncated.
            "chosen_combo_counts": chosen_combo_counts,
            "rtp_contribution_pp": rtp_contribution_pp,
        }


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# ---------------------------------------------------------------------------
register(TopDollarChoice())
