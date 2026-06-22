"""Guard: round_win rule-type discovery + base-exclusion invariants.

Mirrors tests/analyzer/test_phase4_auto_discover.py for the new
``fresh_slotlab/round_win_rules/`` layer. Proves the core property of the
pluggable rule engine (the whole point of the refactor):

  * the 4 built-in rule types are auto-discovered into RULE_REGISTRY;
  * adding a rule-type MODULE does NOT flip base_hash (the modules are
    base-EXCLUDED — only round_win_rules/__init__.py is in the closure);
  * a rule-type module's content DOES affect base_hash *if* it were in the
    closure — so the exclusion (not file inertness) is what keeps base_hash
    stable (meaningfulness / inject-bug proof);
  * only machines that DECLARE a rule type (applies_to) fold its hash into
    their effective_version; non-declaring machines are unchanged;
  * the type-string contract is enforced at registration (TYPE_STR mismatch /
    non-subclass raise instead of silently producing an empty rule list).
"""
from __future__ import annotations

import hashlib
import sys
import textwrap
from pathlib import Path

import pytest

import fresh_slotlab.round_win_rules as rwr
from fresh_slotlab.analyzer.versioning import (
    _used_round_win_types,
    compute_base_analyzer_version,
    compute_effective_version_for_machine,
)

_PROBE_STEM = "_probe_rule_test"
_PROBE_TYPE = "_probe_rule_test_type"
_PROBE_REL = f"fresh_slotlab/round_win_rules/{_PROBE_STEM}.py"
_RULES_DIR = Path(rwr.__file__).resolve().parent
_PROBE_PATH = _RULES_DIR / f"{_PROBE_STEM}.py"

_PROBE_SRC = textwrap.dedent('''\
    """Ephemeral probe rule type for the discovery guard test. Deleted in teardown."""
    from __future__ import annotations
    from typing import ClassVar
    try:
        from fresh_slotlab.round_win import RoundWinRule
        from fresh_slotlab.round_win_rules import register_rule
    except ImportError:
        from round_win import RoundWinRule  # type: ignore[no-redef]
        from round_win_rules import register_rule  # type: ignore[no-redef]


    class _ProbeRule(RoundWinRule):
        TYPE_STR: ClassVar[str] = "_probe_rule_test_type"

        def extract_win(self, round_dict, ctx=None):
            return None


    register_rule("_probe_rule_test_type", _ProbeRule)
''')


def _cleanup_probe() -> None:
    _PROBE_PATH.unlink(missing_ok=True)
    rwr.RULE_REGISTRY.pop(_PROBE_TYPE, None)
    sys.modules.pop(f"fresh_slotlab.round_win_rules.{_PROBE_STEM}", None)
    sys.modules.pop(f"round_win_rules.{_PROBE_STEM}", None)


@pytest.fixture
def probe_rule():
    """Write the probe rule module, discover it, yield; clean up file + registry."""
    _PROBE_PATH.write_text(_PROBE_SRC, encoding="utf-8")
    try:
        rwr.discover_rules()
        yield
    finally:
        _cleanup_probe()


class TestRoundWinRuleDiscovery:
    def test_known_types_discovered(self):
        rwr.discover_rules()
        for t in ("settlement_winamount", "synthesize_pay_id", "win_residual", "bcm_cycle_anchor"):
            assert t in rwr.RULE_REGISTRY, f"{t} not auto-discovered"

    def test_adding_rule_type_does_not_flip_base_hash(self):
        """A new rule-type module is base-EXCLUDED → base_hash unchanged."""
        bh_before = compute_base_analyzer_version()
        _PROBE_PATH.write_text(_PROBE_SRC, encoding="utf-8")
        try:
            bh_after = compute_base_analyzer_version()
        finally:
            _cleanup_probe()
        assert bh_after == bh_before, (
            "adding a round_win_rules/*.py rule-type module flipped base_hash — "
            "the rule-type modules must be base-EXCLUDED (only __init__.py is in "
            "_CLOSURE_FILES)."
        )

    def test_probe_content_would_flip_if_in_closure(self):
        """Meaningfulness: the probe's bytes DO change the hash when included in
        the closure, so the exclusion above is what keeps base_hash stable —
        not that the file is inert (inject-bug proof)."""
        from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES
        _PROBE_PATH.write_text(_PROBE_SRC, encoding="utf-8")
        try:
            bh_excluded = compute_base_analyzer_version()
            bh_included = compute_base_analyzer_version(
                closure_files=_CLOSURE_FILES + (_PROBE_REL,)
            )
        finally:
            _cleanup_probe()
        assert bh_included != bh_excluded, (
            "probe content did not affect the hash even when in-closure — the "
            "guard would be vacuous."
        )

    def test_only_declaring_machine_reflags(self, probe_rule):
        """A machine that declares the probe type folds rw:<type>; another does not."""
        cfg = {"rules": {"_probe": {"type": _PROBE_TYPE, "applies_to": ["M15"]}}}
        assert _PROBE_TYPE in _used_round_win_types("M15", config=cfg)
        assert _PROBE_TYPE not in _used_round_win_types("M43", config=cfg)

        empty = {"rules": {}}
        ev_m15_with = compute_effective_version_for_machine("M15", 1, round_win_rules_config=cfg)
        ev_m15_without = compute_effective_version_for_machine("M15", 1, round_win_rules_config=empty)
        assert ev_m15_with != ev_m15_without, "declaring the rule type did not change M15's EV"

        ev_m43_with = compute_effective_version_for_machine("M43", 1, round_win_rules_config=cfg)
        ev_m43_without = compute_effective_version_for_machine("M43", 1, round_win_rules_config=empty)
        assert ev_m43_with == ev_m43_without, "M43 EV changed despite not declaring the rule type"

    def test_variant_inherits_base_rule_types(self):
        """A variant id (M15$...$) folds the base machine's rule types (EC-1)."""
        cfg = {"rules": {"r": {"type": "settlement_winamount", "applies_to": ["M15"]}}}
        used = _used_round_win_types("M15$TopDollarSelector$1$", config=cfg)
        assert "settlement_winamount" in used

    def test_register_rule_type_str_mismatch_raises(self):
        from fresh_slotlab.round_win import RoundWinRule

        class _Bad(RoundWinRule):
            TYPE_STR = "declared_x"

        with pytest.raises(ValueError):
            rwr.register_rule("config_y", _Bad)

    def test_register_rule_rejects_non_subclass(self):
        with pytest.raises(TypeError):
            rwr.register_rule("nope", object)

    def test_rule_type_hash_crlf_normalized(self):
        rwr.discover_rules()
        h = rwr.rule_type_hash("win_residual")
        src = (_RULES_DIR / "win_residual.py").read_bytes().replace(b"\r\n", b"\n")
        assert h == hashlib.sha256(src).hexdigest()[:12]
