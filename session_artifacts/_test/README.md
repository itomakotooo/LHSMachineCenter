# Fleet console smoke test — Wave 1 inputs (full spec: planner brief in session)

Files:
- `build_work_plan.py` — one-shot generator → `work_plan.csv`.
- `work_plan.csv` — 255 reps (203 `copy_from_main`, 52 `fresh_sample`), one per variant family.
- `runner.py` — Wave 2 invokes this. CLI: `--limit N`, `--retry-failed`, `--no-retry-pass`.
- `run_log.jsonl` — append-only audit trail (written by runner).

Prereq: Wave 2 starts the console backend at `http://127.0.0.1:8877` (using `configs/servers.json` default `dev`) BEFORE invoking runner.py. Runner exits 2 with a hint if `/api/health` is unreachable.

Workflow: `python build_work_plan.py` (already done) → supervisor starts backend → `python runner.py`. Status: `pending → copied → submitted → completed|failed|timeout`, with one auto retry pass for failures at end.
