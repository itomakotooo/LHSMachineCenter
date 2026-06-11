# 02_traces — real-rawdata ground truth (event-based)

> Per the redesigned arch process (agent charters `.claude/agents/arch-*.md`): **real-rawdata traces only — no design, no
> opinions.** These are the validated facts the model + any build must hold. Produced 2026-06-02 by deep-parsing
> cached chunks (`json.loads` the JSON-string `response`; walk `roundResult`; a raw grep false-negatives on
> escaped JSON). Cached only — no upstream fetch.

## M275 — same SpinType, different trigger, different account (proves: trigger = attribution)
M275 mode_1, 5 chunks. The freespin event is **SpinType 126** (one event kind). It is opened by two different
triggers, and its economy books to different accounts accordingly (each trace from the per-session walk):

| trigger of the freespin session | sessions | freespin win |
|---|---|---|
| scatter (paid spin carries `pay_id 666`) | 437 | 16,681,500 |
| BCM cycle (paid spin `CollectCount == peak 1000`) | 39 | 1,190,500 |
| both signals at once (ambiguous) | 1 | 80,500 |
| **no trigger (orphan)** | **0** | — |

477 freespin sessions; **every one resolves to exactly one trigger; total reconciles** (17,952,500 = 16.68M +
1.19M + 0.08M); **no double-count, no drop.** The two triggers are essentially disjoint — exactly 1 of 40,000
paid rounds carries both `pay_id 666` AND `CollectCount==peak`. → The SAME SpinType (126) parses identically but
books to different accounts decided by the trigger. An "ST → one bucket" map cannot express this.

Examples (real rounds): scatter — paid spin `cc=7` (mid-cycle) + `pay_id 666` → 10 freespins, win 127,500.
BCM — paid spin `cc=1000` (peak) + no 666 → 10 freespins, win 81,000. Identical "Freespin N" rounds, different account.

## M15 — a SpinType that is a player CHOICE (TopDollar), + its statistics
M15 mode_1, 5 chunks (440 TopDollar sessions, 40,000 base spins). TopDollar's events:
- **ST=1** — base paid spin (cost 1000); a `ReMarks="Trigger"` ST=1 opens a TopDollar session.
- **ST=14** — the player's PICK (玩法: up to 4 picks; stop early, or forced to take the 4th). Fields:
  `DollarCount`, `ChosenDollar` (e.g. "5-10-5"), `OfferValue`. **`WinCredits` here is a PREVIEW of the offer,
  NOT real win → 0 economy** (else RTP double-counts).
- **ST=15** — settlement; `WinAmount` = the accepted/forced offer = the real win.

ST=14 statistics (the behavioral value a "phantom 0-win" reading discards):

| stat | value |
|---|---|
| picks-per-session (1 / 2 / 3 / 4) | 104 / 66 / 69 / 201 |
| stopped-early vs forced-4th | 54.3% / 45.7% |
| bad-gamble (forced 4th < a passed offer) | 91 / 201 = 45.3% |
| final settled value | median 40k, max 440k |
| dollar tiers | 5:2188, 10:1030, 20:230, 50:22, 100:2 |
| trigger rate | 440 / 40000 = 1.10% of base spins |
| **TopDollar RTP contribution** | **50.4%** |

Headline: TopDollar is a **1.1%-frequency event carrying ~50% of RTP**; players gamble to the 4th pick 46% of
the time, and 45% of those land below a passed offer. This is the validated spec the M15 event parser must encode.
