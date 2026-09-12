# 基线契约（BASELINE CONTRACT）

> 本文件记录**第一阶段 `route3_paired_cases.csv` 的实际基线**：源码、冻结组件、生效配置，
> 以及由此发现的**对照污染**问题及其处理方式。
> 这是第二阶段三臂比较的前提；未记录清楚就不允许开始比较。

---

## 1. CSV 的产生链路

```
experiments/roadmap/route3_paired_cases.csv
  ← experiments/roadmap/export_route3_paired_csv.py
      ← experiments/roadmap/results/route3_responsive_stop_results.json   (k=1/2/3 朴素阈值臂)
      ← experiments/roadmap/results/route3b_j0_gated_results.json         (θ 门控臂)
          ← experiments/roadmap/route3_responsive_stop.py :: build_engine()
          ← experiments/roadmap/route3b_j0_gated_stop.py :: build_engine()
```

两处 `build_engine` 的构造完全一致：

```python
env  = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=is_p4, seed=seed)
drv  = LocalSimDriver(env)
eng  = StrategyEngine(driver=drv, is_p4=is_p4, version="C", verbose=False)
# 基线臂 A：stop_after_blind=None -> 不注入任何替换，直接用引擎自建的 local_decision
```

## 2. 生效源码与冻结组件（P4 基线）

| 角色 | 文件 | sha256（前 16 位） |
|---|---|---|
| 环境/驱动 | `src/sim_env.py` | `FFA4F33AA5F943DE` |
| 全局调度引擎（version="C" → `run_version_c_openroute`） | `src/strategy_engine.py` | `8DCA0841BA7C45DE` |
| 覆盖/证据（`EvidenceTrackerP4`） | `src/evidence_tracker.py` | `4A627A8BB8A236A1` |
| **局部决策（冻结，实际生效）** | `local_decision_frozen.py` | `6D26E61DE9A25FD4` |
| **安全网格（冻结，实际生效）** | `conservative_grid_frozen.py` | `778AF8FD986A79B6` |
| 局部决策（共享版，**P4 基线未使用**） | `src/local_decision.py` | `EAC1BDD8A0B3E964` |
| 安全网格（共享版，**P4 基线未使用**） | `src/conservative_grid.py` | `2908487383308ACA` |

来源：`src/strategy_engine.py` 在 `is_p4=True` 时执行

```python
import local_decision_frozen
import conservative_grid_frozen
self.local_decision = local_decision_frozen.LocalDecisionMaker(max_followups=12,
                                                               max_followup_time_s=600.0,
                                                               margin_s=5.0)
self.grid_class = conservative_grid_frozen.ConservativeGrid
```

即：**冻结组件从仓库根目录导入**，与 `src/` 下的同名模块不是同一份代码。

## 3. 生效配置（P4 基线臂）

| 参数 | 生效值 | 依据 |
|---|---|---|
| `is_p4` | `True` | 场景为 P4 |
| `version` | `"C"` → `run_version_c_openroute` | `build_engine` |
| `verbose` | `False` | `build_engine` |
| `scan_at_clearance` | `False`（P4 下被强制关闭） | `strategy_engine.py`：`scan_at_clearance if not is_p4 else False` |
| `enable_2opt_head` | `False`（默认） | 构造签名默认值 |
| `enable_adaptive_radial_coverage` | `False`（P4 下被强制关闭） | `strategy_engine.py`：`... if not is_p4 else False` |
| `enable_pruning` | `True` | `version not in ["B","C_BASELINE","C_BASE","BASELINE"]` |
| `max_followups` / `max_followup_time_s` / `margin_s` | `12` / `600.0` / `5.0` | 冻结决策器默认 |
| `max_repeat_clear_fail` | `3` | 引擎默认 |
| 环境种子 | `SimEnvironment.generate_random_case(num_sources=n_src, is_p4=True, seed=seed)` | 本地参考环境（非官方端口） |
| 定向源比例 | `dir_ratio=0.5`（环境默认） | `sim_env.generate_random_case` |

## 4. 发现的问题：此前的 B 臂对照被污染

第一阶段 B 臂的注入方式是：

```python
# route3_responsive_stop.py
from src.local_decision import LocalDecisionMaker          # <-- 共享版！
class ResponsiveStopLocalDecision(LocalDecisionMaker): ...
eng.local_decision = ResponsiveStopLocalDecision(...)      # 对 P4 而言等于换掉了冻结组件
```

`local_decision_frozen.py` 与 `src/local_decision.py` 的差异量：

```
1 file changed, 114 insertions(+), 124 deletions(-)          # 结构差异，并非同一份代码
```

因此第一阶段的 **B − A** 差值在原理上同时包含两种效应：
1. `k=1` 止损规则；
2. **冻结决策器 → 共享决策器**的组件替换。

### 4.1 实测：该替换在行为上是**中性的**

`diag_frozen_vs_shared.py` 在同样的三组预注册场景上跑了 A′ = 只换决策器、不加任何规则：

| seed | 源数 | 冻结版 T | 共享版 T | ΔT |
|---|---|---|---|---|
| 8801 | 10 | 6 773.05 | 6 773.05 | **+0.00 s** |
| 8813 | 13 | 9 318.82 | 9 318.82 | **+0.00 s** |
| 8816 | 16 | 6 928.61 | 6 928.61 | **+0.00 s** |

三局清除率、空频道数、计费闭合也完全一致。

**结论修正**：`local_decision_frozen.py` 与 `src/local_decision.py` 的差异是
**真实的源码契约差异**（不同文件、不同版本、114/124 行结构改动，多为重构：
docstring、`decide_action` 拆分出 `_decide_action_impl`、辅助函数重命名、
`infeasible_penalty_s` 参数、注释增删），但在本批场景上**不产生任何行为差异**。
因此此前 route3 的 B 臂结果并未被该替换实质污染。

**处理方式**：第二阶段的三臂仍全部以 `local_decision_frozen.LocalDecisionMaker` 为基类
（见 `arm_decision.py` 顶部契约），使 A/B/C 之间只差各自的机制；
该诊断的 3 局**不计入 9 局配对**，只作为基线契约记录。

## 5. 第二阶段三臂定义（锁定）

| 臂 | 类 | 与基线的差异 | 是否叠加 k 规则 |
|---|---|---|---|
| **A** | `local_decision_frozen.LocalDecisionMaker`（引擎自建，不做任何替换） | — | 否 |
| **B** | `K1StopFrozenDecision`（基类 = 冻结决策器） | 连续 1 次补测未使存活集收缩 ⇒ 强制转入清除 | 是（就是该规则） |
| **C** | `CHypothesisDecision`（基类 = 冻结决策器） | 接收概率改由历史观测假设模型给出；全部假设不相容时逐字回退冻结公式 | **否**（明确不叠加） |

**明确不改动**：P3、P4 覆盖布局、扫描规则、全局调度、候选补测点生成、完整清除计划、结束判据。
`run_paired.py` 用的就是 `src/strategy_engine.py` 与冻结组件，三臂只替换 `eng.local_decision` 这一个对象。

## 6. 臂 C 的"只改一处"如何被机检

`arm_decision.build_decide_with_model()` **读取冻结版 `decide_action` 的源码**，
只把"接收概率"那一个切片替换成对假设模型的调用，其余（含全部注释与空行）逐字保留，
再 `exec` 成 `_decide_with_model`。

`check_mechanism.py` 的源码一致性检查验证：
删掉被替换切片后，生成文本与冻结文本**逐行相同**（实测：277 行 vs 277 行，一致）。
