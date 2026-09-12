# P3 合入 + P4 首任务 2-opt 实验 · 交付包

## 一、本轮做了什么

### 1. P3 径向候选合入主线（已完成）

| 项 | 值 |
|---|---|
| 主线分支 | `master` |
| P3 功能提交 | `7a51d32` feat(p3): wire --profile radial switch into launch entry and add delivery audit tooling |
| **合入（合并）提交** | **`3a7491206c16acaa8c363b483679d9ab2a09da2f`（`3a74912`）** |
| 合入方式 | `git merge --no-ff feature/p3-adaptive-radial-coverage`（保留完整分支历史） |
| 合入前主线 | `160d265` baseline: v3.4.2-guard-upperbound |

合入后的默认行为：

- 默认档位仍为 `stable`，**径向开关默认关闭**；
- `radial_candidate` 必须通过 `--profile radial_candidate` 显式选择；
- **这是"代码合入主线"，不代表径向策略已成为默认配置。**

合入后做了入口与配置回归（未重跑九组性能测试），见 `01_p3_merge/`：
档位矩阵 14/14 PASS；三档入口实跑（`stable` / `radial_candidate` / 不带 `--profile` 的默认档）
逐一验证生效配置、清除数、未决数、排除证明类型与计费残差。

### 2. P4 独立实验分支（已建立，唯一变量已就绪）

| 项 | 值 |
|---|---|
| 实验分支 | `feature/p4-head-2opt-experiment` |
| 分支点 | `master` @ `3a74912` |
| 实验提交 | `cf48fbc`（唯一变量）\u3001`24585d1`（试验与诊断） |
| **唯一实验变量** | 允许 P4 开放路线的 2-opt 改变**最终实际派发的首任务**（`enable_2opt_head` False → True） |
| 默认 | 仍为 `False`（默认继续关闭） |

生效链：`run_port_test.py --enable_2opt_head` → `StrategyEngine(enable_2opt_head=...)` →
`self.enable_2opt_head`（**P4 强制覆盖已解除**）→ `start_i = -1 if self.enable_2opt_head else 0` →
`path[0]` 派发 → `head_dispatch_records` 逐轮审计。链路验收 14/14 PASS。

保持不变：P4 覆盖点集（25 点）、冻结定位与清除组件、扫描规则、完成判据、
清除点额外扫描（P4 仍强制关闭）、P3 径向选点（未迁移到 P4）。
源码差异中 `local_decision_frozen.py`/`conservative_grid_frozen.py`/`src/local_decision.py`/
`src/conservative_grid.py`/`src/sim_env.py` 与 `master` **逐字节相同**。

### 3. 三组配对试验（已执行，但**无法给出收益结论**）

预注册三场景：10/13/16 源，seed 7210/7213/7216，`dir_ratio=0.5`，本地替代驱动，有界运行（动作上限 1500），
**未调用官方模拟器**。

结果：**6/6 局非终止，0 个目标被清除，20 个频道全部未决，0 局通过完整验收。**

| 案例 | 源数(全向/定向) | 基线 | 候选 | 基线清除 | 候选清除 | 基线首任务改变 | 候选首任务改变 |
|---|---|---|---|---|---|---|---|
| P4H-10src-7210 | 10 (1/9) | RUNAWAY | RUNAWAY | 0/10 | 0/10 | 0 | 1 |
| P4H-13src-7213 | 13 (6/7) | RUNAWAY | RUNAWAY | 0/13 | 0/13 | 0 | 1 |
| P4H-16src-7216 | 16 (7/9) | RUNAWAY | RUNAWAY | 0/16 | 0/16 | 0 | 1 |

- 由于不满足"完整清除 + 结束证据成立"的前提，**本轮不给任何配对收益数值**，
  也不以预计路径缩短代替实际节省，不凭三例宣称收益。
- 但机制本身确实生效：**候选臂每一局都真实改变了 1 次派发首任务**（来自 `head_dispatch_records`
  中 `pre_head != final_head` 的轮次，**不是** 2-opt 内部交换次数 `total_2opt_swaps`）。

---

## 二、阻塞根因（与本实验变量、与 P3 合入均无关）

诊断证据见 `02_p4_experiment/diagnosis/`：

1. **既有 P4 成功记录不可复现**：`results/p4_benchmark_results.csv`、
   `results/p4_heldout_benchmark_results.csv` 中标注完整清除的场景
   （seed 5000/5001/5002/9101/9102），在当前 P4 代码路径下**全部非终止**。
2. **归属明确**：同一场景、同一参数下，根目录**冻结组件**非终止，
   而**共享 `src/` 组件**可正常终止并完整清除：
   - seed 5000: frozen RUNAWAY 清除 0/10 ↔ shared NORMAL 清除 10/10, T=6285.64s
   - seed 9101: frozen RUNAWAY 清除 0/10 ↔ shared NORMAL 清除 10/10, T=7039.07s
   - seed 5001: frozen RUNAWAY 清除 0/13 ↔ shared NORMAL 清除 13/13, T=8674.07s
3. **直接机制**：某 FOUND 目标经一次补测后保守网格存活单元归零，
   冻结决策器仍返回 `reason='safe_clear_guaranteed'` 且位置固定的清除动作，清除持续失败；
   `service_found_target` 的 `while st.status == 'FOUND'` 循环无法退出；
   引擎对 `max_virtual_duration_s` / `max_real_duration_s` 没有任何强制终止，虚拟时间无界增长。
4. 该缺陷在合入前的主线基线 `160d265` 上**同样存在**，**不是 P3 合入引入的**。

---

## 三、目录结构

```
P3P4_delivery_20260912/
├── README_交付说明.md              本文件
├── CONCLUSION_本轮结论.md          简短结论
├── LAUNCH_COMMANDS.md              P3 两档位 + P4 实验 启动命令
├── MANIFEST_文件清单.csv            包内文件 sha256 + 字节数（不含自身）
├── 01_p3_merge/
│   ├── master_commit.txt           master 提交号
│   ├── git_graph.txt               分支历史图（保留历史版本）
│   ├── profile_matrix.log/.json    档位矩阵回归（14/14 PASS）
│   ├── entry_stable.log/.json      稳定档入口实跑
│   ├── entry_radial_candidate.log/.json  径向候选档入口实跑
│   └── entry_default.log/.json     默认档（不带 --profile）入口实跑
├── 02_p4_experiment/
│   ├── source_diff_vs_master.patch 完整源码差异（无省略号）
│   ├── source_diff_stat.txt        差异统计
│   ├── full_source/src/strategy_engine.py   改动后源码全文
│   ├── p4_head_2opt_chain.json/.log         入口→引擎生效链验收
│   ├── p4_head_2opt_paired.csv              三组配对 CSV
│   ├── p4_head_2opt_audit.json              逐局审计（生效配置/计费/逐频道结束状态/首任务记录）
│   ├── p4_head_2opt_run.log                 配对试验原始输出
│   ├── P4_EXPERIMENT_CONCLUSION.md          实验结论
│   ├── action_logs/*.jsonl                  6 局原始动作日志（每局 1500 条）
│   ├── diagnosis/                           非终止诊断证据
│   └── scripts/                             4 个新增脚本
└── ```

---

## 四、复现方式

```bash
# P3 合入后的入口/配置回归（无性能测试）
python scripts/verify_launch_profiles.py

# P4 首任务 2-opt 生效链验收（无通信）
python scripts/verify_p4_head_2opt_chain.py

# P4 三组配对试验（有界运行，不连官方模拟器）
python scripts/verify_p4_head_2opt_rigorous.py

# P4 非终止根因诊断
python scripts/diagnose_p4_nontermination.py

# 生成简短结论
python scripts/summarize_p4_head_2opt.py
```

---

## 五、本轮未做（刻意不做）

- 未修复 P4 冻结组件的非终止缺陷——那会引入第二个变量，破坏单变量实验设计；
- 未修改 P4 覆盖点集、扫描规则、完成判据、清除点额外扫描开关；
- 未把 P3 径向选点迁移到 P4；
- 未追参、未追加惩罚项、未针对个别种子做特例；
- 未调用官方模拟器；
- 未把"代码合入"表述为"径向策略已成为默认"。
