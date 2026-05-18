"""Tests for scripts/deploy/SlotConsole.xml Task Scheduler definition (P4-T3).

Pure Python XML parsing — cross-platform (no WIN_ONLY mark needed).

Memory feedback cited:
- feedback_enumerate_safety_paths.md — every critical invariant (dynamic path,
  non-SYSTEM principal, BootTrigger, RestartOnFailure, LogonType) gets its own
  test so regressions are caught individually.

Inject-bug recipe:
  BUG-G (dynamic repo path):
    In SlotConsole.xml, change:
        <Arguments>-NoProfile -ExecutionPolicy Bypass -File "%SLOT_REPO_ROOT%\\scripts\\start_console.ps1" ...</Arguments>
    to:
        <Arguments>-NoProfile -ExecutionPolicy Bypass -File "C:\\repo\\scripts\\start_console.ps1" ...</Arguments>
    Expected: test_xml_uses_repo_root_env_not_hardcoded goes RED.

  BUG-H (non-SYSTEM principal):
    In SlotConsole.xml, change:
        <UserId>%USERNAME%</UserId>
    to:
        <UserId>SYSTEM</UserId>
    Expected: test_xml_principal_is_not_system_or_localservice goes RED.

  BUG-I (LogonType regression):
    In SlotConsole.xml, change:
        <LogonType>Password</LogonType>
    to:
        <LogonType>InteractiveToken</LogonType>
    Expected: test_xml_logon_type_is_not_interactive_token goes RED.
    Revert and the test goes GREEN again.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
XML_FILE = REPO_ROOT / "scripts" / "deploy" / "SlotConsole.xml"

# Task Scheduler XML namespace (v1.2)
_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def _get(root: ET.Element, path: str) -> ET.Element | None:
    """Find element in the Task Scheduler namespace."""
    ns_path = "/".join(f"{{{_NS}}}{part}" for part in path.split("/"))
    return root.find(ns_path)


def _require(root: ET.Element, path: str) -> ET.Element:
    el = _get(root, path)
    assert el is not None, f"XML element not found: {path}"
    return el


@pytest.fixture(scope="module")
def xml_root() -> ET.Element:
    assert XML_FILE.exists(), f"SlotConsole.xml not found at {XML_FILE}"
    tree = ET.parse(str(XML_FILE))
    return tree.getroot()


# ---------------------------------------------------------------------------
# T3-1: XML parses without errors
# ---------------------------------------------------------------------------

def test_xml_parses_cleanly():
    """SlotConsole.xml must be valid XML with no parse errors."""
    assert XML_FILE.exists(), f"SlotConsole.xml not found at {XML_FILE}"
    # If this raises, the test fails with a descriptive parse error.
    tree = ET.parse(str(XML_FILE))
    root = tree.getroot()
    assert root is not None


# ---------------------------------------------------------------------------
# T3-2: Action command is powershell.exe
# ---------------------------------------------------------------------------

def test_xml_uses_powershell_action(xml_root: ET.Element):
    """Actions/Exec/Command must be 'powershell.exe'."""
    cmd_el = _require(xml_root, "Actions/Exec/Command")
    assert cmd_el.text == "powershell.exe", (
        f"Expected 'powershell.exe', got {cmd_el.text!r}"
    )


# ---------------------------------------------------------------------------
# T3-3: Arguments reference start_console.ps1
# ---------------------------------------------------------------------------

def test_xml_references_start_console_ps1(xml_root: ET.Element):
    """Arguments must reference 'start_console.ps1'."""
    args_el = _require(xml_root, "Actions/Exec/Arguments")
    assert "start_console.ps1" in (args_el.text or ""), (
        f"Expected 'start_console.ps1' in Arguments, got {args_el.text!r}"
    )


# ---------------------------------------------------------------------------
# T3-4: Dynamic repo path via %SLOT_REPO_ROOT%, no hardcoded C:\
# ---------------------------------------------------------------------------

def test_xml_uses_repo_root_env_not_hardcoded(xml_root: ET.Element):
    """Arguments must contain %SLOT_REPO_ROOT% and must NOT contain 'C:\\'."""
    args_el = _require(xml_root, "Actions/Exec/Arguments")
    args_text = args_el.text or ""
    assert "%SLOT_REPO_ROOT%" in args_text, (
        f"Expected '%SLOT_REPO_ROOT%' in Arguments.\nGot: {args_text!r}"
    )
    assert "C:\\" not in args_text, (
        f"Arguments must NOT contain hardcoded 'C:\\\\'. Got: {args_text!r}"
    )


# ---------------------------------------------------------------------------
# T3-5: Principal is not SYSTEM / LocalService / LocalSystem
# ---------------------------------------------------------------------------

def test_xml_principal_is_not_system_or_localservice(xml_root: ET.Element):
    """Principal/UserId must NOT be SYSTEM, LocalService, or LocalSystem."""
    userid_el = _require(xml_root, "Principals/Principal/UserId")
    user_id = (userid_el.text or "").strip()
    forbidden = {"SYSTEM", "LocalService", "LocalSystem",
                 "NT AUTHORITY\\SYSTEM", "NT AUTHORITY\\LocalService"}
    assert user_id not in forbidden, (
        f"Principal UserId must be the operator account, NOT '{user_id}'"
    )
    assert user_id, "Principal UserId must not be empty"


# ---------------------------------------------------------------------------
# T3-6: BootTrigger is present
# ---------------------------------------------------------------------------

def test_xml_has_boot_trigger(xml_root: ET.Element):
    """Triggers must contain a BootTrigger element."""
    boot_trigger = _get(xml_root, "Triggers/BootTrigger")
    assert boot_trigger is not None, (
        "Expected <BootTrigger> under <Triggers>. "
        f"Got children: {[c.tag for c in xml_root.find(f'{{{_NS}}}Triggers') or []]}"
    )


# ---------------------------------------------------------------------------
# T3-7: RestartOnFailure block is present with Count and Interval
# ---------------------------------------------------------------------------

def test_xml_inner_settings_restart_on_failure_present(xml_root: ET.Element):
    """Settings/RestartOnFailure must exist with Interval and Count sub-elements."""
    rof_el = _get(xml_root, "Settings/RestartOnFailure")
    assert rof_el is not None, (
        "Expected <RestartOnFailure> under <Settings> (defense-in-depth restart)."
    )
    interval_el = rof_el.find(f"{{{_NS}}}Interval")
    count_el = rof_el.find(f"{{{_NS}}}Count")
    assert interval_el is not None, "RestartOnFailure must have <Interval>"
    assert count_el is not None, "RestartOnFailure must have <Count>"
    # Count must be a positive integer.
    count_val = int(count_el.text or "0")
    assert count_val > 0, f"RestartOnFailure Count must be > 0, got {count_val}"


# ---------------------------------------------------------------------------
# T3-8: LogonType is NOT InteractiveToken (IMPORTANT-4 / BLOCKER-1 regression guard)
# ---------------------------------------------------------------------------

def test_xml_logon_type_is_not_interactive_token(xml_root: ET.Element):
    """LogonType=InteractiveToken + BootTrigger means the task only fires when
    an operator is interactively logged in — defeats the self-healing-server
    intent. Acceptable: Password (stores credentials), S4U (no password).
    NOT acceptable: InteractiveToken.

    Inject-bug recipe (BUG-I):
      In SlotConsole.xml change <LogonType>Password</LogonType>
      to <LogonType>InteractiveToken</LogonType>.
      This test goes RED. Revert → GREEN.
    """
    logon_type_el = _require(xml_root, "Principals/Principal/LogonType")
    assert logon_type_el.text != "InteractiveToken", (
        "LogonType is 'InteractiveToken' — task will not run at boot without "
        "an active operator session. Use 'Password' or 'S4U' instead."
    )
    # Positive assertion: must be one of the known-good values.
    assert logon_type_el.text in {"Password", "S4U"}, (
        f"Unexpected LogonType '{logon_type_el.text}' — expected 'Password' or 'S4U'"
    )
