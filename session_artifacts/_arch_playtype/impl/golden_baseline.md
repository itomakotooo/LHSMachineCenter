# Pristine golden baselines — byte-identical reference for Commit B+

Captured by coordinator (impl-verifier agent was unavailable — transient socket failures).
Captured on **HEAD `7babf1e`** (Commit A is inert scaffolding → HEAD output == pristine analyzer output).

## Exact reproducible command (the Commit-B tester MUST re-run identically post-change)
```
python -m fresh_slotlab.player_impact_analyzer \
  --machine <M> --rtp-mode 1 \
  --from-cache rawdata/<M>/mode_1 \
  --output-dir <dir> \
  --max-chunks 2
```
- `--from-cache` only (cached rawdata; NO upstream fetch). `--bet` defaults to 1000.
- Deterministic given the same cached chunks + same `--max-chunks 2`.

## Pilots captured (9), mode_1
M14 (pure paid), M272 (BCM simple), M275 (BCM hybrid+jackpot), M279 (BCM+nudge+wheel),
M274 (BCM minigame, cc=0), M268 (BCM lockreels), M15 (TopDollar selector),
M120 (multi-symbol collection), M10 (lock-lines, cc=0 family).

## Golden location (ephemeral — NOT committed; under gitignored cache/)
`cache/_playtype_golden_pristine/<M>/player_impact_summary.json` (+ `player_impact_report.md`, `run.log`)

## Byte-identical comparison rule
Compare the summary JSON **after normalizing out these VOLATILE fields** (they differ on every run and/or on any code edit, so they are NOT part of behavior):
- `report_id` (embeds a timestamp)
- `run_id` (embeds a timestamp)
- `analyzer_version` (monolith code hash — changes when parser.py etc. change)
- `effective_analyzer_version` (per-machine effective hash — changes likewise)
- `effective_analyzer_version_error`
- `duration_seconds`, `started_at`, `finished_at`, `evaluated_at` (wall-clock timing fields — confirmed volatile during Commit B)
- any other timestamp / wall-clock-duration field encountered deeper in the summary

**KEEP** in the comparison (these describe the cached DATA, not the code, so they must stay stable for the same cache): `config_md5`, `code_md5`, and all analytical content — `sampling.*` counts, RTP, `payouts_by_spin_type`, `payout_ids_*`, `all_cycle_peaks`, `collect_mechanic`, bucket histograms, etc.

A behavior-neutral change (Commit B flag-off AND flag-on-empty-registry) must produce a summary that is **identical to the pristine golden after normalization**. Any diff in a KEPT field = a real behavior change = the byte-identical gate fails.

## Note
`config_md5`/`code_md5` are upstream-data envelope hashes (stable for the same cache). If a future change alters how they are computed, revisit this list.
