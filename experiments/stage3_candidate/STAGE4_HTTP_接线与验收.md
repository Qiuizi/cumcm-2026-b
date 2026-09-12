# 第四阶段：P4 history_candidate 接入 HTTP 运行入口 · 有限交付验收

> 只用**已有本地替代 HTTP 服务**（`src/mock_server.py`，由 `run_port_test.py` 自动拉起）。
> 不调用官方模拟器、不另建模拟器、不新增策略、不调参、不扩大性能测试。

---

## 0. 最终回答

**`history_candidate` 已经具备由真实 HTTP 入口运行的条件。**
本轮有限验收 **5 项全部通过**（见 §3）。**无阻塞项。**

同时必须如实上报一个**环境级问题**（不影响结论，但影响交付方式）：
本工作区存在**周期性把已跟踪文件恢复为 HEAD** 的外部行为，实测两次把我对
`scripts/run_port_test.py` 的接线改动回退掉（一次打断 history_candidate 运行，一次打断验收第三局）。
因此本轮把接线做成 **幂等补丁 + 每次运行前重放**，并单独导出 patch 作为交付物；
在用户自己的检出里按 §2.4 一次性应用即可长期生效。

---

## 1. 两条真实端口启动命令（本验收实际执行）

```powershell
# R1 —— 稳定基线（P4）
python scripts/run_port_test.py --port 14026 --prob p4 --version C --profile stable `
    --robot_id team2026 --sources 10 --mock_seed 9501 `
    --session_dir results/delivery/http_sessions

# R2 —— 历史接收模型候选版（P4）
python scripts/run_port_test.py --port 14027 --prob p4 --version C --profile history_candidate `
    --robot_id team2026 --sources 10 --mock_seed 9501 `
    --session_dir results/delivery/http_sessions
```

（R3 为 P3 既有入口不变性核对：`--port 14028 --prob p3 --version C --profile stable`，
其余参数相同。）

- `--version` 的调度含义**未改动**（B/C 仍决定固定顺序 vs 开放路线重排）。
- 新增 `--profile history_candidate` 选择 P4 档位，**默认仍为 stable**。
- 新增 `--mock_seed` 固定本地 mock 场景（可复现验收）；缺省仍为当前时间。
- 新增 `--session_dir`：把完成状态/逐频道结束证据/计费/回退/生效配置写入
  `session_<profile>_<prob>_<时间戳>.json`，**文件名带时间戳，绝不覆盖前局**。

不兼容组合在**进入任务前**报错（实测）：

```
$ python scripts/run_port_test.py --prob p3 --profile history_candidate
run_port_test.py: error: --profile=history_candidate 是 P4 档位，与 --prob p3 不兼容；…

$ python scripts/run_port_test.py --prob p4 --profile radial_candidate
run_port_test.py: error: --profile=radial_candidate 是 P3 档位（径向自适应覆盖），与 --prob p4 不兼容；…
```

---

## 2. 接线方式

### 2.1 直接复用已验证模块（不另写决策实现）

`scripts/run_port_test.py` 在 `--profile history_candidate` 时调用
`experiments/stage3_candidate/wiring.py::build_candidate()`，返回：

| 角色 | 实现 | 源码文件 |
|---|---|---|
| 决策器 | `candidate_decision.HistoryCandidateDecision` | `experiments/stage3_candidate/candidate_decision.py` |
| 接收预测接口 | `predictor.HistoryReceptionPredictor` | `experiments/stage3_candidate/predictor.py` |
| 假言集模型 | `model.ReceptionHypothesisModel` | `experiments/stage3_candidate/model.py` |
| 观测来源 | `observer.RecordingObserverDriver` | `experiments/stage3_candidate/observer.py` |

接线动作只有一步：`engine.local_decision = candidate_decision`，
另加 `observer.attach_engine(engine)`（只为记录网格计数取证）。
**P3、P4 覆盖布局、扫描规则、全局调度、候选点、清除计划、结束判据全部未改。**

### 2.2 冻结源码指纹核对（构建来源 vs 实际加载）

候选决策主体由冻结源码**构建期生成**，因此基类一旦变化，逐字继承前提即失效。
入口在进入任务前核对（实测全部 OK）：

| 文件 | 期望（FREEZE.json） | 实际加载 | 结论 |
|---|---|---|---|
| `candidate_decision.py` | `811ed39875813301` | `811ed39875813301` | OK |
| `predictor.py` | `0fa1753454775cbd` | `0fa1753454775cbd` | OK |
| `model.py` | `ada6c0069ee9b426` | `ada6c0069ee9b426` | OK |
| `local_decision_frozen.py`（生成来源/基类） | `6d26e61de9a25fd4` | `6d26e61de9a25fd4` | OK |
| `conservative_grid_frozen.py`（生成来源/基类） | `778af8fd986a79b6` | `778af8fd986a79b6` | OK |

模型先验规格（`n_hyp=512 / p_dir=0.5 / R∈[1000,1500] / 朝向均匀 /
eps 继承安全网格 / pool_factor=40 / max_rounds=6 / seed_base=20260912, stride=131）
与实际生效值逐项一致；不一致时入口直接 `SystemExit`，不允许带病运行。

### 2.3 历史模型只吃接口观测；重试不重复记账

- `RecordingObserverDriver` 包在 `HttpSimDriver` **外层**；
  观测字典只允许 `{kind, p, svd}`，其值全部来自 HTTP 响应的
  `measure_result` / `svd_deg`。
- `HttpSimDriver._post_with_retry` 的超时重试**复用自己的 `request_id`**，
  且在接口层**内部**完成 —— 外层观测器一次逻辑动作只看到一次调用，
  因此**重试不会重复写入历史**；服务器侧另有 `(path, request_id)` 幂等缓存。
- AST 静态检查：候选 4 个模块无 `sources / is_directional / orientation_deg /
  SimEnvironment / RadioSource / import sim_env` 的任何访问；
  `HttpSimDriver` 实例字段仅
  `base_url, robot_id, timeout_s, log_file, session_file, abs_session_path,
  req_seq, remaining_real_duration_s, start_timestamp` —— **不含任何真值**。

### 2.4 必要源码差异

| 交付物 | 说明 |
|---|---|
| `results/delivery/run_port_test_wiring.patch` | `scripts/run_port_test.py` 相对 HEAD 的完整 diff（**本阶段唯一被修改的既有文件**） |
| `scratch/apply_port_wiring.py` | 幂等补丁脚本：8 个锚点各要求命中一次，任一缺失即报错不写文件；用于重放 |

在自己检出里长期生效：

```powershell
git apply results/delivery/run_port_test_wiring.patch
# 或（等价、且可重复执行）
python scratch/apply_port_wiring.py
```

---

## 3. 验收结果：5 项全部通过

场景：**同一既有合法场景 P4 / 10 源 / mock seed 9501**（与第三阶段预注册案例
`P4-10src-seed9501` 同一环境种子）。

### A. 实际调用的决策器、模型参数与模块指纹 —— 通过

- R1（stable）：`local_decision_frozen.LocalDecisionMaker` +
  `conservative_grid_frozen.ConservativeGrid` ✅
- R2（history_candidate）：`candidate_decision.HistoryCandidateDecision`，
  模块文件 = `experiments/stage3_candidate/candidate_decision.py` ✅
- 候选/冻结指纹逐项一致、模型先验与冻结规格一致、`provenance_all_match = True` ✅
- 决策器限值 `max_followups=12 / max_followup_time_s=600.0 / margin_s=5.0` ✅

### B. 候选已脱离本地真值访问 —— 通过

候选 AST 静态检查通过；观测字段白名单 `['kind','p','svd']`；
接口层无真值字段命中；观测器位于接口层外层。

### C. 完整清除 / 结束证据 / 计费闭合 —— 通过

| 局 | 配置 | 完成 | 清除 | 空频道 | 未决 | 失败 | 逐频道结束证据 | T (s) | 闭合残差 (s) | 现实 (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| R1 | p4 stable | ✅ | 10 | 10 | 0 | 0 | **20/20 全决** | 8 661.10 | 0.002 | 93.1 |
| R2 | p4 history_candidate | ✅ | 10 | 10 | 0 | 0 | **20/20 全决** | **7 454.35** | 0.004 | 83.3 |
| R3 | p3 stable | ✅ | 10 | 10 | 0 | 0 | **20/20 全决** | 3 319.93 | −0.004 | 23.0 |

计费闭合按 `T = L/5 + 5M + S + 3F + 5N` 由 HTTP 明文日志独立复算，与模拟器反馈时间一致。

### D. 接线前后在相同输入观测下决策一致 —— 通过

用**同一场景、同一种子**把「HTTP 接线的候选」与「第三阶段本地环境的候选」逐动作比对：

| 项 | 结果 |
|---|---|
| HTTP 候选动作数 | **366** |
| 本地候选动作数 | **366** |
| 逐动作完全一致（kind/位置(2位小数)/频道/结果） | **是** |
| HTTP T vs 本地 T | 7 454.35 vs **7 454.341**（一致） |
| 本地候选分项 | L=26 851.71 m, M=329, S=308, F=27, N=10, 清除 10, 空频道 10 |

即：HTTP 接线**没有改变任何决策**（唯一差异是接口把坐标按 2 位小数传输，
在该场景下不产生任何决策分支差异）。

### E. P3 既有入口配置保持不变 —— 通过

与既有验收记录 `results/delivery/entry_validation_stable.json` 比较 8 个生效配置项，
**差异为空**（`is_p4=False, version=C, pruning=True, scan_at_clearance=False,
enable_2opt_head=True, enable_adaptive_radial_coverage=False,
grid=src.conservative_grid.ConservativeGrid,
decision=src.local_decision.LocalDecisionMaker`）。

源码指纹变化（**均非本次接线引起**，如实列出）：
`src/strategy_engine.py`（`d98fd366…`→`8dca0841…`）、
`src/evidence_tracker.py`（`e9d89c9a…`→`4a627a8b…`）来自更早轮次；
`src/sim_env.py`、两个 `*_frozen.py` 是**本轮新加入指纹清单**（此前未记录）；
`scripts/run_port_test.py` 的变化即本次接线本身。

---

## 4. 候选在 HTTP 局中的运行统计（R2）

| 项 | 值 |
|---|---|
| 用上模型的决策 | **26** |
| 整体回退决策 | **0** |
| 逐调用回退 | **0** |
| 模型打分调用 | 4 370 |
| 创建的假言集 | 10 个 |
| 改变动作类型 | 0 |
| 改变补测点 | 11 |
| no_signal 总次数 | 306 |
| 其中发现后补测 | 3 |
| 其中"网格未收缩" | 3 |
| 其中"网格收缩" | **0**（再次确认 P4 下 no_signal 从不裁剪网格） |

假言集更新示例（channel 9）：`n_obs=2 → 512 个存活`，`n_obs=3 → 296 个（剔除 216）`
—— 观测确实在收窄相容假言集。

---

## 5. 阻塞与限制

1. **无阻塞项**：`history_candidate` 已可由 HTTP 入口运行，且 5 项验收全部通过。
2. **环境级风险（非候选问题）**：本工作区会周期性把已跟踪文件恢复为 HEAD。
   本轮已用「幂等补丁 + 每次运行前重放 + 单独导出 patch」兜住；
   若在用户自己的检出中一次性 `git apply` 该 patch，则不存在此风险。
3. **本验收只用了一个场景**（P4/10 源/seed 9501）。这是**接线验收**，
   不是性能测试；不据此宣称性能收益（性能证据见第三阶段 12 局配对）。
4. **未启用候选为默认**：`--profile` 默认仍为 `stable`。
5. 未追加种子、未启动官方测试、未调用官方模拟器。

---

## 6. 复现

```powershell
# 1) 应用接线（幂等）
python scratch/apply_port_wiring.py

# 2) 完整验收（自动跑 R1/R2/R3 并逐项核对）
python experiments/stage3_candidate/run_http_acceptance.py

# 3) 单独跑候选档位
python scripts/run_port_test.py --port 14027 --prob p4 --version C --profile history_candidate `
    --sources 10 --mock_seed 9501 --session_dir results/delivery/http_sessions
```

| 交付物 | 内容 |
|---|---|
| `results/delivery/run_port_test_wiring.patch` | 必要源码差异（唯一被改的既有文件） |
| `scratch/apply_port_wiring.py` | 幂等补丁脚本 |
| `results/delivery/http_acceptance_R1_stable_p4.log` | 第 1 局 HTTP 验收日志（stable） |
| `results/delivery/http_acceptance_R2_history_candidate_p4.log` | 第 2 局 HTTP 验收日志（候选） |
| `results/delivery/http_acceptance_R3_stable_p3.log` | P3 入口不变性核对日志 |
| `results/delivery/http_acceptance_summary.json` | 5 项验收的机器可读结论 |
| `results/delivery/http_sessions/session_*.json` | 每局独立会话文件（完成状态/结束证据/计费/回退/生效配置） |
| `experiments/stage3_candidate/wiring.py` | 接线助手（指纹核对 / 真值隔离检查 / 复用候选） |
| `experiments/stage3_candidate/run_http_acceptance.py` | 验收 runner |
