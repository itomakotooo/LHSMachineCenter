"""play_types._claim — ClaimSignature dataclass + matches() evaluation.

Per 04_v2.md §4.2 (ClaimSignature) and the evaluation-scope clarification
added in §4.2-rev.

ClaimSignature is the auto-detection predicate for a PlayTypePlugin.  The
detector calls ``ClaimSignature.matches(sample_rounds, parse_state)`` on
the 5,000-round sample from chunk_0001 to determine which plugins apply to a
machine.

Evaluation scope (§4.2-rev)
----------------------------
Each field is evaluated against a specific round population:

required_fields
    Evaluated against PAID rounds (CostCredits > 0 OR
    parse_state.cost_credits_unreliable=True).  A field appearing only on
    bonus rounds is a bonus-round signal, not a paid-round field.
    Exception: if the field name starts with ``"_bonus_"``, it is evaluated
    against CostCredits=0 rounds (bonus-round-only fields convention).

required_bonus_remark_pattern
    Evaluated against CostCredits=0 rounds ONLY (bonus rounds).
    Case-sensitive by default.  Set bonus_remark_case_insensitive=True for
    case-insensitive matching.  The evaluator uses re.search() (not
    re.match()), so anchor the pattern if exact-match is needed.

required_trigger_pay_id
    Evaluated against paid rounds.  The pay_id must appear in
    PayoutIdToWinAmount on at least one paid round in the sample.

exclude_if_fields_present
    Evaluated against ANY round (paid or bonus).  If any round in the
    sample has the excluded field, the signature does not apply.

Minimum sample size
-------------------
The detector uses ALL rounds in chunk_0001 up to 5,000 rounds maximum
(§4.2-rev).  The ClaimSignature.matches() method operates on the rounds
list passed to it; the caller (detect_play_types) is responsible for
capping the sample at 5,000.

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ClaimSignature:
    """Auto-detection predicate for a PlayTypePlugin.

    All fields default to None / empty — a plugin with an empty signature
    matches every machine (useful for universal base plugins like PurePaid
    which match by exclusion of all other signals).

    Fields
    ------
    required_fields : frozenset[str]
        Field names that must be present in at least one PAID round's
        raw round dict.  Exception: names starting with ``"_bonus_"`` are
        evaluated against CostCredits=0 (bonus) rounds instead.
        Empty frozenset = no required-field constraint.

    required_bonus_remark_pattern : Optional[str]
        Regex pattern (re.search) that must match the ``ReMarks`` field on
        at least one CostCredits=0 (bonus) round.  None = no constraint.

    bonus_remark_case_insensitive : bool
        When True, ``required_bonus_remark_pattern`` is compiled with
        re.IGNORECASE.  Default False (case-sensitive).

    required_trigger_pay_id : Optional[str]
        Pay ID that must appear in ``PayoutIdToWinAmount`` on at least one
        paid round in the sample.  None = no constraint.

    exclude_if_fields_present : frozenset[str]
        Field names that, if present on ANY round (paid or bonus), veto this
        signature (Rule 1 structural exclusion from §4.6).
        Empty frozenset = no exclusion constraint.
    """

    required_fields: frozenset = field(default_factory=frozenset)
    required_bonus_remark_pattern: Optional[str] = None
    bonus_remark_case_insensitive: bool = False
    required_trigger_pay_id: Optional[str] = None
    exclude_if_fields_present: frozenset = field(default_factory=frozenset)

    def matches(self, sample_rounds: "list[dict]", parse_state: object) -> bool:
        """Return True if this signature matches the given sample rounds.

        Implements the §4.2-rev evaluation scope rules.

        Parameters
        ----------
        sample_rounds:
            List of raw round dicts (up to 5,000 rounds from chunk_0001).
            READ ONLY.
        parse_state:
            ParseState (or any object) with a ``cost_credits_unreliable``
            boolean attribute.  Defaults to False if the attribute is absent.

        Returns
        -------
        bool
            True if all constraints are satisfied, False if any constraint
            fails.
        """
        cost_credits_unreliable: bool = getattr(
            parse_state, "cost_credits_unreliable", False
        )

        def _is_paid(r: dict) -> bool:
            if cost_credits_unreliable:
                return True
            return (r.get("CostCredits") or 0) > 0

        def _is_bonus(r: dict) -> bool:
            return not _is_paid(r)

        paid_rounds = [r for r in sample_rounds if _is_paid(r)]
        bonus_rounds = [r for r in sample_rounds if _is_bonus(r)]

        # Rule 1: structural exclusion — hard veto (§4.6 Rule 1)
        # Evaluated against ANY round.
        if self.exclude_if_fields_present:
            for r in sample_rounds:
                for excluded_field in self.exclude_if_fields_present:
                    if excluded_field in r:
                        return False

        # required_fields — evaluated against paid rounds (with _bonus_ exception)
        for fname in self.required_fields:
            if fname.startswith("_bonus_"):
                # Exception: _bonus_-prefixed field names are evaluated against
                # CostCredits=0 (bonus) rounds.
                target_rounds = bonus_rounds
                # Strip the _bonus_ prefix for the actual field lookup.
                actual_fname = fname[len("_bonus_"):]
            else:
                target_rounds = paid_rounds
                actual_fname = fname
            if not any(actual_fname in r for r in target_rounds):
                return False

        # required_bonus_remark_pattern — evaluated against bonus rounds only
        if self.required_bonus_remark_pattern is not None:
            flags = re.IGNORECASE if self.bonus_remark_case_insensitive else 0
            pattern = re.compile(self.required_bonus_remark_pattern, flags)
            found = False
            for r in bonus_rounds:
                remarks = r.get("ReMarks") or ""
                if pattern.search(remarks):
                    found = True
                    break
            if not found:
                return False

        # required_trigger_pay_id — evaluated against paid rounds
        if self.required_trigger_pay_id is not None:
            pid = self.required_trigger_pay_id
            found = False
            for r in paid_rounds:
                payout_map = r.get("PayoutIdToWinAmount") or {}
                if pid in payout_map:
                    found = True
                    break
            if not found:
                return False

        return True
