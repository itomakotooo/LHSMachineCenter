"""Contract tests for the MultiRobotTestSpinVariant endpoint switch.

After stage 4 of the variants rollout, every upstream sampling call
targets ``/MachineTest/MultiRobotTestSpinVariant``, and the
``MachineName`` field on the payload is whatever machines.json stores
(a plain name like ``M14`` or a variant key like ``M273$1$1-2-3``).
The Variant endpoint handles both — variant keys get rewritten to
(underlying + selector params) internally; non-variant keys fall
through to the plain test-spin path.

These tests lock the surfaces at module + HTTP boundary so a future
edit that reverts any piece surfaces immediately:

  1. analyzer / sampler / backend ENDPOINT constants end in
     "MultiRobotTestSpinVariant".
  2. backend get_server_endpoint() also routes to the Variant path
     (per-server override path).
  3. make_payload() passes MachineName verbatim — no slicing of the
     variant key's $-structure, no URL-encoding (JSON body).
  4. End-to-end: POST /api/batch-run with a variant machine flows
     through RunManager.start_run into analyzer argv with the
     variant key intact under --machine.

The last one is the sampling-pipeline argv-inspection pattern
memory-pinned as "must write integration test that follows the full
chain" — a module constant flip alone doesn't prove the variant key
survives the backend → analyzer argv traversal.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _batch_payload(machine: str, mode: int = 1) -> dict[str, Any]:
    """Minimal batch-run payload — one item, tiny chunk counts so
    the fake analyzer can complete quickly."""
    return {
        "items": [{"machine": machine, "mode": mode, "chunk_spin_times": 1000}],
        "concurrency": 1,
        "chunk_spin_times": 1000,
        "chunk_robot_count": 20,
        "max_chunks": 5,
        "target_halfwidth_pp": 0.5,
        "batch_concurrency": 2,
        "timeout": 300,
        "auto_cleanup_cache": False,
    }


def _wait_for_analyzer_cmd(stub_popen, deadline_s: float = 15.0) -> list[str] | None:
    """Same pattern as test_batch_analyzer_cli.py — wait for the
    analyzer subprocess spawn, return its argv."""
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        for cmd in stub_popen.cmds:
            if "--target-halfwidth-pp" in cmd:
                return list(cmd)
        time.sleep(0.05)
    return None


def _release_stubs(stub_popen) -> None:
    for p in list(stub_popen.processes):
        if not getattr(p, "_communicated", False):
            p.finish(0)


class TestEndpointConstants:
    """Module-level constants at every caller point to the Variant
    endpoint. If someone reverts any one of these, the UI / CLI /
    direct sampler would silently hit the non-variant endpoint and
    variant machines would get rejected or mishandled by upstream."""

    def test_analyzer_default_endpoint_is_variant(self):
        from fresh_slotlab.analyzer.core.base_pipeline import DEFAULT_ENDPOINT_URL
        assert DEFAULT_ENDPOINT_URL.endswith("/MachineTest/MultiRobotTestSpinVariant"), (
            f"analyzer ENDPOINT must target Variant endpoint; got {DEFAULT_ENDPOINT_URL}"
        )

    def test_analyzer_runtime_endpoint_tracks_default(self):
        """ENDPOINT_URL is mutable (CLI --endpoint-url overrides it)
        but initialises to the Variant default."""
        from fresh_slotlab.analyzer.core.base_pipeline import (
            DEFAULT_ENDPOINT_URL, ENDPOINT_URL,
        )
        assert ENDPOINT_URL == DEFAULT_ENDPOINT_URL

    def test_sampler_endpoint_is_variant(self):
        from fresh_slotlab.sampler import ENDPOINT_URL
        assert ENDPOINT_URL.endswith("/MachineTest/MultiRobotTestSpinVariant"), (
            f"sampler ENDPOINT must target Variant endpoint; got {ENDPOINT_URL}"
        )

    def test_backend_slot_spin_endpoint_is_variant(self):
        from src.web_console.backend.app import SLOT_SPIN_ENDPOINT
        assert SLOT_SPIN_ENDPOINT.endswith(
            "/MachineTest/MultiRobotTestSpinVariant"
        ), f"backend SLOT_SPIN_ENDPOINT must target Variant; got {SLOT_SPIN_ENDPOINT}"

    def test_backend_get_server_endpoint_returns_variant_path(self, tmp_path: Path):
        """Per-server override path (configs/servers.json) routes
        through get_server_endpoint. That function appends the API
        path — assert it's the Variant one."""
        from src.web_console.backend.app import get_server_endpoint
        servers = tmp_path / "servers.json"
        servers.write_text(
            json.dumps({"servers": [{"id": "t", "endpoint": "http://example/"}]}),
            encoding="utf-8",
        )
        url = get_server_endpoint("t", path=servers)
        assert url == "http://example/MachineTest/MultiRobotTestSpinVariant"


class TestMakePayloadPassthroughForVariantKey:
    """make_payload must forward MachineName verbatim. Variant keys
    contain ``$`` (and sometimes ``,`` / ``-``) — a well-meaning
    "sanitize" step here would break the upstream routing."""

    def test_variant_key_with_dollar_and_dash_preserved(self):
        from fresh_slotlab.analyzer.core.base_pipeline import make_payload
        payload = make_payload(
            machine="M273$1$1-2-3",
            rtp_mode=1, bet=1000, spin_times=100, robot_count=5,
            init_credits=10_000_000, reset_each_spin=True,
            continue_after_bankrupt=True,
        )
        assert payload["MachineName"] == "M273$1$1-2-3"

    def test_variant_key_with_comma_preserved(self):
        """M201 uses commas in the CommonParam: ``M201$1$2,3,4`` is
        one variant. JSON body handles commas fine; only a bad
        sanitizer would split on them."""
        from fresh_slotlab.analyzer.core.base_pipeline import make_payload
        payload = make_payload(
            machine="M201$1$2,3,4",
            rtp_mode=1, bet=1000, spin_times=100, robot_count=5,
            init_credits=10_000_000, reset_each_spin=True,
            continue_after_bankrupt=True,
        )
        assert payload["MachineName"] == "M201$1$2,3,4"

    def test_non_variant_machine_name_preserved(self):
        """Non-variant machines (227 of 393) travel the same
        make_payload path — Variant endpoint accepts them verbatim
        per upstream docs."""
        from fresh_slotlab.analyzer.core.base_pipeline import make_payload
        payload = make_payload(
            machine="M14",
            rtp_mode=1, bet=1000, spin_times=100, robot_count=5,
            init_credits=10_000_000, reset_each_spin=True,
            continue_after_bankrupt=True,
        )
        assert payload["MachineName"] == "M14"

    def test_payload_is_json_serializable_with_variant_key(self):
        """Regression guard: the payload goes through json.dumps on
        the way to the upstream. ``$`` / ``,`` / ``-`` in strings
        are legal JSON — the round-trip must preserve the key
        unchanged."""
        from fresh_slotlab.analyzer.core.base_pipeline import make_payload
        payload = make_payload(
            machine="M273$1$1-2-3",
            rtp_mode=1, bet=1000, spin_times=100, robot_count=5,
            init_credits=10_000_000, reset_each_spin=True,
            continue_after_bankrupt=True,
        )
        roundtrip = json.loads(json.dumps(payload))
        assert roundtrip["MachineName"] == "M273$1$1-2-3"


class TestBatchRunForwardsVariantToAnalyzerArgv:
    """End-to-end: the variant key has to survive POST /api/batch-run
    → backend RunManager.start_run → subprocess spawn with
    --machine ... argv. A middle layer that accidentally stripped /
    normalized the key would only surface here.

    Pattern borrowed from test_batch_analyzer_cli.py — stub_popen
    captures the argv without actually spawning the analyzer.
    """

    def test_variant_machine_forwarded_to_analyzer_machine_arg(
        self, client, tmp_path: Path, app_factory, monkeypatch,
        fake_machines: Path,
    ):
        """POST /batch-run with a variant machine → analyzer argv
        carries ``--machine M273$1$1-2-3`` verbatim. If a future
        refactor url-encodes / sanitizes / splits on ``$`` the key,
        this goes red."""
        import src.web_console.backend.app as app_mod
        from tests.backend._save_chunk_cache_compat import _save_chunk_cache

        # Extend the seed machines.json with the variant row so the
        # batch-run validator accepts our request. fake_machines
        # starts with only M14 (conftest); we append the variant.
        variant = "M273$1$1-2-3"
        existing = json.loads(fake_machines.read_text(encoding="utf-8"))
        existing.setdefault("machines", []).append({
            "machine": variant, "modes": [1, 2, 5, 7],
            "configSummaryMd5": "", "codeSummaryMd5": "",
            "logicClassNames": [], "available": True,
        })
        fake_machines.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Point the backend at the tmp rawdata root so chunks land
        # there, not in the repo's real rawdata/ tree.
        raw_root = tmp_path / "rawdata"
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))

        # Seed a chunk under the variant directory name. Windows &
        # Linux both accept ``$`` in path segments; if the FS ever
        # rejects this the write itself fails and the test still
        # surfaces the issue (just one level earlier).
        mode_dir = raw_root / variant / "mode_1"
        mode_dir.mkdir(parents=True, exist_ok=True)
        resp = [{"roundResult": json.dumps([{
            "BetAmount": 1000, "WinCredits": 900,
            "StopSymbolsByCol": "A|B|C|D|E", "SpinType": "Normal",
        }])}]
        _save_chunk_cache(resp, 1, variant, 1, 1000, 1000, 10, mode_dir)

        c, _ = client
        r = c.post("/api/batch-run", json=_batch_payload(variant))
        assert r.status_code == 200, r.text

        cmd = _wait_for_analyzer_cmd(app_factory.stub_popen)
        _release_stubs(app_factory.stub_popen)
        assert cmd is not None, "analyzer subprocess never launched"

        assert "--machine" in cmd, cmd
        m_idx = cmd.index("--machine")
        assert cmd[m_idx + 1] == variant, (
            f"analyzer received --machine {cmd[m_idx + 1]!r}; "
            f"expected verbatim {variant!r}"
        )


class TestDisplayNameAndUpstreamKeySplit:
    """New-schema rows (stage 8) separate the display machine name
    from the upstream key. --machine carries the display name (used
    for rawdata paths + summary identity); --upstream-machine-name
    carries the upstream key (fed to MachineName on the Variant
    payload). Non-variant rows omit the latter — analyzer falls back
    to --machine."""

    def test_variant_row_forwards_display_and_upstream_key(
        self, client, tmp_path: Path, app_factory, monkeypatch,
        fake_machines: Path,
    ):
        import src.web_console.backend.app as app_mod
        from tests.backend._save_chunk_cache_compat import _save_chunk_cache

        display = "M273$WheelSelector$1$1-2-3"
        upstream = "M273$1$1-2-3"

        existing = json.loads(fake_machines.read_text(encoding="utf-8"))
        existing.setdefault("machines", []).append({
            "machine": display,
            "upstream_key": upstream,
            "modes": [1, 2, 5, 7],
            "configSummaryMd5": "", "codeSummaryMd5": "",
            "logicClassNames": [], "available": True,
        })
        fake_machines.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        raw_root = tmp_path / "rawdata"
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))

        # Path segment still uses display name. Windows/Linux both
        # accept ``$`` in path segments.
        mode_dir = raw_root / display / "mode_1"
        mode_dir.mkdir(parents=True, exist_ok=True)
        resp = [{"roundResult": json.dumps([{
            "BetAmount": 1000, "WinCredits": 900,
            "StopSymbolsByCol": "A|B|C|D|E", "SpinType": "Normal",
        }])}]
        _save_chunk_cache(resp, 1, display, 1, 1000, 1000, 10, mode_dir)

        c, _ = client
        r = c.post("/api/batch-run", json=_batch_payload(display))
        assert r.status_code == 200, r.text

        cmd = _wait_for_analyzer_cmd(app_factory.stub_popen)
        _release_stubs(app_factory.stub_popen)
        assert cmd is not None

        # --machine carries the display name (used for rawdata path).
        assert "--machine" in cmd, cmd
        m_idx = cmd.index("--machine")
        assert cmd[m_idx + 1] == display, cmd

        # --upstream-machine-name carries the variant upstream key
        # (used for MachineName on the Variant endpoint payload).
        assert "--upstream-machine-name" in cmd, cmd
        u_idx = cmd.index("--upstream-machine-name")
        assert cmd[u_idx + 1] == upstream, cmd

    def test_non_variant_row_omits_upstream_machine_name(
        self, client, tmp_path: Path, app_factory, monkeypatch,
        fake_machines: Path,
    ):
        """For non-variant rows (M14 / M1 / ...), upstream_key ==
        machine name. The RunManager helper returns None in that
        case and we skip the redundant flag entirely — analyzer
        falls back to --machine for MachineName."""
        import src.web_console.backend.app as app_mod
        from tests.backend._save_chunk_cache_compat import _save_chunk_cache

        existing = json.loads(fake_machines.read_text(encoding="utf-8"))
        # M14 already in fake_machines (conftest seed); ensure it has
        # the new-schema upstream_key field so the code path matches
        # production.
        for row in existing.get("machines", []):
            if row.get("machine") == "M14":
                row["upstream_key"] = "M14"
        fake_machines.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        raw_root = tmp_path / "rawdata"
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", raw_root)
        monkeypatch.setattr(app_mod, "_get_machine_md5", lambda *a, **kw: ("", ""))

        mode_dir = raw_root / "M14" / "mode_1"
        mode_dir.mkdir(parents=True, exist_ok=True)
        resp = [{"roundResult": json.dumps([{
            "BetAmount": 1000, "WinCredits": 900,
            "StopSymbolsByCol": "A|B|C|D|E", "SpinType": "Normal",
        }])}]
        _save_chunk_cache(resp, 1, "M14", 1, 1000, 1000, 10, mode_dir)

        c, _ = client
        r = c.post("/api/batch-run", json=_batch_payload("M14"))
        assert r.status_code == 200, r.text

        cmd = _wait_for_analyzer_cmd(app_factory.stub_popen)
        _release_stubs(app_factory.stub_popen)
        assert cmd is not None

        # --upstream-machine-name must NOT appear for non-variant
        # rows — passing it would duplicate --machine, and tests
        # assert absence so a future regression that always sets
        # the flag surfaces loudly.
        assert "--upstream-machine-name" not in cmd, (
            f"non-variant row should not carry --upstream-machine-name; "
            f"cmd: {cmd}"
        )
