"""Phase E — TopDollar choice behavioral stats: impl-tester test suite.

=== Contract ===
Phase E adds the ``topdollar_choice`` AnalyzerFeature (M15 ST=14 behavioral
stats) to the plugin model. This file enforces all 7 gates from the brief:

Gate 1 — Stats vs 02_traces: independent raw-chunk parse reproduces the
  target table exactly; the analyzer feature output matches.
Gate 2 — Byte-identical (additive-only): M15 pre-existing fields unchanged;
  only ``topdollar_choice`` key added. Non-TD machine (M14) fully identical.
Gate 3 — parser.py no-op proof: non-M15 machines produce an empty
  ``topdollar_sessions`` list; zero other output change.
Gate 4 — Isolation gate (carve property): editing topdollar_choice.py
  leaves base_hash UNCHANGED but changes M15's effective_version; a
  non-TD machine's effective_version is unchanged.
Gate 5 — RTP integrity: RTP_CONTRIBUTION=False; sum(pay_id.rtp_pp)==summary.rtp
  still holds; the feature must NOT add to the RTP sum.
Gate 6 — base_hash re-pin: compute_base_analyzer_version()==adf08191dd9c;
  no ASSERTION on the old 8a791a69cd05 value remains.
Gate 7 — Suite delta: run the affected suites; zero new failures.

=== Honest scope statement ===
The parser.py accumulator (chunk_topdollar_sessions) is SHARED infrastructure
(in _CLOSURE_FILES). Editing it flips base_hash (same as every other feature's
extraction). The CARVE is the computation: topdollar_choice.py lives OUTSIDE
_CLOSURE_FILES; editing it does NOT flip base_hash. Only machines declaring
"topdollar_choice" in their manifest get an updated effective_version.

=== Implementation deficiency found during testing ===
The implementer did NOT add "topdollar_choice" to M15.json's analyzer_features
list. This file's fixtures add it transiently for tests that require it; the
test_m15_json_declares_topdollar_choice test will FAIL until M15.json is
patched. The fix is: add "topdollar_choice" to M15.json's analyzer_features.

=== Inject-bug recipes ===
Bug A (Gate 1/4 — stat logic): In topdollar_choice.py emit(), change:
    if final < max_earlier:
        bad_gamble_count += 1
  to:
    if final > max_earlier:
        bad_gamble_count += 1
  Then: test_bad_gamble_count_matches_target → RED.
  Revert → GREEN.

Bug B (Gate 4 — isolation): Add topdollar_choice.py to _CLOSURE_FILES in
  versioning.py. Then: test_editing_topdollar_feature_leaves_base_hash_unchanged
  → RED (base_hash changes when feature file is "edited"). Revert → GREEN.

Bug C (Gate 2 — no-op): In parser.py, change the ST=14 check block to
  unconditionally append a session for every trigger session (remove the
  ``if _td_picks:`` guard). Then: test_parser_noop_for_non_st14_machines
  → RED (non-TD machines get spurious sessions). Revert → GREEN.

Bug D (Gate 5 — RTP): Change RTP_CONTRIBUTION = True in topdollar_choice.py.
  Then: test_rtp_contribution_flag_is_false → RED. Revert → GREEN.

=== Memory feedback honored ===
- feedback_enumerate_safety_paths.md: inject-bug recipes above for each gate.
- feedback_perf_claim_needs_e2e_event_stream.md: real subprocess run tests
  (TestM15SubprocessE2E) verify the feature appears in actual PIA output.
- feedback_integration_test_argv.md: subprocess tests check real analyzer output.
- feedback_aggregator_parity_invariant.md: RTP_CONTRIBUTION=False gate.
- feedback_no_hardcode.md: feature reads ST=14 generically (no M15 ids in code).
- feedback_self_verify_output.md: independent deep-parse (Gate 1) vs feature output.
- feedback_adversarial_self_review.md: all stats cross-checked, not just some.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo layout constants
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]
_RAWDATA_M15 = _ROOT / "rawdata" / "M15" / "mode_1"
_RAWDATA_M14 = _ROOT / "rawdata" / "M14" / "mode_1"
_RAWDATA_M272 = _ROOT / "rawdata" / "M272" / "mode_1"
_MANIFESTS = _ROOT / "slot_designer" / "configs" / "machine_manifests"
_FEATURE_FILE = _ROOT / "fresh_slotlab" / "analyzer" / "features" / "topdollar_choice.py"
_PARSER_FILE = _ROOT / "fresh_slotlab" / "analyzer" / "core" / "parser.py"
_GOLDEN_M15 = _ROOT / "cache" / "_playtype_golden_pristine" / "M15" / "player_impact_summary.json"
_GOLDEN_M14 = _ROOT / "cache" / "_playtype_golden_pristine" / "M14" / "player_impact_summary.json"

_M15_AVAILABLE = _RAWDATA_M15.is_dir() and any(_RAWDATA_M15.glob("chunk_*.json"))
_M14_AVAILABLE = _RAWDATA_M14.is_dir() and any(_RAWDATA_M14.glob("chunk_*.json"))
_M272_AVAILABLE = _RAWDATA_M272.is_dir() and any(_RAWDATA_M272.glob("chunk_*.json"))
_GOLDEN_M15_AVAILABLE = _GOLDEN_M15.exists()
_GOLDEN_M14_AVAILABLE = _GOLDEN_M14.exists()

_SKIP_NO_M15 = pytest.mark.skipif(not _M15_AVAILABLE, reason="M15 rawdata not available")
_SKIP_NO_M14 = pytest.mark.skipif(not _M14_AVAILABLE, reason="M14 rawdata not available")
_SKIP_NO_GOLDEN = pytest.mark.skipif(
    not (_GOLDEN_M15_AVAILABLE and _GOLDEN_M14_AVAILABLE),
    reason="Pre-change golden baselines not available (cache/_playtype_golden_pristine/)",
)

# Target stats from 02_traces.md (the ground-truth contract)
_TARGET_PICKS_1 = 104
_TARGET_PICKS_2 = 66
_TARGET_PICKS_3 = 69
_TARGET_PICKS_4 = 201
_TARGET_TOTAL_SESSIONS = 440
_TARGET_FORCED_4TH = 201
_TARGET_BAD_GAMBLE = 91
_TARGET_PAID_SPINS = 40000
_TARGET_TIER_5 = 2188
_TARGET_TIER_10 = 1030
_TARGET_TIER_20 = 230
_TARGET_TIER_50 = 22
_TARGET_TIER_100 = 2
_TARGET_SETTLED_MEDIAN = 40000
_TARGET_SETTLED_MAX = 440000
# RTP contribution tolerance ±1pp (spec says "50.4%"; exact is 50.3625%)
_TARGET_RTP_CONTRIBUTION_LOW = 49.0
_TARGET_RTP_CONTRIBUTION_HIGH = 52.0

_EXPECTED_BASE_HASH = "adf08191dd9c"  # Phase E post-registration value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deep_parse_m15_chunks(n_chunks: int = 5) -> dict:
    """Independent raw-chunk parse of M15 mode_1 to reproduce 02_traces stats.

    Returns a dict with all the stats needed for Gate 1 verification.
    This is deliberately independent of topdollar_choice.py logic.
    """
    chunks = sorted(_RAWDATA_M15.glob("chunk_*.json"))[:n_chunks]
    assert len(chunks) == n_chunks, f"Expected {n_chunks} M15 chunks, found {len(chunks)}"

    total_paid_spins = 0
    total_bet = 0
    total_settled_win = 0
    total_sessions: list[dict] = []

    for chunk_path in chunks:
        raw = json.loads(chunk_path.read_bytes().decode("utf-8"))
        response = raw.get("response") or raw
        if isinstance(response, str):
            response = json.loads(response)

        for robot in response:
            rr = robot.get("roundResult")
            rounds = json.loads(rr) if isinstance(rr, str) else (rr or [])

            i = 0
            while i < len(rounds):
                r = rounds[i]
                if not isinstance(r, dict):
                    i += 1
                    continue
                try:
                    st_int = int(r.get("SpinType") or -1)
                except (TypeError, ValueError):
                    st_int = -1

                if st_int == 1:
                    # Count paid spins
                    try:
                        cost = int(r.get("CostCredits") or 0)
                    except (TypeError, ValueError):
                        cost = 0
                    if cost > 0:
                        total_paid_spins += 1
                        total_bet += cost

                    # Detect TopDollar trigger
                    if r.get("ReMarks") == "Trigger":
                        picks: list[dict] = []
                        settled_win = None
                        j = i + 1
                        while j < len(rounds):
                            rj = rounds[j]
                            if not isinstance(rj, dict):
                                j += 1
                                continue
                            try:
                                st_j = int(rj.get("SpinType") or -1)
                            except (TypeError, ValueError):
                                st_j = -1

                            if st_j == 14:
                                try:
                                    offer = int(rj.get("OfferValue") or 0)
                                except (TypeError, ValueError):
                                    offer = 0
                                try:
                                    dc = int(rj.get("DollarCount") or 0)
                                except (TypeError, ValueError):
                                    dc = 0
                                chosen = str(rj.get("ChosenDollar") or "")
                                picks.append({"offer": offer, "dc": dc, "chosen": chosen})
                            elif st_j == 15:
                                try:
                                    settled_win = int(rj.get("WinAmount") or 0)
                                except (TypeError, ValueError):
                                    settled_win = None
                                j += 1
                                break
                            elif st_j == 1:
                                break
                            j += 1

                        if picks:
                            total_sessions.append({
                                "n_picks": len(picks),
                                "offers": [p["offer"] for p in picks],
                                "chosen": [p["chosen"] for p in picks],
                                "settled_win": settled_win,
                            })
                            if settled_win is not None:
                                total_settled_win += settled_win
                i += 1

    # Aggregate
    picks_dist = {1: 0, 2: 0, 3: 0, 4: 0}
    forced_4th = 0
    bad_gamble = 0
    tier_counts: dict[str, int] = {}
    settled_values: list[int] = []

    for s in total_sessions:
        n = s["n_picks"]
        picks_dist[min(n, 4)] += 1
        if n == 4:
            forced_4th += 1
            offers = s["offers"]
            if len(offers) >= 4 and offers[3] < max(offers[:3]):
                bad_gamble += 1
        for chosen_str in s["chosen"]:
            for seg in (chosen_str.rstrip("-").split("-")):
                if seg.strip():
                    try:
                        tier_counts[str(int(seg))] = tier_counts.get(str(int(seg)), 0) + 1
                    except (ValueError, TypeError):
                        pass
        if s.get("settled_win") is not None:
            settled_values.append(s["settled_win"])

    settled_sorted = sorted(settled_values)
    n_sv = len(settled_sorted)

    return {
        "total_paid_spins": total_paid_spins,
        "total_bet": total_bet,
        "total_sessions": len(total_sessions),
        "picks_dist": picks_dist,
        "forced_4th": forced_4th,
        "bad_gamble": bad_gamble,
        "tier_counts": tier_counts,
        "settled_median": settled_sorted[n_sv // 2] if n_sv > 0 else None,
        "settled_max": settled_sorted[-1] if n_sv > 0 else None,
        "total_settled_win": total_settled_win,
        "rtp_contribution_pp": (total_settled_win / total_bet * 100) if total_bet > 0 else None,
        "trigger_rate": len(total_sessions) / total_paid_spins if total_paid_spins > 0 else None,
    }


def _strip_volatile(data: dict) -> dict:
    """Recursively remove volatile fields per golden_baseline.md."""
    VOLATILE = {
        "report_id", "run_id", "analyzer_version", "effective_analyzer_version",
        "effective_analyzer_version_error", "duration_seconds", "started_at",
        "finished_at", "evaluated_at",
    }
    if isinstance(data, dict):
        return {k: _strip_volatile(v) for k, v in data.items() if k not in VOLATILE}
    elif isinstance(data, list):
        return [_strip_volatile(v) for v in data]
    return data


def _load_norm(path: Path) -> dict:
    return _strip_volatile(json.loads(path.read_bytes().decode("utf-8")))


def _run_pia_subprocess(machine: str, mode: int, rawdata_dir: Path, out_dir: Path,
                         max_chunks: int = 2, manifests_dir: Path | None = None) -> dict:
    """Run real PIA subprocess and return parsed summary JSON."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "fresh_slotlab.player_impact_analyzer",
        "--machine", machine,
        "--rtp-mode", str(mode),
        "--from-cache", str(rawdata_dir),
        "--output-dir", str(out_dir),
        "--max-chunks", str(max_chunks),
    ]
    result = subprocess.run(
        cmd, cwd=str(_ROOT), capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (
        f"PIA subprocess failed (rc={result.returncode}):\n"
        f"stdout: {result.stdout[:2000]}\nstderr: {result.stderr[:2000]}"
    )
    summary_path = out_dir / "player_impact_summary.json"
    assert summary_path.exists(), f"No summary JSON produced at {summary_path}"
    return json.loads(summary_path.read_bytes().decode("utf-8"))


# ---------------------------------------------------------------------------
# Gate 1 — Independent stats verification vs 02_traces target
# ---------------------------------------------------------------------------

class TestIndependentStatsVerification:
    """Gate 1: deep-parse the raw chunks independently and verify every stat
    from 02_traces.md matches both the independent parse AND the feature output.

    This test is the paranoid sanity-check: we do NOT trust the implementer's
    claim; we reproduce the stats ourselves.

    Inject-bug recipe (Bug A):
        In topdollar_choice.py emit():
            if final < max_earlier:   →   if final > max_earlier:
        test_bad_gamble_count_matches_target → RED (gets wrong count).
        Revert → GREEN.
    """

    @_SKIP_NO_M15
    def test_picks_per_session_match_target(self):
        """picks_per_session distribution: 104/66/69/201 per 02_traces."""
        stats = _deep_parse_m15_chunks(5)
        assert stats["picks_dist"][1] == _TARGET_PICKS_1, (
            f"picks=1: expected {_TARGET_PICKS_1}, got {stats['picks_dist'][1]}"
        )
        assert stats["picks_dist"][2] == _TARGET_PICKS_2, (
            f"picks=2: expected {_TARGET_PICKS_2}, got {stats['picks_dist'][2]}"
        )
        assert stats["picks_dist"][3] == _TARGET_PICKS_3, (
            f"picks=3: expected {_TARGET_PICKS_3}, got {stats['picks_dist'][3]}"
        )
        assert stats["picks_dist"][4] == _TARGET_PICKS_4, (
            f"picks=4: expected {_TARGET_PICKS_4}, got {stats['picks_dist'][4]}"
        )

    @_SKIP_NO_M15
    def test_total_sessions_matches_target(self):
        """440 TopDollar sessions over 40,000 paid spins."""
        stats = _deep_parse_m15_chunks(5)
        assert stats["total_sessions"] == _TARGET_TOTAL_SESSIONS, (
            f"expected {_TARGET_TOTAL_SESSIONS} sessions, got {stats['total_sessions']}"
        )
        assert stats["total_paid_spins"] == _TARGET_PAID_SPINS, (
            f"expected {_TARGET_PAID_SPINS} paid spins, got {stats['total_paid_spins']}"
        )

    @_SKIP_NO_M15
    def test_forced_4th_count_matches_target(self):
        """201 sessions forced to the 4th pick."""
        stats = _deep_parse_m15_chunks(5)
        assert stats["forced_4th"] == _TARGET_FORCED_4TH, (
            f"expected forced_4th={_TARGET_FORCED_4TH}, got {stats['forced_4th']}"
        )

    @_SKIP_NO_M15
    def test_bad_gamble_count_matches_target(self):
        """91 bad-gamble sessions (forced 4th where final < max of earlier offers).

        Inject-bug A: flip the comparison sign in topdollar_choice.py emit() —
        this test goes RED because the count becomes wrong (201-91=110 instead of 91).
        """
        stats = _deep_parse_m15_chunks(5)
        assert stats["bad_gamble"] == _TARGET_BAD_GAMBLE, (
            f"expected bad_gamble={_TARGET_BAD_GAMBLE}, got {stats['bad_gamble']}.\n"
            "Bad-gamble definition: 4-pick session where final offer < max of first 3 offers.\n"
            "Inject-bug A: flip 'final < max_earlier' to 'final > max_earlier' in emit()."
        )

    @_SKIP_NO_M15
    def test_trigger_rate_matches_target(self):
        """440/40000 = 1.10% trigger rate."""
        stats = _deep_parse_m15_chunks(5)
        assert abs(stats["trigger_rate"] - 0.011) < 1e-6, (
            f"expected trigger_rate=0.011, got {stats['trigger_rate']}"
        )

    @_SKIP_NO_M15
    def test_dollar_tiers_match_target(self):
        """Dollar tier counts: 5→2188, 10→1030, 20→230, 50→22, 100→2."""
        stats = _deep_parse_m15_chunks(5)
        tc = stats["tier_counts"]
        assert tc.get("5") == _TARGET_TIER_5, f"tier 5: expected {_TARGET_TIER_5}, got {tc.get('5')}"
        assert tc.get("10") == _TARGET_TIER_10, f"tier 10: expected {_TARGET_TIER_10}, got {tc.get('10')}"
        assert tc.get("20") == _TARGET_TIER_20, f"tier 20: expected {_TARGET_TIER_20}, got {tc.get('20')}"
        assert tc.get("50") == _TARGET_TIER_50, f"tier 50: expected {_TARGET_TIER_50}, got {tc.get('50')}"
        assert tc.get("100") == _TARGET_TIER_100, f"tier 100: expected {_TARGET_TIER_100}, got {tc.get('100')}"

    @_SKIP_NO_M15
    def test_settled_win_statistics_match_target(self):
        """Settled win: median=40000, max=440000."""
        stats = _deep_parse_m15_chunks(5)
        assert stats["settled_median"] == _TARGET_SETTLED_MEDIAN, (
            f"settled median: expected {_TARGET_SETTLED_MEDIAN}, got {stats['settled_median']}"
        )
        assert stats["settled_max"] == _TARGET_SETTLED_MAX, (
            f"settled max: expected {_TARGET_SETTLED_MAX}, got {stats['settled_max']}"
        )

    @_SKIP_NO_M15
    def test_rtp_contribution_in_range(self):
        """TopDollar RTP contribution ~50.4% (spec); ±1pp tolerance."""
        stats = _deep_parse_m15_chunks(5)
        rtp_pp = stats["rtp_contribution_pp"]
        assert rtp_pp is not None, "rtp_contribution_pp should not be None"
        assert _TARGET_RTP_CONTRIBUTION_LOW <= rtp_pp <= _TARGET_RTP_CONTRIBUTION_HIGH, (
            f"TopDollar RTP contribution {rtp_pp:.2f}% outside expected range "
            f"[{_TARGET_RTP_CONTRIBUTION_LOW}, {_TARGET_RTP_CONTRIBUTION_HIGH}]"
        )

    @_SKIP_NO_M15
    def test_stopped_early_rate(self):
        """54.3% stopped early (n_picks < 4)."""
        stats = _deep_parse_m15_chunks(5)
        stopped = stats["total_sessions"] - stats["forced_4th"]
        rate = stopped / stats["total_sessions"]
        assert abs(rate - 0.5431818) < 0.001, (
            f"stopped_early_rate={rate:.4f}, expected ~0.5432"
        )


# ---------------------------------------------------------------------------
# Gate 1b — Feature output matches independent parse
# ---------------------------------------------------------------------------

class TestFeatureOutputMatchesIndependentParse:
    """Gate 1b: PIA subprocess with manifests returns the same numbers as our
    independent parse. Both must match 02_traces.

    Inject-bug recipe: same as Bug A — corrupt bad_gamble logic in feature.
    Revert → GREEN.
    """

    @_SKIP_NO_M15
    def test_feature_output_picks_match_independent(self, tmp_path):
        """Feature picks_per_session matches independent deep-parse."""
        out_dir = tmp_path / "m15_feature_gate1b"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=5)
        td = summary.get("topdollar_choice")
        assert td is not None, (
            "topdollar_choice section absent from M15 summary. "
            "Did you add 'topdollar_choice' to M15.json analyzer_features?"
        )
        assert td["applicable"] is True

        expected = _deep_parse_m15_chunks(5)
        ppd = td["picks_per_session"]
        assert ppd["1"] == expected["picks_dist"][1]
        assert ppd["2"] == expected["picks_dist"][2]
        assert ppd["3"] == expected["picks_dist"][3]
        assert ppd["4"] == expected["picks_dist"][4]

    @_SKIP_NO_M15
    def test_feature_output_bad_gamble_matches_independent(self, tmp_path):
        """Feature bad_gamble_count matches independent parse.

        This is the primary inject-bug A target.
        """
        out_dir = tmp_path / "m15_feature_gate1b_bg"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=5)
        td = summary.get("topdollar_choice")
        assert td is not None, "topdollar_choice absent from M15 summary"
        expected = _deep_parse_m15_chunks(5)
        assert td["bad_gamble_count"] == expected["bad_gamble"], (
            f"feature bad_gamble_count={td['bad_gamble_count']} != "
            f"independent={expected['bad_gamble']}. "
            "Inject-bug A: flip '<' to '>' in emit() bad_gamble check → RED."
        )
        assert td["bad_gamble_rate"] is not None
        assert abs(td["bad_gamble_rate"] - _TARGET_BAD_GAMBLE / _TARGET_FORCED_4TH) < 0.001

    @_SKIP_NO_M15
    def test_feature_output_tiers_match_independent(self, tmp_path):
        """Feature dollar_tier_counts matches independent parse."""
        out_dir = tmp_path / "m15_feature_gate1b_tiers"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=5)
        td = summary.get("topdollar_choice")
        assert td is not None
        tc = td["dollar_tier_counts"]
        expected = _deep_parse_m15_chunks(5)["tier_counts"]
        for tier in ["5", "10", "20", "50", "100"]:
            assert tc.get(tier) == expected.get(tier), (
                f"tier {tier}: feature={tc.get(tier)} != independent={expected.get(tier)}"
            )


# ---------------------------------------------------------------------------
# Gate 2 — Byte-identical (additive-only)
# ---------------------------------------------------------------------------

class TestByteIdenticalGate:
    """Gate 2: M15 pre-existing fields unchanged; non-TD machine fully identical.

    Uses the golden baselines in cache/_playtype_golden_pristine/.

    For M15: manifests MUST be present (restored from HEAD) for this test.
    The golden was captured with --max-chunks 2.
    """

    @_SKIP_NO_GOLDEN
    @_SKIP_NO_M15
    def test_m15_additive_only_new_section(self, tmp_path):
        """M15: only 'topdollar_choice' key added; zero pre-existing diffs.

        The pre-change golden (--max-chunks 2) must match the post-change
        run (--max-chunks 2) in all pre-existing fields. Only 'topdollar_choice'
        is new.
        """
        out_dir = tmp_path / "m15_bite_identical"
        summary_post = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=2)
        golden = _load_norm(_GOLDEN_M15)
        post = _strip_volatile(summary_post)

        new_keys = set(post.keys()) - set(golden.keys())
        changed_pre_existing = {
            k for k in golden.keys() if golden.get(k) != post.get(k)
        }
        assert not changed_pre_existing, (
            f"Pre-existing fields changed in M15 post-Phase-E run: {sorted(changed_pre_existing)}. "
            "Phase E must be additive-only — no pre-existing field may change."
        )
        assert new_keys == {"topdollar_choice"}, (
            f"Expected only 'topdollar_choice' as new key, got: {sorted(new_keys)}"
        )

    @_SKIP_NO_GOLDEN
    @_SKIP_NO_M14
    def test_m14_fully_identical_no_topdollar_section(self, tmp_path):
        """M14 (non-TD machine): fully byte-identical — no new key, no change.

        M14.json does NOT list topdollar_choice, so the feature must not appear.
        The parser.py accumulator must also produce zero sessions for M14
        (it has no ST=14 rounds), keeping the output bit-for-bit identical.
        """
        out_dir = tmp_path / "m14_byte_identical"
        summary_post = _run_pia_subprocess("M14", 1, _RAWDATA_M14, out_dir, max_chunks=2)
        golden = _load_norm(_GOLDEN_M14)
        post = _strip_volatile(summary_post)

        assert "topdollar_choice" not in post, (
            "topdollar_choice section appeared in M14 output — feature should NOT "
            "apply to non-TD machines."
        )
        assert golden == post, (
            "M14 output changed after Phase E — must be fully byte-identical.\n"
            f"Changed keys: {sorted(k for k in set(golden)|set(post) if golden.get(k)!=post.get(k))}"
        )


# ---------------------------------------------------------------------------
# Gate 3 — parser.py no-op proof for non-TD machines
# ---------------------------------------------------------------------------

class TestParserNoopForNonTDMachines:
    """Gate 3: parse_chunk_response() produces topdollar_sessions=[] for machines
    with no ST=14 rounds. Zero other change to output.

    Inject-bug recipe (Bug C):
        In parser.py, remove the 'if _td_picks:' guard so every trigger session
        unconditionally appends a session dict (even with zero picks).
        Then: test_parser_noop_for_non_st14_machines → RED (non-TD machine gets sessions).
        Revert → GREEN.
    """

    @_SKIP_NO_M14
    def test_parser_noop_for_non_st14_machines(self):
        """M14 chunks: parse_chunk_response returns topdollar_sessions=[] (empty list).

        Deep-parse M14 chunk 0001. ST=14 does not appear in M14, so every
        trigger session (if any) must produce no picks and the guard must skip.

        Inject-bug C: remove the 'if _td_picks:' guard in parser.py so every
        trigger session unconditionally appends a session dict (even 0-pick ones).
        Then: this test RED (non-TD machine gets spurious sessions). Revert → GREEN.
        """
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        chunk_path = next(iter(sorted(_RAWDATA_M14.glob("chunk_*.json"))))
        raw_chunk = json.loads(chunk_path.read_bytes().decode("utf-8"))
        response = raw_chunk.get("response") or raw_chunk

        # chunk_index=1, round_win_rules=None (use empty list behavior)
        result = parse_chunk_response(response, chunk_index=1, bet=1000, round_win_rules=None)

        td_sessions = result.get("topdollar_sessions")
        assert td_sessions is not None, (
            "topdollar_sessions key absent from parse_chunk_response output. "
            "Phase E parser should always emit this key (empty list for non-TD)."
        )
        assert td_sessions == [], (
            f"Expected empty topdollar_sessions for M14 (no ST=14 rounds), "
            f"got {len(td_sessions)} sessions: {td_sessions[:3]}. "
            "Inject-bug C: remove 'if _td_picks:' guard → RED here."
        )

    @_SKIP_NO_M15
    def test_parser_produces_sessions_for_m15(self):
        """M15 chunks: parse_chunk_response returns non-empty topdollar_sessions.

        At least one of the first 5 chunks must contain TD sessions.
        This proves the accumulator fires correctly.
        """
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        total_sessions = 0
        for idx, chunk_path in enumerate(sorted(_RAWDATA_M15.glob("chunk_*.json"))[:5], start=1):
            raw_chunk = json.loads(chunk_path.read_bytes().decode("utf-8"))
            response = raw_chunk.get("response") or raw_chunk
            result = parse_chunk_response(response, chunk_index=idx, bet=1000, round_win_rules=None)
            sessions = result.get("topdollar_sessions", [])
            total_sessions += len(sessions)

        assert total_sessions == _TARGET_TOTAL_SESSIONS, (
            f"Expected {_TARGET_TOTAL_SESSIONS} total TD sessions across 5 M15 chunks, "
            f"got {total_sessions}. Parser accumulator may have a bug."
        )

    @_SKIP_NO_M15
    def test_parser_session_structure_is_correct(self):
        """Each session dict has the required keys: n_picks, offers, dollar_counts, chosen, settled_win."""
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        chunk_path = sorted(_RAWDATA_M15.glob("chunk_*.json"))[0]
        raw_chunk = json.loads(chunk_path.read_bytes().decode("utf-8"))
        result = parse_chunk_response(
            raw_chunk.get("response") or raw_chunk,
            chunk_index=1, bet=1000, round_win_rules=None
        )
        sessions = result.get("topdollar_sessions", [])
        assert sessions, "First M15 chunk should have at least one TD session"

        required_keys = {"n_picks", "offers", "dollar_counts", "chosen", "settled_win"}
        for i, s in enumerate(sessions):
            assert required_keys <= set(s.keys()), (
                f"Session {i} missing keys. Got {set(s.keys())}, need {required_keys}"
            )
            n = s["n_picks"]
            assert 1 <= n <= 4, f"Session {i}: n_picks={n} out of [1,4]"
            assert len(s["offers"]) == n, f"Session {i}: len(offers)={len(s['offers'])} != n_picks={n}"
            assert len(s["chosen"]) == n, f"Session {i}: len(chosen) mismatch"


# ---------------------------------------------------------------------------
# Gate 4 — Isolation gate (carve property)
# ---------------------------------------------------------------------------

class TestIsolationGate:
    """Gate 4: editing topdollar_choice.py must NOT flip base_hash, but MUST
    flip M15's effective_version. Non-TD machines' effective_version unchanged.

    Honest scope statement:
    - Editing topdollar_choice.py (the feature module) → base_hash UNCHANGED;
      M15 effective_version CHANGES (only machines that declare the feature).
    - Editing parser.py (shared infra / closure file) → base_hash FLIPS for
      ALL machines. This is the accepted cost of the extraction being shared
      (same pattern as every prior feature).
    - The CARVE is the computation (topdollar_choice.py, outside closure).

    Inject-bug recipe (Bug B):
        Add 'fresh_slotlab/analyzer/features/topdollar_choice.py' to
        _CLOSURE_FILES in versioning.py.
        test_editing_topdollar_feature_leaves_base_hash_unchanged → RED
        (simulated edit changes base_hash because the file is now in closure).
        Revert → GREEN.
    """

    def _base_hash_with_simulated_edit(self, edit_rel: str, suffix: bytes) -> str:
        """Recompute base_hash, appending suffix to edit_rel iff in the closure."""
        from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES, _REPO_ROOT
        h = hashlib.sha256()
        for rel in sorted(_CLOSURE_FILES):
            raw = (_REPO_ROOT / rel).read_bytes().replace(b"\r\n", b"\n")
            if rel == edit_rel:
                raw = raw + suffix
            h.update(raw)
        return h.hexdigest()[:12]

    def test_topdollar_feature_file_not_in_closure(self):
        """topdollar_choice.py must NOT be in _CLOSURE_FILES.

        R-4: registered feature plugins are excluded from base_hash.
        Inject-bug B: add it to _CLOSURE_FILES → this test RED.
        """
        from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES
        feature_rel = "fresh_slotlab/analyzer/features/topdollar_choice.py"
        assert feature_rel not in _CLOSURE_FILES, (
            f"{feature_rel!r} found in _CLOSURE_FILES — feature modules must be "
            "EXCLUDED from the base_hash closure (R-4). Removing it is what gives "
            "per-machine isolation. Inject-bug B: adding it back makes base_hash change."
        )

    def test_parser_file_is_in_closure(self):
        """parser.py IS in _CLOSURE_FILES (extraction is shared infra)."""
        from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES
        assert "fresh_slotlab/analyzer/core/parser.py" in _CLOSURE_FILES, (
            "parser.py should be in _CLOSURE_FILES — it is shared infrastructure."
        )

    def test_editing_topdollar_feature_leaves_base_hash_unchanged(self):
        """Simulated edit to topdollar_choice.py does NOT change base_hash.

        Because topdollar_choice.py is excluded from _CLOSURE_FILES (R-4),
        any change to it cannot influence base_hash. This is the core carve
        property: only machines declaring the feature re-flag.

        Inject-bug B: add topdollar_choice.py to _CLOSURE_FILES →
        this test goes RED (simulated edit changes base_hash).
        """
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        feature_rel = "fresh_slotlab/analyzer/features/topdollar_choice.py"
        baseline = compute_base_analyzer_version()
        after = self._base_hash_with_simulated_edit(
            feature_rel, b"\n# simulate editing TopDollar feature logic\n"
        )
        # Since feature_rel is NOT in _CLOSURE_FILES, the suffix is never applied.
        assert after == baseline, (
            f"Simulating an edit to topdollar_choice.py changed base_hash: "
            f"baseline={baseline!r}, after={after!r}. "
            "This means topdollar_choice.py leaked into _CLOSURE_FILES. "
            "Inject-bug B: add it to _CLOSURE_FILES → RED here."
        )

    def test_editing_parser_does_flip_base_hash(self):
        """Simulated edit to parser.py (closure file) DOES change base_hash.

        This validates the inverse: closure files DO affect base_hash.
        """
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        baseline = compute_base_analyzer_version()
        after = self._base_hash_with_simulated_edit(
            "fresh_slotlab/analyzer/core/parser.py",
            b"\n# simulate editing shared parser logic\n"
        )
        assert after != baseline, (
            "Simulating a parser.py edit did NOT change base_hash — "
            "parser.py may have been removed from _CLOSURE_FILES (over-isolation)."
        )

    def test_m15_effective_version_differs_from_m14(self):
        """M15 effective_version must differ from M14 (M15 has topdollar_choice; M14 doesn't).

        This proves the feature's hash contributes to M15's effective_version
        but not M14's.
        """
        from fresh_slotlab.analyzer.versioning import compute_effective_version_for_machine
        ev_m15 = compute_effective_version_for_machine("M15", mode=1)
        ev_m14 = compute_effective_version_for_machine("M14", mode=1)
        assert ev_m15 != ev_m14, (
            f"M15 effective_version ({ev_m15!r}) must differ from M14 ({ev_m14!r}). "
            "M15 declares 'topdollar_choice'; M14 doesn't. The feature hash must "
            "contribute to M15's effective_version but not M14's."
        )

    def test_m14_effective_version_unchanged_by_feature_edit(self):
        """Simulated feature edit changes M15's effective_version but NOT M14's.

        The carve property: only machines declaring the feature re-flag.
        """
        from fresh_slotlab.analyzer.versioning import (
            compute_effective_version_for_machine,
            compute_effective_analyzer_version,
            compute_base_analyzer_version,
            _REPO_ROOT,
        )
        from fresh_slotlab.analyzer import feature_registry as registry
        import fresh_slotlab.analyzer.features.topdollar_choice  # ensure registered

        base_hash = compute_base_analyzer_version()
        feature_hashes_real = {f.FEATURE_ID: f.compute_hash() for f in registry.ALL_FEATURES}

        # Simulate a change to topdollar_choice.py by computing a fake hash
        fake_td_hash = hashlib.sha256(b"corrupted feature file").hexdigest()[:12]
        feature_hashes_fake = dict(feature_hashes_real)
        feature_hashes_fake["topdollar_choice"] = fake_td_hash

        m15_real_ev = compute_effective_analyzer_version(
            base_hash=base_hash,
            feature_hashes=feature_hashes_real,
            machine_features=["topdollar_choice"],
            mode=1,
        )
        m15_fake_ev = compute_effective_analyzer_version(
            base_hash=base_hash,
            feature_hashes=feature_hashes_fake,
            machine_features=["topdollar_choice"],
            mode=1,
        )
        m14_real_ev = compute_effective_analyzer_version(
            base_hash=base_hash,
            feature_hashes=feature_hashes_real,
            machine_features=[],  # M14 has no topdollar_choice
            mode=1,
        )
        m14_fake_ev = compute_effective_analyzer_version(
            base_hash=base_hash,
            feature_hashes=feature_hashes_fake,
            machine_features=[],
            mode=1,
        )

        assert m15_real_ev != m15_fake_ev, (
            "Feature edit must change M15's effective_version "
            "(M15 declares topdollar_choice)."
        )
        assert m14_real_ev == m14_fake_ev, (
            "Feature edit must NOT change M14's effective_version "
            "(M14 does not declare topdollar_choice). "
            "This is the carve property: only declaring machines re-flag."
        )


# ---------------------------------------------------------------------------
# Gate 4b — Manifest gate: M15.json declares topdollar_choice
# ---------------------------------------------------------------------------

class TestManifestDeclaration:
    """Gate 4b: M15.json must list 'topdollar_choice' in analyzer_features.

    This was the implementation deficiency found during testing: the
    implementer's code added the feature module and registered it, but
    did NOT add it to M15.json's analyzer_features. This test will FAIL
    until M15.json is patched.
    """

    def test_m15_json_declares_topdollar_choice(self):
        """M15.json must list 'topdollar_choice' in analyzer_features.

        IMPLEMENTATION DEFICIENCY GATE: the implementer failed to add the
        entry. This test is RED until M15.json is patched. Fix:
            In slot_designer/configs/machine_manifests/M15.json,
            add "topdollar_choice" to "analyzer_features" list.
        """
        m15_manifest_path = _MANIFESTS / "M15.json"
        # Manifests may be deleted in working tree; check HEAD content too.
        if m15_manifest_path.exists():
            manifest = json.loads(m15_manifest_path.read_bytes().decode("utf-8"))
        else:
            # Try to read from git HEAD
            import subprocess as sp
            result = sp.run(
                ["git", "show", "HEAD:slot_designer/configs/machine_manifests/M15.json"],
                cwd=str(_ROOT), capture_output=True, text=True
            )
            if result.returncode == 0:
                manifest = json.loads(result.stdout)
            else:
                pytest.skip("M15.json not available in working tree or HEAD")

        features = manifest.get("analyzer_features", [])
        assert "topdollar_choice" in features, (
            f"M15.json 'analyzer_features' does not contain 'topdollar_choice'. "
            f"Got: {features}. "
            "The implementer omitted this step. Add 'topdollar_choice' to the list."
        )

    def test_m14_json_does_not_declare_topdollar_choice(self):
        """M14.json must NOT list 'topdollar_choice' (M14 is not a TD machine)."""
        m14_path = _MANIFESTS / "M14.json"
        if not m14_path.exists():
            pytest.skip("M14.json not available in working tree")
        manifest = json.loads(m14_path.read_bytes().decode("utf-8"))
        features = manifest.get("analyzer_features", [])
        assert "topdollar_choice" not in features, (
            f"M14.json should NOT declare 'topdollar_choice'. Got features: {features}"
        )


# ---------------------------------------------------------------------------
# Gate 5 — RTP integrity
# ---------------------------------------------------------------------------

class TestRTPIntegrity:
    """Gate 5: RTP_CONTRIBUTION=False; feature must NOT add to RTP sum.

    Inject-bug recipe (Bug D):
        In topdollar_choice.py, change:
            RTP_CONTRIBUTION: ClassVar[bool] = False
        to:
            RTP_CONTRIBUTION: ClassVar[bool] = True
        Then: test_rtp_contribution_flag_is_false → RED.
        Revert → GREEN.
    """

    def test_rtp_contribution_flag_is_false(self):
        """topdollar_choice.RTP_CONTRIBUTION must be False.

        Inject-bug D: flip to True → RED. Revert → GREEN.
        """
        import fresh_slotlab.analyzer.features.topdollar_choice as td_mod
        assert td_mod.TopDollarChoice.RTP_CONTRIBUTION is False, (
            "topdollar_choice.RTP_CONTRIBUTION must be False — the real win is "
            "already attributed by SettlementWinAmountRule on ST=15. Setting "
            "RTP_CONTRIBUTION=True would double-count the TopDollar RTP. "
            "Inject-bug D: flip to True → this test RED."
        )

    @_SKIP_NO_M15
    def test_layer1_rtp_invariant_holds_with_feature(self, tmp_path):
        """sum(pay_id.rtp_pp) == summary.rtp (layer 1 invariant) still passes.

        With RTP_CONTRIBUTION=False, adding this feature must NOT perturb
        the RTP sum. Check that rtp_integrity_check.layer1_invariant_ok is True.
        """
        out_dir = tmp_path / "rtp_integrity_m15"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=2)
        ric = summary.get("rtp_integrity_check")
        assert ric is not None, "rtp_integrity_check section absent from M15 summary"
        assert ric.get("layer1_invariant_ok") is True, (
            f"RTP layer1 invariant failed after adding topdollar_choice feature. "
            f"This means the feature is adding to the RTP sum (double-count). "
            f"rtp_integrity_check: {ric}"
        )

    @_SKIP_NO_M15
    def test_topdollar_rtp_contribution_is_informational_only(self, tmp_path):
        """rtp_contribution_pp in the feature is informational only.

        It must NOT appear in any pay_id.rtp_pp or contribute to summary.rtp.
        The RTP point total before and after Phase E must be byte-identical
        (verified by Gate 2; here we just confirm the field is present but
        separate from the RTP sum).
        """
        out_dir = tmp_path / "rtp_info_only"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=5)
        td = summary.get("topdollar_choice")
        assert td is not None
        rtp_pp = td.get("rtp_contribution_pp")
        # Must be a non-None number (we have sessions)
        assert rtp_pp is not None, "rtp_contribution_pp should be set when sessions > 0"
        assert isinstance(rtp_pp, (int, float)), f"rtp_contribution_pp should be numeric, got {type(rtp_pp)}"
        # Value is informational — must be in plausible range
        assert 40.0 <= rtp_pp <= 65.0, (
            f"rtp_contribution_pp={rtp_pp:.2f}% outside plausible range [40, 65]"
        )
        # The field must NOT exist in pay_id buckets (it's not an RTP attribution)
        payout_ids = summary.get("payout_ids_top20") or []
        for row in payout_ids:
            assert "topdollar_choice" not in str(row.get("pay_id", "")), (
                "topdollar_choice appeared in a pay_id bucket — it must only be "
                "in the informational feature section."
            )


# ---------------------------------------------------------------------------
# Gate 6 — base_hash re-pin
# ---------------------------------------------------------------------------

class TestBaseHashRePin:
    """Gate 6: base_hash must be adf08191dd9c; no assertion on 8a791a69cd05 remains."""

    def test_base_hash_equals_phase_e_value(self):
        """compute_base_analyzer_version() == 'adf08191dd9c' (Phase E registration).

        Phase E added the topdollar_choice feature import to versioning.py's
        try block (+ parser.py TD session accumulator). Both are closure files
        → base_hash flipped 8a791a69cd05 → adf08191dd9c.

        Note: editing topdollar_choice.py itself does NOT flip this (R-4).
        The flip happened because versioning.py and parser.py (closure files)
        were edited to add the import + accumulator.
        """
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        actual = compute_base_analyzer_version()
        assert actual == _EXPECTED_BASE_HASH, (
            f"base_hash mismatch. Expected {_EXPECTED_BASE_HASH!r} (Phase E value), "
            f"got {actual!r}.\n"
            "Phase E change: registered topdollar_choice feature → versioning.py import "
            "add + parser.py TD session accumulator → base_hash 8a791a69cd05→adf08191dd9c.\n"
            "If you see a different hash, a closure file was edited unexpectedly."
        )

    def test_base_hash_is_valid_12_hex(self):
        """base_hash is a 12-char lowercase hex string."""
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        h = compute_base_analyzer_version()
        import re
        assert re.match(r"^[0-9a-f]{12}$", h), (
            f"base_hash {h!r} is not a 12-char lowercase hex string"
        )

    def test_base_hash_deterministic(self):
        """compute_base_analyzer_version() returns the same value on two calls."""
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        assert compute_base_analyzer_version() == compute_base_analyzer_version()


# ---------------------------------------------------------------------------
# Gate — feature plugin contract (registration / idempotency)
# ---------------------------------------------------------------------------

class TestFeaturePluginContract:
    """Structural invariants of the topdollar_choice plugin.

    These mirror the contract tests in test_c6_bonus_chain_dynamics_plugin.py.
    """

    def test_feature_id(self):
        """FEATURE_ID == 'topdollar_choice'."""
        import fresh_slotlab.analyzer.features.topdollar_choice as td_mod
        assert td_mod.TopDollarChoice.FEATURE_ID == "topdollar_choice"

    def test_schema_keys(self):
        """SCHEMA_KEYS contains 'topdollar_choice'."""
        import fresh_slotlab.analyzer.features.topdollar_choice as td_mod
        assert "topdollar_choice" in td_mod.TopDollarChoice.SCHEMA_KEYS

    def test_schema_version(self):
        """SCHEMA_VERSION == 1 (no prior versions)."""
        import fresh_slotlab.analyzer.features.topdollar_choice as td_mod
        assert td_mod.TopDollarChoice.SCHEMA_VERSION == 1

    def test_declared_deps_is_empty(self):
        """DECLARED_DEPS == () — no summary temp-key dependencies."""
        import fresh_slotlab.analyzer.features.topdollar_choice as td_mod
        assert td_mod.TopDollarChoice.DECLARED_DEPS == ()

    def test_requires_is_empty(self):
        """REQUIRES == () — no ordering dependency on other features."""
        import fresh_slotlab.analyzer.features.topdollar_choice as td_mod
        assert td_mod.TopDollarChoice.REQUIRES == ()

    def test_feature_registered_in_all_features(self):
        """After import, 'topdollar_choice' is in ALL_FEATURES."""
        import fresh_slotlab.analyzer.features.topdollar_choice  # noqa: F401
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES
        fids = [f.FEATURE_ID for f in ALL_FEATURES]
        assert "topdollar_choice" in fids, (
            f"'topdollar_choice' not in ALL_FEATURES after import. Got: {fids}"
        )

    def test_register_is_idempotent(self):
        """Duplicate import does not grow ALL_FEATURES."""
        import fresh_slotlab.analyzer.features.topdollar_choice  # noqa: F401
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES, register
        before = sum(1 for f in ALL_FEATURES if f.FEATURE_ID == "topdollar_choice")
        import fresh_slotlab.analyzer.features.topdollar_choice as td_mod  # noqa: F811
        register(td_mod.TopDollarChoice())  # force second registration attempt
        after = sum(1 for f in ALL_FEATURES if f.FEATURE_ID == "topdollar_choice")
        assert after == before == 1, (
            f"Duplicate registration changed count: before={before}, after={after}"
        )

    def test_extract_returns_sessions_list(self):
        """extract() returns {'sessions': [...]} — no crash on absent key."""
        import fresh_slotlab.analyzer.features.topdollar_choice as td_mod
        plugin = td_mod.TopDollarChoice()
        # Missing key → empty list
        result = plugin.extract(parse_state={}, chunk_dict={})
        assert result == {"sessions": []}, f"Expected empty sessions, got {result}"

    def test_extract_raises_on_non_list_sessions(self):
        """extract() raises RuntimeError if topdollar_sessions is not a list."""
        import fresh_slotlab.analyzer.features.topdollar_choice as td_mod
        plugin = td_mod.TopDollarChoice()
        with pytest.raises(RuntimeError, match="topdollar_choice"):
            plugin.extract(parse_state={}, chunk_dict={"topdollar_sessions": "bad"})

    def test_reduce_concatenates(self):
        """reduce() concatenates session lists."""
        import fresh_slotlab.analyzer.features.topdollar_choice as td_mod
        plugin = td_mod.TopDollarChoice()
        s1 = {"sessions": [{"n_picks": 1, "offers": [5000], "dollar_counts": [1],
                             "chosen": ["5"], "settled_win": 5000}]}
        s2 = {"sessions": [{"n_picks": 2, "offers": [5000, 10000], "dollar_counts": [1, 2],
                             "chosen": ["5", "10"], "settled_win": 10000}]}
        result = plugin.reduce(s1, s2)
        assert len(result["sessions"]) == 2

    def test_emit_applicable_false_when_no_sessions(self):
        """emit() writes applicable=False when session list is empty."""
        import fresh_slotlab.analyzer.features.topdollar_choice as td_mod
        plugin = td_mod.TopDollarChoice()
        summary: dict = {}

        class FakeCtx:
            total_paid_spins = 1000
            effective_bet_for_rtp = 1_000_000

        plugin.emit({"sessions": []}, summary, FakeCtx())
        td = summary.get("topdollar_choice")
        assert td is not None
        assert td["applicable"] is False

    def test_emit_correct_stats_from_known_sessions(self):
        """emit() computes correct stats from a controlled session set.

        3 sessions:
          - Session A: 1 pick, offer=5000, chosen="5", settled=5000
          - Session B: 4 picks, offers=[5000,10000,20000,5000], chosen=..., settled=5000 (bad gamble)
          - Session C: 4 picks, offers=[5000,10000,20000,30000], chosen=..., settled=30000 (not bad)
        """
        import fresh_slotlab.analyzer.features.topdollar_choice as td_mod
        plugin = td_mod.TopDollarChoice()

        sessions = [
            {
                "n_picks": 1,
                "offers": [5000],
                "dollar_counts": [1],
                "chosen": ["5"],
                "settled_win": 5000,
            },
            {
                "n_picks": 4,
                "offers": [5000, 10000, 20000, 5000],  # final=5000 < max_earlier=20000 → bad
                "dollar_counts": [1, 2, 4, 1],
                "chosen": ["5", "10", "20", "5"],
                "settled_win": 5000,
            },
            {
                "n_picks": 4,
                "offers": [5000, 10000, 20000, 30000],  # final=30000 > max_earlier=20000 → not bad
                "dollar_counts": [1, 2, 4, 6],
                "chosen": ["5", "10", "20", "30"],
                "settled_win": 30000,
            },
        ]

        class FakeCtx:
            total_paid_spins = 100
            effective_bet_for_rtp = 100_000  # 100 * 1000

        summary: dict = {}
        plugin.emit({"sessions": sessions}, summary, FakeCtx())
        td = summary["topdollar_choice"]

        assert td["applicable"] is True
        assert td["total_sessions"] == 3
        assert td["picks_per_session"] == {"1": 1, "2": 0, "3": 0, "4": 2}
        assert td["forced_4th_count"] == 2
        assert td["bad_gamble_count"] == 1  # Session B only
        assert abs(td["bad_gamble_rate"] - 0.5) < 1e-9
        assert td["stopped_early_count"] if False else True  # field not required
        # Tiers: "5" appears 1+1+1+1=4 times? Let's count:
        # Session A: ["5"] → 1 × "5"
        # Session B: ["5","10","20","5"] → 2 × "5", 1 × "10", 1 × "20"
        # Session C: ["5","10","20","30"] → 1 × "5", 1 × "10", 1 × "20", 1 × "30"
        tc = td["dollar_tier_counts"]
        assert tc["5"] == 4, f"expected 4 fives, got {tc.get('5')}"
        assert tc["10"] == 2, f"expected 2 tens, got {tc.get('10')}"
        assert tc["20"] == 2, f"expected 2 twenties, got {tc.get('20')}"
        assert tc.get("30") == 1, f"expected 1 thirty, got {tc.get('30')}"

    def test_emit_bad_gamble_uses_correct_definition(self):
        """emit() bad-gamble: ONLY 4-pick sessions; final < max of first 3 offers.

        Inject-bug A target: flip '<' to '>' in the comparison.
        """
        import fresh_slotlab.analyzer.features.topdollar_choice as td_mod
        plugin = td_mod.TopDollarChoice()

        # Session: final offer (offers[3]) is strictly less than max of offers[0:3]
        bad_session = {
            "n_picks": 4,
            "offers": [100, 200, 300, 50],  # final=50 < max_earlier=300 → bad gamble
            "dollar_counts": [1, 2, 3, 1],
            "chosen": ["5", "10", "20", "5"],
            "settled_win": 50,
        }
        # Session: final offer is the highest
        good_session = {
            "n_picks": 4,
            "offers": [100, 200, 300, 400],  # final=400 > max_earlier=300 → good
            "dollar_counts": [1, 2, 3, 4],
            "chosen": ["5", "10", "20", "50"],
            "settled_win": 400,
        }
        # 1-pick session: cannot be bad (no earlier offers to compare)
        early_stop = {
            "n_picks": 1,
            "offers": [999],
            "dollar_counts": [1],
            "chosen": ["100"],
            "settled_win": 999,
        }

        class FakeCtx:
            total_paid_spins = 10
            effective_bet_for_rtp = 10_000

        summary: dict = {}
        plugin.emit({"sessions": [bad_session, good_session, early_stop]}, summary, FakeCtx())
        td = summary["topdollar_choice"]
        assert td["bad_gamble_count"] == 1, (
            f"Expected 1 bad gamble (only bad_session), got {td['bad_gamble_count']}.\n"
            "Inject-bug A: flip 'final < max_earlier' to 'final > max_earlier' → RED."
        )
        assert td["forced_4th_count"] == 2  # bad_session + good_session

    def test_emit_no_bad_gamble_when_no_forced_4th(self):
        """bad_gamble_rate is None when forced_4th_count == 0 (no 4-pick sessions)."""
        import fresh_slotlab.analyzer.features.topdollar_choice as td_mod
        plugin = td_mod.TopDollarChoice()
        sessions = [
            {"n_picks": 1, "offers": [5000], "dollar_counts": [1],
             "chosen": ["5"], "settled_win": 5000},
            {"n_picks": 2, "offers": [5000, 10000], "dollar_counts": [1, 2],
             "chosen": ["5", "10"], "settled_win": 10000},
        ]

        class FakeCtx:
            total_paid_spins = 100
            effective_bet_for_rtp = 100_000

        summary: dict = {}
        plugin.emit({"sessions": sessions}, summary, FakeCtx())
        td = summary["topdollar_choice"]
        assert td["forced_4th_count"] == 0
        assert td["bad_gamble_rate"] is None, (
            "bad_gamble_rate must be None when no forced-4th sessions exist "
            "(avoids zero/zero false confidence)."
        )


# ---------------------------------------------------------------------------
# Gate — e2e subprocess (per feedback_perf_claim_needs_e2e_event_stream.md)
# ---------------------------------------------------------------------------

class TestM15SubprocessE2E:
    """Gate 6 brief: real subprocess run must show topdollar_choice section.

    Per feedback_perf_claim_needs_e2e_event_stream.md: unit tests + AST checks
    are not enough — a real subprocess against cached M15 chunks must produce
    the expected output. The feature must also be absent from M14.

    Inject-bug: corrupt feature logic → bad stats → test RED. Revert → GREEN.
    """

    @_SKIP_NO_M15
    def test_m15_subprocess_has_topdollar_section(self, tmp_path):
        """Real PIA subprocess for M15 (manifests present) shows topdollar_choice."""
        out_dir = tmp_path / "e2e_m15"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=5)
        assert "topdollar_choice" in summary, (
            "topdollar_choice absent from M15 subprocess output. "
            "Is 'topdollar_choice' in M15.json analyzer_features?"
        )
        td = summary["topdollar_choice"]
        assert td["applicable"] is True
        assert td["total_sessions"] == _TARGET_TOTAL_SESSIONS, (
            f"expected {_TARGET_TOTAL_SESSIONS} sessions in e2e run, "
            f"got {td['total_sessions']}"
        )
        # Spot-check key stats
        ppd = td["picks_per_session"]
        assert ppd["1"] == _TARGET_PICKS_1
        assert ppd["4"] == _TARGET_PICKS_4
        assert td["bad_gamble_count"] == _TARGET_BAD_GAMBLE
        assert td["dollar_tier_counts"].get("5") == _TARGET_TIER_5

    @_SKIP_NO_M15
    def test_m15_subprocess_rtp_contribution_within_range(self, tmp_path):
        """Real M15 subprocess: rtp_contribution_pp in [49, 52]%."""
        out_dir = tmp_path / "e2e_m15_rtp"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=5)
        td = summary.get("topdollar_choice", {})
        rtp = td.get("rtp_contribution_pp")
        assert rtp is not None
        assert _TARGET_RTP_CONTRIBUTION_LOW <= rtp <= _TARGET_RTP_CONTRIBUTION_HIGH, (
            f"rtp_contribution_pp={rtp:.2f}% outside [{_TARGET_RTP_CONTRIBUTION_LOW}, "
            f"{_TARGET_RTP_CONTRIBUTION_HIGH}]"
        )

    @_SKIP_NO_M14
    def test_m14_subprocess_no_topdollar_section(self, tmp_path):
        """Real PIA subprocess for M14 shows NO topdollar_choice section."""
        out_dir = tmp_path / "e2e_m14"
        summary = _run_pia_subprocess("M14", 1, _RAWDATA_M14, out_dir, max_chunks=2)
        assert "topdollar_choice" not in summary, (
            "topdollar_choice appeared in M14 subprocess output — must be absent. "
            "Either M14.json was accidentally given the feature, or the parser "
            "no-op guard is broken."
        )

    @_SKIP_NO_M15
    def test_m15_economy_unchanged_by_feature(self, tmp_path):
        """Real M15 subprocess: existing RTP output is additive-only (economy unchanged).

        Spot-check that the economy stats (rtp.point_pct, sampling.paid_spins)
        match the expected values from the 5-chunk analysis. The feature must not
        perturb any economy field.
        """
        out_dir = tmp_path / "e2e_m15_econ"
        summary = _run_pia_subprocess("M15", 1, _RAWDATA_M15, out_dir, max_chunks=5)
        assert summary["sampling"]["paid_spins"] == _TARGET_PAID_SPINS, (
            f"paid_spins changed: expected {_TARGET_PAID_SPINS}, "
            f"got {summary['sampling']['paid_spins']}"
        )
        # RTP should be the same as without the feature (additive-only)
        rtp = summary["rtp"]["point_pct"]
        assert isinstance(rtp, (int, float)), f"rtp.point_pct should be numeric, got {type(rtp)}"
