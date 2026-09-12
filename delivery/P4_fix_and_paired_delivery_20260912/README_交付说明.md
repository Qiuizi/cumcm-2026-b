# P4 基线正确性修复 + 2-opt 配对实验 · 交付包

## 一句话

定位并修复了 P4 冻结网格的角域判据写反缺陷（外加"空集被当作安全清除依据"与无限重试），
建立新 P4 基线 `P4-BASELINE-v3.5.0-fix`（三局完整验收 3/3 通过，P3 逐字段不变），
随后在**同一修复版本**上完成已预注册的 2-opt 配对实验：**开启首任务 2-opt 三局一致变慢，平均 -1894.66 s**。

## 关键标识

| 项 | 值 |
|---|---|
| 主线（P3 已合入） | `master` = `3a74912`（未改动） |
| 修复分支 | `fix/p4-baseline-correctness` |
| 修复提交 | `fb2de99`、`75f2f16`、`4557ad5`（证据提交 `949b60b`） |
| **新 P4 基线标识** | **`P4-BASELINE-v3.5.0-fix`**（git tag） |
| 实验分支（恢复实验） | `exp/p4-head-2opt-after-fix`，两臂同一 commit `58037a3` |
| 旧文件 / 旧失败日志 | 全部保留，未删除、未改写 |

## 目录结构

```
P4_fix_and_paired_delivery_20260912/
├── README_交付说明.md
├── CONCLUSION_本轮结论.md                     根因 / 修复 / 验收 / 配对结果 / 更正 / 边界
├── MANIFEST_文件清单.csv                       包内文件 sha256（不含自身）
├── 01_root_cause/                              最小复现与根因证据
│   ├── minimal_repro_before.json               修复前：(999,0)->36.96°, (1840,0)->140.06° 场景 4193 -> 0
│   ├── minimal_repro_after_grid_fix.json       网格修复后
│   ├── minimal_repro_after_fix.json            完整修复后
│   └── diagnose_p4_grid_contradiction.py       最小复现脚本（记录 __file__ / 哈希 / 错误语句 / 四类假设）
├── 02_fix/                                     修复
│   ├── source_diff_vs_master.patch             完整源码差异（无省略号）
│   ├── source_diff_stat.txt
│   ├── full_source/                            改动后三个文件全文
│   │   ├── conservative_grid_frozen.py
│   │   ├── local_decision_frozen.py
│   │   └── src_strategy_engine.py
│   └── P4_BASELINE_ID.json                     新 P4 基线标识
├── 03_verification/                            验收
│   ├── fixed_baseline_acceptance.csv/.json     修复后基线三局完整验收（3/3 PASS）
│   ├── grid_semantics_equivalence.json         冻结网格 vs 共享网格 900/900 逐单元一致
│   ├── p3_unchanged_after_p4_fix.json          P3 与合入后记录逐字段一致
│   └── scripts/                                验收与诊断脚本
├── 04_paired_run/                              修复后 2-opt 配对实验（两臂同一 commit）
│   ├── p4_head_2opt_paired_after_fix.csv/.json 配对结果与成本分解
│   ├── fixed_baseline/acceptance.csv + action_logs/    2-opt 关闭（3 局原始动作日志）
│   └── head_2opt_candidate/acceptance.csv + action_logs/ 2-opt 开启（3 局原始动作日志）
└── 05_previous_round_corrected/                上一轮失败运行更正
    ├── p4_head_2opt_paired_corrected.csv       Saved_T_s -> N/A（原值移入 Saved_T_s_original）
    ├── ORIGINAL_p4_head_2opt_paired.csv        原始文件原样保留
    ├── README_更正说明.md
    └── action_logs/                            上一轮 6 局原始动作日志（各 1500 条，未修改）
```

## 复现方式

```bash
# 1) 最小复现（修复前后对比）
python scripts/diagnose_p4_grid_contradiction.py before      # 需在未修复版本上运行
python scripts/diagnose_p4_grid_contradiction.py after_fix

# 2) 修复后基线验收（三局，2-opt 关闭）
python scripts/verify_p4_fix_acceptance.py --arm fixed_baseline

# 3) 语义等价性与 P3 不变性
python scripts/verify_p4_grid_semantics_equivalence.py
python scripts/verify_p3_unchanged_after_p4_fix.py

# 4) 配对实验两臂（同一 commit）
python scripts/verify_p4_fix_acceptance.py --arm fixed_baseline      --outdir results/p4_fix/paired_run/fixed_baseline
python scripts/verify_p4_fix_acceptance.py --arm head_2opt_candidate --outdir results/p4_fix/paired_run/head_2opt_candidate
python scripts/build_p4_paired_after_fix.py
```

## 硬性保证（本轮要求逐条对应）

| 要求 | 落实 |
|---|---|
| 预测不修改真实状态 | 冻结决策器的预测用 `surviving[mask]` 局部数组；核验 H2 未命中 |
| 合法观测更新保留真实位置所在单元 | 角域判据修正后，最小复现中真值单元保留（距真值 0.335 m） |
| 空集不能作为安全清除依据 | `check_safe_clear_at`→False、`find_safe_clear_position`→None、`build_clear_plan`→[] |
| 模型矛盾不得处理成"不存在/已清除" | 会清空存活集的观测被拒绝并留痕；决策器返回 `fail`；引擎标记 `FAILED`（≠ABSENT≠CLEARED） |
| 同位置同频道清除失败且状态不变不再重复 | 连续 3 次同点同状态熔断，标记 `FAILED` |
| 异常恢复使用已有观测与有效状态 | 失败目标只停该目标，其余调度按既有有效状态继续 |
| 无法恢复时明确标记失败并经合法路径结束 | `failed_targets` + `completion_status=INCOMPLETE`，仍走 `driver.exit()`，不伪造完成 |
| 补齐现实与虚拟预算检查 | `max_virtual_duration_s` / `max_real_duration_s` 取自模拟器 `/enter`，耗尽记为 `SAFE_EXIT_BUDGET` |
| 区分安全退出与成功完成 | `completion_status ∈ {COMPLETED, SAFE_EXIT_BUDGET, INCOMPLETE}` |
| 修复独立提交 + 新基线标识 + 保留旧文件与失败日志 | 三个修复提交 + tag `P4-BASELINE-v3.5.0-fix`；旧文件与旧日志原样保留 |
| 收益只比同一修复版本两臂 | 两臂同一 commit `58037a3`；`deadlock_fix_counted_as_2opt_gain=false` |
| 未完成局 Saved_T_s 写 N/A | 上一轮 6 局已更正为 N/A；本轮 6 局全部完成，均可比 |
| 不扩大种子 / 不追加策略 / 不调用官方模拟器 | 仅预注册的三场景 × 两臂；全部本地替代驱动 |
