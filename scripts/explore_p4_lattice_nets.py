"""explore_p4_lattice_nets.py - 三角格子补丁网 vs 环状网：证书与路面对比"""
import sys, os, math, json, itertools
sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "results", "p4_cover_redesign")
R_MAX, OMEGA_R = 1000.0, 1800.0


def path_len(P, order):
    Q = P[np.asarray(order)]
    return float(np.linalg.norm(np.diff(Q, axis=0), axis=1).sum())


def best_open_route(P, restarts=10, seed=0, passes=5):
    P = np.asarray(P, float); n = len(P)
    D = np.linalg.norm(P[:, None, :] - P[None, :, :], axis=2)
    rng = np.random.default_rng(seed)
    bL, bo = 1e18, None
    for s in list(range(n)) + list(rng.integers(0, n, restarts)):
        unv = np.ones(n, bool); unv[s] = False
        order = [int(s)]; cur = int(s)
        while unv.any():
            c = np.where(unv)[0]; nx = int(c[np.argmin(D[cur, c])])
            order.append(nx); unv[nx] = False; cur = nx
        order = np.array(order)
        for _ in range(passes):
            imp = False
            for i in range(n - 2):
                j = np.arange(i + 2, n)
                a, b = order[i], order[i + 1]; c = order[j]
                d = np.where(j + 1 < n, order[np.minimum(j + 1, n - 1)], -1)
                old = D[a, b] + np.where(d >= 0, D[c, d], 0.0)
                new = D[a, c] + np.where(d >= 0, D[b, d], 0.0)
                k = int(np.argmin(new - old))
                if new[k] < old[k] - 1e-9:
                    jj = int(j[k]); order[i+1:jj+1] = order[i+1:jj+1][::-1]; imp = True
            if not imp: break
        L = path_len(P, order)
        if L < bL: bL, bo = L, order
    return bL, bo


def hull_idx(P):
    o = np.lexsort((P[:,1], P[:,0]))
    def half(seq):
        h=[]
        for i in seq:
            while len(h)>=2:
                a,b=P[h[-2]],P[h[-1]]
                if (b[0]-a[0])*(P[i][1]-a[1])-(b[1]-a[1])*(P[i][0]-a[0])<=0: h.pop()
                else: break
            h.append(i)
        return h
    lo=half(o); up=half(o[::-1]); return lo[:-1]+up[:-1]


def hex_patch(L):
    """三角格子六边形补丁: 基矢 u=(a,0), v=(a/2, a*sqrt3/2), 取 |i|,|j|,|i+j|<=L"""
    a = 1000.0
    u = np.array([a, 0.0]); v = np.array([a/2, a*math.sqrt(3)/2])
    pts = []
    for i in range(-L, L+1):
        for j in range(-L, L+1):
            if abs(i+j) <= L:
                pts.append(i*u + j*v)
    return np.array(pts)


def patch_tris(pts, a=1000.0):
    """三角格子自然三角剖分：连接距离 ~a 的点对，再三角化（用 scipy 不可用时用贪心三角剖分）"""
    P = np.asarray(pts, float); n = len(P)
    D = np.linalg.norm(P[:,None,:]-P[None,:,:], axis=2)
    edges = set()
    for i in range(n):
        for j in range(i+1, n):
            if D[i,j] <= a*1.05:
                edges.add((i,j))
    # 贪心找三角形：若 i-j, j-k, i-k 均为边，且三点不共线，则构成一个三角形
    adj = {i:set() for i in range(n)}
    for i,j in edges:
        adj[i].add(j); adj[j].add(i)
    tris = []
    for i in range(n):
        for j in sorted(adj[i]):
            if j <= i: continue
            for k in sorted(adj[i] & adj[j]):
                if k <= j: continue
                ar = abs((P[j][0]-P[i][0])*(P[k][1]-P[i][1])-(P[k][0]-P[i][0])*(P[j][1]-P[i][1]))/2
                if ar > 1e-6:
                    tris.append((i,j,k))
    return tris


def coverage_check(P, tris):
    P = np.asarray(P, float)
    max_edge = max(float(np.linalg.norm(P[a]-P[b])) for t in tris for a,b in itertools.combinations(t,2))
    h = hull_idx(P)
    inr = 1e18
    for i in range(len(h)):
        a,b = P[h[i]], P[h[(i+1)%len(h)]]
        ab = b-a
        inr = min(inr, float(abs(ab[0]*(-a[1])-ab[1]*(-a[0]))/(np.linalg.norm(ab)+1e-12)))
    at = sum(abs((P[t[1]][0]-P[t[0]][0])*(P[t[2]][1]-P[t[0]][1])-(P[t[2]][0]-P[t[0]][0])*(P[t[1]][1]-P[t[0]][1]))/2 for t in tris)
    ap = 0.0
    for i in range(len(h)):
        a,b = P[h[i]], P[h[(i+1)%len(h)]]
        ap += a[0]*b[1]-b[0]*a[1]
    ap = abs(ap)/2
    return {"max_edge": max_edge, "inradius": inr, "area_tri": at, "area_poly": ap,
            "tiles": abs(at-ap) <= max(1.0, 1e-9*ap), "covers": inr >= OMEGA_R-1e-6,
            "valid": bool(max_edge <= R_MAX+1e-9 and inr >= OMEGA_R-1e-6 and abs(at-ap) <= max(1.0,1e-9*ap))}


def main():
    os.makedirs(OUT, exist_ok=True)
    rep = {}
    print("=" * 104)
    print("【三角格子六边形补丁网 (基矢间距 1000m)】")
    print("=" * 104)
    print(f"  {'L':>2} {'点数':>5} {'max_edge':>9} {'inradius':>9} {'tiles':>6} {'covers Ω':>9} {'路线 m':>10} {'路线 s':>9}")
    rows = []
    for L in (1, 2, 3, 4):
        P = hex_patch(L)
        tris = patch_tris(P)
        c = coverage_check(P, tris)
        Lr, _ = best_open_route(P)
        rows.append({"L": L, "n": len(P), **c, "route_m": Lr})
        print(f"  {L:>2} {len(P):>5} {c['max_edge']:9.2f} {c['inradius']:9.2f} {str(c['tiles']):>6} "
              f"{str(c['covers']):>9} {Lr:10.1f} {Lr/5:9.1f}")

    print()
    print("=" * 104)
    print("【成本模型对比：覆盖成本 = 路线/5 + 5×(A×n + f)  (A=空频道数, f=已发现频道检测次数≈107)】")
    print("=" * 104)
    ring = {"label": "环状网 25 点 (基线)", "n": 25, "route_m": 17961.20}
    print(f"  {'组织方式':<26} {'点数':>5} {'路线s':>8} {'A=4':>9} {'A=7':>9} {'A=10':>9}")
    allc = [ring] + [{"label": f"六边形补丁 L={r['L']}", "n": r["n"], "route_m": r["route_m"], "valid": r["valid"]} for r in rows]
    for c in allc:
        n = c["n"]; L = c["route_m"]
        cells = []
        for A in (4, 7, 10):
            T = L/5 + 5*(A*n + 107) + 280 + 114 + 50
            cells.append(T)
        c["T_by_A"] = {str(A): cells[i] for i, A in enumerate((4,7,10))}
        tag = "" if c.get("valid", True) else "  [证书无效: 未覆盖Ω]"
        print(f"  {c['label']:<26} {n:>5} {L/5:8.1f} " + " ".join(f"{v:9.1f}" for v in cells) + tag)

    rep["hex_patches"] = rows
    rep["cost_model"] = allc
    with open(os.path.join(OUT, "lattice_net_exploration.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[written] {os.path.relpath(os.path.join(OUT,'lattice_net_exploration.json'), ROOT)}")


if __name__ == "__main__":
    main()
