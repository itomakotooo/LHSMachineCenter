"""One-time cleanup: remove data rooted at the pre-variants
underlying machine names (M6, M12, ..., M273) from local filesystem
and side configs.

After stage 4 of the variants rollout the 26 underlying keys that
carry variants are no longer valid machine rows — 166 variant keys
replaced them in machines.json. Data files keyed by the old
underlying names are now orphaned:

  * rawdata/<M>/                            (gitignored, regenerable)
  * rawdata/_index.json entries <M>|<mode>  (gitignored)
  * reports/<M>/                            (gitignored, regenerable)
  * dev_reports/<M>/                        (gitignored)
  * configs/paytables/<M>_mode<N>.json      (gitignored)
  * configs/bcm_pairings.json[machines][<M>] (TRACKED — commit the delta)
  * configs/machines_static.json machines[<M>] (gitignored)

Policy: the user OK'd a wholesale delete — variant rows will
regenerate all of these on first sample / generate-report /
refresh. The tradeoff is lower fidelity than reformatting under
variant keys (copying M273 → M273$0$ etc.), but the user explicitly
waived that: "本地的 rawdata 我全删了都行".

Usage:
    python scripts/cleanup_pre_variant_data.py              # dry-run (default safe)
    python scripts/cleanup_pre_variant_data.py --apply      # actually delete
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HALLS_JSON = ROOT / "configs" / "machine_halls.json"


def _underlying_machines() -> set[str]:
    """Source of truth: variants_map values in halls cache. Never
    hard-coded — if upstream adds/removes variants, re-running the
    script picks up the correct set after a halls refresh."""
    if not HALLS_JSON.exists():
        raise SystemExit(
            f"halls cache missing: {HALLS_JSON}. Refresh first via "
            "POST /api/machines/halls/refresh."
        )
    data = json.loads(HALLS_JSON.read_text(encoding="utf-8"))
    vmap = data.get("variants_map") or {}
    return set(vmap.values())


def _plan_dirs(underlying: set[str]) -> list[tuple[str, Path]]:
    """Enumerate per-machine directories to delete, tagged with a
    human label for the plan printout."""
    targets: list[tuple[str, Path]] = []
    for root_name in ("rawdata", "reports", "dev_reports"):
        root_p = ROOT / root_name
        if not root_p.is_dir():
            continue
        for u in sorted(underlying):
            d = root_p / u
            if d.is_dir():
                targets.append((root_name, d))
    return targets


def _plan_paytables(underlying: set[str]) -> list[Path]:
    pt = ROOT / "configs" / "paytables"
    if not pt.is_dir():
        return []
    return sorted(
        p for p in pt.iterdir()
        if any(p.name.startswith(f"{u}_") for u in underlying)
    )


def _plan_index_entries(underlying: set[str]) -> list[str]:
    idx = ROOT / "rawdata" / "_index.json"
    if not idx.is_file():
        return []
    try:
        data = json.loads(idx.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = data.get("entries") or {}
    return sorted(k for k in entries if k.split("|", 1)[0] in underlying)


def _plan_bcm(underlying: set[str]) -> list[str]:
    bcm_path = ROOT / "configs" / "bcm_pairings.json"
    if not bcm_path.is_file():
        return []
    try:
        data = json.loads(bcm_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    machines = data.get("machines") or {}
    return sorted(k for k in machines if k in underlying)


def _plan_machines_static(underlying: set[str]) -> list[str]:
    ms_path = ROOT / "configs" / "machines_static.json"
    if not ms_path.is_file():
        return []
    try:
        data = json.loads(ms_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    machines = data.get("machines") or {}
    return sorted(k for k in machines if k in underlying)


def _apply_dirs(dirs: list[tuple[str, Path]]) -> int:
    deleted = 0
    for label, d in dirs:
        shutil.rmtree(d)
        deleted += 1
    return deleted


def _apply_paytables(files: list[Path]) -> int:
    for p in files:
        p.unlink()
    return len(files)


def _apply_index_entries(keys: list[str]) -> int:
    if not keys:
        return 0
    idx = ROOT / "rawdata" / "_index.json"
    data = json.loads(idx.read_text(encoding="utf-8"))
    entries = data.get("entries") or {}
    for k in keys:
        entries.pop(k, None)
    data["entries"] = entries
    idx.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(keys)


def _apply_bcm(keys: list[str]) -> int:
    if not keys:
        return 0
    bcm_path = ROOT / "configs" / "bcm_pairings.json"
    data = json.loads(bcm_path.read_text(encoding="utf-8"))
    machines = data.get("machines") or {}
    for k in keys:
        machines.pop(k, None)
    data["machines"] = machines
    bcm_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(keys)


def _apply_machines_static(keys: list[str]) -> int:
    """Simpler than selective edit: the fleet-wide aggregate fields
    (feature_distribution / mechanics_distribution) would need
    recomputing after 26 entries leave, and the cache bootstraps
    on next read anyway. Delete the whole file and let the app
    rebuild."""
    if not keys:
        return 0
    ms_path = ROOT / "configs" / "machines_static.json"
    ms_path.unlink()
    return 1  # "1 file deleted" rather than K entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete. Without this, prints the plan only.",
    )
    args = parser.parse_args()

    underlying = _underlying_machines()
    print(f"Underlying machines with variants: {len(underlying)}")
    print(f"  {sorted(underlying)}\n")

    dirs = _plan_dirs(underlying)
    paytables = _plan_paytables(underlying)
    index_keys = _plan_index_entries(underlying)
    bcm_keys = _plan_bcm(underlying)
    static_keys = _plan_machines_static(underlying)

    # Buckets per root for the plan summary.
    per_root: dict[str, int] = {}
    for label, _ in dirs:
        per_root[label] = per_root.get(label, 0) + 1

    print("Plan:")
    for label, count in sorted(per_root.items()):
        print(f"  rmtree {label}/<M> (x{count})")
    print(f"  unlink configs/paytables/<M>_mode<N>.json (x{len(paytables)})")
    print(f"  patch  rawdata/_index.json entries (-{len(index_keys)})")
    print(f"  patch  configs/bcm_pairings.json machines (-{len(bcm_keys)})")
    print(f"  unlink configs/machines_static.json (x{1 if static_keys else 0})")

    if not args.apply:
        print("\n(dry-run) pass --apply to execute")
        return

    # Execute in order: dirs → paytables → index → bcm → static.
    # Independent operations, but do them deterministically so the
    # apply log reads cleanly.
    n_dirs = _apply_dirs(dirs)
    n_pt = _apply_paytables(paytables)
    n_idx = _apply_index_entries(index_keys)
    n_bcm = _apply_bcm(bcm_keys)
    n_static = _apply_machines_static(static_keys)

    print("\nApplied:")
    print(f"  removed {n_dirs} per-machine directories")
    print(f"  removed {n_pt} paytable files")
    print(f"  removed {n_idx} rawdata index entries")
    print(f"  removed {n_bcm} bcm_pairings entries")
    print(f"  removed machines_static.json: {'yes' if n_static else 'no'}")


if __name__ == "__main__":
    main()
