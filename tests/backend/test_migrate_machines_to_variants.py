"""Pure-function tests for scripts/migrate_machines_to_variants.py.

Covers the migration contract:
  - Non-variant rows pass through unchanged.
  - Variant-bearing rows (underlying key present in variants_map
    values) are dropped; one row per variant key is inserted.
  - New variant rows inherit modes / logicClassNames / md5 / available
    from the old underlying row.
  - Pre-existing variant rows (e.g. from a prior partial migration run)
    are preserved, not clobbered.
  - Variants whose underlying row is missing from input get seeded
    with empty md5 and are reported in the ``missing_source`` stat.
  - Output row order is deterministic (machine key ascending) so code
    review diffs stay clean across re-runs.

These tests are the pure-function core of the migration. The script
entry point itself (file I/O) is intentionally left for manual
smoke testing.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_migrate_module():
    """The migration script isn't a package member (it lives under
    ``scripts/``); importlib.util.spec_from_file_location lets us
    import it without needing ``scripts`` to be a package."""
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


def _variants_map_M273() -> dict[str, str]:
    """Minimal realistic map: M273 expanded to 3 variants, M14
    untouched (no variants), M201 with 2 variants. The shape
    mirrors real upstream output."""
    return {
        "M273$0$": "M273",
        "M273$1$1-2-3": "M273",
        "M273$1$1-2-4": "M273",
        "M201$0$": "M201",
        "M201$1$2,3": "M201",
    }


def _source_machines() -> dict:
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


class TestNonVariantPassThrough:
    def test_non_variant_row_preserved_verbatim(self, migrate_mod):
        """M14 has no variants → its row survives intact."""
        new, _ = migrate_mod.migrate(_source_machines(), _variants_map_M273())
        m14 = next(r for r in new["machines"] if r["machine"] == "M14")
        assert m14 == {
            "machine": "M14",
            "modes": [1, 2, 5, 7],
            "logicClassNames": ["Normal"],
            "configSummaryMd5": "cfg14",
            "codeSummaryMd5": "code14",
            "available": True,
        }


class TestUnderlyingRowDropped:
    def test_underlying_row_replaced_by_variants(self, migrate_mod):
        """M273 (the underlying row) gone; 3 variant rows present."""
        new, stats = migrate_mod.migrate(_source_machines(), _variants_map_M273())
        names = {r["machine"] for r in new["machines"]}
        assert "M273" not in names  # dropped
        assert "M273$0$" in names
        assert "M273$1$1-2-3" in names
        assert "M273$1$1-2-4" in names
        assert stats["replaced_rows"] == 2  # M273 + M201
        assert stats["added_rows"] == 5

    def test_variant_inherits_source_md5(self, migrate_mod):
        """Every variant gets its underlying row's md5 as seed —
        critical so the post-migration machines.json is immediately
        functional even before the md5 refresh fanout runs."""
        new, _ = migrate_mod.migrate(_source_machines(), _variants_map_M273())
        m273_variants = [r for r in new["machines"] if r["machine"].startswith("M273$")]
        assert len(m273_variants) == 3
        for v in m273_variants:
            assert v["configSummaryMd5"] == "cfg273"
            assert v["codeSummaryMd5"] == "code273"

    def test_variant_inherits_source_logic_class_names(self, migrate_mod):
        """logicClassNames drives UI mechanic categorization — the
        variant must render the same category as its underlying."""
        new, _ = migrate_mod.migrate(_source_machines(), _variants_map_M273())
        m273_variant = next(r for r in new["machines"] if r["machine"] == "M273$0$")
        assert m273_variant["logicClassNames"] == ["Wheel", "FreeSpin"]

    def test_variant_inherits_source_modes(self, migrate_mod):
        """M273 underlying row was only modes [1, 7]; variants must
        inherit that — not the hard-default [1, 2, 5, 7]."""
        new, _ = migrate_mod.migrate(_source_machines(), _variants_map_M273())
        m273_variant = next(r for r in new["machines"] if r["machine"] == "M273$0$")
        assert m273_variant["modes"] == [1, 7]

    def test_variant_list_is_independent_copy(self, migrate_mod):
        """Regression guard: the variant's ``modes`` list must be a
        distinct object from the source row's — otherwise mutating
        one variant's modes would silently mutate its siblings."""
        new, _ = migrate_mod.migrate(_source_machines(), _variants_map_M273())
        variants = [r for r in new["machines"] if r["machine"].startswith("M273$")]
        variants[0]["modes"].append(99)
        assert variants[1]["modes"] == [1, 7]  # sibling unaffected


class TestPreservesPreExistingVariants:
    def test_pre_existing_variant_row_preserved(self, migrate_mod):
        """Idempotency: running the migration twice must not clobber
        already-migrated data. The second pass should detect the
        variant row is present and preserve it (not re-seed)."""
        # Simulate a post-first-pass state: M273 gone, M273$0$ present
        # with already-refreshed md5 that differs from underlying.
        src = {
            "machines": [
                {"machine": "M14", "configSummaryMd5": "cfg14",
                 "codeSummaryMd5": "code14", "modes": [1], "available": True},
                {
                    "machine": "M273$0$",
                    "modes": [1, 2, 5, 7],
                    "configSummaryMd5": "REFRESHED_cfg273",
                    "codeSummaryMd5": "REFRESHED_code273",
                    "logicClassNames": ["Wheel"],
                    "available": True,
                },
            ],
        }
        new, stats = migrate_mod.migrate(src, _variants_map_M273())
        preserved = next(r for r in new["machines"] if r["machine"] == "M273$0$")
        assert preserved["configSummaryMd5"] == "REFRESHED_cfg273"
        assert stats["skipped_rows"] == 1


class TestDeterministicOrder:
    def test_output_sorted_by_machine_key(self, migrate_mod):
        new, _ = migrate_mod.migrate(_source_machines(), _variants_map_M273())
        names = [r["machine"] for r in new["machines"]]
        assert names == sorted(names)


class TestMissingSourceRow:
    def test_variant_without_underlying_row_seeds_empty_md5(self, migrate_mod):
        """If variants_map references an underlying key that isn't in
        machines.json (e.g. new machine just landed upstream, local
        cache hasn't been md5-refreshed yet), the migration still
        produces variant rows — with empty md5 — and reports the
        issue via ``missing_source`` so the operator knows to refresh
        md5 afterward."""
        src = {"machines": [{"machine": "M14", "modes": [1],
                             "configSummaryMd5": "cfg14",
                             "codeSummaryMd5": "code14",
                             "logicClassNames": [],
                             "available": True}]}
        new, stats = migrate_mod.migrate(src, {"M999$0$": "M999"})
        m999 = next(r for r in new["machines"] if r["machine"] == "M999$0$")
        assert m999["configSummaryMd5"] == ""
        assert m999["codeSummaryMd5"] == ""
        # Safe defaults when no source to inherit from:
        assert m999["modes"] == [1, 2, 5, 7]
        assert m999["available"] is True
        assert stats["missing_source"] == ["M999"]


class TestEmptyAndEdgeInputs:
    def test_empty_variants_map_keeps_all_rows(self, migrate_mod):
        """Empty variants_map (fresh deployment before halls refresh)
        → no rows replaced, no rows added, machines.json unchanged
        semantically (reordered to alphabetical)."""
        new, stats = migrate_mod.migrate(_source_machines(), {})
        assert stats["replaced_rows"] == 0
        assert stats["added_rows"] == 0
        names = {r["machine"] for r in new["machines"]}
        assert names == {"M14", "M201", "M273"}

    def test_missing_machines_field_handled(self, migrate_mod):
        """Defensive: pass a dict without ``machines`` key → treat
        as empty list rather than raising."""
        new, stats = migrate_mod.migrate({}, _variants_map_M273())
        assert stats["kept_rows"] == 0
        assert stats["added_rows"] == 5
        assert stats["missing_source"] == ["M201", "M273"]


class TestBuildUpstreamToVariants:
    def test_inversion_groups_variants_per_underlying(self, migrate_mod):
        inv = migrate_mod.build_upstream_to_variants(_variants_map_M273())
        assert set(inv.keys()) == {"M273", "M201"}
        assert inv["M273"] == ["M273$0$", "M273$1$1-2-3", "M273$1$1-2-4"]
        assert inv["M201"] == ["M201$0$", "M201$1$2,3"]

    def test_inversion_stable_order_per_underlying(self, migrate_mod):
        """Sorted variant lists per underlying key so repeated runs
        produce byte-identical machines.json output."""
        messy = {"M5$3$": "M5", "M5$1$": "M5", "M5$2$": "M5"}
        inv = migrate_mod.build_upstream_to_variants(messy)
        assert inv["M5"] == ["M5$1$", "M5$2$", "M5$3$"]
