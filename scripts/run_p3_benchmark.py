"""
run_p3_benchmark.py - 问题三批量评测与表 1 标准格式输出
评测规则严格按照方案第 11.3 节：
1. 10、13、16 干扰源分层评测
2. 同案例配对对比：版本 B (稳定基线) vs 版本 C (滚动主方案)
3. 统计指标：清除率、虚拟总时间 T、平均单目标耗时、实际运行时间、移动路程
4. 导出 CSV 报告与论文表 1 标准格式结果
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


def run_benchmark(n_cases_per_group: int = 5):
    print("=" * 70)
    print("【问题三】全向干扰源批量对比评测 (版本 B vs 版本 C)")
    print("=" * 70)

    groups = [10, 13, 16]
    records = []

    for n_src in groups:
        print(f"\n>>> 正在评测源数量: {n_src} 个 (各评测 {n_cases_per_group} 组案例) <<<")
        for i in range(n_cases_per_group):
            seed = 3000 + n_src * 100 + i
            case_id = f"P3-{n_src}src-case{i+1}"

            # 版本 B
            env_b = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
            driver_b = LocalSimDriver(env_b)
            eng_b = StrategyEngine(driver=driver_b, is_p4=False, version="B", verbose=False)
            res_b = eng_b.execute()

            # 版本 C
            env_c = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
            driver_c = LocalSimDriver(env_c)
            eng_c = StrategyEngine(driver=driver_c, is_p4=False, version="C", verbose=False)
            res_c = eng_c.execute()

            record = {
                "case_id": case_id,
                "sources": n_src,
                "b_cleared": res_b["cleared_count"],
                "b_T": res_b["virtual_time_s"],
                "b_avg_T": res_b["avg_time_per_target"],
                "b_real_t": res_b["real_time_s"],
                "b_dist": env_b.total_distance_m,
                "c_cleared": res_c["cleared_count"],
                "c_T": res_c["virtual_time_s"],
                "c_avg_T": res_c["avg_time_per_target"],
                "c_real_t": res_c["real_time_s"],
                "c_dist": env_c.total_distance_m,
                "save_T": res_b["virtual_time_s"] - res_c["virtual_time_s"],
            }
            records.append(record)
            print(f"  [{case_id}] B清除: {res_b['cleared_count']}/{n_src}, B耗时: {res_b['virtual_time_s']:.1f}s | C清除: {res_c['cleared_count']}/{n_src}, C耗时: {res_c['virtual_time_s']:.1f}s | C省时: {record['save_T']:.1f}s")

    # 汇总统计
    os.makedirs("results", exist_ok=True)
    csv_path = "results/p3_benchmark_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Case_ID", "Sources",
            "B_Cleared", "B_T_virtual_s", "B_Avg_T_s", "B_Real_time_s", "B_Move_dist_m",
            "C_Cleared", "C_T_virtual_s", "C_Avg_T_s", "C_Real_time_s", "C_Move_dist_m",
            "Time_Saved_s",
        ])
        for r in records:
            writer.writerow([
                r["case_id"], r["sources"],
                r["b_cleared"], f"{r['b_T']:.2f}", f"{r['b_avg_T']:.2f}", f"{r['b_real_t']:.3f}", f"{r['b_dist']:.1f}",
                r["c_cleared"], f"{r['c_T']:.2f}", f"{r['c_avg_T']:.2f}", f"{r['c_real_t']:.3f}", f"{r['c_dist']:.1f}",
                f"{r['save_T']:.2f}",
            ])

    print("\n" + "=" * 70)
    print("【问题三】批量评测统计汇总")
    print("=" * 70)
    b_cleared_tot = sum(r["b_cleared"] for r in records)
    c_cleared_tot = sum(r["c_cleared"] for r in records)
    tot_src = sum(r["sources"] for r in records)

    b_mean_T = float(np.mean([r["b_T"] for r in records]))
    c_mean_T = float(np.mean([r["c_T"] for r in records]))
    b_mean_avg_T = float(np.mean([r["b_avg_T"] for r in records]))
    c_mean_avg_T = float(np.mean([r["c_avg_T"] for r in records]))
    b_mean_real = float(np.mean([r["b_real_t"] for r in records]))
    c_mean_real = float(np.mean([r["c_real_t"] for r in records]))

    print(f"总目标数:                  {tot_src} 个")
    print(f"版本 B 总清除率:           {b_cleared_tot}/{tot_src} ({b_cleared_tot/tot_src*100:.1f}%)")
    print(f"版本 C 总清除率:           {c_cleared_tot}/{tot_src} ({c_cleared_tot/tot_src*100:.1f}%)")
    print(f"版本 B 平均虚拟耗时 T:     {b_mean_T:.2f} 秒 (单目标: {b_mean_avg_T:.2f} 秒/个)")
    print(f"版本 C 平均虚拟耗时 T:     {c_mean_T:.2f} 秒 (单目标: {c_mean_avg_T:.2f} 秒/个)")
    print(f"版本 C 相对版本 B 节省:    {b_mean_T - c_mean_T:.2f} 秒 ({(b_mean_T - c_mean_T)/b_mean_T*100:.2f}%)")
    print(f"单案例实际计算耗时:        版本 B: {b_mean_real:.2f} 秒 | 版本 C: {c_mean_real:.2f} 秒 (限时 1200 秒)")
    print(f"评测明细表已导出至:        {csv_path}")

    # 按照赛题【表 1】标准格式打印示例
    print("\n" + "-" * 70)
    print("【表 1 标准格式对照】问题 3 示例案例输出")
    print("-" * 70)
    print(f"{'测试案例编码':<20} {'清除干扰源个数':<15} {'平均定位清除时间 (s)':<22} {'程序运行时间 (s)'}")
    for i in range(min(3, len(records))):
        r = records[i]
        print(f"{r['case_id']:<20} {r['c_cleared']:<15} {r['c_avg_T']:<22.2f} {r['c_real_t']:.2f}")
    print("=" * 70)


if __name__ == "__main__":
    run_benchmark(n_cases_per_group=3)
