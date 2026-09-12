"""search_p4_nets.py - 用 Delaunay 三角剖分搜索更小的合法覆盖网（离线）"""
import sys, os, math, json, itertools
sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import numpy as np
from scipy.spatial import Delaunay, ConvexHull

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "results", "p4_cover_redesign")
R_MAX, OMEGA_R = 1000.0, 1800.0


def ring(n, r, off_deg):
    a = np.radians(off_deg + 360.0 * np.arange(n) / n)
    return np.stack([r*np.cos(a), r*np.sin(a)], axis=1)


def check(P):
    """返回 (valid, max_delaunay_edge, inradius)"""
    P = np.asarray(P, float)
    try:
        tri = Delaunay(P)
    except Exception:
        return False, None, None
    simp = tri.simplices
    E = P[simp]
    d = np.linalg.norm(E[:, [0,1,2], :] - E[:, [1,2,0], :], axis=2)
    max_edge = float(d.max())
    h = ConvexHull(P)
    eq = h.equations          # [A,B,C] 使 A x + B y + C <= 0
    inr = float(np.min(-eq[:, 2] / np.hypot(eq[:, 0], eq[:, 1])))
    valid = (max_edge <= R_MAX + 1e-9) and (inr >= OMEGA_R - 1e-6)
    return valid, max_edge, inr


def path_len(P, o):
    Q = P[np.asarray(o)]
    return float(np.linalg.norm(np.diff(Q, axis=0), axis=1).sum())


def route(P, restarts=4, seed=0, passes=4):
    P = np.asarray(P, float); n = len(P)
    D = np.linalg.norm(P[:, None, :] - P[None, :, :], axis=2)
    rng = np.random.default_rng(seed)
    bL, bo = 1e18, None
    for s in list(range(n)) + list(rng.integers(0, n, restarts)):
        unv = np.ones(n, bool); unv[s] = False
        o = [int(s)]; cur = int(s)
        while unv.any():
            c = np.where(unv)[0]; nx = int(c[np.argmin(D[cur, c])])
            o.append(nx); unv[nx] = False; cur = nx
        o = np.array(o)
        for _ in range(passes):
            imp = False
            for i in range(n-2):
                j = np.arange(i+2, n); a, b = o[i], o[i+1]; c = o[j]
                dd = np.where(j+1 < n, o[np.minimum(j+1, n-1)], -1)
                old = D[a,b] + np.where(dd >= 0, D[c,dd], 0.0)
                new = D[a,c] + np.where(dd >= 0, D[b,dd], 0.0)
                k = int(np.argmin(new-old))
                if new[k] < old[k]-1e-9:
                    jj = int(j[k]); o[i+1:jj+1] = o[i+1:jj+1][::-1]; imp = True
            if not imp: break
        L = path_len(P, o)
        if L < bL: bL, bo = L, o
    return bL


def build(n1, r1, o1, n2, r2, o2):
    return np.vstack([np.zeros((1,2)), ring(n1, r1, o1), ring(n2, r2, o2)])


def main():
    os.makedirs(OUT, exist_ok=True)
    results = []
    print("=" * 100)
    print("【合法网搜索】O + n1@r1 + n2@r2（Delaunay 边 <= 1000 且凸包内切半径 >= 1800）")
    print("=" * 100)
    cnt = 0
    for n1 in range(3, 11):
        for r1 in np.arange(500, 1001, 25):
            for n2 in range(10, 21):
                for r2 in np.arange(1800, 2101, 25):
                    for o2 in (0.0, 360.0/(2*n2), 360.0/(3*n2)):
                        P = build(n1, float(r1), 0.0, n2, float(r2), float(o2))
                        ok, me, inr = check(P)
                        cnt += 1
                        if ok:
                            results.append({"n1": n1, "r1": float(r1), "n2": n2, "r2": float(r2),
                                            "off2": float(o2), "n_pts": 1+n1+n2,
                                            "max_edge": me, "inradius": inr})
    print(f"  扫描组合数 = {cnt}  可行构型数 = {len(results)}")
    if results:
        ns = sorted(set(r["n_pts"] for r in results))
        print(f"  可行构型的点数分布: {ns}")
        # 对点数最少的若干构型算路线
        results.sort(key=lambda r: (r["n_pts"], r["max_edge"]))
        seen = set()
        top = []
        for r in results:
            k = (r["n1"], r["n2"])
            if k in seen: continue
            seen.add(k); top.append(r)
            if len(top) >= 14: break
        print()
        print(f"  {'点数':>4} {'n1':>3} {'r1':>6} {'n2':>3} {'r2':>6} {'off2':>6} {'max_edge':>9} {'inradius':>9} {'路线 m':>10} {'路线 s':>8}")
        for r in top:
            P = build(r["n1"], r["r1"], 0.0, r["n2"], r["r2"], r["off2"])
            L = route(P)
            r["route_m"] = L
            print(f"  {r['n_pts']:>4} {r['n1']:>3} {r['r1']:6.0f} {r['n2']:>3} {r['r2']:6.0f} {r['off2']:6.2f} "
                  f"{r['max_edge']:9.2f} {r['inradius']:9.2f} {L:10.1f} {L/5:8.1f}")
        best = min(top, key=lambda r: r.get("route_m", 1e18))
        print()
        print(f"  路线最短的可行构型: {best['n_pts']} 点, 路线 {best['route_m']:.1f} m ({best['route_m']/5:.1f} s)")
        base = 17961.20
        print(f"  相对基线 25 点环网 (17961.20 m) 的路线差: {best['route_m']-base:+.1f} m")
    with open(os.path.join(OUT, "net_search.json"), "w", encoding="utf-8") as f:
        json.dump({"n_valid": len(results), "top": results[:60]}, f, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    main()
