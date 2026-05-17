"""Canonical real-machine md5 lookup — single source of truth (Ticket P1-B1).

Provides ``lookup_machine_md5`` — the authoritative helper for reading a
machine's stamped ``(config_md5, code_md5)`` tuple from ``configs/machines.json``.

Before this module existed the same logic was duplicated in:
  - ``fresh_slotlab/player_impact_analyzer.py:_lookup_machine_md5``  (FLAT schema)
  - ``src/web_console/backend/app.py:_get_machine_md5``              (FLAT + modesMd5)

Both callers now import from here; the app.py wrapper adds its per-mode
modesMd5 extension on top of the canonical real-schema path returned here.

---

Virtual-machine cousin
~~~~~~~~~~~~~~~~~~~~~~
``compute_machine_md5_for_mode`` in
``slot_designer/core/backend/machine_version.py`` is the per-mode md5
helper for VIRTUAL machines.  It reads ``machines_virtual.json`` and
hashes spec + weights + plugins rather than looking up a stamped value.
The two helpers serve different schemas and are intentionally NOT merged:

  Real machine  →  ``lookup_machine_md5``       (configs/machines.json, FLAT schema)
  Virtual machine →  ``compute_machine_md5_for_mode`` (machines_virtual.json, per-mode modesMd5)

Per ``session_artifacts/_arch/04_architecture_proposal_v5.md §6.1`` and
ticket §4 (out-of-scope: merging real and virtual md5 computations).

---

Import-time side effects
~~~~~~~~~~~~~~~~~~~~~~~~
This module has NONE.  Per memory
``feedback_subprocess_import_suicide_and_module_globals.md``: no
``app = build_app()``, no global state that changes on import, no
subprocess spawning.  Safe to import inside ``player_impact_analyzer.py``
which is routinely spawned as a subprocess by the backend.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Repo root resolved relative to this file's location.
# fresh_slotlab/machine_md5.py  →  parent = fresh_slotlab/  →  parent.parent = repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MACHINES_CONFIG = _REPO_ROOT / "configs" / "machines.json"


def lookup_machine_md5(
    machine: str,
    machines_config_path: Optional[Path] = None,
) -> tuple[str, str]:
    """Return ``(config_md5, code_md5)`` for *machine* from ``machines.json``.

    Reads the FLAT real-machine schema — ``configSummaryMd5`` /
    ``codeSummaryMd5`` at the top level of each machine entry.  Does NOT
    interpret ``modesMd5`` (per-mode blocks used by virtual machines);
    callers that need per-mode dispatch should add that logic on top of
    this call (see ``src/web_console/backend/app.py:_get_machine_md5``).

    Parameters
    ----------
    machine:
        Machine identifier string, e.g. ``"M14"``.
    machines_config_path:
        Explicit path to ``machines.json``.  When ``None`` (default) the
        function resolves the path relative to the repo root via this
        module's ``__file__``.  Callers in ``app.py`` supply
        ``MACHINES_CONFIG`` / a fixture path so tests remain hermetic.

    Returns
    -------
    tuple[str, str]
        ``(config_md5, code_md5)`` both non-empty when the machine is
        registered.  Returns ``("", "")`` on any error (missing file,
        malformed JSON, unknown machine) — MD5 tagging is best-effort;
        reports remain valid without it.
    """
    cfg_path: Path = (
        machines_config_path if machines_config_path is not None
        else _DEFAULT_MACHINES_CONFIG
    )
    try:
        if not cfg_path.exists():
            return "", ""
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        for m in data.get("machines", []):
            if m.get("machine") == machine:
                return (
                    str(m.get("configSummaryMd5", "")),
                    str(m.get("codeSummaryMd5", "")),
                )
    except (OSError, json.JSONDecodeError, TypeError):
        # Best-effort: missing / malformed machines.json is not fatal.
        pass
    return "", ""
