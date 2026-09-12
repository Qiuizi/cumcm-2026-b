"""p4_radius_sensitivity.py - 覆盖网参数敏感性诊断（同三例、同 2-opt 关闭）

目的：判定 r1 由 999 改为 990 带来的差异是"覆盖结构收益"还是"轨迹分歧"。
对每个 r1 用完全相同的驱动与配置跑 7210/7213/7216 三例，只报告 T/L/M/S/F/N。
"""

import sys, os, json, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.sim_env import SimEnvironment
from src.strategy_engine import StrategyEngine
from src.client_runner import audit_http_action_log
from src import evidence_tracker as et

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "results", "p4_cover_redesign", "sensitivity")
CASES = [("P4H-10src-7210", 10, 7210), ("P4H-13src-7213", 13, 7213), ("P4H-16src-7216", 16, 7216)]
R1_LIST = [float(x) for x in (sys.argv[1:] or ["1000", "980", "999"])]


class D:
    def __init__(s, env, path):
        s.env, s.n, s.path = env, 0, path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
    def _log(s, p, req, res):
        with open(s.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": time.time(), "path": p, "request": req, "response": res},
                               ensure_ascii=False) + "\n")
    def enter(s):
        r = s.env.enter(); s._log("/enter", {"request_id": "e"}, r); return r
    def measure(s, pos, ch):
        s.n += 1
        req = {"request_id": f"m{s.n}", "position": {"x": round(float(pos[0]), 2), "y": round(float(pos[1]), 2)}, "channel": int(ch)}
        r = s.env.measure((float(pos[0]), float(pos[1])), int(ch)); s._log("/measure", req, r); return r
    def clear(s, pos, ch):
        s.n += 1
        req = {"request_id": f"c{s.n}", "position": {"x": round(float(pos[0]), 2), "y": round(float(pos[1]), 2)}, "channel": int(ch)}
        r = s.env.clear((float(pos[0]), float(pos[1])), int(ch)); s._log("/clear", req, r); return r
    def exit(s):
        r = s.env.exit(); s._log("/exit", {"request_id": "x"}, r); return r


def run_with_r1(r1, cid, nsrc, seed):
    orig = et.EvidenceTrackerP4.__init__
    def patched(self, n1=8, _r1=None, n2=16, r2=1840.0):
        orig(self, n1, float(r1), n2, float(r2))
    et.EvidenceTrackerP4.__init__ = patched
    try:
        env = SimEnvironment.generate_random_case(num_sources=nsrc, is_p4=True, seed=seed, dir_ratio=0.5)
        path = os.path.join(OUT, f"r1_{int(r1)}_{cid}.jsonl")
        drv = D(env, path)
        eng = StrategyEngine(driver=drv, is_p4=True, version="C", scan_at_clearance=False,
                             enable_2opt_head=False, enable_adaptive_radial_coverage=False, verbose=False)
        s = eng.execute()
        log = audit_http_action_log(path)
        return {"T": s["virtual_time_s"], "L": round(env.total_distance_m, 1), "M": env.measure_count,
                "S": env.switch_count, "F": env.clear_fail_count, "N": env.clear_succ_count,
                "cleared": s["cleared_count"], "status": s["completion_status"],
                "residual": abs(s["virtual_time_s"] - (env.total_distance_m/5 + 5*env.measure_count
                                + env.switch_count + 3*env.clear_fail_count + 5*env.clear_succ_count))}
    finally:
        et.EvidenceTrackerP4.__init__ = orig


def main():
    os.makedirs(OUT, exist_ok=True)
    rep = {}
    print("=" * 104)
    print("【覆盖网内环半径 r1 敏感性诊断】同三例、同配置、同 2-opt 关闭")
    print("=" * 104)
    print(f"  {'r1':>6} " + " ".join(f"{c[0][4:]:>22}" for c in CASES))
    for r1 in R1_LIST:
        line = f"  {r1:6.0f} "
        rep[str(r1)] = {}
        for cid, nsrc, seed in CASES:
            r = run_with_r1(r1, cid, nsrc, seed)
            rep[str(r1)][cid] = r
            line += (f" T={r['T']:8.2f} L={r['L']:7.0f} M={r['M']:3d} F={r['F']:3d}"[:22] + " ")
        print(line, flush=True)
    print()
    print("  基线(53b664d, r1=999): 7210 T=7177.31 | 7213 T=7904.58 | 7216 T=7919.46")
    means = {}
    for r1 in R1_LIST:
        ts = [rep[str(r1)][c[0]]["T"] for c in CASES]
        means[str(r1)] = sum(ts)/3
        print(f"  r1={r1:.0f}: 三例均值 T = {sum(ts)/3:.2f} s  逐例 {[round(t,2) for t in ts]}")
    vals = list(means.values())
    print(f"\n  r1 取值间三例均值的极差 = {max(vals)-min(vals):.2f} s "
          f"(均值 {sum(vals)/len(vals):.2f} s) -> " +
          ("差异远大于路线变化(约 10 s)，说明主要来自轨迹分歧而非覆盖结构收益"
           if max(vals)-min(vals) > 60 else "差异与路线变化同量级"))
    with open(os.path.join(OUT, "r1_sensitivity.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    main()
