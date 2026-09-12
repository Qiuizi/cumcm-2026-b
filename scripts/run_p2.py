"""
run_p2.py - 运行问题二第二检测点选址求解与分析
1. 生成 Gamma_0 充分候选区域并在 25m 网格上评估
2. 统计最优第二检测点坐标、移动时间、测量耗时、平均清除时间与综合代价 J2
3. 提取 R30 近优候选区域并输出统计特征
4. 输出对比与灵敏度表格
"""

import sys
import os
import csv
import math
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.candidate_p2 import solve_p2_optimization


def main():
    print("=" * 60)
    print("【问题二】第二检测点选址策略与候选区域 Gamma_0 求解")
    print("=" * 60)

    print("正在评估 Gamma_0 候选区域 (步长 25 米，128 个合法先验场景)...")
    res = solve_p2_optimization(step=25.0, eps_deg=1.005)

    best = res["best"]
    min_j2 = res["min_J2"]
    r30 = res["R30"]
    total = res["total_candidates"]
    r30_count = res["r30_count"]

    print(f"\nGamma_0 内有效网格候选点总数: {total} 个")
    print(f"R_30 近优区域网格点数: {r30_count} 个 (占总候选点 {r30_count/total*100:.1f}%)")

    print("\n--- 最优第二检测点数值结果 ---")
    print(f"局部坐标 a (示向方向): {best['a']:.2f} 米")
    print(f"局部坐标 b (侧移方向): {best['b']:.2f} 米")
    print(f"相对首测点移动距离: {best['dist_move']:.2f} 米")
    print(f"移动时间 T_move: {best['t_move']:.2f} 秒")
    print(f"测量时间 T_measure: {best['t_measure']:.2f} 秒")
    print(f"平均后续定位清除耗时 T_clear: {best['mean_t_clear']:.2f} 秒")
    print(f"测后交会区域平均直径 D: {best['mean_diam']:.2f} 米")
    print(f"测后最小覆盖圆平均半径 rho: {best['mean_rho']:.2f} 米")
    print(f"★ 综合预期总耗时 J_2(q*): {best['J2']:.2f} 秒")

    # R30 统计
    r30_a = [p["a"] for p in r30]
    r30_b = [p["b"] for p in r30]
    print("\n--- R_30 近优区域几何范围 (J_2 <= min J_2 + 30s) ---")
    print(f"示向坐标 a 范围: [{min(r30_a):.1f}, {max(r30_a):.1f}] 米")
    print(f"侧移坐标 b 范围: [{min(r30_b):.1f}, {max(r30_b):.1f}] 米")
    print(f"近优区域移动距离范围: [{min([p['dist_move'] for p in r30]):.1f}, {max([p['dist_move'] for p in r30]):.1f}] 米")

    # 保存结果到 CSV
    os.makedirs("results", exist_ok=True)
    csv_path = os.path.join("results", "p2_optimization_results.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["a", "b", "dist_move", "t_move", "mean_t_clear", "mean_diam", "mean_rho", "J2", "in_R30"])
        for r in res["all_results"]:
            writer.writerow([
                r["a"], r["b"], f"{r['dist_move']:.2f}", f"{r['t_move']:.2f}",
                f"{r['mean_t_clear']:.2f}", f"{r['mean_diam']:.2f}", f"{r['mean_rho']:.2f}",
                f"{r['J2']:.2f}", "1" if r["J2"] <= min_j2 + 30.0 else "0"
            ])
    print(f"\n完整优化结果已导出至: {csv_path}")
    print("\n" + "=" * 60)
    print("【问题二】求解与近优区域分析完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
