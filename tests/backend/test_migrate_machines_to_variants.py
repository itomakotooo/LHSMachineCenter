"""Pure-function tests for scripts/migrate_machines_to_variants.py.

The migration is idempotent and schema-evolution-aware: it accepts
legacy rows (plain upstream keys as machine names) and produces the
canonical shape where variant rows carry a display name containing
the selector type and an explicit ``upstream_key`` field for the
sampling path.

Covered invariants:
  - Non-variant rows pass through unchanged modulo the
    ``upstream_key`` field being ensured.
  - Variant-bearing underlying rows (``M273``, ``M201``, ...) are
    dropped; one row per variant upstream key is emitted with
    display name composed via ``compose_display_name``.
  - Variant rows inherit modes / md5 / logic from the best-matching
    seed (upstream_key, then current display name, then legacy
    upstream-key-as-machine, then the underlying).
  - Re-running the migration on a post-migration input is a no-op
    (all kept_variant / kept_non_variant, zero rewrites).
  - Changing ``selector_types`` and re-running rewrites only the
    affected variant rows.
  - Output row order is deterministic (machine key ascending).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_migrate_module():
    spec = importlib.util.spec_from_file_location(
        "migrate_machines_to_variants",
        ROOT / "scripts" / "migrate_machines_to_variants.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def migrate_mod():
    return _load_migrate_module()


def _variants_map_sample() -> dict[str, str]:
    """Three variants for M273, two for M201 — stable test fixture."""
    return {
        "M273$0$": "M273",
        "M273$1$1-2-3": "M273",
        "M273$1$1-2-4": "M273",
        "M201$0$": "M201",
        "M201$1$2,3": "M201",
    }


def _selector_types_sample() -> dict[str, str]:
    return {"M273": "WheelSelector", "M201": "CommonSelector"}


def _legacy_source() -> dict:
    """Pre-variants machines.json: 26 underlying rows. Mirrors the
    state at the start of the variants rollout so tests exercise the
    full upgrade path."""
    return {
        "machines": [
            {
                "machine": "M14",
                "modes": [1, 2, 5, 7],
                "logicClassNames": ["Normal"],
                "configSummaryMd5": "cfg14",
                "codeSummaryMd5": "code14",
                "available": True,
            },
            {
                "machine": "M273",
                "modes": [1, 7],
                "logicClassNames": ["Wheel", "FreeSpin"],
                "configSummaryMd5": "cfg273",
                "codeSummaryMd5": "code273",
                "available": True,
            },
            {
                "machine": "M201",
                "modes": [1, 2, 5, 7],
                "logicClassNames": ["Common"],
                "configSummaryMd5": "cfg201",
                "codeSummaryMd5": "code201",
                "available": True,
            },
        ],
    }


def _post_rebuild_source() -> dict:
    """machines.json after a previous run of the migration — variant
    rows already carry display names + upstream_key. Re-running
    should be a no-op modulo trivial field ordering."""
    return {
        "machines": [
            {
                "machine": "M14",
                "upstream_key": "M14",
                "modes": [1, 2, 5, 7],
                "logicClassNames": ["Normal"],
                "configSummaryMd5": "cfg14",
                "codeSummaryMd5": "code14",
                "available": True,
            },
            {
                "machine": "M273$WheelSelector$0$",
                "upstream_key": "M273$0$",
                "modes": [1, 7],
                "logicClassNames": ["Wheel"],
                "configSummaryMd5": "cfg273",
                "codeSummaryMd5": "code273",
                "available": True,
            },
            {
                "machine": "M273$WheelSelector$1$1-2-3",
                "upstream_key": "M273$1$1-2-3",
                "modes": [1, 7],
                "logicClassNames": ["Wheel"],
                "configSummaryMd5": "cfg273",
                "codeSummaryMd5": "code273",
                "available": True,
            },
            {
                "machine": "M273$WheelSelector$1$1-2-4",
                "upstream_key": "M273$1$1-2-4",
                "modes": [1, 7],
                "logicClassNames": ["Wheel"],
                "configSummaryMd5": "cfg273",
                "codeSummaryMd5": "code273",
                "available": True,
            },
            {
                "machine": "M201$CommonSelector$0$",
                "upstream_key": "M201$0$",
                "modes": [1, 2, 5, 7],
                "logicClassNames": ["Common"],
                "configSummaryMd5": "cfg201",
                "codeSummaryMd5": "code201",
                "available": True,
            },
            {
                "machine": "M201$CommonSelector$1$2,3",
                "upstream_key": "M201$1$2,3",
                "modes": [1, 2, 5, 7],
                "logicClassNames": ["Common"],
                "configSummaryMd5": "cfg201",
                "codeSummaryMd5": "code201",
                "available": True,
            },
        ],
    }


class TestFirstTimeMigration:
    def test_non_variant_preserved_gets_upstream_key_added(self, migrate_mod):
        """M14 has no variants — row survives but gains the
        upstream_key field (= machine name) to match new schema."""
        new, _ = migrate_mod.migrate(
            _legacy_source(), _variants_map_sample(), _selector_types_sample(),
        )
        m14 = next(r for r in new["machines"] if r["machine"] == "M14")
        assert m14["upstream_key"] == "M14"
        assert m14["configSummaryMd5"] == "cfg14"
        assert m14["codeSummaryMd5"] == "code14"
        assert m14["logicClassNames"] == ["Normal"]

    def test_underlying_row_dropped(self, migrate_mod):
        new, stats = migrate_mod.migrate(
            _legacy_source(), _variants_map_sample(), _selector_types_sample(),
        )
        names = {r["machine"] for r in new["machines"]}
        assert "M273" not in names
        assert "M201" not in names
        assert stats["dropped_underlying"] == 2

    def test_variant_rows_have_display_name_with_selector(self, migrate_mod):
        new, _ = migrate_mod.migrate(
            _legacy_source(), _variants_map_sample(), _selector_types_sample(),
        )
        names = {r["machine"] for r in new["machines"]}
        assert "M273$WheelSelector$0$" in names
        assert "M273$WheelSelector$1$1-2-3" in names
        assert "M273$WheelSelector$1$1-2-4" in names
        assert "M201$CommonSelector$0$" in names
        assert "M201$CommonSelector$1$2,3" in names
        # The raw upstream keys must NOT appear as machine names in
        # the post-migration shape.
        assert "M273$0$" not in names
        assert "M273$1$1-2-3" not in names

    def test_variant_rows_carry_upstream_key_field(self, migrate_mod):
        new, _ = migrate_mod.migrate(
            _legacy_source(), _variants_map_sample(), _selector_types_sample(),
        )
        m273_0 = next(r for r in new["machines"] if r["machine"] == "M273$WheelSelector$0$")
        assert m273_0["upstream_key"] == "M273$0$"
        m201_comma = next(r for r in new["machines"] if r["machine"] == "M201$CommonSelector$1$2,3")
        assert m201_comma["upstream_key"] == "M201$1$2,3"

    def test_variant_inherits_underlying_md5(self, migrate_mod):
        new, _ = migrate_mod.migrate(
            _legacy_source(), _variants_map_sample(), _selector_types_sample(),
        )
        m273_variants = [r for r in new["machines"] if r["machine"].startswith("M273$")]
        assert all(v["configSummaryMd5"] == "cfg273" for v in m273_variants)
        assert all(v["codeSummaryMd5"] == "code273" for v in m273_variants)

    def test_variant_inherits_underlying_modes_and_logic(self, migrate_mod):
        new, _ = migrate_mod.migrate(
            _legacy_source(), _variants_map_sample(), _selector_types_sample(),
        )
        m273_0 = next(r for r in new["machines"] if r["machine"] == "M273$WheelSelector$0$")
        assert m273_0["modes"] == [1, 7]
        assert m273_0["logicClassNames"] == ["Wheel", "FreeSpin"]

    def test_stats_counts_match_plan(self, migrate_mod):
        """Legacy → variants migration: every variant gets its md5/
        modes seeded from the underlying row, so they count as
        ``rewritten_variant`` (seed exists but display name/
        upstream_key differ), not ``added_variant``. ``added``
        means "no seed anywhere to inherit from"."""
        new, stats = migrate_mod.migrate(
            _legacy_source(), _variants_map_sample(), _selector_types_sample(),
        )
        assert stats["kept_non_variant"] == 1    # M14
        assert stats["dropped_underlying"] == 2  # M273 + M201
        assert stats["rewritten_variant"] == 5   # 3 M273 + 2 M201 seeded from underlying
        assert stats["added_variant"] == 0
        assert stats["kept_variant"] == 0
        assert stats["total_rows"] == 6          # M14 + 5 variants

    def test_no_seed_counts_as_added(self, migrate_mod):
        """A variants_map entry whose underlying isn't in the input
        machines.json (fresh deployment, never refreshed md5)
        produces a variant row with blank md5 — classified as
        ``added_variant`` not ``rewritten``."""
        # Empty machines.json: no M273 row to inherit from.
        new, stats = migrate_mod.migrate(
            {"machines": []}, _variants_map_sample(), _selector_types_sample(),
        )
        assert stats["added_variant"] == 5
        assert stats["rewritten_variant"] == 0


class TestIdempotentRerun:
    """Running the migration on an already-migrated input should be
    a no-op — every variant row matches the current selector config,
    no rewrites, no drops."""

    def test_post_rebuild_input_produces_same_row_set(self, migrate_mod):
        src = _post_rebuild_source()
        new, stats = migrate_mod.migrate(
            src, _variants_map_sample(), _selector_types_sample(),
        )
        old_names = sorted(r["machine"] for r in src["machines"])
        new_names = sorted(r["machine"] for r in new["machines"])
        assert new_names == old_names

    def test_post_rebuild_input_zero_rewrites(self, migrate_mod):
        new, stats = migrate_mod.migrate(
            _post_rebuild_source(), _variants_map_sample(), _selector_types_sample(),
        )
        assert stats["rewritten_variant"] == 0
        assert stats["added_variant"] == 0
        assert stats["dropped_underlying"] == 0
        # Every variant row kept, M14 kept non-variant.
        assert stats["kept_variant"] == 5
        assert stats["kept_non_variant"] == 1


class TestSelectorTypesChange:
    """Rotating a selector type name on the config must rewrite only
    the affected variant rows, preserving the rest."""

    def test_renamed_selector_rewrites_affected_rows_only(self, migrate_mod):
        # Operator edits selector_types: M273 rebadged to
        # "NewWheelSelector" (contrived — test purposes only).
        updated_selector_types = {
            "M273": "NewWheelSelector",
            "M201": "CommonSelector",  # unchanged
        }
        new, stats = migrate_mod.migrate(
            _post_rebuild_source(), _variants_map_sample(), updated_selector_types,
        )
        # M273 variants show the new selector name.
        names = {r["machine"] for r in new["machines"]}
        assert "M273$NewWheelSelector$0$" in names
        assert "M273$NewWheelSelector$1$1-2-3" in names
        # M201 variants untouched.
        assert "M201$CommonSelector$0$" in names
        assert "M201$CommonSelector$1$2,3" in names
        # Stats: 3 M273 rewrites, 2 M201 kept, 1 M14 kept.
        assert stats["rewritten_variant"] == 3
        assert stats["kept_variant"] == 2
        assert stats["kept_non_variant"] == 1

    def test_missing_selector_type_falls_back_to_bare_upstream_key(self, migrate_mod):
        """A variant_map underlying that's absent from selector_types
        still lands, but with the raw upstream key as its display
        name. The underlying is recorded in missing_selector so the
        operator knows to update the config."""
        partial_types = {"M273": "WheelSelector"}  # M201 missing
        new, stats = migrate_mod.migrate(
            _legacy_source(), _variants_map_sample(), partial_types,
        )
        names = {r["machine"] for r in new["machines"]}
        # M201 variants fall back to raw upstream key as display name.
        assert "M201$0$" in names
        assert "M201$1$2,3" in names
        assert stats["missing_selector"] == ["M201"]


class TestDeterministicOrder:
    def test_output_sorted_by_machine_key(self, migrate_mod):
        new, _ = migrate_mod.migrate(
            _legacy_source(), _variants_map_sample(), _selector_types_sample(),
        )
        names = [r["machine"] for r in new["machines"]]
        assert names == sorted(names)


class TestEdgeInputs:
    def test_empty_variants_map_returns_non_variants_unchanged(self, migrate_mod):
        new, stats = migrate_mod.migrate(_legacy_source(), {}, {})
        # All 3 input rows survive as non-variants (added upstream_key).
        assert stats["dropped_underlying"] == 0
        assert stats["added_variant"] == 0
        names = {r["machine"] for r in new["machines"]}
        assert names == {"M14", "M201", "M273"}
        # Every row gets upstream_key = machine.
        for r in new["machines"]:
            assert r["upstream_key"] == r["machine"]

    def test_missing_machines_field_handled(self, migrate_mod):
        new, stats = migrate_mod.migrate(
            {}, _variants_map_sample(), _selector_types_sample(),
        )
        assert stats["kept_non_variant"] == 0
        assert stats["added_variant"] == 5


class TestBuildUpstreamToVariants:
    def test_inversion_groups_variants_per_underlying(self, migrate_mod):
        inv = migrate_mod.build_upstream_to_variants(_variants_map_sample())
        assert set(inv.keys()) == {"M273", "M201"}
        assert inv["M273"] == ["M273$0$", "M273$1$1-2-3", "M273$1$1-2-4"]
        assert inv["M201"] == ["M201$0$", "M201$1$2,3"]

    def test_inversion_stable_order_per_underlying(self, migrate_mod):
        messy = {"M5$3$": "M5", "M5$1$": "M5", "M5$2$": "M5"}
        inv = migrate_mod.build_upstream_to_variants(messy)
        assert inv["M5"] == ["M5$1$", "M5$2$", "M5$3$"]
