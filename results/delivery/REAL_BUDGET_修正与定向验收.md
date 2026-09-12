# 现实预算取值修正（附件2 §12）与定向验收

> **定性说明（必须保留）**：本轮只修正**现实预算取值**并补足**一次拒绝响应的状态保持测试**。
> 这**不是**"011421 根因已修复"——011421 的历史根因仍为**未确定**（缺该次运行的控制台输出/退出码）。
> 本轮未新增策略、未调用官方模拟器、未扩大基准测试；已有通信与策略验收结果**复用**，未重跑整批案例。
>
> **后续修订说明**：其后一轮按"只修 D1/D2"实施了 D1（`best_jq=None` 格式化异常）与 D2（默认运行日志移到包外），
> 因此本报告 §2/§4 中的 `src/client_runner.py = fd03f0e4c21f571c` 与入口 `= be5bd784d6d6cacf`
> 属**该轮的 r1 身份**，现行指纹已变更（新值见 `results/delivery/MINIMAL_FIXES_D1_D2.md`）。
> 本报告的结论与验收数据不受影响；历史运行仍以 r1 指纹为准。


---

## 一、修正依据（附件2 §12 原文）

> 机器狗成功调用 `/enter` 后开始计算最长 20 分钟的程序运行时间。实际现实截止时刻是
> "25 分钟窗口截止"和"/enter 成功后 20 分钟"两者中较早的时刻。`/enter` 成功响应中的
> **`remaining_real_duration_s`** 是本局实际还能使用的完整现实时间秒数，**范围为 0 至 1200**；
> 机器狗程序**应使用该值，不应固定假定每次都有 1200 秒**。
>
> 使用 `/enter` 返回的 `remaining_real_duration_s` 控制现实运行时间，不要固定假定有 1200 秒。

### 修正前（缺陷）

```python
self.max_real_duration_s = float(
    enter_res.get("max_real_duration_s",
                  enter_res.get("remaining_real_duration_s", 1200.0)) or 1200.0
)
...
if (time.time() - self.start_real_time) >= self.max_real_duration_s:   # 以配置上限当预算
```

1. **优先取 `max_real_duration_s`（配置上限）**，`remaining_real_duration_s` 只在缺失时才被使用
   ⇒ 若本局实际只剩 60 秒，程序仍按 1200 秒安排，**会超时运行**；
2. 用**墙钟** `time.time()` 计量，系统时间调整会影响预算判定；
3. `.get(...) or 1200.0` 会把 `remaining_real_duration_s = 0`（合法取值）**误判成 1200**。

### 修正后（本轮）

| 目标 | 实现 |
|---|---|
| 本局可用现实时间 = `/enter.remaining_real_duration_s` | `real_budget_s = max(0, min(remaining, max_real_duration_s))` |
| `max_real_duration_s` 仅作**配置上限**，不覆盖实际剩余 | 保留为独立字段 `max_real_duration_s`（报告/审计用），**不再充当预算** |
| 不固定假设 1200 秒 | 缺失时退回配置上限（再缺失退回 1200），显式 `0` 视为**预算立即耗尽** |
| 使用**单调时钟** | 预算计量改用 `time.monotonic()`（`self.monotonic_clock`，可注入） |
| 通信重试**不得重新开始或延长**预算 | 起点 `/enter` 成功时**固定一次**，并记录绝对截止点 `real_deadline_monotonic = start + real_budget_s`；重试期间时间照常流逝 |
| 沿用现有预算退出流程 | 仍走 `terminal_reason = REAL_BUDGET_EXHAUSTED` → `completion_status = SAFE_EXIT_BUDGET` |
| 预算不足且未完成**不得标记 COMPLETED** | `completed_successfully = false`（`SAFE_EXIT_BUDGET` / `INCOMPLETE`，取决于是否有显式失败目标） |
| 截止后**不再派发**新的测量/清除动作 | ① 每一轮循环前的检查（原有）；② **新增**原点首扫前的检查；③ **新增**逐频道扫描中的检查（三种版本 B / C_greedy / C_openroute 全覆盖） |

---

## 二、最小差异

| 文件 | 变化 | 指纹(sha256 前16) |
|---|---|---|
| `src/strategy_engine.py` | 现实预算取值/时钟/截止点 + 三处派发前预算检查 + 摘要新增预算字段（**+60 / −15 行**；引擎在上一轮未改动，故即本轮最小差异） | `8dca0841ba7c45de` → **`f4f41a97bd24d289`** |
| `scripts/run_port_test.py` | 会话文件 `completion` 增记 `real_budget_s` / `real_budget_source` / `real_budget_elapsed_monotonic_s` / `max_real_duration_s`（完成与中止两条路径，**+8 行**） | `e5fc7db9d41e50e5` → **`be5bd784d6d6cacf`** |
| `release/build_release_v1.py` | 发布说明补充现实预算一节 | — |

差异文件：

- `results/delivery/strategy_engine_budget.patch` —— 引擎本轮全部差异（8 885 B）
- `results/delivery/run_port_test_budget_fields.patch` —— 入口**本轮仅 8 行**差异（1 603 B）
- `results/delivery/run_port_test_wiring.patch` —— 入口相对 HEAD 的累计差异（接线上下文，28 848 B）

> 上一轮入口版本由当前文件**反推**得到（`scratch/_prev_entry/make_prev_entry.py`），
> 并经发布构建器验证：反推版本生成的发布入口指纹 = `e5fc7db9d41e50e5`（与上一轮完全一致），
> 当前版本 = `5763e3017550edf4` ⇒ 反推逐字节正确，上表"本轮仅 8 行"可核验。

**未改动**：P3、P4 覆盖布局、扫描规则、全局调度、候选补点、清除计划、结束判据、
`local_decision_frozen.py` / `conservative_grid_frozen.py` / `candidate/*`（发布包内与验收版仍逐字节一致）。

---

## 三、定向验收结果（本地 stub + 可控时钟；**未接触官方端口**）

### T1 `max_real_duration_s=1200`、`remaining_real_duration_s=60`：按 60 秒预算处理

| 检查 | 结果 |
|---|---|
| 本局现实预算 | **60.0 s**（取自 `remaining_real_duration_s`） |
| 配置上限 | **1200.0 s**（如实保留，但不覆盖实际剩余） |
| 绝对截止点 | `start + 60.0 s`（固定一次） |
| 派发时刻（相对预算起点） | 0 / 10 / 20 / 30 / 40 / 50 s，共 **6** 次测量 |
| 截止时刻及之后仍派发的动作 | **0** |
| 测试真实墙钟耗时 | **0.000 s** ⇒ **未真实等待 60 秒**（可控时钟） |
| 完成状态 | `SAFE_EXIT_BUDGET`，`completed_successfully=false`，`terminal_reason=REAL_BUDGET_EXHAUSTED` |
| 判定 | **通过** |

### T2 截止后不再派发；完成状态保持真实

| 情形 | 结果 |
|---|---|
| `remaining=0`（合法取值） | 派发 measure=**0**、clear=**0**（含原点首扫亦不派发）；`SAFE_EXIT_BUDGET`，`completed_successfully=false` |
| `remaining=60` 跑到底 | 截止及之后派发动作 **0**；`SAFE_EXIT_BUDGET`，**未标记 COMPLETED** |
| 判定 | **通过** |

### T3 `remaining=1200` 时口径一致；通信重试只消耗预算

| 检查 | 结果 |
|---|---|
| `remaining=1200` / `max=1200` | 预算 = **1200.0 s**，上限 = 1200.0 s ⇒ **与修正前口径一致**；该预算下派发 120 次测量（远超 6，证明按 1200 放宽） |
| 模拟重试（第 3 次动作内部耗时 40 s） | 派发 **3** 次即停；**预算未被延长** |
| 截止点 | 全部预算检查中**恒为** `start+60.0`（固定的绝对截止点） |
| 判定 | **通过** |

### T4（补强）拒绝响应的状态保持 —— `verify_http_semantics.py::T2b`

先由 3 次**真实生效**的测量建立非平凡状态，再让第 4 次测量返回
**HTTP 200 + `accepted=false` + `virtual_time_s=0`**：

| 检查 | 拒绝前 | 拒绝后 |
|---|---|---|
| `virtual_time_s` | **15.0**（非 0） | **15.0** —— 未被 `0` 覆盖 |
| `cur_pos` | **(990.0, 0.0)**（非原点） | **(990.0, 0.0)** —— 保持原值 |
| `cur_channel` | **3**（非 1） | **3** —— 未被重置为 1 |
| 计账 | — | 生效测量 = **3**，**拒绝动作计 0**；计账时钟最终值 = **15.0**（未回退为 0） |

驱动层抛 `HttpActionError(kind='rejected')`；**判定：通过**。

### 复用既有验收（未新增案例，未重跑整批）

| 复用项 | 结果 |
|---|---|
| `verify_client_diagnostics.py` A（500 + 断连的诊断有效性） | **通过**（3 次尝试、同一 `request_id`、计账 0；首次错误分类为 `retryable_status(500)`） |
| `verify_client_diagnostics.py` B（既有场景 `stable / P4 / 10 源 / seed 9501` 本地 mock 一局） | **逐项一致**：T 8661.1、L 30840.51、M/S/F/N = 349/308/130/10 ⇒ 1200 秒预算路径**行为不变** |
| 同一既有场景 + `--session_dir`（验证预算字段确实落进交付会话文件） | `completion_status=COMPLETED`，`real_budget_s=1200.0`，`real_budget_source=min(/enter.remaining_real_duration_s, /enter.max_real_duration_s)`，`real_budget_elapsed_monotonic_s=180.94`，`max_real_duration_s=1200.0`；T/L 仍为 8661.1 / 30840.51 |
| 中止路径会话文件（`scratch/_http_tests/t4_sessions/`） | `ABORTED_HTTP_NO_COMPLETION` 下同样记录 `real_budget_s` / `max_real_duration_s` |
| `verify_http_semantics.py` T1/T2/T2b/T3/T4 | **全部通过** |

结果文件：`results/delivery/budget_remaining_tests.json` / `.log`、
`results/delivery/http_semantics_tests.json` / `.log`、
`results/delivery/client_diagnostics_acceptance.json` / `.log`。

---

## 四、发布指纹（`release/p4_history_candidate_v1/`，已重建；**旧包保留**）

| 文件 | 本版 | 上一版 |
|---|---|---|
| `src/strategy_engine.py` | **`f4f41a97bd24d289`** | `8dca0841ba7c45de` |
| `src/client_runner.py` | `fd03f0e4c21f571c` | `fd03f0e4c21f571c` |
| `run_port_test.py`（发布入口） | **`5763e3017550edf4`** | `e5fc7db9d41e50e5` |
| `src/sim_env.py`（本地参考环境） | `ffa4f33aa5f943de` | 同 |
| `FREEZE.json` | `6e8efb37972ff60b` | 同（只覆盖冻结组件与 candidate） |
| `candidate/candidate_decision.py` | `811ed39875813301` | 同（与验收版逐字节一致） |
| `candidate/predictor.py` | `0fa1753454775cbd` | 同 |
| `candidate/model.py` | `ada6c0069ee9b426` | 同 |
| `candidate/observer.py` | `a58d1931ff3334fe` | 同 |
| `local_decision_frozen.py` | `6d26e61de9a25fd4` | 同 |
| `conservative_grid_frozen.py` | `778af8fd986a79b6` | 同 |

- 发布包自检（从 `C:\` 运行 `check_release.py`）：**全部通过**（依赖全在包内、候选与 upstream 逐字节一致、
  模型参数一致、真值隔离通过、official 模式无服务时退出码 2 且不自动拉起 Mock、拒绝场景参数）。
- **旧包已保留**：`release/_archive/p4_history_candidate_v1_pre_budget_20260913/`
  （其中 `src/strategy_engine.py = 8dca0841ba7c45de`、`src/client_runner.py = fd03f0e4c21f571c`、
  `run_port_test.py = e5fc7db9d41e50e5`、`FREEZE.json = 6e8efb37972ff60b`）。

---

## 五、边界与未做事项

- **不将本轮修正表述为"011421 根因已修复"**；011421 的根因仍归档为"未确定"。
- 未调用官方模拟器（`127.0.0.1:2026` 上的 `jammers-simulator.exe` 自 2026-09-12 10:29:40 起持续监听，
  本轮**一次都没有连接**）；未新增随机案例；未改动策略与结束判据；未降低补测上限、未放弃目标。
- **已知但本轮未改（如实上报）**：`service_found_target` 内因预算耗尽而 `_fail_channel` 时
  **不写入 `terminal_reason`**（该路径下通道已被显式记 FAILED，完成状态为 `INCOMPLETE`，**不会记为 COMPLETED**）；
  若需统一表述为"预算退出"，可在后续轮次单独处理。
- 本包性能数字仍为第三阶段**本地参考环境原始记录**，**不是官方成绩**。
