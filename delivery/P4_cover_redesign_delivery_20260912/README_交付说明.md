# P4 搜索覆盖与路线组织重新设计 · 交付包

## 核心结论（先说答案）

**不能。** 在保留"每个空频道都必须用静默测站覆盖整个 Ω"这一结束证据要求的前提下，
P4 整局虚拟时间**无法接近 4000 秒**：

- 10 源：硬下界 **4892.24 s**（覆盖路线 3592.24 + 空频道检测 1250.00 + 成功清除 50.00）
- 13 源：硬下界 **4532.24 s**
- 16 源：由 K=16 上限提前结束搜索，路线下界不适用；但基线中 **3817.25 s** 的"接入目标绕行"由保留的局部组件决定

覆盖网规模（25 点）、覆盖路线（17961.20 m）、每空频道的检测次数（25 次）三者都已被证明不可再减。

## 关键标识

| 项 | 值 |
|---|---|
| 基线 | 修复提交 `53b664d`（P4 2-opt 关闭） |
| 候选分支 | `exp/p4-cover-redesign`（提交 `0fd8b12`），原基线保留可回退 |
| 改动文件 | `src/evidence_tracker.py`（覆盖网参数化 + 剖分生成 + 连续凸包证书核验） |
| 未改动 | P3、P4 扫描规则、全局调度、局部定位与完整清除计划、参数；未重新开启 2-opt；未调用官方模拟器 |
| 两臂配置 | 均 `is_p4=True, version="C", scan_at_clearance=False, enable_2opt_head=False` |

## 目录结构

```
P4_cover_redesign_delivery_20260912/
├── README_交付说明.md
├── CONCLUSION_结论.md                     候选理由 / 覆盖证明 / 成本预算 / 三例结果 / 限制所在
├── MANIFEST_文件清单.csv                   包内文件 sha256（不含自身）
├── 01_analysis/                            离线成本空间研究
│   ├── baseline_cost_decomposition.txt      基线逐项分解（移动/检测/切频/清除，搜索段/补测段/清除段）
│   ├── cover_cost_exploration.json          环状族可行性与路线
│   ├── lattice_net_exploration.json         三角格子补丁网（M2）对比
│   ├── net_search.json                      Delaunay 构型搜索（72072 组，证明 25 点为最小）
│   └── cost_budget.json                     闭合的 4000 秒预算
├── 02_candidate/
│   ├── source_diff_vs_53b664d.patch         完整源码差异（无省略号）
│   ├── full_source/src_evidence_tracker.py  改动后源码全文
│   └── geometry_certificate.json            连续凸包证书的精确核验结果
├── 03_scripts/                              本轮全部脚本（可复现）
└── 04_paired_run/
    ├── p4_cover_redesign_paired.csv/.json    三例配对 + 敏感性带
    ├── candidate/acceptance.csv/.json + action_logs/   候选臂原始记录与动作日志
    ├── baseline_53b664d/acceptance.json      基线臂原始记录（复用）
    └── sensitivity/r1_sensitivity.json       r1 敏感性诊断（判据：差异是否可归因）
```

## 复现方式

```bash
# 1) 基线成本分解
python scripts/analyze_p4_baseline_cost.py

# 2) 覆盖成本空间：环状族、格子补丁网、Delaunay 最小网搜索
python scripts/explore_p4_cover_cost.py
python scripts/explore_p4_lattice_nets.py
python scripts/search_p4_nets.py

# 3) 闭合的 4000 秒预算
python scripts/p4_cost_budget.py

# 4) 候选三例（2-opt 关闭）
python scripts/verify_p4_fix_acceptance.py --arm fixed_baseline \
       --outdir results/p4_cover_redesign/paired_run/candidate

# 5) r1 敏感性诊断（判定收益是否可归因）
python scripts/p4_radius_sensitivity.py 1000 980

# 6) 配对与敏感性带
python scripts/build_p4_cover_redesign_paired.py
```

## 本轮做了什么 / 没做什么

**做了**

- 两种机制不同的覆盖组织（同心环状网 vs 三角格子补丁网）的离线对比，含连续覆盖保证、路线长度、
  逐频道检测与切频成本、接入目标后新增路程。
- 对 4 / 7 / 10 个空频道的搜索负担分别给出预算。
- 72072 组 Delaunay 构型搜索，证明不存在少于 25 点的合法覆盖网；独立复算证明路线启发式已最优。
- 候选实现：覆盖网参数化 + 剖分生成 + 连续局部凸包证书；几何证书精确核验通过。
- 三例本地配对（2-opt 关闭），六次运行全部通过完整验收。
- r1 敏感性诊断，判定 +385 s 差异**不可归因**于覆盖结构。

**没做**

- 未调用官方模拟器；未修改 P3；未生成论文。
- 未围绕种子调参（r1 由路线长度择优，不由实测用时择优）。
- 未叠加历史 no_signal 概率改造；未重新开启首任务 2-opt。
- 未修改 P4 扫描规则、全局调度、局部定位与完整清除计划。
- 未把 +385 s 包装成收益；三例后停止。
