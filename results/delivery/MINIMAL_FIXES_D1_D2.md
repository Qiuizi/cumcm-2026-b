# 最小修复记录：D1（格式化异常）与 D2（日志外置）

> **本轮范围**：算法停止扩展，**只修 D1、D2**。未调用官方模拟器、未新增随机案例、
> 未重跑整批性能测试（12 局配对验收**未重跑**）；历史实验保留**原版本身份**。
> 两项修复都不改变策略、覆盖布局、扫描规则、调度、补点与结束判据。

---

## 〇、一页速览

| 项 | 内容 |
|---|---|
| D1 | `best_jq=None` 时 `reason` 文本对 `None` 做 `:.1f` → `TypeError`；改为 `jq_txt` 取值，**动作/位置/清除计划不变**；冻结基类 + 构建期再生候选同步携带 |
| D2 | 默认运行产物（HTTP 日志 / 审计 / 会话）从包内 `results/` 移到**包外独立目录** `<release>/p4_official_runs`（由包内 `runs_config.json` 指定）；重建前自动**迁出**包内遗留产物（不删除、不覆盖） |
| D1 验证 | 5 个定向状态：正常评分 4 态修复前后**逐字段一致**；"全部候选不可表示"态修复前抛 `TypeError`、修复后返回原规则 else 分支（`clear` + `clear_plan[0]`） |
| D2 验证 | 发布包入口真实写出日志全部落在包外（包内新增 0 个文件）；**再次重建后 5 个文件内容与指纹完全不变**；142 条历史官方日志 + 15 个验收会话 + 36 个归档文件**零改动** |
| 版本 | `p4_history_candidate_v1 → r2`（r1 = 12 局配对验收版）；r1 原版字节存于 `experiments/_archive_pre_d1_20260913/` |

---

## 一、D1：`best_jq=None` 的格式化异常

### 1.1 缺陷与根因

打分循环中若**全部候选都被判不可表示**（每个候选在正接收概率下的"测向反馈"都与其克隆安全网格全局矛盾，
该候选被剔除并计入 `unrepresentable_prediction_count` / `empty_prediction_count`），
则 `best_q`、`best_jq` 始终为初值 `None`；控制流进入 else 分支后：

```python
"reason": f"direct_clear_better (J0={j0:.1f}s vs Jq={best_jq:.1f}s)"   # ← best_jq 为 None
```

`None.__format__(":.1f")` 抛 `TypeError: unsupported format string passed to NoneType.__format__`。

- 位置：候选 `candidate/candidate_decision.py:385`；**同一写法存在于冻结基类 `local_decision_frozen.py:470`**
  （候选主体由冻结源码在构建期生成，属**继承而来的缺陷**，非候选引入）。
- 补充说明：P3 路径（`src/local_decision.py`）在同位置把 `best_jq` 初始化为 `1e9`，**不会**触发该缺陷，
  因此**未改动**该文件（保持"只修 D1、D2"的最小面）。

### 1.2 修复（只动 reason 文本，不动动作）

冻结基类 `local_decision_frozen.py`：

```diff
         # 5. 门槛判决: 仅当 min J(q) + margin_s < J0 时补测
+        # 【D1 最小修复】best_jq 可能是 None（全部候选都被判不可表示 ⇒ 从未记入 best_jq）：
+        #   该情形只影响 reason 文本的格式化，**不改变动作类型、位置与清除计划**。
+        jq_txt = f"{best_jq:.1f}s" if best_jq is not None else "不可表示"
         if best_q is not None and best_jq is not None and best_jq + self.margin_s < j0:
-                "reason": f"followup_promising (Jq={best_jq:.1f}s vs J0={j0:.1f}s)",
+                "reason": f"followup_promising (Jq={jq_txt} vs J0={j0:.1f}s)",
         else:
-                "reason": f"direct_clear_better (J0={j0:.1f}s vs Jq={best_jq:.1f}s)",
+                "reason": f"direct_clear_better (J0={j0:.1f}s vs Jq={jq_txt})",
```

### 1.3 候选按构建期生成器同步再生（逐字继承）

```powershell
# 1) 修改冻结基类（唯一手工改动）
# 2) 由构建期生成器重新生成候选（只替换"接收概率"切片，其余逐字保留）
python experiments/stage3_candidate/tools/build_candidate_method.py
#    → SELFCHECK OK wrapper=True body=287 frozen=305
# 3) 刷新 stage3 冻结声明
python experiments/stage3_candidate/tools/write_freeze.py
```

再生后的候选与修复前候选的差异**只有**上述 4 行（2 行注释 + `jq_txt` 定义 + 2 处 reason 替换），
且"候选 = 冻结基类 + 仅接收概率切片"的源局部性检查仍通过：

```
[source_locality] identical_except_prediction_block = True
                  frozen_lines = 281, candidate_lines = 281, first_diff = None
                  runtime_uses_inspect_or_exec = False
```

### 1.4 定向验证（结果见 `d1_fix_verification.json` / `.log`）

| 状态 | 内容 | 修复前(old) | 修复后(new) | 判定 |
|---|---|---|---|---|
| A1 | 正常评分：候选=[远点(矛盾), 原点(可表示)]，模型可用 | `measure` pos=[0,0] Jq=493.7 plan=120 | 同左，逐字段一致 | 一致 |
| A2 | 正常评分：使用**真实候选生成器** | `measure` pos=[300,0] Jq=469.4 plan=120 | 同左，逐字段一致 | 一致 |
| A3 | 正常评分：无模型（冻结回退） | `measure` pos=[0,0] Jq=372.7 plan=120 | 同左，逐字段一致 | 一致 |
| C | 仅远点候选 + 无模型（冻结公式 `p_recv=0` ⇒ 可表示） | `clear` Jq=1403.8 | 同左，逐字段一致 | 一致 |
| **B** | **全部候选不可表示**（仅远点候选 + 模型正概率） | **抛 `TypeError`** | **`clear`**，位置=`clear_plan[0]`，`force_clear=True`，`plan_len=120`，`best_jq=None`，`reason="direct_clear_better (J0=598.8s vs Jq=不可表示)"` | **通过** |

要点：
- 状态 A1/A2/A3/C 覆盖"正常评分"的 measure 与 clear 两条分支，**修复前后决策字典逐字段相同**
  ⇒ 动作选择、位置、清除计划、J0/Jq 与计数**均无变化**；
- 状态 B 的修复后结果正是原代码 else 分支**本该返回**的值（动作类型、`clear_plan[0]`、计划长度、
  `force_clear` 全部与独立计算的 `build_clear_plan` 一致），且"不可表示"事件仍被计数（未被修复掩盖）；
- 验证用的 old 侧字节取自 `experiments/_archive_pre_d1_20260913/`（r1 原版），new 侧取自**重建后的发布包**。

> 说明：按本轮要求**未重跑**12 局配对验收（历史性能记录保持原样）；
> 已另行复核"候选 = 冻结 + 仅接收概率切片"的源局部性（§1.3），
> 且 D1 只在原本会抛异常的分支上改变"是否抛异常"，不触及任何数值路径。

---

## 二、D2：默认运行日志放到重建不会删除的独立目录

### 2.1 缺陷与根因

`release/build_release_v1.py` 以 `shutil.rmtree(RELEASE)` 重建包目录；
而客户端默认把运行产物写在 `PROJECT_ROOT/results/`（`PROJECT_ROOT` = `src/` 的上一级）。
⇒ **用发布包跑的官方对局，其明文 HTTP 日志/会话文件会在下一次重建时被一并删除**（无提示）。

### 2.2 修复（先保护，再改流程）

**第 1 步 先保护现有日志（只读清单 + 迁出）：**

- 在任何流程改动之前，用 `scratch/protect_logs_inventory.py` 对现有全部日志做**只读清单与 sha256**
  （`results/delivery/log_inventory_before_d2.json`，共 193 个文件）；
- 构建脚本新增 `protect_package_logs()`：重建前把**包内 `results/**` 全部迁出**到
  `p4_official_runs/legacy_package_results/`，同名文件改名为 `<原名>.migrated_<时间戳>`，
  **绝不删除、绝不覆盖**。

**第 2 步 默认目录改到包外（重建安全）：**

| 文件 | 改动 |
|---|---|
| `src/client_runner.py` | 新增 `resolve_runs_dir()`：解析顺序 **显式参数 > 环境变量 `CUMCM_RUNS_DIR` > 包内 `runs_config.json` > `<PROJECT_ROOT>/results`**；`HttpSimDriver(..., runs_dir=)` 据此确定 `http_action_log.jsonl` 与 `audit_logs/` 落点 |
| `scripts/run_port_test.py` | 新增 `--runs_dir`；解析 `runs_dir` 并传入驱动；启动时打印"运行产物根目录 (Runs)" |
| `release/build_release_v1.py` | 新增 `RUNS_DIR = <release>/p4_official_runs`（相对包目录 `../p4_official_runs`）与 `write_runs_config()`、`protect_package_logs()`；重建时写入包内 `runs_config.json`；README 输出章节改为包外路径；`check_release.py` 新增第 [6] 项自检 |
| 包内新增 | `runs_config.json`（指向包外目录；可用 `--runs_dir` / `CUMCM_RUNS_DIR` 覆盖） |

行为边界：
- **工作区**默认不变：`resolve_runs_dir()` 在工作区解析为 `<工作区>/results`（自检已确认），
  历史日志位置与既有脚本继续有效；
- **发布包**默认写到 `<包目录>/../p4_official_runs/{audit_logs,sessions}`，包内 `results/` 仅留空骨架。

### 2.3 定向验证（结果见 `d2_runsdir_verification.json` / `.log`）

| 检查 | 结果 |
|---|---|
| 入口真实写盘（发布包 + 本地 stub 端口，3 次重试后如实中止，退出码 3） | 新增 3 个文件**全部在包外**：`audit_logs/http_session_20260913_040231_d2test.jsonl`、`http_action_log.jsonl`、`sessions/session_stable_p4_20260913_040233.json` |
| 包内 `results/` 新增文件数 | **0**（日志确实不再落在包内） |
| **再次重建发布包**后 | 包外 5 个文件（2 个探针 + 3 个新日志）**内容与指纹全部不变**，无丢失；包内 `results/` 仍为空（无遗留可迁出） |
| 包内遗留探针（`results/audit_logs/_D2_probe_legacy_test.jsonl`） | 重建时**迁出**到 `legacy_package_results/audit_logs/`，sha256 **`f1371bd485d65929` 前后一致**（未删除、未覆盖） |
| 历史官方记录（`results/audit_logs` 142 个、`results/delivery/http_sessions` 15 个、`release/_archive` 36 个） | 逐条 sha256 **零变更、零缺失、零新增** |
| `check_release.py` 第 [6] 项 | 解析出的运行产物根目录位于包目录之外 = **True** |

> 两个探针文件是**明确标注的测试日志**（`_D2_probe_*`，内容含 `TEST LOG, NOT an official run record`），
> 不是任何官方记录；保留在包外目录中作为"重建安全"的永久回归证据。

---

## 三、版本与指纹（r1 → r2）

### 3.1 工作区（唯一手工改动 + 再生物）

| 文件 | r1（历史身份） | **r2（本版）** |
|---|---|---|
| `local_decision_frozen.py` | `6d26e61de9a25fd4` | **`6f9c895357149c97`** |
| `experiments/stage3_candidate/candidate_decision.py` | `811ed39875813301` | **`8be9f9df647194d8`** |
| `experiments/stage3_candidate/FREEZE.json` | `ea7b5923de780356` | **`299f4025f0f4eb5b`** |
| `src/client_runner.py` | `fd03f0e4c21f571c` | **`5f221dd4e8a83fad`** |
| `scripts/run_port_test.py` | `be5bd784d6d6cacf` | **`67cd0bb818c189a7`** |
| `release/build_release_v1.py` | — | **`92f7f8325dbbb7b5`** |
| `src/strategy_engine.py`（r2 内更早的预算协议对齐，非本轮） | `8dca0841ba7c45de` | `f4f41a97bd24d289`（不变） |
| `candidate/predictor.py` / `model.py` / `observer.py` | 同 r1 | `0fa1753454775cbd` / `ada6c0069ee9b426` / `a58d1931ff3334fe`（不变） |

### 3.2 发布包 `release/p4_history_candidate_v1/`（r2，已重建）

| 文件 | sha256(前16) |
|---|---|
| `run_port_test.py` | `2f59f8daf7a41675` |
| `check_release.py` | `3fe53605662ecf73` |
| `runs_config.json` | `6e38af97cb192e93` |
| `src/client_runner.py` | `5f221dd4e8a83fad` |
| `src/strategy_engine.py` | `f4f41a97bd24d289` |
| `local_decision_frozen.py` | `6f9c895357149c97` |
| `conservative_grid_frozen.py` | `778af8fd986a79b6` |
| `candidate/candidate_decision.py` | `8be9f9df647194d8` |
| `candidate/predictor.py` | `0fa1753454775cbd` |
| `candidate/model.py` | `ada6c0069ee9b426` |
| `candidate/observer.py` | `a58d1931ff3334fe` |
| `FREEZE.json` | `4c86aebf8189d35e` |
| `BUILD_INFO.json` | `702a338a7d095ea7` |
| `README_运行说明.md` | `f29abe9561dd7ee1` |
| `MANIFEST_文件指纹.csv` | `dc319b588d291f6c` |

`FREEZE.json` / `BUILD_INFO.json` 新增字段：
`release_revision = "r2"`、`revision_of`、`revision_changes`（D1/D2 摘要）、
`supersedes_fingerprints（历史身份）`（r1 的候选与冻结基类 sha256）、`runs_dir`（D2 目录与覆盖方式）。

包自检（从 `C:\` 运行 `check_release.py`）：**全部通过**，含新增第 [6] 项"运行产物目录在包外"。

### 3.3 历史身份（不得冒充）

- r1 的**原版字节**（`candidate_decision.py 811ed39875813301`、`local_decision_frozen.py 6d26e61de9a25fd4`、
  当时的 `stage3/FREEZE.json ea7b5923de780356`）保存在 `experiments/_archive_pre_d1_20260913/`（只读）；
- r1 的更早包快照保留在 `release/_archive/p4_history_candidate_v1_pre_budget_20260913/`
  （engine `8dca0841ba7c45de`、client_runner `fd03f0e4c21f571c`、入口 `e5fc7db9d41e50e5`、冻结件与候选同 r1）；
- 此前报告/论文中引用的历史运行与验收结果，**其版本身份是 r1**；
  **不得**用本版 r2 的指纹去标注那些历史运行。

---

## 四、本轮自检

- **未调用官方模拟器**：未连接 `127.0.0.1:2026`；D2 验证用的是本地 stub 端口（永远断连，仅用于触发重试耗尽与落盘路径）。
- **未新增随机案例**：D1/D2 验证全部为合成几何/替身模型与 stub 服务的**定向状态**，不构成案例或基准。
- **未重跑整批性能测试**：12 局配对验收未重跑；仅复核源局部性（§1.3）与两个定向状态（§1.4）。
- **未改动**：P3、P4 覆盖布局、扫描规则、全局调度、候选补点、清除计划、结束判据；
  `src/strategy_engine.py`（预算）、`src/local_decision.py`（P3 决策）、`candidate/predictor.py`、`model.py`、`observer.py` 均未改。
- **历史记录零改动**：142 条官方日志 + 15 个验收会话 + 36 个归档文件逐条 sha256 一致（§2.3）。

## 五、复现命令

```powershell
# D1
python experiments/stage3_candidate/tools/build_candidate_method.py   # 再生候选（构建期一次性）
python experiments/stage3_candidate/tools/write_freeze.py             # 刷新 stage3 冻结声明
python scratch/verify_d1_fix.py                                       # 5 个定向状态（old=r1 归档，new=发布包）

# D2
python scratch/protect_logs_inventory.py results/delivery/log_inventory_after_d2.json
python release/build_release_v1.py                                    # 重建（含迁出保护 + runs_config.json）
python scratch/verify_d2_runsdir.py                                   # 写盘位置 + 重建前后指纹不变
```

## 六、交付物

| 文件 | 内容 |
|---|---|
| `results/delivery/MINIMAL_FIXES_D1_D2.md` | 本记录 |
| `results/delivery/d1_fix_verification.json` / `.log` | D1 五个定向状态（old vs new）结果 |
| `results/delivery/d2_runsdir_verification.json` / `.log` | D2 写盘位置与重建不变性结果 |
| `results/delivery/log_inventory_before_d2.json` | D2 前置：修复前日志清单与指纹（193 个文件） |
| `results/delivery/log_inventory_after_d2.json` | D2 之后同一清单（用于逐条比对） |
| `release/p4_official_runs/` | 包外独立运行产物目录（含 2 个 `_D2_probe_*` 测试日志与 1 次真实入口落盘记录） |
