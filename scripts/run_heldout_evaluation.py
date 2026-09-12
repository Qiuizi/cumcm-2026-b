"""
run_heldout_evaluation.py - 在未参与调参的新案例集上对 B、C_greedy、C_openroute 进行全面配对评估
测试设计：
1. 覆盖 10、12、14、16 四种干扰源数量
2. 覆盖 20% (低)、50% (中)、80% (高) 三种定向源比例
3. 种子选择: 9101 ~ 9112 (完全独立于调参集 4000~5602)
4. 三版本在完全相同的场景和误差场下运行，算法不得读取真值
5. 详细输出每局总虚拟时间 T, T/N, 移动耗时, 其他动作耗时, 真实运行时间
6. 统计胜负、最大退步与计算开销
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

def run_heldout_benchmark():
    print("=" * 80, flush=True)
    print("【问题四】独立测试集 (Held-out Set) 盲测全量配对评估", flush=True)
    print("测试维度: 4 种源数量 (10, 12, 14, 16) x 3 种定向源比例 (20%, 50%, 80%) = 12 局", flush=True)
    print("=" * 80, flush=True)

    test_matrix = [
        # (case_id, n_src, dir_ratio, seed)
        ("H01-10src-dir20", 10, 0.20, 9101),
        ("H02-10src-dir50", 10, 0.50, 9102),
        ("H03-10src-dir80", 10, 0.80, 9103),
        ("H04-12src-dir20", 12, 0.20, 9104),
        ("H05-12src-dir50", 12, 0.50, 9105),
        ("H06-12src-dir80", 12, 0.80, 9106),
        ("H07-14src-dir20", 14, 0.20, 9107),
        ("H08-14src-dir50", 14, 0.50, 9108),
        ("H09-14src-dir80", 14, 0.80, 9109),
        ("H10-16src-dir20", 16, 0.20, 9110),
        ("H11-16src-dir50", 16, 0.50, 9111),
        ("H12-16src-dir80", 16, 0.80, 9112),
    ]

    records = []

    for idx, (case_id, n_src, dir_ratio, seed) in enumerate(test_matrix):
        print(f"\n[{idx+1}/12] 运行案例: {case_id} (源数={n_src}, 定向比例={dir_ratio*100:.0f}%, seed={seed})...", flush=True)

        # 1. Version B
        env_b = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=True, seed=seed, dir_ratio=dir_ratio)
        drv_b = LocalSimDriver(env_b)
        t0 = time.time()
        eng_b = StrategyEngine(driver=drv_b, is_p4=True, version="B", verbose=False)
        res_b = eng_b.execute()
        real_t_b = time.time() - t0
        b_move_t = env_b.total_distance_m / 5.0
        b_other_t = res_b["virtual_time_s"] - b_move_t

        # 2. Version C_greedy
        env_cg = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=True, seed=seed, dir_ratio=dir_ratio)
        drv_cg = LocalSimDriver(env_cg)
        t0 = time.time()
        eng_cg = StrategyEngine(driver=drv_cg, is_p4=True, version="C_GREEDY", verbose=False)
        res_cg = eng_cg.execute()
        real_t_cg = time.time() - t0
        cg_move_t = env_cg.total_distance_m / 5.0
        cg_other_t = res_cg["virtual_time_s"] - cg_move_t

        # 3. Version C_openroute
        env_co = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=True, seed=seed, dir_ratio=dir_ratio)
        drv_co = LocalSimDriver(env_co)
        t0 = time.time()
        eng_co = StrategyEngine(driver=drv_co, is_p4=True, version="C_OPENROUTE", verbose=False)
        res_co = eng_co.execute()
        real_t_co = time.time() - t0
        co_move_t = env_co.total_distance_m / 5.0
        co_other_t = res_co["virtual_time_s"] - co_move_t

        # 汇总行
        rec = {
            "case_id": case_id,
            "sources": n_src,
            "dir_ratio": dir_ratio,
            "seed": seed,
            # Version B
            "b_cleared": res_b["cleared_count"],
            "b_T": res_b["virtual_time_s"],
            "b_T_over_N": res_b["virtual_time_s"] / n_src,
            "b_move_t": b_move_t,
            "b_other_t": b_other_t,
            "b_real_t": real_t_b,
            "b_dist": env_b.total_distance_m,
            # Version C_greedy
            "cg_cleared": res_cg["cleared_count"],
            "cg_T": res_cg["virtual_time_s"],
            "cg_T_over_N": res_cg["virtual_time_s"] / n_src,
            "cg_move_t": cg_move_t,
            "cg_other_t": cg_other_t,
            "cg_real_t": real_t_cg,
            "cg_dist": env_cg.total_distance_m,
            # Version C_openroute
            "co_cleared": res_co["cleared_count"],
            "co_T": res_co["virtual_time_s"],
            "co_T_over_N": res_co["virtual_time_s"] / n_src,
            "co_move_t": co_move_t,
            "co_other_t": co_other_t,
            "co_real_t": real_t_co,
            "co_dist": env_co.total_distance_m,
            # Pairwise Deltas
            "co_minus_b": res_co["virtual_time_s"] - res_b["virtual_time_s"],
            "co_minus_cg": res_co["virtual_time_s"] - res_cg["virtual_time_s"],
        }
        records.append(rec)

        print(f"  [B]          T={rec['b_T']:7.1f}s | T/N={rec['b_T_over_N']:5.1f}s | 移动={rec['b_move_t']:6.1f}s | 其他={rec['b_other_t']:6.1f}s | 真实开销={rec['b_real_t']:.2f}s", flush=True)
        print(f"  [C_greedy]   T={rec['cg_T']:7.1f}s | T/N={rec['cg_T_over_N']:5.1f}s | 移动={rec['cg_move_t']:6.1f}s | 其他={rec['cg_other_t']:6.1f}s | 真实开销={rec['cg_real_t']:.2f}s", flush=True)
        print(f"  [C_openroute]T={rec['co_T']:7.1f}s | T/N={rec['co_T_over_N']:5.1f}s | 移动={rec['co_move_t']:6.1f}s | 其他={rec['co_other_t']:6.1f}s | 真实开销={rec['co_real_t']:.2f}s | 较B省时={-rec['co_minus_b']:+6.1f}s", flush=True)

    # 导出 CSV
    os.makedirs("results", exist_ok=True)
    csv_path = "results/p4_heldout_benchmark_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Case_ID", "Sources", "Dir_Ratio", "Seed",
            "B_Cleared", "B_T_virtual_s", "B_T_over_N_s", "B_Move_T_s", "B_Other_T_s", "B_Real_T_s", "B_Dist_m",
            "C_greedy_Cleared", "C_greedy_T_virtual_s", "C_greedy_T_over_N_s", "C_greedy_Move_T_s", "C_greedy_Other_T_s", "C_greedy_Real_T_s", "C_greedy_Dist_m",
            "C_openroute_Cleared", "C_openroute_T_virtual_s", "C_openroute_T_over_N_s", "C_openroute_Move_T_s", "C_openroute_Other_T_s", "C_openroute_Real_T_s", "C_openroute_Dist_m",
            "Time_Saved_C_open_vs_B_s", "Time_Saved_C_open_vs_C_greedy_s"
        ])
        for r in records:
            writer.writerow([
                r["case_id"], r["sources"], f"{r['dir_ratio']:.2f}", r["seed"],
                r["b_cleared"], f"{r['b_T']:.2f}", f"{r['b_T_over_N']:.2f}", f"{r['b_move_t']:.2f}", f"{r['b_other_t']:.2f}", f"{r['b_real_t']:.3f}", f"{r['b_dist']:.1f}",
                r["cg_cleared"], f"{r['cg_T']:.2f}", f"{r['cg_T_over_N']:.2f}", f"{r['cg_move_t']:.2f}", f"{r['cg_other_t']:.2f}", f"{r['cg_real_t']:.3f}", f"{r['cg_dist']:.1f}",
                r["co_cleared"], f"{r['co_T']:.2f}", f"{r['co_T_over_N']:.2f}", f"{r['co_move_t']:.2f}", f"{r['co_other_t']:.2f}", f"{r['co_real_t']:.3f}", f"{r['co_dist']:.1f}",
                f"{-r['co_minus_b']:.2f}", f"{-r['co_minus_cg']:.2f}"
            ])

    # 统计总结
    print("\n" + "=" * 80, flush=True)
    print("【独立测试集汇总统计指标】", flush=True)
    print("=" * 80, flush=True)
    tot_src = sum(r["sources"] for r in records)
    b_cleared = sum(r["b_cleared"] for r in records)
    cg_cleared = sum(r["cg_cleared"] for r in records)
    co_cleared = sum(r["co_cleared"] for r in records)

    b_mean_T = float(np.mean([r["b_T"] for r in records]))
    cg_mean_T = float(np.mean([r["cg_T"] for r in records]))
    co_mean_T = float(np.mean([r["co_T"] for r in records]))

    b_mean_ton = float(np.mean([r["b_T_over_N"] for r in records]))
    cg_mean_ton = float(np.mean([r["cg_T_over_N"] for r in records]))
    co_mean_ton = float(np.mean([r["co_T_over_N"] for r in records]))

    b_mean_move = float(np.mean([r["b_move_t"] for r in records]))
    cg_mean_move = float(np.mean([r["cg_move_t"] for r in records]))
    co_mean_move = float(np.mean([r["co_move_t"] for r in records]))

    b_mean_other = float(np.mean([r["b_other_t"] for r in records]))
    cg_mean_other = float(np.mean([r["cg_other_t"] for r in records]))
    co_mean_other = float(np.mean([r["co_other_t"] for r in records]))

    b_mean_real = float(np.mean([r["b_real_t"] for r in records]))
    cg_mean_real = float(np.mean([r["cg_real_t"] for r in records]))
    co_mean_real = float(np.mean([r["co_real_t"] for r in records]))

    # 配对胜负
    wins_vs_b = sum(1 for r in records if r["co_T"] < r["b_T"])
    ties_vs_b = sum(1 for r in records if abs(r["co_T"] - r["b_T"]) < 1e-3)
    loss_vs_b = len(records) - wins_vs_b - ties_vs_b

    wins_vs_cg = sum(1 for r in records if r["co_T"] < r["cg_T"])
    ties_vs_cg = sum(1 for r in records if abs(r["co_T"] - r["cg_T"]) < 1e-3)
    loss_vs_cg = len(records) - wins_vs_cg - ties_vs_cg

    # 最大退步 (最坏情况)
    max_deg_vs_b = max(r["co_minus_b"] for r in records) # 越大说明 C 比 B 慢得越多
    worst_case_vs_b = [r["case_id"] for r in records if r["co_minus_b"] == max_deg_vs_b][0]

    max_deg_vs_cg = max(r["co_minus_cg"] for r in records)
    worst_case_vs_cg = [r["case_id"] for r in records if r["co_minus_cg"] == max_deg_vs_cg][0]

    print(f"总目标数:                  {tot_src} 个 (12 案例)", flush=True)
    print(f"完整清除率 (Clearance):", flush=True)
    print(f"  版本 B:          {b_cleared}/{tot_src} ({b_cleared/tot_src*100:.1f}%)", flush=True)
    print(f"  版本 C_greedy:   {cg_cleared}/{tot_src} ({cg_cleared/tot_src*100:.1f}%)", flush=True)
    print(f"  版本 C_openroute:{co_cleared}/{tot_src} ({co_cleared/tot_src*100:.1f}%)", flush=True)
    print(f"---------------------------------------------------------------------------", flush=True)
    print(f"均值指标 (Mean Metrics):", flush=True)
    print(f"  指标项                版本 B          版本 C_greedy   版本 C_openroute", flush=True)
    print(f"  虚拟总时间 T (s):     {b_mean_T:8.2f}        {cg_mean_T:8.2f}        {co_mean_T:8.2f}", flush=True)
    print(f"  平均单目标 T/N (s):   {b_mean_ton:8.2f}        {cg_mean_ton:8.2f}        {co_mean_ton:8.2f}", flush=True)
    print(f"  移动耗时 (s):         {b_mean_move:8.2f}        {cg_mean_move:8.2f}        {co_mean_move:8.2f}", flush=True)
    print(f"  其他动作耗时 (s):     {b_mean_other:8.2f}        {cg_mean_other:8.2f}        {co_mean_other:8.2f}", flush=True)
    print(f"  真实运行耗时 (s):     {b_mean_real:8.2f}        {cg_mean_real:8.2f}        {co_mean_real:8.2f}", flush=True)
    print(f"---------------------------------------------------------------------------", flush=True)
    print(f"配对胜负统计 (Head-to-Head):", flush=True)
    print(f"  C_openroute vs 版本 B:        {wins_vs_b} 胜 / {loss_vs_b} 负 / {ties_vs_b} 平 (胜率: {wins_vs_b/len(records)*100:.1f}%)", flush=True)
    print(f"  C_openroute vs 版本 C_greedy: {wins_vs_cg} 胜 / {loss_vs_cg} 负 / {ties_vs_cg} 平 (胜率: {wins_vs_cg/len(records)*100:.1f}%)", flush=True)
    print(f"---------------------------------------------------------------------------", flush=True)
    print(f"尾部表现与最大退步 (Worst-case Tail Risk):", flush=True)
    print(f"  C_openroute 相比 B 最大退步:       +{max_deg_vs_b:.2f} s ({worst_case_vs_b})", flush=True)
    print(f"  C_openroute 相比 C_greedy 最大退步: +{max_deg_vs_cg:.2f} s ({worst_case_vs_cg})", flush=True)
    print(f"  C_openroute 相比 B 平均省时:       {b_mean_T - co_mean_T:+8.2f} s (T/N 变化: {b_mean_ton - co_mean_ton:+6.2f} s)", flush=True)
    print(f"===========================================================================", flush=True)


if __name__ == "__main__":
    run_heldout_benchmark()
