# Reel 权重调参交付

每台机台一个子目录，每个 **configSummaryMd5 short（前 8 位）= 一个独立版本**。

## 命名：md5 即版本号

每次调参产出的 reel 配置落到 `<machine>/<md5_short>/`。目录名就是虚拟 console UI 里看到的 md5，两边对得上：

```
UI 显示                   →  文件系统路径
Mode 1 · 当前 558dfcdd…  →  slot_designer/deliverables/M1/558dfcdd/
Mode 1 · 历史 32251c25…  →  slot_designer/deliverables/M1/32251c25/
Mode 2 · 当前 e4017d61…  →  slot_designer/deliverables/M1/e4017d61/
Mode 2 · 历史 6edf1ca3…  →  slot_designer/deliverables/M1/6edf1ca3/
```

不用"v1 / v2"这种语义版本号 —— md5 本身就是内容指纹，重跑得到相同结果 = 相同 md5 = 同一版本，任何字节变化 = 新 md5 = 新版本。自洽。

**两个 md5 口径**（2026-04-22 per-mode md5 上线后）：
- **整机 md5**（`configSummaryMd5`）：spec + 所有 mode weights 的聚合指纹；受任何 mode 调参影响
- **per-mode md5**（`modesMd5[<n>].configSummaryMd5`）：spec + 单个 mode 的 weights；调 mode 2 不会 invalidate mode 1 的历史

归档路径以 **per-mode md5** 的前 8 位命名 —— 同 mode 历次版本之间可以稳定对应，不会因为另一 mode 调参而"错位"。整机 md5 在 NOTES.md 里记录一下供 UI 索引对齐。

## 当前 active

每台机台的活动版本由 `slot_designer/weights/<machine>_mode<N>.tuned.json` 指定（虚拟 console 实际读这个）。deliverables/ 下是**归档**（history + current 的完整文件备份）。

切换 active（release 路径）：
```bash
# 1. 把归档版本 promote 成 active
cp slot_designer/deliverables/M1/558dfcdd/reel_weights.json \
   slot_designer/weights/M1_mode1.tuned.json

# 2. 下一次虚拟 console 启动（或 refresh-md5）会自动把新 md5 刷进
#    machines_virtual.json —— UI 显示机台 md5 drift

# 3. Operator 在虚拟 console 里按"开始采样" → virtual_analyzer 按新 md5
#    产 chunk 到 slot_designer/rawdata/<machine>sim/mode_<N>/
#    （旧 md5 的 chunks 自动标 historical，不会和新 chunks 混分析）
```

**Dev scratch vs console rawdata**：`simulate.py` / `tune.py --emit-chunks`
跑完把 chunk 写到 `slot_designer/_dev_scratch/rawdata/...`（ephemeral，
每次跑自动 wipe 同目录下 chunk_*.json）。console 的 rawdata 池
（`slot_designer/rawdata/`）**只由 console 自己的 batch-run 写入**，
dev 脚本从不碰它。这样 tune / re-sim 时不会意外覆盖 console 的数据。

## 每目录内容

```
<md5_short>/
├── reel_weights.tsv       原始 TSV schema（和你给的输入同格式）
├── reel_weights.json      引擎 / 虚拟 console 直接读
├── NOTES.md               本版本的数值 + 调参决策 + 和上一版对比
└── TUNE_REPORT.md         tune.py 自动生成的 Phase 4 / 5 详细 breakdown
                           （只有经 tune.py 产出的版本有，手工配置的版本没有）
```

## M1 版本索引

| md5_short | 口径 | RTP | hit_rate | CV | 简述 |
|---|---|---|---|---|---|
| `32251c25` | 整机 | 93.49% | 24.57% | 5.28 | 第一版（mode 1），只对齐 M14 mode 1 的 shape + CV，hit 未约束 → "所有 slots 平均 20-25%" 档（偏 video slot 风格） |
| `558dfcdd` | 整机 / mode 1 per-mode | 93.48% | **15.29%** | 5.06 | **mode 1 active**，加 hit_rate 软约束 15% → classic 单线行业 typical |
| `6edf1ca3` | 整机（旧） | **306%** | 27.30% | 6.04 | mode 2 **v1**（2026-04-22 初调）。tail-heavy：63% 的 RTP 贡献在 50-500× 高倍率桶，user 反馈波动性过大 |
| `e4017d61` | mode 2 per-mode | **290.9%** | **27.78%** | **4.08** | **mode 2 active**（2026-04-22 v2 重调，RTP 贡献中心下移）。mid 桶 (10-50×) RTP 占比 22.5% → **41.3%**，high 桶 (50-500×) 57.1% → **32.4%**；CV 6.04 → 4.08（-33%）。对应整机 md5 `5738a990` |

## 新机台交付时

复制这个模板：
```bash
mkdir -p slot_designer/deliverables/<MACHINE>
# 调参产出
python -m slot_designer.scripts.tune ... \
  --out-weights /tmp/<machine>_tuned.json ...

# 计算 md5_short
python -c "
import hashlib, sys
spec = open('slot_designer/specs/<MACHINE>.spec.json','rb').read()
h = hashlib.md5(); h.update(spec); h.update(b'\x00')
h.update(open('/tmp/<machine>_tuned.json','rb').read())
print(h.hexdigest()[:8])
"

# 落盘归档 + promote 成 active
MD5=<从上面 print 出来的短 md5>
mkdir -p slot_designer/deliverables/<MACHINE>/$MD5
cp /tmp/<machine>_tuned.json slot_designer/deliverables/<MACHINE>/$MD5/reel_weights.json
# 生成 TSV + NOTES
# ...
cp /tmp/<machine>_tuned.json slot_designer/weights/<MACHINE>_mode<N>.tuned.json
```

（未来可以让 tune.py 自动做这一整套 —— 当前还是半手工）

## 研究依据（每次调参 fresh 重搜）

按 `feedback_always_research_each_time` 规则，memory 里的笔记只当 keyword seed，每个调参 session 都重搜英文行业源。各版本的 NOTES.md 里记录当次 session 的 search URLs。
