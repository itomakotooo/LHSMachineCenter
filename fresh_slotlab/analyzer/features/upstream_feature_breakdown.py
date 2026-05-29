"""AnalyzerFeature: upstream_feature_breakdown — Pattern B plugin that OWNS the compute.

Phase C5 of analyzer unbundle (M275-driven) introduced this plugin per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §7.2
and session_artifacts/_impl/phase_c5/brief.md §2.1.

Phase 3 (analyzer honesty/isolation; see
session_artifacts/_arch_honesty_isolation/07_decision.md §5 Phase 3-6 + R-11 and
session_artifacts/_impl/phase_extract_3_upstream_feature/brief.md) carved the
ENTIRE ``upstream_feature_breakdown`` row-BUILD OUT of player_impact_analyzer.py
(PIA) and INTO this plugin's ``emit()`` (mirrors the 2a collect_mechanic / 2b
bonus_chain_dynamics carves).  Before Phase 3 the plugin was a Pattern-B stash
*shell*: PIA built the fully-formed ``{applicable, source, features}`` dict
inline (~400 lines: the ``sub_streams_by_feature`` post-processing, the reverse
``spin_type_prev_counts`` table, the per-feature row-assembly loop with its
successor/predecessor inference + per-feature multiplier-bucket histograms +
per-path splitting, the sort, and the ``applicable`` flag — PIA:~3505-3892) and
stashed it; this plugin only re-wrote it back unchanged (passthrough).  After
Phase 3:

  - PIA's stash ``summary["_upstream_feature_breakdown_data"]`` carries only the
    RAW accumulator inputs the row-build reads (upstream_feature_tally, the
    SpinType transition / bucket / chain accumulators, the resolved
    feature→SpinType maps, the resolved BCM bonus feature, etc. — no compute).
  - ``emit()`` re-sources those raw inputs, builds the
    ``{applicable, source, features}`` dict VERBATIM (key order / float forms /
    None-vs-0.0 / sort orders preserved — output byte-identical to the pre-carve
    report), and writes ``summary["player_impact"]["upstream_feature_breakdown"]``.

Why the carve: editing this feature's logic must flip ONLY
upstream_feature_breakdown's feature_hash, not ``compute_base_analyzer_version()``
(the fleet-wide base).  PIA shed the ~400-line row-builder, so base shrinks
one-time (report content byte-identical) and this feature's compute now lives
with its own hash.

Mechanism
---------
The upstream API groups payouts by a semantic feature name (string: e.g.
"Normal", "NormalCollectionSpin", "NewFreespin") — richer than the round-level
SpinType int.  For single-feature machines (M14: just "Normal") the breakdown
is redundant with payout_ids_top20, so applicable=False.  For multi-feature
machines (M272 / M275) it is the authoritative per-bonus attribution the
operator needs.

Shared helpers stay in PIA (circular-import law)
------------------------------------------------
The row-build calls four helpers.  Three are SHARED (called elsewhere and/or
unit-tested against the PIA module directly) and MUST NOT move — the plugin must
NEVER import PIA (circular):

  - ``_infer_feature_spin_type_mapping`` (PIA) — also unit-tested directly
    (tests/backend/test_feature_chain_inference.py).  PIA pre-computes its three
    results (feature_to_spin_type / spin_type_to_feature / ambiguous_mapped) and
    stashes them as raw inputs.
  - ``_resolve_bonus_feature`` (PIA) — SHARED with the collect_mechanic stash
    path + unit-tested directly (tests/backend/test_bcm_resolver.py).  PIA
    pre-resolves the (feature, source) strings and stashes them.
  - ``_load_bcm_pairings`` (PIA) — used only by ``_resolve_bonus_feature``;
    stays in PIA.

The fourth, ``build_multiplier_bucket_rows``, already lives in
``fresh_slotlab.analyzer.core.aggregator`` (a base-closure module the plugin may
import dual-path — no circular dependency).  It is imported at module top below.

Stash pattern (Phase 3 — raw inputs; plugin OWNS the build)
-----------------------------------------------------------
The PIA block writes ``summary["_upstream_feature_breakdown_data"]`` carrying the
RAW inputs the row-build reads (no compute):
  - ``upstream_feature_tally`` — the per-feature per-pid {win, times} tally.
  - ``feature_to_spin_type`` / ``spin_type_to_feature`` / ``ambiguous_mapped`` —
    results of ``_infer_feature_spin_type_mapping`` (helper stays in PIA).
  - ``bcm_bonus_feature`` / ``bcm_bonus_source`` — results of
    ``_resolve_bonus_feature`` (helper stays in PIA).
  - the SpinType transition table ``spin_type_next_counts``.
  - the chain post-processing accumulators ``chain_chunk_summaries`` +
    ``chain_bucket_{spins,bet,win}`` (drive the per-path sub_streams build).
  - the round-level bucket accumulators ``spin_type_bucket_{spins,bet,win}`` +
    the settlement-ST fallbacks ``session_bucket_{spins,bet,win}_by_settlement_st``.
  - ``spin_type_spins`` + ``spin_type_nudge_round_count`` (wild-nudge tagging).
  - the scalars ``total_spins`` / ``effective_bet_for_rtp`` / ``upstream_total_win``.

emit() reads the stash, removes it, BUILDS the ``{applicable, source, features}``
dict verbatim (byte-identical to the pre-carve report), and writes
``summary["player_impact"]["upstream_feature_breakdown"]``.

Output schema (SCHEMA_VERSION = 1 — identical to the pre-C5 inline block)
--------------------------------------------------------------------------
summary["player_impact"]["upstream_feature_breakdown"]:
  applicable   — bool; False for single-"Normal" machines
  source       — str; "analysisResult.FeatureWin"
  features      — list of feature rows (see the row-build below for the full schema)

Per-machine isolation
---------------------
This plugin file is NOT in fresh_slotlab/analyzer/core/ so its addition does
NOT change compute_base_analyzer_version().  Only machines that declare
"upstream_feature_breakdown" in their manifest's analyzer_features list will
include this plugin's hash in their effective_analyzer_version.

REQUIRES = () — data arrives via a temp stash key written by the PIA inline
block.  No emit-loop ordering dependency.

Memory feedback honored
-----------------------
- feedback_subprocess_import_suicide_and_module_globals.md:
    register() is a pure list-append — no I/O at import time.
- feedback_no_silent_swallow.md:
    If _upstream_feature_breakdown_data stash key is missing, emit() raises
    a diagnostic RuntimeError (not silently skipped).  Each expected RAW input
    key is read by explicit indexing — a missing key raises a descriptive
    RuntimeError (never a silent default that would corrupt report numbers).
- feedback_invariant_with_fallback_hides_drift.md:
    applicable=False is an explicit "no multi-feature data" signal — NOT a
    catch-all bucket.  Machines that don't declare this feature won't have
    the key at all.
- feedback_no_hardcode.md:
    No machine-specific semantics hardcoded; the resolved feature→SpinType maps
    and BCM bonus feature derive entirely from observed data + manifest overrides
    (computed by the PIA helpers, re-sourced from the stash).
- feedback_prefer_complex_better.md:
    Verbatim carve of the full row-build (not a simplified rewrite); the byte-
    identity contract demands the moved compute preserve key order / float forms
    / None-vs-0.0 / sort orders exactly.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any, ClassVar

try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    from fresh_slotlab.analyzer.feature_registry import register
    from fresh_slotlab.analyzer.core.aggregator import build_multiplier_bucket_rows
except ImportError:  # running as standalone script
    from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
    from analyzer.feature_registry import register  # type: ignore[no-redef]
    from analyzer.core.aggregator import build_multiplier_bucket_rows  # type: ignore[no-redef]

if TYPE_CHECKING:
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
    except ImportError:
        from analyzer.pipeline_context import PipelineContext  # type: ignore[assignment]

# Stash key written by the PIA stash builder. Carries the RAW row-build inputs
# (Phase 3 carve — this plugin builds the dict). Analogous to
# _collect_mechanic_data / _bonus_chain_dynamics_data (Phase 2a/2b raw-input stashes).
_STASH_KEY = "_upstream_feature_breakdown_data"


class UpstreamFeatureBreakdown(AnalyzerFeature):
    """Pattern B plugin that OWNS the upstream FeatureWin breakdown compute.

    extract() / reduce() are no-ops (data flows via the pre-emit stash key).
    emit() re-sources the raw accumulators from the stash, BUILDS the
    ``{applicable, source, features}`` dict verbatim (Phase 3 carve —
    byte-identical to the pre-carve report), and writes
    summary["player_impact"]["upstream_feature_breakdown"].

    Accumulator structure
    ---------------------
    No accumulator — this plugin uses the stash pattern.
    extract() returns {} always.
    reduce() returns {} always.
    """

    FEATURE_ID: ClassVar[str] = "upstream_feature_breakdown"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("upstream_feature_breakdown",)
    SCHEMA_VERSION: ClassVar[int] = 1  # C5: initial plugin version; Phase 3 carve byte-identical
    RTP_CONTRIBUTION: ClassVar[bool] = False  # display only; doesn't add to RTP totals
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    REQUIRES: ClassVar[tuple[str, ...]] = ()  # stash key pre-exists before emit loop
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """No-op — upstream_feature_breakdown uses the pre-emit stash pattern."""
        return {}

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """No-op — no per-chunk accumulator."""
        return {}

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Build the upstream FeatureWin breakdown from raw stash; write it.

        Steps
        -----
        1. Read and remove the stash key written by the PIA stash builder; read
           each RAW input by explicit indexing (fail-loud — no silent default
           that would corrupt report numbers).
        2. BUILD summary["player_impact"]["upstream_feature_breakdown"] verbatim
           from the raw inputs (Phase 3 carve — byte-identical to the pre-carve
           report): the per-path sub_streams post-processing, the reverse
           transition table, the per-feature row loop with successor/predecessor
           inference + per-feature multiplier-bucket histograms + per-path
           splitting, the sort, and the ``applicable`` flag.

        Raises RuntimeError (surfaced as feature_error) if:
          - The stash key is absent (per feedback_no_silent_swallow.md)
          - Any of the RAW input keys is absent (Phase 3 carve contract;
            per feedback_no_silent_swallow.md — never silently default)
        """
        if _STASH_KEY not in summary:
            raise RuntimeError(
                f"upstream_feature_breakdown plugin: stash key '{_STASH_KEY}' "
                f"not found in summary. PIA stash builder (Phase 3 carve) may be "
                f"incomplete. Expected it to write this key before the emit loop."
            )

        stash: dict[str, Any] = summary.pop(_STASH_KEY)

        # ── Read the RAW row-build inputs (Phase 3 carve) ──
        # The PIA stash now carries raw inputs only; this plugin OWNS the
        # row-build (moved verbatim from PIA:~3505-3892). Per
        # feedback_no_silent_swallow.md: each expected raw key is read by
        # explicit indexing so a missing key raises a diagnostic RuntimeError
        # (never a silent default that would corrupt the report numbers).
        _expected_keys = (
            "upstream_feature_tally",
            "feature_to_spin_type", "spin_type_to_feature", "ambiguous_mapped",
            "bcm_bonus_feature", "bcm_bonus_source",
            "spin_type_next_counts",
            "chain_chunk_summaries",
            "chain_bucket_spins", "chain_bucket_bet", "chain_bucket_win",
            "spin_type_bucket_spins", "spin_type_bucket_bet", "spin_type_bucket_win",
            "session_bucket_spins_by_settlement_st",
            "session_bucket_bet_by_settlement_st",
            "session_bucket_win_by_settlement_st",
            "spin_type_spins", "spin_type_nudge_round_count",
            "total_spins", "effective_bet_for_rtp", "upstream_total_win",
        )
        _missing = [k for k in _expected_keys if k not in stash]
        if _missing:
            raise RuntimeError(
                f"upstream_feature_breakdown plugin: stash '{_STASH_KEY}' is "
                f"missing expected raw input key(s) {_missing!r}. The PIA Phase 3 "
                f"carve stash builder must populate every raw input before the "
                f"emit loop. Refusing to silently default (would corrupt report "
                f"numbers) — see feedback_no_silent_swallow.md."
            )

        upstream_feature_tally = stash["upstream_feature_tally"]
        feature_to_spin_type = stash["feature_to_spin_type"]
        spin_type_to_feature = stash["spin_type_to_feature"]
        ambiguous_mapped = stash["ambiguous_mapped"]
        _bcm_bonus_feature = stash["bcm_bonus_feature"]
        _bcm_bonus_source = stash["bcm_bonus_source"]
        spin_type_next_counts = stash["spin_type_next_counts"]
        chain_chunk_summaries = stash["chain_chunk_summaries"]
        chain_bucket_spins = stash["chain_bucket_spins"]
        chain_bucket_bet = stash["chain_bucket_bet"]
        chain_bucket_win = stash["chain_bucket_win"]
        spin_type_bucket_spins = stash["spin_type_bucket_spins"]
        spin_type_bucket_bet = stash["spin_type_bucket_bet"]
        spin_type_bucket_win = stash["spin_type_bucket_win"]
        session_bucket_spins_by_settlement_st = stash["session_bucket_spins_by_settlement_st"]
        session_bucket_bet_by_settlement_st = stash["session_bucket_bet_by_settlement_st"]
        session_bucket_win_by_settlement_st = stash["session_bucket_win_by_settlement_st"]
        spin_type_spins = stash["spin_type_spins"]
        spin_type_nudge_round_count = stash["spin_type_nudge_round_count"]
        total_spins = stash["total_spins"]
        effective_bet_for_rtp = stash["effective_bet_for_rtp"]
        upstream_total_win = stash["upstream_total_win"]

        # ── Build the upstream_feature_breakdown — moved VERBATIM from
        # PIA:~3505-3892. Dict/list key order, float forms, None-vs-0.0, and
        # sort orders preserved exactly (the byte-identity contract depends on
        # this being a verbatim move, not a rewrite). The SHARED helpers
        # (_infer_feature_spin_type_mapping / _resolve_bonus_feature /
        # _load_bcm_pairings) stay in PIA — their RESULTS are re-sourced from
        # the stash above (feature_to_spin_type / spin_type_to_feature /
        # ambiguous_mapped / _bcm_bonus_feature / _bcm_bonus_source). The
        # build_multiplier_bucket_rows helper is imported from
        # analyzer.core.aggregator (a base-closure module — no circular import).

        # Post-process bonus-chain summaries into per-path accumulators
        # (keyed by (feature, label)). User feedback 2026-04-19: the
        # previous sub_streams structure nested all paths under one feature
        # row but kept the bucket distribution SHARED — so operators
        # couldn't tell the via-wheel vs via-BCM paths apart at the bucket
        # level. Now each (feature, label) path carries its own bucket
        # histograms aggregated from chain_bucket_{spins,bet,win}, and the
        # feature assembly emits a SEPARATE row per path when N paths ≥ 2.
        _sub_stream_acc: dict[tuple, dict[str, Any]] = defaultdict(
            lambda: {
                "fires": 0, "win": 0.0, "bet": 0.0,
                "bucket_spins": defaultdict(int),
                "bucket_bet": defaultdict(float),
                "bucket_win": defaultdict(float),
            }
        )
        for (first_st, cc_reset, sp_type), stats in chain_chunk_summaries.items():
            feat_in_chain = spin_type_to_feature.get(int(sp_type))
            if not feat_in_chain:
                continue
            if cc_reset:
                label = "via BCM cycle"
            else:
                entry_feat = spin_type_to_feature.get(int(first_st))
                label = f"via {entry_feat}" if entry_feat else f"via ST{first_st}"
            key = (feat_in_chain, label)
            acc = _sub_stream_acc[key]
            acc["fires"] += int(stats["count"] or 0)
            acc["win"] += float(stats["win"] or 0)
            acc["bet"] += float(stats["bet"] or 0)
            # Aggregate per-path bucket histograms keyed by the same tuple.
            bkey = (first_st, cc_reset, sp_type)
            for bname, c in (chain_bucket_spins.get(bkey) or {}).items():
                acc["bucket_spins"][bname] += int(c or 0)
            for bname, v in (chain_bucket_bet.get(bkey) or {}).items():
                acc["bucket_bet"][bname] += float(v or 0.0)
            for bname, v in (chain_bucket_win.get(bkey) or {}).items():
                acc["bucket_win"][bname] += float(v or 0.0)
        sub_streams_by_feature: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (feat_name, label), stats in _sub_stream_acc.items():
            fires = int(stats["fires"])
            win = float(stats["win"])
            rtp_pp = (win / effective_bet_for_rtp * 100.0) if effective_bet_for_rtp > 0 else 0.0
            sub_streams_by_feature[feat_name].append({
                "label": label,
                "fires": fires,
                "win_credits": win,
                "rtp_contribution_pp": rtp_pp,
                "bucket_spins": dict(stats["bucket_spins"]),
                "bucket_bet": dict(stats["bucket_bet"]),
                "bucket_win": dict(stats["bucket_win"]),
            })
        for rows in sub_streams_by_feature.values():
            rows.sort(key=lambda r: -r["win_credits"])

        # Build a reverse SpinType transition table once (inbound edge
        # counts) so the per-feature loop below can compute BOTH the
        # successor (``chain_parent_feature``, historical name — points
        # to "what comes after this feature in the round sequence") and
        # the predecessor (``chain_predecessor_feature`` — points to
        # "what fires this feature"). The historical ``chain_parent_*``
        # name is a misnomer: it stores the chain's successor, not its
        # parent. We keep it unchanged for backward-compat with front-
        # end / tests but add the correctly-named predecessor fields
        # alongside so operators see both ends of each chain edge.
        spin_type_prev_counts: dict[int, Counter] = defaultdict(Counter)
        for _st_from, _tos in spin_type_next_counts.items():
            for _st_to, _cnt in _tos.items():
                spin_type_prev_counts[int(_st_to)][int(_st_from)] += int(_cnt)

        upstream_feature_rows: list[dict[str, Any]] = []
        for feat_name, payouts in upstream_feature_tally.items():
            feat_total_win = sum(p.get("win", 0.0) for p in payouts.values())
            feat_total_times = sum(int(p.get("times", 0)) for p in payouts.values())
            # Keep full payout breakdown — UI filters what it shows but
            # the raw tally (including the -1 "no-pay" bucket for trigger
            # features) is useful for LLM interpretation and drill-down.
            payout_rows = []
            for pid, entry in sorted(
                payouts.items(),
                key=lambda kv: (-float(kv[1].get("win", 0.0)), kv[0]),
            ):
                payout_rows.append(
                    {
                        "payout_id": str(pid),
                        "win_credits": float(entry.get("win", 0.0)),
                        "times": int(entry.get("times", 0)),
                        "share_of_feature_win": (
                            float(entry.get("win", 0.0)) / feat_total_win
                            if feat_total_win > 0 else 0.0
                        ),
                    }
                )
            # Trigger-only detection: feature fires (times > 0) but
            # direct win credits are zero. These are ceremony/gate/
            # selection features that route to a paying parent. We
            # infer the parent via SpinType transition counts.
            trigger_only = feat_total_times > 0 and feat_total_win == 0.0
            # Chain-parent inference. Requires a resolved SpinType
            # mapping for this feature AND observed transitions.
            chain_parent_feature: str | None = None
            chain_parent_share: float = 0.0
            chain_parent_confidence: str = "none"
            chain_parent_next_fires: int = 0
            resolved_spin_type = feature_to_spin_type.get(feat_name)
            if resolved_spin_type is not None:
                transitions = spin_type_next_counts.get(resolved_spin_type) or Counter()
                total_edges = sum(transitions.values())
                if total_edges > 0:
                    # Most common next SpinType — that's the likely chain
                    # target (what comes after this feature in the round
                    # sequence). Skip self-loops (bonus retriggers) since
                    # they don't reveal the parent relationship.
                    ranked = sorted(
                        (
                            (int(st_to), int(cnt))
                            for st_to, cnt in transitions.items()
                            if int(st_to) != resolved_spin_type
                        ),
                        key=lambda kv: -kv[1],
                    )
                    if ranked:
                        best_st, best_cnt = ranked[0]
                        parent_feat = spin_type_to_feature.get(best_st)
                        if parent_feat:
                            chain_parent_feature = parent_feat
                            chain_parent_next_fires = best_cnt
                            chain_parent_share = best_cnt / total_edges
                            if chain_parent_share >= 0.80:
                                chain_parent_confidence = "high"
                            elif chain_parent_share >= 0.50:
                                chain_parent_confidence = "medium"
                            else:
                                chain_parent_confidence = "low"
# BCM fallback: "BuffCollectionMap" has no round-level
            # SpinType (it's a per-spin CollectCount cycle, not its own
            # round type). When SpinType inference can't bind it, use
            # the BCM pairing resolved from configs/bcm_pairings.json
            # (or the heuristic "biggest-win non-normal feature" fallback).
            if (
                str(feat_name) == "BuffCollectionMap"
                and chain_parent_feature is None
                and _bcm_bonus_feature
            ):
                chain_parent_feature = _bcm_bonus_feature
                chain_parent_confidence = (
                    "high" if _bcm_bonus_source == "config" else "medium"
                )
                # BCM cycles feed the bonus feature — treat every cycle
                # reset as 100% chaining into the paired feature.
                chain_parent_share = 1.0
                chain_parent_next_fires = feat_total_times

            # Chain-PREDECESSOR inference — the feature that fires this
            # one (semantically "parent"). Uses the reverse transition
            # table: which SpinTypes transition INTO this feature's
            # resolved_spin_type? The dominant predecessor is the paying
            # feature that triggers this one. Symmetric to the successor
            # (chain_parent) logic — same confidence thresholds, same
            # self-loop exclusion.
            chain_predecessor_feature: str | None = None
            chain_predecessor_share: float = 0.0
            chain_predecessor_confidence: str = "none"
            chain_predecessor_prev_fires: int = 0
            if resolved_spin_type is not None:
                pred_transitions = spin_type_prev_counts.get(resolved_spin_type) or Counter()
                pred_total_edges = sum(pred_transitions.values())
                if pred_total_edges > 0:
                    ranked_pred = sorted(
                        (
                            (int(st_from), int(cnt))
                            for st_from, cnt in pred_transitions.items()
                            if int(st_from) != resolved_spin_type
                        ),
                        key=lambda kv: -kv[1],
                    )
                    if ranked_pred:
                        best_pred_st, best_pred_cnt = ranked_pred[0]
                        pred_feat = spin_type_to_feature.get(best_pred_st)
                        if pred_feat:
                            chain_predecessor_feature = pred_feat
                            chain_predecessor_prev_fires = best_pred_cnt
                            chain_predecessor_share = best_pred_cnt / pred_total_edges
                            if chain_predecessor_share >= 0.80:
                                chain_predecessor_confidence = "high"
                            elif chain_predecessor_share >= 0.50:
                                chain_predecessor_confidence = "medium"
                            else:
                                chain_predecessor_confidence = "low"
            fire_rate = feat_total_times / total_spins if total_spins > 0 else 0.0
            # Per-feature multiplier bucket histogram. Same shape as the
            # global multiplier_profile.buckets so the UI can reuse the
            # bucket-bar renderer. Requires resolved SpinType (binds the
            # feature to round-level win data); session-level meta
            # features (no SpinType binding) get an empty list.
            #
            # ``total_bet`` passed below is the GLOBAL paid-bet
            # denominator (same as feat_total_win in the header). This
            # makes each bucket's ``rtp_contribution_pp`` a slice of the
            # global RTP — the per-feature bucket pp values sum to the
            # feature header's ``rtp_contribution_pp``. Using the
            # per-feature bet as the denominator (the other option) would
            # inflate bucket pp for bonus features (freespin rounds run
            # 3-4× RTP on their own bet denominator, which is confusing
            # vs the 41pp header).
            feat_bucket_rows: list[dict[str, Any]] = []
            feat_bucket_total_win = 0.0
            feat_bucket_total_spins = 0
            if resolved_spin_type is not None:
                st_b_spins = spin_type_bucket_spins.get(resolved_spin_type) or {}
                st_b_bet = spin_type_bucket_bet.get(resolved_spin_type) or {}
                st_b_win = spin_type_bucket_win.get(resolved_spin_type) or {}
                feat_bucket_total_spins = sum(st_b_spins.values())
                feat_bucket_total_win = sum(st_b_win.values())
                # Iter 6 (2026-04-23): if this feature is bound to a
                # zero-win settlement SpinType (Pass 5 — M15 TopDollar
                # → ST 15 is the canonical case), the round-level
                # ``spin_type_bucket_*`` maps are all zero (settlement
                # rounds carry WinCredits=None). Fall through to the
                # session-level histogram keyed by settlement ST which
                # is built from trigger_sessions' actual session_win.
                # This is what makes the TopDollar card render
                # a real bucket distribution instead of "无倍率分桶数据".
                if feat_bucket_total_win == 0.0 and feat_total_win > 0.0:
                    ss_spins = session_bucket_spins_by_settlement_st.get(resolved_spin_type) or {}
                    ss_bet = session_bucket_bet_by_settlement_st.get(resolved_spin_type) or {}
                    ss_win = session_bucket_win_by_settlement_st.get(resolved_spin_type) or {}
                    if sum(ss_win.values()) > 0:
                        st_b_spins = ss_spins
                        st_b_bet = ss_bet
                        st_b_win = ss_win
                        feat_bucket_total_spins = sum(ss_spins.values())
                        feat_bucket_total_win = sum(ss_win.values())
                feat_bucket_rows = build_multiplier_bucket_rows(
                    st_b_spins,
                    st_b_bet,
                    st_b_win,
                    feat_bucket_total_spins,
                    effective_bet_for_rtp,  # global denominator — see note above
                    feat_bucket_total_win,
                )
            # Fix 2 (2026-04-19 round 5): if ≥2 trigger paths exist for
            # this feature, emit one row PER PATH with a path-specific
            # bucket distribution. Naming convention: "{feat_name} [{label}]".
            # The frontend's feature-breakdown renders these as separate
            # cards automatically — no UI code change needed.
            feat_subs = sub_streams_by_feature.get(feat_name, [])
            # 2026-04-27 (Bug 3): tag features whose SpinType is dominated
            # by wild-nudge rounds (>=90% nudge). M279 ST=36 ("MoveSpin"
            # in upstream FeatureWin) is the wild-nudge mechanic, not an
            # independent BCM/freespin trigger. Surfacing
            # ``is_wild_nudge=True`` lets the UI render the row as nested
            # under the paid spin (instead of equal-level with Wheel /
            # NormalCollectionSpin) and lets downstream BCM heuristics
            # exclude it from candidate lists.
            is_wild_nudge_feature = False
            if resolved_spin_type is not None:
                _st_total_rounds = spin_type_spins.get(resolved_spin_type, 0)
                _st_nudge_rounds = spin_type_nudge_round_count.get(
                    resolved_spin_type, 0,
                )
                if _st_total_rounds > 0 and _st_nudge_rounds / _st_total_rounds >= 0.9:
                    is_wild_nudge_feature = True
            common = {
                "trigger_only": trigger_only,
                "is_wild_nudge": is_wild_nudge_feature,
                "resolved_spin_type": resolved_spin_type,
                "spin_type_binding_ambiguous": feat_name in ambiguous_mapped,
                # Historical "chain_parent_*" fields semantically store
                # the chain SUCCESSOR (what comes after this feature).
                # Kept under the old name for back-compat with front-end
                # + tests that read them to build inbound-chain
                # breadcrumbs. New predecessor fields added below.
                "chain_parent_feature": chain_parent_feature,
                "chain_parent_confidence": chain_parent_confidence,
                "chain_parent_share": chain_parent_share,
                "chain_parent_next_fires": chain_parent_next_fires,
                # Iter 4 (2026-04-23): correctly-named chain predecessor
                # (the feature whose SpinType most commonly transitions
                # INTO this one — i.e. who fires this feature). For a
                # typical trigger-only bonus feature, predecessor is
                # the paid feature (Normal) that hosts the trigger
                # round; for a paid feature with little inbound chain
                # traffic, predecessor is None.
                "chain_predecessor_feature": chain_predecessor_feature,
                "chain_predecessor_confidence": chain_predecessor_confidence,
                "chain_predecessor_share": chain_predecessor_share,
                "chain_predecessor_prev_fires": chain_predecessor_prev_fires,
            }
            # Only split PAYING features into per-path rows. Trigger-only
            # features (WheelSelector / PreWheel / etc.) have direct_win=0
            # on every path — splitting them produces N identical RTP=0
            # rows that clutter the breakdown without adding signal.
            if len(feat_subs) >= 2 and not trigger_only:
                # Aggregate bet from chain sub_streams (per-path) — use for
                # fire_rate calc when splitting.
                for sub in feat_subs:
                    p_win = float(sub.get("win_credits", 0.0))
                    p_fires = int(sub.get("fires", 0))
                    p_bucket_spins = sub.get("bucket_spins") or {}
                    p_bucket_bet = sub.get("bucket_bet") or {}
                    p_bucket_win = sub.get("bucket_win") or {}
                    p_total_spins = sum(p_bucket_spins.values())
                    p_total_win = sum(p_bucket_win.values())
                    p_bucket_rows = (
                        build_multiplier_bucket_rows(
                            p_bucket_spins, p_bucket_bet, p_bucket_win,
                            p_total_spins, effective_bet_for_rtp, p_total_win,
                        )
                        if p_total_spins > 0 else []
                    )
                    p_fire_rate = (p_fires / total_spins) if total_spins > 0 else 0.0
                    label = sub.get("label", "")
                    display_name = f"{feat_name} [{label}]"
                    upstream_feature_rows.append({
                        "feature_name": display_name,
                        "feature_base_name": str(feat_name),
                        "trigger_path_label": label,
                        "total_win": p_win,
                        "total_times": p_fires,
                        "fires_spins": p_fires,
                        "fire_rate": p_fire_rate,
                        "direct_win_credits": p_win,
                        "bucket_distribution": p_bucket_rows,
                        "bucket_total_spins": p_total_spins,
                        "sub_streams": [],  # split into separate rows, no nesting
                        "rtp_contribution_pp": (
                            (p_win / effective_bet_for_rtp) * 100.0
                            if effective_bet_for_rtp > 0 else 0.0
                        ),
                        "share_of_total_win": (
                            p_win / upstream_total_win
                            if upstream_total_win > 0 else 0.0
                        ),
                        # payout_rows is feature-aggregate (not path-specific);
                        # attach to first path for accessibility, keep empty
                        # for the rest.
                        "payouts": payout_rows if sub is feat_subs[0] else [],
                        **common,
                    })
                # Skip the aggregate row append below — continue outer loop.
                continue

            # Single-path (or no-path) case: emit the aggregate row as before.
            upstream_feature_rows.append(
                {
                    "feature_name": str(feat_name),
                    "total_win": feat_total_win,
                    "total_times": feat_total_times,
                    "fires_spins": feat_total_times,
                    "fire_rate": fire_rate,
                    "direct_win_credits": feat_total_win,
                    "bucket_distribution": feat_bucket_rows,
                    "bucket_total_spins": feat_bucket_total_spins,
                    "sub_streams": feat_subs,
                    "rtp_contribution_pp": (
                        (feat_total_win / effective_bet_for_rtp) * 100.0
                        if effective_bet_for_rtp > 0 else 0.0
                    ),
                    "share_of_total_win": (
                        feat_total_win / upstream_total_win
                        if upstream_total_win > 0 else 0.0
                    ),
                    "payouts": payout_rows,
                    **common,
                }
            )
        # Sort: payers first (by total_win desc), then trigger-only
        # features (by fires desc). Keeps the pay hierarchy readable
        # while still surfacing ceremony features after.
        upstream_feature_rows.sort(
            key=lambda row: (
                1 if row["trigger_only"] else 0,
                -float(row["total_win"]),
                -int(row["fires_spins"]),
            )
        )
        # Machines with a single "Normal" feature carry no bonus-mechanic
        # info in this block (it's a duplicate of payout_ids_top20 through a
        # different field). Flagging applicable=False lets the UI / LLM
        # suppress the section for those machines.
        has_multiple_features = len(upstream_feature_tally) > 1
        has_bonus_named_feature = any(
            name != "Normal" for name in upstream_feature_tally.keys()
        )
        upstream_feature_applicable = bool(
            upstream_feature_tally and (has_multiple_features or has_bonus_named_feature)
        )

        # ── Write player_impact.upstream_feature_breakdown (byte-identical) ──
        # The dict shape (applicable / source / features) + the constant
        # source string are preserved verbatim from the pre-carve PIA stash.
        player_impact = summary.setdefault("player_impact", {})
        player_impact["upstream_feature_breakdown"] = {
            "applicable": upstream_feature_applicable,
            "source": "analysisResult.FeatureWin",
            "features": upstream_feature_rows,
        }


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# ---------------------------------------------------------------------------
register(UpstreamFeatureBreakdown())
