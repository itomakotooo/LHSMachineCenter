# M43 — user brief (verbatim user direction)

> Per `slot_designer/ONBOARDING_PROCESS.md` §1, this file is **the verbatim source of user qualitative direction**, never paraphrased. Stage 3.5 Boundary Contract §1 quotes from this file directly.

---

## v1 — kickoff 2026-05-13

User direction (paraphrased here for the brief; verbatim quotes in §1.1 below):

1. **Scope**: ship mode 1 first; derive mode 7 / 2 / 5 in subsequent sessions per framework §C/§D + philosophy. New universal workflow ("以后所有机台都这么做").
2. **Archetype**: Lucky Ducky — well-known IGT machine.
3. **Current state assessment**: bucket distribution (multiplier buckets) looks "稀烂" (very bad); high-multiplier bucket share too thin; overall shape unreasonable.
4. **Hard target**:
   - Mode 1 RTP ∈ [94, 96]% (95% ± 1pp)
   - More share in high-multiplier buckets
   - More reasonable bucket distribution (qualitative; will be quantified at Stage 3.5)

### §1.1 verbatim quotes

> "1，先做mode1，然后根据mode1结合项目框架和哲学，推导出其他mode。以后所有机台都这么做。"

> "2，这是lucky ducky，知名机台。至少从倍率分桶来看，现在的版本很差劲。希望高倍率再多一些，分布再合理一些。"

> "3，rtp在95+-1，其他的刚刚回答了。"

> "4也回答了。你继续分析。"

---

## To clarify at Stage 3.5 (Boundary Contract drafting)

Items the Designer must pose to user during Stage 3.5 Step 7 sign-off (per ONBOARDING_PROCESS.md §1.2 — qualitative vs quantitative ambiguity resolution):

1. **"高倍率"具体哪几个桶**: 是 100×+ / 200×+ / 500×+ / 1000×+？each bucket 想要多少 share / RTP pp？
2. **"分布再合理"哪个形状**: bell-shape peak 5-20× / mid-heavy 1-20× / boom-bust 0+顶 / classic balanced shape？参考 archetype Lucky Ducky 业界数据还是 user 自己有偏好？
3. **Mode 1 hit rate** 期望（user 未指定；按 IGT 1-line classic baseline 12-20% 推还是有具体倾向）？
4. **波动性 (CV)** 期望（未指定；按 RWB baseline ~10 推还是有具体倾向）？
5. **顶奖 cadence**：lifetime story tier (1 in 50-100k spins) 还是 session-rare (1 in 10k)？per philosophy §7 + reference_classic_slot_rtp_distribution.md
6. **Feature mechanism**：M43 logicClassNames 有 wild-respin + mini-game。这两个 feature 是 always-on 还是只在某 RTP mode 启用？是否影响 mode 1 hit / RTP target？
7. **Avoid 范围**：是否有"避免 1000× 以上奖"或类似硬上限？(per M15 user_brief §5 类比)

---

## Reference (out-of-scope this session, captured for future mode 7/2/5 sessions)

- **Mode 7** (cut, 85% RTP) — per universal §C/§D, derive from mode 1 by 砍小奖 / maintain mid/big-pay hit
- **Mode 2** (lucky, ~300% RTP) — independent lucky archetype lifted from mode 1 baseline (per universal §C "mode 1 和 mode 2 是独立 archetypes 不派生" — but lift direction taken from mode 1 hit profile)
- **Mode 5** (super-lucky, ~500% RTP) — base byte-identical to mode 2 + feature / top-bucket enhancement
- Universal rule: 同一 reel_strips 跨 mode 字节级一致 (per ARCHITECTURE.md §8 invariant + DESIGN_PHILOSOPHY.md §E)

---

## Change log

- 2026-05-13 v1 — initial brief from session kickoff (4 numbered direction items)
