# 官方困难频道「长清除序列」诊断：020309/Ch5、020517/Ch9、020723/Ch16

> **本轮边界（严格遵守）**：只诊断、不实施新策略；**未调用官方模拟器**；**未新增随机案例**；**未调参**；
> `src/client_runner.py`（通信）与 `src/strategy_engine.py`（预算）**未改动**（冻结）。
> 本轮只新增只读诊断脚本（`scratch/`）与本报告。
>
> **后续修订说明（不改变本报告任何结论）**：其后一轮按"只修 D1/D2"实施了
> D1（`best_jq=None` 格式化异常）与 D2（默认运行日志移到包外独立目录），
> 因此 `local_decision_frozen.py`、`candidate/candidate_decision.py`、`src/client_runner.py`、
> `scripts/run_port_test.py` 的**现行指纹已变更**；本报告 §2/§4 引用的指纹与全部历史运行
> 均属 **r1 身份**（原版字节存于 `experiments/_archive_pre_d1_20260913/`），**不得**用新指纹冒充。
> 详见 `results/delivery/MINIMAL_FIXES_D1_D2.md`。


---

## 〇、结论摘要（先说不可做的部分）

| 请求交付物 | 状态 | 原因（证据见 §3） |
|---|---|---|
| **三个决策快照**（位置/观测/网格规模与范围/计划长度/模型可用性与相容假设数/是否回退/J0/最佳Jq/预测接收概率/选择理由） | **无法产出** | 三局的**客户端逐动作观测日志在本机不存在**；服务器侧只有聚合计数与加密行为日志 |
| **逐目标成本分解表**（此后该目标实际产生的移动/检测/失败清除成本） | **无法产出**（逐目标） | 同上：逐动作归属需要客户端日志 |
| 运行级成本分解表 | **已产出**（§2，恒等式口径经交叉校验） | 只依赖服务器聚合计数 |
| “预测网格空集异常”到底对应哪个计数 | **已查明**（§4，含对照实测） | 纯代码与合成探针，不依赖缺失日志 |
| 三类原因（几何不确定性 / 模型回退 / 局部评分缺陷）的**逐目标判定** | **证据不足，明确停止** | 缺少逐目标观测；只能给出 1 个可证伪的机制假设（§6） |

同时发现并复现了**两个明确缺陷**（一个代码缺陷、一个交付流程缺陷），见 §5，均只提最小修复、本轮不实施。

---

## 一、对象确认（把三个标签钉到具体官方 run 上）

用户给的 020309 / 020517 / 020723 是**客户端进入时刻**。与服务器统计库、`behavior-logs` 交叉后：

| 标签（本地进入时刻） | 官方 `practice_run_no` | `case_code` | 窗口(window_started_at_utc → ended_at_utc) | 本地窗口 | 指定困难频道 |
|---|---|---|---|---|---|
| 020309 | 5531364280976582949 | `4W45-MSUU-V4V7-H9DZ` | 18:01:14.647Z → 18:04:53.077Z | 02:01:14 → 02:04:53 | Ch5 |
| 020517 | 3190371593355798820 | `C6KE-BSQB-9CZD-P5CH` | 18:05:14.063Z → 18:06:25.924Z | 02:05:14 → 02:06:25 | Ch9 |
| 020723 | 2317764918308646655 | `4S29-ZUPR-M9XK-ZTCM` | 18:07:22.566Z → 18:10:49.643Z | 02:07:22 → 02:10:49 | Ch16 |

钉合依据（秒级吻合，非猜测）：统计库行 `received_at_ms`（= 该局结束）减去 `program_run_duration_ms`（该字段在个别历史行上取值异常，
但对本三局与标签自洽；其语义需以客户端会话文件为准，而会话文件缺失）得到
02:03:1x / 02:05:17 / 02:07:2x，与标签 020309 / 020517 / 020723 对应；`team_no` 均为 `202623001546`。

---

## 二、官方侧可观测量（运行级）

### 2.1 三局统计（服务器明文统计库副本 `practice-statistics-queue.sqlite3`）

| 标签 | Ch | 检测 M | 切换 S | 失败清除 F | 成功清除 N | 干扰源数 | 虚拟时间 T(s) | 窗口时长(ms) | 结束原因 | 是否清完 |
|---|---|---|---|---|---|---|---|---|---|---|
| 020309 | 5 | 243 | 223 | **80** | 13 | 13 | 7132.2 | 103 217 | `user_exit` | **是（13/13）** |
| 020517 | 9 | 239 | 224 | **90** | 15 | 15 | 7533.1 | 68 521 | `user_exit` | **是（15/15）** |
| 020723 | 16 | 295 | 266 | **83** | 12 | 12 | 7677.0 | 206 226 | `user_exit` | **是（12/12）** |

三点即时可读的事实：

1. **三局全部把干扰源清完**（N=jam）且以 `user_exit` 正常退出 ⇒ 「长清除序列」是**成功前的漫长过程**，不是失败局；
2. 失败清除 F 占清除尝试的绝大多数（80/(80+13)=86%、90/105=86%、83/95=87%）；
3. 三局都在同批 49 局 P4 的**上半区但不极端**：检测数排第 17/18/7，失败清除排第 14/11/13，虚拟时间排第 23/17/14（从高到低）。
   ⇒ 「困难」是**逐频道**的概念，运行级总量只能说明它们确实付出了高清除代价。

### 2.2 运行级成本分解（T = L/5 + S + 5M + 3F + 5N，口径与 `audit_http_action_log` 逐字一致）

| 标签 | 5M | S | 3F | 5N | 固定项合计(s) | T 服务端(s) | **推断 L/5(s)** | **推断 L(m)** |
|---|---|---|---|---|---|---|---|---|
| 020309 | 1215 | 223 | 240 | 65 | **1743.0** | 7132.2 | 5389.2 | ≈ 26 946 |
| 020517 | 1195 | 224 | 270 | 75 | **1764.0** | 7533.1 | 5769.1 | ≈ 28 845 |
| 020723 | 1475 | 266 | 249 | 60 | **2050.0** | 7677.0 | 5627.0 | ≈ 28 135 |

**该表可信度有硬证据支撑**：用**同时拥有客户端日志**的 011421 局做同口径交叉校验——
客户端计账与服务器计数**完全相等**（切换 207=207，检测 232=232，失败清除 43=43，成功清除 3=3，
最终虚拟时间 4126.590 vs 4126.594830），反推 L/5 = 2615.595 s ⇒ **L ≈ 13 078.0 m**，
而客户端日志实测 **L = 13 077.97 m**（差 < 0.05 m）。⇒ 上式残差**就是** L/5，不是拟合。

**但逐频道/逐目标归属依旧不可得**：服务器没有逐动作/逐频道列（§3.1）。

---

## 三、证据可得性审计（为什么三个快照做不出来）

### 3.1 服务器侧能给的（已穷尽）

| 来源 | 内容 | 结论 |
|---|---|---|
| `practice-statistics-queue.sqlite3` | 单表 `practice_statistics_tasks`（24 列，121 行） | 只有**聚合计数**：M/F/N/S/T/jam/end_reason…，**无逐频道、无坐标、无观测序列** |
| `*.result.json`（明文） | `version/problem_no/run_no/case_code/package_sha256/window_*/jammer_count/omni/directional` | 只有元数据；三局分别 13（全向6+定向7）、15（12+3）、12（2+10） |
| `*.jlog` / `*.psum` | 76/79/86 KB | 载荷为 **gzip + AES-256-GCM** 加密封装（前轮已确立的硬边界），**不可读** |
| `behavior-runs/` | 空 | — |

### 3.2 客户端侧（唯一可能承载“实际历史观测”的东西）——**不存在**

1. `results/audit_logs/` 有 142 个日志文件，但 **01:39:44 → 02:40:40 完全空档**；
   三局对应的 `http_session_20260913_0203*` / `0205*` / `0207*` **一个都没有**。
2. **整个工作区在 01:50–02:20 之间没有任何文件被写过**（全目录 mtime 扫描）⇒ 这三局不是在本工作区目录树下跑的。
3. 按文件名全盘搜索 `D:\桌面`、`D:\Downloads`、`C:\Users\123`（`dir /s /b`）均**无命中**；
   两个旧副本（`cumcm2026 - Copy`、`- Copy (2)`）也无。
4. 发布包 `release/p4_history_candidate_v1/results/{sessions,audit_logs}` **为空**。
5. 同工作区的另一条工作流（`p4explore/`）最后写入时间是 **01:15:43**，02:03–02:07 期间无活动。

⇒ **“使用对应运行版本及实际历史观测重建各目标状态”在本机不具可行性**：既没有观测序列，
也就无法重建“第一次进入长清除序列之前”的状态，更无法给出该目标的 J0/Jq/预测接收概率/相容假设数。
按纪律，**不用具他局的日志代替**，也**不把最终清除坐标当真值**（本轮没有真值来源，故不存在该风险的使用）。

### 3.3 日志为什么可能不见了（**可证伪的流程性假设**，与策略无关）

- 硬证据 A：`release/build_release_v1.py:627-631` 开头即 `shutil.rmtree(RELEASE)` —— 重建会**连同包内 `results/` 一起删除**；
- 硬证据 B：包内 `results/*` 目录的创建时间 = **03:09:11**（上一轮重建）与 **03:13:25**（本轮重建）
  ⇒ 每次重建后都是空目录；
- 因此：**若这三局是用发布包跑的**，其日志会写在包内 `results/audit_logs/`，并在任何一次重建中**被抹除**。
- 该假设**可被用户直接证伪**：只要那三次运行的控制台窗口或日志副本还在（哪怕是手工复制的 jsonl），
  把它放回 `results/audit_logs/`，本轮的三个快照立刻就能产出。

---

## 四、“预测网格空集异常”究竟对应哪个计数（已查明）

### 4.1 三种“空”在代码中的真实落点

| 概念 | 计数/返回 | 触发条件（代码位置） | 后果 |
|---|---|---|---|
| **(1) 模型假设集为空** | `call_fallback_count` + `fallback_reason_hist`（逐调用）；`decision_fallback_count`（逐决策） | `predictor.prepare_for_decision` 判定 `m.is_usable()` 为假（`n_alive=0`，`exhausted_reason = all_hypotheses_incompatible_after_{n}_observations`）⇒ `reception_probability()` 返回 `None`（`candidate_decision.py:99-104`） | **逐字回退**冻结公式 `frozen_recv_prob` |
| **(2) “预测网格空集异常”** | `empty_prediction_count`（同时 `unrepresentable_prediction_count` +1） | `candidate_decision.py:338-343`（冻结版 `local_decision_frozen.py:423-428`）：候选打分中，`p_recv>0` 时把“指向样本单元的测向反馈”作用到**克隆安全网格**，该裁剪会清空存活集 | 裁剪被**拒绝**、网格标记 `contradiction=True`，该候选**不可表示**、退出 argmin |
| **(3) 实际安全网格不可用** | 返回 `action_type='fail'` | `candidate_decision.py:135-148`：`grid.count()==0` → `empty_grid_no_valid_state`；`grid.contradiction==True` → `model_contradiction_observation_conflicts_with_grid` | **不做打分**，交由引擎显式判失败 |

### 4.2 关键更正：它**不是**“空集”，也**不是**模型回退

- 在 P4 路径下 `_apply_observation_prune`（`conservative_grid_frozen.py:62-85`）**根本不允许把存活集裁空**：
  会清空时它**拒绝**该次裁剪、保留上一版状态，并对测向观测置 `contradiction=True`。
  ⇒ 计数名字里的“空集”是历史命名；实际发生的是**“测向反馈与网格全局矛盾（裁剪被拒）”**。
- 官方报告的“预测网格空集异常”= **(2)**；模型回退 = **(1)**；两者是**不同计数、不同代码路径**。

### 4.3 实测（合成机制探针 + 既有验收数据复用，均未调用模拟器）

机制探针 `scratch/verify_empty_semantics.py`（合成几何 + 可替换模型，结果见
`results/delivery/empty_semantics_check.json`）：

| 情形 | `empty_prediction_count` | `unrepresentable` | 回退计数 | 动作 |
|---|---|---|---|---|
| 模型可用、`p_recv=0.5`、候选含 1 个远点(q=(-2000,0)) | **+1** | +1 | 0 | `measure`（该候选被剔除，其余候选照常打分） |
| **同一几何、同一候选，但无模型**（冻结公式在该距离 `p_recv=0`） | **+0** | +0 | +20（`predictor_not_attached`） | `measure` |
| 假设集耗尽（`n_alive=0`） | **+0** | +0 | +20 调用 / +1 决策（`all_hypotheses_incompatible_after_3_observations`） | `measure` |
| 实际网格 `contradiction=True` | +0 | +0 | 0 | **`fail`**（`model_contradiction_observation_conflicts_with_grid`） |
| 实际网格 `count()==0`（合成掩空） | +0 | +0 | 0 | **`fail`**（`empty_grid_no_valid_state`） |

**既有验收数据复用的独立佐证**：`results/delivery/http_acceptance_R2_history_candidate_p4.log`
（history_candidate，本地 mock，未重跑）同时出现

- `预测网格空集异常计数: 5 次`，而同一局的会话文件里
  `decision_fallbacks = 0、call_fallbacks = 0、fallback_reason_hist = {}`（**该局一次模型回退都没有**）；
- 同场景 stable 基线 `http_acceptance_R1_stable_p4.log` 为 `0 次`。

⇒ **“预测网格空集异常 5 次 + 模型回退 0 次”同时成立**，直接证明二者不可等同；
且该计数只在**候选（模型）路径**出现（stable 基线恒为 0，因为冻结公式在可表示距离内必然给出 `p_recv>0`、
样本单元自身必被保留；只有模型能把正概率延伸到网格算子无法表示的位置）。

---

## 五、发现的明确缺陷与最小修复建议（本轮不实施）

### 缺陷 D1（代码，可复现）：候选全部不可表示时对 `None` 做 `:.1f` 格式化 → 崩溃

- 触发：打分循环中**所有**候选都因 (2) 被剔除 ⇒ `best_q is None, best_jq is None` ⇒
  走到“直接清除”分支的 `reason` 字符串 `f"direct_clear_better (J0={j0:.1f}s vs Jq={best_jq:.1f}s)"`。
- 复现（本报告§4.3 探针用例 4）：`TypeError: unsupported format string passed to NoneType.__format__`，
  位置 `candidate/candidate_decision.py:385`；**同一写法也存在于冻结基类 `local_decision_frozen.py:470`**
  （候选版由冻结源码生成，属**继承而来的缺陷**，不是候选引入）。
- **最小修复建议**（仅改日志文案，不改任何动作选择）：
  ```python
  jq_txt = f"{best_jq:.1f}s" if best_jq is not None else "—"
  ... f"direct_clear_better (J0={j0:.1f}s vs Jq={jq_txt})"
  ```
  影响面：需改**冻结件** ⇒ 必须重新生成候选并重跑验收基线；**本轮不做**（本轮只诊断）。

### 缺陷 D2（交付流程，非策略）：发布包重建会删掉包内官方运行日志

- 位置：`release/build_release_v1.py:627` `shutil.rmtree(RELEASE)`。
- 后果：任何用发布包跑的官方局，其 `results/audit_logs/*.jsonl` 与 `results/sessions/*.json`
  会在下一次重建时**无提示消失**（这正是 §3.3 的假设来源）。
- **最小修复建议**（二选一，均为 1 行级改动）：
  1. 重建前把 `results/` 移出并回填（或对 `results/**` 跳过删除）；
  2. 让官方连接命令默认把日志写到包外（`--session_dir` / 审计目录可覆盖），包内只留空目录。
- 本轮只提建议，不改构建脚本。

---

## 六、唯一一个后续可证伪的机制假设（明确标注：尚未验证）

> **H1**：三局长清除序列的主要成因是**几何不确定性仍大**（安全网格存活规模大、清除计划长，
  阴性观测不收缩网格），而**不是**历史接收模型失效/回退。

**判定式（一旦取到三局日志即可证伪）**：对每个目标，取“首次进入长清除序列”那一刻的快照，

- 若窗口内 `call_fallback_count`（该频道）**= 0** 且 `decision_fallback_count = 0`，
  同时 `surviving_cells` 大、`plan_len ≈ 120`（与本地参考一致）⇒ **支持 H1**；
- 若窗口内出现 `decision_fallback_count > 0` / `fallback_reason_hist` 非空，
  或 `empty_prediction_count`/`unrepresentable_prediction_count` **在序列起点之前聚集上升**
  ⇒ **H1 被推翻**，应转向“模型候选剔除影响补测选择”这一支。

**所需数据**（本轮缺、且只此一份）：三局的
`results/audit_logs/http_session_20260913_0203*/0205*/0207*.jsonl`（逐动作明文请求/响应）
与对应 `--session_dir` 会话文件（含 `model_stats` 与逐决策记录
`decision_records`：`channel/grid_count/baseline_action/candidate_action/model_alive/model_n_obs/model_usable`）。

**不做的事**（按纪律）：不在同一历史状态下声称替代动作“节省了多少官方虚拟时间”——
未实际执行的替代动作**只能报告预测**，本轮连状态都未能重建，因此连预测也不给。

---

## 七、本轮自检

- **未调用官方模拟器**：全程未连接 `127.0.0.1:2026`（该端口上的 `jammers-simulator.exe` 自 2026-09-12 10:29:40 起持续监听）；
  只读取其**落盘数据文件的副本**（统计库副本位于 `scratch/_jstats2/`）。
- **未新增随机案例、未调参**：§4.3 的探针是**合成几何 + 替身模型**的单元级检查，不构成案例或基准；
  §4.3 的 5 次/0 次对照**复用**既有验收日志与会话文件（未重跑）。
- **通信与预算代码冻结**：`src/client_runner.py`、`src/strategy_engine.py`、`scripts/run_port_test.py`
  本轮**零改动**——工作区指纹与上一轮结束值逐字节相同：
  `strategy_engine f4f41a97bd24d289`、`client_runner fd03f0e4c21f571c`、`run_port_test be5bd784d6d6cacf`；
  发布包内同三项亦不变（`f4f41a97bd24d289` / `fd03f0e4c21f571c` / `5763e3017550edf4`）。
- **不把最终清除坐标当真值**：本轮未使用任何“最终清除位置”作为推理输入。

## 八、交付物与复现命令

```powershell
python scratch/diagnose_long_clears.py          # 统计库结构 + 三局统计行 + 客户端日志存在性
python scratch/list_official_runs_timeline.py   # 本队 51 局 P4 官方 run 时间线（含日志可得性）
python scratch/cost_decomposition_official.py   # 口径交叉校验 + 运行级成本分解
python scratch/verify_empty_semantics.py        # 三种“空”的机制辨析（含缺陷 D1 复现）
```

| 交付物 | 内容 |
|---|---|
| `results/delivery/LONG_CLEAR_3RUNS_诊断报告.md` | 本报告 |
| `results/delivery/official_3runs_cost_decomposition.json` / `.log` | 三局运行级成本分解 + 011421 口径校验 |
| `results/delivery/official_runs_timeline.log` | 本队 51 局 P4 官方 run 时间线（含客户端日志可得性） |
| `results/delivery/empty_semantics_check.json` / `.log` | 三种“空”的机制辨析与缺陷 D1 复现 |
