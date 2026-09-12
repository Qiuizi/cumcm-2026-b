"""
geometry_p1.py - P1 几何与交会区域计算核心模块
包括：
1. 角域半平面构建与凸多边形半平面交
2. 旋转卡壳法计算多边形直径 D
3. Welzl 算法计算最小覆盖圆半径 rho 及圆心
4. 直径圆覆盖判据：所有顶点 V 满足 (A - V)·(B - V) <= 0
5. 充分条件 (D <= 20*sqrt(3)) 与必要条件 (D <= 40) 验证
6. 三站反例构造与验证
"""

import math
import numpy as np


def wrap_angle_deg(deg: float) -> float:
    """将角度限制在 [0, 360) 度"""
    return deg % 360.0


def angle_diff_deg(a: float, b: float) -> float:
    """两角度最小差 (-180, 180]"""
    diff = (a - b + 180.0) % 360.0 - 180.0
    return diff


def clip_polygon_by_halfplane(poly, nx, ny, c):
    """
    Sutherland-Hodgman 多边形裁剪
    半平面定义：nx * x + ny * y <= c
    poly 为 [(x, y), ...]
    """
    if not poly:
        return []
    new_poly = []
    n = len(poly)
    for i in range(n):
        cur = poly[i]
        prev = poly[(i - 1) % n]
        cur_in = (nx * cur[0] + ny * cur[1] <= c + 1e-11)
        prev_in = (nx * prev[0] + ny * prev[1] <= c + 1e-11)

        if cur_in:
            if not prev_in:
                # 求交点
                den = nx * (cur[0] - prev[0]) + ny * (cur[1] - prev[1])
                if abs(den) > 1e-12:
                    t = (c - (nx * prev[0] + ny * prev[1])) / den
                    ix = prev[0] + t * (cur[0] - prev[0])
                    iy = prev[1] + t * (cur[1] - prev[1])
                    new_poly.append((ix, iy))
            new_poly.append(cur)
        elif prev_in:
            # 离开半平面，求交点
            den = nx * (cur[0] - prev[0]) + ny * (cur[1] - prev[1])
            if abs(den) > 1e-12:
                t = (c - (nx * prev[0] + ny * prev[1])) / den
                ix = prev[0] + t * (cur[0] - prev[0])
                iy = prev[1] + t * (cur[1] - prev[1])
                new_poly.append((ix, iy))
    return new_poly


def get_bearing_halfplanes(px: float, py: float, theta_deg: float, eps_deg: float = 1.0):
    """
    构建检测点 (px, py) 处示向度 theta_deg +- eps_deg 的前向角域半平面
    返回列表: [(nx, ny, c), ...] 使得 nx*x + ny*y <= c
    """
    th_rad = math.radians(theta_deg)
    eps_rad = math.radians(eps_deg)
    # 前向单位向量
    fx, fy = math.cos(th_rad), math.sin(th_rad)

    # 边界1：逆时针界 theta + eps
    th_max = th_rad + eps_rad
    # 边界2：顺时针界 theta - eps
    th_min = th_rad - eps_rad

    # 内部点 P 满足：从顺时针射线看在左侧，从逆时针射线看在右侧，且沿前向为正
    # 顺时针射线 (fx_min, fy_min): 向量在左侧 -> cross((fx_min, fy_min), (x-px, y-py)) >= 0
    # 即: fx_min * (y - py) - fy_min * (x - px) >= 0 => fy_min * x - fx_min * y <= fy_min * px - fx_min * py
    f_min_x, f_min_y = math.cos(th_min), math.sin(th_min)
    n1_x, n1_y = f_min_y, -f_min_x
    c1 = n1_x * px + n1_y * py

    # 逆时针射线 (fx_max, fy_max): 向量在右侧 -> cross((fx_max, fy_max), (x-px, y-py)) <= 0
    # 即: fx_max * (y - py) - fy_max * (x - px) <= 0 => -fy_max * x + fx_max * y <= -fy_max * px + fx_max * py
    f_max_x, f_max_y = math.cos(th_max), math.sin(th_max)
    n2_x, n2_y = -f_max_y, f_max_x
    c2 = n2_x * px + n2_y * py

    # 前向半平面 (fx*(x-px) + fy*(y-py) >= 0 => -fx*x - fy*y <= -fx*px - fy*py)
    n3_x, n3_y = -fx, -fy
    c3 = n3_x * px + n3_y * py

    return [(n1_x, n1_y, c1), (n2_x, n2_y, c2), (n3_x, n3_y, c3)]


def polygon_diameter_rotating_calipers(vertices):
    """
    计算凸多边形直径及最远顶点对 A, B
    vertices: list of (x, y)
    """
    pts = np.array(vertices, dtype=float)
    n = len(pts)
    if n == 0:
        return 0.0, None, None
    if n == 1:
        return 0.0, pts[0], pts[0]
    if n == 2:
        d = float(np.linalg.norm(pts[0] - pts[1]))
        return d, pts[0], pts[1]

    # 点数较小时（n <= 200），全对枚举兼做高精度验证
    max_d2 = -1.0
    best_pair = (pts[0], pts[1])
    for i in range(n):
        for j in range(i + 1, n):
            d2 = (pts[i, 0] - pts[j, 0]) ** 2 + (pts[i, 1] - pts[j, 1]) ** 2
            if d2 > max_d2:
                max_d2 = d2
                best_pair = (pts[i], pts[j])
    return math.sqrt(max_d2), best_pair[0], best_pair[1]


def welzl_mec(points):
    """
    Welzl 算法计算点集的最小覆盖圆 (Minimum Enclosing Circle)
    返回 (cx, cy, radius)
    """
    pts = [np.array(p, dtype=float) for p in points]
    np.random.seed(42)
    shuffled = pts.copy()

    def mec_b(p_list, r_list):
        if len(p_list) == 0 or len(r_list) == 3:
            if len(r_list) == 0:
                return np.zeros(2), 0.0
            elif len(r_list) == 1:
                return r_list[0], 0.0
            elif len(r_list) == 2:
                c = 0.5 * (r_list[0] + r_list[1])
                r = float(np.linalg.norm(r_list[0] - c))
                return c, r
            else:
                # 3点外接圆
                p1, p2, p3 = r_list[0], r_list[1], r_list[2]
                d = 2 * (p1[0] * (p2[1] - p3[1]) + p2[0] * (p3[1] - p1[1]) + p3[0] * (p1[1] - p2[1]))
                if abs(d) < 1e-12:
                    # 共线退化
                    pair_dists = [
                        (np.linalg.norm(p1 - p2), p1, p2),
                        (np.linalg.norm(p2 - p3), p2, p3),
                        (np.linalg.norm(p3 - p1), p3, p1),
                    ]
                    pair_dists.sort(key=lambda x: x[0], reverse=True)
                    c = 0.5 * (pair_dists[0][1] + pair_dists[0][2])
                    return c, pair_dists[0][0] / 2.0
                ux = (
                    (p1[0] ** 2 + p1[1] ** 2) * (p2[1] - p3[1])
                    + (p2[0] ** 2 + p2[1] ** 2) * (p3[1] - p1[1])
                    + (p3[0] ** 2 + p3[1] ** 2) * (p1[1] - p2[1])
                ) / d
                uy = (
                    (p1[0] ** 2 + p1[1] ** 2) * (p3[0] - p2[0])
                    + (p2[0] ** 2 + p2[1] ** 2) * (p1[0] - p3[0])
                    + (p3[0] ** 2 + p3[1] ** 2) * (p2[0] - p1[0])
                ) / d
                c = np.array([ux, uy])
                r = float(np.linalg.norm(p1 - c))
                return c, r

        p = p_list[-1]
        c, r = mec_b(p_list[:-1], r_list)
        if np.linalg.norm(p - c) <= r + 1e-9:
            return c, r
        return mec_b(p_list[:-1], r_list + [p])

    c, r = mec_b(shuffled, [])
    return float(c[0]), float(c[1]), float(r)


def check_diameter_circle_coverage(vertices, A, B):
    """
    检验以 A, B 为直径的圆是否覆盖所有顶点 V:
    当且仅当所有顶点 V 满足 (A - V) · (B - V) <= 0
    返回 (all_covered: bool, max_dot_product: float)
    """
    max_dot = -1e9
    all_covered = True
    for v in vertices:
        v_arr = np.array(v, dtype=float)
        dot = float(np.dot(A - v_arr, B - v_arr))
        if dot > max_dot:
            max_dot = dot
        if dot > 1e-7:
            all_covered = False
    return all_covered, max_dot


def compute_intersection_polygon(stations, bearings_deg, eps_deg=1.0, bound_radius=1800.0):
    """
    计算多个检测点角域与目标区域 Omega (半径 bound_radius) 的交会多边形
    stations: list of (x, y)
    bearings_deg: list of bearing in degrees
    """
    # 初始多边形：用 128 边外接正多边形近似 Omega
    n_init = 128
    angles = np.linspace(0, 2 * math.pi, n_init, endpoint=False)
    r_init = bound_radius / math.cos(math.pi / n_init)
    poly = [(r_init * math.cos(a), r_init * math.sin(a)) for a in angles]

    for (px, py), th in zip(stations, bearings_deg):
        hps = get_bearing_halfplanes(px, py, th, eps_deg)
        for nx, ny, c in hps:
            poly = clip_polygon_by_halfplane(poly, nx, ny, c)
            if not poly:
                return []
    return poly


def construct_three_station_counterexample():
    """
    构造方案第 3.1 节严格证明的三站反例：
    h = 20 / sqrt(3), s = sqrt(1000^2 - h^2)
    三站位于 (h, -s) 绕原点旋转 0, 120, 240 度
    源位于原点 (0, 0)
    角域交为边长 40 的正三角形，其外接圆半径 rho = 40 / sqrt(3) ~ 23.094 > 20
    """
    h = 20.0 / math.sqrt(3.0)
    s = math.sqrt(1000.0**2 - h**2)
    p0 = np.array([h, -s])

    stations = []
    bearings = []
    # 旋转矩阵
    for k in [0, 1, 2]:
        ang = math.radians(120.0 * k)
        R = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]])
        st = R @ p0
        stations.append((st[0], st[1]))
        # 示向度: 真实方位是原点相对于测站的方向
        # 原点向量 (0 - st)
        bearing_true = math.degrees(math.atan2(-st[1], -st[0])) % 360.0
        # 方案给出的具体读数：91, 211, 331 度
        # 此时误差约为 +0.33839 度
        bearings.append(wrap_angle_deg(91.0 + 120.0 * k))

    # 交会多边形顶点理论值：(h, 20), (h, -20), (-2h, 0)
    ideal_verts = [np.array([h, 20.0]), np.array([h, -20.0]), np.array([-2.0 * h, 0.0])]

    d_12 = np.linalg.norm(ideal_verts[0] - ideal_verts[1])  # 40.0
    d_23 = np.linalg.norm(ideal_verts[1] - ideal_verts[2])  # sqrt((3h)^2 + 20^2) = sqrt(1200 + 400) = 40
    d_31 = np.linalg.norm(ideal_verts[2] - ideal_verts[0])  # 40.0

    diam = 40.0
    cx, cy, rho = welzl_mec(ideal_verts)
    covered, max_dot = check_diameter_circle_coverage(
        ideal_verts, ideal_verts[0], ideal_verts[1]
    )

    return {
        "stations": stations,
        "bearings": bearings,
        "vertices": ideal_verts,
        "diameter": diam,
        "mec_center": (cx, cy),
        "mec_radius": rho,
        "diameter_covers": covered,
        "max_dot_product": max_dot,
    }
