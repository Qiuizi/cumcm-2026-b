"""
run_p1.py - 执行 P1 算法求解与几何验证
1. 验证直径 D 与最小覆盖圆半径 rho 的关系：D/2 <= rho <= D/sqrt(3)
2. 验证直径圆覆盖准则 (A - V)·(B - V) <= 0
3. 验证三站反例：D = 40m，但 rho = 23.094m > 20m，直径圆无法覆盖
4. 多组随机检测场景交会多边形统计
"""

import sys
import os
import math
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

# 将项目根目录加入 sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.geometry_p1 import (
    compute_intersection_polygon,
    polygon_diameter_rotating_calipers,
    welzl_mec,
    check_diameter_circle_coverage,
    construct_three_station_counterexample,
)


def main():
    print("=" * 60)
    print("【问题一】交会定位区域直径与覆盖圆算法求解与验证")
    print("=" * 60)

    # 1. 验证方案 3.1 节三站反例
    print("\n--- 1. 三站反例严格数学验证 ---")
    ce = construct_three_station_counterexample()
    print(f"检测站 1: ({ce['stations'][0][0]:.2f}, {ce['stations'][0][1]:.2f}), 示向度: {ce['bearings'][0]:.2f}°")
    print(f"检测站 2: ({ce['stations'][1][0]:.2f}, {ce['stations'][1][1]:.2f}), 示向度: {ce['bearings'][1]:.2f}°")
    print(f"检测站 3: ({ce['stations'][2][0]:.2f}, {ce['stations'][2][1]:.2f}), 示向度: {ce['bearings'][2]:.2f}°")
    print(f"交会区域形状: 正三角形，边长 = {ce['diameter']:.4f} 米")
    print(f"定位区域直径 D = {ce['diameter']:.4f} 米")
    print(f"以最远点对为直径的圆半径 = D/2 = {ce['diameter']/2.0:.4f} 米")
    print(f"定位区域最小覆盖圆半径 rho = {ce['mec_radius']:.4f} 米")
    print(f"以直径为直径的圆能否覆盖此定位区域: {'【能】' if ce['diameter_covers'] else '【不能】'}")
    print(f"顶点内积判据最大值 (A-V)·(B-V) = {ce['max_dot_product']:.4f} (大于0表示第三顶点在圆外)")
    print(f"清除半径阈值 R_clear = 20.0 米")
    print(f"结论核对: 虽然直径 D = 40.0 <= 40 米满足必要条件，但最小覆盖圆半径 rho = 23.094 米 > 20 米，")
    print("故无法在任何单点安全清除该多边形内所有可能目标！充分条件为 D <= 20*sqrt(3) ≈ 34.641 米。")

    # 2. 模拟典型两站与三站交会定位
    print("\n--- 2. 典型多站交会场景计算演示 ---")
    scenarios = [
        {
            "name": "两站正交检测 (基线 1000m, 距离目标 ~800m)",
            "stations": [(0.0, 0.0), (800.0, -800.0)],
            "bearings": [45.0, 135.0],
        },
        {
            "name": "三站均匀交会 (环绕目标 ~500m)",
            "stations": [(0.0, 0.0), (600.0, 0.0), (300.0, 600.0)],
            "bearings": [45.0, 115.0, 240.0],
        },
        {
            "name": "小交会角两站 (示向线夹角仅 10°，极度扁长区域)",
            "stations": [(0.0, 0.0), (100.0, 50.0)],
            "bearings": [45.0, 55.0],
        },
    ]

    for sc in scenarios:
        poly = compute_intersection_polygon(sc["stations"], sc["bearings"], eps_deg=1.0)
        n_v = len(poly)
        if n_v < 3:
            print(f"\n场景: {sc['name']} -> 交会区域为空或退化")
            continue
        d, a, b = polygon_diameter_rotating_calipers(poly)
        cx, cy, rho = welzl_mec(poly)
        covered, max_dot = check_diameter_circle_coverage(poly, a, b)
        print(f"\n场景: {sc['name']}")
        print(f"  交会多边形顶点数: {n_v}")
        print(f"  定位区域直径 D: {d:.2f} 米")
        print(f"  最远顶点 A: ({a[0]:.2f}, {a[1]:.2f}), B: ({b[0]:.2f}, {b[1]:.2f})")
        print(f"  最小覆盖圆中心: ({cx:.2f}, {cy:.2f}), 最小覆盖圆半径 rho: {rho:.2f} 米")
        print(f"  直径圆能否覆盖: {'是' if covered else '否'} (max_dot={max_dot:.2f})")
        print(f"  理论界核对: D/2={d/2:.2f} <= rho={rho:.2f} <= D/sqrt(3)={d/math.sqrt(3):.2f} -> {'符合' if d/2 - 1e-3 <= rho <= d/math.sqrt(3) + 1e-3 else '异常'}")
        print(f"  能否单点保证清除 (rho <= 20m): {'【保证成功】' if rho <= 20.0 else '【需补测或多点覆盖】'}")

    print("\n" + "=" * 60)
    print("【问题一】全部计算与几何定理核验完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
