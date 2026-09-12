"""p4_cost_budget.py - P4 闭合成本预算（4000 秒目标的可达性判定）"""
import sys, os, json, math
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "results", "p4_cover_redesign")

# 基线实测 (commit 53b664d, 2-opt 关闭)
BASE = {
    "P4H-10src-7210": dict(src=10, absent=10, T=7177.305, L=24546.5, M=357, S=319, F=38, N=10,
                           t_search=3241.25, t_follow=831.58, t_clear=836.48, real=56.1),
    "P4H-13src-7213": dict(src=13, absent=7, T=7904.584, L=28852.9, M=323, S=274, F=60, N=13,
                           t_search=3691.61, t_follow=969.78, t_clear=1109.20, real=98.9),
    "P4H-16src-7216": dict(src=16, absent=4, T=7919.461, L=30692.3, M=218, S=146, F=155, N=16,
                           t_search=2321.21, t_follow=2180.32, t_clear=1636.93, real=109.0),
}
ROUTE_M = 17961.20      # 25 点最优开放路线（Delaunay 搜索证明不存在更小合法网）
ROUTE_S = ROUTE_M / 5.0
N_PTS = 25


def main():
    os.makedirs(OUT, exist_ok=True)
    rep = {"baseline": BASE, "route_m": ROUTE_M, "n_points": N_PTS}
    print("=" * 110)
    print("【P4 闭合成本预算】目标 4000 秒；基线 = 修复提交 53b664d（2-opt 关闭）")
    print("=" * 110)
    print(f"  覆盖网: {N_PTS} 点; 最优开放路线 {ROUTE_M:.2f} m = {ROUTE_S:.2f} s")
    print(f"  Delaunay 三角剖分搜索 72072 组构型: 未发现少于 25 点的合法覆盖网（合法最小点数 = 25）")
    print()

    rows = []
    for cid, d in BASE.items():
        absent_scan_s = d["absent"] * N_PTS * 5.0          # 每个空频道需在覆盖网全部顶点静默
        succ_s = 5.0 * d["N"]                              # 成功清除下界
        found_meas_s = 5.0 * d["M"] - absent_scan_s        # 已发现频道的检测
        service_s = d["L"] / 5.0 - ROUTE_S                 # 接入目标的额外绕行
        # 16 源场景可由 K=16 上限提前结束搜索，纯路线下界对它不适用，单独处理
        early_term = (d["src"] >= 16)
        hard_floor = succ_s + absent_scan_s + (0.0 if early_term else ROUTE_S)
        print(f"  {cid}  (源数 {d['src']}, 空频道 {d['absent']})   基线 T = {d['T']:.3f} s")
        if early_term:
            print(f"    ① 覆盖路线移动          = {ROUTE_S:8.2f} s   [不适用严格下界: K=16 上限提前结束搜索，"
                  f"实际遍历 {d['L']/5 - 0:.0f} s 中的一部分]")
        else:
            print(f"    ① 覆盖路线移动          ≥ {ROUTE_S:8.2f} s   [严格下界: 25 点最优开放路线]")
        print(f"    ② 空频道检测            ≥ {absent_scan_s:8.2f} s   [机制下界: {d['absent']}×{N_PTS}×5s]")
        print(f"    ③ 成功清除              = {succ_s:8.2f} s   [严格下界: 5×N]")
        if early_term:
            print(f"    ④ 硬下界合计(不含路线)  ≥ {hard_floor:8.2f} s   "
                  f"[成功清除 + 空频道检测；该局面由接入目标绕行主导]")
        else:
            print(f"    ④ 三项硬下界合计        ≥ {hard_floor:8.2f} s   " +
                  ("**已 > 4000 s，4000 秒不可达**" if hard_floor > 4000 else "**< 4000 s**"))
        print(f"    ⑤ 切频                  = {d['S']:8.2f} s   [实测/可构造]")
        print(f"    ⑥ 失败清除              = {3*d['F']:8.2f} s   [待验证估计]")
        print(f"    ⑦ 已发现频道检测        ≈ {found_meas_s:8.2f} s   [待验证估计]")
        print(f"    ⑧ 接入目标的额外绕行    ≈ {service_s:8.2f} s   [待验证估计]")
        print(f"    校验: ①+②+③+⑤+⑥+⑦+⑧ = {ROUTE_S+absent_scan_s+succ_s+d['S']+3*d['F']+found_meas_s+service_s:.2f} s "
              f"(基线实测 {d['T']:.2f} s)")
        print(f"    现实耗时 = {d['real']:.1f} s（新增全单元覆盖计划构造的计算开销）")
        print()
        rows.append({"case": cid, "sources": d["src"], "absent": d["absent"], "baseline_T": d["T"],
                     "route_lb_s": ROUTE_S, "absent_scan_lb_s": absent_scan_s, "succ_lb_s": succ_s,
                     "hard_floor_s": hard_floor, "switch_s": d["S"], "fail_clear_s": 3*d["F"],
                     "found_meas_est_s": found_meas_s, "service_detour_est_s": service_s,
                     "reachable_4000": bool(hard_floor <= 4000)})

    print("=" * 110)
    print("【结论】")
    print(f"  10 源场景: 硬下界 {rows[0]['hard_floor_s']:.2f} s > 4000 s  -> 4000 秒不可达")
    print(f"  13 源场景: 硬下界 {rows[1]['hard_floor_s']:.2f} s > 4000 s  -> 4000 秒不可达")
    print(f"  16 源场景: 由 K=16 上限提前结束搜索，硬下界不适用；但该局面被'接入目标绕行'主导")
    print(f"             (基线 T={BASE['P4H-16src-7216']['T']:.2f} s, 其中定位补测 {BASE['P4H-16src-7216']['t_follow']:.1f} s "
          f"+ 清除移动 {BASE['P4H-16src-7216']['t_clear']:.1f} s = {BASE['P4H-16src-7216']['t_follow']+BASE['P4H-16src-7216']['t_clear']:.1f} s)，")
    print(f"             该部分由'保留的局部定位与完整清除计划'决定，本轮不允许改动。")
    print("  因此：在当前'每个空频道都必须用静默测站覆盖整个 Ω'的证书要求下，")
    print("        P4 整局时间无法接近 4000 秒；限制来自覆盖网的几何下界，而不是路线启发式或实现。")
    print("=" * 110)

    rep["rows"] = rows
    with open(os.path.join(OUT, "cost_budget.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
