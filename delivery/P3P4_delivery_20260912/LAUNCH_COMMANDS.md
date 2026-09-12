# 启动命令

## 一、P3（合入后的主线）

稳定版（默认档位，径向实验关闭）：

```bash
python scripts/run_port_test.py --prob p3 --version C --profile stable --port 2026 --robot_id <参赛队号>
```

径向候选版（实验档位，需显式选择）：

```bash
python scripts/run_port_test.py --prob p3 --version C --profile radial_candidate --port 2026 --robot_id <参赛队号>
```

两档位在 P3 下均启用 `enable_2opt_head=True`；不带 `--profile` 时等价于 `stable`。

## 二、P4 首任务 2-opt 实验（分支 `feature/p4-head-2opt-experiment`）

默认（2-opt 首任务关闭，与主线一致）：

```bash
python scripts/run_port_test.py --prob p4 --version C --profile stable --port 2026 --robot_id <参赛队号>
```

候选（显式开启首任务 2-opt）：

```bash
python scripts/run_port_test.py --prob p4 --version C --enable_2opt_head on --port 2026 --robot_id <参赛队号>
```

> 注意：在 P4 非终止缺陷修复前，上述 P4 命令会进入无界清除循环，请勿对官方模拟器执行。

## 三、本轮实际使用的本地验收命令（**不连接官方模拟器**）

```bash
python scripts/verify_launch_profiles.py
python scripts/verify_p4_head_2opt_chain.py
python scripts/verify_p4_head_2opt_rigorous.py
python scripts/diagnose_p4_nontermination.py
python scripts/summarize_p4_head_2opt.py
```
