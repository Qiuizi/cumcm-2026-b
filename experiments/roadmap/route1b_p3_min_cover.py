"""
route1b_p3_min_cover.py —— 路线1 的前置问题：P3 的固定搜索网究竟能不能减少？

【不修改 P3/P4 任何文件；不调用官方模拟器；纯几何离线计算】

为什么这是路线1 的前置问题
--------------------------------------------------
P3 用 7 个固定搜索点（半径 999 m，等角分布）。这些点承担两个作用：
  (i) 发现源：对任意源位置 x ∈ Ω 与任意 R >= 1000，只要存在搜索点 q 使 ||q-x|| <= 1000，
      就能听到该源。即 {q} 的 1000 m 圆盘必须 1-覆盖 Ω = B(0,1800)。
  (ii) 为空频道提供"静默即不存在"的覆盖证据：判据与 (i) 完全相同（全向源 + R >= 1000）。
所以"固定搜索网能不能减少"= "用半径 1000 的圆盘 1-覆盖半径 1800 的圆盘，最少要几个圆盘"。
这就是经典的圆盘覆盖数问题；本脚本用数值搜索给出上下界。

与判据无关的硬下界
--------------------------------------------------
对 r = 1800 的边界圆，圆心距原点 d 的 1000 m 圆盘截得弧半角
    beta(d) = arccos((d^2 + 1800^2 - 1000^2) / (2 d * 1800))，
beta 在 d = 1300 处取极大 32.887° => 单个圆盘最多覆盖 65.774° 的边界弧长。
=> 1-覆盖整圆至少需要 ceil(360 / 65.774) = 6 个圆盘。
本脚本进一步做数值优化，检查 6 个圆盘是否真的可行。
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

R_DISK = 1000.0
R_OMEGA = 1800.0


def sample_omega(n_theta, n_r, r_max=R_OMEGA):
    th = np.linspace(0.0, 2.0 * math.pi, n_theta, endpoint=False)
    rs = np.linspace(0.0, r_max, n_r + 1)[1:]
    T, R = np.meshgrid(th, rs)
    return np.stack([(R * np.cos(T)).ravel(), (R * np.sin(T)).ravel()], axis=1)


def uncovered(X, Q, rmin=R_DISK):
    D2 = ((X[:, None, :] - np.asarray(Q)[None, :, :]) ** 2).sum(axis=2)
    return int(np.sum(D2.min(axis=1) > (rmin + 1e-6) ** 2))


def overhang(X, Q, rmin=R_DISK):
    """连续化目标：未覆盖点到最近圆心的距离超出半径的总量（0 <=> 全覆盖）"""
    D = np.sqrt(((X[:, None, :] - np.asarray(Q)[None, :, :]) ** 2).sum(axis=2))
    dmin = D.min(axis=1)
    ex = np.maximum(0.0, dmin - rmin)
    return float(ex.sum())


def arc_bound():
    """
    解析最优（闭式）：c(d) = (d² + R² − r²)/(2Rd) 在 d* = sqrt(R² − r²) 处最小，
    此时 beta_max = arcsin(r/R)。
    R = 1800, r = 1000 => d* = 1496.663 m, beta_max = 33.74899°, 单圆盘最大边界弧长 = 67.49798°。
    """
    R, r = R_OMEGA, R_DISK
    d = math.sqrt(R * R - r * r)
    beta = math.asin(r / R)
    max_arc = 2.0 * beta
    return {
        "max_arc_deg": round(math.degrees(max_arc), 6),
        "argmax_d_m": round(d, 4),
        "max_arc_formula": "2*arcsin(r/R)",
        "one_cover_lower_bound": int(math.ceil(2.0 * math.pi / max_arc)),
        "exact_ratio": round(2.0 * math.pi / max_arc, 5),
    }


def search_min_cover(m, X, rng, seeds, iters=2500, sigma0=200.0):
    best_Q, best_s = None, float("inf")
    for Q0 in seeds:
        Q = np.array(Q0, dtype=float)
        s = overhang(X, Q)
        sigma = sigma0
        stall = 0
        for _ in range(iters):
            i = int(rng.integers(0, m))
            cand = Q.copy()
            cand[i] += rng.normal(0.0, sigma, size=2)
            sc = overhang(X, cand)
            if sc <= s:
                if sc == s:
                    stall += 1
                else:
                    stall = 0
                Q, s = cand, sc
                if s <= 1e-9:
                    break
            else:
                stall += 1
            if stall > 0 and stall % 80 == 0:
                sigma = max(20.0, sigma * 0.7)
        if s < best_s:
            best_Q, best_s = Q.copy(), s
        if best_s <= 1e-9:
            break
    return best_Q, best_s


def main():
    rng = np.random.default_rng(2026)
    X_opt = sample_omega(240, 24)     # 粗集
    X_fine = sample_omega(1440, 240)  # 细集
    b = arc_bound()
    print("=" * 88)
    print("路线1 前置问题：用 1000 m 圆盘 1-覆盖 Ω = B(0,1800) 的最少圆盘数")
    print("=" * 88)
    print(f"[硬下界] 单圆盘最大边界弧长 = {b['max_arc_deg']:.4f}° (最优圆心半径 "
          f"{b['argmax_d_m']:.1f} m) => 至少需要 {b['one_cover_lower_bound']} 个圆盘")

    # 控制组：P3 现行 7 点
    p3 = [(999.0 * math.cos(2 * math.pi * i / 7), 999.0 * math.sin(2 * math.pi * i / 7))
          for i in range(7)]
    print(f"[控制组] P3 现行 7 点 (r=999)：未覆盖采样点 = {uncovered(X_fine, p3)} / "
          f"{len(X_fine)}")

    results = []
    for m in [6, 5]:
        seeds = []
        # 等角环族种子（半径从 999 到 1400 扫描）
        for r in [999.0, 1100.0, 1200.0, 1300.0, 1400.0, 1500.0]:
            for jitter in [0.0, 150.0]:
                q = [(r * math.cos(2 * math.pi * i / m), r * math.sin(2 * math.pi * i / m))
                     for i in range(m)]
                if jitter > 0:
                    q = (np.array(q) + rng.normal(0, jitter, (m, 2))).tolist()
                seeds.append(q)
        Q, s = search_min_cover(m, X_opt, rng, seeds)
        fine_unc = uncovered(X_fine, Q) if s <= 1e-9 else None
        results.append({
            "m": m,
            "best_overhang_coarse": s,
            "uncovered_fine": fine_unc,
            "feasible": bool(s <= 1e-9 and (fine_unc == 0 if fine_unc is not None else False)),
            "Q": [[round(float(a), 2), round(float(bb), 2)] for a, bb in Q],
        })
        print(f"  m={m}: 粗集 overhang={s:.4f}, 细集未覆盖={fine_unc} => "
              f"{'可行' if results[-1]['feasible'] else '未找到可行覆盖'}")

    # 6 点可行时，给出最小外接半径（影响路程）
    payload = {"arc_bound": b, "p3_current_7pt_uncovered": uncovered(X_fine, p3),
               "results": results}
    with open(os.path.join(OUT_DIR, "route1b_p3_min_cover_results.json"), "w",
              encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    feas6 = [r for r in results if r["m"] == 6 and r["feasible"]]
    print("\n" + "=" * 88)
    if feas6:
        Q6 = np.array(feas6[0]["Q"])
        rmax = float(np.linalg.norm(Q6, axis=1).max())
        route6 = None
        print(f"结论：6 个圆盘**可以** 1-覆盖 Ω => P3 固定搜索网可能由 7 点减为 6 点。")
        print(f"      6 点解的最大半径 = {rmax:.1f} m（P3 现行为 999 m）。")
        print(f"      注意：仍需在真实引擎中验证'6 点网是否仍能发现全部源'（本脚本只验证几何覆盖）。")
    else:
        print("结论：6 个圆盘**未找到**可行 1-覆盖 => 在数值搜索范围内 P3 的 7 点网不可减。")
    print(f"结果已写入 {OUT_DIR}")


if __name__ == "__main__":
    main()
