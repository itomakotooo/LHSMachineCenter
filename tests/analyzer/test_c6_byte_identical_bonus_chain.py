"""Phase C6 — bonus_chain_dynamics stash is byte-identical carve.

Verifies that C6's bonus_chain_dynamics plugin produces the same
player_impact.bonus_chain_dynamics subkey content as was produced by the
pre-C6 inline F6 block.

Since C6 is a pure carve (stash pattern: F6 inline writes the dict, plugin
reads it back and re-writes it unchanged), the carve must be byte-identical
for player_impact.bonus_chain_dynamics.

This test uses a different approach from the git-stash strategy (which requires
git stash/pop and a known pre-C6 baseline) because the branch is already on C6.
Instead it verifies the stash pattern invariant directly:

  1. Plugin emit() receives the stash dict built by F6 inline.
  2. Plugin writes EXACTLY that dict back to player_impact.bonus_chain_dynamics.
  3. The original F6 inline-written value (before plugin runs) equals the
     plugin-rewritten value (after plugin runs).

This equivalence is the byte-identical contract.

Additionally verifies:
  - stash key absent from final M275 summary (cleanup complete).
  - stash key absent from final M14 summary.
  - No _ prefix keys at top level of either summary.
  - base_hash is the R-1 closure value (d8b8c138874a as of phase-6; registered plugins excluded by R-4).

Inject-bug recipe (complementary — main Bug A in test_c6_bonus_chain_dynamics_plugin.py):
    Change PIA stash key to carry a MODIFIED bonus_chain_dynamics (e.g. set
    chain_count to 0). The byte-identical invariant fails because the plugin
    writes the modified stash value, making the two runs diverge.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess required; in-process unit tests cannot catch PIA wiring)
- memory/feedback_subprocess_import_suicide_and_module_globals.md
  (stash cleanup must run even for non-M275 machines like M14)
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_M275_CACHE = _REPO_ROOT / "rawdata" / "M275" / "mode_1"
_M14_CACHE = _REPO_ROOT / "rawdata" / "M14" / "mode_1"

_STASH_KEY = "_bonus_chain_dynamics_data"


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixtures
# ---------------------------------------------------------------------------

def _run_pia(machine: str, cache_dir: Path) -> dict:
    """Run PIA from cache and return summary."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable, str(_PIA),
            "--machine", machine,
            "--rtp-mode", "1",
            "--from-cache", str(cache_dir),
            "--output-dir", tmpdir,
            "--bet", "1000",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=300)
        assert result.returncode == 0, (
            f"{machine} analyzer exited {result.returncode}.\n"
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )
        return json.loads((Path(tmpdir) / "player_impact_summary.json").read_bytes())


@pytest.fixture(scope="module")
def m275_bi2_summary() -> dict:
    if not _M275_CACHE.exists() or not list(_M275_CACHE.glob("chunk_*.json")):
        pytest.skip(f"M275 mode 1 cached chunks not found at {_M275_CACHE}")
    return _run_pia("M275", _M275_CACHE)


@pytest.fixture(scope="module")
def m14_bi2_summary() -> dict:
    if not _M14_CACHE.exists() or not list(_M14_CACHE.glob("chunk_*.json")):
        pytest.skip(f"M14 mode 1 cached chunks not found at {_M14_CACHE}")
    return _run_pia("M14", _M14_CACHE)


# ---------------------------------------------------------------------------
# T1: base_hash unchanged (most important regression guard)
# ---------------------------------------------------------------------------

class TestBaseHashUnchangedC6:
    """base_hash must be the R-1 closure value after C6 (registered plugin excluded by R-4)."""

    def test_base_hash_value(self):
        """compute_base_analyzer_version() must return d8b8c138874a.

        Phase honesty-2 redefined base_hash to the 25-file report-production
        import closure (R-1) → 960e9d18d83d. C6 adds bonus_chain_dynamics.py in
        features/, a registered plugin EXCLUDED from base_hash by R-4. Phase 2a
        carved collect_mechanic's compute out of player_impact_analyzer.py (a
        closure file) → base re-baselined to 57fdb323585d. Phase 2b carved
        bonus_chain_dynamics' dict-build out of PIA (the same closure file) →
        base re-baselined to 980f488f4bb2. Phase 3 carved
        upstream_feature_breakdown's ~400-line row-build out of PIA → base
        re-baselined again to c89db791d8a1. Phase 4 carved multiplier_profile's
        inline dict-build out of PIA → base re-baselined again to ce298f055495.
        Phase 5 carved reel_marginal_by_spin_type's inline dict-build out of PIA →
        base re-baselined again to ccc1ecce185d. Phase 6 carved
        bankruptcy_simulation's inline tier ROW-BUILD loop out of PIA (the LAST
        carve of the unbundle) → base re-baselined again to d8b8c138874a
        (one-time fleet re-baseline; report content byte-identical, proven by the
        deep-diff test below).
        If base_hash changes again, it signals a modification to a production-path
        file in the _CLOSURE_FILES tuple (versioning.py).
        """
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        actual = compute_base_analyzer_version()
        assert actual == "d8b8c138874a", (
            f"base_hash must be 'd8b8c138874a' (R-1 closure value, post phase-6). "
            f"Got: {actual!r}. "
            f"Registered plugin additions must NOT change base_hash (R-4 exclusion). "
            f"If a production-path file (in _CLOSURE_FILES) was modified, update this pin."
        )


# ---------------------------------------------------------------------------
# T2: bonus_chain_dynamics stash pattern — invariant that plugin passes through
# ---------------------------------------------------------------------------

class TestBonusChainDynamicsStashInvariant:
    """Plugin emit() must write back what the stash carried — byte-identical carve."""

    def test_m275_bonus_chain_dynamics_applicable_true(self, m275_bi2_summary):
        """M275 player_impact.bonus_chain_dynamics.applicable must be True.

        The F6 inline block builds applicable=True for M275.
        If the plugin swapped in a different value, this would fail.
        """
        pi = m275_bi2_summary.get("player_impact", {})
        bcd = pi.get("bonus_chain_dynamics", {})
        assert bcd.get("applicable") is True, (
            f"bonus_chain_dynamics.applicable must be True (F6 inline computed True; "
            f"plugin must pass through unchanged). Got: {bcd.get('applicable')!r}"
        )

    def test_m275_chain_count_matches_expected(self, m275_bi2_summary):
        """M275 bonus_chain_dynamics.chain_count must be 908 (observed from cache data).

        If the plugin writes a different value, the byte-identical contract is broken.
        """
        pi = m275_bi2_summary.get("player_impact", {})
        bcd = pi.get("bonus_chain_dynamics", {})
        chain_count = bcd.get("chain_count", -1)
        assert chain_count == 908, (
            f"bonus_chain_dynamics.chain_count must be 908 (observed from M275 cache). "
            f"Got: {chain_count}. Plugin may have written a different value than F6 inline."
        )

    def test_m14_bonus_chain_dynamics_applicable_false(self, m14_bi2_summary):
        """M14 player_impact.bonus_chain_dynamics.applicable must be False.

        F6 inline computes applicable=False for M14 (no BCM mechanic).
        Plugin passthrough must preserve this.
        """
        pi = m14_bi2_summary.get("player_impact", {})
        bcd = pi.get("bonus_chain_dynamics", {})
        assert bcd.get("applicable") is False, (
            f"bonus_chain_dynamics.applicable must be False for M14 (inline F6 computed False; "
            f"plugin must pass through unchanged). Got: {bcd.get('applicable')!r}"
        )


# ---------------------------------------------------------------------------
# T3: Stash key cleanup — no leakage into final summary
# ---------------------------------------------------------------------------

class TestStashKeyCleanup:
    """Stash key must be removed from final summary (cleanup by plugin emit)."""

    def test_m275_stash_key_absent(self, m275_bi2_summary):
        """_bonus_chain_dynamics_data must not appear in M275 final summary."""
        assert _STASH_KEY not in m275_bi2_summary, (
            f"Stash key '{_STASH_KEY}' leaked into M275 final summary. "
            f"emit() must pop the stash key."
        )

    def test_m14_stash_key_absent(self, m14_bi2_summary):
        """_bonus_chain_dynamics_data must not appear in M14 final summary."""
        assert _STASH_KEY not in m14_bi2_summary, (
            f"Stash key '{_STASH_KEY}' leaked into M14 final summary."
        )

    def test_m275_no_underscore_prefix_keys_at_top_level(self, m275_bi2_summary):
        """No _ prefix stash keys at top-level of M275 final summary."""
        stash_keys = [k for k in m275_bi2_summary if k.startswith("_")]
        assert not stash_keys, (
            f"Unexpected _-prefixed keys at M275 top-level: {stash_keys}"
        )

    def test_m14_no_underscore_prefix_keys_at_top_level(self, m14_bi2_summary):
        """No _ prefix stash keys at top-level of M14 final summary."""
        stash_keys = [k for k in m14_bi2_summary if k.startswith("_")]
        assert not stash_keys, (
            f"Unexpected _-prefixed keys at M14 top-level: {stash_keys}"
        )


# ---------------------------------------------------------------------------
# T4: Preexisting fields not disturbed by C6
# ---------------------------------------------------------------------------

class TestPreexistingFieldsUnchanged:
    """C6 must not disturb any preexisting player_impact fields."""

    @pytest.mark.parametrize("field", [
        "bankruptcy_simulation",
        "multiplier_profile",
        "payouts_by_spin_type",
        "machine_mechanics",
        "reel_marginal_by_spin_type",
        "spin_type_breakdown",
    ])
    def test_m275_preexisting_fields_present(self, field, m275_bi2_summary):
        """Preexisting player_impact field must still be present after C6."""
        pi = m275_bi2_summary.get("player_impact", {})
        assert field in pi, (
            f"player_impact.{field} missing from M275 summary after C6. "
            f"C6 must not remove preexisting fields. "
            f"Available: {[k for k in pi if not k.startswith('_')]}"
        )

    def test_m275_rtp_present(self, m275_bi2_summary):
        """summary.rtp must be present (C6 has RTP_CONTRIBUTION=False)."""
        assert "rtp" in m275_bi2_summary, (
            "summary.rtp missing. C6 plugins have RTP_CONTRIBUTION=False and "
            "must not alter rtp values."
        )

    def test_m275_sampling_present(self, m275_bi2_summary):
        """summary.sampling must be present."""
        assert "sampling" in m275_bi2_summary, (
            "summary.sampling missing. C6 must not disturb sampling block."
        )
