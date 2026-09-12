# 第三阶段：P4 历史接收模型候选版（可运行 + 独立验证）

> 本轮目标：把阶段 2 的历史接收模型做成**可运行的候选版本**，并在**未参与开发**的场景上做一次有限独立验证。
> 停止新增机制与调参。
> **最终判断：值得保留候选。**

---

## 0. 结论

| 项 | 结果 |
|---|---|
| 候选是否可运行 | 是。`launch.py` 支持 `stable` / `history_candidate`，默认 `stable`，运行期不读取也不 exec 外部源码 |
| 与阶段2 实验 C 是否一致 | **完全一致**：既有案例 seed 8801:10 的 T/L/M/S/F/N 逐项相同，333 个 driver 级动作**逐动作相同**，T 均为 6365.498 s |
| 独立验证（6 个全新场景 × A/C 配对） | **全部 12 局通过完整清除与计费闭合验收** |
| 总虚拟时间 | 平均节省 **+394.78 s**，中位节省 **+365.47 s**，**4胜 0平 2负**，最大退步 **+51.09 s**（对照最大节省 +1206.76 s） |
| 判断 | **值得保留候选**（不自动切换默认版本） |

---

## 1. 冻结声明

见 `FREEZE.json`。本轮起冻结、不得再调：

| 冻结项 | 值 |
|---|---|
| 假设（粒子）数量 | `n_hyp = 512` |
| 源类型先验 | `p_dir = 0.5`（**建模假设，非题面事实**） |
| 接收半径先验 | `R ~ U[1000, 1500]`（**建模假设**） |
| 朝向先验 | `u ~ U[0, 2π)`（**建模假设**） |
| 测向容差 | 继承安全网格自身的 `eps_deg`（保持与网格自洽） |
| 条件化抽样 | `pool_factor = 40`，`max_rounds = 6` |
| 抽样种子 | `seed = 20260912 + 131 × channel`（同一目标 R/u 固定且可复现） |
| 更新规则 | 用**全部历史观测**重新过滤相容假设（阳性+阴性联合解释），只做剔除，绝不重抽 R/u |
| 回退规则 | 假设集为空 ⇒ `reception_probability` 返回 `None` ⇒ 决策器逐字回退 `frozen_recv_prob`，记录原因与次数 |

`stage3/model.py` 与阶段2 的 `reception_model.py` **逐字节一致**（sha256 `ada6c0069ee9b426…`），
即冻结的是同一份模型实现。

---

## 2. 可运行候选与启动入口

### 2.1 文件

| 文件 | 作用 |
|---|---|
| `predictor.py` | 显式接收预测接口（`prepare_for_decision` / `reception_probability`）与冻结实现 |
| `model.py` | 冻结的假设集模型实现（与阶段2 逐字节一致） |
| `candidate_decision.py` | 候选决策器。**构建期**由 `tools/build_candidate_method.py` 从冻结源码一次性生成；运行期是普通 Python 模块 |
| `observer.py` | 只记录不干预的驱动包装 + 网格计数取证 |
| `launch.py` | 启动入口（stable / history_candidate，默认 stable） |

### 2.2 启动命令

```powershell
# 默认（稳定基线）
python experiments/stage3_candidate/launch.py --version stable --case 9001:10

# 历史接收模型候选版
python experiments/stage3_candidate/launch.py --version history_candidate --case 9001:10 \
    --json experiments/stage3_candidate/results/launch_smoke_history.json
```

### 2.3 启动入口打印内容（实测摘录，`history_candidate`）

```
模块来源与源码标识：
  env_sim                 ffa4f33aa5f943de  D:\...\src\sim_env.py
  strategy_engine         8dca0841ba7c45de  D:\...\src\strategy_engine.py
  evidence_tracker        4a627a8bb8a236a1  D:\...\src\evidence_tracker.py
  decision_maker_frozen   6d26e61de9a25fd4  D:\...\local_decision_frozen.py
  grid_frozen             778af8fd986a79b6  D:\...\conservative_grid_frozen.py
  candidate_decision      811ed39875813301  D:\...\stage3_candidate\candidate_decision.py
  candidate_predictor     0fa1753454775cbd  D:\...\stage3_candidate\predictor.py
  candidate_model         ada6c0069ee9b426  D:\...\stage3_candidate\model.py

实际生效配置：
  is_p4                            = True
  engine_version_tag               = C
  scan_at_clearance                = False
  enable_2opt_head                 = False
  enable_adaptive_radial_coverage  = False
  enable_pruning                   = True
  decision_maker                   = candidate_decision.HistoryCandidateDecision
  grid_class                       = conservative_grid_frozen.ConservativeGrid
  evidence_tracker                 = src.evidence_tracker.EvidenceTrackerP4
  decision_maker_limits            = {'max_followups': 12, 'max_followup_time_s': 600.0, 'margin_s': 5.0}
  predictor                        = HistoryReceptionPredictor @ ...\predictor.py
    frozen_prior                   = {'n_hyp': 512, 'p_dir': 0.5, 'r_range': [1000.0, 1500.0],
                                      'u_prior': 'uniform[0,2pi)', 'eps_deg': 'inherit_from_grid',
                                      'pool_factor': 40, 'max_rounds': 6,
                                      'seed_base': 20260912, 'seed_stride': 131}
    update_rule                    = refilter_all_compatible_hypotheses_with_full_history
    fallback_rule                  = empty_hypothesis_set -> return None -> frozen_recv_prob
```

### 2.4 必要源码差异

候选版与稳定基线的差异只有一处（确定性生成，可机检）：
`local_decision_frozen.decide_action` 中"接收概率"切片被替换为
`self._reception_probability(...)`，其余（含全部注释与空行）逐字保留。

覆盖形式：生成主体 `_decide_with_history` + 手写诊断包装 `decide_action`。
包装只做**只读**的基线对照，不改变任何决策输入。

---

## 3. 验证 1：与阶段2 实验 C 一致（既有案例）

| 检查 | 结果 |
|---|---|
| 源码局部性 | 一致（删掉接收概率切片后 **277 行 vs 277 行**逐行相同） |
| 运行期是否使用 `inspect`/`exec` | **否** |
| 既有案例 `P4-10src-seed8801` 数值 | T / L / M / S / F / N / 清除 / 空频道 / 完成状态 **9 项全部一致** |
| driver 级动作序列 | **333 个动作逐动作完全一致**，T 均为 **6365.498 s** |
| 总体 | **PASS** |

> 该比对同时证明：后加入的诊断包装对决策**无影响**（有无包装 T 与动作序列完全相同）。

---

## 4. 验证 2：六个全新场景 × A/C 配对（12 局）

### 4.1 预注册

在运行前固定，运行中不调参、不换种子：

| 组 | 场景 |
|---|---|
| 10 源 | seed **9501**, seed **9502** |
| 13 源 | seed **9513**, seed **9514** |
| 16 源 | seed **9521**, seed **9522** |

（以上 seed 在本项目此前任何一轮都未使用过。）
环境与内部采样随机规则固定：`SimEnvironment.generate_random_case(..., is_p4=True, seed=s)`、
`dir_ratio=0.5`、误差按 `(位置, 频道)` 哈希确定；预测器先验抽样
`default_rng(20260912 + 131 × channel)`。

### 4.2 验收 1：完整清除与计费闭合

**12 局全部 PASS**：`completed = True`，`cleared == n_src`（10/13/16 全清），未决 0，失败 0，
计费闭合 `T = L/5 + 5M + S + 3F + 5N` 残差 ≤ 1e-6 s。逐频道结束证据见 `validation_12runs.json`。

### 4.3 验收 2：总虚拟时间

| 案例 | A (stable) | C (candidate) | ΔT = C−A | L: A→C | M: A→C | F: A→C |
|---|---|---|---|---|---|---|
| P4-10src-seed9501 | 8 661.10 | **7 454.34** | **−1 206.76** | 30 840→26 852 | 349→329 | 130→27 |
| P4-10src-seed9502 | **7 951.18** | 8 002.27 | **+51.09** | 27 766→28 246 | 347→326 | 102→122 |
| P4-13src-seed9513 | 7 380.00 | **6 909.45** | **−470.55** | 28 485→27 202 | 241→233 | 71→13 |
| P4-13src-seed9514 | 7 429.73 | **6 933.27** | **−496.46** | 29 029→27 156 | 257→235 | 20→16 |
| P4-16src-seed9521 | **6 294.64** | 6 309.02 | **+14.38** | 23 633→24 040 | 236→216 | 37→48 |
| P4-16src-seed9522 | 4 795.08 | **4 534.69** | **−260.39** | 19 490→18 909 | 122→101 | 40→27 |

| 统计量 | 值 |
|---|---|
| 平均节省 | **+394.78 s** |
| 中位节省 | **+365.47 s** |
| 最大退步 | **+51.09 s** |
| 最大节省 | +1 206.76 s |
| 胜 / 平 / 负 | **4 / 0 / 2** |

### 4.4 最大退步案例的成本来源

`P4-10src-seed9502`，ΔT = **+51.09 s**，按计费公式逐项分解：

| 成本项 | Δ = C − A |
|---|---|
| 移动 `ΔL/5` | +96.07 s |
| 检测 `5·ΔM` | −105.00 s |
| 切频 `ΔS` | 0.00 s |
| 失败清除 `3·ΔF` | +60.00 s |
| **合计** | **+51.07 s**（与 ΔT 差 0.02 s，舍入） |

即：这一局候选版**少测了 21 次**（省 105 s），但**多走了 480 m**（+96 s）且**多失败 20 次清除**（+60 s），
净亏 51 s。退步来自"换了补测点之后路径与清除序列的连锁改变"，而非机制失效。

### 4.5 模型使用与回退

| 项 | 12 局合计 |
|---|---|
| 调用过模型的决策数 | **184**（其中模型可用 **174**，整体回退 **10**，占 5.4%） |
| 逐次打分调用回退 | **1446**（集中在 2 局） |
| 实际改变动作类型 | **5 次** |
| 实际改变补测点 | **75 次** |

逐局：

| 案例 | 用模型决策 | 整体回退 | 逐调用回退 | 改变动作 | 改变补测点 |
|---|---|---|---|---|---|
| 9501 (10源) | 26 | 0 | 0 | 0 | 11 |
| 9502 (10源) | 20 | 0 | 0 | 2 | 4 |
| 9513 (13源) | 29 | **9** | **1337** | 0 | 14 |
| 9514 (13源) | 28 | 0 | 0 | 0 | 12 |
| 9521 (16源) | 32 | 0 | 0 | 2 | 16 |
| 9522 (16源) | 39 | 1 | 109 | 1 | 18 |

回退原因（逐局记录在 `validation_12runs.csv` 的 `fallback_reason_hist` 列）：

- 9513：`all_hypotheses_incompatible_after_5_observations`（1000 次调用）、
  `..._after_7_observations`（148 次）等，共 9 个决策整体回退；
- 9522：`all_hypotheses_incompatible_after_12_observations`（109 次调用），1 个决策整体回退。

**回退行为符合冻结契约**：假设集耗尽 ⇒ `reception_probability` 返回 `None`
⇒ 决策器**逐字回退** `frozen_recv_prob`（与稳定基线完全一致），并记录原因与次数；
不删除安全网格、不丢源、不改判空与结束判据。9513 一局在有 9 次整体回退的情况下仍节省 470.55 s，
说明收益来自模型可用的那 29 个决策。

> 说明：本轮逐局记录只保留**计数**（`model_decisions_used` / `model_decision_fallbacks` /
  `model_call_fallbacks` / 动作改变计数），未持久化每次决策的明细，
> 因此不生成"关键决策明细 CSV"；逐局计数见 `validation_fallbacks.csv`。

---

## 5. 第 4 点：三件事的精确区分，并核对上一报告的「289/233/160」

### 5.1 三个量的定义（本阶段新增独立取证）

`observer.py` 在每次驱动调用开始时快照各频道安全网格的存活单元数，
因此可以精确区分：

| 量 | 定义 |
|---|---|
| ① `no_signal_total` | 全部 no_signal 测量次数 |
| ② `no_signal_followup` | 该频道**已发现之后**发生的 no_signal 次数（即"补测盲测"） |
| ③ `no_signal_grid_not_shrunk` | 其中"测后网格存活单元数**未减少**"的次数 |
| ④ `no_signal_grid_shrunk` | 其中"测后网格存活单元数减少"的次数 |

### 5.2 上一报告的「289/233/160」实际含义（已核对）

从阶段2 逐局 CSV 直接核对：

| 案例 | A total / followup | B total / followup | C total / followup | A→C 总次数减少 | A→C 补测减少 |
|---|---|---|---|---|---|
| 8801 (10源) | 311 / 25 | 289 / 3 | **289 / 3** | **22** | **22** |
| 8813 (13源) | 275 / 48 | 233 / 6 | **233 / 6** | **42** | **42** |
| 8816 (16源) | 206 / 52 | 160 / 6 | **160 / 6** | **46** | **46** |

**核对结论（并更正上一报告的表述）**：

- 「289/233/160」是 **no_signal 总次数**（①），**不是"消除的盲测次数"**。
  它的绝大部分（每局 200~300 次）是搜索阶段对**空频道**的静默扫描，与机制无关。
- 真正被消除的**补测盲测**是 **22 / 42 / 46** 次（A→C），
  且恰好等于总次数的减少量（两者逐局相等）。
- 上一报告的表述「B 与 C 消除的盲测次数完全相同（289/233/160）」把**总量**当成了**消除量**，
  属标注错误；正确表述应为：**B 与 C 的 no_signal 总次数相同（289/233/160），
  相对基线的消除量为 22/42/46**。
- 本阶段实测进一步确认 P4 语义：`no_signal_grid_shrunk = 0`
  （P4 下 no_signal 从不裁剪网格），因此 ③ 与 ② 在 P4 上重合。

---

## 6. 约束遵守

| 约束 | 状态 |
|---|---|
| 冻结先验/假设数量/更新规则/回退规则 | 已冻结并写入 `FREEZE.json` |
| 只比较 A（stable）与 C（history_candidate） | 是。k=1 仅作历史对照，本轮未再迭代 |
| 正式候选不依赖"截取源码后 exec" | 是。构建期一次性 codegen，运行期普通模块；机检确认无 `inspect`/`exec` |
| 启动入口支持 stable/history_candidate，默认 stable | 是。实测两种版本均可运行并打印配置/模块/源码标识 |
| P3、覆盖布局、扫描规则、全局调度、候选点、清除计划、结束判据不变 | 是。只替换 `eng.local_decision` 一个对象 |
| 概率模型只影响决策；耗尽走安全回退 | 是。回退逐字执行冻结公式并记录原因 |
| 不调用官方模拟器、不另建模拟器 | 是。只用本地参考环境 `src/sim_env.py` |
| 未完整完成的局不计入省时 | 本轮 12 局全部完整完成，无此情形 |

---

## 7. 限制（必须与结论一起读）

1. **样本量 6 对配对**。这是本轮预注册的上限，不足以给出尾部风险上界或置信区间；
   平均 +394.78 s **不是**普遍保证。
2. **存在退步**：2/6 局退步（+51.09 s、+14.38 s），已完整保留，未剔除。
   本阶段**未**针对这两个种子追加规则或调参。
3. **建模假设不是题面事实**：`p_dir = 0.5`、`R ~ U[1000,1500]`、朝向均匀分布均为建模假设。
4. **本地环境口径**：全部数值来自本地参考环境，**不是官方端口实测**，
   不能等同官方场景的改善幅度。
5. **未自动切换默认版本**：`launch.py` 默认仍为 `stable`。

---

## 8. 交付物与复现

```powershell
# 生成候选决策模块（构建期，一次性；已生成的产物已随包提交）
python experiments/stage3_candidate/tools/build_candidate_method.py

# 冻结清单
python experiments/stage3_candidate/tools/write_freeze.py

# 验证 1：与阶段2 实验 C 一致（源码局部性 + 数值 + 动作序列）
python experiments/stage3_candidate/verify_equivalence.py

# 验证 2：6 个全新场景 × A/C 配对（12 局）
python experiments/stage3_candidate/run_independent_validation.py

# 启动入口（默认 stable）
python experiments/stage3_candidate/launch.py --version stable --case 9001:10
python experiments/stage3_candidate/launch.py --version history_candidate --case 9001:10
```

| 文件 | 内容 |
|---|---|
| `FREEZE.json` | 冻结声明与全部相关文件 sha256 |
| `launch.py` | 启动入口（stable / history_candidate） |
| `candidate_decision.py` | 候选决策器（构建期生成，含唯一改动标记） |
| `predictor.py` | 接收预测接口与冻结实现 |
| `model.py` | 冻结的假设集模型（与阶段2 逐字节一致） |
| `observer.py` | 观测记录 + 网格计数取证 |
| `results/verify_equivalence.json` | 验证 1 结果 |
| `results/validation_12runs.csv` | 12 局逐局记录（T/L/M/S/F/N、闭合残差、完成状态、逐频道结论计数、no_signal 三量、模型计数、回退原因） |
| `results/validation_summary.csv` | 逐案例 A/C 与差值、no_signal 三量对照 |
| `results/validation_stats.csv` | 汇总统计（平均/中位/最差/胜平负/回退） |
| `results/validation_fallbacks.csv` | 逐局模型使用与回退、动作改变计数 |
| `results/validation_12runs.json` | 完整记录（含逐频道结束证据、逐动作轨迹） |
| `results/launch_smoke_history.txt` | 启动入口实测输出（配置/模块/源码标识） |
