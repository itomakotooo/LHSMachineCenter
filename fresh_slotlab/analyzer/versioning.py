"""compute_effective_analyzer_version — per-(machine, mode) hash composition.

Per ticket P2-A1 §3 C2 and 04_architecture_proposal_v5.md §4.1.

Algorithm (verbatim from §4.1)
-------------------------------
  h = sha256(base_hash)
  for fid in sorted(set(machine_features)):
      h.update(b"\\x00" + fid.encode() + b"=" + feature_hashes[fid].encode())
  if mode is not None:
      h.update(b"\\x00mode=" + str(mode).encode())
  return h.hexdigest()[:12]

Where:
  base_hash      — 12-hex hash of fresh_slotlab/analyzer/core/*.py (universal code)
  feature_hashes — {feature_id: 12-hex hash} from feature_registry
  machine_features — list[str] of feature IDs the machine declares
  mode           — int | None; if provided, the per-mode dimension is included

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

import hashlib
from typing import Optional


def compute_effective_analyzer_version(
    *,
    base_hash: str,
    feature_hashes: dict[str, str],
    machine_features: list[str],
    mode: Optional[int] = None,
) -> str:
    """Return the 12-char hex effective_analyzer_version for one (machine, mode).

    This is the per-machine hash that invalidates only machines using a
    changed feature.  Composition algorithm per 04_v5 §4.1:

        h = sha256(base_hash)
        for fid in sorted(set(machine_features)):
            h.update(b"\\x00" + fid.encode() + b"=" + feature_hashes[fid].encode())
        if mode is not None:
            h.update(b"\\x00mode=" + str(mode).encode())
        return h.hexdigest()[:12]

    Parameters
    ----------
    base_hash:
        12-hex hash of the universal analyzer core code.
    feature_hashes:
        Mapping of feature_id → 12-hex hash for every registered feature.
        Only features in *machine_features* are included in the digest.
    machine_features:
        Feature IDs declared by this machine.  Duplicates are deduplicated;
        order does not matter (sorted before hashing → deterministic).
    mode:
        Integer mode.  When provided, the mode dimension is included so that
        per-mode effective versions differ when applicable per 07_decision_v5 P1.

    Returns
    -------
    str
        12-character lowercase hex string.

    Raises
    ------
    KeyError
        If a feature in *machine_features* is not present in *feature_hashes*.
        This is a programming error — register features before calling.
    ValueError
        If *base_hash* is empty.
    """
    if not base_hash:
        raise ValueError("base_hash must not be empty")

    h = hashlib.sha256(base_hash.encode())

    for fid in sorted(set(machine_features)):
        fhash = feature_hashes[fid]  # KeyError is intentional — see docstring
        h.update(b"\x00" + fid.encode() + b"=" + fhash.encode())

    if mode is not None:
        h.update(b"\x00mode=" + str(mode).encode())

    return h.hexdigest()[:12]
