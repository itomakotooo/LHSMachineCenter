"""Phase 2b — index/value coverage for the carved ``_quantiles`` closure.

WHY THIS FILE EXISTS (impl-tester paranoid finding, 2026-05-29)
---------------------------------------------------------------
The Phase 2b carve moved the ``_quantiles`` closure verbatim from PIA into
``fresh_slotlab/analyzer/features/bonus_chain_dynamics.py`` (now a module-level
helper).  The byte-identity deep-diff in
``test_2b_byte_identical_bonus_chain_carve.py`` runs against REAL cached M275/M14
data — but I discovered those datasets are DEGENERATE for ``_quantiles``:

  - M275 mode 1: every bonus chain is length 10 / max-ratio 100, so
    ``chain_length_quantiles`` == ``{p50:10, p90:10, p95:10, max:10, avg:10.0}``
    (and by_feature likewise).  With a UNIFORM input list every quantile index
    lands on the same value (10), so a `_quantiles` INDEX bug (e.g. p90 reading
    ``int(p*(n-1))`` instead of ``round(...)``, or an off-by-one on the p95 idx)
    would produce the SAME output and the deep-diff would stay GREEN.
  - M14: no chains at all → the empty-list early-return branch only.

So neither golden machine exercises the quantile-INDEX arithmetic.  The
implementer's ``_make_stash()`` unit fixture has the same gap (uniform [5]*908).
This file closes it: it drives the moved closure with GENUINELY VARIED inputs so
the p50/p90/p95/max index selection + the rounding rule + the avg division are all
locked.  Combined with the byte-identity test (which locks the VALUE path on real
data + the dict assembly around the closure), the carved compute is fully covered.

This is a pure-function unit test — no subprocess needed (the helper has no I/O).
The byte-identity subprocess test remains the e2e PIA<->plugin wiring guard per
feedback_perf_claim_needs_e2e_event_stream.md; this complements it, not replaces it.

Inject-bug recipe (Path A' — _quantiles index drift)
-----------------------------------------------------
Temporarily mutate the index math in ``_quantiles`` in bonus_chain_dynamics.py,
e.g. change::

    idx = min(n - 1, max(0, int(round(p * (n - 1)))))
to::
    idx = min(n - 1, max(0, int(p * (n - 1))))          # BUG: truncate, not round

RED: ``test_quantiles_varied_input_exact`` fails — for 1..10 the truncate bug
     drops the p95 index from 9 to 8, so p95 becomes 9 not 10 (p50 stays 5 and
     p90 stays 9 — those indices round and truncate to the same value, so this
     particular bug does not move them).  NOTE the M275/M14 byte-identity test
     stays GREEN under this bug (uniform input) — which is precisely why this
     file is needed.
Revert -> GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md
    a test alone proves nothing; the index drift inject-bug proves this catches it.
- memory/feedback_self_verify_output.md
    cross-checked the degeneracy by dumping the real M275 quantiles (all 10) before
    asserting — the gap is real, not assumed.
- memory/feedback_invariant_with_fallback_hides_drift.md
    the empty-list early-return is an explicit no-data branch (not a silent 0-fill
    that could mask a missing input) — asserted distinctly.
"""
from __future__ import annotations

import pytest


def _import_quantiles():
    try:
        from fresh_slotlab.analyzer.features.bonus_chain_dynamics import _quantiles
    except ImportError:
        from analyzer.features.bonus_chain_dynamics import _quantiles  # type: ignore[no-redef]
    return _quantiles


# ---------------------------------------------------------------------------
# T1: varied input — the index arithmetic the golden machines cannot exercise
# ---------------------------------------------------------------------------

class TestQuantilesVariedInput:
    """Varied inputs make p50/p90/p95/max land on DISTINCT values.

    Expected values computed from the verbatim algorithm:
      idx(p) = min(n-1, max(0, round(p*(n-1)))); value = sorted[idx]
      avg    = sum / n
    """

    def test_quantiles_varied_input_exact(self):
        """xs = 1..10 (n=10): p50=5, p90=9, p95=10, max=10, avg=5.5.

        INJECT-BUG (Path A'): truncate instead of round in the idx math →
        p50 becomes 4, p90 becomes 8. RED here (byte-identity stays GREEN — the
        whole point of this file). Revert -> GREEN.
        """
        _quantiles = _import_quantiles()
        q = _quantiles(list(range(1, 11)))
        assert q == {"p50": 5, "p90": 9, "p95": 10, "max": 10, "avg": 5.5}, (
            f"_quantiles(1..10) drifted — index/rounding/avg logic changed. Got {q}"
        )

    def test_quantiles_skewed_input_exact(self):
        """xs = [1,1,1,1,100] (n=5): p50=1, p90=100, p95=100, max=100, avg=20.8.

        A heavy-tail shape: proves p50 picks the low body while p90/p95/max pick
        the tail — distinct index selection a uniform list cannot reveal.
        """
        _quantiles = _import_quantiles()
        q = _quantiles([1, 1, 1, 1, 100])
        assert q == {"p50": 1, "p90": 100, "p95": 100, "max": 100, "avg": 20.8}, (
            f"_quantiles([1,1,1,1,100]) drifted. Got {q}"
        )

    def test_quantiles_unsorted_input_is_sorted_first(self):
        """Input order must not matter — the closure sorts before indexing.

        Same multiset as 1..10 but shuffled; must give the identical result.
        """
        _quantiles = _import_quantiles()
        q = _quantiles([10, 3, 7, 1, 9, 2, 8, 4, 6, 5])
        assert q == {"p50": 5, "p90": 9, "p95": 10, "max": 10, "avg": 5.5}, (
            f"_quantiles must sort its input before indexing. Got {q}"
        )

    def test_quantiles_values_are_int_not_float(self):
        """p50/p90/p95/max must be ints (the closure casts via int()).

        Guards against a type drift (e.g. dropping the int() cast) that the
        deep-diff would catch on data but is cheap to assert directly. avg is the
        only float (true division).
        """
        _quantiles = _import_quantiles()
        q = _quantiles([1, 2, 3, 4, 5])
        for k in ("p50", "p90", "p95", "max"):
            assert isinstance(q[k], int), f"{k} must be int, got {type(q[k]).__name__}"
        assert isinstance(q["avg"], float), "avg must be float (true division)"


# ---------------------------------------------------------------------------
# T2: boundary inputs — empty + single (the early-return + n==1 paths)
# ---------------------------------------------------------------------------

class TestQuantilesBoundaries:
    """The early-return (empty) and single-element branches.

    The empty branch is the ONLY one M14 exercises end-to-end; the single-element
    branch is exercised by neither golden machine.
    """

    def test_quantiles_empty_early_return(self):
        """Empty input -> the explicit no-data dict (NOT a crash / NOT silent None).

        Per feedback_invariant_with_fallback_hides_drift.md this is an explicit
        no-data signal, distinct from a missing field. This matches M14's
        applicable=False bonus_chain_dynamics.chain_length_quantiles exactly.
        """
        _quantiles = _import_quantiles()
        assert _quantiles([]) == {"p50": 0, "p90": 0, "p95": 0, "max": 0, "avg": 0.0}

    def test_quantiles_single_element(self):
        """Single element -> every quantile is that element; avg equals it."""
        _quantiles = _import_quantiles()
        assert _quantiles([42]) == {"p50": 42, "p90": 42, "p95": 42, "max": 42, "avg": 42.0}

    def test_quantiles_uniform_matches_m275_shape(self):
        """Uniform [10]*908 -> the degenerate {10,...} shape M275 actually emits.

        Documents (and locks) the degeneracy the docstring describes: this is
        WHY M275 cannot cover the index arithmetic — the value is correct, but a
        uniform list makes every index land on the same value.
        """
        _quantiles = _import_quantiles()
        q = _quantiles([10] * 908)
        assert q == {"p50": 10, "p90": 10, "p95": 10, "max": 10, "avg": 10.0}
