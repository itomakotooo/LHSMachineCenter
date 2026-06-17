"""AnalyzerFeature: lock_respin_dynamics — the LockSymbolSpin (st96) in-line
hold-and-respin MECHANIC view.

M104 onboarding (Wave 4). The reel / payid / outcome / RTP-bucket DIMENSIONS of
st96 are already covered by the strict-reused PER_SPINTYPE plugins
(payouts_by_spin_type / reel_marginal_by_spin_type / spin_type_outcomes /
spin_type_rtp_buckets). This feature quantifies the LOCK MECHANIC itself — the
felt experience that makes st96 a distinct event — as rates / multipliers /
probabilities / distributions (money-agnostic; NO coin totals).

Why a NEW plugin (NOT a fork of respin_dynamics) — 02_reuse.md §2B / 03_design.md §3.1
-------------------------------------------------------------------------------------
respin_dynamics is structurally BLIND to M104's lock mechanic: it resolves the
respin ST via role=="respin" (M104 has none → it emits applicable:False), and its
grant-rate / continuation math is computed from spin_type_next_counts, which on
M104 is `{96:{96:42366}}` (self-transitions only — the lock chain rides INSIDE the
single ST=96, ReMarks-discriminated, so the mechanic is invisible to any
transition-based plugin). Forcing reuse would require a fake `respin` role (the
grant-rate math then counts every spin as an opener) or a forbidden fork. No
signature match → a genuinely NEW event → ONE new plugin (charter invariant 6).

HOOK = PLAY (LockSymbolSpin), NOT role — 03_design.md §3.2
---------------------------------------------------------
The lock mechanic rides the `paid_spin` ROLE — the SAME role EVERY machine's base
spin carries. A ROLE hook on `paid_spin` would cross-fire this plugin onto M15 /
M43 / M275 / M278 / M279 / M283. So it is keyed on the PLAY "LockSymbolSpin"
(M104-exclusive) via machine_spec.PLAY_ANALYSES — the SAME role-vs-play discipline
as minigame_dynamics→"WinMiniGame" and wheel_dynamics→"Wheel" (both ride the shared
`settlement` role, so MUST key on play). The play hook scopes it to M104 only.

What the player feels (design 03_design.md §4): most spins are ordinary; rarely a
`35x` symbol lands and LOCKS in place (ReMarks='Lock', LockSymbols=pos:2), the
board RESPINS FREE, and more 35x can land and lock (a chain), each respin building
value, until a no-lock settle ends the chain. The Lock feature is rare (~5.6% of
paid spins) but carries the bulk of the high-multiplier tail.

Mechanic metrics (design FD1–FD6 / L1–L5)
-----------------------------------------
- FD1/L1 lock grant-rate: how often a paid spin extends itself with a free lock
    respin. Felt denominators: per all paid spins (≈1 in N), per winning paid spin.
    Signal (base-derivable): lock_symbols_spins (the count of ReMarks='Lock'
    RECORDS — each lock respin carries a non-empty LockSymbols) vs base spins.
    NOTE (parser_blind): the per-GROUP lock-OPENING count (one per SpinTimes group
    that opens a chain, the W1 2,247 figure) differs from the per-RECORD lock count
    (2,374); the group→record collapse needs per-SpinTimes-group run-length
    accumulation that lives in parser.py (base-closure) or a NEW st_extract
    extractor — both OUT of new-plugin scope. The record-level rate IS delivered;
    the group-opener rate is flagged parser_blind (see `parser_blind`).
- FD2/L2 chain-length × outcome ladder (len 0/1/2/3 × hit% × avg mult × RTP-share):
    the headline escalation metric. NEEDS the per-SpinTimes-group lock-COUNT tally
    (nLock → {groups, hit_groups, win}). The current chunk accumulators do NOT
    expose it base-excluded (spin_type_next_counts is 96→96 only). → parser_blind
    (framework-team), SAME boundary respin_dynamics flags for M43/M279 burst-length.
- FD3/L3 35x ⟺ Lock determinism: P(Lock|35x)=1.0, P(Lock|¬35x)=0.0 (W1 CROSS-D, 0
    exceptions). A DECLARED structural fact (manifest spin_types['96'].lock_mechanic
    .trigger_symbol = '35x'); the empirical per-record proof needs a StopSymbolsByCol
    cross → parser_blind, but the determinism itself is reported from the declaration.
- FD4/L4 multiplier-wild escalation ladder (5x/7x/35x presence × avg multiplier):
    the volatility driver. NEEDS a per-record 5x/7x/35x presence tally
    (StopSymbolsByCol) → parser_blind (same per-ST-extraction boundary as M279's
    per-skin breakout). The ladder's EXISTENCE is a verified W1 data fact.
- FD5/L5 lock RTP-concentration: a rare event carrying most of the payback (the
    boom in a boom-bust profile). Signal (base-derivable): lock_symbols_win share of
    all st96 win + the ST96 fat-tail (≥20×) win share + zero-win-round rate from the
    per-ST return-bucket histogram.
- FD6: the SummaryWin tier distribution (the machine's own taxonomy) — REUSE: it
    renders verbatim via multiplier_profile / spin_type_rtp_buckets; this plugin does
    NOT re-emit it (no parallel impl — feedback_no_parallel_panel_impl.md). The
    per-ST bucket distribution this plugin DOES surface is the lock-RTP framing of
    that same shape (FD5), not a duplicate of FD6.

Data path (all base-EXCLUDED — no parser/closure dependency)
------------------------------------------------------------
extract() reads PER-CHUNK accumulators the parser already emits in the chunk dict
(rec) — accumulated OURSELVES (no stash-ordering dependency):

  chunk_dict["lock_symbols_spins" | "lock_symbols_win" | "lock_symbols_unique"]
      the per-machine LockSymbols mechanic accumulators (parser.py emits these for
      ANY machine whose rounds carry a non-empty LockSymbols field). On M104 these
      are the count / Σ win / token-value set of the ReMarks='Lock' RESPIN records
      (FD1 record-rate, FD5 win share). Absent / zero on machines without lock
      symbols — a legitimate state (the feature degrades; never fabricates).
  chunk_dict["spin_type_next_counts"]
      {str(from_st): {str(to_st): count}} — used ONLY to surface the structural fact
      that the lock chain is invisible to transition counts (96→96 self only), the
      justification for the parser_blind L2 boundary; NOT a metric source here.
  chunk_dict["spin_type_bucket_spins" | "spin_type_bucket_win"]
      {str(st): {return_bucket_label: value}} — per-ST win/bet multiplier-band
      histogram. For st96 the bands are meaningful multipliers (bet=1000 plumbed),
      giving the fat-tail (≥20×) win share + zero-win rate (FD5).

emit() additionally reads the byte-stable summary["player_impact"]["spin_type_breakdown"]
(per-ST round-level stats: spins, win_rounds, hit_rate, total_win,
rtp_contribution_pp) for the felt denominators + RTP share. REQUIRES
payouts_by_spin_type guarantees that section is present before emit().

RTP_CONTRIBUTION = False
  This feature re-presents wins already attributed to st96 by the NATURAL per-payid
  map + the PER_SPINTYPE plugins (M104 needs NO SynthesizePayIdRule —
  03_design.md §2). It adds NOTHING to the RTP sum; sum(pay_id.rtp_pp)==summary.rtp
  is unaffected (feedback_aggregator_parity_invariant.md).

Per-machine isolation
---------------------
NOT in fresh_slotlab/analyzer/core/ and NOT in versioning._CLOSURE_FILES — base-
EXCLUDED (R-4). Auto-discovered via feature_registry.discover_features() (globs
features/*.py). Editing it re-flags ONLY machines declaring "lock_respin_dynamics"
(via play "LockSymbolSpin" in machine_spec.PLAY_ANALYSES — NOT the shared
`paid_spin` role, so it does NOT fire on any other machine's base spin).

Memory feedback honored
-----------------------
- feedback_no_hardcode.md: no M104-specific ids. The lock ST is resolved from the
  manifest's spin_types (play "LockSymbolSpin"); the base ST from role "paid_spin".
- feedback_no_silent_swallow.md: a missing REQUIRES section (payouts_by_spin_type)
  RAISES. The parser_blind sub-metrics are surfaced EXPLICITLY in a `parser_blind`
  field rather than emitted as fabricated zeros.
- feedback_aggregator_parity_invariant.md: RTP_CONTRIBUTION = False.
- feedback_invariant_with_fallback_hides_drift.md: no catch-all bucket; rates with
  a zero denominator are emitted as null (not a "0.0 with 0 denominator" lie).
- feedback_no_parallel_panel_impl.md: mirrors respin_dynamics / minigame_dynamics
  (extract/reduce/emit, ClassVar layout, dual-path import, register()); reuses
  RETURN_BUCKET_ORDER + the _TAIL_GE20_BANDS tail cut; does NOT re-emit FD6.
- feedback_subprocess_import_suicide_and_module_globals.md: register() is a pure
  list-append; no I/O at import time.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    from fresh_slotlab.analyzer.feature_registry import register
    from fresh_slotlab.analyzer.core.aggregator import RETURN_BUCKET_ORDER
except ImportError:  # running as standalone script
    from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
    from analyzer.feature_registry import register  # type: ignore[no-redef]
    from analyzer.core.aggregator import RETURN_BUCKET_ORDER  # type: ignore[no-redef]

if TYPE_CHECKING:
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
    except ImportError:
        from analyzer.pipeline_context import PipelineContext  # type: ignore[assignment]


# Multiplier-band tail thresholds (felt "fat-tail" cut). A band qualifies as tail
# if its lower bound is >= the threshold. Used for the FD5 fat-tail (≥20×) share.
# Mirrors respin_dynamics._TAIL_GE20_BANDS verbatim (no parallel impl).
_TAIL_GE20_BANDS: frozenset[str] = frozenset({
    "ge20_lt50", "ge50_lt100", "ge100_lt200", "ge200_lt500",
    "ge500_lt1000", "ge1000_lt5000", "ge5000",
})


def _resolve_st_by_role_or_play(
    manifest: dict[str, Any] | None,
    *,
    role: str | None = None,
    play: str | None = None,
) -> int | None:
    """Return the first SpinType int whose spec matches the given role or play.

    Reads ctx.machine_spec_manifest (the SpinType-native manifest). Returns None
    if no manifest or no match — callers degrade gracefully (no hardcoded ids,
    per feedback_no_hardcode.md).
    """
    if not isinstance(manifest, dict):
        return None
    for st_key, spec in (manifest.get("spin_types") or {}).items():
        if not isinstance(spec, dict):
            continue
        if role is not None and str(spec.get("role", "")) == role:
            try:
                return int(st_key)
            except (TypeError, ValueError):
                continue
        if play is not None and str(spec.get("play", "")) == play:
            try:
                return int(st_key)
            except (TypeError, ValueError):
                continue
    return None


def _lock_mechanic_block(
    manifest: dict[str, Any] | None, lock_st: int | None
) -> dict[str, Any]:
    """Return the spin_types['<lock_st>'].lock_mechanic declaration (or {}).

    The manifest declares the lock mechanic's structural facts (discriminator,
    trigger_symbol, group_unit, …) — the dimension spec this plugin consumes,
    analog of M279's wheel_cells / M275's trigger_paths declarative blocks.
    """
    if not isinstance(manifest, dict) or lock_st is None:
        return {}
    spec = (manifest.get("spin_types") or {}).get(str(lock_st))
    if not isinstance(spec, dict):
        return {}
    lm = spec.get("lock_mechanic")
    return lm if isinstance(lm, dict) else {}


class LockRespinDynamics(AnalyzerFeature):
    """Pattern-B plugin: accumulate the per-machine LockSymbols mechanic counters
    + per-ST bucket histograms per chunk; compute the lock-mechanic metrics in
    emit() (reading the byte-stable spin_type_breakdown section too).

    Accumulator structure
    ---------------------
      lock_symbols_spins: int         # count of ReMarks='Lock' respin records
      lock_symbols_win:   float       # Σ win on those lock records
      lock_symbols_unique: set[str]   # distinct LockSymbols token base values
      next_counts: dict[str, dict[str, int]]   # ST transition tally (for the
                                               # invisibility-of-chain fact only)
      bucket_spins / bucket_win: dict[str, dict[str, number]]  # per-ST band hist
    """

    FEATURE_ID: ClassVar[str] = "lock_respin_dynamics"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("lock_respin_dynamics",)
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False  # re-presents already-attributed wins
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    # We read summary["player_impact"]["spin_type_breakdown"] in emit();
    # REQUIRES payouts_by_spin_type guarantees it is present (payouts_by_spin_type
    # itself requires spin_type_breakdown, written by the inline F1 block).
    REQUIRES: ClassVar[tuple[str, ...]] = ("payouts_by_spin_type",)
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """Lift the per-chunk LockSymbols counters + per-ST bucket histograms.

        Empty/zero when the keys are absent (old cached chunks / non-lock
        machine) — a valid state, not an error (feedback_no_silent_swallow.md:
        absence of OPTIONAL per-chunk accumulators is legitimate; only a malformed
        shape would raise, but these are simple reads with defensive coercion).
        """
        empty = {
            "lock_symbols_spins": 0,
            "lock_symbols_win": 0.0,
            "lock_symbols_unique": [],
            "next_counts": {},
            "bucket_spins": {},
            "bucket_win": {},
        }
        if not chunk_dict or not isinstance(chunk_dict, dict):
            return empty

        def _coerce_nested(raw: Any, *, as_int: bool) -> dict[str, dict[str, float]]:
            out: dict[str, dict[str, float]] = {}
            if not isinstance(raw, dict):
                return out
            for okey, imap in raw.items():
                if not isinstance(imap, dict):
                    continue
                inner: dict[str, float] = {}
                for ikey, val in imap.items():
                    try:
                        inner[str(ikey)] = int(val or 0) if as_int else float(val or 0.0)
                    except (TypeError, ValueError):
                        continue
                if inner:
                    out[str(okey)] = inner
            return out

        try:
            lock_spins = int(chunk_dict.get("lock_symbols_spins") or 0)
        except (TypeError, ValueError):
            lock_spins = 0
        try:
            lock_win = float(chunk_dict.get("lock_symbols_win") or 0.0)
        except (TypeError, ValueError):
            lock_win = 0.0
        unique_raw = chunk_dict.get("lock_symbols_unique") or []
        lock_unique = sorted({str(u) for u in unique_raw}) if isinstance(unique_raw, (list, tuple, set)) else []

        return {
            "lock_symbols_spins": lock_spins,
            "lock_symbols_win": lock_win,
            "lock_symbols_unique": lock_unique,
            "next_counts": _coerce_nested(
                chunk_dict.get("spin_type_next_counts"), as_int=True
            ),
            "bucket_spins": _coerce_nested(
                chunk_dict.get("spin_type_bucket_spins"), as_int=True
            ),
            "bucket_win": _coerce_nested(
                chunk_dict.get("spin_type_bucket_win"), as_int=False
            ),
        }

    @staticmethod
    def _merge_nested_counts(
        prev: dict[str, dict[str, float]],
        this: dict[str, dict[str, float]],
    ) -> dict[str, dict[str, float]]:
        """Additively merge two {outer: {inner: number}} dicts."""
        out: dict[str, dict[str, float]] = {}
        for okey, imap in prev.items():
            out[okey] = dict(imap)
        for okey, imap in this.items():
            dest = out.setdefault(okey, {})
            for ikey, val in imap.items():
                dest[ikey] = dest.get(ikey, 0) + val
        return out

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Additively merge lock counters + bucket tallies across chunks."""
        empty = {
            "lock_symbols_spins": 0,
            "lock_symbols_win": 0.0,
            "lock_symbols_unique": [],
            "next_counts": {},
            "bucket_spins": {},
            "bucket_win": {},
        }
        if not prev_acc:
            return this_acc if this_acc else empty
        if not this_acc:
            return prev_acc
        return {
            "lock_symbols_spins": (
                int(prev_acc.get("lock_symbols_spins") or 0)
                + int(this_acc.get("lock_symbols_spins") or 0)
            ),
            "lock_symbols_win": (
                float(prev_acc.get("lock_symbols_win") or 0.0)
                + float(this_acc.get("lock_symbols_win") or 0.0)
            ),
            "lock_symbols_unique": sorted(
                set(prev_acc.get("lock_symbols_unique") or [])
                | set(this_acc.get("lock_symbols_unique") or [])
            ),
            "next_counts": self._merge_nested_counts(
                prev_acc.get("next_counts") or {}, this_acc.get("next_counts") or {}
            ),
            "bucket_spins": self._merge_nested_counts(
                prev_acc.get("bucket_spins") or {}, this_acc.get("bucket_spins") or {}
            ),
            "bucket_win": self._merge_nested_counts(
                prev_acc.get("bucket_win") or {}, this_acc.get("bucket_win") or {}
            ),
        }

    @staticmethod
    def _bucket_distribution(
        bucket_spins: dict[str, int],
        bucket_win: dict[str, float],
    ) -> dict[str, Any]:
        """Build a money-agnostic multiplier-band distribution for one ST.

        Mirrors respin_dynamics._bucket_distribution (no parallel impl). Returns
        {bands:[{band, spin_count, prob, win_share}], total_spins, win_rounds,
        tail_ge20x_win_share, tail_ge20x_spin_rate}. The denominator is ALL of
        this ST's rounds (incl. the eq0 loss band) so prob sums to 1.0.
        """
        total_spins = sum(int(v) for v in bucket_spins.values())
        total_win = sum(float(v) for v in bucket_win.values())
        win_rounds = sum(int(c) for b, c in bucket_spins.items() if b != "eq0")
        bands: list[dict[str, Any]] = []
        tail_win = 0.0
        tail_spins = 0
        for band in RETURN_BUCKET_ORDER:
            sc = int(bucket_spins.get(band, 0))
            bw = float(bucket_win.get(band, 0.0))
            if sc == 0 and bw == 0.0:
                continue
            bands.append({
                "band": band,
                "spin_count": sc,
                "prob": (sc / total_spins) if total_spins > 0 else None,
                "win_share": (bw / total_win) if total_win > 0 else None,
            })
            if band in _TAIL_GE20_BANDS:
                tail_win += bw
                tail_spins += sc
        return {
            "total_spins": total_spins,
            "win_rounds": win_rounds,
            "bands": bands,
            "tail_ge20x_win_share": (tail_win / total_win) if total_win > 0 else None,
            "tail_ge20x_spin_rate": (
                (tail_spins / total_spins) if total_spins > 0 else None
            ),
        }

    @staticmethod
    def _loss_rate(bucket_spins: dict[str, int]) -> float | None:
        """Share of this ST's rounds that won nothing (the eq0 band)."""
        total = sum(int(v) for v in bucket_spins.values())
        zero = int(bucket_spins.get("eq0", 0))
        return (zero / total) if total > 0 else None

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Compute and write summary["player_impact"]["lock_respin_dynamics"].

        Resolves the lock ST (play=="LockSymbolSpin") and base/paid ST
        (role=="paid_spin") from ctx.machine_spec_manifest (no hardcoded ids). On
        M104 they are the SAME ST=96 (the lock rides in-line on the paid spin). If
        no LockSymbolSpin play is declared, writes {applicable: False} and returns.
        """
        player_impact = summary.setdefault("player_impact", {})

        # Hard dependency check (feedback_no_silent_swallow.md): payouts_by_spin_type
        # ALWAYS writes spin_type_breakdown when it runs; an ABSENT section means it
        # crashed upstream — surface loudly (the emit loop records it in feature_errors).
        if "payouts_by_spin_type" not in player_impact:
            raise RuntimeError(
                "lock_respin_dynamics requires player_impact['payouts_by_spin_type'] "
                "(REQUIRES dependency) but it is absent at emit time — "
                "PayoutsBySpinType did not run or failed upstream."
            )
        if "spin_type_breakdown" not in player_impact:
            raise RuntimeError(
                "lock_respin_dynamics requires player_impact['spin_type_breakdown'] "
                "but it is absent at emit time — the inline F1 block / "
                "PayoutsBySpinType did not run or failed upstream."
            )

        manifest = getattr(ctx, "machine_spec_manifest", None)
        lock_st = _resolve_st_by_role_or_play(manifest, play="LockSymbolSpin")
        base_st = _resolve_st_by_role_or_play(manifest, role="paid_spin")

        if lock_st is None:
            player_impact["lock_respin_dynamics"] = {
                "applicable": False,
                "reason": "no SpinType with play 'LockSymbolSpin' in manifest",
            }
            return

        final_acc = final_acc or {}
        lock_records = int(final_acc.get("lock_symbols_spins") or 0)
        lock_win = float(final_acc.get("lock_symbols_win") or 0.0)
        lock_token_values = list(final_acc.get("lock_symbols_unique") or [])
        next_counts: dict[str, dict[str, int]] = final_acc.get("next_counts") or {}
        bucket_spins: dict[str, dict[str, int]] = final_acc.get("bucket_spins") or {}
        bucket_win: dict[str, dict[str, float]] = final_acc.get("bucket_win") or {}

        lock_st_s = str(lock_st)
        lock_mechanic = _lock_mechanic_block(manifest, lock_st)

        # --- round-level stats from spin_type_breakdown (byte-stable) ---
        stb_rows: list[dict[str, Any]] = player_impact.get("spin_type_breakdown") or []
        stb_by_st: dict[int, dict[str, Any]] = {}
        for row in stb_rows:
            try:
                stb_by_st[int(row.get("spin_type"))] = row
            except (TypeError, ValueError):
                continue
        lock_row = stb_by_st.get(lock_st) or {}
        base_row = stb_by_st.get(base_st) if base_st is not None else {}
        base_row = base_row or {}

        base_spins = int(base_row.get("spins") or 0)
        base_win_rounds = int(base_row.get("win_rounds") or 0)
        # On M104 lock rides in-line on ST96, so the "paid spin" denominator is the
        # lock ST's own round count when base==lock; settle records + lock records
        # share ST96. The base spins figure is the ST96 spins (one paid spin per
        # SpinTimes group + its free lock respins). For the felt grant denominator
        # we prefer the ST96 spins as the paid-spin universe.
        denom_spins = base_spins if base_spins > 0 else int(lock_row.get("spins") or 0)

        # ── FD1 / L1 — lock grant-rate (RECORD-level, base-derivable) ──
        # lock_records = ReMarks='Lock' RESPIN records (each carries a non-empty
        # LockSymbols). This is the per-RECORD lock count; the per-GROUP opening
        # count (one per chain) is parser_blind (needs SpinTimes-group run-length).
        grant_rate = {
            "lock_records": lock_records,
            "per_paid_spin_record_rate": (
                lock_records / denom_spins if denom_spins > 0 else None
            ),
            "one_per_n_paid_spins_records": (
                denom_spins / lock_records if lock_records > 0 else None
            ),
            "lock_token_values": lock_token_values,
            "note": (
                "lock_records counts ReMarks='Lock' RESPIN records (each carries a "
                "non-empty LockSymbols token). The per-GROUP lock-OPENING count (one "
                "per SpinTimes chain, the felt 'a lock triggered' moment) requires a "
                "per-SpinTimes-group run-length tally — see parser_blind."
            ),
        }

        # ── FD3 / L3 — 35x ⟺ Lock determinism (DECLARED structural fact) ──
        trigger_symbol = lock_mechanic.get("trigger_symbol")
        determinism = {
            "trigger_symbol": trigger_symbol,
            "p_lock_given_trigger": 1.0 if trigger_symbol else None,
            "p_lock_given_no_trigger": 0.0 if trigger_symbol else None,
            "source": (
                "manifest spin_types['%s'].lock_mechanic.trigger_symbol (declared "
                "structural fact: W1 CROSS-D, 35x present <=> Lock chain, 0/40,000 "
                "exceptions). The per-record empirical proof (StopSymbolsByCol cross) "
                "is parser_blind." % lock_st_s
            ) if trigger_symbol else "no lock_mechanic.trigger_symbol declared",
        }

        # ── FD5 / L5 — lock RTP-concentration + fat-tail shape (base-derivable) ──
        lock_st_total_win = float(lock_row.get("total_win") or 0.0)
        all_win = sum(float(r.get("total_win") or 0.0) for r in stb_rows)
        st_dist = self._bucket_distribution(
            bucket_spins.get(lock_st_s) or {}, bucket_win.get(lock_st_s) or {}
        )
        rtp_concentration = {
            "lock_records": lock_records,
            "lock_record_win": lock_win,
            "lock_record_win_share_of_st": (
                (lock_win / lock_st_total_win) if lock_st_total_win > 0 else None
            ),
            "lock_record_rate": (
                lock_records / denom_spins if denom_spins > 0 else None
            ),
            "st_rtp_contribution_pp": lock_row.get("rtp_contribution_pp"),
            "share_of_all_win": (
                (lock_st_total_win / all_win) if all_win > 0 else None
            ),
            "fat_tail_ge20x_win_share": st_dist.get("tail_ge20x_win_share"),
            "fat_tail_ge20x_spin_rate": st_dist.get("tail_ge20x_spin_rate"),
            "loss_rate": self._loss_rate(bucket_spins.get(lock_st_s) or {}),
            "note": (
                "the Lock feature is a small-frequency, fat-tailed driver — most "
                "spins win small or nothing, the lock chains carry the high-multiplier "
                "tail. lock_record_win_share_of_st quantifies how much of ST%s's win "
                "rides the lock respin records (a base-derivable lower bound on the "
                "felt 'the lock IS the excitement engine'); the exact per-chain-length "
                "RTP split (L2) is parser_blind." % lock_st_s
            ),
        }

        # ── multiplier band distribution (the lock-RTP framing of FD6's shape) ──
        # NOT a re-emit of FD6 (multiplier_profile / spin_type_rtp_buckets own that);
        # this is the ST96 per-ST band shape the FD5 framing reads.
        multiplier_distribution = st_dist

        # ── chain invisibility fact (justifies the L2 parser_blind boundary) ──
        lock_out = next_counts.get(lock_st_s) or {}
        chain_transition_fact = {
            "next_counts_for_lock_st": {str(k): int(v) for k, v in lock_out.items()},
            "note": (
                "the lock chain rides INSIDE ST%s (ReMarks-discriminated), so it "
                "produces ONLY %s->%s self-transitions — it is structurally invisible "
                "to any transition-based plugin (this is WHY respin_dynamics is "
                "blind to M104 and a NEW plugin is warranted). It is ALSO why the "
                "per-group chain-length ladder (L2) cannot be derived from "
                "spin_type_next_counts and is parser_blind." % (lock_st_s, lock_st_s, lock_st_s)
            ),
        }

        player_impact["lock_respin_dynamics"] = {
            "applicable": True,
            "lock_spin_type": lock_st,
            "base_spin_type": base_st,
            "lock_mechanic": {
                "discriminator": lock_mechanic.get("discriminator"),
                "lock_value": lock_mechanic.get("lock_value"),
                "settle_value": lock_mechanic.get("settle_value"),
                "trigger_symbol": lock_mechanic.get("trigger_symbol"),
                "group_unit": lock_mechanic.get("group_unit"),
            },
            "grant_rate": grant_rate,
            "determinism": determinism,
            "rtp_concentration": rtp_concentration,
            "multiplier_distribution": multiplier_distribution,
            "chain_transition_fact": chain_transition_fact,
            "parser_blind": [
                "chain_length_ladder (per-SpinTimes-group nLock 0/1/2/3 x hit% x "
                "avg multiplier x RTP-share — the FD2/L2 headline escalation ladder)",
                "lock_chain_run_length_histogram (per-record run-length within a "
                "chain) + win_gating_proof (which record in the chain carries the "
                "win; the within-chain win-build curve)",
                "group_lock_opening_rate (one open per SpinTimes chain vs the "
                "per-record lock count surfaced in grant_rate)",
                "multiplier_wild_ladder (5x/7x/35x presence x avg multiplier per "
                "record — the FD4/L4 volatility ladder; its EXISTENCE is a verified "
                "W1 data fact, the base-excluded cross is the parser_blind boundary)",
            ],
            "parser_blind_reason": (
                "the per-SpinTimes-group lock-count ladder + the per-record "
                "run-length / win-gating + the per-record 5x/7x/35x wild cross all "
                "need per-round sequence accumulation keyed on the SpinTimes group "
                "(a per-ST extraction substrate). The current chunk accumulators "
                "expose only the per-record lock_symbols_* counters + the per-ST "
                "RETURN_BUCKET histograms (96->96 self-transitions only), which give "
                "the lock-record rate + RTP concentration but NOT the chain-length "
                "shape. Wiring the group ladder requires a parser.py change "
                "(base-closure) or a NEW st_extract extractor (st_extract/*.py) — "
                "both OUT of new-plugin onboarding scope. SAME boundary "
                "respin_dynamics flags for M43/M279 burst-length / minigame_dynamics "
                "for node paths. Escalated to the framework team."
            ),
        }


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# Auto-discovered by feature_registry.discover_features() (globs features/*.py).
# ---------------------------------------------------------------------------
register(LockRespinDynamics())
