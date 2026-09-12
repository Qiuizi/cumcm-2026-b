"""
candidate_p2.py - P2 第二检测点候选区域与综合成本排序计算
实现：
1. 充分候选区域 Gamma_0 的几何与不等式定义与网格生成 (25米步长)
2. 128 个合法先验场景的蒙特卡洛抽样
3. 候选点第二测点反馈与二次定位交会多边形生成
4. 综合预期成本 J_2(q) = 移动时间 + 测量时间 + 平均清除成本
5. 近优区域 R_30 = {q in Gamma_0: J_2(q) <= min J_2 + 30s} 提取
"""

import math
import numpy as np
from src.geometry_p1 import (
    get_bearing_halfplanes,
    clip_polygon_by_halfplane,
    polygon_diameter_rotating_calipers,
    welzl_mec,
)


def is_in_gamma0(a: float, b: float, eps_deg: float = 1.005) -> bool:
    """
    判断局部坐标 (a, b) 是否属于 Gamma_0
    a >= 0, a^2 + b^2 <= 1000^2, a^2 + b^2 <= 2000*(a*cos(eps) - |b|*sin(eps))
    """
    if a < 1e-6:
        return False
    r2 = a * a + b * b
    if r2 > 1000.0**2:
        return False
    eps_rad = math.radians(eps_deg)
    bound = 2000.0 * (a * math.cos(eps_rad) - abs(b) * math.sin(eps_rad))
    return r2 <= bound + 1e-7


def generate_gamma0_grid(step: float = 25.0, eps_deg: float = 1.005):
    """
    在 Gamma_0 内生成 step 间距的候选格点 (a, b)
    """
    candidates = []
    a_vals = np.arange(step, 1000.0 + 1e-3, step)
    # b 最大范围不超过 1000*sin(eps) ~ 17.5m? 不，不等式允许的 b 范围：
    # a^2 + b^2 <= 2000 a cos(eps) - 2000 |b| sin(eps)
    # 当 a=500 时，b 可以达到很大。我们扫描 b in [-1000, 1000]
    b_max = 1000.0
    for a in a_vals:
        # 对应 a 的可能 b 范围
        b_lim = math.sqrt(max(0.0, 1000.0**2 - a * a))
        b_vals = np.arange(-b_lim, b_lim + 1e-3, step)
        for b in b_vals:
            if is_in_gamma0(a, b, eps_deg):
                candidates.append((float(a), float(b)))
    return candidates


def generate_p2_scenarios(
    n_scenarios: int = 128, eps_deg: float = 1.0, seed: int = 2026
):
    """
    生成 128 个合法先验场景 (真实目标位置 x_s, 接收半径 R_s, 首测误差 e1_s)
    在局部坐标系中，首测示向为 +a 轴 (0 度)
    距离概率密度正比于 r * P(R >= r)
    """
    rng = np.random.default_rng(seed)
    scenarios = []

    # 拒绝抽样生成符合分布的目标
    count = 0
    while count < n_scenarios:
        # R 在 [1000, 1500] 独立均匀分布
        R = rng.uniform(1000.0, 1500.0)
        # r 采样在 (5, 1500]
        r = rng.uniform(5.0, 1500.0)
        if r > R:
            continue
        # 面积均匀权重为 r，因此接受概率正比于 r / 1500
        if rng.uniform(0.0, 1500.0) > r:
            continue

        # 首测误差 e1 in [-eps, eps]
        e1 = rng.uniform(-eps_deg, eps_deg)
        # 真实目标偏角相对于首测示向线为 -e1
        target_angle_rad = math.radians(-e1)
        tx = r * math.cos(target_angle_rad)
        ty = r * math.sin(target_angle_rad)

        scenarios.append(
            {
                "tx": tx,
                "ty": ty,
                "r": r,
                "R": R,
                "e1": e1,
            }
        )
        count += 1
    return scenarios


def evaluate_candidate_point(
    a: float,
    b: float,
    scenarios: list,
    eps_deg: float = 1.0,
    seed_noise: int = 42,
):
    """
    评估单个候选点 q = (a, b) 的综合指标 J_2(q)
    J_2(q) = ||q - p1|| / 5 + 5 + mean(T_clear(C_{2,s}, q))
    """
    dist_move = math.hypot(a, b)
    t_move = dist_move / 5.0
    t_measure = 5.0

    t_clears = []
    rhos = []
    diams = []

    rng = np.random.default_rng(seed_noise + int(a * 100 + b))

    # 首测半平面 (p1=(0,0), 示向度 0 度)
    p1_hps = get_bearing_halfplanes(0.0, 0.0, 0.0, eps_deg)

    for sc in scenarios:
        tx, ty = sc["tx"], sc["ty"]
        # q 到真实目标的距离
        dq = math.hypot(tx - a, ty - b)

        if dq <= 5.0:
            # 触发 near 信号！直接在当前点清除，0 移动，5 秒成功
            t_clears.append(5.0)
            rhos.append(0.0)
            diams.append(0.0)
            continue

        # 正常接收信号：q 点测得示向度 = 真实方向 + 测向误差 e2
        true_bearing_q = math.degrees(math.atan2(ty - b, tx - a))
        e2 = rng.uniform(-eps_deg, eps_deg)
        bearing_q = true_bearing_q + e2

        # 构建交会多边形
        # 初始多边形取较大外框
        box = [(-2000.0, -2000.0), (2000.0, -2000.0), (2000.0, 2000.0), (-2000.0, 2000.0)]
        # 裁首测半平面
        poly = box
        for nx, ny, c in p1_hps:
            poly = clip_polygon_by_halfplane(poly, nx, ny, c)
            if not poly:
                break
        # 裁第二测点半平面
        if poly:
            q_hps = get_bearing_halfplanes(a, b, bearing_q, eps_deg)
            for nx, ny, c in q_hps:
                poly = clip_polygon_by_halfplane(poly, nx, ny, c)
                if not poly:
                    break

        if not poly or len(poly) < 3:
            # 退化情况，保守估计
            t_clears.append(dq / 5.0 + 5.0)
            rhos.append(20.0)
            diams.append(40.0)
            continue

        diam, vA, vB = polygon_diameter_rotating_calipers(poly)
        mc_x, mc_y, rho = welzl_mec(poly)
        rhos.append(rho)
        diams.append(diam)

        if rho <= 20.0:
            # 最小覆盖圆半径 <= 20，走到圆心处清除必成功
            d_to_c = math.hypot(mc_x - a, mc_y - b)
            t_c = d_to_c / 5.0 + 5.0
            t_clears.append(t_c)
        else:
            # rho > 20，需要两点或多点覆盖清除
            # 采用贪心 20米圆覆盖最坏耗时
            # 近似为沿直径两端布置覆盖圆
            n_circles = max(2, math.ceil(diam / 34.64))
            # 移动走完所有覆盖圆并清除 (每次清除尝试失败计 3s，最后成功 5s)
            extra_move = diam
            t_c = (math.hypot(mc_x - a, mc_y - b) + extra_move) / 5.0 + 3.0 * (n_circles - 1) + 5.0
            t_clears.append(t_c)

    mean_t_clear = float(np.mean(t_clears))
    mean_rho = float(np.mean(rhos))
    mean_diam = float(np.mean(diams))

    j2 = t_move + t_measure + mean_t_clear

    return {
        "a": a,
        "b": b,
        "dist_move": dist_move,
        "t_move": t_move,
        "t_measure": t_measure,
        "mean_t_clear": mean_t_clear,
        "mean_rho": mean_rho,
        "mean_diam": mean_diam,
        "J2": j2,
    }


def solve_p2_optimization(step: float = 25.0, eps_deg: float = 1.005):
    """
    完整执行 P2 网格搜索与近优区域提取
    """
    candidates = generate_gamma0_grid(step=step, eps_deg=eps_deg)
    scenarios = generate_p2_scenarios(n_scenarios=128, eps_deg=1.0, seed=2026)

    results = []
    for a, b in candidates:
        res = evaluate_candidate_point(a, b, scenarios, eps_deg=1.0)
        results.append(res)

    results.sort(key=lambda x: x["J2"])
    best = results[0]
    min_j2 = best["J2"]

    # 提取 R30 近优区域
    r30 = [r for r in results if r["J2"] <= min_j2 + 30.0]

    return {
        "all_results": results,
        "best": best,
        "min_J2": min_j2,
        "R30": r30,
        "total_candidates": len(candidates),
        "r30_count": len(r30),
    }
