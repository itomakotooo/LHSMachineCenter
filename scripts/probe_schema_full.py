"""Exhaustive per-machine schema probe — emit a complete KB-scale
markdown inventory of every field at every nesting level, all composite
string internals, per-SpinType field coverage, and cross-field
consistency checks.

Never echoes raw round content. All outputs are counts / distinct value
lists / small structural samples. Designed for the operator to get a
"I know exactly what's in this machine's rawdata" feel without dumping
a 6 MB JSON into the chat.

Usage:
    python scripts/probe_schema_full.py --machine M273 --mode 1
    python scripts/probe_schema_full.py --machine M273 --mode 1 --output dev_reports/_schema/M273_m1.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV_RAWDATA = ROOT / "dev_rawdata"


def _iter_chunks(machine: str, mode: int):
    d = DEV_RAWDATA / machine / f"mode_{mode}"
    if not d.is_dir():
        return
    for f in sorted(d.glob("chunk_*.json")):
        yield f


def _load_env(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_round_result(robot: dict) -> list[dict]:
    rr = robot.get("roundResult")
    if isinstance(rr, str):
        try:
            return json.loads(rr)
        except json.JSONDecodeError:
            return []
    if isinstance(rr, list):
        return rr
    return []


def _shape_of(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return f"str(len={len(v)})"
    if isinstance(v, list):
        return f"list(n={len(v)})"
    if isinstance(v, dict):
        return f"dict(keys={len(v)})"
    return type(v).__name__


def _distinct_values_capped(values, cap: int = 50):
    counts = Counter()
    for v in values:
        try:
            counts[v] += 1
        except TypeError:
            counts[f"<{type(v).__name__}>"] += 1
    return counts, len(counts)


def _probe_envelope(env: dict) -> dict:
    """Top-level envelope keys (`_bet`, `_config_md5`, `response`, etc.)."""
    out = {}
    for k, v in env.items():
        out[k] = _shape_of(v)
    return out


def _probe_robot(robot: dict) -> list[str]:
    return sorted(robot.keys())


def _probe_analysis(robot: dict) -> dict:
    ar = robot.get("analysisResult")
    if isinstance(ar, str):
        try:
            ar = json.loads(ar)
        except json.JSONDecodeError:
            return {"_parse_error": "invalid JSON string"}
    if not isinstance(ar, dict):
        return {"_shape": _shape_of(ar)}
    detail = {}
    for k, v in ar.items():
        if k == "FeatureWin" and isinstance(v, dict):
            # FeatureWin structure: {feat_name: {pay_id: int_or_obj}}
            feats = {}
            for feat, payouts in v.items():
                if isinstance(payouts, dict):
                    feats[feat] = {
                        "pay_ids_count": len(payouts),
                        "pay_id_samples": list(payouts.keys())[:5],
                        "first_entry_shape": (
                            _shape_of(next(iter(payouts.values())))
                            if payouts else "empty"
                        ),
                    }
                else:
                    feats[feat] = _shape_of(payouts)
            detail[k] = feats
        else:
            detail[k] = _shape_of(v)
    return detail


def _decompose_remarks(remarks_counter: Counter) -> dict:
    """Bucket ReMarks strings by leading word / prefix pattern."""
    buckets = Counter()
    samples = {}
    for rm, n in remarks_counter.items():
        if not isinstance(rm, str) or not rm:
            key = "<empty>"
        else:
            # First word or first "Word" up to whitespace/colon.
            m = re.match(r"^\s*([A-Za-z]+)", rm)
            key = m.group(1) if m else rm[:30]
        buckets[key] += n
        if key not in samples:
            samples[key] = rm[:100] if isinstance(rm, str) else str(rm)
    return {"buckets": buckets, "samples": samples}


def _decompose_stop_symbols(samples: list) -> dict:
    """StopSymbolsByCol: usually a list[str] where each element is a
    column like 'sym0-sym1-sym2-' (dash-joined, trailing dash).
    Fallback for str / other shapes."""
    if not samples:
        return {"sample_count": 0}
    first = samples[0]
    sym_counter = Counter()
    col_counts = Counter()
    row_counts = Counter()
    for s in samples:
        if isinstance(s, list):
            col_counts[len(s)] += 1
            for col in s:
                if isinstance(col, str):
                    rows = [p for p in col.split("-") if p]
                    row_counts[len(rows)] += 1
                    for sym in rows:
                        sym_counter[sym] += 1
        elif isinstance(s, str):
            col_counts[("str", s.count("|"))] += 1
            for seg in s.split("|"):
                for cell in seg.split(","):
                    cell = cell.strip()
                    if cell:
                        sym_counter[cell] += 1
    return {
        "sample_type": type(first).__name__,
        "sample_count": len(samples),
        "sample_first_repr": repr(first)[:200],
        "column_count_distribution": dict(col_counts.most_common(5)),
        "rows_per_column_distribution": dict(row_counts.most_common(5)),
        "distinct_symbols_count": len(sym_counter),
        "symbols": dict(sym_counter.most_common(30)),
    }


_PAYLINE_RE = re.compile(r"(-?\d+):(-?\d+)-(-?\d+)\(([^)]*)\)")


def _decompose_paylines(samples: list) -> dict:
    """PayoutByPayline format: `line_id:pay_id-mult(positions);` per record.

    Two semantic classes, distinguished by `line_id` sign:
      * `line_id >= 1` — normal payline hit (one of N paylines fired)
      * `line_id == -1` — **board-wide / scatter-like win** (doesn't
         go through a specific payline). 策划 confirmed: this is the
         machine's 盘面奖 channel, NOT a negative pay_id as earlier
         misread.

    Earlier probe regex required positive line_id so board-win records
    were miscategorized as "odd records". Fixed.
    """
    payline_records = 0   # line_id >= 1
    board_records = 0     # line_id == -1 (scatter / board-wide)
    other_odd = Counter()
    payline_pay_ids = Counter()
    board_pay_ids = Counter()
    payline_mults = Counter()
    board_mults = Counter()
    payline_positions = Counter()
    board_positions = Counter()
    for s in samples:
        if not isinstance(s, str) or not s:
            continue
        for rec in s.split(";"):
            rec = rec.strip()
            if not rec:
                continue
            m = _PAYLINE_RE.match(rec)
            if not m:
                other_odd[rec[:40]] += 1
                continue
            line_id = int(m.group(1))
            pid = int(m.group(2))
            mult = int(m.group(3))
            positions = m.group(4)
            n_pos = len([p for p in positions.split(",") if p.strip()])
            if line_id >= 1:
                payline_records += 1
                payline_pay_ids[pid] += 1
                payline_mults[mult] += 1
                payline_positions[n_pos] += 1
            elif line_id == -1:
                board_records += 1
                board_pay_ids[pid] += 1
                board_mults[mult] += 1
                board_positions[n_pos] += 1
            else:
                other_odd[f"line_id={line_id}"] += 1
    return {
        "payline_records (line_id >= 1)": payline_records,
        "board_records  (line_id == -1)": board_records,
        "other_odd_count": sum(other_odd.values()),
        "other_odd_samples": dict(other_odd.most_common(5)),
        "payline: pay_id range": (min(payline_pay_ids), max(payline_pay_ids)) if payline_pay_ids else None,
        "payline: pay_id distinct": len(payline_pay_ids),
        "payline: mult range": (min(payline_mults), max(payline_mults)) if payline_mults else None,
        "payline: positions distribution": dict(payline_positions.most_common(10)),
        "board: pay_id distinct": len(board_pay_ids),
        "board: pay_id top": dict(board_pay_ids.most_common(10)),
        "board: mult top": dict(board_mults.most_common(10)),
        "board: positions distribution": dict(board_positions.most_common(10)),
    }


def _probe_one_machine(machine: str, mode: int, max_chunks: int | None) -> list[str]:
    out = []
    out.append(f"# Schema probe — {machine} mode_{mode}")
    out.append("")

    chunks = list(_iter_chunks(machine, mode))
    if not chunks:
        out.append(f"*no chunks found under dev_rawdata/{machine}/mode_{mode}/*")
        return out
    if max_chunks is not None:
        chunks = chunks[:max_chunks]
    out.append(f"Chunks scanned: **{len(chunks)}** (first: `{chunks[0].name}`, last: `{chunks[-1].name}`)")
    out.append("")

    # --- Envelope layer -------------------------------------------------
    env0 = _load_env(chunks[0])
    env_shape = _probe_envelope(env0)
    out.append("## Envelope keys (top-level)")
    for k, shape in sorted(env_shape.items()):
        out.append(f"- `{k}`: {shape}")
    out.append("")

    # --- Response / robot layer ----------------------------------------
    resp0 = env0.get("response") or []
    n_robots = len(resp0)
    robot_keys = _probe_robot(resp0[0]) if n_robots else []
    out.append("## Response-level")
    out.append(f"- `response`: list of {n_robots} robots")
    out.append(f"- per-robot keys: `{robot_keys}`")
    out.append("")

    # --- analysisResult layer ------------------------------------------
    ar_detail = _probe_analysis(resp0[0]) if n_robots else {}
    out.append("## `analysisResult` structure (first robot, first chunk)")
    out.append("```json")
    out.append(json.dumps(ar_detail, indent=2, ensure_ascii=False)[:2500])
    out.append("```")
    out.append("")

    # --- Round layer: enumerate over all chunks ------------------------
    round_key_counter = Counter()  # key -> present count
    keys_by_spin_type = defaultdict(Counter)  # spin_type -> Counter(key -> count)
    rounds_by_spin_type = Counter()
    remarks_counter = Counter()
    stop_symbols_samples = []
    payline_samples = []
    credits_symbols_samples = []
    symbol_index_rewards_samples = []
    reward_last_node_samples = Counter()
    payout_id_win_sample_keys = Counter()
    payout_id_win_sample_values = []
    rtp_id_values = Counter()
    spin_times_values = Counter()
    reel_skin_samples = Counter()
    # Cross-field consistency tallies
    pbp_pay_ids_per_round = []
    piw_pay_ids_per_round = []
    # Nested composite samples
    total_rounds = 0

    for cp in chunks:
        env = _load_env(cp)
        for robot in env.get("response") or []:
            rounds = _parse_round_result(robot)
            for r in rounds:
                total_rounds += 1
                st = r.get("SpinType")
                rounds_by_spin_type[st] += 1
                for k in r.keys():
                    round_key_counter[k] += 1
                    keys_by_spin_type[st][k] += 1
                rm = r.get("ReMarks")
                if rm:
                    remarks_counter[rm] += 1
                ssc = r.get("StopSymbolsByCol")
                if ssc and len(stop_symbols_samples) < 200:
                    stop_symbols_samples.append(ssc)
                pbp = r.get("PayoutByPayline")
                if isinstance(pbp, str) and pbp and len(payline_samples) < 500:
                    payline_samples.append(pbp)
                cs = r.get("CreditsSymbols")
                if isinstance(cs, str) and cs and len(credits_symbols_samples) < 50:
                    credits_symbols_samples.append(cs[:80])
                sir = r.get("SymbolIndexToRewards")
                if sir and len(symbol_index_rewards_samples) < 50:
                    symbol_index_rewards_samples.append(
                        sir[:80] if isinstance(sir, str) else str(sir)[:80]
                    )
                rln = r.get("RewardLastNode")
                if isinstance(rln, list):
                    for entry in rln:
                        reward_last_node_samples[str(entry)] += 1
                piw = r.get("PayoutIdToWinAmount")
                pbp_ids = set()
                piw_ids = set()
                if isinstance(pbp, str):
                    for m in _PAYLINE_RE.finditer(pbp):
                        pbp_ids.add(int(m.group(2)))
                if isinstance(piw, dict):
                    for k, v in piw.items():
                        try:
                            piw_ids.add(int(k))
                        except (ValueError, TypeError):
                            pass
                        payout_id_win_sample_keys[str(k)] += 1
                        if len(payout_id_win_sample_values) < 50:
                            payout_id_win_sample_values.append(v)
                if pbp_ids or piw_ids:
                    pbp_pay_ids_per_round.append(pbp_ids)
                    piw_pay_ids_per_round.append(piw_ids)
                rtp_v = r.get("RTPId")
                if rtp_v is not None:
                    rtp_id_values[rtp_v] += 1
                sp_t = r.get("SpinTimes")
                if sp_t is not None:
                    spin_times_values[sp_t] += 1
                rs = r.get("ReelSkin")
                if rs is not None:
                    reel_skin_samples[str(rs)[:40]] += 1

    out.append("## Round layer")
    out.append(f"- total rounds across {len(chunks)} chunks: **{total_rounds:,}**")
    out.append("")

    out.append("### Global per-key presence")
    for k, n in sorted(round_key_counter.items()):
        pct = 100 * n / total_rounds if total_rounds else 0
        out.append(f"- `{k}`: {n:,}  ({pct:.1f}%)")
    out.append("")

    out.append("### SpinType distribution")
    for st, n in rounds_by_spin_type.most_common():
        pct = 100 * n / total_rounds if total_rounds else 0
        out.append(f"- SpinType `{st}`: {n:,}  ({pct:.1f}%)")
    out.append("")

    out.append("### Per-SpinType field coverage (just keys with <100% presence)")
    out.append("Highlights fields that are SpinType-specific — a field missing from one"
               " type but present in another usually indicates a schema variation.")
    out.append("")
    for st in sorted(rounds_by_spin_type.keys(), key=lambda x: -(rounds_by_spin_type[x])):
        n_rounds_st = rounds_by_spin_type[st]
        if n_rounds_st < 3:
            continue
        type_keys = keys_by_spin_type[st]
        sparse = []
        for k in sorted(round_key_counter.keys()):
            cnt = type_keys.get(k, 0)
            pct = 100 * cnt / n_rounds_st if n_rounds_st else 0
            if pct < 100:
                sparse.append(f"`{k}`={pct:.0f}%")
        out.append(f"- SpinType `{st}` ({n_rounds_st:,} rounds): {', '.join(sparse) if sparse else 'all keys present'}")
    out.append("")

    # --- Composite field internals -------------------------------------
    out.append("## Composite field internals")
    out.append("")

    out.append("### `ReMarks` prefix distribution")
    decomp = _decompose_remarks(remarks_counter)
    for bucket, n in decomp["buckets"].most_common(15):
        sample = decomp["samples"][bucket]
        out.append(f"- `{bucket}`: {n:,}  example: `{sample[:80]}`")
    out.append("")

    out.append("### `StopSymbolsByCol` structure")
    ss_decomp = _decompose_stop_symbols(stop_symbols_samples)
    for k, v in ss_decomp.items():
        out.append(f"- {k}: `{v}`")
    out.append("")

    out.append("### `PayoutByPayline` structure")
    pbp_decomp = _decompose_paylines(payline_samples)
    for k, v in pbp_decomp.items():
        out.append(f"- {k}: `{v}`")
    out.append("")

    out.append("### `CreditsSymbols` samples (≤5)")
    for s in list(set(credits_symbols_samples))[:5]:
        out.append(f"- `{s}`")
    out.append("")

    out.append("### `SymbolIndexToRewards` samples (≤5)")
    for s in list(set(symbol_index_rewards_samples))[:5]:
        out.append(f"- `{s}`")
    out.append("")

    out.append("### `RewardLastNode` distinct entries (across all rounds)")
    for entry, n in reward_last_node_samples.most_common(30):
        out.append(f"- `{entry}`: {n:,}")
    out.append("")

    out.append("### `ReelSkin` distinct values (top 10)")
    for s, n in reel_skin_samples.most_common(10):
        out.append(f"- `{s}`: {n:,}")
    out.append("")

    out.append("### `RTPId` distinct values")
    for v, n in rtp_id_values.most_common(15):
        out.append(f"- `{v}`: {n:,}")
    out.append("")

    out.append("### `SpinTimes` distinct values (top 10)")
    for v, n in spin_times_values.most_common(10):
        out.append(f"- `{v}`: {n:,}")
    out.append("")

    out.append("### `PayoutIdToWinAmount` pay_id keys (top 20)")
    for k, n in payout_id_win_sample_keys.most_common(20):
        out.append(f"- `{k}`: {n:,}")
    # Win values range
    try:
        nums = [float(v) for v in payout_id_win_sample_values if v is not None]
        if nums:
            out.append(f"- value range: min={min(nums):,.0f}  max={max(nums):,.0f}  n_samples={len(nums)}")
            neg = [v for v in nums if v < 0]
            if neg:
                out.append(f"- **NEGATIVE VALUES**: {len(neg)}  samples={neg[:5]}")
    except Exception:
        pass
    out.append("")

    # --- Cross-field consistency ---------------------------------------
    out.append("## Cross-field consistency")
    out.append("")
    if pbp_pay_ids_per_round:
        mismatches = 0
        only_in_pbp = Counter()
        only_in_piw = Counter()
        for pbp_ids, piw_ids in zip(pbp_pay_ids_per_round, piw_pay_ids_per_round):
            if pbp_ids != piw_ids:
                mismatches += 1
                for x in pbp_ids - piw_ids:
                    only_in_pbp[x] += 1
                for x in piw_ids - pbp_ids:
                    only_in_piw[x] += 1
        out.append(f"- rounds with both PayoutByPayline and PayoutIdToWinAmount: {len(pbp_pay_ids_per_round):,}")
        out.append(f"- rounds where pay_id sets differ: {mismatches:,}")
        if only_in_pbp:
            out.append(f"- pay_ids appearing in PayoutByPayline but NOT in PayoutIdToWinAmount: {dict(only_in_pbp.most_common(10))}  ← **potential board-win / non-payline markers**")
        if only_in_piw:
            out.append(f"- pay_ids in PayoutIdToWinAmount but NOT in PayoutByPayline: {dict(only_in_piw.most_common(10))}")
    out.append("")

    out.append("---")
    out.append(f"*probe generated from {total_rounds:,} rounds across {len(chunks)} chunks*")
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--machine", required=True)
    p.add_argument("--mode", type=int, default=1)
    p.add_argument("--max-chunks", type=int, default=None,
                   help="cap chunks scanned (default: all)")
    p.add_argument("--output", type=Path, default=None,
                   help="write markdown here instead of stdout")
    args = p.parse_args()

    lines = _probe_one_machine(args.machine, args.mode, args.max_chunks)
    text = "\n".join(lines)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output} ({len(text):,} bytes)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
