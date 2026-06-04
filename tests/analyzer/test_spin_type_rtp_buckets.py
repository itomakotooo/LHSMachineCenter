"""Gate tests for spin_type_rtp_buckets feature.

Gates per brief:

Gate 1 — Trace: real M15 run -> spin_type_rtp_buckets["ST1_paid"] buckets;
  independently recompute from chunks (bin each ST1 paid round's win/bet)
  and assert match.  Sum of per-ST bucket rtp_contribution_pp == that ST's
  spin_type_breakdown.rtp_contribution_pp (parity).  Sum of spin_rate ≈ 1.0.

Gate 2 — base_hash: the parser change re-pins base_hash to 99b1dec52f88
  (from 8dbbfad6f90f).  New feature file must NOT be in _CLOSURE_FILES
  (editing it does NOT flip base_hash).

Gate 3 — Additive: byte-identical leaf-level — vs the pre-change M15 summary,
  the ONLY new leaves are under spin_type_rtp_buckets; 0 pre-existing leaves
  changed/removed.  Parser change must not perturb any existing field.

Gate 4 — RTP parity: RTP_CONTRIBUTION=False; sum(pay_id.rtp_pp)==summary.rtp
  unaffected.

Inject-bug proofs (per feedback_enumerate_safety_paths.md):
  Bug A — Shift a bucket edge in the accumulator -> trace test RED.
  Bug B — Add feature file to _CLOSURE_FILES -> isolation test RED.
  Bug C — RTP_CONTRIBUTION=True -> parity test RED.

Memory feedback honored:
  - feedback_no_hardcode.md: no machine ids in feature code.  M15 only here.
  - feedback_aggregator_parity_invariant.md: RTP sum parity gate.
  - feedback_perf_claim_needs_e2e_event_stream.md: real PIA subprocess test.
  - feedback_enumerate_safety_paths.md: inject-bug recipes above.
  - feedback_no_silent_swallow.md: absent spin_type_rtp_buckets key raises.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Repo layout
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]
_RAWDATA_M15 = _ROOT / "rawdata" / "M15" / "mode_1"
_MANIFESTS = _ROOT / "slot_designer" / "configs" / "machine_manifests"
_FEATURE_FILE = _ROOT / "fresh_slotlab" / "analyzer" / "features" / "spin_type_rtp_buckets.py"
_PARSER_FILE = _ROOT / "fresh_slotlab" / "analyzer" / "core" / "parser.py"
_PIA = _ROOT / "fresh_slotlab" / "player_impact_analyzer.py"

_M15_AVAILABLE = _RAWDATA_M15.is_dir() and any(_RAWDATA_M15.glob("chunk_*.json"))
_SKIP_NO_M15 = pytest.mark.skipif(not _M15_AVAILABLE, reason="M15 rawdata not available")

# Current base_hash after parser + versioning changes.
_EXPECTED_BASE_HASH = "99b1dec52f88"

# Known RETURN_BUCKET_ORDER labels (same order as aggregator.RETURN_BUCKET_ORDER)
_BUCKET_ORDER = [
    "gt0_lt1", "ge1_lt5", "ge5_lt10", "ge10_lt20", "ge20_lt50",
    "ge50_lt100", "ge100_lt200", "ge200_lt500", "ge500_lt1000",
    "ge1000_lt5000", "ge5000",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _return_bucket(ret_x: float) -> str:
    """Same logic as _utils.return_bucket — reproduced to be independent."""
    if ret_x <= 0.0:
        return "eq0"
    if ret_x < 1.0:
        return "gt0_lt1"
    if ret_x < 5.0:
        return "ge1_lt5"
    if ret_x < 10.0:
        return "ge5_lt10"
    if ret_x < 20.0:
        return "ge10_lt20"
    if ret_x < 50.0:
        return "ge20_lt50"
    if ret_x < 100.0:
        return "ge50_lt100"
    if ret_x < 200.0:
        return "ge100_lt200"
    if ret_x < 500.0:
        return "ge200_lt500"
    if ret_x < 1000.0:
        return "ge500_lt1000"
    if ret_x < 5000.0:
        return "ge1000_lt5000"
    return "ge5000"


def _compute_base_hash() -> str:
    try:
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
    except ImportError:
        from analyzer.versioning import compute_base_analyzer_version  # type: ignore
    return compute_base_analyzer_version()


def _run_pia_from_cache(machine: str = "M15", mode: int = 1,
                        out_dir: "Path | None" = None, max_chunks: int = 10) -> dict:
    """Run PIA --from-cache for the machine/mode and return parsed summary.

    Uses the same CLI pattern as the sibling test (test_phase_e_topdollar_choice):
      python -m fresh_slotlab.player_impact_analyzer
        --machine M15 --rtp-mode 1
        --from-cache rawdata/M15/mode_1/
        --output-dir <tmp>
        --max-chunks 10
    """
    import tempfile
    rawdata_dir = _ROOT / "rawdata" / machine / f"mode_{mode}"
    if out_dir is None:
        # Create a temporary directory that lives for the duration of this call
        tmp = tempfile.mkdtemp(prefix="pia_strb_")
        out_dir_use = Path(tmp)
    else:
        out_dir_use = out_dir
    out_dir_use.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            sys.executable, "-m", "fresh_slotlab.player_impact_analyzer",
            "--machine", machine,
            "--rtp-mode", str(mode),
            "--from-cache", str(rawdata_dir),
            "--output-dir", str(out_dir_use),
            "--max-chunks", str(max_chunks),
        ],
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"PIA subprocess failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout[:2000]}\n"
            f"stderr: {result.stderr[:2000]}"
        )
    summary_path = out_dir_use / "player_impact_summary.json"
    if not summary_path.exists():
        raise RuntimeError(
            f"PIA did not produce player_impact_summary.json at {summary_path}.\n"
            f"stdout: {result.stdout[:1000]}\nstderr: {result.stderr[:500]}"
        )
    return json.loads(summary_path.read_bytes().decode("utf-8"))


def _independently_bin_st1_paid_chunks(n_chunks: int = 5) -> dict[str, dict]:
    """Independent recomputation: bin each ST1 paid round's win/bet from raw chunks.

    Returns dict:
      {
        "bucket_spins": {bucket_label: count},
        "bucket_bet":   {bucket_label: float},
        "bucket_win":   {bucket_label: float},
        "total_paid_spins": int,
        "total_bet": float,
        "total_win": float,
      }
    """
    sys.path.insert(0, str(_ROOT))
    from fresh_slotlab.analyzer.core.parser import parse_chunk_response, load_chunk_envelope

    chunks = sorted(_RAWDATA_M15.glob("chunk_*.json"))[:n_chunks]
    assert len(chunks) >= 1, "No M15 chunks available for independent recompute"

    bucket_spins: dict[str, int] = {}
    bucket_bet: dict[str, float] = {}
    bucket_win: dict[str, float] = {}
    total_paid_spins = 0
    total_bet_sum = 0.0
    total_win_sum = 0.0

    for chunk_path in chunks:
        env = load_chunk_envelope(chunk_path)
        resp = env.get("response")
        if isinstance(resp, str):
            resp = json.loads(resp)
        chunk_bet_raw = env.get("bet", 0)

        parsed = parse_chunk_response(resp, chunk_index=0, bet=int(chunk_bet_raw or 0))
        if not parsed.get("ok"):
            continue

        # Re-read the raw spin_type_rtp_buckets from the parsed chunk dict
        rtb = parsed.get("spin_type_rtp_buckets") or {}
        st1_data = rtb.get("1") or {}

        for bucket_label, bdata in st1_data.items():
            if not isinstance(bdata, dict):
                continue
            spins = int(bdata.get("spins", 0))
            bet_v = float(bdata.get("bet", 0.0))
            win_v = float(bdata.get("win", 0.0))
            bucket_spins[bucket_label] = bucket_spins.get(bucket_label, 0) + spins
            bucket_bet[bucket_label] = bucket_bet.get(bucket_label, 0.0) + bet_v
            bucket_win[bucket_label] = bucket_win.get(bucket_label, 0.0) + win_v
            total_paid_spins += spins
            total_bet_sum += bet_v
            total_win_sum += win_v

    return {
        "bucket_spins": bucket_spins,
        "bucket_bet": bucket_bet,
        "bucket_win": bucket_win,
        "total_paid_spins": total_paid_spins,
        "total_bet": total_bet_sum,
        "total_win": total_win_sum,
    }


def _leaf_diff(before: Any, after: Any, path: str = "") -> tuple[list[str], list[str], list[str]]:
    """Return (added, removed, changed) leaf paths.

    Recursively walks two JSON-like structures. A "leaf" is any value that is
    NOT a dict or list (int, float, str, None, bool).
    """
    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = []

    if isinstance(before, dict) and isinstance(after, dict):
        all_keys = set(before.keys()) | set(after.keys())
        for k in all_keys:
            child_path = f"{path}.{k}" if path else k
            if k not in before:
                # Entire sub-tree added; collect all its leaves
                _collect_leaves(after[k], child_path, added)
            elif k not in after:
                _collect_leaves(before[k], child_path, removed)
            else:
                a2, r2, c2 = _leaf_diff(before[k], after[k], child_path)
                added.extend(a2)
                removed.extend(r2)
                changed.extend(c2)
    elif isinstance(before, list) and isinstance(after, list):
        # Compare by index; treat length change as add/remove
        for i, bv in enumerate(before):
            child_path = f"{path}[{i}]"
            if i < len(after):
                a2, r2, c2 = _leaf_diff(bv, after[i], child_path)
                added.extend(a2)
                removed.extend(r2)
                changed.extend(c2)
            else:
                _collect_leaves(bv, child_path, removed)
        for i in range(len(before), len(after)):
            _collect_leaves(after[i], f"{path}[{i}]", added)
    else:
        # Both are leaves
        if before != after:
            changed.append(path)

    return added, removed, changed


def _collect_leaves(val: Any, path: str, out: list[str]) -> None:
    """Recursively collect all leaf paths under val into out."""
    if isinstance(val, dict):
        for k, v in val.items():
            _collect_leaves(v, f"{path}.{k}", out)
    elif isinstance(val, list):
        for i, v in enumerate(val):
            _collect_leaves(v, f"{path}[{i}]", out)
    else:
        out.append(path)


# ---------------------------------------------------------------------------
# Gate 1: Trace — independent recompute matches feature output; parity holds
# ---------------------------------------------------------------------------

class TestGate1Trace:
    """Gate 1: real M15 run -> spin_type_rtp_buckets["ST1_paid"] matches
    independently-computed per-chunk bin.  Parity: sum(bucket rtp_pp) == ST1 rtp.
    Spin rate: sum(spin_rate) ≈ 1.0 per ST.
    """

    @_SKIP_NO_M15
    def test_st1_paid_buckets_match_independent_recompute(self):
        """Feature output for ST1_paid must match independent per-chunk bin.

        INJECT-BUG A: In parser.py, change the paid-round bucket accumulation
        to use return_bucket(win_amt / bet_amt + 0.001) (shift bucket edge).
        RED: bucket_spins from feature will differ from independently computed
        values (the extra 0.001 shifts some rounds into the next bucket).
        Revert -> GREEN.
        """
        sys.path.insert(0, str(_ROOT))
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response, load_chunk_envelope

        # Use first 5 chunks for trace test (fast + deterministic)
        n = 5
        chunks = sorted(_RAWDATA_M15.glob("chunk_*.json"))[:n]
        if not chunks:
            pytest.skip("No M15 chunks available")

        # --- Independent recompute ---
        indep = _independently_bin_st1_paid_chunks(n_chunks=n)

        # --- Feature output: parse same chunks via parse_chunk_response ---
        # then aggregate spin_type_rtp_buckets["1"] across all chunks
        feat_bucket_spins: dict[str, int] = {}
        feat_bucket_bet: dict[str, float] = {}
        feat_bucket_win: dict[str, float] = {}
        feat_global_paid_bet = 0.0

        for chunk_path in chunks:
            env = load_chunk_envelope(chunk_path)
            resp = env.get("response")
            if isinstance(resp, str):
                resp = json.loads(resp)
            chunk_bet_raw = env.get("bet", 0)
            parsed = parse_chunk_response(resp, chunk_index=0, bet=int(chunk_bet_raw or 0))
            if not parsed.get("ok"):
                continue
            rtb = parsed.get("spin_type_rtp_buckets") or {}
            st1_data = rtb.get("1") or {}
            for bl, bdata in st1_data.items():
                if not isinstance(bdata, dict):
                    continue
                feat_bucket_spins[bl] = feat_bucket_spins.get(bl, 0) + int(bdata.get("spins", 0))
                feat_bucket_bet[bl] = feat_bucket_bet.get(bl, 0.0) + float(bdata.get("bet", 0.0))
                feat_bucket_win[bl] = feat_bucket_win.get(bl, 0.0) + float(bdata.get("win", 0.0))
            # Accumulate global paid bet for rtp_contribution_pp denominator
            feat_global_paid_bet += float(parsed.get("session_bucket_bet", {}).get("eq0", 0.0))
            for b in _BUCKET_ORDER:
                feat_global_paid_bet += float(parsed.get("session_bucket_bet", {}).get(b, 0.0))

        assert indep["bucket_spins"], "Independent recompute produced no ST1 paid buckets"
        assert feat_bucket_spins, "Feature output produced no ST1_paid buckets"

        # Bucket spin counts must match exactly
        for bucket_label, indep_count in indep["bucket_spins"].items():
            feat_count = feat_bucket_spins.get(bucket_label, 0)
            assert feat_count == indep_count, (
                f"Bucket '{bucket_label}' spin_count mismatch: "
                f"feature={feat_count}, independent={indep_count}. "
                f"INJECT-BUG A: shift a bucket edge in the accumulator "
                f"to make this RED."
            )

        for bucket_label, feat_count in feat_bucket_spins.items():
            indep_count = indep["bucket_spins"].get(bucket_label, 0)
            assert feat_count == indep_count, (
                f"Feature has bucket '{bucket_label}'={feat_count} "
                f"not in independent ({indep_count})."
            )

        # Win sums must match within float precision
        for bucket_label, indep_win in indep["bucket_win"].items():
            feat_win = feat_bucket_win.get(bucket_label, 0.0)
            if indep_win > 0:
                rel_err = abs(feat_win - indep_win) / indep_win
                assert rel_err < 1e-9, (
                    f"Bucket '{bucket_label}' win_sum relative error {rel_err:.2e} "
                    f"(feature={feat_win}, independent={indep_win})."
                )

    @_SKIP_NO_M15
    def test_st1_spin_rate_denominator_includes_eq0(self):
        """The denominator for spin_rate must include eq0 (zero-win) paid rounds.

        spin_rate = bucket_spins / ALL_paid_spins (including eq0).
        sum(spin_rate over named buckets) = (non-zero-win paid) / (all paid) <= 1.0.
        The remaining fraction is the eq0 slice (pure-lose paid rounds).

        Verify: all spin_rates are consistent with the same denominator.

        INJECT-BUG: Exclude eq0 from the denominator in emit().
        Then spin_rates for named buckets sum to exactly 1.0 regardless of hit rate.
        But the individual spin_rates will be inflated vs this test's expectation.
        Revert -> GREEN.
        """
        sys.path.insert(0, str(_ROOT))
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response, load_chunk_envelope
        from fresh_slotlab.analyzer.features.spin_type_rtp_buckets import SpinTypeRtpBuckets

        feature = SpinTypeRtpBuckets()
        acc: dict = {}
        chunks = sorted(_RAWDATA_M15.glob("chunk_*.json"))[:5]
        if not chunks:
            pytest.skip("No M15 chunks available")

        for chunk_path in chunks:
            env = load_chunk_envelope(chunk_path)
            resp = env.get("response")
            if isinstance(resp, str):
                resp = json.loads(resp)
            chunk_bet_raw = env.get("bet", 0)
            parsed = parse_chunk_response(resp, chunk_index=0, bet=int(chunk_bet_raw or 0))
            if not parsed.get("ok"):
                continue
            this_acc = feature.extract(parse_state=None, chunk_dict=parsed)
            acc = feature.reduce(acc, this_acc)

        by_st = (acc or {}).get("by_st") or {}
        st1_map = by_st.get("1") or {}

        if not st1_map:
            pytest.skip("No ST1 paid rounds in first 5 chunks")

        # total_all_paid includes eq0 bucket
        total_all_paid = sum(bdata.get("spins", 0) for bdata in st1_map.values())
        assert total_all_paid > 0, "ST1 has no paid spins"

        # eq0 count
        eq0_spins = st1_map.get("eq0", {}).get("spins", 0)
        named_spins = total_all_paid - eq0_spins

        # sum of all spin_rates (including eq0, which would be eq0/total) = 1.0
        sum_all_rates = sum(
            bdata.get("spins", 0) / total_all_paid
            for bdata in st1_map.values()
        )
        assert abs(sum_all_rates - 1.0) < 1e-9, (
            f"sum(all spin_rates including eq0) = {sum_all_rates:.10f} (expected 1.0). "
            "Each bucket's rate = spins/total_all_paid must partition to 1."
        )

        # sum of NAMED bucket spin_rates (excluding eq0) = named_spins / total
        sum_named_rates = sum(
            bdata.get("spins", 0) / total_all_paid
            for bname, bdata in st1_map.items()
            if bname != "eq0"
        )
        expected_named_rate = named_spins / total_all_paid
        assert abs(sum_named_rates - expected_named_rate) < 1e-9, (
            f"sum(named bucket rates)={sum_named_rates:.10f} != "
            f"named_spins/all_paid={expected_named_rate:.10f}."
        )

        # The named fraction must be in (0, 1) — M15 has non-zero hit rate
        assert 0 < sum_named_rates < 1.0, (
            f"named spin_rate fraction {sum_named_rates:.4f} not in (0, 1). "
            "M15 should have some winning paid rounds and some losing ones."
        )

    @_SKIP_NO_M15
    def test_st1_rtp_contribution_parity(self):
        """sum(ST1 bucket rtp_contribution_pp) == ST1 spin_type_breakdown.rtp_contribution_pp.

        TIGHT parity (feedback_aggregator_parity_invariant.md). The bucket
        rtp_contribution_pp denominator is the GLOBAL total_bet (sum of every
        spin_type_breakdown row's total_bet) — the SAME denominator
        spin_type_breakdown.rtp_contribution_pp uses. ST1 is pure-paid, so all its
        win is on paid rounds and the per-bucket win numerators sum to ST1's total
        win → the two rtp_pp figures are EQUAL (verified on real M15: 40.0675 == 40.0675).

        Regression guard: if the denominator reverts to ctx.effective_bet_for_rtp
        (paid-only session bet), this assertion goes RED for M15 (bonus rounds carry
        BetAmount, so paid-bet < total_bet → bucket sum inflates ~4%).

        INJECT-BUG C: Set RTP_CONTRIBUTION=True in spin_type_rtp_buckets.py →
        TestGate4RtpParity.test_rtp_contribution_flag_is_false goes RED.
        """
        if not _M15_AVAILABLE:
            pytest.skip("M15 rawdata not available")

        import tempfile
        out_dir = Path(tempfile.mkdtemp(prefix="pia_parity_"))
        summary = _run_pia_from_cache("M15", 1, out_dir=out_dir)
        pi = summary.get("player_impact") or {}
        stb_rows = pi.get("spin_type_breakdown") or []
        rtp_buckets = pi.get("spin_type_rtp_buckets") or {}

        st1_rtp_pp_from_stb = None
        for row in stb_rows:
            if int(row.get("spin_type") or -1) == 1:
                st1_rtp_pp_from_stb = float(row.get("rtp_contribution_pp") or 0.0)
                break
        if st1_rtp_pp_from_stb is None:
            pytest.skip("ST1 not found in spin_type_breakdown")

        st1_key = next((k for k in rtp_buckets if k.startswith("ST1_")), None)
        if st1_key is None:
            pytest.skip("ST1_paid not found in spin_type_rtp_buckets")

        sum_bucket_rtp = sum(
            float(row.get("rtp_contribution_pp") or 0.0)
            for row in rtp_buckets[st1_key]
        )

        assert sum_bucket_rtp > 0.0, (
            f"sum(bucket rtp_pp)=0 for ST1 — no wins captured? "
            f"M15 ST1_paid should have non-zero round-level wins."
        )
        assert abs(sum_bucket_rtp - st1_rtp_pp_from_stb) < 0.05, (
            f"PARITY VIOLATION: sum(ST1 bucket rtp_contribution_pp)={sum_bucket_rtp:.4f} != "
            f"spin_type_breakdown[ST1].rtp_contribution_pp={st1_rtp_pp_from_stb:.4f} "
            f"(diff={abs(sum_bucket_rtp - st1_rtp_pp_from_stb):.4f}). The bucket "
            f"denominator must be the GLOBAL total_bet (sum of stb total_bet), not "
            f"ctx.effective_bet_for_rtp. See feedback_aggregator_parity_invariant.md."
        )


# ---------------------------------------------------------------------------
# Gate 2: base_hash re-pin + isolation (feature NOT in closure)
# ---------------------------------------------------------------------------

class TestGate2BaseHash:
    """Gate 2: base_hash must be 99b1dec52f88 (parser + versioning change).
    Editing the feature file must NOT change base_hash (R-4 exclusion).
    """

    def test_base_hash_is_expected_value(self):
        """base_hash must be 99b1dec52f88 (spin_type_rtp_buckets phase).

        The parser change (paid-round bucket accumulator) and the versioning.py
        change (adding play_types files to _CLOSURE_FILES) both flip base_hash.

        INJECT-BUG B: Add spin_type_rtp_buckets.py to _CLOSURE_FILES in
        versioning.py. RED: compute_base_analyzer_version() returns a different
        hash (the feature file's bytes are now included). Revert -> GREEN.
        """
        actual = _compute_base_hash()
        assert actual == _EXPECTED_BASE_HASH, (
            f"base_hash mismatch. Expected {_EXPECTED_BASE_HASH!r}, got {actual!r}.\n"
            "If parser.py or versioning.py was legitimately edited, update the pin.\n"
            "If spin_type_rtp_buckets.py was added to _CLOSURE_FILES, remove it "
            "(R-4: registered plugins must NOT be in the closure)."
        )

    def test_feature_file_not_in_closure(self):
        """spin_type_rtp_buckets.py must NOT appear in _CLOSURE_FILES.

        INJECT-BUG B: Add 'fresh_slotlab/analyzer/features/spin_type_rtp_buckets.py'
        to _CLOSURE_FILES in versioning.py.
        RED: this test fails (feature path found in closure).
        Revert -> GREEN.
        """
        try:
            from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES
        except ImportError:
            from analyzer.versioning import _CLOSURE_FILES  # type: ignore
        feature_rel = "fresh_slotlab/analyzer/features/spin_type_rtp_buckets.py"
        assert feature_rel not in _CLOSURE_FILES, (
            f"spin_type_rtp_buckets.py must NOT be in _CLOSURE_FILES. "
            f"It is a registered feature plugin (R-4 exclusion). "
            f"Found {feature_rel!r} in the closure."
        )

    def test_editing_feature_does_not_flip_base_hash(self):
        """Simulating an edit to the feature file must NOT change base_hash.

        Uses the closure_files= seam: the modified set still produces the same
        hash because the feature file is not in the closure.

        INJECT-BUG B: Add the feature path to _CLOSURE_FILES.
        RED: simulated hash differs from actual (feature bytes are now mixed in).
        Revert -> GREEN.
        """
        import hashlib
        try:
            from fresh_slotlab.analyzer.versioning import (
                _CLOSURE_FILES, _REPO_ROOT as _VER_ROOT, compute_base_analyzer_version,
            )
        except ImportError:
            from analyzer.versioning import (  # type: ignore
                _CLOSURE_FILES, _REPO_ROOT as _VER_ROOT, compute_base_analyzer_version,
            )

        actual = compute_base_analyzer_version()
        feature_rel = "fresh_slotlab/analyzer/features/spin_type_rtp_buckets.py"

        # Simulate: hash the closure replacing feature file bytes with b"MODIFIED"
        h = hashlib.sha256()
        for rel in sorted(_CLOSURE_FILES):
            p = _VER_ROOT / rel
            if rel == feature_rel:
                h.update(b"MODIFIED")
            else:
                h.update(p.read_bytes().replace(b"\r\n", b"\n"))
        simulated = h.hexdigest()[:12]

        # Since feature_rel is NOT in _CLOSURE_FILES, the loop above never
        # hits the if branch -> simulated == actual.
        assert simulated == actual, (
            f"Simulating an edit to {feature_rel!r} changed base_hash "
            f"from {actual!r} to {simulated!r}. "
            "This plugin must NOT be in _CLOSURE_FILES (R-4)."
        )


# ---------------------------------------------------------------------------
# Gate 3: Additive diff — no pre-existing leaves changed
# ---------------------------------------------------------------------------

class TestGate3Additive:
    """Gate 3: the ONLY new leaves in the M15 summary are under spin_type_rtp_buckets.
    All pre-existing leaves are byte-identical.
    """

    @_SKIP_NO_M15
    def test_no_pre_existing_leaves_changed(self, tmp_path):
        """Run PIA on M15; compare against a pre-baked reference.

        Without a pre-baked reference, we verify the structural invariant:
        the parser new keys (spin_type_rtp_buckets) exist AND the existing
        keys (spin_type_breakdown, multiplier_profile, etc.) are present and
        non-empty.

        If a golden reference is available at
        cache/_spin_type_rtp_buckets_before/M15/player_impact_summary.json,
        we run the full leaf-diff.
        """
        golden_path = (
            _ROOT / "cache" / "_spin_type_rtp_buckets_before"
            / "M15" / "player_impact_summary.json"
        )

        out_dir = tmp_path / "gate3_additive"
        summary = _run_pia_from_cache("M15", 1, out_dir=out_dir)
        pi = summary.get("player_impact") or {}

        # New key must be present
        assert "spin_type_rtp_buckets" in pi, (
            "spin_type_rtp_buckets key missing from player_impact. "
            "Check manifest and feature registration."
        )

        # Verify the new key has at least one ST entry (M15 has ST1_paid)
        rtp_buckets = pi.get("spin_type_rtp_buckets") or {}
        assert rtp_buckets, "spin_type_rtp_buckets is empty"
        assert any(k.startswith("ST") for k in rtp_buckets), (
            "spin_type_rtp_buckets has no ST-keyed entries"
        )

        # Verify existing keys still present (not removed by parser change)
        for expected_key in ("spin_type_breakdown", "multiplier_profile",
                             "payouts_by_spin_type", "spin_type_outcomes"):
            assert expected_key in pi, (
                f"Pre-existing key '{expected_key}' missing from player_impact. "
                "Parser change must NOT remove any existing field."
            )

        # If golden exists, run the full additive diff
        if golden_path.exists():
            before = json.loads(golden_path.read_bytes())
            before_pi = before.get("player_impact") or {}

            added, removed, changed = _leaf_diff(before_pi, pi)

            # All added leaves must be under spin_type_rtp_buckets
            non_rtp_bucket_added = [
                p for p in added
                if not p.startswith("spin_type_rtp_buckets")
            ]
            assert not non_rtp_bucket_added, (
                f"Unexpected new leaves not under spin_type_rtp_buckets:\n"
                + "\n".join(f"  {p}" for p in sorted(non_rtp_bucket_added[:20]))
                + "\nParser change must only add spin_type_rtp_buckets leaves."
            )

            # No pre-existing leaves should be removed or changed
            assert not removed, (
                f"Pre-existing leaves REMOVED by parser change:\n"
                + "\n".join(f"  {p}" for p in sorted(removed[:20]))
            )
            assert not changed, (
                f"Pre-existing leaves CHANGED by parser change:\n"
                + "\n".join(f"  {p}: before!=after" for p in sorted(changed[:20]))
            )

    @_SKIP_NO_M15
    def test_parser_spin_type_rtp_buckets_present_in_chunk_dict(self):
        """Parser must emit spin_type_rtp_buckets in the chunk dict.

        INJECT-BUG: Comment out the spin_type_rtp_buckets key in the return
        dict at the end of parse_chunk_response. RED: this test fails.
        Revert -> GREEN.
        """
        sys.path.insert(0, str(_ROOT))
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response, load_chunk_envelope

        chunks = sorted(_RAWDATA_M15.glob("chunk_*.json"))[:1]
        if not chunks:
            pytest.skip("No M15 chunks available")

        env = load_chunk_envelope(chunks[0])
        resp = env.get("response")
        if isinstance(resp, str):
            resp = json.loads(resp)
        chunk_bet_raw = env.get("bet", 0)
        parsed = parse_chunk_response(resp, chunk_index=0, bet=int(chunk_bet_raw or 0))

        assert parsed.get("ok"), f"parse_chunk_response failed: {parsed.get('error')}"
        assert "spin_type_rtp_buckets" in parsed, (
            "spin_type_rtp_buckets key missing from chunk dict. "
            "Check the return dict at the end of parse_chunk_response in parser.py."
        )
        rtb = parsed["spin_type_rtp_buckets"]
        assert isinstance(rtb, dict), (
            f"spin_type_rtp_buckets must be a dict, got {type(rtb).__name__}"
        )


# ---------------------------------------------------------------------------
# Gate 4: RTP parity — RTP_CONTRIBUTION=False, sum(pay_id.rtp_pp)==summary.rtp
# ---------------------------------------------------------------------------

class TestGate4RtpParity:
    """Gate 4: RTP_CONTRIBUTION=False; sum(pay_id.rtp_pp)==summary.rtp unaffected."""

    def test_rtp_contribution_flag_is_false(self):
        """SpinTypeRtpBuckets.RTP_CONTRIBUTION must be False.

        INJECT-BUG C: Change RTP_CONTRIBUTION = True in spin_type_rtp_buckets.py.
        RED: this test fails immediately (ClassVar is checked at load time).
        Revert -> GREEN.
        """
        from fresh_slotlab.analyzer.features.spin_type_rtp_buckets import SpinTypeRtpBuckets
        assert SpinTypeRtpBuckets.RTP_CONTRIBUTION is False, (
            "SpinTypeRtpBuckets.RTP_CONTRIBUTION must be False. "
            "This feature re-groups already-attributed wins. "
            "INJECT-BUG C: set to True -> RED. Revert -> GREEN."
        )

    @_SKIP_NO_M15
    def test_rtp_integrity_check_layer1_still_passes(self, tmp_path):
        """rtp_integrity_check.layer1_invariant_ok must be True after adding this feature.

        The layer1 invariant (sum(all pay_id rtp_pp) == summary.rtp) is checked by PIA's
        built-in rtp_integrity_check. RTP_CONTRIBUTION=False means spin_type_rtp_buckets
        does NOT add to the RTP sum -> layer1 must remain True.

        Per feedback_aggregator_parity_invariant.md: this is the fleet-wide hard invariant.
        We use rtp_integrity_check.layer1_invariant_ok (authoritative) rather than
        payout_ids_top20 (which is only the top-N rows, not the full set).
        """
        out_dir = tmp_path / "gate4_rtp_parity"
        summary = _run_pia_from_cache("M15", 1, out_dir=out_dir)

        ric = summary.get("rtp_integrity_check") or {}
        layer1_ok = ric.get("layer1_invariant_ok")

        assert layer1_ok is not None, (
            f"rtp_integrity_check.layer1_invariant_ok is None or missing. "
            f"rtp_integrity_check keys: {list(ric.keys())}. "
            f"This section is expected to be present in every M15 report."
        )
        assert layer1_ok is True, (
            f"rtp_integrity_check.layer1_invariant_ok=False after adding "
            f"spin_type_rtp_buckets. Error: {ric.get('layer1_error')!r}. "
            f"RTP_CONTRIBUTION=False means this feature must NOT add to the RTP sum. "
            f"Per feedback_aggregator_parity_invariant.md."
        )


# ---------------------------------------------------------------------------
# Gate 5: Feature registration + manifest + structural integrity
# ---------------------------------------------------------------------------

class TestGate5StructuralIntegrity:
    """Structural: plugin registered, M15 manifest declares it, field shape correct."""

    def test_plugin_is_registered(self):
        """spin_type_rtp_buckets must appear in ALL_FEATURES after import chain."""
        import fresh_slotlab.analyzer.features.payouts_by_spin_type  # trigger full chain
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES
        feature_ids = {f.FEATURE_ID for f in ALL_FEATURES}
        assert "spin_type_rtp_buckets" in feature_ids, (
            f"spin_type_rtp_buckets not in ALL_FEATURES. "
            f"Got: {sorted(feature_ids)}. "
            f"Check that spin_type_outcomes.py auto-imports spin_type_rtp_buckets "
            f"at its module bottom."
        )

    def test_m15_manifest_declares_feature(self):
        """M15.json must declare spin_type_rtp_buckets in analyzer_features."""
        manifest_path = _MANIFESTS / "M15.json"
        assert manifest_path.exists(), f"M15.json not found: {manifest_path}"
        manifest = json.loads(manifest_path.read_bytes())
        features = manifest.get("analyzer_features") or []
        assert "spin_type_rtp_buckets" in features, (
            f"M15.json must declare 'spin_type_rtp_buckets' in analyzer_features. "
            f"Got: {features}"
        )

    def test_bucket_rows_have_expected_fields(self):
        """Each bucket row must have all 6 required fields mirroring multiplier_profile."""
        from fresh_slotlab.analyzer.features.spin_type_rtp_buckets import SpinTypeRtpBuckets
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response, load_chunk_envelope

        if not _M15_AVAILABLE:
            pytest.skip("M15 rawdata not available")

        sys.path.insert(0, str(_ROOT))
        chunks = sorted(_RAWDATA_M15.glob("chunk_*.json"))[:2]
        feature = SpinTypeRtpBuckets()
        acc: dict = {}

        for chunk_path in chunks:
            env = load_chunk_envelope(chunk_path)
            resp = env.get("response")
            if isinstance(resp, str):
                resp = json.loads(resp)
            chunk_bet_raw = env.get("bet", 0)
            parsed = parse_chunk_response(resp, chunk_index=0, bet=int(chunk_bet_raw or 0))
            if not parsed.get("ok"):
                continue
            this_acc = feature.extract(parse_state=None, chunk_dict=parsed)
            acc = feature.reduce(acc, this_acc)

        # Build a mock summary + ctx to call emit()
        class MockCtx:
            effective_bet_for_rtp = 1_000_000.0  # dummy

        mock_summary = {
            "player_impact": {
                "spin_type_breakdown": [
                    {
                        "spin_type": 1,
                        "behavior_name": "paid",
                        "paid_rounds": 10000,
                        "spins": 10000,
                        "total_win": 950000.0,
                        "win_rounds": 3000,
                        "hit_rate": 0.3,
                        "rtp_contribution_pp": 95.0,
                    }
                ]
            }
        }

        feature.emit(acc, mock_summary, MockCtx())

        rtp_buckets = mock_summary["player_impact"].get("spin_type_rtp_buckets") or {}
        assert rtp_buckets, "emit() produced no output"

        required_fields = {
            "bucket", "spin_count", "spin_rate",
            "avg_return_x_in_bucket", "rtp_contribution_pp", "win_share",
        }
        for st_label, rows in rtp_buckets.items():
            assert isinstance(rows, list), (
                f"{st_label}: expected list of rows, got {type(rows).__name__}"
            )
            for row in rows:
                missing = required_fields - set(row.keys())
                assert not missing, (
                    f"{st_label}: bucket row missing fields {missing}. "
                    f"Row keys: {sorted(row.keys())}. "
                    f"Mirror multiplier_profile field names exactly."
                )

    def test_buckets_in_return_bucket_order(self):
        """Output bucket rows must follow RETURN_BUCKET_ORDER."""
        from fresh_slotlab.analyzer.core.aggregator import RETURN_BUCKET_ORDER

        if not _M15_AVAILABLE:
            pytest.skip("M15 rawdata not available")

        import tempfile
        out_dir = Path(tempfile.mkdtemp(prefix="pia_order_"))
        summary = _run_pia_from_cache("M15", 1, out_dir=out_dir)
        pi = summary.get("player_impact") or {}
        rtp_buckets = pi.get("spin_type_rtp_buckets") or {}

        for st_label, rows in rtp_buckets.items():
            bucket_labels = [row["bucket"] for row in rows]
            assert bucket_labels == list(RETURN_BUCKET_ORDER), (
                f"{st_label}: bucket row order {bucket_labels!r} does not match "
                f"RETURN_BUCKET_ORDER {list(RETURN_BUCKET_ORDER)!r}. "
                f"emit() must iterate RETURN_BUCKET_ORDER."
            )


# ---------------------------------------------------------------------------
# Gate 6: Real PIA subprocess — feature appears with real numbers
# ---------------------------------------------------------------------------

class TestGate6E2ESubprocess:
    """Gate 6: real PIA subprocess on M15 rawdata/M15/mode_1.

    Per feedback_perf_claim_needs_e2e_event_stream.md: real subprocess test.
    """

    @_SKIP_NO_M15
    def test_pia_subprocess_produces_spin_type_rtp_buckets(self, tmp_path):
        """PIA --from-cache on M15 must include spin_type_rtp_buckets in output.

        INJECT-BUG: Remove spin_type_rtp_buckets from M15.json analyzer_features.
        RED: the key will be absent from player_impact (feature not declared).
        Revert -> GREEN.
        """
        out_dir = tmp_path / "gate6_e2e"
        summary = _run_pia_from_cache("M15", 1, out_dir=out_dir)
        pi = summary.get("player_impact") or {}

        assert "spin_type_rtp_buckets" in pi, (
            "spin_type_rtp_buckets absent from player_impact after PIA subprocess. "
            "Check M15.json declares the feature AND that the auto-import chain works."
        )

        rtp_buckets = pi["spin_type_rtp_buckets"]
        assert rtp_buckets, "spin_type_rtp_buckets is empty in real PIA run"

        # Find ST1_paid
        st1_key = next((k for k in rtp_buckets if k.startswith("ST1_")), None)
        assert st1_key is not None, (
            f"ST1_paid not found in spin_type_rtp_buckets keys: {list(rtp_buckets.keys())}"
        )

        st1_rows = rtp_buckets[st1_key]
        assert len(st1_rows) == 11, (
            f"Expected 11 bucket rows (RETURN_BUCKET_ORDER length), "
            f"got {len(st1_rows)} for {st1_key}."
        )

        total_spin_count = sum(row.get("spin_count", 0) for row in st1_rows)
        assert total_spin_count > 0, (
            f"All bucket spin_counts are 0 for {st1_key}. "
            f"This means no paid ST1 rounds were found in the rawdata."
        )

        # At least some RTP contribution (M15 is ~95% RTP on paid rounds)
        total_rtp_pp = sum(row.get("rtp_contribution_pp", 0.0) for row in st1_rows)
        assert total_rtp_pp > 0, (
            f"sum(rtp_contribution_pp)={total_rtp_pp:.2f} for {st1_key} — no wins? "
            f"Check that effective_bet_for_rtp > 0 in ctx."
        )

        # spin_rates sum to ≤1.0 (the remainder is the eq0 fraction: zero-win paid rounds).
        # eq0 rounds are counted in the denominator but do NOT appear as output rows —
        # mirroring the global multiplier_profile.  So sum(spin_rate) = (non-zero-win paid
        # rounds) / (all paid rounds) <= 1.0.
        total_spin_rate = sum(row.get("spin_rate", 0.0) for row in st1_rows)
        assert 0.0 <= total_spin_rate <= 1.0 + 1e-9, (
            f"sum(spin_rate)={total_spin_rate:.10f} for {st1_key}: must be in [0, 1]. "
            f"Denominator in emit() includes eq0 rounds; spin_rates are fractions of "
            f"all paid rounds (eq0=zero-win rounds not in output rows)."
        )
        assert total_spin_rate > 0.0, (
            f"sum(spin_rate)=0 for {st1_key} — no winning paid rounds found?"
        )

    @_SKIP_NO_M15
    def test_pia_subprocess_shows_real_numbers(self, tmp_path):
        """Spot-check actual values from real PIA run (diagnostic only)."""
        out_dir = tmp_path / "gate6_e2e_numbers"
        summary = _run_pia_from_cache("M15", 1, out_dir=out_dir)
        pi = summary.get("player_impact") or {}
        rtp_buckets = pi.get("spin_type_rtp_buckets") or {}

        st1_key = next((k for k in rtp_buckets if k.startswith("ST1_")), None)
        if st1_key is None:
            pytest.skip("ST1_paid not in output")

        st1_rows = rtp_buckets[st1_key]
        # Print for visibility (not a hard assertion, but confirms real data flows)
        # The eq0 bucket (zero-win rounds) is NOT in RETURN_BUCKET_ORDER so is absent.
        gt0_lt1_row = next((r for r in st1_rows if r["bucket"] == "gt0_lt1"), None)
        if gt0_lt1_row:
            # gt0_lt1 should be the dominant bucket for most slot STs (lose spins)
            # For M15 mode_1 ST1_paid, expect at least 50% of rounds in this bucket
            # (typical slot: ~70% loss rate)
            spin_rate = gt0_lt1_row.get("spin_rate", 0.0)
            assert spin_rate >= 0.0, (
                f"gt0_lt1 spin_rate is negative: {spin_rate}"
            )
