"""
test_problem_cases.py - 专项复测两个问题案例：
Case 1: P4-16src-case1 (seed=5600)
Case 2: 端口通信实测案例 (基于 http_action_log 提取的真实源配置，验证 Ch 14 和 Ch 17 的消除效果)
"""

import sys
import os
import json
import time
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

sys.stdout.reconfigure(encoding="utf-8")
from src.sim_env import SimEnvironment, LocalSimDriver, RadioSource
from src.strategy_engine import StrategyEngine

def run_case_1():
    print("=" * 70, flush=True)
    print("【测试案例 1】P4-16src-case1 (seed = 5600, 16 源)", flush=True)
    print("=" * 70, flush=True)

    # 1. Version B
    print(">> 正在运行 Version B...", flush=True)
    t0 = time.time()
    env_b = SimEnvironment.generate_random_case(num_sources=16, is_p4=True, seed=5600)
    drv_b = LocalSimDriver(env_b)
    eng_b = StrategyEngine(driver=drv_b, is_p4=True, version="B", verbose=False)
    res_b = eng_b.execute()
    print(f"   Version B 完成! 耗时: {time.time()-t0:.2f}s", flush=True)

    # 2. Version C_greedy
    print(">> 正在运行 Version C_greedy...", flush=True)
    t0 = time.time()
    env_cg = SimEnvironment.generate_random_case(num_sources=16, is_p4=True, seed=5600)
    drv_cg = LocalSimDriver(env_cg)
    eng_cg = StrategyEngine(driver=drv_cg, is_p4=True, version="C_GREEDY", verbose=False)
    res_cg = eng_cg.execute()
    print(f"   Version C_greedy 完成! 耗时: {time.time()-t0:.2f}s", flush=True)

    # 3. Version C_openroute
    print(">> 正在运行 Version C_openroute...", flush=True)
    t0 = time.time()
    env_co = SimEnvironment.generate_random_case(num_sources=16, is_p4=True, seed=5600)
    drv_co = LocalSimDriver(env_co)
    eng_co = StrategyEngine(driver=drv_co, is_p4=True, version="C_OPENROUTE", verbose=False)
    res_co = eng_co.execute()
    print(f"   Version C_openroute 完成! 耗时: {time.time()-t0:.2f}s", flush=True)

    print(f"版本 B:          清除={res_b['cleared_count']}/16 | 虚拟总耗时={res_b['virtual_time_s']:.2f}s | 移动距离={env_b.total_distance_m:.1f}m | 测量={env_b.measure_count}次 | 清除失败={env_b.clear_fail_count}次")
    print(f"版本 C_greedy:   清除={res_cg['cleared_count']}/16 | 虚拟总耗时={res_cg['virtual_time_s']:.2f}s | 移动距离={env_cg.total_distance_m:.1f}m | 测量={env_cg.measure_count}次 | 清除失败={env_cg.clear_fail_count}次")
    print(f"版本 C_openroute:清除={res_co['cleared_count']}/16 | 虚拟总耗时={res_co['virtual_time_s']:.2f}s | 移动距离={env_co.total_distance_m:.1f}m | 测量={env_co.measure_count}次 | 清除失败={env_co.clear_fail_count}次")
    
    save_vs_b_greedy = res_b['virtual_time_s'] - res_cg['virtual_time_s']
    save_vs_b_open = res_b['virtual_time_s'] - res_co['virtual_time_s']
    print(f"\n[成效分析]")
    print(f"  旧版 C 耗时 7232.71s (比 B 慢 1894.51s)")
    print(f"  新版 C_greedy 耗时: {res_cg['virtual_time_s']:.2f}s (相较旧版 C 降低 {7232.71 - res_cg['virtual_time_s']:.2f}s)")
    print(f"  新版 C_openroute 耗时: {res_co['virtual_time_s']:.2f}s (相较旧版 C 降低 {7232.71 - res_co['virtual_time_s']:.2f}s)")

    # 导出决策日志与动作历史
    os.makedirs("results/audit_logs", exist_ok=True)
    with open("results/audit_logs/case1_decision_log_c_openroute.json", "w", encoding="utf-8") as f:
        json.dump(eng_co.decision_logs, f, indent=2, ensure_ascii=False)

    with open("results/audit_logs/case1_action_history_c_openroute.txt", "w", encoding="utf-8") as f:
        for log in eng_co.log_history:
            f.write(log + "\n")

    return res_b, res_cg, res_co

def run_case_2():
    print("\n" + "=" * 70)
    print("【测试案例 2】端口实测 HTTP 日志对应真实场景 (15 源实测场景)")
    print("=" * 70)

    # 从 http_action_log 提取的 15 个源位置构造仿真环境
    # 已知清空点坐标，设置典型 R=1250m，定向源随机设定
    sources_data = [
        (9, 198.95, 381.21),
        (8, 504.71, -547.84),
        (10, -168.25, -646.51),
        (12, -358.59, -901.51),
        (5, -503.25, -477.94),
        (19, -744.19, 627.74),
        (1, -895.74, 1275.71),
        (3, -609.99, 1530.78),
        (4, -1532.65, -683.76),
        (7, -1230.01, -607.89),
        (2, -878.52, -1404.11),
        (20, 752.09, 989.95),
        (18, 254.65, 1574.38),
        (16, -1761.92, 128.07),
        (14, 1549.85, -587.63),
    ]

    sources_b = []
    sources_c = []
    for ch, x, y in sources_data:
        # Ch 14 在 (1549.85, -587.63)，定向朝向约 142度，在原点测不到，在 (1699.9, -704.1) 测到
        is_dir = (ch in [14, 9, 10, 4, 16])
        ori = 145.0 if ch == 14 else (65.0 if ch == 9 else 0.0)
        sources_b.append(RadioSource(ch, x, y, R=1300.0, is_directional=is_dir, orientation_deg=ori))
        sources_c.append(RadioSource(ch, x, y, R=1300.0, is_directional=is_dir, orientation_deg=ori))

    env_b = SimEnvironment(sources_b)
    drv_b = LocalSimDriver(env_b)
    eng_b = StrategyEngine(driver=drv_b, is_p4=True, version="B", verbose=False)
    res_b = eng_b.execute()

    env_c = SimEnvironment(sources_c)
    drv_c = LocalSimDriver(env_c)
    eng_c = StrategyEngine(driver=drv_c, is_p4=True, version="C_OPENROUTE", verbose=False)
    res_c = eng_c.execute()

    print(f"版本 B:          清除={res_b['cleared_count']}/15 | 虚拟总耗时={res_b['virtual_time_s']:.2f}s | 移动距离={env_b.total_distance_m:.1f}m | 测量={env_b.measure_count}次 | 清除失败={env_b.clear_fail_count}次")
    print(f"版本 C_openroute:清除={res_c['cleared_count']}/15 | 虚拟总耗时={res_c['virtual_time_s']:.2f}s | 移动距离={env_c.total_distance_m:.1f}m | 测量={env_c.measure_count}次 | 清除失败={env_c.clear_fail_count}次")

    with open("results/audit_logs/case2_decision_log_c_openroute.json", "w", encoding="utf-8") as f:
        json.dump(eng_c.decision_logs, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    run_case_1()
    run_case_2()
