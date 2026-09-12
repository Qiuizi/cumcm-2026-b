# 官方连接命令（P4）

## 前置

官方模拟器需**由用户自行启动并处于就绪状态**。本包不会自动启动任何服务：
official 模式下若目标端口没有服务在监听，程序会立即以退出码 `2` 退出。

> 本机只读观测：`jammers-simulator.exe`
> （`D:\\Downloads\\CUMCM2026B\\Jammers-simulator-win64\\Jammers-simulator\\`）
> 自 2026-09-12 起在 `127.0.0.1:2026` 监听。

## 稳定版（默认档位）

```powershell
python run_port_test.py --prob p4 --version C --profile stable --port 2026 --robot_id <参赛队号>
```

## 候选版（历史接收模型）

```powershell
python run_port_test.py --prob p4 --version C --profile history_candidate --port 2026 --robot_id <参赛队号>
```

## 规则说明

- 默认 `--mode official`：**只连接用户已启动的服务**；连不上直接退出（退出码 2），
  **绝不**自动拉起 Mock 冒充官方运行。
- official 模式禁止 `--sources` / `--mock_seed`（场景生成参数），传入即报错。
- `--version` 的调度含义未改动：`C` = 开放路线重排 + 动态剪枝，`B` = 固定顺序基线。
- `--profile` 默认 `stable`；`history_candidate` 仅适用于 `--prob p4`（与 `p3` 组合会在进入任务前报错）。
- `--robot_id` 也可通过环境变量 `ROBOT_ID` 提供。

## 本地替代服务验收（不接触官方端口）

```powershell
python run_port_test.py --mode mock --port 14029 --prob p4 --version C `
    --profile history_candidate --robot_id team2026 --sources 10 --mock_seed 9501
```

注意：若 `--mode mock` 指定的端口**已被占用**（例如 2026 上正在运行官方模拟器），
本包会打印告警并连接到该已有服务，而不会启动本地 Mock；此时请改用 `--mode official`
以获得正确的运行标注。
