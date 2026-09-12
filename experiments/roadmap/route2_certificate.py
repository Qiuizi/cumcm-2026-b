"""
route2_certificate.py —— 路线2（按实际覆盖区域构造证书）的离线可行性研究

【不修改 P3/P4 任何文件；不调用官方模拟器；纯几何离线计算】

核心命题（本脚本要验证与量化的东西）
--------------------------------------------------
静默点集 Q（每点都测到 no_signal）。对候选真位置 x，判据是：
    x 已被证书排除  <=>  x ∈ conv{ q ∈ Q : ||q - x|| <= R_min }
其中 R_min = 1000 m（题设 R ∈ [1000,1500]，no_signal 只保证 ||q-s|| > R >= 1000）。

证明（充分性）：设 x ∈ conv(S)，S = {q ∈ Q: ||q-x|| <= 1000}。由 Carathéodory，
存在 S 中至多 3 点使 x 落在其凸包内。于是任一方向 u 至少满足一个 (q_i - x)·u >= 0。
若源在 x、朝向 u（定向源波束为前向半平面），则该 q_i 同时在波束内且距离 <= 1000 <= R，
理应收到信号，与 no_signal 矛盾；全向源同理（R >= 1000）。故 x 处无源。
必要性：证书必然由"三静默点凸包包含 x 且三点均在 1000 m 内"这类子证书组成。

对照现有实现
--------------------------------------------------
P4 现行判据（`EvidenceTrackerP4` 局部凸包证书）：三角形三顶点同频道静默 **且三边 <= 1000 m**
  则整个三角形被认证。这是上述判据的**充分条件**（三角边长 <= 1000 => 三角形内任一点到
  三顶点均 <= 1000）。本脚本给出的是同一判据的**精确形式**，两者之差就是路线2要研究的空间。

P3 现行判据（`EvidenceTrackerP3`，全向源）：168 个扇区单元，单元内**最远点** <= 1000 才排除。
  P3 的精确判据是 1-覆盖：x 被排除 <=> ∃q ∈ Q, ||q-x|| <= 1000（全向 + R >= 1000）。
  离散 168 单元是它的保守化版本。
"""

import csv
import json
import math
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(HERE, "results")
os.makedirs(OUT_DIR, exist_ok=True)

R_MIN = 1000.0
R_OMEGA = 1800.0


# ----------------------------------------------------------------------------
# 几何工具
# ----------------------------------------------------------------------------
def convex_hull(points):
    """Andrew monotone chain，返回逆时针凸包顶点（去共线中间点）"""
    pts = sorted(set((round(float(p[0]), 9), round(float(p[1]), 9)) for p in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 1e-12:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 1e-12:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def point_in_convex_polygon(pt, hull, tol=1e-7):
    """点是否在逆时针凸包多边形内（含边界）。tol 为绝对距离容差（米）。"""
    if len(hull) == 0:
        return False
    if len(hull) == 1:
        return (pt[0] - hull[0][0]) ** 2 + (pt[1] - hull[0][1]) ** 2 <= tol * tol
    if len(hull) == 2:
        (x1, y1), (x2, y2) = hull
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        if L2 < 1e-18:
            return (pt[0] - x1) ** 2 + (pt[1] - y1) ** 2 <= tol * tol
        t = ((pt[0] - x1) * dx + (pt[1] - y1) * dy) / L2
        t = min(1.0, max(0.0, t))
        cx, cy = x1 + t * dx, y1 + t * dy
        return (pt[0] - cx) ** 2 + (pt[1] - cy) ** 2 <= tol * tol

    n = len(hull)
    for i in range(n):
        ax, ay = hull[i]
        bx, by = hull[(i + 1) % n]
        # 逆时针 => 内部在左侧
        cr = (bx - ax) * (pt[1] - ay) - (by - ay) * (pt[0] - ax)
        # cr >= 0 -> 内侧（或边上）
        seg_len = math.hypot(bx - ax, by - ay)
        if seg_len > 1e-12 and cr < -tol * seg_len:
            return False
    return True


def certified_point(x, Q, rmin=R_MIN, tol=1e-6):
    """
    精确证书判据：x 被静默点集 Q 排除 <=> x ∈ conv{ q ∈ Q : ||q-x|| <= rmin }。
    返回 (是否被排除, 1000 m 内静默点数)。
    说明：|S| <= 2 时 conv(S) 为零测度，对区域覆盖无贡献，按"未排除"处理。
    """
    xa, ya = x
    S = []
    r2 = (rmin + tol) ** 2
    for q in Q:
        dx = q[0] - xa
        dy = q[1] - ya
        if dx * dx + dy * dy <= r2:
            S.append((q[0], q[1]))
    if len(S) < 3:
        return False, len(S)
    if len(S) == 3:
        hull = convex_hull(S)
    else:
        hull = convex_hull(S)
    return point_in_convex_polygon((xa, ya), hull, tol=tol), len(S)


def omni_covered_point(x, Q, rmin=R_MIN, tol=1e-6):
    """P3（全向源）精确判据：1-覆盖。x 被排除 <=> ∃q: ||q-x|| <= 1000。"""
    xa, ya = x
    r2 = (rmin + tol) ** 2
    for q in Q:
        dx = q[0] - xa
        dy = q[1] - ya
        if dx * dx + dy * dy <= r2:
            return True
    return False


def sample_omega(n_theta=1440, n_r=360, r_max=R_OMEGA, angle_lo=0.0, angle_hi=2 * math.pi):
    """在极坐标网格上采样 Ω（可只采一个对称楔形）"""
    thetas = np.linspace(angle_lo, angle_hi, n_theta, endpoint=False)
    rs = np.linspace(r_max / n_r, r_max, n_r)  # 步长 r_max/n_r
    T, R = np.meshgrid(thetas, rs)
    pts = np.stack([R.ravel() * np.cos(T.ravel()), R.ravel() * np.sin(T.ravel())], axis=1)
    return pts


def sample_omega_cartesian(step=8.0, r_max=R_OMEGA):
    """笛卡尔网格采样（不利用对称性，用于复核）"""
    xs = np.arange(-r_max, r_max + 1e-9, step)
    X, Y = np.meshgrid(xs, xs)
    m = (X * X + Y * Y) <= r_max * r_max
    return np.stack([X[m], Y[m]], axis=1)


def coverage_report(Q, judge, n_theta=1440, n_r=360, angle_lo=0.0, angle_hi=2 * math.pi):
    """给定判据函数与采样集，返回覆盖统计"""
    pts = sample_omega(n_theta=n_theta, n_r=n_r, angle_lo=angle_lo, angle_hi=angle_hi)
    bad = 0
    bad_examples = []
    min_n_in_range = 10 ** 9
    for p in pts:
        ok, n_in = judge((float(p[0]), float(p[1])), Q)
        min_n_in_range = min(min_n_in_range, n_in)
        if not ok:
            bad += 1
            if len(bad_examples) < 8:
                bad_examples.append([round(float(p[0]), 2), round(float(p[1]), 2),
                                     round(math.hypot(float(p[0]), float(p[1])), 2)])
    total = len(pts)
    return {
        "n_samples": int(total),
        "n_uncovered": int(bad),
        "covered_fraction": round(1.0 - bad / total, 6),
        "min_points_within_1000": int(min_n_in_range),
        "uncovered_examples": bad_examples,
    }


# ----------------------------------------------------------------------------
# 现行 P4 覆盖网 / 三角剖分（只读复刻，用于对照；不 import 以免与冻结实现耦合）
# ----------------------------------------------------------------------------
def build_ring_net(n1, r1, n2, r2, phase2=0.0, include_origin=True):
    pts = []
    if include_origin:
        pts.append((0.0, 0.0))
    A = [(r1 * math.cos(2 * math.pi * i / n1), r1 * math.sin(2 * math.pi * i / n1)) for i in range(n1)]
    B = [(r2 * math.cos(2 * math.pi * k / n2 + phase2), r2 * math.sin(2 * math.pi * k / n2 + phase2))
         for k in range(n2)]
    return pts, A, B


def p4_fan_triangles(A, B, n1, n2, origin=(0.0, 0.0)):
    """P4 扇面三角剖分生成规则（与 evidence_tracker.py 的构造完全一致）"""
    tris = []
    for i in range(n1):
        ai = A[i]
        ai_next = A[(i + 1) % n1]
        b_2i = B[2 * i % n2]
        b_2i_1 = B[(2 * i + 1) % n2]
        b_2i_2 = B[(2 * i + 2) % n2]
        tris.append([origin, ai, ai_next])
        tris.append([ai, b_2i, b_2i_1])
        tris.append([ai, b_2i_1, ai_next])
        tris.append([ai_next, b_2i_1, b_2i_2])
    return tris


def tri_max_edge(tri):
    (x1, y1), (x2, y2), (x3, y3) = tri
    return max(math.hypot(x2 - x1, y2 - y1),
               math.hypot(x3 - x2, y3 - y2),
               math.hypot(x1 - x3, y1 - y3))


def point_in_triangle(pt, tri, tol=1e-7):
    (x1, y1), (x2, y2), (x3, y3) = tri
    px, py = pt
    d1 = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
    d2 = (x3 - x2) * (py - y2) - (y3 - y2) * (px - x2)
    d3 = (x1 - x3) * (py - y3) - (y1 - y3) * (px - x3)
    has_neg = (d1 < -tol) or (d2 < -tol) or (d3 < -tol)
    has_pos = (d1 > tol) or (d2 > tol) or (d3 > tol)
    return not (has_neg and has_pos)


def strict_judge_factory(tris):
    """现行（严格）判据：落在某个'三边 <= 1000'的剖分三角形内才算被排除"""
    strict_tris = [t for t in tris if tri_max_edge(t) <= R_MIN + 1e-9]

    def judge(x, Q):
        for t in strict_tris:
            if point_in_triangle(x, t):
                return True, 3
        return False, 0

    return judge


# ----------------------------------------------------------------------------
# 主实验
# ----------------------------------------------------------------------------
def experiment_p4_relaxation():
    """路线2 · 实验A：同一 25 点网下，严格判据 vs 精确判据"""
    n1, r1, n2, r2 = 8, 990.0, 16, 1840.0
    origin_pts, A, B = build_ring_net(n1, r1, n2, r2)
    Q = origin_pts + A + B
    tris = p4_fan_triangles(A, B, n1, n2)

    wedge = 2 * math.pi / n1  # 45° 对称楔形
    exact = coverage_report(Q, certified_point, n_theta=180, n_r=360, angle_hi=wedge)
    strict = coverage_report(Q, strict_judge_factory(tris), n_theta=180, n_r=360, angle_hi=wedge)

    edges = [tri_max_edge(t) for t in tris]
    return {
        "config": {"n1": n1, "r1": r1, "n2": n2, "r2": r2, "n_points": len(Q)},
        "max_triangle_edge_m": round(max(edges), 4),
        "n_triangles": len(tris),
        "strict_coverage_of_omega": strict,
        "exact_coverage_of_omega": exact,
        "strict_ok": strict["n_uncovered"] == 0,
        "exact_ok": exact["n_uncovered"] == 0,
    }


def experiment_p4_edge_relaxation():
    """路线2 · 实验B：把外环半径推大，看严格判据何时失效、精确判据是否仍成立"""
    rows = []
    n1, n2 = 8, 16
    for r2 in [1840, 1900, 2000, 2100, 2200, 2400, 2600, 2800]:
        for r1 in [990, 900, 800, 700]:
            _, A, B = build_ring_net(n1, r1, n2, r2)
            Q = [(0.0, 0.0)] + A + B
            tris = p4_fan_triangles(A, B, n1, n2)
            wedge = 2 * math.pi / n1
            ex = coverage_report(Q, certified_point, n_theta=90, n_r=180, angle_hi=wedge)
            st = coverage_report(Q, strict_judge_factory(tris), n_theta=90, n_r=180, angle_hi=wedge)
            rows.append({
                "n1": n1, "r1": r1, "n2": n2, "r2": r2,
                "max_edge_m": round(max(tri_max_edge(t) for t in tris), 2),
                "strict_covered_frac": st["covered_fraction"],
                "exact_covered_frac": ex["covered_fraction"],
                "strict_ok": st["n_uncovered"] == 0,
                "exact_ok": ex["n_uncovered"] == 0,
            })
    return rows


def experiment_min_subset():
    """
    路线2 · 实验C：不换网点，只问"哪几点的静默就足以让 Ω 全部被认证"。

    注意：Ω 的覆盖必须对**全部 8 个扇区**成立，不能只对一个楔形。做法是
    对每个扇区 i 独立求一个覆盖该扇区的极小点集 S_i，再取并集 ∪S_i
    （并集是充分条件；并用 360° 全采样做最终复核，避免楔形采样的误判）。
    """
    n1, r1, n2, r2 = 8, 990.0, 16, 1840.0
    origin_pts, A, B = build_ring_net(n1, r1, n2, r2)
    Q = origin_pts + A + B
    labels = (["O"] + [f"A{i}" for i in range(n1)] + [f"B{k}" for k in range(n2)])

    wedge = 2 * math.pi / n1
    per_wedge = []
    union = set()
    for i in range(n1):
        # 扇区 i 的采样：把楔形旋转到该扇区
        base = sample_omega(n_theta=90, n_r=180, angle_hi=wedge)
        ca, sa = math.cos(i * wedge), math.sin(i * wedge)
        samples = [(float(p[0]) * ca - float(p[1]) * sa, float(p[0]) * sa + float(p[1]) * ca)
                   for p in base]

        cache = {}

        def covers(idxs):
            key = tuple(sorted(idxs))
            if key in cache:
                return cache[key]
            sub = [Q[j] for j in key]
            ok = True
            for x in samples:
                if not certified_point(x, sub)[0]:
                    ok = False
                    break
            cache[key] = ok
            return ok

        kept = list(range(len(Q)))
        changed = True
        while changed:
            changed = False
            for j in list(kept):
                trial = [t for t in kept if t != j]
                if covers(trial):
                    kept = trial
                    changed = True
        per_wedge.append({
            "wedge_idx": i,
            "subset_size": len(kept),
            "subset_labels": [labels[j] for j in kept],
        })
        union |= set(kept)

    # 360° 全采样复核并集
    full_samples = sample_omega(n_theta=720, n_r=240)
    sub_union = [Q[j] for j in sorted(union)]
    misses = 0
    for p in full_samples:
        if not certified_point((float(p[0]), float(p[1])), sub_union)[0]:
            misses += 1

    # 逐点必要性（从全量出发逐个删除，看 360° 采样是否仍全覆盖）
    all_idx = list(range(len(Q)))
    essential = []
    for j in all_idx:
        trial = [t for t in all_idx if t != j]
        sub = [Q[t] for t in trial]
        ok = True
        for p in full_samples:
            if not certified_point((float(p[0]), float(p[1])), sub)[0]:
                ok = False
                break
        if not ok:
            essential.append(labels[j])

    return {
        "config": {"n1": n1, "r1": r1, "n2": n2, "r2": r2, "n_points": len(Q)},
        "per_wedge_minimal_subsets": per_wedge,
        "union_subset_size": len(union),
        "union_subset_labels": [labels[j] for j in sorted(union)],
        "union_covers_omega_360deg": misses == 0,
        "union_uncovered_samples_360deg": int(misses),
        "reduction_vs_full_net": len(Q) - len(union),
        "saving_per_absent_channel_s": (len(Q) - len(union)) * 5.0,
        "essential_points_wrt_full_set": essential,
        "n_essential": len(essential),
    }


def experiment_min_net_search():
    """
    路线2 · 实验D：在松弛（精确）判据下搜索更少点数的覆盖网。

    结构：可选原点 + 内环 n1 点 @ r1 + 外环 n2 = m*n1 点 @ r2，
          两环相对相位 φ ∈ {2πj/n2, j=0..m-1}。
    对称性：n2 为 n1 的整数倍 => 整网点集在旋转 2π/n1 下不变，只需采样一个楔形。
    目标：找到"精确证书仍覆盖 Ω"的最小点数（并与理论下界比较）。
    """
    grid_n1 = [3, 4, 5, 6, 7, 8]
    grid_m = [2, 3, 4]
    grid_r1 = [700, 850, 990, 1150, 1300]
    grid_r2 = [1800, 1840, 1900, 2000, 2150]

    rows = []
    feasible = []
    for n1 in grid_n1:
        for m in grid_m:
            n2 = m * n1
            for has_origin in [False, True]:
                total = n1 + n2 + (1 if has_origin else 0)
                if total > 25:
                    continue
                best = None
                for r1 in grid_r1:
                    for r2 in grid_r2:
                        for j in range(m):
                            phase = 2 * math.pi * j / n2
                            origin_pts, A, B = build_ring_net(
                                n1, r1, n2, r2, phase2=phase, include_origin=has_origin)
                            Q = origin_pts + A + B
                            w = 2 * math.pi / n1
                            ex = coverage_report(Q, certified_point, n_theta=48, n_r=100,
                                                 angle_hi=w)
                            if ex["n_uncovered"] == 0:
                                cand = {"n_points": total, "n1": n1, "n2": n2,
                                        "has_origin": has_origin, "r1": r1, "r2": r2,
                                        "phase_deg": round(math.degrees(phase), 4)}
                                feasible.append(cand)
                                if best is None:
                                    best = cand
                rows.append({
                    "n1": n1, "n2": n2, "m": m, "has_origin": has_origin,
                    "total_points": n1 + n2 + (1 if has_origin else 0),
                    "feasible_found": best is not None,
                    "best": best,
                })

    # 精细复核：按点数从小到大逐个体检
    feasible.sort(key=lambda c: c["n_points"])
    fine = []
    for cand in feasible:
        origin_pts, A, B = build_ring_net(
            cand["n1"], cand["r1"], cand["n2"], cand["r2"],
            phase2=math.radians(cand["phase_deg"]), include_origin=cand["has_origin"])
        Q = origin_pts + A + B
        w = 2 * math.pi / cand["n1"]
        ex = coverage_report(Q, certified_point, n_theta=480, n_r=720, angle_hi=w)
        rec = dict(cand)
        rec["fine_n_uncovered"] = ex["n_uncovered"]
        rec["fine_covered_fraction"] = ex["covered_fraction"]
        rec["fine_n_samples"] = ex["n_samples"]
        fine.append(rec)

    ok_fine = [c for c in fine if c["fine_n_uncovered"] == 0]
    return {
        "search_rows": rows,
        "fine_verification": fine[:40],
        "min_points_coarse": min((c["n_points"] for c in feasible), default=None),
        "min_points_fine_verified": min((c["n_points"] for c in ok_fine), default=None),
        "n_feasible_coarse": len(feasible),
    }


def omni_judge(x, Q):
    """适配 coverage_report 的 (ok, n_in) 接口"""
    ok = omni_covered_point(x, Q)
    return ok, (1 if ok else 0)


def theoretical_bounds():
    """
    与判据无关的两条硬下界（严格判据与精确判据都受其约束）：

    (1) 外环半径下界：取 x ∈ Ω 且 |x| = 1800。任何子证书要求 x ∈ conv(S(x))，
        故存在 q ∈ S(x) 且 |q| >= |x| = 1800。=> 覆盖网必须含半径 >= 1800 的点，
        最外圈往返里程因此下界约 2 × 1800 m。
    (2) 点数下界：任一 x ∈ Ω 需至少 3 个静默点在 1000 m 内（2 点的凸包是零测度线段）。
        对 r = 1800 的边界圆，中心距原点 d 的 1000 m 圆盘截得的弧半角
            β(d) = arccos((d^2 + 1800^2 - 1000^2) / (2 d * 1800))，
        β 在 d 上的最大值给出单个圆盘可覆盖的最大弧长；3 重覆盖整圆因此需要
            |Q| >= ceil(3 * 2π / max_arc)。
    """
    def beta(d):
        val = (d * d + 1800.0 ** 2 - 1000.0 ** 2) / (2.0 * d * 1800.0)
        val = max(-1.0, min(1.0, val))
        return math.acos(val)

    ds = np.linspace(800.0, 4000.0, 320001)
    betas = np.array([beta(float(d)) for d in ds[::1000]])
    d_fine = ds[::1000][int(np.argmax(betas))]
    # 局部精修
    for _ in range(60):
        step = max(0.001, 1.0 / (1 + _) )
        cand = [d_fine - step, d_fine, d_fine + step]
        vals = [beta(c) for c in cand]
        d_fine = cand[int(np.argmax(vals))]
    b_max = beta(d_fine)
    max_arc = 2.0 * b_max
    lb_points = math.ceil(3.0 * 2.0 * math.pi / max_arc)

    return {
        "max_arc_per_disk_deg": round(math.degrees(max_arc), 4),
        "argmax_center_radius_m": round(d_fine, 3),
        "three_cover_point_lower_bound": int(lb_points),
        "outer_ring_radius_lower_bound_m": 1800.0,
        "min_two_way_travel_lower_bound_m": 3600.0,
    }


def experiment_p3_omni():
    """
    路线2 · 实验E：P3（全向源）—— 精确 1-覆盖 vs 168 单元离散判据。
    只读 import EvidenceTrackerP3 用于对照，不修改其任何行为。
    """
    sys.path.insert(0, ROOT)
    from src.evidence_tracker import EvidenceTrackerP3

    tr = EvidenceTrackerP3()
    fixed = list(tr.search_points)

    wedge_exact = coverage_report(fixed, omni_judge, n_theta=1440, n_r=360)

    # 168 单元判据：单元被排除 <=> ∃q ∈ Q 使 max_distance_to_cell(q, cell) <= 1000
    # （record_no_signal 的语义：单次静默即可排除该单元）
    def cell_mask(Q):
        mask = np.zeros(168, dtype=bool)
        for q in Q:
            for idx, cell in enumerate(tr.cells):
                if not mask[idx] and tr.max_distance_to_cell(q[0], q[1], cell) <= R_MIN:
                    mask[idx] = True
        return mask

    mask7 = cell_mask(fixed)
    n_cells_fixed = int(np.sum(mask7))

    # 逐单元建立 168 单元的极坐标索引表（用于 O(1) 定位样本点所属单元）
    def locate_cell(x, y):
        rr = math.hypot(x, y)
        phi = math.atan2(y, x) % (2 * math.pi)
        i_phi = min(27, int(phi / (2 * math.pi / 28)))
        for i_r in range(6):
            if tr.cells[i_phi * 6 + i_r]["r1"] <= rr <= tr.cells[i_phi * 6 + i_r]["r2"]:
                return i_phi * 6 + i_r
        return -1

    samples = sample_omega(n_theta=720, n_r=360)
    diff_exact_only = 0
    diff_cell_only = 0
    in_cell_counts = {}
    for p in samples:
        x = (float(p[0]), float(p[1]))
        ex = omni_covered_point(x, fixed)
        ci = locate_cell(x[0], x[1])
        cell_ok = (ci >= 0) and bool(mask7[ci])
        if ci < 0:
            continue
        # 该点所属单元内的"最远点"是否也在 1000 内 —— 单元判据要求的正是这个
        if ex and not cell_ok:
            diff_exact_only += 1
        if cell_ok and not ex:
            diff_cell_only += 1
        in_cell_counts[ci] = in_cell_counts.get(ci, 0) + 1

    # 哪些单元在 7 点静默后仍未被单元判据排除（说明离散化损失）
    missing_cells = [i for i in range(168) if not mask7[i]]

    return {
        "n_fixed_search_points": len(fixed),
        "fixed_points": [[round(p[0], 2), round(p[1], 2)] for p in fixed],
        "exact_1cover_of_omega_with_7_points": wedge_exact,
        "n_cells_excluded_by_7_points_of_168": n_cells_fixed,
        "cells_check_complete": n_cells_fixed == 168,
        "missing_cell_ids": missing_cells,
        "missing_cell_geometry": [
            {"id": i, "r1": tr.cells[i]["r1"], "r2": tr.cells[i]["r2"],
             "phi_mid_deg": round(math.degrees((tr.cells[i]["phi1"] + tr.cells[i]["phi2"]) / 2), 2)}
            for i in missing_cells
        ],
        "cell_vs_exact": {
            "n_samples": int(len(samples)),
            "exact_covered_but_cell_not": diff_exact_only,
            "cell_covered_but_exact_not": diff_cell_only,
        },
    }


def main():
    results = {}

    print("=" * 78)
    print("路线2 研究：按实际覆盖区域构造证书（精确证书 vs 现行判据）")
    print("=" * 78)
    print("精确判据：x 被排除 <=> x ∈ conv{q ∈ Q : ||q-x|| <= 1000}")

    print("\n[实验A] 现行 25 点网：严格判据 vs 精确判据")
    a = experiment_p4_relaxation()
    results["A_p4_relaxation"] = a
    print(f"  三角形最大边长 = {a['max_triangle_edge_m']} m，三角形数 = {a['n_triangles']}")
    print(f"  严格判据覆盖率 = {a['strict_coverage_of_omega']['covered_fraction']:.6f} "
          f"(未覆盖样本 {a['strict_coverage_of_omega']['n_uncovered']})")
    print(f"  精确判据覆盖率 = {a['exact_coverage_of_omega']['covered_fraction']:.6f} "
          f"(未覆盖样本 {a['exact_coverage_of_omega']['n_uncovered']})")

    print("\n[下界] 与判据无关的硬下界")
    tb = theoretical_bounds()
    results["theoretical_bounds"] = tb
    print(f"  单个 1000 m 圆盘在 r=1800 边界圆上最多覆盖弧长 = {tb['max_arc_per_disk_deg']:.4f}° "
          f"(最优圆心半径 {tb['argmax_center_radius_m']:.1f} m)")
    print(f"  => 3 重覆盖整圆 => 点数下界 |Q| >= {tb['three_cover_point_lower_bound']}")
    print(f"  外环半径下界 = {tb['outer_ring_radius_lower_bound_m']:.0f} m "
          f"=> 最外圈往返里程下界约 {tb['min_two_way_travel_lower_bound_m']:.0f} m")

    print("\n[实验B] 把外环半径推大：严格判据失效点 vs 精确判据")
    b = experiment_p4_edge_relaxation()
    results["B_edge_relaxation"] = b
    print(f"  {'r1':>6} {'r2':>6} {'max_edge':>9} {'strict':>9} {'exact':>9}")
    for row in b:
        flag = ""
        if row["strict_ok"] and not row["exact_ok"]:
            flag = "  <-- 异常"
        if (not row["strict_ok"]) and row["exact_ok"]:
            flag = "  <-- 路线2 增量"
        print(f"  {row['r1']:>6} {row['r2']:>6} {row['max_edge_m']:>9.1f} "
              f"{row['strict_covered_frac']:>9.4f} {row['exact_covered_frac']:>9.4f}{flag}")

    print("\n[实验C] 不换网点：每个扇区的极小覆盖子集 & 其并集")
    c = experiment_min_subset()
    results["C_min_subset"] = c
    print(f"  全网点数 = {c['config']['n_points']}")
    for w in c["per_wedge_minimal_subsets"]:
        print(f"    扇区 {w['wedge_idx']}: {w['subset_size']} 点 -> {', '.join(w['subset_labels'])}")
    print(f"  8 个扇区子集的并集大小 = {c['union_subset_size']} "
          f"({', '.join(c['union_subset_labels'])})")
    print(f"  并集对 Ω 的 360° 全采样覆盖 = {c['union_covers_omega_360deg']} "
          f"(未覆盖样本 {c['union_uncovered_samples_360deg']})")
    print(f"  相对 25 点的可省检测次数 = {c['reduction_vs_full_net']} 次 "
          f"= {c['saving_per_absent_channel_s']:.1f} s / 空频道")
    print(f"  在 25 点全量下仍不可删除的点 = {len(c['essential_points_wrt_full_set'])} 个: "
          f"{', '.join(c['essential_points_wrt_full_set'])}")

    print("\n[实验D] 松弛判据下的最少点数覆盖网搜索")
    d = experiment_min_net_search()
    results["D_min_net_search"] = d
    rows_d = d["search_rows"]
    print(f"  {'n1':>4} {'n2':>4} {'原点':>5} {'总点数':>7} {'可行':>5}  最优参数")
    for r in sorted(rows_d, key=lambda r: r["total_points"]):
        best = r["best"]
        bt = (f"r1={best['r1']}, r2={best['r2']}, phase={best['phase_deg']}deg"
              if best else "-")
        print(f"  {r['n1']:>4} {r['n2']:>4} {str(r['has_origin']):>5} "
              f"{r['total_points']:>7} {str(r['feasible_found']):>5}  {bt}")
    print(f"  粗搜索可达最小点数 = {d['min_points_coarse']}，"
          f"高分辨率复验确认的最小点数 = {d['min_points_fine_verified']}")
    for c in d["fine_verification"]:
        if c["fine_n_uncovered"] == 0:
            print(f"    ✓ n1={c['n1']} n2={c['n2']} origin={c['has_origin']} "
                  f"r1={c['r1']} r2={c['r2']} phase={c['phase_deg']}° -> {c['n_points']} 点")

    print("\n[实验E] P3 全向源：精确 1-覆盖 vs 168 单元离散判据")
    e = experiment_p3_omni()
    results["E_p3_omni"] = e
    ex = e["exact_1cover_of_omega_with_7_points"]
    print(f"  7 个固定搜索点：精确 1-覆盖 Ω 覆盖率 = {ex['covered_fraction']:.6f} "
          f"(未覆盖 {ex['n_uncovered']}/{ex['n_samples']})")
    print(f"  7 个点按 168 单元离散判据排除的单元数 = {e['n_cells_excluded_by_7_points_of_168']}/168 "
          f"(完备 = {e['cells_check_complete']})")
    print(f"  边界差样本：精确已覆盖但单元未覆盖 = {e['cell_vs_exact']['exact_covered_but_cell_not']}，"
          f"反向 = {e['cell_vs_exact']['cell_covered_but_exact_not']}")
    print(f"  未被 168 单元判据排除的单元数 = {len(e['missing_cell_ids'])}")

    with open(os.path.join(OUT_DIR, "route2_certificate_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    with open(os.path.join(OUT_DIR, "route2_edge_relaxation.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(b[0].keys()))
        w.writeheader()
        w.writerows(b)

    with open(os.path.join(OUT_DIR, "route2_min_net_search.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["n1", "n2", "has_origin", "total_points", "feasible_found",
                    "best_n_points", "best_r1", "best_r2", "best_phase_deg"])
        for r in rows_d:
            best = r["best"] or {}
            w.writerow([r["n1"], r["n2"], r["has_origin"], r["total_points"],
                        r["feasible_found"], best.get("n_points"), best.get("r1"),
                        best.get("r2"), best.get("phase_deg")])

    print(f"\n结果已写入 {OUT_DIR}")


if __name__ == "__main__":
    main()
