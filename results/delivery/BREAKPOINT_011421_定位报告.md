# 011421 会话「无推进」定位报告

> **结论限定（更新后的正式口径，2026-09-13 修订）**
>
> 1. **服务器没有新增被接受动作**（明文计数：`measure_accepted_count = 232`，与客户端 232 条完全相等）。
> 2. **本地严格回放能越过断点**（279/279 逐条核对无分歧，并产出下一动作 `/measure` ch16 @(-112.71,-126.36)）。
> 3. **历史根因未确定。**
>
> “通信失败后客户端退出” **保留为假设**，不是结论。
> 该次运行的**控制台输出/退出码未能找到**——这是**已明确的证据缺失**。
> 因此**不继续宣称已排除所有策略或运行问题**：只能确认"在本地可复现范围内，
> 未能在断点处复现停滞"，不能据此推定为通信问题已定案。

> 范围：只定位 `http_session_20260913_011421_202623001546.jsonl` 断点后的停止阶段与原因。
> 未优化策略、未调用官方模拟器、未增加随机案例；未降低补测上限、未放弃目标、未放宽结束判据。

---

## 一、已确认事实（均有直接证据）

### 1. 客户端侧（原始日志）

| 项 | 值 |
|---|---|
| 日志 | `results/audit_logs/http_session_20260913_011421_202623001546.jsonl`（279 行，最后写入 01:15:22） |
| 动作构成 | `/enter` 1 + `/measure` 232 + `/clear` 46（成功 3 / 失败 43），**无 `/exit`** |
| 首条 `/enter` | 客户端墙钟 1789233261.522（本地 **01:14:21.522**） |
| 末条（断点） | `measure-000279`，ch16，位置(-105.16,-226.07)，`accepted=true`，`no_signal`，`virtual_time_s=4126.594830`（本地 **01:15:22.462**） |
| 会话内活动跨度 | **60.9 s** |

### 2. 服务器侧（官方模拟器明文记录，只读）

`JammersSimulatorData/practice-statistics-queue.sqlite3`（明文 SQLite，复制副本后查询，未连接模拟器）
中该 run 的行（`practice_run_no = 374517967544758826`，`case_code = KKVX-9XQV-MMHX-W5PC`）：

| 字段 | 值 | 与客户端交叉核对 |
|---|---|---|
| `measure_accepted_count` | **232** | = 客户端 `/measure` 条数 **232** ✓ |
| `clear_failure_count` | 43 | = 客户端失败清除 43 ✓ |
| `cleared_jammer_count` | 3 | = 客户端成功清除 3 ✓ |
| `virtual_time_us` | 4126594830 | = 客户端末条 `4126.594830` ✓ |
| `channel_switch_count` | 207 | — |
| `entered` | 1 | — |
| **`end_reason`** | **`manual_abort_running`** | 服务器把它记作"运行中被人工中止"（对照：同批 106/108 号 run 均为 `user_exit`） |
| `program_run_duration_ms` | **473233**（473.2 s） | ≈ 窗口全程，服务器**未感知客户端消失** |

`practice-p4-374517967544758826-KKVX-9XQV-MMHX-W5PC.result.json`（明文）：

```
window_started_at_utc = 2026-09-12T17:14:20.785Z   → 本地 01:14:20.785（客户端 /enter 早 0.7 s，吻合）
ended_at_utc          = 2026-09-12T17:22:14.702Z   → 本地 01:22:14.702
jammer_count = 12（全向 2 + 定向 10）
```

**推论 1（强证据）**：末条响应之后 **412 s** 内，服务器**再未接受任何动作**；
窗口一直开着，直到 **01:22:14 被人工中止**。下一个客户端会话在 **01:22:30** 启动（16 s 后）。

### 3. 客户端日志语义（代码事实）

`HttpSimDriver._post_with_retry`（修改前版本）：
- **任何 HTTP 200**（不论 `accepted` 真假）都会写日志；
- 非 200 与传输异常**不写日志**，但会重试，共 `max_retries=3`、`timeout=10 s`、间隔 `sleep(0.5)`；
- 重试耗尽 → `raise RuntimeError("HTTP 请求失败: …")`，**且不写任何日志**。

⇒ "会话日志停在 #279" 与 "客户端在 HTTP 层失败后退出" **在事后完全无法区分**（这正是本轮需要跨侧取证的根因）。

### 4. 耗时归属（墙钟 vs 虚拟钟）

最后 4 条的相邻墙钟间隔为 **6.265 / 5.567 / 5.516 / 5.221 s**；其余全部间隔中位 **0.015 s**。
HTTP 往返本身仅 **0.015–0.05 s**（响应里 `real_timestamp_ms` 与客户端 `timestamp` 之差）。

### 5. 本地回放（严格核对，零分歧）

用**真实引擎**（`is_p4=True, version="C"` + 冻结决策器/网格）与一个回放驱动重放全部观测，
**逐条核对请求类型 / 频道 / 坐标(2位小数)**：

| 结果 | 值 |
|---|---|
| 回放条数 | **279 / 279**，**首次分歧：无** |
| 结局 | **已越过断点** |
| 引擎在记录用尽后要求的下一动作 | **`/measure`，channel 16，位置 (-112.71, -126.36)** |
| 决策耗时 | 21 次决策共 66.91 s，单次最大 7.46 s；ch16 五次决策 = 7.459 / 6.244 / 6.265 / 5.949 / **5.573** s |
| `build_clear_plan` | 3 584 次调用共 62.05 s，单次最大 0.26 s；10 941 单元时均 230 ms；`plan_len` ≈ 120–123 |

**推论 2（强证据）**：断点后客户端**并未卡在自己的逻辑里** —— 同一状态可复现，
且本地在 **5.573 s** 内算出了下一条动作。日志里的 5–6 s 间隔与本地决策耗时**吻合**，
因此那些间隔是**本地决策计算**（P4 盲补测的候选打分 + 清除计划构造），不是通信等待。

### 6. 各组件版本可得性（对应工作边界 1）

| 文件 | 状态 | 结论 |
|---|---|---|
| `local_decision_frozen.py` | tracked & **clean**，mtime 9/12 16:53 > 会话前 | 当时内容 = 现在，`6d26e61de9a25fd4` |
| `conservative_grid_frozen.py` | tracked & clean，mtime 9/12 16:52 | `778af8fd986a79b6` |
| `src/strategy_engine.py` | tracked & clean，mtime 9/12 16:55 | `8dca0841ba7c45de` |
| `src/evidence_tracker.py` | tracked & clean，mtime 9/12 17:49 | `4a627a8bb8a236a1` |
| `src/client_runner.py` | tracked & clean，mtime 9/13 00:07（会话前） | 当时为 `e4e6ba0f160d9b94`（未含本轮诊断） |
| `scripts/run_port_test.py` | **dirty**（现为接线版），且该文件存在被回退现象 | **当时版本不可判定**：日志未留配置快照。<br>但 `stable` 档位下入口只影响 profile/mode/session-dir，**不影响**上表策略组件与生效配置；故行为相关指纹**可确认**，入口指纹**不可确认** |

### 7. 旁证：当时工作区存在并发负载

同工作区另一条工作流在窗口期内持续写文件：
`p4explore/deliver/evidence_*.jsonl` 01:13:26 / 01:13:27 / 01:14:02 / 01:14:02 / 01:14:38，
`p4explore/deliver/robot_p4.py` **01:14:21**（= 本会话 driver 构造时刻），
`README_使用说明.md` **01:15:43**。⇒ 当时的机器有并发负载。

### 8. 无法读取的部分（硬边界）

官方模拟器的行为日志 `.jlog` / `.psum` 载荷为 **gzip + AES-256-GCM（RSA-OAEP 包装 DEK）加密**，
信封内只有元数据，**无法读出服务器侧逐动作清单**。
因此"服务器是否曾收到一条我们没记下的请求"不能用服务器日志直接证实，
只能用上面第 2 节的**明文计数**（232）反证：**服务器从未接受第 280 条动作**。

---

## 二、最后状态 / 首次分歧 / 阻塞位置

| 项 | 结论 |
|---|---|
| 最后状态 | 客户端已完成第 279 条响应的处理，并**已经算出下一条动作**（`/measure` ch16 @(-112.71,-126.36)），停在**"准备/等待该请求的 HTTP 往返"**这一阶段 |
| 首次分歧 | **无**：本地回放 279/279 与原始日志逐条一致（类型/频道/坐标） |
| 阻塞位置 | **不在**局部决策、清除计划构造、调度或下一请求准备（这些均已跑通，得出具体下一动作）；<br>**指向 HTTP 发送/响应环节**：该请求**从未取得任何 HTTP 200**（服务器侧计数证明未被接受） |

---

## 三、根因证据 / 仍缺少的最小证据

### 已成立的根因链（**假设**，证据支持但未定案）

1. 决策阶段正常：本地可复现并产出下一动作（推论 2）。
2. 第 280 条请求**没有产生任何 HTTP 200**：服务器明文计数 `measure_accepted_count = 232` 与客户端 232 条完全相等（第 2 节）；
   而按第 3 节的日志语义，**任何 200 都会被记下** —— 所以既无 200、也无记录。
3. HTTP 层的等待是**有界**的：`3 × timeout(10 s) + 2 × 0.5 s ≈ 31 s` 必抛 `RuntimeError`。
   因此 **"进程仍存活却静默 412 s" 与 HTTP 层不符**。
4. 服务器窗口在客户端静默后仍持续 412 s，且 `end_reason = manual_abort_running`
   （同批其它 run 都是 `user_exit`）⇒ 服务器**没有客户端死亡检测**，它把整个窗口时长记为 run 时长。

**假设（保留，未定案）**：第 280 条 `POST /measure` 在传输层失败（500/断连/超时），
3 次尝试均未取得 200 → 客户端抛 `RuntimeError` 退出（约在 01:15:23–01:15:54 之间）；
操作者等待后在 **01:22:14 手动停止模拟器**，服务器记为 `manual_abort_running`。

### 证据边界（不得越界宣称）

- **可确认**：在本地严格回放的条件下，断点处**不出现停滞**；且断点之后的服务器侧无新增被接受动作。
- **不可确认 / 不能宣称**：
  - 不能宣称"已排除所有策略或运行问题"——缺少该次运行的控制台输出与退出码，
    因而无法排除"client 被外部终止"或"存在远超本地 5.6 s 的偶发长计算"等可能；
  - 不能宣称"通信失败即根因"——这只是**最符合现有计数证据的假设**。
- 因此本轮将其**归档为原因未确定**；除非取得新证据（控制台输出/退出码/服务器侧 429-5xx 记录），否则不再推进该归因。

### 仍缺少的最小证据（决定性）

**该次运行客户端的控制台输出 / 退出码**。具体判据：
- 若出现 3 条 `[RETRY] …` + `RuntimeError: HTTP 请求失败: /measure` ⇒ **传输层失败导致退出**（与推断一致，可直接结案）；
- 若控制台完全安静、进程仍在 ⇒ 说明是**被外部终止或存在远超 5.6 s 的计算**，需要另找原因。

第二顺位证据（若能取到）：
- 该进程的退出码 / Windows 事件日志中的进程终止记录；
- 官方模拟器侧是否有 429/5xx 的记录（其 `.jlog` 加密，不可读）。

### 更正：此前对 §5.3 重试 id 规则的判断有误

本报告早先版本曾把"非 200（含 429/5xx）重试复用原 request_id"称为协议偏差。
**该判断应更正**：那一条来自二手转述（另一份脚本的注释），**不是附件原文**。
核对附件2 §5.3 原文后，实际规则是：

> 每个新动作必须使用新的 request_id。**只有在网络超时、连接中断等情况下重试完全相同的动作时，
> 才复用原请求内容和原 request_id。** 同一ID、同一内容返回第一次的完整响应，
> 不重复移动、检测、清除、退出或推进时间；**同一ID改动路径、位置、频道等内容返回 HTTP 409。**
> 结构错误、未知字段以及 arena_id、robot_id 不匹配**不占用该 ID**，修正请求后可以复用。

即：**"重试完全相同动作时复用原 id"恰恰是唯一被允许（也是唯一安全）的复用场景**——
因为幂等键保证"至多执行一次"。若在结果不明的重试中改用新 id，反而会导致**重复执行/重复计费**。
因此原实现"重试复用原 id"是**正确**的；本轮把"每次重试换新 id"或"所有错误一律重试"
两种做法都明确排除（见第四节）。

---

## 四、必要修复差异（按附件2 §5.3 的错误处理与幂等性）与定向测试

> **定性说明：本节改动是"HTTP 错误处理与幂等性"的协议对齐，**
> **不得表述为"011421 根因已修复"**——011421 的历史根因仍为**未确定**（缺控制台证据）。

### 4.1 §5.3/§12 逐条核对结果

| 附件要求 | 改前 | 改后 |
|---|---|---|
| 每个**新动作**使用新的 request_id | ✓ 已合规 | ✓ 不变 |
| 只有重试**完全相同**动作时才复用原 id 与原内容 | ✓ 已合规 | ✓ 不变（且**未**改成"每次重试换新 id"） |
| 同一 id 改动内容 → 409；**不得靠换 id 掩盖冲突** | 409 被当作普通非 200，重试 3 次后报"HTTP 请求失败" | **409/400/404/405/413/415 立即失败、不重试、不换 id**，并给出各状态码含义 |
| 429/500 可退避重试 | 与非 200 混同 | **单独分类为可重试**，复用原 id 与原内容（幂等保护下不会重复执行） |
| 禁止"所有错误无限重试" | 上限 3 次 | ✓ 上限 3 次不变（仅可重试类会重试） |
| **同时检查 HTTP 状态和 accepted** | ✓ 两处都查 | ✓ 抽出 `_require_accepted()` 统一强制，`/exit` 也检查并告警 |
| `accepted=false` 表示动作未生效；`virtual_time_s=0` **不是**当前虚拟时刻 | 直接抛错（未泄漏） | ✓ 保留抛错语义，并在异常信息中显式声明"0 不覆盖时钟/位置/频道" |
| 响应体异常 / 无法形成 HTTP 响应（连不上） | 200 非 JSON 会抛未分类异常 | 200 但非 JSON → 归类为 `fatal_status`（不当作成功）；连接被关闭 → `transport_error` 复用原 id 重试 |
| 重试耗尽须留下异常与未完成状态 | 抛 `RuntimeError`，**不落盘任何未完成状态**，进程退出码非零但无记录 | 写 `retry_exhausted` 诊断；入口落盘 `completion_status=ABORTED_HTTP_NO_COMPLETION`、`completed_successfully=false`，**退出码 3**，并打印"运行未完成" |

**另发现、且已在后续单独一轮修正（见 `results/delivery/REAL_BUDGET_修正与定向验收.md`）**：
`src/strategy_engine.py` 取现实预算时**优先用 `max_real_duration_s`**，
而附件2 §12 要求"使用 /enter 返回的 `remaining_real_duration_s` 控制现实运行时间，
不要固定假定有 1200 秒"。在 011421 那次两值均为 1200，**对本会话无实际影响**；
若某次 `remaining < max`，修正前会超时运行。
该取值问题已在下轮**单独修正并定向验收**（单调时钟、固定截止点、截止后不再派发），
**该修正与 011421 的历史根因无关，不得据此宣称"011421 根因已修复"**。

### 4.2 差异清单

| 文件 | 变化 |
|---|---|
| `src/client_runner.py` | 新增 `HttpActionError`（带 `kind/status_code/attempts`）/ `_require_accepted()` / `STATUS_MEANING`；`_post_with_retry` 按 §5.3 分类（可重试 / 确定性 / 未列出）；`/exit` 检查 accepted；`audit_http_action_log` 对 `response:null` 健壮化。**正常成功路径的请求内容、顺序、次数完全不变** |
| `scripts/run_port_test.py` | 新增"运行未完成"分支：捕获异常 → 打印分类信息 → 落盘未完成会话文件 → 退出码 3。**正常完成路径不变** |
| 发布包 | 重建 `release/p4_history_candidate_v1/`，指纹刷新（见 4.4） |

### 4.3 定向测试结果（本地 stub / 本地 mock，**未接触官方端口**）

| 编号 | 场景 | 结果 |
|---|---|---|
| **T1** | 服务端**已执行但响应丢失** | 服务端执行 **1** 次、计费 **1** 次（5.0 s）；客户端用**同一 id**（`measure-000002`）重试，服务端幂等回放；客户端计账 **measure=1**、最终虚拟时间 **5.0 s** —— **通过** |
| **T2** | HTTP 200 且 `accepted=false` | 驱动层抛 `HttpActionError(kind=rejected)`；该动作**不计账**（measure=0）；真实引擎状态保持 `virtual_time_s=0.0`、`cur_pos=(0.0,0.0)`、`cur_channel=1` —— **0 未覆盖任何业务状态** —— **通过** |
| **T2b**（后续轮补强） | 同上，但**先建立非平凡状态**再拒绝 | 拒绝前 `virtual_time_s=15.0`（非 0）、`cur_pos=(990.0,0.0)`（非原点）、`cur_channel=3`（非 1）；第 4 次 `/measure` 返回 200 + `accepted=false` + `virtual_time_s=0` ⇒ 三者**逐项保持原值**，生效测量计账 **3**、拒绝动作计 **0** —— **通过** |
| **T3** | 结构错误(400) 与 409 冲突 | 两者均 **1 次尝试、不重试**、`kind=fatal_status`、状态码分别为 400/409；服务端只看到各动作**各自唯一**的 request_id（**未因错误另换 id**）；409 未被当作成功、未被换 id 掩盖 —— **通过** |
| **T4** | 重试耗尽 | 单元层 `kind=retry_exhausted, attempts=3`，会话日志含 3 条 `transport_error` + 1 条 `retry_exhausted`；**入口层退出码 = 3**，stdout 含"运行未完成"，未完成会话文件 `completion_status=ABORTED_HTTP_NO_COMPLETION`、`completed_successfully=false` —— **通过** |
| 复用旧测 | `verify_client_diagnostics.py`（500 + 断连 + 行为不变） | A 诊断有效性**通过**；B 既有场景 `stable/P4/10源/seed 9501` 与改前**逐项一致**（T 8661.10、L 30840.5→30840.51、M/S/F/N 349/308/130/10）—— **通过** |
| 不变性 | 011421 断点回放（改后重跑） | **279/279 无分歧**，且**越过断点的下一动作完全相同**：`/measure` ch16 @(-112.71,-126.36) ⇒ **正常动作序列未变** |

结果文件：`results/delivery/http_semantics_tests.json` / `.log`、
`results/delivery/client_diagnostics_acceptance.json` / `.log`。

### 4.4 更新后的发布指纹（`release/p4_history_candidate_v1/`）

下表为**本轮（HTTP 错误处理与幂等性）结束时**的指纹快照。后续单独一轮按附件2 §12 修正了
现实预算取值，使 `src/strategy_engine.py` 与发布入口再次变更（新值见
`results/delivery/REAL_BUDGET_修正与定向验收.md`）；本报告的结论不依赖那两个文件的新旧。

| 文件 | sha256(前16) | 相对上一版 |
|---|---|---|
| `src/client_runner.py` | `fd03f0e4c21f571c` | **变更**（HTTP 层修复；后续轮未再改） |
| `run_port_test.py`（发布入口） | `e5fc7db9d41e50e5` | **变更**（未完成分支；后续轮增记预算字段） |
| `src/strategy_engine.py` | `8dca0841ba7c45de` | 本轮不变（预算修正属后续轮） |
| `local_decision_frozen.py` | `6d26e61de9a25fd4` | 不变 |
| `conservative_grid_frozen.py` | `778af8fd986a79b6` | 不变 |
| `candidate/candidate_decision.py` | `811ed39875813301` | 不变（与验收版逐字节一致） |
| `candidate/predictor.py` | `0fa1753454775cbd` | 不变 |
| `candidate/model.py` | `ada6c0069ee9b426` | 不变 |
| `candidate/observer.py` | `a58d1931ff3334fe` | 不变 |

发布包自检（从 `C:\` 运行 `check_release.py`）：**全部通过**
（导入路径全在包内、候选与 upstream 逐字节一致、模型参数一致、真值隔离通过、
official 模式无服务时退出码 2 且不自动拉起 Mock、拒绝场景参数）。

---

## 五、复现与证据清单

```powershell
python scratch/analyze_011421_session.py      # 客户端日志：动作/频道/时间线
python scratch/analyze_011421_timing.py       # 墙钟间隔、ch16 检测与补测链
python scratch/replay_011421_breakpoint.py    # 本地回放（严格核对 + 越过断点 + 计时 + 停滞栈）
python scratch/list_sim_runs.py               # 服务器侧明文统计库（end_reason 对照）
python scratch/read_sim_behavior_log.py <jlog># 服务器侧日志信封（载荷加密，不可读）
python scratch/verify_http_semantics.py        # §5.3 错误分类与幂等性定向测试 T1–T4 + T2b（本地 stub/mock）
python scratch/verify_budget_remaining.py      # §12 现实预算取值定向测试 T1–T3（本地 stub + 可控时钟）
python scratch/verify_client_diagnostics.py   # 既有诊断测 A/B（诊断有效性 + 行为不变）
```

| 交付物 | 内容 |
|---|---|
| `results/delivery/breakpoint_011421_replay.json` / `.log` | 回放结论、越过断点的下一动作、决策与计划计时、停滞栈 |
| `results/delivery/client_runner_http_semantics.patch` | `src/client_runner.py` 完整差异（诊断 + §5.3 错误分类/幂等性，14 010 B） |
| `results/delivery/run_port_test_wiring.patch` | `scripts/run_port_test.py` 完整差异（接线 + 未完成分支，28 166 B） |
| `results/delivery/http_semantics_tests.json` / `.log` | T1–T4（重试幂等 / accepted=false / 400 与 409 / 重试耗尽）结果 |
| `results/delivery/client_diagnostics_acceptance.json` / `.log` | 既有诊断测 A/B（诊断有效性 + 行为不变）结果 |
| `results/delivery/BREAKPOINT_011421_定位报告.md` | 本报告 |
