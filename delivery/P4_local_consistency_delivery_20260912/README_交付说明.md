# P4 局部预测/执行一致性修复 · 交付包

## 一句话

按指出的四处缺陷定向修复 P4 冻结组件的局部预测一致性（预测复用真实观测更新、删除假想真值捷径、
取消 50 步截断并保证全存活单元覆盖、补齐 `prune_by_near`）；最小验收 **20/20 通过**，
在完全相同的决策状态上对拍证明**评分修复确实改变了动作**（S3：measure → clear）；
随后以 58037a3（2-opt 关闭）为对照跑完三例，**平均 Saved_T = +8.96 s（1 胜 2 负）**，结果原样保留。

## 关键标识

| 项 | 值 |
|---|---|
| 对照基线 | `58037a3`（P4 2-opt 关闭的既有三例：7040.56 / 7840.02 / 8147.65 s） |
| 本轮分支 | `fix/p4-local-scoring-consistency` |
| 修复提交 | `53b664d` |
| 证据提交 | `e647c54` |
| 两臂 2-opt | 均 `enable_2opt_head=False`（未重新开启 2-opt） |
| 改动文件 | `conservative_grid_frozen.py`、`local_decision_frozen.py`、`src/strategy_engine.py` |
| 未改动 | P3、P4 覆盖点集、扫描规则、全局调度、现有参数、`src/conservative_grid.py`、`src/local_decision.py` |

## 目录结构

```
P4_local_consistency_delivery_20260912/
├── README_交付说明.md
├── CONCLUSION_本轮结论.md
├── MANIFEST_文件清单.csv
├── 01_fix_diff/
│   ├── source_diff_vs_58037a3.patch      完整源码差异（无省略号）
│   ├── source_diff_stat.txt
│   └── full_source/                      改动后三个文件全文
├── 02_minimal_acceptance/
│   ├── minimal_acceptance.json           20 项检查明细
│   ├── minimal_acceptance.log            运行 stdout
│   └── verify_p4_local_consistency.py    最小验收脚本
├── 03_scoring_event_ab/
│   ├── scoring_event_ab.json             同一决策状态的新旧评分对拍
│   ├── compare_p4_scoring_event.py       对拍脚本
│   └── old_modules_58037a3/              58037a3 的旧模块副本（对拍用，隔离加载）
├── 04_paired_run/
│   ├── p4_local_consistency_paired.csv/.json   三例配对与成本对比
│   ├── local_scoring_fixed/acceptance.csv/.json + action_logs/   新版三例原始动作日志
│   └── baseline_58037a3/acceptance.csv/.json                     对照臂原始记录
└── 05_reference/
    ├── P4_BASELINE_ID.json               上一轮新 P4 基线标识（可追溯）
    └── p4_fix_paired_baseline.csv        58037a3 原始配对记录
```

## 复现方式

```bash
# 1) 四处缺陷最小验收（20 项）
python scripts/verify_p4_local_consistency.py

# 2) 同一决策状态上的新旧评分对拍（旧模块从 58037a3 隔离加载）
python scripts/compare_p4_scoring_event.py

# 3) 三例运行（2-opt 关闭，局部评分修正版）
python scripts/verify_p4_fix_acceptance.py --arm fixed_baseline \
       --outdir results/p4_local_consistency/paired_run/local_scoring_fixed

# 4) 与 58037a3 基线配对（基线记录从分支 exp/p4-head-2opt-after-fix 读取）
python scripts/build_p4_local_consistency_paired.py
```

## 硬性要求逐条对应

| 要求 | 落实 |
|---|---|
| 预测必须克隆真实网格并复用实际观测更新函数，删除重复手写角域判据 | `grid.clone()` + `prune_by_direction`；手写 `n_cw/n_ccw` 谓词已删除 |
| 预测不得修改原网格 | 调用前后 `alive` 逐元素一致（D1 检查通过） |
| 零概率分支不参与评估 | `if p_recv > 0.0` / `if p_nosig > 0.0` 门控；0 次裁剪 vs 对照组 10 次 |
| 删除 `plan_dir=[sc]` 与未命中后走向 sc 的补偿 | 源码检查 + `_plan_cost_from` 与解析值精确对拍 |
| sc 只能生成假想反馈、判断是否命中 | `sc` 仅出现在反馈判定与命中判定中 |
| J0/J(q) 按算法实际可生成的计划累计成本 | 两者都用 `build_clear_plan` 生成的计划 |
| 不用 300s / 1e9 人为惩罚 | 评分路径已无 1e9；不可表示返回 `(costs=[], ok=False)` 并显式排除候选 |
| 取消 50 步截断、检查全部存活单元 | `for _ in range(len(valid_centers))` + 全单元补齐覆盖；`verify_full_coverage` 逐单元校验 |
| 样本覆盖不能代替全部单元覆盖 | 补齐循环以 `cells`（全部存活单元）判定，不以抽样 `sample_cells` 判定 |
| 预测与执行使用同一个计划生成器 | 两侧都调用 `grid.build_clear_plan` |
| 补齐 prune_by_near 且不套用 no_signal 规则 | 5 m 邻域语义；与 `prune_by_no_signal_omni` 行为不同（37 vs 10941） |
| 保留空集/矛盾处理，不靠忽略异常或删除目标通过 | 空集/矛盾分支未改动；无网格 FOUND 显式判 FAILED；验收中任何异常都会 FAIL |
| 结果无论改善或退步都保留 | 平均 +8.96 s，1 胜 2 负，逐例数值原样保留 |
| 不调阈值、不换种子、不叠加新策略、三例后停止 | 未改任何阈值/种子；仅修四处缺陷；三例后停止 |
