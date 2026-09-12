# 启动命令（两条，均为实测可用）

入口：`scripts/run_port_test.py` → `src/strategy_engine.py: StrategyEngine`。
两个档位除径向开关外配置完全一致，**均启用 `enable_2opt_head=True`**；P4 下两个档位都被强制冻结（径向=False、2opt=False）。

## 一、稳定版（默认档位，径向实验关闭）

```bash
python scripts/run_port_test.py --prob p3 --version C --profile stable --port 2026 --robot_id <参赛队号>
```

等价写法（低级开关显式覆盖，必须与档位一致）：

```bash
python scripts/run_port_test.py --prob p3 --version C --profile stable --radial_coverage off --port 2026 --robot_id <参赛队号>
```

## 二、径向候选版（实验档位，径向开关打开）

```bash
python scripts/run_port_test.py --prob p3 --version C --profile radial_candidate --port 2026 --robot_id <参赛队号>
```

等价写法：

```bash
python scripts/run_port_test.py --prob p3 --version C --profile radial_candidate --radial_coverage on --port 2026 --robot_id <参赛队号>
```

## 三、本地替代驱动验收命令（**不连接官方端口**）

本轮验收实际执行的两条命令（端口 13026 / 13027，由脚本在空闲端口自动拉起本地 Mock 服务器，源数 10）：

```bash
python scripts/run_port_test.py --port 13026 --prob p3 --version C --profile stable          --sources 10 --emit_summary_json results/delivery/entry_validation_stable.json
python scripts/run_port_test.py --port 13027 --prob p3 --version C --profile radial_candidate --sources 10 --emit_summary_json results/delivery/entry_validation_radial_candidate.json
```

补充：脚本**仅当目标端口已被占用时**才连入该端口的外部服务；使用 13026/13027 等非官方端口时不会接触官方模拟器。

## 四、档位与开关语义

| 参数 | 取值 | 说明 |
|---|---|---|
| `--profile` | `stable`（默认）/ `radial_candidate` | 运行档位，决定径向开关与报告中的档位标签 |
| `--radial_coverage` | `on` / `off` | 径向开关的低级覆盖项；**与 `--profile` 冲突时直接报错退出**（exit 1），避免配置歧义 |
| `--enable_2opt_head` | `on` / `off` | 默认 P3=on、P4=off；两档位在 P3 下均为 on |
| `--emit_summary_json` | 路径 | 把最终生效配置、源码指纹、本局汇总、HTTP 计费审计落盘为 JSON |

冲突保护实测：

```
$ python scripts/run_port_test.py --profile stable --radial_coverage on
run_port_test.py: error: --radial_coverage=on 与 --profile=stable 冲突；请使用 --profile stable|radial_candidate 明确选择档位（两者必须一致）
[exit code: 1]
```

## 五、启动报告中会打印的内容

每次启动都会打印：运行档位、代码版本（含 git commit）、**最终生效配置 8 项**、**源码标识**
（`src/strategy_engine.py`、`src/local_decision.py`、`src/conservative_grid.py`、`src/evidence_tracker.py`、
`src/client_runner.py`、`scripts/run_port_test.py` 的 sha256 前 16 位）、以及本局明文 HTTP 日志绝对路径。
