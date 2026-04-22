"""Tests for the variants-map resolver.

The resolver is the single place where "machine → upstream md5 key"
is answered. These tests lock the contract:

  1. A machine present in the variants_map resolves to its listed
     upstream key (md5 fanout: many machines can share one key).
  2. A machine absent from the map resolves to itself (non-variant
     machines and empty-map deployments).
  3. ``load_variants_map`` reads the current schema
     (``data["variants_map"]``), falls back to the raw upstream
     payload (``data["raw_upstream"]["machineTestVariantsJson"]``),
     and returns empty on every error path instead of raising.
  4. Malformed entries (non-string key/value) are dropped rather
     than propagated.

The resolver must never parse the variant-key structure — callers
downstream rely on that invariant to avoid breaking when upstream
changes the key format.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.web_console.backend.machine_variants import (
    apply_md5_refresh,
    load_variants_map,
    resolve_upstream_md5_key,
)


class TestResolveUpstreamMd5Key:
    def test_variant_resolves_to_listed_upstream_key(self):
        vmap = {"M273$0$": "M273", "M273$1$1-2-3": "M273"}
        assert resolve_upstream_md5_key("M273$1$1-2-3", vmap) == "M273"
        assert resolve_upstream_md5_key("M273$0$", vmap) == "M273"

    def test_fanout_many_variants_same_upstream_key(self):
        """26 underlying machines feed 166 variant entries — the map
        is many-to-one. Every variant under the same upstream key
        returns the same value."""
        vmap = {
            "M201$0$": "M201",
            "M201$1$2": "M201",
            "M201$1$3,4": "M201",
            "M201$1$2,3,4": "M201",
        }
        resolved = {resolve_upstream_md5_key(k, vmap) for k in vmap}
        assert resolved == {"M201"}

    def test_non_variant_resolves_to_self(self):
        """Machines with no variants (227 of the 253-machine fleet)
        stay unchanged — the map simply doesn't list them."""
        vmap = {"M273$0$": "M273"}
        assert resolve_upstream_md5_key("M14", vmap) == "M14"
        assert resolve_upstream_md5_key("M1", vmap) == "M1"

    def test_empty_map_is_identity(self):
        """A fresh deployment before the first halls refresh has no
        variants map yet. The resolver must degrade to identity so
        existing non-variant machines keep working."""
        assert resolve_upstream_md5_key("M273$0$", {}) == "M273$0$"
        assert resolve_upstream_md5_key("M14", {}) == "M14"

    def test_key_format_is_not_parsed(self):
        """Regression guard: the resolver must NOT try to derive the
        upstream key by splitting on ``$`` or any other separator.
        If someone later introduces a variant whose upstream key
        doesn't share the machine key's prefix, string-splitting
        would produce the wrong answer — the map is authoritative.
        """
        # Contrived but valid: map entry where the upstream key has
        # nothing structurally in common with the machine key.
        vmap = {"WEIRD_KEY$$": "CompletelyDifferent"}
        assert resolve_upstream_md5_key("WEIRD_KEY$$", vmap) == "CompletelyDifferent"

    def test_unknown_machine_not_in_map_resolves_to_self(self):
        """Defensive: a machine.json entry that somehow isn't in the
        variants map (e.g. map loaded stale) falls back to itself
        rather than raising — the md5 refresh can still proceed for
        machines it can resolve and flag the rest as unresolved."""
        vmap = {"M273$0$": "M273"}
        assert resolve_upstream_md5_key("M9999$0$", vmap) == "M9999$0$"


class TestLoadVariantsMap:
    def test_reads_direct_variants_map_field(self, tmp_path: Path):
        halls = tmp_path / "halls.json"
        halls.write_text(
            json.dumps({"variants_map": {"M273$0$": "M273"}}),
            encoding="utf-8",
        )
        assert load_variants_map(halls) == {"M273$0$": "M273"}

    def test_backcompat_parses_raw_upstream(self, tmp_path: Path):
        """Older halls.json written before the variants_map field
        landed stored only the raw upstream payload. Loader parses
        ``machineTestVariantsJson`` inline so a stale cache still
        provides the map without requiring an explicit refresh."""
        halls = tmp_path / "halls.json"
        halls.write_text(
            json.dumps({
                "raw_upstream": {
                    "machineTestVariantsJson": json.dumps(
                        {"M273$0$": "M273", "M273$1$1-2-3": "M273"}
                    ),
                },
            }),
            encoding="utf-8",
        )
        assert load_variants_map(halls) == {
            "M273$0$": "M273",
            "M273$1$1-2-3": "M273",
        }

    def test_direct_field_takes_precedence_over_raw(self, tmp_path: Path):
        """When both are present (after a refresh under the current
        schema), the direct field wins — it's the post-parse
        canonical view and shouldn't be second-guessed by re-parsing
        the raw stash."""
        halls = tmp_path / "halls.json"
        halls.write_text(
            json.dumps({
                "variants_map": {"M273$0$": "M273"},
                "raw_upstream": {
                    "machineTestVariantsJson": json.dumps(
                        {"OBSOLETE$0$": "OLD"}
                    ),
                },
            }),
            encoding="utf-8",
        )
        assert load_variants_map(halls) == {"M273$0$": "M273"}

    def test_missing_file_returns_empty(self, tmp_path: Path):
        """Fresh checkout with no halls.json yet — hot paths call
        this on every md5 refresh so raising would break every
        such call until the operator runs the halls refresh."""
        assert load_variants_map(tmp_path / "no_such_file.json") == {}

    def test_unreadable_json_returns_empty(self, tmp_path: Path):
        halls = tmp_path / "halls.json"
        halls.write_text("{not valid json", encoding="utf-8")
        assert load_variants_map(halls) == {}

    def test_no_variants_field_returns_empty(self, tmp_path: Path):
        """halls.json without variants_map / raw_upstream (e.g.
        operator ran a trimmed local fixture) returns empty rather
        than raising KeyError."""
        halls = tmp_path / "halls.json"
        halls.write_text(
            json.dumps({"default_order": ["M14"]}),
            encoding="utf-8",
        )
        assert load_variants_map(halls) == {}

    def test_non_dict_top_level_returns_empty(self, tmp_path: Path):
        halls = tmp_path / "halls.json"
        halls.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
        assert load_variants_map(halls) == {}

    def test_malformed_entries_are_dropped(self, tmp_path: Path):
        """Defensive filter: if upstream schema drifts and returns
        non-string values, drop those rows rather than letting them
        confuse downstream resolution."""
        halls = tmp_path / "halls.json"
        halls.write_text(
            json.dumps({"variants_map": {
                "M273$0$": "M273",
                "M200$0$": 42,          # bad value
                "M201$0$": ["M201"],    # bad value
                "M202$0$": None,        # bad value
            }}),
            encoding="utf-8",
        )
        assert load_variants_map(halls) == {"M273$0$": "M273"}

    def test_raw_upstream_variants_json_malformed_returns_empty(
        self, tmp_path: Path,
    ):
        """raw_upstream.machineTestVariantsJson is a *string* that
        needs JSON decoding; garbage in that string must not raise."""
        halls = tmp_path / "halls.json"
        halls.write_text(
            json.dumps({"raw_upstream": {
                "machineTestVariantsJson": "{not valid",
            }}),
            encoding="utf-8",
        )
        assert load_variants_map(halls) == {}


# ---------------------------------------------------------------------
# apply_md5_refresh — variant-aware fanout
# ---------------------------------------------------------------------


def _md5_entry(cfg: str, code: str, logic: list[str] | None = None) -> dict:
    """Minimal upstream MachineConfigMd5 row. Mirrors the real shape
    so tests don't drift from production behaviour."""
    return {
        "configSummaryMd5": cfg,
        "codeSummaryMd5": code,
        "logicClassNames": logic or [],
        "files": [],  # upstream returns this; we don't persist it
    }


class TestFanoutVariantMd5:
    def test_all_variants_inherit_underlying_md5(self):
        """Core fanout contract: updating M273's upstream md5 makes
        *every* M273$... row pick up the new value with a single
        refresh call. Before stage 3, only a bare M273 row would
        have seen the update."""
        machines_json = {"machines": [
            {"machine": "M273$0$", "configSummaryMd5": "old",
             "codeSummaryMd5": "old", "modes": [1, 7]},
            {"machine": "M273$1$1-2-3", "configSummaryMd5": "old",
             "codeSummaryMd5": "old", "modes": [1, 7]},
            {"machine": "M273$1$4-5-6", "configSummaryMd5": "old",
             "codeSummaryMd5": "old", "modes": [1, 7]},
        ]}
        upstream = {"M273": _md5_entry("cfg_NEW", "code_NEW", ["Wheel"])}
        vmap = {"M273$0$": "M273", "M273$1$1-2-3": "M273", "M273$1$4-5-6": "M273"}

        new, stats = apply_md5_refresh(machines_json, upstream, vmap)

        for name in ("M273$0$", "M273$1$1-2-3", "M273$1$4-5-6"):
            row = next(r for r in new["machines"] if r["machine"] == name)
            assert row["configSummaryMd5"] == "cfg_NEW"
            assert row["codeSummaryMd5"] == "code_NEW"
            assert row["logicClassNames"] == ["Wheel"]
        assert stats["updated_count"] == 3
        assert stats["updated_machines"] == sorted(vmap.keys())

    def test_non_variant_row_unaffected_by_sibling_variant_change(self):
        """Fanout must not bleed across underlyings: updating only
        M273 upstream leaves M14 alone even if both rows exist in
        the local machines.json."""
        machines_json = {"machines": [
            {"machine": "M14", "configSummaryMd5": "m14_old",
             "codeSummaryMd5": "m14_old", "modes": [1]},
            {"machine": "M273$0$", "configSummaryMd5": "old",
             "codeSummaryMd5": "old", "modes": [1]},
        ]}
        upstream = {
            "M14": _md5_entry("m14_old", "m14_old"),      # unchanged
            "M273": _md5_entry("cfg_NEW", "code_NEW"),    # changed
        }
        vmap = {"M273$0$": "M273"}

        _, stats = apply_md5_refresh(machines_json, upstream, vmap)
        assert stats["updated_machines"] == ["M273$0$"]

    def test_non_variant_row_updated_normally(self):
        """Legacy path: non-variant rows route through identity
        resolution and behave as they did before stage 3."""
        machines_json = {"machines": [
            {"machine": "M14", "configSummaryMd5": "old",
             "codeSummaryMd5": "old", "modes": [1]},
        ]}
        upstream = {"M14": _md5_entry("cfg_NEW", "code_NEW")}
        _, stats = apply_md5_refresh(machines_json, upstream, {})
        assert stats["updated_machines"] == ["M14"]

    def test_empty_variants_map_is_backcompat(self):
        """Pre-variants deployment: every row resolves to itself.
        The upstream data drives updates exactly like before."""
        machines_json = {"machines": [
            {"machine": "M14", "configSummaryMd5": "old",
             "codeSummaryMd5": "old", "modes": [1]},
            {"machine": "M272", "configSummaryMd5": "old",
             "codeSummaryMd5": "old", "modes": [1]},
        ]}
        upstream = {
            "M14": _md5_entry("cfg_NEW", "code_NEW"),
            "M272": _md5_entry("cfg_NEW2", "code_NEW2"),
        }
        _, stats = apply_md5_refresh(machines_json, upstream, {})
        assert stats["updated_machines"] == ["M14", "M272"]
        assert stats["unresolved_entries"] == []

    def test_same_md5_no_op_updates_nothing(self):
        """Re-running refresh against identical upstream must
        produce zero updates — drift surfaces *only* when something
        actually changed."""
        machines_json = {"machines": [
            {"machine": "M273$0$", "configSummaryMd5": "cur",
             "codeSummaryMd5": "cur", "modes": [1]},
        ]}
        upstream = {"M273": _md5_entry("cur", "cur")}
        vmap = {"M273$0$": "M273"}
        _, stats = apply_md5_refresh(machines_json, upstream, vmap)
        assert stats["updated_count"] == 0
        assert stats["updated_machines"] == []


class TestUnresolvedEntries:
    def test_variant_missing_upstream_flagged_not_overwritten(self):
        """A variant row references an upstream key that's NOT in
        the current response (e.g. upstream decommissioned the
        underlying). The variant row must retain its old md5 and
        get listed in unresolved_entries so the operator notices."""
        machines_json = {"machines": [
            {"machine": "M999$0$", "configSummaryMd5": "keep",
             "codeSummaryMd5": "keep", "modes": [1]},
        ]}
        upstream = {"M14": _md5_entry("cfg", "code")}
        vmap = {"M999$0$": "M999"}
        new, stats = apply_md5_refresh(machines_json, upstream, vmap)
        row = next(r for r in new["machines"] if r["machine"] == "M999$0$")
        assert row["configSummaryMd5"] == "keep"
        assert stats["unresolved_entries"] == ["M999$0$"]


class TestDiscovery:
    def test_new_non_variant_machine_added(self):
        """Upstream reports a machine we haven't seen locally and
        it's not variant-bearing → create a bare row. Same as
        legacy behaviour."""
        machines_json = {"machines": []}
        upstream = {"M999": _md5_entry("cfg", "code")}
        new, stats = apply_md5_refresh(machines_json, upstream, {})
        names = [r["machine"] for r in new["machines"]]
        assert names == ["M999"]
        assert stats["discovered_machines"] == ["M999"]

    def test_variant_bearing_underlying_key_not_added_as_bare_row(self):
        """Regression guard: when upstream reports M273 and
        variants_map lists M273 as the upstream key for several
        variants, we must NOT create a bare M273 row. If we did,
        that row would shadow the variant rows during resolution
        and they'd stop updating."""
        machines_json = {"machines": [
            {"machine": "M273$0$", "configSummaryMd5": "old",
             "codeSummaryMd5": "old", "modes": [1]},
        ]}
        upstream = {"M273": _md5_entry("cfg_NEW", "code_NEW")}
        vmap = {"M273$0$": "M273", "M273$1$1-2-3": "M273"}
        new, stats = apply_md5_refresh(machines_json, upstream, vmap)
        names = [r["machine"] for r in new["machines"]]
        assert "M273" not in names
        assert "M273$0$" in names
        assert stats["discovered_machines"] == []

    def test_all_empty_md5_row_not_materialized(self):
        """Noise filter: upstream sometimes returns a row with
        everything blank. Don't materialize that as a local row
        — it's not useful information and spams the catalog."""
        machines_json = {"machines": []}
        upstream = {"M999": _md5_entry("", "")}
        new, stats = apply_md5_refresh(machines_json, upstream, {})
        assert new["machines"] == []
        assert stats["discovered_machines"] == []


class TestDefensiveEmptyMd5:
    def test_empty_upstream_md5_does_not_overwrite_existing(self):
        """Legacy guard preserved: blank upstream md5 must NOT
        replace a real local md5. This has been a bug source pre-
        variants; the variants path keeps the same defense."""
        machines_json = {"machines": [
            {"machine": "M14", "configSummaryMd5": "real",
             "codeSummaryMd5": "real", "modes": [1]},
        ]}
        upstream = {"M14": _md5_entry("", "")}
        new, stats = apply_md5_refresh(machines_json, upstream, {})
        row = next(r for r in new["machines"] if r["machine"] == "M14")
        assert row["configSummaryMd5"] == "real"
        assert stats["skipped_empty_upstream"] == 1


class TestMalformedInput:
    def test_non_dict_upstream_row_treated_as_unresolved(self):
        """Upstream schema drift: a row came back as a string /
        list / other non-dict. Don't crash; flag as unresolved so
        the operator sees it."""
        machines_json = {"machines": [
            {"machine": "M14", "configSummaryMd5": "keep",
             "codeSummaryMd5": "keep", "modes": [1]},
        ]}
        upstream = {"M14": "not a dict"}
        new, stats = apply_md5_refresh(machines_json, upstream, {})
        row = next(r for r in new["machines"] if r["machine"] == "M14")
        assert row["configSummaryMd5"] == "keep"
        assert stats["unresolved_entries"] == ["M14"]

    def test_malformed_local_row_silently_skipped(self):
        """machines.json could in principle have a row without a
        ``machine`` field (bad hand-edit, corrupted import). Skip
        it rather than crash — don't let one bad row block the
        fleet-wide refresh."""
        machines_json = {"machines": [
            {"machine": "M14", "configSummaryMd5": "old",
             "codeSummaryMd5": "old", "modes": [1]},
            {"no_machine_field": "oops"},  # malformed
            {"machine": 42},               # bad type
        ]}
        upstream = {"M14": _md5_entry("new", "new")}
        _, stats = apply_md5_refresh(machines_json, upstream, {})
        assert stats["updated_machines"] == ["M14"]
        assert stats["unresolved_entries"] == []

    def test_missing_machines_field_initializes(self):
        """Called with a machines.json missing the ``machines`` key
        (e.g. fresh file). setdefault initializes it to [] so pass
        1 can still discover — return structure stays consistent."""
        machines_json = {}
        upstream = {"M999": _md5_entry("cfg", "code")}
        new, _ = apply_md5_refresh(machines_json, upstream, {})
        assert new["machines"][0]["machine"] == "M999"


class TestFanoutCountSemantics:
    def test_updated_count_equals_updated_machines_length(self):
        """updated_count stat must always match the length of
        updated_machines list — surfaces if we ever accidentally
        double-count or miss a row."""
        machines_json = {"machines": [
            {"machine": f"M273$1${i}", "configSummaryMd5": "old",
             "codeSummaryMd5": "old", "modes": [1]}
            for i in range(5)
        ]}
        upstream = {"M273": _md5_entry("cfg_NEW", "code_NEW")}
        vmap = {f"M273$1${i}": "M273" for i in range(5)}
        _, stats = apply_md5_refresh(machines_json, upstream, vmap)
        assert stats["updated_count"] == len(stats["updated_machines"]) == 5

    def test_updated_machines_sorted_for_deterministic_log(self):
        """Activity log dedups and shows first 5 + suffix (+K).
        Stable order matters: operators eyeballing the log want the
        same rendering across refresh clicks."""
        machines_json = {"machines": [
            {"machine": n, "configSummaryMd5": "old",
             "codeSummaryMd5": "old", "modes": [1]}
            for n in ("M273$1$zz", "M273$0$", "M273$1$aa")
        ]}
        upstream = {"M273": _md5_entry("cfg_NEW", "code_NEW")}
        vmap = {"M273$0$": "M273", "M273$1$aa": "M273", "M273$1$zz": "M273"}
        _, stats = apply_md5_refresh(machines_json, upstream, vmap)
        assert stats["updated_machines"] == sorted(stats["updated_machines"])
