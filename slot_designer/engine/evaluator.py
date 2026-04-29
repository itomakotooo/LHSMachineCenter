"""Payline evaluator: N symbols on the payline → PayResult | None.

Implements the M1 / M15 / M37 precedence/substitution logic
reverse-engineered from production rawdata. See:
  - tests/fixtures/M1_field_analysis.md (M1)
  - specs/M15.spec.json _notes (M15)
  - tests/fixtures/M37_field_analysis.md (M37)

Stages (each conditional on presence in ``evaluation_order``):

  1. Cherry precedence (M1) — any cherry → cherry_count pay; wilds inert.
  2. Booster-center (M37) — col 1 is booster → short-circuit: check
     side cells for a 3-match anchor (wild-subbed), apply booster mult;
     fallback to pure-wild-with-booster or booster-alone pay.
  3. Blank short-circuit — any blank/filler on non-cherry, non-booster
     path AND no side-wild-alone rule declared → no pay.
  4. Pure-wild (all 3 wild) — exact multiset match against pure_wild
     or pure_wild_group rules. rtp_excluded → None.
  5. Wild-substituted 3-match (line_3_same + line_3_group) — max final
     multiplier across matching rules.
  6. Side-wild-alone (M37) — col 0 or col 2 is wild, col 1 is blank,
     no 3-match → flat 1× pay (M37 pay_id 9).
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
        """Evaluate one payline. payline_symbols are in col order.

        Positions returned are (col, row=1) for each col of the payline
        (middle row). Cherry pay positions only include cells with cherry.
        """
        all_positions = tuple((c, 1) for c in range(len(payline_symbols)))

        # --- Stage 1: cherry precedence (M1) ---
        if "cherry_count" in self.order:
            cherry_positions = tuple(
                (c, 1) for c, s in enumerate(payline_symbols)
                if self.symbols.get(s).is_cherry
            )
            if cherry_positions:
                rule = self.rules.cherry_by_count.get(len(cherry_positions))
                if rule is None:
                    return None
                return PayResult(
                    pay_id=rule.pay_id,
                    multiplier=rule.multiplier,
                    positions=cherry_positions,
                )

        # --- Stage 2: booster-center short-circuit (M37) ---
        # When col 1 holds a booster (mini/minor/major/grand), standard
        # 3-match logic doesn't apply (booster isn't in any group, not
        # same as any regular symbol). Instead:
        #   (a) check if col 0 + col 2 form a 3-match anchor when booster
        #       is treated as the 3rd cell (wild-subbed); apply booster×
        #   (b) (wild, booster, wild): pure_wild_with_booster rule
        #   (c) otherwise: center_booster_alone rule (pay_id 8/9)
        if len(payline_symbols) == 3 and self.symbols.get(payline_symbols[1]).is_booster:
            return self._evaluate_booster_center(payline_symbols, all_positions)

        # --- Stage 3: blank kills non-cherry / non-booster path ---
        # On M37, "wild on side + blank center" is handled by Stage 6
        # (side_wild_alone); blank-kill skipped when that rule exists.
        if any(self.symbols.get(s).is_filler for s in payline_symbols):
            if "side_wild_alone" in self.order and self.rules.side_wild_alone is not None:
                # Fall through to Stage 6; only return None if no wild
                # on sides (Stage 6 will handle that cleanly).
                pass
            else:
                return None

        wilds = [s for s in payline_symbols if self.symbols.get(s).is_wild]
        non_wilds = [s for s in payline_symbols if not self.symbols.get(s).is_wild]

        # --- Stage 4: pure-wild (all 3 are wild) ---
        if not non_wilds:
            mset = Counter(payline_symbols)

            if "pure_wild" in self.order:
                for rule in self.rules.pure_wild:
                    if Counter(rule.multiset) == mset:
                        if rule.rtp_excluded:
                            return None
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
            return None

        # --- Stage 5: wild-substituted regular pays ---
        wild_product = 1
        for w in wilds:
            wild_product *= self.symbols.get(w).multiplier

        # Skip if any filler on payline (e.g. blank in col 1 with wild
        # on side; falls through to Stage 6 side_wild_alone below).
        if not any(self.symbols.get(s).is_filler for s in payline_symbols):
            candidates: list[tuple[int, int]] = []

            if "line_3_same" in self.order and len(set(non_wilds)) == 1:
                sym = non_wilds[0]
                n_wilds = len(wilds)
                for rule in self.rules.line_3_same_by_symbol.get(sym, []):
                    if rule.wild_required is True and n_wilds == 0:
                        continue
                    if rule.wild_required is False and n_wilds > 0:
                        continue
                    candidates.append((rule.pay_id, rule.multiplier * wild_product))

            if "line_3_group" in self.order:
                for rule in self.rules.line_3_group:
                    if all(s in rule.group for s in non_wilds):
                        candidates.append((rule.pay_id, rule.multiplier * wild_product))

            if candidates:
                best_pid, best_mult = max(candidates, key=lambda t: t[1])
                return PayResult(
                    pay_id=best_pid,
                    multiplier=best_mult,
                    positions=all_positions,
                )

        # --- Stage 6: side-wild-alone (M37) ---
        # Wild on col 0 or col 2 (or both), col 1 non-booster, no 3-match
        # fired above → flat pay (pay_id 9 × 1 on M37).
        if "side_wild_alone" in self.order and self.rules.side_wild_alone is not None:
            wild_positions = tuple(
                (c, 1) for c, s in enumerate(payline_symbols)
                if self.symbols.get(s).is_wild
            )
            if wild_positions:
                return PayResult(
                    pay_id=self.rules.side_wild_alone.pay_id,
                    multiplier=self.rules.side_wild_alone.multiplier,
                    positions=wild_positions,
                )

        return None

    def _evaluate_booster_center(
        self,
        payline_symbols: list[str],
        all_positions: tuple,
    ) -> PayResult | None:
        """Stage 2 body — col 1 is a booster symbol.

        Dispatches to:
          (a) pure_wild_with_booster if both sides wild (pay_id 102-104)
          (b) line_3_same / line_3_group with booster × mult, if sides
              form a 3-match anchor (wild-subbed, col 1 acts as the
              "third cell" matching the anchor)
          (c) center_booster_alone (pay_id 8/9) otherwise
        """
        booster_sym = self.symbols.get(payline_symbols[1])
        booster_name = payline_symbols[1]
        col_0 = payline_symbols[0]
        col_2 = payline_symbols[2]
        s_0 = self.symbols.get(col_0)
        s_2 = self.symbols.get(col_2)

        # (a) pure wild sides + booster center
        if s_0.is_wild and s_2.is_wild:
            if "pure_wild_with_booster" in self.order:
                rule = self.rules.pure_wild_with_booster_by_symbol.get(booster_name)
                if rule is not None:
                    return PayResult(
                        pay_id=rule.pay_id,
                        multiplier=rule.multiplier,
                        positions=all_positions,
                    )
            # fall through to center-alone if no rule (booster tier
            # without a dedicated pure-wild rule, e.g. M37's grand
            # which is reroll-blocked at server level). Both sides wild
            # → include both side positions in emission.
            return self._center_booster_alone(booster_name, ((0, 1), (2, 1)))

        # (b) side-match with booster center
        # Both side cells must be WILD or the target symbol — if any side
        # is blank/filler, the 3-match is broken (booster center alone
        # with flanking blank doesn't form a pay).
        has_filler_side = any(self.symbols.get(s).is_filler for s in (col_0, col_2))
        sides_non_wild = [s for s in (col_0, col_2)
                          if not self.symbols.get(s).is_wild
                          and not self.symbols.get(s).is_filler]

        if (
            not has_filler_side
            and sides_non_wild
            and "line_3_same" in self.order
            and len(set(sides_non_wild)) == 1
        ):
            target = sides_non_wild[0]
            # Check for a line_3_same rule matching this target (wild-subbed,
            # with booster treated as wild-equivalent for the match).
            n_wilds = sum(1 for s in (col_0, col_2)
                          if self.symbols.get(s).is_wild)
            for rule in self.rules.line_3_same_by_symbol.get(target, []):
                # wild_required semantics: booster center doesn't count
                # as a wild (it's a booster, distinct kind). M37 doesn't
                # use wild_required, so both M37 rules match regardless.
                if rule.wild_required is True and n_wilds == 0:
                    continue
                if rule.wild_required is False and n_wilds > 0:
                    continue
                # wild product: wilds on sides contribute their mult
                wild_product = 1
                for c in (col_0, col_2):
                    sym = self.symbols.get(c)
                    if sym.is_wild:
                        wild_product *= sym.multiplier
                final_mult = rule.multiplier * wild_product * booster_sym.multiplier
                return PayResult(
                    pay_id=rule.pay_id,
                    multiplier=final_mult,
                    positions=all_positions,
                )

        # (b') side-match with booster center via line_3_group
        if (
            not has_filler_side
            and "line_3_group" in self.order
            and sides_non_wild
        ):
            for rule in self.rules.line_3_group:
                # Group match: all side non-wilds in group. Booster fills
                # a virtual "third" slot matching the group (any group
                # member OK since booster is wild-like for match purposes).
                if all(s in rule.group for s in sides_non_wild):
                    wild_product = 1
                    for c in (col_0, col_2):
                        sym = self.symbols.get(c)
                        if sym.is_wild:
                            wild_product *= sym.multiplier
                    final_mult = rule.multiplier * wild_product * booster_sym.multiplier
                    return PayResult(
                        pay_id=rule.pay_id,
                        multiplier=final_mult,
                        positions=all_positions,
                    )

        # (c) center-alone — include side wild positions in PayoutByPayline
        # emission (production rawdata: pay_id 9 with side wild emits BOTH
        # positions, not just middle. Match production rawdata format so
        # downstream paytable inference can correctly classify match_count.)
        side_wild_positions = tuple(
            (c, 1) for c, s in enumerate(payline_symbols)
            if c != 1 and self.symbols.get(s).is_wild
        )
        return self._center_booster_alone(booster_name, side_wild_positions)

    def _center_booster_alone(
        self, booster_name: str,
        side_wild_positions: tuple = (),
    ) -> PayResult | None:
        """Lookup center_booster_alone pay (pay_id 8 grand, pay_id 9
        mini/minor/major on M37). Position list includes center (1,1)
        plus any side wild positions present on payline (production
        rawdata format)."""
        if "center_booster_alone" not in self.order:
            return None
        rule = self.rules.center_booster_alone_by_symbol.get(booster_name)
        if rule is None:
            return None
        # Sort positions by column for consistent emission order
        positions = tuple(sorted(side_wild_positions + ((1, 1),)))
        return PayResult(
            pay_id=rule.pay_id,
            multiplier=rule.multiplier,
            positions=positions,
        )

    def evaluate_all_paylines(
        self,
        grid: list[list[str]],
        paylines: Sequence[Sequence[tuple[int, int]]],
    ) -> list[PayResult]:
        """Evaluate all paylines on a multi-line machine.

        Calls ``evaluate_payline`` once per line and returns the list of
        non-None pays. Each PayResult's positions are remapped to the
        actual (col, row) cells of that line (not the (col, 1) middle-
        row default that ``evaluate_payline`` produces).

        Used by M279 (3-reel × 9-line) and any future multi-line machine.
        Single-line machines (M1/M15/M37) keep using ``evaluate_payline``
        directly; this method is purely additive.

        Returns: list of PayResult, one per winning line. Empty list when
        no line wins.
        """
        results: list[PayResult] = []
        for line_positions in paylines:
            line_syms = [grid[c][r] for (c, r) in line_positions]
            pay = self.evaluate_payline(line_syms)
            if pay is None:
                continue
            # Remap positions from (col, 1) default to actual line cells.
            # evaluate_payline returns positions tied to row=1; we replace
            # them with the line's own positions (preserving col order).
            actual_positions = tuple(tuple(p) for p in line_positions)
            results.append(PayResult(
                pay_id=pay.pay_id,
                multiplier=pay.multiplier,
                positions=actual_positions,
            ))
        return results

    def evaluate_scatters(
        self,
        grid: list[list[str]],
        payline_positions: Sequence[tuple[int, int]],
    ) -> list[PayResult]:
        """Evaluate scatter-trigger rules against the grid.

        Returns a list of PayResult for each ``ScatterTriggerRule`` whose
        target symbol lands on the payline cell of its specified reel.
        Scatter pays are ADDITIVE to the main payline pay — both coexist
        in PayoutIdToWinAmount in production rawdata (e.g., pay_id 9 for
        1-cherry + pay_id 666 for topdollar trigger on same spin).

        M15 use case: pay_id 666 fires when ``topdollar`` lands on reel 3
        (col 2) middle row. WinCredits contribution is 0 (marker pay).
        """
        results: list[PayResult] = []
        # Build a map of col_idx → row_idx on the payline.
        payline_row_by_col = {c: r for c, r in payline_positions}
        for rule in self.rules.scatter_triggers:
            col_idx = rule.reel - 1  # spec is 1-indexed
            row_idx = payline_row_by_col.get(col_idx)
            if row_idx is None:
                continue  # this reel isn't part of the payline
            if col_idx < 0 or col_idx >= len(grid):
                continue
            col = grid[col_idx]
            if row_idx < 0 or row_idx >= len(col):
                continue
            if col[row_idx] == rule.symbol:
                results.append(PayResult(
                    pay_id=rule.pay_id,
                    multiplier=rule.multiplier,
                    positions=((col_idx, row_idx),),
                ))
        return results
