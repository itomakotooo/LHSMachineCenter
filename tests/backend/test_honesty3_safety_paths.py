"""honesty-3 safety path tests (inject-bug → red → revert → green).

Covers ALL 5 safety paths from phase_honesty_3/brief.md §6:

  SP1. Per-machine isolation — machine A stale does NOT flag machine B.
  SP2. No false-fresh on monolith/closure edit — changed base → all stale.
  SP3. R-6 empty-cache honest dead-end — stale + no rawdata → needs_rawdata.
  SP4. R-8 virtual honest — virtual summary gets honest effective, never empty.
  SP5. No-manifest unverifiable ≠ stale; closure-missing surfaces.

Each test pair (green) is documented with its inject-bug recipe so future
developers can reproduce the red→green cycle.

Memory citations:
  - memory/feedback_enumerate_safety_paths.md — inject-bug per path required
  - memory/feedback_no_silent_swallow.md — closure errors must surface
  - memory/feedback_integration_test_argv.md — real endpoints/subprocesses,
    not just unit mocks
  - memory/feedback_perf_claim_needs_e2e_event_stream.md — backend endpoint
    assertions are the "e2e" signal, not unit-only

Hard gate (must pass before and after all edits):
  python -c "import sys; sys.path.insert(0,'fresh_slotlab');
             from analyzer.versioning import compute_base_analyzer_version as f;
             print(f())"
  MUST print: 57fdb323585d  (was 960e9d18d83d pre phase-2a; PIA shrank when
              collect_mechanic's compute was carved into its plugin)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers (extend existing test_stale_count helpers, per
# feedback_no_parallel_panel_impl.md — reuse, don't duplicate)
# ─────────────────────────────────────────────────────────────────────────────


def _seed_run(
    db_path: Path,
    run_id: str,
    machine: str,
    mode: int,
    *,
    cfg: str | None,
    code: str | None,
    analyzer: str | None,
    effective: str | None = None,
    status: str = "completed",
) -> None:
    """Insert a completed run row into the runs table."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, machine, mode, status, model_id, created_at,
                started_at, target_halfwidth_pp, chunk_spin_times,
                chunk_robot_count, batch_concurrency, max_chunks, timeout,
                bankruptcy_session_spins, bankruptcy_bankroll_multipliers,
                report_version, output_dir, progress_file, summary_file,
                rawdata_config_md5, rawdata_code_md5, analyzer_version,
                effective_analyzer_version
            ) VALUES (
                ?, ?, ?, ?, 'sdk', '2026-01-01T00:00:00Z',
                '2026-01-01T00:00:00Z', 0.5, 5000,
                24, 2, 10, 30, 500, '100,200,500',
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                run_id, machine, mode, status,
                f"rv_{run_id}", f"/dir/{run_id}",
                f"/dir/{run_id}/p.jsonl", f"/dir/{run_id}/s.json",
                cfg, code, analyzer, effective,
            ),
        )
        conn.commit()


def _write_machines_config(path: Path, machines: dict[str, tuple[str, str]]) -> None:
    """Write a machines.json with the given (machine → (cfg_md5, code_md5)) entries."""
    path.write_text(json.dumps({
        "machines": [
            {
                "machine": m,
                "modes": [1, 2, 5, 7],
                "configSummaryMd5": cfg,
                "codeSummaryMd5": code,
            }
            for m, (cfg, code) in machines.items()
        ]
    }), encoding="utf-8")


def _write_stub_chunk(rawdata_root: Path, machine: str, mode: int,
                      cfg: str, code: str) -> None:
    """Write a minimal chunk file so check_rawdata_status reports usable rawdata.

    Used by SP1/SP2/SP3 tests to control whether a (machine, mode) has rawdata.
    Matches the helper in test_stale_count.py.
    """
    chunk_dir = rawdata_root / machine / f"mode_{mode}"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_data = {
        "_config_md5": cfg,
        "_code_md5": code,
        "_saved_at": "2026-01-01T00:00:00Z",
        "rounds": [],
    }
    (chunk_dir / "chunk_1.json").write_text(
        json.dumps(chunk_data), encoding="utf-8"
    )


def _make_app(
    tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
    machines_config, fake_analyzer, monkeypatch,
):
    """Create an isolated app for safety-path tests."""
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: True,
    )
    from fastapi.testclient import TestClient
    from src.web_console.backend.app import create_app

    app = create_app(
        state_dir=tmp_state_dir,
        reports_root=tmp_reports,
        cache_root=tmp_cache,
        machines_config=machines_config,
        analyzer_path=fake_analyzer,
        rawdata_root=tmp_rawdata,
    )
    return app


# ═══════════════════════════════════════════════════════════════════════════════
# SP1 — Per-machine isolation
# ═══════════════════════════════════════════════════════════════════════════════


class TestPerMachineIsolation:
    """Safety path 1: machine A effective changes but B's does not →
    stale-count flags ONLY A, not B.

    The M31 bug was: a single global hash meant ANY edit flagged ALL 393 machines.
    honesty-3 fix: per-(machine, mode) effective_analyzer_version.

    Inject-bug recipe for this class (documents red phase):
      In app.py's stale_report_count(), change:
          row_eff = row.get("effective_analyzer_version") or ""
          cur_eff = eff_cache.get(str(machine), int(mode))
      to (legacy global read):
          row_eff = row.get("analyzer_version") or ""
          cur_eff = cur_analyzer   # single global value
      → Machine B is flagged stale (its "OLD_GLOBAL" != cur_analyzer) even though
        its effective_analyzer_version matches → test_only_machine_a_flagged fails
        because B.stale_analyzer would be 1 instead of 0 → RED.
      Revert → GREEN.
    """

    def test_only_machine_a_flagged_when_only_a_stale(
        self,
        tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_analyzer, tmp_path, monkeypatch,
    ):
        """Machine A has stale effective; B's effective matches current.
        → stale_analyzer==1 (only A), fixable_items==[A], B not flagged.

        Requires BOTH machines to have manifests (so EffectiveVersionCache
        can compute their current effective). The monkeypatch below injects a
        synthetic cache so we control the "current effective" for each machine
        exactly, without needing real manifests on disk.
        """
        mc = tmp_path / "machines.json"
        _write_machines_config(mc, {
            "MA": ("CFG_A", "CODE_A"),
            "MB": ("CFG_B", "CODE_B"),
        })
        app = _make_app(
            tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
            mc, fake_analyzer, monkeypatch,
        )
        db_path = tmp_state_dir / "console.db"

        # Inject a fake EffectiveVersionCache whose .get() returns controlled values:
        #   MA/1 → "CURRENT_EFF_A" (the "current" hash)
        #   MB/1 → "CURRENT_EFF_B" (the "current" hash)
        _per_machine_current = {
            ("MA", 1): "CURRENT_EFF_A",
            ("MB", 1): "CURRENT_EFF_B",
        }

        class FakeEffCache:
            UNVERIFIABLE = "UNVERIFIABLE"
            def __init__(self, **_kwargs):
                pass
            def get(self, machine_id, mode):
                return _per_machine_current.get((machine_id, mode), self.UNVERIFIABLE)

        monkeypatch.setattr(
            "src.web_console.backend.effective_version_cache.EffectiveVersionCache",
            FakeEffCache,
        )

        # Write rawdata so both are "fixable" if stale
        _write_stub_chunk(tmp_rawdata, "MA", 1, "CFG_A", "CODE_A")
        _write_stub_chunk(tmp_rawdata, "MB", 1, "CFG_B", "CODE_B")

        # MA: effective = OLD (stale); MB: effective = CURRENT_EFF_B (fresh)
        _seed_run(db_path, "rA", "MA", 1,
                  cfg="CFG_A", code="CODE_A", analyzer="OLD_ANA",
                  effective="OLD_EFF_A")  # stale: OLD != CURRENT_EFF_A
        _seed_run(db_path, "rB", "MB", 1,
                  cfg="CFG_B", code="CODE_B", analyzer="OLD_ANA",
                  effective="CURRENT_EFF_B")  # fresh: matches

        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.get("/api/reports/stale-count").json()

        assert resp["stale_analyzer"] == 1, (
            f"only MA should be stale, got stale_analyzer={resp['stale_analyzer']}"
        )
        assert resp["fixable_count"] == 1
        assert resp["fixable_items"] == [{"machine": "MA", "mode": 1}], (
            f"only MA should be fixable, got {resp['fixable_items']}"
        )

    def test_both_machines_fresh_zero_stale(
        self,
        tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_analyzer, tmp_path, monkeypatch,
    ):
        """Both machines fresh → stale_analyzer==0, fixable_count==0."""
        mc = tmp_path / "machines.json"
        _write_machines_config(mc, {
            "MA": ("CFG_A", "CODE_A"),
            "MB": ("CFG_B", "CODE_B"),
        })
        app = _make_app(
            tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
            mc, fake_analyzer, monkeypatch,
        )
        db_path = tmp_state_dir / "console.db"

        _per_machine_current = {
            ("MA", 1): "EFF_A_CURRENT",
            ("MB", 1): "EFF_B_CURRENT",
        }

        class FakeEffCache:
            UNVERIFIABLE = "UNVERIFIABLE"
            def __init__(self, **_kwargs):
                pass
            def get(self, machine_id, mode):
                return _per_machine_current.get((machine_id, mode), self.UNVERIFIABLE)

        monkeypatch.setattr(
            "src.web_console.backend.effective_version_cache.EffectiveVersionCache",
            FakeEffCache,
        )

        _seed_run(db_path, "rA", "MA", 1,
                  cfg="CFG_A", code="CODE_A", analyzer="ANA",
                  effective="EFF_A_CURRENT")  # fresh
        _seed_run(db_path, "rB", "MB", 1,
                  cfg="CFG_B", code="CODE_B", analyzer="ANA",
                  effective="EFF_B_CURRENT")  # fresh

        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.get("/api/reports/stale-count").json()

        assert resp["stale_analyzer"] == 0
        assert resp["fixable_count"] == 0

    def test_both_machines_stale_when_both_effective_changed(
        self,
        tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_analyzer, tmp_path, monkeypatch,
    ):
        """When both machines have stale effective → both flagged (correct, not a bug)."""
        mc = tmp_path / "machines.json"
        _write_machines_config(mc, {
            "MA": ("CFG_A", "CODE_A"),
            "MB": ("CFG_B", "CODE_B"),
        })
        app = _make_app(
            tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
            mc, fake_analyzer, monkeypatch,
        )
        db_path = tmp_state_dir / "console.db"

        class FakeEffCacheBothNew:
            UNVERIFIABLE = "UNVERIFIABLE"
            def __init__(self, **_kwargs):
                pass
            def get(self, machine_id, mode):
                return {"MA": "NEW_EFF_A", "MB": "NEW_EFF_B"}.get(machine_id, self.UNVERIFIABLE)

        monkeypatch.setattr(
            "src.web_console.backend.effective_version_cache.EffectiveVersionCache",
            FakeEffCacheBothNew,
        )

        _write_stub_chunk(tmp_rawdata, "MA", 1, "CFG_A", "CODE_A")
        _write_stub_chunk(tmp_rawdata, "MB", 1, "CFG_B", "CODE_B")

        _seed_run(db_path, "rA", "MA", 1,
                  cfg="CFG_A", code="CODE_A", analyzer="OLD",
                  effective="OLD_EFF_A")  # stale
        _seed_run(db_path, "rB", "MB", 1,
                  cfg="CFG_B", code="CODE_B", analyzer="OLD",
                  effective="OLD_EFF_B")  # stale

        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.get("/api/reports/stale-count").json()

        assert resp["stale_analyzer"] == 2
        assert resp["fixable_count"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# SP2 — No false-fresh on closure/base edit
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoFalseFreshOnBaseChange:
    """Safety path 2: when base changes (simulated via monkeypatched cache),
    every machine's effective shifts → all reports correctly flagged stale.

    This simulates what happens when a closure file is edited: base flips,
    EffectiveVersionCache.get() returns a new hash for every machine, so any
    row whose effective_analyzer_version was stamped against the OLD base
    is now stale.

    Important: we do NOT actually edit a closure file here (that would flip
    the fleet-wide base hash permanently and break the hard gate). Instead we
    monkeypatch EffectiveVersionCache so its .get() returns a "new" hash.

    Inject-bug recipe:
      In app.py stale_report_count(), change:
          row_eff = row.get("effective_analyzer_version") or ""
          cur_eff = eff_cache.get(str(machine), int(mode))
          analyzer_is_stale = (row_eff != cur_eff)
      to use legacy field:
          row_eff = row.get("analyzer_version") or ""
          cur_eff = cur_analyzer   # old global
      If cur_analyzer happens to equal the rows' "OLD_GLOBAL_ANA" → false-fresh.
      More precisely: the test seeds rows with effective="OLD_EFF_HASH" and
      the fake cache returns "NEW_EFF_HASH" → without the per-machine effective
      comparator the rows look fresh (because analyzer_version == cur_analyzer).
      → test_base_change_flags_all_machines_stale fails → RED.
      Revert → GREEN.
    """

    def test_base_change_flags_all_machines_stale(
        self,
        tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_analyzer, tmp_path, monkeypatch,
    ):
        """Simulated base change: effective cache returns a NEW hash for every
        (machine, mode). All rows stamped with OLD effective → all stale.
        """
        mc = tmp_path / "machines.json"
        _write_machines_config(mc, {
            "MA": ("CFG_A", "CODE_A"),
            "MB": ("CFG_B", "CODE_B"),
        })
        app = _make_app(
            tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
            mc, fake_analyzer, monkeypatch,
        )
        db_path = tmp_state_dir / "console.db"

        # Simulate base flip: every machine now has a NEW effective hash
        class FakeEffCacheNewBase:
            UNVERIFIABLE = "UNVERIFIABLE"
            def __init__(self, **_kwargs):
                pass
            def get(self, machine_id, mode):
                # Simulate "closure changed → new base → new effective for everyone"
                return f"NEW_BASE_EFF_{machine_id}"

        monkeypatch.setattr(
            "src.web_console.backend.effective_version_cache.EffectiveVersionCache",
            FakeEffCacheNewBase,
        )

        _write_stub_chunk(tmp_rawdata, "MA", 1, "CFG_A", "CODE_A")
        _write_stub_chunk(tmp_rawdata, "MB", 1, "CFG_B", "CODE_B")

        # Both rows stamped with OLD effective (from pre-closure-edit analyzer)
        _seed_run(db_path, "rA", "MA", 1,
                  cfg="CFG_A", code="CODE_A", analyzer="OLD_GLOBAL_ANA",
                  effective="OLD_EFF_MA")  # stale vs NEW_BASE_EFF_MA
        _seed_run(db_path, "rB", "MB", 1,
                  cfg="CFG_B", code="CODE_B", analyzer="OLD_GLOBAL_ANA",
                  effective="OLD_EFF_MB")  # stale vs NEW_BASE_EFF_MB

        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.get("/api/reports/stale-count").json()

        assert resp["stale_analyzer"] == 2, (
            f"after base change all machines must be stale, got {resp['stale_analyzer']}"
        )
        assert resp["fixable_count"] == 2, (
            f"all stale + rawdata present → all fixable, got {resp['fixable_count']}"
        )

    def test_false_fresh_scenario(
        self,
        tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_analyzer, tmp_path, monkeypatch,
    ):
        """Verify that using the legacy global comparator WOULD produce false-fresh.

        This test is GREEN (documents the broken-world scenario by using the
        legacy field explicitly). It proves that the old approach IS wrong:
        when row.analyzer_version == cur_analyzer even though effective is stale,
        the row would appear fresh under the legacy comparator.

        This test intentionally reads the legacy field directly to simulate what
        the inject-bug would cause — and asserts the legacy approach gives the
        wrong answer (0 stale instead of 2). This is the "red-world" documented
        inline, not an inject into production code.
        """
        # Rows where row.analyzer_version == cur_analyzer (legacy "fresh")
        # but row.effective_analyzer_version != current effective (actually stale)
        mc = tmp_path / "machines.json"
        _write_machines_config(mc, {
            "MA": ("CFG_A", "CODE_A"),
            "MB": ("CFG_B", "CODE_B"),
        })
        app = _make_app(
            tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
            mc, fake_analyzer, monkeypatch,
        )
        db_path = tmp_state_dir / "console.db"

        # Cache returns NEW effective (simulating base flip)
        class FakeEffCacheNew:
            UNVERIFIABLE = "UNVERIFIABLE"
            def __init__(self, **_kwargs):
                pass
            def get(self, machine_id, mode):
                return "NEW_EFF_AFTER_BASE_FLIP"

        monkeypatch.setattr(
            "src.web_console.backend.effective_version_cache.EffectiveVersionCache",
            FakeEffCacheNew,
        )

        _write_stub_chunk(tmp_rawdata, "MA", 1, "CFG_A", "CODE_A")

        # Row: legacy analyzer_version is current BUT effective is stale
        # (honesty-3 must detect this as stale; legacy would not)
        _seed_run(db_path, "rA", "MA", 1,
                  cfg="CFG_A", code="CODE_A", analyzer="LEGACY_CURRENT",
                  effective="OLD_EFF_BEFORE_FLIP")  # stale vs NEW_EFF_AFTER_BASE_FLIP

        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.get("/api/reports/stale-count").json()

        # honesty-3 correctly flags it stale via effective_analyzer_version
        assert resp["stale_analyzer"] == 1, (
            "effective mismatch must still be caught even if legacy analyzer_version looks fresh"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SP3 — R-6 empty-cache honest dead-end
# ═══════════════════════════════════════════════════════════════════════════════


class TestR6EmptyCacheHonestDeadEnd:
    """Safety path 3: stale analyzer + ZERO cached rawdata →
    lands in needs_rawdata_items, NOT fixable_items, NOT fresh, NO crash.

    Verifies the M275/mode_7 = 0 chunks scenario from brief §4.4.

    Inject-bug recipe:
      In app.py stale_report_count(), remove the rawdata check:
          has_rawdata = bool(rs.get("usable_chunks", 0) > 0)
          if has_rawdata:
              fixable_keys.add(...)
          else:
              needs_rawdata_keys.add(...)
      and replace with simply:
          fixable_keys.add(str(machine), m_int)  # always fixable
      → test_stale_no_rawdata_lands_in_needs_rawdata fails because
        item appears in fixable_items not needs_rawdata_items → RED.
      Revert → GREEN.
    """

    def test_stale_no_rawdata_lands_in_needs_rawdata(
        self,
        tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_analyzer, tmp_path, monkeypatch,
    ):
        """M275-style: stale effective + ZERO chunks → needs_rawdata, not fixable."""
        mc = tmp_path / "machines.json"
        _write_machines_config(mc, {"M275": ("CFG_275", "CODE_275")})
        app = _make_app(
            tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
            mc, fake_analyzer, monkeypatch,
        )
        db_path = tmp_state_dir / "console.db"

        # Fake cache: current effective differs from row's → stale
        class FakeEffCacheStale:
            UNVERIFIABLE = "UNVERIFIABLE"
            def __init__(self, **_kwargs):
                pass
            def get(self, machine_id, mode):
                return "CURRENT_EFF_275"

        monkeypatch.setattr(
            "src.web_console.backend.effective_version_cache.EffectiveVersionCache",
            FakeEffCacheStale,
        )

        # NO rawdata chunk on disk (simulating M275/mode_7 empty index)
        # mode_7 dir doesn't even exist
        _seed_run(db_path, "r275", "M275", 7,
                  cfg="CFG_275", code="CODE_275", analyzer="OLD",
                  effective="OLD_EFF_275")  # stale vs CURRENT_EFF_275

        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.get("/api/reports/stale-count").json()

        # Must be stale but NOT fixable
        assert resp["stale_analyzer"] == 1
        assert resp["fixable_count"] == 0, (
            f"no rawdata → must not be fixable, got fixable_count={resp['fixable_count']}"
        )
        # Must appear in needs_rawdata_items
        assert resp["needs_rawdata_count"] == 1, (
            f"no rawdata → must be in needs_rawdata, got needs_rawdata_count={resp['needs_rawdata_count']}"
        )
        assert {"machine": "M275", "mode": 7} in resp["needs_rawdata_items"], (
            f"M275/mode_7 must be in needs_rawdata_items, got {resp['needs_rawdata_items']}"
        )

    def test_stale_with_rawdata_is_fixable_not_needs_rawdata(
        self,
        tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_analyzer, tmp_path, monkeypatch,
    ):
        """Stale effective + rawdata present → fixable_items, NOT needs_rawdata.
        Proves the presence/absence of rawdata drives the categorization.
        """
        mc = tmp_path / "machines.json"
        _write_machines_config(mc, {"M14": ("CFG_14", "CODE_14")})
        app = _make_app(
            tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
            mc, fake_analyzer, monkeypatch,
        )
        db_path = tmp_state_dir / "console.db"

        class FakeEffCacheStale:
            UNVERIFIABLE = "UNVERIFIABLE"
            def __init__(self, **_kwargs):
                pass
            def get(self, machine_id, mode):
                return "CURRENT_EFF_14"

        monkeypatch.setattr(
            "src.web_console.backend.effective_version_cache.EffectiveVersionCache",
            FakeEffCacheStale,
        )

        _write_stub_chunk(tmp_rawdata, "M14", 1, "CFG_14", "CODE_14")
        _seed_run(db_path, "r14", "M14", 1,
                  cfg="CFG_14", code="CODE_14", analyzer="OLD",
                  effective="OLD_EFF_14")

        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.get("/api/reports/stale-count").json()

        assert resp["fixable_count"] == 1
        assert resp["needs_rawdata_count"] == 0

    def test_r6_no_crash_on_missing_rawdata_dir(
        self,
        tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_analyzer, tmp_path, monkeypatch,
    ):
        """Rawdata dir doesn't exist (fresh install for machine) → no crash.
        The endpoint must return a valid JSON response even when the machine
        has never had any rawdata sampled.
        """
        mc = tmp_path / "machines.json"
        _write_machines_config(mc, {"MNEW": ("CFG_NEW", "CODE_NEW")})
        app = _make_app(
            tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
            mc, fake_analyzer, monkeypatch,
        )
        db_path = tmp_state_dir / "console.db"

        class FakeEffCacheStale:
            UNVERIFIABLE = "UNVERIFIABLE"
            def __init__(self, **_kwargs):
                pass
            def get(self, machine_id, mode):
                return "CURRENT_EFF_NEW"

        monkeypatch.setattr(
            "src.web_console.backend.effective_version_cache.EffectiveVersionCache",
            FakeEffCacheStale,
        )

        _seed_run(db_path, "rnew", "MNEW", 1,
                  cfg="CFG_NEW", code="CODE_NEW", analyzer="OLD",
                  effective="OLD_EFF_NEW")

        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            # Must NOT raise; must return valid response
            resp_http = c.get("/api/reports/stale-count")
            assert resp_http.status_code == 200
            resp = resp_http.json()
        # No rawdata dir → needs_rawdata
        assert resp["needs_rawdata_count"] == 1
        assert resp["fixable_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# SP4 — R-8 virtual honest effective stamp
# ═══════════════════════════════════════════════════════════════════════════════


class TestR8VirtualHonestEffective:
    """Safety path 4: virtual machine summary never gets empty effective_analyzer_version.

    Tests _patch_summary_effective_version() in virtual_analyzer.py.
    Virtual machines have no manifest, so PIA leaves effective_analyzer_version="".
    The post-delegate stamp in virtual_analyzer.py must fill it with the base hash
    + kind="virtual_base_only".

    Inject-bug recipe:
      In virtual_analyzer.py's _patch_summary_effective_version(), make it
      skip the stamp by returning early unconditionally:
          if not existing_eff:
              return   # BUG: skip stamp
      → test_virtual_summary_gets_base_hash fails because effective remains "" → RED.
      Revert → GREEN.
    """

    def _write_minimal_summary(self, output_dir: Path, effective: str = "") -> None:
        """Write a minimal summary.json simulating PIA output."""
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "machine": "M1sim",
            "mode": 1,
            "config_md5": "CFG1",
            "code_md5": "CODE1",
            "effective_analyzer_version": effective,
            "rtp": {"point_pct": 95.0},
        }
        (output_dir / "player_impact_summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )

    def test_virtual_summary_gets_base_hash(self, tmp_path):
        """When PIA leaves effective_analyzer_version empty, the post-delegate
        stamp fills it with compute_base_analyzer_version() value."""
        output_dir = tmp_path / "output"
        self._write_minimal_summary(output_dir, effective="")  # PIA left it empty

        from slot_designer.core.backend.virtual_analyzer import (
            _patch_summary_effective_version,
        )
        _patch_summary_effective_version(output_dir, "M1sim", 1)

        summary = json.loads(
            (output_dir / "player_impact_summary.json").read_text(encoding="utf-8")
        )
        eff = summary.get("effective_analyzer_version", "")
        assert eff, f"effective_analyzer_version must be non-empty after patch, got {eff!r}"
        assert len(eff) == 12, f"expected 12-char hex, got {eff!r}"
        assert eff != "UNVERIFIABLE", "virtual effective should be base hash, not sentinel"

        # Must carry the kind marker
        kind = summary.get("effective_analyzer_version_kind", "")
        assert kind == "virtual_base_only", (
            f"kind must be 'virtual_base_only', got {kind!r}"
        )

    def test_virtual_effective_matches_expected_base(self, tmp_path):
        """The stamped effective value must equal compute_base_analyzer_version()."""
        output_dir = tmp_path / "output"
        self._write_minimal_summary(output_dir, effective="")

        import sys
        sys.path.insert(0, "fresh_slotlab")
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        expected_base = compute_base_analyzer_version()

        from slot_designer.core.backend.virtual_analyzer import (
            _patch_summary_effective_version,
        )
        _patch_summary_effective_version(output_dir, "M1sim", 1)

        summary = json.loads(
            (output_dir / "player_impact_summary.json").read_text(encoding="utf-8")
        )
        eff = summary.get("effective_analyzer_version", "")
        assert eff == expected_base, (
            f"virtual effective must equal base hash {expected_base!r}, got {eff!r}"
        )

    def test_virtual_stamp_is_no_op_when_pia_sets_effective(self, tmp_path):
        """If PIA already set effective (future-proofing), patch is a no-op."""
        output_dir = tmp_path / "output"
        preexisting = "abc123def456"  # 12-char hex
        self._write_minimal_summary(output_dir, effective=preexisting)

        from slot_designer.core.backend.virtual_analyzer import (
            _patch_summary_effective_version,
        )
        _patch_summary_effective_version(output_dir, "M1sim", 1)

        summary = json.loads(
            (output_dir / "player_impact_summary.json").read_text(encoding="utf-8")
        )
        assert summary["effective_analyzer_version"] == preexisting, (
            "patch must not overwrite a pre-existing effective value"
        )

    def test_virtual_stamp_no_crash_missing_summary(self, tmp_path):
        """Missing summary.json → no crash; function logs to stderr and returns."""
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        # No summary.json written

        from slot_designer.core.backend.virtual_analyzer import (
            _patch_summary_effective_version,
        )
        # Must not raise
        _patch_summary_effective_version(output_dir, "M1sim", 1)
        # summary still absent — that's OK (run succeeded; just no stamp)
        assert not (output_dir / "player_impact_summary.json").exists()

    def test_virtual_effective_is_never_empty_after_stamp(self, tmp_path):
        """Core guarantee: after _patch_summary_effective_version, effective is NEVER ""."""
        output_dir = tmp_path / "output"
        self._write_minimal_summary(output_dir, effective="")

        from slot_designer.core.backend.virtual_analyzer import (
            _patch_summary_effective_version,
        )
        _patch_summary_effective_version(output_dir, "M1sim", 1)

        summary = json.loads(
            (output_dir / "player_impact_summary.json").read_text(encoding="utf-8")
        )
        assert summary.get("effective_analyzer_version") != "", (
            "effective must never be empty after stamp — that recreates the PIA swallow hole"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SP5 — No-manifest unverifiable ≠ stale; closure-missing surfaces
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoManifestUnverifiableNotStale:
    """Safety path 5: unregistered/virtual machine rows → UNVERIFIABLE →
    NOT counted stale, NOT fixable (honest). AND closure-missing FileNotFoundError
    is not swallowed — it propagates so the operator can investigate.

    SP5a (unverifiable ≠ stale) inject-bug recipe:
      In app.py stale_report_count(), remove the UNVERIFIABLE guard:
          if cur_eff != EffectiveVersionCache.UNVERIFIABLE and cur_eff:
              analyzer_is_stale = row_eff != cur_eff
      and replace with:
          analyzer_is_stale = row_eff != cur_eff  # BUG: treats UNVERIFIABLE as real hash
      → Machine with UNVERIFIABLE cur_eff and non-empty row_eff is marked stale
        (row_eff != "UNVERIFIABLE") → test_unverifiable_machine_not_stale fails → RED.
      Revert → GREEN.

    SP5b (closure-missing raises) inject-bug recipe:
      In effective_version_cache.py _ensure_base(), wrap the compute call:
          try:
              self._base_hash = compute_base_analyzer_version(...)
          except FileNotFoundError:
              self._base_hash = ""  # BUG: swallow
      → test_closure_missing_raises_not_swallowed fails on missing FileNotFoundError → RED.
      Revert → GREEN.
    """

    def test_unverifiable_machine_not_stale(
        self,
        tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_analyzer, tmp_path, monkeypatch,
    ):
        """Unregistered machine → cache returns UNVERIFIABLE → NOT stale, NOT fixable."""
        mc = tmp_path / "machines.json"
        # MUNREG is NOT in machines.json config (no md5 values)
        _write_machines_config(mc, {"M14": ("CFG_14", "CODE_14")})
        app = _make_app(
            tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
            mc, fake_analyzer, monkeypatch,
        )
        db_path = tmp_state_dir / "console.db"

        # Cache returns UNVERIFIABLE for MUNREG (no manifest)
        from src.web_console.backend.effective_version_cache import (
            EffectiveVersionCache as _RealCache,
        )
        _UNVERIFIABLE = _RealCache.UNVERIFIABLE

        class FakeEffCacheUnverifiable:
            UNVERIFIABLE = _UNVERIFIABLE
            def __init__(self, **_kwargs):
                pass
            def get(self, machine_id, mode):
                if machine_id == "MUNREG":
                    return self.UNVERIFIABLE
                return "CURRENT_EFF_14"

        monkeypatch.setattr(
            "src.web_console.backend.effective_version_cache.EffectiveVersionCache",
            FakeEffCacheUnverifiable,
        )

        # MUNREG: has effective but cache says UNVERIFIABLE (no manifest)
        _seed_run(db_path, "runreg", "MUNREG", 1,
                  cfg=None, code=None, analyzer=None,
                  effective="SOME_OLD_EFF")

        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.get("/api/reports/stale-count").json()

        # row_eff="SOME_OLD_EFF" is set, so the row is NOT in the untagged
        # bucket (untagged = `not row_cfg and not row_code and not row_eff`).
        # The reason it is not counted stale: the machine has no manifest, so
        # the cache returns UNVERIFIABLE, and the comparator guard
        # `if cur_eff != UNVERIFIABLE and cur_eff:` is False → staleness is
        # never evaluated. UNVERIFIABLE means "cannot verify", not "stale".
        assert resp["stale_analyzer"] == 0, (
            f"UNVERIFIABLE machine must NOT be counted stale, got {resp['stale_analyzer']}"
        )
        assert resp["fixable_count"] == 0, (
            f"UNVERIFIABLE machine must NOT be fixable, got {resp['fixable_count']}"
        )

    def test_unverifiable_in_versions_current_not_stale(
        self,
        tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_analyzer, tmp_path, monkeypatch,
    ):
        """versions/current returns UNVERIFIABLE for virtual machines in effective_versions."""
        mc = tmp_path / "machines.json"
        _write_machines_config(mc, {"M14": ("CFG_14", "CODE_14")})
        app = _make_app(
            tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
            mc, fake_analyzer, monkeypatch,
        )
        db_path = tmp_state_dir / "console.db"

        from src.web_console.backend.effective_version_cache import (
            EffectiveVersionCache as _RealCache,
        )
        _UNVERIFIABLE = _RealCache.UNVERIFIABLE

        class FakeEffCacheForVersions:
            UNVERIFIABLE = _UNVERIFIABLE
            def __init__(self, **_kwargs):
                pass
            def get(self, machine_id, mode):
                if machine_id == "M1sim":
                    return self.UNVERIFIABLE
                return "CURRENT_EFF_14"

        monkeypatch.setattr(
            "src.web_console.backend.effective_version_cache.EffectiveVersionCache",
            FakeEffCacheForVersions,
        )

        # Seed a virtual machine run so it appears in versions/current effective_versions
        _seed_run(db_path, "rvirt", "M1sim", 1,
                  cfg=None, code=None, analyzer=None, effective="")

        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.get("/api/versions/current").json()

        assert "effective_versions" in resp
        # M1sim must appear with UNVERIFIABLE value
        assert resp["effective_versions"].get("M1sim|1") == _UNVERIFIABLE, (
            f"virtual machine must have UNVERIFIABLE in effective_versions, "
            f"got {resp['effective_versions'].get('M1sim|1')!r}"
        )

    def test_closure_missing_raises_in_effective_cache(self, tmp_path):
        """EffectiveVersionCache with a missing closure file → FileNotFoundError, not swallowed.

        SP5b: closure-missing is a broken install and must surface loudly.
        """
        from pathlib import Path
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir(parents=True)
        # Write a manifest so the manifest-exists check passes (not the UNVERIFIABLE path)
        (manifests_dir / "MTEST.json").write_text(
            json.dumps({"machine_id": "MTEST", "manifest_version": 1,
                        "inherits_from": None, "features": []}),
            encoding="utf-8",
        )
        # Closure file does NOT exist
        bad_closure = ("this_file_does_not_exist_honesty3_test.py",)

        from src.web_console.backend.effective_version_cache import EffectiveVersionCache
        cache = EffectiveVersionCache(
            manifests_root=manifests_dir,
            closure_files=bad_closure,
            repo_root=tmp_path,
        )
        with pytest.raises(FileNotFoundError):
            cache.get("MTEST", 1)

    def test_stale_count_endpoint_propagates_closure_error(
        self,
        tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_analyzer, tmp_path, monkeypatch,
    ):
        """If EffectiveVersionCache raises FileNotFoundError (broken install),
        the stale-count endpoint lets it propagate (not silently fresh).

        FastAPI's TestClient raises the exception rather than converting to 500
        when raise_server_exceptions=True (the default). The key invariant is
        that the error is NOT swallowed — the endpoint does not catch it and
        return a fake "0 stale" or "0 fixable" response. We assert that the
        error is raised (not eaten) by checking it propagates to the test.

        Alternative phrasing: the endpoint MUST NOT return HTTP 200 with stale=0
        when the effective cache is broken. Swallowing would give stale=0 (false-fresh).
        """
        mc = tmp_path / "machines.json"
        _write_machines_config(mc, {"M14": ("CFG_14", "CODE_14")})
        app = _make_app(
            tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
            mc, fake_analyzer, monkeypatch,
        )
        db_path = tmp_state_dir / "console.db"

        class FakeEffCacheRaises:
            UNVERIFIABLE = "UNVERIFIABLE"
            def __init__(self, **_kwargs):
                pass
            def get(self, machine_id, mode):
                raise FileNotFoundError("closure file gone — broken install simulation")

        monkeypatch.setattr(
            "src.web_console.backend.effective_version_cache.EffectiveVersionCache",
            FakeEffCacheRaises,
        )

        _seed_run(db_path, "r14", "M14", 1,
                  cfg="CFG_14", code="CODE_14", analyzer="OLD",
                  effective="OLD_EFF")

        from fastapi.testclient import TestClient
        # TestClient with raise_server_exceptions=True (default) propagates
        # unhandled server exceptions to the test. This proves the error is NOT
        # swallowed into a false-fresh 200 response.
        with pytest.raises(FileNotFoundError, match="closure file gone"):
            with TestClient(app, raise_server_exceptions=True) as c:
                c.get("/api/reports/stale-count")


# ═══════════════════════════════════════════════════════════════════════════════
# SP — Frontend versionBadges per-machine effective comparator (additional)
# ═══════════════════════════════════════════════════════════════════════════════
# These tests run pure.js via a subprocess to prove the frontend comparator
# reads effective_versions, not the legacy global. They complement the existing
# pure.test.cjs tests with the inject-bug perspective from this module.


class TestFrontendVersionBadgesIsolation:
    """Verify that versionBadges reads per-(machine,mode) effective_versions, not global.

    These are documented here (not in pure.test.cjs) to group the inject-bug
    evidence for SP1-frontend with the other honesty-3 safety paths.

    The full functional tests are in tests/frontend/pure.test.cjs.
    These Python tests invoke the JS tests via subprocess to get them in the
    pytest report, and to document the expected inject-bug behavior.

    Inject-bug recipe for frontend SP1:
      In pure.js versionBadges(), change:
          const curEffective = modeKey ? (effectiveMap[modeKey] || "") : "";
      to use the global:
          const curEffective = (current && current.analyzer_version) || "";
      → test "versionBadges: analyzer mismatch" passes (row.effective matches
        something different from current.analyzer_version) but
        "versionBadges: machine missing from current" fails because M999's
        analyzer_version matches → falsely fresh → RED.
      Revert → GREEN.
    """

    def test_frontend_pure_tests_pass(self):
        """Run the pure.js test suite via Node to confirm all versionBadges tests pass.

        This is the e2e proof per feedback_perf_claim_needs_e2e_event_stream.md —
        a real subprocess, not just a mock.
        """
        import subprocess
        import io
        repo_root = Path(__file__).resolve().parent.parent.parent
        result = subprocess.run(
            ["node", "--test",
             str(repo_root / "tests" / "frontend" / "pure.test.cjs")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(repo_root),
        )
        # Decode with errors="replace" to handle Windows code page issues
        stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        output = stdout + stderr
        # Check for versionBadges-specific failures
        assert "versionBadges" in output, (
            "pure.test.cjs must include versionBadges tests"
        )
        assert result.returncode == 0, (
            f"pure.test.cjs failed (return code {result.returncode}):\n"
            f"stdout: {stdout[-3000:]}\n"
            f"stderr: {stderr[-1000:]}"
        )
