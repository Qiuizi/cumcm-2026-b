# 最终生效配置（由入口实跑落盘自动生成）

| 配置项 | stable（稳定版） | radial_candidate（径向候选版） |
|---|---|---|
| `is_p4` | `False` | `False` |
| `version` | `C` | `C` |
| `enable_pruning` | `True` | `True` |
| `scan_at_clearance` | `False` | `False` |
| `enable_2opt_head` | `True` | `True` |
| `enable_adaptive_radial_coverage` | `False` | `True` |
| `grid_class` | `src.conservative_grid.ConservativeGrid` | `src.conservative_grid.ConservativeGrid` |
| `local_decision_class` | `src.local_decision.LocalDecisionMaker` | `src.local_decision.LocalDecisionMaker` |

## 不变量核验

- `P3_two_profiles_share_identical_config_except_radial`: **True**
- `both_profiles_enable_2opt_head`: **True**
- `radial_default_off_in_stable_profile`: **True**
- `source_fingerprint_identical_between_profiles`: **True**
- `P4_frozen`: **见 03_verification/launch_profile_matrix.json（P4 两档位均为 radial=False, 2opt=False）**

## 源码标识（两档位完全一致）

| 文件 | sha256[:16] |
|---|---|
| `src/strategy_engine.py` | `d98fd3660a82e693` |
| `src/local_decision.py` | `eac1bdd8a0b3e964` |
| `src/conservative_grid.py` | `2908487383308aca` |
| `src/evidence_tracker.py` | `e9d89c9adb9c6152` |
| `src/client_runner.py` | `e4e6ba0f160d9b94` |
| `scripts/run_port_test.py` | `b2bcb8f17a0b4275` |

## 入口验收实跑（本地 Mock，非官方端口）

| 档位 | 端口 | 外部官方端口 | 场景源数 | 成功清除 | 未决频道 | 阴性覆盖排除 | 16源上限排除 | 径向调点 | 计费残差(s) |
|---|---|---|---|---|---|---|---|---|---|
| stable | 13026 | False | 10 | 10 | 0 | 10 | 0 | 0 | 0.0003 |
| radial_candidate | 13027 | False | 10 | 10 | 0 | 10 | 0 | 2 | 0.0004 |

> 说明：两局入口验收仅用于验证启动接线与配置落地，源分布为时间随机种子，**不作为收益证据**。
