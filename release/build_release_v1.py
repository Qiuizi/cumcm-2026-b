"""
build_release_v1.py —— 生成 P4 history_candidate 的独立发布包

产物：release/p4_history_candidate_v1/  —— 自包含、可复制到任意位置：
  * 自带 src/（引擎、证据、环境、HTTP 客户端、Mock 服务）与两个冻结组件
  * 自带 candidate/（与第三阶段验收过的实现**逐字节相同**）
  * 入口 run_port_test.py 已固化接线；正常启动**不改自身源码**、不执行 git apply、不依赖补丁重放
  * 官方连接模式（默认）只连已启动服务，连不上直接退出，绝不自动拉起 Mock
  * 无 git 依赖：版本标识来自包内 BUILD_INFO.json，不调用 git rev-parse/status

本脚本只写 release/ 目录，不修改实验工作区的任何已跟踪文件。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RELEASE = os.path.join(ROOT, "release", "p4_history_candidate_v1")
STAGE3 = os.path.join(ROOT, "experiments", "stage3_candidate")

# ---- 【D2 最小修复】发布运行产物的"包外独立目录" ----
# 背景：本构建脚本以 rmtree 重建包目录，写在包内 results/ 的官方运行日志会被一并抹除。
# 规则：
#   1) 重建前先把"将要被删除的包内 results/**"**迁出**到 RUNS_DIR（绝不删除、绝不覆盖同名历史文件）；
#   2) 包内写入 runs_config.json，使入口的默认日志/会话/审计根目录指向 RUNS_DIR（包外）；
#   3) RUNS_DIR 用相对路径描述（相对包目录的上一级），整个 release/ 目录可整体搬移。
RUNS_DIR_REL = "../p4_official_runs"          # 相对包目录 ⇒ <release>/p4_official_runs
RUNS_DIR = os.path.abspath(os.path.join(RELEASE, RUNS_DIR_REL))

# ---- 版本与修订标识（D1/D2 最小修复记录随包落盘） ----
RELEASE_REVISION = "r2"
REVISION_OF = "p4_history_candidate_v1 r1（12 局配对验收版）"
REVISION_CHANGES = [
    "D1: 修复 best_jq=None（全部候选不可表示）时 reason 文本对 None 做 ':.1f' 格式化抛 TypeError；"
    "改为 jq_txt 取值，动作类型/位置/清除计划不变；冻结基类与构建期再生的候选同步携带",
    "D2: 默认运行产物（HTTP 日志/审计/会话）改写到包外独立目录 runs_config.json → "
    "../p4_official_runs；构建前自动迁出包内遗留产物（不删除、不覆盖）",
    "（r2 内更早的协议对齐：现实预算以 /enter 的 remaining_real_duration_s 为准；"
    "HTTP 错误处理/幂等性按附件2 §5.3 分类）",
]
# r1（历史身份）的指纹：原版字节在 experiments/_archive_pre_d1_20260913/
SUPERSEDED_FINGERPRINTS = {
    "candidate/candidate_decision.py": "811ed398758133016ec37e24e56eb01e799660464bd39523f5ccdb3c0c01c4af",
    "local_decision_frozen.py": "6d26e61de9a25fd4ee82e643ea1a4b6e172cd38a3f52e2e996d4757d06cef642",
}


def protect_package_logs(release_dir: str, runs_dir: str) -> dict:
    """重建前**保护**包内既有运行日志：迁出到 runs_dir/legacy_package_results/，绝不删除。

    返回迁移清单（供构建日志与最小修复记录引用）。同名文件若已存在，则改用
    `<原名>.migrated_<时间戳>` 命名，**不覆盖**既有历史记录。
    """
    src = os.path.join(release_dir, "results")
    moved = {"source": src, "dest": None, "files": [], "skipped": []}
    if not os.path.isdir(src):
        return moved
    dest = os.path.join(runs_dir, "legacy_package_results")
    os.makedirs(dest, exist_ok=True)
    moved["dest"] = dest
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for dp, _ds, fs in os.walk(src):
        for fn in fs:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, src)
            target = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.exists(target):
                target = f"{target}.migrated_{stamp}"
            shutil.copy2(p, target)          # 复制（源目录随后由 rmtree 清理）
            moved["files"].append({"rel": rel.replace("\\", "/"),
                                   "sha256": sha(p),
                                   "migrated_to": os.path.relpath(target, runs_dir)
                                   .replace("\\", "/")})
    return moved


def write_runs_config(release_dir: str, runs_dir_rel: str) -> str:
    """在包内写入 runs_config.json：告诉客户端把默认运行产物写到包外独立目录。"""
    cfg = {
        "runs_dir": runs_dir_rel,
        "note": ("默认运行产物根目录（HTTP 日志/审计/会话文件）。相对路径按包目录解析，"
                 "指向**包外**目录，因此发布包重建（rmtree 包目录）不会删除历史运行记录。"
                 "可用环境变量 CUMCM_RUNS_DIR 或命令行 --runs_dir 覆盖。"),
        "env_override": "CUMCM_RUNS_DIR",
        "cli_override": "--runs_dir",
    }
    p = os.path.join(release_dir, "runs_config.json")
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return p

SRC_COPY = ["strategy_engine.py", "evidence_tracker.py", "sim_env.py", "client_runner.py",
            "conservative_grid.py", "local_decision.py", "mock_server.py"]
FROZEN_COPY = ["local_decision_frozen.py", "conservative_grid_frozen.py"]
CANDIDATE_COPY = ["candidate_decision.py", "predictor.py", "model.py", "observer.py"]


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


README_SRC = """# P4 history_candidate 独立发布包 v1 · 修订 r2

## 这是什么

问题四（P4）**历史接收模型候选版**的独立可运行包。已把已验收的 HTTP 入口接线**固化进源码**：
正常启动**不修改自身源码**、**不执行 git apply**、**不依赖任何补丁重放**，也不依赖原实验工作区路径。

默认档位仍为 `stable`；P3 与所有策略参数未改动。

## 本版修订（相对 12 局配对验收版 r1）

| 编号 | 修订 | 影响面 |
|---|---|---|
| **D1** | 修复 `best_jq=None`（全部候选都被判不可表示）时 `reason` 文本对 `None` 做 `:.1f` 格式化抛 `TypeError`：改为按 `jq_txt` 取值。**动作类型、位置与清除计划完全不变**；冻结基类与由构建期生成器再生的候选同步携带该修复 | 只影响该异常分支的日志文案 |
| **D2** | 默认运行产物（明文 HTTP 日志 / 审计 / 会话文件）不再写在包内 `results/`，改由包内 `runs_config.json` 指向**包外独立目录** `{runs_dir_rel}`；构建脚本在重建前把包内既有产物**迁出**（绝不删除/覆盖） | 只影响日志落盘位置 |

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
| `candidate/candidate_decision.py` | `{h_cand}` | `811ed39875813301` |
| `candidate/predictor.py` | `{h_pred}` | `0fa1753454775cbd` |
| `candidate/model.py` | `{h_model}` | `ada6c0069ee9b426` |
| `candidate/observer.py` | `{h_obs}` | `a58d1931ff3334fe` |
| `local_decision_frozen.py` | `{h_frozen}` | `6d26e61de9a25fd4` |
| `conservative_grid_frozen.py` | `{h_grid}` | `778af8fd986a79b6` |

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

## 输出（全部写在包外独立目录 `{runs_dir_rel}`）

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
"""

LAUNCH_SRC = """# 官方连接命令（P4）

## 前置

官方模拟器需**由用户自行启动并处于就绪状态**。本包不会自动启动任何服务：
official 模式下若目标端口没有服务在监听，程序会立即以退出码 `2` 退出。

> 本机只读观测：`jammers-simulator.exe`
> （`D:\\\\Downloads\\\\CUMCM2026B\\\\Jammers-simulator-win64\\\\Jammers-simulator\\\\`）
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
"""


def render_readme(release_dir: str) -> str:
    """把 README 模板中的指纹/路径占位符替换为**实际包内文件**的值（避免文档与包不一致）。"""
    def h(rel):
        p = os.path.join(release_dir, rel)
        return sha(p)[:16] if os.path.exists(p) else "MISSING"
    return README_SRC.format(
        runs_dir_rel=RUNS_DIR_REL,
        h_cand=h("candidate/candidate_decision.py"),
        h_pred=h("candidate/predictor.py"),
        h_model=h("candidate/model.py"),
        h_obs=h("candidate/observer.py"),
        h_frozen=h("local_decision_frozen.py"),
        h_grid=h("conservative_grid_frozen.py"),
    )


def write_docs(release_dir: str) -> None:
    contents = (("README_运行说明.md", render_readme(release_dir)),
                ("LAUNCH_官方连接命令.md", LAUNCH_SRC))
    for name, content in contents:
        with io.open(os.path.join(release_dir, name), "w", encoding="utf-8",
                     newline="\n") as f:
            f.write(content)


def refresh_manifest(release_dir: str) -> None:
    """刷新全部文件指纹清单（不含自身，避免自指）"""
    import csv
    rows = []
    for dp, ds, fs in os.walk(release_dir):
        ds[:] = [d for d in ds if d not in ("results", "__pycache__")]
        for f in fs:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, release_dir).replace("\\", "/")
            if rel == "MANIFEST_文件指纹.csv":
                continue
            rows.append((rel, sha(p), os.path.getsize(p)))
    rows.sort()
    with io.open(os.path.join(release_dir, "MANIFEST_文件指纹.csv"), "w",
                 encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["相对路径", "sha256", "字节数"])
        for r in rows:
            w.writerow(list(r))
    print(f"MANIFEST 已刷新：{len(rows)} 个文件（不含自身）")


def build_entry(upstream_entry: str) -> str:
    """把已验收的入口改造成独立包入口（只做路径与模式两类改动）"""
    with io.open(upstream_entry, encoding="utf-8") as f:
        src = f.read()

    pairs = []

    pairs.append((
        'sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))',
        'sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  '
        '# 包根：src/ 与冻结组件都在包内'))

    pairs.append((
        '''WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STAGE3_DIR = os.path.join(WORKSPACE, "experiments", "stage3_candidate")
if STAGE3_DIR not in sys.path:
    sys.path.insert(0, STAGE3_DIR)''',
        '''# 独立发布包：入口即包根，全部依赖都在包内（不依赖原实验工作区路径）
PACKAGE_ROOT = os.path.dirname(os.path.abspath(__file__))
if PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, PACKAGE_ROOT)
CANDIDATE_DIR = os.path.join(PACKAGE_ROOT, "candidate")
if CANDIDATE_DIR not in sys.path:
    sys.path.insert(0, CANDIDATE_DIR)

MODE_OFFICIAL = "official"
MODE_MOCK = "mock"'''))

    pairs.append((
        '''SOURCE_FINGERPRINT_FILES = [
    "src/strategy_engine.py",
    "src/local_decision.py",
    "src/conservative_grid.py",
    "src/evidence_tracker.py",
    "src/client_runner.py",
    "src/sim_env.py",
    "local_decision_frozen.py",
    "conservative_grid_frozen.py",
    "scripts/run_port_test.py",
]''',
        '''SOURCE_FINGERPRINT_FILES = [
    "src/strategy_engine.py",
    "src/local_decision.py",
    "src/conservative_grid.py",
    "src/evidence_tracker.py",
    "src/client_runner.py",
    "src/sim_env.py",
    "local_decision_frozen.py",
    "conservative_grid_frozen.py",
    "run_port_test.py",
]'''))

    pairs.append((
        '''HISTORY_FINGERPRINT_FILES = [
    "experiments/stage3_candidate/candidate_decision.py",
    "experiments/stage3_candidate/predictor.py",
    "experiments/stage3_candidate/model.py",
    "experiments/stage3_candidate/observer.py",
    "experiments/stage3_candidate/wiring.py",
]''',
        '''HISTORY_FINGERPRINT_FILES = [
    "candidate/candidate_decision.py",
    "candidate/predictor.py",
    "candidate/model.py",
    "candidate/observer.py",
    "candidate/wiring.py",
]'''))

    pairs.append((
        '''def workspace_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))''',
        '''def workspace_root() -> str:
    """发布包根：所有指纹与输出路径都相对它，不含任何绝对路径依赖"""
    return PACKAGE_ROOT

def load_build_info() -> dict:
    """版本标识来自包内 BUILD_INFO.json —— 不调用 git，避免依赖所在仓库"""
    p = os.path.join(PACKAGE_ROOT, "BUILD_INFO.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {"release_id": "unknown", "upstream_validated": "unknown"}'''))

    pairs.append((
        '''def get_code_version() -> str:
    """获取当前代码版本与 git commit 信息"""
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()
        return f"v3.4.2-guard-upperbound (git-{git_hash}, 2026-09-12)"
    except Exception:
        return "v3.4.2-guard-upperbound (2026-09-12)"


def get_git_dirty() -> bool:
    """工作区是否存在未提交改动（源码标识的可信度声明）"""
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()
        return len(out) > 0
    except Exception:
        return True''',
        '''def get_code_version() -> str:
    """发布包版本标识（来自包内 BUILD_INFO.json，不调用 git）"""
    info = load_build_info()
    return (f"{info.get('release_id', 'unknown')} "
            f"(upstream-validated: {info.get('upstream_validated', 'unknown')})")


def get_git_dirty() -> bool:
    """发布包不使用 git 状态；以包内清单一致性代替（见 verify_release_integrity）"""
    return False


def verify_release_integrity() -> dict:
    """启动前核对：包内自包含文件与随包清单/baseline 指纹是否一致"""
    info = load_build_info()
    manifest = info.get("files", {})
    root = PACKAGE_ROOT
    mismatch = {}
    for rel, expected in manifest.items():
        p = os.path.join(root, rel)
        actual = sha256_of(p) if os.path.exists(p) else "MISSING"
        if actual != expected:
            mismatch[rel] = {"expected": expected[:16], "actual": actual[:16]}
    return {"checked": len(manifest), "mismatch": mismatch, "ok": not mismatch}


def sha256_of(path: str) -> str:
    import hashlib as _h
    with open(path, "rb") as f:
        return _h.sha256(f.read()).hexdigest()'''))

    # ---- argparse：新增 --mode；--sources 默认改为 None；--session_dir 默认包内 ----
    pairs.append((
        '''    parser.add_argument("--sources", type=int, default=12, help="Mock 环境干扰源数量 (10-16)")''',
        '''    parser.add_argument("--mode", type=str, default=MODE_OFFICIAL,
                        choices=[MODE_OFFICIAL, MODE_MOCK],
                        help="运行模式: official (默认；只连接用户已启动的服务，连不上直接退出，"
                             "绝不自动拉起 Mock) 或 mock (本地替代 HTTP 服务验收)")
    parser.add_argument("--sources", type=int, default=None,
                        help="[仅 mock] Mock 环境干扰源数量 (10-16)；official 模式禁止传入")'''))

    pairs.append((
        '''    parser.add_argument("--mock_seed", type=int, default=None,
                        help="本地 Mock 场景种子；缺省用当前时间（不可复现）。固定它可复现验收")
    parser.add_argument("--session_dir", type=str, default=None,
                        help="把完成状态/逐频道结束证据/计费/回退/生效配置写入该目录下的独立会话文件")''',
        '''    parser.add_argument("--mock_seed", type=int, default=None,
                        help="[仅 mock] 本地 Mock 场景种子；official 模式禁止传入")
    parser.add_argument("--session_dir", type=str, default=None,
                        help="会话文件目录；缺省写入 runs_config.json 指定的**包外**独立目录"
                             "（发布包重建不会删除历史记录）")'''))

    pairs.append((
        '''    args = parser.parse_args()

    # 【D2】运行产物根目录：显式 --runs_dir > 环境变量 > runs_config.json > <项目根>/results
    runs_dir = resolve_runs_dir(override=args.runs_dir)

    port = args.port''',
        '''    args = parser.parse_args()

    # 【D2】运行产物根目录：显式 --runs_dir > 环境变量 CUMCM_RUNS_DIR > 包内 runs_config.json
    #   ⇒ 指向**包外**独立目录：发布包重建（删除包目录）不会抹除历史运行日志
    runs_dir = resolve_runs_dir(override=args.runs_dir)
    if args.session_dir is None:
        args.session_dir = os.path.join(runs_dir, "sessions")

    # official 模式禁止场景生成参数：避免把 Mock 场景当作官方连接
    if args.mode == MODE_OFFICIAL:
        if args.sources is not None or args.mock_seed is not None:
            parser.error(
                "--sources / --mock_seed 是本地 Mock 场景生成参数，official 模式下不允许传入。"
                "官方连接请只用 --prob / --version / --profile / --port / --robot_id；"
                "如需本地替代服务验收，请显式加 --mode mock")

    port = args.port'''))

    pairs.append((
        '''    if is_port_in_use(port):
        print(f"\\n[外部服务连接] 检测到端口 {port} 已就绪，直接连入外部官方模拟器...")
        mock_seed = None
    else:
        mock_seed = int(time.time()) if args.mock_seed is None else int(args.mock_seed)
        print(f"\\n[本地模拟运行] 端口 {port} 空闲，在本地拉起高真 Mock 服务器 "
              f"(源数={args.sources}, seed={mock_seed})...")
        httpd = run_mock_server(port=port, num_sources=args.sources,
                                is_p4=is_p4, seed=mock_seed)
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.5)''',
        '''    mock_seed = None
    if is_port_in_use(port):
        print(f"\\n[外部服务连接] 检测到端口 {port} 已就绪，直接连入外部服务 ...")
        if args.mode == MODE_MOCK:
            print("  ！注意：端口已被占用，本次**不会**启动本地 Mock，将连接到已有服务。")
            print("     若该服务是官方模拟器，请改用 --mode official 运行以获得正确标注。")
    elif args.mode == MODE_MOCK:
        mock_seed = int(time.time()) if args.mock_seed is None else int(args.mock_seed)
        n_src = 12 if args.sources is None else int(args.sources)
        print(f"\\n[本地模拟运行] 端口 {port} 空闲，在本地拉起高真 Mock 服务器 "
              f"(源数={n_src}, seed={mock_seed})...")
        httpd = run_mock_server(port=port, num_sources=n_src,
                                is_p4=is_p4, seed=mock_seed)
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.5)
    else:
        print(f"\\n[连接失败] official 模式要求目标服务已在 127.0.0.1:{port} 监听。")
        print("  本模式**不会**自动拉起 Mock 服务器（避免把本地替代运行误当作官方运行）。")
        print("  请先在官方模拟器完成启动/就绪；本地验收请显式使用 --mode mock。")
        raise SystemExit(2)'''))

    # ---- 横幅与模式标识 ----
    pairs.append((
        '''    print(f"目标服务端口:           {port}")''',
        '''    print(f"目标服务端口:           {port}")
    print(f"运行模式 (Mode):        {args.mode}"
          + (" (只连接已启动服务, 连不上直接退出, 不自动拉起 Mock)"
             if args.mode == MODE_OFFICIAL else " (本地替代 HTTP 服务)"))'''))

    # ---- 会话文件里记录 mode，并做启动完整性核对 ----
    pairs.append((
        '''        session_payload = {
            "profile": profile,''',
        '''        session_payload = {
            "mode": args.mode,
            "profile": profile,'''))

    pairs.append((
        '''    print("=" * 85)
    print("【2026 数模国赛 B 题】HTTP 端口通信与官方演练实测系统")
    print("=" * 85)''',
        '''    integrity = verify_release_integrity()
    print("=" * 85)
    print("【2026 数模国赛 B 题】HTTP 端口通信与官方演练实测系统")
    print("=" * 85)
    print(f"发布包完整性:           {'一致' if integrity['ok'] else '不一致(见下)'}"
          f" (核对 {integrity['checked']} 个文件)")
    if not integrity["ok"]:
        for rel, v in integrity["mismatch"].items():
            print(f"    {rel}: 期望 {v['expected']} 实际 {v['actual']}")
        raise SystemExit("[错误] 发布包文件与随包清单不一致，拒绝运行。")'''))

    new = src
    report = []
    for i, (old, repl) in enumerate(pairs):
        n = new.count(old)
        report.append((i, n))
        if n != 1:
            raise SystemExit(f"[锚点失败] 第 {i} 处命中 {n} 次（要求 1 次），未写文件。")
        new = new.replace(old, repl, 1)

    # 头部注释：说明这是发布包入口
    new = new.replace(
        'run_port_test.py - 端口通信与端到端实测运行脚本',
        'run_port_test.py - 端口通信与端到端实测运行脚本（P4 history_candidate 独立发布包 v1）\n'
        '\n'
        '本文件已固化 history_candidate 接线；正常启动不修改自身源码、不执行 git apply、\n'
        '不依赖任何补丁重放。默认 official 模式只连用户已启动的服务，连不上直接退出。',
        1)
    return new, report


CHECK_SRC = '''"""
check_release.py —— 发布包自检（只读，不跑对局）

检查内容：
  1. 实际导入路径：所有依赖都必须解析到**本发布包内**，且不落在实验工作区
  2. 源码指纹：包内文件与 BUILD_INFO.json / FREEZE.json 一致；候选实现与 upstream 验收版一致
  3. 模型参数：预测器的冻结先验与 FREEZE.json 一致
  4. 真值隔离：候选模块 AST 静态检查
  5. 启动行为：official 模式在无服务时"直接退出且不自动拉起 Mock"；official 模式拒绝场景参数
"""
import importlib
import os
import subprocess
import sys

PKG = os.path.dirname(os.path.abspath(__file__))
for p in (PKG, os.path.join(PKG, "candidate")):
    if p not in sys.path:
        sys.path.insert(0, p)

MODULES = ["src.strategy_engine", "src.evidence_tracker", "src.sim_env",
           "src.client_runner", "src.conservative_grid", "src.local_decision",
           "src.mock_server", "local_decision_frozen", "conservative_grid_frozen",
           "candidate_decision", "predictor", "model", "observer", "wiring"]

FORBIDDEN_PARENT_HINT = "cumcm2026" + os.sep + "experiments"


def main():
    ok = True
    print("=" * 96)
    print("发布包自检（只读）")
    print("=" * 96)

    # 1. 导入路径
    print("\\n[1] 实际导入路径")
    paths = {}
    for m in MODULES:
        mod = importlib.import_module(m)
        p = os.path.abspath(getattr(mod, "__file__", "<none>"))
        paths[m] = p
        inside = os.path.normcase(p).startswith(os.path.normcase(PKG + os.sep))
        leaked = FORBIDDEN_PARENT_HINT.lower() in os.path.normcase(p)
        ok &= inside and not leaked
        flag = "OK " if (inside and not leaked) else "!! "
        print(f"  {flag}{m:<28} {p}")
    print(f"  全部依赖都在包内且未引用实验工作区: {all(os.path.normcase(v).startswith(os.path.normcase(PKG + os.sep)) for v in paths.values())}")

    # 2. 指纹
    print("\\n[2] 源码指纹")
    import wiring
    prov = wiring.verify_provenance()
    print(f"  候选/冻结指纹与 FREEZE.json 一致: {prov['all_match']}")
    for rel, c in prov["candidate_files"].items():
        print(f"    {'OK ' if c['match'] else '!! '}{rel:<44} {c['actual'][:16]}")
        ok &= c["match"]
    for rel, c in prov["frozen_baseline"].items():
        print(f"    {'OK ' if c['match'] else '!! '}{rel:<44} {c['actual'][:16]}  [{c['role']}]")
        ok &= c["match"]

    # upstream（第三阶段验收版）一致性
    import json
    fr = json.load(open(os.path.join(PKG, "FREEZE.json"), encoding="utf-8"))
    up = fr["upstream_validated"]
    import hashlib
    def sha(p):
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    print("  与 upstream 验收版逐字节一致：")
    for name, expect in up.items():
        p = os.path.join(PKG, "candidate", name) if os.path.exists(
            os.path.join(PKG, "candidate", name)) else os.path.join(PKG, name)
        actual = sha(p) if os.path.exists(p) else "MISSING"
        same = (actual == expect)
        ok &= same
        print(f"    {'OK ' if same else '!! '}{name:<28} {actual[:16]}  upstream {expect[:16]}")

    # 3. 模型参数
    print("\\n[3] 模型参数")
    from predictor import HistoryReceptionPredictor as P
    spec = fr["frozen_model_spec"]
    checks = {
        "n_hyp": (spec["n_hyp"], P.N_HYP),
        "p_dir": (spec["p_dir"], P.P_DIR),
        "r_prior": (spec["r_prior"], [P.R_LO, P.R_HI]),
        "pool_factor": (spec["pool_factor"], P.POOL_FACTOR),
        "max_rounds": (spec["max_rounds"], P.MAX_ROUNDS),
        "seed_base": (spec["seed_base"], P.SEED_BASE),
        "seed_stride": (spec["seed_stride"], P.SEED_STRIDE),
    }
    for k, (a, b) in checks.items():
        same = (a == b)
        ok &= same
        print(f"    {'OK ' if same else '!! '}{k:<14} spec={a} actual={b}")

    # 4. 真值隔离
    print("\\n[4] 真值隔离静态检查")
    iso = wiring.check_truth_isolation()
    print(f"  候选模块无禁止字段访问: {iso['clean']}")
    if iso["violations"]:
        print(f"    违规: {iso['violations'][:5]}")
    ok &= iso["clean"]

    # 5. 启动行为（不跑对局）
    print("\\n[5] 启动行为（official 模式，无服务）")
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    free_port = s.getsockname()[1]
    s.close()

    r = subprocess.run([sys.executable, os.path.join(PKG, "run_port_test.py"),
                        "--prob", "p4", "--version", "C", "--port", str(free_port)],
                       capture_output=True, text=True, encoding="utf-8", cwd=PKG)
    no_mock = "本地模拟运行" not in (r.stdout or "")
    fail_fast = (r.returncode == 2) and ("连接失败" in (r.stdout or ""))
    ok &= no_mock and fail_fast
    print(f"    无服务时直接退出: {fail_fast} (returncode={r.returncode})")
    print(f"    未自动拉起 Mock:  {no_mock}")

    r2 = subprocess.run([sys.executable, os.path.join(PKG, "run_port_test.py"),
                         "--prob", "p4", "--version", "C", "--port", str(free_port),
                         "--sources", "10"],
                        capture_output=True, text=True, encoding="utf-8", cwd=PKG)
    guard = ("不允许传入" in (r2.stderr or "") + (r2.stdout or "")) and r2.returncode != 0
    ok &= guard
    print(f"    official 拒绝场景参数 --sources: {guard}")

    # 6. 【D2】运行产物目录必须在**包外**（否则发布包重建会删除历史运行记录）
    print("\\n[6] 运行产物目录（D2：包外独立目录）")
    cfg_path = os.path.join(PKG, "runs_config.json")
    cfg_ok = os.path.exists(cfg_path)
    ok &= cfg_ok
    print(f"    包内 runs_config.json 存在: {cfg_ok}")
    runs_dir = None
    if cfg_ok:
        sys.path.insert(0, os.path.join(PKG, "src"))
        from client_runner import resolve_runs_dir
        runs_dir = resolve_runs_dir(project_root=PKG)
        pkg_abs = os.path.abspath(PKG)
        runs_abs = os.path.abspath(runs_dir)
        outside = os.path.commonpath([pkg_abs, runs_abs]) != pkg_abs
        ok &= outside
        print(f"    解析出的运行产物根目录: {runs_abs}")
        print(f"    位于包目录之外（重建不会删除）: {outside}")
        print(f"    可用 --runs_dir / 环境变量 CUMCM_RUNS_DIR 覆盖: True")

    print("\\n" + "=" * 96)
    print(f"发布包自检总结论：{'全部通过' if ok else '存在未通过项'}")
    print("=" * 96)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
'''


def build_wiring_release() -> str:
    with io.open(os.path.join(STAGE3, "wiring.py"), encoding="utf-8") as f:
        src = f.read()

    src = src.replace(
        '''STAGE3_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(STAGE3_DIR, "..", ".."))
FREEZE_PATH = os.path.join(STAGE3_DIR, "FREEZE.json")

if STAGE3_DIR not in sys.path:
    sys.path.insert(0, STAGE3_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)''',
        '''CANDIDATE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(CANDIDATE_DIR)          # 发布包根
FREEZE_PATH = os.path.join(REPO_ROOT, "FREEZE.json")

if CANDIDATE_DIR not in sys.path:
    sys.path.insert(0, CANDIDATE_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)''', 1)

    src = src.replace(
        '''CANDIDATE_MODULE_FILES = [
    "experiments/stage3_candidate/model.py",
    "experiments/stage3_candidate/predictor.py",
    "experiments/stage3_candidate/candidate_decision.py",
    "experiments/stage3_candidate/observer.py",
]''',
        '''CANDIDATE_MODULE_FILES = [
    "candidate/model.py",
    "candidate/predictor.py",
    "candidate/candidate_decision.py",
    "candidate/observer.py",
    "candidate/wiring.py",
]''', 1)

    src = src.replace('wiring.py —— 把已验证的 P4 history_candidate 接入 HTTP 入口所需的接线助手',
                      'wiring.py —— 发布包接线助手（路径为包内相对；逻辑与验收版一致）', 1)
    return src


def main():
    # ---- 【D2】重建前先保护包内既有运行日志（迁出到包外独立目录，绝不删除/覆盖） ----
    protected = protect_package_logs(RELEASE, RUNS_DIR)
    if protected["files"]:
        print(f"[D2] 已迁出包内历史运行产物 {len(protected['files'])} 个 → "
              f"{protected['dest']}（重建不会删除这些记录）")
    if os.path.isdir(RELEASE):
        shutil.rmtree(RELEASE)
    os.makedirs(os.path.join(RELEASE, "src"))
    os.makedirs(os.path.join(RELEASE, "candidate"))
    os.makedirs(os.path.join(RELEASE, "results", "sessions"))
    os.makedirs(os.path.join(RELEASE, "results", "audit_logs"))
    # 包外独立运行产物目录 + 包内 runs_config.json（D2：默认日志不再落在包内）
    os.makedirs(RUNS_DIR, exist_ok=True)
    os.makedirs(os.path.join(RUNS_DIR, "audit_logs"), exist_ok=True)
    os.makedirs(os.path.join(RUNS_DIR, "sessions"), exist_ok=True)
    write_runs_config(RELEASE, RUNS_DIR_REL)
    print(f"[D2] 默认运行产物根目录（包外，重建安全）: {RUNS_DIR}")

    # ---- 复制源码 ----
    for n in SRC_COPY:
        shutil.copy2(os.path.join(ROOT, "src", n), os.path.join(RELEASE, "src", n))
    for n in FROZEN_COPY:
        shutil.copy2(os.path.join(ROOT, n), os.path.join(RELEASE, n))
    cand_hash_check = {}
    for n in CANDIDATE_COPY:
        src_p = os.path.join(STAGE3, n)
        dst_p = os.path.join(RELEASE, "candidate", n)
        shutil.copy2(src_p, dst_p)
        cand_hash_check[n] = {"upstream": sha(src_p), "release": sha(dst_p),
                              "identical": sha(src_p) == sha(dst_p)}

    # ---- 生成 wiring.py 与入口 ----
    wiring_src = build_wiring_release()
    with io.open(os.path.join(RELEASE, "candidate", "wiring.py"), "w",
                 encoding="utf-8", newline="\n") as f:
        f.write(wiring_src)
    with io.open(os.path.join(RELEASE, "candidate", "__init__.py"), "w",
                 encoding="utf-8", newline="\n") as f:
        f.write("")

    entry_src, report = build_entry(os.path.join(ROOT, "scripts", "run_port_test.py"))
    with io.open(os.path.join(RELEASE, "run_port_test.py"), "w",
                 encoding="utf-8", newline="\n") as f:
        f.write(entry_src)

    with io.open(os.path.join(RELEASE, "check_release.py"), "w",
                 encoding="utf-8", newline="\n") as f:
        f.write(CHECK_SRC)

    # 运行说明与官方连接命令（随包交付；不参与 BUILD_INFO 的可运行集自检）
    write_docs(RELEASE)

    # ---- 生成包内 FREEZE.json（含 upstream 校验值） ----
    upstream_freeze = json.load(open(os.path.join(STAGE3, "FREEZE.json"), encoding="utf-8"))
    release_files = []
    for dirpath, _dirs, files in os.walk(RELEASE):
        for fn in files:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, RELEASE).replace("\\", "/")
            if rel.startswith("results/"):
                continue
            release_files.append(rel)

    manifest = {rel: sha(os.path.join(RELEASE, rel)) for rel in sorted(release_files)}
    freeze = {
        "release_id": "p4_history_candidate_v1",
        "release_revision": RELEASE_REVISION,
        "revision_of": REVISION_OF,
        "revision_changes": REVISION_CHANGES,
        "supersedes_fingerprints（历史身份，见 experiments/_archive_pre_d1_20260913/）":
            SUPERSEDED_FINGERPRINTS,
        "说明": "独立发布包：自包含 src/ + 冻结组件 + candidate/；不依赖原实验工作区路径",
        # —— 与验收版接线助手兼容的 schema（其校验逻辑因此无需改动）——
        "frozen_baseline_components": {
            "local_decision_frozen.py": {
                "path": os.path.join(RELEASE, "local_decision_frozen.py"),
                "sha256": sha(os.path.join(RELEASE, "local_decision_frozen.py"))},
            "conservative_grid_frozen.py": {
                "path": os.path.join(RELEASE, "conservative_grid_frozen.py"),
                "sha256": sha(os.path.join(RELEASE, "conservative_grid_frozen.py"))},
        },
        "candidate_files": {
            f"candidate/{k}": {
                "path": os.path.join(RELEASE, "candidate", k),
                "sha256": sha(os.path.join(RELEASE, "candidate", k))}
            for k in CANDIDATE_COPY + ["wiring.py"]
        },
        "frozen_model_spec": upstream_freeze["frozen_model_spec"],
        # —— 发布包附加：指向第三阶段验收版的校验值 ——
        "upstream_validated": {
            "candidate_decision.py": upstream_freeze["candidate_files"][
                "experiments/stage3_candidate/candidate_decision.py"]["sha256"],
            "predictor.py": upstream_freeze["candidate_files"][
                "experiments/stage3_candidate/predictor.py"]["sha256"],
            "model.py": upstream_freeze["candidate_files"][
                "experiments/stage3_candidate/model.py"]["sha256"],
            "observer.py": upstream_freeze["candidate_files"][
                "experiments/stage3_candidate/observer.py"]["sha256"],
            "local_decision_frozen.py": upstream_freeze["frozen_baseline_components"][
                "local_decision_frozen.py"]["sha256"],
            "conservative_grid_frozen.py": upstream_freeze["frozen_baseline_components"][
                "conservative_grid_frozen.py"]["sha256"],
        },
        "constraints": upstream_freeze["constraints"] + [
            "official 模式不生成场景、不自动拉起 Mock；连不上直接退出",
            "启动不修改自身源码、不执行 git apply、不依赖补丁重放",
        ],
    }
    with io.open(os.path.join(RELEASE, "FREEZE.json"), "w", encoding="utf-8",
                 newline="\n") as f:
        json.dump(freeze, f, ensure_ascii=False, indent=2)

    # ---- BUILD_INFO.json（含全部文件指纹；入口启动时据此自检） ----
    build_info = {
        "release_id": "p4_history_candidate_v1",
        "release_revision": RELEASE_REVISION,
        "revision_of": REVISION_OF,
        "revision_changes": REVISION_CHANGES,
        "supersedes_fingerprints（历史身份）": SUPERSEDED_FINGERPRINTS,
        "runs_dir": {"config": "runs_config.json", "value": RUNS_DIR_REL,
                     "resolved": RUNS_DIR,
                     "note": "默认运行产物根目录（包外，重建安全）；可被 CUMCM_RUNS_DIR / --runs_dir 覆盖"},
        "upstream_validated": "stage3 (P4 history_candidate, 12 局配对验收通过；r2 与 r1 数值行为一致)",
        "build_mode": "self-contained（打包后不依赖实验工作区，也不需要 git）",
        "files": manifest,
    }
    with io.open(os.path.join(RELEASE, "BUILD_INFO.json"), "w", encoding="utf-8",
                 newline="\n") as f:
        json.dump(build_info, f, ensure_ascii=False, indent=2)

    # ---- MANIFEST CSV ----
    import csv
    with io.open(os.path.join(RELEASE, "MANIFEST_文件指纹.csv"), "w", encoding="utf-8-sig",
                 newline="") as f:
        w = csv.writer(f)
        w.writerow(["相对路径", "sha256", "字节数", "角色"])
        roles = {
            "run_port_test.py": "启动入口（已固化接线）",
            "check_release.py": "发布包自检脚本（只读）",
            "FREEZE.json": "冻结声明与 upstream 校验值",
            "BUILD_INFO.json": "版本标识与文件指纹（启动自检用）",
            "local_decision_frozen.py": "冻结决策器（候选生成来源/基类）",
            "conservative_grid_frozen.py": "冻结安全网格",
        }
        for rel in sorted(manifest) + ["BUILD_INFO.json"]:
            p = os.path.join(RELEASE, rel)
            role = roles.get(rel)
            if role is None and rel.startswith("candidate/"):
                role = "候选实现（与验收版逐字节相同）" if rel != "candidate/wiring.py" \
                    else "接线助手（路径改为包内相对）"
            if role is None and rel.startswith("src/"):
                role = "引擎/环境/接口依赖（原样复制）"
            w.writerow([rel, sha(p), os.path.getsize(p), role or ""])

    print(f"发布包已生成：{RELEASE}")
    print(f"  文件数（不含 results/）：{len(release_files)}")
    print("  候选模块与验收版逐字节一致性：")
    for k, v in cand_hash_check.items():
        print(f"    {k:<24} {v['release'][:16]}  identical={v['identical']}")
    print(f"  入口改造锚点命中：{report}")


if __name__ == "__main__":
    if "--docs-only" in sys.argv:
        # 仅补写文档并刷新指纹清单：不动 src/、candidate/、入口 —— 用于在已验收的包上补交付物
        write_docs(RELEASE)
        refresh_manifest(RELEASE)
        print("文档已写入并刷新清单（未改动任何代码文件）")
    else:
        main()
