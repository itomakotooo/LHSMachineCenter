"""Regression: M15 feature_weights.tsv is the SOURCE OF TRUTH; each
mode's weights.json `feature_params` block mirrors the compiled TSV.

Why this matters:
  - Designer edits the TSV (human-readable table). Wrapper script
    ``compile_m15_features_from_tsv`` writes the compiled block into
    each mode_<N>/weights.json.
  - If someone later hand-edits the JSON block (e.g. bumping
    x_value_weights on mode 5 for a quick experiment) without
    propagating to the TSV, the two diverge silently. Next edit of
    the TSV + recompile would clobber their JSON edit.
  - This test runs ``compile_m15_features_from_tsv --check`` which
    exits 1 on drift. CI catches the skew immediately.

Also asserts:
  (a) the TSV parses cleanly (no schema regressions on the file format)
  (b) expanding per-value weights to 10-slot aligns with ``_X_POOL``
      (catches pool reordering in feature_m15.py)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent


def test_feature_tsv_is_source_of_truth():
    """Running ``compile_m15_features_from_tsv --check`` must succeed
    (exit 0). If someone edits weights.json.feature_params without
    reflecting in the TSV, this fails with the drift dump.
    """
    r = subprocess.run(
        [sys.executable, "-m", "slot_designer.scripts.compile_m15_features_from_tsv", "--check"],
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
    )
    assert r.returncode == 0, (
        f"TSV ↔ weights.json drift detected — run "
        f"`python -m slot_designer.scripts.compile_m15_features_from_tsv` to "
        f"resync (or update TSV to match JSON if the JSON is correct).\n"
        f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    )


def test_feature_tsv_header_has_all_4_modes():
    """TSV header must carry columns for mode_1, mode_2, mode_5, mode_7."""
    import sys
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from slot_designer.scripts.compile_m15_features_from_tsv import (
        _TSV_PATH,
        _parse_tsv,
    )
    modes, _ = _parse_tsv(_TSV_PATH.read_text(encoding="utf-8"))
    assert sorted(modes) == [1, 2, 5, 7], (
        f"TSV header must declare columns for modes {[1,2,5,7]}; got {modes}"
    )


def test_feature_tsv_expands_to_ten_slot_x_value_weights():
    """TSV lists per-unique-value weights (6 values); compile expands to
    10 slots aligned with ``_X_POOL``. Verifies duplicate values get
    the same weight at both their slots — i.e., mode 5's 50-card weight
    (3.5) appears at pool indices 2 AND 3.
    """
    import sys
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from slot_designer.engine.feature_m15 import _X_POOL
    from slot_designer.scripts.compile_m15_features_from_tsv import (
        _TSV_PATH,
        _compile_mode,
        _parse_tsv,
    )

    modes, rows = _parse_tsv(_TSV_PATH.read_text(encoding="utf-8"))
    fp_m5 = _compile_mode(5, modes, rows)
    x_vals = fp_m5["x_value_weights"]
    assert len(x_vals) == len(_X_POOL), (
        f"x_value_weights must be 10 slots aligned with _X_POOL; got {len(x_vals)}"
    )
    # Mode 5 TSV v7: x_val[50]=3.5, expect both pool-50 slots (idx 2, 3) to be 3.5
    slots_50 = [i for i, v in enumerate(_X_POOL) if v == 50]
    for i in slots_50:
        assert x_vals[i] == 3.5, (
            f"pool[{i}]=50 should have compiled weight 3.5 from mode 5 TSV; "
            f"got {x_vals[i]}"
        )
    # Spot-check: 1000 is only at slot 0, weight 0.0001
    assert x_vals[0] == 0.0001, (
        f"pool[0]=1000 should have mode 5 v7 weight 0.0001; got {x_vals[0]}"
    )


def test_feature_tsv_preserves_analytic_sub_block_on_compile():
    """``_analytic`` in weights.json.feature_params is hand-authored
    metadata (EV numbers, P(jackpot) etc.) that the TSV doesn't know
    about. Compile must preserve it across recompiles.
    """
    import json
    doc = json.loads(
        (_ROOT / "slot_designer" / "weights" / "M15" / "mode_5" / "weights.json")
        .read_text(encoding="utf-8")
    )
    fp = doc.get("feature_params", {})
    assert "_analytic" in fp, (
        "mode 5 feature_params lost its _analytic sub-block after compile. "
        "The compile script must preserve designer-authored metadata that "
        "the TSV doesn't carry."
    )
    # Known fields from the hand-authored v7 _analytic
    analytic = fp["_analytic"]
    assert "ev_per_trigger" in analytic


if __name__ == "__main__":
    test_feature_tsv_is_source_of_truth()
    print("ok  test_feature_tsv_is_source_of_truth")
    test_feature_tsv_header_has_all_4_modes()
    print("ok  test_feature_tsv_header_has_all_4_modes")
    test_feature_tsv_expands_to_ten_slot_x_value_weights()
    print("ok  test_feature_tsv_expands_to_ten_slot_x_value_weights")
    test_feature_tsv_preserves_analytic_sub_block_on_compile()
    print("ok  test_feature_tsv_preserves_analytic_sub_block_on_compile")
    print("4/4 passed")
