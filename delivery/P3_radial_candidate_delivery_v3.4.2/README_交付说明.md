# P3 径向覆盖候选版 · 精简交付包

**基线**：`v3.4.2-guard-upperbound`（git 基线提交 `160d265`）
**候选**：`v3.4.2 + radial`（径向自适应覆盖检测点，实验特性，**默认关闭**）
**本包性质**：可选候选版交付：**不自动合入稳定默认配置**，不新增策略，不调参，不调用官方模拟器，不追加整批测试。

---

## 1. 交付范围与状态

| 验收项 | 状态 | 证据 |
|---|---|---|
| 启动入口可选稳定版 / 径向候选版，两档均 `enable_2opt_head=True` | ✅ 通过 | `03_verification/launch_profile_matrix.json`、`01_source_diff/source_diff_vs_v3.4.2.patch` |
| 本地替代驱动端到端实跑（非官方端口） | ✅ 通过（两档各 1 局） | `03_verification/entry_validation_*.log` / `.json` |
| 九组配对逐局完整性汇总 | ✅ 完成（18 局全部目标清除 + 计费闭合） | `04_results/p3_radial_per_run_completeness.csv` |
| 字段完整性（未记录字段显式标注） | ⚠️ 4 个字段原始记录未落盘 | `04_results/p3_radial_field_coverage_audit.json` |
| 固定结论 + 两例退步保留 | ✅ 完成 | `CONCLUSION_结论.md` |
| 稳定基线 v3.4.2 / P4 保持原状态 | ✅ 未改动 | 见下 §4 |

---

## 2. 目录结构

```
P3_radial_candidate_delivery_v3.4.2/
├── README_交付说明.md                      本文件
├── CONCLUSION_结论.md                      固定结论 + 两例退步 + 三条边界声明
├── LAUNCH_COMMANDS.md                      稳定版 / 候选版 / 本地验收 启动命令
├── MANIFEST_文件清单.csv                    包内 27 个文件的 sha256 + 字节数
│                                            （清单无法自哈希，不含自身）
├── 01_source_diff/
│   ├── source_diff_vs_v3.4.2.patch         完整源码差异（无省略，1482 行新增 / 8 行删除，7 个文件）
│   ├── source_diff_stat.txt                差异统计
│   └── full_source/                        改动后源码全文（便于直接阅读实现）
├── 02_config/
│   ├── final_effective_config.json         最终生效配置（由两次入口实跑的落盘 JSON 生成）
│   └── final_effective_config.md           同上，表格版
├── 03_verification/
│   ├── run_port_test.py                    入口（含 --profile 径向接线）
│   ├── verify_launch_profiles.py           档位接线验收（不通信）
│   ├── launch_profile_matrix.json          档位矩阵结论
│   ├── verify_p3_radial_coverage_rigorous.py  九组配对评测脚本（产出原始记录）
│   ├── verify_p3_radial_coverage.py        早期径向验证脚本（保留）
│   ├── aggregate_p3_radial_delivery.py     九组逐局完整性汇总脚本
│   ├── entry_validation_stable.log / .json
│   └── entry_validation_radial_candidate.log / .json
└── 04_results/
    ├── p3_radial_coverage_9cases_summary.csv    九组配对原始记录（原始审计CSV）
    ├── p3_radial_coverage_6new_cases.csv        新六例原始记录
    ├── p3_radial_coverage_3cases_corrected.csv  纠偏三例原始记录
    ├── p3_radial_coverage_9cases_audit.json     九组原始审计 JSON（五类计费明细 + 径向事件）
    ├── p3_radial_per_run_completeness.csv       逐局(18 行)完整性汇总 ← 新增
    ├── p3_radial_per_case_delta.csv             逐案例(9 行)配对节省 ← 新增
    └── p3_radial_field_coverage_audit.json      字段级"已记录/未记录"审计 ← 新增
```

---

## 3. 逐局完整性：已记录 / 未记录

原始记录（九组配对 CSV + 审计 JSON）覆盖情况：

**已记录（18/18 局）**：场景源数、成功清除数、T（总虚拟时间）、L（里程）、测量次数、切频次数、
失败清除次数、现实耗时、成本核算残差。

**未记录（18/18 局，一律标注为"未记录"）**：

| 字段 | 原因 |
|---|---|
| 未决频道数 | 评测脚本执行时未把 `summary['unsolved_count']` 落盘 |
| 阴性覆盖排除数 | 评测脚本未落盘 `absent_coverage_count` |
| 16 源上限排除数 | 评测脚本未落盘 `absent_upper_bound_count` |
| 实际生效配置（逐局） | 评测脚本未逐局落盘配置对象；配置仅硬编码于脚本并在运行头部打印 |

> **处理原则**：不填 0，不由耗时反推成功。四类字段在 CSV 中一律写 **`未记录`**。
> 入口侧已在本轮补齐落盘能力（`--emit_summary_json` 会写出 `unsolved_count`、
> `absent_coverage_count`、`absent_upper_bound_count` 与完整 `effective_config`），
> 但**未重跑九组旧案例**以回填——遵循"不重复整批测试"的约束。

**每局结束证据核对结论**：18 局中 18 局同时满足
① `成功清除数 == 场景源数`（所有目标清除）；
② `|T − (L/5 + 5M + S + 3F + 5N)| < 1e-3`（五类成本核算闭合）。
另有独立交叉校验：审计 JSON 与配对 CSV 的 T/L/M/S/F/N 六个字段全部一致（容差取落盘显示精度的半分度）。

---

## 4. 未改动项（保持原状态）

- **稳定基线 `v3.4.2-guard-upperbound`**：源码差异中 `src/strategy_engine.py` 的径向逻辑全部由
  `enable_adaptive_radial_coverage`（默认 `False`）守护；不显式开启时行为与基线一致。
- **径向实验默认关闭**：`--profile` 默认值为 `stable`。
- **P4**：`src/strategy_engine.py` 中 `is_p4` 分支继续使用 `local_decision_frozen` /
  `conservative_grid_frozen`，且对 `scan_at_clearance` / `enable_2opt_head` /
  `enable_adaptive_radial_coverage` 在 P4 下三重强制关闭。`P4` 与补测后重排均未改动。
- **未新增策略、未调参、未调用官方模拟器、未追加 30+ 局测试**：本轮仅 2 局本地入口验收（端口 13026/13027）。

---

## 5. 复现方式

```bash
# 1) 档位接线验收（无通信）
python scripts/verify_launch_profiles.py

# 2) 九组逐局完整性汇总（只读既有原始记录，不重跑）
python scripts/aggregate_p3_radial_delivery.py

# 3) 本地替代驱动入口验收（非官方端口）
python scripts/run_port_test.py --port 13026 --prob p3 --version C --profile stable --sources 10
python scripts/run_port_test.py --port 13027 --prob p3 --version C --profile radial_candidate --sources 10

# 4) 若需完整重跑九组配对评测（会产生新随机场景，约 7 分钟）
python scripts/verify_p3_radial_coverage_rigorous.py
```
