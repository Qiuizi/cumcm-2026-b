"""
run_p4_benchmark.py - 问题四定向与全向混合场景批量评测与三版本对比
评测规则：
1. 10、13、16 干扰源分层评测 (含未知定向源与随机发射朝向，共 9 组配对案例)
2. 同案例三方对比：版本 B (固定覆盖) vs 版本 C_greedy (最近邻贪心) vs 版本 C_openroute (开放路线重排)
3. 导出 CSV 报告与论文表 1 标准格式结果
"""

import sys
import os
import csv
import time
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine


def run_benchmark(n_cases_per_group: int = 3):
    print("=" * 75, flush=True)
    print("【问题四】三方案同案例配对全量评测 (版本 B vs C_greedy vs C_openroute)", flush=True)
    print("=" * 75, flush=True)

    groups = [10, 13, 16]
    records = []

    for n_src in groups:
        print(f"\n>>> 正在评测源数量: {n_src} 个 (含定向源与随机发射角，各评测 {n_cases_per_group} 组案例) <<<", flush=True)
        for i in range(n_cases_per_group):
            seed = 4000 + n_src * 100 + i
            case_id = f"P4-{n_src}src-case{i+1}"

            # 版本 B
            env_b = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=True, seed=seed)
            driver_b = LocalSimDriver(env_b)
            eng_b = StrategyEngine(driver=driver_b, is_p4=True, version="B", verbose=False)
            res_b = eng_b.execute()

            # 版本 C_greedy
            env_cg = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=True, seed=seed)
            driver_cg = LocalSimDriver(env_cg)
            eng_cg = StrategyEngine(driver=driver_cg, is_p4=True, version="C_GREEDY", verbose=False)
            res_cg = eng_cg.execute()

            # 版本 C_openroute
            env_co = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=True, seed=seed)
            driver_co = LocalSimDriver(env_co)
            eng_co = StrategyEngine(driver=driver_co, is_p4=True, version="C_OPENROUTE", verbose=False)
            res_co = eng_co.execute()

            record = {
                "case_id": case_id,
                "sources": n_src,
                "b_cleared": res_b["cleared_count"],
                "b_T": res_b["virtual_time_s"],
                "b_dist": env_b.total_distance_m,
                "cg_cleared": res_cg["cleared_count"],
                "cg_T": res_cg["virtual_time_s"],
                "cg_dist": env_cg.total_distance_m,
                "co_cleared": res_co["cleared_count"],
                "co_T": res_co["virtual_time_s"],
                "co_dist": env_co.total_distance_m,
                "save_vs_b": res_b["virtual_time_s"] - res_co["virtual_time_s"],
                "save_vs_cg": res_cg["virtual_time_s"] - res_co["virtual_time_s"],
            }
            records.append(record)
            print(f"  [{case_id}] B耗时: {res_b['virtual_time_s']:7.1f}s ({env_b.total_distance_m:6.0f}m) | "
                  f"C_greedy: {res_cg['virtual_time_s']:7.1f}s ({env_cg.total_distance_m:6.0f}m) | "
                  f"C_open: {res_co['virtual_time_s']:7.1f}s ({env_co.total_distance_m:6.0f}m) | "
                  f"C_open相比B省时: {record['save_vs_b']:+6.1f}s", flush=True)

    # 导出 CSV
    os.makedirs("results", exist_ok=True)
    csv_path = "results/p4_benchmark_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Case_ID", "Sources",
            "B_Cleared", "B_T_virtual_s", "B_Move_dist_m",
            "C_greedy_Cleared", "C_greedy_T_virtual_s", "C_greedy_Move_dist_m",
            "C_openroute_Cleared", "C_openroute_T_virtual_s", "C_openroute_Move_dist_m",
            "Time_Saved_vs_B_s", "Time_Saved_vs_C_greedy_s",
        ])
        for r in records:
            writer.writerow([
                r["case_id"], r["sources"],
                r["b_cleared"], f"{r['b_T']:.2f}", f"{r['b_dist']:.1f}",
                r["cg_cleared"], f"{r['cg_T']:.2f}", f"{r['cg_dist']:.1f}",
                r["co_cleared"], f"{r['co_T']:.2f}", f"{r['co_dist']:.1f}",
                f"{r['save_vs_b']:.2f}", f"{r['save_vs_cg']:.2f}",
            ])

    print("\n" + "=" * 75, flush=True)
    print("【问题四】批量评测三方案统计汇总", flush=True)
    print("=" * 75, flush=True)
    tot_src = sum(r["sources"] for r in records)
    b_cleared_tot = sum(r["b_cleared"] for r in records)
    cg_cleared_tot = sum(r["cg_cleared"] for r in records)
    co_cleared_tot = sum(r["co_cleared"] for r in records)

    b_mean_T = float(np.mean([r["b_T"] for r in records]))
    cg_mean_T = float(np.mean([r["cg_T"] for r in records]))
    co_mean_T = float(np.mean([r["co_T"] for r in records]))

    b_mean_dist = float(np.mean([r["b_dist"] for r in records]))
    cg_mean_dist = float(np.mean([r["cg_dist"] for r in records]))
    co_mean_dist = float(np.mean([r["co_dist"] for r in records]))

    # 最坏案例退步分析
    worst_vs_b = min(r["save_vs_b"] for r in records)
    worst_case_id = [r["case_id"] for r in records if r["save_vs_b"] == worst_vs_b][0]

    print(f"总目标数:                  {tot_src} 个", flush=True)
    print(f"版本 B 总清除率:           {b_cleared_tot}/{tot_src} ({b_cleared_tot/tot_src*100:.1f}%) | 平均耗时: {b_mean_T:7.2f}s | 平均路程: {b_mean_dist:.1f}m", flush=True)
    print(f"版本 C_greedy 总清除率:    {cg_cleared_tot}/{tot_src} ({cg_cleared_tot/tot_src*100:.1f}%) | 平均耗时: {cg_mean_T:7.2f}s | 平均路程: {cg_mean_dist:.1f}m", flush=True)
    print(f"版本 C_openroute 总清除率: {co_cleared_tot}/{tot_src} ({co_cleared_tot/tot_src*100:.1f}%) | 平均耗时: {co_mean_T:7.2f}s | 平均路程: {co_mean_dist:.1f}m", flush=True)
    print(f"---------------------------------------------------------------------------", flush=True)
    print(f"C_openroute 相比 B 平均省时:         {b_mean_T - co_mean_T:+7.2f}s (路程压缩 {b_mean_dist - co_mean_dist:+.1f}m)", flush=True)
    print(f"C_openroute 相比 C_greedy 平均省时:  {cg_mean_T - co_mean_T:+7.2f}s (路程压缩 {cg_mean_dist - co_mean_dist:+.1f}m)", flush=True)
    print(f"最坏退步案例:                       {worst_case_id} (省时: {worst_vs_b:+.2f}s)", flush=True)
    print("=" * 75, flush=True)


if __name__ == "__main__":
    run_benchmark(n_cases_per_group=3)
