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
