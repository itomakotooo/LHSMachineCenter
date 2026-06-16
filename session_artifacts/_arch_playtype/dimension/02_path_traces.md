# 02_path_traces.md — Path / Dimension Ground Truth

Traced: 2026-06-15
Source: rawdata cached chunks (json.loads roundResult; no estimates)
All numbers are from parsed rounds.

---

## Parse provenance

| Machine | Mode | Chunks | Total rounds |
|---------|------|--------|-------------|
| M275 | 1 | chunk_0001, chunk_0002 (8 robots each) | 89,090 |
| M15 | 1 | chunk_0001 – chunk_0224 (8 robots each) | 2,135,124 |
| M43 | 1 | chunk_0002 – chunk_0042 (8 robots each) | 696,410 |
| M279 | 1 | chunk_0001 – chunk_0048 (8 robots each) | 2,139,508 |

SpinType sanity tallies (confirm deep parse, not raw-text grep):

| Machine | ST | Count |
|---------|----|-------|
| M275 | 126 | 9,090 |
| M275 | 140 | 80,000 |
| M15 | 1 | 2,048,000 |
| M15 | 14 | 64,033 |
| M15 | 15 | 23,091 |
| M43 | 1 | 680,000 |
| M43 | 50 | 9,264 |
| M43 | 51 | 7,146 |
| M279 | 140 | 1,920,000 |
| M279 | 36 | 217,588 |
| M279 | 2 | 1,920 |

---

## M275 ST126 (NewFreespin) — confirmed 2-path

### Discriminator

Field: `GameplayTriggerType` (present on every ST126 round; values {0, 2} only; 0 unmapped values observed).

| GTT value | Path label | Count (rounds) | Sessions | Total win |
|-----------|-----------|---------------|---------|-----------|
| 0 | scatter (3 bonus symbols, pid-666) | 8,290 | 829 | 32,685,500 |
| 2 | collect_peak (CollectCount==1000) | 800 | 80 | 2,846,000 |

### Trigger-round confirmation

For each GTT=0 session, the preceding ST140 round: has pid-666 in PayoutIdToWinAmount (829/829 matches); CC values span full range (never necessarily 1000).

For each GTT=2 session, the preceding ST140 round: CC==1000 on 80/80 matches; pid-666 present on 1/80 (see double-trigger below).

### Double-trigger edge case (1 event in 89,090 rounds)

chunk_0001.json, robot 3, round index 4459:
- ST140 round: CC=1000 AND pid-666 = {'666': 0} (win=0 trigger)
- Immediately followed by: GTT=2 session (Freespin 1 at [4460]), then GTT=0 session (Freespin 1 at [4470])
- The collect_peak session is emitted FIRST (GTT=2), then the scatter session (GTT=0)
- Same single ST140 round opens BOTH sessions in order

### Outcome comparison (today's config — both slots carry identical values)

**Per-round win statistics:**

| Path | n | mean_win | sd | se |
|------|---|----------|----|----|
| scatter (GTT=0) | 8,290 | 3,942.8 | 12,638.8 | 138.8 |
| collect_peak (GTT=2) | 800 | 3,557.5 | 9,364.5 | 331.1 |

Z-score for difference in means: 1.07 (|Z| < 1.96; NOT significant at 5%).

**Skin (ReelSkin) distribution per round:**

| Skin | scatter % | collect_peak % |
|------|-----------|----------------|
| 11 | 30.0% (2,487) | 30.0% (240) |
| 21 | 40.0% (3,316) | 40.0% (320) |
| 31 | 30.0% (2,487) | 30.0% (240) |

Identical proportions to 3 decimal places.

**Hit rate per session:**
- scatter: 790/829 = 95.3%
- collect_peak: 76/80 = 95.0%

**ExtraRatio ladder at session start:**
- Not all sessions start at ER=100: 222/829 scatter and 26/80 collect_peak sessions start above 100.
- This is because the ER state carries over between sessions: when a session ends mid-ladder (e.g. last ER=1500), the next session starts at a reduced ER (e.g. 200 or 300), for BOTH paths.
- The carry-over pattern is identical across paths — ER ladder is a shared machine-level state, not path-specific.

**Conclusion:** today both paths produce STATISTICALLY IDENTICAL outcomes. The paths are genuinely distinct (different config slots) — if those slots ever diverged in value (different ER ladders, different session counts, different skin probabilities) ALL per-ST126 metrics would split: hit-rate, avg-win, ER progression, skin distribution, multiplier histogram.

---

## M275 ST140 (NormalCollectionSpin) — 1 path

GameplayTriggerType on ST140: all 80,000 rounds have GTT=0 (constant; no behavioral split). This is a schema-version marker present in every round uniformly — no entry path discrimination.

Entry context: always follows another ST140 (continuation) or the last ST126 round of a freespin session.

---

## M15 ST1 (paid spin) — 1 path

**GTT field presence is a schema version marker, not a behavioral discriminator.**

Evidence:
- Chunks 0001–0216: GTT field ABSENT from every ST1 round (field not in the JSON object).
- Chunks 0217–0224 (last 8): GTT field present, value always 0.
- pid distribution comparison across schema versions: pids {9, 8, 666, 7, 5, 71, 3, 2, 21, 4} appear at same relative rates in both groups. Mean win: GTT=0 chunks avg 413.3, GTT-absent chunks avg 425.7 (Z = not significant given slot variance).
- The field's presence correlates with chunk timestamp (later batches), not with any player-observable game mode.

**One entry path:** ST1 always follows ST1 (or ST15 = end of previous TopDollar sequence). No secondary entry.

---

## M15 ST14 (TopDollar pick) — 1 path, ExtraRatio is NOT a path discriminator

**Entry context (10-chunk sample, 2,444 ST14 events):**

| Previous ST | Count |
|------------|-------|
| ST14 | 1,573 (continuation pick) |
| ST1 with pid-666 | 805 (first pick) |
| ST1 with pids {666, 9} | 65 |
| ST1 with pids {666, 71} | 1 |

Every ST14 session is opened by ST1 with pid-666 in its PayoutIdToWinAmount. Subsequent picks are ST14->ST14 chains. No other opening signal observed.

**ExtraRatio on ST14 (1/2/4) — multiplier within the session, NOT a separate path:**

| ExtraRatio | Count (20-chunk sample) |
|-----------|------------------------|
| 1 | 3,708 |
| 2 | 977 |
| 4 | 225 |

The ExtraRatio value is NOT determined by the triggering ST1's content (the trigger round always has ReMarks="Trigger", RewardLastNode=['666-'], and ExtraRatio is ABSENT from ST1). The multiplier (1x/2x/4x) is set per-pick by the engine — it is a per-event property of individual ST14 rounds within a session, not an entry path. DoubleDiamond symbol count on the trigger round does not reliably predict the ExtraRatio distribution. All ST14 events share one config slot.

---

## M15 ST15 (TopDollar settlement) — 1 path

Entry context (10-chunk sample): 871/871 ST15 events preceded by ST14. No other entry observed. Single path.

---

## M43 ST1 (paid spin) — 1 path

GameplayTriggerType: present only in chunk_0042 (last chunk, value always 0; all earlier chunks: absent). Z-score of win difference between GTT-present and GTT-absent groups: 0.11 (not significant; same behavioral path). Schema version marker only.

No secondary entry observed.

---

## M43 ST50 (WinRespin) — 1 path

**GTT=0 in last chunk only (schema version, confirmed):**
- chunk_0042: 581 ST50 rounds all with GTT=0, avg_win=2,321.9
- All other chunks: 8,683 ST50 rounds with GTT=None, avg_win=2,250.1
- Z-score: 0.11 (not significant)

**Entry context:** Every ST50 (9,264 total) preceded by ST1. No other entry. Triggering ST1 always has non-zero WinCredits (win-gated; trigger threshold not visible in rawdata — the minimum winning amount is not a field).

All ST50 rounds carry ReMarks="ReSpin" and RTPId=1. Single path.

---

## M43 ST51 (WinMiniGame) — sequence-level 2 paths, NO in-round discriminating field

**Entry context (full 696,410 rounds):**

| Sequence | Count |
|---------|-------|
| ST1 -> ST51 (direct; no respin) | 7,068 |
| ST50 -> ST51 (respin completes, then minigame fires) | 78 |

Two sequence-level paths exist. However:

1. ST51 itself carries NO discriminating field: fields are {WinCredits, ReMarks, SpinTimes, SpinType, RTPId, IsLackCreditsSpin, LastCredits}. No GTT, no pid, no trigger-path field.
2. The triggering ST1 round for the "direct" path typically has empty PayoutIdToWinAmount (not pid-gated; the minigame fires by in-engine per-spin random, per manifest caveat confirmed by user sign-off).
3. Outcome distributions:

| Sequence | n | mean_win | sd |
|---------|---|----------|-----|
| ST1->ST51 | 7,068 | 27,214.5 | 8,015.5 |
| ST50->ST51 | 78 | 26,948.7 | 8,805.1 |

Z-score: 0.27. Outcomes are STATISTICALLY IDENTICAL.

4. MiniGame node-code distribution (ReMarks): same codes appear in both paths (MiniGame[110], [108], [109], [109,101], etc.) at proportional rates.

**Conclusion:** M43 ST51 has two sequence-level paths that the rawdata cannot distinguish via any per-round field in ST51 itself. Both paths deliver the SAME minigame. This is NOT an independently configurable multi-path in the M275-ST126 sense — there is no config slot split possible here. The two-path observation is a sequence artifact of whether a respin happened to fire before the minigame trigger.

---

## M279 ST140 (NormalCollectionSpin) — 1 path

GTT field: present in last 8 chunks (chunk_0041–chunk_0048), value always 0 — schema version marker, same pattern as M15/M43.

Entry contexts: ST140 follows ST140 (184,713 — continuation), ST36 (15,087 — return after move sequence), ST2 (160 — return after wheel spin). All three are returns to the normal paid spin loop, not alternative entry paths for the ST140 event type.

Single behavioral path for ST140 itself.

---

## M279 ST36 (MoveSpin) — 1 path

**Entry context (10-chunk sample):**

| Previous ST | Count |
|------------|-------|
| ST140 | 15,102 |
| ST36 | 7,497 (continuation within move sequence) |

**Trigger discriminator:** The trigger is presence of directional-wild symbols (wild_up, wild_down, wild2x_mid) in StopSymbolsByCol on the preceding ST140 round. Of the ST140 -> ST36 transitions: 17,729 have EMPTY RewardLastNode (no payline win; triggered purely by wild stop position), and the remainder have paying pids alongside the wild-symbol trigger.

No round-level pid triggers ST36 (no dedicated trigger payout_id). The trigger is stop-content-based, not pid-based. GTT=0 appears only in last 8 chunks (schema version). All ST36 carry ReMarks="move". Single path.

---

## M279 ST2 (Wheel) — sequence-level 2 paths, NO in-round discriminating field

**Entry context (full 2,139,508 rounds):**

| Sequence | Count |
|---------|-------|
| ST140 -> ST2 (direct; wheel fires after CC=1000 with no preceding move) | 1,770 |
| ST36 -> ST2 (move sequence completes at CC=1000, wheel fires after final move) | 150 |

Total ST2: 1,920 (matches full-corpus count).

**Trigger CC:** In all 200 sampled cases (5 chunks), the preceding ST140 round has CollectCount=1000. The CC=1000 fires the wheel regardless of whether moves intervened. ST2 itself carries NO discriminating field: fields are {WinCredits, ReMarks, SpinTimes, SpinType, RTPId, IsLackCreditsSpin, LastCredits, StopSymbolsByCol}. No GTT, no path field.

**Outcome comparison:**

| Path | n | avg_win | CellIndex dist |
|------|---|---------|---------------|
| direct (ST140->ST2) | 1,770 | 40,406.8 | {1:14.7%, 10:14.6%, 12:14.3%, 3:9.2%, 5:9.3%, 7:8.9%, 2:7.7%, 8:6.1%, 4:5.0%, 11:4.9%, 6:3.1%, 9:2.3%} |
| via ST36 (ST36->ST2) | 150 | 35,066.7 | {1:14.0%, 12:16.0%, 7:13.3%, 2:12.7%, 10:11.3%, 3:7.3%, 5:6.7%, 11:6.0%, 4:4.7%, 8:4.0%, 6:2.0%, 9:2.0%} |

The 13% win difference (40,407 vs 35,067) is within sampling noise at n=150. CellIndex proportions are consistent across paths (no structural difference). Both paths use WheelId=1 and produce identical ReMarks format "WheelSpin CellIndex X; WheelId 1;".

**Conclusion:** M279 ST2 has two sequence-level paths that are NOT discriminable via any in-round field. Same mechanism (same wheel, same config slot). This is a sequence-order artifact, not a configurable dimension split.

---

## Cross-machine GTT schema version pattern

`GameplayTriggerType` appears with value 0 on all STs in the LATEST sampled chunks only:

| Machine | STs with GTT=0 | Chunks | Pattern |
|---------|---------------|--------|---------|
| M15 | ST1 | chunks 0217–0224 (last 8) | schema version only |
| M43 | ST1, ST50 | chunk_0042 (last 1) | schema version only |
| M279 | ST140, ST36 | chunks 0041–0048 (last 8) | schema version only |
| M275 | ST126 (GTT=0 vs GTT=2) | BOTH chunks | BEHAVIORAL discriminator (not schema version) |

On M275 ST126, GTT takes values {0, 2} with real semantic meaning confirmed by the trigger-round analysis (GTT=0 sessions: triggering ST140 has pid-666; GTT=2 sessions: triggering ST140 has CC=1000). On all other machines, GTT value is always 0 and correlates purely with sampling batch timestamp.

---

## Latent multi-path probe results

The question: "does any existing ST have a SECOND entry route we did not model?"

| ST | Machine | Finding | 2nd path? |
|----|---------|---------|-----------|
| ST1 | M15 | Single path (GTT=0 in late chunks = schema version) | No |
| ST14 | M15 | Single path (ExtraRatio is a per-round multiplier, not path) | No |
| ST15 | M15 | Single path (always from last ST14) | No |
| ST1 | M43 | Single path (GTT=0 in last chunk = schema version) | No |
| ST50 | M43 | Single path (GTT=0 in last chunk = schema version) | No |
| ST51 | M43 | 2 sequence paths (ST1->ST51 and ST50->ST51) but NO in-round discriminator, SAME outcomes (Z=0.27), SAME minigame | No discriminable path |
| ST140 | M279 | Single path (GTT=0 in last 8 chunks = schema version) | No |
| ST36 | M279 | Single path (wild-stop trigger; GTT=0 = schema version) | No |
| ST2 | M279 | 2 sequence paths (direct and via ST36) but NO in-round discriminator, same WheelId=1 | No discriminable path |
| ST126 | M275 | **2 TRUE paths with GTT discriminator** | YES — GTT=0 vs GTT=2 |
| ST140 | M275 | Single path (GTT constant 0) | No |

---

## Could NOT determine

1. **M43 ST51 exact random trigger probability:** The per-spin minigame trigger rate is in-engine, not expressed as a rawdata field. The 7,068 direct-trigger count includes events where no immediately preceding pid triggered it — the trigger is opaque. Cannot distinguish "triggered on this spin" from "triggered on a prior spin's deferred result."

2. **M279 ST36 exact wild-nudge trigger threshold:** The stop-symbol presence of directional wilds is necessary but the exact gating rule (e.g., must land in a specific row? minimum count?) cannot be determined from PayoutIdToWinAmount alone. 17,729 of the ST36 trigger rounds have empty PayoutIdToWinAmount — the trigger is not pid-gated.

3. **M279 ST2 via-ST36 vs direct path separation at config level:** The two sequence paths produce the same wheel (same WheelId=1, same CellIndex distribution). Cannot determine from rawdata whether these are routed through separate config slots or the same one.

4. **M15 ST14 ExtraRatio determination mechanism:** The 1x/2x/4x multiplier on individual picks is not traceable to the triggering ST1 round's stop content (DoubleDiamond count does not reliably predict ER). The engine-internal rule for assigning ER to each pick is unobservable in rawdata.

5. **M275 ST126 double-trigger frequency at production scale:** 1 double-trigger event in 89,090 rounds (= 1 per 1,000 paid spins, 1.09% of sessions). The exact probability is a function of the probability that a scatter trigger and a CC=1000 coincide on the same paid spin — a rare but real event. Only 1 observed; cannot measure its exact rate precisely from this sample.
