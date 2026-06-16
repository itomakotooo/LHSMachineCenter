"""Compat shim for legacy callers of `_save_chunk_cache`.

Post-P2-B3 (commit 0f115bb), `_save_chunk_cache` requires two new
keyword-only arguments injected by the DI rewrite:
  - lookup_machine_md5: Callable[[str], tuple[str, str]]
  - rawdata_index_update_entry: Callable[..., None] | None

Existing tests authored before P2-B3 pass 8 positional args and expect
the writer to internally invoke both helpers. This shim defaults both
to safe stubs (empty md5, real `rawdata_index.update_entry`) so test
intent is preserved without per-callsite edits.

Use::

    from tests.backend._save_chunk_cache_compat import _save_chunk_cache

This module is *only* for legacy test code. New tests should call
`fresh_slotlab.player_impact_analyzer._save_chunk_cache` directly with
explicit kwargs.
"""
from __future__ import annotations

from fresh_slotlab.analyzer.core.writer import _save_chunk_cache as _real
from fresh_slotlab import rawdata_index as _ri


def _stub_md5_lookup(_machine: str) -> tuple[str, str]:
    return ("", "")


def _save_chunk_cache(*args, **kwargs):
    kwargs.setdefault("lookup_machine_md5", _stub_md5_lookup)
    kwargs.setdefault("rawdata_index_update_entry", _ri.update_entry)
    return _real(*args, **kwargs)
