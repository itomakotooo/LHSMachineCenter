"""play_types._machine_config — MachinePlayTypeConfig + JSON persistence.

Per 04_v2.md §6 (per-machine config layer) and §9-rev Phase 1 deliverable 8.

MachinePlayTypeConfig is the per-(machine, mode) record that captures:
  - Which play-type plugins are active (list of FEATURE_IDs).
  - The SpinType → play-type-feature-name mapping (st_map).
  - Per-plugin config blobs (plugin-specific parameters that cannot be
    auto-detected from rawdata alone, e.g. trigger pay_id override).
  - Onboarding-alert markers (signals that require human review before the
    config is considered complete).

Storage path
------------
  configs/play_type_configs/<machine_id>/mode_<mode>.json

The path is relative to the repo root (two parents up from this file's
location in fresh_slotlab/analyzer/play_types/).

per_machine_config_hash()
-------------------------
Returns a 12-char sha256 hex hash of the config's canonical JSON
representation (sorted keys, no whitespace variation).  Mirrors the hashing
style of machine_md5.py (sha256 + hexdigest[:12]) and versioning.py
(CRLF-normalised source content → sha256).  Used by the version model
(§7.2 Step 4) to detect config changes that should invalidate cached reports.

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# Repo root: three parents up from fresh_slotlab/analyzer/play_types/_machine_config.py
# → fresh_slotlab/analyzer/play_types/ → fresh_slotlab/analyzer/ → fresh_slotlab/ → repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_PLAY_TYPE_CONFIGS_ROOT = _REPO_ROOT / "configs" / "play_type_configs"


@dataclass
class MachinePlayTypeConfig:
    """Per-(machine, mode) play-type configuration record.

    Fields
    ------
    machine_id : str
        Machine identifier (e.g. "M14", "M272$BCM$0$").
    mode : int
        RTP mode integer (1, 2, 5, 7, ...).
    active_plugins : list[str]
        FEATURE_IDs of play-type plugins active for this (machine, mode).
        Order is the topo-sorted MECHANIC_DEPS order; serialised in that order
        so the JSON is deterministic and the hash stable.
    st_map : dict[str, str]
        SpinType (as string key) → play-type FEATURE_ID mapping.
        Auto-detected by detect_play_types(); can be overridden per-plugin
        config.  Example: {"13": "lockrepin_base", "0": "pure_paid"}.
    plugin_configs : dict[str, dict[str, Any]]
        Per-plugin config blobs keyed by FEATURE_ID.  Each blob contains
        plugin-specific parameters (e.g. trigger pay_id, remark prefix).
        Empty dict if no plugin-specific config is needed.
    onboarding_alerts : list[str]
        Human-readable alert messages for signals that require review.
        Empty list = config is complete.  Non-empty = ONBOARDING ALERT;
        the config is cached but marked incomplete pending human review.
        Example: ["unknown_bonus: ST=99 claimed by 0 plugins — review needed"]
    """

    machine_id: str
    mode: int
    active_plugins: list = field(default_factory=list)
    st_map: dict = field(default_factory=dict)
    plugin_configs: dict = field(default_factory=dict)
    onboarding_alerts: list = field(default_factory=list)

    # ------------------------------------------------------------------
    # JSON persistence
    # ------------------------------------------------------------------

    @classmethod
    def config_path(
        cls,
        machine_id: str,
        mode: int,
        configs_root: Optional[Path] = None,
    ) -> Path:
        """Return the JSON file path for (machine_id, mode).

        Parameters
        ----------
        machine_id:
            Machine identifier (e.g. "M14").  Forward slashes in variant
            IDs (e.g. "M272$BCM$0$") are replaced with "__" for filesystem
            safety.
        mode:
            Integer mode.
        configs_root:
            Override the configs root directory.  Production passes None to
            use the default (``configs/play_type_configs/`` in repo root).
            Tests supply a tmp_path.

        Returns
        -------
        Path
            Absolute path to the JSON file.  Parent directories may not
            exist yet; callers must create them before writing.
        """
        root = configs_root if configs_root is not None else _PLAY_TYPE_CONFIGS_ROOT
        # Sanitise machine_id for filesystem use: replace "$" with "__"
        safe_id = machine_id.replace("$", "__")
        return root / safe_id / f"mode_{mode}.json"

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (suitable for JSON output).

        Keys are sorted for determinism.  The schema version field allows
        future migration.
        """
        return {
            "_schema_version": 1,
            "machine_id": self.machine_id,
            "mode": self.mode,
            "active_plugins": self.active_plugins,
            "st_map": self.st_map,
            "plugin_configs": self.plugin_configs,
            "onboarding_alerts": self.onboarding_alerts,
        }

    def to_json(self, *, indent: int = 2) -> str:
        """Return the canonical JSON string for this config.

        Uses sorted keys and the given indent for human readability.
        The canonical form (indent=None, no separators spacing) is used
        for hashing; this form (indent=2) is used for on-disk storage.
        """
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    def write(
        self,
        configs_root: Optional[Path] = None,
    ) -> Path:
        """Write config to disk as JSON.

        Creates parent directories as needed.

        Parameters
        ----------
        configs_root:
            Override the configs root.  Production passes None.

        Returns
        -------
        Path
            The path the file was written to.

        Raises
        ------
        OSError
            On any filesystem error (disk full, permission denied, etc.).
            Never silently swallowed per
            memory/feedback_no_silent_swallow.md.
        """
        path = self.config_path(self.machine_id, self.mode, configs_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def read(
        cls,
        machine_id: str,
        mode: int,
        configs_root: Optional[Path] = None,
    ) -> Optional["MachinePlayTypeConfig"]:
        """Read config from disk, or return None if the file does not exist.

        Parameters
        ----------
        machine_id:
            Machine identifier.
        mode:
            Integer mode.
        configs_root:
            Override the configs root.  Production passes None.

        Returns
        -------
        MachinePlayTypeConfig
            Parsed config, or None if the file does not exist.

        Raises
        ------
        json.JSONDecodeError
            If the file exists but contains malformed JSON.  Not silently
            swallowed — callers must handle this explicitly.
        KeyError
            If the JSON is valid but missing required fields.
        """
        path = cls.config_path(machine_id, mode, configs_root)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            machine_id=data["machine_id"],
            mode=data["mode"],
            active_plugins=data.get("active_plugins", []),
            st_map=data.get("st_map", {}),
            plugin_configs=data.get("plugin_configs", {}),
            onboarding_alerts=data.get("onboarding_alerts", []),
        )

    # ------------------------------------------------------------------
    # Version hash
    # ------------------------------------------------------------------

    def per_machine_config_hash(self) -> str:
        """Return 12-char sha256 hex of this config's canonical representation.

        Mirrors the hashing style in machine_md5.py / versioning.py:
        sha256 of content bytes (CRLF-normalised) → hexdigest[:12].

        The canonical representation is:
          json.dumps(self.to_dict(), sort_keys=True, separators=(',', ':'))

        Sorted keys + compact separators eliminate whitespace/order variation
        so the hash depends only on the config content.  This is used by the
        version model (§7.2 Step 4) to detect config changes that invalidate
        cached reports.

        Returns
        -------
        str
            12-character lowercase hex string.
        """
        canonical = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        # CRLF-normalise to match versioning.py FIX-2 convention.
        content = canonical.encode("utf-8").replace(b"\r\n", b"\n")
        return hashlib.sha256(content).hexdigest()[:12]
