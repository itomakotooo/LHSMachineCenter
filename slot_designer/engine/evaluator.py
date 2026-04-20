"""Payline evaluator: 3 symbols on the payline → PayResult | None.

Implements the M1 precedence/substitution logic reverse-engineered from
rawdata (see slot_designer/tests/fixtures/M1_field_analysis.md):

  1. Cherry precedence — any cherry on payline triggers cherry_count pay,
     wilds are inert.
  2. Blank short-circuit — any blank/filler on non-cherry path → no pay.
  3. Pure-wild (all 3 wild) — exact multiset match against pure_wild or
     pure_wild_group rules. rtp_excluded rules return None (e.g. grand
     jackpot: spec declares it's never paid through normal spins).
  4. Regular pays with wild substitution + multiplicative wild multiplier
     stacking. Engine picks max final multiplier across candidate rules
     (line_3_same typically beats line_3_group when both match).
"""
from __future__ import annotations

from collections import Counter
from typing import Sequence

from .rules import PayResult, RuleSet
from .symbol import SymbolRegistry


class PaytableEvaluator:
    def __init__(
        self,
        symbols: SymbolRegistry,
        rules: RuleSet,
        evaluation_order: Sequence[str],
    ):
        self.symbols = symbols
        self.rules = rules
        self.order = tuple(evaluation_order)

    def evaluate_payline(self, payline_symbols: list[str]) -> PayResult | None:
        """Evaluate one payline. payline_symbols are in col order (M1: 3 syms).

        Positions returned are (col, row=1) for each col of the payline
        (middle row). Cherry pay positions only include cells with cherry.
        """
        all_positions = tuple((c, 1) for c in range(len(payline_symbols)))

        # --- Stage 1: cherry precedence ---
        if "cherry_count" in self.order:
            cherry_positions = tuple(
                (c, 1) for c, s in enumerate(payline_symbols)
                if self.symbols.get(s).is_cherry
            )
            if cherry_positions:
                rule = self.rules.cherry_by_count.get(len(cherry_positions))
                if rule is None:
                    # Cherry present but no rule for this count (shouldn't happen
                    # for M1; 1/2/3 all defined). No pay.
                    return None
                return PayResult(
                    pay_id=rule.pay_id,
                    multiplier=rule.multiplier,
                    positions=cherry_positions,
                )

        # --- Stage 2: blank kills non-cherry path ---
        if any(self.symbols.get(s).is_filler for s in payline_symbols):
            return None

        wilds = [s for s in payline_symbols if self.symbols.get(s).is_wild]
        non_wilds = [s for s in payline_symbols if not self.symbols.get(s).is_wild]

        # --- Stage 3: pure-wild (all 3 are wild) ---
        if not non_wilds:
            mset = Counter(payline_symbols)

            if "pure_wild" in self.order:
                for rule in self.rules.pure_wild:
                    if Counter(rule.multiset) == mset:
                        if rule.rtp_excluded:
                            return None  # e.g. grand jackpot: blocked from normal spins
                        return PayResult(
                            pay_id=rule.pay_id,
                            multiplier=rule.multiplier,
                            positions=all_positions,
                        )

            if "pure_wild_group" in self.order:
                for rule in self.rules.pure_wild_group:
                    for alt in rule.alternatives:
                        if Counter(alt["multiset"]) == mset:
                            if rule.rtp_excluded:
                                return None
                            return PayResult(
                                pay_id=rule.pay_id,
                                multiplier=alt["multiplier"],
                                positions=all_positions,
                            )
            return None  # all-wild but no rule matches

        # --- Stages 4-5: wild-substituted regular pays ---
        wild_product = 1
        for w in wilds:
            wild_product *= self.symbols.get(w).multiplier

        candidates: list[tuple[int, int]] = []  # (pay_id, final_multiplier)

        # line_3_same: all non-wilds are the same symbol → wilds substitute for it
        if "line_3_same" in self.order and len(set(non_wilds)) == 1:
            sym = non_wilds[0]
            rule = self.rules.line_3_same_by_symbol.get(sym)
            if rule is not None:
                candidates.append((rule.pay_id, rule.multiplier * wild_product))

        # line_3_group: all non-wilds live in a common group (e.g. all Bars)
        if "line_3_group" in self.order:
            for rule in self.rules.line_3_group:
                if all(s in rule.group for s in non_wilds):
                    candidates.append((rule.pay_id, rule.multiplier * wild_product))

        if not candidates:
            return None

        best_pid, best_mult = max(candidates, key=lambda t: t[1])
        return PayResult(
            pay_id=best_pid,
            multiplier=best_mult,
            positions=all_positions,
        )
