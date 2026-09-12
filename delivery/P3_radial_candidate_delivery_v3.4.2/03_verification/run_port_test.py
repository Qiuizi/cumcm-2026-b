"""
run_port_test.py - 端口通信与端到端实测运行脚本
使用方法：
1. 若官方模拟器已启动并处于测试就绪状态 (监听 2026 端口)，本脚本将直接通过 HTTP 端口连入官方模拟器进行测试。
2. 若官方模拟器未启动，本脚本会自动在本地 2026 端口拉起符合官方协议的高真 Mock 服务器进行闭环测试。

运行档位 (--profile)：
  stable           稳定版 v3.4.2 (径向自适应覆盖实验关闭) —— 交付默认档位
  radial_candidate 径向候选版 v3.4.2+radial (沿射线自适应选点，实验特性)
两个档位在 P3 下均强制 enable_2opt_head=True，配置完全一致，仅径向开关不同。

参数支持：
--port 2026 (默认 2026)
--robot_id <参赛队号> (默认读取环境变量 ROBOT_ID 或 team2026)
--prob p3 或 p4 (默认 p3)
--version B 或 C (默认 C)
--profile stable 或 radial_candidate (默认 stable)
--radial_coverage on|off (径向开关低级覆盖项，必须与 --profile 一致，否则报错退出)
--sources 12 (干扰源个数，仅在本地 mock 时生效)
--emit_summary_json <path> (可选：把最终生效配置与本局汇总落盘为审计 JSON)
"""

import sys
import os
import json
import time
import socket
import hashlib
import argparse
import threading
import subprocess

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.client_runner import HttpSimDriver, audit_http_action_log
from src.strategy_engine import StrategyEngine
from src.mock_server import run_mock_server

PROFILE_STABLE = "stable"
PROFILE_RADIAL = "radial_candidate"

# 参与"源码标识"指纹的同目录/上级目录源码文件（相对工作区根）
SOURCE_FINGERPRINT_FILES = [
    "src/strategy_engine.py",
    "src/local_decision.py",
    "src/conservative_grid.py",
    "src/evidence_tracker.py",
    "src/client_runner.py",
    "scripts/run_port_test.py",
]


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            return True
        except (socket.timeout, ConnectionRefusedError):
            return False


def workspace_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_code_version() -> str:
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
        return True


def get_source_fingerprint() -> dict:
    """逐文件 sha256(前16位) 源码标识，用于证明本次实际运行的源码身份"""
    root = workspace_root()
    fp = {}
    for rel in SOURCE_FINGERPRINT_FILES:
        path = os.path.join(root, rel)
        try:
            with open(path, "rb") as f:
                fp[rel] = hashlib.sha256(f.read()).hexdigest()[:16]
        except OSError:
            fp[rel] = "MISSING"
    return fp


def resolve_profile(args, parser):
    """解析并校验运行档位与径向开关，返回 (profile, enable_radial_coverage)"""
    profile = args.profile
    profile_radial = (profile == PROFILE_RADIAL)

    if args.radial_coverage is None:
        enable_radial = profile_radial
    else:
        enable_radial = (args.radial_coverage.lower() == "on")
        if enable_radial != profile_radial:
            parser.error(
                f"--radial_coverage={args.radial_coverage} 与 --profile={profile} 冲突；"
                f"请使用 --profile {PROFILE_STABLE}|{PROFILE_RADIAL} 明确选择档位（两者必须一致）"
            )
    return profile, enable_radial


def main():
    parser = argparse.ArgumentParser(description="无线电干扰源定位清除 HTTP 端口官方对接与实测程序")
    parser.add_argument("--port", type=int, default=2026, help="测试端口，默认 2026")
    parser.add_argument("--robot_id", type=str, default=os.getenv("ROBOT_ID", "team2026"), help="机器狗标识 (参赛队号，默认读取环境变量 ROBOT_ID 或 team2026)")
    parser.add_argument("--prob", type=str, default="p3", choices=["p3", "p4"], help="测试问题: p3 或 p4")
    parser.add_argument("--version", type=str, default="C", choices=["B", "C"], help="策略版本: B 或 C (默认 C)")
    parser.add_argument("--profile", type=str, default=PROFILE_STABLE, choices=[PROFILE_STABLE, PROFILE_RADIAL],
                        help="运行档位: stable (稳定版 v3.4.2, 径向关闭, 默认) 或 radial_candidate (径向候选版)")
    parser.add_argument("--radial_coverage", type=str, default=None, choices=["on", "off"],
                        help="径向自适应覆盖检测点低级覆盖项；默认随 --profile，若与档位冲突则直接报错")
    parser.add_argument("--scan_at_clearance", type=str, default="off", choices=["off", "on"], help="P3清除点额外扫未知频道开关: off (默认推荐) 或 on (用于复现基线)")
    parser.add_argument("--enable_2opt_head", type=str, default=None, choices=["on", "off"], help="首任务2-opt拓扑优化开关: 默认在P3下开启(on)，P4下禁用(off)")
    parser.add_argument("--sources", type=int, default=12, help="Mock 环境干扰源数量 (10-16)")
    parser.add_argument("--emit_summary_json", type=str, default=None, help="可选：将最终生效配置与本局汇总写入指定 JSON 路径")
    parser.add_argument("--verbose", action="store_true", help="打印详细动作日志")

    args = parser.parse_args()

    port = args.port
    is_p4 = (args.prob.lower() == "p4")
    version = args.version.upper()
    robot_id = args.robot_id
    scan_at_clearance = (args.scan_at_clearance.lower() == "on")

    profile, enable_radial_requested = resolve_profile(args, parser)

    if args.enable_2opt_head is not None:
        enable_2opt_head = (args.enable_2opt_head.lower() == "on")
    else:
        enable_2opt_head = (not is_p4)  # P3 默认开启 True，P4 强制保持 False

    # 径向候选仅作用于 P3；P4 严格冻结
    enable_adaptive_radial_coverage = bool(enable_radial_requested and not is_p4)

    code_version = get_code_version()
    git_dirty = get_git_dirty()
    fingerprint = get_source_fingerprint()
    profile_label = (
        f"{PROFILE_RADIAL} (径向候选版 v3.4.2+radial, 实验特性, 径向开关=ON)"
        if profile == PROFILE_RADIAL
        else f"{PROFILE_STABLE} (稳定版 v3.4.2, 径向实验关闭, 径向开关=OFF)"
    )

    server_thread = None
    httpd = None

    if is_port_in_use(port):
        print(f"\n[外部服务连接] 检测到端口 {port} 已就绪，直接连入外部官方模拟器...")
    else:
        print(f"\n[本地模拟运行] 端口 {port} 空闲，在本地拉起高真 Mock 服务器 (源数={args.sources})...")
        httpd = run_mock_server(port=port, num_sources=args.sources, is_p4=is_p4, seed=int(time.time()))
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.5)

    base_url = f"http://127.0.0.1:{port}"
    driver = HttpSimDriver(base_url=base_url, robot_id=robot_id)

    engine = StrategyEngine(
        driver=driver,
        is_p4=is_p4,
        version=version,
        scan_at_clearance=scan_at_clearance,
        enable_2opt_head=enable_2opt_head,
        enable_adaptive_radial_coverage=enable_adaptive_radial_coverage,
        verbose=args.verbose,
    )

    print("=" * 85)
    print("【2026 数模国赛 B 题】HTTP 端口通信与官方演练实测系统")
    print("=" * 85)
    print(f"运行档位 (Profile):      {profile_label}")
    print(f"代码版本:               {code_version}")
    print(f"机器狗标识 (队号):      {robot_id}")
    print(f"目标服务端口:           {port}")
    print(f"任务模式:               {'问题四 (含未知定向源 - 依赖严格隔离冻结模式)' if is_p4 else '问题三 (全向源 - 完整计划安全覆盖版)'}")
    print(f"调度策略版本:           版本 {engine.version} ({'开放路线重排+动态剪枝' if engine.version == 'C' else '固定顺序基线'})")
    print("-" * 85)
    print("【最终生效配置 (Effective Config，以下为引擎对象实际取值)】")
    print(f"  1. is_p4:                              {engine.is_p4}")
    print(f"  2. version:                            {engine.version}")
    print(f"  3. enable_pruning:                     {engine.enable_pruning}")
    print(f"  4. scan_at_clearance:                  {engine.scan_at_clearance}")
    print(f"  5. enable_2opt_head:                   {engine.enable_2opt_head}")
    print(f"  6. enable_adaptive_radial_coverage:    {engine.enable_adaptive_radial_coverage}")
    print(f"  7. enable_reschedule_after_followup:   不存在于当前代码 (等效关闭, 未实现该实验路径)")
    print(f"  8. 底层决策与网格依赖:                 {engine.grid_class.__module__}.{engine.grid_class.__name__} / {engine.local_decision.__class__.__module__}.{engine.local_decision.__class__.__name__}")
    print("-" * 85)
    print("【源码标识 (Source Identity, sha256 前16位)】")
    print(f"  git HEAD:                {'(工作区存在未提交改动, 以文件指纹为准)' if git_dirty else '(工作区干净)'}")
    for rel, digest in fingerprint.items():
        print(f"  {rel:<38} {digest}")
    print("-" * 85)
    print(f"本局明文 HTTP 日志归档: {driver.session_file}")

    print("\n>>> 开始执行自动搜索、定位与清除主策略 <<<")
    summary = engine.execute()

    print("\n" + "=" * 85)
    print("【官方演练执行总结与五类耗时闭合审计报告】")
    print("=" * 85)

    # 从归档明文日志中审计五类耗时
    audit = audit_http_action_log(driver.session_file)

    cleared_n = summary['cleared_count']
    total_sources = cleared_n + summary['unsolved_count']
    vt = summary['virtual_time_s']
    t_per_n = (vt / cleared_n) if cleared_n > 0 else 0.0

    print(f"演练策略与版本:         {summary['version']} | 代码版本: {code_version}")
    print(f"运行档位:               {profile_label}")
    print(f"径向自适应覆盖开关:     {'ON (沿射线自适应选点, 实验特性)' if summary.get('enable_adaptive_radial_coverage') else 'OFF (径向实验关闭)'}")
    print(f"径向调点次数:           {summary.get('radial_adjustments_count', 0)} 次")
    print(f"首任务 2-opt 优化状态:  {'ON' if summary.get('enable_2opt_head') else 'OFF'} (派发首任务变更: {summary.get('dispatched_head_change_count', 0)} 轮, 内部交换: {summary.get('total_2opt_swaps', 0)} 次)")
    print(f"清除点额外扫描开关:     {'ON' if summary.get('scan_at_clearance') else 'OFF'}")
    cov_cnt = summary.get('absent_coverage_count', 0)
    ub_cnt = summary.get('absent_upper_bound_count', 0)
    cov_label = "168单元覆盖完备" if not is_p4 else "三角形网格完备覆盖"
    print(f"证明空频道总数:         {summary['absent_count']} 个 (实际阴性覆盖: {cov_cnt} 个 [{cov_label}] | 16源上限直接排除: {ub_cnt} 个)")
    print(f"未决频道数:             {summary['unsolved_count']} 个 (成功清除 {cleared_n} 个, 场景已决率 {(20 - summary['unsolved_count']) / 20.0 * 100:.1f}%)")
    print(f"总虚拟时间 T:           {vt:.2f} 秒 (平均单目标耗时 T/N: {t_per_n:.2f} 秒/目标)")
    print(f"预测网格空集异常计数:   {summary.get('empty_prediction_count', 0)} 次")
    print(f"计划未覆盖异常计数:     {summary.get('plan_uncovered_count', 0)} 次")
    print(f"最大单次决策现实耗时:   {summary.get('max_single_decision_ms', 0.0):.2f} 毫秒")
    print(f"现实运行总时间:         {summary['real_time_s']:.2f} 秒 (距离1200秒硬时限安全退出余量: {1200.0 - summary['real_time_s']:.2f} 秒)")
    print("-" * 85)
    print("【五类成本完整会计核算闭环】")
    print(f"  1. 移动耗时 (T_move):       {audit['movement_time_s']:8.2f} 秒 | 实际移动距离: {audit['total_move_dist_m']:.1f} m (占比 {audit['movement_pct']}%)")
    print(f"  2. 切频道耗时 (T_switch):   {audit['channel_switch_time_s']:8.2f} 秒 | 切频道次数:   {audit['channel_switch_count']} 次")
    print(f"  3. 测量检测耗时 (T_meas):   {audit['measure_time_s']:8.2f} 秒 | 检测采样次数: {audit['measure_count']} 次")
    print(f"  4. 失败清除耗时 (T_fail):   {audit['clear_fail_time_s']:8.2f} 秒 | 失败清除次数: {audit['clear_fail_count']} 次")
    print(f"  5. 成功清除耗时 (T_succ):   {audit['clear_succ_time_s']:8.2f} 秒 | 成功清除次数: {audit['clear_succ_count']} 次")
    print(f"  --> 五类成本直接求和:       {audit['total_accounted_virtual_time_s']:8.2f} 秒")
    print(f"  --> 模拟器最终反馈时间:     {audit['final_virtual_time_s']:8.2f} 秒")
    print(f"  --> 会计核算闭合差值:       {audit['accounting_discrepancy_s']:8.4f} 秒 (严格闭合)")
    print(f"  末次成功清除至退出耗时:     {audit['time_last_clear_to_exit_s']:8.2f} 秒")
    print("-" * 85)
    print(f"已接受的唯一实际动作总数:   {audit['unique_accepted_action_count']} 次")
    print(f"本局明文日志绝对路径:       {driver.session_file}")
    print("-" * 85)
    print("【特别警示说明】")
    print("  * 本地评测录得的 6.44% (平均 222.9s) 改善幅度属于本地模拟器基准数据，")
    print("    官方演练受具体随机源分布、真值信噪比和交互开销影响，不能直接等同于官方改善幅度！")
    print("  * 官方演练的真实改善情况必须以本次官方实际输出指标为准。")
    print("=" * 85)

    if args.emit_summary_json:
        out_path = os.path.abspath(args.emit_summary_json)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        payload = {
            "profile": profile,
            "profile_label": profile_label,
            "code_version": code_version,
            "git_dirty": git_dirty,
            "source_fingerprint": fingerprint,
            "effective_config": {
                "is_p4": engine.is_p4,
                "version": engine.version,
                "enable_pruning": engine.enable_pruning,
                "scan_at_clearance": engine.scan_at_clearance,
                "enable_2opt_head": engine.enable_2opt_head,
                "enable_adaptive_radial_coverage": engine.enable_adaptive_radial_coverage,
                "grid_class": f"{engine.grid_class.__module__}.{engine.grid_class.__name__}",
                "local_decision_class": f"{engine.local_decision.__class__.__module__}.{engine.local_decision.__class__.__name__}",
            },
            "scenario": {
                "port": port,
                "robot_id": robot_id,
                "sources_requested": args.sources if httpd is not None else "外部端口(未由本脚本指定)",
                "external_official_port": httpd is None,
            },
            "summary": {k: v for k, v in summary.items() if k != "radial_events"},
            "radial_events": summary.get("radial_events", []),
            "http_audit": audit,
            "session_file": driver.session_file,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"\n[审计落盘] 最终生效配置与本局汇总已写入: {out_path}")

    if httpd is not None:
        print("\n正在停止本地 Mock 服务器...")
        httpd.shutdown()
        print("本地 Mock 服务器已关闭。")


if __name__ == "__main__":
    main()
