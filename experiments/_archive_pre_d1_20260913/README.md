# pre-D1 原版归档（历史身份，禁止修改）

本目录保存 **D1 最小修复之前**的原版字节，用于保证"历史实验保留原版本身份、
不把修订后版本冒充历史运行版本"。

| 文件 | sha256(前16) | 说明 |
|---|---|---|
| `candidate_decision.py` | `811ed39875813301` | 第三阶段验收版候选决策模块（构建期生成物） |
| `local_decision_frozen.py` | `6d26e61de9a25fd4` | 验收版冻结决策基类（候选的生成来源 / 基类） |
| `stage3_FREEZE.json` | `ea7b5923de780356` | 验收时的 stage3 冻结声明（记录当时各文件 sha256） |

用途与边界：

- 上述指纹是**历史运行/验收时的身份**。此前所有官方与本地运行、验收报告、
  论文中引用的候选指纹，均指这一版。
- D1 之后重新生成的候选与冻结基类**是新版本**，**不得**用来冒充上述历史版本；
  引用历史结果时必须同时给出本目录的指纹。
- 本目录内容只读：任何后续重建都不得覆盖或删除。

## r1 完整身份（跨版本引用用）

| 组件 | r1 指纹（sha256 前16） | 现存位置 |
|---|---|---|
| `candidate_decision.py` | `811ed39875813301` | 本目录（原版字节） |
| `local_decision_frozen.py` | `6d26e61de9a25fd4` | 本目录（原版字节） |
| `stage3/FREEZE.json` | `ea7b5923de780356` | 本目录（`stage3_FREEZE.json`） |
| `conservative_grid_frozen.py` | `778af8fd986a79b6` | 工作区（r1=r2，未改） |
| `candidate/predictor.py` | `0fa1753454775cbd` | 工作区（r1=r2，未改） |
| `candidate/model.py` | `ada6c0069ee9b426` | 工作区（r1=r2，未改） |
| `candidate/observer.py` | `a58d1931ff3334fe` | 工作区（r1=r2，未改） |
| `src/strategy_engine.py` | `8dca0841ba7c45de`（r1 验收时） | `release/_archive/p4_history_candidate_v1_pre_budget_20260913/src/` |
| `src/client_runner.py` | `fd03f0e4c21f571c`（r1 验收时） | 同上归档包 |
| `run_port_test.py`（发布入口） | `e5fc7db9d41e50e5`（r1 验收时） | 同上归档包 |

对应关系（后续版本自查）：修订后指纹见 `results/delivery/MINIMAL_FIXES_D1_D2.md`。
