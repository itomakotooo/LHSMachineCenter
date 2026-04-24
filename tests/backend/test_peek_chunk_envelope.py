"""Tests for the chunk envelope peek optimization.

Context: resume-read with a new md5 filter (e.g. after a
MachineConfig swap creates a new ``localcfg_<hash>`` bucket) used to
load + parse every historical chunk just to discover its md5 doesn't
match. On a 100MB history (29 × ~3.5MB chunks for M15 mode 5) that
took ~15s of pure waste. ``peek_chunk_envelope`` reads only the first
4KB and regex-extracts the md5 + chunk_index from the envelope
header — the rest of the chunk (the huge ``response`` array) never
gets read or parsed when the caller plans to skip it anyway.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

from fresh_slotlab.player_impact_analyzer import peek_chunk_envelope


def _write_chunk(
    path: Path,
    *,
    chunk_index: int = 5,
    config_md5: str = "cfg_abcd",
    code_md5: str = "code_wxyz",
    response_bytes: int = 3_000_000,
):
    """Write a chunk file with a realistic envelope header + an
    opaque ``response`` field padded to ``response_bytes`` so we can
    assert the peek really avoids reading the tail."""
    # The peek regex needs `_chunk_index`, `_config_md5`, `_code_md5`
    # in that order in the header. Match production writer's order.
    envelope = {
        "_cache_version": 3,
        "_machine": "M14",
        "_mode": 1,
        "_bet": 1000,
        "_spin_times": 2000,
        "_robot_count": 8,
        "_chunk_index": chunk_index,
        "_saved_at": "2026-04-24T12:00:00Z",
        "_config_md5": config_md5,
        "_code_md5": code_md5,
        "_upstream_schema_fingerprint": "abc123",
        "_payload_sha256": "deadbeef" * 8,
        # Opaque filler to reach ``response_bytes``. We use a single
        # huge string so JSON parsing would be expensive, but peek
        # never reaches here.
        "response": "x" * response_bytes,
    }
    path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")


class TestPeekChunkEnvelope:
    def test_peek_extracts_fields_without_full_parse(self, tmp_path):
        """Write a 3MB chunk, then assert peek returns the 3 header
        fields correctly — shape test."""
        p = tmp_path / "chunk_0007.json"
        _write_chunk(p, chunk_index=7,
                     config_md5="localcfg_abc12345",
                     code_md5="real_code_md5")
        assert p.stat().st_size > 2_500_000, "test needs a fat chunk"
        result = peek_chunk_envelope(p)
        assert result == (7, "localcfg_abc12345", "real_code_md5")

    def test_peek_returns_none_for_malformed_header(self, tmp_path):
        """Envelope missing the 3 required fields → peek returns
        None so caller falls back to full parse (preserves old
        envelope compatibility)."""
        p = tmp_path / "chunk_0001.json"
        p.write_text(
            json.dumps({"_cache_version": 1, "response": []}),
            encoding="utf-8",
        )
        assert peek_chunk_envelope(p) is None

    def test_peek_returns_none_for_missing_file(self, tmp_path):
        """Safety: missing file → None, not exception. Caller's
        fall-through to load_chunk_envelope will raise the real
        file-not-found."""
        assert peek_chunk_envelope(tmp_path / "nope.json") is None

    def test_peek_reads_bounded_bytes(self, tmp_path, monkeypatch):
        """Hard proof that peek doesn't read the whole file: wrap
        Path.open and count bytes read. Budget: 4KB + a little
        slack for OS buffer alignment."""
        p = tmp_path / "chunk_0003.json"
        _write_chunk(p, chunk_index=3, response_bytes=2_000_000)

        read_counter = {"bytes": 0}
        original_open = Path.open

        def counting_open(self, mode="r", *args, **kwargs):
            # Only intercept reads on the chunk file itself; pass
            # everything else through unchanged.
            if self == p:
                real = original_open(self, mode, *args, **kwargs)

                class _CountingReader:
                    def __init__(self, inner):
                        self._inner = inner
                    def read(self, size=-1):
                        data = self._inner.read(size)
                        read_counter["bytes"] += len(data)
                        return data
                    def __enter__(self):
                        self._inner.__enter__()
                        return self
                    def __exit__(self, *a):
                        return self._inner.__exit__(*a)
                    def __getattr__(self, name):
                        return getattr(self._inner, name)

                return _CountingReader(real)
            return original_open(self, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "open", counting_open)
        peek_chunk_envelope(p)
        # peek buffers 4KB; tolerant upper bound at 16KB for any
        # disk-block-alignment quirks. The important property is
        # "NOT 2MB" (full file) — which would be a 100x regression.
        assert read_counter["bytes"] < 16_384, (
            f"peek must not read full file; got {read_counter['bytes']:,}B"
        )

    def test_peek_handles_fields_in_whitespace_variant(self, tmp_path):
        """Different JSON formatters may insert spaces around colons.
        Regex accounts for optional whitespace — lock it."""
        p = tmp_path / "chunk_0009.json"
        # Hand-write with varied spacing; regex must still find all 3.
        body = (
            '{"_cache_version": 3,'
            ' "_machine" : "M14" ,'
            ' "_chunk_index"   :   9 ,'
            ' "_config_md5"  :\t"localcfg_xx", '
            ' "_code_md5":"cc" ,'
            ' "response":""}'
        )
        p.write_text(body, encoding="utf-8")
        assert peek_chunk_envelope(p) == (9, "localcfg_xx", "cc")
