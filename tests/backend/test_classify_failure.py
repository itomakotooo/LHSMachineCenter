"""Tests for ``_classify_failure`` — the network-vs-machine error
splitter that drives the dual-counter circuit-breaker.

Background (2026-04-26): user moved sampling to internal upstream
(192.168.10.21) and asked for the circuit-breaker to discriminate
between the two failure classes:

  - 'network': transient errors that retry might help with (5xx,
    TimeoutError, IncompleteRead, TCP resets, etc.). Tolerate a
    handful before bailing as ``upstream_unstable``.

  - 'machine': permanent errors that retry won't help (4xx, parse_
    failed_*, response_shape_unexpected_*, schema_drift_*). Bail
    fast as ``machine_bug`` so operator sees the signal early.

These tests pin every error-string format the codebase produces
(grep for ``"error":`` in ``run_sampling_chunk`` and
``parse_chunk_response``) so a future refactor can't accidentally
drop a class into the wrong bucket.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "fresh_slotlab"))

from analyzer.core.base_pipeline import _classify_failure  # noqa: E402


# ── Network-class: retry might help ───────────────────────────────


class TestNetworkClass:
    def test_5xx_codes_are_network(self):
        for code in (500, 502, 503, 504):
            err = f"request_failed_http_{code}"
            assert _classify_failure(err) == "network", (
                f"{code} is in _RETRYABLE_HTTP_CODES — must classify as network"
            )

    def test_timeout_is_network(self):
        # TimeoutError classified by run_sampling_chunk's
        # `(URLError, TimeoutError)` clause.
        assert _classify_failure("request_failed_network_TimeoutError") == "network"

    def test_url_error_is_network(self):
        # urllib.error.URLError — DNS / connection refused / etc.
        assert _classify_failure("request_failed_network_URLError") == "network"

    def test_socket_timeout_is_network(self):
        assert _classify_failure("request_failed_network_timeout") == "network"

    def test_generic_exception_fallback_is_network(self):
        # The bare-except fallback in run_sampling_chunk emits
        # "request_failed_<TypeName>" without the _network_ prefix.
        # Common cases: ConnectionResetError, RemoteDisconnected,
        # IncompleteRead — all transient TCP/HTTP-stack hiccups.
        for name in (
            "ConnectionResetError",
            "RemoteDisconnected",
            "IncompleteRead",
            "BrokenPipeError",
            "ConnectionAbortedError",
        ):
            err = f"request_failed_{name}"
            assert _classify_failure(err) == "network", (
                f"{err} is a TCP/HTTP transient — must be network-class"
            )


# ── Machine-class: retry won't help ───────────────────────────────


class TestMachineClass:
    def test_4xx_codes_are_machine(self):
        # 4xx = bad request / config mismatch / unauthorized — the
        # machine config or API contract is wrong, retry won't fix.
        for code in (400, 401, 403, 404, 410, 422):
            err = f"request_failed_http_{code}"
            assert _classify_failure(err) == "machine", (
                f"{code} is a client error — retry won't fix; must be machine"
            )

    def test_parse_failed_empty_response_is_machine(self):
        assert _classify_failure("parse_failed_empty_response") == "machine"

    def test_parse_failed_zero_chunk_is_machine(self):
        assert _classify_failure("parse_failed_zero_chunk") == "machine"

    def test_response_shape_unexpected_is_machine(self):
        # Both observed variants from parse_chunk_response.
        assert _classify_failure(
            "response_shape_unexpected:expected_list:dict"
        ) == "machine"
        assert _classify_failure(
            "response_shape_unexpected:expected_robot_dicts:item_types=str,int"
        ) == "machine"

    def test_schema_drift_missing_fields_is_machine(self):
        # Real example from M14 sampling: round dict missing
        # StopSymbolsByCol. Schema-level mismatch → machine bug.
        assert _classify_failure(
            "schema_drift_missing_fields:StopSymbolsByCol"
        ) == "machine"
        assert _classify_failure(
            "schema_drift_missing_fields:Field1,Field2,Field3"
        ) == "machine"


# ── Defensive defaults ────────────────────────────────────────────


class TestDefaults:
    def test_empty_string_defaults_to_machine(self):
        # Safer to fail-fast on uncertain failures than burn the
        # network-tolerance budget.
        assert _classify_failure("") == "machine"

    def test_none_or_missing_classifies_as_machine(self):
        # Some code paths might pass None / absent error fields.
        assert _classify_failure(None) == "machine"  # type: ignore[arg-type]

    def test_unknown_prefix_is_machine(self):
        # Any string we don't recognize → safer to bail fast.
        assert _classify_failure("totally_made_up_error") == "machine"
        assert _classify_failure("error: something") == "machine"

    def test_malformed_http_code_is_machine(self):
        # If someone emits ``request_failed_http_<garbage>`` we can't
        # parse the code — treat conservatively as machine (don't
        # accidentally tolerate broken code paths as network blips).
        assert _classify_failure("request_failed_http_") == "machine"
        assert _classify_failure("request_failed_http_xyz") == "machine"

    def test_unknown_5xx_is_still_network(self):
        # 599 isn't in _RETRYABLE_HTTP_CODES (we only list the 4
        # standard transient codes), so it should classify as
        # machine. Pinning this so a future "expand 5xx range"
        # change is intentional.
        assert _classify_failure("request_failed_http_599") == "machine"
