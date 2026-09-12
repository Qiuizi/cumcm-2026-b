"""explore_p4_cover_cost.py - P4 覆盖组织的成本空间探索（离线，向量化，快）"""
import sys, os, math, json, itertools
sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "results", "p4_cover_redesign")
R_MAX = 1000.0
OMEGA_R = 1800.0


def ring(n, r, off=0.0):
    a = np.radians(off + 360.0 * np.arange(n) / n)
    return np.stack([r * np.cos(a), r * np.sin(a)], axis=1)


def path_len(P, order):
    Q = P[np.asarray(order)]
    return float(np.linalg.norm(np.diff(Q, axis=0), axis=1).sum())


def best_open_route(P, restarts=12, seed=0, two_opt_passes=6):
    P = np.asarray(P, dtype=float)
    n = len(P)
    D = np.linalg.norm(P[:, None, :] - P[None, :, :], axis=2)
    rng = np.random.default_rng(seed)
    best_L, best_o = 1e18, None
    for s in list(range(n)) + list(rng.integers(0, n, restarts).tolist()):
        unv = np.ones(n, bool); unv[s] = False
        order = [s]; cur = s
        while unv.any():
            cand = np.where(unv)[0]
            nxt = int(cand[np.argmin(D[cur, cand])])
            order.append(nxt); unv[nxt] = False; cur = nxt
        order = np.array(order)
        for _ in range(two_opt_passes):
            improved = False
            for i in range(n - 2):
                j = np.arange(i + 2, n)
                if len(j) == 0:
                    continue
                a, b = order[i], order[i + 1]
                c = order[j]
                d = np.where(j + 1 < n, order[np.minimum(j + 1, n - 1)], -1)
                old = D[a, b] + np.where(d >= 0, D[c, d], 0.0)
                new = D[a, c] + np.where(d >= 0, D[b, d], 0.0)
                k = np.argmin(new - old)
                if new[k] < old[k] - 1e-9:
                    jj = int(j[k])
                    order[i + 1:jj + 1] = order[i + 1:jj + 1][::-1]
                    improved = True
            if not improved:
                break
        L = path_len(P, order)
        if L < best_L:
            best_L, best_o = L, order
    return best_L, best_o


def convex_hull_idx(P):
    order = np.lexsort((P[:, 1], P[:, 0]))
    def half(seq):
        h = []
        for i in seq:
            while len(h) >= 2:
                o, a = P[h[-2]], P[h[-1]]
                if (a[0]-o[0])*(P[i][1]-o[1]) - (a[1]-o[1])*(P[i][0]-o[0]) <= 0:
                    h.pop()
                else:
                    break
            h.append(i)
        return h
    lower = half(order); upper = half(order[::-1])
    return lower[:-1] + upper[:-1]


def check_triangulation(P, tris, omega_r=OMEGA_R):
    P = np.asarray(P, dtype=float)
    max_edge = 0.0
    for t in tris:
        for a, b in itertools.combinations(t, 2):
            max_edge = max(max_edge, float(np.linalg.norm(P[a] - P[b])))
    hull = convex_hull_idx(P)
    inradius = 1e18
    for i in range(len(hull)):
        a, b = P[hull[i]], P[hull[(i + 1) % len(hull)]]
        ab = b - a
        inradius = min(inradius, float(abs(ab[0] * (-a[1]) - ab[1] * (-a[0])) / (np.linalg.norm(ab) + 1e-12)))
    area_tri = 0.0
    for t in tris:
        a, b, c = P[t[0]], P[t[1]], P[t[2]]
        area_tri += abs((b[0]-a[0])*(c[1]-a[1]) - (c[0]-a[0])*(b[1]-a[1])) / 2.0
    area_poly = 0.0
    for i in range(len(hull)):
        a, b = P[hull[i]], P[hull[(i+1) % len(hull)]]
        area_poly += a[0]*b[1] - b[0]*a[1]
    area_poly = abs(area_poly) / 2.0
    return {"max_edge": max_edge, "inradius": inradius, "tiles": abs(area_tri-area_poly) <= max(1.0, 1e-9*area_poly),
            "covers": inradius >= omega_r - 1e-6,
            "valid": bool(max_edge <= R_MAX + 1e-9 and inradius >= omega_r - 1e-6
                          and abs(area_tri-area_poly) <= max(1.0, 1e-9*area_poly))}


def two_ring(n1, r1, n2, r2, off2=0.0):
    P = np.vstack([np.zeros((1, 2)), ring(n1, r1), ring(n2, r2, off2)])
    tris = []
    for i in range(n1):
        a, a2 = 1+i, 1+((i+1) % n1)
        b0 = 1+n1+((2*i) % n2); b1 = 1+n1+((2*i+1) % n2); b2 = 1+n1+((2*i+2) % n2)
        tris += [(0, a, a2), (a, b0, b1), (a, b1, a2), (a2, b1, b2)]
    return P, tris


def main():
    os.makedirs(OUT, exist_ok=True)
    rep = {}
    print("=" * 108)
    print("【A. 基线 25 点网（O + 8@999 + 16@1840）】")
    print("=" * 108)
    Pb, Tb = two_ring(8, 999.0, 16, 1840.0)
    cb = check_triangulation(Pb, Tb)
    print(f"  证书校验: valid={cb['valid']} max_edge={cb['max_edge']:.3f} inradius={cb['inradius']:.2f} "
          f"tiles={cb['tiles']} covers_Omega={cb['covers']}")
    Lb, ob = best_open_route(Pb)
    print(f"  引擎启发式 17961.20 m | 本离线最优开放路线 = {Lb:.2f} m ({Lb/5:.2f} s)")
    rep["baseline"] = {"route_m": Lb, "check": cb}

    print()
    print("=" * 108)
    print("【B. 两环对齐族可行性（O + n1@r1 + 2n1@r2，扇面三角剖分）】")
    print("=" * 108)
    feas = []
    for n1 in range(5, 13):
        n2 = 2 * n1
        cnt = 0; best_local = None
        for r1 in np.arange(600, 1001, 10):
            for r2 in np.arange(1820, 2011, 5):
                P, T = two_ring(n1, float(r1), n2, float(r2))
                c = check_triangulation(P, T)
                if c["valid"]:
                    cnt += 1
                    if best_local is None or r2 < best_local[1]:
                        best_local = (float(r1), float(r2))
        print(f"  n1={n1:2d} n2={n2:2d} 总点数={1+n1+n2:2d}  可行(r1,r2)组合数={cnt:4d}  "
              f"最小r2可行点={'r1=%.0f,r2=%.0f' % best_local if best_local else '—'}")
        if best_local:
            feas.append({"n1": n1, "n2": n2, "n_pts": 1+n1+n2, "r1": best_local[0], "r2": best_local[1]})
    rep["two_ring_feasible"] = feas

    print()
    print("=" * 108)
    print("【C. 可行族中的路面对比（挑点数最少与路线最短者）】")
    print("=" * 108)
    cand = []
    for f in feas:
        P, T = two_ring(f["n1"], f["r1"], f["n2"], f["r2"])
        L, _ = best_open_route(P, restarts=8)
        cand.append({**f, "route_m": L, "route_s": L/5})
        print(f"  {f['n_pts']:2d} 点 (n1={f['n1']},n2={f['n2']}, r1={f['r1']:.0f}, r2={f['r2']:.0f}): "
              f"路线 {L:9.2f} m = {L/5:8.2f} s   [基线 {Lb:.1f} m, 差 {L-Lb:+.1f} m]")
    rep["two_ring_routes"] = cand

    with open(os.path.join(OUT, "cover_cost_exploration.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(f"\n[written] {os.path.relpath(os.path.join(OUT,'cover_cost_exploration.json'), ROOT)}")


if __name__ == "__main__":
    main()
