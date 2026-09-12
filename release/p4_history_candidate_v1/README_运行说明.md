# P4 history_candidate 独立发布包 v1 · 修订 r2

## 这是什么

问题四（P4）**历史接收模型候选版**的独立可运行包。已把已验收的 HTTP 入口接线**固化进源码**：
正常启动**不修改自身源码**、**不执行 git apply**、**不依赖任何补丁重放**，也不依赖原实验工作区路径。

默认档位仍为 `stable`；P3 与所有策略参数未改动。

## 本版修订（相对 12 局配对验收版 r1）

| 编号 | 修订 | 影响面 |
|---|---|---|
| **D1** | 修复 `best_jq=None`（全部候选都被判不可表示）时 `reason` 文本对 `None` 做 `:.1f` 格式化抛 `TypeError`：改为按 `jq_txt` 取值。**动作类型、位置与清除计划完全不变**；冻结基类与由构建期生成器再生的候选同步携带该修复 | 只影响该异常分支的日志文案 |
| **D2** | 默认运行产物（明文 HTTP 日志 / 审计 / 会话文件）不再写在包内 `results/`，改由包内 `runs_config.json` 指向**包外独立目录** `../p4_official_runs`；构建脚本在重建前把包内既有产物**迁出**（绝不删除/覆盖） | 只影响日志落盘位置 |

两项均为**最小修复**，不改策略、不改覆盖布局、不改扫描规则、不改结束判据；
本版与 r1 的数值行为一致（D1 只在原本会崩溃的状态下改变"是否抛异常"）。

更早的一处**协议对齐**（同属 r2）：现实预算以 `/enter` 的 `remaining_real_duration_s` 为准；
HTTP 错误处理/幂等性按附件2 §5.3 分类（`400/404/405/409/413/415` 立即失败不重试；
`429/500` 才退避重试且复用原 `request_id`；拒绝响应不当作成功）。

## 目录

| 路径 | 作用 |
|---|---|
| `run_port_test.py` | 启动入口（已固化接线；official / mock 两种模式） |
| `check_release.py` | 只读自检：导入路径 / 指纹 / 模型参数 / 真值隔离 / 启动行为 / 日志目录在包外 |
| `runs_config.json` | **运行产物根目录**（指向包外独立目录，重建不会删除历史记录） |
| `FREEZE.json` | 冻结声明 + upstream（第三阶段验收版）校验值 |
| `BUILD_INFO.json` | 版本标识 + **可运行文件**指纹（入口启动时自检，不一致即拒绝运行） |
| `MANIFEST_文件指纹.csv` | 全部文件指纹清单 |
| `src/` | 引擎、证据、环境、HTTP 客户端、本地替代 Mock 服务 |
| `local_decision_frozen.py` / `conservative_grid_frozen.py` | 冻结组件（候选决策主体的生成来源 / 基类） |
| `candidate/` | 候选实现（由构建期生成器从冻结基类生成，仅接收概率切片不同） |
| `results/` | 仅保留空骨架（历史兼容）；**实际运行产物写到 `runs_config.json` 指定的包外目录** |

## 与验收版（r1）的一致性（sha256 前 16 位）

| 文件 | 本版(r2) | r1（历史身份） |
|---|---|---|
| `candidate/candidate_decision.py` | `8be9f9df647194d8` | `811ed39875813301` |
| `candidate/predictor.py` | `0fa1753454775cbd` | `0fa1753454775cbd` |
| `candidate/model.py` | `ada6c0069ee9b426` | `ada6c0069ee9b426` |
| `candidate/observer.py` | `a58d1931ff3334fe` | `a58d1931ff3334fe` |
| `local_decision_frozen.py` | `6f9c895357149c97` | `6d26e61de9a25fd4` |
| `conservative_grid_frozen.py` | `778af8fd986a79b6` | `778af8fd986a79b6` |

> 上表右列是 **r1 的历史身份**（12 局配对验收与原官方运行所用版本），
> 其原版字节保存在 `experiments/_archive_pre_d1_20260913/`；
> 引用历史结果时必须引用右列指纹，**不得**用本版左列指纹冒充历史运行版本。

`candidate/wiring.py` 与验收版逻辑相同，仅把路径改为包内相对（因为发布包不在原目录结构中）。

## 冻结内容（本轮起不得再调）

- 假设数量 `n_hyp = 512`
- 源类型先验 `p_dir = 0.5`；半径先验 `R ~ U[1000, 1500]`；朝向先验 `u ~ U[0, 2π)`
  ——均为**建模假设**，不是题面事实
- 测向容差：继承安全网格自身的 `eps_deg`
- 条件化抽样 `pool_factor = 40`、`max_rounds = 6`
- 抽样种子 `20260912 + 131 × channel`（同一目标的半径/朝向在各次观测之间固定）
- 更新规则：用**全部历史观测**重新过滤相容假设（阳性+阴性联合解释），只做剔除
- 回退规则：假设集为空 ⇒ 预测返回 `None` ⇒ 决策器**逐字回退**冻结公式并记录原因

## 运行

官方连接与本地验收命令见 `LAUNCH_官方连接命令.md`。

## 输出（全部写在包外独立目录 `../p4_official_runs`）

- `<runs>/sessions/session_<profile>_<prob>_<时间戳>.json`
  —— 完成状态、逐频道结束证据、计费汇总（含 `T = L/5+5M+S+3F+5N` 复算）、
  模型回退统计、生效配置、源码指纹。文件名带时间戳，不覆盖前局。
- `<runs>/audit_logs/http_session_*.jsonl` —— 明文 HTTP 请求/响应（按 `request_id` 去重计账）
- `<runs>/http_action_log.jsonl` —— 最新一局的快捷日志

> 运行产物**不再写在包内**：发布包重建（删除并重写包目录）不会删除历史官方记录。
> 可用环境变量 `CUMCM_RUNS_DIR` 或命令行 `--runs_dir <目录>` 覆盖默认位置；
> 重建前构建脚本会自动把包内遗留的旧产物迁出到 `<runs>/legacy_package_results/`（不删除、不覆盖）。

## 自检

```powershell
python check_release.py
```

## 现实预算（附件2 §12）

- 本局可用现实时间取 `/enter` 返回的 **`remaining_real_duration_s`**（范围 0–1200）；
  `max_real_duration_s` 只作**配置上限**，不覆盖实际剩余时间，也不固定假定 1200 秒。
- 预算起点在 `/enter` 成功那一刻用**单调时钟**固定一次；通信重试只消耗预算，
  **不会重新开始或延长**本局预算。
- 截止后不再派发任何测量/清除动作；预算不足且未完成时如实记为
  `completion_status = SAFE_EXIT_BUDGET`（`completed_successfully = false`），**绝不标记 `COMPLETED`**。

## 边界

- 本包只实现 HTTP 客户端与本地替代服务；**不调用官方模拟器**，official 模式仅连接用户已启动的服务。
- 包内性能数字沿用第三阶段的**原始记录**（本地参考环境 12 局配对），**不是官方成绩**。
- 默认档位 `stable`；候选档位需显式 `--profile history_candidate`。
