# M1 — reel 权重

## 当前状态

| mode | 类型 | RTP | hit_rate | CV | 文件 |
|---|---|---|---|---|---|
| 1 | classic 单线 | 93.48% | 15.29% | 5.49 | [mode_1/](mode_1/) |
| 2 | 幸运模式 | 290.94% | 27.78% | 4.08 | [mode_2/](mode_2/) |

每个 mode 一个子目录，包含：
- `reel_weights.json` —— 引擎 / 虚拟 console 读这个
- `reel_weights.tsv` —— 人类可读 36×3 表格
- `NOTES.md` —— 数值 + 设计意图 + pay_id 分解
- `TUNE_REPORT.md` —— 最近一次 tune 的 Phase 4/5 原始报告

## 设计约束

两个 mode **共用 paytable + rules**（都从 `slot_designer/specs/M1.spec.json` 读），**只换 reel 权重**。paytable 不能为了 mode 2 改 —— 改了 mode 1 也跟着变。

## 重跑 tune

见每个 mode 目录里 `NOTES.md` 末尾的 "Tune 命令" 章节。重跑会原地覆盖 `reel_weights.json` + `TUNE_REPORT.md`。历史版本走 git：

```bash
git log --follow -- slot_designer/weights/M1/mode_2/reel_weights.json
git show <sha>:slot_designer/weights/M1/mode_2/reel_weights.json > /tmp/old_mode2.json
```
