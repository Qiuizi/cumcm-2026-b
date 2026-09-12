"""
route2b_point_budget.py —— 路线2 的决定性实验：精确证书下的"点数预算前沿"

【不修改 P3/P4 任何文件；不调用官方模拟器；纯几何离线计算】

问题
--------------------------------------------------
既有交付包 `delivery/P4_cover_redesign_delivery_20260912/CONCLUSION_结论.md` 的结论是：
  "连续覆盖 Ω 需要边长 ≤ 1000 m 的三角剖分 …… 几何可实现的最小规模就是 25 点"，
  并指出"若未来要真正突破，需要改变的是'空频道必须由静默测站覆盖整个 Ω'这一证据强度本身"。

但那条最小性结论是在**严格充分条件**（三边 ≤ 1000 m 的三角剖分）下得到的。
路线2 把判据换成**精确证书**：
    x 被排除  <=>  x ∈ conv{ q ∈ Q : ||q - x|| <= 1000 }
它比严格条件严格更弱（更大可行域）。因此必须重做最小性：**精确证书下是否还存在 < 25 点的
合法覆盖网？** 本脚本用数值搜索给出上界，并给出与判据无关的硬下界。

判据的精确实现（本脚本用的等价形式）
--------------------------------------------------
设 S(x) = {q ∈ Q : ||q-x|| <= 1000}，d_q = q - x。则
    x ∈ conv(S(x))  <=>  0 ∈ conv{d_q}  <=>  {d_q} 的方向不被任何开半平面包含
                    <=>  把各方向按角排序后，最大循环夹角间隙 <= π。
（"被开半平面包含" <=> 存在角宽 π 的空隙。）该判据是精确的，不是采样近似；
本脚本另用凸包/点在凸多边形内判据交叉复核最优候选。

与判据无关的硬下界
--------------------------------------------------
LB1  conv(Q) ⊇ Ω。因为 x ∈ conv(S(x)) ⊆ conv(Q)。故 Q 的凸包必须包含半径 1800 的圆盘，
     特别是外圈半径 >= 1800（若外圈是凸包顶点）。
LB2  任一 x ∈ Ω 需至少 3 个静默点在 1000 m 内（2 点的凸包是零测度线段）。
     对 r = 1800 边界圆，中心距原点 d 的 1000 m 圆盘截得弧半角
         β(d) = arccos((d² + 1800² − 1000²) / (2 d · 1800))，
     单圆盘最大弧长 = 2·max β，3 重覆盖整圆 => |Q| >= ceil(3·2π / max_arc)。
LB3  单调性：若存在 m 点可行网，则任何 m' > m 也可行（加点不会破坏覆盖）。
     故"找不到 24 点可行网"在**穷尽搜索**意义下即可排除所有更小规模。
"""

import json
import math
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "results")
os.makedirs(OUT_DIR, exist_ok=True)

R_MIN = 1000.0
R_OMEGA = 1800.0
TOL = 1e-9


# ----------------------------------------------------------------------------
# 采样与判据
# ----------------------------------------------------------------------------
def sample_omega(n_theta, n_r, r_max=R_OMEGA):
    th = np.linspace(0.0, 2.0 * math.pi, n_theta, endpoint=False)
    rs = np.linspace(r_max / n_r, r_max, n_r)
    T, R = np.meshgrid(th, rs)
    return np.stack([(R * np.cos(T)).ravel(), (R * np.sin(T)).ravel()], axis=1)


def certify_matrix(X, Q, rmin=R_MIN):
    """
    返回 (overhang_sum, n_uncovered, min_n_in_range, worst_gap_deg)
    overhang_sum = Σ_x max(0, max_gap(x) - π)：0 当且仅当 Ω 全域被精确证书覆盖。
    """
    Q = np.asarray(Q, dtype=float)
    diff = X[:, None, :] - Q[None, :, :]              # (N,M,2)
    d2 = np.einsum("nmk,nmk->nm", diff, diff)
    mask = d2 <= (rmin + 1e-6) ** 2
    ang = np.arctan2(diff[:, :, 1], diff[:, :, 0])     # (N,M)
    n_in = mask.sum(axis=1)

    overhang = 0.0
    unc = 0
    worst = -1.0
    for n in range(X.shape[0]):
        if n_in[n] < 3:
            overhang += math.pi
            unc += 1
            worst = max(worst, 2.0 * math.pi)
            continue
        a = np.sort(ang[n][mask[n]])
        gaps = np.diff(a)
        cyc = 2.0 * math.pi - (a[-1] - a[0])
        mg = max(float(gaps.max()), float(cyc))
        if mg > math.pi + TOL:
            overhang += mg - math.pi
            unc += 1
            worst = max(worst, mg)
        else:
            worst = max(worst, mg)
    return float(overhang), int(unc), int(n_in.min()), math.degrees(worst) if worst > 0 else 0.0


def verify_exact_hull(Q, n_theta=1440, n_r=240, tol=1e-7):
    """
    用凸包 + 点在凸多边形内 判据做独立复核（不依赖角度间隙实现的正确性）。
    返回 (n_uncovered, n_samples, examples)
    """
    sys.path.insert(0, HERE)
    from route2_certificate import certified_point  # 只读复用

    X = sample_omega(n_theta, n_r)
    unc = 0
    ex = []
    for p in X:
        ok, _ = certified_point((float(p[0]), float(p[1])), [tuple(q) for q in Q])
        if not ok:
            unc += 1
            if len(ex) < 6:
                ex.append([round(float(p[0]), 2), round(float(p[1]), 2)])
    return unc, len(X), ex


# ----------------------------------------------------------------------------
# 候选构造与局部搜索
# ----------------------------------------------------------------------------
def ring_net(n_out, r_out, n_in, r_in, phase_out=0.0, phase_in=0.0, origin=True, jitter=0.0,
             rng=None):
    pts = []
    if origin:
        pts.append((0.0, 0.0))
    for k in range(n_out):
        a = 2 * math.pi * k / n_out + phase_out
        pts.append((r_out * math.cos(a), r_out * math.sin(a)))
    for i in range(n_in):
        a = 2 * math.pi * i / n_in + phase_in
        pts.append((r_in * math.cos(a), r_in * math.sin(a)))
    pts = np.array(pts, dtype=float)
    if jitter > 0 and rng is not None:
        pts = pts + rng.normal(0.0, jitter, size=pts.shape)
    return pts


def seeds_for_m(m, rng, n_random=5):
    """
    构造 m 点的种子：
      - 若 m == 24：对已知 25 点网逐个删除一个点的 25 个变体（最贴近"再减一点"的方向）
      - 若干随机环族初值
      - 一个等半径环族保底
    """
    out = []
    base = ring_net(16, 1840.0, 8, 990.0, origin=True)

    if m == 24:
        for i in range(len(base)):
            out.append(np.delete(base, i, axis=0))
    elif m < 24:
        # 从 25 点网随机删到 m 点（可能已不覆盖，但结构接近）
        for _ in range(3):
            idx = rng.permutation(len(base))[:m]
            out.append(base[idx])

    for _ in range(n_random):
        origin = bool(rng.integers(0, 2))
        rem = m - (1 if origin else 0)
        if rem < 8:
            origin = False
            rem = m
        n_out = int(rng.integers(8, max(9, rem - 3)))
        n_in = rem - n_out
        if n_in < 3:
            n_out = rem - 3
            n_in = 3
        if n_in < 3 or n_out < 6:
            continue
        r_out = 1800.0 / math.cos(math.pi / n_out) * float(rng.uniform(1.0, 1.12))
        r_in = float(rng.uniform(650.0, 1500.0))
        out.append(ring_net(n_out, r_out, n_in, r_in,
                            phase_out=float(rng.uniform(0, 2 * math.pi)),
                            phase_in=float(rng.uniform(0, 2 * math.pi)),
                            origin=origin,
                            jitter=float(rng.uniform(0, 80.0)), rng=rng))
    origin = (m % 2 == 1)
    rem = m - (1 if origin else 0)
    if rem >= 8:
        n_out = rem * 2 // 3
        n_in = rem - n_out
        if n_in >= 3:
            out.append(ring_net(n_out, 1835.0, n_in, 990.0, origin=origin))
    return out


def score(Q, X):
    return certify_matrix(X, Q)[0]


def local_search(m, X, X_verify, rng, iters_per_seed=250, sigma0=130.0, max_seeds=12):
    """
    对 m 点网做带预算的局部搜索。
    目标 = overhang_sum（0 <=> 采样集上被精确证书完整覆盖）。
    **判定只用高分辨率网格 X_verify**：粗网格 serving 仅作优化信号，
    这样避免"粗采样假阳性"（历史上已经踩过一次：粗/中网格 0 未覆盖，细网格 3481 未覆盖）。
    """
    seeds = seeds_for_m(m, rng)
    rng.shuffle(seeds)
    seeds = seeds[:max_seeds]
    best_Q, best_s, n_eval = None, float("inf"), 0

    for Q0 in seeds:
        Q = np.array(Q0, dtype=float)
        s = score(Q, X)
        n_eval += 1
        if s <= 1e-9:
            sv = certify_matrix(X_verify, Q)
            if sv[0] <= 1e-9:
                return Q, 0.0, n_eval, sv
        sigma = sigma0
        stall = 0
        for _ in range(iters_per_seed):
            i = int(rng.integers(0, m))
            cand = Q.copy()
            cand[i] = cand[i] + rng.normal(0.0, sigma, size=2)
            sc = score(cand, X)
            n_eval += 1
            if sc <= s:
                if sc < s - 1e-18:
                    stall = 0
                else:
                    stall += 1
                Q, s = cand, sc
                if s <= 1e-9:
                    sv = certify_matrix(X_verify, Q)
                    n_eval += 1
                    if sv[0] <= 1e-9:
                        return Q, 0.0, n_eval, sv
                    # 高分辨率否定：把它当作不为 0 的目标，继续优化
                    s = sv[0] * 1e-3  # 保留细网格信号，避免又掉回同一个假阳性
                    best_Q, best_s = Q.copy(), s
                    continue
            else:
                stall += 1
            if stall > 0 and stall % 60 == 0:
                sigma = max(10.0, sigma * 0.7)
            if n_eval > 4000:
                break
        if best_s > s:
            best_Q, best_s = Q.copy(), s
        if n_eval > 4000:
            break
    return best_Q, best_s, n_eval, None


def theoretical_bounds():
    """
    解析最优：c(d) = (d² + R² − r²)/(2Rd) 在 d* = sqrt(R² − r²) 处最小，
    此时 beta_max = arccos(sqrt(R² − r²)/R) = arcsin(r/R)，单圆盘最大边界弧长 = 2·arcsin(r/R)。
    R = 1800, r = 1000 => d* = 1496.663 m, beta_max = 33.74899°, 弧长 = 67.49798°。
    """
    R, r = 1800.0, 1000.0
    d = math.sqrt(R * R - r * r)
    beta = math.asin(r / R)
    max_arc = 2.0 * beta
    lb1 = math.ceil(2.0 * math.pi / max_arc)
    lb3 = math.ceil(3.0 * 2.0 * math.pi / max_arc)
    return {
        "max_arc_per_disk_deg": round(math.degrees(max_arc), 6),
        "argmax_center_radius_m": round(d, 4),
        "max_arc_formula": "2*arcsin(r/R)",
        "one_cover_lower_bound": int(lb1),
        "three_cover_lower_bound": int(lb3),
        "exact_ratio_3cover": round(3.0 * 2.0 * math.pi / max_arc, 5),
        "convex_hull_must_contain_omega": True,
        "outer_radius_lower_bound_m": 1800.0,
    }


def main():
    rng = np.random.default_rng(20260912)
    X_opt = sample_omega(180, 15)          # 2,700 采样点（优化目标，粗）
    X_check = sample_omega(480, 40)        # 19,200 采样点（判成功前复核）
    X_fine = sample_omega(1440, 120)       # 172,800 采样点（最终复核）
    print("=" * 90)
    print("路线2 决定性实验：精确证书下的点数预算前沿")
    print("=" * 90)
    b = theoretical_bounds()
    print(f"[硬下界] 单圆盘在 r=1800 上的最大弧长 = {b['max_arc_per_disk_deg']:.4f}° "
          f"(最优圆心半径 {b['argmax_center_radius_m']:.1f} m)")
    print(f"         3 重覆盖 => |Q| >= {b['three_cover_lower_bound']}")
    print(f"         conv(Q) 必须包含 Ω（外圈半径 >= 1800 m）")

    # 控制组：25 点已知网
    base25 = ring_net(16, 1840.0, 8, 990.0, origin=True)
    s25 = certify_matrix(X_opt, base25)
    print(f"\n[控制组] 已知 25 点网：overhang={s25[0]:.6f}, 未覆盖样本={s25[1]}, "
          f"最小 1000m 内点数={s25[2]}, 最大角间隙={s25[3]:.4f}°")

    results = []
    print(f"\n{'点数m':>6} {'最优overhang':>13} {'未覆盖(粗)':>10} {'未覆盖(细)':>11} "
          f"{'覆盖率(细)':>10} {'凸包独立复核':>12} {'评估次数':>9}  判定")
    for m in [24, 23, 22, 21, 20, 18]:
        Q, s, ne, sv = local_search(m, X_opt, X_fine, rng)
        coarse = certify_matrix(X_opt, Q)
        fine = sv if sv is not None else certify_matrix(X_fine, Q)
        hull_unc = None
        if fine[1] == 0:
            hull_unc, _, _ = verify_exact_hull(Q)
        feasible = bool(fine[1] == 0 and (hull_unc == 0))
        results.append({
            "m": m,
            "best_overhang_coarse": s,
            "uncovered_coarse": coarse[1],
            "uncovered_fine": fine[1],
            "covered_fraction_fine": fine[0] if isinstance(fine[0], float) else None,
            "fine_n_samples": fine[3] if False else int(X_fine.shape[0]),
            "hull_verify_uncovered": hull_unc,
            "n_eval": ne,
            "feasible": feasible,
            "Q": [[round(float(a), 3), round(float(bb), 3)] for a, bb in Q],
        })
        print(f"{m:>6} {s:>13.6f} {coarse[1]:>10} {fine[1]:>11} "
              f"{1 - fine[1] / X_fine.shape[0]:>10.6f} {str(hull_unc):>12} {ne:>9}  "
              f"{'可行' if feasible else '不可行'}")

    feasible_m = [r["m"] for r in results if r["feasible"]]
    payload = {
        "theoretical_bounds": b,
        "control_25pt": {"overhang": s25[0], "uncovered": s25[1],
                         "min_n_in_range": s25[2], "worst_gap_deg": s25[3],
                         "n_samples": int(X_opt.shape[0])},
        "results": results,
        "min_feasible_m_found": min(feasible_m) if feasible_m else None,
        "n_opt_samples": int(X_opt.shape[0]),
        "n_check_samples": int(X_check.shape[0]),
        "n_fine_samples": int(X_fine.shape[0]),
        "search_budget_evals_per_m": 4000,
    }
    with open(os.path.join(OUT_DIR, "route2b_point_budget_results.json"), "w",
              encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 90)
    if payload["min_feasible_m_found"] is not None:
        print(f"搜索结论：精确证书下找到 {payload['min_feasible_m_found']} 点的可行覆盖网 "
              f"（< 25）=> 路线2 在点数上确有收益。")
    else:
        print("搜索结论：在 18–24 点范围内**未找到**任何满足精确证书的 Ω 覆盖网；")
        print("         结合单调性（LB3），这支持'25 点不可减'，但本搜索不是穷尽搜索，")
        print("         因此只能说'未找到更小者'，不能声称已证明下界 25。")
    print(f"结果已写入 {OUT_DIR}")


if __name__ == "__main__":
    main()
