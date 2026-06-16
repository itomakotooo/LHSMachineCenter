"""Framework-pass byte-identical gate (supersedes the M15-only _p5_gate.py —
use this one for any machine): a registered machine's report ANALYSIS content
must be stable across closure surgery, for machines that do not use the new
mechanisms.

Strips volatile + version metadata (which legitimately changes when the closure
is edited) and canonicalizes the rest.

Usage:
  python _fwpass_gate.py write M15 1     # baseline -> cache/_fwpass_gate/M15_1.json
  python _fwpass_gate.py check M15 1     # compare; exit 1 on diff
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent

_VOLATILE_TOP = {
    "run_id", "report_id", "storage",
    "analyzer_version", "effective_analyzer_version", "effective_analyzer_version_error",
    "code_md5",  # changes whenever a closure file is edited
}


def _blank_timestamps(obj):
    if isinstance(obj, dict):
        return {
            k: ("<TS>" if k.endswith("_at") else _blank_timestamps(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_blank_timestamps(x) for x in obj]
    return obj


def _strip(d):
    if not isinstance(d, dict):
        return d
    stripped = {k: v for k, v in d.items() if k not in _VOLATILE_TOP}
    return _blank_timestamps(stripped)


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _gen(machine: str, mode: int):
    from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks
    chunk_dir = _REPO / "rawdata" / machine / f"mode_{mode}"
    if not chunk_dir.exists():
        print(f"FATAL: chunks absent at {chunk_dir}")
        sys.exit(2)
    with tempfile.TemporaryDirectory() as tmp:
        summary = generate_report_from_chunks(
            machine, mode, chunk_dir=chunk_dir, output_dir=Path(tmp)
        )
    content = _strip(summary)
    canon = _canon(content)
    h = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    return content, canon, h


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    mode_arg, machine, mmode = sys.argv[1], sys.argv[2], int(sys.argv[3])
    golden_path = _REPO / "cache" / "_fwpass_gate" / f"{machine}_{mmode}.json"

    content, canon, h = _gen(machine, mmode)
    ric = content.get("rtp_integrity_check", {})
    rtp = content.get("rtp", {})
    sig = {
        "integrity_passed": ric.get("passed"),
        "rtp_pct": rtp.get("achieved_rtp_pct") or rtp.get("rtp_pct"),
        "pi_panels": len((content.get("player_impact") or {})),
    }

    if mode_arg == "write":
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(canon, encoding="utf-8")
        print(f"BASELINE written: {golden_path}")
        print(f"  content sha256: {h}")
        print(f"  signals: {sig}")
        sys.exit(0)

    if not golden_path.exists():
        print(f"FATAL: golden absent at {golden_path}; run 'write' first")
        sys.exit(2)
    golden_canon = golden_path.read_text(encoding="utf-8")
    golden_h = hashlib.sha256(golden_canon.encode("utf-8")).hexdigest()
    print(f"  {machine} mode {mmode}")
    print(f"  now    sha256: {h}")
    print(f"  golden sha256: {golden_h}")
    print(f"  signals: {sig}")
    if h == golden_h:
        print(f"GATE PASS: {machine}|{mmode} analysis content byte-identical to baseline.")
        sys.exit(0)
    try:
        now_obj = json.loads(canon)
        gold_obj = json.loads(golden_canon)
        diff_keys = [k for k in sorted(set(now_obj) | set(gold_obj))
                     if now_obj.get(k) != gold_obj.get(k)]
        print(f"GATE FAIL: differing top-level keys: {diff_keys}")
        if "player_impact" in diff_keys:
            npi = now_obj.get("player_impact", {})
            gpi = gold_obj.get("player_impact", {})
            pidiff = [k for k in sorted(set(npi) | set(gpi)) if npi.get(k) != gpi.get(k)]
            print(f"  player_impact differing sub-keys: {pidiff}")
    except Exception as e:
        print(f"  (diff introspection failed: {e})")
    sys.exit(1)


if __name__ == "__main__":
    main()
