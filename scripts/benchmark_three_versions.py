import os
import sys
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine
from local_decision_frozen import LocalDecisionMaker as LocalDecisionMakerFrozen
from src.local_decision import LocalDecisionMaker as LocalDecisionMakerFixed

def run_benchmark():
    test_cases = [
        ("P3-10src (seed 110)", 10, 110),
        ("P3-13src (seed 113)", 13, 113),
        ("P3-16src (seed 116)", 16, 116),
        ("P3-10src (benchmark 4000)", 10, 4000),
        ("P3-13src (benchmark 4300)", 13, 4300),
        ("P3-16src (benchmark 4600)", 16, 4600),
    ]

    print("=" * 120)
    print("【问题三】三版本同场景配对对比测试：")
    print("  版本 1: 冻结基线版 (Frozen-Baseline, 旧评分, 2-Opt首任务关闭)")
    print("  版本 2: 仅修评分版 (Fix-Score, 修复几何与信息隔离, 2-Opt首任务关闭)")
    print("  版本 3: 修评分并启用首任务2-opt版 (Fix-Score + 2-Opt Head, 允许改变下一动作)")
    print("=" * 120)

    results = []

    for name, n_src, seed in test_cases:
        print(f"\n>>> 测试案例: {name} <<<", flush=True)

        # -------------------------------------------------------------
        # 版本 1: 冻结基线版
        # -------------------------------------------------------------
        env_v1 = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        drv_v1 = LocalSimDriver(env_v1)
        eng_v1 = StrategyEngine(driver=drv_v1, is_p4=False, version="C", scan_at_clearance=False, enable_2opt_head=False, verbose=False)
        # 注入冻结版的局部决策器
        eng_v1.local_decision = LocalDecisionMakerFrozen(max_followups=12, max_followup_time_s=600.0, margin_s=5.0)
        res_v1 = eng_v1.execute()

        # -------------------------------------------------------------
        # 版本 2: 仅修评分版 (统一几何规则 + 严格信息隔离，2-opt首任务关闭)
        # -------------------------------------------------------------
        env_v2 = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        drv_v2 = LocalSimDriver(env_v2)
        eng_v2 = StrategyEngine(driver=drv_v2, is_p4=False, version="C", scan_at_clearance=False, enable_2opt_head=False, verbose=False)
        eng_v2.local_decision = LocalDecisionMakerFixed(max_followups=12, max_followup_time_s=600.0, margin_s=5.0)
        res_v2 = eng_v2.execute()

        # -------------------------------------------------------------
        # 版本 3: 修评分并启用首任务 2-opt 版
        # -------------------------------------------------------------
        env_v3 = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        drv_v3 = LocalSimDriver(env_v3)
        eng_v3 = StrategyEngine(driver=drv_v3, is_p4=False, version="C", scan_at_clearance=False, enable_2opt_head=True, verbose=False)
        eng_v3.local_decision = LocalDecisionMakerFixed(max_followups=12, max_followup_time_s=600.0, margin_s=5.0)
        res_v3 = eng_v3.execute()

        row = {
            "name": name,
            "n_src": n_src,
            "seed": seed,
            # V1
            "cleared_v1": res_v1["cleared_count"],
            "t_v1": res_v1["virtual_time_s"],
            "tn_v1": res_v1["virtual_time_s"] / n_src,
            "dist_v1": env_v1.total_distance_m,
            "meas_v1": env_v1.measure_count,
            "sw_v1": env_v1.switch_count,
            # V2
            "cleared_v2": res_v2["cleared_count"],
            "t_v2": res_v2["virtual_time_s"],
            "tn_v2": res_v2["virtual_time_s"] / n_src,
            "dist_v2": env_v2.total_distance_m,
            "meas_v2": env_v2.measure_count,
            "sw_v2": env_v2.switch_count,
            # V3
            "cleared_v3": res_v3["cleared_count"],
            "t_v3": res_v3["virtual_time_s"],
            "tn_v3": res_v3["virtual_time_s"] / n_src,
            "dist_v3": env_v3.total_distance_m,
            "meas_v3": env_v3.measure_count,
            "sw_v3": env_v3.switch_count,
            "head_swaps_v3": res_v3["head_swaps_count"],
        }
        results.append(row)

        print(f"  [V1 冻结版]       清除: {row['cleared_v1']}/{n_src} | T = {row['t_v1']:7.2f}s | T/N = {row['tn_v1']:6.2f}s | 路程: {row['dist_v1']:7.1f}m | 测量: {row['meas_v1']}次", flush=True)
        print(f"  [V2 仅修评分]     清除: {row['cleared_v2']}/{n_src} | T = {row['t_v2']:7.2f}s | T/N = {row['tn_v2']:6.2f}s | 路程: {row['dist_v2']:7.1f}m | 测量: {row['meas_v2']}次 | vs V1: {row['t_v1']-row['t_v2']:+6.2f}s", flush=True)
        print(f"  [V3 修复+2Opt首]  清除: {row['cleared_v3']}/{n_src} | T = {row['t_v3']:7.2f}s | T/N = {row['tn_v3']:6.2f}s | 路程: {row['dist_v3']:7.1f}m | 测量: {row['meas_v3']}次 | 改变首任务: {row['head_swaps_v3']}次 | vs V1: {row['t_v1']-row['t_v3']:+6.2f}s", flush=True)

    # 汇总输出
    print("\n" + "=" * 125)
    print("【三版本同场景配对对比汇总表格】")
    print("=" * 125)
    header = f"{'案例名称':<26} | {'版本1: 冻结基线':<24} | {'版本2: 仅修评分':<24} | {'版本3: 修复+首任务2-Opt':<28} | {'2-Opt首任务更换'}"
    print(header)
    print("-" * 125)

    for r in results:
        v1_str = f"T={r['t_v1']:6.1f}s, L={r['dist_v1']:6.0f}m"
        v2_str = f"T={r['t_v2']:6.1f}s, L={r['dist_v2']:6.0f}m"
        v3_str = f"T={r['t_v3']:6.1f}s, L={r['dist_v3']:6.0f}m"
        swaps_str = f"{r['head_swaps_v3']} 次改变下一动作"
        print(f"{r['name']:<26} | {v1_str:<24} | {v2_str:<24} | {v3_str:<28} | {swaps_str}")

    print("-" * 125)

    # 总体均值
    m_t1 = np.mean([r["t_v1"] for r in results])
    m_t2 = np.mean([r["t_v2"] for r in results])
    m_t3 = np.mean([r["t_v3"] for r in results])

    m_l1 = np.mean([r["dist_v1"] for r in results])
    m_l2 = np.mean([r["dist_v2"] for r in results])
    m_l3 = np.mean([r["dist_v3"] for r in results])

    m_meas1 = np.mean([r["meas_v1"] for r in results])
    m_meas2 = np.mean([r["meas_v2"] for r in results])
    m_meas3 = np.mean([r["meas_v3"] for r in results])

    tot_swaps = sum(r["head_swaps_v3"] for r in results)

    print(f"【六案例平均值对比】")
    print(f"  版本 1 (冻结基线版):         平均 T = {m_t1:.2f}s | 平均路程 L = {m_l1:.1f}m | 平均测量 = {m_meas1:.1f}次")
    print(f"  版本 2 (仅修评分版):         平均 T = {m_t2:.2f}s | 平均路程 L = {m_l2:.1f}m | 平均测量 = {m_meas2:.1f}次 | 净省时: {m_t1 - m_t2:+.2f}s")
    print(f"  版本 3 (修复评分+首任务2-opt): 平均 T = {m_t3:.2f}s | 平均路程 L = {m_l3:.1f}m | 平均测量 = {m_meas3:.1f}次 | 净省时: {m_t1 - m_t3:+.2f}s | 累计改首任务: {tot_swaps}次")
    print("=" * 125)

if __name__ == "__main__":
    run_benchmark()
