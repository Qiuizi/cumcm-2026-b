# CUMCM 2026 B 题：无线电干扰源的快速自动定位与清除

2026 年高教社杯全国大学生数学建模竞赛 **B 题**的建模求解与工程实现仓库。

题目要求在半径 1800 m 的圆形区域内，为搭载于机器狗的干扰源自动定位清除系统建立数学模型：
用交会定位法确定多边形定位区域（问题 1）、设计第二检测点选择策略（问题 2）、制定机器狗自动搜索
定位与清除策略并设计算法（问题 3、问题 4）。干扰源个数未知（10–16 个），需在保证全部清除的前提
下最小化"虚拟时间"。

本仓库包含：核心求解代码（`src/`）、实验与验收脚本（`scripts/`）、方法研究报告与阶段实验记录
（`experiments/`）、论文图表（`figures/`）、交付结论与审计报告（`results/delivery/`）、题面与附件
（`raw/`、`paper/extract/`）。

> 说明：本仓库为**精简版**，仅收录核心代码、关键结果、图表与报告。原始逐动作审计日志
> （`results/audit_logs/`、各产物的 `action_logs/`，约 10 MB）、调试草稿（`scratch/`）、
> 探索性原型（`p4explore/`）与历史归档包（`release/_archive/`）未纳入版本库，
> 详见下方 [未纳入的内容](#未纳入的内容)。

---

## 1. 方法概览

### 1.1 计费模型：一切动作折算为虚拟时间

| 动作 | 虚拟时间成本 |
|---|---|
| 移动 | `d / 5`（距离 m ÷ 5 m·s⁻¹） |
| 切换频道 | 1 s / 次 |
| 检测 `/measure` | 5 s / 次 |
| 清除失败 | 3 s / 次 |
| 清除成功 | 5 s / 次 |

一局的虚拟时间恒等式为 **`T = L/5 + 5M + S + 3F + 5N`**（L 移动距离、M 检测次数、S 切频次数、
F 失败清除、N 成功清除）。实现对该恒等式逐局复算，残差 ≤ 1e-6 s。

### 1.2 问题 1：交会定位多边形与直径圆判据

`src/geometry_p1.py` 以示向度射线族的凸交会构造定位多边形，给出直径 `D` 的精确算法，并证明
直径圆覆盖判据 `(A − V)·(B − V) ≤ 0`。结论层面：若以定位区域直径为直径的圆要覆盖该区域，
当且仅当该区域所有顶点都落在以直径为弦、直径圆内侧的半圆内；存在三点反例（`D = 40 m` 但
最小覆盖圆半径 `ρ = 23.094 m > 20 m`）说明**直径圆一般不覆盖**定位区域，一般关系为
`D/2 ≤ ρ ≤ D/√3`。

### 1.3 问题 2：第二检测点选择策略

`src/candidate_p2.py` 基于先验分布对候选点做期望定位误差评估，输出第二检测点选择策略与候选区域。

### 1.4 问题 3 / 问题 4：搜索—定位—清除策略

- **P3（固定覆盖站 + 扇区证据链）**：7 个静默测站 @ r = 999，用 **168 个扇区单元**的"存在静默测站
  且最远点 ≤ 1000 m"排除性证据建立覆盖证书。`no_signal` 的语义是**排除以测站为中心、半径 1000 m
  的圆盘 `B(q, 1000)`**，而非"该频道不存在"。
- **P4（25 点三角网 + 可证否覆盖证书）**：测站网 **25 点 = 中心 O + 8 @ 990 + 16 @ 1840 m**，
  证书由 **32 个三角形**构成——"三顶点静默且三边 ≤ 1000 m ⇒ 三角形内任意点不可能是源"。
  精确刻画：候选点 `x` 被排除 ⟺ `x ∈ conv{ q ∈ Q : ‖q − x‖ ≤ 1000 }`，等价于"以 `x` 为心的
  环向角隙最大值 ≤ π"。
- **硬下界（与布局无关）**：若要 P4 证书对 Ω 精确成立，外环半径 **≥ 1800 m**；半径 1800 m
  边界圆上单圆盘截得的最大弧长为 **67.49798°**（在 `d* = √(1800² − 1000²) = 1496.663 m` 处）；
  3-重覆盖至少需 `|Q| ≥ 17` 个测站（1-重覆盖至少 `|Q| ≥ 6`）。
- **布局敏感性**：内环半径由 990 降到 900 时，严格放行率由 **1.0000 掉到 0.4718**，故
  990 / 1840 是在严格判据下几乎不损失、且点数可行的选择。
- **局部决策（`src/local_decision.py`）**：每个目标维护由测向 / 静默 / 近距 / 清除失败四类观测
  裁剪出的**保守安全网格**；已收缩到可一步安全清除时直接清除，否则构造有限清除计划并把其在
  采样场景上的平均代价记为 **J0**；对候选补测点 `q` 计算闭环 **Jq**，仅当 `min J(q) + margin < J0`
  才派发补测。
- **历史接收模型候选版（`experiments/stage3_candidate/`）**：假设（粒子）数 `n_hyp = 512`，
  源类型先验 `p_dir = 0.5`、接收半径 `R ~ U[1000, 1500]`、朝向 `u ~ U[0, 2π)`（均为**建模假设**，
  非题面事实）；用全部历史观测重新过滤相容假设，假设集为空时**逐字回退**冻结公式并记录原因。
  候选决策主体由**构建期生成器**从冻结基线生成，只替换"接收概率"一个切片，其余逐行相同
  （`277 vs 277` 行，`runtime_uses_inspect_or_exec = False`）。

### 1.5 工程协议对齐

- **通信幂等**：同一 `request_id` + 同一内容重复提交不重复执行；`400/404/405/409/413/415`
  立即失败不重试，`429/500` 才退避重试且复用原 id；重试耗尽时如实记录"未完成"，不伪造 `COMPLETED`。
- **现实预算**：本局可用现实时间取 `/enter` 返回的 `remaining_real_duration_s`（配置上限只作封顶），
  以**单调时钟**固定起点；截止后不再派发任何测量 / 清除。
- **运行产物外置**：默认日志写在发布包外的独立目录，包重建不会删除历史记录。

---

## 2. 关键结果

### 2.1 本地 12 局配对验收（6 个新场景 × A(stable) / C(history_candidate)）

| 案例 | A (stable) | C (candidate) | ΔT = C − A (s) |
|---|---|---|---|
| P4-10src-seed9501 | 8 661.10 | **7 454.34** | **−1 206.76** |
| P4-10src-seed9502 | **7 951.18** | 8 002.27 | +51.09 |
| P4-13src-seed9513 | 7 380.00 | **6 909.45** | **−470.55** |
| P4-13src-seed9514 | 7 429.73 | **6 933.27** | **−496.46** |
| P4-16src-seed9521 | **6 294.64** | 6 309.02 | +14.38 |
| P4-16src-seed9522 | 4 795.08 | **4 534.69** | **−260.39** |

平均节省 **+394.78 s**、中位 **+365.47 s**、最大节省 **+1 206.76 s**、最大退步 **+51.09 s**，
**4 胜 0 平 2 负**。12 局合计：调用过模型的决策 184 次（模型可用 174，整体回退 10，占 5.4%）。
最大退步局 `seed9502` 的 ΔT 由 `ΔL/5 = +96.07`、`5ΔM = −105.00`、`ΔS = 0`、`3ΔF = +60.00` 构成
（合计 +51.07 s）⇒ 退步来自"换补测点后路径与清除序列的连锁改变"，**不是机制失效**。

证据：`experiments/stage3_candidate/STAGE3_REPORT.md`、`validation_12runs.json`、
`experiments/stage2_hypothesis/results/stage2_paired_9runs.json`。

### 2.2 本队官方模拟器运行（队号 `202623001546`）

模拟器统计库中 121 行统计（problem 3: 70，problem 4: 51）。三局"困难频道"对象：

| 进入时刻 | 频道 | M | S | F | N | 干扰源 | T (s) | 是否清完 |
|---|---|---|---|---|---|---|---|---|
| 020309 | Ch5 | 243 | 223 | 80 | 13 | 13 | 7 132.2 | 是 13/13 |
| 020517 | Ch9 | 239 | 224 | 90 | 15 | 15 | 7 533.1 | 是 15/15 |
| 020723 | Ch16 | 295 | 266 | 83 | 12 | 12 | 7 677.0 | 是 12/12 |

失败清除占比 80/93、90/105、83/95 ≈ **86%、86%、87%** ⇒ "长清除序列"是成功前的漫长过程。
运行级成本分解与口径交叉校验见 `results/delivery/official_3runs_cost_decomposition.json`、
`results/delivery/LONG_CLEAR_3RUNS_诊断报告.md`。

### 2.3 工程性验收

| 项目 | 结果 | 证据 |
|---|---|---|
| 通信错误分类与幂等 | T1–T4 + T2b 全部通过 | `results/delivery/http_semantics_tests.json` |
| 现实预算（60 s 按 60 s 用） | 截止后零派发，重试不延长预算 | `results/delivery/budget_remaining_tests.json` |
| D1 最小修复 | 正常评分 4 态修复前后逐字段一致 | `results/delivery/d1_fix_verification.json` |
| D2 日志外置 | 入口日志全部落在包外，重建后 5 个指纹不变 | `results/delivery/d2_runsdir_verification.json` |

---

## 3. 目录结构

```
cumcm_2026/
├── src/                        核心求解代码
│   ├── geometry_p1.py          P1 交会定位多边形 + 直径算法
│   ├── candidate_p2.py         P2 第二检测点候选评估
│   ├── evidence_tracker.py     P3/P4 覆盖证据链与测站网
│   ├── conservative_grid.py    保守安全网格（观测裁剪）
│   ├── local_decision.py       局部决策：清除计划 + J0/Jq 门槛
│   ├── strategy_engine.py      策略引擎（P3/P4 分支、档位接线）
│   ├── client_runner.py        HTTP 客户端：幂等 / 重试 / 预算
│   ├── sim_env.py              本地替代仿真环境
│   └── mock_server.py          本地 Mock 服务端
├── scripts/                    实验、评测与验收脚本（含 run_port_test.py 入口）
├── experiments/                方法研究与阶段实验
│   ├── roadmap/                覆盖结构与硬下界研究（ROUTES_研究报告.md）
│   ├── stage2_hypothesis/      假设检验与配对实验
│   ├── stage3_candidate/       历史接收模型候选版（STAGE3_REPORT.md）
│   └── _archive_pre_d1_20260913/  r1 原版字节（只读，用于指纹溯源）
├── figures/                    论文图 1–6
├── paper/extract/              题面与附件的文本抽取
├── raw/                        题面 PDF 与附件 1/2
├── results/
│   ├── delivery/               论文素材、诊断报告与工程验收记录
│   ├── p3_merge_regression/    P3 合并回归
│   ├── p4_fix/                 P4 修复与等价性验收
│   └── p4_cover_redesign/      P4 覆盖网重设计与敏感性
├── release/                    冻结候选发布包 + 打包脚本
├── *_frozen.py                 冻结基线组件（P2/P3/P4 依赖）
└── requirements.txt
```

---

## 4. 复现

环境：Python 3.9+（在 3.12 验证），依赖 `numpy`、`scipy`、`matplotlib`、`requests`。

```bash
pip install -r requirements.txt

# 问题 1 / 问题 2：算法求解与几何验证
python scripts/run_p1.py
python scripts/run_p2.py

# 问题 3 / 问题 4：本地基准评测
python scripts/run_p3_benchmark.py
python scripts/run_p4_benchmark.py

# 论文图表
python scripts/generate_paper_figures.py

# 档位接线验收（不通信）
python scripts/verify_launch_profiles.py

# 本地替代驱动端到端（非官方端口），stable 与候选版
python scripts/run_port_test.py --port 13026 --prob p3 --version C --profile stable --sources 10
python scripts/run_port_test.py --port 13027 --prob p3 --version C --profile radial_candidate --sources 10

# P4 历史接收模型候选版（需显式开启；默认 stable）
python scripts/run_port_test.py --port 13028 --prob p4 --version C --profile history_candidate --sources 10 --mock_seed 9501

# P3 径向覆盖九组配对评测（会生成新随机场景，约 7 分钟）
python scripts/verify_p3_radial_coverage_rigorous.py
```

档位：`stable`（默认，v3.4.2）、`radial_candidate`（P3 径向自适应覆盖，实验特性）、
`history_candidate`（P4 历史接收模型候选版）。候选特性均**默认关闭**，不显式开启时行为与基线一致。

官方端口运行命令见 `delivery/P3_radial_candidate_delivery_v3.4.2/LAUNCH_COMMANDS.md`。

---

## 5. 版本身份与引用规范

历史运行 / 验收数据一律标注 **r1** 指纹，不得用 r2 指纹冒充：

| 文件 | r1 | r2（当前） |
|---|---|---|
| `candidate/candidate_decision.py` | `811ed39875813301` | `8be9f9df647194d8` |
| `local_decision_frozen.py` | `6d26e61de9a25fd4` | `6f9c895357149c97` |
| `src/client_runner.py` | `fd03f0e4c21f571c` | `5f221dd4e8a83fad` |
| `run_port_test.py` | `e5fc7db9d41e50e5` | `2f59f8daf7a41675` |
| `src/strategy_engine.py` | `8dca0841ba7c45de` | `f4f41a97bd24d289` |

r1 原版字节见 `experiments/_archive_pre_d1_20260913/`；包内指纹总表见各交付包的
`FREEZE.json` 与 `MANIFEST_文件指纹.csv`。

---

## 6. 局限与不可宣称清单

论文与结论中必须如实写出的边界（完整版见 `results/delivery/PAPER_MATERIALS_方法与结果与局限.md`）：

1. **官方逐动作日志缺失**：三局困难频道（020309 / 020517 / 020723）在本机没有客户端逐动作日志，
   服务器侧只有聚合计数，`.jlog/.psum` 为 gzip + AES-256-GCM 加密不可读 ⇒ **不能**给出逐频道
   快照，也不能做逐目标归因，只有运行级分解与一个可证伪假设。
2. **无真值**：源的真实位置不可从接口获得，**不得**把"最终清除坐标"当作真值使用。
3. **先验是假设**：`p_dir`、`R`、`u` 的分布均为建模假设，非题面事实；敏感性测试只覆盖网格布局与
   半径，未做先验的系统性标定。
4. **官方成绩的表述边界**：本队官方运行为**练习局**（统计库）且未保存逐动作日志；论文中不得使用
   "官方成绩 / 官方排名"字样。本地 12 局配对数据是**本地参考环境**结果。
5. **D1/D2 修订的身份边界**：r2 只改了一条异常分支的文案与日志落盘位置，不改变数值行为；但 r2 指纹
   与 r1 不同 ⇒ 引用历史结果必须标注 r1 指纹。
6. **`empty_prediction_count` 命名与实际语义不符**：该计数对应"正概率假设下的测向反馈与克隆安全
   网格全局矛盾（裁剪被拒绝）"，**并非**真的网格空集（P4 路径的裁剪运算符不允许把存活集裁空）。
   佐证：history_candidate 一局该计数 = 5 次，而同局 `decision_fallbacks = 0`、`call_fallbacks = 0`。
7. **模型未自动启用**：候选版需显式 `--profile history_candidate`，默认仍为 `stable`。
8. **P4 网格不收缩的语义**：阴性观测（`no_signal`）在 P4 **不使网格收缩**（`shrunk = 0` 已验证），
   其作用是"排除圆盘"而非"裁剪网格"；讨论信息增益时不可混用两种语义。

---

## 7. 未纳入的内容

以下内容因体量或性质未纳入版本库（已在 `.gitignore` 中声明）：

| 路径 | 说明 |
|---|---|
| `results/audit_logs/` | 官方 / 本地会话的逐动作原始日志（`.jsonl`，约 9 MB） |
| `delivery/**/action_logs/` | 各交付包的逐动作日志副本 |
| `scratch/` | 一次性调试与诊断草稿脚本 |
| `p4explore/` | P4 覆盖结构探索性原型与中间搜索结果 |
| `release/_archive/` | 历史归档发布包 |
| `delivery/*.zip` | 交付包压缩副本（内容即对应目录） |
| `**/__pycache__/`、`*.sqlite3` | 字节码缓存与本地数据库 |

需要完整证据链时，可在本地按 `scripts/` 中的评测脚本重跑复现，或用 `results/delivery/*.patch`
核对源码差异。

---

## 8. 说明

- 题面与附件（`raw/`、`paper/extract/`）版权归全国大学生数学建模竞赛组委会所有，此处仅用于
  复现对应解答。
- 本仓库未附开源许可证；如需授权请与作者联系。
